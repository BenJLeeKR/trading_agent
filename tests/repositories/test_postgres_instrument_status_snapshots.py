from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import InstrumentEntity, InstrumentStatusSnapshotEntity
from agent_trading.repositories.container import RepositoryContainer


@pytest.fixture
async def seeded_status_instrument_id(
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
async def test_add_and_get_latest_instrument_status_snapshot(
    seeded_postgres_data: RepositoryContainer,
    seeded_status_instrument_id: UUID,
) -> None:
    snapshot = InstrumentStatusSnapshotEntity(
        instrument_status_snapshot_id=uuid4(),
        instrument_id=seeded_status_instrument_id,
        snapshot_at=datetime(2026, 6, 29, 4, 55, tzinfo=timezone.utc),
        source_type="kis_stock_basic_info",
        status_scope="instrument",
        tr_stop_yn="N",
        admn_item_yn="N",
        status_reason_codes=["status_normal"],
        raw_payload_json={"tr_stop_yn": "N", "admn_item_yn": "N"},
    )

    saved = await seeded_postgres_data.instrument_status_snapshots.add(snapshot)
    assert saved.instrument_status_snapshot_id == snapshot.instrument_status_snapshot_id

    latest = await seeded_postgres_data.instrument_status_snapshots.get_latest_by_instrument(
        seeded_status_instrument_id,
    )
    assert latest is not None
    assert latest.source_type == "kis_stock_basic_info"
    assert latest.status_reason_codes == ["status_normal"]


@pytest.mark.asyncio
async def test_get_latest_before_and_list_latest_by_instrument_ids(
    seeded_postgres_data: RepositoryContainer,
    seeded_status_instrument_id: UUID,
) -> None:
    older = InstrumentStatusSnapshotEntity(
        instrument_status_snapshot_id=uuid4(),
        instrument_id=seeded_status_instrument_id,
        snapshot_at=datetime(2026, 6, 29, 4, 55, tzinfo=timezone.utc),
        source_type="kis_stock_basic_info",
        status_scope="instrument",
        tr_stop_yn="N",
        admn_item_yn="N",
        status_reason_codes=["status_normal"],
        raw_payload_json={"version": "old"},
    )
    newer = InstrumentStatusSnapshotEntity(
        instrument_status_snapshot_id=uuid4(),
        instrument_id=seeded_status_instrument_id,
        snapshot_at=datetime(2026, 6, 29, 5, 5, tzinfo=timezone.utc),
        source_type="kis_stock_basic_info",
        status_scope="instrument",
        tr_stop_yn="Y",
        admn_item_yn="Y",
        status_reason_codes=["trading_halt", "management_issue"],
        raw_payload_json={"version": "new"},
    )

    second_instrument = InstrumentEntity(
        instrument_id=uuid4(),
        symbol="123456",
        market_code="KRX",
        asset_class="kr_stock",
        currency="KRW",
        name="상태스냅샷테스트2",
        exchange_code="KRX",
        market_segment="KOSDAQ",
        is_active=True,
    )
    await seeded_postgres_data.instruments.add(second_instrument)
    second_snapshot = InstrumentStatusSnapshotEntity(
        instrument_status_snapshot_id=uuid4(),
        instrument_id=second_instrument.instrument_id,
        snapshot_at=datetime(2026, 6, 29, 5, 0, tzinfo=timezone.utc),
        source_type="kis_inquire_price",
        status_scope="market_overlay_probe",
        iscd_stat_cls_code="05",
        temp_stop_yn="Y",
        status_reason_codes=["suspended_status:05"],
        raw_payload_json={"iscd_stat_cls_code": "05"},
    )

    await seeded_postgres_data.instrument_status_snapshots.add(older)
    await seeded_postgres_data.instrument_status_snapshots.add(newer)
    await seeded_postgres_data.instrument_status_snapshots.add(second_snapshot)

    before_cutoff = await seeded_postgres_data.instrument_status_snapshots.get_latest_by_instrument_before(
        seeded_status_instrument_id,
        datetime(2026, 6, 29, 5, 0, tzinfo=timezone.utc),
    )
    assert before_cutoff is not None
    assert before_cutoff.raw_payload_json["version"] == "old"

    rows = await seeded_postgres_data.instrument_status_snapshots.list_latest_by_instrument_ids(
        (seeded_status_instrument_id, second_instrument.instrument_id),
    )
    assert len(rows) == 2
    by_instrument_id = {row.instrument_id: row for row in rows}
    assert by_instrument_id[seeded_status_instrument_id].raw_payload_json["version"] == "new"
    assert by_instrument_id[second_instrument.instrument_id].temp_stop_yn == "Y"
