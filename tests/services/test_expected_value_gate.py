from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from agent_trading.domain.entities import SignalFeatureSnapshotEntity
from agent_trading.services.common_types import AssembledContext
from agent_trading.services.deterministic_trigger_engine import (
    DeterministicTriggerAssessment,
)
from agent_trading.services.expected_value_gate import evaluate_expected_value_gate


def _make_context() -> AssembledContext:
    return AssembledContext(
        signal_feature_snapshot=SignalFeatureSnapshotEntity(
            signal_feature_snapshot_id=uuid4(),
            instrument_id=uuid4(),
            timeframe="1d",
            snapshot_at=datetime.now(timezone.utc),
            feature_set_version="signal_backbone_v1",
            bar_count=60,
            atr_14_pct=Decimal("2.50"),
            overall_score=Decimal("0.71"),
        ),
        deterministic_trigger=DeterministicTriggerAssessment(
            trigger_version="deterministic_trigger_v1",
            primary_candidate="BUY_CANDIDATE",
            candidate_set=("BUY_CANDIDATE",),
            watch_candidate=False,
            buy_candidate=True,
            sell_candidate=False,
            reduce_candidate=False,
            candidate_confidence=0.82,
            entry_score=0.76,
            exit_score=0.21,
            watch_score=0.33,
        ),
    )


def test_expected_value_gate_derives_anchor_for_actionable_buy() -> None:
    result = evaluate_expected_value_gate(
        decision_type="BUY",
        confidence=0.9,
        conviction=0.8,
        risk_score=0.3,
        context=_make_context(),
    )

    assert result.expected_value_gate_passed is True
    assert result.expected_return_bps is not None
    assert result.expected_downside_bps is not None
    assert result.net_expected_value_bps is not None
    assert result.final_trade_score is not None
    assert result.minimum_required_edge_bps == Decimal("10.00")
    assert result.edge_after_cost_bps is not None
    assert result.estimated_round_trip_cost_bps is not None
    assert result.slippage_buffer_bps is not None
    assert result.reason_codes == (
        "expected_value_anchor_present",
        "expected_value_edge_meets_minimum_required",
    )


def test_expected_value_gate_uses_ai_only_fallback_when_anchor_missing() -> None:
    result = evaluate_expected_value_gate(
        decision_type="SELL",
        confidence=0.7,
        conviction=0.6,
        risk_score=0.5,
        context=SimpleNamespace(
            signal_feature_snapshot=None,
            deterministic_trigger=None,
        ),
    )

    assert result.expected_value_gate_passed is True
    assert result.expected_return_bps is not None
    assert "expected_value_signal_feature_missing" in result.reason_codes
    assert "expected_value_trigger_missing" in result.reason_codes
    assert "expected_value_fallback_ai_only" in result.reason_codes
    assert "expected_value_edge_meets_minimum_required" in result.reason_codes


def test_expected_value_gate_blocks_when_after_cost_edge_is_too_low() -> None:
    result = evaluate_expected_value_gate(
        decision_type="BUY",
        confidence=0.3,
        conviction=0.2,
        risk_score=0.7,
        context=SimpleNamespace(
            signal_feature_snapshot=None,
            deterministic_trigger=None,
        ),
    )

    assert result.expected_value_gate_passed is False
    assert result.edge_after_cost_bps is not None
    assert result.minimum_required_edge_bps == Decimal("10.00")
    assert "expected_value_edge_below_minimum_required" in result.reason_codes
