# VaR 엔진 / AI Compliance / Guardrail 일원화 구현 경로 분석

## 1. 목적

현재 설계에는 존재하지만 아직 전용 구현체가 없거나 분산 구현 상태인 아래 3개 축을
어떤 순서와 형태로 진행하는 것이 맞는지 정리한다.

1. 전용 deterministic VaR 엔진
2. AI Compliance Agent
3. Hard Guardrail / Compliance Validator 일원화

이 문서는 새 기능을 바로 추가하는 설계서라기보다,
**현재 코드와 설계의 간극을 메우기 위한 구현 순서와 책임 분리 원칙**을 정리하는 분석 문서다.

---

## 2. 현재 상태 요약

기준 문서:

- `plan_docs/agents/01_agent_inventory_and_status.md`
- `plan_docs/agents/03_risk_role_boundaries.md`
- `plan_docs/detailed_design/01_system_architecture.md`
- `plan_docs/detailed_design/08_ai_decision_policy.md`

기준 코드:

- `src/agent_trading/services/ai_agents/ai_risk.py`
- `src/agent_trading/services/decision_factory.py`
- `src/agent_trading/services/decision_orchestrator.py`
- `src/agent_trading/services/execution_service.py`
- `src/agent_trading/services/guardrail_audit.py`
- `src/agent_trading/brokers/koreainvestment/snapshot.py`

### 2.1 현재 이미 있는 것

- `AI Risk Agent`는 실제 런타임에 연결되어 있다.
- `risk_limit_snapshot` 저장 경로가 있다.
- `kill_switch_active`, `blocked_reason_codes`, `gross/net exposure`, `daily_loss_used_pct` 같은
  deterministic risk fact 일부가 이미 존재한다.
- guardrail 차단 결과를 `guardrail_evaluations`에 저장하는 경로가 있다.
- stale snapshot, sell guard, duplicate buy guard, low-liquidity execution block 등
  실전 방어 로직이 이미 존재한다.

### 2.2 현재 없는 것

- VaR를 독립적으로 계산하고, 그 값을 authoritative risk fact로 저장하는 전용 엔진
- `AI Compliance Agent` 전용 구현체와 런타임 연결
- 분산된 차단 로직을 단일 규칙 집합으로 평가하는 통합 validator 계층

### 2.3 핵심 문제

현재 구조는 "기능이 없다"기보다,

- 리스크 fact 계산은 일부 있으나 VaR가 비어 있고
- compliance는 설계만 있고
- hard guardrail은 여러 지점에 흩어져 있다

는 상태다.

즉 지금 필요한 것은 단순 기능 추가가 아니라,
**결정적 계산 계층과 해석 계층의 경계를 더 명시적으로 닫는 작업**이다.

---

## 3. 세 항목의 올바른 책임 배치

## 3.1 VaR 엔진

VaR는 AI가 계산하면 안 된다.

이유:

- 동일 입력에 동일 출력이 나와야 한다.
- replay / audit / 사후 설명이 가능해야 한다.
- threshold 초과 여부를 hard rule로 집행할 수 있어야 한다.

따라서 VaR는
`AI Risk Agent` 내부가 아니라 **전용 deterministic risk engine**이 계산해야 한다.

권장 책임:

- 입력
  - 최신 `position_snapshot`
  - `cash_balance_snapshot`
  - 현재 open order exposure
  - instrument/segment/membership 정보
  - 변동성 산출용 feature 또는 market data snapshot
- 출력
  - account-level VaR
  - symbol-level marginal VaR
  - stress loss proxy
  - concentration-adjusted exposure
  - threshold breach 여부
- 저장
  - 기존 `risk_limit_snapshot` 확장 또는 전용 `risk_analytics_snapshot` 계층

## 3.2 AI Compliance Agent

AI Compliance Agent는 **최종 차단기**가 아니라
정책/규정/이벤트 맥락의 **해석기**로 두는 것이 맞다.

권장 책임:

- ambiguous policy risk 설명
- 규정/정책 위반 가능성 요약
- 특수 상황에서의 보수적 의견
- human-readable compliance rationale 생성

하면 안 되는 일:

- 필수 필드 누락을 AI가 최종 허용/거부
- 브로커 미지원 주문을 AI가 임의 허용
- 금지 시장/금지 자산/권한 불일치를 AI가 최종 집행

즉 구조는 아래가 맞다.

- deterministic compliance validator
  - 명확한 금지/허용 집행
- AI Compliance Agent
  - 애매한 정책/규정/이벤트 해석 보조

## 3.3 Hard Guardrail / Validator

장기적으로는 `ExecutionService`와 `DecisionOrchestrator` 주변에 흩어진 차단 로직을
하나의 **통합 Validator 계층**으로 모으는 것이 맞다.

단, 이 통합은 "모든 코드를 한 파일로 모은다"가 아니라
아래처럼 구조화하는 방향이어야 한다.

- `Decision Validator`
  - decision context 기준 차단
- `Risk Validator`
  - VaR, exposure, daily loss, kill switch
- `Compliance Validator`
  - 금지 시장, 금지 자산, 브로커 capability, 권한, 세션 규칙
- `Execution Validator`
  - duplicate buy/sell, low-liquidity block, stale snapshot, reconciliation lock

즉 "통합 방어벽"은 단일 거대 함수가 아니라
**규칙 모듈들의 평가 체계 + 공통 결과 모델**이어야 한다.

---

## 4. 무엇부터 해야 하는가

## 4.1 권장 순서

권장 구현 순서는 아래다.

1. Guardrail / Validator 일원화
2. 전용 VaR 엔진 추가
3. deterministic compliance validator 명시화
4. AI Compliance Agent 연결

### 왜 이 순서가 맞는가

#### 1단계로 Guardrail 일원화가 먼저인 이유

현재 차단 로직이 분산된 상태에서 VaR 엔진이나 AI Compliance를 먼저 붙이면,
새 fact와 새 의견이 또 다른 우회 경로를 만들 가능성이 높다.

먼저 해야 할 일은:

- 차단 지점 inventory 정리
- 공통 `ValidationResult` 모델 정리
- rule_set_version / failed_rule_codes / blocking_rule_codes 표준화
- guardrail 평가와 기록 경로 일원화

즉 **새 판단을 넣기 전에, 어디서 authoritative 차단이 일어나는지부터 고정**해야 한다.

#### 2단계로 VaR 엔진이 그 다음인 이유

VaR는 AI Risk와 Compliance 양쪽이 모두 참조할 수 있는
upstream deterministic fact다.

따라서 VaR를 먼저 안정적으로 만들면:

- AR은 그 fact를 읽고 의견을 낼 수 있고
- validator는 그 fact로 하드 차단할 수 있고
- 이후 AI Compliance도 같은 숫자를 근거로 설명할 수 있다

즉 VaR는 "하나의 agent 기능"이 아니라
여러 계층이 공유하는 공통 기반이다.

#### AI Compliance를 마지막에 두는 이유

현재 가장 위험한 실패는
"애매한 해석이 없다"가 아니라
"차단/허용의 authoritative 경계가 불명확해지는 것"이다.

AI Compliance를 먼저 붙이면 설명은 풍부해질 수 있지만,

- deterministic validator보다 앞에서 과도한 영향력을 가질 수 있고
- 구현 복잡도만 증가할 수 있다

따라서 AI Compliance는
**deterministic compliance validator와 VaR/risk fact 구조가 먼저 닫힌 뒤**
올리는 것이 맞다.

---

## 5. 항목별 구체 진행안

## 5.1 1단계: Guardrail / Validator 일원화

### 목표

현재 분산된 hard stop 로직을
공통 규칙 평가 인터페이스로 정리한다.

### 현재 분산 위치 예시

- stale snapshot 계열 차단
- low-liquidity execution block
- duplicate buy guard
- sell guard
- reconciliation lock 기반 우회/차단
- kill switch / blocked reason code 기반 차단

### 권장 산출물

- `services/validators/` 계층 신설
- 공통 계약
  - `ValidationContext`
  - `ValidationRule`
  - `ValidationResult`
  - `ValidationSeverity`
- 실행 단계별 rule bundle
  - `decision_validator_v1`
  - `risk_validator_v1`
  - `compliance_validator_v1`
  - `execution_validator_v1`
- `guardrail_evaluations` 기록을 공통 writer로 일원화

### 구현 원칙

- 기존 보호 로직 의미를 바꾸지 않고 포장부터 정리한다.
- 처음부터 대규모 재작성하지 않는다.
- 기존 로직을 rule adapter 형태로 옮겨
  결과 모델만 먼저 표준화한다.

### 완료 기준

- 주요 block path가 `ValidationResult`를 통해 공통 형식으로 표현된다.
- `rule_set_version`, `blocking_rule_codes`, `rule_results`가 일관되게 남는다.
- ExecutionService 내부의 분산 if-block이 단계적으로 validator 호출로 치환된다.

## 5.2 2단계: 전용 deterministic VaR 엔진

### 목표

현재 `risk_limit_snapshot`을 exposure 중심 fact 저장소에서
**실제 risk analytics snapshot**으로 승격한다.

### 권장 구현 범위

v1에서는 복잡한 full covariance VaR보다 아래 순서가 적절하다.

#### v1-a

- symbol 변동성 기반 단순 parametric VaR
- 계좌 총 VaR
- 종목별 marginal contribution
- concentration penalty

#### v1-b

- segment / membership 가중치 반영
- open order exposure 포함
- held position + pending buy 동시 반영

#### v1-c

- stress scenario loss
- regime-aware multiplier

### 저장 구조 판단

가장 실용적인 방향은 아래 둘 중 하나다.

1. `risk_limit_snapshot` 확장
   - 장점: 기존 read path와 잘 붙음
   - 단점: risk analytics와 hard limit fact가 너무 섞일 수 있음
2. `risk_analytics_snapshot` 신설
   - 장점: VaR/stress analytics를 독립 확장 가능
   - 단점: read path 하나 더 늘어남

현재 구조에서는 **v1은 `risk_limit_snapshot` 확장**이 더 현실적이다.
다만 필드가 과도하게 커지면 P3 이후 `risk_analytics_snapshot` 분리를 재검토한다.

### 완료 기준

- snapshot sync 이후 deterministic VaR fact가 생성된다.
- `AI Risk Agent`가 그 fact를 읽을 수 있다.
- validator가 VaR threshold를 authoritative rule로 차단할 수 있다.
- replay 시 동일 시점 VaR 재현이 가능하다.

## 5.3 3단계: deterministic compliance validator

### 목표

AI Compliance 이전에,
절대 조건을 deterministic하게 차단하는 계층을 명문화한다.

### v1 authoritative hard rules 예시

- 금지 시장 / 금지 asset class
- 브로커 capability 미지원
- 계좌-상품 권한 불일치
- 시장 세션상 주문 불가
- 필수 필드 누락
- price band / lot / order type 규칙 위반
- restricted / blocked symbol
- 내부 운영 금지 리스트

### 완료 기준

- "AI가 아니어도 반드시 차단해야 하는 규칙"이 코드와 문서에서 명시된다.
- execution 전에 compliance validator가 공통 호출된다.
- AI Compliance가 없어도 live-safe 경계가 닫힌다.

## 5.4 4단계: AI Compliance Agent

### 목표

AI를 이용해 정책/규정 위반 가능성을 해석하되,
최종 집행은 deterministic validator가 수행하는 hybrid 구조를 완성한다.

### 권장 입력

- decision context
- risk analytics summary
- compliance validator 결과
- recent external events
- market session / account policy context
- instrument segment / membership / source type

### 권장 출력

- `compliance_opinion`
  - `allow`
  - `warn`
  - `review`
  - `reject`
- `compliance_score`
- `policy_flags`
- `reason_codes`
- `summary`
- `opposing_evidence`

### 연결 위치

권장 순서는 아래다.

- deterministic compliance validator
- AI Compliance Agent
- Hard Guardrail / unified validator final pass

즉 AI Compliance는
**hard rule 전단의 해석 계층** 또는
**hard rule 결과를 보강 설명하는 계층**으로 붙는 것이 맞다.

### 완료 기준

- paper/live 공통으로 structured output이 저장된다.
- FDC 또는 AR와 책임이 겹치지 않는다.
- deterministic validator보다 우선권을 갖지 않는다.

---

## 6. 우선순위 판단

## 6.1 실질 우선순위

### Priority A

- Guardrail / Validator 일원화

이유:

- 지금 당장 운영 안전성에 직접 연결된다.
- 이후 VaR와 compliance를 붙일 기반이 된다.

### Priority B

- deterministic VaR 엔진

이유:

- `최대 기대수익률`을 추구하더라도
  exposure와 tail risk를 숫자로 닫는 기반이 필요하다.
- AR 의견 품질도 이 fact에 의해 개선된다.

### Priority C

- deterministic compliance validator 명시화

이유:

- 이미 일부 규칙은 구현돼 있으나,
  "어디까지가 compliance hard rule인가"가 아직 문서/코드 구조상 흐리다.

### Priority D

- AI Compliance Agent

이유:

- 중요하지만, 앞의 세 단계가 닫히기 전에는
  설명은 늘고 authoritative 경계는 오히려 흐려질 수 있다.

## 6.2 roadmap 권장 배치

- P2 초반
  - Guardrail / Validator 일원화
  - deterministic compliance validator 명시화
- P2 중반
  - deterministic VaR 엔진
- P2 후반 또는 P3 초입
  - AI Compliance Agent

---

## 7. 우리의 핵심 목표와의 정합성

이 세 항목은 모두 `최대 기대수익률`과 직접 연결된다.

단, 기여 방식은 서로 다르다.

### VaR 엔진

- 무의미한 과대 포지션과 concentration risk를 줄여
  **손실 꼬리 위험을 낮춘다.**

### AI Compliance Agent

- 규정/정책/특수 이벤트 리스크를 더 정교하게 읽어
  **불필요한 체결/거부/운영 사고를 줄인다.**

### Guardrail 일원화

- 동일한 차단 기준을 일관되게 집행해
  **운영 drift와 예외 누락을 줄인다.**

즉 기대수익률 극대화 관점에서도
가장 먼저 해야 할 일은 "더 많은 AI"가 아니라
**결정적 방어 계층을 구조적으로 닫는 것**이다.

---

## 8. 최종 결론

세 항목 모두 필요하지만, 동시에 병렬로 크게 벌리면 안 된다.

가장 합리적인 경로는 아래다.

1. **Guardrail / Validator 일원화**
   - 현재 분산된 차단 로직을 공통 규칙 평가 체계로 정리
2. **전용 deterministic VaR 엔진**
   - risk fact를 숫자로 닫고 validator/AR가 함께 참조
3. **deterministic compliance validator 명시화**
   - 절대 금지 조건을 구조적으로 분리
4. **AI Compliance Agent**
   - 마지막에 해석 계층으로 붙이고 authoritative 집행은 주지 않음

한 줄로 요약하면:

**지금 필요한 것은 AI 계층 확대보다, deterministic validator 기반을 먼저 닫고 그 위에 VaR와 Compliance를 올리는 순서다.**
