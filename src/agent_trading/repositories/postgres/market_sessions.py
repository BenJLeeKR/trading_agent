from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timezone

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import (
    MarketSessionEntity,
    SessionEventEntity,
)


class PostgresMarketSessionRepository:
    """PostgreSQL implementation of ``MarketSessionRepository``.

    ``market_sessions`` 테이블은 ``run_date`` 기준 unique index가 있으며,
    ``INSERT … ON CONFLICT (run_date) DO UPDATE`` 로 upsert 한다.

    ``session_events`` 테이블은 append-only 이벤트 로그이다.
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def upsert(self, session: MarketSessionEntity) -> MarketSessionEntity:
        """Upsert a market session by ``run_date``.

        동일 ``run_date`` 가 이미 존재하면 업데이트, 없으면 INSERT.
        ``RETURNING *`` 으로 서버 생성값(id, created_at 등)을 반환받는다.
        """
        row = await self._tx.connection.fetchrow(
            """INSERT INTO trading.market_sessions
               (run_date, is_trading_day,
                opnd_yn, bzdy_yn, tr_day_yn,
                market_phase,
                raw_opnd_yn, raw_mkop_cls_code, raw_antc_mkop_cls_code,
                source, reason_code, reason,
                checked_at, updated_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
               ON CONFLICT (run_date) DO UPDATE SET
                   is_trading_day    = EXCLUDED.is_trading_day,
                   opnd_yn           = EXCLUDED.opnd_yn,
                   bzdy_yn           = EXCLUDED.bzdy_yn,
                   tr_day_yn         = EXCLUDED.tr_day_yn,
                   market_phase      = EXCLUDED.market_phase,
                   raw_opnd_yn       = EXCLUDED.raw_opnd_yn,
                   raw_mkop_cls_code = EXCLUDED.raw_mkop_cls_code,
                   raw_antc_mkop_cls_code = EXCLUDED.raw_antc_mkop_cls_code,
                   source            = EXCLUDED.source,
                   reason_code       = EXCLUDED.reason_code,
                   reason            = EXCLUDED.reason,
                   checked_at        = EXCLUDED.checked_at,
                   updated_at        = EXCLUDED.updated_at
               RETURNING *""",
            session.run_date,
            session.is_trading_day,
            session.opnd_yn,
            session.bzdy_yn,
            session.tr_day_yn,
            session.market_phase,
            session.raw_opnd_yn,
            session.raw_mkop_cls_code,
            session.raw_antc_mkop_cls_code,
            session.source,
            session.reason_code,
            session.reason,
            session.checked_at or datetime.now(timezone.utc),
            datetime.now(timezone.utc),
        )
        return row_to_entity(row, MarketSessionEntity)

    async def get_by_run_date(self, run_date: date) -> MarketSessionEntity | None:
        """Get the session state for a specific run date."""
        row = await self._tx.connection.fetchrow(
            """SELECT * FROM trading.market_sessions
               WHERE run_date = $1""",
            run_date,
        )
        return row_to_entity(row, MarketSessionEntity) if row else None

    async def list_recent(
        self, limit: int = 10
    ) -> Sequence[MarketSessionEntity]:
        """Return recent sessions ordered by ``run_date DESC``."""
        rows = await self._tx.connection.fetch(
            """SELECT * FROM trading.market_sessions
               ORDER BY run_date DESC
               LIMIT $1""",
            limit,
        )
        return [row_to_entity(r, MarketSessionEntity) for r in rows]

    async def add_event(self, event: SessionEventEntity) -> SessionEventEntity:
        """Append a phase-change event to the session_events log."""
        row = await self._tx.connection.fetchrow(
            """INSERT INTO trading.session_events
               (market_session_id, previous_phase, new_phase,
                trigger_source, metadata,
                occurred_at, created_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7)
               RETURNING *""",
            event.market_session_id,
            event.previous_phase,
            event.new_phase,
            event.trigger_source,
            event.metadata,
            event.occurred_at or datetime.now(timezone.utc),
            datetime.now(timezone.utc),
        )
        return row_to_entity(row, SessionEventEntity)

    async def get_events(
        self, market_session_id: int, limit: int = 50
    ) -> Sequence[SessionEventEntity]:
        """Return events for a session, ordered by ``occurred_at DESC``."""
        rows = await self._tx.connection.fetch(
            """SELECT * FROM trading.session_events
               WHERE market_session_id = $1
               ORDER BY occurred_at DESC
               LIMIT $2""",
            market_session_id,
            limit,
        )
        return [row_to_entity(r, SessionEventEntity) for r in rows]
