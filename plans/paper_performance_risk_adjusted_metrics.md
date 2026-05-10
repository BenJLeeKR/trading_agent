# Paper Performance Metrics 심화 — Sharpe / Sortino / Calmar Ratio

> **상태**: 설계 — **mode-agnostic**
> **목표**: 기존 [`PerformanceMetrics`](src/agent_trading/services/performance_summary.py:258) dataclass와
> [`GET /performance-metrics`](src/agent_trading/api/routes/performance.py:174) endpoint에
> Sharpe ratio, Sortino ratio, Calmar ratio를 **additive field expansion**으로 추가한다.
>
> **원칙**:
> - 기존 endpoint semantics 유지 (response field만 확장)
> - 기존 19개 field 변경 없음, 신규 3개 field만 추가
> - 계산 규칙은 deterministic backend logic으로 고정
> - benchmark-relative history 작업과 충돌 없음
> - paper/live 동일 시스템 (mode-agnostic)
> - DB migration 불필요 (계산값만 반환, 저장 안함)
> - Admin UI 변경 금지
> - risk-free rate env/config 추가 금지
> - missing date / missing equity 보간 금지
> - PaperGateService / PaperExitEvaluator / LiveGateEvaluator 동작 변경 금지

---

## 1. 설계 판단 (고정 사항)

### 1.1 수익률 입력 단위

[`DailyPerformancePoint.total_equity`](src/agent_trading/services/performance_summary.py:223) 기반 **일별 수익률 (decimal, non-percentage)**.

### 1.2 일별 수익률 생성 규칙

```python
# daily_return[t] 계산식
daily_return[t] = (equity[t] - equity[t-1]) / equity[t-1]

# 조건 (모두 충족 필요):
# 1. equity[t] is not None
# 2. equity[t-1] is not None
# 3. equity[t-1] > 0 (0으로 나누기 방지)
#
# equity[t]와 equity[t-1]은 연속하는 두 DailyPerformancePoint.total_equity
# get_daily_history()는 calendar iteration을 사용하므로 포인트 순서 보장됨
#
# 누락 데이터 처리:
# - equity[t] == None → 해당 return 건너뜀, prev_equity는 이전 유효값 유지 (carry-forward)
# - equity[t-1] == 0 → 해당 return 건너뜀 (division guard)
# - equity[t-1] == None → return 계산 불가, 건너뜀
# - 연속 None equity로 인한 gap은 보간하지 않음 (interpolation 금지)
```

### 1.3 Sharpe / Sortino 연율화 정책

**이번 턴: 비연율화 (raw daily ratio)** 로 고정.

```python
# Sharpe (raw daily) = mean(daily_returns) / stddev(daily_returns)
# Sortino (raw daily) = mean(daily_returns) / downside_deviation
```

후속 작업에서 `sqrt(252)` annualization을 추가할 수 있도록
pure helper 시그니처는 확장에 열려 있게 유지 (별도 annualize wrapper 또는 옵션 파라미터).

### 1.4 Risk-Free Rate

**`0` 고정**. env var/config 추가 없음. (이번 턴 범위 외)

### 1.5 최소 표본 조건

| 지표 | 최소 요구 조건 | 부족 시 | 근거 |
|------|---------------|---------|------|
| Sharpe ratio | **2개 이상** 유효 일별 수익률 | `None` | ddof=1 표본 표준편차 계산 가능 조건 |
| Sortino ratio | **2개 이상** 유효 일별 수익률 **AND** **2개 이상** 음수 수익률 | `None` | 음수 수익률만으로 downside deviation 계산 필요 |
| Calmar ratio | `cumulative_return_pct` + `max_drawdown_pct` 모두 정상 | `None` | 단순 나눗셈, 두 값만 있으면 계산 가능 |

> **Sortino 특이사항**: 전체 일별 수익률이 10개여도 downside sample이 1개뿐이면
> downside deviation을 신뢰할 수 없으므로 `None`. 이는 Sortino 비율의 특성상
> 음수 수익률이 거의 없는 포트폴리오에서 자연스러운 결과.

### 1.6 Denominator 0 정책

| 상황 | Sharpe | Sortino | Calmar |
|------|--------|---------|--------|
| stddev=0 (모든 return 동일) | `None` | — | — |
| downside deviation=0 (모든 return >= 0) | — | `None` | — |
| max_drawdown=0 (하락 없음) | — | — | `None` |

### 1.7 Calmar ratio 부호/분모 규칙

```python
calmar_ratio = cumulative_return_pct / max_drawdown_pct
# - cumulative_return_pct와 max_drawdown_pct는 모두 percentage (e.g. 15.0 = 15%)
# - max_drawdown_pct == 0 → None (division guard)
# - cumulative_return_pct가 음수이면 calmar_ratio도 음수 가능
#   예: return=-5%, drawdown=10% → calmar=-0.5 (portfolio 손실 상태)
```

### 1.8 기존 Metrics Semantics 호환성

- 기존 `PerformanceMetrics` 19개 field의 계산 규칙은 **전혀 변경하지 않음**
- 신규 `sharpe_ratio`, `sortino_ratio`, `calmar_ratio` 3개 field만 **additive 추가**
- 기존 `_calc_equity_metrics()`, `_calc_win_loss_metrics()` pure helper는 변경 없음
- 기존 `get_performance_metrics()` 반환값 중 기존 field는 동일한 값 유지

### 1.9 배치 위치

Pure helper `_calc_sharpe_sortino()`를 [`performance_summary.py`](src/agent_trading/services/performance_summary.py)에 신규 추가.
기존 `_calc_equity_metrics()`, `_calc_win_loss_metrics()`와 동일한 pure function 패턴.

---

## 2. 계산 규칙

### 2.1 일별 수익률 계산 (공통 전제)

```python
# 입력: get_daily_history()가 반환한 Sequence[DailyPerformancePoint]
# calendar iteration 보장됨 (start_date부터 end_date까지每日 1포인트)

prev_equity: Decimal | None = None
daily_returns: list[Decimal] = []

for p in points:
    if p.total_equity is not None and prev_equity is not None and prev_equity > 0:
        # 조건: equity[t] != None AND equity[t-1] != None AND equity[t-1] > 0
        daily_return = (p.total_equity - prev_equity) / prev_equity  # decimal, non-%
        daily_returns.append(daily_return)
    # prev_equity 갱신: None이 아닌 equity만 carry-forward
    if p.total_equity is not None:
        prev_equity = p.total_equity
    # p.total_equity가 None이면 prev_equity 유지 (carry-forward)

# 보간 금지: equity[t]==None인 날은 return을 계산하지 않고 prev_equity 유지
# 연속 None으로 인한 gap은 return list에서 자연스럽게 누락됨
```

### 2.2 Sharpe Ratio (비연율화, raw daily)

```python
n = len(daily_returns)             # 유효 일별 수익률 개수
mean_return = sum(r for r in daily_returns) / Decimal(str(n))

# 표본 표준편차 (ddof=1)
variance = sum((r - mean_return) ** 2 for r in daily_returns) / Decimal(str(n - 1))
stddev = variance.sqrt() if variance > 0 else Decimal("0")

# n >= 2, stddev > 0 → 계산
# n < 2 → None (위 최소 표본 조건)
# stddev == 0 → None (denominator 0 정책)
sharpe_ratio = mean_return / stddev if stddev > 0 else None
```

### 2.3 Sortino Ratio (비연율화, raw daily)

```python
n = len(daily_returns)
mean_return = sum(r for r in daily_returns) / Decimal(str(n))

# downside: risk-free rate=0 기준, 음수 수익률만
downside_returns = [r for r in daily_returns if r < 0]
m = len(downside_returns)          # 음수 수익률 개수

# m >= 2 → downside deviation 계산 가능
# m < 2 → None (별도 최소 downside 표본 조건)
if m >= 2:
    downside_variance = sum(r * r for r in downside_returns) / Decimal(str(n - 1))
    # 주의: 분모는 n-1 (전체 표본 기준), NOT m-1
    # 이는 Sortino ratio 표준 정의 (Rollinger & Hoffman, 2013)를 따름
    downside_dev = downside_variance.sqrt() if downside_variance > 0 else Decimal("0")
    sortino_ratio = mean_return / downside_dev if downside_dev > 0 else None
else:
    sortino_ratio = None
```

### 2.4 Calmar Ratio

```python
# cumulative_return_pct와 max_drawdown_pct는 이미 _calc_equity_metrics()에서 계산됨
# 둘 다 percentage 형태 (예: 15.0 = 15%)
# max_drawdown_pct == 0 → None (division guard)
# cumulative_return_pct가 음수이면 calmar_ratio도 음수 가능
calmar_ratio = cumulative_return_pct / max_drawdown_pct if max_drawdown_pct > 0 else None
```

Calmar는 별도 pure helper 없이 [`get_performance_metrics()`](src/agent_trading/services/performance_summary.py:736) 내에서 직접 계산.

---

## 3. Data Model 변경

### 3.1 PerformanceMetrics Dataclass (기존 확장)

[`src/agent_trading/services/performance_summary.py`](src/agent_trading/services/performance_summary.py:258)

```python
@dataclass(slots=True, frozen=True)
class PerformanceMetrics:
    # ... 기존 19개 field 유지 ...

    # ── 신규: 위험 조정 수익률 지표 ──
    sharpe_ratio: Decimal | None = None
    """Sharpe ratio = mean daily return / stddev of daily returns.
    risk-free rate = 0. 최소 2개 유효 일별 수익률 필요.
    stddev=0이면 None."""

    sortino_ratio: Decimal | None = None
    """Sortino ratio = mean daily return / downside deviation.
    risk-free rate = 0. 최소 2개 유효 일별 수익률 필요.
    downside deviation=0이면 None."""

    calmar_ratio: Decimal | None = None
    """Calmar ratio = cumulative_return_pct / max_drawdown_pct.
    max_drawdown_pct=0이면 None."""
```

> **참고**: Python dataclass에서 mutable default는 금지되지만, `None`은 immutable이므로 안전.
> 또는 `field(default=None)` 사용 가능.

### 3.2 PerformanceMetricsView Schema (기존 확장)

[`src/agent_trading/api/schemas.py`](src/agent_trading/api/schemas.py:472)

```python
class PerformanceMetricsView(BaseModel):
    # ... 기존 19개 field 유지 ...

    # ── 신규 ──
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    calmar_ratio: float | None = None
```

---

## 4. Pure Helper 설계

### `_calc_sharpe_sortino()`

```python
def _calc_sharpe_sortino(
    points: Sequence[DailyPerformancePoint],
) -> tuple[Decimal | None, Decimal | None]:
    """일별 equity history에서 Sharpe ratio와 Sortino ratio를 계산합니다.

    계산 규칙
    --------
    - 비연율화 raw daily 기준 (후속에서 sqrt(252) 확장 예정)
    - risk-free rate = 0 고정 (env/config 추가 금지)
    - 일별 수익률은 연속된 두 non-None equity 쌍에서만 생성
    - equity[t-1] == 0인 경우 해당 return 계산하지 않음
    - missing day equity는 보간하지 않음 (prev_equity carry-forward)
    - 최소 2개 유효 일별 수익률 필요 (ddof=1 표본 표준편차 계산 가능 조건)
    - Sortino: 음수 수익률 표본이 2개 미만이면 None

    Parameters
    ----------
    points:
        일별 성과 포인트 목록 (start_date→end_date 순).

    Returns
    -------
    tuple[Decimal | None, Decimal | None]
        (sharpe_ratio, sortino_ratio)
        유효 daily return이 2개 미만이면 (None, None).
    """
    # 1. 일별 수익률 계산 (연속된 non-None equity 쌍만)
    daily_returns: list[Decimal] = []
    prev_equity: Decimal | None = None

    for p in points:
        if p.total_equity is not None and prev_equity is not None and prev_equity > 0:
            daily_return = (p.total_equity - prev_equity) / prev_equity
            daily_returns.append(daily_return)
        if p.total_equity is not None:
            prev_equity = p.total_equity
        # p.total_equity가 None이면 prev_equity 유지 (carry forward, 보간 금지)

    if len(daily_returns) < 2:
        return (None, None)

    # 2. Mean daily return
    n = len(daily_returns)
    mean_return = sum(daily_returns) / Decimal(str(n))

    # 3. Sharpe: mean / stddev (비연율화, raw daily)
    variance = sum((r - mean_return) ** 2 for r in daily_returns) / Decimal(str(n - 1))
    stddev = variance.sqrt() if variance > 0 else Decimal("0")

    sharpe_ratio: Decimal | None = None
    if stddev > 0:
        sharpe_ratio = mean_return / stddev

    # 4. Sortino: mean / downside deviation (비연율화, raw daily)
    downside_returns = [r for r in daily_returns if r < 0]
    # 최소 downside 표본 조건: 음수 수익률 2개 미만이면 None
    if len(downside_returns) >= 2:
        downside_variance = sum(r * r for r in downside_returns) / Decimal(str(n - 1))
        downside_dev = downside_variance.sqrt() if downside_variance > 0 else Decimal("0")
    else:
        downside_dev = Decimal("0")

    sortino_ratio: Decimal | None = None
    if downside_dev > 0:
        sortino_ratio = mean_return / downside_dev

    return (sharpe_ratio, sortino_ratio)
```

### `get_performance_metrics()` 내 Calmar 계산

```python
# 기존 equity metrics 계산 후 (lines 790-796)
# Calmar ratio (cumulative_return_pct / max_drawdown_pct)
# max_drawdown_pct == 0 → None (division guard)
# cumulative_return_pct가 음수이면 calmar_ratio도 음수 가능
calmar_ratio = (
    cumulative_return_pct / max_drawdown_pct
    if max_drawdown_pct > 0
    else None
)
```

---

## 5. get_performance_metrics() 내 통합 위치

[`get_performance_metrics()`](src/agent_trading/services/performance_summary.py:736)는 현재:

1. `get_daily_history()` 호출 (line 766)
2. `starting_equity` 계산 (line 770)
3. `_calc_equity_metrics()` (line 790) → return/drawdown
4. Per-order PnL / `_calc_win_loss_metrics()` (line 798)
5. `PerformanceMetrics` 조립 (line 852)

**변경 후**:

1. 동일
2. 동일
3. 동일
4. 동일
5. **신규**: `_calc_sharpe_sortino(points)` 호출 → (sharpe, sortino)
6. **신규**: `calmar_ratio` 계산 (cumulative_return_pct / max_drawdown_pct)
7. `PerformanceMetrics` 조립 — 기존 19개 + 신규 3개 field

---

## 6. 변경 파일 목록

| 파일 | 변경 유형 | 설명 |
|------|-----------|------|
| [`src/agent_trading/services/performance_summary.py`](src/agent_trading/services/performance_summary.py) | 🔹 수정 | `_calc_sharpe_sortino()` pure helper 추가, `PerformanceMetrics` dataclass에 3개 field 추가, `get_performance_metrics()`에 계산 로직 추가 |
| [`src/agent_trading/api/schemas.py`](src/agent_trading/api/schemas.py) | 🔹 수정 | `PerformanceMetricsView`에 `sharpe_ratio`, `sortino_ratio`, `calmar_ratio` 3개 field 추가 |
| [`tests/services/test_performance_summary.py`](tests/services/test_performance_summary.py) | 🔹 수정 | `TestCalcSharpeSortino` pure function tests + `TestGetPerformanceMetrics` 확장 |
| [`tests/api/test_inspection.py`](tests/api/test_inspection.py) 또는 신규 API test file | 🔹 수정 | `GET /performance-metrics` 응답에 신규 field 포함 검증 |
| [`plans/paper_performance_metrics.md`](plans/paper_performance_metrics.md) | 🔹 수정 | 설계 문서에 Sharpe/Sortino/Calmar 섹션 추가, deferred 상태 해제 |
| [`plans/BACKLOG.md`](plans/BACKLOG.md) | 🔹 수정 | 승격 기록 추가 |

**변경 불필요**:
- [`benchmark_comparison.py`](src/agent_trading/services/benchmark_comparison.py) — 변경 없음 (순수 portfolio metrics)
- [`routes/performance.py`](src/agent_trading/api/routes/performance.py) — 변경 없음 (`PerformanceMetricsView`가 자동 반영)
- [`db/migrations/`](db/migrations/) — 변경 없음 (저장 안함)
- [`admin_ui/`](admin_ui/) — 변경 금지
- [`config/settings.py`](src/agent_trading/config/settings.py) — 변경 없음 (rf=0 고정)
- 기존 endpoint — 전혀 변경 없음

---

## 7. 테스트 계획

### 7.1 Pure Function Tests: `TestCalcSharpeSortino`

| # | 테스트 | 입력 | 기대 결과 |
|---|--------|------|----------|
| 1 | **mixed_returns** | [+0.01, -0.005, +0.02, +0.015, -0.01] 5개 return | sharpe=양수, sortino=양수 |
| 2 | **all_positive_returns** | [+0.01, +0.02, +0.015] → downside=0 | sharpe=정상, sortino=None (downside_dev=0) |
| 3 | **all_same_returns** | [+0.01, +0.01, +0.01] → stddev=0 | sharpe=None, sortino=None |
| 4 | **single_valid_return** | 1개 return만 (< 2) | (None, None) |
| 5 | **insufficient_data** | 0개 return (모두 None equity) | (None, None) |
| 6 | **mixed_negative_heavy** | [-0.02, -0.01, +0.03, -0.015] | sharpe=음수 가능, sortino=음수 가능 |

### 7.2 Service Integration Tests: `TestGetPerformanceMetrics` 확장

기존 `TestGetPerformanceMetrics` 클래스에 3개 시나리오 추가:

| # | 테스트 | 설명 | 검증 포인트 |
|---|--------|------|-----------|
| 7 | **basic_risk_metrics** | equity 변화 다양 + 2개 이상 FILLED order | sharpe/sortino/calmar 모두 정상 계산 |
| 8 | **flat_equity** | equity 변동 없음 → stddev=0 | sharpe=None, sortino=None |
| 9 | **no_data** | 데이터 없는 계좌 | 모든 신규 field=None |

### 7.3 API Response Tests

| # | 테스트 | 설명 | 검증 포인트 |
|---|--------|------|-----------|
| 10 | **new_fields_present** | 정상 시나리오 응답 | `sharpe_ratio`, `sortino_ratio`, `calmar_ratio` field 존재 |
| 11 | **new_fields_null** | equity 없음 → 모든 신규 field None | `null` 확인 |
| 12 | **existing_fields_unchanged** | 기존 19개 field 값 회귀 확인 | 기존 field 값 동일 |

### 7.4 회귀 검증

```bash
# performance_summary 전체
python3 -m pytest tests/services/test_performance_summary.py -v

# benchmark_comparison (변경 없음 확인)
python3 -m pytest tests/services/test_benchmark_comparison.py -v

# API inspection (회귀)
python3 -m pytest tests/api/test_inspection.py -v

# 전체 테스트 스위트
python3 -m pytest tests/ -v
```

---

## 8. 실행 단계

```mermaid
flowchart LR
    A["Step 1<br/>Pure Helper 추가"] --> B["Step 2<br/>Dataclass 확장"]
    B --> C["Step 3<br/>Service 통합"]
    C --> D["Step 4<br/>Schema 확장"]
    D --> E["Step 5<br/>테스트 작성"]
    E --> F["Step 6<br/>회귀 검증"]
    F --> G["Step 7<br/>문서 정리"]
```

| 단계 | 내용 | 담당 모드 | 변경 파일 |
|------|------|-----------|----------|
| **Step 1** | `_calc_sharpe_sortino()` pure helper 구현 (일별 수익률 추출, Sharpe/Sortino 계산, zero/insufficient guard) | Code | `performance_summary.py` |
| **Step 2** | `PerformanceMetrics` dataclass에 `sharpe_ratio`, `sortino_ratio`, `calmar_ratio` 3개 field 추가 | Code | `performance_summary.py` |
| **Step 3** | `get_performance_metrics()`에 `_calc_sharpe_sortino()` 호출 및 Calmar 계산 로직 추가 | Code | `performance_summary.py` |
| **Step 4** | `PerformanceMetricsView`에 3개 field 추가 (float \| None) | Code | `schemas.py` |
| **Step 5** | 테스트 작성 — `TestCalcSharpeSortino` (6 tests) + `TestGetPerformanceMetrics` 확장 (3 tests) + API response (3 tests) | Code | `test_performance_summary.py` + API test file |
| **Step 6** | 회귀 검증 — 전체 pytest suite | Code | — |
| **Step 7** | 문서 정리 — `paper_performance_metrics.md` 업데이트 + `BACKLOG.md` 승격 기록 | Code | 문서 2건 |

---

## 9. 제약 조건 점검

| 제약 조건 | 준수 여부 | 설명 |
|-----------|-----------|------|
| 기존 endpoint semantics 유지 | ✅ | `GET /performance-metrics` response field만 확장, 기존 19개 field 변경 없음 |
| `GET /performance-benchmark` 변경 금지 | ✅ | 전혀 건드리지 않음 |
| benchmark-relative history 충돌 없음 | ✅ | 순수 portfolio metrics layer, benchmark 관련 코드 전혀 변경 없음 |
| DB migration 불필요 | ✅ | 계산값만 반환, 저장 안함 |
| Admin UI 변경 금지 | ✅ | API layer까지만 변경 |
| Paper/live 동일 시스템 | ✅ | mode-agnostic, repository 기반 |
| Broker submit semantics 변경 금지 | ✅ | broker 코드 전혀 건드리지 않음 |
| Hard guardrail/reconciliation 경계 변경 금지 | ✅ | guardrail/reconciliation 코드 전혀 건드리지 않음 |
| Additive 변경만 수행 | ✅ | 기존 파일에 field/lines 추가만, 구조 변경 없음 |
| PaperGate / PaperExit / LiveGate semantics 변경 금지 | ✅ | gate 코드 전혀 건드리지 않음 |

---

## 10. 완료 조건

1. ✅ `_calc_sharpe_sortino()` pure helper — 6개 순수 함수 테스트 통과
2. ✅ `PerformanceMetrics` dataclass — 3개 신규 field 추가 (기존 19개 유지)
3. ✅ `PerformanceMetricsView` schema — 3개 신규 field 추가 (기존 19개 유지)
4. ✅ `get_performance_metrics()` — Sharpe/Sortino/Calmar 계산 통합
5. ✅ 3개 service 통합 테스트 통과
6. ✅ 3개 API response 테스트 통과
7. ✅ 기존 44개 performance_summary 테스트 회귀 없음
8. ✅ 전체 테스트 스위트 회귀 없음
9. ✅ 설계 문서 업데이트 (`paper_performance_metrics.md`)
10. ✅ `BACKLOG.md` 업데이트

---

## 11. 후속 작업 (이번 턴 범위 외)

1. **Risk-free rate 동적 설정** — rf를 env var/config에서 주입 가능하게 확장
2. **Information ratio** — benchmark 대비 tracking error 기반 위험 조정 지표
3. **Rolling Sharpe/Sortino** — fixed window rolling Sharpe
4. **AI Decision Layer feature 공급** — Sharpe/Sortino/Calmar를 agent context에 포함
5. **Admin UI 표시** — 성과 대시보드에 신규 지표 시각화
