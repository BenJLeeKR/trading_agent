"""Risk metric status codes and error note message constants.

이 모듈은 Sharpe / Sortino / Calmar Ratio의 상태 코드와
계산 불가(Error path) 시 설명 메시지를 공통 상수로 정의합니다.

사용 규칙
---------
- ``RiskMetricStatus`` 는 **내부 코드에서만 enum 자체로 사용**합니다.
- 외부 API/DB serialization 시에는 ``.value`` (기존 문자열)를 사용합니다.
- Error note 상수는 Performance API note 와 Gate WARN message 가
  동일한 문자열을 참조하도록 보장합니다 (semantic drift 방지).
- PASS / threshold 미달 / display-only 메시지는 공통화 대상이 아니므로
  각 계층(performance_summary, paper_gate, evaluate_live_gate)이
  별도로 관리합니다.
"""

from __future__ import annotations

from enum import Enum
from typing import Final


class RiskMetricStatus(str, Enum):
    """Risk-adjusted metric 상태 코드 (3개 계층 공용, 내부 전용).

    외부 API/DB serialization 시에는 ``.value`` (기존 문자열)를 사용하세요.
    """

    OK = "ok"
    INSUFFICIENT_DATA = "insufficient_data"
    INSUFFICIENT_DOWNSIDE_SAMPLES = "insufficient_downside_samples"
    ZERO_VARIANCE = "zero_variance"
    ZERO_DRAWDOWN = "zero_drawdown"


# ── Error Note Templates (error path only commonization) ──
# Performance API note와 Gate WARN message가 동일 상수 공유.
# PASS / threshold 미달 / display-only message는 각 계층이 별도 관리.
# fmt: off

# Sharpe: 일별 수익률 < 2개
SHARPE_INSUFFICIENT_DATA_NOTE: Final[str] = (
    "일별 수익률 표본 부족으로 Sharpe Ratio를 계산할 수 없습니다"
)

# Sharpe: stddev == 0 (모든 수익률 동일)
SHARPE_ZERO_VARIANCE_NOTE: Final[str] = (
    "일별 수익률 변동성이 0이어서 Sharpe Ratio를 계산할 수 없습니다"
)

# Sortino: 일별 수익률 < 2개 (기본 표본 부족)
SORTINO_INSUFFICIENT_DATA_NOTE: Final[str] = (
    "일별 수익률 표본 부족으로 Sortino Ratio를 계산할 수 없습니다"
)

# Sortino: 음수 수익률 표본 < 2개 (Sortino 특화)
SORTINO_INSUFFICIENT_DOWNSIDE_NOTE: Final[str] = (
    "음수 수익률 표본 부족으로 Sortino Ratio를 계산할 수 없습니다"
)

# Sortino: downside_dev == 0 (음수 수익률 존재하나 변동 없음)
SORTINO_ZERO_VARIANCE_NOTE: Final[str] = (
    "하방 변동성이 0이어서 Sortino Ratio를 계산할 수 없습니다"
)

# Calmar: max_drawdown_pct == 0
CALMAR_ZERO_DRAWDOWN_NOTE: Final[str] = (
    "최대 손실 폭이 0이어서 Calmar Ratio를 계산할 수 없습니다"
)

# fmt: on


class GateReasonCode(str, Enum):
    """Gate/policy check 결과의 machine-readable 원인 코드.

    ``reason_code`` 의 vocabulary를 제공합니다.
    WARN/FAIL인 check에만 설정하고, PASS인 check는 ``None`` 을 유지합니다.

    사용 규칙
    ---------
    - WARN/FAIL check: 반드시 이유를 설명하는 ``reason_code`` 를 설정합니다.
    - PASS check: ``reason_code=None`` 을 유지합니다 (별도 enum 값 없음).
    - 예외: ``DISPLAY_ONLY`` 는 PASS지만 정보 표시 전용임을 나타내기 위해 설정합니다.
    - 네이밍: ``snake_case`` 만 사용합니다.
    - ``RiskMetricStatus`` 와 동일한 문자열(insufficient_data 등)을 재사용하지만,
      역할은 다릅니다 (RiskMetricStatus=metric 계산 상태, GateReasonCode=gate 결과 원인).
    """

    # ── WARN/FAIL 계열 ──
    METRIC_BELOW_THRESHOLD = "metric_below_threshold"
    METRIC_UNAVAILABLE = "metric_unavailable"
    INSUFFICIENT_DATA = "insufficient_data"
    INSUFFICIENT_DOWNSIDE_SAMPLES = "insufficient_downside_samples"
    ZERO_DRAWDOWN = "zero_drawdown"
    SNAPSHOT_STALE = "snapshot_stale"
    BLOCKING_LOCK_PRESENT = "blocking_lock_present"
    BENCHMARK_UNAVAILABLE = "benchmark_unavailable"
    BENCHMARK_CODE_MISSING = "benchmark_code_missing"
    EXCESSIVE_SYNC_FAILURES = "excessive_sync_failures"
    EXCESSIVE_RECONCILE_REQUIRED = "excessive_reconcile_required"
    HEALTH_UNAVAILABLE = "health_unavailable"
    SYNC_FAILURE = "sync_failure"

    # ── 정보 표시 전용 (PASS지만 의미 있는 예외) ──
    DISPLAY_ONLY = "display_only"
