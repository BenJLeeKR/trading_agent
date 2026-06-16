from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from agent_trading.domain.entities import GuardrailEvaluationEntity
from agent_trading.repositories.container import RepositoryContainer

logger = logging.getLogger(__name__)


async def persist_blocking_guardrail_evaluation(
    repos: RepositoryContainer,
    *,
    rule_set_version: str,
    blocking_rule_codes: list[str],
    rule_results: dict[str, object],
    decision_context_id: UUID | None = None,
    trade_decision_id: UUID | None = None,
    order_request_id: UUID | None = None,
) -> None:
    """Persist a blocking guardrail evaluation without interrupting flow."""
    try:
        guardrail_eval = GuardrailEvaluationEntity(
            guardrail_evaluation_id=uuid4(),
            decision_context_id=decision_context_id,
            trade_decision_id=trade_decision_id,
            order_request_id=order_request_id,
            rule_set_version=rule_set_version,
            overall_passed=False,
            evaluated_at=datetime.now(timezone.utc),
            rule_results=rule_results,
            blocking_rule_codes=blocking_rule_codes,
        )
        await repos.guardrail_evaluations.add(guardrail_eval)
    except Exception:
        logger.warning(
            "Failed to record guardrail evaluation rule_set=%s codes=%s",
            rule_set_version,
            blocking_rule_codes,
            exc_info=True,
        )
