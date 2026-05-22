# 작업 보고서: 의사결정 페이지 로딩 UX 개선 + AgentRunsView 오늘 변경분 원복

**작업일:** 2026-05-22  
**관련 요청:** User Request — 두 가지 병렬 작업

---

## 목차

1. [개요](#1-개요)
2. [작업 1: 의사결정 페이지 체감 로딩 UX 개선](#2-작업-1-의사결정-페이지-체감-로딩-ux-개선)
3. [작업 2: AgentRunsView 오늘 변경분 원복](#3-작업-2-agentrunsview-오늘-변경분-원복)
4. [테스트 결과](#4-테스트-결과)
5. [파일별 변경 요약](#5-파일별-변경-요약)
6. [참고사항](#6-참고사항)

---

## 1. 개요

### 1.1 작업 목적

| 항목 | 설명 |
|------|------|
| **작업 1** | 의사결정(`DecisionsView`) 페이지의 전체 화면 spinner(`if (loading) return <LoadingSpinner />`)를 제거하고, inline/skeleton 로딩으로 대체하여 체감 로딩 UX 개선 |
| **작업 2** | `AgentRunsView` 페이지의 오늘 추가된 구조화된 출력 확장형 뷰(`StructuredOutputCell`, `StructuredValue`, `StructuredKeyValueRow`, Raw JSON debug view, EI fallback 등)를 전부 원복 |

### 1.2 작업 범위

| 구분 | 해당 파일 | 작업 내용 |
|------|-----------|-----------|
| UX 개선 | [`DecisionsView.tsx`](admin_ui/src/components/DecisionsView.tsx) | 전체 화면 spinner 제거, `DataTable`에 `isLoading` prop 전달 |
| UX 개선 | [`DataTable.tsx`](admin_ui/src/components/common/DataTable.tsx) | 로딩 상태에서 기존 데이터 유지, thin loading indicator 추가 |
| 원복 | [`AgentRunsTable.tsx`](admin_ui/src/components/AgentRunsTable.tsx) | `StructuredOutputCell`/`StructuredValue`/`StructuredKeyValueRow` 제거, "구조화된 출력" 컬럼 제거 |
| 원복 | [`AgentRunDetailPanel.tsx`](admin_ui/src/components/AgentRunDetailPanel.tsx) | Raw JSON debug view, EI fallback, reason_codes, copy 버튼 제거 |
| 원복 | [`admin-theme.css`](admin_ui/src/styles/admin-theme.css) | `.structured-output-*` CSS 클래스 19개 제거 (섹션 39) |
| 원복 | [`agentRuns.test.tsx`](admin_ui/src/__tests__/agentRuns.test.tsx) | 구조화된 출력 확장형 뷰 테스트 5개 제거 |
| 원복 | [`fixtures.ts`](admin_ui/src/__tests__/test-utils/fixtures.ts) | `mockEiAgentRunNoSummary` export 제거 |
| 테스트 보정 | [`decisions.test.tsx`](admin_ui/src/__tests__/decisions.test.tsx) | DataTable 로딩 UX 변경으로 인한 `getByText` → `findByText` 변경 (10개소) |

---

## 2. 작업 1: 의사결정 페이지 체감 로딩 UX 개선

### 2.1 문제 상황

기존 [`DecisionsView.tsx`](admin_ui/src/components/DecisionsView.tsx:229)는 다음과 같은 패턴을 사용:

```typescript
if (loading) return <LoadingSpinner />;
```

이로 인해:
- 페이지 전환 시 **전체 화면이 빈 흰색 + spinner**로 대체되어 깜빡임 발생
- API 응답이 빠르더라도(수백 ms) 무조건 전체 화면 리렌더링
- 헤더, 필터, 테이블 구조가 모두 사라져 UX 저하

### 2.2 해결 방법

#### 2.2.1 DecisionsView.tsx — 전체 화면 spinner 제거

[`DecisionsView.tsx`](admin_ui/src/components/DecisionsView.tsx)에서 `if (loading) return <LoadingSpinner />;` 라인을 제거하고, 항상 레이아웃을 렌더링하도록 변경:

```typescript
// 제거됨:
// if (loading) return <LoadingSpinner />;

// DataTable에 isLoading prop 전달:
<DataTable
  columns={decisionColumns}
  data={filteredDecisions}
  idKey="trade_decision_id"
  isLoading={loading}  // ← 추가
  // ...
/>
```

#### 2.2.2 DataTable.tsx — 로딩 상태에서 기존 데이터 유지

[`DataTable.tsx`](admin_ui/src/components/common/DataTable.tsx)의 로딩 로직을 세 가지 상태로 분기:

| 조건 | 동작 |
|------|------|
| `isLoading && data.length === 0` | 중앙 정렬 spinner + "로딩 중..." (초기 로딩) |
| `!isLoading && data.length === 0` | 빈 메시지 표시 |
| `isLoading && data.length > 0` | 기존 데이터 유지 + 상단 thin loading indicator bar |

```typescript
// 초기 로딩 (데이터 없음)
if (isLoading && data.length === 0) {
  return <div className="flex flex-col items-center justify-center p-8 gap-3">
    <div className="h-6 w-6 animate-spin ..." />
    <p className="text-sm text-[#64748b]">로딩 중...</p>
  </div>;
}

// 빈 상태 (로딩 아님)
if (!isLoading && data.length === 0) {
  return <div className="bg-white rounded-xl ...">{emptyMessage}</div>;
}

// 데이터 있음 + 로딩 중 → thin indicator
return (
  <div className="bg-white rounded-xl border ...">
    {isLoading && data.length > 0 && (
      <div className="flex items-center justify-center gap-2 py-2 bg-[#f8fafc] border-b border-[#e2e8f0]">
        <div className="h-3 w-3 animate-spin ..." />
        <span className="text-xs text-[#64748b]">로딩 중...</span>
      </div>
    )}
    <div className="overflow-x-auto">
      <table>...</table>
    </div>
  </div>
);
```

### 2.3 UX 개선 효과

| 항목 | 개선 전 | 개선 후 |
|------|---------|---------|
| 페이지 전환 | 전체 화면 깜빡임 + spinner | 헤더/필터/테이블 구조 유지 |
| 데이터 갱신 | 전체 화면 리렌더링 | 기존 데이터 유지 + thin indicator |
| 초기 로딩 | 전체 화면 spinner | DataTable 영역만 spinner |
| 체감 속도 | 느리게 느껴짐 | 즉시 반응하는 느낌 |

---

## 3. 작업 2: AgentRunsView 오늘 변경분 원복

### 3.1 원복 대상

오늘 추가된 구조화된 출력 확장형 뷰 관련 모든 변경사항을 원복:

| 컴포넌트 | 추가된 기능 | 원복 내용 |
|----------|------------|-----------|
| `AgentRunsTable.tsx` | `StructuredOutputCell`, `StructuredValue`, `StructuredKeyValueRow` | 함수 및 "구조화된 출력" 컬럼 제거 |
| `AgentRunDetailPanel.tsx` | Raw JSON `<details>` debug view, EI fallback(`formatEiOutput`), reason_codes chips, copy-to-clipboard | 모두 제거, 기본 summary/decision_type/risk_opinion만 유지 |
| `admin-theme.css` | 19개 `.structured-output-*` CSS 클래스 (섹션 39) | 전체 제거 |
| `agentRuns.test.tsx` | 구조화된 출력 확장형 뷰 테스트 5개 | 전체 제거 |
| `fixtures.ts` | `mockEiAgentRunNoSummary` | export 제거 |

### 3.2 보존된 기능

- AgentRunsTable: 기본 5개 컬럼 (agent type, status, context link, start time, summary) 유지
- AgentRunDetailPanel: 기본 메타데이터 + structured_output_json의 summary/decision_type/risk_opinion 표시 유지
- AgentRunsView: 검색/필터/상태 표시 기능 모두 유지

### 3.3 TypeScript 타입 안전성

[`AgentRunDetailPanel.tsx`](admin_ui/src/components/AgentRunDetailPanel.tsx)에서 `structured_output_json`은 `unknown` 타입이므로, 속성 접근 시 `as Record<string, unknown>` 캐스팅 사용:

```typescript
{!!(run.structured_output_json as Record<string, unknown>)["summary"] && (
  <div>
    <p className="text-[#64748b] font-medium mb-1">요약</p>
    <p className="text-[#0f172a]">
      {String((run.structured_output_json as Record<string, unknown>)["summary"])}
    </p>
  </div>
)}
```

---

## 4. 테스트 결과

### 4.1 최종 테스트 결과

```
Test Files  16 passed (16)
Tests       259 passed (259)
```

모든 테스트 통과. 실패/경고 없음.

### 4.2 테스트 보정 내역

DataTable 로딩 UX 변경으로 인해 [`decisions.test.tsx`](admin_ui/src/__tests__/decisions.test.tsx)에서 10개 테스트의 `screen.getByText("AAPL")`를 `await screen.findByText("AAPL")`로 변경:

| 라인 | 테스트 | 변경 내용 |
|------|--------|-----------|
| 76 | renders trade decisions | `getByText` → `findByText` (AAPL) |
| 109 | confidence color | `getByText` → `findByText` (85%) |
| 168 | detail panel | `getByText` → `findByText` (AAPL) |
| 225 | context API error | `getByText` → `findByText` (AAPL) |
| 265 | side filter | `getByText` → `findByText` (AAPL) |
| 296 | symbol search | `getByText` → `findByText` (AAPL) |
| 325 | agent runs panel | `getByText` → `findByText` (AAPL) |
| 361 | empty agent runs | `getByText` → `findByText` (AAPL) |
| 427 | agent runs error | `getByText` → `findByText` (AAPL) |
| 459 | structured output toggle | `getByText` → `findByText` (AAPL) |
| 533 | EI aggregate_view | `getByText` → `findByText` (AAPL) |
| 595 | FDC/AR regression | `getByText` → `findByText` (AAPL) |
| 1018 | Recent Events | `getByText` → `findByText` (Samsung Electronics) |

변경 이유: DataTable이 로딩 상태일 때 `isLoading && data.length === 0` 조건에서 spinner를 표시하므로, API 응답이 도착할 때까지 `findByText`로 대기해야 함.

---

## 5. 파일별 변경 요약

### 5.1 수정된 파일

| 파일 | 상태 | 변경 라인 수 |
|------|------|-------------|
| [`DecisionsView.tsx`](admin_ui/src/components/DecisionsView.tsx) | 수정 | 2 (spinner 제거, isLoading 추가) |
| [`DataTable.tsx`](admin_ui/src/components/common/DataTable.tsx) | 수정 | ~15 (로딩 로직 변경) |
| [`AgentRunsTable.tsx`](admin_ui/src/components/AgentRunsTable.tsx) | 수정 | ~260 → ~105 (대규모 축소) |
| [`AgentRunDetailPanel.tsx`](admin_ui/src/components/AgentRunDetailPanel.tsx) | 수정 | ~197 → ~107 (대규모 축소) |
| [`admin-theme.css`](admin_ui/src/styles/admin-theme.css) | 수정 | ~185 (CSS 클래스 제거) |
| [`agentRuns.test.tsx`](admin_ui/src/__tests__/agentRuns.test.tsx) | 수정 | ~120 (테스트 제거) |
| [`fixtures.ts`](admin_ui/src/__tests__/test-utils/fixtures.ts) | 수정 | ~30 (export 제거) |
| [`decisions.test.tsx`](admin_ui/src/__tests__/decisions.test.tsx) | 수정 | ~13 (getByText → findByText) |

### 5.2 변경되지 않은 파일

| 파일 | 이유 |
|------|------|
| [`AgentRunsView.tsx`](admin_ui/src/components/AgentRunsView.tsx) | 변경 불필요 (필터/검색 로직 유지) |
| [`AgentRunsPanel.tsx`](admin_ui/src/components/AgentRunsPanel.tsx) | 변경 불필요 |
| [`AgentTypeBadge.tsx`](admin_ui/src/components/AgentTypeBadge.tsx) | 변경 불필요 |
| [`api.ts`](admin_ui/src/types/api.ts) | 변경 불필요 (타입 정의 유지) |
| [`client.ts`](admin_ui/src/api/client.ts) | 변경 불필요 |

---

## 6. 참고사항

### 6.1 알려진 이슈

- **없음.** 모든 테스트 통과, 기존 기능 정상 동작 확인.

### 6.2 추후 고려사항

1. **AgentRunsView 재설계**: 사용자 코멘트대로, AgentRunsView는 추후 완전히 재설계될 예정. 현재는 기본 테이블 + detail panel만 유지.
2. **Skeleton loading 도입**: 현재는 thin loading indicator bar를 사용하지만, 추후 skeleton loading 컴포넌트로 대체 가능.
3. **페이지네이션 UX**: DecisionsView의 페이지 전환 시에도 현재 데이터 유지 + loading indicator가 표시되므로, 페이지 전환 UX도 개선됨.

### 6.3 롤백 가이드

만약 AgentRunsView의 구조화된 출력 확장형 뷰를 다시 도입해야 한다면:

1. `AgentRunsTable.tsx`: `StructuredOutputCell`, `StructuredValue`, `StructuredKeyValueRow` 함수 재추가
2. `AgentRunDetailPanel.tsx`: Raw JSON debug view, EI fallback, copy 버튼 재추가
3. `admin-theme.css`: 섹션 39 (`.structured-output-*`) CSS 클래스 재추가
4. `agentRuns.test.tsx`: 구조화된 출력 테스트 재추가
5. `fixtures.ts`: `mockEiAgentRunNoSummary` 재추가

---

*보고서 작성일: 2026-05-22*
