# AI Agent vs Deterministic Bot 대체 적합성 분석 (2026-08-16 KST)

## 0. 이 문서의 성격

이 문서는 **read-only 비교 분석 문서**다 — 현재 운영 중인 4개 AI
Agent(`event_interpretation`, `ai_risk`, `ai_compliance`,
`final_decision_composer`) 중 어떤 판단을 deterministic
bot/rule로 대체하는 것이 효율적인지, 어떤 판단은 아직 AI로 유지하거나
추가 실측이 필요한지를 코드·DB·설계 문서 근거로 비교·정리한 것이며,
**구현을 확정하거나 착수하는 문서가 아니다.**

이 조사는 "AI Agent 전체를 deterministic bot으로 바꾼다"는 결론을
전제하지 않는다. 이 시스템의 목표는 차단을 늘리는 것이 아니라
**감내 가능한 손실 제약 아래 기대수익률을 극대화**하는 것이며(공통
판단 원칙, `[PRIORITY_MAP] remaining_work_priority_map.md` 공통
판단 원칙 절, `AGENTS.md` 핵심 작업 원칙), AI 축소 여부를 토큰 절감
효과만으로 판단하지 않는다. 사후 성과, 기회비용, 오탐(false
positive)/미탐(false negative), 지연 시간, 운영 복원력, 관측성을
함께 비교한다.

조사는 코드 조사 서브에이전트, 설계 문서 조사 서브에이전트, 그리고
운영 DB(`trading_db`, 최근 7~9일 표본) narrow `SELECT` 조회를
병행해 수행했다. DB 쓰기, 외부 API 호출, 컨테이너 재기동은 수행하지
않았다.

## 1. 확인 범위

**코드**: `services/decision_agent_runner.py`,
`services/decision_orchestrator.py`, `services/decision_factory.py`,
`services/translation.py`, `services/execution_service.py`,
`runtime/bootstrap.py`,
`services/ai_agents/{event_interpretation,ai_risk,ai_compliance,final_decision_composer}.py`,
`services/subprocess_helpers.py`, `scripts/run_agent_subprocess.py`,
`repositories/postgres/{agent_runs,trade_decisions}.py`,
`domain/entities.py`.

**문서**: `docs/00_foundational_design/detailed_design/08_ai_decision_policy.md`,
`docs/10_signal_research_sppv/[ADVICE] ai_token_optimization.md`,
`docs/20_system_analysis/buy_path_variable_gate_matrix.md`(발췌),
`docs/10_signal_research_sppv/[PLAN] deterministic_compliance_validator_phase1.md`,
`docs/10_signal_research_sppv/[ANALYSIS] var_compliance_guardrail_implementation_path.md`,
`docs/10_signal_research_sppv/[RUNBOOK] ai_compliance_runtime_baseline.md`,
`docs/10_signal_research_sppv/[GUIDE] end_to_end_order_flow_guide.md`,
`docs/10_signal_research_sppv/[PRIORITY_MAP] remaining_work_priority_map.md`(공통
판단 원칙 절 발췌),
`docs/30_work_log/2026-06-05_pre_ai_decision_skip_gate.md`.

**DB**(`trading_db` 운영 컨테이너, `docker exec ... psql`을 통한
narrow `SELECT`만 실행, 쓰기 없음): `agent_runs`(최근 7일
`agent_type`별 건수), `trade_decisions`(최근 7~9일 표본,
`decision_json`, `risk_check_passed`, `compliance_check_passed`),
`order_requests`와의 조인.

## 2. Agent별 현재 실제 역할 매트릭스

| Agent | 새 판단 생성 | deterministic 재확인 | 후속 Agent 입력 | 최종 저장 projection | 주문 생성 영향 | reporting/trace 전용 여부 |
|---|---|---|---|---|---|---|
| `event_interpretation` | 이벤트 해석(사유코드, `event_bias`) | 없음 | AR/FDC 컨텍스트로 전달 | `event_reason_codes` 등 저장 | 간접(FDC 입력 경유). 신규 core BUY + 이벤트 없음 + 무보유 조건에서 자체 스킵(`decision_agent_runner.py:58-78, 238-256`) | 부분적 — 이벤트 없는 core 경로는 스킵되어 영향 없음, 이벤트 있는 경로만 실질 입력 |
| `ai_risk` | `risk_opinion`/`risk_score`/`size_adjustment_factor` | 없음(스킵 로직 없음, `ar_skipped` 항상 `False` 하드코딩 — `decision_agent_runner.py:610`) | FDC 입력 + EV gate 입력(`risk_score`) | `decision_json.risk_opinion`, `risk_check_passed = risk_opinion in {"allow","reduce"}`(`decision_factory.py:155`) | **`risk_check_passed`는 `translation.py`/`execution_service.py` 어디서도 참조되지 않음(grep 전수 확인 0건) → 저장 컬럼일 뿐 실질 주문 차단 효과 없음.** EV게이트 `risk_score` 입력을 통한 간접 영향만 존재 | 아니오(직접 영향 있는 필드가 있으나 그 필드 자체가 gate로 안 쓰임) |
| `ai_compliance` | LLM 호출 시도(서브프로세스 내부에서 실제 실행됨, `run_agent_subprocess.py:1008`) | 없음(설계상 처음부터 authoritative 아님) | 설계상으로는 전달용이나 **실제로는 전달 자체가 안 됨**(아래 §4 참고) | **agent_runs 0건, `compliance_json` 유실 → 기본값(`allow`)으로 대체 저장** | **0** — `compliance_check_passed`는 항상 default `allow`로 채워짐 | 사실상 전무(현재 고장 상태로 인해) |
| `final_decision_composer` | `decision_type`/`confidence`/`conviction`/`entry_style` | 이후 override guard(`_check_ai_buy_override_gate`, `_check_held_position_sell_override` 등, `decision_orchestrator.py:577-758`)가 재확인·override | EV gate 입력(`confidence`, `conviction`) | `decision_json` 핵심 필드 다수, `decision_type` 컬럼 자체 | **직접적** — `decision_type`이 `translation.py`의 1차 필터(APPROVE/BUY/SELL/EXIT/REDUCE만 통과) | 아니오 — 최종 저장·주문 경로에 실질적 영향 |

`deterministic_trigger`, `candidate_vs_final`, `expected_value_gate`,
`ai_call_path`는 4개 AI Agent 중 어느 것의 출력도 아니다. 모두 순수
rule 기반 사전/사후 계산값이며 `decision_json`에 그대로 직렬화된다
(`decision_orchestrator.py:1256-1270`, `decision_factory.py:115-118,
314-382, 495-560`, `decision_agent_runner.py:614-633`). 단
`expected_value_gate`는 FDC의 `confidence`/`conviction`과 AR의
`risk_score`를 입력으로 받으므로 AI와 완전히 독립적이지는 않다.

### 2.1 DB 실측 (최근 7~9일, 4,905건 표본)

- `agent_runs.agent_type`(최근 7일): `ai_risk` 3,650 / `event_interpretation`
  3,650 / `final_decision_composer` 3,650 / **`ai_compliance` 0건**.
- `compliance_check_passed`: 표본 전체 100% `true`, `decision_json.compliance_opinion`도
  100% `"allow"`.
- `risk_check_passed=false` ⟺ `decision_json.risk_opinion="review"`(정확히
  일치, 3,204건). `risk_opinion`은 `allow`/`reduce`/`review` 3값만
  존재하고 `"block"`은 표본에서 한 번도 없음.
- `risk_check_passed=false`인데도 `order_requests`가 생성·`filled`까지
  간 사례 5건 확인(decision_type=`buy` 4건, `approve` 1건).
- `expected_value_gate.passed=false`인 `buy` 결정이 112/125건(약
  90%)이며, 그중 다수가 실제 `order_request`로 이어짐(`buy`: ev_passed=false
  이면서 risk_check_passed=true인 77건 중 4건이 주문으로 이어짐;
  ev_passed=false·risk_check_passed=false인 35건 중 4건도 주문으로
  이어짐).
- `deterministic_trigger.trigger_version="deterministic_trigger_v1"` —
  eligibility/ranking/candidate_set과 다수의 `shadow_*` 실험 필드까지
  포함한 정교한 rule 엔진이 AI 실행 **이전** 단계에서 이미 계산 완료됨.
- `candidate_vs_final.override_applied=true`가 1,213/4,905건(약
  25%) — AI 최종 판단이 deterministic 후보와 다른 경우가 4건 중
  1건꼴로 발생.

## 3. Agent별 bot 대체 적합성 매트릭스

| Agent | rule로 표현 가능성 | 이미 같은 판단을 하는 deterministic guard 존재 | 현재 독립 영향 확인 | 잘못 대체 시 기대수익률 손실 위험 | 저장/감사 개선 여지 | provider 장애·latency·token 비용 개선 |
|---|---|---|---|---|---|---|
| `event_interpretation` | 정형 이벤트(실적발표 코드, 공시 코드 매칭)는 높음, 비정형 뉴스 해석은 낮음 | 부분적 — `recent_events==0` 스킵 조건만 존재 | 간접적(스킵 판단, FDC 입력) | 중간 — 비정형 이벤트 오독 시 기회비용 발생 가능 | 낮음(이미 저장되고 있음) | 있음 — 호출 자체를 더 줄일 여지가 남아 있음(`[ADVICE] ai_token_optimization.md` Phase 2 제안 중 일부만 반영됨) |
| `ai_risk` | 상당수 `reason_codes`(`not_overconcentrated`, `sufficient_cash`, `bullish_trend`)가 정형 수치 비교의 텍스트 재서술로 보임(단, 프롬프트 상세는 이번 조사에서 확인 못함) | 부분적으로 이미 중복 가능성 있음 | **낮음 — 현재 `risk_check_passed`는 주문 생성에 영향 없음** | `risk_score`가 EV gate 입력이므로 대체 시 EV게이트 계산값 자체가 바뀜 → 사후 성과 재검증 필요 | 있음 — 현재 `risk_check_passed`는 사실상 죽은 신호이므로, rule 기반으로 바꾸면 최소한 "의미 있는" true/false를 만들 수 있음 | 있음 — 3,650건/7일 규모로 latency·비용이 큼 |
| `ai_compliance` | **매우 높음** — 문서 자체가 authoritative 차단은 처음부터 deterministic validator 몫으로 설계(§4.2 참고) | **예, 이미 존재** — `deterministic_compliance_validator`가 hard block 담당 | **0 — 버그로 완전히 무효화됨** | 낮음 — 설계상 원래도 non-authoritative였고, 현재도 어차피 영향 0 | **매우 큼** — 지금은 토큰·지연만 소모하고 산출물이 전혀 남지 않음 | **매우 큼** — LLM 호출은 실제로 발생하지만 결과가 통째로 유실됨(§4 참고) |
| `final_decision_composer` | 낮음 — `decision_type`을 직접 결정하는 핵심 레이어, override 25% 구간이 AI 고유 기여분일 가능성 | 없음 — 오히려 FDC 위에 override guard가 얹히는 구조 | **높음(직접적)** | **큼** — 잘못 대체 시 override 25% 구간의 기대수익 기여를 잃을 위험 | 이미 충분(핵심 저장 필드) | 낮음 — 대체 이득보다 손실 위험이 큼 |

## 4. 저장/주문 영향 경로 — 핵심 코드 근거

### 4.1 `translation.py`가 유일한 order_request 게이트

`translation.py:build_submit_order_request_from_decision()`(`47-142`행)이
실제 order_request 생성 여부를 결정하는 **유일한 게이트**다.
`risk_check_passed`/`compliance_check_passed`를 **전혀 참조하지
않는다**(전체 파일 grep 결과 해당 필드 참조 0건). 확인하는 조건은:

1. `decision_type`이 `{APPROVE, BUY, SELL, EXIT, REDUCE}`인지(`77-80`행)
2. `_has_required_expected_value_anchor()`(`82-86, 145-186`행) — 정책
   주석이 명시하듯 "신규매수(APPROVE/BUY)는 `expected_value_gate`
   불통과만으로 submit을 차단하지 않는다"(`153-158`행), `is_new_entry`이면
   EV 게이트 실패 여부와 무관하게 통과시킴
3. `held_position` 상태에서 side≠SELL이면 차단(`95-96`행)
4. `quantity <= 0`이면 차단(`99-100`행)

`ExecutionService`(`execution_service.py`)도 `risk_check_passed`를
참조하는 코드가 없으며, `compliance_check_passed`는 로깅·노출용
projection(`_extract_ai_compliance_projection`, `121-134`행)에만
쓰인다 — 게이트 로직이 아니다.

### 4.2 `ai_compliance`가 agent_runs에 0건인 정확한 원인

`ai_compliance.py`에는 `StubAIComplianceAgent`(기본값 반환)와
`AIComplianceAgent`(`self._provider.generate_structured(...)` 실제
호출) 2종이 있고, `bootstrap.py:_build_ai_compliance_agent()`(`462-491`행)는
다른 3개 Agent와 동일한 패턴으로 provider 설정이 있으면 실제 클래스를
선택한다. **feature flag로 AC만 비활성화하는 코드는 없다.**

운영 기본 경로는 서브프로세스 격리(`AGENT_SUBPROCESS_ISOLATION` 기본값
`"1"`, `decision_orchestrator.py:147-149`)이며, 이 경로에서 두 결함이
겹친다.

1. `scripts/run_agent_subprocess.py:_write_output()`(`1145-1161`행)은
   `AgentSubprocessOutput.compliance_output` 필드(`180, 1126`행에서
   값을 채움에도)를 stdout JSON에 **아예 쓰지 않는다**(`event_output`/`risk_output`/`composer_output`/`error`/`duration_seconds`/`ei_error_metadata`만
   기록).
2. 부모 프로세스의 rehydrate 코드(`decision_orchestrator.py:2180-2195`)는
   EI/AR/FDC 3개(`_ei_run`, `_ar_run`, `_fdc_run`)만 `record()`를
   호출하고, **AC record 호출 자체가 빠져 있다.**

이 두 결함이 겹쳐서, AC의 LLM 호출은 서브프로세스 안에서 실제로
일어나지만(`run_agent_subprocess.py:1008`) 결과가 부모 프로세스로
전달되지 않아 `agent_runs` 기록 시도조차 없고(0건), 부모는
`deserialize_agent_output()`(`subprocess_helpers.py:119-121`)에서
빈 `{}`를 받아 `AIComplianceOutput()` 기본값(`compliance_opinion="allow"`,
`schemas.py:466`)으로 채운다. 이 기본값이 `compliance_check_passed
= (compliance_opinion in {"allow","warn"})`(`decision_factory.py:156`)를
통해 **항상 `true`**로 저장되는 이유다.

### 4.3 `execution_check_passed`는 항상 NULL

`PostgresTradeDecisionRepository.add()`(`repositories/postgres/trade_decisions.py:51,
111`행)가 INSERT 컬럼 목록에는 포함하지만, `TradeDecisionEntity.execution_check_passed`(`domain/entities.py:303`행)
기본값은 `None`이고 저장소 전체에서 이 필드에 값을 대입하는 코드가
단 한 곳도 없다(전수 grep 확인). 항상 NULL — 사실상 죽은 컬럼이다.

### 4.4 설계 문서와의 정합성

`08_ai_decision_policy.md` §4.3(Deterministic Backend Boundary)은
"최종 사칙연산, 점수 합성, 사이징 계산, 한도 검증은 LLM이 아니라
backend math engine이 수행해야 한다"고 명시하고, §4.5/§12.2는 v1
최소 세트(EI/AR/FDC)에서 `ai_compliance`를 후속 단계로 유보했다.
실제 도입 이후에도 `[PLAN] deterministic_compliance_validator_phase1.md`,
`[ANALYSIS] var_compliance_guardrail_implementation_path.md`,
`[RUNBOOK] ai_compliance_runtime_baseline.md` 세 문서 모두
"authoritative 차단은 항상 deterministic validator가 수행하고,
`ai_compliance`는 해석·설명 보조 계층일 뿐"이라는 원칙을 반복
명시한다. 즉 **§4.2의 버그는 설계 의도(non-authoritative)를 벗어난
것은 아니지만, 설계된 "해석·감사 보조" 기능 자체를 완전히
무효화하고 있다는 점에서 여전히 결함**이다.

한편 `[GUIDE] end_to_end_order_flow_guide.md` §8은 "AI가 BUY를
말해도 compliance hard rule 위반이면 실행 안 된다"고 서술하지만,
§4.1에서 확인했듯 코드는 `risk_check_passed`/`compliance_check_passed`
플래그를 애초에 참조하지 않는다. 이 **문서-코드 불일치는 이번
조사에서 확정 판단하지 못했다** — `risk_check_passed`가
`translation.py`에서 참조되지 않는 것이 의도된 정책(신규 BUY는
eligibility/EV만 본다)인지, 설계 누락인지는 §6 미확인 사항으로
남긴다.

## 5. 4분류 (잠정)

### 5.1 즉시 조치 필요 (bot 대체가 아니라 버그 수정 문제)

- **`ai_compliance`**: 서브프로세스 직렬화/rehydrate 누락 버그로
  현재 완전히 무효화된 상태. "AI 유지 vs bot 대체"를 논하기 전에,
  (a) 버그를 고쳐 설계된 해석 보조 역할을 복원하거나, (b) 복원
  비용 대비 실효성이 낮다고 판단되면 호출 자체를 중단해 토큰·지연
  낭비를 없애는 것 중 하나를 먼저 결정해야 한다.
  - 코드 근거: §4.2
  - DB 근거: `agent_runs` 0건, `compliance_check_passed`/`compliance_opinion`
    100% `allow`
  - 문서 근거: §4.4(설계상 원래도 non-authoritative)
  - 미확인: 이 버그가 언제부터 존재했는지, 과거에는 정상 저장되던
    시기가 있었는지는 이번 조사 범위 밖

### 5.2 부분 bot 대체 후보

- **`ai_risk`**: `reason_codes` 상당수가 이미 정형 수치 비교로
  보이므로, concentration/cash/regime 같은 정형 판단은 rule로
  옮기고 비정형 서술(요약문, `opposing_evidence` 텍스트)만 AI로
  남기는 분리가 유력. 단 `risk_score`가 EV gate 입력이므로 교체 전
  EV게이트 재계산 영향을 실측해야 한다.
  - 코드 근거: §2, §4.1(현재 `risk_check_passed` 자체는 주문에
    영향 없음)
  - DB 근거: §2.1(`risk_opinion` 3값 분포)
  - 미확인: `ai_risk.py` 프롬프트/스키마 상세, `size_adjustment_factor`가
    실제 사이징에 반영되는지 여부
- **`event_interpretation`**: 정형 이벤트(실적발표 코드, 공시 코드
  매칭)는 rule 대체 후보, 비정형 뉴스 해석은 AI 유지.
  - 문서 근거: `[ADVICE] ai_token_optimization.md` Phase 1~3,
    `2026-06-05_pre_ai_decision_skip_gate.md`(일부 반영 확인)

### 5.3 추가 실측 필요

- **`final_decision_composer`**: `override_applied` 25% 구간(AI가
  deterministic 후보와 다르게 판단한 구간)의 사후 성과(백테스트)를
  분리 측정해야 AI 고유 기여도를 판단할 수 있다. 이 구간이 기대수익률에
  긍정적이면 AI 유지 근거가 강해지고, 아니면 축소 여지가 생긴다.
  - DB 근거: `candidate_vs_final.override_applied=true` 1,213/4,905건
  - 미확인: override 구간별 사후 실현 손익 비교(이번 턴은 read-only
    조회 범위상 미수행)
- **`risk_check_passed=false`인데 주문이 체결된 경로**(현재 5건
  확인)의 정책 의도 여부 — 의도된 정책(신규 BUY는 risk_check와
  무관하게 EV/eligibility만 본다)인지, risk_check_passed를 gate로
  쓰려던 설계가 누락된 것인지 불명확.
  - 코드 근거: §4.1, §4.4(문서-코드 불일치 가능성)
  - DB 근거: §2.1

### 5.4 AI 유지 필요

- `final_decision_composer`의 비정형 종합판단(전략적합도, 시장상황
  서술, `opposing_evidence` 생성) 자체.
- `event_interpretation`의 비정형 이벤트 해석.
- `ai_compliance`의 설계된 역할(자연어 규정 해석, human-readable
  rationale) — 단, 이는 §5.1 버그 수정 이후에 재판단할 문제.

## 6. 권고

1. **`ai_compliance` 직렬화/rehydrate 버그를 최우선으로 확인·수정할지,
   아니면 호출 자체를 중단할지 결정한다.** 현재는 "AI vs bot" 논의
   자체가 무의미한 상태(둘 다 아닌 유실 상태)이므로 이 결정이 다른
   모든 분류보다 선행돼야 한다.
2. `risk_check_passed`가 `translation.py`에서 전혀 쓰이지 않는 현재
   구조가 의도된 것인지 확인이 필요하다. 의도된 것이라면
   `[GUIDE] end_to_end_order_flow_guide.md` §8을 코드에 맞게
   갱신해야 하고, 의도치 않은 누락이라면 게이트 연결이 필요하다
   (단, 이는 "차단 강화" 방향 변경이므로 사후 성과 검증 없이
   임의로 연결하면 안 된다 — `AGENTS.md` 핵심 작업 원칙과 직결).
3. `ai_risk`의 정형/비정형 판단 분리는 `ai_risk.py` 프롬프트/스키마
   상세 조사를 먼저 수행한 뒤 결정한다.
4. `final_decision_composer` override 25% 구간은 백테스트/사후
   성과 비교 턴을 별도로 진행해 AI 고유 기여도를 실측한 뒤 대체
   여부를 논의한다.

## 7. 미확인 사항

- 운영 환경에서 `AGENT_SUBPROCESS_ISOLATION`의 실제 값(코드
  기본값은 `"1"`이나 배포 env override 여부는 미확인 — 다만 DB
  실측(AC 0건, `compliance_check_passed` 항상 true)이 이 가설과
  정확히 일치함).
- `ai_risk.py`, `event_interpretation.py`,
  `final_decision_composer.py`의 프롬프트/스키마 상세(`ai_compliance.py`만큼
  깊이 조사하지 못함).
- `_check_ai_buy_override_gate` 등 override guard들의 나머지 세부
  로직(파일 뒷부분 약 1,500줄 미독).
- `size_adjustment_factor`(AR 산출)가 실제 주문 수량 계산에 반영되는지
  여부(`target_quantity` 계산 코드 미조사).
- `risk_check_passed`가 `translation.py`에서 미참조되는 것이
  의도된 정책인지 설계 누락인지 — 문서와 코드 사이 불일치 가능성
  존재, 확정 판단 못함.
- `buy_path_variable_gate_matrix.md`(423KB),
  `[PRIORITY_MAP] remaining_work_priority_map.md`(803KB)는 전체가
  아닌 발췌만 확인.
- 이 버그(§4.2)가 도입된 시점, 과거 정상 동작 이력 여부.

## 8. 다음 턴 제안

1. **read-only 실측 턴**: `ai_compliance` 버그의 재현 여부를 실제
   서브프로세스 stdout 로그/최근 배포 이력으로 재확인.
2. 사용자 확인: `risk_check_passed` 미참조 구조가 의도된 것인지
   직접 확인.
3. 위 결과에 따라 (a) 버그 수정(구현 턴) 또는 (b) FDC override
   25% 구간 백테스트(설계 비교 턴) 중 우선순위 결정.
