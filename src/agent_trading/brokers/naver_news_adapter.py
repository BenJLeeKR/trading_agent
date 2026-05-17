"""NAVER News Search API adapter — KIS disclosure seed 보조 검색용.

**이 어댑터는 범용 뉴스 수집기가 아닙니다.**
Strictly seed-based supplementary search for EI enhancement.
KIS 공시 제목을 seed로 하여 NAVER 뉴스 검색 API를 호출,
상위 1~3개의 관련 뉴스 후보를 반환합니다.

API spec: https://developers.naver.com/docs/serviceapi/search/news/news.md
"""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from agent_trading.domain.models import DisclosureTitleDTO

logger = logging.getLogger(__name__)

_DEFAULT_DISPLAY = 10
"""NAVER API ``display`` parameter default (max 100, default 10)."""

_NAVER_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
"""HTTP status codes that trigger retry with exponential backoff.

- 429: Rate limited (가장 빈번)
- 500/502/503/504: Server-side transient errors
"""


@dataclass(slots=True, frozen=True)
class NaverNewsItem:
    """Single item from NAVER News Search API response."""

    title: str
    """뉴스 제목 (HTML entity 포함 가능, e.g. ``"``)."""
    description: str
    """뉴스 요약/설명 (HTML 태그 포함 가능, e.g. ``<b>``)."""
    link: str
    """NAVER 뉴스 링크 (``https://news.naver.com/...``)."""
    originallink: str
    """언론사 원본 링크."""
    pubDate: str
    """발행 일시 (NAVER API 원본 문자열, e.g. ``2026-05-17T10:00:00+09:00``)."""


@dataclass(slots=True, frozen=True)
class NaverSearchResponse:
    """Parsed NAVER News Search API response."""

    items: list[NaverNewsItem]
    total: int = 0
    display: int = 0


class NaverNewsSearchAdapter:
    """NAVER News Search API adapter — KIS disclosure seed 보조 검색용.

    NOT a general-purpose news source. Strictly seed-based supplementary
    search for EI (Event Interpretation) enhancement.

    Parameters
    ----------
    client_id : str
        NAVER API Client ID (``X-Naver-Client-Id`` header).
    client_secret : str
        NAVER API Client Secret (``X-Naver-Client-Secret`` header).
    api_url : str
        NAVER Search API endpoint URL.
    http_client : httpx.AsyncClient | None
        Optional pre-configured HTTP client. Creates one if not provided.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        api_url: str = "https://openapi.naver.com/v1/search/news.json",
        http_client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        backoff_max: float = 30.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._api_url = api_url
        self._http_client = http_client or httpx.AsyncClient(timeout=10.0)
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max

    async def search_by_seed(
        self,
        seed: DisclosureTitleDTO,
        queries: list[str],
    ) -> list[NaverNewsItem]:
        """KIS disclosure seed → NAVER 검색 → raw news items 반환.

        내부적으로 각 query별로 ``sort=sim`` 만 호출 (sort=date 제거,
        429 Rate Limit 대응을 위한 호출량 50% 감축).
        동일 API call 내 중복은 ``originallink`` 기준으로 제거한다.

        Parameters
        ----------
        seed : DisclosureTitleDTO
            The KIS disclosure seed to search for.
        queries : list[str]
            Pre-built search queries from DisclosureQueryBuilder.

        Returns
        -------
        list[NaverNewsItem]
            Raw news items (pre-dedupe, pre-scoring).
            Empty if queries is empty or no results.
        """
        if not queries:
            logger.warning(
                "NaverNewsSearchAdapter: no queries for symbol=%s headline=%r",
                seed.symbol,
                seed.headline,
            )
            return []

        query_count = len(queries)
        logger.info(
            "NaverNewsSearchAdapter: query_count=%d symbol=%s",
            query_count,
            seed.symbol,
        )

        seen_links: set[str] = set()
        all_items: list[NaverNewsItem] = []

        for query in queries:
            # sort=sim only (sort=date removed to reduce API calls by 50%)
            try:
                response = await self._call_api(query, sort="sim")
            except Exception:
                logger.exception(
                    "NaverNewsSearchAdapter: API call failed "
                    "query=%r sort=sim — skipping",
                    query,
                )
                continue

            for item in response.items:
                # Intra-batch dedupe by originallink
                dedup_key = item.originallink or item.link
                if dedup_key in seen_links:
                    continue
                seen_links.add(dedup_key)
                all_items.append(item)

        logger.info(
            "NaverNewsSearchAdapter: symbol=%s queries=%d -> %d raw items",
            seed.symbol,
            len(queries),
            len(all_items),
        )
        return all_items

    async def _call_api(
        self,
        query: str,
        sort: str = "sim",
        display: int = _DEFAULT_DISPLAY,
    ) -> NaverSearchResponse:
        """Call NAVER News Search API with retry/backoff for transient errors.

        Retry policy:
        - Retryable status codes (429, 500, 502, 503, 504): exponential backoff + jitter
        - Non-retryable 4xx (400, 401, 403, etc.): immediate failure → return []
        - Transient exceptions (Timeout, ConnectError): exponential backoff + jitter
        - Max retries: ``self._max_retries`` (default 3) → total attempts = max_retries + 1

        Parameters
        ----------
        query : str
            Search query string.
        sort : str
            Sort mode: ``"sim"`` (similarity) only.
        display : int
            Number of results to return (max 100, default 10).

        Returns
        -------
        NaverSearchResponse
            Parsed API response. Empty items list if all retries exhausted.
        """
        headers = {
            "X-Naver-Client-Id": self._client_id,
            "X-Naver-Client-Secret": self._client_secret,
        }
        params: dict[str, str] = {
            "query": query,
            "display": str(display),
            "sort": sort,
        }

        for attempt in range(self._max_retries + 1):  # 최초 1회 + retry 최대 3회 = 총 4회
            try:
                response = await self._http_client.get(
                    self._api_url,
                    headers=headers,
                    params=params,
                )

                # Non-retryable 4xx: 즉시 실패
                if response.status_code in (400, 401, 403, 404):
                    logger.error(
                        "NAVER API non-retryable error %d for query=%r — skipping",
                        response.status_code,
                        query,
                    )
                    return NaverSearchResponse(items=[])

                # Retryable status codes (429, 5xx)
                if response.status_code in _NAVER_RETRYABLE_STATUS_CODES:
                    if attempt < self._max_retries:
                        delay = self._backoff_base * (2**attempt) + random.uniform(
                            0, 0.5 * self._backoff_base * (2**attempt)
                        )
                        delay = min(delay, self._backoff_max)
                        logger.warning(
                            "NAVER API %d (attempt %d/%d), retrying in %.2fs — query=%r",
                            response.status_code,
                            attempt + 1,
                            self._max_retries + 1,
                            delay,
                            query,
                        )
                        await asyncio.sleep(delay)
                        continue
                    else:
                        logger.error(
                            "NAVER API %d — max retries exceeded for query=%r",
                            response.status_code,
                            query,
                        )
                        return NaverSearchResponse(items=[])

                response.raise_for_status()
                data: dict[str, Any] = response.json()

                items = [
                    NaverNewsItem(
                        title=item.get("title", ""),
                        description=item.get("description", ""),
                        link=item.get("link", ""),
                        originallink=item.get("originallink", ""),
                        pubDate=item.get("pubDate", ""),
                    )
                    for item in data.get("items", [])
                ]

                logger.debug(
                    "NAVER API success: query=%r sort=%s items=%d",
                    query,
                    sort,
                    len(items),
                )
                return NaverSearchResponse(
                    items=items,
                    total=data.get("total", 0),
                    display=data.get("display", 0),
                )

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                if attempt < self._max_retries:
                    delay = self._backoff_base * (2**attempt) + random.uniform(
                        0, 0.5 * self._backoff_base * (2**attempt)
                    )
                    delay = min(delay, self._backoff_max)
                    logger.warning(
                        "NAVER API transient error (attempt %d/%d): %s, "
                        "retrying in %.2fs — query=%r",
                        attempt + 1,
                        self._max_retries + 1,
                        type(e).__name__,
                        delay,
                        query,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error(
                    "NAVER API transient error — max retries exceeded: %s — query=%r",
                    e,
                    query,
                )
                return NaverSearchResponse(items=[])

            except Exception:
                logger.exception(
                    "NAVER API unexpected error for query=%r", query,
                )
                return NaverSearchResponse(items=[])

        return NaverSearchResponse(items=[])

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http_client.aclose()
