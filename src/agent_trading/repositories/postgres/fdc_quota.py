"""PostgreSQL ``FdcQuotaRepository`` 구현.

설계 근거: docs/40_action_plans/fdc_cycle_scoped_batch_queue_gemini_
shared_13rpm_quota_design_2026-08-25.md §6·§8·§9.
"""

from __future__ import annotations

import uuid

import asyncpg

from agent_trading.db.transaction import TransactionManager
from agent_trading.repositories.contracts import (
    CoordinatorError,
    CoordinatorErrorClass,
    ReservationDenied,
    ReservationGrant,
    ReservationResult,
    ShadowJudgement,
    ShadowJudgementResult,
)

# reservation 성공/진행 중/완료 등 "이 window의 슬롯을 소비한" 것으로
# 간주하는 모든 outcome. reserved_but_http_not_started도 포함해야
# 슬롯 이중 사용을 막는다(설계 문서 §6).
_QUOTA_CONSUMING_OUTCOMES = (
    "reservation_granted",
    "http_started",
    "http_succeeded",
    "http_failed_retryable",
    "http_failed_final",
    "reserved_but_http_not_started",
)


def _classify_error(exc: Exception) -> CoordinatorErrorClass:
    if isinstance(exc, (asyncpg.LockNotAvailableError, asyncpg.QueryCanceledError)):
        return CoordinatorErrorClass.COORDINATOR_LOCK_TIMEOUT
    if isinstance(
        exc,
        (asyncpg.PostgresConnectionError, asyncpg.InterfaceError, OSError, ConnectionError),
    ):
        return CoordinatorErrorClass.COORDINATOR_UNAVAILABLE
    return CoordinatorErrorClass.COORDINATOR_TRANSACTION_ERROR


class PostgresFdcQuotaRepository:
    """``fdc_quota_state``/``fdc_queue_jobs``/``fdc_provider_attempts`` 구현.

    ``create_shadow_job()``/``judge_shadow_reservation()``은 다른 저장소와
    동일하게 생성자에 주입된 ambient ``tx``(요청 단위 공유 트랜잭션)를
    사용한다 — 단순 관측 기록이라 별도 원자성이 필요 없다.

    ``try_reserve()``만 예외적으로 **자신만의 독립 트랜잭션**을 새로
    연다(``TransactionManager()`` 직접 생성) — 이 메서드의 존재 이유
    자체가 "여러 동시 호출자 사이의 원자적 경쟁"이므로, 호출자의 ambient
    트랜잭션(길게는 `assemble()` 전체 요청 범위)에 얹으면 anchor 행
    잠금이 그 요청이 끝날 때까지 유지돼 다른 호출자를 불필요하게
    막는다. Phase 1에서는 이 메서드가 실제 런타임 경로에서 호출되지
    않으므로(단위/통합 테스트 전용) 이 설계 결정의 실제 영향은 없다.
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def try_reserve(
        self,
        *,
        quota_scope: str,
        target_rpm: int,
        window_seconds: int,
        job_id: uuid.UUID | None,
        caller_id: str,
        mode: str = "real",
        manual_run_id: str | None = None,
        attempt_no: int = 1,
        lock_timeout_ms: int = 3000,
    ) -> ReservationResult:
        try:
            async with TransactionManager() as reservation_tx:
                await reservation_tx.connection.execute(
                    f"SET LOCAL lock_timeout = {int(lock_timeout_ms)}"
                )
                await reservation_tx.connection.fetchrow(
                    "SELECT quota_scope FROM trading.fdc_quota_state "
                    "WHERE quota_scope = $1 FOR UPDATE",
                    quota_scope,
                )

                window_count = await reservation_tx.connection.fetchval(
                    "SELECT count(*) FROM trading.fdc_provider_attempts "
                    "WHERE quota_scope = $1 AND mode = 'real' "
                    "AND outcome = ANY($2::text[]) "
                    "AND reserved_at > now() - make_interval(secs => $3)",
                    quota_scope,
                    list(_QUOTA_CONSUMING_OUTCOMES),
                    window_seconds,
                )

                if window_count >= target_rpm:
                    if job_id is not None:
                        await reservation_tx.connection.execute(
                            "UPDATE trading.fdc_queue_jobs SET "
                            "queue_poll_count = queue_poll_count + 1, "
                            "reservation_denied_count = reservation_denied_count + 1, "
                            "updated_at = now() WHERE job_id = $1",
                            job_id,
                        )
                    await reservation_tx.commit()
                    return ReservationDenied(
                        quota_scope=quota_scope, window_count=window_count
                    )

                reservation_id = uuid.uuid4()
                await reservation_tx.connection.execute(
                    "INSERT INTO trading.fdc_provider_attempts "
                    "(attempt_id, job_id, manual_run_id, quota_scope, caller_id, "
                    " mode, attempt_no, outcome, reserved_at) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, 'reservation_granted', now())",
                    reservation_id,
                    job_id,
                    manual_run_id,
                    quota_scope,
                    caller_id,
                    mode,
                    attempt_no,
                )
                if job_id is not None:
                    await reservation_tx.connection.execute(
                        "UPDATE trading.fdc_queue_jobs SET "
                        "queue_poll_count = queue_poll_count + 1, "
                        "dispatch_attempt_no = dispatch_attempt_no + 1, "
                        "permit_consumed_count = permit_consumed_count + 1, "
                        "status = 'RESERVATION_GRANTED', updated_at = now() "
                        "WHERE job_id = $1",
                        job_id,
                    )
                await reservation_tx.commit()
                return ReservationGrant(
                    reservation_id=reservation_id,
                    quota_scope=quota_scope,
                    job_id=job_id,
                    attempt_no=attempt_no,
                    window_count_before_grant=window_count,
                )
        except asyncpg.PostgresError as exc:
            return CoordinatorError(_classify_error(exc), str(exc))
        except (OSError, ConnectionError) as exc:
            return CoordinatorError(_classify_error(exc), str(exc))

    async def create_shadow_job(
        self,
        *,
        decision_cycle_id: str | None,
        decision_context_id: uuid.UUID | None,
        symbol: str,
        source_type: str,
    ) -> uuid.UUID:
        job_id = uuid.uuid4()
        await self._tx.connection.execute(
            "INSERT INTO trading.fdc_queue_jobs "
            "(job_id, decision_cycle_id, decision_context_id, symbol, "
            " source_type, mode, status) "
            "VALUES ($1, $2, $3, $4, $5, 'shadow', 'QUEUED')",
            job_id,
            decision_cycle_id,
            decision_context_id,
            symbol,
            source_type,
        )
        return job_id

    async def judge_shadow_reservation(
        self,
        *,
        job_id: uuid.UUID,
        quota_scope: str,
        target_rpm: int,
        window_seconds: int,
        caller_id: str = "ops-scheduler",
    ) -> ShadowJudgementResult:
        try:
            window_count = await self._tx.connection.fetchval(
                "SELECT count(*) FROM trading.fdc_provider_attempts "
                "WHERE quota_scope = $1 AND mode = 'real' "
                "AND outcome = ANY($2::text[]) "
                "AND reserved_at > now() - make_interval(secs => $3)",
                quota_scope,
                list(_QUOTA_CONSUMING_OUTCOMES),
                window_seconds,
            )
            would_grant = window_count < target_rpm
            attempt_id = uuid.uuid4()
            outcome = "shadow_would_grant" if would_grant else "shadow_denied"
            await self._tx.connection.execute(
                "INSERT INTO trading.fdc_provider_attempts "
                "(attempt_id, job_id, quota_scope, caller_id, mode, "
                " attempt_no, outcome, reserved_at) "
                "VALUES ($1, $2, $3, $4, 'shadow', 1, $5, now())",
                attempt_id,
                job_id,
                quota_scope,
                caller_id,
                outcome,
            )
            await self._tx.connection.execute(
                "UPDATE trading.fdc_queue_jobs SET "
                "status = $2, queue_poll_count = queue_poll_count + 1, "
                "updated_at = now() WHERE job_id = $1",
                job_id,
                "SHADOW_WOULD_GRANT" if would_grant else "SHADOW_DENIED",
            )
            return ShadowJudgement(
                would_grant=would_grant,
                window_count=window_count,
                attempt_id=attempt_id,
            )
        except asyncpg.PostgresError as exc:
            return CoordinatorError(_classify_error(exc), str(exc))
        except (OSError, ConnectionError) as exc:
            return CoordinatorError(_classify_error(exc), str(exc))
