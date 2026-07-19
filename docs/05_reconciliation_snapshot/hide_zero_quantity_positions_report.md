# 수량 0 포지션 숨기기 — 조사 및 구현 보고서

> **최종 업데이트:** 2026-05-21
> **상태:** ✅ 구현 완료

---

## 0. 최종 변경 사항 요약

| 항목 | 내용 |
|---|---|
| 수정 파일 | [`admin_ui/src/components/AccountsView.tsx`](admin_ui/src/components/AccountsView.tsx) |
| 테스트 파일 | [`admin_ui/src/__tests__/accounts.test.tsx`](admin_ui/src/__tests__/accounts.test.tsx) |
| 수정 방식 | `latestPositions` useMemo 내 `if (pos.quantity <= 0) continue;` 추가 |
| 영향 범위 | 계좌 화면 포지션 상세 테이블 (기본 뷰) |
| 이력 모드 | 스냅샷 이력 보기에서는 수량 0 포함 (디버깅 가능) |
| DB/API 변경 | 없음 |
| Docker 재빌드 | 불필요 (프론트엔드만 변경) |
| 테스트 결과 | 18개 전부 통과 (신규 4개 포함) |
| 운영 검증 | `/health` → `status: "ok"`, `database: "connected"` |

## 1. 현재 0 수량 종목은 어떤 API 응답을 통해 UI에 들어오는가?

**API 경로:** `GET /positions?account_id={uuid}`

**백엔드 처리 흐름:**
1. [`GET /positions`](src/agent_trading/api/routes/positions.py:18) → `repos.position_snapshots.list_latest_by_account(aid)` 호출
2. [`list_latest_by_account()`](src/agent_trading/repositories/postgres/position_snapshots.py:58) → `DISTINCT ON (instrument_id)` SQL로 각 종목별 최신 snapshot 1건 반환
   - SQL에 `quantity > 0` 조건 없음
   - 리포지토리 docstring에 *"호출자(consumer)가 필요시 `quantity > 0` 필터를 적용할 수 있다"* 명시
3. [`PositionSnapshotView`](src/agent_trading/api/schemas.py:370) 스키마로 변환되어 반환

**프론트엔드 처리 흐름:**
1. [`getPositions(accountId)`](admin_ui/src/api/client.ts:181) → `/positions?account_id=...` 호출
2. [`latestPositions`](admin_ui/src/components/AccountsView.tsx:103) useMemo에서 instrument_id별 dedup 수행
   - **`quantity > 0` 필터 없음**
3. 포지션 테이블에 `latestPositions` (기본값) 또는 `positions` (스냅샷 이력) 렌더링

**결론:** API가 quantity와 무관하게 모든 최신 snapshot을 반환하고, 프론트엔드에서도 필터 없이 그대로 렌더링하므로 0 수량 종목이 화면에 표시됨.

---

## 2. "포지션 상세"만 숨기면 되는가, 아니면 계좌 관련 다른 현재 포지션 뷰도 같이 맞춰야 하는가?

| 뷰 | 파일 | `getPositions` 사용 | 영향 |
|---|---|---|---|
| 계좌 화면 포지션 상세 | [`AccountsView.tsx`](admin_ui/src/components/AccountsView.tsx) | ✅ 기본 대상 | 수량 0 숨김 필요 |
| 운영 알림 | [`OperationsAlertsView.tsx`](admin_ui/src/components/OperationsAlertsView.tsx) | ✅ 사용 | 포지션 분석에 사용하나, quantity=0은 자연스럽게 무시됨 |
| 운영 대시보드 | [`OperationsDashboardView.tsx`](admin_ui/src/components/OperationsDashboardView.tsx) | ✅ 사용 | 이미 807번 줄에 `"quantity>0"` 주석 존재 |
| 메인 대시보드 | [`Dashboard.tsx`](admin_ui/src/components/Dashboard.tsx) | ✅ 사용 | 포지션 평가액 계산에 사용 (quantity=0 → 0 기여) |
| Reconciliation | [`ReconciliationView.tsx`](admin_ui/src/components/ReconciliationView.tsx) | ✅ 사용 | symbol 매칭 용도 |

**결론:** 계정 화면의 "포지션 상세"(position detail table)가 가장 직접적인 영향을 받는다. 다른 뷰들은 quantity=0 row가 있어도 무해하거나 이미 자연스럽게 처리된다. 따라서 **포지션 상세만 필터**해도 충분하다.

---

## 3. 가장 안전한 수정 위치는 어디인가? (프론트 렌더링 필터 / API 응답 필터 / 둘 다)

### 검토 옵션

| 옵션 | 장점 | 단점 |
|---|---|---|
| **A. 프론트 필터 (권장)** | • API 공유 문제 없음<br>• 이력/디버깅 모드 유지 가능<br>• 최소 변경<br>• 리포지토리 의도와 일치 | • API 자체는 여전히 0 수량 반환 |
| **B. API 응답 필터** | • 모든 클라이언트 일관 적용 | • 다른 뷰에 영향 가능<br>• 리포지토리 설계 의도와 상충<br>• 이력 조회 어려움 |
| **C. 둘 다** | • 이중 안전장치 | • 중복 작업<br>• 유연성低下 |

### 선택: **A. 프론트 필터 (권장)**

**이유:**
1. [`list_latest_by_account()`](src/agent_trading/repositories/postgres/position_snapshots.py:58) docstring에 이미 consumer-side 필터 명시
2. `GET /positions`는 공용 API로 여러 뷰에서 사용 → API 수정 시 회귀 위험
3. "스냅샷 이력 보기" 모드에서는 0 수량도 표시되어야 디버깅 가능 — 프론트 필터만이 이를 지원
4. 프론트 필터는 변경 범위가 [`AccountsView.tsx`](admin_ui/src/components/AccountsView.tsx) 한 파일로 제한됨

---

## 4. 이력/디버깅 화면은 그대로 유지해야 하는가?

**예, 유지해야 함.**

[`AccountsView.tsx`](admin_ui/src/components/AccountsView.tsx:599-606)는 `showSnapshotHistory` 토글을 제공:
- 기본값(false): `latestPositions` (최신 snapshot, 수량 0 필터 적용)
- 토글 ON(true): `positions` (전체 snapshot 이력, 수량 0 포함)

이렇게 하면:
- 일반 사용자: 0 수량 종목이 보이지 않아 화면 해석 용이
- 운영자/디버깅: 토글 클릭 한 번으로 전체 이력 확인 가능

---

## 5. 가장 작은 수정으로 문제를 해결하려면 어디를 고쳐야 하는가?

### 수정 대상

**단 1곳:** [`AccountsView.tsx`](admin_ui/src/components/AccountsView.tsx:103-112)

```typescript
// 현재 (103-112줄):
const latestPositions = useMemo(() => {
    const map = new Map<string, PositionSnapshotView>();
    for (const pos of positions) {
      const existing = map.get(pos.instrument_id);
      if (!existing || pos.snapshot_at > existing.snapshot_at) {
        map.set(pos.instrument_id, pos);
      }
    }
    return Array.from(map.values());
  }, [positions]);

// 수정 후:
const latestPositions = useMemo(() => {
    const map = new Map<string, PositionSnapshotView>();
    for (const pos of positions) {
      const existing = map.get(pos.instrument_id);
      if (!existing || pos.snapshot_at > existing.snapshot_at) {
        map.set(pos.instrument_id, pos);
      }
    }
    return Array.from(map.values()).filter(p => p.quantity > 0);
  }, [positions]);
```

**변경 사항 요약:**
- `return Array.from(map.values())` → `return Array.from(map.values()).filter(p => p.quantity > 0);`
- `.filter(p => p.quantity > 0)`로 수량 0 초과인 항목만 반환
- **DB, API, 리포지토리, 타입 — 모두 변경 없음**

---

## 6. 구현 계획

### 변경 파일
1. [`admin_ui/src/components/AccountsView.tsx`](admin_ui/src/components/AccountsView.tsx) — `latestPositions`에 `.filter(p => p.quantity > 0)` 추가

### 테스트 파일
1. [`admin_ui/src/__tests__/accounts.test.tsx`](admin_ui/src/__tests__/accounts.test.tsx) — 다음 테스트 케이스 추가:
   - `quantity=0` 항목이 `latestPositions`에서 제외되는지 검증
   - `quantity>0` 항목은 정상 표시되는지 검증
   - 스냅샷 이력 모드에서는 quantity=0도 표시되는지 검증

### 제외 사항
- 백엔드 API(`/positions`), 리포지토리, 스키마 — 변경 없음
- 다른 뷰(`OperationsAlertsView`, `Dashboard` 등) — 변경 없음
- DB migration — 불필요

---

## 7. 최종 결정 사항 요약

| 항목 | 결정 |
|---|---|
| 필터 위치 | **프론트엔드** (`AccountsView.tsx` `latestPositions`) |
| 이력 모드 | **유지** — `showSnapshotHistory=true` 시 전체 표시 |
| DB 변경 | **없음** — 데이터 보존 |
| API 변경 | **없음** — 공용 API 유지 |
| 리포지토리 변경 | **없음** — 설계 의도와 일치 |
| 수정 파일 수 | **1개** (테스트 파일별도) |
| 위험도 | **낮음** — 격리된 프론트 필터, 기존 동작 영향 없음 |
