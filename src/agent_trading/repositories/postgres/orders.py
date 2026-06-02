from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

import asyncpg

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import OrderRequestEntity
from agent_trading.domain.enums import OrderStatus
from agent_trading.repositories.filters import OrderQuery


class PostgresOrderRepository:
    """PostgreSQL implementation of ``OrderRepository``.

    Satisfies the protocol defined in ``repositories/contracts.py``.

    Idempotency is enforced at two levels:
      1. Application-level pre-check via ``get_by_client_order_id()``.
      2. Database-level UNIQUE constraints on ``client_order_id`` and
         ``idempotency_key`` (see DDL).
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(self, order: OrderRequestEntity) -> OrderRequestEntity:
        try:
            row = await self._tx.connection.fetchrow(
                """
                INSERT INTO trading.order_requests
                    (order_request_id, account_id, instrument_id,
                     client_order_id, idempotency_key, correlation_id,
                     side, order_type, time_in_force,
                     requested_price, requested_quantity,
                     status, status_reason_code, status_reason_message,
                     trade_decision_id, decision_context_id, submitted_at,
                     created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
                RETURNING *
                """,
                order.order_request_id,
                order.account_id,
                order.instrument_id,
                order.client_order_id,
                order.idempotency_key,
                order.correlation_id,
                order.side.value,
                order.order_type.value,
                order.time_in_force.value,
                order.requested_price,
                order.requested_quantity,
                order.status.value,
                order.status_reason_code,
                order.status_reason_message,
                order.trade_decision_id,
                order.decision_context_id,
                order.submitted_at,
                order.created_at,
                order.updated_at,
            )
            return row_to_entity(row, OrderRequestEntity)
        except asyncpg.UniqueViolationError as exc:
            # Determine which constraint was violated for a better error message.
            constraint = exc.constraint_name
            if constraint == "uq_order_requests_client_order_id":
                raise DuplicateClientOrderIdError(order.client_order_id) from exc
            if constraint == "uq_order_requests_idempotency_key":
                raise DuplicateIdempotencyKeyError(order.idempotency_key) from exc
            raise

    async def get(self, order_request_id: UUID) -> OrderRequestEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.order_requests WHERE order_request_id = $1",
            order_request_id,
        )
        return row_to_entity(row, OrderRequestEntity) if row else None

    async def get_by_client_order_id(self, client_order_id: str) -> OrderRequestEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.order_requests WHERE client_order_id = $1",
            client_order_id,
        )
        return row_to_entity(row, OrderRequestEntity) if row else None

    async def list(self, query: OrderQuery) -> Sequence[OrderRequestEntity]:
        where_clause, params, idx = self._build_where_clause(query)
        sql = f"SELECT o.* FROM trading.order_requests o JOIN trading.accounts a ON o.account_id = a.account_id JOIN trading.instruments i ON o.instrument_id = i.instrument_id {where_clause} ORDER BY o.created_at DESC LIMIT ${idx}"
        params.append(query.limit)

        rows = await self._tx.connection.fetch(sql, *params)
        return tuple(row_to_entity(r, OrderRequestEntity) for r in rows)

    async def count(self, query: OrderQuery) -> int:
        where_clause, params, _ = self._build_where_clause(query)
        row = await self._tx.connection.fetchrow(
            f"""
            SELECT COUNT(*) AS cnt
            FROM trading.order_requests o
            JOIN trading.accounts a ON o.account_id = a.account_id
            JOIN trading.instruments i ON o.instrument_id = i.instrument_id
            {where_clause}
            """,
            *params,
        )
        return int(row["cnt"]) if row else 0

    async def count_by_status(self, query: OrderQuery) -> dict[str, int]:
        where_clause, params, _ = self._build_where_clause(query)
        rows = await self._tx.connection.fetch(
            f"""
            SELECT o.status, COUNT(*) AS cnt
            FROM trading.order_requests o
            JOIN trading.accounts a ON o.account_id = a.account_id
            JOIN trading.instruments i ON o.instrument_id = i.instrument_id
            {where_clause}
            GROUP BY o.status
            """,
            *params,
        )
        return {str(r["status"]): int(r["cnt"]) for r in rows}

    def _build_where_clause(
        self,
        query: OrderQuery,
    ) -> tuple[str, list[object], int]:
        conditions: list[str] = []
        params: list[object] = []
        idx = 1

        if query.account_id is not None:
            conditions.append(f"o.account_id = ${idx}")
            params.append(query.account_id)
            idx += 1
        if query.client_order_id is not None:
            conditions.append(f"o.client_order_id = ${idx}")
            params.append(query.client_order_id)
            idx += 1
        if query.correlation_id is not None:
            conditions.append(f"o.correlation_id = ${idx}")
            params.append(query.correlation_id)
            idx += 1
        if query.status is not None:
            conditions.append(f"o.status = ${idx}")
            params.append(query.status.value)
            idx += 1
        if query.statuses is not None:
            placeholders = ",".join(f"${idx + i}" for i in range(len(query.statuses)))
            conditions.append(f"o.status IN ({placeholders})")
            params.extend(s.value for s in query.statuses)
            idx += len(query.statuses)
        if query.trade_decision_id is not None:
            conditions.append(f"o.trade_decision_id = ${idx}")
            params.append(query.trade_decision_id)
            idx += 1
        if query.decision_context_id is not None:
            conditions.append(f"o.decision_context_id = ${idx}")
            params.append(query.decision_context_id)
            idx += 1
        if query.submitted_from is not None:
            conditions.append(f"o.submitted_at >= ${idx}")
            params.append(query.submitted_from)
            idx += 1
        if query.submitted_to is not None:
            conditions.append(f"o.submitted_at <= ${idx}")
            params.append(query.submitted_to)
            idx += 1
        if query.created_from is not None:
            conditions.append(f"o.created_at >= ${idx}")
            params.append(query.created_from)
            idx += 1
        if query.created_to is not None:
            conditions.append(f"o.created_at <= ${idx}")
            params.append(query.created_to)
            idx += 1

        conditions.append("a.account_code NOT LIKE 'E2E-%'")
        conditions.append("i.symbol != 'E2ESUM'")
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        return where_clause, params, idx

    async def update_status(
        self,
        order_request_id: UUID,
        status: OrderStatus,
        reason_code: str | None = None,
        reason_message: str | None = None,
        expected_version: int | None = None,
        submitted_at: datetime | None = None,
    ) -> None:
        if expected_version is not None:
            result = await self._tx.connection.execute(
                """
                UPDATE trading.order_requests
                SET status = $2::varchar,
                    status_reason_code = $3,
                    status_reason_message = $4,
                    submitted_at = COALESCE($6, submitted_at, CASE
                        WHEN $2::text = 'submitted' THEN NOW()
                        ELSE NULL
                    END),
                    version = version + 1,
                    updated_at = NOW()
                WHERE order_request_id = $1 AND version = $5
                """,
                order_request_id,
                status.value,
                reason_code,
                reason_message,
                expected_version,
                submitted_at,
            )
            if result != "UPDATE 1":
                current = await self.get(order_request_id)
                if current is None:
                    raise ValueError(f"Order not found: {order_request_id}")
                raise VersionConflictError(
                    order_request_id=order_request_id,
                    expected_version=expected_version,
                    actual_version=current.version,
                )
        else:
            await self._tx.connection.execute(
                """
                UPDATE trading.order_requests
                SET status = $2::varchar,
                    status_reason_code = $3,
                    status_reason_message = $4,
                    submitted_at = COALESCE($5, submitted_at, CASE
                        WHEN $2::text = 'submitted' THEN NOW()
                        ELSE NULL
                    END),
                    updated_at = NOW()
                WHERE order_request_id = $1
                """,
                order_request_id,
                status.value,
                reason_code,
                reason_message,
                submitted_at,
            )


class VersionConflictError(ValueError):
    """Raised when an optimistic lock version mismatch is detected.

    Indicates that another worker has modified the order between
    the read and the update.
    """

    def __init__(
        self,
        order_request_id: UUID,
        expected_version: int,
        actual_version: int,
    ) -> None:
        self.order_request_id = order_request_id
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(
            f"Version conflict for {order_request_id}: "
            f"expected {expected_version}, actual {actual_version}"
        )


class DuplicateClientOrderIdError(ValueError):
    """Raised when a duplicate ``client_order_id`` is detected."""

    def __init__(self, client_order_id: str) -> None:
        self.client_order_id = client_order_id
        super().__init__(f"Duplicate client_order_id: {client_order_id}")


class DuplicateIdempotencyKeyError(ValueError):
    """Raised when a duplicate ``idempotency_key`` is detected."""

    def __init__(self, idempotency_key: str) -> None:
        self.idempotency_key = idempotency_key
        super().__init__(f"Duplicate idempotency_key: {idempotency_key}")
