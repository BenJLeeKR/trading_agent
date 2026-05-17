"""KIS 국내휴장일조회 (076) 전용 REST 클라이언트.

``KISHolidayClient``는 **오직** 076 API (``/uapi/domestic-stock/v1/quotations/chk-holiday``)
호출만을 담당하는 간단한 REST 클라이언트입니다.

**중요: live-info client 분리 원칙**
- 이 클래스는 주문/잔고/체결 경로와 **완전히 분리**되어 있습니다.
- ``KISRestClient``(paper/live 주문 클라이언트)와 상속/공유 관계가 없습니다.
- 생성자는 ``app_key``, ``app_secret``, ``base_url`` 3개 필드만 받습니다.
- 이 클래스가 ``submit``, ``inquire_balance``, ``inquire_daily_ccld`` 등의
  주문/잔고/체결 API를 호출하는 일은 **절대** 없습니다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from agent_trading.brokers.koreainvestment.token_cache import (
    CachePurpose,
    KisTokenCache,
    KisTokenCacheConfig,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Live-info OAuth token cache constants
# ---------------------------------------------------------------------------

_HOLIDAY_OAUTH_CACHE_DEFAULT_FILENAME = "kis_live_oauth_token.json"

# ---------------------------------------------------------------------------
# HolidayStatus — 076 API 응답 구조체
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HolidayStatus:
    """국내휴장일조회 응답을 표현하는 불변 dataclass.

    Attributes:
        bass_dt: 기준일자 (YYYYMMDD)
        wday_dvsn_cd: 요일구분코드 (01=일, 02=월, ..., 07=토)
        bzdy_yn: 영업일여부 (Y/N) — 금융기관 업무 가능일
        tr_day_yn: 거래일여부 (Y/N) — 증권 업무 가능일
        opnd_yn: 개장일여부 (Y/N) — 주식시장 개장일 (주문 가능)
        sttl_day_yn: 결제일여부 (Y/N) — 실제 결제일
    """

    bass_dt: str
    wday_dvsn_cd: str
    bzdy_yn: str
    tr_day_yn: str
    opnd_yn: str
    sttl_day_yn: str

    @property
    def is_trading_day(self) -> bool:
        """``opnd_yn == 'Y'`` 여부 (주문 가능일)."""
        return self.opnd_yn == "Y"

    @property
    def is_business_day(self) -> bool:
        """``bzdy_yn == 'Y'`` 여부 (금융기관 업무일)."""
        return self.bzdy_yn == "Y"


# ---------------------------------------------------------------------------
# KISHolidayClient — 076 API 전용 REST 클라이언트
# ---------------------------------------------------------------------------


class KISHolidayClient:
    """076 국내휴장일조회 API 전용 간단 REST 클라이언트.

    ``KISRestClient``와 **완전히 독립된** 클래스입니다.
    주문/잔고/체결 경로에 접근할 수 없습니다.

    Args:
        app_key: KIS 앱키 (``KIS_LIVE_INFO_APP_KEY``)
        app_secret: KIS 앱시크릿 (``KIS_LIVE_INFO_APP_SECRET``)
        base_url: KIS 실전 API base URL (``KIS_LIVE_INFO_BASE_URL``)
            기본값: ``https://openapi.koreainvestment.com:9443``

    Note:
        076 API는 모의투자를 지원하지 않으므로(``모의투자 미지원``),
        ``base_url``은 항상 실전 endpoint여야 합니다.
    """

    # 076 API endpoint 경로
    _HOLIDAY_ENDPOINT = "/uapi/domestic-stock/v1/quotations/chk-holiday"
    _OAUTH2_ENDPOINT = "/oauth2/tokenP"
    _DEFAULT_BASE_URL = "https://openapi.koreainvestment.com:9443"
    # TR_ID for 076 (실전 only; 모의투자 미지원)
    _TR_ID = "CTCA0903R"

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        base_url: str = _DEFAULT_BASE_URL,
        *,
        enable_token_cache: bool = False,
        token_cache_path: str | None = None,
    ) -> None:
        self._app_key = app_key
        self._app_secret = app_secret
        self._base_url = base_url.rstrip("/")

        # HTTP client (lazy init)
        self._client: httpx.AsyncClient | None = None

        # In-memory token cache
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._auth_lock = asyncio.Lock()

        # File token cache (live-info OAuth token persistence across restarts)
        self._cache_enabled = enable_token_cache
        cache_path = token_cache_path or f".cache/{_HOLIDAY_OAUTH_CACHE_DEFAULT_FILENAME}"
        # secret hash for fingerprint input
        secret_hash = app_secret[-4:] if len(app_secret) >= 4 else app_secret
        self._token_cache = KisTokenCache(KisTokenCacheConfig(
            enabled=enable_token_cache,
            cache_path=Path(cache_path),
            cache_purpose=CachePurpose.LIVE_HOLIDAY_OAUTH,
            fingerprint_input=f"holiday_oauth_{app_key}_{secret_hash}_{self._base_url}",
            extra_validators={
                "token_purpose": "holiday_oauth",
            },
            load_expiry_buffer=60.0,
            save_expiry_buffer=60.0,
        ))

    # ------------------------------------------------------------------
    # HTTP client lifecycle
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the shared ``httpx.AsyncClient`` instance."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(15.0, connect=10.0),
            )
        return self._client

    async def close(self) -> None:
        """Explicitly close the underlying HTTP client."""
        if self._client is not None:
            try:
                await self._client.aclose()
            except RuntimeError:
                pass
            self._client = None

    async def __aenter__(self) -> KISHolidayClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Auth: access token (minimal single-flight implementation)
    # ------------------------------------------------------------------

    async def _ensure_token(self) -> str:
        """Obtain (or return cached) KIS OAuth2 access token.

        Cache resolution order:
        1. In-memory cache (fastest, per-process)
        2. File cache via ``KisTokenCache`` (cross-restart)
        3. HTTP call (``/oauth2/tokenP``)

        Implements single-flight pattern with asyncio.Lock to guarantee
        at most 1 concurrent HTTP call to ``/oauth2/tokenP``.
        """
        async with self._auth_lock:
            now_wall = time.time()

            # 1. In-memory cache hit check
            if self._access_token is not None and now_wall < self._token_expires_at:
                return self._access_token

            # 2. File cache load via KisTokenCache
            if self._cache_enabled:
                cached_token = await self._token_cache.load()
                if cached_token is not None:
                    self._access_token = cached_token
                    self._token_expires_at = now_wall + 86400 - 300
                    return self._access_token

            # 3. HTTP call (oauth2/tokenP)
            client = await self._get_client()
            body = {
                "grant_type": "client_credentials",
                "appkey": self._app_key,
                "appsecret": self._app_secret,
            }
            try:
                resp = await client.post(self._OAUTH2_ENDPOINT, json=body)
            except httpx.RequestError as exc:
                raise KISHolidayError(
                    f"Request failed for oauth2_token: {exc}",
                ) from exc
            data = self._parse_response(resp, context="oauth2_token")

            # Update in-memory cache — refresh 5 min early
            self._access_token = data["access_token"]
            expires_in = int(data.get("expires_in", 86400))
            self._token_expires_at = now_wall + expires_in - 300

            # 4. Persist to file cache via KisTokenCache
            if self._cache_enabled:
                await self._token_cache.save(self._access_token, expires_in)

            logger.debug(
                "KISHolidayClient: token acquired (expires_in=%ds)",
                expires_in,
            )
            return self._access_token

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_response(
        self,
        resp: httpx.Response,
        context: str = "",
    ) -> dict[str, Any]:
        """Parse and validate KIS API JSON response.

        Raises ``KISHolidayError`` on HTTP or business-level errors.

        Note:
            OAuth2 ``/oauth2/tokenP`` 응답은 ``rt_cd`` 필드가 없으므로
            ``context="oauth2_token"``일 때는 ``rt_cd`` 검증을 건너뜁니다.
        """
        try:
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
        except httpx.HTTPStatusError as exc:
            raise KISHolidayError(
                f"HTTP {exc.response.status_code} from {context}: {exc.response.text}",
            ) from exc
        except (httpx.RequestError, ValueError) as exc:
            raise KISHolidayError(
                f"Request failed for {context}: {exc}",
            ) from exc

        # OAuth2 /oauth2/tokenP 응답에는 rt_cd 필드가 없으므로 검증 생략
        if context == "oauth2_token":
            return data

        # Check KIS business-level error (uapi 응답 전용)
        rt_cd = data.get("rt_cd", "")
        if rt_cd != "0":
            msg = data.get("msg1", data.get("msg_cd", "unknown error"))
            raise KISHolidayError(
                f"KIS error (rt_cd={rt_cd}) from {context}: {msg}",
            )

        return data

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_holiday_status(self, base_date: str | None = None) -> HolidayStatus:
        """076 국내휴장일조회 API 호출.

        Args:
            base_date: 기준일자 (YYYYMMDD). ``None``이면 오늘 날짜 사용.

        Returns:
            ``HolidayStatus`` dataclass 인스턴스.

        Raises:
            KISHolidayError: API 호출 실패 시 (인증 오류, 네트워크 오류 등).
                호출자(예: ``KisHolidayProvider``)에서 fallback 처리 필요.

        Note:
            KIS 권장사항: 이 API는 **1일 1회**만 호출할 것.
            단시간 내 다수 호출시 KIS 원장 서비스에 영향을 줄 수 있음.
        """
        if base_date is None:
            base_date = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")

        token = await self._ensure_token()
        client = await self._get_client()

        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": self._app_key,
            "appsecret": self._app_secret,
            "tr_id": self._TR_ID,
            "custtype": "P",  # 개인
        }

        params = {
            "BASS_DT": base_date,
            "CTX_AREA_NK": "",
            "CTX_AREA_FK": "",
        }

        resp = await client.get(
            self._HOLIDAY_ENDPOINT,
            headers=headers,
            params=params,
        )
        data = self._parse_response(resp, context="chk-holiday")

        # extract output — response may have single or array output
        output_raw = data.get("output", [])
        if isinstance(output_raw, list):
            if not output_raw:
                raise KISHolidayError(
                    f"Empty output array from chk-holiday for base_date={base_date}",
                )
            output = output_raw[0]  # first entry matches our base_date
        elif isinstance(output_raw, dict):
            output = output_raw
        else:
            raise KISHolidayError(
                f"Unexpected output type from chk-holiday: {type(output_raw).__name__}",
            )

        return HolidayStatus(
            bass_dt=str(output.get("bass_dt", base_date)),
            wday_dvsn_cd=str(output.get("wday_dvsn_cd", "")),
            bzdy_yn=str(output.get("bzdy_yn", "N")),
            tr_day_yn=str(output.get("tr_day_yn", "N")),
            opnd_yn=str(output.get("opnd_yn", "N")),
            sttl_day_yn=str(output.get("sttl_day_yn", "N")),
        )


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class KISHolidayError(Exception):
    """076 API 호출 실패를 나타내는 예외."""
