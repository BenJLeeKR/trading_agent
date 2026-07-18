"""국면 혼합도(regime mixedness) 모니터링 — 순수 판정 함수, read-only.

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §40(SPPV-2.50)
이 확인한 "혼합 국면 약세" 강한 구조적 정합 증거를, §40.5/§40.7이
"다음 단계"로 남긴 대로 **실제로 소비 가능한 모니터링 primitive**로
전환한다(SPPV-2.62).

§40이 3년 전체 634거래일에서 확인한 것: 최근 60거래일 창의 시장
공통 국면 분포에서 `mixed_score = 1 - (최빈 라벨 비중)`을 계산해
3분위(저/중/고혼합)로 나누면, 고혼합 구간에서 T+20 t_NW가 0.37(사실상
0과 구분 불가능)까지 떨어진다 — 저혼합 구간(t_NW=3.64)과 질적으로
다른 상태다. 이 모듈은 그 3분위 경계값을 그대로 재사용해, **매일의
mixed_score를 이 3개 버킷 중 하나로 분류하고 신뢰도 caveat을
reason_code로 남기는** 순수 함수를 제공한다.

**이 모듈은 BUY/SELL 판정을 막지 않는다** — §40.5가 이미 "이 발견은
SPPV-3 착수를 추가로 차단하는 사유가 아니라 운영상 모니터링
지표"라고 명시했으므로, 이 모듈은 `regime_switch_gate.py`처럼 실제
게이트로 파이프라인에 연결하지 않는다. 순수하게 **관측·로깅용
분류기**다 — 신뢰도가 낮은 시기를 사람이 인지할 수 있게 표시하는
용도다.

DB write / 주문 경로 / 실시간 구독 / broker submit 없음.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

# §40(SPPV-2.50)이 3년 634거래일 전체 표본에서 확정한 3분위 경계값
# 그대로 재사용한다(신규 재추정 없음 — 기존 실측 결과를 그대로 상수화).
MIXEDNESS_TERCILE_CUT1 = 0.1500
MIXEDNESS_TERCILE_CUT2 = 0.3833

MIXEDNESS_WINDOW_TRADING_DAYS = 60
"""§40과 동일한 trailing window 길이(약 1분기)."""

BUCKET_LOW = "저혼합(단일 국면 지배)"
BUCKET_MID = "중혼합"
BUCKET_HIGH = "고혼합"

REASON_MIXEDNESS_LOW_HIGH_CONFIDENCE = "mixedness_low_bucket_high_confidence"
"""§40 기준: 저혼합 구간은 T+20 t_NW=3.64(강한 유의성) — 신뢰도 caveat 없음."""

REASON_MIXEDNESS_MID_MODERATE_CONFIDENCE = "mixedness_mid_bucket_moderate_confidence"
"""§40 기준: 중혼합 구간은 T+20 t_NW=2.51(통상 유의 수준) — 신뢰도 보통."""

REASON_MIXEDNESS_HIGH_LOW_CONFIDENCE = "mixedness_high_bucket_low_confidence_caveat"
"""§40 기준: 고혼합 구간은 T+20 t_NW=0.37(0과 구분 불가) — 이 구간에서는
신호의 통계적 신뢰도가 사실상 사라진다는 것이 §40에서 확정됐다. 이
reason_code는 그 caveat을 운영 로그/diagnostics에 남기기 위한 것이다."""


@dataclass(slots=True, frozen=True)
class MixednessAssessment:
    """국면 혼합도 판정 결과 — 순수 관측/로깅용, BUY/SELL을 막지 않는다."""

    mixed_score: float
    bucket: str
    reason_code: str


def compute_mixed_score(
    trailing_labels: list[str],
    *,
    min_window: int = 20,
) -> float | None:
    """최근 거래일들의 시장 공통 국면 라벨 리스트(가장 최근이 마지막
    원소)에서 `mixed_score = 1 - (최빈 라벨 비중)`을 계산한다.

    §40과 동일한 정의 — `trailing_labels`가 `MIXEDNESS_WINDOW_TRADING_
    DAYS`보다 짧으면 있는 만큼만 쓰되, `min_window`(기본 20일) 미만이면
    계산하지 않고 `None`을 반환한다(§40의 "20일 미만 skip" 규칙과 동일).
    """
    window = trailing_labels[-MIXEDNESS_WINDOW_TRADING_DAYS:]
    if len(window) < min_window:
        return None
    counts = Counter(window)
    max_share = max(counts.values()) / len(window)
    return round(1.0 - max_share, 4)


def classify_mixedness_bucket(mixed_score: float) -> MixednessAssessment:
    """§40이 확정한 3분위 경계값으로 `mixed_score`를 분류한다 — 순수
    함수, BUY/SELL 판정에 영향을 주지 않는다(관측/로깅 전용)."""
    if mixed_score <= MIXEDNESS_TERCILE_CUT1:
        return MixednessAssessment(
            mixed_score=mixed_score,
            bucket=BUCKET_LOW,
            reason_code=REASON_MIXEDNESS_LOW_HIGH_CONFIDENCE,
        )
    if mixed_score <= MIXEDNESS_TERCILE_CUT2:
        return MixednessAssessment(
            mixed_score=mixed_score,
            bucket=BUCKET_MID,
            reason_code=REASON_MIXEDNESS_MID_MODERATE_CONFIDENCE,
        )
    return MixednessAssessment(
        mixed_score=mixed_score,
        bucket=BUCKET_HIGH,
        reason_code=REASON_MIXEDNESS_HIGH_LOW_CONFIDENCE,
    )
