"""Tests for ``RealizedPnlRecomputeService`` — recompute/replay 복구 경로.

계산 로직 자체(이동평균, 실현 손익 산식)는 ``realized_pnl_engine.py``에서
이미 테스트됐다. 여기서는 orchestration 책임만 검증한다: fill 수집·정렬,
``replay_fills()`` 호출, 결과 upsert, queue resolve, 실패 시 관측 가능성.

Test matrix
-----------
1.  여러 fill(삽입 순서와 무관하게)을 정렬 후 replay — 최종 state/event/
    daily aggregate가 올바르게 재구성됨
2.  out-of-order로 recompute_required였던 상태가 replay 후 정상 해제되고,
    지연 도착한 fill이 올바르게 반영됨
3.  recompute 성공 시 해당 계좌×종목의 pending queue 항목만 resolve하고
    다른 계좌×종목의 pending은 그대로 유지
4.  process_pending_queue()가 같은 계좌×종목의 pending 여러 건을 coalesce
    (중복 replay 방지)
5.  recompute 실패(collect 단계 예외) 시 queue 미해결 유지 + run failed 기록
6.  recompute를 두 번 실행해도 결과가 동일함(idempotent)
7.  daily aggregate는 절대값으로 재구성됨(phantom 값이 있어도 올바른
    합계로 덮어써짐)
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import (
    BrokerOrderEntity,
    FillEventEntity,
    OrderRequestEntity,
    RealizedPnlDailyAggregateEntity,
    RealizedPnlRecomputeQueueEntity,
)
from agent_trading.domain.enums import (
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.realized_pnl_ledger_service import RealizedPnlLedgerService
from agent_trading.services.realized_pnl_recompute_service import (
    RealizedPnlRecomputeService,
)

_BASE_TS = datetime(2026, 5, 1, 9, 0, 0, tzinfo=timezone.utc)


# ======================================================================
# Helpers
# ======================================================================


def _make_order_request(
    *, account_id: UUID, instrument_id: UUID, side: OrderSide = OrderSide.BUY
) -> OrderRequestEntity:
    # created_at을 명시한다 — InMemoryOrderRepository.list()가 정렬 시
    # created_at/submitted_at 둘 다 None인 항목이 2건 이상이면 비교 불가로
    # 실패한다(실 데이터는 DB DEFAULT NOW()로 항상 채워져 발생하지 않는
    # 케이스). 실제 계좌×종목에는 order가 여러 건 있으므로 테스트에서도
    # 항상 명시한다.
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
        created_at=datetime.now(timezone.utc),
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
    broker_fill_id: str | None = None,
    created_at: datetime | None = None,
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
        broker_fill_id=broker_fill_id,
        created_at=created_at or fill_timestamp,
    )


async def _seed_order_and_fill(
    repos: RepositoryContainer,
    *,
    account_id: UUID,
    instrument_id: UUID,
    side: OrderSide,
    quantity: Decimal,
    price: Decimal,
    fill_timestamp: datetime,
    fill_fee: Decimal | None = None,
    fill_tax: Decimal | None = None,
) -> FillEventEntity:
    """order_request + broker_order를 만들고 fill_events에 직접 저장한다.

    ``RealizedPnlLedgerService``를 거치지 않는다 — recompute는 오직
    ``fill_events`` 테이블(과 그 lineage)만 보고 처음부터 다시 계산해야
    하므로, 테스트 데이터도 "실시간 반영이 안 된(또는 잘못된) 채로
    fill_events에만 쌓인" 상태를 그대로 흉내낸다.
    """
    order = _make_order_request(account_id=account_id, instrument_id=instrument_id, side=side)
    await repos.orders.add(order)
    broker_order = _make_broker_order(order_request_id=order.order_request_id)
    await repos.broker_orders.add(broker_order)
    fill = _make_fill_event(
        broker_order_id=broker_order.broker_order_id,
        quantity=quantity,
        price=price,
        fill_timestamp=fill_timestamp,
        fill_fee=fill_fee,
        fill_tax=fill_tax,
        broker_fill_id=f"CCLD-{uuid4().hex[:8]}",
    )
    await repos.fill_events.add(fill)
    return fill


class _RaisingOrderRepository:
    """``orders.list()``가 항상 예외를 던지는 fake — collect 단계 실패 격리 검증용."""

    async def list(self, query):  # noqa: ANN001 — 테스트 전용 fake
        raise RuntimeError("simulated order repository failure")


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
def recompute_service(repos: RepositoryContainer) -> RealizedPnlRecomputeService:
    return RealizedPnlRecomputeService(repos)


# ======================================================================
# 1. 여러 fill 정렬 후 replay — 최종 state/event/aggregate 재구성
# ======================================================================


@pytest.mark.asyncio
async def test_recompute_replays_multiple_fills_in_correct_order(
    recompute_service, repos, account_id, instrument_id
):
    # 삽입 순서를 실제 시간 순서와 다르게 만들어 정렬이 실제로 동작하는지 검증한다.
    sell_fill = await _seed_order_and_fill(
        repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.SELL,
        quantity=Decimal("4"), price=Decimal("150"),
        fill_fee=Decimal("3"), fill_tax=Decimal("2"),
        fill_timestamp=_BASE_TS + timedelta(seconds=1),
    )
    buy_fill = await _seed_order_and_fill(
        repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY,
        quantity=Decimal("10"), price=Decimal("100"), fill_timestamp=_BASE_TS,
    )
    assert sell_fill.fill_event_id != buy_fill.fill_event_id  # 삽입은 SELL이 먼저

    outcome = await recompute_service.recompute_account_instrument(account_id, instrument_id)

    assert outcome.computation_run.status == "completed"
    assert outcome.computation_run.fills_replayed == 2

    state = await repos.position_cost_basis_states.get(account_id, instrument_id)
    assert state.quantity == Decimal("6")
    assert state.average_cost == Decimal("100")
    assert state.recompute_required is False

    events = await repos.realized_pnl_events.list_by_account_and_instrument(
        account_id, instrument_id
    )
    assert len(events) == 1
    assert events[0].realized_pnl_gross == Decimal("200")  # (150-100)*4

    aggregates = await repos.realized_pnl_daily_aggregates.list_by_account_and_instrument(
        account_id, instrument_id
    )
    assert len(aggregates) == 1
    # net = gross - fee - tax = 200 - 3 - 2 = 195.
    assert aggregates[0].realized_pnl_net_sum == Decimal("195")
    assert aggregates[0].sell_event_count == 1
    # UI용 파생 합계 캐시(entities.py RealizedPnlDailyAggregateEntity 참고) —
    # 절대값 재구성이라 events 전체에서 다시 합산된다.
    assert aggregates[0].buy_amount_sum == Decimal("400")  # 4*100
    assert aggregates[0].sell_amount_sum == Decimal("600")  # 4*150
    assert aggregates[0].fee_tax_sum == Decimal("5")  # 3+2


# ======================================================================
# 2. out-of-order recompute_required 해제 + 지연 fill 반영
# ======================================================================


@pytest.mark.asyncio
async def test_recompute_resolves_out_of_order_state_and_incorporates_late_fill(
    repos, account_id, instrument_id
):
    ledger_service = RealizedPnlLedgerService(repos)
    recompute_service = RealizedPnlRecomputeService(repos)

    on_time_fill = await _seed_order_and_fill(
        repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY,
        quantity=Decimal("10"), price=Decimal("100"), fill_timestamp=_BASE_TS,
    )
    await ledger_service.apply_fill(on_time_fill)

    late_arriving_fill = await _seed_order_and_fill(
        repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY,
        quantity=Decimal("5"), price=Decimal("80"),
        fill_timestamp=_BASE_TS - timedelta(seconds=1),  # on_time_fill보다 과거
    )
    result = await ledger_service.apply_fill(late_arriving_fill)
    assert result.status == "recompute_required"

    state_before = await repos.position_cost_basis_states.get(account_id, instrument_id)
    assert state_before.recompute_required is True
    assert state_before.quantity == Decimal("10")  # late_arriving_fill 미반영

    outcome = await recompute_service.recompute_account_instrument(account_id, instrument_id)

    assert outcome.computation_run.status == "completed"
    state_after = await repos.position_cost_basis_states.get(account_id, instrument_id)
    assert state_after.recompute_required is False
    assert state_after.recompute_reason is None
    # 올바른 순서(late_arriving_fill 먼저, on_time_fill 나중)로 재계산되어
    # 두 BUY 수량이 모두 반영돼야 한다: 5 + 10 = 15
    assert state_after.quantity == Decimal("15")
    expected_avg = (Decimal("5") * Decimal("80") + Decimal("10") * Decimal("100")) / Decimal("15")
    assert state_after.average_cost == expected_avg

    assert len(outcome.resolved_queue_item_ids) >= 1
    pending = await repos.realized_pnl_recompute_queue.list_pending()
    assert len(pending) == 0


# ======================================================================
# 3. queue resolve는 해당 계좌×종목에만 적용
# ======================================================================


@pytest.mark.asyncio
async def test_recompute_resolves_only_matching_account_instrument_queue_items(
    recompute_service, repos, account_id, instrument_id
):
    await _seed_order_and_fill(
        repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY,
        quantity=Decimal("10"), price=Decimal("100"), fill_timestamp=_BASE_TS,
    )
    other_account_id, other_instrument_id = uuid4(), uuid4()
    await _seed_order_and_fill(
        repos, account_id=other_account_id, instrument_id=other_instrument_id, side=OrderSide.BUY,
        quantity=Decimal("5"), price=Decimal("50"), fill_timestamp=_BASE_TS,
    )

    item_a1 = RealizedPnlRecomputeQueueEntity(
        recompute_queue_id=uuid4(), account_id=account_id, instrument_id=instrument_id,
        reason_code="manual_request",
    )
    item_a2 = RealizedPnlRecomputeQueueEntity(
        recompute_queue_id=uuid4(), account_id=account_id, instrument_id=instrument_id,
        reason_code="out_of_order_fill_detected",
    )
    item_other = RealizedPnlRecomputeQueueEntity(
        recompute_queue_id=uuid4(), account_id=other_account_id, instrument_id=other_instrument_id,
        reason_code="manual_request",
    )
    for item in (item_a1, item_a2, item_other):
        await repos.realized_pnl_recompute_queue.add(item)

    outcome = await recompute_service.recompute_account_instrument(account_id, instrument_id)

    assert set(outcome.resolved_queue_item_ids) == {item_a1.recompute_queue_id, item_a2.recompute_queue_id}
    pending = await repos.realized_pnl_recompute_queue.list_pending()
    assert len(pending) == 1
    assert pending[0].recompute_queue_id == item_other.recompute_queue_id


# ======================================================================
# 4. process_pending_queue — 같은 계좌×종목 coalesce
# ======================================================================


@pytest.mark.asyncio
async def test_process_pending_queue_coalesces_duplicate_account_instrument(
    recompute_service, repos, account_id, instrument_id
):
    await _seed_order_and_fill(
        repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY,
        quantity=Decimal("10"), price=Decimal("100"), fill_timestamp=_BASE_TS,
    )
    for _ in range(3):
        await repos.realized_pnl_recompute_queue.add(
            RealizedPnlRecomputeQueueEntity(
                recompute_queue_id=uuid4(), account_id=account_id, instrument_id=instrument_id,
                reason_code="manual_request",
            )
        )

    outcomes = await recompute_service.process_pending_queue()

    assert len(outcomes) == 1, "같은 계좌×종목은 한 번만 replay돼야 한다"
    pending = await repos.realized_pnl_recompute_queue.list_pending()
    assert len(pending) == 0


# ======================================================================
# 5. collect 단계 실패 → queue 미해결 유지 + run failed
# ======================================================================


@pytest.mark.asyncio
async def test_recompute_failure_during_collect_leaves_queue_pending(
    repos, account_id, instrument_id
):
    queue_item = RealizedPnlRecomputeQueueEntity(
        recompute_queue_id=uuid4(), account_id=account_id, instrument_id=instrument_id,
        reason_code="manual_request",
    )
    await repos.realized_pnl_recompute_queue.add(queue_item)

    broken_repos = replace(repos, orders=_RaisingOrderRepository())
    recompute_service = RealizedPnlRecomputeService(broken_repos)

    outcome = await recompute_service.recompute_account_instrument(account_id, instrument_id)

    assert outcome.computation_run.status == "failed"
    assert outcome.computation_run.anomalies_detected == 1
    assert outcome.computation_run.summary_json.get("phase") == "collect_fills"
    assert outcome.resolved_queue_item_ids == ()

    # 원래(정상) repos 기준으로는 여전히 pending이어야 한다.
    pending = await repos.realized_pnl_recompute_queue.list_pending()
    assert len(pending) == 1
    assert pending[0].recompute_queue_id == queue_item.recompute_queue_id


# ======================================================================
# 6. idempotent 재실행
# ======================================================================


@pytest.mark.asyncio
async def test_recompute_is_idempotent_when_run_twice(
    recompute_service, repos, account_id, instrument_id
):
    await _seed_order_and_fill(
        repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY,
        quantity=Decimal("10"), price=Decimal("100"), fill_timestamp=_BASE_TS,
    )
    await _seed_order_and_fill(
        repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.SELL,
        quantity=Decimal("4"), price=Decimal("150"),
        fill_timestamp=_BASE_TS + timedelta(seconds=1),
    )

    first = await recompute_service.recompute_account_instrument(account_id, instrument_id)
    state_after_first = await repos.position_cost_basis_states.get(account_id, instrument_id)
    events_after_first = await repos.realized_pnl_events.list_by_account_and_instrument(
        account_id, instrument_id
    )

    second = await recompute_service.recompute_account_instrument(account_id, instrument_id)
    state_after_second = await repos.position_cost_basis_states.get(account_id, instrument_id)
    events_after_second = await repos.realized_pnl_events.list_by_account_and_instrument(
        account_id, instrument_id
    )

    assert first.computation_run.status == second.computation_run.status == "completed"
    assert state_after_first.quantity == state_after_second.quantity
    assert state_after_first.average_cost == state_after_second.average_cost
    assert len(events_after_first) == len(events_after_second) == 1
    assert events_after_first[0].realized_pnl_event_id == events_after_second[0].realized_pnl_event_id
    assert events_after_first[0].realized_pnl_net == events_after_second[0].realized_pnl_net


# ======================================================================
# 7. daily aggregate는 절대값으로 재구성(phantom 값 덮어쓰기)
# ======================================================================


@pytest.mark.asyncio
async def test_recompute_overwrites_phantom_daily_aggregate(
    recompute_service, repos, account_id, instrument_id
):
    from agent_trading.services.realized_pnl_ledger_service import to_kst_trade_date

    await _seed_order_and_fill(
        repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY,
        quantity=Decimal("10"), price=Decimal("100"), fill_timestamp=_BASE_TS,
    )
    await _seed_order_and_fill(
        repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.SELL,
        quantity=Decimal("4"), price=Decimal("150"),
        fill_timestamp=_BASE_TS + timedelta(seconds=1),
    )

    # 실제로는 있을 수 없는 잘못된(phantom) 값을 미리 심어 둔다.
    trade_date = to_kst_trade_date(_BASE_TS)
    await repos.realized_pnl_daily_aggregates.upsert(
        RealizedPnlDailyAggregateEntity(
            account_id=account_id, instrument_id=instrument_id, trade_date=trade_date,
            realized_pnl_net_sum=Decimal("999999"), sell_event_count=999,
            buy_amount_sum=Decimal("999999"), sell_amount_sum=Decimal("999999"),
            fee_tax_sum=Decimal("999999"),
            computation_run_id=uuid4(),
        )
    )

    await recompute_service.recompute_account_instrument(account_id, instrument_id)

    aggregates = await repos.realized_pnl_daily_aggregates.list_by_account_and_instrument(
        account_id, instrument_id
    )
    assert len(aggregates) == 1
    assert aggregates[0].realized_pnl_net_sum == Decimal("200")  # (150-100)*4, phantom 값이 아님
    assert aggregates[0].sell_event_count == 1
    # UI용 파생 합계 캐시도 절대값 재구성이라 phantom 값이 남지 않는다.
    assert aggregates[0].buy_amount_sum == Decimal("400")  # 4*100
    assert aggregates[0].sell_amount_sum == Decimal("600")  # 4*150
    assert aggregates[0].fee_tax_sum == Decimal("0")


# ======================================================================
# 8. historical_buy_fee_overlays 병합 — `007070` 파일럿 재현
# ======================================================================


@pytest.mark.asyncio
async def test_recompute_merges_historical_buy_fee_overlay_and_reallocates_existing_sells(
    recompute_service, repos, account_id, instrument_id
):
    """`007070` 실제 이력(BUY 176 → SELL 88 → SELL 70, 잔량 18)을 그대로
    재현한다. overlay 등록 전에는 BUY fee가 없어 두 SELL 모두
    allocated_buy_fee=0으로 계산되지만, overlay를 얹고 recompute하면
    fill_events 원본은 그대로인 채 두 SELL의 allocated_buy_fee/
    realized_pnl_net과 최종 pool이 재배분돼야 한다."""
    from agent_trading.domain.entities import (
        ConfigVersionEntity,
        HistoricalBuyFeeOverlayEntity,
    )
    from agent_trading.domain.enums import Environment, RealizedPnlBuyFeeAllocationSource

    buy_ts = _BASE_TS
    sell1_ts = _BASE_TS + timedelta(days=3)
    sell2_ts = _BASE_TS + timedelta(days=3, seconds=1)

    buy_fill = await _seed_order_and_fill(
        repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY,
        quantity=Decimal("176"), price=Decimal("28000"), fill_timestamp=buy_ts,
        # fill_fee/fill_tax=None — 실제 007070과 동일(정책 등록 이전 backfill).
    )
    await _seed_order_and_fill(
        repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.SELL,
        quantity=Decimal("88"), price=Decimal("26800"), fill_timestamp=sell1_ts,
    )
    await _seed_order_and_fill(
        repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.SELL,
        quantity=Decimal("70"), price=Decimal("26650"), fill_timestamp=sell2_ts,
    )

    # --- overlay 등록 전 recompute: BUY fee가 없으므로 allocated_buy_fee=0 ---
    before = await recompute_service.recompute_account_instrument(account_id, instrument_id)
    assert before.computation_run.status == "completed"
    events_before = await repos.realized_pnl_events.list_by_account_and_instrument(
        account_id, instrument_id
    )
    assert len(events_before) == 2
    assert all(e.allocated_buy_fee == Decimal("0") for e in events_before)
    assert all(
        e.buy_fee_allocation_source == RealizedPnlBuyFeeAllocationSource.FULLY_ASSUMED_ZERO
        for e in events_before
    )

    # --- overlay 등록(fill_events 원본은 건드리지 않음) ---
    client_id = uuid4()
    policy_version = ConfigVersionEntity(
        config_version_id=uuid4(), client_id=client_id, environment=Environment.PAPER,
        version_tag="test", config_json={"execution": {"fee_tax": {"buy_commission_rate_pct": "0.0140527"}}},
        checksum="test", activated_at=datetime.now(timezone.utc),
    )
    await repos.config_versions.add(policy_version)

    overlay = HistoricalBuyFeeOverlayEntity(
        overlay_id=uuid4(),
        fill_event_id=buy_fill.fill_event_id,
        estimated_fee=Decimal("693"),  # illustrative: 176*28000*0.0140527% ≈ 692.52 → round_half_up
        fee_tax_source="historical_policy_estimate",
        basis_config_version_id=policy_version.config_version_id,
        reason="007070 파일럿 — 정책 등록 이전 BUY fee 소급 추정",
        created_by="test-operator",
    )
    await repos.historical_buy_fee_overlays.add(overlay)

    # fill_events 원본은 여전히 그대로여야 한다(overlay가 아니라 원본을 다시 조회).
    original_fills = await repos.fill_events.list_by_broker_order(buy_fill.broker_order_id)
    original_fill = next(f for f in original_fills if f.fill_event_id == buy_fill.fill_event_id)
    assert original_fill.fill_fee is None
    assert original_fill.fee_tax_source is None

    # --- overlay 등록 후 recompute: 두 SELL 모두 재배분돼야 한다 ---
    after = await recompute_service.recompute_account_instrument(account_id, instrument_id)
    assert after.computation_run.status == "completed"
    assert after.computation_run.fills_replayed == 3

    events_after = await repos.realized_pnl_events.list_by_account_and_instrument(
        account_id, instrument_id
    )
    assert len(events_after) == 2
    sell1_event = next(e for e in events_after if e.sell_quantity == Decimal("88"))
    sell2_event = next(e for e in events_after if e.sell_quantity == Decimal("70"))

    # pool 693 * (88/176) = 346.5
    assert sell1_event.allocated_buy_fee == Decimal("346.5")
    assert sell1_event.buy_fee_allocation_source == RealizedPnlBuyFeeAllocationSource.HISTORICALLY_ESTIMATED
    # gross는 절대 안 바뀐다: (26800-28000)*88 = -105600
    assert sell1_event.realized_pnl_gross == Decimal("-105600")
    # net = gross - fee - tax - allocated_buy_fee = -105600 - 0 - 0 - 346.5
    assert sell1_event.realized_pnl_net == Decimal("-105946.5")

    # 남은 pool 346.5 * (70/88) = 275.625
    assert sell2_event.allocated_buy_fee == Decimal("275.625")
    assert sell2_event.buy_fee_allocation_source == RealizedPnlBuyFeeAllocationSource.HISTORICALLY_ESTIMATED
    assert sell2_event.realized_pnl_gross == Decimal("-94500")  # (26650-28000)*70
    assert sell2_event.realized_pnl_net == Decimal("-94775.625")

    # 최종 남은 pool: 693 - 346.5 - 275.625 = 70.875
    state = await repos.position_cost_basis_states.get(account_id, instrument_id)
    assert state.quantity == Decimal("18")
    assert state.average_cost == Decimal("28000")  # average_cost는 절대 안 바뀐다
    assert state.remaining_buy_fee_pool == Decimal("70.875")
    assert state.buy_fee_pool_provenance == RealizedPnlBuyFeeAllocationSource.HISTORICALLY_ESTIMATED

    # daily aggregate의 net_sum도 재구성된 값을 반영한다.
    aggregates = await repos.realized_pnl_daily_aggregates.list_by_account_and_instrument(
        account_id, instrument_id
    )
    total_net = sum((a.realized_pnl_net_sum for a in aggregates), Decimal("0"))
    assert total_net == Decimal("-105946.5") + Decimal("-94775.625")


@pytest.mark.asyncio
async def test_recompute_ignores_sell_events_without_overlay(
    recompute_service, repos, account_id, instrument_id
):
    """SELL overlay가 전혀 없으면 recompute 결과는 overlay 도입 이전과
    완전히 동일해야 한다(회귀 방지 — 실시간 경로/기존 BUY-only 시나리오
    무영향)."""
    from agent_trading.domain.enums import RealizedPnlFeeTaxSource

    buy_ts = _BASE_TS
    sell_ts = _BASE_TS + timedelta(days=1)

    await _seed_order_and_fill(
        repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY,
        quantity=Decimal("10"), price=Decimal("1000"), fill_timestamp=buy_ts,
        fill_fee=Decimal("0"), fill_tax=Decimal("0"),
    )
    await _seed_order_and_fill(
        repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.SELL,
        quantity=Decimal("10"), price=Decimal("1100"), fill_timestamp=sell_ts,
    )

    outcome = await recompute_service.recompute_account_instrument(account_id, instrument_id)
    assert outcome.computation_run.status == "completed"

    events = await repos.realized_pnl_events.list_by_account_and_instrument(
        account_id, instrument_id
    )
    assert len(events) == 1
    sell_event = events[0]
    assert sell_event.fee == Decimal("0")
    assert sell_event.tax == Decimal("0")
    assert sell_event.fee_tax_source == RealizedPnlFeeTaxSource.ASSUMED_ZERO
    assert sell_event.realized_pnl_net == Decimal("1000")  # (1100-1000)*10 - 0 - 0 - 0


@pytest.mark.asyncio
async def test_recompute_merges_historical_sell_fee_tax_overlay_and_reinterprets_existing_sells(
    recompute_service, repos, account_id, instrument_id
):
    """`007070` 실제 이력 확장 — BUY overlay가 이미 반영된 상태(§8.13,
    allocated_buy_fee=346.5/275.625) 위에, SELL 2건의 매도 수수료+매도세
    historical estimate overlay를 추가로 얹는다. overlay 반영 전에는
    fee=tax=0(assumed_zero)이던 두 SELL이, overlay 반영 후에는 fee/tax가
    채워지고 realized_pnl_net이 그만큼 추가로 악화돼야 한다 — allocated_
    buy_fee는 이번 오버레이와 무관하게 그대로 유지된다."""
    from agent_trading.domain.entities import (
        ConfigVersionEntity,
        HistoricalBuyFeeOverlayEntity,
        HistoricalSellFeeTaxOverlayEntity,
    )
    from agent_trading.domain.enums import Environment, RealizedPnlFeeTaxSource

    buy_ts = _BASE_TS
    sell1_ts = _BASE_TS + timedelta(days=3)
    sell2_ts = _BASE_TS + timedelta(days=3, seconds=1)

    buy_fill = await _seed_order_and_fill(
        repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY,
        quantity=Decimal("176"), price=Decimal("28000"), fill_timestamp=buy_ts,
    )
    sell1_fill = await _seed_order_and_fill(
        repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.SELL,
        quantity=Decimal("88"), price=Decimal("26800"), fill_timestamp=sell1_ts,
    )
    sell2_fill = await _seed_order_and_fill(
        repos, account_id=account_id, instrument_id=instrument_id, side=OrderSide.SELL,
        quantity=Decimal("70"), price=Decimal("26650"), fill_timestamp=sell2_ts,
    )

    client_id = uuid4()
    policy_version = ConfigVersionEntity(
        config_version_id=uuid4(), client_id=client_id, environment=Environment.PAPER,
        version_tag="test", config_json={"execution": {"fee_tax": {}}},
        checksum="test", activated_at=datetime.now(timezone.utc),
    )
    await repos.config_versions.add(policy_version)

    # --- 1단계: BUY overlay만 등록하고 recompute(§8.13과 동일한 baseline) ---
    buy_overlay = HistoricalBuyFeeOverlayEntity(
        overlay_id=uuid4(),
        fill_event_id=buy_fill.fill_event_id,
        estimated_fee=Decimal("693"),
        fee_tax_source="historical_policy_estimate",
        basis_config_version_id=policy_version.config_version_id,
        reason="007070 파일럿 — 정책 등록 이전 BUY fee 소급 추정",
        created_by="test-operator",
    )
    await repos.historical_buy_fee_overlays.add(buy_overlay)
    baseline = await recompute_service.recompute_account_instrument(account_id, instrument_id)
    assert baseline.computation_run.status == "completed"

    events_baseline = await repos.realized_pnl_events.list_by_account_and_instrument(
        account_id, instrument_id
    )
    sell1_baseline = next(e for e in events_baseline if e.sell_quantity == Decimal("88"))
    sell2_baseline = next(e for e in events_baseline if e.sell_quantity == Decimal("70"))
    assert sell1_baseline.fee == Decimal("0")
    assert sell1_baseline.tax == Decimal("0")
    assert sell1_baseline.fee_tax_source == RealizedPnlFeeTaxSource.ASSUMED_ZERO
    assert sell1_baseline.allocated_buy_fee == Decimal("346.5")
    assert sell1_baseline.realized_pnl_net == Decimal("-105946.5")
    assert sell2_baseline.allocated_buy_fee == Decimal("275.625")
    assert sell2_baseline.realized_pnl_net == Decimal("-94775.625")

    # --- 2단계: SELL fee/tax overlay 등록(illustrative — 26800×88/26650×70 기준 추정치) ---
    sell1_overlay = HistoricalSellFeeTaxOverlayEntity(
        overlay_id=uuid4(),
        fill_event_id=sell1_fill.fill_event_id,
        estimated_fee=Decimal("331"),
        estimated_tax=Decimal("4717"),
        fee_tax_source="historical_policy_estimate",
        basis_config_version_id=policy_version.config_version_id,
        reason="007070 파일럿 — 정책 등록 이전 SELL fee/tax 소급 추정",
        created_by="test-operator",
    )
    sell2_overlay = HistoricalSellFeeTaxOverlayEntity(
        overlay_id=uuid4(),
        fill_event_id=sell2_fill.fill_event_id,
        estimated_fee=Decimal("262"),
        estimated_tax=Decimal("3731"),
        fee_tax_source="historical_policy_estimate",
        basis_config_version_id=policy_version.config_version_id,
        reason="007070 파일럿 — 정책 등록 이전 SELL fee/tax 소급 추정",
        created_by="test-operator",
    )
    await repos.historical_sell_fee_tax_overlays.add(sell1_overlay)
    await repos.historical_sell_fee_tax_overlays.add(sell2_overlay)

    # fill_events 원본은 여전히 그대로여야 한다(overlay가 아니라 원본을 다시 조회).
    original_sell1_fills = await repos.fill_events.list_by_broker_order(sell1_fill.broker_order_id)
    original_sell1 = next(f for f in original_sell1_fills if f.fill_event_id == sell1_fill.fill_event_id)
    assert original_sell1.fill_fee is None
    assert original_sell1.fill_tax is None
    assert original_sell1.fee_tax_source is None

    # --- 3단계: SELL overlay 등록 후 recompute ---
    after = await recompute_service.recompute_account_instrument(account_id, instrument_id)
    assert after.computation_run.status == "completed"
    assert after.computation_run.fills_replayed == 3

    events_after = await repos.realized_pnl_events.list_by_account_and_instrument(
        account_id, instrument_id
    )
    sell1_after = next(e for e in events_after if e.sell_quantity == Decimal("88"))
    sell2_after = next(e for e in events_after if e.sell_quantity == Decimal("70"))

    # fee/tax가 overlay 값으로 override됨.
    assert sell1_after.fee == Decimal("331")
    assert sell1_after.tax == Decimal("4717")
    assert sell1_after.fee_tax_source == RealizedPnlFeeTaxSource.HISTORICAL_POLICY_ESTIMATE
    assert sell2_after.fee == Decimal("262")
    assert sell2_after.tax == Decimal("3731")
    assert sell2_after.fee_tax_source == RealizedPnlFeeTaxSource.HISTORICAL_POLICY_ESTIMATE

    # allocated_buy_fee는 이번 SELL overlay와 무관하게 그대로 유지된다
    # (BUY overlay가 그대로 남아 있고 pool 배분 로직은 안 바뀌었으므로).
    assert sell1_after.allocated_buy_fee == Decimal("346.5")
    assert sell2_after.allocated_buy_fee == Decimal("275.625")

    # gross는 절대 안 바뀐다.
    assert sell1_after.realized_pnl_gross == Decimal("-105600")
    assert sell2_after.realized_pnl_gross == Decimal("-94500")

    # net = gross - fee - tax - allocated_buy_fee
    assert sell1_after.realized_pnl_net == Decimal("-105600") - Decimal("331") - Decimal("4717") - Decimal("346.5")
    assert sell1_after.realized_pnl_net == Decimal("-110994.5")
    assert sell2_after.realized_pnl_net == Decimal("-94500") - Decimal("262") - Decimal("3731") - Decimal("275.625")
    assert sell2_after.realized_pnl_net == Decimal("-98768.625")

    # 기존(1단계) 대비 추가로 악화된 정도 = 매도 수수료+매도세 합계.
    assert (sell1_baseline.realized_pnl_net - sell1_after.realized_pnl_net) == Decimal("331") + Decimal("4717")
    assert (sell2_baseline.realized_pnl_net - sell2_after.realized_pnl_net) == Decimal("262") + Decimal("3731")

    # position_cost_basis_state — average_cost/quantity/pool은 SELL fee/tax
    # overlay와 무관하게 유지된다(매도 비용은 pool 배분에 영향 주지 않음).
    state = await repos.position_cost_basis_states.get(account_id, instrument_id)
    assert state.quantity == Decimal("18")
    assert state.average_cost == Decimal("28000")
    assert state.remaining_buy_fee_pool == Decimal("70.875")

    # daily aggregate의 net_sum도 재구성된 값을 반영한다.
    aggregates = await repos.realized_pnl_daily_aggregates.list_by_account_and_instrument(
        account_id, instrument_id
    )
    total_net_after = sum((a.realized_pnl_net_sum for a in aggregates), Decimal("0"))
    assert total_net_after == Decimal("-110994.5") + Decimal("-98768.625")
