"""Tests for ``RealizedPnlLedgerService`` — 계산 엔진을 실제 저장 흐름에 연결.

계산 로직 자체(이동평균, 실현 손익 산식)는 ``realized_pnl_engine.py``에서
이미 테스트됐다. 여기서는 orchestration 책임만 검증한다: fill → NormalizedFill
정규화, 현재 state 조회, 엔진 호출, 결과 저장, idempotency, out-of-order/실패
시 recompute_queue·recompute_required 처리, computation run 카운트.

Test matrix
-----------
1.  BUY fill 반영 — state upsert, event 없음, run.status=completed/fills_applied=1
2.  SELL fill 반영 — state upsert + realized event append + daily aggregate 신규 생성
3.  같은 날 두 번째 SELL — daily aggregate 누계 합산(신규 생성이 아니라 합산)
4.  fee/tax 둘 다 None → assumed_zero 정규화
5.  fee/tax 값 존재 → reported 정규화
6.  동일 SELL fill_event_id 재적용 → skipped_duplicate(기존 event 반환, 재계산 없음)
7.  동일 BUY fill_event_id(직전 적용분과 일치) 재적용 → skipped_duplicate
8.  계산 엔진 예외(보유수량 초과 SELL) → recompute_queue 기록 + recompute_required=True
9.  timestamp 역행(out-of-order) → 엔진 호출 없이 recompute_queue 기록 + recompute_required=True
10. broker_order/order_request를 찾을 수 없음 → UnresolvedFillLineageError, run.status=failed
11. computation run 상태/카운트 — 성공/중복/실패 각각의 run 필드 확인
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import (
    BrokerOrderEntity,
    FillEventEntity,
    OrderRequestEntity,
)
from agent_trading.domain.enums import (
    OrderSide,
    OrderStatus,
    OrderType,
    RealizedPnlFeeTaxSource,
    TimeInForce,
)
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.realized_pnl_engine import InsufficientPositionQuantityError
from agent_trading.services.realized_pnl_ledger_service import (
    RealizedPnlLedgerService,
    UnresolvedFillLineageError,
)

_BASE_TS = datetime(2026, 5, 1, 9, 0, 0, tzinfo=timezone.utc)


# ======================================================================
# Helpers
# ======================================================================


def _make_order_request(
    *, account_id: UUID, instrument_id: UUID, side: OrderSide = OrderSide.BUY
) -> OrderRequestEntity:
    return OrderRequestEntity(
        order_request_id=uuid4(),
        account_id=account_id,
        instrument_id=instrument_id,
        client_order_id=f"CLI-{uuid4().hex[:8]}",
        idempotency_key=f"idem-{uuid4().hex[:8]}",
        correlation_id=f"corr-{uuid4().hex[:8]}",
        side=side,
        order_type=OrderType.MARKET,
        requested_quantity=Decimal("10"),
        status=OrderStatus.FILLED,
        time_in_force=TimeInForce.DAY,
    )


def _make_broker_order(*, order_request_id: UUID) -> BrokerOrderEntity:
    return BrokerOrderEntity(
        broker_order_id=uuid4(),
        order_request_id=order_request_id,
        broker_name="koreainvestment",
        broker_status="confirmed",
    )


def _make_fill_event(
    *,
    broker_order_id: UUID,
    quantity: Decimal = Decimal("10"),
    price: Decimal = Decimal("100"),
    fill_fee: Decimal | None = None,
    fill_tax: Decimal | None = None,
    fill_timestamp: datetime = _BASE_TS,
) -> FillEventEntity:
    return FillEventEntity(
        fill_event_id=uuid4(),
        broker_order_id=broker_order_id,
        fill_timestamp=fill_timestamp,
        fill_price=price,
        fill_quantity=quantity,
        source_channel="rest_poll",
        fill_fee=fill_fee,
        fill_tax=fill_tax,
    )


async def _seed_order(
    repos: RepositoryContainer,
    *,
    account_id: UUID,
    instrument_id: UUID,
    side: OrderSide,
) -> BrokerOrderEntity:
    order_request = _make_order_request(account_id=account_id, instrument_id=instrument_id, side=side)
    await repos.orders.add(order_request)
    broker_order = _make_broker_order(order_request_id=order_request.order_request_id)
    await repos.broker_orders.add(broker_order)
    return broker_order


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
def service(repos: RepositoryContainer) -> RealizedPnlLedgerService:
    return RealizedPnlLedgerService(repos)


# ======================================================================
# 1. BUY fill 반영
# ======================================================================


@pytest.mark.asyncio
async def test_buy_fill_upserts_state_without_event(service, repos, account_id, instrument_id):
    broker_order = await _seed_order(repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY)
    fill = _make_fill_event(broker_order_id=broker_order.broker_order_id, quantity=Decimal("10"), price=Decimal("100"))

    result = await service.apply_fill(fill)

    assert result.status == "applied"
    assert result.realized_pnl_event is None
    assert result.state.quantity == Decimal("10")
    assert result.state.average_cost == Decimal("100")
    assert result.state.last_applied_fill_event_id == fill.fill_event_id
    assert result.computation_run.status == "completed"
    assert result.computation_run.fills_applied == 1

    stored = await repos.position_cost_basis_states.get(account_id, instrument_id)
    assert stored.quantity == Decimal("10")


# ======================================================================
# 2 & 3. SELL fill 반영 — event append + daily aggregate
# ======================================================================


@pytest.mark.asyncio
async def test_sell_fill_appends_event_and_creates_daily_aggregate(service, repos, account_id, instrument_id):
    buy_order = await _seed_order(repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY)
    await service.apply_fill(
        _make_fill_event(broker_order_id=buy_order.broker_order_id, quantity=Decimal("10"), price=Decimal("100"))
    )

    sell_order = await _seed_order(repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.SELL)
    sell_fill = _make_fill_event(
        broker_order_id=sell_order.broker_order_id,
        quantity=Decimal("4"),
        price=Decimal("150"),
        fill_timestamp=_BASE_TS + timedelta(seconds=1),
    )

    result = await service.apply_fill(sell_fill)

    assert result.status == "applied"
    assert result.realized_pnl_event is not None
    assert result.realized_pnl_event.realized_pnl_gross == Decimal("200")  # (150-100)*4
    assert result.state.quantity == Decimal("6")

    stored_event = await repos.realized_pnl_events.get_by_fill_event_id(sell_fill.fill_event_id)
    assert stored_event is not None

    aggregates = await repos.realized_pnl_daily_aggregates.list_by_account_and_instrument(
        account_id, instrument_id
    )
    assert len(aggregates) == 1
    assert aggregates[0].realized_pnl_net_sum == Decimal("200")
    assert aggregates[0].sell_event_count == 1
    # UI용 파생 합계 캐시(entities.py RealizedPnlDailyAggregateEntity 참고) —
    # buy_amount_sum = sell_quantity * avg_cost_basis_before = 4 * 100 = 400
    # sell_amount_sum = sell_quantity * sell_price = 4 * 150 = 600
    assert aggregates[0].buy_amount_sum == Decimal("400")
    assert aggregates[0].sell_amount_sum == Decimal("600")
    assert aggregates[0].fee_tax_sum == Decimal("0")


@pytest.mark.asyncio
async def test_second_sell_same_day_accumulates_daily_aggregate(service, repos, account_id, instrument_id):
    buy_order = await _seed_order(repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY)
    await service.apply_fill(
        _make_fill_event(broker_order_id=buy_order.broker_order_id, quantity=Decimal("20"), price=Decimal("100"))
    )

    sell_order = await _seed_order(repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.SELL)
    await service.apply_fill(
        _make_fill_event(
            broker_order_id=sell_order.broker_order_id,
            quantity=Decimal("5"),
            price=Decimal("150"),
            fill_timestamp=_BASE_TS + timedelta(seconds=1),
        )
    )
    await service.apply_fill(
        _make_fill_event(
            broker_order_id=sell_order.broker_order_id,
            quantity=Decimal("5"),
            price=Decimal("120"),
            fill_timestamp=_BASE_TS + timedelta(seconds=2),
        )
    )

    aggregates = await repos.realized_pnl_daily_aggregates.list_by_account_and_instrument(
        account_id, instrument_id
    )
    assert len(aggregates) == 1
    # (150-100)*5 + (120-100)*5 = 250 + 100 = 350
    assert aggregates[0].realized_pnl_net_sum == Decimal("350")
    assert aggregates[0].sell_event_count == 2
    # 두 매도 모두 avg_cost_basis_before=100(매도는 average_cost를 바꾸지 않는다).
    # buy_amount_sum = 5*100 + 5*100 = 1000, sell_amount_sum = 5*150 + 5*120 = 1350
    assert aggregates[0].buy_amount_sum == Decimal("1000")
    assert aggregates[0].sell_amount_sum == Decimal("1350")
    assert aggregates[0].fee_tax_sum == Decimal("0")


@pytest.mark.asyncio
async def test_daily_aggregate_accumulates_fee_tax_sum(service, repos, account_id, instrument_id):
    """``fee_tax_sum``이 SELL마다 ``fee + tax``를 누적하는지 확인한다."""
    buy_order = await _seed_order(repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY)
    await service.apply_fill(
        _make_fill_event(broker_order_id=buy_order.broker_order_id, quantity=Decimal("10"), price=Decimal("100"))
    )

    sell_order = await _seed_order(repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.SELL)
    await service.apply_fill(
        _make_fill_event(
            broker_order_id=sell_order.broker_order_id,
            quantity=Decimal("4"),
            price=Decimal("150"),
            fill_fee=Decimal("3"),
            fill_tax=Decimal("2"),
            fill_timestamp=_BASE_TS + timedelta(seconds=1),
        )
    )
    await service.apply_fill(
        _make_fill_event(
            broker_order_id=sell_order.broker_order_id,
            quantity=Decimal("6"),
            price=Decimal("120"),
            fill_fee=Decimal("5"),
            fill_tax=Decimal("1"),
            fill_timestamp=_BASE_TS + timedelta(seconds=2),
        )
    )

    aggregates = await repos.realized_pnl_daily_aggregates.list_by_account_and_instrument(
        account_id, instrument_id
    )
    assert len(aggregates) == 1
    # (3+2) + (5+1) = 11
    assert aggregates[0].fee_tax_sum == Decimal("11")
    assert aggregates[0].buy_amount_sum == Decimal("1000")  # 4*100 + 6*100
    assert aggregates[0].sell_amount_sum == Decimal("1320")  # 4*150 + 6*120


# ======================================================================
# 4 & 5. fee/tax 정규화
# ======================================================================


@pytest.mark.asyncio
async def test_fee_tax_none_normalizes_to_assumed_zero(service, repos, account_id, instrument_id):
    buy_order = await _seed_order(repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY)
    await service.apply_fill(
        _make_fill_event(broker_order_id=buy_order.broker_order_id, quantity=Decimal("10"), price=Decimal("100"))
    )
    sell_order = await _seed_order(repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.SELL)
    sell_fill = _make_fill_event(
        broker_order_id=sell_order.broker_order_id,
        quantity=Decimal("10"),
        price=Decimal("150"),
        fill_fee=None,
        fill_tax=None,
        fill_timestamp=_BASE_TS + timedelta(seconds=1),
    )

    result = await service.apply_fill(sell_fill)

    assert result.realized_pnl_event.fee_tax_source == RealizedPnlFeeTaxSource.ASSUMED_ZERO
    assert result.realized_pnl_event.fee == Decimal("0")
    assert result.realized_pnl_event.tax == Decimal("0")
    assert result.realized_pnl_event.realized_pnl_net == result.realized_pnl_event.realized_pnl_gross


@pytest.mark.asyncio
async def test_fee_tax_present_normalizes_to_reported(service, repos, account_id, instrument_id):
    buy_order = await _seed_order(repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY)
    await service.apply_fill(
        _make_fill_event(broker_order_id=buy_order.broker_order_id, quantity=Decimal("10"), price=Decimal("100"))
    )
    sell_order = await _seed_order(repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.SELL)
    sell_fill = _make_fill_event(
        broker_order_id=sell_order.broker_order_id,
        quantity=Decimal("10"),
        price=Decimal("150"),
        fill_fee=Decimal("5"),
        fill_tax=None,
        fill_timestamp=_BASE_TS + timedelta(seconds=1),
    )

    result = await service.apply_fill(sell_fill)

    assert result.realized_pnl_event.fee_tax_source == RealizedPnlFeeTaxSource.REPORTED
    assert result.realized_pnl_event.fee == Decimal("5")
    assert result.realized_pnl_event.tax == Decimal("0")
    assert result.realized_pnl_event.realized_pnl_net == result.realized_pnl_event.realized_pnl_gross - Decimal("5")


# ======================================================================
# 6 & 7. idempotency
# ======================================================================


@pytest.mark.asyncio
async def test_duplicate_sell_fill_is_skipped(service, repos, account_id, instrument_id):
    buy_order = await _seed_order(repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY)
    await service.apply_fill(
        _make_fill_event(broker_order_id=buy_order.broker_order_id, quantity=Decimal("10"), price=Decimal("100"))
    )
    sell_order = await _seed_order(repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.SELL)
    sell_fill = _make_fill_event(
        broker_order_id=sell_order.broker_order_id,
        quantity=Decimal("4"),
        price=Decimal("150"),
        fill_timestamp=_BASE_TS + timedelta(seconds=1),
    )

    first = await service.apply_fill(sell_fill)
    second = await service.apply_fill(sell_fill)

    assert first.status == "applied"
    assert second.status == "skipped_duplicate"
    assert second.realized_pnl_event.realized_pnl_event_id == first.realized_pnl_event.realized_pnl_event_id

    # 중복 반영으로 수량이 두 번 빠지지 않아야 한다.
    state = await repos.position_cost_basis_states.get(account_id, instrument_id)
    assert state.quantity == Decimal("6")

    aggregates = await repos.realized_pnl_daily_aggregates.list_by_account_and_instrument(
        account_id, instrument_id
    )
    assert aggregates[0].sell_event_count == 1  # 중복 반영으로 2가 되면 안 된다


@pytest.mark.asyncio
async def test_duplicate_buy_fill_matching_last_applied_is_skipped(service, repos, account_id, instrument_id):
    buy_order = await _seed_order(repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY)
    buy_fill = _make_fill_event(broker_order_id=buy_order.broker_order_id, quantity=Decimal("10"), price=Decimal("100"))

    first = await service.apply_fill(buy_fill)
    second = await service.apply_fill(buy_fill)

    assert first.status == "applied"
    assert second.status == "skipped_duplicate"

    # 중복 반영으로 수량이 두 번 더해지지 않아야 한다(20이 되면 안 됨).
    state = await repos.position_cost_basis_states.get(account_id, instrument_id)
    assert state.quantity == Decimal("10")


# ======================================================================
# 8. 계산 엔진 예외 → recompute_queue + recompute_required
# ======================================================================


@pytest.mark.asyncio
async def test_engine_exception_records_recompute_queue_and_flag(service, repos, account_id, instrument_id):
    buy_order = await _seed_order(repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY)
    await service.apply_fill(
        _make_fill_event(broker_order_id=buy_order.broker_order_id, quantity=Decimal("5"), price=Decimal("100"))
    )

    sell_order = await _seed_order(repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.SELL)
    oversell_fill = _make_fill_event(
        broker_order_id=sell_order.broker_order_id,
        quantity=Decimal("999"),  # 보유 수량(5) 초과 — 숏 포지션 미지원
        price=Decimal("150"),
        fill_timestamp=_BASE_TS + timedelta(seconds=1),
    )

    result = await service.apply_fill(oversell_fill)

    assert result.status == "recompute_required"
    assert result.realized_pnl_event is None
    assert result.recompute_queue_item is not None
    assert result.recompute_queue_item.reason_code == "ledger_write_failed"
    assert result.recompute_queue_item.triggering_fill_event_id == oversell_fill.fill_event_id
    assert result.computation_run.status == "failed"
    assert result.computation_run.anomalies_detected == 1

    pending = await repos.realized_pnl_recompute_queue.list_pending()
    assert len(pending) == 1

    state = await repos.position_cost_basis_states.get(account_id, instrument_id)
    assert state.recompute_required is True
    # 실패했으므로 원래 수량(5)이 그대로 보존돼야 한다(오버셀이 반영되면 안 됨).
    assert state.quantity == Decimal("5")


# ======================================================================
# 9. out-of-order → recompute_required (엔진 호출 없이)
# ======================================================================


@pytest.mark.asyncio
async def test_out_of_order_fill_is_deferred_to_recompute_queue(service, repos, account_id, instrument_id):
    buy_order = await _seed_order(repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY)
    await service.apply_fill(
        _make_fill_event(
            broker_order_id=buy_order.broker_order_id,
            quantity=Decimal("10"),
            price=Decimal("100"),
            fill_timestamp=_BASE_TS,
        )
    )

    late_arriving_fill = _make_fill_event(
        broker_order_id=buy_order.broker_order_id,
        quantity=Decimal("5"),
        price=Decimal("90"),
        fill_timestamp=_BASE_TS - timedelta(seconds=1),  # 이미 반영된 fill보다 과거
    )

    result = await service.apply_fill(late_arriving_fill)

    assert result.status == "recompute_required"
    assert result.recompute_queue_item.reason_code == "out_of_order_fill_detected"

    state = await repos.position_cost_basis_states.get(account_id, instrument_id)
    assert state.recompute_required is True
    assert state.recompute_reason == "out_of_order_fill_detected"
    # 엔진을 호출하지 않았으므로 기존 상태(수량 10)가 그대로 보존돼야 한다.
    assert state.quantity == Decimal("10")


# ======================================================================
# 10. lineage 조인 실패
# ======================================================================


@pytest.mark.asyncio
async def test_unresolved_broker_order_raises_and_marks_run_failed(service, repos):
    orphan_fill = _make_fill_event(broker_order_id=uuid4())  # 존재하지 않는 broker_order_id

    with pytest.raises(UnresolvedFillLineageError):
        await service.apply_fill(orphan_fill)

    runs = await repos.realized_pnl_computation_runs.list_runs()
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert runs[0].anomalies_detected == 1


# ======================================================================
# 11. computation run 카운트 종합
# ======================================================================


@pytest.mark.asyncio
async def test_computation_run_counts_reflect_outcome(service, repos, account_id, instrument_id):
    buy_order = await _seed_order(repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY)
    buy_fill = _make_fill_event(broker_order_id=buy_order.broker_order_id, quantity=Decimal("10"), price=Decimal("100"))

    applied = await service.apply_fill(buy_fill)
    duplicate = await service.apply_fill(buy_fill)

    assert applied.computation_run.fills_applied == 1
    assert applied.computation_run.fills_skipped_duplicate == 0
    assert duplicate.computation_run.fills_applied == 0
    assert duplicate.computation_run.fills_skipped_duplicate == 1
    # 실시간 반영은 호출 1건당 run 1건이므로 서로 다른 run이어야 한다.
    assert applied.computation_run.computation_run_id != duplicate.computation_run.computation_run_id
