"""Guardrail evaluation inspection endpoints: ``GET /guardrail-evaluations``.

Returns guardrail rule evaluation results, optionally filtered by
``account_id``, ``decision_context_id``, or ``order_request_id``.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import GuardrailEvaluationView
from agent_trading.repositories.container import RepositoryContainer

router = APIRouter(tags=["guardrail-evaluations"])


def _to_view(evaluation: object) -> GuardrailEvaluationView:
    """Convert domain entity to API schema."""
    return GuardrailEvaluationView(
        guardrail_evaluation_id=evaluation.guardrail_evaluation_id,
        rule_set_version=evaluation.rule_set_version,
        overall_passed=evaluation.overall_passed,
        evaluated_at=evaluation.evaluated_at,
        decision_context_id=evaluation.decision_context_id,
        trade_decision_id=evaluation.trade_decision_id,
        order_request_id=evaluation.order_request_id,
        rule_results=evaluation.rule_results,
        blocking_rule_codes=evaluation.blocking_rule_codes,
        warning_rule_codes=evaluation.warning_rule_codes,
        created_at=evaluation.created_at,
    )


@router.get("/guardrail-evaluations", response_model=list[GuardrailEvaluationView])
async def list_guardrail_evaluations(
    account_id: UUID | None = Query(
        None, description="Filter by account UUID (via decision_context join)"
    ),
    decision_context_id: UUID | None = Query(
        None, description="Filter by decision context UUID"
    ),
    order_request_id: UUID | None = Query(
        None, description="Filter by order request UUID"
    ),
    limit: int = Query(20, ge=1, le=200, description="Max results"),
    repos: RepositoryContainer = Depends(get_repos),
) -> list[GuardrailEvaluationView]:
    """List guardrail evaluations, optionally filtered.

    At most one filter parameter should be provided.  If none are given,
    an empty list is returned.
    """
    if account_id is not None:
        results = await repos.guardrail_evaluations.list_by_account(account_id, limit)
    elif decision_context_id is not None:
        results = await repos.guardrail_evaluations.get_by_decision_context(
            decision_context_id
        )
    elif order_request_id is not None:
        results = await repos.guardrail_evaluations.get_by_order_request(
            order_request_id
        )
    else:
        return []

    return [_to_view(r) for r in results]


@router.get(
    "/guardrail-evaluations/{evaluation_id}",
    response_model=GuardrailEvaluationView,
)
async def get_guardrail_evaluation(
    evaluation_id: UUID = Path(..., description="Guardrail evaluation UUID"),
    repos: RepositoryContainer = Depends(get_repos),
) -> GuardrailEvaluationView:
    """Get a single guardrail evaluation by its UUID."""
    evaluation = await repos.guardrail_evaluations.get(evaluation_id)
    if evaluation is None:
        raise HTTPException(
            status_code=404, detail="Guardrail evaluation not found"
        )
    return _to_view(evaluation)
