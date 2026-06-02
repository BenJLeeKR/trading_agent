from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import OrderSubmissionAttemptEntity


class PostgresOrderSubmissionAttemptRepository:
    """PostgreSQL implementation of ``OrderSubmissionAttemptRepository``.

    Satisfies the protocol defined in ``repositories/contracts.py``.
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(
        self, attempt: OrderSubmissionAttemptEntity
    ) -> OrderSubmissionAttemptEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.order_submission_attempts
                (order_request_id, attempt_number, submitted_at,
                 broker_name, accepted, broker_native_order_id, broker_status,
                 raw_code, raw_message, error_type, retryable, http_status,
                 request_payload_uri, response_payload_uri, duration_ms)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            RETURNING *
            """,
            attempt.order_request_id,
            attempt.attempt_number,
            attempt.submitted_at,
            attempt.broker_name,
            attempt.accepted,
            attempt.broker_native_order_id,
            attempt.broker_status,
            attempt.raw_code,
            attempt.raw_message,
            attempt.error_type,
            attempt.retryable,
            attempt.http_status,
            attempt.request_payload_uri,
            attempt.response_payload_uri,
            attempt.duration_ms,
        )
        return row_to_entity(row, OrderSubmissionAttemptEntity)

    async def list_by_order_request(
        self, order_request_id: UUID
    ) -> Sequence[OrderSubmissionAttemptEntity]:
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.order_submission_attempts "
            "WHERE order_request_id = $1 "
            "ORDER BY attempt_number ASC",
            order_request_id,
        )
        return tuple(row_to_entity(r, OrderSubmissionAttemptEntity) for r in rows)

    async def get_failure_summary(self) -> dict[str, Any]:
        """Return aggregated failure counts for the last 1h, 24h, and KST today.

        Counts all submission attempts (not DISTINCT ON per order request),
        then derives the outcome per attempt using the same logic as
        ``list_recent_failures``.

        Returns a dict with keys:
        - last_1h_count, last_24h_count, rejected_count, exception_count,
          total_submissions_24h, failure_rate_pct_24h,
          today_count, rejected_count_today, exception_count_today,
          total_submissions_today, failure_rate_pct_today
        """
        sql = """
            WITH outcome AS (
                SELECT
                    submitted_at,
                    CASE
                        WHEN error_type IS NOT NULL THEN 'exception'
                        WHEN accepted = FALSE THEN 'rejected'
                        WHEN accepted = TRUE THEN 'accepted'
                        ELSE NULL
                    END AS outcome
                FROM trading.order_submission_attempts
                WHERE submitted_at >= NOW() - INTERVAL '24 hours'
                   OR submitted_at >= (
                        (date_trunc('day', NOW() AT TIME ZONE 'Asia/Seoul'))
                        AT TIME ZONE 'Asia/Seoul'
                   )
            )
            SELECT
                COUNT(*) FILTER (
                    WHERE outcome IN ('rejected', 'exception')
                      AND submitted_at >= NOW() - INTERVAL '1 hour'
                ) AS last_1h_count,
                COUNT(*) FILTER (
                    WHERE outcome IN ('rejected', 'exception')
                ) AS last_24h_count,
                COUNT(*) FILTER (
                    WHERE outcome = 'rejected'
                ) AS rejected_count,
                COUNT(*) FILTER (
                    WHERE outcome = 'exception'
                ) AS exception_count,
                COUNT(*) FILTER (
                    WHERE submitted_at >= NOW() - INTERVAL '24 hours'
                ) AS total_submissions_24h,
                COUNT(*) FILTER (
                    WHERE outcome IN ('rejected', 'exception')
                      AND submitted_at >= (
                        (date_trunc('day', NOW() AT TIME ZONE 'Asia/Seoul'))
                        AT TIME ZONE 'Asia/Seoul'
                      )
                ) AS today_count,
                COUNT(*) FILTER (
                    WHERE outcome = 'rejected'
                      AND submitted_at >= (
                        (date_trunc('day', NOW() AT TIME ZONE 'Asia/Seoul'))
                        AT TIME ZONE 'Asia/Seoul'
                      )
                ) AS rejected_count_today,
                COUNT(*) FILTER (
                    WHERE outcome = 'exception'
                      AND submitted_at >= (
                        (date_trunc('day', NOW() AT TIME ZONE 'Asia/Seoul'))
                        AT TIME ZONE 'Asia/Seoul'
                      )
                ) AS exception_count_today,
                COUNT(*) FILTER (
                    WHERE submitted_at >= (
                        (date_trunc('day', NOW() AT TIME ZONE 'Asia/Seoul'))
                        AT TIME ZONE 'Asia/Seoul'
                    )
                ) AS total_submissions_today
            FROM outcome
        """
        row = await self._tx.connection.fetchrow(sql)
        result = dict(row) if row else {}
        total = result.get("total_submissions_24h", 0)
        failed = result.get("last_24h_count", 0)
        total_today = result.get("total_submissions_today", 0)
        failed_today = result.get("today_count", 0)
        result["failure_rate_pct_24h"] = (
            round(failed / total * 100, 1) if total > 0 else None
        )
        result["failure_rate_pct_today"] = (
            round(failed_today / total_today * 100, 1) if total_today > 0 else None
        )
        return result

    async def list_recent_failures(self, limit: int = 10) -> Sequence[dict[str, Any]]:
        """Return the most recent submission failures (rejected or exception).

        Uses ``DISTINCT ON`` to get the latest attempt per order request,
        then filters to rejected/exception outcomes and joins with
        ``trading.order_requests`` for symbol/side/created_at.
        """
        sql = """
            WITH latest_attempts AS (
                SELECT DISTINCT ON (osa.order_request_id)
                    osa.order_request_id,
                    osa.attempt_number,
                    osa.submitted_at,
                    osa.accepted,
                    osa.raw_code,
                    osa.raw_message,
                    osa.error_type,
                    CASE
                        WHEN osa.error_type IS NOT NULL THEN 'exception'
                        WHEN osa.accepted = TRUE THEN 'accepted'
                        WHEN osa.accepted = FALSE THEN 'rejected'
                        ELSE NULL
                    END AS latest_outcome
                FROM trading.order_submission_attempts osa
                ORDER BY osa.order_request_id, osa.attempt_number DESC
            )
            SELECT
                la.order_request_id::text,
                la.latest_outcome,
                la.error_type AS latest_error_type,
                la.raw_code AS latest_raw_code,
                la.raw_message AS latest_raw_message,
                la.submitted_at AS last_submitted_at,
                o.symbol,
                o.side,
                o.created_at
            FROM latest_attempts la
            JOIN trading.order_requests o ON o.order_request_id = la.order_request_id
            WHERE la.latest_outcome IN ('rejected', 'exception')
            ORDER BY la.submitted_at DESC NULLS LAST
            LIMIT $1
        """
        rows = await self._tx.connection.fetch(sql, limit)
        return [dict(row) for row in rows]
