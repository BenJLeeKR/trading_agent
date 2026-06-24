from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from agent_trading.services.holding_profile_policy import (
    derive_holding_profile_policy,
    serialize_holding_profile_policy,
)


def test_event_overlay_short_horizon_maps_to_event_probe() -> None:
    now = datetime(2026, 6, 24, 0, 0, tzinfo=timezone.utc)
    policy = derive_holding_profile_policy(
        source_type="event_overlay",
        decision_type="BUY",
        side="BUY",
        time_horizon="short",
        quantity=Decimal("1"),
        max_order_value=Decimal("50000"),
        signal_feature_snapshot_id="snap-1",
        reason_codes=("event_overlay_bias",),
        now_utc=now,
    )

    assert policy.holding_profile == "event_probe"
    assert policy.minimum_hold_until == datetime(
        2026, 6, 24, 0, 15, tzinfo=timezone.utc
    )
    assert policy.reentry_cooldown_until is None
    assert policy.sell_cooldown_until == datetime(
        2026, 6, 24, 0, 10, tzinfo=timezone.utc
    )
    assert serialize_holding_profile_policy(policy)["holding_profile"] == "event_probe"


def test_sell_path_maps_to_risk_reduction_only_with_reentry_cooldown() -> None:
    now = datetime(2026, 6, 24, 1, 0, tzinfo=timezone.utc)
    policy = derive_holding_profile_policy(
        source_type="held_position",
        decision_type="REDUCE",
        side="SELL",
        time_horizon="short",
        quantity=Decimal("5"),
        max_order_value=Decimal("100000"),
        signal_feature_snapshot_id="snap-2",
        reason_codes=("risk_off",),
        now_utc=now,
    )

    assert policy.holding_profile == "risk_reduction_only"
    assert policy.minimum_hold_until is None
    assert policy.reentry_cooldown_until == datetime(
        2026, 6, 24, 1, 20, tzinfo=timezone.utc
    )
    assert policy.sell_cooldown_until is None
