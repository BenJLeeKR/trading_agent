"""FDC cycle-scoped batch queue — Gemini 공용 13 RPM quota coordinator.

설계 근거: docs/40_action_plans/fdc_cycle_scoped_batch_queue_gemini_
shared_13rpm_quota_design_2026-08-25.md §6·§9.

Phase 1(lifecycle shadow) 범위
------------------------------
이 서비스는 두 가지 서로 다른 API를 제공하며, 실제 DB 접근은 전부
``repositories.contracts.FdcQuotaRepository``(주입된 repository)에
위임한다 — 이 파일 자체는 asyncpg/DB transaction을 직접 다루지 않는다
(architecture 계약: services 계층은 repositories 계층을 거쳐서만 DB에
접근한다).

- ``register_shadow_job_and_judge()``: 실제로 운영 런타임에서 호출되는
  **관측 전용** 경로. FDC-ready로 확정된 건을 같은 quota_scope의
  ``mode='shadow'`` 가상 FIFO 13 RPM 큐에 등록하고, "같은 cycle 내
  앞선 shadow FDC-ready job까지 포함한 FIFO 큐에서 지금 승인
  가능한가"를 판단한다 — ``mode='real'`` 행은 전혀 보지 않으므로
  실제 quota를 절대 소비하지 않는다.
- ``try_reserve()``: §6의 atomic reservation transaction 계약을 그대로
  구현한 **실제 quota 소비 경로**. Phase 1에서는 단위/통합 테스트로만
  검증되며, 실제 FDC 실행 경로(cycle-scoped dispatcher)에는 아직 연결
  되지 않는다 — 그 연결은 후속 PR(dispatcher 전환)의 범위다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from agent_trading.repositories.contracts import (
    CoordinatorError,
    CoordinatorErrorClass,
    FdcQuotaRepository,
    ReservationDenied,
    ReservationGrant,
    ReservationResult,
    ShadowJudgement,
    ShadowJudgementResult,
)

DEFAULT_QUOTA_SCOPE = "gemini:shared-operational"
DEFAULT_LOCK_TIMEOUT_MS = 3000

__all__ = [
    "CoordinatorError",
    "CoordinatorErrorClass",
    "DEFAULT_LOCK_TIMEOUT_MS",
    "DEFAULT_QUOTA_SCOPE",
    "FdcQuotaCoordinator",
    "ReservationDenied",
    "ReservationGrant",
    "ReservationResult",
    "ShadowJudgement",
    "ShadowJudgementResult",
]


class FdcQuotaCoordinator:
    """PostgreSQL singleton anchor row 기반 공용 13 RPM quota coordinator.

    이 클래스 자체는 설정값(target_rpm/window_seconds/quota_scope)만
    들고 있고, 실제 DB 작업은 ``repo``(주입된 ``FdcQuotaRepository``)에
    위임한다.
    """

    def __init__(
        self,
        *,
        repo: FdcQuotaRepository,
        target_rpm: int,
        window_seconds: int = 60,
        quota_scope: str = DEFAULT_QUOTA_SCOPE,
        lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
        declared_rpm_limit: int | None = None,
    ) -> None:
        if target_rpm <= 0:
            raise ValueError("target_rpm must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if declared_rpm_limit is not None and target_rpm >= declared_rpm_limit:
            raise ValueError(
                f"target_rpm({target_rpm}) must be strictly below "
                f"declared_rpm_limit({declared_rpm_limit})"
            )
        self._repo = repo
        self._target_rpm = target_rpm
        self._window_seconds = window_seconds
        self._quota_scope = quota_scope
        self._lock_timeout_ms = lock_timeout_ms

    # ------------------------------------------------------------------
    # 실제 quota 소비 경로 — Phase 1에서는 단위/통합 테스트 전용, 런타임 미연결
    # ------------------------------------------------------------------

    async def try_reserve(
        self,
        *,
        job_id: uuid.UUID | None,
        caller_id: str,
        mode: str = "real",
        manual_run_id: str | None = None,
        attempt_no: int = 1,
    ) -> ReservationResult:
        """§6의 atomic reservation transaction 계약을 그대로 위임한다."""
        return await self._repo.try_reserve(
            quota_scope=self._quota_scope,
            target_rpm=self._target_rpm,
            window_seconds=self._window_seconds,
            job_id=job_id,
            caller_id=caller_id,
            mode=mode,
            manual_run_id=manual_run_id,
            attempt_no=attempt_no,
            lock_timeout_ms=self._lock_timeout_ms,
        )

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
        """``try_reserve()``가 발급한 reservation의 실제 HTTP 실행 결과를
        기록한다(PR A 신설). 새 reservation을 요청하지 않는다 — 이미
        승인된 attempt 행의 상태만 갱신한다."""
        await self._repo.record_attempt_outcome(
            reservation_id=reservation_id,
            outcome=outcome,
            http_status=http_status,
            error_class=error_class,
            http_429_observed=http_429_observed,
            http_started_at=http_started_at,
            completed_at=completed_at,
        )

    # ------------------------------------------------------------------
    # shadow 관측 경로 — Phase 1에서 실제로 호출되는 유일한 경로
    # ------------------------------------------------------------------

    async def register_shadow_job_and_judge(
        self,
        *,
        decision_cycle_id: str | None,
        decision_context_id: uuid.UUID | None,
        symbol: str,
        source_type: str,
        fdc_ready_at: datetime,
        caller_id: str = "ops-scheduler",
    ) -> ShadowJudgementResult:
        """FDC-ready job을 shadow 가상 FIFO 13 RPM 큐에 등록하고, "같은
        cycle 내 앞선 shadow FDC-ready job까지 포함한 FIFO 큐에서 지금
        승인 가능한가"를 원자적으로 판단한다.

        ``mode='real'`` 행은 전혀 보지 않으므로 기존 strict limiter/
        실제 quota에 전혀 영향을 주지 않는다. 등록과 판단이 하나의
        원자적 트랜잭션이라 동시 등록 시에도 새치기가 없다.
        """
        return await self._repo.register_shadow_job_and_judge(
            quota_scope=self._quota_scope,
            target_rpm=self._target_rpm,
            window_seconds=self._window_seconds,
            decision_cycle_id=decision_cycle_id,
            decision_context_id=decision_context_id,
            symbol=symbol,
            source_type=source_type,
            fdc_ready_at=fdc_ready_at,
            caller_id=caller_id,
            lock_timeout_ms=self._lock_timeout_ms,
        )
