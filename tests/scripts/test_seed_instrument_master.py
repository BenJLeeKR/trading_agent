"""Tests for ``scripts.seed_instrument_master`` — KRX instrument master seed.

검증 범위
---------
1. ``_make_instrument_id()`` — 결정적 UUID 생성
2. ``_make_instrument()`` — InstrumentEntity 생성 정확성
3. ``_classify_action()`` — INSERT / UPDATE / SKIP 분류 정확성
4. ``_format_diff()`` — diff 출력 포맷
5. ``_parse_args()`` — CLI 인자 파싱 (--csv, --dry-run, --apply)
6. ``_seed_instruments()`` — dry-run 모드에서 DB write 없음
7. ``_seed_instruments()`` — apply 모드에서 모든 seed upsert
8. ``_seed_instruments()`` — idempotent (재실행 시 모두 SKIP)
9. ``_load_csv()`` — CSV 파일 로드 정확성
10. AAPL/NASDAQ 등 해외 종목이 seed 목록에 없는지 확인
11. 005930(기존)이 SKIP 처리되는지 확인
"""
from __future__ import annotations

import csv
import io
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from agent_trading.domain.entities import InstrumentEntity
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer

# Module under test
from scripts.seed_instrument_master import (
    SEED_INSTRUMENTS,
    _ACTION_INSERT,
    _ACTION_SKIP,
    _ACTION_UPDATE,
    _classify_action,
    _format_diff,
    _load_csv,
    _make_instrument,
    _make_instrument_id,
    _parse_args,
    _seed_instruments,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAMSUNG_UUID = _make_instrument_id("005930")
SK_HYNIX_UUID = _make_instrument_id("000660")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repos() -> RepositoryContainer:
    """In-memory repos with 005930 pre-loaded."""
    container = build_in_memory_repositories()
    # Pre-load 005930 (삼성전자) as existing instrument
    samsung = InstrumentEntity(
        instrument_id=SAMSUNG_UUID,
        symbol="005930",
        market_code="KRX",
        asset_class="kr_stock",
        currency="KRW",
        name="Samsung Electronics",  # 영문명 (seed는 한글명)
        tick_size=Decimal("100"),
        lot_size=Decimal("1"),
        is_active=True,
        metadata={},
    )
    # Use the internal _items dict for direct injection
    container.instruments._items[SAMSUNG_UUID] = samsung  # type: ignore[attr-defined]
    return container


# ---------------------------------------------------------------------------
# _make_instrument_id
# ---------------------------------------------------------------------------


class TestMakeInstrumentId:
    def test_deterministic(self) -> None:
        """동일 symbol에 대해 항상 같은 UUID가 생성되어야 함."""
        uid1 = _make_instrument_id("005930")
        uid2 = _make_instrument_id("005930")
        assert uid1 == uid2

    def test_different_symbols(self) -> None:
        """다른 symbol은 다른 UUID를 생성해야 함."""
        uid1 = _make_instrument_id("005930")
        uid2 = _make_instrument_id("000660")
        assert uid1 != uid2

    def test_uuid5_namespace(self) -> None:
        """UUID v5 (SHA-1 based) 여야 함."""
        uid = _make_instrument_id("005930")
        assert uid.version == 5


# ---------------------------------------------------------------------------
# _make_instrument
# ---------------------------------------------------------------------------


class TestMakeInstrument:
    def test_basic(self) -> None:
        """InstrumentEntity가 올바르게 생성되어야 함."""
        inst = _make_instrument(
            "005930", "KRX", "kr_stock", "KRW",
            "삼성전자", "100", "1", True,
        )
        assert isinstance(inst, InstrumentEntity)
        assert inst.symbol == "005930"
        assert inst.market_code == "KRX"
        assert inst.asset_class == "kr_stock"
        assert inst.currency == "KRW"
        assert inst.name == "삼성전자"
        assert inst.tick_size == Decimal("100")
        assert inst.lot_size == Decimal("1")
        assert inst.is_active is True
        assert inst.metadata == {}
        assert inst.instrument_id == _make_instrument_id("005930")

    def test_deterministic_id(self) -> None:
        """동일 seed data에서 항상 같은 instrument_id가 생성되어야 함."""
        inst1 = _make_instrument(
            "000660", "KRX", "kr_stock", "KRW",
            "SK하이닉스", "100", "1", True,
        )
        inst2 = _make_instrument(
            "000660", "KRX", "kr_stock", "KRW",
            "SK하이닉스", "100", "1", True,
        )
        assert inst1.instrument_id == inst2.instrument_id


# ---------------------------------------------------------------------------
# _classify_action
# ---------------------------------------------------------------------------


class TestClassifyAction:
    def test_insert_when_none(self) -> None:
        """existing이 None이면 INSERT."""
        seed = _make_instrument(
            "000660", "KRX", "kr_stock", "KRW",
            "SK하이닉스", "100", "1", True,
        )
        action, diffs = _classify_action(None, seed)
        assert action == _ACTION_INSERT
        assert diffs is None

    def test_skip_when_identical(self) -> None:
        """모든 mutable field가 동일하면 SKIP."""
        existing = _make_instrument(
            "005930", "KRX", "kr_stock", "KRW",
            "삼성전자", "100", "1", True,
        )
        seed = _make_instrument(
            "005930", "KRX", "kr_stock", "KRW",
            "삼성전자", "100", "1", True,
        )
        action, diffs = _classify_action(existing, seed)
        assert action == _ACTION_SKIP
        assert diffs is None

    def test_update_when_name_differs(self) -> None:
        """name이 다르면 UPDATE."""
        existing = _make_instrument(
            "005930", "KRX", "kr_stock", "KRW",
            "Samsung Electronics", "100", "1", True,
        )
        seed = _make_instrument(
            "005930", "KRX", "kr_stock", "KRW",
            "삼성전자", "100", "1", True,
        )
        action, diffs = _classify_action(existing, seed)
        assert action == _ACTION_UPDATE
        assert diffs is not None
        assert "name" in diffs

    def test_update_when_tick_size_differs(self) -> None:
        """tick_size가 다르면 UPDATE."""
        existing = _make_instrument(
            "005930", "KRX", "kr_stock", "KRW",
            "삼성전자", "50", "1", True,
        )
        seed = _make_instrument(
            "005930", "KRX", "kr_stock", "KRW",
            "삼성전자", "100", "1", True,
        )
        action, diffs = _classify_action(existing, seed)
        assert action == _ACTION_UPDATE
        assert diffs is not None
        assert "tick_size" in diffs

    def test_update_when_is_active_differs(self) -> None:
        """is_active가 다르면 UPDATE."""
        existing = _make_instrument(
            "005930", "KRX", "kr_stock", "KRW",
            "삼성전자", "100", "1", False,
        )
        seed = _make_instrument(
            "005930", "KRX", "kr_stock", "KRW",
            "삼성전자", "100", "1", True,
        )
        action, diffs = _classify_action(existing, seed)
        assert action == _ACTION_UPDATE
        assert diffs is not None
        assert "is_active" in diffs


# ---------------------------------------------------------------------------
# _format_diff
# ---------------------------------------------------------------------------


class TestFormatDiff:
    def test_insert_format(self) -> None:
        seed = _make_instrument(
            "000660", "KRX", "kr_stock", "KRW",
            "SK하이닉스", "100", "1", True,
        )
        line = _format_diff(_ACTION_INSERT, seed, None, None)
        assert "INSERT" in line
        assert "000660" in line
        assert "SK하이닉스" in line

    def test_skip_format(self) -> None:
        existing = _make_instrument(
            "005930", "KRX", "kr_stock", "KRW",
            "삼성전자", "100", "1", True,
        )
        seed = _make_instrument(
            "005930", "KRX", "kr_stock", "KRW",
            "삼성전자", "100", "1", True,
        )
        line = _format_diff(_ACTION_SKIP, seed, existing, None)
        assert "SKIP" in line
        assert "005930" in line
        assert "no changes" in line

    def test_update_format(self) -> None:
        existing = _make_instrument(
            "005930", "KRX", "kr_stock", "KRW",
            "Samsung", "100", "1", True,
        )
        seed = _make_instrument(
            "005930", "KRX", "kr_stock", "KRW",
            "삼성전자", "100", "1", True,
        )
        line = _format_diff(_ACTION_UPDATE, seed, existing, ["name"])
        assert "UPDATE" in line
        assert "005930" in line
        assert "name:" in line
        assert "Samsung" in line
        assert "삼성전자" in line


# ---------------------------------------------------------------------------
# _parse_args
# ---------------------------------------------------------------------------


class TestParseArgs:
    def test_default_dry_run(self) -> None:
        """인자 없이 실행하면 --dry-run이 기본값이어야 함."""
        args = _parse_args([])
        assert args.dry_run is True
        assert args.apply is False

    def test_dry_run_explicit(self) -> None:
        """--dry-run을 명시하면 dry_run=True."""
        args = _parse_args(["--dry-run"])
        assert args.dry_run is True

    def test_apply_overrides_dry_run(self) -> None:
        """--apply를 주면 dry_run이 override되어야 함."""
        args = _parse_args(["--apply"])
        assert args.apply is True

    def test_apply_and_dry_run(self) -> None:
        """--apply와 --dry-run을 동시에 주면 --apply가 우선."""
        args = _parse_args(["--dry-run", "--apply"])
        assert args.apply is True


# ---------------------------------------------------------------------------
# _seed_instruments — dry-run / apply / idempotent
# ---------------------------------------------------------------------------


class TestSeedInstruments:
    """_seed_instruments() 단위 테스트 (InMemory repository 직접 사용)."""

    @pytest.mark.asyncio
    async def test_dry_run_no_db_write(self, repos: RepositoryContainer) -> None:
        """dry-run 모드에서는 DB write가 발생하지 않아야 함.

        InMemory repository의 upsert_by_symbol이 호출되지 않음을 검증.
        """
        repo = repos.instruments

        inserted, updated, skipped = await _seed_instruments(repo, SEED_INSTRUMENTS, dry_run=True)

        # dry-run: 분류는 실제와 동일하지만 write는 발생하지 않음
        # 005930은 name이 'Samsung Electronics' → '삼성전자'로 달라 UPDATE 분류
        assert inserted == 9  # 005930 제외 9개 신규
        assert updated == 1  # 005930 name update (dry-run이므로 write는 안 됨)
        assert skipped == 0

        # dry-run 이후에도 005930만 존재해야 함 (새로 INSERT되지 않음)
        samsung = await repo.get_by_symbol("005930", "KRX")
        assert samsung is not None
        # name은 여전히 'Samsung Electronics' (UPDATE되지 않음)
        assert samsung.name == "Samsung Electronics"

        sk_hynix = await repo.get_by_symbol("000660", "KRX")
        assert sk_hynix is None  # INSERT되지 않음

    @pytest.mark.asyncio
    async def test_apply_inserts_all_seed(self, repos: RepositoryContainer) -> None:
        """apply 모드에서는 모든 seed instrument가 upsert되어야 함."""
        repo = repos.instruments

        inserted, updated, skipped = await _seed_instruments(repo, SEED_INSTRUMENTS, dry_run=False)

        assert inserted == 9
        assert updated == 1  # 005930 name update
        assert skipped == 0

        # 모든 seed symbol이 존재해야 함
        for row in SEED_INSTRUMENTS:
            symbol = row[0]
            inst = await repo.get_by_symbol(symbol, "KRX")
            assert inst is not None, f"{symbol} should exist after apply"
            assert inst.name == row[4], f"{symbol} name mismatch"

    @pytest.mark.asyncio
    async def test_apply_idempotent(self, repos: RepositoryContainer) -> None:
        """apply를 두 번 실행해도 에러 없이 모두 SKIP 처리되어야 함."""
        repo = repos.instruments

        # First apply
        inserted1, updated1, skipped1 = await _seed_instruments(repo, SEED_INSTRUMENTS, dry_run=False)
        assert inserted1 == 9
        assert updated1 == 1

        # Second apply (idempotent)
        inserted2, updated2, skipped2 = await _seed_instruments(repo, SEED_INSTRUMENTS, dry_run=False)
        assert inserted2 == 0
        assert updated2 == 0
        assert skipped2 == 10  # 모두 SKIP

        # 모든 seed symbol이 존재하고 이름이 일치해야 함
        for row in SEED_INSTRUMENTS:
            symbol = row[0]
            inst = await repo.get_by_symbol(symbol, "KRX")
            assert inst is not None
            assert inst.name == row[4]

    @pytest.mark.asyncio
    async def test_005930_updated_to_korean_name(self, repos: RepositoryContainer) -> None:
        """005930(삼성전자)은 기존 영문명 → 한글명으로 UPDATE되어야 함."""
        repo = repos.instruments

        inserted, updated, skipped = await _seed_instruments(repo, SEED_INSTRUMENTS, dry_run=False)

        assert inserted == 9
        assert updated == 1  # 005930 name update
        assert skipped == 0

        samsung = await repo.get_by_symbol("005930", "KRX")
        assert samsung is not None
        # name이 seed 값으로 UPDATE되어야 함
        assert samsung.name == "삼성전자"


# ---------------------------------------------------------------------------
# AAPL/NASDAQ exclusion check
# ---------------------------------------------------------------------------


class TestNoNonKrxInSeed:
    """해외 종목(AAPL 등)이 SEED_INSTRUMENTS에 없는지 확인."""

    def test_no_aapl(self) -> None:
        symbols = {row[0] for row in SEED_INSTRUMENTS}
        assert "AAPL" not in symbols, "AAPL should not be in KRX seed"

    def test_all_krx_market(self) -> None:
        for row in SEED_INSTRUMENTS:
            assert row[1] == "KRX", f"{row[0]} market_code should be KRX"

    def test_all_kr_stock_asset_class(self) -> None:
        for row in SEED_INSTRUMENTS:
            assert row[2] == "kr_stock", f"{row[0]} asset_class should be kr_stock"

    def test_all_krw_currency(self) -> None:
        for row in SEED_INSTRUMENTS:
            assert row[3] == "KRW", f"{row[0]} currency should be KRW"

    def test_seed_count(self) -> None:
        """정확히 10개 seed symbol이 있어야 함."""
        assert len(SEED_INSTRUMENTS) == 10


# ---------------------------------------------------------------------------
# SEED_INSTRUMENTS data integrity
# ---------------------------------------------------------------------------


class TestSeedDataIntegrity:
    """SEED_INSTRUMENTS 데이터 무결성 검증."""

    def test_no_duplicate_symbols(self) -> None:
        symbols = [row[0] for row in SEED_INSTRUMENTS]
        assert len(symbols) == len(set(symbols)), "Duplicate symbols in SEED_INSTRUMENTS"

    def test_all_symbols_are_strings(self) -> None:
        for row in SEED_INSTRUMENTS:
            assert isinstance(row[0], str)
            assert len(row[0]) == 6, f"{row[0]} should be 6-digit KRX symbol"

    def test_all_active(self) -> None:
        for row in SEED_INSTRUMENTS:
            assert row[7] is True, f"{row[0]} should be active"

    def test_tick_size_positive(self) -> None:
        for row in SEED_INSTRUMENTS:
            ts = Decimal(row[5])
            assert ts > 0, f"{row[0]} tick_size should be positive"

    def test_lot_size_positive(self) -> None:
        for row in SEED_INSTRUMENTS:
            ls = Decimal(row[6])
            assert ls > 0, f"{row[0]} lot_size should be positive"


# ---------------------------------------------------------------------------
# _load_csv() tests
# ---------------------------------------------------------------------------


class TestLoadCsv:
    """_load_csv() 단위 테스트."""

    def _make_csv(self, content: str) -> str:
        """테스트용 임시 CSV 파일 경로를 생성 (tempfile 사용)."""
        import tempfile
        import os
        fd, path = tempfile.mkstemp(suffix=".csv", prefix="test_seed_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_valid_csv(self) -> None:
        """정상 CSV 파일 로드."""
        csv_content = "symbol,name\n005930,삼성전자\n000660,SK하이닉스\n"
        path = self._make_csv(csv_content)
        try:
            result = _load_csv(path)
            assert len(result) == 2
            assert result[0][0] == "005930"
            assert result[0][4] == "삼성전자"  # name
            assert result[0][1] == "KRX"  # default market_code
            assert result[0][2] == "kr_stock"  # default asset_class
            assert result[0][3] == "KRW"  # default currency
            assert result[0][5] == "100"  # default tick_size
            assert result[0][6] == "1"  # default lot_size
            assert result[0][7] is True  # default is_active
            assert result[1][0] == "000660"
            assert result[1][4] == "SK하이닉스"
        finally:
            import os
            os.unlink(path)

    def test_all_columns_explicit(self) -> None:
        """모든 컬럼을 명시적으로 지정한 CSV."""
        csv_content = (
            "symbol,market_code,asset_class,currency,name,tick_size,lot_size,is_active\n"
            "005930,KRX,kr_stock,KRW,삼성전자,100,1,TRUE\n"
        )
        path = self._make_csv(csv_content)
        try:
            result = _load_csv(path)
            assert len(result) == 1
            assert result[0] == ("005930", "KRX", "kr_stock", "KRW", "삼성전자", "100", "1", True)
        finally:
            import os
            os.unlink(path)

    def test_bom_header(self) -> None:
        """BOM (utf-8-sig) 헤더 처리."""
        csv_content = "\ufeffsymbol,name\n005930,삼성전자\n"
        path = self._make_csv(csv_content)
        try:
            result = _load_csv(path)
            assert len(result) == 1
            assert result[0][0] == "005930"
        finally:
            import os
            os.unlink(path)

    def test_missing_symbol_column(self) -> None:
        """symbol 컬럼이 누락된 경우 ValueError 발생."""
        csv_content = "name\n삼성전자\n"
        path = self._make_csv(csv_content)
        try:
            with pytest.raises(ValueError, match="Missing required column"):
                _load_csv(path)
        finally:
            import os
            os.unlink(path)

    def test_empty_file(self) -> None:
        """빈 CSV 파일 (헤더만 있음) → 빈 리스트 반환."""
        csv_content = "symbol,name\n"
        path = self._make_csv(csv_content)
        try:
            result = _load_csv(path)
            assert len(result) == 0
        finally:
            import os
            os.unlink(path)

    def test_extra_columns_ignored(self) -> None:
        """정의되지 않은 추가 컬럼 (instrument_id, is_tradable 등)은 무시."""
        csv_content = (
            "instrument_id,symbol,name,is_tradable\n"
            "some-uuid,005930,삼성전자,TRUE\n"
        )
        path = self._make_csv(csv_content)
        try:
            result = _load_csv(path)
            assert len(result) == 1
            assert result[0][0] == "005930"
            assert result[0][4] == "삼성전자"
        finally:
            import os
            os.unlink(path)

    def test_is_active_false(self) -> None:
        """is_active=FALSE 처리."""
        csv_content = "symbol,name,is_active\n005930,삼성전자,FALSE\n"
        path = self._make_csv(csv_content)
        try:
            result = _load_csv(path)
            assert result[0][7] is False
        finally:
            import os
            os.unlink(path)

    def test_is_active_variants(self) -> None:
        """is_active 다양한 truthy/falsy 값 처리."""
        csv_content = (
            "symbol,name,is_active\n"
            "A,test1,TRUE\n"
            "B,test2,true\n"
            "C,test3,1\n"
            "D,test4,YES\n"
            "E,test5,Y\n"
            "F,test6,FALSE\n"
            "G,test7,false\n"
            "H,test8,0\n"
            "I,test9,NO\n"
            "J,test10,N\n"
        )
        path = self._make_csv(csv_content)
        try:
            result = _load_csv(path)
            assert len(result) == 10
            for i in range(5):
                assert result[i][7] is True, f"row {i} should be active"
            for i in range(5, 10):
                assert result[i][7] is False, f"row {i} should be inactive"
        finally:
            import os
            os.unlink(path)

    def test_whitespace_stripping(self) -> None:
        """컬럼 값의 leading/trailing whitespace 제거."""
        csv_content = "symbol,name\n 005930 , 삼성전자 \n"
        path = self._make_csv(csv_content)
        try:
            result = _load_csv(path)
            assert result[0][0] == "005930"
            assert result[0][4] == "삼성전자"
        finally:
            import os
            os.unlink(path)

    def test_case_insensitive_header(self) -> None:
        """헤더 이름 대소문자 구분 없이 매핑."""
        csv_content = "SYMBOL,NAME\n005930,삼성전자\n"
        path = self._make_csv(csv_content)
        try:
            result = _load_csv(path)
            assert result[0][0] == "005930"
            assert result[0][4] == "삼성전자"
        finally:
            import os
            os.unlink(path)

    def test_kospi200_csv_format(self) -> None:
        """실제 kospi200_instruments.csv 포맷 호환성 검증."""
        csv_content = (
            "instrument_id,symbol,name,market_code,asset_class,currency,"
            "tick_size,lot_size,is_tradable,is_active\n"
            "550e8400-e29b-41d4-a716-446655440000,005930,삼성전자,KRX,kr_stock,KRW,100,1,TRUE,TRUE\n"
            "550e8400-e29b-41d4-a716-446655440001,000660,SK하이닉스,KRX,kr_stock,KRW,100,1,TRUE,TRUE\n"
        )
        path = self._make_csv(csv_content)
        try:
            result = _load_csv(path)
            assert len(result) == 2
            # instrument_id와 is_tradable은 무시됨
            assert result[0] == ("005930", "KRX", "kr_stock", "KRW", "삼성전자", "100", "1", True)
            assert result[1] == ("000660", "KRX", "kr_stock", "KRW", "SK하이닉스", "100", "1", True)
        finally:
            import os
            os.unlink(path)
