from __future__ import annotations

from collections.abc import Sequence

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import OrderStateEventEntity


class PostgresOrderStateEventRepository:
    """PostgreSQL implementation of ``OrderStateEventRepository``.

    This is an **append-only** store.  Rows must never be UPDATEd or
    DELETEd — the application layer guarantees this by only calling
    ``add()``.
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(self, event: OrderStateEventEntity) -> OrderStateEventEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.order_state_events
                (order_state_event_id, order_request_id,
                 previous_status, new_status, event_source,
                 event_timestamp, ingested_at,
                 reason_code, raw_event_uri, correlation_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING *
            """,
            event.order_state_event_id,
            event.order_request_id,
            event.previous_status.value if event.previous_status is not None else None,
            event.new_status.value,
            event.event_source.value,
            event.event_timestamp,
            event.ingested_at,
            event.reason_code,
            event.raw_event_uri,
            event.correlation_id,
        )
        return row_to_entity(row, OrderStateEventEntity)

    async def list_by_order_request(
        self, order_request_id: object
    ) -> Sequence[OrderStateEventEntity]:
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.order_state_events "
            "WHERE order_request_id = $1 "
            "ORDER BY ingested_at",
            order_request_id,
        )
        return tuple(row_to_entity(r, OrderStateEventEntity) for r in rows)

    async def list_recent(self, limit: int = 100) -> Sequence[OrderStateEventEntity]:
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.order_state_events "
            "ORDER BY ingested_at DESC "
            "LIMIT $1",
            limit,
        )
        return tuple(row_to_entity(r, OrderStateEventEntity) for r in rows)
