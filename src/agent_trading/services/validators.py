from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

from agent_trading.domain.entities import GuardrailEvaluationEntity


@dataclass(slots=True, frozen=True)
class ValidationContext:
    """공통 validator 평가 컨텍스트.

    1차 단계에서는 guardrail 기록에 필요한 식별자와 최소 메타데이터만 담는다.
    이후 risk/compliance/execution validator bundle로 확장할 때
    같은 구조를 재사용한다.
    """

    decision_context_id: UUID | None = None
    trade_decision_id: UUID | None = None
    order_request_id: UUID | None = None
    account_id: UUID | None = None
    symbol: str | None = None
    market: str | None = None
    side: str | None = None
    source_type: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ValidationResult:
    """공통 validator 평가 결과.

    현재는 hard block 기록 공통화가 목적이므로
    pass/warn/block 결과를 모두 표현할 수 있는 최소 계약으로 둔다.
    """

    rule_set_version: str
    overall_passed: bool
    blocking_rule_codes: tuple[str, ...] = ()
    warning_rule_codes: tuple[str, ...] = ()
    rule_results: dict[str, object] = field(default_factory=dict)
    stop_reason: str | None = None
    message: str | None = None
    evaluated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def is_blocking(self) -> bool:
        return (not self.overall_passed) and bool(self.blocking_rule_codes)

    @classmethod
    def blocked(
        cls,
        *,
        rule_set_version: str,
        blocking_rule_codes: list[str] | tuple[str, ...],
        rule_results: dict[str, object] | None = None,
        stop_reason: str | None = None,
        message: str | None = None,
    ) -> ValidationResult:
        return cls(
            rule_set_version=rule_set_version,
            overall_passed=False,
            blocking_rule_codes=tuple(blocking_rule_codes),
            rule_results=dict(rule_results or {}),
            stop_reason=stop_reason,
            message=message,
        )

    @classmethod
    def allowed(
        cls,
        *,
        rule_set_version: str,
        rule_results: dict[str, object] | None = None,
        warning_rule_codes: list[str] | tuple[str, ...] = (),
        message: str | None = None,
    ) -> ValidationResult:
        return cls(
            rule_set_version=rule_set_version,
            overall_passed=True,
            warning_rule_codes=tuple(warning_rule_codes),
            rule_results=dict(rule_results or {}),
            message=message,
        )

    def to_guardrail_evaluation(
        self,
        *,
        context: ValidationContext,
    ) -> GuardrailEvaluationEntity:
        merged_rule_results = dict(self.rule_results)
        if context.account_id is not None:
            merged_rule_results.setdefault("account_id", str(context.account_id))
        if context.symbol is not None:
            merged_rule_results.setdefault("symbol", context.symbol)
        if context.market is not None:
            merged_rule_results.setdefault("market", context.market)
        if context.side is not None:
            merged_rule_results.setdefault("side", context.side)
        if context.source_type is not None:
            merged_rule_results.setdefault("source_type", context.source_type)
        if context.metadata:
            merged_rule_results.setdefault("context_metadata", dict(context.metadata))

        return GuardrailEvaluationEntity(
            guardrail_evaluation_id=uuid4(),
            decision_context_id=context.decision_context_id,
            trade_decision_id=context.trade_decision_id,
            order_request_id=context.order_request_id,
            rule_set_version=self.rule_set_version,
            overall_passed=self.overall_passed,
            evaluated_at=self.evaluated_at,
            rule_results=merged_rule_results,
            blocking_rule_codes=list(self.blocking_rule_codes) or None,
            warning_rule_codes=list(self.warning_rule_codes) or None,
        )


@dataclass(slots=True, frozen=True)
class RuleOutcome:
    """개별 validation rule의 평가 결과."""

    code: str
    passed: bool
    details: dict[str, object] = field(default_factory=dict)
    message: str | None = None
    warning: bool = False


@dataclass(slots=True, frozen=True)
class ValidationRule:
    """공통 validation rule 계약."""

    name: str
    evaluator: Callable[[ValidationContext], RuleOutcome]


def _coerce_uuid(value: object | None) -> UUID | None:
    if value is None or isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _coerce_optional_str(value: object | None) -> str | None:
    if value is None:
        return None
    return str(value)


def build_validation_context(
    *,
    decision_context_id: object | None = None,
    trade_decision_id: object | None = None,
    order_request_id: object | None = None,
    account_id: object | None = None,
    symbol: object | None = None,
    market: object | None = None,
    side: object | None = None,
    source_type: object | None = None,
    metadata: dict[str, object] | None = None,
    rule_results: dict[str, object] | None = None,
) -> ValidationContext:
    """여러 서비스에서 공통으로 쓰는 ValidationContext 조립 helper."""

    raw_rule_results = rule_results or {}
    return ValidationContext(
        decision_context_id=_coerce_uuid(decision_context_id),
        trade_decision_id=_coerce_uuid(trade_decision_id),
        order_request_id=_coerce_uuid(order_request_id),
        account_id=_coerce_uuid(account_id or raw_rule_results.get("account_id")),
        symbol=_coerce_optional_str(symbol or raw_rule_results.get("symbol")),
        market=_coerce_optional_str(market or raw_rule_results.get("market")),
        side=_coerce_optional_str(side or raw_rule_results.get("side")),
        source_type=_coerce_optional_str(
            source_type or raw_rule_results.get("source_type")
        ),
        metadata=dict(metadata or {}),
    )


def run_validation_rules(
    *,
    rule_set_version: str,
    context: ValidationContext,
    rules: tuple[ValidationRule, ...] | list[ValidationRule],
) -> ValidationResult:
    """공통 validation rule bundle 실행기.

    현재 단계에서는 첫 blocking code를 stop_reason으로 채택하고,
    각 rule의 세부 결과는 ``rule_outcomes``에 남긴다.
    """

    blocking_rule_codes: list[str] = []
    warning_rule_codes: list[str] = []
    rule_outcomes: dict[str, object] = {}
    first_message: str | None = None

    for rule in rules:
        outcome = rule.evaluator(context)
        rule_outcomes[rule.name] = {
            "code": outcome.code,
            "passed": outcome.passed,
            "details": dict(outcome.details),
            "message": outcome.message,
            "warning": outcome.warning,
        }
        if outcome.message is not None and first_message is None:
            first_message = outcome.message
        if not outcome.passed:
            if outcome.warning:
                warning_rule_codes.append(outcome.code)
            else:
                blocking_rule_codes.append(outcome.code)

    if blocking_rule_codes:
        return ValidationResult.blocked(
            rule_set_version=rule_set_version,
            blocking_rule_codes=blocking_rule_codes,
            rule_results={
                "rule_outcomes": rule_outcomes,
                "context_metadata": dict(context.metadata),
            },
            stop_reason=blocking_rule_codes[0],
            message=first_message,
        )

    return ValidationResult.allowed(
        rule_set_version=rule_set_version,
        rule_results={
            "rule_outcomes": rule_outcomes,
            "context_metadata": dict(context.metadata),
        },
        warning_rule_codes=warning_rule_codes,
        message=first_message,
    )
