"""Realized PnL ledger inspection endpoints (read-only).

``GET /performance/realized-pnl/positions`` — 계좌×종목 realized PnL 종목 누계 + 현재 상태.
``GET /performance/realized-pnl/events`` — 체결별 realized PnL event 목록.
``GET /performance/realized-pnl/daily`` — 계좌×단일 종목 일자별 realized PnL aggregate 목록.
``GET /performance/realized-pnl/summary`` — 계좌(전체/단일 종목) 기간 요약 + 종목별 분해.
``GET /performance/realized-pnl/daily-summary`` — 계좌 전체(모든 종목) 기간 **일자별** 요약.
``GET /performance/realized-pnl/recompute-queue`` — 미해결 recompute 큐 항목 목록.

이 endpoint들은 **read-only**이며 저장된 realized PnL ledger
(``position_cost_basis_state`` / ``realized_pnl_events`` /
``realized_pnl_daily_aggregates`` / ``realized_pnl_recompute_queue``)를
그대로 조회만 한다. 이동평균/실현손익 계산은 전혀 수행하지 않는다 —
계산 자체는 ``realized_pnl_engine.py``/``realized_pnl_ledger_service.py``/
``realized_pnl_recompute_service.py``에 전적으로 위임되어 있고, 이 route는
그 결과가 이미 저장된 값을 읽을 뿐이다.

``broker_fill_snapshots``(VTTC0081R)는 이 endpoint들의 조회 대상이 아니다
— 설계 문서 10절과 동일하게 대사(reconciliation) 전용으로 남긴다. 이
ledger는 KIS REST 기반 ``_sync_fills()``가 저장한 ``fill_events``를
authoritative 입력으로 삼는다는 전제도 그대로 유지한다.

Authoritative source 요약
--------------------------
- 체결 상세: ``realized_pnl_events`` (그대로 읽음).
- 일자 요약: ``realized_pnl_daily_aggregates`` (그대로 읽음).
- 종목 누계(``realized_pnl_net_cumulative``): ``realized_pnl_daily_aggregates``의
  해당 계좌×종목 전체 날짜 ``realized_pnl_net_sum``을 단순 합산한 값이다.
  이 합산은 이동평균/실현손익 재계산이 아니라 이미 저장된 파생 캐시 값을
  더하는 것뿐이다(``sum()`` 외 어떤 도메인 계산도 하지 않는다).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from agent_trading.api.deps import get_repos
from agent_trading.api.errors import build_http_exception
from agent_trading.api.schemas import (
    RealizedPnlDailyAggregateView,
    RealizedPnlDailyResponse,
    RealizedPnlDailySummaryResponse,
    RealizedPnlEventsResponse,
    RealizedPnlEventView,
    RealizedPnlPositionView,
    RealizedPnlRecomputeQueueItemView,
    RealizedPnlRecomputeQueueResponse,
    RealizedPnlSummaryInstrumentView,
    RealizedPnlSummaryResponse,
)
from agent_trading.repositories.container import RepositoryContainer

router = APIRouter(tags=["realized-pnl"])

_DEFAULT_EVENTS_LIMIT = 200
_DEFAULT_RECOMPUTE_QUEUE_LIMIT = 100


def _parse_uuid(value: str, *, field: str, request_path: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise build_http_exception(
            status_code=400,
            error_code=f"invalid_{field}",
            message=f"Invalid {field} UUID",
            field=field,
            expected="UUID string",
            received=value,
            request_path=request_path,
            next_action=f"check {field} format",
        )


def _parse_date(value: str, *, field: str, request_path: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise build_http_exception(
            status_code=400,
            error_code=f"invalid_{field}",
            message=f"Invalid {field} (use YYYY-MM-DD)",
            field=field,
            expected="YYYY-MM-DD",
            received=value,
            request_path=request_path,
            next_action=f"check {field} format",
        )


@router.get(
    "/performance/realized-pnl/positions",
    response_model=list[RealizedPnlPositionView],
)
async def list_realized_pnl_positions(
    account_id: str = Query(..., description="Account UUID"),
    instrument_id: str | None = Query(
        None, description="Optional instrument UUID — omit to list every instrument"
    ),
    repos: RepositoryContainer = Depends(get_repos),
) -> list[RealizedPnlPositionView]:
    """계좌×종목 단위 realized PnL 종목 누계와 현재 이동평균 상태를 나열한다.

    ``instrument_id``를 생략하면 계좌가 가진 모든 계좌×종목 상태를
    반환한다. 계산은 하지 않는다 — ``position_quantity``/``average_cost``/
    ``recompute_required``/``recompute_reason``은 ``position_cost_basis_state``
    를 그대로 읽은 값이고, ``realized_pnl_net_cumulative``는
    ``realized_pnl_daily_aggregates``의 저장된 일자 합계를 더한 값이다.
    """
    request_path = "/performance/realized-pnl/positions"
    aid = _parse_uuid(account_id, field="account_id", request_path=request_path)

    if instrument_id is not None:
        iid = _parse_uuid(instrument_id, field="instrument_id", request_path=request_path)
        state = await repos.position_cost_basis_states.get(aid, iid)
        states = [state] if state is not None else []
    else:
        states = list(await repos.position_cost_basis_states.list_by_account(aid))

    views: list[RealizedPnlPositionView] = []
    for state in states:
        daily_rows = await repos.realized_pnl_daily_aggregates.list_by_account_and_instrument(
            aid, state.instrument_id
        )
        cumulative = sum(
            (row.realized_pnl_net_sum for row in daily_rows), Decimal("0")
        )

        inst = await repos.instruments.get(state.instrument_id)
        views.append(
            RealizedPnlPositionView(
                account_id=state.account_id,
                instrument_id=state.instrument_id,
                symbol=inst.symbol if inst is not None else None,
                instrument_name=inst.name if inst is not None else None,
                position_quantity=state.quantity,
                average_cost=state.average_cost,
                recompute_required=state.recompute_required,
                recompute_reason=state.recompute_reason,
                realized_pnl_net_cumulative=cumulative,
                updated_at=state.updated_at,
            )
        )
    return views


@router.get(
    "/performance/realized-pnl/events",
    response_model=RealizedPnlEventsResponse,
)
async def list_realized_pnl_events(
    account_id: str = Query(..., description="Account UUID"),
    instrument_id: str = Query(..., description="Instrument UUID"),
    before: datetime | None = Query(
        None, description="Optional — only events with fill_timestamp before this instant"
    ),
    limit: int = Query(
        _DEFAULT_EVENTS_LIMIT, ge=1, le=1000, description="Maximum events to return"
    ),
    repos: RepositoryContainer = Depends(get_repos),
) -> RealizedPnlEventsResponse:
    """체결별 realized PnL event를 ``fill_timestamp`` 내림차순으로 나열한다.

    ``trading.realized_pnl_events``를 그대로 읽는다 — 계산은 하지 않는다.
    """
    request_path = "/performance/realized-pnl/events"
    aid = _parse_uuid(account_id, field="account_id", request_path=request_path)
    iid = _parse_uuid(instrument_id, field="instrument_id", request_path=request_path)

    events = await repos.realized_pnl_events.list_by_account_and_instrument(
        aid, iid, limit=limit, before=before
    )

    return RealizedPnlEventsResponse(
        account_id=aid,
        instrument_id=iid,
        limit=limit,
        before=before,
        events=[RealizedPnlEventView.model_validate(e) for e in events],
    )


@router.get(
    "/performance/realized-pnl/daily",
    response_model=RealizedPnlDailyResponse,
)
async def list_realized_pnl_daily(
    account_id: str = Query(..., description="Account UUID"),
    instrument_id: str = Query(..., description="Instrument UUID"),
    start_date: str | None = Query(None, description="Optional start date (YYYY-MM-DD)"),
    end_date: str | None = Query(None, description="Optional end date (YYYY-MM-DD)"),
    repos: RepositoryContainer = Depends(get_repos),
) -> RealizedPnlDailyResponse:
    """일자별 realized PnL aggregate를 ``trade_date`` 오름차순으로 나열한다.

    ``trading.realized_pnl_daily_aggregates``를 그대로 읽는다 — 계산은
    하지 않는다. 이 테이블 자체는 ``realized_pnl_events``에서 언제든
    재생성 가능한 파생 캐시이며(설계 문서 참고), 이 endpoint는 그 캐시를
    읽기만 한다.
    """
    request_path = "/performance/realized-pnl/daily"
    aid = _parse_uuid(account_id, field="account_id", request_path=request_path)
    iid = _parse_uuid(instrument_id, field="instrument_id", request_path=request_path)

    sd: date | None = None
    if start_date is not None:
        sd = _parse_date(start_date, field="start_date", request_path=request_path)

    ed: date | None = None
    if end_date is not None:
        ed = _parse_date(end_date, field="end_date", request_path=request_path)

    if sd is not None and ed is not None and sd > ed:
        raise build_http_exception(
            status_code=400,
            error_code="invalid_date_range",
            message="start_date must be on or before end_date",
            field="start_date,end_date",
            expected="start_date <= end_date",
            request_path=request_path,
            next_action="check date range",
        )

    rows = await repos.realized_pnl_daily_aggregates.list_by_account_and_instrument(
        aid, iid, start_date=sd, end_date=ed
    )

    return RealizedPnlDailyResponse(
        account_id=aid,
        instrument_id=iid,
        start_date=sd,
        end_date=ed,
        daily=[RealizedPnlDailyAggregateView.model_validate(r) for r in rows],
    )


@router.get(
    "/performance/realized-pnl/summary",
    response_model=RealizedPnlSummaryResponse,
)
async def get_realized_pnl_summary(
    account_id: str = Query(..., description="Account UUID"),
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    instrument_id: str | None = Query(
        None, description="Optional instrument UUID — omit to summarize every instrument"
    ),
    repos: RepositoryContainer = Depends(get_repos),
) -> RealizedPnlSummaryResponse:
    """계좌(전체 종목 또는 단일 종목) 기간 요약 — Admin UI 실현손익 화면의

    요약 카드 + 종목별 탭을 위한 단일 호출 조회다. ``instrument_id``를
    생략하면 ``realized_pnl_daily_aggregates.list_by_account()``로 계좌의
    모든 종목을 **한 번의 조회**로 가져온 뒤 종목별로 그룹핑해 합산한다 —
    종목마다 개별 ``daily`` 호출을 반복하던 프런트의 N+1을 없애기 위한
    endpoint다(``design/realized_pnl_screen_spec.md`` P1 항목).

    계산은 하지 않는다 — 여기서 하는 산술은 ``realized_pnl_daily_aggregates``
    에 이미 저장된 5개 합계 필드(``realized_pnl_net_sum``/``sell_event_count``/
    ``buy_amount_sum``/``sell_amount_sum``/``fee_tax_sum``)를 종목별로,
    다시 전체로 더하는 것뿐이다. 이동평균 원가나 실현손익 자체를 다시
    산출하지 않는다 — 그 값은 항상 ``realized_pnl_engine.py``가 계산해
    저장한 값을 그대로 읽는다.

    ``recompute_required``는 ``position_cost_basis_state``를 그대로 읽는다
    (``PositionCostBasisStateRepository`` 확장 없이 기존
    ``get()``/``list_by_account()``만 사용).
    """
    request_path = "/performance/realized-pnl/summary"
    aid = _parse_uuid(account_id, field="account_id", request_path=request_path)
    sd = _parse_date(start_date, field="start_date", request_path=request_path)
    ed = _parse_date(end_date, field="end_date", request_path=request_path)

    if sd > ed:
        raise build_http_exception(
            status_code=400,
            error_code="invalid_date_range",
            message="start_date must be on or before end_date",
            field="start_date,end_date",
            expected="start_date <= end_date",
            request_path=request_path,
            next_action="check date range",
        )

    grouped: dict[UUID, list] = {}
    recompute_by_instrument: dict[UUID, bool] = {}
    target_instrument_id: UUID | None = None

    if instrument_id is not None:
        iid = _parse_uuid(instrument_id, field="instrument_id", request_path=request_path)
        target_instrument_id = iid
        rows = await repos.realized_pnl_daily_aggregates.list_by_account_and_instrument(
            aid, iid, start_date=sd, end_date=ed
        )
        # 단일 종목 조회는 활동이 전혀 없어도(0건) by_instrument에 그 종목을
        # 항상 노출한다 — 사용자가 명시적으로 그 종목을 지정했기 때문이다.
        grouped[iid] = list(rows)
        state = await repos.position_cost_basis_states.get(aid, iid)
        recompute_by_instrument[iid] = state.recompute_required if state is not None else False
    else:
        rows = await repos.realized_pnl_daily_aggregates.list_by_account(
            aid, start_date=sd, end_date=ed
        )
        for row in rows:
            grouped.setdefault(row.instrument_id, []).append(row)
        # 종목 "전체"는 활동이 없는 종목까지 나열하지 않는다(빈 상태 원칙 —
        # daily aggregate 자체가 활동이 있는 날에만 생성되므로 grouped에
        # 없는 종목은 이 기간에 실현손익 활동이 없었던 것이다).
        states = await repos.position_cost_basis_states.list_by_account(aid)
        recompute_by_instrument = {s.instrument_id: s.recompute_required for s in states}

    by_instrument: list[RealizedPnlSummaryInstrumentView] = []
    total_net = Decimal("0")
    total_count = 0
    total_buy = Decimal("0")
    total_sell = Decimal("0")
    total_fee_tax = Decimal("0")
    recompute_pending_count = 0

    for iid_key in sorted(grouped, key=str):
        agg_rows = grouped[iid_key]
        net = sum((r.realized_pnl_net_sum for r in agg_rows), Decimal("0"))
        count = sum(r.sell_event_count for r in agg_rows)
        buy = sum((r.buy_amount_sum for r in agg_rows), Decimal("0"))
        sell = sum((r.sell_amount_sum for r in agg_rows), Decimal("0"))
        fee_tax = sum((r.fee_tax_sum for r in agg_rows), Decimal("0"))
        recompute_required = recompute_by_instrument.get(iid_key, False)

        inst = await repos.instruments.get(iid_key)
        by_instrument.append(
            RealizedPnlSummaryInstrumentView(
                instrument_id=iid_key,
                symbol=inst.symbol if inst is not None else None,
                instrument_name=inst.name if inst is not None else None,
                realized_pnl_net_sum=net,
                sell_event_count=count,
                buy_amount_sum=buy,
                sell_amount_sum=sell,
                fee_tax_sum=fee_tax,
                recompute_required=recompute_required,
            )
        )

        total_net += net
        total_count += count
        total_buy += buy
        total_sell += sell
        total_fee_tax += fee_tax
        if recompute_required:
            recompute_pending_count += 1

    return RealizedPnlSummaryResponse(
        account_id=aid,
        instrument_id=target_instrument_id,
        start_date=sd,
        end_date=ed,
        realized_pnl_net_sum=total_net,
        sell_event_count=total_count,
        buy_amount_sum=total_buy,
        sell_amount_sum=total_sell,
        fee_tax_sum=total_fee_tax,
        recompute_pending_count=recompute_pending_count,
        by_instrument=by_instrument,
    )


@router.get(
    "/performance/realized-pnl/daily-summary",
    response_model=RealizedPnlDailySummaryResponse,
)
async def get_realized_pnl_daily_summary(
    account_id: str = Query(..., description="Account UUID"),
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    repos: RepositoryContainer = Depends(get_repos),
) -> RealizedPnlDailySummaryResponse:
    """계좌 전체(모든 종목) 기간 **일자별** 요약 — Admin UI 탭 A(일자별)의

    종목 "전체" N+1(종목마다 개별 ``daily`` 호출 후 프런트에서 날짜별 합산)을
    없애기 위한 단일 호출 조회다. ``/performance/realized-pnl/summary``가
    이미 쓰는 ``realized_pnl_daily_aggregates.list_by_account()``(신규
    repository 메서드 없음)로 계좌의 모든 종목을 한 번에 가져온 뒤,
    ``summary``가 종목별로 묶는 것과 달리 이 endpoint는 **날짜별**로 묶어
    5개 합계 필드를 더한다 — 역할이 분리돼 있을 뿐 계산 로직은 없다(``sum()``
    외 어떤 도메인 계산도 하지 않는다).

    기존 ``/performance/realized-pnl/daily``(계좌×**단일** 종목 전용,
    ``instrument_id`` 필수)는 계약을 바꾸지 않고 그대로 유지한다 — 이
    endpoint는 그 계약을 건드리지 않는 **추가** 경로다.
    """
    request_path = "/performance/realized-pnl/daily-summary"
    aid = _parse_uuid(account_id, field="account_id", request_path=request_path)
    sd = _parse_date(start_date, field="start_date", request_path=request_path)
    ed = _parse_date(end_date, field="end_date", request_path=request_path)

    if sd > ed:
        raise build_http_exception(
            status_code=400,
            error_code="invalid_date_range",
            message="start_date must be on or before end_date",
            field="start_date,end_date",
            expected="start_date <= end_date",
            request_path=request_path,
            next_action="check date range",
        )

    rows = await repos.realized_pnl_daily_aggregates.list_by_account(
        aid, start_date=sd, end_date=ed
    )

    grouped: dict[date, list] = {}
    for row in rows:
        grouped.setdefault(row.trade_date, []).append(row)

    daily: list[RealizedPnlDailyAggregateView] = []
    for trade_date in sorted(grouped):
        day_rows = grouped[trade_date]
        daily.append(
            RealizedPnlDailyAggregateView(
                trade_date=trade_date,
                realized_pnl_net_sum=sum(
                    (r.realized_pnl_net_sum for r in day_rows), Decimal("0")
                ),
                sell_event_count=sum(r.sell_event_count for r in day_rows),
                buy_amount_sum=sum(
                    (r.buy_amount_sum for r in day_rows), Decimal("0")
                ),
                sell_amount_sum=sum(
                    (r.sell_amount_sum for r in day_rows), Decimal("0")
                ),
                fee_tax_sum=sum((r.fee_tax_sum for r in day_rows), Decimal("0")),
            )
        )

    return RealizedPnlDailySummaryResponse(
        account_id=aid, start_date=sd, end_date=ed, daily=daily
    )


@router.get(
    "/performance/realized-pnl/recompute-queue",
    response_model=RealizedPnlRecomputeQueueResponse,
)
async def list_realized_pnl_recompute_queue(
    account_id: str | None = Query(
        None, description="Optional account UUID filter"
    ),
    instrument_id: str | None = Query(
        None, description="Optional instrument UUID filter (requires account_id)"
    ),
    limit: int = Query(
        _DEFAULT_RECOMPUTE_QUEUE_LIMIT, ge=1, le=1000,
        description="Maximum pending queue items to scan",
    ),
    repos: RepositoryContainer = Depends(get_repos),
) -> RealizedPnlRecomputeQueueResponse:
    """미해결(``resolved_at IS NULL``) recompute 큐 항목을 나열한다.

    ``recompute_required`` 상태 자체는
    ``/performance/realized-pnl/positions``의 같은 필드로도 확인할 수
    있다 — 이 endpoint는 "왜/언제 큐에 들어갔는지"(``reason_code``/
    ``requested_at``/``triggering_fill_event_id``)를 보는 별도 경로다.
    ``RealizedPnlRecomputeQueueRepository.list_pending()``은 계좌 필터가
    없으므로, ``account_id``/``instrument_id``가 주어지면 이 endpoint가
    조회 후 애플리케이션 레벨에서 필터링한다(계산이 아니라 단순 필터).
    """
    request_path = "/performance/realized-pnl/recompute-queue"

    aid: UUID | None = None
    if account_id is not None:
        aid = _parse_uuid(account_id, field="account_id", request_path=request_path)

    iid: UUID | None = None
    if instrument_id is not None:
        iid = _parse_uuid(instrument_id, field="instrument_id", request_path=request_path)

    items = await repos.realized_pnl_recompute_queue.list_pending(limit=limit)
    if aid is not None:
        items = [item for item in items if item.account_id == aid]
    if iid is not None:
        items = [item for item in items if item.instrument_id == iid]

    return RealizedPnlRecomputeQueueResponse(
        account_id=aid,
        instrument_id=iid,
        limit=limit,
        items=[RealizedPnlRecomputeQueueItemView.model_validate(item) for item in items],
    )
