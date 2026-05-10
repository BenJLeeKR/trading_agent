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
| `InMemoryBenchmarkPriceRepository` | ✅ 테스트 가능 | dict-backed, _DEFAULT_BENCHMARK_PRICES fixture |
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
| `DailyPerformancePoint` benchmark field | ❌ 미존재 | portfolio equity만 있고 benchmark 비교 field 없음 |

### 1.3 Enablers (Already Present)

| Enabler | 위치 | 설명 |
|---------|------|------|
| `BenchmarkPriceRepository` Protocol | `benchmark_comparison.py:86` | `get_price_series()` → `Sequence[tuple[date, Decimal]]` |
| `InMemoryBenchmarkPriceRepository` | `benchmark_comparison.py:138` | dict-backed, 테스트 가능 |
| `_DEFAULT_BENCHMARK_PRICES` | `benchmark_comparison.py:108` | KOSPI 9 + KOSDAQ 9 points fixture |
| `get_daily_history()` | `performance_summary.py:612` | `total_equity` 포함 `DailyPerformancePoint` 반환 |
| `_calc_equity_metrics()` | `performance_summary.py:324` | portfolio equity return/drawdown 순수 함수 |
| Pure function 패턴 | 두 모듈 모두 | `_calc*()` → service method → API endpoint |
| 테스트 인프라 | `test_benchmark_comparison.py:64` | `_seed_repos()` + `_setup_service()` context manager |

---

## 2. 설계

### 2.1 신규 Dataclass: `RelativeBenchmarkPoint`

**파일**: `src/agent_trading/services/benchmark_comparison.py` (기존 파일에 추가)

```python
@dataclass(slots=True, frozen=True)
class RelativeBenchmarkPoint:
    date: date
    portfolio_return_pct: Decimal | None         # cumulative portfolio return from period_start
    benchmark_return_pct: Decimal | None          # cumulative benchmark return from period_start
    excess_return_pct: Decimal | None             # portfolio_return_pct - benchmark_return_pct
    portfolio_drawdown_pct: Decimal | None        # current portfolio drawdown from running peak
    benchmark_drawdown_pct: Decimal | None        # current benchmark drawdown from running peak
    relative_drawdown_pct: Decimal | None         # portfolio_drawdown_pct - benchmark_drawdown_pct
    outperformance_streak: int                    # consecutive days excess_return > 0 (positive) or < 0 (negative), 0 if == 0
    benchmark_data_available: bool                # True if benchmark price exists for this date
```

**최종 필드 목록 (고정)**:

| # | 필드 | 타입 | null 가능 | 설명 |
|---|------|------|-----------|------|
| 1 | `date` | `date` | ❌ | 기준일 |
| 2 | `portfolio_return_pct` | `Decimal \| None` | O (starting_equity=0 or missing) | 기간 시작일 대비 누적 portfolio 수익률 (%) |
| 3 | `benchmark_return_pct` | `Decimal \| None` | O (price missing or zero) | 기간 시작일 대비 누적 benchmark 수익률 (%) |
| 4 | `excess_return_pct` | `Decimal \| None` | O (둘 중 하나 null) | portfolio_return_pct - benchmark_return_pct |
| 5 | `portfolio_drawdown_pct` | `Decimal \| None` | O | portfolio running peak 대비 하락률 (%) |
| 6 | `benchmark_drawdown_pct` | `Decimal \| None` | O | benchmark running peak 대비 하락률 (%) |
| 7 | `relative_drawdown_pct` | `Decimal \| None` | O | portfolio_drawdown_pct - benchmark_drawdown_pct |
| 8 | `outperformance_streak` | `int` | ❌ (0 가능) | 연속 양수/음수 excess_return 일수 |
| 9 | `benchmark_data_available` | `bool` | ❌ | 해당 날짜 benchmark price 존재 여부 |

> **portfolio_equity와 benchmark_price는 응답에서 제외**: 이 trend는 상대 성과 해석이 목적이므로 raw equity/price 노출은 불필요. `GET /performance-history`에서 portfolio equity는 이미 제공 중.

### 2.2 Outperformance Streak 부호/리셋 규칙

| 상황 | streak 변화 |
|------|-----------|
| `excess_return_pct > 0` (양수) | 직전 streak >= 0 → `streak += 1`, 직전 streak < 0 → `streak = 1` |
| `excess_return_pct < 0` (음수) | 직전 streak <= 0 → `streak -= 1`, 직전 streak > 0 → `streak = -1` |
| `excess_return_pct == 0` | `streak = 0` (리셋) |
| `excess_return_pct is None` (data missing) | `streak = 0` (리셋, 정보 부족) |

**부호 해석**:
- `streak > 0`: N일 연속 benchmark 대비 outperform (portfolio 수익률이 benchmark보다 높음)
- `streak < 0`: N일 연속 benchmark 대비 underperform (portfolio 수익률이 benchmark보다 낮음)
- `streak == 0`: 당일 excess return이 0이거나 data 부족으로 판단 불가

### 2.3 Portfolio/Benchmark 기준선 (Starting Point) 선택 규칙

```
period_start = start_date (API query param)

starting_equity = period_start 시점의 total_equity
  1. period_start에 daily_history data가 있으면 → 해당 equity 사용
  2. 없으면 → period_start 이후 가장 빠른 유효 equity 날짜 사용
  3. equity data가 전혀 없으면 (기간 내 equity 데이터 0건) → portfolio_return_pct = None

starting_price = period_start 시점의 benchmark_price
  1. period_start에 benchmark price가 있으면 → 해당 price 사용
  2. 없으면 → period_start 이후 가장 빠른 유효 price 날짜 사용
  3. price data가 전혀 없으면 (기간 내 benchmark data 0건) → benchmark_return_pct = None
```

**계산식**:
```
portfolio_return_pct[t] = (equity[t] - starting_equity) / starting_equity * 100
  - starting_equity == 0 → None (division guard)

benchmark_return_pct[t] = (price[t] - starting_price) / starting_price * 100
  - starting_price == 0 → None (division guard)

excess_return_pct[t] = portfolio_return_pct[t] - benchmark_return_pct[t]
  - 둘 중 하나 None → None
```

**기준일 시작점 선택 이유**:
- period_start는 사용자가 명시적으로 지정한 분석 기간 시작점
- period_start에 equity/price가 없어도 이후 첫 유효값을 기준으로 삼아 기간 내 가장 긴 시계열을 제공
- equity/price가 전혀 없는 경우는 유효한 비교가 불가능하므로 None 반환

### 2.4 Missing Benchmark Data 정책 (보간 금지)

| 상황 | 처리 |
|------|------|
| portfolio equity O, benchmark price O | 정상 계산, `benchmark_data_available=True` |
| portfolio equity O, benchmark price X | `benchmark_return_pct=None`, `excess_return_pct=None`, `benchmark_drawdown_pct=None`, `relative_drawdown_pct=None`, `benchmark_data_available=False`, `portfolio_drawdown_pct`는 계산 유지, `outperformance_streak=0` (리셋) |
| portfolio equity X, benchmark price O | `portfolio_return_pct=None`, `excess_return_pct=None`, `portfolio_drawdown_pct=None`, `relative_drawdown_pct=None`, `benchmark_drawdown_pct`는 계산 유지, `benchmark_data_available=True`, `outperformance_streak=0` (리셋) |
| 둘 다 X | 모든 field None, `benchmark_data_available=False`, `outperformance_streak=0` |

**핵심 원칙**:
- **보간(interpolation) 금지**: 누락된 benchmark price를 이전/이후 값으로 채우지 않음
- **누적 계산에 영향 없음**: benchmark data가 없는 날은 benchmark 관련 field만 None, portfolio 자체 계산(drawdown 등)은 정상 수행
- **Streak 리셋**: missing data로 인해 streak 판단이 불가능하므로 0으로 리셋

### 2.5 Relative Drawdown 부호 해석

| 부호 | 의미 | 해석 |
|------|------|------|
| `relative_drawdown_pct > 0` | portfolio_drawdown > benchmark_drawdown | portfolio가 benchmark보다 더 많이 하락 (상대적으로 성과 나쁨) |
| `relative_drawdown_pct == 0` | portfolio_drawdown == benchmark_drawdown | portfolio와 benchmark 하락률 동일 |
| `relative_drawdown_pct < 0` | portfolio_drawdown < benchmark_drawdown | portfolio 하락이 benchmark보다 적음 (상대적으로 방어 잘함) |

**예시**:
- portfolio drawdown -5%, benchmark drawdown -3% → `relative_drawdown_pct = -2.0` (portfolio가 benchmark보다 2%p 덜 하락 = 방어 잘함)
- portfolio drawdown -8%, benchmark drawdown -3% → `relative_drawdown_pct = 5.0` (portfolio가 benchmark보다 5%p 더 하락 = 방어 못함)

> **참고**: drawdown 자체는 음수 값(하락)이지만, 계산식에서 양수로 표현된다. `relative_drawdown_pct = portfolio_drawdown_pct - benchmark_drawdown_pct`로 계산하므로 양수일수록 portfolio가 benchmark 대비 더 많이 하락했음을 의미한다.

### 2.6 정렬 및 빈 결과 정책

| 상황 | 정책 | 기존 endpoint 일관성 |
|------|------|---------------------|
| **날짜 정렬 순서** | 오름차순 (오래된 날짜 → 최신 날짜) | `GET /performance-history`와 동일 |
| **빈 결과 (equity/price 모두 없음)** | `points=[]` 반환, 에러 아님 | `GET /performance-history`와 동일 (에러가 아니라 빈 리스트) |
| **유효하지 않은 benchmark_code** | `400 HTTPException` | `GET /performance-benchmark`와 동일 (ValueError → 400 변환) |
| **유효하지 않은 UUID** | `400 HTTPException` | 모든 performance endpoint와 동일 |
| **start_date > end_date** | `400 HTTPException` | 모든 performance endpoint와 동일 |
| **benchmark_code = "KOSPI" 및 "KOSDAQ"만 유효** | `400 HTTPException` + valid codes 목록 포함 | `GET /performance-benchmark`와 동일 |

---

## 3. 변경 파일 목록

| 파일 | 변경 유형 | 설명 |
|------|-----------|------|
| `src/agent_trading/services/benchmark_comparison.py` | 🔹 수정 | `RelativeBenchmarkPoint` dataclass 추가, `_calc_relative_benchmark_points()` pure helper 추가, `get_benchmark_daily_history()` service method 추가 |
| `src/agent_trading/api/schemas.py` | 🔹 수정 | `RelativeBenchmarkPointView` + `BenchmarkHistoryResponse` Pydantic model 추가 |
| `src/agent_trading/api/routes/performance.py` | 🔹 수정 | `GET /performance-benchmark-history` endpoint 추가 |
| `tests/services/test_benchmark_comparison.py` | 🔹 수정 | `TestCalcRelativeBenchmarkPoints` pure function tests + `TestGetBenchmarkDailyHistory` integration tests 추가 |
| `plans/BACKLOG.md` | 🔹 수정 | Backlog 업데이트 (신규 작업 승격 기록) |

**변경 불필요 파일**:
- `src/agent_trading/services/performance_summary.py` — 변경 없음 (기존 `get_daily_history()` 재사용)
- `src/agent_trading/domain/models.py` — 변경 없음 (dataclass는 service 레이어에 추가)
- `src/agent_trading/domain/entities.py` — 변경 없음 (DB entity 변경 없음)
- `db/migrations/` — 변경 없음 (기존 데이터만으로 계산, 저장소 변경 없음)
- `admin_ui/` — 변경 없음 (작업 제약)
- `brokers/` — 변경 없음 (작업 제약)
- `scripts/` — 변경 없음 (작업 제약)
- `src/agent_trading/config/settings.py` — 변경 없음 (새로운 env var 불필요)

---

## 4. 신규 Pure Helper: `_calc_relative_benchmark_points()`

**파일**: `src/agent_trading/services/benchmark_comparison.py`

```python
def _calc_relative_benchmark_points(
    portfolio_points: Sequence[DailyPerformancePoint],
    benchmark_prices: Sequence[tuple[date, Decimal]],
    start_date: date,
    end_date: date,
) -> list[RelativeBenchmarkPoint]:
```

**알고리즘**:

1. `portfolio_points`를 `dict[date, DailyPerformancePoint]`로 변환
2. `benchmark_prices`를 `dict[date, Decimal]`로 변환
3. 기준선 결정:
   - `starting_equity` = start_date equity, 없으면 첫 유효 equity
   - `starting_price` = start_date price, 없으면 첫 유효 price
4. **Data-date Union** 순회 — `portfolio_by_date.keys() ∪ benchmark_by_date.keys()`의
   정렬 결과를 `[start_date, end_date]` 범위로 필터링
   (캘린더 전체 날짜를 생성하지 않음)
5. 각 날짜에 대해:
   a. `portfolio_equity` = `daily_points_dict[date].total_equity` or None
   b. `benchmark_price` = `benchmark_prices_dict[date]` or None
   c. `benchmark_data_available = benchmark_price is not None`
   d. 기준선 기반 cumulative return 계산 (division guard)
   e. 각각 running peak 추적하여 drawdown 계산
   f. `relative_drawdown_pct = portfolio_drawdown_pct - benchmark_drawdown_pct`
   g. excess_return 부호 기반 outperformance_streak 계산 (2.2 규칙)
   h. missing data 처리 (2.4 정책)
6. `RelativeBenchmarkPoint` 리스트 반환

**순수 함수 검증 포인트**:
- 단조 증가 equity → excess_return 양수
- equity peak 후 decline → portfolio_drawdown_pct 증가
- benchmark price 없음 → benchmark field None + benchmark_data_available=False
- 시작일 equity/price 0 → division guard (return None)
- 연속 양수 excess_return → outperformance_streak 증가
- 연속 음수 → underperformance_streak (음수)
- excess_return 0 → streak=0

---

## 5. 신규 Service Method: `get_benchmark_daily_history()`

**파일**: `src/agent_trading/services/benchmark_comparison.py`

```python
class BenchmarkComparisonService:
    # 기존: get_benchmark_comparison() 유지

    async def get_benchmark_daily_history(
        self,
        account_id: UUID,
        start_date: date,
        end_date: date,
        benchmark_code: str,
        strategy_id: UUID | None = None,
    ) -> list[RelativeBenchmarkPoint]:
        """일별 portfolio vs benchmark 상대 성과 시계열을 반환합니다.

        1. PerformanceSummaryService.get_daily_history() 호출
        2. BenchmarkPriceRepository.get_price_series() 호출
        3. _calc_relative_benchmark_points()로 결합
        """
```

**데이터 흐름**:

```
Client Request
    → GET /performance-benchmark-history?account_id=X&start_date=...&end_date=...&benchmark_code=KOSPI&strategy_id=...
    → BenchmarkComparisonService.get_benchmark_daily_history()
        → PerformanceSummaryService.get_daily_history() → Sequence[DailyPerformancePoint]
        → BenchmarkPriceRepository.get_price_series() → Sequence[tuple[date, Decimal]]
        → _calc_relative_benchmark_points() → list[RelativeBenchmarkPoint]
    → BenchmarkHistoryResponse JSON
```

---

## 6. 신규 Pydantic Schema

**파일**: `src/agent_trading/api/schemas.py`

```python
class RelativeBenchmarkPointView(BaseModel):
    """GET /performance-benchmark-history 응답의 단일 일별 상대 성과 포인트."""

    model_config = ConfigDict(from_attributes=True)

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
    """GET /performance-benchmark-history — 일별 portfolio vs benchmark 상대 성과 시계열.

    ``total_days``는 ``points`` 개수와 동일하며, ``start_date~end_date``의
    캘린더 일수가 아닙니다. date coverage는 **Data-date Union** 정책을 따릅니다
    (portfolio/benchmark 데이터가 있는 날짜의 합집합).
    """

    account_id: str
    start_date: date
    end_date: date
    strategy_id: str | None
    benchmark_code: str
    total_days: int
    points: list[RelativeBenchmarkPointView]
```

---

## 7. 신규 API Endpoint: `GET /performance-benchmark-history`

**파일**: `src/agent_trading/api/routes/performance.py`

```python
@router.get(
    "/performance-benchmark-history",
    response_model=BenchmarkHistoryResponse,
)
async def get_performance_benchmark_history(
    account_id: str = Query(..., description="Account UUID"),
    start_date: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end_date: str = Query(..., description="End date (YYYY-MM-DD)"),
    benchmark_code: str = Query("KOSPI", description=f"Benchmark code ({sorted(VALID_BENCHMARK_CODES)}). Default: KOSPI"),
    strategy_id: str | None = Query(None, description="Optional strategy UUID"),
    repos: RepositoryContainer = Depends(get_repos),
) -> BenchmarkHistoryResponse:
```

**Query Parameters** (기존 ``GET /performance-history``와 동일한 순서):

| Parameter | Type | Required | Default | 설명 |
|-----------|------|----------|---------|------|
| `account_id` | str | ✅ | — | 계좌 UUID |
| `start_date` | str (YYYY-MM-DD) | ✅ | — | 시작일 |
| `end_date` | str (YYYY-MM-DD) | ✅ | — | 종료일 |
| `benchmark_code` | str | ❌ | `"KOSPI"` | 기준 지수 코드 |
| `strategy_id` | str | ❌ | `None` | 전략 필터 |

**Validation (기존 endpoint와 동일 패턴)**:

1. `account_id` → `UUID` 변환 실패 → 400
2. `start_date` / `end_date` → `date.fromisoformat()` 실패 → 400
3. `start_date > end_date` → 400
4. `benchmark_code not in VALID_BENCHMARK_CODES` → 400 (valid codes 명시)
5. `strategy_id` 제공 시 UUID 변환 실패 → 400

**에러 핸들링 패턴** (기존 `GET /performance-benchmark`과 동일):
```python
try:
    aid = UUID(account_id)
except ValueError:
    raise HTTPException(status_code=400, detail="Invalid account_id UUID")
# ... 동일 패턴 각 파라미터에 적용
```

**기존 endpoint와의 관계**:

| Endpoint | 성격 | 유지 여부 |
|----------|------|-----------|
| `GET /performance-summary` | 계좌/전략 요약 | ✅ 유지 |
| `GET /performance-history` | 포트폴리오 일별 시계열 | ✅ 유지 |
| `GET /performance-metrics` | 기간 기반 지표 | ✅ 유지 |
| `GET /performance-benchmark` | benchmark 단일 요약 비교 | ✅ 유지 |
| `GET /performance-benchmark-history` | **🔹 신규** benchmark 일별 상대 추세 | 신규 추가 |
| `GET /paper-go-no-go` | Paper Gate 평가 | ✅ 유지 |

---

## 8. 응답 예시 (JSON)

```json
{
  "account_id": "550e8400-e29b-41d4-a716-446655440000",
  "strategy_id": null,
  "benchmark_code": "KOSPI",
  "period_start": "2026-05-01",
  "period_end": "2026-05-10",
  "total_days": 10,
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
      "benchmark_return_pct": 0.77,
      "excess_return_pct": 0.73,
      "portfolio_drawdown_pct": 0.0,
      "benchmark_drawdown_pct": 0.0,
      "relative_drawdown_pct": 0.0,
      "outperformance_streak": 1,
      "benchmark_data_available": true
    },
    {
      "date": "2026-05-03",
      "portfolio_return_pct": 0.5,
      "benchmark_return_pct": 0.38,
      "excess_return_pct": 0.12,
      "portfolio_drawdown_pct": 0.99,
      "benchmark_drawdown_pct": 0.57,
      "relative_drawdown_pct": 0.42,
      "outperformance_streak": 2,
      "benchmark_data_available": true
    },
    {
      "date": "2026-05-04",
      "portfolio_return_pct": 0.5,
      "benchmark_return_pct": null,
      "excess_return_pct": null,
      "portfolio_drawdown_pct": 0.99,
      "benchmark_drawdown_pct": null,
      "relative_drawdown_pct": null,
      "outperformance_streak": 0,
      "benchmark_data_available": false
    }
  ]
}
```

---

## 9. 테스트 계획

### 9.1 Pure Function Tests: `TestCalcRelativeBenchmarkPoints`

| # | 테스트 | 설명 | 검증 포인트 |
|---|--------|------|-------------|
| 1 | `test_basic_relative_points` | 기본 시나리오: portfolio 상승, benchmark 상승 | excess_return 양수, streak 양수 |
| 2 | `test_portfolio_underperforms` | portfolio < benchmark | excess_return 음수, streak 음수 |
| 3 | `test_missing_benchmark_dates` | benchmark data 없는 날 (주말) partial 처리 | benchmark field None, `benchmark_data_available=False` |
| 4 | `test_missing_portfolio_dates` | portfolio equity 없는 날 | portfolio field None, streak=0 |
| 5 | `test_start_equity_zero` | 시작 equity 0 → division guard | portfolio_return_pct=None |
| 6 | `test_start_price_zero` | 시작 benchmark price 0 → division guard | benchmark_return_pct=None |
| 7 | `test_outperformance_streak` | 연속 양수/음수/0 excess_return | streak 증가/리셋/부호 규칙 검증 |
| 8 | `test_drawdown_tracking` | equity peak 후 decline | portfolio_drawdown_pct 증가 |
| 9 | `test_empty_data` | daily_points/benchmark_prices 둘 다 빔 | 빈 리스트 반환 |
| 10 | `test_no_overlap` | portfolio 날짜와 benchmark 날짜 완전 불일치 | partial 처리 검증 |
| 11 | `test_date_order` | 결과 오름차순 정렬 확인 | 모든 point date가 이전보다 큼 |
| 12 | `test_relative_drawdown_sign` | relative_drawdown_pct 부호 해석 검증 | portfolio_drawdown > benchmark_drawdown → 양수 |

### 9.2 Integration Tests: `TestGetBenchmarkDailyHistory`

| # | 테스트 | 설명 | 검증 포인트 |
|---|--------|------|-------------|
| 1 | `test_basic_history` | 정상 시나리오 | points 개수, excess_return 정확성 |
| 2 | `test_invalid_benchmark_code` | 존재하지 않는 benchmark_code | ValueError |
| 3 | `test_strategy_filter` | strategy_id 제공 | 해당 전략만 집계 |
| 4 | `test_longer_period` | 2주 이상 기간 | 다수 point, streak 변화 |
| 5 | `test_empty_result` | equity/price 모두 없음 | points=[] 빈 리스트 |

### 9.3 테스트 패턴

기존 [`test_benchmark_comparison.py`](tests/services/test_benchmark_comparison.py)의 `_seed_repos()` + `_setup_service()` 패턴 재사용.

---

## 10. 실행 단계

### Step 1: Pure Helper + Dataclass 추가
**파일**: `src/agent_trading/services/benchmark_comparison.py`
1. `RelativeBenchmarkPoint` dataclass 추가 (필드 9개 고정)
2. `_calc_relative_benchmark_points()` pure helper 구현
   - 기준선 alignment (2.3 규칙)
   - Cumulative return / drawdown / excess return 계산
   - Outperformance streak 추적 (2.2 규칙)
   - Missing data partial 처리 (2.4 정책)
   - relative_drawdown_pct 부호 (2.5 해석)
   - 날짜 오름차순 정렬

### Step 2: Service Method 추가
**파일**: `src/agent_trading/services/benchmark_comparison.py`
1. `BenchmarkComparisonService.get_benchmark_daily_history()` 구현
   - `PerformanceSummaryService.get_daily_history()` 호출
   - `BenchmarkPriceRepository.get_price_series()` 호출
   - `_calc_relative_benchmark_points()` 호출

### Step 3: Pydantic Schema 추가
**파일**: `src/agent_trading/api/schemas.py`
1. `RelativeBenchmarkPointView` 추가 (9개 필드)
2. `BenchmarkHistoryResponse` 추가

### Step 4: API Endpoint 추가
**파일**: `src/agent_trading/api/routes/performance.py`
1. `GET /performance-benchmark-history` endpoint 추가
   - `benchmark_code` default="KOSPI" (기존 endpoint는 required, 추세 조회에서는 default 제공)
   - 기존 `GET /performance-benchmark`과 동일한 validation/에러 패턴 사용

### Step 5: Pure Function 테스트
**파일**: `tests/services/test_benchmark_comparison.py`
1. `TestCalcRelativeBenchmarkPoints` 클래스 추가 (최소 12개 pure function 테스트)

### Step 6: Integration 테스트
**파일**: `tests/services/test_benchmark_comparison.py`
1. `TestGetBenchmarkDailyHistory` 클래스 추가 (최소 5개 integration 테스트)
2. 기존 `_seed_repos()` + `_setup_service()` 패턴 재사용

### Step 7: 전체 테스트 실행 + BACKLOG 업데이트
```bash
cd /workspace/agent_trading && python3 -m pytest tests/services/test_benchmark_comparison.py -v 2>&1
cd /workspace/agent_trading && python3 -m pytest tests/api/test_inspection.py -v 2>&1
```

---

## 11. 제약 조건 점검

| 제약 조건 | 상태 | 설명 |
|-----------|------|------|
| 기존 endpoint semantics 유지 | ✅ | 5개 기존 endpoint 변경 없음, 신규 endpoint만 추가 |
| `GET /performance-benchmark` 변경 금지 | ✅ | 기존 단일 요약 endpoint는 그대로 유지 |
| PaperGate / PaperExit / LiveGate 의존 semantics 변경 금지 | ✅ | gate 코드 전혀 수정하지 않음 |
| `DailyPerformancePoint` 기존 용도 유지 | ✅ | 신규 `RelativeBenchmarkPoint`는 별도 dataclass |
| Benchmark missing data 보간 금지 | ✅ | None 처리로 명시적 금지 |
| DB migration 추가 금지 | ✅ | 기존 데이터만으로 계산, 저장소 변경 없음 |
| Admin UI 변경 금지 | ✅ | API layer까지만 변경 |
| Additive 변경만 수행 | ✅ | 기존 파일에 추가만, 구조 변경 없음 |
| Paper/live 동일 시스템 원칙 | ✅ | Repository Protocol 기반, paper/live 모두 동일 로직 |
| Broker submit semantics 변경 금지 | ✅ | broker 코드 전혀 변경 없음 |
| Hard guardrail/reconciliation 경계 변경 금지 | ✅ | guardrail/reconciliation 코드 전혀 변경 없음 |
| Live 실계정 검증 금지 | ✅ | 테스트는 InMemory 기반 |

---

## 12. 완료 조건

1. ✅ `RelativeBenchmarkPoint` dataclass — 9개 필드 명시적 고정, `benchmark_comparison.py`에 추가
2. ✅ `_calc_relative_benchmark_points()` pure helper — 최소 12개 순수 함수 테스트 통과
3. ✅ `get_benchmark_daily_history()` service method — 최소 5개 통합 테스트 통과
4. ✅ `RelativeBenchmarkPointView` + `BenchmarkHistoryResponse` Pydantic schema — `schemas.py`에 추가
5. ✅ `GET /performance-benchmark-history` endpoint — `routes/performance.py`에 추가
6. ✅ 기존 endpoint 회귀 테스트 통과 (test_benchmark_comparison.py 기존 10개 + test_inspection.py 유지)
7. ✅ `plans/BACKLOG.md` 업데이트

---

## 13. 후속 작업 (이번 턴 범위 외)

- Benchmark price source 실제 연동 (현재는 InMemory fixture만 있음)
- Sharpe / Sortino / Calmar ratio (V2 설계 문서 P2)
- AI Decision Layer에 benchmark 상대 추세 feature 공급
- Admin UI에 benchmark-relative history 차트 추가
