"""KIS disclosure headline → NAVER search query builder.

Phase P-2b: Extracts core search terms from Korean disclosure titles
to build NAVER News Search API queries.

Strategy priority (MVP):
    1. ``{company_name} {extracted_keywords}`` — optimal (MVP 기본 경로)
    2. ``{company_name} 공시`` — fallback when keyword extraction fails
    3. (MVP에서 제외) ``{keywords only}`` — 종목 anchor 없이 noise 급증 위험
"""
from __future__ import annotations

import logging
import re
from collections.abc import Sequence

from agent_trading.domain.models import DisclosureTitleDTO

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 헤드라인에서 제거할 boilerplate 패턴
# ---------------------------------------------------------------------------
_BOILERPLATE_TOKENS: frozenset[str] = frozenset({
    "결정",
    "공시",
    "통보",
    "안내",
    "보고",
    "사항",
})

# 제거할 일반 동사/조사 패턴
_GENERAL_VERB_PATTERN = re.compile(
    r"(에\s*관한|에\s*따른|위한|에\s*대한|에\s*의한|으로\s*인한)",
)

# 보존할 핵심 명사 패턴 (키워드 후보로 간주)
_CORE_KEYWORD_PATTERN = re.compile(
    r"(유상증자|무상증자|감자|자기주식\s*취득|자기주식\s*처분|"
    r"감사보고서|사업보고서|분기보고서|반기보고서|"
    r"배당|합병|분할|전환|"
    r"영업양수도|채무|인수|지분|"
    r"신주인수권|전환사채|CB|BW|"
    r"공개매수|장부가액|평가|"
    r"거래정지|상장폐지|관리종목)",
)


class DisclosureQueryBuilder:
    """Build NAVER search queries from KIS disclosure title seeds.

    Strategy priority:
    1. ``{company_name} {extracted_keywords}`` — optimal (MVP 기본 경로)
    2. ``{company_name} 공시`` — fallback when keyword extraction fails

    ``{keywords only}`` (Strategy 3)는 MVP에서 제외 — 종목 anchor가
    없으면 noise가 급격히 커질 가능성이 있음.
    """

    def build_queries(
        self,
        seed: DisclosureTitleDTO,
    ) -> list[str]:
        """Build prioritized query list from a disclosure seed.

        Parameters
        ----------
        seed : DisclosureTitleDTO
            KIS disclosure seed with headline and company_name.

        Returns
        -------
        list[str]
            Queries ordered by priority. Empty if seed has no headline.
        """
        if not seed.headline:
            logger.warning(
                "DisclosureQueryBuilder: empty headline for symbol=%s",
                seed.symbol,
            )
            return []

        headline = seed.headline
        company_name = seed.company_name or ""

        # Extract core keywords from headline
        keywords = self._extract_keywords(headline)

        queries: list[str] = []

        # Strategy 1: {company_name} {keywords} — MVP 기본 경로
        if keywords:
            kw_str = " ".join(keywords)
            query = f"{company_name} {kw_str}".strip()
            if query:
                queries.append(query)

        # Strategy 2: {company_name} 공시 (fallback)
        # 항상 추가하되, Strategy 1과 동일하면 skip
        fallback = f"{company_name} 공시".strip()
        if fallback and (not queries or fallback != queries[0]):
            queries.append(fallback)

        # NOTE: Strategy 3 ({keywords only})는 MVP에서 제외.
        # 종목 anchor가 사라져 noise가 급격히 커질 가능성이 큼.
        # 필요시 실험용/진단용 플래그로만 활성화.

        logger.debug(
            "DisclosureQueryBuilder: symbol=%s headline=%r -> queries=%s",
            seed.symbol,
            headline,
            queries,
        )
        return queries

    def _extract_keywords(self, headline: str) -> list[str]:
        """Extract core keywords from a Korean disclosure headline.

        Steps
        -----
        1. Remove general verb/adverb patterns (e.g., 에 관한, 에 따른)
        2. Tokenize by whitespace
        3. Remove boilerplate tokens, numeric-only tokens, 1-char tokens
        4. Return remaining tokens as unique keywords (preserving order)
        """
        # Step 1: Remove general verb patterns
        cleaned = _GENERAL_VERB_PATTERN.sub("", headline)

        # Step 2: Split into tokens
        tokens = cleaned.split()

        # Step 3: Filter tokens
        keywords: list[str] = []
        for token in tokens:
            token = token.strip()
            if not token:
                continue
            if len(token) <= 1:
                continue
            if token in _BOILERPLATE_TOKENS:
                continue
            if token.isdigit():
                continue

            # Core keyword pattern match or any meaningful (2+ char) token
            if _CORE_KEYWORD_PATTERN.search(token) or len(token) >= 2:
                keywords.append(token)

        # Step 4: Remove duplicates while preserving order
        seen: set[str] = set()
        unique_keywords: list[str] = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique_keywords.append(kw)

        return unique_keywords

    def get_keyword_overlap(
        self,
        headline: str,
        title: str,
    ) -> int:
        """Count overlapping keywords between seed headline and a news title.

        Used by the Hard Gate to check if a news item is actually related
        to the disclosure seed topic.

        Parameters
        ----------
        headline : str
            The original disclosure headline (seed headline).
        title : str
            The news item title to compare against.

        Returns
        -------
        int
            Number of overlapping keywords (0 = no overlap).
        """
        seed_kw: set[str] = set(self._extract_keywords(headline))
        title_lower = title.lower()
        return sum(1 for kw in seed_kw if kw.lower() in title_lower)
