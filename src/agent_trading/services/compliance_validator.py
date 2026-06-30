from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from agent_trading.domain.enums import OrderSide, OrderType
from agent_trading.services.source_policy import evaluate_action_envelope
from agent_trading.services.validators import (
    RuleOutcome,
    ValidationContext,
    ValidationResult,
    ValidationRule,
    run_validation_rules,
)


@dataclass(slots=True, frozen=True)
class ComplianceValidationInput:
    """deterministic compliance validator 입력."""

    source_type: str
    has_position: bool
    intent_action: str = "new_buy"
    account_ref: str | None = None
    symbol: str | None = None
    market: str | None = None
    strategy_id: str | None = None
    client_order_id: str | None = None
    side: str | None = None
    order_type: str | None = None
    quantity: str | None = None
    price: str | None = None
    tr_stop_yn: str | None = None
    admn_item_yn: str | None = None
    nxt_tr_stop_yn: str | None = None
    temp_stop_yn: str | None = None
    iscd_stat_cls_code: str | None = None
    status_reason_codes: tuple[str, ...] = ()
    status_snapshot_at: datetime | None = None
    status_source_type: str | None = None
    allow_unknown_status_for_sell: bool = True
    blocked_reason_codes: tuple[str, ...] = ()
    supported_order_types: tuple[str, ...] = ()
    holding_profile: str | None = None
    earliest_reduce_at: datetime | None = None
    earliest_reentry_at: datetime | None = None


_STATUS_BLOCK_CODES: frozenset[str] = frozenset({"01", "02", "03", "04", "05"})


def _normalized_flag(value: str | None) -> str:
    return str(value or "").strip().upper()


def evaluate_compliance_rules(
    *,
    context: ValidationContext,
    validation_input: ComplianceValidationInput,
) -> ValidationResult:
    """Phase 1 compliance hard rule 평가.

    현재 범위는 source policy 기반 신규 진입 금지 규칙만 먼저 닫는다.
    """

    normalized_source_type = (validation_input.source_type or "core").strip().lower()
    envelope = evaluate_action_envelope(
        source_type=normalized_source_type,
        has_position=validation_input.has_position,
    )
    has_status_snapshot = (
        validation_input.status_snapshot_at is not None
        or bool(validation_input.status_reason_codes)
        or bool(_normalized_flag(validation_input.tr_stop_yn))
        or bool(_normalized_flag(validation_input.admn_item_yn))
        or bool(_normalized_flag(validation_input.nxt_tr_stop_yn))
        or bool(_normalized_flag(validation_input.temp_stop_yn))
        or bool(str(validation_input.iscd_stat_cls_code or "").strip())
    )
    allow_sell_override = (
        validation_input.allow_unknown_status_for_sell
        and validation_input.has_position
        and validation_input.intent_action != "new_buy"
        and (validation_input.side or "").strip().lower() == OrderSide.SELL.value
    )

    def _source_policy_buy_rule(_context: ValidationContext) -> RuleOutcome:
        if validation_input.intent_action != "new_buy":
            return RuleOutcome(
                code="compliance_source_policy_not_applicable",
                passed=True,
            )
        if envelope.allow_new_buy:
            return RuleOutcome(
                code="compliance_source_policy_buy_allowed",
                passed=True,
                details={"source_type": normalized_source_type},
            )
        return RuleOutcome(
            code="source_policy_buy_blocked",
            passed=False,
            details={
                "source_type": normalized_source_type,
                "policy_reason_codes": envelope.reason_codes,
            },
        )

    def _reconciliation_overlay_flat_buy_rule(
        _context: ValidationContext,
    ) -> RuleOutcome:
        if (
            normalized_source_type == "reconciliation_overlay"
            and validation_input.intent_action == "new_buy"
            and not validation_input.has_position
            and not envelope.allow_new_buy
        ):
            return RuleOutcome(
                code="policy_reconciliation_overlay_flat_buy_blocked",
                passed=False,
                details={
                    "source_type": normalized_source_type,
                    "has_position": validation_input.has_position,
                },
            )
        return RuleOutcome(
            code="compliance_reconciliation_overlay_buy_allowed",
            passed=True,
        )

    def _required_field_rule(_context: ValidationContext) -> RuleOutcome:
        required_values = {
            "account_ref": validation_input.account_ref,
            "symbol": validation_input.symbol,
            "market": validation_input.market,
            "strategy_id": validation_input.strategy_id,
            "client_order_id": validation_input.client_order_id,
            "side": validation_input.side,
            "order_type": validation_input.order_type,
            "quantity": validation_input.quantity,
        }
        missing_fields = tuple(
            field_name
            for field_name, field_value in required_values.items()
            if field_value in (None, "")
        )
        if missing_fields:
            return RuleOutcome(
                code="compliance_missing_required_field",
                passed=False,
                details={"missing_fields": missing_fields},
            )
        return RuleOutcome(
            code="compliance_required_fields_ok",
            passed=True,
        )

    def _order_shape_rule(_context: ValidationContext) -> RuleOutcome:
        order_type = (validation_input.order_type or "").strip().lower()
        side = (validation_input.side or "").strip().lower()
        quantity = validation_input.quantity
        price = validation_input.price

        if side and side not in {OrderSide.BUY.value, OrderSide.SELL.value}:
            return RuleOutcome(
                code="compliance_invalid_order_shape",
                passed=False,
                details={"reason": "invalid_side", "side": side},
            )
        if quantity in (None, "", "0", "0.0", "0.000000"):
            return RuleOutcome(
                code="compliance_invalid_order_shape",
                passed=False,
                details={"reason": "non_positive_quantity", "quantity": quantity},
            )
        if order_type == OrderType.LIMIT.value and price in (None, ""):
            return RuleOutcome(
                code="compliance_invalid_order_shape",
                passed=False,
                details={"reason": "limit_without_price"},
            )
        return RuleOutcome(
            code="compliance_order_shape_ok",
            passed=True,
        )

    def _instrument_status_rule(_context: ValidationContext) -> RuleOutcome:
        if allow_sell_override:
            return RuleOutcome(
                code="compliance_instrument_status_sell_override_allowed",
                passed=True,
            )
        if _normalized_flag(validation_input.tr_stop_yn) == "Y":
            return RuleOutcome(
                code="compliance_instrument_status_blocked",
                passed=False,
                details={
                    "reason": "trading_halt",
                    "status_source_type": validation_input.status_source_type,
                    "status_snapshot_at": (
                        validation_input.status_snapshot_at.isoformat()
                        if validation_input.status_snapshot_at is not None
                        else None
                    ),
                    "status_reason_codes": validation_input.status_reason_codes,
                },
            )
        if _normalized_flag(validation_input.admn_item_yn) == "Y":
            return RuleOutcome(
                code="compliance_instrument_status_blocked",
                passed=False,
                details={
                    "reason": "administrative_issue",
                    "status_source_type": validation_input.status_source_type,
                    "status_snapshot_at": (
                        validation_input.status_snapshot_at.isoformat()
                        if validation_input.status_snapshot_at is not None
                        else None
                    ),
                    "status_reason_codes": validation_input.status_reason_codes,
                },
            )
        if _normalized_flag(validation_input.nxt_tr_stop_yn) == "Y":
            return RuleOutcome(
                code="compliance_instrument_status_blocked",
                passed=False,
                details={
                    "reason": "next_session_halt",
                    "status_source_type": validation_input.status_source_type,
                    "status_snapshot_at": (
                        validation_input.status_snapshot_at.isoformat()
                        if validation_input.status_snapshot_at is not None
                        else None
                    ),
                    "status_reason_codes": validation_input.status_reason_codes,
                },
            )
        if _normalized_flag(validation_input.temp_stop_yn) == "Y":
            return RuleOutcome(
                code="compliance_instrument_status_blocked",
                passed=False,
                details={
                    "reason": "temporary_halt",
                    "status_source_type": validation_input.status_source_type,
                    "status_snapshot_at": (
                        validation_input.status_snapshot_at.isoformat()
                        if validation_input.status_snapshot_at is not None
                        else None
                    ),
                    "status_reason_codes": validation_input.status_reason_codes,
                },
            )
        status_code = str(validation_input.iscd_stat_cls_code or "").strip()
        if status_code and status_code in _STATUS_BLOCK_CODES:
            return RuleOutcome(
                code="compliance_instrument_status_blocked",
                passed=False,
                details={
                    "reason": f"suspended_status:{status_code}",
                    "status_source_type": validation_input.status_source_type,
                    "status_snapshot_at": (
                        validation_input.status_snapshot_at.isoformat()
                        if validation_input.status_snapshot_at is not None
                        else None
                    ),
                    "status_reason_codes": validation_input.status_reason_codes,
                },
            )
        if has_status_snapshot:
            return RuleOutcome(
                code="compliance_instrument_status_allowed",
                passed=True,
                details={
                    "status_source_type": validation_input.status_source_type,
                },
            )
        return RuleOutcome(
            code="compliance_status_snapshot_unavailable",
            passed=True,
        )

    def _holding_profile_window_rule(_context: ValidationContext) -> RuleOutcome:
        side = (validation_input.side or "").strip().lower()
        now_utc = datetime.now(timezone.utc)
        if (
            side == OrderSide.SELL.value
            and validation_input.has_position
            and validation_input.earliest_reduce_at is not None
            and validation_input.earliest_reduce_at > now_utc
        ):
            return RuleOutcome(
                code="compliance_holding_profile_window_blocked",
                passed=False,
                details={
                    "reason": "earliest_reduce_at_active",
                    "holding_profile": validation_input.holding_profile,
                    "earliest_reduce_at": validation_input.earliest_reduce_at.isoformat(),
                },
            )
        if (
            side == OrderSide.BUY.value
            and validation_input.intent_action == "new_buy"
            and validation_input.earliest_reentry_at is not None
            and validation_input.earliest_reentry_at > now_utc
        ):
            return RuleOutcome(
                code="compliance_holding_profile_window_blocked",
                passed=False,
                details={
                    "reason": "earliest_reentry_at_active",
                    "holding_profile": validation_input.holding_profile,
                    "earliest_reentry_at": validation_input.earliest_reentry_at.isoformat(),
                },
            )
        return RuleOutcome(
            code="compliance_holding_profile_window_allowed",
            passed=True,
        )

    def _restricted_symbol_rule(_context: ValidationContext) -> RuleOutcome:
        if validation_input.blocked_reason_codes:
            return RuleOutcome(
                code="compliance_restricted_symbol_fallback",
                passed=False,
                details={
                    "blocked_reason_codes": validation_input.blocked_reason_codes,
                },
            )
        return RuleOutcome(
            code="compliance_symbol_allowed",
            passed=True,
        )

    def _broker_capability_rule(_context: ValidationContext) -> RuleOutcome:
        order_type = (validation_input.order_type or "").strip().lower()
        supported_order_types = tuple(
            value.strip().lower()
            for value in validation_input.supported_order_types
            if value is not None and str(value).strip()
        )
        if order_type and supported_order_types and order_type not in supported_order_types:
            return RuleOutcome(
                code="compliance_broker_capability_blocked",
                passed=False,
                details={
                    "order_type": order_type,
                    "supported_order_types": supported_order_types,
                },
            )
        return RuleOutcome(
            code="compliance_broker_capability_allowed",
            passed=True,
        )

    result = run_validation_rules(
        rule_set_version="compliance_validator_v1",
        context=context,
        rules=(
            ValidationRule(
                name="source_policy_buy_blocked",
                evaluator=_source_policy_buy_rule,
            ),
            ValidationRule(
                name="reconciliation_overlay_flat_buy_blocked",
                evaluator=_reconciliation_overlay_flat_buy_rule,
            ),
            ValidationRule(
                name="required_fields",
                evaluator=_required_field_rule,
            ),
            ValidationRule(
                name="order_shape",
                evaluator=_order_shape_rule,
            ),
            ValidationRule(
                name="holding_profile_window",
                evaluator=_holding_profile_window_rule,
            ),
            ValidationRule(
                name="instrument_status",
                evaluator=_instrument_status_rule,
            ),
            ValidationRule(
                name="restricted_symbol",
                evaluator=_restricted_symbol_rule,
            ),
            ValidationRule(
                name="broker_capability",
                evaluator=_broker_capability_rule,
            ),
        ),
    )
    enriched_rule_results = dict(result.rule_results)
    enriched_rule_results.setdefault("validator_bundle", "compliance_validator_v1")
    if result.is_blocking:
        return ValidationResult.blocked(
            rule_set_version=result.rule_set_version,
            blocking_rule_codes=list(result.blocking_rule_codes),
            rule_results=enriched_rule_results,
            stop_reason=result.stop_reason,
            message=result.message,
        )
    return ValidationResult.allowed(
        rule_set_version=result.rule_set_version,
        rule_results=enriched_rule_results,
        warning_rule_codes=list(result.warning_rule_codes),
        message=result.message,
    )
