# 운영 대시보드 실패 카드/스냅샷 카드 단순화

## 요청 내용
1. `최근 제출 실패` 카드에서 `최근 1시간 x건 / 24시간 x건` 대신 `오늘 x건` 중심으로 표시
2. `마지막 스냅샷 동기화` 카드 하단의 계좌 정합 세부 블록 제거

## 문제
### 최근 제출 실패 카드
기존 카드는 1시간/24시간 rolling window를 동시에 노출했다.
- 운영자가 원하는 기준은 `오늘` 기준 누적 건수였다.
- `24시간` 값은 자정 경계에서 `오늘`과 다를 수 있어 라벨을 바꾸기만 하면 안 됐다.

### 마지막 스냅샷 동기화 카드
기존 카드 하단에는
- `계좌 정합 상태`
- `동기화 완료 1개`
- `✓ 모든 계좌 정합`
같은 세부 정보가 붙었다.
요청 기준에서는 스냅샷 카드가 정상/주의/즉시확인만 보여주면 충분하므로 정보 과잉이었다.

## 적용한 수정
### 1. failure-summary API 확장
기존 1시간/24시간 집계는 유지하면서, KST 오늘 기준 집계를 추가했다.

추가 필드:
- `today_count`
- `rejected_count_today`
- `exception_count_today`
- `total_submissions_today`
- `failure_rate_pct_today`

적용 위치:
- `src/agent_trading/repositories/postgres/order_submission_attempts.py`
- `src/agent_trading/repositories/memory.py`
- `src/agent_trading/api/schemas.py`
- `src/agent_trading/repositories/contracts.py`

### 2. 운영 대시보드 카드 변경
`OperationsDashboardView`에서:
- 값: `오늘 {today_count}건`
- subtitle: `실패율: {failure_rate_pct_today}% (오늘) | 거절 {rejected_count_today}건 · 예외 {exception_count_today}건`
- 상태: `today_count > 0`이면 warning, 0이면 neutral

### 3. 스냅샷 카드 하단 정합 블록 제거
`마지막 스냅샷 동기화` 카드의 child block 전체 제거.
이에 따라 alignment helper / derived summary도 함께 제거했다.

## 테스트
### 백엔드
- `tests/api/test_order_submission_attempts.py`
  - today 필드 검증 추가
- `tests/api/test_inspection.py`
  - daily summary 검증 유지

### 프론트엔드
- `admin_ui/src/__tests__/dashboard.test.tsx`
  - `오늘 x건` 문구로 갱신
  - today failure rate / today rejected/exception 검증
- `npx tsc --noEmit`

## 결과
- `최근 제출 실패` 카드는 이제 오늘 기준으로 더 직관적으로 표시된다.
- `마지막 스냅샷 동기화` 카드는 핵심 상태만 남고 하단 세부 블록은 제거됐다.
