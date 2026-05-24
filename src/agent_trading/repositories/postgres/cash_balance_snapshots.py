"""PostgreSQL implementation of ``CashBalanceSnapshotRepository``."""

from __future__ import annotations

from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import CashBalanceSnapshotEntity


class PostgresCashBalanceSnapshotRepository:
    """PostgreSQL implementation of ``CashBalanceSnapshotRepository``.

    Stores point-in-time cash balance snapshots in the
    ``trading.cash_balance_snapshots`` table.
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(self, snapshot: CashBalanceSnapshotEntity) -> CashBalanceSnapshotEntity:
        fk_val = snapshot.snapshot_sync_run_id
        import sys
        print(f"DEBUG_FK_REPO: cash_balance_snapshot_id={snapshot.cash_balance_snapshot_id} snapshot_sync_run_id={fk_val}", file=sys.stderr)
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.cash_balance_snapshots
                (cash_balance_snapshot_id, account_id, currency,
                 available_cash, settled_cash, unsettled_cash,
                 source_of_truth, snapshot_at,
                 total_asset, settlement_amount, total_unrealized_pnl,
                 orderable_amount,
                 fetch_status,
                 snapshot_sync_run_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            RETURNING *
            """,
            snapshot.cash_balance_snapshot_id,
            snapshot.account_id,
            snapshot.currency,
            snapshot.available_cash,
            snapshot.settled_cash,
            snapshot.unsettled_cash,
            snapshot.source_of_truth,
            snapshot.snapshot_at,
            snapshot.total_asset,
            snapshot.settlement_amount,
            snapshot.total_unrealized_pnl,
            snapshot.orderable_amount,
            snapshot.fetch_status,
            fk_val,
        )
        print(f"DEBUG_FK_REPO: AFTER INSERT fk_val={fk_val} row_sync_run_id={row['snapshot_sync_run_id'] if row else 'NO_ROW'}", file=sys.stderr)
        return row_to_entity(row, CashBalanceSnapshotEntity)

    async def get(self, cash_balance_snapshot_id: UUID) -> CashBalanceSnapshotEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.cash_balance_snapshots "
            "WHERE cash_balance_snapshot_id = $1",
            cash_balance_snapshot_id,
        )
        return row_to_entity(row, CashBalanceSnapshotEntity) if row else None

    async def list_by_account(self, account_id: UUID) -> Sequence[CashBalanceSnapshotEntity]:
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.cash_balance_snapshots "
            "WHERE account_id = $1 "
            "ORDER BY snapshot_at DESC",
            account_id,
        )
        return tuple(row_to_entity(r, CashBalanceSnapshotEntity) for r in rows)

    async def get_latest_by_account(
        self, account_id: UUID
    ) -> CashBalanceSnapshotEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.cash_balance_snapshots "
            "WHERE account_id = $1 "
            "ORDER BY snapshot_at DESC "
            "LIMIT 1",
            account_id,
        )
        return row_to_entity(row, CashBalanceSnapshotEntity) if row else None

    async def get_by_sync_run(
        self, account_id: UUID, sync_run_id: UUID,
    ) -> CashBalanceSnapshotEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.cash_balance_snapshots "
            "WHERE account_id = $1 AND snapshot_sync_run_id = $2 "
            "ORDER BY snapshot_at DESC "
            "LIMIT 1",
            account_id,
            sync_run_id,
        )
        return row_to_entity(row, CashBalanceSnapshotEntity) if row else None
