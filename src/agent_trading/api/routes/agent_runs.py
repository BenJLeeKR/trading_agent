"""Agent run inspection endpoint: ``GET /agent-runs``.

Returns AI Agent execution run records, optionally filtered by
``decision_context_id``.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import AgentRunResponse
from agent_trading.repositories.container import RepositoryContainer

router = APIRouter(tags=["agent-runs"])


def _to_response(run: object) -> AgentRunResponse:
    """Convert domain entity to API schema."""
    return AgentRunResponse(
        agent_run_id=run.agent_run_id,
        decision_context_id=run.decision_context_id,
        agent_type=run.agent_type,
        started_at=run.started_at,
        model_id=run.model_id,
        prompt_id=run.prompt_id,
        temperature=float(run.temperature) if run.temperature is not None else None,
        seed=run.seed,
        raw_output_uri=run.raw_output_uri,
        structured_output_json=run.structured_output_json,
        status=run.status,
        completed_at=run.completed_at,
        created_at=run.created_at,
    )


@router.get("/agent-runs", response_model=list[AgentRunResponse])
async def list_agent_runs(
    decision_context_id: str | None = Query(
        None, description="Filter by decision context ID (optional)"
    ),
    repos: RepositoryContainer = Depends(get_repos),
) -> list[AgentRunResponse]:
    """List AI Agent execution runs, optionally filtered by ``decision_context_id``.

    Returns runs ordered by ``started_at`` descending (most recent first).
    """
    if decision_context_id is not None:
        try:
            ctx_id = UUID(decision_context_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid UUID: {decision_context_id}"
            ) from exc

        runs = await repos.agent_runs.list_by_decision_context(ctx_id)
    else:
        runs = await repos.agent_runs.list_all()

    return [_to_response(r) for r in runs]
