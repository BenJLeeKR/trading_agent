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
from collections.abc import Awaitable, Callable
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
MANUAL_CALLER_ID_PREFIX = "manual:"

# 2026-08-27 3차 리뷰 보정 신설: 수동(manual:*) reservation 요청을
# 허용할지 판단하는 좁은 정책 콜백의 얕은 모양. 이 모듈은 실제 정책
# 구현(예: 거래일 판정, KIS/session provider)을 전혀 모른다 —
# ``PermitCallback``/``HttpStartCallback``(provider_client.py)과 동일한
# 계층 결합 최소화 원칙. ``True``를 반환하면 이번 순간 manual 호출이
# 허용된다는 뜻이다(예: 오늘이 거래일이 아님).
ManualCallPolicy = Callable[[], Awaitable[bool]]

__all__ = [
    "CoordinatorError",
    "CoordinatorErrorClass",
    "DEFAULT_LOCK_TIMEOUT_MS",
    "DEFAULT_QUOTA_SCOPE",
    "MANUAL_CALLER_ID_PREFIX",
    "FdcQuotaCoordinator",
    "ManualCallPolicy",
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
        manual_call_policy: ManualCallPolicy | None = None,
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
        # 2026-08-27 3차 리뷰 보정: caller_id가 "manual:"로 시작하는
        # reservation 요청을 허용할지 판단하는 좁은 정책. None이면
        # fail-closed로 무조건 거부한다(§11 계약 — 절차적 금지 문구만
        # 으로 충분하다고 서술하지 않는다).
        self._manual_call_policy = manual_call_policy

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
        """§6의 atomic reservation transaction 계약을 그대로 위임한다.

        2026-08-27 3차 리뷰 보정: ``caller_id``가 ``"manual:"``로
        시작하면(§11 "수동 provider 호출") repository에 위임하기
        **전에** ``manual_call_policy``를 먼저 확인한다 — 정책이
        주입돼 있지 않거나 정책이 거부하면 ``CoordinatorError``를
        즉시 반환하고 repository는 전혀 호출하지 않는다(quota window도
        건드리지 않는다). ``manual:``이 아닌 caller(예: 운영
        ``ops-scheduler``)는 이 검사를 완전히 우회한다 — 영향을 받지
        않는다.
        """
        if caller_id.startswith(MANUAL_CALLER_ID_PREFIX):
            if self._manual_call_policy is None:
                return CoordinatorError(
                    CoordinatorErrorClass.MANUAL_CALL_POLICY_REJECTED,
                    f"manual caller_id={caller_id!r} rejected: no "
                    "manual_call_policy was injected into FdcQuotaCoordinator "
                    "(fail-closed default — §11 계약).",
                )
            allowed = await self._manual_call_policy()
            if not allowed:
                return CoordinatorError(
                    CoordinatorErrorClass.MANUAL_CALL_POLICY_REJECTED,
                    f"manual caller_id={caller_id!r} rejected by "
                    "manual_call_policy (e.g. 운영 시간/거래일 fail-closed 차단).",
                )

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
