from __future__ import annotations

from uuid import uuid4

from agent_trading.domain.entities import UniverseFreezeRunItemEntity
from agent_trading.services.universe_freeze_dedupe import (
    dedupe_universe_freeze_run_items,
)


def test_dedupe_universe_freeze_run_items_skips_duplicate_symbol_market() -> None:
    run_id = uuid4()
    first = UniverseFreezeRunItemEntity(
        universe_freeze_run_item_id=uuid4(),
        universe_freeze_run_id=run_id,
        instrument_id=uuid4(),
        symbol="005930",
        market_code="KRX",
        source_type="core",
        inclusion_reason="approved_core_universe",
        rank=1,
        cap_bucket="core",
    )
    duplicate = UniverseFreezeRunItemEntity(
        universe_freeze_run_item_id=uuid4(),
        universe_freeze_run_id=run_id,
        instrument_id=uuid4(),
        symbol="005930",
        market_code="KRX",
        source_type="market_overlay",
        inclusion_reason="event_overlay",
        rank=2,
        cap_bucket="market_overlay",
    )

    deduped, skipped = dedupe_universe_freeze_run_items((first, duplicate))

    assert skipped == 1
    assert len(deduped) == 1
    assert deduped[0].symbol == "005930"
    assert deduped[0].rank == 1


def test_dedupe_universe_freeze_run_items_skips_duplicate_instrument() -> None:
    run_id = uuid4()
    instrument_id = uuid4()
    first = UniverseFreezeRunItemEntity(
        universe_freeze_run_item_id=uuid4(),
        universe_freeze_run_id=run_id,
        instrument_id=instrument_id,
        symbol="005930",
        market_code="KRX",
        source_type="core",
        inclusion_reason="approved_core_universe",
        rank=1,
        cap_bucket="core",
    )
    duplicate = UniverseFreezeRunItemEntity(
        universe_freeze_run_item_id=uuid4(),
        universe_freeze_run_id=run_id,
        instrument_id=instrument_id,
        symbol="005930A",
        market_code="KRX",
        source_type="core",
        inclusion_reason="approved_core_universe",
        rank=2,
        cap_bucket="core",
    )

    deduped, skipped = dedupe_universe_freeze_run_items((first, duplicate))

    assert skipped == 1
    assert len(deduped) == 1
    assert deduped[0].instrument_id == instrument_id
