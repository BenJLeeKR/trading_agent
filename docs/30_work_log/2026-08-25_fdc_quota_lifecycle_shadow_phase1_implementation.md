# FDC cycle-scoped batch queue Phase 1(lifecycle shadow 기반) 구현

## 배경

PR #350(설계 확정 문서, `docs/40_action_plans/fdc_cycle_scoped_batch_
queue_gemini_shared_13rpm_quota_design_2026-08-25.md`)이 병합된 것을
확인한 뒤, 그 설계의 Phase 1(lifecycle shadow 기반)을 구현했다. 이번
PR의 목적은 새 PostgreSQL quota/lifecycle 구조를 실제 코드·DB 계약으로
만들고 운영에서 관측할 준비를 하는 것이며, 기존 실제 FDC 실행·기존
FIFO limiter·provider 호출 수·주문 정책은 전혀 바꾸지 않는다.

## 구현한 것

### 1. Migration
`db/migrations/0068_add_fdc_quota_lifecycle_tables.sql` — `fdc_quota_
state`(singleton anchor, `'gemini:shared-operational'` 1행 seed),
`fdc_queue_jobs`(job 최신 상태 + accounting 컬럼 전부), `fdc_provider_
attempts`(append-only, `job_id` nullable — 비운영 수동 호출은 `manual_
run_id`로 연결). `(mode, quota_scope, reserved_at)` sliding-window
인덱스, `(job_id, attempt_no) WHERE job_id IS NOT NULL` partial unique
제약 포함. **작성만 했고 운영 DB에 적용하지 않았다.**

### 2. Repository
당초 계획은 `services/` 계층에서 직접 `asyncpg`/`TransactionManager`를
쓰는 것이었으나, `accept architecture`가 이를 `legacy_direct_db_import`
위반(고정 baseline 0 초과)으로 잡아내 **기존 repository 관례를 그대로
따르도록 재구성**했다:

- `repositories/contracts.py`: `FdcQuotaRepository` Protocol +
  `ReservationGrant`/`ReservationDenied`/`CoordinatorError`/
  `CoordinatorErrorClass`/`ShadowJudgement` 결과 타입.
- `repositories/postgres/fdc_quota.py`: `PostgresFdcQuotaRepository` —
  `create_shadow_job()`/`judge_shadow_reservation()`은 다른 저장소와
  동일하게 ambient `tx`(요청 단위 공유 트랜잭션)를 쓰고, `try_reserve()`
  만 예외적으로 자신만의 독립 `TransactionManager()`를 연다(이유:
  이 메서드의 존재 이유 자체가 "여러 동시 호출자 사이의 원자적 경쟁"
  이라, ambient 트랜잭션에 얹으면 anchor 행 잠금이 요청 전체 범위 동안
  유지돼 다른 호출자를 불필요하게 막는다 — Phase 1에서는 이 메서드가
  실제 런타임 경로에서 호출되지 않으므로 이 결정의 실제 영향은 없다).
- `repositories/memory.py`: `InMemoryFdcQuotaRepository` —
  `asyncio.Lock`으로 anchor 행 잠금 의미를 프로세스 내에서 재현.
- `repositories/container.py`/`repositories/bootstrap.py`/
  `repositories/postgres/bootstrap.py`: 기존 42개 repository와 동일한
  방식으로 `fdc_quota` 필드 추가·wiring.

### 3. 서비스
`services/fdc_quota_coordinator.py`: `FdcQuotaCoordinator` — 설정값
(target_rpm/window_seconds/quota_scope)만 들고 실제 DB 작업은 주입된
`repo`(`FdcQuotaRepository`)에 위임하는 얇은 서비스. 생성자에서
`target_rpm < declared_rpm_limit` validation. `try_reserve()`(§6 atomic
reservation, Phase 1은 테스트 전용) / `create_shadow_job()`·`judge_
shadow_reservation()`(Phase 1의 실제 관측 경로) 제공.

### 4. lifecycle shadow 런타임 배선
`decision_orchestrator.py`에 `_record_fdc_batch_queue_lifecycle_shadow_
observation()` 추가 — 다른 shadow 관측 메서드(AR/EI shadow bot,
held_position FDC/REDUCE skip shadow)와 완전히 동일한 원칙: `assemble()`
안, 기존 `decision_type`/`side`/주문 mutate 코드가 전혀 없는 지점에서
호출, `fdc_skipped=False`(FDC-ready)인 건만 대상, coordinator 예외를
전부 삼켜 기존 파이프라인에 영향 없음. `fdc_batch_queue_lifecycle_
shadow_enabled`(기본 `False`)와 `fdc_quota_coordinator`(기본 `None`)
생성자 파라미터 추가 — 둘 다 기본값에서는 완전한 no-op.

### 5. 설정 배선
`settings.py`(4개 신규 resolver+field) → `run_decision_loop.py`(양쪽
`DecisionOrchestratorService` 생성 지점에 `fdc_batch_queue_lifecycle_
shadow_enabled`/`fdc_quota_coordinator=FdcQuotaCoordinator(repo=repos.
fdc_quota, ...)` 전달) → `docker-compose.yml`(ops-scheduler
`environment:`) → `.env.example`(주석 포함 4개 키, 기본값 그대로).

## 기존 런타임 무영향 근거

- `FDC_BATCH_QUEUE_LIFECYCLE_SHADOW_ENABLED` 기본값 `false` — 이 경우
  `_record_fdc_batch_queue_lifecycle_shadow_observation()`이 최상단에서
  즉시 반환하며 `FdcQuotaCoordinator`/`repos.fdc_quota`를 전혀 건드리지
  않는다(테스트로 직접 확인).
- `try_reserve()`(실제 quota 소비 경로)는 이번 PR의 어떤 런타임 호출
  경로에서도 호출되지 않는다 — `grep`으로 확인 가능, 단위/통합 테스트
  에서만 호출됨.
- `fdc_rate_limiter.py`, `provider_client.py`, EI/AR/AC, held_position
  override, EV gate, sizing, sell guard, 주문 제출 경로는 이번 diff에
  전혀 포함되지 않았다.

## 검증

| 명령 | 결과 |
|---|---|
| `bash scripts/harness/run.sh test-file tests/services/test_fdc_quota_coordinator.py` | PASS(11 passed, 3 skipped — DATABASE_HOST 없어 Postgres 통합 테스트만 skip) |
| `bash scripts/harness/run.sh test-file tests/services/test_decision_orchestrator.py` | PASS(105 passed, 신규 6건 포함) |
| `bash scripts/harness/run.sh accept architecture` | PASS(`architecture_violation_count=0`) |
| `bash scripts/harness/run.sh accept db-structure` | PASS(`repository_protocol_count=43`, container/memory/postgres/bootstrap 전부 42→43 동기화) |
| `bash scripts/harness/run.sh accept backend-runtime` | PASS(`env_example_missing_key_count=0`) |
| `bash scripts/harness/run.sh accept env` | PASS(신규 키 4개는 advisory로만 표시 — 외부 런타임 env 파일에 아직 없다는 뜻, 코드 계약 위반 아님) |
| `bash scripts/harness/run.sh accept no-bypass` | PASS(`hard_bypass_count=0`, review_bypass 11건은 기존 파일에 이미 있는 패턴과 동일 — `except Exception`은 다른 shadow 메서드와 동일, `# type: ignore[attr-defined]`/`AsyncMock`/`skipif`는 기존 테스트 파일에 이미 있는 패턴) |
| `bash scripts/harness/run.sh accept style` | PASS |
| `bash scripts/harness/run.sh accept docs` | PASS |
| `bash scripts/harness/run.sh accept script-file scripts/run_decision_loop.py` | PASS(`test_failed_count=0`) |

`accept backend-file src/agent_trading/repositories/contracts.py`와
`accept backend-file src/agent_trading/config/settings.py`가 각각 13건/
2건의 실패를 보고했으나, `git stash`로 이번 PR 변경분을 제외한 `main`
기준으로 동일 테스트를 재실행해 **완전히 동일한 실패**(`OSError:
Multiple exceptions: ... Connect call failed`, sandbox 컨테이너의
`network_mode=none`으로 인한 DB 연결 불가)를 확인했다 — 이번 PR과 무관한
사전 존재 하네스 환경 제약이다(회귀 아님).

## 미검증 운영 가정

- `try_reserve()`의 실제 Postgres 행 잠금/`(t-60초,t]` 경계/lock timeout
  동작은 이 dev 샌드박스(네트워크 격리)에서 검증하지 못했다 — CI의
  "pinned PostgreSQL container" 단계에서 `DATABASE_HOST`가 설정되면
  `TestPostgresAtomicReservation` 3건이 실제로 실행되어 검증된다.
- shadow 관측이 실제 운영 트래픽에서 DB 부하를 얼마나 늘리는지는
  실측하지 않았다(설계상 `assemble()`당 최대 2회 추가 쿼리 정도로
  가볍다고 추정하나 확인 안 됨).

## 변경 파일

- `db/migrations/0068_add_fdc_quota_lifecycle_tables.sql`(신규)
- `src/agent_trading/repositories/contracts.py`
- `src/agent_trading/repositories/postgres/fdc_quota.py`(신규)
- `src/agent_trading/repositories/memory.py`
- `src/agent_trading/repositories/container.py`
- `src/agent_trading/repositories/bootstrap.py`
- `src/agent_trading/repositories/postgres/bootstrap.py`
- `src/agent_trading/services/fdc_quota_coordinator.py`(신규)
- `src/agent_trading/services/decision_orchestrator.py`
- `src/agent_trading/config/settings.py`
- `scripts/run_decision_loop.py`
- `docker-compose.yml`
- `.env.example`
- `tests/services/test_fdc_quota_coordinator.py`(신규)
- `tests/services/test_decision_orchestrator.py`
- `docs/40_action_plans/fdc_cycle_scoped_batch_queue_gemini_shared_13rpm_quota_design_2026-08-25.md`(상태 갱신)
- `docs/99_meta_handover/[BACKLOG] backlog.md`
- 본 문서(신규)

## 다음 단계

실제 cycle-scoped dispatcher(사이클 안에서 FDC-ready job 전원을 처리),
FDC one-shot 인터페이스(`generate_structured_once()`, 기존 공용
`generate_structured()`는 무변경), `LiveGeminiProviderClient`/
`FakeProviderClient` 타입 분리(quota coordinator 우회 차단), held_
position lane 한정 실제 전환 — 전부 후속 PR 대상. 이번 PR에서는
미착수.
