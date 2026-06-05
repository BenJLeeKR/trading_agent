#!/usr/bin/env python3
"""KIS live-info read-only smoke / preflight.

실주문 없이 다음 항목만 검증한다.

- live-info credential 존재 여부
- live quote client 생성 가능 여부
- access token 발급
- approval key 발급
- 현재가 quote 1건 조회

실거래 submit/cancel/amend는 호출하지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

from agent_trading.config.settings import AppSettings
from agent_trading.runtime.bootstrap import _build_kis_live_quote_client


@dataclass(slots=True, frozen=True)
class LiveReadonlySmokeResult:
    overall_status: str
    checked_at: str
    symbol: str
    kis_env: str
    live_info_credentials_present: bool
    live_quote_client_built: bool
    auth_ok: bool
    approval_ok: bool
    quote_ok: bool
    budget_snapshot: dict[str, Any] | None
    message: str
    quote_last_price: str | None = None
    error: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def to_text(self) -> str:
        lines = [
            "=== KIS Live Read-only Smoke ===",
            f"status: {self.overall_status}",
            f"checked_at: {self.checked_at}",
            f"symbol: {self.symbol}",
            f"kis_env: {self.kis_env}",
            f"live_info_credentials_present: {self.live_info_credentials_present}",
            f"live_quote_client_built: {self.live_quote_client_built}",
            f"auth_ok: {self.auth_ok}",
            f"approval_ok: {self.approval_ok}",
            f"quote_ok: {self.quote_ok}",
            f"quote_last_price: {self.quote_last_price or 'N/A'}",
            f"message: {self.message}",
        ]
        if self.error:
            lines.append(f"error: {self.error}")
        return "\n".join(lines)


async def evaluate_live_readonly_smoke(symbol: str) -> LiveReadonlySmokeResult:
    settings = AppSettings()
    checked_at = datetime.now(timezone.utc).isoformat()
    creds_present = bool(settings.kis_live_app_key and settings.kis_live_app_secret)
    if not creds_present:
        return LiveReadonlySmokeResult(
            overall_status="BLOCKED",
            checked_at=checked_at,
            symbol=symbol,
            kis_env=settings.kis_env,
            live_info_credentials_present=False,
            live_quote_client_built=False,
            auth_ok=False,
            approval_ok=False,
            quote_ok=False,
            budget_snapshot=None,
            message="KIS_LIVE_INFO_APP_KEY / KIS_LIVE_INFO_APP_SECRET 가 없어 live read-only smoke를 실행할 수 없습니다.",
        )

    client = _build_kis_live_quote_client(settings)
    if client is None:
        return LiveReadonlySmokeResult(
            overall_status="BLOCKED",
            checked_at=checked_at,
            symbol=symbol,
            kis_env=settings.kis_env,
            live_info_credentials_present=True,
            live_quote_client_built=False,
            auth_ok=False,
            approval_ok=False,
            quote_ok=False,
            budget_snapshot=None,
            message="live quote client 생성에 실패했습니다.",
        )

    try:
        await client.authenticate()
        approval = await client.get_approval_key()
        quote = await client.get_quote(symbol)
        last_price = quote.get("stck_prpr") or quote.get("last") or quote.get("stck_clpr")
        quote_ok = bool(quote)
        return LiveReadonlySmokeResult(
            overall_status="READY" if quote_ok else "WARN",
            checked_at=checked_at,
            symbol=symbol,
            kis_env=settings.kis_env,
            live_info_credentials_present=True,
            live_quote_client_built=True,
            auth_ok=True,
            approval_ok=bool(approval),
            quote_ok=quote_ok,
            budget_snapshot=client.budget_manager.snapshot() if client.budget_manager is not None else None,
            quote_last_price=str(last_price) if last_price is not None else None,
            message="live read-only smoke가 완료되었습니다." if quote_ok else "quote 응답은 받았지만 가격 필드가 비어 있습니다.",
        )
    except Exception as exc:
        return LiveReadonlySmokeResult(
            overall_status="BLOCKED",
            checked_at=checked_at,
            symbol=symbol,
            kis_env=settings.kis_env,
            live_info_credentials_present=True,
            live_quote_client_built=True,
            auth_ok=False,
            approval_ok=False,
            quote_ok=False,
            budget_snapshot=client.budget_manager.snapshot() if client.budget_manager is not None else None,
            message="live read-only smoke 실행 중 오류가 발생했습니다.",
            error=str(exc),
        )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="KIS live read-only smoke")
    parser.add_argument("--symbol", default="005930", help="Quote symbol to verify (default: 005930)")
    parser.add_argument("--output", choices=("text", "json"), default="text")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if load_dotenv is not None:
        load_dotenv()
    args = _parse_args(argv)
    result = asyncio.run(evaluate_live_readonly_smoke(args.symbol))
    print(result.to_json() if args.output == "json" else result.to_text())
    return 0 if result.overall_status == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
