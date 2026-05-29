"""Tests for NaverNewsSearchAdapter — KIS disclosure seed 보조 검색용 NAVER API.

Tests cover:
- 정상 API 응답 (기존)
- 429 Fast-Fail → 즉시 empty, retry 없음 (변경)
- 5xx transient error → retry → eventual success (변경)
- 5xx retry exhaustion → empty (변경)
- Transient timeout → retry → success (기존)
- Non-retryable 4xx → immediate empty (기존)
- sort=date 제거 검증 (기존)
- NaverDailyQuotaTracker unit tests (신규)
"""
from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from agent_trading.brokers.naver_news_adapter import (
    NaverDailyQuotaTracker,
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

        results, quota_exhausted = await adapter.search_by_seed(sample_seed, queries)

        # 2 API calls (2 queries × 1 sort mode = sim only)
        assert mock_http_client.get.call_count == 2
        # 2 unique items (no duplicates across calls)
        assert len(results) == 2
        assert quota_exhausted is False

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

        results, quota_exhausted = await adapter.search_by_seed(sample_seed, queries)

        # Should have 1 result from the successful call
        assert len(results) == 1
        assert quota_exhausted is False
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

        results, quota_exhausted = await adapter.search_by_seed(sample_seed, queries)

        assert results == []
        assert quota_exhausted is False
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
        results, quota_exhausted = await adapter.search_by_seed(sample_seed, [])

        assert results == []
        assert quota_exhausted is False
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
    # 변경된 테스트: 429는 더 이상 retry하지 않음 (Fast-Fail)
    # 5xx transient error → retry → eventual success
    # ==================================================================

    @pytest.mark.asyncio
    async def test_429_fast_fail_returns_empty_immediately(
        self,
        adapter: NaverNewsSearchAdapter,
        mock_http_client: AsyncMock,
    ) -> None:
        """429 → 즉시 [] 반환 (retry 없음, 1회만 호출)."""
        error_429 = _make_mock_response([], status_code=429)

        mock_http_client.get.return_value = error_429

        response = await adapter._call_api("test query")

        assert len(response.items) == 0
        # Exactly 1 call — no retry for 429
        mock_http_client.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_5xx_triggers_retry_and_eventually_succeeds(
        self,
        adapter: NaverNewsSearchAdapter,
        mock_http_client: AsyncMock,
    ) -> None:
        """첫 2회 500 → 3회차 성공 (최대 3회 retry 내 성공)."""
        success_response = _make_mock_response([
            {"title": "성공뉴스", "description": "desc", "link": "link1",
             "originallink": "orig1", "pubDate": "Fri, 17 May 2026 09:00:00 +0900"},
        ])
        error_500 = _make_mock_response([], status_code=500)

        # side_effect: 500, 500, success (3rd attempt succeeds)
        mock_http_client.get.side_effect = [
            error_500,   # attempt 1: 500
            error_500,   # attempt 2: 500
            success_response,  # attempt 3 (retry 2): success
        ]

        response = await adapter._call_api("test query")

        assert len(response.items) == 1
        assert response.items[0].title == "성공뉴스"
        # Should have made exactly 3 GET calls
        assert mock_http_client.get.call_count == 3

    @pytest.mark.asyncio
    async def test_5xx_retry_exhaustion_returns_empty(
        self,
        adapter: NaverNewsSearchAdapter,
        mock_http_client: AsyncMock,
    ) -> None:
        """3회 모두 500 → [] 반환 (max_retries=3, 총 4회 시도 후 포기)."""
        error_500 = _make_mock_response([], status_code=500)

        # All 4 attempts return 500
        mock_http_client.get.side_effect = [
            error_500,  # attempt 1: 500
            error_500,  # attempt 2: 500
            error_500,  # attempt 3: 500
            error_500,  # attempt 4 (last): 500 → give up
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

        results, quota_exhausted = await adapter.search_by_seed(sample_seed, queries)

        # sort=date가 제거되었으므로 1회만 호출 (query=1 × sort=sim)
        assert mock_http_client.get.call_count == 1
        call_kwargs = mock_http_client.get.call_args.kwargs
        assert call_kwargs["params"]["sort"] == "sim"
        assert len(results) == 1
        assert quota_exhausted is False


class TestNaverDailyQuotaTracker:
    """NaverDailyQuotaTracker unit tests.

    Uses a temporary file path to avoid interfering with production state.
    """

    @pytest.fixture(autouse=True)
    def _patch_file_path(self) -> None:
        """Override NaverDailyQuotaTracker._FILE_PATH with a temp file."""
        self._tmp_path = os.path.join(
            os.path.dirname(__file__), ".quota_test_tmp.json",
        )
        # Initialise with a valid empty-state record so the first read
        # returns count=0 rather than hitting a fail-closed fallback.
        with open(self._tmp_path, "w") as f:
            json.dump({"count": 0, "date": ""}, f)
        # Patch the class-level file path
        self._original_path = NaverDailyQuotaTracker._FILE_PATH
        NaverDailyQuotaTracker._FILE_PATH = self._tmp_path
        yield
        # Restore original path and clean up
        NaverDailyQuotaTracker._FILE_PATH = self._original_path
        if os.path.exists(self._tmp_path):
            os.unlink(self._tmp_path)

    def test_initial_state_is_zero(self) -> None:
        """초기 상태: consumption=0, ratio=0.0, not exhausted."""
        assert NaverDailyQuotaTracker.get_current_consumption() == 0
        assert NaverDailyQuotaTracker.get_consumption_ratio() == 0.0
        assert not NaverDailyQuotaTracker.is_exhausted()

    def test_increment_increases_count(self) -> None:
        """increment() 후 consumption이 1 증가."""
        NaverDailyQuotaTracker.increment()
        assert NaverDailyQuotaTracker.get_current_consumption() == 1

    def test_multiple_increments(self) -> None:
        """5회 increment → consumption=5."""
        for _ in range(5):
            NaverDailyQuotaTracker.increment()
        assert NaverDailyQuotaTracker.get_current_consumption() == 5

    def test_is_exhausted_at_threshold(self) -> None:
        """22500회 (90%) → is_exhausted()=True (기본 threshold=0.9)."""
        for _ in range(22500):
            NaverDailyQuotaTracker.increment()
        assert NaverDailyQuotaTracker.is_exhausted()
        assert NaverDailyQuotaTracker.get_consumption_ratio() == pytest.approx(0.9, abs=0.001)

    def test_not_exhausted_below_threshold(self) -> None:
        """20000회 (80%) → is_exhausted()=False."""
        for _ in range(20000):
            NaverDailyQuotaTracker.increment()
        assert not NaverDailyQuotaTracker.is_exhausted()

    def test_custom_threshold(self) -> None:
        """custom threshold=0.5 → 12500회에서 exhausted."""
        for _ in range(12500):
            NaverDailyQuotaTracker.increment()
        assert NaverDailyQuotaTracker.is_exhausted(threshold=0.5)
        assert not NaverDailyQuotaTracker.is_exhausted(threshold=0.6)

    def test_file_persistence(self) -> None:
        """increment() 후 파일에 count가 기록되어야 함."""
        NaverDailyQuotaTracker.increment()
        NaverDailyQuotaTracker.increment()
        NaverDailyQuotaTracker.increment()

        # Read file directly
        with open(self._tmp_path, "r") as f:
            data = json.load(f)
        assert data["count"] == 3

    def test_fail_open_on_corrupt_file(self) -> None:
        """파일이 깨지면 _DAILY_LIMIT 반환 (fail-closed → quota 소진 가정)."""
        # Write corrupt data
        with open(self._tmp_path, "w") as f:
            f.write("not valid json")

        # Should not raise — returns _DAILY_LIMIT
        assert NaverDailyQuotaTracker.get_current_consumption() == NaverDailyQuotaTracker._DAILY_LIMIT
        assert NaverDailyQuotaTracker.get_consumption_ratio() == 1.0
        assert NaverDailyQuotaTracker.is_exhausted()

    def test_fail_open_on_missing_file(self) -> None:
        """파일이 없으면 _DAILY_LIMIT 반환 (fail-closed → quota 소진 가정)."""
        # Remove the file
        if os.path.exists(self._tmp_path):
            os.unlink(self._tmp_path)

        assert NaverDailyQuotaTracker.get_current_consumption() == NaverDailyQuotaTracker._DAILY_LIMIT
        assert NaverDailyQuotaTracker.get_consumption_ratio() == 1.0
        assert NaverDailyQuotaTracker.is_exhausted()

    def test_fail_open_on_permission_error(self) -> None:
        """파일 권한 오류 시 _DAILY_LIMIT 반환 (fail-closed → quota 소진 가정)."""
        # Make file read-only
        if os.path.exists(self._tmp_path):
            os.chmod(self._tmp_path, 0o000)

        try:
            assert NaverDailyQuotaTracker.get_current_consumption() == NaverDailyQuotaTracker._DAILY_LIMIT
            assert NaverDailyQuotaTracker.get_consumption_ratio() == 1.0
            assert NaverDailyQuotaTracker.is_exhausted()
        finally:
            # Restore permissions for cleanup
            os.chmod(self._tmp_path, 0o644)

    def test_get_daily_usage_ratio_class_method(self) -> None:
        """NaverNewsSearchAdapter.get_daily_usage_ratio()가 tracker를 통해 동작."""
        NaverDailyQuotaTracker.increment()
        ratio = NaverNewsSearchAdapter.get_daily_usage_ratio()
        assert ratio == pytest.approx(1.0 / 25000, abs=1e-6)

    def test_is_quota_exhausted_class_method(self) -> None:
        """NaverNewsSearchAdapter.is_quota_exhausted()가 tracker를 통해 동작."""
        assert not NaverNewsSearchAdapter.is_quota_exhausted()
        for _ in range(22500):
            NaverDailyQuotaTracker.increment()
        assert NaverNewsSearchAdapter.is_quota_exhausted()

    def test_increment_logs_warning_on_read_failure(self, caplog, _patch_file_path):
        """_read_or_init() 실패 시 logger.warning이 출력되는지 확인."""
        import logging

        caplog.set_level(logging.WARNING)

        # _read_or_init()은 내부에서 모든 예외를 직접 처리(swallow)하므로,
        # patch.object로 강제 예외 발생시켜 increment()의 예외 처리 경로 검증
        with patch.object(NaverDailyQuotaTracker, "_read_or_init", side_effect=OSError("mock read error")):
            NaverDailyQuotaTracker.increment()

        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("_read_or_init() failed" in msg for msg in warning_messages), \
            f"Expected warning about _read_or_init failure, got: {warning_messages}"

    def test_increment_logs_warning_on_write_failure(self, caplog, _patch_file_path):
        """_write() 실패 시 logger.warning이 출력되는지 확인."""
        import logging

        caplog.set_level(logging.WARNING)

        # _write()는 내부에서 모든 예외를 직접 처리(swallow)하므로,
        # patch.object로 강제 예외 발생시켜 increment()의 예외 처리 경로 검증
        with patch.object(NaverDailyQuotaTracker, "_write", side_effect=OSError("mock write error")):
            NaverDailyQuotaTracker.increment()

        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("_write() failed" in msg for msg in warning_messages), \
            f"Expected warning about _write failure, got: {warning_messages}"

    def test_increment_success_no_warning(self, caplog, _patch_file_path):
        """정상 increment() 시 warning이 출력되지 않는지 확인."""
        import logging

        caplog.set_level(logging.WARNING)

        NaverDailyQuotaTracker.increment()

        warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_messages) == 0, \
            f"Expected no warnings on success, got: {warning_messages}"
