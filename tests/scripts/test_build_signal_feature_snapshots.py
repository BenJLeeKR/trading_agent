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
    assert args.trigger_type == "after_market_scheduler"


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

    assert len(rows.rows) == 1
    assert rows.rows[0].symbol == "005930"
    assert rows.rows[0].market == "KRX"
    assert rows.rows[0].timeframe == "1d"
    assert rows.rows[0].feature_set_version == "signal_backbone_v1"
    assert rows.rows[0].bars[0].timestamp == datetime(2026, 6, 16, tzinfo=timezone.utc)


def test_load_rows_accepts_v2_object_payload(tmp_path) -> None:
    path = tmp_path / "bars_v2.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "signal_feature_input.v2",
                "universe_metadata": {
                    "universe_freeze_run_id": "freeze-1",
                    "trigger_type": "after_market_scheduler",
                    "universe_count": 1,
                    "symbols": [
                        {
                            "symbol": "005930",
                            "market": "KRX",
                            "source_type": "core",
                            "inclusion_reason": "approved_core_universe",
                        }
                    ],
                },
                "fetch_success_rows": [
                    {
                        "symbol": "005930",
                        "market": "KRX",
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
                ],
                "fetch_error_rows": [
                    {
                        "symbol": "000001",
                        "market": "KRX",
                        "error_code": "timeout",
                        "error_message": "request timeout",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    rows = _load_rows(
        str(path),
        default_market="KRX",
        default_timeframe="1d",
        feature_set_version="signal_backbone_v1",
    )

    assert len(rows.rows) == 1
    assert rows.rows[0].symbol == "005930"
    assert rows.rows[0].market == "KRX"
    assert rows.universe_metadata["universe_freeze_run_id"] == "freeze-1"
    assert len(rows.fetch_error_rows) == 1


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
        component_scores_json={
            "slow_momentum": 0.5,
            "diagnostics": {
                "bar_count": 80,
                "overall_bucket": "non_negative",
                "fast_bucket": "non_negative",
                "slow_bucket": "non_negative",
                "missing_feature_flags": [],
                "input_quality_flags": [],
                "reason_code_count": 1,
            },
            "shadow_signal_backbone_variant": "signal_backbone_v1_shadow_v2",
            "shadow_slow_score_v2": 0.41,
            "shadow_fast_score_v2": 0.33,
            "shadow_overall_score_v2": 0.37,
            "shadow_component_scores_v2": {"slow_momentum": 0.55},
            "shadow_reason_codes_v2": ["momentum_3m_positive"],
            "shadow_diagnostics_v2": {
                "bar_count": 80,
                "overall_bucket": "non_negative",
                "fast_bucket": "non_negative",
                "slow_bucket": "non_negative",
                "missing_feature_flags": [],
                "input_quality_flags": [],
                "reason_code_count": 1,
            },
            "shadow_signal_backbone_variant_v5": "signal_backbone_v1_shadow_v5",
            "shadow_slow_score_v5": 0.28,
            "shadow_fast_score_v5": 0.33,
            "shadow_overall_score_v5": 0.30,
            "shadow_component_scores_v5": {"slow_momentum": 0.35},
            "shadow_reason_codes_v5": ["momentum_3m_soft_negative_shadow_v5"],
            "shadow_diagnostics_v5": {
                "bar_count": 80,
                "overall_bucket": "non_negative",
                "fast_bucket": "non_negative",
                "slow_bucket": "non_negative",
                "missing_feature_flags": [],
                "input_quality_flags": [],
                "reason_code_count": 1,
            },
        },
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
    assert payload["snapshots"][0]["component_scores_json"]["diagnostics"]["overall_bucket"] == (
        "non_negative"
    )


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
        ),
        signal_feature_batch_runs=SimpleNamespace(add=AsyncMock()),
        signal_feature_batch_run_items=SimpleNamespace(add_many=AsyncMock()),
    )
    repos.signal_feature_batch_runs.add = AsyncMock(
        side_effect=lambda run: run
    )
    batch_result = SignalFeatureBatchResult(
        processed=1,
        persisted=1,
        skipped=0,
        errors=(),
        snapshots=(
            SignalFeatureSnapshotEntity(
                signal_feature_snapshot_id=uuid4(),
                instrument_id=instrument.instrument_id,
                timeframe="1d",
                snapshot_at=datetime(2026, 6, 16, tzinfo=timezone.utc),
                feature_set_version="signal_backbone_v1",
                bar_count=80,
                overall_score=Decimal("0.42"),
                fast_score=Decimal("0.33"),
                slow_score=Decimal("0.48"),
                component_scores_json={
                    "slow_momentum": 0.5,
                    "diagnostics": {
                        "bar_count": 80,
                        "overall_bucket": "non_negative",
                        "fast_bucket": "non_negative",
                        "slow_bucket": "non_negative",
                        "missing_feature_flags": [],
                        "input_quality_flags": [],
                        "reason_code_count": 1,
                    },
                    "shadow_signal_backbone_variant": "signal_backbone_v1_shadow_v2",
                    "shadow_slow_score_v2": 0.41,
                    "shadow_fast_score_v2": 0.33,
                    "shadow_overall_score_v2": 0.37,
                    "shadow_component_scores_v2": {"slow_momentum": 0.55},
                    "shadow_reason_codes_v2": ["momentum_3m_positive"],
                    "shadow_diagnostics_v2": {
                        "bar_count": 80,
                        "overall_bucket": "non_negative",
                        "fast_bucket": "non_negative",
                        "slow_bucket": "non_negative",
                        "missing_feature_flags": [],
                        "input_quality_flags": [],
                        "reason_code_count": 1,
                    },
                    "shadow_signal_backbone_variant_v5": "signal_backbone_v1_shadow_v5",
                    "shadow_slow_score_v5": 0.28,
                    "shadow_fast_score_v5": 0.33,
                    "shadow_overall_score_v5": 0.30,
                    "shadow_component_scores_v5": {"slow_momentum": 0.35},
                    "shadow_reason_codes_v5": ["momentum_3m_soft_negative_shadow_v5"],
                    "shadow_diagnostics_v5": {
                        "bar_count": 80,
                        "overall_bucket": "non_negative",
                        "fast_bucket": "non_negative",
                        "slow_bucket": "non_negative",
                        "missing_feature_flags": [],
                        "input_quality_flags": [],
                        "reason_code_count": 1,
                    },
                },
                reason_codes=["momentum_3m_strong"],
            ),
        ),
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
    repos.signal_feature_batch_runs.add.assert_awaited_once()
    repos.signal_feature_batch_run_items.add_many.assert_awaited_once()
    saved_run = repos.signal_feature_batch_runs.add.await_args.args[0]
    assert saved_run.trigger_type == "after_market_scheduler"
    quality_summary = saved_run.summary_json["snapshot_quality"]
    assert quality_summary["snapshot_count"] == 1
    assert quality_summary["overall_missing_count"] == 0
    assert quality_summary["overall_bucket_counts"]["non_negative"] == 1
    assert "shadow_overall_bucket_counts_v2" in quality_summary
    assert "shadow_overall_bucket_counts_v5" in quality_summary
    saved_items = repos.signal_feature_batch_run_items.add_many.await_args.args[0]
    assert len(saved_items) == 1
    assert saved_items[0].metadata_json["overall_bucket"] == "non_negative"
    assert saved_items[0].metadata_json["bar_count"] == 80
    assert "shadow_signal_backbone_variant" in saved_items[0].metadata_json


@pytest.mark.asyncio
async def test_run_dry_run_does_not_store_unpersisted_snapshot_fk(tmp_path) -> None:
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
        ),
        signal_feature_batch_runs=SimpleNamespace(add=AsyncMock()),
        signal_feature_batch_run_items=SimpleNamespace(add_many=AsyncMock()),
    )
    repos.signal_feature_batch_runs.add = AsyncMock(side_effect=lambda run: run)
    batch_result = SignalFeatureBatchResult(
        processed=1,
        persisted=0,
        skipped=1,
        errors=(),
        snapshots=(
            SignalFeatureSnapshotEntity(
                signal_feature_snapshot_id=uuid4(),
                instrument_id=instrument.instrument_id,
                timeframe="1d",
                snapshot_at=datetime(2026, 6, 16, tzinfo=timezone.utc),
                feature_set_version="signal_backbone_v1",
                bar_count=80,
                overall_score=Decimal("0.42"),
                fast_score=Decimal("0.33"),
                slow_score=Decimal("0.48"),
                component_scores_json={
                    "slow_momentum": 0.5,
                    "diagnostics": {
                        "bar_count": 80,
                        "overall_bucket": "non_negative",
                        "fast_bucket": "non_negative",
                        "slow_bucket": "non_negative",
                        "missing_feature_flags": [],
                        "input_quality_flags": [],
                        "reason_code_count": 1,
                    },
                    "shadow_signal_backbone_variant": "signal_backbone_v1_shadow_v2",
                    "shadow_slow_score_v2": 0.41,
                    "shadow_fast_score_v2": 0.33,
                    "shadow_overall_score_v2": 0.37,
                    "shadow_component_scores_v2": {"slow_momentum": 0.55},
                    "shadow_reason_codes_v2": ["momentum_3m_positive"],
                    "shadow_diagnostics_v2": {
                        "bar_count": 80,
                        "overall_bucket": "non_negative",
                        "fast_bucket": "non_negative",
                        "slow_bucket": "non_negative",
                        "missing_feature_flags": [],
                        "input_quality_flags": [],
                        "reason_code_count": 1,
                    },
                    "shadow_signal_backbone_variant_v5": "signal_backbone_v1_shadow_v5",
                    "shadow_slow_score_v5": 0.28,
                    "shadow_fast_score_v5": 0.33,
                    "shadow_overall_score_v5": 0.30,
                    "shadow_component_scores_v5": {"slow_momentum": 0.35},
                    "shadow_reason_codes_v5": ["momentum_3m_soft_negative_shadow_v5"],
                    "shadow_diagnostics_v5": {
                        "bar_count": 80,
                        "overall_bucket": "non_negative",
                        "fast_bucket": "non_negative",
                        "slow_bucket": "non_negative",
                        "missing_feature_flags": [],
                        "input_quality_flags": [],
                        "reason_code_count": 1,
                    },
                },
                reason_codes=["momentum_3m_strong"],
            ),
        ),
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
            rc = await _run(
                _parse_args(["--input", str(path), "--dry-run", "--output", "json"])
            )

    assert rc == 0
    saved_items = repos.signal_feature_batch_run_items.add_many.await_args.args[0]
    assert len(saved_items) == 1
    assert saved_items[0].status == "computed"
    assert saved_items[0].signal_feature_snapshot_id is None
    assert saved_items[0].snapshot_at is None
