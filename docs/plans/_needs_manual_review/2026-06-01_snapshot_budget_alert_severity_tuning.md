# 스냅샷 budget fallback 경고 강도 보정

## 배경
paper 공유 예산 구조에서 `VTTC8908R_pre_check`는 `orderable_cash` 보조 조회를 실제 API 호출 대신 안전한 대체값으로 처리했다는 뜻이다. 이는 cash snapshot 전체 실패와는 다르며, 운영상 즉시 경고로 볼 수준은 아니다.

반면 아래 두 경우는 실제 hard fallback으로 취급할 필요가 있다.
- `VTTC8908R_budget_exhausted`
- `VTTC8908R_api_failure`

## 문제
기존 UI/알림은 `pre-check fallback`도 `budget exhausted`, `api failure`와 같은 수준으로 묶어 보여줬다.
- 운영 대시보드 subtitle
- Accounts 화면 sync 요약
- Operations Alerts 규칙 `SNAP-BUDGET-001`

그 결과 snapshot이 정상 저장돼도 과한 경고처럼 보일 수 있었다.

## 적용한 수정
1. `admin_ui/src/lib/snapshotBudget.ts`
- snapshot budget counter 파싱 helper 추가
- 표시용 parts formatter 추가
- hard fallback 수 계산 helper 추가

2. 화면 문구 보정
- `pre-check fallback` → `pre-check 대체`로 변경
- 적용 위치
  - `OperationsDashboardView.tsx`
  - `AccountsView.tsx`
  - `OperationsAlertsView.tsx`

3. 경고 규칙 보정
- `SNAP-BUDGET-001`는 이제 `budget_exhausted + api_failure > 0`일 때만 발생
- `pre-check`만 있는 경우는 경고 미발생
- alert description도 `hard fallback` 기준으로 표시

## 테스트
- `alerts.test.ts`
  - pre-check only → alert 미발생
  - hard fallback 존재 → alert 발생
- `snapshotBudget.test.ts`
  - 표시 문구 포맷 검증
  - hard fallback count 계산 검증
- `tsc --noEmit`

## 기대 효과
- 정상 cash snapshot + pre-check 대체 상황이 과한 운영 경고로 보이지 않는다.
- 실제 대응이 필요한 `budget exhausted`, `api failure`만 경고로 분리된다.
- 운영자가 스냅샷 문제의 심각도를 더 정확히 해석할 수 있다.
