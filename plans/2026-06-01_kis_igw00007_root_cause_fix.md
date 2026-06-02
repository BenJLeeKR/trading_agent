# 2026-06-01 KIS `IGW00007` 주문 바디 오류 수정

## 배경

2026-06-01 11:08 KST에 `001740` 보유 포지션 자동 SELL 주문이
`submission_failed_no_broker_id`로 정리되었다.

직접 원인을 추적한 결과, 실제 브로커 제출 단계에서는 다음 에러가 발생했다.

- `KIS order_cash: HTTP 500 (msg_cd=IGW00007): MCA 전문바디 구성 중 오류가 발생하였습니다.`

동일한 패턴은 과거 `000660` held-position SELL에서도 확인되었다.

## 원인 분석

### 1. 직접 원인

`src/agent_trading/brokers/koreainvestment/rest_client.py`의
`submit_order()`가 국내주식 `order-cash` 요청 바디에 문서상 존재하지 않는
`ALGO` 필드를 추가하고 있었다.

기존 전송 형태:

```json
{
  "CANO": "...",
  "ACNT_PRDT_CD": "01",
  "PDNO": "001740",
  "ORD_DVSN": "01",
  "ORD_QTY": "207.00000000",
  "ORD_UNPR": "0",
  "ALGO": "01"
}
```

### 2. 문서 근거

`reference_docs/kis_openapi_full_20260503_markdown/020_주식주문(현금).md`
기준 요청 바디 필드는 다음만 정의되어 있다.

- `CANO`
- `ACNT_PRDT_CD`
- `PDNO`
- `SLL_TYPE` (선택)
- `ORD_DVSN`
- `ORD_QTY`
- `ORD_UNPR`
- `CNDT_PRIC` (특정 주문만)
- `EXCG_ID_DVSN_CD` (선택)

즉, 국내주식 `주식주문(현금)` API에는 `ALGO` 필드가 없다.

또한 IOC/FOK는 별도 필드가 아니라 `ORD_DVSN` 코드로 표현해야 한다.

- 지정가 DAY: `00`
- 시장가 DAY: `01`
- IOC 지정가: `11`
- FOK 지정가: `12`
- IOC 시장가: `13`
- FOK 시장가: `14`

### 3. 왜 일부 주문은 성공했는가

동일한 잘못된 필드가 항상 즉시 실패를 내지는 않았던 것으로 보인다.
하지만 paper KIS 서버는 보유 포지션 자동 SELL 경로에서 이 잘못된 바디를
`IGW00007`로 거부한 사례가 실제로 누적 확인되었다.

즉, 기존 구현은 “우연히 통과하는 주문도 있었지만 규격상 잘못된 요청”이었다.

## 수정 내용

### 파일

- `src/agent_trading/brokers/koreainvestment/rest_client.py`
- `tests/brokers/koreainvestment/test_rest_client_submit.py`

### 코드 변경

1. `submit_order()`에서 `ALGO` 필드 제거
2. `order_type + time_in_force` 조합을 `ORD_DVSN` 하나로 인코딩하도록 변경
3. 기존 `_map_time_in_force()` 제거
4. `_map_order_type()`를 `_map_order_style()`로 교체

신규 매핑:

- `LIMIT + DAY` → `00`
- `LIMIT + IOC` → `11`
- `LIMIT + FOK` → `12`
- `MARKET + DAY` → `01`
- `MARKET + IOC` → `13`
- `MARKET + FOK` → `14`

## 검증

### 테스트

실행:

```bash
pytest -q \
  tests/brokers/koreainvestment/test_rest_client_submit.py \
  tests/brokers/test_kis_adapter_validation.py \
  tests/brokers/test_budget_exhaustion.py
```

결과:

- `54 passed`

### 추가 검증 포인트

- LIMIT DAY 요청 바디에 `ALGO`가 더 이상 포함되지 않음
- IOC MARKET 요청이 `ORD_DVSN=13`으로 인코딩됨
- paper submit pacing 관련 기존 테스트 회귀 없음

## 운영 반영

다음 컨테이너를 재시작하여 런타임 반영:

- `app`
- `ops-scheduler`

## 기대 효과

### 재발 방지

앞으로 국내주식 `order-cash` 주문은 KIS 문서 형식에 맞는 바디로만 전송된다.
따라서 `ALGO` 오전송 때문에 발생하던 `HTTP 500 / IGW00007 / MCA 전문바디 구성 오류`
재발 가능성은 제거되었다.

### 부가 효과

기존 IOC/FOK 주문도 잘못된 별도 필드가 아니라 KIS 공식 `ORD_DVSN` 코드로
정상 인코딩되므로, 향후 해당 주문 타입 도입 시에도 형식 오류를 줄일 수 있다.
