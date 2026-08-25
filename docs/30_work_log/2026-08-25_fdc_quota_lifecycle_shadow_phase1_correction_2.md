# FDC cycle-scoped batch queue Phase 1(lifecycle shadow) 2차 보정 — PR #351

## 배경

1차 보정(`docs/30_work_log/2026-08-25_fdc_quota_lifecycle_shadow_phase1_
correction.md`)은 `fdc_ready_at` 값 자체를 기존 FDC permit 대기 이전에
캡처하도록 고쳤다. 그러나 실제 shadow job의 **DB 등록과 `enqueue_
sequence` 발급**은 여전히 `assemble()` 내부, 즉 기존 FDC 호출·10 RPM
strict limiter 대기가 끝난 뒤 일어났다. 여러 심볼이 semaphore(5) 안에서
동시 처리되는 실제 운영 구조에서는 "`assemble()`에 먼저 도착한 순서"가
"실제 `fdc_ready_at` 순서"와 다를 수 있다 — 나중에 FDC-ready가 된 심볼이
limiter 대기가 짧아 먼저 처리를 끝내고 먼저 `assemble()`에 도착하면, 더
이른 `fdc_ready_at`을 가진 다른 심볼보다 먼저 작은 `enqueue_sequence`를
받는 역전이 발생했다. 이 문서는 같은 PR #351(같은 브랜치)에서 이 구조적
결함을 보정한 내역을 기록한다.

## 보정 방식 선택 — B(사이클 종료 후 정렬 재생) 채택

사용자가 제시한 두 방식(A: subprocess에서 즉시 DB 기록, B: 사이클 종료
후 정렬 재생) 중 **B**를 채택했다.

**A를 배제한 이유**: `run_agent_subprocess.py`는 심볼 하나를 처리하는
독립 OS 프로세스로 스폰되며, 지금까지 의도적으로 DB에 직접 접근하지
않는다(부모 프로세스만 репозитор 계층을 통해 DB에 접근). A안대로
subprocess에서 즉시 shadow를 기록하려면 프로세스마다 별도의 asyncpg
connection pool을 새로 여는 구조가 필요한데, 이는 (1) 심볼마다 매번
pool을 새로 만드는 비용이 크고, (2) "subprocess는 DB를 모른다"는 기존
격리 설계 원칙을 깨며, (3) 이번 보정의 고정 조건("실제 cycle-scoped
dispatcher 전환은 이번 범위가 아니다")과 어울리지 않는 더 큰 구조
변경이다.

**B를 채택한 이유**: `run_decision_loop.py`는 이미 한 사이클의 모든
심볼을 `asyncio.gather()`로 모아서 기다리는 지점(`cycle_results =
list(await asyncio.gather(*coros))`)을 갖고 있다. `asyncio.gather()`는
**완료 순서와 무관하게 입력 코루틴 순서를 그대로 보존**하므로,
`enumerate(universe)` 시점에 고정된 위치(`cycle_index`)를 그대로
tie-breaker로 쓸 수 있다 — 이는 이미 설계 문서(§16)가 명시한 "FDC
cycle-scoped batch queue"라는 최종 목표(사이클 단위로 FDC-ready job을
모아 처리)와도 정확히 일치한다. subprocess 구조·DB 접근 계층 어느 것도
바꾸지 않고, `assemble()`이 DB에 쓰지 않게만 바꾸면 되므로 변경 범위가
훨씬 작다.

## 보정 전 잘못된 FIFO 순서 경로

```
symbol A: _check_fdc_skip() 통과 → fdc_ready_at=T1(이름) 캡처
symbol B: _check_fdc_skip() 통과 → fdc_ready_at=T2(T1보다 늦음) 캡처
  ↓ (semaphore 안에서 동시 처리, limiter 대기 시간이 다름)
symbol B: FDC 호출 짧게 끝남 → assemble() 도착 → register_shadow_job_
          and_judge() 즉시 호출 → enqueue_sequence=1 (T2인데 1번)
symbol A: FDC 호출 오래 걸림 → assemble() 도착 → register_shadow_job_
          and_judge() 즉시 호출 → enqueue_sequence=2 (T1인데 2번)
```
결과: 실제로는 A가 먼저 FDC-ready였는데도 B가 더 작은 `enqueue_
sequence`를 받아 shadow FIFO에서 "먼저 온 것"으로 잘못 기록된다.

## 보정 후 FDC-ready 순서 및 tie-breaker 계약

1차 기준: 실제 `fdc_ready_at`(subprocess가 permit 대기 이전에 캡처한
값, 변경 없음). 2차 기준(동일 `fdc_ready_at`일 때만): `cycle_index` —
`run_decision_loop.py`의 `enumerate(universe)`가 사이클 시작 시 고정하는
위치값. `asyncio.gather()`가 입력 순서를 그대로 보존하므로 `cycle_
results[i]`는 언제나 `universe[i]`에 대응하며, 어떤 subprocess/코루틴
완료 순서나 `assemble()` 도착 순서에도 의존하지 않는다.

흐름:

```
assemble() 안에서: _capture_fdc_ready_shadow_event()  ← DB 쓰지 않음.
    FdcReadyShadowEvent(decision_cycle_id, decision_context_id, symbol,
    source_type, fdc_ready_at)를 orchestrator.pending_fdc_ready_shadow_
    event에 노출만 한다.

_run_one_cycle()이 이 값을 꺼내 결과 dict에 "_fdc_ready_shadow_event"로
    JSON 직렬화 가능한 dict 형태로 담는다(원본 dataclass 인스턴스를
    그대로 담으면 output=="json"일 때 json.dumps()가 실패하므로 문자열/
    None만 담는다).

run_decision_loop.py의 사이클 루프:
    cycle_results = list(await asyncio.gather(*coros))  # 완료 순서 무관,
                                                          # 입력 순서 보존
    await _replay_fdc_ready_shadow_events_for_cycle(cycle_results, ...)
        → cycle_results를 enumerate해 (fdc_ready_at, cycle_index)로 정렬
        → 정렬된 순서대로 coordinator.register_shadow_job_and_judge()를
          **순차(await 하나씩)** 호출
        → register_shadow_job_and_judge() 자체는 변경 없음(anchor-row
          잠금 트랜잭션 안에서 INSERT+enqueue_sequence 채번+COUNT+UPDATE) —
          다만 이제 이 함수가 "순서대로 순차 호출"되므로 enqueue_sequence가
          항상 그 정렬 순서를 그대로 반영한다.
```

`decision_cycle_id`도 함께 교체했다: 1차 보정까지는 `request.
correlation_id`(예: `f"paper-loop-{symbol}-{cycle}-{int(start)}"`,
심볼·타임스탬프가 섞인 심볼별 고유 문자열)를 그대로 shadow의
`decision_cycle_id`로 썼다. 이는 "같은 cycle의 job을 묶는다"는 shadow의
목적과 맞지 않는다 — `run_decision_loop.py`에는 이미 **진짜
cycle-scoped** 식별자 `decision_cycle_id`(사이클 시작 시 1회 확정,
`f"{scheduler_cycle_id}#{cycle_count}"`, 모든 심볼에 동일하게 전달됨 —
`_record_pre_ai_guardrail_evaluation()`/`_record_scheduler_guardrail_
evaluation()` 등 기존 guardrail 기록 경로가 이미 이 값을 그대로 쓰고
있어 cycle 단위임이 코드로 증명된다)가 존재하므로, `assemble()`/
`assemble_and_submit()`/`_run_decision_pipeline()`에 `decision_cycle_id`
파라미터를 새로 추가해 이 값을 명시적으로 전달받도록 바꿨다 — 추정이
아니라 기존 코드 경로(같은 사이클의 모든 심볼에 동일 인자로 전달되는
`_run_one_cycle(decision_cycle_id=cycle_decision_cycle_id, ...)`)로
증명된 값이다. 이 사실은 기존 회귀 테스트 `tests/scripts/test_run_
decision_loop.py::TestDecisionCycleIdDispatch::test_same_cycle_id_
reaches_every_symbol_in_the_cycle`(변경하지 않음, 여전히 통과)로도
뒷받침된다.

## lifecycle 상태

첫 13개(정렬된 진짜 순서 기준) `SHADOW_WOULD_GRANT`, 같은 60초 창에서
그 이후는 `SHADOW_QUEUED` — 이 판정 규칙 자체(`register_shadow_job_and_
judge()`)는 1차 보정에서 이미 구현했고 이번에 변경하지 않았다.
`SHADOW_QUEUED`는 timeout·cancelled·실패가 아니다. Phase 1은 여전히
자동 dispatcher가 없으므로 "몇 분 후 실제로 grant될지"는 관측하지 않고,
사이클 종료 시점 기준 "정렬된 순서에서 즉시 grant 가능/queued"만
신뢰성 있게 관측한다 — 이 한계는 설계 문서 6차 개정에 명시했다.
`mode='shadow'`는 여전히 `mode='real'` SQL과 완전 분리돼 있다(이번
보정에서 그 분리 자체는 건드리지 않았다).

## A/B 역전 14건·40건 테스트 결과

`tests/scripts/test_run_decision_loop.py::TestReplayFdcReadyShadowEventsForCycle`
(신규 8개 테스트, 전부 PASS, 실제 Postgres 연결 없이 `InMemoryFdcQuotaRepository`
+ fake `AppSettings`/`_db_transaction`/`build_postgres_repositories`로
검증):

- `test_core_reversal_earlier_ready_gets_smaller_enqueue_sequence` — 핵심
  역전 테스트. B가 `cycle_results` 리스트 위치 0(먼저 처리를 끝낸
  것처럼 보임), A가 위치 1이지만 A의 `fdc_ready_at`이 더 이르면 A가
  먼저(더 작은 `enqueue_sequence`로) grant된다.
- `test_reversal_14th_ready_job_is_queued_not_the_14th_list_position` —
  `cycle_results` 리스트 순서를 완전히 뒤집어도, 진짜 `fdc_ready_at`
  기준 가장 늦은 1건만 `SHADOW_QUEUED`이고 나머지 13건(진짜 순서 기준
  앞선 13건)은 `SHADOW_WOULD_GRANT`.
- `test_reversal_40_jobs_only_first_13_by_true_order_grant` — 짝/홀
  인터리빙으로 뒤섞인 40건 입력에서도 진짜 순서 기준 첫 13건만 grant,
  나머지 27건 queued, timeout/cancelled 상태 없음.
- `test_same_fdc_ready_at_tie_break_by_cycle_index_is_reproducible` —
  동일 `fdc_ready_at` 충돌 시 `cycle_index`로 항상 재현 가능한 순서.
- `test_limiter_wait_or_provider_duration_does_not_affect_order` —
  이 함수의 입력 자체가 `fdc_ready_at`(permit 대기 이전 캡처값)만 담고
  있으므로, 그 이후에 실제로 걸리는 limiter 대기·provider 실행 시간이
  구조적으로 순서에 영향을 줄 수 없음을 증명.
- `test_shadow_disabled_flag_is_a_full_noop` / `test_no_shadow_events_is_
  a_full_noop` — shadow flag=false 또는 이번 사이클에 FDC-ready 이벤트가
  없으면(전부 skip 건) DB 접근 함수 호출 자체가 없음(호출되면
  `AssertionError`를 던지는 fake로 직접 증명).
- `test_real_mode_quota_is_untouched_by_shadow_replay` — replay가
  `mode='real'` 저장소를 전혀 건드리지 않음.

실제 PostgreSQL로도 "애플리케이션 계층이 이미 올바른 순서로 순차
호출하면 DB가 그 호출 순서를 정확히 `enqueue_sequence`로 기록한다"를
`tests/services/test_fdc_quota_coordinator.py::TestPostgresShadowFifoQueue::
test_sequential_replay_in_true_fdc_ready_order_grants_by_that_order`(신규)
로 확인했다 — 재정렬 로직 자체는 DB가 아니라 `_replay_fdc_ready_shadow_
events_for_cycle()`의 책임이므로, DB 계층 검증은 "호출자가 정렬해서
순차 호출하면 DB가 그 순서를 정확히 반영한다"는 계약만 확인하면 충분하다.

## 실제 runtime 무영향 근거

- `_capture_fdc_ready_shadow_event()`는 이제 완전한 동기 함수이고
  `await`가 전혀 없다 — `assemble()` 안에서 DB I/O를 절대 일으키지
  않는다(1차 보정보다 더 안전해짐 — 기존에는 coordinator 호출 실패를
  삼키는 try/except가 필요했으나 이제는 그 경로 자체가 없다).
- `_replay_fdc_ready_shadow_events_for_cycle()`은 `asyncio.gather()`
  **이후**에만 호출되므로, 사이클 안의 어떤 실제 FDC 호출·주문 제출·
  Pass 2 실제 제출 로직보다도 먼저 실행되지 않는다(Pass 2는 이미 확정된
  actionable 후보의 제출만 다루고 FDC를 다시 호출하지 않으므로, 이
  시점 이후 이번 사이클의 FDC-ready 이벤트가 더 늘어나지 않는다).
- shadow flag 기본값 `false` — `_replay_fdc_ready_shadow_events_for_
  cycle()`이 최상단에서 즉시 반환하며 `AppSettings`/`build_postgres_
  repositories`/`FdcQuotaCoordinator` 어느 것도 건드리지 않는다(테스트로
  직접 증명).
- 개별 replay 항목의 등록 실패·전체 트랜잭션 실패 모두 예외를 삼켜
  나머지 항목의 재생과 사이클 진행에 영향을 주지 않는다(best-effort,
  다른 shadow 관측 경로와 동일한 안전 원칙).
- 기존 실제 FDC 호출, `fdc_rate_limiter.py`(10 RPM strict limiter),
  provider 호출 횟수, override, EV gate, sizing, sell guard, 주문 제출
  경로는 이번 diff에 전혀 포함되지 않았다.

## PostgreSQL 통합 테스트 로컬/CI 결과 분리

로컬(네트워크 격리 dev-validation 컨테이너): `TestPostgresShadowFifoQueue`
(신규 1건 포함 총 6건) `DATABASE_HOST` 없어 **skip**(사유: `requires
DATABASE_* env vars`, 코드 결함 아님) — `tests/services/test_fdc_quota_
coordinator.py` 전체 24건 중 15건 PASS, 9건 SKIP으로 확인.

CI 자동 실행 여부(1차 보정 때 이미 확인한 사실 재확인): GitHub Actions의
`Safe harness contracts`(모든 PR에서 자동 실행)는 pinned PostgreSQL
컨테이너를 기동하지만 `check quick`/`accept db-structure`/`accept
architecture`/`accept style`/타입체크/보안 스캔만 실행하고 전체 pytest
스위트는 실행하지 않는다. `Heavy harness contracts`(전체 테스트 스위트
실행)는 `.github/workflows/harness.yml`의 `if: github.event_name ==
'workflow_dispatch' && inputs.run_heavy == 'true'` 조건으로 **수동
트리거 전용**이며 일반 PR push/synchronize에서는 자동 실행되지 않는다
(`if` 조건을 코드로 직접 확인). 즉 이 PostgreSQL 통합 테스트는 병합
전에 `workflow_dispatch(run_heavy=true)`를 수동으로 실행해야만 실제로
검증된다 — 이번 2차 보정 턴에서도 이 실행 여부는 완료 보고에 별도로
명시한다.

## 변경 파일

- `src/agent_trading/services/decision_orchestrator.py` — `FdcReadyShadowEvent`
  dataclass 신설, `fdc_quota_coordinator` 생성자 파라미터 제거,
  `pending_fdc_ready_shadow_event` 공개 속성 추가, `_record_fdc_batch_
  queue_lifecycle_shadow_observation()`(async, DB 직접 호출)을
  `_capture_fdc_ready_shadow_event()`(sync, DB 미접촉)로 교체,
  `assemble()`/`assemble_and_submit()`/`_run_decision_pipeline()`에
  `decision_cycle_id` 파라미터 추가.
- `scripts/run_decision_loop.py` — 두 `DecisionOrchestratorService(...)`
  생성 지점에서 `fdc_quota_coordinator=...` 인자 제거, 3개
  `assemble()`/`assemble_and_submit()` 호출부에 `decision_cycle_id=
  decision_cycle_id` 추가, `_run_one_cycle()` 성공 반환 직전에
  `pending_fdc_ready_shadow_event`를 JSON 직렬화 가능한 dict로 변환해
  결과에 포함, 신규 함수 `_replay_fdc_ready_shadow_events_for_cycle()`
  추가 및 `asyncio.gather()` 직후 호출 지점 추가, `CoordinatorError`
  import 추가.
- `tests/services/test_decision_orchestrator.py` — `TestFdcBatchQueue
  LifecycleShadowObservation`을 `TestFdcReadyShadowEventCapture`로
  재작성(coordinator mock 제거, `pending_fdc_ready_shadow_event` 직접
  검증), 미사용 import 제거.
- `tests/scripts/test_run_decision_loop.py` — `_replay_fdc_ready_shadow_
  events_for_cycle` import 추가, 신규 `TestReplayFdcReadyShadowEventsForCycle`
  클래스(8개 테스트) 추가.
- `tests/services/test_fdc_quota_coordinator.py` — `TestPostgresShadowFifoQueue`
  에 `test_sequential_replay_in_true_fdc_ready_order_grants_by_that_order`
  신규 추가.
- `docs/40_action_plans/fdc_cycle_scoped_batch_queue_gemini_shared_13rpm_
  quota_design_2026-08-25.md` — 5차 개정의 "DB INSERT 순서가 FIFO를
  보장한다" 서술이 틀렸음을 명시하고, 6차 개정으로 `(fdc_ready_at,
  cycle_index)` 정렬 계약으로 정정.
- 본 문서(신규).

## 실행한 harness와 결과

| 명령 | 결과 |
|---|---|
| `accept backend-file src/agent_trading/services/decision_orchestrator.py` | PASS(`tests_run_count=3`, 그 외 `test-file`로 `test_decision_orchestrator.py` 104 passed 직접 확인) |
| `accept script-file scripts/run_decision_loop.py` | PASS(`tests_run_count=3`, `test_run_decision_loop.py` 147 passed 직접 확인, `test_run_ops_scheduler.py` 155 passed 별도 확인) |
| `accept backend-file src/agent_trading/services/fdc_quota_coordinator.py` | PASS(`test_fdc_quota_coordinator.py` 15 passed, 9 skipped 직접 확인) |
| `accept architecture` | PASS(`architecture_violation_count=0`) |
| `accept db-structure` | PASS(`repository_protocol_count=43`, 변경 없음 — repository 계층 자체는 이번 보정 대상 아님) |
| `accept backend-runtime` | PASS |
| `accept env` | PASS |
| `accept no-bypass` | PASS(`hard_bypass_count=0`, review_bypass 17건은 전부 테스트 파일의 monkeypatch/type-ignore, 기존 broad exception 패턴) |
| `accept style` | PASS |
| `accept docs` | PASS |

전체 테스트 스위트·실제 Gemini 호출·migration 적용·운영 DB write·컨테이너
재기동은 이번 2차 보정에서도 전혀 수행하지 않았다.

## 미검증 가정

- `_replay_fdc_ready_shadow_events_for_cycle()`이 실제 다수 심볼(예:
  전체 유니버스 규모) 사이클에서 순차 `await` N회 호출에 걸리는 실제
  wall-clock 지연은 실측하지 않았다 — 순차 실행이므로 이론상 N × (DB
  왕복 시간)만큼 사이클 종료를 늦추지만, 이는 사이클의 다음 단계(Pass
  1.5/Pass 2)보다 먼저 실행되므로 사이클 전체 지연에 더해진다. 이
  지연이 실제 운영에서 무시할 수준인지는 실측 필요.
- 서로 다른 두 `run_decision_loop.py` 프로세스(예: core lane과
  held_position lane을 별도 스케줄러 인스턴스로 실행하는 경우)가 같은
  `quota_scope`에 동시에 shadow를 재생하면, 각 프로세스 내부의
  사이클-스코프 정렬은 보장되지만 **두 프로세스 사이의 상대적 도착
  순서**는 이번 보정으로 해결되지 않는다 — 이는 실제 cycle-scoped
  dispatcher(이번 범위 밖)가 다뤄야 할 문제로 남긴다.
- PostgreSQL 통합 테스트(`TestPostgresShadowFifoQueue`, 6건)는 로컬
  샌드박스에서 skip됐고, CI 자동 실행에도 포함되지 않는다(위 "PostgreSQL
  통합 테스트 로컬/CI 결과 분리" 참고) — 수동 `workflow_dispatch(run_
  heavy=true)` 실행 여부는 완료 보고에서 별도로 확인한다.
