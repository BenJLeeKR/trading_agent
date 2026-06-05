from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from agent_trading.domain.entities import BrokerOrderEntity, OrderRequestEntity
from agent_trading.domain.enums import BrokerName, OrderSide, OrderStatus, OrderType, TimeInForce
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.services.fill_history_sync import sync_fill_history_for_account
from agent_trading.brokers.rate_limit import BudgetExhaustedError

pytestmark = pytest.mark.asyncio


def _make_order() -> OrderRequestEntity:
    now = datetime.now(timezone.utc)
    return OrderRequestEntity(
        order_request_id=uuid4(),
        account_id=uuid4(),
        instrument_id=uuid4(),
        client_order_id="FILL-SYNC-ORDER-001",
        idempotency_key="fill-sync-idem-001",
        correlation_id="fill-sync-corr-001",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        requested_price=Decimal("10000"),
        requested_quantity=Decimal("1"),
        status=OrderStatus.SUBMITTED,
        trade_decision_id=None,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_sync_fill_history_links_order_request_id_from_broker_native_order_id() -> None:
    repos = build_in_memory_repositories()
    order = _make_order()
    repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]
    broker_order = BrokerOrderEntity(
        broker_order_id=uuid4(),
        order_request_id=order.order_request_id,
        broker_name=BrokerName.KOREA_INVESTMENT.value,
        broker_status="submitted",
        broker_native_order_id="0000033121",
    )
    repos.broker_orders._items[broker_order.broker_order_id] = broker_order  # type: ignore[attr-defined]

    rest_client = AsyncMock()
    rest_client.inquire_daily_ccld = AsyncMock(
        return_value=[
            {
                "odno": "0000033121",
                "pdno": "001740",
                "sll_buy_dvsn_cd": "02",
                "ord_qty": "207",
                "tot_ccld_qty": "207",
                "avg_prvs": "11980",
                "ord_tmd": "144301",
                "ccld_tmd": "144305",
                "ord_stat": "22",
            }
        ]
    )

    result = await sync_fill_history_for_account(
        rest_client=rest_client,
        fill_repo=repos.broker_fill_snapshots,
        broker_order_repo=repos.broker_orders,
        account_id=order.account_id,
        order_day=datetime(2026, 6, 1, tzinfo=timezone.utc).date(),
        fill_sync_run_id=uuid4(),
        after_hours=True,
    )

    assert result.fills_synced == 1
    rows = await repos.broker_fill_snapshots.list_recent(
        limit=10,
        order_request_id=order.order_request_id,
    )
    assert len(rows) == 1
    assert rows[0].order_request_id == order.order_request_id
    assert rows[0].broker_native_order_id == "0000033121"


@pytest.mark.asyncio
async def test_sync_fill_history_retries_once_on_inquiry_budget_exhaustion() -> None:
    repos = build_in_memory_repositories()
    order = _make_order()
    repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]
    broker_order = BrokerOrderEntity(
        broker_order_id=uuid4(),
        order_request_id=order.order_request_id,
        broker_name=BrokerName.KOREA_INVESTMENT.value,
        broker_status="submitted",
        broker_native_order_id="0000039999",
    )
    repos.broker_orders._items[broker_order.broker_order_id] = broker_order  # type: ignore[attr-defined]

    rest_client = AsyncMock()
    rest_client.inquire_daily_ccld = AsyncMock(
        side_effect=[
            BudgetExhaustedError("inquiry", "Bucket 'inquiry' exhausted (remaining=0/1)"),
            [
                {
                    "odno": "0000039999",
                    "pdno": "005930",
                    "sll_buy_dvsn_cd": "02",
                    "ord_qty": "10",
                    "tot_ccld_qty": "10",
                    "avg_prvs": "70000",
                    "ord_tmd": "100000",
                    "ccld_tmd": "100001",
                }
            ],
        ]
    )
    rest_client._wait_for_inquiry_budget = AsyncMock(return_value=True)

    result = await sync_fill_history_for_account(
        rest_client=rest_client,
        fill_repo=repos.broker_fill_snapshots,
        broker_order_repo=repos.broker_orders,
        account_id=order.account_id,
        order_day=datetime(2026, 6, 2, tzinfo=timezone.utc).date(),
        fill_sync_run_id=uuid4(),
        after_hours=True,
    )

    assert result.fills_synced == 1
    assert result.retried_days == 1
    assert result.retry_count == 1
    assert rest_client.inquire_daily_ccld.await_count == 2
    rest_client._wait_for_inquiry_budget.assert_awaited_once()


async def test_build_fill_sync_run_entity_includes_retry_summary() -> None:
    from agent_trading.services.fill_history_sync import FillBatchSyncResult, build_fill_sync_run_entity

    batch = FillBatchSyncResult(
        total_accounts=1,
        succeeded=1,
        total_fills_synced=9,
        retried_accounts=1,
        retried_days=1,
        total_retries=1,
    )

    run = build_fill_sync_run_entity(
        batch,
        trigger_type="scheduler",
        scope="all",
    )

    assert run.summary_json == {
        "retried_accounts": 1,
        "retried_days": 1,
        "total_retries": 1,
    }
