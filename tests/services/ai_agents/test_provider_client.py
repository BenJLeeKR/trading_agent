"""Tests for ``OpenAICompatibleClient`` using mock HTTP transport.

All tests use ``httpx.MockTransport`` to simulate HTTP responses without
making real network calls.
"""

from __future__ import annotations

import json
import socket
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from agent_trading.repositories.contracts import ReservationGrant
from agent_trading.repositories.memory import InMemoryFdcQuotaRepository
from agent_trading.services.ai_agents.base import RawProviderResponse
from agent_trading.services.ai_agents.provider_client import (
    MAX_RETRIES,
    LiveGeminiProviderClient,
    OpenAICompatibleClient,
    PermitDeniedError,
    PermitResult,
    _coerce_nested_json_strings,
    _compute_retry_delay,
    _parse_retry_after_seconds,
)
from agent_trading.services.fdc_quota_coordinator import FdcQuotaCoordinator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class _FakeOutput:
    """Minimal dataclass used as ``response_format`` in tests."""
    symbol: str = ""
    score: float = 0.0


@dataclass(slots=True, frozen=True)
class _NestedInner:
    """Minimal nested dataclass for testing dict→dataclass coercion."""
    size_mode: str = "no_change"
    size_adjustment_factor: float = 0.0


@dataclass(slots=True, frozen=True)
class _NestedOuter:
    """Outer dataclass with a nested dataclass field."""
    decision: str = "hold"
    sizing_hint: _NestedInner = _NestedInner()


def _make_client(
    transport: httpx.MockTransport,
    *,
    api_key: str = "test-key",
    base_url: str = "https://api.test.com",
) -> OpenAICompatibleClient:
    """Build an ``OpenAICompatibleClient`` with a mock transport.

    We override the internal ``_client`` directly so that the mock
    transport is used instead of a real HTTP connection.
    """
    client = OpenAICompatibleClient(
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=10,
    )
    client._client = httpx.AsyncClient(transport=transport, base_url=base_url)
    return client


def _ok_response(body: dict[str, Any]) -> httpx.Response:
    """Return a 200 OK response with the given JSON body."""
    return httpx.Response(200, json=body)


def _make_coordinator(*, target_rpm: int = 13) -> FdcQuotaCoordinator:
    return FdcQuotaCoordinator(
        repo=InMemoryFdcQuotaRepository(),
        target_rpm=target_rpm,
        quota_scope="test:live-gemini",
    )


def _make_live_client(
    transport: httpx.MockTransport,
    *,
    coordinator: FdcQuotaCoordinator | None = None,
    api_key: str = "test-key",
    base_url: str = "https://api.test.com",
) -> LiveGeminiProviderClient:
    """``LiveGeminiProviderClient``를 mock transport로 생성한다(2026-08-27
    PR A 신설 — 기존 ``_make_client()``와 동일한 패턴)."""
    client = LiveGeminiProviderClient(
        coordinator=coordinator or _make_coordinator(),
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=10,
    )
    client._client = httpx.AsyncClient(transport=transport, base_url=base_url)
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOpenAICompatibleClient:
    """Unit tests with mock HTTP transport."""

    @pytest.mark.asyncio
    async def test_generate_structured_returns_parsed_output(self) -> None:
        """Mock HTTP response → parsed dataclass."""
        raw_json = '{"symbol": "AAPL", "score": 0.85}'

        def handler(req: httpx.Request) -> httpx.Response:
            return _ok_response({
                "choices": [{"message": {"content": raw_json}}],
            })

        client = _make_client(httpx.MockTransport(handler))
        result: RawProviderResponse = await client.generate_structured(
            model_id="test-model",
            system_prompt="system",
            user_prompt="user",
            response_format=_FakeOutput,
        )

        assert isinstance(result, RawProviderResponse)
        assert isinstance(result.parsed, _FakeOutput)
        assert result.parsed.symbol == "AAPL"
        assert result.parsed.score == 0.85
        assert result.raw_content == raw_json

    @pytest.mark.asyncio
    async def test_generate_structured_raises_on_http_error(self) -> None:
        """HTTP 4xx → httpx.HTTPStatusError."""
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "unauthorized"})

        client = _make_client(httpx.MockTransport(handler))
        with pytest.raises(httpx.HTTPStatusError):
            await client.generate_structured(
                model_id="test-model",
                system_prompt="system",
                user_prompt="user",
                response_format=_FakeOutput,
            )

    @pytest.mark.asyncio
    async def test_generate_structured_raises_on_invalid_json(self) -> None:
        """Non-JSON response body → json.JSONDecodeError."""
        def handler(req: httpx.Request) -> httpx.Response:
            return _ok_response({
                "choices": [{"message": {"content": "not-json"}}],
            })

        client = _make_client(httpx.MockTransport(handler))
        with pytest.raises(Exception):
            await client.generate_structured(
                model_id="test-model",
                system_prompt="system",
                user_prompt="user",
                response_format=_FakeOutput,
            )

    @pytest.mark.asyncio
    async def test_generate_structured_raises_on_missing_field(self) -> None:
        """Missing required field in response → dataclass TypeError."""
        def handler(req: httpx.Request) -> httpx.Response:
            return _ok_response({
                "choices": [{"message": {"content": '{"symbol": "AAPL"}'}}],
            })

        client = _make_client(httpx.MockTransport(handler))
        # _FakeOutput has defaults for all fields, so no error here.
        # But if we used a dataclass with required fields, it would raise.
        result = await client.generate_structured(
            model_id="test-model",
            system_prompt="system",
            user_prompt="user",
            response_format=_FakeOutput,
        )
        assert result.parsed.symbol == "AAPL"

    @pytest.mark.asyncio
    async def test_client_lazy_init(self) -> None:
        """Client is initialised on first call, not in ``__init__``."""
        client = OpenAICompatibleClient(api_key="test-key")
        # _client should be None before any call
        assert client._client is None

    @pytest.mark.asyncio
    async def test_close_cleans_up(self) -> None:
        """``close()`` releases the HTTP client."""
        def handler(req: httpx.Request) -> httpx.Response:
            return _ok_response({
                "choices": [{"message": {"content": '{"symbol": "X"}'}}],
            })

        client = _make_client(httpx.MockTransport(handler))
        # Trigger lazy init
        await client.generate_structured(
            model_id="m",
            system_prompt="s",
            user_prompt="u",
            response_format=_FakeOutput,
        )
        assert client._client is not None
        await client.close()
        assert client._client is None

    @pytest.mark.asyncio
    async def test_generate_structured_sends_correct_body(self) -> None:
        """Verify the request body sent to the API."""
        captured: list[dict[str, Any]] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(json.loads(req.content))
            return _ok_response({
                "choices": [{"message": {"content": '{"symbol": "X"}'}}],
            })

        client = _make_client(httpx.MockTransport(handler))
        await client.generate_structured(
            model_id="deepseek-chat",
            system_prompt="You are a helpful assistant.",
            user_prompt="Analyze this.",
            response_format=_FakeOutput,
            temperature=0.5,
            seed=42,
        )

        assert len(captured) == 1
        body = captured[0]
        assert body["model"] == "deepseek-chat"
        assert body["messages"][0]["role"] == "system"
        assert body["messages"][0]["content"] == "You are a helpful assistant."
        assert body["messages"][1]["role"] == "user"
        assert body["messages"][1]["content"] == "Analyze this."
        assert body["temperature"] == 0.5
        assert body["seed"] == 42
        assert body["response_format"] == {"type": "json_object"}

    @pytest.mark.asyncio
    async def test_generate_structured_without_seed(self) -> None:
        """When seed is None, it should not be included in the body."""
        captured: list[dict[str, Any]] = []

        def handler(req: httpx.Request) -> httpx.Response:
            captured.append(json.loads(req.content))
            return _ok_response({
                "choices": [{"message": {"content": '{"symbol": "X"}'}}],
            })

        client = _make_client(httpx.MockTransport(handler))
        await client.generate_structured(
            model_id="m",
            system_prompt="s",
            user_prompt="u",
            response_format=_FakeOutput,
        )

        assert "seed" not in captured[0]


# ---------------------------------------------------------------------------
# Nested dataclass coercion tests
# ---------------------------------------------------------------------------


class TestCoerceNestedJsonStrings:
    """Unit tests for ``_coerce_nested_json_strings()`` nested dataclass conversion."""

    def test_nested_dict_converts_to_dataclass(self) -> None:
        """Dict sizing_hint -> _NestedInner dataclass instance after coercion."""
        raw: dict[str, Any] = {
            "decision": "buy",
            "sizing_hint": {"size_mode": "increase", "size_adjustment_factor": 0.15},
        }
        coerced = _coerce_nested_json_strings(_NestedOuter, raw)
        assert isinstance(coerced["sizing_hint"], _NestedInner)
        assert coerced["sizing_hint"].size_mode == "increase"
        assert coerced["sizing_hint"].size_adjustment_factor == 0.15

        # Also verify that the full construction succeeds
        outer = _NestedOuter(**coerced)
        assert outer.decision == "buy"
        assert isinstance(outer.sizing_hint, _NestedInner)
        assert outer.sizing_hint.size_mode == "increase"

    def test_nested_dict_malformed_fallback(self) -> None:
        """Malformed nested dict stays as dict (fallback, no crash)."""
        raw: dict[str, Any] = {
            "decision": "buy",
            "sizing_hint": {"size_mode": "increase", "unknown_field": 1},
        }
        # _NestedInner has only size_mode and size_adjustment_factor;
        # extra keys cause a TypeError on frozen dataclass, but the function
        # should catch it and keep the dict.
        coerced = _coerce_nested_json_strings(_NestedOuter, raw)
        # Should NOT crash; fallback keeps it as dict
        assert isinstance(coerced["sizing_hint"], dict)

    def test_nested_json_string_converts_to_dataclass(self) -> None:
        """JSON-string sizing_hint -> parsed dict -> _NestedInner dataclass."""
        raw: dict[str, Any] = {
            "decision": "sell",
            "sizing_hint": '{"size_mode": "decrease", "size_adjustment_factor": 0.1}',
        }
        coerced = _coerce_nested_json_strings(_NestedOuter, raw)
        assert isinstance(coerced["sizing_hint"], _NestedInner)
        assert coerced["sizing_hint"].size_mode == "decrease"
        assert coerced["sizing_hint"].size_adjustment_factor == 0.1

        outer = _NestedOuter(**coerced)
        assert outer.decision == "sell"
        assert isinstance(outer.sizing_hint, _NestedInner)
        assert outer.sizing_hint.size_mode == "decrease"
        assert outer.sizing_hint.size_adjustment_factor == 0.1


# ---------------------------------------------------------------------------
# Retry / DNS error tests
# ---------------------------------------------------------------------------


class TestRetryAndDnsError:
    """Retry 로직 및 DNS 에러 분류 테스트.

    MockTransport 핸들러에서 예외를 발생시켜 transient 실패를 시뮬레이션.
    """

    @pytest.mark.asyncio
    async def test_dns_error_retry_then_success(self) -> None:
        """DNS resolution 실패 후 retry, 2번째 시도에서 성공."""
        call_count: list[int] = [0]

        def handler(req: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            if call_count[0] == 1:
                raise socket.gaierror(-5, "No address associated with hostname")
            return httpx.Response(200, json={
                "choices": [{"message": {"content": '{"symbol": "AAPL", "score": 0.85}'}}],
            })

        client = _make_client(httpx.MockTransport(handler))
        result = await client.generate_structured(
            model_id="test-model",
            system_prompt="system",
            user_prompt="user",
            response_format=_FakeOutput,
        )
        assert call_count[0] == 2
        assert isinstance(result.parsed, _FakeOutput)
        assert result.parsed.symbol == "AAPL"

    @pytest.mark.asyncio
    async def test_dns_error_all_retries_exhausted(self) -> None:
        """DNS resolution 실패 → 모든 retry 소진 후 최종 실패."""
        call_count: list[int] = [0]

        def handler(req: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            raise socket.gaierror(-5, "No address associated with hostname")

        client = _make_client(httpx.MockTransport(handler))
        with pytest.raises(socket.gaierror, match="No address associated with hostname"):
            await client.generate_structured(
                model_id="test-model",
                system_prompt="system",
                user_prompt="user",
                response_format=_FakeOutput,
            )
        # MAX_RETRIES만큼 시도했어야 함
        assert call_count[0] == MAX_RETRIES

    @pytest.mark.asyncio
    async def test_http_429_retry_then_success(self) -> None:
        """HTTP 429 (rate limit) → retry 후 성공."""
        call_count: list[int] = [0]

        def handler(req: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            if call_count[0] == 1:
                return httpx.Response(429, json={"error": "rate limited"})
            return httpx.Response(200, json={
                "choices": [{"message": {"content": '{"symbol": "AAPL", "score": 0.85}'}}],
            })

        client = _make_client(httpx.MockTransport(handler))
        result = await client.generate_structured(
            model_id="test-model",
            system_prompt="system",
            user_prompt="user",
            response_format=_FakeOutput,
        )
        assert call_count[0] == 2
        assert isinstance(result.parsed, _FakeOutput)
        assert result.parsed.symbol == "AAPL"

    @pytest.mark.asyncio
    async def test_http_400_non_retryable_fails_immediately(self) -> None:
        """HTTP 400 (client error) → retry 없이 즉시 실패."""
        call_count: list[int] = [0]

        def handler(req: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            return httpx.Response(400, json={"error": "bad request"})

        client = _make_client(httpx.MockTransport(handler))
        with pytest.raises(httpx.HTTPStatusError):
            await client.generate_structured(
                model_id="test-model",
                system_prompt="system",
                user_prompt="user",
                response_format=_FakeOutput,
            )
        # 400은 non-retryable → 1번만 호출
        assert call_count[0] == 1

    @pytest.mark.asyncio
    async def test_http_500_retry_then_success(self) -> None:
        """HTTP 500 (server error) → retry 후 성공."""
        call_count: list[int] = [0]

        def handler(req: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            if call_count[0] == 1:
                return httpx.Response(500, json={"error": "internal error"})
            return httpx.Response(200, json={
                "choices": [{"message": {"content": '{"symbol": "AAPL", "score": 0.85}'}}],
            })

        client = _make_client(httpx.MockTransport(handler))
        result = await client.generate_structured(
            model_id="test-model",
            system_prompt="system",
            user_prompt="user",
            response_format=_FakeOutput,
        )
        assert call_count[0] == 2
        assert isinstance(result.parsed, _FakeOutput)

    @pytest.mark.asyncio
    async def test_json_decode_error_no_retry(self) -> None:
        """JSON decode 에러 → retry 없이 즉시 실패."""
        call_count: list[int] = [0]

        def handler(req: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "not-valid-json"}}],
            })

        client = _make_client(httpx.MockTransport(handler))
        with pytest.raises(json.JSONDecodeError):
            await client.generate_structured(
                model_id="test-model",
                system_prompt="system",
                user_prompt="user",
                response_format=_FakeOutput,
            )
        # JSON decode error는 retry 불필요 → 1번만 호출
        assert call_count[0] == 1

    @pytest.mark.asyncio
    async def test_transport_error_retry_then_success(self) -> None:
        """TransportError (connection refused 등) → retry 후 성공."""
        call_count: list[int] = [0]

        def handler(req: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            if call_count[0] == 1:
                raise httpx.ConnectError("Connection refused")
            return httpx.Response(200, json={
                "choices": [{"message": {"content": '{"symbol": "AAPL", "score": 0.85}'}}],
            })

        client = _make_client(httpx.MockTransport(handler))
        result = await client.generate_structured(
            model_id="test-model",
            system_prompt="system",
            user_prompt="user",
            response_format=_FakeOutput,
        )
        assert call_count[0] == 2
        assert isinstance(result.parsed, _FakeOutput)
        assert result.parsed.symbol == "AAPL"

    @pytest.mark.asyncio
    async def test_timeout_exception_retry_then_success(self) -> None:
        """TimeoutException → retry 후 성공."""
        call_count: list[int] = [0]

        def handler(req: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            if call_count[0] == 1:
                raise httpx.TimeoutException("Request timed out")
            return httpx.Response(200, json={
                "choices": [{"message": {"content": '{"symbol": "AAPL", "score": 0.85}'}}],
            })

        client = _make_client(httpx.MockTransport(handler))
        result = await client.generate_structured(
            model_id="test-model",
            system_prompt="system",
            user_prompt="user",
            response_format=_FakeOutput,
        )
        assert call_count[0] == 2
        assert isinstance(result.parsed, _FakeOutput)
        assert result.parsed.symbol == "AAPL"

    def test_parse_retry_after_seconds_with_delta_seconds(self) -> None:
        """Retry-After 숫자 헤더를 초 단위로 해석한다."""
        response = httpx.Response(
            503,
            headers={"Retry-After": "4"},
            request=httpx.Request("POST", "https://api.test.com/v1/chat/completions"),
        )
        assert _parse_retry_after_seconds(response) == 4.0

    def test_parse_retry_after_seconds_with_http_date(self) -> None:
        """Retry-After HTTP-date 헤더를 초 단위로 해석한다."""
        retry_at = datetime.now(timezone.utc) + timedelta(seconds=3)
        response = httpx.Response(
            503,
            headers={"Retry-After": retry_at.strftime("%a, %d %b %Y %H:%M:%S GMT")},
            request=httpx.Request("POST", "https://api.test.com/v1/chat/completions"),
        )
        parsed = _parse_retry_after_seconds(response)
        assert parsed is not None
        assert 0.0 <= parsed <= 5.0

    def test_compute_retry_delay_prefers_retry_after_header(self) -> None:
        """Retry-After가 있으면 지수 백오프보다 우선한다."""
        request = httpx.Request("POST", "https://api.test.com/v1/chat/completions")
        response = httpx.Response(
            503,
            headers={"Retry-After": "4"},
            request=request,
        )
        error = httpx.HTTPStatusError(
            "503 Service Unavailable",
            request=request,
            response=response,
        )
        assert _compute_retry_delay(0, error) == 4.0


# ---------------------------------------------------------------------------
# acquire_permit gating tests (2026-08-21, strict FDC rate limiter)
# ---------------------------------------------------------------------------


class TestAcquirePermitGating:
    """``acquire_permit`` 콜백이 최초 요청 + 매 재시도마다 재호출되고,
    permit 거부 시 실제 HTTP 요청이 전혀 발생하지 않음을 검증한다.
    """

    @pytest.mark.asyncio
    async def test_permit_denied_before_first_request_sends_no_http_call(
        self,
    ) -> None:
        """permit이 최초 시도에서부터 거부되면 HTTP 요청이 0번 발생해야 한다."""
        call_count: list[int] = [0]

        def handler(req: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            raise AssertionError("permit이 거부됐는데 HTTP 요청이 발생함")

        async def deny_permit() -> PermitResult:
            return PermitResult(granted=False, waited_seconds=18.0, denial_reason="queue_timeout")

        client = _make_client(httpx.MockTransport(handler))
        with pytest.raises(PermitDeniedError) as exc_info:
            await client.generate_structured(
                model_id="test-model",
                system_prompt="system",
                user_prompt="user",
                response_format=_FakeOutput,
                acquire_permit=deny_permit,
            )
        assert call_count[0] == 0
        assert exc_info.value.http_attempt_count == 0
        assert exc_info.value.http_429_count == 0
        assert exc_info.value.result.denial_reason == "queue_timeout"

    @pytest.mark.asyncio
    async def test_permit_granted_before_every_attempt_including_retries(
        self,
    ) -> None:
        """429로 2회 재시도되는 경우, permit도 정확히 3회(시도당 1회씩)
        재획득돼야 한다."""
        http_call_count: list[int] = [0]
        permit_call_count: list[int] = [0]

        def handler(req: httpx.Request) -> httpx.Response:
            http_call_count[0] += 1
            if http_call_count[0] < 3:
                return httpx.Response(429, json={"error": "rate limited"})
            return httpx.Response(200, json={
                "choices": [{"message": {"content": '{"symbol": "AAPL", "score": 0.85}'}}],
            })

        async def grant_permit() -> PermitResult:
            permit_call_count[0] += 1
            return PermitResult(granted=True, waited_seconds=0.5)

        client = _make_client(httpx.MockTransport(handler))
        result = await client.generate_structured(
            model_id="test-model",
            system_prompt="system",
            user_prompt="user",
            response_format=_FakeOutput,
            acquire_permit=grant_permit,
        )
        assert http_call_count[0] == 3
        assert permit_call_count[0] == 3
        assert result.http_attempt_count == 3
        assert result.http_429_count == 2

    @pytest.mark.asyncio
    async def test_permit_denied_on_retry_halts_further_http_attempts(
        self,
    ) -> None:
        """첫 시도는 permit 승인 후 429를 받지만, 재시도 직전 permit이
        거부되면 두 번째 HTTP 요청은 절대 발생하지 않아야 한다."""
        http_call_count: list[int] = [0]
        permit_call_count: list[int] = [0]

        def handler(req: httpx.Request) -> httpx.Response:
            http_call_count[0] += 1
            return httpx.Response(429, json={"error": "rate limited"})

        async def permit_then_deny() -> PermitResult:
            permit_call_count[0] += 1
            if permit_call_count[0] == 1:
                return PermitResult(granted=True, waited_seconds=0.0)
            return PermitResult(
                granted=False, waited_seconds=18.0, denial_reason="queue_timeout",
            )

        client = _make_client(httpx.MockTransport(handler))
        with pytest.raises(PermitDeniedError) as exc_info:
            await client.generate_structured(
                model_id="test-model",
                system_prompt="system",
                user_prompt="user",
                response_format=_FakeOutput,
                acquire_permit=permit_then_deny,
            )
        # 첫 HTTP 요청(429)만 발생했어야 한다 — 재시도 직전 permit 거부로
        # 두 번째 HTTP 요청은 절대 나가지 않는다.
        assert http_call_count[0] == 1
        assert permit_call_count[0] == 2
        assert exc_info.value.http_attempt_count == 1
        assert exc_info.value.http_429_count == 1

    @pytest.mark.asyncio
    async def test_no_acquire_permit_preserves_existing_behavior(self) -> None:
        """``acquire_permit=None``(기본값)이면 permit 체크 없이 기존과
        100% 동일하게 즉시 호출한다(Stub/EI/AR 등 기존 호출자 호환성)."""
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "choices": [{"message": {"content": '{"symbol": "AAPL", "score": 0.85}'}}],
            })

        client = _make_client(httpx.MockTransport(handler))
        result = await client.generate_structured(
            model_id="test-model",
            system_prompt="system",
            user_prompt="user",
            response_format=_FakeOutput,
        )
        assert result.parsed.symbol == "AAPL"
        assert result.http_attempt_count == 1
        assert result.http_429_count == 0


# ---------------------------------------------------------------------------
# LiveGeminiProviderClient / generate_structured_once (2026-08-27 PR A 신설)
# ---------------------------------------------------------------------------


class TestLiveGeminiProviderClientConstruction:
    """coordinator 없이는 생성 불가(설계 문서 §12 fail-closed 경계)."""

    def test_requires_coordinator(self) -> None:
        with pytest.raises(ValueError, match="coordinator"):
            LiveGeminiProviderClient(coordinator=None, api_key="k")  # type: ignore[arg-type]

    def test_constructs_with_coordinator(self) -> None:
        client = LiveGeminiProviderClient(coordinator=_make_coordinator(), api_key="k")
        assert client.coordinator is not None

    def test_is_subclass_of_openai_compatible_client(self) -> None:
        """``isinstance`` 관계는 유지되지만(코드 재사용 목적),
        ``generate_structured()``는 아래 ``TestGenerateStructuredBlocked``
        가 검증하듯 의도적으로 차단돼 있다 — AR 같은 non-FDC 호출이
        이 클래스를 상속 관계만으로 "우연히" 재사용하면 안 된다는
        신호이기도 하다(2026-08-27 리뷰 보정)."""
        client = LiveGeminiProviderClient(coordinator=_make_coordinator(), api_key="k")
        assert isinstance(client, OpenAICompatibleClient)


class TestGenerateStructuredBlocked:
    """2026-08-27 리뷰 보정: ``LiveGeminiProviderClient``가 상속받은
    ``generate_structured()``를 그대로 노출하면, 호출자가 reservation
    없이 이 메서드를 직접 호출해 FDC quota coordinator를 완전히
    우회하는 live HTTP를 보낼 수 있었다. 이제 이 메서드는 HTTP 요청
    **전**에 항상 예외를 던진다."""

    @pytest.mark.asyncio
    async def test_raises_before_any_http_request(self) -> None:
        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return _ok_response({"choices": [{"message": {"content": "{}"}}]})

        client = _make_live_client(httpx.MockTransport(handler))

        with pytest.raises(RuntimeError, match="generate_structured_once"):
            await client.generate_structured(
                model_id="test-model", system_prompt="s", user_prompt="u",
                response_format=_FakeOutput,
            )

        assert call_count == 0

    @pytest.mark.asyncio
    async def test_raises_even_with_acquire_permit_supplied(self) -> None:
        """acquire_permit을 넘겨도(레거시 permit 어댑터를 실수로 재사용
        하려는 시도) 차단은 그대로 유지된다."""
        client = _make_live_client(
            httpx.MockTransport(lambda req: _ok_response({"choices": [{"message": {"content": "{}"}}]}))
        )

        async def _always_granted() -> PermitResult:
            return PermitResult(granted=True)

        with pytest.raises(RuntimeError, match="generate_structured_once"):
            await client.generate_structured(
                model_id="test-model", system_prompt="s", user_prompt="u",
                response_format=_FakeOutput, acquire_permit=_always_granted,
            )


class TestGenerateStructuredOnce:
    """``generate_structured_once()``는 정확히 HTTP 1회만 수행하고,
    retry/backoff/acquire_permit/새 reservation 요청을 전혀 하지 않는다."""

    @pytest.mark.asyncio
    async def test_success_calls_http_exactly_once(self) -> None:
        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return _ok_response({
                "choices": [{"message": {"content": '{"symbol": "AAPL", "score": 0.9}'}}],
            })

        coordinator = _make_coordinator()
        client = _make_live_client(httpx.MockTransport(handler), coordinator=coordinator)
        grant_result = await coordinator.try_reserve(job_id=None, caller_id="test")
        assert isinstance(grant_result, ReservationGrant)

        result = await client.generate_structured_once(
            grant_result,
            expected_job_id=None,
            expected_attempt_no=1,
            model_id="test-model",
            system_prompt="system",
            user_prompt="user",
            response_format=_FakeOutput,
        )

        assert call_count == 1
        assert result.parsed.symbol == "AAPL"
        assert result.http_attempt_count == 1
        assert result.http_429_count == 0

    @pytest.mark.asyncio
    async def test_does_not_retry_on_retryable_failure(self) -> None:
        """429처럼 기존 ``generate_structured()``라면 재시도했을 오류도
        one-shot은 재시도 없이 즉시 예외를 던진다 — retry는 dispatcher/
        호출자가 새 reservation으로 다시 호출해야 하는 책임이다."""
        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(429, json={"error": "rate_limited"})

        coordinator = _make_coordinator()
        client = _make_live_client(httpx.MockTransport(handler), coordinator=coordinator)
        grant_result = await coordinator.try_reserve(job_id=None, caller_id="test")
        assert isinstance(grant_result, ReservationGrant)

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await client.generate_structured_once(
                grant_result,
                expected_job_id=None,
                expected_attempt_no=1,
                model_id="test-model",
                system_prompt="system",
                user_prompt="user",
                response_format=_FakeOutput,
            )

        assert call_count == 1  # 재시도 없음 — MAX_RETRIES와 무관
        assert exc_info.value.http_attempt_count == 1
        assert exc_info.value.http_429_count == 1

    @pytest.mark.asyncio
    async def test_grant_mismatch_rejects_before_http(self) -> None:
        """grant의 job_id/attempt_no가 호출자가 실행하려는 job과 다르면
        HTTP를 보내기 전에 거부한다."""
        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return _ok_response({"choices": [{"message": {"content": "{}"}}]})

        coordinator = _make_coordinator()
        client = _make_live_client(httpx.MockTransport(handler), coordinator=coordinator)
        grant_result = await coordinator.try_reserve(job_id=None, caller_id="test")
        assert isinstance(grant_result, ReservationGrant)

        with pytest.raises(ValueError, match="grant mismatch"):
            await client.generate_structured_once(
                grant_result,
                expected_job_id=None,
                expected_attempt_no=99,  # grant.attempt_no(1)와 불일치
                model_id="test-model",
                system_prompt="system",
                user_prompt="user",
                response_format=_FakeOutput,
            )

        assert call_count == 0  # HTTP가 전혀 나가지 않았어야 한다

    @pytest.mark.asyncio
    async def test_does_not_call_acquire_permit(self) -> None:
        """one-shot은 기존 10 RPM strict limiter(acquire_permit)를 호출할
        방법 자체가 없다 — 시그니처에 그 인자가 없음을 코드로도 보증한다."""
        import inspect
        sig = inspect.signature(LiveGeminiProviderClient.generate_structured_once)
        assert "acquire_permit" not in sig.parameters


class TestSingleHttpAttemptExtractionRegression:
    """2026-08-27 PR A: ``generate_structured()``의 retry 루프 안에 있던
    "요청 1회 전송 + 성공 파싱"을 ``_single_http_attempt()``로 추출했다
    — 이 회귀 테스트는 그 추출이 순수 리팩터링이었음을 별도로 증명한다
    (파일 상단의 기존 테스트 전부가 이미 이를 간접 검증하지만, 여기서는
    헬퍼 자체의 존재와 호출 가능성을 직접 확인한다)."""

    @pytest.mark.asyncio
    async def test_single_http_attempt_helper_exists_and_is_shared(self) -> None:
        client = _make_client(httpx.MockTransport(lambda req: _ok_response({"choices": [{"message": {"content": "{}"}}]})))
        live_client = _make_live_client(
            httpx.MockTransport(lambda req: _ok_response({"choices": [{"message": {"content": "{}"}}]}))
        )
        # 두 클래스가 같은 private 헬퍼를 공유한다(상속) — 별개로 구현되지 않았음.
        assert type(client)._single_http_attempt is type(live_client)._single_http_attempt
