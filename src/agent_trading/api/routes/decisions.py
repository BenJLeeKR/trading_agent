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


def _to_detail(d: object) -> TradeDecisionDetail:
    """Convert domain entity to API schema."""
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
    )


async def _enrich_decision_detail(
    detail: TradeDecisionDetail,
    repos: RepositoryContainer,
) -> TradeDecisionDetail:
    """Resolve ``instrument_name`` from the decision's symbol + market."""
    if detail.symbol:
        inst = await repos.instruments.get_by_symbol(detail.symbol, detail.market)
        if inst is not None:
            detail.instrument_name = inst.name
    return detail


@router.get("/trade-decisions", response_model=list[TradeDecisionDetail])
async def list_trade_decisions(
    decision_context_id: str | None = Query(None, description="Decision context ID (optional)"),
    repos: RepositoryContainer = Depends(get_repos),
) -> list[TradeDecisionDetail]:
    """List trade decisions, optionally filtered by ``decision_context_id``."""
    if decision_context_id is not None:
        try:
            ctx_id = UUID(decision_context_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid UUID: {decision_context_id}"
            ) from exc

        decisions = await repos.trade_decisions.list_by_context(ctx_id)
        if not decisions:
            return []
        return [await _enrich_decision_detail(_to_detail(d), repos) for d in decisions]
    else:
        decisions = await repos.trade_decisions.list_all()
        return [await _enrich_decision_detail(_to_detail(d), repos) for d in decisions]


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
