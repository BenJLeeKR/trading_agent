from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from agent_trading.domain.entities import PositionSnapshotEntity, SignalFeatureSnapshotEntity
from agent_trading.services.deterministic_trigger_engine import (
    _build_buy_ranking_score,
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
    # SPPV-2.159: 이 fixture는 regime_label="bullish_trend"+risk_tone=
    # "risk_on"이라 옛 regime_tailwind=1.0(가중치 0.03)이 반영돼 있었다.
    # 항 제거로 ranking_score가 그만큼(0.03) 더 낮아져 threshold 기대치도
    # 함께 하향 보정한다.
    # §13.2.5: entry_score에서 자본 보너스/패널티 항을 제거해 entry_score가
    # 낮아지면서(이 fixture는 max_new_capital_pct=5.0, Δ=0.05) ranking_score
    # 도 0.55*0.05=0.0275만큼 더 낮아졌다 — 절대 threshold 기대치만 하향
    # 보정한다(buy_candidate는 여전히 True로 무변화).
    assert result.ranking_score > 0.53
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
    # §13.2.5: entry_score에서 자본 보너스/패널티 항을 제거해 entry_score가
    # 낮아지면서(0.4725→0.4475) authoritative 게이트 점수(0.55*entry_score
    # +0.10*allocation_bonus_like)가 0.28 문턱 아래로 내려갔다. "강한 core
    # setup" 의도를 유지하기 위해 overall만 상향 보정한다(경계값만 조정,
    # 게이트 코드/threshold 자체는 무변화).
    result = assess_deterministic_triggers(
        source_type="core",
        signal_feature_snapshot=_make_signal(
            overall="0.45",
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

    §13.2.5: entry_score에서 자본 보너스/패널티 항을 제거해 entry_score가
    일률적으로 낮아지면서(이 fixture는 max_new_capital_pct=2.5로 고정,
    Δ=0.025) authoritative 게이트 점수도 함께 낮아져 경계가 이동했다.
    좁은 경계 자체를 다시 실측해 blocked/passed 값을 재조정했다(overall
    0.33/0.34 → 0.44/0.45) — 게이트 코드/threshold(0.28)는 무변화다.

    §13.2.9/§13.2.10: `risk_off` soft penalty를 `-0.15 → -0.05`로
    완화해 entry_score가 이 fixture 기준 0.10만큼 다시 높아지면서
    경계가 재차 이동했다. 좁은 경계를 다시 실측해 blocked/passed
    값을 재조정했다(overall 0.44/0.45 → 0.00/0.02) — 하드 게이트
    코드/threshold(0.28)는 여전히 무변화다.
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
            overall="0.00",
            fast="0.80",
            slow="0.30",
            volume_surge_ratio="1.20",
            turnover_surge_ratio="1.20",
        ),
        **common_kwargs,
    )
    passed = assess_deterministic_triggers(
        signal_feature_snapshot=_make_signal(
            overall="0.02",
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


def test_trigger_engine_core_risk_off_authoritative_score_matches_ranking_score_formula() -> None:
    """§13.1.6 2차 수정 회귀 테스트.

    `_assess_core_risk_off_buy_guard()`는 이제 `_build_buy_ranking_score()`를
    재호출하지 않고 게이트 안에서 entry_score + allocation 보조 조건을
    직접 계산한다. 두 계산식이 서로 다른 코드 경로로 분리됐으므로, 이
    테스트는 `result.ranking_score`(`_build_buy_ranking_score()`가 만든
    값)와 `_build_buy_ranking_score(entry_score=result.entry_score,
    portfolio_allocation=...)`를 직접 재계산한 값이 여전히 일치하고,
    그 값과 authoritative 게이트의 통과/차단 판정(0.28 경계)이 어긋나지
    않는지 pass/blocked 경계 양쪽에서 고정한다 — 이 두 계산식 중
    하나만 바뀌고 다른 하나가 그대로면 이 테스트가 실패해야 한다.

    §13.2.5: entry_score에서 자본 보너스/패널티 항을 제거해 경계가
    이동했으므로(overall 0.33/0.34 → 0.44/0.45, 위 boundary 테스트와
    동일한 재실측 근거), fixture를 함께 갱신했다.

    §13.2.9/§13.2.10: `risk_off` soft penalty를 `-0.15 → -0.05`로
    완화해 경계가 재차 이동했으므로(overall 0.44/0.45 → 0.00/0.02,
    위 boundary 테스트와 동일한 재실측 근거), fixture를 함께 갱신했다.
    """
    portfolio_allocation = _make_portfolio(max_new_capital_pct=2.5, current_weight_pct=0.0)
    common_kwargs = dict(
        source_type="core",
        market_regime=_make_regime(regime_label="bearish_trend", risk_tone="risk_off"),
        strategy_selection=_make_strategy(preferred_strategy="defensive_low_volatility_rotation"),
        portfolio_allocation=portfolio_allocation,
        position_snapshot=None,
    )

    passed = assess_deterministic_triggers(
        signal_feature_snapshot=_make_signal(
            overall="0.02",
            fast="0.80",
            slow="0.30",
            volume_surge_ratio="1.20",
            turnover_surge_ratio="1.20",
        ),
        **common_kwargs,
    )
    blocked = assess_deterministic_triggers(
        signal_feature_snapshot=_make_signal(
            overall="0.00",
            fast="0.80",
            slow="0.30",
            volume_surge_ratio="1.20",
            turnover_surge_ratio="1.20",
        ),
        **common_kwargs,
    )

    assert passed is not None and blocked is not None
    for result, expect_pass in ((passed, True), (blocked, False)):
        recomputed_ranking_score = _build_buy_ranking_score(
            entry_score=result.entry_score,
            portfolio_allocation=portfolio_allocation,
        )
        # result.entry_score/ranking_score는 저장 시 각각 4자리로 반올림되므로
        # (round(entry_score, 4), round(ranking_score, 4)), 반올림 오차를
        # 감안한 허용치를 둔다.
        assert result.ranking_score == pytest.approx(recomputed_ranking_score, abs=1e-3)
        if expect_pass:
            assert "eligibility_core_risk_off_ranking_pass" in result.eligibility_reasons
            assert result.ranking_score >= 0.28
        else:
            assert "eligibility_core_risk_off_ranking_blocked" in result.eligibility_reasons
            assert result.ranking_score < 0.28


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
    # §13.2.5: entry_score에서 자본 보너스/패널티 항을 제거해 entry_score/
    # ranking_score가 다시 낮아지면서(이 fixture는 max_new_capital_pct=2.5
    # 고정, Δ=0.025) `ranking_score>=0.26` 관찰용 절대값을 더 이상 넘지
    # 못했다. overall만 소폭 상향(-0.05→0.00)해 moderate_relax 분기 의도를
    # 유지한다 — 실제 BUY/eligibility 판정과는 무관한 순수 관찰용 메타데이터
    # 재조정이다.
    result = assess_deterministic_triggers(
        source_type="core",
        signal_feature_snapshot=_make_signal(
            overall="0.00",
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
    # SPPV-2.159: regime_tailwind(0.03*regime_tailwind) 항 제거로
    # ranking_score가 추가로 0.015(neutral 계층 값 0.5 기준) 낮아져
    # shadow_would_pass 기준을 다시 넘지 못하게 됐다 — 신호 강도(overall)
    # 만 최소한으로 상향해 기존 검증 의도(shadow lane 메타데이터가 정상적
    # 으로 채워지는지)를 유지한다. 실제 BUY/eligibility 판정과는 무관한
    # 순수 관찰용 메타데이터 변화다(docs/10_signal_research_sppv/[DESIGN]
    # regime_conditional_entry_signal_v1.md §126/§146).
    # §13.2.5: entry_score에서 자본 보너스/패널티 항을 제거해 entry_score/
    # ranking_score가 다시 낮아지면서(이 fixture는 max_new_capital_pct=2.5
    # 고정, Δ=0.025) `_EVENT_OVERLAY_SHADOW_MIN_SCORE=0.56` 기준을 다시
    # 넘지 못했다. overall만 추가로 상향(0.75→0.90)해 기존 검증 의도(shadow
    # lane 메타데이터가 정상적으로 채워지는지)를 유지한다 — 실제 BUY/
    # eligibility 판정과는 무관한 순수 관찰용 메타데이터 재조정이다.
    result = assess_deterministic_triggers(
        source_type="event_overlay",
        signal_feature_snapshot=_make_signal(
            overall="0.90",
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


def test_trigger_engine_strategy_alignment_removed_from_ranking_kept_in_entry() -> None:
    """SPPV-2.147 — `strategy_alignment`가 ranking_score에서만 빠졌는지 고정.

    `_build_entry_score()`의 `+0.05`는 유지되고 `_build_buy_ranking_score()`의
    직접항 `0.02`만 제거됐으므로, `preferred_strategy`만 바꾼 두 입력을 비교하면
    ``ranking_score`` 차이가 ``entry_score`` 차이의 정확히 0.55배여야 한다
    (제거 전이라면 여기에 0.02가 더 붙는다).

    주의: 이 항은 "죽은 항"이 아니다 — `event_overlay` 경로에서는 실제로
    발동 중이며(SPPV-2.146 §134.2), 제거 근거는 entry_score와의 직접 중복이다.
    """
    common = dict(
        source_type="core",
        signal_feature_snapshot=_make_signal(overall="0.70", fast="0.60", slow="0.65"),
        market_regime=_make_regime(regime_label="bullish_trend", risk_tone="risk_on"),
        portfolio_allocation=_make_portfolio(max_new_capital_pct=5.0, current_weight_pct=2.0),
        position_snapshot=None,
    )
    aligned = assess_deterministic_triggers(
        strategy_selection=_make_strategy(preferred_strategy="swing_momentum"),
        **common,
    )
    not_aligned = assess_deterministic_triggers(
        strategy_selection=_make_strategy(preferred_strategy="mean_reversion_bounce"),
        **common,
    )

    assert aligned is not None and not_aligned is not None
    # entry_score 쪽 +0.05는 그대로 살아 있다.
    assert "trigger_strategy_alignment" in aligned.reason_codes
    assert "trigger_strategy_alignment" not in not_aligned.reason_codes
    assert aligned.entry_score is not None and not_aligned.entry_score is not None
    entry_delta = aligned.entry_score - not_aligned.entry_score
    assert round(entry_delta, 4) == 0.05

    # ranking_score 차이는 entry_score 경유분(0.55배)뿐이어야 한다.
    assert aligned.ranking_score is not None and not_aligned.ranking_score is not None
    ranking_delta = aligned.ranking_score - not_aligned.ranking_score
    assert round(ranking_delta, 4) == round(0.55 * entry_delta, 4)


def test_build_buy_ranking_score_has_no_regime_tailwind_term() -> None:
    """SPPV-2.159 — `regime_tailwind`(0.03*regime_tailwind) 제거 고정.

    SPPV-2.157/§144 선행 검증(판정 A)에서 확인한 대로, `_build_buy_
    ranking_score()`는 더 이상 `market_regime`을 받지 않으며
    `entry_score`와 `allocation_quality`만으로 값이 결정된다 — 제거
    전이라면 `market_regime`에 따라 최대 0.03의 차이가 났을 것이다.
    `assess_deterministic_triggers()` 레벨에서 직접 비교하면
    `market_regime`이 `entry_score`에도 별도 영향(risk_off 페널티 등)을
    주어 확인이 오염되므로, 이 함수만 단독으로 고정한다.
    """
    portfolio_allocation = _make_portfolio(max_new_capital_pct=5.0, current_weight_pct=2.0)

    score = _build_buy_ranking_score(
        entry_score=0.70,
        portfolio_allocation=portfolio_allocation,
    )

    # market_regime 인자가 시그니처에서 완전히 제거됐는지도 함께 고정한다.
    with pytest.raises(TypeError):
        _build_buy_ranking_score(  # type: ignore[call-arg]
            entry_score=0.70,
            market_regime=_make_regime(regime_label="bullish_trend", risk_tone="risk_on"),
            portfolio_allocation=portfolio_allocation,
        )

    assert round(score, 4) == round(0.55 * 0.70 + 0.10 * 0.50, 4)


def test_trigger_engine_buy_candidate_path_intact_after_strategy_alignment_removal() -> None:
    """SPPV-2.147 — 기본 BUY 판정 경로가 깨지지 않았는지 고정."""
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
    assert result.eligibility_passed is True
    assert result.ranking_score is not None
