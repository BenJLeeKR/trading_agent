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
                 purchase_amount, evaluation_amount,
                 source_of_truth, snapshot_at,
                 fetch_status,
                 snapshot_sync_run_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            RETURNING *
            """,
            snapshot.position_snapshot_id,
            snapshot.account_id,
            snapshot.instrument_id,
            snapshot.quantity,
            snapshot.average_price,
            snapshot.market_price,
            snapshot.unrealized_pnl,
            snapshot.purchase_amount,
            snapshot.evaluation_amount,
            snapshot.source_of_truth,
            snapshot.snapshot_at,
            snapshot.fetch_status,
            snapshot.snapshot_sync_run_id,
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
        """각 instrument별 최신 position snapshot 1건만 반환.

        ``DISTINCT ON (instrument_id)``를 사용하여 동일 instrument의
        중복 snapshot 중 가장 최신(``snapshot_at DESC``) 1건만 반환한다.
        전량 매도되어 수량이 0인 snapshot도 최신 row가 반환되므로,
        호출자(consumer)가 필요시 ``quantity > 0`` 필터를 적용할 수 있다.
        DB에는 모든 이력이 보존되어 디버깅이 가능하다.
        """
        rows = await self._tx.connection.fetch(
            "SELECT DISTINCT ON (instrument_id) * "
            "FROM trading.position_snapshots "
            "WHERE account_id = $1 "
            "ORDER BY instrument_id, snapshot_at DESC",
            account_id,
        )
        return tuple(row_to_entity(r, PositionSnapshotEntity) for r in rows)

    async def get_latest_by_account_and_instrument_before(
        self,
        account_id: UUID,
        instrument_id: UUID,
        before: datetime,
    ) -> PositionSnapshotEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.position_snapshots "
            "WHERE account_id = $1 AND instrument_id = $2 AND snapshot_at < $3 "
            "ORDER BY snapshot_at DESC "
            "LIMIT 1",
            account_id,
            instrument_id,
            before,
        )
        return row_to_entity(row, PositionSnapshotEntity) if row else None

    async def get_earliest_by_account_and_instrument_after(
        self,
        account_id: UUID,
        instrument_id: UUID,
        after: datetime,
    ) -> PositionSnapshotEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.position_snapshots "
            "WHERE account_id = $1 AND instrument_id = $2 AND snapshot_at > $3 "
            "ORDER BY snapshot_at ASC "
            "LIMIT 1",
            account_id,
            instrument_id,
            after,
        )
        return row_to_entity(row, PositionSnapshotEntity) if row else None

    async def list_by_sync_run(
        self, account_id: UUID, sync_run_id: UUID,
    ) -> Sequence[PositionSnapshotEntity]:
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.position_snapshots "
            "WHERE account_id = $1 AND snapshot_sync_run_id = $2 "
            "ORDER BY instrument_id",
            account_id,
            sync_run_id,
        )
        return tuple(row_to_entity(r, PositionSnapshotEntity) for r in rows)

    async def get_latest_sync_run_id(
        self, account_id: UUID,
    ) -> UUID | None:
        row = await self._tx.connection.fetchrow(
            "SELECT snapshot_sync_run_id "
            "FROM trading.position_snapshots "
            "WHERE account_id = $1 AND snapshot_sync_run_id IS NOT NULL "
            "ORDER BY snapshot_at DESC "
            "LIMIT 1",
            account_id,
        )
        return row["snapshot_sync_run_id"] if row else None
