#!/usr/bin/env python3
"""EI→AR→FDC provenance 전파 이후 output 변화 측정.

Read-only measurement script (default).
- No DB writes.
- No external provider/API calls (unless --with-provider flag).
- Compares old-style vs new-style AR/FDC prompts for 3 symbols.
- Measures provenance completeness, continuity coverage, context depth.
- Token increase rate is a secondary indicator only.

사용법:
    python -m scripts.ar_fdc_output_measurement
    python -m scripts.ar_fdc_output_measurement --with-provider  # 선택적 provider 호출

Exit code:
    0 — measurement completed
    1 — unexpected error
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

# .env 파일 로드 (provider API key 등)
try:
    from dotenv import load_dotenv
    _dotenv_path = Path(__file__).resolve().parent.parent / ".env"
    if _dotenv_path.exists():
        load_dotenv(_dotenv_path)
except ImportError:
    pass

from agent_trading.runtime.bootstrap import postgres_runtime
from agent_trading.services.ai_agents.ai_risk import AIRiskAgent
from agent_trading.services.ai_agents.base import AgentExecutionRequest
from agent_trading.services.ai_agents.event_interpretation import EventInterpretationAgent
from agent_trading.services.ai_agents.final_decision_composer import FinalDecisionComposerAgent
from agent_trading.services.ai_agents.schemas import (
    AggregateEventView,
    EventInterpretationOutput,
    AIRiskOutput,
    FinalDecisionComposerOutput,
    InterpretedEvent,
)
from agent_trading.services.decision_orchestrator import AssembledContext, ScoreResult

logger = logging.getLogger(__name__)

SEP = "=" * 78
DASH = "-" * 78

# 계측 대상 symbol (event 3건 이상, 다양성 확보)
SYMBOLS = ["030200", "327260", "090150"]

# ── Context depth scoring constants ──
MAX_REASON_CODE_DEPTH = 3
MAX_EVENT_RICHNESS = 5
MAX_AGENT_CONTINUITY = 11

# ── Agent continuity field names ──
EI_TO_AR_FIELDS = [
    "overall_bias",
    "event_conflict",
    "top_reason_codes",
    "interpreted_events",
]
AR_TO_FDC_FIELDS = [
    "risk_opinion",
    "risk_score",
    "confidence",
    "size_adjustment_factor",
    "reason_codes",
    "opposing_evidence",
    "summary",
]


# ========================================================================
#  Old-style prompt formatters (approximate reconstruction)
# ========================================================================


def _build_old_style_ar_prompt(
    request: AgentExecutionRequest,
) -> str:
    """P1-A/P1-B 이전 old-style AR prompt 재현 (approximate reconstruction).

    Old-style 특징:
    - events 섹션: dash-prefix "  - [{event_type}] {headline}" (provenance tag 없음)
    - Symbol line: DecisionContextEntity repr (BUG 상태)
    - EI output 섹션: 동일 (변경 없음)
    - Score/position/cash/risk 섹션: 동일 (변경 없음)

    NOTE: This is an approximate reconstruction based on the code before
    provenance propagation. Historical 100% 일치를 보장하지 않음.
    """
    context = request.context
    score = context.score
    events = context.recent_events or []

    lines: list[str] = [
        f"Correlation ID: {request.correlation_id}",
    ]

    # Old-style Symbol line: DecisionContextEntity repr (BUG)
    dc = context.decision_context
    if dc:
        lines.append(f"Symbol: {dc}")  # BUG: prints repr, not symbol
    else:
        lines.append("Symbol: (not available)")

    # === Event Interpretation output (if available) ===
    ei_output = request.event_interpretation_output
    if ei_output is not None:
        lines.append("")
        lines.append("=== Event Interpretation ===")
        lines.append(f"Overall bias: {ei_output.aggregate_view.overall_bias}")
        lines.append(f"Event conflict: {ei_output.aggregate_view.event_conflict}")
        if ei_output.aggregate_view.top_reason_codes:
            lines.append(
                "Top reason codes: "
                f"{', '.join(ei_output.aggregate_view.top_reason_codes)}"
            )

        interpreted = ei_output.events or ()
        if interpreted:
            lines.append(f"Interpreted events ({len(interpreted)}):")
            for ie in interpreted[:10]:
                if isinstance(ie, dict):
                    summary = ie.get("summary") or ie.get("headline") or "(no summary)"
                    lines.append(f"  - [{ie.get('event_type', '?')}] {summary}")
                    lines.append(
                        f"    impact={ie.get('impact_direction', '?')} "
                        f"confidence={ie.get('confidence', '?')}"
                    )
                else:
                    summary = ie.summary or ie.headline or "(no summary)"
                    lines.append(f"  - [{ie.event_type}] {summary}")
                    lines.append(
                        f"    impact={ie.impact_direction} "
                        f"confidence={ie.confidence}"
                    )
        lines.append("")

    if score:
        lines.append(f"Score: {score.score} (threshold: {score.threshold})")
        if score.reason_codes:
            lines.append(f"Reason codes: {', '.join(score.reason_codes)}")

    if dc:
        lines.append(f"Decision context account_id: {dc.account_id}")

    # === Position snapshot summary (if available) ===
    pos = context.position_snapshot
    if pos is not None:
        lines.append("")
        lines.append("=== Current Position (this symbol) ===")
        lines.append(f"  Quantity: {pos.quantity}")
        lines.append(f"  Average price: {pos.average_price}")
        if pos.market_price is not None:
            lines.append(f"  Market price: {pos.market_price}")
        if pos.unrealized_pnl is not None:
            lines.append(f"  Unrealised P&L: {pos.unrealized_pnl}")

    # === Cash balance snapshot summary (if available) ===
    cash = context.cash_balance_snapshot
    if cash is not None:
        lines.append("")
        lines.append("=== Cash Balance ===")
        lines.append(f"  Available cash: {cash.available_cash}")
        lines.append(f"  Currency: {cash.currency}")
        if cash.settled_cash is not None:
            lines.append(f"  Settled cash: {cash.settled_cash}")
        if cash.unsettled_cash is not None:
            lines.append(f"  Unsettled cash: {cash.unsettled_cash}")

    # === Risk limit snapshot summary (if available) ===
    rl = context.risk_limit_snapshot
    if rl is not None:
        lines.append("")
        lines.append("=== Risk Limit State ===")
        lines.append(f"  Kill switch active: {rl.kill_switch_active}")
        if rl.drawdown_state:
            lines.append(f"  Drawdown state: {rl.drawdown_state}")
        if rl.blocked_reason_codes:
            lines.append(
                "  Blocked reason codes: "
                f"{', '.join(rl.blocked_reason_codes)}"
            )
        if rl.daily_loss_used_pct is not None and rl.max_daily_loss_limit_pct is not None:
            lines.append(
                f"  Daily loss: {rl.daily_loss_used_pct}% / "
                f"{rl.max_daily_loss_limit_pct}% limit"
            )
        if rl.gross_exposure_pct is not None:
            lines.append(f"  Gross exposure: {rl.gross_exposure_pct}%")
        if rl.net_exposure_pct is not None:
            lines.append(f"  Net exposure: {rl.net_exposure_pct}%")

    # Old-style events: dash-prefix, no provenance tags
    lines.append(f"Recent events ({len(events)}):")
    for e in events[:20]:
        headline = e.headline or "(no headline)"
        summary = e.body_summary or ""
        lines.append(
            f"  - [{e.event_type}] {headline}"
            f"{' — ' + summary[:200] if summary else ''}"
        )

    return "\n".join(lines)


def _build_old_style_fdc_prompt(
    request: AgentExecutionRequest,
) -> str:
    """P1-A/P1-B 이전 old-style FDC prompt 재현 (approximate reconstruction).

    Old-style 특징:
    - events 섹션: dash-prefix "  - [{event_type}] {headline}" (provenance tag 없음)
    - EI/AR output 섹션: 동일 (변경 없음)
    - Score 섹션: 동일 (변경 없음)

    NOTE: This is an approximate reconstruction based on the code before
    provenance propagation. Historical 100% 일치를 보장하지 않음.
    """
    context = request.context
    score = context.score
    events = context.recent_events or []

    lines: list[str] = [
        f"Correlation ID: {request.correlation_id}",
    ]

    dc = context.decision_context
    if dc:
        lines.append(f"Account ID: {dc.account_id}")

    # === Assembled context score ===
    if score:
        lines.append("")
        lines.append("=== Assembled Context Score ===")
        lines.append(f"Score: {score.score} (threshold: {score.threshold})")
        if score.reason_codes:
            lines.append(f"Reason codes: {', '.join(score.reason_codes)}")

    # === Event Interpretation output (if available) ===
    ei_output = request.event_interpretation_output
    if ei_output is not None:
        lines.append("")
        lines.append("=== Event Interpretation Output ===")
        lines.append(f"Overall bias: {ei_output.aggregate_view.overall_bias}")
        lines.append(f"Event conflict: {ei_output.aggregate_view.event_conflict}")
        if ei_output.aggregate_view.top_reason_codes:
            lines.append(
                "Top reason codes: "
                f"{', '.join(ei_output.aggregate_view.top_reason_codes)}"
            )

        interpreted = ei_output.events or ()
        if interpreted:
            lines.append(f"Interpreted events ({len(interpreted)}):")
            for ie in interpreted[:10]:
                if isinstance(ie, dict):
                    summary = ie.get("summary") or "(no summary)"
                    lines.append(f"  - [{ie.get('event_type', '?')}] {summary}")
                    lines.append(
                        f"    impact={ie.get('impact_direction', '?')} "
                        f"confidence={ie.get('confidence', '?')}"
                    )
                else:
                    summary = ie.summary or "(no summary)"
                    lines.append(f"  - [{ie.event_type}] {summary}")
                    lines.append(
                        f"    impact={ie.impact_direction} "
                        f"confidence={ie.confidence}"
                    )

    # === AI Risk output (if available) ===
    ar_output = request.ai_risk_output
    if ar_output is not None:
        lines.append("")
        lines.append("=== AI Risk Output ===")
        lines.append(f"Risk opinion: {ar_output.risk_opinion}")
        lines.append(f"Risk score: {ar_output.risk_score}")
        lines.append(f"Confidence: {ar_output.confidence}")
        lines.append(f"Size adjustment factor: {ar_output.size_adjustment_factor}")
        if ar_output.reason_codes:
            lines.append(f"Reason codes: {', '.join(ar_output.reason_codes)}")
        if ar_output.opposing_evidence:
            lines.append("Opposing evidence:")
            for oe in ar_output.opposing_evidence:
                lines.append(f"  - {oe}")

    # Old-style events: dash-prefix, no provenance tags
    lines.append("")
    lines.append(f"Recent events ({len(events)}):")
    for e in events[:20]:
        headline = e.headline or "(no headline)"
        summary = e.body_summary or ""
        lines.append(
            f"  - [{e.event_type}] {headline}"
            f"{' — ' + summary[:200] if summary else ''}"
        )

    return "\n".join(lines)


# ========================================================================
#  계측 함수
# ========================================================================


def _count_provenance_tags(text: str) -> dict[str, int]:
    """Count provenance tags in a prompt text."""
    return {
        "src": text.count("[src:"),
        "tier": text.count("[tier:"),
        "event_type_bracket": text.count("[") - text.count("[src:") - text.count("[tier:"),
        "issuer": text.count("[issuer:"),
        "stale": text.count("⚠️STALE"),
        "severity": text.count("[severity:"),
        "direction_positive": text.count("[positive]"),
        "direction_negative": text.count("[negative]"),
    }


def _estimate_tokens(text: str) -> int:
    """Rough token estimation (~4 chars per token for Korean/English mixed)."""
    return len(text) // 4


def _extract_event_lines(text: str) -> list[str]:
    """Extract lines that contain event data (start with '  ' or '  -')."""
    return [line for line in text.split("\n") if line.startswith("  ") and not line.startswith("  ===")]


def _compute_provenance_completeness(tags: dict[str, int], text: str, event_count: int) -> dict[str, Any]:
    """Provenance completeness score.

    5 mandatory tags per event: [src:], [tier:], [{event_type}], [date], [issuer:]
    Returns completeness ratio and per-tag coverage.
    """
    if event_count == 0:
        return {
            "score": 0.0,
            "per_tag": {},
            "total_expected": 0,
            "total_actual": 0,
        }

    expected_per_tag = event_count
    per_tag = {
        "src": min(tags["src"] / expected_per_tag, 1.0),
        "tier": min(tags["tier"] / expected_per_tag, 1.0),
        "issuer": min(tags["issuer"] / expected_per_tag, 1.0),
    }
    # event_type tags: total [ - src - tier - issuer - severity - positive - negative
    event_type_actual = max(0, tags["event_type_bracket"] - tags["severity"]
                            - tags["direction_positive"] - tags["direction_negative"])
    per_tag["event_type"] = min(event_type_actual / expected_per_tag, 1.0) if expected_per_tag > 0 else 0.0

    # date tag: count [YYYY-MM-DD] patterns
    date_count = len(re.findall(r"\[\d{4}-\d{2}-\d{2}\]", text))
    per_tag["date"] = min(date_count / expected_per_tag, 1.0) if expected_per_tag > 0 else 0.0

    total_expected = 5 * event_count
    total_actual = (
        tags["src"] + tags["tier"] + event_type_actual + date_count + tags["issuer"]
    )
    score = total_actual / max(total_expected, 1)

    return {
        "score": round(score, 3),
        "per_tag": {k: round(v, 3) for k, v in per_tag.items()},
        "total_expected": total_expected,
        "total_actual": total_actual,
    }


def _compute_context_depth(
    prompt_text: str,
    has_ei_output: bool,
    has_ar_output: bool,
    agent_type: str,  # "ar" or "fdc"
) -> dict[str, Any]:
    """Context depth 계량 (3개 하위 항목 종합).

    1. Reason-code upstream fields (0-3점):
       - Score reason_codes present
       - EI top_reason_codes present
       - AR reason_codes present (FDC only)
    2. Event context richness (0-5점):
       - Event count > 0
       - Body summary present in events
       - Source name present
       - Reliability tier present
       - Issuer code present
    3. Agent continuity coverage (0-11점):
       - EI→AR: 4 fields (overall_bias, event_conflict, top_reason_codes, interpreted_events)
       - AR→FDC: 7 fields (risk_opinion, risk_score, confidence, size_adjustment_factor,
         reason_codes, opposing_evidence, summary)
       - FDC total: EI+AR combined = 11 fields
    """
    lines = prompt_text.split("\n")

    # ── 1. Reason-code upstream fields ──
    reason_code_depth = 0
    if any("Reason codes:" in line for line in lines):
        reason_code_depth += 1  # Score reason_codes
    if has_ei_output and any("Top reason codes:" in line for line in lines):
        reason_code_depth += 1  # EI top_reason_codes
    if agent_type == "fdc" and has_ar_output:
        # FDC prompt has both score reason_codes and AR reason_codes
        rc_lines = [line for line in lines if "Reason codes:" in line]
        if len(rc_lines) >= 2:
            reason_code_depth += 1  # AR reason_codes

    # ── 2. Event context richness ──
    event_richness = 0
    event_lines = _extract_event_lines(prompt_text)
    if event_lines:
        event_richness += 1  # Event count > 0
    has_summary = bool(re.search(r" — \S", prompt_text))
    if has_summary:
        event_richness += 1
    if "[src:" in prompt_text:
        event_richness += 1
    if "[tier:" in prompt_text:
        event_richness += 1
    if "[issuer:" in prompt_text:
        event_richness += 1

    # ── 3. Agent continuity coverage ──
    continuity_score = 0
    continuity_details: dict[str, bool] = {}

    if agent_type == "ar":
        # EI→AR: 4 fields
        continuity_details["overall_bias"] = any("Overall bias:" in line for line in lines)
        continuity_details["event_conflict"] = any("Event conflict:" in line for line in lines)
        continuity_details["top_reason_codes"] = any("Top reason codes:" in line for line in lines)
        continuity_details["interpreted_events"] = any("Interpreted events" in line for line in lines)
        continuity_score = sum(1 for v in continuity_details.values() if v)

    elif agent_type == "fdc":
        # EI→AR→FDC combined: 11 fields
        continuity_details["ei_overall_bias"] = any("Overall bias:" in line for line in lines)
        continuity_details["ei_event_conflict"] = any("Event conflict:" in line for line in lines)
        continuity_details["ei_top_reason_codes"] = any("Top reason codes:" in line for line in lines)
        continuity_details["ei_interpreted_events"] = any("Interpreted events" in line for line in lines)
        continuity_details["ar_risk_opinion"] = any("Risk opinion:" in line for line in lines)
        continuity_details["ar_risk_score"] = any("Risk score:" in line for line in lines)
        continuity_details["ar_confidence"] = any("Confidence:" in line for line in lines)
        continuity_details["ar_size_adjustment"] = any("Size adjustment factor:" in line for line in lines)
        continuity_details["ar_reason_codes"] = any("Reason codes:" in line for line in lines)
        continuity_details["ar_opposing_evidence"] = any("Opposing evidence:" in line for line in lines)
        continuity_details["ar_summary"] = any("Summary:" in line for line in lines)
        continuity_score = sum(1 for v in continuity_details.values() if v)

    total_possible = MAX_AGENT_CONTINUITY if agent_type == "fdc" else len(EI_TO_AR_FIELDS)

    return {
        "reason_code_depth": min(reason_code_depth, MAX_REASON_CODE_DEPTH),
        "reason_code_depth_max": MAX_REASON_CODE_DEPTH,
        "event_richness": min(event_richness, MAX_EVENT_RICHNESS),
        "event_richness_max": MAX_EVENT_RICHNESS,
        "continuity_score": continuity_score,
        "continuity_max": total_possible,
        "continuity_details": continuity_details,
        "total_score": min(reason_code_depth + event_richness + continuity_score,
                           MAX_REASON_CODE_DEPTH + MAX_EVENT_RICHNESS + total_possible),
        "total_max": MAX_REASON_CODE_DEPTH + MAX_EVENT_RICHNESS + total_possible,
    }


def _measure_prompt_quality(
    new_prompt: str,
    old_prompt: str,
    event_count: int,
    has_ei_output: bool,
    has_ar_output: bool,
    agent_type: str,
) -> dict[str, Any]:
    """종합 prompt quality 계측.

    핵심 지표:
    - Provenance completeness (new-style only)
    - Context depth (reason_code_depth + event_richness + continuity)
    - Continuity coverage (EI→AR or EI+AR→FDC)

    보조 지표:
    - Token 증가율
    """
    new_tags = _count_provenance_tags(new_prompt)
    old_tags = _count_provenance_tags(old_prompt)
    new_tokens = _estimate_tokens(new_prompt)
    old_tokens = _estimate_tokens(old_prompt)

    provenance = _compute_provenance_completeness(new_tags, new_prompt, event_count)
    context_depth = _compute_context_depth(new_prompt, has_ei_output, has_ar_output, agent_type)

    token_increase_pct = round(((new_tokens - old_tokens) / max(old_tokens, 1)) * 100, 1)

    return {
        "tokens": {
            "old": old_tokens,
            "new": new_tokens,
            "increase_pct": token_increase_pct,
        },
        "provenance_completeness": provenance,
        "context_depth": context_depth,
        "tags_new": new_tags,
        "tags_old": old_tags,
    }


# ========================================================================
#  Inline Subclass: OLD-style prompt로 provider 호출 (스크립트 전용)
# ========================================================================


class _OldStyleAIRiskAgent(AIRiskAgent):
    """스크립트 내부 전용: OLD-style (pre-provenance) prompt로 provider 호출.

    ``_build_user_prompt()``만 override하여 OLD-style formatter를 사용.
    ``run()``의 나머지 pipeline (system prompt, fallback, error 처리)은 그대로 재사용.

    NOTE: production 경로에서 재사용되지 않음. 측정 스크립트 전용 private class.
    """

    def _build_user_prompt(self, request: AgentExecutionRequest) -> str:
        return _build_old_style_ar_prompt(request)


class _OldStyleFinalDecisionComposerAgent(FinalDecisionComposerAgent):
    """스크립트 내부 전용: OLD-style (pre-provenance) prompt로 provider 호출.

    ``_build_user_prompt()``만 override하여 OLD-style formatter를 사용.
    ``run()``의 나머지 pipeline (system prompt, fallback, error 처리)은 그대로 재사용.

    NOTE: production 경로에서 재사용되지 않음. 측정 스크립트 전용 private class.
    """

    def _build_user_prompt(self, request: AgentExecutionRequest) -> str:
        return _build_old_style_fdc_prompt(request)


# ========================================================================
#  Provider 호출 (선택적)
# ========================================================================


async def _call_provider_ar(
    agent: AIRiskAgent,
    request: AgentExecutionRequest,
    run_label: str,
) -> dict[str, Any]:
    """AR provider 호출 (선택적, 탐색적 관찰).

    NOTE: This is an exploratory observation. Results are non-deterministic
    and should not be used for causal claims about provenance impact.
    """
    try:
        result = await agent.run(request)
        return {
            "run": run_label,
            "success": True,
            "risk_opinion": result.risk_opinion,
            "risk_score": result.risk_score,
            "confidence": result.confidence,
            "reason_codes": list(result.reason_codes) if result.reason_codes else [],
            "risk_flags": list(result.risk_flags) if result.risk_flags else [],
            "summary": result.summary,
            "opposing_evidence": list(result.opposing_evidence) if result.opposing_evidence else [],
        }
    except Exception as e:
        return {
            "run": run_label,
            "success": False,
            "error": str(e),
        }


async def _call_provider_fdc(
    agent: FinalDecisionComposerAgent,
    request: AgentExecutionRequest,
    run_label: str,
) -> dict[str, Any]:
    """FDC provider 호출 (선택적, 탐색적 관찰).

    NOTE: This is an exploratory observation. Results are non-deterministic
    and should not be used for causal claims about provenance impact.
    """
    try:
        result = await agent.run(request)
        return {
            "run": run_label,
            "success": True,
            "decision_type": result.decision_type,
            "confidence": result.confidence,
            "reason_codes": list(result.reason_codes) if result.reason_codes else [],
            "opposing_evidence": list(result.opposing_evidence) if result.opposing_evidence else [],
            "summary": result.summary,
        }
    except Exception as e:
        return {
            "run": run_label,
            "success": False,
            "error": str(e),
        }


# ========================================================================
#  Symbol별 측정
# ========================================================================


async def measure_symbol(
    repos: Any,
    symbol: str,
    now: datetime,
    since: datetime,
    with_provider: bool = False,
    provider_client: Any = None,
) -> dict[str, Any]:
    """Measure AR/FDC prompt quality for a single symbol."""
    print(f"\n{SEP}")
    print(f"  Symbol: {symbol}")
    print(SEP)

    # ── 1. Event 조회 ──
    events = await repos.external_events.list_by_symbol(symbol=symbol, since=since)
    events_list = list(events)
    print(f"  Events found: {len(events_list)}")
    print(f"  Since (72h):  {since.strftime('%Y-%m-%d %H:%M:%S')}Z")

    event_types = sorted({e.event_type for e in events_list if e.event_type})
    issuer_codes = sorted({e.issuer_code for e in events_list if e.issuer_code})
    pub_dates = sorted({e.published_at.strftime("%Y-%m-%d") for e in events_list if e.published_at})
    print(f"  Event types ({len(event_types)}):")
    for et in event_types:
        cnt = sum(1 for e in events_list if e.event_type == et)
        print(f"    - {cnt}x {et}")
    print(f"  Issuer codes: {issuer_codes}")
    print(f"  Published at: {pub_dates}")

    # ── 2. 공통 context 구성 ──
    score = ScoreResult(score=75.0, threshold=60.0, reason_codes=["REASON_001"])
    context = AssembledContext(
        recent_events=tuple(events_list),
        score=score,
    )
    correlation_id = f"ar-fdc-measure-{symbol.lower()}-001"

    # ── 3. EI output 구성 (downstream 전파용) ──
    ei_output = EventInterpretationOutput(
        symbol=symbol,
        events=tuple(
            InterpretedEvent(
                source_event_id=e.source_event_id or "",
                event_type=e.event_type or "",
                source_name=e.source_name or "",
                source_reliability_tier=e.source_reliability_tier or "",
                summary=e.headline or "",
            )
            for e in events_list[:5]
        ),
        aggregate_view=AggregateEventView(
            overall_bias="neutral",
            event_conflict=False,
            top_reason_codes=("REASON_001",),
        ),
    )

    # ── 4. AR output 구성 (FDC 전파용) ──
    ar_output = AIRiskOutput(
        risk_opinion="allow",
        risk_score=0.3,
        confidence=0.8,
        size_adjustment_factor=1.0,
        reason_codes=("REASON_001",),
        summary="No significant risk detected.",
    )

    # ── 5. Request 구성 ──
    request_with_ei = AgentExecutionRequest(
        decision_context_id=UUID("00000000-0000-0000-0000-000000000001"),
        correlation_id=correlation_id,
        context=context,
        event_interpretation_output=ei_output,
    )
    request_full = AgentExecutionRequest(
        decision_context_id=UUID("00000000-0000-0000-0000-000000000001"),
        correlation_id=correlation_id,
        context=context,
        event_interpretation_output=ei_output,
        ai_risk_output=ar_output,
    )

    # ====================================================================
    #  AR Prompt Quality
    # ====================================================================
    print(f"\n  ── AR Prompt Quality ──")

    ar_agent = AIRiskAgent(provider_client=AsyncMock())
    new_ar_prompt = ar_agent._build_user_prompt(request_with_ei)
    old_ar_prompt = _build_old_style_ar_prompt(request_with_ei)

    ar_quality = _measure_prompt_quality(
        new_prompt=new_ar_prompt,
        old_prompt=old_ar_prompt,
        event_count=len(events_list),
        has_ei_output=True,
        has_ar_output=False,
        agent_type="ar",
    )

    print(f"  Token: {ar_quality['tokens']['old']} → {ar_quality['tokens']['new']} "
          f"(+{ar_quality['tokens']['increase_pct']}%) [보조 지표]")
    print(f"  Provenance completeness: {ar_quality['provenance_completeness']['score']:.1%}")
    print(f"    per_tag: {ar_quality['provenance_completeness']['per_tag']}")
    print(f"  Context depth: {ar_quality['context_depth']['total_score']}/{ar_quality['context_depth']['total_max']}")
    print(f"    reason_code_depth: {ar_quality['context_depth']['reason_code_depth']}/{ar_quality['context_depth']['reason_code_depth_max']}")
    print(f"    event_richness:    {ar_quality['context_depth']['event_richness']}/{ar_quality['context_depth']['event_richness_max']}")
    print(f"    continuity:        {ar_quality['context_depth']['continuity_score']}/{ar_quality['context_depth']['continuity_max']}")
    print(f"    continuity details: {ar_quality['context_depth']['continuity_details']}")

    # AR Symbol line check
    ar_lines = new_ar_prompt.split("\n")
    symbol_line = next((line for line in ar_lines if line.startswith("Symbol:")), "(not found)")
    symbol_bug_fixed = "DecisionContextEntity" not in symbol_line
    print(f"  AR Symbol line: {symbol_line}")
    print(f"  AR Symbol BUG fixed: {'✅' if symbol_bug_fixed else '❌'}")

    # ====================================================================
    #  FDC Prompt Quality
    # ====================================================================
    print(f"\n  ── FDC Prompt Quality ──")

    fdc_agent = FinalDecisionComposerAgent(provider_client=AsyncMock())
    new_fdc_prompt = fdc_agent._build_user_prompt(request_full)
    old_fdc_prompt = _build_old_style_fdc_prompt(request_full)

    fdc_quality = _measure_prompt_quality(
        new_prompt=new_fdc_prompt,
        old_prompt=old_fdc_prompt,
        event_count=len(events_list),
        has_ei_output=True,
        has_ar_output=True,
        agent_type="fdc",
    )

    print(f"  Token: {fdc_quality['tokens']['old']} → {fdc_quality['tokens']['new']} "
          f"(+{fdc_quality['tokens']['increase_pct']}%) [보조 지표]")
    print(f"  Provenance completeness: {fdc_quality['provenance_completeness']['score']:.1%}")
    print(f"    per_tag: {fdc_quality['provenance_completeness']['per_tag']}")
    print(f"  Context depth: {fdc_quality['context_depth']['total_score']}/{fdc_quality['context_depth']['total_max']}")
    print(f"    reason_code_depth: {fdc_quality['context_depth']['reason_code_depth']}/{fdc_quality['context_depth']['reason_code_depth_max']}")
    print(f"    event_richness:    {fdc_quality['context_depth']['event_richness']}/{fdc_quality['context_depth']['event_richness_max']}")
    print(f"    continuity:        {fdc_quality['context_depth']['continuity_score']}/{fdc_quality['context_depth']['continuity_max']}")
    print(f"    continuity details: {fdc_quality['context_depth']['continuity_details']}")

    # ====================================================================
    #  Prompt excerpt 비교
    # ====================================================================
    print(f"\n  ── AR Prompt Excerpt (events section, first 2 events) ──")
    ar_new_lines = new_ar_prompt.split("\n")
    ar_old_lines = old_ar_prompt.split("\n")
    ar_new_events_start = next((i for i, l in enumerate(ar_new_lines) if l.startswith("Recent events")), 0)
    ar_old_events_start = next((i for i, l in enumerate(ar_old_lines) if l.startswith("Recent events")), 0)
    print("  NEW-STYLE:")
    for line in ar_new_lines[ar_new_events_start:ar_new_events_start + 4]:
        print(f"    {line}")
    print("  OLD-STYLE (approximate reconstruction):")
    for line in ar_old_lines[ar_old_events_start:ar_old_events_start + 4]:
        print(f"    {line}")

    print(f"\n  ── FDC Prompt Excerpt (events section, first 2 events) ──")
    fdc_new_lines = new_fdc_prompt.split("\n")
    fdc_old_lines = old_fdc_prompt.split("\n")
    fdc_new_events_start = next((i for i, l in enumerate(fdc_new_lines) if l.startswith("Recent events")), 0)
    fdc_old_events_start = next((i for i, l in enumerate(fdc_old_lines) if l.startswith("Recent events")), 0)
    print("  NEW-STYLE:")
    for line in fdc_new_lines[fdc_new_events_start:fdc_new_events_start + 4]:
        print(f"    {line}")
    print("  OLD-STYLE (approximate reconstruction):")
    for line in fdc_old_lines[fdc_old_events_start:fdc_old_events_start + 4]:
        print(f"    {line}")

    # ====================================================================
    #  선택적 Provider 호출 (030200 only, 2-3회 반복)
    # ====================================================================
    provider_results: dict[str, Any] = {"ar": [], "fdc": []}
    if with_provider and provider_client is not None and symbol == "030200":
        print(f"\n  ── Provider 호출 (탐색적 관찰, 030200 only) ──")
        print(f"  NOTE: Results are non-deterministic. 2-3회 반복, 인과 주장 금지.")

        # ── AR: OLD-style 2회 ──
        print(f"\n  [AR] OLD-style provider 호출 (2회, approximate reconstruction):")
        for i in range(2):
            ar_old = _OldStyleAIRiskAgent(provider_client=provider_client)
            result = await _call_provider_ar(ar_old, request_with_ei, f"ar-old-{i+1}")
            provider_results["ar"].append(result)
            print(f"    run ar-old-{i+1}: opinion={result.get('risk_opinion')}, "
                  f"score={result.get('risk_score')}, success={result.get('success')}")

        # ── AR: NEW-style 2회 ──
        print(f"\n  [AR] NEW-style provider 호출 (2회, provenance-rich):")
        for i in range(2):
            ar_new = AIRiskAgent(provider_client=provider_client)
            result = await _call_provider_ar(ar_new, request_with_ei, f"ar-new-{i+1}")
            provider_results["ar"].append(result)
            print(f"    run ar-new-{i+1}: opinion={result.get('risk_opinion')}, "
                  f"score={result.get('risk_score')}, success={result.get('success')}")

        # ── FDC: OLD-style 2회 ──
        print(f"\n  [FDC] OLD-style provider 호출 (2회, approximate reconstruction):")
        for i in range(2):
            fdc_old = _OldStyleFinalDecisionComposerAgent(provider_client=provider_client)
            result = await _call_provider_fdc(fdc_old, request_full, f"fdc-old-{i+1}")
            provider_results["fdc"].append(result)
            print(f"    run fdc-old-{i+1}: decision={result.get('decision_type')}, "
                  f"confidence={result.get('confidence')}, success={result.get('success')}")

        # ── FDC: NEW-style 2회 ──
        print(f"\n  [FDC] NEW-style provider 호출 (2회, provenance-rich):")
        for i in range(2):
            fdc_new = FinalDecisionComposerAgent(provider_client=provider_client)
            result = await _call_provider_fdc(fdc_new, request_full, f"fdc-new-{i+1}")
            provider_results["fdc"].append(result)
            print(f"    run fdc-new-{i+1}: decision={result.get('decision_type')}, "
                  f"confidence={result.get('confidence')}, success={result.get('success')}")

    # ── 9. 결과 수집 ──
    result: dict[str, Any] = {
        "symbol": symbol,
        "events_count": len(events_list),
        "event_types": event_types,
        "issuer_codes": issuer_codes,
        "published_dates": pub_dates,
        "ar": {
            "quality": ar_quality,
            "symbol_bug_fixed": symbol_bug_fixed,
            "symbol_line_excerpt": symbol_line,
        },
        "fdc": {
            "quality": fdc_quality,
        },
        "provider_results": provider_results,
    }

    return result


async def main() -> int:
    """Run measurement for all symbols."""
    parser = argparse.ArgumentParser(
        description="EI→AR→FDC provenance 전파 이후 output 변화 측정"
    )
    parser.add_argument(
        "--with-provider",
        action="store_true",
        help="선택적 provider 호출 (030200 only, 2회 반복, 탐색적 관찰)",
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=72)

    print(SEP)
    print("  EI→AR→FDC Provenance 전파 이후 Output 변화 측정")
    print(SEP)
    print(f"  측정 시각 (UTC): {now.strftime('%Y-%m-%d %H:%M:%S')}Z")
    print(f"  72h since:       {since.strftime('%Y-%m-%d %H:%M:%S')}Z")
    print(f"  대상 symbol:     {', '.join(SYMBOLS)}")
    print(f"  Provider 호출:   {'✅ (030200 only, 탐색적 관찰)' if args.with_provider else '❌ (read-only)'}")
    print(SEP)

    async with postgres_runtime() as runtime:
        repos = runtime["repositories"]

        # Provider client (선택적)
        provider_client = None
        if args.with_provider:
            try:
                from agent_trading.services.ai_agents.provider_client import OpenAICompatibleClient
                from agent_trading.config.settings import AppSettings
                settings = AppSettings()
                provider_client = OpenAICompatibleClient(
                    api_key=settings.provider_api_key,
                    base_url=settings.provider_base_url,
                    timeout_seconds=settings.provider_timeout_seconds,
                )
                print("  Provider client initialized (OpenAICompatibleClient).")
            except (ImportError, AttributeError) as e:
                print(f"  ⚠️ Provider client not available: {e}. Skipping provider calls.")
                provider_client = None

        all_results: list[dict[str, Any]] = []
        for symbol in SYMBOLS:
            result = await measure_symbol(
                repos, symbol, now, since,
                with_provider=args.with_provider,
                provider_client=provider_client,
            )
            all_results.append(result)

        # ── 종합 요약 ──
        print(f"\n{SEP}")
        print("  종합 요약")
        print(SEP)

        for r in all_results:
            sym = r["symbol"]
            ec = r["events_count"]
            ar_q = r["ar"]["quality"]
            fdc_q = r["fdc"]["quality"]

            print(f"\n  [{sym}] events={ec}")

            # AR
            ar_prov = ar_q["provenance_completeness"]["score"]
            ar_ctx = ar_q["context_depth"]
            ar_tok = ar_q["tokens"]["increase_pct"]
            print(f"    AR: prov={ar_prov:.0%} ctx={ar_ctx['total_score']}/{ar_ctx['total_max']} "
                  f"tok=+{ar_tok}% [보조] sym_bug_fixed={r['ar']['symbol_bug_fixed']}")

            # FDC
            fdc_prov = fdc_q["provenance_completeness"]["score"]
            fdc_ctx = fdc_q["context_depth"]
            fdc_tok = fdc_q["tokens"]["increase_pct"]
            print(f"    FDC: prov={fdc_prov:.0%} ctx={fdc_ctx['total_score']}/{fdc_ctx['total_max']} "
                  f"tok=+{fdc_tok}% [보조]")

        # ── 최종 판정 ──
        print(f"\n{DASH}")
        print("  최종 판정")
        print(DASH)

        # Provenance completeness
        all_ar_prov_ok = all(r["ar"]["quality"]["provenance_completeness"]["score"] >= 0.8
                             for r in all_results)
        all_fdc_prov_ok = all(r["fdc"]["quality"]["provenance_completeness"]["score"] >= 0.8
                              for r in all_results)

        # Context depth
        all_ar_ctx_ok = all(
            r["ar"]["quality"]["context_depth"]["continuity_score"] >= 3
            for r in all_results
        )
        all_fdc_ctx_ok = all(
            r["fdc"]["quality"]["context_depth"]["continuity_score"] >= 9
            for r in all_results
        )

        # Symbol bug
        all_symbol_fixed = all(r["ar"]["symbol_bug_fixed"] for r in all_results)

        # Token overhead
        max_token_increase = max(
            r["ar"]["quality"]["tokens"]["increase_pct"]
            for r in all_results
        )

        print(f"\n  [판정 기준] provenance completeness + continuity + context depth 중심")
        print(f"  [보조] token 증가율: max={max_token_increase}%")

        if all_ar_prov_ok and all_fdc_prov_ok and all_ar_ctx_ok and all_fdc_ctx_ok and all_symbol_fixed:
            print(f"\n  ▶ 종합 판정: 명확한 개선")
            print(f"    - AR/FDC 모두 provenance tags complete (≥80%)")
            print(f"    - Continuity coverage: AR≥3/4, FDC≥9/11")
            print(f"    - AR Symbol BUG fixed: ✅")
            print(f"    - Token overhead acceptable: max +{max_token_increase}%")
        elif all_ar_prov_ok and all_fdc_prov_ok:
            print(f"\n  ▶ 종합 판정: 제한적 개선")
            print(f"    - Provenance tags complete but continuity/context depth gap exists")
            if not all_ar_ctx_ok:
                print(f"    - AR continuity < 3/4")
            if not all_fdc_ctx_ok:
                print(f"    - FDC continuity < 9/11")
            if not all_symbol_fixed:
                print(f"    - AR Symbol BUG not fully fixed")
        else:
            print(f"\n  ▶ 종합 판정: 불명확")
            print(f"    - Provenance completeness or continuity has major gaps")
            if not all_ar_prov_ok:
                print(f"    - AR provenance < 80%")
            if not all_fdc_prov_ok:
                print(f"    - FDC provenance < 80%")

        # Provider 결과 (있을 경우)
        if args.with_provider and provider_client is not None:
            print(f"\n{DASH}")
            print("  Provider 호출 결과 (참고용, 탐색적 관찰)")
            print(DASH)
            print("""
    NOTE: Provider 호출 결과는 비결정성(non-deterministic)을 가지며,
    provenance 개선과 output 변화 사이의 인과 관계를 증명하지 않습니다.
    아래 결과는 단순 참고용 관찰 데이터입니다.
    OLD-style prompt는 approximate reconstruction입니다 (historical exact replay 아님).
            """)
            for r in all_results:
                sym = r["symbol"]
                ar_results = r["provider_results"]["ar"]
                fdc_results = r["provider_results"]["fdc"]

                if ar_results:
                    print(f"\n  [{sym}] AR provider results (OLD vs NEW):")
                    old_ar = [pr for pr in ar_results if "old" in pr.get("run", "")]
                    new_ar = [pr for pr in ar_results if "new" in pr.get("run", "")]
                    print(f"    OLD-style (approximate reconstruction):")
                    for pr in old_ar:
                        print(f"      {pr['run']}: opinion={pr.get('risk_opinion')}, "
                              f"score={pr.get('risk_score')}, "
                              f"codes={pr.get('reason_codes')}, "
                              f"flags={pr.get('risk_flags')}, "
                              f"success={pr.get('success')}")
                    print(f"    NEW-style (provenance-rich):")
                    for pr in new_ar:
                        print(f"      {pr['run']}: opinion={pr.get('risk_opinion')}, "
                              f"score={pr.get('risk_score')}, "
                              f"codes={pr.get('reason_codes')}, "
                              f"flags={pr.get('risk_flags')}, "
                              f"success={pr.get('success')}")

                if fdc_results:
                    print(f"\n  [{sym}] FDC provider results (OLD vs NEW):")
                    old_fdc = [pr for pr in fdc_results if "old" in pr.get("run", "")]
                    new_fdc = [pr for pr in fdc_results if "new" in pr.get("run", "")]
                    print(f"    OLD-style (approximate reconstruction):")
                    for pr in old_fdc:
                        print(f"      {pr['run']}: decision={pr.get('decision_type')}, "
                              f"confidence={pr.get('confidence')}, "
                              f"codes={pr.get('reason_codes')}, "
                              f"evidence={pr.get('opposing_evidence')}, "
                              f"success={pr.get('success')}")
                    print(f"    NEW-style (provenance-rich):")
                    for pr in new_fdc:
                        print(f"      {pr['run']}: decision={pr.get('decision_type')}, "
                              f"confidence={pr.get('confidence')}, "
                              f"codes={pr.get('reason_codes')}, "
                              f"evidence={pr.get('opposing_evidence')}, "
                              f"success={pr.get('success')}")

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    exit_code = asyncio.run(main())
    sys.exit(exit_code)