from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from agent_trading.domain.enums import OrderSide

_POLICY_VERSION = "holding_profile_v1"
_EVENT_PROBE_MIN_HOLD = timedelta(minutes=15)
_EVENT_SWING_MIN_HOLD = timedelta(minutes=90)
_CORE_SWING_MIN_HOLD = timedelta(hours=2)
_POSITION_TRADE_MIN_HOLD = timedelta(minutes=30)
_DEFAULT_SELL_COOLDOWN = timedelta(minutes=20)
_SHORT_SELL_COOLDOWN = timedelta(minutes=10)
_DEFAULT_REENTRY_COOLDOWN = timedelta(minutes=20)


@dataclass(slots=True, frozen=True)
class HoldingProfilePolicy:
    holding_profile: str | None
    minimum_hold_until: datetime | None
    reentry_cooldown_until: datetime | None
    sell_cooldown_until: datetime | None
    thesis_state_hash: str | None
    metadata: dict[str, object] = field(default_factory=dict)


def derive_holding_profile_policy(
    *,
    source_type: str,
    decision_type: str,
    side: str | OrderSide | None,
    time_horizon: str | None,
    quantity: Decimal | None,
    max_order_value: Decimal | None,
    signal_feature_snapshot_id: str | None,
    reason_codes: tuple[str, ...] | list[str] | None,
    now_utc: datetime | None = None,
) -> HoldingProfilePolicy:
    now = now_utc or datetime.now(timezone.utc)
    normalized_source_type = (source_type or "core").strip().lower()
    normalized_decision_type = (decision_type or "HOLD").strip().upper()
    normalized_time_horizon = (time_horizon or "").strip().lower() or None
    normalized_side = _normalize_side(side)

    if (
        normalized_side == OrderSide.SELL.value
        or normalized_decision_type in {"SELL", "EXIT", "REDUCE"}
        or normalized_source_type == "held_position"
    ):
        metadata = {
            "policy_version": _POLICY_VERSION,
            "source_type": normalized_source_type,
            "time_horizon": normalized_time_horizon,
            "policy_mode": "risk_reduction",
            "reentry_cooldown_minutes": int(
                _DEFAULT_REENTRY_COOLDOWN.total_seconds() // 60
            ),
            "signal_feature_snapshot_id": signal_feature_snapshot_id,
        }
        return HoldingProfilePolicy(
            holding_profile="risk_reduction_only",
            minimum_hold_until=None,
            reentry_cooldown_until=now + _DEFAULT_REENTRY_COOLDOWN,
            sell_cooldown_until=None,
            thesis_state_hash=_build_thesis_state_hash(
                source_type=normalized_source_type,
                decision_type=normalized_decision_type,
                time_horizon=normalized_time_horizon,
                signal_feature_snapshot_id=signal_feature_snapshot_id,
                reason_codes=reason_codes,
            ),
            metadata=metadata,
        )

    holding_profile = "position_trade"
    minimum_hold_delta = _POSITION_TRADE_MIN_HOLD
    sell_cooldown_delta = _DEFAULT_SELL_COOLDOWN

    if normalized_source_type == "core":
        holding_profile = "core_swing"
        minimum_hold_delta = _CORE_SWING_MIN_HOLD
    elif normalized_source_type == "event_overlay":
        if normalized_time_horizon == "short" or quantity == Decimal("1"):
            holding_profile = "event_probe"
            minimum_hold_delta = _EVENT_PROBE_MIN_HOLD
            sell_cooldown_delta = _SHORT_SELL_COOLDOWN
        else:
            holding_profile = "event_swing"
            minimum_hold_delta = _EVENT_SWING_MIN_HOLD
    elif normalized_source_type == "market_overlay":
        holding_profile = "position_trade"
        minimum_hold_delta = _POSITION_TRADE_MIN_HOLD

    metadata = {
        "policy_version": _POLICY_VERSION,
        "source_type": normalized_source_type,
        "time_horizon": normalized_time_horizon,
        "minimum_hold_minutes": int(minimum_hold_delta.total_seconds() // 60),
        "sell_cooldown_minutes": int(sell_cooldown_delta.total_seconds() // 60),
        "signal_feature_snapshot_id": signal_feature_snapshot_id,
        "quantity": str(quantity) if quantity is not None else None,
        "max_order_value": str(max_order_value) if max_order_value is not None else None,
    }
    return HoldingProfilePolicy(
        holding_profile=holding_profile,
        minimum_hold_until=now + minimum_hold_delta,
        reentry_cooldown_until=None,
        sell_cooldown_until=now + sell_cooldown_delta,
        thesis_state_hash=_build_thesis_state_hash(
            source_type=normalized_source_type,
            decision_type=normalized_decision_type,
            time_horizon=normalized_time_horizon,
            signal_feature_snapshot_id=signal_feature_snapshot_id,
            reason_codes=reason_codes,
        ),
        metadata=metadata,
    )


def serialize_holding_profile_policy(
    policy: HoldingProfilePolicy,
) -> dict[str, object]:
    return {
        "holding_profile": policy.holding_profile,
        "minimum_hold_until": (
            policy.minimum_hold_until.isoformat()
            if policy.minimum_hold_until is not None
            else None
        ),
        "reentry_cooldown_until": (
            policy.reentry_cooldown_until.isoformat()
            if policy.reentry_cooldown_until is not None
            else None
        ),
        "sell_cooldown_until": (
            policy.sell_cooldown_until.isoformat()
            if policy.sell_cooldown_until is not None
            else None
        ),
        "thesis_state_hash": policy.thesis_state_hash,
        "metadata": dict(policy.metadata),
    }


def parse_datetime_or_none(value: object | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _normalize_side(side: str | OrderSide | None) -> str:
    if side is None:
        return ""
    return str(getattr(side, "value", side)).strip().lower()


def _build_thesis_state_hash(
    *,
    source_type: str,
    decision_type: str,
    time_horizon: str | None,
    signal_feature_snapshot_id: str | None,
    reason_codes: tuple[str, ...] | list[str] | None,
) -> str:
    payload: dict[str, Any] = {
        "source_type": source_type,
        "decision_type": decision_type,
        "time_horizon": time_horizon,
        "signal_feature_snapshot_id": signal_feature_snapshot_id,
        "reason_codes": list(reason_codes or ()),
    }
    return hashlib.sha1(
        json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()
