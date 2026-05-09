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
    python -m scripts.run_paper_decision_loop

    # 1회 실행 후 종료
    python -m scripts.run_paper_decision_loop --count 1

    # Dry-run (assemble + sizing only, submit 없음)
    python -m scripts.run_paper_decision_loop --count 1 --dry-run

    # 60초 간격, 5회, JSON 출력
    python -m scripts.run_paper_decision_loop --interval 60 --count 5 --output json

    # 명시적 submit 모드 (기본값)
    python -m scripts.run_paper_decision_loop --submit --count 1

환경 변수
---------
* ``PAPER_DECISION_LOOP_INTERVAL_SECONDS`` — 기본 interval (기본 300)
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
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, NoReturn

from agent_trading.domain.enums import OrderSide, OrderType
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.contracts import SnapshotSyncHealthSummary
from agent_trading.runtime.bootstrap import postgres_runtime
from agent_trading.services.decision_orchestrator import SubmitResult
from agent_trading.services.sizing_engine import calculate_sizing

# ── Seed constants (reused from run_orchestrator_once.py) ───────────────────
from scripts.run_orchestrator_once import (
    ACCOUNT_ALIAS,
    CLIENT_ID,
    STRATEGY_ID,
    SYMBOL,
    MARKET,
    _seed_if_empty,
)

logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────────────────────

DEFAULT_INTERVAL_SECONDS = 300
ENV_INTERVAL = "PAPER_DECISION_LOOP_INTERVAL_SECONDS"

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
            request = SubmitOrderRequest(
                account_ref=ACCOUNT_ALIAS,
                client_order_id=f"paper-loop-{cycle}-{int(start)}",
                correlation_id=f"paper-loop-{cycle}-{int(start)}",
                strategy_id=str(STRATEGY_ID),
                symbol=SYMBOL,
                market=MARKET,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("10"),
                price=Decimal("50000"),
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

        # Run decision cycle
        result = await _run_one_cycle(
            cycle=cycle_count,
            submit=submit,
            dry_run=dry_run,
            output=output,
        )
        results.append(result)

        status = result.get("status", "UNKNOWN")
        if status in ("SUBMITTED", "DRY_RUN", "SKIPPED"):
            total_success += 1
        else:
            total_fail += 1

        # Output per-cycle result
        if output == "json":
            print(json.dumps(result, ensure_ascii=False))
        else:
            precheck_str = ""
            precheck_data = result.get("precheck")
            if isinstance(precheck_data, dict):
                h = precheck_data.get("health_status", "?")
                precheck_str = f" [health={h}]"
            logger.info(
                "Cycle %d/%s complete — status=%s duration=%.2fs%s",
                cycle_count,
                "∞" if max_cycles == 0 else str(max_cycles),
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
    """Entry point for the paper continuous decision loop."""
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
