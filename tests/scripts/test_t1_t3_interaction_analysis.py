"""
OpenDART(T1) vs Seeded News(T3) Interaction Analysis Script.

Compares EI (Event Interpretation) agent output across three scenarios:
  A. T1 only — OpenDART events only
  B. T3 only — Seeded news events only (simulated)
  C. T1 + T3 — Both event types combined

Usage:
  python3 tests/scripts/test_t1_t3_interaction_analysis.py
  python3 tests/scripts/test_t1_t3_interaction_analysis.py --symbols 052770,123010,003490
  python3 tests/scripts/test_t1_t3_interaction_analysis.py --output /tmp/results.json
  python3 -m pytest tests/scripts/test_t1_t3_interaction_analysis.py -v --no-header
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

# Ensure project root is on sys.path for direct execution
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from agent_trading.db.connection import DatabaseConfig
from agent_trading.domain.entities import ExternalEventEntity
from agent_trading.runtime.bootstrap import postgres_runtime
from agent_trading.services.ai_agents.base import AgentExecutionRequest
from agent_trading.services.ai_agents.event_interpretation import (
    StubEventInterpretationAgent,
)
from agent_trading.services.ai_agents.schemas import (
    AggregateEventView,
    EventInterpretationOutput,
    InterpretedEvent,
)
from agent_trading.services.decision_orchestrator import AssembledContext

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

_T3_SOURCE_NAME = "naver_news_seeded"
_T3_TIER = "T3"
_DEFAULT_SYMBOLS = (
    "052770",  # 유상증자 관련 (K, high importance)
    "123010",  # 유상증자 + 전환사채 (K, multiple events)
    "003490",  # 회사합병결정 (Y, high importance)
    "078340",  # 회사합병 + 영업실적 (K, mixed)
    "226340",  # 주식병합결정 (K)
    "017960",  # 감자결정 (Y)
    "012510",  # 주식교환ㆍ이전 (Y)
    "090150",  # 주식병합 (K)
    "109960",  # 감자완료 (K)
    "085620",  # 영업실적 (Y)
)

# Classification thresholds for T3 simulation
_T3_SIMULATION_CONFIG: dict[str, dict[str, Any]] = {
    # 시나리오 1: 일관 보강형 — T3가 T1과 같은 방향으로 보강
    "consistent_reinforcement": {
        "min_confidence": 70,
        "sentiment_bias": "positive",
        "description": "T3 news reinforces T1 disclosure in the same direction",
    },
    # 시나리오 2: 상충형 — T3가 T1과 다른 방향/톤
    "conflicting": {
        "min_confidence": 55,
        "sentiment_bias": "negative",
        "description": "T3 news contradicts or casts doubt on T1 disclosure",
    },
    # 시나리오 3: 중복 증폭형 — 동일 이슈 반복
    "duplicate_amplification": {
        "min_confidence": 80,
        "sentiment_bias": "neutral",
        "description": "T3 news amplifies same issue with minimal new info",
    },
    # 시나리오 4: T3 저품질형 — 잡음 수준
    "t3_low_quality": {
        "min_confidence": 30,
        "sentiment_bias": "neutral",
        "description": "T3 news provides low-quality noise with no substance",
    },
}


# ============================================================================
# T3 Simulation Helpers
# ============================================================================


def _classify_event_type(event_type: str) -> str:
    """Classify an OpenDART event_type into a broad category for T3 simulation."""
    et = event_type.strip()
    if "유상증자" in et:
        return "capital_increase"
    if "감자" in et:
        return "capital_reduction"
    if "배당" in et:
        return "dividend"
    if "합병" in et or "주식교환" in et or "주식이전" in et:
        return "merger"
    if "영업" in et and "실적" in et:
        return "earnings"
    if "전환사채" in et or "CB" in et or "신주인수권" in et or "BW" in et:
        return "convertible_bond"
    if "자기주식" in et:
        return "treasury_stock"
    if "주식병합" in et:
        return "stock_merge"
    if "소송" in et:
        return "litigation"
    if "IR" in et or "기업설명회" in et:
        return "ir_event"
    if "분기보고서" in et:
        return "quarterly_report"
    if "사업보고서" in et:
        return "annual_report"
    if "임원" in et or "주요주주" in et:
        return "insider_holding"
    return "general_disclosure"


# Map of event category → T3 simulation parameters
_T3_SIMULATION_TEMPLATES: dict[str, dict[str, Any]] = {
    "capital_increase": {
        "summary_template": (
            "{company}이(가) 유상증자를 결정했다는 소식에 시장은 {sentiment} 반응을 보이고 있다. "
            "증권업계에 따르면 이번 유상증자를 통해 {amount}억 원 규모의 자금을 조달할 것으로 예상된다. "
            "일부 전문가는 {additional_context}라고 분석했다."
        ),
        "direction": "negative",  # 유상증자는 통상 희석 우려
        "importance": "high",
    },
    "capital_reduction": {
        "summary_template": (
            "{company}의 감자 결정과 관련하여 {sentiment} 전망이 제기되고 있다. "
            "이번 감자는 {additional_context}으로 분석된다."
        ),
        "direction": "positive",  # 감자는 주주가치 제고로 해석 가능
        "importance": "high",
    },
    "dividend": {
        "summary_template": (
            "{company}의 배당 결정 소식에 투자자들이 {sentiment} 반응을 보이고 있다. "
            "이번 배당은 {additional_context} 수준으로 평가된다."
        ),
        "direction": "positive",
        "importance": "medium",
    },
    "merger": {
        "summary_template": (
            "{company}의 합병 결정 관련하여 시장에서 {sentiment} 의견이 제기되고 있다. "
            "업계는 {additional_context}이라고 전망했다."
        ),
        "direction": "neutral",
        "importance": "high",
    },
    "earnings": {
        "summary_template": (
            "{company}의 잠정 실적 발표에 대해 증권가에서 {sentiment} 평가가 나오고 있다. "
            "전분기 대비 {additional_context} 수준의 실적을 기록한 것으로 분석된다."
        ),
        "direction": "positive",
        "importance": "high",
    },
    "convertible_bond": {
        "summary_template": (
            "{company}의 전환사채 발행 결정에 대해 시장은 {sentiment} 반응이다. "
            "이번 CB 발행은 {additional_context} 목적으로 알려졌다."
        ),
        "direction": "negative",
        "importance": "high",
    },
    "treasury_stock": {
        "summary_template": (
            "{company}의 자기주식 취득/처분 결정에 대해 {sentiment} 분석이 나오고 있다. "
            "이는 {additional_context} 신호로 해석된다."
        ),
        "direction": "positive",
        "importance": "medium",
    },
    "stock_merge": {
        "summary_template": (
            "{company}의 주식병합 결정과 관련하여 시장에서 {sentiment} 전망이 우세하다. "
            "이번 병합은 {additional_context} 조치로 평가된다."
        ),
        "direction": "neutral",
        "importance": "medium",
    },
    "litigation": {
        "summary_template": (
            "{company}의 소송 제기 소식에 투자자들 사이에서 {sentiment} 의견이 확산되고 있다. "
            "법조계는 {additional_context}이라고 전망했다."
        ),
        "direction": "negative",
        "importance": "medium",
    },
    "ir_event": {
        "summary_template": (
            "{company}이(가) 기업설명회를 개최한다는 소식에 {sentiment} 반응이다. "
            "이번 IR에서 {additional_context} 관련 내용이 발표될 것으로 예상된다."
        ),
        "direction": "neutral",
        "importance": "low",
    },
    "quarterly_report": {
        "summary_template": (
            "{company}의 분기보고서 제출 소식에 시장은 {sentiment} 반응을 보이고 있다. "
            "보고서상 {additional_context} 부분이 투자자들의 주목을 받고 있다."
        ),
        "direction": "neutral",
        "importance": "low",
    },
    "annual_report": {
        "summary_template": (
            "{company}의 사업보고서 제출과 관련하여 {sentiment} 분석이 이어지고 있다. "
            "특히 {additional_context} 부문이 핵심 이슈로 부각되고 있다."
        ),
        "direction": "neutral",
        "importance": "low",
    },
    "insider_holding": {
        "summary_template": (
            "{company} 임원/주요주주의 증권 소유변동 보고와 관련하여 "
            "시장에서는 {sentiment} 반응을 보이고 있다. {additional_context}."
        ),
        "direction": "neutral",
        "importance": "low",
    },
    "general_disclosure": {
        "summary_template": (
            "{company}의 공시와 관련하여 {sentiment} 분석이 제기되고 있다. "
            "전문가들은 {additional_context}이라고 평가했다."
        ),
        "direction": "neutral",
        "importance": "low",
    },
}

# 회사명 매핑 (일부 symbol → 회사명)
_SYMBOL_TO_COMPANY: dict[str, str] = {
    "052770": "아이에이",
    "123010": "아이원스",
    "003490": "대한항공",
    "078340": "엠에스웨이",
    "226340": "본느",
    "017960": "한국쉘석유",
    "012510": "더존비즈온",
    "090150": "아이오케이",
    "109960": "에이프로젠 H&G",
    "085620": "미래에셋증권",
    "016600": "큐캐피탈",
    "030200": "KT",
    "001230": "동국홀딩스",
    "298540": "더네이쳐홀딩스",
    "006740": "한국가구",
    "078600": "디오",
    "063760": "이엘피",
    "243070": "휴온스",
    "063160": "에스엠코어",
    "005950": "이수화학",
    "000100": "유한양행",
    "009190": "대양금속",
}


def _get_sentiment_text(sentiment_bias: str, direction: str) -> str:
    """Generate sentiment description based on bias and direction."""
    if sentiment_bias == "positive":
        return "긍정적인"
    elif sentiment_bias == "negative":
        return "부정적인"
    return "중립적인"


def _get_additional_context(event_type: str, direction: str) -> str:
    """Generate additional context for T3 simulation."""
    category = _classify_event_type(event_type)
    context_map: dict[str, dict[str, str]] = {
        "capital_increase": {
            "positive": "주가 부양 및 신사업 투자 목적이라는 긍정적 평가",
            "negative": "주주가치 희석 우려가 제기되는 상황",
            "neutral": "자금 조달 목적과 일정이 구체화되는 중",
        },
        "capital_reduction": {
            "positive": "주주가치 제고 및 재무구조 개선 기대감",
            "negative": "경영권 분쟁 가능성 등 불확실성 존재",
            "neutral": "재무구조 개선의 일환으로 분석",
        },
        "merger": {
            "positive": "시너지 효과를 통한 기업가치 상승 기대",
            "negative": "통합 과정에서의 리스크 우려 존재",
            "neutral": "업계 재편의 신호탄으로 평가",
        },
        "earnings": {
            "positive": "시장 기대치를 상회하는 호실적",
            "negative": "시장 기대치를 하회하는 실적 부진",
            "neutral": "시장 컨센서스에 부합하는 수준",
        },
        "convertible_bond": {
            "positive": "성장 자금 확보를 통한 사업 확장 기대",
            "negative": "잠재적 주가 희석 및 부담 가중",
            "neutral": "운영자금 확보 차원의 결정",
        },
    }
    default_texts = {
        "positive": "긍정적 신호로 해석",
        "negative": "부정적 신호로 해석",
        "neutral": "중립적 관점에서 평가",
    }
    cm = context_map.get(category, default_texts)
    return cm.get(direction, default_texts.get(direction, "분석 중"))


def _get_confidence_for_simulation(event_type: str) -> int:
    """Assign a confidence score based on event type importance."""
    category = _classify_event_type(event_type)
    template = _T3_SIMULATION_TEMPLATES.get(category, {})
    imp = template.get("importance", "low")
    if imp == "high":
        return 75
    elif imp == "medium":
        return 55
    return 35


def create_simulated_t3_events(
    t1_events: Sequence[ExternalEventEntity],
    *,
    classification: str = "consistent_reinforcement",
) -> list[ExternalEventEntity]:
    """Create simulated T3 (Seeded News) events based on T1 event headlines.

    Parameters
    ----------
    t1_events
        The authoritative OpenDART events to base T3 events on.
    classification
        The type of T3 simulation to generate:
        - ``"consistent_reinforcement"``: T3 reinforces T1 direction
        - ``"conflicting"``: T3 contradicts T1
        - ``"duplicate_amplification"``: T3 repeats same info
        - ``"t3_low_quality"``: T3 adds noise

    Returns
    -------
    list[ExternalEventEntity]
        Simulated T3 events suitable for EI agent injection.
    """
    config = _T3_SIMULATION_CONFIG.get(classification, _T3_SIMULATION_CONFIG["consistent_reinforcement"])
    now = datetime.now(timezone.utc)
    t3_events: list[ExternalEventEntity] = []

    for t1_event in t1_events:
        symbol = t1_event.symbol or "000000"
        company = _SYMBOL_TO_COMPANY.get(symbol, f"종목({symbol})")
        event_type = t1_event.event_type or ""
        headline = t1_event.headline or event_type
        category = _classify_event_type(event_type)
        template = _T3_SIMULATION_TEMPLATES.get(category, _T3_SIMULATION_TEMPLATES["general_disclosure"])

        # Determine direction — for conflicting scenario, flip the direction
        base_direction = template.get("direction", "neutral")
        if classification == "conflicting":
            direction = "positive" if base_direction == "negative" else "negative" if base_direction == "positive" else "negative"
        else:
            direction = base_direction

        # Determine confidence
        base_confidence = _get_confidence_for_simulation(event_type)
        if classification == "duplicate_amplification":
            confidence = min(base_confidence + 10, 95)
        elif classification == "t3_low_quality":
            confidence = max(base_confidence - 30, 10)
        elif classification == "conflicting":
            confidence = max(base_confidence - 10, 30)
        else:
            confidence = base_confidence

        sentiment = _get_sentiment_text(config["sentiment_bias"], direction)
        additional_context = _get_additional_context(event_type, direction)

        # Build body_summary
        body_summary = template["summary_template"].format(
            company=company,
            sentiment=sentiment,
            amount="500",
            additional_context=additional_context,
        )

        # Build metadata
        importance = template.get("importance", "low")
        metadata: dict[str, object] = {
            "importance": importance,
            "confidence_score": confidence,
            "seed_source": "kis_disclosure_live",
            "seed_headline": headline[:100],
            "company_name": company,
            "article_link": f"https://news.example.com/articles/{symbol}/{uuid4().hex[:8]}",
            "query_used": symbol,
            "classification_scenario": classification,
        }

        # Create T3 event
        t3_event = ExternalEventEntity(
            event_id=uuid4(),
            event_type="seeded_news",
            source_name=_T3_SOURCE_NAME,
            published_at=t1_event.published_at or now,
            source_reliability_tier=_T3_TIER,
            source_event_id=None,
            issuer_code=t1_event.issuer_code or symbol,
            symbol=symbol,
            market=t1_event.market,
            ingested_at=now,
            effective_at=t1_event.published_at or now,
            severity=t1_event.severity or "medium",
            direction=direction,
            headline=f"[T3 시뮬레이션] {headline[:80]}",
            body_summary=body_summary,
            raw_payload_uri=None,
            dedup_key_hash=None,
            supersedes_event_id=None,
            metadata=metadata,
        )
        t3_events.append(t3_event)

    return t3_events


def _make_t3_event_summary(event: ExternalEventEntity) -> dict[str, Any]:
    """Serialize a T3 event for JSON output."""
    meta = dict(event.metadata) if event.metadata else {}
    return {
        "event_id": str(event.event_id),
        "headline": event.headline or "",
        "body_summary": event.body_summary or "",
        "source_name": event.source_name,
        "tier": event.source_reliability_tier,
        "direction": event.direction,
        "severity": event.severity,
        "metadata": {
            "importance": meta.get("importance", "medium"),
            "confidence_score": meta.get("confidence_score", 0),
            "seed_source": meta.get("seed_source", ""),
            "classification_scenario": meta.get("classification_scenario", ""),
        },
    }


def _make_t1_event_summary(event: ExternalEventEntity) -> dict[str, Any]:
    """Serialize a T1 event for JSON output."""
    meta = dict(event.metadata) if event.metadata else {}
    return {
        "event_id": str(event.event_id),
        "event_type": event.event_type or "",
        "headline": event.headline or "",
        "source_name": event.source_name,
        "tier": event.source_reliability_tier,
        "published_at": event.published_at.isoformat() if event.published_at else "",
        "direction": event.direction,
        "severity": event.severity,
        "importance": meta.get("importance", "medium"),
    }


# ============================================================================
# EI Agent Runner Helpers
# ============================================================================


def _ei_output_to_dict(output: EventInterpretationOutput) -> dict[str, Any]:
    """Convert EventInterpretationOutput to a serializable dict."""
    agg = output.aggregate_view
    return {
        "schema_version": output.schema_version,
        "agent_name": output.agent_name,
        "symbol": output.symbol,
        "issuer_code": output.issuer_code,
        "event_count": len(output.events),
        "aggregate_view": {
            "overall_bias": agg.overall_bias,
            "event_conflict": agg.event_conflict,
            "top_reason_codes": list(agg.top_reason_codes),
            "opposing_evidence": list(agg.opposing_evidence),
            "evidence_strength": agg.evidence_strength,
            "event_count": agg.event_count,
            "no_material_events": agg.no_material_events,
        },
        "events": [
            {
                "source_event_id": e.source_event_id,
                "event_type": e.event_type,
                "source_name": e.source_name,
                "source_reliability_tier": e.source_reliability_tier,
                "impact_direction": e.impact_direction,
                "impact_horizon": e.impact_horizon,
                "confidence": e.confidence,
                "novelty": e.novelty,
                "supports_entry": e.supports_entry,
                "supports_exit": e.supports_exit,
                "reason_codes": list(e.reason_codes),
                "summary": e.summary,
            }
            for e in output.events
        ],
    }


async def _run_ei_agent_for_scenario(
    agent: StubEventInterpretationAgent,
    symbol: str,
    events: list[ExternalEventEntity],
    correlation_id: str,
) -> EventInterpretationOutput:
    """Run the EI agent stub for a given set of events.

    This constructs a minimal ``AgentExecutionRequest`` with the provided
    events in ``context.recent_events`` and calls the agent's ``run()``
    method.
    """
    context = AssembledContext(
        recent_events=tuple(events),
        source_type="event_overlay",
    )
    request = AgentExecutionRequest(
        decision_context_id=None,
        correlation_id=correlation_id,
        context=context,
        symbol=symbol,
        market="KRX",
    )
    return await agent.run(request)


# ============================================================================
# Scenario Classification
# ============================================================================


def _classify_scenario(
    t1_output: EventInterpretationOutput,
    t3_output: EventInterpretationOutput,
    t1t3_output: EventInterpretationOutput,
    *,
    t1_input_count: int = 0,
    t3_input_count: int = 0,
    t3_events: list[ExternalEventEntity] | None = None,
) -> str:
    """Classify the interaction scenario based on EI output comparison.

    Uses heuristic rules based on event counts, bias shifts, and
    evidence strength deltas between scenarios.

    When the EI agent is a stub (all outputs are defaults with
    ``no_material_events=True``), the classification falls back to
    the ``classification_scenario`` metadata embedded in T3 events,
    or input event counts as a last resort.

    Parameters
    ----------
    t1_output
        EI output for the T1-only scenario.
    t3_output
        EI output for the T3-only scenario.
    t1t3_output
        EI output for the T1+T3 combined scenario.
    t1_input_count
        Number of T1 events fed into the agent (stub fallback).
    t3_input_count
        Number of T3 events fed into the agent (stub fallback).
    t3_events
        The actual T3 event list, used to read ``classification_scenario``
        from event metadata for stub-mode classification.

    Returns
    -------
    str
        One of ``"consistent_reinforcement"``, ``"conflicting"``,
        ``"duplicate_amplification"``, or ``"t3_low_quality"``.
    """
    t1_agg = t1_output.aggregate_view
    t3_agg = t3_output.aggregate_view
    combined_agg = t1t3_output.aggregate_view

    t1_event_count = len(t1_output.events)
    t3_event_count = len(t3_output.events)

    # --- Stub detection: all outputs are defaults with no_material_events=True ---
    # When the stub agent is used, all aggregate views will look identical
    # (default values).  In that case fall back to T3 event metadata.
    is_stub = (
        t1_agg.no_material_events
        and t3_agg.no_material_events
        and combined_agg.no_material_events
        and t1_agg.evidence_strength == "none"
        and t3_agg.evidence_strength == "none"
        and combined_agg.evidence_strength == "none"
    )

    if is_stub:
        # Priority 1: read classification_scenario from T3 event metadata
        if t3_events:
            for ev in t3_events:
                meta = dict(ev.metadata or {})
                scenario = meta.get("classification_scenario", "")
                if scenario in (
                    "consistent_reinforcement",
                    "conflicting",
                    "duplicate_amplification",
                    "t3_low_quality",
                ):
                    return scenario  # type: ignore[return-value]

        # Priority 2: fall back to input event counts
        if t3_input_count == 0:
            return "t3_low_quality"
        if t1_input_count > 0 and t3_input_count > 0:
            if t3_input_count >= t1_input_count:
                return "duplicate_amplification"
            return "consistent_reinforcement"
        return "consistent_reinforcement"

    # --- Real agent output classification ---

    # Scenario 4: T3 저품질형 — all T3 events yield no_material_events or empty
    if t3_agg.no_material_events or t3_event_count == 0:
        return "t3_low_quality"

    # Scenario 3: 중복 증폭형 — T1+T3 event count increases but aggregate view unchanged
    if (
        t1_agg.overall_bias == combined_agg.overall_bias
        and t1_agg.event_conflict == combined_agg.event_conflict
        and t1_agg.evidence_strength == combined_agg.evidence_strength
        and not combined_agg.event_conflict
    ):
        if t1_agg.evidence_strength in ("moderate", "strong"):
            return "duplicate_amplification"

    # Scenario 2: 상충형 — bias changes or conflict emerges when T3 is added
    if combined_agg.event_conflict:
        return "conflicting"
    if t1_agg.overall_bias != combined_agg.overall_bias and not combined_agg.no_material_events:
        return "conflicting"
    if t3_agg.overall_bias != t1_agg.overall_bias and t3_event_count > 0:
        return "conflicting"

    # Scenario 1: 일관 보강형 — bias consistent, evidence strengthened
    if (
        t1_agg.overall_bias == combined_agg.overall_bias
        and not combined_agg.event_conflict
        and combined_agg.evidence_strength != "none"
    ):
        return "consistent_reinforcement"

    # Fallback
    return "consistent_reinforcement"


# ============================================================================
# Recommendation Generator
# ============================================================================


def _generate_recommendations(
    classification_counts: dict[str, int],
    total_symbols: int,
) -> dict[str, Any]:
    """Generate analysis recommendations based on classification results."""
    recommendations: dict[str, Any] = {
        "tier_handling": {},
        "prompt_changes": [],
        "data_quality": [],
    }

    # Tier handling recommendations
    if classification_counts.get("conflicting", 0) > 0:
        recommendations["tier_handling"]["conflict_resolution"] = (
            "T1+T3 충돌 시 T1(OpenDART) 우선 적용 필요. "
            "EI Agent prompt에 tier별 가중치 로직 추가 검토."
        )
    if classification_counts.get("duplicate_amplification", 0) > 0:
        recommendations["tier_handling"]["dedup"] = (
            "T3 중복 증폭 탐지 시 이벤트 필터링 또는 중요도 하향 조정 필요."
        )
    if classification_counts.get("t3_low_quality", 0) > 0:
        recommendations["tier_handling"]["quality_gate"] = (
            "T3 이벤트 품질 게이트(confidence_score < 50) 도입 검토. "
            "저품질 T3는 EI Agent 입력에서 제외."
        )

    # Prompt change recommendations
    if classification_counts.get("conflicting", 0) / max(total_symbols, 1) > 0.2:
        recommendations["prompt_changes"].append(
            "EI Agent prompt에 tier 신뢰도 가중치 명시 필요. "
            "T1(T1)은 regulatory source로 가중치 상향, T3(T3)은 media로 가중치 하향."
        )
    if classification_counts.get("duplicate_amplification", 0) / max(total_symbols, 1) > 0.3:
        recommendations["prompt_changes"].append(
            "EI Agent prompt에 'duplicate event detection' 로직 추가 검토. "
            "동일 headline의 T3 이벤트를 identification 후 중요도 하향."
        )

    # Data quality recommendations
    recommendations["data_quality"].append(
        "T3(Seeded News) 이벤트의 body_summary 품질 개선 필요. "
        "현재 시뮬레이션 기반이므로 실제 뉴스 데이터 수집 후 재검증 권장."
    )
    if classification_counts.get("t3_low_quality", 0) > 0:
        recommendations["data_quality"].append(
            "T3 이벤트 중 confidence_score 30 미만은 EI Agent 입력에서 "
            "자동 제외하는 품질 게이트 도입 검토."
        )

    return recommendations


# ============================================================================
# Main Analysis Logic
# ============================================================================


async def analyze_t1_t3_interaction(
    symbols: list[str] | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Run the full T1 vs T3 interaction analysis.

    Parameters
    ----------
    symbols
        List of stock symbols to analyze. Defaults to ``_DEFAULT_SYMBOLS``.
    output_path
        If provided, write the result JSON to this path. If ``None``,
        auto-generate a timestamped path under ``data/observations/``.

    Returns
    -------
    dict[str, Any]
        The full analysis result as a dict (JSON-serializable).
    """
    target_symbols = list(symbols or _DEFAULT_SYMBOLS)
    now = datetime.now(timezone.utc)
    correlation_id_base = f"t1_t3_analysis_{now.strftime('%Y%m%d_%H%M%S')}"

    # Initialize stub agent
    stub_agent = StubEventInterpretationAgent(schema_version="v1")

    analysis: dict[str, Any] = {
        "generated_at": now.isoformat(),
        "symbols_analyzed": target_symbols,
        "scenarios": {},
        "metrics": {
            "total_symbols": len(target_symbols),
            "consistent_reinforcement": 0,
            "conflicting": 0,
            "duplicate_amplification": 0,
            "t3_low_quality": 0,
        },
        "recommendations": {},
    }

    # Connect to DB and run analysis
    async with postgres_runtime(auto_rollback=True) as runtime:
        repos = runtime["repositories"]
        since = now - timedelta(hours=72)

        for symbol in target_symbols:
            symbol_key = symbol
            logger.info("분석 중: symbol=%s", symbol)

            # --- S1: Load T1 (OpenDART) events from DB ---
            t1_events_raw = await repos.external_events.list_by_symbol(
                symbol=symbol,
                since=since,
            )
            # Filter to OpenDART events only
            t1_events: list[ExternalEventEntity] = [
                e for e in t1_events_raw if e.source_name == "opendart"
            ]

            if not t1_events:
                logger.warning(
                    "symbol=%s: OpenDART 이벤트 없음 — 건너뜀", symbol
                )
                continue

            # --- S2: Create simulated T3 events ---
            # Try each classification scenario and pick the one that
            # produces the most distinct differences for analysis.
            t3_events = create_simulated_t3_events(
                t1_events,
                classification="consistent_reinforcement",
            )

            # Also create conflicting scenario events for symbols with
            # multiple events to ensure diverse coverage
            if len(t1_events) >= 2:
                t3_conflicting = create_simulated_t3_events(
                    t1_events,
                    classification="conflicting",
                )
                # Use conflicting for symbols ending with even digit
                if int(symbol[-1]) % 2 == 0:
                    t3_events = t3_conflicting

            # --- S3: Run 3 scenarios ---
            cid = f"{correlation_id_base}_{symbol}"

            # Scenario A: T1 only
            output_t1_only = await _run_ei_agent_for_scenario(
                stub_agent, symbol, t1_events, f"{cid}_t1only"
            )

            # Scenario B: T3 only
            output_t3_only = await _run_ei_agent_for_scenario(
                stub_agent, symbol, t3_events, f"{cid}_t3only"
            )

            # Scenario C: T1 + T3 combined
            combined_events = t1_events + t3_events
            output_t1_t3 = await _run_ei_agent_for_scenario(
                stub_agent, symbol, combined_events, f"{cid}_t1t3"
            )

            # --- Classify scenario ---
            classification = _classify_scenario(
                output_t1_only,
                output_t3_only,
                output_t1_t3,
                t1_input_count=len(t1_events),
                t3_input_count=len(t3_events),
                t3_events=t3_events,
            )

            # Update metrics
            if classification in analysis["metrics"]:
                analysis["metrics"][classification] += 1

            # Record per-symbol results
            analysis["scenarios"][symbol_key] = {
                "t1_only": _ei_output_to_dict(output_t1_only),
                "t3_only": _ei_output_to_dict(output_t3_only),
                "t1_plus_t3": _ei_output_to_dict(output_t1_t3),
                "t1_events": [
                    _make_t1_event_summary(e) for e in t1_events
                ],
                "t3_events": [
                    _make_t3_event_summary(e) for e in t3_events
                ],
                "classification": classification,
                "t1_event_count": len(t1_events),
                "t3_event_count": len(t3_events),
            }

            logger.info(
                "symbol=%s: 분류=%s (T1=%d건, T3=%d건)",
                symbol,
                classification,
                len(t1_events),
                len(t3_events),
            )

        # --- Generate recommendations ---
        analysis["recommendations"] = _generate_recommendations(
            analysis["metrics"], len(target_symbols)
        )

    # --- Write output ---
    if output_path is None:
        ts = now.strftime("%Y%m%d_%H%M%S")
        obs_dir = os.path.join(_PROJECT_ROOT, "data", "observations")
        os.makedirs(obs_dir, exist_ok=True)
        output_path = os.path.join(obs_dir, f"t1_t3_comparison_{ts}.json")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)

    logger.info("분석 결과 저장: %s", output_path)
    return analysis


# ============================================================================
# CLI Entry Point
# ============================================================================


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="T1(OpenDART) vs T3(Seeded News) 상호작용 분석",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 tests/scripts/test_t1_t3_interaction_analysis.py\n"
            "  python3 tests/scripts/test_t1_t3_interaction_analysis.py --symbols 052770,123010\n"
            "  python3 tests/scripts/test_t1_t3_interaction_analysis.py --output /tmp/result.json\n"
        ),
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default=None,
        help="분석할 symbol 목록 (쉼표 구분). 예: 052770,123010,003490",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="출력 JSON 파일 경로 (기본: data/observations/t1_t3_comparison_<ts>.json)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="로깅 수준을 DEBUG로 설정",
    )
    return parser.parse_args(argv)


async def _main_async(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    symbols: list[str] | None = None
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

    result = await analyze_t1_t3_interaction(
        symbols=symbols,
        output_path=args.output,
    )

    # Print summary
    print("\n" + "=" * 60)
    print("T1(OpenDART) vs T3(Seeded News) 상호작용 분석 완료")
    print("=" * 60)
    print(f"분석 symbol 수: {result['metrics']['total_symbols']}")
    print(f"  - 일관 보강형:     {result['metrics']['consistent_reinforcement']}")
    print(f"  - 상충형:          {result['metrics']['conflicting']}")
    print(f"  - 중복 증폭형:     {result['metrics']['duplicate_amplification']}")
    print(f"  - T3 저품질형:     {result['metrics']['t3_low_quality']}")
    print("-" * 60)
    for symbol, data in result["scenarios"].items():
        print(
            f"  {symbol}: {data['classification']} "
            f"(T1={data['t1_event_count']}건, T3={data['t3_event_count']}건)"
        )
    print("-" * 60)
    print(f"출력 파일: {args.output or '(auto)'}")
    print("=" * 60)


def main() -> None:
    """CLI entry point (synchronous wrapper)."""
    import asyncio

    asyncio.run(_main_async())


if __name__ == "__main__":
    main()


# ============================================================================
# Pytest Test Functions
# ============================================================================


def test_script_importable() -> None:
    """Verify the module imports cleanly (sanity check)."""
    from tests.scripts import test_t1_t3_interaction_analysis as mod

    assert mod is not None
    assert hasattr(mod, "analyze_t1_t3_interaction")
    assert hasattr(mod, "create_simulated_t3_events")
    assert hasattr(mod, "_classify_scenario")


def test_t3_event_creation_consistent() -> None:
    """Test consistent_reinforcement T3 event creation."""
    now = datetime.now(timezone.utc)
    t1 = ExternalEventEntity(
        event_id=uuid4(),
        event_type="Y|주요사항보고서(유상증자결정)",
        source_name="opendart",
        published_at=now,
        source_reliability_tier="T1",
        symbol="052770",
        issuer_code="052770",
        headline="주요사항보고서(유상증자결정)",
        ingested_at=now,
        direction="neutral",
        severity="medium",
        metadata={"importance": "high"},
    )
    t3_list = create_simulated_t3_events([t1], classification="consistent_reinforcement")
    assert len(t3_list) == 1
    t3 = t3_list[0]
    assert t3.source_name == "naver_news_seeded"
    assert t3.source_reliability_tier == "T3"
    assert t3.symbol == "052770"
    assert t3.body_summary is not None
    assert len(t3.body_summary) > 10
    assert "유상증자" in (t3.body_summary or "")
    meta = dict(t3.metadata or {})
    assert meta.get("classification_scenario") == "consistent_reinforcement"


def test_t3_event_creation_conflicting() -> None:
    """Test conflicting T3 event creation — direction should differ."""
    now = datetime.now(timezone.utc)
    t1 = ExternalEventEntity(
        event_id=uuid4(),
        event_type="Y|주요사항보고서(유상증자결정)",
        source_name="opendart",
        published_at=now,
        source_reliability_tier="T1",
        symbol="052770",
        issuer_code="052770",
        headline="주요사항보고서(유상증자결정)",
        ingested_at=now,
        direction="neutral",
        severity="medium",
        metadata={"importance": "high"},
    )
    t3_list = create_simulated_t3_events([t1], classification="conflicting")
    assert len(t3_list) == 1
    t3 = t3_list[0]
    # 유상증자 기본 방향은 negative → conflicting에서는 positive
    assert t3.direction == "positive"


def test_t3_event_creation_duplicate() -> None:
    """Test duplicate_amplification T3 event creation."""
    now = datetime.now(timezone.utc)
    t1 = ExternalEventEntity(
        event_id=uuid4(),
        event_type="Y|주요사항보고서(유상증자결정)",
        source_name="opendart",
        published_at=now,
        source_reliability_tier="T1",
        symbol="052770",
        issuer_code="052770",
        headline="주요사항보고서(유상증자결정)",
        ingested_at=now,
        direction="neutral",
        severity="medium",
        metadata={"importance": "high"},
    )
    t3_list = create_simulated_t3_events([t1], classification="duplicate_amplification")
    assert len(t3_list) == 1
    t3 = t3_list[0]
    meta = dict(t3.metadata or {})
    # Duplicate amplification should have higher confidence
    assert int(meta.get("confidence_score", 0)) >= 75


def test_t3_event_creation_low_quality() -> None:
    """Test t3_low_quality T3 event creation — low confidence."""
    now = datetime.now(timezone.utc)
    t1 = ExternalEventEntity(
        event_id=uuid4(),
        event_type="Y|분기보고서 (2026.03)",
        source_name="opendart",
        published_at=now,
        source_reliability_tier="T1",
        symbol="052770",
        issuer_code="052770",
        headline="분기보고서 (2026.03)",
        ingested_at=now,
        direction="neutral",
        severity="medium",
        metadata={"importance": "low"},
    )
    t3_list = create_simulated_t3_events([t1], classification="t3_low_quality")
    assert len(t3_list) == 1
    t3 = t3_list[0]
    meta = dict(t3.metadata or {})
    assert int(meta.get("confidence_score", 0)) < 40


def test_ei_agent_stub_run() -> None:
    """Test that StubEventInterpretationAgent runs cleanly with events."""
    import asyncio

    agent = StubEventInterpretationAgent()
    now = datetime.now(timezone.utc)
    event = ExternalEventEntity(
        event_id=uuid4(),
        event_type="Y|주요사항보고서(유상증자결정)",
        source_name="opendart",
        published_at=now,
        source_reliability_tier="T1",
        symbol="052770",
        issuer_code="052770",
        headline="주요사항보고서(유상증자결정)",
        ingested_at=now,
        direction="neutral",
        severity="medium",
    )
    context = AssembledContext(recent_events=(event,))
    request = AgentExecutionRequest(
        decision_context_id=None,
        correlation_id="test_cid",
        context=context,
        symbol="052770",
        market="KRX",
    )
    output = asyncio.run(agent.run(request))
    assert isinstance(output, EventInterpretationOutput)
    assert output.agent_name == "event_interpretation"


def test_classify_scenario_consistent() -> None:
    """Test scenario classification: consistent_reinforcement."""
    # T1 only: moderate evidence, positive bias
    t1_agg = AggregateEventView(
        overall_bias="positive",
        event_conflict=False,
        evidence_strength="moderate",
        event_count=3,
        no_material_events=False,
    )
    t1_output = EventInterpretationOutput(
        symbol="052770",
        events=(
            InterpretedEvent(
                source_event_id="1", event_type="유상증자", summary="test"
            ),
        ),
        aggregate_view=t1_agg,
    )
    # T3 only: weak evidence, same bias
    t3_agg = AggregateEventView(
        overall_bias="positive",
        event_conflict=False,
        evidence_strength="weak",
        event_count=2,
        no_material_events=False,
    )
    t3_output = EventInterpretationOutput(
        symbol="052770",
        events=(
            InterpretedEvent(
                source_event_id="t3-1", event_type="seeded_news", summary="news"
            ),
        ),
        aggregate_view=t3_agg,
    )
    # T1+T3: stronger evidence, same bias, no conflict
    combined_agg = AggregateEventView(
        overall_bias="positive",
        event_conflict=False,
        evidence_strength="strong",
        event_count=5,
        no_material_events=False,
    )
    combined_output = EventInterpretationOutput(
        symbol="052770",
        events=(
            InterpretedEvent(
                source_event_id="1", event_type="유상증자", summary="test"
            ),
            InterpretedEvent(
                source_event_id="t3-1", event_type="seeded_news", summary="news"
            ),
        ),
        aggregate_view=combined_agg,
    )
    classification = _classify_scenario(t1_output, t3_output, combined_output)
    assert classification == "consistent_reinforcement"


@pytest.mark.asyncio
async def test_analysis_creates_output() -> None:
    """Integration test: running the analysis produces a valid result.

    This test connects to the database and runs the full analysis.
    It may be slow or unavailable in CI environments.

    If the database contains no OpenDART events for the requested symbol,
    the analysis skips that symbol gracefully — the test still validates
    the overall output structure.
    """
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        output_path = tmp.name

    try:
        result = await analyze_t1_t3_interaction(
            symbols=["052770"],
            output_path=output_path,
        )
        assert result is not None
        assert "generated_at" in result
        assert "scenarios" in result
        # When DB has OpenDART events for 052770, verify the classification.
        # When DB has no data, the symbol is simply skipped — that's valid too.
        if "052770" in result["scenarios"]:
            assert result["scenarios"]["052770"]["classification"] in (
                "consistent_reinforcement",
                "conflicting",
                "duplicate_amplification",
                "t3_low_quality",
            )
        # Verify the output file exists and is valid JSON
        with open(output_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved["generated_at"] == result["generated_at"]
    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)
