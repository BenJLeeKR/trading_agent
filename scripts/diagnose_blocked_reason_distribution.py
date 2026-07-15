#!/usr/bin/env python3
"""보조 진단 — 새 alpha 상위군 중 '차단됨' 표본의 실제 eligibility 실패
사유 분포 확인 (read-only, validate_new_alpha_vs_existing_blocking_axes.py
결과 해석 보강용)."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("diagnose_blocked_reason_distribution")

import sys as _sys  # noqa: E402

_sys.path.insert(0, "scripts")
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    _build_benchmark_daily_series,
    _fetch_extended_bars,
)
from validate_new_alpha_vs_existing_blocking_axes import (  # noqa: E402
    RECENT_WINDOW_CALENDAR_DAYS,
    TOP_QUINTILE_FRACTION,
    _collect_symbol_rows,
    _top_quintile_rows,
)


async def main() -> None:
    from agent_trading.config.settings import AppSettings
    from agent_trading.runtime.bootstrap import _build_kis_live_quote_client
    from agent_trading.services.core_universe_seed import APPROVED_CORE_UNIVERSE_SYMBOLS

    settings = AppSettings()
    client = _build_kis_live_quote_client(settings)
    if client is None:
        raise SystemExit("KIS live quote client 생성 실패")

    bench_bars = await _fetch_extended_bars(client, BENCHMARK_SYMBOL)
    market_common_regime_by_date, _ = _build_benchmark_daily_series(bench_bars)

    symbols = sorted(APPROVED_CORE_UNIVERSE_SYMBOLS - {BENCHMARK_SYMBOL})
    all_rows = []
    for symbol in symbols:
        bars = await _fetch_extended_bars(client, symbol)
        if len(bars) < 61 + 20 + 5:
            continue
        all_rows.extend(_collect_symbol_rows(symbol, bars, market_common_regime_by_date))

    last_date = max(datetime.strptime(r["trade_date"], "%Y-%m-%d") for r in all_rows)
    cutoff = (last_date - timedelta(days=RECENT_WINDOW_CALENDAR_DAYS)).strftime("%Y-%m-%d")
    recent_rows = [r for r in all_rows if r["trade_date"] >= cutoff]

    for label, rows in [("3y", all_rows), ("recent_12m", recent_rows)]:
        top = _top_quintile_rows(rows)
        blocked = [r for r in top if not r["eligible"]]
        reasons = Counter(r["eligibility_first_fail_reason"] for r in blocked)
        print(f"\n[{label}] 차단됨 {len(blocked)}건 — 실패 사유 분포:")
        for reason, cnt in reasons.most_common():
            print(f"  {reason}: {cnt}건 ({cnt/len(blocked)*100:.1f}%)")


if __name__ == "__main__":
    asyncio.run(main())
