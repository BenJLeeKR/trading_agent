from __future__ import annotations

from dataclasses import dataclass

from agent_trading.domain.enums import (
    PipelineStopReason,
    general_submit_disabled_reason,
    submit_budget_consumed_reason,
)

HELD_POSITION_SELL_MAX_PER_CYCLE = 2
"""Per-cycle cap for held-position REDUCE/EXIT SELL submit lane."""


@dataclass(slots=True, frozen=True)
class SubmitLaneDecision:
    """Deterministic scheduler submit-lane evaluation result."""

    submit: bool
    dry_run: bool
    dry_run_reason: str | None = None


def evaluate_symbol_submit_lane(
    *,
    submit: bool,
    dry_run: bool,
    allow_general_submit: bool,
    source_type: str,
    submit_budget_consumed_count: int,
    max_general_submits_this_cycle: int,
    held_position_sell_cycle_count: int,
    held_position_sell_cycle_symbols: set[str],
    symbol: str,
    held_position_sell_max_per_cycle: int = HELD_POSITION_SELL_MAX_PER_CYCLE,
) -> SubmitLaneDecision:
    """Return the canonical per-symbol scheduler lane decision.

    ``held_position`` items use a dedicated lane so that a risk-reducing SELL
    candidate is not downgraded merely because a general BUY slot was already
    consumed earlier in the same scheduler cycle. That lane still respects a
    cycle-level cap and same-symbol deduplication.
    """
    if not submit or dry_run:
        return SubmitLaneDecision(
            submit=False,
            dry_run=True,
            dry_run_reason=PipelineStopReason.CLI_DRY_RUN.value,
        )

    if source_type == "held_position":
        if held_position_sell_cycle_count >= held_position_sell_max_per_cycle:
            return SubmitLaneDecision(
                submit=False,
                dry_run=True,
                dry_run_reason=PipelineStopReason.HELD_POSITION_SELL_CYCLE_CAP.value,
            )
        if symbol in held_position_sell_cycle_symbols:
            return SubmitLaneDecision(
                submit=False,
                dry_run=True,
                dry_run_reason=PipelineStopReason.HELD_POSITION_SELL_SYMBOL_DUPLICATE.value,
            )
        return SubmitLaneDecision(submit=True, dry_run=False, dry_run_reason=None)

    if not allow_general_submit:
        return SubmitLaneDecision(
            submit=False,
            dry_run=True,
            dry_run_reason=general_submit_disabled_reason(source_type),
        )

    if submit_budget_consumed_count >= max_general_submits_this_cycle:
        return SubmitLaneDecision(
            submit=False,
            dry_run=True,
            dry_run_reason=submit_budget_consumed_reason(source_type),
        )

    return SubmitLaneDecision(submit=True, dry_run=False, dry_run_reason=None)
