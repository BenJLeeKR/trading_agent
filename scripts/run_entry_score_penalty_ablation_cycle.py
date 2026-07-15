#!/usr/bin/env python3
"""`entry_score` 중복 penalty ablation — 시계열 누적 + 국면 정의 비교 사이클
(read-only).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §8(1일치 실측),
§9(신설, 이 스크립트 도입 근거) 참고.

§8(SPPV-2.18)은 오늘 하루치로 "entry_score의 세 penalty 축(A/B/C)이
사실상 완전히 겹친다"와 "종목별(per-symbol) regime_label이 시장 공통
(market-common) 국면과 전혀 다르다"는 두 가지를 정량화했다. 이 스크립트는
그 두 관찰을 **하루치 관찰에서 시계열 누적 절차로 승격**한다 — 새 계산
로직을 만들지 않고 기존 두 스크립트의 함수를 그대로 재사용한다.

1. `scripts/shadow_entry_score_penalty_ablation.py`의
   `_reconstruct_symbol_state()`(§8 penalty 축 A/B/C 계산, 종목별
   `classify_market_regime` 재사용)를 그대로 가져온다.
2. `scripts/run_regime_conditional_shadow_cycle.py`가 이미 확립한
   "시장 공통 국면"(벤치마크 KODEX 200의 rolling 상태, §22
   `_build_benchmark_regime_by_date` 재사용) 계산을 그대로 가져와,
   종목별 regime_label과 대조한다.
3. 매 실행 결과를 **누적 이력 파일**(`logs/entry_score_penalty_
   ablation_history.jsonl`, append-only, 거래일당 1줄, 같은 거래일
   재실행 시 중복 추가하지 않음)에 쌓는다 — `run_regime_conditional_
   shadow_cycle.py`가 확립한 이력 파일 패턴과 동일한 형식을 따른다.

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
logger = logging.getLogger("run_entry_score_penalty_ablation_cycle")

_KST = timezone(timedelta(hours=9))

import sys as _sys  # noqa: E402

_sys.path.insert(0, "scripts")
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    _fetch_extended_bars,
)
from shadow_entry_score_penalty_ablation import _reconstruct_symbol_state  # noqa: E402
from shadow_regime_conditional_entry_signal import (  # noqa: E402
    _build_benchmark_regime_by_date,
)

HISTORY_PATH = "logs/entry_score_penalty_ablation_history.jsonl"


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

    print("\n=== entry_score 중복 penalty ablation — 시계열 누적 + 국면 비교 사이클 ===")

    # 시장 공통 국면(§22 로직 재사용) — 벤치마크는 1회만 조회
    bench_bars = await _fetch_extended_bars(client, BENCHMARK_SYMBOL)
    market_common_regime_by_date = _build_benchmark_regime_by_date(bench_bars)
    if not market_common_regime_by_date:
        raise SystemExit("시장 공통 국면 계산 실패")
    latest_date = max(market_common_regime_by_date)
    market_common_regime = market_common_regime_by_date[latest_date]
    print(f"[시장 공통 국면] 기준일={latest_date}, 국면={market_common_regime}")

    symbols = sorted(APPROVED_CORE_UNIVERSE_SYMBOLS - {BENCHMARK_SYMBOL})
    rows: list[dict] = []
    fetch_failures: list[str] = []
    for idx, symbol in enumerate(symbols, start=1):
        bars = await _fetch_extended_bars(client, symbol)
        row = _reconstruct_symbol_state(symbol, bars)
        if row is None:
            fetch_failures.append(symbol)
            continue
        row["market_common_regime"] = market_common_regime_by_date.get(row["trade_date"], "unknown")
        row["per_symbol_vs_market_common_agree"] = (
            row["regime_label"] == row["market_common_regime"]
        )
        rows.append(row)
        if idx % 20 == 0 or idx == len(symbols):
            logger.info("[%d/%d] 처리 완료", idx, len(symbols))

    n = len(rows)
    axis_a = sum(1 for r in rows if r["axis_entry_score_regime_penalty"])
    axis_b = sum(1 for r in rows if r["axis_eligibility_regime_block"])
    axis_c = sum(1 for r in rows if r["axis_eligibility_signal_floor"])
    overlap_abc = sum(1 for r in rows if r["axes_fired_count"] == 3)
    none_fired = sum(1 for r in rows if r["axes_fired_count"] == 0)

    agree_count = sum(1 for r in rows if r["per_symbol_vs_market_common_agree"])
    disagree_count = n - agree_count

    # "시장은 비하락장인데 종목별로는 bearish_trend" — 가장 중요한 divergence 축
    market_non_bearish_but_symbol_bearish = sum(
        1
        for r in rows
        if r["market_common_regime"] != "bearish_trend" and r["regime_label"] == "bearish_trend"
    )
    market_bearish_but_symbol_non_bearish = sum(
        1
        for r in rows
        if r["market_common_regime"] == "bearish_trend" and r["regime_label"] != "bearish_trend"
    )

    from collections import Counter

    per_symbol_regime_dist = dict(Counter(r["regime_label"] for r in rows))

    print(f"\n재구성 종목: {n}/{len(symbols)} (실패 {len(fetch_failures)})")
    print(f"[축 A] entry_score regime penalty: {axis_a}건, [축 B] eligibility regime 차단: {axis_b}건, "
          f"[축 C] eligibility signal floor: {axis_c}건, [A∩B∩C]: {overlap_abc}건, [무발동]: {none_fired}건")
    print(f"[국면 정의 비교] 종목별 분포={per_symbol_regime_dist}, 시장 공통={market_common_regime}")
    print(f"[국면 일치] 일치={agree_count}건, 불일치={disagree_count}건")
    print(f"  - 시장 비하락장인데 종목별 하락장 판정: {market_non_bearish_but_symbol_bearish}건")
    print(f"  - 시장 하락장인데 종목별 비하락장 판정: {market_bearish_but_symbol_non_bearish}건")

    # 누적 이력에 한 줄 추가(같은 거래일 중복 스킵)
    trade_date = rows[0]["trade_date"] if rows else latest_date
    existing_dates = _load_existing_trade_dates(HISTORY_PATH)

    history_record = {
        "as_of": datetime.now(_KST).isoformat(),
        "trade_date": trade_date,
        "market_common_regime": market_common_regime,
        "symbol_count_total": len(symbols),
        "symbol_count_reconstructed": n,
        "fetch_failures": fetch_failures,
        "venn": {
            "A_entry_score_regime_penalty": axis_a,
            "B_eligibility_regime_block": axis_b,
            "C_eligibility_signal_floor": axis_c,
            "A_and_B_and_C": overlap_abc,
            "none_fired": none_fired,
        },
        "per_symbol_regime_distribution": per_symbol_regime_dist,
        "regime_agreement": {
            "agree_count": agree_count,
            "disagree_count": disagree_count,
            "market_non_bearish_but_symbol_bearish": market_non_bearish_but_symbol_bearish,
            "market_bearish_but_symbol_non_bearish": market_bearish_but_symbol_non_bearish,
        },
    }

    if trade_date in existing_dates:
        print(f"\n[누적] {trade_date}는 이미 이력에 존재 — 중복 추가 skip(파일: {HISTORY_PATH})")
    else:
        os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
        with open(HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(history_record, ensure_ascii=False) + "\n")
        print(f"\n[누적] 이력에 1줄 추가 완료 — {HISTORY_PATH}")

    total_history = len(existing_dates | {trade_date})
    print(f"[누적] 현재까지 누적된 고유 거래일 수: {total_history}")

    detail_report = {
        "as_of": datetime.now(_KST).isoformat(),
        "trade_date": trade_date,
        "market_common_regime": market_common_regime,
        "symbol_count_total": len(symbols),
        "symbol_count_reconstructed": n,
        "fetch_failures": fetch_failures,
        "venn": history_record["venn"],
        "regime_agreement": history_record["regime_agreement"],
        "rows": rows,
    }
    detail_path = f"logs/entry_score_penalty_ablation_{trade_date}.json"
    with open(detail_path, "w", encoding="utf-8") as f:
        json.dump(detail_report, f, ensure_ascii=False, indent=2)
    print(f"[상세] 당일 스냅샷 저장 — {detail_path}")


if __name__ == "__main__":
    asyncio.run(main())
