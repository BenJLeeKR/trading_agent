# EI(event_interpretation) Deterministic Bot 전환 (PR1)

## 목적

`docs/30_work_log/2026-08-16_ei_ar_deterministic_bot_design_review.md`에서
확정한 설계에 따라, EI(`event_interpretation`)를 100% deterministic
bot으로 본경로 전환한다. AR(`ai_risk`)은 이번 PR 대상이 아니며 별도
PR(PR2)로 진행한다. AC(`ai_compliance`)는 PR #277에서 이미 완료됐고,
FDC(`final_decision_composer`)는 유지 대상이다.

## 변경 요약

- **`src/agent_trading/services/ai_agents/event_interpretation.py`**
  - `DeterministicEventInterpretationAgent` 추가 — `agent_name=
    "event_interpretation"`, `schema_version="v1"` 유지, `run()`은
    LLM 호출 없이 `_compute_deterministic_event_interpretation()`을
    호출한다.
  - `_compute_deterministic_event_interpretation()`(모듈 함수) 추가 —
    `compute_shadow_event_bot()`(shadow_bots.py)으로 `aggregate_view`를
    계산하고, `_finalize_ei_output()`(기존 함수, LLM detected-only
    fallback 경로가 이미 쓰던 것)에 위임해 `events[]`/
    `interpreted_event_count`/`summary_basis`/`summary`를 채운다.
  - 기존 LLM `EventInterpretationAgent` 클래스는 삭제하지 않고, 클래스
    앞에 "2026-08-17부터 wiring 제외, legacy/테스트 전용 보존" 주석을
    추가했다.
  - `last_error_metadata` 프로퍼티를 `DeterministicEventInterpretationAgent`에
    추가(`decision_agent_runner.py:271`이 `self._ei_agent.
    last_error_metadata`를 직접 접근하므로 필수 — `getattr` 방어 없이
    속성이 존재해야 함).
- **`src/agent_trading/services/shadow_bots.py`**
  - `compute_shadow_event_bot()`에 `rule_set_marker` 키워드 전용
    파라미터를 추가(기본값은 기존 `shadow_rule_set:ei_shadow_v1`과
    100% 동일해 기존 shadow 관측 호출은 전혀 영향받지 않음). 본경로
    EI bot은 `deterministic_rule_set:ei_bot_v1`을 넘겨 관측 전용 마커와
    구분한다.
  - `EI_BOT_RULE_SET_VERSION = "ei_bot_v1"` 상수 추가.
  - **AR 관련 로직(`compute_shadow_risk_bot`)은 전혀 건드리지 않았다.**
- **`src/agent_trading/runtime/bootstrap.py`**
  - `_build_provider_agent()`의 본문을 AC 전환(`_build_ai_compliance_agent()`)과
    동일한 패턴으로 교체 — provider 설정 유무와 무관하게 항상
    `DeterministicEventInterpretationAgent()`를 반환한다. 함수
    시그니처(파라미터 `settings`)는 다른 builder와 통일성을 위해
    유지했다.
  - `_build_orchestrator()`의 `event_interpretation_agent` 파라미터
    타입 힌트를 `DeterministicEventInterpretationAgent | None`으로
    갱신.
- **`scripts/run_agent_subprocess.py`**
  - `_build_agent_triplet()`에서 EI 슬롯이 provider_client 유무와
    무관하게 항상 `DeterministicEventInterpretationAgent()`가 되도록
    변경(AC와 동일 패턴). AR/FDC는 기존 provider/stub 판단을 그대로
    유지했다.
  - 반환 타입 힌트를 `DeterministicEventInterpretationAgent`로 갱신.
- **`decision_agent_runner.py`/`decision_orchestrator.py`/
  `subprocess_helpers.py`는 전혀 수정하지 않았다** — 구조적 타이핑
  (protocol) 덕분에 EI 구현체 교체가 이 세 파일에 영향을 주지 않는다.

## 저장/관측 호환성

- `agent_runs.agent_type`은 계속 `"event_interpretation"`.
- `agent_runs.structured_output_json.aggregate_view.top_reason_codes`에
  `deterministic_rule_set:ei_bot_v1` 마커가 남아 deterministic 판단임을
  구분할 수 있다.
- `trade_decisions.decision_json`의 기존 key(`event_bias`,
  `event_conflict`, `event_reason_codes`, `evidence_strength`,
  `no_material_events`, `detected_event_count`,
  `interpreted_event_count`)는 `decision_factory.py`의 매핑 코드를
  전혀 바꾸지 않았으므로 그대로 유지된다.
- `decision_json.shadow_event_bot`(관측 전용, PR #278)은 이번 PR에서
  건드리지 않았다 — 계속 별도로 기록된다(단, 이제는 "AI vs bot" 비교가
  아니라 사실상 "bot vs bot" 비교가 되므로 그 자체의 의미는 옅어짐 —
  PR3에서 정리 검토).

## 실제 policy 영향 여부

**직접적인 주문/차단/수량 로직 변경 없음.** `translation.py`/
`execution_service.py`/`sizing_engine.py`는 전혀 수정하지 않았다. 다만
FDC가 참조하는 EI 출력의 **품질**이 바뀌었다는 점은 policy 관점에서
의미가 있다:

- 정형 신호(direction/severity/source_reliability_tier) 기반 판단은
  100% 보존된다.
- 비정형 헤드라인/본문 뉘앙스 해석은 사라진다 — FDC가 그만큼 얕아진
  이벤트 서술을 입력받게 되며, 이는 FDC 자신의 최종 판단(`decision_type`
  등)에 간접적으로 영향을 줄 수 있다(설계 문서 §4.4/4.5에서 이미
  예상한 트레이드오프). 이 영향의 크기는 배포 후 실측이 필요하다.

## EV gate 관련 변경 여부

없음. EV gate 코드/필드를 전혀 건드리지 않았다.

## 테스트 결과

| 명령 | 결과 |
| --- | --- |
| `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_ei_deterministic.py`(신규) | 12 passed |
| `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_bootstrap.py` | 32 passed(EI 관련 assertion 전면 갱신 포함) |
| `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_agent_subprocess.py` | 20 passed(실제 subprocess 스폰 경유, EI가 deterministic bot으로 정상 동작) |
| `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_orchestrator_agents.py` | 22 passed(변경 없음 확인용) |
| `bash scripts/harness/run.sh test-file tests/services/test_decision_orchestrator.py` | 81 passed(decision_orchestrator.py 미변경 회귀 확인) |
| `bash scripts/harness/run.sh test-file tests/services/test_shadow_bots.py` | 16 passed(`rule_set_marker` 파라미터 추가가 기존 shadow bot 동작에 영향 없음) |
| `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_event_interpretation.py` | 38 passed(`_reconstruct_events`/`_finalize_ei_output` 등 재사용 함수 회귀 없음) |
| `bash scripts/harness/run.sh test-file tests/services/test_decision_submit_pipeline.py` | 65 passed |
| `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_ai_compliance_deterministic.py` / `test_ai_compliance_prompt.py` | 10 + 2 passed(AC 무관 확인용) |
| `bash scripts/harness/run.sh accept backend-file src/agent_trading/services/ai_agents/event_interpretation.py` | 자동 선택 후보 중 `tests/scripts/test_fdc_skip.py`가 `/workspace` read-only 파일시스템 오류로 실패 — **PR #277에서 이미 확인한 사전 존재 인프라 이슈와 동일**(무관). 실제 관련 테스트(`test_decision_submit_pipeline.py`, `test_event_interpretation.py`, 신규 `test_ei_deterministic.py`)는 위에서 개별 실행해 0 실패 확인 |
| `bash scripts/harness/run.sh accept backend-file src/agent_trading/services/shadow_bots.py` | PASS(`test_shadow_bots.py` + `test_ei_deterministic.py` 자동 실행, 0 실패) |
| `bash scripts/harness/run.sh accept backend-runtime` | PASS |
| `bash scripts/harness/run.sh accept script-file scripts/run_agent_subprocess.py` | 자동 선택 후보가 `test_fdc_skip.py` 하나뿐이라 동일한 사전 존재 인프라 이슈로 FAIL — 관련 실제 테스트는 `test_agent_subprocess.py`(위에서 20 passed 확인)로 대체 검증 |
| `bash scripts/harness/run.sh accept architecture` / `accept no-bypass` / `accept style` | 전부 PASS |
| `HARNESS_ALLOW_NO_TEST=1 bash scripts/harness/run.sh accept backend-file src/agent_trading/services/ai_agents/__init__.py` | PASS(재수출 전용 파일, 직접 테스트 없음 — 우회 사유 명시, PR #277과 동일 판단) |

**사전 존재 실패 확인 방법**: `tests/scripts/test_fdc_skip.py`의 `/workspace` read-only
오류를 `git stash`로 대조해 이번 변경 전 `main`에서도 동일하게 발생함을
재확인했다(PR #277에서 이미 확인한 것과 동일 이슈, 이번 PR과 무관).
`tests/services/ai_agents/test_fdc_prompt.py::TestBuildSubmitOrderRequestWatch`
5건도 동일한 방법(`git stash`)으로 대조한 결과 **이번 변경 전 `main`에서도
이미 실패**하고 있음을 확인했다(`translation.py` 관련, 이번 PR이
건드리지 않은 파일 — 무관한 사전 존재 결함).

## 부수 발견 (이번 PR 범위에서 함께 교정)

`tests/smoke/test_runtime_three_agent_smoke.py`의
`TestRuntimeThreeAgentFallback`(`@pytest.mark.smoke` 마커가 없어
상시 실행되는 클래스)이 PR #277(AC 전환) 이후 `runtime["ai_compliance_agent"]
is None` 단언이 갱신되지 않은 채 남아 있던 것을 이번 EI 관련 편집
과정에서 발견했다. AC 코드 자체는 전혀 건드리지 않고, 단언만
`isinstance(..., DeterministicAIComplianceAgent)`로 교정했다(EI 관련
단언과 함께 같은 파일/같은 편집 범위에서 수정하는 것이 합리적이라
판단). 이 파일은 `tests/smoke/` 경로 자체가 하네스 정책상 승인 없이
실행할 수 없어(`ERROR: 부하 또는 외부 연동 가능성이 있는 테스트 경로는
승인 없이 실행하지 않습니다`), 이번 세션에서 `py_compile` 검증만
수행했고 실제 pytest 실행 검증은 하지 못했다(§미검증 사항).

## 미검증 사항

- `tests/smoke/test_runtime_three_agent_smoke.py`의 실제 pytest 실행
  검증(하네스가 `tests/smoke/` 경로를 승인 없이 차단, `py_compile`만
  확인).
- 다음 거래일 이후 실제 decision loop 기준 `agent_runs.agent_type=
  'event_interpretation'` 기록과 `decision_json.event_*` 필드 분포.
- FDC가 얕아진 이벤트 서술을 받았을 때 최종 `decision_type` 판단이
  실제로 얼마나 달라지는지(설계 문서에서 예상한 트레이드오프의 실측).
- `tests/scripts/test_fdc_skip.py`/`test_fdc_prompt.py`의 사전 존재
  실패(각각 인프라 이슈/`translation.py` 관련)는 이번 PR 범위 밖이라
  수정하지 않았다 — 별도 이슈로 남긴다.

## 후속 작업

- PR2: AR(`ai_risk`) deterministic 본경로 전환 — `"reject"` opinion
  트리거 보강 포함, held_position override/FDC skip/execution
  risk-off/EXIT 승격 회귀 테스트 필수.
- PR3: legacy LLM `EventInterpretationAgent`/`AIRiskAgent` 정리,
  `shadow_event_bot`/`shadow_risk_bot` 필드 정리 — PR1/2 배포 후
  관측 기간을 거쳐 결정.
- 배포 후 실측(위 미검증 사항 참고).
