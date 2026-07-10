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

    async def get(
        self, guardrail_evaluation_id: object
    ) -> GuardrailEvaluationEntity | None:
        """Get a single guardrail evaluation by its UUID."""
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.guardrail_evaluations "
            "WHERE guardrail_evaluation_id = $1",
            guardrail_evaluation_id,
        )
        return row_to_entity(row, GuardrailEvaluationEntity) if row else None

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

    async def get_by_decision_contexts(
        self, decision_context_ids: Sequence[object]
    ) -> dict[object, list[GuardrailEvaluationEntity]]:
        if not decision_context_ids:
            return {}
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.guardrail_evaluations "
            "WHERE decision_context_id = ANY($1::uuid[]) "
            "ORDER BY decision_context_id, evaluated_at",
            list(set(decision_context_ids)),
        )
        result: dict[object, list[GuardrailEvaluationEntity]] = {}
        for row in rows:
            entity = row_to_entity(row, GuardrailEvaluationEntity)
            result.setdefault(entity.decision_context_id, []).append(entity)
        return result

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

    async def list_by_account(
        self, account_id: object, limit: int = 20
    ) -> Sequence[GuardrailEvaluationEntity]:
        """List guardrail evaluations for an account via decision_context JOIN."""
        rows = await self._tx.connection.fetch(
            "SELECT ge.* FROM trading.guardrail_evaluations ge "
            "JOIN trading.decision_contexts dc "
            "ON ge.decision_context_id = dc.decision_context_id "
            "WHERE dc.account_id = $1 "
            "ORDER BY ge.evaluated_at DESC "
            "LIMIT $2",
            account_id,
            limit,
        )
        return tuple(row_to_entity(r, GuardrailEvaluationEntity) for r in rows)
