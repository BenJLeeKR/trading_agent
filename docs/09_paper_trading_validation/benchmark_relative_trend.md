# Benchmark Daily Relative Trend — 설계 문서

## 1. Source Inventory

### 1.1 현재 구현 상태

| 계층 | 상태 | 설명 |
|------|------|------|
| `BenchmarkComparison` dataclass | ✅ 단일 요약 | period-level return/drawdown only, 11 fields |
| `_calc_benchmark_metrics()` | ✅ 단일 요약 | returns `(return_pct, max_drawdown_pct)` — 일별 시계열 미출력 |
| `DailyPerformancePoint` dataclass | ✅ 포트폴리오 전용 | 7 fields, benchmark-relative field 없음 |
| `get_daily_history()` | ✅ 포트폴리오 전용 | benchmark 데이터 미포함 |
| `get_performance_metrics()` | ✅ 포트폴리오 전용 | benchmark 비교 미통합 |
| `BenchmarkPriceRepository.get_price_series()` | ✅ 일별 가격 제공 | `Sequence[tuple[date, Decimal]]` — 상대 추세 계산에 충분 |
| `InMemoryBenchmarkPriceRepository` | ✅ 테스트 가능 | dict-backed, `_DEFAULT_BENCHMARK_PRICES` fixture |
| `GET /performance-benchmark` | ✅ 단일 요약 응답 | `BenchmarkComparisonView` — 시계열 없음 |
| `GET /performance-history` | ✅ 포트폴리오 전용 | `DailyPerformancePointView` — benchmark field 없음 |

### 1.2 Confirmed Gaps

| Gap | 심각도 | 설명 |
|-----|--------|------|
| 일별 benchmark return 시계열 | ❌ 미존재 | portfolio 대비 상대 수익률 추세를 일별로 볼 수 없음 |
| 일별 excess return | ❌ 미존재 | period 단위 초과수익만 있고 daily cumulative excess 없음 |
| 일별 relative drawdown | ❌ 미존재 | period 최대값만 있고 daily running drawdown 비교 없음 |
| Outperformance streak | ❌ 미존재 | 연속 양수/음수 excess return 일수 추적 없음 |
| Cumulative spread trend | ❌ 미존재 | 기간 누적 excess return의 추세선 없음 |

### 1.3 Enablers (Already Present)

| Enabler | 위치 | 설명 |
|---------|------|------|
| `BenchmarkPriceRepository` Protocol | `benchmark_comparison.py:86` | `get_price_series()` → `Sequence[tuple[date, Decimal]]` |
| `InMemoryBenchmarkPriceRepository` | `benchmark_comparison.py:138` | dict-backed, 테스트 가능 |
| `_DEFAULT_BENCHMARK_PRICES` | `benchmark_comparison.py:108` | KOSPI 9 + KOSDAQ 9 points fixture |
| `get_daily_history()` | `performance_summary.py:612` | `total_equity` 포함 `DailyPerformancePoint` 반환 |
| `_calc_equity_metrics()` | `performance_summary.py:324` | portfolio equity return/drawdown 순수 함수 |
| Pure function 패턴 | 두 모듈 모두 | `_calc_*()` → service method → API endpoint |
| 테스트 인프라 | `test_benchmark_comparison.py:64` | `_seed_repos()` + `_setup_service()` context manager |

---

## 2. 설계 고정사항 (보정사항 반영 완료)

### 2.1 최종 Dataclass: `RelativeBenchmarkPoint` (9개 필드 확정)

**파일**: `src/agent_trading/services/benchmark_comparison.py` (기존 파일에 추가)

```python
@dataclass(slots=True, frozen=True)
class RelativeBenchmarkPoint:
    date: date
    portfolio_return_pct: Decimal | None         # portfolio cumulative return from starting point
    benchmark_return_pct: Decimal | None          # benchmark cumulative return from starting point
    excess_return_pct: Decimal | None             # portfolio_return_pct - benchmark_return_pct
    portfolio_drawdown_pct: Decimal | None        # current portfolio drawdown from running peak
    benchmark_drawdown_pct: Decimal | None        # current benchmark drawdown from running peak
    relative_drawdown_pct: Decimal | None         # portfolio_drawdown_pct - benchmark_drawdown_pct
    outperformance_streak: int                    # consecutive days excess_return >0 (+) or <0 (-)
    benchmark_data_available: bool                # True if benchmark price exists on this date
```

**필드별 의미**:

| 필드 | 의미 | null 가능 |
|------|------|-----------|
| `date` | 해당 날짜 | 항상 있음 |
| `portfolio_return_pct` | 기준일 대비 portfolio 누적 수익률(%) | O — starting equity 없음 |
| `benchmark_return_pct` | 기준일 대비 benchmark 누적 수익률(%) | O — starting price 없음 |
| `excess_return_pct` | portfolio 초과 수익률(%), 양수=outperform | O |
| `portfolio_drawdown_pct` | portfolio running peak 대비 하락률(%) | O |
| `benchmark_drawdown_pct` | benchmark running peak 대비 하락률(%) | O |
| `relative_drawdown_pct` | portfolio_drawdown - benchmark_drawdown. 양수=portfolio가 더 나쁨, 음수=portfolio가 더 방어적 | O |
| `outperformance_streak` | 연속 excess_return 양수/음수 일수. 양수=outperform streak, 음수=underperform streak, 0=리셋 | 항상 있음 |
| `benchmark_data_available` | 해당 날짜 benchmark price 존재 여부 | 항상 있음 |

### 2.2 `outperformance_streak` 부호/리셋 규칙

| 조건 | streak 변화 |
|------|------------|
| `excess_return_pct > 0` AND 이전 streak >= 0 | `streak = previous_streak + 1` |
| `excess_return_pct > 0` AND 이전 streak < 0 | `streak = 1` (underperform → outperform 전환) |
| `excess_return_pct < 0` AND 이전 streak <= 0 | `streak = previous_streak - 1` |
| `excess_return_pct < 0` AND 이전 streak > 0 | `streak = -1` (outperform → underperform 전환) |
| `excess_return_pct == 0` | `streak = 0` (리셋) |
| `excess_return_pct is None` | `streak = 0` (리셋) |

### 2.3 Starting Point (기준선) 선택 규칙

**Portfolio 기준선**:
1. `start_date` 당일 `total_equity` 우선
2. 없으면 `start_date` 이후 첫 번째 유효한 `total_equity`가 있는 날짜
3. 전혀 없으면 모든 날짜의 `portfolio_return_pct = None`

**Benchmark 기준선**:
1. `start_date` 당일 benchmark price 우선
2. 없으면 `start_date` 이후 첫 번째 유효한 price가 있는 날짜
3. 전혀 없으면 모든 날짜의 `benchmark_return_pct = None`

**기준선 이후 계산식**:
```
portfolio_return_pct[t] = (equity[t] - starting_equity) / starting_equity * 100
benchmark_return_pct[t] = (price[t] - starting_price) / starting_price * 100
excess_return_pct[t] = portfolio_return_pct[t] - benchmark_return_pct[t]
```

### 2.4 Missing Data 정책

| 항목 | 정책 |
|------|------|
| benchmark price 없는 날 | `benchmark_return_pct=None`, `excess_return_pct=None`, `benchmark_drawdown_pct=None`, `relative_drawdown_pct=None`, `benchmark_data_available=False`. portfolio field는 유지 |
| portfolio data 없는 날 | `portfolio_return_pct=None`, `excess_return_pct=None`, `portfolio_drawdown_pct=None`, `relative_drawdown_pct=None`. benchmark field는 유지 |
| 보간(interpolation) | ❌ **금지** |
| 이후 유효 benchmark 날짜에서 cumulative 계산 | 최초 기준선 기준으로 계속 계산, 재정렬하지 않음 |

### 2.5 Date Coverage 정책

**선택: A안** — `portfolio/benchmark 데이터가 있는 날짜의 union만 반환`

- `get_daily_history()`의 결과 날짜와 benchmark price series의 날짜를 union
- 두 집합 중 하나라도 데이터가 있는 날짜만 `RelativeBenchmarkPoint`로 반환
- `[start_date, end_date]` 전체 캘린더 날짜를 생성하지 않음
- 포트폴리오/벤치마크 데이터가 전혀 없는 날짜는 응답에서 제외

### 2.6 API 계약

| 항목 | 정책 |
|------|------|
| 날짜 정렬 | **오름차순** (오래된 날짜 → 최신 날짜) |
| 빈 결과 | `{"points": [], ...}` — `total_days=0` |
| invalid benchmark_code | 기존 `get_benchmark_comparison()`과 동일: `ValueError` |
| account_id / strategy_id / date validation | 기존 performance endpoints와 동일한 FastAPI validation |
| 기존 endpoint 영향 | **없음** — 신규 endpoint만 추가 |

---

## 3. 신규 Pure Helper: `_calc_relative_benchmark_points()`

**파일**: `src/agent_trading/services/benchmark_comparison.py`

```python
def _calc_relative_benchmark_points(
    daily_points: Sequence[DailyPerformancePoint],
    benchmark_prices: Sequence[tuple[date, Decimal]],
    period_start: date,
    period_end: date,
) -> Sequence[RelativeBenchmarkPoint]:
```

**알고리즘**:

1. `daily_points`를 date → `DailyPerformancePoint` dict로 변환
2. `benchmark_prices`를 date → `Decimal` dict로 변환
3. Union date set 구성: `set(daily_points dates) ∪ set(benchmark_prices dates)`
4. Union dates를 오름차순 정렬
5. 기준선(Starting Point) 선택:
   - Portfolio: union dates 중 첫 번째 유효 equity 날짜
   - Benchmark: union dates 중 첫 번째 유효 price 날짜
6. 각 날짜 순회:
   a. `portfolio_equity` = `daily_points_dict[date].total_equity` or None
   b. `benchmark_price` = `benchmark_prices_dict[date]` or None
   c. Starting point 기준 cumulative return 계산
   d. Running peak 추적 → drawdown 계산
   e. Excess return 부호 기반 streak 계산
7. `RelativeBenchmarkPoint` 리스트 반환

---

## 4. Service Method: `get_benchmark_daily_history()`

**파일**: `src/agent_trading/services/benchmark_comparison.py`

```python
class BenchmarkComparisonService:
    # 기존: get_benchmark_comparison() — 유지

    async def get_benchmark_daily_history(
        self,
        account_id: UUID,
        strategy_id: UUID | None,
        benchmark_code: str,
        period_start: date,
        period_end: date,
    ) -> Sequence[RelativeBenchmarkPoint]:
        """일별 portfolio vs benchmark 상대 성과 시계열을 반환합니다.

        1. PerformanceSummaryService.get_daily_history() 호출
        2. BenchmarkPriceRepository.get_price_series() 호출
        3. _calc_relative_benchmark_points()로 결합
        """
```

**데이터 흐름**:

```
Client Request
  → BenchmarkComparisonService.get_benchmark_daily_history()
    → PerformanceSummaryService.get_daily_history()  → Sequence[DailyPerformancePoint]
    → BenchmarkPriceRepository.get_price_series()    → Sequence[tuple[date, Decimal]]
    → _calc_relative_benchmark_points()              → Sequence[RelativeBenchmarkPoint]
  → JSON Response
```

---

## 5. Pydantic Schemas

**파일**: `src/agent_trading/api/schemas.py`

```python
class RelativeBenchmarkPointView(BaseModel):
    date: date
    portfolio_return_pct: float | None
    benchmark_return_pct: float | None
    excess_return_pct: float | None
    portfolio_drawdown_pct: float | None
    benchmark_drawdown_pct: float | None
    relative_drawdown_pct: float | None
    outperformance_streak: int
    benchmark_data_available: bool


class BenchmarkHistoryResponse(BaseModel):
    account_id: str
    strategy_id: str | None
    benchmark_code: str
    period_start: date
    period_end: date
    total_days: int
    points: list[RelativeBenchmarkPointView]
```

---

## 6. API Endpoint: `GET /performance-benchmark-history`

**파일**: `src/agent_trading/api/routes/performance.py`

```python
@router.get("/performance-benchmark-history")
async def get_performance_benchmark_history(
    account_id: str,
    benchmark_code: str = "KOSPI",
    strategy_id: str | None = None,
    start_date: str = Query(...),
    end_date: str = Query(...),
    request: Request,
) -> BenchmarkHistoryResponse:
```

**Query Parameters**:

| Parameter | Type | Required | Default | 설명 |
|-----------|------|----------|---------|------|
| `account_id` | str | ✅ | — | 계좌 UUID |
| `benchmark_code` | str | ❌ | `"KOSPI"` | 기준 지수 코드 |
| `strategy_id` | str | ❌ | `None` | 전략 필터 |
| `start_date` | str (YYYY-MM-DD) | ✅ | — | 시작일 |
| `end_date` | str (YYYY-MM-DD) | ✅ | — | 종료일 |

**기존 endpoint 영향 없음**:

| Endpoint | 성격 | 변경 |
|----------|------|------|
| `GET /performance-summary` | 계좌/전략 요약 | ❌ 유지 |
| `GET /performance-history` | 포트폴리오 일별 시계열 | ❌ 유지 |
| `GET /performance-metrics` | 기간 기반 지표 | ❌ 유지 |
| `GET /performance-benchmark` | benchmark 단일 요약 비교 | ❌ 유지 |
| `GET /performance-benchmark-history` | **🔹 신규** benchmark 일별 상대 추세 | 신규 추가 |
| `GET /paper-go-no-go` | Paper Gate 평가 | ❌ 유지 |

---

## 7. 변경 파일 목록

| 파일 | 변경 유형 | 설명 |
|------|-----------|------|
| `src/agent_trading/services/benchmark_comparison.py` | 🔹 수정 | `RelativeBenchmarkPoint` dataclass 추가, `_calc_relative_benchmark_points()` pure helper 추가, `get_benchmark_daily_history()` service method 추가 |
| `src/agent_trading/api/schemas.py` | 🔹 수정 | `RelativeBenchmarkPointView` + `BenchmarkHistoryResponse` Pydantic model 추가 |
| `src/agent_trading/api/routes/performance.py` | 🔹 수정 | `GET /performance-benchmark-history` endpoint 추가 |
| `tests/services/test_benchmark_comparison.py` | 🔹 수정 | Pure function tests + integration tests 추가 |

**변경 불필요 파일** (의도적 제외):
- `performance_summary.py` — 변경 없음, 기존 `get_daily_history()` 재사용
- `domain/models.py` — 변경 없음, service-layer dataclass로 충분
- `domain/entities.py` — 변경 없음, DB entity 변경 없음
- `db/migrations/` — 변경 없음, 기존 데이터만으로 계산
- `admin_ui/` — 변경 없음 (작업 제약)
- `brokers/` — 변경 없음 (작업 제약)
- `PaperGateService`, `PaperExitEvaluator`, `LiveGateEvaluator` — 변경 없음, 기존 benchmark summary semantics 유지
- `DailyPerformancePoint` — 변경 없음, 기존 용도 유지

---

## 8. 테스트 계획

### 8.1 Pure Function Tests: `TestCalcRelativeBenchmarkPoints` (최소 9개)

| 테스트 | 설명 | 검증 포인트 |
|--------|------|-------------|
| `test_basic_outperform` | portfolio +10%, benchmark +5% | excess_return=+5%, streak 양수 |
| `test_underperform` | portfolio +2%, benchmark +5% | excess_return=-3%, streak 음수 |
| `test_missing_benchmark_dates` | benchmark data 없는 날 | `benchmark_data_available=False`, portfolio field 유지 |
| `test_start_equity_zero` | 시작 equity 0 | `portfolio_return_pct=None`, `benchmark_data_available=True` |
| `test_start_price_zero` | 시작 price 0 | `benchmark_return_pct=None` |
| `test_outperformance_streak_consecutive` | 3일 연속 양수 excess_return | streak=1→2→3 |
| `test_streak_reset_on_zero` | excess_return=0 | streak=0 |
| `test_streak_sign_flip` | 양수→음수 전환 | streak=1→ -1 |
| `test_drawdown_tracking` | equity peak 100→80→90 | `portfolio_drawdown_pct` 0→20→10 |
| `test_relative_drawdown` | portfolio drawdown 20%, benchmark 10% | `relative_drawdown_pct=+10%` |
| `test_no_overlap` | portfolio 날짜와 benchmark 날짜 완전 불일치 | union 기반, partial 처리 |
| `test_empty_daily_points` | portfolio 데이터 없음 | 빈 리스트 |
| `test_empty_benchmark_prices` | benchmark 데이터 없음 | `benchmark_data_available=False` |
| `test_relative_drawdown_negative` | portfolio drawdown 5%, benchmark 15% | `relative_drawdown_pct=-10%` (portfolio 방어적) |

### 8.2 Integration Tests: `TestGetBenchmarkDailyHistory` (최소 4개)

| 테스트 | 설명 | 검증 포인트 |
|--------|------|-------------|
| `test_basic_history` | 정상 시나리오 | points 개수, excess_return 정확성, 오름차순 정렬 |
| `test_invalid_benchmark_code` | 존재하지 않는 benchmark_code | ValueError |
| `test_strategy_filter` | strategy_id 제공 | 해당 전략만 집계 |
| `test_no_data` | 데이터 없는 기간 | 빈 리스트, `total_days=0` |

### 8.3 기존 테스트 유지

기존 10개 테스트(`TestCalcBenchmarkMetrics` 5개 + `TestGetBenchmarkComparison` 5개)는 **전혀 변경하지 않음**.

---

## 9. 실행 단계

### Step 1: 설계 문서 최종 확정 ← 현재 위치

### Step 2: Pure Helper + Dataclass 구현 (`benchmark_comparison.py`)

1. `RelativeBenchmarkPoint` dataclass 추가
2. `_calc_relative_benchmark_points()` 구현

### Step 3: Service Method 구현 (`benchmark_comparison.py`)

1. `get_benchmark_daily_history()` 구현

### Step 4: Pydantic Schema 추가 (`schemas.py`)

1. `RelativeBenchmarkPointView` + `BenchmarkHistoryResponse` 추가

### Step 5: API Endpoint 추가 (`routes/performance.py`)

1. `GET /performance-benchmark-history` 추가

### Step 6: Pure Function 테스트 작성

1. `TestCalcRelativeBenchmarkPoints` — 최소 14개 테스트

### Step 7: Integration 테스트 작성

1. `TestGetBenchmarkDailyHistory` — 최소 4개 테스트

### Step 8: 전체 테스트 실행

```bash
cd /workspace/agent_trading && python3 -m pytest tests/services/test_benchmark_comparison.py -v 2>&1
```

### Step 9: BACKLOG 업데이트

---

## 10. 응답 예시 (JSON)

```json
{
  "account_id": "550e8400-e29b-41d4-a716-446655440000",
  "strategy_id": null,
  "benchmark_code": "KOSPI",
  "period_start": "2026-05-01",
  "period_end": "2026-05-10",
  "total_days": 8,
  "points": [
    {
      "date": "2026-05-01",
      "portfolio_return_pct": 0.0,
      "benchmark_return_pct": 0.0,
      "excess_return_pct": 0.0,
      "portfolio_drawdown_pct": 0.0,
      "benchmark_drawdown_pct": 0.0,
      "relative_drawdown_pct": 0.0,
      "outperformance_streak": 0,
      "benchmark_data_available": true
    },
    {
      "date": "2026-05-02",
      "portfolio_return_pct": 1.5,
      "benchmark_return_pct": 1.0,
      "excess_return_pct": 0.5,
      "portfolio_drawdown_pct": 0.0,
      "benchmark_drawdown_pct": 0.0,
      "relative_drawdown_pct": 0.0,
      "outperformance_streak": 1,
      "benchmark_data_available": true
    },
    {
      "date": "2026-05-04",
      "portfolio_return_pct": 0.5,
      "benchmark_return_pct": null,
      "excess_return_pct": null,
      "portfolio_drawdown_pct": 0.985,
      "benchmark_drawdown_pct": null,
      "relative_drawdown_pct": null,
      "outperformance_streak": 0,
      "benchmark_data_available": false
    }
  ]
}
```

---

## 11. 제약 조건 점검 (최종)

| 제약 조건 | 상태 | 설명 |
|-----------|------|------|
| 기존 `GET /performance-benchmark` semantics 유지 | ✅ 유지 | 단일 요약 endpoint, gate 의존성 모두 유지 |
| `PaperGateService` / `PaperExitEvaluator` / `LiveGateEvaluator` 기존 benchmark summary 의존성 유지 | ✅ 유지 | `BenchmarkComparison` dataclass, `get_benchmark_comparison()` 변경 없음 |
| `DailyPerformancePoint` 기존 용도 유지 | ✅ 유지 | benchmark-relative history는 별도 dataclass/response |
| benchmark missing data 보간 금지 | ✅ 준수 | partial policy, interpolation 없음 |
| DB migration 금지 | ✅ 준수 | 기존 데이터만으로 계산 |
| admin UI 변경 금지 | ✅ 준수 | API layer까지만 |
| Paper/live 동일 시스템 원칙 | ✅ 준수 | benchmark_comparison.py는 공통, mode-agnostic |
| Additive 변경만 수행 | ✅ 준수 | 신규 dataclass/method/endpoint만 추가 |
| Pure helper → Service → API 순서 | ✅ 준수 | Step 2→3→4→5 순서 |
| 기존 numeric/history endpoint 회귀 없음 | ✅ 보장 | 기존 endpoint/테스트 전혀 변경 없음 |
