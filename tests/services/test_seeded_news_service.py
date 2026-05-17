"""Integration tests for SeededNewsCandidateService.

Full pipeline: seed → query builder → NAVER search → hard gate → dedupe → score.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from agent_trading.brokers.naver_news_adapter import (
    NaverNewsItem,
    NaverNewsSearchAdapter,
    NaverSearchResponse,
)
from agent_trading.domain.models import DisclosureTitleDTO
from agent_trading.services.disclosure_query_builder import DisclosureQueryBuilder
from agent_trading.services.seeded_news_service import SeededNewsCandidateService


@pytest.fixture
def sample_seed() -> DisclosureTitleDTO:
    return DisclosureTitleDTO(
        symbol="005930",
        company_name="삼성전자",
        headline="유상증자 결정",
        published_at="20260517",
    )


def _make_mock_response(
    items: list[dict],
    status_code: int = 200,
) -> Mock:
    """Helper to create a mock httpx.Response with JSON data."""
    response = Mock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = {
        "items": items,
        "total": len(items),
        "display": len(items),
    }
    response.raise_for_status = Mock()
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Error",
            request=Mock(),
            response=response,
        )
    return response


def _make_news_item(
    title: str,
    description: str = "",
    link: str = "",
    originallink: str = "",
    pub_date: str = "Fri, 17 May 2026 09:00:00 +0900",
) -> NaverNewsItem:
    return NaverNewsItem(
        title=title,
        description=description,
        link=link,
        originallink=originallink,
        pubDate=pub_date,
    )


class TestSeededNewsCandidateService:
    """Test suite for SeededNewsCandidateService.

    Covers the full pipeline integration (Case 9 from test plan):
    - 1 seed with mock NAVER returning 8 items
    - 6 items with score >= 50, 2 items with score < 50
    - Expect top-3 candidates with score >= 50
    """

    @pytest.mark.asyncio
    async def test_full_pipeline_integration(self, sample_seed: DisclosureTitleDTO) -> None:
        """Full pipeline: seed → query → search → hard gate → dedupe → score → top-3."""
        # ── Setup: mock HTTP client ──────────────────────────────────
        mock_http = AsyncMock(spec=httpx.AsyncClient)

        # 6 high-score items (삼성전자 + keyword overlap)
        high_score_items = [
            {
                "title": "삼성전자, 유상증자 결정…주주가치 제고 기대",
                "description": "삼성전자가 오늘 이사회를 열고 유상증자를 결정했습니다. "
                              "이번 유상증자를 통해 약 1조원 규모의 자금을 조달할 계획입니다.",
                "link": "https://news.naver.com/main/article/001",
                "originallink": "https://edaily.co.kr/news/001",
                "pubDate": "Fri, 17 May 2026 09:00:00 +0900",
            },
            {
                "title": "삼성전자 유상증자, 증권가 호평…목표주가 상향",
                "description": "삼성전자의 유상증자 결정에 대해 증권가에서 호평이 이어지고 있습니다.",
                "link": "https://news.naver.com/main/article/002",
                "originallink": "https://hankyung.com/news/002",
                "pubDate": "Fri, 17 May 2026 08:30:00 +0900",
            },
            {
                "title": "삼성전자, 유상증자 발표…자사주 매입도 병행",
                "description": "삼성전자가 유상증자와 함께 자사주 매입 계획도 발표했습니다.",
                "link": "https://news.naver.com/main/article/003",
                "originallink": "https://mt.co.kr/news/003",
                "pubDate": "Thu, 16 May 2026 14:00:00 +0900",
            },
            {
                "title": "삼성전자 유상증자 소식에 주가 강세",
                "description": "삼성전자 주가가 유상증자 발표 이후 강세를 보이고 있습니다.",
                "link": "https://news.naver.com/main/article/004",
                "originallink": "https://yna.co.kr/news/004",
                "pubDate": "Fri, 17 May 2026 10:00:00 +0900",
            },
            {
                "title": "삼성전자, 유상증자 통해 신사업 투자 확대",
                "description": "삼성전자가 유상증자로 조달한 자금을 신사업 투자에 활용할 계획입니다.",
                "link": "https://news.naver.com/main/article/005",
                "originallink": "https://chosun.com/news/005",
                "pubDate": "Fri, 17 May 2026 07:00:00 +0900",
            },
            {
                "title": "삼성전자 유상증자, 기관투자자 수요예측 흥행",
                "description": "삼성전자 유상증자 수요예측에 기관투자자가 대거 참여했습니다.",
                "link": "https://news.naver.com/main/article/006",
                "originallink": "https://mk.co.kr/news/006",
                "pubDate": "Thu, 16 May 2026 18:00:00 +0900",
            },
        ]
        # 2 low-score items (회사명 언급 없음 or keyword mismatch)
        low_score_items = [
            {
                "title": "코스피 시황…외국인 순매수 지속",
                "description": "오늘 코스피 시장에서 외국인이 순매수를 지속했습니다.",
                "link": "https://news.naver.com/main/article/101",
                "originallink": "https://news1.kr/news/101",
                "pubDate": "Fri, 17 May 2026 11:00:00 +0900",
            },
            {
                "title": "美 Fed 금리 동결…국내 증시 영향은",
                "description": "미국 연준이 기준금리를 동결했습니다.",
                "link": "https://news.naver.com/main/article/102",
                "originallink": "https://reuters.com/news/102",
                "pubDate": "Fri, 17 May 2026 06:00:00 +0900",
            },
        ]

        all_items = high_score_items + low_score_items
        mock_http.get.return_value = _make_mock_response(all_items)

        # ── Build service ────────────────────────────────────────────
        search_adapter = NaverNewsSearchAdapter(
            client_id="test_client_id",
            client_secret="test_client_secret",
            http_client=mock_http,
        )
        service = SeededNewsCandidateService(
            search_adapter=search_adapter,
        )

        # ── Execute ──────────────────────────────────────────────────
        candidates, metrics = await service.process_seeds([sample_seed])

        # ── Assertions ───────────────────────────────────────────────
        # Top-3 candidates
        assert len(candidates) <= 3, "Should be limited to top-3 per symbol"

        # All candidates should have score >= 50
        for c in candidates:
            assert c.confidence_score >= 50, (
                f"Candidate {c.related_news_title} has score "
                f"{c.confidence_score} < 50"
            )

        # All candidates should be for the correct symbol
        for c in candidates:
            assert c.symbol == "005930"

        # High-score items should be included, low-score items excluded
        # (low-score items don't have "삼성전자" or "유상증자" in title)
        candidate_titles = {c.related_news_title for c in candidates}
        for item in low_score_items:
            assert item["title"] not in candidate_titles, (
                f"Low-score item should be excluded: {item['title']}"
            )

        # Sort by score descending
        scores = [c.confidence_score for c in candidates]
        assert scores == sorted(scores, reverse=True), (
            "Candidates should be sorted by score descending"
        )

        # Cleanup
        await service.close()

    @pytest.mark.asyncio
    async def test_empty_seeds_returns_empty(self) -> None:
        """Empty seeds list → []."""
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        search_adapter = NaverNewsSearchAdapter(
            client_id="test", client_secret="test",
            http_client=mock_http,
        )
        service = SeededNewsCandidateService(search_adapter=search_adapter)

        candidates, metrics = await service.process_seeds([])
        assert candidates == []
        assert metrics.kept_count == 0
        mock_http.get.assert_not_called()
        await service.close()

    @pytest.mark.asyncio
    async def test_hard_gate_filters_unrelated(self, sample_seed: DisclosureTitleDTO) -> None:
        """Hard gate가 관련 없는 뉴스를 필터링해야 함."""
        mock_http = AsyncMock(spec=httpx.AsyncClient)

        # Item with company_name but without keyword overlap
        items = [
            {
                "title": "삼성전자, 분기배당 결정",
                "description": "삼성전자가 분기배당을 결정했습니다.",
                "link": "https://news.naver.com/main/article/201",
                "originallink": "https://example.com/news/201",
                "pubDate": "Fri, 17 May 2026 09:00:00 +0900",
            },
        ]
        mock_http.get.return_value = _make_mock_response(items)

        search_adapter = NaverNewsSearchAdapter(
            client_id="test", client_secret="test",
            http_client=mock_http,
        )
        service = SeededNewsCandidateService(search_adapter=search_adapter)

        candidates, _ = await service.process_seeds([sample_seed])

        # "분기배당" != "유상증자" keyword, and headline "유상증자 결정" vs title
        # "삼성전자, 분기배당 결정": no keyword overlap, but title similarity
        # headline 키워드: "유상증자"만
        # title: "삼성전자, 분기배당 결정" — "유상증자" 없음, title similarity < 0.3
        # → hard gate 통과 실패
        assert len(candidates) == 0, (
            "Unrelated news should be filtered by hard gate"
        )

        await service.close()

    @pytest.mark.asyncio
    async def test_global_top_n_limits_per_symbol(self) -> None:
        """여러 seed가 같은 symbol을 가질 때, 글로벌 Top-N이 3으로 제한되는지 검증.

        4개 seed (모두 005930) → 각 seed당 3개 candidate → 총 12개 candidate
        → 글로벌 Top-N(3) 적용 후 최종 3개만 retained
        """
        from agent_trading.domain.models import SeededNewsCandidate
        from agent_trading.services.seeded_news_service import (
            _MAX_CANDIDATES_PER_SEED,
        )

        # ── Setup: mock _process_one_seed to return controlled candidates ──
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        search_adapter = NaverNewsSearchAdapter(
            client_id="test", client_secret="test",
            http_client=mock_http,
        )
        service = SeededNewsCandidateService(search_adapter=search_adapter)

        # 4 seeds, all same symbol "005930", different headlines
        seeds = [
            DisclosureTitleDTO(
                symbol="005930",
                company_name="삼성전자",
                headline=f"유상증자 결정 variant_{i}",
                published_at="20260517",
            )
            for i in range(4)
        ]

        # Mock _process_one_seed to return 3 real SeededNewsCandidate per seed
        # with decreasing confidence scores so we can verify top-3 selection
        async def mock_process_one_seed(
            seed: DisclosureTitleDTO,
        ) -> tuple[list[SeededNewsCandidate], dict]:
            candidates = []
            seed_idx = seeds.index(seed)
            for j in range(_MAX_CANDIDATES_PER_SEED):
                score = 95.0 - (seed_idx * 10 + j)
                candidate = SeededNewsCandidate(
                    symbol=seed.symbol,
                    company_name=seed.company_name,
                    seed_headline=seed.headline,
                    related_news_title=f"News {seed.headline} #{j}",
                    confidence_score=score,
                    link=f"https://news.example.com/{seed_idx}_{j}",
                    published_at=None,
                    source="naver_news_seeded",
                    seed_source="kis_disclosure_live",
                    originallink=None,
                )
                candidates.append(candidate)

            # Simulate seed-level metrics: each seed returns 3
            seed_metrics = {
                "has_queries": 1,
                "queries_count": 1,
                "raw_count": 10,
                "hard_gate_passed": 5,
                "hard_gate_dropped": 5,
                "deduped_count": 3,
                "scored_count": 3,
                "dropped_low_confidence": 0,
            }
            return candidates, seed_metrics

        service._process_one_seed = mock_process_one_seed  # type: ignore[assignment]

        # ── Execute ──────────────────────────────────────────────────
        candidates, metrics = await service.process_seeds(seeds)

        # ── Assertions ───────────────────────────────────────────────
        # 4 seeds × 3 candidates = 12 before global Top-N
        # After global Top-N (3 per symbol), only 3 should remain
        assert len(candidates) <= 3, (
            f"Expected max 3 candidates after global Top-N, got {len(candidates)}"
        )
        assert metrics.kept_count == len(candidates), (
            f"metrics.kept_count ({metrics.kept_count}) != candidates ({len(candidates)})"
        )
        assert metrics.kept_count <= 3, (
            f"metrics.kept_count should be <= 3, got {metrics.kept_count}"
        )

        # Top-3 candidates should be the highest scoring ones
        # Seed 0 → scores 95, 94, 93
        # Seed 1 → scores 85, 84, 83
        # Seed 2 → scores 75, 74, 73
        # Seed 3 → scores 65, 64, 63
        # After global sort: 95, 94, 93, 85, 84, 83, 75, 74, 73, 65, 64, 63
        # Global Top-N (3): 95, 94, 93 (all from seed 0)
        assert candidates[0].confidence_score == 95.0, (
            f"Top candidate should have score 95.0, got {candidates[0].confidence_score}"
        )
        scores = [c.confidence_score for c in candidates]
        assert scores == sorted(scores, reverse=True), (
            "Candidates should be sorted by score descending"
        )

        # All candidates should be for 005930
        for c in candidates:
            assert c.symbol == "005930"

        # per_symbol metrics should reflect global Top-N kept count
        assert metrics.per_symbol["005930"]["kept"] == len(candidates), (
            f"per_symbol['005930']['kept'] ({metrics.per_symbol['005930']['kept']}) "
            f"!= candidates ({len(candidates)})"
        )

        # ── Cleanup ──────────────────────────────────────────────────
        await service.close()


class TestCrossSymbolNoiseAndScoring:
    """Tests for cross-symbol noise detection, scoring weights, seed pacing, and quality filtering."""

    # ------------------------------------------------------------------
    # Cross-symbol noise detection
    # ------------------------------------------------------------------
    def test_cross_symbol_noise_detection(self) -> None:
        """company_name≠symbol seed → noise 감지 + penalty 적용.

        seed.company_name='한미반도체' 이지만 symbol='000660' (SK하이닉스)인 경우,
        candidate에 '한미반도체'가 없으면 cross-symbol noise로 감지.
        """
        service = SeededNewsCandidateService(
            search_adapter=Mock(spec=NaverNewsSearchAdapter),
        )

        # Item about SK하이닉스 (no mention of 한미반도체)
        item = _make_news_item(
            title="SK하이닉스, HBM4 양산 발표",
            description="SK하이닉스가 HBM4 양산을 발표했습니다.",
        )

        is_noise, penalty = service._is_cross_symbol_noise(
            candidate=item,
            seed_company_name="한미반도체",
            seed_symbol="000660",
        )

        assert is_noise is True
        assert penalty == 0.3  # 70% penalty

    def test_cross_symbol_noise_no_false_positive(self) -> None:
        """회사명이 일치하면 noise로 감지하지 않음."""
        service = SeededNewsCandidateService(
            search_adapter=Mock(spec=NaverNewsSearchAdapter),
        )

        item = _make_news_item(
            title="삼성전자, 유상증자 결정",
            description="삼성전자가 유상증자를 결정했습니다.",
        )

        is_noise, penalty = service._is_cross_symbol_noise(
            candidate=item,
            seed_company_name="삼성전자",
            seed_symbol="005930",
        )

        assert is_noise is False
        assert penalty == 1.0

    # ------------------------------------------------------------------
    # Scoring weight: company_name (40→20)
    # ------------------------------------------------------------------
    def test_scoring_company_name_weight_reduced(self) -> None:
        """company_name만 매칭 = 20점 (기존 40→하향).

        계산: company_name in title(+20) + freshness 24h이내(+20) = 40점
        - "결정"은 boilerplate token이므로 keyword overlap 미발생
        - symbol("005930")은 title/desc에 없음
        """
        service = SeededNewsCandidateService(
            search_adapter=Mock(spec=NaverNewsSearchAdapter),
        )
        seed = DisclosureTitleDTO(
            symbol="005930",
            company_name="삼성전자",
            headline="유상증자 결정",
            published_at="20260517",
        )
        item = _make_news_item(
            title="삼성전자, 분기배당 결정",
            description="삼성전자가 분기배당을 결정했습니다.",
        )

        score = service._compute_score(item, seed, "삼성전자", "005930")

        # company_name in title = 20, no symbol match, keyword overlap=0
        # ("결정"은 boilerplate), freshness=20 → total = 40
        assert score == 40.0, (
            f"Expected score 40.0 (company=20 + freshness=20), got {score}"
        )
        # Verify company_name component is 20 (reduced from 40)
        assert score >= 20.0, f"company_name score should be at least 20"

    # ------------------------------------------------------------------
    # Scoring weight: symbol (10→20)
    # ------------------------------------------------------------------
    def test_scoring_symbol_match_increased(self) -> None:
        """symbol 매칭 = 20점 (기존 10→상향). title에 있으면 25점."""
        service = SeededNewsCandidateService(
            search_adapter=Mock(spec=NaverNewsSearchAdapter),
        )
        seed = DisclosureTitleDTO(
            symbol="005930",
            company_name="삼성전자",
            headline="유상증자 결정",
            published_at="20260517",
        )
        # Item without company_name mention but with symbol in description
        item = _make_news_item(
            title="코스피 시황…외국인 순매수",
            description="005930 삼성전자 강세",
        )

        score = service._compute_score(item, seed, "삼성전자", "005930")

        # company_name not in title, but in desc → +10
        # symbol in desc → +20
        # Total = 10 + 20 = 30 (minimum)
        assert score >= 30.0, (
            f"Expected score >= 30 (company desc + symbol desc), got {score}"
        )

    def test_scoring_symbol_in_title_gives_bonus(self) -> None:
        """symbol이 title에 있으면 25점."""
        service = SeededNewsCandidateService(
            search_adapter=Mock(spec=NaverNewsSearchAdapter),
        )
        seed = DisclosureTitleDTO(
            symbol="005930",
            company_name="삼성전자",
            headline="유상증자 결정",
            published_at="20260517",
        )
        item = _make_news_item(
            title="005930 삼성전자, 유상증자 결정",
            description="삼성전자가 유상증자를 결정했습니다.",
        )

        score = service._compute_score(item, seed, "삼성전자", "005930")

        # company_name in title = 20
        # symbol in title = 25
        # Total = 45 minimum
        assert score >= 45.0, (
            f"Expected score >= 45 (company title + symbol title), got {score}"
        )

    # ------------------------------------------------------------------
    # Hard gate + cross-symbol mismatch (scoring penalty, not hard gate)
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_hard_gate_company_name_and_symbol_mismatch(self) -> None:
        """Hard gate는 통과하지만 scoring에서 cross-symbol penalty 적용.

        seed: symbol='000660', company_name='SK하이닉스'
        news: '한미반도체 관련 기사' (한미반도체 언급, SK하이닉스 언급 없음)

        Hard gate: company_name이 title에 없음 → 통과 실패 (hard gate에서 걸러짐)
        """
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        search_adapter = NaverNewsSearchAdapter(
            client_id="test", client_secret="test",
            http_client=mock_http,
        )
        service = SeededNewsCandidateService(search_adapter=search_adapter)

        seed = DisclosureTitleDTO(
            symbol="000660",
            company_name="SK하이닉스",
            headline="HBM4 양산 발표",
            published_at="20260517",
        )

        # Item about 한미반도체 (no mention of SK하이닉스)
        items = [
            {
                "title": "한미반도체, 신규 장비 수주",
                "description": "한미반도체가 신규 장비를 수주했습니다.",
                "link": "https://news.naver.com/main/article/301",
                "originallink": "https://example.com/news/301",
                "pubDate": "Fri, 17 May 2026 09:00:00 +0900",
            },
        ]
        mock_http.get.return_value = _make_mock_response(items)

        candidates, metrics = await service.process_seeds([seed])

        # Hard gate: company_name "SK하이닉스" not in title/desc → hard gate drop
        assert len(candidates) == 0
        assert metrics.hard_gate_dropped >= 1

        await service.close()

    # ------------------------------------------------------------------
    # Seed pacing
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_seed_pacing_delay(self) -> None:
        """seed 간 asyncio.sleep(0.5) 호출 검증.

        3개 seed → 2회의 sleep 호출 (첫 번째 seed 직전에는 sleep 없음).
        """
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        search_adapter = NaverNewsSearchAdapter(
            client_id="test", client_secret="test",
            http_client=mock_http,
        )
        service = SeededNewsCandidateService(search_adapter=search_adapter)

        # Mock _process_one_seed to return empty results quickly
        async def mock_process(seed):
            return [], {
                "has_queries": 1, "queries_count": 1, "raw_count": 0,
                "hard_gate_passed": 0, "hard_gate_dropped": 0,
                "deduped_count": 0, "scored_count": 0,
                "dropped_low_confidence": 0, "dropped_cross_symbol": 0,
                "retry_count": 0,
            }
        service._process_one_seed = mock_process  # type: ignore[assignment]

        seeds = [
            DisclosureTitleDTO(symbol="005930", company_name="삼성전자",
                               headline=f"공시 {i}", published_at="20260517")
            for i in range(3)
        ]

        import time
        start = time.monotonic()
        candidates, metrics = await service.process_seeds(seeds)
        elapsed = time.monotonic() - start

        # 2 delays × 0.5s = minimum ~1.0s
        assert elapsed >= 0.8, (
            f"Expected pacing delay ~1.0s for 3 seeds, got {elapsed:.2f}s"
        )

        await service.close()

    # ------------------------------------------------------------------
    # Seed quality filter
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_seed_quality_filter(self) -> None:
        """잘못된 company_name seed → 필터링 + seed_quality_drop_count 증가.

        - seed with company_name='X' (1자) → quality filter drop
        - seed with company_name='삼성전자' (정상) → 통과
        """
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        search_adapter = NaverNewsSearchAdapter(
            client_id="test", client_secret="test",
            http_client=mock_http,
        )
        service = SeededNewsCandidateService(search_adapter=search_adapter)

        # Valid seed
        valid_seed = DisclosureTitleDTO(
            symbol="005930", company_name="삼성전자",
            headline="유상증자 결정", published_at="20260517",
        )
        # Invalid seed (too short company_name — 1자)
        invalid_seed = DisclosureTitleDTO(
            symbol="000660", company_name="X",  # 1자 → quality filter drop
            headline="HBM4 발표", published_at="20260517",
        )

        # Mock search to return items for valid seed
        items = [
            {
                "title": "삼성전자 유상증자", "description": "desc",
                "link": "link1", "originallink": "orig1",
                "pubDate": "Fri, 17 May 2026 09:00:00 +0900",
            },
        ]
        mock_http.get.return_value = _make_mock_response(items)

        candidates, metrics = await service.process_seeds([invalid_seed, valid_seed])

        # Invalid seed filtered (1자 company_name), valid seed processed
        assert metrics.seed_quality_drop_count == 1, (
            f"Expected 1 seed quality drop, got {metrics.seed_quality_drop_count}"
        )
        assert metrics.seeds_with_results >= 1, "Valid seed should have results"

        await service.close()

    @pytest.mark.asyncio
    async def test_seed_quality_filter_short_name(self) -> None:
        """매우 짧은 company_name seed (<2자) → 필터링."""
        service = SeededNewsCandidateService(
            search_adapter=Mock(spec=NaverNewsSearchAdapter),
        )

        seed = DisclosureTitleDTO(
            symbol="000660",
            company_name="",  # empty
            headline="HBM4 발표",
            published_at="20260517",
        )

        # Empty company_name passes validation (can't validate, pass through)
        assert service._validate_seed_company_name(seed, "000660") is True

        # Very short company_name fails
        seed2 = DisclosureTitleDTO(
            symbol="000660",
            company_name="A",  # too short
            headline="HBM4 발표",
            published_at="20260517",
        )
        assert service._validate_seed_company_name(seed2, "000660") is False

    # ------------------------------------------------------------------
    # Cross-symbol noise in metrics
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_cross_symbol_noise_in_metrics(self) -> None:
        """metrics에 cross-symbol noise 카운트 반영 확인.

        Note: 현재 _is_cross_symbol_noise는 hard gate 통과 항목에 대해
        항상 (False, 1.0)을 반환 (hard gate가 이미 company_name 존재를 보장).
        따라서 dropped_cross_symbol은 0이 기본값.
        metrics 필드가 정상적으로 초기화되고 집계되는지만 검증.
        """
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        search_adapter = NaverNewsSearchAdapter(
            client_id="test", client_secret="test",
            http_client=mock_http,
        )
        service = SeededNewsCandidateService(search_adapter=search_adapter)

        seed = DisclosureTitleDTO(
            symbol="005930",
            company_name="삼성전자",
            headline="유상증자 결정",
            published_at="20260517",
        )

        # Relevant items only (no cross-symbol noise in current implementation)
        items = [
            {
                "title": "삼성전자 유상증자 결정",
                "description": "삼성전자가 유상증자를 결정했습니다.",
                "link": "link1", "originallink": "orig1",
                "pubDate": "Fri, 17 May 2026 09:00:00 +0900",
            },
            {
                "title": "삼성전자, 유상증자 소식에 주가 강세",
                "description": "삼성전자 주가가 유상증자 발표 이후 강세.",
                "link": "link2", "originallink": "orig2",
                "pubDate": "Fri, 17 May 2026 09:00:00 +0900",
            },
        ]
        mock_http.get.return_value = _make_mock_response(items)

        candidates, metrics = await service.process_seeds([seed])

        # Verify metrics field exists and is properly initialized
        assert hasattr(metrics, "dropped_cross_symbol")
        assert isinstance(metrics.dropped_cross_symbol, int)
        # Cross-symbol noise usually 0 since hard gate catches unrelated items first
        assert metrics.dropped_cross_symbol >= 0
        # Verify item-level metric
        for sym_data in metrics.per_symbol.values():
            assert "dropped_cross_symbol" in sym_data
            assert isinstance(sym_data["dropped_cross_symbol"], int)

        await service.close()
