# EI/AR Deterministic Bot 전환 설계 검토

## 0. 이 문서의 성격

이 문서는 **설계 검토 문서**다 — EI(`event_interpretation`)/AR(`ai_risk`)을
100% deterministic bot으로 전환하기로 이미 결정된 상태에서, "전환할지
말지"가 아니라 **"어떻게 안전하게 설계하고 구현할지"**를 확정하는 것이
목적이다. 이번 턴은 read-only 조사 + 문서 작성만 수행했고 코드/DB
변경은 없다.

## 1. 사용자 결정 (전제)

- EI/AR은 100% deterministic bot으로 전환한다(전환 여부 재논쟁 없음).
- AC(`ai_compliance`)는 PR #277에서 이미 deterministic bot 전환 완료.
- FDC(`final_decision_composer`)는 유지한다 — 이번 전환 대상 아님.
- EV gate 재도입을 전제로 설계하지 않는다(2026-08-07 신규매수 EV gate
  무력화 정책 유지).
- 시스템 목표는 차단 증가가 아니라 감내 가능한 손실 제약 아래
  기대수익률 극대화 — bot 전환도 이 기준으로 평가한다.

## 2. 확인 범위

**코드**: `decision_agent_runner.py`, `decision_orchestrator.py`,
`shadow_bots.py`, `ai_agents/{event_interpretation,ai_risk,
ai_compliance,final_decision_composer}.py`, `ai_agents/schemas.py`,
`subprocess_helpers.py`, `scripts/run_agent_subprocess.py`,
`runtime/bootstrap.py`, `scripts/run_decision_loop.py`,
`docker-compose.yml`, `.env.example`, `decision_factory.py`,
`common_types.py`, 관련 테스트(`test_decision_orchestrator.py`,
`test_shadow_bots.py`, `test_agent_subprocess.py`,
`test_ai_compliance_deterministic.py`, `test_bootstrap.py`).

**DB**(narrow SELECT, 쓰기 없음): 최근 3일 `trade_decisions`의
`decision_json.shadow_risk_bot`/`shadow_event_bot` 적재 여부 —
**결과: 0건, 미적재**(가장 최근 결정이 2026-08-14이고, shadow bot
flag는 2026-08-17 컨테이너 재생성 이후부터 켜졌으나 그 이후 거래일이
아직 없어 새 결정 자체가 생성되지 않았음). agreement 분포는 실측
데이터가 없어 **미확인**으로 남긴다.

## 3. 현재 EI/AR 실행 경로 (코드 근거)

| 단계 | in-process(`decision_agent_runner.py`) | subprocess(`run_agent_subprocess.py`) |
|---|---|---|
| 에이전트 생성 | `bootstrap.py:_build_provider_agent()`(EI, `:394`)/`_build_ai_risk_agent()`(AR, `:426`)가 provider 설정 있으면 real class, 없으면 `None`→orchestrator가 `StubEventInterpretationAgent()`/`StubAIRiskAgent()`로 fallback | `_build_agent_triplet()`(`:225-269`)이 provider_client 유무로 4종 일괄 결정 — EI/AR은 provider 있으면 real class, 없으면 stub. **AC만 예외적으로 항상 `DeterministicAIComplianceAgent()`**(PR #277) |
| 호출 | `decision_agent_runner.py:run_agents()` — EI 먼저(`:238-`, `_should_skip_event_interpretation()` 스킵 조건 있음), AR 다음(스킵 없음, `ar_skipped=False` 하드코딩 `:610`) | `run_agent_subprocess.py`의 `main()` — EI(`:925-955`), AR(`:960-999`) 순차 호출, 각각 `asyncio.wait_for(timeout=_PER_AGENT_TIMEOUT=30)` |
| timeout/fallback | EI: `_build_ei_timeout_fallback()`. AR: `decision_agent_runner.py:381-397` — `except asyncio.TimeoutError`/`except Exception` 둘 다 `AIRiskOutput()` 기본값으로 fallback(EI/AC와 동일 패턴, 확인 완료) | EI: `_build_ei_timeout_fallback()`(`:943-947`). AR: `_build_ar_timeout_fallback()`(`:985-988`) |
| `agent_runs.record()` | in-process: EI/AR 모두 즉시 `record()` 호출(`:363-408` 부근) | subprocess: 호출 안 함 → 부모(`decision_orchestrator.py`)의 `_rehydrate_subprocess_agent_runs()`(PR #277에서 추출, 현재 EI/AR/AC/FDC 4개 모두 기록) |
| `AIDecisionInputs` 조립 | `decision_agent_runner.py` 내부에서 직접 구성(`:570-640` 부근, `event_bias`/`risk_opinion`/`risk_score` 등 매핑) | `subprocess_helpers.py:deserialize_agent_output()`(`:118-160` 부근)가 동일 필드를 매핑 |
| FDC request에 EI/AR 포함 | `AgentExecutionRequest(event_interpretation_output=event_output, ai_risk_output=risk_output, ...)`로 FDC/AC 요청에 그대로 전달 | 동일 구조, `_reconstruct_request()`로 재구성 |
| `decision_json` 저장 | `decision_factory.py:200-218`이 `ai_inputs.event_bias`/`event_conflict`/`event_reason_codes`/`evidence_strength`/`no_material_events`/`detected_event_count`/`interpreted_event_count`/`risk_opinion`/`risk_flags`/`risk_reason_codes`를 그대로 매핑. **`risk_score`/`risk_confidence`/`size_adjustment_factor`는 현재도 decision_json에 매핑되지 않는 기존 누락**(이번 전환과 무관하게 이미 존재하던 갭, §8 참고) |

## 4. EI bot 본경로 설계

### 4.1 클래스/스키마

- 클래스명: `DeterministicEventInterpretationAgent`(`ai_compliance.py`의
  `DeterministicAIComplianceAgent` 명명 컨벤션과 동일).
- 기존 `EventInterpretationOutput`/`AggregateEventView`/`InterpretedEvent`
  dataclass를 **그대로 반환**한다 — 신규 스키마 도입 없음(§7 호환성
  참고).
- `agent_name` 프로퍼티는 **`"event_interpretation"` 유지** — 하위
  API/UI 호환(§6).

### 4.2 입력

`recent_events`(`ExternalEventEntity` tuple), `source_type`, `symbol`,
`market`, `deterministic_trigger`(eligibility 참고용, 선택), 필요시
`market_regime`(추후 확장, 초기 버전에서는 미사용 권장 — 정형 근거가
약함).

### 4.3 출력 필드 채우는 방법

기존 `_reconstruct_events()`(`event_interpretation.py:189-239`)가 이미
**"LLM-only 필드는 절대 조작하지 않고 factual 필드만 채우는" 정확히
같은 원칙**으로 `InterpretedEvent`를 만드는 함수다. EI bot은 이 함수를
그대로 재사용(또는 `shadow_bots.py`로 이식)하면 된다:

| 출력 필드 | 채우는 방법 |
|---|---|
| `detected_event_count` | `len(recent_events)` |
| `interpreted_event_count` | `len(events)` — 정형 재구성 이벤트 수(현재 `_finalize_ei_output()`과 동일 규칙, `interpreted_event_count`는 항상 `len(events)`와 일치) |
| `events[]`(개별 이벤트) | `_reconstruct_events()` 그대로: `impact_direction=ev.direction`(factual), `impact_horizon="swing"`(고정 기본값), `confidence=0.0`, `novelty="medium"`, `supports_entry/exit=False`, `risk_flags=()`, `reason_codes=()`, `summary=headline or body_summary 앞부분`, `is_reconstructed=True` |
| `aggregate_view.overall_bias` | `shadow_bots.compute_shadow_event_bot()`의 direction 다수결 로직 재사용(positive>negative→positive, 반대→negative, 동수→neutral) |
| `aggregate_view.event_conflict` | `positive_count>0 and negative_count>0` |
| `aggregate_view.evidence_strength` | count 기반 weak/moderate/strong + T1 소스 존재 시 한 단계 상향(이미 `compute_shadow_event_bot()`에 구현됨) |
| `aggregate_view.no_material_events` | `len(recent_events)==0` |
| `aggregate_view.top_reason_codes` | `["bot_bias_{bias}", "event_conflict_detected"(해당 시), "t1_source_present"(해당 시), "shadow_rule_set:..." → **"deterministic_rule_set:ei_bot_v1"로 개명(shadow 접두어 제거)**] |
| `stale` (개별 이벤트) | `published_at`/`ingested_at`과 `decision_orchestrator.py`의 기존 `stale_threshold_seconds` 개념을 재사용해 계산 가능(초기 버전은 `stale=False` 고정도 허용 — LLM도 이 필드를 신뢰성 있게 채우지 못했을 가능성이 있어 과도한 정교화보다 관측 후 보강 권장) |

### 4.4 잃는 정보 (비정형 headline/body 해석 제거 시)

- **잃는 것**: 헤드라인/본문 자유 텍스트에서 나오는 뉘앙스(예: "실적
  발표는 긍정적이나 가이던스가 보수적" 같은 복합 판단), `novelty`(신규성)
  판단, `supports_entry`/`supports_exit`의 맥락적 근거, LLM이 여러
  이벤트를 종합해 만드는 `opposing_evidence` 서술.
- **유지되는 것**: `direction`/`severity`/`source_reliability_tier`
  같은 이미 구조화된 필드 기반 판단 — 이 시스템의 EI가 실제로
  "감지"하는 정형 이벤트(공시 코드, 실적 발표 여부 등)의 방향성/신뢰도는
  bot으로도 100% 보존된다.
- **결론**: 비정형 이벤트(뉴스 헤드라인의 뉘앙스, 복합 맥락)의 해석
  품질은 낮아지지만, 이 시스템의 이벤트 소스가 대부분 `direction`
  필드가 이미 채워진 상태로 들어온다는 점(공시/뉴스 어댑터가 소스
  단계에서 이미 방향성을 태깅)을 고려하면 실손실은 제한적일 가능성이
  높다 — 단, 이는 **실측 필요 사항**이지 단정할 수 없다(§10).

### 4.5 FDC 프롬프트 품질 변화

`final_decision_composer.py:328-344`가 참조하는 필드
(`overall_bias`/`event_conflict`/`evidence_strength`/`detected_event_count`/
`no_material_events`/`top_reason_codes`/개별 `events`)는 EI bot도 전부
채우므로 **프롬프트 구조 자체는 깨지지 않는다.** 다만 개별 이벤트의
`summary` 필드가 LLM의 종합 서술 대신 헤드라인 원문 발췌로 바뀌므로,
FDC가 참조하는 이벤트 서술의 "해석 깊이"는 얕아진다. FDC 자체는 여전히
LLM이므로 이 텍스트를 바탕으로 자체 판단을 내리는 능력은 유지된다.

### 4.6 shadow_event_bot 재사용 여부

`compute_shadow_event_bot()`(`shadow_bots.py:170-231`)의 계산 로직을
**그대로 재사용**하되, 반환 타입을 shadow 전용 `ShadowEventBotResult`
dataclass가 아니라 **`EventInterpretationOutput`으로 매핑하는 어댑터
함수를 추가**한다(`_finalize_ei_output()`과 유사한 조립 함수). rule
버전 문자열은 `shadow_rule_set:ei_shadow_v1`이 아니라
`deterministic_rule_set:ei_bot_v1`(신규, 관측용과 본경로용을 문자열로
구분 — 본경로 승격 이후에도 과거 shadow 데이터와 구분 가능하게).

### 4.7 테스트 전략

- 순수 함수 단위 테스트: `compute_shadow_event_bot()`(이미 존재,
  `test_shadow_bots.py`)를 그대로 재사용 + 어댑터 함수용 신규 테스트.
- `DeterministicEventInterpretationAgent.run()` 반환값이
  `EventInterpretationOutput` 계약을 만족하는지(필드 타입, `agent_name`).
- FDC 프롬프트 빌더(`_build_user_prompt`류)가 bot 출력에 대해서도
  `KeyError`/`AttributeError` 없이 동작하는지(`test_fdc_prompt.py` 확장).
- in-process/subprocess 양쪽 wiring 테스트(`test_bootstrap.py`,
  `test_agent_subprocess.py` 패턴 재사용, PR #277과 동일).

## 5. AR bot 본경로 설계

### 5.1 클래스/스키마

- 클래스명: `DeterministicAIRiskAgent`.
- 기존 `AIRiskOutput` dataclass 그대로 반환.
- `agent_name="ai_risk"` 유지.

### 5.2 입력

`portfolio_allocation`, `market_regime`, `deterministic_trigger`,
`recent_events`(이미 `compute_shadow_risk_bot()`이 쓰는 4개, 그대로
유지). `position_snapshot`/`cash_balance_snapshot`/
`risk_limit_snapshot`/`signal_feature_snapshot`은 **현재
`compute_shadow_risk_bot()`이 직접 쓰지 않는다** — `portfolio_allocation`이
이미 이 값들로부터 파생된 집중도/현금 지표를 담고 있어 이중 참조가
불필요하기 때문(관측 턴에서 이미 이렇게 설계함). EI bot output은
AR bot의 입력으로 **직접 연결하지 않는다** — AR bot 자체가 이미
`recent_events`로 event conflict를 독립 계산하므로, EI bot의 결과를
다시 받으면 두 계산이 이중으로 얽혀 원인 추적이 어려워진다(각 bot이
자기 완결적으로 유지되는 것이 감사 관점에서 더 낫다).

### 5.3 출력 채우는 방법

`compute_shadow_risk_bot()`(`shadow_bots.py:82-166`)이 이미
`risk_opinion`/`risk_score`/`reason_codes`/`risk_flags`/`confidence`를
계산한다 — AR bot은 이 결과를 `AIRiskOutput`으로 매핑하는 어댑터만
추가하면 된다. `size_adjustment_factor`는 §5.5 참고. `opposing_evidence`/
`summary`는 `reason_codes`를 한국어 문장으로 조립하는 짧은 결정론적
포맷터를 추가한다(LLM 서술의 자연스러움은 낮아지나 사실 관계는 보존).

### 5.4 AR의 실제 영향 경로 보존 — **가장 중요한 부분**

| 실제 영향 경로 | 현재 트리거 조건 | bot 전환 후 보존 방법 |
|---|---|---|
| `risk_opinion in ("reject","reduce")` → held_position override | `decision_orchestrator.py:401-403` | `compute_shadow_risk_bot()`의 `score>=0.8→"reduce"` 매핑을 그대로 쓰면 이 조건 재현됨. **단, 현재 bot 룰에는 `"reject"`가 없다** — `reject`는 hard breach(예: 즉시 청산 필요) 신호인데 현재 룰셋은 concentration/cash/regime/event 4개 신호의 가산 합만으로 최대 `"reduce"`까지만 도달한다. **완전한 보존을 위해 "reject" 트리거 조건을 명시적으로 추가 설계해야 한다**(예: `remaining_concentration_pct <= -X%`처럼 심각한 초과 시 즉시 `"reject"`) — 이걸 하지 않으면 AR bot은 기존 LLM AR이 드물게 `"reject"`를 내던 극단 케이스를 놓칠 수 있다(§8 리스크). |
| `risk_opinion=="review" and risk_score>=0.8` → held_position override | `decision_orchestrator.py:404-406` | 현재 bot 룰은 `"review"` opinion 자체가 없다(allow/review/reduce 3단계가 아니라 allow/review/reduce로 이미 구현돼 있음 — §5.3 확인 결과 `score>=0.5→review`, `score>=0.8→reduce`이므로 **"review"이면서 score>=0.8인 상태는 도달 불가능**(0.8 이상이면 이미 reduce로 넘어감). 이 특정 트리거는 "reduce" 트리거와 사실상 통합되므로 실질적으로 보존됨 — 단, `_check_held_position_sell_override()`의 `elif` 순서상 opinion이 "review"인 채로 score만 0.8을 넘는 조합이 필요한 게 아니라 "risk_override=True가 되는 조건 중 하나"이므로 실질적 커버리지는 동일하다. |
| `risk_score>=0.8`(opinion 무관) → held_position override | `decision_orchestrator.py:407-409` | bot의 `score>=0.8→"reduce"` 매핑과 사실상 동일 조건이라 자동 보존. |
| `risk_score>=0.85` → FDC skip | `decision_agent_runner.py:101` | bot score 상한이 현재 룰(0.4+0.3+0.2+0.2+0.1=1.2→clamp 1.0)로는 도달 가능하므로 조건 자체는 재현 가능. 다만 LLM AR이 0.85~1.0 사이를 세밀하게 구분하던 것과 달리 bot은 이산적 가산식이라 **score 분포가 0.0/0.1/0.2/.../1.0 근처 특정 값에 몰리는 결과**가 될 수 있다(연속값이 아니라 사실상 이산값) — FDC skip 발동 빈도가 바뀔 수 있음(§10 리스크). |
| `risk_score>=0.6` → execution risk-off(단주 MARKET 차단) | `execution_service.py:415-417` | 동일하게 bot score로 대체 가능, 위와 같은 이산화 리스크 존재. |
| `risk_flags`의 "concent"/"expos"/"over" 포함 → EXIT 승격 | `decision_orchestrator.py:423-425` | bot의 `risk_flags`에 `"concentration_over_limit"`이 이미 포함되므로("concent"/"over" 둘 다 매치) **그대로 보존됨** — 이 부분은 우연히도 이미 정확히 호환. |
| `risk_check_passed` | `decision_factory.py:155`(`risk_opinion in {"allow","reduce"}`) | opinion 값 집합이 동일(`allow/review/reduce`, `reject`는 위에서 추가 설계 필요)하므로 계산식 자체는 변경 불필요. |

### 5.5 `size_adjustment_factor` 처리

관측 턴에서 이미 확인했듯, 현재 AR의 `size_adjustment_factor`는 실제
사이징 계산에 **직접 연결되지 않는다** — `final_decision_composer.py:371`에서
FDC 프롬프트의 텍스트 컨텍스트로만 쓰이고, 실제 `sizing_engine.py`는
FDC 자신의 `sizing_hint`만 사용한다. 따라서 bot 전환 시:

- **권장**: `size_adjustment_factor`는 `risk_opinion`에 연동된 간단한
  결정론적 값(예: `"reduce"→0.5`, `"review"→0.2`, `"allow"→0.0`)으로
  채워 FDC 프롬프트에 텍스트로 계속 노출하되, **실제 사이징에
  영향을 준다고 오인하지 않도록 문서/주석에 "FDC 프롬프트 텍스트
  전용, 프로그램적 연결 없음"을 명시**한다. 새로운 프로그램적 연결을
  만들지 않는다(스코프 확장 금지 원칙).

### 5.6 shadow_risk_bot 그대로 승격 시 부족한 점

- `"reject"` opinion 미도달(§5.4) — 극단 손실 회피 트리거를 놓칠 수
  있음. **PR2 설계에 반드시 포함해야 할 보강 사항.**
- score가 이산적으로 몰리는 문제(§5.4) — 가산식 항목 수가 적어(최대 5개
  불리언 조건) 실제 발생 가능한 score 값이 `{0.0, 0.1, 0.2, 0.3, 0.4,
  0.5, 0.6, 0.7, 0.9, 1.0}` 등 제한된 집합에 그침. LLM AR은 이론상
  연속값(예: 0.42, 0.67)을 냈으나 실제 운영 데이터(이전 턴 실측)에서도
  꽤 이산적인 패턴을 보였으므로 치명적이지는 않으나, **FDC skip/EV
  gate anchor 계산의 민감도가 달라질 수 있어 배포 후 분포 비교가
  필요**하다.
- `opposing_evidence`/`summary`의 자연어 품질 저하(§5.3) — FDC 프롬프트
  가독성에 미치는 영향은 미미할 것으로 예상되나 실측 필요.

### 5.7 테스트 전략

- `compute_shadow_risk_bot()` 단위 테스트(이미 존재) + `"reject"` 트리거
  보강분 신규 테스트.
- **회귀 테스트 최우선 순위**: `test_held_position_sell_override.py`를
  bot 출력으로도 통과시키는 parametrize 확장(AI/bot 두 경로 모두
  같은 override 판정이 나오는지).
- `test_ev_gate_near_miss_override.py`/`test_fdc_skip.py`(FDC skip 조건)
  회귀.
- `execution_service.py`의 risk-off 단주 차단 조건 회귀
  (기존 테스트 파일 확인 필요 — 미확인 사항으로 분리, §11).

## 6. 기존 LLM EI/AR 클래스 처리 — 옵션 비교

| 기준 | A. 유지 + wiring만 교체 | B. legacy/deprecated 표시 후 보존(권장) | C. 삭제 |
|---|---|---|---|
| rollback 가능성 | 높음(코드 그대로) | 높음(코드 그대로, 표시만 추가) | 낮음(재작성 필요) |
| 테스트 영향 | 없음(기존 테스트 그대로 유효) | 없음 | 기존 LLM 전용 테스트 삭제/이관 필요 |
| provider 의존 제거 명확성 | 낮음(코드에 provider 호출 경로가 여전히 존재해 혼동 가능) | 중간(주석/네이밍으로 명시) | 높음(코드 자체가 없음) |
| 코드 유지보수 | 부담 있음(안 쓰는 경로도 계속 관리) | 부담 있음(동일) | 부담 없음 |
| PR 크기 | 작음 | 작음 | 큼(삭제 범위, 관련 테스트 정리) |
| 운영 리스크 | 낮음(문제 시 즉시 원복 가능) | 낮음 | 높음(원복하려면 재작성) |

**권장안(AC 전환 선례와 동일한 보수적 접근)**: **옵션 B** — 기존
`EventInterpretationAgent`/`AIRiskAgent`(LLM) 클래스는 삭제하지 않고
남긴다. `ai_compliance.py`의 `AIComplianceAgent`(LLM)를 PR #277에서
그대로 남긴 선례와 동일하게, `event_interpretation.py`/`ai_risk.py`에
"2026-08-16부터 실행 경로에 wiring하지 않음, 테스트/향후 재검토 목적
보존" 주석을 추가한다. 삭제(옵션 C)는 관측 기간(§9)이 충분히 지나
bot으로 완전히 대체 가능하다는 확신이 선 뒤 별도 PR로 검토한다.

## 7. FDC 입력 호환성 확인

`final_decision_composer.py`가 참조하는 EI/AR 필드
(`ei_output.aggregate_view.*`, `ei_output.detected_event_count`,
`ei_output.events`, `ar_output.risk_opinion`, `ar_output.risk_score`,
`ar_output.size_adjustment_factor`, `ar_output.risk_flags`,
`ar_output.reason_codes`)는 **전부 기존 dataclass 필드 그대로**이므로,
bot이 이 dataclass를 정확히 채우기만 하면 FDC 코드는 **한 줄도 수정할
필요가 없다.** 이것이 "기존 dataclass를 그대로 반환"을 원칙으로 삼은
핵심 이유다.

## 8. agent_type/저장 호환성 결정

- `agent_runs.agent_type`은 **`event_interpretation`/`ai_risk` 그대로
  유지**(PR #277의 `ai_compliance` 선례와 동일 이유 — `api/routes/
  decisions.py`의 `agent_type=="ai_compliance"` 필터처럼 EI/AR도
  유사한 조회 경로가 있을 수 있으므로 이름 변경은 하위 호환을 깬다).
- deterministic 여부 표시 위치: **`reason_codes`에
  `deterministic_rule_set:{ei_bot_v1|ar_bot_v1}` 마커**를 AC 선례와
  동일하게 넣는다. `schema_version`은 `"v1"` 유지(스키마 자체는
  안 바뀌므로), 필요하면 `"v1-deterministic"`처럼 세분화하는 것도
  검토 가능하나 다운스트림 파서가 정확히 `"v1"`을 기대하는 곳이 있는지
  먼저 확인 필요(§11 미확인).
- `decision_json.risk_opinion`/`event_bias`/`event_reason_codes` 등
  기존 key는 **전부 그대로 유지** — `decision_factory.py`의 매핑
  코드를 전혀 바꾸지 않으므로 자동으로 유지된다.
- `shadow_risk_bot`/`shadow_event_bot`: bot이 본경로로 승격된 후에는
  "AI vs bot 비교"라는 원래 목적이 사라지므로(본경로 자체가 bot이 됨),
  **일정 관측 기간(§9) 동안은 유지하되 값이 무의미해짐(AI가 없으므로
  ai_* 필드가 항상 bot과 100% 일치) — PR3에서 정리(중단) 대상**으로
  분류한다.

## 9. subprocess/in-process 정합성 설계

AC 전환(PR #277)에서 확립한 패턴을 그대로 재사용한다:

- `runtime/bootstrap.py`: `_build_provider_agent()`/`_build_ai_risk_agent()`가
  provider 설정과 무관하게 항상 `DeterministicEventInterpretationAgent()`/
  `DeterministicAIRiskAgent()`를 반환하도록 교체(`_build_ai_compliance_agent()`가
  이미 이 패턴).
- `scripts/run_agent_subprocess.py`: `_build_agent_triplet()`에서 EI/AR
  슬롯도 provider_client 유무와 무관하게 결정론적 클래스로 고정
  (AC와 동일하게 4개 모두 결정론적이 됨 — 함수명 `_build_agent_triplet`이
  이제 더 부적절해지므로 **이 시점에 이름을 `_build_agents()`로
  리네임하는 것을 PR2 또는 PR3에서 함께 검토**할 것을 권장(사소하지만
  가독성 개선).
- `decision_agent_runner.py`: EI/AR 생성자 주입 타입이 `ProviderAIAgent`
  프로토콜이므로 별도 코드 변경 불필요(구조적 타이핑).
- provider 호출이 아예 발생하지 않게 하는 방법: bot 클래스의 `run()`
  내부에 `self._provider`/`generate_structured` 호출이 전혀 없으면
  됨(AC bot과 동일 원칙) — 이 부분이 지켜지지 않으면 "결정론적"이라는
  주장 자체가 거짓이 되므로 코드 리뷰에서 반드시 확인해야 할 항목.
- timeout/fallback 경로: **여전히 유지 권장.** bot 계산 자체는
  네트워크 I/O가 없어 사실상 즉시 완료되지만, 예외 방어(런타임 버그로
  인한 무한루프/과도한 재귀 등)에 대비해 `asyncio.wait_for()` 래핑은
  그대로 두는 것이 안전하다(AC 전환 때도 이 wrapper를 제거하지 않았음).
- `agent_runs` rehydrate 4개 기록: 이미 PR #277에서 4개 모두 기록하도록
  고쳤으므로 **추가 변경 불필요** — EI/AR이 bot이 되어도 동일한
  `_rehydrate_subprocess_agent_runs()` 경로를 그대로 통과한다.

## 10. token/latency 절감 효과와 잃는 정보 (종합)

**절감 효과**:
- 토큰 비용: 최근 실측 기준 EI+AR이 7일간 각각 3,650건씩 실행 —
  이 두 Agent의 LLM 호출이 전부 사라지면 AC 전환분(1개 Agent)의
  2배 규모 절감.
- 지연시간: 앞선 dry-run 실측에서 EI 1.19초, AR 1.16초(Gemini 기준) —
  결정론적 계산은 밀리초 단위이므로 decision loop 사이클당 체감
  지연이 크게 줄어든다(EI+AR+FDC 체인의 약 2/3 구간이 사라짐, FDC만
  남으므로).
- 장애 복원력: provider 장애/rate limit/타임아웃이 EI/AR 두 곳에서
  더 이상 발생하지 않음 — 남은 provider 의존은 FDC 하나뿐.

**잃는 정보/기회비용**(토큰 절감만으로 정당화하지 않기 위해 명시):
- EI: 비정형 뉴스/헤드라인의 복합 뉘앙스 해석 능력 상실(§4.4).
- AR: 연속적 risk_score 대신 이산적 가산 점수로 대체 — 미묘한
  중간 위험 신호를 놓칠 false negative 가능성, 반대로 정형 조건
  하나만으로 과도하게 점수가 튀는 false positive 가능성 둘 다
  존재(§5.6). `"reject"` 트리거 미보존은 확인된 리스크(§5.4).
- 관측성: 오히려 **개선** — bot은 매번 같은 입력에 같은 출력을 내므로
  재현 가능하고, `reason_codes`가 실제 계산식을 그대로 드러내
  감사 추적이 LLM 서술보다 명확해진다.
- 기대수익률 영향: **아직 실측 없음.** override/skip 발동 빈도가
  바뀌면 그만큼 진입/청산 타이밍이 바뀌므로 사후 성과 비교(백테스트
  또는 병행 운영 관찰)가 필요 — 이는 bot 전환의 최우선 검증 항목이지
  "토큰이 싸지니 좋다"로 결론 내릴 사안이 아니다.

## 11. 구현 PR 분리안

**EI와 AR을 한 PR로 묶지 않고 분리하는 것을 권장한다** — 근거: (1)
AR의 held_position override/FDC skip/execution risk-off 회귀 테스트
범위가 EI보다 훨씬 크고 리스크가 높다(§5.4의 `"reject"` 트리거 미보존
같은 실질적 동작 변경 가능성이 AR에만 있음), (2) EI 변경 자체는
FDC 프롬프트 텍스트 품질에만 영향을 주고 direct override/skip 트리거가
없어 상대적으로 안전하다, (3) 각 PR을 독립적으로 롤백할 수 있어야
사고 발생 시 원인 격리가 쉽다.

- **PR 1 — EI deterministic 본경로 전환**
  - `DeterministicEventInterpretationAgent` 추가(`_reconstruct_events()`
    재사용, `compute_shadow_event_bot()` 어댑터).
  - `bootstrap.py`/`run_agent_subprocess.py`/wiring 교체.
  - `agent_runs`/`decision_json` 호환 테스트, FDC 프롬프트 회귀 테스트.
  - 문서 반영(`work_log`, `backlog`).
- **PR 2 — AR deterministic 본경로 전환**
  - `DeterministicAIRiskAgent` 추가 + **`"reject"` 트리거 보강 설계**
    (§5.4/5.6 리스크 해소).
  - `bootstrap.py`/`run_agent_subprocess.py`/wiring 교체.
  - held_position override/FDC skip/execution risk-off/EXIT 승격
    회귀 테스트(§5.7).
  - `size_adjustment_factor` 프롬프트 전용 명시 주석 추가.
  - 문서 반영.
- **PR 3 — legacy/shadow 정리**(관측 기간 이후, 별도 착수 시점 결정)
  - LLM EI/AR legacy 클래스 삭제 여부 재검토.
  - `shadow_risk_bot`/`shadow_event_bot` 필드 중단 또는 정리.
  - PR 1/2 배포 후 실측(override/skip 발동 빈도, agreement had-been
    100%인지, 사후 성과) 결과를 근거로 결정.

## 12. 리스크와 완화책 요약

| 리스크 | 완화책 |
|---|---|
| AR `"reject"` opinion 미도달 → 극단 위험 신호 누락 | PR2에서 명시적 reject 트리거 규칙 추가 후 배포 |
| AR score 이산화로 FDC skip/execution risk-off 발동 빈도 변화 | 배포 후 최소 1~2주 발동 빈도를 기존(LLM) 기간과 비교 |
| EI 비정형 이벤트 해석 품질 저하 | 정형 이벤트 비중이 높은 core 경로부터 우선 전환, held_position/event_overlay 등 비정형 의존도가 높은 경로는 배포 후 별도 관찰 |
| `agent_type` 유지로 인해 "AI가 판단했다"는 오인 지속 가능성 | `reason_codes`의 `deterministic_rule_set:*` 마커, `summary` 문구, 이번 문서/backlog에 명시적으로 기록 |
| provider 호출이 실수로 남아있는 경우 "결정론적" 주장이 거짓이 됨 | 코드 리뷰에서 bot 클래스 내부에 `generate_structured`/provider 호출이 전혀 없는지 grep으로 확인하는 것을 accept 체크리스트에 추가 검토 |

## 13. 검증 전략 (요약)

- 순수 함수 단위 테스트(`shadow_bots.py` 확장 또는 어댑터 함수 신규
  테스트).
- 기존 override/skip 회귀 테스트 확장(AI 경로 대신 bot 경로로도
  동일 결과 재현 확인).
- `db-structure`(repository 변경 있을 시), `backend-runtime`(bootstrap
  변경), `architecture`/`style`/`no-bypass`(공통).
- 배포 후 실측: `agent_runs.agent_type`별 건수(EI/AR도 AC처럼
  누락되지 않는지), `decision_json`의 EI/AR 관련 필드가 이산적/정형
  패턴을 보이는지, override/skip 발동 빈도 비교.

## 14. 다음 단계

1. 이 설계 문서에 대한 사용자 피드백 반영(특히 §5.4 `"reject"` 트리거
   보강안, §9 `_build_agent_triplet` 리네임 여부).
2. PR 1(EI) 구현 착수 여부 결정.
3. PR 1 배포 후 실측 → PR 2(AR) 착수.
4. §12의 미확인 사항(아래) 먼저 좁은 코드 조회로 해소.

## 15. 미확인 사항

- `schema_version="v1"` 문자열을 다운스트림 어딘가에서 정확히
  `"v1"`으로 매칭하는 파서가 있는지(있다면 `"v1-deterministic"` 같은
  세분화가 깨질 수 있음).
- `execution_service.py`의 단주 MARKET risk-off 차단 조건에 대한
  기존 회귀 테스트 파일이 무엇인지(이번 턴에서 특정하지 못함).
- 실제 `decision_json.shadow_risk_bot`/`shadow_event_bot` 적재 및
  agreement 분포 — 다음 거래일(2026-08-18) 이후 실측 필요.
- EI bot의 `stale` 필드 계산 방식(고정 `False` vs `stale_threshold_seconds`
  재사용) 최종 결정은 PR1 구현 시점에 확정.
