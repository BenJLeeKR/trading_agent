from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from agent_trading.api.app import create_app
from agent_trading.api.deps import get_repos
from agent_trading.domain.entities import (
    AccountEntity,
    BrokerFillSnapshotEntity,
    FillSyncRunEntity,
    InstrumentEntity,
    OrderRequestEntity,
)
from agent_trading.domain.enums import Environment, OrderSide, OrderStatus, OrderType, TimeInForce
from agent_trading.repositories.bootstrap import build_in_memory_repositories


def test_list_fill_history_returns_rows() -> None:
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    account_id = uuid.uuid4()
    broker_account_id = uuid.uuid4()
    repos.accounts._items[account_id] = AccountEntity(  # type: ignore[attr-defined]
        account_id=account_id,
        client_id=uuid.uuid4(),
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="테스트 계좌",
        account_masked="1234",
        status="active",
        account_code="TEST-001",
    )
    instrument_id = uuid.uuid4()
    repos.instruments._items[instrument_id] = InstrumentEntity(  # type: ignore[attr-defined]
        instrument_id=instrument_id,
        symbol="005930",
        market_code="KRX",
        asset_class="equity",
        currency="KRW",
        name="삼성전자",
        tick_size=Decimal("100"),
        lot_size=Decimal("1"),
        is_active=True,
        metadata={},
    )
    snapshot = BrokerFillSnapshotEntity(
        broker_fill_snapshot_id=uuid.uuid4(),
        fill_sync_run_id=uuid.uuid4(),
        account_id=account_id,
        order_request_id=uuid.uuid4(),
        broker_name="koreainvestment",
        broker_native_order_id="0001234567",
        broker_fill_id="CCLD-1",
        symbol="005930",
        side="buy",
        order_date=date(2026, 6, 2),
        order_status_code="22",
        ordered_quantity=Decimal("10"),
        filled_quantity=Decimal("10"),
        fill_price=Decimal("71200"),
        order_time="091500",
        fill_time="091501",
        fill_timestamp=datetime.now(timezone.utc),
        dedupe_key="dedupe-1",
        raw_payload_json={},
    )
    asyncio.run(repos.broker_fill_snapshots.upsert(snapshot))

    with TestClient(app) as client:
        resp = client.get(
            "/fill-history?date=2026-06-02",
            headers={"Authorization": "Bearer test-token"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["symbol"] == "005930"
    assert data[0]["instrument_name"] == "삼성전자"
    assert data[0]["account_alias"] == "테스트 계좌"
    assert data[0]["order_request_id"] is not None


def test_list_fill_history_hides_zero_fill_polling_rows_and_keeps_latest_positive() -> None:
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    account_id = uuid.uuid4()
    broker_account_id = uuid.uuid4()
    order_request_id = uuid.uuid4()
    repos.accounts._items[account_id] = AccountEntity(  # type: ignore[attr-defined]
        account_id=account_id,
        client_id=uuid.uuid4(),
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="테스트 계좌",
        account_masked="1234",
        status="active",
        account_code="TEST-001",
    )
    instrument_id = uuid.uuid4()
    repos.instruments._items[instrument_id] = InstrumentEntity(  # type: ignore[attr-defined]
        instrument_id=instrument_id,
        symbol="005940",
        market_code="KRX",
        asset_class="equity",
        currency="KRW",
        name="NH투자증권우",
        tick_size=Decimal("1"),
        lot_size=Decimal("1"),
        is_active=True,
        metadata={},
    )
    base_time = datetime.now(timezone.utc)
    for snapshot in (
        BrokerFillSnapshotEntity(
            broker_fill_snapshot_id=uuid.uuid4(),
            fill_sync_run_id=uuid.uuid4(),
            account_id=account_id,
            order_request_id=order_request_id,
            broker_name="koreainvestment",
            broker_native_order_id="0000005097",
            broker_fill_id=None,
            symbol="005940",
            side="buy",
            order_date=date(2026, 6, 8),
            order_status_code="시장가",
            ordered_quantity=Decimal("17"),
            filled_quantity=Decimal("0"),
            fill_price=Decimal("0"),
            order_time="091400",
            fill_time="",
            fill_timestamp=None,
            dedupe_key="dedupe-zero",
            raw_payload_json={},
            created_at=base_time,
            updated_at=base_time,
        ),
        BrokerFillSnapshotEntity(
            broker_fill_snapshot_id=uuid.uuid4(),
            fill_sync_run_id=uuid.uuid4(),
            account_id=account_id,
            order_request_id=order_request_id,
            broker_name="koreainvestment",
            broker_native_order_id="0000005097",
            broker_fill_id=None,
            symbol="005940",
            side="buy",
            order_date=date(2026, 6, 8),
            order_status_code="시장가",
            ordered_quantity=Decimal("17"),
            filled_quantity=Decimal("17"),
            fill_price=Decimal("29117"),
            order_time="091400",
            fill_time="091405",
            fill_timestamp=base_time + timedelta(minutes=1),
            dedupe_key="dedupe-positive",
            raw_payload_json={},
            created_at=base_time + timedelta(minutes=1),
            updated_at=base_time + timedelta(minutes=1),
        ),
    ):
        asyncio.run(repos.broker_fill_snapshots.upsert(snapshot))

    with TestClient(app) as client:
        resp = client.get(
            "/fill-history?date=2026-06-08",
            headers={"Authorization": "Bearer test-token"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["symbol"] == "005940"
    assert data[0]["filled_quantity"] == 17.0
    assert data[0]["fill_price"] == 29117.0


def test_list_fill_history_supports_order_symbol_odno_and_trade_decision_filters() -> None:
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    account_id = uuid.uuid4()
    broker_account_id = uuid.uuid4()
    target_order_request_id = uuid.uuid4()
    other_order_request_id = uuid.uuid4()
    target_trade_decision_id = uuid.uuid4()
    other_trade_decision_id = uuid.uuid4()
    repos.accounts._items[account_id] = AccountEntity(  # type: ignore[attr-defined]
        account_id=account_id,
        client_id=uuid.uuid4(),
        broker_account_id=broker_account_id,
        environment=Environment.PAPER,
        account_alias="테스트 계좌",
        account_masked="1234",
        status="active",
        account_code="TEST-001",
    )
    now = datetime.now(timezone.utc)
    for order in (
        OrderRequestEntity(
            order_request_id=target_order_request_id,
            account_id=account_id,
            instrument_id=uuid.uuid4(),
            client_order_id="client-1",
            idempotency_key="idem-1",
            correlation_id="corr-1",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            requested_quantity=Decimal("10"),
            status=OrderStatus.FILLED,
            trade_decision_id=target_trade_decision_id,
            time_in_force=TimeInForce.DAY,
            created_at=now,
            updated_at=now,
            version=1,
        ),
        OrderRequestEntity(
            order_request_id=other_order_request_id,
            account_id=account_id,
            instrument_id=uuid.uuid4(),
            client_order_id="client-2",
            idempotency_key="idem-2",
            correlation_id="corr-2",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            requested_quantity=Decimal("1"),
            status=OrderStatus.FILLED,
            trade_decision_id=other_trade_decision_id,
            time_in_force=TimeInForce.DAY,
            created_at=now,
            updated_at=now,
            version=1,
        ),
    ):
        asyncio.run(repos.orders.add(order))
    for snapshot in (
        BrokerFillSnapshotEntity(
            broker_fill_snapshot_id=uuid.uuid4(),
            fill_sync_run_id=uuid.uuid4(),
            account_id=account_id,
            order_request_id=target_order_request_id,
            broker_name="koreainvestment",
            broker_native_order_id="0001111111",
            broker_fill_id="CCLD-1",
            symbol="005930",
            side="buy",
            order_date=date(2026, 6, 2),
            order_status_code="22",
            ordered_quantity=Decimal("10"),
            filled_quantity=Decimal("10"),
            fill_price=Decimal("71200"),
            order_time="091500",
            fill_time="091501",
            fill_timestamp=datetime.now(timezone.utc),
            dedupe_key="dedupe-1",
            raw_payload_json={},
        ),
        BrokerFillSnapshotEntity(
            broker_fill_snapshot_id=uuid.uuid4(),
            fill_sync_run_id=uuid.uuid4(),
            account_id=account_id,
            order_request_id=other_order_request_id,
            broker_name="koreainvestment",
            broker_native_order_id="0002222222",
            broker_fill_id="CCLD-2",
            symbol="000660",
            side="buy",
            order_date=date(2026, 6, 2),
            order_status_code="22",
            ordered_quantity=Decimal("1"),
            filled_quantity=Decimal("1"),
            fill_price=Decimal("150000"),
            order_time="091502",
            fill_time="091503",
            fill_timestamp=datetime.now(timezone.utc),
            dedupe_key="dedupe-2",
            raw_payload_json={},
        ),
    ):
        asyncio.run(repos.broker_fill_snapshots.upsert(snapshot))

    with TestClient(app) as client:
        resp_by_order = client.get(
            f"/fill-history?date=2026-06-02&order_request_id={target_order_request_id}",
            headers={"Authorization": "Bearer test-token"},
        )
        resp_by_symbol = client.get(
            "/fill-history?date=2026-06-02&symbol=000660",
            headers={"Authorization": "Bearer test-token"},
        )
        resp_by_odno = client.get(
            "/fill-history?date=2026-06-02&broker_native_order_id=0001111111",
            headers={"Authorization": "Bearer test-token"},
        )
        resp_by_trade_decision = client.get(
            f"/fill-history?date=2026-06-02&trade_decision_id={target_trade_decision_id}",
            headers={"Authorization": "Bearer test-token"},
        )

    assert resp_by_order.status_code == 200
    assert len(resp_by_order.json()) == 1
    assert resp_by_order.json()[0]["order_request_id"] == str(target_order_request_id)
    assert resp_by_order.json()[0]["trade_decision_id"] == str(target_trade_decision_id)

    assert resp_by_symbol.status_code == 200
    assert len(resp_by_symbol.json()) == 1
    assert resp_by_symbol.json()[0]["symbol"] == "000660"

    assert resp_by_odno.status_code == 200
    assert len(resp_by_odno.json()) == 1
    assert resp_by_odno.json()[0]["broker_native_order_id"] == "0001111111"

    assert resp_by_trade_decision.status_code == 200
    assert len(resp_by_trade_decision.json()) == 1
    assert resp_by_trade_decision.json()[0]["trade_decision_id"] == str(
        target_trade_decision_id
    )


def test_list_fill_sync_runs_and_summary() -> None:
    repos = build_in_memory_repositories()
    app = create_app(auth_token="test-token")
    app.dependency_overrides[get_repos] = lambda: repos

    run = FillSyncRunEntity(
        fill_sync_run_id=uuid.uuid4(),
        trigger_type="scheduler",
        scope="all",
        dry_run=False,
        total_accounts=1,
        succeeded_accounts=1,
        partial_accounts=0,
        failed_accounts=0,
        skipped_accounts=0,
        fills_synced_total=3,
        fills_skipped_total=0,
        error_count=0,
        status="completed",
        started_at=datetime.now(timezone.utc),
        env_filter="paper",
        summary_json={"pages": 1, "retried_accounts": 1, "retried_days": 2, "total_retries": 3},
        completed_at=datetime.now(timezone.utc),
    )
    asyncio.run(repos.fill_sync_runs.add(run))

    with TestClient(app) as client:
        list_resp = client.get("/fill-sync-runs", headers={"Authorization": "Bearer test-token"})
        summary_resp = client.get("/fill-sync-runs/summary", headers={"Authorization": "Bearer test-token"})
    assert list_resp.status_code == 200
    assert list_resp.json()[0]["fills_synced_total"] == 3
    assert summary_resp.status_code == 200
    assert summary_resp.json()["last_status"] == "completed"
    assert summary_resp.json()["retried_accounts"] == 1
    assert summary_resp.json()["retried_days"] == 2
    assert summary_resp.json()["total_retries"] == 3
