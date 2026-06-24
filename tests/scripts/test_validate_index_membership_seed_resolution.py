from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from agent_trading.domain.entities import InstrumentEntity
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from scripts.validate_index_membership_seed_resolution import (
    SeedResolutionItem,
    SeedResolutionSummary,
    _load_seed_symbols,
    _resolve_seed_items,
)


def test_load_seed_symbols_groups_codes(tmp_path: Path) -> None:
    path = tmp_path / "seed.csv"
    path.write_text(
        (
            "symbol,membership_code\n"
            "005930,KOSPI100\n"
            "005930,KOSPI200\n"
            "090150,KOSDAQ50\n"
        ),
        encoding="utf-8",
    )
    assert _load_seed_symbols(str(path)) == [
        ("005930", ("KOSPI100", "KOSPI200")),
        ("090150", ("KOSDAQ50",)),
    ]


@pytest.mark.asyncio
async def test_resolve_seed_items_reports_resolved_unresolved_and_placeholder() -> None:
    repos = build_in_memory_repositories()
    normal = InstrumentEntity(
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
        metadata={},
    )
    placeholder = InstrumentEntity(
        instrument_id=uuid4(),
        symbol="090150",
        market_code="KRX",
        asset_class="kr_stock",
        currency="KRW",
        name="[PLACEHOLDER] 090150",
        tick_size=Decimal("1"),
        lot_size=Decimal("1"),
        is_active=False,
        exchange_code="KRX",
        market_segment="KOSDAQ",
        metadata={"placeholder": True},
    )
    await repos.instruments.add(normal)
    await repos.instruments.add(placeholder)

    summary, items = await _resolve_seed_items(
        repos.instruments,
        [
            ("005930", ("KOSPI100",)),
            ("090150", ("KOSDAQ50",)),
            ("999999", ("KOSDAQ150",)),
        ],
    )

    assert summary == SeedResolutionSummary(
        target_symbol_count=3,
        resolved_symbol_count=2,
        unresolved_symbol_count=1,
        placeholder_symbol_count=1,
    )
    assert items == [
        SeedResolutionItem(
            symbol="005930",
            membership_codes=("KOSPI100",),
            resolved=True,
            placeholder=False,
            instrument_id=str(normal.instrument_id),
            market_segment="KOSPI",
            instrument_name="삼성전자",
        ),
        SeedResolutionItem(
            symbol="090150",
            membership_codes=("KOSDAQ50",),
            resolved=True,
            placeholder=True,
            instrument_id=str(placeholder.instrument_id),
            market_segment="KOSDAQ",
            instrument_name="[PLACEHOLDER] 090150",
        ),
        SeedResolutionItem(
            symbol="999999",
            membership_codes=("KOSDAQ150",),
            resolved=False,
            placeholder=False,
            instrument_id=None,
            market_segment=None,
            instrument_name=None,
        ),
    ]
