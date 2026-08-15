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
    BackfillAnchorType,
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


class TestHistoricalPolicyEstimateOverride:
    """``use_historical_policy_estimate_for_buy_fee`` 옵션 — `001450`/`004370`

    파일럿(둘 다 SELL 없는 BUY-only 종목, 정책 활성 이전 BUY)을 재현한다.
    설계 근거: docs/00_foundational_design/detailed_design/
    16_broker_fill_snapshot_historical_backfill_design.md §8, 12번 문서
    13절/14절. 의도적으로 ``TestFeeTaxPolicyIntegration``을 상속하지 않고
    필요한 seed helper만 별도로 둔다 — 상속하면 그 클래스의 기존 테스트가
    이 클래스 아래에서 중복 실행되기 때문이다.
    """

    def _seed_account_and_instrument(
        self, repos, *, account_id, instrument_id, asset_class="kr_stock",
        market_segment="KOSPI",
    ):
        client_id = uuid4()
        account = AccountEntity(
            account_id=account_id, client_id=client_id, broker_account_id=uuid4(),
            environment=Environment.PAPER, account_alias="historical-estimate-test",
            account_masked="test-masked", status="active",
        )
        repos.accounts._items[account_id] = account  # type: ignore[attr-defined]
        instrument = InstrumentEntity(
            instrument_id=instrument_id, symbol="001450", market_code="KRX",
            asset_class=asset_class, currency="KRW", name="테스트종목",
            market_segment=market_segment,
        )
        repos.instruments._items[instrument_id] = instrument  # type: ignore[attr-defined]
        return client_id

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

    async def _seed_policy_activated_after_buy(self, repos, *, client_id, **overrides):
        """BUY(2026-08-10 08:58:36 KST) **이후** 시점(2026-08-14)에 활성화되는
        정책 — `001450`/`004370`가 실제로 겪는 시간 관계(정책이 BUY보다
        나중에 등록됨)를 그대로 재현한다."""
        await self._seed_policy(
            repos, client_id=client_id,
            activated_at_override=_dt("2026-08-14 15:50:11"),
            **overrides,
        )

    async def _seed_policy(self, repos, *, client_id, activated_at_override=None, **overrides):
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
        activated_at = activated_at_override or _dt("2026-01-01 00:00:00")
        version = ConfigVersionEntity(
            config_version_id=uuid4(), client_id=client_id, environment=Environment.PAPER,
            version_tag="test", config_json={"execution": {"fee_tax": fee_tax}},
            checksum="test", activated_at=activated_at,
        )
        await repos.config_versions.add(version)

    @pytest.mark.asyncio
    async def test_option_off_keeps_assumed_zero_for_policy_activated_after_buy(self, repos):
        """시나리오 1: 옵션 없음 → 정책 활성 이전 BUY는 기존대로 assumed_zero."""
        account_id, instrument_id = self._seed_single_buy_scenario(repos)
        client_id = self._seed_account_and_instrument(
            repos, account_id=account_id, instrument_id=instrument_id,
        )
        await self._seed_policy_activated_after_buy(repos, client_id=client_id)

        plan = await build_backfill_plan(
            repos, account_id=account_id, instrument_id=instrument_id,
            start_date=date(2026, 8, 1),
            # use_historical_policy_estimate_for_buy_fee 생략 → 기본값 False
        )
        assert plan.eligible is True
        candidate = plan.synthetic_fills[0]
        assert candidate.fee == Decimal("0")
        assert candidate.tax == Decimal("0")
        assert candidate.fee_tax_source.value == "assumed_zero"

    @pytest.mark.asyncio
    async def test_option_on_overrides_buy_with_historical_policy_estimate(self, repos):
        """시나리오 2: 옵션 있음 + 정책 활성 이전 BUY + 현재 활성 정책 존재
        → historical_policy_estimate로 fee 계산."""
        account_id, instrument_id = self._seed_single_buy_scenario(repos)
        client_id = self._seed_account_and_instrument(
            repos, account_id=account_id, instrument_id=instrument_id,
        )
        await self._seed_policy_activated_after_buy(repos, client_id=client_id)

        plan = await build_backfill_plan(
            repos, account_id=account_id, instrument_id=instrument_id,
            start_date=date(2026, 8, 1),
            use_historical_policy_estimate_for_buy_fee=True,
        )
        assert plan.eligible is True
        candidate = plan.synthetic_fills[0]
        expected_fee = (Decimal("28000") * Decimal("176") * Decimal("0.015") / 100).to_integral_value()
        assert candidate.fee == expected_fee
        assert candidate.tax == Decimal("0")
        assert candidate.fee_tax_source.value == "historical_policy_estimate"

        # apply까지 해도 fill_events에 그대로 저장된다(overlay/recompute 없음).
        result = await apply_backfill_plan(repos, plan)
        assert result.applied is True
        saved = await repos.fill_events.list_by_broker_order(
            plan.order_details[0].candidates[0].broker_order_id
        )
        assert saved[0].fill_fee == expected_fee
        assert saved[0].fee_tax_source == "historical_policy_estimate"

    @pytest.mark.asyncio
    async def test_option_on_does_not_affect_sell(self, repos):
        """시나리오 3: 옵션 있음이어도 SELL에는 적용 안 됨(1 buy + 2 sell,
        `007070` 실제 형태를 그대로 재현 — 정책은 BUY/SELL 모두보다 나중에
        활성화됨)."""
        account_id = uuid4()
        instrument_id = uuid4()
        client_id = self._seed_account_and_instrument(
            repos, account_id=account_id, instrument_id=instrument_id,
        )
        await self._seed_policy_activated_after_buy(repos, client_id=client_id)

        await repos.position_snapshots.add(
            _make_position(
                account_id=account_id, instrument_id=instrument_id,
                quantity=Decimal("0"), average_price=Decimal("0"),
                snapshot_at=_dt("2026-06-18 12:00:00"),
            )
        )
        buy_order = _make_order(
            account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY,
            requested_quantity=Decimal("176"), created_at=_dt("2026-08-10 08:58:36"),
        )
        sell_order = _make_order(
            account_id=account_id, instrument_id=instrument_id, side=OrderSide.SELL,
            requested_quantity=Decimal("176"), created_at=_dt("2026-08-13 08:52:17"),
        )
        for order in (buy_order, sell_order):
            await repos.orders.add(order)
        buy_broker_order = _make_broker_order(buy_order, "0000000871")
        sell_broker_order = _make_broker_order(sell_order, "0000000758")
        for bo in (buy_broker_order, sell_broker_order):
            await repos.broker_orders.add(bo)
        await repos.broker_fill_snapshots.upsert(
            _make_snapshot(
                account_id=account_id, order=buy_order, native_id="0000000871",
                filled_quantity=Decimal("176"), fill_price=Decimal("28000"),
                updated_at=_dt("2026-08-10 09:01:05"),
            )
        )
        await repos.broker_fill_snapshots.upsert(
            _make_snapshot(
                account_id=account_id, order=sell_order, native_id="0000000758",
                filled_quantity=Decimal("176"), fill_price=Decimal("26800"),
                updated_at=_dt("2026-08-13 15:42:50"),
            )
        )
        await repos.position_snapshots.add(
            _make_position(
                account_id=account_id, instrument_id=instrument_id,
                quantity=Decimal("0"), average_price=Decimal("0"),
                snapshot_at=_dt("2026-08-13 15:42:20"),
            )
        )

        plan = await build_backfill_plan(
            repos, account_id=account_id, instrument_id=instrument_id,
            start_date=date(2026, 8, 1),
            use_historical_policy_estimate_for_buy_fee=True,
        )
        assert plan.eligible is True
        buy_fill = next(f for f in plan.synthetic_fills if f.side == OrderSide.BUY)
        sell_fill = next(f for f in plan.synthetic_fills if f.side == OrderSide.SELL)
        assert buy_fill.fee_tax_source.value == "historical_policy_estimate"
        assert sell_fill.fee_tax_source.value == "assumed_zero"  # SELL은 옵션과 무관
        assert sell_fill.fee == Decimal("0")
        assert sell_fill.tax == Decimal("0")

    @pytest.mark.asyncio
    async def test_option_on_does_not_override_unsupported_asset_class(self, repos):
        """시나리오 4: 옵션 있음이어도 자산군/시장군 비대상은 override 안 됨.

        기본 계산(fill_timestamp 기준)은 그 시점에 활성 정책 자체가 없어
        ``assumed_zero``다. override 재조회(현재 시각 기준)는 활성 정책은
        있지만 이 자산군(``kr_etf``)이 비지원이라 ``policy_not_applicable``을
        반환하므로, override 조건("재조회 결과가 CALCULATED_FROM_POLICY")을
        만족하지 못해 원래 값(``assumed_zero``)이 그대로 유지돼야 한다 —
        ``policy_not_applicable``로 바뀌면 안 된다(그건 "재조회 자체를
        기본 계산 결과로 승격시킨다"는 뜻이 되어 override 함수의 계약을
        벗어난다)."""
        account_id, instrument_id = self._seed_single_buy_scenario(repos)
        client_id = self._seed_account_and_instrument(
            repos, account_id=account_id, instrument_id=instrument_id,
            asset_class="kr_etf",  # 정책의 supported_asset_classes=["kr_stock"]엔 없음
        )
        await self._seed_policy_activated_after_buy(repos, client_id=client_id)

        plan = await build_backfill_plan(
            repos, account_id=account_id, instrument_id=instrument_id,
            start_date=date(2026, 8, 1),
            use_historical_policy_estimate_for_buy_fee=True,
        )
        assert plan.eligible is True
        candidate = plan.synthetic_fills[0]
        assert candidate.fee == Decimal("0")
        assert candidate.fee_tax_source.value == "assumed_zero"

    @pytest.mark.asyncio
    async def test_option_on_without_active_policy_stays_assumed_zero(self, repos):
        """옵션이 켜져 있어도 활성 정책이 아예 없으면 override할 근거가 없다."""
        account_id, instrument_id = self._seed_single_buy_scenario(repos)
        self._seed_account_and_instrument(
            repos, account_id=account_id, instrument_id=instrument_id,
        )
        # config_versions에는 아무것도 등록하지 않는다.

        plan = await build_backfill_plan(
            repos, account_id=account_id, instrument_id=instrument_id,
            start_date=date(2026, 8, 1),
            use_historical_policy_estimate_for_buy_fee=True,
        )
        assert plan.eligible is True
        candidate = plan.synthetic_fills[0]
        assert candidate.fee == Decimal("0")
        assert candidate.fee_tax_source.value == "assumed_zero"

    @pytest.mark.asyncio
    async def test_option_on_does_not_change_calculated_from_policy_case(self, repos):
        """회귀: BUY 시점에 이미 정책이 활성이었던(calculated_from_policy) 경우,
        옵션을 켜도 결과가 그대로여야 한다(이미 CALCULATED_FROM_POLICY라서
        override 조건(base=ASSUMED_ZERO)에 안 걸림)."""
        account_id, instrument_id = self._seed_single_buy_scenario(repos)
        client_id = self._seed_account_and_instrument(
            repos, account_id=account_id, instrument_id=instrument_id,
        )
        await self._seed_policy(repos, client_id=client_id)  # 2026-01-01 활성 — BUY보다 이전

        plan = await build_backfill_plan(
            repos, account_id=account_id, instrument_id=instrument_id,
            start_date=date(2026, 8, 1),
            use_historical_policy_estimate_for_buy_fee=True,
        )
        assert plan.eligible is True
        candidate = plan.synthetic_fills[0]
        expected_fee = (Decimal("28000") * Decimal("176") * Decimal("0.015") / 100).to_integral_value()
        assert candidate.fee == expected_fee
        assert candidate.fee_tax_source.value == "calculated_from_policy"


class TestInitialEntryAnchor:
    """`INITIAL_ENTRY` anchor — window_start 이전 filled 주문 자체가 전혀
    없는 종목은 zero-crossing 스냅샷 없이도 backfill 자격을 인정한다.

    설계 근거: docs/00_foundational_design/detailed_design/
    16_broker_fill_snapshot_historical_backfill_design.md §8.12.
    `001450`/`004370`와 달리 zero-crossing 스냅샷 자체가 없는 진짜
    "이 종목을 처음 산 경우"(예: `009240`, `011200` 등 13종목 파일럿
    후보)를 재현한다.
    """

    @pytest.mark.asyncio
    async def test_initial_entry_passes_without_zero_crossing_snapshot(self, repos):
        """시나리오 1: zero-crossing 스냅샷 없음 + window 이전 filled 주문
        없음 + window 안 BUY만 존재 + 기존 안전 조건 만족 → eligible=True,
        anchor_type=initial_entry."""
        account_id = uuid4()
        instrument_id = uuid4()
        # position_snapshots에 quantity=0 관측을 전혀 심지 않는다 —
        # 이 종목은 브로커 스냅샷 관측 자체가 없던 신규 종목이라는 뜻.
        order = _make_order(
            account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY,
            requested_quantity=Decimal("80"), created_at=_dt("2026-08-05 09:00:00"),
        )
        await repos.orders.add(order)
        broker_order = _make_broker_order(order, "9000000001")
        await repos.broker_orders.add(broker_order)
        await repos.broker_fill_snapshots.upsert(
            _make_snapshot(
                account_id=account_id, order=order, native_id="9000000001",
                filled_quantity=Decimal("80"), fill_price=Decimal("10000"),
                updated_at=_dt("2026-08-05 09:01:00"),
            )
        )
        await repos.position_snapshots.add(
            _make_position(
                account_id=account_id, instrument_id=instrument_id,
                quantity=Decimal("80"), average_price=Decimal("10000"),
                snapshot_at=_dt("2026-08-05 09:02:00"),
            )
        )

        plan = await build_backfill_plan(
            repos, account_id=account_id, instrument_id=instrument_id,
            start_date=date(2026, 8, 1),
        )

        assert plan.eligible is True
        assert plan.exclusion_reason is None
        assert plan.anchor_type == BackfillAnchorType.INITIAL_ENTRY
        assert plan.zero_crossing_at is None  # 스냅샷 anchor가 아니므로 None
        assert plan.expected_final_quantity == Decimal("80")
        assert plan.broker_reported_quantity == Decimal("80")
        assert plan.broker_reported_quantity_matches is True
        assert len(plan.synthetic_fills) == 1

    @pytest.mark.asyncio
    async def test_existing_zero_crossing_case_still_reports_zero_crossing_anchor_type(self, repos):
        """시나리오 2(회귀): zero-crossing이 있는 기존 케이스는 그대로
        anchor_type=zero_crossing으로 보고된다."""
        account_id = uuid4()
        instrument_id = uuid4()
        await repos.position_snapshots.add(
            _make_position(
                account_id=account_id, instrument_id=instrument_id,
                quantity=Decimal("0"), average_price=Decimal("0"),
                snapshot_at=_dt("2026-06-18 12:00:00"),
            )
        )
        order = _make_order(
            account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY,
            requested_quantity=Decimal("176"), created_at=_dt("2026-08-10 08:58:36"),
        )
        await repos.orders.add(order)
        broker_order = _make_broker_order(order, "0000000871")
        await repos.broker_orders.add(broker_order)
        await repos.broker_fill_snapshots.upsert(
            _make_snapshot(
                account_id=account_id, order=order, native_id="0000000871",
                filled_quantity=Decimal("176"), fill_price=Decimal("28000"),
                updated_at=_dt("2026-08-10 09:01:05"),
            )
        )
        await repos.position_snapshots.add(
            _make_position(
                account_id=account_id, instrument_id=instrument_id,
                quantity=Decimal("176"), average_price=Decimal("28000"),
                snapshot_at=_dt("2026-08-10 09:02:00"),
            )
        )

        plan = await build_backfill_plan(
            repos, account_id=account_id, instrument_id=instrument_id,
            start_date=date(2026, 8, 1),
        )

        assert plan.eligible is True
        assert plan.anchor_type == BackfillAnchorType.ZERO_CROSSING
        assert plan.zero_crossing_at == _dt("2026-06-18 12:00:00")

    @pytest.mark.asyncio
    async def test_orders_before_window_block_initial_entry(self, repos):
        """시나리오 3: zero-crossing도 없고 window 이전 filled 주문이
        있으면(=이 종목이 처음 진입이 아니라는 뜻) initial-entry로도
        통과 못 하고 여전히 제외돼야 한다."""
        account_id = uuid4()
        instrument_id = uuid4()
        # position_snapshots에 zero-crossing 관측 없음.
        old_order = _make_order(
            account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY,
            requested_quantity=Decimal("10"), created_at=_dt("2026-07-15 09:00:00"),
        )
        new_order = _make_order(
            account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY,
            requested_quantity=Decimal("5"), created_at=_dt("2026-08-05 09:00:00"),
        )
        await repos.orders.add(old_order)
        await repos.orders.add(new_order)

        plan = await build_backfill_plan(
            repos, account_id=account_id, instrument_id=instrument_id,
            start_date=date(2026, 8, 1),
        )

        assert plan.eligible is False
        assert plan.exclusion_reason == BackfillExclusionReason.ZERO_CROSSING_NOT_FOUND
        assert plan.anchor_type is None

    @pytest.mark.asyncio
    async def test_initial_entry_first_order_sell_is_rejected(self, repos):
        """window 이전 주문이 전혀 없어도, window 안 첫 주문이 SELL이면
        (사기 전에 파는 셈이라 논리적으로 불가능) initial-entry로 인정하지
        않는다 — 사용자 전제("매수가 그 종목의 첫 진입")를 그대로 반영."""
        account_id = uuid4()
        instrument_id = uuid4()
        order = _make_order(
            account_id=account_id, instrument_id=instrument_id, side=OrderSide.SELL,
            requested_quantity=Decimal("10"), created_at=_dt("2026-08-05 09:00:00"),
        )
        await repos.orders.add(order)

        plan = await build_backfill_plan(
            repos, account_id=account_id, instrument_id=instrument_id,
            start_date=date(2026, 8, 1),
        )

        assert plan.eligible is False
        assert plan.exclusion_reason == BackfillExclusionReason.ZERO_CROSSING_NOT_FOUND
        assert plan.anchor_type is None

    @pytest.mark.asyncio
    async def test_initial_entry_still_excludes_existing_anomalies(self, repos):
        """시나리오 4: initial-entry 조건(window 이전 주문 없음)을 만족해도,
        기존 anomaly 검증(여기서는 snapshot 자체가 없는 경우)은 그대로
        적용돼 제외된다 — anchor만 넓어졌을 뿐 나머지 안전장치는 완화되지
        않는다."""
        account_id = uuid4()
        instrument_id = uuid4()
        order = _make_order(
            account_id=account_id, instrument_id=instrument_id, side=OrderSide.BUY,
            requested_quantity=Decimal("10"), created_at=_dt("2026-08-05 09:00:00"),
        )
        await repos.orders.add(order)
        # broker_fill_snapshots를 심지 않는다 — SNAPSHOT_MISSING 유발.

        plan = await build_backfill_plan(
            repos, account_id=account_id, instrument_id=instrument_id,
            start_date=date(2026, 8, 1),
        )

        assert plan.eligible is False
        assert plan.exclusion_reason == BackfillExclusionReason.SNAPSHOT_MISSING
        assert plan.anchor_type is None
