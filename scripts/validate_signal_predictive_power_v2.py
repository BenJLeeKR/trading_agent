#!/usr/bin/env python3
"""SPPV-2 — 신호 예측력 통계 보정 확장 (read-only).

``plans/[DESIGN] signal_predictive_power_validation.md`` §4.2(SPPV-2) 참고.

SPPV-1(파일럿) 대비 확장 사항:
1. core 8종목 → core 전체(APPROVED_CORE_UNIVERSE_SYMBOLS, ~90종목).
2. pooled IC → **거래일별 cross-sectional Spearman IC**(그날 여러 종목을
   순위 비교) + 시계열 평균/표준편차/ICIR/t-stat.
3. **국면별 분해**: 운영 코드 `classify_market_regime()`을 그대로 재사용해
   각 표본 시점의 종목 자체 regime_label(bullish/bearish/range 등)로 IC를
   쪼갠다.
4. **overlap 보정**: non-overlapping(호라이즌 간격만큼 띄어 뽑기) 표본으로도
   동일 지표를 재계산해 겹침 표본 결과와 나란히 제시.
5. **비용 차감 성과**: 왕복비용 가정치를 차감한 net return, MFE/MAE, 상위/
   하위 quintile 양수 비율을 함께 산출(단순 IC 숫자만으로 판단하지 않음).
6. horizon 확장: T+1/3/5/10/20.

point-in-time universe(당시 편입·편출 종목 포함)는 이번 턴에서 시도하지
않는다 — 지수/편입 이력이 1년 전체를 커버하지 못해(가장 오래된 스냅샷
2026-06-27) 시도 자체가 왜곡된 결과를 낼 위험이 크다. 이 한계는 결과
보고서에 그대로 명시한다(§ 분석 원칙: "표본 부족 시 부족하다고 명시").

운영 코드(`build_signal_snapshot`, `classify_market_regime`)를 그대로
재사용 — 검증용 신호 로직을 새로 만들지 않는다. DB write / 주문 경로 /
실시간 구독 없음. KIS 과거 일봉 조회(read)만 수행한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from math import sqrt
from types import SimpleNamespace

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_signal_predictive_power_v2")

_KST = timezone(timedelta(hours=9))

DIRECT_SIGNALS = ["slow_score", "fast_score", "overall_score"]
COMPONENT_SIGNALS = ["slow_momentum", "slow_trend"]
ALL_SIGNALS = DIRECT_SIGNALS + COMPONENT_SIGNALS
FORWARD_HORIZONS = [1, 3, 5, 10, 20]

_MIN_LOOKBACK = 61
_ROUND_TRIP_COST_BPS = 30.0  # 진입 8~ + 청산 6~ + slippage 보수적 가정(운영 EV gate 참고)


# ── 순위상관 유틸 (SPPV-1과 동일) ────────────────────────────────────────────


def _rank(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def _pearson(x: list[float], y: list[float]) -> float | None:
    n = len(x)
    if n < 3:
        return None
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    dx = sqrt(sum((a - mx) ** 2 for a in x))
    dy = sqrt(sum((b - my) ** 2 for b in y))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def _spearman_ic(signal: list[float], fwd: list[float]) -> float | None:
    if len(signal) != len(fwd) or len(signal) < 3:
        return None
    return _pearson(_rank(signal), _rank(fwd))


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _stdev(xs: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    m = _mean(xs)
    return sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _newey_west_se_of_mean(xs: list[float], lag: int) -> float | None:
    """평균의 Newey-West 표준오차 (겹치는 forward window로 인한 자기상관 보정).

    lag = horizon-1 만큼의 자기공분산을 Bartlett 가중치로 합산한다.
    """
    n = len(xs)
    if n < 3:
        return None
    m = _mean(xs)
    centered = [x - m for x in xs]
    gamma0 = sum(c * c for c in centered) / n
    var = gamma0
    for k in range(1, min(lag, n - 1) + 1):
        weight = 1.0 - k / (lag + 1.0)
        gamma_k = sum(centered[t] * centered[t - k] for t in range(k, n)) / n
        var += 2.0 * weight * gamma_k
    if var <= 0:
        return None
    return sqrt(var / n)


def _strength_label(ic: float) -> str:
    a = abs(ic)
    if a < 0.02:
        return "없음(노이즈)"
    if a < 0.05:
        return "미약"
    if a < 0.10:
        return "유의미"
    return "강함"


# ── KIS 일봉 페처 (SPPV-1과 동일 로직 재사용) ─────────────────────────────────


_BARS_CACHE_DIR = "logs/_bars_cache_core88_2026-07-14"


async def _fetch_year_bars(client, symbol: str, cache_dir: str | None = None):
    """과거 1년 일봉을 슬라이딩 조회로 병합. ``cache_dir`` 지정 시 종목별 원본
    응답(raw dict)을 로컬 JSON으로 캐싱해, 후속 분석(SPPV-2.5 등)에서 동일
    KIS 호출을 반복하지 않게 한다(rate budget 보호, read-only 산출물)."""
    import json as _json
    import os as _os

    from agent_trading.services.signal_backbone import PriceBar

    cache_path = _os.path.join(cache_dir, f"{symbol}.json") if cache_dir else None
    if cache_path and _os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            merged = _json.load(f)
        bars = _rows_to_bars(merged)
        if bars:
            return bars

    end = datetime.now(_KST).date()
    start = end - timedelta(days=400)

    merged: dict[str, dict] = {}
    window_start = start
    while window_start < end:
        window_end = min(window_start + timedelta(days=110), end)
        try:
            raw_rows = await client.inquire_daily_itemchartprice(
                symbol=symbol,
                market_code="J",
                start_date=window_start.strftime("%Y%m%d"),
                end_date=window_end.strftime("%Y%m%d"),
                period_div_code="D",
                adjusted_price=True,
            )
        except Exception as exc:
            logger.warning("%s: 일봉 조회 실패(%s~%s) — %s", symbol, window_start, window_end, exc)
            raw_rows = []
        for raw in raw_rows:
            d = str(raw.get("stck_bsop_date", "")).strip()
            if d:
                merged[d] = raw
        await asyncio.sleep(0.35)
        window_start = window_end + timedelta(days=1)

    if cache_path:
        _os.makedirs(cache_dir, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            _json.dump(merged, f, ensure_ascii=False)

    return _rows_to_bars(merged)


def _rows_to_bars(merged: dict[str, dict]):
    from agent_trading.services.signal_backbone import PriceBar

    bars: list[PriceBar] = []
    for d in sorted(merged.keys()):
        raw = merged[d]
        try:
            close = float(str(raw.get("stck_clpr", "")).replace(",", ""))
            high = float(str(raw.get("stck_hgpr", "")).replace(",", ""))
            low = float(str(raw.get("stck_lwpr", "")).replace(",", ""))
            open_ = float(str(raw.get("stck_oprc", "")).replace(",", "") or close)
            volume = float(str(raw.get("acml_vol", "")).replace(",", "") or 0)
            turnover_raw = str(raw.get("acml_tr_pbmn", "")).replace(",", "").strip()
            turnover = float(turnover_raw) if turnover_raw else None
        except (TypeError, ValueError):
            continue
        if close <= 0:
            continue
        bars.append(
            PriceBar(
                timestamp=datetime.strptime(d, "%Y%m%d").replace(tzinfo=_KST),
                open_price=open_,
                high_price=high,
                low_price=low,
                close_price=close,
                volume=volume,
                turnover=turnover,
            )
        )
    return bars


# ── 종목별 rolling 재계산 (신호 + regime + MFE/MAE + 비용차감 수익률) ────────


def _regime_label_for_features(features) -> str | None:
    """운영 코드 classify_market_regime()을 duck-typed snapshot으로 재사용."""
    from agent_trading.services.market_regime import classify_market_regime

    snapshot = SimpleNamespace(
        overall_score=None,
        fast_score=None,
        slow_score=None,
        return_1m_pct=features.return_1m_pct,
        return_3m_pct=features.return_3m_pct,
        price_vs_sma_20_pct=features.price_vs_sma_20_pct,
        price_vs_sma_60_pct=features.price_vs_sma_60_pct,
        volatility_20d_pct=features.volatility_20d_pct,
        atr_14_pct=features.atr_14_pct,
        volume_surge_ratio=features.volume_surge_ratio,
    )
    assessment = classify_market_regime(snapshot)
    return assessment.regime_label if assessment else None


def _collect_symbol_samples(symbol: str, bars: list) -> list[dict]:
    from agent_trading.services.signal_backbone import build_signal_snapshot

    samples: list[dict] = []
    last_t = len(bars) - 1 - max(FORWARD_HORIZONS)
    if last_t < _MIN_LOOKBACK - 1:
        return samples

    for t in range(_MIN_LOOKBACK - 1, last_t + 1):
        window = bars[: t + 1]
        try:
            features, card = build_signal_snapshot(symbol, window)
        except Exception:
            continue

        row: dict = {
            "symbol": symbol,
            "trade_date": bars[t].timestamp.strftime("%Y-%m-%d"),
        }
        for s in DIRECT_SIGNALS:
            row[s] = float(getattr(card, s))
        for s in COMPONENT_SIGNALS:
            if s in card.component_scores:
                row[s] = float(card.component_scores[s])

        # regime_label은 슬로우/오버롤 값을 채워 다시 분류(overall/fast/slow는
        # classify_market_regime에서 slow>=0.35 등 조건에 직접 쓰이므로 정확히
        # 채워 넣는다)
        try:
            from agent_trading.services.market_regime import classify_market_regime

            snapshot = SimpleNamespace(
                overall_score=row["overall_score"],
                fast_score=row["fast_score"],
                slow_score=row["slow_score"],
                return_1m_pct=features.return_1m_pct,
                return_3m_pct=features.return_3m_pct,
                price_vs_sma_20_pct=features.price_vs_sma_20_pct,
                price_vs_sma_60_pct=features.price_vs_sma_60_pct,
                volatility_20d_pct=features.volatility_20d_pct,
                atr_14_pct=features.atr_14_pct,
                volume_surge_ratio=features.volume_surge_ratio,
            )
            assessment = classify_market_regime(snapshot)
            row["regime_label"] = assessment.regime_label if assessment else "unknown"
        except Exception:
            row["regime_label"] = "unknown"

        base_close = bars[t].close_price
        for h in FORWARD_HORIZONS:
            fwd_bars = bars[t + 1 : t + h + 1]
            fwd_close = bars[t + h].close_price
            raw_ret = (fwd_close / base_close) - 1.0
            row[f"fwd_{h}"] = raw_ret
            row[f"fwd_{h}_net"] = raw_ret - (_ROUND_TRIP_COST_BPS / 10_000.0)
            if fwd_bars:
                mfe = max((b.high_price / base_close) - 1.0 for b in fwd_bars)
                mae = min((b.low_price / base_close) - 1.0 for b in fwd_bars)
            else:
                mfe = mae = raw_ret
            row[f"mfe_{h}"] = mfe
            row[f"mae_{h}"] = mae

        samples.append(row)
    return samples


# ── 집계: cross-sectional daily IC / ICIR / Newey-West ───────────────────────


def _cross_sectional_ic_series(
    all_samples: list[dict], signal: str, horizon: int, step: int = 1
) -> list[float]:
    """거래일별로 그날 표본을 모아 cross-sectional Spearman IC 계산.

    step>1이면 매 step 거래일(정렬된 유니크 날짜 기준)만 사용해 overlap을
    줄인 non-overlapping 근사치를 만든다.
    """
    by_date: dict[str, list[dict]] = defaultdict(list)
    for row in all_samples:
        if signal in row and f"fwd_{horizon}" in row:
            by_date[row["trade_date"]].append(row)

    dates_sorted = sorted(by_date.keys())
    if step > 1:
        dates_sorted = dates_sorted[::step]

    ic_series: list[float] = []
    for d in dates_sorted:
        rows = by_date[d]
        if len(rows) < 5:  # cross-section 최소 5종목 없으면 그날은 skip
            continue
        xs = [r[signal] for r in rows]
        ys = [r[f"fwd_{horizon}"] for r in rows]
        ic = _spearman_ic(xs, ys)
        if ic is not None:
            ic_series.append(ic)
    return ic_series


def _summarize_ic_series(ic_series: list[float], horizon: int) -> dict:
    n = len(ic_series)
    if n < 3:
        return {"n_days": n, "mean_ic": None}
    mean_ic = _mean(ic_series)
    std_ic = _stdev(ic_series)
    icir = (mean_ic / std_ic) if std_ic else None
    t_naive = (mean_ic / (std_ic / sqrt(n))) if std_ic else None
    nw_se = _newey_west_se_of_mean(ic_series, lag=max(horizon - 1, 1))
    t_nw = (mean_ic / nw_se) if nw_se else None
    pct_positive_days = sum(1 for x in ic_series if x > 0) / n
    return {
        "n_days": n,
        "mean_ic": round(mean_ic, 4),
        "std_ic": round(std_ic, 4) if std_ic else None,
        "icir": round(icir, 4) if icir else None,
        "t_naive": round(t_naive, 2) if t_naive else None,
        "t_newey_west": round(t_nw, 2) if t_nw else None,
        "pct_positive_days": round(pct_positive_days, 3),
        "strength": _strength_label(mean_ic),
    }


def _quintile_return_stats(all_samples: list[dict], signal: str, horizon: int) -> dict:
    """거래일별 신호 상위/하위 20% 그룹의 net forward return 비교(단순 IC 숫자 대신
    실제 수익률 분포로도 확인)."""
    by_date: dict[str, list[dict]] = defaultdict(list)
    for row in all_samples:
        if signal in row and f"fwd_{horizon}_net" in row:
            by_date[row["trade_date"]].append(row)

    top_returns: list[float] = []
    bottom_returns: list[float] = []
    top_mae: list[float] = []
    bottom_mae: list[float] = []
    for rows in by_date.values():
        if len(rows) < 5:
            continue
        ordered = sorted(rows, key=lambda r: r[signal])
        q = max(1, len(ordered) // 5)
        bottom = ordered[:q]
        top = ordered[-q:]
        top_returns.extend(r[f"fwd_{horizon}_net"] for r in top)
        bottom_returns.extend(r[f"fwd_{horizon}_net"] for r in bottom)
        top_mae.extend(r[f"mae_{horizon}"] for r in top)
        bottom_mae.extend(r[f"mae_{horizon}"] for r in bottom)

    def _stats(xs: list[float]) -> dict:
        if not xs:
            return {"n": 0}
        return {
            "n": len(xs),
            "mean_net_return_pct": round(_mean(xs) * 100, 3),
            "pct_positive": round(sum(1 for x in xs if x > 0) / len(xs), 3),
        }

    return {
        "top_quintile": {**_stats(top_returns), "mean_mae_pct": round(_mean(top_mae) * 100, 3) if top_mae else None},
        "bottom_quintile": {**_stats(bottom_returns), "mean_mae_pct": round(_mean(bottom_mae) * 100, 3) if bottom_mae else None},
        "spread_pct": round((_mean(top_returns) - _mean(bottom_returns)) * 100, 3)
        if top_returns and bottom_returns else None,
    }


def _regime_decomposed_ic(all_samples: list[dict], signal: str, horizon: int) -> dict:
    by_regime: dict[str, list[dict]] = defaultdict(list)
    for row in all_samples:
        by_regime[row.get("regime_label", "unknown")].append(row)

    result = {}
    for regime, rows in by_regime.items():
        if len(rows) < 30:
            result[regime] = {"n": len(rows), "ic": None, "note": "표본부족(<30)"}
            continue
        xs = [r[signal] for r in rows if signal in r and f"fwd_{horizon}" in r]
        ys = [r[f"fwd_{horizon}"] for r in rows if signal in r and f"fwd_{horizon}" in r]
        ic = _spearman_ic(xs, ys)
        result[regime] = {
            "n": len(xs),
            "ic": round(ic, 4) if ic is not None else None,
            "strength": _strength_label(ic) if ic is not None else None,
        }
    return result


async def main() -> None:
    from agent_trading.config.settings import AppSettings
    from agent_trading.runtime.bootstrap import _build_kis_live_quote_client
    from agent_trading.services.core_universe_seed import APPROVED_CORE_UNIVERSE_SYMBOLS

    settings = AppSettings()
    client = _build_kis_live_quote_client(settings)
    if client is None:
        raise SystemExit("KIS live quote client 생성 실패 — KIS_LIVE_INFO_* 확인")
    logger.info("KIS client env=%s", getattr(client, "env", None))

    symbols = sorted(APPROVED_CORE_UNIVERSE_SYMBOLS)
    logger.info("대상 core 종목 수: %d", len(symbols))

    all_samples: list[dict] = []
    per_symbol_bar_counts: dict[str, int] = {}
    fetch_failures: list[str] = []

    for idx, symbol in enumerate(symbols, start=1):
        bars = await _fetch_year_bars(client, symbol, cache_dir=_BARS_CACHE_DIR)
        per_symbol_bar_counts[symbol] = len(bars)
        if len(bars) < _MIN_LOOKBACK + max(FORWARD_HORIZONS) + 5:
            logger.warning("[%d/%d] %s: 표본 부족(%d봉) — 건너뜀", idx, len(symbols), symbol, len(bars))
            fetch_failures.append(symbol)
            continue
        samples = _collect_symbol_samples(symbol, bars)
        all_samples.extend(samples)
        if idx % 10 == 0 or idx == len(symbols):
            logger.info("[%d/%d] 누적 표본 %d건 (최근 %s: %d봉 -> %d표본)",
                        idx, len(symbols), len(all_samples), symbol, len(bars), len(samples))

    logger.info("전체 rolling 표본: %d건 (%d개 종목, 실패 %d개)",
                len(all_samples), len(symbols) - len(fetch_failures), len(fetch_failures))

    report: dict = {
        "as_of": datetime.now(_KST).isoformat(),
        "universe": "core_full_current_survivors",
        "universe_note": (
            "point-in-time(당시 편입·편출 종목) universe는 지수 편입 이력이 "
            "1년 전체를 커버하지 못해(가장 오래된 스냅샷 2026-06-27) 이번 턴에 "
            "시도하지 않았다 — 현재 생존 core 종목만 사용, survivorship bias 존재."
        ),
        "symbol_count_total": len(symbols),
        "symbol_count_used": len(symbols) - len(fetch_failures),
        "fetch_failures": fetch_failures,
        "total_rolling_samples": len(all_samples),
        "round_trip_cost_bps_assumption": _ROUND_TRIP_COST_BPS,
        "by_signal": {},
    }

    for sig in ALL_SIGNALS:
        report["by_signal"][sig] = {}
        for h in FORWARD_HORIZONS:
            overlapping = _cross_sectional_ic_series(all_samples, sig, h, step=1)
            non_overlapping = _cross_sectional_ic_series(all_samples, sig, h, step=h)
            entry = {
                "cross_sectional_overlapping": _summarize_ic_series(overlapping, h),
                "cross_sectional_non_overlapping": _summarize_ic_series(non_overlapping, h),
            }
            if sig in DIRECT_SIGNALS:
                entry["quintile_return_stats"] = _quintile_return_stats(all_samples, sig, h)
            report["by_signal"][sig][f"T+{h}"] = entry

        report["by_signal"][sig]["regime_decomposed_T+5"] = _regime_decomposed_ic(all_samples, sig, 5)

    out_path = "logs/signal_ic_sppv2_expanded_2026-07-14.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n=== SPPV-2 확장 검증 결과 (요약) ===")
    print(f"종목: {report['symbol_count_used']}/{report['symbol_count_total']}, 표본: {report['total_rolling_samples']}")
    for sig in ALL_SIGNALS:
        print(f"\n[{sig}]")
        for h in FORWARD_HORIZONS:
            e = report["by_signal"][sig][f"T+{h}"]["cross_sectional_overlapping"]
            e_no = report["by_signal"][sig][f"T+{h}"]["cross_sectional_non_overlapping"]
            print(
                f"  T+{h}: overlap mean_IC={e.get('mean_ic')} ICIR={e.get('icir')} "
                f"t_NW={e.get('t_newey_west')} ({e.get('strength')}) | "
                f"non-overlap mean_IC={e_no.get('mean_ic')} t_NW={e_no.get('t_newey_west')}"
            )
        regime = report["by_signal"][sig]["regime_decomposed_T+5"]
        print(f"  국면별(T+5) IC: {regime}")

    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
