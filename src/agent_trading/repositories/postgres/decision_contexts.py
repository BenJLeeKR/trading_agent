from __future__ import annotations

from uuid import UUID

import asyncpg

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import DecisionContextEntity
from agent_trading.repositories.filters import DecisionContextQuery


class PostgresDecisionContextRepository:
    """PostgreSQL implementation of ``DecisionContextRepository``.

    Satisfies the protocol defined in ``repositories/contracts.py``.

    This is a replay-critical repository — ``DecisionContext`` is the
    fundamental unit of replay. The ``correlation_id`` enables tracking
    of decision units, and ``market_timestamp`` enables point-in-time
    reconstruction.
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(self, context: DecisionContextEntity) -> DecisionContextEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.decision_contexts
                (decision_context_id, account_id, strategy_id, config_version_id,
                 market_timestamp, correlation_id, strategy_version_id,
                 trading_session_id, feature_snapshot_id, signal_feature_snapshot_id,
                 position_snapshot_id, cash_balance_snapshot_id, input_bundle_uri)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            RETURNING *
            """,
            context.decision_context_id,
            context.account_id,
            context.strategy_id,
            context.config_version_id,
            context.market_timestamp,
            context.correlation_id,
            context.strategy_version_id,
            context.trading_session_id,
            context.feature_snapshot_id,
            context.signal_feature_snapshot_id,
            context.position_snapshot_id,
            context.cash_balance_snapshot_id,
            context.input_bundle_uri,
        )
        return row_to_entity(row, DecisionContextEntity)

    async def get(self, decision_context_id: UUID) -> DecisionContextEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.decision_contexts WHERE decision_context_id = $1",
            decision_context_id,
        )
        return row_to_entity(row, DecisionContextEntity) if row else None

    async def get_by_correlation_id(
        self, correlation_id: str
    ) -> DecisionContextEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.decision_contexts WHERE correlation_id = $1",
            correlation_id,
        )
        return row_to_entity(row, DecisionContextEntity) if row else None

    async def list(
        self, query: DecisionContextQuery
    ) -> list[DecisionContextEntity]:
        """List decision contexts matching the given query filters.

        Builds a dynamic WHERE clause based on non-None query fields.
        Results are ordered by ``market_timestamp DESC`` with the given limit.
        """
        conditions: list[str] = []
        params: list[object] = []
        param_index = 1

        if query.account_id is not None:
            conditions.append(f"account_id = ${param_index}")
            params.append(query.account_id)
            param_index += 1

        if query.strategy_id is not None:
            conditions.append(f"strategy_id = ${param_index}")
            params.append(query.strategy_id)
            param_index += 1

        if query.correlation_id is not None:
            conditions.append(f"correlation_id = ${param_index}")
            params.append(query.correlation_id)
            param_index += 1

        if query.market_timestamp_from is not None:
            conditions.append(f"market_timestamp >= ${param_index}")
            params.append(query.market_timestamp_from)
            param_index += 1

        if query.market_timestamp_to is not None:
            conditions.append(f"market_timestamp <= ${param_index}")
            params.append(query.market_timestamp_to)
            param_index += 1

        where_clause = " AND ".join(conditions) if conditions else "TRUE"
        limit = query.limit

        sql = f"""
            SELECT * FROM trading.decision_contexts
            WHERE {where_clause}
            ORDER BY market_timestamp DESC
            LIMIT ${param_index}
        """
        params.append(limit)

        rows = await self._tx.connection.fetch(sql, *params)
        return [row_to_entity(row, DecisionContextEntity) for row in rows]

    async def attach_signal_feature_snapshot(
        self,
        decision_context_id: UUID,
        signal_feature_snapshot_id: UUID,
    ) -> DecisionContextEntity | None:
        row = await self._tx.connection.fetchrow(
            """
            UPDATE trading.decision_contexts
            SET signal_feature_snapshot_id = $2
            WHERE decision_context_id = $1
            RETURNING *
            """,
            decision_context_id,
            signal_feature_snapshot_id,
        )
        return row_to_entity(row, DecisionContextEntity) if row else None
