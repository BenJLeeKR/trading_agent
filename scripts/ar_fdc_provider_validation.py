#!/usr/bin/env python3
"""Phase 2: Provider Call Only — Load JSON artifact, call provider, report results.

사용법:
    python -m scripts.ar_fdc_provider_validation

Phase 1 선행 조건:
    python -m scripts.ar_fdc_output_measurement --dump-prompts
    → data/ar_fdc_prompts_030200.json 생성

종료 코드:
    0 — 성공 (일부 성공 포함)
    1 — artifact 로드 실패 / 환경 문제

설계 문서: plans/ar_fdc_provider_2phase_design.md
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

# .env 로드 (provider API key 등)
try:
    from dotenv import load_dotenv
    _dotenv_path = Path(__file__).resolve().parent.parent / ".env"
    if _dotenv_path.exists():
        load_dotenv(_dotenv_path)
except ImportError:
    pass

# 2026-08-27 PR A: 공용 PostgreSQL quota coordinator 경로로 전환하며
# "DB import 없음" 제약을 의도적으로 해제한다(설계 문서 §11/§19 진입점
# #3) — TransactionManager()/PostgresFdcQuotaRepository만 쓰고,
# postgres_runtime()의 전체 RepositoryContainer(migration 실행 포함)는
# 여전히 쓰지 않는다. create_pool()/close_pool()로 이 standalone
# 스크립트가 필요한 최소 DB pool lifecycle만 직접 관리한다(2026-08-27
# 3차 리뷰 보정 — 기존에는 pool을 전혀 초기화하지 않아 reservation
# 전에 "Database pool is not initialised" 오류로 실패했다).
from agent_trading.config.settings import AppSettings
from agent_trading.db.connection import close_pool, create_pool
from agent_trading.db.transaction import TransactionManager
from agent_trading.repositories.postgres.fdc_quota import PostgresFdcQuotaRepository
from agent_trading.services.ai_agents.provider_client import (
    LiveGeminiProviderClient,
    OpenAICompatibleClient,
)
from agent_trading.services.fdc_quota_coordinator import FdcQuotaCoordinator
from scripts.fdc_manual_provider_gate import (
    MarketHoursBlockedError,
    assert_not_market_hours,
    build_manual_call_policy,
    build_manual_run_id,
    call_with_coordinator,
)

SCRIPT_NAME = "ar_fdc_provider_validation"

SEP = "=" * 60
DASH = "-" * 40

ARTIFACT_PATH = Path("data/ar_fdc_prompts_030200.json")
RESULT_PATH = Path("data/ar_fdc_provider_validation_030200.json")
CLIENT_TIMEOUT = 120  # seconds (client-level, 각 호출당)
PROCESS_TIMEOUT = 150  # seconds (process-level, 전체)


def _is_ar_fallback(parsed: Any) -> bool:
    """AR fallback 감지: 모든 field가 default 값인 경우."""
    try:
        return (
            parsed.risk_opinion == "allow"
            and parsed.risk_score == 0.0
            and not parsed.reason_codes
        )
    except AttributeError:
        return True


def _is_fdc_fallback(parsed: Any) -> bool:
    """FDC fallback 감지: 모든 field가 default 값인 경우."""
    try:
        return (
            parsed.decision_type == "HOLD"
            and parsed.confidence == 0.0
        )
    except AttributeError:
        return True


async def _call_ar(
    client: OpenAICompatibleClient,
    user_prompt: str,
    system_prompt: str,
    label: str,
    model_id: str,
) -> dict[str, Any]:
    """AR provider 호출 + fallback 감지 + used_fallback 포함 반환.

    2026-08-27 리뷰 보정: AR live provider 호출은 FDC 공용 13 RPM
    coordinator의 대상이 **아니다**(production에서도 ``AIRiskAgent.
    run()``이 ``acquire_permit``을 쓰지 않음 — §1 배경 문서가 "FDC
    provider(Gemini) 호출"만 quota 대상으로 명시). 따라서 여기서는
    coordinator를 거치지 않는 일반 ``OpenAICompatibleClient``를 그대로
    쓴다 — FDC 전용 ``LiveGeminiProviderClient``를 억지로 재사용하지
    않는다(그 클래스의 ``generate_structured()``는 애초에 차단돼
    있어 호출해도 실패한다).
    """
    from agent_trading.services.ai_agents.schemas import AIRiskOutput

    start = time.monotonic()
    try:
        response = await client.generate_structured(
            model_id=model_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=AIRiskOutput,
            temperature=0.0,
        )
        elapsed = time.monotonic() - start
        result = response.parsed
        is_fallback = _is_ar_fallback(result)

        return {
            "run": label,
            "success": True,
            "used_fallback": is_fallback,
            "duration_seconds": round(elapsed, 1),
            "parsed_output": {
                "risk_opinion": result.risk_opinion,
                "risk_score": result.risk_score,
                "reason_codes": list(result.reason_codes) if result.reason_codes else [],
                "reasoning": result.summary or "",
            },
            "raw_response_preview": (response.raw_content or "")[:500],
        }
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - start
        return {
            "run": label,
            "success": False,
            "used_fallback": True,
            "duration_seconds": round(elapsed, 1),
            "error": "timeout",
            "parsed_output": None,
        }
    except Exception as e:
        elapsed = time.monotonic() - start
        return {
            "run": label,
            "success": False,
            "used_fallback": True,
            "duration_seconds": round(elapsed, 1),
            "error": str(e),
            "parsed_output": None,
        }


async def _call_fdc(
    client: LiveGeminiProviderClient,
    coordinator: FdcQuotaCoordinator,
    manual_run_id: str,
    user_prompt: str,
    system_prompt: str,
    label: str,
    model_id: str,
) -> dict[str, Any]:
    """FDC provider 호출(공용 quota coordinator 경유) + fallback 감지 +
    used_fallback 포함 반환."""
    from agent_trading.services.ai_agents.schemas import FinalDecisionComposerOutput

    start = time.monotonic()
    try:
        response = await call_with_coordinator(
            coordinator=coordinator,
            client=client,
            caller_id=f"manual:{SCRIPT_NAME}",
            manual_run_id=manual_run_id,
            model_id=model_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=FinalDecisionComposerOutput,
            temperature=0.0,
        )
        elapsed = time.monotonic() - start
        result = response.parsed
        is_fallback = _is_fdc_fallback(result)

        return {
            "run": label,
            "success": True,
            "used_fallback": is_fallback,
            "duration_seconds": round(elapsed, 1),
            "parsed_output": {
                "decision_type": result.decision_type,
                "confidence": result.confidence,
                "reasoning": result.summary or "",
            },
            "raw_response_preview": (response.raw_content or "")[:500],
        }
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - start
        return {
            "run": label,
            "success": False,
            "used_fallback": True,
            "duration_seconds": round(elapsed, 1),
            "error": "timeout",
            "parsed_output": None,
        }
    except Exception as e:
        elapsed = time.monotonic() - start
        return {
            "run": label,
            "success": False,
            "used_fallback": True,
            "duration_seconds": round(elapsed, 1),
            "error": str(e),
            "parsed_output": None,
        }


def _classify_conclusion(calls: list[dict[str, Any]]) -> str:
    """Phase 2 최종 결론 분류.

    Returns:
        "improvement_signal" | "mixed_signal" | "inconclusive"
    """
    successful = [c for c in calls if c.get("success")]
    genuine = [c for c in successful if not c.get("used_fallback", True)]
    fallback_only = [c for c in successful if c.get("used_fallback", True)]
    failed = [c for c in calls if not c.get("success")]

    # 자동 inconclusive 조건
    if len(genuine) == 0:
        return "inconclusive"  # 모든 성공이 fallback 또는 전부 실패
    if len(failed) == len(calls):
        return "inconclusive"  # 전부 timeout/실패

    # OLD/NEW 쌍 비교 가능 여부
    ar_calls = [c for c in genuine if "ar" in c.get("run", "")]
    fdc_calls = [c for c in genuine if "fdc" in c.get("run", "")]
    ar_old = [c for c in ar_calls if "old" in c.get("run", "")]
    ar_new = [c for c in ar_calls if "new" in c.get("run", "")]
    fdc_old = [c for c in fdc_calls if "old" in c.get("run", "")]
    fdc_new = [c for c in fdc_calls if "new" in c.get("run", "")]

    ar_comparable = len(ar_old) > 0 and len(ar_new) > 0
    fdc_comparable = len(fdc_old) > 0 and len(fdc_new) > 0

    if not ar_comparable and not fdc_comparable:
        return "inconclusive"  # 비교 불가

    # improvement signal 탐지
    ar_signal = False
    fdc_signal = False

    if ar_comparable:
        old_opinion = ar_old[0].get("parsed_output", {}).get("risk_opinion", "")
        new_opinion = ar_new[0].get("parsed_output", {}).get("risk_opinion", "")
        old_score = ar_old[0].get("parsed_output", {}).get("risk_score", 0.0)
        new_score = ar_new[0].get("parsed_output", {}).get("risk_score", 0.0)
        old_codes = ar_old[0].get("parsed_output", {}).get("reason_codes", [])
        new_codes = ar_new[0].get("parsed_output", {}).get("reason_codes", [])

        if old_opinion != new_opinion or abs(old_score - new_score) > 0.05:
            ar_signal = True
        if len(new_codes) > len(old_codes):
            ar_signal = True

    if fdc_comparable:
        old_decision = fdc_old[0].get("parsed_output", {}).get("decision_type", "")
        new_decision = fdc_new[0].get("parsed_output", {}).get("decision_type", "")
        old_conf = fdc_old[0].get("parsed_output", {}).get("confidence", 0.0)
        new_conf = fdc_new[0].get("parsed_output", {}).get("confidence", 0.0)

        if old_decision != new_decision or abs(old_conf - new_conf) > 0.05:
            fdc_signal = True

    if ar_signal and fdc_signal:
        return "improvement_signal"
    elif ar_signal or fdc_signal:
        return "mixed_signal"
    else:
        return "inconclusive"


def _save_results(
    calls: list[dict[str, Any]],
    artifact: dict[str, Any],
    total_duration: float,
) -> str:
    """Save Phase 2 results to data/ar_fdc_provider_validation_030200.json."""
    conclusion = _classify_conclusion(calls)
    successful = sum(1 for c in calls if c.get("success"))
    failed = sum(1 for c in calls if not c.get("success"))
    fallback_count = sum(1 for c in calls if c.get("used_fallback", False))

    result: dict[str, Any] = {
        "meta": {
            "run_ts_utc": artifact.get("meta", {}).get("measured_at_utc", ""),
            "symbol": artifact.get("meta", {}).get("symbol", "030200"),
            "phase1_artifact": str(ARTIFACT_PATH),
            "model_id": artifact.get("meta", {}).get("model_id", "deepseek-chat"),
            "client_timeout_seconds": CLIENT_TIMEOUT,
            "process_timeout_seconds": PROCESS_TIMEOUT,
            "schema_version": "1.0",
        },
        "calls": calls,
        "summary": {
            "total_calls": len(calls),
            "successful": successful,
            "failed": failed,
            "fallback_count": fallback_count,
            "total_duration_seconds": round(total_duration, 1),
            "conclusion": conclusion,
        },
    }

    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "ar_fdc_provider_validation_030200.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    return str(path)


def _print_results(calls: list[dict[str, Any]], conclusion: str) -> None:
    """Print Phase 2 results to stdout."""
    print(f"\n{SEP}")
    print("  Phase 2: Provider Call Results")
    print(SEP)

    for c in calls:
        label = c.get("run", "?")
        success = c.get("success", False)
        fallback = c.get("used_fallback", True)
        duration = c.get("duration_seconds", 0)
        error = c.get("error")

        status = "✅" if success and not fallback else "⚠️" if success and fallback else "❌"
        print(f"\n  {status} [{label}] ({duration}s)")
        if error:
            print(f"    Error: {error}")
        elif fallback:
            print(f"    Fallback (used_fallback=true)")
        else:
            parsed = c.get("parsed_output", {})
            if "risk_opinion" in parsed:
                print(f"    opinion={parsed['risk_opinion']}, score={parsed['risk_score']}, "
                      f"codes={parsed.get('reason_codes', [])}")
            elif "decision_type" in parsed:
                print(f"    decision_type={parsed['decision_type']}, confidence={parsed['confidence']}")

    print(f"\n{DASH}")
    print(f"  결론: {conclusion}")
    print(DASH)


async def main() -> int:
    """Phase 2: Load JSON artifact, call provider, report results.

    동작:
    1. JSON artifact 로드
    2. 운영 시간(거래일) fail-closed 차단 확인(CLI 사전 검사, 1단계) —
       차단되면 DB pool 초기화·HTTP 전에 즉시 종료
    3. .env에서 DEEPSEEK_API_KEY 로드
    4. DB pool 초기화(create_pool()) — standalone 스크립트라 명시적으로
       필요하다(2026-08-27 3차 리뷰 보정)
    5. 공용 quota coordinator 구성(운영 시간 정책을 2단계 중앙 경계로도
       주입 — coordinator.try_reserve()가 manual: caller를 직접 재확인)
    6. LiveGeminiProviderClient 생성 (coordinator 필수, timeout_seconds=120)
    7. OLD-style AR 1회 → NEW-style AR 1회 (순차, coordinator 미사용)
    8. OLD-style FDC 1회 → NEW-style FDC 1회 (순차, 매 시도마다 reservation)
    9. 결과 출력 + 결과 artifact 저장
    10. provider_client.close() + close_pool()(모든 종료 경로에서)
    """
    # 1. Load artifact
    if not ARTIFACT_PATH.exists():
        print(f"❌ Artifact not found: {ARTIFACT_PATH}")
        print("   Run Phase 1 first: python -m scripts.ar_fdc_output_measurement --dump-prompts")
        return 1

    with open(ARTIFACT_PATH, encoding="utf-8") as f:
        artifact = json.load(f)

    print(f"  ✅ Artifact loaded: {ARTIFACT_PATH}")
    print(f"  Symbol: {artifact.get('meta', {}).get('symbol', '?')}")
    print(f"  Events: {artifact.get('meta', {}).get('event_count', 0)}")

    # 2. 운영 시간(거래일) fail-closed 차단(1단계, CLI 사전 검사) — DB
    # pool 초기화·HTTP 전에 즉시 종료한다.
    try:
        await assert_not_market_hours(script_name=SCRIPT_NAME)
    except MarketHoursBlockedError as exc:
        print(f"❌ {exc}")
        return 1

    # 3. Settings 확인
    settings = AppSettings()
    if not settings.provider_api_key:
        print("❌ provider_api_key is empty. Check .env file.")
        return 1

    print(f"  Provider: {settings.provider_base_url}")
    print(f"  Model:    {settings.provider_model_id}")
    print(f"  Timeout:  {CLIENT_TIMEOUT}s (client) + {PROCESS_TIMEOUT}s (process)")
    print(SEP)

    prompts = artifact.get("prompts", {})
    system_prompts = artifact.get("system_prompts", {})
    model_id = settings.provider_model_id

    calls: list[dict[str, Any]] = []
    start_total = time.monotonic()

    # AR과 FDC는 서로 다른 quota 정책을 따르므로 provider client도
    # 분리한다 — AR은 coordinator 없는 일반 클라이언트, FDC만 coordinator
    # 필수인 LiveGeminiProviderClient(2026-08-27 리뷰 보정).
    ar_client = OpenAICompatibleClient(
        api_key=settings.provider_api_key,
        base_url=settings.provider_base_url,
        timeout_seconds=CLIENT_TIMEOUT,
    )

    # 4. DB pool 초기화(2026-08-27 3차 리뷰 보정) — postgres_runtime()은
    # migration까지 실행하는 무거운 경로라 쓰지 않는다. 이 standalone
    # 스크립트에 필요한 것은 pool 하나뿐이다. 이 지점부터는 반드시
    # close_pool()로 정리한다(모든 종료 경로).
    await create_pool()
    try:
        # 5. repo/coordinator 구성 — ambient transaction은 이 구성 목적
        # 으로만 잠깐 열고 즉시 닫는다(HTTP 호출 동안 열어두지 않는다).
        # PostgresFdcQuotaRepository.try_reserve()/record_attempt_outcome()
        # 는 각자 독립 transaction을 새로 열므로, 이 ambient_tx는 생성자
        # 인자를 채우는 용도 외에는 쓰이지 않는다.
        async with TransactionManager() as ambient_tx:
            repo = PostgresFdcQuotaRepository(ambient_tx)
        coordinator = FdcQuotaCoordinator(
            repo=repo,
            target_rpm=settings.fdc_provider_target_rpm,
            window_seconds=settings.fdc_provider_rate_window_seconds,
            declared_rpm_limit=settings.gemini_provider_declared_rpm_limit,
            # 2단계 중앙 fail-closed 경계 — CLI 사전 검사(2번)와 별개로,
            # coordinator.try_reserve()가 manual: caller를 직접 재확인한다.
            manual_call_policy=build_manual_call_policy(script_name=SCRIPT_NAME),
        )
        fdc_client = LiveGeminiProviderClient(
            coordinator=coordinator,
            api_key=settings.provider_api_key,
            base_url=settings.provider_base_url,
            timeout_seconds=CLIENT_TIMEOUT,
        )
        manual_run_id = build_manual_run_id(script_name=SCRIPT_NAME)

        try:
            # 6. Call provider for each prompt (순차 호출)
            # AR OLD/NEW — coordinator를 거치지 않는다(FDC quota 대상 아님).
            calls.append(await _call_ar(
                ar_client, prompts.get("ar_old_prompt", ""),
                system_prompts.get("ar", ""), "ar-old-1", model_id))

            calls.append(await _call_ar(
                ar_client, prompts.get("ar_new_prompt", ""),
                system_prompts.get("ar", ""), "ar-new-1", model_id))

            # FDC OLD/NEW — 매 HTTP 시도마다 공용 quota reservation을 얻는다.
            calls.append(await _call_fdc(
                fdc_client, coordinator, manual_run_id, prompts.get("fdc_old_prompt", ""),
                system_prompts.get("fdc", ""), "fdc-old-1", model_id))

            calls.append(await _call_fdc(
                fdc_client, coordinator, manual_run_id, prompts.get("fdc_new_prompt", ""),
                system_prompts.get("fdc", ""), "fdc-new-1", model_id))

        except asyncio.TimeoutError:
            print(f"❌ Global timeout ({PROCESS_TIMEOUT}s) exceeded.")
            total_duration = time.monotonic() - start_total
            _save_results(calls, artifact, total_duration)
            return 1
        finally:
            await ar_client.close()
            await fdc_client.close()

        total_duration = time.monotonic() - start_total

        # 7. Classify conclusion
        conclusion = _classify_conclusion(calls)

        # 8. Save results artifact
        result_path = _save_results(calls, artifact, total_duration)
        print(f"\n  ✅ Results saved: {result_path}")

        # 9. Print results
        _print_results(calls, conclusion)

        return 0
    finally:
        await close_pool()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
