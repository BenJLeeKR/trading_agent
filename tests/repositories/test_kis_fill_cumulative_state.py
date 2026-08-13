from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from agent_trading.domain.entities import KisFillCumulativeStateEntity
from agent_trading.repositories.bootstrap import build_in_memory_repositories


def _make_state(
    *,
    account_id,
    broker_native_order_id: str,
    cumulative: str,
    observed_at: datetime,
) -> KisFillCumulativeStateEntity:
    return KisFillCumulativeStateEntity(
        kis_fill_cumulative_state_id=uuid4(),
        account_id=account_id,
        broker_name="koreainvestment",
        broker_native_order_id=broker_native_order_id,
        last_cumulative_filled_quantity=Decimal(cumulative),
        last_average_fill_price=Decimal("10390"),
        last_observed_at=observed_at,
        last_raw_field_fingerprint="abc123",
    )


async def test_get_returns_none_when_no_state_exists() -> None:
    repos = build_in_memory_repositories()
    result = await repos.kis_fill_cumulative_state.get(
        account_id=uuid4(),
        broker_name="koreainvestment",
        broker_native_order_id="0000015609",
    )
    assert result is None


async def test_upsert_then_get_roundtrips() -> None:
    repos = build_in_memory_repositories()
    account_id = uuid4()
    now = datetime.now(timezone.utc)

    state = _make_state(
        account_id=account_id,
        broker_native_order_id="0000015609",
        cumulative="11",
        observed_at=now,
    )
    saved = await repos.kis_fill_cumulative_state.upsert(state)
    assert saved.last_cumulative_filled_quantity == Decimal("11")

    fetched = await repos.kis_fill_cumulative_state.get(
        account_id=account_id,
        broker_name="koreainvestment",
        broker_native_order_id="0000015609",
    )
    assert fetched is not None
    assert fetched.last_cumulative_filled_quantity == Decimal("11")


async def test_upsert_updates_existing_row_in_place() -> None:
    """같은 (account_id, broker_name, broker_native_order_id) 재 upsert시
    새 행이 아니라 기존 행이 갱신된다 — staircase 0→11→259 관측 시나리오와
    동일한 반복 upsert 패턴."""
    repos = build_in_memory_repositories()
    account_id = uuid4()
    t1 = datetime.now(timezone.utc)

    await repos.kis_fill_cumulative_state.upsert(
        _make_state(
            account_id=account_id,
            broker_native_order_id="0000015609",
            cumulative="0",
            observed_at=t1,
        ),
    )
    await repos.kis_fill_cumulative_state.upsert(
        _make_state(
            account_id=account_id,
            broker_native_order_id="0000015609",
            cumulative="11",
            observed_at=t1,
        ),
    )
    final = await repos.kis_fill_cumulative_state.upsert(
        _make_state(
            account_id=account_id,
            broker_native_order_id="0000015609",
            cumulative="259",
            observed_at=t1,
        ),
    )
    assert final.last_cumulative_filled_quantity == Decimal("259")

    fetched = await repos.kis_fill_cumulative_state.get(
        account_id=account_id,
        broker_name="koreainvestment",
        broker_native_order_id="0000015609",
    )
    assert fetched is not None
    assert fetched.last_cumulative_filled_quantity == Decimal("259")


async def test_different_orders_are_tracked_independently() -> None:
    repos = build_in_memory_repositories()
    account_id = uuid4()
    now = datetime.now(timezone.utc)

    await repos.kis_fill_cumulative_state.upsert(
        _make_state(
            account_id=account_id,
            broker_native_order_id="ORDER-A",
            cumulative="5",
            observed_at=now,
        ),
    )
    await repos.kis_fill_cumulative_state.upsert(
        _make_state(
            account_id=account_id,
            broker_native_order_id="ORDER-B",
            cumulative="99",
            observed_at=now,
        ),
    )

    a = await repos.kis_fill_cumulative_state.get(
        account_id=account_id, broker_name="koreainvestment",
        broker_native_order_id="ORDER-A",
    )
    b = await repos.kis_fill_cumulative_state.get(
        account_id=account_id, broker_name="koreainvestment",
        broker_native_order_id="ORDER-B",
    )
    assert a is not None and a.last_cumulative_filled_quantity == Decimal("5")
    assert b is not None and b.last_cumulative_filled_quantity == Decimal("99")
