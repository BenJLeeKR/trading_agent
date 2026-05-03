from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import BrokerOrderEntity


class PostgresBrokerOrderRepository:
    """PostgreSQL implementation of ``BrokerOrderRepository``.

    Satisfies the protocol defined in ``repositories/contracts.py``.

    ``broker_native_order_id`` is nullable; the UNIQUE constraint
    ``uq_broker_orders_native (broker_name, broker_native_order_id)``
    does not enforce uniqueness when ``broker_native_order_id`` is NULL
    (per SQL standard).
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(self, broker_order: BrokerOrderEntity) -> BrokerOrderEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.broker_orders
                (broker_order_id, order_request_id, broker_name,
                 broker_native_order_id, broker_status,
                 request_payload_uri, response_payload_uri,
                 last_synced_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING *
            """,
            broker_order.broker_order_id,
            broker_order.order_request_id,
            broker_order.broker_name,
            broker_order.broker_native_order_id,
            broker_order.broker_status,
            broker_order.request_payload_uri,
            broker_order.response_payload_uri,
            broker_order.last_synced_at,
        )
        return row_to_entity(row, BrokerOrderEntity)

    async def get_by_native_order_id(
        self, broker_name: str, broker_native_order_id: str
    ) -> BrokerOrderEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.broker_orders WHERE broker_name = $1 AND broker_native_order_id = $2",
            broker_name,
            broker_native_order_id,
        )
        return row_to_entity(row, BrokerOrderEntity) if row else None

    async def list_by_order_request(
        self, order_request_id: UUID
    ) -> Sequence[BrokerOrderEntity]:
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.broker_orders WHERE order_request_id = $1 ORDER BY created_at",
            order_request_id,
        )
        return tuple(row_to_entity(r, BrokerOrderEntity) for r in rows)
