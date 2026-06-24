from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from agent_trading.domain.entities import DecisionContextEntity
from agent_trading.domain.enums import OrderSide, OrderType, TimeInForce
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.services.ai_agents.schemas import FinalDecisionComposerOutput
from agent_trading.services.common_types import (
    AIDecisionInputs,
    AgentExecutionBundle,
    AssembledContext,
)
from agent_trading.services.decision_factory import build_trade_decision_entity
from agent_trading.services.deterministic_trigger_engine import (
    DeterministicTriggerAssessment,
)


def _make_request() -> SubmitOrderRequest:
    return SubmitOrderRequest(
        account_ref="test_account",
        client_order_id="test-001",
        correlation_id="corr-001",
        strategy_id=str(uuid4()),
        symbol="005930",
        market="KRX",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        price=Decimal("50000"),
        time_in_force=TimeInForce.DAY,
    )


def _make_request_with_universe_anchor() -> SubmitOrderRequest:
    return SubmitOrderRequest(
        account_ref="test_account",
        client_order_id="test-001",
        correlation_id="corr-001",
        strategy_id=str(uuid4()),
        symbol="005930",
        market="KRX",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        price=Decimal("50000"),
        time_in_force=TimeInForce.DAY,
        metadata={
            "universe_anchor": {
                "source": "intraday_freeze",
                "universe_freeze_run_id": str(uuid4()),
                "freeze_purpose": "decision_loop_intraday",
                "freeze_reused": True,
                "business_date": "2026-06-24",
            }
        },
    )


def _make_context(trigger: DeterministicTriggerAssessment) -> AssembledContext:
    return AssembledContext(
        decision_context=DecisionContextEntity(
            decision_context_id=uuid4(),
            account_id=uuid4(),
            strategy_id=uuid4(),
            config_version_id=uuid4(),
            market_timestamp=datetime.now(timezone.utc),
            correlation_id="corr-001",
        ),
        deterministic_trigger=trigger,
        source_type="core",
    )


def test_build_trade_decision_entity_stores_candidate_vs_final_matched() -> None:
    trigger = DeterministicTriggerAssessment(
        trigger_version="deterministic_trigger_v1",
        primary_candidate="BUY_CANDIDATE",
        candidate_set=("BUY_CANDIDATE",),
        watch_candidate=False,
        buy_candidate=True,
        sell_candidate=False,
        reduce_candidate=False,
        candidate_confidence=0.82,
        entry_score=0.82,
        exit_score=0.14,
        watch_score=0.2,
        reason_codes=("trigger_buy_candidate",),
        thresholds={"buy_candidate_threshold": 0.65},
        metadata={},
    )
    entity = build_trade_decision_entity(
        decision_context_id=uuid4(),
        request=_make_request(),
        assembled_context=_make_context(trigger),
        agent_bundle=AgentExecutionBundle(
            composer_output=FinalDecisionComposerOutput(
                decision_type="BUY",
                side="BUY",
                confidence=0.9,
            ),
        ),
    )

    assert entity is not None
    assert entity.decision_json["candidate_vs_final"]["candidate_intent"] == "buy"
    assert entity.decision_json["candidate_vs_final"]["final_intent"] == "buy"
    assert entity.decision_json["candidate_vs_final"]["alignment_status"] == "matched"
    assert entity.decision_json["candidate_vs_final"]["override_applied"] is False
    assert entity.decision_json["deterministic_trigger"]["eligibility_passed"] is False
    assert entity.decision_json["deterministic_trigger"]["candidate_mode"] == "absolute_threshold_v1"
    assert entity.decision_json["deterministic_trigger"]["ranking_percentile"] is None


def test_build_trade_decision_entity_sets_instrument_id_when_provided() -> None:
    trigger = DeterministicTriggerAssessment(
        trigger_version="deterministic_trigger_v1",
        primary_candidate="BUY_CANDIDATE",
        candidate_set=("BUY_CANDIDATE",),
        watch_candidate=False,
        buy_candidate=True,
        sell_candidate=False,
        reduce_candidate=False,
        candidate_confidence=0.82,
        entry_score=0.82,
        exit_score=0.14,
        watch_score=0.2,
        reason_codes=("trigger_buy_candidate",),
        thresholds={"buy_candidate_threshold": 0.65},
        metadata={},
    )
    instrument_id = uuid4()
    entity = build_trade_decision_entity(
        decision_context_id=uuid4(),
        request=_make_request(),
        assembled_context=_make_context(trigger),
        agent_bundle=AgentExecutionBundle(
            composer_output=FinalDecisionComposerOutput(
                decision_type="BUY",
                side="BUY",
                confidence=0.9,
            ),
        ),
        instrument_id=instrument_id,
    )

    assert entity is not None
    assert entity.instrument_id == instrument_id


def test_build_trade_decision_entity_stores_universe_anchor() -> None:
    trigger = DeterministicTriggerAssessment(
        trigger_version="deterministic_trigger_v1",
        primary_candidate="BUY_CANDIDATE",
        candidate_set=("BUY_CANDIDATE",),
        watch_candidate=False,
        buy_candidate=True,
        sell_candidate=False,
        reduce_candidate=False,
        candidate_confidence=0.82,
        entry_score=0.82,
        exit_score=0.14,
        watch_score=0.2,
        reason_codes=("trigger_buy_candidate",),
        thresholds={"buy_candidate_threshold": 0.65},
        metadata={},
    )
    request = _make_request_with_universe_anchor()
    entity = build_trade_decision_entity(
        decision_context_id=uuid4(),
        request=request,
        assembled_context=_make_context(trigger),
        agent_bundle=AgentExecutionBundle(
            composer_output=FinalDecisionComposerOutput(
                decision_type="BUY",
                side="BUY",
                confidence=0.9,
            ),
        ),
    )

    assert entity is not None
    assert entity.decision_json["universe_anchor"] == request.metadata["universe_anchor"]


def test_build_trade_decision_entity_stores_candidate_vs_final_downgraded() -> None:
    trigger = DeterministicTriggerAssessment(
        trigger_version="deterministic_trigger_v1",
        primary_candidate="SELL_CANDIDATE",
        candidate_set=("SELL_CANDIDATE", "REDUCE_CANDIDATE"),
        watch_candidate=False,
        buy_candidate=False,
        sell_candidate=True,
        reduce_candidate=True,
        candidate_confidence=0.88,
        entry_score=0.1,
        exit_score=0.88,
        watch_score=0.3,
        reason_codes=("trigger_sell_candidate",),
        thresholds={"sell_candidate_threshold": 0.75},
        metadata={},
    )
    entity = build_trade_decision_entity(
        decision_context_id=uuid4(),
        request=_make_request(),
        assembled_context=_make_context(trigger),
        agent_bundle=AgentExecutionBundle(
            composer_output=FinalDecisionComposerOutput(
                decision_type="HOLD",
                side="BUY",
                confidence=0.4,
            ),
        ),
    )

    assert entity is not None
    assert entity.decision_json["candidate_vs_final"]["candidate_intent"] == "sell"
    assert entity.decision_json["candidate_vs_final"]["final_intent"] == "no_action"
    assert entity.decision_json["candidate_vs_final"]["alignment_status"] == "downgraded"
    assert entity.decision_json["candidate_vs_final"]["override_applied"] is True
    assert entity.decision_json["deterministic_trigger"]["eligibility_reasons"] == []


def test_build_trade_decision_entity_stores_ai_call_path_skip_metadata() -> None:
    trigger = DeterministicTriggerAssessment(
        trigger_version="deterministic_trigger_v1",
        primary_candidate="WATCH",
        candidate_set=("WATCH",),
        watch_candidate=True,
        buy_candidate=False,
        sell_candidate=False,
        reduce_candidate=False,
        candidate_confidence=0.55,
        entry_score=0.55,
        exit_score=0.10,
        watch_score=0.55,
        reason_codes=("trigger_watch_candidate",),
        thresholds={"watch_candidate_threshold": 0.45},
        metadata={"source_type": "core"},
    )
    assembled = AssembledContext(
        decision_context=DecisionContextEntity(
            decision_context_id=uuid4(),
            account_id=uuid4(),
            strategy_id=uuid4(),
            config_version_id=uuid4(),
            market_timestamp=datetime.now(timezone.utc),
            correlation_id="corr-ai-call-path",
        ),
        deterministic_trigger=trigger,
        source_type="core",
    )
    bundle = AgentExecutionBundle(
        ai_inputs=AIDecisionInputs(
            decision_type="WATCH",
            reason_codes=("pre_ai_risk_short_circuit",),
            ei_skipped=True,
            fdc_skipped=True,
            skip_reason_codes=("skip_ei_no_recent_events", "skip_fdc_high_risk"),
        ),
        composer_output=FinalDecisionComposerOutput(
            decision_type="WATCH",
            summary="한국어 요약",
        ),
    )
    entity = build_trade_decision_entity(
        decision_context_id=assembled.decision_context.decision_context_id,
        request=SubmitOrderRequest(
            account_ref="test-account",
            client_order_id="cid",
            correlation_id="corr",
            strategy_id="strat",
            symbol="005930",
            market="KRX",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1"),
            price=Decimal("50000"),
            time_in_force=TimeInForce.DAY,
        ),
        assembled_context=assembled,
        agent_bundle=bundle,
    )

    assert entity is not None
    ai_call_path = entity.decision_json["ai_call_path"]
    assert ai_call_path["ei_skipped"] is True
    assert ai_call_path["ar_skipped"] is False
    assert ai_call_path["fdc_skipped"] is True
    assert ai_call_path["skip_reason_codes"] == [
        "skip_ei_no_recent_events",
        "skip_fdc_high_risk",
    ]


def test_build_trade_decision_entity_stores_expected_value_gate_fields() -> None:
    trigger = DeterministicTriggerAssessment(
        trigger_version="deterministic_trigger_v1",
        primary_candidate="BUY_CANDIDATE",
        candidate_set=("BUY_CANDIDATE",),
        watch_candidate=False,
        buy_candidate=True,
        sell_candidate=False,
        reduce_candidate=False,
        candidate_confidence=0.82,
        entry_score=0.82,
        exit_score=0.14,
        watch_score=0.2,
    )
    entity = build_trade_decision_entity(
        decision_context_id=uuid4(),
        request=_make_request(),
        assembled_context=_make_context(trigger),
        agent_bundle=AgentExecutionBundle(
            ai_inputs=AIDecisionInputs(
                decision_type="BUY",
                expected_return_bps=Decimal("80.00"),
                expected_downside_bps=Decimal("20.00"),
                net_expected_value_bps=Decimal("60.00"),
                final_trade_score=Decimal("0.85"),
                minimum_required_edge_bps=Decimal("10.00"),
                edge_after_cost_bps=Decimal("39.00"),
                estimated_round_trip_cost_bps=Decimal("11.00"),
                slippage_buffer_bps=Decimal("10.00"),
                expected_value_gate_passed=True,
                expected_value_gate_reason_codes=(
                    "expected_value_anchor_present",
                    "expected_value_edge_meets_minimum_required",
                ),
            ),
            composer_output=FinalDecisionComposerOutput(
                decision_type="BUY",
                side="BUY",
                confidence=0.9,
            ),
        ),
    )

    assert entity is not None
    assert entity.expected_return_bps == Decimal("80.00")
    assert entity.net_expected_value_bps == Decimal("60.00")
    assert entity.final_trade_score == Decimal("0.85")
    assert entity.minimum_required_edge_bps == Decimal("10.00")
    assert entity.decision_json["expected_value_gate"]["passed"] is True
    assert entity.decision_json["expected_value_gate"]["edge_after_cost_bps"] == "39.00"
    assert (
        entity.decision_json["expected_value_gate"]["estimated_round_trip_cost_bps"]
        == "11.00"
    )
    assert entity.decision_json["expected_value_gate"]["slippage_buffer_bps"] == "10.00"


def test_build_trade_decision_entity_stores_holding_profile_policy() -> None:
    trigger = DeterministicTriggerAssessment(
        trigger_version="deterministic_trigger_v1",
        primary_candidate="BUY_CANDIDATE",
        candidate_set=("BUY_CANDIDATE",),
        watch_candidate=False,
        buy_candidate=True,
        sell_candidate=False,
        reduce_candidate=False,
        candidate_confidence=0.82,
        entry_score=0.82,
        exit_score=0.14,
        watch_score=0.2,
    )
    assembled = _make_context(trigger)
    entity = build_trade_decision_entity(
        decision_context_id=uuid4(),
        request=_make_request(),
        assembled_context=assembled,
        agent_bundle=AgentExecutionBundle(
            ai_inputs=AIDecisionInputs(
                decision_type="BUY",
                expected_return_bps=Decimal("70.00"),
                expected_downside_bps=Decimal("20.00"),
                net_expected_value_bps=Decimal("50.00"),
                final_trade_score=Decimal("0.80"),
                minimum_required_edge_bps=Decimal("10.00"),
                edge_after_cost_bps=Decimal("30.00"),
                estimated_round_trip_cost_bps=Decimal("10.00"),
                slippage_buffer_bps=Decimal("10.00"),
                expected_value_gate_passed=True,
            ),
            composer_output=FinalDecisionComposerOutput(
                decision_type="BUY",
                side="BUY",
                confidence=0.9,
                time_horizon="swing",
            ),
        ),
    )

    assert entity is not None
    holding_profile_policy = entity.decision_json["holding_profile_policy"]
    assert holding_profile_policy["holding_profile"] == "core_swing"
    assert holding_profile_policy["minimum_hold_until"] is not None
    assert holding_profile_policy["metadata"]["source_type"] == "core"
