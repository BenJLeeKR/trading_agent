from __future__ import annotations

import json
from uuid import UUID

import asyncpg

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import ConfigVersionEntity
from agent_trading.domain.enums import Environment


class PostgresConfigVersionRepository:
    """PostgreSQL implementation of ``ConfigVersionRepository``.

    Satisfies the protocol defined in ``repositories/contracts.py``.

    This is a replay-critical repository — ``get_active()`` is used to
    restore the configuration that was active at a given time during replay.
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(self, config_version: ConfigVersionEntity) -> ConfigVersionEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.config_versions
                (config_version_id, client_id, environment, version_tag,
                 config_json, checksum, activated_at, activated_by)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8)
            RETURNING *
            """,
            config_version.config_version_id,
            config_version.client_id,
            config_version.environment.value,
            config_version.version_tag,
            json.dumps(config_version.config_json),
            config_version.checksum,
            config_version.activated_at,
            config_version.activated_by,
        )
        return row_to_entity(row, ConfigVersionEntity)

    async def get(self, config_version_id: UUID) -> ConfigVersionEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.config_versions WHERE config_version_id = $1",
            config_version_id,
        )
        return row_to_entity(row, ConfigVersionEntity) if row else None

    async def get_active(
        self, client_id: UUID, environment: Environment
    ) -> ConfigVersionEntity | None:
        """Return the most recently activated config version for the given
        client and environment.

        ``activated_at`` may be NULL for versions that have been created
        but not yet activated. Those are excluded by ``NULLS LAST``.
        """
        row = await self._tx.connection.fetchrow(
            """
            SELECT * FROM trading.config_versions
            WHERE client_id = $1 AND environment = $2
            ORDER BY activated_at DESC NULLS LAST
            LIMIT 1
            """,
            client_id,
            environment.value,
        )
        return row_to_entity(row, ConfigVersionEntity) if row else None

    async def get_active_at(
        self, client_id: UUID, environment: Environment, at: datetime
    ) -> ConfigVersionEntity | None:
        """Return the config version that was active at the given timestamp.

        Selects the most recently activated version where ``activated_at <= at``.
        Returns ``None`` if no version was activated before the given timestamp.

        This is critical for replay: to reconstruct the system state at a
        specific point in time, we need the config that was governing at that time.
        """
        row = await self._tx.connection.fetchrow(
            """
            SELECT * FROM trading.config_versions
            WHERE client_id = $1
              AND environment = $2
              AND activated_at IS NOT NULL
              AND activated_at <= $3
            ORDER BY activated_at DESC
            LIMIT 1
            """,
            client_id,
            environment.value,
            at,
        )
        return row_to_entity(row, ConfigVersionEntity) if row else None
