#!/usr/bin/env python3
"""KIS live submit-path preflight (read-only).

실주문 없이 다음 항목만 검증한다.

- ``KIS_ENV=live`` 설정 여부
- live 주문 credential / 계좌번호 설정 여부
- primary trading client 생성 가능 여부
- access token 발급
- approval key 발급
- live 계좌 cash/positions 조회 가능 여부
- live 계좌 orderable cash 조회 가능 여부

submit/cancel/amend 는 호출하지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

from agent_trading.config.settings import AppSettings
from agent_trading.runtime.bootstrap import _build_kis_adapter


@dataclass(slots=True, frozen=True)
class LiveSubmitPreflightResult:
    overall_status: str
    checked_at: str
    kis_env: str
    trading_credentials_present: bool
    account_config_present: bool
    trading_client_built: bool
    auth_ok: bool
    approval_ok: bool
    cash_positions_ok: bool
    orderable_cash_ok: bool
    orderable_cash_source: str | None
    orderable_cash_amount: str | None
    positions_count: int | None
    settlement_amount: str | None
    budget_snapshot: dict | None
    message: str
    error: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def to_text(self) -> str:
        lines = [
            "=== KIS Live Submit Preflight ===",
            f"status: {self.overall_status}",
            f"checked_at: {self.checked_at}",
            f"kis_env: {self.kis_env}",
            f"trading_credentials_present: {self.trading_credentials_present}",
            f"account_config_present: {self.account_config_present}",
            f"trading_client_built: {self.trading_client_built}",
            f"auth_ok: {self.auth_ok}",
            f"approval_ok: {self.approval_ok}",
            f"cash_positions_ok: {self.cash_positions_ok}",
            f"orderable_cash_ok: {self.orderable_cash_ok}",
            f"orderable_cash_source: {self.orderable_cash_source or 'N/A'}",
            f"orderable_cash_amount: {self.orderable_cash_amount or 'N/A'}",
            f"positions_count: {self.positions_count if self.positions_count is not None else 'N/A'}",
            f"settlement_amount: {self.settlement_amount or 'N/A'}",
            f"message: {self.message}",
        ]
        if self.error:
            lines.append(f"error: {self.error}")
        return "\n".join(lines)


async def evaluate_live_submit_preflight(*, symbol: str, price: str) -> LiveSubmitPreflightResult:
    settings = AppSettings()
    checked_at = datetime.now(timezone.utc).isoformat()
    trading_creds_present = bool(settings.kis_api_key and settings.kis_api_secret)
    account_config_present = bool(settings.kis_account_number and settings.kis_account_product_code)

    if settings.kis_env != "live":
        return LiveSubmitPreflightResult(
            overall_status="BLOCKED",
            checked_at=checked_at,
            kis_env=settings.kis_env,
            trading_credentials_present=trading_creds_present,
            account_config_present=account_config_present,
            trading_client_built=False,
            auth_ok=False,
            approval_ok=False,
            cash_positions_ok=False,
            orderable_cash_ok=False,
            orderable_cash_source=None,
            orderable_cash_amount=None,
            positions_count=None,
            settlement_amount=None,
            budget_snapshot=None,
            message="KIS_ENV=live 가 아니므로 live submit preflight를 진행할 수 없습니다.",
        )

    if not trading_creds_present or not account_config_present:
        return LiveSubmitPreflightResult(
            overall_status="BLOCKED",
            checked_at=checked_at,
            kis_env=settings.kis_env,
            trading_credentials_present=trading_creds_present,
            account_config_present=account_config_present,
            trading_client_built=False,
            auth_ok=False,
            approval_ok=False,
            cash_positions_ok=False,
            orderable_cash_ok=False,
            orderable_cash_source=None,
            orderable_cash_amount=None,
            positions_count=None,
            settlement_amount=None,
            budget_snapshot=None,
            message="live 주문 credential 또는 계좌 설정이 부족합니다.",
        )

    adapter = _build_kis_adapter(settings)
    client = getattr(adapter, "_rest", None)
    if client is None:
        return LiveSubmitPreflightResult(
            overall_status="BLOCKED",
            checked_at=checked_at,
            kis_env=settings.kis_env,
            trading_credentials_present=True,
            account_config_present=True,
            trading_client_built=False,
            auth_ok=False,
            approval_ok=False,
            cash_positions_ok=False,
            orderable_cash_ok=False,
            orderable_cash_source=None,
            orderable_cash_amount=None,
            positions_count=None,
            settlement_amount=None,
            budget_snapshot=None,
            message="primary trading client 생성에 실패했습니다.",
        )

    try:
        await client.authenticate()
        approval = await client.get_approval_key()
        cp_result = await client.get_cash_and_positions(after_hours=False)
        orderable_result = await client.get_orderable_cash_result(
            account_ref=settings.kis_account_number,
            symbol=symbol,
            price=price,
            order_type="00",
            fallback_cash=None,
        )
        cash_balance = cp_result.cash_balance or {}
        settlement_amount = cash_balance.get("dnca_tot_amt")
        positions_count = len(cp_result.positions)
        orderable_ok = orderable_result.amount is not None
        overall_status = "READY" if orderable_ok else "WARN"
        message = (
            "live submit preflight가 완료되었습니다."
            if orderable_ok
            else "orderable cash 응답이 비어 있습니다. submit 전 추가 확인이 필요합니다."
        )
        return LiveSubmitPreflightResult(
            overall_status=overall_status,
            checked_at=checked_at,
            kis_env=settings.kis_env,
            trading_credentials_present=True,
            account_config_present=True,
            trading_client_built=True,
            auth_ok=True,
            approval_ok=bool(approval),
            cash_positions_ok=bool(cp_result.cash_balance is not None),
            orderable_cash_ok=orderable_ok,
            orderable_cash_source=orderable_result.source,
            orderable_cash_amount=str(orderable_result.amount) if orderable_result.amount is not None else None,
            positions_count=positions_count,
            settlement_amount=str(settlement_amount) if settlement_amount is not None else None,
            budget_snapshot=client.budget_manager.snapshot() if client.budget_manager is not None else None,
            message=message,
        )
    except Exception as exc:
        return LiveSubmitPreflightResult(
            overall_status="BLOCKED",
            checked_at=checked_at,
            kis_env=settings.kis_env,
            trading_credentials_present=True,
            account_config_present=True,
            trading_client_built=True,
            auth_ok=False,
            approval_ok=False,
            cash_positions_ok=False,
            orderable_cash_ok=False,
            orderable_cash_source=None,
            orderable_cash_amount=None,
            positions_count=None,
            settlement_amount=None,
            budget_snapshot=client.budget_manager.snapshot() if client.budget_manager is not None else None,
            message="live submit preflight 실행 중 오류가 발생했습니다.",
            error=str(exc),
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="KIS live submit preflight")
    parser.add_argument("--symbol", default="005930", help="Orderable cash probe symbol (default: 005930)")
    parser.add_argument("--price", default="1", help="Orderable cash probe price (default: 1)")
    parser.add_argument("--output", choices=("text", "json"), default="text")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if load_dotenv is not None:
        load_dotenv()
    args = _parse_args(argv)
    result = asyncio.run(evaluate_live_submit_preflight(symbol=args.symbol, price=args.price))
    print(result.to_json() if args.output == "json" else result.to_text())
    return 0 if result.overall_status == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
