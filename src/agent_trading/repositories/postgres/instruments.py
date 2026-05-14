from __future__ import annotations

import json
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
                 name, tick_size, lot_size, is_active, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb)
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
            json.dumps(instrument.metadata) if instrument.metadata is not None else None,
        )
        return row_to_entity(row, InstrumentEntity)

    async def get(self, instrument_id: UUID) -> InstrumentEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.instruments WHERE instrument_id = $1",
            instrument_id,
        )
        return row_to_entity(row, InstrumentEntity) if row else None

    async def get_by_symbol(self, symbol: str, market_code: str) -> InstrumentEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.instruments WHERE symbol = $1 AND market_code = $2",
            symbol,
            market_code,
        )
        return row_to_entity(row, InstrumentEntity) if row else None

    async def upsert_by_symbol(self, instrument: InstrumentEntity) -> InstrumentEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.instruments
                (instrument_id, symbol, market_code, asset_class, currency,
                 name, tick_size, lot_size, is_active, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb)
            ON CONFLICT (symbol, market_code) DO UPDATE
                SET name = EXCLUDED.name,
                    asset_class = EXCLUDED.asset_class,
                    currency = EXCLUDED.currency,
                    tick_size = EXCLUDED.tick_size,
                    lot_size = EXCLUDED.lot_size,
                    is_active = EXCLUDED.is_active,
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
            json.dumps(instrument.metadata) if instrument.metadata is not None else None,
        )
        return row_to_entity(row, InstrumentEntity)
