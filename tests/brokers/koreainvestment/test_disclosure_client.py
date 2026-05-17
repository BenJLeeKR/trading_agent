"""Tests for KIS live disclosure client + LiveDisclosureSeedService.

Phase P-1c/d/e: 7 test cases covering:
1. Live credential 정상 → client 생성 성공
2. Live credential 미제공 → client=None
3. client=None 상태 fetch → []
4. API 정상 응답 → DTO 정규화
5. API empty 응답 → [] (hard fail ❌)
6. BrokerError 발생 → [] (graceful fallback)
7. Cache 메커니즘 재사용 확인
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.services.disclosure_seed_service import LiveDisclosureSeedService
from agent_trading.domain.models import DisclosureTitleDTO


class TestDisclosureClientCreation:
    """Live credential 정상/부재 시 client 생성 검증."""

    def test_credential_present_creates_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """1. Live credential 정상 → client 생성 성공"""
        monkeypatch.setenv("KIS_LIVE_INFO_APP_KEY", "test-live-key")
        monkeypatch.setenv("KIS_LIVE_INFO_APP_SECRET", "test-live-secret")

        from agent_trading.config.settings import AppSettings
        from agent_trading.runtime.bootstrap import _build_live_disclosure_client

        settings = AppSettings()  # monkeypatch된 env var 읽음
        client = _build_live_disclosure_client(settings)
        assert client is not None
        assert client.env == "live"

    def test_credential_missing_returns_none(self) -> None:
        """2. Live credential 미제공 → client=None"""
        from agent_trading.config.settings import AppSettings
        from agent_trading.runtime.bootstrap import _build_live_disclosure_client

        settings = AppSettings(kis_live_app_key=None, kis_live_app_secret=None)
        client = _build_live_disclosure_client(settings)
        assert client is None


class TestDisclosureSeedService:
    """LiveDisclosureSeedService fallback/정규화 검증."""

    async def test_client_none_returns_empty(self) -> None:
        """3. client=None 상태 fetch → []"""
        service = LiveDisclosureSeedService(client=None)
        result = await service.fetch_disclosure_titles(["005930"])
        assert result == []

    async def test_api_returns_items(self) -> None:
        """4. API 정상 응답 → DTO 정규화"""
        mock_client = AsyncMock(spec=KISRestClient)
        mock_client.get_disclosure_news_title.return_value = [
            {"hts_pbnt_titl_cntt": "유상증자 결정", "kor_isnm1": "삼성전자"},
        ]

        service = LiveDisclosureSeedService(client=mock_client)
        result = await service.fetch_disclosure_titles(["005930"])

        assert len(result) == 1
        assert result[0].symbol == "005930"
        assert result[0].headline == "유상증자 결정"
        assert result[0].company_name == "삼성전자"
        assert result[0].source == "kis_disclosure_live"

    async def test_api_empty_returns_empty(self) -> None:
        """5. API empty 응답 → [] (hard fail ❌)"""
        mock_client = AsyncMock(spec=KISRestClient)
        mock_client.get_disclosure_news_title.return_value = []

        service = LiveDisclosureSeedService(client=mock_client)
        result = await service.fetch_disclosure_titles(["005930"])
        assert result == []

    async def test_api_error_returns_empty(self) -> None:
        """6. BrokerError 발생 → [] (graceful fallback)"""
        mock_client = AsyncMock(spec=KISRestClient)
        mock_client.get_disclosure_news_title.side_effect = RuntimeError("API failure")

        service = LiveDisclosureSeedService(client=mock_client)
        result = await service.fetch_disclosure_titles(["005930"])
        assert result == []

    def test_cache_mechanism_reuse(self) -> None:
        """7. Cache 메커니즘 재사용 확인 — dev_token_cache_path 파라미터"""
        client = KISRestClient(
            env="live",
            api_key="test-key",
            api_secret="test-secret",
            account_number="",
            account_product_code="",
            dev_token_cache_path=".cache/kis_test_disclosure.json",
            dev_token_cache_enabled=True,
        )
        assert client.dev_token_cache_path == ".cache/kis_test_disclosure.json"
        assert client.dev_token_cache_enabled is True
