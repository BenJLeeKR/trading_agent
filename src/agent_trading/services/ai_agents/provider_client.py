"""HTTP-based OpenAI-compatible provider client.

Implements the ``AIProviderClient`` protocol using raw HTTP calls
(no SDK dependency).  Works with DeepSeek, OpenAI, Ollama, or any
OpenAI-compatible chat completion endpoint.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from agent_trading.services.ai_agents.base import RawProviderResponse

logger = logging.getLogger(__name__)

# Retry configuration for transient network / DNS / rate-limit errors.
MAX_RETRIES = 3
RETRY_DELAY = 1.0  # seconds, base for exponential backoff
MAX_RETRY_DELAY = 5.0  # seconds, backoff 상한


@dataclass(slots=True, frozen=True)
class PermitResult:
    """rate limiter permit 판정 결과(provider 계층 전용 얕은 프로토콜).

    2026-08-21: strict FDC rate limiter 도입 — ``provider_client.py``는
    실제 limiter 구현(``fdc_rate_limiter.py``)을 전혀 모른다. 호출자
    (``final_decision_composer.py``/``run_agent_subprocess.py``)가 이
    모양의 결과만 반환하는 콜백을 주입한다 — 계층 결합을 피하기 위한
    최소 계약이다.

    Attributes
    ----------
    granted:
        ``True``면 실제 HTTP 요청을 진행해도 된다는 뜻. ``False``면
        요청을 보내지 않고 즉시 포기해야 한다(``PermitDeniedError``).
    waited_seconds:
        이 permit을 얻기 위해(또는 포기하기까지) 실제로 대기한 시간.
    denial_reason:
        ``granted=False``일 때만 의미 있음 — ``"queue_timeout"``(대기
        상한 초과) 또는 ``"state_file_error"``(상태 파일 접근 실패).
        호출자(``final_decision_composer._classify_provider_exception()``)
        가 이 문자열을 각각 ``provider_queue_timeout``/
        ``provider_limiter_unavailable`` reason code로 매핑한다.
    """

    granted: bool
    waited_seconds: float = 0.0
    denial_reason: str | None = None


PermitCallback = Callable[[], Awaitable[PermitResult]]


class PermitDeniedError(Exception):
    """rate limiter permit을 얻지 못해 HTTP 요청을 보내지 않고 중단했다.

    이 예외가 발생했다는 것 자체가 "Gemini에 실제 요청을 보내지 않았다"는
    확정적 증거다(``generate_structured()``의 permit 체크는 항상
    ``client.post()`` 호출 **이전**에 일어난다).
    """

    def __init__(self, result: PermitResult) -> None:
        self.result = result
        self.http_attempt_count = 0
        self.http_429_count = 0
        super().__init__(
            f"FDC rate limiter permit denied: {result.denial_reason} "
            f"(waited {result.waited_seconds:.1f}s)"
        )


def _is_retryable_http_status(status_code: int) -> bool:
    """재시도 가능한 HTTP 상태코드를 판정한다."""
    return status_code == 429 or 500 <= status_code < 600


def _parse_retry_after_seconds(response: httpx.Response) -> float | None:
    """``Retry-After`` 헤더를 초 단위 지연으로 해석한다."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return None

    value = raw.strip()
    try:
        delay = float(value)
        return max(0.0, min(delay, MAX_RETRY_DELAY))
    except ValueError:
        pass

    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None

    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)

    delay = (retry_at - datetime.now(timezone.utc)).total_seconds()
    return max(0.0, min(delay, MAX_RETRY_DELAY))


def _compute_retry_delay(attempt: int, error: Exception) -> float:
    """예외 유형과 헤더를 고려해 재시도 지연을 계산한다."""
    if isinstance(error, httpx.HTTPStatusError):
        retry_after = _parse_retry_after_seconds(error.response)
        if retry_after is not None:
            return retry_after
    return min(RETRY_DELAY * (2 ** attempt), MAX_RETRY_DELAY)


def _coerce_nested_json_strings(
    dataclass_type: type, data: dict[str, Any]
) -> dict[str, Any]:
    """Recursively coerce JSON-string fields into dicts for nested dataclass fields.

    Some providers (e.g. DeepSeek) may return nested objects as serialised JSON
    strings instead of proper nested JSON objects.  This function detects such
    fields by inspecting the dataclass type's field annotations and, when a field
    value is a string but the target type is a dataclass (or tuple of dataclasses),
    parses the string with ``json.loads`` and recurses.

    .. note::
        Uses ``typing.get_type_hints()`` to resolve string annotations that arise
        from ``from __future__ import annotations``, which makes all annotations
        strings at runtime.
    """
    import dataclasses
    import typing

    # Resolve string annotations to actual types (handles ``from __future__ import annotations``).
    try:
        resolved_hints = typing.get_type_hints(dataclass_type)
    except Exception:
        resolved_hints = {}

    for f in dataclasses.fields(dataclass_type):
        # Use the resolved type hint if available, otherwise fall back to f.type
        field_type = resolved_hints.get(f.name, f.type)
        origin = getattr(field_type, "__origin__", None)
        value = data.get(f.name)

        if value is None or isinstance(value, (int, float, bool)):
            continue

        # Nested dataclass field — value should be a dict, but may be a JSON string
        if hasattr(field_type, "__dataclass_fields__"):
            if isinstance(value, str):
                try:
                    data[f.name] = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    pass  # leave as-is, will fail at construction
            if isinstance(data.get(f.name), dict):
                coerced = _coerce_nested_json_strings(
                    field_type, data[f.name]
                )
                try:
                    data[f.name] = field_type(**coerced)
                except (TypeError, ValueError):
                    data[f.name] = coerced  # fallback: keep as dict

        # Tuple of dataclasses — value should be a list, but items may be JSON strings
        elif origin is tuple:
            args = getattr(field_type, "__args__", ())
            if args and hasattr(args[0], "__dataclass_fields__") and isinstance(value, list):
                elem_type = args[0]
                coerced: list[dict[str, Any]] = []
                for item in value:
                    if isinstance(item, str):
                        try:
                            item = json.loads(item)
                        except (json.JSONDecodeError, TypeError):
                            pass
                    if isinstance(item, dict):
                        coerced.append(_coerce_nested_json_strings(elem_type, item))
                    else:
                        coerced.append(item)  # type: ignore[arg-type]
                data[f.name] = coerced

    return data


class OpenAICompatibleClient:
    """HTTP-based OpenAI-compatible provider client.

    Implements ``AIProviderClient`` protocol.  Uses ``httpx.AsyncClient``
    to send chat completion requests and parse JSON responses.

    Parameters
    ----------
    api_key
        The API key for authentication (``Authorization: Bearer <key>``).
    base_url
        The base URL of the OpenAI-compatible endpoint
        (e.g. ``"https://api.deepseek.com"``).
    timeout_seconds
        Timeout for HTTP requests in seconds.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model_id: str = "deepseek-chat",
        timeout_seconds: int = 30,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model_id = model_id
        self._timeout = timeout_seconds
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy-initialise the HTTP client with granular timeouts.

        Timeout breakdown
        -----------------
        * ``connect=10.0``  — fail fast on network issues
        * ``read``          — derived from ``self._timeout`` (minus connect/write
                             buffer) so that httpx raises ``ReadTimeout`` before
                             the per-agent ``asyncio.wait_for()`` fires, allowing
                             the agent's ``except Exception`` handler to produce
                             a fallback output instead of hanging the event loop
                             on C-level I/O blocking.
        * ``write=10.0``   — generous write window
        * ``pool=10.0``    — connection pool acquisition timeout
        """
        if self._client is None:
            # Use self._timeout as the total timeout budget; reserve
            # connect+write+pool overhead so read timeout fits within it.
            read_timeout = max(10.0, float(self._timeout) - 30.0)
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=read_timeout,
                    write=10.0,
                    pool=10.0,
                ),
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        return self._client

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
        """Send a chat completion request and return the parsed response.

        Parameters
        ----------
        model_id
            The model identifier (e.g. ``"deepseek-v4-pro"``).
        system_prompt
            The system-level instruction for the model.
        user_prompt
            The user / context prompt.
        response_format
            A dataclass type to parse the JSON response into.
        temperature
            Sampling temperature (default ``0.0``).
        seed
            Optional seed for reproducible sampling.
        acquire_permit
            2026-08-21 추가: 실제 HTTP 요청 **직전**(최초 시도와 매
            재시도 각각)에 호출되는 rate limiter permit 콜백. ``None``
            (기본값)이면 permit 체크 없이 기존 동작과 100% 동일하게
            즉시 요청을 보낸다 — Stub/provider 미설정 경로나 EI/AR처럼
            재시도 대상이 아닌 호출자는 이 인자를 넘기지 않는다. 콜백이
            ``granted=False``를 반환하면 **HTTP 요청을 보내지 않고**
            ``PermitDeniedError``를 즉시 던지며, 남은 재시도는 시도하지
            않는다(대기해도 슬롯이 없다면 다시 시도해도 마찬가지이므로).
            이 모듈은 실제 limiter 구현(``fdc_rate_limiter.py``)을
            전혀 import하지 않는다 — ``PermitResult``라는 얕은 모양만
            안다.

        Returns
        -------
        RawProviderResponse
            Wrapper containing both the parsed dataclass instance, the
            raw JSON string, and 실제 HTTP 시도/429 횟수 관측값.

        Raises
        ------
        PermitDeniedError
            ``acquire_permit``이 permit을 거부했을 때 — Gemini에 HTTP
            요청을 **전혀 보내지 않았다**는 확정적 신호.
        httpx.HTTPStatusError
            On HTTP 4xx/5xx responses(재시도 소진 후).
        json.JSONDecodeError
            On invalid JSON in the response body.
        TypeError / ValueError
            On dataclass construction failure.

        모든 예외 인스턴스에는 ``http_attempt_count``/``http_429_count``
        속성이 부착돼 호출자가 실패 시에도 실제 시도 횟수를 관측할 수
        있다.
        """
        client = await self._get_client()

        body: dict[str, Any] = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        if seed is not None:
            body["seed"] = seed

        last_exception: Exception | None = None
        http_attempt_count = 0
        http_429_count = 0

        for attempt in range(MAX_RETRIES):
            if acquire_permit is not None:
                permit = await acquire_permit()
                if not permit.granted:
                    logger.warning(
                        "Provider request permit denied (attempt %d/%d): "
                        "reason=%s waited=%.1fs — HTTP request NOT sent.",
                        attempt + 1, MAX_RETRIES,
                        permit.denial_reason, permit.waited_seconds,
                    )
                    exc = PermitDeniedError(permit)
                    exc.http_attempt_count = http_attempt_count
                    exc.http_429_count = http_429_count
                    raise exc

            http_attempt_count += 1
            try:
                response = await client.post("/v1/chat/completions", json=body)
                response.raise_for_status()
                data = response.json()
                raw_content: str = data["choices"][0]["message"]["content"]

                # Parse JSON into the target dataclass
                parsed_dict = json.loads(raw_content)

                # Recursively coerce nested JSON strings into dicts for nested dataclass fields.
                # Some providers (e.g. DeepSeek) may return nested objects as serialised JSON
                # strings instead of proper nested JSON objects.
                parsed_dict = _coerce_nested_json_strings(response_format, parsed_dict)

                parsed = response_format(**parsed_dict)

                return RawProviderResponse(
                    parsed=parsed,
                    raw_content=raw_content,
                    http_attempt_count=http_attempt_count,
                    http_429_count=http_429_count,
                )

            except (httpx.TransportError, httpx.TimeoutException, httpx.HTTPStatusError, socket.gaierror) as e:
                last_exception = e
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429:
                    http_429_count += 1
                # HTTP 429 또는 5xx만 retry; 그 외 HTTP 에러는 즉시 실패
                if isinstance(e, httpx.HTTPStatusError):
                    status = e.response.status_code
                    if not _is_retryable_http_status(status):
                        e.http_attempt_count = http_attempt_count
                        e.http_429_count = http_429_count
                        raise  # non-retryable HTTP error → 즉시 실패
                # DNS/connect/timeout/429/5xx → retry
                if attempt < MAX_RETRIES - 1:
                    delay = _compute_retry_delay(attempt, e)
                    status_info = ""
                    if isinstance(e, httpx.HTTPStatusError):
                        status_info = f" status={e.response.status_code}"
                    logger.warning(
                        "Provider request failed (attempt %d/%d)%s: %s. "
                        "Retrying in %.1fs...",
                        attempt + 1, MAX_RETRIES, status_info, e, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                # 마지막 시도도 실패 → 원본 예외 throw
                e.http_attempt_count = http_attempt_count
                e.http_429_count = http_429_count
                raise

            except (json.JSONDecodeError, TypeError, ValueError) as e:
                # 파싱 에러는 retry 불필요 → 즉시 실패
                e.http_attempt_count = http_attempt_count
                e.http_429_count = http_429_count
                raise

        # 모든 retry 소진 (위 루프가 raise 없이 끝나면 여기 도달)
        last_exception.http_attempt_count = http_attempt_count  # type: ignore[union-attr]
        last_exception.http_429_count = http_429_count  # type: ignore[union-attr]
        raise last_exception  # type: ignore[misc]

    async def close(self) -> None:
        """Release the underlying HTTP client connection."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
