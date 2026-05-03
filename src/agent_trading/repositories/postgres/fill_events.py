from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import FillEventEntity


class PostgresFillEventRepository:
    """PostgreSQL implementation of ``FillEventRepository``.

    Satisfies the protocol defined in ``repositories/contracts.py``.

    ``broker_fill_id`` is nullable; the UNIQUE constraint
    ``uq_fill_events_native (broker_order_id, broker_fill_id)``
    does not enforce uniqueness when ``broker_fill_id`` is NULL
    (per SQL standard).

    The ``source_channel`` column has a CHECK constraint allowing:
    ``websocket``, ``rest_poll``, ``backfill``, ``manual``.
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(self, fill_event: FillEventEntity) -> FillEventEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.fill_events
                (fill_event_id, broker_order_id, broker_fill_id,
                 fill_timestamp, fill_price, fill_quantity,
                 fill_fee, fill_tax,
                 source_channel, raw_payload_uri)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING *
            """,
            fill_event.fill_event_id,
            fill_event.broker_order_id,
            fill_event.broker_fill_id,
            fill_event.fill_timestamp,
            fill_event.fill_price,
            fill_event.fill_quantity,
            fill_event.fill_fee,
            fill_event.fill_tax,
            fill_event.source_channel,
            fill_event.raw_payload_uri,
        )
        return row_to_entity(row, FillEventEntity)

    async def list_by_broker_order(
        self, broker_order_id: UUID
    ) -> Sequence[FillEventEntity]:
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.fill_events WHERE broker_order_id = $1 ORDER BY fill_timestamp DESC",
            broker_order_id,
        )
        return tuple(row_to_entity(r, FillEventEntity) for r in rows)
