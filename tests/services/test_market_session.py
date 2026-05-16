"""Tests for ``MarketSessionProvider`` (거래일/장운영 정보 추상화 레이어).

Test scope:
1. KisHolidayProvider: opnd_yn=Y → is_trading_day=True
2. KisHolidayProvider: opnd_yn=N → is_trading_day=False
3. FallbackSessionProvider: 평일 → True
4. FallbackSessionProvider: 주말 → False
5. KisHolidayProvider 실패 → 예외 전파 (호출자에서 fallback)
6. KisHolidayProvider 캐싱 (1일 1회 호출 정책)
7. ``create_session_provider()`` factory
"""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_trading.brokers.koreainvestment.holiday_client import (
    KISHolidayClient,
    KISHolidayError,
    HolidayStatus,
)
from agent_trading.brokers.koreainvestment.market_state_client import (
    MarketPhaseCode,
    MarketState,
    MarketStateProvider,
)
from agent_trading.services.market_session import (
    CombinedSessionProvider,
    FallbackSessionProvider,
    KisHolidayProvider,
    MarketSessionProvider,
    SessionInfo,
    create_session_provider,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_holiday_client() -> KISHolidayClient:
    """Mocked KISHolidayClient."""
    client = MagicMock(spec=KISHolidayClient)
    client.get_holiday_status = AsyncMock()
    return client  # type: ignore[return-value]


@pytest.fixture
def kis_provider(mock_holiday_client: KISHolidayClient) -> KisHolidayProvider:
    return KisHolidayProvider(holiday_client=mock_holiday_client)


# ---------------------------------------------------------------------------
# KisHolidayProvider — success scenarios
# ---------------------------------------------------------------------------


class TestKisHolidayProvider:
    """076 API 기반 거래일 제공자."""

    @pytest.mark.asyncio
    async def test_trading_day_true(
        self,
        kis_provider: KisHolidayProvider,
        mock_holiday_client: KISHolidayClient,
    ) -> None:
        """opnd_yn=Y → is_trading_day()=True."""
        mock_holiday_client.get_holiday_status.return_value = HolidayStatus(
            bass_dt="20260516",
            wday_dvsn_cd="03",
            bzdy_yn="Y",
            tr_day_yn="Y",
            opnd_yn="Y",
            sttl_day_yn="Y",
        )
        result = await kis_provider.is_trading_day(date(2026, 5, 16))
        assert result is True

    @pytest.mark.asyncio
    async def test_trading_day_false(
        self,
        kis_provider: KisHolidayProvider,
        mock_holiday_client: KISHolidayClient,
    ) -> None:
        """opnd_yn=N → is_trading_day()=False."""
        mock_holiday_client.get_holiday_status.return_value = HolidayStatus(
            bass_dt="20260516",
            wday_dvsn_cd="01",
            bzdy_yn="N",
            tr_day_yn="N",
            opnd_yn="N",
            sttl_day_yn="N",
        )
        result = await kis_provider.is_trading_day(date(2026, 5, 16))
        assert result is False

    @pytest.mark.asyncio
    async def test_get_session_info_returns_source(
        self,
        kis_provider: KisHolidayProvider,
        mock_holiday_client: KISHolidayClient,
    ) -> None:
        """get_session_info() returns kis_holiday_api source."""
        mock_holiday_client.get_holiday_status.return_value = HolidayStatus(
            bass_dt="20260516",
            wday_dvsn_cd="03",
            bzdy_yn="Y",
            tr_day_yn="Y",
            opnd_yn="Y",
            sttl_day_yn="Y",
        )
        info = await kis_provider.get_session_info(date(2026, 5, 16))
        assert info.source == "kis_holiday_api"
        assert info.is_trading_day is True
        assert info.opnd_yn == "Y"
        assert info.bzdy_yn == "Y"
        assert info.tr_day_yn == "Y"

    @pytest.mark.asyncio
    async def test_caching_same_date(
        self,
        kis_provider: KisHolidayProvider,
        mock_holiday_client: KISHolidayClient,
    ) -> None:
        """Same date → API 호출 1회 (캐싱)."""
        mock_holiday_client.get_holiday_status.return_value = HolidayStatus(
            bass_dt="20260516",
            wday_dvsn_cd="03",
            bzdy_yn="Y",
            tr_day_yn="Y",
            opnd_yn="Y",
            sttl_day_yn="Y",
        )

        # First call
        await kis_provider.get_session_info(date(2026, 5, 16))
        assert mock_holiday_client.get_holiday_status.call_count == 1

        # Second call — same date, should use cache
        await kis_provider.get_session_info(date(2026, 5, 16))
        assert mock_holiday_client.get_holiday_status.call_count == 1  # no extra call

    @pytest.mark.asyncio
    async def test_no_cache_different_date(
        self,
        kis_provider: KisHolidayProvider,
        mock_holiday_client: KISHolidayClient,
    ) -> None:
        """Different date → 별도 API 호출."""
        mock_holiday_client.get_holiday_status.return_value = HolidayStatus(
            bass_dt="20260516",
            wday_dvsn_cd="03",
            bzdy_yn="Y",
            tr_day_yn="Y",
            opnd_yn="Y",
            sttl_day_yn="Y",
        )

        await kis_provider.get_session_info(date(2026, 5, 16))
        await kis_provider.get_session_info(date(2026, 5, 17))
        assert mock_holiday_client.get_holiday_status.call_count == 2

    @pytest.mark.asyncio
    async def test_api_failure_propagates(
        self,
        kis_provider: KisHolidayProvider,
        mock_holiday_client: KISHolidayClient,
    ) -> None:
        """API 실패 → KISHolidayError 전파 (호출자에서 fallback 처리)."""
        mock_holiday_client.get_holiday_status.side_effect = KISHolidayError(
            "API failure",
        )
        with pytest.raises(KISHolidayError):
            await kis_provider.get_session_info(date(2026, 5, 16))

    @pytest.mark.asyncio
    async def test_is_trading_day_caches_session_info(
        self,
        kis_provider: KisHolidayProvider,
        mock_holiday_client: KISHolidayClient,
    ) -> None:
        """is_trading_day() → session info 캐싱됨 (get_session_info 재사용 가능)."""
        mock_holiday_client.get_holiday_status.return_value = HolidayStatus(
            bass_dt="20260516",
            wday_dvsn_cd="03",
            bzdy_yn="Y",
            tr_day_yn="Y",
            opnd_yn="Y",
            sttl_day_yn="Y",
        )

        result = await kis_provider.is_trading_day(date(2026, 5, 16))
        assert result is True

        # get_session_info should use cache now
        info = await kis_provider.get_session_info(date(2026, 5, 16))
        assert info.is_trading_day is True
        assert info.source == "kis_holiday_api"
        assert mock_holiday_client.get_holiday_status.call_count == 1  # cached


# ---------------------------------------------------------------------------
# FallbackSessionProvider
# ---------------------------------------------------------------------------


class TestFallbackSessionProvider:
    """주말 heuristic 기반 fallback."""

    @pytest.fixture
    def fallback(self) -> FallbackSessionProvider:
        return FallbackSessionProvider()

    @pytest.mark.asyncio
    async def test_weekday_is_trading_day(
        self,
        fallback: FallbackSessionProvider,
    ) -> None:
        """평일(월~금) → 거래일."""
        # 2026-05-18 = Monday
        assert await fallback.is_trading_day(date(2026, 5, 18)) is True
        # 2026-05-19 = Tuesday
        assert await fallback.is_trading_day(date(2026, 5, 19)) is True
        # 2026-05-22 = Friday
        assert await fallback.is_trading_day(date(2026, 5, 22)) is True

    @pytest.mark.asyncio
    async def test_weekend_not_trading_day(
        self,
        fallback: FallbackSessionProvider,
    ) -> None:
        """주말(토~일) → 비거래일."""
        # 2026-05-16 = Saturday
        assert await fallback.is_trading_day(date(2026, 5, 16)) is False
        # 2026-05-17 = Sunday
        assert await fallback.is_trading_day(date(2026, 5, 17)) is False
        # 2026-05-23 = Saturday
        assert await fallback.is_trading_day(date(2026, 5, 23)) is False

    @pytest.mark.asyncio
    async def test_session_info_source(
        self,
        fallback: FallbackSessionProvider,
    ) -> None:
        """SessionInfo.source == 'fallback'."""
        info = await fallback.get_session_info(date(2026, 5, 18))
        assert info.source == "fallback"
        assert info.is_trading_day is True

        info_weekend = await fallback.get_session_info(date(2026, 5, 16))
        assert info_weekend.source == "fallback"
        assert info_weekend.is_trading_day is False
        assert "주말" in info_weekend.reason


# ---------------------------------------------------------------------------
# Provider chaining (factory)
# ---------------------------------------------------------------------------


class TestCreateSessionProvider:
    """``create_session_provider()`` factory."""

    @pytest.mark.asyncio
    async def test_fallback_when_disabled(self) -> None:
        """KIS_LIVE_INFO_ENABLED=false → FallbackSessionProvider."""
        with patch.dict("os.environ", {
            "KIS_LIVE_INFO_ENABLED": "false",
        }, clear=False):
            provider = await create_session_provider()
            assert isinstance(provider, FallbackSessionProvider)

    @pytest.mark.asyncio
    async def test_fallback_when_missing_credentials(self) -> None:
        """KIS_LIVE_INFO_ENABLED=true but missing credentials → FallbackSessionProvider."""
        with patch.dict("os.environ", {
            "KIS_LIVE_INFO_ENABLED": "true",
            "KIS_LIVE_INFO_APP_KEY": "",
            "KIS_LIVE_INFO_APP_SECRET": "",
        }, clear=False):
            provider = await create_session_provider()
            assert isinstance(provider, FallbackSessionProvider)

    @pytest.mark.asyncio
    async def test_kis_provider_when_configured(self) -> None:
        """KIS_LIVE_INFO_ENABLED=true + credentials → KisHolidayProvider."""
        with patch.dict("os.environ", {
            "KIS_LIVE_INFO_ENABLED": "true",
            "KIS_LIVE_INFO_APP_KEY": "test-key",
            "KIS_LIVE_INFO_APP_SECRET": "test-secret",
            "KIS_LIVE_INFO_BASE_URL": "https://api.test.com:9443",
        }, clear=False):
            provider = await create_session_provider()
            assert isinstance(provider, KisHolidayProvider)

    @pytest.mark.asyncio
    async def test_kis_provider_default_base_url(self) -> None:
        """KIS_LIVE_INFO_BASE_URL 미설정 → 기본 실전 URL 사용."""
        with patch.dict("os.environ", {
            "KIS_LIVE_INFO_ENABLED": "true",
            "KIS_LIVE_INFO_APP_KEY": "test-key",
            "KIS_LIVE_INFO_APP_SECRET": "test-secret",
        }, clear=False):
            provider = await create_session_provider()
            assert isinstance(provider, KisHolidayProvider)
            # Check the default base URL was used
            assert provider._client._base_url == "https://openapi.koreainvestment.com:9443"


# ---------------------------------------------------------------------------
# ABC compliance
# ---------------------------------------------------------------------------


class TestMarketSessionProviderABC:
    """ABC 인터페이스 준수."""

    def test_cannot_instantiate_abc(self) -> None:
        """MarketSessionProvider 직접 인스턴스화 불가."""
        with pytest.raises(TypeError):
            MarketSessionProvider()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# CombinedSessionProvider (P2: 076 + 163 WebSocket 통합)
# ---------------------------------------------------------------------------


class TestCombinedSessionProvider:
    """``CombinedSessionProvider`` — 076 + 163 통합 phase 결정 로직."""

    @pytest.fixture
    def mock_holiday_provider(self) -> MagicMock:
        """076 holiday provider mock — 기본 opnd_yn=Y."""
        provider = MagicMock(spec=MarketSessionProvider)
        provider.get_session_info = AsyncMock(return_value=SessionInfo(
            is_trading_day=True,
            opnd_yn="Y",
            bzdy_yn="Y",
            tr_day_yn="Y",
            source="kis_holiday_api",
            reason="test",
        ))
        return provider

    @pytest.fixture
    def mock_market_state_provider(self) -> MagicMock:
        """163 market state provider mock — 기본 OPEN."""
        provider = MagicMock(spec=MarketStateProvider)
        provider.get_current_state = AsyncMock(return_value=MarketState(
            timestamp=datetime.now(),
            mkop_cls_code="1",
            phase=MarketPhaseCode.OPEN,
        ))
        provider.is_connected = True
        return provider

    # --- Phase decision logic tests ---

    @pytest.mark.asyncio
    async def test_trading_day_when_open(
        self,
        mock_holiday_provider: MagicMock,
        mock_market_state_provider: MagicMock,
    ) -> None:
        """076 opnd_yn=Y + 163 OPEN → is_trading_day=True."""
        combined = CombinedSessionProvider(
            holiday_provider=mock_holiday_provider,
            market_state_provider=mock_market_state_provider,
        )
        info = await combined.get_session_info(date(2026, 5, 18))
        assert info.is_trading_day is True
        assert info.market_phase == MarketPhaseCode.OPEN.value
        assert info.source == "combined"

    @pytest.mark.asyncio
    async def test_trading_day_when_closing(
        self,
        mock_holiday_provider: MagicMock,
        mock_market_state_provider: MagicMock,
    ) -> None:
        """076 opnd_yn=Y + 163 CLOSING → is_trading_day=True."""
        mock_market_state_provider.get_current_state = AsyncMock(return_value=MarketState(
            timestamp=datetime.now(),
            mkop_cls_code="2",
            phase=MarketPhaseCode.CLOSING,
        ))
        combined = CombinedSessionProvider(
            holiday_provider=mock_holiday_provider,
            market_state_provider=mock_market_state_provider,
        )
        info = await combined.get_session_info(date(2026, 5, 18))
        assert info.is_trading_day is True
        assert info.market_phase == MarketPhaseCode.CLOSING.value

    @pytest.mark.asyncio
    async def test_trading_day_when_pre_market(
        self,
        mock_holiday_provider: MagicMock,
        mock_market_state_provider: MagicMock,
    ) -> None:
        """076 opnd_yn=Y + 163 PRE_MARKET → is_trading_day=True."""
        mock_market_state_provider.get_current_state = AsyncMock(return_value=MarketState(
            timestamp=datetime.now(),
            mkop_cls_code="0",
            phase=MarketPhaseCode.PRE_MARKET,
        ))
        combined = CombinedSessionProvider(
            holiday_provider=mock_holiday_provider,
            market_state_provider=mock_market_state_provider,
        )
        info = await combined.get_session_info(date(2026, 5, 18))
        assert info.is_trading_day is True
        assert info.market_phase == MarketPhaseCode.PRE_MARKET.value

    @pytest.mark.asyncio
    async def test_trading_day_when_after_hours(
        self,
        mock_holiday_provider: MagicMock,
        mock_market_state_provider: MagicMock,
    ) -> None:
        """076 opnd_yn=Y + 163 AFTER_HOURS → is_trading_day=True (after-hours 허용)."""
        mock_market_state_provider.get_current_state = AsyncMock(return_value=MarketState(
            timestamp=datetime.now(),
            mkop_cls_code="3",
            phase=MarketPhaseCode.AFTER_HOURS,
        ))
        combined = CombinedSessionProvider(
            holiday_provider=mock_holiday_provider,
            market_state_provider=mock_market_state_provider,
        )
        info = await combined.get_session_info(date(2026, 5, 18))
        assert info.is_trading_day is True
        assert info.market_phase == MarketPhaseCode.AFTER_HOURS.value

    # --- Safe mode tests ---

    @pytest.mark.asyncio
    async def test_safe_mode_when_halt(
        self,
        mock_holiday_provider: MagicMock,
        mock_market_state_provider: MagicMock,
    ) -> None:
        """076 opnd_yn=Y + 163 HALT → is_trading_day=False (safe mode)."""
        mock_market_state_provider.get_current_state = AsyncMock(return_value=MarketState(
            timestamp=datetime.now(),
            mkop_cls_code="4",
            phase=MarketPhaseCode.HALT,
        ))
        combined = CombinedSessionProvider(
            holiday_provider=mock_holiday_provider,
            market_state_provider=mock_market_state_provider,
        )
        info = await combined.get_session_info(date(2026, 5, 18))
        assert info.is_trading_day is False
        assert "safe mode" in (info.reason or "").lower()

    @pytest.mark.asyncio
    async def test_safe_mode_when_unknown(
        self,
        mock_holiday_provider: MagicMock,
        mock_market_state_provider: MagicMock,
    ) -> None:
        """076 opnd_yn=Y + 163 UNKNOWN → is_trading_day=False (safe mode)."""
        mock_market_state_provider.get_current_state = AsyncMock(return_value=MarketState(
            timestamp=datetime.now(),
            mkop_cls_code="",
            phase=MarketPhaseCode.UNKNOWN,
        ))
        combined = CombinedSessionProvider(
            holiday_provider=mock_holiday_provider,
            market_state_provider=mock_market_state_provider,
        )
        info = await combined.get_session_info(date(2026, 5, 18))
        assert info.is_trading_day is False
        assert "safe mode" in (info.reason or "").lower()

    # --- 076 blocks regardless of 163 ---

    @pytest.mark.asyncio
    async def test_076_opnd_n_blocks_even_when_open(
        self,
        mock_holiday_provider: MagicMock,
        mock_market_state_provider: MagicMock,
    ) -> None:
        """076 opnd_yn=N → 163 OPEN이어도 is_trading_day=False."""
        mock_holiday_provider.get_session_info = AsyncMock(return_value=SessionInfo(
            is_trading_day=False,
            opnd_yn="N",
            bzdy_yn="N",
            tr_day_yn="N",
            source="kis_holiday_api",
            reason="non-trading day",
        ))
        combined = CombinedSessionProvider(
            holiday_provider=mock_holiday_provider,
            market_state_provider=mock_market_state_provider,
        )
        info = await combined.get_session_info(date(2026, 5, 18))
        assert info.is_trading_day is False
        # Reason should mention 076
        assert "076" in (info.reason or "")

    # --- 163 not connected fallback ---

    @pytest.mark.asyncio
    async def test_fallback_when_ws_not_connected(
        self,
        mock_holiday_provider: MagicMock,
    ) -> None:
        """163 WS 미연결 → 076 판단만 사용."""
        provider = MagicMock(spec=MarketStateProvider)
        provider.is_connected = False
        # Even though is_connected is False, get_current_state should not raise
        provider.get_current_state = AsyncMock(return_value=MarketState(
            timestamp=datetime.now(),
            mkop_cls_code="",
            phase=MarketPhaseCode.UNKNOWN,
        ))
        combined = CombinedSessionProvider(
            holiday_provider=mock_holiday_provider,
            market_state_provider=provider,
        )
        info = await combined.get_session_info(date(2026, 5, 18))
        assert info.is_trading_day is True  # 076 says Y
        assert info.market_phase is None  # WS not available
        assert "163 WS" in (info.reason or "")

    # --- 076 provider error handling ---

    @pytest.mark.asyncio
    async def test_076_error_fallback(
        self,
        mock_market_state_provider: MagicMock,
    ) -> None:
        """076 provider 오류 → conservatively block (source=combined)."""
        error_provider = MagicMock(spec=MarketSessionProvider)
        error_provider.get_session_info = AsyncMock(side_effect=RuntimeError("API unavailable"))

        combined = CombinedSessionProvider(
            holiday_provider=error_provider,
            market_state_provider=mock_market_state_provider,
        )
        info = await combined.get_session_info(date(2026, 5, 18))
        # 076 error → conservative block even though 163 says OPEN
        assert info.is_trading_day is False
        assert info.source == "combined"
        assert "076" in (info.reason or "")

    # --- 163 provider error handling ---

    @pytest.mark.asyncio
    async def test_163_error_fallback_to_076(
        self,
        mock_holiday_provider: MagicMock,
    ) -> None:
        """163 provider 오류 → 076 판단만 사용."""
        error_provider = MagicMock(spec=MarketStateProvider)
        error_provider.is_connected = True
        error_provider.get_current_state = AsyncMock(side_effect=RuntimeError("WS unavailable"))

        combined = CombinedSessionProvider(
            holiday_provider=mock_holiday_provider,
            market_state_provider=error_provider,
        )
        info = await combined.get_session_info(date(2026, 5, 18))
        # 076 says Y, 163 error → fallback to 076
        assert info.is_trading_day is True
