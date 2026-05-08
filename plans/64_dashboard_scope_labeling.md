# Dashboard metric 의미 명확화 — 대표 계좌 기준 레이블링

## 변경 사항

### 1. [`Dashboard.tsx`](admin_ui/src/components/Dashboard.tsx) — MetricCard subtitle 변경

**Active Locks** 카드:
```
변경 전: subtitle={activeLocksCount > 0 ? "Requires attention" : "No active locks"}
변경 후: subtitle={repAccountName || "No account selected"}
```

**Incomplete Recon** 카드:
```
변경 전: subtitle={incompleteReconCount > 0 ? "Needs review" : "All reconciled"}
변경 후: subtitle={repAccountName || "No account selected"}
```

### 2. [`Dashboard.tsx`](admin_ui/src/components/Dashboard.tsx) — Active Locks section helper text

섹션 제목 아래에 대표 계좌 기준임을 표시하는 작은 텍스트 추가:
```
<p className="text-xs text-[#94a3b8]">
  Representative account: {repAccountName}
</p>
```

### 3. 새 변수 `repAccountName`

derived metrics 영역에 추가:
```typescript
const repAccountName = accounts[0]?.account_alias ?? accounts[0]?.account_masked ?? "";
```

### 4. [`dashboard.test.tsx`](admin_ui/src/__tests__/dashboard.test.tsx)

- `mockAccounts[0].account_alias` ("Paper Account 1") 텍스트가 나타나는지 확인
- 기존 테스트는 `getByText("Paper Account 1")`를 이미 account 테이블에서 검증 중 → 추가 검증 불필요
- 단, subtitle 변경으로 인한 회귀 없음 확인

## 시각적 예시

```
┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
│ 🛒 Recent Orders    │  │ 🔒 Active Locks     │  │ 🔄 Incomplete Recon │
│ 2                   │  │ 1                   │  │ 1                   │
│ Total orders in sys │  │ Paper Account 1     │  │ Paper Account 1     │ ← 명확화
└─────────────────────┘  └─────────────────────┘  └─────────────────────┘

Active Locks ──────── [View all locks]
Representative account: Paper Account 1   ← 명확화
┌─────────────────────────────────────────────┐
│ Lock Key          │ Type │ Symbol │ ...     │
│ manual-review-... │ ...  │ ...    │         │
└─────────────────────────────────────────────┘
```

## 작업 파일

| 파일 | 변경 | 설명 |
|---|---|---|
| [`Dashboard.tsx`](admin_ui/src/components/Dashboard.tsx) | 수정 | `repAccountName` 변수 추가, Active Locks/Incomplete Recon card subtitle 변경, section helper text 추가 |
| [`dashboard.test.tsx`](admin_ui/src/__tests__/dashboard.test.tsx) | 변경 없음 | 기존 검증으로 충분 |

## 검증

1. `npx vitest run` — 76/76 통과
2. `npm run build` — tsc + vite build 성공
