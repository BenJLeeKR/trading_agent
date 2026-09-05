"""PostgreSQL ``FdcQuotaRepository`` 구현.

설계 근거: docs/40_action_plans/fdc_cycle_scoped_batch_queue_gemini_
shared_13rpm_quota_design_2026-08-25.md §6·§8·§9.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any

import asyncpg

from agent_trading.db.transaction import TransactionManager
from agent_trading.repositories.contracts import (
    AttemptHttpLifecycle,
    CoordinatorError,
    CoordinatorErrorClass,
    ProviderGlobalGateDenied,
    ProviderGlobalGateGranted,
    ProviderGlobalGateResult,
    ResumableRealJob,
    ReservationDenied,
    ReservationGrant,
    ReservationResult,
    ShadowJudgement,
    ShadowJudgementResult,
)

logger = logging.getLogger(__name__)

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

                # FIFO 공정성(2026-08-27, held_position 실제 dispatcher 신설
                # — PR #359 리뷰 보정): job_id가 있는 호출(=dispatcher가
                # 관리하는 real job)에 한해, 나보다 먼저 등록됐고 아직
                # QUEUED 상태인(=아직 grant를 못 받은) job이 있으면 이번
                # window에 여유가 있어도 순번을 양보한다 — 동시에 여러
                # symbol의 coroutine이 각자 try_reserve()를 폴링해도
                # "늦게 등록된 job이 먼저 grant받는" 새치기를 anchor 행
                # 잠금 하에 원천 차단한다. job_id가 없는 호출(기존 manual
                # 스크립트 경로)은 이 검사 대상이 아니다 — 하위 호환.
                not_my_turn = False
                if job_id is not None:
                    earlier_queued = await reservation_tx.connection.fetchval(
                        "SELECT EXISTS(SELECT 1 FROM trading.fdc_queue_jobs "
                        "WHERE quota_scope = $1 AND mode = 'real' "
                        "AND status = 'QUEUED' "
                        "AND enqueue_sequence < ("
                        "  SELECT enqueue_sequence FROM trading.fdc_queue_jobs "
                        "  WHERE job_id = $2"
                        "))",
                        quota_scope,
                        job_id,
                    )
                    not_my_turn = bool(earlier_queued)

                if window_count >= target_rpm or not_my_turn:
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

    async def record_attempt_outcome(
        self,
        *,
        reservation_id: uuid.UUID,
        outcome: str,
        http_status: int | None = None,
        error_class: str | None = None,
        http_429_observed: bool = False,
        http_started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        """``try_reserve()``가 발급한 ``reservation_id``(=``attempt_id``)
        행에 실제 HTTP 실행 결과를 기록한다(PR A 신설 — 설계 문서 §7/§9가
        요구하는 lifecycle 기록 중, ``try_reserve()``까지는 있었으나 그
        이후 실제 HTTP outcome을 남기는 API가 코드베이스에 없어 이번에
        추가했다).

        단일 행 UPDATE이므로 anchor 행 잠금(``FOR UPDATE``)이 필요 없다
        — quota window 판단은 ``outcome`` 값 자체(``_QUOTA_CONSUMING_
        OUTCOMES``)로만 이뤄지므로, 이미 ``reservation_granted``로
        window를 소비한 행의 ``outcome`` 문자열만 갱신하면 충분하다.

        2026-08-27 리뷰 보정: 대응하는 attempt 행이 없으면(``reservation_
        id``가 실제 ``try_reserve()``가 발급한 값이 아니거나 이미
        삭제됐다면) ``UPDATE``가 조용히 0행을 갱신하고 성공한 것처럼
        반환했었다 — 이는 감사 기록 누락을 숨기는 것과 같으므로,
        ``RETURNING``으로 실제 갱신 행 수를 확인해 정확히 1행이
        아니면 명시적으로 실패시킨다(HTTP 재시도나 성공 처리로
        이어지지 않는다 — 순수하게 기록 정합성만 검증한다).

        2026-08-27 2차 리뷰 보정: ``outcome="http_started"``(실제
        ``client.post()`` 직전에 기록되는 HTTP 시작 마커, provider_
        client.py의 ``on_http_start`` 콜백이 호출)는 **``http_started_
        at``이 아직 NULL인 행에만** 적용되도록 ``WHERE`` 절에 추가
        조건을 건다 — "하나의 reservation은 하나의 실제 실행 기회에만
        대응해야 한다"는 계약을 DB 수준에서 fail-closed로 강제한다.
        같은 reservation에 HTTP 시작을 두 번 기록하려 하면(이미
        ``http_started_at``이 채워진 행) 이 조건에 걸려 0행이 갱신되고
        ``ValueError``를 던진다. 다른 outcome(성공/실패 최종 기록)은
        이 조건 없이 그대로 갱신한다 — HTTP 시작 이후 그 행의 최종
        상태를 채우는 것이 정상 흐름이기 때문이다.
        """
        extra_guard = " AND http_started_at IS NULL" if outcome == "http_started" else ""
        async with TransactionManager() as outcome_tx:
            updated_id = await outcome_tx.connection.fetchval(
                "UPDATE trading.fdc_provider_attempts SET "
                "outcome = $2, http_status = $3, error_class = $4, "
                "http_429_observed = $5, http_started_at = "
                "COALESCE($6, http_started_at), completed_at = "
                "COALESCE($7, completed_at) "
                f"WHERE attempt_id = $1{extra_guard} "
                "RETURNING attempt_id",
                reservation_id,
                outcome,
                http_status,
                error_class,
                http_429_observed,
                http_started_at,
                completed_at,
            )
            if updated_id is None:
                await outcome_tx.rollback()
                if outcome == "http_started":
                    # 행 자체가 없는지, 이미 http_started_at이 찍혀 있어
                    # 가드에 걸린 것인지 구분해 더 정확한 오류를 낸다.
                    async with TransactionManager() as check_tx:
                        existing = await check_tx.connection.fetchval(
                            "SELECT http_started_at FROM trading.fdc_provider_attempts "
                            "WHERE attempt_id = $1",
                            reservation_id,
                        )
                        await check_tx.rollback()
                    if existing is not None:
                        raise ValueError(
                            f"record_attempt_outcome: attempt_id={reservation_id!r} "
                            f"already has http_started_at={existing!r} — refusing to "
                            "record a second HTTP start for the same reservation "
                            "(one reservation = one real execution attempt)"
                        )
                raise ValueError(
                    f"record_attempt_outcome: no fdc_provider_attempts row "
                    f"for attempt_id={reservation_id!r} — nothing updated "
                    "(reservation_id must come from a prior try_reserve() "
                    "grant)"
                )
            await outcome_tx.commit()

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

    async def register_real_job(
        self,
        *,
        decision_cycle_id: str | None,
        decision_context_id: uuid.UUID | None,
        symbol: str,
        source_type: str,
        quota_scope: str,
        fdc_ready_at: datetime,
        pre_fdc_result: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> uuid.UUID:
        job_id = uuid.uuid4()
        async with TransactionManager() as reg_tx:
            await reg_tx.connection.execute(
                "INSERT INTO trading.fdc_queue_jobs "
                "(job_id, decision_cycle_id, decision_context_id, symbol, "
                " source_type, quota_scope, mode, status, fdc_ready_at, "
                " pre_fdc_result_json, correlation_id) "
                "VALUES ($1, $2, $3, $4, $5, $6, 'real', 'QUEUED', $7, "
                "$8::jsonb, $9)",
                job_id,
                decision_cycle_id,
                decision_context_id,
                symbol,
                source_type,
                quota_scope,
                fdc_ready_at,
                json.dumps(pre_fdc_result) if pre_fdc_result is not None else None,
                correlation_id,
            )
            await reg_tx.commit()
        return job_id

    async def list_resumable_real_jobs(
        self, *, quota_scope: str,
    ) -> list[ResumableRealJob]:
        async with TransactionManager() as list_tx:
            rows = await list_tx.connection.fetch(
                "SELECT job_id, symbol, source_type, decision_cycle_id, "
                "decision_context_id, correlation_id, pre_fdc_result_json, "
                "fdc_ready_at FROM trading.fdc_queue_jobs "
                "WHERE quota_scope = $1 AND mode = 'real' AND status = 'QUEUED' "
                "ORDER BY enqueue_sequence ASC",
                quota_scope,
            )
            await list_tx.commit()
        resumable = []
        for row in rows:
            raw_pre_fdc = row["pre_fdc_result_json"]
            correlation_id = row["correlation_id"]
            # 2026-08-28 5차 리뷰 보정 — 불완전한 QUEUED row를 조용히
            # 건너뛰고 로그만 남기면, try_reserve()의 FIFO admission이
            # "나보다 먼저 등록된 QUEUED job이 있으면 양보"하므로 이
            # row 하나가 뒤따르는 모든 real job을 영구 대기시킨다
            # (§17.3/§17.7). 건너뛰지 않고 즉시 fail-closed로 종결해
            # FIFO head를 비운다 — idempotent(다음 호출부터는 이미
            # 'QUEUED'가 아니므로 이 SELECT 자체에 다시 걸리지 않는다).
            if raw_pre_fdc is None or not correlation_id:
                reason = (
                    "fdc_carryover_payload_missing_data_integrity_error"
                    if raw_pre_fdc is None
                    else "fdc_carryover_correlation_id_missing_data_integrity_error"
                )
                logger.error(
                    "list_resumable_real_jobs: job_id=%s status=QUEUED인데 "
                    "%s가 없다 — 데이터 정합성 이상. 재개하지 않고 "
                    "FDC_FAILED_FINAL(reason=%s)로 즉시 종결해 FIFO head "
                    "차단을 막는다.",
                    row["job_id"],
                    "pre_fdc_result_json" if raw_pre_fdc is None else "correlation_id",
                    reason,
                )
                await self.mark_job_terminal(
                    job_id=row["job_id"], status="FDC_FAILED_FINAL", reason=reason,
                )
                continue
            resumable.append(ResumableRealJob(
                job_id=row["job_id"],
                symbol=row["symbol"],
                source_type=row["source_type"],
                quota_scope=quota_scope,
                decision_cycle_id=row["decision_cycle_id"],
                decision_context_id=row["decision_context_id"],
                correlation_id=correlation_id,
                pre_fdc_result=json.loads(raw_pre_fdc),
                fdc_ready_at=row["fdc_ready_at"],
            ))
        return resumable

    async def cancel_stale_real_jobs(
        self,
        *,
        quota_scope: str,
        reason: str = "process_terminated_carryover_lost",
    ) -> int:
        # 2026-08-28 4차 리뷰 보정 — status='QUEUED'는 더 이상 이
        # 메서드의 대상이 아니다(durable resume 신설로
        # list_resumable_real_jobs()가 안전하게 재개한다). 여기서는
        # 오직 reservation을 실제로 받은 뒤 process crash로 결과가
        # 불명확하게 남은 job(status='RESERVATION_GRANTED')만 다룬다.
        async with TransactionManager() as scan_tx:
            stale_rows = await scan_tx.connection.fetch(
                "SELECT job_id, status FROM trading.fdc_queue_jobs "
                "WHERE quota_scope = $1 AND mode = 'real' "
                "AND status = 'RESERVATION_GRANTED'",
                quota_scope,
            )
            await scan_tx.commit()

        transitioned = 0
        for row in stale_rows:
            job_id = row["job_id"]
            status = row["status"]
            lifecycle = await self.get_latest_real_job_attempt_lifecycle(
                job_id=job_id,
            )
            if lifecycle == AttemptHttpLifecycle.NOT_FOUND:
                logger.error(
                    "cancel_stale_real_jobs: job_id=%s status=%s인데 attempt "
                    "행이 하나도 없다 — try_reserve()가 grant/attempt 행을 "
                    "원자적으로 함께 만드는 계약(§6)이 깨진 데이터 정합성 "
                    "이상. 안전하게 CANCELLED로 처리한다(HTTP를 실제로 "
                    "보낼 수 없었을 것이므로 재시도 금지는 과도한 보수화가 "
                    "아니라 감사 신호다).",
                    job_id, status,
                )
                await self.mark_job_terminal(
                    job_id=job_id, status="CANCELLED", reason=reason,
                )
                transitioned += 1
            elif lifecycle == AttemptHttpLifecycle.NOT_STARTED:
                # HTTP가 나가지 않았다 — 안전하게 취소(재시도는 이
                # job_id로는 더 이상 불가능하므로 향후 새 job 등록으로
                # 대체된다).
                await self.mark_job_terminal(
                    job_id=job_id, status="CANCELLED", reason=reason,
                )
                transitioned += 1
            else:
                # STARTED — HTTP가 실제로 나갔을 수 있어 자동으로
                # 안전하다고 볼 수 없다. complete_fdc_actual_dispatch()의
                # 라이브 crash 판정과 동일한 reason으로 fail-closed
                # 종결한다(중복 호출 위험 회피).
                await self.mark_job_terminal(
                    job_id=job_id, status="FDC_FAILED_FINAL",
                    reason="fdc_only_subprocess_crashed_after_http_start_result_unknown",
                )
                transitioned += 1
        return transitioned

    async def mark_job_terminal(
        self,
        *,
        job_id: uuid.UUID,
        status: str,
        reason: str | None = None,
    ) -> None:
        """job을 종결 상태(``FDC_SUCCEEDED``/``FDC_FAILED_FINAL``/
        ``CANCELLED``)로 전이시킨다 — dispatcher가 attempt 단위
        accounting(``try_reserve()``/``record_attempt_outcome()``)과는
        별개로, job 단위 최종 상태를 명시적으로 기록하기 위한 헬퍼다."""
        async with TransactionManager() as term_tx:
            await term_tx.connection.execute(
                "UPDATE trading.fdc_queue_jobs SET "
                "status = $2, failure_or_cancel_reason = $3, "
                "completed_at = now(), updated_at = now() WHERE job_id = $1",
                job_id,
                status,
                reason,
            )
            await term_tx.commit()

    async def mark_job_status(self, *, job_id: uuid.UUID, status: str) -> None:
        """job의 비종결(non-terminal) 상태 전이(``RETRY_QUEUED`` 등)를
        기록한다 — ``completed_at``은 건드리지 않는다."""
        async with TransactionManager() as status_tx:
            await status_tx.connection.execute(
                "UPDATE trading.fdc_queue_jobs SET "
                "status = $2, updated_at = now() WHERE job_id = $1",
                job_id,
                status,
            )
            await status_tx.commit()

    async def apply_retry_failure(
        self, *, job_id: uuid.UUID, reason: str, will_retry: bool,
    ) -> None:
        """FIFO tail 재등록(2026-08-28 6차 리뷰 보정 — PR #359, 설계
        문서 §5/§9; 2026-08-28 7차 리뷰 보정으로 counter 의미 정정).

        ``reason``은 ``"provider_retryable_failure"``(HTTP가 실제로
        시작된 뒤 429/5xx/timeout) 또는 ``"pre_http_execution_
        failure"``(HTTP 시작 전 subprocess 실패)다.

        **7차 보정** — ``provider_retry_count``/``pre_http_execution_
        failure_count``(및 파생 지표 ``queue_reenqueue_count``)는
        ``will_retry=True``일 때만(=실제로 FIFO tail에 다시 섰을 때만)
        증가한다. 소진(``will_retry=False``)으로 이어지는 마지막 실패는
        "재등록"이 아니라 "종결"이므로 이 counter들을 건드리지 않는다
        — ``queue_reenqueue_count``는 문자 그대로 **"실제 FIFO tail
        재등록 횟수"**를 뜻해야 하며, "이 유형의 실패가 몇 번
        발생했는지"(그건 ``http_attempt_count``/``http_429_count``가
        attempt 단위로 이미 담당한다)와 혼동해서는 안 된다(이전 라운드의
        결함 — will_retry와 무관하게 증가시켰던 것을 이 보정으로
        되돌렸다).

        ``reserved_but_http_not_started_count``는 예외다 — 이것은
        "``outcome='reserved_but_http_not_started'``로 기록된 attempt
        수"라는 attempt 단위 관측값(§9)이므로, 재등록 여부와 무관하게
        이 outcome이 기록될 때마다(=``reason="pre_http_execution_
        failure"``일 때마다) 항상 증가한다.

        ``will_retry=True``일 때만 실제로 FIFO tail로 재등록한다 —
        ``enqueue_sequence``를 시퀀스의 다음 값으로 새로 발급하고
        ``status``를 ``QUEUED``로 되돌린다. 이 job의 ``job_id``(audit
        identity)는 그대로 유지된다 — 새 row를 만들지 않는다. 이후
        ``try_reserve()``가 이 job_id로 다시 호출되면, FIFO admission
        쿼리가 "나보다 작은 enqueue_sequence를 가진 QUEUED job"을 이
        새 sequence 기준으로 재평가하므로, 이 재시도보다 먼저 대기
        중이던 다른 job이 우선권을 갖는다 — 별도의 admission 로직
        변경이 필요 없다(같은 쿼리가 새 sequence 값을 그대로 본다).

        ``will_retry=False``(소진)면 이 메서드는 ``reserved_but_http_
        not_started_count``(``reason``이 pre-HTTP일 때만) 외에는 아무
        것도 갱신하지 않는다 — 호출자가 곧바로 ``mark_job_terminal()``로
        종결시키며, 실제 HTTP 시도/429 관측은 별도로
        ``record_http_attempt_counters()``가 이미 반영했다.
        """
        async with TransactionManager() as retry_tx:
            await retry_tx.connection.execute(
                "UPDATE trading.fdc_queue_jobs SET "
                "provider_retry_count = provider_retry_count + "
                "CASE WHEN $3 AND $2 = 'provider_retryable_failure' THEN 1 ELSE 0 END, "
                "pre_http_execution_failure_count = pre_http_execution_failure_count + "
                "CASE WHEN $3 AND $2 = 'pre_http_execution_failure' THEN 1 ELSE 0 END, "
                "reserved_but_http_not_started_count = reserved_but_http_not_started_count + "
                "CASE WHEN $2 = 'pre_http_execution_failure' THEN 1 ELSE 0 END, "
                "queue_reenqueue_count = queue_reenqueue_count + CASE WHEN $3 THEN 1 ELSE 0 END, "
                "status = CASE WHEN $3 THEN 'QUEUED' ELSE status END, "
                "enqueue_sequence = CASE WHEN $3 THEN "
                "nextval(pg_get_serial_sequence('trading.fdc_queue_jobs', 'enqueue_sequence')) "
                "ELSE enqueue_sequence END, "
                "updated_at = now() "
                "WHERE job_id = $1",
                job_id,
                reason,
                will_retry,
            )
            await retry_tx.commit()

    async def record_http_attempt_counters(
        self, *, job_id: uuid.UUID, http_429_observed: bool = False,
    ) -> None:
        """실제 HTTP 시도가 있었던 attempt마다 job 단위 ``http_attempt_
        count``/``http_429_count``를 갱신한다(2026-08-28 6차 리뷰 보정 —
        설계 문서 §9). ``http_started_at``이 채워진 attempt(성공이든
        provider 레벨 실패든, crash-after-http-start든)마다 정확히
        1회 호출돼야 한다 — HTTP가 시작되지 않은 경우(pre-HTTP 실패)는
        호출하지 않는다."""
        async with TransactionManager() as http_tx:
            await http_tx.connection.execute(
                "UPDATE trading.fdc_queue_jobs SET "
                "http_attempt_count = http_attempt_count + 1, "
                "http_429_count = http_429_count + CASE WHEN $2 THEN 1 ELSE 0 END, "
                "updated_at = now() WHERE job_id = $1",
                job_id,
                http_429_observed,
            )
            await http_tx.commit()

    async def get_attempt_http_lifecycle(
        self, *, reservation_id: uuid.UUID,
    ) -> AttemptHttpLifecycle:
        async with TransactionManager() as read_tx:
            row = await read_tx.connection.fetchrow(
                "SELECT http_started_at FROM trading.fdc_provider_attempts "
                "WHERE attempt_id = $1",
                reservation_id,
            )
            await read_tx.commit()
        if row is None:
            return AttemptHttpLifecycle.NOT_FOUND
        if row["http_started_at"] is None:
            return AttemptHttpLifecycle.NOT_STARTED
        return AttemptHttpLifecycle.STARTED

    async def get_latest_real_job_attempt_lifecycle(
        self, *, job_id: uuid.UUID,
    ) -> AttemptHttpLifecycle:
        async with TransactionManager() as read_tx:
            row = await read_tx.connection.fetchrow(
                "SELECT http_started_at FROM trading.fdc_provider_attempts "
                "WHERE job_id = $1 ORDER BY reserved_at DESC LIMIT 1",
                job_id,
            )
            await read_tx.commit()
        if row is None:
            return AttemptHttpLifecycle.NOT_FOUND
        if row["http_started_at"] is None:
            return AttemptHttpLifecycle.NOT_STARTED
        return AttemptHttpLifecycle.STARTED

    async def try_acquire_provider_global_gate_permit(
        self,
        *,
        gate_scope: str,
        target_rpm: int,
        window_seconds: int,
        caller_lane: str,
        caller_id: str,
        lock_timeout_ms: int = 3000,
    ) -> ProviderGlobalGateResult:
        """PR D(2026-09-03) — ``fdc_provider_global_gate_state``/
        ``fdc_provider_global_gate_grants``만 다룬다. 기존 actual
        coordinator의 ``fdc_quota_state``/``fdc_provider_attempts``/
        ``fdc_queue_jobs``는 전혀 참조하지 않는다(독립 window)."""
        try:
            async with TransactionManager() as gate_tx:
                await gate_tx.connection.execute(
                    f"SET LOCAL lock_timeout = {int(lock_timeout_ms)}"
                )
                anchor_row = await gate_tx.connection.fetchrow(
                    "SELECT gate_scope FROM trading.fdc_provider_global_gate_state "
                    "WHERE gate_scope = $1 FOR UPDATE",
                    gate_scope,
                )
                if anchor_row is None:
                    await gate_tx.rollback()
                    return CoordinatorError(
                        CoordinatorErrorClass.COORDINATOR_TRANSACTION_ERROR,
                        f"anchor row missing for gate_scope={gate_scope!r} "
                        "in trading.fdc_provider_global_gate_state — seed the "
                        "anchor row before use (fail-closed, gate not granted)",
                    )

                window_count = await gate_tx.connection.fetchval(
                    "SELECT count(*) FROM trading.fdc_provider_global_gate_grants "
                    "WHERE gate_scope = $1 "
                    "AND granted_at > now() - make_interval(secs => $2)",
                    gate_scope,
                    window_seconds,
                )

                if window_count >= target_rpm:
                    await gate_tx.commit()
                    return ProviderGlobalGateDenied(
                        gate_scope=gate_scope, window_count=window_count,
                    )

                grant_id = uuid.uuid4()
                await gate_tx.connection.execute(
                    "INSERT INTO trading.fdc_provider_global_gate_grants "
                    "(grant_id, gate_scope, caller_lane, caller_id, granted_at) "
                    "VALUES ($1, $2, $3, $4, now())",
                    grant_id,
                    gate_scope,
                    caller_lane,
                    caller_id,
                )
                await gate_tx.commit()
                return ProviderGlobalGateGranted(
                    grant_id=grant_id,
                    gate_scope=gate_scope,
                    window_count_before_grant=window_count,
                )
        except asyncpg.PostgresError as exc:
            return CoordinatorError(_classify_error(exc), str(exc))
        except (OSError, ConnectionError) as exc:
            return CoordinatorError(_classify_error(exc), str(exc))

    async def record_legacy_http_start_event(
        self,
        *,
        event_id: uuid.UUID,
        provider_scope: str,
        decision_context_id: str | None,
        correlation_id: str | None,
        attempt_no: int,
        observed_at: datetime,
    ) -> None:
        """``fdc_legacy_http_start_events``에 append-only 1행을 INSERT
        한다(2026-09-05, legacy HTTP-start 관측 신설). anchor 잠금이나
        window 판정이 전혀 없는 단순 감사 기록이다 — 호출자가 실패를
        어떻게 처리할지(fail-open) 결정한다, 이 메서드는 예외를 그대로
        전파할 뿐이다."""
        async with TransactionManager() as event_tx:
            await event_tx.connection.execute(
                "INSERT INTO trading.fdc_legacy_http_start_events "
                "(event_id, provider_scope, decision_context_id, "
                "correlation_id, attempt_no, observed_at) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                event_id,
                provider_scope,
                decision_context_id,
                correlation_id,
                attempt_no,
                observed_at,
            )
            await event_tx.commit()
