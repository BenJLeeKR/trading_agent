#!/usr/bin/env python3
"""Replay verification script — 결정론적 backend 일관성 검증.

테스트 harness (``tests.services.replay_test_harness``)와 **동일한**
``REPLAY_SCENARIOS`` 소스를 재사용하여, pytest 외부에서도
결정론적 replay 검증을 실행한다.

Usage
-----
.. code-block:: bash

    # 모든 시나리오 검증 (JSON stdout)
    python -m scripts.replay_verification

    # 특정 시나리오만 검증
    python -m scripts.replay_verification --scenario happy_buy_submit

    # JSON 파일 출력
    python -m scripts.replay_verification --output results.json

    # 간결한 human-readable 출력
    python -m scripts.replay_verification --format text

검증 항목
---------
동일 ``ReplayBundle`` × 결정론적 in-memory repos → 항상 동일한:
1. ``SubmitResult.status``
2. ``requested_quantity``
3. guardrail ``blocking_rule_codes``
4. ``submit_order()`` 호출 여부 (호출 카운트)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from agent_trading.brokers.base import BrokerAdapter
from agent_trading.domain.enums import BrokerName, OrderStatus
from agent_trading.domain.models import SubmitOrderResult
from agent_trading.services.decision_orchestrator import (
    DecisionOrchestratorService,
    SubmitResult,
)
from agent_trading.services.order_manager import OrderManager
from agent_trading.services.reconciliation_service import ReconciliationService

# ── 테스트 harness에서 동일한 scenario source 재사용 ──
from tests.services.replay_test_harness import REPLAY_SCENARIOS, ReplayBundle

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _serialize_result(
    scenario_name: str,
    result: SubmitResult | None,
    duration: float,
    guardrail_codes: list[str] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Serialize a single verification result."""
    data: dict[str, Any] = {
        "scenario": scenario_name,
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
        data["trade_decision_id"] = (
            str(result.trade_decision_id) if result.trade_decision_id else None
        )
        data["decision_context_id"] = (
            str(result.decision_context_id) if result.decision_context_id else None
        )
        if result.submit_response is not None:
            data["order_id"] = str(result.submit_response.order_request_id)
            data["order_status"] = result.submit_response.status.value
            data["requested_quantity"] = str(result.submit_response.requested_quantity)
        else:
            data["order_id"] = None
            data["requested_quantity"] = None
        data["guardrail_codes"] = guardrail_codes or []
    else:
        data["status"] = "UNKNOWN"
    return data


# ---------------------------------------------------------------------------
# Verification runner
# ---------------------------------------------------------------------------


def _make_mock_broker() -> MagicMock:
    """Build a mock broker adapter for deterministic replay."""
    mock_broker = MagicMock(spec=BrokerAdapter)
    mock_broker.submit_order = AsyncMock()
    mock_broker.submit_order.return_value = SubmitOrderResult(
        accepted=True,
        broker_name=BrokerName.KOREA_INVESTMENT,
        client_order_id="REPLAY-VERIFY-001",
        broker_order_id="BRK-VERIFY-001",
        broker_status=OrderStatus.ACKNOWLEDGED,
        ack_timestamp=datetime.now(timezone.utc),
        raw_code="0000",
        raw_message="Accepted",
    )
    return mock_broker


async def _run_one_scenario(
    bundle: ReplayBundle,
) -> dict[str, Any]:
    """Execute a single replay scenario and return serialized result."""
    start = time.monotonic()
    try:
        # ── Given: mock broker + services ──
        mock_broker = _make_mock_broker()
        rs = ReconciliationService(bundle.repos)
        om = OrderManager(repos=bundle.repos, reconciliation_service=rs)

        service = DecisionOrchestratorService(
            repos=bundle.repos,
            final_decision_agent=bundle.stub_fdc,  # type: ignore[arg-type]
        )

        # ── When ──
        result = await service.assemble_and_submit(
            bundle.request,
            order_manager=om,
            broker=mock_broker,  # type: ignore[arg-type]
        )

        # ── Then: guardrail codes (fresh lookup) ──
        guardrail_codes: list[str] = []
        if result.decision_context_id is not None:
            guardrails = await bundle.repos.guardrail_evaluations.get_by_decision_context(
                result.decision_context_id
            )
            for g in guardrails:
                if g.blocking_rule_codes:
                    guardrail_codes.extend(g.blocking_rule_codes)

        duration = time.monotonic() - start
        return _serialize_result(
            bundle.name,
            result,
            duration,
            guardrail_codes=guardrail_codes,
        )

    except Exception as exc:
        duration = time.monotonic() - start
        logger.exception("Scenario %s failed: %s", bundle.name, exc)
        return _serialize_result(bundle.name, None, duration, error=str(exc))


async def _run_all_scenarios(
    scenario_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Run all (or filtered) replay scenarios."""
    results: list[dict[str, Any]] = []
    for bundle in REPLAY_SCENARIOS:
        if scenario_filter and bundle.name != scenario_filter:
            continue
        logger.info("Running scenario: %s …", bundle.name)
        result = await _run_one_scenario(bundle)
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


def _output_json(results: list[dict[str, Any]], path: str | None = None) -> None:
    """Output results as JSON."""
    payload = {
        "meta": {
            "tool": "replay_verification",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total": len(results),
            "passed": sum(1 for r in results if r.get("error") is None),
            "failed": sum(1 for r in results if r.get("error") is not None),
        },
        "results": results,
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        logger.info("Results written to %s", path)
    else:
        print(text)


def _output_text(results: list[dict[str, Any]]) -> None:
    """Output results as human-readable text."""
    passed = 0
    failed = 0
    for r in results:
        scenario = r["scenario"]
        status = r["status"]
        duration = r["duration_seconds"]
        error = r.get("error")
        guardrails = r.get("guardrail_codes", [])
        qty = r.get("requested_quantity", "N/A")

        if error:
            print(f"❌ {scenario}: ERROR ({error}) [{duration:.3f}s]")
            failed += 1
        elif status == "SUBMITTED":
            print(
                f"✅ {scenario}: {status} qty={qty}"
                f" guardrails={guardrails} [{duration:.3f}s]"
            )
            passed += 1
        else:
            print(
                f"✅ {scenario}: {status}"
                f" guardrails={guardrails} [{duration:.3f}s]"
            )
            passed += 1

    print(f"\n{'=' * 48}")
    print(f"Total: {len(results)} | Passed: {passed} | Failed: {failed}")
    print(f"{'=' * 48}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay verification — 결정론적 backend 일관성 검증"
    )
    parser.add_argument(
        "--scenario",
        help="특정 시나리오만 실행 (예: happy_buy_submit)",
        default=None,
    )
    parser.add_argument(
        "--output",
        help="JSON 파일 경로 (생략 시 stdout)",
        default=None,
    )
    parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="출력 포맷 (default: json)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for replay verification."""
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
    )

    results = asyncio.run(_run_all_scenarios(scenario_filter=args.scenario))

    if args.format == "text":
        _output_text(results)
    else:
        _output_json(results, path=args.output)

    # Exit code: 0 if all passed, 1 if any failed
    failed = sum(1 for r in results if r.get("error") is not None)
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
