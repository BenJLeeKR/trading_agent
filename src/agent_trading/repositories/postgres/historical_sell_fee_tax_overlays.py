from __future__ import annotations

from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import HistoricalSellFeeTaxOverlayEntity


class PostgresHistoricalSellFeeTaxOverlayRepository:
    """PostgreSQL implementation of ``HistoricalSellFeeTaxOverlayRepository``.

    ``trading.historical_sell_fee_tax_overlays``는 append-only다 —
    ``fill_event_id`` UNIQUE 제약이 idempotency의 1차 방어선이다(같은
    fill에 두 번째 overlay를 추가하려 하면 DB가 거부한다).
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(
        self, overlay: HistoricalSellFeeTaxOverlayEntity
    ) -> HistoricalSellFeeTaxOverlayEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.historical_sell_fee_tax_overlays
                (overlay_id, fill_event_id, estimated_fee, estimated_tax,
                 fee_tax_source, basis_config_version_id, reason, created_by)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING *
            """,
            overlay.overlay_id,
            overlay.fill_event_id,
            overlay.estimated_fee,
            overlay.estimated_tax,
            overlay.fee_tax_source,
            overlay.basis_config_version_id,
            overlay.reason,
            overlay.created_by,
        )
        return row_to_entity(row, HistoricalSellFeeTaxOverlayEntity)

    async def get_by_fill_event_id(
        self, fill_event_id: UUID
    ) -> HistoricalSellFeeTaxOverlayEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.historical_sell_fee_tax_overlays WHERE fill_event_id = $1",
            fill_event_id,
        )
        return row_to_entity(row, HistoricalSellFeeTaxOverlayEntity) if row else None
