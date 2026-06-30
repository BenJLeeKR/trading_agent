# 기대수익률 중심 보유기간 / Churn 제어 리팩토링 설계

> 작성일: 2026-06-23
>
> 목적:
> 현재 장중에 관측되는
> `reconciliation_overlay` 재진입,
> 동일 종목 단기 재매수/재매도,
> `1주` probe churn,
> `expected value` 비고정 상태를
> 하나의 상위 구조 문제로 보고,
> `최고 기대수익률` 목표에 맞는
> 진입-보유-축소 상태모델로 재설계한다.

## 1. 문제 요약

최근 운영 실측에서 다음 패턴이 확인됐다.

1. 같은 종목에서 `BUY -> REDUCE/SELL -> BUY -> REDUCE/SELL`이
   짧은 간격으로 반복된다.
2. `reconciliation_overlay` 경로가
   상태 확인/정합성 보조 경로를 넘어
   신규 `BUY approve`를 다시 만드는 사례가 존재한다.
3. 신규 진입과 위험축소가
   같은 종목에서 서로 다른 경로로 동시에 정당화된다.
4. 실제 제출된 주문은 `1주 시장가`가 반복되며,
   기대수익률보다 churn과 거래비용이 먼저 커진다.
5. `trade_decisions`에는 `expected_return_bps`,
   `net_expected_value_bps`,
   `final_trade_score`가 비어 있는 상태에서도
   일부 실행 판단이 흘러간다.

핵심 해석:

- 현재 시스템의 짧은 보유기간은
  `의도된 단기 전략의 결과`라기보다,
  `충돌하는 진입/축소 트리거`와
  `심볼 상태 기억 부재`의 결과일 가능성이 높다.
- 이는 `최고 기대수익률`과 직접 정렬되지 않는다.

---

## 2. 왜 현재 구조가 기대수익률 목표와 어긋나는가

기대수익률 최대화 관점에서 중요한 것은
`보유기간이 짧은가 긴가` 자체가 아니라,
`같은 가설을 거래비용을 감안한 뒤에도 충분히 밀어붙일 수 있는가`다.

현재는 아래 결손 때문에
좋은 가설을 충분히 보유하지 못하고,
약한 충돌 신호만으로 뒤집힐 수 있다.

1. `source_type`별 허용 행동 범위가 약하다.
2. 동일 종목의 직전 행동과 현재 행동 사이의
   `hysteresis`가 없다.
3. `after-cost expected value`가
   실제 submit의 강제 anchor가 아니다.
4. 보유 상태에 대한 `의도된 holding profile`이 없다.
5. `reconciliation_overlay`가
   상태 관리가 아니라 재진입 source로 오염될 수 있다.

즉, 지금 필요한 것은
threshold 몇 개를 조정하는 것이 아니라,
`심볼 단위 상태기계 + 기대값 anchor + 행동 envelope`
로 구조를 한 단계 올리는 일이다.

---

## 3. 설계 원칙

### 3.1 기대수익률 우선

- submit 가능한 판단은 반드시
  `after-cost net expected value`를 가져야 한다.
- 기대값이 비어 있거나 너무 낮으면
  `WATCH/HOLD`로 강등한다.

### 3.2 source_type는 행동 권한을 가진다

- `source_type`는 설명용 label이 아니라
  허용 가능한 action envelope를 결정해야 한다.

### 3.3 보유기간은 결과가 아니라 정책이어야 한다

- 종목별 진입 시점에
  `holding_profile`과 `minimum_hold_horizon`을 함께 기록한다.
- 이후 축소/재진입은 그 상태를 참조해야 한다.

### 3.4 동일 종목 반전 매매는 더 강한 증거가 필요하다

- 직전 `SELL/REDUCE` 후의 `BUY`,
  직전 `BUY` 후의 `REDUCE/SELL`은
  일반 진입/축소보다 더 높은 기준을 요구해야 한다.

### 3.5 정합성 경로와 알파 경로를 분리한다

- `reconciliation_overlay`는
  원칙적으로 `상태 관리/관찰` 경로다.
- 알파 진입 경로는
  `core`, `event_overlay`, 향후 `ranked_market_overlay`
  같은 명시적 source로 제한해야 한다.

---

## 4. 목표 구조

```text
Universe / Events / Held Position / Reconciliation
  -> Source Policy Layer
  -> Expected Value Derivation Layer
  -> Symbol Trade State Layer
  -> Candidate Projection
  -> AI Review
  -> Hard Guardrail / Sizing / Execution
```

핵심 추가 계층은 네 개다.

1. `Source Policy Layer`
2. `Expected Value Gate`
3. `Symbol Trade State Layer`
4. `Re-entry / Exit Hysteresis Gate`

---

## 5. Source Policy Layer

### 5.1 현재 문제

현재는 `reconciliation_overlay`가 deterministic trigger에서
일부 차단되더라도,
AI override나 후속 경로에서
`BUY approve`로 다시 살아날 수 있다.

### 5.2 목표 정책

`source_type`별 허용 action envelope를 명시한다.

#### `core`

- 허용:
  - `watch`
  - `approve buy`
  - 기존 보유 시 `hold`
- 금지:
  - flat 상태에서 `reduce/sell`

#### `event_overlay`

- 허용:
  - `watch`
  - `approve buy`
- 조건:
  - `expected value gate` 통과
  - `symbol state` 상 reverse cooldown 미해당

#### `reconciliation_overlay`

- flat 상태:
  - `watch`만 허용
  - 신규 `approve buy` 금지
- open/reconcile 상태:
  - `reconcile_manage`
  - `watch`
  - 필요 시 `hold`
- 기존 보유 상태:
  - 신규 진입 근거가 아니라
    기존 보유 상태 확인 보조 정보만 제공

즉,
`reconciliation_overlay`는
`알파 source`가 아니라
`상태 보조 source`로 내린다.

#### `held_position`

- 허용:
  - `hold`
  - `reduce`
  - `exit`
- 금지:
  - `buy`

### 5.3 구현 방향

- 신규 helper:
  - `services.source_policy.evaluate_action_envelope()`
- 출력:
  - `allowed_actions`
  - `blocked_actions`
  - `policy_reason_codes`

이 helper는
AI 호출 전 deterministic하게 적용해야 한다.

---

## 6. Expected Value Gate

### 6.1 현재 문제

- 일부 actionable decision에
  `expected_return_bps`, `net_expected_value_bps`,
  `final_trade_score`가 비어 있다.
- 이 상태에서는
  시스템이 실제로 기대값을 최적화하는지,
  아니면 서술형 rationale에 의존하는지 불명확해진다.

### 6.2 목표 정책

실행 가능한 판단은 아래 필드를 모두 가져야 한다.

- `expected_return_bps`
- `expected_downside_bps`
- `net_expected_value_bps`
- `final_trade_score`
- `minimum_required_edge_bps`

추가로 실제 제출 기준은
`after-cost net edge`를 사용한다.

예시:

```text
edge_after_cost_bps
  = net_expected_value_bps
    - estimated_round_trip_cost_bps
    - slippage_buffer_bps
```

### 6.3 강제 규칙

#### 신규 BUY

- `edge_after_cost_bps < minimum_required_edge_bps`
  -> `WATCH` 또는 `HOLD`

#### REDUCE / EXIT

- 단순 `risk_off`만으로는 부족
- 아래 중 하나가 필요
  - `downside risk increase`
  - `edge collapse`
  - `thesis invalidation`
  - `holding_profile risk breach`

즉,
`고변동성 + 리스크오프`만으로
보유 직후 바로 `REDUCE`가 나오는 구조를 줄여야 한다.

### 6.4 구현 방향

- 신규 helper:
  - `services.expected_value_gate.evaluate_expected_value_gate()`
- 저장 필드 추가:
  - `edge_after_cost_bps`
  - `estimated_round_trip_cost_bps`
  - `slippage_buffer_bps`
  - `expected_value_gate_passed`
  - `expected_value_gate_reason_codes`

---

## 7. Holding Profile / 보유기간 정책

### 7.1 현재 문제

현재는 종목을 살 때
`얼마나 들고 갈 전략인지`
명시적으로 기록하지 않는다.

결과:

- 진입 직후 `held_position` 경로가
  동일 종목을 짧게 `REDUCE`할 수 있다.
- 단기 probe와 swing 진입이 구분되지 않는다.

### 7.2 목표 정책

진입 시점에 `holding_profile`을 확정한다.

예시 profile:

- `event_probe`
- `event_swing`
- `core_swing`
- `position_trade`
- `risk_reduction_only`

### 7.3 profile별 정책 예시

#### `event_probe`

- 매우 제한적으로만 허용
- 최소 주문가치, 최소 edge를 높게 요구
- 빠른 exit 허용

#### `event_swing`

- 기본 권장 profile
- `minimum_hold_minutes` 존재
- 진입 직후 reverse sell은 강화된 조건 필요

#### `core_swing`

- `core` 종목 기본 진입
- 단기 `risk_off`만으로 즉시 뒤집지 않음
- `edge collapse` 또는 `thesis invalidation` 요구

### 7.4 구현 방향

- `trade_decisions` 또는 별도 state에 저장:
  - `holding_profile`
  - `minimum_hold_until`
  - `earliest_reduce_at`
  - `earliest_reentry_at`

---

## 8. Symbol Trade State Layer

### 8.1 현재 문제

동일 종목에 대해
직전 `BUY`, `SELL`, `REDUCE`,
현재 보유 수량, 마지막 thesis를
한곳에서 authoritative하게 보지 못한다.

### 8.2 목표 상태기계

```text
FLAT
 -> ENTRY_PENDING
 -> HELD_ACTIVE
 -> REDUCE_PENDING
 -> FLAT_COOLDOWN
```

부가 상태:

- `last_entry_at`
- `last_exit_at`
- `last_reduce_at`
- `last_entry_source_type`
- `last_exit_reason_codes`
- `holding_profile`
- `reentry_cooldown_until`
- `sell_cooldown_until`
- `thesis_state_hash`

### 8.3 핵심 규칙

#### BUY 직후 SELL/REDUCE

아래 중 하나가 아니면 차단:

- `hard guardrail`
- `unexpected downside shock`
- `thesis invalidation`
- `stop loss / max adverse excursion breach`

#### SELL/REDUCE 직후 BUY

아래를 모두 요구:

- `reentry_cooldown` 경과
- `feature anchor` 변화 또는 신규 강한 이벤트
- `edge_after_cost_bps` 재상승
- `source_type != reconciliation_overlay`

### 8.4 구현 방향

신규 테이블 권장:

- `trading.symbol_trade_states`

필수 컬럼 예시:

- `account_id`
- `instrument_id`
- `symbol`
- `market`
- `state`
- `holding_profile`
- `position_quantity`
- `last_entry_order_request_id`
- `last_exit_order_request_id`
- `last_entry_at`
- `last_reduce_at`
- `last_exit_at`
- `reentry_cooldown_until`
- `sell_cooldown_until`
- `last_signal_feature_snapshot_id`
- `last_decision_context_id`
- `last_reason_codes`
- `metadata_json`

이 테이블은
`보유 상태`, `최근 행동`, `cooldown`을
결정 계층에서 빠르게 읽는
authoritative state cache 역할을 한다.

---

## 9. Re-entry Cooldown / Hysteresis

### 9.1 단순 cooldown만으로는 부족하다

시간만 막아서는 안 된다.
같은 종목을 다시 살 수 있으려면
상태 변화가 확인돼야 한다.

### 9.2 재진입 조건

`SELL/REDUCE -> BUY` 재진입은
다음 4개를 같이 본다.

1. 시간:
   - `reentry_cooldown_until` 경과
2. 정보 변화:
   - `signal_feature_snapshot_id` 변경
   - 또는 `event novelty score` 상승
3. 가격/유동성 변화:
   - `turnover_surge_ratio` 개선
   - `below_sma20` 해소 또는 momentum 회복
4. 기대값 변화:
   - `edge_after_cost_bps`가
     직전 exit 시점보다 충분히 개선

### 9.3 역방향 hysteresis

`BUY -> REDUCE/SELL`도 동일하게
강한 조건이 필요하다.

즉,
진입 기준과 청산 기준은
같은 문턱이 아니라
서로 다른 문턱이어야 한다.

권장 예시:

- 진입:
  - `edge_after_cost_bps >= 35`
- 축소:
  - `edge_after_cost_bps <= 5`
  - 또는 thesis invalidation

이렇게 해야
약한 노이즈 구간에서
왕복 churn이 줄어든다.

---

## 10. 1주 Probe Churn 차단

### 10.1 현재 문제

`1주` 주문 자체가 항상 나쁜 것은 아니지만,
현재는 다음 조합에서 churn을 만든다.

- `source_type=reconciliation_overlay`
- `market` order
- `quantity=1`
- `high_volatility`
- `risk_off`
- `same-symbol reverse shortly after`

### 10.2 목표 정책

신규 BUY에 대해
`1주 허용`을 일반 규칙이 아니라 예외 규칙으로 바꾼다.

#### 기본 규칙

- `quantity == 1` 이고
  `max_order_value < min_probe_order_value`
  -> submit 금지

#### 예외 허용

- 고가주라서 1주가
  이미 충분한 주문가치인 경우
- `core` 또는 `event_overlay`의
  `edge_after_cost_bps`가 매우 높은 경우

#### 금지 조합

- `reconciliation_overlay + BUY + quantity=1`
- `high_volatility + risk_off + quantity=1 + market`

### 10.3 구현 방향

- `sizing_engine` 자체의 최소 1주 보정은 유지하더라도,
  최종 submit 전
  `execution_probe_churn_guard`에서 막는다.

신규 rule code 예시:

- `probe_churn_single_share_blocked`
- `overlay_single_share_buy_blocked`
- `reverse_trade_single_share_blocked`

---

## 11. AI 역할 재정의

### 11.1 현재 문제

현재는 deterministic trigger가 `WATCH` 또는 `NO_ACTION`이어도
AI가 이를 `BUY approve`로 뒤집을 수 있다.

이것이 항상 나쁜 것은 아니지만,
`execution infeasible` 또는 `state conflict` 상황까지
같이 승격되면 안 된다.

### 11.2 목표 정책

AI는 아래 범위에서만 override 가능해야 한다.

#### 허용

- `eligibility_passed = true`
- `expected_value_gate_passed = true`
- `action_envelope`가 BUY 허용
- `symbol state`가 reverse cooldown 비해당

#### 금지

- `reconciliation_overlay flat buy`
- `expected value fields missing`
- `execution infeasible`
- `reverse cooldown active`

즉,
AI는 `candidate ranking 조정자`이지
`상태기계 위반 허가자`가 아니어야 한다.

---

## 12. 리팩토링 경계

### 12.1 신규 서비스 권장

- `services.source_policy`
- `services.expected_value_gate`
- `services.symbol_trade_state`
- `services.reverse_trade_hysteresis`
- `services.execution_probe_churn_guard`

### 12.2 기존 서비스 책임 축소

#### `decision_orchestrator.py`

현재보다 줄여야 하는 책임:

- source_type별 action 허용 판정
- reverse cooldown 판정
- expected value 강제 여부 판단

위 책임은 전용 service로 빼고,
orchestrator는 조립자로 남기는 편이 맞다.

#### `deterministic_trigger_engine.py`

추가해야 할 책임:

- `candidate`뿐 아니라
  `holding_profile proposal`
  `reentry risk flags`
  `reverse_trade_penalty`

#### `execution_service.py`

추가해야 할 책임:

- 마지막 submit 직전
  `probe churn guard`
  `state conflict guard`
  적용

---

## 13. 단계별 적용 순서

### Phase 1

- `reconciliation_overlay flat BUY 금지`
- `expected value fields missing -> submit 금지`
- `quantity=1 probe churn guard`
- `same-symbol reentry cooldown` 1차

### Phase 2

- `symbol_trade_states` 테이블 도입
- `holding_profile` / `minimum_hold_until` 도입
- `BUY -> SELL`, `SELL -> BUY` hysteresis 분리

### Phase 3

- `edge_after_cost_bps` 정식 계산
- `reverse trade attribution`
- `holding_profile`별 성과 비교

---

## 14. 우선 구현 체크리스트

- [x] `reconciliation_overlay`의 flat 상태 신규 `BUY approve`를 deterministic layer에서 전면 차단
- [x] `source_type`별 `action_envelope` helper 추가
- [x] actionable decision에 `expected_return_bps`, `net_expected_value_bps`, `final_trade_score` 비어 있으면 submit 금지
- [x] `edge_after_cost_bps` 계산 필드 추가
- [x] `same-symbol reentry cooldown` 1차 추가
- [x] `BUY 직후 SELL/REDUCE cooldown` 1차 추가
- [x] `signal_feature_snapshot_id` 변경 없는 reverse trade 차단
- [x] `quantity=1` 신규 BUY의 `probe churn guard` 추가
- [x] `symbol_trade_states` 테이블 설계 및 migration 추가
- [x] `holding_profile`, `minimum_hold_until`, `reentry_cooldown_until` 저장 경로 추가
- [x] AI override 허용 범위를 `eligibility + expected value + state` 통과 시로 축소

---

## 14-A. 현재 기준 남은 후속 범위

현재까지는 `Phase 1`과 `Phase 2`의 1차 골격이 대부분 닫혔다.
하지만 아래 항목들은 아직 남아 있으며,
`11-c`를 `완료`로 보려면 이 범위를 추가로 닫아야 한다.

### 1. holding_profile 정책의 authoritative 집행

아직 `holding_profile`은 저장과 일부 cooldown 계산 중심이다.
다음이 추가로 필요하다.

- `earliest_reduce_at`
- `earliest_reentry_at`
- `holding_profile breach`

즉,
`decision_json.holding_profile_policy`와
`symbol_trade_states`에 기록된 값이
설명용 메타데이터가 아니라
실제 pre-AI / pre-submit 차단 규칙으로 동작해야 한다.

현재 기준 1차 authoritative 집행은 완료했다.

- `holding_profile_policy`에
  `earliest_reduce_at`, `earliest_reentry_at` 추가
- `decision_json.holding_profile_policy` 직렬화 반영
- `symbol_trade_states.metadata_json.holding_profile_policy`를
  authoritative source로 사용
- `pre_ai_gate`에서
  `holding_profile_earliest_reduce_guard`,
  `holding_profile_earliest_reentry_guard`
  차단 반영
- submit 직전 `compliance_validator`에서도
  같은 시간창 차단을 재검증하도록 연결

즉, 이제
`minimum_hold_until` / `reentry_cooldown_until`은
설명용 보조값이 아니라,
`earliest_*` 명시 필드와 함께
실차단 규칙으로 승격되었다.

### 2. reverse trade hysteresis의 2차 승격

현재는 다음이 1차 구현 상태다.

- 시간 기반 cooldown
- `signal_feature_snapshot_id` 불변 차단

하지만 최종 구조로는 부족하다.
추가로 아래 3축을 동시에 봐야 한다.

- `signal_feature_snapshot_id` 변화
- `event novelty` 또는 신규 강한 이벤트
- `edge_after_cost_bps` 개선

즉, `SELL/REDUCE -> BUY` 재진입은
단순 시간 경과가 아니라
정보 변화와 기대값 개선이 같이 확인되어야 한다.

현재 기준 2차 승격의 1차 구현은 완료했다.

- `pre_ai_gate`
  - same-snapshot 재진입은 즉시 차단
  - 다만 최근 신규 진입 이벤트 novelty가 있으면
    단순 cooldown만으로는 막지 않고
    AI 단계까지 진행 허용
- `DecisionOrchestratorService.ai_override_gate`
  - `signal_feature_snapshot_id 변화`
  - `event novelty`
  - `edge_after_cost_bps` 개선
  세 축을 모두 통과해야
  `WATCH/HOLD`에서 `BUY/APPROVE`로 재진입 승격 허용
- `symbol_trade_states.metadata_json`
  - 직전 `SELL/REDUCE/EXIT` 시점의
    `edge_after_cost_bps` 저장
  - 이후 재진입 시
    `current_edge_after_cost_bps`와 비교 가능하게 정리

아직 남은 것은
이 3축 판정을 inspection / attribution에 직접 노출하고,
실측 리포트로 churn 감소와 기대수익률 개선을 확인하는 단계다.

### 3. 비대칭 exit hysteresis 강화

현재는 조기 SELL/REDUCE 차단의 1차 cooldown은 들어갔지만,
축소/청산 문턱 자체가 완전히 비대칭으로 재정의되진 않았다.

최종적으로는 아래 중 하나가 필요해야 한다.

- `thesis invalidation`
- `edge collapse`
- `unexpected downside shock`
- `holding_profile risk breach`

즉,
단순 `risk_off` 또는 약한 노이즈만으로
진입 직후 바로 뒤집는 구조를 더 줄여야 한다.

현재 기준 1차 비대칭 exit hysteresis 구현은 완료했다.

- 적용 범위:
  - `held_position`
  - `earliest_reduce_at` 창이 아직 살아있는 조기 `REDUCE / EXIT`
- 허용 조건:
  - `edge collapse`
  - `unexpected downside shock`
  - `thesis invalidation`
  - `holding_profile breach`
- 구현 위치:
  - `services.reverse_trade_hysteresis.evaluate_symbol_state_sell_hysteresis()`
  - `DecisionOrchestratorService._check_held_position_exit_hysteresis_gate()`

즉, 이제 조기 축소/청산은
`risk_off` 단독이나 약한 잡음으로는 열리지 않고,
위의 강한 exit 근거 중 하나가 있어야만 통과한다.

아직 남은 것은
이 판단 결과를 inspection / attribution에 노출하고,
exit 시점의 expected value anchor를 더 직접 비교하는 단계다.

### 4. symbol_trade_states 상태기계 완성

현재 테이블/저장 경로는 들어갔지만,
상태기계 전이가 완결된 것은 아니다.

목표 상태는 아래와 같다.

```text
FLAT
 -> ENTRY_PENDING
 -> HELD_ACTIVE
 -> REDUCE_PENDING
 -> FLAT_COOLDOWN
```

추가로 아래를 authoritative하게 연결해야 한다.

- 주문 생성
- 주문 체결
- 부분 체결
- cancel / expire
- reconciliation 결과

즉, `symbol_trade_states`는
단순 최신 메타 캐시가 아니라
심볼 단위 행동 제약의 authoritative 상태여야 한다.

### 5. 전용 reverse_trade_hysteresis service 분리

현재 reverse 판단은
`pre_ai_gate`, `execution_service`, `DecisionOrchestratorService`에
나뉘어 있다.

다음 단계에서는 전용 service로 수렴해야 한다.

- `services.reverse_trade_hysteresis`

이 service는 최소한 아래 입력을 받아야 한다.

- current source type
- current signal feature anchor
- last action / last state
- cooldown window
- event novelty
- expected value delta

현재 기준 1차 구현은 완료했다.

- `services.reverse_trade_hysteresis` 추가
- `pre_ai_gate`의
  `held_position_recent_buy_sell_cooldown`,
  `held_position_recent_risk_sell_cooldown`,
  `same_symbol_reentry_cooldown`,
  `reverse_trade_same_signal_feature_snapshot`
  판단 수렴
- `DecisionOrchestratorService`의
  `ai_override_reverse_cooldown_blocked`
  경로를 같은 contract로 연결
- `ExecutionService`의
  `reverse_trade_single_share_blocked`
  경로도 같은 contract로 연결

다만 이것은 `contract 수렴` 단계다.
`event novelty + edge_after_cost_bps 개선`을 포함한
3축 hysteresis 승격은
여전히 별도 후속 범위로 남아 있다.

### 6. expected value anchor의 exit 경로 확장

현재는 신규 BUY 쪽 anchor 강제가 더 강하다.
다음 단계에서는 `REDUCE / EXIT`에도
`after-cost expected value` 논리가 더 직접 연결되어야 한다.

예를 들면 다음을 비교해야 한다.

- 직전 entry 시점 edge
- 직전 exit / reduce 시점 edge
- 현재 edge_after_cost_bps

즉, 청산도 단순 위험감소가 아니라
기대값 악화의 수치적 근거를 가져야 한다.

구현 기준으로는 다음이 반영되었다.

- `SubmitOrderRequest.metadata.expected_value_anchor`에
  현재 edge,
  직전 entry / reduce / exit edge,
  각 delta를 함께 저장
- `decision_factory`가 동일 payload를
  `decision_json.expected_value_anchor`에 보존
- `symbol_trade_states.metadata_json`에도
  최신 anchor와 직전 exit/reduce edge를 함께 축적
- submit translation은
  `SELL / EXIT / REDUCE` 경로에서
  `expected_value_anchor.anchor_passed=false`이면
  실제 주문 request를 만들지 않음

### 7. inspection / attribution / 운영 관측 확장

현재는 차단 자체는 많이 남기지만,
운영자가 `왜 churn이 줄었는지 / 왜 다시 진입을 막았는지`를
한 번에 보기 어렵다.

추가로 필요한 관측 항목:

- `holding_profile`
- `reverse_trade_hysteresis` 판단 결과
- `probe churn guard` 차단 결과
- `edge_after_cost_bps` 비교값
- `last_signal_feature_snapshot_id` 대비 변화 여부

이 정보는
inspection API / 운영 대시보드 / attribution 리포트에서
직접 노출되어야 한다.

현행 구현 기준으로는 다음이 반영되었다.

- `GET /trade-decisions`에
  `decision_inspection` view를 추가해
  `holding_profile`,
  `expected_value_anchor`,
  `reverse_trade`,
  `probe_churn`,
  `guardrail_attribution`
  을 한 payload에서 바로 읽을 수 있게 했다.
- 운영 대시보드의
  `Universe Selection / Market Overlay`
  freeze 표는
  오늘자 `trade-decisions`를 함께 조회해
  종목별 `최근 판단`,
  `holding profile`,
  `차단/가드레일 사유`
  를 나란히 보여주도록 확장했다.

### 8. 성과 검증 리포트

`11-c`가 완료되었다고 판단하려면
단지 guard를 추가하는 것만으로는 부족하다.
실제로 아래가 줄거나 개선됐는지 비교가 필요하다.

- same-symbol reverse trade 횟수
- `BUY -> SELL/REDUCE -> BUY` churn 빈도
- `quantity=1` probe 발생 빈도
- holding profile별 평균 보유기간
- holding profile별 기대값 대비 실현성과

즉, 최종 완료 기준에는
`churn 차단이 실제 성과 개선으로 이어졌는지`를 보는
attribution 단계가 포함되어야 한다.

---

## 15. 결론

현재 문제의 본질은
`짧은 보유기간` 자체가 아니라,
`같은 종목을 어떤 기대값 가설로 얼마나 보유할지`
시스템이 기억하지 못한 채
서로 다른 source가 번갈아 행동을 만들고 있다는 점이다.

따라서 다음 단계는

- `source_type별 행동 권한`
- `심볼 상태기계`
- `expected value 강제 anchor`
- `reverse trade hysteresis`

를 중심으로
진입-보유-축소를 하나의 구조로 묶는 리팩토링이어야 한다.

이 방향이
현재의 단기 churn을 줄이면서도,
실제로 기대값이 높은 종목은 더 오래, 더 일관되게 보유하게 만드는
가장 직접적인 개선축이다.
