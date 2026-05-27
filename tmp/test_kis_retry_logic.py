"""
KIS RestClient _request() retry 로직 검증

시나리오:
1. 정상 요청 → retry 없이 즉시 성공
2. 1회 timeout → 1회 retry → 성공
3. 2회 timeout → 2회 retry → 최종 실패 → BrokerError
4. 3회 timeout → 최대 retry 소진 → BrokerError + circuit breaker 기록
"""
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from decimal import Decimal

import httpx

from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.brokers.errors import BrokerError, BrokerErrorType
from agent_trading.brokers.rate_limit import BucketType
from agent_trading.brokers.backoff import CircuitState


# ── Helpers ──────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    """Minimal KISRestClient with pre-set access token and mocked HTTP client."""
    c = KISRestClient(
        api_key="dummy-key",
        api_secret="dummy-secret",
        account_number="12345678",
        account_product_code="01",
        env="paper",
        dev_token_cache_path="/tmp/_test_kis_token.json",
    )
    # Pre-set access token so authenticate() returns immediately without HTTP call
    object.__setattr__(c, "_access_token", "test-access-token")
    object.__setattr__(c, "_token_expires_at", time.time() + 3600)
    # Reset circuit breaker via object.__setattr__ (slots dataclass)
    object.__setattr__(c._circuit_breaker, "_state", CircuitState.CLOSED)
    object.__setattr__(c._circuit_breaker, "_failure_count", 0)
    return c


def _success_response():
    """Return a mock Response that looks like a successful KIS API response."""
    resp = AsyncMock()
    resp.status_code = 200
    # _raise_on_error calls resp.json() synchronously (no await)
    resp.json = MagicMock(return_value={
        "rt_cd": "0",
        "msg_cd": "00000",
        "msg": "success",
        "output": {},
    })
    return resp


def _timeout_exception():
    """Return a TimeoutException."""
    return httpx.TimeoutException("Connection timed out", request=None)


def _setup_mock_client(c, mock_http):
    """Inject a mock httpx.AsyncClient into the KISRestClient via _client slot.
    
    Since KISRestClient uses @dataclass(slots=True), we use object.__setattr__
    to bypass the read-only restriction for slots fields.
    """
    object.__setattr__(c, "_client", mock_http)


# ── Tests ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_normal_request_succeeds_without_retry(client):
    """Scenario 1: 정상 요청 → retry 없이 즉시 성공"""
    c = client
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.get = AsyncMock(return_value=_success_response())
    _setup_mock_client(c, mock_http)

    result = await c._request(
        method="GET",
        endpoint_key="inquire_psbl_order",
        tr_id_key="inquire_psbl_order",
        bucket=BucketType.INQUIRY,
    )

    assert result is not None
    assert result.get("output") == {}
    # get이 정확히 1번만 호출되어야 함 (retry 없음)
    assert mock_http.get.call_count == 1
    # circuit breaker는 기록되지 않아야 함
    assert c._circuit_breaker._failure_count == 0


@pytest.mark.asyncio
async def test_one_timeout_then_retry_succeeds(client):
    """Scenario 2: 1회 timeout → 1회 retry → 성공"""
    c = client
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.get = AsyncMock(
        side_effect=[
            _timeout_exception(),   # 1차: timeout
            _success_response(),    # 2차: 성공
        ]
    )
    _setup_mock_client(c, mock_http)

    result = await c._request(
        method="GET",
        endpoint_key="inquire_psbl_order",
        tr_id_key="inquire_psbl_order",
        bucket=BucketType.INQUIRY,
    )

    assert result is not None
    assert result.get("output") == {}
    # get이 2번 호출되어야 함 (1회 실패 + 1회 성공)
    assert mock_http.get.call_count == 2
    # 최종 성공했으므로 circuit breaker 기록 없음
    assert c._circuit_breaker._failure_count == 0


@pytest.mark.asyncio
async def test_two_timeouts_then_retry_succeeds(client):
    """Scenario 3: 2회 timeout → 2회 retry → 성공"""
    c = client
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.get = AsyncMock(
        side_effect=[
            _timeout_exception(),   # 1차: timeout
            _timeout_exception(),   # 2차: timeout
            _success_response(),    # 3차: 성공
        ]
    )
    _setup_mock_client(c, mock_http)

    result = await c._request(
        method="GET",
        endpoint_key="inquire_psbl_order",
        tr_id_key="inquire_psbl_order",
        bucket=BucketType.INQUIRY,
    )

    assert result is not None
    assert result.get("output") == {}
    # get이 3번 호출되어야 함 (2회 실패 + 1회 성공)
    assert mock_http.get.call_count == 3
    # 최종 성공했으므로 circuit breaker 기록 없음
    assert c._circuit_breaker._failure_count == 0


@pytest.mark.asyncio
async def test_three_timeouts_raises_broker_error_with_circuit_breaker(client):
    """Scenario 4: 3회 timeout → 최대 retry 소진 → BrokerError + circuit breaker 기록"""
    c = client
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.get = AsyncMock(
        side_effect=[
            _timeout_exception(),   # 1차: timeout
            _timeout_exception(),   # 2차: timeout (retry)
            _timeout_exception(),   # 3차: timeout (retry) → 최종 실패
        ]
    )
    _setup_mock_client(c, mock_http)

    with pytest.raises(BrokerError) as exc_info:
        await c._request(
            method="GET",
            endpoint_key="inquire_psbl_order",
            tr_id_key="inquire_psbl_order",
            bucket=BucketType.INQUIRY,
        )

    assert exc_info.value.error_type == BrokerErrorType.TIMEOUT
    assert exc_info.value.retryable is True
    assert "timeout after 3 attempts" in exc_info.value.raw_message
    # get이 정확히 3번 호출되어야 함 (모두 timeout)
    assert mock_http.get.call_count == 3
    # circuit breaker가 기록되어야 함
    assert c._circuit_breaker._failure_count == 1


@pytest.mark.asyncio
async def test_request_error_no_retry(client):
    """httpx.RequestError는 retry 없이 즉시 BrokerError 발생"""
    c = client
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.get = AsyncMock(
        side_effect=httpx.RequestError("Connection refused", request=None)
    )
    _setup_mock_client(c, mock_http)

    with pytest.raises(BrokerError) as exc_info:
        await c._request(
            method="GET",
            endpoint_key="inquire_psbl_order",
            tr_id_key="inquire_psbl_order",
            bucket=BucketType.INQUIRY,
        )

    assert exc_info.value.error_type == BrokerErrorType.NETWORK_ERROR
    assert exc_info.value.retryable is True
    # RequestError는 retry 없이 즉시 실패 → 1번만 호출
    assert mock_http.get.call_count == 1
    # circuit breaker 기록
    assert c._circuit_breaker._failure_count == 1


@pytest.mark.asyncio
async def test_circuit_breaker_open_raises_immediately(client):
    """Circuit breaker가 OPEN 상태면 요청 없이 즉시 BrokerError"""
    c = client
    # state property가 _check_timeout()을 호출하므로 _last_failure_time을
    # 현재 시간 근처로 설정하여 recovery_timeout(30s)이 경과하지 않도록 함
    now = time.monotonic()
    object.__setattr__(c._circuit_breaker, "_state", CircuitState.OPEN)
    object.__setattr__(c._circuit_breaker, "_failure_count", 3)
    object.__setattr__(c._circuit_breaker, "_last_failure_time", now)
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    _setup_mock_client(c, mock_http)

    with pytest.raises(BrokerError) as exc_info:
        await c._request(
            method="GET",
            endpoint_key="inquire_psbl_order",
            tr_id_key="inquire_psbl_order",
            bucket=BucketType.INQUIRY,
        )

    assert exc_info.value.error_type == BrokerErrorType.API_ERROR
    assert "circuit breaker open" in exc_info.value.raw_message
    # HTTP 요청이 전혀 발생하지 않아야 함
    assert mock_http.get.call_count == 0


if __name__ == "__main__":
    pytest.main([__file__, "-x", "-v"])
