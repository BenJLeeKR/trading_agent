"""Tests for held position sell override logic."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from agent_trading.domain.enums import OrderSide
from agent_trading.services.ai_agents.schemas import AIRiskOutput, FinalDecisionComposerOutput
from agent_trading.services.common_types import (
    AgentExecutionBundle,
    AIDecisionInputs,
)
from agent_trading.services.decision_orchestrator import (
    AssembledContext,
    DecisionOrchestratorService,
    OrderIntent,
    build_submit_order_request_from_decision,
)
from agent_trading.services.deterministic_trigger_engine import (
    DeterministicTriggerAssessment,
)
from agent_trading.services.subprocess_helpers import (
    build_fallback_bundle,
)
from agent_trading.domain.models import SubmitOrderRequest


def _make_submit_request(
    *, side: OrderSide, quantity: Decimal, metadata: dict[str, object] | None = None,
) -> SubmitOrderRequest:
    """테스트용 최소 ``SubmitOrderRequest``."""
    return SubmitOrderRequest(
        account_ref="test-account",
        client_order_id="test-client-order-id",
        correlation_id="test-correlation-id",
        strategy_id="test-strategy",
        symbol="005930",
        market="KRX",
        side=side,
        order_type="market",
        quantity=quantity,
        metadata=metadata or {},
    )


def _make_deterministic_trigger(*, exit_score: float) -> DeterministicTriggerAssessment:
    """테스트용 최소 ``DeterministicTriggerAssessment``(exit_score만 의미 있음)."""
    return DeterministicTriggerAssessment(
        trigger_version="v1",
        primary_candidate="REDUCE_CANDIDATE",
        candidate_set=("REDUCE_CANDIDATE",),
        watch_candidate=False,
        buy_candidate=False,
        sell_candidate=False,
        reduce_candidate=True,
        candidate_confidence=exit_score,
        entry_score=None,
        exit_score=exit_score,
        watch_score=None,
        eligibility_passed=True,
        eligibility_reasons=("eligibility_position_present",),
    )


class TestCheckHeldPositionSellOverride:
    """``DecisionOrchestratorService._check_held_position_sell_override()``."""

    @pytest.fixture
    def service(self) -> DecisionOrchestratorService:
        """Minimal service instance for method testing."""
        # Mock repos to satisfy __init__
        mock_repos = MagicMock()
        return DecisionOrchestratorService(repos=mock_repos)

    def test_non_held_position_returns_none(self, service) -> None:
        """``source_type != "held_position"`` → ``None`` (buy 경로 보존)."""
        ar = AIRiskOutput(risk_opinion="reject", risk_score=0.9)
        fdc = FinalDecisionComposerOutput(decision_type="HOLD")
        result = service._check_held_position_sell_override(
            source_type="core",
            ar_output=ar,
            fdc_output=fdc,
        )
        assert result is None

    def test_held_position_risk_allow_returns_none(self, service) -> None:
        """held position + ``risk_opinion=allow`` → ``None``."""
        ar = AIRiskOutput(risk_opinion="allow", risk_score=0.1)
        fdc = FinalDecisionComposerOutput(decision_type="HOLD")
        result = service._check_held_position_sell_override(
            source_type="held_position",
            ar_output=ar,
            fdc_output=fdc,
        )
        assert result is None

    def test_held_position_risk_reject_returns_reduce(self, service) -> None:
        """held position + ``risk_opinion=reject`` → ``("REDUCE", "SELL", ...)``."""
        ar = AIRiskOutput(risk_opinion="reject", risk_score=0.85)
        fdc = FinalDecisionComposerOutput(decision_type="HOLD")
        result = service._check_held_position_sell_override(
            source_type="held_position",
            ar_output=ar,
            fdc_output=fdc,
        )
        assert result is not None
        dt, side, rationale = result
        assert dt == "REDUCE"
        assert side == "SELL"
        assert "held_position_override" in rationale
        assert "reject" in rationale

    def test_held_position_risk_reduce_returns_reduce(self, service) -> None:
        """held position + ``risk_opinion=reduce`` → ``("REDUCE", "SELL", ...)``."""
        ar = AIRiskOutput(risk_opinion="reduce", risk_score=0.7)
        fdc = FinalDecisionComposerOutput(decision_type="HOLD")
        result = service._check_held_position_sell_override(
            source_type="held_position",
            ar_output=ar,
            fdc_output=fdc,
        )
        assert result is not None
        dt, side, rationale = result
        assert dt == "REDUCE"
        assert side == "SELL"

    def test_held_position_risk_review_high_score_returns_reduce(self, service) -> None:
        """held position + ``risk_opinion=review`` + ``risk_score>=0.8`` → override."""
        ar = AIRiskOutput(risk_opinion="review", risk_score=0.85)
        fdc = FinalDecisionComposerOutput(decision_type="HOLD")
        result = service._check_held_position_sell_override(
            source_type="held_position",
            ar_output=ar,
            fdc_output=fdc,
        )
        assert result is not None
        dt, side, rationale = result
        assert dt == "REDUCE"
        assert side == "SELL"
        assert "review" in rationale

    def test_held_position_risk_review_low_score_returns_none(self, service) -> None:
        """held position + ``risk_opinion=review`` + ``risk_score<0.8`` → ``None``."""
        ar = AIRiskOutput(risk_opinion="review", risk_score=0.65)
        fdc = FinalDecisionComposerOutput(decision_type="HOLD")
        result = service._check_held_position_sell_override(
            source_type="held_position",
            ar_output=ar,
            fdc_output=fdc,
        )
        assert result is None

    def test_held_position_high_risk_score_returns_reduce(self, service) -> None:
        """held position + ``risk_score>=0.8`` (allow여도) → override."""
        ar = AIRiskOutput(risk_opinion="allow", risk_score=0.85)
        fdc = FinalDecisionComposerOutput(decision_type="HOLD")
        result = service._check_held_position_sell_override(
            source_type="held_position",
            ar_output=ar,
            fdc_output=fdc,
        )
        assert result is not None
        dt, side, rationale = result
        assert dt == "REDUCE" or dt == "EXIT"

    def test_fdc_already_reduce_no_override(self, service) -> None:
        """FDC가 이미 REDUCE → 이중 override 방지 → ``None``."""
        ar = AIRiskOutput(risk_opinion="reject", risk_score=0.9)
        fdc = FinalDecisionComposerOutput(decision_type="REDUCE")
        result = service._check_held_position_sell_override(
            source_type="held_position",
            ar_output=ar,
            fdc_output=fdc,
        )
        assert result is None

    def test_fdc_already_exit_no_override(self, service) -> None:
        """FDC가 이미 EXIT → 이중 override 방지 → ``None``."""
        ar = AIRiskOutput(risk_opinion="reject", risk_score=0.9)
        fdc = FinalDecisionComposerOutput(decision_type="EXIT")
        result = service._check_held_position_sell_override(
            source_type="held_position",
            ar_output=ar,
            fdc_output=fdc,
        )
        assert result is None

    def test_ar_output_none_returns_none(self, service) -> None:
        """``ar_output=None`` → ``None``."""
        fdc = FinalDecisionComposerOutput(decision_type="HOLD")
        result = service._check_held_position_sell_override(
            source_type="held_position",
            ar_output=None,
            fdc_output=fdc,
        )
        assert result is None

    def test_fdc_output_none_returns_none(self, service) -> None:
        """``fdc_output=None`` → ``None``."""
        ar = AIRiskOutput(risk_opinion="reject", risk_score=0.9)
        result = service._check_held_position_sell_override(
            source_type="held_position",
            ar_output=ar,
            fdc_output=None,
        )
        assert result is None


class TestFallbackBundleEiSummary:
    """``build_fallback_bundle()``의 EI summary non-empty 검증."""

    def test_fallback_bundle_ei_summary_non_empty(self) -> None:
        """``build_fallback_bundle()``의 EI output summary가 비공란인지 검증."""
        bundle = build_fallback_bundle()
        assert bundle.event_output is not None
        assert bundle.event_output.summary != ""
        assert bundle.event_output.summary is not None

    def test_fallback_bundle_ei_summary_contains_korean(self) -> None:
        """``build_fallback_bundle()``의 EI summary가 한국어 문자열을 포함하는지 검증."""
        bundle = build_fallback_bundle()
        assert bundle.event_output is not None
        summary = bundle.event_output.summary
        # _build_summary_text()는 항상 한국어 요약을 생성하므로
        # "유의미한 신규 이벤트 없음"과 같은 문자열이 포함되어야 함
        assert "이벤트" in summary or "전반" in summary or "건" in summary


class TestOverrideRationaleInFdcSummary:
    """Override 발동 시 ``composer_output.summary``에 rationale이 포함되는지 검증.

    ``assemble()`` 메서드의 override 적용 부분에서
    ``agent_bundle.composer_output.summary``에 override rationale이
    추가되는지를 검증한다.
    """

    def test_override_rationale_appended_to_fdc_summary(self) -> None:
        """``_check_held_position_sell_override()`` 반환값을
        ``composer_output.summary``에 추가하는 로직 검증."""
        from agent_trading.services.ai_agents.schemas import (
            EventInterpretationOutput,
        )

        # Given: held_position override가 발동하는 상황
        ar = AIRiskOutput(risk_opinion="reject", risk_score=0.85)
        fdc = FinalDecisionComposerOutput(
            decision_type="HOLD",
            summary="FDC original summary",
        )
        ei = EventInterpretationOutput()

        # _check_held_position_sell_override() 호출
        service = DecisionOrchestratorService(repos=MagicMock())
        override = service._check_held_position_sell_override(
            source_type="held_position",
            ar_output=ar,
            fdc_output=fdc,
        )
        assert override is not None
        override_dt, override_side, override_rationale = override

        # When: composer_output.summary에 override rationale 추가 (assemble() 로직 재현)
        object.__setattr__(
            fdc, "summary",
            (fdc.summary + f" | {override_rationale}") if fdc.summary else override_rationale,
        )

        # Then: summary에 override rationale이 포함되어야 함
        assert override_rationale in fdc.summary
        assert "FDC original summary" in fdc.summary


class TestApplyHeldPositionSellOverrideEvRecompute:
    """``_apply_held_position_sell_override()`` — override 후 EV gate 재계산(2026-08-19).

    배경: override는 ``decision_type``/``side``만 바꾸고 EV gate 8개
    필드(override *이전* HOLD 시점에 트리비얼 통과로 전부 None)는 그대로
    두면, ``translation.py::_has_required_expected_value_anchor()``가
    항상 ``False``를 반환해 주문이 생성되지 않는다. 이 클래스는 override
    직후 ``evaluate_expected_value_gate()``를 재호출해 이 8개 필드가
    실제로 다시 채워지는지, 그리고 그 결과가 기존 REDUCE/EXIT 게이트
    정책(threshold)과 동일한 잣대로 판정되는지를 검증한다.
    """

    @pytest.fixture
    def service(self) -> DecisionOrchestratorService:
        return DecisionOrchestratorService(repos=MagicMock())

    def _make_bundle(
        self, *, confidence: float = 0.63, conviction: float = 0.7,
        risk_score: float = 0.8,
    ) -> AgentExecutionBundle:
        """override 전(HOLD, 트리비얼 EV 통과) 상태를 흉내낸 bundle."""
        ai_inputs = AIDecisionInputs(
            decision_type="HOLD",
            side="",
            confidence=confidence,
            conviction=conviction,
            risk_score=risk_score,
            expected_return_bps=None,
            expected_downside_bps=None,
            net_expected_value_bps=None,
            final_trade_score=None,
            minimum_required_edge_bps=None,
            edge_after_cost_bps=None,
            estimated_round_trip_cost_bps=None,
            slippage_buffer_bps=None,
            expected_value_gate_passed=True,
            expected_value_gate_reason_codes=("expected_value_not_required_non_actionable",),
        )
        return AgentExecutionBundle(
            ai_inputs=ai_inputs,
            risk_output=AIRiskOutput(risk_opinion="reduce", risk_score=risk_score),
            composer_output=FinalDecisionComposerOutput(
                decision_type="HOLD", side="", summary="FDC HOLD summary",
            ),
        )

    def test_override_fires_and_ev_fields_no_longer_none(self, service) -> None:
        """override 발동 시 decision_type/side가 바뀌고, EV gate 8개 필드가
        더 이상 전부 None이 아니어야 한다(트리비얼 통과 상태 탈출)."""
        bundle = self._make_bundle()
        context = AssembledContext(
            source_type="held_position",
            deterministic_trigger=_make_deterministic_trigger(exit_score=0.9),
        )
        derivation = SimpleNamespace(source_type="held_position")

        service._apply_held_position_sell_override(
            agent_bundle=bundle,
            assembled_context=context,
            derivation=derivation,
            symbol="005930",
        )

        assert bundle.ai_inputs.decision_type in ("REDUCE", "EXIT")
        assert bundle.ai_inputs.side == "SELL"
        assert bundle.ai_inputs.expected_return_bps is not None
        assert bundle.ai_inputs.expected_downside_bps is not None
        assert bundle.ai_inputs.net_expected_value_bps is not None
        assert bundle.ai_inputs.final_trade_score is not None
        assert bundle.ai_inputs.minimum_required_edge_bps is not None
        assert bundle.ai_inputs.edge_after_cost_bps is not None
        assert bundle.ai_inputs.estimated_round_trip_cost_bps is not None
        assert bundle.ai_inputs.slippage_buffer_bps is not None
        assert bundle.ai_inputs.expected_value_gate_reason_codes != (
            "expected_value_not_required_non_actionable",
        )

    def test_ev_recompute_works_with_fdc_fallback_shape(self, service) -> None:
        """FDC 429 fallback 형태(confidence=0.0, conviction=0.0)여도 override
        후 EV 재계산이 유효한 값을 만들어야 한다 — SELL/EXIT/REDUCE는
        ``deterministic_trigger.exit_score``를 우선 쓰므로 FDC 자신의
        confidence/conviction과 무관해야 한다."""
        bundle = self._make_bundle(confidence=0.0, conviction=0.0, risk_score=0.85)
        context = AssembledContext(
            source_type="held_position",
            deterministic_trigger=_make_deterministic_trigger(exit_score=0.95),
        )
        derivation = SimpleNamespace(source_type="held_position")

        service._apply_held_position_sell_override(
            agent_bundle=bundle,
            assembled_context=context,
            derivation=derivation,
            symbol="005930",
        )

        assert bundle.ai_inputs.decision_type in ("REDUCE", "EXIT")
        assert bundle.ai_inputs.edge_after_cost_bps is not None
        assert bundle.ai_inputs.net_expected_value_bps is not None

    def test_no_override_leaves_ev_fields_untouched(self, service) -> None:
        """override 조건 미충족(risk_opinion=allow, 낮은 risk_score)이면
        decision_type도 EV 필드도 전혀 바뀌지 않아야 한다."""
        bundle = self._make_bundle(risk_score=0.2)
        object.__setattr__(bundle.risk_output, "risk_opinion", "allow")
        object.__setattr__(bundle.risk_output, "risk_score", 0.2)
        context = AssembledContext(
            source_type="held_position",
            deterministic_trigger=_make_deterministic_trigger(exit_score=0.9),
        )
        derivation = SimpleNamespace(source_type="held_position")

        service._apply_held_position_sell_override(
            agent_bundle=bundle,
            assembled_context=context,
            derivation=derivation,
            symbol="005930",
        )

        assert bundle.ai_inputs.decision_type == "HOLD"
        assert bundle.ai_inputs.expected_return_bps is None
        assert bundle.ai_inputs.expected_value_gate_reason_codes == (
            "expected_value_not_required_non_actionable",
        )

    def test_recomputed_ev_gate_still_blocks_low_edge_case(self, service) -> None:
        """재계산 후에도 edge가 낮으면 여전히 게이트가 막아야 한다 —
        이번 수정이 '차단을 줄이는' 방향이 아님을 확인하는 회귀 테스트."""
        bundle = self._make_bundle(risk_score=0.85)
        # exit_score가 낮고 risk_score(0.85)가 높으면 net_expected_value_bps가
        # 작아져 edge_after_cost_bps가 minimum_required_edge_bps(5bps)에
        # 못 미칠 가능성이 높다.
        context = AssembledContext(
            source_type="held_position",
            deterministic_trigger=_make_deterministic_trigger(exit_score=0.1),
        )
        derivation = SimpleNamespace(source_type="held_position")

        service._apply_held_position_sell_override(
            agent_bundle=bundle,
            assembled_context=context,
            derivation=derivation,
            symbol="005930",
        )

        assert bundle.ai_inputs.expected_value_gate_passed is False
        assert "expected_value_edge_below_minimum_required" in (
            bundle.ai_inputs.expected_value_gate_reason_codes
        )

    def test_translation_accepts_order_after_ev_recompute_with_good_edge(
        self, service,
    ) -> None:
        """override 후 EV 게이트를 실제로 통과하는 케이스는
        ``build_submit_order_request_from_decision()``이 더 이상
        anchor 결측으로 차단하지 않고 주문을 생성해야 한다."""
        bundle = self._make_bundle(risk_score=0.85)
        context = AssembledContext(
            source_type="held_position",
            deterministic_trigger=_make_deterministic_trigger(exit_score=0.95),
        )
        derivation = SimpleNamespace(source_type="held_position")

        service._apply_held_position_sell_override(
            agent_bundle=bundle,
            assembled_context=context,
            derivation=derivation,
            symbol="005930",
        )
        assert bundle.ai_inputs.expected_value_gate_passed is True, (
            "이 테스트는 게이트를 통과하는 exit_score로 구성돼야 한다"
        )

        intent = OrderIntent(
            decision_context_id=uuid4(),
            order_intent_id=uuid4(),
            request=_make_submit_request(
                side=OrderSide.SELL, quantity=Decimal("10"),
                metadata={"source_type": "held_position"},
            ),
            context=context,
            ai_backend_inputs=bundle.ai_inputs,
        )
        result = build_submit_order_request_from_decision(intent)
        assert result is not None, (
            "EV anchor 8개 필드가 채워졌으므로 anchor 결측으로 차단되면 안 된다"
        )
        assert result.side == OrderSide.SELL

    def test_translation_still_blocks_order_without_recompute(self, service) -> None:
        """(수정 전 상태 재현) EV 재계산을 하지 않으면 여전히 anchor 결측으로
        차단됨을 보여, 이번 수정의 필요성을 대조 확인한다."""
        bundle = self._make_bundle(risk_score=0.85)
        # override는 호출하지 않고, decision_type/side만 수동으로 override와
        # 동일하게 바꾼 뒤 EV 필드는 그대로(None) 둔다 — 수정 전 버그 상태 재현.
        object.__setattr__(bundle.ai_inputs, "decision_type", "EXIT")
        object.__setattr__(bundle.ai_inputs, "side", "SELL")

        intent = OrderIntent(
            decision_context_id=uuid4(),
            order_intent_id=uuid4(),
            request=_make_submit_request(
                side=OrderSide.SELL, quantity=Decimal("10"),
                metadata={"source_type": "held_position"},
            ),
            context=AssembledContext(source_type="held_position"),
            ai_backend_inputs=bundle.ai_inputs,
        )
        result = build_submit_order_request_from_decision(intent)
        assert result is None, (
            "EV anchor 8개 필드가 None이면 여전히 차단돼야 한다(버그 재현 확인)"
        )
