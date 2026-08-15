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
    AccountEntity,
    BrokerFillSnapshotEntity,
    BrokerOrderEntity,
    ConfigVersionEntity,
    InstrumentEntity,
    OrderRequestEntity,
    PositionSnapshotEntity,
)
from agent_trading.domain.enums import Environment, OrderSide, OrderStatus, OrderType, TimeInForce
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


async def _seed_policy_activated_after_buy(repos: RepositoryContainer, account_id, instrument_id) -> None:
    """이 계좌×종목에 대해, BUY(2026-08-05 09:00 KST)보다 나중(2026-08-14)에
    활성화되는 execution.fee_tax 정책을 심는다 — `001450`/`004370` 파일럿의
    실제 시간 관계(정책이 BUY보다 나중에 등록됨) 재현."""
    client_id = uuid4()
    account = AccountEntity(
        account_id=account_id, client_id=client_id, broker_account_id=uuid4(),
        environment=Environment.PAPER, account_alias="cli-historical-estimate-test",
        account_masked="test-masked", status="active",
    )
    repos.accounts._items[account_id] = account  # type: ignore[attr-defined]
    instrument = InstrumentEntity(
        instrument_id=instrument_id, symbol="007070", market_code="KRX",
        asset_class="kr_stock", currency="KRW", name="테스트종목",
        market_segment="KOSPI",
    )
    repos.instruments._items[instrument_id] = instrument  # type: ignore[attr-defined]
    version = ConfigVersionEntity(
        config_version_id=uuid4(), client_id=client_id, environment=Environment.PAPER,
        version_tag="test",
        config_json={
            "execution": {
                "fee_tax": {
                    "enabled": True,
                    "supported_asset_classes": ["kr_stock"],
                    "supported_market_segments": ["KOSPI", "KOSDAQ"],
                    "buy_commission_rate_pct": "0.015",
                    "sell_commission_rate_pct": "0.015",
                    "sell_tax_rate_pct": "0.18",
                    "sell_agri_tax_rate_pct": "0.02",
                    "rounding_mode": "round_half_up",
                    "rounding_unit": "1",
                }
            }
        },
        checksum="test", activated_at=_dt("2026-08-14 15:50:11"),
    )
    await repos.config_versions.add(version)


class TestParseArgs:
    def test_defaults_are_dry_run(self):
        """플래그를 명시하지 않으면 항상 dry-run이어야 한다 — 안전장치."""
        args = parse_args(
            ["--account-id", str(uuid4()), "--instrument-id", str(uuid4()), "--start-date", "2026-08-01"]
        )
        assert args.mode == "dry-run"
        assert args.verbose is False
        assert args.use_historical_policy_estimate_for_buy_fee is False

    def test_historical_policy_estimate_flag_default_false(self):
        args = parse_args(
            ["--account-id", str(uuid4()), "--instrument-id", str(uuid4()), "--start-date", "2026-08-01"]
        )
        assert args.use_historical_policy_estimate_for_buy_fee is False

    def test_historical_policy_estimate_flag_can_be_enabled(self):
        args = parse_args(
            [
                "--account-id", str(uuid4()), "--instrument-id", str(uuid4()),
                "--start-date", "2026-08-01",
                "--use-historical-policy-estimate-for-buy-fee",
            ]
        )
        assert args.use_historical_policy_estimate_for_buy_fee is True

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
async def test_historical_policy_estimate_flag_off_keeps_assumed_zero(repos):
    """플래그 없음(기본값) → 정책 활성 이전 BUY는 기존대로 assumed_zero."""
    account_id = uuid4()
    instrument_id = uuid4()
    _seed_eligible_candidate(repos, account_id, instrument_id)
    await _seed_policy_activated_after_buy(repos, account_id, instrument_id)

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
    assert all_fill_events[0].fee_tax_source == "assumed_zero"


@pytest.mark.asyncio
async def test_historical_policy_estimate_flag_on_overrides_buy_fee(repos, capsys):
    """플래그 있음 → historical_policy_estimate로 override되고, dry-run
    리포트에도 그 사실이 [HISTORICAL_POLICY_ESTIMATE] 마커로 드러난다."""
    account_id = uuid4()
    instrument_id = uuid4()
    _seed_eligible_candidate(repos, account_id, instrument_id)
    await _seed_policy_activated_after_buy(repos, account_id, instrument_id)

    args = parse_args(
        [
            "--account-id", str(account_id),
            "--instrument-id", str(instrument_id),
            "--start-date", "2026-08-01",
            "--use-historical-policy-estimate-for-buy-fee",
        ]
    )
    exit_code = await run_backfill(repos, args)

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "fee_tax_source=historical_policy_estimate" in captured.out
    assert "[HISTORICAL_POLICY_ESTIMATE]" in captured.out
    assert "historical_policy_estimate로 override된 fill 수: 1" in captured.out
    # dry-run이므로 여전히 아무것도 쓰지 않는다.
    all_fill_events = list(repos.fill_events._items.values())  # type: ignore[attr-defined]
    assert all_fill_events == []


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


@pytest.mark.asyncio
async def test_dry_run_report_shows_initial_entry_anchor_type(repos, capsys):
    """window_start 이전 filled 주문이 전혀 없는 종목은 zero-crossing
    스냅샷 없이도 eligible=True가 되고, dry-run 리포트에 anchor_type:
    initial_entry가 그대로 드러나야 한다."""
    account_id = uuid4()
    instrument_id = uuid4()

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
        broker_native_order_id="9000000123",
        broker_status="filled",
    )
    repos.broker_orders._items[broker_order.broker_order_id] = broker_order  # type: ignore[attr-defined]

    snapshot = BrokerFillSnapshotEntity(
        broker_fill_snapshot_id=uuid4(),
        account_id=account_id,
        broker_name="koreainvestment",
        broker_native_order_id="9000000123",
        symbol="009240",
        side="buy",
        order_date=_dt("2026-08-05 09:05:00").date(),
        filled_quantity=Decimal("10"),
        fill_price=Decimal("2000"),
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
    # position_snapshots에 zero-crossing 관측을 전혀 심지 않는다.

    args = parse_args(
        [
            "--account-id", str(account_id),
            "--instrument-id", str(instrument_id),
            "--start-date", "2026-08-01",
        ]
    )
    exit_code = await run_backfill(repos, args)

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "eligible:            True" in captured.out
    assert "anchor_type:         initial_entry" in captured.out
    assert "zero_crossing_at:    None" in captured.out
    all_fill_events = list(repos.fill_events._items.values())  # type: ignore[attr-defined]
    assert all_fill_events == []  # dry-run — 여전히 아무것도 쓰지 않음
