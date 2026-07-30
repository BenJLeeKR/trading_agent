from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from agent_trading.domain.entities import PositionSnapshotEntity, SignalFeatureSnapshotEntity
from agent_trading.services.deterministic_trigger_engine import (
    assess_deterministic_triggers,
)
from agent_trading.services.market_regime import MarketRegimeAssessment
from agent_trading.services.portfolio_allocation import PortfolioAllocationAssessment
from agent_trading.services.strategy_selection import StrategySelectionAssessment


def _make_signal(
    *,
    overall: str,
    fast: str,
    slow: str,
    shadow_overall_v5: str | None = None,
    shadow_slow_v5: str | None = None,
    average_volume_20d: str | None = "50000",
    average_turnover_20d: str | None = "700000000",
    volume_surge_ratio: str | None = "1.6",
    turnover_surge_ratio: str | None = "1.7",
    sma_20: str | None = "10000",
) -> SignalFeatureSnapshotEntity:
    return SignalFeatureSnapshotEntity(
        signal_feature_snapshot_id=uuid4(),
        instrument_id=uuid4(),
        timeframe="1d",
        snapshot_at=datetime.now(timezone.utc),
        feature_set_version="signal_backbone_v1",
        bar_count=80,
        sma_20=Decimal(sma_20) if sma_20 is not None else None,
        average_volume_20d=(
            Decimal(average_volume_20d) if average_volume_20d is not None else None
        ),
        average_turnover_20d=(
            Decimal(average_turnover_20d)
            if average_turnover_20d is not None else None
        ),
        volume_surge_ratio=(
            Decimal(volume_surge_ratio) if volume_surge_ratio is not None else None
        ),
        turnover_surge_ratio=(
            Decimal(turnover_surge_ratio)
            if turnover_surge_ratio is not None else None
        ),
        overall_score=Decimal(overall),
        fast_score=Decimal(fast),
        slow_score=Decimal(slow),
        component_scores_json={
            "shadow_overall_score_v5": float(
                shadow_overall_v5 if shadow_overall_v5 is not None else overall
            ),
            "shadow_slow_score_v5": float(
                shadow_slow_v5 if shadow_slow_v5 is not None else slow
            ),
        },
    )


def _make_regime(
    *,
    regime_label: str,
    risk_tone: str,
    volatility_regime: str = "normal_volatility",
) -> MarketRegimeAssessment:
    return MarketRegimeAssessment(
        regime_label=regime_label,
        volatility_regime=volatility_regime,
        risk_tone=risk_tone,
        confidence=0.8,
        half_life_hours=24,
        strategy_weights={"swing_momentum": 0.45},
        reason_codes=("regime_test",),
    )


def _make_strategy(*, preferred_strategy: str = "swing_momentum") -> StrategySelectionAssessment:
    return StrategySelectionAssessment(
        preferred_strategy=preferred_strategy,
        allowed_strategies=(preferred_strategy, "event_continuation"),
        preferred_entry_style="LIMIT",
        preferred_time_horizon="swing",
        confidence=0.75,
        reason_codes=("strategy_test",),
        metadata={},
    )


def _make_portfolio(
    *,
    max_new_capital_pct: float,
    current_weight_pct: float | None,
    max_single_position_pct: float = 10.0,
) -> PortfolioAllocationAssessment:
    return PortfolioAllocationAssessment(
        target_weight_pct=8.0,
        current_weight_pct=current_weight_pct,
        max_single_position_pct=max_single_position_pct,
        remaining_concentration_pct=(
            max(0.0, max_single_position_pct - (current_weight_pct or 0.0))
            if current_weight_pct is not None
            else None
        ),
        remaining_gross_budget_pct=55.0,
        max_new_capital_pct=max_new_capital_pct,
        orderable_cash=Decimal("5000000"),
        available_allocation_cash=Decimal("4000000"),
        recommended_max_order_value=Decimal("3000000"),
        allocation_bias="accumulate",
        confidence=0.75,
        reason_codes=("portfolio_test",),
        metadata={},
    )


def test_trigger_engine_builds_buy_candidate_for_bullish_core() -> None:
    result = assess_deterministic_triggers(
        source_type="core",
        signal_feature_snapshot=_make_signal(overall="0.70", fast="0.60", slow="0.65"),
        market_regime=_make_regime(regime_label="bullish_trend", risk_tone="risk_on"),
        strategy_selection=_make_strategy(),
        portfolio_allocation=_make_portfolio(max_new_capital_pct=5.0, current_weight_pct=2.0),
        position_snapshot=None,
    )

    assert result is not None
    assert result.buy_candidate is True
    assert result.primary_candidate == "BUY_CANDIDATE"
    assert "BUY_CANDIDATE" in result.candidate_set
    assert result.eligibility_passed is True
    assert result.coverage_score is not None
    assert result.coverage_score > 0.8
    assert result.ranking_score is not None
    # SPPV-2.138: ranking_score에서 coverage_score 항(0.20*1.0)을 제거해
    # 최댓값이 0.20 낮아짐 — 절대 threshold 기대치만 하향 보정.
    assert result.ranking_score > 0.6
    assert "eligibility_feature_coverage_ok" in result.eligibility_reasons
    assert result.candidate_mode == "relative_surge_v1_instrumented"


def test_trigger_engine_builds_watch_candidate_for_core_setup() -> None:
    result = assess_deterministic_triggers(
        source_type="core",
        signal_feature_snapshot=_make_signal(overall="0.18", fast="0.22", slow="0.15"),
        market_regime=_make_regime(regime_label="range_bound", risk_tone="neutral"),
        strategy_selection=_make_strategy(),
        portfolio_allocation=_make_portfolio(max_new_capital_pct=2.0, current_weight_pct=1.0),
        position_snapshot=None,
    )

    assert result is not None
    assert result.watch_candidate is True
    assert result.primary_candidate == "WATCH"
    assert "WATCH" in result.candidate_set
    assert result.eligibility_passed is True
    assert result.ranking_score is not None


def test_trigger_engine_builds_sell_candidate_for_bearish_held_position() -> None:
    result = assess_deterministic_triggers(
        source_type="held_position",
        signal_feature_snapshot=_make_signal(overall="-0.85", fast="-0.80", slow="-0.70"),
        market_regime=_make_regime(
            regime_label="bearish_trend",
            risk_tone="risk_off",
            volatility_regime="high_volatility",
        ),
        strategy_selection=_make_strategy(preferred_strategy="defensive_low_volatility_rotation"),
        portfolio_allocation=_make_portfolio(max_new_capital_pct=0.0, current_weight_pct=12.0),
        position_snapshot=PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=uuid4(),
            instrument_id=uuid4(),
            quantity=Decimal("10"),
            average_price=Decimal("50000"),
            market_price=Decimal("45000"),
            unrealized_pnl=Decimal("-50000"),
            source_of_truth="broker",
            snapshot_at=datetime.now(timezone.utc),
        ),
    )

    assert result is not None
    assert result.sell_candidate is True
    assert result.primary_candidate == "SELL_CANDIDATE"
    assert "SELL_CANDIDATE" in result.candidate_set
    assert result.eligibility_passed is True
    assert result.ranking_score is not None
    assert "eligibility_position_present" in result.eligibility_reasons


def test_trigger_engine_instruments_buy_eligibility_failure_without_allocation_budget() -> None:
    result = assess_deterministic_triggers(
        source_type="core",
        signal_feature_snapshot=_make_signal(overall="0.30", fast="0.20", slow="0.25"),
        market_regime=_make_regime(regime_label="range_bound", risk_tone="neutral"),
        strategy_selection=_make_strategy(),
        portfolio_allocation=_make_portfolio(max_new_capital_pct=0.0, current_weight_pct=1.0),
        position_snapshot=None,
    )

    assert result is not None
    assert result.eligibility_passed is False
    assert "eligibility_allocation_blocked" in result.eligibility_reasons
    assert result.coverage_score is not None
    assert result.ranking_score is not None


def test_trigger_engine_blocks_low_average_volume_buy_candidate() -> None:
    result = assess_deterministic_triggers(
        source_type="core",
        signal_feature_snapshot=_make_signal(
            overall="0.72",
            fast="0.60",
            slow="0.63",
            average_volume_20d="1200",
            sma_20="10670",
        ),
        market_regime=_make_regime(regime_label="bullish_trend", risk_tone="risk_on"),
        strategy_selection=_make_strategy(),
        portfolio_allocation=_make_portfolio(max_new_capital_pct=5.0, current_weight_pct=2.0),
        position_snapshot=None,
    )

    assert result is not None
    assert result.eligibility_passed is False
    assert result.buy_candidate is False
    assert "eligibility_low_average_volume" in result.eligibility_reasons


def test_trigger_engine_blocks_excessive_turnover_participation() -> None:
    result = assess_deterministic_triggers(
        source_type="core",
        signal_feature_snapshot=_make_signal(
            overall="0.72",
            fast="0.61",
            slow="0.64",
            average_volume_20d="5500",
            sma_20="10000",
        ),
        market_regime=_make_regime(regime_label="bullish_trend", risk_tone="risk_on"),
        strategy_selection=_make_strategy(),
        portfolio_allocation=_make_portfolio(max_new_capital_pct=5.0, current_weight_pct=2.0),
        position_snapshot=None,
    )

    assert result is not None
    assert result.eligibility_passed is False
    assert result.buy_candidate is False
    assert "eligibility_participation_rate_blocked" in result.eligibility_reasons


def test_trigger_engine_blocks_low_relative_activity() -> None:
    result = assess_deterministic_triggers(
        source_type="core",
        signal_feature_snapshot=_make_signal(
            overall="0.72",
            fast="0.61",
            slow="0.64",
            volume_surge_ratio="1.02",
            turnover_surge_ratio="1.03",
        ),
        market_regime=_make_regime(regime_label="bullish_trend", risk_tone="risk_on"),
        strategy_selection=_make_strategy(),
        portfolio_allocation=_make_portfolio(max_new_capital_pct=1.0, current_weight_pct=2.0),
        position_snapshot=None,
    )

    assert result is not None
    assert result.eligibility_passed is False
    assert "eligibility_low_relative_activity" in result.eligibility_reasons


def test_trigger_engine_ranking_reflects_turnover_surge() -> None:
    low = assess_deterministic_triggers(
        source_type="core",
        signal_feature_snapshot=_make_signal(
            overall="0.72",
            fast="0.61",
            slow="0.64",
            volume_surge_ratio="1.20",
            turnover_surge_ratio="1.20",
        ),
        market_regime=_make_regime(regime_label="bullish_trend", risk_tone="risk_on"),
        strategy_selection=_make_strategy(),
        portfolio_allocation=_make_portfolio(max_new_capital_pct=0.5, current_weight_pct=2.0),
        position_snapshot=None,
    )
    high = assess_deterministic_triggers(
        source_type="core",
        signal_feature_snapshot=_make_signal(
            overall="0.72",
            fast="0.61",
            slow="0.64",
            volume_surge_ratio="2.80",
            turnover_surge_ratio="2.90",
        ),
        market_regime=_make_regime(regime_label="bullish_trend", risk_tone="risk_on"),
        strategy_selection=_make_strategy(),
        portfolio_allocation=_make_portfolio(max_new_capital_pct=0.5, current_weight_pct=2.0),
        position_snapshot=None,
    )

    assert low is not None and high is not None
    assert high.ranking_score is not None
    assert low.ranking_score is not None
    assert high.ranking_score > low.ranking_score


def test_trigger_engine_blocks_buy_path_for_reconciliation_overlay() -> None:
    result = assess_deterministic_triggers(
        source_type="reconciliation_overlay",
        signal_feature_snapshot=_make_signal(overall="0.72", fast="0.61", slow="0.64"),
        market_regime=_make_regime(regime_label="bullish_trend", risk_tone="risk_on"),
        strategy_selection=_make_strategy(),
        portfolio_allocation=_make_portfolio(max_new_capital_pct=5.0, current_weight_pct=0.0),
        position_snapshot=None,
    )

    assert result is not None
    assert result.eligibility_passed is False
    assert result.buy_candidate is False
    assert "eligibility_source_type_blocked" in result.eligibility_reasons


def test_trigger_engine_marks_risk_off_exception_eligible_for_strong_core_setup() -> None:
    # SPPV-2.133: relative_activity 案1 적용으로 ranking_score에서
    # 0.10*relative_activity 항이 제거돼, 기존 fixture(turnover=1.60)는
    # _CORE_RISK_OFF_RANKING_MIN_SCORE=0.48 문턱을 더 이상 넘지 못한다.
    # "강한 core setup" 의도를 유지하기 위해 turnover_surge_ratio만 상향.
    result = assess_deterministic_triggers(
        source_type="core",
        signal_feature_snapshot=_make_signal(
            overall="0.28",
            fast="0.58",
            slow="0.02",
            average_volume_20d="250000",
            average_turnover_20d="12000000000",
            volume_surge_ratio="1.45",
            turnover_surge_ratio="2.50",
        ),
        market_regime=_make_regime(
            regime_label="bearish_trend",
            risk_tone="risk_off",
        ),
        strategy_selection=_make_strategy(
            preferred_strategy="defensive_low_volatility_rotation"
        ),
        portfolio_allocation=_make_portfolio(
            max_new_capital_pct=2.5,
            current_weight_pct=0.0,
        ),
        position_snapshot=None,
    )

    assert result is not None
    assert result.risk_off_exception_eligible is True
    assert result.eligibility_passed is True
    assert "eligibility_core_risk_off_guard_pass" in result.eligibility_reasons
    assert "eligibility_risk_off_exception_pass" in result.eligibility_reasons
    assert "eligibility_risk_off_block" not in result.eligibility_reasons


def test_trigger_engine_core_risk_off_ranking_boundary_shifts_by_coverage_score_weight() -> None:
    """SPPV-2.138 A-3안 회귀 테스트.

    `ranking_score`에서 `coverage_score` 항(가중치 0.20)을 제거하고
    `_CORE_RISK_OFF_RANKING_MIN_SCORE`를 `0.48→0.28`로 동일하게 낮췄으므로,
    `coverage_score=1.0`(하드 게이트를 통과한 population의 상시 값)인
    대표 입력에서 실제 판정 경계는 정확히 0.20만큼만 이동하고 그 외에는
    바뀌지 않아야 한다 — 이 값이 하나만 달라도(overall 0.33→0.34) 통과/
    차단이 뒤집히는 좁은 경계를 확인해 "완화가 아니라 무변화 리팩터링"
    임을 코드로 증명한다.
    """
    common_kwargs = dict(
        source_type="core",
        market_regime=_make_regime(regime_label="bearish_trend", risk_tone="risk_off"),
        strategy_selection=_make_strategy(preferred_strategy="defensive_low_volatility_rotation"),
        portfolio_allocation=_make_portfolio(max_new_capital_pct=2.5, current_weight_pct=0.0),
        position_snapshot=None,
    )

    blocked = assess_deterministic_triggers(
        signal_feature_snapshot=_make_signal(
            overall="0.33",
            fast="0.80",
            slow="0.30",
            volume_surge_ratio="1.20",
            turnover_surge_ratio="1.20",
        ),
        **common_kwargs,
    )
    passed = assess_deterministic_triggers(
        signal_feature_snapshot=_make_signal(
            overall="0.34",
            fast="0.80",
            slow="0.30",
            volume_surge_ratio="1.20",
            turnover_surge_ratio="1.20",
        ),
        **common_kwargs,
    )

    assert blocked is not None and passed is not None
    assert blocked.coverage_score == 1.0
    assert passed.coverage_score == 1.0
    assert blocked.ranking_score is not None and blocked.ranking_score < 0.28
    assert passed.ranking_score is not None and passed.ranking_score >= 0.28
    assert "eligibility_core_risk_off_ranking_blocked" in blocked.eligibility_reasons
    assert "eligibility_core_risk_off_ranking_pass" in passed.eligibility_reasons


def test_trigger_engine_keeps_risk_off_block_for_weak_core_setup() -> None:
    result = assess_deterministic_triggers(
        source_type="core",
        signal_feature_snapshot=_make_signal(
            overall="-0.02",
            fast="0.20",
            slow="-0.08",
            average_volume_20d="250000",
            average_turnover_20d="12000000000",
            volume_surge_ratio="1.05",
            turnover_surge_ratio="1.08",
        ),
        market_regime=_make_regime(
            regime_label="bearish_trend",
            risk_tone="risk_off",
        ),
        strategy_selection=_make_strategy(
            preferred_strategy="defensive_low_volatility_rotation"
        ),
        portfolio_allocation=_make_portfolio(
            max_new_capital_pct=2.5,
            current_weight_pct=0.0,
        ),
        position_snapshot=None,
    )

    assert result is not None
    assert result.risk_off_exception_eligible is False
    assert result.eligibility_passed is False
    assert "eligibility_core_risk_off_ranking_blocked" in result.eligibility_reasons
    experiment = result.metadata["core_risk_off_experiment"]
    assert experiment["mode"] == "hard_block_v1"
    assert experiment["shadow_mode"] == "shadow_topk_exception_v2"
    assert experiment["active"] is True
    assert experiment["shadow_top_k_cap"] == 2
    assert experiment["shadow_overall_pass"] is False
    assert experiment["shadow_slow_pass"] is False
    assert experiment["shadow_signal_fail_reasons"] == (
        "shadow_core_risk_off_overall_floor_blocked",
        "shadow_core_risk_off_slow_floor_blocked",
    )
    assert experiment["shadow_floor_bucket"] == "mild_relax"
    assert experiment["shadow_floor_relax_pass"] is True
    assert experiment["shadow_floor_relax_reason_codes"] == (
        "shadow_core_risk_off_floor_mild_relax_pass",
    )
    assert experiment["shadow_floor_relax_v2_bucket"] == "mild_relax"
    assert experiment["shadow_floor_relax_v2_pass"] is True
    assert experiment["shadow_floor_relax_v2_reason_codes"] == (
        "shadow_core_risk_off_floor_v2_mild_relax_pass",
    )
    assert experiment["shadow_floor_relax_v3_bucket"] == "mild_relax"
    assert experiment["shadow_floor_relax_v3_pass"] is True
    assert experiment["shadow_floor_relax_v3_reason_codes"] == (
        "shadow_core_risk_off_floor_v3_mild_relax_pass",
    )
    assert experiment["shadow_floor_relax_v5_bucket"] == "mild_relax"
    assert experiment["shadow_floor_relax_v5_pass"] is True
    assert experiment["shadow_floor_relax_v5_reason_codes"] == (
        "shadow_core_risk_off_floor_v5_mild_relax_pass",
    )
    assert experiment["shadow_entry_observe_pass"] is True
    assert experiment["shadow_topk_candidate"] is False
    assert experiment["shadow_group_size"] is None
    assert experiment["shadow_rank"] is None
    assert experiment["shadow_topk_selected"] is False
    assert experiment["apply_ready"] is False
    assert experiment["shadow_would_pass"] is False


def test_trigger_engine_marks_core_risk_off_shadow_topk_candidate() -> None:
    result = assess_deterministic_triggers(
        source_type="core",
        signal_feature_snapshot=_make_signal(
            overall="0.12",
            fast="0.22",
            slow="0.01",
            average_volume_20d="250000",
            average_turnover_20d="12000000000",
            volume_surge_ratio="1.14",
            turnover_surge_ratio="1.18",
        ),
        market_regime=_make_regime(
            regime_label="bearish_trend",
            risk_tone="risk_off",
        ),
        strategy_selection=_make_strategy(
            preferred_strategy="defensive_low_volatility_rotation"
        ),
        portfolio_allocation=_make_portfolio(
            max_new_capital_pct=2.5,
            current_weight_pct=0.0,
        ),
        position_snapshot=None,
    )

    assert result is not None
    assert result.eligibility_passed is False
    assert "eligibility_core_risk_off_ranking_blocked" in result.eligibility_reasons
    experiment = result.metadata["core_risk_off_experiment"]
    assert experiment["shadow_mode"] == "shadow_topk_exception_v2"
    assert experiment["shadow_overall_pass"] is True
    assert experiment["shadow_slow_pass"] is True
    assert experiment["shadow_signal_fail_reasons"] == ()
    assert experiment["shadow_floor_bucket"] == "strict_pass"
    assert experiment["shadow_floor_relax_pass"] is True
    assert experiment["shadow_floor_relax_v2_bucket"] == "strict_pass"
    assert experiment["shadow_floor_relax_v2_pass"] is True
    assert experiment["shadow_floor_relax_v3_bucket"] == "strict_pass"
    assert experiment["shadow_floor_relax_v3_pass"] is True
    assert experiment["shadow_floor_relax_v5_bucket"] == "strict_pass"
    assert experiment["shadow_floor_relax_v5_pass"] is True
    assert round(experiment["shadow_entry_score"], 4) == result.entry_score
    assert experiment["shadow_entry_observe_pass"] is True
    assert experiment["shadow_topk_candidate"] is True
    assert experiment["shadow_rank_candidate_score"] == round(result.ranking_score or 0.0, 4)
    assert experiment["shadow_activity_min"] == 1.10
    assert experiment["shadow_entry_observe_min"] == 0.05
    assert experiment["shadow_would_pass"] is False


def test_trigger_engine_marks_core_risk_off_shadow_floor_moderate_relax() -> None:
    # SPPV-2.138: ranking_score에서 coverage_score 항(0.20*1.0)이 빠지면서
    # 이 함수 내부에 하드코딩된 관찰용 절대값 `ranking_score>=0.26`(범위 밖,
    # 이번 턴 변경 대상 아님)의 유효 문턱이 사실상 높아졌다. 기존 fixture
    # (overall=-0.22)는 v1/v3만 통과하고 v2는 실패하도록 정교하게 설계돼
    # 있었으나, 그 정도로 낮은 overall에서는 새 ranking_score 상한(약 0.25)
    # 으로 0.26을 넘길 수 없어(대수적으로 재확인) v1/v2/v3 분기 자체가
    # 성립하지 않는다. fixture를 활동성 최대값으로 보정해 v1/v2/v3이 모두
    # moderate_relax로 수렴하는 것으로 갱신한다 — 실제 BUY/eligibility
    # 판정과는 무관한 순수 관찰용 메타데이터 변화다(docs/10_signal_
    # research_sppv/[DESIGN] regime_conditional_entry_signal_v1.md §126).
    result = assess_deterministic_triggers(
        source_type="core",
        signal_feature_snapshot=_make_signal(
            overall="-0.05",
            fast="1.00",
            slow="-0.20",
            average_volume_20d="250000",
            average_turnover_20d="12000000000",
            volume_surge_ratio="1.14",
            turnover_surge_ratio="3.00",
        ),
        market_regime=_make_regime(
            regime_label="bearish_trend",
            risk_tone="risk_off",
        ),
        strategy_selection=_make_strategy(
            preferred_strategy="defensive_low_volatility_rotation"
        ),
        portfolio_allocation=_make_portfolio(
            max_new_capital_pct=2.5,
            current_weight_pct=0.0,
        ),
        position_snapshot=None,
    )

    assert result is not None
    experiment = result.metadata["core_risk_off_experiment"]
    assert experiment["active"] is True
    assert experiment["shadow_floor_bucket"] == "moderate_relax"
    assert experiment["shadow_floor_relax_pass"] is True
    assert experiment["shadow_floor_relax_reason_codes"] == (
        "shadow_core_risk_off_floor_moderate_relax_pass",
    )
    assert experiment["shadow_floor_relax_entry_min"] == 0.12
    assert experiment["shadow_floor_relax_ranking_min"] == 0.26
    assert experiment["shadow_floor_relax_v2_bucket"] == "moderate_relax"
    assert experiment["shadow_floor_relax_v2_pass"] is True
    assert experiment["shadow_floor_relax_v2_reason_codes"] == (
        "shadow_core_risk_off_floor_v2_moderate_relax_pass",
    )
    assert experiment["shadow_floor_relax_v3_bucket"] == "moderate_relax"
    assert experiment["shadow_floor_relax_v3_pass"] is True
    assert experiment["shadow_floor_relax_v3_reason_codes"] == (
        "shadow_core_risk_off_floor_v3_moderate_relax_pass",
    )
    assert experiment["shadow_floor_relax_v5_bucket"] == "moderate_relax"
    assert experiment["shadow_floor_relax_v5_pass"] is True
    assert experiment["shadow_floor_relax_v5_reason_codes"] == (
        "shadow_core_risk_off_floor_v5_moderate_relax_pass",
    )


def test_trigger_engine_marks_core_risk_off_shadow_floor_v2_mild_relax_expansion() -> None:
    result = assess_deterministic_triggers(
        source_type="core",
        signal_feature_snapshot=_make_signal(
            overall="-0.15",
            fast="-1.00",
            slow="-0.15",
            average_volume_20d="250000",
            average_turnover_20d="12000000000",
            volume_surge_ratio="1.14",
            turnover_surge_ratio="1.14",
        ),
        market_regime=_make_regime(
            regime_label="bearish_trend",
            risk_tone="risk_off",
        ),
        strategy_selection=_make_strategy(
            preferred_strategy="defensive_low_volatility_rotation"
        ),
        portfolio_allocation=_make_portfolio(
            max_new_capital_pct=0.1,
            current_weight_pct=0.0,
        ),
        position_snapshot=None,
    )

    assert result is not None
    experiment = result.metadata["core_risk_off_experiment"]
    assert experiment["shadow_floor_bucket"] == "deep_negative"
    assert experiment["shadow_floor_relax_v2_bucket"] == "mild_relax"
    assert experiment["shadow_floor_relax_v2_pass"] is True
    assert experiment["shadow_floor_relax_v2_reason_codes"] == (
        "shadow_core_risk_off_floor_v2_mild_relax_pass",
    )
    assert experiment["shadow_floor_relax_v2_mild_overall_min"] == -0.15
    assert experiment["shadow_floor_relax_v2_mild_slow_min"] == -0.15
    assert experiment["shadow_floor_relax_v2_moderate_overall_min"] == -0.20
    assert experiment["shadow_floor_relax_v2_moderate_slow_min"] == -0.25


def test_trigger_engine_marks_core_risk_off_shadow_floor_v3_mild_relax_expansion() -> None:
    result = assess_deterministic_triggers(
        source_type="core",
        signal_feature_snapshot=_make_signal(
            overall="-0.18",
            fast="-1.00",
            slow="-0.15",
            average_volume_20d="250000",
            average_turnover_20d="12000000000",
            volume_surge_ratio="1.14",
            turnover_surge_ratio="1.14",
        ),
        market_regime=_make_regime(
            regime_label="bearish_trend",
            risk_tone="risk_off",
        ),
        strategy_selection=_make_strategy(
            preferred_strategy="defensive_low_volatility_rotation"
        ),
        portfolio_allocation=_make_portfolio(
            max_new_capital_pct=0.1,
            current_weight_pct=0.0,
        ),
        position_snapshot=None,
    )

    assert result is not None
    experiment = result.metadata["core_risk_off_experiment"]
    assert experiment["shadow_floor_bucket"] == "deep_negative"
    assert experiment["shadow_floor_relax_v2_bucket"] == "deep_negative"
    assert experiment["shadow_floor_relax_v3_bucket"] == "mild_relax"
    assert experiment["shadow_floor_relax_v3_pass"] is True
    assert experiment["shadow_floor_relax_v3_reason_codes"] == (
        "shadow_core_risk_off_floor_v3_mild_relax_pass",
    )
    assert experiment["shadow_floor_relax_v3_mild_overall_min"] == -0.20
    assert experiment["shadow_floor_relax_v3_mild_slow_min"] == -0.15
    assert experiment["shadow_floor_relax_v3_moderate_overall_min"] == -0.25
    assert experiment["shadow_floor_relax_v3_moderate_slow_min"] == -0.25
    assert experiment["shadow_floor_relax_v5_bucket"] == "mild_relax"
    assert experiment["shadow_floor_relax_v5_pass"] is True
    assert experiment["shadow_floor_relax_v5_reason_codes"] == (
        "shadow_core_risk_off_floor_v5_mild_relax_pass",
    )
    assert experiment["shadow_floor_relax_v5_mild_overall_min"] == -0.20
    assert experiment["shadow_floor_relax_v5_mild_slow_min"] == -0.15
    assert experiment["shadow_floor_relax_v5_moderate_overall_min"] == -0.25
    assert experiment["shadow_floor_relax_v5_moderate_slow_min"] == -0.25


def test_trigger_engine_uses_shadow_v5_scores_for_floor_bucket() -> None:
    result = assess_deterministic_triggers(
        source_type="core",
        signal_feature_snapshot=_make_signal(
            overall="-0.40",
            fast="-1.00",
            slow="-0.40",
            shadow_overall_v5="-0.18",
            shadow_slow_v5="-0.14",
            average_volume_20d="250000",
            average_turnover_20d="12000000000",
            volume_surge_ratio="1.14",
            turnover_surge_ratio="1.14",
        ),
        market_regime=_make_regime(
            regime_label="bearish_trend",
            risk_tone="risk_off",
        ),
        strategy_selection=_make_strategy(
            preferred_strategy="defensive_low_volatility_rotation"
        ),
        portfolio_allocation=_make_portfolio(
            max_new_capital_pct=0.1,
            current_weight_pct=0.0,
        ),
        position_snapshot=None,
    )

    assert result is not None
    experiment = result.metadata["core_risk_off_experiment"]
    assert experiment["shadow_floor_bucket"] == "deep_negative"
    assert experiment["shadow_floor_relax_v5_bucket"] == "mild_relax"
    assert experiment["shadow_floor_relax_v5_pass"] is True
    assert experiment["shadow_overall_score_v5"] == -0.18
    assert experiment["shadow_slow_score_v5"] == -0.14


def test_trigger_engine_applies_core_risk_off_topk_override_for_selected_candidate() -> None:
    result = assess_deterministic_triggers(
        source_type="core",
        signal_feature_snapshot=_make_signal(
            overall="0.12",
            fast="0.22",
            slow="0.01",
            average_volume_20d="250000",
            average_turnover_20d="12000000000",
            volume_surge_ratio="1.14",
            turnover_surge_ratio="1.18",
        ),
        market_regime=_make_regime(
            regime_label="bearish_trend",
            risk_tone="risk_off",
        ),
        strategy_selection=_make_strategy(
            preferred_strategy="defensive_low_volatility_rotation"
        ),
        portfolio_allocation=_make_portfolio(
            max_new_capital_pct=2.5,
            current_weight_pct=0.0,
        ),
        position_snapshot=None,
        deterministic_trigger_override={
            "core_risk_off_topk_v1": {
                "selected": True,
                "path": "core_risk_off_topk_v1",
                "shadow_rank": 1,
                "shadow_group_size": 2,
            }
        },
    )

    assert result is not None
    assert result.eligibility_passed is True
    assert result.risk_off_exception_eligible is True
    assert "eligibility_core_risk_off_topk_override_pass" in result.eligibility_reasons
    assert "eligibility_core_risk_off_ranking_blocked" not in result.eligibility_reasons
    experiment = result.metadata["core_risk_off_experiment"]
    assert experiment["apply_selected"] is True
    assert experiment["apply_ready"] is True
    assert experiment["risk_off_exception_path"] == "core_risk_off_topk_v1"
    assert experiment["shadow_rank"] == 1
    assert experiment["shadow_group_size"] == 2


def test_trigger_engine_topk_override_does_not_bypass_low_relative_activity() -> None:
    result = assess_deterministic_triggers(
        source_type="core",
        signal_feature_snapshot=_make_signal(
            overall="0.12",
            fast="0.22",
            slow="0.01",
            average_volume_20d="250000",
            average_turnover_20d="12000000000",
            volume_surge_ratio="1.05",
            turnover_surge_ratio="1.06",
        ),
        market_regime=_make_regime(
            regime_label="bearish_trend",
            risk_tone="risk_off",
        ),
        strategy_selection=_make_strategy(
            preferred_strategy="defensive_low_volatility_rotation"
        ),
        portfolio_allocation=_make_portfolio(
            max_new_capital_pct=2.5,
            current_weight_pct=0.0,
        ),
        position_snapshot=None,
        deterministic_trigger_override={
            "core_risk_off_topk_v1": {
                "selected": True,
                "path": "core_risk_off_topk_v1",
            }
        },
    )

    assert result is not None
    assert result.risk_off_exception_eligible is False
    assert result.eligibility_passed is False
    assert "eligibility_core_risk_off_activity_blocked" in result.eligibility_reasons


def test_trigger_engine_keeps_event_overlay_on_regime_pass_path_under_risk_off() -> None:
    result = assess_deterministic_triggers(
        source_type="event_overlay",
        signal_feature_snapshot=_make_signal(
            overall="0.24",
            fast="0.55",
            slow="0.01",
            average_volume_20d="180000",
            average_turnover_20d="8000000000",
            volume_surge_ratio="1.35",
            turnover_surge_ratio="1.42",
        ),
        market_regime=_make_regime(
            regime_label="bearish_trend",
            risk_tone="risk_off",
        ),
        strategy_selection=_make_strategy(
            preferred_strategy="event_continuation"
        ),
        portfolio_allocation=_make_portfolio(
            max_new_capital_pct=2.5,
            current_weight_pct=0.0,
        ),
        position_snapshot=None,
    )

    assert result is not None
    assert result.risk_off_exception_eligible is False
    assert result.eligibility_passed is False
    assert "eligibility_risk_off_block" in result.eligibility_reasons
    assert "eligibility_risk_off_exception_pass" not in result.eligibility_reasons
    experiment = result.metadata["event_overlay_experiment"]
    assert experiment["mode"] == "no_bonus_v1"
    assert experiment["shadow_mode"] == "shadow_event_lane_v1"
    assert experiment["active"] is True
    assert experiment["base_eligibility_passed"] is False
    assert experiment["shadow_would_pass"] is False
    assert experiment["apply_ready"] is False


def test_trigger_engine_instruments_event_overlay_shadow_lane_metadata() -> None:
    # SPPV-2.138: ranking_score에서 coverage_score 항(0.20*1.0)이 빠지면서
    # 이 경로 전용 관찰용 절대값 `_EVENT_OVERLAY_SHADOW_MIN_SCORE=0.56`
    # (범위 밖, 이번 턴 변경 대상 아님)의 유효 문턱이 사실상 높아졌다.
    # 기존 fixture는 새 ranking_score로 shadow_would_pass 기준을 넘지
    # 못해, 신호 강도(overall/fast/slow)만 최소한으로 상향해 기존 검증
    # 의도(shadow lane 메타데이터가 정상적으로 채워지는지)를 유지한다 —
    # 실제 BUY/eligibility 판정과는 무관한 순수 관찰용 메타데이터 변화다
    # (docs/10_signal_research_sppv/[DESIGN] regime_conditional_entry_
    # signal_v1.md §126).
    result = assess_deterministic_triggers(
        source_type="event_overlay",
        signal_feature_snapshot=_make_signal(
            overall="0.70",
            fast="0.90",
            slow="0.50",
            average_volume_20d="220000",
            average_turnover_20d="9500000000",
            volume_surge_ratio="1.42",
            turnover_surge_ratio="3.00",
        ),
        market_regime=_make_regime(
            regime_label="event_driven_unstable",
            risk_tone="neutral",
        ),
        strategy_selection=_make_strategy(
            preferred_strategy="event_continuation"
        ),
        portfolio_allocation=_make_portfolio(
            max_new_capital_pct=2.5,
            current_weight_pct=0.0,
        ),
        position_snapshot=None,
    )

    assert result is not None
    assert result.eligibility_passed is True
    experiment = result.metadata["event_overlay_experiment"]
    assert experiment["mode"] == "no_bonus_v1"
    assert experiment["shadow_mode"] == "shadow_event_lane_v1"
    assert experiment["active"] is True
    assert experiment["base_eligibility_passed"] is True
    assert experiment["shadow_top_k_cap"] == 2
    assert experiment["adjusted_ranking_score"] is not None
    assert experiment["shadow_signal_pass"] is True
    assert experiment["shadow_activity_pass"] is True
    assert experiment["shadow_strategy_pass"] is True
    assert experiment["shadow_would_pass"] is True
    assert experiment["apply_ready"] is False
