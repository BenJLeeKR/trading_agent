# 2026-06-01 Accounts 기본 선택 정상화 최종 검증

## 검증 목적
- Accounts 첫 화면이 E2E client가 아니라 `.env`에 매핑된 운영 client/account를 기본으로 선택하는지 확인

## 확인한 기준
- `.env`
  - `KIS_ENV=paper`
  - `KIS_ACCOUNT_NO=50186448`
- DB 매핑
  - `broker_accounts.account_ref='50186448'`
  - `clients.client_code='EPC001'`
  - `accounts.account_code='EPC001-PAPER-ENTRYPOINT'`

## 검증 결과

### 1. DB 매핑 확인
- 운영 계좌 매핑 확인 완료
- 결과:
  - `client_code = EPC001`
  - `account_code = EPC001-PAPER-ENTRYPOINT`
  - `account_ref = 50186448`
  - `environment = paper`

### 2. API 기본 client 확인
- 실제 API 호출:
  - `GET /clients/default`
- 결과:
  - `client_code = EPC001`
  - `name = Entrypoint Client`
- 결론:
  - Accounts UI가 의존하는 기본 client API는 운영 client를 정상 반환함

### 3. 프론트엔드 AccountsView 검증
- 테스트:
  - `cd admin_ui && npx vitest run src/__tests__/accounts.test.tsx`
- 결과:
  - `26 passed`
- 포함된 핵심 검증:
  - `/clients` 목록에서 E2E client가 먼저 와도
  - `/clients/default`가 반환한 운영 client를 우선 선택하고
  - 그 client 기준으로 `/accounts`를 조회함

### 4. API 테스트 검증
- 테스트:
  - `pytest -q tests/api/test_clients.py`
- 결과:
  - `4 passed`

## 최종 판단
- Accounts 기본 선택 정상화는 현재 기준으로 완료 상태
- 첫 진입 기본 선택 기준은 이제 단순 정렬 순서가 아니라 `/clients/default`의 운영 client 응답임

## 남은 확인 사항
1. 브라우저 실화면에서 Accounts 첫 진입 시 `EPC001`이 기본으로 보이는지 최종 육안 확인
2. Orders 첫 화면이 운영 주문 중심으로 유지되는지 별도 재검증
