#!/usr/bin/env python3
"""KIS live/paper budget isolation read-only smoke.

실주문 없이 다음 항목만 검증한다.

- paper trading client / live quote client 동시 생성 가능 여부
- paper global budget 이 process-shared(file-backed) 인지
- live global budget 이 paper shared budget 과 분리돼 있는지
- live quote 1건 호출 후 paper budget 이 감소하지 않는지
- paper truth query(VTTC0081R) 1건 호출 후 live budget 이 감소하지 않는지

submit/cancel/amend 는 호출하지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

from agent_trading.brokers.rate_limit import BudgetExhaustedError
from agent_trading.config.settings import AppSettings
from agent_trading.runtime.bootstrap import _build_kis_adapter, _build_kis_live_quote_client


def _global_bucket_meta(client: Any) -> dict[str, Any] | None:
    mgr = getattr(client, "budget_manager", None)
    if mgr is None or getattr(mgr, "global_rest", None) is None:
        return None
    bucket = mgr.global_rest
    file_path = getattr(bucket, "_FILE_PATH", None)
    return {
        "manager_class": type(mgr).__name__,
        "global_bucket_class": type(bucket).__name__,
        "shared_file_path": file_path,
        "session_id": str(getattr(mgr, "session_id", "")),
    }


def _global_remaining(snapshot: dict[str, Any] | None) -> int | None:
    if not snapshot:
        return None
    global_bucket = snapshot.get("global")
    if not isinstance(global_bucket, dict):
        return None
    remaining = global_bucket.get("remaining")
    return int(remaining) if remaining is not None else None


async def _run_paper_truth_query(client: Any) -> int:
    """Run one read-only paper truth query (VTTC0081R family)."""
    if hasattr(client, "_wait_for_inquiry_budget"):
        await client._wait_for_inquiry_budget(timeout=3.0)  # noqa: SLF001
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst).strftime("%Y%m%d")
    rows = await client.inquire_daily_ccld(
        strt_dt=today,
        end_dt=today,
        after_hours=True,
    )
    return len(rows)


@dataclass(slots=True, frozen=True)
class BudgetIsolationSmokeResult:
    overall_status: str
    checked_at: str
    symbol: str
    kis_env: str
    paper_client_built: bool
    live_quote_client_built: bool
    paper_shared_global_budget: bool
    live_shared_global_budget: bool
    live_quote_ok: bool
    paper_truth_query_ok: bool
    isolation_ok: bool
    paper_only_policy_isolated: bool
    paper_rows_count: int | None
    paper_global_meta: dict[str, Any] | None
    live_global_meta: dict[str, Any] | None
    paper_budget_before: dict[str, Any] | None
    paper_budget_after_live: dict[str, Any] | None
    paper_budget_after_paper: dict[str, Any] | None
    live_budget_before: dict[str, Any] | None
    live_budget_after_live: dict[str, Any] | None
    live_budget_after_paper: dict[str, Any] | None
    message: str
    error: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    def to_text(self) -> str:
        lines = [
            "=== KIS Budget Isolation Smoke ===",
            f"status: {self.overall_status}",
            f"checked_at: {self.checked_at}",
            f"symbol: {self.symbol}",
            f"kis_env: {self.kis_env}",
            f"paper_client_built: {self.paper_client_built}",
            f"live_quote_client_built: {self.live_quote_client_built}",
            f"paper_shared_global_budget: {self.paper_shared_global_budget}",
            f"live_shared_global_budget: {self.live_shared_global_budget}",
            f"paper_only_policy_isolated: {self.paper_only_policy_isolated}",
            f"live_quote_ok: {self.live_quote_ok}",
            f"paper_truth_query_ok: {self.paper_truth_query_ok}",
            f"isolation_ok: {self.isolation_ok}",
            f"paper_rows_count: {self.paper_rows_count if self.paper_rows_count is not None else 'N/A'}",
            f"message: {self.message}",
        ]
        if self.error:
            lines.append(f"error: {self.error}")
        return "\n".join(lines)


async def evaluate_budget_isolation_smoke(symbol: str) -> BudgetIsolationSmokeResult:
    settings = AppSettings()
    checked_at = datetime.now(timezone.utc).isoformat()

    paper_adapter = _build_kis_adapter(settings)
    live_client = _build_kis_live_quote_client(settings)
    paper_client = getattr(paper_adapter, "_rest", None)

    if paper_client is None or live_client is None:
        return BudgetIsolationSmokeResult(
            overall_status="BLOCKED",
            checked_at=checked_at,
            symbol=symbol,
            kis_env=settings.kis_env,
            paper_client_built=paper_client is not None,
            live_quote_client_built=live_client is not None,
            paper_shared_global_budget=False,
            live_shared_global_budget=False,
            live_quote_ok=False,
            paper_truth_query_ok=False,
            isolation_ok=False,
            paper_only_policy_isolated=False,
            paper_rows_count=None,
            paper_global_meta=_global_bucket_meta(paper_client),
            live_global_meta=_global_bucket_meta(live_client),
            paper_budget_before=None,
            paper_budget_after_live=None,
            paper_budget_after_paper=None,
            live_budget_before=None,
            live_budget_after_live=None,
            live_budget_after_paper=None,
            message="paper trading client 또는 live quote client 생성에 실패했습니다.",
        )

    paper_meta = _global_bucket_meta(paper_client)
    live_meta = _global_bucket_meta(live_client)
    paper_shared = bool(paper_meta and paper_meta.get("global_bucket_class") == "FileBackedGlobalBucket")
    live_shared = bool(live_meta and live_meta.get("global_bucket_class") == "FileBackedGlobalBucket")
    paper_only_policy_isolated = paper_shared and not live_shared and getattr(live_client, "env", "") == "live"

    paper_budget_before = (
        paper_client.budget_manager.snapshot() if getattr(paper_client, "budget_manager", None) is not None else None
    )
    live_budget_before = (
        live_client.budget_manager.snapshot() if getattr(live_client, "budget_manager", None) is not None else None
    )

    try:
        await live_client.authenticate()
        await live_client.get_approval_key()
        await live_client.get_quote(symbol)
        live_quote_ok = True
    except Exception as exc:
        return BudgetIsolationSmokeResult(
            overall_status="BLOCKED",
            checked_at=checked_at,
            symbol=symbol,
            kis_env=settings.kis_env,
            paper_client_built=True,
            live_quote_client_built=True,
            paper_shared_global_budget=paper_shared,
            live_shared_global_budget=live_shared,
            live_quote_ok=False,
            paper_truth_query_ok=False,
            isolation_ok=False,
            paper_only_policy_isolated=paper_only_policy_isolated,
            paper_rows_count=None,
            paper_global_meta=paper_meta,
            live_global_meta=live_meta,
            paper_budget_before=paper_budget_before,
            paper_budget_after_live=None,
            paper_budget_after_paper=None,
            live_budget_before=live_budget_before,
            live_budget_after_live=None,
            live_budget_after_paper=None,
            message="live quote read-only smoke가 실패했습니다.",
            error=str(exc),
        )

    live_budget_after_live = (
        live_client.budget_manager.snapshot() if getattr(live_client, "budget_manager", None) is not None else None
    )
    paper_budget_after_live = (
        paper_client.budget_manager.snapshot() if getattr(paper_client, "budget_manager", None) is not None else None
    )

    try:
        paper_rows_count = await _run_paper_truth_query(paper_client)
        paper_truth_query_ok = True
    except BudgetExhaustedError as exc:
        return BudgetIsolationSmokeResult(
            overall_status="WARN",
            checked_at=checked_at,
            symbol=symbol,
            kis_env=settings.kis_env,
            paper_client_built=True,
            live_quote_client_built=True,
            paper_shared_global_budget=paper_shared,
            live_shared_global_budget=live_shared,
            live_quote_ok=True,
            paper_truth_query_ok=False,
            isolation_ok=False,
            paper_only_policy_isolated=paper_only_policy_isolated,
            paper_rows_count=None,
            paper_global_meta=paper_meta,
            live_global_meta=live_meta,
            paper_budget_before=paper_budget_before,
            paper_budget_after_live=paper_budget_after_live,
            paper_budget_after_paper=None,
            live_budget_before=live_budget_before,
            live_budget_after_live=live_budget_after_live,
            live_budget_after_paper=None,
            message="paper truth query가 budget exhaustion으로 완료되지 않았습니다.",
            error=str(exc),
        )
    except Exception as exc:
        return BudgetIsolationSmokeResult(
            overall_status="BLOCKED",
            checked_at=checked_at,
            symbol=symbol,
            kis_env=settings.kis_env,
            paper_client_built=True,
            live_quote_client_built=True,
            paper_shared_global_budget=paper_shared,
            live_shared_global_budget=live_shared,
            live_quote_ok=True,
            paper_truth_query_ok=False,
            isolation_ok=False,
            paper_only_policy_isolated=paper_only_policy_isolated,
            paper_rows_count=None,
            paper_global_meta=paper_meta,
            live_global_meta=live_meta,
            paper_budget_before=paper_budget_before,
            paper_budget_after_live=paper_budget_after_live,
            paper_budget_after_paper=None,
            live_budget_before=live_budget_before,
            live_budget_after_live=live_budget_after_live,
            live_budget_after_paper=None,
            message="paper truth query smoke가 실패했습니다.",
            error=str(exc),
        )

    paper_budget_after_paper = (
        paper_client.budget_manager.snapshot() if getattr(paper_client, "budget_manager", None) is not None else None
    )
    live_budget_after_paper = (
        live_client.budget_manager.snapshot() if getattr(live_client, "budget_manager", None) is not None else None
    )

    paper_before_remaining = _global_remaining(paper_budget_before)
    paper_after_live_remaining = _global_remaining(paper_budget_after_live)
    live_after_live_remaining = _global_remaining(live_budget_after_live)
    live_after_paper_remaining = _global_remaining(live_budget_after_paper)

    paper_not_drained_by_live = (
        paper_before_remaining is None
        or paper_after_live_remaining is None
        or paper_after_live_remaining >= paper_before_remaining
    )
    live_not_drained_by_paper = (
        live_after_live_remaining is None
        or live_after_paper_remaining is None
        or live_after_paper_remaining >= live_after_live_remaining
    )
    isolation_ok = paper_not_drained_by_live and live_not_drained_by_paper and paper_only_policy_isolated

    overall_status = "READY" if isolation_ok and paper_truth_query_ok and live_quote_ok else "WARN"
    return BudgetIsolationSmokeResult(
        overall_status=overall_status,
        checked_at=checked_at,
        symbol=symbol,
        kis_env=settings.kis_env,
        paper_client_built=True,
        live_quote_client_built=True,
        paper_shared_global_budget=paper_shared,
        live_shared_global_budget=live_shared,
        live_quote_ok=live_quote_ok,
        paper_truth_query_ok=paper_truth_query_ok,
        isolation_ok=isolation_ok,
        paper_only_policy_isolated=paper_only_policy_isolated,
        paper_rows_count=paper_rows_count,
        paper_global_meta=paper_meta,
        live_global_meta=live_meta,
        paper_budget_before=paper_budget_before,
        paper_budget_after_live=paper_budget_after_live,
        paper_budget_after_paper=paper_budget_after_paper,
        live_budget_before=live_budget_before,
        live_budget_after_live=live_budget_after_live,
        live_budget_after_paper=live_budget_after_paper,
        message=(
            "live quote와 paper truth query가 서로 다른 global budget 경로에서 실행되는 것을 확인했습니다."
            if isolation_ok
            else "budget isolation smoke가 경고 상태로 종료되었습니다."
        ),
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="KIS live/paper budget isolation smoke")
    parser.add_argument("--symbol", default="005930", help="Live quote symbol to verify (default: 005930)")
    parser.add_argument("--output", choices=("text", "json"), default="text")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if load_dotenv is not None:
        load_dotenv()
    args = _parse_args(argv)
    result = asyncio.run(evaluate_budget_isolation_smoke(args.symbol))
    print(result.to_json() if args.output == "json" else result.to_text())
    return 0 if result.overall_status == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
