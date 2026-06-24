from __future__ import annotations

from dataclasses import dataclass


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
