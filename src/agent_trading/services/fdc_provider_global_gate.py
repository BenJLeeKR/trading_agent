"""Gemini FDC provider 전체(legacy `mode="full"` + held_position/BUY
actual-dispatch) 물리적 HTTP-start 상한을 강제하는 durable global gate
(PR D, 2026-09-03).

설계 근거: docs/40_action_plans/fdc_pr_d_provider_global_quota_design_
2026-09-02.md (대안 C — 별도 global HTTP-start gate 신설, §4.2 legacy
limiter → global gate 순서 확정).

이 모듈은 기존 ``FdcQuotaCoordinator``(held_position/BUY actual-dispatch
자신의 FIFO/window 판정 — "누가 다음 실행 기회를 가질 자격이 있는가")와
완전히 독립적이다. 이 gate는 "지금 물리적으로 HTTP를 내보내도 되는가"만
판단하며, 별도 DB 테이블(``fdc_provider_global_gate_state``/
``fdc_provider_global_gate_grants``)만 다룬다 — actual coordinator의
``fdc_quota_state``/``fdc_provider_attempts``/``fdc_queue_jobs``는 전혀
참조하지 않는다.
"""

from __future__ import annotations

from agent_trading.repositories.contracts import (
    FdcQuotaRepository,
    ProviderGlobalGateDenied,
    ProviderGlobalGateGranted,
)
from agent_trading.services.ai_agents.provider_client import PermitResult

DEFAULT_GATE_SCOPE = "gemini:provider-global"

# 2026-09-03 Finding 1 보정 — global gate가 강제해야 하는 "legacy+actual
# 합산 60초 sliding window 최대 13건" 계약 자체를 이 gate가 스스로
# 지키도록 하는 최소/최대 불변식. FDC_PROVIDER_TARGET_RPM/FDC_PROVIDER_
# RATE_WINDOW_SECONDS는 원래 held_position actual coordinator만을
# 염두에 두고 만들어진 설정값이라 최소값만 검사했고, 13 초과나 60초가
# 아닌 window로도 얼마든지 설정될 수 있었다 — global gate가 활성화된
# 상태에서 이런 설정이 들어오면 "13 RPM을 넘지 않는다"는 계약 자체가
# 깨진다. 13보다 낮은 target은 더 보수적이므로(gate가 더 일찍 거부할
# 뿐, 13 RPM 상한을 절대 넘지 않는다는 계약은 그대로 유지되므로) 허용한다.
_MIN_TARGET_RPM = 1
_MAX_TARGET_RPM = 13
_REQUIRED_WINDOW_SECONDS = 60


class FdcProviderGlobalGate:
    """``FdcQuotaRepository.try_acquire_provider_global_gate_permit()``를
    감싸는 얇은 서비스 계층 — legacy/actual 양쪽 호출부가 lane 이름만
    다르게 넘겨 동일한 gate를 통과시킨다.

    반환값은 기존 ``PermitResult``(legacy limiter가 이미 쓰는 모양)로
    통일한다 — 호출부가 gate 거부를 기존 ``PermitDeniedError`` 경로로
    그대로 흘려보낼 수 있게 하기 위해서다(새 예외 타입을 만들지 않는다).
    """

    __slots__ = ("_repo", "_target_rpm", "_window_seconds", "_gate_scope")

    def __init__(
        self,
        *,
        repo: FdcQuotaRepository,
        target_rpm: int,
        window_seconds: int,
        gate_scope: str = DEFAULT_GATE_SCOPE,
    ) -> None:
        self._repo = repo
        self._target_rpm = target_rpm
        self._window_seconds = window_seconds
        self._gate_scope = gate_scope

    async def acquire(self, *, caller_lane: str, caller_id: str) -> PermitResult:
        """gate를 1회 통과 시도한다 — 내부적으로 재시도/대기 루프를 갖지
        않는 단일 원자적 판단이다(legacy/actual 양쪽 모두 이미 자신의
        상위 재시도 루프를 갖고 있으므로, gate 자체가 또 다른 대기
        루프를 추가하면 예산 계산이 이중으로 복잡해진다 — §4.2 설계
        문서가 확정한 단순화).

        ``granted=False``일 때 ``denial_reason``은 다음 둘 중 하나다.

        - ``"global_gate_timeout"``: window 포화(정상 거부, DB 오류
          아님) — ``ProviderGlobalGateDenied``.
        - ``"global_gate_error"``: gate 자체의 DB/lock/connection
          오류(fail-closed — grant하지 않는다) — ``CoordinatorError``.
          2026-09-03 보정: ``target_rpm``/``window_seconds`` 설정값
          자체가 "legacy+actual 합산 13 RPM 상한"을 보장할 수 없는
          범위(``target_rpm`` 1~13 밖, ``window_seconds`` != 60)여도
          같은 marker로 fail-closed한다 — repository/DB 호출 자체를
          하지 않는다(설정 오류를 DB에 떠넘기지 않는다).
        """
        if not (_MIN_TARGET_RPM <= self._target_rpm <= _MAX_TARGET_RPM):
            return PermitResult(
                granted=False, waited_seconds=0.0, denial_reason="global_gate_error",
            )
        if self._window_seconds != _REQUIRED_WINDOW_SECONDS:
            return PermitResult(
                granted=False, waited_seconds=0.0, denial_reason="global_gate_error",
            )

        result = await self._repo.try_acquire_provider_global_gate_permit(
            gate_scope=self._gate_scope,
            target_rpm=self._target_rpm,
            window_seconds=self._window_seconds,
            caller_lane=caller_lane,
            caller_id=caller_id,
        )
        if isinstance(result, ProviderGlobalGateGranted):
            return PermitResult(granted=True, waited_seconds=0.0, denial_reason=None)
        if isinstance(result, ProviderGlobalGateDenied):
            return PermitResult(
                granted=False, waited_seconds=0.0, denial_reason="global_gate_timeout",
            )
        # CoordinatorError — gate 자체가 판정 불능이었다(fail-closed).
        return PermitResult(
            granted=False, waited_seconds=0.0, denial_reason="global_gate_error",
        )
