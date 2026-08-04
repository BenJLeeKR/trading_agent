"""realized PnL ledger write orchestration — 계산 엔진을 실제 저장 흐름에 연결.

설계 근거: docs/00_foundational_design/detailed_design/12_realized_pnl_moving_average_ledger.md
(4절 엔티티, 6절 idempotency/replay, 8절 장애 시 복구 계약).

Responsibility
--------------
이 모듈은 ``realized_pnl_engine.py``의 순수 함수(:func:`apply_fill_to_cost_basis`)를
**감싸는 orchestration 계층**이다. 계산식 자체는 절대 여기서 다시 구현하지
않는다. 이 서비스가 갖는 책임은 다음 4가지뿐이다.

1. ``FillEventEntity`` + join으로 얻은 계좌/종목/side 정보를
   :class:`~agent_trading.services.realized_pnl_engine.NormalizedFill`로
   정규화한다(:func:`build_normalized_fill`).
2. 현재 :class:`PositionCostBasisStateEntity`를 조회하고, idempotency/정렬
   순서를 확인한 뒤 엔진을 호출한다.
3. 결과(state/event)를 저장소에 쓰고, SELL이면 일자 집계를 갱신한다.
4. 실패·out-of-order를 조용히 넘기지 않고 ``realized_pnl_recompute_queue``
   append + ``position_cost_basis_state.recompute_required`` 표시로
   관측 가능하게 남긴다.

이 모듈은 계산 엔진과 달리 순수 함수가 아니다 — repository I/O,
``uuid4()``, ``datetime.now()``를 사용한다. 이것은 의도된 경계다:
``realized_pnl_engine.py``의 "숨겨진 비결정 값 금지" 원칙은 계산 자체에만
적용되고, 이 orchestration 계층이 새로 만드는 감사 레코드(computation run,
recompute queue 항목)의 id/시각 생성에는 적용되지 않는다.

체결 입력 경로에 대한 전제
--------------------------
이 서비스는 KIS REST 기반 ``_sync_fills()``가 저장한 ``fill_events``만을
입력으로 전제한다(action plan/설계 문서에 이미 명시). websocket fill writer
존재 여부는 여전히 미확인이며, 이 서비스는 그 경로가 있다고 가정하지 않는다.

Integration (다음 단계, 이번 PR 범위 밖)
---------------------------------------
``order_sync_service._sync_fills()``가 ``fill_events.add()``로 새 fill을
저장한 직후 :meth:`RealizedPnlLedgerService.apply_fill`을 호출하도록 훅을
추가하는 것이 다음 단계다. 이 서비스는 그 훅을 스스로 만들지 않는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from agent_trading.domain.entities import (
    FillEventEntity,
    PositionCostBasisStateEntity,
    RealizedPnlComputationRunEntity,
    RealizedPnlDailyAggregateEntity,
    RealizedPnlEventEntity,
    RealizedPnlRecomputeQueueEntity,
)
from agent_trading.domain.enums import OrderSide, RealizedPnlComputationRunType, RealizedPnlFeeTaxSource
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.realized_pnl_engine import (
    NormalizedFill,
    RealizedPnlEngineError,
    apply_fill_to_cost_basis,
)

logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))

__all__ = [
    "ApplyFillResult",
    "RealizedPnlOrchestrationError",
    "UnresolvedFillLineageError",
    "build_normalized_fill",
    "RealizedPnlLedgerService",
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RealizedPnlOrchestrationError(RuntimeError):
    """orchestration 계층 자체의 불변식 위반(계산 엔진 예외와는 구분한다)."""


class UnresolvedFillLineageError(RealizedPnlOrchestrationError):
    """``fill_event.broker_order_id → broker_order → order_request`` 조인이 끊어진 경우.

    ``broker_order`` 또는 ``order_request``를 찾을 수 없으면 side/account_id/
    instrument_id를 확정할 수 없어 계산 자체를 시도할 수 없다.
    ``realized_pnl_recompute_queue``는 account_id/instrument_id가
    ``NOT NULL`` FK라서 이 상황에서는 큐에 남길 수도 없다 — 대신
    ``computation_run``을 ``status='failed'``로 기록한 뒤 예외를 던져
    호출자가 조용히 넘기지 못하게 한다.
    """


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class ApplyFillResult:
    """:meth:`RealizedPnlLedgerService.apply_fill`의 반환 타입."""

    status: str
    """``"applied"`` | ``"skipped_duplicate"`` | ``"recompute_required"``."""

    computation_run: RealizedPnlComputationRunEntity
    state: PositionCostBasisStateEntity | None
    realized_pnl_event: RealizedPnlEventEntity | None
    recompute_queue_item: RealizedPnlRecomputeQueueEntity | None = None


@dataclass(slots=True, frozen=True)
class _FillLineage:
    account_id: UUID
    instrument_id: UUID
    order_request_id: UUID
    side: OrderSide


# ---------------------------------------------------------------------------
# fill → NormalizedFill 정규화
# ---------------------------------------------------------------------------


def _normalize_fee_tax(
    fill_fee: Decimal | None, fill_tax: Decimal | None
) -> tuple[Decimal, Decimal, RealizedPnlFeeTaxSource]:
    """fee/tax provenance 판정 규칙(고정).

    ``fill_fee``와 ``fill_tax``가 **둘 다** ``None``이면 브로커가 아무것도
    보고하지 않은 것으로 보고 ``ASSUMED_ZERO``(둘 다 0)로 처리한다. 둘 중
    하나라도 값이 있으면(0을 명시적으로 보고한 경우 포함) ``REPORTED``로
    보고 각각 ``None``인 쪽만 0으로 채운다. 이 규칙은 계산 엔진의
    ``FeeTaxSourceMismatchError`` 가드를 절대 위반하지 않도록 설계됐다
    (``ASSUMED_ZERO``는 오직 fee=0, tax=0 조합에서만 나온다).
    """
    if fill_fee is None and fill_tax is None:
        return Decimal("0"), Decimal("0"), RealizedPnlFeeTaxSource.ASSUMED_ZERO
    return (
        fill_fee if fill_fee is not None else Decimal("0"),
        fill_tax if fill_tax is not None else Decimal("0"),
        RealizedPnlFeeTaxSource.REPORTED,
    )


def build_normalized_fill(
    fill_event: FillEventEntity,
    *,
    account_id: UUID,
    instrument_id: UUID,
    order_request_id: UUID,
    side: OrderSide,
) -> NormalizedFill:
    """``FillEventEntity`` + join으로 얻은 계좌/종목/side 정보를 계산 엔진
    입력으로 정규화한다.

    ``fill_events``에는 ``account_id``/``instrument_id``/``side``가 없다
    (``broker_order_id → broker_orders.order_request_id → order_requests``
    로 join해야 한다 — :meth:`RealizedPnlLedgerService._resolve_lineage`
    참고). 이 함수는 그 join이 이미 끝난 뒤의 순수 변환만 담당한다.
    """
    fee, tax, fee_tax_source = _normalize_fee_tax(fill_event.fill_fee, fill_event.fill_tax)
    return NormalizedFill(
        fill_event_id=fill_event.fill_event_id,
        account_id=account_id,
        instrument_id=instrument_id,
        broker_order_id=fill_event.broker_order_id,
        order_request_id=order_request_id,
        side=side,
        quantity=fill_event.fill_quantity,
        price=fill_event.fill_price,
        fee=fee,
        tax=tax,
        fee_tax_source=fee_tax_source,
        fill_timestamp=fill_event.fill_timestamp,
    )


def _to_kst_trade_date(fill_timestamp: datetime) -> date:
    """``realized_pnl_daily_aggregates.trade_date`` 산정 규칙.

    ``fill_history_sync.py``의 ``_KST`` 상수와 동일한 정책(KST 기준 날짜)을
    따른다.
    """
    return fill_timestamp.astimezone(_KST).date()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class RealizedPnlLedgerService:
    """realized PnL ledger write orchestration.

    계산 로직은 항상 :func:`agent_trading.services.realized_pnl_engine.apply_fill_to_cost_basis`
    에 위임한다 — 이 클래스 안에서 이동평균/실현손익 계산식을 다시 쓰지 않는다.

    idempotency 보장 범위(현재 구현)
    --------------------------------
    - **SELL**: ``realized_pnl_events.fill_event_id`` UNIQUE 제약을 전제로,
      호출 전 ``get_by_fill_event_id()``로 이미 반영된 fill인지 확인한다.
      이 fill이 언제 적용됐든(바로 직전이든 오래전이든) 항상 정확하게
      감지된다.
    - **BUY**: ``realized_pnl_events``에 행이 생기지 않으므로 같은 방식의
      전역 dedup 앵커가 없다. 이 구현은
      ``state.last_applied_fill_event_id == fill_event.fill_event_id``만
      확인한다 — 즉 **"가장 최근에 적용된 fill과 정확히 같은 경우"만
      감지**한다. 그보다 이전에 적용된 BUY fill이 다시 들어오는
      non-adjacent 중복은 이 버전에서 감지되지 않고 수량이 다시 더해진다.
      완전한 방지에는 fill 단위 적용 이력(예: 별도 apply-log 테이블 또는
      적용된 fill_event_id 집합)이 필요하며, 스키마 변경을 늘리지 않기
      위해 이번 범위에서는 추가하지 않았다. 이 한계는 실서비스 연결
      전(다음 단계 계획 문서)에서 반드시 재검토해야 한다.
    """

    def __init__(self, repos: RepositoryContainer) -> None:
        self._repos = repos

    async def apply_fill(self, fill_event: FillEventEntity) -> ApplyFillResult:
        """체결 1건을 ledger에 반영한다.

        내부적으로 다음 순서로 진행한다.

        1. ``RealizedPnlComputationRunEntity``를 하나 만든다(이 호출
           1건 = run 1건 — 실시간 반영 경로의 관측 단위).
        2. ``broker_order → order_request`` join으로 계좌/종목/side를
           확정한다. 실패하면 run을 ``failed``로 마감하고
           :class:`UnresolvedFillLineageError`를 던진다(조용히 넘기지 않음).
        3. 현재 :class:`PositionCostBasisStateEntity`를 조회하고
           idempotency(위 클래스 docstring)를 확인한다 — 중복이면
           ``status="skipped_duplicate"``로 즉시 반환한다.
        4. 상태의 ``last_applied_fill_timestamp``보다 이 fill이 앞서 있으면
           (out-of-order) 엔진을 호출하지 않고
           ``realized_pnl_recompute_queue``에 등록 +
           ``recompute_required=True``로 표시한 뒤
           ``status="recompute_required"``로 반환한다.
        5. 엔진 호출이 예외를 던지면(불변식 위반) 마찬가지로
           recompute_queue/recompute_required로 남기고
           ``status="recompute_required"``로 반환한다.
        6. 성공하면 state를 upsert하고, SELL이면 event를 append한 뒤
           일자 집계를 갱신하고 ``status="applied"``로 반환한다.
        """
        run = await self._repos.realized_pnl_computation_runs.add(
            RealizedPnlComputationRunEntity(
                computation_run_id=uuid4(),
                run_type=RealizedPnlComputationRunType.REALTIME_INCREMENTAL,
                status="running",
                fills_applied=0,
                fills_skipped_duplicate=0,
                fills_replayed=0,
                anomalies_detected=0,
                started_at=datetime.now(timezone.utc),
            )
        )

        try:
            lineage = await self._resolve_lineage(fill_event)
        except UnresolvedFillLineageError as exc:
            await self._finalize_run(
                run,
                status="failed",
                anomalies_detected=1,
                summary={"error": str(exc), "error_type": type(exc).__name__},
            )
            raise

        normalized_fill = build_normalized_fill(
            fill_event,
            account_id=lineage.account_id,
            instrument_id=lineage.instrument_id,
            order_request_id=lineage.order_request_id,
            side=lineage.side,
        )

        state = await self._repos.position_cost_basis_states.get(
            lineage.account_id, lineage.instrument_id
        )

        is_duplicate, duplicate_event = await self._check_duplicate(
            state, fill_event, normalized_fill
        )
        if is_duplicate:
            run = await self._finalize_run(run, status="completed", fills_skipped_duplicate=1)
            return ApplyFillResult(
                status="skipped_duplicate",
                computation_run=run,
                state=state,
                realized_pnl_event=duplicate_event,
            )

        if (
            state is not None
            and state.last_applied_fill_timestamp is not None
            and normalized_fill.fill_timestamp < state.last_applied_fill_timestamp
        ):
            recompute_item = await self._record_recompute(
                account_id=lineage.account_id,
                instrument_id=lineage.instrument_id,
                reason_code="out_of_order_fill_detected",
                triggering_fill_event_id=fill_event.fill_event_id,
            )
            await self._mark_recompute_required(
                account_id=lineage.account_id,
                instrument_id=lineage.instrument_id,
                existing_state=state,
                reason="out_of_order_fill_detected",
            )
            run = await self._finalize_run(
                run,
                status="failed",
                anomalies_detected=1,
                summary={"reason": "out_of_order_fill_detected"},
            )
            return ApplyFillResult(
                status="recompute_required",
                computation_run=run,
                state=state,
                realized_pnl_event=None,
                recompute_queue_item=recompute_item,
            )

        try:
            new_state, event = apply_fill_to_cost_basis(
                state, normalized_fill, computation_run_id=run.computation_run_id
            )
        except RealizedPnlEngineError as exc:
            recompute_item = await self._record_recompute(
                account_id=lineage.account_id,
                instrument_id=lineage.instrument_id,
                reason_code="ledger_write_failed",
                triggering_fill_event_id=fill_event.fill_event_id,
            )
            await self._mark_recompute_required(
                account_id=lineage.account_id,
                instrument_id=lineage.instrument_id,
                existing_state=state,
                reason=f"engine_error:{type(exc).__name__}"[:64],
            )
            run = await self._finalize_run(
                run,
                status="failed",
                anomalies_detected=1,
                summary={"error": str(exc), "error_type": type(exc).__name__},
            )
            return ApplyFillResult(
                status="recompute_required",
                computation_run=run,
                state=state,
                realized_pnl_event=None,
                recompute_queue_item=recompute_item,
            )

        try:
            saved_state = await self._repos.position_cost_basis_states.upsert(new_state)
            saved_event: RealizedPnlEventEntity | None = None
            if event is not None:
                saved_event = await self._repos.realized_pnl_events.add(event)
                await self._update_daily_aggregate(saved_event)
        except Exception as exc:  # noqa: BLE001 — repository write 실패는 원인 불문 관측 대상
            recompute_item = await self._record_recompute(
                account_id=lineage.account_id,
                instrument_id=lineage.instrument_id,
                reason_code="ledger_write_failed",
                triggering_fill_event_id=fill_event.fill_event_id,
            )
            await self._mark_recompute_required(
                account_id=lineage.account_id,
                instrument_id=lineage.instrument_id,
                existing_state=state,
                reason=f"repository_write_failed:{type(exc).__name__}"[:64],
            )
            run = await self._finalize_run(
                run,
                status="failed",
                anomalies_detected=1,
                summary={"error": str(exc), "error_type": type(exc).__name__},
            )
            return ApplyFillResult(
                status="recompute_required",
                computation_run=run,
                state=state,
                realized_pnl_event=None,
                recompute_queue_item=recompute_item,
            )

        run = await self._finalize_run(run, status="completed", fills_applied=1)
        return ApplyFillResult(
            status="applied",
            computation_run=run,
            state=saved_state,
            realized_pnl_event=saved_event,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _resolve_lineage(self, fill_event: FillEventEntity) -> _FillLineage:
        broker_order = await self._repos.broker_orders.get(fill_event.broker_order_id)
        if broker_order is None:
            raise UnresolvedFillLineageError(
                f"broker_order를 찾을 수 없다: broker_order_id={fill_event.broker_order_id}, "
                f"fill_event_id={fill_event.fill_event_id}"
            )
        order_request = await self._repos.orders.get(broker_order.order_request_id)
        if order_request is None:
            raise UnresolvedFillLineageError(
                f"order_request를 찾을 수 없다: order_request_id={broker_order.order_request_id}, "
                f"fill_event_id={fill_event.fill_event_id}"
            )
        return _FillLineage(
            account_id=order_request.account_id,
            instrument_id=order_request.instrument_id,
            order_request_id=order_request.order_request_id,
            side=order_request.side,
        )

    async def _check_duplicate(
        self,
        state: PositionCostBasisStateEntity | None,
        fill_event: FillEventEntity,
        normalized_fill: NormalizedFill,
    ) -> tuple[bool, RealizedPnlEventEntity | None]:
        """``(is_duplicate, existing_event)``를 반환한다.

        SELL은 ``realized_pnl_events.fill_event_id`` UNIQUE 제약을 전제로
        기존 event 존재 여부를 직접 조회해 판정한다(언제 적용됐든 정확히
        감지된다). BUY는 event가 생기지 않으므로
        ``state.last_applied_fill_event_id``와의 일치만 확인한다 — 클래스
        docstring에 적은 대로 "가장 최근에 적용된 fill과 정확히 같은 경우"
        만 감지하는 제한적 dedup이다.
        """
        if normalized_fill.side == OrderSide.SELL:
            existing_event = await self._repos.realized_pnl_events.get_by_fill_event_id(
                fill_event.fill_event_id
            )
            return existing_event is not None, existing_event
        if state is not None and state.last_applied_fill_event_id == fill_event.fill_event_id:
            return True, None
        return False, None

    async def _update_daily_aggregate(
        self, event: RealizedPnlEventEntity
    ) -> RealizedPnlDailyAggregateEntity:
        trade_date = _to_kst_trade_date(event.fill_timestamp)
        existing_rows = await self._repos.realized_pnl_daily_aggregates.list_by_account_and_instrument(
            event.account_id,
            event.instrument_id,
            start_date=trade_date,
            end_date=trade_date,
        )
        existing = existing_rows[0] if existing_rows else None
        new_sum = (existing.realized_pnl_net_sum if existing else Decimal("0")) + event.realized_pnl_net
        new_count = (existing.sell_event_count if existing else 0) + 1
        aggregate = RealizedPnlDailyAggregateEntity(
            account_id=event.account_id,
            instrument_id=event.instrument_id,
            trade_date=trade_date,
            realized_pnl_net_sum=new_sum,
            sell_event_count=new_count,
            computation_run_id=event.computation_run_id,
        )
        return await self._repos.realized_pnl_daily_aggregates.upsert(aggregate)

    async def _record_recompute(
        self,
        *,
        account_id: UUID,
        instrument_id: UUID,
        reason_code: str,
        triggering_fill_event_id: UUID,
    ) -> RealizedPnlRecomputeQueueEntity:
        item = RealizedPnlRecomputeQueueEntity(
            recompute_queue_id=uuid4(),
            account_id=account_id,
            instrument_id=instrument_id,
            reason_code=reason_code,
            triggering_fill_event_id=triggering_fill_event_id,
        )
        return await self._repos.realized_pnl_recompute_queue.add(item)

    async def _mark_recompute_required(
        self,
        *,
        account_id: UUID,
        instrument_id: UUID,
        existing_state: PositionCostBasisStateEntity | None,
        reason: str,
    ) -> PositionCostBasisStateEntity:
        base = existing_state or PositionCostBasisStateEntity(
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=Decimal("0"),
            average_cost=Decimal("0"),
        )
        updated = replace(base, recompute_required=True, recompute_reason=reason)
        return await self._repos.position_cost_basis_states.upsert(updated)

    async def _finalize_run(
        self,
        run: RealizedPnlComputationRunEntity,
        *,
        status: str,
        fills_applied: int = 0,
        fills_skipped_duplicate: int = 0,
        fills_replayed: int = 0,
        anomalies_detected: int = 0,
        summary: dict[str, object] | None = None,
    ) -> RealizedPnlComputationRunEntity:
        updated = replace(
            run,
            status=status,
            fills_applied=run.fills_applied + fills_applied,
            fills_skipped_duplicate=run.fills_skipped_duplicate + fills_skipped_duplicate,
            fills_replayed=run.fills_replayed + fills_replayed,
            anomalies_detected=run.anomalies_detected + anomalies_detected,
            summary_json=summary if summary is not None else run.summary_json,
            completed_at=datetime.now(timezone.utc),
        )
        return await self._repos.realized_pnl_computation_runs.update_run(updated)
