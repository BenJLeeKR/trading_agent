# 2026-06-01 Orders 첫 화면 운영 주문 우선 노출 재검증

## 검증 목적
- Orders 첫 화면이 E2E 테스트 주문이 아니라 운영 계좌 주문 중심으로 표시되는지 확인
- 특히 `E2ESUM` 종목과 `E2E-%` 계정 주문이 기본 주문 목록을 오염시키지 않는지 확인

## 현재 방어 로직
- `PostgresOrderRepository.list()`에서 기본 주문 목록 조회 시 다음 조건을 적용함
  - `a.account_code NOT LIKE 'E2E-%'`
  - `i.symbol != 'E2ESUM'`
- 정렬 기준은 `o.created_at DESC`
- 따라서 기본 `/orders` 응답은 최신 운영 주문을 먼저 반환해야 함

## DB 검증 결과
- 최신 20건 주문은 모두 운영 계좌 기준으로 확인됨
  - `account_code = EPC001-PAPER-ENTRYPOINT`
  - 최근 심볼 예시: `004990`, `001740`, `000150`, `006260`, `005935`, `005930`
- 전체 주문 테이블 기준 E2E 오염 여부
  - `E2ESUM` 주문: 0건
  - `E2E-%` 계정 주문: 0건

## API 검증 결과
- 실제 API 호출:
  - `GET /orders?limit=20`
- 결과:
  - 최신 20건 모두 운영 계좌 ID 기준 주문
  - `E2ESUM` 없음
- 추가 확인:
  - `GET /orders?limit=100` 결과에서 `symbol == "E2ESUM"` 건수는 0건

## 테스트 결과
- 프론트엔드:
  - `cd admin_ui && npx vitest run src/__tests__/orders.test.tsx`
  - 결과: `10 passed`
- 백엔드/repository/API 관련:
  - `pytest -q tests/repositories/test_orders.py tests/api/routes/test_orders_manual_resolve.py tests/api/test_order_submission_attempts.py`
  - 결과: `37 passed`

## 최종 판단
- Orders 첫 화면 운영 주문 우선 노출은 현재 기준으로 정상
- 기본 API 응답과 UI 렌더링 테스트 모두 통과
- `E2ESUM` 또는 E2E 계정 주문이 기본 Orders 화면에 다시 보이는 증거는 없음

## 다음 작업
1. paper 주문 안정화 이후 실제 주문 흐름 실측
   - `submitted`
   - `rejected`
   - `BUDGET_EXHAUSTED`
   - `SKIPPED`
2. BUY skip 사유 비율 분석
   - `non_actionable_decision`
   - `missing_reference_price_for_market_buy`
