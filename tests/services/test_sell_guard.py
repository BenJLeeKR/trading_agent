"""Tests for ``AvailableSellQtyResolver`` — duplicate sell guard logic.

Test matrix
-----------
1.  No position → available=0, blocked
2.  Position with no open sells → available=position, not blocked
3.  Position with open sells → available=position - open_sells
4.  Position with partially filled sells → available=position - partial_remaining
5.  Multiple open sells summed correctly
6.  Multiple partially filled sells summed correctly
7.  Open sells + partially filled combined
8.  Requested qty <= available → not blocked
9.  Requested qty > available → blocked
10. BUY orders ignored in open_sell_qty calculation
11. BUY orders ignored in partially_filled_remaining calculation
12. Different instrument filtered out
13. Unknown symbol (no instrument) → graceful fallback (Decimal 0)
14. SellAvailability dataclass fields
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import (
    BrokerOrderEntity,
    FillEventEntity,
    InstrumentEntity,
    OrderRequestEntity,
    PositionSnapshotEntity,
)
from agent_trading.domain.enums import (
    AssetClass,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.sell_guard import AvailableSellQtyResolver, SellAvailability


# ======================================================================
# Helpers
# ======================================================================


def _make_instrument(
    *,
    instrument_id: UUID | None = None,
    symbol: str = "005930",
) -> InstrumentEntity:
    return InstrumentEntity(
        instrument_id=instrument_id or uuid4(),
        symbol=symbol,
        market_code="KRX",
        asset_class=AssetClass.KR_STOCK.value,
        currency="KRW",
        name="Samsung Electronics",
        is_active=True,
    )


def _make_order(
    *,
    order_request_id: UUID | None = None,
    account_id: UUID,
    instrument_id: UUID,
    side: OrderSide = OrderSide.SELL,
    quantity: str = "10",
    status: OrderStatus = OrderStatus.SUBMITTED,
) -> OrderRequestEntity:
    now = datetime.now(timezone.utc)
    return OrderRequestEntity(
        order_request_id=order_request_id or uuid4(),
        account_id=account_id,
        instrument_id=instrument_id,
        client_order_id=f"CLI-{uuid4().hex[:8]}",
        idempotency_key=f"idem-{uuid4().hex[:8]}",
        correlation_id=f"corr-{uuid4().hex[:8]}",
        side=side,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        requested_price=Decimal("50000"),
        requested_quantity=Decimal(quantity),
        status=status,
        trade_decision_id=None,
        submitted_at=now,
        status_reason_code=None,
        status_reason_message=None,
        created_at=now,
        updated_at=now,
    )


def _make_position_snapshot(
    *,
    account_id: UUID,
    instrument_id: UUID,
    quantity: str = "100",
) -> PositionSnapshotEntity:
    now = datetime.now(timezone.utc)
    return PositionSnapshotEntity(
        position_snapshot_id=uuid4(),
        account_id=account_id,
        instrument_id=instrument_id,
        quantity=Decimal(quantity),
        average_price=Decimal("50000"),
        market_price=Decimal("51000"),
        unrealized_pnl=Decimal("1000"),
        source_of_truth="broker",
        snapshot_at=now,
    )


def _make_broker_order(
    *,
    broker_order_id: UUID | None = None,
    order_request_id: UUID,
    native_order_id: str = "ODNO12345",
) -> BrokerOrderEntity:
    now = datetime.now(timezone.utc)
    return BrokerOrderEntity(
        broker_order_id=broker_order_id or uuid4(),
        order_request_id=order_request_id,
        broker_name="koreainvestment",
        broker_status="confirmed",
        broker_native_order_id=native_order_id,
        last_synced_at=now,
        created_at=now,
    )


def _make_fill_event(
    *,
    broker_order_id: UUID,
    fill_quantity: str = "3",
) -> FillEventEntity:
    now = datetime.now(timezone.utc)
    return FillEventEntity(
        fill_event_id=uuid4(),
        broker_order_id=broker_order_id,
        fill_timestamp=now,
        fill_price=Decimal("50000"),
        fill_quantity=Decimal(fill_quantity),
        source_channel="REST",
        broker_fill_id=f"FILL-{uuid4().hex[:8]}",
    )


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def account_id() -> UUID:
    return uuid4()


@pytest.fixture
def instrument_id() -> UUID:
    return uuid4()


@pytest.fixture
def repos() -> RepositoryContainer:
    return build_in_memory_repositories()


@pytest.fixture
def resolver(repos: RepositoryContainer) -> AvailableSellQtyResolver:
    return AvailableSellQtyResolver(repos=repos)


@pytest.fixture
async def seeded_instrument(
    repos: RepositoryContainer,
    instrument_id: UUID,
) -> InstrumentEntity:
    instr = _make_instrument(instrument_id=instrument_id, symbol="005930")
    await repos.instruments.add(instr)
    return instr


# ======================================================================
# 1. No position → available=0, blocked
# ======================================================================


class TestNoPosition:
    async def test_no_position_returns_zero_blocked(
        self,
        resolver: AvailableSellQtyResolver,
        repos: RepositoryContainer,
        account_id: UUID,
        instrument_id: UUID,
    ) -> None:
        """No position snapshot → available_sell_qty=0, is_blocked=True."""
        # Seed instrument so symbol resolves
        instr = _make_instrument(instrument_id=instrument_id, symbol="005930")
        await repos.instruments.add(instr)

        result = await resolver.resolve(
            account_id=account_id,
            symbol="005930",
            requested_qty=Decimal("10"),
        )

        assert result.available_sell_qty == Decimal("0")
        assert result.current_position_qty == Decimal("0")
        assert result.open_sell_qty == Decimal("0")
        assert result.partially_filled_remaining_qty == Decimal("0")
        assert result.is_blocked is True
        assert result.blocking_reason is not None
        assert "no position" in result.blocking_reason


# ======================================================================
# 2. Position with no open sells → available=position, not blocked
# ======================================================================


class TestPositionNoOpenSells:
    async def test_position_no_open_sells(
        self,
        resolver: AvailableSellQtyResolver,
        repos: RepositoryContainer,
        account_id: UUID,
        instrument_id: UUID,
    ) -> None:
        """Position exists, no open sells → available=position, not blocked."""
        instr = _make_instrument(instrument_id=instrument_id, symbol="005930")
        await repos.instruments.add(instr)

        snapshot = _make_position_snapshot(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity="100",
        )
        await repos.position_snapshots.add(snapshot)

        result = await resolver.resolve(
            account_id=account_id,
            symbol="005930",
            requested_qty=Decimal("10"),
        )

        assert result.available_sell_qty == Decimal("100")
        assert result.current_position_qty == Decimal("100")
        assert result.open_sell_qty == Decimal("0")
        assert result.partially_filled_remaining_qty == Decimal("0")
        assert result.is_blocked is False
        assert result.blocking_reason is None


# ======================================================================
# 3. Position with open sells → available=position - open_sells
# ======================================================================


class TestOpenSells:
    async def test_single_open_sell_subtracted(
        self,
        resolver: AvailableSellQtyResolver,
        repos: RepositoryContainer,
        account_id: UUID,
        instrument_id: UUID,
    ) -> None:
        """Single open SELL order → available = position - open_sell."""
        instr = _make_instrument(instrument_id=instrument_id, symbol="005930")
        await repos.instruments.add(instr)

        snapshot = _make_position_snapshot(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity="100",
        )
        await repos.position_snapshots.add(snapshot)

        order = _make_order(
            account_id=account_id,
            instrument_id=instrument_id,
            side=OrderSide.SELL,
            quantity="30",
            status=OrderStatus.SUBMITTED,
        )
        await repos.orders.add(order)

        result = await resolver.resolve(
            account_id=account_id,
            symbol="005930",
            requested_qty=Decimal("10"),
        )

        assert result.available_sell_qty == Decimal("70")  # 100 - 30
        assert result.open_sell_qty == Decimal("30")
        assert result.is_blocked is False

    async def test_multiple_open_sells_summed(
        self,
        resolver: AvailableSellQtyResolver,
        repos: RepositoryContainer,
        account_id: UUID,
        instrument_id: UUID,
    ) -> None:
        """Multiple open SELL orders → open_sell_qty is sum of all."""
        instr = _make_instrument(instrument_id=instrument_id, symbol="005930")
        await repos.instruments.add(instr)

        snapshot = _make_position_snapshot(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity="100",
        )
        await repos.position_snapshots.add(snapshot)

        for qty in ["20", "30", "10"]:
            order = _make_order(
                account_id=account_id,
                instrument_id=instrument_id,
                side=OrderSide.SELL,
                quantity=qty,
                status=OrderStatus.SUBMITTED,
            )
            await repos.orders.add(order)

        result = await resolver.resolve(
            account_id=account_id,
            symbol="005930",
            requested_qty=Decimal("10"),
        )

        assert result.open_sell_qty == Decimal("60")  # 20 + 30 + 10
        assert result.available_sell_qty == Decimal("40")  # 100 - 60
        assert result.is_blocked is False

    async def test_open_sell_different_statuses(
        self,
        resolver: AvailableSellQtyResolver,
        repos: RepositoryContainer,
        account_id: UUID,
        instrument_id: UUID,
    ) -> None:
        """PENDING_SUBMIT, SUBMITTED, ACKNOWLEDGED all counted."""
        instr = _make_instrument(instrument_id=instrument_id, symbol="005930")
        await repos.instruments.add(instr)

        snapshot = _make_position_snapshot(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity="100",
        )
        await repos.position_snapshots.add(snapshot)

        statuses = [
            OrderStatus.PENDING_SUBMIT,
            OrderStatus.SUBMITTED,
            OrderStatus.ACKNOWLEDGED,
        ]
        for status in statuses:
            order = _make_order(
                account_id=account_id,
                instrument_id=instrument_id,
                side=OrderSide.SELL,
                quantity="10",
                status=status,
            )
            await repos.orders.add(order)

        result = await resolver.resolve(
            account_id=account_id,
            symbol="005930",
            requested_qty=Decimal("10"),
        )

        assert result.open_sell_qty == Decimal("30")  # 10 + 10 + 10
        assert result.available_sell_qty == Decimal("70")  # 100 - 30

    async def test_open_sell_includes_reconcile_required(
        self,
        resolver: AvailableSellQtyResolver,
        repos: RepositoryContainer,
        account_id: UUID,
        instrument_id: UUID,
    ) -> None:
        """RECONCILE_REQUIRED 상태의 SELL 주문도 open_sell_qty에 집계되어야 함."""
        instr = _make_instrument(instrument_id=instrument_id, symbol="005930")
        await repos.instruments.add(instr)

        snapshot = _make_position_snapshot(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity="100",
        )
        await repos.position_snapshots.add(snapshot)

        # RECONCILE_REQUIRED SELL 주문 생성
        order = _make_order(
            account_id=account_id,
            instrument_id=instrument_id,
            side=OrderSide.SELL,
            quantity="25",
            status=OrderStatus.RECONCILE_REQUIRED,
        )
        await repos.orders.add(order)

        result = await resolver.resolve(
            account_id=account_id,
            symbol="005930",
            requested_qty=Decimal("10"),
        )

        assert result.open_sell_qty == Decimal("25")
        assert result.available_sell_qty == Decimal("75")  # 100 - 25

    async def test_open_sell_mixed_statuses_includes_reconcile_required(
        self,
        resolver: AvailableSellQtyResolver,
        repos: RepositoryContainer,
        account_id: UUID,
        instrument_id: UUID,
    ) -> None:
        """PENDING_SUBMIT + SUBMITTED + ACKNOWLEDGED + RECONCILE_REQUIRED 모두 합산."""
        instr = _make_instrument(instrument_id=instrument_id, symbol="005930")
        await repos.instruments.add(instr)

        snapshot = _make_position_snapshot(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity="100",
        )
        await repos.position_snapshots.add(snapshot)

        statuses = [
            OrderStatus.PENDING_SUBMIT,
            OrderStatus.SUBMITTED,
            OrderStatus.ACKNOWLEDGED,
            OrderStatus.RECONCILE_REQUIRED,
        ]
        for status in statuses:
            order = _make_order(
                account_id=account_id,
                instrument_id=instrument_id,
                side=OrderSide.SELL,
                quantity="10",
                status=status,
            )
            await repos.orders.add(order)

        result = await resolver.resolve(
            account_id=account_id,
            symbol="005930",
            requested_qty=Decimal("10"),
        )

        assert result.open_sell_qty == Decimal("40")  # 10 + 10 + 10 + 10
        assert result.available_sell_qty == Decimal("60")  # 100 - 40


# ======================================================================
# 4. Position with partially filled sells
# ======================================================================


class TestPartiallyFilled:
    async def test_partially_filled_remaining_subtracted(
        self,
        resolver: AvailableSellQtyResolver,
        repos: RepositoryContainer,
        account_id: UUID,
        instrument_id: UUID,
    ) -> None:
        """Partially filled SELL → remaining qty subtracted."""
        instr = _make_instrument(instrument_id=instrument_id, symbol="005930")
        await repos.instruments.add(instr)

        snapshot = _make_position_snapshot(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity="100",
        )
        await repos.position_snapshots.add(snapshot)

        order = _make_order(
            account_id=account_id,
            instrument_id=instrument_id,
            side=OrderSide.SELL,
            quantity="20",
            status=OrderStatus.PARTIALLY_FILLED,
        )
        await repos.orders.add(order)

        bo = _make_broker_order(order_request_id=order.order_request_id)
        await repos.broker_orders.add(bo)

        fill = _make_fill_event(broker_order_id=bo.broker_order_id, fill_quantity="5")
        await repos.fill_events.add(fill)

        result = await resolver.resolve(
            account_id=account_id,
            symbol="005930",
            requested_qty=Decimal("10"),
        )

        # remaining = 20 - 5 = 15
        assert result.partially_filled_remaining_qty == Decimal("15")
        assert result.available_sell_qty == Decimal("85")  # 100 - 15
        assert result.is_blocked is False

    async def test_multiple_partially_filled_summed(
        self,
        resolver: AvailableSellQtyResolver,
        repos: RepositoryContainer,
        account_id: UUID,
        instrument_id: UUID,
    ) -> None:
        """Multiple partially filled SELL → remaining summed."""
        instr = _make_instrument(instrument_id=instrument_id, symbol="005930")
        await repos.instruments.add(instr)

        snapshot = _make_position_snapshot(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity="100",
        )
        await repos.position_snapshots.add(snapshot)

        for qty, filled in [("20", "5"), ("30", "10")]:
            order = _make_order(
                account_id=account_id,
                instrument_id=instrument_id,
                side=OrderSide.SELL,
                quantity=qty,
                status=OrderStatus.PARTIALLY_FILLED,
            )
            await repos.orders.add(order)

            bo = _make_broker_order(order_request_id=order.order_request_id)
            await repos.broker_orders.add(bo)

            fill = _make_fill_event(
                broker_order_id=bo.broker_order_id,
                fill_quantity=filled,
            )
            await repos.fill_events.add(fill)

        result = await resolver.resolve(
            account_id=account_id,
            symbol="005930",
            requested_qty=Decimal("10"),
        )

        # remaining = (20-5) + (30-10) = 15 + 20 = 35
        assert result.partially_filled_remaining_qty == Decimal("35")
        assert result.available_sell_qty == Decimal("65")  # 100 - 35


# ======================================================================
# 5. Open sells + partially filled combined
# ======================================================================


class TestCombined:
    async def test_open_and_partial_combined(
        self,
        resolver: AvailableSellQtyResolver,
        repos: RepositoryContainer,
        account_id: UUID,
        instrument_id: UUID,
    ) -> None:
        """Both open sells and partially filled → both subtracted."""
        instr = _make_instrument(instrument_id=instrument_id, symbol="005930")
        await repos.instruments.add(instr)

        snapshot = _make_position_snapshot(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity="100",
        )
        await repos.position_snapshots.add(snapshot)

        # Open sell
        open_order = _make_order(
            account_id=account_id,
            instrument_id=instrument_id,
            side=OrderSide.SELL,
            quantity="20",
            status=OrderStatus.SUBMITTED,
        )
        await repos.orders.add(open_order)

        # Partially filled
        partial_order = _make_order(
            account_id=account_id,
            instrument_id=instrument_id,
            side=OrderSide.SELL,
            quantity="30",
            status=OrderStatus.PARTIALLY_FILLED,
        )
        await repos.orders.add(partial_order)

        bo = _make_broker_order(order_request_id=partial_order.order_request_id)
        await repos.broker_orders.add(bo)

        fill = _make_fill_event(broker_order_id=bo.broker_order_id, fill_quantity="10")
        await repos.fill_events.add(fill)

        result = await resolver.resolve(
            account_id=account_id,
            symbol="005930",
            requested_qty=Decimal("10"),
        )

        # available = 100 - 20 - (30-10) = 100 - 20 - 20 = 60
        assert result.open_sell_qty == Decimal("20")
        assert result.partially_filled_remaining_qty == Decimal("20")
        assert result.available_sell_qty == Decimal("60")
        assert result.is_blocked is False


# ======================================================================
# 6. Requested qty > available → blocked
# ======================================================================


class TestBlocked:
    async def test_requested_exceeds_available_blocked(
        self,
        resolver: AvailableSellQtyResolver,
        repos: RepositoryContainer,
        account_id: UUID,
        instrument_id: UUID,
    ) -> None:
        """Requested qty > available → is_blocked=True."""
        instr = _make_instrument(instrument_id=instrument_id, symbol="005930")
        await repos.instruments.add(instr)

        snapshot = _make_position_snapshot(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity="50",
        )
        await repos.position_snapshots.add(snapshot)

        order = _make_order(
            account_id=account_id,
            instrument_id=instrument_id,
            side=OrderSide.SELL,
            quantity="40",
            status=OrderStatus.SUBMITTED,
        )
        await repos.orders.add(order)

        # available = 50 - 40 = 10
        result = await resolver.resolve(
            account_id=account_id,
            symbol="005930",
            requested_qty=Decimal("20"),  # > 10
        )

        assert result.available_sell_qty == Decimal("10")
        assert result.is_blocked is True
        assert result.blocking_reason is not None
        assert "blocked" in result.blocking_reason

    async def test_requested_equals_available_not_blocked(
        self,
        resolver: AvailableSellQtyResolver,
        repos: RepositoryContainer,
        account_id: UUID,
        instrument_id: UUID,
    ) -> None:
        """Requested qty == available → not blocked."""
        instr = _make_instrument(instrument_id=instrument_id, symbol="005930")
        await repos.instruments.add(instr)

        snapshot = _make_position_snapshot(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity="50",
        )
        await repos.position_snapshots.add(snapshot)

        order = _make_order(
            account_id=account_id,
            instrument_id=instrument_id,
            side=OrderSide.SELL,
            quantity="30",
            status=OrderStatus.SUBMITTED,
        )
        await repos.orders.add(order)

        # available = 50 - 30 = 20
        result = await resolver.resolve(
            account_id=account_id,
            symbol="005930",
            requested_qty=Decimal("20"),  # == 20
        )

        assert result.available_sell_qty == Decimal("20")
        assert result.is_blocked is False
        assert result.blocking_reason is None


# ======================================================================
# 7. BUY orders ignored
# ======================================================================


class TestBuyOrdersIgnored:
    async def test_buy_orders_not_counted_as_open_sell(
        self,
        resolver: AvailableSellQtyResolver,
        repos: RepositoryContainer,
        account_id: UUID,
        instrument_id: UUID,
    ) -> None:
        """BUY orders should not be counted in open_sell_qty."""
        instr = _make_instrument(instrument_id=instrument_id, symbol="005930")
        await repos.instruments.add(instr)

        snapshot = _make_position_snapshot(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity="100",
        )
        await repos.position_snapshots.add(snapshot)

        # BUY order — should be ignored
        buy_order = _make_order(
            account_id=account_id,
            instrument_id=instrument_id,
            side=OrderSide.BUY,
            quantity="50",
            status=OrderStatus.SUBMITTED,
        )
        await repos.orders.add(buy_order)

        result = await resolver.resolve(
            account_id=account_id,
            symbol="005930",
            requested_qty=Decimal("10"),
        )

        assert result.open_sell_qty == Decimal("0")
        assert result.available_sell_qty == Decimal("100")

    async def test_buy_orders_not_counted_as_partial(
        self,
        resolver: AvailableSellQtyResolver,
        repos: RepositoryContainer,
        account_id: UUID,
        instrument_id: UUID,
    ) -> None:
        """BUY PARTIALLY_FILLED orders should not be counted."""
        instr = _make_instrument(instrument_id=instrument_id, symbol="005930")
        await repos.instruments.add(instr)

        snapshot = _make_position_snapshot(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity="100",
        )
        await repos.position_snapshots.add(snapshot)

        buy_order = _make_order(
            account_id=account_id,
            instrument_id=instrument_id,
            side=OrderSide.BUY,
            quantity="50",
            status=OrderStatus.PARTIALLY_FILLED,
        )
        await repos.orders.add(buy_order)

        bo = _make_broker_order(order_request_id=buy_order.order_request_id)
        await repos.broker_orders.add(bo)

        fill = _make_fill_event(broker_order_id=bo.broker_order_id, fill_quantity="20")
        await repos.fill_events.add(fill)

        result = await resolver.resolve(
            account_id=account_id,
            symbol="005930",
            requested_qty=Decimal("10"),
        )

        assert result.partially_filled_remaining_qty == Decimal("0")
        assert result.available_sell_qty == Decimal("100")


# ======================================================================
# 8. Different instrument filtered out
# ======================================================================


class TestDifferentInstrument:
    async def test_different_instrument_not_counted(
        self,
        resolver: AvailableSellQtyResolver,
        repos: RepositoryContainer,
        account_id: UUID,
        instrument_id: UUID,
    ) -> None:
        """Orders for different instruments should be filtered out."""
        instr = _make_instrument(instrument_id=instrument_id, symbol="005930")
        await repos.instruments.add(instr)

        snapshot = _make_position_snapshot(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity="100",
        )
        await repos.position_snapshots.add(snapshot)

        # SELL order for a different instrument
        other_instr_id = uuid4()
        other_instr = _make_instrument(instrument_id=other_instr_id, symbol="000660")
        await repos.instruments.add(other_instr)

        other_order = _make_order(
            account_id=account_id,
            instrument_id=other_instr_id,  # SK Hynix, not Samsung
            side=OrderSide.SELL,
            quantity="50",
            status=OrderStatus.SUBMITTED,
        )
        await repos.orders.add(other_order)

        result = await resolver.resolve(
            account_id=account_id,
            symbol="005930",
            requested_qty=Decimal("10"),
        )

        assert result.open_sell_qty == Decimal("0")
        assert result.available_sell_qty == Decimal("100")


# ======================================================================
# 9. Unknown symbol (no instrument) → graceful fallback
# ======================================================================


class TestUnknownSymbol:
    async def test_unknown_symbol_returns_zero_blocked(
        self,
        resolver: AvailableSellQtyResolver,
        account_id: UUID,
    ) -> None:
        """Unknown symbol (no instrument) → available=0, blocked."""
        result = await resolver.resolve(
            account_id=account_id,
            symbol="UNKNOWN",
            requested_qty=Decimal("10"),
        )

        assert result.available_sell_qty == Decimal("0")
        assert result.current_position_qty == Decimal("0")
        assert result.open_sell_qty == Decimal("0")
        assert result.partially_filled_remaining_qty == Decimal("0")
        assert result.is_blocked is True


# ======================================================================
# 10. SellAvailability dataclass fields
# ======================================================================


class TestSellAvailabilityDataclass:
    def test_fields(self) -> None:
        """SellAvailability dataclass fields are correctly typed."""
        sa = SellAvailability(
            available_sell_qty=Decimal("50"),
            current_position_qty=Decimal("100"),
            open_sell_qty=Decimal("30"),
            partially_filled_remaining_qty=Decimal("20"),
            is_blocked=False,
            blocking_reason=None,
        )

        assert sa.available_sell_qty == Decimal("50")
        assert sa.current_position_qty == Decimal("100")
        assert sa.open_sell_qty == Decimal("30")
        assert sa.partially_filled_remaining_qty == Decimal("20")
        assert sa.is_blocked is False
        assert sa.blocking_reason is None

    def test_blocked_with_reason(self) -> None:
        """Blocked SellAvailability has blocking_reason set."""
        sa = SellAvailability(
            available_sell_qty=Decimal("0"),
            current_position_qty=Decimal("0"),
            open_sell_qty=Decimal("0"),
            partially_filled_remaining_qty=Decimal("0"),
            is_blocked=True,
            blocking_reason="Sell guard blocked: no position",
        )

        assert sa.is_blocked is True
        assert sa.blocking_reason == "Sell guard blocked: no position"

    def test_frozen(self) -> None:
        """SellAvailability is frozen (immutable)."""
        sa = SellAvailability(
            available_sell_qty=Decimal("10"),
            current_position_qty=Decimal("100"),
            open_sell_qty=Decimal("90"),
            partially_filled_remaining_qty=Decimal("0"),
            is_blocked=False,
            blocking_reason=None,
        )
        with pytest.raises(AttributeError):
            sa.available_sell_qty = Decimal("20")  # type: ignore[misc]


# ======================================================================
# Stale PENDING_SUBMIT 관련 테스트
# ======================================================================


async def test_sell_guard_stale_pending_submit_excluded() -> None:
    """Stale PENDING_SUBMIT sell (30분↑ + broker_native_order_id=NULL)은
    open_sell_qty에 포함되지 않아야 한다."""
    repos = build_in_memory_repositories()
    resolver = AvailableSellQtyResolver(repos=repos)

    account_id = uuid4()
    instrument = _make_instrument()
    await repos.instruments.add(instrument)

    # 31분 전 생성된 stale PENDING_SUBMIT SELL 주문
    stale_created_at = datetime.now(timezone.utc) - timedelta(minutes=31)
    stale_order = _make_order(
        account_id=account_id,
        instrument_id=instrument.instrument_id,
        side=OrderSide.SELL,
        quantity="10",
        status=OrderStatus.PENDING_SUBMIT,
    )
    # created_at을 31분 전으로 override (frozen dataclass)
    stale_order = OrderRequestEntity(
        order_request_id=stale_order.order_request_id,
        account_id=stale_order.account_id,
        instrument_id=stale_order.instrument_id,
        client_order_id=stale_order.client_order_id,
        idempotency_key=stale_order.idempotency_key,
        correlation_id=stale_order.correlation_id,
        side=stale_order.side,
        order_type=stale_order.order_type,
        requested_quantity=stale_order.requested_quantity,
        status=stale_order.status,
        trade_decision_id=stale_order.trade_decision_id,
        decision_context_id=stale_order.decision_context_id,
        requested_price=stale_order.requested_price,
        time_in_force=stale_order.time_in_force,
        status_reason_code=stale_order.status_reason_code,
        status_reason_message=stale_order.status_reason_message,
        submitted_at=stale_order.submitted_at,
        created_at=stale_created_at,  # 31분 전
        updated_at=stale_created_at,
        version=stale_order.version,
        order_intent_id=stale_order.order_intent_id,
    )
    await repos.orders.add(stale_order)

    # broker_native_order_id가 없는 BrokerOrderEntity 추가 (orphan)
    bo = _make_broker_order(
        order_request_id=stale_order.order_request_id,
        native_order_id=None,
    )
    await repos.broker_orders.add(bo)

    # Position 10주
    snap = _make_position_snapshot(
        account_id=account_id,
        instrument_id=instrument.instrument_id,
        quantity="10",
    )
    await repos.position_snapshots.add(snap)

    sa = await resolver.resolve(
        account_id=account_id,
        symbol=instrument.symbol,
        requested_qty=Decimal("1"),
    )

    # stale PENDING_SUBMIT은 제외 → open_sell_qty=0, available=10
    assert sa.open_sell_qty == Decimal("0"), (
        f"Expected open_sell_qty=0 for stale PENDING_SUBMIT, got {sa.open_sell_qty}"
    )
    assert sa.available_sell_qty == Decimal("10"), (
        f"Expected available_sell_qty=10, got {sa.available_sell_qty}"
    )
    assert sa.is_blocked is False, "Stale PENDING_SUBMIT should not block sell"


async def test_sell_guard_fresh_pending_submit_included() -> None:
    """Fresh PENDING_SUBMIT sell (30분 미만)은 계속 open_sell_qty에 포함되어
    매도를 차단해야 한다."""
    repos = build_in_memory_repositories()
    resolver = AvailableSellQtyResolver(repos=repos)

    account_id = uuid4()
    instrument = _make_instrument()
    await repos.instruments.add(instrument)

    # 5분 전 생성된 fresh PENDING_SUBMIT SELL 주문
    fresh_created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    fresh_order = _make_order(
        account_id=account_id,
        instrument_id=instrument.instrument_id,
        side=OrderSide.SELL,
        quantity="10",
        status=OrderStatus.PENDING_SUBMIT,
    )
    fresh_order = OrderRequestEntity(
        order_request_id=fresh_order.order_request_id,
        account_id=fresh_order.account_id,
        instrument_id=fresh_order.instrument_id,
        client_order_id=fresh_order.client_order_id,
        idempotency_key=fresh_order.idempotency_key,
        correlation_id=fresh_order.correlation_id,
        side=fresh_order.side,
        order_type=fresh_order.order_type,
        requested_quantity=fresh_order.requested_quantity,
        status=fresh_order.status,
        trade_decision_id=fresh_order.trade_decision_id,
        decision_context_id=fresh_order.decision_context_id,
        requested_price=fresh_order.requested_price,
        time_in_force=fresh_order.time_in_force,
        status_reason_code=fresh_order.status_reason_code,
        status_reason_message=fresh_order.status_reason_message,
        submitted_at=fresh_order.submitted_at,
        created_at=fresh_created_at,  # 5분 전
        updated_at=fresh_created_at,
        version=fresh_order.version,
        order_intent_id=fresh_order.order_intent_id,
    )
    await repos.orders.add(fresh_order)

    # broker_native_order_id가 없는 BrokerOrderEntity
    bo = _make_broker_order(
        order_request_id=fresh_order.order_request_id,
        native_order_id=None,
    )
    await repos.broker_orders.add(bo)

    # Position 10주
    snap = _make_position_snapshot(
        account_id=account_id,
        instrument_id=instrument.instrument_id,
        quantity="10",
    )
    await repos.position_snapshots.add(snap)

    sa = await resolver.resolve(
        account_id=account_id,
        symbol=instrument.symbol,
        requested_qty=Decimal("1"),
    )

    # fresh PENDING_SUBMIT은 포함 → open_sell_qty=10, available=0
    assert sa.open_sell_qty == Decimal("10"), (
        f"Expected open_sell_qty=10 for fresh PENDING_SUBMIT, got {sa.open_sell_qty}"
    )
    assert sa.available_sell_qty == Decimal("0"), (
        f"Expected available_sell_qty=0, got {sa.available_sell_qty}"
    )
    assert sa.is_blocked is True, "Fresh PENDING_SUBMIT should block sell"


async def test_sell_guard_stale_pending_submit_buy_unaffected() -> None:
    """BUY PENDING_SUBMIT 주문은 stale/exclusion과 무관하게 기존 동작 유지."""
    repos = build_in_memory_repositories()
    resolver = AvailableSellQtyResolver(repos=repos)

    account_id = uuid4()
    instrument = _make_instrument()
    await repos.instruments.add(instrument)

    # 31분 전 생성된 stale PENDING_SUBMIT BUY 주문
    stale_created_at = datetime.now(timezone.utc) - timedelta(minutes=31)
    buy_order = _make_order(
        account_id=account_id,
        instrument_id=instrument.instrument_id,
        side=OrderSide.BUY,
        quantity="10",
        status=OrderStatus.PENDING_SUBMIT,
    )
    buy_order = OrderRequestEntity(
        order_request_id=buy_order.order_request_id,
        account_id=buy_order.account_id,
        instrument_id=buy_order.instrument_id,
        client_order_id=buy_order.client_order_id,
        idempotency_key=buy_order.idempotency_key,
        correlation_id=buy_order.correlation_id,
        side=buy_order.side,
        order_type=buy_order.order_type,
        requested_quantity=buy_order.requested_quantity,
        status=buy_order.status,
        trade_decision_id=buy_order.trade_decision_id,
        decision_context_id=buy_order.decision_context_id,
        requested_price=buy_order.requested_price,
        time_in_force=buy_order.time_in_force,
        status_reason_code=buy_order.status_reason_code,
        status_reason_message=buy_order.status_reason_message,
        submitted_at=buy_order.submitted_at,
        created_at=stale_created_at,
        updated_at=stale_created_at,
        version=buy_order.version,
        order_intent_id=buy_order.order_intent_id,
    )
    await repos.orders.add(buy_order)

    bo = _make_broker_order(
        order_request_id=buy_order.order_request_id,
        native_order_id=None,
    )
    await repos.broker_orders.add(bo)

    # Position 10주
    snap = _make_position_snapshot(
        account_id=account_id,
        instrument_id=instrument.instrument_id,
        quantity="10",
    )
    await repos.position_snapshots.add(snap)

    sa = await resolver.resolve(
        account_id=account_id,
        symbol=instrument.symbol,
        requested_qty=Decimal("1"),
    )

    # BUY 주문은 open_sell_qty에 영향을 주지 않음
    assert sa.open_sell_qty == Decimal("0"), (
        f"Expected open_sell_qty=0 for BUY order, got {sa.open_sell_qty}"
    )
    assert sa.available_sell_qty == Decimal("10"), (
        f"Expected available_sell_qty=10, got {sa.available_sell_qty}"
    )
    assert sa.is_blocked is False, "BUY PENDING_SUBMIT should not affect sell guard"


async def test_sell_guard_stale_pending_submit_with_broker_native_id_included() -> None:
    """Stale PENDING_SUBMIT이지만 broker_native_order_id가 있으면
    broker에 도달한 것으로 간주하여 open_sell_qty에 포함."""
    repos = build_in_memory_repositories()
    resolver = AvailableSellQtyResolver(repos=repos)

    account_id = uuid4()
    instrument = _make_instrument()
    await repos.instruments.add(instrument)

    # 31분 전 생성되었지만 broker_native_order_id가 있는 PENDING_SUBMIT
    stale_created_at = datetime.now(timezone.utc) - timedelta(minutes=31)
    order = _make_order(
        account_id=account_id,
        instrument_id=instrument.instrument_id,
        side=OrderSide.SELL,
        quantity="10",
        status=OrderStatus.PENDING_SUBMIT,
    )
    order = OrderRequestEntity(
        order_request_id=order.order_request_id,
        account_id=order.account_id,
        instrument_id=order.instrument_id,
        client_order_id=order.client_order_id,
        idempotency_key=order.idempotency_key,
        correlation_id=order.correlation_id,
        side=order.side,
        order_type=order.order_type,
        requested_quantity=order.requested_quantity,
        status=order.status,
        trade_decision_id=order.trade_decision_id,
        decision_context_id=order.decision_context_id,
        requested_price=order.requested_price,
        time_in_force=order.time_in_force,
        status_reason_code=order.status_reason_code,
        status_reason_message=order.status_reason_message,
        submitted_at=order.submitted_at,
        created_at=stale_created_at,
        updated_at=stale_created_at,
        version=order.version,
        order_intent_id=order.order_intent_id,
    )
    await repos.orders.add(order)

    # broker_native_order_id가 있는 BrokerOrderEntity
    bo = _make_broker_order(
        order_request_id=order.order_request_id,
        native_order_id="BROKER-12345",
    )
    await repos.broker_orders.add(bo)

    # Position 10주
    snap = _make_position_snapshot(
        account_id=account_id,
        instrument_id=instrument.instrument_id,
        quantity="10",
    )
    await repos.position_snapshots.add(snap)

    sa = await resolver.resolve(
        account_id=account_id,
        symbol=instrument.symbol,
        requested_qty=Decimal("1"),
    )

    # broker_native_order_id가 있으므로 open_sell_qty에 포함
    assert sa.open_sell_qty == Decimal("10"), (
        f"Expected open_sell_qty=10 (has broker_native_order_id), got {sa.open_sell_qty}"
    )
    assert sa.available_sell_qty == Decimal("0"), (
        f"Expected available_sell_qty=0, got {sa.available_sell_qty}"
    )
    assert sa.is_blocked is True, (
        "Stale PENDING_SUBMIT with broker_native_order_id should block sell"
    )


async def test_sell_guard_prior_day_submitted_sell_excluded() -> None:
    """전일 DAY SUBMITTED SELL 잔량은 다음 거래일 sell guard에서 제외한다."""
    repos = build_in_memory_repositories()
    resolver = AvailableSellQtyResolver(repos=repos)

    account_id = uuid4()
    instrument = _make_instrument()
    await repos.instruments.add(instrument)

    old_time = datetime.now(timezone.utc) - timedelta(days=1, minutes=5)
    order = _make_order(
        account_id=account_id,
        instrument_id=instrument.instrument_id,
        side=OrderSide.SELL,
        quantity="30",
        status=OrderStatus.SUBMITTED,
    )
    order = OrderRequestEntity(
        order_request_id=order.order_request_id,
        account_id=order.account_id,
        instrument_id=order.instrument_id,
        client_order_id=order.client_order_id,
        idempotency_key=order.idempotency_key,
        correlation_id=order.correlation_id,
        side=order.side,
        order_type=order.order_type,
        requested_quantity=order.requested_quantity,
        status=order.status,
        trade_decision_id=order.trade_decision_id,
        decision_context_id=order.decision_context_id,
        requested_price=order.requested_price,
        time_in_force=TimeInForce.DAY,
        status_reason_code=order.status_reason_code,
        status_reason_message=order.status_reason_message,
        submitted_at=old_time,
        created_at=old_time,
        updated_at=old_time,
        version=order.version,
        order_intent_id=order.order_intent_id,
    )
    await repos.orders.add(order)

    snap = _make_position_snapshot(
        account_id=account_id,
        instrument_id=instrument.instrument_id,
        quantity="50",
    )
    await repos.position_snapshots.add(snap)

    sa = await resolver.resolve(
        account_id=account_id,
        symbol=instrument.symbol,
        requested_qty=Decimal("20"),
    )

    assert sa.open_sell_qty == Decimal("0")
    assert sa.available_sell_qty == Decimal("50")
    assert sa.is_blocked is False


async def test_sell_guard_prior_day_partial_remaining_excluded() -> None:
    """전일 DAY PARTIALLY_FILLED 잔량은 다음 거래일 sell guard에서 제외한다."""
    repos = build_in_memory_repositories()
    resolver = AvailableSellQtyResolver(repos=repos)

    account_id = uuid4()
    instrument = _make_instrument()
    await repos.instruments.add(instrument)

    old_time = datetime.now(timezone.utc) - timedelta(days=1, minutes=5)
    order = _make_order(
        account_id=account_id,
        instrument_id=instrument.instrument_id,
        side=OrderSide.SELL,
        quantity="40",
        status=OrderStatus.PARTIALLY_FILLED,
    )
    order = OrderRequestEntity(
        order_request_id=order.order_request_id,
        account_id=order.account_id,
        instrument_id=order.instrument_id,
        client_order_id=order.client_order_id,
        idempotency_key=order.idempotency_key,
        correlation_id=order.correlation_id,
        side=order.side,
        order_type=order.order_type,
        requested_quantity=order.requested_quantity,
        status=order.status,
        trade_decision_id=order.trade_decision_id,
        decision_context_id=order.decision_context_id,
        requested_price=order.requested_price,
        time_in_force=TimeInForce.DAY,
        status_reason_code=order.status_reason_code,
        status_reason_message=order.status_reason_message,
        submitted_at=old_time,
        created_at=old_time,
        updated_at=old_time,
        version=order.version,
        order_intent_id=order.order_intent_id,
    )
    await repos.orders.add(order)

    bo = _make_broker_order(order_request_id=order.order_request_id)
    await repos.broker_orders.add(bo)
    fill = _make_fill_event(
        broker_order_id=bo.broker_order_id,
        fill_quantity="5",
    )
    await repos.fill_events.add(fill)

    snap = _make_position_snapshot(
        account_id=account_id,
        instrument_id=instrument.instrument_id,
        quantity="50",
    )
    await repos.position_snapshots.add(snap)

    sa = await resolver.resolve(
        account_id=account_id,
        symbol=instrument.symbol,
        requested_qty=Decimal("20"),
    )

    assert sa.partially_filled_remaining_qty == Decimal("0")
    assert sa.available_sell_qty == Decimal("50")
    assert sa.is_blocked is False
