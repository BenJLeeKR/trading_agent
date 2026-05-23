"""Execution-attempt inspection endpoints:

- ``GET /execution-attempts`` — list by ``trade_decision_id`` (optional).
- ``GET /execution-attempts/{execution_attempt_id}`` — single attempt detail.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import (
    ExecutionAttemptDetail,
    ExecutionAttemptListResponse,
)
from agent_trading.repositories.container import RepositoryContainer

router = APIRouter(tags=["execution_attempts"])


@router.get(
    "/execution-attempts",
    response_model=ExecutionAttemptListResponse,
)
async def list_execution_attempts(
    trade_decision_id: str | None = Query(
        None, description="Filter by trade decision ID (optional)"
    ),
    repos: RepositoryContainer = Depends(get_repos),
) -> ExecutionAttemptListResponse:
    """List execution attempts, optionally filtered by ``trade_decision_id``."""
    if trade_decision_id is not None:
        try:
            td_id = UUID(trade_decision_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid trade_decision_id UUID: {trade_decision_id}",
            ) from exc
        attempts = await repos.execution_attempts.list_by_trade_decision(td_id)
    else:
        # No unfiltered list method — return empty (caller must filter).
        attempts = []

    return ExecutionAttemptListResponse(
        status="ok",
        data=[
            ExecutionAttemptDetail(
                execution_attempt_id=ea.execution_attempt_id,
                trade_decision_id=ea.trade_decision_id,
                decision_context_id=ea.decision_context_id,
                status=ea.status,
                stop_phase=ea.stop_phase,
                stop_reason=ea.stop_reason,
                phase_trace=ea.phase_trace,
                order_request_id=ea.order_request_id,
                started_at=ea.started_at,
                completed_at=ea.completed_at,
                created_at=ea.created_at,
            )
            for ea in attempts
        ],
    )


@router.get(
    "/execution-attempts/{execution_attempt_id}",
    response_model=ExecutionAttemptDetail,
)
async def get_execution_attempt(
    execution_attempt_id: str,
    repos: RepositoryContainer = Depends(get_repos),
) -> ExecutionAttemptDetail:
    """Get a single execution attempt by ID."""
    try:
        ea_id = UUID(execution_attempt_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid UUID: {execution_attempt_id}",
        ) from exc

    entity = await repos.execution_attempts.get(ea_id)
    if entity is None:
        raise HTTPException(
            status_code=404,
            detail=f"Execution attempt not found: {execution_attempt_id}",
        )

    return ExecutionAttemptDetail(
        execution_attempt_id=entity.execution_attempt_id,
        trade_decision_id=entity.trade_decision_id,
        decision_context_id=entity.decision_context_id,
        status=entity.status,
        stop_phase=entity.stop_phase,
        stop_reason=entity.stop_reason,
        phase_trace=entity.phase_trace,
        order_request_id=entity.order_request_id,
        started_at=entity.started_at,
        completed_at=entity.completed_at,
        created_at=entity.created_at,
    )
