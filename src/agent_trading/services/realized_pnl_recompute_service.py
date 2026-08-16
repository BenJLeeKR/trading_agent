"""realized PnL ledger recompute/replay 복구 경로.

설계 근거: docs/00_foundational_design/detailed_design/12_realized_pnl_moving_average_ledger.md
(5절 정렬 키, 6절 idempotency/replay, 7절 out-of-order/정정, 8절 장애 시 복구 계약).

Responsibility
--------------
``realized_pnl_recompute_queue``에 쌓인(또는 ``position_cost_basis_state.
recompute_required=True``로 표시된) 계좌×종목을 **처음부터 다시 계산**해
ledger를 authoritative하게 복구한다. 계산 자체는 항상
:func:`agent_trading.services.realized_pnl_engine.replay_fills`에 위임한다
— 이동평균/실현손익 계산식을 여기서 다시 구현하지 않는다.

``RealizedPnlLedgerService``(단일 fill, 실시간 반영)와 이 서비스(계좌×종목
전체, batch replay)는 서로 다른 orchestration이다. 계산 엔진만 공유하고
저장 흐름은 공유하지 않는다 — 단일 fill 경로는 여전히 append-only
(``add()``)만 쓰고, 이 recompute 경로만 upsert(재계산 덮어쓰기)를 쓴다.

체결 입력 경로에 대한 전제
--------------------------
이 서비스는 ``trading.fill_events``만을 1차 입력으로 삼는다(KIS REST 기반
``_sync_fills()``가 저장한 행). ``broker_fill_snapshots``(VTTC0081R 백필)는
이번 단계에서도 replay 입력이 아니라 대사(reconciliation) 대상으로만
남긴다 — 설계 문서 10절과 동일한 경계를 유지한다.

정렬 규칙
---------
``fill_events``에는 계좌×종목이 없으므로, ``orders``/``broker_orders``를
경유해 대상 계좌×종목에 속한 모든 fill을 모은 뒤 설계 문서 5절 tie-break로
정렬한다: ``fill_timestamp`` → ``broker_fill_id``(NULL은 마지막) →
``created_at`` → ``fill_event_id``(최종 결정적 tie-break, 순서 의미는 없음).
``replay_fills()``는 정렬을 하지 않으므로 이 정렬 책임은 전적으로 이 모듈에
있다.

기존 ledger 데이터 재구성 방식(핵심 설계 판단)
----------------------------------------------
``realized_pnl_events.fill_event_id`` UNIQUE 제약 때문에, 당초 설계 문서
7.3절이 상정한 "``superseded_by_event_id``를 채운 별도 보정 행 append"는
**같은 fill_event_id로 두 번째 행을 만들 수 없어 그대로 구현할 수 없다**
(실제 구현 과정에서 확인). 대신 ``realized_pnl_event_id``가
``fill_event_id``로부터 결정론적으로 파생된다는 성질을 이용해, 같은
fill_event_id에 대해 **동일한 identity(realized_pnl_event_id)의 계산값을
다시 쓰는 upsert**로 정정한다(:meth:`RealizedPnlEventRepository.upsert`,
contracts.py 참고). 이것은 "다른 정정 행을 추가하는" 것이 아니라 "같은
사실(이 fill)에 대한 계산값을 authoritative하게 다시 쓰는" 것이므로
append-only 원칙("같은 fill을 두 번 다른 행으로 기록하지 않는다")과
충돌하지 않는다. ``superseded_by_event_id``는 이 경로에서 사용하지 않는다
(향후 수동 정정 도구가 별도 identity로 정정해야 하는 경우를 위해 필드
자체는 남겨 둔다).

``realized_pnl_daily_aggregates``는 이번 replay가 만든
``ReplayResult.realized_pnl_events`` 전체를 KST 날짜별로 그룹핑해 **그
날짜의 합계를 절대값으로 다시 쓴다**(증분 합산이 아니라 전체 재계산) —
이미 문서화된 대로 이 테이블은 "``realized_pnl_events``에서 언제든
재생성 가능한 파생 캐시"이기 때문이다. replay가 찾은 활동이 전혀 없는
날짜(예: 데이터 이상으로 생긴 phantom aggregate)는 이번 경로에서 0으로
되돌리지 않는다 — 그런 경우가 실제로 발생하는지는 별도 감사 대상으로
남긴다(아래 "알려진 한계" 참고).

idempotency / 안전성
--------------------
- 같은 recompute 대상을 두 번 처리해도 안전하다 — replay는 순수 함수라
  같은 입력에는 항상 같은 결과를 내고, upsert는 같은 identity를 다시
  쓸 뿐이라 재실행은 자연스럽게 idempotent하다.
- 쓰기 순서: events upsert → daily aggregate 재구성 → **마지막으로**
  ``position_cost_basis_state``의 ``recompute_required=False`` 반영 →
  queue resolve. 중간에 실패하면 상태가 여전히 ``recompute_required=True``
  로 남아 다음 재시도가 자연스럽게 다시 잡는다 — "일부만 반영된 채
  recompute_required만 조용히 해제되는" 상황을 피한다.
- 이 서비스는 자체적으로 DB 트랜잭션을 관리하지 않는다(``RepositoryContainer``
  를 받아 쓰는 이 저장소의 기존 관례와 동일) — 진짜 원자성이 필요하면
  호출자가 같은 트랜잭션으로 묶인 ``RepositoryContainer``를 넘겨야 한다.

BUY non-adjacent duplicate 한계와 replay의 관계
------------------------------------------------
``RealizedPnlLedgerService``의 실시간 반영 경로는 BUY dedup을
"가장 최근 적용 fill과의 일치"만 확인한다(그 한계는 그대로 유지된다,
이 PR에서 고치지 않는다). **replay는 이 한계를 물려받지 않는다** —
replay는 반복 호출로 같은 fill을 두 번 먹이는 구조가 아니라,
``fill_events`` 테이블의 **distinct 행**을 정렬해 정확히 한 번씩만
훑는다. ``fill_events`` 자체의 dedup(``order_sync_service._sync_fills()``,
``broker_fill_id`` 우선/composite key fallback)이 같은 실제 체결을 두 번
저장하지 않는 한, replay가 만드는 최종 ``position_cost_basis_state``는
실시간 경로의 (혹시 있었을) BUY 중복 누적 실수와 무관하게 항상 올바르다
— replay는 과거의 잘못된 incremental 상태를 신뢰하지 않고 fill_events
원본에서 처음부터 다시 계산하기 때문이다. 즉 recompute는 out-of-order
뿐 아니라 (가정상의) BUY non-adjacent 중복 문제에 대해서도 사실상의
안전망 역할을 한다. 단, ``fill_events`` 테이블 자체에 중복 행이 실제로
들어간 경우(그 자체 dedup이 뚫린 경우)는 replay도 그 중복을 그대로
반영한다 — 이 가정은 검증하지 못했다.

알려진 한계(이번 범위)
-----------------------
- ``fill_events`` 조회는 ``OrderRepository.list(OrderQuery(account_id=...))``
  로 계좌의 전체 주문을 가져온 뒤 애플리케이션에서 ``instrument_id``로
  필터링한다(``OrderQuery``에 ``instrument_id`` 필터가 없다). 매우 큰
  limit을 명시적으로 지정해 절단 위험을 낮췄지만, 이론상 한 계좌가
  그 limit을 넘는 주문을 가진 극단적 케이스는 다루지 않는다.
- daily aggregate의 phantom 값(activity가 전혀 없는 날짜에 남아있는
  잘못된 합계)을 0으로 되돌리는 처리는 하지 않는다 — 위 재구성 방식
  설명 참고.
- backfill 전체 러너(수천 개 계좌×종목을 스케줄에 따라 도는 것), API,
  Admin UI, ``recompute_queue``를 자동으로 소진하는 스케줄러 연결은
  이번 범위 밖이다. 이 모듈은 그 위에서 호출될 두 public 진입점만
  제공한다(:meth:`RealizedPnlRecomputeService.recompute_account_instrument`,
  :meth:`RealizedPnlRecomputeService.process_pending_queue`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from agent_trading.domain.entities import (
    FillEventEntity,
    RealizedPnlComputationRunEntity,
    RealizedPnlDailyAggregateEntity,
)
from agent_trading.domain.enums import RealizedPnlComputationRunType, RealizedPnlFeeTaxSource
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import OrderQuery
from agent_trading.services.realized_pnl_engine import (
    RealizedPnlEngineError,
    replay_fills,
)
from agent_trading.services.realized_pnl_ledger_service import (
    build_normalized_fill,
    to_kst_trade_date,
)

logger = logging.getLogger(__name__)

# OrderQuery(account_id=...) 기본 limit(100)은 recompute 목적에는 너무
# 작다 — 계좌 전체 주문 히스토리를 훑어 instrument_id로 걸러내야 하므로
# 실무상 도달하기 어려운 큰 값을 명시한다(위 모듈 docstring "알려진 한계").
_ORDER_LOOKUP_LIMIT = 100_000

__all__ = [
    "RecomputeOutcome",
    "RealizedPnlRecomputeService",
]


@dataclass(slots=True, frozen=True)
class RecomputeOutcome:
    """:meth:`RealizedPnlRecomputeService.recompute_account_instrument`의 반환 타입."""

    account_id: UUID
    instrument_id: UUID
    computation_run: RealizedPnlComputationRunEntity
    resolved_queue_item_ids: tuple[UUID, ...] = ()


class RealizedPnlRecomputeService:
    """계좌×종목 단위 recompute/replay 복구 서비스.

    계산은 전부 :func:`agent_trading.services.realized_pnl_engine.replay_fills`
    에 위임한다. 이 클래스는 (1) 정렬된 fill 시퀀스 준비, (2) replay 실행,
    (3) 결과를 저장소에 반영(upsert), (4) 성공/실패에 따른
    ``recompute_queue``/``recompute_required``/``computation_run`` 관측
    가능성 확보만 담당한다.
    """

    def __init__(self, repos: RepositoryContainer) -> None:
        self._repos = repos

    # ------------------------------------------------------------------
    # Public entrypoints
    # ------------------------------------------------------------------

    async def recompute_account_instrument(
        self, account_id: UUID, instrument_id: UUID
    ) -> RecomputeOutcome:
        """이 계좌×종목의 전체 fill 히스토리를 처음부터 다시 계산해 반영한다.

        ``recompute_queue``를 거치지 않고 직접 호출할 수 있다(예: 향후
        admin action). 성공 시 해당 계좌×종목의 pending queue 항목을
        전부 resolve하고 ``recompute_required``를 해제한다.
        """
        run = await self._repos.realized_pnl_computation_runs.add(
            RealizedPnlComputationRunEntity(
                computation_run_id=uuid4(),
                run_type=RealizedPnlComputationRunType.BACKFILL_REPLAY,
                status="running",
                fills_applied=0,
                fills_skipped_duplicate=0,
                fills_replayed=0,
                anomalies_detected=0,
                account_id=account_id,
                started_at=datetime.now(timezone.utc),
            )
        )

        try:
            ordered_fills = await self._collect_ordered_normalized_fills(
                account_id, instrument_id
            )
        except Exception as exc:  # noqa: BLE001 — 원인 불문 관측 대상(8절)
            run = await self._finalize_run(
                run,
                status="failed",
                anomalies_detected=1,
                summary={
                    "phase": "collect_fills",
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
            return RecomputeOutcome(account_id, instrument_id, run)

        try:
            replay_result = replay_fills(
                ordered_fills, computation_run_id=run.computation_run_id
            )
        except RealizedPnlEngineError as exc:
            run = await self._finalize_run(
                run,
                status="failed",
                anomalies_detected=1,
                summary={
                    "phase": "replay",
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
            return RecomputeOutcome(account_id, instrument_id, run)

        try:
            for event in replay_result.realized_pnl_events:
                await self._repos.realized_pnl_events.upsert(event)

            await self._rebuild_daily_aggregates(
                account_id,
                instrument_id,
                replay_result.realized_pnl_events,
                run.computation_run_id,
            )

            # recompute_required 해제는 마지막에 반영한다 — 그 전 단계가
            # 실패하면 상태는 여전히 recompute_required=True로 남아
            # 재시도가 자연스럽게 다시 잡는다(모듈 docstring "쓰기 순서").
            if replay_result.final_state is not None:
                cleared_state = replace(
                    replay_result.final_state,
                    recompute_required=False,
                    recompute_reason=None,
                )
                await self._repos.position_cost_basis_states.upsert(cleared_state)
        except Exception as exc:  # noqa: BLE001 — 원인 불문 관측 대상(8절)
            run = await self._finalize_run(
                run,
                status="failed",
                anomalies_detected=1,
                summary={
                    "phase": "persist",
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
            return RecomputeOutcome(account_id, instrument_id, run)

        run = await self._finalize_run(
            run,
            status="completed",
            fills_replayed=len(ordered_fills),
        )

        resolved_ids = await self._resolve_pending_queue_items(
            account_id, instrument_id, run.computation_run_id
        )
        return RecomputeOutcome(account_id, instrument_id, run, resolved_ids)

    async def process_pending_queue(
        self, *, limit: int = 100
    ) -> tuple[RecomputeOutcome, ...]:
        """``realized_pnl_recompute_queue`` pending 항목을 계좌×종목 단위로
        coalesce해 처리한다.

        같은 계좌×종목에 pending이 여러 건이어도 :meth:`recompute_account_instrument`
        는 한 번만 호출한다(중복 replay 방지) — 성공하면 그 계좌×종목의
        모든 pending 항목을 함께 resolve한다.
        """
        pending = await self._repos.realized_pnl_recompute_queue.list_pending(limit=limit)
        seen: set[tuple[UUID, UUID]] = set()
        outcomes: list[RecomputeOutcome] = []
        for item in pending:
            key = (item.account_id, item.instrument_id)
            if key in seen:
                continue
            seen.add(key)
            outcomes.append(
                await self.recompute_account_instrument(item.account_id, item.instrument_id)
            )
        return tuple(outcomes)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _collect_ordered_normalized_fills(
        self, account_id: UUID, instrument_id: UUID
    ) -> list:
        """대상 계좌×종목의 전체 fill을 모아 설계 문서 5절 tie-break로 정렬한다.

        ``order_requests``에서 시작해 ``broker_orders → fill_events``로
        내려가므로(``RealizedPnlLedgerService._resolve_lineage``의 반대
        방향), 여기서 얻는 fill들은 항상 유효한 lineage를 갖는다 —
        ``UnresolvedFillLineageError``가 발생할 수 없는 방향이다.

        ``historical_buy_fee_overlays``(16번 문서 §8.13, `007070` overlay
        파일럿)에 이 fill에 대한 overlay가 있으면, ``fill_events`` 원본은
        그대로 두고 이 조회 단계에서만 ``fill_fee``/``fill_tax``/
        ``fee_tax_source``를 overlay 값으로 override한 뒤
        :func:`build_normalized_fill`에 넘긴다 — overlay는 오직 이
        recompute 경로에서만 반영되고, 실시간 경로(``RealizedPnlLedgerService.
        apply_fill``)는 이 저장소를 전혀 참조하지 않는다.

        ``historical_sell_fee_tax_overlays``(16번 문서 §8.15, `007070`
        SELL fee/tax historical estimate 파일럿)도 같은 병합 지점에서
        같은 방식으로 처리한다 — BUY overlay를 먼저 적용한 사본 위에
        SELL overlay를 이어서 적용한다(한 fill은 실제로는 BUY 또는 SELL
        둘 중 하나이므로 두 overlay가 같은 fill에 동시에 존재하지는
        않지만, 순서를 고정해 어느 쪽이 있어도 결정론적으로 동작하게
        한다). BUY overlay는 ``fill_tax``를 항상 0으로 두지만, SELL
        overlay는 ``estimated_fee``/``estimated_tax``를 둘 다 반영한다
        (매도는 매도 수수료와 매도세가 별개로 존재하기 때문).
        """
        orders = await self._repos.orders.list(
            OrderQuery(account_id=account_id, limit=_ORDER_LOOKUP_LIMIT)
        )
        matching_orders = [o for o in orders if o.instrument_id == instrument_id]

        fill_rows: list[FillEventEntity] = []
        for order in matching_orders:
            broker_orders = await self._repos.broker_orders.list_by_order_request(
                order.order_request_id
            )
            for broker_order in broker_orders:
                fills = await self._repos.fill_events.list_by_broker_order(
                    broker_order.broker_order_id
                )
                for fill_event in fills:
                    effective_fill_event = fill_event

                    buy_overlay = await self._repos.historical_buy_fee_overlays.get_by_fill_event_id(
                        fill_event.fill_event_id
                    )
                    if buy_overlay is not None:
                        effective_fill_event = replace(
                            effective_fill_event,
                            fill_fee=buy_overlay.estimated_fee,
                            fill_tax=Decimal("0"),
                            fee_tax_source=RealizedPnlFeeTaxSource.HISTORICAL_POLICY_ESTIMATE.value,
                        )

                    sell_overlay = await self._repos.historical_sell_fee_tax_overlays.get_by_fill_event_id(
                        fill_event.fill_event_id
                    )
                    if sell_overlay is not None:
                        effective_fill_event = replace(
                            effective_fill_event,
                            fill_fee=sell_overlay.estimated_fee,
                            fill_tax=sell_overlay.estimated_tax,
                            fee_tax_source=RealizedPnlFeeTaxSource.HISTORICAL_POLICY_ESTIMATE.value,
                        )

                    normalized = build_normalized_fill(
                        effective_fill_event,
                        account_id=account_id,
                        instrument_id=instrument_id,
                        order_request_id=order.order_request_id,
                        side=order.side,
                    )
                    fill_rows.append((fill_event, normalized))

        fill_rows.sort(key=lambda pair: _fill_sort_key(pair[0]))
        return [normalized for _fill_event, normalized in fill_rows]

    async def _rebuild_daily_aggregates(
        self,
        account_id: UUID,
        instrument_id: UUID,
        events,
        computation_run_id: UUID,
    ) -> None:
        grouped: dict = {}
        for event in events:
            trade_date = to_kst_trade_date(event.fill_timestamp)
            grouped.setdefault(trade_date, []).append(event)

        for trade_date, day_events in grouped.items():
            net_sum = sum((e.realized_pnl_net for e in day_events), Decimal("0"))
            # UI용 파생 합계 캐시(도메인 계산 아님) — 절대값 재구성이므로
            # 그 날짜의 events 전체에서 매번 처음부터 다시 합산한다(증분 아님).
            buy_amount_sum = sum(
                (e.sell_quantity * e.avg_cost_basis_before for e in day_events), Decimal("0")
            )
            sell_amount_sum = sum(
                (e.sell_quantity * e.sell_price for e in day_events), Decimal("0")
            )
            fee_tax_sum = sum(
                (e.fee + e.tax for e in day_events), Decimal("0")
            )
            aggregate = RealizedPnlDailyAggregateEntity(
                account_id=account_id,
                instrument_id=instrument_id,
                trade_date=trade_date,
                realized_pnl_net_sum=net_sum,
                sell_event_count=len(day_events),
                computation_run_id=computation_run_id,
                buy_amount_sum=buy_amount_sum,
                sell_amount_sum=sell_amount_sum,
                fee_tax_sum=fee_tax_sum,
            )
            await self._repos.realized_pnl_daily_aggregates.upsert(aggregate)

    async def _resolve_pending_queue_items(
        self,
        account_id: UUID,
        instrument_id: UUID,
        computation_run_id: UUID,
    ) -> tuple[UUID, ...]:
        pending = await self._repos.realized_pnl_recompute_queue.list_pending(limit=1000)
        matching = [
            item
            for item in pending
            if item.account_id == account_id and item.instrument_id == instrument_id
        ]
        resolved_ids: list[UUID] = []
        for item in matching:
            await self._repos.realized_pnl_recompute_queue.mark_resolved(
                item.recompute_queue_id,
                resolved_by_computation_run_id=computation_run_id,
            )
            resolved_ids.append(item.recompute_queue_id)
        return tuple(resolved_ids)

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


def _fill_sort_key(fill_event: FillEventEntity):
    """설계 문서 5절 tie-break: fill_timestamp → broker_fill_id(NULL last)
    → created_at → fill_event_id(최종 결정적 tie-break, 순서 의미 없음).
    """
    broker_fill_rank = (
        (0, fill_event.broker_fill_id)
        if fill_event.broker_fill_id is not None
        else (1, "")
    )
    created_at = fill_event.created_at or datetime.max.replace(tzinfo=timezone.utc)
    return (
        fill_event.fill_timestamp,
        broker_fill_rank,
        created_at,
        str(fill_event.fill_event_id),
    )
