# Admin UI Enum Label 적용 — 설계 및 구현 계획

> **목표**: 이미 구현된 `/metadata/enums` API를 Admin UI가 실제로 소비하여 `order_type`의 raw canonical 값(`limit`) 대신 한국어 label(`지정가`)을 표시한다.

---

## 1. 설계 결정

### 1-A. Metadata fetch 전략: **B안 — shared hook + module-level cache**

| 항목 | A안: OrderDetail 내부 직접 fetch | **B안: shared hook + module cache** |
|------|-------------------------------|-----------------------------------|
| 중복 fetch 방지 | ❌ 각 컴포넌트가 개별 호출 | ✅ 앱 전체에서 1회만 fetch |
| 확장성 | ❌ P1 필드 추가 시 재작업 | ✅ 모든 enum field에 동일 패턴 적용 |
| 복잡도 | ✅ 낮음 (OrderDetail만 수정) | ⚠️ 중간 (hook 파일 1개 생성) |
| fallback 안정성 | ⚠️ 비동기 상태별 처리 필요 | ✅ hook에서 loading/error 통합 관리 |

**선택 근거**: `side`, `status`, `decision_type` 등 P1 확장 시 hook 재사용 가능. module-level cache로 앱 전체에서 1회 fetch.

### 1-B. Cache + pendingPromise 처리 (보정 #1)

```typescript
let _cachedData: Record<string, EnumFieldMetadataSchema> | null = null;
let _pendingPromise: Promise<void> | null = null;
```

- `_cachedData`만 두지 않고 `_pendingPromise`도 함께 관리
- 컴포넌트가 여러 번 mount되어도 중복 fetch 방지
- `_pendingPromise`가 존재하면 기존 promise를 await

### 1-C. `getEnumLabel()` nullish/fallback 정책 (보정 #2)

```typescript
export function getEnumLabel(
  fieldMap: Record<string, EnumFieldMetadataSchema>,
  field: string,
  value: string | null | undefined,
): string {
  if (!value) return "-"; // null/undefined/"" → "-"
  return fieldMap[field]?.values.find((v) => v.value === value)?.label ?? value;
}
```

- `null` / `undefined` / 빈 문자열 → `"-"` (일관된 빈 값 표시)
- metadata lookup 실패 → raw `value` 유지
- 정상 lookup → label 반환

### 1-D. 렌더링 정책 (보정 #3)

| 위치 | 표시 | raw value |
|------|------|-----------|
| subtitle (line 87) | `{symbol} · {side} · {label}` | `<span title>` tooltip으로만 |
| 주문 유형 상세 (line 113) | `{label}` | `({raw})` 회색 작은 글씨 보조 표시 |

**원칙**: 동일 값을 반복 노출하지 않음. subtitle은 깔끔하게 label 위주. 상세 필드에서만 raw value 보조 표시.

### 1-E. P1 확장 대상 TODO (보정 #4)

```typescript
// TODO(P1): Extend enum label lookup to other fields:
//   - side:    "buy" → "매수", "sell" → "매도"
//   - status:  "filled" → "체결", "pending" → "대기", "rejected" → "거부", etc.
//   - decision_type: "approve" → "승인", "reject" → "거절", "hold" → "보류", etc.
//   - entry_style: "limit" → "지정가", "market" → "시장가", etc.
//   These require P1 registration in the backend ENUM_METADATA registry first.
```

### 1-F. 적용 범위

| 파일 | 변경 | 비고 |
|------|------|------|
| [`admin_ui/src/hooks/useEnumMetadata.ts`](admin_ui/src/hooks/useEnumMetadata.ts) | **신규 생성** | shared hook + `getEnumLabel` 유틸 |
| [`admin_ui/src/components/OrderDetail.tsx`](admin_ui/src/components/OrderDetail.tsx) | **수정** | `order_type` raw value → label로 교체 |
| [`admin_ui/src/__tests__/hooks/useEnumMetadata.test.ts`](admin_ui/src/__tests__/hooks/useEnumMetadata.test.ts) | **신규 생성** | `getEnumLabel` unit test + fallback 검증 |

**변경 제외**:
- [`admin_ui/src/components/OrdersView.tsx`](admin_ui/src/components/OrdersView.tsx) — `order_type` 미표시, 변경 불필요
- 백엔드 API — shape 변경 금지
- `getEnumFieldMetadata("order_type")` 개별 호출 — shared cache로 대체

---

## 2. 변경 상세

### 2-1. `admin_ui/src/hooks/useEnumMetadata.ts` (신규)

```typescript
import { useState, useEffect } from "react";
import { getEnumMetadata } from "../api/client";
import type { EnumFieldMetadataSchema } from "../types/api";

// ── Module-level cache + pendingPromise ─────────────────────────────
let _cachedData: Record<string, EnumFieldMetadataSchema> | null = null;
let _pendingPromise: Promise<void> | null = null;

/**
 * React hook that loads enum metadata once and caches at module level.
 * ``_pendingPromise`` prevents duplicate fetches when multiple components
 * mount concurrently.
 */
export function useEnumMetadata() {
  const [fieldMap, setFieldMap] = useState<
    Record<string, EnumFieldMetadataSchema>
  >(_cachedData ?? {});
  const [loading, setLoading] = useState(_cachedData === null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (_cachedData) return; // already loaded

    if (!_pendingPromise) {
      _pendingPromise = getEnumMetadata()
        .then((data) => {
          const map: Record<string, EnumFieldMetadataSchema> = {};
          for (const f of data.fields) {
            map[f.field] = f;
          }
          _cachedData = map;
          setFieldMap(map);
        })
        .catch((err: unknown) => {
          const msg =
            err instanceof Error
              ? err.message
              : "Failed to load enum metadata";
          setError(msg);
        })
        .finally(() => {
          setLoading(false);
        });
    } else {
      // Already in-flight — wait for the same promise
      _pendingPromise.then(() => {
        if (_cachedData) setFieldMap(_cachedData);
        setLoading(false);
      });
    }
  }, []);

  return { fieldMap, loading, error };
}

/**
 * Resolve a canonical enum value to its display label.
 *
 * @param fieldMap - Field map from ``useEnumMetadata()``.
 * @param field    - Field name (e.g. ``"order_type"``).
 * @param value    - Canonical value (e.g. ``"limit"``), may be nullish.
 * @returns Display label, ``"-"`` for nullish input, or raw value as fallback.
 */
export function getEnumLabel(
  fieldMap: Record<string, EnumFieldMetadataSchema>,
  field: string,
  value: string | null | undefined,
): string {
  if (!value) return "-";
  return (
    fieldMap[field]?.values.find((v) => v.value === value)?.label ?? value
  );
}

// TODO(P1): Extend enum label lookup to other fields:
//   - side:    "buy" → "매수", "sell" → "매도"
//   - status:  "filled" → "체결", "pending" → "대기", etc.
//   - decision_type, entry_style
//   These require P1 registration in the backend ENUM_METADATA first.
```

### 2-2. `admin_ui/src/components/OrderDetail.tsx` (수정)

**변경 전 (line 3-4)**:
```typescript
import type { OrderDetail as OrderDetailType, OrderEvent, BrokerOrderView } from "../types/api";
import { getOrderDetail, getOrderEvents, getBrokerOrders } from "../api/client";
```

**변경 후**:
```typescript
import type { OrderDetail as OrderDetailType, OrderEvent, BrokerOrderView } from "../types/api";
import { getOrderDetail, getOrderEvents, getBrokerOrders } from "../api/client";
import { useEnumMetadata, getEnumLabel } from "../hooks/useEnumMetadata";
```

**변경 전 (line 13)**:
```typescript
export default function OrderDetail() {
```

**변경 후**:
```typescript
export default function OrderDetail() {
  const { fieldMap } = useEnumMetadata();
```

**subtitle (line 87)** — label만, raw value는 tooltip:
```tsx
// Before:
<p className="text-sm text-[#64748b]">{order.symbol} · {order.side} · {order.order_type}</p>

// After:
<p className="text-sm text-[#64748b]">
  {order.symbol} · {order.side} ·{" "}
  <span title={order.order_type ?? ""}>
    {getEnumLabel(fieldMap, "order_type", order.order_type)}
  </span>
</p>
```

**주문 유형 상세 (line 113)** — label + raw value 보조:
```tsx
// Before:
<dd className="text-sm font-medium text-[#0f172a] mt-0.5">{order.order_type}</dd>

// After:
<dd className="text-sm font-medium text-[#0f172a] mt-0.5">
  {getEnumLabel(fieldMap, "order_type", order.order_type)}
  <span className="ml-2 text-xs text-[#94a3b8] font-mono">
    ({order.order_type})
  </span>
</dd>
```

### 2-3. `admin_ui/src/__tests__/hooks/useEnumMetadata.test.ts` (신규)

```typescript
import { getEnumLabel } from "../../hooks/useEnumMetadata";
import type { EnumFieldMetadataSchema } from "../../types/api";

const mockFieldMap: Record<string, EnumFieldMetadataSchema> = {
  order_type: {
    field: "order_type",
    type: "enum",
    values: [
      { value: "limit", label: "지정가", description: null, broker_code: "00", supported: true },
      { value: "market", label: "시장가", description: null, broker_code: "01", supported: true },
      { value: "stop", label: "조건부지정가", description: "unsupported", broker_code: "02", supported: false },
      { value: "stop_limit", label: "조건부지정가", description: "unsupported", broker_code: "03", supported: false },
    ],
  },
};

describe("getEnumLabel", () => {
  it("returns label for known value", () => {
    expect(getEnumLabel(mockFieldMap, "order_type", "limit")).toBe("지정가");
    expect(getEnumLabel(mockFieldMap, "order_type", "market")).toBe("시장가");
  });

  it("returns raw value as fallback when field not found", () => {
    expect(getEnumLabel(mockFieldMap, "unknown_field", "some_value")).toBe("some_value");
  });

  it("returns raw value as fallback when value not found in field", () => {
    expect(getEnumLabel(mockFieldMap, "order_type", "unknown_value")).toBe("unknown_value");
  });

  it("returns '-' for null value", () => {
    expect(getEnumLabel(mockFieldMap, "order_type", null)).toBe("-");
  });

  it("returns '-' for undefined value", () => {
    expect(getEnumLabel(mockFieldMap, "order_type", undefined)).toBe("-");
  });

  it("returns '-' for empty string", () => {
    expect(getEnumLabel(mockFieldMap, "order_type", "")).toBe("-");
  });

  it("returns raw value when fieldMap is empty (fetch failure)", () => {
    expect(getEnumLabel({}, "order_type", "limit")).toBe("limit");
  });
});
```

---

## 3. 미적용 사항 (명시적)

| 항목 | 사유 |
|------|------|
| OrdersView.tsx 테이블에 `order_type` 컬럼 추가 | 요청 범위 초과 (이번 턴은 기존 위치의 raw→label 교체만) |
| `side` label 변환 (`buy`→`매수`) | P1, 이번 턴 제외 (TODO 주석으로만 기록) |
| `status` label 변환 | P1, 이번 턴 제외 |
| `decision_type` label 변환 | P1, 이번 턴 제외 |
| FilterBar 옵션 label 동기화 | 현재 하드코딩, P1 과제 |
| 백엔드 API 변경 | shape 변경 금지 |

---

## 4. 작업 제약 준수 확인

| 제약 | 상태 |
|------|------|
| broker submit semantics 변경 금지 | ✅ 해당 없음 |
| domain enum canonical 값 변경 금지 | ✅ `order.order_type` raw string 유지 |
| admin UI 대규모 개편 금지 | ✅ hook 1개 생성 + OrderDetail.tsx 최소 수정 |
| 과도한 abstraction 금지 | ✅ hook 단순, `getEnumLabel`은 순수 함수 |
| metadata fetch 실패 시 raw value fallback | ✅ `?? value` 처리 |
| `side`/`status`/`decision_type` 확장 가능 구조 | ✅ `useEnumMetadata` + `getEnumLabel`로 확장 가능, TODO 기록 |
| nullish 안전 처리 | ✅ `!value` → `"-"` |
| in-flight 중복 fetch 방지 | ✅ `_pendingPromise` 관리 |

---

## 5. Mermaid: cache + pendingPromise 흐름

```mermaid
flowchart TD
    Mount[Component mounts] --> CheckCache{_cachedData\n존재?}
    CheckCache -->|Yes| UseCache[fieldMap ← _cachedData\nloading=false]
    CheckCache -->|No| CheckPending{_pendingPromise\n존재?}

    CheckPending -->|No| Fetch[getEnumMetadata\n_pendingPromise 할당]
    CheckPending -->|Yes| Wait[기존 _pendingPromise await]

    Fetch --> Success[응답 → _cachedData 저장\nfieldMap 갱신]
    Fetch --> Fail[error 설정\nfieldMap=빈 객체]
    Success --> Done[loading=false]
    Fail --> Done
    Wait --> Done

    UseCache --> Render[렌더링]
    Done --> Render

    Render --> Label[getEnumLabel\nfieldMap[field]?.find\n?? value or '-']
```

---

## 6. 작업 순서

1. [`admin_ui/src/hooks/useEnumMetadata.ts`](admin_ui/src/hooks/useEnumMetadata.ts) 신규 생성
2. [`admin_ui/src/components/OrderDetail.tsx`](admin_ui/src/components/OrderDetail.tsx) 수정 — import + `useEnumMetadata` 호출 + 2곳 label 교체
3. [`admin_ui/src/__tests__/hooks/useEnumMetadata.test.ts`](admin_ui/src/__tests__/hooks/useEnumMetadata.test.ts) 신규 생성 — `getEnumLabel` unit test 7개
4. Admin UI 빌드/타입 체크 확인 (`npm run build` 또는 `tsc --noEmit`)
