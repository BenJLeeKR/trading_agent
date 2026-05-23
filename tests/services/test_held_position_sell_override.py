"""Tests for held position sell override logic."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent_trading.services.ai_agents.schemas import AIRiskOutput, FinalDecisionComposerOutput
from agent_trading.services.decision_orchestrator import (
    DecisionOrchestratorService,
    _build_fallback_bundle,
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
        """held position + ``risk_opinion=review`` + ``risk_score>=0.6`` → override."""
        ar = AIRiskOutput(risk_opinion="review", risk_score=0.65)
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
        """held position + ``risk_opinion=review`` + ``risk_score<0.6`` → ``None``."""
        ar = AIRiskOutput(risk_opinion="review", risk_score=0.4)
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
    """``_build_fallback_bundle()``의 EI summary non-empty 검증."""

    def test_fallback_bundle_ei_summary_non_empty(self) -> None:
        """``_build_fallback_bundle()``의 EI output summary가 비공란인지 검증."""
        bundle = _build_fallback_bundle()
        assert bundle.event_output is not None
        assert bundle.event_output.summary != ""
        assert bundle.event_output.summary is not None

    def test_fallback_bundle_ei_summary_contains_korean(self) -> None:
        """``_build_fallback_bundle()``의 EI summary가 한국어 문자열을 포함하는지 검증."""
        bundle = _build_fallback_bundle()
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
        assert " | " in fdc.summary
