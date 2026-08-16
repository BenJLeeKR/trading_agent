"""Tests for ``scripts.apply_historical_sell_fee_tax_overlay`` — `007070` 파일럿.

검증 범위
---------
1. ``parse_args()`` — 기본값이 항상 dry-run인지
2. ``run()`` — in-memory repository 기반:
   - dry-run: 계산 결과만 출력하고 overlay/recompute_queue에 아무것도 안 씀
   - apply: overlay 1건 + recompute_queue 1건만 append, fill_events 원본은 불변
   - 활성 정책이 없으면 apply/dry-run 모두 거부
   - 이미 overlay가 있는 fill에는 중복 등록 거부
   - 아직 realized_pnl_events가 없는 fill(한 번도 recompute 안 된 SELL)에는 거부
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
    HistoricalSellFeeTaxOverlayEntity,
    InstrumentEntity,
    OrderRequestEntity,
    RealizedPnlEventEntity,
)
from agent_trading.domain.enums import (
    Environment,
    OrderSide,
    OrderStatus,
    OrderType,
    RealizedPnlFeeTaxSource,
    TimeInForce,
)
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer
from scripts.apply_historical_sell_fee_tax_overlay import parse_args, run

_KST = timezone(timedelta(hours=9))


def _dt(s: str) -> datetime:
    naive = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    return naive.replace(tzinfo=_KST).astimezone(timezone.utc)


@pytest.fixture
def repos() -> RepositoryContainer:
    return build_in_memory_repositories()


async def _seed_007070_sell1(repos: RepositoryContainer, *, already_recomputed: bool = True):
    """`007070` 실제 이력의 SELL1(88주) fill과, 이미 한 번 recompute를 거쳐
    확정된 ``realized_pnl_events`` 행을 재현한다(overlay 대상 전제조건)."""
    account_id = uuid4()
    instrument_id = uuid4()
    client_id = uuid4()

    account = AccountEntity(
        account_id=account_id, client_id=client_id, broker_account_id=uuid4(),
        environment=Environment.PAPER, account_alias="007070-sell-overlay-test",
        account_masked="test-masked", status="active",
    )
    repos.accounts._items[account_id] = account  # type: ignore[attr-defined]
    instrument = InstrumentEntity(
        instrument_id=instrument_id, symbol="007070", market_code="KRX",
        asset_class="kr_stock", currency="KRW", name="테스트종목",
        market_segment="KOSPI",
    )
    repos.instruments._items[instrument_id] = instrument  # type: ignore[attr-defined]

    # 선행 BUY fill(176주) — `_simulate_full_recompute()`는 계좌×종목 전체를
    # replay하므로, 직전 보유 상태 없이 SELL만 있으면 MissingCostBasisStateError가
    # 난다. 007070 실제 이력과 동일하게 BUY 176주를 먼저 시드한다.
    buy_order = OrderRequestEntity(
        order_request_id=uuid4(), account_id=account_id, instrument_id=instrument_id,
        client_order_id=f"client-{uuid4()}", idempotency_key=f"idem-{uuid4()}",
        correlation_id=f"corr-{uuid4()}", side=OrderSide.BUY, order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY, requested_quantity=Decimal("176"),
        status=OrderStatus.FILLED, created_at=_dt("2026-08-10 08:58:36"),
        updated_at=_dt("2026-08-10 08:58:36"),
    )
    await repos.orders.add(buy_order)
    buy_broker_order = BrokerOrderEntity(
        broker_order_id=uuid4(), order_request_id=buy_order.order_request_id,
        broker_name="koreainvestment", broker_native_order_id="0000000871",
        broker_status="filled",
    )
    await repos.broker_orders.add(buy_broker_order)
    buy_fill = FillEventEntity(
        fill_event_id=uuid4(), broker_order_id=buy_broker_order.broker_order_id,
        fill_timestamp=_dt("2026-08-10 08:58:37"), fill_price=Decimal("28000"),
        fill_quantity=Decimal("176"), source_channel="backfill",
    )
    await repos.fill_events.add(buy_fill)

    order = OrderRequestEntity(
        order_request_id=uuid4(), account_id=account_id, instrument_id=instrument_id,
        client_order_id=f"client-{uuid4()}", idempotency_key=f"idem-{uuid4()}",
        correlation_id=f"corr-{uuid4()}", side=OrderSide.SELL, order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY, requested_quantity=Decimal("88"),
        status=OrderStatus.FILLED, created_at=_dt("2026-08-13 08:52:16"),
        updated_at=_dt("2026-08-13 08:52:16"),
    )
    await repos.orders.add(order)
    broker_order = BrokerOrderEntity(
        broker_order_id=uuid4(), order_request_id=order.order_request_id,
        broker_name="koreainvestment", broker_native_order_id="0000000872",
        broker_status="filled",
    )
    await repos.broker_orders.add(broker_order)
    fill = FillEventEntity(
        fill_event_id=uuid4(), broker_order_id=broker_order.broker_order_id,
        fill_timestamp=_dt("2026-08-13 08:52:17"), fill_price=Decimal("26800"),
        fill_quantity=Decimal("88"), source_channel="backfill",
    )
    await repos.fill_events.add(fill)

    if already_recomputed:
        existing_event = RealizedPnlEventEntity(
            realized_pnl_event_id=uuid4(),
            account_id=account_id,
            instrument_id=instrument_id,
            fill_event_id=fill.fill_event_id,
            broker_order_id=broker_order.broker_order_id,
            order_request_id=order.order_request_id,
            sell_quantity=Decimal("88"),
            sell_price=Decimal("26800"),
            avg_cost_basis_before=Decimal("28000"),
            fee=Decimal("0"),
            tax=Decimal("0"),
            fee_tax_source=RealizedPnlFeeTaxSource.ASSUMED_ZERO,
            realized_pnl_gross=Decimal("-105600"),
            realized_pnl_net=Decimal("-105946.5"),
            position_quantity_after=Decimal("88"),
            computation_run_id=uuid4(),
            fill_timestamp=fill.fill_timestamp,
            allocated_buy_fee=Decimal("346.5"),
        )
        await repos.realized_pnl_events.add(existing_event)

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
    account_id, instrument_id, broker_order_id, fill_event_id, client_id = await _seed_007070_sell1(repos)
    await _seed_policy(repos, client_id=client_id)

    args = parse_args(
        [
            "--account-id", str(account_id), "--instrument-id", str(instrument_id),
            "--broker-order-id", str(broker_order_id), "--fill-event-id", str(fill_event_id),
            "--reason", "007070 파일럿 — SELL fee/tax", "--created-by", "tester",
        ]
    )
    exit_code = await run(repos, args)

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "이미 recompute를 통해 realized_pnl_net이 한 번 확정된 SELL" in captured.out
    overlay = await repos.historical_sell_fee_tax_overlays.get_by_fill_event_id(fill_event_id)
    assert overlay is None  # dry-run이므로 아무것도 안 씀
    all_queue_items = list(repos.realized_pnl_recompute_queue._items.values())  # type: ignore[attr-defined]
    assert all_queue_items == []


@pytest.mark.asyncio
async def test_apply_appends_overlay_and_registers_recompute(repos):
    account_id, instrument_id, broker_order_id, fill_event_id, client_id = await _seed_007070_sell1(repos)
    await _seed_policy(repos, client_id=client_id)

    args = parse_args(
        [
            "--account-id", str(account_id), "--instrument-id", str(instrument_id),
            "--broker-order-id", str(broker_order_id), "--fill-event-id", str(fill_event_id),
            "--reason", "007070 파일럿 — SELL fee/tax", "--created-by", "tester",
            "--mode", "apply",
        ]
    )
    exit_code = await run(repos, args)

    assert exit_code == 0
    overlay = await repos.historical_sell_fee_tax_overlays.get_by_fill_event_id(fill_event_id)
    assert overlay is not None
    assert overlay.fee_tax_source == "historical_policy_estimate"
    assert overlay.reason == "007070 파일럿 — SELL fee/tax"
    assert overlay.created_by == "tester"
    assert overlay.estimated_fee >= Decimal("0")
    assert overlay.estimated_tax >= Decimal("0")

    # fill_events 원본은 여전히 그대로다.
    fills = await repos.fill_events.list_by_broker_order(broker_order_id)
    assert fills[0].fill_fee is None
    assert fills[0].fill_tax is None
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
    account_id, instrument_id, broker_order_id, fill_event_id, _client_id = await _seed_007070_sell1(repos)
    # 정책을 등록하지 않는다.

    args = parse_args(
        [
            "--account-id", str(account_id), "--instrument-id", str(instrument_id),
            "--broker-order-id", str(broker_order_id), "--fill-event-id", str(fill_event_id),
            "--reason", "007070 파일럿 — SELL fee/tax", "--created-by", "tester",
        ]
    )
    exit_code = await run(repos, args)

    assert exit_code == 1
    overlay = await repos.historical_sell_fee_tax_overlays.get_by_fill_event_id(fill_event_id)
    assert overlay is None


@pytest.mark.asyncio
async def test_rejects_duplicate_overlay(repos):
    account_id, instrument_id, broker_order_id, fill_event_id, client_id = await _seed_007070_sell1(repos)
    await _seed_policy(repos, client_id=client_id)

    existing = HistoricalSellFeeTaxOverlayEntity(
        overlay_id=uuid4(), fill_event_id=fill_event_id, estimated_fee=Decimal("331"),
        estimated_tax=Decimal("4717"), fee_tax_source="historical_policy_estimate",
        basis_config_version_id=uuid4(), reason="already registered", created_by="someone",
    )
    await repos.historical_sell_fee_tax_overlays.add(existing)

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


@pytest.mark.asyncio
async def test_rejects_when_never_recomputed(repos):
    """이 fill이 한 번도 recompute를 거쳐 realized_pnl_events에 기록된 적이
    없으면 거부한다 — 이 스크립트는 '이미 확정된 SELL을 재해석'하는 용도이며
    신규 계산 스크립트가 아니다."""
    account_id, instrument_id, broker_order_id, fill_event_id, client_id = await _seed_007070_sell1(
        repos, already_recomputed=False
    )
    await _seed_policy(repos, client_id=client_id)

    args = parse_args(
        [
            "--account-id", str(account_id), "--instrument-id", str(instrument_id),
            "--broker-order-id", str(broker_order_id), "--fill-event-id", str(fill_event_id),
            "--reason", "007070 파일럿 — SELL fee/tax", "--created-by", "tester",
        ]
    )
    exit_code = await run(repos, args)

    assert exit_code == 1
    overlay = await repos.historical_sell_fee_tax_overlays.get_by_fill_event_id(fill_event_id)
    assert overlay is None
