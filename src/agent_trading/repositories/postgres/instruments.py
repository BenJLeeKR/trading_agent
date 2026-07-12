from __future__ import annotations

import json
from collections.abc import Sequence
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import InstrumentEntity


class PostgresInstrumentRepository:
    """PostgreSQL implementation of ``InstrumentRepository``.

    Satisfies the protocol defined in ``repositories/contracts.py``.
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(self, instrument: InstrumentEntity) -> InstrumentEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.instruments
                (instrument_id, symbol, market_code, asset_class, currency,
                 name, tick_size, lot_size, is_active, exchange_code, market_segment, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb)
            RETURNING *
            """,
            instrument.instrument_id,
            instrument.symbol,
            instrument.market_code,
            instrument.asset_class,
            instrument.currency,
            instrument.name,
            instrument.tick_size,
            instrument.lot_size,
            instrument.is_active,
            instrument.exchange_code,
            instrument.market_segment,
            json.dumps(instrument.metadata) if instrument.metadata is not None else None,
        )
        return row_to_entity(row, InstrumentEntity)

    async def get(self, instrument_id: UUID) -> InstrumentEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.instruments WHERE instrument_id = $1",
            instrument_id,
        )
        return row_to_entity(row, InstrumentEntity) if row else None

    async def get_many(self, instrument_ids: Sequence[UUID]) -> dict[UUID, InstrumentEntity]:
        if not instrument_ids:
            return {}
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.instruments WHERE instrument_id = ANY($1::uuid[])",
            list(set(instrument_ids)),
        )
        entities = [row_to_entity(row, InstrumentEntity) for row in rows]
        return {e.instrument_id: e for e in entities}

    async def get_by_symbol(self, symbol: str, market_code: str) -> InstrumentEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.instruments WHERE symbol = $1 AND market_code = $2",
            symbol,
            market_code,
        )
        return row_to_entity(row, InstrumentEntity) if row else None

    async def get_by_symbol_any_market(self, symbol: str) -> InstrumentEntity | None:
        row = await self._tx.connection.fetchrow(
            """
            SELECT *
            FROM trading.instruments
            WHERE symbol = $1
            ORDER BY
                CASE
                    WHEN exchange_code = 'KRX' AND market_code = 'KRX' THEN 0
                    WHEN exchange_code = 'KRX' AND is_active = true THEN 1
                    WHEN exchange_code = 'KRX' THEN 2
                    WHEN is_active = true THEN 3
                    ELSE 4
                END,
                CASE
                    WHEN market_segment IN ('KOSPI', 'KOSDAQ') THEN 0
                    ELSE 1
                END,
                updated_at DESC NULLS LAST,
                created_at DESC NULLS LAST
            LIMIT 1
            """,
            symbol,
        )
        return row_to_entity(row, InstrumentEntity) if row else None

    async def get_by_symbols_any_market(
        self, symbols: Sequence[str]
    ) -> dict[str, InstrumentEntity]:
        if not symbols:
            return {}
        rows = await self._tx.connection.fetch(
            """
            SELECT * FROM (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY symbol
                        ORDER BY
                            CASE
                                WHEN exchange_code = 'KRX' AND market_code = 'KRX' THEN 0
                                WHEN exchange_code = 'KRX' AND is_active = true THEN 1
                                WHEN exchange_code = 'KRX' THEN 2
                                WHEN is_active = true THEN 3
                                ELSE 4
                            END,
                            CASE
                                WHEN market_segment IN ('KOSPI', 'KOSDAQ') THEN 0
                                ELSE 1
                            END,
                            updated_at DESC NULLS LAST,
                            created_at DESC NULLS LAST
                    ) AS rn
                FROM trading.instruments
                WHERE symbol = ANY($1::text[])
            ) ranked
            WHERE rn = 1
            """,
            list(set(symbols)),
        )
        entities = [row_to_entity(row, InstrumentEntity) for row in rows]
        return {e.symbol: e for e in entities}

    async def upsert_by_symbol(self, instrument: InstrumentEntity) -> InstrumentEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.instruments
                (instrument_id, symbol, market_code, asset_class, currency,
                 name, tick_size, lot_size, is_active, exchange_code, market_segment, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb)
            ON CONFLICT (symbol, market_code) DO UPDATE
                SET name = EXCLUDED.name,
                    asset_class = EXCLUDED.asset_class,
                    currency = EXCLUDED.currency,
                    tick_size = EXCLUDED.tick_size,
                    lot_size = EXCLUDED.lot_size,
                    is_active = EXCLUDED.is_active,
                    exchange_code = EXCLUDED.exchange_code,
                    market_segment = EXCLUDED.market_segment,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
            RETURNING *
            """,
            instrument.instrument_id,
            instrument.symbol,
            instrument.market_code,
            instrument.asset_class,
            instrument.currency,
            instrument.name,
            instrument.tick_size,
            instrument.lot_size,
            instrument.is_active,
            instrument.exchange_code,
            instrument.market_segment,
            json.dumps(instrument.metadata) if instrument.metadata is not None else None,
        )
        return row_to_entity(row, InstrumentEntity)

    async def list_active_by_market(
        self, market_code: str
    ) -> Sequence[InstrumentEntity]:
        """List all active instruments for a given market code.

        Returns only ``is_active=true`` instruments, ordered by symbol.
        """
        rows = await self._tx.connection.fetch(
            """
            SELECT * FROM trading.instruments
            WHERE market_code = $1 AND is_active = true AND symbol != 'E2ESUM'
            ORDER BY symbol
            """,
            market_code,
        )
        return [row_to_entity(row, InstrumentEntity) for row in rows]
