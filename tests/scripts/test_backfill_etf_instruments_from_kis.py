from __future__ import annotations

import argparse
from unittest.mock import AsyncMock

import pytest

from agent_trading.repositories.bootstrap import build_in_memory_repositories

from scripts.backfill_etf_instruments_from_kis import (
    ETF_SECURITY_GROUP_CODE,
    BackfillCounters,
    _backfill,
    _build_etf_instrument,
    _collect_symbols,
    _derive_market_segment,
    _load_symbols_file,
    _parse_args,
    _validate_etf_symbol,
)

# KIS CTPF1002R 실측 응답 예시(KODEX 200) — reference_docs/
# kis_openapi_full_20260503_markdown/103_주식기본조회.md Response Example를
# ETF 케이스에 맞게 각색.
_KODEX200_PAYLOAD = {
    "pdno": "069500",
    "prdt_type_cd": "300",
    "mket_id_cd": "ETF",
    "scty_grp_id_cd": "EF",
    "excg_dvsn_cd": "02",
    "kospi200_item_yn": "N",
    "scts_mket_lstg_dt": "20021014",
    "kosdaq_mket_lstg_dt": "",
    "etf_dvsn_cd": "1",
    "etf_type_cd": "01",
    "lstg_abol_dt": "",
    "prdt_name": "코덱스200",
    "prdt_name120": "코덱스200",
    "prdt_abrv_name": "KODEX 200",
    "std_pdno": "KR7069500007",
    "prdt_eng_name": "KODEX 200",
    "tr_stop_yn": "N",
    "admn_item_yn": "N",
}

_SAMSUNG_STOCK_PAYLOAD = {
    "pdno": "005930",
    "prdt_type_cd": "300",
    "mket_id_cd": "STK",
    "scty_grp_id_cd": "ST",
    "excg_dvsn_cd": "02",
    "prdt_abrv_name": "삼성전자",
    "std_pdno": "KR7005930003",
    "lstg_abol_dt": "",
}


def _make_args(**overrides) -> argparse.Namespace:
    base = _parse_args(["--symbols", "069500"])
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


class TestSymbolValidationAndCollection:
    def test_validate_etf_symbol_accepts_six_digits(self) -> None:
        assert _validate_etf_symbol(" 069500 ") == "069500"

    def test_validate_etf_symbol_rejects_wrong_length(self) -> None:
        assert _validate_etf_symbol("Q500001") is None  # 7자리 — ETN 전용 포맷
        assert _validate_etf_symbol("12345") is None  # 5자리

    def test_validate_etf_symbol_accepts_alphanumeric_six_char_code(self) -> None:
        """최근 상장 ETF 중 다수가 영숫자 혼합 6자리 코드다(예: 0000D0)."""
        assert _validate_etf_symbol(" 0000d0 ") == "0000D0"

    def test_validate_etf_symbol_rejects_non_alnum(self) -> None:
        assert _validate_etf_symbol("00-0D0") is None

    def test_collect_symbols_dedupes_and_preserves_order(self) -> None:
        args = _make_args(symbols="069500,102110,069500", symbols_file=None)
        assert _collect_symbols(args) == ["069500", "102110"]

    def test_collect_symbols_skips_invalid_with_warning(self, caplog) -> None:
        args = _make_args(symbols="069500,BADCODE", symbols_file=None)
        symbols = _collect_symbols(args)
        assert symbols == ["069500"]

    def test_load_symbols_file_ignores_comments_and_header(self, tmp_path) -> None:
        path = tmp_path / "symbols.txt"
        path.write_text("symbol\n# comment\n069500\n\n102110,TIGER 200\n")
        assert _load_symbols_file(str(path)) == ["069500", "102110"]

    def test_load_symbols_file_missing_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            _load_symbols_file("does/not/exist.txt")


class TestMarketSegmentDerivation:
    def test_excg_dvsn_cd_02_maps_to_kospi(self) -> None:
        assert _derive_market_segment({"excg_dvsn_cd": "02"}) == "KOSPI"

    def test_excg_dvsn_cd_03_maps_to_kosdaq(self) -> None:
        assert _derive_market_segment({"excg_dvsn_cd": "03"}) == "KOSDAQ"

    def test_falls_back_to_listing_date_fields_when_excg_dvsn_cd_unknown(self) -> None:
        assert _derive_market_segment(
            {"excg_dvsn_cd": "99", "kosdaq_mket_lstg_dt": "20200101"}
        ) == "KOSDAQ"
        assert _derive_market_segment(
            {"excg_dvsn_cd": "99", "scts_mket_lstg_dt": "20200101"}
        ) == "KOSPI"

    def test_returns_none_when_no_evidence(self) -> None:
        assert _derive_market_segment({}) is None


class TestBuildEtfInstrument:
    def test_maps_kis_fields_to_instrument_entity(self) -> None:
        instrument = _build_etf_instrument(
            "069500",
            _KODEX200_PAYLOAD,
            market_code="KRX",
            currency="KRW",
            source_tag="kis_ctpf1002r_live",
        )
        assert instrument.symbol == "069500"
        assert instrument.name == "KODEX 200"
        assert instrument.market_code == "KRX"
        assert instrument.exchange_code == "KRX"
        assert instrument.market_segment == "KOSPI"
        assert instrument.asset_class == "kr_etf"
        assert instrument.currency == "KRW"
        assert instrument.is_active is True
        assert instrument.metadata["std_pdno"] == "KR7069500007"
        assert instrument.metadata["scty_grp_id_cd"] == ETF_SECURITY_GROUP_CODE

    def test_falls_back_to_prdt_name_when_abrv_name_missing(self) -> None:
        payload = dict(_KODEX200_PAYLOAD)
        del payload["prdt_abrv_name"]
        instrument = _build_etf_instrument(
            "069500", payload, market_code="KRX", currency="KRW", source_tag="tag"
        )
        assert instrument.name == "코덱스200"

    def test_delisted_symbol_is_inactive(self) -> None:
        payload = dict(_KODEX200_PAYLOAD, lstg_abol_dt="20260101")
        instrument = _build_etf_instrument(
            "069500", payload, market_code="KRX", currency="KRW", source_tag="tag"
        )
        assert instrument.is_active is False


class TestBackfill:
    async def test_inserts_new_etf_instrument(self) -> None:
        repos = build_in_memory_repositories()
        client = AsyncMock()
        client.get_stock_basic_info = AsyncMock(return_value=_KODEX200_PAYLOAD)
        args = _make_args(apply=True)

        counters = await _backfill(client, repos.instruments, ["069500"], args=args)

        assert counters == BackfillCounters(inserted=1)
        stored = await repos.instruments.get_by_symbol_any_market("069500")
        assert stored is not None
        assert stored.name == "KODEX 200"
        assert stored.asset_class == "kr_etf"

    async def test_dry_run_does_not_persist(self) -> None:
        repos = build_in_memory_repositories()
        client = AsyncMock()
        client.get_stock_basic_info = AsyncMock(return_value=_KODEX200_PAYLOAD)
        args = _make_args(apply=False)

        counters = await _backfill(client, repos.instruments, ["069500"], args=args)

        assert counters.inserted == 1  # 카운트는 되지만
        stored = await repos.instruments.get_by_symbol_any_market("069500")
        assert stored is None  # 실제로는 저장되지 않음

    async def test_skips_non_etf_by_default(self) -> None:
        repos = build_in_memory_repositories()
        client = AsyncMock()
        client.get_stock_basic_info = AsyncMock(return_value=_SAMSUNG_STOCK_PAYLOAD)
        args = _make_args(apply=True)

        counters = await _backfill(client, repos.instruments, ["005930"], args=args)

        assert counters == BackfillCounters(skipped_non_etf=1)
        assert await repos.instruments.get_by_symbol_any_market("005930") is None

    async def test_allow_non_etf_flag_forces_insert(self) -> None:
        repos = build_in_memory_repositories()
        client = AsyncMock()
        client.get_stock_basic_info = AsyncMock(return_value=_SAMSUNG_STOCK_PAYLOAD)
        args = _make_args(apply=True, allow_non_etf=True)

        counters = await _backfill(client, repos.instruments, ["005930"], args=args)

        assert counters.inserted == 1
        assert await repos.instruments.get_by_symbol_any_market("005930") is not None

    async def test_empty_payload_is_skipped(self) -> None:
        repos = build_in_memory_repositories()
        client = AsyncMock()
        client.get_stock_basic_info = AsyncMock(return_value={})
        args = _make_args(apply=True)

        counters = await _backfill(client, repos.instruments, ["999999"], args=args)

        assert counters == BackfillCounters(skipped_empty_payload=1)

    async def test_exception_from_kis_is_counted_as_error_and_does_not_raise(self) -> None:
        repos = build_in_memory_repositories()
        client = AsyncMock()
        client.get_stock_basic_info = AsyncMock(side_effect=RuntimeError("network error"))
        args = _make_args(apply=True)

        counters = await _backfill(client, repos.instruments, ["069500"], args=args)

        assert counters == BackfillCounters(errors=1)

    async def test_existing_canonical_instrument_is_skipped(self) -> None:
        repos = build_in_memory_repositories()
        # 이미 동일한 canonical 데이터가 있으면(placeholder 아님) 덮어쓰지 않고 skip.
        seed = _build_etf_instrument(
            "069500",
            _KODEX200_PAYLOAD,
            market_code="KRX",
            currency="KRW",
            source_tag="kis_ctpf1002r_live",
        )
        await repos.instruments.upsert_by_symbol(seed)

        client = AsyncMock()
        client.get_stock_basic_info = AsyncMock(return_value=_KODEX200_PAYLOAD)
        args = _make_args(apply=True)

        counters = await _backfill(client, repos.instruments, ["069500"], args=args)

        assert counters == BackfillCounters(skipped_existing_canonical=1)

    async def test_promotes_placeholder_instrument(self) -> None:
        repos = build_in_memory_repositories()
        from decimal import Decimal

        from agent_trading.domain.entities import InstrumentEntity
        from scripts.sync_kis_instrument_master import _make_instrument_id

        placeholder = InstrumentEntity(
            instrument_id=_make_instrument_id("069500", "KRX"),
            symbol="069500",
            market_code="KRX",
            asset_class="kr_stock",
            currency="KRW",
            name="[PLACEHOLDER] 069500",
            tick_size=Decimal("1"),
            lot_size=Decimal("1"),
            is_active=False,
            exchange_code="KRX",
            market_segment=None,
            metadata={"placeholder": True},
        )
        await repos.instruments.upsert_by_symbol(placeholder)

        client = AsyncMock()
        client.get_stock_basic_info = AsyncMock(return_value=_KODEX200_PAYLOAD)
        args = _make_args(apply=True)

        counters = await _backfill(client, repos.instruments, ["069500"], args=args)

        assert counters == BackfillCounters(updated=1)
        stored = await repos.instruments.get_by_symbol_any_market("069500")
        assert stored.name == "KODEX 200"
        assert stored.asset_class == "kr_etf"


class TestParseArgs:
    def test_defaults(self) -> None:
        args = _parse_args(["--symbols", "069500"])
        assert args.symbols == "069500"
        assert args.symbols_file is None
        assert args.apply is False
        assert args.allow_non_etf is False
        assert args.market_code == "KRX"
        assert args.currency == "KRW"
        assert args.product_type_code == "300"
