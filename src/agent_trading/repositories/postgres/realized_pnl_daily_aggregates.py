from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import RealizedPnlDailyAggregateEntity


class PostgresRealizedPnlDailyAggregateRepository:
    """PostgreSQL implementation of ``RealizedPnlDailyAggregateRepository``.

    ``trading.realized_pnl_daily_aggregates``는 ``realized_pnl_events``에서
    언제든 재생성 가능한 조회 성능용 파생 캐시다. PK는
    ``(account_id, instrument_id, trade_date)``.
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def upsert(
        self, aggregate: RealizedPnlDailyAggregateEntity
    ) -> RealizedPnlDailyAggregateEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.realized_pnl_daily_aggregates
                (account_id, instrument_id, trade_date,
                 realized_pnl_net_sum, sell_event_count, computation_run_id,
                 buy_amount_sum, sell_amount_sum, fee_tax_sum, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
            ON CONFLICT (account_id, instrument_id, trade_date) DO UPDATE SET
                realized_pnl_net_sum = EXCLUDED.realized_pnl_net_sum,
                sell_event_count = EXCLUDED.sell_event_count,
                computation_run_id = EXCLUDED.computation_run_id,
                buy_amount_sum = EXCLUDED.buy_amount_sum,
                sell_amount_sum = EXCLUDED.sell_amount_sum,
                fee_tax_sum = EXCLUDED.fee_tax_sum,
                updated_at = NOW()
            RETURNING *
            """,
            aggregate.account_id,
            aggregate.instrument_id,
            aggregate.trade_date,
            aggregate.realized_pnl_net_sum,
            aggregate.sell_event_count,
            aggregate.computation_run_id,
            aggregate.buy_amount_sum,
            aggregate.sell_amount_sum,
            aggregate.fee_tax_sum,
        )
        return row_to_entity(row, RealizedPnlDailyAggregateEntity)

    async def list_by_account_and_instrument(
        self,
        account_id: UUID,
        instrument_id: UUID,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> Sequence[RealizedPnlDailyAggregateEntity]:
        conditions = ["account_id = $1", "instrument_id = $2"]
        params: list[object] = [account_id, instrument_id]
        idx = 3
        if start_date is not None:
            conditions.append(f"trade_date >= ${idx}")
            params.append(start_date)
            idx += 1
        if end_date is not None:
            conditions.append(f"trade_date <= ${idx}")
            params.append(end_date)
            idx += 1
        where_clause = " AND ".join(conditions)
        rows = await self._tx.connection.fetch(
            f"SELECT * FROM trading.realized_pnl_daily_aggregates "
            f"WHERE {where_clause} ORDER BY trade_date ASC",
            *params,
        )
        return tuple(row_to_entity(row, RealizedPnlDailyAggregateEntity) for row in rows)

    async def list_by_account(
        self,
        account_id: UUID,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> Sequence[RealizedPnlDailyAggregateEntity]:
        conditions = ["account_id = $1"]
        params: list[object] = [account_id]
        idx = 2
        if start_date is not None:
            conditions.append(f"trade_date >= ${idx}")
            params.append(start_date)
            idx += 1
        if end_date is not None:
            conditions.append(f"trade_date <= ${idx}")
            params.append(end_date)
            idx += 1
        where_clause = " AND ".join(conditions)
        rows = await self._tx.connection.fetch(
            f"SELECT * FROM trading.realized_pnl_daily_aggregates "
            f"WHERE {where_clause} ORDER BY instrument_id ASC, trade_date ASC",
            *params,
        )
        return tuple(row_to_entity(row, RealizedPnlDailyAggregateEntity) for row in rows)
