# paper ORDER bucket refill을 global gate와 정렬

## 배경

paper 환경에서는 submit path가 이미 `global_rest=1RPS` pacing에 맞춰 직렬화되고 있다.

그런데 로컬 `ORDER` bucket은 다음처럼 더 느리게 설정되어 있었다.

- `capacity = 3`
- `refill_rate = 0.1/s`

이 조합 때문에 짧은 시간에 BUY 3건이 연속 제출되면, 그 뒤 주문은 KIS 1RPS 제한보다 먼저 로컬 `ORDER` bucket에서 `BUDGET_EXHAUSTED(order)`로 막혔다.

즉, 실제 병목은 KIS가 아니라 내부 budget 설정이었다.

## 수정 내용

`src/agent_trading/brokers/rate_limit.py`의 paper budget factory를 조정했다.

- 유지:
  - `order_capacity = max(3, int(total * 3))`
- 변경:
  - `order_refill_rate = 0.1 * total`
  - → `order_refill_rate = 1.0 * total`

paper 1RPS 기준으로 보면:

- 이전: `order_capacity=3`, `order_refill_rate=0.1/s`
- 이후: `order_capacity=3`, `order_refill_rate=1.0/s`

즉, burst 여유는 유지하되 refill 속도를 global gate와 동일하게 맞췄다.

## 기대 효과

- submit pacing이 1초 간격으로 진행될 때
- 로컬 `ORDER` bucket이 먼저 바닥나서 BUY를 거절하는 현상 감소
- 실제 제약은 `global_rest`와 KIS 1RPS가 맡고,
  `ORDER` bucket은 보조 안전장치 역할만 수행

## 테스트

실행:

`pytest -q tests/brokers/test_rate_limit.py tests/brokers/test_budget_exhaustion.py tests/brokers/test_kis_adapter_validation.py`

결과:

- `63 passed`

추가 검증:

- `build_kis_budget_manager(kis_env='paper', paper_rest_rps=1)`
  - `order_capacity == 3`
  - `order_refill_rate == 1.0`
  - `global_refill_rate == 1.0`

## 비고

이 변경은 `global_rest`를 우회하는 것이 아니다.  
오히려 이미 존재하는 1RPS global gate와 로컬 ORDER bucket의 refill을 일치시켜, paper submit 경로가 자기모순적으로 먼저 막히지 않도록 정렬한 것이다.
