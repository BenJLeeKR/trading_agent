"""EGW00123 Token Expiry Auto-Recovery — 테스트 스위트.

``TokenExpiredError`` 예외 클래스, ``_raise_on_error()`` 감지 로직,
``KisTokenCache.invalidate()``, ``KISRestClient._invalidate_token_cache()``,
그리고 ``_request()``의 read-only bucket 자동 재시도 로직을 검증한다.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent_trading.brokers.errors import BrokerError, TokenExpiredError
from agent_trading.brokers.koreainvestment.rest_client import (
    KISRestClient,
    _TOKEN_EXPIRED_CODES,
)
from agent_trading.brokers.koreainvestment.token_cache import (
    CachePurpose,
    KisTokenCache,
    KisTokenCacheConfig,
)
from agent_trading.brokers.rate_limit import BucketType
from agent_trading.domain.enums import BrokerName


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def mock_rest_client() -> KISRestClient:
    """Minimal KISRestClient fixture for unit tests."""
    client = KISRestClient(
        api_key="test_key",
        api_secret="test_secret",
        account_number="12345678",
        account_product_code="01",
        env="paper",
    )
    # Mock the HTTP client to avoid real network calls
    client._client = MagicMock(spec=httpx.AsyncClient)
    return client


def _make_response(
    status_code: int = 200,
    msg_cd: str = "",
    rt_cd: str = "0",
    msg1: str = "",
) -> httpx.Response:
    """Helper: create a mock httpx.Response with given KIS error fields."""
    json_data = {
        "msg_cd": msg_cd,
        "rt_cd": rt_cd,
        "msg1": msg1,
    }
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    return resp


# =========================================================================
# Test 1: _raise_on_error() EGW00123 → TokenExpiredError
# =========================================================================


class TestRaiseOnErrorDetectsTokenExpired:
    """_raise_on_error()가 EGW00123/EGW00101 감지 시 TokenExpiredError를 raise하는지 검증."""

    @pytest.mark.parametrize("msg_cd", ["EGW00123", "EGW00101"])
    def test_token_expired_codes_raise_token_expired_error(
        self, mock_rest_client: KISRestClient, msg_cd: str
    ) -> None:
        """EGW00123과 EGW00101 모두 TokenExpiredError를 raise해야 함."""
        resp = _make_response(status_code=200, msg_cd=msg_cd, rt_cd="1", msg1="token expired")

        with pytest.raises(TokenExpiredError) as exc_info:
            mock_rest_client._raise_on_error(resp, endpoint="inquire_balance")

        assert exc_info.value.retryable is True
        assert exc_info.value.endpoint_key == "inquire_balance"
        assert exc_info.value.msg_cd == msg_cd

    def test_egw00123_not_in_ambiguous_codes(
        self, mock_rest_client: KISRestClient
    ) -> None:
        """EGW00123이 _AMBIGUOUS_ERROR_CODES에 없어야 함.
        
        즉, EGW00123은 TokenExpiredError로 처리되고 BrokerError(ambiguous)가 아님.
        """
        from agent_trading.brokers.koreainvestment.rest_client import (
            _AMBIGUOUS_ERROR_CODES,
        )
        assert "EGW00123" not in _AMBIGUOUS_ERROR_CODES

    def test_other_ambiguous_codes_unchanged(
        self, mock_rest_client: KISRestClient
    ) -> None:
        """EGW00123 외 다른 ambiguous code는 기존 BrokerError로 raise되어야 함."""
        resp = _make_response(
            status_code=200, msg_cd="EGW00125", rt_cd="1", msg1="주문전송 실패"
        )

        with pytest.raises(BrokerError) as exc_info:
            mock_rest_client._raise_on_error(resp, endpoint="order_cash")

        assert not isinstance(exc_info.value, TokenExpiredError)
        assert exc_info.value.retryable is False


# =========================================================================
# Test 2: KisTokenCache.invalidate()
# =========================================================================


class TestKisTokenCacheInvalidate:
    """KisTokenCache.invalidate()가 캐시 파일을 삭제하는지 검증."""

    @pytest.fixture
    def temp_cache_path(self, tmp_path: Path) -> Path:
        return tmp_path / "test_kis_token.json"

    @pytest.fixture
    def cache(self, temp_cache_path: Path) -> KisTokenCache:
        return KisTokenCache(KisTokenCacheConfig(
            enabled=True,
            cache_path=temp_cache_path,
            cache_purpose=CachePurpose.PAPER_ACCESS_TOKEN,
            fingerprint_input="test_key",
        ))

    async def test_invalidate_removes_file(
        self, cache: KisTokenCache, temp_cache_path: Path
    ) -> None:
        """invalidate() 호출 후 캐시 파일이 삭제되어야 함."""
        # 먼저 저장
        await cache.save("test_token", expires_in=86400)
        assert temp_cache_path.exists()

        # 무효화
        await cache.invalidate()
        assert not temp_cache_path.exists()

    async def test_invalidate_skips_when_disabled(
        self, temp_cache_path: Path
    ) -> None:
        """enabled=False면 invalidate()가 아무것도 하지 않아야 함."""
        cache = KisTokenCache(KisTokenCacheConfig(
            enabled=False,
            cache_path=temp_cache_path,
            cache_purpose=CachePurpose.PAPER_ACCESS_TOKEN,
            fingerprint_input="test_key",
        ))
        # 파일이 없어도 에러 없이 skip
        await cache.invalidate()

    async def test_invalidate_skips_when_missing(
        self, cache: KisTokenCache
    ) -> None:
        """캐시 파일이 없으면 invalidate()가 에러 없이 skip."""
        await cache.invalidate()  # should not raise


# =========================================================================
# Test 3: KISRestClient._invalidate_token_cache()
# =========================================================================


class TestInvalidateTokenCache:
    """KISRestClient._invalidate_token_cache()가 in-memory + file cache를 모두 무효화하는지 검증."""

    async def test_invalidates_in_memory_and_file(
        self, mock_rest_client: KISRestClient
    ) -> None:
        """_invalidate_token_cache() 호출 후 in-memory cache가 초기화되어야 함."""
        # Given: in-memory cache가 설정됨
        mock_rest_client._access_token = "expired_token"
        mock_rest_client._token_expires_at = time.time() + 3600

        # Mock file cache
        mock_rest_client._token_cache = AsyncMock(spec=KisTokenCache)

        # When: invalidate 호출
        await mock_rest_client._invalidate_token_cache()

        # Then: in-memory cache가 초기화됨
        assert mock_rest_client._access_token is None
        assert mock_rest_client._token_expires_at == 0.0

        # Then: file cache invalidate가 호출됨
        mock_rest_client._token_cache.invalidate.assert_awaited_once()

    async def test_skips_file_cache_when_none(
        self, mock_rest_client: KISRestClient
    ) -> None:
        """_token_cache가 None이면 file cache 무효화를 skip해야 함."""
        mock_rest_client._token_cache = None
        mock_rest_client._access_token = "expired_token"

        await mock_rest_client._invalidate_token_cache()

        assert mock_rest_client._access_token is None


# =========================================================================
# Test 4: _request() auto-reauth on TokenExpiredError
# =========================================================================


class TestRequestAutoReauth:
    """_request()에서 TokenExpiredError 발생 시 재인증 후 재시도하는지 검증.

    KISRestClient는 @dataclass(slots=True)이므로 메서드 patch.object가 불가능.
    대신 _client.get/_client.post를 모킹하고, authenticate()가 실제 호출될 때
    _client.post (oauth2/tokenP)도 모킹하여 재인증을 시뮬레이션한다.
    """

    @pytest.fixture
    def client(self) -> KISRestClient:
        """Mock HTTP client가 있는 KISRestClient."""
        c = KISRestClient(
            api_key="test_key",
            api_secret="test_secret",
            account_number="12345678",
            account_product_code="01",
            env="paper",
        )
        # _client는 slots에 정의된 attribute이므로 object.__setattr__로 설정 가능
        object.__setattr__(c, "_client", AsyncMock(spec=httpx.AsyncClient))
        # _invalidate_token_cache도 slots에 정의되어 있으므로 직접 모킹 불가.
        # 대신 _access_token/_token_expires_at 상태로 검증
        return c

    async def _setup_auth_mock(self, client: KISRestClient) -> AsyncMock:
        """authenticate()가 정상 동작하도록 _client.post (oauth2)를 모킹."""
        auth_resp = MagicMock(spec=httpx.Response)
        auth_resp.status_code = 200
        auth_resp.json.return_value = {
            "access_token": "new_token",
            "token_type": "Bearer",
            "expires_in": 86400,
        }
        mock_post = AsyncMock(return_value=auth_resp)
        client._client.post = mock_post  # type: ignore[method-assign]
        return mock_post

    async def test_auto_reauth_on_token_expired_inquiry(
        self, client: KISRestClient
    ) -> None:
        """INQUIRY bucket에서 TokenExpiredError 발생 시 재인증 후 1회 재시도 성공."""
        await self._setup_auth_mock(client)

        # 첫 번째 응답: TokenExpiredError
        error_resp = _make_response(
            status_code=200, msg_cd="EGW00123", rt_cd="1", msg1="기간이 만료된 token 입니다."
        )
        # 두 번째 응답: 성공
        success_resp = MagicMock(spec=httpx.Response)
        success_resp.status_code = 200
        success_resp.json.return_value = {"output": {"key": "value"}, "rt_cd": "0"}

        # Mock HTTP GET: 첫 호출은 실패, 두 번째는 성공
        mock_get = AsyncMock(side_effect=[error_resp, success_resp])
        client._client.get = mock_get  # type: ignore[method-assign]

        result = await client._request(
            "GET",
            endpoint_key="inquire_balance",
            tr_id_key="inquire_balance",
            bucket=BucketType.INQUIRY,
        )

        # 재시도 성공 확인
        assert result == {"output": {"key": "value"}}
        # in-memory cache가 무효화되었는지 확인
        assert client._access_token is not None  # 재인증 후 새 token
        # HTTP GET이 2번 호출되었는지 확인 (원본 + 재시도)
        assert mock_get.call_count == 2

    async def test_no_reauth_on_order_bucket(
        self, client: KISRestClient
    ) -> None:
        """ORDER bucket에서는 TokenExpiredError가 자동 재시도되지 않아야 함."""
        await self._setup_auth_mock(client)

        error_resp = _make_response(
            status_code=200, msg_cd="EGW00123", rt_cd="1", msg1="기간이 만료된 token 입니다."
        )
        # ORDER bucket은 POST를 사용하므로 _client.post를 모킹
        mock_post = AsyncMock(return_value=error_resp)
        client._client.post = mock_post  # type: ignore[method-assign]

        with pytest.raises(TokenExpiredError):
            await client._request(
                "POST",
                endpoint_key="order_cash",
                tr_id_key="order_buy",
                bucket=BucketType.ORDER,
                body={"key": "value"},
            )

        # ORDER bucket은 재시도하지 않으므로 POST는 1번만 호출
        assert mock_post.call_count == 1

    async def test_reauth_exhausted(
        self, client: KISRestClient
    ) -> None:
        """재인증 후에도 동일 오류 발생 시 원본 TokenExpiredError가 전파되어야 함."""
        await self._setup_auth_mock(client)

        error_resp = _make_response(
            status_code=200, msg_cd="EGW00123", rt_cd="1", msg1="기간이 만료된 token 입니다."
        )
        # 계속 EGW00123 반환
        mock_get = AsyncMock(return_value=error_resp)
        client._client.get = mock_get  # type: ignore[method-assign]

        with pytest.raises(TokenExpiredError) as exc_info:
            await client._request(
                "GET",
                endpoint_key="inquire_balance",
                tr_id_key="inquire_balance",
                bucket=BucketType.INQUIRY,
            )

        # 재시도 후에도 실패 → 원본 오류 전파
        assert exc_info.value.msg_cd == "EGW00123"
        # HTTP GET이 2번 호출되었는지 확인 (원본 + 재시도)
        assert mock_get.call_count == 2

    async def test_market_data_bucket_auto_reauth(
        self, client: KISRestClient
    ) -> None:
        """MARKET_DATA bucket에서도 TokenExpiredError 자동 재시도가 동작해야 함."""
        await self._setup_auth_mock(client)

        error_resp = _make_response(
            status_code=200, msg_cd="EGW00123", rt_cd="1", msg1="기간이 만료된 token 입니다."
        )
        success_resp = MagicMock(spec=httpx.Response)
        success_resp.status_code = 200
        success_resp.json.return_value = {"output": {"price": "50000"}, "rt_cd": "0"}

        mock_get = AsyncMock(side_effect=[error_resp, success_resp])
        client._client.get = mock_get  # type: ignore[method-assign]

        result = await client._request(
            "GET",
            endpoint_key="inquire_price",
            tr_id_key="inquire_price",
            bucket=BucketType.MARKET_DATA,
        )

        assert result == {"output": {"price": "50000"}}
        assert mock_get.call_count == 2

    async def test_reconciliation_bucket_auto_reauth(
        self, client: KISRestClient
    ) -> None:
        """RECONCILIATION bucket에서도 TokenExpiredError 자동 재시도가 동작해야 함."""
        await self._setup_auth_mock(client)

        error_resp = _make_response(
            status_code=200, msg_cd="EGW00123", rt_cd="1", msg1="기간이 만료된 token 입니다."
        )
        success_resp = MagicMock(spec=httpx.Response)
        success_resp.status_code = 200
        success_resp.json.return_value = {"output": [], "rt_cd": "0"}

        mock_get = AsyncMock(side_effect=[error_resp, success_resp])
        client._client.get = mock_get  # type: ignore[method-assign]

        result = await client._request(
            "GET",
            endpoint_key="inquire_daily_ccld",
            tr_id_key="inquire_daily_ccld",
            bucket=BucketType.RECONCILIATION,
        )

        assert result == {"output": []}
        assert mock_get.call_count == 2


# =========================================================================
# Test 5: _TOKEN_EXPIRED_CODES 상수 검증
# =========================================================================


class TestTokenExpiredCodes:
    """_TOKEN_EXPIRED_CODES 상수에 올바른 코드가 포함되어 있는지 검증."""

    def test_contains_egw00123(self) -> None:
        assert "EGW00123" in _TOKEN_EXPIRED_CODES

    def test_contains_egw00101(self) -> None:
        assert "EGW00101" in _TOKEN_EXPIRED_CODES

    def test_does_not_contain_other_codes(self) -> None:
        """다른 일반 오류 코드는 _TOKEN_EXPIRED_CODES에 없어야 함."""
        assert "EGW00125" not in _TOKEN_EXPIRED_CODES
        assert "EGW00100" not in _TOKEN_EXPIRED_CODES
        assert "EGW00200" not in _TOKEN_EXPIRED_CODES
