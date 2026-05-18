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
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.cash_balance_snapshots
                (cash_balance_snapshot_id, account_id, currency,
                 available_cash, settled_cash, unsettled_cash,
                 source_of_truth, snapshot_at,
                 total_asset, settlement_amount, total_unrealized_pnl,
                 orderable_amount)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
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
        )
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
