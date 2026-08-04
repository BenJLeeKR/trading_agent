"""이동평균법 실현 손익(Realized PnL) 계산 엔진 — 순수 함수, 부수효과 없음.

설계 근거: docs/00_foundational_design/detailed_design/12_realized_pnl_moving_average_ledger.md
(3절 계산 의미론, 5절 정렬 키, 6절 idempotency/replay).

Design principles
-----------------
1. **Pure function** — DB/repository 접근, I/O, async 없음. 저장은 이 모듈
   호출자(다음 단계 — 실시간 반영/백필 러너)의 책임이다.
2. **정렬 순서에 강하게 의존한다** — 이동평균은 히스토리 의존적이므로,
   호출자가 5절 tie-break 규칙(``fill_timestamp`` → ``broker_fill_id`` →
   ``fill_events.created_at`` → ``fill_event_id``)으로 미리 정렬한 순서를
   그대로 믿는다. 이 모듈은 정렬을 수행하지 않으며, :func:`replay_fills`는
   ``fill_timestamp`` 역행만 감지해 명시적으로 실패한다(out-of-order 복구
   로직 자체는 이번 범위 밖).
3. **Decimal만 사용** — float 연산은 쓰지 않는다.
4. **UUID/시각은 호출자 책임** — 이 모듈은 ``datetime.now()``나 임의
   ``uuid4()`` 같은 숨겨진 비결정 값을 만들지 않는다.
   ``RealizedPnlEventEntity.realized_pnl_event_id``는 ``fill_event_id``로부터
   결정론적으로 파생한다(:data:`_REALIZED_PNL_EVENT_UUID_NAMESPACE`) — 같은
   fill을 다시 먹이면 항상 같은 id가 나오므로 replay가 그 자체로 비교 가능한
   idempotent 결과를 만든다. ``created_at``/``updated_at``은 엔티티의 기존
   관례대로 ``None``으로 두어 저장 시점에 DB ``DEFAULT NOW()``가 채운다.
5. **숏 포지션 미지원** — 개인 계좌 기준으로 지원 범위에 넣지 않는다
   (migration 0053의 ``quantity >= 0`` CHECK와 동일한 정책). 보유 수량을
   초과하는 SELL은 조용히 클램프하지 않고 명시적으로 실패한다.
6. **저장소 호출 금지** — 이 파일은 ``agent_trading.repositories``를
   import하지 않는다.

Integration (다음 단계, 이번 PR 범위 밖)
---------------------------------------
- 실시간 반영: ``order_sync_service``가 fill 저장 성공 후
  ``apply_fill_to_cost_basis()``를 단일 fill에 대해 호출.
- 백필: 계좌×종목별 전체 fill 히스토리를 정렬해 :func:`replay_fills`에 전달.
- 두 경로 모두 실패(예외)를 잡아 ``realized_pnl_recompute_queue``에 등록하는
  책임은 이 모듈이 아니라 호출자에게 있다(설계 문서 8절 복구 계약).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid5

from agent_trading.domain.entities import (
    PositionCostBasisStateEntity,
    RealizedPnlEventEntity,
)
from agent_trading.domain.enums import OrderSide, RealizedPnlFeeTaxSource

__all__ = [
    "NormalizedFill",
    "ReplayResult",
    "RealizedPnlEngineError",
    "InvalidFillQuantityError",
    "InvalidFillPriceError",
    "InvalidFeeOrTaxError",
    "FeeTaxSourceMismatchError",
    "MissingCostBasisStateError",
    "InsufficientPositionQuantityError",
    "FillsNotSortedError",
    "apply_fill_to_cost_basis",
    "replay_fills",
]


# ---------------------------------------------------------------------------
# 결정론적 realized_pnl_event_id 파생
# ---------------------------------------------------------------------------

# 고정 namespace UUID — 이 값 자체에 의미는 없다. uuid5(namespace, fill_event_id)가
# 같은 fill_event_id에 대해 항상 같은 realized_pnl_event_id를 만들도록 고정만
# 한다. 절대 바꾸지 않는다 — 바꾸면 기존에 계산된 realized_pnl_event_id와
# 재계산 결과가 어긋난다.
_REALIZED_PNL_EVENT_UUID_NAMESPACE = UUID("6f1a6b8e-6b8d-4b8a-9e8a-3f1a6b8e6b8d")


def _derive_realized_pnl_event_id(fill_event_id: UUID) -> UUID:
    return uuid5(_REALIZED_PNL_EVENT_UUID_NAMESPACE, str(fill_event_id))


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RealizedPnlEngineError(ValueError):
    """계산 엔진 불변식 위반의 공통 베이스."""


class InvalidFillQuantityError(RealizedPnlEngineError):
    """``fill.quantity``가 0 이하인 경우."""


class InvalidFillPriceError(RealizedPnlEngineError):
    """``fill.price``가 음수인 경우."""


class InvalidFeeOrTaxError(RealizedPnlEngineError):
    """``fill.fee`` 또는 ``fill.tax``가 음수인 경우."""


class FeeTaxSourceMismatchError(RealizedPnlEngineError):
    """``fee_tax_source=ASSUMED_ZERO``인데 ``fee``/``tax``가 0이 아닌 경우.

    "0으로 간주됨"이라는 provenance 표시와 실제 값이 모순되면, 상류
    (fill 정규화 단계)의 버그를 조용히 넘기지 않고 여기서 드러낸다.
    """


class MissingCostBasisStateError(RealizedPnlEngineError):
    """직전 보유 상태가 전혀 없는 계좌×종목에 SELL fill이 들어온 경우.

    이동평균 계산 엔진은 개인 계좌 기준 숏 포지션을 지원하지 않는다
    (설계 문서 3.2절). 이 상황은 보통 대응하는 BUY fill이 아직 반영되지
    않았거나 out-of-order로 도착했다는 신호다.
    """


class InsufficientPositionQuantityError(RealizedPnlEngineError):
    """보유 수량보다 큰 SELL fill이 들어와 잔량이 음수가 되는 경우.

    이동평균 계산 엔진은 개인 계좌 기준 숏 포지션을 지원하지 않는다
    (설계 문서 3.2절).
    """


class FillsNotSortedError(RealizedPnlEngineError):
    """:func:`replay_fills`에 전달된 ``ordered_fills``의 ``fill_timestamp``가
    역행하는 경우.

    이 모듈은 정렬을 수행하지 않는다 — 호출자가 설계 문서 5절 tie-break
    규칙으로 미리 정렬해야 한다는 계약을 명시적으로 강제한다.
    """


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class NormalizedFill:
    """계산 엔진 입력용으로 정규화된 체결 1건.

    ``trading.fill_events``는 ``account_id``/``instrument_id``/``side``를
    직접 갖지 않는다 — ``broker_order_id → order_requests``로 join해야
    채워진다(설계 문서 2절 핵심 관찰 1). 이 타입은 그 join과 fee/tax
    provenance 판정을 이미 마친 결과를 담아, 계산 엔진이 저장소를 전혀
    몰라도 되게 한다. 이 join·판정을 실제로 수행하는 코드는 다음 단계
    (order_sync_service 연결)의 책임이며 이번 PR 범위 밖이다.
    """

    fill_event_id: UUID
    account_id: UUID
    instrument_id: UUID
    broker_order_id: UUID
    order_request_id: UUID
    side: OrderSide
    quantity: Decimal
    price: Decimal
    fee: Decimal
    tax: Decimal
    fee_tax_source: RealizedPnlFeeTaxSource
    fill_timestamp: datetime


# ---------------------------------------------------------------------------
# Result (replay)
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class ReplayResult:
    """:func:`replay_fills`의 반환 타입."""

    final_state: PositionCostBasisStateEntity | None
    """전체 fill 반영 후 최종 상태. ``ordered_fills``가 비어 있고
    ``initial_state``도 ``None``이면 ``None``."""

    realized_pnl_events: tuple[RealizedPnlEventEntity, ...]
    """반영 과정에서 생성된 realized PnL 이벤트(SELL fill마다 1건),
    적용 순서 그대로."""


# ---------------------------------------------------------------------------
# Validation (pure)
# ---------------------------------------------------------------------------


def _validate_fill(fill: NormalizedFill) -> None:
    if fill.quantity <= 0:
        raise InvalidFillQuantityError(
            f"fill.quantity는 0보다 커야 한다: fill_event_id={fill.fill_event_id}, "
            f"quantity={fill.quantity}"
        )
    if fill.price < 0:
        raise InvalidFillPriceError(
            f"fill.price는 음수일 수 없다: fill_event_id={fill.fill_event_id}, "
            f"price={fill.price}"
        )
    if fill.fee < 0 or fill.tax < 0:
        raise InvalidFeeOrTaxError(
            f"fill.fee/tax는 음수일 수 없다: fill_event_id={fill.fill_event_id}, "
            f"fee={fill.fee}, tax={fill.tax}"
        )
    if fill.fee_tax_source == RealizedPnlFeeTaxSource.ASSUMED_ZERO and (
        fill.fee != 0 or fill.tax != 0
    ):
        raise FeeTaxSourceMismatchError(
            "fee_tax_source=assumed_zero인데 fee/tax가 0이 아니다: "
            f"fill_event_id={fill.fill_event_id}, fee={fill.fee}, tax={fill.tax}"
        )


# ---------------------------------------------------------------------------
# Core state transition
# ---------------------------------------------------------------------------


def _apply_buy(
    state: PositionCostBasisStateEntity | None,
    fill: NormalizedFill,
) -> PositionCostBasisStateEntity:
    if state is None or state.quantity == 0:
        new_quantity = fill.quantity
        new_average_cost = fill.price
    else:
        new_quantity = state.quantity + fill.quantity
        new_average_cost = (
            (state.quantity * state.average_cost) + (fill.quantity * fill.price)
        ) / new_quantity

    return PositionCostBasisStateEntity(
        account_id=fill.account_id,
        instrument_id=fill.instrument_id,
        quantity=new_quantity,
        average_cost=new_average_cost,
        last_applied_fill_event_id=fill.fill_event_id,
        last_applied_fill_timestamp=fill.fill_timestamp,
        recompute_required=False,
        recompute_reason=None,
    )


def _apply_sell(
    state: PositionCostBasisStateEntity | None,
    fill: NormalizedFill,
    *,
    computation_run_id: UUID,
) -> tuple[PositionCostBasisStateEntity, RealizedPnlEventEntity]:
    if state is None or state.quantity == 0:
        raise MissingCostBasisStateError(
            "직전 보유 상태 없이 SELL fill이 도착했다: "
            f"fill_event_id={fill.fill_event_id}, account_id={fill.account_id}, "
            f"instrument_id={fill.instrument_id}"
        )
    if fill.quantity > state.quantity:
        raise InsufficientPositionQuantityError(
            "보유 수량을 초과하는 SELL fill이다(숏 포지션 미지원): "
            f"fill_event_id={fill.fill_event_id}, held_quantity={state.quantity}, "
            f"sell_quantity={fill.quantity}"
        )

    old_average_cost = state.average_cost
    realized_pnl_gross = (fill.price - old_average_cost) * fill.quantity
    realized_pnl_net = realized_pnl_gross - fill.fee - fill.tax
    new_quantity = state.quantity - fill.quantity
    if new_quantity < 0:
        # 위의 fill.quantity > state.quantity 가드로 도달할 수 없어야 하는
        # 방어적 재확인이다 — 조용히 음수 잔량을 만들지 않는다.
        raise InsufficientPositionQuantityError(
            "SELL 반영 후 잔량이 음수가 된다(숏 포지션 미지원): "
            f"fill_event_id={fill.fill_event_id}, held_quantity={state.quantity}, "
            f"sell_quantity={fill.quantity}"
        )
    new_average_cost = Decimal("0") if new_quantity == 0 else old_average_cost

    new_state = PositionCostBasisStateEntity(
        account_id=fill.account_id,
        instrument_id=fill.instrument_id,
        quantity=new_quantity,
        average_cost=new_average_cost,
        last_applied_fill_event_id=fill.fill_event_id,
        last_applied_fill_timestamp=fill.fill_timestamp,
        recompute_required=False,
        recompute_reason=None,
    )
    event = RealizedPnlEventEntity(
        realized_pnl_event_id=_derive_realized_pnl_event_id(fill.fill_event_id),
        account_id=fill.account_id,
        instrument_id=fill.instrument_id,
        fill_event_id=fill.fill_event_id,
        broker_order_id=fill.broker_order_id,
        order_request_id=fill.order_request_id,
        sell_quantity=fill.quantity,
        sell_price=fill.price,
        avg_cost_basis_before=old_average_cost,
        fee=fill.fee,
        tax=fill.tax,
        fee_tax_source=fill.fee_tax_source,
        realized_pnl_gross=realized_pnl_gross,
        realized_pnl_net=realized_pnl_net,
        position_quantity_after=new_quantity,
        computation_run_id=computation_run_id,
        fill_timestamp=fill.fill_timestamp,
    )
    return new_state, event


def apply_fill_to_cost_basis(
    state: PositionCostBasisStateEntity | None,
    fill: NormalizedFill,
    *,
    computation_run_id: UUID,
) -> tuple[PositionCostBasisStateEntity, RealizedPnlEventEntity | None]:
    """체결 1건을 이동평균 원가 상태에 적용한다.

    **정렬 순서에 의존한다**: ``state``는 이 fill보다 먼저 정렬된(설계 문서
    5절 tie-break 기준) 모든 fill을 이미 반영한 상태여야 한다. 이 함수는
    그 순서를 검증하지 않는다 — 순서 보장은 호출자(:func:`replay_fills` 또는
    실시간 반영 훅) 책임이다.

    BUY
        평균단가를 갱신한다. ``RealizedPnlEventEntity``를 만들지 않는다.
        (v1 범위: 매수 수수료는 평균단가에 반영하지 않는다 — 후속 확장 후보.)

    SELL
        평균단가는 바꾸지 않는다. ``(fill.price - 기존 평균단가) * 수량``으로
        실현 손익을 계산하고 ``RealizedPnlEventEntity`` 1건을 반환한다.
        잔량이 0이 되면 평균단가를 0으로 리셋한다. 보유 수량을 초과하는
        SELL, 또는 보유 상태 자체가 없는 SELL은 예외로 명시 실패한다
        (개인 계좌 기준 숏 포지션 미지원).

    Raises
    ------
    InvalidFillQuantityError, InvalidFillPriceError, InvalidFeeOrTaxError,
    FeeTaxSourceMismatchError
        입력 fill 자체가 불변식을 위반하는 경우.
    MissingCostBasisStateError, InsufficientPositionQuantityError
        숏 포지션이 되는 SELL인 경우.
    """
    _validate_fill(fill)

    if fill.side == OrderSide.BUY:
        return _apply_buy(state, fill), None
    return _apply_sell(state, fill, computation_run_id=computation_run_id)


# ---------------------------------------------------------------------------
# Replay helper
# ---------------------------------------------------------------------------


def replay_fills(
    ordered_fills: Sequence[NormalizedFill],
    *,
    computation_run_id: UUID,
    initial_state: PositionCostBasisStateEntity | None = None,
) -> ReplayResult:
    """이미 정렬된 fill 시퀀스 전체를 순서대로 반영한다.

    이름 그대로 ``ordered_fills``는 **이미 정렬돼 있어야 한다**(설계 문서
    5절 tie-break 기준). 이 함수는 정렬을 수행하지 않으며, ``fill_timestamp``
    가 역행하는 것만 감지해 :class:`FillsNotSortedError`로 명시 실패한다
    (동일 ``fill_timestamp``가 연속되는 것은 허용 — 동시각 다건 체결은
    정상 케이스다). 그 이상의 out-of-order 복구 로직(재정렬, 부분 재계산
    등)은 이번 범위 밖이다.

    같은 ``ordered_fills``와 같은 ``initial_state``로 다시 호출하면 항상
    바이트 단위로 동일한 :class:`ReplayResult`를 반환한다(``uuid4()``나
    ``datetime.now()`` 같은 숨겨진 비결정 값을 쓰지 않기 때문).

    backfill replay(빈 ``initial_state``에서 계좌×종목 전체 히스토리를
    처음부터 다시 계산)와 향후 부분 재계산 helper 양쪽에서 재사용 가능하도록
    ``initial_state``를 주입식으로 받는다.
    """
    state = initial_state
    events: list[RealizedPnlEventEntity] = []
    previous_timestamp: datetime | None = (
        initial_state.last_applied_fill_timestamp if initial_state is not None else None
    )

    for fill in ordered_fills:
        if previous_timestamp is not None and fill.fill_timestamp < previous_timestamp:
            raise FillsNotSortedError(
                "ordered_fills가 fill_timestamp 기준으로 정렬돼 있지 않다: "
                f"fill_event_id={fill.fill_event_id}, fill_timestamp={fill.fill_timestamp}, "
                f"previous_timestamp={previous_timestamp}"
            )
        state, event = apply_fill_to_cost_basis(
            state, fill, computation_run_id=computation_run_id
        )
        if event is not None:
            events.append(event)
        previous_timestamp = fill.fill_timestamp

    return ReplayResult(final_state=state, realized_pnl_events=tuple(events))
