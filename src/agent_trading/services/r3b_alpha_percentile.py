"""R3b alpha(candidate_percentile) — cycle 단위 cross-sectional 사전 계산.

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §54(SPPV-2.65)가
발견한 아키텍처 제약(entry_score는 종목 단위 계산이지만 R3b alpha는
당일 cross-sectional 순위가 필요)을 해소하는 §54.5의 "2단계" 구현이다
(SPPV-2.67).

이 세션의 모든 R3b shadow 스크립트(예:
``scripts/validate_r3b_point_in_time_pipeline_shadow.py``)가 반복
사용해 온 로직을 그대로 이식했다 — 신규 알고리즘 발명 없음:

1. 시장 공통 국면 라벨(``market_common_label``)이 ``bullish_trend``
   또는 ``range_bound``이면 ``regime_conditional_signal =
   return_3m_pct / max(volatility_20d_pct, 1.0)``(risk-adjusted
   3개월 모멘텀), ``bearish_trend``이면 ``regime_conditional_signal =
   -return_1m_pct``(1개월 역추세) — 그 외 라벨/결측이면 ``None``.
2. 당일 ``regime_conditional_signal``이 not-None인 종목을 내림차순
   정렬해 상위 20%(quintile)를 candidate pool로 선정.
3. candidate pool 내부에서만 오름차순 percentile(0~1)을 부여한다.

**이 모듈은 BUY/SELL 판정에 아직 연결되지 않는다** — 순수 계산
함수만 제공하며, 실제로 ``deterministic_trigger_engine.py``의
``r3b_alpha_percentile``/``r3b_alpha_enabled`` 파라미터에 주입하는
배선은 이 모듈을 사용하는 별도의 cycle precompute 호출부(§54.5의
"신규 cycle당 1회 precompute 함수")가 담당한다 — 그 호출부 자체는
``AppSettings.entry_score_r3b_alpha_enabled``(기본값 False)로만
활성화되므로, 이 모듈이 존재하는 것만으로는 기존 동작에 영향이 없다.

DB write / 주문 경로 / 실시간 구독 / broker submit 없음.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

TOP_QUINTILE_FRACTION = 0.20
"""shadow 스크립트와 동일한 상위 20% candidate pool 기준(신규 재추정 없음)."""

_BULLISH_OR_RANGE_LABELS = frozenset({"bullish_trend", "range_bound"})
_BEARISH_LABEL = "bearish_trend"


@dataclass(frozen=True)
class R3bAlphaInput:
    """cycle precompute 호출부가 종목별로 채워 전달하는 입력값."""

    symbol: str
    market_common_label: str | None
    return_1m_pct: float | None
    return_3m_pct: float | None
    volatility_20d_pct: float | None


def compute_regime_conditional_signal(item: R3bAlphaInput) -> float | None:
    """shadow 스크립트의 ``regime_conditional_signal`` 산출 로직 그대로."""
    if item.market_common_label in _BULLISH_OR_RANGE_LABELS:
        if item.return_3m_pct is None or item.volatility_20d_pct is None:
            return None
        return item.return_3m_pct / max(item.volatility_20d_pct, 1.0)
    if item.market_common_label == _BEARISH_LABEL:
        if item.return_1m_pct is None:
            return None
        return -item.return_1m_pct
    return None


def build_candidate_percentiles(
    items: list[R3bAlphaInput],
) -> dict[str, float]:
    """당일 universe 전체에서 상위 20% candidate에만 percentile을 부여한다.

    반환값은 ``{symbol: candidate_percentile}`` — candidate pool 밖의
    종목/신호 결측 종목은 키 자체가 없다(shadow 스크립트의 ``None``
    처리와 동일하게, 호출부는 ``.get(symbol)``로 조회해야 한다).
    """
    signals_by_symbol: dict[str, float] = {}
    for item in items:
        signal = compute_regime_conditional_signal(item)
        if signal is not None:
            signals_by_symbol[item.symbol] = signal

    if len(signals_by_symbol) < 5:
        return {}

    ordered = sorted(signals_by_symbol.items(), key=lambda kv: kv[1], reverse=True)
    q = max(1, int(len(ordered) * TOP_QUINTILE_FRACTION))
    day_candidates = ordered[:q]
    cand_signals = sorted(value for _, value in day_candidates)
    n = len(cand_signals)

    percentiles: dict[str, float] = {}
    for symbol, signal in day_candidates:
        idx = bisect.bisect_left(cand_signals, signal)
        percentiles[symbol] = idx / (n - 1) if n > 1 else 0.5
    return percentiles
