from __future__ import annotations

import json
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import SymbolTradeStateEntity


class PostgresSymbolTradeStateRepository:
    """PostgreSQL implementation of ``SymbolTradeStateRepository``."""

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def upsert(
        self,
        state: SymbolTradeStateEntity,
    ) -> SymbolTradeStateEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.symbol_trade_states
                (symbol_trade_state_id, account_id, instrument_id,
                 symbol, market, state, holding_profile, position_quantity,
                 last_entry_order_request_id, last_exit_order_request_id,
                 last_entry_source_type,
                 last_entry_at, last_reduce_at, last_exit_at,
                 minimum_hold_until, reentry_cooldown_until, sell_cooldown_until,
                 last_signal_feature_snapshot_id, last_decision_context_id,
                 last_reason_codes, thesis_state_hash, metadata_json,
                 created_at, updated_at)
            VALUES ($1, $2, $3,
                    $4, $5, $6, $7, $8,
                    $9, $10,
                    $11,
                    $12, $13, $14,
                    $15, $16, $17,
                    $18, $19,
                    $20, $21, $22::jsonb,
                    COALESCE($23, NOW()), COALESCE($24, NOW()))
            ON CONFLICT (account_id, instrument_id) DO UPDATE
            SET symbol = EXCLUDED.symbol,
                market = EXCLUDED.market,
                state = EXCLUDED.state,
                holding_profile = EXCLUDED.holding_profile,
                position_quantity = EXCLUDED.position_quantity,
                last_entry_order_request_id = EXCLUDED.last_entry_order_request_id,
                last_exit_order_request_id = EXCLUDED.last_exit_order_request_id,
                last_entry_source_type = EXCLUDED.last_entry_source_type,
                last_entry_at = EXCLUDED.last_entry_at,
                last_reduce_at = EXCLUDED.last_reduce_at,
                last_exit_at = EXCLUDED.last_exit_at,
                minimum_hold_until = EXCLUDED.minimum_hold_until,
                reentry_cooldown_until = EXCLUDED.reentry_cooldown_until,
                sell_cooldown_until = EXCLUDED.sell_cooldown_until,
                last_signal_feature_snapshot_id = EXCLUDED.last_signal_feature_snapshot_id,
                last_decision_context_id = EXCLUDED.last_decision_context_id,
                last_reason_codes = EXCLUDED.last_reason_codes,
                thesis_state_hash = EXCLUDED.thesis_state_hash,
                metadata_json = EXCLUDED.metadata_json,
                updated_at = COALESCE(EXCLUDED.updated_at, NOW())
            RETURNING *
            """,
            state.symbol_trade_state_id,
            state.account_id,
            state.instrument_id,
            state.symbol,
            state.market,
            state.state,
            state.holding_profile,
            state.position_quantity,
            state.last_entry_order_request_id,
            state.last_exit_order_request_id,
            state.last_entry_source_type,
            state.last_entry_at,
            state.last_reduce_at,
            state.last_exit_at,
            state.minimum_hold_until,
            state.reentry_cooldown_until,
            state.sell_cooldown_until,
            state.last_signal_feature_snapshot_id,
            state.last_decision_context_id,
            state.last_reason_codes,
            state.thesis_state_hash,
            json.dumps(state.metadata_json),
            state.created_at,
            state.updated_at,
        )
        return row_to_entity(row, SymbolTradeStateEntity)

    async def get_by_account_and_instrument(
        self,
        account_id: UUID,
        instrument_id: UUID,
    ) -> SymbolTradeStateEntity | None:
        row = await self._tx.connection.fetchrow(
            """
            SELECT *
            FROM trading.symbol_trade_states
            WHERE account_id = $1
              AND instrument_id = $2
            """,
            account_id,
            instrument_id,
        )
        return row_to_entity(row, SymbolTradeStateEntity) if row else None
