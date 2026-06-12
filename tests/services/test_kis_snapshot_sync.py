"""Unit tests for ``kis_snapshot_sync`` service.

Tests use in-memory repositories and a mock KIS REST client to verify:
- Position mapping (pdno → instrument_id, field mapping)
- Cash balance mapping (dnca_tot_amt → available_cash, etc.)
- Instrument lookup failure → skip + warning (not hard fail)
- Partial success when some positions fail
- Empty responses
- Batch sync (multiple account IDs, auto-discovery, filtering)
- Budget exhaustion recovery (cash snapshot 우선 저장, orderable_cash fallback)
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from agent_trading.brokers.rate_limit import BudgetExhaustedError
from agent_trading.domain.entities import (
    AccountEntity,
    BrokerAccountEntity,
    CashBalanceSnapshotEntity,
    InstrumentEntity,
    PositionSnapshotEntity,
    SnapshotSyncRunEntity,
)
from agent_trading.domain.enums import Environment
from agent_trading.repositories.memory import (
    InMemoryAccountRepository,
    InMemoryBrokerAccountRepository,
    InMemoryCashBalanceSnapshotRepository,
    InMemoryInstrumentRepository,
    InMemoryPositionSnapshotRepository,
    InMemorySnapshotSyncRunRepository,
)
from agent_trading.brokers.koreainvestment.rest_client import CashAndPositionsResult
from agent_trading.brokers.koreainvestment.rest_client import OrderableCashResult
from agent_trading.services.kis_snapshot_sync import (
    BatchSyncResult,
    SyncResult,
    build_sync_run_entity,
    sync_all_kis_accounts,
    sync_kis_account_snapshots,
    sync_kis_accounts_by_ids,
)


# ── Helpers ─────────────────────────────────────────────────────────────


class FakeKISRestClient:
    """Simulates ``KISRestClient.get_positions()``, ``get_cash_balance()``,
    and ``get_orderable_cash()``."""

    def __init__(
        self,
        positions: list[dict[str, Any]] | None = None,
        cash_balance: dict[str, Any] | None = None,
        orderable_cash: Decimal | None = None,
    ) -> None:
        self._positions = positions or []
        self._cash_balance = cash_balance or {}
        self._orderable_cash = orderable_cash
        self.get_positions_called = False
        self.get_cash_balance_called = False
        self.get_orderable_cash_called = False

    async def get_positions(self) -> list[dict[str, Any]]:
        self.get_positions_called = True
        return self._positions

    async def get_cash_balance(self, after_hours: bool = False) -> dict[str, Any]:
        self.get_cash_balance_called = True
        return self._cash_balance

    async def get_orderable_cash(
        self,
        account_ref: str = "",
        symbol: str = "",
        price: str = "",
        order_type: str = "00",
        fallback_cash: Decimal | None = None,
    ) -> Decimal | None:
        self.get_orderable_cash_called = True
        return self._orderable_cash

    async def get_orderable_cash_result(
        self,
        account_ref: str = "",
        symbol: str = "",
        price: str = "",
        order_type: str = "00",
        fallback_cash: Decimal | None = None,
    ) -> OrderableCashResult:
        amount = await self.get_orderable_cash(
            account_ref=account_ref,
            symbol=symbol,
            price=price,
            order_type=order_type,
            fallback_cash=fallback_cash,
        )
        if amount is None:
            return OrderableCashResult(amount=None, source="missing_field")
        if amount is not None and amount != fallback_cash:
            return OrderableCashResult(
                amount=amount,
                source="vttc8908r",
            )
        if fallback_cash is not None:
            return OrderableCashResult(
                amount=amount,
                source="budget_precheck_fallback",
            )
        return OrderableCashResult(amount=amount, source="missing_field")

    async def get_cash_and_positions(
        self,
        *,
        after_hours: bool = False,
    ) -> CashAndPositionsResult:
        """Fake implementation: delegates to get_positions() and get_cash_balance().

        Delegating to the individual methods allows subclasses (e.g. FailingClient)
        to override ``get_positions()`` or ``get_cash_balance()`` and still have
        those overrides exercised through ``get_cash_and_positions()``.
        """
        positions = await self.get_positions()
        cash_balance = await self.get_cash_balance(after_hours=after_hours)
        return CashAndPositionsResult(
            positions=positions,
            cash_balance=cash_balance,
            raw_response={
                "output1": positions,
                "output2": cash_balance,
            },
        )

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
    tot_evlu_amt: str = "15000000",
    prvs_rcdl_excc_amt: str = "3500000",
    evlu_pfls_smtl_amt: str = "500000",
) -> dict[str, Any]:
    return {
        "dnca_tot_amt": dnca_tot_amt,
        "nxdy_excc_amt": nxdy_excc_amt,
        "ord_psbl_amt": ord_psbl_amt,
        "tot_evlu_amt": tot_evlu_amt,
        "prvs_rcdl_excc_amt": prvs_rcdl_excc_amt,
        "evlu_pfls_smtl_amt": evlu_pfls_smtl_amt,
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

    # ── 정상 케이스 ────────────────────────────────────────────────────

    async def test_sync_cash_balance(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """Cash balance with all fields (including KIS output2) is mapped correctly."""
        client = FakeKISRestClient(
            positions=[],
            cash_balance=_make_cash_balance(
                dnca_tot_amt="5000000",
                nxdy_excc_amt="3000000",
                tot_evlu_amt="15000000",
                prvs_rcdl_excc_amt="3500000",
                evlu_pfls_smtl_amt="500000",
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
        # KIS output2 account-level summary fields
        assert snap.total_asset == Decimal("15000000")
        assert snap.settlement_amount == Decimal("3500000")
        assert snap.total_unrealized_pnl == Decimal("500000")

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
            async def get_cash_balance(self, after_hours: bool = False) -> dict[str, Any]:
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

    # ── Budget exhaustion 복구 테스트 ──────────────────────────────────

    async def test_cash_balance_budget_exhausted_cash_not_saved(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """``get_cash_and_positions()``가 BudgetExhaustedError로 실패하면
        cash snapshot은 저장되지 않고 positions도 함께 실패한다.
        리팩토링 후 ``get_cash_and_positions()`` 1회 호출이므로
        cash/positions가 함께 실패하는 것이 production contract와 일치한다."""

        class BudgetExhaustedCashClient(FakeKISRestClient):
            async def get_cash_and_positions(
                self,
                *,
                after_hours: bool = False,
            ) -> CashAndPositionsResult:
                raise BudgetExhaustedError(
                    bucket="inquiry",
                    message="Bucket 'inquiry' exhausted (remaining=0/1)",
                )

        client = BudgetExhaustedCashClient(
            positions=[_make_position(pdno="005930")],
        )
        result = await sync_kis_account_snapshots(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_id=account_id,
        )

        # cash 조회 실패 → cash_balance_synced=False
        assert result.cash_balance_synced is False
        assert len(cash_repo._items) == 0
        # budget exhaustion 에러 메시지 확인 (BudgetExhaustedError → "exhausted" 포함)
        assert any("exhausted" in err.lower() for err in result.errors)
        # get_cash_and_positions() 1회 호출 실패 → positions도 함께 실패
        assert result.positions_synced == 0

    async def test_orderable_cash_budget_exhausted_fallback_to_raw_cash(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """orderable_cash 조회가 BudgetExhaustedError로 실패해도
        raw_cash(available_cash)로 fallback하여 cash snapshot 저장."""

        class BudgetExhaustedOrderableClient(FakeKISRestClient):
            async def get_orderable_cash(
                self,
                account_ref: str = "",
                symbol: str = "",
                price: str = "",
                order_type: str = "00",
                fallback_cash: Decimal | None = None,
            ) -> Decimal | None:
                raise BudgetExhaustedError(
                    bucket="inquiry",
                    message="Bucket 'inquiry' exhausted (remaining=0/1)",
                )

        client = BudgetExhaustedOrderableClient(
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

        # cash snapshot은 저장되어야 함 (orderable_cash 실패에도 불구하고)
        assert result.cash_balance_synced is True
        assert len(cash_repo._items) == 1
        snap = list(cash_repo._items.values())[0]
        # available_cash는 정상 조회됨
        assert snap.available_cash == Decimal("5000000")
        # orderable_amount는 unsafe available_cash 승격 대신 0으로 고정
        assert snap.orderable_amount == Decimal("0")
        assert snap.fetch_status == "stale"
        # CASH_SYNC_ZERO가 아닌 값으로 저장됨
        assert snap.available_cash > 0

    async def test_positions_budget_exhausted_cash_still_saved(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """``get_cash_and_positions()``가 BudgetExhaustedError로 실패하면
        cash도 positions도 모두 저장되지 않는다.
        리팩토링 후 ``get_cash_and_positions()`` 1회 호출이므로
        cash/positions가 함께 실패하는 것이 production contract와 일치한다."""

        class BudgetExhaustedPositionsClient(FakeKISRestClient):
            async def get_cash_and_positions(
                self,
                *,
                after_hours: bool = False,
            ) -> CashAndPositionsResult:
                raise BudgetExhaustedError(
                    bucket="inquiry",
                    message="Bucket 'inquiry' exhausted (remaining=0/1)",
                )

        client = BudgetExhaustedPositionsClient(
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

        # cash도 함께 실패 (get_cash_and_positions() 1회 호출이므로)
        assert result.cash_balance_synced is False
        assert len(cash_repo._items) == 0
        # positions도 budget 부족으로 실패
        assert result.positions_synced == 0
        # budget exhaustion 에러 메시지 확인 (BudgetExhaustedError → "exhausted" 포함)
        assert any("exhausted" in err.lower() for err in result.errors)

    async def test_orderable_cash_general_exception_fallback_to_available_cash(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """orderable_cash가 BudgetExhaustedError가 아닌 일반 예외로 실패하면
        BUY-safe zero로 fallback."""

        class FailingOrderableClient(FakeKISRestClient):
            async def get_orderable_cash(
                self,
                account_ref: str = "",
                symbol: str = "",
                price: str = "",
                order_type: str = "00",
                fallback_cash: Decimal | None = None,
            ) -> Decimal | None:
                raise RuntimeError("VTTC8908R network error")

        client = FailingOrderableClient(
            positions=[],
            cash_balance=_make_cash_balance(
                dnca_tot_amt="5000000",
                nxdy_excc_amt="3000000",
                ord_psbl_amt="2000000",
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
        snap = list(cash_repo._items.values())[0]
        # 일반 Exception → available_cash 승격 금지
        assert snap.orderable_amount == Decimal("0"), (
            f"Expected 0 from Exception fallback, "
            f"got {snap.orderable_amount}"
        )
        assert snap.available_cash == Decimal("5000000")
        assert snap.fetch_status == "stale"

    async def test_orderable_cash_logs_budget_precheck_fallback_source(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level("INFO")
        class BudgetPrecheckFallbackClient(FakeKISRestClient):
            async def get_orderable_cash_result(
                self,
                account_ref: str = "",
                symbol: str = "",
                price: str = "",
                order_type: str = "00",
                fallback_cash: Decimal | None = None,
            ) -> OrderableCashResult:
                return OrderableCashResult(
                    amount=fallback_cash,
                    source="budget_precheck_fallback",
                )

        client = BudgetPrecheckFallbackClient(
            positions=[],
            cash_balance=_make_cash_balance(
                dnca_tot_amt="5000000",
                nxdy_excc_amt="3000000",
            ),
            orderable_cash=None,
        )
        result = await sync_kis_account_snapshots(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_id=account_id,
        )

        assert result.cash_balance_synced is True
        assert "source: budget_precheck_fallback" in caplog.text

    async def test_fetch_positions_false_skips_positions(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """``fetch_positions=False`` → positions 조회를 건너뛰고 cash+orderable만 저장."""
        client = FakeKISRestClient(
            positions=[{"pdno": "005930", "hldg_qty": "10", "pchs_avg_pric": "70000"}],
            cash_balance=_make_cash_balance(
                dnca_tot_amt="5000000",
                nxdy_excc_amt="3000000",
            ),
            orderable_cash=Decimal("4500000"),
        )
        result = await sync_kis_account_snapshots(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_id=account_id,
            fetch_positions=False,
        )

        # cash는 저장됨
        assert result.cash_balance_synced is True
        snap = list(cash_repo._items.values())[0]
        assert snap.orderable_amount == Decimal("4500000")
        assert snap.available_cash == Decimal("5000000")

        # positions는 저장되지 않음
        assert result.positions_synced == 0
        assert len(position_repo._items) == 0

    # ── P1+P2 통합: 호출 순서 변경 + Budget fallback ──────────────────────

    async def test_positions_before_orderable_cash_when_budget_limited(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """P1+P2: budget 2회 제한 시나리오에서 positions이 orderable_cash보다
        먼저 확보되는지 검증.

        cash=1회 + positions=1회로 budget 소진 후,
        orderable_cash는 BudgetExhaustedError 발생 없이 available_cash로 fallback."""
        class BudgetLimitedClient(FakeKISRestClient):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self._call_count = 0

            async def get_cash_balance(self, after_hours: bool = False) -> dict[str, Any]:
                self._call_count += 1
                self.get_cash_balance_called = True
                if self._call_count > 2:
                    raise BudgetExhaustedError(
                        bucket="inquiry",
                        message="Budget exhausted after 2 calls",
                    )
                return self._cash_balance

            async def get_positions(self) -> list[dict[str, Any]]:
                self._call_count += 1
                self.get_positions_called = True
                if self._call_count > 2:
                    raise BudgetExhaustedError(
                        bucket="inquiry",
                        message="Budget exhausted after 2 calls",
                    )
                return self._positions

            async def get_orderable_cash(
                self,
                account_ref: str = "",
                symbol: str = "",
                price: str = "",
                order_type: str = "00",
                fallback_cash: Decimal | None = None,
            ) -> Decimal | None:
                self._call_count += 1
                self.get_orderable_cash_called = True
                if self._call_count > 2:
                    raise BudgetExhaustedError(
                        bucket="inquiry",
                        message="Budget exhausted after 2 calls",
                    )
                return self._orderable_cash

        client = BudgetLimitedClient(
            positions=[_make_position(pdno="005930")],
            cash_balance=_make_cash_balance(
                dnca_tot_amt="5000000",
                nxdy_excc_amt="3000000",
            ),
            orderable_cash=Decimal("4500000"),
        )
        result = await sync_kis_account_snapshots(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_id=account_id,
        )

        # cash는 정상 조회
        assert result.cash_balance_synced is True
        assert len(cash_repo._items) == 1
        snap = list(cash_repo._items.values())[0]
        assert snap.available_cash == Decimal("5000000")

        # positions는 budget 2회 이내에 성공 (cash 1회 + positions 1회)
        assert result.positions_synced == 1
        pos_snaps = list(position_repo._items.values())
        assert len(pos_snaps) == 1
        assert pos_snaps[0].quantity == Decimal("10")  # _make_position 기본값

        # orderable_cash는 budget 부족으로 fallback → BUY-safe zero
        assert snap.orderable_amount == Decimal("0")
        assert snap.fetch_status == "stale"

    # ── P3: after-hours 모드 ─────────────────────────────────────────────

    async def test_orderable_cash_skipped_when_after_hours(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """P3: after-hours=True → VTTC8908R(orderable_cash) 완전 생략.
        장 마감 후(15:30 KST 이후) 매수 주문 불가 → orderable_amount 불필요.
        cash balance(dnca_tot_amt)만으로 충분."""
        client = FakeKISRestClient(
            positions=[_make_position(pdno="005930")],
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
            after_hours=True,
        )

        # cash는 정상 저장
        assert result.cash_balance_synced is True
        assert len(cash_repo._items) == 1
        snap = list(cash_repo._items.values())[0]
        assert snap.available_cash == Decimal("5000000")

        # after-hours → positions 미조회
        assert result.positions_synced == 0
        assert len(position_repo._items) == 0

        # after-hours → get_orderable_cash() 미호출
        assert client.get_orderable_cash_called is False
        # orderable_amount가 설정되지 않음 (None)
        assert snap.orderable_amount is None

    # ── P2: Budget pre-check fallback ─────────────────────────────────────

    async def test_orderable_cash_fallback_with_pre_check(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """P2: budget 사전 확인(_has_budget_for_inquiry)으로
        INQUIRY budget 부족 시 API 호출 없이 available_cash fallback.
        BudgetExhaustedError가 발생하지 않아야 함."""
        class BudgetPreCheckClient(FakeKISRestClient):
            """budget_manager를 흉내내어 budget 부족 시 fallback_cash 반환."""

            def __init__(self, budget_available: bool, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self._budget_available = budget_available

            async def get_orderable_cash(
                self,
                account_ref: str = "",
                symbol: str = "",
                price: str = "",
                order_type: str = "00",
                fallback_cash: Decimal | None = None,
            ) -> Decimal | None:
                self.get_orderable_cash_called = True
                # budget pre-check 시뮬레이션
                if fallback_cash is not None and not self._budget_available:
                    return fallback_cash
                return self._orderable_cash

        # budget 부족 상태 → fallback_cash가 반환되어야 함
        client = BudgetPreCheckClient(
            budget_available=False,
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
        # budget pre-check로 인해 available_cash 승격 금지 → 0
        assert snap.orderable_amount == Decimal("0")
        assert snap.available_cash == Decimal("5000000")
        assert snap.fetch_status == "stale"
        assert result.positions_synced == 0

    async def test_orderable_cash_none_and_ord_psbl_amt_missing_fallback_to_available_cash(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """VTTC8908R이 None 반환 + VTTC8434R ord_psbl_amt도 없을 때
        available_cash 승격 없이 0으로 저장한다."""
        # ord_psbl_amt 필드 자체를 제거한 cash_balance 생성
        cash_balance = _make_cash_balance(
            dnca_tot_amt="5000000",
            nxdy_excc_amt="3000000",
        )
        # ord_psbl_amt 키 제거 (필드 자체가 없는 상황 시뮬레이션)
        cash_balance.pop("ord_psbl_amt", None)

        client = FakeKISRestClient(
            positions=[],
            cash_balance=cash_balance,
            orderable_cash=None,  # VTTC8908R이 None 반환
        )
        with caplog.at_level("WARNING", logger="agent_trading.services.kis_snapshot_sync"):
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

        # available_cash 승격 없이 0으로 저장
        assert snap.orderable_amount == Decimal("0")
        assert snap.fetch_status == "stale"
        assert snap.available_cash == Decimal("5000000")

        # 경고 로그 출력 확인
        assert any(
            "orderable_amount not available from KIS" in record.message
            for record in caplog.records
        ), "fallback warning log should be emitted"


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


# ── Batch Sync Tests ─────────────────────────────────────────────────────


class TestBatchSyncByIds:
    """``sync_kis_accounts_by_ids()`` tests."""

    async def test_sync_multiple_ids(
        self,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """Multiple account IDs are synced and aggregated correctly."""
        account_id_1 = uuid4()
        account_id_2 = uuid4()
        client = FakeKISRestClient(
            positions=[_make_position(pdno="005930")],
            cash_balance=_make_cash_balance(),
        )

        batch = await sync_kis_accounts_by_ids(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_ids=[account_id_1, account_id_2],
        )

        assert batch.total_accounts == 2
        assert batch.succeeded == 2
        assert batch.partial == 0
        assert batch.failed == 0
        assert batch.skipped == 0
        assert batch.total_positions_synced == 2  # 1 per account
        assert batch.total_cash_synced == 2       # 1 per account
        assert len(batch.account_results) == 2
        assert len(position_repo._items) == 2
        assert len(cash_repo._items) == 2

    async def test_batch_partial_failure(
        self,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """When some accounts fail, partial/failed counters reflect correctly."""

        class FailingClient(FakeKISRestClient):
            def __init__(self) -> None:
                super().__init__(positions=[_make_position(pdno="005930")])
                self.call_count = 0

            async def get_positions(self) -> list[dict[str, Any]]:
                self.call_count += 1
                if self.call_count == 2:
                    raise RuntimeError("KIS timeout on second call")
                return self._positions

        account_id_1 = uuid4()
        account_id_2 = uuid4()
        client = FailingClient()

        batch = await sync_kis_accounts_by_ids(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_ids=[account_id_1, account_id_2],
        )

        assert batch.total_accounts == 2
        assert batch.succeeded == 1
        assert batch.partial == 0
        assert batch.failed == 1
        assert batch.total_positions_synced == 1
        assert len(batch.account_results) == 2  # both appended (one with errors)
        assert len(position_repo._items) == 1

    async def test_batch_empty_ids(
        self,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """Empty account_ids list produces empty BatchSyncResult."""
        client = FakeKISRestClient()
        batch = await sync_kis_accounts_by_ids(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_ids=[],
        )

        assert batch.total_accounts == 0
        assert batch.succeeded == 0
        assert batch.partial == 0
        assert batch.failed == 0
        assert batch.skipped == 0
        assert batch.total_positions_synced == 0
        assert len(batch.account_results) == 0


class TestSyncAllKisAccounts:
    """``sync_all_kis_accounts()`` tests."""

    async def test_sync_all_discovery(
        self,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """Discovered KIS broker accounts are resolved and synced."""
        broker_account_id_1 = uuid4()
        broker_account_id_2 = uuid4()
        account_id_1 = uuid4()
        account_id_2 = uuid4()

        broker_repo = InMemoryBrokerAccountRepository()
        await broker_repo.add(BrokerAccountEntity(
            broker_account_id=broker_account_id_1,
            broker_name="koreainvestment",
            account_ref="1234567890",
            environment=Environment.PAPER,
            credential_ref="default",
        ))
        await broker_repo.add(BrokerAccountEntity(
            broker_account_id=broker_account_id_2,
            broker_name="koreainvestment",
            account_ref="0987654321",
            environment=Environment.PAPER,
            credential_ref="default",
        ))

        account_repo = InMemoryAccountRepository()
        await account_repo.add(AccountEntity(
            account_id=account_id_1,
            client_id=uuid4(),
            broker_account_id=broker_account_id_1,
            account_alias="KIS-1",
            account_masked="1234-****",
            environment=Environment.PAPER,
            status="active",
        ))
        await account_repo.add(AccountEntity(
            account_id=account_id_2,
            client_id=uuid4(),
            broker_account_id=broker_account_id_2,
            account_alias="KIS-2",
            account_masked="0987-****",
            environment=Environment.PAPER,
            status="active",
        ))

        client = FakeKISRestClient(
            positions=[_make_position(pdno="005930")],
            cash_balance=_make_cash_balance(),
        )

        batch = await sync_all_kis_accounts(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            broker_account_repo=broker_repo,
            account_repo=account_repo,
        )

        assert batch.total_accounts == 2
        assert batch.succeeded == 2
        assert batch.partial == 0
        assert batch.failed == 0
        assert batch.skipped == 0
        assert batch.total_positions_synced == 2
        assert len(position_repo._items) == 2

    async def test_sync_all_with_account_number_filter(
        self,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """When kis_account_number is set, non-matching accounts are skipped."""
        broker_account_id_1 = uuid4()
        broker_account_id_2 = uuid4()
        account_id_1 = uuid4()

        broker_repo = InMemoryBrokerAccountRepository()
        await broker_repo.add(BrokerAccountEntity(
            broker_account_id=broker_account_id_1,
            broker_name="koreainvestment",
            account_ref="1234567890",
            environment=Environment.PAPER,
            credential_ref="default",
        ))
        await broker_repo.add(BrokerAccountEntity(
            broker_account_id=broker_account_id_2,
            broker_name="koreainvestment",
            account_ref="0987654321",
            environment=Environment.PAPER,
            credential_ref="default",
        ))

        account_repo = InMemoryAccountRepository()
        await account_repo.add(AccountEntity(
            account_id=account_id_1,
            client_id=uuid4(),
            broker_account_id=broker_account_id_1,
            account_alias="KIS-1",
            account_masked="1234-****",
            environment=Environment.PAPER,
            status="active",
        ))

        client = FakeKISRestClient(
            positions=[_make_position(pdno="005930")],
            cash_balance=_make_cash_balance(),
        )

        batch = await sync_all_kis_accounts(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            broker_account_repo=broker_repo,
            account_repo=account_repo,
            kis_account_number="1234567890",
        )

        assert batch.total_accounts == 2
        assert batch.succeeded == 1
        assert batch.skipped == 1  # 0987654321 skipped
        assert batch.failed == 0
        assert batch.total_positions_synced == 1
        assert len(position_repo._items) == 1

    async def test_batch_empty_discovery(
        self,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """No KIS broker accounts → empty BatchSyncResult."""
        broker_repo = InMemoryBrokerAccountRepository()
        account_repo = InMemoryAccountRepository()
        client = FakeKISRestClient()

        batch = await sync_all_kis_accounts(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            broker_account_repo=broker_repo,
            account_repo=account_repo,
        )

        assert batch.total_accounts == 0
        assert batch.succeeded == 0
        assert batch.partial == 0
        assert batch.failed == 0
        assert batch.skipped == 0
        assert batch.total_positions_synced == 0
        assert len(batch.account_results) == 0


class TestSyncAllWithEnvFilter:
    """``sync_all_kis_accounts()`` — environment (``env``) filter tests."""

    async def test_filter_env_paper_only(
        self,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """When ``env=Environment.PAPER``, only paper accounts are synced."""
        broker_account_id_paper = uuid4()
        broker_account_id_live = uuid4()
        account_id_paper = uuid4()

        broker_repo = InMemoryBrokerAccountRepository()
        await broker_repo.add(BrokerAccountEntity(
            broker_account_id=broker_account_id_paper,
            broker_name="koreainvestment",
            account_ref="1111111111",
            environment=Environment.PAPER,
            credential_ref="default",
        ))
        await broker_repo.add(BrokerAccountEntity(
            broker_account_id=broker_account_id_live,
            broker_name="koreainvestment",
            account_ref="2222222222",
            environment=Environment.LIVE,
            credential_ref="default",
        ))

        account_repo = InMemoryAccountRepository()
        await account_repo.add(AccountEntity(
            account_id=account_id_paper,
            client_id=uuid4(),
            broker_account_id=broker_account_id_paper,
            account_alias="KIS-PAPER",
            account_masked="****1111",
            environment=Environment.PAPER,
            status="active",
        ))

        client = FakeKISRestClient(
            positions=[_make_position(pdno="005930")],
            cash_balance=_make_cash_balance(),
        )

        batch = await sync_all_kis_accounts(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            broker_account_repo=broker_repo,
            account_repo=account_repo,
            env=Environment.PAPER,
        )

        # Only 1 broker account discovered (paper), 1 synced
        assert batch.total_accounts == 1
        assert batch.succeeded == 1
        assert batch.skipped == 0
        assert batch.failed == 0
        assert batch.total_positions_synced == 1
        assert len(position_repo._items) == 1

    async def test_filter_env_live_only(
        self,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """When ``env=Environment.LIVE``, only live accounts are synced."""
        broker_account_id_paper = uuid4()
        broker_account_id_live = uuid4()
        account_id_live = uuid4()

        broker_repo = InMemoryBrokerAccountRepository()
        await broker_repo.add(BrokerAccountEntity(
            broker_account_id=broker_account_id_paper,
            broker_name="koreainvestment",
            account_ref="1111111111",
            environment=Environment.PAPER,
            credential_ref="default",
        ))
        await broker_repo.add(BrokerAccountEntity(
            broker_account_id=broker_account_id_live,
            broker_name="koreainvestment",
            account_ref="2222222222",
            environment=Environment.LIVE,
            credential_ref="default",
        ))

        account_repo = InMemoryAccountRepository()
        await account_repo.add(AccountEntity(
            account_id=account_id_live,
            client_id=uuid4(),
            broker_account_id=broker_account_id_live,
            account_alias="KIS-LIVE",
            account_masked="****2222",
            environment=Environment.LIVE,
            status="active",
        ))

        client = FakeKISRestClient(
            positions=[_make_position(pdno="005930")],
            cash_balance=_make_cash_balance(),
        )

        batch = await sync_all_kis_accounts(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            broker_account_repo=broker_repo,
            account_repo=account_repo,
            env=Environment.LIVE,
        )

        assert batch.total_accounts == 1
        assert batch.succeeded == 1
        assert batch.skipped == 0
        assert batch.failed == 0
        assert batch.total_positions_synced == 1
        assert len(position_repo._items) == 1

    async def test_filter_env_none(
        self,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """When ``env=None``, all environments are discovered (backward compat)."""
        broker_account_id_paper = uuid4()
        broker_account_id_live = uuid4()
        account_id_paper = uuid4()
        account_id_live = uuid4()

        broker_repo = InMemoryBrokerAccountRepository()
        await broker_repo.add(BrokerAccountEntity(
            broker_account_id=broker_account_id_paper,
            broker_name="koreainvestment",
            account_ref="1111111111",
            environment=Environment.PAPER,
            credential_ref="default",
        ))
        await broker_repo.add(BrokerAccountEntity(
            broker_account_id=broker_account_id_live,
            broker_name="koreainvestment",
            account_ref="2222222222",
            environment=Environment.LIVE,
            credential_ref="default",
        ))

        account_repo = InMemoryAccountRepository()
        await account_repo.add(AccountEntity(
            account_id=account_id_paper,
            client_id=uuid4(),
            broker_account_id=broker_account_id_paper,
            account_alias="KIS-PAPER",
            account_masked="****1111",
            environment=Environment.PAPER,
            status="active",
        ))
        await account_repo.add(AccountEntity(
            account_id=account_id_live,
            client_id=uuid4(),
            broker_account_id=broker_account_id_live,
            account_alias="KIS-LIVE",
            account_masked="****2222",
            environment=Environment.LIVE,
            status="active",
        ))

        client = FakeKISRestClient(
            positions=[_make_position(pdno="005930")],
            cash_balance=_make_cash_balance(),
        )

        batch = await sync_all_kis_accounts(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            broker_account_repo=broker_repo,
            account_repo=account_repo,
            env=None,
        )

        assert batch.total_accounts == 2
        assert batch.succeeded == 2
        assert batch.skipped == 0
        assert batch.failed == 0
        assert batch.total_positions_synced == 2
        assert len(position_repo._items) == 2


# ── Snapshot sync run history tests ────────────────────────────────────


class TestSnapshotSyncRunEntity:
    """``SnapshotSyncRunEntity`` construction validation."""

    def test_manual_single_completed(self) -> None:
        """A fully successful manual single-account sync."""
        now = datetime.now(timezone.utc)
        entity = SnapshotSyncRunEntity(
            snapshot_sync_run_id=uuid4(),
            trigger_type="manual",
            scope="single",
            dry_run=False,
            total_accounts=1,
            succeeded_accounts=1,
            partial_accounts=0,
            failed_accounts=0,
            skipped_accounts=0,
            positions_synced_total=5,
            positions_skipped_total=0,
            cash_synced_count=1,
            error_count=0,
            status="completed",
            started_at=now,
            completed_at=now,
        )
        assert entity.trigger_type == "manual"
        assert entity.status == "completed"
        assert entity.scope == "single"
        assert entity.dry_run is False

    def test_scheduler_all_partial(self) -> None:
        """A scheduler run with partial success."""
        now = datetime.now(timezone.utc)
        entity = SnapshotSyncRunEntity(
            snapshot_sync_run_id=uuid4(),
            trigger_type="scheduler",
            scope="all",
            dry_run=False,
            total_accounts=5,
            succeeded_accounts=3,
            partial_accounts=1,
            failed_accounts=1,
            skipped_accounts=0,
            positions_synced_total=15,
            positions_skipped_total=2,
            cash_synced_count=4,
            error_count=2,
            status="partial",
            started_at=now,
            completed_at=now,
        )
        assert entity.trigger_type == "scheduler"
        assert entity.status == "partial"
        assert entity.scope == "all"

    def test_manual_single_failed(self) -> None:
        """A fully failed manual sync."""
        now = datetime.now(timezone.utc)
        entity = SnapshotSyncRunEntity(
            snapshot_sync_run_id=uuid4(),
            trigger_type="manual",
            scope="single",
            dry_run=False,
            total_accounts=1,
            succeeded_accounts=0,
            partial_accounts=0,
            failed_accounts=1,
            skipped_accounts=0,
            positions_synced_total=0,
            positions_skipped_total=0,
            cash_synced_count=0,
            error_count=3,
            status="failed",
            started_at=now,
            completed_at=now,
        )
        assert entity.status == "failed"
        assert entity.failed_accounts == 1
        assert entity.error_count == 3

    def test_dry_run_flag(self) -> None:
        """Dry-run flag is stored correctly."""
        now = datetime.now(timezone.utc)
        entity = SnapshotSyncRunEntity(
            snapshot_sync_run_id=uuid4(),
            trigger_type="manual",
            scope="all",
            dry_run=True,
            total_accounts=2,
            succeeded_accounts=2,
            partial_accounts=0,
            failed_accounts=0,
            skipped_accounts=0,
            positions_synced_total=10,
            positions_skipped_total=0,
            cash_synced_count=2,
            error_count=0,
            status="completed",
            started_at=now,
        )
        assert entity.dry_run is True

    def test_with_env_and_status_filter(self) -> None:
        """Entity stores env_filter and status_filter when provided."""
        now = datetime.now(timezone.utc)
        entity = SnapshotSyncRunEntity(
            snapshot_sync_run_id=uuid4(),
            trigger_type="manual",
            scope="all",
            dry_run=False,
            total_accounts=3,
            succeeded_accounts=2,
            partial_accounts=1,
            failed_accounts=0,
            skipped_accounts=0,
            positions_synced_total=8,
            positions_skipped_total=1,
            cash_synced_count=2,
            error_count=1,
            status="partial",
            started_at=now,
            env_filter="paper",
            status_filter="active",
        )
        assert entity.env_filter == "paper"
        assert entity.status_filter == "active"

    def test_with_summary_json(self) -> None:
        """Entity stores summary_json dict."""
        now = datetime.now(timezone.utc)
        entity = SnapshotSyncRunEntity(
            snapshot_sync_run_id=uuid4(),
            trigger_type="scheduler",
            scope="all",
            dry_run=False,
            total_accounts=10,
            succeeded_accounts=10,
            partial_accounts=0,
            failed_accounts=0,
            skipped_accounts=0,
            positions_synced_total=50,
            positions_skipped_total=0,
            cash_synced_count=10,
            error_count=0,
            status="completed",
            started_at=now,
            summary_json={"duration_seconds": 12.5},
        )
        assert entity.summary_json is not None
        assert entity.summary_json["duration_seconds"] == 12.5


class TestBuildSyncRunEntity:
    """``build_sync_run_entity()`` status classification tests."""

    def test_completed_no_errors(self) -> None:
        """Zero failures + zero errors → status='completed'."""
        batch = BatchSyncResult(
            total_accounts=2,
            succeeded=2,
            partial=0,
            failed=0,
            skipped=0,
            total_positions_synced=10,
            total_positions_skipped=0,
            total_cash_synced=2,
            errors=[],
        )
        entity = build_sync_run_entity(
            batch,
            trigger_type="manual",
            scope="batch",
            dry_run=False,
        )
        assert entity.status == "completed"
        assert entity.total_accounts == 2
        assert entity.succeeded_accounts == 2
        assert entity.failed_accounts == 0
        assert entity.error_count == 0
        assert entity.trigger_type == "manual"
        assert entity.scope == "batch"

    def test_partial_some_failures(self) -> None:
        """Some failures but partial success → status='partial'."""
        batch = BatchSyncResult(
            total_accounts=3,
            succeeded=2,
            partial=1,
            failed=0,
            skipped=0,
            total_positions_synced=8,
            total_positions_skipped=2,
            total_cash_synced=2,
            errors=["Account B: timeout"],
        )
        entity = build_sync_run_entity(
            batch,
            trigger_type="scheduler",
            scope="all",
            dry_run=False,
        )
        assert entity.status == "partial"
        assert entity.error_count == 1
        assert entity.trigger_type == "scheduler"
        assert entity.scope == "all"

    def test_failed_all_fail(self) -> None:
        """All accounts failed → status='failed'."""
        batch = BatchSyncResult(
            total_accounts=2,
            succeeded=0,
            partial=0,
            failed=2,
            skipped=0,
            total_positions_synced=0,
            total_positions_skipped=0,
            total_cash_synced=0,
            errors=["Account A: auth error", "Account B: network error"],
        )
        entity = build_sync_run_entity(
            batch,
            trigger_type="manual",
            scope="single",
            dry_run=False,
        )
        assert entity.status == "failed"
        assert entity.error_count == 2
        assert entity.succeeded_accounts == 0
        assert entity.failed_accounts == 2

    def test_partial_with_only_partial_count(self) -> None:
        """batch.partial > 0 but no failures → status='partial'."""
        batch = BatchSyncResult(
            total_accounts=1,
            succeeded=0,
            partial=1,
            failed=0,
            skipped=0,
            total_positions_synced=3,
            total_positions_skipped=2,
            total_cash_synced=1,
            errors=[],
        )
        entity = build_sync_run_entity(
            batch,
            trigger_type="manual",
            scope="single",
            dry_run=False,
        )
        assert entity.status == "partial"

    def test_dry_run_propagated(self) -> None:
        """dry_run flag is passed through to entity."""
        batch = BatchSyncResult(
            total_accounts=1,
            succeeded=1,
            errors=[],
        )
        entity = build_sync_run_entity(
            batch,
            trigger_type="manual",
            scope="single",
            dry_run=True,
        )
        assert entity.dry_run is True

    def test_env_status_filter_propagated(self) -> None:
        """env_filter and status_filter are passed through."""
        batch = BatchSyncResult(total_accounts=1, succeeded=1, errors=[])
        entity = build_sync_run_entity(
            batch,
            trigger_type="manual",
            scope="all",
            dry_run=False,
            env_filter="live",
            status_filter="active",
        )
        assert entity.env_filter == "live"
        assert entity.status_filter == "active"

    def test_summary_json_embeds_errors_and_positions_skipped(self) -> None:
        """run summary should retain snapshot mapping errors for later inspection."""
        batch = BatchSyncResult(
            total_accounts=1,
            succeeded=0,
            partial=1,
            failed=0,
            skipped=0,
            total_positions_synced=0,
            total_positions_skipped=2,
            total_cash_synced=1,
            errors=[
                "Instrument not found for pdno=005940 — skipped",
                "Instrument not found for pdno=001234 — skipped",
            ],
        )
        entity = build_sync_run_entity(
            batch,
            trigger_type="scheduler",
            scope="all",
            summary_json={"VTTC8434R_pre_check": 1},
        )
        assert entity.summary_json is not None
        assert entity.summary_json["VTTC8434R_pre_check"] == 1
        assert entity.summary_json["positions_skipped_total"] == 2
        assert entity.summary_json["errors"] == [
            "Instrument not found for pdno=005940 — skipped",
            "Instrument not found for pdno=001234 — skipped",
        ]


class TestSnapshotSyncRunRepository:
    """``InMemorySnapshotSyncRunRepository`` round-trip tests."""

    async def test_add_and_retrieve(self) -> None:
        """Adding a run entity succeeds and returns it."""
        repo = InMemorySnapshotSyncRunRepository()
        now = datetime.now(timezone.utc)
        entity = SnapshotSyncRunEntity(
            snapshot_sync_run_id=uuid4(),
            trigger_type="manual",
            scope="single",
            dry_run=False,
            total_accounts=1,
            succeeded_accounts=1,
            partial_accounts=0,
            failed_accounts=0,
            skipped_accounts=0,
            positions_synced_total=5,
            positions_skipped_total=0,
            cash_synced_count=1,
            error_count=0,
            status="completed",
            started_at=now,
        )
        saved = await repo.add(entity)
        assert saved.snapshot_sync_run_id == entity.snapshot_sync_run_id
        assert saved.status == "completed"
        assert len(repo._items) == 1

    async def test_add_multiple_runs(self) -> None:
        """Multiple runs can be added independently."""
        repo = InMemorySnapshotSyncRunRepository()
        now = datetime.now(timezone.utc)
        e1 = SnapshotSyncRunEntity(
            snapshot_sync_run_id=uuid4(),
            trigger_type="manual", scope="single", dry_run=False,
            total_accounts=1, succeeded_accounts=1,
            partial_accounts=0, failed_accounts=0, skipped_accounts=0,
            positions_synced_total=3, positions_skipped_total=0,
            cash_synced_count=1, error_count=0, status="completed",
            started_at=now,
        )
        e2 = SnapshotSyncRunEntity(
            snapshot_sync_run_id=uuid4(),
            trigger_type="scheduler", scope="all", dry_run=False,
            total_accounts=5, succeeded_accounts=4,
            partial_accounts=1, failed_accounts=0, skipped_accounts=0,
            positions_synced_total=20, positions_skipped_total=1,
            cash_synced_count=5, error_count=1, status="partial",
            started_at=now,
        )
        await repo.add(e1)
        await repo.add(e2)
        assert len(repo._items) == 2


class TestSyncAllWithStatusFilter:
    """``sync_all_kis_accounts()`` — account status (``account_status``) filter tests."""

    async def test_filter_status_active(
        self,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """When ``account_status='active'``, inactive accounts are skipped."""
        broker_account_id_active = uuid4()
        broker_account_id_inactive = uuid4()
        account_id_active = uuid4()

        broker_repo = InMemoryBrokerAccountRepository()
        await broker_repo.add(BrokerAccountEntity(
            broker_account_id=broker_account_id_active,
            broker_name="koreainvestment",
            account_ref="1111111111",
            environment=Environment.PAPER,
            credential_ref="default",
        ))
        await broker_repo.add(BrokerAccountEntity(
            broker_account_id=broker_account_id_inactive,
            broker_name="koreainvestment",
            account_ref="2222222222",
            environment=Environment.PAPER,
            credential_ref="default",
        ))

        account_repo = InMemoryAccountRepository()
        await account_repo.add(AccountEntity(
            account_id=account_id_active,
            client_id=uuid4(),
            broker_account_id=broker_account_id_active,
            account_alias="KIS-ACTIVE",
            account_masked="****1111",
            environment=Environment.PAPER,
            status="active",
        ))
        # Inactive account — no matching AccountEntity in this test
        # (it exists but has status="inactive" so will be skipped)

        client = FakeKISRestClient(
            positions=[_make_position(pdno="005930")],
            cash_balance=_make_cash_balance(),
        )

        batch = await sync_all_kis_accounts(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            broker_account_repo=broker_repo,
            account_repo=account_repo,
            account_status="active",
        )

        assert batch.total_accounts == 2
        assert batch.succeeded == 1
        assert batch.skipped == 1  # inactive account has no AccountEntity → skipped
        assert batch.failed == 0

    async def test_filter_status_inactive(
        self,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """When ``account_status='inactive'``, active accounts are skipped."""
        broker_account_id_active = uuid4()
        broker_account_id_inactive = uuid4()
        account_id_inactive = uuid4()

        broker_repo = InMemoryBrokerAccountRepository()
        await broker_repo.add(BrokerAccountEntity(
            broker_account_id=broker_account_id_active,
            broker_name="koreainvestment",
            account_ref="1111111111",
            environment=Environment.PAPER,
            credential_ref="default",
        ))
        await broker_repo.add(BrokerAccountEntity(
            broker_account_id=broker_account_id_inactive,
            broker_name="koreainvestment",
            account_ref="2222222222",
            environment=Environment.PAPER,
            credential_ref="default",
        ))

        account_repo = InMemoryAccountRepository()
        await account_repo.add(AccountEntity(
            account_id=account_id_inactive,
            client_id=uuid4(),
            broker_account_id=broker_account_id_inactive,
            account_alias="KIS-INACTIVE",
            account_masked="****2222",
            environment=Environment.PAPER,
            status="inactive",
        ))

        client = FakeKISRestClient(
            positions=[_make_position(pdno="005930")],
            cash_balance=_make_cash_balance(),
        )

        batch = await sync_all_kis_accounts(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            broker_account_repo=broker_repo,
            account_repo=account_repo,
            account_status="inactive",
        )

        assert batch.total_accounts == 2
        assert batch.succeeded == 1
        # active account has no AccountEntity with status="inactive"
        # so it is discovered but the broker account resolves to an AccountEntity
        # whose status ("active") != "inactive" → skipped
        assert batch.skipped == 1
        assert batch.failed == 0

    async def test_filter_status_none(
        self,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """When ``account_status=None``, all statuses are synced (backward compat)."""
        broker_account_id_active = uuid4()
        broker_account_id_inactive = uuid4()
        account_id_active = uuid4()
        account_id_inactive = uuid4()

        broker_repo = InMemoryBrokerAccountRepository()
        await broker_repo.add(BrokerAccountEntity(
            broker_account_id=broker_account_id_active,
            broker_name="koreainvestment",
            account_ref="1111111111",
            environment=Environment.PAPER,
            credential_ref="default",
        ))
        await broker_repo.add(BrokerAccountEntity(
            broker_account_id=broker_account_id_inactive,
            broker_name="koreainvestment",
            account_ref="2222222222",
            environment=Environment.PAPER,
            credential_ref="default",
        ))

        account_repo = InMemoryAccountRepository()
        await account_repo.add(AccountEntity(
            account_id=account_id_active,
            client_id=uuid4(),
            broker_account_id=broker_account_id_active,
            account_alias="KIS-ACTIVE",
            account_masked="****1111",
            environment=Environment.PAPER,
            status="active",
        ))
        await account_repo.add(AccountEntity(
            account_id=account_id_inactive,
            client_id=uuid4(),
            broker_account_id=broker_account_id_inactive,
            account_alias="KIS-INACTIVE",
            account_masked="****2222",
            environment=Environment.PAPER,
            status="inactive",
        ))

        client = FakeKISRestClient(
            positions=[_make_position(pdno="005930")],
            cash_balance=_make_cash_balance(),
        )

        batch = await sync_all_kis_accounts(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            broker_account_repo=broker_repo,
            account_repo=account_repo,
            account_status=None,
        )

        assert batch.total_accounts == 2
        assert batch.succeeded == 2
        assert batch.skipped == 0
        assert batch.failed == 0
        assert batch.total_positions_synced == 2
        assert len(position_repo._items) == 2


# ── Zero-out Tests ─────────────────────────────────────────────────────────


class TestZeroOutMissingPositions:
    """``sync_kis_account_snapshots()`` zero-out logic for positions missing
    from the KIS response."""

    async def _seed_snapshot(
        self,
        position_repo: InMemoryPositionSnapshotRepository,
        account_id: UUID,
        instrument_id: UUID,
        quantity: Decimal,
        snapshot_at: datetime | None = None,
    ) -> PositionSnapshotEntity:
        """Helper to seed a position snapshot into the in-memory repo."""
        snap = PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=quantity,
            average_price=Decimal("70000"),
            market_price=Decimal("72000"),
            unrealized_pnl=Decimal("20000"),
            source_of_truth="broker",
            snapshot_at=snapshot_at or datetime.now(tz=timezone.utc),
        )
        await position_repo.add(snap)
        return snap

    async def test_sync_zeroes_out_missing_positions(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """KIS 응답에 없는 종목이 quantity=0으로 저장되는지 검증.

        시나리오:
        1. 기존 snapshot: 000990=10, 005930=10
        2. KIS 응답: 005930=10만 있음
        3. zero-out 후: 000990=0, 005930=10
        """
        # Given: fixture가 pre-seed한 005930(삼성전자)을 재사용하고,
        #        000990(한국금융지주)을 추가로 등록
        kiwoom = _make_instrument("000990")
        await instrument_repo.add(kiwoom)

        # fixture의 005930 instrument 조회 (get_by_symbol 사용)
        samsung = await instrument_repo.get_by_symbol("005930", "KRX")
        assert samsung is not None

        now = datetime.now(tz=timezone.utc)
        await self._seed_snapshot(position_repo, account_id, kiwoom.instrument_id, Decimal("10"), now)
        await self._seed_snapshot(position_repo, account_id, samsung.instrument_id, Decimal("10"), now)

        # When: KIS 응답에는 005930만 있음
        client = FakeKISRestClient(
            positions=[_make_position(pdno="005930", hldg_qty="10")],
            cash_balance={},
        )
        result = await sync_kis_account_snapshots(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_id=account_id,
        )

        # Then: 005930은 그대로, 000990은 quantity=0으로 zero-out
        assert result.positions_synced == 1  # 005930만 sync됨

        # list_latest_by_account로 최신 snapshot 확인
        latest = await position_repo.list_latest_by_account(account_id)
        latest_by_instrument: dict[UUID, PositionSnapshotEntity] = {}
        for snap in latest:
            if snap.instrument_id not in latest_by_instrument or snap.snapshot_at > latest_by_instrument[snap.instrument_id].snapshot_at:
                latest_by_instrument[snap.instrument_id] = snap

        # 005930은 quantity=10 유지
        samsung_latest = latest_by_instrument[samsung.instrument_id]
        assert samsung_latest.quantity == Decimal("10")

        # 000990은 quantity=0으로 zero-out됨
        kiwoom_latest = latest_by_instrument[kiwoom.instrument_id]
        assert kiwoom_latest.quantity == Decimal("0")
        assert kiwoom_latest.source_of_truth == "broker"

    async def test_sync_preserves_existing_positions(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """KIS 응답에 있는 종목은 그대로 유지되는지 검증.

        시나리오:
        1. 기존 snapshot: 005930=10
        2. KIS 응답: 005930=10
        3. zero-out 후: 005930=10 (변화 없음)
        """
        # fixture의 005930 instrument 재사용
        samsung = await instrument_repo.get_by_symbol("005930", "KRX")
        assert samsung is not None

        now = datetime.now(tz=timezone.utc)
        await self._seed_snapshot(position_repo, account_id, samsung.instrument_id, Decimal("10"), now)

        client = FakeKISRestClient(
            positions=[_make_position(pdno="005930", hldg_qty="10")],
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

        latest = await position_repo.list_latest_by_account(account_id)
        samsung_snaps = [s for s in latest if s.instrument_id == samsung.instrument_id]
        # 최신 snapshot의 quantity가 10인지 확인
        latest_snap = max(samsung_snaps, key=lambda s: s.snapshot_at)
        assert latest_snap.quantity == Decimal("10")

    async def test_sync_does_not_zero_out_recently_zeroed(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """이미 quantity=0인 종목은 다시 zero-out하지 않는지 검증.

        시나리오:
        1. 기존 snapshot: 000990=0 (이미 zero-out됨)
        2. KIS 응답: 005930=10만 있음
        3. zero-out 후: 000990=0 (중복 zero-out 없음)
        """
        kiwoom = _make_instrument("000990")
        await instrument_repo.add(kiwoom)
        samsung = await instrument_repo.get_by_symbol("005930", "KRX")
        assert samsung is not None

        now = datetime.now(tz=timezone.utc)
        # 이미 zero-out된 snapshot
        await self._seed_snapshot(position_repo, account_id, kiwoom.instrument_id, Decimal("0"), now)
        await self._seed_snapshot(position_repo, account_id, samsung.instrument_id, Decimal("10"), now)

        client = FakeKISRestClient(
            positions=[_make_position(pdno="005930", hldg_qty="10")],
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

        # 000990의 snapshot 수가 1개인지 확인 (중복 zero-out 없음)
        kiwoom_snaps = [s for s in position_repo._items.values()
                        if s.instrument_id == kiwoom.instrument_id]
        assert len(kiwoom_snaps) == 1  # 중복 zero-out 없음
        assert kiwoom_snaps[0].quantity == Decimal("0")

    async def test_sync_zero_out_handles_exception_gracefully(
        self,
        account_id: UUID,
        instrument_repo: InMemoryInstrumentRepository,
        position_repo: InMemoryPositionSnapshotRepository,
        cash_repo: InMemoryCashBalanceSnapshotRepository,
    ) -> None:
        """zero-out 중 예외 발생 시 graceful handling 검증.

        전체 sync 실패로 이어지지 않아야 함.
        """
        samsung = await instrument_repo.get_by_symbol("005930", "KRX")
        assert samsung is not None

        now = datetime.now(tz=timezone.utc)
        await self._seed_snapshot(position_repo, account_id, samsung.instrument_id, Decimal("10"), now)

        # list_latest_by_account가 예외를 던지도록 mocking
        original_list_latest = position_repo.list_latest_by_account

        async def failing_list_latest(_account_id: UUID) -> list[PositionSnapshotEntity]:
            raise RuntimeError("DB connection lost")

        position_repo.list_latest_by_account = failing_list_latest  # type: ignore[assignment]

        client = FakeKISRestClient(
            positions=[_make_position(pdno="005930", hldg_qty="10")],
            cash_balance={},
        )
        # zero-out 실패에도 전체 sync는 성공해야 함
        result = await sync_kis_account_snapshots(
            rest_client=client,
            instrument_repo=instrument_repo,
            position_snapshot_repo=position_repo,
            cash_balance_snapshot_repo=cash_repo,
            account_id=account_id,
        )

        # zero-out 실패가 전체 sync를 중단시키지 않음
        assert result.positions_synced == 1

        # list_latest_by_account 복원
        position_repo.list_latest_by_account = original_list_latest
