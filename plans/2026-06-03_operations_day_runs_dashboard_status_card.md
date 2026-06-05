# 2026-06-03 `operations_day_runs` 운영 대시보드 상태 카드 연결

## 목적

- 운영 대시보드의 `Scheduler Status` 카드가 더 이상 `market_sessions/latest`만으로 추정 상태를 표시하지 않도록 한다.
- `operations_day_runs`에 저장된 운영일 상태를 우선 사용해,
  - 비거래일
  - 장중 운영중
  - 장후
  - 종료
  - heartbeat 지연
  상태를 더 직접적으로 보여준다.

## 변경 범위

### 1. Admin UI 타입/클라이언트 추가

- `admin_ui/src/types/api.ts`
  - `OperationsDayRunSummary`
  - `OperationsDayStatusResponse`
  추가
- `admin_ui/src/api/client.ts`
  - `getLatestOperationsDay()`
  - `GET /market-sessions/operations-day/latest`
  추가

### 2. `OperationsDashboardView` 상태 해석 로직 변경

- `admin_ui/src/components/OperationsDashboardView.tsx`
  - `DashboardData.operationsDayData` 추가
  - `fetchAll()`에서 `getLatestOperationsDay()` 병렬 호출 추가
  - `getSchedulerStatus(...)`가 `operations_day_runs`를 우선 사용하도록 변경

우선순위:

1. `operations_day_runs`
2. 실패 시 기존 `market_sessions/latest` fallback

### 3. 카드 표시 규칙

`operations_day_runs` 기준:

- `is_trading_day=false` → `휴장`
- stale / unhealthy → `지연`
- `scheduler_status=intraday` → `운영중`
- `scheduler_status=after_hours` → `장후`
- `scheduler_status=end_of_day_complete` → `종료`
- 그 외 → `준비`

subtitle:

- `OPEN | 제출 X / HP매도 Y / cycles Z`
- 또는 `제출 X / HP매도 Y / cycles Z`

즉, 운영 카드에서 제출 카운트와 held-position sell 카운트도 같이 읽을 수 있게 했다.

## 테스트

### 단위/UI 테스트

- `cd admin_ui && npx vitest run src/__tests__/dashboard.test.tsx src/__tests__/schedulerStatus.test.ts`
- 결과: `42 passed`

### 타입 검증

- `cd admin_ui && npx tsc --noEmit`
- 결과: 통과

### 빌드 검증

- `cd admin_ui && npm run build`
- 결과: 통과

## 테스트 보강

- `admin_ui/src/__tests__/schedulerStatus.test.ts`
  - 기존 `market_sessions` 기반 케이스를 새 시그니처에 맞게 정리
  - `operations_day intraday` 우선 사용 케이스 추가
- `admin_ui/src/__tests__/dashboard.test.tsx`
  - `GET /market-sessions/operations-day/latest` mock 추가
  - `Scheduler Status` 카드가
    - `운영중`
    - `OPEN | 제출 2 / HP매도 1 / cycles 14`
    를 표시하는지 검증

## 결과

- 운영 대시보드는 이제 `operations_day_runs`를 우선 기준으로 상태를 표시한다.
- `market_sessions/latest`는 fallback으로만 남는다.
- 비거래일/장중/장후/종료를 더 운영 친화적으로 읽을 수 있다.

## 다음 단계

- 필요 시 `operations_day_runs` recent list / `run_date` filter 조회 API 추가
- 그 외 우선순위는 `2026-06-03_remaining_work_priority_map.md` 기준 다음 항목으로 이동
