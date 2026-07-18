#!/usr/bin/env python3
"""SPPV-2.62 — 국면 혼합도 모니터링 모듈 검증: §40(SPPV-2.50) 실측
결과를 신규 재구현(`services/regime_mixedness_monitor.py`)이 정확히
재현하는지 확인(read-only, 신규 KIS 호출 0건 — 기존 3년 bars 캐시만
재사용).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §40.5/§40.7
이 "다음 단계"로 남긴 "국면 혼합도를 실거래 반영 이후 모니터링
지표로 삼을지" 검토를, 이번 턴에 **소비 가능한 순수 판정 모듈**로
전환하고 그 정확성을 검증한다.

**방법**: 벤치마크(KODEX 200, 069500)의 3년 캐시된 일봉에서 시장
공통 국면 라벨 시계열을 재계산하고(§40과 동일한 로직 재사용), 신규
모듈의 `compute_mixed_score`/`classify_mixedness_bucket`으로 634
거래일 전부를 재분류한다. §40이 실측한 저혼합 217일/중혼합 215일/
고혼합 202일과 정확히 일치하는지 확인한다 — 일치하면 신규 모듈이
기존 연구 결과를 정확히 재구현했다는 뜻이고, 불일치하면 재구현에
버그가 있다는 뜻이다.

이 스크립트는 `client=None`으로 `_fetch_extended_bars`를 호출한다 —
3년치 bars가 이미 로컬 캐시(`logs/_bars_cache_core87_3y_2026-07-14/
069500.json`)에 있으므로 KIS 클라이언트 자체가 필요 없다(캐시 히트
시 client 인자를 전혀 참조하지 않는 기존 함수 구조를 그대로 이용).

DB write / 주문 경로 / 실시간 구독 / broker submit 없음.
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
logger = logging.getLogger("validate_regime_mixedness_monitor")

_KST = timezone(timedelta(hours=9))

_sys.path.insert(0, "scripts")
_sys.path.insert(0, "src")


async def main() -> None:
    from agent_trading.services.regime_mixedness_monitor import (
        MIXEDNESS_WINDOW_TRADING_DAYS,
        classify_mixedness_bucket,
        compute_mixed_score,
    )
    from validate_signal_predictive_power_v4_extended_period import (
        BENCHMARK_SYMBOL,
        _build_benchmark_daily_series,
        _fetch_extended_bars,
    )

    # 캐시 히트 시 client를 전혀 참조하지 않으므로 None으로 충분하다
    # (신규 KIS 호출 없이 순수 read-only 로컬 재계산).
    bench_bars = await _fetch_extended_bars(None, BENCHMARK_SYMBOL)
    if not bench_bars:
        raise SystemExit(
            f"벤치마크 bars 캐시를 찾지 못함 — logs/_bars_cache_core87_3y_2026-07-14/"
            f"{BENCHMARK_SYMBOL}.json 확인 필요(신규 KIS 호출 없이는 재계산 불가)"
        )

    regime_by_date, _ = _build_benchmark_daily_series(bench_bars)
    if not regime_by_date:
        raise SystemExit("시장 공통 국면 계산 실패")

    dates = sorted(regime_by_date.keys())
    labels_in_order = [regime_by_date[d] for d in dates]

    bucket_day_counts: dict[str, int] = {"저혼합(단일 국면 지배)": 0, "중혼합": 0, "고혼합": 0}
    n_skipped_insufficient_history = 0
    n_classified = 0
    reason_code_counts: dict[str, int] = {}

    for i, d in enumerate(dates):
        trailing_labels = labels_in_order[: i + 1]
        mixed_score = compute_mixed_score(trailing_labels)
        if mixed_score is None:
            n_skipped_insufficient_history += 1
            continue
        assessment = classify_mixedness_bucket(mixed_score)
        bucket_day_counts[assessment.bucket] += 1
        reason_code_counts[assessment.reason_code] = reason_code_counts.get(assessment.reason_code, 0) + 1
        n_classified += 1

    print("\n=== 국면 혼합도 모니터링 모듈 검증 — §40 재현성 확인 ===")
    print(f"전체 거래일: {len(dates)}, 분류된 거래일: {n_classified}, "
          f"이력 부족으로 skip: {n_skipped_insufficient_history}")
    print(f"버킷별 거래일 수: {bucket_day_counts}")
    print(f"reason_code 분포: {reason_code_counts}")

    expected = {"저혼합(단일 국면 지배)": 217, "중혼합": 215, "고혼합": 202}
    matches_sppv_2_50 = bucket_day_counts == expected

    print(f"\n§40(SPPV-2.50) 실측치와 일치 여부: {matches_sppv_2_50}")
    print(f"  §40 기대값: {expected}")
    print(f"  이번 재구현: {bucket_day_counts}")

    report = {
        "as_of": datetime.now(_KST).isoformat(),
        "benchmark_symbol": BENCHMARK_SYMBOL,
        "mixedness_window_trading_days": MIXEDNESS_WINDOW_TRADING_DAYS,
        "total_trading_days": len(dates),
        "n_classified": n_classified,
        "n_skipped_insufficient_history": n_skipped_insufficient_history,
        "bucket_day_counts": bucket_day_counts,
        "reason_code_counts": reason_code_counts,
        "sppv_2_50_expected_bucket_day_counts": expected,
        "matches_sppv_2_50": matches_sppv_2_50,
        "note": (
            "신규 KIS 호출 없음 — 기존 3년 bars 캐시(logs/_bars_cache_core87_3y_2026-07-14/"
            f"{BENCHMARK_SYMBOL}.json)만 재사용. classify_mixedness_bucket()은 BUY/SELL "
            "판정에 연결되지 않은 순수 관측/로깅용 분류기다(§40.5 원칙 유지)."
        ),
    }
    out_path = "logs/signal_ic_regime_mixedness_monitor_validation_2026-07-18.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
