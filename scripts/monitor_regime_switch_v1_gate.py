#!/usr/bin/env python3
"""SPPV-2.13 — `regime_switch_v1` 1차 게이트 모니터링 (규칙 A, read-only).

``plans/[DESIGN] signal_predictive_power_validation.md`` §20.2/§20.5,
§21 참고.

§20(SPPV-2.12)은 `regime_switch_v1`(국면 전환형 shadow 후보)의 1차
게이트 예외로 **규칙 A(관찰 유예)**를 채택했다 — 표본을 억지로 조작해
지금 당장 통과시키지 않고, "시장 공통 국면이 `bearish_trend`로 실제
전환되는 시점"을 재검증 트리거로 삼는다.

이 스크립트는 그 트리거를 감시하는 경량 도구다. 87종목 전체를 조회할
필요 없이 **벤치마크(KODEX 200, 069500) 하나만** 조회해 최근 12개월
창의 시장 공통 국면 분포를 계산한다 — 매일/매주 반복 실행해도 KIS
호출 부담이 거의 없다(벤치마크 1종목, 캐시 우선 재사용).

판정 로직:
  - 최근 12개월 창에 `bearish_trend` 거래일이 `MIN_REGIME_TRADING_DAYS`
    (30일, §16/§20과 동일 기준) 이상 나타나면 → 트리거 발동, `regime_
    switch_v1`의 1차 게이트 재검증(SPPV-2.9~2.12 스크립트 재실행)을
    권고한다.
  - 1일 이상 30일 미만이면 → "부분 관측"으로 표시, 아직 재검증 시점은
    아니지만 감시를 강화한다.
  - 0일이면 → 이전과 동일, 계속 관찰 유예.

DB write / 주문 경로 / 실시간 구독 없음. KIS 과거 일봉 조회(read)만
수행하며, 캐시가 있으면 그것을 그대로 재사용한다(신규 호출 최소화).
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("monitor_regime_switch_v1_gate")

_KST = timezone(timedelta(hours=9))

import sys as _sys  # noqa: E402

_sys.path.insert(0, "scripts")
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    _build_benchmark_daily_series,
    _fetch_extended_bars,
)

RECENT_WINDOW_CALENDAR_DAYS = 365
MIN_REGIME_TRADING_DAYS = 30


async def _run() -> dict:
    from agent_trading.config.settings import AppSettings
    from agent_trading.runtime.bootstrap import _build_kis_live_quote_client

    settings = AppSettings()
    client = _build_kis_live_quote_client(settings)
    if client is None:
        raise SystemExit("KIS live quote client 생성 실패 — KIS_LIVE_INFO_* 확인")

    bench_bars = await _fetch_extended_bars(client, BENCHMARK_SYMBOL)
    regime_by_date, _ = _build_benchmark_daily_series(bench_bars)
    if not regime_by_date:
        raise SystemExit("벤치마크 국면 라벨 계산 실패 — 캐시/조회 결과 확인 필요")

    last_date = max(datetime.strptime(d, "%Y-%m-%d") for d in regime_by_date)
    cutoff = (last_date - timedelta(days=RECENT_WINDOW_CALENDAR_DAYS)).strftime("%Y-%m-%d")

    recent_counts: dict[str, int] = defaultdict(int)
    for d, r in regime_by_date.items():
        if d >= cutoff:
            recent_counts[r] += 1

    bearish_days = recent_counts.get("bearish_trend", 0)
    if bearish_days >= MIN_REGIME_TRADING_DAYS:
        trigger_status = "TRIGGERED"
        trigger_message = (
            f"최근 12개월 창에 bearish_trend {bearish_days}일 확보(>= "
            f"{MIN_REGIME_TRADING_DAYS}) — regime_switch_v1 1차 게이트 재검증 권고"
        )
    elif bearish_days > 0:
        trigger_status = "PARTIAL"
        trigger_message = (
            f"최근 12개월 창에 bearish_trend {bearish_days}일 관측(< "
            f"{MIN_REGIME_TRADING_DAYS}) — 아직 재검증 시점 아님, 감시 강화"
        )
    else:
        trigger_status = "NOT_TRIGGERED"
        trigger_message = "최근 12개월 창에 bearish_trend 0일 — 규칙 A(관찰 유예) 유지"

    report = {
        "as_of": datetime.now(_KST).isoformat(),
        "benchmark_symbol": BENCHMARK_SYMBOL,
        "recent_window_calendar_days": RECENT_WINDOW_CALENDAR_DAYS,
        "cutoff_trade_date": cutoff,
        "last_trade_date": last_date.strftime("%Y-%m-%d"),
        "recent_common_market_regime_distribution": dict(recent_counts),
        "min_regime_trading_days_gate": MIN_REGIME_TRADING_DAYS,
        "trigger_status": trigger_status,
        "trigger_message": trigger_message,
    }

    print("\n=== regime_switch_v1 1차 게이트 모니터링(규칙 A) ===")
    print(f"기준일: {last_date.strftime('%Y-%m-%d')}, 최근 {RECENT_WINDOW_CALENDAR_DAYS}일 cutoff={cutoff}")
    print(f"국면 분포: {dict(recent_counts)}")
    print(f"판정: {trigger_status} — {trigger_message}")

    return report


def main() -> None:
    import asyncio

    report = asyncio.run(_run())
    out_path = "logs/regime_switch_v1_gate_monitor_2026-07-14.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    main()
