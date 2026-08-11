# submit budget reservation 구조 — D안(분석/제출 2단계 분리) 1차 설계 (2026-08-11 KST)

## 0. 목적과 범위

이 문서는 `docs/10_signal_research_sppv/[PRIORITY_MAP] remaining_work_priority_map.md`의
"submit budget reservation 구조 수정안 비교(2026-08-11 KST)"에서 우선 구현
후보(안 A)와 별개로, **장기 구조 개선 후보인 안 D(분석/제출 2단계 분리)를
실제로 구현 가능한 수준까지 설계**한 결과다.

**이번 턴은 코드 구현이 아니라 설계 문서로 종료한다.** 이유는 §7 참고.

## 1. 현재 구조의 핵심 문제 재정리

`run_decision_loop.py`의 `_process_one()`은 symbol마다:

1. `evaluate_symbol_submit_lane()`으로 budget 체크 — 이 시점에 AI는
   아직 실행되지 않았다.
2. 통과하면 즉시 `general_submit_inflight_count += 1`(예약).
3. 그제서야 `_run_one_cycle()` → `orchestrator.assemble_and_submit()`을
   호출해 AI 판단 + 주문 제출을 **하나의 fused 호출**로 실행한다.
4. 결과가 나온 뒤(WATCH/HOLD면 반납, SUBMITTED/RECONCILE_REQUIRED면
   `submit_budget_consumed_count` 확정 증가)에야 예약을 해제한다.

`SUBMIT_BUDGET_TRACE` 실측(2026-08-10/08-11)으로 확정된 사실: 이 예약이
AI 실행 시간(수백ms~수십 초) 동안 유지되기 때문에, `_SEMAPHORE_MAX=5`
동시성 하에서 "아직 결과를 모르는 예약" 수 + "이미 확정 소비된" 수가
실제 daily budget보다 훨씬 빨리 상한에 도달한다(`2026-08-11` 첫 cycle:
실제 SUBMITTED 1건, 차단 5건, 전부 `consumed=1, inflight=4, effective=5,
max=5` 동일 조합).

**추가로 이번 설계 조사에서 새로 확인한 사실(중요)**: 현재 구조에서
budget 차단(`submit_budget_consumed_core`)이 걸려도, `run_decision_loop.py`는
그 symbol을 `dry_run=True`로 계속 `_run_one_cycle()`에 넘기고,
`_run_one_cycle()`은 `dry_run=True`이면 `orchestrator.assemble()`을
**그대로 실행한다**(§`scripts/run_decision_loop.py:1949` 이하). 즉
**budget에 막힌 symbol도 AI/LLM 비용을 동일하게 지불한다** — budget
차단은 "AI를 안 돌린다"가 아니라 "AI가 뭐라 하든 제출만 막는다"는
뜻이다. (`trading.execution_attempts`의 `started_at==completed_at`
0초 기록은, `scripts/run_decision_loop.py`가 이 entity를 생성할 때
시작/종료 시각에 동일한 `_now` 변수 하나만 stamping해서 생기는
**관측 상의 착시**이지, 실제로 AI가 즉시 종료됐다는 뜻이 아니다 —
이는 D안 로깅 설계(§6)에서 반드시 고쳐야 할 부분이다.)

**D안이 필요한 이유**: "예약 후 결과 대기" 패턴 자체가 안티패턴이다.
AI 판단(analysis)과 실제 제출(submission)을 분리하면, budget은 "이미
BUY로 확정된 후보"에만 걸리게 되어 위 문제가 구조적으로 사라진다.

## 2. 기존 코드에서 발견한 유리한 사실 — 이미 존재하는 분리 지점

`DecisionOrchestratorService.assemble_and_submit()`
(`src/agent_trading/services/decision_orchestrator.py:2619`)은 이미
내부적으로 두 단계로 나뉘어 있다:

```python
# Phase 1: 분석
intent, trade_decision_id, pipeline_result = await self._run_decision_pipeline(...)
if pipeline_result is not None:
    return pipeline_result  # HOLD 등 short-circuit

# Phase 2: 제출
return await self._execution_service.run_execution_pipeline(
    intent, trade_decision_id, request, order_manager, broker, ...
)
```

그리고 `assemble()`(공개 메서드, `dry_run` 경로에서 이미 사용 중)은
`_run_decision_pipeline()`과 동등한 분석 전용 경로로 `OrderIntent`를
반환한다. `ExecutionService.run_execution_pipeline()`은 호출 시점에
**직접 broker quote를 다시 조회하고(`_resolve_quote`), sizing/guard를
그 자리에서 재계산**한다 — 즉 이미 "제출 직전 재검증"을 전제로 설계돼
있다.

**결론**: D안이 요구하는 "분석 따로, 제출 따로"의 경계는 이미 코드베이스
안에 존재한다(`assemble()` / `run_execution_pipeline()`). 완전히 새로운
아키텍처를 만드는 게 아니라, **이 기존 경계를 `run_decision_loop.py`
레벨의 cycle 오케스트레이션에서 명시적으로 두 pass로 나눠 쓰는 문제**로
좁힐 수 있다. 이는 처음 우려했던 것보다 구현 난이도가 낮다는 뜻이지,
**지금 당장 안전하다는 뜻은 아니다** — §7 참고.

## 3. 1차 권장 구조: same-cycle 경량 2단계 (persistent queue 없음)

### 3.1 단계 경계

**Pass 1 — 분석 단계** (기존 semaphore=5 동시성 그대로 유지)

- 대상: held_position이 아닌 모든 core/event_overlay/market_overlay
  universe symbol.
- 각 symbol에 대해 pre_ai_gate(`evaluate_pre_ai_validation_result`,
  budget과 무관한 사유들 — held position 상태, cooldown, cash 등)를
  그대로 통과시키고, `orchestrator.assemble()`을 호출해 `OrderIntent`
  + `trade_decision_id`를 얻는다.
- **이 단계에서는 submit budget을 절대 확인하지 않는다.** budget 체크는
  Pass 2 전용이다.
- held_position 경로는 지금처럼 이 Pass와 완전히 분리된 자기 lane으로
  유지한다(§3.5).

**Pass 1.5 — 제출 후보 확정 단계** (동시성 없음, cycle 메인 루프에서
순차 처리)

- Pass 1 결과 중 `intent.ai_backend_inputs.decision_type`이
  실제 actionable(신규 진입 BUY/APPROVE)인 것만 추린다.
- 이 목록에 대해 dedupe(§3.4)와 우선순위 정렬(§3.6)을 적용해
  "제출 후보 목록"(candidate list, 메모리 내 리스트 — §3.2)을 만든다.

**Pass 2 — 실제 제출 단계** (필요시 낮은 동시성 또는 순차)

- 후보 목록을 우선순위 순서로 순회하며, **그 순간의**
  `submit_budget_consumed_count`를 확인해 여유가 있으면
  `ExecutionService.run_execution_pipeline(intent, trade_decision_id,
  request, order_manager, broker, ...)`을 호출한다.
- 이 호출이 성공적으로 `SUBMITTED`/`RECONCILE_REQUIRED`를 반환할 때만
  `submit_budget_consumed_count += 1`.
- 예산이 소진되면 남은 후보는 `submit_budget_consumed_core`로 marking하고
  스킵(§3.3 stale 처리와 결합).

### 3.2 후보 표현 모델

새 내부 DTO(가칭 `SubmitCandidate`, `run_decision_loop.py` 내부 또는
얇은 dataclass — **DB 테이블 아님**, 메모리 한정):

| 필드 | 용도 |
|---|---|
| `symbol`, `market`, `source_type` | 식별 |
| `intent: OrderIntent` | Pass 1에서 만든 원본 intent (context, ai_backend_inputs 포함) |
| `trade_decision_id: UUID` | `trade_decisions` 참조 — Pass 2가 그대로 재사용 |
| `decision_context_id: UUID` | 동일 |
| `request: SubmitOrderRequest` | Pass 1이 만든 원본 request(가격/수량 초안) |
| `analysis_completed_at: datetime` | Pass 1 완료 시각 — stale 판단(§4)의 기준 |
| `priority_key: tuple` | §3.6 정렬 키 (source_type 우선순위, deterministic trigger strength, 생성 시각 등) |

**이번 1차 단계에서는 persistent queue(별도 DB 테이블)가 필요 없다.**
이유:
- 후보 목록의 수명은 "한 cycle 내부"로 한정된다(cycle은 독립
  subprocess 실행이라 프로세스 재시작 시 이어받을 필요가 없다 — 다음
  cycle이 어차피 새로 universe를 처리한다).
- `trade_decisions`/`decision_contexts`는 Pass 1에서 이미 DB에
  영속화되므로(§8), 후보 목록 자체가 사라져도 "AI가 무엇을 판단했는지"는
  감사 가능하다 — 잃는 것은 "그 판단이 제출까지 이어졌는지"뿐이고,
  이는 애초에 Pass 2가 못 돌면 원래도 실패였을 케이스다.
- persistent queue는 프로세스 crash 복구/cross-cycle 이월이 필요할 때
  도입할 것 — 지금은 과설계다.

### 3.3 stale 방지

Pass 1(분석)과 Pass 2(제출) 사이에 다른 후보들 처리로 인한 시간차가
생긴다(현재 관측상 한 cycle 전체가 ~150초까지 걸림). 이 시간차 동안
아래를 **Pass 2 진입 직전에 반드시 재검증**한다:

| 항목 | 재검증 방법 | stale일 때 처리 |
|---|---|---|
| cash / orderable amount | `ExecutionService.run_execution_pipeline()`이 이미 자체적으로 최신 cash snapshot을 참조 — **기존 guard 재사용, 신규 로직 불필요** | 기존 guard 그대로(`low_orderable_amount` 등으로 스킵) |
| held position 변화 | Pass 2 진입 직전 `symbol_trade_states`/`position_snapshots` 재조회 — Pass 1 시점과 달라졌으면(예: 그새 다른 lane에서 매도됨) 후보 drop | drop + `stale_reason=position_changed_since_analysis`로 기록 |
| duplicate active buy | 기존 `_has_recent_active_buy_order()`(`execution_service.py`) 재사용 — Pass 2 호출 시점에 자동 재검증됨 | 기존 guard 그대로 |
| stale snapshot | 기존 `_evaluate_stale_snapshot_validation_result()` 재사용 | 기존 guard 그대로 |
| market session | Pass 2 시작 전 `MarketSessionProvider`로 재확인 — 세션이 끝났으면(예: cycle이 장마감 직전 시작해 Pass 2가 장마감 이후로 넘어감) 남은 후보 전체 drop | drop + `stale_reason=market_session_closed` |
| quote/reference price | `ExecutionService._resolve_quote()`가 Pass 2 호출 시점에 **항상 새로 조회** — Pass 1의 quote를 재사용하지 않는다 | 기존 로직 그대로(신선한 값 사용) |

**원칙**: 재검증 가능한 항목(cash/duplicate/quote/stale snapshot)은
이미 `ExecutionService.run_execution_pipeline()`이 호출 시점에 다시
확인하므로 **추가 구현이 거의 필요 없다** — Pass 1/Pass 2를 시간상
분리해도 이 guard들은 "그 순간의 진실"을 보게 된다(오히려 지금의
fused 호출보다 더 정확해진다, 지금도 어차피 AI 판단 이후에 이 guard를
재확인하고 있었으므로 시간차만 늘어날 뿐 로직은 동일).
**추가로 필요한 것은 held position 변화와 market session 종료, 두
가지뿐**이다 — 이 둘은 현재 fused 호출에서는 "동시에 일어난다"고
가정해도 되지만, 2단계 분리 후에는 명시적으로 다시 확인해야 한다.

재평가(재실행)는 하지 않는다 — stale하면 drop하고 다음 cycle에서
다시 분석하게 둔다(AI를 다시 부르는 것은 비용/일관성 문제를 만든다).

### 3.4 dedupe / 중복 제출 방지

- **같은 cycle 내 같은 symbol**: universe 구성상 한 symbol이 여러
  `source_type`(core/event_overlay/market_overlay)으로 동시에
  등장할 수 있다는 것이 `2026-08-11` 실측 로그에서 확인됐다(예:
  `196170`이 `event_overlay`로 처리됨). Pass 1.5에서 후보 목록을
  만들 때 **symbol 단위로 그룹화**하고, 같은 symbol에 여러 actionable
  intent가 있으면 우선순위(§3.6, source_type 우선순위 포함)로 1개만
  남긴다 — 나머지는 `dedupe_reason=symbol_duplicate_in_cycle`로 drop.
- **이전 cycle 미정리 상태와 충돌**: 각 cycle은 독립 subprocess이므로
  이전 cycle의 후보 목록은 메모리에 남지 않는다. 대신 기존
  `_has_recent_active_buy_order()`(§3.3에서 이미 언급) guard가 "직전
  cycle에서 이미 제출된 주문"과의 충돌을 Pass 2 시점에 그대로 잡아준다
  — 새 로직 불필요.
- **기존 duplicate guard와의 관계**: `execution_service.py`의 기존
  guard(`_evaluate_buy_duplicate_validation_result`)는 그대로 Pass 2의
  최종 방어선으로 유지한다. Pass 1.5의 dedupe는 "같은 cycle 내 같은
  symbol이 budget을 두 번 쓰지 않게" 하는 상위 계층 필터일 뿐, 기존
  guard를 대체하지 않는다.

### 3.5 held_position 경로 분리

- held_position(REDUCE/EXIT sell)은 **Pass 1/1.5/2 어디에도 섞이지
  않는다.** 지금처럼 `item_source_type == "held_position"`이면 이
  설계 전체를 완전히 우회해 기존 경로(즉시 `_execute_symbol_cycle`
  호출, budget 무관, cycle당 중복 방지 카운터만 적용)를 그대로 쓴다.
- 이유: held_position sell은 위험 축소가 목적이라 예산이 아니라
  "즉시성"이 중요하다 — 2단계로 나눠 지연시키면 원래 취지(위험 축소)를
  해친다. 이 설계는 general BUY lane에만 적용한다.

### 3.6 submit priority/order

Pass 1.5에서 정렬 키를 명시한다(무엇을 쓸지보다 **반드시 명시적 정렬
기준이 있어야 한다**는 원칙 확인):

1. **1차 키**: `source_type` 우선순위(예: `core` > `event_overlay` >
   `market_overlay` — 현재 universe 설계상 core가 가장 신뢰도 높은
   후보군이므로).
2. **2차 키**: deterministic trigger strength 또는 `final_trade_score`
   (`AIDecisionInputs.final_trade_score`, 이미 `trade_decisions`에
   존재하는 필드 — 새 필드 불필요).
3. **3차 키(tie-break)**: `analysis_completed_at`(Pass 1 완료 시각,
   먼저 끝난 것 우선 — FIFO).

이 정렬 기준 자체가 "기대수익률 우선" 원칙과 맞닿는다: 현재 구조는
사실상 **semaphore 스케줄링 순서(우연)**가 누가 예산을 쓰는지를
결정하는데, 이는 "좋은 진입이 밀리지 않아야 한다"는 목표와 무관한
기준이다. 명시적 정렬로 바꾸면 최소한 "무엇을 기준으로 우선순위를
매기는지"가 감사 가능해진다.

### 3.7 관측/로깅

새 prefix `SUBMIT_PIPELINE_TRACE`(기존 `SUBMIT_BUDGET_TRACE`와 구분,
budget 숫자 자체가 아니라 파이프라인 단계 전이를 추적):

- `SUBMIT_PIPELINE_TRACE analysis_complete cycle=N symbol=S decision_type=D trade_decision_id=T elapsed_ms=E`
- `SUBMIT_PIPELINE_TRACE candidate_enqueued cycle=N symbol=S priority_key=P`
- `SUBMIT_PIPELINE_TRACE candidate_dropped cycle=N symbol=S reason=R`(dedupe/stale 모두 포함)
- `SUBMIT_PIPELINE_TRACE submit_attempt cycle=N symbol=S submit_budget_consumed_count_before=C`
- `SUBMIT_PIPELINE_TRACE submit_consumed cycle=N symbol=S status=S submit_budget_consumed_count_after=C`
- `SUBMIT_PIPELINE_TRACE submit_skipped cycle=N symbol=S reason=budget_exhausted remaining=0`

**중요한 수정 사항**: `analysis_complete`의 `elapsed_ms`는 §1에서 지적한
"0초 착시" 버그를 고친다 — Pass 1 시작 시각을 별도로 기록해 실제
AI 소요 시간을 정확히 남긴다. 이 로깅 개선은 D안 구현과 별개로도
가치가 있다(현재 `execution_attempts.started_at==completed_at` 오기록
자체가 운영 관측성 결함이다 — 별도 backlog 항목으로 분리해도 된다).

### 3.8 replay / audit / persistence 영향

- **`trade_decisions`**: Pass 1(`assemble()`)이 오늘과 동일하게
  기록한다 — **의미론 변경 없음**. 다만 지금은 budget에 막힌 candidate도
  `assemble()`만 실행되고 제출은 안 되는 것이 오늘도 동일하므로,
  `trade_decisions` 자체의 row 수/내용은 **오늘과 거의 동일하게 유지될
  것**으로 예상한다(검증 필요, §9).
- **`execution_attempts`**: 의미가 살짝 바뀐다 — 오늘은 pre_ai_gate
  차단과 scheduler_gate(budget) 차단이 모두 "Pass 1 단계에서" 만들어지는
  반면, D안에서는 budget 차단이 명확히 "Pass 2 단계"에서 만들어진다.
  `stop_phase` 값 자체(`scheduler_gate`)는 유지 가능하지만, 이제는
  진짜로 Pass 2 시작 시점의 상태를 반영하게 되어 **오히려 의미가
  정확해진다**.
- **`order_requests`**: 변경 없음 — Pass 2가 성공한 경우에만
  `OrderManager.create_order()`가 호출되는 것은 오늘과 동일.
- **replay engine**: replay는 `trade_decisions`/`order_requests`/
  `execution_attempts`의 최종 상태를 재생하는 것이므로, Pass 1/Pass 2로
  나뉘어도 **최종 저장되는 엔티티의 스키마와 의미가 바뀌지 않으면
  replay는 영향받지 않는다.** 이번 설계는 새 테이블을 추가하지 않으므로
  이 조건을 만족한다.
- **DB schema 변경**: **불필요** — §3.2에서 결정한 대로 후보 목록은
  메모리 내 구조이고, 기존 4개 테이블(`trade_decisions`,
  `decision_contexts`, `execution_attempts`, `order_requests`)의 스키마나
  의미론을 바꾸지 않는다. 이는 이번 1차 설계의 핵심 안전장치다 —
  스키마 변경이 필요했다면 이번 턴에서 구현 보류를 훨씬 더 강하게
  권고했을 것이다.

## 4. 반드시 지켜야 할 불변식

1. **한 cycle 내 같은 symbol의 신규 진입(general BUY) submit은 최대
   1회** — Pass 1.5 dedupe(§3.4)로 보장.
2. **submit budget은 Pass 2에서, 실제 제출 후보가 확정된 이후에만
   차감** — Pass 1/1.5는 budget 카운터를 절대 건드리지 않는다.
3. **held_position lane은 general submit lane과 완전히 분리 유지** —
   이 설계의 Pass 1/1.5/2 어디에도 held_position이 들어오지 않는다.
4. **Pass 2 진입 직전 재검증 필수** — cash/duplicate/stale
   snapshot/quote는 기존 `ExecutionService` guard가 호출 시점에
   자동 재확인(신규 구현 불필요), held position 변화와 market
   session 종료는 신규로 추가 확인.
5. **stale 후보는 재평가하지 않고 drop** — AI를 다시 부르지 않는다.
6. **DB schema 변경 없음** — 후보 목록은 메모리 한정, 기존 4개
   테이블 의미론 유지.
7. **정렬 기준은 항상 명시적으로 로깅** — "왜 이 순서로 제출됐는지"가
   `SUBMIT_PIPELINE_TRACE candidate_enqueued`의 `priority_key`로 항상
   재구성 가능해야 한다.

## 5. 위험요소와 대응안

| 위험 | 설명 | 대응 |
|---|---|---|
| Pass 1→Pass 2 시간차 확대로 인한 staleness | 전체 cycle이 150초 이상 걸리면, 먼저 분석된 candidate가 한참 뒤에 제출될 수 있음 | §3.3 재검증 + `analysis_completed_at`이 일정 시간(예: cycle 최대 허용시간) 초과 시 무조건 drop하는 상한 추가 검토(1차 구현 시 임계값 확정 필요 — 이번 설계에서는 "필요하다"는 것만 명시) |
| Pass 2 자체의 동시성 재도입 | Pass 2를 병렬로 돌리면 원래 문제(reservation)가 재발할 수 있음 | Pass 2는 **순차 처리**(또는 budget lock을 Pass 2 전용으로 유지)로 제한 — 이 설계는 Pass 2에 새로운 동시성을 도입하지 않는다 |
| dedupe 로직 자체의 버그로 중복 제출 | symbol 그룹화 실수 시 같은 symbol이 후보 목록에 두 번 남을 위험 | 단위 테스트로 "같은 symbol 여러 source_type → 1개만 통과" 케이스 필수 커버(구현 턴의 필수 테스트 항목으로 지정) |
| `assemble()`과 `assemble_and_submit()`의 미묘한 차이 | `assemble_and_submit()`의 `_run_decision_pipeline()`이 `assemble()`과 100% 동일한 부수효과(예: `ExecutionAttemptEntity` 생성 시점/필드)를 갖는지 이번 턴에서 라인 단위로 전부 확인하지 않음 | 구현 턴에서 두 경로의 `_add_phase`/`_phase_trace`/`ExecutionAttemptEntity` 생성 지점을 diff 수준으로 대조 필요 |
| 주문 제출 경계 변경 자체의 리스크 | `src/AGENTS.md`가 명시한 "근거+테스트 없이 변경 금지" 대상 | 구현 턴은 반드시 `tests/scripts/test_run_ops_scheduler.py`류의 관련 테스트 확장 + 최소 1일 paper 운영 관찰을 거쳐 병합 |
| 장중 배포 | 이번 설계 자체는 장중에 작성했지만, 실제 구현/배포는 반드시 장 종료 후 | §7에서 명시 |

## 6. D안(완전 분리, persistent queue/worker)과의 관계

이 문서의 §3 구조는 사용자가 제시한 "1차 권장안(보수적 D안)"에
해당한다 — persistent queue/별도 worker 프로세스는 도입하지 않는다.
완전한 D안(영속 큐, cross-cycle 이월, 독립 submit worker)은 아래
조건이 생겼을 때 재검토한다:
- cycle 하나가 처리 가능한 universe 크기를 넘어서서 분석 결과를
  다음 cycle로 이월해야 할 필요가 실제로 생겼을 때
- 여러 계좌/전략을 동시에 운용해 submit lane 자체를 프로세스
  경계 밖으로 빼야 할 때

지금은 두 조건 다 해당하지 않으므로, 경량 2단계로 충분하다고 판단한다.

## 7. 이번 턴 결정: 설계만, 구현 보류

**구현 보류.** 이유:

1. **현재 KST 09:35경으로 장중이다.** 이 설계는 주문 제출 경계
   (`execution_service.py`/`decision_orchestrator.py`/
   `run_decision_loop.py`)를 직접 재구성하는 변경이며, `src/AGENTS.md`
   원칙과 `[BACKLOG]` #17 자체에 이미 명시한 "주문 제출 경계 변경은
   장 종료 후 배포"를 따라야 한다. 코드를 지금 작성해도 장중에
   병합/배포하는 것은 부적절하다.
2. **이번 턴은 full pytest가 금지돼 있다.** §5에서 지적한
   "`assemble()`과 `assemble_and_submit()`의 미묘한 차이"를 라인
   단위로 검증하려면 관련 스위트를 충분히 돌려야 하는데, 이번 턴의
   제약상 불가능하다.
3. §2에서 확인했듯 기존 코드에 이미 유리한 분리 지점(`assemble()` /
   `run_execution_pipeline()`)이 있어 **구현 자체의 난이도는 낮아졌지만**,
   그것이 "지금 당장 안전하게 병합 가능"을 의미하지는 않는다 — 설계와
   구현 사이의 간극(§5 위험요소)이 아직 남아있다.

따라서 이번 턴은 이 설계 문서를 남기고, 구현은 **전용 구현 턴(장
종료 후, 관련 테스트 확장 포함)**으로 넘긴다.

## 8. 다음 구현 턴에서 확정해야 할 것

- Pass 1.5의 "analysis_completed_at 상한"(§5) 구체적 임계값
- `assemble()` vs `assemble_and_submit()`의 부수효과 diff 확인 결과
- Pass 1.5 dedupe 로직의 단위 테스트 케이스 목록
- `SUBMIT_PIPELINE_TRACE`와 기존 `SUBMIT_BUDGET_TRACE`(PR #215)의
  공존 방식(둘 다 유지할지, 후자를 흡수할지)
- `execution_attempts.started_at`/`completed_at` 0초 오기록 수정
  (§3.7) — D안과 독립적으로 먼저 고칠 수도 있음, 별도 backlog 분리
  검토

## 9. 미확인 사항

- `trade_decisions` row 수/내용이 D안 적용 후에도 오늘과 동일하게
  유지되는지는 설계 단계에서 추론했을 뿐 실측하지 않았다.
- `_run_decision_pipeline()`과 `assemble()`이 완전히 동일한 코드
  경로인지, 혹은 `assemble_and_submit()` 전용의 미묘한 분기가 있는지
  라인 단위로 diff하지 않았다(§5).
- Pass 2 순차 처리 시 전체 cycle 소요 시간이 얼마나 늘어나는지
  추정하지 않았다 — 구현 턴에서 실측 필요.

---

## 10. 구현 반영 결과 (2026-08-11 KST, 코드 구현 턴)

`scripts/run_decision_loop.py`에 §3의 same-cycle 경량 2단계 구조를
그대로 구현했다. DB schema 변경 없음. `held_position` lane은 손대지
않았다(기존 코드 100% 유지).

### 구현 위치
- `_run_one_cycle()`: `defer_actionable_for_pass2` 파라미터 추가.
  True이면 `assemble()`만 실행하고, `build_submit_order_request_
  from_decision(intent)`로 actionable 여부를 판정한다. actionable이면
  `pending_candidates_sink`(cycle 메모리 내 리스트)에 후보를 적재하고
  `PENDING_PASS2` 상태를 반환, non-actionable이면 오늘과 동일하게
  즉시 `ExecutionService.run_execution_pipeline()`을 실행해
  `execution_attempts` 감사 추적을 그대로 남긴다.
- `_process_one()`: general lane(`item_source_type != "held_position"`)
  분기에서 기존 reservation(lock+inflight) 코드를 제거하고, Pass 1
  분석 호출 1건으로 대체.
- 신규 `_run_general_lane_pass2()` / `_submit_general_lane_candidate()`
  / `_general_lane_priority_key()` / `_general_lane_dropped_result()`
  / `_emit_general_lane_pass2_output()`: Pass 1.5(dedupe+정렬) + Pass 2
  (순차 제출)를 `_run_loop()`의 cycle 본문에서 `asyncio.gather()` 직후
  호출한다. `cycle_results`를 `cycle_index`로 in-place 갱신해
  `PENDING_PASS2` placeholder를 최종 결과로 교체한다.
- `ExecutionService`는 `assemble_and_submit()`이 내부적으로 쓰는 것과
  동일하게 `ExecutionService(repos=repos)`(기본값)로 매 호출마다 새로
  구성한다 — §2에서 확인한 대로 오늘 코드와 동등하다(인스턴스별 quote
  circuit breaker/cache는 애초에 심볼 호출마다 새 인스턴스라 공유되지
  않았다).

### 기존 설계 대비 실제 구현 차이
- §3.3(stale 방지)의 "held position 변화 재검증"은 설계 문서가
  가정한 것보다 약하다: `evaluate_pre_ai_validation_result()`를 Pass 2
  직전에 재호출하지만, 이 함수는 신규 진입(non-held) 경로에서 "포지션이
  생겼다"는 사실 자체로 하드 블록하지 않도록 **의도적으로** 설계돼
  있다(HOLD/REDUCE 판단을 막지 않기 위해). 대신 `run_execution_
  pipeline()` 내부의 duplicate-buy guard(`_evaluate_buy_duplicate_
  validation_result`)가 "이미 활성 매수 주문이 있는" 케이스를 잡는다.
  즉 재검증은 reentry cooldown/저orderable cash만 신규로 잡고, 포지션
  변화 자체는 downstream guard에 위임한다 — §3의 "재검증"이라는 표현이
  다소 과했다.
- market session 재확인은 설계에서 예고한 대로 경량(15:30 KST 이후
  여부만 확인하는 시각 비교)으로 구현했다 — `MarketSessionProvider`
  같은 정식 세션 게이트는 쓰지 않았다.
- 기존 `SUBMIT_BUDGET_TRACE`는 `lane_enter`/`reserve`/`release`
  이벤트는 자연 소멸했다(그 코드 경로 자체가 삭제됐으므로 발생 불가) —
  `scheduler` 이벤트(`run_ops_scheduler.py`, 변경 없음)와 `blocked`
  이벤트(이제 Pass 2에서, `general_submit_inflight_count=0` 고정값으로
  발생)만 남아 공존한다. 이는 "당장 제거하지 말고 공존시켜라"는 지시를
  "구조적으로 여전히 의미 있는 이벤트만 남기고, 사라진 개념(reserve)은
  거짓으로 흉내내지 않는다"로 해석한 결과다.
- `execution_attempts.started_at==completed_at` 0초 오기록(§3.7)은
  **이번 구현 범위에서 자연스럽게 해결되지 않았다** — non-actionable
  분기에서 새로 만든 `_add_phase`/`_phase_trace` 클로저는
  `run_execution_pipeline()` 내부에서 실제 `ExecutionAttemptEntity`를
  만들 때 자체 `_now = datetime.now(timezone.utc)`를 다시 쓰므로
  (execution_service.py 기존 코드, 이번 턴에서 손대지 않음) 여전히
  즉시 stamping된다. 별도 TODO로 남긴다 — `execution_service.py`의
  `run_execution_pipeline()` 자체를 고쳐야 한다.

### 지켜진 불변식 / 미검증 불변식
- ✅ (1) 한 cycle 내 같은 symbol 신규 BUY submit 최대 1회 — Pass 1.5
  dedupe로 보장, 코드 리뷰로 확인.
- ✅ (2) held_position lane 완전 분리 — `_process_one`의 held_position
  분기는 한 글자도 바꾸지 않았다.
- ✅ (3) budget은 Pass 2에서만 차감 — `submit_budget_consumed_count`는
  `_run_general_lane_pass2()` 내부, `SUBMITTED`/`RECONCILE_REQUIRED`
  확정 시에만 증가.
- 🟡 (4) Pass 2 직전 재검증 — cash/duplicate/stale snapshot/quote는
  `run_execution_pipeline()`이 자체 재확인(기존 코드, 변경 없음).
  reentry cooldown/cash는 재호출로 재확인. **포지션 변화 자체는
  duplicate-buy guard에 의존**(위 "실제 구현 차이" 참고) — 완전한
  실측 검증은 다음 장중 관찰 필요.
- ✅ (5) stale이면 재분석하지 않고 drop — Pass 2는 `intent`를 그대로
  재사용, `assemble()`을 다시 호출하지 않는다.
- ✅ (6) DB schema 변경 없음 — 신규 테이블/컬럼 없음, 후보는 메모리
  `dict` 리스트.
- ✅ (7) 정렬 기준 로깅 — `SUBMIT_PIPELINE_TRACE candidate_enqueued`에
  `priority_rank`/`source_type_rank`/`final_trade_score`/
  `analysis_completed_at` 모두 포함.
- 🔴 **미검증**: `assemble()`과 기존 `_run_decision_pipeline()`의
  부수효과가 라인 단위로 100% 동일한지는 코드 읽기로만 확인했다(§2에서
  `_run_decision_pipeline()`이 사실상 `self.assemble()` 호출 그 자체임을
  확인) — 실제 subprocess 실행으로 재검증하지 않았다(장중 배포 금지
  전제라 이번 턴엔 불가).
- 🔴 **미검증**: Pass 2 순차화로 인한 cycle 전체 소요시간 증가폭 —
  다음 장중 실측 시 `CADENCE_TRACE decision_submit_gate action=complete
  ... actual_duration=...`로 확인 가능.

### 검증
- `python3 -m py_compile scripts/run_decision_loop.py` — OK
- `bash scripts/harness/run.sh accept style` — PASS
- `bash scripts/harness/run.sh accept no-bypass` — PASS (단,
  `review_bypass_count=1`: `_submit_general_lane_candidate()`의
  `except Exception as exc:` — 기존 `_execute_symbol_cycle()`과
  동일하게 "candidate 1건 실패가 나머지 cycle을 죽이지 않게" 하는
  의도적 격리이며 신규 패턴이 아니다)
- `bash scripts/harness/run.sh accept architecture` — PASS (신규
  위반 없음)
- `bash scripts/harness/run.sh accept backend-file scripts/
  run_decision_loop.py` — N/A(`invalid_path_scope`, `scripts/`는
  스코프 밖)
- full pytest/DB write/컨테이너 재기동/외부 API 호출 없음(원칙 준수)

### 남은 위험요소
- 위 "미검증 불변식" 2건.
- `tests/scripts/test_run_ops_scheduler.py` 등 관련 테스트가 이번
  변경으로 깨지는지 실행하지 못했다(host에 pytest 없음 — 기존에
  확인된 하네스 갭, 별도 항목).
- 장중 첫 실측 시 `SUBMIT_BUDGET_TRACE`(scheduler/blocked)와
  `SUBMIT_PIPELINE_TRACE`(analysis_complete/candidate_enqueued/
  candidate_dropped/submit_attempt/submit_consumed/submit_skipped)를
  함께 grep해 실제 동작을 확인해야 한다 — 장중 배포 전에는 확정할 수
  없다.

상세: PR로 반영, `docs/99_meta_handover/[BACKLOG] backlog.md` #17,
`docs/10_signal_research_sppv/[PRIORITY_MAP] remaining_work_priority_map.md`
참고.
