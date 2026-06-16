from __future__ import annotations

from datetime import date
from uuid import uuid4

from agent_trading.services.universe_selection_types import MarketOverlayDiagnostics
from scripts.evaluate_market_overlay_runtime_validation import (
    MarketOverlayRecentSample,
    MarketOverlayRuntimeEvaluator,
    MarketOverlayRuntimeInputs,
    _build_persisted_summary,
)


def _make_inputs(
    *,
    account_present: bool = True,
    diagnostics: MarketOverlayDiagnostics | None = None,
    preview_market_overlay_count: int = 0,
    decision_count: int = 0,
    order_count: int = 0,
    decision_type_counts: dict[str, int] | None = None,
) -> MarketOverlayRuntimeInputs:
    return MarketOverlayRuntimeInputs(
        target_date=date(2026, 6, 14),
        account_id=uuid4() if account_present else None,
        account_label="paper-1" if account_present else None,
        kis_env="real",
        preview_total_count=10,
        preview_market_overlay_count=preview_market_overlay_count,
        preview_source_type_counts={"market_overlay": preview_market_overlay_count, "core": 7},
        diagnostics=diagnostics
        or MarketOverlayDiagnostics(
            enabled=True,
            quotes_requested_count=10,
            quotes_received_count=8,
            added_count=preview_market_overlay_count,
        ),
        decision_count=decision_count,
        order_count=order_count,
        decision_type_counts=decision_type_counts or {},
        order_status_counts={"submitted": order_count} if order_count > 0 else {},
        recent_samples=(
            MarketOverlayRecentSample(
                symbol="001740",
                decision_type="approve",
                side="buy",
                inclusion_reason="trade_strength",
                created_at=None,
                order_status="submitted" if order_count > 0 else None,
            ),
        ),
    )


def test_evaluator_blocks_when_preview_disabled() -> None:
    evaluation = MarketOverlayRuntimeEvaluator().evaluate(
        _make_inputs(
            diagnostics=MarketOverlayDiagnostics(
                enabled=False,
                skipped_reason="no_kis_client",
            ),
        )
    )

    assert evaluation.overall_status == "BLOCKED"
    assert evaluation.bottleneck_stage == "universe_selection"
    assert evaluation.checks[0].code == "MKT_OVR_PREVIEW"
    assert evaluation.checks[0].status == "BLOCKED"


def test_evaluator_warns_when_preview_active_but_no_decisions() -> None:
    evaluation = MarketOverlayRuntimeEvaluator().evaluate(
        _make_inputs(
            preview_market_overlay_count=2,
            decision_count=0,
            order_count=0,
        )
    )

    assert evaluation.overall_status == "WARN"
    assert evaluation.bottleneck_stage == "decision_loop"
    assert any(check.code == "MKT_OVR_DECISION" and check.status == "WARN" for check in evaluation.checks)


def test_evaluator_warns_for_hold_bias_without_orders() -> None:
    evaluation = MarketOverlayRuntimeEvaluator().evaluate(
        _make_inputs(
            preview_market_overlay_count=2,
            decision_count=3,
            order_count=0,
            decision_type_counts={"hold": 2, "watch": 1},
        )
    )

    assert evaluation.overall_status == "WARN"
    assert evaluation.bottleneck_stage == "order_conversion"
    conversion = next(check for check in evaluation.checks if check.code == "MKT_OVR_CONVERSION")
    assert conversion.status == "WARN"
    assert "HOLD/WATCH" in conversion.message


def test_evaluator_ready_when_preview_and_conversion_active() -> None:
    evaluation = MarketOverlayRuntimeEvaluator().evaluate(
        _make_inputs(
            preview_market_overlay_count=3,
            decision_count=5,
            order_count=2,
            decision_type_counts={"approve": 2, "hold": 3},
        )
    )

    assert evaluation.overall_status == "READY"
    assert evaluation.bottleneck_stage == "active"


def test_build_persisted_summary_contains_bottleneck_stage() -> None:
    evaluation = MarketOverlayRuntimeEvaluator().evaluate(
        _make_inputs(
            preview_market_overlay_count=3,
            decision_count=5,
            order_count=2,
            decision_type_counts={"approve": 2, "hold": 3},
        )
    )

    payload = _build_persisted_summary(evaluation)
    assert payload["overall_status"] == "READY"
    assert payload["bottleneck_stage"] == "active"
    assert payload["preview_market_overlay_count"] == 3
