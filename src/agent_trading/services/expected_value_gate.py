from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from agent_trading.domain.entities import SignalFeatureSnapshotEntity

_ACTIONABLE_DECISION_TYPES = frozenset({"APPROVE", "BUY", "SELL", "EXIT", "REDUCE"})


class _ExpectedValueContext(Protocol):
    signal_feature_snapshot: SignalFeatureSnapshotEntity | None
    deterministic_trigger: object | None


@dataclass(slots=True, frozen=True)
class ExpectedValueAssessment:
    expected_return_bps: Decimal | None
    expected_downside_bps: Decimal | None
    net_expected_value_bps: Decimal | None
    final_trade_score: Decimal | None
    minimum_required_edge_bps: Decimal | None
    edge_after_cost_bps: Decimal | None
    estimated_round_trip_cost_bps: Decimal | None
    slippage_buffer_bps: Decimal | None
    expected_value_gate_passed: bool
    reason_codes: tuple[str, ...] = ()


def evaluate_expected_value_gate(
    *,
    decision_type: str,
    confidence: float,
    conviction: float,
    risk_score: float,
    context: _ExpectedValueContext,
) -> ExpectedValueAssessment:
    normalized_decision_type = (decision_type or "").strip().upper()
    if normalized_decision_type not in _ACTIONABLE_DECISION_TYPES:
        return ExpectedValueAssessment(
            expected_return_bps=None,
            expected_downside_bps=None,
            net_expected_value_bps=None,
            final_trade_score=None,
            minimum_required_edge_bps=None,
            edge_after_cost_bps=None,
            estimated_round_trip_cost_bps=None,
            slippage_buffer_bps=None,
            expected_value_gate_passed=True,
            reason_codes=("expected_value_not_required_non_actionable",),
        )

    signal_snapshot = context.signal_feature_snapshot
    deterministic_trigger = context.deterministic_trigger
    is_entry = normalized_decision_type in {"APPROVE", "BUY"}
    score_anchor = _resolve_score_anchor(
        deterministic_trigger=deterministic_trigger,
        signal_snapshot=signal_snapshot,
        is_entry=is_entry,
        confidence=confidence,
        conviction=conviction,
    )
    if score_anchor is None:
        return ExpectedValueAssessment(
            expected_return_bps=None,
            expected_downside_bps=None,
            net_expected_value_bps=None,
            final_trade_score=None,
            minimum_required_edge_bps=None,
            edge_after_cost_bps=None,
            estimated_round_trip_cost_bps=None,
            slippage_buffer_bps=None,
            expected_value_gate_passed=False,
            reason_codes=("expected_value_anchor_score_missing",),
        )

    risk_anchor = max(0.0, min(1.0, float(risk_score or 0.0)))
    atr_pct = (
        _decimal_to_float(signal_snapshot.atr_14_pct)
        if signal_snapshot is not None
        else None
    )
    atr_penalty_bps = min(max(atr_pct, 0.0) * 10.0, 30.0) if atr_pct is not None else 0.0

    expected_return_bps = _decimal_from_float(score_anchor * 100.0)
    expected_downside_bps = _decimal_from_float((risk_anchor * 40.0) + atr_penalty_bps)
    net_expected_value_bps = expected_return_bps - expected_downside_bps
    final_trade_score = _decimal_from_float(
        (
            max(0.0, min(1.0, float(confidence or 0.0)))
            + max(0.0, min(1.0, float(conviction or 0.0)))
            + score_anchor
        )
        / 3.0
    )
    minimum_required_edge_bps = Decimal("10.00") if is_entry else Decimal("5.00")
    risk_off_exception_path = _is_risk_off_exception_path(deterministic_trigger)
    if is_entry and risk_off_exception_path:
        minimum_required_edge_bps += Decimal("7.50")
    estimated_round_trip_cost_bps = _estimate_round_trip_cost_bps(
        signal_snapshot=signal_snapshot,
        deterministic_trigger=deterministic_trigger,
        is_entry=is_entry,
    )
    slippage_buffer_bps = _estimate_slippage_buffer_bps(
        signal_snapshot=signal_snapshot,
        deterministic_trigger=deterministic_trigger,
        is_entry=is_entry,
    )
    edge_after_cost_bps = (
        net_expected_value_bps
        - estimated_round_trip_cost_bps
        - slippage_buffer_bps
    )
    reason_codes: list[str] = ["expected_value_anchor_present"]
    if signal_snapshot is None:
        reason_codes.append("expected_value_signal_feature_missing")
    if deterministic_trigger is None:
        reason_codes.append("expected_value_trigger_missing")
    if signal_snapshot is None and deterministic_trigger is None:
        reason_codes.append("expected_value_fallback_ai_only")
    gate_passed = edge_after_cost_bps >= minimum_required_edge_bps
    if gate_passed:
        reason_codes.append("expected_value_edge_meets_minimum_required")
    else:
        reason_codes.append("expected_value_edge_below_minimum_required")
    if risk_off_exception_path:
        reason_codes.append("expected_value_risk_off_exception_path")

    return ExpectedValueAssessment(
        expected_return_bps=expected_return_bps,
        expected_downside_bps=expected_downside_bps,
        net_expected_value_bps=net_expected_value_bps,
        final_trade_score=final_trade_score,
        minimum_required_edge_bps=minimum_required_edge_bps,
        edge_after_cost_bps=edge_after_cost_bps,
        estimated_round_trip_cost_bps=estimated_round_trip_cost_bps,
        slippage_buffer_bps=slippage_buffer_bps,
        expected_value_gate_passed=gate_passed,
        reason_codes=tuple(reason_codes),
    )


def _resolve_score_anchor(
    *,
    deterministic_trigger: object | None,
    signal_snapshot: SignalFeatureSnapshotEntity | None,
    is_entry: bool,
    confidence: float,
    conviction: float,
) -> float | None:
    if deterministic_trigger is not None:
        trigger_score = None
        if is_entry:
            trigger_score = getattr(deterministic_trigger, "entry_score", None)
        else:
            trigger_score = getattr(deterministic_trigger, "exit_score", None)
        if trigger_score is None:
            trigger_score = getattr(deterministic_trigger, "candidate_confidence", None)
        if trigger_score is not None:
            return max(0.0, min(1.0, float(trigger_score)))

    if signal_snapshot is not None:
        overall_score = _decimal_to_float(signal_snapshot.overall_score)
        if overall_score is not None:
            if is_entry:
                return max(0.0, min(1.0, overall_score))
            return max(0.0, min(1.0, abs(overall_score)))

    fallback_score = max(
        0.0,
        min(
            1.0,
            (
                max(0.0, min(1.0, float(confidence or 0.0)))
                + max(0.0, min(1.0, float(conviction or 0.0)))
            )
            / 2.0,
        ),
    )
    return fallback_score


def _decimal_from_float(value: float) -> Decimal:
    return Decimal(f"{value:.2f}")


def _decimal_to_float(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _estimate_round_trip_cost_bps(
    *,
    signal_snapshot: SignalFeatureSnapshotEntity | None,
    deterministic_trigger: object | None,
    is_entry: bool,
) -> Decimal:
    total_bps = 8.0 if is_entry else 6.0
    if signal_snapshot is None:
        total_bps += 3.0
    turnover_20d = (
        _decimal_to_float(signal_snapshot.average_turnover_20d)
        if signal_snapshot is not None
        else None
    )
    if turnover_20d is None:
        total_bps += 2.0
    elif turnover_20d < 1_000_000_000:
        total_bps += 3.0
    elif turnover_20d < 5_000_000_000:
        total_bps += 1.5
    ranking_percentile = (
        getattr(deterministic_trigger, "ranking_percentile", None)
        if deterministic_trigger is not None
        else None
    )
    if ranking_percentile is not None and float(ranking_percentile) < 0.35:
        total_bps += 2.0
    return _decimal_from_float(total_bps)


def _is_risk_off_exception_path(deterministic_trigger: object | None) -> bool:
    if deterministic_trigger is None:
        return False
    if bool(getattr(deterministic_trigger, "risk_off_exception_eligible", False)):
        return True
    metadata = getattr(deterministic_trigger, "metadata", None)
    if isinstance(metadata, dict):
        return bool(metadata.get("risk_off_exception_eligible"))
    return False


def _estimate_slippage_buffer_bps(
    *,
    signal_snapshot: SignalFeatureSnapshotEntity | None,
    deterministic_trigger: object | None,
    is_entry: bool,
) -> Decimal:
    total_bps = 3.0 if is_entry else 2.0
    atr_pct = (
        _decimal_to_float(signal_snapshot.atr_14_pct)
        if signal_snapshot is not None
        else None
    )
    if atr_pct is None:
        total_bps += 3.0
    else:
        total_bps += min(max(atr_pct, 0.0) * 4.0, 15.0)
    average_volume_20d = (
        _decimal_to_float(signal_snapshot.average_volume_20d)
        if signal_snapshot is not None
        else None
    )
    if average_volume_20d is None:
        total_bps += 2.0
    elif average_volume_20d < 100_000:
        total_bps += 4.0
    elif average_volume_20d < 300_000:
        total_bps += 2.0
    candidate_mode = (
        str(getattr(deterministic_trigger, "candidate_mode", "")).strip().lower()
        if deterministic_trigger is not None
        else ""
    )
    if candidate_mode.startswith("watch"):
        total_bps += 1.0
    return _decimal_from_float(total_bps)
