# Benchmark History API Test 보강 + Date Coverage Semantics 정리

> **조건부 승인 반영 (2026-05-10)**
> 6개 보정사항을 반영한 최종 계획. 핵심 방향은 "현재 구현 semantics를 문서/API/test로 정확히 고정".

## 1. 분석 결과

### 1.1 Date Coverage Semantics: A안 (Union) 채택

**선택: A안 — 현재 구현 유지 (data-date union)**

**근거**:

| 고려사항 | 내용 |
|----------|------|
| `get_daily_history()` 동작 | [`PerformanceSummaryService.get_daily_history()`](src/agent_trading/services/performance_summary.py:693-732)는 **calendar iteration** (`current_date += timedelta(days=1)`)으로 모든 날짜를 포함함 |
| 결과 | Portfolio 데이터가 모든 calendar date를 커버하므로, `union(portfolio_dates, benchmark_dates)`는 실질적으로 calendar와 동일 |
| 주말/휴일 처리 | Portfolio에는 모든 날짜가 있고, Benchmark에는 trading day만 있음 → union 결과에 주말 포함됨 |
| `outperformance_streak` | 주말/휴일은 `excess_return_pct=None` → `streak=0` 으로 리셋되지 않음 (의도된 동작) |
| `total_days` | `len(points)` = 데이터가 있는 날짜 수 (실제 포인트 수) |

**일치시킬 대상**: 설계 문서의 Step 4를 A안(union)으로 수정하고, `total_days` 필드만 추가

### 1.2 설계 문서 vs 구현 불일치 항목

| # | 항목 | 설계 문서 | 현재 구현 | 결정 |
|---|------|-----------|-----------|------|
| 1 | Date coverage | "period_start부터 period_end까지 **모든 날짜** 순회" (B안) | `sorted(set(portfolio) | set(benchmark))` (A안) | **문서 수정 → A안** |
| 2 | `total_days` 필드 | `BenchmarkHistoryResponse`에 `total_days: int` 있음 | 없음 | **구현에 추가** |
| 3 | Parameter명 | `daily_points` | `portfolio_points` | **문서 수정** (의미상 동일) |
| 4 | Parameter 순서 | `benchmark_code` → `strategy_id` → `start_date` → `end_date` | `account_id` → `start_date` → `end_date` → `benchmark_code` → `strategy_id` | **문서 수정** (기존 endpoint 패턴 따름) |
| 5 | Field명 | `period_start` / `period_end` | `start_date` / `end_date` | **문서 수정** (기존 `GET /performance-history`와 일관성) |

### 1.3 변경 범위

```
변경 파일 (3개):
  1. plans/benchmark_relative_trend.md  — 설계 문서 수정 (4개 항목)
  2. src/agent_trading/api/schemas.py  — total_days 필드 추가
  3. tests/api/test_performance_benchmark_history.py  — 신규 (API 레벨 테스트)

변경 불필요 (0개):
  - benchmark_comparison.py  — date coverage 로직 변경 없음
  - routes/performance.py    — endpoint 로직 변경 없음
  - test_benchmark_comparison.py  — 서비스 레벨 테스트는 기존으로 충분

Migration: 불필요
DB 변경: 불필요
```

---

## 2. 변경 상세

### Step 1: 설계 문서 수정 (`plans/benchmark_relative_trend.md`)

**Section 4 — Algorithm Step 4** (line 210):
```diff
- 4. `period_start`부터 `period_end`까지 모든 날짜 순회
+ 4. portfolio / benchmark 데이터가 있는 날짜의 합집합(union)만 순회
+    (단, portfolio 조회 결과(`get_daily_history()`)가 이미 calendar range를
+     포함하므로, 실질적으로는 calendar 내 데이터 존재일)
```

**Section 4 — Parameter명** (line 196):
```diff
-     daily_points: Sequence[DailyPerformancePoint],
+     portfolio_points: Sequence[DailyPerformancePoint],
```

**Section 5 — Service Method** (line 241-248):
```diff
     async def get_benchmark_daily_history(
         self,
         account_id: UUID,
         strategy_id: UUID | None,
+        start_date: date,
+        end_date: date,
         benchmark_code: str,
-        period_start: date,
-        period_end: date,
     ) -> list[RelativeBenchmarkPoint]:
```

**Section 6 — `BenchmarkHistoryResponse`** (line 292-302):
```diff
 class BenchmarkHistoryResponse(BaseModel):
     account_id: str
+    start_date: date
+    end_date: date
     strategy_id: str | None
     benchmark_code: str
-    period_start: date
-    period_end: date
     total_days: int
     points: list[RelativeBenchmarkPointView]
```

**Section 7 — Endpoint** (line 315-323):
```diff
 async def get_performance_benchmark_history(
     account_id: str = Query(...),
+    start_date: str = Query(...),
+    end_date: str = Query(...),
     benchmark_code: str = Query("KOSPI"),
     strategy_id: str | None = Query(None),
-    start_date: str = Query(...),
-    end_date: str = Query(...),
     repos: RepositoryContainer = Depends(get_repos),
 ) -> BenchmarkHistoryResponse:
```

### Step 2: `BenchmarkHistoryResponse`에 `total_days` 추가

**파일**: [`src/agent_trading/api/schemas.py`](src/agent_trading/api/schemas.py:561-573)

```diff
 class BenchmarkHistoryResponse(BaseModel):
     account_id: str
     start_date: date
     end_date: date
     strategy_id: str | None
     benchmark_code: str
+    total_days: int
     points: list[RelativeBenchmarkPointView]
```

**Endpoint** [`routes/performance.py`](src/agent_trading/api/routes/performance.py:458-465):
```diff
     return BenchmarkHistoryResponse(
         account_id=account_id,
         start_date=sd,
         end_date=ed,
         strategy_id=strategy_id,
         benchmark_code=benchmark_code,
+        total_days=len(points),
         points=[RelativeBenchmarkPointView.model_validate(p) for p in points],
     )
```

### Step 3: API Test 파일 신규 생성

**파일**: `tests/api/test_performance_benchmark_history.py` (신규)

**Fixture**: 기존 [`tests/api/conftest.py`](tests/api/conftest.py)의 `client` fixture 재사용

**Test Matrix** (7 tests):

| # | Test | 검증 내용 | HTTP expected |
|---|------|-----------|---------------|
| 1 | `test_normal_response` | 정상 응답: 200 + 모든 필드 존재 + total_days == len(points) | 200 |
| 2 | `test_invalid_account_id` | 잘못된 UUID 형식 | 400 |
| 3 | `test_invalid_date_format` | 잘못된 date 형식 (start_date / end_date 각각) | 400 |
| 4 | `test_start_date_after_end_date` | 시작일 > 종료일 | 400 |
| 5 | `test_invalid_benchmark_code` | 존재하지 않는 benchmark_code | 400 |
| 6 | `test_points_ascending_order` | points 배열 date 오름차순 정렬 | 200 |
| 7 | `test_date_coverage_union` | date coverage가 portfolio/benchmark union 기반임을 검증 | 200 |

**Test 7 상세 (date coverage union 검증)**:
- `GET /performance-benchmark-history` 호출
- 반환된 모든 point의 date가 `[start_date, end_date]` 범위 내에 있는지 확인
- 각 point에 대해 `portfolio_return_pct` 또는 `benchmark_return_pct` 중 하나는 `None`이 아닌지 확인 (union 특성)
- `total_days`와 `len(points)`가 일치하는지 확인

---

## 3. 데이터 흐름 (Mermaid)

```mermaid
flowchart LR
    TC[TestClient] -->|GET /performance-benchmark-history| EP[Endpoint]
    EP -->|validate params| VAL{Valid?}
    VAL -->|No| 400[400 HTTPException]
    VAL -->|Yes| SVC[BenchmarkComparisonService\n.get_benchmark_daily_history]
    SVC --> PSS[PerformanceSummaryService\n.get_daily_history]
    SVC --> BPR[InMemoryBenchmarkPriceRepository\n.get_price_series]
    PSS --> DPP[Sequence[DailyPerformancePoint]\ncalendar-based, all dates]
    BPR --> BP[Sequence[tuple[date, Decimal]]\ntrading days only]
    SVC -->|_calc_relative_benchmark_points| CALC
    CALC -->|union of portfolio + benchmark dates| POINTS[list[RelativeBenchmarkPoint]]
    EP -->|total_days=len(points| RESP[BenchmarkHistoryResponse\n200 OK]
```

---

## 4. API 테스트 상세 설계

### Test 1: 정상 응답

```python
def test_normal_response(self, client: TestClient) -> None:
    """정상 파라미터 → 200 + 모든 필드 존재 + total_days == len(points)."""
    account_id = _get_account_id(client)
    response = client.get(
        f"/performance-benchmark-history"
        f"?account_id={account_id}"
        f"&start_date=2026-05-01"
        f"&end_date=2026-05-08"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["account_id"] == account_id
    assert data["start_date"] == "2026-05-01"
    assert data["end_date"] == "2026-05-08"
    assert data["benchmark_code"] == "BENCHMARK_KOSPI"
    assert data["strategy_id"] is None
    assert data["total_days"] == len(data["points"])
    assert isinstance(data["total_days"], int)
    assert data["total_days"] >= 0
```

### Test 2-5: Validation Error

```python
def test_invalid_account_id(self, client: TestClient) -> None:
    response = client.get(
        "/performance-benchmark-history"
        "?account_id=not-a-uuid"
        "&start_date=2026-05-01"
        "&end_date=2026-05-08"
    )
    assert response.status_code == 400
    assert "Invalid account_id" in response.text

def test_invalid_start_date(self, client: TestClient) -> None:
    account_id = _get_account_id(client)
    response = client.get(
        f"/performance-benchmark-history"
        f"?account_id={account_id}"
        f"&start_date=invalid"
        f"&end_date=2026-05-08"
    )
    assert response.status_code == 400

def test_invalid_end_date(self, client: TestClient) -> None:
    account_id = _get_account_id(client)
    response = client.get(
        f"/performance-benchmark-history"
        f"?account_id={account_id}"
        f"&start_date=2026-05-01"
        f"&end_date=invalid"
    )
    assert response.status_code == 400

def test_start_date_after_end_date(self, client: TestClient) -> None:
    account_id = _get_account_id(client)
    response = client.get(
        f"/performance-benchmark-history"
        f"?account_id={account_id}"
        f"&start_date=2026-05-08"
        f"&end_date=2026-05-01"
    )
    assert response.status_code == 400

def test_invalid_benchmark_code(self, client: TestClient) -> None:
    account_id = _get_account_id(client)
    response = client.get(
        f"/performance-benchmark-history"
        f"?account_id={account_id}"
        f"&start_date=2026-05-01"
        f"&end_date=2026-05-08"
        f"&benchmark_code=INVALID"
    )
    assert response.status_code == 400
```

### Test 6: Points 정렬

```python
def test_points_ascending_order(self, client: TestClient) -> None:
    account_id = _get_account_id(client)
    response = client.get(
        f"/performance-benchmark-history"
        f"?account_id={account_id}"
        f"&start_date=2026-05-01"
        f"&end_date=2026-05-13"
    )
    assert response.status_code == 200
    data = response.json()
    dates = [p["date"] for p in data["points"]]
    assert dates == sorted(dates)
```

### Test 7: Date Coverage Union 검증

```python
def test_date_coverage_union(self, client: TestClient) -> None:
    """모든 point의 date가 [start_date, end_date] 이내이며,
    portfolio/benchmark 데이터가 있는 날짜의 union으로 구성됨."""
    account_id = _get_account_id(client)
    response = client.get(
        f"/performance-benchmark-history"
        f"?account_id={account_id}"
        f"&start_date=2026-05-01"
        f"&end_date=2026-05-13"
    )
    assert response.status_code == 200
    data = response.json()
    start = date.fromisoformat(data["start_date"])
    end = date.fromisoformat(data["end_date"])
    for p in data["points"]:
        d = date.fromisoformat(p["date"])
        assert start <= d <= end
        # 최소한 portfolio_return_pct 또는 benchmark_return_pct 중 하나는 존재
        # (union 특성상 데이터가 있는 날짜만 포함)
        assert (
            p["portfolio_return_pct"] is not None
            or p["benchmark_return_pct"] is not None
            or p["benchmark_data_available"] is True
        )
    assert data["total_days"] == len(data["points"])
```

---

## 5. 변경 파일 요약

| 파일 | 변경 유형 | 내용 |
|------|-----------|------|
| `plans/benchmark_relative_trend.md` | 수정 | Section 4/5/6/7 문서 보정 (5개 항목) |
| `src/agent_trading/api/schemas.py` | 수정 (+1 line) | `BenchmarkHistoryResponse`에 `total_days: int` 추가 |
| `src/agent_trading/api/routes/performance.py` | 수정 (+1 line) | `BenchmarkHistoryResponse(... total_days=len(points))` 추가 |
| `tests/api/test_performance_benchmark_history.py` | **신규** | 7개 API 레벨 테스트 |

**변경 불필요 확인**:
- `benchmark_comparison.py` — date coverage 로직 변경 없음 (A안 유지)
- `test_benchmark_comparison.py` — 서비스 레벨 테스트는 기존 19개로 충분
- DB migration — 불필요
- `GET /performance-benchmark` — 변경 금지 (user 요청)

---

## 6. Test 실행 계획

```bash
# 서비스 레벨 테스트 (기존, regression)
cd /workspace/agent_trading && python -m pytest tests/services/test_benchmark_comparison.py -v

# 신규 API 테스트
cd /workspace/agent_trading && python -m pytest tests/api/test_performance_benchmark_history.py -v

# API 전체 테스트 (regression)
cd /workspace/agent_trading && python -m pytest tests/api/ -v

# 전체 테스트
cd /workspace/agent_trading && python -m pytest -x
```

---

## 7. 완료 조건

1. ✅ 설계 문서 보정 완료 (Section 4/5/6/7)
2. ✅ `total_days` 필드 추가 및 endpoint 반영
3. ✅ 7개 API 테스트 통과
4. ✅ 기존 29개 benchmark comparison 테스트 regression 통과
5. ✅ 8-section 보고서 완료
