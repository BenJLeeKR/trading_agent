"""AR(``ai_risk``)/EI(``event_interpretation``) **shadow 관측** 전용 순수 계산.

이 모듈은 어떤 실행 경로에도 개입하지 않는다. 계산만 하고 값을 반환할
뿐, DB 쓰기·주문 제출·decision_type 변경은 전혀 하지 않는다 — 그건
호출자인 ``decision_orchestrator.py``의 몫이며, 거기서도 ``agent_bundle``을
바꾸는 어떤 guard 함수 목록에도 들어가지 않고 실제 결정이 모두 확정된
뒤 관측 전용으로만 호출된다(``loss_cut_shadow.py``와 동일한 순수 함수
스타일).

목적: AR/EI를 즉시 deterministic bot으로 대체하지 않고, 같은 decision
context에서 rule 기반 shadow 판단을 병렬로 계산해 AI 판단과의 일치율을
관측한다. EV gate는 신규 매수 주경로에서 이미 제거된 상태이므로 이
모듈의 핵심 판단 로직에는 EV 관련 입력을 사용하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_trading.domain.entities import ExternalEventEntity
from agent_trading.services.deterministic_trigger_engine import (
    DeterministicTriggerAssessment,
)
from agent_trading.services.market_regime import MarketRegimeAssessment
from agent_trading.services.portfolio_allocation import PortfolioAllocationAssessment

AR_SHADOW_RULE_SET_VERSION = "ar_shadow_v1"
EI_SHADOW_RULE_SET_VERSION = "ei_shadow_v1"
EI_BOT_RULE_SET_VERSION = "ei_bot_v1"
"""EI가 deterministic bot으로 본경로 전환된 뒤(PR1) 사용하는 rule set
버전 — ``EI_SHADOW_RULE_SET_VERSION``과 동일한 계산 로직을 쓰지만,
관측 전용 shadow 호출과 본경로 호출을 reason_codes 마커로 구분하기
위한 별도 상수다."""
AR_BOT_RULE_SET_VERSION = "ar_bot_v1"
"""AR이 deterministic bot으로 본경로 전환된 뒤(PR2) 사용하는 rule set
버전 — ``AR_SHADOW_RULE_SET_VERSION``과 동일한 계산 로직을 쓰지만,
관측 전용 shadow 호출과 본경로 호출을 reason_codes 마커로 구분하기
위한 별도 상수다."""

# risk_score를 사람이 비교하기 쉬운 구간으로 나누는 고정 경계값.
# AI risk_score와 bot risk_score를 같은 버킷 기준으로 비교하기 위한 것으로,
# 실제 게이트 임계값(0.6/0.8/0.85 등)과는 별개의 관측용 구분이다.
_SCORE_BUCKET_BOUNDARIES: tuple[float, ...] = (0.2, 0.4, 0.6, 0.8)
_SCORE_BUCKET_LABELS: tuple[str, ...] = (
    "0.0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0",
)


def risk_score_bucket(score: float) -> str:
    """risk_score(0.0-1.0)를 5개 고정 구간 중 하나로 매핑한다."""
    clamped = max(0.0, min(1.0, float(score or 0.0)))
    for boundary, label in zip(_SCORE_BUCKET_BOUNDARIES, _SCORE_BUCKET_LABELS):
        if clamped < boundary:
            return label
    return _SCORE_BUCKET_LABELS[-1]


def _classify_event_direction_counts(
    recent_events: tuple[ExternalEventEntity, ...],
) -> tuple[int, int, int]:
    """(positive_count, negative_count, neutral_count)를 반환한다."""
    positive = sum(1 for e in recent_events if e.direction == "positive")
    negative = sum(1 for e in recent_events if e.direction == "negative")
    neutral = len(recent_events) - positive - negative
    return positive, negative, neutral


# ============================================================================
# AR(ai_risk) shadow bot
# ============================================================================


@dataclass(slots=True, frozen=True)
class ShadowRiskBotResult:
    """AR shadow bot의 순수 계산 결과."""

    risk_opinion: str
    risk_score: float
    reason_codes: tuple[str, ...] = ()
    risk_flags: tuple[str, ...] = ()
    confidence: float = 1.0


def compute_shadow_risk_bot(
    *,
    portfolio_allocation: PortfolioAllocationAssessment | None,
    market_regime: MarketRegimeAssessment | None,
    deterministic_trigger: DeterministicTriggerAssessment | None,
    recent_events: tuple[ExternalEventEntity, ...] = (),
    rule_set_marker: str = f"shadow_rule_set:{AR_SHADOW_RULE_SET_VERSION}",
) -> ShadowRiskBotResult:
    """정형 신호만으로 risk_opinion/risk_score를 계산한다(LLM 호출 없음).

    확실한 정형 근거가 없으면 과도하게 차단하지 않는다 — 근거가 있는
    조건만 점수에 반영하고, 아무 근거도 없으면 항상 ``allow``/``0.0``이다.

    ``rule_set_marker``: 첫 번째 ``reason_codes`` 항목으로 남는 마커
    문자열. 기본값은 관측 전용 shadow bot 호출(``decision_
    orchestrator.py._record_ar_shadow_bot_observation``)과 호환되는
    ``shadow_rule_set:*``이며, 본경로 AR bot(``DeterministicAIRiskAgent``,
    PR2)은 ``deterministic_rule_set:ar_bot_v1``을 넘겨 shadow 관측용
    마커와 구분한다. 계산 로직 자체는 두 호출자가 완전히 동일하게
    공유한다.

    ``risk_opinion`` 등급(2026-08-17 PR2에서 ``reject`` 등급 추가):
    ``score>=0.9`` → ``reject``(예: concentration 초과(0.4) + 현금
    부족(0.3) + risk-off regime(0.2) 동시 발생 = 0.9의 극단 조합),
    ``0.8<=score<0.9`` → ``reduce``, ``0.5<=score<0.8`` → ``review``,
    그 미만은 ``allow``. ``reject``는 새 주문 차단을 추가하는 것이
    아니라, 이미 존재하는 held_position override(``risk_opinion in
    ("reject","reduce")``)/FDC skip(``risk_opinion=="reject"`` 조건이
    score와 무관하게 즉시 skip) 판정이 기대하는 신호를 deterministic
    bot도 낼 수 있게 하는 것이다(design review §5.4/5.6 참고).
    """
    score = 0.0
    reason_codes: list[str] = [rule_set_marker]
    risk_flags: list[str] = []

    if portfolio_allocation is not None:
        remaining_concentration_pct = portfolio_allocation.remaining_concentration_pct
        if remaining_concentration_pct is not None:
            if remaining_concentration_pct <= 0:
                score += 0.4
                risk_flags.append("concentration_over_limit")
                reason_codes.append("concentration_over_limit")
            elif remaining_concentration_pct < 2.0:
                score += 0.2
                risk_flags.append("concentration_approaching_limit")
                reason_codes.append("concentration_approaching_limit")
            else:
                reason_codes.append("not_overconcentrated")

        remaining_gross_budget_pct = portfolio_allocation.remaining_gross_budget_pct
        if remaining_gross_budget_pct is not None:
            if remaining_gross_budget_pct <= 0:
                score += 0.3
                risk_flags.append("insufficient_cash")
                reason_codes.append("insufficient_cash")
            else:
                reason_codes.append("sufficient_cash")

    if market_regime is not None:
        if market_regime.risk_tone == "risk_off":
            score += 0.2
            risk_flags.append("risk_off_regime")
            reason_codes.append("risk_off_regime")
        else:
            reason_codes.append(f"regime_risk_tone_{market_regime.risk_tone}")
        if market_regime.volatility_regime in {
            "high_volatility", "elevated_volatility",
        }:
            score += 0.2
            risk_flags.append("volatility_elevated")
            reason_codes.append("volatility_elevated")

    positive, negative, _neutral = _classify_event_direction_counts(recent_events)
    if positive > 0 and negative > 0:
        score += 0.1
        risk_flags.append("event_conflict")
        reason_codes.append("event_conflict")

    if deterministic_trigger is not None and not bool(
        getattr(deterministic_trigger, "eligibility_passed", True)
    ):
        reason_codes.append("deterministic_eligibility_not_passed")

    # round()로 부동소수점 가산 오차(예: 0.4+0.3+0.2 == 0.8999999999999999)를
    # 제거한다 — 그렇지 않으면 정확히 threshold에 걸치는 조합이 threshold
    # 미만으로 판정되는 경계값 버그가 생긴다.
    score = round(max(0.0, min(1.0, score)), 4)

    if score >= 0.9:
        opinion = "reject"
    elif score >= 0.8:
        opinion = "reduce"
    elif score >= 0.5:
        opinion = "review"
    else:
        opinion = "allow"

    return ShadowRiskBotResult(
        risk_opinion=opinion,
        risk_score=score,
        reason_codes=tuple(reason_codes),
        risk_flags=tuple(risk_flags),
        confidence=1.0,
    )


# ============================================================================
# EI(event_interpretation) shadow bot
# ============================================================================


@dataclass(slots=True, frozen=True)
class ShadowEventBotResult:
    """EI shadow bot의 순수 계산 결과."""

    detected_event_count: int
    interpreted_event_count: int
    event_bias: str
    event_conflict: bool
    evidence_strength: str
    no_material_events: bool
    reason_codes: tuple[str, ...] = ()


def compute_shadow_event_bot(
    recent_events: tuple[ExternalEventEntity, ...],
    *,
    rule_set_marker: str = f"shadow_rule_set:{EI_SHADOW_RULE_SET_VERSION}",
) -> ShadowEventBotResult:
    """정형 이벤트 필드(``direction``/``severity``/``source_reliability_tier``)
    만으로 이벤트 해석을 계산한다(LLM 호출 없음, 비정형 헤드라인/본문
    텍스트 해석은 하지 않는다).

    ``rule_set_marker``: 첫 번째 ``reason_codes`` 항목으로 남는 마커
    문자열. 기본값은 관측 전용 shadow bot 호출(``decision_
    orchestrator.py._record_ei_shadow_bot_observation``)과 호환되는
    ``shadow_rule_set:*``이며, 본경로 EI bot(``DeterministicEvent
    InterpretationAgent``)은 ``deterministic_rule_set:ei_bot_v1``을
    넘겨 shadow 관측용 마커와 구분한다. 계산 로직 자체는 두 호출자가
    완전히 동일하게 공유한다.
    """
    count = len(recent_events)
    reason_codes: list[str] = [rule_set_marker]

    if count == 0:
        return ShadowEventBotResult(
            detected_event_count=0,
            interpreted_event_count=0,
            event_bias="neutral",
            event_conflict=False,
            evidence_strength="none",
            no_material_events=True,
            reason_codes=tuple(reason_codes + ["no_material_events"]),
        )

    positive, negative, _neutral = _classify_event_direction_counts(recent_events)
    event_conflict = positive > 0 and negative > 0
    if event_conflict:
        reason_codes.append("event_conflict_detected")

    if positive > negative:
        bias = "positive"
    elif negative > positive:
        bias = "negative"
    else:
        bias = "neutral"
    reason_codes.append(f"bot_bias_{bias}")

    has_t1_source = any(
        e.source_reliability_tier == "T1" for e in recent_events
    )
    if count >= 4:
        evidence_strength = "strong"
    elif count >= 2:
        evidence_strength = "moderate"
    else:
        evidence_strength = "weak"
    if has_t1_source and evidence_strength != "strong":
        evidence_strength = (
            "strong" if evidence_strength == "moderate" else "moderate"
        )
        reason_codes.append("t1_source_present")

    return ShadowEventBotResult(
        detected_event_count=count,
        interpreted_event_count=count,
        event_bias=bias,
        event_conflict=event_conflict,
        evidence_strength=evidence_strength,
        no_material_events=False,
        reason_codes=tuple(reason_codes),
    )
