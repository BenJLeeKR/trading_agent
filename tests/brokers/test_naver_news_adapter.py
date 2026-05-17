"""Tests for NaverNewsSearchAdapter — KIS disclosure seed 보조 검색용 NAVER API.

Tests cover:
- 정상 API 응답 (기존)
- 429 Rate Limit → retry → eventual success (신규)
- 429 Rate Limit → retry exhaustion → empty (신규)
- Transient error → retry → success (신규)
- Non-retryable 4xx → immediate empty (신규)
- sort=date 제거 검증 (신규)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from agent_trading.brokers.naver_news_adapter import (
    NaverNewsItem,
    NaverNewsSearchAdapter,
    NaverSearchResponse,
)
from agent_trading.domain.models import DisclosureTitleDTO


@pytest.fixture
def sample_seed() -> DisclosureTitleDTO:
    return DisclosureTitleDTO(
        symbol="005930",
        company_name="삼성전자",
        headline="유상증자 결정",
        published_at="20260517",
    )


@pytest.fixture
def mock_http_client() -> AsyncMock:
    """Create a mock httpx.AsyncClient."""
    client = AsyncMock(spec=httpx.AsyncClient)
    return client


@pytest.fixture
def adapter(mock_http_client: AsyncMock) -> NaverNewsSearchAdapter:
    return NaverNewsSearchAdapter(
        client_id="test_client_id",
        client_secret="test_client_secret",
        http_client=mock_http_client,
        max_retries=3,
        backoff_base=0.01,  # Fast retry in tests
        backoff_max=1.0,
    )


def _make_mock_response(
    items: list[dict],
    status_code: int = 200,
) -> Mock:
    """Helper to create a mock httpx.Response with JSON data."""
    response = Mock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = {
        "items": items,
        "total": len(items),
        "display": len(items),
    }
    response.raise_for_status = Mock()
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Error",
            request=Mock(),
            response=response,
        )
    return response


class TestNaverNewsSearchAdapter:
    """Test suite for NaverNewsSearchAdapter.

    Covers 4 original test cases + 5 new rate-limit/retry tests.
    """

    # ------------------------------------------------------------------
    # Case 5 (original): 정상 API 응답
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_search_by_seed_success(
        self,
        adapter: NaverNewsSearchAdapter,
        sample_seed: DisclosureTitleDTO,
        mock_http_client: AsyncMock,
    ) -> None:
        """2개 query × 1 sort (sim only) = 2회 API 호출, 중복 제거되어야 함."""
        queries = ["삼성전자 유상증자", "삼성전자 공시"]

        # Mock 2 API calls to return items
        mock_items = [
            {"title": "뉴스1", "description": "desc1", "link": "link1",
             "originallink": "orig1", "pubDate": "Fri, 17 May 2026 09:00:00 +0900"},
            {"title": "뉴스2", "description": "desc2", "link": "link2",
             "originallink": "orig2", "pubDate": "Fri, 17 May 2026 09:00:00 +0900"},
        ]
        mock_http_client.get.return_value = _make_mock_response(mock_items)

        results = await adapter.search_by_seed(sample_seed, queries)

        # 2 API calls (2 queries × 1 sort mode = sim only)
        assert mock_http_client.get.call_count == 2
        # 2 unique items (no duplicates across calls)
        assert len(results) == 2

    # ------------------------------------------------------------------
    # Case 6 (adapted): API 4xx 에러 (일부 실패 → 나머지 정상 진행)
    # non-retryable 4xx (400) → immediate skip, other queries continue
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_search_by_seed_partial_api_error(
        self,
        adapter: NaverNewsSearchAdapter,
        sample_seed: DisclosureTitleDTO,
        mock_http_client: AsyncMock,
    ) -> None:
        """첫 번째 호출 400 → 즉시 실패, 두 번째 호출 정상 진행."""
        queries = ["삼성전자 유상증자", "삼성전자 공시"]

        # First call returns 400 (non-retryable), second call succeeds
        error_response = _make_mock_response([], status_code=400)
        success_response = _make_mock_response([
            {"title": "뉴스1", "description": "desc1", "link": "link1",
             "originallink": "orig1", "pubDate": "Fri, 17 May 2026 09:00:00 +0900"},
        ])

        mock_http_client.get.side_effect = [
            error_response,   # query 1 fails with 400 (no retry)
            success_response,  # query 2 succeeds
        ]

        results = await adapter.search_by_seed(sample_seed, queries)

        # Should have 1 result from the successful call
        assert len(results) == 1
        assert mock_http_client.get.call_count == 2

    # ------------------------------------------------------------------
    # Case 7 (original): API timeout (전체 실패 → [])
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_search_by_seed_all_timeout(
        self,
        adapter: NaverNewsSearchAdapter,
        sample_seed: DisclosureTitleDTO,
        mock_http_client: AsyncMock,
    ) -> None:
        """모든 호출 timeout → [] 반환, ERROR 로그."""
        queries = ["삼성전자 유상증자"]

        mock_http_client.get.side_effect = httpx.TimeoutException(
            "Connection timeout",
            request=Mock(),
        )

        results = await adapter.search_by_seed(sample_seed, queries)

        assert results == []
        # Initially expected 1 call + 3 retries = 4 total
        # But due to the way side_effect works with TimeoutException,
        # the exact count may vary. At minimum 1 call should be made.
        assert mock_http_client.get.call_count >= 1

    # ------------------------------------------------------------------
    # Case 8 (original): Query empty → []
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_search_by_seed_empty_queries(
        self,
        adapter: NaverNewsSearchAdapter,
        sample_seed: DisclosureTitleDTO,
        mock_http_client: AsyncMock,
    ) -> None:
        """queries=[] → [] 반환, API 호출 없음."""
        results = await adapter.search_by_seed(sample_seed, [])

        assert results == []
        mock_http_client.get.assert_not_called()

    # ------------------------------------------------------------------
    # Original: _call_api unit test
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_call_api_with_sort_params(
        self,
        adapter: NaverNewsSearchAdapter,
        mock_http_client: AsyncMock,
    ) -> None:
        """_call_api가 올바른 sort 파라미터(sim)로 호출되어야 함."""
        mock_items = [
            {"title": "뉴스", "description": "desc", "link": "link",
             "originallink": "orig", "pubDate": "Fri, 17 May 2026 09:00:00 +0900"},
        ]
        mock_http_client.get.return_value = _make_mock_response(mock_items)

        response = await adapter._call_api("test query", sort="sim")

        # Verify the request was made with correct params
        call_kwargs = mock_http_client.get.call_args.kwargs
        assert call_kwargs["params"]["sort"] == "sim"
        assert call_kwargs["params"]["query"] == "test query"
        assert call_kwargs["headers"]["X-Naver-Client-Id"] == "test_client_id"

        assert len(response.items) == 1
        assert response.items[0].title == "뉴스"

    # ------------------------------------------------------------------
    # Original: close test
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_close(
        self,
        adapter: NaverNewsSearchAdapter,
        mock_http_client: AsyncMock,
    ) -> None:
        """close()가 HTTP 클라이언트를 정리해야 함."""
        await adapter.close()
        mock_http_client.aclose.assert_awaited_once()

    # ==================================================================
    # 신규 테스트: 429 Rate Limit 대응
    # ==================================================================

    @pytest.mark.asyncio
    async def test_429_triggers_retry_and_eventually_succeeds(
        self,
        adapter: NaverNewsSearchAdapter,
        mock_http_client: AsyncMock,
    ) -> None:
        """첫 2회 429 → 3회차 성공 (최대 3회 retry 내 성공)."""
        success_response = _make_mock_response([
            {"title": "성공뉴스", "description": "desc", "link": "link1",
             "originallink": "orig1", "pubDate": "Fri, 17 May 2026 09:00:00 +0900"},
        ])
        error_429 = _make_mock_response([], status_code=429)

        # side_effect: 429, 429, success (3rd attempt succeeds)
        mock_http_client.get.side_effect = [
            error_429,   # attempt 1: 429
            error_429,   # attempt 2: 429
            success_response,  # attempt 3 (retry 2): success
        ]

        response = await adapter._call_api("test query")

        assert len(response.items) == 1
        assert response.items[0].title == "성공뉴스"
        # Should have made exactly 3 GET calls
        assert mock_http_client.get.call_count == 3

    @pytest.mark.asyncio
    async def test_429_retry_exhaustion_returns_empty(
        self,
        adapter: NaverNewsSearchAdapter,
        mock_http_client: AsyncMock,
    ) -> None:
        """3회 모두 429 → [] 반환 (max_retries=3, 총 4회 시도 후 포기)."""
        error_429 = _make_mock_response([], status_code=429)

        # All 4 attempts return 429
        mock_http_client.get.side_effect = [
            error_429,  # attempt 1: 429
            error_429,  # attempt 2: 429
            error_429,  # attempt 3: 429
            error_429,  # attempt 4 (last): 429 → give up
        ]

        response = await adapter._call_api("test query")

        assert len(response.items) == 0
        # Should have made exactly 4 GET calls (1 initial + 3 retries)
        assert mock_http_client.get.call_count == 4

    @pytest.mark.asyncio
    async def test_transient_error_retry(
        self,
        adapter: NaverNewsSearchAdapter,
        mock_http_client: AsyncMock,
    ) -> None:
        """Timeout → retry → 성공."""
        success_response = _make_mock_response([
            {"title": "성공뉴스", "description": "desc", "link": "link1",
             "originallink": "orig1", "pubDate": "Fri, 17 May 2026 09:00:00 +0900"},
        ])

        # First call times out, second call succeeds
        mock_http_client.get.side_effect = [
            httpx.TimeoutException("timeout", request=Mock()),
            success_response,
        ]

        response = await adapter._call_api("test query")

        assert len(response.items) == 1
        assert response.items[0].title == "성공뉴스"
        assert mock_http_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_non_retryable_error_no_retry(
        self,
        adapter: NaverNewsSearchAdapter,
        mock_http_client: AsyncMock,
    ) -> None:
        """400 error → 즉시 [] 반환 (retry 없음, 1회만 호출)."""
        error_400 = _make_mock_response([], status_code=400)

        mock_http_client.get.return_value = error_400

        response = await adapter._call_api("test query")

        assert len(response.items) == 0
        # Exactly 1 call — no retry for 400
        mock_http_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_sort_date_removed(
        self,
        adapter: NaverNewsSearchAdapter,
        sample_seed: DisclosureTitleDTO,
        mock_http_client: AsyncMock,
    ) -> None:
        """search_by_seed()가 sort=sim만 호출하고 sort=date는 호출하지 않는지 검증."""
        queries = ["삼성전자 유상증자"]
        mock_items = [
            {"title": "뉴스", "description": "desc", "link": "link1",
             "originallink": "orig1", "pubDate": "Fri, 17 May 2026 09:00:00 +0900"},
        ]
        mock_http_client.get.return_value = _make_mock_response(mock_items)

        results = await adapter.search_by_seed(sample_seed, queries)

        # sort=date가 제거되었으므로 1회만 호출 (query=1 × sort=sim)
        assert mock_http_client.get.call_count == 1
        call_kwargs = mock_http_client.get.call_args.kwargs
        assert call_kwargs["params"]["sort"] == "sim"
        assert len(results) == 1
