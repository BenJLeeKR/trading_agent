"""PostgreSQL implementation of ``PositionSnapshotRepository``."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import PositionSnapshotEntity


class PostgresPositionSnapshotRepository:
    """PostgreSQL implementation of ``PositionSnapshotRepository``.

    Stores point-in-time position snapshots in the
    ``trading.position_snapshots`` table.
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(self, snapshot: PositionSnapshotEntity) -> PositionSnapshotEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.position_snapshots
                (position_snapshot_id, account_id, instrument_id,
                 quantity, average_price, market_price, unrealized_pnl,
                 source_of_truth, snapshot_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING *
            """,
            snapshot.position_snapshot_id,
            snapshot.account_id,
            snapshot.instrument_id,
            snapshot.quantity,
            snapshot.average_price,
            snapshot.market_price,
            snapshot.unrealized_pnl,
            snapshot.source_of_truth,
            snapshot.snapshot_at,
        )
        return row_to_entity(row, PositionSnapshotEntity)

    async def get(self, position_snapshot_id: UUID) -> PositionSnapshotEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.position_snapshots "
            "WHERE position_snapshot_id = $1",
            position_snapshot_id,
        )
        return row_to_entity(row, PositionSnapshotEntity) if row else None

    async def list_latest_by_account(
        self, account_id: UUID
    ) -> Sequence[PositionSnapshotEntity]:
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.position_snapshots "
            "WHERE account_id = $1 "
            "ORDER BY snapshot_at DESC",
            account_id,
        )
        return tuple(row_to_entity(r, PositionSnapshotEntity) for r in rows)
