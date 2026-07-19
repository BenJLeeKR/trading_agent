#!/usr/bin/env python3
"""SPPV-2.67 — R3b alpha candidate_percentile 사전 계산 모듈 검증:
`services/r3b_alpha_percentile.py`가 이 세션 내내 사용해 온 shadow
스크립트(`validate_r3b_point_in_time_pipeline_shadow.py`)의
`_attach_candidate_only_percentile` 로직을 정확히 재현하는지
무작위 대조 검증한다(read-only, 신규 KIS 호출 0건).

**방법**: 무작위로 생성한 종목별 (market_common_label, return_1m_pct,
return_3m_pct, volatility_20d_pct) 조합을 두 구현(기존 shadow 함수 /
신규 `r3b_alpha_percentile` 모듈)에 동일하게 입력해 candidate pool
구성과 percentile 값이 정확히 일치하는지 비교한다. 200회 trial(종목
수 3~40 무작위) 전부 일치해야 "정확히 이식됨"으로 판정한다.

DB write / 주문 경로 / 실시간 구독 / broker submit 없음.
"""

from __future__ import annotations

import random
import sys

sys.path.insert(0, "scripts")
sys.path.insert(0, "src")


def main() -> None:
    from validate_r3b_point_in_time_pipeline_shadow import (
        _attach_candidate_only_percentile,
    )

    from agent_trading.services.r3b_alpha_percentile import (
        R3bAlphaInput,
        build_candidate_percentiles,
    )

    random.seed(42)
    labels = ["bullish_trend", "range_bound", "bearish_trend", None]
    mismatches = 0
    trials = 200

    for _ in range(trials):
        n = random.randint(3, 40)
        rows: list[dict] = []
        items: list[R3bAlphaInput] = []
        for i in range(n):
            label = random.choice(labels)
            ret1m = random.uniform(-20, 20)
            ret3m = random.uniform(-30, 30)
            vol = random.uniform(0.5, 30)
            if label in ("bullish_trend", "range_bound"):
                signal = ret3m / max(vol, 1.0)
            elif label == "bearish_trend":
                signal = -ret1m
            else:
                signal = None
            rows.append(
                {
                    "trade_date": "D1",
                    "regime_conditional_signal": signal,
                    "symbol": f"S{i}",
                }
            )
            items.append(R3bAlphaInput(f"S{i}", label, ret1m, ret3m, vol))

        _attach_candidate_only_percentile(rows)
        shadow_result = {
            r["symbol"]: r["candidate_percentile"]
            for r in rows
            if r.get("candidate_percentile") is not None
        }
        mine = build_candidate_percentiles(items)

        if shadow_result.keys() != mine.keys():
            mismatches += 1
            continue
        for k in shadow_result:
            if abs(shadow_result[k] - mine[k]) > 1e-9:
                mismatches += 1
                break

    print(f"총 {trials}회 trial 중 불일치: {mismatches}")
    if mismatches:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
