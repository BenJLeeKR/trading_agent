"""Performance summary inspection endpoint.

``GET /performance-summary`` — paper 운용 성과 요약.
``GET /performance-history`` — 기간 필터 기반 일별 성과 히스토리.
``GET /performance-metrics`` — 기간 기반 cumulative return / drawdown / win-rate.

계좌 수준 또는 전략 수준의 PnL/equity 요약,
일별 시계열 히스토리, 그리고 기간 기반 성과 지표를 반환합니다.
이 endpoint들은 **read-only**이며, 어떤 데이터도 변경하지 않습니다.
"""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import (
    AccountPerformanceSummaryView,
    DailyPerformancePointView,
    PerformanceHistoryResponse,
    PerformanceMetricsView,
    StrategyPerformanceSummaryView,
)
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.performance_summary import PerformanceSummaryService

router = APIRouter(tags=["performance"])


@router.get(
    "/performance-summary",
    response_model=AccountPerformanceSummaryView,
)
async def get_performance_summary(
    account_id: str = Query(..., description="Account UUID"),
    strategy_id: str | None = Query(
        None, description="Optional strategy UUID for strategy-level summary"
    ),
    repos: RepositoryContainer = Depends(get_repos),
) -> AccountPerformanceSummaryView | StrategyPerformanceSummaryView:
    """Get paper performance summary for an account.

    Returns account-level PnL/equity summary by default.
    When ``strategy_id`` is provided, returns strategy-level summary
    (subset of metrics scoped to that strategy).

    Parameters
    ----------
    account_id:
        Target account UUID (required).
    strategy_id:
        Optional strategy UUID. When provided, the response includes
        strategy-scoped metrics.

    Returns
    -------
    AccountPerformanceSummaryView
        Account-level performance summary (default).
    StrategyPerformanceSummaryView
        Strategy-level performance summary (when ``strategy_id`` is given).
    """
    try:
        aid = UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account_id UUID")

    service = PerformanceSummaryService(repos)

    if strategy_id is not None:
        try:
            sid = UUID(strategy_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid strategy_id UUID")

        summary = await service.get_strategy_summary(aid, sid)
        return StrategyPerformanceSummaryView.model_validate(summary)

    summary = await service.get_account_summary(aid)
    return AccountPerformanceSummaryView.model_validate(summary)


@router.get(
    "/performance-history",
    response_model=PerformanceHistoryResponse,
)
async def get_performance_history(
    account_id: str = Query(..., description="Account UUID"),
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    strategy_id: str | None = Query(
        None, description="Optional strategy UUID for strategy-filtered history"
    ),
    repos: RepositoryContainer = Depends(get_repos),
) -> PerformanceHistoryResponse:
    """Get daily performance history for an account.

    Returns a time-series of daily performance points from ``start_date``
    to ``end_date`` (inclusive). Each point includes realized PnL,
    cumulative realized PnL, cash balance, position market value,
    unrealized PnL, and total equity.

    Parameters
    ----------
    account_id:
        Target account UUID (required).
    start_date:
        Start date in ``YYYY-MM-DD`` format (inclusive, required).
    end_date:
        End date in ``YYYY-MM-DD`` format (inclusive, required).
    strategy_id:
        Optional strategy UUID. When provided, only orders belonging
        to that strategy are included in realized PnL aggregation.

    Returns
    -------
    PerformanceHistoryResponse
        Time-series of daily performance points.
    """
    try:
        aid = UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account_id UUID")

    try:
        sd = date.fromisoformat(start_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid start_date (use YYYY-MM-DD)")

    try:
        ed = date.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid end_date (use YYYY-MM-DD)")

    if sd > ed:
        raise HTTPException(
            status_code=400,
            detail="start_date must be on or before end_date",
        )

    sid: UUID | None = None
    if strategy_id is not None:
        try:
            sid = UUID(strategy_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid strategy_id UUID")

    service = PerformanceSummaryService(repos)
    points = await service.get_daily_history(aid, sd, ed, strategy_id=sid)

    return PerformanceHistoryResponse(
        account_id=account_id,
        start_date=sd,
        end_date=ed,
        strategy_id=strategy_id,
        points=[DailyPerformancePointView.model_validate(p) for p in points],
    )


@router.get(
    "/performance-metrics",
    response_model=PerformanceMetricsView,
)
async def get_performance_metrics(
    account_id: str = Query(..., description="Account UUID"),
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    strategy_id: str | None = Query(
        None, description="Optional strategy UUID for strategy-filtered metrics"
    ),
    repos: RepositoryContainer = Depends(get_repos),
) -> PerformanceMetricsView:
    """Get performance metrics for an account over a date range.

    Computes cumulative return, drawdown, win-rate, avg win/loss,
    and profit factor from the equity history and per-order PnL
    between ``start_date`` and ``end_date`` (inclusive).

    Parameters
    ----------
    account_id:
        Target account UUID (required).
    start_date:
        Start date in ``YYYY-MM-DD`` format (inclusive, required).
    end_date:
        End date in ``YYYY-MM-DD`` format (inclusive, required).
    strategy_id:
        Optional strategy UUID. When provided, only orders belonging
        to that strategy are included.

    Returns
    -------
    PerformanceMetricsView
        Period-based performance metrics (19 fields).
    """
    try:
        aid = UUID(account_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account_id UUID")

    try:
        sd = date.fromisoformat(start_date)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid start_date (use YYYY-MM-DD)"
        )

    try:
        ed = date.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid end_date (use YYYY-MM-DD)"
        )

    if sd > ed:
        raise HTTPException(
            status_code=400,
            detail="start_date must be on or before end_date",
        )

    sid: UUID | None = None
    if strategy_id is not None:
        try:
            sid = UUID(strategy_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid strategy_id UUID")

    service = PerformanceSummaryService(repos)
    metrics = await service.get_performance_metrics(aid, sd, ed, strategy_id=sid)

    return PerformanceMetricsView.model_validate(metrics)
