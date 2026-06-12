from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent_trading.repositories.memory import InMemoryInstrumentRepository
from scripts.seed_placeholder_instruments_from_mapping_gaps import (
    MappingGap,
    _build_placeholder_instrument,
    _parse_args,
    _seed_placeholders,
)
from scripts.sync_kis_instrument_master import _make_instrument_id


def test_parse_args_defaults() -> None:
    args = _parse_args([])
    assert args.lookback_days == 14
    assert args.apply is False
    assert args.default_market_code == "KRX"
    assert args.default_asset_class == "kr_stock"
    assert args.default_currency == "KRW"
    assert args.source_tag == "mapping_gap_placeholder"


def test_build_placeholder_instrument_is_inactive_and_tagged() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    gap = MappingGap(
        symbol="005940",
        sources=("broker_fill_snapshots", "snapshot_sync_runs"),
        occurrence_count=3,
        latest_observed_at=now,
    )
    instrument = _build_placeholder_instrument(
        gap,
        market_code="KRX",
        asset_class="kr_stock",
        currency="KRW",
        source_tag="test_gap",
    )
    assert instrument.instrument_id == _make_instrument_id("005940", "KRX")
    assert instrument.name == "[PLACEHOLDER] 005940"
    assert instrument.is_active is False
    assert instrument.metadata["placeholder"] is True
    assert instrument.metadata["sources"] == ["broker_fill_snapshots", "snapshot_sync_runs"]


@pytest.mark.asyncio
async def test_seed_placeholders_inserts_missing_and_skips_existing() -> None:
    repo = InMemoryInstrumentRepository()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    missing_gap = MappingGap(
        symbol="005940",
        sources=("snapshot_sync_runs",),
        occurrence_count=2,
        latest_observed_at=now,
    )
    existing_gap = MappingGap(
        symbol="005930",
        sources=("external_events",),
        occurrence_count=1,
        latest_observed_at=now,
    )
    await repo.upsert_by_symbol(
        _build_placeholder_instrument(
            existing_gap,
            market_code="KRX",
            asset_class="kr_stock",
            currency="KRW",
            source_tag="preseed",
        )
    )

    counters = await _seed_placeholders(
        repo,
        [missing_gap, existing_gap],
        dry_run=False,
        market_code="KRX",
        asset_class="kr_stock",
        currency="KRW",
        source_tag="test_gap",
    )

    assert counters.inserted == 1
    assert counters.skipped_existing == 1
    inserted = await repo.get_by_symbol("005940", "KRX")
    assert inserted is not None
    assert inserted.is_active is False
    assert inserted.metadata["placeholder_source"] == "mapping_gap_auto_seed"


@pytest.mark.asyncio
async def test_seed_placeholders_dry_run_does_not_persist() -> None:
    repo = InMemoryInstrumentRepository()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    gap = MappingGap(
        symbol="001234",
        sources=("external_events",),
        occurrence_count=1,
        latest_observed_at=now,
    )
    counters = await _seed_placeholders(
        repo,
        [gap],
        dry_run=True,
        market_code="KRX",
        asset_class="kr_stock",
        currency="KRW",
        source_tag="test_gap",
    )
    assert counters.inserted == 1
    assert await repo.get_by_symbol("001234", "KRX") is None
