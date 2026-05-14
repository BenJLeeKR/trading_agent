# 운영 메모 정적 데이터 수정 계획 (v2 - 보정 반영)

## 문제 분석

### 현재 상태
1. **`operationNotes`** — 모듈 레벨 상수 (정적 데이터), 3개 하드코딩 항목
   - NOTE-001: `2026-05-13 오전 장 개장 전 포지션 정리 / 완료` ✅ (과거 데이터, 문제 없음)
   - NOTE-002: `2026-05-13 API 토큰 갱신 / 완료` ✅ (과거 데이터, 문제 없음)
   - **NOTE-003**: `2026-05-14 Pre-Market 점검 필요 / 대기` ❌ (실제 Pre-Market은 08:00 KST에 완료됨)

2. **`preMarketChecklist`** — 모듈 레벨 상수, 제목 "내일 Pre-Market 확인 사항"

3. **`fetchAlerts`** — 이미 `getSnapshotSyncRuns(1)` 호출하여 `snapshotSyncRun` 데이터 보유
   - 단, 컴포넌트 상태에 저장되지 않음 → 재활용 필요

## 변경 사항 (프런트엔드 전용, 1개 파일)

**Only [`OperationsAlertsView.tsx`](admin_ui/src/components/OperationsAlertsView.tsx)**

### 1. NOTE-003 제거
- `Pre-Market 점검 필요 / 대기` 항목 삭제
- NOTE-001, NOTE-002는 유지

### 2. 정적 메모 섹션 하단으로 이동 + 접을 수 있게 처리
- "운영 메모" 섹션을 화면 **최하단**으로 이동
- 접을 수 있는(collapsible) UI로 변경하여 기본적으로 접힌 상태
- 내부에 "(예시) 백엔드 API 미연동 상태에서는 샘플 데이터가 표시됩니다" 안내 문구 추가

### 3. 신규 "Pre-Market 스냅샷 동기화 실행" 동적 섹션 추가 (정적 메보 위)
- `fetchAlerts`에서 이미 가져오는 `snapshotSyncRun`을 `useState`에 저장
- 조건:
  - `snapshotSyncRun` 존재 + 오늘 날짜 run:
    - `completed` → "Pre-Market 스냅샷 동기화 실행" / `"완료"`
    - `partial` → 동일 action / `"주의"`
    - `failed` → "Pre-Market 스냅샷 동기화 실패" / `"긴급"`
  - `snapshotSyncRun` 존재 but 오늘 run 아님:
    - "오늘 Pre-Market 실행 이력 없음" / `"수동 확인 필요"`
  - `snapshotSyncRun` 없음 (`null`):
    - API error면 섹션 숨김 (alert으로 대체)
    - run 진짜 없으면 "오늘 Pre-Market 실행 이력 없음" / `"수동 확인 필요"`
- 문구는 **"Pre-Market 스냅샷 동기화 실행"**으로 제한 (이벤트/주문 동기화 포함으로 단정하지 않음)

### 4. `preMarketChecklist` 제목 변경
- "내일 Pre-Market 확인 사항" → **"Pre-Market 확인 리스트 (참고)"**
- 정적 체크리스트임을 명확히 표시

## 수정 파일

| 파일 | 변경 |
|------|------|
| [`OperationsAlertsView.tsx`](admin_ui/src/components/OperationsAlertsView.tsx) | NOTE-003 제거, useState 추가, 동적 섹션 추가, 정적 메모 하단 이동 + collapsible, 체크리스트 제목 변경 |

## 백엔드 필요 항목 (구현 제외, TODO로만 명시)

| 항목 | 설명 |
|------|------|
| 운영 메모 CRUD API | 운영자가 메모를 작성/수정/완료 처리하는 API |
| Scheduler phase 결과 저장/조회 API | Pre-Market/EOD 각 phase별 완료 상태를 영구 기록 |
| Admin UI phase별 완료 상태 표시 | 위 API를 기반으로 한 UI 표시 |

## 검증
- `cd admin_ui && npm run build`
- `cd admin_ui && npm run test:run`
- `#/operations/alerts`에서 `Pre-Market 점검 필요 / 대기`가 사라졌는지 확인
- 오늘 snapshot sync run이 있으면 "Pre-Market 스냅샷 동기화 실행"이 완료/주의/긴급 중 하나로 표시되는지 확인
