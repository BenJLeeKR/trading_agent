from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import InstrumentEntity, SymbolTradeStateEntity
from agent_trading.repositories.container import RepositoryContainer


@pytest.fixture
async def symbol_state_instrument_id(
    seeded_postgres_data: RepositoryContainer,
    sample_instrument: InstrumentEntity,
) -> UUID:
    saved = await seeded_postgres_data.instruments.get_by_symbol(
        sample_instrument.symbol,
        sample_instrument.market_code,
    )
    assert saved is not None
    return saved.instrument_id


@pytest.mark.asyncio
async def test_upsert_and_get_symbol_trade_state(
    seeded_postgres_data: RepositoryContainer,
    sample_account,
    symbol_state_instrument_id: UUID,
) -> None:
    state = SymbolTradeStateEntity(
        symbol_trade_state_id=uuid4(),
        account_id=sample_account.account_id,
        instrument_id=symbol_state_instrument_id,
        symbol="005930",
        market="KRX",
        state="held_active",
        holding_profile="core_swing",
        position_quantity=Decimal("17"),
        last_entry_source_type="core",
        minimum_hold_until=datetime.now(timezone.utc) + timedelta(minutes=30),
        reentry_cooldown_until=datetime.now(timezone.utc) + timedelta(hours=4),
        last_reason_codes=["expected_value_gate_passed", "core_entry"],
        thesis_state_hash="hash-1",
        metadata_json={"policy_version": "holding_profile_v1"},
    )

    saved = await seeded_postgres_data.symbol_trade_states.upsert(state)

    assert saved.account_id == sample_account.account_id
    assert saved.holding_profile == "core_swing"
    assert saved.last_reason_codes == ["expected_value_gate_passed", "core_entry"]

    fetched = await seeded_postgres_data.symbol_trade_states.get_by_account_and_instrument(
        sample_account.account_id,
        symbol_state_instrument_id,
    )
    assert fetched is not None
    assert fetched.symbol_trade_state_id == state.symbol_trade_state_id
    assert fetched.metadata_json["policy_version"] == "holding_profile_v1"


@pytest.mark.asyncio
async def test_upsert_updates_existing_state_on_account_instrument_conflict(
    seeded_postgres_data: RepositoryContainer,
    sample_account,
    symbol_state_instrument_id: UUID,
) -> None:
    first = SymbolTradeStateEntity(
        symbol_trade_state_id=uuid4(),
        account_id=sample_account.account_id,
        instrument_id=symbol_state_instrument_id,
        symbol="005930",
        market="KRX",
        state="entry_pending",
        holding_profile="event_swing",
        position_quantity=Decimal("3"),
        last_reason_codes=["initial_entry"],
        metadata_json={"revision": 1},
        created_at=datetime(2026, 6, 24, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 24, tzinfo=timezone.utc),
    )
    second = SymbolTradeStateEntity(
        symbol_trade_state_id=uuid4(),
        account_id=sample_account.account_id,
        instrument_id=symbol_state_instrument_id,
        symbol="005930",
        market="KRX",
        state="flat_cooldown",
        holding_profile="event_swing",
        position_quantity=Decimal("0"),
        last_exit_at=datetime(2026, 6, 24, 1, tzinfo=timezone.utc),
        reentry_cooldown_until=datetime(2026, 6, 24, 2, tzinfo=timezone.utc),
        last_reason_codes=["cooldown_after_exit"],
        metadata_json={"revision": 2},
    )

    await seeded_postgres_data.symbol_trade_states.upsert(first)
    saved = await seeded_postgres_data.symbol_trade_states.upsert(second)

    fetched = await seeded_postgres_data.symbol_trade_states.get_by_account_and_instrument(
        sample_account.account_id,
        symbol_state_instrument_id,
    )
    assert fetched is not None
    assert fetched.symbol_trade_state_id == first.symbol_trade_state_id
    assert fetched.state == "flat_cooldown"
    assert fetched.position_quantity == Decimal("0")
    assert fetched.last_reason_codes == ["cooldown_after_exit"]
    assert fetched.metadata_json["revision"] == 2
    assert saved.symbol_trade_state_id == first.symbol_trade_state_id


@pytest.mark.asyncio
async def test_get_by_account_and_instrument_returns_none_when_missing(
    seeded_postgres_data: RepositoryContainer,
    sample_account,
) -> None:
    result = await seeded_postgres_data.symbol_trade_states.get_by_account_and_instrument(
        sample_account.account_id,
        uuid4(),
    )
    assert result is None
