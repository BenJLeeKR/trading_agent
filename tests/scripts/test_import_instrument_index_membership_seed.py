from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from agent_trading.domain.entities import InstrumentEntity
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from scripts.import_instrument_index_membership_seed import (
    MembershipSeedRow,
    _apply_seed,
    _load_seed_rows,
    _parse_effective_from,
)


def test_parse_effective_from_defaults_today(monkeypatch) -> None:
    class _FakeDatetime:
        @classmethod
        def now(cls):
            from datetime import datetime

            return datetime(2026, 6, 19, 12, 0, 0)

    monkeypatch.setattr(
        "scripts.import_instrument_index_membership_seed.datetime",
        _FakeDatetime,
    )
    assert _parse_effective_from(None) == date(2026, 6, 19)


def test_load_seed_rows_groups_and_dedupes(tmp_path: Path) -> None:
    path = tmp_path / "seed.csv"
    path.write_text(
        (
            "symbol,membership_code\n"
            "005930,KOSPI100\n"
            "005930,KOSPI100\n"
            "005930,KOSPI200\n"
            "090150,KOSDAQ50\n"
        ),
        encoding="utf-8",
    )
    rows, grouped = _load_seed_rows(str(path))
    assert rows == [
        MembershipSeedRow(symbol="005930", membership_code="KOSPI100"),
        MembershipSeedRow(symbol="005930", membership_code="KOSPI100"),
        MembershipSeedRow(symbol="005930", membership_code="KOSPI200"),
        MembershipSeedRow(symbol="090150", membership_code="KOSDAQ50"),
    ]
    assert grouped == {
        "005930": ["KOSPI100", "KOSPI200"],
        "090150": ["KOSDAQ50"],
    }


@pytest.mark.asyncio
async def test_apply_seed_merges_with_existing_memberships() -> None:
    repos = build_in_memory_repositories()
    instrument = InstrumentEntity(
        instrument_id=uuid4(),
        symbol="005930",
        market_code="KRX",
        asset_class="kr_stock",
        currency="KRW",
        name="삼성전자",
        tick_size=Decimal("100"),
        lot_size=Decimal("1"),
        is_active=True,
        exchange_code="KRX",
        market_segment="KOSPI",
    )
    await repos.instruments.add(instrument)
    await repos.instrument_index_memberships.sync_current_memberships(
        instrument.instrument_id,
        ["KOSPI200"],
        effective_from=date(2026, 6, 19),
        source_tag="kis_master_csv",
        metadata={"sync_source": "kis_master_file"},
    )

    summary = await _apply_seed(
        repos.instruments,
        repos.instrument_index_memberships,
        grouped_memberships={"005930": ["KOSPI100"]},
        effective_from=date(2026, 6, 20),
        source_tag="index_membership_seed_csv",
        replace_listed_symbols=False,
    )

    memberships = await repos.instrument_index_memberships.list_active_by_instrument(
        instrument.instrument_id
    )
    assert summary.target_symbol_count == 1
    assert summary.resolved_symbol_count == 1
    assert summary.skipped_symbol_count == 0
    assert [item.membership_code for item in memberships] == ["KOSPI100", "KOSPI200"]


@pytest.mark.asyncio
async def test_apply_seed_replaces_when_requested() -> None:
    repos = build_in_memory_repositories()
    instrument = InstrumentEntity(
        instrument_id=uuid4(),
        symbol="090150",
        market_code="KRX",
        asset_class="kr_stock",
        currency="KRW",
        name="광진윈텍",
        tick_size=Decimal("100"),
        lot_size=Decimal("1"),
        is_active=True,
        exchange_code="KRX",
        market_segment="KOSDAQ",
    )
    await repos.instruments.add(instrument)
    await repos.instrument_index_memberships.sync_current_memberships(
        instrument.instrument_id,
        ["KOSDAQ150"],
        effective_from=date(2026, 6, 19),
        source_tag="kis_master_csv",
        metadata={"sync_source": "kis_master_file"},
    )

    await _apply_seed(
        repos.instruments,
        repos.instrument_index_memberships,
        grouped_memberships={"090150": ["KOSDAQ50"]},
        effective_from=date(2026, 6, 20),
        source_tag="index_membership_seed_csv",
        replace_listed_symbols=True,
    )

    memberships = await repos.instrument_index_memberships.list_active_by_instrument(
        instrument.instrument_id
    )
    assert [item.membership_code for item in memberships] == ["KOSDAQ50"]


@pytest.mark.asyncio
async def test_apply_seed_skips_unknown_symbol() -> None:
    repos = build_in_memory_repositories()
    summary = await _apply_seed(
        repos.instruments,
        repos.instrument_index_memberships,
        grouped_memberships={"999999": ["KOSDAQ150"]},
        effective_from=date(2026, 6, 20),
        source_tag="index_membership_seed_csv",
        replace_listed_symbols=False,
    )
    assert summary.target_symbol_count == 1
    assert summary.resolved_symbol_count == 0
    assert summary.skipped_symbol_count == 1
    assert summary.updated_symbol_count == 0
