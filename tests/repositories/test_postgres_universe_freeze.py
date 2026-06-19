from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import (
    InstrumentEntity,
    UniverseFreezeRunEntity,
    UniverseFreezeRunItemEntity,
)
from agent_trading.repositories.container import RepositoryContainer


@pytest.fixture
async def seeded_instrument_id(
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
async def test_add_and_get_latest_universe_freeze_run(
    seeded_postgres_data: RepositoryContainer,
) -> None:
    older = UniverseFreezeRunEntity(
        universe_freeze_run_id=uuid4(),
        business_date=date(2026, 6, 19),
        freeze_purpose="signal_feature_after_market",
        freeze_sequence=1,
        frozen_at=datetime(2026, 6, 19, 11, 10, tzinfo=timezone.utc),
        selection_version="universe_selection.v1",
        selection_params_json={"core_cap": 80, "market_overlay_cap": 10},
        target_count=90,
        status="materialized",
    )
    newer = UniverseFreezeRunEntity(
        universe_freeze_run_id=uuid4(),
        business_date=date(2026, 6, 19),
        freeze_purpose="signal_feature_after_market",
        freeze_sequence=2,
        frozen_at=datetime(2026, 6, 19, 11, 15, tzinfo=timezone.utc),
        selection_version="universe_selection.v1",
        selection_params_json={"core_cap": 80, "market_overlay_cap": 10},
        target_count=96,
        status="materialized",
    )

    await seeded_postgres_data.universe_freeze_runs.add(older)
    saved = await seeded_postgres_data.universe_freeze_runs.add(newer)

    assert saved.universe_freeze_run_id == newer.universe_freeze_run_id
    latest = await seeded_postgres_data.universe_freeze_runs.get_latest(
        date(2026, 6, 19),
        "signal_feature_after_market",
    )
    assert latest is not None
    assert latest.universe_freeze_run_id == newer.universe_freeze_run_id
    assert latest.target_count == 96


@pytest.mark.asyncio
async def test_add_and_list_universe_freeze_run_items(
    seeded_postgres_data: RepositoryContainer,
    seeded_instrument_id: UUID,
) -> None:
    run = UniverseFreezeRunEntity(
        universe_freeze_run_id=uuid4(),
        business_date=date(2026, 6, 19),
        freeze_purpose="signal_feature_after_market",
        freeze_sequence=1,
        frozen_at=datetime(2026, 6, 19, 11, 10, tzinfo=timezone.utc),
        selection_version="universe_selection.v1",
        target_count=2,
        status="materialized",
    )
    await seeded_postgres_data.universe_freeze_runs.add(run)

    first = UniverseFreezeRunItemEntity(
        universe_freeze_run_item_id=uuid4(),
        universe_freeze_run_id=run.universe_freeze_run_id,
        instrument_id=seeded_instrument_id,
        symbol="005930",
        market_code="KRX",
        source_type="core",
        inclusion_reason="core_universe",
        priority_score=Decimal("0.91000000"),
        rank=2,
        cap_bucket="core",
        metadata_json={"reason_codes": ["core_universe"]},
    )
    second_instrument = InstrumentEntity(
        instrument_id=uuid4(),
        symbol="399660",
        market_code="KRX",
        asset_class="kr_stock",
        currency="KRW",
        name="Universe Freeze Test 2",
        is_active=True,
    )
    await seeded_postgres_data.instruments.add(second_instrument)
    second = UniverseFreezeRunItemEntity(
        universe_freeze_run_item_id=uuid4(),
        universe_freeze_run_id=run.universe_freeze_run_id,
        instrument_id=second_instrument.instrument_id,
        symbol="399660",
        market_code="KRX",
        source_type="market_overlay",
        inclusion_reason="flow_relative_turnover_surge",
        priority_score=Decimal("0.98000000"),
        rank=1,
        cap_bucket="market_overlay",
        metadata_json={"surge_ratio": "3.4"},
    )

    await seeded_postgres_data.universe_freeze_run_items.add_many((first, second))

    rows = await seeded_postgres_data.universe_freeze_run_items.list_by_run(
        run.universe_freeze_run_id,
    )
    assert len(rows) == 2
    assert rows[0].symbol == "399660"
    assert rows[0].rank == 1
    assert rows[1].symbol == "005930"
    assert rows[1].metadata_json["reason_codes"] == ["core_universe"]
