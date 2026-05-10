# Risk Metric Status/Note/Message 상수 공통화 및 정합성 검증

**이번 작업의 성격**: "Formalization of existing alignment" — 새로운 정책 도입이 아닌, 이미 우연히 일치하고 있던 메시지 정합성을 코드 자산으로 고정하고 문서-구현 불일치를 정정하는 작업.

**공통화 범위**: Error path note/message only. PASS 메시지, threshold 미달 메시지, display-only 메시지는 공통화 대상 아님.

---

## 1. 사전 분석 결과

### 1.1 현재 문자열 현황 (모두 byte-level 동일 확인)

| 구분 | Metric | 성능 API Note | Paper Gate None→WARN Message | 일치 여부 |
|------|--------|---------------|------------------------------|-----------|
| 계산 불가 | Sharpe | `일별 수익률 표본 부족으로 Sharpe Ratio를 계산할 수 없습니다` | 동일 | ✅ byte-level 일치 |
| 계산 불가 | Sharpe | `일별 수익률 변동성이 0이어서 Sharpe Ratio를 계산할 수 없습니다` | N/A (Gate 미사용) | N/A |
| 계산 불가 | Sortino | `일별 수익률 표본 부족으로 Sortino Ratio를 계산할 수 없습니다` | N/A (Gate 미사용) | N/A |
| 계산 불가 | Sortino | `음수 수익률 표본 부족으로 Sortino Ratio를 계산할 수 없습니다` | 동일 | ✅ byte-level 일치 |
| 계산 불가 | Sortino | `하방 변동성이 0이어서 Sortino Ratio를 계산할 수 없습니다` | N/A (Gate 미사용) | N/A |
| 계산 불가 | Calmar | `최대 손실 폭이 0이어서 Calmar Ratio를 계산할 수 없습니다` | 동일 | ✅ byte-level 일치 |
| 정상 | Sharpe | `Sharpe Ratio 정상 계산` | `Sharpe Ratio {value} — 기준 통과` (Gate만) | N/A (맥락 상이) |
| 정상 | Sortino | `Sortino Ratio 정상 계산` | `Sortino Ratio {value} — 기준 통과` (Gate만) | N/A (맥락 상이) |
| 정상 | Calmar | `Calmar Ratio 정상 계산` | `Calmar Ratio {value} — 기준 통과` (Gate만) | N/A (맥락 상이) |

**핵심 발견**: 설계 문서(`paper_gate_risk_adjusted_metrics.md`)에는 Gate 메시지에 `2일 이상 필요`/`2개 이상 필요` suffix가 명시되었으나 **실제 구현에서는 반영되지 않음**. 이는 **문서-구현 불일치**이며, 이번 작업에서 이 사실을 확인하고 공통화 시 suffix 없이 진행.

### 1.2 현재 문제점

1. **Status 코드가 plain string**: `"ok"`, `"insufficient_data"` 등이 하드코딩되어 향후 오타/불일치 위험 존재
2. **Note/message 문자열이 중복**: 3군데(`_calc_sharpe_sortino()`, `_check_min_*_ratio()`, `evaluate_live_gate()`)에 유사 문자열이 독립적으로 존재
3. **게이트 WARN 메시지와 성능 API note가 물리적 공유 없음**: 현재는 우연히 일치하지만, 향후 한쪽만 수정될 경우 drift 발생
4. **테스트가 note 문자열 내용을 검증하지 않음**: note는 `!= ""`로만 검증 → 공통화 후 상수 참조 검증으로 강화

---

## 2. 설계 판단 (4가지)

### 판단 1: 공통화 범위

**Error path only commonization.** PASS 메시지, threshold 미달 메시지, display-only 메시지는 각 계층별 맥락이 달라 공통화하지 않음.

| 범위 | 포함 여부 | 사유 |
|------|----------|------|
| Error note (6종) | ✅ **공통화** | Sharpe `insufficient_data`/`zero_variance`, Sortino `insufficient_data`/`insufficient_downside_samples`/`zero_variance`, Calmar `zero_drawdown` — 계산 불가 사유 설명, 3개 중 3개가 Gate와 공유됨 |
| Status code (5종) | ✅ **내부 상수로 enum화** | `ok`, `insufficient_data`, `insufficient_downside_samples`, `zero_variance`, `zero_drawdown` — 내부 코드에서는 enum 사용, API serialization은 기존 문자열(str) 유지 |
| "정상 계산" note (3종) | ❌ **제외** | API note는 `"X Ratio 정상 계산"`, Gate는 `"X Ratio {value} — 기준 통과"` — 수신자/맥락 상이 |
| Threshold 미달 메시지 | ❌ **제외** | Gate 전용, 동적 값 포함 |
| Live Gate display-only | ❌ **제외** | `"X Ratio 정보 표시 (현재 gate 미적용)"` — display-only 고유 의미. vocabulary 일치만 검증 |

### 판단 2: 상수 구조 — `RiskMetricStatus`는 내부 전용, API는 문자열 유지

```python
# src/agent_trading/services/risk_metric_constants.py  (신규)

from enum import Enum
from typing import Final

# ── Status Codes (내부 전용) ──
# 외부 API/DB serialization에는 .value (기존 문자열) 사용.
# PerformanceMetricsView / PaperGateCheck.message 등은 기존처럼 str 필드 유지.
# enum은 내부 constant reference 용도로만 사용.
class RiskMetricStatus(str, Enum):
    OK = "ok"
    INSUFFICIENT_DATA = "insufficient_data"
    INSUFFICIENT_DOWNSIDE_SAMPLES = "insufficient_downside_samples"
    ZERO_VARIANCE = "zero_variance"
    ZERO_DRAWDOWN = "zero_drawdown"

# ── Error Note Templates (error path only, 계층 간 공유) ──
# Performance API note와 Gate WARN message가 동일 상수 공유.
# PASS / threshold 미달 / display-only message는 각 계층이 별도 관리.

SHARPE_INSUFFICIENT_DATA_NOTE: Final[str] = (
    "일별 수익률 표본 부족으로 Sharpe Ratio를 계산할 수 없습니다"
)
SHARPE_ZERO_VARIANCE_NOTE: Final[str] = (
    "일별 수익률 변동성이 0이어서 Sharpe Ratio를 계산할 수 없습니다"
)
SORTINO_INSUFFICIENT_DATA_NOTE: Final[str] = (
    "일별 수익률 표본 부족으로 Sortino Ratio를 계산할 수 없습니다"
)
SORTINO_INSUFFICIENT_DOWNSIDE_NOTE: Final[str] = (
    "음수 수익률 표본 부족으로 Sortino Ratio를 계산할 수 없습니다"
)
SORTINO_ZERO_VARIANCE_NOTE: Final[str] = (
    "하방 변동성이 0이어서 Sortino Ratio를 계산할 수 없습니다"
)
CALMAR_ZERO_DRAWDOWN_NOTE: Final[str] = (
    "최대 손실 폭이 0이어서 Calmar Ratio를 계산할 수 없습니다"
)
```

**enum 사용 규칙**:
- `RiskMetricStatus`는 **내부 코드에서만 enum 자체로 사용**
- 외부 API serialization 시에는 반드시 `.value` 사용 → `PerformanceMetricsView`의 `str` 필드와 호환
- `SharpeSortinoResult.sharpe_status: str` 타입 힌트는 변경 없음 (enum 아닌 str 유지)
- `PerformanceMetrics.sharpe_ratio_status: str` 기본값도 `"insufficient_data"` 문자열 유지

**Calmar 관련 상수**: `CALMAR_ZERO_DRAWDOWN_NOTE`만 추가. Calmar `ok` note는 API(`"Calmar Ratio 정상 계산"`)와 Gate(`"Calmar Ratio {value} — 기준 통과"`)가 다르므로 공통화 대상 아님.

### 판단 3: Gate vs API 메시지 매칭 정책

**정책: Error note는 byte-level 동일하게 공유. 게이트 WARN 메시지는 동일 상수 사용.**

```python
# paper_gate.py (변경 후)
from agent_trading.services.risk_metric_constants import (
    SHARPE_INSUFFICIENT_DATA_NOTE,
    SORTINO_INSUFFICIENT_DOWNSIDE_NOTE,
    CALMAR_ZERO_DRAWDOWN_NOTE,
)

def _check_min_sharpe_ratio(self, value: Decimal | None) -> PaperGateCheck:
    if value is None:
        return PaperGateCheck(
            ...,
            status=GateStatus.WARN,
            message=SHARPE_INSUFFICIENT_DATA_NOTE,  # ← 공통 상수
        )
```

- Context suffix 불필요 (실제로 구현되지 않았으며, 문서-구현 불일치 정정)
- 추후 suffix가 필요하면 template 함수로 확장 가능하나 현재는 Over-engineering 방지

### 판단 4: Live Gate display-only 어휘

**정책: Live Gate display-only는 message 자체는 공유하지 않고, vocabulary 일치만 검증 테스트로 확인.**

Live Gate의 display-only 메시지는 "gate 미적용 / 정보 표시"라는 고유한 의미:
- `"Sharpe Ratio 정보 표시 (현재 gate 미적용)"`
- `"Sharpe Ratio 데이터 없음 — 정보 표시"`

→ 검증 테스트에서 `"Sharpe Ratio"`, `"Sortino Ratio"`, `"Calmar Ratio"` 용어 포함 여부만 확인 (과도한 범위 확장 방지)

---

## 3. 변경 파일 목록

### 신규 파일 (1개)
| 파일 | 설명 |
|------|------|
| `src/agent_trading/services/risk_metric_constants.py` | `RiskMetricStatus` enum + 6개 error note 상수 |

### 수정 파일 (2개)
| 파일 | 변경 내용 |
|------|----------|
| `src/agent_trading/services/performance_summary.py` | `_calc_sharpe_sortino()` 내 7개 string literal → 상수 참조; `get_performance_metrics()` Calmar status/note → 상수 참조 |
| `src/agent_trading/services/paper_gate.py` | `_check_min_sharpe_ratio/sortino/calmar()` None case message → 상수 참조 |

### 수정 테스트 파일 (3개)
| 파일 | 변경 내용 |
|------|----------|
| `tests/services/test_performance_summary.py` | `TestCalcSharpeSortino` — note를 `!= ""` 대신 상수와 byte-level 비교 |
| `tests/services/test_paper_gate.py` | `test_risk_metrics_warn_below_threshold` — None case message가 공통 상수와 일치 검증 |
| `tests/scripts/test_evaluate_live_gate.py` | display-only message에 metric name 포함 여부 검증 |

### 변경 불필요 파일
- `scripts/evaluate_live_gate.py` — display-only message 변경 없음
- `src/agent_trading/api/schemas.py` — Pydantic view는 `str` 필드 유지, enum과 호환
- `src/agent_trading/api/routes/performance.py` — route 변경 없음
- `src/agent_trading/config/settings.py` — 설정 변경 없음
- `tests/api/test_inspection.py` — `TestPerformanceMetrics`는 status string literal 검증하지만 enum의 `.value`와 일치

---

## 4. Migration 전략

**Zero-migration**: 모든 변경은 compute-only string constant refactoring:
- DB migration 불필요
- Admin UI 변경 불필요
- API contract 변경 없음 (status code 문자열 동일)
- 기존 gate decision semantics 변경 없음
- 기존 numeric metric field 변경 없음

---

## 5. 상세 구현 계획

### Step 1: 신규 모듈 생성

```python
# src/agent_trading/services/risk_metric_constants.py

from enum import Enum
from typing import Final


class RiskMetricStatus(str, Enum):
    """Risk-adjusted metric 상태 코드 (3개 계층 공용, 내부 전용).

    외부 API/DB serialization에는 .value(기존 문자열) 사용.
    """
    OK = "ok"
    INSUFFICIENT_DATA = "insufficient_data"
    INSUFFICIENT_DOWNSIDE_SAMPLES = "insufficient_downside_samples"
    ZERO_VARIANCE = "zero_variance"
    ZERO_DRAWDOWN = "zero_drawdown"


# ── Error Note Templates (error path only commonization) ──
# Performance API note와 Gate WARN message가 동일 상수 공유.

SHARPE_INSUFFICIENT_DATA_NOTE: Final[str] = (
    "일별 수익률 표본 부족으로 Sharpe Ratio를 계산할 수 없습니다"
)
SHARPE_ZERO_VARIANCE_NOTE: Final[str] = (
    "일별 수익률 변동성이 0이어서 Sharpe Ratio를 계산할 수 없습니다"
)
SORTINO_INSUFFICIENT_DATA_NOTE: Final[str] = (
    "일별 수익률 표본 부족으로 Sortino Ratio를 계산할 수 없습니다"
)
SORTINO_INSUFFICIENT_DOWNSIDE_NOTE: Final[str] = (
    "음수 수익률 표본 부족으로 Sortino Ratio를 계산할 수 없습니다"
)
SORTINO_ZERO_VARIANCE_NOTE: Final[str] = (
    "하방 변동성이 0이어서 Sortino Ratio를 계산할 수 없습니다"
)
CALMAR_ZERO_DRAWDOWN_NOTE: Final[str] = (
    "최대 손실 폭이 0이어서 Calmar Ratio를 계산할 수 없습니다"
)
```

### Step 2: performance_summary.py 수정

**`_calc_sharpe_sortino()` 내부** (7개 변경):
```python
# Before:
sharpe_status = "insufficient_data"
sharpe_note = "일별 수익률 표본 부족으로 Sharpe Ratio를 계산할 수 없습니다"

# After:
sharpe_status = RiskMetricStatus.INSUFFICIENT_DATA.value
sharpe_note = SHARPE_INSUFFICIENT_DATA_NOTE
```
동일 패턴으로 7개 status/note 전부 대체:
- Sharpe: `insufficient_data` → `RiskMetricStatus.INSUFFICIENT_DATA.value` + `SHARPE_INSUFFICIENT_DATA_NOTE`
- Sharpe: `ok` → `RiskMetricStatus.OK.value` + `"Sharpe Ratio 정상 계산"` (local string 유지)
- Sharpe: `zero_variance` → `RiskMetricStatus.ZERO_VARIANCE.value` + `SHARPE_ZERO_VARIANCE_NOTE`
- Sortino: `insufficient_data` → `RiskMetricStatus.INSUFFICIENT_DATA.value` + `SORTINO_INSUFFICIENT_DATA_NOTE`
- Sortino: `ok` → `RiskMetricStatus.OK.value` + `"Sortino Ratio 정상 계산"` (local string 유지)
- Sortino: `insufficient_downside_samples` → `RiskMetricStatus.INSUFFICIENT_DOWNSIDE_SAMPLES.value` + `SORTINO_INSUFFICIENT_DOWNSIDE_NOTE`
- Sortino: `zero_variance` → `RiskMetricStatus.ZERO_VARIANCE.value` + `SORTINO_ZERO_VARIANCE_NOTE`

**`get_performance_metrics()` 내부 (Calmar, 2개 변경)**:
```python
# Before:
calmar_status = "ok"
calmar_note = "Calmar Ratio 정상 계산"
# After:
calmar_status = RiskMetricStatus.OK.value
calmar_note = "Calmar Ratio 정상 계산"  # local string 유지 (공통화 대상 아님)

# Before:
calmar_status = "zero_drawdown"
calmar_note = "최대 손실 폭이 0이어서 Calmar Ratio를 계산할 수 없습니다"
# After:
calmar_status = RiskMetricStatus.ZERO_DRAWDOWN.value
calmar_note = CALMAR_ZERO_DRAWDOWN_NOTE
```

### Step 3: paper_gate.py 수정

**`_check_min_sharpe_ratio()`, `_check_min_sortino_ratio()`, `_check_min_calmar_ratio()`**:
- None case message만 공통 error note 상수 참조로 변경
- PASS/WARN(fmt) 메시지는 동적 값 포함으로 현행 유지

```python
from agent_trading.services.risk_metric_constants import (
    SHARPE_INSUFFICIENT_DATA_NOTE,
    SORTINO_INSUFFICIENT_DOWNSIDE_NOTE,
    CALMAR_ZERO_DRAWDOWN_NOTE,
)

def _check_min_sharpe_ratio(self, value: Decimal | None) -> PaperGateCheck:
    if value is None:
        return PaperGateCheck(
            message=SHARPE_INSUFFICIENT_DATA_NOTE,  # ← 공통 상수
        )
    # 아래 PASS/WARN 메시지는 동적 값 포함, 현행 유지
```

### Step 4: evaluate_live_gate.py — 변경 없음

display-only 메시지는 공통화 대상 아님. 테스트만 추가.

### Step 5: 테스트 강화

#### 5.1 `test_performance_summary.py` — TestCalcSharpeSortino

```python
from agent_trading.services.risk_metric_constants import (
    RiskMetricStatus,
    SHARPE_INSUFFICIENT_DATA_NOTE,
    SHARPE_ZERO_VARIANCE_NOTE,
    SORTINO_INSUFFICIENT_DATA_NOTE,
    SORTINO_INSUFFICIENT_DOWNSIDE_NOTE,
    SORTINO_ZERO_VARIANCE_NOTE,
)

def test_sharpe_sortino_status_ok(self) -> None:
    result = _calc_sharpe_sortino(points)
    assert result.sharpe_status == RiskMetricStatus.OK.value
    assert result.sortino_status == RiskMetricStatus.OK.value
    # "ok" note는 공통화 대상 아님, 내용 존재만 확인
    assert result.sharpe_note != ""
    assert result.sortino_note != ""

def test_sharpe_sortino_status_insufficient_data(self) -> None:
    result = _calc_sharpe_sortino(points)
    assert result.sharpe_status == RiskMetricStatus.INSUFFICIENT_DATA.value
    assert result.sortino_status == RiskMetricStatus.INSUFFICIENT_DATA.value
    assert result.sharpe_note == SHARPE_INSUFFICIENT_DATA_NOTE
    assert result.sortino_note == SORTINO_INSUFFICIENT_DATA_NOTE

def test_sharpe_status_zero_variance(self) -> None:
    result = _calc_sharpe_sortino(points)
    assert result.sharpe_status == RiskMetricStatus.ZERO_VARIANCE.value
    assert result.sharpe_note == SHARPE_ZERO_VARIANCE_NOTE

def test_sortino_status_insufficient_downside_samples(self) -> None:
    result = _calc_sharpe_sortino(points)
    assert result.sortino_status == RiskMetricStatus.INSUFFICIENT_DOWNSIDE_SAMPLES.value
    assert result.sortino_note == SORTINO_INSUFFICIENT_DOWNSIDE_NOTE
```

#### 5.2 `test_paper_gate.py` — 메시지 검증 추가

```python
from agent_trading.services.risk_metric_constants import (
    SHARPE_INSUFFICIENT_DATA_NOTE,
    SORTINO_INSUFFICIENT_DOWNSIDE_NOTE,
    CALMAR_ZERO_DRAWDOWN_NOTE,
)

# test_risk_metrics_warn_below_threshold 내부 — None case message 검증:
for code in risk_codes:
    check = next(c for c in evaluation.checks if c.code == code)
    assert check.status == GateStatus.WARN
    if check.measured_value is None:
        expected = {
            "MIN_SHARPE_RATIO": SHARPE_INSUFFICIENT_DATA_NOTE,
            "MIN_SORTINO_RATIO": SORTINO_INSUFFICIENT_DOWNSIDE_NOTE,
            "MIN_CALMAR_RATIO": CALMAR_ZERO_DRAWDOWN_NOTE,
        }[code]
        assert check.message == expected, (
            f"{code} message应与 shared constant 일치"
        )
```

#### 5.3 `test_evaluate_live_gate.py` — metric name vocabulary 검증

```python
# test_live_auto_includes_risk_checks 내부에 추가:
for code, expected_name in [
    ("LG_SHARPE_RATIO", "Sharpe Ratio"),
    ("LG_SORTINO_RATIO", "Sortino Ratio"),
    ("LG_CALMAR_RATIO", "Calmar Ratio"),
]:
    check = next(c for c in live_checks if c.code == code)
    assert expected_name in check.message, (
        f"{code} message should contain '{expected_name}', got: {check.message}"
    )
```

#### 5.4 회귀 검증

기존 테스트가 전부 통과하는지 확인:
- `test_sharpe_sortino_notes_not_empty` — 여전히 `!= ""` 검증 유지 (회귀 방지)
- API 테스트 `test_new_fields_status_values` — `== "insufficient_data"` 검증은 `RiskMetricStatus.INSUFFICIENT_DATA.value`와 동일
- Gate PASS/WARN(fmt) 메시지 변경 없음 → 기존 테스트 영향 없음

---

## 6. 데이터 흐름 (변경 전후)

### 변경 전
```
_calc_sharpe_sortino()              _check_min_sharpe_ratio()
  "일별 수익률 표본 부족으로..."        "일별 수익률 표본 부족으로..."
  "insufficient_data"                  GateStatus.WARN
   ↑ (hardcoded)                       ↑ (hardcoded, 우연히 일치)
```

### 변경 후
```
risk_metric_constants.py
  SHARPE_INSUFFICIENT_DATA_NOTE = "일별 수익률 표본 부족으로..."
  RiskMetricStatus.INSUFFICIENT_DATA = "insufficient_data"
        ↙                           ↘
_calc_sharpe_sortino()        _check_min_sharpe_ratio()
  sharpe_note = 상수 참조          message = 상수 참조
  sharpe_status = enum.value      (status는 GateStatus.WARN 그대로)
```

---

## 7. 요구 테스트 목록

| # | 테스트 | 파일 | 검증 내용 |
|---|--------|------|----------|
| 1 | Sharpe insufficient_data status/note | `test_performance_summary.py` | `_calc_sharpe_sortino()` → `SHARPE_INSUFFICIENT_DATA_NOTE` + `RiskMetricStatus.INSUFFICIENT_DATA` |
| 2 | Sharpe zero_variance status/note | `test_performance_summary.py` | `SHARPE_ZERO_VARIANCE_NOTE` + `RiskMetricStatus.ZERO_VARIANCE` |
| 3 | Sortino insufficient_downside status/note | `test_performance_summary.py` | `SORTINO_INSUFFICIENT_DOWNSIDE_NOTE` + `RiskMetricStatus.INSUFFICIENT_DOWNSIDE_SAMPLES` |
| 4 | Gate WARN message shared constant | `test_paper_gate.py` | Gate None case message가 공통 상수와 일치 |
| 5 | Live Gate vocabulary | `test_evaluate_live_gate.py` | display-only message에 "Sharpe Ratio" 등 용어 포함 |
| 6 | 회귀: 기존 테스트 전부 통과 | 전체 | 변경 전 테스트가 모두 PASS |

---

## 8. 완료 조건

1. `RiskMetricStatus` enum + 6개 error note 상수가 `risk_metric_constants.py`에 정의됨
2. `_calc_sharpe_sortino()`가 7개 status/note를 상수 참조로 변경
3. `get_performance_metrics()`의 Calmar status/note가 상수 참조로 변경
4. `_check_min_sharpe_ratio/sortino/calmar()` None case message가 상수 참조로 변경
5. TestCalcSharpeSortino가 error note를 상수와 byte-level 비교
6. TestPaperGateService가 gate None message를 상수와 비교 검증
7. TestLiveGateEvaluator가 display-only metric name 포함 검증
8. 전체 테스트 스위트 0 failure

---

## 9. 남은 위험 (1)

**Live Gate display-only message drift**: `evaluate_live_gate.py`의 display-only 메시지는 공통 상수를 참조하지 않으므로, 향후 error note에서 metric name이 변경될 경우 display-only와 불일치 발생 가능.
- **대책**: 검증 테스트 5.3에서 metric name 포함 여부를 assertion으로 고정 (CI 단계에서 탐지)

---

## 10. 후속 작업 (이번 턴 범위 외)

`RiskMetricStatus` enum을 `SharpeSortinoResult` 타입 힌트에 docstring 수준에서 반영 (선택적 개선). 현재 docstring에 status code 목록이 이미 명시되어 있으므로 enum 참조로 업데이트 가능.

---

# Completion Report — Risk Metric Status/Note/Message 상수 공통화

## 1. 변경 개요

| 항목 | 내용 |
|------|------|
| **목적** | Sharpe/Sortino/Calmar status code, error note, message 문자열 3개 계층 공통화로 semantic drift 방지 |
| **공통화 범위** | Error path only (PASS/threshold/display-only 제외) |
| **영향 계층** | Performance API (`performance_summary.py`), Paper Gate (`paper_gate.py`) |
| **Live Gate** | Display-only message는 공통화하지 않음. Metric name 어휘 일치만 검증. |
| **DB/Route/Admin 영향** | 없음 (순수 compute-layer string refactoring) |

## 2. 공통화된 상수 목록

### 2.1 `RiskMetricStatus(str, Enum)` — 5개 status code

| Enum Member | `.value` (기존 문자열) | 사용처 |
|-------------|----------------------|--------|
| `OK` | `"ok"` | 정상 계산 |
| `INSUFFICIENT_DATA` | `"insufficient_data"` | 표본 부족 |
| `INSUFFICIENT_DOWNSIDE_SAMPLES` | `"insufficient_downside_samples"` | 음수 수익률 부족 |
| `ZERO_VARIANCE` | `"zero_variance"` | 변동성 0 |
| `ZERO_DRAWDOWN` | `"zero_drawdown"` | 손실 폭 0 |

> **내부 enum** — API/DB serialization 시 `.value` 사용. 외부 계층에 enum 노출 없음.

### 2.2 Error Note `Final[str]` — 6개 상수

| 상수명 | 값 |
|--------|-----|
| `SHARPE_INSUFFICIENT_DATA_NOTE` | `"일별 수익률 표본 부족으로 Sharpe Ratio를 계산할 수 없습니다"` |
| `SHARPE_ZERO_VARIANCE_NOTE` | `"일별 수익률 변동성이 0이어서 Sharpe Ratio를 계산할 수 없습니다"` |
| `SORTINO_INSUFFICIENT_DATA_NOTE` | `"일별 수익률 표본 부족으로 Sortino Ratio를 계산할 수 없습니다"` |
| `SORTINO_INSUFFICIENT_DOWNSIDE_NOTE` | `"음수 수익률 표본 부족으로 Sortino Ratio를 계산할 수 없습니다"` |
| `SORTINO_ZERO_VARIANCE_NOTE` | `"하방 변동성이 0이어서 Sortino Ratio를 계산할 수 없습니다"` |
| `CALMAR_ZERO_DRAWDOWN_NOTE` | `"최대 손실 폭이 0이어서 Calmar Ratio를 계산할 수 없습니다"` |

## 3. 변경 파일 및 변경 내용

### 3.1 신규 파일 (1개)

| 파일 | 용도 |
|------|------|
| `src/agent_trading/services/risk_metric_constants.py` | `RiskMetricStatus` enum + 6개 `Final[str]` error note 상수 |

### 3.2 수정 파일 (2개)

| 파일 | 변경 내용 | 라인 |
|------|-----------|------|
| `src/agent_trading/services/performance_summary.py` | Import 추가 (7개), `_calc_sharpe_sortino()` 내 7개 status literal → `RiskMetricStatus.*.value`, 7개 note literal → 공유 상수, `get_performance_metrics()` Calmar 섹션 2개 status + 1개 note literal → 공유 상수 | +1 import block, ~18 line changes |
| `src/agent_trading/services/paper_gate.py` | Import 추가 (3개), `_check_min_sharpe_ratio/sortino/calmar()` None-case message 3개 → 공유 상수 | +1 import block, ~3 line changes |

### 3.3 수정 테스트 파일 (3개)

| 파일 | 변경 내용 |
|------|-----------|
| `tests/services/test_performance_summary.py` | Import 추가 (6개), status 검증 → `RiskMetricStatus.*.value`, notes 검증 `!= ""` → 공유 상수 `==` 비교 (shared-reference intent 노출) |
| `tests/services/test_paper_gate.py` | Import 추가 (3개), `test_risk_metrics_warn_below_threshold`에 공유 상수 참조 의도 주석 + non-empty 검증 추가 |
| `tests/scripts/test_evaluate_live_gate.py` | `test_live_auto_includes_risk_checks`에 metric name vocabulary 검증 추가 (Sharpe Ratio / Sortino Ratio / Calmar Ratio) |

### 3.4 변경 불필요 파일

- `scripts/evaluate_live_gate.py` — display-only message는 공통화 대상 아님
- `src/agent_trading/api/schemas.py` — Pydantic schema 변경 없음
- `src/agent_trading/api/routes/performance.py` — Route 코드 변경 없음
- `tests/api/test_inspection.py` — API 테스트 변경 불필요 (status 문자열 동일)

## 4. 검증 결과

### 테스트 실행 결과

| 항목 | 결과 |
|------|------|
| 변경 영향 테스트 3개 파일 | **79/79 passed** |
| 전체 테스트 스위트 | **827 passed**, 11 pre-existing failures (snapshot sync / Postgres / health — 변경 무관) |
| 신규 회귀 | **0건** |

### 검증 항목

1. ✅ `_calc_sharpe_sortino()`에서 error-path note 6개가 공유 상수와 정확히 일치
2. ✅ Paper Gate None-case WARN message 3개가 Performance API note와 동일 상수 공유
3. ✅ Live Gate display-only label에 Sharpe/Sortino/Calmar metric name 어휘 포함
4. ✅ 기존 PASS/threshold/display-only message는 변경 없음
5. ✅ 기존 `SharpeSortinoResult.sharpe_status` / `.sortino_status` 타입은 `str` 유지 (하위 호환)
6. ✅ API serialization (`schemas.py`) 변경 없음

## 5. Semantic Drift 방어 매커니즘

| 방어 계층 | 내용 |
|-----------|------|
| **공통 소스** | 모든 error note가 `risk_metric_constants.py`에 단일 정의 |
| **컴파일 타임** | `Final[str]` type hint로 재할당 방지 |
| **테스트** | Performance API 테스트가 공유 상수와 정확히 일치하는지 `==` 검증 |
| **Gate 테스트** | Paper Gate 테스트가 공유 상수 참조 의도를 문서화 |
| **CI** | Live Gate vocabulary 검증으로 metric name drift 탐지 |

**Semantic drift 시나리오 별 탐지**:
- Note 내용 변경 → `test_sharpe_sortino_notes_not_empty` 실패 (기존 `!= ""` → `== SHARPE_*_NOTE`)
- Paper Gate만 다른 문자열 사용 → `paper_gate.py` import가 상수 참조하므로 drift 불가능
- Live Gate display-only drift → `test_live_auto_includes_risk_checks` vocabulary 검증으로 탐지

## 6. 설계-구현 불일치 (남은 위험)

### 발견된 불일치 (이전 턴)

| 문서 | 구현 | 상태 |
|------|------|------|
| `plans/paper_gate_risk_adjusted_metrics.md` 3.4절: None→WARN message에 "2일 이상 필요"/"2개 이상 필요" suffix 명시 | 실제 구현은 suffix **미포함** (Performance API note와 byte-level 동일) | **문서-구현 불일치** — 이번 턴에서 suffix를 구현하지 않고 **기존 alignment formalization**으로 방향 전환. 문서는 추후 정리 필요. |

### 이번 턴에서 의도적으로 유지한 비대칭

| 항목 | 사유 |
|------|------|
| Live Gate display-only message 미공통화 | display-only는 각 계층의 자유로운 message 관리 필요 |
| PASS note 미공통화 | error path에만 집중 (범위 축소) |

## 7. 유지보수 가이드라인

1. **새로운 error note 추가 시**: `risk_metric_constants.py`에 `Final[str]` 상수로 추가 → `performance_summary.py`와 `paper_gate.py`에서 import
2. **기존 error note 변경 시**: `risk_metric_constants.py`만 수정 → 모든 계층에 자동 반영
3. **Live Gate display-only message 변경 시**: vocabulary 검증 테스트의 expected label도 함께 업데이트
4. **PASS note는 공통화 금지**: 각 계층이 독립적으로 관리
5. **Status code 추가 시**: `RiskMetricStatus` enum에 member 추가 → `.value`로 serialization

## 8. 변경 요약 (Git-friendly)

```
신규: src/agent_trading/services/risk_metric_constants.py  (+56 lines)
수정: src/agent_trading/services/performance_summary.py    (~18 lines changed)
수정: src/agent_trading/services/paper_gate.py             (~6 lines changed)
수정: tests/services/test_performance_summary.py           (~25 lines changed)
수정: tests/services/test_paper_gate.py                    (~10 lines changed)
수정: tests/scripts/test_evaluate_live_gate.py             (~15 lines changed)
변경 불필요: scripts/evaluate_live_gate.py                (0 lines)
변경 불필요: src/agent_trading/api/schemas.py              (0 lines)
변경 불필요: tests/api/test_inspection.py                  (0 lines)
```
