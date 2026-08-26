#!/usr/bin/env python3
"""SPPV-3 OOS 일봉 cache 일 1회 자동 수집 배치 wrapper — read-only 연구용.

``docs/40_action_plans/sppv3_oos_daily_batch_design_2026-08-25.md``와
``docs/10_signal_research_sppv/[DESIGN] signal_predictive_power_validation.md``
§45가 정한 아키텍처를 코드로 구현한다. 이 wrapper 자체는 신호 계산·
Go/Watch/Hold/No-Go 판정·정책 반영을 전혀 수행하지 않는다 — 오직 (1)
거래일·시간 가드를 확인하고, (2) 이미 완료된 날짜면 skip하고, (3) 기존
``build_sppv3_oos_bar_cache.py`` 수집기를 lock 아래에서 1회 실행하고,
(4) 수집이 성공(``ready_for_oos=true``)한 경우에만 기존
``measure_sppv3_oos_candidate_performance.py`` 분석기를 read-only로
1회 실행하고, (5) 민감정보 없는 JSON 요약 로그 1건을 남기는 것까지만
한다.

허용된 KIS 호출은 정확히 둘뿐이다.

1. ``inquire_daily_itemchartprice``(historical daily bar, read-only) —
   OOS 일봉 수집.
2. KIS 076 국내휴장일조회(``KisHolidayProvider``/``KISHolidayClient``) —
   거래일/휴장일 판정.

**2026-08-25 초판 설계는 ``KIS_LIVE_INFO_ENABLED=false``를 고정
배선해 076을 아예 호출하지 않고 항상 ``FallbackSessionProvider``
(주말 heuristic)로 대체하는 방식이었다 — 이후 이 방식은 평일
공휴일을 정확히 걸러내지 못한다는 문제로 폐기했다(§45.7 정정,
§47.1).** 지금은 ``build_authoritative_holiday_provider()``가 076
API를 직접 호출해 거래일을 판정한다. 076 인증 실패·timeout 등
어떤 이유로든 거래일을 확정하지 못하면 **weekday heuristic으로
넘어가지 않고** ``skip_market_calendar_unavailable``로 안전하게
종료하며, 이 경우 일봉 수집기(``collector_main``)는 호출조차 되지
않는다. 계좌·주문·잔고·체결 API 호출, DB 연결·write, `.env` 수정,
컨테이너 재기동은 이 wrapper 어디에서도 하지 않는다.

cache immutability
-------------------
같은 KST 날짜의 cache 디렉터리(``logs/_bars_cache_core87_3y_<날짜>``)에
이미 ``ready_for_oos=true`` manifest가 있으면 즉시 skip한다(KIS 재호출
방지, 중복 실행 방지). 실패·불완전한 cache(manifest 없음 또는
``ready_for_oos=false``)는 재시도를 허용하되, **이전 성공 cache나 base
cache(``logs/_bars_cache_core87_3y_2026-07-14``)는 이 wrapper의 어떤
경로로도 건드리지 않는다** — 그 불변성은 기존 ``build_sppv3_oos_bar_
cache.py``가 이미 보장한다(§42/§43).

lock/idempotency
-----------------
파일 기반 ``flock``(exclusive, non-blocking)을 사용한다. flock은
프로세스가 죽거나 컨테이너가 강제 종료돼도 커널이 자동으로 해제하므로,
전통적인 PID 파일 방식과 달리 "stale lock"이 발생할 수 없다 — 별도의
staleness 판정 로직이 필요 없다. 같은 시각 두 실행이 겹치면 나중에
lock을 시도한 쪽은 실패로 취급하지 않고 ``skip_lock_held``로 정상
종료한다(exit 0) — 동시 실행 자체가 이례적 상황이 아니라 방어적으로
예상된 상황이기 때문이다.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import fcntl
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Awaitable, Callable

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
if os.path.join(_REPO_ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("run_sppv3_oos_batch")

KST = timezone(timedelta(hours=9))

# §45.1/45.6 — 21:03 KST 1회 관찰(2026-08-25)에서 88/88 종목 당일 bar 확보를
# 확인했다. 반복 검증 전까지는 이 상수를 실행 결과를 보고 낮추지 않는다.
EARLIEST_RUN_TIME_KST = dtime(21, 0)
DEFAULT_TIMEOUT_SECONDS = 1800  # 30분 — 88종목 순차 수집의 보수적 상한
CACHE_DIR_PREFIX = "_bars_cache_core87_3y_"
LOCK_FILE_RELATIVE_PATH = os.path.join("logs", ".sppv3_oos_batch.lock")
ANALYSIS_RUN_LOG_RELATIVE_DIR = os.path.join("logs", "_sppv3_oos_batch_runs")

# 이 wrapper가 절대 참조해서는 안 되는 식별자들 — 정적 회귀 테스트가
# 이 파일 자신의 소스를 읽어 아래 목록이 등장하지 않는지 검사한다.
FORBIDDEN_SOURCE_SUBSTRINGS: tuple[str, ...] = (
    "_build_kis_adapter",
    "place_order",
    "inquire_balance",
    "DATABASE_URL",
    "DATABASE_HOST",
    "asyncpg",
)


# ── 순수 함수(DB/네트워크 미사용, 단위 테스트 대상) ─────────────────────────


def is_time_gate_open(now_kst: datetime, earliest: dtime = EARLIEST_RUN_TIME_KST) -> bool:
    """``now_kst``의 시각이 ``earliest`` 이상이면 실행 허용."""
    return now_kst.time() >= earliest


@dataclass(frozen=True, slots=True)
class CacheDirState:
    exists: bool
    manifest_exists: bool
    ready_for_oos: bool | None  # None = manifest 없음 또는 파싱 불가


def inspect_cache_dir_state(cache_dir: str) -> CacheDirState:
    """오늘 날짜 cache 디렉터리의 현재 상태를 읽기 전용으로 조사한다."""
    if not os.path.isdir(cache_dir):
        return CacheDirState(exists=False, manifest_exists=False, ready_for_oos=None)
    manifest_path = os.path.join(cache_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        return CacheDirState(exists=True, manifest_exists=False, ready_for_oos=None)
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError):
        return CacheDirState(exists=True, manifest_exists=True, ready_for_oos=None)
    return CacheDirState(exists=True, manifest_exists=True, ready_for_oos=bool(manifest.get("ready_for_oos")))


class MarketCalendarUnavailableError(RuntimeError):
    """076 국내휴장일조회로 거래일을 확정할 수 없을 때 발생.

    이 예외를 받은 호출자는 **weekday heuristic으로 넘어가지 않는다** —
    ``skip_market_calendar_unavailable``로 안전하게 종료하고 일봉 수집을
    호출하지 않는다.
    """


async def build_authoritative_holiday_provider():
    """076 국내휴장일조회 기반 ``KisHolidayProvider``를 직접 구성한다.

    ``agent_trading.services.market_session.create_session_provider()``와
    달리 자격증명이 없거나 ``KIS_LIVE_INFO_ENABLED``가 꺼져 있을 때
    ``FallbackSessionProvider``(주말 heuristic)로 자동 강등하지
    **않는다** — 대신 ``MarketCalendarUnavailableError``를 던진다.
    이 배치가 실제로 호출을 허용하는 두 KIS API(historical daily bar,
    076 국내휴장일조회) 중 하나라도 확정적으로 쓸 수 없으면, 거래일
    판정 자체를 내리지 않고 호출자가 안전하게 skip하도록 강제하기
    위함이다.
    """
    enabled = os.getenv("KIS_LIVE_INFO_ENABLED", "false").strip().lower() == "true"
    if not enabled:
        raise MarketCalendarUnavailableError(
            "KIS_LIVE_INFO_ENABLED=false — 이 배치는 weekday fallback을 쓰지 않으므로 "
            "076 국내휴장일조회가 비활성화된 상태에서는 거래일을 판정할 수 없다"
        )

    app_key = os.getenv("KIS_LIVE_INFO_APP_KEY", "").strip()
    app_secret = os.getenv("KIS_LIVE_INFO_APP_SECRET", "").strip()
    if not app_key or not app_secret:
        raise MarketCalendarUnavailableError(
            "KIS_LIVE_INFO_APP_KEY/KIS_LIVE_INFO_APP_SECRET 미설정 — 076 조회 불가"
        )
    base_url = os.getenv("KIS_LIVE_INFO_BASE_URL", "").strip() or "https://openapi.koreainvestment.com:9443"
    cache_enabled = os.getenv("KIS_DISCLOSURE_TOKEN_CACHE_ENABLED", "true").strip().lower() == "true"
    cache_path = os.getenv("KIS_DISCLOSURE_TOKEN_CACHE_PATH", ".cache/kis_disclosure_token.json").strip()

    from agent_trading.brokers.koreainvestment.holiday_client import KISHolidayClient
    from agent_trading.services.market_session import KisHolidayProvider

    client = KISHolidayClient(
        app_key=app_key,
        app_secret=app_secret,
        base_url=base_url,
        enable_token_cache=cache_enabled,
        token_cache_path=cache_path,
        share_rest_access_token_cache=True,
    )
    return KisHolidayProvider(holiday_client=client)


def decide_batch_action(*, is_trading_day: bool, cache_state: CacheDirState) -> tuple[str, str]:
    """(action, reason) — 순수 판단 함수. I/O를 전혀 수행하지 않는다.

    action은 ``skip_non_trading_day`` / ``skip_already_ready`` /
    ``collect``(신규 또는 실패분 재시도, 둘 다 같은 수집 경로를 탄다) 중
    하나다.
    """
    if not is_trading_day:
        return "skip_non_trading_day", "휴장일 — 수집 skip"
    if cache_state.ready_for_oos is True:
        return "skip_already_ready", "이미 ready_for_oos=true인 cache 존재 — 중복 실행 skip"
    if cache_state.exists and cache_state.manifest_exists and cache_state.ready_for_oos is False:
        return "collect", "이전 실행이 ready_for_oos=false로 끝남 — 재시도"
    if cache_state.exists and not cache_state.manifest_exists:
        return "collect", "이전 실행이 manifest 없이 중단됨 — 재시도"
    return "collect", "신규 수집"


class LockAcquisitionError(RuntimeError):
    """다른 실행이 이미 lock을 보유 중일 때 발생."""


@contextlib.contextmanager
def acquire_batch_lock(lock_path: str):
    """파일 기반 exclusive non-blocking lock. 프로세스 종료 시 커널이 자동 해제한다."""
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(fd)
        raise LockAcquisitionError(f"다른 실행이 lock을 보유 중입니다: {lock_path}") from exc
    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            logger.warning("lock 해제 중 오류 — 프로세스 종료 시 OS가 자동 해제하므로 안전하게 무시")
        os.close(fd)


def build_batch_summary(
    *,
    run_at_kst_iso: str,
    target_trade_date: str,
    action: str,
    action_reason: str,
    manifest: dict[str, Any] | None,
    analyzer_status_by_candidate: dict[str, str] | None,
    exit_code: int,
) -> dict[str, Any]:
    """민감정보(계좌·API 키·토큰) 없는 구조화 요약을 조립한다(순수 함수)."""
    fetch_failed_symbols: list[str] = []
    fetch_success_count: int | None = None
    universe_symbol_count: int | None = None
    cache_id: str | None = None
    ready_for_oos: bool | None = None
    oos_start_date: str | None = None
    oos_end_date: str | None = None

    if manifest is not None:
        cache_id = manifest.get("cache_id")
        ready_for_oos = manifest.get("ready_for_oos")
        universe_symbol_count = manifest.get("universe_symbol_count")
        window = manifest.get("oos_collection_window") or {}
        oos_start_date = window.get("start_date")
        oos_end_date = window.get("end_date")
        symbols = manifest.get("symbols") or []
        fetch_failed_symbols = sorted(
            s.get("symbol", "") for s in symbols if s.get("fetch_status") != "ok"
        )
        fetch_success_count = sum(1 for s in symbols if s.get("fetch_status") == "ok")

    return {
        "run_at_kst": run_at_kst_iso,
        "target_trade_date": target_trade_date,
        "action": action,
        "action_reason": action_reason,
        "cache_id": cache_id,
        "cache_relative_path": os.path.join("logs", f"{CACHE_DIR_PREFIX}{target_trade_date}"),
        "oos_collection_window": {"start_date": oos_start_date, "end_date": oos_end_date},
        "universe_symbol_count": universe_symbol_count,
        "fetch_success_count": fetch_success_count,
        "fetch_failed_symbols": fetch_failed_symbols,
        "ready_for_oos": ready_for_oos,
        "oos_analysis_run": analyzer_status_by_candidate is not None,
        "oos_analysis_status_by_candidate": analyzer_status_by_candidate,
        "exit_code": exit_code,
    }


# ── I/O 오케스트레이션(단위 테스트는 의존성 주입으로 network/DB 미사용) ─────


async def _run_collector_with_timeout(
    collector_main: Callable[[list[str]], Awaitable[int]], timeout_seconds: int
) -> int:
    try:
        return await asyncio.wait_for(collector_main([]), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        logger.error("수집기 timeout(%d초) — 부분 결과만 존재할 수 있음", timeout_seconds)
        return 1
    except SystemExit as exc:
        logger.error("수집기가 SystemExit(%r)로 중단됨", exc.code)
        return 1
    except Exception as exc:  # noqa: BLE001 - 예외 타입 이름만 안전하게 기록
        logger.error("수집기 실행 중 예외 발생: %s", type(exc).__name__)
        return 1


async def _run_analyzer_and_collect_status(
    analyzer_main: Callable[[list[str]], Awaitable[int]],
    cache_dir: str,
    output_json_path: str,
) -> dict[str, str] | None:
    try:
        await analyzer_main(["--oos-cache-dir", cache_dir, "--output-json", output_json_path])
    except SystemExit as exc:
        logger.error("분석기가 SystemExit(%r)로 중단됨", exc.code)
        return None
    except Exception as exc:  # noqa: BLE001 - 예외 타입 이름만 안전하게 기록
        logger.error("분석기 실행 중 예외 발생: %s", type(exc).__name__)
        return None

    if not os.path.exists(output_json_path):
        return None
    with open(output_json_path, encoding="utf-8") as f:
        result = json.load(f)
    return {
        name: info.get("status", {}).get("status", "UNKNOWN")
        for name, info in result.get("candidates", {}).items()
    }


async def run_batch(
    *,
    now_kst: datetime | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    repo_root: str | None = None,
    session_provider_factory: Callable[[], Awaitable[Any]] | None = None,
    collector_main: Callable[[list[str]], Awaitable[int]] | None = None,
    analyzer_main: Callable[[list[str]], Awaitable[int]] | None = None,
) -> int:
    """배치 전체 오케스트레이션. 실제 실행에서는 인자를 전부 생략한다.

    테스트는 ``repo_root``(임시 디렉터리)와 ``session_provider_factory``/
    ``collector_main``/``analyzer_main``(가짜 구현)을 주입해 DB/네트워크
    없이 전체 흐름을 검증한다.
    """
    now_kst = now_kst or datetime.now(KST)
    repo_root = repo_root or _REPO_ROOT
    target_trade_date = now_kst.strftime("%Y-%m-%d")
    run_at_kst_iso = now_kst.isoformat()

    if not is_time_gate_open(now_kst):
        summary = build_batch_summary(
            run_at_kst_iso=run_at_kst_iso,
            target_trade_date=target_trade_date,
            action="skip_time_gate_not_open",
            action_reason=f"{EARLIEST_RUN_TIME_KST.strftime('%H:%M')} KST 이전 — 실행 대기",
            manifest=None,
            analyzer_status_by_candidate=None,
            exit_code=0,
        )
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    if session_provider_factory is None:
        session_provider_factory = build_authoritative_holiday_provider

    try:
        provider = await session_provider_factory()
        is_trading = await provider.is_trading_day(now_kst.date())
    except MarketCalendarUnavailableError as exc:
        logger.warning("076 국내휴장일조회 비활성화/미설정 — 안전 skip: %s", exc)
        summary = build_batch_summary(
            run_at_kst_iso=run_at_kst_iso,
            target_trade_date=target_trade_date,
            action="skip_market_calendar_unavailable",
            action_reason=str(exc),
            manifest=None,
            analyzer_status_by_candidate=None,
            exit_code=0,
        )
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001 - 076 인증 실패/timeout 등, 절대 weekday fallback으로 넘어가지 않는다
        logger.warning("076 국내휴장일조회 실패(%s) — weekday fallback 없이 안전 skip", type(exc).__name__)
        summary = build_batch_summary(
            run_at_kst_iso=run_at_kst_iso,
            target_trade_date=target_trade_date,
            action="skip_market_calendar_unavailable",
            action_reason=f"076 국내휴장일조회 오류: {type(exc).__name__}",
            manifest=None,
            analyzer_status_by_candidate=None,
            exit_code=0,
        )
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    cache_dir = os.path.join(repo_root, "logs", f"{CACHE_DIR_PREFIX}{target_trade_date}")
    cache_state = inspect_cache_dir_state(cache_dir)
    action, reason = decide_batch_action(is_trading_day=is_trading, cache_state=cache_state)

    if action in ("skip_non_trading_day", "skip_already_ready"):
        manifest = None
        if cache_state.manifest_exists:
            with contextlib.suppress(OSError, json.JSONDecodeError):
                with open(os.path.join(cache_dir, "manifest.json"), encoding="utf-8") as f:
                    manifest = json.load(f)
        summary = build_batch_summary(
            run_at_kst_iso=run_at_kst_iso,
            target_trade_date=target_trade_date,
            action=action,
            action_reason=reason,
            manifest=manifest,
            analyzer_status_by_candidate=None,
            exit_code=0,
        )
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    lock_path = os.path.join(repo_root, LOCK_FILE_RELATIVE_PATH)
    if collector_main is None:
        from scripts.analysis import build_sppv3_oos_bar_cache as _collector_module

        collector_main = _collector_module.main
    if analyzer_main is None:
        from scripts.analysis import measure_sppv3_oos_candidate_performance as _analyzer_module

        analyzer_main = _analyzer_module.main

    try:
        with acquire_batch_lock(lock_path):
            collector_exit = await _run_collector_with_timeout(collector_main, timeout_seconds)
    except LockAcquisitionError as exc:
        logger.warning("%s", exc)
        summary = build_batch_summary(
            run_at_kst_iso=run_at_kst_iso,
            target_trade_date=target_trade_date,
            action="skip_lock_held",
            action_reason=str(exc),
            manifest=None,
            analyzer_status_by_candidate=None,
            exit_code=0,
        )
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    manifest_after: dict[str, Any] | None = None
    manifest_path = os.path.join(cache_dir, "manifest.json")
    if os.path.exists(manifest_path):
        with contextlib.suppress(OSError, json.JSONDecodeError):
            with open(manifest_path, encoding="utf-8") as f:
                manifest_after = json.load(f)

    analyzer_status: dict[str, str] | None = None
    if collector_exit == 0 and manifest_after is not None and manifest_after.get("ready_for_oos") is True:
        run_log_dir = os.path.join(repo_root, ANALYSIS_RUN_LOG_RELATIVE_DIR, target_trade_date)
        os.makedirs(run_log_dir, exist_ok=True)
        output_json_path = os.path.join(run_log_dir, "oos_analysis_result.json")
        analyzer_status = await _run_analyzer_and_collect_status(analyzer_main, cache_dir, output_json_path)

    exit_code = 0 if collector_exit == 0 else 1
    summary = build_batch_summary(
        run_at_kst_iso=run_at_kst_iso,
        target_trade_date=target_trade_date,
        action=action,
        action_reason=reason,
        manifest=manifest_after,
        analyzer_status_by_candidate=analyzer_status,
        exit_code=exit_code,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return exit_code


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "SPPV-3 OOS 일봉 cache 일 1회 자동 수집 배치 wrapper — "
            "거래일/시간 가드, 중복 skip, 수집 성공 후 read-only 분석까지"
        )
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"수집기 전체 timeout(초). 기본 {DEFAULT_TIMEOUT_SECONDS}.",
    )
    args = parser.parse_args(argv)
    return await run_batch(timeout_seconds=args.timeout_seconds)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
