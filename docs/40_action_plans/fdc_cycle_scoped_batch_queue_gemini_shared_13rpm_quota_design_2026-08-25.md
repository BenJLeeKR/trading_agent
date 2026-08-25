# FDC Cycle-Scoped Batch Queue + Gemini Shared 13 RPM Quota (PostgreSQL Atomic Reservation) — 설계 확정

> **상태**: 설계 확정(read-only 검토·문서화 전용). 런타임 코드/migration/compose/`.env` 변경 없음.
> 구현은 이 문서를 기준으로 별도 후속 PR에서 진행한다.

## 1. 배경과 문제 정의

held_position 매도 후보의 FDC(FinalDecisionComposer) 판단이 `provider_queue_timeout`으로
소실되는 문제를 여러 차례 read-only 실측·설계 검토로 추적한 결과, 근본 원인은 다음과
같이 확인됐다.

- FDC provider(Gemini) 호출은 공유 rate limiter(`fdc_rate_limiter.py`)로 `10 RPM`(현재
  하드코딩 상수)만 허용하는데, 사이클당 실제 FDC 대상 수(held_position+core 합산 최대
  수십 건)가 이를 크게 초과한다.
- 현재 in-cycle FIFO 재대기열(PR #313)은 "1차 대기 18초 + 재대기 18초 = 최대 36초"
  후 확정 실패(`provider_queue_timeout`)한다. 실측(2026-08-24~25, 2거래일) 결과 **재대기
  128건 중 재대기 후 실제 HTTP 성공 사례는 0건**이었다 — 재대기 상한(36초)이 sliding
  window의 slot 회복 주기(약 60초)보다 짧아 구조적으로 회복 전에 예산이 바닥난다.
- 이 병목은 재대기 정책의 미세조정이 아니라, "탈락 없이 순서대로 전원 처리"라는 근본적
  아키텍처 전환으로만 해소된다.

추가로, 설계 검토 과정에서 아래 2개의 사전에 알려지지 않았던 사실을 확인했다.

- **운영 `ops-scheduler`의 EI/AR/AC는 Gemini를 전혀 호출하지 않는다** — `runtime/
  bootstrap.py`의 factory가 항상(always) `Deterministic*Agent`를 반환한다(코드 확인).
  **운영에서 Gemini를 호출하는 것은 FDC 하나뿐이다.**
- `scripts/ar_fdc_output_measurement.py --with-provider`, `scripts/
  ar_fdc_provider_validation.py` 두 개의 수동 분석 스크립트가 `acquire_permit` 콜백
  없이 provider client를 직접 생성/호출해, **현재 limiter를 완전히 우회할 수 있는 경로가
  실재**한다. 이 스크립트들은 `app` 컨테이너(`docker exec`용 유휴 컨테이너)에서 실행
  가능하며, `app`은 `ops-scheduler`와 **동일한 `GEMINI_API_KEY`**를 갖는다(값 자체는
  비공개, 존재만 확인).

## 2. 목표 · 비목표

### 목표

- Gemini 실제 HTTP 요청(최초+retry 합산)이 임의의 sliding 60초 구간에서 **13건을
  넘지 않는다**(Gemini 공식 한도 15보다 여유 2건을 둔 운영 목표).
- `ops-scheduler`의 FDC 요청과 수동 분석 스크립트의 요청이 **하나의 공용 quota를
  공유**해, 두 주체가 각자 13 RPM씩 써서 합계 26 RPM이 되는 위험을 없앤다.
- 사이클 내 FDC 대상 30건이면 약 3개 이상, 40건이면 약 4개 이상의 60초 window에
  걸쳐 **전원이 순서상 밀린다는 이유만으로 탈락하지 않고** 최소 1회 실제 HTTP 호출
  기회를 받는다.
- FDC job이 완료되는 즉시(배치 전체 종료를 기다리지 않고) 기존 `assemble()`/저장/
  주문 제출 경로로 합류한다(현재 코드가 이미 이렇게 동작하므로 이 성질을 보존한다).
- 재기동 시 사이클의 진행 상태(대기/완료/취소)를 DB에서 사후 확인할 수 있다.

### 비목표

- EI/AR/AC의 결정론적 bot 로직, held_position sell override, EV gate, translation,
  sizing, sell guard, 주문 제출 조건, freshness 게이트 — **어느 것도 변경하지 않는다.**
- Gemini의 실제 quota 적용 단위(API 키/프로젝트/모델)를 확정하는 것은 이 문서의
  목표가 아니다(외부 provider 정책, 미확인 사항으로 명시).
- 사이클 병행 실행, cross-cycle supersede — 채택하지 않는다(순차 cycle을 그대로
  유지하는 것이 확정 계약).

## 3. 현재 구조와 탈락 원인(코드 근거 요약)

- `run_decision_loop.py`: 사이클은 완전 순차 — 모든 종목 처리(세마포어 `_SEMAPHORE_
  MAX=5`) + T3 drain이 끝난 뒤 `interval`(900초, `OPS_SCHEDULER_DECISION_INTERVAL_
  SECONDS`) 만큼 sleep 후 다음 사이클. **`interval`은 "사이클 완료 후 sleep"이지
  "사이클 시작 간격 고정"이 아니다** — 사이클이 길어지면 다음 사이클 시작이 그만큼
  밀릴 뿐, 코드 변경 없이 3~4분 이상의 사이클을 자연스럽게 수용한다.
- `decision_agent_runner.py::run_agents_in_subprocess()`: EI+AR+AC+FDC 4개 에이전트를
  **하나의 subprocess**에서 순차 실행, 부모가 90초로 감싸 SIGTERM(10초 유예)→SIGKILL.
- `run_agent_subprocess.py`: `_FDC_PER_AGENT_TIMEOUT=70`초가 **permit 대기와 HTTP
  실행을 합쳐서** 제한한다(코드 주석에 명시) — 이것이 "36초 재대기 상한이 70초/90초
  예산 안에 갇혀 있다"는 구조적 제약의 근거다.
- `fdc_rate_limiter.py`: `DEFAULT_MAX_CALLS_PER_WINDOW=10`(모듈 상수, env/settings/
  compose 배선 전무), `DEFAULT_WINDOW_SECONDS=60`, `DEFAULT_MAX_WAIT_SECONDS=18`,
  `DEFAULT_MAX_REQUEUE_COUNT=1`. 상태 파일은 `tempfile.gettempdir()`(컨테이너 로컬
  `/tmp`)에 있다 — **`app`과 `ops-scheduler`가 이미 `./tmp:/app/tmp`를 공유
  bind-mount하고 있음에도(둘 다 host의 같은 `./tmp` 디렉터리), limiter가 이 공유
  경로가 아니라 컨테이너별 로컬 `/tmp`를 쓰고 있어 공유되지 않는다.**
- `provider_client.py::generate_structured()`: `MAX_RETRIES=3`은 **총 HTTP 시도
  횟수**(최초 1회+추가 재시도 최대 2회, `for attempt in range(3)`). 매 attempt마다
  `acquire_permit()`을 다시 호출, permit 거부 시 HTTP 시도로 집계되지 않는다.
  429/5xx/timeout/DNS 오류는 retry, 그 외 4xx·파싱 오류는 즉시 확정 실패.
- `app` 컨테이너는 `DATABASE_HOST: trading_db`로 **ops-scheduler와 동일한
  PostgreSQL**에 접근 가능(확인) — DB 기반 공용 coordinator가 신규 인프라 없이
  실현 가능한 근거.
- 기존 저장소에 **이미 확립된 행 잠금 관례**: `repositories/postgres/
  kis_fill_cumulative_state.py`가 "미리 존재하는 행을 `SELECT ... FOR UPDATE`로
  잠근 뒤 read-modify-write"하는 패턴을 실사용 중 — 이번 quota reservation 설계의
  직접적 선례.

## 4. 확정 아키텍처

**Cycle-scoped strict batch queue**(사이클 안에서 FDC 대상 전원을 끝까지 처리,
사이클 병행 없음) + **PostgreSQL 기반 공용 13 RPM quota coordinator**(anchor 행
잠금) + **dispatcher 완전 소유 permit ownership**(provider client는 1회 시도만
수행) 조합을 채택한다.

- 사이클 초반에 종목별 EI/AR/AC/deterministic_trigger를 먼저 전부 실행(기존과 동일,
  변경 없음). 결정론적 skip(risk_reject/NO_ACTION/WATCH-safe 등 기존 조건)은 즉시
  `assemble()`으로 저장(큐에 들어가지 않음).
- FDC가 필요한 대상만 `fdc_queue_jobs`에 `QUEUED`로 등록.
- 중앙 dispatcher(사이클 본문 안, 별도 장기 상주 프로세스 아님)가 사이클이 끝날
  때까지(=큐가 빌 때까지) worker slot·quota reservation을 관리하며 반복.
- job이 `FDC_SUCCEEDED`/`FDC_FAILED_FINAL`에 도달하는 즉시 기존 `assemble()`으로
  저장(배치 전체 종료를 기다리지 않음 — 기존 코드의 "종목별 즉시 저장" 성질 보존,
  `decision_orchestrator.py:1603 await self._repos.trade_decisions.add(td_entity)`가
  `assemble()` 내부에서 이미 동기 저장하는 것을 확인).
- 사이클은 전 job이 `FDC_SUCCEEDED`/`FDC_FAILED_FINAL`/`CANCELLED`에 도달해야 종료.

## 5. 상태 전이도

```
[Job lifecycle]
QUEUED
  → (worker slot 확보 성공 && quota reservation 성공)
  → RESERVATION_GRANTED
  → FDC_RUNNING(HTTP one-shot 실행)
    → HTTP_SUCCEEDED → FDC_SUCCEEDED → 즉시 assemble()/저장
    → HTTP_FAILED_RETRYABLE(429/5xx/timeout/DNS)
        → RETRY_QUEUED(새 queue_entry_id, FIFO tail) → QUEUED로 복귀
        → (max_http_attempts=3 소진) → FDC_FAILED_FINAL → 즉시 assemble()(fallback)/저장
    → HTTP_FAILED_NONRETRYABLE(4xx/파싱오류) → FDC_FAILED_FINAL(즉시)
  → (reservation 성공 후 HTTP 시작 전 worker/subprocess 생성 실패)
      → RESERVED_BUT_HTTP_NOT_STARTED(quota는 그 60초 동안 계속 소비된 것으로 기록)
      → (max_pre_http_execution_failures 소진 전) RETRY_QUEUED
      → (소진) FDC_FAILED_FINAL(reason=worker_start_exhausted)
CANCELLED ← 시장 종료 / 운영자 명시 취소 / 프로세스 종료(오직 이 세 사유만)

[Cycle lifecycle]
전 종목 pre-FDC(EI/AR/AC) 완료
  → FDC-ready job 전원 QUEUED
  → dispatcher 반복(전원 종결 상태 도달까지, deadline 없음 — 명시적 취소만 종료 사유)
  → 사이클 종료 → interval(900초) sleep → 다음 사이클
```

`provider_queue_timeout`이라는 기존 reason code는 **이 신규 경로에서 사용하지
않는다** — 순번 대기로 인한 확정 실패라는 개념 자체가 새 계약에는 존재하지 않는다.

## 6. Atomic reservation transaction 계약

```sql
BEGIN;  -- 기본 isolation level(READ COMMITTED), 명시적 상향 불필요

  SELECT * FROM fdc_quota_state
    WHERE quota_scope = 'gemini:shared-operational'
    FOR UPDATE;
    -- 이 행은 배포 시 1회 seed(migration의 INSERT)로 항상 존재한다.
    -- "최근 reservation 행"이 아니라 "항상 존재하는 고정 anchor 행"을 잠그므로,
    -- reservation이 0건인 순간에도 잠금 대상이 없어 발생하는 phantom insert
    -- 경쟁 조건(두 트랜잭션이 동시에 count=0을 보고 각자 INSERT)이 원천 차단된다.

  SELECT count(*) FROM fdc_provider_attempts
    WHERE quota_scope = 'gemini:shared-operational'
      AND outcome IN ('reservation_granted','http_started',
                       'http_succeeded','http_failed_retryable',
                       'http_failed_final','reserved_but_http_not_started')
      AND reserved_at > now() - interval '60 seconds';
    -- reservation 성공 순간부터 60초 동안 quota를 소비한 것으로 간주 —
    -- HTTP 시작 전 worker 실패(reserved_but_http_not_started)도 포함해야
    -- 슬롯 이중 사용을 막는다(보수적 정책).

  IF count < 13:
    INSERT INTO fdc_provider_attempts(..., outcome='reservation_granted', reserved_at=now());
    UPDATE fdc_queue_jobs SET status='reservation_granted', ... WHERE job_id=...;
  ELSE:
    ROLLBACK;  -- job은 QUEUED에 그대로 남는다. 탈락이 아니다.

COMMIT;
-- ── 불변식: 이 COMMIT 이전에 Gemini HTTP 호출이 발생하지 않는다.
--    트랜잭션/행 잠금을 쥔 채 네트워크 I/O를 수행하지 않는다.
--    commit 이후에만 worker가 즉시 HTTP one-shot을 시작한다.
```

- **DB 장애/lock timeout/트랜잭션 오류 시**: live Gemini HTTP 호출은 **fail-closed**
  — coordinator에 접근할 수 없으면 그 job은 시도하지 않고 `QUEUED`에 남는다(탈락
  아님, 다음 재시도 기회를 기다림).
- **60초 경계의 판단 SQL과 사후 검증 SQL 일치**: 양쪽 모두 `reserved_at`(reservation
  성공 시각) 기준 `> now() - interval '60 seconds'`(판단 시) / `RANGE BETWEEN
  INTERVAL '60 seconds' PRECEDING AND CURRENT ROW`(사후 검증, §11) — **동일한
  컬럼·동일한 반열림 구간 규칙**을 쓰도록 통일한다.

## 7. worker·retry·freshness·즉시 저장 계약

**실행 순서(확정)**:
```
local FDC worker slot 확보(asyncio.Semaphore 또는 동등)
→ PostgreSQL atomic reservation(§6)
→ commit
→ 즉시 FDC one-shot HTTP 실행
→ 결과 기록(fdc_provider_attempts UPDATE)
→ local worker slot 반환
```
worker slot을 **먼저** 확보하는 이유: reservation과 실제 HTTP 시작 사이의 시간차를
최소화해, "permit은 받았는데 worker가 없어 대기"로 60초 window의 슬롯이 낭비되는
상황을 막는다.

- **reservation 거부**: worker slot 즉시 반환, job은 `QUEUED` 유지.
- **reservation 성공 후 worker 시작 실패**: `RESERVED_BUT_HTTP_NOT_STARTED` 기록
  (quota는 60초간 소비 유지), `max_pre_http_execution_failures`(신규 설정, 권고
  초기값 3) 소진 전엔 `RETRY_QUEUED`, 소진 시 `FDC_FAILED_FINAL(reason=
  worker_start_exhausted)` — **이 종료는 순번 탈락도 `CANCELLED`도 아닌, 명확히
  분리된 내부 실행 실패 사유다.**
- **`FDC_WORKER_CONCURRENCY`**: 기존 `_SEMAPHORE_MAX`(종목 처리 동시성, 5)와는
  **별개의 설정**으로 신설한다. **초기값 5를 제안하되, 이는 확정값이 아니라
  실측 전 보수적 시작값**이다 — 13 RPM을 실제로 소진할 만큼 충분한지는 구현 후
  실측이 필요하다(13절 미확인 사항).
- **즉시 저장**: job이 `FDC_SUCCEEDED`/`FDC_FAILED_FINAL`에 도달하는 즉시 기존
  `assemble()` 경로로 저장한다 — 배치 전체 종료를 기다리는 방식은 **채택하지
  않는다**(기존 코드의 종목별 즉시 저장 동작을 그대로 보존).
- **freshness**: 기존 `stale_threshold_seconds=900`(계좌 스냅샷)과 주문 직전
  실시간 시세 재조회(`_resolve_quote()`) 메커니즘을 **변경하지 않고 그대로 재사용**
  한다. 배치가 길어져도(§10 계산상 최악 약 9분) 900초 임계값에는 여유가 있다.

## 8. 영속 스키마와 migration 계획(설계, 이번 턴에서 migration 파일 작성 안 함)

### `fdc_quota_state`(신규, singleton anchor 행)
| 컬럼 | 타입 | 비고 |
|---|---|---|
| `quota_scope` | text PK | 고정값 `'gemini:shared-operational'`, migration에서 1행 seed |
| `created_at` | timestamptz | |

### `fdc_queue_jobs`(신규)
| 컬럼 | 비고 |
|---|---|
| `job_id` | UUID PK |
| `decision_cycle_id`, `decision_context_id`, `symbol`, `source_type` | |
| `status` | 인덱스 필요(재기동 후 미완료 조회) |
| `queue_poll_count`, `dispatch_attempt_no`, `retry_count` | §9 정의 |
| `permit_consumed_count`, `http_attempt_count`, `http_429_count`, `reserved_but_http_not_started_count` | §9 정의 |
| `queued_at`, `completed_at` | |
| `trade_decision_id` | nullable FK → `trade_decisions` |
| `failure_or_cancel_reason` | nullable |
| `created_at`, `updated_at` | |

### `fdc_provider_attempts`(신규, append-only — reservation 1회=attempt 1행)
| 컬럼 | 비고 |
|---|---|
| `attempt_id` | UUID PK |
| `job_id` | FK → `fdc_queue_jobs` |
| `quota_scope`, `caller_id`(`"ops-scheduler"` / `"manual:<script명>"`), `queue_entry_id` | |
| `attempt_no`, `retry_count` | |
| `reserved_at`, `http_started_at`(nullable), `completed_at`(nullable) | `(quota_scope, reserved_at)` range 인덱스 필수 |
| `outcome`, `http_status`(nullable), `error_class`(nullable), `http_429_observed` | |
| unique 제약 `(job_id, attempt_no)` | 중복 기록 방지 |

**원칙**: attempt row는 reservation 시 INSERT하고, 이후 같은 row를 HTTP 시작/종료
정보로 UPDATE한다(하나의 "실행 기회"는 하나의 사건이므로 별도 event 테이블로 더
쪼개지 않는다 — 현재 규모에서 과잉 정규화). **삭제·재사용 없음**(append-only).

## 9. Accounting 정의(확정)

| 필드 | 정의 |
|---|---|
| `queue_poll_count` | reservation 가능 여부를 확인 시도한 횟수(거부 포함) |
| `reservation_denied_count` | 13 RPM window가 가득 차 거부된 횟수 |
| `dispatch_attempt_no` | reservation을 실제로 받아 worker 실행으로 넘어간 횟수 |
| `retry_count` | 실패 후 FIFO tail 재등록 횟수 |
| `permit_consumed_count` | 성공 reservation 수(`fdc_provider_attempts`에 `reservation_granted` 이상으로 기록된 행 수) |
| `http_attempt_count` | `http_started_at IS NOT NULL`인 attempt 수 |
| `http_429_count` | `http_status=429`인 attempt 수 |
| `reserved_but_http_not_started_count` | `outcome='reserved_but_http_not_started'`인 attempt 수 |

**불변식**: `http_attempt_count ≤ permit_consumed_count`(reservation 성공 후 HTTP
시작 전 실패 사례가 있으면 부등식 성립) / `retry_count ≤ max_http_attempts-1=2`
/ 임의 sliding 60초 구간 reservation 수 ≤ 13(§6 트랜잭션이 보장).

**명명 전환**: `MAX_RETRIES=3`(총 HTTP 시도 수)이라는 기존 이름이 실제 의미와
혼동되므로, **신규 설계 문서·신규 코드에서는 `max_http_attempts=3`으로 명명**한다
(기존 `provider_client.py`의 모듈 상수 자체는 이번 문서화 턴에서 변경하지 않음 —
구현 PR에서 리네이밍 여부와 영향 범위 전수 확인 후 결정).

## 10. 13 RPM 용량 계산(확정 계산식, 실측 아님)

```
필요 dispatch 묶음 수 = ceil(A / 13)   (A = 실제 총 HTTP 시도 수)
마지막 HTTP 시작 기준 ≈ (ceil(A/13) - 1) × 60초 + worker 지연
마지막 완료 기준 ≈ 위 값 + provider 실행 시간(+ 재시도 backoff 누적)
```

- **40개 최초 job, 전원 첫 시도 성공(A=40)**: `ceil(40/13)=4` → 마지막 HTTP 시작
  ≈ 180초, 완료 ≈ **약 3.3분**.
- **총 HTTP 시도 120회 극단(A=120, `max_http_attempts=3` 전원 소진)**: `ceil(120/13)
  =10` → 마지막 HTTP 시작 ≈ 540초, 완료 ≈ **약 9~9.5분**(재시도 backoff 포함).

## 11. 수동 provider 호출 정책(확정)

- 정책 후보 A(기술적 실행 금지)/B(공용 coordinator+low-priority)/C(synthetic job
  으로 FDC FIFO에 편입)/D(운영 중 A, 비운영 시 B) 중 **D를 권고**한다: 운영 시간대
  (정규장 중)에는 수동 스크립트의 `--with-provider` 실행을 절차적으로 금지하고,
  기술적으로는 아래 §12의 강제 구조로 인해 **coordinator 없이는 애초에 live HTTP를
  낼 수 없다**(실행하더라도 자동으로 같은 quota_scope를 공유하게 되거나 fail-closed로
  막힌다).
- 수동 호출도 `fdc_queue_jobs.job_id`가 필요하다(§8 스키마의 `caller_id` 필드로
  ops-scheduler와 구분, `source_type`은 해당 없음 값으로 기록).
- `fdc_provider_attempts`는 FDC 전용이 아니라 **`quota_scope`/`caller_id` 필드로
  이미 범용화**돼 있으므로 별도 `gemini_provider_attempts` 테이블 분리는 불필요.
- 수동 트래픽이 FDC 판단 기회를 늦추지 않는 방법: FIFO 순서는 `queue_entry_id`
  생성 순서를 그대로 따르므로, 수동 호출도 같은 FIFO에 얹히면 도착 순서대로 공정하게
  경쟁한다 — 운영 시간대 금지 정책(위 D안)이 이 경쟁 자체를 회피하는 1차 방어선이다.

## 12. Live provider fail-closed 경계(확정)

- 실제 Gemini HTTP를 낼 수 있는 구현체(`LiveGeminiProviderClient`, 신규 명명 제안)는
  **coordinator 의존성 없이는 생성·실행 불가능**하게 한다(생성자 필수 인자).
- fake/test provider는 **별도 구현체**(`FakeProviderClient`)로 분리 — `live_provider
  =False` 같은 **플래그 방식은 채택하지 않는다**(오설정 우회 위험, 사용자 지적 반영).
- FDC 전용 `generate_structured_once()`는 dispatcher가 permit/retry/backoff를
  전담하기 위한 **최소 신규 인터페이스**다. 기존 공용 `generate_structured()`(EI/AR/
  AC 구식 클래스가 참조하나 운영 비활성)는 **무근거로 변경하지 않는다** — 이 함수
  내부에서도 결국 `LiveGeminiProviderClient`의 coordinator 강제를 상속받으므로
  이중 방어가 자연히 성립한다.
- raw provider client 직접 호출(`ar_fdc_provider_validation.py` 등)과 두 분석
  스크립트 모두 **같은 강제 지점**(`LiveGeminiProviderClient` 생성자)을 통과해야
  하므로 개별적으로 막을 필요가 없다.

## 13. 설정 계약(확정, 값은 구현 PR에서 실제 배선)

| 키 | 기본값 | 용도 |
|---|---|---|
| `FDC_PROVIDER_TARGET_RPM` | `13` | 운영 목표 |
| `FDC_PROVIDER_RATE_WINDOW_SECONDS` | `60` | sliding window 길이 |
| `GEMINI_PROVIDER_DECLARED_RPM_LIMIT` | `15` | 문서/startup validation 전용(코드가 강제 호출하는 값 아님) |
| `FDC_WORKER_CONCURRENCY` | `5`(실측 전 보수적 시작값) | FDC 전용 동시 실행 수 |
| `FDC_QUOTA_COORDINATOR_BACKEND` | `"postgres"` | 백엔드 선택(현재 단일 값만 지원) |

startup validation(구현 PR 대상): `FDC_PROVIDER_TARGET_RPM < GEMINI_PROVIDER_
DECLARED_RPM_LIMIT`, 모든 수치형 값 `> 0`. 배선 경로: `.env.example` 주석 추가 →
`settings.py` 필드 → dispatcher가 `settings`에서 읽어 명시적으로 전달(현재처럼
함수 기본값에 암묵 의존하지 않음) → `docker-compose.yml`의 `ops-scheduler`
`environment:` 블록. **이번 문서화 턴에서 `.env`/`.env.example`/compose/migration
실제 수정 없음** — 구현 PR 대상.

## 14. 관측(감사) SQL 요구사항

```sql
-- 임의 sliding 60초 구간 reservation 수 최댓값(13 초과 여부 검증)
WITH counts AS (
  SELECT reserved_at,
         count(*) OVER (ORDER BY reserved_at
           RANGE BETWEEN INTERVAL '60 seconds' PRECEDING AND CURRENT ROW) AS window_count
  FROM fdc_provider_attempts WHERE quota_scope='gemini:shared-operational'
)
SELECT max(window_count) FROM counts;

-- 실제 HTTP 시작 수 최댓값(같은 방식, http_started_at 기준)
-- reserved_at은 있으나 http_started_at 없는 attempt(reserved_but_http_not_started)
-- caller_id별 quota 소비량
-- job별 permit_consumed_count와 attempt 행 수 정합성(HAVING 불일치)
-- 재기동 뒤 미완료 job 및 마지막 상태(status NOT IN 종결상태)
-- provider_queue_timeout reason code가 신규 경로에서 생성되지 않았는지(기대값 0)
```
(전체 SQL 원문은 이전 설계 검토 세션 로그에 보존, 구현 PR에서 뷰/함수로 정리 예정.)

## 15. 테스트 · shadow · 단계적 전환 계획

**필수 테스트 시나리오**(구현 PR 대상, fake clock/fake PG repository/fake provider,
실제 sleep·외부 API 없음): (1) 동시 2 caller가 합산 13건까지만 승인, (2) reservation
0건 상태에서 phantom insert 미발생, (3) DB 장애 시 fail-closed, (4) worker slot
확보 전 reservation 미소비, (5) reservation 후 HTTP 전 실패 시 quota 60초 소비 +
`reserved_but_http_not_started` 기록, (6) retry는 새 reservation 없이 HTTP 미실행,
(7) 임의 60초 구간 reservation/HTTP 시작 수 ≤ 13, (8) 수동/운영 caller가 같은
quota_scope 공유, (9) coordinator 없는 raw 호출 차단, (10) fake provider는
coordinator 없이도 정상 동작, (11) job 상태와 attempt 기록 수치 일관, (12) 40개/
120개 극단 조건의 dispatch 스케줄이 §10 계산과 일치.

**단계적 도입**: ① lifecycle 관측(quota_state/queue_jobs/attempts 스키마 + shadow
기록, 실제 dispatch 동작은 미변경) → ② held_position lane 한정 실전 전환 → ③ 전체
lane(core 포함) 전환. 각 단계에서 §14 SQL로 실측(FDC 대상 수/permit grant 수/queue
대기 분포/timeout/cancellation/HTTP attempt·429/cycle wall-clock/stale 차단/최종
decision·order 영향/lane 공정성)을 수행한다.

## 16. 위험 · 롤백 · 확정된 구현 계약 vs 구현 후 실측 필요

### 확정된 구현 계약(이번 문서로 확정, 구현 PR은 이를 그대로 따른다)
- Cycle-scoped(순차 유지), dispatcher 완전 소유 permit, PostgreSQL anchor-row
  atomic reservation, FDC one-shot 인터페이스 신설(공용 `generate_structured()`
  불변), 즉시 저장(배치 종료 대기 안 함), `CANCELLED` 사유 3종 한정, `fdc_queue_jobs`
  +`fdc_provider_attempts`+`fdc_quota_state` 3-테이블 스키마.

### 구현 후 실측 필요(이번 문서로 확정하지 않음, 값·성능은 구현 후 검증)
- `FDC_WORKER_CONCURRENCY=5`가 13 RPM을 실제로 소진하기에 충분한지.
- PG 행 잠금이 사이클 실제 트래픽에서 유발하는 지연 정도(이론상 미미하나 실측 없음).
- `MAX_RETRIES`→`max_http_attempts` 리네이밍의 전체 참조처 영향 범위.
- 두 분석 스크립트를 `LiveGeminiProviderClient`로 전환했을 때 기존 사용 방식(비교
  검증 등)에 미치는 영향.
- Gemini의 실제 quota 적용 단위(API 키/프로젝트/모델) — 외부 provider 정책, 이
  문서로 확정 불가.

### 롤백
전부 신규 테이블·신규 인터페이스 추가이며 기존 `fdc_rate_limiter.py`/`run_agent_
subprocess.py`의 기존 경로를 즉시 제거하지 않고 병행 가능(①단계 shadow 방식) —
문제 발생 시 신규 dispatcher 호출부만 되돌리면 기존 경로로 즉시 복귀 가능하다(구현
PR에서 feature flag로 전환 여부를 감쌀 것을 권고).
