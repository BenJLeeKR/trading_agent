"""Tests for the deterministic Event Interpretation bot.

2026-08-17 결정: LLM 기반 ``EventInterpretationAgent``를 실행 경로에서
제거하고, ``DeterministicEventInterpretationAgent``로 전환했다(PR1,
AR은 별도 PR). 이 bot은 정형 이벤트 필드(``direction``/``severity``/
``source_reliability_tier``)만으로 판단하고, 비정형 헤드라인/본문 텍스트
해석은 하지 않는다. ``compute_shadow_event_bot()``(shadow_bots.py)과
완전히 동일한 계산 로직을 공유하되, reason_codes 마커만
``deterministic_rule_set:*``로 구분한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from agent_trading.domain.entities import ExternalEventEntity
from agent_trading.services.ai_agents.base import AgentExecutionRequest
from agent_trading.services.ai_agents.event_interpretation import (
    DeterministicEventInterpretationAgent,
    _compute_deterministic_event_interpretation,
)
from agent_trading.services.ai_agents.schemas import EventInterpretationOutput
from agent_trading.services.common_types import AIPolicyContextView
from agent_trading.services.shadow_bots import EI_BOT_RULE_SET_VERSION


def _event(direction: str, *, tier: str = "T3") -> ExternalEventEntity:
    return ExternalEventEntity(
        event_id=uuid4(),
        event_type="news",
        source_name="test",
        published_at=datetime.now(timezone.utc),
        symbol="005930",
        market="KRX",
        source_reliability_tier=tier,
        direction=direction,
        headline="test headline",
    )


def _make_request(
    *,
    decision_context_id=None,
    symbol: str = "005930",
    recent_events: tuple[ExternalEventEntity, ...] = (),
) -> AgentExecutionRequest:
    return AgentExecutionRequest(
        decision_context_id=decision_context_id or uuid4(),
        correlation_id="ei-deterministic-test",
        context=AIPolicyContextView(
            source_type="core", recent_events=recent_events,
        ),
        symbol=symbol,
        market="KRX",
        source_type="core",
    )


class TestDeterministicEventInterpretationAgent:
    """``DeterministicEventInterpretationAgent``는 LLM 호출 없이 항상 값을 반환한다."""

    def test_agent_name_matches_llm_agent_for_compatibility(self) -> None:
        """agent_type 기반 API/UI 필터(``agent_type=="event_interpretation"``)
        호환을 위해 agent_name을 그대로 유지해야 한다."""
        agent = DeterministicEventInterpretationAgent()
        assert agent.agent_name == "event_interpretation"
        assert agent.schema_version == "v1"

    def test_last_error_metadata_is_always_none(self) -> None:
        """decision_agent_runner.py가 ``self._ei_agent.last_error_metadata``를
        직접 접근하므로 이 프로퍼티가 반드시 존재해야 한다."""
        agent = DeterministicEventInterpretationAgent()
        assert agent.last_error_metadata is None

    @pytest.mark.asyncio
    async def test_run_never_calls_llm_and_returns_event_interpretation_output(
        self,
    ) -> None:
        agent = DeterministicEventInterpretationAgent()
        result = await agent.run(_make_request())
        assert isinstance(result, EventInterpretationOutput)
        assert result.agent_name == "event_interpretation"


class TestComputeDeterministicEventInterpretation:
    """계산 함수 ``_compute_deterministic_event_interpretation()`` 단위 테스트."""

    def test_no_events_is_no_material_events(self) -> None:
        output = _compute_deterministic_event_interpretation(_make_request())
        assert output.detected_event_count == 0
        assert output.interpreted_event_count == 0
        assert output.aggregate_view.overall_bias == "neutral"
        assert output.aggregate_view.event_conflict is False
        assert output.aggregate_view.evidence_strength == "none"
        assert output.aggregate_view.no_material_events is True
        assert any(
            code.startswith(f"deterministic_rule_set:{EI_BOT_RULE_SET_VERSION}")
            for code in output.aggregate_view.top_reason_codes
        )

    def test_positive_majority_sets_positive_bias(self) -> None:
        request = _make_request(
            recent_events=(_event("positive"), _event("positive")),
        )
        output = _compute_deterministic_event_interpretation(request)
        assert output.detected_event_count == 2
        assert output.interpreted_event_count == 2
        assert output.aggregate_view.overall_bias == "positive"
        assert output.aggregate_view.event_conflict is False
        assert output.aggregate_view.no_material_events is False

    def test_negative_majority_sets_negative_bias(self) -> None:
        request = _make_request(
            recent_events=(_event("negative"), _event("negative"), _event("negative")),
        )
        output = _compute_deterministic_event_interpretation(request)
        assert output.aggregate_view.overall_bias == "negative"
        assert output.aggregate_view.event_conflict is False

    def test_mixed_direction_is_conflict(self) -> None:
        request = _make_request(
            recent_events=(_event("positive"), _event("negative")),
        )
        output = _compute_deterministic_event_interpretation(request)
        assert output.aggregate_view.event_conflict is True
        assert any(
            "event_conflict_detected" in code
            for code in output.aggregate_view.top_reason_codes
        )

    def test_t1_source_upgrades_evidence_strength(self) -> None:
        weak_request = _make_request(
            recent_events=(_event("positive", tier="T3"),),
        )
        strong_candidate_request = _make_request(
            recent_events=(_event("positive", tier="T1"),),
        )
        weak_output = _compute_deterministic_event_interpretation(weak_request)
        upgraded_output = _compute_deterministic_event_interpretation(
            strong_candidate_request
        )
        assert weak_output.aggregate_view.evidence_strength == "weak"
        assert upgraded_output.aggregate_view.evidence_strength == "moderate"
        assert any(
            "t1_source_present" in code
            for code in upgraded_output.aggregate_view.top_reason_codes
        )

    def test_deterministic_rule_set_marker_present(self) -> None:
        output = _compute_deterministic_event_interpretation(
            _make_request(recent_events=(_event("positive"),)),
        )
        assert any(
            code == f"deterministic_rule_set:{EI_BOT_RULE_SET_VERSION}"
            for code in output.aggregate_view.top_reason_codes
        )
        # shadow 관측 전용 마커(shadow_rule_set:*)는 본경로 출력에 남으면 안 된다.
        assert not any(
            code.startswith("shadow_rule_set:")
            for code in output.aggregate_view.top_reason_codes
        )

    def test_events_reconstructed_with_factual_fields_only(self) -> None:
        """개별 이벤트는 ``_reconstruct_events()``로 factual 필드만 채워야
        한다 — LLM-only 필드(novelty/confidence 등)는 조작하지 않는다."""
        request = _make_request(recent_events=(_event("positive"),))
        output = _compute_deterministic_event_interpretation(request)
        assert len(output.events) == 1
        event = output.events[0]
        assert event.impact_direction == "positive"
        assert event.is_reconstructed is True
        assert event.confidence == 0.0

    def test_decision_context_id_and_symbol_propagated(self) -> None:
        ctx_id = uuid4()
        request = _make_request(decision_context_id=ctx_id, symbol="000660")
        output = _compute_deterministic_event_interpretation(request)
        assert output.decision_context_id == str(ctx_id)
        assert output.symbol == "000660"
        assert output.agent_name == "event_interpretation"

    def test_fdc_relevant_fields_all_populated(self) -> None:
        """FDC가 참조하는 필드가 전부 채워지는지 확인한다(FDC 코드 미수정
        원칙 검증 — final_decision_composer.py:328-344 참조 필드)."""
        request = _make_request(
            recent_events=(_event("positive"), _event("negative")),
        )
        output = _compute_deterministic_event_interpretation(request)
        av = output.aggregate_view
        # 아래 접근이 예외 없이 되는지가 핵심 — FDC 프롬프트 빌더가
        # 참조하는 것과 동일한 필드들이다.
        assert av.overall_bias in {"positive", "negative", "neutral"}
        assert isinstance(av.event_conflict, bool)
        assert av.evidence_strength in {"none", "weak", "moderate", "strong"}
        assert isinstance(av.no_material_events, bool)
        assert isinstance(av.top_reason_codes, tuple)
        assert isinstance(output.detected_event_count, int)
        assert isinstance(output.events, tuple)
