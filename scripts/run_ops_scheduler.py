#!/usr/bin/env python3
"""
Operations scheduler — KIS market session aware trading scheduler.

This is the canonical entrypoint for the trading operations scheduler.
It is environment-neutral: the same script works for both paper and live
trading environments, differentiated only by the KIS_ENV setting.

This is a single-process, in-application scheduler for the KIS trading
day. It does not depend on cron/systemd timers for task timing.

The scheduler intentionally reuses the existing operational entrypoints:

* ``run_snapshot_sync_loop.py --max-cycles 1``
* ``run_event_ingestion_loop.py --count 1``
* ``run_decision_loop.py --count 1``
* ``run_post_submit_sync_loop.py --once``

P0 scope is conservative: one process manages timing and safety gates, while
the existing scripts keep broker/API/database behavior unchanged.

Session Gate (P1, 2026-05-16)
==============================
Before each phase transition (pre-market / intraday / EOD), the scheduler
calls ``MarketSessionProvider.is_trading_day()`` to confirm the current
date is an actual KIS trading day:

* ``KisHolidayProvider``: 076 REST API (국내휴장일조회) — **live credential**
  completely separated from paper/live order path.
* ``FallbackSessionProvider``: weekday heuristic when live-info not configured
  or API unavailable.

Dual-provider architecture prevents accidental live credential leakage into
submit/order/balance paths while enabling accurate holiday detection.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

# Session gate — P1 market session hardening (076 API + fallback).
# 163 WebSocket(KisMarketStateClient)/CombinedSessionProvider 의존은
# 2026-07-10에 제거되었다 — session source는 076 REST(KisHolidayProvider)
# + FallbackSessionProvider(시계 기반)로 고정된다.
# 근거: plans/[PRIORITY_MAP] remaining_work_priority_map.md 항목 20,
# plan_docs/detailed_design/11_kis_realtime_quote_operations_screen.md
# "163 WS(장운영정보, ops-scheduler) 제거 가능성 검토 메모".
from agent_trading.services.market_session import (
    MarketSessionProvider,
    SCHEDULER_ADVISORY_LOCK_KEY,
    SessionInfo,
    create_session_provider,
    try_scheduler_lock,
)
from agent_trading.brokers.koreainvestment.token_cache import (
    CachePurpose,
    KisTokenCache,
    build_live_approval_key_cache_config,
    build_rest_approval_key_cache_config,
    build_rest_access_token_cache_config,
)
from agent_trading.config.settings import AppSettings
from agent_trading.domain.entities import (
    UniverseFreezeRunEntity,
    UniverseFreezeRunItemEntity,
)
from agent_trading.runtime.bootstrap import postgres_runtime
from agent_trading.services.held_position_policy import (
    is_held_position_sell_path,
)
from agent_trading.services.signal_feature_batch_runtime import (
    DEFAULT_SIGNAL_FEATURE_AFTER_MARKET_FREEZE_PURPOSE,
    DEFAULT_SIGNAL_FEATURE_AFTER_MARKET_TRIGGER_TYPE,
    SignalFeatureBatchRuntimeSpec,
    should_run_signal_feature_retry_batch,
    should_run_signal_feature_tail_retry,
)
from agent_trading.services.universe_freeze_dedupe import (
    dedupe_universe_freeze_run_items,
)

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is declared in pyproject
    load_dotenv = None  # type: ignore[assignment]

KST = ZoneInfo("Asia/Seoul")

DEFAULT_SNAPSHOT_INTERVAL_SECONDS = 300
DEFAULT_EVENT_INTERVAL_SECONDS = 300
DEFAULT_DECISION_INTERVAL_SECONDS = 300
DEFAULT_POST_SUBMIT_INTERVAL_SECONDS = 30
DEFAULT_FILL_SYNC_INTERVAL_SECONDS = 600
DEFAULT_FILL_SYNC_AFTER_HOURS_INTERVAL_SECONDS = 1800
DEFAULT_SIGNAL_FEATURE_BATCH_TIME = dtime(20, 10)
DEFAULT_TRIGGER_PROXY_ATTRIBUTION_LOOKBACK_DAYS = 14
DEFAULT_DECISION_LOOP_INTRADAY_FREEZE_PURPOSE = "decision_loop_intraday"
DEFAULT_INSTRUMENT_MASTER_SYNC_TIME = dtime(4, 50)
DEFAULT_INSTRUMENT_STATUS_SNAPSHOT_TIME = dtime(5, 5)
DEFAULT_INSTRUMENT_MASTER_SYNC_CSV_PATH = (
    "data/instrument_master/normalized/kis_kospi_kosdaq_master_normalized_for_sync.csv"
)
DEFAULT_INSTRUMENT_MASTER_SOURCE_CSV_PATHS = (
    "data/instrument_master/source/kospi_master.csv",
    "data/instrument_master/source/kosdaq_master.csv",
)
DEFAULT_INSTRUMENT_MASTER_ARCHIVE_DIR = "data/instrument_master/archive"
DEFAULT_INSTRUMENT_STATUS_SNAPSHOT_FREEZE_PURPOSES = (
    DEFAULT_DECISION_LOOP_INTRADAY_FREEZE_PURPOSE,
    DEFAULT_SIGNAL_FEATURE_AFTER_MARKET_FREEZE_PURPOSE,
)
DEFAULT_DECISION_SUBMIT_TIMEOUT_SECONDS = 420
# Phase 4: subprocess isolation provides SIGKILL-guaranteed timeout,
# so the scheduler-level timeout can be reduced from 240s to 120s.
# The subprocess itself enforces a 35s timeout for agent execution.
# Increased from 420s to 600s because 14 symbols × 3 batches × ~110s
# = ~330s, plus held_position sell (REDUCE/EXIT) symbols may need
# additional time for AI agent execution. The subprocess-level
# PER_AGENT_HARD_TIMEOUT (300s) provides per-symbol safety, and the
# scheduler-level timeout is the outer safety net for the entire
# subprocess (all symbols via asyncio.gather).
DEFAULT_TASK_TIMEOUT_SECONDS = 600
PYTHON_BIN = "python3"

# timeout 후 partial stdout/stderr capture 시
# 마지막 64KB tail만 보존 (전체 버퍼를 decode하지 않음)
_MAX_PARTIAL_LOG_BYTES: int = 65536  # 64KB — 마지막 64KB tail만 보존
_PARTIAL_READ_TIMEOUT: float = 10.0  # partial read timeout (초) — 424초 누적 버퍼 대응

DEFAULT_MAX_GENERAL_BUY_SUBMIT_PER_DAY = 6
# Held-position REDUCE/EXIT sell은 위험 축소 목적이므로 별도 budget 허용.
# 신규 진입(BUY) budget과 분리하여 held_position sell만 추가 통과시킨다.
HELD_POSITION_SELL_MAX_PER_DAY = 5
# Cycle당 held_position REDUCE/EXIT sell 최대 건수 (같은 cycle 내 중복 submit 방지)
HELD_POSITION_SELL_MAX_PER_CYCLE = 2

# After-hours snapshot window (seconds after EOD phase)
AFTER_HOURS_SNAPSHOT_WINDOW_SECONDS: int = 3600  # 1 hour
# Budget-consuming order statuses for DB-based submit budget safeguard.
# These statuses indicate that a submit budget slot was consumed.
#
# NOTE: reconcile_required is intentionally excluded because broker truth has
# not yet been confirmed.  Counting it as budget-consumed would cause the
# submit gate to block legitimate submissions (see scheduler_submit_gate_block
# post-mortem: plans/scheduler_submit_gate_block_reason_2026-05-15.md).
_BUDGET_CONSUMING_STATUSES: frozenset[str] = frozenset({
    "submitted",
    "acknowledged",
    "partially_filled",
    "filled",
})


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _resolve_repo_path(path: str) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        return str(candidate)
    return str((_repo_root() / candidate).resolve())

PRE_MARKET_START = dtime(8, 0)
INTRADAY_START = dtime(8, 50)
MARKET_CLOSE = dtime(15, 30, 30)
END_OF_DAY_END = dtime(16, 30)

logger = logging.getLogger("ops_scheduler")


@dataclass(slots=True)
class CommandResult:
    """Completed subprocess execution result."""

    name: str
    argv: list[str]
    returncode: int
    duration_seconds: float
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


@dataclass(slots=True)
class ScheduledTask:
    """Periodic task state.

    ``due``는 ``last_run_at + interval_seconds``를 기준으로 판단하여,
    ``next_run_at``과 무관하게 동작한다.  ``next_run_at``은 CADENCE_TRACE
    로깅에서 다음 예정 시각 표시용으로만 유지한다.
    """

    name: str
    interval_seconds: int
    next_run_at: datetime
    last_run_at: datetime | None = None

    @property
    def due(self) -> bool:
        """``last_run_at`` 단일 기준 due 판정.

        - ``last_run_at is None`` (최초 실행) → ``True``
        - ``last_run_at + interval_seconds <= now`` → ``True``
        - 그 외 → ``False``
        """
        now = datetime.now(KST)
        if self.last_run_at is None:
            return True
        return now >= self.last_run_at + timedelta(seconds=self.interval_seconds)

    def mark_ran(self, now: datetime) -> None:
        self.last_run_at = now
        self.next_run_at = now + timedelta(seconds=self.interval_seconds)


@dataclass(slots=True)
class SchedulerState:
    """Mutable scheduler state for a single operating day."""

    run_date: date
    pre_market_done: bool = False
    end_of_day_done: bool = False
    after_hours_mode: bool = False
    after_hours_next_snapshot_at: datetime | None = None
    submit_count: int = 0
    # held_position REDUCE/EXIT sell 전용 submit count (별도 budget)
    held_position_sell_submit_count: int = 0
    cycles: int = 0
    command_results: list[CommandResult] = field(default_factory=list)
    # P1: Session gate state
    session_info: SessionInfo | None = None
    # P2: Real-time market phase tracking
    market_phase: str | None = None
    last_phase_change: datetime | None = None
    session_db_id: int | None = None
    # 16:00 KST after-hours 복구 배치 완료 여부 (1회만 실행)
    recovery_batch_done: bool = False
    # 장후 첫 1회 full snapshot(positions+cash) 완료 여부
    after_hours_full_snapshot_done: bool = False
    # 장 마감 후 20:10 KST signal feature batch 1회 실행 여부
    signal_feature_batch_done: bool = False
    # 장후 trigger proxy attribution 분석 배치 완료 여부
    trigger_proxy_attribution_done: bool = False
    # 장중 decision loop intraday universe freeze 완료 여부
    intraday_universe_freeze_done: bool = False
    # 장전 04:50 KST instrument master sync 1회 실행 여부
    instrument_master_sync_done: bool = False
    # 장전 sync window를 놓친 사실을 1회만 기록하기 위한 플래그
    instrument_master_sync_missed: bool = False
    # 장전 05:05 KST instrument status snapshot 1회 실행 여부
    instrument_status_snapshot_done: bool = False
    # 장전 status snapshot window 누락 기록 플래그
    instrument_status_snapshot_missed: bool = False


def _derive_operations_day_status(state: SchedulerState) -> str:
    """Derive a compact scheduler status label for ``operations_day_runs``."""
    if state.after_hours_mode:
        return "after_hours"
    if state.end_of_day_done:
        return "end_of_day_complete"
    if state.pre_market_done:
        return "intraday"
    return "pre_market"


def _parse_hhmm(value: str) -> dtime:
    """Parse ``HH:MM`` into ``datetime.time``."""
    try:
        hour, minute = value.split(":", 1)
        return dtime(int(hour), int(minute))
    except Exception as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid time {value!r}; expected HH:MM"
        ) from exc


def _combine(run_date: date, clock: dtime) -> datetime:
    """Return a timezone-aware KST datetime for ``run_date`` + ``clock``."""
    return datetime.combine(run_date, clock, tzinfo=KST)


def _resolve_intraday_freeze_run_date(run_date: date) -> date:
    """Resolve the business date used for intraday freeze materialization.

    운영 스케줄러의 intraday freeze는 현재 KST 영업일과 동일한 날짜에
    앵커되어야 한다. stale state나 잘못된 재기동으로 ``run_date``가
    과거값인 경우, 현재 KST 날짜로 보정하여 잘못된 business_date 적재를 방지한다.
    """
    now_kst = datetime.now(KST).date()
    if run_date != now_kst:
        logger.warning(
            "decision loop intraday freeze run_date mismatch: state_run_date=%s now_kst=%s "
            "— using current KST date for freeze materialization",
            run_date.isoformat(),
            now_kst.isoformat(),
        )
        return now_kst
    return run_date


def _should_rollover_to_next_run_date(
    *,
    now: datetime,
    run_date: date,
    end_at: datetime,
    state: SchedulerState,
    signal_feature_batch_at: dtime,
) -> bool:
    """Decide whether the scheduler may safely roll over to the next run date."""
    if now < end_at:
        return False
    if now.date() == run_date:
        signal_feature_trigger_at = _combine(run_date, signal_feature_batch_at)
        if not state.end_of_day_done:
            return False
        if now < signal_feature_trigger_at:
            return False
    if state.after_hours_mode and not state.signal_feature_batch_done:
        return False
    if state.after_hours_mode and not state.trigger_proxy_attribution_done:
        return False
    if now.date() > run_date:
        return True
    return True


async def _session_gate(
    session_provider: MarketSessionProvider,
    run_date: date,
    state: SchedulerState,
    phase_name: str,
) -> bool:
    """Check if the session gate permits the given phase to run.

    Returns ``True`` if the phase may proceed, ``False`` if it should be
    skipped (non-trading day).

    On first call for the day, fetches ``SessionInfo`` via the provider and
    caches it in ``state.session_info`` for observability logging.
    On subsequent calls, reuses the cached info.
    """
    if state.session_info is None:
        try:
            info = await session_provider.get_session_info(run_date)
        except Exception:
            logger.exception(
                "session_gate: provider.get_session_info failed for %s — "
                "allowing phase to proceed conservatively",
                run_date.isoformat(),
            )
            state.session_info = SessionInfo(
                is_trading_day=True,
                source="gate_error_fallback",
                reason="provider exception — conservative allow",
            )
            return True
        state.session_info = info

    if not state.session_info.is_trading_day:
        logger.warning(
            "session_gate: SKIP phase=%s run_date=%s "
            "session_source=%s opnd_yn=%s bzdy_yn=%s tr_day_yn=%s reason=%s",
            phase_name,
            run_date.isoformat(),
            state.session_info.source,
            state.session_info.opnd_yn,
            state.session_info.bzdy_yn,
            state.session_info.tr_day_yn,
            state.session_info.reason,
        )
        return False

    logger.info(
        "session_gate: ALLOW phase=%s run_date=%s "
        "session_source=%s opnd_yn=%s bzdy_yn=%s tr_day_yn=%s "
        "market_phase=%s",
        phase_name,
        run_date.isoformat(),
        state.session_info.source,
        state.session_info.opnd_yn,
        state.session_info.bzdy_yn,
        state.session_info.tr_day_yn,
        state.market_phase or state.session_info.market_phase or "N/A",
    )
    return True


def _load_env() -> None:
    """Load .env if python-dotenv is available.

    Existing environment variables are not overwritten, which keeps Docker or
    manually exported runtime settings authoritative.
    """
    if load_dotenv is not None:
        load_dotenv()


def _build_base_env() -> dict[str, str]:
    """Build subprocess environment."""
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def _extract_json_objects(text: str) -> list[dict[str, Any]]:
    """Extract JSON objects from line-oriented command output."""
    objects: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{") or not stripped.endswith("}"):
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            objects.append(parsed)
    return objects


def _is_submit_consuming_result(result: CommandResult) -> bool:
    """Return true when a decision command consumed the daily submit budget.

    Only ``SUBMITTED`` is considered budget-consuming because it confirms
    the broker accepted the order.  ``RECONCILE_REQUIRED`` is excluded:
    broker truth has not been confirmed, so counting it would inflate the
    submit budget and potentially block legitimate submissions.
    """
    if not result.ok:
        return False
    for obj in _extract_json_objects(result.stdout):
        status = str(obj.get("status", "")).upper()
        if status in {"SUBMITTED"}:
            return True
    return False


def _is_held_position_sell_result(result: CommandResult) -> bool:
    """Check if the submitted result was a held_position REDUCE/EXIT sell.

    stdout JSON에서 3중 조건을 모두 확인한다:
    1. ``source_type == 'held_position'``
    2. ``decision_type in ('reduce', 'exit')``
    3. ``side == 'sell'``

    세 조건이 모두 충족되어야 held_position sell budget을 소비한 것으로 간주한다.
    """
    if not result.ok:
        return False
    for obj in _extract_json_objects(result.stdout):
        if is_held_position_sell_path(
            source_type=str(obj.get("source_type", "")),
            decision_type=str(obj.get("decision_type", "")),
            side=str(obj.get("side", "")),
        ):
            return True
    return False


def _parse_snapshot_sync_summary(result: CommandResult) -> dict[str, Any]:
    """Parse snapshot sync summary metrics from command output.

    The snapshot sync loop logs a structured line like::

        sync-cycle  accounts=1 (ok=1 partial=0 fail=0 skip=0)  positions=5 (skipped=0)  cash=1  errors=0

    Snapshot sync uses standard logging, so in subprocess execution the
    structured line normally lands in ``stderr`` rather than ``stdout``.
    Returns a dict with parsed metrics or empty dict on failure.
    """
    metrics: dict[str, Any] = {}
    combined_output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    for line in combined_output.splitlines():
        stripped = line.strip()
        if "sync-cycle" in stripped:
            # Extract key=value pairs from the log line
            import re
            m = re.search(
                r"accounts=(\d+).*?ok=(\d+).*?partial=(\d+).*?fail=(\d+).*?skip=(\d+).*?"
                r"positions=(\d+).*?skipped=(\d+).*?cash=(\d+).*?errors=(\d+)",
                stripped,
            )
            if m:
                metrics["total_accounts"] = int(m.group(1))
                metrics["succeeded"] = int(m.group(2))
                metrics["partial"] = int(m.group(3))
                metrics["failed"] = int(m.group(4))
                metrics["skipped"] = int(m.group(5))
                metrics["total_positions_synced"] = int(m.group(6))
                metrics["total_positions_skipped"] = int(m.group(7))
                metrics["total_cash_synced"] = int(m.group(8))
                metrics["errors"] = int(m.group(9))
            break
    return metrics


def _parse_fill_sync_summary(result: CommandResult) -> dict[str, Any]:
    """Parse fill sync summary metrics from command output."""
    metrics: dict[str, Any] = {}
    combined_output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    for line in combined_output.splitlines():
        stripped = line.strip()
        if "fill-sync-cycle" not in stripped:
            continue
        import re

        m = re.search(
            r"accounts=(\d+).*?succeeded=(\d+).*?partial=(\d+).*?failed=(\d+).*?"
            r"skipped=(\d+).*?fills=(\d+).*?skipped_fills=(\d+).*?retries=(\d+).*?"
            r"retried_accounts=(\d+).*?errors=(\d+)",
            stripped,
        )
        if not m:
            break
        metrics["total_accounts"] = int(m.group(1))
        metrics["succeeded"] = int(m.group(2))
        metrics["partial"] = int(m.group(3))
        metrics["failed"] = int(m.group(4))
        metrics["skipped"] = int(m.group(5))
        metrics["fills"] = int(m.group(6))
        metrics["skipped_fills"] = int(m.group(7))
        metrics["retries"] = int(m.group(8))
        metrics["retried_accounts"] = int(m.group(9))
        metrics["errors"] = int(m.group(10))
        break
    return metrics


def _parse_decision_loop_summary(result: CommandResult) -> dict[str, Any]:
    """Parse decision loop aggregate summary metrics from JSON stdout."""
    for obj in reversed(_extract_json_objects(result.stdout)):
        if str(obj.get("mode", "")).lower() != "summary":
            continue
        metrics = obj.get("metrics")
        if not isinstance(metrics, dict):
            continue
        return metrics
    return {}


def _parse_post_submit_sync_summary(result: CommandResult) -> dict[str, Any]:
    """Parse post-submit sync summary and fill-triggered refresh metrics."""
    metrics: dict[str, Any] = {}
    refresh_metrics: dict[str, Any] = {}
    combined_output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    for line in combined_output.splitlines():
        stripped = line.strip()
        if "sync-cycle-refresh" in stripped:
            import re

            m = re.search(
                r"scheduled=(\d+).*?deduped=(\d+).*?completed=(\d+).*?degraded=(\d+).*?"
                r"failed=(\d+).*?avg_elapsed_ms=(\d+).*?max_elapsed_ms=(\d+)",
                stripped,
            )
            if m:
                refresh_metrics["scheduled"] = int(m.group(1))
                refresh_metrics["deduped"] = int(m.group(2))
                refresh_metrics["completed"] = int(m.group(3))
                refresh_metrics["degraded"] = int(m.group(4))
                refresh_metrics["failed"] = int(m.group(5))
                refresh_metrics["avg_elapsed_ms"] = int(m.group(6))
                refresh_metrics["max_elapsed_ms"] = int(m.group(7))
            continue
        if "sync-cycle" not in stripped:
            continue
        import re

        m = re.search(
            r"orders=(\d+).*?updated=(\d+).*?filled=(\d+).*?partial=(\d+).*?"
            r"snapshots=(\d+).*?errors=(\d+).*?orphans_expired=(\d+).*?"
            r"pending=(\d+).*?reconcile=(\d+).*?elapsed=([0-9.]+)s",
            stripped,
        )
        if not m:
            continue
        metrics["orders"] = int(m.group(1))
        metrics["updated"] = int(m.group(2))
        metrics["filled"] = int(m.group(3))
        metrics["partial"] = int(m.group(4))
        metrics["snapshots_refreshed"] = int(m.group(5))
        metrics["errors"] = int(m.group(6))
        metrics["orphans_expired"] = int(m.group(7))
        metrics["orphans_expired_pending"] = int(m.group(8))
        metrics["orphans_expired_reconcile"] = int(m.group(9))
        metrics["elapsed_seconds"] = float(m.group(10))
    if refresh_metrics:
        metrics["refresh"] = refresh_metrics
    return metrics


def _parse_signal_feature_batch_summary(result: CommandResult) -> dict[str, Any]:
    """Parse signal feature snapshot batch summary from JSON/stdout."""
    for obj in reversed(_extract_json_objects(result.stdout)):
        processed = obj.get("processed")
        persisted = obj.get("persisted")
        skipped = obj.get("skipped")
        errors = obj.get("errors")
        if processed is None or persisted is None or skipped is None:
            continue
        error_list = errors if isinstance(errors, list) else []
        return {
            "processed": int(processed),
            "persisted": int(persisted),
            "skipped": int(skipped),
            "errors": len(error_list),
            "persist_error_count": len(error_list),
            "persist_success_count": int(persisted),
            "failed_symbols_sample": [
                str(item).split(":", 2)[0]
                for item in error_list[:5]
                if isinstance(item, str) and item.strip()
            ],
        }
    return {}


def _parse_signal_feature_input_summary(result: CommandResult) -> dict[str, Any]:
    """Parse signal feature input generation summary from JSON/stdout."""
    for obj in reversed(_extract_json_objects(result.stdout)):
        universe_count = obj.get("universe_count")
        generated_count = obj.get("generated_count")
        error_count = obj.get("error_count")
        if universe_count is None or generated_count is None or error_count is None:
            continue
        errors = obj.get("errors")
        error_list = errors if isinstance(errors, list) else []
        payload: dict[str, Any] = {
            "universe_count": int(universe_count),
            "generated_count": int(generated_count),
            "error_count": int(error_count),
            "target_count": int(universe_count),
            "fetch_success_count": int(generated_count),
            "fetch_error_count": int(error_count),
            "failed_symbols_sample": [
                str(item).split(":", 2)[0]
                for item in error_list[:5]
                if isinstance(item, str) and item.strip()
            ],
        }
        output = obj.get("output")
        if output:
            payload["output"] = str(output)
        universe_freeze_run_id = obj.get("universe_freeze_run_id")
        if universe_freeze_run_id:
            payload["universe_freeze_run_id"] = str(universe_freeze_run_id)
        payload["retry_mode"] = bool(obj.get("retry_mode", False))
        retry_source_input = obj.get("retry_source_input")
        if retry_source_input:
            payload["retry_source_input"] = str(retry_source_input)
        return payload
    return {}


def _parse_trigger_proxy_attribution_summary(result: CommandResult) -> dict[str, Any]:
    """Parse trigger proxy attribution batch summary from JSON/stdout."""
    json_objects = list(_extract_json_objects(result.stdout))
    if not json_objects:
        try:
            argv = list(result.argv)
            if "--write-json" in argv:
                idx = argv.index("--write-json")
                path = argv[idx + 1] if idx + 1 < len(argv) else ""
                if path:
                    candidate = Path(str(path))
                    if candidate.exists():
                        raw = json.loads(candidate.read_text(encoding="utf-8"))
                        if isinstance(raw, dict):
                            json_objects = [raw]
        except Exception:
            logger.exception(
                "trigger_proxy_attribution summary fallback read failed"
            )
    for obj in reversed(json_objects):
        if bool(obj.get("skipped")):
            payload: dict[str, Any] = {
                "skipped": True,
                "skipped_reason": str(obj.get("skipped_reason") or "unknown"),
            }
            if obj.get("start_date"):
                payload["start_date"] = str(obj["start_date"])
            if obj.get("end_date"):
                payload["end_date"] = str(obj["end_date"])
            return payload
        sample_count = obj.get("sample_count")
        if sample_count is None:
            continue
        watch_projection_items = (
            obj.get("watch_projection_items")
            if isinstance(obj.get("watch_projection_items"), list)
            else []
        )
        core_shadow_items = (
            obj.get("core_risk_off_shadow_items")
            if isinstance(obj.get("core_risk_off_shadow_items"), list)
            else []
        )
        event_shadow_items = (
            obj.get("event_overlay_shadow_items")
            if isinstance(obj.get("event_overlay_shadow_items"), list)
            else []
        )
        core_floor_report = (
            obj.get("core_risk_off_floor_v5_report")
            if isinstance(obj.get("core_risk_off_floor_v5_report"), dict)
            else (
                obj.get("core_risk_off_floor_report")
                if isinstance(obj.get("core_risk_off_floor_report"), dict)
                else {}
            )
        )
        core_floor_proxy = (
            core_floor_report.get("proxy_availability")
            if isinstance(core_floor_report.get("proxy_availability"), dict)
            else {}
        )
        core_floor_diagnostics = (
            obj.get("core_risk_off_floor_v5_diagnostics")
            if isinstance(obj.get("core_risk_off_floor_v5_diagnostics"), dict)
            else (
                obj.get("core_risk_off_floor_diagnostics")
                if isinstance(obj.get("core_risk_off_floor_diagnostics"), dict)
                else {}
            )
        )
        core_floor_items = (
            core_floor_report.get("items")
            if isinstance(core_floor_report.get("items"), list)
            else []
        )
        slow_trend_relax_candidate_items = (
            core_floor_diagnostics.get("slow_trend_relax_candidate_items")
            if isinstance(core_floor_diagnostics.get("slow_trend_relax_candidate_items"), list)
            else []
        )
        slow_floor_shadow_relax_path_items = (
            core_floor_diagnostics.get("slow_floor_shadow_relax_path_items")
            if isinstance(core_floor_diagnostics.get("slow_floor_shadow_relax_path_items"), list)
            else []
        )
        active_slow_floor_relax_ready_transition_stage_items = (
            core_floor_diagnostics.get("active_slow_floor_relax_ready_transition_stage_items")
            if isinstance(
                core_floor_diagnostics.get("active_slow_floor_relax_ready_transition_stage_items"),
                list,
            )
            else []
        )
        active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_band_items = (
            core_floor_diagnostics.get("active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_band_items")
            if isinstance(
                core_floor_diagnostics.get(
                    "active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_band_items"
                ),
                list,
            )
            else []
        )
        active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_projection_items = (
            core_floor_diagnostics.get("active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_projection_items")
            if isinstance(
                core_floor_diagnostics.get(
                    "active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_projection_items"
                ),
                list,
            )
            else []
        )
        pre_buy_boundary_watch_from_entry_setup_small_entry_gap_report = (
            core_floor_diagnostics.get("pre_buy_boundary_watch_from_entry_setup_small_entry_gap_report")
            if isinstance(
                core_floor_diagnostics.get(
                    "pre_buy_boundary_watch_from_entry_setup_small_entry_gap_report"
                ),
                dict,
            )
            else {}
        )
        pre_buy_boundary_watch_from_entry_setup_moderate_entry_gap_report = (
            core_floor_diagnostics.get("pre_buy_boundary_watch_from_entry_setup_moderate_entry_gap_report")
            if isinstance(
                core_floor_diagnostics.get(
                    "pre_buy_boundary_watch_from_entry_setup_moderate_entry_gap_report"
                ),
                dict,
            )
            else {}
        )
        pre_buy_boundary_watch_from_entry_setup_small_entry_gap_items = (
            pre_buy_boundary_watch_from_entry_setup_small_entry_gap_report.get("cohort_items")
            if isinstance(
                pre_buy_boundary_watch_from_entry_setup_small_entry_gap_report.get("cohort_items"),
                list,
            )
            else []
        )
        pre_buy_boundary_watch_from_entry_setup_small_entry_gap_projection_items = (
            pre_buy_boundary_watch_from_entry_setup_small_entry_gap_report.get("projection_items")
            if isinstance(
                pre_buy_boundary_watch_from_entry_setup_small_entry_gap_report.get("projection_items"),
                list,
            )
            else []
        )
        pre_buy_boundary_watch_from_entry_setup_moderate_entry_gap_items = (
            pre_buy_boundary_watch_from_entry_setup_moderate_entry_gap_report.get("cohort_items")
            if isinstance(
                pre_buy_boundary_watch_from_entry_setup_moderate_entry_gap_report.get("cohort_items"),
                list,
            )
            else []
        )
        pre_buy_boundary_watch_from_entry_setup_moderate_entry_gap_projection_items = (
            pre_buy_boundary_watch_from_entry_setup_moderate_entry_gap_report.get("projection_items")
            if isinstance(
                pre_buy_boundary_watch_from_entry_setup_moderate_entry_gap_report.get("projection_items"),
                list,
            )
            else []
        )
        shadow_relax_projection_summary = (
            core_floor_diagnostics.get("shadow_relax_projection_summary")
            if isinstance(core_floor_diagnostics.get("shadow_relax_projection_summary"), dict)
            else {}
        )
        return {
            "sample_count": int(sample_count),
            "account_id": str(obj.get("account_id")) if obj.get("account_id") else None,
            "account_label": (
                str(obj.get("account_label")) if obj.get("account_label") else None
            ),
            "start_date": str(obj.get("start_date")) if obj.get("start_date") else None,
            "end_date": str(obj.get("end_date")) if obj.get("end_date") else None,
            "output_path": (
                str(result.argv[result.argv.index("--write-json") + 1])
                if "--write-json" in result.argv
                and result.argv.index("--write-json") + 1 < len(result.argv)
                else None
            ),
            "watch_projection_bucket_count": len(watch_projection_items),
            "core_risk_off_shadow_bucket_count": len(core_shadow_items),
            "event_overlay_shadow_bucket_count": len(event_shadow_items),
            "watch_projection_shadow_watch_only": _find_bucket_sample_count(
                watch_projection_items,
                "shadow_watch_only",
            ),
            "watch_projection_legacy_only": _find_bucket_sample_count(
                watch_projection_items,
                "legacy_watch_only",
            ),
            "core_risk_off_shadow_would_pass": _find_bucket_sample_count(
                core_shadow_items,
                "shadow_would_pass",
            ),
            "core_risk_off_floor_active_sample_count": int(
                core_floor_report.get("active_sample_count", 0) or 0
            ),
            "core_risk_off_floor_strict_pass_count": _find_bucket_sample_count(
                core_floor_items,
                "strict_pass",
            ),
            "core_risk_off_floor_mild_relax_count": _find_bucket_sample_count(
                core_floor_items,
                "mild_relax",
            ),
            "core_risk_off_floor_moderate_relax_count": _find_bucket_sample_count(
                core_floor_items,
                "moderate_relax",
            ),
            "core_risk_off_floor_deep_negative_count": _find_bucket_sample_count(
                core_floor_items,
                "deep_negative",
            ),
            "core_risk_off_floor_t1_ready_count": int(
                core_floor_proxy.get("t1_ready_count", 0) or 0
            ),
            "core_risk_off_floor_t3_ready_count": int(
                core_floor_proxy.get("t3_ready_count", 0) or 0
            ),
            "core_risk_off_floor_t5_ready_count": int(
                core_floor_proxy.get("t5_ready_count", 0) or 0
            ),
            "trend_moderate_candidate_count": _find_bucket_sample_count(
                slow_trend_relax_candidate_items,
                "trend_moderate_candidate",
            ),
            "trend_edge_deep_count": _find_bucket_sample_count(
                slow_trend_relax_candidate_items,
                "trend_edge_deep",
            ),
            "trend_deep_tail_count": _find_bucket_sample_count(
                slow_trend_relax_candidate_items,
                "trend_deep_tail",
            ),
            "shadow_relax_projection_selected_count": int(
                shadow_relax_projection_summary.get("selected_count", 0) or 0
            ),
            "slow_floor_relax_ready_count": _find_bucket_sample_count(
                slow_floor_shadow_relax_path_items,
                "slow_floor_relax_ready",
            ),
            "slow_floor_relax_activity_blocked_count": _find_bucket_sample_count(
                slow_floor_shadow_relax_path_items,
                "slow_floor_relax_activity_blocked",
            ),
            "slow_floor_relax_watch_only_core_path_count": _find_bucket_sample_count(
                active_slow_floor_relax_ready_transition_stage_items,
                "watch_only_core_path",
            ),
            "watch_only_core_path_large_entry_gap_count": _find_bucket_sample_count(
                active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_band_items,
                "large_entry_gap",
            ),
            "watch_only_core_path_moderate_entry_gap_count": _find_bucket_sample_count(
                active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_band_items,
                "moderate_entry_gap",
            ),
            "watch_only_core_path_small_entry_gap_count": _find_bucket_sample_count(
                active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_band_items,
                "small_entry_gap",
            ),
            "watch_only_core_path_entry_ready_count": _find_bucket_sample_count(
                active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_band_items,
                "entry_ready",
            ),
            "watch_only_core_path_large_entry_gap_candidate_count": _find_bucket_metric_count(
                active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_projection_items,
                "large_entry_gap",
                "candidate_count",
            ),
            "watch_only_core_path_large_entry_gap_would_buy_count": _find_bucket_metric_count(
                active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_projection_items,
                "large_entry_gap",
                "would_buy_count",
            ),
            "watch_only_core_path_large_entry_gap_submitted_count": _find_bucket_metric_count(
                active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_projection_items,
                "large_entry_gap",
                "submitted_count",
            ),
            "watch_only_core_path_moderate_entry_gap_candidate_count": _find_bucket_metric_count(
                active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_projection_items,
                "moderate_entry_gap",
                "candidate_count",
            ),
            "watch_only_core_path_moderate_entry_gap_would_buy_count": _find_bucket_metric_count(
                active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_projection_items,
                "moderate_entry_gap",
                "would_buy_count",
            ),
            "watch_only_core_path_moderate_entry_gap_submitted_count": _find_bucket_metric_count(
                active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_projection_items,
                "moderate_entry_gap",
                "submitted_count",
            ),
            "watch_only_core_path_small_entry_gap_candidate_count": _find_bucket_metric_count(
                active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_projection_items,
                "small_entry_gap",
                "candidate_count",
            ),
            "watch_only_core_path_small_entry_gap_would_buy_count": _find_bucket_metric_count(
                active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_projection_items,
                "small_entry_gap",
                "would_buy_count",
            ),
            "watch_only_core_path_small_entry_gap_submitted_count": _find_bucket_metric_count(
                active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_projection_items,
                "small_entry_gap",
                "submitted_count",
            ),
            "watch_only_core_path_entry_ready_candidate_count": _find_bucket_metric_count(
                active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_projection_items,
                "entry_ready",
                "candidate_count",
            ),
            "watch_only_core_path_entry_ready_would_buy_count": _find_bucket_metric_count(
                active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_projection_items,
                "entry_ready",
                "would_buy_count",
            ),
            "watch_only_core_path_entry_ready_submitted_count": _find_bucket_metric_count(
                active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_projection_items,
                "entry_ready",
                "submitted_count",
            ),
            "pre_buy_boundary_entry_setup_small_gap_count": _find_bucket_sample_count(
                pre_buy_boundary_watch_from_entry_setup_small_entry_gap_items,
                "watch_from_entry_setup|small_entry_gap",
            ),
            "pre_buy_boundary_entry_setup_small_gap_candidate_count": _find_bucket_metric_count(
                pre_buy_boundary_watch_from_entry_setup_small_entry_gap_projection_items,
                "watch_from_entry_setup|small_entry_gap",
                "candidate_count",
            ),
            "pre_buy_boundary_entry_setup_small_gap_would_buy_count": _find_bucket_metric_count(
                pre_buy_boundary_watch_from_entry_setup_small_entry_gap_projection_items,
                "watch_from_entry_setup|small_entry_gap",
                "would_buy_count",
            ),
            "pre_buy_boundary_entry_setup_small_gap_submitted_count": _find_bucket_metric_count(
                pre_buy_boundary_watch_from_entry_setup_small_entry_gap_projection_items,
                "watch_from_entry_setup|small_entry_gap",
                "submitted_count",
            ),
            "pre_buy_boundary_entry_setup_moderate_gap_count": _find_bucket_sample_count(
                pre_buy_boundary_watch_from_entry_setup_moderate_entry_gap_items,
                "watch_from_entry_setup|moderate_entry_gap",
            ),
            "pre_buy_boundary_entry_setup_moderate_gap_candidate_count": _find_bucket_metric_count(
                pre_buy_boundary_watch_from_entry_setup_moderate_entry_gap_projection_items,
                "watch_from_entry_setup|moderate_entry_gap",
                "candidate_count",
            ),
            "pre_buy_boundary_entry_setup_moderate_gap_would_buy_count": _find_bucket_metric_count(
                pre_buy_boundary_watch_from_entry_setup_moderate_entry_gap_projection_items,
                "watch_from_entry_setup|moderate_entry_gap",
                "would_buy_count",
            ),
            "pre_buy_boundary_entry_setup_moderate_gap_submitted_count": _find_bucket_metric_count(
                pre_buy_boundary_watch_from_entry_setup_moderate_entry_gap_projection_items,
                "watch_from_entry_setup|moderate_entry_gap",
                "submitted_count",
            ),
            "event_overlay_shadow_would_pass": _find_bucket_sample_count(
                event_shadow_items,
                "shadow_would_pass",
            ),
        }
    return {}


def _parse_instrument_status_snapshot_summary(result: CommandResult) -> dict[str, Any]:
    """Parse instrument status snapshot batch summary from JSON/stdout."""
    for obj in reversed(_extract_json_objects(result.stdout)):
        target_count = obj.get("target_count")
        persisted_count = obj.get("persisted_count")
        skipped_count = obj.get("skipped_count")
        error_count = obj.get("error_count")
        if (
            target_count is None
            or persisted_count is None
            or skipped_count is None
            or error_count is None
        ):
            continue
        rows = obj.get("rows")
        row_list = rows if isinstance(rows, list) else []
        failed_symbols_sample = [
            str(item.get("symbol"))
            for item in row_list[:20]
            if isinstance(item, dict)
            and str(item.get("status", "")).strip() in {"broker_error", "error"}
            and str(item.get("symbol", "")).strip()
        ][:5]
        return {
            "target_count": int(target_count),
            "persisted_count": int(persisted_count),
            "skipped_count": int(skipped_count),
            "error_count": int(error_count),
            "failed_symbols_sample": failed_symbols_sample,
        }
    return {}


def _aggregate_signal_feature_input_metrics(
    state: SchedulerState,
) -> dict[str, Any] | None:
    results = [
        result
        for result in state.command_results
        if result.name in {
            "after_market_signal_feature_input",
            "after_market_signal_feature_input_tail_retry",
        }
    ]
    parsed_metrics = []
    for result in results:
        metrics = _parse_signal_feature_input_summary(result)
        if metrics:
            parsed_metrics.append(metrics)
    if not parsed_metrics:
        return None

    primary = next(
        (item for item in parsed_metrics if not item.get("retry_mode")),
        parsed_metrics[0],
    )
    last = parsed_metrics[-1]
    fetch_success_total = sum(int(item.get("fetch_success_count", 0)) for item in parsed_metrics)
    payload: dict[str, Any] = {
        "universe_count": int(primary.get("universe_count", 0)),
        "generated_count": fetch_success_total,
        "error_count": int(last.get("fetch_error_count", 0)),
        "target_count": int(primary.get("target_count", 0)),
        "fetch_success_count": fetch_success_total,
        "fetch_error_count": int(last.get("fetch_error_count", 0)),
        "tail_retry_count": sum(1 for item in parsed_metrics if item.get("retry_mode")),
        "failed_symbols_sample": list(last.get("failed_symbols_sample", [])),
    }
    if primary.get("output"):
        payload["output"] = str(primary["output"])
    if primary.get("universe_freeze_run_id"):
        payload["universe_freeze_run_id"] = str(primary["universe_freeze_run_id"])
    if last.get("retry_source_input"):
        payload["retry_source_input"] = str(last["retry_source_input"])
    return payload


def _aggregate_signal_feature_batch_metrics(
    state: SchedulerState,
) -> dict[str, Any] | None:
    results = [
        result
        for result in state.command_results
        if result.name in {
            "after_market_signal_feature_batch",
            "after_market_signal_feature_batch_tail_retry",
        }
    ]
    parsed_metrics = []
    for result in results:
        metrics = _parse_signal_feature_batch_summary(result)
        if metrics:
            parsed_metrics.append(metrics)
    if not parsed_metrics:
        return None

    return {
        "processed": sum(int(item.get("processed", 0)) for item in parsed_metrics),
        "persisted": sum(int(item.get("persisted", 0)) for item in parsed_metrics),
        "skipped": sum(int(item.get("skipped", 0)) for item in parsed_metrics),
        "errors": sum(int(item.get("errors", 0)) for item in parsed_metrics),
        "persist_error_count": sum(
            int(item.get("persist_error_count", 0)) for item in parsed_metrics
        ),
        "persist_success_count": sum(
            int(item.get("persist_success_count", 0)) for item in parsed_metrics
        ),
        "tail_retry_count": max(len(parsed_metrics) - 1, 0),
        "failed_symbols_sample": list(
            dict.fromkeys(
                symbol
                for item in parsed_metrics
                for symbol in item.get("failed_symbols_sample", [])
            )
        )[:5],
    }


def _find_bucket_sample_count(items: list[Any], bucket: str) -> int:
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("bucket") or "") != bucket:
            continue
        try:
            return int(item.get("sample_count", 0))
        except (TypeError, ValueError):
            return 0
    return 0


def _find_bucket_metric_count(items: list[Any], bucket: str, field: str) -> int:
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("bucket") or "") != bucket:
            continue
        try:
            return int(item.get(field, 0) or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def _extract_command_failure_reason(result: CommandResult) -> str | None:
    """Extract a compact failure reason from command output."""
    json_objects = _extract_json_objects(result.stdout)
    for obj in reversed(json_objects):
        errors = obj.get("errors")
        if isinstance(errors, list) and errors:
            first_error = errors[0]
            if isinstance(first_error, str) and first_error.strip():
                return first_error.strip()
        error = obj.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()
        detail = obj.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()

    for source in (result.stderr, result.stdout):
        for line in reversed(source.splitlines()):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("{") and stripped.endswith("}"):
                continue
            return stripped[:500]
    return None


def _extract_command_skip_metadata(result: CommandResult) -> dict[str, Any]:
    """Extract structured skip metadata from command stdout JSON when present."""
    for obj in reversed(_extract_json_objects(result.stdout)):
        skipped = obj.get("skipped")
        skipped_reason = obj.get("skipped_reason")
        if skipped is None and skipped_reason is None:
            continue
        payload: dict[str, Any] = {}
        if skipped is not None:
            payload["skipped"] = bool(skipped)
        if isinstance(skipped_reason, str) and skipped_reason.strip():
            payload["skipped_reason"] = skipped_reason.strip()
        details = obj.get("details")
        if isinstance(details, dict) and details:
            payload["details"] = details
        return payload
    return {}


def _build_skip_command_result(
    *,
    name: str,
    argv: list[str],
    skipped_reason: str,
    details: dict[str, Any] | None = None,
) -> CommandResult:
    payload: dict[str, Any] = {
        "skipped": True,
        "skipped_reason": skipped_reason,
    }
    if details:
        payload["details"] = details
    return CommandResult(
        name=name,
        argv=argv,
        returncode=0,
        duration_seconds=0.0,
        stdout=json.dumps(payload, ensure_ascii=True),
    )


def _latest_command_result(
    state: SchedulerState,
    names: set[str],
) -> CommandResult | None:
    """Return the most recent command result whose name is in ``names``."""
    for result in reversed(state.command_results):
        if result.name in names:
            return result
    return None


def _command_result_summary(
    result: CommandResult | None,
    *,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build a compact JSON-safe summary for a command result."""
    if result is None:
        return None
    payload: dict[str, Any] = {
        "name": result.name,
        "ok": result.ok,
        "returncode": result.returncode,
        "timed_out": result.timed_out,
        "duration_seconds": result.duration_seconds,
    }
    if metrics:
        payload["metrics"] = metrics
    skip_metadata = _extract_command_skip_metadata(result)
    if skip_metadata:
        payload.update(skip_metadata)
    if not result.ok:
        failure_reason = _extract_command_failure_reason(result)
        if failure_reason:
            payload["last_error"] = failure_reason
    return payload


def _command_family_stats(
    state: SchedulerState,
    *,
    names: set[str],
    metrics_parser: Callable[[CommandResult], dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Build aggregate stats for one logical command family."""
    results = [result for result in state.command_results if result.name in names]
    if not results:
        return None

    last = results[-1]
    payload: dict[str, Any] = {
        "count": len(results),
        "ok_count": sum(1 for result in results if result.ok),
        "failed_count": sum(1 for result in results if not result.ok),
        "timed_out_count": sum(1 for result in results if result.timed_out),
        "last_name": last.name,
        "last_ok": last.ok,
        "last_returncode": last.returncode,
        "last_timed_out": last.timed_out,
        "last_duration_seconds": last.duration_seconds,
    }
    if metrics_parser is not None:
        payload["last_metrics"] = metrics_parser(last)
    if not last.ok:
        failure_reason = _extract_command_failure_reason(last)
        if failure_reason:
            payload["last_error"] = failure_reason
    return payload


def _build_operations_day_summary_json(state: SchedulerState) -> dict[str, Any]:
    """Build structured ``summary_json`` for ``operations_day_runs``."""
    total = len(state.command_results)
    ok_count = sum(1 for result in state.command_results if result.ok)
    failed_count = sum(1 for result in state.command_results if not result.ok)
    timed_out_count = sum(1 for result in state.command_results if result.timed_out)

    latest_snapshot = _latest_command_result(
        state,
        {"pre_snapshot_sync", "snapshot_sync", "eod_snapshot_sync", "after_hours_snapshot_sync"},
    )
    latest_fill = _latest_command_result(
        state,
        {"pre_fill_sync", "fill_sync", "eod_fill_sync"},
    )
    latest_recovery = _latest_command_result(state, {"eod_recovery_batch"})
    latest_signal_feature_batch = _latest_command_result(
        state,
        {"after_market_signal_feature_batch", "after_market_signal_feature_batch_tail_retry"},
    )
    latest_signal_feature_input = _latest_command_result(
        state,
        {"after_market_signal_feature_input", "after_market_signal_feature_input_tail_retry"},
    )
    latest_trigger_proxy_attribution = _latest_command_result(
        state,
        {"after_market_trigger_proxy_attribution"},
    )
    signal_feature_batch_metrics = _aggregate_signal_feature_batch_metrics(state)
    signal_feature_input_metrics = _aggregate_signal_feature_input_metrics(state)
    if signal_feature_batch_metrics is not None and signal_feature_input_metrics is not None:
        merged_signal_feature_batch_metrics = {
            **signal_feature_batch_metrics,
            "target_count": int(signal_feature_input_metrics.get("target_count", 0)),
            "fetch_success_count": int(signal_feature_input_metrics.get("fetch_success_count", 0)),
            "fetch_error_count": int(signal_feature_input_metrics.get("fetch_error_count", 0)),
            "final_missing_count": max(
                int(signal_feature_input_metrics.get("target_count", 0))
                - int(signal_feature_batch_metrics.get("persist_success_count", 0)),
                0,
            ),
            "failed_symbols_sample": list(dict.fromkeys(
                list(signal_feature_input_metrics.get("failed_symbols_sample", []))
                + list(signal_feature_batch_metrics.get("failed_symbols_sample", []))
            ))[:5],
        }
    else:
        merged_signal_feature_batch_metrics = signal_feature_batch_metrics
    latest_decision_loop = _latest_command_result(
        state,
        {"decision_submit_gate", "decision_dry_run"},
    )
    command_health = {
        "snapshot_sync": _command_family_stats(
            state,
            names={"pre_snapshot_sync", "snapshot_sync", "eod_snapshot_sync", "after_hours_snapshot_sync"},
            metrics_parser=_parse_snapshot_sync_summary,
        ),
        "fill_sync": _command_family_stats(
            state,
            names={"pre_fill_sync", "fill_sync", "eod_fill_sync"},
            metrics_parser=_parse_fill_sync_summary,
        ),
        "event_ingestion": _command_family_stats(
            state,
            names={"pre_event_ingestion", "event_ingestion"},
        ),
        "post_submit_sync": _command_family_stats(
            state,
            names={"pre_post_submit_sync", "post_submit_sync", "eod_post_submit_sync"},
            metrics_parser=_parse_post_submit_sync_summary,
        ),
        "decision_loop": _command_family_stats(
            state,
            names={"decision_submit_gate", "decision_dry_run"},
            metrics_parser=_parse_decision_loop_summary,
        ),
        "recovery_batch": _command_family_stats(
            state,
            names={"eod_recovery_batch"},
        ),
        "signal_feature_batch": _command_family_stats(
            state,
            names={"after_market_signal_feature_batch", "after_market_signal_feature_batch_tail_retry"},
            metrics_parser=_parse_signal_feature_batch_summary,
        ),
        "signal_feature_input": _command_family_stats(
            state,
            names={"after_market_signal_feature_input", "after_market_signal_feature_input_tail_retry"},
            metrics_parser=_parse_signal_feature_input_summary,
        ),
        "trigger_proxy_attribution": _command_family_stats(
            state,
            names={"after_market_trigger_proxy_attribution"},
            metrics_parser=_parse_trigger_proxy_attribution_summary,
        ),
        "instrument_master_sync": _command_family_stats(
            state,
            names={"instrument_master_sync"},
        ),
        "instrument_master_normalize": _command_family_stats(
            state,
            names={"instrument_master_normalize"},
        ),
        "instrument_status_snapshot": _command_family_stats(
            state,
            names={"instrument_status_snapshot"},
            metrics_parser=_parse_instrument_status_snapshot_summary,
        ),
    }
    token_cache_health = _build_token_cache_health_summary()

    return {
        "command_results_count": total,
        "ok_count": ok_count,
        "failed_count": failed_count,
        "timed_out_count": timed_out_count,
        "last_command_name": state.command_results[-1].name if state.command_results else None,
        "session_reason": state.session_info.reason if state.session_info else None,
        "after_hours_full_snapshot_done": state.after_hours_full_snapshot_done,
        "signal_feature_batch_done": state.signal_feature_batch_done,
        "trigger_proxy_attribution_done": state.trigger_proxy_attribution_done,
        "intraday_universe_freeze_done": state.intraday_universe_freeze_done,
        "instrument_master_sync_done": state.instrument_master_sync_done,
        "instrument_master_sync_missed": state.instrument_master_sync_missed,
        "instrument_status_snapshot_done": state.instrument_status_snapshot_done,
        "instrument_status_snapshot_missed": state.instrument_status_snapshot_missed,
        "scheduler_runtime": _build_scheduler_runtime_summary(),
        "command_health": {k: v for k, v in command_health.items() if v is not None},
        "token_cache_health": token_cache_health,
        "snapshot_sync": _command_result_summary(
            latest_snapshot,
            metrics=_parse_snapshot_sync_summary(latest_snapshot) if latest_snapshot else None,
        ),
        "fill_sync": _command_result_summary(
            latest_fill,
            metrics=_parse_fill_sync_summary(latest_fill) if latest_fill else None,
        ),
        "decision_loop": _command_result_summary(
            latest_decision_loop,
            metrics=_parse_decision_loop_summary(latest_decision_loop) if latest_decision_loop else None,
        ),
        "recovery_batch": _command_result_summary(latest_recovery),
        "signal_feature_batch": _command_result_summary(
            latest_signal_feature_batch,
            metrics=merged_signal_feature_batch_metrics,
        ),
        "signal_feature_input": _command_result_summary(
            latest_signal_feature_input,
            metrics=signal_feature_input_metrics,
        ),
        "trigger_proxy_attribution": _command_result_summary(
            latest_trigger_proxy_attribution,
            metrics=(
                _parse_trigger_proxy_attribution_summary(latest_trigger_proxy_attribution)
                if latest_trigger_proxy_attribution
                else None
            ),
        ),
        "instrument_master_sync": _command_result_summary(
            _latest_command_result(state, {"instrument_master_sync"}),
        ),
        "instrument_master_normalize": _command_result_summary(
            _latest_command_result(state, {"instrument_master_normalize"}),
        ),
        "instrument_status_snapshot": _command_result_summary(
            _latest_command_result(state, {"instrument_status_snapshot"}),
            metrics=_parse_instrument_status_snapshot_summary(
                _latest_command_result(state, {"instrument_status_snapshot"})
            )
            if _latest_command_result(state, {"instrument_status_snapshot"})
            else None,
        ),
    }


def _build_scheduler_runtime_summary() -> dict[str, Any]:
    """Build runtime-identifying metadata for the live scheduler process."""
    script_path = Path(__file__).resolve()
    repo_root = _repo_root()
    return {
        "pid": os.getpid(),
        "cwd": os.getcwd(),
        "repo_root": str(repo_root),
        "script_path": str(script_path),
        "python_bin": sys.executable,
        "instrument_master_sync_supported": True,
        "instrument_master_sync_time": DEFAULT_INSTRUMENT_MASTER_SYNC_TIME.strftime("%H:%M"),
        "instrument_status_snapshot_supported": True,
        "instrument_status_snapshot_time": DEFAULT_INSTRUMENT_STATUS_SNAPSHOT_TIME.strftime("%H:%M"),
        "instrument_status_snapshot_freeze_purposes": list(
            DEFAULT_INSTRUMENT_STATUS_SNAPSHOT_FREEZE_PURPOSES
        ),
        "instrument_master_sync_csv_path": DEFAULT_INSTRUMENT_MASTER_SYNC_CSV_PATH,
        "instrument_master_sync_csv_path_resolved": _resolve_repo_path(
            DEFAULT_INSTRUMENT_MASTER_SYNC_CSV_PATH
        ),
        "instrument_master_source_csv_paths": list(
            DEFAULT_INSTRUMENT_MASTER_SOURCE_CSV_PATHS
        ),
        "instrument_master_source_csv_paths_resolved": [
            _resolve_repo_path(path) for path in DEFAULT_INSTRUMENT_MASTER_SOURCE_CSV_PATHS
        ],
        "instrument_master_archive_dir": DEFAULT_INSTRUMENT_MASTER_ARCHIVE_DIR,
        "instrument_master_archive_dir_resolved": _resolve_repo_path(
            DEFAULT_INSTRUMENT_MASTER_ARCHIVE_DIR
        ),
        "signal_feature_batch_supported": True,
        "signal_feature_batch_time": DEFAULT_SIGNAL_FEATURE_BATCH_TIME.strftime("%H:%M"),
        "trigger_proxy_attribution_supported": True,
        "trigger_proxy_attribution_mode": "after_signal_feature_batch",
        "trigger_proxy_attribution_lookback_days": DEFAULT_TRIGGER_PROXY_ATTRIBUTION_LOOKBACK_DAYS,
        "decision_loop_intraday_freeze_supported": True,
        "decision_loop_intraday_freeze_purpose": DEFAULT_DECISION_LOOP_INTRADAY_FREEZE_PURPOSE,
        "script_mtime_epoch": script_path.stat().st_mtime,
    }


def _build_token_cache_health_summary() -> dict[str, Any]:
    """Build a compact operational view of KIS token/approval cache files.

    2026-07-13 토큰 캐시 통합: ``holiday_oauth``(076)는 더 이상 전용 파일
    (``kis_live_oauth_token.json``)을 쓰지 않는다 — disclosure/시세 client와
    동일한 appkey(``KIS_LIVE_INFO_*``)로 인증하는 같은 종류의 REST access
    token이므로, ``live_disclosure_access_token``과 캐시 파일/purpose를
    공유한다(아래 두 항목이 동일한 path/status를 보고하면 정상 통합된 것).
    상세: `plans/[BACKLOG] backlog.md` "KIS 토큰 캐시 통합(appkey당 1개)".
    """
    settings = AppSettings()
    caches: dict[str, KisTokenCache] = {
        "paper_rest_access_token": KisTokenCache(
            build_rest_access_token_cache_config(
                enabled=settings.kis_dev_token_cache_enabled,
                cache_path=Path(settings.kis_dev_token_cache_path),
                cache_purpose=CachePurpose.PAPER_ACCESS_TOKEN,
                api_key=settings.kis_api_key,
                kis_env=settings.kis_env,
                base_url=settings.kis_base_url,
            ),
        ),
        "trading_approval_key": KisTokenCache(
            build_rest_approval_key_cache_config(
                enabled=settings.kis_approval_key_cache_enabled,
                cache_path=Path(settings.kis_approval_key_cache_path),
                api_key=settings.kis_api_key,
                api_secret=settings.kis_api_secret,
                kis_env=settings.kis_env,
                base_url=settings.kis_base_url,
            ),
        ),
        "holiday_oauth": KisTokenCache(
            build_rest_access_token_cache_config(
                enabled=settings.kis_disclosure_token_cache_enabled,
                cache_path=Path(settings.kis_disclosure_token_cache_path),
                cache_purpose=CachePurpose.LIVE_DISCLOSURE_ACCESS_TOKEN,
                api_key=settings.kis_live_app_key or "",
                kis_env="live",
                base_url=settings.kis_live_info_base_url or settings.kis_base_url,
            ),
        ),
        "live_approval_key": KisTokenCache(
            build_live_approval_key_cache_config(
                enabled=settings.kis_live_token_cache_enabled,
                cache_path=Path(settings.kis_live_token_cache_path),
                app_key=settings.kis_live_app_key or "",
                api_secret=settings.kis_live_app_secret or "",
                base_ws_url=settings.kis_live_info_ws_url or settings.kis_ws_url,
            ),
        ),
    }
    if settings.kis_live_app_key and settings.kis_live_app_secret:
        caches["live_disclosure_access_token"] = KisTokenCache(
            build_rest_access_token_cache_config(
                enabled=settings.kis_disclosure_token_cache_enabled,
                cache_path=Path(settings.kis_disclosure_token_cache_path),
                cache_purpose=CachePurpose.LIVE_DISCLOSURE_ACCESS_TOKEN,
                api_key=settings.kis_live_app_key,
                kis_env="live",
                base_url=settings.kis_live_info_base_url or settings.kis_base_url,
            ),
        )
    return {
        name: cache.inspect().to_dict()
        for name, cache in caches.items()
    }


async def _get_db_submit_count(run_date: date) -> int:
    """Query ``trading.order_requests`` for today's general BUY submit count.

    Returns the count of general BUY orders whose status is in the
    budget-consuming set and whose ``created_at`` falls on the KST
    operating date.

    ``held_position`` ``REDUCE/EXIT`` ``SELL`` orders are intentionally
    excluded because they use a dedicated budget lane and must not
    consume the general BUY/core submit budget.

    On any failure (connection error, query error, etc.), returns
    ``DEFAULT_MAX_GENERAL_BUY_SUBMIT_PER_DAY`` (conservative dry-run fallback).
    """
    import asyncpg

    from dotenv import load_dotenv

    load_dotenv()  # ensure .env loaded (idempotent)

    dsn = os.getenv("DATABASE_DSN")
    if dsn is None:
        host = os.getenv("DATABASE_HOST") or os.getenv("DB_HOST") or "localhost"
        port = os.getenv("DATABASE_PORT") or os.getenv("DB_PORT") or "5432"
        user = os.getenv("DATABASE_USER") or os.getenv("DB_USER") or "trading"
        password = os.getenv("DATABASE_PASSWORD") or os.getenv("DB_PASSWORD") or "trading"
        database = os.getenv("DATABASE_NAME") or os.getenv("DB_NAME") or "trading"
        dsn = f"postgresql://{user}:{password}@{host}:{port}/{database}"

    try:
        conn = await asyncpg.connect(dsn=dsn)
        try:
            # KST operating day boundaries
            kst_midnight = datetime.combine(run_date, dtime(0, 0, 0), tzinfo=KST)
            kst_end_of_day = kst_midnight + timedelta(days=1)

            row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS cnt
                FROM trading.order_requests o
                LEFT JOIN trading.trade_decisions td
                  ON o.trade_decision_id = td.trade_decision_id
                WHERE o.created_at >= $1
                  AND o.created_at < $2
                  AND o.status = ANY($3::text[])
                  AND td.side = 'buy'
                  AND NOT (
                    td.source_type = 'held_position'
                    AND td.decision_type IN ('reduce', 'exit')
                    AND td.side = 'sell'
                  )
                """,
                kst_midnight,
                kst_end_of_day,
                list(_BUDGET_CONSUMING_STATUSES),
            )
            count: int = row["cnt"] if row else 0
            logger.info(
                "db_general_buy_submit_count=%d run_date=%s statuses=%s",
                count,
                run_date.isoformat(),
                sorted(_BUDGET_CONSUMING_STATUSES),
            )
            return count
        finally:
            await conn.close()
    except Exception:
        logger.exception(
            "db_general_buy_submit_count query failed — conservative dry-run fallback"
        )
        return DEFAULT_MAX_GENERAL_BUY_SUBMIT_PER_DAY


async def _get_db_held_position_sell_count(run_date: date) -> int:
    """Query today's held_position REDUCE/EXIT sell submit count.

    ``trade_decisions`` 테이블과 JOIN하여 3중 조건을 모두 확인한다:
    1. ``td.source_type = 'held_position'``
    2. ``td.decision_type IN ('reduce', 'exit')``
    3. ``td.side = 'sell'``

    세 조건이 모두 충족되어야 held_position sell budget을 소비한 것으로 간주한다.
    이는 crash-safe한 budget 트래킹을 위해 DB 레벨에서도 동일한 조건을 적용한다.

    On any failure, returns 0 (held_position sell budget을 소비하지 않은 것으로 간주).
    """
    import asyncpg

    from dotenv import load_dotenv

    load_dotenv()

    dsn = os.getenv("DATABASE_DSN")
    if dsn is None:
        host = os.getenv("DATABASE_HOST") or os.getenv("DB_HOST") or "localhost"
        port = os.getenv("DATABASE_PORT") or os.getenv("DB_PORT") or "5432"
        user = os.getenv("DATABASE_USER") or os.getenv("DB_USER") or "trading"
        password = os.getenv("DATABASE_PASSWORD") or os.getenv("DB_PASSWORD") or "trading"
        database = os.getenv("DATABASE_NAME") or os.getenv("DB_NAME") or "trading"
        dsn = f"postgresql://{user}:{password}@{host}:{port}/{database}"

    try:
        conn = await asyncpg.connect(dsn=dsn)
        try:
            kst_midnight = datetime.combine(run_date, dtime(0, 0, 0), tzinfo=KST)
            kst_end_of_day = kst_midnight + timedelta(days=1)

            row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS cnt
                FROM trading.order_requests o
                JOIN trading.trade_decisions td ON o.trade_decision_id = td.trade_decision_id
                WHERE o.created_at >= $1
                  AND o.created_at < $2
                  AND o.status = ANY($3::text[])
                  AND td.source_type = 'held_position'
                  AND td.decision_type IN ('reduce', 'exit')
                  AND td.side = 'sell'
                """,
                kst_midnight,
                kst_end_of_day,
                list(_BUDGET_CONSUMING_STATUSES),
            )
            count: int = row["cnt"] if row else 0
            logger.info(
                "db_held_position_sell_count=%d run_date=%s",
                count,
                run_date.isoformat(),
            )
            return count
        finally:
            await conn.close()
    except Exception:
        logger.exception(
            "db_held_position_sell_count query failed — returning 0"
        )
        return 0


async def _run_command(
    name: str,
    argv: list[str],
    *,
    timeout_seconds: int,
    env: dict[str, str],
) -> CommandResult:
    """Run a subprocess command without using a shell."""
    start = time.monotonic()
    resolved_argv = list(argv)
    if resolved_argv:
        executable = resolved_argv[0]
        if os.path.sep not in executable:
            resolved_executable = shutil.which(executable) or sys.executable
            resolved_argv[0] = resolved_executable
    logger.info("task=%s start argv=%s", name, " ".join(resolved_argv))

    proc = await asyncio.create_subprocess_exec(
        *resolved_argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    timed_out = False
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        timed_out = True
        # timeout 후 partial stdout/stderr capture:
        # - read timeout 2→10초로 확대 (424초 누적 버퍼 수백 KB~MB 대응)
        # - tail 64KB trim: 전체 버퍼 대신 마지막 64KB tail만 보존 (decode 부하 최소화)
        # - 실패 시에도 logger.warning으로 가시성 확보
        partial_stdout = ""
        partial_stderr = ""
        try:
            if proc.stdout and not proc.stdout.at_eof():
                partial_stdout_bytes = await asyncio.wait_for(
                    proc.stdout.read(_MAX_PARTIAL_LOG_BYTES), timeout=_PARTIAL_READ_TIMEOUT
                )
                partial_stdout = partial_stdout_bytes.decode("utf-8", errors="replace")
                if partial_stdout:
                    logger.info(
                        "[PARTIAL_CAPTURE] stdout tail (%d bytes):\n%s",
                        len(partial_stdout_bytes), partial_stdout[:2000],
                    )
        except Exception as exc:
            logger.warning(
                "[PARTIAL_READ_FAILED] stdout partial read failed after timeout: %s", exc
            )
        try:
            if proc.stderr and not proc.stderr.at_eof():
                partial_stderr_bytes = await asyncio.wait_for(
                    proc.stderr.read(_MAX_PARTIAL_LOG_BYTES), timeout=_PARTIAL_READ_TIMEOUT
                )
                partial_stderr = partial_stderr_bytes.decode("utf-8", errors="replace")
                if partial_stderr:
                    logger.info(
                        "[PARTIAL_CAPTURE] stderr tail (%d bytes):\n%s",
                        len(partial_stderr_bytes), partial_stderr[:2000],
                    )
        except Exception as exc:
            logger.warning(
                "[PARTIAL_READ_FAILED] stderr partial read failed after timeout: %s", exc
            )
        if partial_stdout:
            logger.warning(
                "[PARTIAL_CAPTURE] Subprocess timed out — partial stdout "
                "(tail %d bytes):\n%s",
                min(len(partial_stdout.encode("utf-8")), _MAX_PARTIAL_LOG_BYTES),
                partial_stdout[-4096:],
            )
        if partial_stderr:
            logger.warning(
                "[PARTIAL_CAPTURE] Subprocess timed out — partial stderr "
                "(tail %d bytes):\n%s",
                min(len(partial_stderr.encode("utf-8")), _MAX_PARTIAL_LOG_BYTES),
                partial_stderr[-4096:],
            )
        # terminate → wait → kill (if needed)
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=3)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        stdout_b = partial_stdout.encode("utf-8")
        stderr_b = partial_stderr.encode("utf-8")

    duration = time.monotonic() - start
    result = CommandResult(
        name=name,
        argv=resolved_argv,
        returncode=proc.returncode if proc.returncode is not None else -1,
        duration_seconds=round(duration, 3),
        stdout=stdout_b.decode(errors="replace"),
        stderr=stderr_b.decode(errors="replace"),
        timed_out=timed_out,
    )

    level = logging.INFO if result.ok else logging.ERROR
    logger.log(
        level,
        "task=%s complete ok=%s returncode=%s timeout=%s duration=%.2fs",
        name,
        result.ok,
        result.returncode,
        result.timed_out,
        result.duration_seconds,
    )
    if result.stderr.strip():
        # Child scripts (e.g. run_snapshot_sync_loop.py) use logging.basicConfig()
        # which defaults to stderr.  A non-empty stderr does NOT indicate failure;
        # it often contains normal INFO-level log lines.
        #
        # - If returncode == 0: log stderr at INFO level (normal logging output).
        # - If returncode != 0: log stderr at ERROR level (likely actual errors).
        # - Additionally, if stderr contains Python traceback lines, always ERROR.
        _stderr_text = result.stderr.strip()
        _has_traceback = "Traceback" in _stderr_text or "Error:" in _stderr_text
        if result.returncode == 0 and not _has_traceback:
            logger.info("task=%s stderr:\n%s", name, _stderr_text)
        else:
            logger.error("task=%s stderr:\n%s", name, _stderr_text)
    if result.stdout.strip():
        logger.log(
            logging.ERROR if not result.ok else logging.DEBUG,
            "task=%s stdout:\n%s",
            name,
            result.stdout.strip(),
        )
    return result


def _snapshot_command(
    *,
    after_hours: bool = False,
    allow_after_hours_positions: bool = False,
) -> list[str]:
    argv = [PYTHON_BIN, "scripts/run_snapshot_sync_loop.py", "--max-cycles", "1"]
    if after_hours:
        argv.append("--after-hours")
    if allow_after_hours_positions:
        argv.append("--allow-after-hours-positions")
    return argv


def _event_command() -> list[str]:
    return [
        PYTHON_BIN,
        "-m",
        "scripts.run_event_ingestion_loop",
        "--count",
        "1",
        "--output",
        "json",
    ]


def _decision_command(
    *,
    dry_run: bool,
    allow_general_submit: bool = True,
    max_general_submits_this_cycle: int = 1,
) -> list[str]:
    argv = [
        PYTHON_BIN,
        "-m",
        "scripts.run_decision_loop",
        "--count",
        "1",
        "--output",
        "json",
        "--max-general-submits-this-cycle",
        str(max(0, max_general_submits_this_cycle)),
    ]
    if dry_run:
        argv.append("--dry-run")
    else:
        argv.append("--submit")
    if not allow_general_submit:
        argv.append("--no-allow-general-submit")
    return argv


def _post_submit_command(*, after_hours: bool = False, recovery: bool = False) -> list[str]:
    argv = [PYTHON_BIN, "scripts/run_post_submit_sync_loop.py", "--once"]
    # recovery=True는 항상 after-hours를 수반한다 (EXPIRED fallback 허용 조건)
    effective_after_hours = after_hours or recovery
    if effective_after_hours:
        argv.append("--after-hours")
    if recovery:
        argv.append("--recovery")
    return argv


def _fill_sync_command(*, after_hours: bool = False) -> list[str]:
    argv = [PYTHON_BIN, "scripts/run_fill_sync_loop.py", "--once"]
    if after_hours:
        argv.append("--after-hours")
    return argv


def _signal_feature_snapshot_command(
    *,
    input_path: str,
) -> list[str]:
    spec = SignalFeatureBatchRuntimeSpec(
        command_name_prefix="after_market_signal_feature",
        input_path=input_path,
        freeze_purpose=DEFAULT_SIGNAL_FEATURE_AFTER_MARKET_FREEZE_PURPOSE,
        trigger_type=DEFAULT_SIGNAL_FEATURE_AFTER_MARKET_TRIGGER_TYPE,
    )
    return spec.build_batch_command(python_bin=PYTHON_BIN, input_path=input_path)


def _signal_feature_snapshot_retry_input_path(input_path: str) -> str:
    spec = SignalFeatureBatchRuntimeSpec(
        command_name_prefix="after_market_signal_feature",
        input_path=input_path,
        freeze_purpose=DEFAULT_SIGNAL_FEATURE_AFTER_MARKET_FREEZE_PURPOSE,
        trigger_type=DEFAULT_SIGNAL_FEATURE_AFTER_MARKET_TRIGGER_TYPE,
    )
    return spec.retry_input_path


def _instrument_master_sync_command(
    *,
    csv_path: str,
) -> list[str]:
    return [
        PYTHON_BIN,
        str((_repo_root() / "scripts/sync_kis_instrument_master.py").resolve()),
        "--csv",
        csv_path,
        "--apply",
    ]


def _instrument_status_snapshot_command(
    *,
    freeze_purposes: Sequence[str],
) -> list[str]:
    argv = [
        PYTHON_BIN,
        str((_repo_root() / "scripts/build_instrument_status_snapshots.py").resolve()),
        "--output",
        "json",
    ]
    for purpose in freeze_purposes:
        argv.extend(["--freeze-purpose", str(purpose)])
    return argv


def _build_instrument_master_sync_csv_command(
    *,
    input_paths: list[str],
    output_path: str,
    archive_dir: str,
    archive_label: str,
) -> list[str]:
    argv = [
        PYTHON_BIN,
        str((_repo_root() / "scripts/build_kis_instrument_master_sync_csv.py").resolve()),
    ]
    for path in input_paths:
        argv.extend(["--input", path])
    argv.extend(
        [
            "--output",
            output_path,
            "--archive-dir",
            archive_dir,
            "--archive-label",
            archive_label,
        ]
    )
    return argv


def _generate_signal_feature_snapshot_input_command(
    *,
    output_path: str,
    retry_from_input: str | None = None,
) -> list[str]:
    spec = SignalFeatureBatchRuntimeSpec(
        command_name_prefix="after_market_signal_feature",
        input_path=output_path,
        freeze_purpose=DEFAULT_SIGNAL_FEATURE_AFTER_MARKET_FREEZE_PURPOSE,
        trigger_type=DEFAULT_SIGNAL_FEATURE_AFTER_MARKET_TRIGGER_TYPE,
    )
    return spec.build_input_command(
        python_bin=PYTHON_BIN,
        output_path=output_path,
        retry_from_input=retry_from_input,
    )


def _trigger_proxy_attribution_command(
    *,
    run_date: date,
    lookback_days: int,
    output_path: str,
) -> list[str]:
    start_date = run_date - timedelta(days=max(lookback_days - 1, 0))
    return [
        PYTHON_BIN,
        str((_repo_root() / "scripts/analyze_trigger_proxy_attribution.py").resolve()),
        "--start-date",
        start_date.isoformat(),
        "--end-date",
        run_date.isoformat(),
        "--output",
        "json",
        "--write-json",
        output_path,
    ]


async def _run_and_record(
    state: SchedulerState,
    name: str,
    argv: list[str],
    *,
    timeout_seconds: int,
    env: dict[str, str],
) -> CommandResult:
    # KIS subprocess pacing-delay 로깅 (디버깅/운영 가시성용)
    if name in ("snapshot_sync", "post_submit_sync", "decision_submit_gate", "decision_dry_run"):
        logger.info("[pacing] Starting KIS subprocess: %s", name)

    result = await _run_command(
        name,
        argv,
        timeout_seconds=timeout_seconds,
        env=env,
    )

    if name in ("snapshot_sync", "post_submit_sync", "decision_submit_gate", "decision_dry_run"):
        logger.info(
            "[pacing] Completed KIS subprocess: %s (rc=%s, %.1fs)",
            name,
            result.returncode,
            result.duration_seconds,
        )

    state.command_results.append(result)
    return result


async def _run_pre_market(
    state: SchedulerState,
    *,
    timeout_seconds: int,
    env: dict[str, str],
    dsn: str | None = None,
) -> None:
    """Run one-time pre-market preparation tasks.

    After snapshot sync, validates that both cash and position snapshots
    were successfully refreshed. Logs a warning if cash sync is missing
    (e.g., KIS API not yet available before market open).
    """
    logger.info("phase=pre-market start")

    # ── Step 1: Snapshot sync ──────────────────────────────────────────
    snap_result = await _run_and_record(
        state,
        "pre_snapshot_sync",
        _snapshot_command(),
        timeout_seconds=timeout_seconds,
        env=env,
    )

    # Validate snapshot sync result: cash must be synced
    snap_metrics = _parse_snapshot_sync_summary(snap_result)
    if snap_metrics:
        total_cash = snap_metrics.get("total_cash_synced", 0)
        total_accounts = snap_metrics.get("total_accounts", 0)
        if total_cash == 0 and total_accounts > 0:
            logger.warning(
                "pre-market snapshot sync: cash_synced=0 accounts=%d "
                "positions=%d — KIS API may not yet return cash balance "
                "before market open. Stale-snapshot guardrail will block "
                "submits until cash is refreshed.",
                total_accounts,
                snap_metrics.get("total_positions_synced", 0),
            )
        elif total_cash > 0:
            logger.info(
                "pre-market snapshot sync: cash_synced=%d accounts=%d positions=%d",
                total_cash,
                total_accounts,
                snap_metrics.get("total_positions_synced", 0),
            )
    else:
        logger.warning(
            "pre-market snapshot sync: could not parse sync summary from stdout. "
            "task=%s returncode=%s",
            snap_result.name,
            snap_result.returncode,
        )

    # ── Step 2: Event ingestion ────────────────────────────────────────
    await _run_and_record(
        state,
        "pre_event_ingestion",
        _event_command(),
        timeout_seconds=timeout_seconds,
        env=env,
    )

    # ── Step 3: Post-submit sync ───────────────────────────────────────
    await _run_and_record(
        state,
        "pre_post_submit_sync",
        _post_submit_command(),
        timeout_seconds=timeout_seconds,
        env=env,
    )

    await _run_and_record(
        state,
        "pre_fill_sync",
        _fill_sync_command(),
        timeout_seconds=timeout_seconds,
        env=env,
    )

    state.pre_market_done = True
    await _persist_operations_day_run(state, dsn)
    logger.info("phase=pre-market complete")


async def _run_instrument_master_sync(
    state: SchedulerState,
    *,
    timeout_seconds: int,
    env: dict[str, str],
    source_csv_paths: list[str],
    csv_path: str,
    archive_dir: str,
    run_date: date,
    dsn: str | None = None,
) -> None:
    """Run one-time pre-market instrument master sync."""
    resolved_source_csv_paths = [
        _resolve_repo_path(path) for path in source_csv_paths
    ]
    resolved_csv_path = _resolve_repo_path(csv_path)
    resolved_archive_dir = _resolve_repo_path(archive_dir)
    existing_inputs = [
        path for path in resolved_source_csv_paths if Path(path).exists()
    ]
    if not existing_inputs:
        state.command_results.append(
            _build_skip_command_result(
                name="instrument_master_sync",
                argv=_instrument_master_sync_command(csv_path=resolved_csv_path),
                skipped_reason="no_source_csv",
                details={
                    "source_csv_paths": resolved_source_csv_paths,
                    "resolved_csv_path": resolved_csv_path,
                },
            )
        )
        logger.warning(
            "phase=instrument-master-sync skipped — no source csv found: %s",
            ",".join(resolved_source_csv_paths),
        )
        await _persist_operations_day_run(state, dsn)
        return

    logger.info(
        "phase=instrument-master-sync normalize start inputs=%s output=%s",
        ",".join(existing_inputs),
        resolved_csv_path,
    )
    normalize_result = await _run_and_record(
        state,
        "instrument_master_normalize",
        _build_instrument_master_sync_csv_command(
            input_paths=existing_inputs,
            output_path=resolved_csv_path,
            archive_dir=resolved_archive_dir,
            archive_label=run_date.isoformat(),
        ),
        timeout_seconds=timeout_seconds,
        env=env,
    )
    if not normalize_result.ok:
        await _persist_operations_day_run(state, dsn)
        logger.warning(
            "phase=instrument-master-normalize failed — will retry on next tick"
        )
        return

    csv_file = Path(resolved_csv_path)
    if not csv_file.exists():
        state.command_results.append(
            _build_skip_command_result(
                name="instrument_master_sync",
                argv=_instrument_master_sync_command(csv_path=resolved_csv_path),
                skipped_reason="normalized_csv_missing",
                details={
                    "resolved_csv_path": resolved_csv_path,
                },
            )
        )
        logger.warning(
            "phase=instrument-master-sync skipped — normalized csv not produced: %s",
            resolved_csv_path,
        )
        await _persist_operations_day_run(state, dsn)
        return

    logger.info(
        "phase=instrument-master-sync start csv=%s",
        resolved_csv_path,
    )
    result = await _run_and_record(
        state,
        "instrument_master_sync",
        _instrument_master_sync_command(csv_path=resolved_csv_path),
        timeout_seconds=timeout_seconds,
        env=env,
    )
    if not result.ok:
        await _persist_operations_day_run(state, dsn)
        logger.warning(
            "phase=instrument-master-sync failed — will retry on next tick"
        )
        return
    state.instrument_master_sync_done = True
    await _persist_operations_day_run(state, dsn)
    logger.info("phase=instrument-master-sync complete")


async def _mark_instrument_master_sync_missed(
    state: SchedulerState,
    *,
    now: datetime,
    instrument_master_sync_at: datetime,
    intraday_at: datetime,
    dsn: str | None = None,
) -> None:
    """장전 instrument master sync window 누락을 1회만 기록한다."""
    if state.instrument_master_sync_done or state.instrument_master_sync_missed:
        return
    if _latest_command_result(state, {"instrument_master_sync", "instrument_master_normalize"}) is not None:
        return

    state.instrument_master_sync_missed = True
    state.command_results.append(
        _build_skip_command_result(
            name="instrument_master_sync",
            argv=_instrument_master_sync_command(
                csv_path=_resolve_repo_path(DEFAULT_INSTRUMENT_MASTER_SYNC_CSV_PATH),
            ),
            skipped_reason="missed_pre_market_window",
            details={
                "now_kst": now.isoformat(),
                "scheduled_at_kst": instrument_master_sync_at.isoformat(),
                "intraday_start_kst": intraday_at.isoformat(),
            },
        )
    )
    logger.warning(
        "phase=instrument-master-sync missed — scheduler started after pre-market window "
        "(now=%s scheduled=%s intraday_start=%s)",
        now.isoformat(),
        instrument_master_sync_at.isoformat(),
        intraday_at.isoformat(),
    )
    await _persist_operations_day_run(state, dsn)


async def _run_instrument_status_snapshot(
    state: SchedulerState,
    *,
    timeout_seconds: int,
    env: dict[str, str],
    freeze_purposes: Sequence[str],
    dsn: str | None = None,
) -> None:
    """Run one-time pre-market instrument status snapshot batch."""
    logger.info(
        "phase=instrument-status-snapshot start freeze_purposes=%s",
        ",".join(str(item) for item in freeze_purposes),
    )
    result = await _run_and_record(
        state,
        "instrument_status_snapshot",
        _instrument_status_snapshot_command(
            freeze_purposes=freeze_purposes,
        ),
        timeout_seconds=timeout_seconds,
        env=env,
    )
    if not result.ok:
        await _persist_operations_day_run(state, dsn)
        logger.warning(
            "phase=instrument-status-snapshot failed — will retry on next tick"
        )
        return
    state.instrument_status_snapshot_done = True
    await _persist_operations_day_run(state, dsn)
    logger.info("phase=instrument-status-snapshot complete")


async def _mark_instrument_status_snapshot_missed(
    state: SchedulerState,
    *,
    now: datetime,
    instrument_status_snapshot_at: datetime,
    intraday_at: datetime,
    dsn: str | None = None,
) -> None:
    """장전 instrument status snapshot window 누락을 1회만 기록한다."""
    if state.instrument_status_snapshot_done or state.instrument_status_snapshot_missed:
        return
    if _latest_command_result(state, {"instrument_status_snapshot"}) is not None:
        return

    state.instrument_status_snapshot_missed = True
    state.command_results.append(
        _build_skip_command_result(
            name="instrument_status_snapshot",
            argv=_instrument_status_snapshot_command(
                freeze_purposes=DEFAULT_INSTRUMENT_STATUS_SNAPSHOT_FREEZE_PURPOSES,
            ),
            skipped_reason="missed_pre_market_window",
            details={
                "now_kst": now.isoformat(),
                "scheduled_at_kst": instrument_status_snapshot_at.isoformat(),
                "intraday_start_kst": intraday_at.isoformat(),
            },
        )
    )
    logger.warning(
        "phase=instrument-status-snapshot missed — scheduler started after pre-market window "
        "(now=%s scheduled=%s intraday_start=%s)",
        now.isoformat(),
        instrument_status_snapshot_at.isoformat(),
        intraday_at.isoformat(),
    )
    await _persist_operations_day_run(state, dsn)


async def _run_end_of_day(
    state: SchedulerState,
    *,
    timeout_seconds: int,
    env: dict[str, str],
    snapshot_interval: int = DEFAULT_SNAPSHOT_INTERVAL_SECONDS,
    dsn: str | None = None,
) -> None:
    """Run one-time end-of-day finalization tasks.

    After the initial EOD snapshot and post-submit sync, transitions
    into after-hours mode where only snapshot sync continues at regular
    intervals (no decision loop, no event ingestion, no post-submit-sync).
    """
    logger.info("phase=end-of-day start")
    state.after_hours_full_snapshot_done = False
    snap_result = await _run_and_record(
        state,
        "eod_snapshot_sync",
        _snapshot_command(
            after_hours=True,
            allow_after_hours_positions=True,
        ),
        timeout_seconds=timeout_seconds,
        env=env,
    )
    snap_metrics = _parse_snapshot_sync_summary(snap_result)
    if snap_result.ok and snap_metrics.get("total_positions_synced", 0) > 0:
        state.after_hours_full_snapshot_done = True
    await _run_and_record(
        state,
        "eod_post_submit_sync",
        _post_submit_command(after_hours=True),
        timeout_seconds=timeout_seconds,
        env=env,
    )
    await _run_and_record(
        state,
        "eod_fill_sync",
        _fill_sync_command(after_hours=True),
        timeout_seconds=timeout_seconds,
        env=env,
    )
    state.end_of_day_done = True
    # Enter after-hours mode: continue snapshot sync only
    state.after_hours_mode = True
    now = datetime.now(KST)
    state.after_hours_next_snapshot_at = now + timedelta(seconds=snapshot_interval)
    await _persist_operations_day_run(state, dsn)
    logger.info(
        "phase=end-of-day complete — entering after-hours snapshot mode "
        "(next snapshot at %s, interval=%ds, window=%ds)",
        state.after_hours_next_snapshot_at.isoformat(),
        snapshot_interval,
        AFTER_HOURS_SNAPSHOT_WINDOW_SECONDS,
    )


async def _run_after_hours_snapshot_cycle(
    state: SchedulerState,
    *,
    timeout_seconds: int,
    env: dict[str, str],
    now: datetime,
    dsn: str | None = None,
) -> None:
    """Run a single after-hours snapshot sync cycle.

    Only snapshot sync is performed — no decision loop, event ingestion,
    or post-submit-sync runs during after-hours.

    This is called from the main loop when ``state.after_hours_mode`` is
    True and the snapshot timer has elapsed.
    """
    if state.after_hours_next_snapshot_at is None or now < state.after_hours_next_snapshot_at:
        return
    allow_after_hours_positions = not state.after_hours_full_snapshot_done
    logger.info(
        "phase=after-hours snapshot cycle due at %s (allow_after_hours_positions=%s)",
        now.isoformat(),
        allow_after_hours_positions,
    )
    result = await _run_and_record(
        state,
        "after_hours_snapshot_sync",
        _snapshot_command(
            after_hours=True,
            allow_after_hours_positions=allow_after_hours_positions,
        ),
        timeout_seconds=timeout_seconds,
        env=env,
    )
    metrics = _parse_snapshot_sync_summary(result)
    if result.ok and metrics.get("total_positions_synced", 0) > 0:
        state.after_hours_full_snapshot_done = True
    # Schedule next after-hours snapshot
    state.after_hours_next_snapshot_at = now + timedelta(
        seconds=DEFAULT_SNAPSHOT_INTERVAL_SECONDS,
    )
    await _persist_operations_day_run(state, dsn)
    logger.info(
        "after-hours snapshot cycle complete — next at %s",
        state.after_hours_next_snapshot_at.isoformat(),
    )


async def _run_after_market_signal_feature_batch(
    state: SchedulerState,
    *,
    timeout_seconds: int,
    env: dict[str, str],
    now: datetime,
    signal_feature_batch_at: dtime = DEFAULT_SIGNAL_FEATURE_BATCH_TIME,
    signal_feature_input_path: str = "data/signal_feature_snapshot_input.json",
    dsn: str | None = None,
) -> None:
    """Run one signal feature snapshot batch at the configured post-close time."""
    if state.signal_feature_batch_done:
        return
    trigger_at = _combine(state.run_date, signal_feature_batch_at)
    if now < trigger_at:
        return
    await _run_signal_feature_batch_runtime(
        state,
        timeout_seconds=timeout_seconds,
        env=env,
        dsn=dsn,
        runtime_spec=SignalFeatureBatchRuntimeSpec(
            command_name_prefix="after_market_signal_feature",
            input_path=signal_feature_input_path,
            freeze_purpose=DEFAULT_SIGNAL_FEATURE_AFTER_MARKET_FREEZE_PURPOSE,
            trigger_type=DEFAULT_SIGNAL_FEATURE_AFTER_MARKET_TRIGGER_TYPE,
        ),
        completion_flag_attr="signal_feature_batch_done",
        phase_label="after-market",
        log_input_path=signal_feature_input_path,
        now=now,
    )


async def _run_signal_feature_batch_runtime(
    state: SchedulerState,
    *,
    timeout_seconds: int,
    env: dict[str, str],
    dsn: str | None,
    runtime_spec: SignalFeatureBatchRuntimeSpec,
    completion_flag_attr: str,
    phase_label: str,
    log_input_path: str,
    now: datetime,
) -> None:
    logger.info(
        "phase=%s signal feature batch start at %s (input=%s trigger_type=%s freeze_purpose=%s)",
        phase_label,
        now.isoformat(),
        log_input_path,
        runtime_spec.trigger_type,
        runtime_spec.freeze_purpose,
    )
    input_result = await _run_and_record(
        state,
        runtime_spec.primary_input_name,
        runtime_spec.build_input_command(
            python_bin=PYTHON_BIN,
            output_path=runtime_spec.input_path,
        ),
        timeout_seconds=timeout_seconds,
        env=env,
    )
    if not input_result.ok:
        await _persist_operations_day_run(state, dsn)
        logger.warning(
            "phase=%s signal feature input failed — will retry on next tick",
            phase_label,
        )
        return

    batch_result = await _run_and_record(
        state,
        runtime_spec.primary_batch_name,
        runtime_spec.build_batch_command(
            python_bin=PYTHON_BIN,
            input_path=runtime_spec.input_path,
        ),
        timeout_seconds=timeout_seconds,
        env=env,
    )
    if not batch_result.ok:
        await _persist_operations_day_run(state, dsn)
        logger.warning(
            "phase=%s signal feature batch failed — will retry on next tick",
            phase_label,
        )
        return

    input_metrics = _parse_signal_feature_input_summary(input_result)
    if should_run_signal_feature_tail_retry(input_metrics):
        retry_input_result = await _run_and_record(
            state,
            runtime_spec.retry_input_name,
            runtime_spec.build_input_command(
                python_bin=PYTHON_BIN,
                output_path=runtime_spec.retry_input_path,
                retry_from_input=runtime_spec.input_path,
            ),
            timeout_seconds=timeout_seconds,
            env=env,
        )
        if not retry_input_result.ok:
            await _persist_operations_day_run(state, dsn)
            logger.warning(
                "phase=%s signal feature tail-retry input failed — will retry on next tick",
                phase_label,
            )
            return

        retry_input_metrics = _parse_signal_feature_input_summary(retry_input_result)
        if should_run_signal_feature_retry_batch(retry_input_metrics):
            retry_batch_result = await _run_and_record(
                state,
                runtime_spec.retry_batch_name,
                runtime_spec.build_batch_command(
                    python_bin=PYTHON_BIN,
                    input_path=runtime_spec.retry_input_path,
                ),
                timeout_seconds=timeout_seconds,
                env=env,
            )
            if not retry_batch_result.ok:
                await _persist_operations_day_run(state, dsn)
                logger.warning(
                    "phase=%s signal feature tail-retry batch failed — will retry on next tick",
                    phase_label,
                )
                return

    setattr(state, completion_flag_attr, True)
    await _persist_operations_day_run(state, dsn)
    logger.info("phase=%s signal feature batch complete", phase_label)


async def _run_after_market_trigger_proxy_attribution(
    state: SchedulerState,
    *,
    timeout_seconds: int,
    env: dict[str, str],
    dsn: str | None,
) -> None:
    if state.trigger_proxy_attribution_done:
        return
    if not state.signal_feature_batch_done:
        return

    output_path = (
        _repo_root() / "logs" / f"trigger_proxy_attribution_{state.run_date.isoformat()}.json"
    )
    logger.info(
        "phase=after-market trigger proxy attribution start run_date=%s output=%s",
        state.run_date.isoformat(),
        output_path,
    )
    result = await _run_and_record(
        state,
        "after_market_trigger_proxy_attribution",
        _trigger_proxy_attribution_command(
            run_date=state.run_date,
            lookback_days=DEFAULT_TRIGGER_PROXY_ATTRIBUTION_LOOKBACK_DAYS,
            output_path=str(output_path),
        ),
        timeout_seconds=timeout_seconds,
        env=env,
    )
    if not result.ok:
        await _persist_operations_day_run(state, dsn)
        logger.warning(
            "phase=after-market trigger proxy attribution failed — will retry on next tick",
        )
        return

    state.trigger_proxy_attribution_done = True
    await _persist_operations_day_run(state, dsn)
    logger.info("phase=after-market trigger proxy attribution complete")


async def _ensure_decision_loop_intraday_freeze(
    state: SchedulerState,
    *,
    dsn: str | None = None,
) -> None:
    """Ensure today's intraday decision-loop universe freeze exists."""
    if state.intraday_universe_freeze_done:
        return

    freeze_run_date = _resolve_intraday_freeze_run_date(state.run_date)

    async with postgres_runtime(run_migrations=False) as runtime:
        repos = runtime["repositories"]
        existing_run = await repos.universe_freeze_runs.get_latest(
            freeze_run_date,
            DEFAULT_DECISION_LOOP_INTRADAY_FREEZE_PURPOSE,
        )
        if existing_run is not None:
            existing_items = await repos.universe_freeze_run_items.list_by_run(
                existing_run.universe_freeze_run_id
            )
            if existing_items:
                state.intraday_universe_freeze_done = True
                await _persist_operations_day_run(state, dsn)
                logger.info(
                    "decision loop intraday freeze reused "
                    "(freeze_run_id=%s, target_count=%d, run_date=%s)",
                    existing_run.universe_freeze_run_id,
                    len(existing_items),
                    freeze_run_date.isoformat(),
                )
                return

    try:
        from scripts.run_decision_loop import _load_trading_universe_with_anchor
    except ModuleNotFoundError:
        # ops-scheduler 컨테이너는 PYTHONPATH에 /app/scripts 만 포함될 수 있어
        # 패키지 import(`scripts.run_decision_loop`)가 깨질 수 있다.
        from run_decision_loop import _load_trading_universe_with_anchor

    universe, universe_anchor = await _load_trading_universe_with_anchor()
    if not universe:
        logger.warning(
            "decision loop intraday freeze skipped: composed universe empty "
            "(run_date=%s)",
            freeze_run_date.isoformat(),
        )
        return

    async with postgres_runtime(run_migrations=False) as runtime:
        repos = runtime["repositories"]
        existing_run = await repos.universe_freeze_runs.get_latest(
            freeze_run_date,
            DEFAULT_DECISION_LOOP_INTRADAY_FREEZE_PURPOSE,
        )
        if existing_run is not None:
            existing_items = await repos.universe_freeze_run_items.list_by_run(
                existing_run.universe_freeze_run_id
            )
            if existing_items:
                state.intraday_universe_freeze_done = True
                await _persist_operations_day_run(state, dsn)
                logger.info(
                    "decision loop intraday freeze reused after compose "
                    "(freeze_run_id=%s, target_count=%d, run_date=%s)",
                    existing_run.universe_freeze_run_id,
                    len(existing_items),
                    freeze_run_date.isoformat(),
                )
                return

        freeze_run_id = uuid4()
        freeze_items: list[UniverseFreezeRunItemEntity] = []
        errors: list[str] = []
        for rank, item in enumerate(universe, start=1):
            instrument = await repos.instruments.get_by_symbol(
                symbol=item.symbol,
                market_code=item.market,
            )
            if instrument is None:
                instrument = await repos.instruments.get_by_symbol_any_market(
                    item.symbol
                )
            if instrument is None:
                errors.append(f"{item.symbol}:{item.market}:instrument_not_found_for_freeze")
                continue
            freeze_items.append(
                UniverseFreezeRunItemEntity(
                    universe_freeze_run_item_id=uuid4(),
                    universe_freeze_run_id=freeze_run_id,
                    instrument_id=instrument.instrument_id,
                    symbol=item.symbol,
                    market_code=item.market,
                    source_type=item.source_type,
                    inclusion_reason=item.inclusion_reason,
                    rank=rank,
                    cap_bucket=item.source_type,
                    metadata_json={},
                )
            )

        freeze_items, skipped_duplicates = dedupe_universe_freeze_run_items(
            freeze_items
        )

        if not freeze_items:
            logger.warning(
                "decision loop intraday freeze materialization failed: no_items "
                "(run_date=%s, errors=%s)",
                freeze_run_date.isoformat(),
                errors[:5],
            )
            return

        source_type_counts: dict[str, int] = {}
        for item in universe:
            source_type_counts[item.source_type] = (
                source_type_counts.get(item.source_type, 0) + 1
            )

        freeze_run = UniverseFreezeRunEntity(
            universe_freeze_run_id=freeze_run_id,
            business_date=freeze_run_date,
            freeze_purpose=DEFAULT_DECISION_LOOP_INTRADAY_FREEZE_PURPOSE,
            freeze_sequence=1 if existing_run is None else existing_run.freeze_sequence + 1,
            frozen_at=datetime.now(timezone.utc),
            selection_version="decision_loop_intraday.freeze.v1",
            selection_params_json={
                "source": "ops_scheduler",
                "target_count": len(universe),
                "resolved_run_date": freeze_run_date.isoformat(),
                "universe_anchor": {
                    "source": universe_anchor.source,
                    "universe_freeze_run_id": universe_anchor.universe_freeze_run_id,
                    "freeze_purpose": universe_anchor.freeze_purpose,
                    "freeze_reused": universe_anchor.freeze_reused,
                    "business_date": universe_anchor.business_date,
                },
                "source_type_counts": source_type_counts,
            },
            target_count=len(freeze_items),
            status="materialized",
        )
        await repos.universe_freeze_runs.add(freeze_run)
        await repos.universe_freeze_run_items.add_many(freeze_items)

    state.intraday_universe_freeze_done = True
    await _persist_operations_day_run(state, dsn)
    logger.info(
        "decision loop intraday freeze materialized "
        "(freeze_run_id=%s, target_count=%d, skipped=%d, run_date=%s, anchor_source=%s)",
        freeze_run_id,
        len(freeze_items),
        len(errors) + skipped_duplicates,
        freeze_run_date.isoformat(),
        universe_anchor.source,
    )


async def _run_intraday_due_tasks(
    state: SchedulerState,
    tasks: dict[str, ScheduledTask],
    *,
    max_general_buy_submit_per_day: int,
    held_position_sell_max_per_day: int,
    timeout_seconds: int,
    env: dict[str, str],
    now: datetime,
    decision_interval: int = 300,
    dsn: str | None = None,
) -> None:
    """Run due intraday periodic tasks sequentially.

    Note: snapshot_sync is handled in the main loop to decouple
    its cadence from decision_submit_gate's potential long runtime.
    """
    if tasks["event"].due:
        await _run_and_record(
            state,
            "event_ingestion",
            _event_command(),
            timeout_seconds=timeout_seconds,
            env=env,
        )
        completed_at = datetime.now(KST)
        tasks["event"].mark_ran(completed_at)

    if tasks["decision"].due:
        await _ensure_decision_loop_intraday_freeze(state, dsn=dsn)

        # DB-based submit budget check (survives process crash/restart)
        db_submit_count = await _get_db_submit_count(state.run_date)
        effective_submit_count = max(state.submit_count, db_submit_count)

        # held_position REDUCE/EXIT sell은 별도 budget으로 관리
        db_hp_sell_count = await _get_db_held_position_sell_count(state.run_date)
        effective_hp_sell_count = max(
            state.held_position_sell_submit_count, db_hp_sell_count
        )

        # 일반 submit budget이 남았으면 submit 허용
        general_budget_ok = (
            effective_submit_count < max_general_buy_submit_per_day
        )
        remaining_general_submit_budget = max(
            0,
            max_general_buy_submit_per_day - effective_submit_count,
        )

        # held_position REDUCE/EXIT sell은 위험 축소 목적이므로 일일 제출 상한에 묶이지 않음.
        # 항상 submit path 진입 가능 (일반 BUY budget과 독립적).
        hp_sell_budget_ok = True  # held_position sell은 항상 허용

        # dry_run = 일반 budget도 없고 held_position sell budget도 없을 때
        # hp_sell_budget_ok가 항상 True이므로, held_position sell 모드에서는
        # dry_run이 절대 발생하지 않음 (일반 BUY만 budget 소진 시 dry-run)
        dry_run = not general_budget_ok and not hp_sell_budget_ok

        # decision_submit_gate timeout: must accommodate all universe symbols
        # running concurrently via asyncio.gather() with semaphore(5).
        # 장중 실측상 정상 완료도 160~185초 수준이며, 일부 symbol의
        # EI fallback/held_position 경로가 겹치면 300초는 너무 타이트하다.
        # 운영 안정성 우선으로 scheduler-level timeout을 별도 상향하고,
        # 필요 시 env로 미세 조정 가능하게 둔다.
        _DECISION_TIMEOUT = int(
            os.environ.get(
                "OPS_SCHEDULER_DECISION_TIMEOUT_SECONDS",
                str(DEFAULT_DECISION_SUBMIT_TIMEOUT_SECONDS),
            )
        )

        # ★ CADENCE_TRACE: decision_submit_gate start
        last_run = tasks["decision"].last_run_at or now
        gap = (now - last_run).total_seconds()
        logger.info(
            "CADENCE_TRACE decision_submit_gate symbol=ALL "
            "action=start due_at=%s last_run_gap=%.0fs target_interval=%ds drift=%.0fs",
            now.isoformat(), gap, decision_interval, gap - decision_interval,
        )

        allow_general_submit = general_budget_ok
        result = await _run_and_record(
            state,
            "decision_dry_run" if dry_run else "decision_submit_gate",
            _decision_command(
                dry_run=dry_run,
                allow_general_submit=allow_general_submit,
                max_general_submits_this_cycle=remaining_general_submit_budget,
            ),
            timeout_seconds=min(timeout_seconds, _DECISION_TIMEOUT),
            env=env,
        )
        if not dry_run and _is_submit_consuming_result(result):
            if _is_held_position_sell_result(result):
                state.held_position_sell_submit_count += 1
                logger.warning(
                    "held_position sell submit budget consumed: "
                    "hp_sell_count=%d db_hp_sell_count=%d "
                    "effective_hp=%d max_hp=%d",
                    state.held_position_sell_submit_count,
                    db_hp_sell_count,
                    effective_hp_sell_count,
                    held_position_sell_max_per_day,
                )
            else:
                state.submit_count += 1
                logger.warning(
                    "general BUY submit budget consumed: submit_count=%d "
                    "db_submit_count=%d effective=%d max=%d",
                    state.submit_count,
                    db_submit_count,
                    effective_submit_count,
                    max_general_buy_submit_per_day,
                )
        completed_at = datetime.now(KST)
        tasks["decision"].mark_ran(completed_at)

        # ★ CADENCE_TRACE: decision_submit_gate complete
        logger.info(
            "CADENCE_TRACE decision_submit_gate symbol=ALL "
            "action=complete completed_at=%s actual_duration=%.1fs next_at=%s",
            completed_at.isoformat(),
            (completed_at - now).total_seconds(),
            tasks["decision"].next_run_at.isoformat(),
        )

        # Persist immediately after decision loop completion so the first
        # intraday submit-gate result is visible in ``operations_day_runs``
        # even before later tasks in the same cycle complete.
        await _persist_operations_day_run(state, dsn)

    if tasks["post_submit"].due:
        await _run_and_record(
            state,
            "post_submit_sync",
            _post_submit_command(),
            timeout_seconds=timeout_seconds,
            env=env,
        )
        completed_at = datetime.now(KST)
        tasks["post_submit"].mark_ran(completed_at)

    if tasks["fill_sync"].due:
        await _run_and_record(
            state,
            "fill_sync",
            _fill_sync_command(),
            timeout_seconds=timeout_seconds,
            env=env,
        )
        completed_at = datetime.now(KST)
        tasks["fill_sync"].mark_ran(completed_at)

    await _persist_operations_day_run(state, dsn)


def _build_tasks(
    now: datetime,
    *,
    snapshot_interval: int,
    event_interval: int,
    decision_interval: int,
    post_submit_interval: int,
    fill_sync_interval: int = DEFAULT_FILL_SYNC_INTERVAL_SECONDS,
) -> dict[str, ScheduledTask]:
    """Build initial periodic task state."""
    return {
        "snapshot": ScheduledTask("snapshot", snapshot_interval, now),
        "event": ScheduledTask("event", event_interval, now),
        "decision": ScheduledTask("decision", decision_interval, now),
        "post_submit": ScheduledTask("post_submit", post_submit_interval, now),
        "fill_sync": ScheduledTask("fill_sync", fill_sync_interval, now),
    }


def _log_summary(state: SchedulerState) -> None:
    """Log end-of-process summary."""
    total = len(state.command_results)
    failed = [r for r in state.command_results if not r.ok]
    logger.info("=" * 72)
    logger.info("ops-scheduler summary")
    logger.info("  run_date            : %s", state.run_date.isoformat())
    logger.info("  cycles              : %d", state.cycles)
    logger.info("  tasks               : %d", total)
    logger.info("  failed_tasks         : %d", len(failed))
    logger.info("  submit_count         : %d", state.submit_count)
    logger.info("  hp_sell_submit_count : %d", state.held_position_sell_submit_count)
    logger.info("  pre_market_done      : %s", state.pre_market_done)
    logger.info("  end_of_day_done      : %s", state.end_of_day_done)
    logger.info("  after_hours_active   : %s", state.after_hours_mode)
    if state.session_info:
        logger.info("  session_source       : %s", state.session_info.source)
        logger.info("  session_opnd_yn      : %s", state.session_info.opnd_yn)
        logger.info("  session_bzdy_yn      : %s", state.session_info.bzdy_yn)
        logger.info("  session_tr_day_yn    : %s", state.session_info.tr_day_yn)
        logger.info("  session_is_trading_day: %s", state.session_info.is_trading_day)
        logger.info("  session_market_phase : %s", state.session_info.market_phase or "N/A")
    # P2: Market phase tracking summary
    logger.info("  last_known_phase    : %s", state.market_phase or "N/A")
    logger.info("  last_phase_change_at: %s", state.last_phase_change.isoformat() if state.last_phase_change else "N/A")
    logger.info("  session_db_id       : %s", state.session_db_id or "N/A")
    for result in failed[:10]:
        logger.info(
            "  failed task          : %s returncode=%s timeout=%s",
            result.name,
            result.returncode,
            result.timed_out,
        )
    logger.info("=" * 72)


async def _init_session_provider() -> MarketSessionProvider:
    """Initialize session provider from environment configuration.

    Uses ``create_session_provider()`` which resolves:
    - ``KisHolidayProvider`` (076 API) if ``KIS_LIVE_INFO_ENABLED=true`` + credentials
    - ``FallbackSessionProvider`` (weekday heuristic) otherwise

    163 WebSocket(``CombinedSessionProvider``)와의 결합은 2026-07-10에
    제거되었다 — session source는 항상 이 base provider(076/fallback-only)다.
    """
    base_provider = await create_session_provider()
    logger.info(
        "Session provider initialized: %s (076/fallback-only, 163 WS removed)",
        type(base_provider).__name__,
    )
    return base_provider


async def _close_session_provider(provider: MarketSessionProvider | None) -> None:
    """Close the session provider's underlying resources if applicable."""
    if provider is None:
        return
    # If KisHolidayProvider, close the underlying KISHolidayClient
    try:
        # Check if provider has a _client attribute (KisHolidayProvider)
        inner = getattr(provider, "_client", None)
        if inner is not None and hasattr(inner, "close"):
            await inner.close()
            logger.debug("Session provider HTTP client closed")
    except Exception:
        logger.debug("Session provider close (ignored)", exc_info=True)


async def _persist_session_state(
    state: SchedulerState,
    dsn: str | None,
) -> None:
    """Persist current session state to the ``trading.market_sessions`` table.

    Uses direct ``asyncpg`` connection (consistent with existing
    ``_get_db_submit_count`` pattern). If ``dsn`` is ``None`` or the DB
    operation fails, the error is logged and the in-memory state is preserved.
    """
    if dsn is None:
        return
    try:
        import asyncpg

        conn = await asyncpg.connect(dsn=dsn)
        try:
            opnd_yn = state.session_info.opnd_yn if state.session_info else None
            bzdy_yn = state.session_info.bzdy_yn if state.session_info else None
            tr_day_yn = state.session_info.tr_day_yn if state.session_info else None
            is_trading_day = state.session_info.is_trading_day if state.session_info else True
            source = state.session_info.source if state.session_info else "scheduler"
            reason_code = state.session_info.reason_code if state.session_info else None
            reason = state.session_info.reason if state.session_info else ""
            reason_metadata = state.session_info.reason_metadata if state.session_info else None
            market_phase = state.market_phase
            raw_opnd = state.session_info.raw_opnd_yn if state.session_info else None
            raw_mkop = state.session_info.raw_mkop_cls_code if state.session_info else None
            raw_antc = state.session_info.raw_antc_mkop_cls_code if state.session_info else None

            row = await conn.fetchrow(
                """
                INSERT INTO trading.market_sessions
                    (run_date, is_trading_day, opnd_yn, bzdy_yn, tr_day_yn,
                     market_phase, raw_opnd_yn, raw_mkop_cls_code,
                     raw_antc_mkop_cls_code, source, reason_code, reason, reason_metadata, checked_at)
                VALUES
                    ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13::jsonb, $14)
                ON CONFLICT (run_date) DO UPDATE SET
                    is_trading_day = EXCLUDED.is_trading_day,
                    opnd_yn = EXCLUDED.opnd_yn,
                    bzdy_yn = EXCLUDED.bzdy_yn,
                    tr_day_yn = EXCLUDED.tr_day_yn,
                    market_phase = EXCLUDED.market_phase,
                    raw_opnd_yn = EXCLUDED.raw_opnd_yn,
                    raw_mkop_cls_code = EXCLUDED.raw_mkop_cls_code,
                    raw_antc_mkop_cls_code = EXCLUDED.raw_antc_mkop_cls_code,
                    source = EXCLUDED.source,
                    reason_code = EXCLUDED.reason_code,
                    reason = EXCLUDED.reason,
                    reason_metadata = EXCLUDED.reason_metadata,
                    checked_at = EXCLUDED.checked_at,
                    updated_at = NOW()
                RETURNING id
                """,
                state.run_date,
                is_trading_day,
                opnd_yn,
                bzdy_yn,
                tr_day_yn,
                market_phase,
                raw_opnd,
                raw_mkop,
                raw_antc,
                source,
                reason_code,
                reason,
                json.dumps(reason_metadata or {}),
                datetime.now(),
            )
            if row:
                state.session_db_id = row["id"]
        finally:
            await conn.close()
    except Exception:
        logger.exception("Failed to persist session state to DB")

    await _persist_operations_day_run(state, dsn)


async def _persist_operations_day_run(
    state: SchedulerState,
    dsn: str | None,
) -> None:
    """Persist current scheduler day summary to ``trading.operations_day_runs``."""
    if dsn is None:
        return
    try:
        import asyncpg

        conn = await asyncpg.connect(dsn=dsn)
        try:
            is_trading_day = state.session_info.is_trading_day if state.session_info else True
            session_source = state.session_info.source if state.session_info else "scheduler"
            summary_json = _build_operations_day_summary_json(state)
            await conn.execute(
                """
                INSERT INTO trading.operations_day_runs
                    (run_date, scheduler_status, is_trading_day, session_source,
                     market_phase, pre_market_done, end_of_day_done, after_hours_mode,
                     recovery_batch_done, submit_count, held_position_sell_submit_count,
                     cycles, last_phase_change_at, summary_json)
                VALUES
                    ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14::jsonb)
                ON CONFLICT (run_date) DO UPDATE SET
                    scheduler_status = EXCLUDED.scheduler_status,
                    is_trading_day = EXCLUDED.is_trading_day,
                    session_source = EXCLUDED.session_source,
                    market_phase = EXCLUDED.market_phase,
                    pre_market_done = EXCLUDED.pre_market_done,
                    end_of_day_done = EXCLUDED.end_of_day_done,
                    after_hours_mode = EXCLUDED.after_hours_mode,
                    recovery_batch_done = EXCLUDED.recovery_batch_done,
                    submit_count = EXCLUDED.submit_count,
                    held_position_sell_submit_count = EXCLUDED.held_position_sell_submit_count,
                    cycles = EXCLUDED.cycles,
                    last_phase_change_at = EXCLUDED.last_phase_change_at,
                    summary_json = EXCLUDED.summary_json,
                    updated_at = NOW()
                """,
                state.run_date,
                _derive_operations_day_status(state),
                is_trading_day,
                session_source,
                state.market_phase,
                state.pre_market_done,
                state.end_of_day_done,
                state.after_hours_mode,
                state.recovery_batch_done,
                state.submit_count,
                state.held_position_sell_submit_count,
                state.cycles,
                state.last_phase_change,
                json.dumps(summary_json),
            )
        finally:
            await conn.close()
    except Exception:
        logger.exception("Failed to persist operations day run to DB")


# _insert_session_event() / _handle_phase_change() / _session_phase_monitor()
# (163 WebSocket phase polling — KisMarketStateClient 기반) removed 2026-07-10.
# ``state.market_phase``/``state.last_phase_change``는 이 세 함수의 유일한
# writer였으므로 이제 항상 None으로 남는다 — DB 컬럼(trading.market_sessions/
# operations_day_runs)은 그대로 두고 NULL을 기록한다(스키마 변경 없음,
# 로깅/조회 쪽은 이미 "N/A" 폴백을 갖추고 있어 별도 수정이 필요 없다).
# 근거: plans/[PRIORITY_MAP] remaining_work_priority_map.md 항목 20.


def _build_dsn(env: dict[str, str]) -> str | None:
    """Build a DSN from environment variables.

    Resolution order:
    1. ``DATABASE_URL`` (full DSN)
    2. ``DATABASE_DSN`` (full DSN, legacy)
    3. ``DATABASE_HOST`` + ``DATABASE_PORT`` + ``DATABASE_USER`` + ``DATABASE_PASSWORD`` + ``DATABASE_NAME``
    """
    dsn = env.get("DATABASE_URL") or env.get("DATABASE_DSN")
    if dsn:
        return dsn

    host = env.get("DATABASE_HOST") or env.get("DB_HOST") or "localhost"
    port = env.get("DATABASE_PORT") or env.get("DB_PORT") or "5432"
    user = env.get("DATABASE_USER") or env.get("DB_USER") or "trading"
    password = env.get("DATABASE_PASSWORD") or env.get("DB_PASSWORD") or "trading"
    database = env.get("DATABASE_NAME") or env.get("DB_NAME") or "trading"
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


async def _heartbeat_task(state: SchedulerState, pool) -> None:
    """10초 간격으로 DB heartbeat 업데이트.

    ``state.session_db_id``가 설정되어 있으면 해당 row를 UPDATE하고,
    ``None``이면 ``run_date`` 기준으로 UPSERT를 시도한다.
    이렇게 하면 ``_persist_session_state()``가 호출되기 전에도 heartbeat이
    유지되어 ``last_heartbeat_at`` stale 문제를 방지한다.
    """
    while True:
        try:
            summary_json = json.dumps(_build_operations_day_summary_json(state))
            if state.session_db_id is not None:
                await pool.execute(
                    "UPDATE trading.market_sessions SET last_heartbeat_at = NOW(), updated_at = NOW() WHERE id = $1",
                    state.session_db_id,
                )
                await pool.execute(
                    "UPDATE trading.operations_day_runs SET last_heartbeat_at = NOW(), summary_json = $2::jsonb, updated_at = NOW() WHERE run_date = $1",
                    state.run_date,
                    summary_json,
                )
            else:
                # session 미존재 시 run_date로 UPSERT — heartbeat 연속성 보장
                is_trading_day = state.session_info.is_trading_day if state.session_info else True
                await pool.execute(
                    """INSERT INTO trading.market_sessions (run_date, is_trading_day, last_heartbeat_at)
                       VALUES ($1, $2, NOW())
                       ON CONFLICT (run_date) DO UPDATE SET last_heartbeat_at = NOW(), updated_at = NOW()""",
                    state.run_date,
                    is_trading_day,
                )
                await pool.execute(
                    """INSERT INTO trading.operations_day_runs
                           (run_date, scheduler_status, is_trading_day, last_heartbeat_at, summary_json)
                       VALUES ($1, $2, $3, NOW(), $4::jsonb)
                       ON CONFLICT (run_date) DO UPDATE
                       SET last_heartbeat_at = NOW(),
                           summary_json = EXCLUDED.summary_json,
                           updated_at = NOW()""",
                    state.run_date,
                    _derive_operations_day_status(state),
                    is_trading_day,
                    summary_json,
                )
                logger.debug("Heartbeat UPSERT via run_date=%s (session not yet persisted)", state.run_date)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Heartbeat task failed — DB error during heartbeat update")
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            raise


async def _log_startup_info(env: dict[str, str], state: SchedulerState, pool_ok: bool) -> None:
    """스케줄러 시작 정보 로깅."""
    logger.info("=" * 60)
    logger.info("🚀 Ops Scheduler starting up")
    logger.info("=" * 60)
    logger.info("  KIS env:             %s", env.get("KIS_ENV", "paper"))
    logger.info("  Live-info enabled:   %s", env.get("KIS_LIVE_INFO_ENABLED", "false"))
    logger.info("  Live-info token cache: %s (path: %s)",
        env.get("KIS_LIVE_TOKEN_CACHE_ENABLED", "false"),
        env.get("KIS_LIVE_TOKEN_CACHE_PATH", "N/A"),
    )
    logger.info("  Session source:      076 REST (KisHolidayProvider) + FallbackSessionProvider "
                "(163 WS removed 2026-07-10)")
    logger.info("  After-hours window:  %ss", env.get("SCHEDULER_AFTER_HOURS_WINDOW", "3600"))
    logger.info("  Signal batch time:   %s", DEFAULT_SIGNAL_FEATURE_BATCH_TIME.strftime("%H:%M"))
    logger.info(
        "  Status batch time:   %s",
        DEFAULT_INSTRUMENT_STATUS_SNAPSHOT_TIME.strftime("%H:%M"),
    )
    logger.info(
        "  Signal batch input:  %s",
        env.get("SCHEDULER_SIGNAL_FEATURE_INPUT_PATH", "data/signal_feature_snapshot_input.json"),
    )
    logger.info("  Instance ID:         %s", env.get("SCHEDULER_INSTANCE_ID", "default"))
    logger.info("  Run date:            %s", datetime.now(KST).strftime("%Y-%m-%d %A"))
    logger.info("  DB pool:             %s", "connected" if pool_ok else "not connected")
    logger.info("  Advisory lock:       enabled (key=0x%X)", SCHEDULER_ADVISORY_LOCK_KEY)
    # Credential presence diagnostics (without exposing secrets)
    trading_key_present = "present" if env.get("KIS_APP_KEY") else "missing"
    live_info_key_present = "present" if env.get("KIS_LIVE_INFO_APP_KEY") else "missing"
    logger.info("  trading_kis_config=%s", trading_key_present)
    logger.info("  live_info_kis_config=%s", live_info_key_present)
    logger.info("=" * 60)


async def _run_scheduler(args: argparse.Namespace) -> int:
    """Run the operations scheduler."""
    _load_env()

    env = _build_base_env()
    kis_env = env.get("KIS_ENV", "paper")

    # P3: Build DSN for DB operations
    dsn = _build_dsn(env)

    run_date = args.run_date or datetime.now(KST).date()
    state = SchedulerState(run_date=run_date)

    pre_market_at = _combine(run_date, args.pre_market_start)
    instrument_master_sync_at = _combine(run_date, args.instrument_master_sync_time)
    instrument_status_snapshot_at = _combine(
        run_date,
        args.instrument_status_snapshot_time,
    )
    intraday_at = _combine(run_date, args.intraday_start)
    market_close_at = _combine(run_date, args.market_close)
    end_at = _combine(run_date, args.end_of_day_end)

    # P1: Initialize session provider (076 REST + fallback-only —
    # 163 WebSocket/CombinedSessionProvider removed 2026-07-10).
    session_provider = await _init_session_provider()

    # Persist initial state immediately so the very first market_sessions
    # row exists (market_phase stays NULL — no writer for it anymore).
    await _persist_session_state(state, dsn)

    # P3: Create DB pool for advisory lock and heartbeat (with retries)
    pool = None
    if dsn:
        import asyncpg
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                pool = await asyncpg.create_pool(
                    dsn=dsn,
                    min_size=int(env.get("DB_POOL_MIN", "2")),
                    max_size=int(env.get("DB_POOL_MAX", "10")),
                )
                logger.info("DB pool created successfully (attempt %d/%d)", attempt, max_retries)
                break  # 성공 시 루프 탈출
            except Exception:
                if attempt < max_retries:
                    wait = 2 ** attempt  # 2s, 4s, 8s
                    logger.warning(
                        "DB pool creation attempt %d/%d failed, retrying in %ds",
                        attempt, max_retries, wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.exception(
                        "Failed to create DB pool after %d attempts — advisory lock and heartbeat disabled",
                        max_retries,
                    )
                    pool = None

    # P3: Startup info logging
    await _log_startup_info(env, state, pool is not None)

    # P3: Advisory lock wrapper
    async def _run_with_lock() -> int:
        """Inner scheduler logic with lock context."""
        nonlocal run_date, state, pre_market_at
        nonlocal instrument_master_sync_at, instrument_status_snapshot_at
        nonlocal intraday_at, market_close_at, end_at

        # P3: Heartbeat task
        heartbeat_task: asyncio.Task[None] | None = None
        if pool is not None:
            heartbeat_task = asyncio.create_task(_heartbeat_task(state, pool))
            logger.info("Heartbeat background task created (interval=10s)")

        try:
            if args.once:
                now = datetime.now(KST)
                tasks = _build_tasks(
                    now,
                    snapshot_interval=args.snapshot_interval,
                    event_interval=args.event_interval,
                    decision_interval=args.decision_interval,
                    post_submit_interval=args.post_submit_interval,
                    fill_sync_interval=args.fill_sync_interval,
                )
                # P2: Persist session state BEFORE running tasks — critical for
                # heartbeat continuity. If decision_submit_gate times out and
                # the subprocess is SIGKILL'd, _persist_session_state() after
                # tasks would never be reached, leaving state.session_db_id=None
                # and causing heartbeat UPDATE to skip.
                if state.session_info is not None:
                    await _persist_session_state(state, dsn)

                # --once mode: session gate applies to all phases
                if not args.skip_pre_market:
                    if await _session_gate(session_provider, run_date, state, "pre_market"):
                        if (
                            now >= instrument_master_sync_at
                            and not state.instrument_master_sync_done
                        ):
                            await _run_instrument_master_sync(
                                state,
                                timeout_seconds=args.task_timeout,
                                env=env,
                                source_csv_paths=args.instrument_master_source_csv_path,
                                csv_path=args.instrument_master_sync_csv_path,
                                archive_dir=args.instrument_master_archive_dir,
                                run_date=run_date,
                                dsn=dsn,
                            )
                        if (
                            now >= instrument_status_snapshot_at
                            and state.instrument_master_sync_done
                            and not state.instrument_status_snapshot_done
                        ):
                            await _run_instrument_status_snapshot(
                                state,
                                timeout_seconds=args.task_timeout,
                                env=env,
                                freeze_purposes=args.instrument_status_snapshot_freeze_purpose,
                                dsn=dsn,
                            )
                        await _run_pre_market(
                            state,
                            timeout_seconds=args.task_timeout,
                            env=env,
                            dsn=dsn,
                        )
                    else:
                        logger.info("--once: pre-market phase skipped by session gate")

                if await _session_gate(session_provider, run_date, state, "intraday"):
                        await _run_intraday_due_tasks(
                            state,
                            tasks,
                            max_general_buy_submit_per_day=(
                                args.max_general_buy_submit_per_day
                            ),
                            held_position_sell_max_per_day=args.held_position_sell_max_per_day,
                            timeout_seconds=args.task_timeout,
                            env=env,
                        now=now,
                        dsn=dsn,
                    )
                else:
                    logger.info("--once: intraday phase skipped by session gate")

                if args.run_eod:
                    if await _session_gate(session_provider, run_date, state, "end_of_day"):
                        await _run_end_of_day(
                            state,
                            timeout_seconds=args.task_timeout,
                            env=env,
                            snapshot_interval=args.snapshot_interval,
                            dsn=dsn,
                        )
                    else:
                        logger.info("--once: end-of-day phase skipped by session gate")

                # P2: Persist final session state on --once exit (second call is
                # safe — upsert by run_date)
                if state.session_info is not None:
                    await _persist_session_state(state, dsn)
                _log_summary(state)
                return 0 if all(r.ok for r in state.command_results) else 1

            now = datetime.now(KST)
            tasks = _build_tasks(
                max(now, intraday_at),
                snapshot_interval=args.snapshot_interval,
                event_interval=args.event_interval,
                decision_interval=args.decision_interval,
                post_submit_interval=args.post_submit_interval,
                fill_sync_interval=args.fill_sync_interval,
            )

            stop_event = asyncio.Event()

            def _request_stop() -> None:
                logger.info("Shutdown requested; current task will finish before exit.")
                stop_event.set()

            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, _request_stop)
                except NotImplementedError:  # pragma: no cover
                    signal.signal(sig, lambda _sig, _frame: _request_stop())

            while not stop_event.is_set():
                state.cycles += 1
                now = datetime.now(KST)

                if _should_rollover_to_next_run_date(
                    now=now,
                    run_date=run_date,
                    end_at=end_at,
                    state=state,
                    signal_feature_batch_at=args.signal_feature_batch_time,
                ):
                    logger.info(
                        "═══ Reached scheduler end time — entering idle mode until next run date ═══"
                    )
                    await _persist_session_state(state, dsn)  # 현재 session state 저장
                    _log_summary(state)  # 오늘 summary 출력
                    # Idle 전환: run_date + 1일, state 초기화
                    run_date = run_date + timedelta(days=1)
                    state = SchedulerState(run_date=run_date)
                    # 시간 상수 재계산
                    pre_market_at = _combine(run_date, args.pre_market_start)
                    instrument_master_sync_at = _combine(
                        run_date,
                        args.instrument_master_sync_time,
                    )
                    instrument_status_snapshot_at = _combine(
                        run_date,
                        args.instrument_status_snapshot_time,
                    )
                    intraday_at = _combine(run_date, args.intraday_start)
                    market_close_at = _combine(run_date, args.market_close)
                    end_at = _combine(run_date, args.end_of_day_end)
                    # Heartbeat task 재생성: 새 state 참조하도록 교체
                    if heartbeat_task is not None and not heartbeat_task.done():
                        heartbeat_task.cancel()
                        try:
                            await heartbeat_task
                        except asyncio.CancelledError:
                            pass
                    if pool is not None:
                        heartbeat_task = asyncio.create_task(_heartbeat_task(state, pool))
                        logger.info("Heartbeat background task recreated after idle rollover (interval=10s)")
                    logger.info("═══ Next run_date: %s — waiting for market hours ═══", run_date)
                    continue
                if (
                    now >= end_at
                    and state.after_hours_mode
                    and not state.signal_feature_batch_done
                ):
                    logger.info(
                        "Rollover deferred — waiting for after-market signal feature batch "
                        "(now=%s trigger=%s run_date=%s)",
                        now.isoformat(),
                        _combine(run_date, args.signal_feature_batch_time).isoformat(),
                        run_date.isoformat(),
                    )

                # 비영업일 early termination — session gate가 모든 phase를 차단하면
                # 16:30까지 대기하지 않고 즉시 graceful shutdown
                if state.session_info is not None and not state.session_info.is_trading_day:
                    logger.info(
                        "═══ Non-trading day detected (source=%s) — entering idle mode ═══",
                        state.session_info.source,
                    )
                    await _persist_session_state(state, dsn)  # 현재 session state 저장
                    _log_summary(state)  # 오늘 summary 출력
                    # 다음 날로 run_date rollover
                    run_date = run_date + timedelta(days=1)
                    state = SchedulerState(run_date=run_date)
                    # 시간 상수 재계산
                    pre_market_at = _combine(run_date, args.pre_market_start)
                    instrument_master_sync_at = _combine(
                        run_date,
                        args.instrument_master_sync_time,
                    )
                    instrument_status_snapshot_at = _combine(
                        run_date,
                        args.instrument_status_snapshot_time,
                    )
                    intraday_at = _combine(run_date, args.intraday_start)
                    market_close_at = _combine(run_date, args.market_close)
                    end_at = _combine(run_date, args.end_of_day_end)
                    # Heartbeat task 재생성: 새 state 참조하도록 교체
                    if heartbeat_task is not None and not heartbeat_task.done():
                        heartbeat_task.cancel()
                        try:
                            await heartbeat_task
                        except asyncio.CancelledError:
                            pass
                    if pool is not None:
                        heartbeat_task = asyncio.create_task(_heartbeat_task(state, pool))
                        logger.info("Heartbeat background task recreated after non-trading day rollover (interval=10s)")
                    logger.info("═══ Next run_date: %s — waiting for next trading day ═══", run_date)
                    continue

                # P1: Session gate — check before each phase
                if (
                    instrument_master_sync_at <= now < intraday_at
                    and not state.instrument_master_sync_done
                    and not args.skip_pre_market
                ):
                    if await _session_gate(session_provider, run_date, state, "pre_market"):
                            await _run_instrument_master_sync(
                                state,
                                timeout_seconds=args.task_timeout,
                                env=env,
                                source_csv_paths=args.instrument_master_source_csv_path,
                                csv_path=args.instrument_master_sync_csv_path,
                                archive_dir=args.instrument_master_archive_dir,
                                run_date=run_date,
                                dsn=dsn,
                            )
                    else:
                        logger.info(
                            "Instrument master sync skipped by session gate for %s",
                            run_date.isoformat(),
                        )
                elif now >= intraday_at and not args.skip_pre_market:
                    await _mark_instrument_master_sync_missed(
                        state,
                        now=now,
                        instrument_master_sync_at=instrument_master_sync_at,
                        intraday_at=intraday_at,
                        dsn=dsn,
                    )

                if (
                    instrument_status_snapshot_at <= now < intraday_at
                    and state.instrument_master_sync_done
                    and not state.instrument_status_snapshot_done
                    and not args.skip_pre_market
                ):
                    if await _session_gate(session_provider, run_date, state, "pre_market"):
                        await _run_instrument_status_snapshot(
                            state,
                            timeout_seconds=args.task_timeout,
                            env=env,
                            freeze_purposes=args.instrument_status_snapshot_freeze_purpose,
                            dsn=dsn,
                        )
                    else:
                        logger.info(
                            "Instrument status snapshot skipped by session gate for %s",
                            run_date.isoformat(),
                        )
                elif now >= intraday_at and not args.skip_pre_market:
                    await _mark_instrument_status_snapshot_missed(
                        state,
                        now=now,
                        instrument_status_snapshot_at=instrument_status_snapshot_at,
                        intraday_at=intraday_at,
                        dsn=dsn,
                    )

                if now >= pre_market_at and not state.pre_market_done and not args.skip_pre_market:
                    if await _session_gate(session_provider, run_date, state, "pre_market"):
                        await _run_pre_market(
                            state,
                            timeout_seconds=args.task_timeout,
                            env=env,
                            dsn=dsn,
                        )
                    else:
                        state.pre_market_done = True  # Mark done to avoid retry
                        logger.info(
                            "Pre-market phase skipped by session gate for %s",
                            run_date.isoformat(),
                        )

                if intraday_at <= now < market_close_at:
                    # ★ P0: snapshot은 session_gate와 무관하게 자체 due 체크
                    # decision_submit_gate의 장기 timeout과 독립적인 cadence 유지
                    if tasks["snapshot"].due:
                        last_run = tasks["snapshot"].last_run_at or now
                        gap = (now - last_run).total_seconds()
                        logger.info(
                            "CADENCE_TRACE snapshot_sync symbol=ALL "
                            "action=start due_at=%s last_run_gap=%.0fs target_interval=%ds drift=%.0fs",
                            now.isoformat(), gap, args.snapshot_interval,
                            gap - args.snapshot_interval,
                        )
                        await _run_and_record(
                            state,
                            "snapshot_sync",
                            _snapshot_command(),
                            timeout_seconds=args.task_timeout,
                            env=env,
                        )
                        completed_at = datetime.now(KST)
                        tasks["snapshot"].mark_ran(completed_at)
                        logger.info(
                            "CADENCE_TRACE snapshot_sync symbol=ALL action=complete "
                            "completed_at=%s actual_duration=%.1fs next_at=%s",
                            completed_at.isoformat(),
                            (completed_at - now).total_seconds(),
                            tasks["snapshot"].next_run_at.isoformat(),
                        )

                    if await _session_gate(session_provider, run_date, state, "intraday"):
                        # snapshot이 이미 위에서 처리되었으므로 event/decision/post_submit만 전달
                        if any(
                            tasks[k].due
                            for k in ("event", "decision", "post_submit")
                        ):
                            await _run_intraday_due_tasks(
                                state,
                                tasks,
                                max_general_buy_submit_per_day=(
                                    args.max_general_buy_submit_per_day
                                ),
                                held_position_sell_max_per_day=args.held_position_sell_max_per_day,
                                timeout_seconds=args.task_timeout,
                                env=env,
                                now=now,
                                decision_interval=args.decision_interval,
                                dsn=dsn,
                            )
                    else:
                        logger.info(
                            "Intraday tasks skipped by session gate for %s",
                            run_date.isoformat(),
                        )

                if now >= market_close_at and not state.end_of_day_done:
                    if await _session_gate(session_provider, run_date, state, "end_of_day"):
                        await _run_end_of_day(
                            state,
                            timeout_seconds=args.task_timeout,
                            env=env,
                            snapshot_interval=args.snapshot_interval,
                            dsn=dsn,
                        )
                    else:
                        state.end_of_day_done = True  # Mark done to avoid retry
                        logger.info(
                            "End-of-day phase skipped by session gate for %s",
                            run_date.isoformat(),
                        )

                # After-hours: continue snapshot sync only (no decision/post-submit)
                if state.after_hours_mode:
                    await _run_after_hours_snapshot_cycle(
                        state,
                        timeout_seconds=args.task_timeout,
                        env=env,
                        now=now,
                        dsn=dsn,
                    )

                    # 16:00 KST after-hours 복구 배치 (1회만 실행)
                    if not state.recovery_batch_done and now.hour >= 16:
                        logger.info(
                            "[RECOVERY_BATCH] 16:00 KST 도달 — "
                            "after-hours 복구 배치 실행"
                        )
                        await _run_and_record(
                            state,
                            "eod_recovery_batch",
                            _post_submit_command(recovery=True),
                            timeout_seconds=args.task_timeout,
                            env=env,
                        )
                        state.recovery_batch_done = True
                        logger.info("[RECOVERY_BATCH] 복구 배치 완료")

                    await _run_after_market_signal_feature_batch(
                        state,
                        timeout_seconds=args.task_timeout,
                        env=env,
                        now=now,
                        signal_feature_batch_at=args.signal_feature_batch_time,
                        signal_feature_input_path=args.signal_feature_input_path,
                        dsn=dsn,
                    )
                    await _run_after_market_trigger_proxy_attribution(
                        state,
                        timeout_seconds=args.task_timeout,
                        env=env,
                        dsn=dsn,
                    )

                # Idle/non-trading day: 긴 polling interval (60초)
                if state.session_info is None or state.cycles == 0:
                    await asyncio.sleep(min(args.tick_seconds, 60))
                else:
                    await asyncio.sleep(args.tick_seconds)

            # Main loop exited via SIGTERM/SIGINT only — rollover 시에는 이미
            # _log_summary + _persist_session_state가 각 idle 전환에서 처리됨
            logger.info("Scheduler main loop exited — cleaning up background tasks")
            return 0
        finally:
            # P3: Cancel heartbeat task
            if heartbeat_task is not None and not heartbeat_task.done():
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

            await _close_session_provider(session_provider)

    # P3: Run inner logic with advisory lock
    if pool is not None:
        async with try_scheduler_lock(pool) as acquired:
            if not acquired:
                logger.warning("❗ Scheduler advisory lock NOT acquired — another instance is running. Exiting.")
                return 1
            logger.info("✅ Scheduler advisory lock acquired — proceeding with main loop")
            return await _run_with_lock()
    else:
        logger.warning("No DB pool — running without advisory lock")
        return await _run_with_lock()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Near-real internal operations scheduler.",
    )
    parser.add_argument(
        "--run-date",
        type=lambda value: date.fromisoformat(value),
        default=None,
        help="KST operating date in YYYY-MM-DD format (default: today).",
    )
    parser.add_argument("--pre-market-start", type=_parse_hhmm, default=PRE_MARKET_START)
    parser.add_argument("--intraday-start", type=_parse_hhmm, default=INTRADAY_START)
    parser.add_argument("--market-close", type=_parse_hhmm, default=MARKET_CLOSE)
    parser.add_argument("--end-of-day-end", type=_parse_hhmm, default=END_OF_DAY_END)
    parser.add_argument("--snapshot-interval", type=int, default=DEFAULT_SNAPSHOT_INTERVAL_SECONDS)
    parser.add_argument("--event-interval", type=int, default=DEFAULT_EVENT_INTERVAL_SECONDS)
    parser.add_argument("--decision-interval", type=int, default=DEFAULT_DECISION_INTERVAL_SECONDS)
    parser.add_argument("--post-submit-interval", type=int, default=DEFAULT_POST_SUBMIT_INTERVAL_SECONDS)
    parser.add_argument("--fill-sync-interval", type=int, default=DEFAULT_FILL_SYNC_INTERVAL_SECONDS)
    parser.add_argument(
        "--instrument-master-sync-time",
        type=_parse_hhmm,
        default=DEFAULT_INSTRUMENT_MASTER_SYNC_TIME,
        help="Pre-market instrument master sync trigger time in KST.",
    )
    parser.add_argument(
        "--instrument-master-sync-csv-path",
        default=DEFAULT_INSTRUMENT_MASTER_SYNC_CSV_PATH,
        help="Normalized KIS instrument master CSV path for pre-market sync.",
    )
    parser.add_argument(
        "--instrument-master-source-csv-path",
        action="append",
        default=list(DEFAULT_INSTRUMENT_MASTER_SOURCE_CSV_PATHS),
        help="Source KIS/raw instrument CSV path. 여러 번 지정 가능.",
    )
    parser.add_argument(
        "--instrument-master-archive-dir",
        default=DEFAULT_INSTRUMENT_MASTER_ARCHIVE_DIR,
        help="원본 instrument master CSV 보관 디렉터리.",
    )
    parser.add_argument(
        "--instrument-status-snapshot-time",
        type=_parse_hhmm,
        default=DEFAULT_INSTRUMENT_STATUS_SNAPSHOT_TIME,
        help="Pre-market instrument status snapshot trigger time in KST.",
    )
    parser.add_argument(
        "--instrument-status-snapshot-freeze-purpose",
        action="append",
        default=list(DEFAULT_INSTRUMENT_STATUS_SNAPSHOT_FREEZE_PURPOSES),
        help="Instrument status snapshot 대상 freeze purpose. 여러 번 지정 가능.",
    )
    parser.add_argument(
        "--signal-feature-batch-time",
        type=_parse_hhmm,
        default=DEFAULT_SIGNAL_FEATURE_BATCH_TIME,
        help="Signal feature batch trigger time in KST.",
    )
    parser.add_argument(
        "--signal-feature-input-path",
        default="data/signal_feature_snapshot_input.json",
        help="Input JSON path for signal feature snapshot batch.",
    )
    parser.add_argument("--tick-seconds", type=int, default=5)
    parser.add_argument("--task-timeout", type=int, default=DEFAULT_TASK_TIMEOUT_SECONDS)
    parser.add_argument(
        "--max-general-buy-submit-per-day",
        type=int,
        default=DEFAULT_MAX_GENERAL_BUY_SUBMIT_PER_DAY,
        help=(
            "Max general BUY submits per day for core/market_overlay lanes. "
            "held_position risk-reducing SELL uses a separate budget."
        ),
    )
    parser.add_argument(
        "--max-submit-per-day",
        type=int,
        dest="legacy_max_submit_per_day",
        default=None,
        help=(
            "Deprecated alias for --max-general-buy-submit-per-day. "
            "Kept for backward compatibility."
        ),
    )
    parser.add_argument(
        "--held-position-sell-max-per-day",
        type=int,
        default=HELD_POSITION_SELL_MAX_PER_DAY,
        help="Max held_position REDUCE/EXIT sell submits per day (별도 budget).",
    )
    parser.add_argument("--skip-pre-market", action="store_true", default=False)
    parser.add_argument(
        "--once",
        action="store_true",
        default=False,
        help="Run one scheduler tick immediately for smoke validation.",
    )
    parser.add_argument(
        "--run-eod",
        action="store_true",
        default=False,
        help="With --once, also run end-of-day tasks.",
    )
    args = parser.parse_args(argv)
    if args.legacy_max_submit_per_day is not None:
        args.max_general_buy_submit_per_day = args.legacy_max_submit_per_day
    return args


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] ops-scheduler: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    args = _parse_args(argv)
    return asyncio.run(_run_scheduler(args))


if __name__ == "__main__":
    sys.exit(main())
