from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from agent_trading.domain.entities import InstrumentEntity
from agent_trading.domain.enums import AssetClass


class TestInstrumentRepositoryContract:
    """Verify that InstrumentRepository implementations satisfy the contract."""

    @pytest.mark.asyncio
    async def test_add_and_get(self, in_memory_repos, sample_instrument) -> None:
        created = await in_memory_repos.instruments.add(sample_instrument)
        assert created.instrument_id == sample_instrument.instrument_id

        fetched = await in_memory_repos.instruments.get(sample_instrument.instrument_id)
        assert fetched is not None
        assert fetched.symbol == "005930"
        assert fetched.name == "Samsung Electronics"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, in_memory_repos) -> None:
        result = await in_memory_repos.instruments.get(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_symbol(self, in_memory_repos, sample_instrument) -> None:
        await in_memory_repos.instruments.add(sample_instrument)

        fetched = await in_memory_repos.instruments.get_by_symbol(
            "005930", "KRX"
        )
        assert fetched is not None
        assert fetched.instrument_id == sample_instrument.instrument_id

    @pytest.mark.asyncio
    async def test_get_by_symbol_nonexistent_returns_none(
        self, in_memory_repos
    ) -> None:
        result = await in_memory_repos.instruments.get_by_symbol(
            "NONEXISTENT", "KRX"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_symbol_any_market_prefers_krx_canonical_row(
        self,
        in_memory_repos,
    ) -> None:
        symbol = "T001800"
        older_krx = InstrumentEntity(
            instrument_id=uuid4(),
            symbol=symbol,
            market_code="KRX",
            asset_class=AssetClass.KR_STOCK.value,
            currency="KRW",
            name="오리온홀딩스",
            is_active=True,
            exchange_code="KRX",
            created_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
        )
        newer_kospi = InstrumentEntity(
            instrument_id=uuid4(),
            symbol=symbol,
            market_code="KOSPI",
            asset_class=AssetClass.KR_STOCK.value,
            currency="KRW",
            name="오리온홀딩스",
            is_active=True,
            exchange_code="KRX",
            market_segment="KOSPI",
            created_at=datetime(2026, 6, 19, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 19, tzinfo=timezone.utc),
        )
        await in_memory_repos.instruments.add(newer_kospi)
        await in_memory_repos.instruments.add(older_krx)

        fetched = await in_memory_repos.instruments.get_by_symbol_any_market(symbol)

        assert fetched is not None
        assert fetched.market_code == "KRX"
        assert fetched.instrument_id == older_krx.instrument_id

    @pytest.mark.asyncio
    async def test_get_by_symbol_any_market_prefers_active_krx_segment_row_when_no_legacy_krx(
        self,
        in_memory_repos,
    ) -> None:
        symbol = "T005930"
        inactive_other = InstrumentEntity(
            instrument_id=uuid4(),
            symbol=symbol,
            market_code="US",
            asset_class=AssetClass.US_STOCK.value,
            currency="USD",
            name="Samsung ADR",
            is_active=False,
            exchange_code="NASDAQ",
            created_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
        )
        active_kospi = InstrumentEntity(
            instrument_id=uuid4(),
            symbol=symbol,
            market_code="KOSPI",
            asset_class=AssetClass.KR_STOCK.value,
            currency="KRW",
            name="삼성전자",
            is_active=True,
            exchange_code="KRX",
            market_segment="KOSPI",
            created_at=datetime(2026, 6, 19, tzinfo=timezone.utc),
            updated_at=datetime(2026, 6, 19, tzinfo=timezone.utc),
        )
        await in_memory_repos.instruments.add(inactive_other)
        await in_memory_repos.instruments.add(active_kospi)

        fetched = await in_memory_repos.instruments.get_by_symbol_any_market(symbol)

        assert fetched is not None
        assert fetched.instrument_id == active_kospi.instrument_id
        assert fetched.exchange_code == "KRX"
        assert fetched.market_segment == "KOSPI"


@pytest.mark.asyncio
async def test_postgres_get_by_symbol_any_market_prefers_krx_canonical_row(
    postgres_repos,
) -> None:
    symbol = "T001800"
    older_krx = InstrumentEntity(
        instrument_id=uuid4(),
        symbol=symbol,
        market_code="KRX",
        asset_class=AssetClass.KR_STOCK.value,
        currency="KRW",
        name="오리온홀딩스",
        is_active=True,
        exchange_code="KRX",
        created_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
    )
    newer_kospi = InstrumentEntity(
        instrument_id=uuid4(),
        symbol=symbol,
        market_code="KOSPI",
        asset_class=AssetClass.KR_STOCK.value,
        currency="KRW",
        name="오리온홀딩스",
        is_active=True,
        exchange_code="KRX",
        market_segment="KOSPI",
        created_at=datetime(2026, 6, 19, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 19, tzinfo=timezone.utc),
    )
    await postgres_repos.instruments.add(newer_kospi)
    await postgres_repos.instruments.add(older_krx)

    fetched = await postgres_repos.instruments.get_by_symbol_any_market(symbol)

    assert fetched is not None
    assert fetched.market_code == "KRX"
    assert fetched.instrument_id == older_krx.instrument_id


@pytest.mark.asyncio
async def test_postgres_get_by_symbol_any_market_prefers_active_krx_segment_row_when_no_legacy_krx(
    postgres_repos,
) -> None:
    symbol = "T005930"
    inactive_other = InstrumentEntity(
        instrument_id=uuid4(),
        symbol=symbol,
        market_code="US",
        asset_class=AssetClass.US_STOCK.value,
        currency="USD",
        name="Samsung ADR",
        is_active=False,
        exchange_code="NASDAQ",
        created_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
    )
    active_kospi = InstrumentEntity(
        instrument_id=uuid4(),
        symbol=symbol,
        market_code="KOSPI",
        asset_class=AssetClass.KR_STOCK.value,
        currency="KRW",
        name="삼성전자",
        is_active=True,
        exchange_code="KRX",
        market_segment="KOSPI",
        created_at=datetime(2026, 6, 19, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 19, tzinfo=timezone.utc),
    )
    await postgres_repos.instruments.add(inactive_other)
    await postgres_repos.instruments.add(active_kospi)

    fetched = await postgres_repos.instruments.get_by_symbol_any_market(symbol)

    assert fetched is not None
    assert fetched.instrument_id == active_kospi.instrument_id
    assert fetched.exchange_code == "KRX"
    assert fetched.market_segment == "KOSPI"


@pytest.mark.asyncio
async def test_postgres_get_by_symbols_any_market_batches_and_applies_same_tiebreak(
    postgres_repos,
) -> None:
    """Batch variant should return the same tie-broken row per symbol as
    calling ``get_by_symbol_any_market`` once per symbol, in a single query."""
    symbol_a = "T009900"
    symbol_b = "T009901"
    older_krx_a = InstrumentEntity(
        instrument_id=uuid4(),
        symbol=symbol_a,
        market_code="KRX",
        asset_class=AssetClass.KR_STOCK.value,
        currency="KRW",
        name="배치조회A-구KRX",
        is_active=True,
        exchange_code="KRX",
        created_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 18, tzinfo=timezone.utc),
    )
    newer_kospi_a = InstrumentEntity(
        instrument_id=uuid4(),
        symbol=symbol_a,
        market_code="KOSPI",
        asset_class=AssetClass.KR_STOCK.value,
        currency="KRW",
        name="배치조회A-신KOSPI",
        is_active=True,
        exchange_code="KRX",
        market_segment="KOSPI",
        created_at=datetime(2026, 6, 19, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 19, tzinfo=timezone.utc),
    )
    single_b = InstrumentEntity(
        instrument_id=uuid4(),
        symbol=symbol_b,
        market_code="KOSDAQ",
        asset_class=AssetClass.KR_STOCK.value,
        currency="KRW",
        name="배치조회B",
        is_active=True,
        exchange_code="KRX",
        market_segment="KOSDAQ",
    )
    await postgres_repos.instruments.add(newer_kospi_a)
    await postgres_repos.instruments.add(older_krx_a)
    await postgres_repos.instruments.add(single_b)

    result = await postgres_repos.instruments.get_by_symbols_any_market(
        [symbol_a, symbol_b, "T_NOT_FOUND"]
    )

    assert set(result.keys()) == {symbol_a, symbol_b}
    # 심볼 A는 단건 조회와 동일하게 legacy KRX row를 우선해야 한다.
    assert result[symbol_a].instrument_id == older_krx_a.instrument_id
    assert result[symbol_b].instrument_id == single_b.instrument_id


@pytest.mark.asyncio
async def test_postgres_get_by_symbols_any_market_empty_input_returns_empty_dict(
    postgres_repos,
) -> None:
    result = await postgres_repos.instruments.get_by_symbols_any_market([])
    assert result == {}
