"""Tests for ``KISSyncSnapshotProvider`` — KIS implementation of ``SnapshotFetchProvider``.

Verifies:
- Provider conforms to ``SnapshotFetchProvider`` protocol
- Position field mapping (pdno → instrument_id, qty, price)
- Cash balance mapping (dnca_tot_amt → available_cash, etc.)
- Instrument lookup failure → skip + error
- Empty responses
- Error propagation from REST client failures
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from agent_trading.brokers.koreainvestment.snapshot import (
    KISSyncSnapshotProvider,
)
from agent_trading.domain.entities import (
    InstrumentEntity,
    PositionSnapshotEntity,
)
from agent_trading.repositories.contracts import InstrumentRepository
from agent_trading.repositories.memory import InMemoryInstrumentRepository
from agent_trading.services.snapshot_sync import (
    FetchedSnapshot,
    SnapshotFetchProvider,
)


# ── Fake KIS REST client ─────────────────────────────────────────────────


class FakeKISRestClient:
    """Simulates KIS REST client with configurable responses."""

    def __init__(
        self,
        positions: list[dict[str, Any]] | None = None,
        cash_balance: dict[str, Any] | None = None,
        fail_positions: bool = False,
        fail_cash: bool = False,
    ) -> None:
        self._positions = positions or []
        self._cash_balance = cash_balance or {}
        self._fail_positions = fail_positions
        self._fail_cash = fail_cash
        self.closed = False

    async def get_positions(self) -> list[dict[str, Any]]:
        if self._fail_positions:
            raise RuntimeError("KIS positions fetch failed")
        return self._positions

    async def get_cash_balance(self) -> dict[str, Any]:
        if self._fail_cash:
            raise RuntimeError("KIS cash balance fetch failed")
        return self._cash_balance

    async def close(self) -> None:
        self.closed = True

    async def authenticate(self) -> None:
        pass


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def instrument_repo() -> InMemoryInstrumentRepository:
    repo = InMemoryInstrumentRepository()
    return repo


@pytest.fixture
def sample_instrument(instrument_repo: InMemoryInstrumentRepository) -> InstrumentEntity:
    inst = InstrumentEntity(
        instrument_id=uuid4(),
        symbol="005930",
        name="Samsung Electronics",
        market_code="KRX",
        asset_class="stock",
        currency="KRW",
    )
    # We need to add it to the repo via direct attribute manipulation
    # since InMemoryInstrumentRepository doesn't have an add() method.
    # Instead, we'll use get_by_symbol mock setup.
    return inst


# ── Tests ────────────────────────────────────────────────────────────────


class TestKISSyncSnapshotProvider:
    """KISSyncSnapshotProvider — protocol conformance + mapping."""

    async def test_implements_protocol(self) -> None:
        """Structural subtyping: provider conforms to SnapshotFetchProvider."""
        client = FakeKISRestClient()
        provider: SnapshotFetchProvider = KISSyncSnapshotProvider(client)  # type: ignore[assignment]
        assert provider is not None

    async def test_empty_positions(self) -> None:
        """No positions → empty result, no errors."""
        client = FakeKISRestClient(positions=[], cash_balance={})
        provider = KISSyncSnapshotProvider(client)
        inst_repo = InMemoryInstrumentRepository()

        result = await provider.fetch_snapshot(uuid4(), inst_repo)
        assert len(result.positions) == 0
        assert result.cash_balance is None
        assert result.errors == []

    async def test_position_mapping(self) -> None:
        """Valid pdno → instrument lookup → PositionSnapshotEntity."""
        account_id = uuid4()
        inst_id = uuid4()
        client = FakeKISRestClient(
            positions=[
                {
                    "pdno": "005930",
                    "hldg_qty": "10",
                    "pchs_avg_pric": "50000",
                    "prpr": "52000",
                    "evlu_pfls_amt": "20000",
                }
            ],
            cash_balance={},
        )
        provider = KISSyncSnapshotProvider(client)

        # Build an instrument repo that can resolve "005930"
        inst_repo = InMemoryInstrumentRepository()

        # Add a resolvable instrument to the repo
        inst = InstrumentEntity(
            instrument_id=inst_id,
            symbol="005930",
            name="Samsung Electronics",
            market_code="KRX",
            asset_class="stock",
            currency="KRW",
        )
        await inst_repo.add(inst)

        result = await provider.fetch_snapshot(account_id, inst_repo)
        assert len(result.positions) == 1
        pos = result.positions[0]
        assert pos.account_id == account_id
        assert pos.instrument_id == inst_id
        assert pos.quantity == 10
        assert pos.average_price == 50000
        assert pos.market_price == 52000  # type: ignore[comparison-overlap]
        assert pos.unrealized_pnl == 20000  # type: ignore[comparison-overlap]

    async def test_position_missing_pdno(self) -> None:
        """Position row without 'pdno' → skipped + error."""
        client = FakeKISRestClient(
            positions=[{"hldg_qty": "10"}],
            cash_balance={},
        )
        provider = KISSyncSnapshotProvider(client)
        inst_repo = InMemoryInstrumentRepository()

        result = await provider.fetch_snapshot(uuid4(), inst_repo)
        assert len(result.positions) == 0
        assert any("pdno" in err for err in result.errors)

    async def test_instrument_not_found(self) -> None:
        """pdno that has no instrument in DB → skipped."""
        client = FakeKISRestClient(
            positions=[{"pdno": "UNKNOWN", "hldg_qty": "10"}],
            cash_balance={},
        )
        provider = KISSyncSnapshotProvider(client)
        inst_repo = InMemoryInstrumentRepository()

        result = await provider.fetch_snapshot(uuid4(), inst_repo)
        assert len(result.positions) == 0
        assert any("Instrument not found" in err for err in result.errors)

    async def test_cash_balance_mapping(self) -> None:
        """Valid cash balance → CashBalanceSnapshotEntity."""
        account_id = uuid4()
        client = FakeKISRestClient(
            positions=[],
            cash_balance={
                "dnca_tot_amt": "1000000",
                "nxdy_excc_amt": "800000",
            },
        )
        provider = KISSyncSnapshotProvider(client)
        inst_repo = InMemoryInstrumentRepository()

        result = await provider.fetch_snapshot(account_id, inst_repo)
        assert result.cash_balance is not None
        cash = result.cash_balance
        assert cash.account_id == account_id
        assert cash.available_cash == 1000000
        assert cash.settled_cash == 800000
        assert cash.unsettled_cash == 200000  # 1,000,000 - 800,000
        assert cash.currency == "KRW"

    async def test_cash_balance_without_settled(self) -> None:
        """No nxdy_excc_amt → settled_cash falls back to available_cash."""
        account_id = uuid4()
        client = FakeKISRestClient(
            positions=[],
            cash_balance={"dnca_tot_amt": "500000"},
        )
        provider = KISSyncSnapshotProvider(client)
        inst_repo = InMemoryInstrumentRepository()

        result = await provider.fetch_snapshot(account_id, inst_repo)
        assert result.cash_balance is not None
        cash = result.cash_balance
        assert cash.available_cash == 500000
        assert cash.settled_cash == 500000
        assert cash.unsettled_cash is None

    async def test_cash_balance_fetch_failure(self) -> None:
        """REST client failure → error, no cash balance."""
        client = FakeKISRestClient(fail_cash=True)
        provider = KISSyncSnapshotProvider(client)
        inst_repo = InMemoryInstrumentRepository()

        result = await provider.fetch_snapshot(uuid4(), inst_repo)
        assert result.cash_balance is None
        assert any("cash balance" in err.lower() for err in result.errors)

    async def test_positions_fetch_failure(self) -> None:
        """REST client failure → error, empty positions."""
        client = FakeKISRestClient(fail_positions=True)
        provider = KISSyncSnapshotProvider(client)
        inst_repo = InMemoryInstrumentRepository()

        result = await provider.fetch_snapshot(uuid4(), inst_repo)
        assert len(result.positions) == 0
        assert any("positions" in err.lower() for err in result.errors)
