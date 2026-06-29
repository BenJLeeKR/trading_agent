# Deterministic Compliance Validator Phase 1

## 목적

`AI Compliance Agent`가 아직 없는 상태에서도,
AI 해석과 무관하게 반드시 차단해야 하는 주문/의사결정 위반 조건을
deterministic validator로 먼저 닫는다.

핵심 원칙은 아래와 같다.

- authoritative 차단은 항상 deterministic validator가 수행한다.
- `AI Compliance Agent`는 향후 설명/해석 계층으로만 붙는다.
- `OrderManager / ReconciliationService / BrokerAdapter` 경계는 유지한다.
- unknown order state보다 신규 주문 우선 금지 원칙을 깨지 않는다.

## Phase 1 범위

Phase 1에서는 이미 코드 곳곳에 흩어져 있거나
부분적으로만 구현된 compliance 성격의 hard rule을
하나의 validator 체계로 명시하는 것까지를 범위로 둔다.

### 포함 대상

1. source policy 기반 신규 진입 금지
2. reconciliation overlay flat BUY 금지
3. 시장 세션상 주문 불가
4. 브로커 capability 미지원 주문형 차단
5. 필수 주문 필드 누락 / 비정상 side / order_type 조합 차단
6. restricted / blocked symbol / 내부 운영 금지 리스트 차단

### Phase 1 비포함

1. 자연어 규정 해석
2. 이벤트 맥락 기반 규정 해석
3. 정책 설명용 LLM 출력
4. VaR 수치 판단

## 권장 rule set 구조

### validator bundle

- `compliance_validator_v1`

### 개별 rule 초안

- `compliance_source_policy_buy_blocked`
- `compliance_reconciliation_overlay_flat_buy_blocked`
- `compliance_market_session_blocked`
- `compliance_broker_capability_blocked`
- `compliance_missing_required_field`
- `compliance_invalid_order_shape`
- `compliance_restricted_symbol`

## 코드 연결 지점

### 1. decision_orchestrator

AI 호출 전 deterministic short-circuit 대상 중
compliance 성격이 강한 항목을
`decision_policy_validator_v1`에서 분리해
`compliance_validator_v1`로 이동할 수 있게 준비한다.

우선 후보:

- `source_policy_buy_blocked`
- `policy_reconciliation_overlay_flat_buy_blocked`

### 2. execution_service

실제 submit 직전 authoritative enforcement 지점으로 사용한다.

우선 후보:

- 시장 세션상 주문 불가
- 필수 필드 누락
- 브로커 capability 미지원
- restricted symbol

후속 확장:

- `restricted symbol`은 장기적으로
  `risk_limit_snapshot.blocked_reason_codes` fallback이 아니라
  `instrument_status_snapshot` 기반 fact를 우선 읽어야 한다.
- 관련 설계:
  [`plans/[PLAN] instrument_status_snapshot_phase1.md`](./[PLAN]%20instrument_status_snapshot_phase1.md)

### 3. 공통 저장 형식

모든 차단 결과는 아래를 만족해야 한다.

- `rule_set_version`
- `blocking_rule_codes`
- `rule_results`
- `validator_bundle=compliance_validator_v1`
- 가능하면 `rule_outcomes`

## 구현 순서

### Step 1

`services/compliance_validator.py` 추가

- `ComplianceValidationInput`
- `evaluate_compliance_rules(...)`
- Phase 1 rule skeleton

### Step 2

`decision_orchestrator`의 source policy short-circuit 중
compliance 성격 rule을 별도 bundle로 분리

### Step 3

`execution_service` submit 직전 공통 compliance validator 호출 추가

### Step 4

guardrail row와 테스트에서
`validator_bundle=compliance_validator_v1` 검증 추가

## 완료 기준

아래가 만족되면 Phase 1 완료로 본다.

- compliance hard rule 목록이 문서와 코드에 일치한다.
- 최소 2개 이상의 실제 차단 경로가 `compliance_validator_v1`로 기록된다.
- `decision_orchestrator` 또는 `execution_service` 중 최소 1개 지점에서
  공통 compliance validator 호출이 붙는다.
- `AI Compliance Agent` 없이도 live-safe 차단 경계가 유지된다.
