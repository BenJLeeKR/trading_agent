# 2026-06-17 WATCH band / BUY gap 실측

## 목적

- `2026-06-17` 장중 `매수 의사결정`이 사실상 발생하지 않은 원인을
  감이 아니라 `trade_decisions.decision_json` 실측 기준으로 고정한다.
- 다음 단계인 `feature 기반 WATCH/BUY/SELL trigger` 리팩토링에서
  어떤 항목을 우선 수정해야 하는지 좁힌다.

## 확인 기준

- 데이터 소스: `trade_decisions`
- 기준 시각: `Asia/Seoul`
- 확인일:
  - `2026-06-16`
  - `2026-06-17`
- `source_type` 판정 경로:
  - `decision_json.deterministic_trigger.metadata.source_type`
  - 없으면 `decision_json.portfolio_allocation.metadata.source_type`
  - 없으면 `decision_json.strategy_selection.metadata.source_type`

## 핵심 결론

1. `2026-06-17`의 `core`와 `market_overlay`에서는
   `entry_score >= 0.65`를 만족한 행이 `0건`이었다.
2. 따라서 `BUY_CANDIDATE` 부재의 1차 원인은
   주문 가능 금액이나 사이징이 아니라
   `deterministic trigger`의 `entry_score` 자체다.
3. 특히 `market_overlay`는 평균 `entry_score=0.4366`,
   평균 `watch_score=0.5472`로
   `BUY threshold` 바로 아래의 `WATCH band`에 과밀되어 있다.
4. `core`는 평균 `entry_score=0.2018`이지만,
   `trigger_core_watch_path` 때문에 상당수가 `WATCH`로 유지된다.
5. `held_position`은 반대로 `exit_score`가 높아
   `REDUCE/SELL` 쪽으로 기울어 있으며,
   `entry_score`는 구조적으로 `trigger_held_position_buy_block` 때문에 낮다.

## 2026-06-17 실측 요약

### source_type별 행 수 / 종목 수

- `core`
  - row `48`
  - symbol `12`
- `market_overlay`
  - row `42`
  - symbol `10`
- `held_position`
  - row `297`
  - symbol `34`

### source_type별 점수 분포

- `core`
  - `avg_entry_score = 0.2018`
  - `avg_watch_score = 0.4453`
  - `BUY threshold(0.65) 이상 = 0건`
  - `entry_score 0.45~0.65 = 17건 / 9종목`
  - `primary_candidate=WATCH = 39건 / 12종목`
- `market_overlay`
  - `avg_entry_score = 0.4366`
  - `avg_watch_score = 0.5472`
  - `BUY threshold(0.65) 이상 = 0건`
  - `entry_score 0.45~0.65 = 33건 / 7종목`
  - `primary_candidate=WATCH = 42건 / 10종목`
- `held_position`
  - `avg_entry_score = 0.0476`
  - `avg_watch_score = 0.3762`
  - `avg_exit_score = 0.6762`
  - `REDUCE threshold(0.60) 이상 exit_score = 165건`
  - `SELL threshold(0.75) 이상 exit_score = 100건`

## 2026-06-17 의사결정 형태

- `core`
  - `WATCH = 38건`
  - `HOLD = 8건`
  - `APPROVE = 0건`
- `market_overlay`
  - `WATCH = 25건`
  - `HOLD = 17건`
  - `APPROVE = 0건`
- `held_position`
  - `APPROVE = 3건`
  - `HOLD = 62건`
  - `REDUCE = 147건`
  - `WATCH = 85건`

## WATCH band를 만든 반복 reason code

### core

- `trigger_source_core`
- `trigger_allocation_budget_available`
- `trigger_no_position_exit_penalty`
- `trigger_watch_candidate`
- `trigger_core_watch_path`
- `trigger_risk_off_penalty`
- `trigger_exit_risk_off`
- `trigger_bearish_regime`

해석:

- `core`는 예산 부족으로 막힌 것이 아니라
  예산이 있어도 `entry_score`가 약한 상태다.
- `risk_off` / `bearish` 조합이 붙는 순간
  `entry_score`는 낮아지고,
  `core_watch_path`가 `WATCH`를 유지한다.

### market_overlay

- `trigger_source_market_overlay`
- `trigger_allocation_budget_available`
- `trigger_market_overlay_bias`
- `trigger_no_position_exit_penalty`
- `trigger_watch_candidate`
- `trigger_watch_from_entry_setup`
- `trigger_risk_off_penalty`
- `trigger_exit_risk_off`
- `trigger_high_volatility`

해석:

- `market_overlay`는 `+0.05` bias를 받아도
  `risk_off_penalty(-0.15)`와 `high_volatility`, `exit_risk_off` 조합 때문에
  `0.45~0.65` 구간에 많이 머문다.
- 즉, 현재는 `market_overlay`가
  기대수익이 있는 진입 후보를 만들기보다
  관찰 후보를 대량 생성하는 구조에 가깝다.

## 대표 케이스

### core의 고정형 WATCH

- 여러 종목에서 반복적으로 다음 패턴이 나타났다.
  - `entry_score = 0.45`
  - `watch_score = 0.45`
  - `exit_score = 0.175`
  - `allocation_bias = neutral`
  - `target_weight_pct = 5.0`
  - reason:
    - `trigger_source_core`
    - `trigger_allocation_budget_available`
    - `trigger_no_position_exit_penalty`
    - `trigger_watch_from_entry_setup`
    - `trigger_core_watch_path`
    - `trigger_watch_candidate`

해석:

- 이 경우는 `feature`가 충분히 강해서 `BUY`에 접근한 것이 아니라,
  `core_watch_path`가 사실상 `기본 WATCH floor`로 작동한 것이다.

### market_overlay의 경계형 WATCH

- 대표 예시:
  - `entry_score = 0.5788`
  - `watch_score = 0.5788`
  - `exit_score = 0.2368`
  - `allocation_bias = de_risk`
  - `target_weight_pct = 3.0`
  - `preferred_strategy = defensive_low_volatility_rotation`
  - reason:
    - `trigger_bullish_regime`
    - `trigger_risk_off_penalty`
    - `trigger_market_overlay_bias`
    - `trigger_high_volatility`
    - `trigger_exit_risk_off`
    - `trigger_watch_from_entry_setup`
    - `trigger_watch_candidate`

해석:

- 진입 강도는 약하지 않지만
  `BUY threshold=0.65`를 넘기기엔 부족하다.
- 결국 `market_overlay`는 현재 구조에서
  `관심 종목 표시기` 역할이 더 강하다.

## 2026-06-16과의 비교에서 보이는 점

- `2026-06-16`에는 `held_position` 계열에서
  `WATCH -> APPROVE/REDUCE` 승격이 다수 있었다.
- 이는 이후 반영한 하드가드 수정 전 데이터이며,
  `held_position`의 `WATCH` 후보가 FDC에서
  `APPROVE`로 올라가는 문제가 실제로 존재했음을 보여준다.
- 반면 `2026-06-17`의 `core` / `market_overlay`는
  승격보다도 애초에 `BUY_CANDIDATE`가 `0건`인 것이 더 핵심이다.

## 바로 다음 리팩토링 타깃

1. `core_watch_path`의 역할 축소
   - 지금은 `feature`가 약한 상태에서도
     `WATCH`를 쉽게 생성하는 floor로 작동한다.
2. `market_overlay`의 `BUY threshold` 또는 가중치 구조 재설계
   - `risk_off_penalty`와 `market_overlay_bias`의 비대칭이 커서
     실제로는 `WATCH` 과밀을 만든다.
3. `entry_score`와 `watch_score`의 분리 강화
   - 현재는 `entry_score`가 경계값 아래에만 있어도
     거의 그대로 `WATCH`로 전달된다.
4. `WATCH`를 기대수익 기반의 유의미한 대기 상태로 축소
   - 현재는 `HOLD`와 `WATCH`의 경계가 넓고,
     특히 `core`에서 `WATCH`가 과도하게 많다.

## 권장 순서

1. `deterministic_trigger_engine.py`
   - `core_watch_path`
   - `watch_score` 생성 규칙
2. `market_overlay` entry 가중치 재조정
   - `risk_off_penalty`
   - `market_overlay_bias`
   - 필요 시 `buy_candidate_threshold`
3. 수정 후 같은 쿼리로 재실측
   - `entry_score >= 0.65`가 실제로 생기는지
   - `WATCH band`가 얼마나 줄었는지
   - `HOLD/WATCH/APPROVE` 비율이 어떻게 바뀌는지
