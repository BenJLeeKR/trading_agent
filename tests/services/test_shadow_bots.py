"""Tests for AR/EI shadow bot 순수 계산(``shadow_bots.py``).

이 테스트들은 ``compute_shadow_risk_bot``/``compute_shadow_event_bot``이
순수 함수이고, 확실한 정형 근거가 있을 때만 위험/이벤트 신호를 올린다는
것을 검증한다. 실제 주문/decision_type에 대한 영향은 여기서 다루지
않는다(``test_decision_orchestrator.py``의 ``TestArShadowBotObservation``/
``TestEiShadowBotObservation``에서 별도로 검증).
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from agent_trading.domain.entities import ExternalEventEntity
from agent_trading.services.deterministic_trigger_engine import (
    DeterministicTriggerAssessment,
)
from agent_trading.services.market_regime import MarketRegimeAssessment
from agent_trading.services.portfolio_allocation import PortfolioAllocationAssessment
from agent_trading.services.shadow_bots import (
    AR_SHADOW_RULE_SET_VERSION,
    EI_SHADOW_RULE_SET_VERSION,
    compute_shadow_event_bot,
    compute_shadow_risk_bot,
    risk_score_bucket,
)


def _portfolio_allocation(
    *, remaining_concentration_pct=10.0, remaining_gross_budget_pct=50.0,
) -> PortfolioAllocationAssessment:
    return PortfolioAllocationAssessment(
        target_weight_pct=5.0,
        current_weight_pct=2.0,
        max_single_position_pct=10.0,
        remaining_concentration_pct=remaining_concentration_pct,
        remaining_gross_budget_pct=remaining_gross_budget_pct,
        max_new_capital_pct=5.0,
        orderable_cash=None,
        available_allocation_cash=None,
        recommended_max_order_value=None,
        allocation_bias="neutral",
        confidence=0.5,
    )


def _market_regime(
    *, risk_tone="neutral", volatility_regime="normal_volatility",
) -> MarketRegimeAssessment:
    return MarketRegimeAssessment(
        regime_label="range_bound",
        volatility_regime=volatility_regime,
        risk_tone=risk_tone,
        confidence=0.5,
        half_life_hours=24,
    )


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
    )


class TestRiskScoreBucket:
    def test_boundaries(self) -> None:
        assert risk_score_bucket(0.0) == "0.0-0.2"
        assert risk_score_bucket(0.19) == "0.0-0.2"
        assert risk_score_bucket(0.2) == "0.2-0.4"
        assert risk_score_bucket(0.59) == "0.4-0.6"
        assert risk_score_bucket(0.6) == "0.6-0.8"
        assert risk_score_bucket(0.99) == "0.8-1.0"
        assert risk_score_bucket(1.0) == "0.8-1.0"

    def test_clamps_out_of_range_values(self) -> None:
        assert risk_score_bucket(-5.0) == "0.0-0.2"
        assert risk_score_bucket(5.0) == "0.8-1.0"


class TestComputeShadowRiskBot:
    def test_no_signals_stays_allow(self) -> None:
        result = compute_shadow_risk_bot(
            portfolio_allocation=None,
            market_regime=None,
            deterministic_trigger=None,
        )
        assert result.risk_opinion == "allow"
        assert result.risk_score == 0.0
        assert result.confidence == 1.0
        assert any(
            code.startswith(f"shadow_rule_set:{AR_SHADOW_RULE_SET_VERSION}")
            for code in result.reason_codes
        )

    def test_concentration_over_limit_alone_stays_allow(self) -> None:
        result = compute_shadow_risk_bot(
            portfolio_allocation=_portfolio_allocation(
                remaining_concentration_pct=-1.0,
            ),
            market_regime=None,
            deterministic_trigger=None,
        )
        assert result.risk_score == 0.4
        assert result.risk_opinion == "allow"
        assert "concentration_over_limit" in result.risk_flags
        assert "concentration_over_limit" in result.reason_codes

    def test_concentration_and_cash_issue_escalates_to_review(self) -> None:
        result = compute_shadow_risk_bot(
            portfolio_allocation=_portfolio_allocation(
                remaining_concentration_pct=-1.0,
                remaining_gross_budget_pct=-1.0,
            ),
            market_regime=None,
            deterministic_trigger=None,
        )
        assert result.risk_score == 0.7
        assert result.risk_opinion == "review"
        assert "insufficient_cash" in result.risk_flags

    def test_all_negative_signals_clamp_to_one_and_reject(self) -> None:
        """concentration+cash+regime+volatility 4개 신호가 모두 겹치면
        score가 1.0(clamp)까지 올라가 reject 등급(>=0.9)에 도달한다
        (2026-08-17 PR2에서 reject 등급 추가)."""
        result = compute_shadow_risk_bot(
            portfolio_allocation=_portfolio_allocation(
                remaining_concentration_pct=-1.0,
                remaining_gross_budget_pct=-1.0,
            ),
            market_regime=_market_regime(
                risk_tone="risk_off", volatility_regime="high_volatility",
            ),
            deterministic_trigger=None,
        )
        assert result.risk_score == 1.0
        assert result.risk_opinion == "reject"
        assert "risk_off_regime" in result.risk_flags
        assert "volatility_elevated" in result.risk_flags

    def test_concentration_cash_and_regime_combo_reaches_reject(self) -> None:
        """concentration_over_limit(0.4) + insufficient_cash(0.3) +
        risk_off_regime(0.2) = 0.9 — reject 등급의 대표 예시 조합."""
        result = compute_shadow_risk_bot(
            portfolio_allocation=_portfolio_allocation(
                remaining_concentration_pct=-1.0,
                remaining_gross_budget_pct=-1.0,
            ),
            market_regime=_market_regime(risk_tone="risk_off"),
            deterministic_trigger=None,
        )
        assert result.risk_score == 0.9
        assert result.risk_opinion == "reject"

    def test_healthy_allocation_records_positive_reason_codes(self) -> None:
        result = compute_shadow_risk_bot(
            portfolio_allocation=_portfolio_allocation(),
            market_regime=_market_regime(),
            deterministic_trigger=None,
        )
        assert result.risk_opinion == "allow"
        assert result.risk_score == 0.0
        assert "not_overconcentrated" in result.reason_codes
        assert "sufficient_cash" in result.reason_codes

    def test_event_conflict_from_recent_events_adds_flag(self) -> None:
        result = compute_shadow_risk_bot(
            portfolio_allocation=None,
            market_regime=None,
            deterministic_trigger=None,
            recent_events=(_event("positive"), _event("negative")),
        )
        assert result.risk_score == 0.1
        assert "event_conflict" in result.risk_flags

    def test_no_event_conflict_when_all_same_direction(self) -> None:
        result = compute_shadow_risk_bot(
            portfolio_allocation=None,
            market_regime=None,
            deterministic_trigger=None,
            recent_events=(_event("positive"), _event("positive")),
        )
        assert result.risk_score == 0.0
        assert "event_conflict" not in result.risk_flags

    def test_eligibility_not_passed_adds_reason_code_without_score_change(
        self,
    ) -> None:
        trigger = DeterministicTriggerAssessment(
            trigger_version="deterministic_trigger_v1",
            primary_candidate="NO_ACTION",
            candidate_set=(),
            watch_candidate=False,
            buy_candidate=False,
            sell_candidate=False,
            reduce_candidate=False,
            candidate_confidence=0.0,
            entry_score=None,
            exit_score=None,
            watch_score=None,
            eligibility_passed=False,
            eligibility_reasons=("eligibility_low_average_volume",),
        )
        result = compute_shadow_risk_bot(
            portfolio_allocation=None,
            market_regime=None,
            deterministic_trigger=trigger,
        )
        assert result.risk_score == 0.0
        assert result.risk_opinion == "allow"
        assert "deterministic_eligibility_not_passed" in result.reason_codes


class TestComputeShadowEventBot:
    def test_no_events_is_no_material_events(self) -> None:
        result = compute_shadow_event_bot(())
        assert result.detected_event_count == 0
        assert result.interpreted_event_count == 0
        assert result.event_bias == "neutral"
        assert result.event_conflict is False
        assert result.evidence_strength == "none"
        assert result.no_material_events is True
        assert any(
            code.startswith(f"shadow_rule_set:{EI_SHADOW_RULE_SET_VERSION}")
            for code in result.reason_codes
        )

    def test_single_positive_event_is_weak_evidence(self) -> None:
        result = compute_shadow_event_bot((_event("positive"),))
        assert result.detected_event_count == 1
        assert result.interpreted_event_count == 1
        assert result.event_bias == "positive"
        assert result.event_conflict is False
        assert result.evidence_strength == "weak"
        assert result.no_material_events is False

    def test_mixed_direction_is_conflict(self) -> None:
        result = compute_shadow_event_bot(
            (_event("positive"), _event("negative")),
        )
        assert result.event_conflict is True
        assert result.event_bias == "neutral"

    def test_majority_direction_wins_bias(self) -> None:
        result = compute_shadow_event_bot(
            (_event("positive"), _event("positive"), _event("negative")),
        )
        assert result.event_bias == "positive"
        assert result.event_conflict is True  # 여전히 반대 방향 존재

    def test_t1_source_upgrades_evidence_strength(self) -> None:
        weak = compute_shadow_event_bot((_event("positive", tier="T3"),))
        strong_candidate = compute_shadow_event_bot(
            (_event("positive", tier="T1"),),
        )
        assert weak.evidence_strength == "weak"
        assert strong_candidate.evidence_strength == "moderate"
        assert "t1_source_present" in strong_candidate.reason_codes

    def test_four_or_more_events_is_strong_evidence(self) -> None:
        events = tuple(_event("positive") for _ in range(4))
        result = compute_shadow_event_bot(events)
        assert result.evidence_strength == "strong"
