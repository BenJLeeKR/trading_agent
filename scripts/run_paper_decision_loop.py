#!/usr/bin/env python3
"""Paper continuous decision loop — 반복 운영 전용.

``run_orchestrator_once.py``는 단발 실행을 유지하고,
이 스크립트가 **연속 실행(continuous loop)** 을 담당한다.

기존 ``verify_paper_loop.py``는 **검증(verification)** 전용이며,
이 스크립트는 **운영(operations)** 전용이다.

역할 분리
---------
* ``run_snapshot_sync_loop.py`` — position/cash 데이터 최신성 유지 (300s)
* ``run_post_submit_sync_loop.py`` — 미체결/부분체결 주문 상태 Broker 수렴 (30s)
* ``run_paper_decision_loop.py`` — AI Decision → Submit 반복 실행 (300s, 신규)

Usage
-----
.. code-block:: bash

    # 기본 실행 (5분 간격, 무한 반복, submit 모드)
    python3 -m scripts.run_paper_decision_loop

    # 1회 실행 후 종료
    python3 -m scripts.run_paper_decision_loop --count 1

    # Dry-run (assemble + sizing only, submit 없음)
    python3 -m scripts.run_paper_decision_loop --count 1 --dry-run

    # 60초 간격, 5회, JSON 출력
    python3 -m scripts.run_paper_decision_loop --interval 60 --count 5 --output json

    # 명시적 submit 모드 (기본값)
    python3 -m scripts.run_paper_decision_loop --submit --count 1

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

from agent_trading.domain.enums import OrderSide, OrderType
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.contracts import SnapshotSyncHealthSummary
from agent_trading.repositories.filters import AccountLookup
from agent_trading.runtime.bootstrap import postgres_runtime
from agent_trading.services.decision_orchestrator import SubmitResult
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


def _handle_signal(signum: int, _frame: object) -> None:
    """Set shutdown event on SIGTERM/SIGINT."""
    sig_name = signal.Signals(signum).name
    logger.info("Received %s — completing current cycle then exiting ...", sig_name)
    _shutdown_event.set()


def _install_signal_handlers() -> None:
    """Install signal handlers for graceful shutdown."""
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _handle_signal(s, None))
        except NotImplementedError:
            signal.signal(sig, _handle_signal)


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

            # Create KIS client if available (P2 market overlay)
            kis_client: KISRestClient | None = None
            if _HAS_KIS:
                try:
                    from agent_trading.config.settings import AppSettings

                    settings = AppSettings()
                    kis_client = KISRestClient(settings=settings)
                except Exception:
                    logger.debug(
                        "KIS client init failed — market overlay disabled.",
                        exc_info=True,
                    )

            selector = UniverseSelectionService(
                repos,
                kis_client=kis_client,
            )

            # Resolve account ID for held-position lookup
            account_id: UUID = FALLBACK_ACCOUNT_ID
            try:
                account = await repos.accounts.find_one(
                    AccountLookup(alias=ACCOUNT_ALIAS)
                )
                if account is not None:
                    account_id = account.account_id
            except Exception:
                logger.debug("Account lookup failed — using fallback account ID.")

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
                logger.info(
                    "Trading universe from UniverseSelectionService: "
                    "%d symbols loaded (cap=%d).",
                    len(universe),
                    ctx.max_cap,
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
    """
    now = datetime.now(timezone.utc)
    started_at = now.isoformat()
    completed_at = now.isoformat()

    data: dict[str, object] = {
        "cycle": cycle,
        "symbol": symbol,
        "market": market,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_seconds": round(duration, 3),
    }

    if precheck is not None:
        data["precheck"] = precheck

    if error:
        data["status"] = "ERROR"
        data["error"] = error
    elif dry_run:
        # Dry-run mode: assemble + sizing, no broker submit
        data["status"] = "DRY_RUN"
        if result is not None and result.intent is not None:
            data["decision_context_id"] = (
                str(result.decision_context_id) if result.decision_context_id else None
            )
            data["trade_decision_id"] = (
                str(result.trade_decision_id) if result.trade_decision_id else None
            )
            data["order_intent_id"] = str(result.intent.order_intent_id)
            data["decision_type"] = result.intent.ai_backend_inputs.decision_type
            data["sized_quantity"] = str(result.intent.request.quantity)
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
        if result.intent is not None:
            data["order_intent_id"] = str(result.intent.order_intent_id)
            data["decision_type"] = result.intent.ai_backend_inputs.decision_type
            data["sized_quantity"] = str(result.intent.request.quantity)
        if result.order is not None:
            data["order_request_id"] = str(result.order.order_request_id)
            data["order_status"] = result.order.status.value
            data["client_order_id"] = result.order.client_order_id
            data["requested_quantity"] = str(result.order.requested_quantity)
    else:
        data["status"] = "UNKNOWN"

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


async def _run_one_cycle(
    cycle: int,
    *,
    submit: bool,
    dry_run: bool,
    output: str,
    symbol: str = SYMBOL,
    market: str = MARKET,
) -> dict[str, object]:
    """Execute a single decision cycle.

    Returns a serialized result dict.
    """
    start = time.monotonic()
    precheck: dict[str, object] | None = None

    try:
        async with postgres_runtime(run_migrations=False) as runtime:
            repos: RepositoryContainer = runtime["repositories"]
            orchestrator = runtime["orchestrator"]

            # ── 1. Seed FK chain if empty ───────────────────────────────
            seeded = await _seed_if_empty(repos)
            if seeded:
                logger.info("Cycle %d: seed completed.", cycle)
            else:
                logger.debug("Cycle %d: seed already exists (skipped).", cycle)

            # ── 2. Pre-check snapshot health ────────────────────────────
            precheck = await _run_precheck(repos)

            # ── 3. Build request ────────────────────────────────────────
            resolved_price = _resolve_smoke_price()
            request = SubmitOrderRequest(
                account_ref=ACCOUNT_ALIAS,
                client_order_id=f"paper-loop-{symbol}-{cycle}-{int(start)}",
                correlation_id=f"paper-loop-{symbol}-{cycle}-{int(start)}",
                strategy_id=str(STRATEGY_ID),
                symbol=symbol,
                market=market,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("10"),
                price=resolved_price,
            )

            # ── 4. Execute cycle ────────────────────────────────────────
            if dry_run:
                # Dry-run: assemble + sizing only
                intent = await orchestrator.assemble(request)
                sizing_inputs = orchestrator._build_sizing_inputs(intent)
                sizing_result = calculate_sizing(sizing_inputs)

                # Build synthetic SubmitResult for consistent serialization
                result = SubmitResult(
                    status="DRY_RUN",
                    intent=intent,
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
                order_manager = runtime["order_manager"]
                broker = runtime["primary_broker_adapter"]
                result = await orchestrator.assemble_and_submit(
                    request,
                    order_manager=order_manager,
                    broker=broker,
                )
            else:
                # Should not happen (CLI defaults ensure submit=True or dry_run)
                result = SubmitResult(
                    status="ERROR",
                    error_phase="config",
                    error_message="Neither --submit nor --dry-run was set.",
                )

            duration = time.monotonic() - start
            return _serialize_cycle_result(
                cycle,
                result,
                duration,
                symbol=symbol,
                market=market,
                precheck=precheck,
                dry_run=dry_run,
            )

    except Exception as exc:
        duration = time.monotonic() - start
        logger.exception("Cycle %d failed: %s", cycle, exc)
        return _serialize_cycle_result(
            cycle,
            None,
            duration,
            symbol=symbol,
            market=market,
            precheck=precheck,
            dry_run=dry_run,
            error=str(exc),
        )


# ── Main loop ───────────────────────────────────────────────────────────────


async def _run_loop(
    *,
    interval: int,
    max_cycles: int,
    submit: bool,
    dry_run: bool,
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

    while not _shutdown_event.is_set():
        # Check cycle limit
        if max_cycles > 0 and cycle_count >= max_cycles:
            logger.info("Reached requested cycle count (%d).", max_cycles)
            break

        cycle_count += 1
        logger.info("=== Decision Cycle %d ===", cycle_count)

        submit_budget_consumed = False
        for item in universe:
            # In submit mode, evaluate all symbols but allow at most one
            # budget-consuming broker submit per script invocation.
            symbol_submit = submit and not dry_run and not submit_budget_consumed
            symbol_dry_run = dry_run or (submit and submit_budget_consumed)

            result = await _run_one_cycle(
                cycle=cycle_count,
                submit=symbol_submit,
                dry_run=symbol_dry_run,
                output=output,
                symbol=item.symbol,
                market=item.market,
            )
            results.append(result)

            status = result.get("status", "UNKNOWN")
            if status in ("SUBMITTED", "DRY_RUN", "SKIPPED"):
                total_success += 1
            else:
                total_fail += 1

            if status in ("SUBMITTED", "RECONCILE_REQUIRED"):
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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the continuous decision loop.

    .. note::
       This script is named ``run_paper_decision_loop`` for historical
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
