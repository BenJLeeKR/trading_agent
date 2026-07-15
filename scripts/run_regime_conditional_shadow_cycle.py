#!/usr/bin/env python3
"""국면 분기형 진입 신호 — Phase 2 shadow 누적 사이클 (read-only).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §4.2/§4.3,
§6(신설, 이 스크립트 도입 근거) 참고.

Phase 1(§5, 2026-07-15)은 `scripts/shadow_regime_conditional_entry_
signal.py`로 1회 스냅샷만 남겼다. Phase 2는 **반복 실행해 시계열로
누적**해야 의미가 있으므로, 이 스크립트는 기존 두 도구를 새로 짜지
않고 그대로 재사용해 한 번에 묶는다:

1. `scripts/monitor_regime_switch_v1_gate.py`의 게이트 판정 로직(1차
   창=최근 12개월, 국면 분포 → `TRIGGERED`/`PARTIAL`/`NOT_TRIGGERED`,
   §21에서 확립)을 그대로 재사용한다.
2. `scripts/shadow_regime_conditional_entry_signal.py`의 신호 계산
   함수(`_build_benchmark_regime_by_date`, `_latest_regime_and_signal`,
   §22에서 확립)를 그대로 재사용한다.
3. 벤치마크(069500) bars를 **한 번만** 조회해 위 두 계산에 함께
   사용한다 — 중복 KIS 호출을 만들지 않는다.
4. 매 실행 결과를 **누적 이력 파일**(`logs/regime_conditional_signal_
   shadow_history.jsonl`, append-only, 거래일당 1줄, 같은 거래일
   재실행 시 덮어쓰지 않고 중복 스킵)에 한 줄씩 추가한다 — Phase 1의
   "1회성 스냅샷"과 달리 이 파일을 반복 실행하면 시계열이 쌓인다.
5. 게이트 판정이 `TRIGGERED`(또는 `PARTIAL`)이면, 화면에 **다음에
   수행해야 할 재검증 순서**를 그대로 출력한다(§4.3의 runbook을
   실행 시점에 다시 보여주는 역할 — 자동 재검증은 하지 않는다, 3년
   전체 재계산은 비용이 크고 신중한 판단이 필요하므로 사람이 다음
   턴에 명시적으로 착수한다).

DB write / 주문 경로 / 실시간 구독 없음. 3년 캐시를 재사용하며, 캐시가
없는 신규 심볼만 KIS 조회한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("run_regime_conditional_shadow_cycle")

_KST = timezone(timedelta(hours=9))

import sys as _sys  # noqa: E402

_sys.path.insert(0, "scripts")
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    _build_benchmark_daily_series,
    _fetch_extended_bars,
)
from monitor_regime_switch_v1_gate import (  # noqa: E402
    MIN_REGIME_TRADING_DAYS,
    RECENT_WINDOW_CALENDAR_DAYS,
)
from shadow_regime_conditional_entry_signal import (  # noqa: E402
    _build_benchmark_regime_by_date,
    _latest_regime_and_signal,
)

HISTORY_PATH = "logs/regime_conditional_signal_shadow_history.jsonl"

# TRIGGERED/PARTIAL 시 사람이 다음 턴에 수행해야 할 재검증 순서(§4.3 runbook).
# 여기서 자동 실행하지 않는다 — 3년 캐시 재구축·전면 재검증은 신중한 판단이
# 필요한 별도 작업이다.
_TRIGGERED_RUNBOOK = [
    "1. 3년 캐시(logs/_bars_cache_core87_3y_*)를 하락장 구간을 포함하도록 최신화한다"
    "(KIS 재조회 필요 — rate budget 고려해 진행).",
    "2. scripts/validate_signal_predictive_power_v9_gate_and_fast_features.py"
    "를 재실행해 regime_switch_v1의 §16 1차(최근 12개월) 게이트가"
    "실제로 |t_NW|>=2를 통과하는지, 2차(3년) 국면별 분해에서 역전이"
    "없는지 재확인한다.",
    "3. plans/[DESIGN] regime_conditional_entry_signal_v1.md §4.3의"
    "Go/No-Go 기준(1차 유의 + 2차 무역전 + 하락장 표본 30일 이상)을"
    "모두 만족하는지 판정하고 문서에 근거를 남긴다.",
    "4. Go 판정이면 entry_score 통합(§3, 현재 미적용)의 실제 코드"
    "변경 여부를 사용자와 논의한다 — 이 스크립트는 그 결정을 대신하지"
    "않는다.",
]


def _load_existing_trade_dates(path: str) -> set[str]:
    if not os.path.exists(path):
        return set()
    dates: set[str] = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            d = rec.get("trade_date")
            if d:
                dates.add(d)
    return dates


async def main() -> None:
    from agent_trading.config.settings import AppSettings
    from agent_trading.runtime.bootstrap import _build_kis_live_quote_client
    from agent_trading.services.core_universe_seed import APPROVED_CORE_UNIVERSE_SYMBOLS

    settings = AppSettings()
    client = _build_kis_live_quote_client(settings)
    if client is None:
        raise SystemExit("KIS live quote client 생성 실패 — KIS_LIVE_INFO_* 확인")

    print("\n=== 국면 분기형 진입 신호 — Phase 2 shadow 누적 사이클 ===")

    # 벤치마크는 한 번만 조회 — 게이트 판정과 오늘 신호 계산 양쪽에 재사용.
    bench_bars = await _fetch_extended_bars(client, BENCHMARK_SYMBOL)

    # 1) 게이트 판정(§21 monitor_regime_switch_v1_gate.py 로직 재사용)
    gate_regime_by_date, _ = _build_benchmark_daily_series(bench_bars)
    if not gate_regime_by_date:
        raise SystemExit("게이트용 국면 라벨 계산 실패")
    gate_last_date = max(datetime.strptime(d, "%Y-%m-%d") for d in gate_regime_by_date)
    gate_cutoff = (gate_last_date - timedelta(days=RECENT_WINDOW_CALENDAR_DAYS)).strftime("%Y-%m-%d")

    from collections import defaultdict

    recent_counts: dict[str, int] = defaultdict(int)
    for d, r in gate_regime_by_date.items():
        if d >= gate_cutoff:
            recent_counts[r] += 1
    bearish_days = recent_counts.get("bearish_trend", 0)
    if bearish_days >= MIN_REGIME_TRADING_DAYS:
        gate_status = "TRIGGERED"
    elif bearish_days > 0:
        gate_status = "PARTIAL"
    else:
        gate_status = "NOT_TRIGGERED"

    print(f"[게이트] 기준일={gate_last_date.strftime('%Y-%m-%d')}, cutoff={gate_cutoff}, "
          f"국면분포={dict(recent_counts)}, 판정={gate_status}")

    # 2) 오늘 신호 계산(§22 shadow_regime_conditional_entry_signal.py 로직 재사용)
    shadow_regime_by_date = _build_benchmark_regime_by_date(bench_bars)
    if not shadow_regime_by_date:
        raise SystemExit("shadow용 국면 라벨 계산 실패")
    shadow_latest_date = max(shadow_regime_by_date)
    shadow_latest_regime = shadow_regime_by_date[shadow_latest_date]
    print(f"[신호] 기준일={shadow_latest_date}, 시장 공통 국면={shadow_latest_regime}")

    symbols = sorted(APPROVED_CORE_UNIVERSE_SYMBOLS - {BENCHMARK_SYMBOL})
    rows: list[dict] = []
    fetch_failures: list[str] = []
    for idx, symbol in enumerate(symbols, start=1):
        bars = await _fetch_extended_bars(client, symbol)
        row = _latest_regime_and_signal(symbol, bars, shadow_regime_by_date)
        if row is None:
            fetch_failures.append(symbol)
            continue
        rows.append(row)
        if idx % 20 == 0 or idx == len(symbols):
            logger.info("[%d/%d] 처리 완료", idx, len(symbols))

    valid_rows = [r for r in rows if r["regime_conditional_signal"] is not None]
    signal_source_counts: dict[str, int] = defaultdict(int)
    for r in valid_rows:
        signal_source_counts[r["signal_source"]] += 1

    # 3) 누적 이력에 한 줄 추가(같은 거래일 중복 스킵)
    existing_dates = _load_existing_trade_dates(HISTORY_PATH)
    history_record = {
        "as_of": datetime.now(_KST).isoformat(),
        "trade_date": shadow_latest_date,
        "common_market_regime": shadow_latest_regime,
        "gate_status": gate_status,
        "gate_bearish_days_recent_12m": bearish_days,
        "symbol_count_total": len(symbols),
        "symbol_count_with_signal": len(valid_rows),
        "signal_source_distribution": dict(signal_source_counts),
        "fetch_failures": fetch_failures,
    }

    if shadow_latest_date in existing_dates:
        print(f"\n[누적] {shadow_latest_date}는 이미 이력에 존재 — 중복 추가 skip"
              f"(파일: {HISTORY_PATH})")
    else:
        os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
        with open(HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(history_record, ensure_ascii=False) + "\n")
        print(f"\n[누적] 이력에 1줄 추가 완료 — {HISTORY_PATH}")

    total_history = len(existing_dates | {shadow_latest_date})
    print(f"[누적] 현재까지 누적된 고유 거래일 수: {total_history}")

    # 상세 스냅샷도 함께 저장(당일자 파일 — Phase 1과 동일 포맷)
    detail_report = {
        "as_of": datetime.now(_KST).isoformat(),
        "benchmark_symbol": BENCHMARK_SYMBOL,
        "latest_benchmark_trade_date": shadow_latest_date,
        "latest_common_market_regime": shadow_latest_regime,
        "gate_status": gate_status,
        "symbol_count_total": len(symbols),
        "symbol_count_with_signal": len(valid_rows),
        "fetch_failures": fetch_failures,
        "rows": rows,
    }
    detail_path = f"logs/shadow_regime_conditional_entry_signal_{shadow_latest_date}.json"
    with open(detail_path, "w", encoding="utf-8") as f:
        json.dump(detail_report, f, ensure_ascii=False, indent=2)
    print(f"[상세] 당일 스냅샷 저장 — {detail_path}")

    if gate_status != "NOT_TRIGGERED":
        print(f"\n⚠️ 게이트 판정이 {gate_status}입니다 — 다음 재검증 절차를 수행하세요:")
        for step in _TRIGGERED_RUNBOOK:
            print(f"  {step}")
    else:
        print("\n게이트 판정 NOT_TRIGGERED — 규칙 A(관찰 유예) 유지, 추가 조치 없음.")


if __name__ == "__main__":
    asyncio.run(main())
