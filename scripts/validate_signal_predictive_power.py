#!/usr/bin/env python3
"""신호 예측력 실증 검증 (Signal Predictive Power / IC) — read-only 파일럿.

``[DESIGN] signal_predictive_power_validation_2026-07-14.md`` 참고.

slow_momentum/slow_trend/slow_score/fast_score/overall_score 가 실제 미래
수익률(T+1/T+3/T+5)을 예측하는지를, 과거 약 1년 일봉으로 rolling 재계산해
Spearman 순위상관(IC)으로 측정한다.

- 운영 코드 ``build_signal_snapshot``(순수 함수)를 그대로 재사용 — 검증용
  별도 신호 로직을 만들지 않는다.
- DB write / 주문 / 실시간 구독 없음. KIS 과거 일봉 조회(read)만 수행.
- numpy/scipy 미설치 환경이라 순위상관은 순수 파이썬으로 구현.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from math import sqrt

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_signal_predictive_power")

_KST = timezone(timedelta(hours=9))

# 파일럿 대상 — core 대형주 8종목(다양한 섹터)
PILOT_SYMBOLS: list[tuple[str, str]] = [
    ("005930", "삼성전자"),
    ("000660", "SK하이닉스"),
    ("035420", "NAVER"),
    ("005380", "현대차"),
    ("000270", "기아"),
    ("068270", "셀트리온"),
    ("207940", "삼성바이오로직스"),
    ("105560", "KB금융"),
]

# 측정할 신호 목록 — SignalScoreCard 직속 필드 + component_scores 키
DIRECT_SIGNALS = ["slow_score", "fast_score", "overall_score"]
COMPONENT_SIGNALS = ["slow_momentum", "slow_trend"]
FORWARD_HORIZONS = [1, 3, 5]

_MIN_LOOKBACK = 61  # signal_backbone: SMA60/return_3m 온전 계산에 필요한 최소 봉 수


# ── Spearman 순위상관 (순수 파이썬) ──────────────────────────────────────────


def _rank(values: list[float]) -> list[float]:
    """평균순위 방식으로 tie를 처리한 순위 벡터."""
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


def _t_stat(ic: float, n: int) -> float | None:
    if n < 3 or abs(ic) >= 1.0:
        return None
    return ic * sqrt((n - 2) / (1.0 - ic * ic))


def _strength_label(ic: float) -> str:
    a = abs(ic)
    if a < 0.02:
        return "없음(노이즈)"
    if a < 0.05:
        return "미약"
    if a < 0.10:
        return "유의미"
    return "강함"


# ── KIS 일봉 페처 (과거 1년, 슬라이딩 병합) ──────────────────────────────────


async def _fetch_year_bars(client, symbol: str):
    """과거 약 1년치 일봉을 100일 제한 회피용 슬라이딩 조회로 병합한다."""
    from agent_trading.services.signal_backbone import PriceBar

    end = datetime.now(_KST).date()
    start = end - timedelta(days=400)  # 거래일 ~245 확보 위해 캘린더 400일

    merged: dict[str, dict] = {}
    window_start = start
    while window_start < end:
        window_end = min(window_start + timedelta(days=110), end)
        raw_rows = await client.inquire_daily_itemchartprice(
            symbol=symbol,
            market_code="J",
            start_date=window_start.strftime("%Y%m%d"),
            end_date=window_end.strftime("%Y%m%d"),
            period_div_code="D",
            adjusted_price=True,
        )
        for raw in raw_rows:
            d = str(raw.get("stck_bsop_date", "")).strip()
            if d:
                merged[d] = raw
        await asyncio.sleep(0.3)  # rate budget 보호
        window_start = window_end + timedelta(days=1)

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


# ── Rolling 신호 재계산 + forward return 수집 ────────────────────────────────


def _collect_pairs(symbol: str, bars) -> dict:
    """각 거래일 T의 신호값과 T+h forward return 쌍을 수집한다."""
    from agent_trading.services.signal_backbone import build_signal_snapshot

    # signal_key -> list[float], horizon -> list[float] (인덱스 정렬 동일)
    samples: list[dict] = []
    last_t = len(bars) - 1 - max(FORWARD_HORIZONS)
    for t in range(_MIN_LOOKBACK - 1, last_t + 1):
        window = bars[: t + 1]
        try:
            _features, card = build_signal_snapshot(symbol, window)
        except Exception:
            continue
        row: dict = {}
        for s in DIRECT_SIGNALS:
            row[s] = float(getattr(card, s))
        for s in COMPONENT_SIGNALS:
            if s in card.component_scores:
                row[s] = float(card.component_scores[s])
        base_close = bars[t].close_price
        for h in FORWARD_HORIZONS:
            fwd_close = bars[t + h].close_price
            row[f"fwd_{h}"] = (fwd_close / base_close) - 1.0
        samples.append(row)
    return {"symbol": symbol, "samples": samples}


# ── 집계 ────────────────────────────────────────────────────────────────────


def _aggregate_ic(all_samples: list[dict]) -> dict:
    """전 종목 표본을 합쳐 신호별×horizon별 Spearman IC를 계산한다."""
    pooled: list[dict] = []
    for entry in all_samples:
        pooled.extend(entry["samples"])

    result: dict = {"total_samples": len(pooled), "by_signal": {}}
    signals = DIRECT_SIGNALS + COMPONENT_SIGNALS
    for sig in signals:
        result["by_signal"][sig] = {}
        for h in FORWARD_HORIZONS:
            xs: list[float] = []
            ys: list[float] = []
            for row in pooled:
                if sig in row and f"fwd_{h}" in row:
                    xs.append(row[sig])
                    ys.append(row[f"fwd_{h}"])
            ic = _spearman_ic(xs, ys)
            if ic is None:
                result["by_signal"][sig][f"T+{h}"] = {"n": len(xs), "ic": None}
            else:
                result["by_signal"][sig][f"T+{h}"] = {
                    "n": len(xs),
                    "ic": round(ic, 4),
                    "t_stat": round(_t_stat(ic, len(xs)) or 0.0, 2),
                    "strength": _strength_label(ic),
                }
    return result


async def main() -> None:
    from agent_trading.config.settings import AppSettings
    from agent_trading.runtime.bootstrap import _build_kis_live_quote_client

    settings = AppSettings()
    client = _build_kis_live_quote_client(settings)
    if client is None:
        raise SystemExit("KIS live quote client 생성 실패 — KIS_LIVE_INFO_* 확인")
    logger.info("KIS client env=%s", getattr(client, "env", None))

    all_samples: list[dict] = []
    per_symbol_bar_counts: dict[str, int] = {}
    for symbol, name in PILOT_SYMBOLS:
        bars = await _fetch_year_bars(client, symbol)
        per_symbol_bar_counts[f"{symbol}({name})"] = len(bars)
        logger.info("%s(%s): 일봉 %d개 확보", symbol, name, len(bars))
        if len(bars) < _MIN_LOOKBACK + max(FORWARD_HORIZONS) + 5:
            logger.warning("%s: 표본 부족(%d봉) — 건너뜀", symbol, len(bars))
            continue
        entry = _collect_pairs(symbol, bars)
        logger.info("%s: rolling 표본 %d개", symbol, len(entry["samples"]))
        all_samples.append(entry)

    report = _aggregate_ic(all_samples)
    report["per_symbol_bar_counts"] = per_symbol_bar_counts
    report["as_of"] = datetime.now(_KST).isoformat()

    print("\n=== 신호 예측력 IC 파일럿 결과 ===")
    print(f"총 표본 수: {report['total_samples']}")
    for sig, horizons in report["by_signal"].items():
        print(f"\n[{sig}]")
        for h, v in horizons.items():
            if v.get("ic") is None:
                print(f"  {h}: N={v['n']} IC=계산불가")
            else:
                print(
                    f"  {h}: N={v['n']} IC={v['ic']:+.4f} "
                    f"t={v.get('t_stat')} → {v.get('strength')}"
                )

    out_path = "logs/signal_ic_pilot_2026-07-14.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
