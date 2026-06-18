# 2026-06-17 REDUCE sizing 보유수량 비율 기준 정렬

## 배경

- 2026-06-17 장중 동일 종목에 대한 반복 `REDUCE` 매도가 다수 발생했다.
- 실측 결과 반복 매도 자체는 실제 `REDUCE/EXIT` 판단이 여러 사이클에 걸쳐 재생성된 결과였지만,
  그 안에 `1주 매도`가 비정상적으로 섞여 있었다.
- 원인 추적 결과, 현재 구현은 `REDUCE`의 `size_adjustment_factor`를
  `매도 비율`이 아니라 사실상 `잔여 보유 비율`처럼 해석하고 있었다.
- 그 결과 `size_adjustment_factor=1.0`인 경우 `0주`가 계산된 뒤,
  execution 단계에서 SELL 공통 fallback이 placeholder `request.quantity=1`을 다시 살려
  `1주 매도`를 만들어냈다.

## 실측 근거

- `trade_decisions.quantity`는 현재 의사결정 placeholder `1`이므로 실제 제출 수량 근거로 사용할 수 없다.
- 실제 제출 수량은 `order_requests.requested_quantity`를 기준으로 봐야 한다.
- 2026-06-17 기준 주요 종목 패턴:
  - `001230`: `380 -> 189 -> 74 -> 37 -> 18 -> 8 -> ...` 중간중간 `1주` 반복
  - `000050`: `65 -> 32 -> 13 -> 5 -> 2 -> 1`
  - `000370`: `81 -> 40 -> 20 -> 10 -> 5 -> 3 -> 1`
- 특히 `size_mode=reduce`, `size_adjustment_factor=1.0` 케이스에서
  `1주 주문` 또는 `주문 미발생`이 집중되었다.

## 코드 기준 원인

### 1. `REDUCE` factor 해석 오류

- 기존 [`src/agent_trading/services/sizing_engine.py`](../src/agent_trading/services/sizing_engine.py)
  의 `_base_qty_reduce()`는 아래처럼 동작했다.
  - `reduction = current_position_qty * factor`
  - `base_qty = current_position_qty - reduction`
- 그러나 `AIRiskOutput.size_adjustment_factor` 문서는
  `0.5 = 절반 축소`, `1.0 = 포지션 0까지 축소`를 의미한다.
  - [`src/agent_trading/services/ai_agents/schemas.py`](../src/agent_trading/services/ai_agents/schemas.py)
- 즉 `REDUCE` sell 수량은 `current_position_qty * factor`로 해석되어야 한다.

### 2. held-position SELL zero fallback 문제

- [`src/agent_trading/services/execution_service.py`](../src/agent_trading/services/execution_service.py)
  에는 `SELL/REDUCE/EXIT`에서 sizing 결과가 `0`이면
  `intent.request.quantity`로 fallback 하는 경로가 있다.
- held-position `REDUCE/EXIT` 요청의 `intent.request.quantity`는 현재 placeholder `1`이므로,
  sizing 결과 `0`이 나오는 순간 실제 제출이 `1주`로 왜곡될 수 있다.
- 이 fallback은 일반 SELL 보호 장치로는 의미가 있으나,
  held-position `REDUCE/EXIT`에는 적용되면 안 된다.

## 이번 수정 원칙

1. `REDUCE + size_mode in ("reduce", "fractional_reduce")`는
   `보유수량 기준 매도 비율`로 해석한다.
2. factor는 `0.0 ~ 1.0` 범위로 clamp 한다.
3. factor > 0 인데 floor 결과가 0이면 최소 `1주`를 반환한다.
   - 단, 이 `1주`는 `보유수량 * 비율` 계산의 최소 단위 보정이며,
     placeholder fallback과는 다르다.
4. held-position `REDUCE/EXIT SELL`은 sizing 결과가 `0`일 때
   placeholder `1주` fallback을 타지 않고 sizing skip으로 종료한다.

## 적용 범위

- 코드
  - [`src/agent_trading/services/sizing_engine.py`](../src/agent_trading/services/sizing_engine.py)
  - [`src/agent_trading/services/execution_service.py`](../src/agent_trading/services/execution_service.py)
- 테스트
  - [`tests/services/test_sizing_engine.py`](../tests/services/test_sizing_engine.py)
  - [`tests/services/test_decision_submit_pipeline.py`](../tests/services/test_decision_submit_pipeline.py)

## 기대 효과

- `size_adjustment_factor=1.0`이 `1주 매도`로 왜곡되지 않고 `전량 매도`로 해석된다.
- `0.5`, `0.8` 등도 문서 의미대로 각각 `50%`, `80%` 매도 비율로 정렬된다.
- held-position `REDUCE/EXIT`에서 sizing 오류가 발생해도
  placeholder `1주` 주문이 살아나는 경로를 제거할 수 있다.

## 후속 작업

- 다음 작업으로 별도 진행:
  - `trade_decisions.quantity`를 placeholder가 아닌
    실제 deterministic sizing 결과와 어떻게 분리/기록할지 정리
- 운영 재검증 항목:
  - 동일 종목 반복 `REDUCE` 빈도 자체가 과도한지
  - `held_position_sell_cycle_cap` 계열 stop reason 잔존 경로가 남아 있는지
