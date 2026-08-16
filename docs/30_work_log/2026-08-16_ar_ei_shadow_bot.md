# AR/EI Shadow Bot 관측값 저장 작업 기록

## 목적

PR #277(`ai_compliance` deterministic bot 전환)의 후속 작업이다. AR
(`ai_risk`)과 EI(`event_interpretation`)는 이번 PR에서 **대체하지
않는다** — 실제 판단은 그대로 유지하고, 같은 decision context에서
deterministic rule 기반 shadow 판단을 병렬로 계산해 AI 판단과의 일치율을
관측만 한다. FDC(`final_decision_composer`)는 이번 작업의 대상이
아니다.

## 변경 요약

- `src/agent_trading/services/shadow_bots.py`(신규) — 순수 계산 모듈.
  - `compute_shadow_risk_bot()`: `portfolio_allocation`(concentration/
    cash), `market_regime`(risk_tone/volatility_regime),
    `deterministic_trigger`(eligibility), `recent_events`(direction
    기반 event conflict)만으로 `risk_opinion`/`risk_score`를 계산한다.
    확실한 정형 근거가 없으면 항상 `allow`/`0.0`이다.
  - `compute_shadow_event_bot()`: `recent_events`의 `direction`/
    `severity`/`source_reliability_tier` 정형 필드만으로 이벤트 개수/
    bias/conflict/evidence_strength를 계산한다. 헤드라인/본문 자유
    텍스트는 해석하지 않는다(비정형 뉴스 해석은 AI 유지 대상으로 남김).
  - `risk_score_bucket()`: AI/bot risk_score를 동일한 5구간으로 비교
    하기 위한 순수 함수.
- `src/agent_trading/services/decision_orchestrator.py`
  - `_record_ar_shadow_bot_observation()`/`_record_ei_shadow_bot_
    observation()` 추가 — `_record_loss_cut_shadow_observation()`과
    동일한 원칙: 결정 mutating guard 목록에 속하지 않고, `assemble()`
    최말단(트레이드 결정 확정 이후)에서만 호출되며, 반환값이 없고
    어떤 결정 필드도 mutate하지 않는다.
  - held_position override/FDC skip "would trigger" 비교는 **실제
    override/skip 판정 함수를 그대로 재사용**한다
    (`_check_held_position_sell_override()`, `_should_skip_final_
    decision_composer()`) — AR의 실제 출력과 bot 산출값을 담은
    synthetic `AIRiskOutput`을 각각 넣어 같은 함수로 두 번 평가한다.
    이렇게 하면 override/skip 로직이 바뀌어도 shadow 비교가 자동으로
    최신 로직을 따라가고, 별도 로직을 중복 구현할 필요가 없다.
  - execution risk-off "would trigger"는 `execution_service.py`의
    실제 조건(`risk_opinion != "allow" or risk_score >= 0.6`)을
    인라인으로 재현했다(이 조건 자체는 단순 불리언이라 함수 재사용
    없이 직접 계산).
  - shadow 계산 자체가 예외를 던지면 `shadow_error` 필드를 담은
    fallback payload를 대신 저장한다(계산 실패를 조용히 숨기지
    않음). 계산이 성공했더라도 DB 저장이 실패하면 로그만 남기고
    `assemble()` 흐름에 예외를 전파하지 않는다.
- `src/agent_trading/config/settings.py` — `AR_SHADOW_BOT_ENABLED`/
  `EI_SHADOW_BOT_ENABLED` env 스위치(기본값 `false`, `loss_cut_shadow_
  enabled`와 동일한 패턴)와 `AppSettings.ar_shadow_bot_enabled`/
  `ei_shadow_bot_enabled` 필드를 추가했다.
- `.env.example` — 위 두 env 키 문서화.
- `scripts/run_decision_loop.py` — 실제 운영 진입점 2곳(`DecisionOrchestratorService`
  생성 지점)에 `ar_shadow_bot_enabled=settings.ar_shadow_bot_enabled`/
  `ei_shadow_bot_enabled=settings.ei_shadow_bot_enabled`를 연결했다.
- `src/agent_trading/repositories/{contracts.py,postgres/trade_decisions.py,memory.py}`
  — `sync_shadow_risk_bot_observation()`/`sync_shadow_event_bot_
  observation()` 추가. `sync_loss_cut_shadow_observation()`과 동일한
  append-only `jsonb_set` 패치 패턴이며, DB migration은 없다(기존
  `decision_json` JSONB 컬럼에 새 키만 추가).

## 저장 필드

- `trade_decisions.decision_json.shadow_risk_bot`: `rule_set_version`,
  `bot_risk_opinion`, `bot_risk_score`, `bot_reason_codes`,
  `bot_risk_flags`, `bot_confidence`, `ai_risk_opinion`,
  `ai_risk_score_bucket`, `bot_risk_score_bucket`, `opinion_agreement`,
  `score_bucket_agreement`, `held_position_override_ai_would_trigger`,
  `held_position_override_bot_would_trigger`,
  `held_position_override_agreement`, `fdc_skip_ai_would_trigger`,
  `fdc_skip_bot_would_trigger`, `fdc_skip_agreement`,
  `execution_risk_off_ai_would_trigger`,
  `execution_risk_off_bot_would_trigger`,
  `execution_risk_off_agreement`, `shadow_only`,
  `decision_unaffected_by_shadow`(항상 `true`).
- `trade_decisions.decision_json.shadow_event_bot`: `rule_set_version`,
  `bot_detected_event_count`, `bot_interpreted_event_count`,
  `bot_event_bias`, `bot_event_conflict`, `bot_evidence_strength`,
  `bot_no_material_events`, `bot_reason_codes`,
  `ai_detected_event_count`, `ai_interpreted_event_count`,
  `ai_event_bias`, `ai_event_conflict`, `ai_no_material_events`,
  `event_count_agreement`, `bias_agreement`, `conflict_agreement`,
  `no_material_events_agreement`, `shadow_only`,
  `decision_unaffected_by_shadow`.
- 기존 `decision_json` key(예: `risk_opinion`, `compliance_*`,
  `candidate_vs_final`, `ai_call_path`)는 전혀 건드리지 않았다 —
  append-only 확장이다.

## 실제 policy 영향 여부

**없음.** `_record_ar_shadow_bot_observation`/`_record_ei_shadow_bot_
observation`은 `assemble()`에서 `_ensure_trade_decision()` 이후, 즉
`decision_type`/`side`/`target_quantity`가 이미 확정되고 저장된
**다음**에만 호출된다. 두 메서드 모두 반환값이 없고(`-> None`)
`agent_bundle`/`intent`/`decision_type`을 mutate하는 코드가 전혀 없다.
`translation.py`/`execution_service.py`/`sizing_engine.py`의 주문
생성·수량·guard 로직도 건드리지 않았다. feature flag 기본값이
`false`이므로 이번 배포만으로는 계산 자체가 실행되지 않는다(관측
시작은 별도로 env를 켜야 한다).

## EV gate 관련 변경 여부

없음. AR shadow bot의 핵심 판단 로직(`compute_shadow_risk_bot`)은
EV gate 관련 필드를 입력으로 사용하지 않는다(2026-08-07 신규매수 EV
gate 무력화 정책을 전제로, EV gate를 재도입하는 방향으로 설계하지
않았다). EV gate 코드/필드 자체는 이번 PR에서 수정하지 않았다.

## 테스트 결과

| 명령 | 결과 |
| --- | --- |
| `bash scripts/harness/run.sh test-file tests/services/test_shadow_bots.py` | 16 passed(순수 계산 함수 단위 테스트) |
| `bash scripts/harness/run.sh test-file tests/services/test_decision_orchestrator.py` | 81 passed(기존 70 + 신규 AR/EI shadow 관측 10건 + 전체 흐름 회귀 테스트 1건) |
| `bash scripts/harness/run.sh test-file tests/scripts/test_run_decision_loop.py` | 130 passed |
| `bash scripts/harness/run.sh test-file tests/services/test_ev_gate_near_miss_override.py` | 14 passed |
| `bash scripts/harness/run.sh test-file tests/services/test_held_position_sell_override.py` | 14 passed |
| `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_orchestrator_agents.py` | 22 passed |
| `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_settings.py` | 65 passed |
| `bash scripts/harness/run.sh accept backend-file src/agent_trading/services/shadow_bots.py` | PASS |
| `bash scripts/harness/run.sh accept backend-runtime` | PASS |
| `bash scripts/harness/run.sh accept db-structure` | PASS(protocol/postgres/memory 3자 일치, missing count 0) |
| `bash scripts/harness/run.sh accept style` / `accept no-bypass` / `accept architecture` | PASS |
| `bash scripts/harness/run.sh lint-path <변경 파일 전체>` | 전부 PASS |

`accept backend-file src/agent_trading/services/decision_orchestrator.py`와
`accept backend-file src/agent_trading/config/settings.py`는 자동 선택된
후보 중 `test_kis_realtime_quote_source.py`/`test_broker_capacity.py`가
실패로 잡히지만, 이는 이번 변경 이전(`main`)에서도 동일하게 실패하는
사전 존재 문제(웹소켓 타이밍 flaky, Postgres 연결 거부)로 PR #277 작업
때 이미 `git stash` 대조로 확인된 것과 동일한 패턴이다. 이번 턴에서는
관련 실제 테스트 파일(`test_decision_orchestrator.py`, `test_settings.py`
등)을 개별적으로 직접 실행해 0 실패를 확인했다.

## 머지 전 확인 사항

- feature flag 기본값이 `false`인지(`AR_SHADOW_BOT_ENABLED`/
  `EI_SHADOW_BOT_ENABLED`) 재확인.
- `decision_orchestrator.py`의 `_record_ar_shadow_bot_observation`/
  `_record_ei_shadow_bot_observation` 호출 위치가 `_ensure_trade_
  decision()` 이후인지(결정 확정 이후에만 호출되는지) 코드 리뷰로
  재확인.
- `db-structure` 계약이 3개 구현(Protocol/Postgres/Memory)의 신규
  메서드 시그니처 일치를 계속 강제하는지 확인.

## 배포 후 실측할 항목

- `AR_SHADOW_BOT_ENABLED=true`/`EI_SHADOW_BOT_ENABLED=true`로 켠 뒤,
  다음 거래일 실제 결정 사이클에서 `trade_decisions.decision_json.
  shadow_risk_bot`/`shadow_event_bot`이 실제로 적재되는지 확인한다.
- `opinion_agreement`/`bias_agreement`/`held_position_override_
  agreement`/`fdc_skip_agreement`/`execution_risk_off_agreement`의
  실측 분포(일치율)를 확인한다.
- shadow 계산이 실패해 `shadow_error` 필드가 기록되는 사례가 있는지
  확인한다(있다면 rule 계산 로직의 예외 케이스를 보강해야 함).

## 후속 작업

- shadow agreement 집계용 read-only 쿼리/API 작성(`loss_cut_shadow`의
  `list_loss_cut_shadow_observations()` 선례 참고).
- AI/bot이 다르게 판단한 구간의 사후 실현손익/MFE/MAE/기회비용 비교
  분석 턴.
- 위 실측이 쌓인 뒤 AR/EI를 부분/전체 deterministic bot으로 전환할지
  결정하는 턴.
