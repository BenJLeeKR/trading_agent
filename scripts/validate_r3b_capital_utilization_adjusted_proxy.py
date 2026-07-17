#!/usr/bin/env python3
"""SPPV-2.40 — R3b 총 기대수익 proxy의 유휴 자본(미사용 슬롯) 반영
보강 검증 (read-only, broker submit 없음).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §29.5(다음
단계, 유휴 자본 기회비용 반영 정교화) 참고.

§29(SPPV-2.39)는 `총 기대수익 proxy = would_buy_n × mean_forward_
return_pct`로 8개 창×2horizon(16개 조합) 중 14개에서 R3b가 R0보다
높다는 것을 확인했으나, 이 proxy는 **거래일당 3슬롯(WATCH_TOP_K_
BUY) 중 실제로 쓰지 않은 슬롯의 기회비용을 반영하지 않는다** —
즉 "덜 사는 만큼 총효율이 떨어지는가"라는 질문에 아직 완전히
답하지 않았다.

이 스크립트는 신규 실측(§20 funnel 재실행)을 하지 않고, 두 가지
보강 proxy만 계산한다:

**보강 A(전체 슬롯 정규화, per-slot proxy)**: 창의 전체 거래일 수
(이 스크립트가 유일하게 새로 계측하는 값 — 기존 캐시된 3년치 봉
데이터로만 거래일 집합을 구성해 계산하며, 신규 KIS 호출은 없다)
× 3(WATCH_TOP_K_BUY)을 "전체 가용 슬롯"으로 두고, 미사용 슬롯은
수익률 0%(유휴 현금)로 가정해 `총 기대수익 proxy / 전체 가용
슬롯`을 계산한다. **이 정규화는 R0/R3b 모두 같은 창의 같은 분모로
나누는 것이므로, 대수적으로 R3b/R0 비율 자체는 변하지 않는다**
(항등식 — 아래 §40.1에서 직접 검증) — 그러나 "거래당 평균"이
아니라 "가용 자본 전체 대비 수익률"이라는, 더 운영에 가까운 단위로
같은 결론을 재확인한다는 의의가 있다.

**보강 B(엄격한 유휴 자본 기회비용 상한 테스트)**: R3b의 실제
총합(realized, 미사용 슬롯은 0%로 가정 — 가장 보수적)을, "R0가
전체 가용 슬롯(거래일수×3)을 전부 R0 자신의 평균 수익률로 채웠다면
얻었을 이론적 최대"와 비교한다. 이는 R0의 **실현된** 총합(§29의
기존 비교 대상)보다 항상 크거나 같은, R3b 입장에서 가장 불리한
벤치마크다 — 이 기준을 통과하면 "유휴 자본을 최대한 관대하게
계산해도 R3b가 이긴다"는 강한 증거가 된다.

DB write / 주문 경로 / 실시간 구독 / broker submit 없음. 실제 KIS
호출 여부는 가정하지 않고 로그의 `HTTP Request:` 카운트로 그대로
보고한다(이 스크립트는 캐시된 3년 봉 데이터만 사용하므로 0건이
기대값이다).
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys as _sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_r3b_capital_utilization_adjusted_proxy")

_KST = timezone(timedelta(hours=9))

_sys.path.insert(0, "scripts")
from validate_alpha_layer_r3_reproducibility import _split_into_quarters  # noqa: E402
from validate_activity_filter_threshold_sweep import _split_first_second_half  # noqa: E402
from validate_alpha_layer_score_rescaling_comparison import _collect_symbol_rows  # noqa: E402
from validate_signal_predictive_power_v2 import _MIN_LOOKBACK  # noqa: E402
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    FORWARD_HORIZONS_FOCUS,
    _build_benchmark_daily_series,
    _fetch_extended_bars,
)

WATCH_TOP_K_BUY = 3  # trigger_proxy_attribution.py의 실제 운영 상수 재사용(신규 아님)

REPRO_JSON = "logs/signal_ic_alpha_layer_r3_reproducibility_2026-07-16.json"

WINDOW_LABELS = {
    "supplementary_3y": "2차(3년)",
    "primary_recent_12m": "1차(12M)",
    "3y_first_half": "전반부",
    "3y_second_half": "후반부",
    "quarter_1": "분기1",
    "quarter_2": "분기2",
    "quarter_3": "분기3",
    "quarter_4": "분기4",
}


def _compute_proxies(total_trading_days: dict) -> dict:
    with open(REPRO_JSON, encoding="utf-8") as f:
        repro = json.load(f)

    report: dict = {"windows": {}}
    print("=== R3b 유휴 자본 반영 보강 proxy — R0 vs R3b ===\n")

    for wkey, label in WINDOW_LABELS.items():
        w = repro["windows"][wkey]["scenarios"]
        r0 = w["B_R0_no_rescale"]
        r3b = w["B_R3b_percentile_candidateonly"]
        n_days = total_trading_days[wkey]
        total_slots = n_days * WATCH_TOP_K_BUY

        window_report: dict = {"label": label, "n_trading_days": n_days, "total_slots": total_slots, "by_horizon": {}}
        print(f"--- {label} (거래일 {n_days}일, 전체 가용 슬롯 {total_slots}) ---")

        for h in ("T+5", "T+20"):
            r0_n, r3b_n = r0["would_buy_n"], r3b["would_buy_n"]
            r0_m = r0["by_stage_horizon"][h]["mean_pct"]
            r3b_m = r3b["by_stage_horizon"][h]["mean_pct"]

            r0_total_raw = round(r0_n * r0_m, 1)
            r3b_total_raw = round(r3b_n * r3b_m, 1)
            raw_ratio = round(r3b_total_raw / r0_total_raw * 100, 1) if r0_total_raw else None

            # 보강 A: 전체 슬롯 정규화(per-slot, 미사용=0%) — 항등식 검증용
            r0_per_slot = round(r0_total_raw / total_slots, 4)
            r3b_per_slot = round(r3b_total_raw / total_slots, 4)
            per_slot_ratio = round(r3b_per_slot / r0_per_slot * 100, 1) if r0_per_slot else None

            # 보강 B: R0의 이론적 최대(전체 슬롯을 R0 자신의 평균으로 100% 채웠다고 가정)
            r0_theoretical_max_total = round(total_slots * r0_m, 1)
            strict_ratio = round(r3b_total_raw / r0_theoretical_max_total * 100, 1) if r0_theoretical_max_total else None

            flip_vs_raw = (raw_ratio is not None and strict_ratio is not None) and ((raw_ratio > 100) != (strict_ratio > 100))

            horizon_report = {
                "r0_would_buy_n": r0_n, "r3b_would_buy_n": r3b_n,
                "r0_mean_pct": r0_m, "r3b_mean_pct": r3b_m,
                "raw_total_proxy": {"R0": r0_total_raw, "R3b": r3b_total_raw, "r3b_pct_of_r0": raw_ratio},
                "per_slot_proxy_idle_zero": {"R0": r0_per_slot, "R3b": r3b_per_slot, "r3b_pct_of_r0": per_slot_ratio},
                "strict_vs_r0_theoretical_max": {
                    "r0_theoretical_max_total": r0_theoretical_max_total,
                    "r3b_realized_total": r3b_total_raw,
                    "r3b_pct_of_r0_theoretical_max": strict_ratio,
                },
                "verdict_flip_raw_vs_strict": flip_vs_raw,
            }
            window_report["by_horizon"][h] = horizon_report

            print(f"  [{h}] 기존(raw) proxy R3b/R0={raw_ratio}% | "
                  f"per-slot(항등식 확인) R3b/R0={per_slot_ratio}% | "
                  f"엄격 기준(R0 이론적 최대 대비) R3b={strict_ratio}% | "
                  f"판정 뒤집힘={flip_vs_raw}")

        report["windows"][wkey] = window_report
        print()

    return report


async def _count_trading_days() -> dict:
    from agent_trading.config.settings import AppSettings
    from agent_trading.runtime.bootstrap import _build_kis_live_quote_client
    from agent_trading.services.core_universe_seed import APPROVED_CORE_UNIVERSE_SYMBOLS

    settings = AppSettings()
    client = _build_kis_live_quote_client(settings)
    if client is None:
        raise SystemExit("KIS live quote client 생성 실패 — KIS_LIVE_INFO_* 확인")

    bench_bars = await _fetch_extended_bars(client, BENCHMARK_SYMBOL)
    market_common_regime_by_date, _ = _build_benchmark_daily_series(bench_bars)
    if not market_common_regime_by_date:
        raise SystemExit("시장 공통 국면 계산 실패")

    symbols = sorted(APPROVED_CORE_UNIVERSE_SYMBOLS - {BENCHMARK_SYMBOL})
    all_rows: list[dict] = []
    fetch_failures: list[str] = []
    for idx, symbol in enumerate(symbols, start=1):
        bars = await _fetch_extended_bars(client, symbol)
        if len(bars) < _MIN_LOOKBACK + max(FORWARD_HORIZONS_FOCUS) + 5:
            fetch_failures.append(symbol)
            continue
        rows = _collect_symbol_rows(symbol, bars, market_common_regime_by_date)
        all_rows.extend(rows)
        if idx % 20 == 0 or idx == len(symbols):
            logger.info("[%d/%d] 누적 표본 %d건", idx, len(symbols), len(all_rows))

    logger.info("전체 3년 표본 %d건, 실패 %d종목", len(all_rows), len(fetch_failures))

    last_date = max(datetime.strptime(r["trade_date"], "%Y-%m-%d") for r in all_rows)
    cutoff = (last_date - timedelta(days=365)).strftime("%Y-%m-%d")
    recent_rows = [r for r in all_rows if r["trade_date"] >= cutoff]
    first_half_rows, second_half_rows = _split_first_second_half(all_rows)
    quarters = _split_into_quarters(all_rows)

    window_rows = {
        "supplementary_3y": all_rows,
        "primary_recent_12m": recent_rows,
        "3y_first_half": first_half_rows,
        "3y_second_half": second_half_rows,
        "quarter_1": quarters[0],
        "quarter_2": quarters[1],
        "quarter_3": quarters[2],
        "quarter_4": quarters[3],
    }
    return {k: len({r["trade_date"] for r in rows}) for k, rows in window_rows.items()}


async def main() -> None:
    total_trading_days = await _count_trading_days()
    print("=== 창별 전체 거래일 수(신규 KIS 호출 없음, 캐시 봉 데이터로만 계산) ===")
    for k, v in total_trading_days.items():
        print(f"  {WINDOW_LABELS[k]}: {v}일")
    print()

    report = _compute_proxies(total_trading_days)
    report["as_of"] = datetime.now(_KST).isoformat()
    report["total_trading_days"] = total_trading_days

    out_path = "logs/signal_ic_r3b_capital_utilization_adjusted_proxy_2026-07-17.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
