# FDC cycle-scoped batch queue Phase 1(lifecycle shadow) 보정 — PR #351

## 배경

PR #351(Phase 1 lifecycle shadow 초기 구현)에 두 가지 핵심 결함이
발견됐다. 이 문서는 같은 PR #351을 병합하지 않은 채, 같은 브랜치에서
보정한 내역을 기록한다.

## 결함 1 — shadow 판정이 항상 `SHADOW_WOULD_GRANT`가 되는 결함

초기 구현의 `judge_shadow_reservation()`은 `mode='real'` attempt 수를
세어 window_count를 계산했다. 그러나 Phase 1은 실제 reservation
(`try_reserve()`)을 런타임에서 전혀 호출하지 않고 `mode='shadow'` 행만
기록하므로, `mode='real'` 카운트는 항상 0이었다 — 즉 shadow를 켜도
모든 FDC-ready job이 예외 없이 `SHADOW_WOULD_GRANT`로 기록됐다.

**보정**: 판정 쿼리가 오직 같은 `quota_scope`의 `mode='shadow'` 행만
보도록 변경했다(`mode='real'` 행은 절대 조회하지 않음). `try_reserve()`
(`mode='real'` 전용, 실제 quota 소비 경로)와 완전히 분리된 코드 경로다.

## 결함 2 — shadow 관측 시점이 기존 FDC permit 대기 이후였던 결함

초기 구현은 `decision_orchestrator.py::assemble()` 내부, 기존 FDC 호출·
strict limiter 대기·`trade_decisions` 저장 **뒤**에 shadow를 기록했다.
이 시점은 실제 FDC-ready 시점이 아니므로 13 RPM 가상 큐의 도착 순서·
대기 여부를 재현할 수 없었다.

**보정**: `fdc_ready_at` 캡처를 subprocess 경계 안(`run_agent_subprocess.
py`, `_check_fdc_skip()` 반환 직후·permit 대기/HTTP 호출 시작 직전)으로
이동했다. `AgentSubprocessOutput.fdc_ready_at`(ISO-8601 문자열, skip 시
빈 문자열)로 직렬화 → `subprocess_helpers.py::deserialize_agent_output()`
→ `AIDecisionInputs.fdc_ready_at` → `decision_orchestrator.py`가 이 값을
파싱해 shadow 등록에 사용한다. in-process 경로(`decision_agent_runner.
py::run_agents()`)도 동일하게 캡처하도록 대칭 반영했다(운영은 항상
subprocess 경로를 쓴다).

pre-FDC/FDC 완전 분리 dispatcher는 이번 보정 범위 밖이다 — 기존
subprocess 경계를 유지한 채 관측 시점만 옮겼다.

## shadow FIFO/window 산정 규칙과 real/shadow 분리 근거

`register_shadow_job_and_judge()`(신규, `create_shadow_job()`+`judge_
shadow_reservation()`를 대체하는 단일 원자적 메서드)의 계약:

1. 같은 `fdc_quota_state` singleton anchor 행을 `SELECT ... FOR UPDATE`로
   잠근 채 하나의 트랜잭션 안에서 (a) `fdc_queue_jobs`에 `mode='shadow'`
   행을 INSERT하고 `enqueue_sequence`(`BIGSERIAL`, DB 발급)를 `RETURNING`
   으로 받는다, (b) 같은 `quota_scope`의 `mode='shadow'` 행 중
   `enqueue_sequence < 이번 값` 이고 `status='SHADOW_WOULD_GRANT'`이고
   `fdc_ready_at`이 `(이번 fdc_ready_at - 60초, 이번 fdc_ready_at]`
   반열림 구간에 있는 것만 센다, (c) 그 수가 `target_rpm`(13) 미만이면
   `SHADOW_WOULD_GRANT`, 아니면 `SHADOW_QUEUED`로 갱신한다.
2. `enqueue_sequence`를 FIFO 키로 쓰는 이유: 동시 subprocess 여러 개가
   비동기로 완료되는 순서는 신뢰할 수 없지만(Python task 완료 순서 ≠
   실제 도착 순서), 같은 anchor 잠금 트랜잭션 안에서 INSERT + 채번이
   원자적으로 일어나므로 `enqueue_sequence`는 항상 진짜 DB 직렬화 순서를
   반영한다 — 사용자가 명시한 "DB insertion 순서 또는 DB 발급 monotonic
   sequence" 요구사항을 그대로 만족한다.
3. real/shadow 분리: `mode='real'` 행을 세는 쿼리(`try_reserve()`)와
   `mode='shadow'` 행을 세는 쿼리(`register_shadow_job_and_judge()`)는
   `WHERE mode = ...` 조건이 다른 별개 쿼리이며, 두 경로 모두 상대
   `mode`의 attempt/job 행을 전혀 읽지 않는다 — 테스트로 직접 확인
   (`test_shadow_does_not_consume_or_read_real_quota`, `test_shadow_rows_
   tagged_shadow_mode`).
4. 상태명은 `SHADOW_WOULD_GRANT`/`SHADOW_QUEUED`로 실제 상태(`GRANTED`/
   `DENIED`)와 혼동되지 않게 분리했다. `SHADOW_QUEUED`는 실패·timeout이
   아니다 — 순번상 아직 승인되지 않았다는 관측값일 뿐이며, queue rank로
   인한 자동 timeout/cancelled 처리는 하지 않는다(Phase 1은 dispatcher가
   없으므로 애초에 그런 처리를 할 수 없다).

## 13/14/40건 테스트 결과

`tests/services/test_fdc_quota_coordinator.py::TestShadowFifoQueueLogic`
(fake clock/injectable timestamp, 실제 sleep·Gemini·운영 DB write 없음,
in-memory repository 대상 15개 테스트 전부 PASS):

- `test_13_same_instant_jobs_all_would_grant` — 같은 시각 13건 전부
  `SHADOW_WOULD_GRANT`.
- `test_14th_same_instant_job_is_queued` — 14번째는 `SHADOW_QUEUED`.
- `test_40_concurrent_jobs_only_first_13_grant_no_timeout_state` — 40건
  동시 진입 시 `enqueue_sequence` 순으로 처음 13건만 grant, 나머지 27건은
  전부 `SHADOW_QUEUED`, `CANCELLED`/timeout 상태 없음.
- `test_fifo_no_queue_jumping` — 앞선 job이 queued인데 뒤 job이 먼저
  grant되지 않음(양쪽 job_id를 직접 조회해 순서 위반 없음을 확인).
- `test_exactly_60_seconds_old_shadow_grant_excluded` — 정확히 60초 전
  shadow grant는 `(t-60, t]` 반열림 구간에서 제외됨(경계값 직접 검증).
- `test_shadow_does_not_consume_or_read_real_quota` /
  `test_shadow_rows_tagged_shadow_mode` — `mode='real'`/`mode='shadow'`
  상호 무간섭.

동일 계약을 실제 PostgreSQL로 검증하는 `TestPostgresShadowFifoQueue`
(5개 테스트, `DATABASE_HOST` 없으면 skip)도 같은 파일에 추가했다.

## 기존 runtime 무영향 근거

- `FDC_BATCH_QUEUE_LIFECYCLE_SHADOW_ENABLED` 기본값 `false` —
  `_record_fdc_batch_queue_lifecycle_shadow_observation()`이 최상단에서
  즉시 반환하며 coordinator/repository를 전혀 건드리지 않는다(회귀
  테스트로 확인, `tests/services/test_decision_orchestrator.py`).
- `fdc_ready_at`이 빈 문자열("", FDC skip 시)이거나 `datetime.fromisoformat()`
  파싱에 실패하면 즉시 반환 — skip 건은 shadow 대상에서 제외된다
  (`test_empty_fdc_ready_at_is_a_noop`, `test_invalid_fdc_ready_at_is_a_noop`).
- `try_reserve()`(`mode='real'` 실제 quota 소비 경로)는 이번 보정에서도
  런타임 호출 경로에 전혀 연결되지 않았다 — 단위/통합 테스트 전용.
- 기존 `fdc_rate_limiter.py`(10 RPM strict limiter), `provider_client.py`
  retry, EI/AR/AC, held_position override, EV gate, sizing, sell guard,
  주문 제출 경로는 이번 diff에 포함되지 않았다.

### shadow 등록 시점이 기존 FDC permit 대기 이전임을 증명하는 테스트

`tests/scripts/test_fdc_skip.py::TestFdcReadyAtCapturedBeforePermitWait`
(신규):

- `test_fdc_ready_at_capture_precedes_agent_run_entry` — 실제 프로덕션
  함수 `_check_fdc_skip()`과 `_run_fdc_with_outer_timeout()`을 그대로
  호출한다. `fdc_ready_at` 캡처 표현식(운영 코드와 동일한 식)의 결과
  시각이, FDC agent의 `run()`(=permit 대기·HTTP 호출 시작점) 진입 시각을
  기록하는 witness agent보다 항상 이전임을 직접 비교로 증명한다 —
  두 시점 사이에 `await`가 없는 순수 동기 코드만 있다는 실제 코드 구조에
  의존하므로, Python task 완료 순서가 아니라 코드 경로의 순차 실행
  순서 자체를 검증한다.
- `test_skip_path_never_captures_fdc_ready_at` — skip 판정이면
  `fdc_ready_at`이 항상 빈 문자열임을 확인(skip 건은 shadow 대상 제외).

## PostgreSQL 통합 테스트 실행/skip/CI 분리

로컬 dev-validation 컨테이너는 `network_mode=none`이라 `DATABASE_HOST`가
없어 `TestPostgresShadowFifoQueue`(5건)와 기존 `TestPostgresAtomicReservation`
계열은 전부 **skip**됐다(사유: `requires DATABASE_* env vars`, 코드
결함 아님). CI의 "Safe harness contracts" job은 pinned PostgreSQL
컨테이너를 기동하고 `DATABASE_HOST`를 설정하므로 그 단계에서 실제
실행된다 — PR #351의 CI 결과로 확인 필요(로컬에서는 실행 자체가 불가능한
환경 제약).

## 변경 파일

- `db/migrations/0068_add_fdc_quota_lifecycle_tables.sql`(amend —
  `quota_scope`/`fdc_ready_at`/`enqueue_sequence` 컬럼 + shadow FIFO
  인덱스 추가, 여전히 미적용)
- `src/agent_trading/services/common_types.py`(`AIDecisionInputs.fdc_
  ready_at` 필드 추가)
- `scripts/run_agent_subprocess.py`(`fdc_ready_at` 캡처 + `AgentSubprocessOutput`
  필드 추가)
- `src/agent_trading/services/subprocess_helpers.py`(역직렬화)
- `src/agent_trading/services/decision_agent_runner.py`(in-process 경로
  대칭 반영)
- `src/agent_trading/repositories/contracts.py`(`register_shadow_job_and_
  judge()` Protocol로 교체, `ShadowJudgement`에 `job_id`/`enqueue_sequence`
  추가)
- `src/agent_trading/repositories/postgres/fdc_quota.py`(신규 원자적
  구현)
- `src/agent_trading/repositories/memory.py`(신규 원자적 구현)
- `src/agent_trading/services/fdc_quota_coordinator.py`(단일 메서드로
  교체)
- `src/agent_trading/services/decision_orchestrator.py`(`fdc_ready_at_raw`
  파싱 + 호출 시점 변경 없이 인자만 교체 — 호출 위치 자체는 여전히
  `assemble()` 안이지만 이제 subprocess에서 역사적으로 정확한 시각을
  실어온다)
- `tests/scripts/test_fdc_skip.py`(타이밍 증명 테스트 추가)
- `tests/services/test_decision_orchestrator.py`(shadow 관측 테스트
  재작성)
- `tests/services/test_fdc_quota_coordinator.py`(FIFO 큐 테스트 전면
  재작성)
- `docs/40_action_plans/fdc_cycle_scoped_batch_queue_gemini_shared_13rpm_
  quota_design_2026-08-25.md`(5차 개정 이력 추가)
- `docs/30_work_log/2026-08-25_fdc_quota_lifecycle_shadow_phase1_
  implementation.md`(정정 안내 추가)
- `docs/99_meta_handover/[BACKLOG] backlog.md`(정정 이력 추가)
- 본 문서(신규)

## 실행한 harness와 결과

| 명령 | 결과 |
|---|---|
| `accept script-file scripts/run_agent_subprocess.py` | PASS(`tests_run_count=3`, `test_failed_count=0`) |
| `accept backend-file src/agent_trading/services/common_types.py` | PASS |
| `accept backend-file src/agent_trading/services/decision_agent_runner.py` | PASS |
| `accept backend-file src/agent_trading/services/decision_orchestrator.py` | PASS |
| `accept backend-file src/agent_trading/services/subprocess_helpers.py` | PASS |
| `accept backend-file src/agent_trading/services/fdc_quota_coordinator.py` | PASS(`test_fdc_quota_coordinator.py`+`test_decision_orchestrator.py` 포함) |
| `accept backend-file src/agent_trading/repositories/memory.py` | PASS |
| `accept backend-file src/agent_trading/repositories/postgres/fdc_quota.py` | PASS |
| `accept backend-file src/agent_trading/repositories/contracts.py` | FAIL(13건, `test_postgres_trade_decisions.py`) — `git stash` 대조로 `main` 기준 동일 실패 확인, sandbox `network_mode=none` 사전 존재 제약(회귀 아님) |
| `accept architecture` | PASS(`architecture_violation_count=0`) |
| `accept db-structure` | PASS(`repository_protocol_count=43`) |
| `accept backend-runtime` | PASS |
| `accept env` | PASS |
| `accept no-bypass` | PASS(`hard_bypass_count=0`) |
| `accept style` | PASS |
| `accept docs` | PASS |

전체 테스트 스위트·실제 Gemini 호출·migration 적용·운영 DB write·컨테이너
재기동은 이번 보정에서 전혀 수행하지 않았다.

## 미검증 가정

- `register_shadow_job_and_judge()`의 실제 PostgreSQL 행 잠금 동작·60초
  경계·동시성은 CI의 pinned PostgreSQL 컨테이너 단계에서만 실제로
  실행된다 — 로컬 dev-validation 샌드박스에서는 skip이 불가피하다.
- `fdc_ready_at` subprocess 캡처가 실제 다수 심볼 동시 실행 환경에서
  체감상 얼마나 정확히 "논리적 FDC-ready 순간"을 반영하는지는 실측하지
  않았다(코드 구조상 캡처와 permit 대기 사이에 `await`가 없다는 정적
  근거만 확인).
- shadow 등록 쿼리 2개(INSERT+COUNT)가 `assemble()`당 추가하는 DB 부하는
  이번 보정에서도 실측하지 않았다.

## PR #351 최신 커밋/CI/병합 가능 여부

본 항목은 완료 보고 본문에 별도로 기재한다(브랜치 push 및 `gh pr checks`/
`gh pr view` 실행 후).
