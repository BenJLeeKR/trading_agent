"""Decision inspection endpoints: ``GET /trade-decisions``,
``GET /decision-contexts/{id}``.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import (
    DecisionContextDetail,
    PaginatedTradeDecisionsResponse,
    TradeDecisionDetail,
)
from agent_trading.repositories.container import RepositoryContainer

router = APIRouter(tags=["decisions"])


def _safe_enum_str(value: object) -> str:
    """Enum 또는 문자열 값을 API 응답용 문자열로 정규화."""
    if value is None:
        return ""
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str):
        return enum_value
    if isinstance(value, str):
        return value
    return str(value)


def _to_detail(d: object, instrument_name: str | None = None) -> TradeDecisionDetail:
    """Convert domain entity to API schema.

    ``instrument_name``은 SQL LEFT JOIN으로 미리 resolve된 값을 받아
    N+1 문제를 방지한다.
    """
    return TradeDecisionDetail(
        trade_decision_id=str(d.trade_decision_id),
        decision_context_id=str(d.decision_context_id),
        decision_type=_safe_enum_str(d.decision_type),
        side=_safe_enum_str(d.side),
        strategy_id=str(d.strategy_id),
        symbol=d.symbol,
        market=d.market,
        entry_style=_safe_enum_str(d.entry_style),
        created_at=d.created_at,
        entry_price=float(d.entry_price) if d.entry_price is not None else None,
        quantity=float(d.quantity) if d.quantity is not None else None,
        max_order_value=float(d.max_order_value) if d.max_order_value is not None else None,
        confidence=float(d.confidence) if d.confidence is not None else None,
        rationale_summary=d.rationale_summary,
        source_type=d.source_type,
        decision_json=d.decision_json,
        instrument_name=instrument_name,
    )


@router.get("/trade-decisions", response_model=PaginatedTradeDecisionsResponse)
async def list_trade_decisions(
    decision_context_id: str | None = Query(None, description="Decision context ID (optional)"),
    limit: int = Query(50, ge=1, le=500, description="페이지당 최대 항목 수"),
    offset: int = Query(0, ge=0, description="건너뛸 항목 수"),
    repos: RepositoryContainer = Depends(get_repos),
) -> PaginatedTradeDecisionsResponse:
    """List trade decisions with server-side pagination.

    ``decision_context_id``가 주어지면 해당 컨텍스트로 필터링.
    ``limit``: 페이지당 최대 항목 수 (기본 50, 최대 500).
    ``offset``: 건너뛸 항목 수 (기본 0).

    SQL LEFT JOIN으로 instrument_name을 한 번에 resolve하여
    N+1 문제를 방지한다.
    """
    ctx_id: UUID | None = None
    if decision_context_id is not None:
        try:
            ctx_id = UUID(decision_context_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid UUID: {decision_context_id}"
            ) from exc

    items_with_names, total = await repos.trade_decisions.list_all_paginated(
        limit=limit,
        offset=offset,
        decision_context_id=ctx_id,
    )

    # SQL LEFT JOIN으로 instrument_name이 이미 resolve되어 있음
    details = [_to_detail(d, instrument_name=name) for d, name in items_with_names]

    return PaginatedTradeDecisionsResponse(
        items=details,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/decision-contexts/{decision_context_id}", response_model=DecisionContextDetail)
async def get_decision_context(
    decision_context_id: str,
    repos: RepositoryContainer = Depends(get_repos),
) -> DecisionContextDetail:
    """Get a single decision context by ID."""
    try:
        uid = UUID(decision_context_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {decision_context_id}") from exc

    ctx = await repos.decision_contexts.get(uid)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"Decision context not found: {decision_context_id}")

    return DecisionContextDetail(
        decision_context_id=str(ctx.decision_context_id),
        account_id=str(ctx.account_id),
        strategy_id=str(ctx.strategy_id),
        config_version_id=str(ctx.config_version_id),
        market_timestamp=ctx.market_timestamp,
        correlation_id=ctx.correlation_id,
        trading_session_id=str(ctx.trading_session_id) if ctx.trading_session_id is not None else None,
        created_at=ctx.created_at,
    )
