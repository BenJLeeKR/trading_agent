"""Tests for EV gate near-miss 조건부 완화(SPPV-2.87/2.88).

두 계층을 검증한다:
1. ``resolve_ev_gate_near_miss_override()`` — 5개 AND 조건 순수 판정.
2. ``build_submit_order_request_from_decision()`` — near-miss override가
   적용된 ``AIDecisionInputs``가 실제로 제출을 허용하는지.

전역 threshold(``minimum_required_edge_bps``)나 EV 계산 로직은 이 변경으로
전혀 바뀌지 않는다 — 이 테스트들은 그 사실을 하위호환 축으로도 확인한다.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from agent_trading.domain.enums import OrderSide
from agent_trading.services.decision_orchestrator import (
    AIDecisionInputs,
    AssembledContext,
    OrderIntent,
    build_submit_order_request_from_decision,
    resolve_ev_gate_near_miss_override,
)
from agent_trading.services.decision_orchestrator import SubmitOrderRequest


def _base_kwargs(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = dict(
        enabled=True,
        decision_type="APPROVE",
        expected_value_gate_passed=False,
        source_type="core",
        minimum_required_edge_bps=Decimal("10.00"),
        edge_after_cost_bps=Decimal("8.56"),
        deterministic_trigger_reason_codes=("trigger_r3b_alpha_percentile",),
    )
    kwargs.update(overrides)
    return kwargs


class TestResolveEvGateNearMissOverride:
    """순수 판정 함수 단위 테스트 — 5개 AND 조건."""

    def test_disabled_switch_never_applies(self) -> None:
        applied, deficit, threshold = resolve_ev_gate_near_miss_override(
            **_base_kwargs(enabled=False)
        )
        assert applied is False
        assert deficit is None
        assert threshold is None

    def test_all_conditions_met_within_2bps_applies(self) -> None:
        applied, deficit, threshold = resolve_ev_gate_near_miss_override(
            **_base_kwargs()
        )
        assert applied is True
        assert deficit == Decimal("1.44")
        assert threshold == Decimal("2.0")

    def test_deficit_over_2bps_does_not_apply(self) -> None:
        applied, deficit, threshold = resolve_ev_gate_near_miss_override(
            **_base_kwargs(edge_after_cost_bps=Decimal("6.56"))  # deficit=3.44
        )
        assert applied is False
        assert deficit is None
        assert threshold is None

    def test_already_passed_gate_does_not_apply(self) -> None:
        """EV gate가 이미 통과(True)한 경우는 near-miss override 대상이 아니다."""
        applied, _, _ = resolve_ev_gate_near_miss_override(
            **_base_kwargs(expected_value_gate_passed=True)
        )
        assert applied is False

    def test_non_core_source_type_does_not_apply(self) -> None:
        applied, _, _ = resolve_ev_gate_near_miss_override(
            **_base_kwargs(source_type="held_position")
        )
        assert applied is False

    def test_without_r3b_reason_code_does_not_apply(self) -> None:
        """R3b가 아닌 일반 케이스는 영향받지 않는다."""
        applied, _, _ = resolve_ev_gate_near_miss_override(
            **_base_kwargs(deterministic_trigger_reason_codes=("trigger_source_core",))
        )
        assert applied is False

    def test_non_actionable_decision_type_does_not_apply(self) -> None:
        applied, _, _ = resolve_ev_gate_near_miss_override(
            **_base_kwargs(decision_type="WATCH")
        )
        assert applied is False

    def test_missing_edge_values_does_not_apply(self) -> None:
        applied, _, _ = resolve_ev_gate_near_miss_override(
            **_base_kwargs(minimum_required_edge_bps=None)
        )
        assert applied is False

    def test_exact_boundary_2bps_applies(self) -> None:
        """부족분이 정확히 2.0bps인 경계값도 통과(<=)."""
        applied, deficit, _ = resolve_ev_gate_near_miss_override(
            **_base_kwargs(edge_after_cost_bps=Decimal("8.00"))  # deficit=2.00
        )
        assert applied is True
        assert deficit == Decimal("2.00")


def _make_ai_inputs(
    *,
    expected_value_gate_passed: bool,
    ev_gate_near_miss_override_applied: bool = False,
    ev_gate_near_miss_deficit_bps: Decimal | None = None,
) -> AIDecisionInputs:
    return AIDecisionInputs(
        decision_type="APPROVE",
        side="buy",
        expected_return_bps=Decimal("78.56"),
        expected_downside_bps=Decimal("42.00"),
        net_expected_value_bps=Decimal("36.56"),
        final_trade_score=Decimal("0.77"),
        minimum_required_edge_bps=Decimal("10.00"),
        edge_after_cost_bps=Decimal("8.56"),
        estimated_round_trip_cost_bps=Decimal("8.00"),
        slippage_buffer_bps=Decimal("20.00"),
        expected_value_gate_passed=expected_value_gate_passed,
        ev_gate_near_miss_override_applied=ev_gate_near_miss_override_applied,
        ev_gate_near_miss_deficit_bps=ev_gate_near_miss_deficit_bps,
    )


def _make_order_intent(ai_inputs: AIDecisionInputs) -> OrderIntent:
    request = SubmitOrderRequest(
        account_ref="test-account",
        client_order_id="test-client-order-id",
        correlation_id="test-correlation-id",
        strategy_id="test-strategy",
        symbol="000810",
        market="KRX",
        side=OrderSide.BUY,
        order_type="market",
        quantity=Decimal("10"),
    )
    return OrderIntent(
        decision_context_id=uuid4(),
        order_intent_id=uuid4(),
        request=request,
        context=AssembledContext(),
        ai_backend_inputs=ai_inputs,
    )


class TestTranslationNearMissOverride:
    """``build_submit_order_request_from_decision()``의 near-miss 반영 확인."""

    def test_off_path_ev_fail_without_override_returns_none(self) -> None:
        """스위치 off(override 미적용) 상태 — 기존 동작과 100% 동일하게 차단."""
        ai_inputs = _make_ai_inputs(expected_value_gate_passed=False)
        intent = _make_order_intent(ai_inputs)
        result = build_submit_order_request_from_decision(intent)
        assert result is None

    def test_on_path_near_miss_override_allows_submission(self) -> None:
        """override 적용 시 동일 EV-fail 조건이라도 제출이 허용된다."""
        ai_inputs = _make_ai_inputs(
            expected_value_gate_passed=False,
            ev_gate_near_miss_override_applied=True,
            ev_gate_near_miss_deficit_bps=Decimal("1.44"),
        )
        intent = _make_order_intent(ai_inputs)
        result = build_submit_order_request_from_decision(intent)
        assert result is not None
        assert result.side == OrderSide.BUY

    def test_original_gate_passed_field_untouched_by_override_flag(self) -> None:
        """override가 True여도 원 expected_value_gate_passed 값은 그대로 False —
        판정 로직 자체를 바꾸는 게 아니라 제출 허용 여부만 바꾼다는 것을 보존한다."""
        ai_inputs = _make_ai_inputs(
            expected_value_gate_passed=False,
            ev_gate_near_miss_override_applied=True,
            ev_gate_near_miss_deficit_bps=Decimal("1.44"),
        )
        assert ai_inputs.expected_value_gate_passed is False
        assert ai_inputs.ev_gate_near_miss_override_applied is True

    def test_gate_pass_without_override_flag_still_works_as_before(self) -> None:
        """near-miss 필드 도입이 기존 EV-pass 케이스의 하위호환을 깨지 않는다."""
        ai_inputs = _make_ai_inputs(expected_value_gate_passed=True)
        intent = _make_order_intent(ai_inputs)
        result = build_submit_order_request_from_decision(intent)
        assert result is not None
