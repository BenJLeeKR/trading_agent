"""단위 테스트: broker_fill_snapshots 기반 historical backfill.

설계 근거: docs/00_foundational_design/detailed_design/16_broker_fill_
snapshot_historical_backfill_design.md

이 테스트는 in-memory repository만 사용한다 — DB 연결/네트워크 없음.
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
from agent_trading.services.historical_fill_backfill import (
    BackfillExclusionReason,
    apply_backfill_plan,
    build_backfill_plan,
)

_KST = timezone(timedelta(hours=9))


def _dt(s: str) -> datetime:
    """``"2026-08-10 08:58:00"`` (KST) → aware UTC datetime."""
    naive = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    return naive.replace(tzinfo=_KST).astimezone(timezone.utc)


def _make_order(
    *, account_id, instrument_id, side, requested_quantity, created_at
) -> OrderRequestEntity:
    return OrderRequestEntity(
        order_request_id=uuid4(),
        account_id=account_id,
        instrument_id=instrument_id,
        client_order_id=f"client-{uuid4()}",
        idempotency_key=f"idem-{uuid4()}",
        correlation_id=f"corr-{uuid4()}",
        side=side,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        requested_quantity=requested_quantity,
        status=OrderStatus.FILLED,
        created_at=created_at,
        updated_at=created_at,
    )


def _make_broker_order(order: OrderRequestEntity, native_id: str) -> BrokerOrderEntity:
    return BrokerOrderEntity(
        broker_order_id=uuid4(),
        order_request_id=order.order_request_id,
        broker_name="koreainvestment",
        broker_native_order_id=native_id,
        broker_status="filled",
    )


def _make_snapshot(
    *,
    account_id,
    order: OrderRequestEntity,
    native_id: str,
    filled_quantity: Decimal,
    fill_price: Decimal,
    updated_at: datetime,
    cancel_yn: str | None = None,
) -> BrokerFillSnapshotEntity:
    return BrokerFillSnapshotEntity(
        broker_fill_snapshot_id=uuid4(),
        account_id=account_id,
        broker_name="koreainvestment",
        broker_native_order_id=native_id,
        symbol="007070",
        side=order.side.value,
        order_date=updated_at.date(),
        filled_quantity=filled_quantity,
        fill_price=fill_price,
        dedupe_key=f"dedupe-{uuid4()}",
        order_request_id=order.order_request_id,
        ordered_quantity=order.requested_quantity,
        cancel_yn=cancel_yn,
        fill_timestamp=updated_at,
        updated_at=updated_at,
    )


def _make_position(
    *, account_id, instrument_id, quantity: Decimal, average_price: Decimal, snapshot_at
) -> PositionSnapshotEntity:
    return PositionSnapshotEntity(
        position_snapshot_id=uuid4(),
        account_id=account_id,
        instrument_id=instrument_id,
        quantity=quantity,
        average_price=average_price,
        market_price=None,
        unrealized_pnl=None,
        source_of_truth="broker",
        snapshot_at=snapshot_at,
    )


@pytest.fixture
def repos():
    return build_in_memory_repositories()


class TestCleanCandidate:
    """조사에서 확인된 실제 사례(1 buy + 2 sell, 완전 청산 시작점 확인됨)를
    그대로 재현한다."""

    @pytest.mark.asyncio
    async def test_eligible_with_correct_synthetic_fills(self, repos):
        account_id = uuid4()
        instrument_id = uuid4()

        # 완전 청산 시작점: 2026-06-18 KST, quantity=0
        zero_anchor = _make_position(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=Decimal("0"),
            average_price=Decimal("0"),
            snapshot_at=_dt("2026-06-18 12:00:00"),
        )
        await repos.position_snapshots.add(zero_anchor)

        buy_order = _make_order(
            account_id=account_id,
            instrument_id=instrument_id,
            side=OrderSide.BUY,
            requested_quantity=Decimal("176"),
            created_at=_dt("2026-08-10 08:58:36"),
        )
        sell1 = _make_order(
            account_id=account_id,
            instrument_id=instrument_id,
            side=OrderSide.SELL,
            requested_quantity=Decimal("88"),
            created_at=_dt("2026-08-13 08:52:17"),
        )
        sell2 = _make_order(
            account_id=account_id,
            instrument_id=instrument_id,
            side=OrderSide.SELL,
            requested_quantity=Decimal("70"),
            created_at=_dt("2026-08-13 09:15:50"),
        )
        for order in (buy_order, sell1, sell2):
            await repos.orders.add(order)

        buy_broker_order = _make_broker_order(buy_order, "0000000871")
        sell1_broker_order = _make_broker_order(sell1, "0000000758")
        sell2_broker_order = _make_broker_order(sell2, "0000008019")
        for bo in (buy_broker_order, sell1_broker_order, sell2_broker_order):
            await repos.broker_orders.add(bo)

        # 매수: snapshot 1건, 완전체결 1회성
        await repos.broker_fill_snapshots.upsert(
            _make_snapshot(
                account_id=account_id,
                order=buy_order,
                native_id="0000000871",
                filled_quantity=Decimal("176"),
                fill_price=Decimal("28000"),
                updated_at=_dt("2026-08-10 09:01:05"),
            )
        )
        # 매도1: staircase 0→88 (설계 문서 §4.1 순서: updated_at 오름차순)
        await repos.broker_fill_snapshots.upsert(
            _make_snapshot(
                account_id=account_id,
                order=sell1,
                native_id="0000000758",
                filled_quantity=Decimal("0"),
                fill_price=Decimal("0"),
                updated_at=_dt("2026-08-13 08:54:49"),
            )
        )
        await repos.broker_fill_snapshots.upsert(
            _make_snapshot(
                account_id=account_id,
                order=sell1,
                native_id="0000000758",
                filled_quantity=Decimal("88"),
                fill_price=Decimal("26800"),
                updated_at=_dt("2026-08-13 15:42:50"),
            )
        )
        # 매도2: snapshot 1건, 완전체결
        await repos.broker_fill_snapshots.upsert(
            _make_snapshot(
                account_id=account_id,
                order=sell2,
                native_id="0000008019",
                filled_quantity=Decimal("70"),
                fill_price=Decimal("26650"),
                updated_at=_dt("2026-08-13 15:42:50"),
            )
        )

        # 현재 브로커 보고 잔량(정합성 교차 확인용)
        await repos.position_snapshots.add(
            _make_position(
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=Decimal("18"),
                average_price=Decimal("28000"),
                snapshot_at=_dt("2026-08-13 15:42:20"),
            )
        )

        plan = await build_backfill_plan(
            repos,
            account_id=account_id,
            instrument_id=instrument_id,
            start_date=date(2026, 8, 1),
        )

        assert plan.eligible is True
        assert plan.exclusion_reason is None
        assert len(plan.order_details) == 3
        assert len(plan.synthetic_fills) == 3  # buy(176) + sell(0→88=1건) + sell(70)
        assert plan.expected_final_quantity == Decimal("18")
        assert plan.broker_reported_quantity == Decimal("18")
        assert plan.broker_reported_quantity_matches is True

        buy_fill = next(f for f in plan.synthetic_fills if f.side == OrderSide.BUY)
        assert buy_fill.fill_quantity == Decimal("176")
        assert buy_fill.fill_price == Decimal("28000")

        sell_fills = [f for f in plan.synthetic_fills if f.side == OrderSide.SELL]
        assert sorted(f.fill_quantity for f in sell_fills) == [Decimal("70"), Decimal("88")]

        # apply: 실제 fill_events append
        result = await apply_backfill_plan(repos, plan)
        assert result.applied is True
        assert result.fills_appended == 3
        assert result.fills_skipped_duplicate == 0
        assert result.recompute_queue_item_id is not None

        saved_buy_fills = await repos.fill_events.list_by_broker_order(
            buy_broker_order.broker_order_id
        )
        assert len(saved_buy_fills) == 1
        assert saved_buy_fills[0].source_channel == "backfill"

        state = await repos.position_cost_basis_states.get(account_id, instrument_id)
        assert state is not None
        assert state.recompute_required is True

        # idempotency: 같은 계획을 다시 apply해도 중복 append 없음
        result2 = await apply_backfill_plan(repos, plan)
        assert result2.fills_appended == 0
        assert result2.fills_skipped_duplicate == 3


class TestExclusionReasons:
    @pytest.mark.asyncio
    async def test_no_filled_orders_in_window(self, repos):
        plan = await build_backfill_plan(
            repos,
            account_id=uuid4(),
            instrument_id=uuid4(),
            start_date=date(2026, 8, 1),
        )
        assert plan.eligible is False
        assert plan.exclusion_reason == BackfillExclusionReason.NO_FILLED_ORDERS_IN_WINDOW

    @pytest.mark.asyncio
    async def test_zero_crossing_not_found_excludes_whole_instrument(self, repos):
        account_id = uuid4()
        instrument_id = uuid4()
        order = _make_order(
            account_id=account_id,
            instrument_id=instrument_id,
            side=OrderSide.SELL,
            requested_quantity=Decimal("10"),
            created_at=_dt("2026-08-05 09:00:00"),
        )
        await repos.orders.add(order)
        # position_snapshots에 quantity=0 관측이 전혀 없음 — 원가 시작점 불명확
        plan = await build_backfill_plan(
            repos,
            account_id=account_id,
            instrument_id=instrument_id,
            start_date=date(2026, 8, 1),
        )
        assert plan.eligible is False
        assert plan.exclusion_reason == BackfillExclusionReason.ZERO_CROSSING_NOT_FOUND

    @pytest.mark.asyncio
    async def test_cancel_flag_excludes_whole_instrument(self, repos):
        account_id = uuid4()
        instrument_id = uuid4()
        await repos.position_snapshots.add(
            _make_position(
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=Decimal("0"),
                average_price=Decimal("0"),
                snapshot_at=_dt("2026-06-18 12:00:00"),
            )
        )
        order = _make_order(
            account_id=account_id,
            instrument_id=instrument_id,
            side=OrderSide.BUY,
            requested_quantity=Decimal("10"),
            created_at=_dt("2026-08-05 09:00:00"),
        )
        await repos.orders.add(order)
        broker_order = _make_broker_order(order, "9999999999")
        await repos.broker_orders.add(broker_order)
        await repos.broker_fill_snapshots.upsert(
            _make_snapshot(
                account_id=account_id,
                order=order,
                native_id="9999999999",
                filled_quantity=Decimal("10"),
                fill_price=Decimal("1000"),
                updated_at=_dt("2026-08-05 09:05:00"),
                cancel_yn="Y",
            )
        )
        plan = await build_backfill_plan(
            repos,
            account_id=account_id,
            instrument_id=instrument_id,
            start_date=date(2026, 8, 1),
        )
        assert plan.eligible is False
        assert plan.exclusion_reason == BackfillExclusionReason.CANCEL_FLAG_PRESENT
        assert plan.synthetic_fills == ()

    @pytest.mark.asyncio
    async def test_negative_delta_staircase_excludes_whole_instrument(self, repos):
        account_id = uuid4()
        instrument_id = uuid4()
        await repos.position_snapshots.add(
            _make_position(
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=Decimal("0"),
                average_price=Decimal("0"),
                snapshot_at=_dt("2026-06-18 12:00:00"),
            )
        )
        order = _make_order(
            account_id=account_id,
            instrument_id=instrument_id,
            side=OrderSide.BUY,
            requested_quantity=Decimal("10"),
            created_at=_dt("2026-08-05 09:00:00"),
        )
        await repos.orders.add(order)
        broker_order = _make_broker_order(order, "9999999999")
        await repos.broker_orders.add(broker_order)
        # staircase 역행: 5 -> 3 (음수 delta)
        await repos.broker_fill_snapshots.upsert(
            _make_snapshot(
                account_id=account_id,
                order=order,
                native_id="9999999999",
                filled_quantity=Decimal("5"),
                fill_price=Decimal("1000"),
                updated_at=_dt("2026-08-05 09:05:00"),
            )
        )
        await repos.broker_fill_snapshots.upsert(
            _make_snapshot(
                account_id=account_id,
                order=order,
                native_id="9999999999",
                filled_quantity=Decimal("3"),
                fill_price=Decimal("1000"),
                updated_at=_dt("2026-08-05 09:06:00"),
            )
        )
        plan = await build_backfill_plan(
            repos,
            account_id=account_id,
            instrument_id=instrument_id,
            start_date=date(2026, 8, 1),
        )
        assert plan.eligible is False
        assert plan.exclusion_reason == BackfillExclusionReason.NEGATIVE_DELTA

    @pytest.mark.asyncio
    async def test_final_quantity_mismatch_excludes_whole_instrument(self, repos):
        account_id = uuid4()
        instrument_id = uuid4()
        await repos.position_snapshots.add(
            _make_position(
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=Decimal("0"),
                average_price=Decimal("0"),
                snapshot_at=_dt("2026-06-18 12:00:00"),
            )
        )
        order = _make_order(
            account_id=account_id,
            instrument_id=instrument_id,
            side=OrderSide.BUY,
            requested_quantity=Decimal("10"),
            created_at=_dt("2026-08-05 09:00:00"),
        )
        await repos.orders.add(order)
        broker_order = _make_broker_order(order, "9999999999")
        await repos.broker_orders.add(broker_order)
        # 최종 관측 수량(7)이 요청수량(10)과 불일치 — 미체결 잔량 존재 의심
        await repos.broker_fill_snapshots.upsert(
            _make_snapshot(
                account_id=account_id,
                order=order,
                native_id="9999999999",
                filled_quantity=Decimal("7"),
                fill_price=Decimal("1000"),
                updated_at=_dt("2026-08-05 09:05:00"),
            )
        )
        plan = await build_backfill_plan(
            repos,
            account_id=account_id,
            instrument_id=instrument_id,
            start_date=date(2026, 8, 1),
        )
        assert plan.eligible is False
        assert plan.exclusion_reason == BackfillExclusionReason.FINAL_QUANTITY_MISMATCH

    @pytest.mark.asyncio
    async def test_snapshot_missing_excludes_whole_instrument(self, repos):
        account_id = uuid4()
        instrument_id = uuid4()
        await repos.position_snapshots.add(
            _make_position(
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=Decimal("0"),
                average_price=Decimal("0"),
                snapshot_at=_dt("2026-06-18 12:00:00"),
            )
        )
        order = _make_order(
            account_id=account_id,
            instrument_id=instrument_id,
            side=OrderSide.BUY,
            requested_quantity=Decimal("10"),
            created_at=_dt("2026-08-05 09:00:00"),
        )
        await repos.orders.add(order)
        # broker_fill_snapshots에 관측 없음 — filled인데 snapshot 누락
        plan = await build_backfill_plan(
            repos,
            account_id=account_id,
            instrument_id=instrument_id,
            start_date=date(2026, 8, 1),
        )
        assert plan.eligible is False
        assert plan.exclusion_reason == BackfillExclusionReason.SNAPSHOT_MISSING


class TestApplyGuards:
    @pytest.mark.asyncio
    async def test_apply_is_noop_when_plan_not_eligible(self, repos):
        account_id = uuid4()
        instrument_id = uuid4()
        plan = await build_backfill_plan(
            repos,
            account_id=account_id,
            instrument_id=instrument_id,
            start_date=date(2026, 8, 1),
        )
        assert plan.eligible is False

        result = await apply_backfill_plan(repos, plan)
        assert result.applied is False
        assert result.fills_appended == 0
        assert result.recompute_queue_item_id is None


class TestFeeTaxPolicyIntegration:
    """정책 기반 fee/tax 계산이 backfill 경로에도 연결되는지 확인한다.

    설계 근거: docs/00_foundational_design/detailed_design/
    12_realized_pnl_moving_average_ledger.md 13절. 실시간 경로
    (test_order_sync_service.py::TestFeeTaxPolicyIntegration)와 동일한
    ``compute_fee_tax()``를 공유한다 — 계산 결과가 같은 정책값에 대해
    같은 방식으로 나오는지가 핵심이다.
    """

    def _seed_account_and_instrument(
        self, repos, *, account_id, instrument_id, asset_class="kr_stock",
        market_segment="KOSPI",
    ):
        client_id = uuid4()
        account = AccountEntity(
            account_id=account_id, client_id=client_id, broker_account_id=uuid4(),
            environment=Environment.PAPER, account_alias="backfill-fee-test",
            account_masked="test-masked", status="active",
        )
        repos.accounts._items[account_id] = account  # type: ignore[attr-defined]
        instrument = InstrumentEntity(
            instrument_id=instrument_id, symbol="007070", market_code="KRX",
            asset_class=asset_class, currency="KRW", name="테스트종목",
            market_segment=market_segment,
        )
        repos.instruments._items[instrument_id] = instrument  # type: ignore[attr-defined]
        return client_id

    async def _seed_policy(self, repos, *, client_id, **overrides):
        fee_tax = {
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
        fee_tax.update(overrides)
        version = ConfigVersionEntity(
            config_version_id=uuid4(), client_id=client_id, environment=Environment.PAPER,
            version_tag="test", config_json={"execution": {"fee_tax": fee_tax}},
            checksum="test", activated_at=_dt("2026-01-01 00:00:00"),
        )
        await repos.config_versions.add(version)

    def _seed_single_buy_scenario(self, repos):
        account_id = uuid4()
        instrument_id = uuid4()
        repos.position_snapshots._items[uuid4()] = _make_position(  # type: ignore[attr-defined]
            account_id=account_id, instrument_id=instrument_id, quantity=Decimal("0"),
            average_price=Decimal("0"), snapshot_at=_dt("2026-06-18 12:00:00"),
        )
        order = _make_order(
            account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY,
            requested_quantity=Decimal("176"), created_at=_dt("2026-08-10 08:58:36"),
        )
        broker_order = _make_broker_order(order, "0000000871")
        repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]
        repos.broker_orders._items[broker_order.broker_order_id] = broker_order  # type: ignore[attr-defined]
        snapshot = _make_snapshot(
            account_id=account_id, order=order, native_id="0000000871",
            filled_quantity=Decimal("176"), fill_price=Decimal("28000"),
            updated_at=_dt("2026-08-10 09:01:05"),
        )
        repos.broker_fill_snapshots._items[snapshot.broker_fill_snapshot_id] = snapshot  # type: ignore[attr-defined]
        repos.broker_fill_snapshots._by_dedupe_key[snapshot.dedupe_key] = (  # type: ignore[attr-defined]
            snapshot.broker_fill_snapshot_id
        )
        return account_id, instrument_id

    @pytest.mark.asyncio
    async def test_calculated_from_policy_end_to_end_via_apply(self, repos):
        account_id, instrument_id = self._seed_single_buy_scenario(repos)
        client_id = self._seed_account_and_instrument(
            repos, account_id=account_id, instrument_id=instrument_id,
        )
        await self._seed_policy(repos, client_id=client_id)

        plan = await build_backfill_plan(
            repos, account_id=account_id, instrument_id=instrument_id,
            start_date=date(2026, 8, 1),
        )
        assert plan.eligible is True
        assert len(plan.synthetic_fills) == 1
        candidate = plan.synthetic_fills[0]
        expected_fee = (Decimal("28000") * Decimal("176") * Decimal("0.015") / 100).to_integral_value()
        assert candidate.fee == expected_fee
        assert candidate.tax == Decimal("0")
        assert candidate.fee_tax_source.value == "calculated_from_policy"

        result = await apply_backfill_plan(repos, plan)
        assert result.applied is True
        broker_order_id = plan.order_details[0].candidates[0].broker_order_id
        saved = await repos.fill_events.list_by_broker_order(broker_order_id)
        assert len(saved) == 1
        assert saved[0].fill_fee == expected_fee
        assert saved[0].fee_tax_source == "calculated_from_policy"

    @pytest.mark.asyncio
    async def test_assumed_zero_when_no_policy_registered(self, repos):
        account_id, instrument_id = self._seed_single_buy_scenario(repos)
        self._seed_account_and_instrument(
            repos, account_id=account_id, instrument_id=instrument_id,
        )
        # config_versions에는 아무것도 등록하지 않는다.

        plan = await build_backfill_plan(
            repos, account_id=account_id, instrument_id=instrument_id,
            start_date=date(2026, 8, 1),
        )
        assert plan.eligible is True
        candidate = plan.synthetic_fills[0]
        assert candidate.fee == Decimal("0")
        assert candidate.tax == Decimal("0")
        assert candidate.fee_tax_source.value == "assumed_zero"
