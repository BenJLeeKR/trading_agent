"""Tests for broker-agnostic snapshot sync runner (``snapshot_sync``).

Verifies:
- ``SnapshotFetchProvider`` protocol structural compatibility
- ``FetchedSnapshot`` dataclass
- ``sync_account_snapshots`` with a mock provider
- ``sync_accounts_by_ids`` batch sync
- ``sync_all_accounts`` auto-discover + broker parameter
- Re-exports from ``kis_snapshot_sync``
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import (
    AccountEntity,
    BrokerAccountEntity,
    CashBalanceSnapshotEntity,
    InstrumentEntity,
    PositionSnapshotEntity,
)
from agent_trading.domain.enums import Environment
from agent_trading.repositories.contracts import InstrumentRepository
from agent_trading.repositories.memory import (
    InMemoryAccountRepository,
    InMemoryBrokerAccountRepository,
    InMemoryCashBalanceSnapshotRepository,
    InMemoryInstrumentRepository,
    InMemoryPositionSnapshotRepository,
    InMemorySnapshotSyncRunRepository,
)
from agent_trading.services.snapshot_sync import (
    FetchedSnapshot,
    SnapshotFetchProvider,
    safe_decimal,
    safe_optional_decimal,
    sync_account_snapshots,
    sync_accounts_by_ids,
    sync_all_accounts,
)
from agent_trading.services.kis_snapshot_sync import (
    BatchSyncResult,
    SyncResult,
    build_sync_run_entity,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _d(val: str | int | float) -> Decimal:
    """Shortcut to create a Decimal for assertions."""
    from decimal import Decimal
    return Decimal(str(val))


# ── Test: re-exports ──────────────────────────────────────────────────────


class TestReExports:
    """Verify that broker-agnostic module re-exports KIS types."""

    def test_sync_result_imported(self) -> None:
        from agent_trading.services.snapshot_sync import SyncResult as SR
        assert SR is SyncResult

    def test_batch_sync_result_imported(self) -> None:
        from agent_trading.services.snapshot_sync import BatchSyncResult as BSR
        assert BSR is BatchSyncResult

    def test_build_sync_run_entity_imported(self) -> None:
        from agent_trading.services.snapshot_sync import build_sync_run_entity as bse
        assert bse is build_sync_run_entity


# ── Test: safe_decimal / safe_optional_decimal ────────────────────────────


class TestSafeDecimal:
    def test_safe_decimal_valid(self) -> None:
        assert safe_decimal("123.45") == _d("123.45")

    def test_safe_decimal_zero_on_invalid(self) -> None:
        assert safe_decimal("not-a-number") == _d("0")

    def test_safe_decimal_none(self) -> None:
        assert safe_decimal(None) == _d("0")  # type: ignore[arg-type]

    def test_safe_optional_decimal_valid(self) -> None:
        assert safe_optional_decimal("123.45") == _d("123.45")

    def test_safe_optional_decimal_none(self) -> None:
        assert safe_optional_decimal(None) is None

    def test_safe_optional_decimal_empty(self) -> None:
        assert safe_optional_decimal("") is None

    def test_safe_optional_decimal_invalid(self) -> None:
        assert safe_optional_decimal("abc") is None


# ── Test: FetchedSnapshot dataclass ──────────────────────────────────────


class TestFetchedSnapshot:
    def test_fetched_snapshot_defaults(self) -> None:
        snap = FetchedSnapshot(positions=[], cash_balance=None, errors=[])
        assert snap.positions == []
        assert snap.cash_balance is None
        assert snap.errors == []

    def test_fetched_snapshot_with_data(self) -> None:
        pos = PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=uuid4(),
            instrument_id=uuid4(),
            quantity=_d("10"),
            average_price=_d("5000"),
            market_price=None,
            unrealized_pnl=None,
            source_of_truth="broker",
            snapshot_at=None,
        )
        cash = CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=uuid4(),
            currency="KRW",
            available_cash=_d("10000"),
            settled_cash=None,
            unsettled_cash=None,
            source_of_truth="broker",
            snapshot_at=None,
        )
        snap = FetchedSnapshot(positions=[pos], cash_balance=cash, errors=["warn"])
        assert len(snap.positions) == 1
        assert snap.cash_balance is not None
        assert snap.errors == ["warn"]


# ── Mock provider ────────────────────────────────────────────────────────


class MockSnapshotProvider:
    """Mock implementation of ``SnapshotFetchProvider`` for testing."""

    def __init__(self, positions: list[PositionSnapshotEntity] | None = None,
                 cash: CashBalanceSnapshotEntity | None = None,
                 errors: list[str] | None = None,
                 fail: bool = False) -> None:
        self._positions = positions or []
        self._cash = cash
        self._errors = errors or []
        self._fail = fail

    async def fetch_snapshot(
        self,
        account_id: UUID,
        instrument_repo: InstrumentRepository,
        *,
        after_hours: bool = False,
    ) -> FetchedSnapshot:
        if self._fail:
            msg = f"Mock failure for account_id={account_id}"
            raise RuntimeError(msg)
        if after_hours:
            return FetchedSnapshot(
                positions=[],
                cash_balance=self._cash,
                errors=self._errors,
            )
        return FetchedSnapshot(
            positions=self._positions,
            cash_balance=self._cash,
            errors=self._errors,
        )


# ── Test: sync_account_snapshots ─────────────────────────────────────────


class TestSyncAccountSnapshots:
    """``sync_account_snapshots`` — broker-agnostic single-account runner."""

    async def test_sync_empty_positions(self) -> None:
        provider = MockSnapshotProvider()
        pos_repo = InMemoryPositionSnapshotRepository()
        cash_repo = InMemoryCashBalanceSnapshotRepository()
        inst_repo = InMemoryInstrumentRepository()

        result = await sync_account_snapshots(
            fetch_provider=provider,
            instrument_repo=inst_repo,
            position_snapshot_repo=pos_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_id=uuid4(),
        )
        assert result.positions_synced == 0
        assert result.cash_balance_synced is False
        assert result.errors == []

    async def test_sync_with_positions(self) -> None:
        account_id = uuid4()
        pos = PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=account_id,
            instrument_id=uuid4(),
            quantity=_d("10"),
            average_price=_d("5000"),
            market_price=None,
            unrealized_pnl=None,
            source_of_truth="broker",
            snapshot_at=None,
        )
        provider = MockSnapshotProvider(positions=[pos])
        pos_repo = InMemoryPositionSnapshotRepository()
        cash_repo = InMemoryCashBalanceSnapshotRepository()
        inst_repo = InMemoryInstrumentRepository()

        result = await sync_account_snapshots(
            fetch_provider=provider,
            instrument_repo=inst_repo,
            position_snapshot_repo=pos_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_id=account_id,
        )
        assert result.positions_synced == 1
        assert result.cash_balance_synced is False

    async def test_sync_with_cash(self) -> None:
        account_id = uuid4()
        cash = CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=account_id,
            currency="KRW",
            available_cash=_d("50000"),
            settled_cash=None,
            unsettled_cash=None,
            source_of_truth="broker",
            snapshot_at=None,
        )
        provider = MockSnapshotProvider(cash=cash)
        pos_repo = InMemoryPositionSnapshotRepository()
        cash_repo = InMemoryCashBalanceSnapshotRepository()
        inst_repo = InMemoryInstrumentRepository()

        result = await sync_account_snapshots(
            fetch_provider=provider,
            instrument_repo=inst_repo,
            position_snapshot_repo=pos_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_id=account_id,
        )
        assert result.cash_balance_synced is True

    async def test_sync_provider_failure(self) -> None:
        provider = MockSnapshotProvider(fail=True)
        pos_repo = InMemoryPositionSnapshotRepository()
        cash_repo = InMemoryCashBalanceSnapshotRepository()
        inst_repo = InMemoryInstrumentRepository()

        result = await sync_account_snapshots(
            fetch_provider=provider,
            instrument_repo=inst_repo,
            position_snapshot_repo=pos_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_id=uuid4(),
        )
        assert result.positions_synced == 0
        assert len(result.errors) == 1
        assert "Mock failure" in result.errors[0]

    async def test_sync_provider_errors(self) -> None:
        provider = MockSnapshotProvider(errors=["Instrument lookup failed"])
        pos_repo = InMemoryPositionSnapshotRepository()
        cash_repo = InMemoryCashBalanceSnapshotRepository()
        inst_repo = InMemoryInstrumentRepository()

        result = await sync_account_snapshots(
            fetch_provider=provider,
            instrument_repo=inst_repo,
            position_snapshot_repo=pos_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_id=uuid4(),
        )
        assert result.errors == ["Instrument lookup failed"]


# ── Test: sync_accounts_by_ids ───────────────────────────────────────────


class TestSyncAccountsByIds:
    """``sync_accounts_by_ids`` — broker-agnostic batch sync."""

    async def test_batch_empty(self) -> None:
        provider = MockSnapshotProvider()
        pos_repo = InMemoryPositionSnapshotRepository()
        cash_repo = InMemoryCashBalanceSnapshotRepository()
        inst_repo = InMemoryInstrumentRepository()

        batch = await sync_accounts_by_ids(
            fetch_provider=provider,
            instrument_repo=inst_repo,
            position_snapshot_repo=pos_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_ids=[],
        )
        assert batch.total_accounts == 0
        assert batch.succeeded == 0

    async def test_batch_two_accounts(self) -> None:
        account_a = uuid4()
        account_b = uuid4()
        pos_a = PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=account_a,
            instrument_id=uuid4(),
            quantity=_d("5"),
            average_price=_d("1000"),
            market_price=None,
            unrealized_pnl=None,
            source_of_truth="broker",
            snapshot_at=None,
        )
        pos_b = PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=account_b,
            instrument_id=uuid4(),
            quantity=_d("10"),
            average_price=_d("2000"),
            market_price=None,
            unrealized_pnl=None,
            source_of_truth="broker",
            snapshot_at=None,
        )

        provider_a = MockSnapshotProvider(positions=[pos_a])
        provider_b = MockSnapshotProvider(positions=[pos_b])
        # Use a provider factory pattern via different instances won't work
        # since sync_accounts_by_ids uses one provider for all accounts.
        # Instead, test with a single provider that handles both.
        provider = MockSnapshotProvider(positions=[pos_a, pos_b])
        pos_repo = InMemoryPositionSnapshotRepository()
        cash_repo = InMemoryCashBalanceSnapshotRepository()
        inst_repo = InMemoryInstrumentRepository()

        batch = await sync_accounts_by_ids(
            fetch_provider=provider,
            instrument_repo=inst_repo,
            position_snapshot_repo=pos_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_ids=[account_a, account_b],
        )
        assert batch.total_accounts == 2
        assert batch.succeeded == 2
        assert batch.total_positions_synced == 4  # both positions per account call


# ── Test: sync_all_accounts ──────────────────────────────────────────────


class TestSyncAllAccounts:
    """``sync_all_accounts`` — broker-agnostic auto-discover + batch sync."""

    async def test_discover_empty(self) -> None:
        """No broker accounts → empty result."""
        provider = MockSnapshotProvider()
        ba_repo = InMemoryBrokerAccountRepository()
        acc_repo = InMemoryAccountRepository()
        pos_repo = InMemoryPositionSnapshotRepository()
        cash_repo = InMemoryCashBalanceSnapshotRepository()
        inst_repo = InMemoryInstrumentRepository()

        batch = await sync_all_accounts(
            fetch_provider=provider,
            instrument_repo=inst_repo,
            position_snapshot_repo=pos_repo,
            cash_balance_snapshot_repo=cash_repo,
            broker_account_repo=ba_repo,
            account_repo=acc_repo,
            broker_name="koreainvestment",
        )
        assert batch.total_accounts == 0
        assert batch.succeeded == 0

    async def test_discover_with_accounts(self) -> None:
        """One broker account + one account entity → synced."""
        broker_account_id = uuid4()
        account_id = uuid4()
        ba = BrokerAccountEntity(
            broker_account_id=broker_account_id,
            broker_name="koreainvestment",
            account_ref="1234",
            environment=Environment.PAPER,
            credential_ref="default",
        )
        acc = AccountEntity(
            account_id=account_id,
            client_id=uuid4(),
            broker_account_id=broker_account_id,
            environment=Environment.PAPER,
            account_alias="Test Account",
            account_masked="1234****",
            status="active",
        )

        ba_repo = InMemoryBrokerAccountRepository()
        await ba_repo.add(ba)
        acc_repo = InMemoryAccountRepository()
        await acc_repo.add(acc)

        pos = PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=account_id,
            instrument_id=uuid4(),
            quantity=_d("10"),
            average_price=_d("5000"),
            market_price=None,
            unrealized_pnl=None,
            source_of_truth="broker",
            snapshot_at=None,
        )
        provider = MockSnapshotProvider(positions=[pos])
        pos_repo = InMemoryPositionSnapshotRepository()
        cash_repo = InMemoryCashBalanceSnapshotRepository()
        inst_repo = InMemoryInstrumentRepository()

        batch = await sync_all_accounts(
            fetch_provider=provider,
            instrument_repo=inst_repo,
            position_snapshot_repo=pos_repo,
            cash_balance_snapshot_repo=cash_repo,
            broker_account_repo=ba_repo,
            account_repo=acc_repo,
            broker_name="koreainvestment",
        )
        assert batch.total_accounts == 1
        assert batch.succeeded == 1
        assert batch.total_positions_synced == 1

    async def test_broker_name_param(self) -> None:
        """``broker_name`` is passed to ``BrokerAccountRepository``."""
        ba_repo = InMemoryBrokerAccountRepository()
        acc_repo = InMemoryAccountRepository()
        provider = MockSnapshotProvider()
        pos_repo = InMemoryPositionSnapshotRepository()
        cash_repo = InMemoryCashBalanceSnapshotRepository()
        inst_repo = InMemoryInstrumentRepository()

        # Register a broker account for "test_broker"
        ba = BrokerAccountEntity(
            broker_account_id=uuid4(),
            broker_name="test_broker",
            account_ref="9999",
            environment=Environment.PAPER,
            credential_ref="default",
        )
        await ba_repo.add(ba)

        # Sync with broker_name="test_broker" — should discover the account
        # but skip it since no AccountEntity exists.
        batch = await sync_all_accounts(
            fetch_provider=provider,
            instrument_repo=inst_repo,
            position_snapshot_repo=pos_repo,
            cash_balance_snapshot_repo=cash_repo,
            broker_account_repo=ba_repo,
            account_repo=acc_repo,
            broker_name="test_broker",
        )
        # Account was discovered but has no AccountEntity → skipped
        assert batch.total_accounts == 1
        assert batch.skipped == 1


# ── Test: SnapshotFetchProvider protocol ─────────────────────────────────


class TestSnapshotFetchProviderProtocol:
    """Structural subtyping test for ``SnapshotFetchProvider``."""

    async def test_mock_implements_protocol(self) -> None:
        """Verify our mock conforms to the protocol."""
        provider: SnapshotFetchProvider = MockSnapshotProvider()  # type: ignore[assignment]
        result = await provider.fetch_snapshot(uuid4(), InMemoryInstrumentRepository())
        assert isinstance(result, FetchedSnapshot)

    async def test_protocol_accepts_concrete_types(self) -> None:
        """Protocol accepts properly typed implementations."""
        class CustomProvider:
            async def fetch_snapshot(
                self,
                account_id: UUID,
                instrument_repo: InstrumentRepository,
            ) -> FetchedSnapshot:
                return FetchedSnapshot(positions=[], cash_balance=None, errors=[])

        provider: SnapshotFetchProvider = CustomProvider()  # type: ignore[assignment]
        result = await provider.fetch_snapshot(uuid4(), InMemoryInstrumentRepository())
        assert isinstance(result, FetchedSnapshot)
