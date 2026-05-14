"""OpenDART 전용 corp_code → stock_code (symbol) resolver.

OpenDART /company.json API를 사용하여 corp_code(8자리 고유번호)를
stock_code(6자리 종목코드)로 매핑한다.

- 성공/실패 모두 인메모리 캐싱 (negative cache 포함)
- 동일 batch 내 중복 corp_code는 1회만 API 호출
- 이 클래스는 OpenDART 전용이며, KIS/기타 소스의 symbol 매핑은 담당하지 않는다.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

OPENDART_BASE_URL = "https://opendart.fss.or.kr/api"

# OpenDART status codes
_STATUS_SUCCESS = "000"


class OpenDartSymbolResolver:
    """OpenDART corp_code → stock_code (symbol) resolver.

    Parameters
    ----------
    api_key : str
        OpenDART API authentication key (``crtfc_key``).
    base_url : str
        OpenDART API base URL (default: production).
    request_timeout : int
        HTTP request timeout in seconds.
    rate_limit_interval : float
        Minimum interval (seconds) between API calls to respect rate limits.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = OPENDART_BASE_URL,
        request_timeout: int = 30,
        rate_limit_interval: float = 1.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._request_timeout = request_timeout
        self._rate_limit_interval = rate_limit_interval

        # 인메모리 캐시: corp_code → str | None
        # None = negative cache (매핑 실패 기록 → 재조회 방지)
        self._cache: dict[str, str | None] = {}

        self._client: httpx.AsyncClient | None = None
        self._last_request_time: float = 0.0

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._request_timeout,
            )
        return self._client

    async def close(self) -> None:
        """HTTP client 정리. 더 이상 resolve()를 호출하지 않을 때 호출한다."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def resolve(self, corp_code: str) -> str | None:
        """corp_code → stock_code (symbol).

        캐시 히트 시 API 호출 없이 즉시 반환한다.
        실패한 corp_code도 negative cache에 기록하여 동일 batch 내 재조회를 방지한다.

        Parameters
        ----------
        corp_code : str
            OpenDART 8자리 고유번호.

        Returns
        -------
        str | None
            매핑된 stock_code (6자리). 매핑 불가능하면 None.
        """
        if corp_code in self._cache:
            cached = self._cache[corp_code]
            if cached is None:
                logger.debug(
                    "Negative cache hit for corp_code=%s (skipping API call)",
                    corp_code,
                )
            else:
                logger.debug(
                    "Cache hit for corp_code=%s → symbol=%s",
                    corp_code,
                    cached,
                )
            return cached

        symbol = await self._fetch_symbol(corp_code)
        # 성공/실패 모두 캐시 (negative cache 포함)
        self._cache[corp_code] = symbol
        return symbol

    async def _fetch_symbol(self, corp_code: str) -> str | None:
        """/company.json API를 호출하여 corp_code에 대한 stock_code를 조회한다.

        Returns
        -------
        str | None
            stock_code (6자리). API 오류 또는 stock_code가 없으면 None.
        """
        # Rate limit 준수
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time
        if elapsed < self._rate_limit_interval:
            wait = self._rate_limit_interval - elapsed
            logger.debug("Rate limit: waiting %.2f seconds before /company.json call", wait)
            await asyncio.sleep(wait)

        client = await self._get_client()

        try:
            response = await client.get(
                "/company.json",
                params={
                    "crtfc_key": self._api_key,
                    "corp_code": corp_code,
                },
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        except Exception:
            logger.exception(
                "OpenDART /company.json API request failed for corp_code=%s",
                corp_code,
            )
            return None
        finally:
            self._last_request_time = asyncio.get_event_loop().time()

        status = data.get("status", "")
        if status != _STATUS_SUCCESS:
            message = data.get("message", "Unknown error")
            logger.warning(
                "OpenDART /company.json returned non-success status=%s message=%s for corp_code=%s",
                status,
                message,
                corp_code,
            )
            return None

        stock_code: str | None = data.get("stock_code") or None
        if stock_code is None:
            logger.info(
                "OpenDART /company.json returned no stock_code for corp_code=%s corp_name=%s",
                corp_code,
                data.get("corp_name", "unknown"),
            )
        else:
            logger.debug(
                "Resolved corp_code=%s → stock_code=%s via /company.json",
                corp_code,
                stock_code,
            )

        return stock_code

    @property
    def cache_size(self) -> int:
        """현재 캐시에 저장된 corp_code 수 (negative cache 포함)."""
        return len(self._cache)

    def clear_cache(self) -> None:
        """캐시 초기화. 새 batch 시작 시 호출할 수 있다."""
        self._cache.clear()
