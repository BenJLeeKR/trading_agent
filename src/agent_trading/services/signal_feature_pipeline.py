from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from agent_trading.domain.entities import InstrumentEntity, SignalFeatureSnapshotEntity
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.signal_backbone import (
    PriceBar,
    build_signal_feature_entity,
    build_signal_snapshot,
)


@dataclass(slots=True, frozen=True)
class SignalFeatureBatchRow:
    """배치 1건의 입력."""

    instrument: InstrumentEntity
    bars: Sequence[PriceBar]
    timeframe: str = "1d"
    feature_set_version: str = "signal_backbone_v1"


@dataclass(slots=True, frozen=True)
class SignalFeatureBatchResult:
    """배치 계산 결과 요약."""

    processed: int = 0
    persisted: int = 0
    skipped: int = 0
    errors: tuple[str, ...] = ()
    snapshots: tuple[SignalFeatureSnapshotEntity, ...] = ()


class SignalFeaturePipelineService:
    """결정론적 signal feature 계산 및 저장 파이프라인."""

    def __init__(self, repos: RepositoryContainer) -> None:
        self._repos = repos

    async def compute_snapshot(
        self,
        row: SignalFeatureBatchRow,
    ) -> SignalFeatureSnapshotEntity:
        features, score_card = build_signal_snapshot(
            row.instrument.symbol,
            list(row.bars),
        )
        return build_signal_feature_entity(
            instrument_id=row.instrument.instrument_id,
            features=features,
            score_card=score_card,
            timeframe=row.timeframe,
            feature_set_version=row.feature_set_version,
        )

    async def compute_and_persist(
        self,
        row: SignalFeatureBatchRow,
    ) -> SignalFeatureSnapshotEntity:
        snapshot = await self.compute_snapshot(row)
        return await self._repos.signal_feature_snapshots.add(snapshot)

    async def compute_many(
        self,
        rows: Sequence[SignalFeatureBatchRow],
        *,
        persist: bool,
    ) -> SignalFeatureBatchResult:
        snapshots: list[SignalFeatureSnapshotEntity] = []
        errors: list[str] = []
        processed = 0
        persisted = 0
        skipped = 0

        for row in rows:
            processed += 1
            try:
                if persist:
                    snapshot = await self.compute_and_persist(row)
                    persisted += 1
                else:
                    snapshot = await self.compute_snapshot(row)
                    skipped += 1
                snapshots.append(snapshot)
            except Exception as exc:
                errors.append(
                    f"{row.instrument.symbol}:{row.timeframe}:{exc}"
                )

        return SignalFeatureBatchResult(
            processed=processed,
            persisted=persisted,
            skipped=skipped,
            errors=tuple(errors),
            snapshots=tuple(snapshots),
        )
