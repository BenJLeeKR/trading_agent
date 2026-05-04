"""Decision inspection endpoints: ``GET /trade-decisions``,
``GET /decision-contexts/{id}``.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import DecisionContextDetail, TradeDecisionDetail
from agent_trading.repositories.container import RepositoryContainer

router = APIRouter(tags=["decisions"])


@router.get("/trade-decisions", response_model=list[TradeDecisionDetail])
async def list_trade_decisions(
    decision_context_id: str = Query(..., description="Decision context ID (required)"),
    repos: RepositoryContainer = Depends(get_repos),
) -> list[TradeDecisionDetail]:
    """List trade decisions filtered by ``decision_context_id``."""
    try:
        ctx_id = UUID(decision_context_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid UUID: {decision_context_id}"
        ) from exc

    decision = await repos.trade_decisions.get_by_context(ctx_id)
    if decision is None:
        return []

    return [
        TradeDecisionDetail(
            trade_decision_id=str(decision.trade_decision_id),
            decision_context_id=str(decision.decision_context_id),
            decision_type=decision.decision_type.value,
            side=decision.side.value,
            strategy_id=str(decision.strategy_id),
            symbol=decision.symbol,
            market=decision.market,
            entry_style=decision.entry_style.value,
            created_at=decision.created_at,
            entry_price=float(decision.entry_price) if decision.entry_price is not None else None,
            quantity=float(decision.quantity) if decision.quantity is not None else None,
            max_order_value=float(decision.max_order_value) if decision.max_order_value is not None else None,
        )
    ]


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
        created_at=ctx.created_at,
    )
