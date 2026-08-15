"""Tests for ``scripts.apply_historical_buy_fee_overlay`` — `007070` 파일럿.

검증 범위
---------
1. ``parse_args()`` — 기본값이 항상 dry-run인지
2. ``run()`` — in-memory repository 기반:
   - dry-run: 계산 결과만 출력하고 overlay/recompute_queue에 아무것도 안 씀
   - apply: overlay 1건 + recompute_queue 1건만 append, fill_events 원본은 불변
   - 활성 정책이 없으면 apply/dry-run 모두 거부
   - 이미 overlay가 있는 fill에는 중복 등록 거부
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from agent_trading.domain.entities import (
    AccountEntity,
    BrokerOrderEntity,
    ConfigVersionEntity,
    FillEventEntity,
    HistoricalBuyFeeOverlayEntity,
    InstrumentEntity,
    OrderRequestEntity,
)
from agent_trading.domain.enums import Environment, OrderSide, OrderStatus, OrderType, TimeInForce
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer
from scripts.apply_historical_buy_fee_overlay import parse_args, run

_KST = timezone(timedelta(hours=9))


def _dt(s: str) -> datetime:
    naive = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    return naive.replace(tzinfo=_KST).astimezone(timezone.utc)


@pytest.fixture
def repos() -> RepositoryContainer:
    return build_in_memory_repositories()


async def _seed_007070_buy(repos: RepositoryContainer):
    """`007070` 실제 이력의 BUY 176주만 재현한다(overlay 대상)."""
    account_id = uuid4()
    instrument_id = uuid4()
    client_id = uuid4()

    account = AccountEntity(
        account_id=account_id, client_id=client_id, broker_account_id=uuid4(),
        environment=Environment.PAPER, account_alias="007070-overlay-test",
        account_masked="test-masked", status="active",
    )
    repos.accounts._items[account_id] = account  # type: ignore[attr-defined]
    instrument = InstrumentEntity(
        instrument_id=instrument_id, symbol="007070", market_code="KRX",
        asset_class="kr_stock", currency="KRW", name="테스트종목",
        market_segment="KOSPI",
    )
    repos.instruments._items[instrument_id] = instrument  # type: ignore[attr-defined]

    order = OrderRequestEntity(
        order_request_id=uuid4(), account_id=account_id, instrument_id=instrument_id,
        client_order_id=f"client-{uuid4()}", idempotency_key=f"idem-{uuid4()}",
        correlation_id=f"corr-{uuid4()}", side=OrderSide.BUY, order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY, requested_quantity=Decimal("176"),
        status=OrderStatus.FILLED, created_at=_dt("2026-08-10 08:58:36"),
        updated_at=_dt("2026-08-10 08:58:36"),
    )
    await repos.orders.add(order)
    broker_order = BrokerOrderEntity(
        broker_order_id=uuid4(), order_request_id=order.order_request_id,
        broker_name="koreainvestment", broker_native_order_id="0000000871",
        broker_status="filled",
    )
    await repos.broker_orders.add(broker_order)
    fill = FillEventEntity(
        fill_event_id=uuid4(), broker_order_id=broker_order.broker_order_id,
        fill_timestamp=_dt("2026-08-10 08:58:37"), fill_price=Decimal("28000"),
        fill_quantity=Decimal("176"), source_channel="backfill",
    )
    await repos.fill_events.add(fill)
    return account_id, instrument_id, broker_order.broker_order_id, fill.fill_event_id, client_id


async def _seed_policy(repos, *, client_id, activated_at=None):
    version = ConfigVersionEntity(
        config_version_id=uuid4(), client_id=client_id, environment=Environment.PAPER,
        version_tag="test",
        config_json={
            "execution": {
                "fee_tax": {
                    "enabled": True,
                    "supported_asset_classes": ["kr_stock"],
                    "supported_market_segments": ["KOSPI", "KOSDAQ"],
                    "buy_commission_rate_pct": "0.0140527",
                    "sell_commission_rate_pct": "0.0140527",
                    "sell_tax_rate_pct": "0.20",
                    "sell_agri_tax_rate_pct": "0.00",
                    "rounding_mode": "round_half_up",
                    "rounding_unit": "1",
                }
            }
        },
        checksum="test",
        activated_at=activated_at or (datetime.now(timezone.utc) - timedelta(days=1)),
    )
    await repos.config_versions.add(version)
    return version


class TestParseArgs:
    def test_defaults_are_dry_run(self):
        args = parse_args(
            [
                "--account-id", str(uuid4()), "--instrument-id", str(uuid4()),
                "--broker-order-id", str(uuid4()), "--fill-event-id", str(uuid4()),
                "--reason", "test", "--created-by", "tester",
            ]
        )
        assert args.mode == "dry-run"


@pytest.mark.asyncio
async def test_dry_run_never_writes(repos, capsys):
    account_id, instrument_id, broker_order_id, fill_event_id, client_id = await _seed_007070_buy(repos)
    await _seed_policy(repos, client_id=client_id)

    args = parse_args(
        [
            "--account-id", str(account_id), "--instrument-id", str(instrument_id),
            "--broker-order-id", str(broker_order_id), "--fill-event-id", str(fill_event_id),
            "--reason", "007070 파일럿", "--created-by", "tester",
        ]
    )
    exit_code = await run(repos, args)

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "추정 BUY fee(historical_policy_estimate): 693" in captured.out
    overlay = await repos.historical_buy_fee_overlays.get_by_fill_event_id(fill_event_id)
    assert overlay is None  # dry-run이므로 아무것도 안 씀
    all_queue_items = list(repos.realized_pnl_recompute_queue._items.values())  # type: ignore[attr-defined]
    assert all_queue_items == []


@pytest.mark.asyncio
async def test_apply_appends_overlay_and_registers_recompute(repos):
    account_id, instrument_id, broker_order_id, fill_event_id, client_id = await _seed_007070_buy(repos)
    await _seed_policy(repos, client_id=client_id)

    args = parse_args(
        [
            "--account-id", str(account_id), "--instrument-id", str(instrument_id),
            "--broker-order-id", str(broker_order_id), "--fill-event-id", str(fill_event_id),
            "--reason", "007070 파일럿", "--created-by", "tester",
            "--mode", "apply",
        ]
    )
    exit_code = await run(repos, args)

    assert exit_code == 0
    overlay = await repos.historical_buy_fee_overlays.get_by_fill_event_id(fill_event_id)
    assert overlay is not None
    assert overlay.estimated_fee == Decimal("693")
    assert overlay.fee_tax_source == "historical_policy_estimate"
    assert overlay.reason == "007070 파일럿"
    assert overlay.created_by == "tester"

    # fill_events 원본은 여전히 그대로다.
    fills = await repos.fill_events.list_by_broker_order(broker_order_id)
    assert fills[0].fill_fee is None
    assert fills[0].fee_tax_source is None

    queue_items = [
        item for item in repos.realized_pnl_recompute_queue._items.values()  # type: ignore[attr-defined]
        if item.instrument_id == instrument_id
    ]
    assert len(queue_items) == 1
    assert queue_items[0].reason_code == "manual_request"
    assert queue_items[0].resolved_at is None


@pytest.mark.asyncio
async def test_rejects_when_no_active_policy(repos):
    account_id, instrument_id, broker_order_id, fill_event_id, _client_id = await _seed_007070_buy(repos)
    # 정책을 등록하지 않는다.

    args = parse_args(
        [
            "--account-id", str(account_id), "--instrument-id", str(instrument_id),
            "--broker-order-id", str(broker_order_id), "--fill-event-id", str(fill_event_id),
            "--reason", "007070 파일럿", "--created-by", "tester",
        ]
    )
    exit_code = await run(repos, args)

    assert exit_code == 1
    overlay = await repos.historical_buy_fee_overlays.get_by_fill_event_id(fill_event_id)
    assert overlay is None


@pytest.mark.asyncio
async def test_rejects_duplicate_overlay(repos):
    account_id, instrument_id, broker_order_id, fill_event_id, client_id = await _seed_007070_buy(repos)
    await _seed_policy(repos, client_id=client_id)

    existing = HistoricalBuyFeeOverlayEntity(
        overlay_id=uuid4(), fill_event_id=fill_event_id, estimated_fee=Decimal("693"),
        fee_tax_source="historical_policy_estimate",
        basis_config_version_id=uuid4(), reason="already registered", created_by="someone",
    )
    await repos.historical_buy_fee_overlays.add(existing)

    args = parse_args(
        [
            "--account-id", str(account_id), "--instrument-id", str(instrument_id),
            "--broker-order-id", str(broker_order_id), "--fill-event-id", str(fill_event_id),
            "--reason", "재시도", "--created-by", "tester", "--mode", "apply",
        ]
    )
    exit_code = await run(repos, args)

    assert exit_code == 1
    queue_items = list(repos.realized_pnl_recompute_queue._items.values())  # type: ignore[attr-defined]
    assert queue_items == []
