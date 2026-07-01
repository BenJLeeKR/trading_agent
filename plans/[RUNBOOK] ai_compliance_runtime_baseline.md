# AI Compliance Runtime Baseline

## 목적

`11-d`의 마지막 항목인 `AI Compliance prompt / runtime smoke / 실운영 로그 기준선 문서화`를 고정한다.

이 문서는 다음 세 가지를 한 번에 다룬다.

1. `AIComplianceAgent` 프롬프트가 지켜야 할 경계
2. 4-agent runtime smoke에서 확인해야 할 최소 성공 조건
3. 실운영 로그 / DB에서 확인해야 할 기준선과 이상 징후

핵심 전제는 변하지 않는다.

- `AI Compliance`는 해석 보조 계층이다.
- authoritative 허용/차단은 언제나 deterministic validator가 맡는다.
- `AI Compliance`는 정책/규정/이벤트 맥락의 애매함을 구조화해 설명력을 높이는 용도다.

---

## Prompt 기준선

### 1. System Prompt 불변 조건

`src/agent_trading/services/ai_agents/ai_compliance.py`의 system prompt는 아래 내용을 항상 유지해야 한다.

- `compliance_opinion` 허용 값은 `allow / warn / review / reject`
- hard broker rejection rule을 재구현하지 않음
- deterministic validator가 최종 권한이라는 점을 명시
- `policy_flags`, `reason_codes`는 기계 판독 가능한 영어 코드
- `summary`, `opposing_evidence`는 한국어

즉, prompt가 강화되더라도 아래 경계는 깨지면 안 된다.

- `AI Compliance`가 직접 주문 허용/차단 authority를 주장하면 안 됨
- deterministic validator보다 앞서 절대 규칙을 집행하면 안 됨
- broker field validation, order shape validation, restricted symbol validation을 다시 쓰면 안 됨

### 2. User Prompt 불변 조건

user prompt는 최소한 아래 입력 단면을 포함해야 한다.

- `Source type`
- deterministic context projection
- `Event Interpretation Output`
- `AI Risk Output`

특히 아래 항목은 실운영 품질과 직접 연결된다.

- `Source type: core / held_position / event_overlay / market_overlay`
- `Evidence strength`
- `Risk opinion`
- `Risk flags`
- `Top reason codes`

---

## Runtime Smoke 기준선

### 1. 대상 테스트

다음 테스트를 `AI Compliance` runtime baseline으로 본다.

- `tests/services/ai_agents/test_ai_compliance_prompt.py`
- `tests/smoke/test_runtime_three_agent_smoke.py`
  - 파일명은 legacy지만 현재 기준은 **4-agent chain smoke**
- `tests/smoke/test_kis_sandbox_ai_runtime_smoke.py`

### 2. 최소 성공 조건

#### A. Prompt 단위 기준

- `AIComplianceAgent._build_system_prompt()`에 non-authoritative 경계 문구가 존재
- `AIComplianceAgent._build_user_prompt()`에 `Source type`, `EI`, `AR` 단면이 모두 존재

#### B. Runtime wiring 기준

`build_default_runtime()` 기준으로 아래 key가 모두 존재해야 한다.

- `event_interpretation_agent`
- `ai_risk_agent`
- `ai_compliance_agent`
- `final_decision_agent`

provider 미설정 시에는 네 슬롯 모두 `None`이어야 한다.

#### C. Stub assemble 기준

provider 미설정 환경에서 `orchestrator.assemble()` 호출 시:

- recorder에 agent run이 4건 남아야 함
- `agent_type`
  - `event_interpretation`
  - `ai_risk`
  - `ai_compliance`
  - `final_decision_composer`
- `ai_backend_inputs.source_agent_names` 길이 4
- `ai_backend_inputs.schema_versions` 길이 4
- `ai_backend_inputs.compliance_opinion == "allow"`

#### D. Real runtime smoke 기준

provider 설정 환경에서:

- `EI -> AR -> AC -> FDC` 4-agent chain이 모두 실행됨
- recorder에 4건의 structured output이 남음
- `AIDecisionInputs`에 아래 compliance 필드가 접근 가능함
  - `compliance_opinion`
  - `compliance_score`
  - `compliance_confidence`
  - `compliance_reason_codes`
  - `compliance_policy_flags`
  - `compliance_check_passed`

#### E. KIS 결합 smoke 기준

`tests/smoke/test_kis_sandbox_ai_runtime_smoke.py` 기준으로:

- `SubmitOrderRequest`에는 AI field가 직접 섞이지 않아야 함
- `OrderIntent.ai_backend_inputs`에는 compliance field가 존재해야 함
- real provider 환경에서는 `source_agent_names`가 4건이어야 함

---

## 실운영 로그 기준선

### 1. 정상 기준선

실운영에서 아래 세 축이 서로 맞물려 보여야 정상이다.

#### A. agent run

- `agent_runs.agent_type = "ai_compliance"` row 존재
- `structured_output_json.agent_name = "ai_compliance"`

#### B. trade decision projection

`trade_decisions.decision_json` 또는 projection 필드에 아래가 존재

- `compliance_opinion`
- `compliance_score`
- `compliance_confidence`
- `compliance_reason_codes`
- `compliance_policy_flags`
- `compliance_check_passed`

#### C. submit 직전 validator telemetry

`guardrail_evaluations.rule_results.ai_compliance_alignment`에 아래가 남음

- `agreement_status`
- `mismatch_reason`
- `ai_check_passed`
- `deterministic_check_passed`
- `deterministic_blocking_rule_codes`
- `deterministic_stop_reason`
- `validator_bundle`

### 2. 경고 로그 기준선

아래 warning 로그는 `AI Compliance`와 deterministic validator가 엇갈렸음을 의미한다.

`AI compliance mismatch detected: symbol=%s trade_decision_id=%s reason=%s ai_check_passed=%s deterministic_check_passed=%s`

이 로그는 곧바로 장애는 아니지만, 다음 우선순위로 점검해야 한다.

- `ai_check_passed=True`, `deterministic_check_passed=False`
  - `AI`는 허용했지만 hard rule이 막은 상태
  - 보통 prompt drift가 아니라 정상적인 hard guard 작동일 수 있음
  - 다만 동일 사유가 반복되면 prompt가 hard rule 경계를 너무 자주 침범하는지 점검

- `ai_check_passed=False`, `deterministic_check_passed=True`
  - deterministic path는 허용인데 `AI Compliance`가 review/reject로 기울어진 상태
  - 정책 해석이 과보수적인지, source/event context가 과도하게 부정적으로 투영되는지 점검

### 3. inspection API 기준선

`GET /trade-decisions`의 `compliance_inspection`에서 아래가 보여야 한다.

- `agreement_status`
- `ai_projection`
- `ai_agent_run`
- `deterministic_validator`

submit 직전 telemetry가 존재하면 `agreement_status`는 그 값을 우선 반영한다.

즉, 단순히 `decision_json`과 guardrail row를 사후 비교한 값보다,
실제 submit 시점에 기록한 `ai_compliance_alignment`가 운영 기준선이다.

---

## 이상 징후 해석

### 1. `ai_compliance` agent run이 없음

점검 순서:

1. runtime wiring에서 `ai_compliance_agent` key 존재 여부
2. `DecisionAgentRunner`가 `EI -> AR -> AC -> FDC` 순서로 실행되는지
3. provider credential 미설정으로 stub fallback만 남았는지

### 2. `decision_json`에는 compliance projection이 있는데 guardrail telemetry가 없음

해석:

- submit 이전 단계까지만 진행되고 실제 submit-time compliance validator가 타지 않았을 수 있음
- 또는 차단/불일치가 없어 telemetry persist 조건을 충족하지 않았을 수 있음

현재 기준:

- `compliance_validator_v1` 차단이면 반드시 guardrail row가 남아야 함
- `allowed`여도 `agreement_status=conflict`이면 guardrail row가 남아야 함

### 3. mismatch warning이 과다 발생

우선 점검:

1. `AIComplianceAgent` prompt drift
2. `source_type` 전달값 오류
3. `risk_flags` / `event_reason_codes`가 과도하게 부정적으로 들어가는지
4. deterministic validator 신규 rule 추가 이후 prompt 경계 문구가 뒤처졌는지

---

## 권장 점검 명령

### 단위/계약 테스트

```bash
docker compose exec app python3 -B -m pytest -q \
  tests/services/ai_agents/test_ai_compliance_prompt.py
```

### smoke 회귀

```bash
docker compose exec app python3 -B -m pytest -q \
  tests/smoke/test_runtime_three_agent_smoke.py \
  tests/smoke/test_kis_sandbox_ai_runtime_smoke.py
```

### inspection / submit-time 회귀

```bash
docker compose exec app python3 -B -m pytest -q \
  tests/api/test_inspection.py \
  tests/services/test_decision_submit_pipeline.py
```

---

## 후속 연결

이 문서는 아래 작업의 기준선으로 사용한다.

- `11-d` 완료 판정
- `13. AI Compliance / Model Monitor 분해`
- 향후 provider 교체 시 `AI Compliance` runtime 검증

---

## 최근 검증 메모

### 2026-07-01

- `KIS_LIVE_INFO_APP_KEY` / `KIS_LIVE_INFO_APP_SECRET` 반영값을 재검증했다.
- live-info OAuth 직접 호출 결과 `200 OK`를 확인했다.
- 아래 캐시 파일 재생성을 확인했다.
  - `.cache/kis_live_oauth_token.json`
  - `.cache/kis_disclosure_token.json`
- `ops-scheduler` 로그에서 아래 기준선을 확인했다.
  - `live_holiday_oauth token cache: hit`
  - `KisHolidayProvider: session_info ... source=kis_holiday_api`
  - `EGW00103`
  - `유효하지 않은 AppKey입니다.`
    가 더 이상 발생하지 않음

이는 `AI Compliance`가 참조하는 live disclosure / session 보조 경로가
현재 기준 정상 복구되었음을 뜻한다.
