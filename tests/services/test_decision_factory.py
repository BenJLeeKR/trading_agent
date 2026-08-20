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
from agent_trading.services.decision_factory import (
    _build_expected_value_gate_margin,
    build_trade_decision_entity,
)
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


def _make_request_with_expected_value_anchor() -> SubmitOrderRequest:
    return SubmitOrderRequest(
        account_ref="test_account",
        client_order_id="test-001",
        correlation_id="corr-001",
        strategy_id=str(uuid4()),
        symbol="005930",
        market="KRX",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        price=Decimal("50000"),
        time_in_force=TimeInForce.DAY,
        metadata={
            "expected_value_anchor": {
                "decision_type": "REDUCE",
                "anchor_required": True,
                "anchor_passed": True,
                "current_edge_after_cost_bps": "18.00",
                "last_exit_edge_after_cost_bps": "12.00",
                "edge_vs_last_exit_delta_bps": "6.00",
                "reentry_edge_improved_vs_last_exit": True,
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


def test_build_trade_decision_entity_uses_deterministic_fallback_when_summary_empty() -> None:
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
        metadata={},
    )
    entity = build_trade_decision_entity(
        decision_context_id=uuid4(),
        request=_make_request(),
        assembled_context=_make_context(trigger),
        agent_bundle=AgentExecutionBundle(
            composer_output=FinalDecisionComposerOutput(
                decision_type="HOLD",
                side="",
                confidence=0.4,
                summary="",
            ),
            ai_inputs=AIDecisionInputs(
                no_material_events=True,
                detected_event_count=0,
            ),
        ),
    )

    assert entity is not None
    assert entity.rationale_summary is not None
    assert entity.rationale_summary.startswith("[결정론적 코멘트]")
    assert "WATCH" in entity.rationale_summary
    assert "suppressed" in entity.rationale_summary
    assert "최신 관련 이벤트 없음" in entity.rationale_summary


def test_build_trade_decision_entity_keeps_ai_summary_when_present() -> None:
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
                summary="AI가 작성한 매수 근거 요약입니다.",
            ),
        ),
    )

    assert entity is not None
    assert entity.rationale_summary == "AI가 작성한 매수 근거 요약입니다."


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
    # Stage A-3(2026-08-20): gate margin(관측성 전용) — 판정(passed=True)
    # 자체는 margin 추가 전과 동일하게 유지되고, margin_value만 새로
    # 더해진다(39.00 - 10.00 = 29.00, 양수 = 여유 통과).
    gate_margin = entity.decision_json["expected_value_gate"]["gate_margin"]
    assert gate_margin == {
        "metric_name": "edge_after_cost_bps",
        "metric_value": "39.00",
        "threshold_name": "minimum_required_edge_bps",
        "threshold_value": "10.00",
        "margin_value": "29.00",
        "margin_unit": "bps",
    }


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


def test_build_trade_decision_entity_stores_expected_value_anchor_metadata() -> None:
    trigger = DeterministicTriggerAssessment(
        trigger_version="deterministic_trigger_v1",
        primary_candidate="REDUCE_CANDIDATE",
        candidate_set=("REDUCE_CANDIDATE",),
        watch_candidate=False,
        buy_candidate=False,
        sell_candidate=False,
        reduce_candidate=True,
        candidate_confidence=0.72,
        entry_score=0.21,
        exit_score=0.72,
        watch_score=0.18,
    )
    entity = build_trade_decision_entity(
        decision_context_id=uuid4(),
        request=_make_request_with_expected_value_anchor(),
        assembled_context=_make_context(trigger),
        agent_bundle=AgentExecutionBundle(
            ai_inputs=AIDecisionInputs(
                decision_type="REDUCE",
                expected_return_bps=Decimal("35.00"),
                expected_downside_bps=Decimal("15.00"),
                net_expected_value_bps=Decimal("20.00"),
                final_trade_score=Decimal("0.68"),
                minimum_required_edge_bps=Decimal("5.00"),
                edge_after_cost_bps=Decimal("18.00"),
                estimated_round_trip_cost_bps=Decimal("7.00"),
                slippage_buffer_bps=Decimal("8.00"),
                expected_value_gate_passed=True,
            ),
            composer_output=FinalDecisionComposerOutput(
                decision_type="REDUCE",
                side="SELL",
                confidence=0.8,
            ),
        ),
    )

    assert entity is not None
    assert entity.decision_json["expected_value_anchor"]["anchor_passed"] is True
    assert (
        entity.decision_json["expected_value_anchor"]["edge_vs_last_exit_delta_bps"]
        == "6.00"
    )


def test_build_trade_decision_entity_stores_policy_git_sha_when_provided() -> None:
    """Stage A(2026-08-20): policy_git_sha가 그대로 entity에 저장돼야
    한다(관측성 전용, 판정 로직 무관)."""
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
            composer_output=FinalDecisionComposerOutput(
                decision_type="BUY",
                side="BUY",
                confidence=0.9,
            ),
        ),
        policy_git_sha="abc1234def5678",
    )

    assert entity is not None
    assert entity.policy_git_sha == "abc1234def5678"


def test_build_trade_decision_entity_policy_git_sha_defaults_to_none() -> None:
    """policy_git_sha를 넘기지 않으면 기존과 동일하게 None이어야 한다
    (하위 호환)."""
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
            composer_output=FinalDecisionComposerOutput(
                decision_type="BUY",
                side="BUY",
                confidence=0.9,
            ),
        ),
    )

    assert entity is not None
    assert entity.policy_git_sha is None


# ============================================================================
# Stage A-3 (2026-08-20 KST) — expected value gate margin telemetry
# ============================================================================


class TestBuildExpectedValueGateMargin:
    """``_build_expected_value_gate_margin()`` — 순수 함수 단위 검증."""

    def test_pass_case_has_positive_margin(self) -> None:
        """실제값이 threshold보다 크면(=gate 통과) margin이 양수여야
        한다."""
        margin = _build_expected_value_gate_margin(
            edge_after_cost_bps=Decimal("10.07"),
            minimum_required_edge_bps=Decimal("10.00"),
        )
        assert margin == {
            "metric_name": "edge_after_cost_bps",
            "metric_value": "10.07",
            "threshold_name": "minimum_required_edge_bps",
            "threshold_value": "10.00",
            "margin_value": "0.07",
            "margin_unit": "bps",
        }

    def test_blocked_case_has_negative_margin(self) -> None:
        """실제값이 threshold에 못 미치면(=gate 차단) margin이 음수여야
        한다."""
        margin = _build_expected_value_gate_margin(
            edge_after_cost_bps=Decimal("7.50"),
            minimum_required_edge_bps=Decimal("10.00"),
        )
        assert margin is not None
        assert margin["margin_value"] == "-2.50"

    def test_returns_none_when_edge_after_cost_bps_missing(self) -> None:
        """non-actionable decision 등 값이 없는 경우 margin을 억지로
        만들지 않고 None을 반환해야 한다."""
        assert (
            _build_expected_value_gate_margin(
                edge_after_cost_bps=None,
                minimum_required_edge_bps=Decimal("10.00"),
            )
            is None
        )

    def test_returns_none_when_minimum_required_edge_bps_missing(self) -> None:
        assert (
            _build_expected_value_gate_margin(
                edge_after_cost_bps=Decimal("10.07"),
                minimum_required_edge_bps=None,
            )
            is None
        )

    def test_returns_none_when_both_missing(self) -> None:
        assert (
            _build_expected_value_gate_margin(
                edge_after_cost_bps=None,
                minimum_required_edge_bps=None,
            )
            is None
        )


class TestBuildTradeDecisionEntityGateMargin:
    """``build_trade_decision_entity()`` — gate margin 저장/직렬화 및
    판정 무변화 검증(end-to-end)."""

    @staticmethod
    def _trigger() -> DeterministicTriggerAssessment:
        return DeterministicTriggerAssessment(
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

    def test_blocked_case_stores_negative_margin_and_passed_false(self) -> None:
        """gate가 실제로 차단된 경우(``expected_value_gate_passed=
        False``)에도 margin이 저장되고, 그 부호(음수)가 차단 방향과
        일치해야 한다 — 판정(passed=False) 자체는 그대로 유지."""
        entity = build_trade_decision_entity(
            decision_context_id=uuid4(),
            request=_make_request(),
            assembled_context=_make_context(self._trigger()),
            agent_bundle=AgentExecutionBundle(
                ai_inputs=AIDecisionInputs(
                    decision_type="REDUCE",
                    minimum_required_edge_bps=Decimal("10.00"),
                    edge_after_cost_bps=Decimal("7.50"),
                    expected_value_gate_passed=False,
                    expected_value_gate_reason_codes=(
                        "expected_value_edge_below_minimum_required",
                    ),
                ),
                composer_output=FinalDecisionComposerOutput(
                    decision_type="REDUCE",
                    side="SELL",
                    confidence=0.8,
                ),
            ),
        )

        assert entity is not None
        assert entity.decision_json["expected_value_gate"]["passed"] is False
        gate_margin = entity.decision_json["expected_value_gate"]["gate_margin"]
        assert gate_margin["margin_value"] == "-2.50"
        assert gate_margin["margin_unit"] == "bps"

    def test_non_actionable_decision_has_no_gate_margin(self) -> None:
        """EV anchor 자체가 없는(비actionable) 결정은 gate_margin도
        None이어야 한다 — margin을 억지로 만들지 않는다."""
        entity = build_trade_decision_entity(
            decision_context_id=uuid4(),
            request=_make_request(),
            assembled_context=_make_context(self._trigger()),
            agent_bundle=AgentExecutionBundle(
                ai_inputs=AIDecisionInputs(decision_type="HOLD"),
                composer_output=FinalDecisionComposerOutput(
                    decision_type="HOLD",
                    side="",
                    confidence=0.5,
                ),
            ),
        )

        assert entity is not None
        assert entity.decision_json["expected_value_gate"]["gate_margin"] is None

    def test_gate_margin_addition_does_not_change_passed_verdict(self) -> None:
        """"관측성만 바뀌고 판정은 안 바뀌었다"를 직접 증명한다 —
        동일 입력에 대해 ``passed``가 margin의 부호와 정확히 일치하는
        기존 계약(``edge_after_cost_bps >= minimum_required_edge_bps``)
        그대로 유지됨을 pass/blocked 양쪽에서 재확인."""
        for edge_after_cost_bps, minimum_required_edge_bps, expected_passed in (
            (Decimal("10.00"), Decimal("10.00"), True),  # 경계값(동일) → 통과
            (Decimal("9.99"), Decimal("10.00"), False),  # 근소 부족 → 차단
        ):
            entity = build_trade_decision_entity(
                decision_context_id=uuid4(),
                request=_make_request(),
                assembled_context=_make_context(self._trigger()),
                agent_bundle=AgentExecutionBundle(
                    ai_inputs=AIDecisionInputs(
                        decision_type="BUY",
                        minimum_required_edge_bps=minimum_required_edge_bps,
                        edge_after_cost_bps=edge_after_cost_bps,
                        expected_value_gate_passed=expected_passed,
                    ),
                    composer_output=FinalDecisionComposerOutput(
                        decision_type="BUY",
                        side="BUY",
                        confidence=0.9,
                    ),
                ),
            )
            assert entity is not None
            assert (
                entity.decision_json["expected_value_gate"]["passed"]
                is expected_passed
            )
            gate_margin = entity.decision_json["expected_value_gate"]["gate_margin"]
            margin_value = Decimal(gate_margin["margin_value"])
            # margin의 부호가 판정(passed)과 정확히 대응해야 한다 —
            # margin >= 0 이면 통과, margin < 0 이면 차단.
            assert (margin_value >= 0) == expected_passed
