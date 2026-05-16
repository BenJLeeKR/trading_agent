"""Tests for ``KISHolidayClient`` (076 국내휴장일조회 전용 REST 클라이언트).

Test scope:
1. 성공 응답 파싱 (단일 output, 배열 output)
2. 에러 처리 (HTTP 오류, KIS business error, empty output)
3. Token 발급 실패 처리
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent_trading.brokers.koreainvestment.holiday_client import (
    KISHolidayClient,
    KISHolidayError,
    HolidayStatus,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> KISHolidayClient:
    """Create a KISHolidayClient with dummy credentials."""
    return KISHolidayClient(
        app_key="test-app-key",
        app_secret="test-app-secret",
        base_url="https://api.test.com:9443",
    )


def _mock_token_response() -> dict:
    return {
        "rt_cd": "0",
        "access_token": "test-access-token-12345",
        "token_type": "bearer",
        "expires_in": 86400,
    }


def _mock_holiday_response(
    bass_dt: str = "20260516",
    wday_dvsn_cd: str = "03",
    bzdy_yn: str = "Y",
    tr_day_yn: str = "Y",
    opnd_yn: str = "Y",
    sttl_day_yn: str = "Y",
) -> dict:
    return {
        "rt_cd": "0",
        "msg_cd": "00000",
        "msg1": "success",
        "output": [
            {
                "bass_dt": bass_dt,
                "wday_dvsn_cd": wday_dvsn_cd,
                "bzdy_yn": bzdy_yn,
                "tr_day_yn": tr_day_yn,
                "opnd_yn": opnd_yn,
                "sttl_day_yn": sttl_day_yn,
            },
        ],
    }


def _mock_holiday_response_dict_output(
    bass_dt: str = "20260516",
    wday_dvsn_cd: str = "03",
    bzdy_yn: str = "Y",
    tr_day_yn: str = "Y",
    opnd_yn: str = "Y",
    sttl_day_yn: str = "Y",
) -> dict:
    """Response where output is a single dict (not array)."""
    return {
        "rt_cd": "0",
        "msg_cd": "00000",
        "msg1": "success",
        "output": {
            "bass_dt": bass_dt,
            "wday_dvsn_cd": wday_dvsn_cd,
            "bzdy_yn": bzdy_yn,
            "tr_day_yn": tr_day_yn,
            "opnd_yn": opnd_yn,
            "sttl_day_yn": sttl_day_yn,
        },
    }


# ---------------------------------------------------------------------------
# HolidayStatus dataclass tests
# ---------------------------------------------------------------------------


class TestHolidayStatus:
    """HolidayStatus dataclass properties."""

    def test_is_trading_day_true(self) -> None:
        status = HolidayStatus(
            bass_dt="20260516",
            wday_dvsn_cd="03",
            bzdy_yn="Y",
            tr_day_yn="Y",
            opnd_yn="Y",
            sttl_day_yn="Y",
        )
        assert status.is_trading_day is True
        assert status.is_business_day is True

    def test_is_trading_day_false(self) -> None:
        status = HolidayStatus(
            bass_dt="20260516",
            wday_dvsn_cd="01",
            bzdy_yn="N",
            tr_day_yn="N",
            opnd_yn="N",
            sttl_day_yn="N",
        )
        assert status.is_trading_day is False
        assert status.is_business_day is False

    def test_business_day_not_trading_day(self) -> None:
        """영업일(bzdy_yn=Y)이지만 개장일(opnd_yn=N)인 경우."""
        status = HolidayStatus(
            bass_dt="20221231",
            wday_dvsn_cd="07",
            bzdy_yn="N",
            tr_day_yn="Y",
            opnd_yn="N",
            sttl_day_yn="N",
        )
        assert status.is_trading_day is False
        assert status.is_business_day is False  # bzdy_yn=N


# ---------------------------------------------------------------------------
# KISHolidayClient — success scenarios
# ---------------------------------------------------------------------------


class TestGetHolidayStatusSuccess:
    """076 API 성공 응답 파싱."""

    @pytest.mark.asyncio
    async def test_parses_array_output(self, client: KISHolidayClient) -> None:
        """단일 output 배열 파싱."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_holiday_response()

        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            mock_get_client.return_value = mock_http

            # First call: token, second: holiday
            mock_http.post.return_value = MagicMock(
                status_code=200,
                json=lambda: _mock_token_response(),
            )
            mock_http.get.return_value = mock_resp

            status = await client.get_holiday_status("20260516")

        assert isinstance(status, HolidayStatus)
        assert status.bass_dt == "20260516"
        assert status.wday_dvsn_cd == "03"
        assert status.opnd_yn == "Y"
        assert status.bzdy_yn == "Y"
        assert status.tr_day_yn == "Y"
        assert status.sttl_day_yn == "Y"
        assert status.is_trading_day is True

    @pytest.mark.asyncio
    async def test_parses_dict_output(self, client: KISHolidayClient) -> None:
        """output이 dict인 경우 파싱."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_holiday_response_dict_output(
            opnd_yn="N",
        )

        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            mock_get_client.return_value = mock_http
            mock_http.post.return_value = MagicMock(
                status_code=200,
                json=lambda: _mock_token_response(),
            )
            mock_http.get.return_value = mock_resp

            status = await client.get_holiday_status("20260516")

        assert status.is_trading_day is False
        assert status.opnd_yn == "N"

    @pytest.mark.asyncio
    async def test_uses_default_base_date(self, client: KISHolidayClient) -> None:
        """base_date=None → 오늘 날짜 자동 사용."""
        from datetime import datetime, timezone

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200

        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            mock_get_client.return_value = mock_http
            mock_http.post.return_value = MagicMock(
                status_code=200,
                json=lambda: _mock_token_response(),
            )

            async def _side_effect(*args: object, **kwargs: object) -> MagicMock:
                # Verify BASS_DT was set to today
                params = kwargs.get("params", {})
                expected = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
                assert params.get("BASS_DT") == expected, (
                    f"Expected BASS_DT={expected}, got {params.get('BASS_DT')}"
                )
                return mock_resp

            mock_http.get = AsyncMock(side_effect=_side_effect)
            mock_resp.json.return_value = _mock_holiday_response()

            await client.get_holiday_status()

    @pytest.mark.asyncio
    async def test_token_caching(self, client: KISHolidayClient) -> None:
        """Same client reuse → token cached, only one oauth2 call."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_holiday_response()

        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            mock_get_client.return_value = mock_http
            mock_http.post.return_value = MagicMock(
                status_code=200,
                json=lambda: _mock_token_response(),
            )
            mock_http.get.return_value = mock_resp

            # First call
            status1 = await client.get_holiday_status("20260516")
            assert status1.is_trading_day is True

            # Second call — token should be cached, no extra POST
            mock_http.post.reset_mock()
            status2 = await client.get_holiday_status("20260517")
            assert status2.is_trading_day is True

            # oauth2/tokenP should not be called again
            mock_http.post.assert_not_called()


# ---------------------------------------------------------------------------
# KISHolidayClient — error scenarios
# ---------------------------------------------------------------------------


class TestGetHolidayStatusErrors:
    """076 API 에러 처리."""

    @pytest.mark.asyncio
    async def test_http_error(self, client: KISHolidayClient) -> None:
        """HTTP 401 → KISHolidayError."""
        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            mock_get_client.return_value = mock_http
            mock_http.post.return_value = MagicMock(
                status_code=200,
                json=lambda: _mock_token_response(),
            )

            # Simulate HTTP 401 on holiday endpoint
            error_resp = MagicMock(spec=httpx.Response)
            error_resp.status_code = 401
            error_resp.text = "Unauthorized"
            error_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "401 Unauthorized", request=MagicMock(), response=error_resp,
            )
            mock_http.get.return_value = error_resp

            with pytest.raises(KISHolidayError, match="HTTP 401"):
                await client.get_holiday_status("20260516")

    @pytest.mark.asyncio
    async def test_kis_business_error(self, client: KISHolidayClient) -> None:
        """KIS business error (rt_cd != '0')."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "rt_cd": "E",
            "msg_cd": "EGW00100",
            "msg1": "인증실패",
        }

        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            mock_get_client.return_value = mock_http
            mock_http.post.return_value = MagicMock(
                status_code=200,
                json=lambda: _mock_token_response(),
            )
            mock_http.get.return_value = mock_resp

            with pytest.raises(KISHolidayError, match="인증실패"):
                await client.get_holiday_status("20260516")

    @pytest.mark.asyncio
    async def test_empty_output(self, client: KISHolidayClient) -> None:
        """Empty output array → KISHolidayError."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "rt_cd": "0",
            "msg_cd": "00000",
            "msg1": "success",
            "output": [],
        }

        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            mock_get_client.return_value = mock_http
            mock_http.post.return_value = MagicMock(
                status_code=200,
                json=lambda: _mock_token_response(),
            )
            mock_http.get.return_value = mock_resp

            with pytest.raises(KISHolidayError, match="Empty output"):
                await client.get_holiday_status("20260516")

    @pytest.mark.asyncio
    async def test_token_failure(self, client: KISHolidayClient) -> None:
        """OAuth2 token 발급 실패 → KISHolidayError."""
        error_resp = MagicMock(spec=httpx.Response)
        error_resp.status_code = 401
        error_resp.text = "Bad credentials"
        error_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized", request=MagicMock(), response=error_resp,
        )

        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            mock_get_client.return_value = mock_http
            mock_http.post.return_value = error_resp

            with pytest.raises(KISHolidayError):
                await client.get_holiday_status("20260516")

    @pytest.mark.asyncio
    async def test_request_error(self, client: KISHolidayClient) -> None:
        """Network error → KISHolidayError."""
        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            mock_get_client.return_value = mock_http
            mock_http.post.side_effect = httpx.RequestError("Connection refused")

            with pytest.raises(KISHolidayError, match="Request failed"):
                await client.get_holiday_status("20260516")


# ---------------------------------------------------------------------------
# Client lifecycle
# ---------------------------------------------------------------------------


class TestClientLifecycle:
    """Client 생성/소멸."""

    @pytest.mark.asyncio
    async def test_close_idempotent(self) -> None:
        """Multiple close() calls are safe."""
        client = KISHolidayClient("k", "s")
        await client.close()
        await client.close()  # second call should not raise

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        """``async with`` 패턴."""
        async with KISHolidayClient("k", "s") as client:
            assert client._app_key == "k"
            assert client._app_secret == "s"
