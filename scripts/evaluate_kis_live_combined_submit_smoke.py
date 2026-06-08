#!/usr/bin/env python3
"""KIS live combined submit smoke with explicit opt-in.

기본 동작은 read-only preflight + request validation까지만 수행한다.
실제 live submit은 명시적 실행 플래그와 확인 문구가 모두 있어야만 진행한다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

from agent_trading.config.settings import AppSettings
from agent_trading.domain.enums import OrderSide, TimeInForce
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.runtime.bootstrap import _build_kis_adapter

try:  # pragma: no cover - import path differs between script execution and test import
    from scripts.evaluate_kis_live_submit_preflight import evaluate_live_submit_preflight
except ModuleNotFoundError:  # pragma: no cover
    from evaluate_kis_live_submit_preflight import evaluate_live_submit_preflight

_EXECUTE_CONFIRM_PHRASE = "SUBMIT_REAL_ORDER"


@dataclass(slots=True, frozen=True)
class LiveCombinedSubmitSmokeResult:
    overall_status: str
    checked_at: str
    kis_env: str
    mode: str
    preflight_status: str
    request_validation_ok: bool
    validation_errors: list[str]
    execution_enabled: bool
    submitted: bool
    broker_order_id: str | None
    message: str
    error: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def to_text(self) -> str:
        lines = [
            "=== KIS Live Combined Submit Smoke ===",
            f"status: {self.overall_status}",
            f"checked_at: {self.checked_at}",
            f"kis_env: {self.kis_env}",
            f"mode: {self.mode}",
            f"preflight_status: {self.preflight_status}",
            f"request_validation_ok: {self.request_validation_ok}",
            f"execution_enabled: {self.execution_enabled}",
            f"submitted: {self.submitted}",
            f"broker_order_id: {self.broker_order_id or 'N/A'}",
            f"message: {self.message}",
        ]
        if self.validation_errors:
            lines.append(f"validation_errors: {self.validation_errors}")
        if self.error:
            lines.append(f"error: {self.error}")
        return "\n".join(lines)


def _build_sample_request(*, symbol: str, quantity: Decimal, price: Decimal) -> SubmitOrderRequest:
    return SubmitOrderRequest(
        client_order_id=f"live-smoke-{uuid4()}",
        correlation_id=f"live-smoke-{uuid4()}",
        account_ref="live-smoke",
        strategy_id="live-smoke-strategy",
        symbol=symbol,
        market="KRX",
        side=OrderSide.BUY,
        order_type="limit",
        time_in_force=TimeInForce.DAY,
        quantity=quantity,
        price=price,
        idempotency_key=f"live-smoke-{uuid4()}",
    )


async def evaluate_live_combined_submit_smoke(
    *,
    symbol: str,
    quantity: Decimal,
    price: Decimal,
    execute_live_order: bool,
    confirmation_phrase: str,
) -> LiveCombinedSubmitSmokeResult:
    checked_at = datetime.now(timezone.utc).isoformat()
    settings = AppSettings()

    preflight = await evaluate_live_submit_preflight(symbol=symbol, price=str(price))
    if preflight.overall_status != "READY":
        return LiveCombinedSubmitSmokeResult(
            overall_status="BLOCKED",
            checked_at=checked_at,
            kis_env=settings.kis_env,
            mode="execute" if execute_live_order else "dry_run",
            preflight_status=preflight.overall_status,
            request_validation_ok=False,
            validation_errors=[],
            execution_enabled=False,
            submitted=False,
            broker_order_id=None,
            message="live submit preflight가 READY가 아니므로 combined submit smoke를 중단합니다.",
        )

    adapter = _build_kis_adapter(settings)
    request = _build_sample_request(symbol=symbol, quantity=quantity, price=price)
    validation_errors = adapter._validate_order_request(request)  # noqa: SLF001
    if validation_errors:
        return LiveCombinedSubmitSmokeResult(
            overall_status="BLOCKED",
            checked_at=checked_at,
            kis_env=settings.kis_env,
            mode="execute" if execute_live_order else "dry_run",
            preflight_status=preflight.overall_status,
            request_validation_ok=False,
            validation_errors=validation_errors,
            execution_enabled=False,
            submitted=False,
            broker_order_id=None,
            message="live submit request validation에 실패했습니다.",
        )

    if not execute_live_order:
        return LiveCombinedSubmitSmokeResult(
            overall_status="READY",
            checked_at=checked_at,
            kis_env=settings.kis_env,
            mode="dry_run",
            preflight_status=preflight.overall_status,
            request_validation_ok=True,
            validation_errors=[],
            execution_enabled=False,
            submitted=False,
            broker_order_id=None,
            message="preflight + request validation 완료. 실제 live submit은 --execute-live-order 와 확인 문구가 있어야 진행됩니다.",
        )

    if confirmation_phrase != _EXECUTE_CONFIRM_PHRASE:
        return LiveCombinedSubmitSmokeResult(
            overall_status="BLOCKED",
            checked_at=checked_at,
            kis_env=settings.kis_env,
            mode="execute",
            preflight_status=preflight.overall_status,
            request_validation_ok=True,
            validation_errors=[],
            execution_enabled=False,
            submitted=False,
            broker_order_id=None,
            message="실제 live submit은 확인 문구가 일치할 때만 진행됩니다.",
        )

    try:
        result = await adapter.submit_order(request)
        return LiveCombinedSubmitSmokeResult(
            overall_status="EXECUTED",
            checked_at=checked_at,
            kis_env=settings.kis_env,
            mode="execute",
            preflight_status=preflight.overall_status,
            request_validation_ok=True,
            validation_errors=[],
            execution_enabled=True,
            submitted=True,
            broker_order_id=result.broker_order_id,
            message="live combined submit smoke가 실제 submit까지 완료되었습니다.",
        )
    except Exception as exc:
        return LiveCombinedSubmitSmokeResult(
            overall_status="BLOCKED",
            checked_at=checked_at,
            kis_env=settings.kis_env,
            mode="execute",
            preflight_status=preflight.overall_status,
            request_validation_ok=True,
            validation_errors=[],
            execution_enabled=True,
            submitted=False,
            broker_order_id=None,
            message="live combined submit smoke 실제 submit 단계에서 오류가 발생했습니다.",
            error=str(exc),
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="KIS live combined submit smoke")
    parser.add_argument("--symbol", default="005930")
    parser.add_argument("--quantity", default="1")
    parser.add_argument("--price", default="1")
    parser.add_argument("--execute-live-order", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--output", choices=("text", "json"), default="text")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if load_dotenv is not None:
        load_dotenv()
    args = _parse_args(argv)
    result = asyncio.run(
        evaluate_live_combined_submit_smoke(
            symbol=args.symbol,
            quantity=Decimal(args.quantity),
            price=Decimal(args.price),
            execute_live_order=args.execute_live_order,
            confirmation_phrase=args.confirm,
        ),
    )
    print(result.to_json() if args.output == "json" else result.to_text())
    return 0 if result.overall_status in {"READY", "EXECUTED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
