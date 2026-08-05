from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import RealizedPnlEventEntity


class PostgresRealizedPnlEventRepository:
    """PostgreSQL implementation of ``RealizedPnlEventRepository``.

    ``trading.realized_pnl_events``는 append-only 원장이다. ``fill_event_id``에
    UNIQUE 제약이 있어 같은 fill을 두 번 ``add()``하면 DB가 위반을 발생시킨다
    (idempotency의 1차 방어선).
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(self, event: RealizedPnlEventEntity) -> RealizedPnlEventEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.realized_pnl_events
                (realized_pnl_event_id, account_id, instrument_id,
                 fill_event_id, broker_order_id, order_request_id,
                 sell_quantity, sell_price, avg_cost_basis_before,
                 fee, tax, fee_tax_source,
                 realized_pnl_gross, realized_pnl_net, position_quantity_after,
                 computation_run_id, superseded_by_event_id, fill_timestamp)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                    $13, $14, $15, $16, $17, $18)
            RETURNING *
            """,
            event.realized_pnl_event_id,
            event.account_id,
            event.instrument_id,
            event.fill_event_id,
            event.broker_order_id,
            event.order_request_id,
            event.sell_quantity,
            event.sell_price,
            event.avg_cost_basis_before,
            event.fee,
            event.tax,
            event.fee_tax_source.value,
            event.realized_pnl_gross,
            event.realized_pnl_net,
            event.position_quantity_after,
            event.computation_run_id,
            event.superseded_by_event_id,
            event.fill_timestamp,
        )
        return row_to_entity(row, RealizedPnlEventEntity)

    async def upsert(self, event: RealizedPnlEventEntity) -> RealizedPnlEventEntity:
        """``fill_event_id`` 기준 upsert(recompute/replay 전용, contracts.py 참고).

        ``realized_pnl_event_id``는 ``fill_event_id``로부터 결정론적으로
        파생되므로 충돌 시에도 동일한 PK 값으로 들어온다 — 계산값 컬럼만
        다시 쓰고 ``created_at``/``superseded_by_event_id``는 그대로 둔다.
        """
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.realized_pnl_events
                (realized_pnl_event_id, account_id, instrument_id,
                 fill_event_id, broker_order_id, order_request_id,
                 sell_quantity, sell_price, avg_cost_basis_before,
                 fee, tax, fee_tax_source,
                 realized_pnl_gross, realized_pnl_net, position_quantity_after,
                 computation_run_id, superseded_by_event_id, fill_timestamp)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                    $13, $14, $15, $16, $17, $18)
            ON CONFLICT (fill_event_id) DO UPDATE SET
                sell_quantity = EXCLUDED.sell_quantity,
                sell_price = EXCLUDED.sell_price,
                avg_cost_basis_before = EXCLUDED.avg_cost_basis_before,
                fee = EXCLUDED.fee,
                tax = EXCLUDED.tax,
                fee_tax_source = EXCLUDED.fee_tax_source,
                realized_pnl_gross = EXCLUDED.realized_pnl_gross,
                realized_pnl_net = EXCLUDED.realized_pnl_net,
                position_quantity_after = EXCLUDED.position_quantity_after,
                computation_run_id = EXCLUDED.computation_run_id
            RETURNING *
            """,
            event.realized_pnl_event_id,
            event.account_id,
            event.instrument_id,
            event.fill_event_id,
            event.broker_order_id,
            event.order_request_id,
            event.sell_quantity,
            event.sell_price,
            event.avg_cost_basis_before,
            event.fee,
            event.tax,
            event.fee_tax_source.value,
            event.realized_pnl_gross,
            event.realized_pnl_net,
            event.position_quantity_after,
            event.computation_run_id,
            event.superseded_by_event_id,
            event.fill_timestamp,
        )
        return row_to_entity(row, RealizedPnlEventEntity)

    async def get_by_fill_event_id(
        self, fill_event_id: UUID
    ) -> RealizedPnlEventEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.realized_pnl_events WHERE fill_event_id = $1",
            fill_event_id,
        )
        return row_to_entity(row, RealizedPnlEventEntity) if row else None

    async def list_by_account_and_instrument(
        self,
        account_id: UUID,
        instrument_id: UUID,
        *,
        limit: int = 200,
        before: datetime | None = None,
    ) -> Sequence[RealizedPnlEventEntity]:
        if before is not None:
            rows = await self._tx.connection.fetch(
                "SELECT * FROM trading.realized_pnl_events "
                "WHERE account_id = $1 AND instrument_id = $2 AND fill_timestamp < $3 "
                "ORDER BY fill_timestamp DESC LIMIT $4",
                account_id,
                instrument_id,
                before,
                limit,
            )
        else:
            rows = await self._tx.connection.fetch(
                "SELECT * FROM trading.realized_pnl_events "
                "WHERE account_id = $1 AND instrument_id = $2 "
                "ORDER BY fill_timestamp DESC LIMIT $3",
                account_id,
                instrument_id,
                limit,
            )
        return tuple(row_to_entity(row, RealizedPnlEventEntity) for row in rows)
