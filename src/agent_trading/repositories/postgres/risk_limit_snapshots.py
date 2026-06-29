from __future__ import annotations

import json
from collections.abc import Sequence

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import RiskLimitSnapshotEntity


class PostgresRiskLimitSnapshotRepository:
    """PostgreSQL implementation of ``RiskLimitSnapshotRepository``.

    Stores point-in-time risk limit and exposure snapshots in the
    ``trading.risk_limit_snapshots`` table.
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(
        self, snapshot: RiskLimitSnapshotEntity
    ) -> RiskLimitSnapshotEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.risk_limit_snapshots
                (risk_limit_snapshot_id, account_id, snapshot_at,
                 nav, cash_available,
                 gross_exposure_pct, net_exposure_pct,
                 daily_realized_pnl, daily_unrealized_pnl,
                 daily_loss_used_pct, max_daily_loss_limit_pct,
                 var_confidence_level, var_horizon_days, var_lookback_days,
                 portfolio_var_1d, portfolio_var_1d_adjusted,
                 largest_var_symbol, largest_var_contribution_pct,
                 concentration_penalty_pct, var_status, var_reason_codes,
                 symbol_var_json, symbol_marginal_contribution_json,
                 symbol_exposure_json, sector_exposure_json,
                 open_order_exposure_json,
                 drawdown_state, kill_switch_active, blocked_reason_codes)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                    $12, $13, $14, $15, $16, $17, $18, $19, $20, $21,
                    $22::jsonb, $23::jsonb, $24::jsonb, $25::jsonb, $26::jsonb,
                    $27, $28, $29)
            RETURNING *
            """,
            snapshot.risk_limit_snapshot_id,
            snapshot.account_id,
            snapshot.snapshot_at,
            snapshot.nav,
            snapshot.cash_available,
            snapshot.gross_exposure_pct,
            snapshot.net_exposure_pct,
            snapshot.daily_realized_pnl,
            snapshot.daily_unrealized_pnl,
            snapshot.daily_loss_used_pct,
            snapshot.max_daily_loss_limit_pct,
            snapshot.var_confidence_level,
            snapshot.var_horizon_days,
            snapshot.var_lookback_days,
            snapshot.portfolio_var_1d,
            snapshot.portfolio_var_1d_adjusted,
            snapshot.largest_var_symbol,
            snapshot.largest_var_contribution_pct,
            snapshot.concentration_penalty_pct,
            snapshot.var_status,
            snapshot.var_reason_codes,
            json.dumps(snapshot.symbol_var_json),
            json.dumps(snapshot.symbol_marginal_contribution_json),
            json.dumps(snapshot.symbol_exposure_json),
            json.dumps(snapshot.sector_exposure_json),
            json.dumps(snapshot.open_order_exposure_json),
            snapshot.drawdown_state,
            snapshot.kill_switch_active,
            snapshot.blocked_reason_codes,
        )
        return row_to_entity(row, RiskLimitSnapshotEntity)

    async def get_latest_by_account(
        self, account_id: object
    ) -> RiskLimitSnapshotEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.risk_limit_snapshots "
            "WHERE account_id = $1 "
            "ORDER BY snapshot_at DESC "
            "LIMIT 1",
            account_id,
        )
        return row_to_entity(row, RiskLimitSnapshotEntity) if row else None

    async def list_by_account(
        self, account_id: object, limit: int = 20
    ) -> Sequence[RiskLimitSnapshotEntity]:
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.risk_limit_snapshots "
            "WHERE account_id = $1 "
            "ORDER BY snapshot_at DESC "
            "LIMIT $2",
            account_id,
            limit,
        )
        return tuple(row_to_entity(r, RiskLimitSnapshotEntity) for r in rows)
