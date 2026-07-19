# Performance Metrics Explanation Field 강화 — 설계 문서 (v2, 피드백 반영)

## 1. 목적

`PerformanceMetrics` dataclass와 `PerformanceMetricsView` Pydantic 모델에 **gate-facing explanation/status field**를 추가합니다.

현재 Sharpe/Sortino/Calmar ratio는 값이 `None`일 때 API 응답에 `"sharpe_ratio": null`만 노출되어, **왜** 계산되지 않았는지 구분할 수 없습니다. PaperGateService는 매번 자체 한국어 메시지를 하드코딩하고 있어, Performance 계층과 Gate 계층 간 메시지 의미 불일치가 발생합니다.

이번 작업은:
- **Read-only API**에 structured status + human-readable note 추가
- Gate 계층이 Performance 계층의 **의미적으로 일관된** status/note를 참조할 수 있는 기반 마련
- **Additive only**: 기존 numeric field 의미/타입 절대 변경 불가
- **DB migration 금지**, **Route 코드 변경 금지**, **admin UI 변경 금지**

---

## 2. 유지 원칙 (변경 금지 사항)

| 원칙 | 설명 |
|---|---|
| **기존 `GET /performance-metrics` semantics 변경 금지** | 응답 구조에 새 필드만 추가, 기존 필드 의미/타입 변경 불가 |
| **기존 numeric metric 계산 규칙 변경 금지** | `sharpe_ratio`, `sortino_ratio`, `calmar_ratio` 값 계산은 그대로 |
| **Gate/Layer 판정 semantics 변경 금지** | `PaperGateService`, `PaperExitEvaluator`, `LiveGateEvaluator` 수정 불가 |
| **계층 결합 금지** | status/note는 read-only 설명 필드로만 추가, Gate가 내부적으로 강제 사용하도록 변경하지 않음 |
| **Additive only** | 기존 필드/계산에 영향을 주지 않는 새 필드만 추가 |
| **Paper/live 동일 시스템 원칙** | `performance_summary.py`는 공통 서비스, mode-agnostic 유지 |
| **DB migration 불필요** | Compute-only Read Model |

---

## 3. Helper 반환 계약 결정

### 3.1 결정: 기존 `_calc_sharpe_sortino()`를 NamedTuple 반환으로 변경

**선택 근거:**
1. NamedTuple은 `tuple`의 서브클래스이므로, 기존 `sharpe, sortino = _calc_sharpe_sortino(points)` 형태의 unpacking이 **그대로 동작** (하위 호환)
2. Production call site는 1곳(`get_performance_metrics()` line 938)뿐이므로 영향 범위 협소
3. 신규 함수를 추가하면 daily returns 계산 로직이 중복되어 유지보수 비용 증가
4. 기존 6개 테스트는 numeric assert 변경 없이 통과, status assert만 추가

### 3.2 SharpeSortinoResult NamedTuple

```python
class SharpeSortinoResult(NamedTuple):
    """_calc_sharpe_sortino()의 반환 타입.

    첫 2개 요소는 기존 tuple[Decimal|None, Decimal|None]과 동일하므로
    ``sharpe, sortino = _calc_sharpe_sortino(points)`` 형태의 unpacking이
    그대로 동작합니다.
    """
    sharpe_ratio: Decimal | None
    sharpe_status: str
    sharpe_note: str
    sortino_ratio: Decimal | None
    sortino_status: str
    sortino_note: str
```

### 3.3 하위 호환성 예

```python
# 기존 코드 (변경 불필요):
sharpe, sortino = _calc_sharpe_sortino(points)
# sharpe == result.sharpe_ratio  (result[0])
# sortino == result.sortino_ratio (result[1])

# 신규 코드 (call site에서만 사용):
result = _calc_sharpe_sortino(points)
sharpe_status = result.sharpe_status
sharpe_note = result.sharpe_note
```

---

## 4. 최종 Status Code 목록

| Code | 의미 | 적용 대상 | 결정 사유 |
|---|---|---|---|
| `ok` | 정상 계산됨 | Sharpe/Sortino/Calmar | numeric value 존재 |
| `insufficient_data` | 일별 수익률 표본 < 2개 | Sharpe/Sortino | `len(daily_returns) < 2` |
| `insufficient_downside_samples` | 음수 수익률 표본 < 2개 | Sortino | `len(downside_returns) < 2` |
| `zero_variance` | 변동성 0으로 계산 불가 | Sharpe/Sortino | `stddev == 0`(Sharpe) 또는 `downside_dev == 0`(Sortino). `insufficient_data`와 의미가 다르므로 분리 유지 |
| `zero_drawdown` | 최대 손실 폭 = 0 | Calmar | `max_drawdown_pct == 0` |

---

## 5. Metric별 Status 전이표

### 5.1 Sharpe Ratio

| 조건 | sharpe_ratio | sharpe_status | sharpe_note |
|---|---|---|---|
| `len(daily_returns) >= 2` and `stddev > 0` | 계산값 | `ok` | "Sharpe Ratio 정상 계산" |
| `len(daily_returns) < 2` | `None` | `insufficient_data` | "일별 수익률 표본 부족으로 Sharpe Ratio를 계산할 수 없습니다" |
| `len(daily_returns) >= 2` and `stddev == 0` | `None` | `zero_variance` | "일별 수익률 변동성이 0이어서 Sharpe Ratio를 계산할 수 없습니다" |

### 5.2 Sortino Ratio

| 조건 | sortino_ratio | sortino_status | sortino_note |
|---|---|---|---|
| `len(daily_returns) >= 2` and `len(downside) >= 2` and `downside_dev > 0` | 계산값 | `ok` | "Sortino Ratio 정상 계산" |
| `len(daily_returns) < 2` | `None` | `insufficient_data` | "일별 수익률 표본 부족으로 Sortino Ratio를 계산할 수 없습니다" |
| `len(downside) < 2` | `None` | `insufficient_downside_samples` | "음수 수익률 표본 부족으로 Sortino Ratio를 계산할 수 없습니다" |
| `len(downside) >= 2` and `downside_dev == 0` | `None` | `zero_variance` | "하방 변동성이 0이어서 Sortino Ratio를 계산할 수 없습니다" |

### 5.3 Calmar Ratio

| 조건 | calmar_ratio | calmar_status | calmar_note |
|---|---|---|---|
| `max_drawdown_pct > 0` | 계산값 | `ok` | "Calmar Ratio 정상 계산" |
| `max_drawdown_pct == 0` | `None` | `zero_drawdown` | "최대 손실 폭이 0이어서 Calmar Ratio를 계산할 수 없습니다" |

> **Calmar와 `insufficient_data`**: Calmar ratio는 `cumulative_return_pct`와 `max_drawdown_pct`를 사용합니다. 이 두 값은 `_calc_equity_metrics()`에서 항상 `Decimal` (0 이상)을 반환하므로(empty data에도 safe default), Calmar가 `insufficient_data` 상태가 되는 경우는 없습니다. 유일한 None 조건은 `max_drawdown_pct == 0` → `zero_drawdown`입니다.

---

## 6. Note 설계 원칙

### 6.1 Gate 메시지와의 관계

**"의미 일치 (semantic consistency)"** 를 목표로 하며, **"문자열 byte-level 완전 일치"는 요구하지 않습니다.**

- Performance API note는 **설명 메시지** (읽는 사람이 왜 None인지 이해)
- Gate message는 **판정 메시지** (GO/HOLD 결정 사유)
- 의미와 용어는 일치시키되, 양측이 동일 문자열일 필요는 없음
- 향후 Gate가 이 status/note를 참조하는 개선 시에도 문자열 동일성 강제 금지

### 6.2 Note 메시지 일람

| Metric | Status | Note | Gate 의미 일치 |
|---|---|---|---|
| Sharpe | `ok` | "Sharpe Ratio 정상 계산" | N/A |
| Sharpe | `insufficient_data` | "일별 수익률 표본 부족으로 Sharpe Ratio를 계산할 수 없습니다" | ✅ |
| Sharpe | `zero_variance` | "일별 수익률 변동성이 0이어서 Sharpe Ratio를 계산할 수 없습니다" | Gate에 해당 case 없음 |
| Sortino | `ok` | "Sortino Ratio 정상 계산" | N/A |
| Sortino | `insufficient_data` | "일별 수익률 표본 부족으로 Sortino Ratio를 계산할 수 없습니다" | ✅ (Sharpe와 동일 조건) |
| Sortino | `insufficient_downside_samples` | "음수 수익률 표본 부족으로 Sortino Ratio를 계산할 수 없습니다" | ✅ |
| Sortino | `zero_variance` | "하방 변동성이 0이어서 Sortino Ratio를 계산할 수 없습니다" | Gate에 해당 case 없음 |
| Calmar | `ok` | "Calmar Ratio 정상 계산" | N/A |
| Calmar | `zero_drawdown` | "최대 손실 폭이 0이어서 Calmar Ratio를 계산할 수 없습니다" | ✅ |

---

## 7. 변경 파일 목록

| 파일 | 변경 유형 | 변경 목적 |
|---|---|---|
| `src/agent_trading/services/performance_summary.py` | 수정 | `SharpeSortinoResult` NamedTuple 추가, `PerformanceMetrics`에 6개 설명 필드 추가, `_calc_sharpe_sortino()` 반환 타입을 NamedTuple로 변경, `get_performance_metrics()` Calmar status/note 로직 추가 |
| `src/agent_trading/api/schemas.py` | 수정 | `PerformanceMetricsView`에 6개 설명 필드 추가 (`from_attributes`로 자동 매핑) |
| `tests/services/test_performance_summary.py` | 수정 | `TestCalcSharpeSortino`에 status 검증 6개 테스트 추가, `TestGetPerformanceMetrics`에 status assert 3개 통합 |
| `tests/api/test_inspection.py` | 수정 | `TestPerformanceMetrics`에 신규 6개 field 존재 + status 값 + 기존 numeric 회귀 없음 검증 |

**변경 불필요 파일**:
- `src/agent_trading/api/routes/performance.py` — `model_validate`가 자동 처리
- `src/agent_trading/services/paper_gate.py` — Gate 판정 semantics 변경 금지
- `scripts/evaluate_paper_exit.py` — Gate 재사용만 함, 변경 불필요
- `scripts/evaluate_live_gate.py` — Gate 재사용만 함, 변경 불필요
- DB migration — 없음
- admin UI — 변경 금지

---

## 8. API 계약

### 8.1 PerformanceMetricsView 추가 필드

```python
class PerformanceMetricsView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    # ... 기존 19개 필드 유지 (변경 없음) ...
    
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    calmar_ratio: float | None = None
    
    # ── Explanation / Status Fields (신규 6개) ──
    sharpe_ratio_status: str
    sharpe_ratio_note: str
    sortino_ratio_status: str
    sortino_ratio_note: str
    calmar_ratio_status: str
    calmar_ratio_note: str
```

### 8.2 응답 예시 (JSON)

```json
{
  "account_id": "...",
  "period_start": "2026-05-01",
  "period_end": "2026-05-10",
  "sharpe_ratio": -0.15,
  "sortino_ratio": null,
  "calmar_ratio": -0.5,
  "sharpe_ratio_status": "ok",
  "sharpe_ratio_note": "Sharpe Ratio 정상 계산",
  "sortino_ratio_status": "insufficient_downside_samples",
  "sortino_ratio_note": "음수 수익률 표본 부족으로 Sortino Ratio를 계산할 수 없습니다",
  "calmar_ratio_status": "ok",
  "calmar_ratio_note": "Calmar Ratio 정상 계산",
  "...": "기존 19개 필드 유지"
}
```

### 8.3 Route 코드 변경 여부

**변경 불필요.** `PerformanceMetricsView.model_validate(metrics)`가 `from_attributes=True`로 dataclass의 새 필드를 자동 매핑합니다.

---

## 9. 테스트 계획

### 9.1 Pure Function Tests: `TestCalcSharpeSortino` (6개 신규 + 기존 6개 보강)

| # | 테스트명 | 검증 내용 | 기존 변경 |
|---|---|---|---|
| 1 | `test_mixed_returns` (기존) | sharpe/sortino numeric 정확성 | 변경 없음 (NamedTuple 하위 호환) |
| 2 | `test_all_positive_returns` (기존) | sortino=None (downside=0) | 변경 없음 |
| 3 | `test_all_same_returns` (기존) | sharpe=None (stddev=0), sortino=None | 변경 없음 |
| 4 | `test_single_valid_return` (기존) | (None, None) < 2 returns | 변경 없음 |
| 5 | `test_insufficient_data` (기존) | (None, None) all None equity | 변경 없음 |
| 6 | `test_mixed_negative_heavy` (기존) | both computed | 변경 없음 |
| 7 | **`test_status_ok` (신규)** | 정상 계산 → status="ok" | 신규 |
| 8 | **`test_status_insufficient_data` (신규)** | return < 2개 → sharpe_status="insufficient_data" | 신규 |
| 9 | **`test_status_insufficient_downside` (신규)** | downside < 2개 → sortino_status="insufficient_downside_samples" | 신규 |
| 10 | **`test_status_zero_variance_sharpe` (신규)** | stddev=0 → sharpe_status="zero_variance" | 신규 |
| 11 | **`test_status_zero_variance_sortino` (신규)** | all positive → sortino_status="zero_variance" | 신규 |
| 12 | **`test_notes_not_empty` (신규)** | 모든 status 케이스에서 note가 비어있지 않음 | 신규 |

### 9.2 Integration Tests: `TestGetPerformanceMetrics` (기존 7개 + 3개 status 보강)

| # | 테스트명 | 검증 내용 |
|---|---|---|
| 1 | `test_basic_risk_metrics` | 기존 numeric + sharpe_status="ok", sortino_status="ok", calmar_status="ok" |
| 2 | `test_flat_equity_risk_metrics` | 기존 numeric + sharpe_status="zero_variance", sortino_status="zero_variance", calmar_status="zero_drawdown" |
| 3 | `test_no_data_risk_metrics` | 기존 numeric + sharpe_status="insufficient_data", sortino_status="insufficient_data", calmar_status="zero_drawdown" |

### 9.3 API Response Tests: `TestPerformanceMetrics` (3개 보강)

| # | 테스트명 | 검증 내용 |
|---|---|---|
| 1 | `test_new_fields_present` | 기존 3개 + 신규 6개 = 9개 field 존재 확인 |
| 2 | `test_new_fields_status_values` | 데이터 없음 → status 값이 "insufficient_data"/"zero_drawdown"인지 확인 |
| 3 | `test_existing_fields_unchanged` | 기존 19개 numeric field 타입/값 유지 + 신규 6개 field str 타입 확인 |

---

## 10. 실행 단계

### Step 1: `SharpeSortinoResult` NamedTuple + `_calc_sharpe_sortino()` 반환 타입 변경

파일: `src/agent_trading/services/performance_summary.py`
- 모듈 레벨에 `SharpeSortinoResult` NamedTuple 정의
- `_calc_sharpe_sortino()` 내부: 각 None 조건별 status/note 분기 추가
- return 타입을 `SharpeSortinoResult`로 변경 (첫 2개 요소는 기존과 동일)

### Step 2: `PerformanceMetrics` dataclass 6개 설명 필드 추가

파일: `src/agent_trading/services/performance_summary.py`
- `sharpe_ratio_status`, `sharpe_ratio_note`, `sortino_ratio_status`, `sortino_ratio_note`, `calmar_ratio_status`, `calmar_ratio_note` 추가

### Step 3: `get_performance_metrics()` 호출부 및 Calmar status/note 로직 변경

파일: `src/agent_trading/services/performance_summary.py`
- `_calc_sharpe_sortino()` 호출 결과를 NamedTrip의 속성으로 unpack
- Calmar ratio status/note 결정 로직 추가
- `PerformanceMetrics(...)` 생성자에 신규 6개 필드 전달

### Step 4: `PerformanceMetricsView` 6개 설명 필드 추가

파일: `src/agent_trading/api/schemas.py`

### Step 5: Pure function 테스트 6개 추가

파일: `tests/services/test_performance_summary.py`
- `TestCalcSharpeSortino` 클래스 내 6개 신규 테스트 메서드 추가

### Step 6: Integration 테스트 3개 보강

파일: `tests/services/test_performance_summary.py`
- 기존 3개 risk metric 통합 테스트에 status assert 추가

### Step 7: API 테스트 3개 보강

파일: `tests/api/test_inspection.py`
- 신규 6개 field 존재 확인 + status 값 검증 + 기존 numeric 회귀 없음 검증

### Step 8: 전체 테스트 실행

```bash
cd /workspace/agent_trading && python3 -m pytest tests/services/test_performance_summary.py tests/api/test_inspection.py -v --tb=short 2>&1 | tail -30
```

---

## 11. 제약 조건 점검

| 조건 | 상태 | 설명 |
|---|---|---|
| **Additive only** | ✅ | 기존 19개 필드 변경 없음 |
| **기존 numeric 계산 규칙 변경 없음** | ✅ | `_calc_sharpe_sortino()`의 sharpe/sortino 계산은 기존과 동일, status만 추가 분기 |
| **Frozen dataclass 호환** | ✅ | 기본값 있는 필드로 frozen 제약 우회 |
| **Mode-agnostic** | ✅ | `performance_summary.py` 변경만으로 paper/live 모두 적용 |
| **DB migration 불필요** | ✅ | Compute-only Read Model |
| **Gate semantics 변경 금지** | ✅ | `paper_gate.py` 포함 어느 Gate도 수정하지 않음 |
| **Route 코드 변경 불필요** | ✅ | `model_validate` + `from_attributes`로 자동 매핑 |
| **Admin UI 변경 금지** | ✅ | 수정 대상 아님 |
| **의미 일치 only** | ✅ | note와 gate message는 의미 일치, 문자열 동일성 강제하지 않음 |
