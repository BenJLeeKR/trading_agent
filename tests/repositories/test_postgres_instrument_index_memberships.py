from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from agent_trading.domain.entities import InstrumentEntity


@pytest.mark.asyncio
async def test_sync_current_memberships_tracks_active_set_over_time(
    postgres_repos,
) -> None:
    instrument = InstrumentEntity(
        instrument_id=uuid4(),
        symbol="T399660",
        market_code="KRX",
        asset_class="kr_stock",
        currency="KRW",
        name="테스트멤버십종목",
        exchange_code="KRX",
        market_segment="KOSPI",
        is_active=True,
    )
    await postgres_repos.instruments.add(instrument)

    first = await postgres_repos.instrument_index_memberships.sync_current_memberships(
        instrument.instrument_id,
        ["KOSPI200", "KOSPI100"],
        effective_from=date(2026, 6, 19),
        source_tag="kis_master_csv",
        metadata={"sync_source": "kis_master_file"},
    )
    assert [item.membership_code for item in first] == ["KOSPI100", "KOSPI200"]

    second = await postgres_repos.instrument_index_memberships.sync_current_memberships(
        instrument.instrument_id,
        ["KOSPI200"],
        effective_from=date(2026, 6, 20),
        source_tag="kis_master_csv",
        metadata={"sync_source": "kis_master_file"},
    )
    assert [item.membership_code for item in second] == ["KOSPI200"]


@pytest.mark.asyncio
async def test_list_active_by_instruments_batches_multiple_instruments(
    postgres_repos,
) -> None:
    """Batch variant should return the same active memberships as calling
    ``list_active_by_instrument`` once per instrument, in a single query."""
    instrument_a = InstrumentEntity(
        instrument_id=uuid4(),
        symbol="T399661",
        market_code="KRX",
        asset_class="kr_stock",
        currency="KRW",
        name="배치조회A",
        exchange_code="KRX",
        market_segment="KOSPI",
        is_active=True,
    )
    instrument_b = InstrumentEntity(
        instrument_id=uuid4(),
        symbol="T399662",
        market_code="KRX",
        asset_class="kr_stock",
        currency="KRW",
        name="배치조회B",
        exchange_code="KRX",
        market_segment="KOSDAQ",
        is_active=True,
    )
    instrument_c_no_memberships = InstrumentEntity(
        instrument_id=uuid4(),
        symbol="T399663",
        market_code="KRX",
        asset_class="kr_stock",
        currency="KRW",
        name="배치조회C",
        exchange_code="KRX",
        market_segment="KOSPI",
        is_active=True,
    )
    await postgres_repos.instruments.add(instrument_a)
    await postgres_repos.instruments.add(instrument_b)
    await postgres_repos.instruments.add(instrument_c_no_memberships)

    await postgres_repos.instrument_index_memberships.sync_current_memberships(
        instrument_a.instrument_id,
        ["KOSPI200"],
        effective_from=date(2026, 6, 19),
    )
    await postgres_repos.instrument_index_memberships.sync_current_memberships(
        instrument_b.instrument_id,
        ["KOSDAQ150", "KRX300"],
        effective_from=date(2026, 6, 19),
    )

    result = await postgres_repos.instrument_index_memberships.list_active_by_instruments(
        [
            instrument_a.instrument_id,
            instrument_b.instrument_id,
            instrument_c_no_memberships.instrument_id,
        ]
    )

    assert [item.membership_code for item in result[instrument_a.instrument_id]] == ["KOSPI200"]
    assert [item.membership_code for item in result[instrument_b.instrument_id]] == [
        "KOSDAQ150",
        "KRX300",
    ]
    assert instrument_c_no_memberships.instrument_id not in result


@pytest.mark.asyncio
async def test_list_active_by_instruments_empty_input_returns_empty_dict(
    postgres_repos,
) -> None:
    result = await postgres_repos.instrument_index_memberships.list_active_by_instruments([])
    assert result == {}
