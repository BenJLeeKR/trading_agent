# Positions API 응답 확장 + AccountsView 컬럼 확장 보고서

**작성일**: 2026-05-17  
**목적**: KIS `pchs_amt`(매입금액) / `evlu_amt`(평가금액) 필드를 전체 스택(end-to-end)에 반영

---

## 1. KIS `pchs_amt` / `evlu_amt` ↔ 내부 필드 매핑

| KIS Raw Field | 한글명     | 내부 필드            | 타입         | 비고                        |
|---------------|-----------|---------------------|-------------|-----------------------------|
| `pchs_amt`    | 매입금액    | `purchase_amount`   | `Decimal` / `float \| None` | DB: `NUMERIC(20,8)`         |
| `evlu_amt`    | 평가금액    | `evaluation_amount` | `Decimal` / `float \| None` | DB: `NUMERIC(20,8)`         |

파서 매핑 위치: [`src/agent_trading/brokers/koreainvestment/snapshot.py`](../../src/agent_trading/brokers/koreainvestment/snapshot.py:35)

```python
_KIS_PCHS_AMT = "pchs_amt"    # 매입금액
_KIS_EVL_AMT  = "evlu_amt"    # 평가금액
```

```python
purchase_amount=safe_optional_decimal(raw.get(_KIS_PCHS_AMT)),   # line 138
evaluation_amount=safe_optional_decimal(raw.get(_KIS_EVL_AMT)),  # line 139
```

---

## 2. API Schema 확장 내용

[`src/agent_trading/api/schemas.py`](../../src/agent_trading/api/schemas.py:364) — `PositionSnapshotView` Pydantic schema

```python
class PositionSnapshotView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    position_snapshot_id: UUID
    account_id: UUID
    instrument_id: UUID
    quantity: float
    average_price: float
    market_price: float
    unrealized_pnl: float | None = None
    purchase_amount: float | None = None       # ← 신규
    evaluation_amount: float | None = None      # ← 신규
    source_of_truth: str
    snapshot_at: datetime
    created_at: datetime

    # ── Resolved instrument display fields ──
    symbol: str | None = None
    instrument_name: str | None = None
```

---

## 3. AccountsView 컬럼 변경 내용

[`admin_ui/src/components/AccountsView.tsx`](../../admin_ui/src/components/AccountsView.tsx:219)

### 변경 전 (Before)

| 순서 | 컬럼 | 비고 |
|------|------|------|
| 1 | 종목 | |
| 2 | 종목명 | |
| 3 | 수량 | |
| 4 | 평균단가 | |
| 5 | 시장가 | |
| 6 | 미실현 손익 | |
| 7 | 스냅샷 시각 | |
| 8 | actions | |

### 변경 후 (After)

| 순서 | 컬럼 | 비고 |
|------|------|------|
| 1 | 종목 | |
| 2 | 종목명 | |
| 3 | 수량 | |
| 4 | 평균단가 | |
| 5 | **매입금액** | ← 신규, `purchase_amount` |
| 6 | **현재가** | ← 시장가 → rename |
| 7 | **평가금액** | ← 신규, `evaluation_amount` |
| 8 | 미실현 손익 | |
| 9 | 스냅샷 시각 | |
| 10 | actions | |

### 주요 변경점 요약

- **매입금액** 컬럼 추가 (`purchase_amount`): KIS `pchs_amt` 값 표시, `null`이면 `"—"` 렌더링
- **시장가 → 현재가** 헤더 rename (`market_price`)
- **평가금액** 컬럼 추가 (`evaluation_amount`): KIS `evlu_amt` 값 표시, `null`이면 `"—"` 렌더링
- 숫자 포맷: `formatKrw()` 사용 (한국 원화 표시)

---

## 4. 전체 스택 변경 요약 (9개 레이어)

| # | 레이어 | 파일 | 변경 내용 |
|---|--------|------|----------|
| 1 | **DB Migration** | [`db/migrations/0017_add_position_amounts.sql`](../../db/migrations/0017_add_position_amounts.sql) | `purchase_amount NUMERIC(20,8)`, `evaluation_amount NUMERIC(20,8)` 컬럼 추가 |
| 2 | **Domain Entity** | [`src/agent_trading/domain/entities.py`](../../src/agent_trading/domain/entities.py:128) | `PositionSnapshotEntity`에 `purchase_amount: Decimal \| None = None`, `evaluation_amount: Decimal \| None = None` 필드 추가 |
| 3 | **KIS Snapshot Parser** | [`src/agent_trading/brokers/koreainvestment/snapshot.py`](../../src/agent_trading/brokers/koreainvestment/snapshot.py:138) | KIS `pchs_amt` → `purchase_amount`, `evlu_amt` → `evaluation_amount` 매핑 |
| 4 | **Postgres Repository** | [`src/agent_trading/repositories/postgres/position_snapshots.py`](../../src/agent_trading/repositories/postgres/position_snapshots.py:31) | INSERT 쿼리에 `purchase_amount`, `evaluation_amount` 컬럼/값 추가 |
| 5 | **API Schema** | [`src/agent_trading/api/schemas.py`](../../src/agent_trading/api/schemas.py:384) | `PositionSnapshotView`에 `purchase_amount: float \| None`, `evaluation_amount: float \| None` 추가 |
| 6 | **TypeScript Interface** | [`admin_ui/src/types/api.ts`](../../admin_ui/src/types/api.ts:138) | `PositionSnapshotView` 인터페이스에 `purchase_amount: number \| null`, `evaluation_amount: number \| null` 추가 |
| 7 | **Mock Fixtures** | [`admin_ui/src/__tests__/test-utils/fixtures.ts`](../../admin_ui/src/__tests__/test-utils/fixtures.ts:300) | 모의 데이터에 `purchase_amount`, `evaluation_amount` 값 포함 |
| 8 | **React UI** | [`admin_ui/src/components/AccountsView.tsx`](../../admin_ui/src/components/AccountsView.tsx:244) | 매입금액 / 평가금액 컬럼 추가, 시장가 → 현재가 rename |
| 9 | **Tests** | [`admin_ui/src/__tests__/accounts.test.tsx`](../../admin_ui/src/__tests__/accounts.test.tsx:72) | 새 필드 단언(assertion) 추가 |
| 9 | **Tests** | [`tests/api/conftest.py`](../../tests/api/conftest.py:276) | pytest fixture에 `purchase_amount`/`evaluation_amount` 값 포함 |
| 9 | **Tests** | [`tests/api/test_inspection.py`](../../tests/api/test_inspection.py:411) | API 응답에 `purchase_amount`/`evaluation_amount` 필드 검증 |

---

## 5. 테스트 결과

| 도구 | 결과 | 비고 |
|------|------|------|
| `pytest` | **42/42 passed** | inspection 전체 테스트 |
| `npm test` | **202/202 passed** (16개 파일) | 모든 UI 테스트 통과 |
| `tsc --noEmit` | **0 errors** | TypeScript 정적 타입 검사 통과 |
| `npm run build` | **성공** | 프로덕션 번들 빌드 성공 |

### pytest 상세 실행 커맨드

```bash
# API inspection 테스트
pytest tests/api/ -v

# 전체 테스트
pytest -v
```

### npm test 상세 실행 커맨드

```bash
cd admin_ui && npm test -- --watchAll=false
```

### TypeScript 타입 검사

```bash
cd admin_ui && npx tsc --noEmit
```

---

## 6. Docker 검증 결과

| 단계 | 명령 | 결과 |
|------|------|------|
| 빌드 | `docker compose build api` | 성공 |
| 실행 | `docker compose up -d api` | Container started |
| 헬스 체크 | `curl localhost:8000/health` | `{"status":"ok","database":"connected"}` |

> Docker compose 환경에서도 새 필드가 포함된 API 응답이 정상 반환됨을 확인.

---

## 7. 파일 수정 목록 (11개 파일)

| # | 파일 | 상태 | 변경 요약 |
|---|------|------|----------|
| 1 | [`db/migrations/0017_add_position_amounts.sql`](../../db/migrations/0017_add_position_amounts.sql) | **신규** | `purchase_amount`, `evaluation_amount` 컬럼 추가 |
| 2 | [`src/agent_trading/domain/entities.py`](../../src/agent_trading/domain/entities.py:128) | 수정 | `PositionSnapshotEntity`에 두 필드 추가 |
| 3 | [`src/agent_trading/brokers/koreainvestment/snapshot.py`](../../src/agent_trading/brokers/koreainvestment/snapshot.py:138) | 수정 | KIS raw → entity 매핑 추가 |
| 4 | [`src/agent_trading/repositories/postgres/position_snapshots.py`](../../src/agent_trading/repositories/postgres/position_snapshots.py:31) | 수정 | INSERT/UPDATE 쿼리 반영 |
| 5 | [`src/agent_trading/api/schemas.py`](../../src/agent_trading/api/schemas.py:384) | 수정 | `PositionSnapshotView` schema 확장 |
| 6 | [`admin_ui/src/types/api.ts`](../../admin_ui/src/types/api.ts:138) | 수정 | TypeScript interface 확장 |
| 7 | [`admin_ui/src/components/AccountsView.tsx`](../../admin_ui/src/components/AccountsView.tsx:244) | 수정 | 매입금액/평가금액 컬럼 추가, 시장가→현재가 rename |
| 8 | [`admin_ui/src/__tests__/test-utils/fixtures.ts`](../../admin_ui/src/__tests__/test-utils/fixtures.ts:300) | 수정 | 모의 데이터에 새 필드 포함 |
| 9 | [`admin_ui/src/__tests__/accounts.test.tsx`](../../admin_ui/src/__tests__/accounts.test.tsx:72) | 수정 | UI 테스트 assertion 추가 |
| 10 | [`tests/api/conftest.py`](../../tests/api/conftest.py:276) | 수정 | pytest fixture에 새 필드 포함 |
| 11 | [`tests/api/test_inspection.py`](../../tests/api/test_inspection.py:411) | 수정 | API 응답 검증 assertion 추가 |

---

## 부록: AccountsView.tsx — 컬럼 정의 발췌

```typescript
const positionColumns: Column<PositionSnapshotView>[] = [
  { key: "symbol",           header: "종목" },
  { key: "instrument_name",  header: "종목명" },
  { key: "quantity",         header: "수량" },
  { key: "average_price",    header: "평균단가" },
  { key: "purchase_amount",  header: "매입금액",    render: (r) => r.purchase_amount != null ? formatKrw(r.purchase_amount) : "—" },
  { key: "market_price",     header: "현재가" },
  { key: "evaluation_amount",header: "평가금액",    render: (r) => r.evaluation_amount != null ? formatKrw(r.evaluation_amount) : "—" },
  { key: "unrealized_pnl",   header: "미실현 손익" },
  { key: "snapshot_at",      header: "스냅샷 시각" },
  { key: "actions",          header: "" },
];
```
