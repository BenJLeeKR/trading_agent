"""Tests for ``scripts.backfill_broker_fill_snapshot_historical_fills``.

검증 범위
---------
1. ``parse_args()`` — CLI 인자 파싱 정확성(기본값이 항상 dry-run인지 포함)
2. ``run_backfill()`` — in-memory repository 기반:
   - dry-run 모드: eligible한 대상도 DB에 아무것도 쓰지 않음
   - apply 모드: eligible한 대상만 실제 append, exit_code=0
   - eligible=False 대상: apply 모드에서도 아무것도 쓰지 않고 exit_code=1
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from agent_trading.domain.entities import (
    BrokerFillSnapshotEntity,
    BrokerOrderEntity,
    OrderRequestEntity,
    PositionSnapshotEntity,
)
from agent_trading.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer
from scripts.backfill_broker_fill_snapshot_historical_fills import parse_args, run_backfill

_KST = timezone(timedelta(hours=9))


def _dt(s: str) -> datetime:
    naive = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    return naive.replace(tzinfo=_KST).astimezone(timezone.utc)


@pytest.fixture
def repos() -> RepositoryContainer:
    return build_in_memory_repositories()


def _seed_eligible_candidate(repos: RepositoryContainer, account_id, instrument_id) -> None:
    repos.position_snapshots._items[uuid4()] = PositionSnapshotEntity(  # type: ignore[attr-defined]
        position_snapshot_id=uuid4(),
        account_id=account_id,
        instrument_id=instrument_id,
        quantity=Decimal("0"),
        average_price=Decimal("0"),
        market_price=None,
        unrealized_pnl=None,
        source_of_truth="broker",
        snapshot_at=_dt("2026-06-18 12:00:00"),
    )

    order = OrderRequestEntity(
        order_request_id=uuid4(),
        account_id=account_id,
        instrument_id=instrument_id,
        client_order_id=f"client-{uuid4()}",
        idempotency_key=f"idem-{uuid4()}",
        correlation_id=f"corr-{uuid4()}",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        requested_quantity=Decimal("10"),
        status=OrderStatus.FILLED,
        created_at=_dt("2026-08-05 09:00:00"),
        updated_at=_dt("2026-08-05 09:00:00"),
    )
    repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

    broker_order = BrokerOrderEntity(
        broker_order_id=uuid4(),
        order_request_id=order.order_request_id,
        broker_name="koreainvestment",
        broker_native_order_id="1234567890",
        broker_status="filled",
    )
    repos.broker_orders._items[broker_order.broker_order_id] = broker_order  # type: ignore[attr-defined]

    snapshot = BrokerFillSnapshotEntity(
        broker_fill_snapshot_id=uuid4(),
        account_id=account_id,
        broker_name="koreainvestment",
        broker_native_order_id="1234567890",
        symbol="007070",
        side="buy",
        order_date=_dt("2026-08-05 09:05:00").date(),
        filled_quantity=Decimal("10"),
        fill_price=Decimal("1000"),
        dedupe_key=f"dedupe-{uuid4()}",
        order_request_id=order.order_request_id,
        ordered_quantity=Decimal("10"),
        fill_timestamp=_dt("2026-08-05 09:05:00"),
        updated_at=_dt("2026-08-05 09:05:00"),
    )
    repos.broker_fill_snapshots._items[snapshot.broker_fill_snapshot_id] = snapshot  # type: ignore[attr-defined]
    repos.broker_fill_snapshots._by_dedupe_key[snapshot.dedupe_key] = (  # type: ignore[attr-defined]
        snapshot.broker_fill_snapshot_id
    )


class TestParseArgs:
    def test_defaults_are_dry_run(self):
        """플래그를 명시하지 않으면 항상 dry-run이어야 한다 — 안전장치."""
        args = parse_args(
            ["--account-id", str(uuid4()), "--instrument-id", str(uuid4()), "--start-date", "2026-08-01"]
        )
        assert args.mode == "dry-run"
        assert args.verbose is False

    def test_apply_requires_explicit_mode(self):
        args = parse_args(
            [
                "--account-id", str(uuid4()),
                "--instrument-id", str(uuid4()),
                "--start-date", "2026-08-01",
                "--mode", "apply",
            ]
        )
        assert args.mode == "apply"

    def test_invalid_mode_rejected(self):
        with pytest.raises(SystemExit):
            parse_args(
                [
                    "--account-id", str(uuid4()),
                    "--instrument-id", str(uuid4()),
                    "--start-date", "2026-08-01",
                    "--mode", "not-a-real-mode",
                ]
            )


@pytest.mark.asyncio
async def test_dry_run_never_writes(repos):
    account_id = uuid4()
    instrument_id = uuid4()
    _seed_eligible_candidate(repos, account_id, instrument_id)

    args = parse_args(
        [
            "--account-id", str(account_id),
            "--instrument-id", str(instrument_id),
            "--start-date", "2026-08-01",
        ]
    )
    exit_code = await run_backfill(repos, args)

    assert exit_code == 0
    all_fill_events = list(repos.fill_events._items.values())  # type: ignore[attr-defined]
    assert all_fill_events == []


@pytest.mark.asyncio
async def test_apply_writes_when_eligible(repos):
    account_id = uuid4()
    instrument_id = uuid4()
    _seed_eligible_candidate(repos, account_id, instrument_id)

    args = parse_args(
        [
            "--account-id", str(account_id),
            "--instrument-id", str(instrument_id),
            "--start-date", "2026-08-01",
            "--mode", "apply",
        ]
    )
    exit_code = await run_backfill(repos, args)

    assert exit_code == 0
    all_fill_events = list(repos.fill_events._items.values())  # type: ignore[attr-defined]
    assert len(all_fill_events) == 1
    assert all_fill_events[0].source_channel == "backfill"


@pytest.mark.asyncio
async def test_apply_is_noop_when_not_eligible(repos):
    account_id = uuid4()
    instrument_id = uuid4()
    # position_snapshots에 zero-crossing 없음 → not eligible

    order = OrderRequestEntity(
        order_request_id=uuid4(),
        account_id=account_id,
        instrument_id=instrument_id,
        client_order_id=f"client-{uuid4()}",
        idempotency_key=f"idem-{uuid4()}",
        correlation_id=f"corr-{uuid4()}",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        requested_quantity=Decimal("5"),
        status=OrderStatus.FILLED,
        created_at=_dt("2026-08-05 09:00:00"),
        updated_at=_dt("2026-08-05 09:00:00"),
    )
    repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]

    args = parse_args(
        [
            "--account-id", str(account_id),
            "--instrument-id", str(instrument_id),
            "--start-date", "2026-08-01",
            "--mode", "apply",
        ]
    )
    exit_code = await run_backfill(repos, args)

    assert exit_code == 1
    all_fill_events = list(repos.fill_events._items.values())  # type: ignore[attr-defined]
    assert all_fill_events == []
