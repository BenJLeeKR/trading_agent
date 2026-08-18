from __future__ import annotations

from dataclasses import dataclass

# FDC(Final Decision Composer)가 source_type별로 선택 가능한 decision_type
# 집합(2026-08-18 KST 추가). held_position은 신규 매수(APPROVE/BUY) 의미론이
# 허용되지 않는 lane이므로, 사후 강등(evaluate_action_envelope/
# _check_source_policy_upgrade_guard)에만 의존하지 않고 AI 선택지 자체를
# 좁혀 "왜 안 사는지"를 매번 추론하는 토큰 낭비를 줄인다. SELL은 canonical
# held_position sell path(REDUCE/EXIT + side=SELL — held_position_policy.
# is_held_position_sell_path 참고)에서 쓰이지 않고, 실측(2026-08-18 DB
# 조회)상으로도 held_position에서 decision_type='SELL'이 사실상 쓰이지
# 않아 함께 제외한다.
HELD_POSITION_ALLOWED_DECISION_TYPES: tuple[str, ...] = (
    "REDUCE",
    "EXIT",
    "HOLD",
    "WATCH",
)
DEFAULT_ALLOWED_DECISION_TYPES: tuple[str, ...] = (
    "APPROVE",
    "BUY",
    "SELL",
    "HOLD",
    "WATCH",
    "EXIT",
    "REDUCE",
)


def allowed_fdc_decision_types(source_type: str | None) -> tuple[str, ...]:
    """FDC가 이 source_type에서 선택 가능한 ``decision_type`` 집합을 반환한다.

    이 함수는 프롬프트 생성(``FinalDecisionComposerAgent._build_system_
    prompt()``)과 출력 정규화(``_guard_held_position_decision_type()``)
    양쪽에서 공유하는 단일 소스다 — 두 곳이 서로 다른 허용 목록을 갖는
    드리프트를 방지한다.
    """
    normalized = (source_type or "core").strip().lower()
    if normalized == "held_position":
        return HELD_POSITION_ALLOWED_DECISION_TYPES
    return DEFAULT_ALLOWED_DECISION_TYPES


@dataclass(slots=True, frozen=True)
class SourceActionEnvelope:
    """source_type별 허용 가능한 행동 범위."""

    source_type: str
    has_position: bool
    allow_new_buy: bool
    reason_codes: tuple[str, ...] = ()


def evaluate_action_envelope(
    *,
    source_type: str,
    has_position: bool,
) -> SourceActionEnvelope:
    """source_type별 신규 BUY 허용 여부를 결정한다."""
    normalized = (source_type or "core").strip().lower()

    if normalized == "held_position":
        return SourceActionEnvelope(
            source_type=normalized,
            has_position=has_position,
            allow_new_buy=False,
            reason_codes=("policy_held_position_buy_blocked",),
        )

    if normalized == "reconciliation_overlay" and not has_position:
        return SourceActionEnvelope(
            source_type=normalized,
            has_position=has_position,
            allow_new_buy=False,
            reason_codes=("policy_reconciliation_overlay_flat_buy_blocked",),
        )

    return SourceActionEnvelope(
        source_type=normalized,
        has_position=has_position,
        allow_new_buy=True,
        reason_codes=(),
    )
