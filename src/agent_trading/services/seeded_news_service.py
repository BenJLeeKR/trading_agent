"""SeededNewsCandidateService — KIS disclosure seed → NAVER news candidate.

전체 파이프라인 오케스트레이션:

    seed → query builder → NAVER search → hard gate → dedupe → score → candidate

Strict fallback 정책:
    - 모든 실패/예외 상황에서 ``[]`` 반환 (절대 예외 전파 금지)
    - API 미설정, empty seed, query 미생성, API 실패 등 모두 동일 처리

PipelineMetrics를 통해 각 실행의 품질 지표를 구조화된 로그로 출력한다.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from agent_trading.brokers.naver_news_adapter import (
    NaverNewsItem,
    NaverNewsSearchAdapter,
)
from agent_trading.domain.models import DisclosureTitleDTO, SeededNewsCandidate
from agent_trading.services.disclosure_query_builder import DisclosureQueryBuilder

logger = logging.getLogger(__name__)

_SCORE_THRESHOLD = 50
"""Minimum confidence score to keep a candidate (0-100)."""

_MAX_CANDIDATES_PER_SEED = 3
"""Maximum candidates per seed after scoring (top-N)."""

_MAX_CANDIDATES_PER_SYMBOL_GLOBAL = 3
"""Global maximum candidates per symbol after aggregation across all seeds."""

_SEED_PACING_DELAY: float = 0.5
"""Seconds to wait between processing each seed (429 Rate Limit 대응)."""


@dataclass(slots=True)
class PipelineMetrics:
    """Structured quality metrics for a single pipeline run.

    Used for sample verification and quality comparison across runs (MVP
    quality logging 목적).  모든 카운트는 ``process_seeds()`` 호출 단위로
    집계된다.
    """

    seeds_total: int = 0
    """Number of input seeds received."""
    seeds_with_queries: int = 0
    """Seeds that produced at least one query."""
    seeds_with_results: int = 0
    """Seeds that returned at least one candidate."""
    queries_executed: int = 0
    """Total NAVER API calls made (query × sort modes)."""
    raw_candidates_fetched: int = 0
    """Total raw items before any processing."""
    hard_gate_passed: int = 0
    """Items that passed the hard gate (company_name + keyword check)."""
    hard_gate_dropped: int = 0
    """Items dropped by hard gate."""
    deduped_count: int = 0
    """Items after deduplication (originallink + title similarity)."""
    kept_count: int = 0
    """Final candidates after score threshold and top-N."""
    dropped_low_confidence: int = 0
    """Items that passed hard gate and dedupe but failed score threshold."""
    dropped_cross_symbol: int = 0
    """Items penalized or dropped due to cross-symbol noise detection."""
    seed_quality_drop_count: int = 0
    """Seeds dropped by quality filter (suspicious company_name)."""
    retry_count: int = 0
    """Total API retry attempts across all queries."""
    per_symbol: dict[str, dict[str, int]] = field(default_factory=dict)
    """Per-symbol breakdown for granular quality inspection."""


class SeededNewsCandidateService:
    """Orchestrate the KIS disclosure seed → NAVER news candidate pipeline.

    This service is the entry point for Phase P-2b. It:

    1. Takes :class:`DisclosureTitleDTO` seeds from :class:`LiveDisclosureSeedService`
    2. Builds search queries via :class:`DisclosureQueryBuilder`
    3. Searches NAVER via :class:`NaverNewsSearchAdapter`
    4. Applies **hard gate** (종목명 + 핵심어 필수 체크)
    5. Deduplicates and scores results
    6. Returns sorted, capped :class:`SeededNewsCandidate` list

    Results are **memory-only** — not persisted to ExternalEventRepository.
    Persistence will be added when EI integration is connected (next turn).

    Structured quality metrics (:class:`PipelineMetrics`) are emitted on every
    ``process_seeds()`` call for sample verification and quality comparison.
    """

    def __init__(
        self,
        search_adapter: NaverNewsSearchAdapter,
        query_builder: DisclosureQueryBuilder | None = None,
    ) -> None:
        self._search_adapter = search_adapter
        self._query_builder = query_builder or DisclosureQueryBuilder()

    async def process_seeds(
        self,
        seeds: Sequence[DisclosureTitleDTO],
    ) -> tuple[list[SeededNewsCandidate], PipelineMetrics]:
        """Process multiple disclosure seeds through the pipeline.

        Parameters
        ----------
        seeds : Sequence[DisclosureTitleDTO]
            KIS disclosure title seeds from :class:`LiveDisclosureSeedService`.

        Returns
        -------
        tuple[list[SeededNewsCandidate], PipelineMetrics]
            Tuple of (scored, deduplicated, top-N limited candidates, PipelineMetrics).
            First element is empty if no seeds provided or all fallbacks triggered.
        """
        metrics = PipelineMetrics(seeds_total=len(seeds))

        if not seeds:
            logger.warning(
                "SeededNewsCandidateService: no seeds provided — returning []",
            )
            self._log_metrics(metrics)
            return [], metrics

        all_candidates: list[SeededNewsCandidate] = []
        seed_quality_drops = 0

        for idx, seed in enumerate(seeds):
            # Seed pacing: delay between seeds to avoid 429 Rate Limit
            if idx > 0:
                await asyncio.sleep(_SEED_PACING_DELAY)

            # Seed quality filter: skip suspicious seeds
            if not self._validate_seed_company_name(seed, seed.symbol):
                logger.warning(
                    "SeededNewsCandidateService: seed quality filter dropped "
                    "symbol=%s company=%s",
                    seed.symbol,
                    seed.company_name,
                )
                seed_quality_drops += 1
                continue

            candidates, seed_metrics = await self._process_one_seed(seed)
            all_candidates.extend(candidates)

            # Accumulate per-symbol metrics (seed-level counts)
            metrics.seeds_with_queries += 1 if seed_metrics.get("has_queries") else 0
            metrics.seeds_with_results += 1 if candidates else 0
            metrics.queries_executed += seed_metrics.get("queries_count", 0)
            metrics.raw_candidates_fetched += seed_metrics.get("raw_count", 0)
            metrics.hard_gate_passed += seed_metrics.get("hard_gate_passed", 0)
            metrics.hard_gate_dropped += seed_metrics.get("hard_gate_dropped", 0)
            metrics.deduped_count += seed_metrics.get("deduped_count", 0)
            metrics.kept_count += len(candidates)
            metrics.dropped_low_confidence += seed_metrics.get(
                "dropped_low_confidence", 0,
            )
            metrics.dropped_cross_symbol += seed_metrics.get(
                "dropped_cross_symbol", 0,
            )
            metrics.retry_count += seed_metrics.get("retry_count", 0)

            metrics.per_symbol[seed.symbol] = {
                "raw": seed_metrics.get("raw_count", 0),
                "hard_gate_passed": seed_metrics.get("hard_gate_passed", 0),
                "hard_gate_dropped": seed_metrics.get("hard_gate_dropped", 0),
                "deduped": seed_metrics.get("deduped_count", 0),
                "scored_before_threshold": seed_metrics.get("scored_count", 0),
                "dropped_low_confidence": seed_metrics.get(
                    "dropped_low_confidence", 0,
                ),
                "dropped_cross_symbol": seed_metrics.get("dropped_cross_symbol", 0),
                "kept": len(candidates),
            }

        metrics.seed_quality_drop_count = seed_quality_drops

        # Sort by confidence_score descending (global rank)
        all_candidates.sort(
            key=lambda c: c.confidence_score,
            reverse=True,
        )

        # Step: Global per-symbol top-N enforcement
        from collections import defaultdict

        per_symbol: dict[str, list[SeededNewsCandidate]] = defaultdict(list)
        for c in all_candidates:
            per_symbol[c.symbol].append(c)

        final: list[SeededNewsCandidate] = []
        for sym, candidates in per_symbol.items():
            candidates.sort(key=lambda x: x.confidence_score, reverse=True)
            final.extend(candidates[:_MAX_CANDIDATES_PER_SYMBOL_GLOBAL])

        final.sort(key=lambda c: c.confidence_score, reverse=True)
        all_candidates = final

        # Recompute kept_count to reflect global per-symbol Top-N
        metrics.kept_count = len(all_candidates)

        # Update per_symbol "kept" to reflect global Top-N
        fresh_per_symbol: dict[str, int] = defaultdict(int)
        for c in all_candidates:
            fresh_per_symbol[c.symbol] += 1
        for sym in metrics.per_symbol:
            metrics.per_symbol[sym]["kept"] = fresh_per_symbol.get(sym, 0)

        self._log_metrics(metrics)
        return all_candidates, metrics

    def _log_metrics(self, metrics: PipelineMetrics) -> None:
        """Emit structured quality metrics as a single INFO log line."""
        logger.info(
            "SeededNewsCandidateService metrics: "
            "seeds=%d queries=%d raw=%d gate+%d/gate-%d "
            "deduped=%d low_conf=%d cross_sym=%d seed_q_drop=%d retry=%d kept=%d",
            metrics.seeds_total,
            metrics.queries_executed,
            metrics.raw_candidates_fetched,
            metrics.hard_gate_passed,
            metrics.hard_gate_dropped,
            metrics.deduped_count,
            metrics.dropped_low_confidence,
            metrics.dropped_cross_symbol,
            metrics.seed_quality_drop_count,
            metrics.retry_count,
            metrics.kept_count,
        )
        # Per-symbol breakdown at DEBUG level
        if logger.isEnabledFor(logging.DEBUG):
            for symbol, sm in metrics.per_symbol.items():
                logger.debug(
                    "  symbol=%s raw=%d gate+%d/gate-%d deduped=%d "
                    "scored=%d drop=%d cross_sym=%d kept=%d",
                    symbol,
                    sm["raw"],
                    sm["hard_gate_passed"],
                    sm["hard_gate_dropped"],
                    sm["deduped"],
                    sm["scored_before_threshold"],
                    sm["dropped_low_confidence"],
                    sm.get("dropped_cross_symbol", 0),
                    sm["kept"],
                )

    async def _process_one_seed(
        self,
        seed: DisclosureTitleDTO,
    ) -> tuple[list[SeededNewsCandidate], dict[str, int]]:
        """Process a single disclosure seed through the pipeline.

        Parameters
        ----------
        seed : DisclosureTitleDTO
            Single KIS disclosure seed.

        Returns
        -------
        tuple[list[SeededNewsCandidate], dict[str, int]]
            Candidates list and per-seed metrics dict.
        """
        seed_metrics: dict[str, int] = {
            "has_queries": 0,
            "queries_count": 0,
            "raw_count": 0,
            "hard_gate_passed": 0,
            "hard_gate_dropped": 0,
            "deduped_count": 0,
            "scored_count": 0,
            "dropped_low_confidence": 0,
            "dropped_cross_symbol": 0,
            "retry_count": 0,
        }

        # Step 1: Build queries
        queries = self._query_builder.build_queries(seed)
        seed_metrics["has_queries"] = 1 if queries else 0
        seed_metrics["queries_count"] = len(queries)

        if not queries:
            logger.warning(
                "SeededNewsCandidateService: no queries for symbol=%s",
                seed.symbol,
            )
            return [], seed_metrics

        # Step 2: Search NAVER
        try:
            raw_items = await self._search_adapter.search_by_seed(seed, queries)
        except Exception:
            logger.exception(
                "SeededNewsCandidateService: NAVER search failed "
                "for symbol=%s — returning []",
                seed.symbol,
            )
            return [], seed_metrics

        seed_metrics["raw_count"] = len(raw_items)

        if not raw_items:
            logger.info(
                "SeededNewsCandidateService: no raw items for symbol=%s",
                seed.symbol,
            )
            return [], seed_metrics

        # Step 3: Hard Gate — 종목명 + 핵심어 필수 체크
        hard_gated = self._apply_hard_gate(raw_items, seed)
        seed_metrics["hard_gate_passed"] = len(hard_gated)
        seed_metrics["hard_gate_dropped"] = len(raw_items) - len(hard_gated)

        if not hard_gated:
            logger.info(
                "SeededNewsCandidateService: all %d items failed hard gate "
                "for symbol=%s",
                len(raw_items),
                seed.symbol,
            )
            return [], seed_metrics

        # Step 4: Deduplicate and score (with cross-symbol noise detection)
        scored, cross_symbol_count = self._score_and_rank(hard_gated, seed)
        seed_metrics["deduped_count"] = len(scored)
        seed_metrics["dropped_cross_symbol"] = cross_symbol_count

        # Step 5: Threshold filter
        qualified = [
            c for c in scored if c.confidence_score >= _SCORE_THRESHOLD
        ]
        seed_metrics["scored_count"] = len(scored)
        seed_metrics["dropped_low_confidence"] = len(scored) - len(qualified)

        # Step 6: Top-N per symbol
        top_n = qualified[:_MAX_CANDIDATES_PER_SEED]

        logger.info(
            "SeededNewsCandidateService: symbol=%s raw=%d gate+%d/gate-%d "
            "deduped=%d scored=%d qualified=%d top=%d",
            seed.symbol,
            len(raw_items),
            seed_metrics["hard_gate_passed"],
            seed_metrics["hard_gate_dropped"],
            seed_metrics["deduped_count"],
            seed_metrics["scored_count"],
            len(qualified),
            len(top_n),
        )
        return top_n, seed_metrics

    def _apply_hard_gate(
        self,
        items: list[NaverNewsItem],
        seed: DisclosureTitleDTO,
    ) -> list[NaverNewsItem]:
        """Apply hard gate: 종목명 + 핵심어 필수 체크.

        Rules (score 계산 전 탈락):
        1. title 또는 description에 종목명(company_name)이 있어야 함
        2. 그리고 title에 seed 핵심어가 1개 이상 겹치거나,
           seed headline과 제목 Jaccard 유사도가 0.3 이상이어야 함

        Parameters
        ----------
        items : list[NaverNewsItem]
            Raw NAVER news items before scoring.
        seed : DisclosureTitleDTO
            The KIS disclosure seed.

        Returns
        -------
        list[NaverNewsItem]
            Items that passed the hard gate. Empty if none passed.
        """
        if not seed.company_name:
            # company_name이 없으면 hard gate 우회 (fallback 허용)
            return list(items)

        company_name_lower = seed.company_name.lower()
        seed_keywords = self._query_builder._extract_keywords(
            seed.headline or "",
        )

        passed: list[NaverNewsItem] = []
        for item in items:
            title_clean = self._strip_html(item.title).lower()
            desc_clean = self._strip_html(
                item.description or "",
            ).lower()

            # Rule 1: 종목명이 title 또는 description에 있어야 함
            if (
                company_name_lower not in title_clean
                and company_name_lower not in desc_clean
            ):
                continue

            # Rule 2: title에 핵심어 1개 이상 겹치거나 제목 유사도 >= 0.3
            has_keyword_overlap = any(
                kw.lower() in title_clean for kw in seed_keywords
            )
            title_similarity = self._title_similarity(
                item.title,
                seed.headline or "",
            )

            if has_keyword_overlap or title_similarity >= 0.3:
                passed.append(item)

        return passed

    def _score_and_rank(
        self,
        items: list[NaverNewsItem],
        seed: DisclosureTitleDTO,
    ) -> tuple[list[SeededNewsCandidate], int]:
        """Score, deduplicate, and rank raw NAVER items.

        Pipeline:
        1. originallink 기준 중복 제거
        2. Jaccard-like title similarity dedupe (>0.85 = duplicate)
        3. 개별 Scoring (cross-symbol noise penalty 포함)
        4. Score descending 정렬

        Parameters
        ----------
        items : list[NaverNewsItem]
            Pre-deduped (intra-batch) raw items.
        seed : DisclosureTitleDTO
            The KIS disclosure seed.

        Returns
        -------
        tuple[list[SeededNewsCandidate], int]
            (Scored candidates sorted by confidence_score descending,
             count of items detected as cross-symbol noise).
        """
        # Phase 1: Dedupe by originallink
        seen_links: set[str] = set()
        deduped: list[NaverNewsItem] = []
        for item in items:
            dedup_key = item.originallink or item.link
            if dedup_key in seen_links:
                continue
            seen_links.add(dedup_key)
            deduped.append(item)

        # Phase 2: Title similarity dedupe (Jaccard-like)
        # Keep first occurrence, skip items with >85% token overlap
        deduped_titles: list[NaverNewsItem] = []
        for item in deduped:
            is_duplicate = False
            for existing in deduped_titles:
                if self._title_similarity(item.title, existing.title) > 0.85:
                    is_duplicate = True
                    break
            if not is_duplicate:
                deduped_titles.append(item)

        # Phase 3: Score each candidate
        company_name = seed.company_name or ""
        symbol = seed.symbol or ""
        candidates: list[SeededNewsCandidate] = []
        cross_symbol_count = 0

        for item in deduped_titles:
            score = self._compute_score(item, seed, company_name, symbol)
            candidate = SeededNewsCandidate(
                symbol=seed.symbol,
                company_name=seed.company_name,
                seed_headline=seed.headline,
                related_news_title=self._strip_html(item.title),
                related_news_summary=self._strip_html(item.description)
                if item.description
                else None,
                link=item.link,
                published_at=self._parse_datetime(item.pubDate),
                source="naver_news_seeded",
                confidence_score=score,
                seed_source="kis_disclosure_live",
                originallink=item.originallink or None,
            )
            candidates.append(candidate)

            # Track cross-symbol noise
            is_noise, _ = self._is_cross_symbol_noise(
                item, company_name, symbol,
            )
            if is_noise:
                cross_symbol_count += 1

        # Sort by score descending
        candidates.sort(
            key=lambda c: c.confidence_score,
            reverse=True,
        )
        return candidates, cross_symbol_count

    def _compute_score(
        self,
        item: NaverNewsItem,
        seed: DisclosureTitleDTO,
        company_name: str = "",
        symbol: str = "",
    ) -> float:
        """Compute relevance score for a NAVER news item against a seed.

        Scoring components (total 0-100):

        ============================ ====== ====================================
        Component                    Max    Notes
        ============================ ====== ====================================
        Company name match in title    20   종목명이 title에 있으면 +20 (하향)
        Symbol in description          20   종목코드가 description에 있으면 +20
        Symbol in title                25   종목코드가 title에 있으면 +25 (상향)
        Keyword overlap                 0~35  seed 핵심어 1개당 +10 (max 35)
        Freshness                       0~20  within 24h=20, within 72h=10
        Description quality            0~5   길이 50자↑=+5, 20자↑=+2
        Cross-symbol noise penalty   ×0.3   회사명 불일치 시 70% 감점
        ============================ ====== ====================================

        Total capped at 100.
        """
        score = 0.0
        title_clean = self._strip_html(item.title).lower()
        desc_clean = self._strip_html(
            item.description,
        ).lower() if item.description else ""
        company_lower = company_name.lower()

        # 1. Company name match in title (하향: 40→20)
        if company_name and company_lower in title_clean:
            score += 20.0
        elif company_name and company_lower in desc_clean:
            score += 10.0  # description만 있으면 +10

        # 2. Symbol match (상향: 10→20, title에 있으면 +25)
        if symbol:
            if symbol in title_clean:
                score += 25.0
            elif symbol in desc_clean:
                score += 20.0

        # 3. Keyword overlap (+0~35, capped)
        keyword_overlap = self._query_builder.get_keyword_overlap(
            seed.headline or "",
            item.title,
        )
        score += min(keyword_overlap * 10, 35)

        # 4. Freshness (+0~20)
        pub_dt = self._parse_datetime(item.pubDate)
        if pub_dt is not None:
            hours_ago = (
                datetime.now(timezone.utc) - pub_dt
            ).total_seconds() / 3600
            if hours_ago < 24:
                score += 20
            elif hours_ago < 72:
                score += 10

        # 5. Description quality (+0~5, 약한 보조 신호)
        desc_len = len(self._strip_html(item.description or ""))
        if desc_len > 50:
            score += 5
        elif desc_len > 20:
            score += 2

        # 6. Cross-symbol noise penalty
        is_noise, penalty = self._is_cross_symbol_noise(
            item, company_name, symbol,
        )
        if is_noise:
            score *= penalty

        return min(score, 100.0)  # cap at 100

    def _is_cross_symbol_noise(
        self,
        candidate: NaverNewsItem,
        seed_company_name: str,
        seed_symbol: str,
    ) -> tuple[bool, float]:
        """
        Detect cross-symbol noise.

        Cross-symbol noise occurs when a NAVER news result mentions a DIFFERENT
        company than the seed's symbol. Example: seed.company_name="한미반도체"
        but symbol="000660" (SK하이닉스). The news may be about SK하이닉스 but
        the seed's company_name doesn't match.

        Detection logic:
        - If the candidate's title/description does NOT mention the seed's
          company_name at all, it's likely about a different company.
        - This is a Scoring-level penalty, NOT Hard Gate 차단 (False Negative
          방지).

        Returns
        -------
        tuple[bool, float]
            (is_noise, penalty_factor):
            - is_noise: True if the candidate appears to be about a different company
            - penalty_factor: 0.0~1.0 (1.0 = no penalty, 0.3 = 70% score reduction)
        """
        if not seed_company_name or not seed_symbol:
            return (False, 1.0)

        title_lower = (candidate.title or "").lower()
        desc_lower = (candidate.description or "").lower()
        seed_company_lower = seed_company_name.lower()

        # Check if the candidate's title/description mentions the seed's company_name
        company_in_title = seed_company_lower in title_lower
        company_in_desc = seed_company_lower in desc_lower

        if not company_in_title and not company_in_desc:
            # Candidate does NOT mention the seed's company at all
            # This is likely cross-symbol noise
            logger.debug(
                "Cross-symbol noise detected: seed_company=%s seed_symbol=%s "
                "title=%r",
                seed_company_name,
                seed_symbol,
                candidate.title,
            )
            return (True, 0.3)  # 70% penalty

        return (False, 1.0)

    def _validate_seed_company_name(
        self,
        seed: DisclosureTitleDTO,
        symbol: str,
    ) -> bool:
        """
        Quick validation: does the seed's company_name look like it belongs
        to this symbol?

        Basic heuristic: company_name should be at least 2 characters.
        Very short company_name strings are suspicious and likely data errors.

        Returns True if seed looks valid, False if suspicious.
        """
        if not seed.company_name or not symbol:
            return True  # can't validate, pass through

        # Basic heuristic: if company_name is very short (< 2 chars), it's suspicious
        if len(seed.company_name.strip()) < 2:
            logger.warning(
                "Suspicious seed company_name (too short): symbol=%s company=%r",
                symbol,
                seed.company_name,
            )
            return False

        return True

    @staticmethod
    def _title_similarity(title_a: str, title_b: str) -> float:
        """Compute Jaccard-like token overlap similarity between two titles.

        Parameters
        ----------
        title_a : str
            First title (may contain HTML).
        title_b : str
            Second title (may contain HTML).

        Returns
        -------
        float
            Jaccard similarity (0.0 to 1.0).  0.0 if either is empty.
        """
        tokens_a = set(
            SeededNewsCandidateService._strip_html(title_a).split(),
        )
        tokens_b = set(
            SeededNewsCandidateService._strip_html(title_b).split(),
        )

        if not tokens_a or not tokens_b:
            return 0.0

        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(intersection) / len(union)

    @staticmethod
    def _strip_html(text: str) -> str:
        """Remove HTML tags from NAVER API response text.

        NAVER News Search API 응답의 ``title``과 ``description`` 필드에는
        ``<b>`` 태그와 HTML entity (``"``, ``<`` 등)가 포함될 수 있음.
        이 메서드는 태그를 제거하고 ``html.unescape()``로 entity를 디코딩한다.
        """
        import html as _html
        import re

        text = re.sub(r"<[^>]+>", "", text)
        text = _html.unescape(text)
        return text.strip()

    @staticmethod
    def _parse_datetime(pub_date: str) -> datetime | None:
        """Parse NAVER ``pubDate`` (RFC 822) to :class:`datetime`.

        Returns ``datetime`` (정규화 완료, timezone-aware) or ``None`` if
        unparseable.  외부 표시 단계에서만 문자열 변환.

        NAVER API 응답 형식 예: ``Wed, 17 May 2026 10:00:00 +0900``
        """
        if not pub_date:
            return None
        try:
            from email.utils import parsedate_to_datetime

            return parsedate_to_datetime(pub_date)
        except Exception:
            logger.debug(
                "SeededNewsCandidateService: failed to parse pubDate=%r",
                pub_date,
            )
            return None

    async def close(self) -> None:
        """Close underlying adapter HTTP client."""
        try:
            await self._search_adapter.close()
        except Exception:
            logger.exception(
                "SeededNewsCandidateService: error closing search adapter",
            )
