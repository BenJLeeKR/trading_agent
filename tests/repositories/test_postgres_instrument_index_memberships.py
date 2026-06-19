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
