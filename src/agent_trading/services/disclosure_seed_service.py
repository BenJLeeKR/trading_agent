"""Disclosure seed service — KIS live 공시 제목 수집 및 정규화.

Phase P-1c/d/e: KIS 종합 시황_공시(제목) API (FHKST01011800) seed 조회.
NAVER 뉴스 연동 및 검색어 추출은 포함하지 않음 (향후 Phase P-2).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.domain.models import DisclosureTitleDTO

logger = logging.getLogger(__name__)


class LiveDisclosureSeedService:
    """Fetch and normalize KIS disclosure news titles for event ingestion seeds.

    Uses a dedicated live-only KISRestClient.  Falls back gracefully (``[]``).

    Parameters
    ----------
    client : KISRestClient | None
        A live-only ``KISRestClient`` configured with disclosure-specific
        credentials.  ``None`` means disclosure is disabled.
    """

    def __init__(self, client: KISRestClient | None) -> None:
        self._client = client
        logger.info(
            "LiveDisclosureSeedService initialized (client=%s)",
            "AVAILABLE" if client else "NONE (disclosure disabled)",
        )

    async def fetch_disclosure_titles(
        self,
        symbols: Sequence[str],
    ) -> list[DisclosureTitleDTO]:
        """Fetch disclosure titles for one or more symbols.

        Iterates over symbols sequentially, collecting normalized results.
        Returns a flat list of ``DisclosureTitleDTO``.
        Returns ``[]`` if client is unavailable or any error occurs.

        Parameters
        ----------
        symbols : Sequence[str]
            Stock symbols to fetch disclosure for (e.g. ``["005930", "000660"]``).

        Returns
        -------
        list[DisclosureTitleDTO]
            Normalized disclosure title DTOs.  Never ``None`` — always a list.
        """
        if not self._client:
            logger.warning(
                "DisclosureSeedService: client unavailable "
                "(live credentials not configured) — returning []",
            )
            return []

        results: list[DisclosureTitleDTO] = []
        for symbol in symbols:
            items = await self._fetch_one(symbol)
            results.extend(items)

        logger.info(
            "DisclosureSeedService: fetch complete — %d titles for %d symbols",
            len(results),
            len(symbols),
        )
        return results

    async def _fetch_one(self, symbol: str) -> list[DisclosureTitleDTO]:
        """Fetch disclosure for a single symbol and normalize.

        Returns a (possibly empty) list of normalized DTOs.
        """
        try:
            raw_items = await self._client.get_disclosure_news_title(symbol)  # type: ignore[union-attr]
        except Exception:
            logger.exception(
                "DisclosureSeedService: _fetch_one failed for symbol=%s",
                symbol,
            )
            return []

        if not raw_items:
            return []

        return [self._normalize(symbol, item) for item in raw_items if item]

    def _normalize(
        self,
        symbol: str,
        raw: dict,
    ) -> DisclosureTitleDTO:
        """Normalize a single KIS disclosure response item.

        Uses ``KISRestClient._normalize_disclosure_output()`` to extract
        fields from the raw KIS response, then wraps into a ``DisclosureTitleDTO``.
        """
        normalized = KISRestClient._normalize_disclosure_output(raw, symbol)
        return DisclosureTitleDTO(
            symbol=normalized["symbol"],
            company_name=normalized["company_name"],
            headline=normalized["headline"],
            published_at=normalized["published_at"],
            source=normalized["source"],
        )
