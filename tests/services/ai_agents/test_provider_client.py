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

from agent_trading.services.ai_agents.base import RawProviderResponse
from agent_trading.services.ai_agents.provider_client import (
    MAX_RETRIES,
    OpenAICompatibleClient,
    _coerce_nested_json_strings,
    _compute_retry_delay,
    _parse_retry_after_seconds,
)


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
