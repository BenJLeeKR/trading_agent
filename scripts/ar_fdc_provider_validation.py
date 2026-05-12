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

# DB import 없음! (postgres_runtime, Repository 등 사용 금지)
from agent_trading.config.settings import AppSettings
from agent_trading.services.ai_agents.provider_client import OpenAICompatibleClient

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
    """AR provider 호출 + fallback 감지 + used_fallback 포함 반환."""
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
    client: OpenAICompatibleClient,
    user_prompt: str,
    system_prompt: str,
    label: str,
    model_id: str,
) -> dict[str, Any]:
    """FDC provider 호출 + fallback 감지 + used_fallback 포함 반환."""
    from agent_trading.services.ai_agents.schemas import FinalDecisionComposerOutput

    start = time.monotonic()
    try:
        response = await client.generate_structured(
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
    1. JSON artifact 로드 (DB 연결 없음)
    2. .env에서 DEEPSEEK_API_KEY 로드
    3. OpenAICompatibleClient 생성 (timeout_seconds=120)
    4. OLD-style AR 1회 → NEW-style AR 1회 (순차)
    5. OLD-style FDC 1회 → NEW-style FDC 1회 (순차)
    6. 결과 출력 + 결과 artifact 저장
    7. provider_client.close()
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

    # 2. Init provider client
    settings = AppSettings()
    if not settings.provider_api_key:
        print("❌ provider_api_key is empty. Check .env file.")
        return 1

    print(f"  Provider: {settings.provider_base_url}")
    print(f"  Model:    {settings.provider_model_id}")
    print(f"  Timeout:  {CLIENT_TIMEOUT}s (client) + {PROCESS_TIMEOUT}s (process)")
    print(SEP)

    client = OpenAICompatibleClient(
        api_key=settings.provider_api_key,
        base_url=settings.provider_base_url,
        timeout_seconds=CLIENT_TIMEOUT,
    )

    prompts = artifact.get("prompts", {})
    system_prompts = artifact.get("system_prompts", {})
    model_id = settings.provider_model_id

    calls: list[dict[str, Any]] = []
    start_total = time.monotonic()

    try:
        # 3. Call provider for each prompt (순차 호출)
        # AR OLD
        calls.append(await _call_ar(
            client, prompts.get("ar_old_prompt", ""),
            system_prompts.get("ar", ""), "ar-old-1", model_id))

        # AR NEW
        calls.append(await _call_ar(
            client, prompts.get("ar_new_prompt", ""),
            system_prompts.get("ar", ""), "ar-new-1", model_id))

        # FDC OLD
        calls.append(await _call_fdc(
            client, prompts.get("fdc_old_prompt", ""),
            system_prompts.get("fdc", ""), "fdc-old-1", model_id))

        # FDC NEW
        calls.append(await _call_fdc(
            client, prompts.get("fdc_new_prompt", ""),
            system_prompts.get("fdc", ""), "fdc-new-1", model_id))

    except asyncio.TimeoutError:
        print(f"❌ Global timeout ({PROCESS_TIMEOUT}s) exceeded.")
        total_duration = time.monotonic() - start_total
        _save_results(calls, artifact, total_duration)
        return 1
    finally:
        await client.close()

    total_duration = time.monotonic() - start_total

    # 4. Classify conclusion
    conclusion = _classify_conclusion(calls)

    # 5. Save results artifact
    result_path = _save_results(calls, artifact, total_duration)
    print(f"\n  ✅ Results saved: {result_path}")

    # 6. Print results
    _print_results(calls, conclusion)

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
