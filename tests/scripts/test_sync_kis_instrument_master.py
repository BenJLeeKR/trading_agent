from __future__ import annotations

from decimal import Decimal
from datetime import datetime

import pytest

from agent_trading.domain.entities import InstrumentEntity
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.services.market_session import SessionInfo

from scripts.sync_kis_instrument_master import (
    AFTER_HOURS_SYNC_START,
    PRE_MARKET_SYNC_CUTOFF,
    _build_instrument,
    _classify,
    _evaluate_update_policy,
    _load_csv,
    _make_instrument_id,
    _parse_args,
    _sync_instruments,
)


def test_make_instrument_id_preserves_krx_seed_shape() -> None:
    assert _make_instrument_id("005930", "KRX") == _make_instrument_id("005930", "KRX")
    assert _make_instrument_id("005930", "KRX") != _make_instrument_id("005930", "NASDAQ")


def test_parse_args_defaults() -> None:
    args = _parse_args(["--csv", "data/test.csv"])
    assert args.csv == "data/test.csv"
    assert args.apply is False
    assert args.deactivate_missing is False
    assert args.deactivate_market_code == "KRX"
    assert args.default_market_code == "KRX"
    assert args.allow_intraday_apply is False
    assert args.ignore_update_policy is False


def test_evaluate_update_policy_allows_non_trading_day_apply() -> None:
    decision = _evaluate_update_policy(
        now_kst=datetime(2026, 6, 7, 10, 0, 0),
        session_info=SessionInfo(
            is_trading_day=False,
            source="fallback",
            reason_code="FALLBACK_WEEKEND",
            reason="주말",
        ),
        allow_intraday_apply=False,
    )
    assert decision.allowed is True
    assert decision.code == "NON_TRADING_DAY_ALLOWED"


def test_evaluate_update_policy_blocks_intraday_apply_on_trading_day() -> None:
    decision = _evaluate_update_policy(
        now_kst=datetime(2026, 6, 8, 10, 30, 0),
        session_info=SessionInfo(
            is_trading_day=True,
            source="kis_holiday_api",
            reason_code="KIS_HOLIDAY_TRADING_DAY",
            reason="거래일",
        ),
        allow_intraday_apply=False,
    )
    assert decision.allowed is False
    assert decision.code == "INTRADAY_APPLY_BLOCKED"
    assert PRE_MARKET_SYNC_CUTOFF.isoformat(timespec="seconds") in decision.message
    assert AFTER_HOURS_SYNC_START.isoformat(timespec="seconds") in decision.message


def test_evaluate_update_policy_allows_pre_market_and_after_hours() -> None:
    trading_day = SessionInfo(
        is_trading_day=True,
        source="kis_holiday_api",
        reason_code="KIS_HOLIDAY_TRADING_DAY",
        reason="거래일",
    )
    early = _evaluate_update_policy(
        now_kst=datetime(2026, 6, 8, 7, 59, 59),
        session_info=trading_day,
        allow_intraday_apply=False,
    )
    late = _evaluate_update_policy(
        now_kst=datetime(2026, 6, 8, 15, 30, 30),
        session_info=trading_day,
        allow_intraday_apply=False,
    )
    assert early.allowed is True
    assert early.code == "PRE_MARKET_ALLOWED"
    assert late.allowed is True
    assert late.code == "AFTER_HOURS_ALLOWED"


def test_evaluate_update_policy_allows_intraday_override() -> None:
    decision = _evaluate_update_policy(
        now_kst=datetime(2026, 6, 8, 11, 0, 0),
        session_info=SessionInfo(
            is_trading_day=True,
            source="kis_holiday_api",
            reason_code="KIS_HOLIDAY_TRADING_DAY",
            reason="거래일",
        ),
        allow_intraday_apply=True,
    )
    assert decision.allowed is True
    assert decision.code == "INTRADAY_OVERRIDE_ALLOWED"


def test_build_instrument_extracts_metadata() -> None:
    record = {
        "symbol": "005930",
        "name": "삼성전자",
        "market_code": "KRX",
        "name_kr": "삼성전자",
        "isin_code": "KR7005930003",
        "metadata_sector": "전자",
    }
    headers = {
        "symbol": "symbol",
        "name": "name",
        "market_code": "market_code",
        "name_kr": "name_kr",
        "isin_code": "isin_code",
        "metadata_sector": "metadata_sector",
    }
    instrument = _build_instrument(
        record,
        headers,
        default_market_code="KRX",
        default_asset_class="kr_stock",
        default_currency="KRW",
        source_tag="kis_master_csv",
    )
    assert instrument.symbol == "005930"
    assert instrument.metadata["name_kr"] == "삼성전자"
    assert instrument.metadata["isin_code"] == "KR7005930003"
    assert instrument.metadata["sector"] == "전자"


def test_load_csv_requires_symbol_and_name(tmp_path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("symbol\n005930\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Missing required column 'name'"):
        _load_csv(
            str(path),
            default_market_code="KRX",
            default_asset_class="kr_stock",
            default_currency="KRW",
            source_tag="kis_master_csv",
        )


@pytest.mark.asyncio
async def test_sync_instruments_deactivates_missing_rows() -> None:
    repos = build_in_memory_repositories()
    existing = InstrumentEntity(
        instrument_id=_make_instrument_id("000660", "KRX"),
        symbol="000660",
        market_code="KRX",
        asset_class="kr_stock",
        currency="KRW",
        name="SK하이닉스",
        tick_size=Decimal("100"),
        lot_size=Decimal("1"),
        is_active=True,
        metadata={"seed": True},
    )
    await repos.instruments.add(existing)
    incoming = [
        InstrumentEntity(
            instrument_id=_make_instrument_id("005930", "KRX"),
            symbol="005930",
            market_code="KRX",
            asset_class="kr_stock",
            currency="KRW",
            name="삼성전자",
            tick_size=Decimal("100"),
            lot_size=Decimal("1"),
            is_active=True,
            metadata={"sync_source": "kis_master_file"},
        )
    ]

    counters = await _sync_instruments(
        repos.instruments,
        incoming,
        dry_run=False,
        deactivate_missing=True,
        deactivate_market_code="KRX",
    )
    assert counters.inserted == 1
    assert counters.deactivated == 1
    deactivated = await repos.instruments.get_by_symbol("000660", "KRX")
    assert deactivated is not None
    assert deactivated.is_active is False
    assert deactivated.metadata["deactivated_by_sync"] is True


def test_classify_detects_metadata_change() -> None:
    existing = InstrumentEntity(
        instrument_id=_make_instrument_id("005930", "KRX"),
        symbol="005930",
        market_code="KRX",
        asset_class="kr_stock",
        currency="KRW",
        name="삼성전자",
        tick_size=Decimal("100"),
        lot_size=Decimal("1"),
        is_active=True,
        metadata={"source_tag": "old"},
    )
    incoming = InstrumentEntity(
        instrument_id=_make_instrument_id("005930", "KRX"),
        symbol="005930",
        market_code="KRX",
        asset_class="kr_stock",
        currency="KRW",
        name="삼성전자",
        tick_size=Decimal("100"),
        lot_size=Decimal("1"),
        is_active=True,
        metadata={"source_tag": "new"},
    )
    assert _classify(existing, incoming) == "update"
