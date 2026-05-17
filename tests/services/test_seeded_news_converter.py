"""Tests for SeededNewsCandidate → ExternalEventEntity conversion."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from agent_trading.domain.models import SeededNewsCandidate
from agent_trading.services.seeded_news_converter import (
    convert_seeded_candidates,
    seeded_candidate_to_event,
    _confidence_to_importance,
    _build_dedup_key,
)


class TestSeededCandidateToEvent:
    """1. SeededNewsCandidate → EI event shape 변환 테스트"""

    def test_basic_conversion(self) -> None:
        """기본 변환: 모든 필드가 올바르게 매핑되는지"""
        candidate = SeededNewsCandidate(
            symbol="005930",
            company_name="삼성전자",
            seed_headline="삼성전자, HBM3E 양산 발표",
            related_news_title="삼성전자 HBM3E, 엔비디아 퀄 테스트 통과",
            related_news_summary="삼성전자의 5세대 HBM인 HBM3E가 엔비디아의 퀄리피케이션 테스트를 통과했다.",
            link="https://n.news.naver.com/article/001",
            originallink="https://news.example.com/hbm3e",
            published_at=datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
            source="naver_news_seeded",
            confidence_score=90.0,
            seed_source="kis_disclosure_live",
            query_used="삼성전자 HBM",
        )
        event = seeded_candidate_to_event(candidate)

        assert event.source_name == "naver_news_seeded"
        assert event.source_reliability_tier == "T3"
        assert event.event_type == "seeded_news"
        assert event.symbol == "005930"
        assert event.headline == "삼성전자 HBM3E, 엔비디아 퀄 테스트 통과"
        assert event.body_summary is not None
        assert "HBM3E" in event.body_summary
        assert event.severity == "medium"
        assert event.direction == "neutral"
        assert event.metadata["confidence_score"] == 90.0
        assert event.metadata["seed_source"] == "kis_disclosure_live"
        assert event.metadata["seed_headline"] == "삼성전자, HBM3E 양산 발표"

    def test_event_id_is_uuid4(self) -> None:
        """event_id가 자동 생성되는지"""
        candidate = SeededNewsCandidate(symbol="005930", related_news_title="title")
        event = seeded_candidate_to_event(candidate)
        assert isinstance(event.event_id, UUID)

    def test_metadata_defaults(self) -> None:
        """기본 confidence(0.0)인 경우 metadata 필드 확인"""
        candidate = SeededNewsCandidate(symbol="005930", related_news_title="title", link="")
        event = seeded_candidate_to_event(candidate)
        assert event.metadata["confidence_score"] == 0.0
        assert event.metadata["article_link"] == ""


class TestConfidenceToImportance:
    """confidence_score → importance 매핑"""

    def test_high(self) -> None:
        assert _confidence_to_importance(90.0) == "high"
        assert _confidence_to_importance(80.0) == "high"

    def test_medium(self) -> None:
        assert _confidence_to_importance(65.0) == "medium"
        assert _confidence_to_importance(50.0) == "medium"

    def test_low(self) -> None:
        assert _confidence_to_importance(30.0) == "low"
        assert _confidence_to_importance(0.0) == "low"


class TestBuildDedupKey:
    """dedup_key_hash 생성"""

    def test_uses_originallink(self) -> None:
        c = SeededNewsCandidate(
            symbol="005930", related_news_title="t",
            link="a", originallink="b",
        )
        key1 = _build_dedup_key(c)
        key2 = _build_dedup_key(c)
        assert key1 == key2  # deterministic
        assert len(key1) == 32  # sha256 hex prefix

    def test_fallback_to_link(self) -> None:
        c = SeededNewsCandidate(
            symbol="005930", related_news_title="t",
            link="url-only", originallink=None,
        )
        key = _build_dedup_key(c)
        assert len(key) == 32


class TestConvertSeededCandidates:
    """2. 리스트 변환 테스트"""

    def test_multiple_candidates(self) -> None:
        candidates = [
            SeededNewsCandidate(symbol="005930", related_news_title="A"),
            SeededNewsCandidate(symbol="005930", related_news_title="B"),
            SeededNewsCandidate(symbol="000660", related_news_title="C"),
        ]
        events = convert_seeded_candidates(candidates)
        assert len(events) == 3
        assert all(e.source_name == "naver_news_seeded" for e in events)
        assert [e.headline for e in events] == ["A", "B", "C"]

    def test_empty_list(self) -> None:
        """3. seeded news 없음 시 기존 경로 회귀 없음"""
        assert convert_seeded_candidates([]) == []


class TestCandidateToEntityPersistable:
    """5. ExternalEventEntity가 DB 저장 가능한 형태인지 검증"""

    def test_all_required_fields_filled(self) -> None:
        """모든 필수 필드가 채워져 DB 저장 가능한지"""
        candidate = SeededNewsCandidate(
            symbol="005930",
            company_name="삼성전자",
            seed_headline="삼성전자, HBM3E 양산 발표",
            related_news_title="삼성전자 HBM3E, 엔비디아 퀄 테스트 통과",
            related_news_summary="삼성전자의 5세대 HBM인 HBM3E가 엔비디아의 퀄리피케이션 테스트를 통과했다.",
            link="https://n.news.naver.com/article/001",
            originallink="https://news.example.com/hbm3e",
            published_at=datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
            source="naver_news_seeded",
            confidence_score=90.0,
            seed_source="kis_disclosure_live",
            query_used="삼성전자 HBM",
            sort_mode="sim",
        )
        event = seeded_candidate_to_event(candidate)

        # DB 저장에 필요한 모든 필드가 None이 아닌지 검증
        assert event.event_id is not None
        assert isinstance(event.event_id, UUID)
        assert event.event_type == "seeded_news"
        assert event.source_name == "naver_news_seeded"
        assert event.published_at is not None
        assert event.source_reliability_tier == "T3"
        assert event.symbol == "005930"
        assert event.ingested_at is not None
        assert event.effective_at is not None
        assert event.severity is not None
        assert event.direction is not None
        assert event.headline is not None
        assert event.dedup_key_hash is not None
        assert len(event.dedup_key_hash) == 32
        assert event.metadata is not None


class TestMetadataProvenanceFields:
    """6. metadata에 provenance 필드 포함 검증"""

    def test_provenance_fields_present(self) -> None:
        """metadata에 pipeline_version, candidate_type, sort_mode 포함"""
        candidate = SeededNewsCandidate(
            symbol="005930",
            related_news_title="test title",
            confidence_score=75.0,
            sort_mode="date",
        )
        event = seeded_candidate_to_event(candidate)

        md = event.metadata
        assert md["pipeline_version"] == "1.0"
        assert md["candidate_type"] == "seeded_news"
        assert md["sort_mode"] == "date"

    def test_provenance_fields_default_sort_mode(self) -> None:
        """sort_mode 기본값 sim 확인"""
        candidate = SeededNewsCandidate(
            symbol="005930",
            related_news_title="test title",
        )
        event = seeded_candidate_to_event(candidate)

        md = event.metadata
        assert md["sort_mode"] == "sim"

    def test_provenance_fields_preserves_existing(self) -> None:
        """provenance 필드 추가로 기존 필드 손실 없음"""
        candidate = SeededNewsCandidate(
            symbol="005930",
            related_news_title="test title",
            confidence_score=60.0,
            seed_source="kis_disclosure_live",
            query_used="test query",
        )
        event = seeded_candidate_to_event(candidate)

        md = event.metadata
        assert md["importance"] == "medium"
        assert md["confidence_score"] == 60.0
        assert md["seed_source"] == "kis_disclosure_live"
        assert md["query_used"] == "test query"


class TestDedupKeyUniqueness:
    """7. dedup_key_hash uniqueness 검증"""

    def test_same_url_same_symbol_same_key(self) -> None:
        """같은 URL + symbol → 같은 dedup_key"""
        c1 = SeededNewsCandidate(
            symbol="005930",
            related_news_title="title A",
            link="https://example.com/article1",
            originallink="https://example.com/article1",
        )
        c2 = SeededNewsCandidate(
            symbol="005930",
            related_news_title="title B",  # 다른 제목
            link="https://example.com/article1",
            originallink="https://example.com/article1",
        )
        e1 = seeded_candidate_to_event(c1)
        e2 = seeded_candidate_to_event(c2)
        assert e1.dedup_key_hash == e2.dedup_key_hash

    def test_different_url_different_key(self) -> None:
        """다른 URL → 다른 dedup_key"""
        c1 = SeededNewsCandidate(
            symbol="005930",
            related_news_title="title A",
            link="https://example.com/article1",
        )
        c2 = SeededNewsCandidate(
            symbol="005930",
            related_news_title="title B",
            link="https://example.com/article2",
        )
        e1 = seeded_candidate_to_event(c1)
        e2 = seeded_candidate_to_event(c2)
        assert e1.dedup_key_hash != e2.dedup_key_hash

    def test_different_symbol_different_key(self) -> None:
        """같은 URL + 다른 symbol → 다른 dedup_key"""
        c1 = SeededNewsCandidate(
            symbol="005930",
            related_news_title="title",
            link="https://example.com/article1",
        )
        c2 = SeededNewsCandidate(
            symbol="000660",
            related_news_title="title",
            link="https://example.com/article1",
        )
        e1 = seeded_candidate_to_event(c1)
        e2 = seeded_candidate_to_event(c2)
        assert e1.dedup_key_hash != e2.dedup_key_hash

    def test_key_format(self) -> None:
        """dedup_key_hash가 sha256 hex prefix 32자"""
        c = SeededNewsCandidate(
            symbol="005930",
            related_news_title="title",
            link="https://example.com/article",
        )
        event = seeded_candidate_to_event(c)
        assert len(event.dedup_key_hash) == 32
        # hex 문자열인지 검증
        int(event.dedup_key_hash, 16)


class TestEventSortingPriority:
    """4. authoritative source 우선순위 유지 테스트"""

    def test_t1_before_t3(self) -> None:
        """OpenDART(T1) 이벤트가 seeded news(T3)보다 앞서는지"""
        from agent_trading.domain.entities import ExternalEventEntity
        from datetime import datetime, timezone
        from uuid import uuid4

        # T1 event (OpenDART)
        t1 = ExternalEventEntity(
            event_id=uuid4(),
            event_type="report",
            source_name="opendart",
            published_at=datetime(2026, 5, 17, 10, 0, tzinfo=timezone.utc),
            source_reliability_tier="T1",
            symbol="005930",
            headline="OpenDART report",
            metadata={"importance": "medium"},
        )
        # T3 event (seeded news)
        t3 = ExternalEventEntity(
            event_id=uuid4(),
            event_type="seeded_news",
            source_name="naver_news_seeded",
            published_at=datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
            source_reliability_tier="T3",
            symbol="005930",
            headline="Seeded news",
            metadata={"importance": "medium"},
        )

        # DecisionOrchestrator의 _event_sort_key 사용 가정
        from agent_trading.services.decision_orchestrator import _event_sort_key

        events = [t3, t1]
        events.sort(key=_event_sort_key, reverse=True)
        assert events[0].source_name == "opendart"
        assert events[1].source_name == "naver_news_seeded"
