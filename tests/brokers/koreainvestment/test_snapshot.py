"""Tests for ``KISSyncSnapshotProvider`` — KIS implementation of ``SnapshotFetchProvider``.

Verifies:
- Provider conforms to ``SnapshotFetchProvider`` protocol
- Position field mapping (pdno → instrument_id, qty, price)
- Cash balance mapping (dnca_tot_amt → available_cash, etc.)
- ``get_orderable_cash()`` integration — ``orderable_amount`` populated from ``VTTC8908R``
- Instrument lookup failure → skip + error
- Empty responses
- Error propagation from REST client failures
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from agent_trading.brokers.koreainvestment.rest_client import (
    CashAndPositionsResult,
    KISRestClient,
    OrderableCashResult,
)
from agent_trading.brokers.koreainvestment.snapshot import (
    KISSyncSnapshotProvider,
)
from agent_trading.domain.entities import (
    CashBalanceSnapshotEntity,
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
    """Simulates KIS REST client with configurable responses.

    Supports ``get_orderable_cash()`` for ``VTTC8908R`` integration testing.
    """

    def __init__(
        self,
        positions: list[dict[str, Any]] | None = None,
        cash_balance: dict[str, Any] | None = None,
        fail_positions: bool = False,
        fail_cash: bool = False,
        orderable_cash: Decimal | None = None,
        fail_orderable_cash: bool = False,
        account_number: str = "test_account",
    ) -> None:
        self._positions = positions or []
        self._cash_balance = cash_balance or {}
        self._fail_positions = fail_positions
        self._fail_cash = fail_cash
        self._orderable_cash = orderable_cash
        self._fail_orderable_cash = fail_orderable_cash
        self.account_number = account_number
        self.closed = False

    async def get_positions(self) -> list[dict[str, Any]]:
        if self._fail_positions:
            raise RuntimeError("KIS positions fetch failed")
        return self._positions

    async def get_cash_balance(self, after_hours: bool = False) -> dict[str, Any]:
        if self._fail_cash:
            raise RuntimeError("KIS cash balance fetch failed")
        return self._cash_balance

    async def get_cash_and_positions(
        self,
        *,
        after_hours: bool = False,
    ) -> CashAndPositionsResult:
        """Simulate VTTC8434R 1회 통합 호출.

        ``fail_cash`` 설정 시 예외 발생 (기존 get_cash_balance 실패 시뮬레이션).
        ``fail_positions`` 단독 설정은 통합 호출에서 전체 실패로 처리.
        """
        if self._fail_cash or self._fail_positions:
            raise RuntimeError("KIS cash+positions fetch failed")
        return CashAndPositionsResult(
            cash_balance=self._cash_balance if self._cash_balance else None,
            positions=self._positions,
            raw_response={},
        )

    async def get_orderable_cash(
        self,
        account_ref: str = "",
        symbol: str = "",
        price: str = "",
        order_type: str = "00",
        fallback_cash: Decimal | None = None,
    ) -> Decimal | None:
        if self._fail_orderable_cash:
            raise RuntimeError("KIS orderable cash fetch failed")
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

    async def test_position_mapping_uses_any_market_lookup_for_segment_row(self) -> None:
        """KOSPI/KOSDAQ segment row만 있어도 canonical lookup으로 매핑된다."""
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

        inst_repo = InMemoryInstrumentRepository()
        inst = InstrumentEntity(
            instrument_id=inst_id,
            symbol="005930",
            name="Samsung Electronics",
            market_code="KOSPI",
            asset_class="stock",
            currency="KRW",
            exchange_code="KRX",
            market_segment="KOSPI",
        )
        await inst_repo.add(inst)

        result = await provider.fetch_snapshot(account_id, inst_repo)
        assert len(result.positions) == 1
        assert result.positions[0].instrument_id == inst_id

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

    async def test_cash_balance_orderable_amount_from_vttc8908r(self) -> None:
        """``get_orderable_cash()`` returns value → ``orderable_amount`` uses VTTC8908R."""
        account_id = uuid4()
        client = FakeKISRestClient(
            positions=[],
            cash_balance={
                "dnca_tot_amt": "1000000",
                "nxdy_excc_amt": "800000",
                "ord_psbl_amt": "-81419050",  # VTTC8434R fallback — should be overridden
            },
            orderable_cash=Decimal("500000"),  # VTTC8908R response
        )
        provider = KISSyncSnapshotProvider(client)
        inst_repo = InMemoryInstrumentRepository()

        result = await provider.fetch_snapshot(account_id, inst_repo)
        assert result.cash_balance is not None
        cash = result.cash_balance
        # VTTC8908R 값이 우선 적용되어야 함
        assert cash.orderable_amount == 500000, (
            f"Expected 500000 from VTTC8908R, got {cash.orderable_amount}"
        )
        assert cash.available_cash == 1000000  # unchanged
        assert cash.settled_cash == 800000  # unchanged
        assert cash.currency == "KRW"

    async def test_cash_balance_orderable_amount_fallback_to_vttc8434r(self) -> None:
        """``get_orderable_cash()`` returns None → falls back to ``ord_psbl_amt`` from VTTC8434R."""
        account_id = uuid4()
        client = FakeKISRestClient(
            positions=[],
            cash_balance={
                "dnca_tot_amt": "1000000",
                "nxdy_excc_amt": "800000",
                "ord_psbl_amt": "-81419050",
            },
            orderable_cash=None,  # VTTC8908R unavailable
        )
        provider = KISSyncSnapshotProvider(client)
        inst_repo = InMemoryInstrumentRepository()

        result = await provider.fetch_snapshot(account_id, inst_repo)
        assert result.cash_balance is not None
        cash = result.cash_balance
        # VTTC8908R이 None → VTTC8434R의 ord_psbl_amt로 fallback
        assert cash.orderable_amount == -81419050, (
            f"Expected -81419050 from VTTC8434R fallback, got {cash.orderable_amount}"
        )
        assert cash.available_cash == 1000000  # unchanged
        assert cash.currency == "KRW"

    async def test_cash_balance_orderable_amount_all_none(self) -> None:
        """Both VTTC8908R and VTTC8434R unavailable → BUY-safe zero."""
        account_id = uuid4()
        client = FakeKISRestClient(
            positions=[],
            cash_balance={
                "dnca_tot_amt": "1000000",
                "nxdy_excc_amt": "800000",
                # No ord_psbl_amt in VTTC8434R response
            },
            orderable_cash=None,  # VTTC8908R also unavailable
        )
        provider = KISSyncSnapshotProvider(client)
        inst_repo = InMemoryInstrumentRepository()

        result = await provider.fetch_snapshot(account_id, inst_repo)
        assert result.cash_balance is not None
        cash = result.cash_balance
        # 최종 fallback: available_cash 승격 금지 → 0으로 고정
        assert cash.orderable_amount == 0, (
            f"Expected 0 (safe zero fallback), got {cash.orderable_amount}"
        )
        assert cash.available_cash == 1000000  # unchanged
        assert cash.fetch_status == "stale"
        assert cash.currency == "KRW"

    async def test_cash_balance_orderable_amount_vttc8908r_failure(self) -> None:
        """``get_orderable_cash()`` raises → BUY-safe zero."""
        account_id = uuid4()
        client = FakeKISRestClient(
            positions=[],
            cash_balance={
                "dnca_tot_amt": "1000000",
                "nxdy_excc_amt": "800000",
                "ord_psbl_amt": "300000",
            },
            orderable_cash=None,
            fail_orderable_cash=True,  # VTTC8908R raises exception
        )
        provider = KISSyncSnapshotProvider(client)
        inst_repo = InMemoryInstrumentRepository()

        result = await provider.fetch_snapshot(account_id, inst_repo)
        assert result.cash_balance is not None
        cash = result.cash_balance
        # VTTC8908R 일반 Exception 실패 → available_cash 승격 금지
        assert cash.orderable_amount == 0, (
            f"Expected 0 from Exception fallback, "
            f"got {cash.orderable_amount}"
        )
        assert cash.available_cash == 1000000  # unchanged
        assert cash.fetch_status == "stale"
        assert cash.currency == "KRW"

    async def test_cash_balance_logs_budget_precheck_fallback_source(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level("INFO")
        account_id = uuid4()
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
            cash_balance={
                "dnca_tot_amt": "1000000",
                "nxdy_excc_amt": "800000",
            },
            orderable_cash=None,
        )
        provider = KISSyncSnapshotProvider(client)
        inst_repo = InMemoryInstrumentRepository()

        await provider.fetch_snapshot(account_id, inst_repo)

        assert "source: budget_precheck_fallback" in caplog.text

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
        # 통합 호출(get_cash_and_positions) 실패 → cash+positions 메시지
        assert any("cash+positions" in err.lower() for err in result.errors)

    async def test_positions_fetch_failure(self) -> None:
        """REST client failure → error, empty positions (통합 호출 전체 실패)."""
        client = FakeKISRestClient(fail_positions=True)
        provider = KISSyncSnapshotProvider(client)
        inst_repo = InMemoryInstrumentRepository()

        result = await provider.fetch_snapshot(uuid4(), inst_repo)
        # 통합 호출 실패로 positions도 빔
        assert len(result.positions) == 0
        # cash+positions 통합 에러 메시지 (통합 호출이므로)
        assert any("cash+positions" in err.lower() for err in result.errors)


class TestFetchSnapshot:
    """fetch_snapshot — after-hours rate-limit hotfix tests."""

    async def _make_cp_mock(
        self,
        cash_balance: dict[str, Any] | None = None,
        positions: list[dict[str, Any]] | None = None,
    ) -> AsyncMock:
        """Helper: create a mock ``KISRestClient`` with ``get_cash_and_positions``."""
        from unittest.mock import AsyncMock

        mock = AsyncMock(spec=KISRestClient)
        cp_result = CashAndPositionsResult(
            cash_balance=cash_balance,
            positions=positions or [],
            raw_response={},
        )
        mock.get_cash_and_positions = AsyncMock(return_value=cp_result)
        mock.get_orderable_cash = AsyncMock(return_value=None)
        return mock

    async def test_fetch_snapshot_after_hours_skips_positions(self) -> None:
        """after_hours=True → get_cash_and_positions()만 호출, positions는 건너뜀."""
        mock_rest = await self._make_cp_mock(
            cash_balance={},
        )

        provider = KISSyncSnapshotProvider(mock_rest)
        inst_repo = InMemoryInstrumentRepository()

        result = await provider.fetch_snapshot(uuid4(), inst_repo, after_hours=True)

        # get_cash_and_positions(after_hours=True)는 호출되어야 함
        mock_rest.get_cash_and_positions.assert_awaited_once_with(after_hours=True)

        # positions는 빈 리스트 (after_hours로 skip)
        assert result.positions == []

    async def test_fetch_snapshot_after_hours_can_fetch_positions_once(self) -> None:
        mock_rest = await self._make_cp_mock(
            cash_balance={},
            positions=[{"pdno": "005930", "hldg_qty": "10", "pchs_avg_pric": "50000"}],
        )

        provider = KISSyncSnapshotProvider(mock_rest)
        inst_repo = InMemoryInstrumentRepository()
        inst = InstrumentEntity(
            instrument_id=uuid4(),
            symbol="005930",
            name="Samsung Electronics",
            market_code="KRX",
            asset_class="stock",
            currency="KRW",
        )
        inst_repo._items[inst.instrument_id] = inst

        result = await provider.fetch_snapshot(
            uuid4(),
            inst_repo,
            after_hours=True,
            allow_after_hours_positions=True,
        )

        mock_rest.get_cash_and_positions.assert_awaited_once_with(after_hours=True)
        assert len(result.positions) == 1

    async def test_fetch_snapshot_after_hours_returns_cash_only(self) -> None:
        """after_hours=True → positions는 빈 리스트, cash_balance는 정상, 에러 없음."""
        account_id = uuid4()
        mock_rest = await self._make_cp_mock(
            cash_balance={"dnca_tot_amt": "2000000", "nxdy_excc_amt": "1500000"},
        )

        provider = KISSyncSnapshotProvider(mock_rest)
        inst_repo = InMemoryInstrumentRepository()

        result = await provider.fetch_snapshot(account_id, inst_repo, after_hours=True)

        # positions는 빈 리스트
        assert result.positions == []

        # cash_balance는 정상
        assert result.cash_balance is not None
        assert result.cash_balance.available_cash == 2000000
        assert result.cash_balance.settled_cash == 1500000

        # 에러 리스트에 positions 관련 에러가 없어야 함
        assert not any("position" in err.lower() for err in result.errors)

    async def test_fetch_snapshot_fetch_positions_false(self) -> None:
        """``fetch_positions=False`` → positions는 빈 리스트, cash+orderable은 정상."""
        from unittest.mock import AsyncMock

        account_id = uuid4()
        mock_rest = await self._make_cp_mock(
            cash_balance={"dnca_tot_amt": "2000000", "nxdy_excc_amt": "1500000"},
            positions=[
                {"pdno": "005930", "hldg_qty": "10"},
            ],
        )
        mock_rest.get_orderable_cash_result = AsyncMock(
            return_value=OrderableCashResult(
                amount=Decimal("1800000"),
                source="vttc8908r",
            )
        )

        provider = KISSyncSnapshotProvider(mock_rest)
        inst_repo = InMemoryInstrumentRepository()

        result = await provider.fetch_snapshot(
            account_id, inst_repo, fetch_positions=False,
        )

        # get_cash_and_positions()는 호출되어야 함 (after_hours가 아니므로)
        mock_rest.get_cash_and_positions.assert_awaited_once_with(after_hours=False)

        # cash_balance는 정상
        assert result.cash_balance is not None
        assert result.cash_balance.available_cash == 2000000
        assert result.cash_balance.orderable_amount == 1800000

        # positions는 빈 리스트 (fetch_positions=False로 skip)
        assert result.positions == []

        # positions 관련 에러가 없어야 함
        assert not any("position" in err.lower() for err in result.errors)
