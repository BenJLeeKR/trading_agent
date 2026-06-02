# KIS 주문 수량 정수 문자열 정규화

## 배경

국내주식 KIS 주문 바디의 `ORD_QTY`는 정수 주식 수량을 문자열로 보내는 것이 안전하다.  
하지만 현재 구현은 `str(request.quantity)`를 그대로 사용하고 있어, `207.00000000`처럼 소수점 꼬리가 붙은 문자열이 그대로 전송될 수 있었다.

이 형식은 내부적으로는 같은 의미일 수 있어도, 브로커 전문 바디 검증이 엄격한 구간에서는 불필요한 형식 리스크가 된다.

## 수정 내용

### 1. 수량 포맷 helper 추가

`src/agent_trading/brokers/koreainvestment/rest_client.py`에 `_format_order_quantity()`를 추가했다.

규칙:

- `quantity <= 0` 이면 `ValueError`
- 정수 주식 수량이 아니면 (`1.5` 등) `ValueError`
- 정수 수량이면 `"207"` 같은 순수 정수 문자열로 변환

### 2. 적용 범위

다음 두 경로에 동일하게 적용했다.

- `submit_order()`의 `ORD_QTY`
- `cancel_order()`의 `ORD_QTY`

즉, 신규 주문과 취소/정정 주문 모두 KIS에 정수 문자열만 보내도록 통일했다.

## 기대 효과

- `207.00000000` 같은 형식 노이즈 제거
- KIS 주문 전문 바디 형식 안정성 향상
- fractional quantity가 브로커까지 내려가기 전에 애플리케이션 레벨에서 즉시 차단

## 테스트

실행:

`pytest -q tests/brokers/koreainvestment/test_rest_client_submit.py tests/brokers/test_kis_adapter_validation.py tests/brokers/test_budget_exhaustion.py`

결과:

- `58 passed`

추가한 검증:

- `Decimal("207.00000000")` → `ORD_QTY == "207"`
- `Decimal("1.5")` → submit 전에 `ValueError`
- helper 단위 검증: 정수 문자열 정규화 / 0 수량 거절

## 참고

로컬 `py_compile`은 기존 컨테이너가 생성한 `__pycache__` 권한 문제로 생략했고, 대신 관련 브로커 회귀 테스트 전체 통과로 검증했다.
