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
    assert policy.earliest_reduce_at == datetime(
        2026, 6, 24, 0, 15, tzinfo=timezone.utc
    )
    assert policy.earliest_reentry_at is None
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
    assert policy.earliest_reduce_at is None
    assert policy.earliest_reentry_at == datetime(
        2026, 6, 24, 1, 20, tzinfo=timezone.utc
    )
    assert policy.reentry_cooldown_until == datetime(
        2026, 6, 24, 1, 20, tzinfo=timezone.utc
    )
    assert policy.sell_cooldown_until is None


def test_held_position_hold_result_unaffected_by_default_side_change() -> None:
    """2026-08-21: held_position의 기본 ``request.side``를 BUY→SELL로
    바꾼 것이 ``derive_holding_profile_policy()``의 결과를 바꾸지
    않아야 한다 — ``source_type == "held_position"``이 이미 단독으로
    ``risk_reduction_only``를 강제하는 OR 조건이므로(``holding_profile_
    policy.py`` 참고), ``side``가 ``""``(변경 전 fallback이 없었다면의
    상황)이든 ``SELL``(변경 후)이든 ``BUY``든 held_position이면 결과가
    동일해야 한다. 이 테스트는 "주문 정책이 바뀌지 않았다"는 주장의
    직접 근거다."""
    now = datetime(2026, 6, 24, 2, 0, tzinfo=timezone.utc)

    common_kwargs = dict(
        source_type="held_position",
        decision_type="HOLD",
        time_horizon="swing",
        quantity=None,
        max_order_value=None,
        signal_feature_snapshot_id="snap-3",
        reason_codes=("provider_queue_timeout",),
        now_utc=now,
    )

    policy_side_empty = derive_holding_profile_policy(side="", **common_kwargs)
    policy_side_sell = derive_holding_profile_policy(side="SELL", **common_kwargs)
    policy_side_buy = derive_holding_profile_policy(side="BUY", **common_kwargs)

    for policy in (policy_side_empty, policy_side_sell, policy_side_buy):
        assert policy.holding_profile == "risk_reduction_only"
        assert policy.earliest_reentry_at == datetime(
            2026, 6, 24, 2, 20, tzinfo=timezone.utc
        )
        assert policy.reentry_cooldown_until == datetime(
            2026, 6, 24, 2, 20, tzinfo=timezone.utc
        )
