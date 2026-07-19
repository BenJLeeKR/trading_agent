# AR / Sizing / Guardrail / Compliance 역할 경계

기준 코드:

- `src/agent_trading/services/ai_agents/ai_risk.py`
- `src/agent_trading/services/sizing_engine.py`
- `src/agent_trading/services/decision_orchestrator.py`
- `src/agent_trading/domain/entities.py`
- `src/agent_trading/domain/enums.py`

기준 문서:

- `plan_docs/detailed_design/01_system_architecture.md`
- `plan_docs/detailed_design/06_config_schema.md`
- `plan_docs/detailed_design/08_ai_decision_policy.md`

## 한 줄 원칙

- `AI Risk Agent`는 **리스크 해석기**다.
- `Sizing Engine`은 **결정적 수량 계산기**다.
- `Hard Guardrail`은 **최종 강제 차단기**다.
- `AI Compliance Agent`는 향후 **정책/규정 해석기**가 될 수 있지만,
  실제 금지/허용의 authoritative 집행은 결국 deterministic validator가 맡아야 한다.

즉, 현재 시스템은 **AI가 의견을 내고, deterministic backend가 강제 집행하는 구조**를 따른다.

---

## 1. 역할 경계 요약

| 계층 | 현재 구현 상태 | 주 역할 | 하면 안 되는 일 |
|---|---|---|---|
| `AI Risk Agent (AR)` | Implemented | 이벤트/포지션/현금/노출 상태를 보고 `allow/reduce/reject/review` 의견과 size adjustment를 제안 | authoritative 한도 집행, broker submit 차단의 최종 소유 |
| `Sizing Engine` | Implemented | AI 의견 + config + snapshot을 받아 최종 수량을 결정적으로 계산 | 정책/규정의 애매한 의미 해석, AI 판단 대체 |
| `Hard Guardrail` | Partially Implemented | stale snapshot, blocked reason, kill switch, risk check 등 후단 차단/기록 | 확률적/서술형 판단 |
| `AI Compliance Agent` | Planned | 규정/정책/금지조건의 해석 보조 | 최종 금지 집행을 AI 단독으로 수행 |

---

## 2. AR이 현재 실제로 보는 Fact

현재 `AIRiskAgent`는 `AgentExecutionRequest.context`를 통해 아래 사실을 입력으로 받는다.

### 2.1 이벤트 해석 결과

`EventInterpretationAgent`의 structured output:

- `overall_bias`
- `event_conflict`
- `top_reason_codes`
- 개별 interpreted event 요약
  - impact direction
  - confidence
  - supports entry/exit
  - risk flags

즉 AR은 raw event만 보지 않고, EI가 먼저 구조화한 의미를 함께 본다.

### 2.2 스코어와 사유 코드

- score
- threshold
- `reason_codes`

즉 “왜 이 주문 후보가 올라왔는가”를 risk 관점에서 다시 읽는다.

### 2.3 현재 포지션 상태

- 보유 수량
- 평균 단가
- 시장가
- 평가손익

### 2.4 현금 상태

- available cash
- settled cash
- unsettled cash
- currency

### 2.5 리스크 제한 스냅샷

`risk_limit_snapshot`에서 이미 계산된 fact를 받는다.

- `kill_switch_active`
- `drawdown_state`
- `blocked_reason_codes`
- `daily_loss_used_pct`
- `max_daily_loss_limit_pct`
- `gross_exposure_pct`
- `net_exposure_pct`

중요한 점은, AR이 이 값을 원천 계산하는 구조가 아니라는 것이다.
AR은 **upstream deterministic 계층이 계산/집계한 리스크 상태를 읽고 해석**한다.

### 2.6 최근 raw external events

EI output 외에도 recent external events 목록을 함께 받는다.

---

## 3. AR이 현재 실제로 내리는 판단

AR 출력은 `AIRiskOutput`이며 핵심 필드는 아래와 같다.

- `risk_opinion`
  - `allow`
  - `reduce`
  - `reject`
  - `review`
- `risk_score`
- `confidence`
- `size_adjustment_factor`
- `max_holding_horizon`
- `risk_flags`
- `reason_codes`
- `summary`

현재 backend는 이 결과를 정규화해서 downstream으로 넘긴다.

실무 해석:

- `allow`: 진행 가능
- `reduce`: 진행은 가능하되 보수적으로 줄일 것
- `reject`: 리스크상 거절 의견
- `review`: 자동집행보다 사람/후단 재확인 필요

이 결과는 **authoritative 집행 결과가 아니라 리스크 의견**이다.

---

## 4. Sizing Engine의 현재 책임

`sizing_engine.py`는 AI가 준 의견과 request를 그대로 집행하지 않고, 아래 제약으로 최종 수량을 결정론적으로 계산한다.

### 4.1 입력

- `decision_type`
- `side`
- `requested_quantity`
- `requested_price`
- AI `sizing_hint`
- current position
- available cash
- NAV
- config-derived limits

### 4.2 현재 적용되는 하드 제약

- `max_single_position_pct`
- `min_cash_buffer_pct`
- `max_order_value`
- `min_order_qty`
- `max_order_qty`
- `lot_size`

즉 포지션 비중이나 최대 주문금액 같은 것은 **AR이 최종 집행하지 않고 Sizing Engine이 결정적으로 적용**한다.

문서상 원칙도 동일하다:

- AI sizing hint는 advisory only
- hard config limit가 항상 우선한다

---

## 5. Hard Guardrail의 현재 책임

현재 hard guardrail은 전용 단일 엔진으로 완결되어 있지는 않지만,
`DecisionOrchestratorService` 후단에 authoritative 차단/기록 책임이 일부 구현되어 있다.

대표 예:

- stale snapshot guard
- account snapshot freshness check
- `blocked_reason_codes`
- `kill_switch_active`
- `risk_check_passed`
- `GuardrailEvaluationEntity` 기록

즉 현재 시스템은 이미 다음 철학을 따른다.

- AI가 “위험해 보인다”고 말할 수는 있다
- 하지만 최종적으로 “여기서 멈춘다 / 기록한다 / 제출하지 않는다”는 결정은 deterministic path가 담당한다

---

## 6. VaR / 포지션 한도 / 노출 한도는 어디에 두는 것이 맞는가

## 6.1 결론

**Authoritative enforcement는 AR도 Compliance도 아니라 deterministic layer가 맡는 것이 맞다.**

### 이유

VaR 한도, 총 익스포저 한도, 순익스포저 한도, 최대 포지션 비중, 일손실 한도는:

- 재현 가능해야 하고
- 감사 가능해야 하고
- 동일 입력에 동일 결과를 내야 하며
- model drift에 영향을 받으면 안 된다

따라서 이 영역은 AI가 소유하면 안 된다.

## 6.2 AR의 역할

AR은 이런 해석을 하는 것은 적절하다.

- “gross exposure가 높아 신규 진입 리스크가 커 보인다”
- “drawdown 상태와 이벤트 불확실성을 함께 보면 reduce가 맞다”
- “현금은 있지만 포지션 집중도가 과도하다”

즉 **경제적 리스크 해석과 완충적 의견**은 AR이 담당할 수 있다.

## 6.3 Compliance의 역할

향후 `AI Compliance Agent`가 생긴다면 더 자연스러운 책임은 아래다.

- restricted / blocked asset 해석 보조
- 내부 정책상 애매한 허용/비허용 상황 정리
- 계좌/시장/세션 규칙의 설명형 판단
- 규정 위반 가능성에 대한 서술형 의견

즉 **정책/규정 해석**은 Compliance 쪽이 더 가깝다.

## 6.4 Deterministic validator의 역할

다음은 AI가 아니라 deterministic validator/guardrail이 authoritative하게 집행해야 한다.

- VaR 한도 초과
- max single position pct 초과
- max gross exposure pct 초과
- max net exposure pct 초과
- daily loss limit 초과
- kill switch active
- blocked reason codes 존재
- 금지 시장/금지 자산/권한 없는 거래

---

## 7. 현재 코드 기준 책임 배치

| 항목 | 지금 어디에 가까운가 | 장기적으로 어디에 있어야 하나 |
|---|---|---|
| 이벤트/시장 리스크 해석 | `AI Risk Agent` | `AI Risk Agent` |
| 포지션/현금 상태를 반영한 보수적 의견 | `AI Risk Agent` | `AI Risk Agent` |
| 사이즈 감액 권고 | `AI Risk Agent` + `SizingHint` | `AI Risk Agent` |
| 최종 수량 계산 | `Sizing Engine` | `Sizing Engine` |
| 최대 포지션 비중 강제 | `Sizing Engine` | `Sizing Engine` 또는 전용 deterministic risk engine |
| max order value 강제 | `Sizing Engine` | `Sizing Engine` |
| stale snapshot 차단 | orchestrator guard | dedicated hard guardrail layer |
| kill switch / blocked reason authoritative 차단 | risk snapshot + guardrail recording | dedicated hard guardrail / compliance validator |
| 규정 위반 가능성 설명 | 미구현 | `AI Compliance Agent` |
| 규정 위반 authoritative 차단 | 미구현/부분구현 | deterministic compliance validator |

---

## 8. 현재 코드에서 아직 비어 있는 부분

현재 시스템은 아래 영역이 완전히 닫혀 있지 않다.

1. **전용 deterministic VaR 엔진**
   - 현재 `risk_limit_snapshot` fact는 있지만, VaR 계산기 자체가 AR 내부에 있는 것은 아니다.
   - 향후에도 AR 안에 넣기보다 deterministic service로 두는 것이 맞다.

2. **전용 AI Compliance Agent**
   - 설계에는 있으나 아직 런타임 구현이 없다.

3. **hard guardrail 일원화**
   - 지금은 orchestrator / sizing / snapshot freshness / risk snapshot 기반 차단이 분산되어 있다.
   - 장기적으로는 더 명시적인 hard guardrail / compliance validator 계층으로 정리하는 것이 바람직하다.

---

## 9. 최종 원칙

현재 코드 기준으로 가장 안전한 역할 경계는 아래와 같다.

- `AR`
  - 리스크를 **해석**한다
  - 사이즈 감액/보수화 의견을 낸다
  - 하지만 최종 한도 집행을 소유하지 않는다

- `Sizing`
  - config와 snapshot을 기반으로 **최종 수량을 결정론적으로 계산**한다
  - 포지션 비중, cash buffer, max order value 같은 hard numeric rule을 적용한다

- `Hard Guardrail`
  - stale snapshot, blocked reason, kill switch, risk check 등 **주문 차단의 최종 책임**을 진다

- `Compliance Agent`
  - 향후 규정/정책 해석 보조로 추가할 수 있다
  - 그러나 실제 허용/금지 집행은 deterministic validator가 맡아야 한다

따라서 “VaR 한도나 포지션 한도는 AR이 하는 것이 맞나, Compliance가 하는 것이 맞나?”에 대한 현재 코드 기준 답은:

> **해석은 AR/Compliance가 도울 수 있지만, authoritative enforcement는 둘 다 아니고 deterministic backend가 맡는 것이 맞다.**
