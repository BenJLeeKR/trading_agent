# AR(ai_risk) Deterministic Bot 전환 (PR2)

## 목적

`docs/30_work_log/2026-08-16_ei_ar_deterministic_bot_design_review.md`와
PR1(`docs/30_work_log/2026-08-17_ei_deterministic_bot_pr1.md`)에 이어,
AR(`ai_risk`)을 100% deterministic bot으로 본경로 전환한다. EI는
PR1에서 이미 완료됐고 이번 PR에서 재작업하지 않는다. AC(`ai_compliance`)는
기존 deterministic 유지, FDC(`final_decision_composer`)는 LLM 유지.

## 실제 영향 경로 (전환 전 재확인)

설계 검토에서 이미 확인했듯, AR은 EI보다 실제 영향 경로가 넓다.
`risk_opinion`/`risk_score`/`risk_flags`가 다음 4곳에 직접 영향을 준다:

1. **held_position sell override**(`decision_orchestrator.py:
   _check_held_position_sell_override`) — `risk_opinion in ("reject",
   "reduce")` 또는 (`risk_opinion=="review"` and `risk_score>=0.8`)
   또는 `risk_score>=0.8`이면 FDC의 HOLD/APPROVE/BUY를 REDUCE/EXIT로
   override. `risk_flags`에 "concent"/"expos"/"over" 포함 시 EXIT로
   승격.
2. **FDC skip**(`decision_agent_runner.py:_should_skip_final_decision_
   composer`) — `risk_opinion=="reject"`(score 무관) 또는
   `risk_score>=0.85`면 신규 core BUY 경로에서 FDC 호출 자체를 생략.
3. **execution risk-off / 단주 MARKET guard**(`execution_service.py`)
   — `risk_opinion != "allow"` 또는 `risk_score>=0.6`이면 고변동성
   단주 시장가 주문을 차단.
4. **FDC 프롬프트 입력**(`final_decision_composer.py`) — `risk_opinion`/
   `risk_score`/`risk_flags`/`reason_codes`/`size_adjustment_factor`를
   그대로 프롬프트 텍스트로 전달.

## `"reject"` 트리거 설계 근거

기존 `compute_shadow_risk_bot()`(PR #278)의 룰셋은 최대 `"reduce"`
(score>=0.8)까지만 도달하고 `"reject"`에는 결코 도달하지 못했다 —
설계 검토에서 확인한 핵심 리스크였다. `_should_skip_final_decision_
composer()`가 `risk_opinion=="reject"`를 score와 무관한 **즉시 skip**
신호로 다루는 것을 볼 때, `"reject"`는 "극단적으로 확실한 위험 상태"를
표현하는 등급이어야 한다.

**설계**: `score>=0.9`일 때 `"reject"`. 대표 예시 —
`concentration_over_limit`(0.4) + `insufficient_cash`(0.3) +
`risk_off_regime`(0.2) = 0.9. 이는 사용자가 제시한 예시 기준
("강한 concentration 초과 + cash 부족 + risk-off regime 동시 발생")과
정확히 일치한다. 새로운 하드 차단을 추가하는 것이 아니라, 이미 존재하는
override/skip 판정이 기대하는 신호를 deterministic bot도 낼 수 있게
하는 것뿐이다 — 4개 조건(concentration/cash/regime/volatility) 중
아무거나 3개 이상이 겹쳐야 도달 가능한 등급이므로 과도한 차단이
아니다(단일 신호만으로는 최대 0.4에 그친다).

**부동소수점 버그**: 구현 중 `0.4 + 0.3 + 0.2 == 0.8999999999999999`
(IEEE754 부동소수점 가산 오차)라는 것을 테스트로 발견해, 정확히
threshold에 걸치는 조합이 threshold 미만으로 판정되는 경계값 버그가
생겼다. `score = round(max(0.0, min(1.0, score)), 4)`로 수정해
해결했다.

## 변경 요약

- **`src/agent_trading/services/ai_agents/ai_risk.py`**
  - `DeterministicAIRiskAgent` 추가 — `agent_name="ai_risk"`,
    `schema_version="v1"` 유지, `run()`은 LLM 호출 없이
    `_compute_deterministic_ai_risk()`를 호출한다.
  - `_compute_deterministic_ai_risk()`(모듈 함수) 추가 —
    `compute_shadow_risk_bot()`으로 `risk_opinion`/`risk_score`/
    `risk_flags`/`reason_codes`를 계산하고, `size_adjustment_factor`는
    opinion에 연동된 참고용 값(allow=0.0/review=0.2/reduce=0.5/
    reject=0.8)으로 채운다(§size_adjustment_factor 참고).
  - 기존 LLM `AIRiskAgent` 클래스는 삭제하지 않고, 클래스 앞에
    "2026-08-17부터 wiring 제외, legacy/테스트 전용 보존" 주석을
    추가했다.
- **`src/agent_trading/services/shadow_bots.py`**
  - `compute_shadow_risk_bot()`에 `rule_set_marker` 키워드 전용
    파라미터 추가(기본값은 기존 `shadow_rule_set:ar_shadow_v1`과 100%
    동일해 기존 shadow 관측 호출은 전혀 영향받지 않음). 본경로 AR bot은
    `deterministic_rule_set:ar_bot_v1`을 넘겨 구분한다.
  - `AR_BOT_RULE_SET_VERSION = "ar_bot_v1"` 상수 추가.
  - **`"reject"` opinion 등급 신설**(score>=0.9) — 기존 allow/review/
    reduce 3단계 임계값(0.5/0.8)은 그대로 유지, 그 위에 한 단계 추가.
  - `round(score, 4)`로 부동소수점 가산 오차 제거(§reject 트리거 설계
    근거 참고) — 이 수정은 shadow 관측 호출과 본경로 호출 양쪽 모두에
    적용되므로, 기존 shadow 관측 데이터도 이제 더 정확한 경계값 판정을
    받는다(값이 실질적으로 달라지는 것은 threshold에 정확히 걸치는
    극히 드문 부동소수점 오차 케이스뿐).
- **`src/agent_trading/runtime/bootstrap.py`**
  - `_build_ai_risk_agent()`의 본문을 EI/AC 전환과 동일한 패턴으로
    교체 — provider 설정 유무와 무관하게 항상
    `DeterministicAIRiskAgent()`를 반환한다.
  - `_build_orchestrator()`의 `ai_risk_agent` 파라미터 타입 힌트를
    `DeterministicAIRiskAgent | None`으로 갱신.
- **`scripts/run_agent_subprocess.py`**
  - `_build_agent_triplet()`에서 AR 슬롯이 provider_client 유무와
    무관하게 항상 `DeterministicAIRiskAgent()`가 되도록 변경. FDC는
    기존 provider/stub 판단을 그대로 유지했다.
- **`decision_agent_runner.py`/`decision_orchestrator.py`는 전혀
  수정하지 않았다** — 구조적 타이핑 덕분에 AR 구현체 교체가 이 두
  파일에 영향을 주지 않는다.

## `size_adjustment_factor` 처리

설계 검토에서 확인한 대로, AR의 `size_adjustment_factor`는 실제
`sizing_engine.py`에 프로그램적으로 연결되지 않는다 — FDC 자신의
`sizing_hint`만 실제 사이징에 쓰이고, AR의 이 값은 FDC 프롬프트의
텍스트 컨텍스트로만 전달된다(`final_decision_composer.py:371`). bot
전환에서도 이 사실을 그대로 반영해 opinion에 연동된 참고용 값만
채우고, 새로운 sizing 연결은 만들지 않았다.

## 실제 policy 영향 여부

**직접적인 주문/차단/수량 로직 변경 없음.** `translation.py`/
`execution_service.py`/`sizing_engine.py`는 전혀 수정하지 않았다.
`risk_check_passed` 컬럼도 새 gate로 연결하지 않았다(여전히
`translation.py`/`execution_service.py` 어디에서도 참조되지 않음,
기존과 동일).

다만 AR 출력의 **품질**이 바뀐다는 점은 policy 관점에서 의미가 있다 —
정형 신호(concentration/cash/regime/event) 기반 판단은 100%
보존되고, 오히려 `"reject"` 등급이 신설되어 극단 위험 신호에 대한
override/skip 커버리지가 이전(LLM AR 시절에도 실측상 매우 드물게만
발동하던 영역)보다 명확해진다. 반면 LLM AR이 텍스트 서술로 포착하던
미묘한 중간 위험 신호(예: 여러 약한 신호의 정성적 종합 판단)는
deterministic 가산식으로 대체되며, 이는 새로운 false positive/false
negative 패턴을 만들 수 있다 — 배포 후 실측이 필요하다.

## EV gate 관련 변경 여부

없음. EV gate 코드/필드를 전혀 건드리지 않았다.

## 실제 영향 경로별 회귀 확인

| 경로 | 확인 방법 | 결과 |
|---|---|---|
| held_position sell override | `tests/services/test_held_position_sell_override.py`(기존, 미변경) — `_check_held_position_sell_override()` 자체를 건드리지 않았으므로 그대로 통과 | **14 passed** |
| FDC skip | `tests/services/ai_agents/test_ar_deterministic.py::test_reject_score_exceeds_fdc_skip_threshold`(신규) — `reject` 등급(>=0.9)이 항상 `_should_skip_final_decision_composer()`의 `risk_score>=0.85` 조건을 만족하는지 확인 | **PASS**(포함된 12건 전체) |
| execution risk-off | `test_ar_deterministic.py::test_non_allow_opinion_and_high_score_trigger_execution_risk_off`(신규) — `review` 이상 등급이 `execution_service.py`의 `risk_opinion!="allow" or risk_score>=0.6` 조건을 만족하는지 확인 | **PASS** |
| FDC prompt input | `tests/services/ai_agents/test_ar_deterministic.py::test_fdc_relevant_fields_all_populated`(신규) — FDC가 참조하는 모든 필드(`risk_opinion`/`risk_score`/`size_adjustment_factor`/`risk_flags`/`reason_codes`/`summary`)가 예외 없이 채워지는지 확인. FDC 코드 자체는 미수정 | **PASS** |

## 수정하지 않은 경로

- EI(`event_interpretation.py`, `DeterministicEventInterpretationAgent`) — PR1에서 이미 완료, 이번 PR에서 재작업 없음.
- AC(`ai_compliance.py`, `DeterministicAIComplianceAgent`) — 기존 그대로.
- FDC(`final_decision_composer.py`) — 미수정, LLM 유지.
- `translation.py`/`execution_service.py`/`sizing_engine.py` — 미수정.
- EV gate 관련 코드/필드 — 미수정.
- `decision_agent_runner.py`/`decision_orchestrator.py` — 미수정(구조적 타이핑으로 wiring 교체가 자동 반영됨).

## 저장/관측 호환성

- `agent_runs.agent_type`은 계속 `"ai_risk"`.
- `agent_runs.structured_output_json.reason_codes`에
  `deterministic_rule_set:ar_bot_v1` 마커가 남아 deterministic 판단임을
  구분할 수 있다.
- `trade_decisions.decision_json`의 기존 key(`risk_opinion`,
  `risk_flags`, `risk_reason_codes`, `risk_check_passed`)는
  `decision_factory.py`를 전혀 바꾸지 않았으므로 그대로 유지된다.
  (`risk_score`/`risk_confidence`/`size_adjustment_factor`가
  `decision_json`에 매핑되지 않는 기존 누락은 이번 PR 범위 밖이라
  손대지 않았다 — 이전 조사에서 이미 확인된 별개의 사전 존재 갭.)
- `decision_json.shadow_risk_bot`(PR #278, 관측 전용)은 이번 PR에서
  건드리지 않았다 — 계속 별도로 기록된다.

## 구현 중 발견·수정한 버그

편집 과정에서 `AIRiskAgent._build_user_prompt()`의 `return "\n".join(
lines)` 문을 실수로 파일 맨 끝으로 밀어내, 이 메서드가 항상 암묵적으로
`None`을 반환하게 만든 것을 `tests/services/ai_agents/test_agents.py`
29건 실패로 발견했다. `git stash`로 대조해 이 실패가 이번 변경 때문임을
확정한 뒤(수정 전 `main`에서는 117건 전부 통과), 정확한 위치로 `return`
문을 복구하고 파일 끝의 orphan 코드를 제거해 해결했다. 최종적으로
`test_agents.py` 117건 전체 재통과를 확인했다.

## 실행한 검증 명령과 결과

| 명령 | 결과 |
| --- | --- |
| `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_ar_deterministic.py`(신규) | 12 passed |
| `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_agents.py` | **117 passed**(버그 수정 후 재확인) |
| `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_bootstrap.py` | 32 passed(AR 관련 assertion 전면 갱신 포함) |
| `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_agent_subprocess.py` | 20 passed(실제 subprocess 스폰 경유) |
| `bash scripts/harness/run.sh test-file tests/services/ai_agents/test_orchestrator_agents.py` | 22 passed |
| `bash scripts/harness/run.sh test-file tests/services/test_decision_orchestrator.py` | 81 passed |
| `bash scripts/harness/run.sh test-file tests/services/test_shadow_bots.py` | 17 passed(`reject` 등급 테스트 2건 추가, 기존 1건 opinion 값 갱신) |
| `bash scripts/harness/run.sh test-file tests/services/test_held_position_sell_override.py` | 14 passed |
| `bash scripts/harness/run.sh test-file tests/services/test_ev_gate_near_miss_override.py` | 14 passed |
| `bash scripts/harness/run.sh accept backend-file src/agent_trading/services/ai_agents/ai_risk.py` | 자동 선택 후보 중 `tests/scripts/test_fdc_skip.py`가 `/workspace` read-only 파일시스템 오류로 실패 — **PR #277/#281에서 이미 확인한 사전 존재 인프라 이슈와 동일**(무관). 실제 관련 테스트(`test_agents.py`, `test_ar_deterministic.py`)는 개별 실행해 0 실패 확인 |
| `bash scripts/harness/run.sh accept backend-runtime` | PASS |
| `bash scripts/harness/run.sh accept script-file scripts/run_agent_subprocess.py` | 자동 선택 후보가 `test_fdc_skip.py` 하나뿐이라 동일한 사전 존재 인프라 이슈로 FAIL — 관련 실제 테스트는 `test_agent_subprocess.py`(20 passed)로 대체 검증 |
| `bash scripts/harness/run.sh accept architecture` / `accept no-bypass` / `accept style` | 전부 PASS |
| `bash scripts/harness/run.sh accept docs` | PASS |

**사전 존재 실패 확인 방법**: `test_fdc_skip.py`의 `/workspace` read-only
오류를 `git stash`로 대조해 이번 변경 전 `main`에서도 동일하게 발생함을
재확인했다(PR #277/#281과 동일 이슈, 이번 PR과 무관).

## 미검증 사항

- 다음 거래일 이후 실제 decision loop 기준 `agent_runs.agent_type=
  'ai_risk'` 기록과 `decision_json.risk_*` 필드 분포.
- `reject` 등급이 실제 운영 데이터에서 얼마나 자주 발동하는지(설계상
  3개 이상 조건 동시 충족이 필요해 드물 것으로 예상되나 실측 필요).
- LLM AR이 텍스트 서술로 포착하던 미묘한 중간 위험 신호를 deterministic
  가산식이 대체했을 때의 false positive/false negative 실제 영향.
- FDC만 LLM으로 남은 구조 전체의 기대수익률/오탐/미탐/지연시간 성과.

## 배포 후 실측 항목

- `agent_runs.agent_type='ai_risk'` 기록이 EI/AC와 함께 정상적으로
  쌓이는지.
- `decision_json.risk_opinion` 분포에서 `"reject"` 값이 처음으로
  나타나는지, 그 빈도가 설계 의도(극단 케이스에 한정)와 일치하는지.
- held_position override/FDC skip/execution risk-off 실제 발동
  빈도가 LLM AR 시절과 비교해 유의미하게 달라지는지.
- `decision_json.shadow_risk_bot`은 이제 "AI vs bot"이 아니라 "bot vs
  bot"이 되므로(§PR3 검토 참고), agreement 필드가 항상 100%로 수렴하는지
  확인해 정리 시점을 판단한다.

## 후속 작업

- PR3: legacy LLM `EventInterpretationAgent`/`AIRiskAgent`/
  `AIComplianceAgent` 정리, `shadow_risk_bot`/`shadow_event_bot` 필드
  정리 — PR1/2 배포 후 관측 기간을 거쳐 결정.
- FDC만 LLM으로 남은 구조의 성과 측정(배포 후 실측 항목 참고).
