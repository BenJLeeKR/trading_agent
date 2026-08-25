"""PostgreSQL ``FdcQuotaRepository`` 구현.

설계 근거: docs/40_action_plans/fdc_cycle_scoped_batch_queue_gemini_
shared_13rpm_quota_design_2026-08-25.md §6·§8·§9.
"""

from __future__ import annotations

import uuid
from datetime import datetime

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

    ``try_reserve()``와 ``register_shadow_job_and_judge()`` 둘 다
    생성자에 주입된 ambient ``tx``(요청 단위 공유 트랜잭션)를 쓰지
    않고 **자신만의 독립 트랜잭션**을 새로 연다(``TransactionManager()``
    직접 생성) — 두 메서드 모두 "여러 동시 호출자 사이의 원자적 FIFO
    경쟁"이 존재 이유이므로, 호출자의 ambient 트랜잭션(길게는
    `assemble()` 전체 요청 범위)에 얹으면 anchor 행 잠금이 그 요청이
    끝날 때까지 유지돼 다른 호출자를 불필요하게 막는다. ``try_reserve()``
    는 Phase 1에서 실제 런타임 경로에서 호출되지 않는다(단위/통합
    테스트 전용). ``register_shadow_job_and_judge()``는 Phase 1의 실제
    관측 경로다.
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
                anchor_row = await reservation_tx.connection.fetchrow(
                    "SELECT quota_scope FROM trading.fdc_quota_state "
                    "WHERE quota_scope = $1 FOR UPDATE",
                    quota_scope,
                )
                if anchor_row is None:
                    # anchor 행이 없으면 ``FOR UPDATE``가 아무것도 잠그지
                    # 못한 채 조용히 통과한다 — 그대로 진행하면 직렬화
                    # 보장 없이 quota를 판단/소비하는 fail-open이 된다.
                    # migration/seed 누락은 정상 상태가 아니므로 명확한
                    # fail-closed 오류로 즉시 종료한다.
                    await reservation_tx.rollback()
                    return CoordinatorError(
                        CoordinatorErrorClass.COORDINATOR_TRANSACTION_ERROR,
                        f"anchor row missing for quota_scope={quota_scope!r} "
                        "in trading.fdc_quota_state — seed the anchor row "
                        "before use (fail-closed, quota not consumed)",
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

    async def register_shadow_job_and_judge(
        self,
        *,
        quota_scope: str,
        target_rpm: int,
        window_seconds: int,
        decision_cycle_id: str | None,
        decision_context_id: uuid.UUID | None,
        symbol: str,
        source_type: str,
        fdc_ready_at: datetime,
        caller_id: str = "ops-scheduler",
        lock_timeout_ms: int = 3000,
    ) -> ShadowJudgementResult:
        try:
            async with TransactionManager() as shadow_tx:
                await shadow_tx.connection.execute(
                    f"SET LOCAL lock_timeout = {int(lock_timeout_ms)}"
                )
                # 다른 shadow 등록(및 try_reserve)과 동일한 anchor 행을
                # 잠가 FIFO 등록 순서를 직렬화한다 — 새치기 방지의 핵심.
                anchor_row = await shadow_tx.connection.fetchrow(
                    "SELECT quota_scope FROM trading.fdc_quota_state "
                    "WHERE quota_scope = $1 FOR UPDATE",
                    quota_scope,
                )
                if anchor_row is None:
                    # anchor 행이 없으면 ``FOR UPDATE``가 아무것도 잠그지
                    # 못해 동시 등록 직렬화(새치기 방지)가 보장되지 않는다
                    # — fail-open으로 shadow job을 등록하는 대신 명확한
                    # fail-closed 오류로 즉시 종료한다(shadow job 미등록).
                    await shadow_tx.rollback()
                    return CoordinatorError(
                        CoordinatorErrorClass.COORDINATOR_TRANSACTION_ERROR,
                        f"anchor row missing for quota_scope={quota_scope!r} "
                        "in trading.fdc_quota_state — seed the anchor row "
                        "before use (fail-closed, shadow job not registered)",
                    )

                job_id = uuid.uuid4()
                inserted = await shadow_tx.connection.fetchrow(
                    "INSERT INTO trading.fdc_queue_jobs "
                    "(job_id, decision_cycle_id, decision_context_id, symbol, "
                    " source_type, quota_scope, mode, status, fdc_ready_at) "
                    "VALUES ($1, $2, $3, $4, $5, $6, 'shadow', 'SHADOW_QUEUED', $7) "
                    "RETURNING enqueue_sequence",
                    job_id,
                    decision_cycle_id,
                    decision_context_id,
                    symbol,
                    source_type,
                    quota_scope,
                    fdc_ready_at,
                )
                enqueue_sequence = inserted["enqueue_sequence"]

                # FIFO 가상 sliding window: 나(enqueue_sequence 기준으로
                # 나보다 앞선)보다 먼저 등록되고 이미 SHADOW_WOULD_GRANT로
                # 확정된 job 중, 내 fdc_ready_at 기준 (t-window, t] 구간에
                # 속하는 것만 센다. enqueue_sequence는 anchor 행 잠금 하에
                # DB가 발급하므로 Python 완료 순서와 무관하게 실제 등록
                # 순서를 그대로 반영한다.
                window_count = await shadow_tx.connection.fetchval(
                    "SELECT count(*) FROM trading.fdc_queue_jobs "
                    "WHERE quota_scope = $1 AND mode = 'shadow' "
                    "AND status = 'SHADOW_WOULD_GRANT' "
                    "AND enqueue_sequence < $2 "
                    "AND fdc_ready_at > $3::timestamptz - make_interval(secs => $4) "
                    "AND fdc_ready_at <= $3::timestamptz",
                    quota_scope,
                    enqueue_sequence,
                    fdc_ready_at,
                    window_seconds,
                )

                would_grant = window_count < target_rpm
                new_status = "SHADOW_WOULD_GRANT" if would_grant else "SHADOW_QUEUED"
                await shadow_tx.connection.execute(
                    "UPDATE trading.fdc_queue_jobs SET "
                    "status = $2, queue_poll_count = queue_poll_count + 1, "
                    "updated_at = now() WHERE job_id = $1",
                    job_id,
                    new_status,
                )

                attempt_id = uuid.uuid4()
                outcome = "shadow_would_grant" if would_grant else "shadow_queued"
                await shadow_tx.connection.execute(
                    "INSERT INTO trading.fdc_provider_attempts "
                    "(attempt_id, job_id, quota_scope, caller_id, mode, "
                    " attempt_no, outcome, reserved_at) "
                    "VALUES ($1, $2, $3, $4, 'shadow', 1, $5, $6)",
                    attempt_id,
                    job_id,
                    quota_scope,
                    caller_id,
                    outcome,
                    fdc_ready_at,
                )

                await shadow_tx.commit()
                return ShadowJudgement(
                    job_id=job_id,
                    would_grant=would_grant,
                    window_count=window_count,
                    attempt_id=attempt_id,
                    enqueue_sequence=enqueue_sequence,
                )
        except asyncpg.PostgresError as exc:
            return CoordinatorError(_classify_error(exc), str(exc))
        except (OSError, ConnectionError) as exc:
            return CoordinatorError(_classify_error(exc), str(exc))
