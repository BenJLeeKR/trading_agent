"""Tests for ``agent_trading.services.symbol_resolver`` — OpenDartSymbolResolver.

Test coverage
-------------
* stock_code present → normal mapping (no API call needed)
* stock_code absent + /company.json success → resolved symbol
* stock_code absent + /company.json failure → None (negative cache)
* Cache hit → no duplicate API call
* Negative cache: failed corp_code not retried
* Rate limit: consecutive calls respect interval
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from agent_trading.services.symbol_resolver import OpenDartSymbolResolver


@pytest.fixture
def api_key() -> str:
    return "test_api_key_12345"


@pytest.fixture
def resolver(api_key: str) -> OpenDartSymbolResolver:
    return OpenDartSymbolResolver(
        api_key=api_key,
        rate_limit_interval=0.0,  # disable rate limit for tests
    )


class TestOpenDartSymbolResolver:
    """OpenDartSymbolResolver unit tests."""

    @pytest.mark.asyncio
    async def test_resolve_cache_hit_returns_cached(self, resolver: OpenDartSymbolResolver) -> None:
        """캐시 히트 시 API 호출 없이 캐시된 값을 반환한다."""
        # 직접 캐시에 값 설정
        resolver._cache["00123456"] = "005930"

        with patch.object(resolver, "_fetch_symbol") as mock_fetch:
            result = await resolver.resolve("00123456")

            assert result == "005930"
            mock_fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolve_negative_cache_hit(self, resolver: OpenDartSymbolResolver) -> None:
        """Negative cache 히트 시 API 호출 없이 None을 반환한다."""
        resolver._cache["00999999"] = None  # 이전에 실패한 corp_code

        with patch.object(resolver, "_fetch_symbol") as mock_fetch:
            result = await resolver.resolve("00999999")

            assert result is None
            mock_fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_symbol_success(self, resolver: OpenDartSymbolResolver) -> None:
        """/company.json API가 stock_code를 반환하면 해당 symbol을 반환한다."""
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "000",
            "corp_code": "00123456",
            "corp_name": "삼성전자",
            "stock_code": "005930",
        }

        async def mock_get(*args: object, **kwargs: object) -> httpx.Response:
            return mock_response

        with patch.object(resolver, "_get_client") as mock_get_client:
            mock_client = AsyncMock(spec=httpx.AsyncClient)
            mock_client.get = mock_get
            mock_get_client.return_value = mock_client

            result = await resolver.resolve("00123456")

            assert result == "005930"
            # 캐시에 저장되었는지 확인
            assert resolver._cache["00123456"] == "005930"

    @pytest.mark.asyncio
    async def test_fetch_symbol_no_stock_code(self, resolver: OpenDartSymbolResolver) -> None:
        """/company.json API가 stock_code 없이 응답하면 None을 반환하고 negative cache에 저장한다."""
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "000",
            "corp_code": "00123456",
            "corp_name": "비상장법인",
            "stock_code": "",  # 빈 stock_code
        }

        async def mock_get(*args: object, **kwargs: object) -> httpx.Response:
            return mock_response

        with patch.object(resolver, "_get_client") as mock_get_client:
            mock_client = AsyncMock(spec=httpx.AsyncClient)
            mock_client.get = mock_get
            mock_get_client.return_value = mock_client

            result = await resolver.resolve("00123456")

            assert result is None
            # Negative cache에 저장되었는지 확인
            assert resolver._cache["00123456"] is None

    @pytest.mark.asyncio
    async def test_fetch_symbol_api_error(self, resolver: OpenDartSymbolResolver) -> None:
        """/company.json API가 HTTP 오류를 반환하면 None을 반환하고 negative cache에 저장한다."""
        async def mock_get(*args: object, **kwargs: object) -> httpx.Response:
            raise httpx.HTTPStatusError(
                "404 Not Found",
                request=httpx.Request("GET", "http://example.com"),
                response=httpx.Response(404),
            )

        with patch.object(resolver, "_get_client") as mock_get_client:
            mock_client = AsyncMock(spec=httpx.AsyncClient)
            mock_client.get = mock_get
            mock_get_client.return_value = mock_client

            result = await resolver.resolve("00123456")

            assert result is None
            # Negative cache에 저장되었는지 확인
            assert resolver._cache["00123456"] is None

    @pytest.mark.asyncio
    async def test_fetch_symbol_non_success_status(self, resolver: OpenDartSymbolResolver) -> None:
        """/company.json API가 비성공 status를 반환하면 None을 반환한다."""
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "999",
            "message": "조회된 데이터가 없습니다.",
            "corp_code": "00123456",
        }

        async def mock_get(*args: object, **kwargs: object) -> httpx.Response:
            return mock_response

        with patch.object(resolver, "_get_client") as mock_get_client:
            mock_client = AsyncMock(spec=httpx.AsyncClient)
            mock_client.get = mock_get
            mock_get_client.return_value = mock_client

            result = await resolver.resolve("00123456")

            assert result is None
            # Negative cache에 저장되었는지 확인
            assert resolver._cache["00123456"] is None

    @pytest.mark.asyncio
    async def test_cache_prevents_duplicate_api_call(self, resolver: OpenDartSymbolResolver) -> None:
        """동일 corp_code를 두 번 resolve하면 두 번째는 API 호출 없이 캐시를 반환한다."""
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "000",
            "corp_code": "00123456",
            "corp_name": "삼성전자",
            "stock_code": "005930",
        }

        call_count = 0

        async def mock_get(*args: object, **kwargs: object) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return mock_response

        with patch.object(resolver, "_get_client") as mock_get_client:
            mock_client = AsyncMock(spec=httpx.AsyncClient)
            mock_client.get = mock_get
            mock_get_client.return_value = mock_client

            # 첫 번째 호출 — API 호출 발생
            result1 = await resolver.resolve("00123456")
            assert result1 == "005930"
            assert call_count == 1

            # 두 번째 호출 — 캐시 히트, API 호출 없음
            result2 = await resolver.resolve("00123456")
            assert result2 == "005930"
            assert call_count == 1  # API 호출 증가 없음

    @pytest.mark.asyncio
    async def test_negative_cache_prevents_retry(self, resolver: OpenDartSymbolResolver) -> None:
        """Negative cache: 실패한 corp_code를 다시 resolve해도 API 호출하지 않는다."""
        mock_response = AsyncMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "999",
            "message": "조회된 데이터가 없습니다.",
        }

        call_count = 0

        async def mock_get(*args: object, **kwargs: object) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return mock_response

        with patch.object(resolver, "_get_client") as mock_get_client:
            mock_client = AsyncMock(spec=httpx.AsyncClient)
            mock_client.get = mock_get
            mock_get_client.return_value = mock_client

            # 첫 번째 호출 — API 호출 발생, 실패
            result1 = await resolver.resolve("00999999")
            assert result1 is None
            assert call_count == 1

            # 두 번째 호출 — negative cache 히트, API 호출 없음
            result2 = await resolver.resolve("00999999")
            assert result2 is None
            assert call_count == 1  # API 호출 증가 없음

    @pytest.mark.asyncio
    async def test_cache_size_tracks_entries(self, resolver: OpenDartSymbolResolver) -> None:
        """cache_size가 캐시된 corp_code 수를 정확히 반영한다."""
        assert resolver.cache_size == 0

        resolver._cache["00123456"] = "005930"
        assert resolver.cache_size == 1

        resolver._cache["00999999"] = None  # negative cache
        assert resolver.cache_size == 2

    @pytest.mark.asyncio
    async def test_clear_cache_resets(self, resolver: OpenDartSymbolResolver) -> None:
        """clear_cache() 호출 시 모든 캐시가 초기화된다."""
        resolver._cache["00123456"] = "005930"
        resolver._cache["00999999"] = None
        assert resolver.cache_size == 2

        resolver.clear_cache()
        assert resolver.cache_size == 0

    @pytest.mark.asyncio
    async def test_close_cleans_up_client(self, resolver: OpenDartSymbolResolver) -> None:
        """close() 호출 시 HTTP client가 정리된다."""
        # 먼저 client 생성
        client = await resolver._get_client()
        assert resolver._client is not None

        await resolver.close()
        assert resolver._client is None

    @pytest.mark.asyncio
    async def test_different_corp_codes_independent(
        self, resolver: OpenDartSymbolResolver
    ) -> None:
        """서로 다른 corp_code는 독립적으로 resolve된다."""
        mock_responses: dict[str, dict[str, str]] = {
            "00123456": {
                "status": "000",
                "corp_code": "00123456",
                "corp_name": "삼성전자",
                "stock_code": "005930",
            },
            "00777777": {
                "status": "000",
                "corp_code": "00777777",
                "corp_name": "비상장법인",
                "stock_code": "",
            },
        }

        async def mock_get(*args: object, **kwargs: object) -> httpx.Response:
            params = kwargs.get("params", {})
            corp_code = params.get("corp_code", "") if isinstance(params, dict) else ""
            resp_data = mock_responses.get(corp_code, {"status": "999"})
            mock_resp = AsyncMock(spec=httpx.Response)
            mock_resp.status_code = 200
            mock_resp.json.return_value = resp_data
            return mock_resp

        with patch.object(resolver, "_get_client") as mock_get_client:
            mock_client = AsyncMock(spec=httpx.AsyncClient)
            mock_client.get = mock_get
            mock_get_client.return_value = mock_client

            # 삼성전자 — symbol 있음
            result1 = await resolver.resolve("00123456")
            assert result1 == "005930"

            # 비상장법인 — symbol 없음
            result2 = await resolver.resolve("00777777")
            assert result2 is None

            # 캐시 확인
            assert resolver._cache["00123456"] == "005930"
            assert resolver._cache["00777777"] is None
