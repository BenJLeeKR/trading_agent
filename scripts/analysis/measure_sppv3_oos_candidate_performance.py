#!/usr/bin/env python3
"""SPPV-3 신호 재설계 후보의 독립 OOS 성과 계산 도구 — read-only 연구용.

``docs/10_signal_research_sppv/[DESIGN] signal_predictive_power_validation.md``
§41(후보 B 역방향 동결)·§42/§43(신규 OOS bar cache 수집)이 준비한
``2026-07-15`` 이후 신규 구간을 대상으로, 다음 세 후보의 성과를 계산한다.

- ``overnight_reversal_v1 = -overnight_ret_5d``
- ``intraday_reversal_v1 = -intraday_ret_5d``
- ``low_volatility_rank_20d``(§36.2 기존 수식·방향 그대로)

**이 스크립트는 수식·기대 방향을 절대 재해석하지 않는다** — §41.2/§36.2가
동결한 그대로 계산만 한다. 신규 KIS 호출·DB 연결·임시 테이블 생성·
컨테이너 재기동을 전혀 하지 않는다. ``scripts/validate_signal_
predictive_power_v11_candidate_bc_freeze.py``의 계산 함수(원재료 계산,
국면/risk_tone 분류, IC·Newey-West 집계, 결측 제외, 동점 평균 순위)를
그대로 재사용하고, 이 파일에서는 오직 "어떤 행을 OOS 표본으로 셀지"와
"표본이 부족하면 판정을 보류한다"는 로직만 새로 추가한다.

핵심 원칙 — 표본 부족은 실패가 아니라 정상 상태
--------------------------------------------------
``2026-07-15``~``2026-08-24`` 구간은 약 27거래일뿐이다. §36.3/§41.3이
정한 최소 표본(국면당 30거래일 등) 근처에도 못 미친다. 이 스크립트는
억지로 Go/Watch/Hold/No-Go를 내지 않는다 — 최소 조건을 만족하지
못하면 ``PENDING_INSUFFICIENT_OOS_SAMPLE``을 반환하고, 정확히 어떤
조건이 왜 미달인지(전체 거래일 수, horizon별 미도래 수, 국면별 표본
수)를 결과에 남긴다.

OOS 표본의 정의(반드시 아래 전부를 만족해야 성과 계산에 포함)
----------------------------------------------------------------
1. ``_cache_provenance == "oos_new"``(§42/§43이 저장한 provenance 태그).
2. 거래일 ``>= 2026-07-15``.
3. OOS cache의 ``manifest.json``이 ``ready_for_oos == true``임을
   실행 시작 시 검증(하나라도 계약을 어기면 명확히 실패).
4. 해당 horizon의 forward return이 실제로 도래하고 유한한 값일 것
   (T+1/T+5/T+20을 horizon별로 독립적으로 판정 — 어느 한 horizon이
   아직 도래하지 않았다고 다른 horizon까지 통째로 버리지 않는다).

기존 base cache(``_cache_provenance == "base_cache"``) 행은 lookback
warm-up(5/20/60일 계산에 필요한 과거 구간)으로만 쓰고, 성과 통계
표본에는 절대 포함하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
if os.path.join(_REPO_ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))
_scripts_path = os.path.join(_REPO_ROOT, "scripts")
if _scripts_path not in sys.path:
    sys.path.insert(0, _scripts_path)

from validate_signal_predictive_power_v11_candidate_bc_freeze import (  # noqa: E402
    CANDIDATE_B_LOOKBACK_DAYS,
    FORWARD_HORIZONS,
    MIN_REGIME_TRADING_DAYS,
    StrictBar,
    _is_finite_number,
    _MIN_LOOKBACK,
    _rows_with_valid_signal_and_return,
    attach_low_volatility_rank,
    compute_overnight_intraday_split_momentum,
    load_strict_bars,
    rank_low_volatility_cross_sectional,  # noqa: F401 - attach_low_volatility_rank가 내부에서 사용, 재노출 목적
    regime_sample_gate,
    summarize_by_regime,
    summarize_signal_window,
)

KST = timezone(timedelta(hours=9))

# ── 고정 계약(§41.3/§42/§43) — 실행 결과를 보고 바꾸지 않음 ─────────────────
EXPECTED_BASE_CACHE_ID = "_bars_cache_core87_3y_2026-07-14"
EXPECTED_BASE_CACHE_RELATIVE_PATH = "logs/_bars_cache_core87_3y_2026-07-14"
EXPECTED_BASE_CACHE_AS_OF_DATE = "2026-07-14"
EXPECTED_OOS_START_DATE_COMPACT = "20260715"  # manifest 포맷(YYYYMMDD)
OOS_START_DATE_ISO = "2026-07-15"  # 표본 필터링에 쓰는 ISO 포맷(YYYY-MM-DD)

MIN_OOS_TRADING_DAYS_FOR_VERDICT = 30  # MIN_REGIME_TRADING_DAYS와 동일 관례

# 후보명 -> (원재료 신호 컬럼, 기대 부호(+1=양의 IC 기대))
CANDIDATES: dict[str, dict[str, Any]] = {
    "overnight_reversal_v1": {"raw_column": "overnight_ret_5d", "sign": -1, "expected_ic_sign": 1},
    "intraday_reversal_v1": {"raw_column": "intraday_ret_5d", "sign": -1, "expected_ic_sign": 1},
    "low_volatility_rank_20d": {"raw_column": "low_volatility_rank_20d", "sign": 1, "expected_ic_sign": 1},
}


# ── manifest/provenance 계약 검증(순수 함수) ────────────────────────────────


def validate_oos_manifest(manifest: dict[str, Any]) -> None:
    """OOS cache manifest가 §42/§43 계약과 일치하는지 검증한다.

    하나라도 어긋나면 ``ValueError``로 명확히 실패한다 — 잘못된 cache를
    가리키거나, base cache가 바뀌었거나, 수집이 불완전한 상태로 이
    스크립트를 실행하는 사고를 막기 위함이다.
    """
    errors: list[str] = []
    if manifest.get("base_cache_id") != EXPECTED_BASE_CACHE_ID:
        errors.append(
            f"base_cache_id 불일치: 기대={EXPECTED_BASE_CACHE_ID!r}, "
            f"실제={manifest.get('base_cache_id')!r}"
        )
    if manifest.get("base_cache_relative_path") != EXPECTED_BASE_CACHE_RELATIVE_PATH:
        errors.append(
            f"base_cache_relative_path 불일치: 기대={EXPECTED_BASE_CACHE_RELATIVE_PATH!r}, "
            f"실제={manifest.get('base_cache_relative_path')!r}"
        )
    if manifest.get("base_cache_as_of_date") != EXPECTED_BASE_CACHE_AS_OF_DATE:
        errors.append(
            f"base_cache_as_of_date 불일치: 기대={EXPECTED_BASE_CACHE_AS_OF_DATE!r}, "
            f"실제={manifest.get('base_cache_as_of_date')!r}"
        )
    oos_window = manifest.get("oos_collection_window") or {}
    if oos_window.get("start_date") != EXPECTED_OOS_START_DATE_COMPACT:
        errors.append(
            f"oos_collection_window.start_date 불일치: "
            f"기대={EXPECTED_OOS_START_DATE_COMPACT!r}, 실제={oos_window.get('start_date')!r}"
        )
    if manifest.get("ready_for_oos") is not True:
        errors.append(
            f"ready_for_oos가 true가 아닙니다(실제={manifest.get('ready_for_oos')!r}) — "
            "수집이 불완전한 cache로는 OOS 성과를 계산하지 않는다."
        )

    if errors:
        raise ValueError(
            "OOS manifest 계약 위반으로 중단합니다:\n- " + "\n- ".join(errors)
        )


def build_benchmark_regime_and_risk_tone_by_date_full_range(
    bench_bars: list, benchmark_symbol: str
) -> dict[str, dict[str, str]]:
    """v11의 ``build_benchmark_regime_and_risk_tone_by_date()``와 달리
    ``len(bench_bars) - 1 - max(FORWARD_HORIZONS)``로 뒷부분을 잘라내지
    않는다.

    v11의 원래 절단은 "같은 루프에서 벤치마크 forward return도 함께
    계산한다"는 v4/v11 원래 설계의 부산물이다 — 3년 전체 cache에서는
    27일 정도 덜 도는 게 무시할 만했지만, **OOS 구간 자체가 27거래일
    밖에 안 되는 이번 분석에서 그 절단을 그대로 쓰면 최근 20거래일의
    국면 라벨이 통째로 사라진다**(실제로 처음 이 버그가 실행 결과에서
    발견됐다 — ``regime_label_unavailable``이 표본 수만큼 튀어나오는
    것으로 드러남). 국면 라벨 자체는 forward return이 전혀 필요 없는
    순수 backward-looking 계산(``window = bars[:t+1]``)이므로, 이
    함수는 그 절단 없이 마지막 거래일까지 전부 계산한다.
    """
    from types import SimpleNamespace

    from agent_trading.services.market_regime import classify_market_regime
    from agent_trading.services.signal_backbone import build_signal_snapshot

    out: dict[str, dict[str, str]] = {}
    for t in range(_MIN_LOOKBACK - 1, len(bench_bars)):
        window = bench_bars[: t + 1]
        try:
            features, card = build_signal_snapshot(benchmark_symbol, window)
        except Exception:  # noqa: BLE001 - 국면 라벨 결측으로만 처리
            continue
        snapshot = SimpleNamespace(
            overall_score=float(card.overall_score),
            fast_score=float(card.fast_score),
            slow_score=float(card.slow_score),
            return_1m_pct=features.return_1m_pct,
            return_3m_pct=features.return_3m_pct,
            price_vs_sma_20_pct=features.price_vs_sma_20_pct,
            price_vs_sma_60_pct=features.price_vs_sma_60_pct,
            volatility_20d_pct=features.volatility_20d_pct,
            atr_14_pct=features.atr_14_pct,
            volume_surge_ratio=features.volume_surge_ratio,
        )
        assessment = classify_market_regime(snapshot)
        trade_date = bench_bars[t].timestamp.strftime("%Y-%m-%d")
        out[trade_date] = {
            "regime_label": assessment.regime_label if assessment else "unknown",
            "risk_tone": assessment.risk_tone if assessment else "unknown",
        }
    return out


# ── OOS provenance가 태그된 bar 로딩(순수 계산 + 얇은 I/O) ──────────────────


def build_provenance_by_date(raw_bars: dict[str, dict[str, Any]]) -> dict[str, str]:
    """cache 파일의 raw dict(날짜 YYYYMMDD -> 원본 row)에서
    ``_cache_provenance``만 뽑아 **ISO 날짜(YYYY-MM-DD) 키**로 돌려준다
    (``_collect_oos_samples_for_symbol``의 ``trade_date``가 ISO 포맷이라
    비교 편의를 위해 여기서 미리 변환한다).

    ``"base_cache"``/``"oos_new"`` 이외의 값이 하나라도 있으면 provenance
    혼입으로 간주해 ``ValueError``를 낸다 — 이 계약이 깨지면 warm-up과
    OOS 표본을 더 이상 안전하게 구분할 수 없기 때문이다.
    """
    out: dict[str, str] = {}
    for compact_date, row in raw_bars.items():
        provenance = row.get("_cache_provenance")
        if provenance not in ("base_cache", "oos_new"):
            raise ValueError(
                f"알 수 없는 _cache_provenance 값({provenance!r})이 날짜 "
                f"{compact_date}에서 발견됐습니다 — cache가 손상됐거나 "
                "다른 출처의 데이터가 섞였을 수 있어 중단합니다."
            )
        iso_date = f"{compact_date[0:4]}-{compact_date[4:6]}-{compact_date[6:8]}"
        out[iso_date] = provenance
    return out


def load_oos_bars_with_provenance(
    symbol: str, oos_cache_dir: str
) -> tuple[list[StrictBar], dict[str, str]]:
    """``load_strict_bars()``(v11 재사용)로 bar 시퀀스를,
    ``build_provenance_by_date()``로 provenance 맵을 함께 만든다.
    """
    strict_bars, _load_exclusions = load_strict_bars(symbol, cache_dir=oos_cache_dir)
    path = os.path.join(oos_cache_dir, f"{symbol}.json")
    with open(path, encoding="utf-8") as f:
        raw_bars = json.load(f)
    provenance_by_date = build_provenance_by_date(raw_bars)
    return strict_bars, provenance_by_date


# ── OOS 전용 표본 수집(base/oos_new를 horizon별로 독립 판정) ────────────────


def collect_oos_samples_for_symbol(
    symbol: str,
    strict_bars: list[StrictBar],
    provenance_by_date: dict[str, str],
    regime_by_date: dict[str, dict[str, str]],
    horizons: list[int] = FORWARD_HORIZONS,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """이 종목의 ``oos_new`` 거래일만 표본으로 만든다.

    v11의 ``_collect_candidate_samples()``와 달리, 특정 horizon의
    forward bar가 아직 없다고 그 거래일 전체를 버리지 않는다 — horizon
    마다 독립적으로 ``fwd_{h}``를 계산하거나(도래했으면) ``None``으로
    남긴다(도래하지 않았으면). 그래야 "T+1은 되는데 T+20은 아직"이라는
    상태를 그대로 보고할 수 있다.
    """
    from agent_trading.services.signal_backbone import PriceBar, build_signal_snapshot

    price_bars = [
        PriceBar(
            timestamp=datetime.strptime(b.trade_date, "%Y%m%d").replace(tzinfo=KST),
            open_price=b.open if b.open_valid else b.close,
            high_price=b.high if b.high is not None else b.close,
            low_price=b.low if b.low is not None else b.close,
            close_price=b.close,
            volume=0.0,
            turnover=None,
        )
        for b in strict_bars
    ]

    exclusion_counts: dict[str, int] = {}

    def _bump(key: str) -> None:
        exclusion_counts[key] = exclusion_counts.get(key, 0) + 1

    samples: list[dict[str, Any]] = []
    if len(price_bars) < _MIN_LOOKBACK:
        return samples, exclusion_counts

    for t in range(_MIN_LOOKBACK - 1, len(price_bars)):
        trade_date_iso = price_bars[t].timestamp.strftime("%Y-%m-%d")
        if provenance_by_date.get(trade_date_iso) != "oos_new":
            continue
        if trade_date_iso < OOS_START_DATE_ISO:
            continue

        b_result = compute_overnight_intraday_split_momentum(strict_bars, t, CANDIDATE_B_LOOKBACK_DAYS)
        if b_result["exclusion_reason"] is not None:
            _bump(f"candidate_b_{b_result['exclusion_reason']}")

        window = price_bars[: t + 1]
        try:
            features, _card = build_signal_snapshot(symbol, window)
            vol_20d = features.volatility_20d_pct
            if not _is_finite_number(vol_20d):
                _bump("candidate_c_volatility_nonfinite")
                vol_20d = None
        except Exception:  # noqa: BLE001 - 결측 사유로만 집계, 원본 예외는 남기지 않음
            _bump("candidate_c_signal_snapshot_failed")
            vol_20d = None

        regime_info = regime_by_date.get(trade_date_iso)
        if regime_info is None:
            _bump("regime_label_unavailable")

        row: dict[str, Any] = {
            "symbol": symbol,
            "trade_date": trade_date_iso,
            "overnight_ret_5d": b_result["overnight_ret_Nd"],
            "intraday_ret_5d": b_result["intraday_ret_Nd"],
            "divergence_5d": b_result["divergence"],
            "volatility_20d_pct_raw": vol_20d,
            "common_market_regime": (regime_info or {}).get("regime_label", "unknown"),
            "risk_tone": (regime_info or {}).get("risk_tone", "unknown"),
        }

        base_close = price_bars[t].close_price
        for h in horizons:
            target_idx = t + h
            if target_idx >= len(price_bars):
                row[f"fwd_{h}"] = None
                row[f"fwd_{h}_net"] = None
                _bump(f"fwd_{h}_horizon_not_arrived")
                continue
            fwd_close = price_bars[target_idx].close_price
            raw_ret = (fwd_close / base_close - 1.0) if base_close else float("nan")
            if not _is_finite_number(raw_ret):
                row[f"fwd_{h}"] = None
                row[f"fwd_{h}_net"] = None
                _bump(f"fwd_{h}_nonfinite")
                continue
            row[f"fwd_{h}"] = raw_ret
            row[f"fwd_{h}_net"] = raw_ret - (30.0 / 10_000.0)

        samples.append(row)

    return samples, exclusion_counts


def attach_reversal_candidates(samples: list[dict[str, Any]]) -> None:
    """§41.2 동결 수식 그대로 ``overnight_reversal_v1``/``intraday_
    reversal_v1``을 부호만 반전해 부여한다 — 원재료가 결측(``None``)
    이면 반전 후에도 결측으로 남긴다(0으로 채우지 않음)."""
    for row in samples:
        overnight = row.get("overnight_ret_5d")
        row["overnight_reversal_v1"] = -overnight if overnight is not None else None
        intraday = row.get("intraday_ret_5d")
        row["intraday_reversal_v1"] = -intraday if intraday is not None else None


# ── 표본 충분성 게이트 + Go/Watch/Hold/No-Go 위임 ──────────────────────────


def classify_verdict_from_t_stat(t_stat: float | None, expected_ic_sign: int) -> str:
    """§36.3/§41.3 판정 규칙을 t-통계 하나에 적용하는 위임 대상 함수.

    표본이 충분하다고 판단된 뒤에만 호출한다 — 표본 부족 여부는 이
    함수의 책임이 아니라 호출자(``determine_oos_analysis_status``)의
    책임이다.
    """
    if t_stat is None:
        return "Hold"
    abs_t = abs(t_stat)
    same_sign = (t_stat > 0) == (expected_ic_sign > 0)
    if abs_t >= 2.0:
        return "Go" if same_sign else "No-Go"
    if abs_t >= 1.5:
        return "Watch" if same_sign else "Hold"
    return "Hold"


def determine_oos_analysis_status(
    *,
    total_oos_trading_days: int,
    per_horizon_valid_counts: dict[int, int],
    regime_gate: dict[str, dict[str, Any]],
    primary_t_stat: float | None = None,
    expected_ic_sign: int = 1,
) -> dict[str, Any]:
    """표본이 §36.3/§41.3 최소 조건을 만족하는지 먼저 확인하고, 만족할
    때만 ``classify_verdict_from_t_stat()``에 판정을 위임한다.

    미달이면 어떤 조건이 왜 미달인지 구체적인 사유 목록과 함께
    ``PENDING_INSUFFICIENT_OOS_SAMPLE``을 반환한다 — Go/Watch/Hold/
    No-Go 중 어느 것도 억지로 내지 않는다.
    """
    reasons: list[str] = []

    if total_oos_trading_days < MIN_OOS_TRADING_DAYS_FOR_VERDICT:
        reasons.append(
            f"전체 OOS 거래일 수 부족: {total_oos_trading_days}일 "
            f"(최소 {MIN_OOS_TRADING_DAYS_FOR_VERDICT}일 필요)"
        )

    for h in FORWARD_HORIZONS:
        valid = per_horizon_valid_counts.get(h, 0)
        if valid < MIN_OOS_TRADING_DAYS_FOR_VERDICT:
            reasons.append(
                f"T+{h} 유효 표본 부족: {valid}건 "
                f"(최소 {MIN_OOS_TRADING_DAYS_FOR_VERDICT}건 필요, horizon 미도래 포함)"
            )

    insufficient_regimes = [
        regime
        for regime, info in regime_gate.items()
        if not info.get("meets_min_sample", False)
    ]
    if insufficient_regimes or not regime_gate:
        reasons.append(
            "국면별 최소 표본(각 "
            f"{MIN_REGIME_TRADING_DAYS}거래일) 미달 국면: "
            f"{sorted(insufficient_regimes) if regime_gate else '관측된 국면 없음'}"
        )

    if reasons:
        return {"status": "PENDING_INSUFFICIENT_OOS_SAMPLE", "reasons": reasons}

    verdict = classify_verdict_from_t_stat(primary_t_stat, expected_ic_sign)
    return {"status": verdict, "reasons": []}


# ── main ────────────────────────────────────────────────────────────────────


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "SPPV-3 신호 재설계 후보의 독립 OOS 성과 계산(read-only) — "
            "표본 부족 시 PENDING_INSUFFICIENT_OOS_SAMPLE 출력"
        )
    )
    parser.add_argument(
        "--oos-cache-dir",
        required=True,
        help="§42/§43이 생성한 OOS bar cache 디렉터리(예: logs/_bars_cache_core87_3y_2026-08-24)",
    )
    parser.add_argument("--output-json", default=None, help="결과 JSON 저장 경로(선택)")
    args = parser.parse_args(argv)

    oos_cache_dir = args.oos_cache_dir
    manifest_path = os.path.join(oos_cache_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        raise SystemExit(f"manifest.json이 없습니다: {manifest_path}")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    validate_oos_manifest(manifest)

    from agent_trading.services.core_universe_seed import APPROVED_CORE_UNIVERSE_SYMBOLS

    universe = sorted(APPROVED_CORE_UNIVERSE_SYMBOLS)
    benchmark_symbol = "069500"

    bench_strict_bars, bench_provenance = load_oos_bars_with_provenance(benchmark_symbol, oos_cache_dir)
    from agent_trading.services.signal_backbone import PriceBar

    bench_price_bars = [
        PriceBar(
            timestamp=datetime.strptime(b.trade_date, "%Y%m%d").replace(tzinfo=KST),
            open_price=b.open if b.open_valid else b.close,
            high_price=b.high if b.high is not None else b.close,
            low_price=b.low if b.low is not None else b.close,
            close_price=b.close,
            volume=0.0,
            turnover=None,
        )
        for b in bench_strict_bars
    ]
    regime_by_date = build_benchmark_regime_and_risk_tone_by_date_full_range(bench_price_bars, benchmark_symbol)

    all_samples: list[dict[str, Any]] = []
    exclusion_totals: dict[str, int] = {}
    for symbol in universe:
        if symbol == benchmark_symbol:
            continue
        strict_bars, provenance_by_date = load_oos_bars_with_provenance(symbol, oos_cache_dir)
        samples, exclusions = collect_oos_samples_for_symbol(symbol, strict_bars, provenance_by_date, regime_by_date)
        for k, v in exclusions.items():
            exclusion_totals[k] = exclusion_totals.get(k, 0) + v
        all_samples.extend(samples)

    attach_reversal_candidates(all_samples)
    attach_low_volatility_rank(all_samples)

    total_oos_trading_days = len({row["trade_date"] for row in all_samples})
    regime_gate = regime_sample_gate(all_samples)

    result: dict[str, Any] = {
        "reproducibility_metadata": {
            "query_executed_at_kst": datetime.now(tz=KST).isoformat(),
            "oos_cache_dir": oos_cache_dir,
            "manifest_validated": True,
            "total_oos_trading_days": total_oos_trading_days,
            "exclusion_counts": exclusion_totals,
            "min_oos_trading_days_for_verdict": MIN_OOS_TRADING_DAYS_FOR_VERDICT,
            "no_operational_reflection_note": (
                "이 결과는 운영 정책 반영·Stage B 착수 근거로 쓰지 않는다. "
                "PENDING_INSUFFICIENT_OOS_SAMPLE 상태에서는 더더욱 그렇다."
            ),
        },
        "candidates": {},
    }

    for candidate_name, spec in CANDIDATES.items():
        signal_col = spec["raw_column"]
        expected_sign = spec["expected_ic_sign"]
        horizon_summary = summarize_signal_window(all_samples, signal_col, FORWARD_HORIZONS)
        by_regime = summarize_by_regime(all_samples, signal_col, FORWARD_HORIZONS)

        per_horizon_valid = {
            h: horizon_summary[f"T+{h}"]["valid_row_count_for_ic"] for h in FORWARD_HORIZONS
        }
        primary_ic = horizon_summary["T+1"]["ic"].get("t_newey_west")

        status = determine_oos_analysis_status(
            total_oos_trading_days=total_oos_trading_days,
            per_horizon_valid_counts=per_horizon_valid,
            regime_gate=regime_gate,
            primary_t_stat=primary_ic,
            expected_ic_sign=expected_sign,
        )

        result["candidates"][candidate_name] = {
            "signal_column": signal_col,
            "expected_ic_sign": expected_sign,
            "horizon_summary": horizon_summary,
            "by_regime": by_regime,
            "status": status,
        }

    result["regime_sample_gate"] = regime_gate

    print(json.dumps(result["reproducibility_metadata"], ensure_ascii=False, indent=2))
    print("\n=== 후보별 상태 ===")
    for name, info in result["candidates"].items():
        print(f"- {name}: {info['status']['status']}")
        for reason in info["status"]["reasons"]:
            print(f"    - {reason}")

    if args.output_json:
        os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n[출력] 결과 JSON 저장: {args.output_json}")

    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
