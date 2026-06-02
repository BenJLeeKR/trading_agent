# 운영 대시보드 오늘 주문 제출 카드 수정

## 문제
운영 대시보드의 `오늘 주문 제출` 카드는 실제 오늘 주문 수를 세지 않았다.
기존 구현은 다음 두 문제를 동시에 갖고 있었다.

1. `GET /orders` 결과 길이 사용
- KST 오늘 날짜 필터 없이 최신 주문 목록 길이만 사용
- 최근 며칠치 주문이 섞여도 그대로 카운트됨

2. `/orders` 기본 limit=100 영향
- 목록 API 기본 limit이 100이라 카드가 `100건`처럼 보일 수 있음
- 실제 오늘 주문 수와 무관하게 cap에 걸린 결과를 보여줄 수 있음

추가로 subtitle의 `대기` 값도 `pending_submit`가 아니라 `submitted`를 세고 있어 의미가 어긋나 있었다.

## 적용한 수정
### 1. 백엔드 집계 API 추가
- `GET /orders/daily-summary`
- 기본 동작: `Asia/Seoul` 기준 오늘 00:00:00 ~ 23:59:59.999999 집계
- optional query: `date=YYYY-MM-DD`

응답 필드:
- `date`
- `timezone`
- `total_count`
- `filled_count`
- `pending_submit_count`
- `submitted_count`

### 2. 저장소 계층 집계 메서드 추가
`OrderRepository`에 아래 메서드 추가:
- `count(query)`
- `count_by_status(query)`

Postgres / InMemory 구현 모두 추가하여 테스트 경로와 운영 경로를 일치시켰다.

### 3. 프론트엔드 카드 수정
`OperationsDashboardView`는 이제 `GET /orders/daily-summary` 응답을 직접 사용한다.

변경 전:
- `data.orders.length`
- subtitle도 `/orders` 목록 기반 재계산

변경 후:
- `todayOrderSummary.total_count`
- subtitle: `체결 / 제출됨 / 제출대기`
- 출처 명시: `GET /orders/daily-summary`

## 검증
### 백엔드
- `tests/api/test_inspection.py`
  - KST 날짜 경계 테스트 추가
  - 같은 날 3건 / 전날 1건 시나리오로 정확한 count 확인
- `tests/api/test_postgres_inspection.py`
  - 응답 shape 검증 추가

### 프론트엔드
- `dashboard.test.tsx`
  - 새 API mock 추가
  - 카드 값 `2건` 표시 확인
- `tsc --noEmit` 통과

## 결과
이제 `오늘 주문 제출` 카드는
- 목록 limit의 영향을 받지 않고
- KST 오늘 날짜 기준으로만
- 실제 총 주문 수와 상태별 수를 정확히 표시한다.
