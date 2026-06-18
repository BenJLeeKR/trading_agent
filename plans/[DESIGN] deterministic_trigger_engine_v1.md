# Deterministic Trigger Engine V1 설계

> 작성일: 2026-06-16
>
> 목적:
> 현재 `signal feature snapshot → market regime → strategy selection → portfolio allocation`
> 까지 구축된 deterministic 입력 계층을
> `WATCH / BUY / SELL / REDUCE 후보 생성` 계층으로 승격하기 위한
> V1 설계를 정의한다.

## 1. 배경

현재 시스템은 feature를 이미 계산하고 저장하며,
그 결과를 AI Risk / FDC prompt에 read-only로 주입하고 있다.

하지만 아직 구조의 중심은 다음과 같다.

- deterministic 계층은 입력을 계산한다
- AI 계층은 최종 판단을 생성한다
- deterministic 계층은 후단 guardrail / sizing / execution을 강제한다

이 구조는 운영 안전성 측면에서는 유효하지만,
`기대수익률 최대화`를 위한 실험/분석 관점에서는 한계가 있다.

대표적인 문제:

1. `WATCH` 부재나 `SELL` 감소 원인을 feature threshold와 직접 연결하기 어렵다.
2. AI가 무엇을 생성했고 무엇을 뒤집었는지 분리 측정이 어렵다.
3. backtest / replay / live 간 candidate 분포 정렬성이 약하다.

따라서 다음 단계는
`AI가 처음부터 판단을 창조하는 구조`를 유지하는 것이 아니라,
**deterministic trigger engine이 candidate를 만들고,
AI는 그 candidate를 해석/승인/보류/기각하는 구조**로 이동하는 것이다.

---

## 2. 목표

V1 목표는 다음 네 가지다.

1. `WATCH / BUY / SELL / REDUCE` 후보를 deterministic하게 생성한다.
2. 후보 생성 근거를 `reason_codes + score + threshold + source_type` 형태로 저장한다.
3. AI Risk / FDC는 후보 생성기가 아니라 `policy / override 계층`으로 더 얇아진다.
4. 기존 execution / sizing / guardrail / reconciliation 경계는 그대로 유지한다.

V1은 **후보 생성까지만 authoritative**하다.
즉, V1에서 trigger engine이 직접 broker submit을 유발하지는 않는다.

---

## 3. 비목표

다음은 V1 범위에 포함하지 않는다.

1. trigger engine이 최종 주문을 직접 확정하는 것
2. 새로운 AI agent 추가
3. 브로커 submit 경계 변경
4. 실시간 분봉/틱 기반 초단타 trigger
5. 성과 attribution의 완전 구현

즉, V1은
`candidate generation layer`를 세우는 설계와 1차 구현을 목표로 한다.

---

## 4. 위치

권장 파일:

- `src/agent_trading/services/deterministic_trigger_engine.py`

권장 호출 위치:

- `DecisionOrchestratorService.assemble()`
  - `signal_feature_snapshot`
  - `market_regime`
  - `strategy_selection`
  - `portfolio_allocation`
  계산 직후

권장 흐름:

1. context assembly
2. deterministic derivation
   - regime
   - strategy
   - portfolio
   - trigger candidate
3. AI policy
   - EI / AR / FDC
4. decision materialization
5. execution preparation

---

## 5. 입력 계약

V1 입력은 현재 이미 존재하는 deterministic 구조를 재사용한다.

### 5.1 필수 입력

- `symbol`
- `market`
- `source_type`
- `signal_feature_snapshot`
- `market_regime`
- `strategy_selection`
- `portfolio_allocation`

### 5.2 선택 입력

- `position_snapshot`
- `cash_balance_snapshot`
- `risk_limit_snapshot`
- `recent_events`

### 5.3 입력 원칙

1. V1의 authoritative input은 가능한 한 deterministic snapshot 우선이다.
2. raw news narrative는 trigger 생성의 1차 입력으로 삼지 않는다.
3. event는 trigger 생성보다는 candidate risk modifier 수준으로만 제한한다.

즉, V1은
`가격/수급/모멘텀/변동성 기반 candidate 생성`
에 집중한다.

---

## 6. 출력 계약

## 6.1 핵심 출력 구조

```python
DeterministicTriggerAssessment
```

권장 필드:

- `trigger_version: str`
- `primary_candidate: str`
- `candidate_set: tuple[str, ...]`
- `watch_candidate: bool`
- `buy_candidate: bool`
- `sell_candidate: bool`
- `reduce_candidate: bool`
- `candidate_confidence: float`
- `entry_score: float | None`
- `exit_score: float | None`
- `watch_score: float | None`
- `reason_codes: tuple[str, ...]`
- `thresholds: dict[str, float]`
- `metadata: dict[str, object]`

## 6.2 candidate 값 정의

`primary_candidate`는 아래 중 하나다.

- `NO_ACTION`
- `WATCH`
- `BUY_CANDIDATE`
- `SELL_CANDIDATE`
- `REDUCE_CANDIDATE`

`candidate_set`은 복수 후보를 허용한다.

예:

- `(WATCH,)`
- `(WATCH, BUY_CANDIDATE)`
- `(REDUCE_CANDIDATE, SELL_CANDIDATE)`

원칙:

- `primary_candidate`는 downstream 설명/로그용 대표값
- `candidate_set`은 실제 분포 분석/override 분석용

---

## 7. V1 규칙 설계

## 7.1 기본 철학

V1은 확률 모델이 아니라
`명시적 점수 + threshold + source_type 정책` 기반이다.

다음 세 점수를 계산한다.

- `entry_score`
- `exit_score`
- `watch_score`

이 점수는 0~1 범위 정규화가 바람직하다.

---

## 7.2 Entry Score

`BUY_CANDIDATE` 생성을 위한 점수.

권장 반영 요소:

- `signal_feature_snapshot.overall_score`
- `signal_feature_snapshot.fast_score`
- `signal_feature_snapshot.slow_score`
- `signal_feature_snapshot.volume_surge_ratio`
- `signal_feature_snapshot.turnover_surge_ratio`
- `market_regime.regime_label`
- `market_regime.risk_tone`
- `strategy_selection.preferred_strategy`
- `portfolio_allocation.max_new_capital_pct`

예시 규칙:

- bullish_trend + risk_on + overall_score 높음
- portfolio allocation에 신규 자본 여유 존재
- source_type이 `core` 또는 `market_overlay`

기각 조건:

- `portfolio_allocation.max_new_capital_pct <= 0`
- `market_regime.risk_tone == risk_off`
- `relative volume`와 `relative turnover`가 동시에 낮아
  상대 활동성이 부족한 경우
- `source_type == held_position`

---

## 7.3 Exit Score

`SELL_CANDIDATE` 또는 `REDUCE_CANDIDATE` 생성을 위한 점수.

권장 반영 요소:

- `signal_feature_snapshot.overall_score` 하락
- `fast_score < 0`
- `slow_score < 0`
- `price_vs_sma_20_pct`, `price_vs_sma_60_pct`
- `market_regime.regime_label == bearish_trend`
- `market_regime.volatility_regime == high_volatility`
- `portfolio_allocation.current_weight_pct`
- `portfolio_allocation.remaining_concentration_pct`
- `position_snapshot` 존재 여부

예시 규칙:

- 보유 중인데 추세 붕괴 + risk_off + high_volatility
  → `REDUCE_CANDIDATE`
- 보유 중인데 신호가 강하게 음수 + 과집중 + bearish_trend
  → `SELL_CANDIDATE`

핵심:

- `held_position`에는 신규 BUY보다 exit trigger가 우선이다.
- 현재 운영에서 중요도가 높은 축은 `risk-reducing SELL`이다.

---

## 7.4 Watch Score

`WATCH` 생성용 점수.

WATCH는 V1에서 가장 먼저 deterministic하게 활성화할 가치가 높다.

권장 반영 요소:

- signal score가 buy threshold 직전이거나
- signal score가 exit threshold 직전이거나
- no-event지만 정량 signal이 존재하거나
- overlay source에서 actionability는 있으나 confidence가 부족한 경우

예시 규칙:

- `entry_score >= 0.45` 이고 `BUY_CANDIDATE` threshold 미만
- `exit_score >= 0.45` 이고 `SELL/REDUCE` threshold 미만
- `source_type == core` + `no_material_events`라도
  `overall_score` 또는 `regime`가 유의미하면 `WATCH`
- `volume_surge_ratio` 또는 `turnover_surge_ratio`가 유의미하게 상승했지만
  아직 BUY threshold를 넘지 못한 경우 `WATCH`

즉, WATCH는
`신호가 없어서 HOLD`가 아니라
`후속 재평가 가치가 있는 후보`를 의미하게 재정의한다.

---

## 7.5 source_type별 정책

### `core`

- 기본 목표:
  - `HOLD 100%` 완화
  - no-event라도 정량 signal 기반 WATCH 허용
- 보수적 BUY candidate
- exit는 보유 중일 때만 의미 있음

### `held_position`

- 신규 BUY candidate 생성 금지
- `REDUCE_CANDIDATE`, `SELL_CANDIDATE` 우선
- concentration / trend breakdown / risk_off에 민감

### `event_overlay`

- WATCH / BUY 모두 가능
- time horizon 짧게
- event 자체는 AI가 해석하되,
  deterministic trigger는 price/volume/volatility 상태만 우선 반영

### `market_overlay`

- WATCH / BUY candidate 적극 허용
- fast_score 비중 확대
- liquidity filter 통과 전제
- 절대 거래대금보다 `relative volume` / `relative turnover`를 우선 반영

---

## 8. V1 threshold 초안

숫자는 확정값이 아니라 1차 운영용 초안이다.

- `buy_candidate_threshold = 0.65`
- `watch_candidate_threshold = 0.45`
- `reduce_candidate_threshold = 0.60`
- `sell_candidate_threshold = 0.75`

보조 제약:

- `portfolio_allocation.max_new_capital_pct > 0`
- `portfolio_allocation.recommended_max_order_value > 0`
- `held_position`이 아니면 SELL/REDUCE 금지
- `held_position`이면 BUY 금지

운영 중 조정이 필요한 값은
config 또는 strategy policy version으로 분리하는 것이 바람직하다.

추가 원칙:

- BUY/WATCH ranking은 절대 점수만으로 정렬하지 않고
  `relative activity`를 별도 가산점으로 반영한다.
- 특히 `market_overlay`와 `core`의 intraday 재정렬에서는
  `turnover_surge_ratio`가 낮은 종목이 상단을 장기 점유하지 않도록 한다.

---

## 9. AI 계층과의 경계

## 9.1 AI Risk

AI Risk는 trigger를 생성하지 않는다.
대신 다음 역할만 가진다.

- candidate가 위험상 유지 가능한지 의견 제공
- size adjustment factor 제안
- concentration / volatility / event uncertainty 해석

즉:

- trigger engine: `무슨 후보가 생겼는가`
- AI Risk: `그 후보를 얼마나 보수적으로 봐야 하는가`

## 9.2 Final Decision Composer

FDC는 다음 역할로 축소한다.

- candidate 승인
- candidate 보류
- candidate 승격
- candidate 기각
- 복수 candidate 중 최종 action 선택

즉, FDC는
`무에서 BUY/SELL을 만드는 계층`이 아니라,
`deterministic candidate를 policy적으로 정리하는 계층`이 된다.

---

## 10. persistence 설계

V1에서는 최소 아래 정보가 저장돼야 한다.

### 10.1 `AssembledContext`

- `deterministic_trigger_assessment`

### 10.2 `decision_json`

- `deterministic_trigger`
  - `primary_candidate`
  - `candidate_set`
  - `candidate_confidence`
  - `entry_score`
  - `exit_score`
  - `watch_score`
  - `reason_codes`
  - `thresholds`
  - `trigger_version`

### 10.3 향후 분리 대상

장기적으로는 다음 분리가 필요하다.

- `deterministic_candidate_json`
- `ai_override_json`
- `final_decision_json`

하지만 V1은 일단 `decision_json` 내부 구조화로 시작한다.

---

## 11. observability 요구사항

운영과 분석을 위해 아래 집계가 가능해야 한다.

1. `primary_candidate` 분포
2. `source_type`별 candidate 분포
3. candidate → final decision 승격/기각 비율
4. `BUY_CANDIDATE` 대비 실제 submit 비율
5. `SELL/REDUCE_CANDIDATE` 대비 실제 order 생성 비율
6. WATCH → 후속 cycle에서 BUY/SELL 전환 비율

즉, trigger engine은 단순 helper가 아니라
**실험 단위**가 되어야 한다.

---

## 12. rollout 단계

## Phase 1

- 설계 문서 확정
- dataclass / pure helper 추가
- `AssembledContext` 연결
- prompt에 read-only 주입

## Phase 2

- `decision_json.deterministic_trigger` 저장
- candidate vs final decision 비교 로깅

## Phase 3

- WATCH 정책 조정
- held_position SELL/REDUCE deterministic 강화
- source_type별 threshold 분리

## Phase 4

- backtest / replay / attribution 연동
- config-driven threshold rollout

---

## 13. 테스트 전략

필수 테스트:

1. `bullish_trend + risk_on + allocation budget 있음` → `BUY_CANDIDATE`
2. `core + no_event + 중간 signal` → `WATCH`
3. `held_position + bearish_trend + concentration 높음` → `REDUCE_CANDIDATE`
4. `held_position + 강한 음수 signal` → `SELL_CANDIDATE`
5. `allocation budget 0` → BUY candidate 금지
6. `held_position`에서 BUY candidate 금지
7. `market_overlay`에서 WATCH/BUY threshold가 core보다 더 유연하게 동작

추가 테스트:

- prompt에 candidate 정보가 주입되는지
- subprocess serialization 경로 정합성
- decision_json 저장 경로 정합성

---

## 14. 이 설계가 해결하는 문제

이 설계는 현재의 대표 문제들을 직접 겨냥한다.

1. `WATCH가 거의 없다`
   - WATCH를 LLM의 우연한 선택이 아니라 deterministic candidate로 만든다.
2. `SELL이 왜 줄었는지 설명이 어렵다`
   - exit score / sell candidate 분포로 직접 설명 가능해진다.
3. `feature를 넣었지만 실제로 무엇이 바뀌었는지 모호하다`
   - feature가 prompt input에서 candidate 생성기로 승격된다.
4. `AI override가 유익했는지 측정이 어렵다`
   - candidate vs final decision 비교가 가능해진다.

---

## 15. 최종 결론

Deterministic Trigger Engine V1은
현재 시스템을 `AI가 feature를 참고해 판단하는 구조`에서
`deterministic backend가 alpha candidate를 만들고 AI는 policy judgment를 수행하는 구조`
로 한 단계 이동시키는 핵심 리팩토링이다.

이 작업은 단순한 기능 추가가 아니다.

- Signal Agent
- Strategy Selection
- Portfolio Agent
- WATCH/HOLD 정책
- held_position SELL 경로

를 하나의 `candidate generation` 관점으로 다시 묶는
구조 정리 작업이다.

따라서 다음 구현 우선순위는
이 문서를 기준으로
`deterministic_trigger_engine.py`와
`AssembledContext / decision_json / prompt projection` 연결을 1차 반영하는 것이다.
