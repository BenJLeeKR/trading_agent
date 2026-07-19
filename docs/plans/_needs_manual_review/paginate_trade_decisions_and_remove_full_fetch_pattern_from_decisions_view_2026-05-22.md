# Admin UI Decisions Page 서버사이드 Pagination 적용 보고서

## 1. 개요

Admin UI의 `의사결정(Decisions)` 페이지가 느린 근본 원인을 분석하고, 서버사이드 pagination을 적용하여 성능을 개선한 작업 보고서.

## 2. 문제 분석

### 2.1 근본 원인 (3-Layer)

| Layer | 문제 | 영향 |
|-------|------|------|
| **API** | `GET /trade-decisions`가 `limit`/`offset` 없이 전체 레코드 반환 | DB에서 수백~수천 건의 decision을 한 번에 로드 |
| **N+1 Query** | `_enrich_decision_detail()`이 각 decision마다 `instruments.get_by_symbol()` 개별 호출 | 597개 decision = 597개 개별 SQL 쿼리 |
| **Frontend** | `DecisionsView`가 전체 데이터를 받아서 `filteredDecisions.slice()`로 클라이언트 pagination | 초기 로딩 시간 증가, 페이지 전환 시 불필요한 데이터 유지 |

### 2.2 증상

- 페이지 로딩 시 수 초 ~ 수십 초 소요
- 페이지 전환 시 지연 (전체 데이터를 이미 가지고 있지만, React re-render 비용)
- 불필요한 네트워크 대역폭 사용

## 3. 적용한 수정 사항

### 3.1 Fix A: 서버사이드 Pagination (`GET /trade-decisions`)

**변경 파일:** [`src/agent_trading/api/routes/decisions.py`](src/agent_trading/api/routes/decisions.py)

- `response_model`을 `list[TradeDecisionDetail]` → `PaginatedTradeDecisionsResponse`로 변경
- `limit` (기본 50, 범위 1~500) 및 `offset` (기본 0) query parameter 추가
- `_enrich_decision_detail()` 함수 제거 (N+1 문제 해결)
- `_to_detail()`에 `instrument_name` optional parameter 추가

### 3.2 Fix B: SQL LEFT JOIN으로 N+1 제거

**변경 파일:** [`src/agent_trading/repositories/postgres/trade_decisions.py`](src/agent_trading/repositories/postgres/trade_decisions.py)

- `list_all_paginated()` 메서드 추가
- SQL LEFT JOIN으로 instrument name을 단일 쿼리로 resolve
- `SELECT COUNT(*)`로 total count 별도 조회
- `decision_context_id` optional filter 지원

### 3.3 Fix C: Protocol 및 In-Memory 구현

**변경 파일:**
- [`src/agent_trading/repositories/contracts.py`](src/agent_trading/repositories/contracts.py): `TradeDecisionRepository` protocol에 `list_all_paginated()` 추가
- [`src/agent_trading/repositories/memory.py`](src/agent_trading/repositories/memory.py): `InMemoryTradeDecisionRepository`에 동일 메서드 구현

### 3.4 Fix D: Response Schema

**변경 파일:** [`src/agent_trading/api/schemas.py`](src/agent_trading/api/schemas.py)

```python
class PaginatedTradeDecisionsResponse(BaseModel):
    items: list[TradeDecisionDetail]
    total: int
    limit: int
    offset: int
```

### 3.5 Fix E: Frontend API Client

**변경 파일:**
- [`admin_ui/src/types/api.ts`](admin_ui/src/types/api.ts): `PaginatedTradeDecisionsResponse` TypeScript interface 추가
- [`admin_ui/src/api/client.ts`](admin_ui/src/api/client.ts): `getTradeDecisions()`에 `limit`/`offset` parameter 추가, `URLSearchParams`로 query string 구성

### 3.6 Fix F: Page-Driven Fetch

**변경 파일:** [`admin_ui/src/components/DecisionsView.tsx`](admin_ui/src/components/DecisionsView.tsx)

- `totalCount` state 추가
- `useEffect` dependency를 `[contextIdParam, currentPage, pageSize]`로 변경
- Fetch 시 `(currentPage - 1) * pageSize`를 offset으로 사용
- `totalPages`를 서버 `totalCount` 기반으로 계산
- `DataTable`에 `totalItems={totalCount}` 전달
- `pagedDecisions` 변수 제거 (더 이상 클라이언트 slice 불필요)

## 4. 테스트 결과

### 4.1 백엔드 테스트 (`test_postgres_trade_decisions.py`)

| 테스트 | 결과 |
|--------|------|
| `test_list_all_paginated_basic` | ✅ 통과 |
| `test_list_all_paginated_limit_offset` | ✅ 통과 (5개 decision 삽입, 3페이지 검증) |
| `test_list_all_paginated_with_context_filter` | ✅ 통과 (contextId 필터 + pagination) |
| 기존 7개 테스트 | ✅ 통과 |

### 4.2 프론트 테스트 (`decisions.test.tsx`)

| 시나리오 | 결과 |
|----------|------|
| DecisionsView with data | ✅ 통과 |
| DecisionsView confidence color | ✅ 통과 |
| DecisionsView empty list | ✅ 통과 |
| DecisionsView detail panel (2 tests) | ✅ 통과 |
| DecisionsView side filter | ✅ 통과 |
| DecisionsView symbol search | ✅ 통과 |
| DecisionsView agent runs panel (5 tests) | ✅ 통과 |
| DecisionsView contextId query param (2 tests) | ✅ 통과 |
| DecisionsView pagination footer | ✅ 통과 |
| DecisionsView EI interpreted labels (2 tests) | ✅ 통과 |
| Recent Events Section (4 tests) | ✅ 통과 |

**총 22개 테스트 전부 통과**

## 5. 변경된 파일 목록

| 파일 | 변경 유형 | 설명 |
|------|-----------|------|
| `src/agent_trading/repositories/contracts.py` | 수정 | `list_all_paginated()` protocol 메서드 추가 |
| `src/agent_trading/repositories/postgres/trade_decisions.py` | 수정 | SQL LEFT JOIN + pagination 구현 |
| `src/agent_trading/repositories/memory.py` | 수정 | In-memory pagination 구현 |
| `src/agent_trading/api/schemas.py` | 수정 | `PaginatedTradeDecisionsResponse` 모델 추가 |
| `src/agent_trading/api/routes/decisions.py` | 수정 | limit/offset 파라미터, N+1 제거 |
| `admin_ui/src/types/api.ts` | 수정 | TypeScript interface 추가 |
| `admin_ui/src/api/client.ts` | 수정 | limit/offset 파라미터 추가 |
| `admin_ui/src/components/DecisionsView.tsx` | 수정 | Page-driven fetch로 변경 |
| `admin_ui/src/__tests__/test-utils/fixtures.ts` | 수정 | `mockTradeDecisions` → paginated wrapper |
| `admin_ui/src/__tests__/decisions.test.tsx` | 수정 | 모든 mock 응답 paginated 형식으로 변경 |
| `tests/repositories/test_postgres_trade_decisions.py` | 수정 | 3개 pagination 테스트 추가 |

## 6. 성능 예상 효과

| 지표 | Before | After | 예상 개선 |
|------|--------|-------|-----------|
| API 응답 시간 (597건) | ~수 초 (N+1: 597개 쿼리) | ~수십 ms (1개 JOIN 쿼리) | **~100x** |
| 네트워크 전송량 | ~수 MB | ~수십 KB (50건/page) | **~90%** 감소 |
| 초기 페이지 로딩 | 수 초 | < 1초 | **즉시** |
| 페이지 전환 | 클라이언트 slice (즉시) | 서버 재조회 (수십 ms) | **유사** |
