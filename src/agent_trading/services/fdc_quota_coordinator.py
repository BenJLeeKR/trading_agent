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

- ``judge_shadow_reservation()`` / ``create_shadow_job()``: 실제로 운영
  런타임에서 호출되는 **관측 전용** 경로. FDC-ready로 확정된 건에 한해
  "13 RPM 공용 quota였다면 이 시점에 승인됐을까"만 판단하고
  ``mode='shadow'``로 기록한다 — 실제 quota를 전혀 소비하지 않는다.
- ``try_reserve()``: §6의 atomic reservation transaction 계약을 그대로
  구현한 **실제 quota 소비 경로**. Phase 1에서는 단위/통합 테스트로만
  검증되며, 실제 FDC 실행 경로(cycle-scoped dispatcher)에는 아직 연결
  되지 않는다 — 그 연결은 후속 PR(dispatcher 전환)의 범위다.
"""

from __future__ import annotations

import uuid

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

    # ------------------------------------------------------------------
    # shadow 관측 경로 — Phase 1에서 실제로 호출되는 유일한 경로
    # ------------------------------------------------------------------

    async def create_shadow_job(
        self,
        *,
        decision_cycle_id: str | None,
        decision_context_id: uuid.UUID | None,
        symbol: str,
        source_type: str,
    ) -> uuid.UUID:
        """FDC-ready로 확정된 건에 대해 ``mode='shadow'`` job row를 만든다.

        기존 런타임 동작에는 영향을 주지 않는 순수 관측 기록이다.
        """
        return await self._repo.create_shadow_job(
            decision_cycle_id=decision_cycle_id,
            decision_context_id=decision_context_id,
            symbol=symbol,
            source_type=source_type,
        )

    async def judge_shadow_reservation(
        self,
        *,
        job_id: uuid.UUID,
        caller_id: str = "ops-scheduler",
    ) -> ShadowJudgementResult:
        """"13 RPM 공용 quota였다면 지금 승인됐을까"를 관측만 한다.

        실제(``mode='real'``) 행만 집계 대상으로 삼으므로, 이 판단은
        기존 strict limiter/실제 quota에 전혀 영향을 주지 않는다.
        """
        return await self._repo.judge_shadow_reservation(
            job_id=job_id,
            quota_scope=self._quota_scope,
            target_rpm=self._target_rpm,
            window_seconds=self._window_seconds,
            caller_id=caller_id,
        )
