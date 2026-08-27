"""수동 FDC/AR provider 분석 스크립트 공용 헬퍼(2026-08-27 PR A 신설).

``scripts/ar_fdc_provider_validation.py``와
``scripts/ar_fdc_output_measurement.py``의 live provider 호출 경로가
공유하는 두 가지 책임을 담당한다.

1. **운영 시간 fail-closed 차단**: 새 문자열 비교나 ad-hoc 시간 계산을
   만들지 않고, 기존 검증된 ``market_session.py::create_session_provider()``
   경로를 그대로 재사용한다. 이 코드베이스는 2026-07-10에 163 WebSocket
   결합(``CombinedSessionProvider``)을 제거해, 현재 운영 경로는 076
   REST(``KisHolidayProvider``) 또는 주말 heuristic(``FallbackSessionProvider``)
   만 제공한다 — 즉 "지금이 정규장 개장 시각대인가"(분 단위)가 아니라
   "오늘이 거래일인가"(일 단위)만 판단할 수 있다. 이 헬퍼는 안전을
   우선해 **거래일이면 하루 종일** 수동 live 호출을 차단한다(보수적
   fail-closed — 실제 정규장 시간대만 좁혀서 허용하지 않는다). 이는
   설계 문서 §11이 의도한 "운영 시간 판정"의 근사이며, 분 단위 장운영
   phase가 필요하면 별도 설계/163 WS 재도입이 선행돼야 한다는 한계를
   명시적으로 남긴다.
2. **비운영 시간 공용 quota coordinator 경로**: HTTP 시도마다 새
   ``FdcQuotaCoordinator.try_reserve()``를 얻어(§7 "HTTP 시도마다
   reservation") ``LiveGeminiProviderClient.generate_structured_once()``
   를 호출하고, 성공/실패/429/HTTP 시작 전 실패를
   ``coordinator.record_attempt_outcome()``으로 ``fdc_provider_attempts``
   에 감사 가능하게 남긴다. reservation 거부·coordinator 오류 시 HTTP를
   전혀 보내지 않는다. ``fdc_queue_jobs`` row는 만들지 않는다
   (``job_id=None``, ``manual_run_id``만 사용 — 설계 문서 §11 A안).
"""

from __future__ import annotations

import socket
import uuid
from datetime import date, datetime, timezone

import httpx

from agent_trading.repositories.contracts import (
    CoordinatorError,
    ReservationDenied,
    ReservationGrant,
)
from agent_trading.services.ai_agents.base import RawProviderResponse
from agent_trading.services.ai_agents.provider_client import (
    LiveGeminiProviderClient,
    PermitCallback,
    PermitResult,
    _is_retryable_http_status,
)
from agent_trading.services.fdc_quota_coordinator import FdcQuotaCoordinator
from agent_trading.services.market_session import create_session_provider

__all__ = [
    "MarketHoursBlockedError",
    "QuotaUnavailableError",
    "assert_not_market_hours",
    "build_manual_run_id",
    "call_with_coordinator",
    "finalize_permit_adapter_outcomes",
    "make_coordinator_permit_adapter",
]


class MarketHoursBlockedError(Exception):
    """운영 시간(거래일)에 수동 live provider 호출을 시도했다 — 기술적
    fail-closed. HTTP 요청은 이 예외가 발생하기 전에 전혀 나가지 않는다.
    """


class QuotaUnavailableError(Exception):
    """quota reservation이 거부되거나 coordinator 자체가 오류를 반환했다
    — 두 경우 모두 HTTP 요청을 절대 보내지 않는다."""


async def assert_not_market_hours(*, script_name: str) -> None:
    """오늘이 거래일이면 ``MarketHoursBlockedError``를 던진다.

    ``create_session_provider()``(기존 검증된 076/fallback 경로, 신규
    로직 없음)만 사용한다. 이 함수가 정상 반환하면(예외 없음) 그날은
    거래일이 아니라는 뜻이며, 그 경우에만 호출자가 live provider 호출을
    진행해야 한다.
    """
    provider = await create_session_provider()
    try:
        info = await provider.get_session_info(date.today())
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            maybe_awaitable = close()
            if hasattr(maybe_awaitable, "__await__"):
                await maybe_awaitable

    if info.is_trading_day:
        raise MarketHoursBlockedError(
            f"{script_name}: 오늘({date.today().isoformat()})은 거래일이다"
            f"(source={info.source!r}, reason={info.reason!r}) — 수동 live "
            "provider 호출은 운영 시간(거래일)에 기술적으로 차단된다. "
            "비운영 시간(주말/공휴일)에 다시 실행하라."
        )


def build_manual_run_id(*, script_name: str) -> str:
    """스크립트별로 구분되는 감사 가능한 ``manual_run_id``를 만든다.

    형식: ``<script_name>:<UTC ISO-8601>:<8자리 랜덤 hex>`` — 같은
    스크립트를 짧은 간격으로 재실행해도(예: 재시도) 충돌하지 않는다.
    """
    now = datetime.now(timezone.utc).isoformat()
    return f"{script_name}:{now}:{uuid.uuid4().hex[:8]}"


def _is_retryable_exception(exc: Exception) -> bool:
    """provider_client.py의 기존 재시도 판정 로직을 그대로 재사용한다
    (429/5xx/네트워크/timeout만 retryable, 그 외는 즉시 최종 실패)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return _is_retryable_http_status(exc.response.status_code)
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException, socket.gaierror))


async def call_with_coordinator(
    *,
    coordinator: FdcQuotaCoordinator,
    client: LiveGeminiProviderClient,
    caller_id: str,
    manual_run_id: str,
    model_id: str,
    system_prompt: str,
    user_prompt: str,
    response_format: type,
    temperature: float = 0.0,
    seed: int | None = None,
    max_attempts: int = 3,
) -> RawProviderResponse:
    """HTTP 시도마다 새 reservation을 얻어 one-shot HTTP를 실행한다.

    - reservation 거부(``ReservationDenied``) 또는 coordinator 오류
      (``CoordinatorError``)면 ``QuotaUnavailableError``를 던지고 HTTP는
      전혀 보내지 않는다.
    - 승인되면 ``LiveGeminiProviderClient.generate_structured_once()``를
      **정확히 1회** 호출하고, 결과(성공/실패)를
      ``coordinator.record_attempt_outcome()``으로 즉시 기록한다.
    - retryable 실패(429/5xx/네트워크/timeout)이고 시도 횟수가 남았으면
      **새 reservation**을 다시 얻어 재시도한다(같은 grant를 재사용하지
      않는다 — one-shot은 grant를 소비하면 끝이다).
    - non-retryable 실패는 즉시 원본 예외를 던진다.
    """
    last_exc: Exception | None = None
    for attempt_no in range(1, max_attempts + 1):
        result = await coordinator.try_reserve(
            job_id=None,
            caller_id=caller_id,
            mode="real",
            manual_run_id=manual_run_id,
            attempt_no=attempt_no,
        )
        if isinstance(result, ReservationDenied):
            raise QuotaUnavailableError(
                f"reservation denied: window_count={result.window_count} "
                f"quota_scope={result.quota_scope!r} manual_run_id={manual_run_id!r}"
            )
        if isinstance(result, CoordinatorError):
            raise QuotaUnavailableError(
                f"coordinator error: {result.error_class.value} {result.detail} "
                f"manual_run_id={manual_run_id!r}"
            )

        grant: ReservationGrant = result
        started_at = datetime.now(timezone.utc)
        try:
            response = await client.generate_structured_once(
                grant,
                expected_job_id=None,
                expected_attempt_no=attempt_no,
                model_id=model_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format=response_format,
                temperature=temperature,
                seed=seed,
            )
        except Exception as exc:  # noqa: BLE001 — 아래에서 재시도 여부만 분류
            completed_at = datetime.now(timezone.utc)
            retryable = _is_retryable_exception(exc)
            is_429 = (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code == 429
            )
            await coordinator.record_attempt_outcome(
                reservation_id=grant.reservation_id,
                outcome="http_failed_retryable" if retryable else "http_failed_final",
                http_status=(
                    exc.response.status_code
                    if isinstance(exc, httpx.HTTPStatusError) else None
                ),
                error_class=type(exc).__name__,
                http_429_observed=is_429,
                http_started_at=started_at,
                completed_at=completed_at,
            )
            last_exc = exc
            if retryable and attempt_no < max_attempts:
                continue
            raise
        else:
            completed_at = datetime.now(timezone.utc)
            await coordinator.record_attempt_outcome(
                reservation_id=grant.reservation_id,
                outcome="http_succeeded",
                http_started_at=started_at,
                completed_at=completed_at,
            )
            return response

    assert last_exc is not None  # pragma: no cover — 루프는 항상 return/raise로 끝난다
    raise last_exc


def make_coordinator_permit_adapter(
    *,
    coordinator: FdcQuotaCoordinator,
    caller_id: str,
    manual_run_id: str,
) -> tuple[PermitCallback, list[uuid.UUID]]:
    """``agent.run()``처럼 이미 완성된 고수준 인터페이스(내부적으로
    기존 ``generate_structured()``의 retry 루프를 그대로 쓰는 경로)를
    바꾸지 않고도, 그 retry 루프의 기존 ``acquire_permit`` 훅에 꽂아
    HTTP 시도마다 공용 quota reservation을 받게 하는 어댑터를 만든다
    (``scripts/ar_fdc_output_measurement.py``처럼 ``FinalDecisionComposerAgent``
    를 직접 생성해 ``agent.run(request)``를 호출하는 경로 전용 — 직접
    ``generate_structured_once()``를 호출하는 ``call_with_coordinator()``
    와는 다른 통합 지점이다).

    반환되는 리스트에는 실제로 승인된 reservation들의 ``reservation_id``
    가 시도 순서대로 쌓인다 — 이 어댑터 자체는 permit 콜백(HTTP 시작
    **전**에만 호출됨)이라 HTTP 결과를 알 수 없으므로, 호출자가
    ``agent.run()`` 완료 후 ``finalize_permit_adapter_outcomes()``로
    이 리스트를 outcome 기록에 넘겨야 한다.
    """
    attempt_no_counter = [0]
    granted_reservations: list[uuid.UUID] = []

    async def _acquire_permit() -> PermitResult:
        attempt_no_counter[0] += 1
        result = await coordinator.try_reserve(
            job_id=None,
            caller_id=caller_id,
            mode="real",
            manual_run_id=manual_run_id,
            attempt_no=attempt_no_counter[0],
        )
        if isinstance(result, ReservationDenied):
            return PermitResult(granted=False, denial_reason="quota_denied")
        if isinstance(result, CoordinatorError):
            return PermitResult(granted=False, denial_reason="coordinator_error")
        granted_reservations.append(result.reservation_id)
        return PermitResult(granted=True)

    return _acquire_permit, granted_reservations


async def finalize_permit_adapter_outcomes(
    *,
    coordinator: FdcQuotaCoordinator,
    reservation_ids: list[uuid.UUID],
    succeeded: bool,
) -> None:
    """``make_coordinator_permit_adapter()``가 쌓아둔 reservation들의
    최종 outcome을 기록한다.

    마지막 reservation만 이번 ``agent.run()`` 호출의 최종 결과(성공/
    실패)를 반영한다. 그 이전(재시도로 버려진) reservation들은 전부
    ``http_failed_retryable``로 기록한다 — 기존 ``generate_structured()``
    의 retry 루프가 실제로 그렇게 처리했기 때문이다(마지막 시도 전까지는
    전부 retryable 실패였으니 다음 attempt로 넘어갔다).
    """
    if not reservation_ids:
        return
    now = datetime.now(timezone.utc)
    for reservation_id in reservation_ids[:-1]:
        await coordinator.record_attempt_outcome(
            reservation_id=reservation_id,
            outcome="http_failed_retryable",
            completed_at=now,
        )
    last = reservation_ids[-1]
    await coordinator.record_attempt_outcome(
        reservation_id=last,
        outcome="http_succeeded" if succeeded else "http_failed_final",
        completed_at=now,
    )
