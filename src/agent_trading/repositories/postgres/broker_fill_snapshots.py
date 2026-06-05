from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import BrokerFillSnapshotEntity


class PostgresBrokerFillSnapshotRepository:
    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def upsert(self, snapshot: BrokerFillSnapshotEntity) -> BrokerFillSnapshotEntity:
        row = await self._tx.connection.fetchrow(
            """INSERT INTO trading.broker_fill_snapshots
               (broker_fill_snapshot_id, fill_sync_run_id, account_id,
                order_request_id,
                broker_name, broker_native_order_id, broker_fill_id,
                symbol, side, order_date, order_status_code, cancel_yn,
                ordered_quantity, filled_quantity, fill_price,
                order_time, fill_time, fill_timestamp,
                dedupe_key, raw_payload_json)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                       $13, $14, $15, $16, $17, $18, $19, $20::jsonb)
               ON CONFLICT (dedupe_key) DO UPDATE SET
                   order_request_id = COALESCE(EXCLUDED.order_request_id, trading.broker_fill_snapshots.order_request_id),
                   fill_sync_run_id = EXCLUDED.fill_sync_run_id,
                   broker_fill_id = EXCLUDED.broker_fill_id,
                   order_status_code = EXCLUDED.order_status_code,
                   cancel_yn = EXCLUDED.cancel_yn,
                   ordered_quantity = EXCLUDED.ordered_quantity,
                   filled_quantity = EXCLUDED.filled_quantity,
                   fill_price = EXCLUDED.fill_price,
                   order_time = EXCLUDED.order_time,
                   fill_time = EXCLUDED.fill_time,
                   fill_timestamp = EXCLUDED.fill_timestamp,
                   raw_payload_json = EXCLUDED.raw_payload_json,
                   updated_at = NOW()
               RETURNING *""",
            snapshot.broker_fill_snapshot_id,
            snapshot.fill_sync_run_id,
            snapshot.account_id,
            snapshot.order_request_id,
            snapshot.broker_name,
            snapshot.broker_native_order_id,
            snapshot.broker_fill_id,
            snapshot.symbol,
            snapshot.side,
            snapshot.order_date,
            snapshot.order_status_code,
            snapshot.cancel_yn,
            snapshot.ordered_quantity,
            snapshot.filled_quantity,
            snapshot.fill_price,
            snapshot.order_time,
            snapshot.fill_time,
            snapshot.fill_timestamp,
            snapshot.dedupe_key,
            json.dumps(snapshot.raw_payload_json),
        )
        return row_to_entity(row, BrokerFillSnapshotEntity)

    async def list_recent(
        self,
        *,
        limit: int = 200,
        account_id: UUID | None = None,
        order_date: date | None = None,
        order_request_id: UUID | None = None,
        symbol: str | None = None,
        broker_native_order_id: str | None = None,
    ) -> Sequence[BrokerFillSnapshotEntity]:
        conditions: list[str] = []
        params: list[object] = []
        idx = 1
        if account_id is not None:
            conditions.append(f"account_id = ${idx}")
            params.append(account_id)
            idx += 1
        if order_date is not None:
            conditions.append(f"order_date = ${idx}")
            params.append(order_date)
            idx += 1
        if order_request_id is not None:
            conditions.append(f"order_request_id = ${idx}")
            params.append(order_request_id)
            idx += 1
        if symbol is not None:
            conditions.append(f"symbol = ${idx}")
            params.append(symbol)
            idx += 1
        if broker_native_order_id is not None:
            conditions.append(f"broker_native_order_id = ${idx}")
            params.append(broker_native_order_id)
            idx += 1
        where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        rows = await self._tx.connection.fetch(
            f"""SELECT * FROM trading.broker_fill_snapshots
                {where_clause}
                ORDER BY order_date DESC, fill_timestamp DESC NULLS LAST, created_at DESC
                LIMIT ${idx}""",
            *params,
        )
        return tuple(row_to_entity(row, BrokerFillSnapshotEntity) for row in rows)
