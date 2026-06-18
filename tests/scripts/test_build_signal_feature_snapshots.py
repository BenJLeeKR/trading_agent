from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from scripts.build_signal_feature_snapshots import (
    _load_rows,
    _parse_args,
    _run,
    _result_to_json,
)
from agent_trading.domain.entities import SignalFeatureSnapshotEntity
from agent_trading.services.signal_feature_pipeline import SignalFeatureBatchResult
from uuid import uuid4
from decimal import Decimal


def test_parse_args_defaults() -> None:
    args = _parse_args(["--input", "sample.json"])

    assert args.input == "sample.json"
    assert args.default_market == "KRX"
    assert args.default_timeframe == "1d"
    assert args.feature_set_version == "signal_backbone_v1"
    assert args.dry_run is False
    assert args.output == "text"


def test_load_rows_applies_defaults(tmp_path) -> None:
    path = tmp_path / "bars.json"
    path.write_text(
        json.dumps(
            [
                {
                    "symbol": "005930",
                    "bars": [
                        {
                            "timestamp": "2026-06-16T00:00:00+00:00",
                            "open_price": 100,
                            "high_price": 110,
                            "low_price": 95,
                            "close_price": 108,
                            "volume": 1000,
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    rows = _load_rows(
        str(path),
        default_market="KRX",
        default_timeframe="1d",
        feature_set_version="signal_backbone_v1",
    )

    assert len(rows) == 1
    assert rows[0].symbol == "005930"
    assert rows[0].market == "KRX"
    assert rows[0].timeframe == "1d"
    assert rows[0].feature_set_version == "signal_backbone_v1"
    assert rows[0].bars[0].timestamp == datetime(2026, 6, 16, tzinfo=timezone.utc)


def test_result_to_json_serializes_snapshot_payload() -> None:
    snapshot = SignalFeatureSnapshotEntity(
        signal_feature_snapshot_id=uuid4(),
        instrument_id=uuid4(),
        timeframe="1d",
        snapshot_at=datetime(2026, 6, 16, tzinfo=timezone.utc),
        feature_set_version="signal_backbone_v1",
        bar_count=80,
        overall_score=Decimal("0.42"),
        average_turnover_20d=Decimal("120000000.50"),
        turnover_surge_ratio=Decimal("1.88"),
        component_scores_json={"slow_momentum": 0.5},
    )

    payload = json.loads(
        _result_to_json(
            SignalFeatureBatchResult(
                processed=1,
                persisted=1,
                skipped=0,
                errors=(),
                snapshots=(snapshot,),
            )
        )
    )

    assert payload["processed"] == 1
    assert payload["persisted"] == 1
    assert payload["snapshots"][0]["timeframe"] == "1d"
    assert payload["snapshots"][0]["overall_score"] == "0.42"
    assert payload["snapshots"][0]["average_turnover_20d"] == "120000000.50"
    assert payload["snapshots"][0]["turnover_surge_ratio"] == "1.88"


@pytest.mark.asyncio
async def test_run_uses_runtime_repositories_without_db_pool(tmp_path) -> None:
    path = tmp_path / "bars.json"
    path.write_text(
        json.dumps(
            [
                {
                    "symbol": "005930",
                    "market": "KRX",
                    "timeframe": "1d",
                    "feature_set_version": "signal_backbone_v1",
                    "bars": [
                        {
                            "timestamp": "2026-06-16T00:00:00+00:00",
                            "open_price": 100,
                            "high_price": 110,
                            "low_price": 95,
                            "close_price": 108,
                            "volume": 1000,
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    instrument = SimpleNamespace(instrument_id=uuid4(), symbol="005930")
    repos = SimpleNamespace(
        instruments=SimpleNamespace(
            get_by_symbol=AsyncMock(return_value=instrument),
        )
    )
    batch_result = SignalFeatureBatchResult(
        processed=1,
        persisted=1,
        skipped=0,
        errors=(),
        snapshots=(),
    )
    service = AsyncMock()
    service.compute_many = AsyncMock(return_value=batch_result)

    @asynccontextmanager
    async def _mock_postgres_runtime(*args, **kwargs):
        yield {"repositories": repos}

    with patch(
        "scripts.build_signal_feature_snapshots.postgres_runtime",
        _mock_postgres_runtime,
    ):
        with patch(
            "scripts.build_signal_feature_snapshots.SignalFeaturePipelineService",
            return_value=service,
        ):
            rc = await _run(_parse_args(["--input", str(path), "--output", "json"]))

    assert rc == 0
    repos.instruments.get_by_symbol.assert_awaited_once_with(
        symbol="005930",
        market_code="KRX",
    )
    service.compute_many.assert_awaited_once()
