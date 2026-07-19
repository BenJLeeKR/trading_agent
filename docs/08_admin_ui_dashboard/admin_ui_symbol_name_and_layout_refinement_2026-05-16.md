# Admin UI 화면 수정 설계서 — 종목명 컬럼 추가 / 매매 width 확대 / 필터 wrapper

**작성일**: 2026-05-16  
**대상 브랜치**: `main`

---

## 1. 수정 대상 화면 목록

| # | 화면 | 파일 | Task-1 (종목명) | Task-2 (매매) | Task-3 (필터) |
|---|------|------|----------------|---------------|---------------|
| 1 | OrdersView | [`OrdersView.tsx`](admin_ui/src/components/OrdersView.tsx) | ✅ | ✅ | — |
| 2 | OrderTrackingView | [`OrderTrackingView.tsx`](admin_ui/src/components/OrderTrackingView.tsx) | ✅ | ✅ | — |
| 3 | DecisionsView | [`DecisionsView.tsx`](admin_ui/src/components/DecisionsView.tsx) | ✅ | ✅ | — |
| 4 | AccountsView (positions) | [`AccountsView.tsx`](admin_ui/src/components/AccountsView.tsx) | ✅ (기존 → **별도 컬럼 분리**) | — | — |
| 5 | ReconciliationView (orders 테이블) | [`ReconciliationView.tsx`](admin_ui/src/components/ReconciliationView.tsx) | ✅ | — | — |
| 6 | ReconciliationView (lock 테이블) | [`ReconciliationView.tsx`](admin_ui/src/components/ReconciliationView.tsx) | ✅ | — | — |
| 7 | OperationsDashboardView | [`OperationsDashboardView.tsx`](admin_ui/src/components/OperationsDashboardView.tsx) | ✅ | ✅ | — |
| 8 | OperationsAlertsView | [`OperationsAlertsView.tsx`](admin_ui/src/components/OperationsAlertsView.tsx) | — | — | ✅ |

> **범위 밖** (이번 턴 미포함):
> - **Dashboard.tsx** — [`Dashboard.tsx`](admin_ui/src/components/Dashboard.tsx): 최근 주문 테이블(line 421-422, `OrderSummary[]`) 및 활성 잠금 테이블(line 519-520, `BlockingLockStatus[]`)에 symbol 컬럼이 있으나, summary/overview 성격으로 종목명 컬럼 추가 시 과도한 레이아웃 변경이 발생하므로 **범위 밖**.
> - **OrderDetail.tsx** — [`OrderDetail.tsx`](admin_ui/src/components/OrderDetail.tsx): detail view로 symbol이 definition list(line 116-117)에 표시되나 list/table이 아니므로 **범위 밖**.

---

## 2. 종목명 데이터 공급 방식

### 2.1 권장 방식: 백엔드 enrichment (기존 패턴 재사용)

[`PositionSnapshotView`](src/agent_trading/api/schemas.py:386-389)는 이미 `instrument_name`을 백엔드에서 enrichment하여 제공하고 있다.  
[`routes/positions.py`](src/agent_trading/api/routes/positions.py:44-47)에서 `repos.instruments.get(instrument_id)` → `inst.name`을 설정하는 패턴.

동일한 방식을 Orders / Decisions / Locks에도 적용한다.

**변경해야 할 백엔드 타입 (3개)**:

| 타입 | 파일 | 현재 구조 | 추가할 필드 |
|------|------|-----------|------------|
| [`OrderSummary`](src/agent_trading/api/schemas.py:118-137) | [`schemas.py`](src/agent_trading/api/schemas.py) | `symbol: str \| None`, 15개 필드 | `instrument_name: str \| None = None` |
| [`TradeDecisionDetail`](src/agent_trading/api/schemas.py:282-300) | [`schemas.py`](src/agent_trading/api/schemas.py) | `symbol: str` (not-null), 12개 필드 | `instrument_name: str \| None = None` |
| [`BlockingLockStatus`](src/agent_trading/api/schemas.py:244-256) | [`schemas.py`](src/agent_trading/api/schemas.py) | `symbol: str \| None`, 9개 필드 | `instrument_name: str \| None = None` |

### 2.2 백엔드 enrichment 로직

**Orders** — [`routes/orders.py:_enrich_order_summary()`](src/agent_trading/api/routes/orders.py:70-85):

```python
async def _enrich_order_summary(order, repos) -> OrderSummary:
    summary = _order_to_summary(order)
    instrument_id: UUID | None = getattr(order, "instrument_id", None)
    if instrument_id is not None:
        inst = await repos.instruments.get(instrument_id)
        if inst is not None:
            summary.symbol = inst.symbol
            summary.instrument_name = inst.name   # ← 추가
    return summary
```

> `InstrumentEntity`는 이미 `name` 속성을 가지고 있다.  
> [`repositories/contracts.py`](src/agent_trading/repositories/contracts.py:207)의 `InstrumentRepository.get(uuid)`로 조회 가능.

**Decisions** — [`routes/decisions.py`](src/agent_trading/api/routes/decisions.py):

`TradeDecisionDetail.symbol`은 decision entity에 직접 저장된 값이다.  
`instrument_name`을 얻기 위해 `repos.instruments.get_by_symbol(symbol, market)`로 조회:

```python
# decisions list endpoint 내 enrichment 루프에 추가
inst = await repos.instruments.get_by_symbol(d.symbol, d.market)
if inst is not None:
    view.instrument_name = inst.name
```

> [`InstrumentRepository.get_by_symbol`](src/agent_trading/repositories/contracts.py:214)은 `(symbol, market_code)`로 조회하는 메서드로 이미 정의되어 있음.

**Locks** — [`routes/reconciliation.py:list_blocking_locks()`](src/agent_trading/api/routes/reconciliation.py:75-89):

`BlockingLockStatus.symbol`은 lock entity에 직접 저장된 값.
lock entity에는 `account_id` 정도만 있고 market_code 정보가 없으므로 lookup이 까다롭다.

**방법**: `InstrumentRepository`에 `get_by_symbol_any_market(symbol: str) -> InstrumentEntity | None` 헬퍼를 추가하거나, 없으면 간단히 `get_by_symbol`을 시도하고 실패 시 `instrument_name=None`으로 fallback.

```python
# contracts.py: InstrumentRepository 프로토콜에 추가
async def get_by_symbol_any_market(self, symbol: str) -> InstrumentEntity | None:
    """Lookup instrument by symbol across all markets.  Returns the first match."""
    ...

# postgres/instruments.py: 구현
async def get_by_symbol_any_market(self, symbol: str) -> InstrumentEntity | None:
    row = await self._tx.connection.fetchrow(
        "SELECT * FROM trading.instruments WHERE symbol = $1 LIMIT 1",
        symbol,
    )
    return row_to_entity(row, InstrumentEntity) if row else None

# routes/reconciliation.py: locks endpoint
if lock.symbol:
    inst = await repos.instruments.get_by_symbol_any_market(lock.symbol)
    if inst is not None:
        status.instrument_name = inst.name
    # lookup 실패 시 instrument_name은 None으로 남음 → UI에서 "—" 표시
```

> **fallback 원칙**: lookup 실패 시 `instrument_name = None`으로 두고,
> UI에서 `r.instrument_name ?? "—"` 처리. "무조건 찾는다"보다 "UI가 안정적이다" 우선.

### 2.3 변경해야 할 프런트엔드 타입 (3개)

파일: [`admin_ui/src/types/api.ts`](admin_ui/src/types/api.ts)

```typescript
// OrderSummary (line 28-43) — instrument_name 추가
export interface OrderSummary {
  // ... 기존 필드 유지 ...
  instrument_name?: string | null;   // 추가
}

// TradeDecisionDetail (line 182-197) — instrument_name 추가
export interface TradeDecisionDetail {
  // ... 기존 필드 유지 ...
  instrument_name?: string | null;   // 추가
}

// BlockingLockStatus (line 93-103) — instrument_name 추가
export interface BlockingLockStatus {
  // ... 기존 필드 유지 ...
  instrument_name?: string | null;   // 추가
}
```

### 2.4 대안: 프런트엔드 측 symbol→name 매핑

**장점**: 백엔드 변경 불필요  
**단점**: 
- `GET /instruments` API 호출 추가 필요
- 종목 수 증가 시 성능 부담
- 기존 백엔드 enrichment 패턴과 일관성 없음

**→ 권장: 백엔드 enrichment (Section 2.2)** 를 채택한다.

---

## 3. 매매 컬럼 width 조정 방식

### 3.1 방법

각 View의 `side`/trade type 컬럼 정의에 `width: "90px"`를 추가하여  
`매수`/`매도` 텍스트가 줄바꿈 없이 한 줄에 표시되도록 한다.

### 3.2 변경 사항

| View | 파일 / 라인 | 현재 상태 | 변경 내용 |
|------|------------|-----------|----------|
| OrdersView | [`OrdersView.tsx:64-66`](admin_ui/src/components/OrdersView.tsx:64-66) | `{ key: "side", header: "매매", render: ... }` — width 없음 | `width: "90px"` 추가 |
| OrderTrackingView | [`OrderTrackingView.tsx:72-79`](admin_ui/src/components/OrderTrackingView.tsx:72-79) | `{ key: "side", header: "구분", render: ... }` — width 없음 | `width: "90px"` 추가 |
| DecisionsView | [`DecisionsView.tsx:118-125`](admin_ui/src/components/DecisionsView.tsx:118-125) | `{ key: "side", header: "매매", render: ... }` — width 없음 | `width: "90px"` 추가 |
| OperationsDashboardView | [`OperationsDashboardView.tsx:881`](admin_ui/src/components/OperationsDashboardView.tsx:881) | `{ key: "side", header: "매매", width: "60px" }` | `width: "60px"` → `width: "90px"` |

> `DataTable` 컴포넌트는 `width` prop을 지원하므로 컬럼 정의에 `width`만 추가하면 된다.

---

## 4. 운영경고 필터 wrapper 변경 내용

### 4.1 변경 대상

[`OperationsAlertsView.tsx:376-405`](admin_ui/src/components/OperationsAlertsView.tsx:376-405)

### 4.2 변경 전

```tsx
<div className="flex items-center gap-2 mb-4">
  {/* 버튼 그룹 (6개 필터 버튼 + 매핑) */}
</div>
```

### 4.3 변경 후

```tsx
<div className="bg-white rounded-xl border border-[#e2e8f0] p-4 mb-4">
  <div className="flex items-center gap-2">
    {/* 버튼 그룹 (변경 없음, 내부 내용 동일) */}
  </div>
</div>
```

### 4.4 효과

- 다른 View들 (`OrdersView`, `OrderTrackingView`, `DecisionsView` 등)의 FilterBar wrapper와 **시각적 일관성** 확보
- 기존의 `mb-4`가 wrapper 외부로 이동되어 전체 레이아웃 유지
- 내부 버튼 그룹 로직은 **변경 없음**

---

## 5. 수정이 필요 없는 부분

- ~~**AccountsView.tsx**~~ — [`AccountsView.tsx:219-233`](admin_ui/src/components/AccountsView.tsx:219-233): 기존에는 symbol 아래 작은 텍스트로 붙어 있었으나, **이번 작업에서 `종목` / `종목명` 별도 컬럼으로 분리**한다. (Section 7.4 참고)
- **DataTable.tsx** — 공통 테이블 컴포넌트. 컬럼 정의만 변경되므로 수정 불필요.
- **FilterBar.tsx** — OperationsAlertsView는 FilterBar 대신 자체 버튼 그룹 사용. FilterBar 자체는 수정 불필요.
- **StatusBadge.tsx** — 매매 컬럼 렌더링에서 이미 사용 중. 컴포넌트 자체 수정 불필요.
- **admin-theme.css** — Tailwind 클래스만으로 충분. CSS 변경 불필요.
- 백엔드 API 응답 호환성 — 새 `instrument_name` 필드는 **optional**이므로 기존 클라이언트에 영향 없음.

---

## 6. 테스트 계획

### 6.1 단위 테스트 / 스냅샷 테스트

| ID | 테스트 | 내용 | 검증 방법 |
|----|--------|------|----------|
| TC-01 | OrdersView 종목명 렌더 | `OrderSummary`에 `instrument_name: "삼성전자"`가 있을 때 화면에 표시 | DataTable symbol 컬럼 아래 `text-xs`로 표시 확인 |
| TC-02 | 종목명 데이터 없음 | `instrument_name`이 null/undefined일 때 `—` 표시 | 조건부 렌더링 `r.instrument_name ?? "—"` |
| TC-03 | OrderTrackingView 종목명 렌더 | `OrderSummary.instrument_name` 표시 | symbol 옆에 작은 텍스트로 표시 |
| TC-04 | DecisionsView 종목명 렌더 | `TradeDecisionDetail.instrument_name` 표시 | symbol 컬럼 아래 표시 |
| TC-05 | ReconciliationView 종목명 렌더 (orders) | `ReconcileRequiredCase.order.instrument_name` 표시 | symbol 컬럼 아래 표시 |
| TC-06 | ReconciliationView 종목명 렌더 (locks) | `BlockingLockStatus.instrument_name` 표시 | raw HTML `<td>`에 표시 |
| TC-07 | OperationsDashboardView 종목명 렌더 | `CompactOrderItem.instrument_name` 표시 | — (로컬 타입, symbol 컬럼 내 표시) |
| TC-08 | 매매 컬럼 줄바꿈 없음 | `매수`/`매도`가 한 줄로 표시 | width: 90px에서 TextOverflow 없음 확인 |
| TC-09 | 필터 wrapper 렌더 | OperationsAlertsView에 `bg-white rounded-xl border border-[#e2e8f0] p-4 mb-4` 적용 확인 |
| TC-10 | 기존 리스트 회귀 없음 | 기존 컬럼/데이터가 사라지지 않음 | 기존 테스트 통과 확인 |

### 6.2 실행 명령

```bash
# 프런트엔드 테스트
cd admin_ui && npm test

# 프런트엔드 빌드
cd admin_ui && npm run build
```

---

## 7. 실행 순서

### Step 1: 백엔드 — `schemas.py` 필드 추가

**파일**: [`src/agent_trading/api/schemas.py`](src/agent_trading/api/schemas.py)

- [`OrderSummary`](src/agent_trading/api/schemas.py:118): `instrument_name: str | None = None` 추가
- [`TradeDecisionDetail`](src/agent_trading/api/schemas.py:282): `instrument_name: str | None = None` 추가
- [`BlockingLockStatus`](src/agent_trading/api/schemas.py:244): `instrument_name: str | None = None` 추가

### Step 2: 백엔드 — enrichment 로직 추가

- [`repositories/contracts.py`](src/agent_trading/repositories/contracts.py:207): `InstrumentRepository` 프로토콜에 `get_by_symbol_any_market(symbol: str) -> InstrumentEntity | None` 메서드 추가
- [`repositories/postgres/instruments.py`](src/agent_trading/repositories/postgres/instruments.py): `get_by_symbol_any_market()` 구현 (symbol 기준 첫 매칭 row 반환, market_code 불필요)
- [`repositories/memory.py`](src/agent_trading/repositories/memory.py): InMemoryInstrumentRepository에도 동일 메서드 추가
- [`routes/orders.py:_enrich_order_summary()`](src/agent_trading/api/routes/orders.py:84): `summary.instrument_name = inst.name` 추가
- [`routes/decisions.py`](src/agent_trading/api/routes/decisions.py): decisions list endpoint에 instrument_name enrichment 루프 추가 (`get_by_symbol` 사용)
- [`routes/reconciliation.py:list_blocking_locks()`](src/agent_trading/api/routes/reconciliation.py:75-89): 각 lock에 `get_by_symbol_any_market()`로 instrument_name enrichment 추가
  > lookup 실패 시 `instrument_name=None`으로 두고 UI fallback에 맡김

### Step 3: 프런트엔드 — 타입 정의 추가

**파일**: [`admin_ui/src/types/api.ts`](admin_ui/src/types/api.ts)

- [`OrderSummary`](admin_ui/src/types/api.ts:28): `instrument_name?: string | null` 추가
- [`TradeDecisionDetail`](admin_ui/src/types/api.ts:182): `instrument_name?: string | null` 추가
- [`BlockingLockStatus`](admin_ui/src/types/api.ts:93): `instrument_name?: string | null` 추가

### Step 4: 프런트엔드 — 종목명 컬럼 추가 (7개 View)

**4-a. AccountsView: `종목` / `종목명` 컬럼 분리**

[`AccountsView.tsx:219-233`](admin_ui/src/components/AccountsView.tsx:219-233) 기존 코드는 하나의 셀에 symbol + instrument_name을 함께 표시.

**변경 전**:
```tsx
{
  key: "symbol",
  header: "종목",
  render: (r) => (
    <div>
      <div className="text-sm font-medium text-[#0f172a]">
        {r.symbol ?? truncateUuid(r.instrument_id)}
      </div>
      {r.instrument_name && (
        <div className="text-xs text-[#64748b]">{r.instrument_name}</div>
      )}
    </div>
  ),
},
```

**변경 후**:
```tsx
{
  key: "symbol",
  header: "종목",
  render: (r) => (
    <span className="text-sm font-medium text-[#0f172a]">
      {r.symbol ?? truncateUuid(r.instrument_id)}
    </span>
  ),
},
{
  key: "instrument_name",
  header: "종목명",
  render: (r) => (
    <span className="text-xs text-[#64748b]">
      {r.instrument_name ?? "—"}
    </span>
  ),
},
```

**4-b. 나머지 6개 View에 symbol 컬럼 내 `instrument_name` 표시**

| View | 컬럼 렌더링 변경 |
|------|----------------|
| OrdersView [`symbol` 컬럼](admin_ui/src/components/OrdersView.tsx:63) | `<div><div>{r.symbol}</div>{r.instrument_name && <div className="text-xs text-[#64748b]">{r.instrument_name}</div>}</div>` |
| OrderTrackingView [`symbol` 컬럼](admin_ui/src/components/OrderTrackingView.tsx:65-70) | 기존 `<span>{row.symbol}</span>` 밑에 `instrument_name` 추가 |
| DecisionsView [`symbol` 컬럼](admin_ui/src/components/DecisionsView.tsx:116) | `<div><div>{r.symbol}</div>{r.instrument_name && <div className="text-xs text-[#64748b]">{r.instrument_name}</div>}</div>` |
| ReconciliationView [`심볼` 컬럼](admin_ui/src/components/ReconciliationView.tsx:226-233) | `r.order.symbol` 밑에 `r.order.instrument_name` 추가 |
| ReconciliationView lock 테이블 [`심볼` `<th>`](admin_ui/src/components/ReconciliationView.tsx:487-500) | `<td>` 내 `lock.symbol` 밑에 `lock.instrument_name ?? "—"` 추가 (lookup 실패 fallback) |
| OperationsDashboardView [`symbol` 컬럼](admin_ui/src/components/OperationsDashboardView.tsx:880) | `CompactOrderItem`에 `instrument_name` 필드 추가 + 데이터 변환 로직에서 매핑 |

> **참고**: `CompactOrderItem`은 로컬 인터페이스이므로 [`OperationsDashboardView.tsx:55-63`](admin_ui/src/components/OperationsDashboardView.tsx:55-63)에 `instrument_name` 필드를 먼저 추가한 후, [데이터 변환 로직](admin_ui/src/components/OperationsDashboardView.tsx:562)에서 매핑해야 함.

### Step 5: 프런트엔드 — 매매 컬럼 width 조정 (4개 View)

| View | 파일 / 라인 | 변경 |
|------|------------|------|
| OrdersView | [`OrdersView.tsx:64`](admin_ui/src/components/OrdersView.tsx:64) | `width: "90px"` 추가 |
| OrderTrackingView | [`OrderTrackingView.tsx:72`](admin_ui/src/components/OrderTrackingView.tsx:72) | `width: "90px"` 추가 |
| DecisionsView | [`DecisionsView.tsx:118`](admin_ui/src/components/DecisionsView.tsx:118) | `width: "90px"` 추가 |
| OperationsDashboardView | [`OperationsDashboardView.tsx:881`](admin_ui/src/components/OperationsDashboardView.tsx:881) | `width: "60px"` → `width: "90px"` |

### Step 6: 프런트엔드 — OperationsAlertsView 필터 wrapper 적용

**파일**: [`OperationsAlertsView.tsx:376-405`](admin_ui/src/components/OperationsAlertsView.tsx:376-405)

외부 `<div>` wrapper만 추가. 내부 버튼 그룹은 **변경 없음**.

### Step 7: 테스트 실행

```bash
cd admin_ui && npm test
```

### Step 8: 빌드 확인

```bash
cd admin_ui && npm run build
```

---

## 8. 전체 변경 요약

### 백엔드 (Python)

| 파일 | 변경 유형 | 예상 라인 |
|------|----------|----------|
| [`src/agent_trading/api/schemas.py`](src/agent_trading/api/schemas.py) | `instrument_name` 필드 3개 타입에 추가 | 3개 라인 |
| [`src/agent_trading/repositories/contracts.py`](src/agent_trading/repositories/contracts.py) | `InstrumentRepository` 프로토콜에 `get_by_symbol_any_market()` 추가 | ~3개 라인 |
| [`src/agent_trading/repositories/postgres/instruments.py`](src/agent_trading/repositories/postgres/instruments.py) | `get_by_symbol_any_market()` SQL 구현 | ~8개 라인 |
| [`src/agent_trading/repositories/memory.py`](src/agent_trading/repositories/memory.py) | InMemoryInstrumentRepository에 동일 메서드 추가 | ~5개 라인 |
| [`src/agent_trading/api/routes/orders.py`](src/agent_trading/api/routes/orders.py) | `_enrich_order_summary()`에 `instrument_name` 설정 추가 | 1개 라인 |
| [`src/agent_trading/api/routes/decisions.py`](src/agent_trading/api/routes/decisions.py) | decisions list에 instrument_name enrichment 루프 추가 | ~5개 라인 |
| [`src/agent_trading/api/routes/reconciliation.py`](src/agent_trading/api/routes/reconciliation.py) | locks endpoint에 `get_by_symbol_any_market()`로 enrichment + fallback | ~5개 라인 |

### 프런트엔드 (TypeScript/React)

| 파일 | 변경 유형 | 예상 라인 |
|------|----------|----------|
| [`admin_ui/src/types/api.ts`](admin_ui/src/types/api.ts) | 3개 인터페이스에 `instrument_name` 필드 추가 | 3개 라인 |
| [`admin_ui/src/components/AccountsView.tsx`](admin_ui/src/components/AccountsView.tsx) | `종목` / `종목명` 별도 컬럼으로 분리 | ~15개 라인 |
| [`admin_ui/src/components/OrdersView.tsx`](admin_ui/src/components/OrdersView.tsx) | symbol 컬럼 render 수정 + side width 추가 | ~5개 라인 |
| [`admin_ui/src/components/OrderTrackingView.tsx`](admin_ui/src/components/OrderTrackingView.tsx) | symbol 컬럼 render 수정 + side width 추가 | ~5개 라인 |
| [`admin_ui/src/components/DecisionsView.tsx`](admin_ui/src/components/DecisionsView.tsx) | symbol 컬럼 render 수정 + side width 추가 | ~5개 라인 |
| [`admin_ui/src/components/ReconciliationView.tsx`](admin_ui/src/components/ReconciliationView.tsx) | reconcile 컬럼 + lock 테이블에 instrument_name 추가 | ~8개 라인 |
| [`admin_ui/src/components/OperationsDashboardView.tsx`](admin_ui/src/components/OperationsDashboardView.tsx) | `CompactOrderItem` + symbol 컬럼 + side width | ~6개 라인 |
| [`admin_ui/src/components/OperationsAlertsView.tsx`](admin_ui/src/components/OperationsAlertsView.tsx) | 필터 wrapper 추가 | ~3개 라인 |

---

## 9. 기대 효과

- 모든 리스트 화면에서 symbol 옆에 한글 종목명 확인 가능 → 트레이더 인식성 향상
- `매수`/`매도`가 줄바꿈 없이 깔끔하게 표시 → 가독성 개선
- 운영경고 화면 필터가 다른 화면과 시각적 일관성 확보 → UI 통일성 향상
- AccountsView의 기존 `instrument_name` 표시 패턴과 일관성 유지
- 새 필드는 optional이므로 기존 API/UI에 **하위 호환성 영향 없음**

---

## 10. 리스크 및 고려 사항

| 리스크 | 영향 | 대응 |
|--------|------|------|
| Lock entity에 market_code 없음 | `get_by_symbol(symbol, market_code)` lookup 불가 | `get_by_symbol_any_market(symbol)` 헬퍼 추가. lookup 실패 시 `instrument_name=None` fallback → UI에서 `"—"` 표시 |
| Decisions 목록 API 성능 | decisions 수가 많을 경우 N+1 쿼리 가능 | 필요한 경우 `get_instruments_by_symbols(symbols: list[str])` 배치 메서드 추가 |
| `CompactOrderItem`이 로컬 인터페이스 | 데이터 변환 로직에서 `instrument_name` 매핑 누락 위험 | 데이터 변환 시 `orderResponse.instrument_name` 포함 확인 |
| Dashboard.tsx / OrderDetail.tsx 미포함 | 추후 "여기도 종목명이 안 보인다"는 요청 가능 | 범위 밖임을 문서에 명시 (Section 1 참고) |
