from __future__ import annotations

import logging
from uuid import UUID

from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.validators import (
    ValidationResult,
    build_validation_context,
)

logger = logging.getLogger(__name__)


async def persist_validation_result(
    repos: RepositoryContainer,
    *,
    validation_context: ValidationContext,
    validation_result: ValidationResult,
) -> None:
    """공통 validation result를 guardrail evaluation으로 저장한다."""
    try:
        await repos.guardrail_evaluations.add(
            validation_result.to_guardrail_evaluation(
                context=validation_context,
            )
        )
    except Exception:
        logger.warning(
            "Failed to record validation result rule_set=%s blocking=%s",
            validation_result.rule_set_version,
            list(validation_result.blocking_rule_codes),
            exc_info=True,
        )


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
    await persist_validation_result(
        repos,
        validation_context=build_validation_context(
            decision_context_id=decision_context_id,
            trade_decision_id=trade_decision_id,
            order_request_id=order_request_id,
        ),
        validation_result=ValidationResult.blocked(
            rule_set_version=rule_set_version,
            blocking_rule_codes=blocking_rule_codes,
            rule_results=rule_results,
        ),
    )
