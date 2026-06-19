from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import InstrumentEntity, SignalFeatureSnapshotEntity
from agent_trading.repositories.postgres.signal_feature_snapshots import (
    PostgresSignalFeatureSnapshotRepository,
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
async def test_add_and_get_latest_by_instrument(
    seeded_postgres_data: RepositoryContainer,
    seeded_instrument_id: UUID,
) -> None:
    snapshot = SignalFeatureSnapshotEntity(
        signal_feature_snapshot_id=uuid4(),
        instrument_id=seeded_instrument_id,
        timeframe="1d",
        snapshot_at=datetime.now(timezone.utc),
        feature_set_version="signal_backbone.v1",
        bar_count=80,
        sma_20=Decimal("169.50000000"),
        return_1m_pct=Decimal("12.57861635"),
        fast_score=Decimal("0.41750000"),
        slow_score=Decimal("0.86000000"),
        overall_score=Decimal("0.66090000"),
        component_scores_json={"fast_trend": 0.8, "volume_confirmation": 0.75},
        reason_codes=["above_sma20", "volume_surge_strong"],
    )
    saved = await seeded_postgres_data.signal_feature_snapshots.add(snapshot)
    assert saved.signal_feature_snapshot_id == snapshot.signal_feature_snapshot_id
    assert saved.feature_set_version == "signal_backbone.v1"

    latest = await seeded_postgres_data.signal_feature_snapshots.get_latest_by_instrument(
        seeded_instrument_id
    )
    assert latest is not None
    assert latest.signal_feature_snapshot_id == snapshot.signal_feature_snapshot_id
    assert latest.component_scores_json["fast_trend"] == 0.8
    assert latest.reason_codes == ["above_sma20", "volume_surge_strong"]


@pytest.mark.asyncio
async def test_get_latest_returns_most_recent_snapshot(
    seeded_postgres_data: RepositoryContainer,
    seeded_instrument_id: UUID,
) -> None:
    older_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
    newer_at = older_at + timedelta(days=1)
    older = SignalFeatureSnapshotEntity(
        signal_feature_snapshot_id=uuid4(),
        instrument_id=seeded_instrument_id,
        timeframe="1d",
        snapshot_at=older_at,
        feature_set_version="signal_backbone.v1",
        bar_count=60,
        overall_score=Decimal("0.10000000"),
    )
    newer = SignalFeatureSnapshotEntity(
        signal_feature_snapshot_id=uuid4(),
        instrument_id=seeded_instrument_id,
        timeframe="1d",
        snapshot_at=newer_at,
        feature_set_version="signal_backbone.v1",
        bar_count=61,
        overall_score=Decimal("0.50000000"),
    )
    await seeded_postgres_data.signal_feature_snapshots.add(older)
    await seeded_postgres_data.signal_feature_snapshots.add(newer)

    latest = await seeded_postgres_data.signal_feature_snapshots.get_latest_by_instrument(
        seeded_instrument_id
    )
    assert latest is not None
    assert latest.signal_feature_snapshot_id == newer.signal_feature_snapshot_id
    assert latest.overall_score == Decimal("0.50000000")


@pytest.mark.asyncio
async def test_list_by_instrument_descending(
    seeded_postgres_data: RepositoryContainer,
    seeded_instrument_id: UUID,
) -> None:
    base_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
    ids: list[UUID] = []
    for idx in range(3):
        entity = SignalFeatureSnapshotEntity(
            signal_feature_snapshot_id=uuid4(),
            instrument_id=seeded_instrument_id,
            timeframe="1d",
            snapshot_at=base_at + timedelta(days=idx),
            feature_set_version="signal_backbone.v1",
            bar_count=40 + idx,
            overall_score=Decimal(str(idx)),
        )
        ids.append(entity.signal_feature_snapshot_id)
        await seeded_postgres_data.signal_feature_snapshots.add(entity)

    rows = await seeded_postgres_data.signal_feature_snapshots.list_by_instrument(
        seeded_instrument_id,
        limit=10,
    )
    assert len(rows) == 3
    assert rows[0].signal_feature_snapshot_id == ids[2]
    assert rows[1].signal_feature_snapshot_id == ids[1]
    assert rows[2].signal_feature_snapshot_id == ids[0]


@pytest.mark.asyncio
async def test_get_latest_by_instrument_nonexistent(
    seeded_postgres_data: RepositoryContainer,
) -> None:
    result = await seeded_postgres_data.signal_feature_snapshots.get_latest_by_instrument(
        uuid4()
    )
    assert result is None


@pytest.mark.asyncio
async def test_add_uses_savepoint_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = SignalFeatureSnapshotEntity(
        signal_feature_snapshot_id=uuid4(),
        instrument_id=uuid4(),
        timeframe="1d",
        snapshot_at=datetime.now(timezone.utc),
        feature_set_version="signal_backbone.v1",
        bar_count=80,
        average_turnover_20d=Decimal("12345678901234.12345678"),
    )

    class FakeSavepoint:
        def __init__(self, calls: list[str]) -> None:
            self._calls = calls

        async def __aenter__(self) -> str:
            self._calls.append("enter")
            return "sp_1"

        async def __aexit__(self, exc_type, exc, tb) -> None:
            self._calls.append("exit")

    class FakeConnection:
        async def fetchrow(self, *_args, **_kwargs) -> dict[str, object]:
            return {
                "signal_feature_snapshot_id": snapshot.signal_feature_snapshot_id,
                "instrument_id": snapshot.instrument_id,
                "timeframe": snapshot.timeframe,
                "snapshot_at": snapshot.snapshot_at,
                "feature_set_version": snapshot.feature_set_version,
                "bar_count": snapshot.bar_count,
                "average_turnover_20d": snapshot.average_turnover_20d,
                "created_at": snapshot.snapshot_at,
            }

    savepoint_calls: list[str] = []
    tx = SimpleNamespace(
        connection=FakeConnection(),
        savepoint=lambda: FakeSavepoint(savepoint_calls),
    )
    repo = PostgresSignalFeatureSnapshotRepository(tx)

    monkeypatch.setattr(
        "agent_trading.repositories.postgres.signal_feature_snapshots.row_to_entity",
        lambda row, _entity_cls: row,
    )

    saved = await repo.add(snapshot)

    assert savepoint_calls == ["enter", "exit"]
    assert saved["signal_feature_snapshot_id"] == snapshot.signal_feature_snapshot_id
