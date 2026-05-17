"""Tests for ``KISHolidayClient`` (076 국내휴장일조회 전용 REST 클라이언트).

Test scope:
1. 성공 응답 파싱 (단일 output, 배열 output)
2. 에러 처리 (HTTP 오류, KIS business error, empty output)
3. Token 발급 실패 처리
4. ``_parse_response()`` oauth2 분기 — oauth2 응답(``rt_cd`` 없음) 정상 파싱
5. ``_parse_response()`` uapi 응답 회귀 방지 — 성공/실패
"""

from __future__ import annotations

import json
import time
from pathlib import Path
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
    """실제 oauth2/tokenP 응답 구조 — ``rt_cd`` 필드가 없음."""
    return {
        "access_token": "test-access-token-12345",
        "token_type": "bearer",
        "expires_in": 86400,
        "access_token_token_expired": "2026-05-17 06:00:00",
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
# _parse_response — oauth2 분기 + uapi 회귀 테스트
# ---------------------------------------------------------------------------


class TestParseResponse:
    """``_parse_response()`` oauth2 분기 및 uapi 회귀 테스트.

    oauth2/tokenP 응답에는 ``rt_cd`` 필드가 없으므로,
    ``context="oauth2_token"``일 때는 rt_cd 검증을 건너뛰어야 함.
    """

    def test_parse_oauth2_response_no_rt_cd(self, client: KISHolidayClient) -> None:
        """oauth2/tokenP 응답(rt_cd 없음) — context="oauth2_token" → 정상 파싱."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = {
            "access_token": "test-token-abc",
            "token_type": "Bearer",
            "expires_in": 86400,
        }

        result = client._parse_response(resp, context="oauth2_token")
        assert result["access_token"] == "test-token-abc"
        assert result["token_type"] == "Bearer"
        assert result["expires_in"] == 86400

    def test_parse_uapi_response_success(self, client: KISHolidayClient) -> None:
        """uapi 정상 응답(rt_cd=0) — context 미지정 → 정상 파싱 (회귀 방지)."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = {
            "rt_cd": "0",
            "msg_cd": "00000",
            "msg1": "success",
            "output": {"key": "value"},
        }

        # 기본 context (빈 문자열)에서도 정상 파싱
        result = client._parse_response(resp, context="")
        assert result["output"]["key"] == "value"

        # uapi context에서도 정상 파싱
        result2 = client._parse_response(resp, context="chk-holiday")
        assert result2["output"]["key"] == "value"

    def test_parse_uapi_response_error(self, client: KISHolidayClient) -> None:
        """uapi 실패 응답(rt_cd!=0) — context 미지정 → KISHolidayError (회귀 방지)."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = {
            "rt_cd": "E",
            "msg_cd": "EGW00100",
            "msg1": "인증실패",
        }

        with pytest.raises(KISHolidayError, match="인증실패"):
            client._parse_response(resp, context="")

        with pytest.raises(KISHolidayError, match="인증실패"):
            client._parse_response(resp, context="chk-holiday")

    def test_parse_oauth2_response_http_error(self, client: KISHolidayClient) -> None:
        """oauth2 응답 HTTP 오류 — context="oauth2_token" → KISHolidayError 발생."""
        error_resp = MagicMock(spec=httpx.Response)
        error_resp.status_code = 401
        error_resp.text = "Bad credentials"
        error_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized", request=MagicMock(), response=error_resp,
        )

        with pytest.raises(KISHolidayError, match="HTTP 401"):
            client._parse_response(error_resp, context="oauth2_token")

    def test_parse_oauth2_response_json_error(self, client: KISHolidayClient) -> None:
        """oauth2 응답 JSON 파싱 실패 — context="oauth2_token" → KISHolidayError."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.side_effect = ValueError("Invalid JSON")

        with pytest.raises(KISHolidayError, match="Request failed"):
            client._parse_response(resp, context="oauth2_token")


# ---------------------------------------------------------------------------
# _ensure_token — oauth2 인증 테스트 (mocked)
# ---------------------------------------------------------------------------


class TestEnsureToken:
    """``_ensure_token()`` 인증 로직 테스트."""

    @pytest.mark.asyncio
    async def test_ensure_token_success(self, client: KISHolidayClient) -> None:
        """oauth2/tokenP 성공 → access_token 반환."""
        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            mock_get_client.return_value = mock_http

            # oauth2 응답 (rt_cd 없음)
            token_resp = MagicMock(spec=httpx.Response)
            token_resp.status_code = 200
            token_resp.json.return_value = {
                "access_token": "live-info-test-token",
                "token_type": "Bearer",
                "expires_in": 86400,
            }
            mock_http.post.return_value = token_resp

            token = await client._ensure_token()
            assert token == "live-info-test-token"
            assert client._access_token == "live-info-test-token"

            # POST 호출 확인
            mock_http.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_token_cached(self, client: KISHolidayClient) -> None:
        """Token 캐싱 — 두 번째 호출은 HTTP 호출 없이 캐시 반환."""
        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            mock_get_client.return_value = mock_http

            token_resp = MagicMock(spec=httpx.Response)
            token_resp.status_code = 200
            token_resp.json.return_value = {
                "access_token": "cached-token",
                "token_type": "Bearer",
                "expires_in": 86400,
            }
            mock_http.post.return_value = token_resp

            # First call
            token1 = await client._ensure_token()
            assert token1 == "cached-token"

            # Second call — should use cache
            mock_http.post.reset_mock()
            token2 = await client._ensure_token()
            assert token2 == "cached-token"
            mock_http.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_token_http_error(self, client: KISHolidayClient) -> None:
        """oauth2/tokenP HTTP 오류 → KISHolidayError."""
        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            mock_get_client.return_value = mock_http

            error_resp = MagicMock(spec=httpx.Response)
            error_resp.status_code = 401
            error_resp.text = "Bad credentials"
            error_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "401 Unauthorized", request=MagicMock(), response=error_resp,
            )
            mock_http.post.return_value = error_resp

            with pytest.raises(KISHolidayError, match="HTTP 401"):
                await client._ensure_token()

    @pytest.mark.asyncio
    async def test_ensure_token_request_error(self, client: KISHolidayClient) -> None:
        """oauth2/tokenP 네트워크 오류 → KISHolidayError."""
        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            mock_get_client.return_value = mock_http
            mock_http.post.side_effect = httpx.RequestError("Connection refused")

            with pytest.raises(KISHolidayError, match="Request failed"):
                await client._ensure_token()


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


# ---------------------------------------------------------------------------
# File token cache tests (live-info OAuth token persistence)
# ---------------------------------------------------------------------------


def _make_cache_data(
    *,
    access_token: str = "cached-token-abc",
    token_type: str = "Bearer",
    expires_at: float | None = None,
    fingerprint: str | None = None,
    token_purpose: str = "holiday_oauth",
) -> dict:
    """Helper to build mock cache file data."""
    return {
        "access_token": access_token,
        "token_type": token_type,
        "expires_at": expires_at or (time.time() + 3600),
        "fingerprint": fingerprint or _compute_test_fingerprint(),
        "token_purpose": token_purpose,
        "created_at": time.time(),
    }


def _compute_test_fingerprint(
    app_key: str = "test-app-key",
    app_secret: str = "test-app-secret",
    base_url: str = "https://api.test.com:9443",
) -> str:
    """Compute the same fingerprint as KISHolidayClient for test matching."""
    import hashlib

    secret_suffix = app_secret[-4:] if len(app_secret) >= 4 else app_secret
    raw = f"holiday_oauth_{app_key}_{secret_suffix}_{base_url.rstrip('/')}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@pytest.fixture
def cache_client(tmp_path: Path) -> tuple[KISHolidayClient, Path]:
    """Create a KISHolidayClient with file token cache enabled, pointing to tmp_path."""
    cache_file = tmp_path / "kis_live_oauth_token.json"
    client = KISHolidayClient(
        app_key="test-app-key",
        app_secret="test-app-secret",
        base_url="https://api.test.com:9443",
        enable_token_cache=True,
        token_cache_path=str(cache_file),
    )
    return client, cache_file


class TestOAuthFileCache:
    """File-based OAuth token cache for holiday client."""

    @pytest.mark.asyncio
    async def test_oauth_file_cache_hit(
        self, cache_client: tuple[KISHolidayClient, Path]
    ) -> None:
        """File cache hit → in-memory cache populated from file, no HTTP call."""
        cl, cache_file = cache_client

        # Write valid cache file
        fp = _compute_test_fingerprint()
        data = _make_cache_data(fingerprint=fp)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(data))

        # _ensure_token should load from file cache without HTTP call
        with patch.object(cl, "_get_client") as mock_get_client:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            mock_get_client.return_value = mock_http

            token = await cl._ensure_token()

        assert token == "cached-token-abc"
        assert cl._access_token == "cached-token-abc"
        # HTTP should NOT be called (file cache hit)
        mock_get_client.assert_not_called()

    @pytest.mark.asyncio
    async def test_oauth_file_cache_missing(
        self, cache_client: tuple[KISHolidayClient, Path]
    ) -> None:
        """File missing → OAuth HTTP call → save to file."""
        cl, cache_file = cache_client

        with patch.object(cl, "_get_client") as mock_get_client:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            mock_get_client.return_value = mock_http
            token_resp = MagicMock(spec=httpx.Response)
            token_resp.status_code = 200
            token_resp.json.return_value = _mock_token_response()
            mock_http.post.return_value = token_resp

            token = await cl._ensure_token()

        assert token == "test-access-token-12345"
        # File should have been created
        assert cache_file.exists()
        saved = json.loads(cache_file.read_text())
        assert saved["access_token"] == "test-access-token-12345"
        assert saved.get("token_purpose") == "holiday_oauth"
        assert saved["credential_fingerprint"] == _compute_test_fingerprint()

    @pytest.mark.asyncio
    async def test_oauth_file_cache_expired(
        self, cache_client: tuple[KISHolidayClient, Path]
    ) -> None:
        """Expired file cache → HTTP call → refresh token."""
        cl, cache_file = cache_client

        # Write expired cache
        fp = _compute_test_fingerprint()
        data = _make_cache_data(
            fingerprint=fp,
            expires_at=time.time() - 60,  # expired 1 min ago
        )
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(data))

        with patch.object(cl, "_get_client") as mock_get_client:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            mock_get_client.return_value = mock_http
            token_resp = MagicMock(spec=httpx.Response)
            token_resp.status_code = 200
            token_resp.json.return_value = _mock_token_response()
            mock_http.post.return_value = token_resp

            token = await cl._ensure_token()

        assert token == "test-access-token-12345"
        # HTTP call should have been made
        mock_http.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_oauth_file_cache_fingerprint_mismatch(
        self, cache_client: tuple[KISHolidayClient, Path]
    ) -> None:
        """Fingerprint mismatch → HTTP call → refresh token."""
        cl, cache_file = cache_client

        # Write cache with WRONG fingerprint
        data = _make_cache_data(
            fingerprint="wrong-fingerprint-1234",
        )
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(data))

        with patch.object(cl, "_get_client") as mock_get_client:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            mock_get_client.return_value = mock_http
            token_resp = MagicMock(spec=httpx.Response)
            token_resp.status_code = 200
            token_resp.json.return_value = _mock_token_response()
            mock_http.post.return_value = token_resp

            token = await cl._ensure_token()

        assert token == "test-access-token-12345"
        mock_http.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_oauth_file_cache_token_purpose_mismatch(
        self, cache_client: tuple[KISHolidayClient, Path]
    ) -> None:
        """token_purpose mismatch (e.g., approval_key) → HTTP call."""
        cl, cache_file = cache_client

        fp = _compute_test_fingerprint()
        data = _make_cache_data(
            fingerprint=fp,
            token_purpose="approval_key",  # mismatched purpose
        )
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(data))

        with patch.object(cl, "_get_client") as mock_get_client:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            mock_get_client.return_value = mock_http
            token_resp = MagicMock(spec=httpx.Response)
            token_resp.status_code = 200
            token_resp.json.return_value = _mock_token_response()
            mock_http.post.return_value = token_resp

            token = await cl._ensure_token()

        assert token == "test-access-token-12345"
        mock_http.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_oauth_file_cache_disabled(
        self, cache_client: tuple[KISHolidayClient, Path]
    ) -> None:
        """Cache disabled → file ignored, HTTP call made."""
        # Create client with cache disabled
        cl = KISHolidayClient(
            app_key="test-app-key",
            app_secret="test-app-secret",
            base_url="https://api.test.com:9443",
            enable_token_cache=False,  # disabled
            token_cache_path=str(cache_client[1]),
        )

        # Write valid cache file
        fp = _compute_test_fingerprint()
        data = _make_cache_data(fingerprint=fp)
        cache_path = cache_client[1]
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(data))

        with patch.object(cl, "_get_client") as mock_get_client:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            mock_get_client.return_value = mock_http
            token_resp = MagicMock(spec=httpx.Response)
            token_resp.status_code = 200
            token_resp.json.return_value = _mock_token_response()
            mock_http.post.return_value = token_resp

            token = await cl._ensure_token()

        assert token == "test-access-token-12345"
        mock_http.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_oauth_in_memory_cache_still_works(
        self, cache_client: tuple[KISHolidayClient, Path]
    ) -> None:
        """In-memory cache: same client reuse → no extra HTTP call (regression)."""
        cl, cache_file = cache_client

        # First call: file missing → HTTP call
        with patch.object(cl, "_get_client") as mock_get_client:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            mock_get_client.return_value = mock_http
            token_resp = MagicMock(spec=httpx.Response)
            token_resp.status_code = 200
            token_resp.json.return_value = _mock_token_response()
            mock_http.post.return_value = token_resp

            token1 = await cl._ensure_token()
            assert token1 == "test-access-token-12345"

            # Second call: in-memory cache hit → no HTTP
            mock_http.post.reset_mock()
            token2 = await cl._ensure_token()
            assert token2 == "test-access-token-12345"
            mock_http.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_holiday_lookup_still_works(
        self, cache_client: tuple[KISHolidayClient, Path]
    ) -> None:
        """076 holiday lookup still works with file cache enabled (regression)."""
        cl, cache_file = cache_client

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_holiday_response()

        with patch.object(cl, "_get_client") as mock_get_client:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            mock_get_client.return_value = mock_http
            mock_http.post.return_value = MagicMock(
                status_code=200,
                json=lambda: _mock_token_response(),
            )
            mock_http.get.return_value = mock_resp

            status = await cl.get_holiday_status("20260516")

        assert isinstance(status, HolidayStatus)
        assert status.bass_dt == "20260516"
        assert status.is_trading_day is True
        # Cache file should have been created
        assert cache_file.exists()

    @pytest.mark.asyncio
    async def test_cache_save_creates_directory(
        self, tmp_path: Path
    ) -> None:
        """Cache save creates parent directory automatically."""
        nested_path = tmp_path / "nested" / "dir" / "kis_live_oauth_token.json"
        cl = KISHolidayClient(
            app_key="test-app-key",
            app_secret="test-app-secret",
            base_url="https://api.test.com:9443",
            enable_token_cache=True,
            token_cache_path=str(nested_path),
        )

        with patch.object(cl, "_get_client") as mock_get_client:
            mock_http = AsyncMock(spec=httpx.AsyncClient)
            mock_get_client.return_value = mock_http
            token_resp = MagicMock(spec=httpx.Response)
            token_resp.status_code = 200
            token_resp.json.return_value = _mock_token_response()
            mock_http.post.return_value = token_resp

            await cl._ensure_token()

        assert nested_path.exists(), "Cache file should be created with parent dirs"
