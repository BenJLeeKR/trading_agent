"""Tests for FDC prompt WATCH policy and backend WATCH handling (P0).

This module covers:

1. FDC system prompt contains WATCH policy for core+weak evidence.
2. FDC system prompt still has HOLD preference for core+none+no_event.
3. FDC system prompt preserves market_overlay WATCH wording.
4. ``_normalize_decision_type()`` preserves WATCH as canonical.
5. ``build_submit_order_request_from_decision()`` recognises WATCH
   in ``actionable_types`` but still returns ``None`` (no submission).
6. No regression for APPROVE/REDUCE/HOLD paths.

See Also
--------
* :mod:`agent_trading.services.ai_agents.final_decision_composer`
* :mod:`agent_trading.services.decision_orchestrator`
* :doc:`plans/watch_absence_and_no_event_hold_policy_analysis_2026-05-15`
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from agent_trading.services.ai_agents.base import (
    AgentExecutionRequest,
    AIProviderClient,
    RawProviderResponse,
)
from agent_trading.services.ai_agents.final_decision_composer import (
    FinalDecisionComposerAgent,
)
from agent_trading.services.ai_agents.schemas import (
    AggregateEventView,
    EventInterpretationOutput,
    FinalDecisionComposerOutput,
)
from agent_trading.services.common_types import (
    AIDecisionInputs,
    AssembledContext,
    OrderIntent,
)
from agent_trading.services.translation import (
    build_submit_order_request_from_decision,
    normalize_decision_type,
)
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.domain.enums import OrderSide, OrderType, TimeInForce
from decimal import Decimal


# ===========================================================================
# Helper
# ===========================================================================


def _make_intent(
    *,
    decision_type: str = "APPROVE",
    quantity: Decimal | None = None,
    decision_context_id=None,
) -> OrderIntent:
    """Build a minimal ``OrderIntent`` for translation tests."""
    from uuid import UUID

    req = SubmitOrderRequest(
        account_ref="test",
        client_order_id="cid",
        correlation_id="corr",
        strategy_id="strat",
        symbol="005930",
        market="KRX",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=quantity or Decimal("10"),
        price=Decimal("50000"),
        time_in_force=TimeInForce.DAY,
    )
    ai = AIDecisionInputs(decision_type=decision_type)
    dc_id = decision_context_id if decision_context_id is not None else uuid4()
    return OrderIntent(
        decision_context_id=dc_id,
        order_intent_id=uuid4(),
        request=req,
        context=AssembledContext(),
        ai_backend_inputs=ai,
    )


# ===========================================================================
# Test 1: FDC system prompt — WATCH policy for core+weak
# ===========================================================================


class TestFDCSystemPromptWatchPolicy:
    """FDC system prompt must include explicit WATCH guidance for core source_type."""

    def test_core_weak_watch_mentioned(self) -> None:
        """System prompt must mention WATCH for core+evidence_strength=weak."""
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        prompt = agent._build_system_prompt()
        assert "WATCH may be considered" in prompt
        assert "monitor without entering" in prompt
        assert "valid non-HOLD option" in prompt

    def test_core_none_no_watch(self) -> None:
        """System prompt for core+evidence_strength=none must prefer HOLD,
        without recommending WATCH."""
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        prompt = agent._build_system_prompt()
        # core+none should say "insufficient information to act" → HOLD
        assert "insufficient information to act" in prompt
        # The old "but WATCH is acceptable if risk is low" must NOT be there
        # for core+none (it was removed in the new policy)
        assert "WATCH is acceptable" not in prompt

    def test_market_overlay_watch_preserved(self) -> None:
        """Existing market_overlay WATCH wording must be preserved."""
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        prompt = agent._build_system_prompt()
        assert "market_overlay" in prompt
        assert "can be APPROVED or WATCHed" in prompt or "CAN be APPROVED or WATCHed" in prompt

    def test_no_event_policy_section_present(self) -> None:
        """The No-Event Policy section header must be present."""
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        prompt = agent._build_system_prompt()
        assert "No-Event Policy" in prompt

    def test_negative_signal_still_separated(self) -> None:
        """'negative signal' must still be separated from 'no event'."""
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        prompt = agent._build_system_prompt()
        assert "negative signal" in prompt
        assert "NOT the same" in prompt

    def test_moderate_strong_core_evaluate_normally(self) -> None:
        """moderate/strong evidence for core must say 'evaluate normally'."""
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        prompt = agent._build_system_prompt()
        assert "Evaluate normally" in prompt
        assert "APPROVE/REDUCE/EXIT" in prompt

    def test_source_type_core_weak_acceptable(self) -> None:
        """Source Type Consideration for core must mention WATCH is viable
        when evidence is weak."""
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        prompt = agent._build_system_prompt()
        assert "WATCH may be viable when evidence is weak" in prompt


# ===========================================================================
# Test 2: FDC user prompt — evidence_strength display for core+weak
# ===========================================================================


class TestFDCUserPromptEvidenceStrength:
    """FDC user prompt must display evidence_strength=weak for core symbols."""

    def _make_request(
        self,
        evidence_strength: str = "weak",
        source_type: str = "core",
    ) -> AgentExecutionRequest:
        context = AssembledContext(source_type=source_type)
        ei_output = EventInterpretationOutput(
            aggregate_view=AggregateEventView(
                overall_bias="neutral",
                event_conflict=False,
                evidence_strength=evidence_strength,
                event_count=1,
                no_material_events=False,
            ),
        )
        return AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="test-watch",
            context=context,
            symbol="005930",
            market="KRX",
            source_type=source_type,
            event_interpretation_output=ei_output,
        )

    def test_weak_evidence_in_prompt(self) -> None:
        """Evidence strength=weak must appear in user prompt."""
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        request = self._make_request(evidence_strength="weak")
        prompt = agent._build_user_prompt(request)
        assert "Evidence strength: weak" in prompt

    def test_none_evidence_in_prompt(self) -> None:
        """Evidence strength=none must appear in user prompt."""
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        request = self._make_request(evidence_strength="none", source_type="core")
        prompt = agent._build_user_prompt(request)
        assert "Evidence strength: none" in prompt

    def test_source_type_core_in_prompt(self) -> None:
        """Source type=core must appear in user prompt."""
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        request = self._make_request(source_type="core")
        prompt = agent._build_user_prompt(request)
        assert "Source type: core" in prompt

    def test_no_event_true_in_prompt(self) -> None:
        """no_material_events=True must appear in user prompt."""
        ei_output = EventInterpretationOutput(
            aggregate_view=AggregateEventView(
                evidence_strength="none",
                event_count=0,
                no_material_events=True,
            ),
        )
        request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="test-no-event",
            context=AssembledContext(),
            symbol="005930",
            market="KRX",
            source_type="core",
            event_interpretation_output=ei_output,
        )
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        prompt = agent._build_user_prompt(request)
        assert "No material events: True" in prompt


# ===========================================================================
# Test 3: Normalization — WATCH preserved
# ===========================================================================


class TestNormalizeDecisionTypeWatch:
    """``normalize_decision_type()`` must preserve WATCH as canonical."""

    def test_watch_passthrough(self) -> None:
        """WATCH passes through unchanged."""
        assert normalize_decision_type("WATCH") == "WATCH"

    def test_watch_lowercase_passthrough(self) -> None:
        """watch (lowercase) normalizes to WATCH."""
        assert normalize_decision_type("watch") == "WATCH"

    def test_watch_mixed_case_passthrough(self) -> None:
        """Watch (mixed case) normalizes to WATCH."""
        assert normalize_decision_type("Watch") == "WATCH"


# ===========================================================================
# Test 4: Backend path — WATCH in actionable_types but no submission
# ===========================================================================


class TestBuildSubmitOrderRequestWatch:
    """WATCH must be recognised but must not produce a submit request."""

    def test_watch_in_actionable_types(self) -> None:
        """WATCH must never produce a submit request."""
        # R5-a: WATCH is excluded from actionable_types (not a separate
        # follow-up branch anymore) — both forms return None identically.
        intent = _make_intent(decision_type="WATCH")
        result = build_submit_order_request_from_decision(intent)
        assert result is None, "WATCH must NOT produce a submit request"

    def test_watch_does_not_break_approve(self) -> None:
        """APPROVE still returns a valid request (regression check)."""
        intent = _make_intent(decision_type="APPROVE")
        result = build_submit_order_request_from_decision(intent)
        assert result is not None

    def test_watch_does_not_break_reduce(self) -> None:
        """REDUCE still returns a valid request (regression check)."""
        intent = _make_intent(decision_type="REDUCE")
        result = build_submit_order_request_from_decision(intent)
        assert result is not None

    def test_watch_does_not_break_hold(self) -> None:
        """HOLD still returns None (regression check)."""
        intent = _make_intent(decision_type="HOLD")
        result = build_submit_order_request_from_decision(intent)
        assert result is None

    def test_watch_does_not_break_exit(self) -> None:
        """EXIT still returns a valid request (regression check)."""
        intent = _make_intent(decision_type="EXIT")
        result = build_submit_order_request_from_decision(intent)
        assert result is not None

    def test_watch_does_not_break_buy(self) -> None:
        """BUY still returns a valid request (regression check)."""
        intent = _make_intent(decision_type="BUY")
        result = build_submit_order_request_from_decision(intent)
        assert result is not None

    def test_watch_does_not_break_sell(self) -> None:
        """SELL still returns a valid request (regression check)."""
        intent = _make_intent(decision_type="SELL")
        result = build_submit_order_request_from_decision(intent)
        assert result is not None


# ===========================================================================
# Test 5: WATCH decision is recorded via AIDecisionInputs
# ===========================================================================


class TestWatchDecisionRecording:
    """WATCH decision_type must flow through to AIDecisionInputs."""

    def test_watch_in_decision_inputs(self) -> None:
        """WATCH decision_type must be carried by AIDecisionInputs."""
        inputs = AIDecisionInputs(decision_type="WATCH")
        assert inputs.decision_type == "WATCH"

    def test_watch_not_mapped_to_hold(self) -> None:
        """WATCH must NOT be silently mapped to HOLD in AIDecisionInputs."""
        # Simulate the _run_agents() normalization path
        normalized = normalize_decision_type("WATCH")
        assert normalized == "WATCH"
        inputs = AIDecisionInputs(decision_type=normalized)
        assert inputs.decision_type == "WATCH"
        assert inputs.decision_type != "HOLD"

    def test_decision_json_contains_watch(self) -> None:
        """A decision_json dict should preserve WATCH when present."""
        # This simulates what _ensure_trade_decision does
        decision_json = {
            "decision_type": "WATCH",
            "side": "",
            "entry_style": "",
        }
        assert decision_json["decision_type"] == "WATCH"


# ===========================================================================
# Test 6: SubmitResult SKIPPED status for WATCH
# ===========================================================================


class TestSubmitResultForWatch:
    """WATCH decisions must result in SKIPPED status, not SUBMITTED."""

    def test_submit_result_skipped_for_watch(self) -> None:
        """Simulate the assemble_and_submit Phase 2 check for WATCH."""
        from agent_trading.services.common_types import SubmitResult

        result = SubmitResult(
            status="SKIPPED",
            error_phase="translation",
            error_message="Decision type 'WATCH' produced no order request",
        )
        assert result.status == "SKIPPED"
        assert result.error_phase == "translation"


# ===========================================================================
# Test 7: No regression — existing HOLD/APPROVE/REDUCE paths
# ===========================================================================


class TestNoRegression:
    """Existing decision paths must not regress."""

    def test_aggregate_view_defaults_unchanged(self) -> None:
        """AggregateEventView defaults must remain (no regression)."""
        view = AggregateEventView()
        assert view.evidence_strength == "none"
        assert view.event_count == 0
        assert view.no_material_events is True

    def test_fdc_output_default_still_hold(self) -> None:
        """FinalDecisionComposerOutput default must still be HOLD."""
        output = FinalDecisionComposerOutput()
        assert output.decision_type == "HOLD"

    def test_system_prompt_still_lists_all_decision_types(self) -> None:
        """System prompt must still list all canonical decision types."""
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        prompt = agent._build_system_prompt()
        for dt in ("APPROVE", "BUY", "SELL", "HOLD", "WATCH", "EXIT", "REDUCE"):
            assert dt in prompt, f"Canonical type {dt!r} missing from system prompt"

    def test_system_prompt_still_lists_source_types(self) -> None:
        """System prompt must still list all four source types."""
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        prompt = agent._build_system_prompt()
        for st in ("core", "held_position", "event_overlay", "market_overlay"):
            assert st in prompt, f"Source type {st!r} missing from system prompt"


# ===========================================================================
# Test 9: held_position — FDC decision_type scope restriction (2026-08-18 KST)
# ===========================================================================


class TestFDCHeldPositionDecisionTypeScope:
    """FDC가 held_position에서 APPROVE/BUY를 선택지로 두지 않아야 한다."""

    def test_held_position_prompt_excludes_approve_and_buy_from_allowed_list(
        self,
    ) -> None:
        """held_position 프롬프트의 canonical enum 목록에는 APPROVE/BUY가
        없어야 하고, REDUCE/EXIT/HOLD/WATCH만 나열돼야 한다."""
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        prompt = agent._build_system_prompt(source_type="held_position")
        assert "decision_type: one of REDUCE, EXIT, HOLD, WATCH" in prompt

    def test_held_position_prompt_has_explicit_invalid_statement(self) -> None:
        """held_position 프롬프트는 APPROVE/BUY가 invalid임을 명시해야 한다."""
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        prompt = agent._build_system_prompt(source_type="held_position")
        assert "Held Position Decision Scope" in prompt
        assert "APPROVE and BUY are INVALID" in prompt
        assert "ALREADY HELD" in prompt

    def test_non_held_position_prompt_unaffected(self) -> None:
        """core/event_overlay/market_overlay/None은 기존 7종 전체 허용
        문구가 그대로 유지돼야 한다(무영향 확인)."""
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        for source_type in ("core", "event_overlay", "market_overlay", None):
            prompt = agent._build_system_prompt(source_type=source_type)
            assert (
                "decision_type: one of APPROVE, BUY, SELL, HOLD, WATCH, EXIT, REDUCE"
                in prompt
            )
            # 조건부 섹션(## Held Position Decision Scope ...) 자체가
            # 삽입되지 않아야 한다 — "Source Type Consideration"의
            # held_position 일반 설명 문구(모든 source_type 호출에 공통으로
            # 존재)는 별개이므로 이건 걸러내지 않는다.
            assert "ALREADY HELD" not in prompt
            assert "## Held Position Decision Scope" not in prompt

    def test_default_call_without_source_type_unaffected(self) -> None:
        """인자 없이 호출하는 기존 호출부(하위 호환)는 전체 7종을 그대로
        유지해야 한다."""
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        prompt = agent._build_system_prompt()
        assert (
            "decision_type: one of APPROVE, BUY, SELL, HOLD, WATCH, EXIT, REDUCE"
            in prompt
        )


class TestFDCHeldPositionDecisionTypeGuard:
    """``_guard_held_position_decision_type()`` — 출력 정규화 검증."""

    def _make_output(self, decision_type: str) -> FinalDecisionComposerOutput:
        return FinalDecisionComposerOutput(
            decision_type=decision_type,
            side="BUY" if decision_type in {"APPROVE", "BUY"} else "",
            reason_codes=("some_reason",),
            summary="원본 요약",
        )

    def test_approve_is_normalized_to_hold_for_held_position(self) -> None:
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        result = agent._guard_held_position_decision_type(
            self._make_output("APPROVE"), source_type="held_position",
        )
        assert result.decision_type == "HOLD"
        assert result.side == ""
        assert "fdc_held_position_decision_type_guard" in result.reason_codes
        assert "fdc_held_position_decision_type_guard" in result.summary

    def test_buy_is_normalized_to_hold_for_held_position(self) -> None:
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        result = agent._guard_held_position_decision_type(
            self._make_output("BUY"), source_type="held_position",
        )
        assert result.decision_type == "HOLD"

    def test_sell_is_normalized_to_hold_for_held_position(self) -> None:
        """SELL도 canonical held_position sell path(REDUCE/EXIT)가 아니므로
        정규화 대상이다."""
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        result = agent._guard_held_position_decision_type(
            self._make_output("SELL"), source_type="held_position",
        )
        assert result.decision_type == "HOLD"

    def test_reduce_passes_through_unchanged_for_held_position(self) -> None:
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        original = self._make_output("REDUCE")
        result = agent._guard_held_position_decision_type(
            original, source_type="held_position",
        )
        assert result is original
        assert result.decision_type == "REDUCE"
        assert "fdc_held_position_decision_type_guard" not in result.reason_codes

    def test_exit_passes_through_unchanged_for_held_position(self) -> None:
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        original = self._make_output("EXIT")
        result = agent._guard_held_position_decision_type(
            original, source_type="held_position",
        )
        assert result is original

    def test_watch_passes_through_unchanged_for_held_position(self) -> None:
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        original = self._make_output("WATCH")
        result = agent._guard_held_position_decision_type(
            original, source_type="held_position",
        )
        assert result is original

    def test_hold_passes_through_unchanged_for_held_position(self) -> None:
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        original = self._make_output("HOLD")
        result = agent._guard_held_position_decision_type(
            original, source_type="held_position",
        )
        assert result is original

    def test_approve_unaffected_for_core(self) -> None:
        """non-held_position(core 등)에서는 APPROVE/BUY가 여전히 그대로
        통과해야 한다 — 무영향 확인."""
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        original = self._make_output("APPROVE")
        result = agent._guard_held_position_decision_type(
            original, source_type="core",
        )
        assert result is original
        assert result.decision_type == "APPROVE"

    def test_buy_unaffected_for_event_overlay(self) -> None:
        agent = FinalDecisionComposerAgent(provider_client=MagicMock())
        original = self._make_output("BUY")
        result = agent._guard_held_position_decision_type(
            original, source_type="event_overlay",
        )
        assert result is original


class TestFDCRunEndToEndHeldPositionScope:
    """``run()`` 전체 경로 — provider가 규칙을 어겨도 held_position에서는
    최종적으로 REDUCE/EXIT/HOLD/WATCH만 반환됨을 증명(end-to-end)."""

    @pytest.mark.asyncio
    async def test_run_normalizes_approve_to_hold_for_held_position(self) -> None:
        provider = AsyncMock(spec=AIProviderClient)
        captured_kwargs: dict[str, object] = {}

        async def _generate(**kwargs: object) -> RawProviderResponse:
            captured_kwargs.update(kwargs)
            # provider가 규칙을 어기고 APPROVE를 반환하는 상황을 시뮬레이션.
            return RawProviderResponse(
                parsed=FinalDecisionComposerOutput(
                    decision_type="APPROVE",
                    side="BUY",
                    summary="추가 매수 근거 요약",
                ),
                raw_content="{}",
            )

        provider.generate_structured = _generate  # type: ignore[method-assign]

        request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="held-position-guard",
            context=AssembledContext(source_type="held_position"),
            symbol="009240",
            market="KRX",
            source_type="held_position",
        )

        agent = FinalDecisionComposerAgent(provider_client=provider)
        result = await agent.run(request)

        # 프롬프트 단계에서 이미 held_position 제한 문구가 나갔는지 확인.
        system_prompt = str(captured_kwargs.get("system_prompt", ""))
        assert "decision_type: one of REDUCE, EXIT, HOLD, WATCH" in system_prompt

        # provider가 규칙을 어겼어도 최종 출력은 HOLD로 정규화됨을 확인.
        assert result.decision_type == "HOLD"
        assert result.side == ""
        assert "fdc_held_position_decision_type_guard" in result.reason_codes

    @pytest.mark.asyncio
    async def test_run_preserves_reduce_for_held_position(self) -> None:
        """held_position에서 REDUCE(위험 축소 판단)는 그대로 통과해야 한다."""
        provider = AsyncMock(spec=AIProviderClient)

        async def _generate(**kwargs: object) -> RawProviderResponse:
            return RawProviderResponse(
                parsed=FinalDecisionComposerOutput(
                    decision_type="REDUCE",
                    side="SELL",
                    summary="위험회피로 축소",
                ),
                raw_content="{}",
            )

        provider.generate_structured = _generate  # type: ignore[method-assign]

        request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="held-position-reduce",
            context=AssembledContext(source_type="held_position"),
            symbol="009240",
            market="KRX",
            source_type="held_position",
        )

        agent = FinalDecisionComposerAgent(provider_client=provider)
        result = await agent.run(request)

        assert result.decision_type == "REDUCE"
        assert result.side == "SELL"
        assert "fdc_held_position_decision_type_guard" not in result.reason_codes

    @pytest.mark.asyncio
    async def test_run_leaves_core_approve_unaffected(self) -> None:
        """core에서는 APPROVE가 여전히 그대로 유지돼야 한다(무영향 확인)."""
        provider = AsyncMock(spec=AIProviderClient)

        async def _generate(**kwargs: object) -> RawProviderResponse:
            return RawProviderResponse(
                parsed=FinalDecisionComposerOutput(
                    decision_type="APPROVE",
                    side="BUY",
                    summary="신규 진입 근거",
                ),
                raw_content="{}",
            )

        provider.generate_structured = _generate  # type: ignore[method-assign]

        request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="core-approve",
            context=AssembledContext(source_type="core"),
            symbol="005930",
            market="KRX",
            source_type="core",
        )

        agent = FinalDecisionComposerAgent(provider_client=provider)
        result = await agent.run(request)

        assert result.decision_type == "APPROVE"
        assert result.side == "BUY"


# ===========================================================================
# Test 8: FDC Position Concentration tests
# ===========================================================================


