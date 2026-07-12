from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import InstrumentIndexMembershipEntity


class PostgresInstrumentIndexMembershipRepository:
    """PostgreSQL implementation of ``InstrumentIndexMembershipRepository``."""

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def sync_current_memberships(
        self,
        instrument_id: UUID,
        membership_codes: Sequence[str],
        *,
        effective_from: date,
        source_tag: str | None = None,
        metadata: dict[str, object] | None = None,
        refresh_existing_metadata: bool = False,
    ) -> Sequence[InstrumentIndexMembershipEntity]:
        normalized_codes = sorted(
            {
                str(code).strip().upper()
                for code in membership_codes
                if str(code).strip()
            }
        )
        active_rows = await self._tx.connection.fetch(
            """
            SELECT *
            FROM trading.instrument_index_memberships
            WHERE instrument_id = $1
              AND effective_to IS NULL
            ORDER BY membership_code
            """,
            instrument_id,
        )
        active_by_code = {
            str(row["membership_code"]).strip().upper(): row
            for row in active_rows
        }

        removed_codes = set(active_by_code) - set(normalized_codes)
        if removed_codes:
            await self._tx.connection.execute(
                """
                UPDATE trading.instrument_index_memberships
                SET effective_to = $3,
                    updated_at = NOW()
                WHERE instrument_id = $1
                  AND membership_code = ANY($2::text[])
                  AND effective_to IS NULL
                """,
                instrument_id,
                list(removed_codes),
                effective_from,
            )

        shared_metadata = json.dumps(metadata or {})
        now = datetime.now(timezone.utc)
        if refresh_existing_metadata and normalized_codes:
            await self._tx.connection.execute(
                """
                UPDATE trading.instrument_index_memberships
                   SET source_tag = $3,
                       metadata = $4::jsonb,
                       updated_at = $5
                 WHERE instrument_id = $1
                   AND membership_code = ANY($2::text[])
                   AND effective_to IS NULL
                """,
                instrument_id,
                list(normalized_codes),
                source_tag,
                shared_metadata,
                now,
            )
        for code in normalized_codes:
            if code in active_by_code:
                continue
            await self._tx.connection.execute(
                """
                INSERT INTO trading.instrument_index_memberships
                    (instrument_index_membership_id, instrument_id, membership_code,
                     effective_from, effective_to, source_tag, metadata,
                     created_at, updated_at)
                VALUES ($1, $2, $3,
                        $4, NULL, $5, $6::jsonb,
                        $7, $8)
                """,
                uuid4(),
                instrument_id,
                code,
                effective_from,
                source_tag,
                shared_metadata,
                now,
                now,
            )

        return await self.list_active_by_instrument(instrument_id)

    async def list_active_by_instrument(
        self,
        instrument_id: UUID,
    ) -> Sequence[InstrumentIndexMembershipEntity]:
        rows = await self._tx.connection.fetch(
            """
            SELECT *
            FROM trading.instrument_index_memberships
            WHERE instrument_id = $1
              AND effective_to IS NULL
            ORDER BY membership_code
            """,
            instrument_id,
        )
        return tuple(row_to_entity(row, InstrumentIndexMembershipEntity) for row in rows)

    async def list_active_by_instruments(
        self,
        instrument_ids: Sequence[UUID],
    ) -> dict[UUID, Sequence[InstrumentIndexMembershipEntity]]:
        if not instrument_ids:
            return {}
        rows = await self._tx.connection.fetch(
            """
            SELECT *
            FROM trading.instrument_index_memberships
            WHERE instrument_id = ANY($1::uuid[])
              AND effective_to IS NULL
            ORDER BY instrument_id, membership_code
            """,
            list(set(instrument_ids)),
        )
        result: dict[UUID, list[InstrumentIndexMembershipEntity]] = {}
        for row in rows:
            entity = row_to_entity(row, InstrumentIndexMembershipEntity)
            result.setdefault(entity.instrument_id, []).append(entity)
        return result

    async def list_active_instrument_ids_by_membership_code(
        self,
        membership_code: str,
    ) -> Sequence[UUID]:
        rows = await self._tx.connection.fetch(
            """
            SELECT DISTINCT instrument_id
            FROM trading.instrument_index_memberships
            WHERE membership_code = $1
              AND effective_to IS NULL
            ORDER BY instrument_id
            """,
            str(membership_code).strip().upper(),
        )
        return tuple(UUID(str(row["instrument_id"])) for row in rows)

    async def get_latest_effective_from(self) -> date | None:
        row = await self._tx.connection.fetchrow(
            """
            SELECT MAX(effective_from) AS latest_effective_from
            FROM trading.instrument_index_memberships
            WHERE effective_to IS NULL
            """
        )
        if row is None:
            return None
        value = row["latest_effective_from"]
        return value if isinstance(value, date) else None
