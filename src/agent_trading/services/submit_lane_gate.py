from __future__ import annotations

from dataclasses import dataclass

from agent_trading.domain.enums import (
    PipelineStopReason,
    general_submit_disabled_reason,
    submit_budget_consumed_reason,
)
from agent_trading.services.validators import (
    RuleOutcome,
    ValidationContext,
    ValidationResult,
    ValidationRule,
    run_validation_rules,
)

HELD_POSITION_SELL_MAX_PER_CYCLE = 2
"""Legacy constant kept for compatibility with older tests and docs."""


@dataclass(slots=True, frozen=True)
class SubmitLaneDecision:
    """Deterministic scheduler submit-lane evaluation result."""

    submit: bool
    dry_run: bool
    dry_run_reason: str | None = None
    validation_result: ValidationResult | None = None


def _build_submit_lane_context(
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
    held_position_sell_max_per_cycle: int,
) -> ValidationContext:
    return ValidationContext(
        symbol=symbol,
        source_type=source_type,
        metadata={
            "submit": submit,
            "dry_run": dry_run,
            "allow_general_submit": allow_general_submit,
            "submit_budget_consumed_count": submit_budget_consumed_count,
            "max_general_submits_this_cycle": max_general_submits_this_cycle,
            "held_position_sell_cycle_count": held_position_sell_cycle_count,
            "held_position_sell_cycle_symbols": sorted(
                held_position_sell_cycle_symbols
            ),
            "held_position_sell_max_per_cycle": held_position_sell_max_per_cycle,
        },
    )


def _evaluate_cli_dry_run(context: ValidationContext) -> RuleOutcome:
    if context.metadata.get("submit") and not context.metadata.get("dry_run"):
        return RuleOutcome(code="submit_requested", passed=True)
    return RuleOutcome(
        code=PipelineStopReason.CLI_DRY_RUN.value,
        passed=False,
        details={"reason": "submit_disabled_or_dry_run"},
    )


def _evaluate_held_position_duplicate(context: ValidationContext) -> RuleOutcome:
    if context.source_type != "held_position":
        return RuleOutcome(code="held_position_lane_not_applicable", passed=True)
    cycle_symbols = set(context.metadata.get("held_position_sell_cycle_symbols", ()))
    if context.symbol in cycle_symbols:
        return RuleOutcome(
            code=PipelineStopReason.HELD_POSITION_SELL_SYMBOL_DUPLICATE.value,
            passed=False,
            details={"symbol": context.symbol},
        )
    return RuleOutcome(code="held_position_symbol_unique", passed=True)


def _evaluate_general_submit_enabled(context: ValidationContext) -> RuleOutcome:
    if context.source_type == "held_position":
        return RuleOutcome(code="general_submit_gate_bypassed", passed=True)
    if context.metadata.get("allow_general_submit"):
        return RuleOutcome(code="general_submit_enabled", passed=True)
    return RuleOutcome(
        code=general_submit_disabled_reason(context.source_type or "core"),
        passed=False,
    )


def _evaluate_general_submit_budget(context: ValidationContext) -> RuleOutcome:
    if context.source_type == "held_position":
        return RuleOutcome(code="general_submit_budget_bypassed", passed=True)
    consumed = int(context.metadata.get("submit_budget_consumed_count", 0))
    max_budget = int(context.metadata.get("max_general_submits_this_cycle", 0))
    if consumed < max_budget:
        return RuleOutcome(code="submit_budget_available", passed=True)
    return RuleOutcome(
        code=submit_budget_consumed_reason(context.source_type or "core"),
        passed=False,
        details={"submit_budget_consumed_count": consumed, "max_budget": max_budget},
    )


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
    consumed earlier in the same scheduler cycle.

    현재 운영 정책에서는 held-position 경로에 cycle-level submit cap을
    적용하지 않는다. 다만 같은 cycle 내 동일 symbol 중복 submit은
    continue 방지를 위해 막는다.
    """
    context = _build_submit_lane_context(
        submit=submit,
        dry_run=dry_run,
        allow_general_submit=allow_general_submit,
        source_type=source_type,
        submit_budget_consumed_count=submit_budget_consumed_count,
        max_general_submits_this_cycle=max_general_submits_this_cycle,
        held_position_sell_cycle_count=held_position_sell_cycle_count,
        held_position_sell_cycle_symbols=held_position_sell_cycle_symbols,
        symbol=symbol,
        held_position_sell_max_per_cycle=held_position_sell_max_per_cycle,
    )
    validation_result = run_validation_rules(
        rule_set_version="submit_lane_gate_v1",
        context=context,
        rules=(
            ValidationRule(name="cli_dry_run", evaluator=_evaluate_cli_dry_run),
            ValidationRule(
                name="held_position_duplicate",
                evaluator=_evaluate_held_position_duplicate,
            ),
            ValidationRule(
                name="general_submit_enabled",
                evaluator=_evaluate_general_submit_enabled,
            ),
            ValidationRule(
                name="general_submit_budget",
                evaluator=_evaluate_general_submit_budget,
            ),
        ),
    )
    if validation_result.is_blocking:
        return SubmitLaneDecision(
            submit=False,
            dry_run=True,
            dry_run_reason=validation_result.stop_reason,
            validation_result=validation_result,
        )

    return SubmitLaneDecision(
        submit=True,
        dry_run=False,
        dry_run_reason=None,
        validation_result=validation_result,
    )
