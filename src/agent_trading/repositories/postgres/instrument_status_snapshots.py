from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import InstrumentStatusSnapshotEntity


class PostgresInstrumentStatusSnapshotRepository:
    """PostgreSQL implementation of ``InstrumentStatusSnapshotRepository``."""

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(
        self,
        snapshot: InstrumentStatusSnapshotEntity,
    ) -> InstrumentStatusSnapshotEntity:
        async with self._tx.savepoint():
            row = await self._tx.connection.fetchrow(
                """
                INSERT INTO trading.instrument_status_snapshots
                    (instrument_status_snapshot_id, instrument_id, snapshot_at,
                     source_type, status_scope,
                     tr_stop_yn, admn_item_yn, nxt_tr_stop_yn, temp_stop_yn,
                     iscd_stat_cls_code, mket_id_cd, scty_grp_id_cd,
                     excg_dvsn_cd, prdt_type_cd,
                     status_reason_codes, raw_payload_json, created_at)
                VALUES ($1, $2, $3,
                        $4, $5,
                        $6, $7, $8, $9,
                        $10, $11, $12,
                        $13, $14,
                        $15::jsonb, $16::jsonb, COALESCE($17, NOW()))
                ON CONFLICT (instrument_id, snapshot_at, source_type, status_scope)
                DO UPDATE SET
                    tr_stop_yn = EXCLUDED.tr_stop_yn,
                    admn_item_yn = EXCLUDED.admn_item_yn,
                    nxt_tr_stop_yn = EXCLUDED.nxt_tr_stop_yn,
                    temp_stop_yn = EXCLUDED.temp_stop_yn,
                    iscd_stat_cls_code = EXCLUDED.iscd_stat_cls_code,
                    mket_id_cd = EXCLUDED.mket_id_cd,
                    scty_grp_id_cd = EXCLUDED.scty_grp_id_cd,
                    excg_dvsn_cd = EXCLUDED.excg_dvsn_cd,
                    prdt_type_cd = EXCLUDED.prdt_type_cd,
                    status_reason_codes = EXCLUDED.status_reason_codes,
                    raw_payload_json = EXCLUDED.raw_payload_json
                RETURNING *
                """,
                snapshot.instrument_status_snapshot_id,
                snapshot.instrument_id,
                snapshot.snapshot_at,
                snapshot.source_type,
                snapshot.status_scope,
                snapshot.tr_stop_yn,
                snapshot.admn_item_yn,
                snapshot.nxt_tr_stop_yn,
                snapshot.temp_stop_yn,
                snapshot.iscd_stat_cls_code,
                snapshot.mket_id_cd,
                snapshot.scty_grp_id_cd,
                snapshot.excg_dvsn_cd,
                snapshot.prdt_type_cd,
                json.dumps(snapshot.status_reason_codes),
                json.dumps(snapshot.raw_payload_json),
                snapshot.created_at,
            )
        return row_to_entity(row, InstrumentStatusSnapshotEntity)

    async def get_latest_by_instrument(
        self,
        instrument_id: UUID,
    ) -> InstrumentStatusSnapshotEntity | None:
        row = await self._tx.connection.fetchrow(
            """
            SELECT *
            FROM trading.instrument_status_snapshots
            WHERE instrument_id = $1
            ORDER BY snapshot_at DESC, created_at DESC, instrument_status_snapshot_id DESC
            LIMIT 1
            """,
            instrument_id,
        )
        return row_to_entity(row, InstrumentStatusSnapshotEntity) if row else None

    async def get_latest_by_instrument_before(
        self,
        instrument_id: UUID,
        as_of: datetime,
    ) -> InstrumentStatusSnapshotEntity | None:
        row = await self._tx.connection.fetchrow(
            """
            SELECT *
            FROM trading.instrument_status_snapshots
            WHERE instrument_id = $1
              AND snapshot_at <= $2
            ORDER BY snapshot_at DESC, created_at DESC, instrument_status_snapshot_id DESC
            LIMIT 1
            """,
            instrument_id,
            as_of,
        )
        return row_to_entity(row, InstrumentStatusSnapshotEntity) if row else None

    async def list_latest_by_instrument_ids(
        self,
        instrument_ids: Sequence[UUID],
    ) -> Sequence[InstrumentStatusSnapshotEntity]:
        normalized_ids = list(dict.fromkeys(instrument_ids))
        if not normalized_ids:
            return ()
        rows = await self._tx.connection.fetch(
            """
            SELECT DISTINCT ON (instrument_id) *
            FROM trading.instrument_status_snapshots
            WHERE instrument_id = ANY($1::uuid[])
            ORDER BY instrument_id, snapshot_at DESC, created_at DESC, instrument_status_snapshot_id DESC
            """,
            normalized_ids,
        )
        return tuple(row_to_entity(row, InstrumentStatusSnapshotEntity) for row in rows)
