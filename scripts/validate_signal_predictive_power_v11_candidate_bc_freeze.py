#!/usr/bin/env python3
"""SPPV-3 §36.2 동결 후보 B/C 계산·검증 — 연구용 read-only 스크립트.

``docs/10_signal_research_sppv/[DESIGN] signal_predictive_power_validation.md``
§36.2(후보군 동결)·§36.3(사전 고정 평가 계약)·§37(1차/2차는 독립 표본이
아니라는 정정)을 그대로 구현한다. 후보 A(``regime_switch_v1``)의 기존
구현·수식·R3b 트랙은 이 파일에서 전혀 건드리지 않는다 — 이 파일은
**후보 B/C만** 새로 계산한다.

- B. ``overnight_intraday_split_momentum_v1``
- C. ``low_volatility_rank_20d``

**이 스크립트는 운영 경로가 아니다.** `entry_score`/`deterministic_
trigger`/AI 판단/주문/gate/env/DB 스키마를 전혀 참조하거나 수정하지
않는다. 로컬 bar cache(``logs/_bars_cache_core87_3y_2026-07-14/``)만
읽고, DB write·외부 네트워크·KIS 호출·컨테이너 재기동을 전혀 하지
않는다. cache는 갱신하지 않는다(§37이 명시한 대로, 갱신은 별도 턴에서
사용자 승인 후에만 수행).

기존 파일과의 관계(신규 스크립트를 선택한 이유)
------------------------------------------------
``scripts/validate_signal_predictive_power_v2.py``/``_v4_extended_
period.py``의 순수 집계 함수(``_newey_west_se_of_mean``/``_spearman_
ic``/``_summarize_series``/``_cross_sectional_ic_by_date``/``_quintile_
spread_series``)를 **import해서 그대로 재사용**하고, 그 파일들의 신호
계산 로직·상수·산출 JSON은 전혀 수정하지 않는다 — 과거 historical
validator 결과의 재현성을 훼손하지 않기 위해 "신규 버전 스크립트
생성"을 택했다(공용 함수를 그 파일들에서 추출해 옮기는 리팩터링은
그 파일들의 import 경로를 바꿔 과거 실행 스크립트의 동작을 건드릴
위험이 있어 피했다).

``_rows_to_bars``(v2)는 시가가 없으면 조용히 종가로 대체한다
(``open_ = ... or close``) — 후보 B의 계약("open<=0/결측을 임의
보정하지 말고 결측 사유로 집계")과 맞지 않아 재사용하지 않았다. 이
파일은 대신 결측을 명시적으로 표시하는 자체 로더(``_load_strict_
bars``)를 쓴다. 국면 라벨/후보 C는 종가만으로 계산되는 기존
``build_signal_snapshot``/``classify_market_regime`` 경로를 그대로
재사용한다(그 경로는 ``open_price``를 실제로 쓰지 않음 — ``signal_
backbone.py``의 ``PriceBar.open_price`` 필드는 선언만 있고 어떤
계산에도 사용되지 않는다. 이 파일에서도 그 경로에 넘길 때만 결측
시가를 종가로 채워 넣되, 후보 B 계산에는 이 채움을 절대 쓰지 않는다).

데이터 누수(look-ahead) 방지
-----------------------------
모든 계산은 거래일 인덱스 ``t``에서 ``bars[0..t]``까지만 본다 —
``compute_overnight_intraday_split_momentum()``은 ``bars[t-n:t+1]``만
읽고, 국면/후보 C 계산은 v2/v4와 동일하게 ``window = bars[:t+1]``을
``build_signal_snapshot()``에 넘긴다. 단위 테스트(``test_no_lookahead_
future_bars_do_not_affect_signal_at_t``)가 ``t`` 이후 bar 값을 극단적으로
바꿔도 ``t`` 시점 신호가 변하지 않음을 직접 증명한다.

§36.3/§37 평가 계약 요약
------------------------
- horizon: T+1/T+5/T+20.
- primary metric: 거래일별 cross-sectional Spearman IC → Newey-West
  보정 pooled t-statistic(``_summarize_series``, v2 재사용).
- 보조 지표: hit-rate(``pct_days_positive``), 표본 거래일 수, 비용
  차감 quintile spread(``_quintile_spread_series``, v4 재사용).
- 층화: ``risk_tone``/시장 공통 ``regime_label``(KODEX 200 단독
  스냅샷 기준, §12.2 이후 표준과 동일한 방식으로 이 파일 안에서
  재계산 — v4의 ``_build_benchmark_daily_series``는 ``regime_label``
  만 반환해 ``risk_tone``이 없으므로, 그 함수를 수정하지 않고 이
  파일에 ``risk_tone``까지 함께 뽑는 별도 함수를 새로 둔다).
- 최소 국면 표본: ``MIN_REGIME_TRADING_DAYS = 30``.
- cache cutoff: ``CACHE_AS_OF_DATE = "2026-07-14"``(캐시가 갱신되지
  않는 한 불변)와 스크립트 실행 시각(KST)을 결과 JSON에 항상 기록.
- **1차(최근 12개월)/2차(3년)는 같은 cache의 최근성·장기 국면
  재검증일 뿐 independent out-of-sample 표본이 아니다** — 결과
  JSON의 ``reproducibility_metadata.independence_caveat``에 이
  사실을 항상 명시한다. 진짜 out-of-sample은 cache를 `2026-07-14`
  이후로 갱신한 뒤 이 파일의 수식을 변경 없이 재실행해야만 확보된다
  (이 파일 자신은 그 갱신을 수행하지 않는다).

이 스크립트는 §36.2에서 동결한 수식을 실행 결과와 무관하게 그대로
쓴다 — 실행 결과를 보고 수식/기간/판정 기준을 바꾸지 않는다.
"""

from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
if os.path.join(_REPO_ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

_sys_scripts_path = os.path.join(_REPO_ROOT, "scripts")
if _sys_scripts_path not in sys.path:
    sys.path.insert(0, _sys_scripts_path)

from validate_signal_predictive_power_v2 import (  # noqa: E402
    _MIN_LOOKBACK,
    _newey_west_se_of_mean,  # noqa: F401  (재노출 — 하위 호환/직접 사용 대비)
    _spearman_ic,  # noqa: F401
)
from validate_signal_predictive_power_v4_extended_period import (  # noqa: E402
    BENCHMARK_SYMBOL,
    _cross_sectional_ic_by_date,
    _quintile_spread_series,
    _summarize_series,
)

_KST = timezone(timedelta(hours=9))

# ── §36.3/§37 고정 계약 상수(동결 — 실행 결과를 보고 바꾸지 않음) ───────────
CACHE_AS_OF_DATE = "2026-07-14"
_BARS_CACHE_DIR_3Y = os.path.join(_REPO_ROOT, "logs", "_bars_cache_core87_3y_2026-07-14")
FORWARD_HORIZONS = [1, 5, 20]
CANDIDATE_B_LOOKBACK_DAYS = 5
MIN_REGIME_TRADING_DAYS = 30
PRIMARY_WINDOW_CALENDAR_DAYS = 365  # 1차(최근성 우선) 창, §16.2/§36.3과 동일
_ROUND_TRIP_COST_BPS = 30.0  # v2/v4와 동일 값(§36.3 "동일 계약" 원칙)
FORMULA_VERSION = "sppv3_candidate_bc_v1"


# ── 결측을 임의 보정하지 않는 엄격 bar 로더(후보 B 계약 전용) ────────────────


@dataclass(slots=True, frozen=True)
class StrictBar:
    trade_date: str  # YYYYMMDD
    close: float | None
    open: float | None
    high: float | None
    low: float | None
    open_valid: bool


def _parse_numeric(raw: dict, key: str) -> float | None:
    text = str(raw.get(key, "")).replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def load_strict_bars(symbol: str, cache_dir: str = _BARS_CACHE_DIR_3Y) -> tuple[list[StrictBar], dict[str, int]]:
    """cache JSON을 결측/비정상 값을 임의로 보정하지 않고 그대로 읽는다.

    반환값의 두 번째 항목(``exclusion_counts``)은 로드 단계에서 이미
    확정되는 결측 사유별 건수다:
      - ``close_missing_or_nonpositive``: 그 거래일 자체를 시퀀스에서
        제외한다(종가가 없으면 그 어떤 계산도 point-in-time 시퀀스에
        넣을 수 없다).
      - ``open_missing_or_nonpositive``: 그 거래일은 시퀀스에는 남지만
        (종가 기반 계산·국면 라벨은 가능), ``open_valid=False``로
        표시돼 후보 B 계산에서 그 거래일이 window에 포함되면 명시적으로
        제외된다.
    """
    path = os.path.join(cache_dir, f"{symbol}.json")
    exclusion_counts = {
        "close_missing_or_nonpositive": 0,
        "open_missing_or_nonpositive": 0,
    }
    if not os.path.exists(path):
        return [], exclusion_counts

    with open(path, encoding="utf-8") as f:
        merged: dict[str, dict] = json.load(f)

    bars: list[StrictBar] = []
    for trade_date in sorted(merged.keys()):
        raw = merged[trade_date]
        close = _parse_numeric(raw, "stck_clpr")
        if close is None or close <= 0:
            exclusion_counts["close_missing_or_nonpositive"] += 1
            continue
        open_ = _parse_numeric(raw, "stck_oprc")
        open_valid = open_ is not None and open_ > 0
        if not open_valid:
            exclusion_counts["open_missing_or_nonpositive"] += 1
        high = _parse_numeric(raw, "stck_hgpr")
        low = _parse_numeric(raw, "stck_lwpr")
        bars.append(
            StrictBar(
                trade_date=trade_date,
                close=close,
                open=open_ if open_valid else None,
                high=high,
                low=low,
                open_valid=open_valid,
            )
        )
    return bars, exclusion_counts


# ── 후보 B: overnight_intraday_split_momentum_v1 ───────────────────────────


def compute_overnight_intraday_split_momentum(
    bars: list[StrictBar], t: int, n: int = CANDIDATE_B_LOOKBACK_DAYS
) -> dict[str, Any]:
    """§36.2 동결 수식. ``bars[t-n : t+1]``만 읽는다(미래 미참조).

    - ``overnight_ret_Nd = Σ_{i=1..n} ln(open_i / close_{i-1})``
    - ``intraday_ret_Nd  = Σ_{i=1..n} ln(close_i / open_i)``
    - ``divergence = overnight_ret_Nd - intraday_ret_Nd``(보조 진단값,
      별도 후보로 취급하지 않음 — §36.2 계약)

    두 성분은 합치거나 가중 평균하지 않고 각각 독립적으로 반환한다 —
    호출자가 이 둘을 각자 IC 검증에 쓴다.
    """
    result: dict[str, Any] = {
        "overnight_ret_Nd": None,
        "intraday_ret_Nd": None,
        "divergence": None,
        "exclusion_reason": None,
    }
    start = t - n
    if start < 0:
        result["exclusion_reason"] = "lookback_insufficient"
        return result

    window = bars[start : t + 1]  # n+1개 bar: start..t
    if any(b.close is None or b.close <= 0 for b in window):
        result["exclusion_reason"] = "close_missing_or_nonpositive_in_window"
        return result
    if any(not b.open_valid for b in window[1:]):
        result["exclusion_reason"] = "open_missing_or_nonpositive_in_window"
        return result

    overnight = 0.0
    intraday = 0.0
    for i in range(1, len(window)):
        prev_close = window[i - 1].close
        cur_open = window[i].open
        cur_close = window[i].close
        overnight += math.log(cur_open / prev_close)
        intraday += math.log(cur_close / cur_open)

    result["overnight_ret_Nd"] = overnight
    result["intraday_ret_Nd"] = intraday
    result["divergence"] = overnight - intraday
    return result


# ── 시장 공통 국면/risk_tone(KODEX 200 단독 스냅샷, §12.2 이후 표준) ────────


def build_benchmark_regime_and_risk_tone_by_date(bench_bars: list) -> dict[str, dict[str, str]]:
    """``v4._build_benchmark_daily_series``와 같은 window=bars[:t+1] 규약을
    쓰되, ``regime_label``뿐 아니라 ``risk_tone``까지 함께 뽑는다(v4는
    ``risk_tone``을 버리므로, v4를 수정하지 않고 이 함수를 새로 둔다).
    """
    from agent_trading.services.market_regime import classify_market_regime
    from agent_trading.services.signal_backbone import build_signal_snapshot

    out: dict[str, dict[str, str]] = {}
    last_t = len(bench_bars) - 1 - max(FORWARD_HORIZONS)
    for t in range(_MIN_LOOKBACK - 1, last_t + 1):
        window = bench_bars[: t + 1]
        try:
            features, card = build_signal_snapshot(BENCHMARK_SYMBOL, window)
        except Exception:
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


# ── 후보 C: low_volatility_rank_20d ────────────────────────────────────────


def rank_low_volatility_cross_sectional(
    vol_by_symbol: dict[str, float | None],
) -> tuple[dict[str, float], dict[str, Any]]:
    """그날 표본의 ``volatility_20d_pct``를 오름차순(낮은 변동성 우선)
    순위로 매겨 ``[-1, 1]``로 스케일링한다 — 낮은 변동성일수록 +1에
    가깝다(``relative_strength_rank_1m``, v10의 스케일링 공식을 그대로
    재사용하되 방향만 반전).

    동점 처리 규칙: Python ``sorted()``는 안정 정렬(stable sort)이라
    변동성 값이 완전히 같은 종목들은 **입력 순서**(이 함수에 넘긴
    ``vol_by_symbol``의 키 순서, 호출자가 항상 정렬된 심볼 리스트로
    호출해 결정론적이게 한다)를 그대로 유지한 채 순위가 매겨진다 —
    별도 임의 난수·2차 정렬 기준을 두지 않는다.

    반환값의 두 번째 항목은 그날의 ``valid_symbol_count``/``missing_
    symbol_count``를 담는다.
    """
    valid = [(sym, v) for sym, v in vol_by_symbol.items() if v is not None]
    missing_count = len(vol_by_symbol) - len(valid)
    meta = {
        "valid_symbol_count": len(valid),
        "missing_symbol_count": missing_count,
        "tie_break_rule": "stable_sort_preserves_input_symbol_order",
    }
    scores: dict[str, float] = {}
    n = len(valid)
    if n < 2:
        for sym, _ in valid:
            scores[sym] = 0.0
        return scores, meta

    ordered = sorted(valid, key=lambda pair: pair[1])  # 오름차순: 낮은 변동성이 앞
    for idx, (sym, _) in enumerate(ordered):
        # idx=0(가장 낮은 변동성) -> +1.0, idx=n-1(가장 높은 변동성) -> -1.0
        scores[sym] = ((n - 1 - idx) / (n - 1)) * 2.0 - 1.0
    return scores, meta


# ── 종목별 point-in-time 표본 수집(후보 B/C + forward return + 국면) ────────


def _collect_candidate_samples(
    symbol: str,
    strict_bars: list[StrictBar],
    regime_by_date: dict[str, dict[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """이 종목의 point-in-time 표본을 만든다.

    - 후보 B: ``compute_overnight_intraday_split_momentum`` 그대로 사용
      (StrictBar, 결측 임의 보정 없음).
    - 후보 C 원재료(``volatility_20d_pct``)와 국면 라벨은
      ``build_signal_snapshot``(v2/v4가 이미 쓰는 point-in-time
      window=bars[:t+1] 경로)에서 얻는다 — 이 경로는 ``open_price``를
      실제로 쓰지 않으므로(``signal_backbone.py`` 확인됨), 결측 시가는
      종가로 채워 넣어 넘긴다. **이 채움은 후보 C/국면 계산에만
      쓰이고, 후보 B의 ``open_valid`` 판정에는 전혀 영향을 주지
      않는다**(후보 B는 StrictBar를 직접 읽는다).
    """
    from agent_trading.services.signal_backbone import PriceBar, build_signal_snapshot

    exclusion_counts: dict[str, int] = defaultdict(int)
    price_bars: list[PriceBar] = []
    for b in strict_bars:
        price_bars.append(
            PriceBar(
                timestamp=datetime.strptime(b.trade_date, "%Y%m%d").replace(tzinfo=_KST),
                open_price=b.open if b.open_valid else b.close,  # 후보 C 경로 전용, §위 docstring
                high_price=b.high if b.high is not None else b.close,
                low_price=b.low if b.low is not None else b.close,
                close_price=b.close,
                volume=0.0,
                turnover=None,
            )
        )

    samples: list[dict[str, Any]] = []
    last_t = len(price_bars) - 1 - max(FORWARD_HORIZONS)
    if last_t < _MIN_LOOKBACK - 1:
        return samples, dict(exclusion_counts)

    for t in range(_MIN_LOOKBACK - 1, last_t + 1):
        trade_date_iso = price_bars[t].timestamp.strftime("%Y-%m-%d")

        b_result = compute_overnight_intraday_split_momentum(strict_bars, t, CANDIDATE_B_LOOKBACK_DAYS)
        if b_result["exclusion_reason"] is not None:
            exclusion_counts[f"candidate_b_{b_result['exclusion_reason']}"] += 1

        window = price_bars[: t + 1]
        try:
            features, _card = build_signal_snapshot(symbol, window)
            vol_20d = features.volatility_20d_pct
        except Exception:
            exclusion_counts["candidate_c_signal_snapshot_failed"] += 1
            vol_20d = None

        regime_info = regime_by_date.get(trade_date_iso)
        if regime_info is None:
            exclusion_counts["regime_label_unavailable"] += 1

        row: dict[str, Any] = {
            "symbol": symbol,
            "trade_date": trade_date_iso,
            "overnight_ret_5d": b_result["overnight_ret_Nd"],
            "intraday_ret_5d": b_result["intraday_ret_Nd"],
            "divergence_5d": b_result["divergence"],
            "candidate_b_exclusion_reason": b_result["exclusion_reason"],
            "volatility_20d_pct_raw": vol_20d,
            "common_market_regime": (regime_info or {}).get("regime_label", "unknown"),
            "risk_tone": (regime_info or {}).get("risk_tone", "unknown"),
        }

        base_close = price_bars[t].close_price
        for h in FORWARD_HORIZONS:
            fwd_close = price_bars[t + h].close_price
            raw_ret = (fwd_close / base_close) - 1.0
            row[f"fwd_{h}"] = raw_ret
            row[f"fwd_{h}_net"] = raw_ret - (_ROUND_TRIP_COST_BPS / 10_000.0)

        samples.append(row)

    return samples, dict(exclusion_counts)


def attach_low_volatility_rank(all_samples: list[dict[str, Any]]) -> dict[str, Any]:
    """거래일별로 ``low_volatility_rank_20d``를 부여하고 그날의 유효/결측
    종목 수·동점 규칙을 일별 메타데이터로 남긴다."""
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in all_samples:
        by_date[row["trade_date"]].append(row)

    daily_meta: dict[str, Any] = {}
    for trade_date in sorted(by_date.keys()):
        rows = sorted(by_date[trade_date], key=lambda r: r["symbol"])  # 결정론적 순서 고정
        vol_by_symbol = {r["symbol"]: r["volatility_20d_pct_raw"] for r in rows}
        scores, meta = rank_low_volatility_cross_sectional(vol_by_symbol)
        for r in rows:
            r["low_volatility_rank_20d"] = scores.get(r["symbol"], 0.0)
        daily_meta[trade_date] = meta
    return daily_meta


# ── §36.3 판정 보조: 국면 최소 표본 게이트 ───────────────────────────────────


def regime_sample_gate(all_samples: list[dict[str, Any]]) -> dict[str, Any]:
    """국면별 표본 거래일 수를 세고, ``MIN_REGIME_TRADING_DAYS`` 미달
    국면을 판정 보류 대상으로 명시한다(§20.2/§36.3 규칙 그대로)."""
    dates_by_regime: dict[str, set[str]] = defaultdict(set)
    for row in all_samples:
        dates_by_regime[row["common_market_regime"]].add(row["trade_date"])
    out = {}
    for regime, dates in dates_by_regime.items():
        n = len(dates)
        out[regime] = {
            "trading_day_count": n,
            "meets_min_sample": n >= MIN_REGIME_TRADING_DAYS,
        }
    return out


def summarize_signal_window(
    all_samples: list[dict[str, Any]], signal: str, horizons: list[int]
) -> dict[str, Any]:
    """한 신호(예: ``overnight_ret_5d``)에 대해 horizon별 IC/NW-t/spread를
    요약한다(§36.3 primary/보조 지표, v2/v4 함수 그대로 재사용)."""
    out: dict[str, Any] = {}
    for h in horizons:
        ic_series = _cross_sectional_ic_by_date(all_samples, signal, h, f"fwd_{h}")
        ic_summary = _summarize_series(ic_series, h, is_pct=False)
        spread_series = _quintile_spread_series(all_samples, signal, f"fwd_{h}_net")
        spread_summary = _summarize_series(spread_series, h)
        out[f"T+{h}"] = {"ic": ic_summary, "cost_adjusted_quintile_spread": spread_summary}
    return out


def summarize_by_regime(
    all_samples: list[dict[str, Any]], signal: str, horizons: list[int]
) -> dict[str, Any]:
    gate = regime_sample_gate(all_samples)
    out: dict[str, Any] = {}
    for regime, gate_info in gate.items():
        if not gate_info["meets_min_sample"]:
            out[regime] = {
                "trading_day_count": gate_info["trading_day_count"],
                "verdict": "판정 보류(표본 부족, §20.2/§36.3 규칙)",
            }
            continue
        per_horizon = {}
        for h in horizons:
            ic_series = _cross_sectional_ic_by_date(
                all_samples, signal, h, f"fwd_{h}", common_regime_filter=regime
            )
            per_horizon[f"T+{h}"] = _summarize_series(ic_series, h, is_pct=False)
        out[regime] = {
            "trading_day_count": gate_info["trading_day_count"],
            "ic_by_horizon": per_horizon,
        }
    return out


async def main() -> int:
    query_executed_at_kst = datetime.now(tz=_KST).isoformat()

    bench_strict_bars, _bench_exclusions = load_strict_bars(BENCHMARK_SYMBOL)
    from agent_trading.services.signal_backbone import PriceBar

    bench_price_bars = [
        PriceBar(
            timestamp=datetime.strptime(b.trade_date, "%Y%m%d").replace(tzinfo=_KST),
            open_price=b.open if b.open_valid else b.close,
            high_price=b.high if b.high is not None else b.close,
            low_price=b.low if b.low is not None else b.close,
            close_price=b.close,
            volume=0.0,
            turnover=None,
        )
        for b in bench_strict_bars
    ]
    regime_by_date = build_benchmark_regime_and_risk_tone_by_date(bench_price_bars)

    symbol_files = sorted(
        f[:-5] for f in os.listdir(_BARS_CACHE_DIR_3Y) if f.endswith(".json")
    )

    all_samples: list[dict[str, Any]] = []
    load_exclusions: dict[str, int] = defaultdict(int)
    compute_exclusions: dict[str, int] = defaultdict(int)
    symbols_used = 0

    for symbol in symbol_files:
        if symbol == BENCHMARK_SYMBOL:
            continue  # §12.1의 자기참조 오류 재발 방지 — 벤치마크는 국면 산출 전용
        strict_bars, sym_load_exclusions = load_strict_bars(symbol)
        for k, v in sym_load_exclusions.items():
            load_exclusions[k] += v
        if not strict_bars:
            continue
        samples, sym_compute_exclusions = _collect_candidate_samples(symbol, strict_bars, regime_by_date)
        for k, v in sym_compute_exclusions.items():
            compute_exclusions[k] += v
        if samples:
            symbols_used += 1
            all_samples.extend(samples)

    daily_rank_meta = attach_low_volatility_rank(all_samples)

    trade_dates = sorted({row["trade_date"] for row in all_samples})
    as_of = datetime.strptime(CACHE_AS_OF_DATE, "%Y-%m-%d")
    primary_cutoff = (as_of - timedelta(days=PRIMARY_WINDOW_CALENDAR_DAYS)).strftime("%Y-%m-%d")
    primary_samples = [row for row in all_samples if row["trade_date"] >= primary_cutoff]

    result = {
        "reproducibility_metadata": {
            "candidate_freeze_reference": (
                "docs/10_signal_research_sppv/[DESIGN] "
                "signal_predictive_power_validation.md §36.2/§36.3/§37"
            ),
            "formula_version": FORMULA_VERSION,
            "cache_as_of_date": CACHE_AS_OF_DATE,
            "cache_path": _BARS_CACHE_DIR_3Y,
            "script_execution_time_kst": query_executed_at_kst,
            "symbol_count_used": symbols_used,
            "trading_day_count": len(trade_dates),
            "trading_day_range": {
                "min": trade_dates[0] if trade_dates else None,
                "max": trade_dates[-1] if trade_dates else None,
            },
            "primary_window_calendar_days": PRIMARY_WINDOW_CALENDAR_DAYS,
            "min_regime_trading_days": MIN_REGIME_TRADING_DAYS,
            "load_exclusion_counts": dict(load_exclusions),
            "compute_exclusion_counts": dict(compute_exclusions),
            "independence_caveat": (
                "1차(최근 12개월)와 2차(3년, 아래 secondary_window_full_"
                "cache) 결과는 같은 정적 cache 하나에서 나온 최근성·장기 "
                "국면 재검증이다 — 1차는 2차의 부분집합이며 서로 독립된 "
                "out-of-sample 표본이 아니다(§37). 진짜 independent "
                "out-of-sample 검증은 이 cache를 2026-07-14 이후 거래일까지 "
                "갱신한 뒤, 이 파일의 수식을 한 글자도 바꾸지 않고 그 신규 "
                "구간에만 재실행해야 확보된다 — 이 스크립트 자신은 그 "
                "갱신을 수행하지 않는다."
            ),
        },
        "candidate_b_overnight_intraday_split_momentum_v1": {
            "primary_window_recent_12m": {
                "overnight_ret_5d": summarize_signal_window(primary_samples, "overnight_ret_5d", FORWARD_HORIZONS),
                "intraday_ret_5d": summarize_signal_window(primary_samples, "intraday_ret_5d", FORWARD_HORIZONS),
            },
            "secondary_window_full_cache": {
                "overnight_ret_5d": summarize_signal_window(all_samples, "overnight_ret_5d", FORWARD_HORIZONS),
                "intraday_ret_5d": summarize_signal_window(all_samples, "intraday_ret_5d", FORWARD_HORIZONS),
                "by_regime": {
                    "overnight_ret_5d": summarize_by_regime(all_samples, "overnight_ret_5d", FORWARD_HORIZONS),
                    "intraday_ret_5d": summarize_by_regime(all_samples, "intraday_ret_5d", FORWARD_HORIZONS),
                },
            },
        },
        "candidate_c_low_volatility_rank_20d": {
            "primary_window_recent_12m": summarize_signal_window(
                primary_samples, "low_volatility_rank_20d", FORWARD_HORIZONS
            ),
            "secondary_window_full_cache": {
                "summary": summarize_signal_window(all_samples, "low_volatility_rank_20d", FORWARD_HORIZONS),
                "by_regime": summarize_by_regime(all_samples, "low_volatility_rank_20d", FORWARD_HORIZONS),
            },
            "daily_rank_metadata_sample": dict(list(daily_rank_meta.items())[:5]),
        },
        "regime_sample_gate": regime_sample_gate(all_samples),
    }

    print(json.dumps(result["reproducibility_metadata"], ensure_ascii=False, indent=2))

    output_path = os.path.join(
        _REPO_ROOT, "logs", f"signal_ic_sppv3_candidate_bc_freeze_{CACHE_AS_OF_DATE}.json"
    )
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[출력] 결과 JSON 저장: {output_path}")
    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
