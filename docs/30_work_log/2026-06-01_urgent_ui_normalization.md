# 2026-06-01 긴급 UI 정상화

## 이번 작업에서 완료한 내용

### 1. Accounts 기본 선택 로직 강화
- 문제:
  - `AccountsView`가 `/clients` 응답의 첫 번째 항목으로 쉽게 되돌아갈 수 있었습니다.
  - E2E client가 운영 client보다 먼저 정렬되면 첫 화면이 다시 테스트 데이터 중심으로 보이는 문제가 있었습니다.
- 수정:
  - 먼저 `/clients/default`를 조회합니다.
  - 조회된 운영 client가 있으면, `/clients` 목록에서 해당 client를 맨 앞으로 재정렬합니다.
  - 가능한 경우 항상 그 운영 client 기준으로 `/accounts`를 조회하도록 고정했습니다.
- 수정 파일:
  - `admin_ui/src/components/AccountsView.tsx`
  - `admin_ui/src/__tests__/accounts.test.tsx`

### 2. Orders 첫 화면 상태
- 현재 상태:
  - 백엔드 기본 orders feed에서는 이미 E2E 계정/주문/종목 row가 제외되도록 방어가 들어가 있습니다.
  - 이번 작업에서는 추가 코드 수정이 필요하지 않았습니다.

## 지금 바로 확인해야 할 항목
- Accounts 첫 진입 시 `.env`에 매핑된 운영 client/account가 기본 선택되는지 확인
- `E2E-SUMMARY-CLIENT`가 다시 기본 선택으로 올라오지 않는지 확인

## 다음 작업
1. 프론트 테스트 통과 후 실제 API 응답 기준으로 Accounts UI 동작 재확인
2. 현재 DB 상태 기준으로 Orders 첫 화면이 운영 주문 중심으로 보이는지 재확인
3. 필요하면 `OrdersView`에 E2E symbol row가 기본 API payload에서 렌더링되지 않는지 검증 테스트 추가

## 남은 작업 일정

### 오늘
1. Accounts 기본 선택 정상화 최종 검증
2. Orders 첫 화면 운영 주문 노출 상태 재검증
3. 변경 후 paper 주문 제출 상태 실측
   - `BUDGET_EXHAUSTED`
   - `submitted`
   - `SKIPPED`
   비율 확인

### 1~2일 내
1. BUY skip 사유 분석
   - `non_actionable_decision`
   - `missing_reference_price_for_market_buy`
2. 현재 skip 기준이 과도하게 보수적인지 판단

### 이번 주 내
1. `truth_probe_conflict` 운영 검토 흐름 정리
2. `failure-summary` 수치가 실제 운영 컨테이너 기준으로 맞는지 검증
