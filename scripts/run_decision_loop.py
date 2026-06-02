#!/usr/bin/env python3
"""Decision loop — 반복 운영 전용.

``run_orchestrator_once.py``는 단발 실행을 유지하고,
이 스크립트가 **연속 실행(continuous loop)** 을 담당한다.

기존 ``verify_decision_loop.py``는 **검증(verification)** 전용이며,
이 스크립트는 **운영(operations)** 전용이다.

역할 분리
---------
* ``run_snapshot_sync_loop.py`` — position/cash 데이터 최신성 유지 (300s)
* ``run_post_submit_sync_loop.py`` — 미체결/부분체결 주문 상태 Broker 수렴 (30s)
* ``run_decision_loop.py`` — AI Decision → Submit 반복 실행 (300s)

Usage
-----
.. code-block:: bash

    # 기본 실행 (5분 간격, 무한 반복, submit 모드)
    python3 -m scripts.run_decision_loop

    # 1회 실행 후 종료
    python3 -m scripts.run_decision_loop --count 1

    # Dry-run (assemble + sizing only, submit 없음)
    python3 -m scripts.run_decision_loop --count 1 --dry-run

    # 60초 간격, 5회, JSON 출력
    python3 -m scripts.run_decision_loop --interval 60 --count 5 --output json

    # 명시적 submit 모드 (기본값)
    python3 -m scripts.run_decision_loop --submit --count 1

환경 변수
---------
* ``PAPER_DECISION_LOOP_INTERVAL_SECONDS`` — 기본 interval (기본 300)
* ``TRADING_UNIVERSE_SYMBOLS`` — comma-separated symbol list (예: 005930,030200:KRX)
* ``KIS_SNAPSHOT_STALE_THRESHOLD_SECONDS`` — snapshot staleness 임계값 (기본 900)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, NoReturn

# Lazy import for python-dotenv (optional, for local dev)
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from agent_trading.brokers.base import BrokerAdapter
from agent_trading.domain.enums import OrderSide, OrderType
from agent_trading.domain.entities import ExternalEventEntity
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.contracts import (
    ExternalEventRepository,
    SnapshotSyncHealthSummary,
)
from agent_trading.repositories.filters import AccountLookup
from agent_trading.runtime.bootstrap import (
    _build_kis_live_quote_client,
    postgres_runtime,
)
from agent_trading.services.common_types import SubmitResult
from agent_trading.services.sizing_engine import calculate_sizing
from agent_trading.services.universe_selection import UniverseSelectionService
from agent_trading.services.universe_selection_types import (
    CompositionContext,
    FALLBACK_ACCOUNT_ID,
)

# Lazy import for KISRestClient (only when KIS credentials are configured)
try:
    from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
    _HAS_KIS = True
except ImportError:
    KISRestClient = None  # type: ignore[assignment,misc]
    _HAS_KIS = False

# ── Seed constants (reused from run_orchestrator_once.py) ───────────────────
from scripts.run_orchestrator_once import (
    ACCOUNT_ALIAS,
    CLIENT_ID,
    STRATEGY_ID,
    SYMBOL,
    MARKET,
    _resolve_smoke_price,
    _seed_if_empty,
)

# ── Price resolution ──────────────────────────────────────────────────────────

_DEFAULT_SAFE_PRICE = Decimal("50000")
"""Ultimate fallback price when both live quote and KIS_SMOKE_PRICE are unavailable."""

HELD_POSITION_SELL_MAX_PER_CYCLE = 2
"""Per-cycle cap for held-position REDUCE/EXIT SELL submit lane."""


def _compute_symbol_submit_mode(
    *,
    submit: bool,
    dry_run: bool,
    allow_general_submit: bool,
    source_type: str,
    submit_budget_consumed: bool,
    held_position_sell_cycle_count: int,
    held_position_sell_cycle_symbols: set[str],
    symbol: str,
) -> tuple[bool, bool]:
    """Return per-symbol ``(submit, dry_run)`` mode for the current cycle.

    ``held_position`` items use a dedicated lane so that a risk-reducing SELL
    candidate is not downgraded to dry-run merely because a general BUY slot
    was already reserved earlier in the same scheduler cycle.  That lane still
    respects cycle-level cap and same-symbol deduplication.
    """
    if not submit or dry_run:
        return False, True

    if source_type == "held_position":
        symbol_submit = (
            held_position_sell_cycle_count < HELD_POSITION_SELL_MAX_PER_CYCLE
            and symbol not in held_position_sell_cycle_symbols
        )
        return symbol_submit, not symbol_submit

    if not allow_general_submit:
        return False, True

    symbol_submit = not submit_budget_consumed
    return symbol_submit, not symbol_submit


async def _resolve_symbol_price(
    symbol: str,
    market: str,
    broker: BrokerAdapter | None,
) -> Decimal:
    """Resolve a per-symbol order price from live broker quote.

    Priority
    --------
    1. ``broker.get_quote(symbol, market).last`` — live quote current price.
    2. ``KIS_SMOKE_PRICE`` env var — smoke-test fallback (legacy).
    3. ``Decimal("50000")`` — safe default when nothing else works.

    Always logs the resolved price and its source for observability.
    """
    # ── Priority 1: Live broker quote ────────────────────────────────────
    if broker is not None and hasattr(broker, "get_quote"):
        try:
            quote = await broker.get_quote(symbol, market)
            if quote is not None and quote.last is not None and quote.last > 0:
                logger.info(
                    "Resolved price symbol=%s price=%s source=live_quote",
                    symbol,
                    quote.last,
                )
                return quote.last
            logger.warning(
                "Quote for %s returned invalid last=%s, falling back.",
                symbol,
                quote.last,
            )
        except Exception as exc:
            logger.warning(
                "Quote fetch failed symbol=%s error=%s, falling back.",
                symbol,
                exc,
            )
    else:
        logger.debug(
            "No broker adapter available for symbol=%s, using fallback price.",
            symbol,
        )

    # ── Priority 2: KIS_SMOKE_PRICE env var (legacy fallback) ────────────
    raw = os.environ.get("KIS_SMOKE_PRICE")
    if raw is not None:
        try:
            price = Decimal(raw)
            logger.info(
                "Resolved price symbol=%s price=%s source=KIS_SMOKE_PRICE(fallback)",
                symbol,
                price,
            )
            return price
        except (InvalidOperation, ValueError):
            logger.warning(
                "Invalid KIS_SMOKE_PRICE=%r for symbol=%s, falling back to default.",
                raw,
                symbol,
            )

    # ── Priority 3: Safe default ─────────────────────────────────────────
    logger.warning(
        "No price source available for symbol=%s, using default price=%s",
        symbol,
        _DEFAULT_SAFE_PRICE,
    )
    return _DEFAULT_SAFE_PRICE


def _resolve_order_type_and_price(
    *,
    side: str,
    decision_type: str | None = None,
    default_price: Decimal | None = None,
) -> tuple[OrderType, Decimal | None]:
    """의사결정 유형과 매매방향에 따라 execution 정책 결정.

    현재는 전면 MARKET 정책 — 항상 ``(OrderType.MARKET, None)`` 반환.
    ``side`` / ``decision_type`` / ``default_price`` 파라미터는
    향후 시장성 지정가 등 확장에 대비해 预留(reserved)해 둠.
    """
    _ = side, decision_type, default_price  # 향후 확장 대비 预留
    return OrderType.MARKET, None


logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────────────────────

DEFAULT_INTERVAL_SECONDS = 300
DEFAULT_EVENT_LOOKBACK_HOURS: int = 24
"""Event lookback window (hours).  Calendar 24h proxy — not trading-session-aware.
장 시작 직후/휴장일 경계에서는 실제 '1거래일'과 다를 수 있음.
P2.1+에서 trading calendar 기반 lookback으로 개선 필요."""
ENV_INTERVAL = "PAPER_DECISION_LOOP_INTERVAL_SECONDS"
ENV_TRADING_UNIVERSE = "TRADING_UNIVERSE_SYMBOLS"


@dataclass(slots=True, frozen=True)
class UniverseSymbol:
    """A symbol/market pair evaluated by the decision loop.

    Attributes
    ----------
    symbol : str
        Ticker symbol (e.g. ``"005930"``).
    market : str
        Market code (e.g. ``"KRX"``).
    source_type : str
        Origin of this symbol's inclusion (``"core"``, ``"held_position"``,
        ``"event_overlay"``, ``"market_overlay"``, ``"manual"``).
        Default: ``"core"``.
    inclusion_reason : str
        Machine-readable reason for inclusion.
        Default: ``"kospi200_core"``.
    """

    symbol: str
    market: str = MARKET
    source_type: str = "core"
    inclusion_reason: str = "kospi200_core"

# ── Signal handling ─────────────────────────────────────────────────────────

_shutdown_event = asyncio.Event()


def _handle_signal() -> None:
    """SIGTERM/SIGINT handler — cancel all tasks and exit."""
    logger.warning("Received shutdown signal — cancelling all pending tasks")
    _shutdown_event.set()
    # Cancel all asyncio tasks to unblock httpx I/O waits
    for task in asyncio.all_tasks():
        if task is not asyncio.current_task():
            task.cancel()


def _install_signal_handlers() -> None:
    """Install signal handlers for graceful shutdown."""
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            signal.signal(sig, lambda s, f: _handle_signal())


# ── Config helpers ──────────────────────────────────────────────────────────


def _read_interval() -> int:
    """Read the decision loop interval from the environment (seconds)."""
    raw = os.getenv(ENV_INTERVAL)
    if raw is None:
        return DEFAULT_INTERVAL_SECONDS
    try:
        val = int(raw)
        if val < 5:
            logger.warning(
                "Interval %d is too short (< 5s), using %d instead.",
                val,
                DEFAULT_INTERVAL_SECONDS,
            )
            return DEFAULT_INTERVAL_SECONDS
        return val
    except (ValueError, TypeError):
        logger.warning(
            "Invalid %s=%r, using default %d.",
            ENV_INTERVAL,
            raw,
            DEFAULT_INTERVAL_SECONDS,
        )
        return DEFAULT_INTERVAL_SECONDS


def _parse_universe_symbols(raw: str | None) -> tuple[UniverseSymbol, ...]:
    """Parse a comma-separated trading universe.

    Supported item formats:
    - ``005930`` → ``005930:KRX``
    - ``005930:KRX`` → explicit symbol/market
    - ``005930.KRX`` → explicit symbol/market
    """
    if raw is None or not raw.strip():
        return (UniverseSymbol(symbol=SYMBOL, market=MARKET),)

    parsed: list[UniverseSymbol] = []
    seen: set[tuple[str, str]] = set()
    for item in raw.split(","):
        token = item.strip()
        if not token:
            continue

        if ":" in token:
            symbol, market = token.split(":", 1)
        elif "." in token:
            symbol, market = token.split(".", 1)
        else:
            symbol, market = token, MARKET

        symbol = symbol.strip().upper()
        market = (market.strip().upper() or MARKET)
        if not symbol:
            continue

        key = (symbol, market)
        if key not in seen:
            parsed.append(UniverseSymbol(symbol=symbol, market=market))
            seen.add(key)

    if not parsed:
        logger.warning(
            "Invalid %s=%r, falling back to %s:%s",
            ENV_TRADING_UNIVERSE,
            raw,
            SYMBOL,
            MARKET,
        )
        return (UniverseSymbol(symbol=SYMBOL, market=MARKET),)
    return tuple(parsed)


async def _read_trading_universe() -> tuple[UniverseSymbol, ...]:
    """Read the trading universe with fallback chain.

    Priority
    --------
    1. ``TRADING_UNIVERSE_SYMBOLS`` env var (explicit override).
    2. ``UniverseSelectionService.compose()`` — 4-source composition with
       Liquidity Filter, priority sort, and daily cap.
    3. Hardcoded fallback: ``UniverseSymbol(symbol=SYMBOL, market=MARKET)`` (005930/KRX).

    The env var takes precedence so that operators can override the universe
    without modifying the database.  When the env var is not set, the
    ``UniverseSelectionService`` is used.  If the service is unavailable or
    returns no symbols, the single-symbol 005930 fallback is used.
    """
    # Priority 1: explicit env var override
    raw = os.getenv(ENV_TRADING_UNIVERSE)
    if raw is not None and raw.strip():
        return _parse_universe_symbols(raw)

    # Priority 2: UniverseSelectionService (4-source composition)
    try:
        async with postgres_runtime(run_migrations=False) as runtime:
            repos: RepositoryContainer = runtime["repositories"]

            # Create KIS quote client if available (P2 market overlay)
            kis_client: KISRestClient | None = None
            if _HAS_KIS:
                try:
                    from agent_trading.config.settings import AppSettings
                    from agent_trading.brokers.rate_limit import build_kis_budget_manager

                    settings = AppSettings()
                    kis_client = _build_kis_live_quote_client(settings)
                    if kis_client is None:
                        budget_manager = build_kis_budget_manager(
                            kis_env=settings.kis_env,
                            real_rest_rps=settings.kis_real_rest_rps,
                            paper_rest_rps=settings.kis_paper_rest_rps,
                            shared_budget_file=settings.kis_shared_budget_file,
                        )
                        kis_client = KISRestClient(
                            api_key=settings.kis_api_key,
                            api_secret=settings.kis_api_secret,
                            account_number=settings.kis_account_number,
                            account_product_code=settings.kis_account_product_code,
                            env=settings.kis_env,
                            base_url=settings.kis_base_url,
                            budget_manager=budget_manager,
                            dev_token_cache_enabled=settings.kis_dev_token_cache_enabled,
                            dev_token_cache_path=settings.kis_dev_token_cache_path,
                        )
                except Exception as exc:
                    logger.warning(
                        "KIS client init failed — market_overlay disabled "
                        "(source=_read_trading_universe, error=%s: %s).",
                        type(exc).__name__,
                        exc,
                    )

            selector = UniverseSelectionService(
                repos,
                kis_client=kis_client,
            )

            # Resolve account ID for held-position lookup
            account_id: UUID = FALLBACK_ACCOUNT_ID
            try:
                account = await repos.accounts.find_one(
                    AccountLookup(account_alias=ACCOUNT_ALIAS)
                )
                if account is not None:
                    account_id = account.account_id
            except TypeError as e:
                logger.error("AccountLookup field name mismatch: %s", e)
                # TypeError는 복구 불가능한 프로그래밍 오류 → 재발생
                raise
            except Exception:
                logger.warning("Account lookup failed — using fallback account ID.")

            ctx = CompositionContext(
                account_id=account_id,
                since=datetime.now(timezone.utc) - timedelta(hours=DEFAULT_EVENT_LOOKBACK_HOURS),
                # P2 minimum: market overlay cap and pre-pool size
                market_overlay_cap=5,
                pre_pool_size=50,
            )
            selected = await selector.compose(ctx)

            if selected:
                universe = tuple(
                    UniverseSymbol(
                        symbol=s.symbol,
                        market=s.market,
                        source_type=s.source_type.value,
                        inclusion_reason=s.inclusion_reason,
                    )
                    for s in selected
                )
                # source_type 분포 로깅 — held_position 포함 여부 추적
                source_counts: dict[str, int] = {}
                for sym in universe:
                    source_counts[sym.source_type] = source_counts.get(sym.source_type, 0) + 1
                logger.info(
                    "Trading universe from UniverseSelectionService: "
                    "%d symbols loaded (cap=%d).  "
                    "source_type distribution: %s",
                    len(universe),
                    ctx.max_cap,
                    source_counts,
                )
                return universe

            logger.info(
                "UniverseSelectionService returned 0 symbols — "
                "falling back to %s:%s.",
                SYMBOL,
                MARKET,
            )
    except Exception as exc:
        logger.warning(
            "UniverseSelectionService failed (%s: %s) — "
            "falling back to %s:%s.",
            type(exc).__name__,
            exc,
            SYMBOL,
            MARKET,
        )

    # Priority 3: hardcoded fallback (single smoke symbol)
    return (UniverseSymbol(symbol=SYMBOL, market=MARKET),)


# ── Pre-check: snapshot sync health ────────────────────────────────────────
# NOTE: This is a lightweight informational pre-check only.
# The actual guard is in DecisionOrchestratorService.assemble_and_submit()
# Phase 4c — we do NOT duplicate the guard policy here.


def _serialize_precheck(health: SnapshotSyncHealthSummary) -> dict[str, object]:
    """Serialize a ``SnapshotSyncHealthSummary`` for cycle summary output."""
    return {
        "health_status": "stale" if health.is_stale else "ok",
        "last_successful_run_at": (
            health.last_successful_run_at.isoformat()
            if health.last_successful_run_at
            else None
        ),
        "last_run_status": health.last_status,
        "consecutive_failures": health.consecutive_failures,
        "stale_threshold_seconds": health.stale_threshold_seconds,
    }


async def _run_precheck(
    repos: RepositoryContainer,
    stale_threshold: int = 900,
) -> dict[str, object] | None:
    """Lightweight pre-check: snapshot sync health summary.

    Returns a dict for the cycle summary, or ``None`` if the check is
    unavailable (e.g. the repository does not support it).

    Does NOT block execution — the real stale-snapshot guard is in
    Phase 4c of ``assemble_and_submit()``.
    """
    try:
        health = await repos.snapshot_sync_runs.get_sync_health_summary(
            stale_threshold_seconds=stale_threshold,
        )
        precheck = _serialize_precheck(health)
        if health.is_stale:
            logger.info(
                "Pre-check: snapshot sync is STALE "
                "(last_successful=%s, threshold=%ds). "
                "Phase 4c guard will block submit if stale.",
                health.last_successful_run_at,
                health.stale_threshold_seconds,
            )
        elif health.last_successful_run_at is None:
            logger.info(
                "Pre-check: snapshot sync has NO HISTORY. "
                "Phase 4c guard will block submit if no_history policy applies."
            )
        else:
            logger.info(
                "Pre-check: snapshot sync HEALTHY (last_successful=%s).",
                health.last_successful_run_at,
            )
        return precheck
    except Exception as exc:
        logger.warning("Pre-check failed: %s", exc)
        return None


# ── Result serialization ────────────────────────────────────────────────────


def _serialize_cycle_result(
    cycle: int,
    result: SubmitResult | None,
    duration: float,
    *,
    symbol: str = SYMBOL,
    market: str = MARKET,
    precheck: dict[str, object] | None = None,
    dry_run: bool = False,
    error: str | None = None,
    ei_output: dict[str, object] | None = None,
    source_type: str = "core",
) -> dict[str, object]:
    """Serialize a single decision cycle result.

    Parameters
    ----------
    cycle:
        Cycle number (1-based).
    result:
        The ``SubmitResult`` from the orchestrator, or ``None`` on error.
    duration:
        Wall-clock duration of the cycle in seconds.
    precheck:
        Optional pre-check result (snapshot sync health summary).
    dry_run:
        Whether this cycle was a dry-run (assemble + sizing only).
    error:
        Top-level error message, if the cycle failed before producing a result.
    ei_output:
        Optional EI Agent output (event_bias, event_conflict, event_reason_codes).
    source_type:
        Source type of the universe item (core, held_position, etc.).
        scheduler-level budget 분기에서 사용된다.
    """
    now = datetime.now(timezone.utc)
    started_at = now.isoformat()
    completed_at = now.isoformat()

    # decision_type과 side는 모든 분기에서 항상 포함되어야 한다.
    # scheduler-level budget 분기(_is_held_position_sell_result)에서
    # 3중 조건(source_type + decision_type + side) 판별에 사용된다.
    decision_type: str | None = None
    side: str | None = None

    if result is not None and result.order_intent is not None:
        decision_type = result.order_intent.ai_backend_inputs.decision_type
        side = result.order_intent.ai_backend_inputs.side

    data: dict[str, object] = {
        "cycle": cycle,
        "symbol": symbol,
        "market": market,
        "source_type": source_type,
        "decision_type": decision_type,
        "side": side,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_seconds": max(round(duration, 3), 0.001) if duration > 0 else 0.0,
    }

    if precheck is not None:
        data["precheck"] = precheck

    if error:
        data["status"] = "ERROR"
        data["error"] = error
    elif dry_run:
        # Dry-run mode: assemble + sizing, no broker submit
        data["status"] = "DRY_RUN"
        if result is not None and result.order_intent is not None:
            data["decision_context_id"] = (
                str(result.decision_context_id) if result.decision_context_id else None
            )
            data["trade_decision_id"] = (
                str(result.trade_decision_id) if result.trade_decision_id else None
            )
            data["order_intent_id"] = str(result.order_intent.order_intent_id)
            data["sized_quantity"] = str(result.order_intent.request.quantity)
            # EXE-001: phase trace
            data["phase_trace"] = [
                {"phase": pt.phase, "elapsed_ms": pt.elapsed_ms, "status": pt.status}
                for pt in result.phase_trace
            ] if result.phase_trace else []
    elif result is not None:
        data["status"] = result.status
        data["error_phase"] = result.error_phase
        data["error_message"] = result.error_message
        data["decision_context_id"] = (
            str(result.decision_context_id) if result.decision_context_id else None
        )
        data["trade_decision_id"] = (
            str(result.trade_decision_id) if result.trade_decision_id else None
        )
        if result.order_intent is not None:
            data["order_intent_id"] = str(result.order_intent.order_intent_id)
            data["sized_quantity"] = str(result.order_intent.request.quantity)
        if result.submit_response is not None:
            data["order_request_id"] = str(result.submit_response.order_request_id)
            data["order_status"] = result.submit_response.status.value
            data["client_order_id"] = result.submit_response.client_order_id
            data["requested_quantity"] = str(result.submit_response.requested_quantity)
        # EXE-001: phase trace
        data["phase_trace"] = [
            {"phase": pt.phase, "elapsed_ms": pt.elapsed_ms, "status": pt.status}
            for pt in result.phase_trace
        ] if result.phase_trace else []
    else:
        data["status"] = "UNKNOWN"

    if ei_output is not None:
        data["ei_output"] = ei_output

    return data


def _build_aggregate_summary(
    results: list[dict[str, object]],
    total_duration: float,
) -> dict[str, object]:
    """Build an aggregate summary from all cycle results."""
    total = len(results)
    success = sum(
        1
        for r in results
        if r.get("status") in ("SUBMITTED", "DRY_RUN", "SKIPPED")
    )
    skipped = sum(1 for r in results if r.get("status") == "SKIPPED")
    errors = sum(1 for r in results if r.get("status") in ("ERROR", "UNKNOWN"))

    return {
        "mode": "summary",
        "total_cycles": total,
        "success": success,
        "skipped": skipped,
        "error": errors,
        "success_rate": round(success / total * 100, 1) if total > 0 else 0,
        "total_duration_seconds": round(total_duration, 3),
    }


# ── Core cycle ──────────────────────────────────────────────────────────────


# Per-agent hard timeout: safety net for the assemble_and_submit() call.
# Phase 4 subprocess isolation provides SIGKILL-guaranteed timeout at the
# subprocess level (30s), so this outer timeout is a last-resort safety
# net rather than the primary timeout mechanism.
# Reduced from 420s to 150s to align with deepseek-chat P99 latency
# (~15.9s) with 9.4x safety margin covering all 3 agents + overhead.
# The scheduler-level _DECISION_TIMEOUT (600s) covers the entire
# asyncio.gather() for all universe symbols.
PER_AGENT_HARD_TIMEOUT = 150  # seconds

# ── T3 (Seeded News) timeout & freshness ─────────────────────────────────────
# T3 pipeline (KIS disclosure + NAVER news search) has no hard timeout
# and can block the critical path for minutes.  Decoupled via parallel
# execution with this timeout for the live pipeline.
_T3_TIMEOUT = 60            # T3 pipeline 전체 timeout (초)
_T3_FRESHNESS_SECONDS = 7200  # T3 freshness window (2시간)
_T3_GATHER_WAIT = 5         # decision 완료 후 T3 추가 대기시간 (초)

# ── T3 async task tracking ──────────────────────────────────────────────────
# Active T3 pipeline tasks running in background (fire-and-forget via
# asyncio.create_task).  These are drained at cycle end so that persisted
# events are available for the next cycle's freshness check.
_active_t3_tasks: set[asyncio.Task] = set()

async def _run_one_cycle(
    cycle: int,
    *,
    submit: bool,
    dry_run: bool,
    output: str,
    symbol: str = SYMBOL,
    market: str = MARKET,
    source_type: str = "core",
    runtime: dict[str, object],              # ★ 공유 runtime (외부에서 주입)
    cycle_precheck: dict[str, object] | None = None,  # ★ cycle precheck (외부에서 주입)
) -> dict[str, object]:
    """Execute a single decision cycle with shared runtime.

    Per-symbol transaction을 생성하여 격리를 보장한다.
    Runtime (pool, httpx clients, agents)은 외부에서 주입받아 공유한다.

    Returns a serialized result dict.
    """
    start = time.monotonic()
    precheck: dict[str, object] | None = cycle_precheck
    logger.info(
        "[SYMBOL_START] cycle=%d symbol=%s market=%s submit=%s dry_run=%s source_type=%s",
        cycle, symbol, market, submit, dry_run, source_type,
    )


    try:
        # ★ Per-symbol transaction 생성 (격리 보장)
        # 변경 전: postgres_runtime()이 하나의 transaction을 모든 symbol이 공유
        # 변경 후: 각 symbol이 독립적 transaction 사용
        from agent_trading.db.transaction import transaction as _db_transaction
        from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories
        from agent_trading.services.decision_orchestrator import DecisionOrchestratorService
        from agent_trading.services.order_manager import OrderManager
        from agent_trading.services.reconciliation_service import ReconciliationService

        async with _db_transaction() as tx:
            repos: RepositoryContainer = build_postgres_repositories(tx)
            orchestrator = DecisionOrchestratorService(repos=repos)
            reconciliation_service = ReconciliationService(repos=repos)
            order_manager = OrderManager(
                repos=repos,
                reconciliation_service=reconciliation_service,
            )

            # ── 3. Build request ────────────────────────────────────────
            # NOTE: _resolve_symbol_price() 호출 제거됨 — 현재 전면 MARKET 정책으로
            # price=None을 사용하며, quote fetch는 execution_service._resolve_quote()에서
            # 단일 경로로 처리됨. 중복 quote fetch로 인한 KIS rate limit 문제 해결.
            order_type, price = _resolve_order_type_and_price(
                side="buy",
                decision_type=None,
                default_price=None,
            )
            request = SubmitOrderRequest(
                account_ref=ACCOUNT_ALIAS,
                client_order_id=f"paper-loop-{symbol}-{cycle}-{int(start)}",
                correlation_id=f"paper-loop-{symbol}-{cycle}-{int(start)}",
                strategy_id=str(STRATEGY_ID),
                symbol=symbol,
                market=market,
                side=OrderSide.BUY,
                order_type=order_type,
                quantity=Decimal("1"),
                price=price,
                metadata={"source_type": source_type},
            )

            # ── 3.5 Seeded news → degraded path with parallel T3 ─────────
            # T3 pipeline is decoupled from the critical decision/submit path.
            # Decision path: reads persisted T3 events from DB only (fast, non-blocking).
            # T3 live path: runs in parallel via create_task, results persisted
            # for future cycles.  Freshness check prevents unnecessary live calls.
            _SEEDED_NEWS_ENABLED = os.environ.get("SEEDED_NEWS_ENABLED", "1") == "1"
            seeded_events: list[ExternalEventEntity] = []

            if _SEEDED_NEWS_ENABLED:
                # ── T3 pipeline skip for held_position and market_overlay ──
                # These source types do not benefit from seeded news context
                # and skipping them saves Naver API quota.
                if source_type in ("held_position", "market_overlay"):
                    logger.debug(
                        "Skipping T3 live pipeline for symbol=%s source_type=%s",
                        symbol, source_type,
                    )
                    # Still read persisted events for decision context
                    seeded_events = await _collect_persisted_seeded_events(repos, symbol)
                else:
                    # ── Decision path: read persisted T3 events (non-blocking) ──
                    seeded_events = await _collect_persisted_seeded_events(repos, symbol)

                    # ── T3 live path: run synchronously (await) before assemble ──
                    t3_fresh = await _is_t3_fresh_for_symbol(repos, symbol)
                    if not t3_fresh:
                        # ── NAVER quota preemptive check ──
                        # If NAVER daily quota is >= 90% exhausted, skip the
                        # live pipeline entirely to avoid 429 timeouts.
                        from agent_trading.brokers.naver_news_adapter import (
                            NaverNewsSearchAdapter,
                        )
                        if NaverNewsSearchAdapter.is_quota_exhausted():
                            logger.warning(
                                "T3 live pipeline skipped for symbol=%s: "
                                "NAVER quota exhausted (%.1f%%)",
                                symbol,
                                NaverNewsSearchAdapter.get_daily_usage_ratio() * 100,
                            )
                        else:
                            # Fire-and-forget: T3 pipeline runs in background,
                            # decision path continues immediately (not blocked).
                            task = asyncio.create_task(
                                _run_t3_live_pipeline_shielded(
                                    runtime, repos, symbol, source_type=source_type
                                )
                            )
                            _active_t3_tasks.add(task)
                            task.add_done_callback(_active_t3_tasks.discard)

                    # ── Logging ──
                    freshness_hint = "fresh" if t3_fresh else "stale"
                    logger.info(
                        "Cycle %d symbol=%s: T3 decision path: %d persisted events "
                        "live_pipeline=%s",
                        cycle, symbol, len(seeded_events),
                        "skipped (fresh)" if t3_fresh else "sync_executed",
                    )
            else:
                logger.info(
                    "Cycle %d symbol=%s: T3 skipped (SEEDED_NEWS_ENABLED=0)",
                    cycle, symbol,
                )

            # ── 4. Execute cycle ────────────────────────────────────────
            if dry_run:
                # Dry-run: assemble + sizing only
                # Per-agent hard timeout: prevents LLM API stall from blocking
                # the cycle indefinitely.
                intent = await asyncio.wait_for(
                    orchestrator.assemble(
                        request,
                        seeded_events=seeded_events,
                    ),
                    timeout=PER_AGENT_HARD_TIMEOUT,
                )
                sizing_inputs = orchestrator.build_sizing_inputs(intent)
                sizing_result = calculate_sizing(sizing_inputs)

                # Build synthetic SubmitResult for consistent serialization
                result = SubmitResult(
                    status="DRY_RUN",
                    order_intent=intent,
                    trade_decision_id=None,
                    decision_context_id=intent.decision_context_id,
                )

                if sizing_result.applied_constraints:
                    logger.info(
                        "Cycle %d (dry-run): sizing constraints=%s quantity=%s",
                        cycle,
                        sizing_result.applied_constraints,
                        sizing_result.quantity,
                    )
            elif submit:
                # Full pipeline: assemble → submit
                # order_manager와 broker는 runtime에서 공유 객체 사용
                broker = runtime["primary_broker_adapter"]
                # Per-agent hard timeout: prevents LLM API stall from blocking
                # the cycle indefinitely.
                result = await asyncio.wait_for(
                    orchestrator.assemble_and_submit(
                        request,
                        order_manager=order_manager,
                        broker=broker,
                        seeded_events=seeded_events,
                    ),
                    timeout=PER_AGENT_HARD_TIMEOUT,
                )
                if result is not None:
                    logger.info(
                        "Cycle %d submit result: status=%s error_phase=%s "
                        "error_message=%s trade_decision_id=%s",
                        cycle,
                        result.status,
                        getattr(result, "error_phase", None),
                        getattr(result, "error_message", None),
                        getattr(result, "trade_decision_id", None),
                    )
            else:
                # Should not happen (CLI defaults ensure submit=True or dry_run)
                result = SubmitResult(
                    status="ERROR",
                    error_phase="config",
                    error_message="Neither --submit nor --dry-run was set.",
                )

            # ── 4.5 Collect EI Agent output ──────────────────────────────
            ei_output: dict[str, object] | None = None
            if result is not None and result.order_intent is not None:
                ai_inputs = result.order_intent.ai_backend_inputs
                ei_output = {
                    "event_bias": ai_inputs.event_bias,
                    "event_conflict": ai_inputs.event_conflict,
                    "event_reason_codes": list(ai_inputs.event_reason_codes),
                }

            # ── 5. Commit per-symbol transaction ─────────────────────────
            await tx.commit()

            duration = time.monotonic() - start
            logger.info(
                "[SYMBOL_DONE] cycle=%d symbol=%s status=%s duration=%.1fs",
                cycle, symbol,
                result.status if result is not None else "ERROR",
                duration,
            )
            return _serialize_cycle_result(
                cycle,
                result,
                duration,
                symbol=symbol,
                market=market,
                precheck=precheck,
                dry_run=dry_run,
                ei_output=ei_output,
                source_type=source_type,
            )

    except asyncio.TimeoutError:
        duration = time.monotonic() - start
        _dc_id = getattr(request, 'decision_context_id', None) if 'request' in dir() else None
        logger.error(
            "PER_AGENT_HARD_TIMEOUT=%ds exceeded after %.1fs — "
            "raising to skip this symbol only.  symbol=%s decision_context_id=%s",
            PER_AGENT_HARD_TIMEOUT, duration, symbol, _dc_id,
        )
        # Cancel all pending asyncio tasks to allow C-level I/O (e.g. httpx
        # socket read) to unblock.  Without explicit cancellation, the event
        # loop may remain blocked on C-level I/O.
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()
        # Allow cancellations to propagate through the event loop
        await asyncio.sleep(0.5)
        # Raise to let _process_one()'s except Exception handler catch this
        # and record ERROR status, so remaining symbols continue processing.
        raise RuntimeError(
            f"TIMEOUT for symbol={symbol} "
            f"(PER_AGENT_HARD_TIMEOUT={PER_AGENT_HARD_TIMEOUT}s)"
        )
    except Exception as exc:
        duration = time.monotonic() - start
        logger.exception("[SYMBOL_DONE] cycle=%d symbol=%s status=ERROR duration=%.1fs error=%s", cycle, symbol, duration, exc)
        return _serialize_cycle_result(
            cycle,
            None,
            duration,
            symbol=symbol,
            market=market,
            precheck=precheck,
            dry_run=dry_run,
            error=str(exc),
            source_type=source_type,
        )


# ── Seeded news persistence ─────────────────────────────────────────────────


async def persist_seeded_events(
    events: list[ExternalEventEntity],
    repo: ExternalEventRepository,
) -> int:
    """
    Persist seeded news events to external_events table with dedup.

    Returns count of newly persisted events.
    - DB: long-term storage, analysis, audit trail
    - Transient injection to EI still happens separately via orchestrator.assemble()
    """
    persisted = 0
    skipped = 0
    for event in events:
        try:
            existing = await repo.find_by_dedup_key(event.dedup_key_hash)
            if existing is None:
                await repo.add(event)
                persisted += 1
            else:
                skipped += 1
        except Exception:
            logger.exception("Failed to persist seeded event: %s", event.dedup_key_hash)
            # Non-fatal: transient injection still works

    if persisted > 0 or skipped > 0:
        logger.info(
            "Seeded events persisted=%d skipped=%d total=%d",
            persisted, skipped, len(events),
        )
    return persisted


def _convert_disclosure_seeds_to_events(
    seeds: list,
    tier: str = "T2",
) -> list[ExternalEventEntity]:
    """Convert KIS disclosure seed DTOs to ExternalEventEntity list.

    These are KIS disclosure events (not seeded_news), so they have:
    - event_type = "Y|{headline}" (KIS disclosure prefix)
    - source_reliability_tier = ``tier`` (default "T2")

    When ``tier="T2"`` (default), this does NOT affect
    ``has_fresh_t3_events()`` since the tier is T2.  But provides
    decision context via ``_collect_persisted_seeded_events()``.

    When ``tier="T3"`` (degraded mode), KIS disclosure seeds are
    stored as T3 events, which enables ``has_fresh_t3_events()``
    freshness check and ``_collect_persisted_seeded_events()``
    to include them in the decision context.
    """
    from uuid import uuid4

    from agent_trading.domain.models import DisclosureTitleDTO

    events: list[ExternalEventEntity] = []
    for seed in seeds:
        assert isinstance(seed, DisclosureTitleDTO), (
            f"Expected DisclosureTitleDTO, got {type(seed).__name__}"
        )
        event = ExternalEventEntity(
            event_id=uuid4(),
            event_type=f"Y|{seed.headline}",
            source_name="kis_disclosure",
            source_reliability_tier=tier,
            symbol=seed.symbol,
            market="KR",
            published_at=datetime.now(timezone.utc),
            ingested_at=datetime.now(timezone.utc),
            severity="medium",
            direction="neutral",
            headline=seed.headline,
        )
        events.append(event)
    return events


# ── T3 degraded path helpers ─────────────────────────────────────────────────


async def _collect_persisted_seeded_events(
    repos: RepositoryContainer,
    symbol: str,
) -> list[ExternalEventEntity]:
    """Read persisted T3 events from external_events table.

    This is the **degraded** path: only events persisted by previous
    T3 runs are available.  Returns [] if none found — the decision
    cycle proceeds gracefully without seeded news.

    Freshness: events within 72h window (same as current list_by_symbol
    default).  The caller decides whether to fire live pipeline based
    on _T3_FRESHNESS_SECONDS.

    Uses ``include_seeded_news=True`` so that ``event_type='seeded_news'``
    events (which do not carry the listed-event prefix) are included in
    the query result alongside listed OpenDART events.
    """
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=72)
        events = await repos.external_events.list_by_symbol(
            symbol=symbol,
            since=since,
            include_seeded_news=True,
        )
        # Filter to T3 events only (seeded news = T3 reliability tier)
        t3_events = [e for e in events if e.source_reliability_tier == "T3"]
        return t3_events
    except Exception:
        logger.exception(
            "Failed to read persisted seeded events for symbol=%s", symbol,
        )
        return []


async def _is_t3_fresh_for_symbol(
    repos: RepositoryContainer,
    symbol: str,
) -> bool:
    """Check if T3 events exist for symbol within freshness window.

    Returns ``True`` on DB error (fail-closed) to protect NAVER quota
    by preventing unnecessary T3 live pipeline execution.
    """
    try:
        return await repos.external_events.has_fresh_t3_events(
            symbol=symbol,
            freshness_seconds=_T3_FRESHNESS_SECONDS,
        )
    except Exception:
        logger.warning(
            "T3 freshness check failed for symbol=%s — assuming fresh to protect NAVER quota",
            symbol,
        )
        return True  # fail-closed: DB 장애 시 "fresh"로 간주하여 live pipeline 실행 방지


async def _run_t3_live_pipeline(
    runtime: dict[str, object],
    repos: RepositoryContainer,
    symbol: str,
    source_type: str = "core",
) -> None:
    """Run live T3 pipeline (KIS disclosure + NAVER news) with timeout.

    This is designed to run **as a parallel task** via asyncio.create_task()
    alongside the decision path.  Results are persisted to DB for
    consumption by future cycles.

    On timeout, persists any partially collected events so that subsequent
    cycles can benefit from them even when NAVER API is degraded.

    Parameters
    ----------
    source_type : str
        Source type for query count policy.
        - ``"core"``: max_queries=1
        - ``"event_overlay"``: max_queries=1
        - ``"held_position"`` / ``"market_overlay"``: 이 경로에 도달하지 않음

    Log tags:
    - "T3 used live" — live pipeline 성공, DB persist 완료
    - "T3 partial persist on timeout" — timeout 시 partial persist 성공
    - "T3 skipped" — timeout 또는 disable로 skip
    """
    # Declare variables outside try so they are accessible in except blocks
    t0 = time.monotonic()
    seeds = None
    candidates = None
    seeded_events = None
    seed_errors = None

    try:
        # ── Preemptive NAVER quota check (이중 방어) ──
        from agent_trading.brokers.naver_news_adapter import (
            NaverNewsSearchAdapter,
        )
        naver_quota_exhausted = NaverNewsSearchAdapter.is_quota_exhausted()

        disclosure_seed_service = runtime.get("disclosure_seed_service")
        seeded_news_service = runtime.get("seeded_news_service")
        if disclosure_seed_service is None or seeded_news_service is None:
            logger.info("symbol=%s T3 skipped: services not available", symbol)
            return

        from agent_trading.db.transaction import transaction as _db_transaction
        from agent_trading.repositories.postgres.external_events import (
            PostgresExternalEventRepository,
        )

        # Step 1: Fetch disclosure titles (KIS API)
        seeds = await asyncio.wait_for(
            disclosure_seed_service.fetch_disclosure_titles([symbol]),
            timeout=_T3_TIMEOUT,
        )
        if not seeds:
            logger.info("symbol=%s T3 skipped: no disclosure seeds", symbol)
            return

        # ── Degraded mode: NAVER quota exhausted → persist KIS disclosure as T3 ──
        if naver_quota_exhausted:
            logger.warning(
                "symbol=%s T3 degraded mode: NAVER quota exhausted (%.1f%%), "
                "persisting %d KIS disclosure seeds as T3 events",
                symbol,
                NaverNewsSearchAdapter.get_daily_usage_ratio() * 100,
                len(seeds),
            )
            # Persist KIS disclosure seeds as T3 events so that
            # has_fresh_t3_events() freshness check and
            # _collect_persisted_seeded_events() can include them.
            partial_events = _convert_disclosure_seeds_to_events(seeds, tier="T3")
            async with _db_transaction() as tx:
                tx_repo = PostgresExternalEventRepository(tx)
                persisted = await persist_seeded_events(partial_events, tx_repo)
            logger.info(
                "symbol=%s T3 degraded: %d disclosure seeds persisted=%d as T3",
                symbol, len(seeds), persisted,
            )
            return

        # Step 2: Process seeds via NAVER news search
        # Source type별 Naver query 수 정책
        _source_type_max_queries: dict[str, int | None] = {
            "core": 1,
            "event_overlay": 1,
            "held_position": 1,
        }
        max_queries = _source_type_max_queries.get(source_type, None)
        candidates, metrics = await asyncio.wait_for(
            seeded_news_service.process_seeds(seeds, max_queries=max_queries),
            timeout=_T3_TIMEOUT,
        )

        # ── 429 감지: NAVER quota exhausted → degraded fallback ──
        if metrics.quota_exhausted_count > 0:
            logger.warning(
                "T3 degraded for symbol=%s: NAVER quota exhausted (%d seeds affected) — "
                "persisting KIS disclosure seeds as T3 events",
                symbol,
                metrics.quota_exhausted_count,
            )
            # KIS disclosure seeds를 T3 이벤트로 직접 persist (degraded mode)
            try:
                partial_events = _convert_disclosure_seeds_to_events(seeds, tier="T3")
                async with _db_transaction() as tx:
                    tx_repo = PostgresExternalEventRepository(tx)
                    partial_persisted = await persist_seeded_events(partial_events, tx_repo)
                    logger.info(
                        "T3 degraded persist for symbol=%s: %d events persisted",
                        symbol,
                        partial_persisted,
                    )
            except Exception:
                logger.exception(
                    "T3 degraded persist failed for symbol=%s", symbol,
                )
            return  # early return: pipeline 완료

        if not candidates:
            logger.info("symbol=%s T3 skipped: no candidates after processing", symbol)
            return

        # Step 3: Convert to ExternalEventEntity
        from agent_trading.services.seeded_news_converter import (
            convert_seeded_candidates,
        )
        seeded_events = convert_seeded_candidates(candidates)

        # Step 4: Persist to DB (use own transaction since parent context is closed)
        async with _db_transaction() as tx:
            ee_repo = PostgresExternalEventRepository(tx)
            persisted = await persist_seeded_events(seeded_events, ee_repo)
        logger.info(
            "symbol=%s T3 used live: %d events from %d candidates "
            "persisted=%d",
            symbol,
            len(seeded_events), len(candidates),
            persisted,
        )

    except asyncio.TimeoutError:
        elapsed = time.monotonic() - t0
        logger.warning(
            "T3 live pipeline timed out after %.1fs for symbol=%s "
            "(source_type=%s, seeds=%d, candidates=%d, seed_errors=%d)",
            elapsed, symbol, source_type, len(seeds or []),
            len(candidates or []),
            len(seed_errors or []),
        )
        # Lazy imports for transaction-scoped repository
        from agent_trading.db.transaction import transaction as _db_transaction
        from agent_trading.repositories.postgres.external_events import (
            PostgresExternalEventRepository,
        )

        persisted = 0
        try:
            async with _db_transaction() as tx:
                tx_repo = PostgresExternalEventRepository(tx)

                if seeded_events is not None:
                    # Step 3 (convert) completed, Step 4 (persist) timed out
                    persisted = await persist_seeded_events(seeded_events, tx_repo)
                    logger.info(
                        "symbol=%s T3 partial persist on timeout: %d events",
                        symbol, len(seeded_events),
                    )
                elif candidates is not None:
                    # Step 2 (process) completed, Step 3 (convert) timed out
                    from agent_trading.services.seeded_news_converter import (
                        convert_seeded_candidates,
                    )
                    partial_events = convert_seeded_candidates(candidates)
                    persisted = await persist_seeded_events(partial_events, tx_repo)
                    logger.info(
                        "symbol=%s T3 partial persist on timeout: "
                        "%d candidates -> %d events",
                        symbol, len(candidates), len(partial_events),
                    )
                elif seeds is not None and len(seeds) > 0:
                    # Step 1 (disclosure) completed, Step 2 (process) timed out
                    # Persist KIS disclosure seeds as T3 events so that
                    # has_fresh_t3_events() recognizes them and prevents
                    # redundant T3 pipeline re-execution within the freshness window.
                    # Also provides decision context via _collect_persisted_seeded_events().
                    partial_events = _convert_disclosure_seeds_to_events(seeds, tier="T3")
                    persisted = await persist_seeded_events(partial_events, tx_repo)
                    logger.info(
                        "symbol=%s T3 partial persist on timeout: "
                        "%d disclosure seeds -> %d events (step 1 only)",
                        symbol, len(seeds), len(partial_events),
                    )
                else:
                    logger.warning(
                        "symbol=%s T3 skipped: live pipeline timed out after %ds "
                        "(no partial data to persist)",
                        symbol, _T3_TIMEOUT,
                    )
                # tx.__aexit__ auto-commits on success
        except Exception:
            logger.exception(
                "T3 partial persist failed for symbol=%s", symbol,
            )
        if persisted:
            logger.info(
                "T3 partial persist: %d seeded events for symbol=%s",
                persisted, symbol,
            )
    except Exception:
        logger.exception(
            "symbol=%s T3 skipped: live pipeline failed", symbol,
        )


async def _run_t3_live_pipeline_shielded(
    runtime: dict[str, object],
    repos: RepositoryContainer,
    symbol: str,
    source_type: str = "core",
) -> None:
    """Wrapper that runs ``_run_t3_live_pipeline`` under ``asyncio.shield()``.

    ``asyncio.shield()`` prevents external ``cancel()`` (e.g. from
    ``_run_one_cycle()``'s ``all_tasks().cancel()``) from propagating to the
    T3 live pipeline task, ensuring partial persist runs to completion.

    This is used via ``asyncio.create_task(_run_t3_live_pipeline_shielded(...))``
    rather than ``asyncio.create_task(asyncio.shield(...))``, because
    ``asyncio.shield()`` returns a ``Future`` while ``create_task()`` requires a
    coroutine.
    """
    return await asyncio.shield(
        _run_t3_live_pipeline(runtime, repos, symbol, source_type=source_type)
    )


# ── Main loop ───────────────────────────────────────────────────────────────


async def _run_loop(
    *,
    interval: int,
    max_cycles: int,
    submit: bool,
    dry_run: bool,
    allow_general_submit: bool,
    output: str,
) -> int:
    """Main loop: run decision cycles until shutdown or count limit.

    Returns an exit code (0 = all cycles successful, 1 = any error).
    """
    logger.info(
        "Starting paper decision loop "
        "(interval=%ds, max_cycles=%s, submit=%s, dry_run=%s, output=%s) ...",
        interval,
        "infinite" if max_cycles <= 0 else str(max_cycles),
        submit,
        dry_run,
        output,
    )
    logger.info("Set %s to change interval (default=%d).", ENV_INTERVAL, DEFAULT_INTERVAL_SECONDS)
    universe = await _read_trading_universe()
    logger.info(
        "Trading universe (%d): %s",
        len(universe),
        ", ".join(f"{item.symbol}:{item.market}" for item in universe),
    )
    logger.info("Set %s to change universe (comma-separated symbols).", ENV_TRADING_UNIVERSE)

    _install_signal_handlers()

    cycle_count = 0
    total_success = 0
    total_fail = 0
    results: list[dict[str, object]] = []
    loop_start = time.monotonic()

    # ── Runtime: 루프 진입 시 1회 생성, 모든 symbol이 공유 ──────────────
    # 변경 전: _run_one_cycle()이 각 symbol마다 postgres_runtime() 생성
    # 변경 후: _run_loop()에서 1회 생성, per-symbol transaction만 분리
    async with postgres_runtime(run_migrations=False) as runtime:
        # ── 최초 1회 seed (FK 체인) ─────────────────────────────────────
        # 변경 전: 각 symbol의 _run_one_cycle()에서 _seed_if_empty() 호출
        # 변경 후: 루프 진입 시 1회만 실행
        from agent_trading.db.transaction import transaction as _db_transaction
        from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories

        async with _db_transaction() as tx:
            seed_repos = build_postgres_repositories(tx)
            seeded = await _seed_if_empty(seed_repos)
            if seeded:
                logger.info("Initial seed completed.")
            else:
                logger.debug("Seed already exists (skipped).")
            await tx.commit()

        while not _shutdown_event.is_set():
            # Check cycle limit
            if max_cycles > 0 and cycle_count >= max_cycles:
                logger.info("Reached requested cycle count (%d).", max_cycles)
                break

            cycle_count += 1
            logger.info("=== Decision Cycle %d ===", cycle_count)

            # ── Cycle당 1회 precheck (snapshot sync health) ─────────────
            # 변경 전: 각 symbol의 _run_one_cycle()에서 _run_precheck() 호출
            # 변경 후: cycle당 1회만 실행, 모든 symbol이 동일한 precheck 공유
            cycle_precheck: dict[str, object] | None = None
            try:
                async with _db_transaction() as tx:
                    precheck_repos = build_postgres_repositories(tx)
                    cycle_precheck = await _run_precheck(precheck_repos)
                    await tx.commit()
            except Exception as exc:
                logger.warning("Cycle pre-check failed: %s", exc)

            # Semaphore-based parallel symbol processing.
            # Max 5 concurrent symbols to avoid overwhelming broker/LLM resources
            # while reducing total wall-clock time from ~190s to ~40s for 35 symbols.
            _SEMAPHORE_MAX = 5
            sem = asyncio.Semaphore(_SEMAPHORE_MAX)
            submit_budget_consumed = False
            # held_position REDUCE/EXIT sell은 위험 축소 목적이므로 일일 제출 상한 없음.
            # cycle 내 중복 submit 방지용 카운터만 유지 (symbol dedupe + cycle cap).
            held_position_sell_cycle_count = 0
            held_position_sell_cycle_symbols: set[str] = set()
            _submit_lock = asyncio.Lock()

            async def _process_one(item: object) -> dict[str, object]:
                """Process a single universe item with semaphore concurrency cap."""
                nonlocal submit_budget_consumed
                nonlocal held_position_sell_cycle_count
                nonlocal held_position_sell_cycle_symbols
                async with sem:
                    # In submit mode, evaluate all symbols but allow at most one
                    # budget-consuming broker submit per script invocation.
                    # held_position sell은 별도 budget으로 관리되어 일반 submit과 분리된다.
                    async with _submit_lock:
                        item_source_type = getattr(item, "source_type", "core")
                        symbol_submit, symbol_dry_run = _compute_symbol_submit_mode(
                            submit=submit,
                            dry_run=dry_run,
                            allow_general_submit=allow_general_submit,
                            source_type=item_source_type,
                            submit_budget_consumed=submit_budget_consumed,
                            held_position_sell_cycle_count=held_position_sell_cycle_count,
                            held_position_sell_cycle_symbols=held_position_sell_cycle_symbols,
                            symbol=item.symbol,
                        )
                        if symbol_submit and item_source_type != "held_position":
                            # Reserve before running the symbol.  Without this,
                            # concurrent tasks can all observe False and submit
                            # multiple BUY orders in the same cycle.
                            submit_budget_consumed = True

                    # HP sell block 이유 로깅 (explainability)
                    is_held_position_item = item_source_type == "held_position"
                    if is_held_position_item and not symbol_submit and submit and not dry_run:
                        reasons = []
                        if held_position_sell_cycle_count >= HELD_POSITION_SELL_MAX_PER_CYCLE:
                            reasons.append("cycle_cap_reached")
                        if item.symbol in held_position_sell_cycle_symbols:
                            reasons.append("symbol_duplicate")
                        if reasons:
                            logger.info(
                                "HP sell block: symbol=%s reasons=%s",
                                item.symbol, ",".join(reasons),
                            )

                    try:
                        result = await _run_one_cycle(
                            cycle=cycle_count,
                            submit=symbol_submit,
                            dry_run=symbol_dry_run,
                            output=output,
                            symbol=item.symbol,
                            market=item.market,
                            source_type=item.source_type,
                            runtime=runtime,              # ★ 공유 runtime 전달
                            cycle_precheck=cycle_precheck,  # ★ cycle precheck 전달
                        )
                    except Exception as exc:
                        logger.exception(
                            "Cycle %d symbol=%s:%s: unexpected error in parallel processing: %s",
                            cycle_count, item.symbol, item.market, exc,
                        )
                        result = {
                            "status": "ERROR",
                            "symbol": item.symbol,
                            "market": item.market,
                            "error": str(exc),
                            "duration_seconds": 0.0,
                        }

                    status = result.get("status", "UNKNOWN")
                    if status in ("SUBMITTED", "RECONCILE_REQUIRED"):
                        async with _submit_lock:
                            # 3중 조건: source_type == held_position AND decision_type in (reduce, exit) AND side == sell
                            result_decision_type = str(result.get("decision_type", "")).lower()
                            result_side = str(result.get("side", "")).lower()
                            is_held_position_sell = (
                                getattr(item, "source_type", "core") == "held_position"
                                and result_decision_type in ("reduce", "exit")
                                and result_side == "sell"
                            )
                            if is_held_position_sell:
                                # held_position sell은 일일 상한 없음 (위험 축소 목적).
                                # cycle 내 중복 방지용 카운터만 증가.
                                held_position_sell_cycle_count += 1
                                held_position_sell_cycle_symbols.add(item.symbol)
                            else:
                                submit_budget_consumed = True

                    # Output per-symbol result
                    if output == "json":
                        print(json.dumps(result, ensure_ascii=False))
                    else:
                        precheck_str = ""
                        precheck_data = result.get("precheck")
                        if isinstance(precheck_data, dict):
                            h = precheck_data.get("health_status", "?")
                            precheck_str = f" [health={h}]"
                        logger.info(
                            "Cycle %d/%s symbol=%s:%s complete — status=%s duration=%.2fs%s",
                            cycle_count,
                            "∞" if max_cycles == 0 else str(max_cycles),
                            item.symbol,
                            item.market,
                            status,
                            result.get("duration_seconds", 0),
                            precheck_str,
                        )

                    return result

            # Process ALL symbols concurrently with semaphore cap
            coros = [_process_one(item) for item in universe]
            cycle_results: list[dict[str, object]] = await asyncio.gather(*coros)
            results.extend(cycle_results)

            # ── Drain T3 background tasks ────────────────────────────────────
            # Wait for all fire-and-forget T3 pipelines to complete so that
            # persisted events are available for the next cycle's freshness check.
            if _active_t3_tasks:
                pending = list(_active_t3_tasks)
                _active_t3_tasks.clear()
                await asyncio.gather(*pending, return_exceptions=True)
                logger.debug(
                    "Drained %d T3 background task(s) after cycle %d.",
                    len(pending), cycle_count,
                )

            # Aggregate success/fail counts from parallel results
            for r in cycle_results:
                s = r.get("status", "UNKNOWN")
                if s in ("SUBMITTED", "DRY_RUN", "SKIPPED"):
                    total_success += 1
                else:
                    total_fail += 1

            # Wait for next cycle (or shutdown)
            if max_cycles > 0 and cycle_count >= max_cycles:
                break

            logger.debug(
                "Waiting %d seconds before next cycle …",
                interval,
            )
            try:
                await asyncio.wait_for(
                    _shutdown_event.wait(),
                    timeout=interval,
                )
                # Shutdown event was set during sleep
                break
            except asyncio.TimeoutError:
                pass

    # ── Runtime context exit: pool/agents 정리 ──────────────────────────
    # postgres_runtime()의 __aexit__에서 shutdown_postgres_runtime() 호출

    # ── Final summary ──
    total_duration = time.monotonic() - loop_start
    summary = _build_aggregate_summary(results, total_duration)

    if output == "json":
        print(json.dumps(summary, ensure_ascii=False))
    else:
        logger.info("=" * 60)
        logger.info("Paper decision loop complete.")
        logger.info("  total cycles : %d", summary["total_cycles"])
        logger.info("  success      : %d", summary["success"])
        logger.info("  skipped      : %d", summary["skipped"])
        logger.info("  error        : %d", summary["error"])
        if summary["total_cycles"] > 0:
            logger.info("  success rate : %.1f%%", summary["success_rate"])
        logger.info("  total time   : %.1fs", summary["total_duration_seconds"])
        logger.info("=" * 60)

    return 0 if total_fail == 0 else 1


# ── CLI ─────────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Paper continuous decision loop — run orchestrator "
                    "assemble/submit repeatedly for paper operations.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=0,
        help=f"Seconds between decision cycles (default: {DEFAULT_INTERVAL_SECONDS}s, "
             f"overridable via {ENV_INTERVAL}).",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        help="Number of cycles to run (0 = infinite, default).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Run assemble + sizing only — no broker submit.",
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        default=True,
        help="Run full assemble → submit pipeline (default).",
    )
    parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format: ``text`` (human-readable) or ``json`` (machine-readable).",
    )
    parser.add_argument(
        "--allow-general-submit",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Allow general/core submit lane. Disable to keep only held_position sell submits.",
    )
    return parser.parse_args(argv)


def _load_env() -> None:
    """Load .env if python-dotenv is available.

    Existing environment variables are not overwritten, which keeps Docker or
    manually exported runtime settings authoritative.
    """
    if load_dotenv is not None:
        load_dotenv()


def main(argv: list[str] | None = None) -> int:
    """Entry point for the continuous decision loop.

    .. note::
       This script is named ``run_decision_loop`` for historical
       reasons (it was introduced during the paper-trading milestone),
       but the core runtime logic is **mode-agnostic**.  The same
       ``assemble()`` → sizing → submit pipeline works identically
       for both paper and live modes.  Only the broker credentials /
       endpoint / rate-limit configuration (driven by ``AppSettings``)
       differ between environments.

       To switch to live mode, change the following env vars:
       ``KIS_ENV=live``, ``KIS_APP_KEY`` / ``KIS_APP_SECRET`` for live,
       ``KIS_ACCOUNT_NUMBER`` for live, ``KIS_BASE_URL`` / ``KIS_WS_URL``
       for live endpoints, and ``KIS_REAL_REST_RPS`` for live rate limits.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] paper-decision-loop: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # SIGTERM 핸들러 등록은 _install_signal_handlers()에서 loop.add_signal_handler()로 처리됨

    _load_env()

    args = _parse_args(argv)

    interval = args.interval or _read_interval()
    max_cycles = args.count

    # Validate conflicting options
    if args.dry_run and args.submit:
        # --submit is the default; --dry-run overrides
        logger.info("--dry-run overrides --submit. Running assemble + sizing only.")
        submit = False
        dry_run = True
    elif args.dry_run:
        submit = False
        dry_run = True
    else:
        submit = args.submit
        dry_run = False

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        exit_code = loop.run_until_complete(
            _run_loop(
                interval=interval,
                max_cycles=max_cycles,
                submit=submit,
                dry_run=dry_run,
                allow_general_submit=args.allow_general_submit,
                output=args.output,
            )
        )
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt — exiting.")
        exit_code = 0
    finally:
        try:
            for task in asyncio.all_tasks(loop):
                task.cancel()
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
