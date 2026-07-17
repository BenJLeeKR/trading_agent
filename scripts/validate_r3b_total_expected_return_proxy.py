#!/usr/bin/env python3
"""SPPV-2.39 — R3b의 거래 빈도 감소를 반영한 총 기대수익 proxy 계산
(read-only, 신규 KIS 호출 없음 — 기존 산출물만 재사용).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §27.4/§27.5
가 명시한 Conditional Go 확정 전 잔여 조건 중 (2) "selected_rate
감소가 총 기대수익(거래 빈도×종목당 수익)에 미치는 영향 정량화"에
답한다.

이 스크립트는 신규 실측을 실행하지 않는다 — 이미 존재하는 두 산출물
만 읽어 재계산한다:
  - `logs/signal_ic_alpha_layer_r3_reproducibility_2026-07-16.json`
    (SPPV-2.30, 8개 창 실제 BUY funnel: candidate/eligible/selected/
    would_buy 표본 수, T+5/T+20 평균, t_NW, 양수 비율, MFE/MAE)
  - `logs/signal_ic_r3b_sppv3_entry_readiness_check_2026-07-17.json`
    (SPPV-2.37, would_buy 모집단의 거래일 수 n_days)

계산 방법(운영 가정, 신규 로직 아님): `WATCH_TOP_K_BUY=3`(거래일당
최대 매수 슬롯, `trigger_proxy_attribution.py`에서 재사용해온 실제
운영 상수)이 각 would_buy 거래에 동일한 자본을 배정한다고 가정하면,
어떤 창의 "총 기대수익 proxy"는 다음과 같이 근사할 수 있다:

    총 기대수익 proxy = would_buy_n × mean_forward_return_pct

이는 "거래 횟수 × 거래당 평균 수익률"의 단순 곱이며, 거래 횟수가
줄어도 거래당 수익률이 충분히 크면 총합이 커질 수 있는지(반대로
작아지는지)를 직접 보여준다. `n_days`(모집단 내 거래일 수)와
`would_buy_n/n_days`(활동일당 평균 매수 수)도 함께 계산해 "덜
사서 평균이 높아 보이는 착시"인지, "실제로 활동일당·거래당 품질이
개선된 것"인지 분리한다.

DB write / 주문 경로 / 실시간 구독 / broker submit 없음.
"""

from __future__ import annotations

import json

REPRO_JSON = "logs/signal_ic_alpha_layer_r3_reproducibility_2026-07-16.json"
READINESS_JSON = "logs/signal_ic_r3b_sppv3_entry_readiness_check_2026-07-17.json"

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


def main() -> None:
    with open(REPRO_JSON, encoding="utf-8") as f:
        repro = json.load(f)
    with open(READINESS_JSON, encoding="utf-8") as f:
        readiness = json.load(f)

    report: dict = {"windows": {}}

    print("=== R3b 총 기대수익 proxy (거래 빈도 반영) — R0 vs R3b ===\n")
    for wkey, label in WINDOW_LABELS.items():
        repro_w = repro["windows"][wkey]["scenarios"]
        readiness_w = readiness["windows"][wkey]["scenarios"]

        window_report: dict = {"label": label, "by_horizon": {}}
        print(f"--- {label} ---")

        for h in ("T+5", "T+20"):
            r0 = repro_w["B_R0_no_rescale"]
            r3b = repro_w["B_R3b_percentile_candidateonly"]

            r0_n = r0["would_buy_n"]
            r3b_n = r3b["would_buy_n"]
            r0_mean = r0["by_stage_horizon"][h]["mean_pct"]
            r3b_mean = r3b["by_stage_horizon"][h]["mean_pct"]
            r0_pos = r0["by_stage_horizon"][h]["pct_positive"]
            r3b_pos = r3b["by_stage_horizon"][h]["pct_positive"]
            r0_t = r0["by_stage_horizon"][h]["t_newey_west"]
            r3b_t = r3b["by_stage_horizon"][h]["t_newey_west"]
            r0_mfe = r0["mfe_mae_would_buy"][h]["mfe_mean_pct"]
            r0_mae = r0["mfe_mae_would_buy"][h]["mae_mean_pct"]
            r3b_mfe = r3b["mfe_mae_would_buy"][h]["mfe_mean_pct"]
            r3b_mae = r3b["mfe_mae_would_buy"][h]["mae_mean_pct"]

            r0_n_days = readiness_w["B_R0_no_rescale"]["by_horizon"][h]["n_days"]
            r3b_n_days = readiness_w["B_R3b_percentile_candidateonly"]["by_horizon"][h]["n_days"]

            r0_total_proxy = round(r0_n * r0_mean, 1)
            r3b_total_proxy = round(r3b_n * r3b_mean, 1)
            ratio_pct = round(r3b_total_proxy / r0_total_proxy * 100, 1) if r0_total_proxy else None

            r0_per_active_day = round(r0_n / r0_n_days, 3) if r0_n_days else None
            r3b_per_active_day = round(r3b_n / r3b_n_days, 3) if r3b_n_days else None

            horizon_report = {
                "R0": {
                    "would_buy_n": r0_n, "n_days": r0_n_days,
                    "would_buy_per_active_day": r0_per_active_day,
                    "mean_pct": r0_mean, "t_newey_west": r0_t, "pct_positive": r0_pos,
                    "mfe_mean_pct": r0_mfe, "mae_mean_pct": r0_mae,
                    "total_return_proxy": r0_total_proxy,
                },
                "R3b": {
                    "would_buy_n": r3b_n, "n_days": r3b_n_days,
                    "would_buy_per_active_day": r3b_per_active_day,
                    "mean_pct": r3b_mean, "t_newey_west": r3b_t, "pct_positive": r3b_pos,
                    "mfe_mean_pct": r3b_mfe, "mae_mean_pct": r3b_mae,
                    "total_return_proxy": r3b_total_proxy,
                },
                "r3b_total_proxy_pct_of_r0": ratio_pct,
            }
            window_report["by_horizon"][h] = horizon_report

            print(f"  [{h}] R0: would_buy={r0_n}(n_days={r0_n_days}, 활동일당={r0_per_active_day}), "
                  f"평균={r0_mean}%, t_NW={r0_t}, 양수율={r0_pos}, 총proxy={r0_total_proxy}")
            print(f"       R3b: would_buy={r3b_n}(n_days={r3b_n_days}, 활동일당={r3b_per_active_day}), "
                  f"평균={r3b_mean}%, t_NW={r3b_t}, 양수율={r3b_pos}, 총proxy={r3b_total_proxy} "
                  f"(R0 대비 {ratio_pct}%)")

        report["windows"][wkey] = window_report
        print()

    out_path = "logs/signal_ic_r3b_total_expected_return_proxy_2026-07-17.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"산출 저장: {out_path}")


if __name__ == "__main__":
    main()
