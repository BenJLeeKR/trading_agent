"""Tests for DisclosureQueryBuilder — KIS disclosure headline → NAVER search query."""
from __future__ import annotations

import pytest

from agent_trading.domain.models import DisclosureTitleDTO
from agent_trading.services.disclosure_query_builder import DisclosureQueryBuilder


class TestDisclosureQueryBuilder:
    """Test suite for DisclosureQueryBuilder.

    Covers 4 test cases from the Phase P-2b test plan:
    1. 핵심어 정상 추출 (boilerplate 제거 + core keyword 보존)
    2. Boilerplate만 있는 경우 (fallback Strategy 2)
    3. 복합 핵심어 포함 (multi-keyword)
    4. Empty headline (graceful fallback)
    """

    def setup_method(self) -> None:
        self.builder = DisclosureQueryBuilder()

    # ------------------------------------------------------------------
    # Case 1: 핵심어 정상 추출
    # ------------------------------------------------------------------
    def test_keyword_extraction_with_boilerplate_removal(self) -> None:
        """boilerplate "결정"이 제거되고 핵심어 "유상증자"가 보존되어야 함."""
        seed = DisclosureTitleDTO(
            symbol="005930",
            company_name="삼성전자",
            headline="유상증자 결정",
            published_at="20260517",
        )
        queries = self.builder.build_queries(seed)

        assert len(queries) >= 1
        # Strategy 1: {company_name} {keywords}
        assert queries[0] == "삼성전자 유상증자"
        # Strategy 2: {company_name} 공시 (fallback)
        assert "삼성전자 공시" in queries

    # ------------------------------------------------------------------
    # Case 2: Boilerplate만 있는 경우 → fallback
    # ------------------------------------------------------------------
    def test_only_boilerplate_tokens_falls_back_to_company_search(self) -> None:
        """모든 토큰이 boilerplate이면 Strategy 2 fallback만 반환."""
        seed = DisclosureTitleDTO(
            symbol="000660",
            company_name="SK하이닉스",
            headline="공시 결정 통보",
            published_at="20260517",
        )
        queries = self.builder.build_queries(seed)

        # Strategy 1: 핵심어가 없으므로 생성되지 않음
        # Strategy 2: {company_name} 공시
        assert queries == ["SK하이닉스 공시"]

    # ------------------------------------------------------------------
    # Case 3: 복합 핵심어 포함
    # ------------------------------------------------------------------
    def test_multi_keyword_extraction(self) -> None:
        """여러 핵심어가 포함된 headline에서 각각 추출되어야 함."""
        seed = DisclosureTitleDTO(
            symbol="035420",
            company_name="NAVER",
            headline="자기주식 취득 신탁계약 체결",
            published_at="20260517",
        )
        queries = self.builder.build_queries(seed)

        assert len(queries) >= 1
        # Strategy 1은 핵심어를 포함
        assert "NAVER" in queries[0]
        assert "자기주식" in queries[0]
        assert "취득" in queries[0]
        # Strategy 2는 항상 fallback으로 추가
        assert "NAVER 공시" in queries

    # ------------------------------------------------------------------
    # Case 4: Empty headline → graceful fallback
    # ------------------------------------------------------------------
    def test_empty_headline_returns_empty_queries(self) -> None:
        """headline이 None이거나 빈 문자열이면 []를 반환해야 함."""
        # None headline
        seed_none = DisclosureTitleDTO(
            symbol="005930",
            company_name="삼성전자",
            headline=None,
        )
        assert self.builder.build_queries(seed_none) == []

        # Empty headline
        seed_empty = DisclosureTitleDTO(
            symbol="005930",
            company_name="삼성전자",
            headline="",
        )
        assert self.builder.build_queries(seed_empty) == []

    # ------------------------------------------------------------------
    # Additional: get_keyword_overlap test
    # ------------------------------------------------------------------
    def test_get_keyword_overlap(self) -> None:
        """get_keyword_overlap()이 정확한 overlap count를 반환해야 함."""
        headline = "유상증자 결정"
        title = "삼성전자, 유상증자 결정…주주가치 제고"
        overlap = self.builder.get_keyword_overlap(headline, title)
        # "유상증자" 1개 overlap (boilerplate "결정"은 제거됨)
        assert overlap >= 1

    def test_get_keyword_overlap_zero(self) -> None:
        """관련 없는 제목에 대해서는 0을 반환해야 함."""
        headline = "유상증자 결정"
        title = "삼성전자, 분기배당 결정"
        # "유상증자"와 "분기배당"은 다르므로 overlap 0
        # headline 키워드: "유상증자"만 (boilerplate "결정" 제거)
        overlap = self.builder.get_keyword_overlap(headline, title)
        assert overlap == 0
