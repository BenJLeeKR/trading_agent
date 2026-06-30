from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Iterable

from agent_trading.domain.entities import ExternalEventEntity, SymbolTradeStateEntity
from agent_trading.domain.enums import PipelineStopReason
from agent_trading.services.holding_profile_policy import resolve_policy_timestamp
from agent_trading.services.ai_agents.schemas import AIRiskOutput

_PENDING_SYMBOL_STATES = {"entry_pending", "reduce_pending", "exit_pending"}
_NOVELTY_LOOKBACK = timedelta(hours=24)
_REENTRY_EDGE_IMPROVEMENT_BPS = Decimal("10")
_EXIT_EDGE_COLLAPSE_ABSOLUTE_BPS = Decimal("5")
_EXIT_EDGE_COLLAPSE_DELTA_BPS = Decimal("15")


@dataclass(slots=True, frozen=True)
class ReverseTradeHysteresisDecision:
    blocked: bool
    stop_reason: str | None = None
    detail_code: str | None = None
    details: dict[str, str | None] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ExitHysteresisDecision:
    blocked: bool
    detail_code: str | None = None
    details: dict[str, str | None] = field(default_factory=dict)


def _decimal_or_none(value: object | None) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _event_supports_reentry(event: ExternalEventEntity) -> bool:
    metadata = dict(event.metadata or {})
    novelty = str(metadata.get("novelty") or event.severity or "").strip().lower()
    supports_entry_raw = metadata.get("supports_entry")
    supports_entry = (
        supports_entry_raw is True
        or str(supports_entry_raw or "").strip().lower() == "true"
    )
    positive_direction = str(
        metadata.get("impact_direction") or event.direction or ""
    ).strip().lower() == "positive"
    high_or_fresh_novelty = novelty in {"high", "medium", "surprising", "fresh"}
    return high_or_fresh_novelty and (supports_entry or positive_direction)


def _event_supports_exit(event: ExternalEventEntity) -> bool:
    metadata = dict(event.metadata or {})
    novelty = str(metadata.get("novelty") or event.severity or "").strip().lower()
    supports_exit_raw = metadata.get("supports_exit")
    supports_exit = (
        supports_exit_raw is True
        or str(supports_exit_raw or "").strip().lower() == "true"
    )
    negative_direction = str(
        metadata.get("impact_direction") or event.direction or ""
    ).strip().lower() == "negative"
    high_or_fresh_novelty = novelty in {"high", "medium", "surprising", "fresh"}
    return high_or_fresh_novelty and (supports_exit or negative_direction)


def _compute_event_novelty_passed(
    *,
    recent_events: tuple[ExternalEventEntity, ...] | list[ExternalEventEntity] | None,
    reference_time: datetime | None,
) -> tuple[bool, str]:
    if not recent_events:
        return False, "none"
    cutoff = reference_time or (datetime.now(UTC) - _NOVELTY_LOOKBACK)
    qualifying = [
        event
        for event in recent_events
        if event.published_at >= cutoff and _event_supports_reentry(event)
    ]
    if qualifying:
        novelty = str(
            dict(qualifying[0].metadata or {}).get("novelty")
            or qualifying[0].severity
            or "medium"
        ).strip().lower()
        return True, novelty or "medium"
    return False, "none"


def _contains_keyword(values: Iterable[str], keywords: tuple[str, ...]) -> bool:
    normalized = " ".join(str(value).strip().lower() for value in values if value)
    return any(keyword in normalized for keyword in keywords)


def _with_flag(
    details: dict[str, str | None],
    *,
    key: str | None,
    value: bool,
) -> dict[str, str | None]:
    merged = dict(details)
    if key is not None:
        merged[key] = "true" if value else "false"
    return merged


def evaluate_recent_reverse_trade(
    *,
    current_signal_feature_snapshot_id: str | None,
    last_signal_feature_snapshot_id: str | None,
    recent_opposite_order_count: int,
    latest_decision_type: str | None,
    eligible_decision_types: Iterable[str] | None,
    cooldown_stop_reason: str,
    details: dict[str, str | None] | None = None,
    snapshot_unchanged_detail_key: str | None = None,
    activity_flag_detail_key: str | None = None,
    require_matching_decision_type: bool = True,
    event_novelty_passed: bool | None = None,
    event_novelty_label: str | None = None,
) -> ReverseTradeHysteresisDecision:
    merged_details = dict(details or {})
    eligible_set = {
        str(item).strip().lower()
        for item in (eligible_decision_types or ())
        if str(item).strip()
    }
    normalized_decision_type = (
        str(latest_decision_type).strip().lower()
        if latest_decision_type is not None
        else None
    )
    decision_type_matched = (
        normalized_decision_type in eligible_set
        if require_matching_decision_type
        else True
    )
    reverse_activity_detected = (
        recent_opposite_order_count > 0 and decision_type_matched
    )

    merged_details = _with_flag(
        merged_details,
        key=activity_flag_detail_key,
        value=reverse_activity_detected,
    )
    if not reverse_activity_detected:
        return ReverseTradeHysteresisDecision(
            blocked=False,
            details=merged_details,
        )

    signal_feature_snapshot_unchanged = (
        current_signal_feature_snapshot_id is not None
        and last_signal_feature_snapshot_id is not None
        and current_signal_feature_snapshot_id == last_signal_feature_snapshot_id
    )
    merged_details = _with_flag(
        merged_details,
        key=snapshot_unchanged_detail_key,
        value=signal_feature_snapshot_unchanged,
    )
    if signal_feature_snapshot_unchanged:
        return ReverseTradeHysteresisDecision(
            blocked=True,
            stop_reason=PipelineStopReason.REVERSE_TRADE_SAME_SIGNAL_FEATURE_SNAPSHOT.value,
            details=merged_details,
        )
    if event_novelty_passed is not None:
        merged_details = _with_flag(
            merged_details,
            key="reentry_event_novelty_passed",
            value=event_novelty_passed,
        )
        merged_details["reentry_event_novelty"] = event_novelty_label
    if event_novelty_passed is True:
        return ReverseTradeHysteresisDecision(
            blocked=False,
            details=merged_details,
        )

    return ReverseTradeHysteresisDecision(
        blocked=True,
        stop_reason=cooldown_stop_reason,
        details=merged_details,
    )


def evaluate_symbol_state_buy_hysteresis(
    *,
    symbol_state: SymbolTradeStateEntity,
    current_signal_feature_snapshot_id: str | None,
    now_utc: datetime,
    current_edge_after_cost_bps: Decimal | None = None,
    recent_events: tuple[ExternalEventEntity, ...] | list[ExternalEventEntity] | None = None,
    details: dict[str, str | None] | None = None,
) -> ReverseTradeHysteresisDecision:
    merged_details = dict(details or {})
    policy_payload = (
        dict(symbol_state.metadata_json.get("holding_profile_policy"))
        if isinstance(symbol_state.metadata_json.get("holding_profile_policy"), dict)
        else {}
    )
    earliest_reentry_at = resolve_policy_timestamp(
        policy_payload,
        key="earliest_reentry_at",
        fallback_key="reentry_cooldown_until",
    ) or symbol_state.reentry_cooldown_until
    merged_details["symbol_state"] = symbol_state.state
    merged_details["earliest_reentry_at"] = (
        earliest_reentry_at.isoformat()
        if earliest_reentry_at is not None
        else None
    )
    merged_details["last_signal_feature_snapshot_id"] = (
        str(symbol_state.last_signal_feature_snapshot_id)
        if symbol_state.last_signal_feature_snapshot_id is not None
        else None
    )
    merged_details["current_signal_feature_snapshot_id"] = (
        current_signal_feature_snapshot_id
    )
    merged_details["current_edge_after_cost_bps"] = (
        str(current_edge_after_cost_bps) if current_edge_after_cost_bps is not None else None
    )

    if symbol_state.state in _PENDING_SYMBOL_STATES:
        return ReverseTradeHysteresisDecision(
            blocked=True,
            stop_reason="ai_override_gate",
            detail_code="ai_override_state_pending_conflict",
            details=merged_details,
        )

    cooldown_active = (
        earliest_reentry_at is not None and earliest_reentry_at > now_utc
    )
    merged_details = _with_flag(
        merged_details,
        key="reentry_cooldown_active",
        value=cooldown_active,
    )
    if not cooldown_active:
        return ReverseTradeHysteresisDecision(
            blocked=False,
            details=merged_details,
        )

    signal_feature_snapshot_unchanged = (
        current_signal_feature_snapshot_id is not None
        and symbol_state.last_signal_feature_snapshot_id is not None
        and current_signal_feature_snapshot_id
        == str(symbol_state.last_signal_feature_snapshot_id)
    )
    signal_feature_snapshot_changed = (
        current_signal_feature_snapshot_id is not None
        and symbol_state.last_signal_feature_snapshot_id is not None
        and current_signal_feature_snapshot_id
        != str(symbol_state.last_signal_feature_snapshot_id)
    )
    merged_details = _with_flag(
        merged_details,
        key="reentry_signal_feature_snapshot_unchanged",
        value=signal_feature_snapshot_unchanged,
    )
    merged_details = _with_flag(
        merged_details,
        key="reentry_signal_feature_snapshot_changed",
        value=signal_feature_snapshot_changed,
    )
    if signal_feature_snapshot_unchanged:
        return ReverseTradeHysteresisDecision(
            blocked=True,
            stop_reason="ai_override_gate",
            detail_code="ai_override_reverse_same_signal_feature_blocked",
            details=merged_details,
        )
    if not signal_feature_snapshot_changed:
        return ReverseTradeHysteresisDecision(
            blocked=True,
            stop_reason="ai_override_gate",
            detail_code="ai_override_reverse_feature_change_blocked",
            details=merged_details,
        )
    last_exit_edge_after_cost_bps = _decimal_or_none(
        policy_payload.get("last_exit_edge_after_cost_bps")
        or policy_payload.get("last_reduce_edge_after_cost_bps")
        or symbol_state.metadata_json.get("last_exit_edge_after_cost_bps")
        or symbol_state.metadata_json.get("last_reduce_edge_after_cost_bps")
    )
    merged_details["last_exit_edge_after_cost_bps"] = (
        str(last_exit_edge_after_cost_bps)
        if last_exit_edge_after_cost_bps is not None
        else None
    )
    edge_improvement_passed = (
        current_edge_after_cost_bps is not None
        and last_exit_edge_after_cost_bps is not None
        and current_edge_after_cost_bps
        >= last_exit_edge_after_cost_bps + _REENTRY_EDGE_IMPROVEMENT_BPS
    )
    merged_details = _with_flag(
        merged_details,
        key="reentry_edge_improvement_passed",
        value=edge_improvement_passed,
    )
    if current_edge_after_cost_bps is not None and last_exit_edge_after_cost_bps is None:
        edge_improvement_passed = True
        merged_details["reentry_edge_improvement_passed"] = "true"
    event_novelty_passed, event_novelty_label = _compute_event_novelty_passed(
        recent_events=recent_events,
        reference_time=symbol_state.last_exit_at or symbol_state.last_reduce_at,
    )
    merged_details = _with_flag(
        merged_details,
        key="reentry_event_novelty_passed",
        value=event_novelty_passed,
    )
    merged_details["reentry_event_novelty"] = event_novelty_label
    if not event_novelty_passed:
        return ReverseTradeHysteresisDecision(
            blocked=True,
            stop_reason="ai_override_gate",
            detail_code="ai_override_reverse_event_novelty_blocked",
            details=merged_details,
        )
    if not edge_improvement_passed:
        return ReverseTradeHysteresisDecision(
            blocked=True,
            stop_reason="ai_override_gate",
            detail_code="ai_override_reverse_edge_regression_blocked",
            details=merged_details,
        )
    return ReverseTradeHysteresisDecision(
        blocked=False,
        details=merged_details,
    )


def evaluate_symbol_state_sell_hysteresis(
    *,
    symbol_state: SymbolTradeStateEntity,
    current_edge_after_cost_bps: Decimal | None,
    risk_output: AIRiskOutput | None,
    recent_events: tuple[ExternalEventEntity, ...] | list[ExternalEventEntity] | None,
    now_utc: datetime,
    details: dict[str, str | None] | None = None,
) -> ExitHysteresisDecision:
    merged_details = dict(details or {})
    policy_payload = (
        dict(symbol_state.metadata_json.get("holding_profile_policy"))
        if isinstance(symbol_state.metadata_json.get("holding_profile_policy"), dict)
        else {}
    )
    earliest_reduce_at = resolve_policy_timestamp(
        policy_payload,
        key="earliest_reduce_at",
        fallback_key="minimum_hold_until",
    ) or symbol_state.minimum_hold_until
    merged_details["earliest_reduce_at"] = (
        earliest_reduce_at.isoformat() if earliest_reduce_at is not None else None
    )
    merged_details["holding_profile"] = symbol_state.holding_profile
    merged_details["current_edge_after_cost_bps"] = (
        str(current_edge_after_cost_bps) if current_edge_after_cost_bps is not None else None
    )

    early_reduce_window_active = (
        earliest_reduce_at is not None and earliest_reduce_at > now_utc
    )
    merged_details = _with_flag(
        merged_details,
        key="early_reduce_window_active",
        value=early_reduce_window_active,
    )
    if not early_reduce_window_active:
        return ExitHysteresisDecision(blocked=False, details=merged_details)

    last_entry_edge_after_cost_bps = _decimal_or_none(
        policy_payload.get("last_entry_edge_after_cost_bps")
        or symbol_state.metadata_json.get("last_entry_edge_after_cost_bps")
    )
    merged_details["last_entry_edge_after_cost_bps"] = (
        str(last_entry_edge_after_cost_bps)
        if last_entry_edge_after_cost_bps is not None
        else None
    )
    edge_collapse = False
    if current_edge_after_cost_bps is not None:
        edge_collapse = current_edge_after_cost_bps <= _EXIT_EDGE_COLLAPSE_ABSOLUTE_BPS
        if (
            not edge_collapse
            and last_entry_edge_after_cost_bps is not None
            and current_edge_after_cost_bps
            <= last_entry_edge_after_cost_bps - _EXIT_EDGE_COLLAPSE_DELTA_BPS
        ):
            edge_collapse = True
    merged_details = _with_flag(
        merged_details,
        key="exit_edge_collapse_passed",
        value=edge_collapse,
    )

    recent_exit_events = tuple(recent_events or ())
    downside_shock = any(_event_supports_exit(event) for event in recent_exit_events)
    merged_details = _with_flag(
        merged_details,
        key="exit_downside_shock_passed",
        value=downside_shock,
    )

    risk_flags = tuple(risk_output.risk_flags) if risk_output is not None else ()
    reason_codes = tuple(risk_output.reason_codes) if risk_output is not None else ()
    thesis_invalidation = _contains_keyword(
        risk_flags + reason_codes,
        (
            "thesis",
            "invalidate",
            "fraud",
            "accounting",
            "guidance_cut",
            "earnings_miss",
            "governance",
        ),
    )
    merged_details = _with_flag(
        merged_details,
        key="exit_thesis_invalidation_passed",
        value=thesis_invalidation,
    )

    holding_profile_breach = _contains_keyword(
        risk_flags + reason_codes,
        (
            "breach",
            "stop_loss",
            "drawdown",
            "mae",
            "adverse",
            "concent",
            "expos",
            "over",
        ),
    )
    merged_details = _with_flag(
        merged_details,
        key="exit_holding_profile_breach_passed",
        value=holding_profile_breach,
    )

    if edge_collapse or downside_shock or thesis_invalidation or holding_profile_breach:
        return ExitHysteresisDecision(blocked=False, details=merged_details)

    return ExitHysteresisDecision(
        blocked=True,
        detail_code="held_position_exit_hysteresis_blocked",
        details=merged_details,
    )
