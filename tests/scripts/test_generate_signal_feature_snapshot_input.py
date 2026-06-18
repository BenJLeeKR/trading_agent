from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent_trading.brokers.rate_limit import BudgetExhaustedError
from scripts.generate_signal_feature_snapshot_input import (
    DEFAULT_SIGNAL_FEATURE_BATCH_PAUSE_SECONDS,
    DEFAULT_SIGNAL_FEATURE_BATCH_SIZE,
    DEFAULT_SIGNAL_FEATURE_BUDGET_RETRY_ATTEMPTS,
    DEFAULT_SIGNAL_FEATURE_BUDGET_RETRY_SLEEP_SECONDS,
    DEFAULT_SIGNAL_FEATURE_CORE_CAP,
    DEFAULT_SIGNAL_FEATURE_MARKET_OVERLAY_CAP,
    DEFAULT_SIGNAL_FEATURE_PRE_POOL_SIZE,
    DEFAULT_SIGNAL_FEATURE_UNIVERSE_MAX_CAP,
    SignalFeatureInputRow,
    _build_rows,
    _estimate_budget_retry_sleep_seconds,
    _normalize_bar,
    _parse_args,
    _parse_end_date,
    _write_rows,
)
from scripts.run_decision_loop import UniverseSymbol


def test_parse_args_defaults() -> None:
    args = _parse_args([])
    assert args.output == "data/signal_feature_snapshot_input.json"
    assert args.lookback_days == 180
    assert args.timeframe == "1d"
    assert args.feature_set_version == "signal_backbone_v1"
    assert args.universe_max_cap == DEFAULT_SIGNAL_FEATURE_UNIVERSE_MAX_CAP
    assert args.core_cap == DEFAULT_SIGNAL_FEATURE_CORE_CAP
    assert args.market_overlay_cap == DEFAULT_SIGNAL_FEATURE_MARKET_OVERLAY_CAP
    assert args.pre_pool_size == DEFAULT_SIGNAL_FEATURE_PRE_POOL_SIZE
    assert args.output_format == "text"
    assert args.batch_size == DEFAULT_SIGNAL_FEATURE_BATCH_SIZE
    assert args.batch_pause_seconds == DEFAULT_SIGNAL_FEATURE_BATCH_PAUSE_SECONDS
    assert args.budget_retry_attempts == DEFAULT_SIGNAL_FEATURE_BUDGET_RETRY_ATTEMPTS
    assert args.budget_retry_sleep_seconds == DEFAULT_SIGNAL_FEATURE_BUDGET_RETRY_SLEEP_SECONDS


def test_parse_end_date_supports_both_formats() -> None:
    assert _parse_end_date("2026-06-16") == date(2026, 6, 16)
    assert _parse_end_date("20260616") == date(2026, 6, 16)


def test_normalize_bar_maps_kis_fields() -> None:
    bar = _normalize_bar(
        {
            "stck_bsop_date": "20260616",
            "stck_oprc": "100",
            "stck_hgpr": "110",
            "stck_lwpr": "95",
            "stck_clpr": "108",
            "acml_vol": "12345",
            "acml_tr_pbmn": "999999",
        }
    )
    assert bar.timestamp == "2026-06-16T00:00:00+00:00"
    assert bar.open_price == 100.0
    assert bar.high_price == 110.0
    assert bar.low_price == 95.0
    assert bar.close_price == 108.0
    assert bar.volume == 12345.0
    assert bar.turnover == 999999.0


def test_write_rows_creates_json_file(tmp_path) -> None:
    path = tmp_path / "signal_input.json"
    _write_rows(
        str(path),
        [
            SignalFeatureInputRow(
                symbol="005930",
                market="KRX",
                timeframe="1d",
                feature_set_version="signal_backbone_v1",
                bars=(),
            )
        ],
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload[0]["symbol"] == "005930"
    assert payload[0]["market"] == "KRX"


def test_estimate_budget_retry_sleep_seconds_uses_refill_rate_maximum() -> None:
    client = SimpleNamespace(
        budget_manager=SimpleNamespace(
            market_data=SimpleNamespace(refill_rate=0.5),
            global_rest=SimpleNamespace(refill_rate=2.0),
        )
    )

    assert _estimate_budget_retry_sleep_seconds(client, 1.0) == 2.0


@pytest.mark.asyncio
async def test_build_rows_retries_on_market_data_budget_exhaustion(monkeypatch) -> None:
    universe = [UniverseSymbol(symbol="005930", market="KRX", source_type="core")]
    response = [
        {
            "stck_bsop_date": "20260616",
            "stck_oprc": "100",
            "stck_hgpr": "110",
            "stck_lwpr": "95",
            "stck_clpr": "108",
            "acml_vol": "12345",
        }
        for _ in range(20)
    ]
    client = SimpleNamespace(
        budget_manager=SimpleNamespace(
            market_data=SimpleNamespace(refill_rate=1.0),
            global_rest=SimpleNamespace(refill_rate=1.0),
        ),
        inquire_daily_itemchartprice=AsyncMock(
            side_effect=[
                BudgetExhaustedError("market_data", "Bucket 'market_data' exhausted"),
                response,
            ]
        ),
    )
    sleep_calls: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("scripts.generate_signal_feature_snapshot_input.asyncio.sleep", _fake_sleep)

    rows, errors = await _build_rows(
        client,
        universe=universe,
        end_date=date(2026, 6, 17),
        lookback_days=30,
        timeframe="1d",
        feature_set_version="signal_backbone_v1",
        batch_size=0,
        batch_pause_seconds=0.0,
        budget_retry_attempts=3,
        budget_retry_sleep_seconds=1.0,
    )

    assert len(rows) == 1
    assert errors == []
    assert sleep_calls == [1.0]
    assert client.inquire_daily_itemchartprice.await_count == 2


@pytest.mark.asyncio
async def test_build_rows_accepts_registered_kosdaq_market() -> None:
    universe = [UniverseSymbol(symbol="090150", market="KOSDAQ", source_type="core")]
    response = [
        {
            "stck_bsop_date": "20260616",
            "stck_oprc": "100",
            "stck_hgpr": "110",
            "stck_lwpr": "95",
            "stck_clpr": "108",
            "acml_vol": "12345",
        }
        for _ in range(20)
    ]
    client = SimpleNamespace(
        budget_manager=SimpleNamespace(
            market_data=SimpleNamespace(refill_rate=1.0),
            global_rest=SimpleNamespace(refill_rate=1.0),
        ),
        inquire_daily_itemchartprice=AsyncMock(return_value=response),
    )

    rows, errors = await _build_rows(
        client,
        universe=universe,
        end_date=date(2026, 6, 17),
        lookback_days=30,
        timeframe="1d",
        feature_set_version="signal_backbone_v1",
        batch_size=0,
        batch_pause_seconds=0.0,
        budget_retry_attempts=1,
        budget_retry_sleep_seconds=1.0,
    )

    assert len(rows) == 1
    assert rows[0].market == "KOSDAQ"
    assert errors == []
