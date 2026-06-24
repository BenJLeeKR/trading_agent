from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from agent_trading.domain.entities import InstrumentEntity
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.services.signal_backbone import PriceBar
from agent_trading.services.signal_feature_pipeline import (
    SignalFeatureBatchRow,
    SignalFeaturePipelineService,
)


def _make_bars(count: int = 80) -> list[PriceBar]:
    started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars: list[PriceBar] = []
    for idx in range(count):
        close_price = 100.0 + idx
        bars.append(
            PriceBar(
                timestamp=started_at + timedelta(days=idx),
                open_price=close_price - 1.0,
                high_price=close_price + 2.0,
                low_price=close_price - 2.0,
                close_price=close_price,
                volume=1000.0 + idx,
                turnover=(1000.0 + idx) * close_price,
            )
        )
    return bars


async def test_compute_snapshot_builds_signal_feature_entity() -> None:
    repos = build_in_memory_repositories()
    service = SignalFeaturePipelineService(repos)
    instrument = InstrumentEntity(
        instrument_id=uuid4(),
        symbol="005930",
        market_code="KRX",
        asset_class="KR_STOCK",
        currency="KRW",
        name="삼성전자",
        tick_size=Decimal("1"),
        lot_size=Decimal("1"),
    )

    snapshot = await service.compute_snapshot(
        SignalFeatureBatchRow(
            instrument=instrument,
            bars=_make_bars(),
        )
    )

    assert snapshot.instrument_id == instrument.instrument_id
    assert snapshot.timeframe == "1d"
    assert snapshot.feature_set_version == "signal_backbone_v1"
    assert snapshot.bar_count == 80
    assert snapshot.overall_score is not None
    assert snapshot.component_scores_json
    snapshot_at_kst = snapshot.snapshot_at.astimezone(timezone(timedelta(hours=9)))
    assert snapshot_at_kst.hour == 20
    assert snapshot_at_kst.minute == 0


async def test_compute_and_persist_saves_latest_snapshot() -> None:
    repos = build_in_memory_repositories()
    service = SignalFeaturePipelineService(repos)
    instrument = InstrumentEntity(
        instrument_id=uuid4(),
        symbol="000660",
        market_code="KRX",
        asset_class="KR_STOCK",
        currency="KRW",
        name="하이닉스",
        tick_size=Decimal("1"),
        lot_size=Decimal("1"),
    )

    saved = await service.compute_and_persist(
        SignalFeatureBatchRow(
            instrument=instrument,
            bars=_make_bars(),
        )
    )
    latest = await repos.signal_feature_snapshots.get_latest_by_instrument(
        instrument.instrument_id,
    )

    assert latest is not None
    assert latest.signal_feature_snapshot_id == saved.signal_feature_snapshot_id


async def test_compute_many_counts_persist_and_errors() -> None:
    repos = build_in_memory_repositories()
    service = SignalFeaturePipelineService(repos)
    instrument = InstrumentEntity(
        instrument_id=uuid4(),
        symbol="035420",
        market_code="KRX",
        asset_class="KR_STOCK",
        currency="KRW",
        name="네이버",
        tick_size=Decimal("1"),
        lot_size=Decimal("1"),
    )

    result = await service.compute_many(
        [
            SignalFeatureBatchRow(instrument=instrument, bars=_make_bars()),
            SignalFeatureBatchRow(instrument=instrument, bars=_make_bars(count=10)),
        ],
        persist=False,
    )

    assert result.processed == 2
    assert result.persisted == 0
    assert result.skipped == 1
    assert len(result.errors) == 1
    assert "최소 20개 일봉" in result.errors[0]
