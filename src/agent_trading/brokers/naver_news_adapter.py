"""NAVER News Search API adapter — KIS disclosure seed 보조 검색용.

**이 어댑터는 범용 뉴스 수집기가 아닙니다.**
Strictly seed-based supplementary search for EI enhancement.
KIS 공시 제목을 seed로 하여 NAVER 뉴스 검색 API를 호출,
상위 1~3개의 관련 뉴스 후보를 반환합니다.

API spec: https://developers.naver.com/docs/serviceapi/search/news/news.md
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from agent_trading.domain.models import DisclosureTitleDTO

logger = logging.getLogger(__name__)

_DEFAULT_DISPLAY = 10
"""NAVER API ``display`` parameter default (max 100, default 10)."""

_NAVER_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({500, 502, 503, 504})
"""HTTP status codes that trigger retry with exponential backoff.

- 500/502/503/504: Server-side transient errors
- 429 is NOT retried — fast-fail instead (daily quota exhausted).
"""

# ── NAVER Daily Quota Tracker (best-effort, file-backed) ──────────────────────

_NAVER_DAILY_QUOTA_FILE = "/app/tmp/naver_daily_quota.json"
"""File path for daily NAVER API call count tracking.

Format: JSON with keys ``count``, ``date`` (YYYYMMDD KST), ``updated_at``.
"""

_NAVER_DAILY_LIMIT = 25000
"""NAVER Search API daily quota (25,000 calls/day)."""

_NAVER_QUOTA_THRESHOLD = 0.9
"""Quota exhaustion threshold ratio (90% = 22,500 calls)."""


class NaverDailyQuotaTracker:
    """File-backed daily quota tracker for NAVER Search API (fail-closed).

    Tracks NAVER API calls made today using a flock-protected JSON file.
    Resets at midnight KST (UTC+9).

    **Fail-Closed:** All file I/O errors are silently ignored. If the tracker
    is unavailable (file corrupt, flock failure, etc.), it returns
    ``_DAILY_LIMIT`` consumption — i.e., "quota exhausted, stop". This
    prevents the 429 → retry → 429 vicious cycle.

    Design follows ``FileBackedGlobalBucket`` pattern from
    :mod:`agent_trading.brokers.shared_budget`.
    """

    _FILE_PATH = _NAVER_DAILY_QUOTA_FILE
    _DAILY_LIMIT = _NAVER_DAILY_LIMIT
    _THRESHOLD = _NAVER_QUOTA_THRESHOLD

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def get_current_consumption(cls) -> int:
        """Read current day's call count from file.

        Returns ``0`` if the file cannot be read or the date has changed.
        """
        count, _ = cls._read_or_init()
        return count

    @classmethod
    def get_consumption_ratio(cls) -> float:
        """Return consumption ratio (0.0 ~ 1.0).

        Returns ``0.0`` if tracker is unavailable.
        """
        count, _ = cls._read_or_init()
        if cls._DAILY_LIMIT <= 0:
            return 0.0
        return min(1.0, count / cls._DAILY_LIMIT)

    @classmethod
    def is_exhausted(cls, threshold: float | None = None) -> bool:
        """Check if daily quota exceeds *threshold* (default 0.9 = 90%).

        Returns ``False`` if tracker is unavailable (fail-open).
        """
        t = threshold if threshold is not None else cls._THRESHOLD
        return cls.get_consumption_ratio() >= t

    @classmethod
    def increment(cls) -> None:
        """Increment daily call count by 1.

        Best-effort: silently ignores all I/O errors.
        """
        try:
            count, date_str = cls._read_or_init()
        except Exception:
            logger.warning("NaverDailyQuotaTracker._read_or_init() failed", exc_info=True)
            return
        try:
            today = cls._today_kst()
            if date_str != today:
                count = 0
            count += 1
            cls._write(count, today)
        except Exception:
            logger.warning(
                "NaverDailyQuotaTracker._write() failed (count=%s, date=%s)",
                count, date_str, exc_info=True,
            )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @classmethod
    def _today_kst(cls) -> str:
        """Return today's date as YYYYMMDD in KST (UTC+9)."""
        from datetime import timedelta
        kst_now = datetime.now(timezone.utc) + timedelta(hours=9)
        return kst_now.strftime("%Y%m%d")

    @classmethod
    def _read_or_init(cls) -> tuple[int, str]:
        """Read (count, date_str) from file; reset if date changed.

        Returns ``(_DAILY_LIMIT, "")`` on any error (file missing, corrupt, etc.)
        — fail-closed: if tracker state is unknown, assume quota is exhausted.
        """
        try:
            if not os.path.exists(cls._FILE_PATH):
                return cls._DAILY_LIMIT, ""
            with open(cls._FILE_PATH, "r") as f:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_SH)
                try:
                    data = json.load(f)
                    count = int(data.get("count", 0))
                    date_str = str(data.get("date", ""))
                    today = cls._today_kst()
                    if date_str != today:
                        return 0, today
                    return count, date_str
                except (json.JSONDecodeError, ValueError, KeyError):
                    return cls._DAILY_LIMIT, cls._today_kst()
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except (OSError, ImportError):
            return cls._DAILY_LIMIT, ""

    @classmethod
    def _write(cls, count: int, date_str: str) -> None:
        """Write (count, date_str) to file with flock protection."""
        try:
            os.makedirs(os.path.dirname(cls._FILE_PATH), exist_ok=True)
            with open(cls._FILE_PATH, "w") as f:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    json.dump(
                        {
                            "count": count,
                            "date": date_str,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        },
                        f,
                    )
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except (OSError, ImportError):
            logger.debug(
                "NaverDailyQuotaTracker: failed to write — "
                "tracker unavailable, continuing",
            )


class _NaverTokenBucket:
    """Token-bucket rate limiter for NAVER Search API.

    NAVER Search API rate limit is ~10 req/s. This bucket enforces a
    conservative 8 req/s with 20% safety margin.

    Thread-safe via ``asyncio.Lock``. Designed for class-level singleton
    usage (shared across all ``NaverNewsSearchAdapter`` instances).

    Parameters
    ----------
    max_tokens : int
        Maximum token count (burst limit). Default 8.
    refill_rate : float
        Tokens added per second. Default 8.0.
    """

    def __init__(self, max_tokens: int = 8, refill_rate: float = 8.0) -> None:
        self._max_tokens = max_tokens
        self._refill_rate = refill_rate
        self._tokens = float(max_tokens)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        """Refill tokens based on elapsed monotonic time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed > 0:
            tokens_to_add = elapsed * self._refill_rate
            if tokens_to_add > 0:
                self._tokens = min(float(self._max_tokens), self._tokens + tokens_to_add)
                self._last_refill = now

    async def consume_or_wait(self) -> None:
        """Consume one token, waiting (polling) until one is available.

        This is an **async blocking** call — it will sleep until a token
        becomes available. Use inside the semaphore context to avoid
        thundering-herd wakeups.
        """
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
            # No token available — wait and retry
            await asyncio.sleep(0.1)


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
    is_quota_exhausted: bool = False


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

    # 전역 shared semaphore: 모든 NaverNewsSearchAdapter 인스턴스가 공유.
    # 동시 Naver API 호출을 최대 2개로 제한하여 429 Rate Limit 발생을 완화.
    _NAVER_SEMAPHORE: asyncio.Semaphore = asyncio.Semaphore(2)

    # Token-bucket rate limiter: 8 req/s (20% safety margin from 10 req/s).
    # Semaphore(2)는 동시성 제어, token bucket은 초당 호출 속도 제어.
    _NAVER_RATE_LIMITER: _NaverTokenBucket = _NaverTokenBucket(
        max_tokens=8,
        refill_rate=8.0,
    )

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        api_url: str = "https://openapi.naver.com/v1/search/news.json",
        http_client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
        backoff_base: float = 2.0,
        backoff_max: float = 30.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._api_url = api_url
        self._http_client = http_client or httpx.AsyncClient(timeout=httpx.Timeout(5.0))
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max

    async def search_by_seed(
        self,
        seed: DisclosureTitleDTO,
        queries: list[str],
        max_queries: int | None = None,
    ) -> tuple[list[NaverNewsItem], bool]:
        """KIS disclosure seed → NAVER 검색 → raw news items 반환.

        내부적으로 각 query별로 ``sort=sim`` 만 호출 (sort=date 제거,
        429 Rate Limit 대응을 위한 호출량 50% 감축).
        동일 API call 내 중복은 ``originallink`` 기준으로 제거한다.

        Returns
        -------
        tuple[list[NaverNewsItem], bool]
            (items, is_quota_exhausted).
            ``is_quota_exhausted=True`` if any 429 was detected.
            Empty items list if queries is empty or no results.
        """
        if max_queries is not None:
            queries = queries[:max_queries]
        if not queries:
            logger.warning(
                "NaverNewsSearchAdapter: no queries for symbol=%s headline=%r",
                seed.symbol,
                seed.headline,
            )
            return [], False

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

            # ── 429 감지: quota exhausted → early return ──
            if response.is_quota_exhausted:
                logger.warning(
                    "NAVER quota exhausted during search_by_seed for symbol=%s — "
                    "returning is_quota_exhausted=True",
                    seed.symbol,
                )
                return [], True

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
        return all_items, False

    @classmethod
    def get_daily_usage_ratio(cls) -> float:
        """Return NAVER API daily quota usage ratio (0.0 ~ 1.0).

        Returns ``0.0`` if tracker is unavailable (fail-open).
        """
        return NaverDailyQuotaTracker.get_consumption_ratio()

    @classmethod
    def is_quota_exhausted(cls, threshold: float = _NAVER_QUOTA_THRESHOLD) -> bool:
        """Check if NAVER daily quota exceeds *threshold* (default 90%).

        Returns ``False`` if tracker is unavailable (fail-open).
        """
        return NaverDailyQuotaTracker.is_exhausted(threshold)

    async def _call_api(
        self,
        query: str,
        sort: str = "sim",
        display: int = _DEFAULT_DISPLAY,
    ) -> NaverSearchResponse:
        """Call NAVER News Search API with retry/backoff for transient errors.

        Retry policy:
        - **429: Fast-fail** — no retry, immediately return empty (daily quota exhausted)
        - Retryable 5xx (500, 502, 503, 504): exponential backoff + jitter
        - Non-retryable 4xx (400, 401, 403, etc.): immediate failure → return []
        - Transient exceptions (Timeout, ConnectError): exponential backoff + jitter
        - Max retries: ``self._max_retries`` (default 2) → total attempts = max_retries + 1
        - Concurrency: ``_NAVER_SEMAPHORE`` (class-level, max 2 concurrent calls)

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
        # Track this API call attempt (best-effort daily quota counter)
        NaverDailyQuotaTracker.increment()

        async with self._NAVER_SEMAPHORE:
            # Token-bucket rate limit: wait until a token is available
            await self._NAVER_RATE_LIMITER.consume_or_wait()

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

                    # ── 429 Fast-Fail: no retry, daily quota likely exhausted ──
                    if response.status_code == 429:
                        logger.warning(
                            "NAVER 429 fast-fail: query=%r — "
                            "daily quota likely exhausted",
                            query,
                        )
                        return NaverSearchResponse(items=[], is_quota_exhausted=True)

                    # Non-retryable 4xx: 즉시 실패
                    if response.status_code in (400, 401, 403, 404):
                        logger.error(
                            "NAVER API non-retryable error %d for query=%r — skipping",
                            response.status_code,
                            query,
                        )
                        return NaverSearchResponse(items=[])

                    # Retryable 5xx status codes (500, 502, 503, 504)
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
