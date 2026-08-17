"""Tests for the deterministic AI Risk bot.

2026-08-17 결정(PR2): LLM 기반 ``AIRiskAgent``를 실행 경로에서 제거하고,
``DeterministicAIRiskAgent``로 전환했다. EI(PR1)/AC(기존)는 이미
deterministic bot이고, FDC는 LLM으로 유지된다.

이 bot은 ``compute_shadow_risk_bot()``(shadow_bots.py)과 완전히 동일한
계산 로직을 공유하되, reason_codes 마커만 ``deterministic_rule_set:*``로
구분한다. 이번 PR에서 ``reject`` opinion 등급을 신설했다(score>=0.9) —
concentration_over_limit(0.4)+insufficient_cash(0.3)+risk_off_regime(0.2)
= 0.9의 극단 조합이 대표 예시다.

AR의 실제 영향 경로(held_position override/FDC skip/execution risk-off)
자체의 회귀 테스트는 ``test_decision_orchestrator.py``/
``test_held_position_sell_override.py``에서 실제 판정 함수를 통해
검증한다. 이 파일은 순수 계산 결과가 그 판정 함수들이 기대하는
threshold/keyword와 정합적인지만 확인한다.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from agent_trading.services.ai_agents.ai_risk import (
    DeterministicAIRiskAgent,
    _compute_deterministic_ai_risk,
)
from agent_trading.services.ai_agents.base import AgentExecutionRequest
from agent_trading.services.ai_agents.schemas import AIRiskOutput
from agent_trading.services.common_types import AIPolicyContextView
from agent_trading.services.deterministic_trigger_engine import (
    DeterministicTriggerAssessment,
)
from agent_trading.services.market_regime import MarketRegimeAssessment
from agent_trading.services.portfolio_allocation import PortfolioAllocationAssessment
from agent_trading.services.shadow_bots import AR_BOT_RULE_SET_VERSION


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


def _make_request(
    *,
    decision_context_id=None,
    symbol: str = "005930",
    portfolio_allocation=None,
    market_regime=None,
    deterministic_trigger=None,
) -> AgentExecutionRequest:
    return AgentExecutionRequest(
        decision_context_id=decision_context_id or uuid4(),
        correlation_id="ar-deterministic-test",
        context=AIPolicyContextView(
            source_type="core",
            portfolio_allocation=portfolio_allocation,
            market_regime=market_regime,
            deterministic_trigger=deterministic_trigger,
        ),
        symbol=symbol,
        market="KRX",
        source_type="core",
    )


class TestDeterministicAIRiskAgent:
    """``DeterministicAIRiskAgent``는 LLM 호출 없이 항상 값을 반환한다."""

    def test_agent_name_matches_llm_agent_for_compatibility(self) -> None:
        """agent_type 기반 API/UI 필터(``agent_type=="ai_risk"``) 호환을
        위해 agent_name을 그대로 유지해야 한다."""
        agent = DeterministicAIRiskAgent()
        assert agent.agent_name == "ai_risk"
        assert agent.schema_version == "v1"

    @pytest.mark.asyncio
    async def test_run_never_calls_llm_and_returns_ai_risk_output(self) -> None:
        agent = DeterministicAIRiskAgent()
        result = await agent.run(_make_request())
        assert isinstance(result, AIRiskOutput)
        assert result.agent_name == "ai_risk"


class TestComputeDeterministicAiRisk:
    """계산 함수 ``_compute_deterministic_ai_risk()`` 단위 테스트."""

    def test_normal_state_stays_allow_with_low_score(self) -> None:
        output = _compute_deterministic_ai_risk(
            _make_request(
                portfolio_allocation=_portfolio_allocation(),
                market_regime=_market_regime(),
            ),
        )
        assert output.risk_opinion == "allow"
        assert output.risk_score == 0.0
        assert output.confidence == 1.0
        assert output.size_adjustment_factor == 0.0
        assert any(
            code.startswith(f"deterministic_rule_set:{AR_BOT_RULE_SET_VERSION}")
            for code in output.reason_codes
        )

    def test_multiple_risk_signals_escalate_to_review_or_reduce(self) -> None:
        output = _compute_deterministic_ai_risk(
            _make_request(
                portfolio_allocation=_portfolio_allocation(
                    remaining_concentration_pct=-1.0,
                    remaining_gross_budget_pct=-1.0,
                ),
            ),
        )
        assert output.risk_score == 0.7
        assert output.risk_opinion == "review"
        assert output.size_adjustment_factor == 0.2

    def test_extreme_risk_signals_escalate_to_reject(self) -> None:
        """concentration_over_limit(0.4)+insufficient_cash(0.3)+
        risk_off_regime(0.2) = 0.9 -> reject(2026-08-17 PR2 신설 등급)."""
        output = _compute_deterministic_ai_risk(
            _make_request(
                portfolio_allocation=_portfolio_allocation(
                    remaining_concentration_pct=-1.0,
                    remaining_gross_budget_pct=-1.0,
                ),
                market_regime=_market_regime(risk_tone="risk_off"),
            ),
        )
        assert output.risk_score == 0.9
        assert output.risk_opinion == "reject"
        assert output.size_adjustment_factor == 0.8

    def test_deterministic_rule_set_marker_present(self) -> None:
        output = _compute_deterministic_ai_risk(_make_request())
        assert any(
            code == f"deterministic_rule_set:{AR_BOT_RULE_SET_VERSION}"
            for code in output.reason_codes
        )
        assert not any(
            code.startswith("shadow_rule_set:") for code in output.reason_codes
        )

    def test_risk_flags_compatible_with_held_position_exit_promotion_keywords(
        self,
    ) -> None:
        """held_position override(decision_orchestrator.py)의 EXIT 승격
        조건은 risk_flags에 'concent'/'expos'/'over' 부분 문자열이
        있는지로 판정한다 — bot의 concentration_over_limit 플래그가
        이 조건과 호환되는지 확인한다."""
        output = _compute_deterministic_ai_risk(
            _make_request(
                portfolio_allocation=_portfolio_allocation(
                    remaining_concentration_pct=-1.0,
                ),
            ),
        )
        assert "concentration_over_limit" in output.risk_flags
        flags_lower = tuple(f.lower() for f in output.risk_flags)
        assert any(
            "concent" in f or "expos" in f or "over" in f for f in flags_lower
        )

    def test_reject_score_exceeds_fdc_skip_threshold(self) -> None:
        """decision_agent_runner.py._should_skip_final_decision_composer()는
        risk_score>=0.85면 FDC를 skip한다 — reject 등급(>=0.9)은 항상
        이 threshold를 만족해야 한다."""
        output = _compute_deterministic_ai_risk(
            _make_request(
                portfolio_allocation=_portfolio_allocation(
                    remaining_concentration_pct=-1.0,
                    remaining_gross_budget_pct=-1.0,
                ),
                market_regime=_market_regime(
                    risk_tone="risk_off", volatility_regime="high_volatility",
                ),
            ),
        )
        assert output.risk_opinion == "reject"
        assert output.risk_score >= 0.85

    def test_non_allow_opinion_and_high_score_trigger_execution_risk_off(
        self,
    ) -> None:
        """execution_service.py의 risk-off 단주 MARKET 차단 조건은
        risk_opinion != "allow" or risk_score >= 0.6이다 — review 이상
        등급이면 항상 이 조건을 만족해야 한다."""
        output = _compute_deterministic_ai_risk(
            _make_request(
                portfolio_allocation=_portfolio_allocation(
                    remaining_concentration_pct=-1.0,
                    remaining_gross_budget_pct=-1.0,
                ),
            ),
        )
        assert output.risk_opinion == "review"
        risk_off = output.risk_opinion != "allow" or output.risk_score >= 0.6
        assert risk_off is True

    def test_deterministic_trigger_eligibility_failure_adds_reason_code_only(
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
        output = _compute_deterministic_ai_risk(
            _make_request(deterministic_trigger=trigger),
        )
        assert output.risk_score == 0.0
        assert output.risk_opinion == "allow"
        assert "deterministic_eligibility_not_passed" in output.reason_codes

    def test_decision_context_id_and_symbol_propagated(self) -> None:
        ctx_id = uuid4()
        request = _make_request(decision_context_id=ctx_id, symbol="000660")
        output = _compute_deterministic_ai_risk(request)
        assert output.decision_context_id == str(ctx_id)
        assert output.symbol == "000660"
        assert output.agent_name == "ai_risk"

    def test_fdc_relevant_fields_all_populated(self) -> None:
        """FDC가 참조하는 필드가 전부 채워지는지 확인한다
        (final_decision_composer.py:371, 379-384 참조 필드)."""
        output = _compute_deterministic_ai_risk(
            _make_request(
                portfolio_allocation=_portfolio_allocation(
                    remaining_concentration_pct=-1.0,
                ),
            ),
        )
        assert output.risk_opinion in {"allow", "review", "reduce", "reject"}
        assert isinstance(output.risk_score, float)
        assert isinstance(output.size_adjustment_factor, float)
        assert isinstance(output.risk_flags, tuple)
        assert isinstance(output.reason_codes, tuple)
        assert isinstance(output.summary, str) and output.summary
