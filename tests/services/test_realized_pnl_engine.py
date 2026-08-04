"""Tests for the moving-average realized PnL calculation engine.

Test matrix
-----------
1.  단일 BUY 후 상태 생성
2.  연속 BUY 시 이동평균 갱신
3.  부분 SELL 시 realized PnL 계산(평균단가 불변)
4.  전량 SELL 시 평균단가 0 리셋
5.  완전 청산 후 재매수 시 새 평균단가 시작
6.  같은 fill 집합이라도 순서가 다르면 결과가 달라짐(정렬 순서 의존성)
7.  fee_tax_source=reported → fee/tax가 realized_pnl_net에서 차감됨
8.  fee_tax_source=assumed_zero → fee/tax는 0이어야 하고, 그렇지 않으면 실패
9.  직전 상태 없이 SELL → MissingCostBasisStateError
10. 보유 수량 초과 SELL → InsufficientPositionQuantityError
11. 잘못된 fill(수량/가격/수수료/세금) → 각각의 InvalidXxxError로 방어(parametrize)
12. replay_fills가 결정론적이고, fill_timestamp 역행을 감지함
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import PositionCostBasisStateEntity
from agent_trading.domain.enums import OrderSide, RealizedPnlFeeTaxSource
from agent_trading.services.realized_pnl_engine import (
    FeeTaxSourceMismatchError,
    FillsNotSortedError,
    InsufficientPositionQuantityError,
    InvalidFeeOrTaxError,
    InvalidFillPriceError,
    InvalidFillQuantityError,
    MissingCostBasisStateError,
    NormalizedFill,
    apply_fill_to_cost_basis,
    replay_fills,
)

_ACCOUNT_ID = uuid4()
_INSTRUMENT_ID = uuid4()
_COMPUTATION_RUN_ID = uuid4()
_BASE_TS = datetime(2026, 5, 1, 9, 0, 0, tzinfo=timezone.utc)


# ======================================================================
# Helpers
# ======================================================================


def _make_fill(
    *,
    side: OrderSide = OrderSide.BUY,
    quantity: Decimal = Decimal("10"),
    price: Decimal = Decimal("100"),
    fee: Decimal = Decimal("0"),
    tax: Decimal = Decimal("0"),
    fee_tax_source: RealizedPnlFeeTaxSource = RealizedPnlFeeTaxSource.ASSUMED_ZERO,
    fill_timestamp: datetime = _BASE_TS,
    fill_event_id: UUID | None = None,
) -> NormalizedFill:
    return NormalizedFill(
        fill_event_id=fill_event_id or uuid4(),
        account_id=_ACCOUNT_ID,
        instrument_id=_INSTRUMENT_ID,
        broker_order_id=uuid4(),
        order_request_id=uuid4(),
        side=side,
        quantity=quantity,
        price=price,
        fee=fee,
        tax=tax,
        fee_tax_source=fee_tax_source,
        fill_timestamp=fill_timestamp,
    )


# ======================================================================
# 1. 단일 BUY
# ======================================================================


def test_single_buy_creates_state():
    fill = _make_fill(side=OrderSide.BUY, quantity=Decimal("10"), price=Decimal("100"))

    state, event = apply_fill_to_cost_basis(None, fill, computation_run_id=_COMPUTATION_RUN_ID)

    assert event is None
    assert state.account_id == _ACCOUNT_ID
    assert state.instrument_id == _INSTRUMENT_ID
    assert state.quantity == Decimal("10")
    assert state.average_cost == Decimal("100")
    assert state.last_applied_fill_event_id == fill.fill_event_id
    assert state.last_applied_fill_timestamp == fill.fill_timestamp
    assert state.recompute_required is False


# ======================================================================
# 2. 연속 BUY — 이동평균 갱신
# ======================================================================


def test_successive_buys_update_moving_average():
    fill1 = _make_fill(quantity=Decimal("10"), price=Decimal("100"))
    fill2 = _make_fill(quantity=Decimal("10"), price=Decimal("200"), fill_timestamp=_BASE_TS + timedelta(seconds=1))

    state1, _ = apply_fill_to_cost_basis(None, fill1, computation_run_id=_COMPUTATION_RUN_ID)
    state2, event2 = apply_fill_to_cost_basis(state1, fill2, computation_run_id=_COMPUTATION_RUN_ID)

    assert event2 is None
    assert state2.quantity == Decimal("20")
    # (10*100 + 10*200) / 20 = 150
    assert state2.average_cost == Decimal("150")


# ======================================================================
# 3. 부분 SELL — realized PnL 계산, 평균단가 불변
# ======================================================================


def test_partial_sell_computes_realized_pnl_and_keeps_average_cost():
    buy = _make_fill(quantity=Decimal("10"), price=Decimal("100"))
    state_after_buy, _ = apply_fill_to_cost_basis(None, buy, computation_run_id=_COMPUTATION_RUN_ID)

    sell = _make_fill(
        side=OrderSide.SELL,
        quantity=Decimal("4"),
        price=Decimal("150"),
        fill_timestamp=_BASE_TS + timedelta(seconds=1),
    )
    state_after_sell, event = apply_fill_to_cost_basis(
        state_after_buy, sell, computation_run_id=_COMPUTATION_RUN_ID
    )

    assert event is not None
    assert event.sell_quantity == Decimal("4")
    assert event.sell_price == Decimal("150")
    assert event.avg_cost_basis_before == Decimal("100")
    # (150 - 100) * 4 = 200
    assert event.realized_pnl_gross == Decimal("200")
    assert event.realized_pnl_net == Decimal("200")
    assert event.position_quantity_after == Decimal("6")
    assert event.computation_run_id == _COMPUTATION_RUN_ID
    assert event.fill_event_id == sell.fill_event_id

    assert state_after_sell.quantity == Decimal("6")
    assert state_after_sell.average_cost == Decimal("100")  # SELL은 평균단가를 바꾸지 않는다


# ======================================================================
# 4. 전량 SELL — 평균단가 0 리셋
# ======================================================================


def test_full_sell_resets_average_cost_to_zero():
    buy = _make_fill(quantity=Decimal("10"), price=Decimal("100"))
    state_after_buy, _ = apply_fill_to_cost_basis(None, buy, computation_run_id=_COMPUTATION_RUN_ID)

    sell = _make_fill(
        side=OrderSide.SELL,
        quantity=Decimal("10"),
        price=Decimal("120"),
        fill_timestamp=_BASE_TS + timedelta(seconds=1),
    )
    state_after_sell, event = apply_fill_to_cost_basis(
        state_after_buy, sell, computation_run_id=_COMPUTATION_RUN_ID
    )

    assert state_after_sell.quantity == Decimal("0")
    assert state_after_sell.average_cost == Decimal("0")
    assert event.position_quantity_after == Decimal("0")


# ======================================================================
# 5. 완전 청산 후 재매수 — 새 평균단가 시작
# ======================================================================


def test_reentry_after_full_exit_starts_new_average_cost():
    buy1 = _make_fill(quantity=Decimal("10"), price=Decimal("100"))
    state1, _ = apply_fill_to_cost_basis(None, buy1, computation_run_id=_COMPUTATION_RUN_ID)

    sell = _make_fill(
        side=OrderSide.SELL,
        quantity=Decimal("10"),
        price=Decimal("120"),
        fill_timestamp=_BASE_TS + timedelta(seconds=1),
    )
    state2, _ = apply_fill_to_cost_basis(state1, sell, computation_run_id=_COMPUTATION_RUN_ID)
    assert state2.quantity == Decimal("0")
    assert state2.average_cost == Decimal("0")

    buy2 = _make_fill(
        quantity=Decimal("5"),
        price=Decimal("300"),
        fill_timestamp=_BASE_TS + timedelta(seconds=2),
    )
    state3, event3 = apply_fill_to_cost_basis(state2, buy2, computation_run_id=_COMPUTATION_RUN_ID)

    assert event3 is None
    assert state3.quantity == Decimal("5")
    # 이전 매도 손익과 무관하게 새 매입가 그대로 시작한다.
    assert state3.average_cost == Decimal("300")


# ======================================================================
# 6. 같은 fill 집합, 다른 순서 → 다른 결과 (정렬 순서 의존성)
# ======================================================================


def test_same_fills_different_order_produce_different_results():
    """BUY 10@100 → SELL 5@200 → BUY 5@50 순서와,
    BUY 10@100 → BUY 5@50 → SELL 5@200 순서는 서로 다른 결과를 낸다.

    이동평균은 히스토리 의존적이므로, 이 테스트 이름 자체가 그 계약을
    드러낸다 — apply_fill_to_cost_basis는 순서를 강제하지 않으므로 호출자가
    올바른 순서로 먹여야 한다.
    """
    buy1 = _make_fill(quantity=Decimal("10"), price=Decimal("100"), fill_timestamp=_BASE_TS)
    sell1 = _make_fill(
        side=OrderSide.SELL,
        quantity=Decimal("5"),
        price=Decimal("200"),
        fill_timestamp=_BASE_TS + timedelta(seconds=1),
    )
    buy2 = _make_fill(
        quantity=Decimal("5"),
        price=Decimal("50"),
        fill_timestamp=_BASE_TS + timedelta(seconds=2),
    )

    # 순서 A: BUY, SELL, BUY
    result_a = replay_fills([buy1, sell1, buy2], computation_run_id=_COMPUTATION_RUN_ID)

    # 순서 B: BUY, BUY, SELL (SELL fill_timestamp을 뒤로 옮겨 순서를 실제로 바꾼다)
    sell1_later = _make_fill(
        side=OrderSide.SELL,
        quantity=Decimal("5"),
        price=Decimal("200"),
        fill_timestamp=_BASE_TS + timedelta(seconds=3),
        fill_event_id=sell1.fill_event_id,
    )
    result_b = replay_fills([buy1, buy2, sell1_later], computation_run_id=_COMPUTATION_RUN_ID)

    # 순서 A: SELL 시점 평균단가 100(BUY2 반영 전) → gross=(200-100)*5=500
    assert result_a.realized_pnl_events[0].realized_pnl_gross == Decimal("500")
    # SELL 후 잔량 5(0이 아님) + BUY2 5@50 병합 → (5*100+5*50)/10=75
    assert result_a.final_state.average_cost == Decimal("75")

    # 순서 B: SELL 시점 평균단가 (10*100+5*50)/15=83.333... → gross=(200-avg)*5
    avg_before_sell_b = (Decimal("10") * Decimal("100") + Decimal("5") * Decimal("50")) / Decimal("15")
    expected_gross_b = (Decimal("200") - avg_before_sell_b) * Decimal("5")
    assert result_b.realized_pnl_events[0].realized_pnl_gross == expected_gross_b
    assert result_a.realized_pnl_events[0].realized_pnl_gross != result_b.realized_pnl_events[0].realized_pnl_gross


# ======================================================================
# 7 & 8. fee/tax provenance
# ======================================================================


def test_fee_tax_reported_is_deducted_from_realized_pnl_net():
    buy = _make_fill(quantity=Decimal("10"), price=Decimal("100"))
    state1, _ = apply_fill_to_cost_basis(None, buy, computation_run_id=_COMPUTATION_RUN_ID)

    sell = _make_fill(
        side=OrderSide.SELL,
        quantity=Decimal("10"),
        price=Decimal("150"),
        fee=Decimal("5"),
        tax=Decimal("3"),
        fee_tax_source=RealizedPnlFeeTaxSource.REPORTED,
        fill_timestamp=_BASE_TS + timedelta(seconds=1),
    )
    _, event = apply_fill_to_cost_basis(state1, sell, computation_run_id=_COMPUTATION_RUN_ID)

    assert event.fee_tax_source == RealizedPnlFeeTaxSource.REPORTED
    assert event.realized_pnl_gross == Decimal("500")
    assert event.realized_pnl_net == Decimal("500") - Decimal("5") - Decimal("3")


def test_fee_tax_assumed_zero_with_zero_values_matches_gross():
    buy = _make_fill(quantity=Decimal("10"), price=Decimal("100"))
    state1, _ = apply_fill_to_cost_basis(None, buy, computation_run_id=_COMPUTATION_RUN_ID)

    sell = _make_fill(
        side=OrderSide.SELL,
        quantity=Decimal("10"),
        price=Decimal("150"),
        fee=Decimal("0"),
        tax=Decimal("0"),
        fee_tax_source=RealizedPnlFeeTaxSource.ASSUMED_ZERO,
        fill_timestamp=_BASE_TS + timedelta(seconds=1),
    )
    _, event = apply_fill_to_cost_basis(state1, sell, computation_run_id=_COMPUTATION_RUN_ID)

    assert event.realized_pnl_net == event.realized_pnl_gross


def test_fee_tax_assumed_zero_with_nonzero_fee_raises():
    sell = _make_fill(
        side=OrderSide.SELL,
        fee=Decimal("1"),
        tax=Decimal("0"),
        fee_tax_source=RealizedPnlFeeTaxSource.ASSUMED_ZERO,
    )
    state = PositionCostBasisStateEntity(
        account_id=_ACCOUNT_ID,
        instrument_id=_INSTRUMENT_ID,
        quantity=Decimal("10"),
        average_cost=Decimal("100"),
    )

    with pytest.raises(FeeTaxSourceMismatchError):
        apply_fill_to_cost_basis(state, sell, computation_run_id=_COMPUTATION_RUN_ID)


# ======================================================================
# 9 & 10. 숏 포지션 미지원 (직전 상태 없음 / 보유 수량 초과)
# ======================================================================


def test_sell_without_prior_state_raises_missing_cost_basis_state():
    sell = _make_fill(side=OrderSide.SELL, quantity=Decimal("1"), price=Decimal("100"))

    with pytest.raises(MissingCostBasisStateError):
        apply_fill_to_cost_basis(None, sell, computation_run_id=_COMPUTATION_RUN_ID)


def test_sell_after_full_exit_raises_missing_cost_basis_state():
    zeroed_state = PositionCostBasisStateEntity(
        account_id=_ACCOUNT_ID,
        instrument_id=_INSTRUMENT_ID,
        quantity=Decimal("0"),
        average_cost=Decimal("0"),
    )
    sell = _make_fill(side=OrderSide.SELL, quantity=Decimal("1"), price=Decimal("100"))

    with pytest.raises(MissingCostBasisStateError):
        apply_fill_to_cost_basis(zeroed_state, sell, computation_run_id=_COMPUTATION_RUN_ID)


def test_sell_exceeding_holdings_raises_insufficient_position_quantity():
    state = PositionCostBasisStateEntity(
        account_id=_ACCOUNT_ID,
        instrument_id=_INSTRUMENT_ID,
        quantity=Decimal("5"),
        average_cost=Decimal("100"),
    )
    sell = _make_fill(side=OrderSide.SELL, quantity=Decimal("6"), price=Decimal("100"))

    with pytest.raises(InsufficientPositionQuantityError):
        apply_fill_to_cost_basis(state, sell, computation_run_id=_COMPUTATION_RUN_ID)


# ======================================================================
# 11. 입력 방어 — 수량/가격/수수료/세금
# ======================================================================


@pytest.mark.parametrize(
    ("overrides", "expected_exception"),
    [
        ({"quantity": Decimal("0")}, InvalidFillQuantityError),
        ({"quantity": Decimal("-1")}, InvalidFillQuantityError),
        ({"price": Decimal("-1")}, InvalidFillPriceError),
        ({"fee": Decimal("-1")}, InvalidFeeOrTaxError),
        ({"tax": Decimal("-1")}, InvalidFeeOrTaxError),
    ],
)
def test_invalid_fill_inputs_are_rejected(overrides, expected_exception):
    fill = _make_fill(side=OrderSide.BUY, **overrides)

    with pytest.raises(expected_exception):
        apply_fill_to_cost_basis(None, fill, computation_run_id=_COMPUTATION_RUN_ID)


# ======================================================================
# 12. replay_fills — 결정론성 + 정렬 계약
# ======================================================================


def test_replay_fills_is_deterministic():
    fills = [
        _make_fill(quantity=Decimal("10"), price=Decimal("100"), fill_timestamp=_BASE_TS),
        _make_fill(
            side=OrderSide.SELL,
            quantity=Decimal("4"),
            price=Decimal("150"),
            fill_timestamp=_BASE_TS + timedelta(seconds=1),
        ),
        _make_fill(
            quantity=Decimal("6"),
            price=Decimal("90"),
            fill_timestamp=_BASE_TS + timedelta(seconds=2),
        ),
    ]

    result1 = replay_fills(fills, computation_run_id=_COMPUTATION_RUN_ID)
    result2 = replay_fills(fills, computation_run_id=_COMPUTATION_RUN_ID)

    assert result1 == result2
    assert len(result1.realized_pnl_events) == 1
    assert result1.final_state.quantity == Decimal("12")


def test_replay_fills_detects_out_of_order_timestamps():
    fills = [
        _make_fill(quantity=Decimal("10"), price=Decimal("100"), fill_timestamp=_BASE_TS),
        _make_fill(
            quantity=Decimal("5"),
            price=Decimal("110"),
            fill_timestamp=_BASE_TS - timedelta(seconds=1),
        ),
    ]

    with pytest.raises(FillsNotSortedError):
        replay_fills(fills, computation_run_id=_COMPUTATION_RUN_ID)


def test_replay_fills_allows_equal_timestamps():
    """동시각 다건 체결은 정상 케이스이며 실패하지 않아야 한다."""
    fills = [
        _make_fill(quantity=Decimal("5"), price=Decimal("100"), fill_timestamp=_BASE_TS),
        _make_fill(quantity=Decimal("5"), price=Decimal("110"), fill_timestamp=_BASE_TS),
    ]

    result = replay_fills(fills, computation_run_id=_COMPUTATION_RUN_ID)

    assert result.final_state.quantity == Decimal("10")


def test_replay_fills_reuses_initial_state():
    initial_state = PositionCostBasisStateEntity(
        account_id=_ACCOUNT_ID,
        instrument_id=_INSTRUMENT_ID,
        quantity=Decimal("10"),
        average_cost=Decimal("100"),
        last_applied_fill_timestamp=_BASE_TS,
    )
    sell = _make_fill(
        side=OrderSide.SELL,
        quantity=Decimal("10"),
        price=Decimal("200"),
        fill_timestamp=_BASE_TS + timedelta(seconds=1),
    )

    result = replay_fills(
        [sell], computation_run_id=_COMPUTATION_RUN_ID, initial_state=initial_state
    )

    assert len(result.realized_pnl_events) == 1
    assert result.realized_pnl_events[0].avg_cost_basis_before == Decimal("100")
    assert result.final_state.quantity == Decimal("0")
