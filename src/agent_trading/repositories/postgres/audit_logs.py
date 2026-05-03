from __future__ import annotations

import json
from collections.abc import Sequence

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import AuditLogEntity


class PostgresAuditLogRepository:
    """PostgreSQL implementation of ``AuditLogRepository``.

    Satisfies the protocol defined in ``repositories/contracts.py``.

    All audit log entries are persisted to the ``trading.audit_logs`` table.
    The ``metadata`` and ``before_json`` / ``after_json`` columns are JSONB;
    dict values are serialised via ``json.dumps()`` before being sent to
    asyncpg.
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(self, audit_log: AuditLogEntity) -> AuditLogEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.audit_logs
                (audit_log_id, actor_type, actor_id, action,
                 target_entity_type, target_entity_id,
                 before_json, after_json,
                 correlation_id, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9, $10::jsonb)
            RETURNING *
            """,
            audit_log.audit_log_id,
            audit_log.actor_type,
            audit_log.actor_id,
            audit_log.action,
            audit_log.target_entity_type,
            audit_log.target_entity_id,
            json.dumps(audit_log.before_json) if audit_log.before_json is not None else None,
            json.dumps(audit_log.after_json) if audit_log.after_json is not None else None,
            audit_log.correlation_id,
            json.dumps(audit_log.metadata) if audit_log.metadata is not None else None,
        )
        return row_to_entity(row, AuditLogEntity)

    async def list_by_correlation_id(
        self, correlation_id: str
    ) -> Sequence[AuditLogEntity]:
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.audit_logs WHERE correlation_id = $1 ORDER BY created_at, audit_log_seq",
            correlation_id,
        )
        return tuple(row_to_entity(r, AuditLogEntity) for r in rows)
