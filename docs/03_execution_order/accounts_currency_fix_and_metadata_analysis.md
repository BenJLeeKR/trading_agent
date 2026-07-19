# Accounts 화면 통화 표시 수정 + KIS 계좌 메타데이터 sync 범위 분석

## 1. 현재 상태

### 문제점
[`admin_ui/src/components/AccountsView.tsx`](admin_ui/src/components/AccountsView.tsx:23)의 `formatCurrency()`가 `currency: "USD"`로 하드코딩되어 있어 모든 금액이 `$30,000,000`처럼 표시됨. 실제 데이터는 모두 KRW 기준.

### 데이터 흐름
```
KIS Paper API (inquire-balance)
  → CashBalance: dnca_tot_amt (예수금총액) = 30,000,000 KRW
  → kis_snapshot_sync.py: currency="KRW" 하드코딩 저장
  → CashBalanceSnapshotEntity.currency = "KRW"
  → GET /cash-balances → CashBalanceSnapshotView.currency = "KRW"
  → AccountsView: cashBalance.currency 사용 가능

ClientEntity.base_currency = "KRW" (기본값)
```

### 통화 결정 트리 (현재와 개선)

| 위치 | 현재 | 개선 |
|------|------|------|
| Summary Cards (Total Value, Cash Balance, P&L) | `USD` 하드코딩 | `cashBalance.currency` (있으면) or `"KRW"` |
| Cash Balance Detail | `USD` 하드코딩 | `cashBalance.currency` |
| Positions Table (Avg Cost, Market Price, P&L) | `USD` 하드코딩 | `"KRW"` (기본값, 차후 KIS 해외주식 대비) |
| Client header | N/A | `selectedClient.base_currency` 활용 가능 |

## 2. Step 1: 통화 표시 버그 수정

### 변경: [`formatCurrency()`](admin_ui/src/components/AccountsView.tsx:20)

```typescript
// BEFORE
function formatCurrency(val: number | null | undefined): string {
  if (val == null) return "—";
  if (Number.isNaN(val)) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(val);
}

// AFTER
function formatCurrency(val: number | null | undefined, currency: string = "KRW"): string {
  if (val == null) return "—";
  if (Number.isNaN(val)) return "—";
  return new Intl.NumberFormat("ko-KR", { style: "currency", currency }).format(val);
}
```

`ko-KR` locale + `currency` 파라미터로 data-driven하게 변경.

### 변경: 호출부 — Summary Cards

```typescript
// Total Value card (line 380)
formatCurrency(totalValue)   →   formatCurrency(totalValue, cashBalance?.currency)

// Cash Balance card (line 392)
formatCurrency(cashBalance.settled_cash)   →   formatCurrency(cashBalance.settled_cash, cashBalance.currency)

// P&L card (line 419)
formatCurrency(totalPnl)   →   formatCurrency(totalPnl, cashBalance?.currency)
```

### 변경: 호출부 — Cash Balance Detail

```typescript
// Available (line 435), Settled (line 441), Unsettled (line 447)
formatCurrency(cashBalance.available_cash)   →   formatCurrency(cashBalance.available_cash, cashBalance.currency)
formatCurrency(cashBalance.settled_cash)     →   formatCurrency(cashBalance.settled_cash, cashBalance.currency)
formatCurrency(cashBalance.unsettled_cash)   →   formatCurrency(cashBalance.unsettled_cash, cashBalance.currency)
```

### 변경: 호출부 — Positions Table

```typescript
// Avg Cost (line 191), Market Price (line 196), P&L (line 208)
formatCurrency(r.average_price)    →   formatCurrency(r.average_price)
formatCurrency(r.market_price)     →   formatCurrency(r.market_price)
formatCurrency(pnl)                →   formatCurrency(pnl)
// Positions은 항상 "KRW" default 사용 (KIS 국내주식)
```

### Intl.NumberFormat 변경: `en-US` → `ko-KR`

| 항목 | en-US | ko-KR |
|------|-------|-------|
| `$30,000,000.00` | O | — |
| `₩30,000,000` | — | O |

`ko-KR` locale은 통화 기호를 **앞**에 표시 (`₩30,000,000`)하며, 천단위 콤마를 사용하고 소수점이 없는 정수 표기에 적합합니다.

## 3. Step 2: Account metadata sync 범위 분석

### AccountEntity 필드별 동기화 가능 여부

| 필드 | 현재 출처 | KIS에서 가능? | 판정 | 근거 |
|------|----------|--------------|------|------|
| `account_id` | 내부 UUID | ❌ | **내부 유지** | 내부 식별자 |
| `client_id` | 내부 UUID | ❌ | **내부 유지** | 내부 관계 |
| `broker_account_id` | BrokerAccountEntity FK | ❌ | **내부 유지** | 내부 관계 |
| `environment` | 수동 설정 (`paper`/`live`) | ❌ | **내부 유지** | KIS API 응답에 env 정보 없음 |
| `account_alias` | 수동 설정 | ❌ | **내부 유지** | KIS API에 alias 개념 없음 |
| `account_masked` | 수동 설정 (마스킹된 계좌번호) | ✅ 부분 가능 | **추가 검토 필요** | `inquire-balance` 응답에 CANO(계좌번호)는 있으나 마스킹은 아님 |
| `status` | 수동 설정 | ❌ | **내부 유지** | KIS API에 계좌 상태 조회 엔드포인트 없음 |
| `risk_profile` | 내부 설정 | ❌ | **내부 유지** | 순수 내부 메타데이터 |

### KIS API가 제공하는 계좌 관련 정보

현재 구현된 KIS API 중 계좌 메타데이터를 제공하는 것은 **없음**:

| API | 제공 정보 | 계좌 메타데이터? |
|-----|----------|----------------|
| `inquire-balance` (`get_positions`, `get_cash_balance`) | positions + cash summary | ❌ 없음 |
| `inquire-daily-ccld` (`get_fills`, `get_order_status`) | 체결/주문 내역 | ❌ 없음 |
| `oauth2/tokenP` | access token | ❌ 없음 |

KIS OpenAPI 문서상 `계좌정보조회` (CANO로 계좌번호 확인) 엔드포인트는 존재하지만, 현재 구현되지 않았고 모의투자에서 지원 여부도 불확실.

### 결론: Account Metadata Sync는 현재 KIS API만으로는 불가능

KIS API로는 `account_masked`(계좌번호 마스킹)조차 직접 가져올 수 없습니다. `inquire-balance` 응답에 CANO(계좌번호) 원본이 포함되나:
- CANO는 8자리 계좌번호 앞자리 (`12345678`)
- 마스킹 처리(`***1234`)는 프론트/백엔드에서 직접 해야 함
- 모의투자 계좌번호는 실제와 다를 수 있음

## 4. 후속 작업 메모

### KIS Account Metadata Sync — 실제 가능한 범위

별도 후속 작업으로 검토할 사항:

1. **`account_masked` 동기화**: `inquire-balance` 응답의 `CANO`(계좌번호) 필드를 활용
   - API 응답에서 CANO 추출 → `AccountEntity.account_masked` 업데이트
   - 단, 마스킹 규칙은 내부에서 정의
   - 모의투자(`paper`) CANO와 실전(`live`) CANO가 다름 → env별 분리 저장

2. **`BrokerAccountEntity.account_ref` 동기화**: KIS 계좌번호(CANO)로 `account_ref` 갱신
   - 현재 `account_ref`가 무엇으로 설정되어 있는지 확인 필요
   - KIS 계좌별 설정과 불일치 시 정정

3. **변경 금지 확인**:
   - ❌ `account_alias` — KIS에 alias 개념 없음
   - ❌ `environment` — 수동 설정 유지
   - ❌ `status` — KIS API에 계좌 상태 없음
   - ❌ `risk_profile` — 순수 내부 메타데이터
   - ❌ `broker_account_id` — 내부 FK

### 요약: 후속 1개 작업만 의미 있음

> **"계좌번호(CANO)를 KIS inquire-balance 응답에서 추출하여 AccountEntity.account_masked에 반영"**

이 작업의 난이도는 낮으나, snapshot sync 로직에 `AccountEntity` 업데이트를 추가해야 하므로 schema 변경(frozen dataclass 해제 or snapshot sync 전용 update 메서드)이 필요할 수 있음.

## 5. 파일 변경 목록

| 파일 | 변경 | 설명 |
|------|------|------|
| [`admin_ui/src/components/AccountsView.tsx`](admin_ui/src/components/AccountsView.tsx) | 수정 | `formatCurrency()` 시그니처 변경 + 호출부 currency 전달 (`cashBalance.currency` 기반) |

## 6. 변경 금지 확인

- ❌ Backend API schema 변경
- ❌ Admin UI write 기능 추가
- ❌ Broker submit semantics 변경
- ❌ Snapshot sync 로직 변경
- ❌ Entities/enums 변경
- ❌ 통화 locale을 `selectedClient.base_currency`까지 연동 (범위 축소)
