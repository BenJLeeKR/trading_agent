"""Tests for NaverNewsSearchAdapter — KIS disclosure seed 보조 검색용 NAVER API."""
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

    Covers 4 test cases from the Phase P-2b test plan:
    5. 정상 API 응답
    6. API 4xx/5xx 에러 (일부 실패)
    7. API timeout (전체 실패)
    8. Query empty
    """

    # ------------------------------------------------------------------
    # Case 5: 정상 API 응답
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_search_by_seed_success(
        self,
        adapter: NaverNewsSearchAdapter,
        sample_seed: DisclosureTitleDTO,
        mock_http_client: AsyncMock,
    ) -> None:
        """2개 query × 2 sort = 4회 API 호출, 중복 제거되어야 함."""
        queries = ["삼성전자 유상증자", "삼성전자 공시"]

        # Mock 4 API calls to return items
        mock_items = [
            {"title": "뉴스1", "description": "desc1", "link": "link1",
             "originallink": "orig1", "pubDate": "Fri, 17 May 2026 09:00:00 +0900"},
            {"title": "뉴스2", "description": "desc2", "link": "link2",
             "originallink": "orig2", "pubDate": "Fri, 17 May 2026 09:00:00 +0900"},
        ]
        mock_http_client.get.return_value = _make_mock_response(mock_items)

        results = await adapter.search_by_seed(sample_seed, queries)

        # 4 API calls (2 queries × 2 sort modes)
        assert mock_http_client.get.call_count == 4
        # 2 unique items (no duplicates across calls)
        assert len(results) == 2

    # ------------------------------------------------------------------
    # Case 6: API 4xx/5xx 에러 (일부 실패 → 나머지 정상 진행)
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_search_by_seed_partial_api_error(
        self,
        adapter: NaverNewsSearchAdapter,
        sample_seed: DisclosureTitleDTO,
        mock_http_client: AsyncMock,
    ) -> None:
        """첫 번째 호출 429 → 나머지 호출 정상 진행, ERROR 로그."""
        queries = ["삼성전자 유상증자"]

        # First call fails with 429
        error_response = _make_mock_response([], status_code=429)
        success_response = _make_mock_response([
            {"title": "뉴스1", "description": "desc1", "link": "link1",
             "originallink": "orig1", "pubDate": "Fri, 17 May 2026 09:00:00 +0900"},
        ])

        mock_http_client.get.side_effect = [
            error_response,  # sort=sim fails
            success_response,  # sort=date succeeds
        ]

        results = await adapter.search_by_seed(sample_seed, queries)

        # Should have 1 result from the successful call
        assert len(results) == 1
        assert mock_http_client.get.call_count == 2

    # ------------------------------------------------------------------
    # Case 7: API timeout (전체 실패 → [])
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
        assert mock_http_client.get.call_count >= 1

    # ------------------------------------------------------------------
    # Case 8: Query empty → []
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
    # Additional: _call_api unit test
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_call_api_with_sort_params(
        self,
        adapter: NaverNewsSearchAdapter,
        mock_http_client: AsyncMock,
    ) -> None:
        """_call_api가 올바른 sort 파라미터로 호출되어야 함."""
        mock_items = [
            {"title": "뉴스", "description": "desc", "link": "link",
             "originallink": "orig", "pubDate": "Fri, 17 May 2026 09:00:00 +0900"},
        ]
        mock_http_client.get.return_value = _make_mock_response(mock_items)

        response = await adapter._call_api("test query", sort="date")

        # Verify the request was made with correct params
        call_kwargs = mock_http_client.get.call_args.kwargs
        assert call_kwargs["params"]["sort"] == "date"
        assert call_kwargs["params"]["query"] == "test query"
        assert call_kwargs["headers"]["X-Naver-Client-Id"] == "test_client_id"

        assert len(response.items) == 1
        assert response.items[0].title == "뉴스"

    # ------------------------------------------------------------------
    # Additional: close test
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
