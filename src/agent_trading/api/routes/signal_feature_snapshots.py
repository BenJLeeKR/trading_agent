"""Signal feature snapshot inspection endpoints.

Provides read-only access to deterministic signal feature snapshots
persisted per instrument/timeframe.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import (
    DecisionContextSignalFeatureCoverageView,
    SignalFeatureSnapshotView,
)
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import DecisionContextQuery

router = APIRouter(tags=["signal-feature-snapshots"])


def _float_or_none(value: object) -> float | None:
    return float(value) if value is not None else None


def _to_view(snapshot: object, *, symbol: str, market_code: str) -> SignalFeatureSnapshotView:
    return SignalFeatureSnapshotView(
        signal_feature_snapshot_id=snapshot.signal_feature_snapshot_id,
        instrument_id=snapshot.instrument_id,
        symbol=symbol,
        market_code=market_code,
        timeframe=snapshot.timeframe,
        snapshot_at=snapshot.snapshot_at,
        feature_set_version=snapshot.feature_set_version,
        bar_count=snapshot.bar_count,
        sma_5=_float_or_none(snapshot.sma_5),
        sma_20=_float_or_none(snapshot.sma_20),
        sma_60=_float_or_none(snapshot.sma_60),
        price_vs_sma_20_pct=_float_or_none(snapshot.price_vs_sma_20_pct),
        price_vs_sma_60_pct=_float_or_none(snapshot.price_vs_sma_60_pct),
        return_1m_pct=_float_or_none(snapshot.return_1m_pct),
        return_3m_pct=_float_or_none(snapshot.return_3m_pct),
        volatility_20d_pct=_float_or_none(snapshot.volatility_20d_pct),
        atr_14_pct=_float_or_none(snapshot.atr_14_pct),
        rsi_14=_float_or_none(snapshot.rsi_14),
        average_volume_20d=_float_or_none(snapshot.average_volume_20d),
        average_turnover_20d=_float_or_none(snapshot.average_turnover_20d),
        volume_surge_ratio=_float_or_none(snapshot.volume_surge_ratio),
        turnover_surge_ratio=_float_or_none(snapshot.turnover_surge_ratio),
        fast_score=_float_or_none(snapshot.fast_score),
        slow_score=_float_or_none(snapshot.slow_score),
        overall_score=_float_or_none(snapshot.overall_score),
        component_scores_json=snapshot.component_scores_json,
        reason_codes=snapshot.reason_codes,
        created_at=snapshot.created_at,
    )


@router.get(
    "/signal-feature-snapshots",
    response_model=list[SignalFeatureSnapshotView],
)
async def list_signal_feature_snapshots(
    symbol: str = Query(..., description="Instrument symbol"),
    market: str = Query("KRX", description="Market code"),
    timeframe: str = Query("1d", description="Timeframe code"),
    limit: int = Query(20, ge=1, le=200, description="Max results"),
    repos: RepositoryContainer = Depends(get_repos),
) -> list[SignalFeatureSnapshotView]:
    instrument = await repos.instruments.get_by_symbol(
        symbol=symbol,
        market_code=market,
    )
    if instrument is None:
        raise HTTPException(status_code=404, detail="Instrument not found")
    snapshots = await repos.signal_feature_snapshots.list_by_instrument(
        instrument.instrument_id,
        timeframe=timeframe,
        limit=limit,
    )
    return [
        _to_view(snapshot, symbol=instrument.symbol, market_code=instrument.market_code)
        for snapshot in snapshots
    ]


@router.get(
    "/signal-feature-snapshots/latest",
    response_model=SignalFeatureSnapshotView,
)
async def get_latest_signal_feature_snapshot(
    symbol: str = Query(..., description="Instrument symbol"),
    market: str = Query("KRX", description="Market code"),
    timeframe: str = Query("1d", description="Timeframe code"),
    repos: RepositoryContainer = Depends(get_repos),
) -> SignalFeatureSnapshotView:
    instrument = await repos.instruments.get_by_symbol(
        symbol=symbol,
        market_code=market,
    )
    if instrument is None:
        raise HTTPException(status_code=404, detail="Instrument not found")
    snapshot = await repos.signal_feature_snapshots.get_latest_by_instrument(
        instrument.instrument_id,
        timeframe=timeframe,
    )
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail="No signal feature snapshot found for this instrument",
        )
    return _to_view(snapshot, symbol=instrument.symbol, market_code=instrument.market_code)


@router.get(
    "/signal-feature-snapshots/decision-context-coverage",
    response_model=DecisionContextSignalFeatureCoverageView,
)
async def get_signal_feature_decision_context_coverage(
    limit: int = Query(50, ge=1, le=500, description="Recent decision context sample size"),
    repos: RepositoryContainer = Depends(get_repos),
) -> DecisionContextSignalFeatureCoverageView:
    contexts = await repos.decision_contexts.list(
        DecisionContextQuery(limit=limit)
    )
    anchored = [
        ctx for ctx in contexts
        if ctx.signal_feature_snapshot_id is not None
    ]
    missing = [
        ctx for ctx in contexts
        if ctx.signal_feature_snapshot_id is None
    ]
    total = len(contexts)
    coverage_rate = (len(anchored) / total) if total > 0 else 0.0
    return DecisionContextSignalFeatureCoverageView(
        recent_context_count=total,
        anchored_context_count=len(anchored),
        missing_context_count=len(missing),
        coverage_rate=coverage_rate,
        sampled_missing_context_ids=[
            ctx.decision_context_id
            for ctx in missing[:10]
        ],
    )
