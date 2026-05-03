from __future__ import annotations

import json
from collections.abc import Sequence

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import GuardrailEvaluationEntity


class PostgresGuardrailEvaluationRepository:
    """PostgreSQL implementation of ``GuardrailEvaluationRepository``.

    Stores guardrail rule evaluation results in the
    ``trading.guardrail_evaluations`` table.
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(
        self, evaluation: GuardrailEvaluationEntity
    ) -> GuardrailEvaluationEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.guardrail_evaluations
                (guardrail_evaluation_id,
                 decision_context_id, trade_decision_id, order_request_id,
                 rule_set_version, overall_passed, evaluated_at,
                 rule_results, blocking_rule_codes, warning_rule_codes)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10)
            RETURNING *
            """,
            evaluation.guardrail_evaluation_id,
            evaluation.decision_context_id,
            evaluation.trade_decision_id,
            evaluation.order_request_id,
            evaluation.rule_set_version,
            evaluation.overall_passed,
            evaluation.evaluated_at,
            json.dumps(evaluation.rule_results),
            evaluation.blocking_rule_codes,
            evaluation.warning_rule_codes,
        )
        return row_to_entity(row, GuardrailEvaluationEntity)

    async def get_by_decision_context(
        self, decision_context_id: object
    ) -> Sequence[GuardrailEvaluationEntity]:
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.guardrail_evaluations "
            "WHERE decision_context_id = $1 "
            "ORDER BY evaluated_at",
            decision_context_id,
        )
        return tuple(row_to_entity(r, GuardrailEvaluationEntity) for r in rows)

    async def get_by_order_request(
        self, order_request_id: object
    ) -> Sequence[GuardrailEvaluationEntity]:
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.guardrail_evaluations "
            "WHERE order_request_id = $1 "
            "ORDER BY evaluated_at",
            order_request_id,
        )
        return tuple(row_to_entity(r, GuardrailEvaluationEntity) for r in rows)
