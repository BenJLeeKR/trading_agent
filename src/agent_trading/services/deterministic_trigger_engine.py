from __future__ import annotations

from dataclasses import dataclass, field

from agent_trading.domain.entities import PositionSnapshotEntity, SignalFeatureSnapshotEntity
from agent_trading.services.market_regime import MarketRegimeAssessment
from agent_trading.services.portfolio_allocation import PortfolioAllocationAssessment
from agent_trading.services.strategy_selection import StrategySelectionAssessment

_CORE_RISK_OFF_RANKING_MODE = "hard_block_v1"
_CORE_RISK_OFF_SHADOW_MODE = "shadow_topk_exception_v2"
_CORE_RISK_OFF_RANKING_MIN_SCORE = 0.48
_CORE_RISK_OFF_SHADOW_MIN_SCORE = 0.22
_CORE_RISK_OFF_SHADOW_TOP_K_CAP = 2
_CORE_RISK_OFF_SHADOW_ACTIVITY_MIN = 1.10
_CORE_RISK_OFF_SHADOW_ENTRY_OBSERVE_MIN = 0.05
_CORE_RISK_OFF_SHADOW_V2_MILD_OVERALL_MIN = -0.15
_CORE_RISK_OFF_SHADOW_V2_MILD_SLOW_MIN = -0.15
_CORE_RISK_OFF_SHADOW_V2_MODERATE_OVERALL_MIN = -0.20
_CORE_RISK_OFF_SHADOW_V2_MODERATE_SLOW_MIN = -0.25
_CORE_RISK_OFF_SHADOW_V3_MILD_OVERALL_MIN = -0.20
_CORE_RISK_OFF_SHADOW_V3_MILD_SLOW_MIN = -0.15
_CORE_RISK_OFF_SHADOW_V3_MODERATE_OVERALL_MIN = -0.25
_CORE_RISK_OFF_SHADOW_V3_MODERATE_SLOW_MIN = -0.25
_EVENT_OVERLAY_MODE = "no_bonus_v1"
_EVENT_OVERLAY_SHADOW_MODE = "shadow_event_lane_v1"
_EVENT_OVERLAY_SHADOW_BONUS = 0.06
_EVENT_OVERLAY_SHADOW_MIN_SCORE = 0.56
_EVENT_OVERLAY_SHADOW_ENTRY_MIN_SCORE = 0.54
_EVENT_OVERLAY_SHADOW_TOP_K_CAP = 2


@dataclass(slots=True, frozen=True)
class DeterministicTriggerAssessment:
    """정량 feature 기반 후보 생성 결과."""

    trigger_version: str
    primary_candidate: str
    candidate_set: tuple[str, ...]
    watch_candidate: bool
    buy_candidate: bool
    sell_candidate: bool
    reduce_candidate: bool
    candidate_confidence: float
    entry_score: float | None
    exit_score: float | None
    watch_score: float | None
    eligibility_passed: bool = False
    eligibility_reasons: tuple[str, ...] = ()
    coverage_score: float | None = None
    ranking_score: float | None = None
    ranking_percentile: float | None = None
    ranking_bucket: str | None = None
    candidate_mode: str = "absolute_threshold_v1"
    risk_off_exception_eligible: bool = False
    reason_codes: tuple[str, ...] = ()
    thresholds: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)


def assess_deterministic_triggers(
    *,
    source_type: str,
    signal_feature_snapshot: SignalFeatureSnapshotEntity | None,
    market_regime: MarketRegimeAssessment | None,
    strategy_selection: StrategySelectionAssessment | None,
    portfolio_allocation: PortfolioAllocationAssessment | None,
    position_snapshot: PositionSnapshotEntity | None,
    deterministic_trigger_override: dict[str, object] | None = None,
) -> DeterministicTriggerAssessment | None:
    """기존 deterministic 파생값을 이용해 후보를 생성한다."""
    if (
        signal_feature_snapshot is None
        and market_regime is None
        and strategy_selection is None
        and portfolio_allocation is None
    ):
        return None

    normalized_source_type = (source_type or "core").strip().lower()
    core_risk_off_topk_override = _normalize_core_risk_off_topk_override(
        deterministic_trigger_override
    )
    thresholds = {
        "buy_candidate_threshold": 0.65,
        "watch_candidate_threshold": 0.45,
        "reduce_candidate_threshold": 0.60,
        "sell_candidate_threshold": 0.75,
        "core_risk_off_ranking_min_score": _CORE_RISK_OFF_RANKING_MIN_SCORE,
        "core_risk_off_shadow_min_score": _CORE_RISK_OFF_SHADOW_MIN_SCORE,
        "core_risk_off_shadow_top_k_cap": float(_CORE_RISK_OFF_SHADOW_TOP_K_CAP),
        "core_risk_off_shadow_activity_min": _CORE_RISK_OFF_SHADOW_ACTIVITY_MIN,
        "event_overlay_shadow_bonus": _EVENT_OVERLAY_SHADOW_BONUS,
        "event_overlay_shadow_min_score": _EVENT_OVERLAY_SHADOW_MIN_SCORE,
        "event_overlay_shadow_entry_min_score": _EVENT_OVERLAY_SHADOW_ENTRY_MIN_SCORE,
        "event_overlay_shadow_top_k_cap": float(_EVENT_OVERLAY_SHADOW_TOP_K_CAP),
    }
    reason_codes: list[str] = [f"trigger_source_{normalized_source_type}"]

    overall = _float_or_none(
        signal_feature_snapshot.overall_score if signal_feature_snapshot else None
    )
    fast = _float_or_none(
        signal_feature_snapshot.fast_score if signal_feature_snapshot else None
    )
    slow = _float_or_none(
        signal_feature_snapshot.slow_score if signal_feature_snapshot else None
    )

    entry_score = _build_entry_score(
        overall=overall,
        fast=fast,
        slow=slow,
        signal_feature_snapshot=signal_feature_snapshot,
        market_regime=market_regime,
        strategy_selection=strategy_selection,
        portfolio_allocation=portfolio_allocation,
        source_type=normalized_source_type,
        reason_codes=reason_codes,
    )
    exit_score = _build_exit_score(
        overall=overall,
        fast=fast,
        slow=slow,
        market_regime=market_regime,
        portfolio_allocation=portfolio_allocation,
        position_snapshot=position_snapshot,
        source_type=normalized_source_type,
        reason_codes=reason_codes,
    )
    watch_score = _build_watch_score(
        entry_score=entry_score,
        exit_score=exit_score,
        source_type=normalized_source_type,
        position_snapshot=position_snapshot,
        reason_codes=reason_codes,
    )
    coverage_score = _build_feature_coverage_score(
        signal_feature_snapshot=signal_feature_snapshot,
        market_regime=market_regime,
        strategy_selection=strategy_selection,
        portfolio_allocation=portfolio_allocation,
    )

    buy_candidate = False
    sell_candidate = False
    reduce_candidate = False
    watch_candidate = False
    candidate_set: list[str] = []
    risk_off_exception_eligible = False
    core_risk_off_guard_active = False
    core_risk_off_guard_reasons: tuple[str, ...] = ()

    allocation_budget_ok = (
        portfolio_allocation is None
        or portfolio_allocation.max_new_capital_pct > 0
    )
    has_position = (
        position_snapshot is not None
        and position_snapshot.quantity is not None
        and position_snapshot.quantity > 0
    )
    if normalized_source_type == "held_position":
        eligibility_passed, eligibility_reasons = _assess_exit_eligibility(
            coverage_score=coverage_score,
            has_position=has_position,
            position_snapshot=position_snapshot,
            exit_score=exit_score,
        )
        ranking_score = _build_exit_ranking_score(
            exit_score=exit_score,
            coverage_score=coverage_score,
            market_regime=market_regime,
            portfolio_allocation=portfolio_allocation,
            has_position=has_position,
        )
    else:
        core_risk_off_guard_active = _is_core_risk_off_regime(
            source_type=normalized_source_type,
            market_regime=market_regime,
        )
        ranking_score = _build_buy_ranking_score(
            entry_score=entry_score,
            coverage_score=coverage_score,
            signal_feature_snapshot=signal_feature_snapshot,
            market_regime=market_regime,
            portfolio_allocation=portfolio_allocation,
            strategy_selection=strategy_selection,
        )
        if core_risk_off_guard_active:
            (
                risk_off_exception_eligible,
                core_risk_off_guard_reasons,
            ) = _assess_core_risk_off_buy_guard(
                signal_feature_snapshot=signal_feature_snapshot,
                overall=overall,
                slow=slow,
                ranking_score=ranking_score,
                strategy_selection=strategy_selection,
                apply_topk_override_selected=bool(
                    core_risk_off_topk_override.get("selected")
                ),
            )
        eligibility_passed, eligibility_reasons = _assess_buy_eligibility(
            source_type=normalized_source_type,
            coverage_score=coverage_score,
            allocation_budget_ok=allocation_budget_ok,
            market_regime=market_regime,
            overall=overall,
            slow=slow,
            signal_feature_snapshot=signal_feature_snapshot,
            portfolio_allocation=portfolio_allocation,
            ranking_score=ranking_score,
            risk_off_exception_eligible=risk_off_exception_eligible,
            core_risk_off_guard_reasons=core_risk_off_guard_reasons,
        )

    if normalized_source_type == "held_position":
        if exit_score >= thresholds["sell_candidate_threshold"]:
            sell_candidate = True
            candidate_set.append("SELL_CANDIDATE")
            reason_codes.append("trigger_sell_candidate")
        elif exit_score >= thresholds["reduce_candidate_threshold"]:
            reduce_candidate = True
            candidate_set.append("REDUCE_CANDIDATE")
            reason_codes.append("trigger_reduce_candidate")
        elif watch_score >= thresholds["watch_candidate_threshold"]:
            watch_candidate = True
            candidate_set.append("WATCH")
            reason_codes.append("trigger_held_position_watch")
    else:
        if (
            eligibility_passed
            and entry_score >= thresholds["buy_candidate_threshold"]
            and allocation_budget_ok
        ):
            buy_candidate = True
            candidate_set.append("BUY_CANDIDATE")
            reason_codes.append("trigger_buy_candidate")
        if watch_score >= thresholds["watch_candidate_threshold"]:
            watch_candidate = True
            candidate_set.append("WATCH")
            reason_codes.append("trigger_watch_candidate")

    if not has_position and normalized_source_type == "held_position":
        candidate_set.clear()
        watch_candidate = False
        sell_candidate = False
        reduce_candidate = False
        reason_codes.append("trigger_no_position_clear")

    if not candidate_set:
        candidate_set.append("NO_ACTION")
        reason_codes.append("trigger_no_action")

    primary_candidate = candidate_set[0]
    confidence_values = [entry_score, exit_score, watch_score]
    confidence = max(value for value in confidence_values if value is not None)

    metadata = {
        "source_type": normalized_source_type,
        "has_position": has_position,
        "allocation_budget_ok": allocation_budget_ok,
        "regime_label": market_regime.regime_label if market_regime else None,
        "risk_tone": market_regime.risk_tone if market_regime else None,
        "preferred_strategy": (
            strategy_selection.preferred_strategy
            if strategy_selection is not None
            else None
        ),
        "average_volume_20d": (
            str(signal_feature_snapshot.average_volume_20d)
            if signal_feature_snapshot is not None
            and signal_feature_snapshot.average_volume_20d is not None
            else None
        ),
        "average_turnover_20d": (
            str(signal_feature_snapshot.average_turnover_20d)
            if signal_feature_snapshot is not None
            and signal_feature_snapshot.average_turnover_20d is not None
            else None
        ),
        "volume_surge_ratio": (
            str(signal_feature_snapshot.volume_surge_ratio)
            if signal_feature_snapshot is not None
            and signal_feature_snapshot.volume_surge_ratio is not None
            else None
        ),
        "turnover_surge_ratio": (
            str(signal_feature_snapshot.turnover_surge_ratio)
            if signal_feature_snapshot is not None
            and signal_feature_snapshot.turnover_surge_ratio is not None
            else None
        ),
        "liquidity_reference_price": (
            _estimate_liquidity_reference_price(signal_feature_snapshot)
        ),
        "recommended_max_order_value": (
            str(portfolio_allocation.recommended_max_order_value)
            if portfolio_allocation is not None
            and portfolio_allocation.recommended_max_order_value is not None
            else None
        ),
        "eligibility_path": (
            "exit" if normalized_source_type == "held_position" else "buy"
        ),
        "risk_off_exception_eligible": (
            risk_off_exception_eligible if normalized_source_type != "held_position" else False
        ),
        "core_risk_off_guard_active": (
            core_risk_off_guard_active if normalized_source_type != "held_position" else False
        ),
        "core_risk_off_guard_reasons": (
            list(core_risk_off_guard_reasons)
            if normalized_source_type != "held_position"
            else []
        ),
        "core_risk_off_experiment": _build_core_risk_off_shadow_experiment_metadata(
            source_type=normalized_source_type,
            core_risk_off_guard_active=core_risk_off_guard_active,
            entry_score=entry_score,
            ranking_score=ranking_score,
            signal_feature_snapshot=signal_feature_snapshot,
            overall=overall,
            slow=slow,
            strategy_selection=strategy_selection,
            apply_override=core_risk_off_topk_override,
            risk_off_exception_eligible=risk_off_exception_eligible,
        ),
        "event_overlay_experiment": _build_event_overlay_shadow_experiment_metadata(
            source_type=normalized_source_type,
            eligibility_passed=eligibility_passed,
            entry_score=entry_score,
            ranking_score=ranking_score,
            signal_feature_snapshot=signal_feature_snapshot,
            overall=overall,
            slow=slow,
            strategy_selection=strategy_selection,
        ),
    }
    return DeterministicTriggerAssessment(
        trigger_version="deterministic_trigger_v1",
        primary_candidate=primary_candidate,
        candidate_set=tuple(dict.fromkeys(candidate_set)),
        watch_candidate=watch_candidate,
        buy_candidate=buy_candidate,
        sell_candidate=sell_candidate,
        reduce_candidate=reduce_candidate,
        candidate_confidence=round(confidence, 4),
        entry_score=round(entry_score, 4),
        exit_score=round(exit_score, 4),
        watch_score=round(watch_score, 4),
        eligibility_passed=eligibility_passed,
        eligibility_reasons=tuple(dict.fromkeys(eligibility_reasons)),
        coverage_score=round(coverage_score, 4),
        ranking_score=round(ranking_score, 4),
        candidate_mode="relative_surge_v1_instrumented",
        risk_off_exception_eligible=(
            risk_off_exception_eligible if normalized_source_type != "held_position" else False
        ),
        reason_codes=tuple(dict.fromkeys(reason_codes)),
        thresholds=thresholds,
        metadata=metadata,
    )


def _build_feature_coverage_score(
    *,
    signal_feature_snapshot: SignalFeatureSnapshotEntity | None,
    market_regime: MarketRegimeAssessment | None,
    strategy_selection: StrategySelectionAssessment | None,
    portfolio_allocation: PortfolioAllocationAssessment | None,
) -> float:
    checks = (
        signal_feature_snapshot is not None,
        signal_feature_snapshot is not None
        and signal_feature_snapshot.overall_score is not None,
        signal_feature_snapshot is not None and signal_feature_snapshot.fast_score is not None,
        signal_feature_snapshot is not None and signal_feature_snapshot.slow_score is not None,
        market_regime is not None,
        strategy_selection is not None,
        portfolio_allocation is not None,
    )
    return sum(1.0 for item in checks if item) / float(len(checks))


def _assess_buy_eligibility(
    *,
    source_type: str,
    coverage_score: float,
    allocation_budget_ok: bool,
    market_regime: MarketRegimeAssessment | None,
    overall: float | None,
    slow: float | None,
    signal_feature_snapshot: SignalFeatureSnapshotEntity | None,
    portfolio_allocation: PortfolioAllocationAssessment | None,
    ranking_score: float | None,
    risk_off_exception_eligible: bool = False,
    core_risk_off_guard_reasons: tuple[str, ...] = (),
) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    if source_type in {"held_position", "reconciliation_overlay"}:
        reasons.append("eligibility_source_type_blocked")
        return False, tuple(reasons)
    reasons.append("eligibility_source_type_allowed")

    if coverage_score < 0.50:
        reasons.append("eligibility_low_feature_coverage")
        return False, tuple(reasons)
    reasons.append("eligibility_feature_coverage_ok")

    if not allocation_budget_ok:
        reasons.append("eligibility_allocation_blocked")
        return False, tuple(reasons)
    reasons.append("eligibility_allocation_available")

    if (
        market_regime is not None
        and market_regime.risk_tone == "risk_off"
        and market_regime.regime_label == "bearish_trend"
    ):
        if source_type == "core":
            if risk_off_exception_eligible:
                reasons.extend(core_risk_off_guard_reasons)
                reasons.append("eligibility_risk_off_exception_pass")
            else:
                reasons.extend(
                    core_risk_off_guard_reasons or ("eligibility_core_risk_off_guard_blocked",)
                )
                return False, tuple(dict.fromkeys(reasons))
        elif risk_off_exception_eligible:
            reasons.append("eligibility_risk_off_exception_pass")
        else:
            reasons.append("eligibility_risk_off_block")
            return False, tuple(reasons)
    reasons.append("eligibility_regime_pass")

    if overall is not None and overall < -0.10:
        reasons.append("eligibility_negative_overall_floor")
        return False, tuple(reasons)
    if slow is not None and slow < -0.15:
        reasons.append("eligibility_negative_slow_floor")
        return False, tuple(reasons)
    reasons.append("eligibility_signal_floor_pass")

    avg_daily_volume = _float_or_none(
        signal_feature_snapshot.average_volume_20d
        if signal_feature_snapshot is not None
        else None
    )
    average_turnover_20d = _float_or_none(
        signal_feature_snapshot.average_turnover_20d
        if signal_feature_snapshot is not None
        else None
    )
    volume_surge_ratio = _float_or_none(
        signal_feature_snapshot.volume_surge_ratio
        if signal_feature_snapshot is not None
        else None
    )
    turnover_surge_ratio = _float_or_none(
        signal_feature_snapshot.turnover_surge_ratio
        if signal_feature_snapshot is not None
        else None
    )
    if avg_daily_volume is not None and avg_daily_volume < 3000.0:
        reasons.append("eligibility_low_average_volume")
        return False, tuple(reasons)

    liquidity_reference_price = _estimate_liquidity_reference_price(
        signal_feature_snapshot
    )
    recommended_max_order_value = _float_or_none(
        portfolio_allocation.recommended_max_order_value
        if portfolio_allocation is not None
        else None
    )
    estimated_average_turnover = (
        average_turnover_20d
        if average_turnover_20d is not None
        else _estimate_average_turnover_20d(
            average_volume_20d=avg_daily_volume,
            liquidity_reference_price=liquidity_reference_price,
        )
    )
    if estimated_average_turnover is not None and estimated_average_turnover < 50_000_000.0:
        reasons.append("eligibility_low_turnover")
        return False, tuple(reasons)

    if (
        volume_surge_ratio is not None
        and turnover_surge_ratio is not None
        and max(volume_surge_ratio, turnover_surge_ratio) < 1.10
    ):
        reasons.append("eligibility_low_relative_activity")
        return False, tuple(reasons)

    if (
        estimated_average_turnover is not None
        and recommended_max_order_value is not None
        and recommended_max_order_value > 0
    ):
        turnover_participation_rate = (
            recommended_max_order_value / estimated_average_turnover
        )
        if turnover_participation_rate > 0.05:
            reasons.append("eligibility_participation_rate_blocked")
            return False, tuple(reasons)

    if (
        avg_daily_volume is not None
        and avg_daily_volume > 0
        and recommended_max_order_value is not None
        and recommended_max_order_value > 0
        and liquidity_reference_price is not None
        and liquidity_reference_price > 0
    ):
        estimated_order_qty = recommended_max_order_value / liquidity_reference_price
        if estimated_order_qty / avg_daily_volume > 0.03:
            reasons.append("eligibility_participation_rate_blocked")
            return False, tuple(reasons)

    reasons.append("eligibility_execution_feasibility_pass")
    return True, tuple(reasons)


def _is_core_risk_off_regime(
    *,
    source_type: str,
    market_regime: MarketRegimeAssessment | None,
) -> bool:
    if source_type != "core":
        return False
    if market_regime is None:
        return False
    return (
        market_regime.risk_tone == "risk_off"
        and market_regime.regime_label == "bearish_trend"
    )


def _assess_core_risk_off_buy_guard(
    *,
    signal_feature_snapshot: SignalFeatureSnapshotEntity | None,
    overall: float | None,
    slow: float | None,
    ranking_score: float | None,
    strategy_selection: StrategySelectionAssessment | None,
    apply_topk_override_selected: bool = False,
) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    required_activity_min = (
        _CORE_RISK_OFF_SHADOW_ACTIVITY_MIN
        if apply_topk_override_selected
        else 1.20
    )
    if ranking_score is None or ranking_score < _CORE_RISK_OFF_RANKING_MIN_SCORE:
        if not apply_topk_override_selected:
            reasons.append("eligibility_core_risk_off_ranking_blocked")
            return False, tuple(reasons)
        reasons.append("eligibility_core_risk_off_topk_override_pass")
        reasons.append("eligibility_core_risk_off_shadow_rank_promoted")
    else:
        reasons.append("eligibility_core_risk_off_ranking_pass")
    if overall is None or overall < 0.0:
        reasons.append("eligibility_core_risk_off_signal_blocked")
        return False, tuple(reasons)
    if slow is None or slow < -0.05:
        reasons.append("eligibility_core_risk_off_signal_blocked")
        return False, tuple(reasons)
    reasons.append("eligibility_core_risk_off_signal_pass")
    if signal_feature_snapshot is None:
        reasons.append("eligibility_core_risk_off_activity_blocked")
        return False, tuple(reasons)
    volume_surge_ratio = _float_or_none(signal_feature_snapshot.volume_surge_ratio)
    turnover_surge_ratio = _float_or_none(signal_feature_snapshot.turnover_surge_ratio)
    if max(volume_surge_ratio or 0.0, turnover_surge_ratio or 0.0) < required_activity_min:
        reasons.append("eligibility_core_risk_off_activity_blocked")
        return False, tuple(reasons)
    reasons.append("eligibility_core_risk_off_activity_pass")
    preferred_strategy = (
        strategy_selection.preferred_strategy if strategy_selection is not None else ""
    )
    if preferred_strategy not in {
        "defensive_low_volatility_rotation",
        "mean_reversion_bounce",
        "event_continuation",
    }:
        reasons.append("eligibility_core_risk_off_strategy_blocked")
        return False, tuple(reasons)
    reasons.append("eligibility_core_risk_off_strategy_pass")
    reasons.append("eligibility_core_risk_off_guard_pass")
    return True, tuple(reasons)


def _normalize_core_risk_off_topk_override(
    deterministic_trigger_override: dict[str, object] | None,
) -> dict[str, object]:
    if not isinstance(deterministic_trigger_override, dict):
        return {}
    raw = deterministic_trigger_override.get("core_risk_off_topk_v1")
    if not isinstance(raw, dict):
        return {}
    return dict(raw)


def _build_core_risk_off_apply_metadata(
    apply_override: dict[str, object],
    *,
    risk_off_exception_eligible: bool,
) -> dict[str, object]:
    selected = bool(apply_override.get("selected"))
    path = str(apply_override.get("path") or "core_risk_off_topk_v1")
    shadow_rank = apply_override.get("shadow_rank")
    shadow_group_size = apply_override.get("shadow_group_size")
    return {
        "apply_enabled": bool(apply_override),
        "apply_selected": selected,
        "apply_path": path if selected else None,
        "apply_ready": selected and risk_off_exception_eligible,
        "risk_off_exception_eligible": selected and risk_off_exception_eligible,
        "risk_off_exception_path": (
            path if selected and risk_off_exception_eligible else None
        ),
        "risk_off_exception_shadow_rank": shadow_rank if selected else None,
        "risk_off_exception_shadow_group_size": (
            shadow_group_size if selected else None
        ),
    }


def _classify_core_risk_off_shadow_floor_bucket(
    *,
    overall: float | None,
    slow: float | None,
    entry_score: float,
    ranking_score: float | None,
    shadow_activity_pass: bool,
    shadow_strategy_pass: bool,
    mild_overall_min: float = -0.10,
    mild_slow_min: float = -0.15,
    moderate_overall_min: float = -0.25,
    moderate_slow_min: float = -0.25,
    reason_prefix: str = "shadow_core_risk_off_floor",
) -> tuple[str, bool, tuple[str, ...]]:
    if overall is not None and overall >= 0.0 and slow is not None and slow >= -0.05:
        return (
            "strict_pass",
            True,
            (f"{reason_prefix}_strict_pass",),
        )
    if overall is not None and overall >= mild_overall_min and slow is not None and slow >= mild_slow_min:
        return (
            "mild_relax",
            True,
            (f"{reason_prefix}_mild_relax_pass",),
        )
    if (
        overall is not None
        and overall >= moderate_overall_min
        and slow is not None
        and slow >= moderate_slow_min
        and entry_score >= 0.12
        and ranking_score is not None
        and ranking_score >= 0.26
        and shadow_activity_pass
        and shadow_strategy_pass
    ):
        return (
            "moderate_relax",
            True,
            (f"{reason_prefix}_moderate_relax_pass",),
        )
    return (
        "deep_negative",
        False,
        (f"{reason_prefix}_deep_negative",),
    )


def _build_core_risk_off_shadow_experiment_metadata(
    *,
    source_type: str,
    core_risk_off_guard_active: bool,
    entry_score: float,
    ranking_score: float | None,
    signal_feature_snapshot: SignalFeatureSnapshotEntity | None,
    overall: float | None,
    slow: float | None,
    strategy_selection: StrategySelectionAssessment | None,
    apply_override: dict[str, object] | None = None,
    risk_off_exception_eligible: bool = False,
) -> dict[str, object]:
    if source_type != "core":
        return {
            "mode": _CORE_RISK_OFF_RANKING_MODE,
            "shadow_mode": _CORE_RISK_OFF_SHADOW_MODE,
            "active": False,
        }

    volume_surge_ratio = _float_or_none(
        signal_feature_snapshot.volume_surge_ratio
        if signal_feature_snapshot is not None
        else None
    )
    turnover_surge_ratio = _float_or_none(
        signal_feature_snapshot.turnover_surge_ratio
        if signal_feature_snapshot is not None
        else None
    )
    shadow_overall_pass = overall is not None and overall >= 0.0
    shadow_slow_pass = slow is not None and slow >= -0.05
    shadow_signal_pass = shadow_overall_pass and shadow_slow_pass
    shadow_entry_observe_pass = entry_score >= _CORE_RISK_OFF_SHADOW_ENTRY_OBSERVE_MIN
    shadow_activity_pass = max(
        volume_surge_ratio or 0.0,
        turnover_surge_ratio or 0.0,
    ) >= _CORE_RISK_OFF_SHADOW_ACTIVITY_MIN
    preferred_strategy = (
        strategy_selection.preferred_strategy if strategy_selection is not None else ""
    )
    shadow_strategy_pass = preferred_strategy in {
        "defensive_low_volatility_rotation",
        "mean_reversion_bounce",
        "event_continuation",
    }
    (
        shadow_floor_bucket,
        shadow_floor_relax_pass,
        shadow_floor_relax_reason_codes,
    ) = _classify_core_risk_off_shadow_floor_bucket(
        overall=overall,
        slow=slow,
        entry_score=entry_score,
        ranking_score=ranking_score,
        shadow_activity_pass=shadow_activity_pass,
        shadow_strategy_pass=shadow_strategy_pass,
    )
    (
        shadow_floor_relax_v2_bucket,
        shadow_floor_relax_v2_pass,
        shadow_floor_relax_v2_reason_codes,
    ) = _classify_core_risk_off_shadow_floor_bucket(
        overall=overall,
        slow=slow,
        entry_score=entry_score,
        ranking_score=ranking_score,
        shadow_activity_pass=shadow_activity_pass,
        shadow_strategy_pass=shadow_strategy_pass,
        mild_overall_min=_CORE_RISK_OFF_SHADOW_V2_MILD_OVERALL_MIN,
        mild_slow_min=_CORE_RISK_OFF_SHADOW_V2_MILD_SLOW_MIN,
        moderate_overall_min=_CORE_RISK_OFF_SHADOW_V2_MODERATE_OVERALL_MIN,
        moderate_slow_min=_CORE_RISK_OFF_SHADOW_V2_MODERATE_SLOW_MIN,
        reason_prefix="shadow_core_risk_off_floor_v2",
    )
    (
        shadow_floor_relax_v3_bucket,
        shadow_floor_relax_v3_pass,
        shadow_floor_relax_v3_reason_codes,
    ) = _classify_core_risk_off_shadow_floor_bucket(
        overall=overall,
        slow=slow,
        entry_score=entry_score,
        ranking_score=ranking_score,
        shadow_activity_pass=shadow_activity_pass,
        shadow_strategy_pass=shadow_strategy_pass,
        mild_overall_min=_CORE_RISK_OFF_SHADOW_V3_MILD_OVERALL_MIN,
        mild_slow_min=_CORE_RISK_OFF_SHADOW_V3_MILD_SLOW_MIN,
        moderate_overall_min=_CORE_RISK_OFF_SHADOW_V3_MODERATE_OVERALL_MIN,
        moderate_slow_min=_CORE_RISK_OFF_SHADOW_V3_MODERATE_SLOW_MIN,
        reason_prefix="shadow_core_risk_off_floor_v3",
    )
    shadow_topk_candidate = (
        core_risk_off_guard_active
        and ranking_score is not None
        and ranking_score >= _CORE_RISK_OFF_SHADOW_MIN_SCORE
        and shadow_signal_pass
        and shadow_activity_pass
        and shadow_strategy_pass
    )
    shadow_reason_codes: list[str] = []
    shadow_signal_fail_reasons: list[str] = []
    if shadow_topk_candidate:
        shadow_reason_codes.append("shadow_core_risk_off_topk_candidate")
    if not shadow_signal_pass:
        shadow_reason_codes.append("shadow_core_risk_off_signal_blocked")
        if not shadow_overall_pass:
            shadow_signal_fail_reasons.append(
                "shadow_core_risk_off_overall_floor_blocked"
            )
        if not shadow_slow_pass:
            shadow_signal_fail_reasons.append(
                "shadow_core_risk_off_slow_floor_blocked"
            )
    if not shadow_activity_pass:
        shadow_reason_codes.append("shadow_core_risk_off_activity_blocked")
    if not shadow_strategy_pass:
        shadow_reason_codes.append("shadow_core_risk_off_strategy_blocked")
    if ranking_score is None or ranking_score < _CORE_RISK_OFF_SHADOW_MIN_SCORE:
        shadow_reason_codes.append("shadow_core_risk_off_ranking_floor_blocked")
    metadata = {
        "mode": _CORE_RISK_OFF_RANKING_MODE,
        "shadow_mode": _CORE_RISK_OFF_SHADOW_MODE,
        "active": core_risk_off_guard_active,
        "ranking_min_score": _CORE_RISK_OFF_RANKING_MIN_SCORE,
        "shadow_min_score": _CORE_RISK_OFF_SHADOW_MIN_SCORE,
        "shadow_activity_min": _CORE_RISK_OFF_SHADOW_ACTIVITY_MIN,
        "shadow_entry_observe_min": _CORE_RISK_OFF_SHADOW_ENTRY_OBSERVE_MIN,
        "shadow_top_k_cap": _CORE_RISK_OFF_SHADOW_TOP_K_CAP,
        "raw_ranking_score": ranking_score,
        "shadow_rank_candidate_score": (
            round(ranking_score, 4) if ranking_score is not None else None
        ),
        "shadow_overall_score": overall,
        "shadow_slow_score": slow,
        "shadow_entry_score": entry_score,
        "shadow_overall_pass": shadow_overall_pass,
        "shadow_slow_pass": shadow_slow_pass,
        "shadow_signal_pass": shadow_signal_pass,
        "shadow_entry_observe_pass": shadow_entry_observe_pass,
        "shadow_signal_fail_reasons": tuple(shadow_signal_fail_reasons),
        "shadow_activity_pass": shadow_activity_pass,
        "shadow_strategy_pass": shadow_strategy_pass,
        "shadow_floor_bucket": shadow_floor_bucket,
        "shadow_floor_relax_pass": shadow_floor_relax_pass,
        "shadow_floor_relax_reason_codes": tuple(shadow_floor_relax_reason_codes),
        "shadow_floor_relax_entry_min": 0.12,
        "shadow_floor_relax_ranking_min": 0.26,
        "shadow_floor_relax_v2_bucket": shadow_floor_relax_v2_bucket,
        "shadow_floor_relax_v2_pass": shadow_floor_relax_v2_pass,
        "shadow_floor_relax_v2_reason_codes": tuple(shadow_floor_relax_v2_reason_codes),
        "shadow_floor_relax_v2_mild_overall_min": _CORE_RISK_OFF_SHADOW_V2_MILD_OVERALL_MIN,
        "shadow_floor_relax_v2_mild_slow_min": _CORE_RISK_OFF_SHADOW_V2_MILD_SLOW_MIN,
        "shadow_floor_relax_v2_moderate_overall_min": (
            _CORE_RISK_OFF_SHADOW_V2_MODERATE_OVERALL_MIN
        ),
        "shadow_floor_relax_v2_moderate_slow_min": _CORE_RISK_OFF_SHADOW_V2_MODERATE_SLOW_MIN,
        "shadow_floor_relax_v3_bucket": shadow_floor_relax_v3_bucket,
        "shadow_floor_relax_v3_pass": shadow_floor_relax_v3_pass,
        "shadow_floor_relax_v3_reason_codes": tuple(shadow_floor_relax_v3_reason_codes),
        "shadow_floor_relax_v3_mild_overall_min": _CORE_RISK_OFF_SHADOW_V3_MILD_OVERALL_MIN,
        "shadow_floor_relax_v3_mild_slow_min": _CORE_RISK_OFF_SHADOW_V3_MILD_SLOW_MIN,
        "shadow_floor_relax_v3_moderate_overall_min": (
            _CORE_RISK_OFF_SHADOW_V3_MODERATE_OVERALL_MIN
        ),
        "shadow_floor_relax_v3_moderate_slow_min": _CORE_RISK_OFF_SHADOW_V3_MODERATE_SLOW_MIN,
        "shadow_topk_candidate": shadow_topk_candidate,
        "shadow_reason_codes": tuple(shadow_reason_codes),
        "shadow_group_size": None,
        "shadow_rank": None,
        "shadow_topk_selected": False,
        "shadow_would_pass": False,
        "apply_ready": False,
    }
    metadata.update(
        _build_core_risk_off_apply_metadata(
            dict(apply_override or {}),
            risk_off_exception_eligible=risk_off_exception_eligible,
        )
    )
    if metadata["apply_selected"]:
        metadata["shadow_group_size"] = metadata["risk_off_exception_shadow_group_size"]
        metadata["shadow_rank"] = metadata["risk_off_exception_shadow_rank"]
        metadata["shadow_topk_selected"] = True
        metadata["shadow_would_pass"] = bool(risk_off_exception_eligible)
    return metadata


def _build_event_overlay_shadow_experiment_metadata(
    *,
    source_type: str,
    eligibility_passed: bool,
    entry_score: float,
    ranking_score: float | None,
    signal_feature_snapshot: SignalFeatureSnapshotEntity | None,
    overall: float | None,
    slow: float | None,
    strategy_selection: StrategySelectionAssessment | None,
) -> dict[str, object]:
    if source_type != "event_overlay":
        return {
            "mode": _EVENT_OVERLAY_MODE,
            "shadow_mode": _EVENT_OVERLAY_SHADOW_MODE,
            "active": False,
        }

    adjusted_ranking_score = None
    if ranking_score is not None:
        adjusted_ranking_score = _clamp(ranking_score + _EVENT_OVERLAY_SHADOW_BONUS)

    volume_surge_ratio = _float_or_none(
        signal_feature_snapshot.volume_surge_ratio
        if signal_feature_snapshot is not None
        else None
    )
    turnover_surge_ratio = _float_or_none(
        signal_feature_snapshot.turnover_surge_ratio
        if signal_feature_snapshot is not None
        else None
    )
    shadow_signal_pass = (
        entry_score >= _EVENT_OVERLAY_SHADOW_ENTRY_MIN_SCORE
        and overall is not None
        and overall >= 0.0
        and slow is not None
        and slow >= -0.05
    )
    shadow_activity_pass = max(
        volume_surge_ratio or 0.0,
        turnover_surge_ratio or 0.0,
    ) >= 1.15
    preferred_strategy = (
        strategy_selection.preferred_strategy if strategy_selection is not None else ""
    )
    shadow_strategy_pass = preferred_strategy == "event_continuation"
    shadow_would_pass = (
        eligibility_passed
        and adjusted_ranking_score is not None
        and adjusted_ranking_score >= _EVENT_OVERLAY_SHADOW_MIN_SCORE
        and shadow_signal_pass
        and shadow_activity_pass
        and shadow_strategy_pass
    )
    return {
        "mode": _EVENT_OVERLAY_MODE,
        "shadow_mode": _EVENT_OVERLAY_SHADOW_MODE,
        "active": True,
        "base_eligibility_passed": eligibility_passed,
        "shadow_bonus": _EVENT_OVERLAY_SHADOW_BONUS,
        "shadow_min_score": _EVENT_OVERLAY_SHADOW_MIN_SCORE,
        "shadow_entry_min_score": _EVENT_OVERLAY_SHADOW_ENTRY_MIN_SCORE,
        "shadow_top_k_cap": _EVENT_OVERLAY_SHADOW_TOP_K_CAP,
        "raw_ranking_score": ranking_score,
        "adjusted_ranking_score": adjusted_ranking_score,
        "shadow_signal_pass": shadow_signal_pass,
        "shadow_activity_pass": shadow_activity_pass,
        "shadow_strategy_pass": shadow_strategy_pass,
        "shadow_would_pass": shadow_would_pass,
        "apply_ready": False,
    }


def _estimate_liquidity_reference_price(
    signal_feature_snapshot: SignalFeatureSnapshotEntity | None,
) -> float | None:
    if signal_feature_snapshot is None:
        return None
    for candidate in (
        signal_feature_snapshot.sma_20,
        signal_feature_snapshot.sma_5,
        signal_feature_snapshot.sma_60,
    ):
        value = _float_or_none(candidate)
        if value is not None and value > 0:
            return value
    return None


def _estimate_average_turnover_20d(
    *,
    average_volume_20d: float | None,
    liquidity_reference_price: float | None,
) -> float | None:
    if (
        average_volume_20d is None
        or average_volume_20d <= 0
        or liquidity_reference_price is None
        or liquidity_reference_price <= 0
    ):
        return None
    return average_volume_20d * liquidity_reference_price


def _assess_exit_eligibility(
    *,
    coverage_score: float,
    has_position: bool,
    position_snapshot: PositionSnapshotEntity | None,
    exit_score: float,
) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    if not has_position or position_snapshot is None:
        reasons.append("eligibility_no_position")
        return False, tuple(reasons)
    reasons.append("eligibility_position_present")

    if coverage_score < 0.35:
        reasons.append("eligibility_low_feature_coverage")
        return False, tuple(reasons)
    reasons.append("eligibility_feature_coverage_ok")

    if exit_score <= 0.30:
        reasons.append("eligibility_low_exit_score")
        return False, tuple(reasons)
    reasons.append("eligibility_exit_signal_pass")
    return True, tuple(reasons)


def _build_buy_ranking_score(
    *,
    entry_score: float,
    coverage_score: float,
    signal_feature_snapshot: SignalFeatureSnapshotEntity | None,
    market_regime: MarketRegimeAssessment | None,
    portfolio_allocation: PortfolioAllocationAssessment | None,
    strategy_selection: StrategySelectionAssessment | None,
) -> float:
    regime_tailwind = 0.5
    if market_regime is not None:
        if market_regime.regime_label == "bullish_trend" and market_regime.risk_tone == "risk_on":
            regime_tailwind = 1.0
        elif market_regime.risk_tone == "risk_off":
            regime_tailwind = 0.0

    allocation_quality = 0.0
    if portfolio_allocation is not None:
        allocation_quality = _clamp(
            (portfolio_allocation.max_new_capital_pct or 0.0) / 10.0
        )

    strategy_alignment = 0.0
    if strategy_selection is not None and strategy_selection.preferred_strategy in {
        "swing_momentum",
        "event_continuation",
    }:
        strategy_alignment = 1.0

    relative_activity = _build_relative_activity_score(signal_feature_snapshot)

    score = (
        0.55 * entry_score
        + 0.10 * relative_activity
        + 0.20 * coverage_score
        + 0.10 * allocation_quality
        + 0.03 * regime_tailwind
        + 0.02 * strategy_alignment
    )
    return _clamp(score)


def _build_exit_ranking_score(
    *,
    exit_score: float,
    coverage_score: float,
    market_regime: MarketRegimeAssessment | None,
    portfolio_allocation: PortfolioAllocationAssessment | None,
    has_position: bool,
) -> float:
    concentration_pressure = 0.0
    if portfolio_allocation is not None:
        current_weight = portfolio_allocation.current_weight_pct or 0.0
        max_weight = portfolio_allocation.max_single_position_pct or 0.0
        if max_weight > 0:
            concentration_pressure = _clamp(current_weight / max_weight)

    regime_downside = 0.0
    if market_regime is not None:
        if market_regime.regime_label == "bearish_trend":
            regime_downside += 0.6
        if market_regime.risk_tone == "risk_off":
            regime_downside += 0.4
    regime_downside = _clamp(regime_downside)

    position_bonus = 1.0 if has_position else 0.0
    score = (
        0.70 * exit_score
        + 0.15 * coverage_score
        + 0.10 * concentration_pressure
        + 0.03 * regime_downside
        + 0.02 * position_bonus
    )
    return _clamp(score)


def _build_entry_score(
    *,
    overall: float | None,
    fast: float | None,
    slow: float | None,
    signal_feature_snapshot: SignalFeatureSnapshotEntity | None,
    market_regime: MarketRegimeAssessment | None,
    strategy_selection: StrategySelectionAssessment | None,
    portfolio_allocation: PortfolioAllocationAssessment | None,
    source_type: str,
    reason_codes: list[str],
) -> float:
    score = 0.0
    score += 0.45 * _normalize_signed_score(overall)
    score += 0.20 * _normalize_signed_score(fast)
    score += 0.15 * _normalize_signed_score(slow)

    if market_regime is not None:
        if market_regime.regime_label == "bullish_trend":
            score += 0.10
            reason_codes.append("trigger_bullish_regime")
        if market_regime.risk_tone == "risk_on":
            score += 0.05
            reason_codes.append("trigger_risk_on")
        if market_regime.risk_tone == "risk_off":
            score -= 0.15
            reason_codes.append("trigger_risk_off_penalty")

    if portfolio_allocation is not None:
        if portfolio_allocation.max_new_capital_pct > 0:
            score += min(0.10, portfolio_allocation.max_new_capital_pct / 100.0)
            reason_codes.append("trigger_allocation_budget_available")
        else:
            score -= 0.20
            reason_codes.append("trigger_allocation_budget_blocked")

    if strategy_selection is not None and strategy_selection.preferred_strategy in {
        "swing_momentum",
        "event_continuation",
    }:
        score += 0.05
        reason_codes.append("trigger_strategy_alignment")

    if source_type == "market_overlay":
        score += 0.05
        reason_codes.append("trigger_market_overlay_bias")
    elif source_type == "held_position":
        score -= 0.35
        reason_codes.append("trigger_held_position_buy_block")

    relative_activity_bonus = _build_relative_activity_score(signal_feature_snapshot)
    if relative_activity_bonus > 0:
        score += min(0.10, relative_activity_bonus * 0.10)
        reason_codes.append("trigger_relative_activity_bonus")

    return _clamp(score)


def _build_exit_score(
    *,
    overall: float | None,
    fast: float | None,
    slow: float | None,
    market_regime: MarketRegimeAssessment | None,
    portfolio_allocation: PortfolioAllocationAssessment | None,
    position_snapshot: PositionSnapshotEntity | None,
    source_type: str,
    reason_codes: list[str],
) -> float:
    score = 0.0
    score += 0.40 * _normalize_signed_score(_negate(overall))
    score += 0.20 * _normalize_signed_score(_negate(fast))
    score += 0.15 * _normalize_signed_score(_negate(slow))

    if market_regime is not None:
        if market_regime.regime_label == "bearish_trend":
            score += 0.15
            reason_codes.append("trigger_bearish_regime")
        if market_regime.volatility_regime == "high_volatility":
            score += 0.10
            reason_codes.append("trigger_high_volatility")
        if market_regime.risk_tone == "risk_off":
            score += 0.10
            reason_codes.append("trigger_exit_risk_off")

    if portfolio_allocation is not None:
        current_weight = portfolio_allocation.current_weight_pct or 0.0
        max_weight = portfolio_allocation.max_single_position_pct
        if current_weight >= max_weight:
            score += 0.20
            reason_codes.append("trigger_over_concentration")
        elif current_weight >= max_weight * 0.8:
            score += 0.08
            reason_codes.append("trigger_near_concentration_limit")

    if source_type == "held_position":
        score += 0.10
        reason_codes.append("trigger_held_position_exit_bias")

    if (
        position_snapshot is None
        or position_snapshot.quantity is None
        or position_snapshot.quantity <= 0
    ):
        score -= 0.20
        reason_codes.append("trigger_no_position_exit_penalty")

    return _clamp(score)


def _build_watch_score(
    *,
    entry_score: float,
    exit_score: float,
    source_type: str,
    position_snapshot: PositionSnapshotEntity | None,
    reason_codes: list[str],
) -> float:
    buy_gap = max(0.0, 0.65 - entry_score)
    sell_gap = max(0.0, 0.75 - exit_score)
    score = 0.0

    if 0.45 <= entry_score < 0.65:
        score = max(score, entry_score)
        reason_codes.append("trigger_watch_from_entry_setup")
    if 0.45 <= exit_score < 0.75:
        score = max(score, exit_score)
        reason_codes.append("trigger_watch_from_exit_setup")

    if source_type == "core" and position_snapshot is None:
        score = max(score, 0.45 if buy_gap <= 0.20 else 0.0)
        if score >= 0.45:
            reason_codes.append("trigger_core_watch_path")

    return _clamp(score)


def _normalize_signed_score(value: float | None) -> float:
    if value is None:
        return 0.5
    return _clamp((value + 1.0) / 2.0)


def _build_relative_activity_score(
    signal_feature_snapshot: SignalFeatureSnapshotEntity | None,
) -> float:
    if signal_feature_snapshot is None:
        return 0.0
    return _build_relative_activity_score_from_raw(
        volume_surge_ratio=_float_or_none(signal_feature_snapshot.volume_surge_ratio),
        turnover_surge_ratio=_float_or_none(signal_feature_snapshot.turnover_surge_ratio),
    )


def _build_relative_activity_score_from_raw(
    *,
    volume_surge_ratio: float | None,
    turnover_surge_ratio: float | None,
) -> float:
    volume_component = _normalize_surge_ratio(volume_surge_ratio)
    turnover_component = _normalize_surge_ratio(turnover_surge_ratio)
    return max(volume_component, turnover_component)


def _normalize_surge_ratio(value: float | None) -> float:
    if value is None or value <= 1.0:
        return 0.0
    if value >= 3.0:
        return 1.0
    return _clamp((value - 1.0) / 2.0)


def _clamp(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _negate(value: float | None) -> float | None:
    return -value if value is not None else None


def _float_or_none(value: object) -> float | None:
    return float(value) if value is not None else None
