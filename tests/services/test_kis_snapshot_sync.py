"""Unit tests for ``kis_snapshot_sync`` service.

Tests use in-memory repositories and a mock KIS REST client to verify:
- Position mapping (pdno → instrument_id, field mapping)
- Cash balance mapping (dnca_tot_amt → available_cash, etc.)
- Instrument lookup failure → skip + warning (not hard fail)
- Partial success when some positions fail
- Empty responses
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import (
    CashBalanceSnapshotEntity,
    InstrumentEntity,
    PositionSnapshotEntity,
)
from agent_trading.repositories.memory import (
    InMemoryCashBalanceSnapshotRepository,
    InMemoryInstrumentRepository,
    InMemoryPositionSnapshotRepository,
)
from agent_trading.services.kis_snapshot_sync import (
    SyncResult,
    sync_kis_account_snapshots,
)


# ── Helpers ─────────────────────────────────────────────────────────────


class FakeKISRestClient:
    """Simulates ``KISRestClient.get_positions()`` and ``get_cash_balance()``."""

    def __init__(
        self,
        positions: list[dict[str, Any]] | None = None,
        cash_balance: dict[str, Any] | None = None,
    ) -> None:
        self._positions = positions or []
        self._cash_balance = cash_balance or {}
        self.get_positions_called = False
        self.get_cash_balance_called = False

    async def get_positions(self) -> list[dict[str, Any]]:
        self.get_positions_called = True
        return self._positions

    async def get_cash_balance(self) -> dict[str, Any]:
        self.get_cash_balance_called = True
        return self._cash_balance

    async def close(self) -> None:
        pass


def _make_instrument(symbol: str, market_code: str = "KRX") -> InstrumentEntity:
    return InstrumentEntity(
        instrument_id=uuid4(),
        symbol=symbol,
        market_code=market_code,
        asset_class="stock",
        currency="KRW",
        name=symbol,
        is_active=True,
    )


def _make_position(
    pdno: str = "005930",
    hldg_qty: str = "10",
    pchs_avg_pric: str = "70000",
    prpr: str = "72000",
    evlu_pfls_amt: str = "20000",
) -> dict[str, Any]:
    return {
        "pdno": pdno,
        "hldg_qty": hldg_qty,
        "pchs_avg_pric": pchs_avg_pric,
        "prpr": prpr,
        "evlu_pfls_amt": evlu_pfls_amt,
    }


def _make_cash_balance(
    dnca_tot_amt: str = "5000000",
    nxdy_excc_amt: str = "3000000",
    ord_psbl_amt: str = "2000000",
) -> dict[str, Any]:
    return {
        "dnca_tot_amt": dnca_tot_amt,
        "nxdy_excc_amt": nxdy_excc_amt,
        "ord_psbl_amt": ord_psbl_amt,
    }


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def account_id() -> UUID:
    return uuid4()


@pytest.fixture
async def instrument_repo() -> InMemoryInstrumentRepository:
    repo = InMemoryInstrumentRepository()
    # Pre-seed some instruments
    samsung = _make_instrument("005930", "KRX")
    kakao = _make_instrument("035720", "KRX")
    await repo.add(samsung)
    await repo.add(kakao)
    return repo


@pytest.fixture
def position_repo() -> InMemoryPositionSnapshotRepository:
    return InMemoryPositionSnapshotRepository()


@pytest.fixture
def cash_repo() -> InMemoryCashBalanceSnapshotRepository:
    return InMemoryCashBalanceSnapshotRepository()


# ── Tests ───────────────────────────────────────────────────────────────


class TestSyncPositions:
    """Position snapshot mapping tests."""

    async def test_sync_single_position(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """A single known position is mapped and persisted."""
        client = FakeKISRestClient(
            positions=[_make_position(pdno="005930")],
            cash_balance={},
        )
        result = await sync_kis_account_snapshots(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_id=account_id,
        )

        assert result.positions_synced == 1
        assert result.positions_skipped == 0
        assert result.cash_balance_synced is False

        snapshots = position_repo._items
        assert len(snapshots) == 1
        snap = list(snapshots.values())[0]
        assert snap.account_id == account_id
        assert snap.quantity == Decimal("10")
        assert snap.average_price == Decimal("70000")
        assert snap.market_price == Decimal("72000")
        assert snap.unrealized_pnl == Decimal("20000")
        assert snap.source_of_truth == "broker"

    async def test_sync_multiple_positions(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """Multiple known positions are all mapped and persisted."""
        client = FakeKISRestClient(
            positions=[
                _make_position(pdno="005930", hldg_qty="10"),
                _make_position(pdno="035720", hldg_qty="5"),
            ],
            cash_balance={},
        )
        result = await sync_kis_account_snapshots(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_id=account_id,
        )

        assert result.positions_synced == 2
        assert result.positions_skipped == 0
        assert len(position_repo._items) == 2

    async def test_skip_unknown_instrument(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """Position with unknown pdno is skipped, not hard-failed."""
        client = FakeKISRestClient(
            positions=[
                _make_position(pdno="005930"),  # known
                _make_position(pdno="UNKNOWN"),  # unknown
            ],
            cash_balance={},
        )
        result = await sync_kis_account_snapshots(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_id=account_id,
        )

        assert result.positions_synced == 1
        assert result.positions_skipped == 1
        assert len(position_repo._items) == 1
        assert any("UNKNOWN" in err for err in result.errors)

    async def test_skip_missing_pdno(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """Position row without pdno is skipped."""
        client = FakeKISRestClient(
            positions=[{"hldg_qty": "10"}],  # no pdno key
            cash_balance={},
        )
        result = await sync_kis_account_snapshots(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_id=account_id,
        )

        assert result.positions_synced == 0
        assert result.positions_skipped == 1

    async def test_empty_positions(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """Empty position list is handled gracefully."""
        client = FakeKISRestClient(positions=[], cash_balance={})
        result = await sync_kis_account_snapshots(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_id=account_id,
        )

        assert result.positions_synced == 0
        assert result.positions_skipped == 0
        assert len(position_repo._items) == 0

    async def test_kis_fetch_error(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """KIS fetch failure is captured as error, not crash."""

        class FailingClient(FakeKISRestClient):
            async def get_positions(self) -> list[dict[str, Any]]:
                raise RuntimeError("KIS timeout")

        client = FailingClient()
        result = await sync_kis_account_snapshots(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_id=account_id,
        )

        assert result.positions_synced == 0
        assert len(result.errors) >= 1
        assert "KIS timeout" in result.errors[0]


class TestSyncCashBalance:
    """Cash balance snapshot mapping tests."""

    async def test_sync_cash_balance(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """Cash balance with all fields is mapped correctly."""
        client = FakeKISRestClient(
            positions=[],
            cash_balance=_make_cash_balance(
                dnca_tot_amt="5000000",
                nxdy_excc_amt="3000000",
            ),
        )
        result = await sync_kis_account_snapshots(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_id=account_id,
        )

        assert result.cash_balance_synced is True
        assert len(cash_repo._items) == 1
        snap = list(cash_repo._items.values())[0]
        assert snap.account_id == account_id
        assert snap.currency == "KRW"
        assert snap.available_cash == Decimal("5000000")
        assert snap.settled_cash == Decimal("3000000")
        assert snap.unsettled_cash == Decimal("2000000")  # 5M - 3M
        assert snap.source_of_truth == "broker"

    async def test_cash_balance_no_settled_field(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """When nxdy_excc_amt is absent, settled_cash falls back to dnca_tot_amt."""
        client = FakeKISRestClient(
            positions=[],
            cash_balance={"dnca_tot_amt": "5000000"},  # no nxdy_excc_amt
        )
        result = await sync_kis_account_snapshots(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_id=account_id,
        )

        assert result.cash_balance_synced is True
        snap = list(cash_repo._items.values())[0]
        assert snap.available_cash == Decimal("5000000")
        assert snap.settled_cash == Decimal("5000000")  # fallback
        assert snap.unsettled_cash is None  # no difference

    async def test_cash_balance_empty(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """Empty cash balance dict is handled gracefully."""
        client = FakeKISRestClient(positions=[], cash_balance={})
        result = await sync_kis_account_snapshots(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_id=account_id,
        )

        assert result.cash_balance_synced is False
        assert len(cash_repo._items) == 0

    async def test_kis_cash_fetch_error(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """KIS cash fetch failure is captured as error."""

        class FailingClient(FakeKISRestClient):
            async def get_cash_balance(self) -> dict[str, Any]:
                raise RuntimeError("KIS cash timeout")

        client = FailingClient()
        result = await sync_kis_account_snapshots(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_id=account_id,
        )

        assert result.cash_balance_synced is False
        assert any("KIS cash timeout" in err for err in result.errors)


class TestSyncCombined:
    """Combined position + cash balance sync tests."""

    async def test_full_sync(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """Both positions and cash balance are synced in one call."""
        client = FakeKISRestClient(
            positions=[
                _make_position(pdno="005930", hldg_qty="10"),
                _make_position(pdno="035720", hldg_qty="5"),
            ],
            cash_balance=_make_cash_balance(),
        )
        result = await sync_kis_account_snapshots(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_id=account_id,
        )

        assert result.positions_synced == 2
        assert result.cash_balance_synced is True
        assert len(position_repo._items) == 2
        assert len(cash_repo._items) == 1

    async def test_sync_is_append_only(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """Calling sync twice appends new snapshots (does not overwrite)."""
        client = FakeKISRestClient(
            positions=[_make_position(pdno="005930")],
            cash_balance=_make_cash_balance(),
        )

        result1 = await sync_kis_account_snapshots(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_id=account_id,
        )
        result2 = await sync_kis_account_snapshots(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_id=account_id,
        )

        assert result1.positions_synced == 1
        assert result2.positions_synced == 1
        # Append-only: 2 snapshots after 2 calls
        assert len(position_repo._items) == 2
        assert len(cash_repo._items) == 2
