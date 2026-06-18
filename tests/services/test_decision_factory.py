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
