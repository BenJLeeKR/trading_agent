"""SeededNewsCandidate → ExternalEventEntity 변환 레이어.

Transient (non-DB) conversion for EI agent event context injection.
Future: persist to ExternalEventRepository for long-term storage.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID, uuid4

from agent_trading.domain.entities import ExternalEventEntity
from agent_trading.domain.models import SeededNewsCandidate


_SOURCE_NAME = "naver_news_seeded"
_SOURCE_TIER = "T3"  # Media (T1=regulatory > T2=institutional > T3=media > T4=low)
_EVENT_TYPE = "seeded_news"
_SEED_SOURCE = "kis_disclosure_live"
_SEVERITY = "medium"
_DIRECTION = "neutral"


def _confidence_to_importance(score: float) -> str:
    """Map confidence score to importance level for event sorting."""
    if score >= 80:
        return "high"
    elif score >= 50:
        return "medium"
    return "low"


def _build_dedup_key(candidate: SeededNewsCandidate) -> str:
    """Build a deterministic dedup key from the article URL."""
    url = candidate.originallink or candidate.link or ""
    raw = f"{_SOURCE_NAME}|{candidate.symbol}|{url}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def seeded_candidate_to_event(
    candidate: SeededNewsCandidate,
    *,
    event_id: UUID | None = None,
) -> ExternalEventEntity:
    """Convert a single SeededNewsCandidate to an ExternalEventEntity.

    This is a **transient** conversion — the returned entity is NOT
    persisted to any repository. It is intended for direct injection
    into ``AssembledContext.recent_events`` so that the EI agent can
    see seeded news candidates alongside authoritative events.
    """
    importance = _confidence_to_importance(candidate.confidence_score)
    now = datetime.now(timezone.utc)

    metadata: dict[str, object] = {
        "importance": importance,
        "confidence_score": candidate.confidence_score,
        "seed_source": candidate.seed_source or _SEED_SOURCE,
        "seed_headline": candidate.seed_headline or "",
        "company_name": candidate.company_name or "",
        "article_link": candidate.link or "",
        "original_link": candidate.originallink or "",
        "query_used": candidate.query_used or "",
        # Provenance fields for pipeline tracking
        "sort_mode": candidate.sort_mode,
        "pipeline_version": "1.0",
        "candidate_type": _EVENT_TYPE,
    }

    return ExternalEventEntity(
        event_id=event_id or uuid4(),
        event_type=_EVENT_TYPE,
        source_name=_SOURCE_NAME,
        published_at=candidate.published_at or now,
        source_reliability_tier=_SOURCE_TIER,
        source_event_id=None,
        issuer_code=candidate.symbol,
        symbol=candidate.symbol,
        market=None,
        ingested_at=now,
        effective_at=candidate.published_at or now,
        severity=_SEVERITY,
        direction=_DIRECTION,
        headline=candidate.related_news_title,
        body_summary=candidate.related_news_summary,
        raw_payload_uri=None,
        dedup_key_hash=_build_dedup_key(candidate),
        supersedes_event_id=None,
        metadata=metadata,
    )


def convert_seeded_candidates(
    candidates: list[SeededNewsCandidate],
) -> list[ExternalEventEntity]:
    """Convert a list of SeededNewsCandidate to ExternalEventEntity list."""
    return [seeded_candidate_to_event(c) for c in candidates]
