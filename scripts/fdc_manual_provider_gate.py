"""수동 FDC/AR provider 분석 스크립트 공용 헬퍼(2026-08-27 PR A 신설).

``scripts/ar_fdc_provider_validation.py``와
``scripts/ar_fdc_output_measurement.py``의 live provider 호출 경로가
공유하는 두 가지 책임을 담당한다.

1. **운영 시간 fail-closed 차단(2단계, 2026-08-27 3차 리뷰 보정)**: 새
   문자열 비교나 ad-hoc 시간 계산을 만들지 않고, 기존 검증된
   ``market_session.py::create_session_provider()`` 경로를 그대로
   재사용한다. 이 코드베이스는 2026-07-10에 163 WebSocket 결합
   (``CombinedSessionProvider``)을 제거해, 현재 운영 경로는 076 REST
   (``KisHolidayProvider``) 또는 주말 heuristic(``FallbackSessionProvider``)
   만 제공한다 — 즉 "지금이 정규장 개장 시각대인가"(분 단위)가 아니라
   "오늘이 거래일인가"(일 단위)만 판단할 수 있다. 안전을 우선해
   **거래일이면 하루 종일** 수동 live 호출을 차단한다(보수적
   fail-closed — 실제 정규장 시간대만 좁혀서 허용하지 않는다). 이는
   설계 문서 §11이 의도한 "운영 시간 판정"의 근사이며, 분 단위 장운영
   phase가 필요하면 별도 설계/163 WS 재도입이 선행돼야 한다는 한계를
   명시적으로 남긴다.
   - **1단계(CLI 사전 검사, 기존)**: ``assert_not_market_hours()``를
     각 스크립트 ``main()`` 시작 부분에서 직접 호출한다 — DB pool
     초기화·HTTP client 준비보다도 먼저 실행되는 빠른 실패 경로다.
   - **2단계(coordinator 중앙 경계, 신설)**: ``build_manual_call_policy()``
     가 위 검사를 ``FdcQuotaCoordinator(manual_call_policy=...)``가
     요구하는 콜백 모양으로 감싸 coordinator에 주입한다.
     ``FdcQuotaCoordinator.try_reserve()``는 ``caller_id``가
     ``"manual:"``로 시작하면 이 정책을 **repository에 위임하기 전에**
     직접 확인한다(``src/agent_trading/services/fdc_quota_coordinator.py``)
     — 정책이 주입돼 있지 않거나 정책이 거부하면 `CoordinatorError`를
     반환하고 quota window를 전혀 건드리지 않는다. 이 경계는 `src`
     계층에 있으므로, CLI 사전 검사를 우회하는 다른 호출자가 같은
     coordinator 인스턴스를 직접 쓰더라도 여전히 강제된다(§11 계약의
     실제 구현 — 1단계는 사용자 편의를 위한 빠른 실패일 뿐, 진짜
     강제 경계는 2단계다).
2. **비운영 시간 공용 quota coordinator 경로 — FDC 전용**: HTTP 시도마다
   새 ``FdcQuotaCoordinator.try_reserve()``를 얻어(§7 "HTTP 시도마다
   reservation") ``LiveGeminiProviderClient.generate_structured_once()``
   를 호출하고, 성공/실패/429/HTTP 시작 전 실패를
   ``coordinator.record_attempt_outcome()``으로 ``fdc_provider_attempts``
   에 감사 가능하게 남긴다. reservation 거부·coordinator 오류 시 HTTP를
   전혀 보내지 않는다. ``fdc_queue_jobs`` row는 만들지 않는다
   (``job_id=None``, ``manual_run_id``만 사용 — 설계 문서 §11 A안).

**AR/FDC quota 적용 범위(2026-08-27 리뷰 보정으로 확정)**: 이 공용
coordinator는 **FDC live provider 호출에만** 적용한다 — AR live
provider 호출은 production에서도 이 quota의 대상이 아니다
(``AIRiskAgent.run()``이 ``acquire_permit``을 전혀 쓰지 않음, §1
배경 문서가 "FDC provider(Gemini) 호출"만 명시). 이 모듈의 함수는
전부 FDC 전용이며, AR 호출에는 절대 쓰지 않는다 — AR은 일반
``OpenAICompatibleClient``(coordinator 없음)를 그대로 쓴다.

**HTTP 실행 경로 두 가지**:
- ``call_with_coordinator()``: `generate_structured_once()`를 직접
  호출하는 명시적 attempt loop(``ar_fdc_provider_validation.py``의
  FDC 호출이 직접 사용).
- ``CoordinatedFdcProviderClient``: 위 함수를 감싸 ``AIProviderClient``
  Protocol을 만족시키는 wrapper — ``FinalDecisionComposerAgent.run()``
  같은 기존 고수준 인터페이스를 바꾸지 않고 재사용해야 할 때
  (``ar_fdc_output_measurement.py``의 FDC 호출이 사용) 쓴다. 둘 다
  내부적으로 동일한 attempt-loop 구현 하나만 쓰므로 lifecycle 기록
  로직이 중복되지 않는다.
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
    _is_retryable_http_status,
)
from agent_trading.services.fdc_quota_coordinator import (
    FdcQuotaCoordinator,
    ManualCallPolicy,
)
from agent_trading.services.market_session import create_session_provider

__all__ = [
    "CoordinatedFdcProviderClient",
    "MarketHoursBlockedError",
    "QuotaUnavailableError",
    "assert_not_market_hours",
    "build_manual_call_policy",
    "build_manual_run_id",
    "call_with_coordinator",
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


def build_manual_call_policy(*, script_name: str) -> ManualCallPolicy:
    """``FdcQuotaCoordinator(manual_call_policy=...)``에 주입할 좁은 정책
    콜백을 만든다(2026-08-27 3차 리뷰 보정 신설).

    ``assert_not_market_hours()``(예외 기반)를 coordinator가 요구하는
    ``Callable[[], Awaitable[bool]]`` 모양으로 감싼다 — 거래일이면
    ``False``(거부), 아니면 ``True``(허용)를 반환한다. **이 정책은
    이 스크립트 자체의 CLI 사전 검사와 별개로, coordinator
    (``src`` 계층)가 ``try_reserve()`` 안에서 직접 강제하는 중앙
    fail-closed 경계에 연결된다** — CLI 사전 검사가 우회되거나 다른
    코드가 이 coordinator 인스턴스를 직접 써도 이 경계는 유지된다.
    """
    async def _policy() -> bool:
        try:
            await assert_not_market_hours(script_name=script_name)
            return True
        except MarketHoursBlockedError:
            return False

    return _policy


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
      **정확히 1회** 호출한다.
    - retryable 실패(429/5xx/네트워크/timeout)이고 시도 횟수가 남았으면
      **새 reservation**을 다시 얻어 재시도한다(같은 grant를 재사용하지
      않는다 — one-shot은 grant를 소비하면 끝이다).
    - non-retryable 실패는 즉시 원본 예외를 던진다.

    **``http_started_at`` 정밀 기록(2026-08-27 2차 리뷰 보정)**: 이
    함수는 더 이상 ``generate_structured_once()`` 호출 *전*에 타임스탬프를
    직접 잡지 않는다 — 그러면 client 준비/body 조립 단계의 실패까지
    "HTTP가 시작됐다"고 잘못 기록할 수 있었다. 대신 ``on_http_start``
    콜백을 넘겨, ``provider_client.py``가 실제 ``client.post()`` 바로
    직전에만 이를 호출하게 한다:

    - 콜백이 성공적으로 실행되면(=실제 HTTP가 시작된 것으로 간주)
      ``coordinator.record_attempt_outcome(outcome="http_started",
      http_started_at=now())``으로 즉시 기록하고, 이후 결과 기록에서는
      ``http_started_at``을 다시 넘기지 않는다(이미 기록된 값을
      ``COALESCE``가 보존).
    - 콜백의 DB 기록 자체가 실패하면(예: coordinator/DB 오류) 그
      예외가 ``generate_structured_once()``를 통해 그대로 전파되고,
      **``client.post()``는 호출되지 않는다** — "감사 기록 실패를
      무시하고 HTTP를 보내면 안 된다"는 계약을 코드 구조로 강제한다.
    - 콜백이 아예 호출되지 못한 경우(client 준비/body 조립 단계 실패,
      또는 콜백 자체의 DB 기록 실패) — 즉 HTTP가 실제로 시작되지
      못한 경우 — 이 함수는 설계 문서 기존 어휘의
      ``outcome="reserved_but_http_not_started"``로 기록한다(새 상태를
      만들지 않는다). 이 실패도 retryable로 간주해 새 reservation으로
      재시도한다.
    - 콜백이 성공한 뒤(HTTP가 실제로 시작된 뒤) 발생한 실패만 기존
      ``http_failed_retryable``/``http_failed_final`` 규칙을 그대로
      따른다.
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
        http_started = False

        async def _on_http_start(_grant: ReservationGrant = grant) -> None:
            nonlocal http_started
            await coordinator.record_attempt_outcome(
                reservation_id=_grant.reservation_id,
                outcome="http_started",
                http_started_at=datetime.now(timezone.utc),
            )
            http_started = True

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
                on_http_start=_on_http_start,
            )
        except Exception as exc:  # noqa: BLE001 — 아래에서 재시도 여부만 분류
            completed_at = datetime.now(timezone.utc)
            if not http_started:
                # HTTP 시작 전 실패(client 준비/body 조립 실패, 또는
                # on_http_start 콜백 자체의 DB 기록 실패) — client.post()는
                # 호출되지 않았다.
                await coordinator.record_attempt_outcome(
                    reservation_id=grant.reservation_id,
                    outcome="reserved_but_http_not_started",
                    error_class=type(exc).__name__,
                    completed_at=completed_at,
                )
                last_exc = exc
                if attempt_no < max_attempts:
                    continue
                raise
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
                completed_at=completed_at,
            )
            return response

    assert last_exc is not None  # pragma: no cover — 루프는 항상 return/raise로 끝난다
    raise last_exc


class CoordinatedFdcProviderClient:
    """``AIProviderClient`` Protocol(``generate_structured()`` 시그니처)을
    만족하는 wrapper — ``FinalDecisionComposerAgent.run()`` 같은 기존
    고수준 인터페이스를 전혀 바꾸지 않고도, 내부적으로는 매 HTTP 시도를
    ``call_with_coordinator()``(정확한 attempt별 lifecycle 기록)로
    대체한다(2026-08-27 리뷰 보정).

    **이전 설계(``make_coordinator_permit_adapter()`` +
    ``finalize_permit_adapter_outcomes()``, 제거됨)의 결함**: 그 방식은
    reservation ID만 모아뒀다가 ``agent.run()`` 종료 **후** 일괄
    outcome을 기록했다 — 그 결과 실제 HTTP가 성공/실패했는데도
    ``http_started_at``이 채워지지 않거나, 개별 attempt의 HTTP status/
    429 여부/예외 유형을 전혀 알 수 없는 부정확한 감사 행이 생겼다.
    이 wrapper는 그 대신 ``call_with_coordinator()``를 그대로 호출해
    (중복 구현 없음), HTTP 시작 직전 타임스탬프와 attempt별 정확한
    결과를 실시간으로 기록한다 — ``acquire_permit``은 아예 받지 않는다
    (기존 10 RPM strict limiter와 무관, coordinator가 전담).
    """

    def __init__(
        self,
        *,
        coordinator: FdcQuotaCoordinator,
        live_client: LiveGeminiProviderClient,
        caller_id: str,
        manual_run_id: str,
        max_attempts: int = 3,
    ) -> None:
        self._coordinator = coordinator
        self._live_client = live_client
        self._caller_id = caller_id
        self._manual_run_id = manual_run_id
        self._max_attempts = max_attempts

    async def generate_structured(
        self,
        *,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        response_format: type,
        temperature: float = 0.0,
        seed: int | None = None,
        acquire_permit: PermitCallback | None = None,
    ) -> RawProviderResponse:
        if acquire_permit is not None:
            raise ValueError(
                "CoordinatedFdcProviderClient.generate_structured()는 "
                "acquire_permit을 받지 않는다 — 기존 10 RPM strict "
                "limiter 대신 공용 FDC quota coordinator가 매 HTTP 시도를 "
                "전담한다(레거시 permit 어댑터를 실수로 재사용하지 않게 "
                "막는 방어적 가드)."
            )
        return await call_with_coordinator(
            coordinator=self._coordinator,
            client=self._live_client,
            caller_id=self._caller_id,
            manual_run_id=self._manual_run_id,
            model_id=model_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=response_format,
            temperature=temperature,
            seed=seed,
            max_attempts=self._max_attempts,
        )
