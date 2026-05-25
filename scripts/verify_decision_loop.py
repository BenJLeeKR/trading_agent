#!/usr/bin/env python3
"""Decision loop verification script — 반복 실행 전용.

``run_orchestrator_once.py``는 단발 실행을 유지하고,
이 스크립트가 **연속 실행(continuous loop)** 역할을 담당한다.

Usage
-----
.. code-block:: bash

    # Basic verification (assemble only, 1회)
    python -m scripts.verify_decision_loop

    # Full pipeline verification (assemble → sizing → submit, 1회)
    python -m scripts.verify_decision_loop --submit

    # Continuous verification (60초 간격, 5회)
    python -m scripts.verify_decision_loop --interval 60 --count 5

    # 무한 반복 (Ctrl+C로 중단)
    python -m scripts.verify_decision_loop --interval 300

    # JSON output for automated analysis
    python -m scripts.verify_decision_loop --submit --output json --count 1

검증 항목
---------
1. DB 연결 및 seed 데이터 존재 확인
2. ``assemble()`` 정상 실행 (3-agent chain)
3. sizing engine 정상 작동
4. (선택) ``assemble_and_submit()`` 정상 실행
5. 결과 요약 출력
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
from typing import NoReturn
from uuid import UUID

from agent_trading.domain.enums import OrderSide, OrderType
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.runtime.bootstrap import postgres_runtime
from agent_trading.services.common_types import SubmitResult
from agent_trading.services.sizing_engine import calculate_sizing

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (mirrored from run_orchestrator_once.py for seed compatibility)
# ---------------------------------------------------------------------------
STRATEGY_ID = UUID("30a1d26b-8230-51fc-8548-30920effff0c")
ACCOUNT_ALIAS = "Entrypoint Paper"
SYMBOL = "005930"
MARKET = "KRX"

# ---------------------------------------------------------------------------
# Signal handling for graceful shutdown
# ---------------------------------------------------------------------------

_shutdown_requested = False


def _handle_signal(signum: int, _frame: object) -> None:
    """Set shutdown flag on SIGINT / SIGTERM."""
    global _shutdown_requested
    _shutdown_requested = True
    logger.info("Shutdown signal received (%s). Finishing current cycle …", signum)


def _install_signal_handlers() -> None:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)


# ---------------------------------------------------------------------------
# Result serialization
# ---------------------------------------------------------------------------


def _serialize_cycle_result(
    cycle: int,
    result: SubmitResult | None,
    duration: float,
    error: str | None = None,
) -> dict[str, object]:
    """Serialize a single verification cycle result."""
    data: dict[str, object] = {
        "cycle": cycle,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(duration, 3),
    }
    if error:
        data["status"] = "ERROR"
        data["error"] = error
    elif result is not None:
        data["status"] = result.status
        data["error_phase"] = result.error_phase
        data["error_message"] = result.error_message
        data["trade_decision_id"] = str(result.trade_decision_id) if result.trade_decision_id else None
        data["decision_context_id"] = str(result.decision_context_id) if result.decision_context_id else None
        if result.order_intent is not None:
            data["order_intent_id"] = str(result.order_intent.order_intent_id)
            data["decision_type"] = result.order_intent.ai_backend_inputs.decision_type
            data["sized_quantity"] = str(result.order_intent.request.quantity)
            data["sizing_constraints"] = result.order_intent.reason_codes
        if result.submit_response is not None:
            data["order_id"] = str(result.submit_response.order_request_id)
            data["order_status"] = result.submit_response.status.value
            data["client_order_id"] = result.submit_response.client_order_id
            data["requested_quantity"] = str(result.submit_response.requested_quantity)
    else:
        data["status"] = "UNKNOWN"
    return data


# ---------------------------------------------------------------------------
# Verification cycle
# ---------------------------------------------------------------------------


async def _run_one_cycle(
    cycle: int,
    *,
    submit: bool,
    output: str,
) -> dict[str, object]:
    """Execute a single verification cycle.

    Returns a serialized result dict.
    """
    start = time.monotonic()
    try:
        async with postgres_runtime() as runtime:
            repos: RepositoryContainer = runtime["repositories"]
            orchestrator = runtime["orchestrator"]

            request = SubmitOrderRequest(
                account_ref=ACCOUNT_ALIAS,
                client_order_id=f"verify-{cycle}-{int(start)}",
                correlation_id=f"verify-{cycle}-{int(start)}",
                strategy_id=str(STRATEGY_ID),
                symbol=SYMBOL,
                market=MARKET,
                side=OrderSide.BUY,
                # 전면 MARKET 정책 — price=None으로 시장가 주문
                order_type=OrderType.MARKET,
                quantity=Decimal("10"),
                price=None,
            )

            if submit:
                order_manager = runtime["order_manager"]
                broker = runtime["primary_broker_adapter"]
                result = await orchestrator.assemble_and_submit(
                    request,
                    order_manager=order_manager,
                    broker=broker,
                )
            else:
                # assemble only + sizing
                intent = await orchestrator.assemble(request)
                sizing_inputs = orchestrator.build_sizing_inputs(intent)
                sizing_result = calculate_sizing(sizing_inputs)

                # Build a synthetic SubmitResult for consistent serialization
                from agent_trading.services.common_types import SubmitResult
                result = SubmitResult(
                    status="ASSEMBLED",
                    order_intent=intent,
                    trade_decision_id=None,
                    decision_context_id=intent.decision_context_id,
                )

                # Attach sizing info to the intent's reason_codes for display
                if sizing_result.applied_constraints:
                    logger.info(
                        "Cycle %d: sizing constraints=%s quantity=%s",
                        cycle,
                        sizing_result.applied_constraints,
                        sizing_result.quantity,
                    )

            duration = time.monotonic() - start
            return _serialize_cycle_result(cycle, result, duration)

    except Exception as exc:
        duration = time.monotonic() - start
        logger.exception("Cycle %d failed: %s", cycle, exc)
        return _serialize_cycle_result(cycle, None, duration, error=str(exc))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> int:
    """Run paper loop verification and return an exit code."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Paper loop verification — run one or more cycles of "
                    "orchestrator assemble/submit to validate the paper trading loop.",
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        default=False,
        help="Run full assemble → submit pipeline (default: assemble only)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=0,
        help="Seconds between verification cycles (0 = run once and exit)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of verification cycles to run (default: 1, 0 = infinite)",
    )
    parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format: ``text`` (human-readable) or ``json`` (machine-readable)",
    )
    args = parser.parse_args()

    _install_signal_handlers()

    cycle_count = 0
    max_cycles = args.count
    total_success = 0
    total_fail = 0
    results: list[dict[str, object]] = []

    logger.info(
        "Paper loop verification — interval=%ds count=%s submit=%s",
        args.interval,
        "infinite" if args.count == 0 else str(args.count),
        args.submit,
    )

    while True:
        # Check shutdown signal
        if _shutdown_requested:
            logger.info("Shutdown requested — stopping verification loop.")
            break

        # Check cycle limit
        if max_cycles > 0 and cycle_count >= max_cycles:
            logger.info("Reached requested cycle count (%d).", max_cycles)
            break

        cycle_count += 1

        # Run verification cycle
        result = await _run_one_cycle(
            cycle=cycle_count,
            submit=args.submit,
            output=args.output,
        )
        results.append(result)

        status = result.get("status", "UNKNOWN")
        if status in ("SUBMITTED", "ASSEMBLED", "SKIPPED"):
            total_success += 1
        else:
            total_fail += 1

        # Log summary
        if args.output == "text":
            logger.info(
                "Cycle %d/%s complete — status=%s duration=%.2fs",
                cycle_count,
                "∞" if max_cycles == 0 else str(max_cycles),
                status,
                result.get("duration_seconds", 0),
            )
        else:
            # JSON per-cycle output
            print(json.dumps(result, ensure_ascii=False))

        # Wait for next cycle (if interval > 0)
        if args.interval > 0 and not (max_cycles > 0 and cycle_count >= max_cycles):
            logger.debug("Waiting %d seconds before next cycle …", args.interval)
            try:
                await asyncio.sleep(args.interval)
            except asyncio.CancelledError:
                logger.info("Sleep cancelled — stopping.")
                break

    # ── Final summary ──
    if args.output == "json" and len(results) > 1:
        # Print aggregate summary as final JSON line
        summary: dict[str, object] = {
            "mode": "summary",
            "total_cycles": cycle_count,
            "success": total_success,
            "fail": total_fail,
            "success_rate": round(total_success / cycle_count * 100, 1) if cycle_count > 0 else 0,
        }
        print(json.dumps(summary, ensure_ascii=False))
    elif args.output == "text":
        logger.info("=" * 60)
        logger.info("Verification complete.")
        logger.info("  total cycles : %d", cycle_count)
        logger.info("  success      : %d", total_success)
        logger.info("  fail         : %d", total_fail)
        if cycle_count > 0:
            logger.info("  success rate : %.1f%%", total_success / cycle_count * 100)
        logger.info("=" * 60)

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
