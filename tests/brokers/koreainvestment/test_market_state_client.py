"""Tests for KisMarketStateClient — 163 WebSocket client."""
from __future__ import annotations as _annotations

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent_trading.brokers.koreainvestment.market_state_client import (
    KisMarketStateClient,
    MarketPhaseCode,
    MarketState,
)
from agent_trading.config.settings import AppSettings


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_settings_paper() -> MagicMock:
    """Paper env용 Mock AppSettings."""
    settings = MagicMock(spec=AppSettings)
    settings.kis_env = "paper"
    settings.kis_live_info_enabled = True
    settings.kis_live_token_cache_enabled = False
    settings.kis_live_token_cache_path = ".cache/kis_live_token.json"
    settings.kis_live_info_ws_url = ""
    settings.kis_base_ws_url = ""
    settings.kis_real_rest_base_url = ""
    return settings


@pytest.fixture
def mock_settings_live() -> MagicMock:
    """Live env용 Mock AppSettings."""
    settings = MagicMock(spec=AppSettings)
    settings.kis_env = "live"
    settings.kis_live_info_enabled = True
    settings.kis_live_token_cache_enabled = False
    settings.kis_live_token_cache_path = ".cache/kis_live_token.json"
    settings.kis_live_info_ws_url = ""
    settings.kis_base_ws_url = ""
    settings.kis_real_rest_base_url = "https://api.kis.com:9443"
    return settings


@pytest.fixture
def paper_client(mock_settings_paper: MagicMock) -> KisMarketStateClient:
    """Paper env KisMarketStateClient fixture."""
    return KisMarketStateClient(
        settings=mock_settings_paper,
        app_key="paper-key",
        api_secret="paper-secret",
    )


@pytest.fixture
def live_client(mock_settings_live: MagicMock) -> KisMarketStateClient:
    """Live env KisMarketStateClient fixture."""
    return KisMarketStateClient(
        settings=mock_settings_live,
        app_key="live-key",
        api_secret="live-secret",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_h0unmko0_message(
    mkop_cls_code: str = "1",
    antc_mkop_cls_code: str = "2",
    vi_cls_code: str = "0",
    trht_yn: str = "N",
    exch_cls_code: str = "KRX",
) -> dict:
    """H0UNMKO0 WebSocket 메시지 생성 헬퍼."""
    return {
        "header": {"tr_id": "H0UNMKO0"},
        "body": {
            "mkop_cls_code": mkop_cls_code,
            "antc_mkop_cls_code": antc_mkop_cls_code,
            "vi_cls_code": vi_cls_code,
            "trht_yn": trht_yn,
            "exch_cls_code": exch_cls_code,
        },
    }


class MockMarketStateListener:
    """Mock listener that records calls."""

    def __init__(self) -> None:
        self.calls: list[MarketState] = []

    async def on_market_state_changed(self, state: MarketState) -> None:
        self.calls.append(state)


# ===========================================================================
# Test 1: Paper env에서 connect() skip + warning log
# ===========================================================================


class TestPaperEnv:
    """Paper/mock/sandbox 환경 검증."""

    @pytest.mark.asyncio
    async def test_paper_env_skips_connect(
        self, paper_client: KisMarketStateClient
    ) -> None:
        """Paper env에서는 connect()가 early return해야 함."""
        await paper_client.connect()
        assert paper_client.is_connected is False

    @pytest.mark.asyncio
    async def test_paper_env_mock_env_also_skips(self) -> None:
        """mock 및 sandbox env도 skip되어야 함."""
        for env in ("mock", "sandbox"):
            settings = MagicMock(spec=AppSettings)
            settings.kis_env = env
            settings.kis_live_info_enabled = True
            settings.kis_live_token_cache_enabled = False
            settings.kis_live_token_cache_path = ".cache/kis_live_token.json"
            settings.kis_live_info_ws_url = ""
            settings.kis_base_ws_url = ""
            settings.kis_real_rest_base_url = ""

            client = KisMarketStateClient(
                settings=settings,
                app_key="dummy-key",
                api_secret="dummy-secret",
            )
            await client.connect()
            assert client.is_connected is False, f"{env} should skip connect"


# ===========================================================================
# Test 2-4: Approval key 관련
# ===========================================================================


class TestApprovalKey:
    """Approval key 발급 및 캐싱 검증."""

    @pytest.mark.asyncio
    async def test_ensure_approval_key_http_post(
        self, live_client: KisMarketStateClient
    ) -> None:
        """_ensure_approval_key()가 HTTP POST /oauth2/Approval을 호출하는지 확인."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "approval_key": "test-approval-key-12345",
            "expires_in": 86400,
        }
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.post.return_value = mock_response

        with patch.object(live_client, "_get_http_client", return_value=mock_http):
            with patch.object(
                live_client._approval_cache, "load", AsyncMock(return_value=None)
            ):
                key = await live_client._ensure_approval_key()

        assert key == "test-approval-key-12345"
        mock_http.post.assert_called_once_with(
            "/oauth2/Approval",
            json={
                "grant_type": "client_credentials",
                "appkey": "live-key",
                "secretkey": "live-secret",
            },
        )

    @pytest.mark.asyncio
    async def test_ensure_approval_key_cache_load(
        self, live_client: KisMarketStateClient
    ) -> None:
        """기존 cache에서 approval key 로드 검증."""
        with patch.object(
            live_client._approval_cache, "load", AsyncMock(return_value="cached-approval-key")
        ):
            key = await live_client._ensure_approval_key()

        assert key == "cached-approval-key"
        assert live_client._approval_key == "cached-approval-key"

    @pytest.mark.asyncio
    async def test_ensure_approval_key_cache_save(
        self, live_client: KisMarketStateClient
    ) -> None:
        """신규 발급 후 cache에 저장되는지 확인."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "approval_key": "new-approval-key",
            "expires_in": 86400,
        }
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.post.return_value = mock_response

        with patch.object(live_client, "_get_http_client", return_value=mock_http):
            with patch.object(
                live_client._approval_cache, "load", AsyncMock(return_value=None)
            ):
                with patch.object(
                    live_client._approval_cache,
                    "save",
                    AsyncMock(),
                ) as mock_save:
                    key = await live_client._ensure_approval_key()

        assert key == "new-approval-key"
        mock_save.assert_called_once_with("new-approval-key", 86400)


# ===========================================================================
# Test 5-6: H0UNMKO0 응답 파싱
# ===========================================================================


class TestH0UNMKO0Parsing:
    """H0UNMKO0 WebSocket 메시지 파싱 검증."""

    @pytest.mark.asyncio
    async def test_parse_open_phase(
        self, live_client: KisMarketStateClient
    ) -> None:
        """mkop_cls_code=1 → MarketPhaseCode.OPEN"""
        msg = _make_h0unmko0_message(mkop_cls_code="1")
        await live_client._process_message(msg)
        state = await live_client.get_current_state()
        assert state.phase == MarketPhaseCode.OPEN
        assert state.mkop_cls_code == "1"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "code,expected",
        [
            ("0", MarketPhaseCode.PRE_MARKET),
            ("1", MarketPhaseCode.OPEN),
            ("2", MarketPhaseCode.CLOSING),
            ("3", MarketPhaseCode.AFTER_HOURS),
            ("4", MarketPhaseCode.HALT),
            ("5", MarketPhaseCode.HALT),
            ("99", MarketPhaseCode.UNKNOWN),
            ("", MarketPhaseCode.UNKNOWN),
        ],
    )
    async def test_parse_all_mkop_codes(
        self,
        live_client: KisMarketStateClient,
        code: str,
        expected: MarketPhaseCode,
    ) -> None:
        """모든 MKOP_CLS_CODE 매핑 케이스 검증."""
        msg = _make_h0unmko0_message(mkop_cls_code=code)
        await live_client._process_message(msg)
        state = await live_client.get_current_state()
        assert state.phase == expected, f"code={code!r} → {expected}"


# ===========================================================================
# Test 7: WebSocket 재연결 지수 백오프
# ===========================================================================


class TestReconnectBackoff:
    """재연결 지수 백오프 검증."""

    @pytest.mark.asyncio
    async def test_reconnect_exponential_backoff(
        self, live_client: KisMarketStateClient
    ) -> None:
        """연결 실패 시 1s→2s→4s→8s→16s 간격 재시도, 최대 5회 후 포기."""
        mock_connect = AsyncMock(side_effect=Exception("Connection refused"))

        captured_timeouts: list[float] = []

        async def _mock_wait_for(coro: object, timeout: float, **kwargs: object) -> object:
            captured_timeouts.append(timeout)
            raise asyncio.TimeoutError()

        with patch(
            "websockets.connect",
            mock_connect,
        ), patch("asyncio.wait_for", _mock_wait_for):
            await live_client._run_connection_loop()

        # 1 initial attempt + 5 retries = 6 total
        assert mock_connect.call_count == 6
        # Backoff delays: 1, 2, 4, 8, 16
        assert captured_timeouts == [1.0, 2.0, 4.0, 8.0, 16.0], (
            f"Expected [1, 2, 4, 8, 16], got {captured_timeouts}"
        )


# ===========================================================================
# Test 8-9: Listener 호출 검증
# ===========================================================================


class TestListeners:
    """MarketStateListener 호출 검증."""

    @pytest.mark.asyncio
    async def test_listener_called_on_phase_change(
        self, live_client: KisMarketStateClient
    ) -> None:
        """phase 변경 시 listener.on_market_state_changed()가 호출되어야 함."""
        listener = MockMarketStateListener()
        live_client.add_listener(listener)

        msg = _make_h0unmko0_message(mkop_cls_code="1")  # OPEN
        await live_client._process_message(msg)

        assert len(listener.calls) == 1
        assert listener.calls[0].phase == MarketPhaseCode.OPEN

    @pytest.mark.asyncio
    async def test_listener_called_on_every_message(
        self, live_client: KisMarketStateClient
    ) -> None:
        """모든 메시지에서 listener가 호출되어야 함 (phase 동일 여부와 무관)."""
        listener = MockMarketStateListener()
        live_client.add_listener(listener)

        # Send two OPEN messages (same phase)
        msg_open = _make_h0unmko0_message(mkop_cls_code="1")
        await live_client._process_message(msg_open)
        await live_client._process_message(msg_open)

        # Listener is called for every message (not only on phase change)
        assert len(listener.calls) == 2
        for call in listener.calls:
            assert call.phase == MarketPhaseCode.OPEN


# ===========================================================================
# Test 10: disconnect() graceful close
# ===========================================================================


class TestDisconnect:
    """연결 종료 검증."""

    @pytest.mark.asyncio
    async def test_disconnect_graceful_close(
        self, live_client: KisMarketStateClient
    ) -> None:
        """disconnect() 호출 시 WebSocket connection이 정상 종료되어야 함."""
        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock()
        live_client._ws = mock_ws
        live_client._connected = True

        await live_client.disconnect()

        mock_ws.close.assert_called_once()
        assert live_client._connected is False
        assert live_client._ws is None

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(
        self, live_client: KisMarketStateClient
    ) -> None:
        """연결되지 않은 상태에서 disconnect() 호출은 안전해야 함."""
        await live_client.disconnect()  # Should not raise


# ===========================================================================
# Test 11: get_current_state() — 최신 상태 반환
# ===========================================================================


class TestGetCurrentState:
    """최신 장상태 반환 검증."""

    @pytest.mark.asyncio
    async def test_get_current_state_initial(
        self, live_client: KisMarketStateClient
    ) -> None:
        """WebSocket 메시지 수신 전 → UNKNOWN phase 반환."""
        state = await live_client.get_current_state()
        assert state.phase == MarketPhaseCode.UNKNOWN
        assert state.mkop_cls_code == ""

    @pytest.mark.asyncio
    async def test_get_current_state_after_message(
        self, live_client: KisMarketStateClient
    ) -> None:
        """WebSocket 메시지 수신 후 올바른 MarketState 반환."""
        msg = _make_h0unmko0_message(
            mkop_cls_code="2",
            vi_cls_code="1",
            trht_yn="N",
            exch_cls_code="KRX",
        )
        await live_client._process_message(msg)

        state = await live_client.get_current_state()
        assert state.phase == MarketPhaseCode.CLOSING
        assert state.mkop_cls_code == "2"
        assert state.vi_cls_code == "1"
        assert state.trht_yn == "N"
        assert state.exch_cls_code == "KRX"
        assert state.raw is not None


# ===========================================================================
# Test 12: _resolve_ws_url() — 4단계 fallback
# ===========================================================================


class TestResolveWsUrl:
    """WebSocket URL resolution 검증."""

    def test_explicit_url(self) -> None:
        """명시적 URL이 설정된 경우 그대로 사용."""
        settings = MagicMock(spec=AppSettings)
        settings.kis_env = "live"
        settings.kis_live_info_enabled = True
        settings.kis_live_token_cache_enabled = False
        settings.kis_live_token_cache_path = ".cache/kis_live_token.json"

        client = KisMarketStateClient(
            settings=settings,
            app_key="k",
            api_secret="s",
            base_ws_url="ws://custom.example.com",
        )
        url = client._resolve_ws_url()
        assert url == "ws://custom.example.com/websocket"

    def test_kis_live_info_ws_url(self) -> None:
        """KIS_LIVE_INFO_WS_URL 설정 사용."""
        settings = MagicMock(spec=AppSettings)
        settings.kis_env = "live"
        settings.kis_live_info_enabled = True
        settings.kis_live_token_cache_enabled = False
        settings.kis_live_token_cache_path = ".cache/kis_live_token.json"
        settings.kis_live_info_ws_url = "live-info.example.com"
        settings.kis_base_ws_url = ""
        settings.kis_real_rest_base_url = ""

        client = KisMarketStateClient(
            settings=settings,
            app_key="k",
            api_secret="s",
        )
        url = client._resolve_ws_url()
        assert url == "ws://live-info.example.com/websocket"

    def test_kis_base_ws_url_fallback(self) -> None:
        """KIS_BASE_WS_URL fallback."""
        settings = MagicMock(spec=AppSettings)
        settings.kis_env = "live"
        settings.kis_live_info_enabled = True
        settings.kis_live_token_cache_enabled = False
        settings.kis_live_token_cache_path = ".cache/kis_live_token.json"
        settings.kis_live_info_ws_url = ""
        settings.kis_base_ws_url = "ws-base.example.com"
        settings.kis_real_rest_base_url = ""

        client = KisMarketStateClient(
            settings=settings,
            app_key="k",
            api_secret="s",
        )
        url = client._resolve_ws_url()
        assert url == "ws://ws-base.example.com/websocket"

    def test_http_base_url_fallback(self) -> None:
        """HTTP base URL → ws:// 변환."""
        settings = MagicMock(spec=AppSettings)
        settings.kis_env = "live"
        settings.kis_live_info_enabled = True
        settings.kis_live_token_cache_enabled = False
        settings.kis_live_token_cache_path = ".cache/kis_live_token.json"
        settings.kis_live_info_ws_url = ""
        settings.kis_base_ws_url = ""
        settings.kis_real_rest_base_url = "https://api.kis.com:9443"

        client = KisMarketStateClient(
            settings=settings,
            app_key="k",
            api_secret="s",
        )
        url = client._resolve_ws_url()
        assert url == "ws://api.kis.com:9443/websocket"


# ===========================================================================
# Test 13: heartbeat 설정
# ===========================================================================


class TestHeartbeat:
    """Heartbeat(ping_interval) 설정 검증."""

    @pytest.mark.asyncio
    async def test_heartbeat_interval(
        self, live_client: KisMarketStateClient
    ) -> None:
        """websockets.connect(ping_interval=30)으로 호출되는지 확인."""
        mock_ws = AsyncMock()

        async def _connect_side_effect(*args: object, **kwargs: object) -> AsyncMock:
            # Set shutdown after connect so the connection loop exits
            live_client._shutdown_event.set()
            return mock_ws

        mock_connect = AsyncMock(side_effect=_connect_side_effect)

        with patch(
            "websockets.connect",
            mock_connect,
        ), patch.object(
            live_client._approval_cache,
            "load",
            AsyncMock(return_value="test-approval"),
        ), patch.object(
            live_client, "_send_subscribe", AsyncMock(),
        ), patch.object(
            live_client, "_message_loop", AsyncMock(),
        ):
            await live_client.connect()
            # Give the background task a chance to run
            await asyncio.sleep(0)

        mock_connect.assert_called_once()
        _call_args, kwargs = mock_connect.call_args
        assert kwargs.get("ping_interval") == 30, (
            f"Expected ping_interval=30, got {kwargs.get('ping_interval')}"
        )


# ===========================================================================
# 추가: _map_mkop_cls_code 단위 테스트 (직접 함수 검증)
# ===========================================================================


class TestMapMkopClsCode:
    """_map_mkop_cls_code 함수 직접 검증."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("0", MarketPhaseCode.PRE_MARKET),
            ("1", MarketPhaseCode.OPEN),
            ("2", MarketPhaseCode.CLOSING),
            ("3", MarketPhaseCode.AFTER_HOURS),
            ("4", MarketPhaseCode.HALT),
            ("5", MarketPhaseCode.HALT),
            ("unknown", MarketPhaseCode.UNKNOWN),
            ("", MarketPhaseCode.UNKNOWN),
            ("99", MarketPhaseCode.UNKNOWN),
        ],
    )
    def test_map_mkop_cls_code(
        self, raw: str, expected: MarketPhaseCode
    ) -> None:
        """원시 MKOP_CLS_CODE → MarketPhaseCode 매핑."""
        from agent_trading.brokers.koreainvestment.market_state_client import (
            _map_mkop_cls_code,
        )

        assert _map_mkop_cls_code(raw) == expected
