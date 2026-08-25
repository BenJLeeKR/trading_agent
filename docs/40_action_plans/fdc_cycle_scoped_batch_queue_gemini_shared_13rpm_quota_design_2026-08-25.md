# FDC Cycle-Scoped Batch Queue + Gemini Shared 13 RPM Quota (PostgreSQL Atomic Reservation) — 설계 확정

> **상태(2026-08-25, Phase 1 구현 완료)**: 이 문서 §8의 영속 스키마(3-테이블),
> §6의 atomic reservation 로직, §11/§12의 shadow 관측 경로를 **Phase 1
> 범위로 구현 완료**했다 — `db/migrations/0068_add_fdc_quota_lifecycle_
> tables.sql`, `src/agent_trading/repositories/contracts.py`(`FdcQuotaRepository`
> Protocol), `src/agent_trading/repositories/postgres/fdc_quota.py`,
> `src/agent_trading/repositories/memory.py`(`InMemoryFdcQuotaRepository`),
> `src/agent_trading/services/fdc_quota_coordinator.py`(`FdcQuotaCoordinator`),
> `src/agent_trading/services/decision_orchestrator.py`(lifecycle shadow
> 관측 메서드). **실제 cycle-scoped dispatcher, FDC one-shot 인터페이스,
> live/fake provider 타입 분리, held_position lane 실제 전환은 아직
> 구현하지 않았다** — 이들은 후속 PR 범위다(§16 참고). 현재도 기존
> `fdc_rate_limiter.py`의 10 RPM strict limiter가 실제 Gemini HTTP 요청의
> 유일한 제한 장치이며, 이 문서의 13 RPM은 `FDC_BATCH_QUEUE_LIFECYCLE_
> SHADOW_ENABLED=true`일 때만 작동하는 **shadow 판단값**일 뿐 실제
> provider 호출량을 바꾸지 않는다.
>
> **개정 이력**: 2026-08-25(2차) — 최초 확정본에 남아있던 4개 계약 충돌(reservation
> 이중 소유 위험, 수동 호출 job 모델 미확정, retry/pre-HTTP 실패 계수 혼재, sliding
> 60초 경계 규칙 불일치)을 보정했다. §4·§6·§7·§8·§9·§11·§12·§14·§15가 이번 개정의
> 영향을 받는다(하단 각 절에 명시).
>
> **개정 이력**: 2026-08-25(3차) — accounting 정의 내부 불일치를 보정했다:
> `dispatch_attempt_no`가 "reservation을 실제로 받아 넘긴 횟수"(§9 정의)와
> "reservation 거부 시 증가"(사례 설명)로 서로 모순되게 서술돼 있던 문제를
> "성공 시에만 증가"로 통일하고, 이전에 accounting 표에만 있고 `fdc_queue_jobs`
> 스키마 표에는 누락됐던 `reservation_denied_count`를 스키마에 추가했다.
> §8·§9·§14·§15·§16이 이번 개정의 영향을 받는다.
>
> **개정 이력**: 2026-08-25(4차) — `queue_poll_count = reservation_denied_
> count + dispatch_attempt_no` 항등식과 DB/coordinator 오류 fail-closed
> 경로 사이의 불일치를 보정했다. coordinator 오류(DB unavailable/lock
> timeout/transaction 오류)는 `GRANTED`도 `DENIED`도 아니므로 이 세 카운터
> 중 어느 것도 증가시키지 않는다(A안 채택)는 것을 명시하고, coordinator
> 오류 전용 상태·backoff·최소 관측 계약을 신설했다. §5·§6·§9·§13·§15·§16이
> 이번 개정의 영향을 받는다.
>
> **개정 이력**: 2026-08-25(5차, PR #351 1차 보정) — Phase 1 초기 구현이
> `mode='real'` attempt만 세는 판정 로직을 그대로 shadow 경로에 재사용해
> shadow window_count가 항상 0이 되던 결함과, shadow 관측 시점이 기존 FDC
> permit 대기·HTTP 호출 이후(잘못된 시점)였던 결함을 보정했다. **정정된
> 표현**: "13 RPM이면 지금 승인됐을까"가 아니라 "**같은 cycle 내 앞선
> shadow FDC-ready job까지 포함한 FIFO 가상 큐에서 지금 승인 가능한가**"이다
> — 판정은 오직 같은 `quota_scope`의 `mode='shadow'` 행만 보고(`mode='real'`
> 행은 절대 보지 않음). **주의**: 이 개정에서 "FIFO 순서는 DB가 발급한
> `enqueue_sequence`(INSERT와 함께 원자적으로 채번)로 정하므로 Python
> task 완료 순서에 의존하지 않는다"고 서술했으나, 이는 **틀렸다** — DB
> INSERT 자체가 `assemble()` 도착 시점에 일어났기 때문에, INSERT 순서는
> 여전히 "여러 심볼이 동시 처리되는 중 어느 것이 먼저 `assemble()`에
> 도착했는가"(=기존 limiter 대기·provider 응답·subprocess 종료 순서에
> 좌우됨)를 반영했을 뿐, 진짜 `fdc_ready_at` 순서를 반영하지 못했다.
> 이 오류는 6차 개정에서 바로잡았다.
>
> **개정 이력**: 2026-08-25(6차, PR #351 2차 보정) — 5차 개정이 남긴
> "DB INSERT 순서가 곧 FDC-ready FIFO 순서"라는 서술을 정정했다. 실제
> FIFO 기준은 **`(fdc_ready_at, cycle_index)`**다 — `fdc_ready_at`이
> 1차 기준, 동일 시각이면 같은 cycle 내 `cycle_index`(universe 열거
> 시점에 고정, `asyncio.gather()`가 입력 순서를 그대로 보존하는 성질을
> 이용 — 어떤 subprocess/코루틴 완료 순서에도 의존하지 않음)가 2차
> tie-breaker다. 기존 limiter 대기 완료 순서·provider 응답 순서·
> subprocess 종료 순서·`assemble()` 호출 순서는 전혀 사용하지 않는다.
> 이를 구현하기 위해 `assemble()`은 더 이상 shadow를 DB에 직접 등록하지
> 않고(`FdcReadyShadowEvent`만 노출), 사이클의 모든 심볼 처리
> (`asyncio.gather()`)가 끝난 뒤 호출자(`run_decision_loop.py`)가 이
> 이벤트들을 `(fdc_ready_at, cycle_index)` 기준으로 정렬해 **순차** 재생한다
> — `enqueue_sequence`는 이제 이 정렬된 재생 순서를 그대로 반영하는
> 값이며, 더 이상 "단순 도착 순서"를 의미하지 않는다. `decision_cycle_id`
> 도 `request.correlation_id`(심볼별 고유 문자열)에서 진짜 cycle-scoped
> 식별자로 교체했다. 자동 dispatcher가 아직 없으므로 Phase 1이 신뢰성
> 있게 관측하는 것은 여전히 "**즉시 shadow grant 가능**"(`SHADOW_WOULD_
> GRANT`)과 "**shadow queued**"(`SHADOW_QUEUED`) 두 상태뿐이며, "몇 분
> 후 실제로 grant될지"는 후속 dispatcher 단계(§16 "구현 후 실측 필요")
> 범위다. `SHADOW_QUEUED`는 실패·timeout이 아니다. 상세는 `docs/30_
> work_log/2026-08-25_fdc_quota_lifecycle_shadow_phase1_correction_2.md`
> 참고.

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

> **보정 1(reservation 단일 소유권, 2026-08-25 2차)**: "dispatcher가 permit을
> 완전히 소유한다"는 문장이 §12의 `LiveGeminiProviderClient.generate_structured_
> once()`도 coordinator를 호출한다는 서술과 병존해 이중 reservation처럼 읽힐
> 여지가 있었다. **정확한 계약은 다음과 같다**: quota coordinator에게 실제로
> reservation을 요청하는 주체는 **dispatcher 하나뿐**이다. dispatcher가 요청해
> 발급받은 `ReservationGrant`(§6)를 FDC one-shot 호출에 **값으로 전달**하고,
> `generate_structured_once(grant)`는 그 grant를 **소비만** 할 뿐 coordinator에게
> 새 reservation을 절대 요청하지 않는다. 즉 "provider client도 coordinator를
> 호출한다"는 것은 "결과를 attempt row에 기록하기 위해 같은 DB 접근 계층을
> 쓴다"는 뜻이지 "reservation을 다시 얻는다"는 뜻이 아니다 — 상세 계약과
> `generate_structured()`/`generate_structured_once()`의 reservation 경로 분리는
> §12에서 표로 확정한다.

## 5. 상태 전이도

> **보정 3(retry/pre-HTTP 실패 계수 분리, 2026-08-25 2차) 반영**: 아래 상태
> 전이도는 `RETRY_QUEUED`를 발생 사유별로 분리해 표기한다 — HTTP가 실제로
> 시작된 뒤의 재등록(`provider_retry_count` 증가)과, reservation은 받았으나
> HTTP 시작 전에 실패한 재등록(`pre_http_execution_failure_count` 증가)은
> **서로 다른 계수**이며, 둘 다 FIFO tail 재등록이라는 점만 같다(§9 참고).

```
[Job lifecycle]
QUEUED
  → (worker slot 확보 성공 && quota reservation 성공 → ReservationGrant 발급)
  → RESERVATION_GRANTED
  → FDC_RUNNING(발급받은 grant로 HTTP one-shot 실행 — 새 reservation 요청 없음)
    → HTTP_SUCCEEDED → FDC_SUCCEEDED → 즉시 assemble()/저장
    → HTTP_FAILED_RETRYABLE(429/5xx/timeout/DNS)
        → provider_retry_count += 1
        → RETRY_QUEUED(provider 사유, 새 queue_entry_id, FIFO tail) → QUEUED로 복귀
        → (provider_retry_count가 max_http_attempts-1=2 소진)
            → FDC_FAILED_FINAL(reason=provider_429_exhausted|provider_5xx_exhausted|provider_timeout_exhausted)
    → HTTP_FAILED_NONRETRYABLE(4xx/파싱오류) → FDC_FAILED_FINAL(즉시, reason=provider_nonretryable)
  → (reservation 성공 후 HTTP 시작 전 worker/subprocess 생성 실패)
      → RESERVED_BUT_HTTP_NOT_STARTED(quota는 그 60초 동안 계속 소비된 것으로 기록)
      → pre_http_execution_failure_count += 1
      → (pre_http_execution_failure_count가 max_pre_http_execution_failures 미만)
          → RETRY_QUEUED(pre-HTTP 사유, 새 queue_entry_id, FIFO tail) → QUEUED로 복귀
      → (소진) → FDC_FAILED_FINAL(reason=worker_start_exhausted)
  → (coordinator 호출이 COORDINATOR_UNAVAILABLE/COORDINATOR_LOCK_TIMEOUT/
     COORDINATOR_TRANSACTION_ERROR로 실패, 보정 4차 — §6 "coordinator 오류
     경로" 참고)
      → worker slot 즉시 반환, job은 QUEUED 유지(탈락 아님)
      → 지수 backoff 후 재시도(queue_poll_count/reservation_denied_count/
        dispatch_attempt_no 어느 것도 증가하지 않음 — 로그/in-memory
        counter로만 관측)
CANCELLED ← 시장 종료 / 운영자 명시 취소 / 프로세스 종료(오직 이 세 사유만 —
             coordinator 오류가 아무리 지속돼도 이 사유가 자동 추가되지 않음)
```

`queue_reenqueue_count = provider_retry_count + pre_http_execution_failure_count`
(§9) — 위 두 재등록 경로를 합친 값으로, "FIFO tail에 총 몇 번 다시 섰는지"를
보고 싶을 때만 참조하는 파생 지표다. 상태 전이의 종결 사유(`FDC_FAILED_FINAL`의
`reason`)는 항상 두 계수 중 **어느 쪽이 소진됐는지**로 명확히 구분된다 — 어느
경로든 순번 탈락이나 `CANCELLED`가 아니다.

```
[Cycle lifecycle]
전 종목 pre-FDC(EI/AR/AC) 완료
  → FDC-ready job 전원 QUEUED
  → dispatcher 반복(전원 종결 상태 도달까지, deadline 없음 — 명시적 취소만 종료 사유)
  → 사이클 종료 → interval(900초) sleep → 다음 사이클
```

`provider_queue_timeout`이라는 기존 reason code는 **이 신규 경로에서 사용하지
않는다** — 순번 대기로 인한 확정 실패라는 개념 자체가 새 계약에는 존재하지 않는다.

## 6. Atomic reservation transaction 계약

> **보정 1 반영**: 이 트랜잭션의 유일한 호출자는 **dispatcher**다. 트랜잭션이
> 성공하면 dispatcher는 `ReservationGrant(reservation_id, quota_scope, job_id,
> attempt_no)`를 발급받아 FDC one-shot 호출에 값으로 전달한다. one-shot은 이
> grant의 네 필드가 자신이 실행하려는 job과 일치하는지 검증한 뒤 HTTP 1회만
> 실행하며, **coordinator에게 새 reservation을 절대 요청하지 않는다**(§12 표
> 참고).

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
    INSERT INTO fdc_provider_attempts(attempt_id, job_id, quota_scope, attempt_no, ...,
      outcome='reservation_granted', reserved_at=now())
      RETURNING attempt_id AS reservation_id;
    UPDATE fdc_queue_jobs SET status='reservation_granted', ... WHERE job_id=...;
    -- dispatcher는 이 reservation_id를 ReservationGrant에 담아 FDC one-shot에 전달한다.
  ELSE:
    ROLLBACK;  -- job은 QUEUED에 그대로 남는다. 탈락이 아니다.

COMMIT;
-- ── 불변식: 이 COMMIT 이전에 Gemini HTTP 호출이 발생하지 않는다.
--    트랜잭션/행 잠금을 쥔 채 네트워크 I/O를 수행하지 않는다.
--    commit 이후에만 worker가 즉시 HTTP one-shot을 시작한다.
```

- **DB 장애/lock timeout/트랜잭션 오류 시**: live Gemini HTTP 호출은 **fail-closed**
  — coordinator에 접근할 수 없으면 그 job은 시도하지 않고 `QUEUED`에 남는다(탈락
  아님, 다음 재시도 기회를 기다림). 상세 계약은 바로 아래 "coordinator 오류 경로"
  절에서 확정한다.

### coordinator 오류 경로(보정, 4차 개정 — `queue_poll_count` 항등식과의 충돌 해소)

**충돌 확인**: 이전 초안은 `queue_poll_count = 모든 reservation 확인 시도`와
`queue_poll_count = reservation_denied_count + dispatch_attempt_no`를 동시에
정의했는데, coordinator 오류(DB unavailable/lock timeout/transaction 오류)는
`GRANTED`도 `DENIED`도 아닌 **"결론 자체를 받지 못한" 시도**라 이 항등식에
끼워 넣을 자리가 없었다.

**A/B 비교**:

| 안 | 설명 | 평가 |
|---|---|---|
| **A(채택)** | `queue_poll_count`를 "coordinator가 정상적으로 `GRANTED`/`DENIED` 결론을 반환한 시도"로 재정의. 오류는 이 세 카운터에 전혀 포함하지 않고 별도 로그/메트릭으로만 관측 | DB 자체가 unavailable이면 `fdc_queue_jobs` row를 UPDATE할 방법이 없다는 근본 제약과 정확히 들어맞는다 — "저장할 수 없는 값을 저장하기로 계약해두는" 모순을 피한다 |
| B(`reservation_error_count` 추가, `queue_poll_count = denied + dispatch + error`) | 오류도 영속 카운터로 관리 | **기각** — DB 자체가 내려간 상황에서 "이 job의 `reservation_error_count`를 `+1`하라"는 UPDATE 자체를 실행할 수 없다. 즉 B안이 요구하는 영속 저장이 정확히 그 순간에 불가능한 경우가 이 오류 경로의 **핵심 시나리오**라, "정의는 있으나 저장할 수 없는 필드"라는 자기모순이 생긴다 |

**확정 계약(A안)**:
```
queue_poll_count:
  coordinator가 정상적으로 GRANTED 또는 DENIED 결론을 반환한 횟수만 계산

reservation_denied_count:
  정상 coordinator 응답 중 quota가 가득 차 DENIED된 횟수

dispatch_attempt_no:
  정상 coordinator 응답 중 GRANTED되어 ReservationGrant가 발급된 횟수

queue_poll_count = reservation_denied_count + dispatch_attempt_no
  (오류 경로는 이 항등식 계산에 전혀 참여하지 않으므로 오류가 아무리 나도 깨지지 않는다)
```

**coordinator 오류 상태와 동작(확정 계약)**:
```
QUEUED
  → coordinator 호출(§6 트랜잭션 시도)
  → COORDINATOR_UNAVAILABLE(DB 연결 자체 실패)
    또는 COORDINATOR_LOCK_TIMEOUT(anchor 행 잠금 대기 초과)
    또는 COORDINATOR_TRANSACTION_ERROR(그 외 트랜잭션 실행 오류)
  → Gemini HTTP 미호출(fail-closed)
  → local worker slot 즉시 반환
  → job은 QUEUED 유지
  → backoff 후 재시도(아래 backoff 원칙)
```

1. **오류 분류**: `COORDINATOR_UNAVAILABLE`/`COORDINATOR_LOCK_TIMEOUT`/
   `COORDINATOR_TRANSACTION_ERROR` 3종으로 분류한다. 이 분류는 **DB row가
   아니라 프로세스 로그/메트릭 계층에서만** 기록된다(A안의 핵심 — DB 자체가
   내려간 경우 이 분류값을 그 job의 DB row에 영속 기록할 수 없으므로, 애초에
   그런 계약을 하지 않는다).
2. **`CANCELLED`/`FDC_FAILED_FINAL`/`provider_queue_timeout`이 아닌 이유**:
   - `CANCELLED`가 아닌 이유: `CANCELLED`는 시장 종료/운영자 명시 취소/프로세스
     종료 **오직 세 사유만**으로 한정된 확정 계약(§5)이다 — infra 오류는 이
     셋 중 어디에도 해당하지 않고, job에게 다시 기회를 줘야 하므로 종결
     상태로 보내지 않는다.
   - `FDC_FAILED_FINAL`이 아닌 이유: 이 상태는 **provider(Gemini) 자신의
     실패**(HTTP가 실제로 나갔으나 429/5xx/파싱오류 등으로 실패)를 뜻하는데,
     coordinator 오류는 HTTP 시도 자체가 발생하기 **이전** 단계의 인프라
     문제라 provider 실패와 원인이 다르다.
   - `provider_queue_timeout`이 아닌 이유: 이 reason code는 폐기된 구
     FIFO 설계(§5)의 "시간 경과로 인한 포기" 개념이다. 새 계약에는 "시간이
     지나서 포기"라는 개념 자체가 없으므로 이 이름을 재사용하지 않는다.
3. **worker slot 반환 시점**: coordinator 호출이 예외로 실패하는 **즉시**
   (reservation `DENIED`를 받았을 때와 동일한 원칙 — worker slot을 쥐고
   backoff 대기까지 하지 않는다, §7의 실행 순서와 일치).
4. **hot-loop 방지 backoff 원칙**: **지수 백오프(exponential backoff)를
   권고**한다(고정 간격이 아님) — DB 장애가 지속되는 동안 고정 짧은 간격으로
   재연결을 반복하면 이미 불안정한 DB에 재연결 시도 자체가 부하를 더해
   회복을 늦출 위험이 있다. 권고 초기값 1초, 배수 2, **상한 30초**(신규 설정
   `FDC_COORDINATOR_ERROR_BACKOFF_MAX_SECONDS`, 구현 PR에서 배선). 이 backoff은
   **그 job 하나의 재시도 간격**이며, cycle 전체는 사이클-scoped 순차 모델
   그대로 이 job(과 같은 처지의 다른 job들)이 종결 상태에 도달할 때까지
   순차적으로 대기한다(§4의 순차 cycle 원칙과 동일 — cycle이 병행되지
   않는다는 계약은 DB 오류 상황에서도 변하지 않는다).
5. **DB 복구 후 재시도 조건**: 별도의 "복구 확인" 절차는 두지 않는다 —
   backoff이 끝난 뒤 다음 폴링 시도가 §6 트랜잭션을 그대로 다시 실행하고,
   DB가 응답 가능한 상태로 돌아와 있으면 그 시도가 곧 "정상적인 `GRANTED`
   또는 `DENIED` 응답"이 되어 `queue_poll_count`에 자연스럽게 편입된다.
6. **DB 자체가 내려가 DB row 기록도 불가능한 경우의 최소 관측 근거**(A안의
   핵심 트레이드오프, 구현 후 실측 필요 항목으로도 별도 명시):
   - **프로세스 로그**: dispatcher 프로세스가 구조화된 로그 라인(오류
     분류/`job_id`/타임스탬프)을 표준 출력/로그 파일에 남긴다 — DB와
     무관한 유일한 즉시 기록 수단.
   - **in-memory counter**: dispatcher 프로세스 메모리 안에서만 오류
     발생 횟수를 집계한다 — **재기동 시 소실되는 휘발성 정보**임을
     명시한다(직전 개정에서 확립한 "휘발성 정보 허용" 원칙과 동일선상).
   - **scheduler cycle summary**: 사이클 종료 시 그 사이클 동안 발생한
     coordinator 오류 총량을 in-memory counter로부터 집계해 1줄 로그로
     요약 출력한다(DB 저장 아님, 로그 전용).
   - **DB 복구 후 final job 상태 기록**: DB가 복구된 뒤에는 해당 job의
     `fdc_queue_jobs` row가 정상적으로 계속 갱신되므로, "그 job이 결국
     `FDC_SUCCEEDED`/`FDC_FAILED_FINAL`/`CANCELLED` 중 무엇으로 끝났는가"는
     DB에 남는다 — 다만 **그 사이에 있었던 개별 오류 발생 횟수 자체**는
     DB에 남지 않고 로그로만 남는다는 한계를 명시적으로 인정한다.
7. **DB 오류가 장기간 지속될 때 cycle의 무한 대기 허용 여부**: 사용자의
   "순번이 늦다는 이유로 탈락하지 않는다"는 요구와 **DB 장애로 인한 대기는
   원인이 다르지만, 계약상으로는 동일하게 다뤄진다** — 둘 다 "명시적
   취소 사유(시장 종료/운영자/프로세스 종료) 외에는 시간 경과만으로 자동
   종료하지 않는다"는 원칙을 따른다. 즉 **새로운 자동 시간제한(예: "DB
   오류가 N분 지속되면 자동으로 `CANCELLED`")은 도입하지 않는다** — 이는
   §5가 이미 확정한 "`CANCELLED` 사유 3종 한정"과 상충하기 때문이다. 다만
   이것이 실무적으로 "장애가 나면 그날 장이 끝날 때까지 사이클이 멈춰
   있을 수 있다"는 운영 위험을 그대로 남긴다는 뜻이므로, **이 경우 운영자가
   기존 `CANCELLED(operator_cancel)` 경로로 수동 개입**하는 것을 표준
   대응 절차로 문서화한다(자동 메커니즘 신설이 아니라 기존 사유를 수동으로
   발동하는 운영 절차 — 구현 후 실측/운영 런북 대상, 12절 미확인 사항에도
   중복 명시).

- **60초 경계의 판단 SQL과 사후 검증 SQL 일치(보정 4)**: 판단 SQL은 `reserved_at
  > now() - interval '60 seconds'`(반열림 구간 `(t-60초, t]`, 즉 **정확히 60초
  이전 시각의 reservation은 이번 window에서 제외**된다 — `>`이지 `>=`가 아니다).
  §14의 사후 검증 SQL은 이전 초안에서 `RANGE BETWEEN INTERVAL '60 seconds'
  PRECEDING AND CURRENT ROW` window frame을 썼는데, 이 frame은 **경계값을
  포함**해 판단 SQL의 반열림 규칙과 불일치했다 — §14에서 self-join 기반으로
  같은 `>` 규칙을 쓰도록 정정했다. coordinator 판단, 사후 감사 SQL, fake clock
  테스트(§15) **셋 모두 이 반열림 규칙을 동일하게 적용**하는 것이 13 RPM strict
  계약의 일부다.

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

> **보정 1 반영**: "PostgreSQL atomic reservation" 단계는 dispatcher가
> §6 트랜잭션으로 `ReservationGrant`를 발급받는 것을 뜻하며, "즉시 FDC one-shot
> HTTP 실행" 단계는 그 grant를 값으로 전달받아 소비만 한다 — one-shot 내부에서
> coordinator를 다시 호출하지 않는다(§12 표).

- **reservation 거부**: worker slot 즉시 반환, job은 `QUEUED` 유지.
- **reservation 성공 후 worker 시작 실패**: `RESERVED_BUT_HTTP_NOT_STARTED` 기록
  (quota는 60초간 소비 유지), `pre_http_execution_failure_count`(§9)를 1 증가시킨다.
  `max_pre_http_execution_failures`(신규 설정, 권고 초기값 3) 소진 전엔
  `RETRY_QUEUED`, 소진 시 `FDC_FAILED_FINAL(reason=worker_start_exhausted)` —
  **이 종료는 순번 탈락도 `CANCELLED`도 아닌, `provider_retry_count`와 무관하게
  별도로 집계되는 내부 실행 실패 사유다(보정 3).**
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
| `queue_poll_count`, `reservation_denied_count`, `dispatch_attempt_no` | §9 정의(**보정 A** — `reservation_denied_count`가 이전 초안의 스키마 표에서 누락돼 있었음, 이번 개정으로 추가) |
| `provider_retry_count`, `pre_http_execution_failure_count`, `queue_reenqueue_count` | **보정 3** — §9에서 3개로 분리 정의(기존 단일 `retry_count` 폐기) |
| `permit_consumed_count`, `http_attempt_count`, `http_429_count`, `reserved_but_http_not_started_count` | §9 정의 |
| `queued_at`, `completed_at` | |
| `trade_decision_id` | nullable FK → `trade_decisions` |
| `failure_or_cancel_reason` | nullable |
| `created_at`, `updated_at` | |

**`reservation_denied_count`의 저장 위치(보정 — A안 채택)**: 이 필드는 `fdc_queue_
jobs`에 저장한다(대안 B — 별도 event 테이블만으로 재구성하는 안은 채택하지 않음.
이유: 거부는 "이 job이 몇 번이나 순서를 기다리며 밀렸는지"를 나타내는 job 단위
누적 카운터일 뿐, `fdc_provider_attempts`(reservation **성공** 1건=1행 원칙, §8
"원칙" 참고)에 넣으면 "성공한 attempt만 기록한다"는 그 테이블의 불변식이 깨진다).
- **초기값**: `0`(job이 `QUEUED`로 INSERT될 때).
- **증가 시점**: coordinator가 §6 트랜잭션에서 `count ≥ 13`으로 `DENIED`를
  반환할 때마다, 그 job의 `fdc_queue_jobs.reservation_denied_count`를 원자적으로
  `+1`한다(같은 UPDATE 문 안에서 `queue_poll_count`도 함께 `+1`, `dispatch_
  attempt_no`는 증가시키지 않음 — 아래 불변식 참고). **주의**: `DENIED`(정상
  응답)와 coordinator 오류(DB unavailable 등, §6 "coordinator 오류 경로")는
  다른 개념이다 — `DENIED`만 이 카운터를 증가시키고, 오류는 이 카운터에
  전혀 관여하지 않는다(§9의 4차 보정 참고).
- **사용 목적**: `reservation_denied_count`가 특정 lane(예: held_position)이나
  특정 사이클에서 유독 높게 나오면 "그 lane의 job들이 quota 경쟁에서 계속 밀리고
  있다"는 lane 공정성 신호가 된다 — ①단계(lifecycle 관측 shadow, §15)에서 배포
  전 기준선을 잡고, ②③단계 실전 전환 후 이 값의 lane별 분포 변화를 비교하는
  것이 배포 후 실측 계획(§15)의 핵심 지표 중 하나다.
- **job 상태와 attempt 행 집계의 정합성 검증**: `reservation_denied_count`는
  정의상 `fdc_provider_attempts`에 대응 행이 없으므로(거부는 attempt로 기록되지
  않음), 이 필드의 정합성은 다른 방식으로 검증한다 — `queue_poll_count =
  reservation_denied_count + dispatch_attempt_no`(폴링 시도는 거부 아니면
  성공 둘 중 하나로만 귀결되므로)라는 항등식을 job별로 SQL 검증한다(§14).

### `fdc_provider_attempts`(신규, append-only — reservation 1회=attempt 1행)
| 컬럼 | 비고 |
|---|---|
| `attempt_id` | UUID PK(= `reservation_id`로도 사용, §6) |
| `job_id` | **nullable** FK → `fdc_queue_jobs`(보정 2 — 비운영 수동 호출은 `fdc_queue_jobs` row 자체를 만들지 않으므로 NULL 허용) |
| `manual_run_id` | nullable, 수동 호출 전용 식별자(§11, `job_id`가 NULL일 때만 사용) |
| `quota_scope`, `caller_id`(`"ops-scheduler"` / `"manual:<script명>"`), `queue_entry_id` | |
| `attempt_no`, `provider_retry_count` | 이 attempt가 몇 번째 provider retry인지(§9) — pre-HTTP 재시도 횟수는 여기 담지 않고 `fdc_queue_jobs.pre_http_execution_failure_count`로만 집계(attempt row는 매 재시도마다 새로 생기므로 job 쪽에서 누적) |
| `reserved_at`, `http_started_at`(nullable), `completed_at`(nullable) | `(quota_scope, reserved_at)` 인덱스 필수(§14 self-join 감사용) |
| `outcome`, `http_status`(nullable), `error_class`(nullable), `http_429_observed` | |
| unique 제약 `(job_id, attempt_no)` | `job_id IS NOT NULL`일 때만 의미(운영 FDC), 수동 호출은 `(manual_run_id, attempt_no)`로 별도 unique 고려 — 구현 PR에서 부분 unique index로 확정 |

**테이블 이름 확정(보정 2 반영)**: `job_id`가 nullable이고 `caller_id`/`manual_
run_id`로 이미 운영·수동 트래픽을 함께 수용하는 범용 구조이므로, **테이블 이름을
`gemini_provider_attempts`로 바꾸지 않고 `fdc_provider_attempts`를 유지**한다 —
FDC가 이 quota_scope의 유일한 운영 소비자이고, 수동 호출은 예외적 부가 사용자일
뿐이라 이름을 일반화할 실익이 적다고 판단했다(구현 PR에서 재검토 가능).

**원칙**: attempt row는 reservation 시 INSERT하고, 이후 같은 row를 HTTP 시작/종료
정보로 UPDATE한다(하나의 "실행 기회"는 하나의 사건이므로 별도 event 테이블로 더
쪼개지 않는다 — 현재 규모에서 과잉 정규화). **삭제·재사용 없음**(append-only).

## 9. Accounting 정의(확정, 보정 3 반영 — retry 계수 3분리)

| 필드 | 정의 |
|---|---|
| `queue_poll_count` | **coordinator가 정상적으로 `GRANTED` 또는 `DENIED` 결론을 반환한** 확인 시도 횟수(보정 — coordinator 오류로 결론 자체를 못 받은 시도는 포함하지 않는다, §6·§9 하단 오류 경로 참고) |
| `reservation_denied_count` | 정상 coordinator 응답 중 13 RPM window가 가득 차 `DENIED`를 받은 횟수 |
| `dispatch_attempt_no` | 정상 coordinator 응답 중 `GRANTED`되어 `ReservationGrant`가 발급된 횟수 — `DENIED` 시에는 증가하지 않는다(보정, 이전 초안의 모순 표현 정정) |
| **`provider_retry_count`** | 실제 HTTP가 **시작된 뒤** retryable provider 오류(429/5xx/timeout/DNS)로 FIFO tail에 재등록된 횟수 — `http_started_at IS NOT NULL`인 attempt에서만 증가 |
| **`pre_http_execution_failure_count`** | reservation 성공 후 **HTTP 시작 전**(`http_started_at IS NULL`)에 worker/subprocess 생성·취소 등으로 실패해 재등록된 횟수 |
| **`queue_reenqueue_count`** | `= provider_retry_count + pre_http_execution_failure_count`(파생 지표, "FIFO tail에 총 몇 번 재등록됐는지"만 알고 싶을 때 참조) |
| `permit_consumed_count` | 성공 reservation 수(`fdc_provider_attempts`에 `reservation_granted` 이상으로 기록된 행 수) |
| `http_attempt_count` | `http_started_at IS NOT NULL`인 attempt 수 |
| `http_429_count` | `http_status=429`인 attempt 수 |
| `reserved_but_http_not_started_count` | `outcome='reserved_but_http_not_started'`인 attempt 수(= `pre_http_execution_failure_count`의 attempt-행 기준 합계와 일치해야 함, §14 정합성 검증 대상) |

**불변식(보정 후 확정)**:
```
provider_retry_count <= max_http_attempts - 1        (= 2, MAX_RETRIES=3 기준)
pre_http_execution_failure_count <= max_pre_http_execution_failures
queue_reenqueue_count = provider_retry_count + pre_http_execution_failure_count
http_attempt_count <= permit_consumed_count
queue_poll_count = reservation_denied_count + dispatch_attempt_no   (보정 — 폴링 시도는 거부/성공 둘 중 하나로만 귀결)
reservation count <= 13 per any sliding 60-second window  (§6 트랜잭션이 보장)
```

**reservation 거부/성공 시 정확한 증가 규칙(보정, 이전 초안의 모순 정정)**:
```
reservation denied(coordinator가 count>=13으로 DENIED 반환):
  queue_poll_count += 1
  reservation_denied_count += 1
  dispatch_attempt_no 증가 없음
  permit_consumed_count 증가 없음
  http_attempt_count 증가 없음
  job은 QUEUED 유지(§6 ROLLBACK 경로)

reservation granted(coordinator가 count<13으로 승인, ReservationGrant 발급):
  queue_poll_count += 1
  dispatch_attempt_no += 1
  permit_consumed_count += 1
  (이후 실제 HTTP 시작 여부는 §7의 worker 실행 결과에 달려 있으며, 그 결과에
   따라 http_attempt_count 또는 pre_http_execution_failure_count가 추가로
   증가한다 — 아래 사례 참고)

coordinator error(DB unavailable / lock timeout / transaction 오류 — GRANTED도
DENIED도 아닌 "결론 자체를 못 받은" 경우, 아래 §6-보정 참고):
  queue_poll_count 증가 없음
  reservation_denied_count 증가 없음
  dispatch_attempt_no 증가 없음
  → 이 세 카운터의 항등식(queue_poll_count = reservation_denied_count +
    dispatch_attempt_no)은 오류 경로에서 애초에 셋 다 건드리지 않으므로
    깨지지 않는다.
```

**세 계수가 항상 같지 않은 이유(사례별)**:
- `reservation_denied_count`만 증가하고 `dispatch_attempt_no`/`permit_consumed_
  count`/`http_attempt_count`는 불변 — reservation이 **거부**된 경우(worker
  slot만 반환, HTTP는 애초에 시도되지 않음, 위 불변식 참고).
- `dispatch_attempt_no`와 `permit_consumed_count`는 증가했으나 `pre_http_
  execution_failure_count`만 추가로 증가 — reservation은 받았으나 worker 시작
  자체가 실패한 경우(`http_attempt_count`는 불변).
- `dispatch_attempt_no`/`permit_consumed_count`/`http_attempt_count`/
  `provider_retry_count`가 모두 증가 — HTTP가 실제로 나갔으나 429/5xx로
  실패한 경우.

이전 초안의 단일 `retry_count`는 위 두 계수를 혼재시켜 `retry_count ≤ max_http_
attempts-1` 불변식이 pre-HTTP 실패 재등록까지 포함하면 깨지는 문제가 있었다 —
이번 보정으로 **`retry_count`라는 이름은 이 문서에서 더 이상 쓰지 않는다**(전부
`provider_retry_count`/`pre_http_execution_failure_count`/`queue_reenqueue_
count` 중 하나로 대체).

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

## 11. 수동 provider 호출 정책(확정, 보정 2 — A안 채택으로 정정)

**정책 비교**:

| 안 | 평가 |
|---|---|
| **A(운영 중 기술적 fail-closed 차단, 비운영 수동 호출은 coordinator reservation만 사용하고 FDC queue job은 만들지 않음)** | **채택** — 운영 FDC 판단 기회를 전혀 지연시키지 않는다(수동 호출이 FDC FIFO에 아예 들어오지 않으므로 worker slot·FIFO 순서 경쟁 자체가 없음). `fdc_queue_jobs.job_id` FK는 항상 실제 FDC job만 가리키면 되므로 정합성이 단순하다. 구현 복잡성 최소(synthetic job lifecycle을 별도로 설계할 필요 없음). 13 RPM strict는 quota_scope 공유만으로 유지된다 |
| B(수동 호출도 synthetic `fdc_queue_job`을 만들어 FDC와 같은 전역 FIFO에 편입) | 기각 — synthetic job의 lifecycle·source_type·우선순위·worker slot 정책을 전부 새로 정의해야 하는데, 수동 분석 호출은 애초에 FDC의 실행 결과(assemble/저장)와 결합될 필요가 없어 "FDC job"이라는 개념 자체가 이 트래픽에 맞지 않는다. 정의가 불완전한 채로 채택하지 않는다(사용자 지침대로 B안은 완전한 정의가 없으면 배제) |

**이전 초안 정정**: "수동 호출도 `fdc_queue_jobs.job_id`가 필요하다"는 이전 문장을
**폐기**한다. 확정 정책은 다음과 같다.

1. **운영 시간(정규장 중) 수동 live provider 호출은 기술적으로 차단된다** —
   절차적 금지 문구만으로 충분하다고 서술하지 않는다. 기술적 강제는 §12의
   `LiveGeminiProviderClient` 생성자가 coordinator 없이는 인스턴스화 자체를
   거부하는 것과, coordinator 쪽에서 운영 시간대에는 `caller_id`가
   `"manual:*"`인 reservation 요청을 무조건 거부(fail-closed)하는 것 **둘
   다**로 구성한다(운영 시간 판정은 기존 `Market-hours` 관련 코드/설정을
   재사용 — 이번 문서에서 새로 발명하지 않음, 구현 PR에서 정확한 재사용
   지점을 확인).
2. **비운영 시간 수동 호출**은 공용 quota coordinator를 통해 `reservation`을
   얻는다 — 즉 `fdc_quota_state`(§6)의 같은 anchor 행을 잠그고 같은 60초
   sliding window 집계에 참여한다. 다만 **FDC batch dispatcher의 FIFO 큐나
   `FDC_WORKER_CONCURRENCY` slot을 전혀 점유하지 않는다** — 수동 호출은 자체
   프로세스 안에서 스스로 worker 역할을 겸한다.
3. 비운영 수동 호출의 provider attempt는 `fdc_provider_attempts.job_id=NULL`,
   `manual_run_id`(호출 시각+스크립트명 기반, 구현 PR에서 생성 규칙 확정)로
   연결한다(§8).
4. 위 3번에 따라 `fdc_provider_attempts.job_id`는 **nullable**이다(§8에서
   이미 반영). 테이블 이름은 `fdc_provider_attempts`를 유지한다(§8 근거).
5. `fdc_queue_jobs`에는 수동 호출 row를 **만들지 않는다** — 이 테이블은 순수
   FDC batch job 전용으로 남는다.

**수동 트래픽이 FDC 판단 기회를 늦추지 않는 방법**: A안 채택으로 수동 호출은
FDC FIFO에 전혀 편입되지 않으므로 "늦춘다"는 상황 자체가 구조적으로 발생하지
않는다 — 유일한 공유 지점은 `fdc_quota_state` anchor 행의 60초 sliding window
집계뿐이며, 운영 시간대에는 그 지점조차 fail-closed로 차단되므로 실질적인
경쟁이 없다.

## 12. Live provider fail-closed 경계(확정, 보정 1 — reservation 경로 표로 명확화)

- 실제 Gemini HTTP를 낼 수 있는 구현체(`LiveGeminiProviderClient`, 신규 명명 제안)는
  **coordinator 의존성 없이는 생성·실행 불가능**하게 한다(생성자 필수 인자).
- fake/test provider는 **별도 구현체**(`FakeProviderClient`)로 분리 — `live_provider
  =False` 같은 **플래그 방식은 채택하지 않는다**(오설정 우회 위험, 사용자 지적 반영).
- FDC 전용 `generate_structured_once()`는 dispatcher가 permit/retry/backoff를
  전담하기 위한 **최소 신규 인터페이스**다. 기존 공용 `generate_structured()`(EI/AR/
  AC 구식 클래스가 참조하나 운영 비활성)는 **무근거로 변경하지 않는다**.
- raw provider client 직접 호출(`ar_fdc_provider_validation.py` 등)과 두 분석
  스크립트 모두 **같은 강제 지점**(`LiveGeminiProviderClient` 생성자)을 통과해야
  하므로 개별적으로 막을 필요가 없다.

**reservation 경로 분리표(보정 1의 핵심 산출물)** — 어느 함수가 coordinator에게
"새 reservation을 요청"하는지, 아니면 "이미 발급된 grant를 소비만" 하는지를
명확히 구분한다:

| 호출 경로 | reservation을 새로 요청하는가? | 실행 주체 |
|---|---|---|
| FDC batch dispatcher | **예** — §6 트랜잭션의 유일한 호출자 | dispatcher(cycle-scoped) |
| `generate_structured_once(grant)`(FDC 전용, 신규) | **아니오** — dispatcher가 전달한 `ReservationGrant`를 검증·소비만 함, coordinator를 호출하지 않음 | FDC worker(HTTP 1회) |
| `generate_structured()`(공용, 기존 유지) | **경로에 따라 다르다** — 운영 EI/AR/AC 경로에서는 애초에 호출되지 않음(비활성). 비운영 수동 스크립트가 이 함수를 직접 쓴다면, `LiveGeminiProviderClient`가 **자체적으로** coordinator에 reservation을 요청(운영 시간대엔 fail-closed 거부, §11 정책 1) | 수동 스크립트 프로세스 |
| raw HTTP client(coordinator 완전 우회 시도) | 시도 자체가 **생성 단계에서 차단**(`LiveGeminiProviderClient` 생성자가 coordinator 의존성 없이는 인스턴스화 거부) | — |

이 표가 **보정 1의 확정 계약**이다: dispatcher가 발급받은 reservation을 FDC
one-shot이 다시 요청하는 이중 소유는 구조적으로 발생하지 않으며, `generate_
structured()`는 FDC 배치 경로에서는 아예 쓰이지 않고 오직 "coordinator를
직접 호출하는 다른 경로"(비운영 수동 스크립트)에서만 자체 reservation을 요청
한다 — 두 함수가 "같은 job에 대해 동시에" reservation을 다투는 경우가 없다.

## 13. 설정 계약(확정, 값은 구현 PR에서 실제 배선)

| 키 | 기본값 | 용도 |
|---|---|---|
| `FDC_PROVIDER_TARGET_RPM` | `13` | 운영 목표 |
| `FDC_PROVIDER_RATE_WINDOW_SECONDS` | `60` | sliding window 길이 |
| `GEMINI_PROVIDER_DECLARED_RPM_LIMIT` | `15` | 문서/startup validation 전용(코드가 강제 호출하는 값 아님) |
| `FDC_WORKER_CONCURRENCY` | `5`(실측 전 보수적 시작값) | FDC 전용 동시 실행 수 |
| `FDC_QUOTA_COORDINATOR_BACKEND` | `"postgres"` | 백엔드 선택(현재 단일 값만 지원) |
| `FDC_COORDINATOR_ERROR_BACKOFF_INITIAL_SECONDS` | `1` | coordinator 오류(§6) 시 job 재시도 지수 backoff 초기값 |
| `FDC_COORDINATOR_ERROR_BACKOFF_MAX_SECONDS` | `30` | 위 backoff 상한(hot-loop 방지) |

startup validation(구현 PR 대상): `FDC_PROVIDER_TARGET_RPM < GEMINI_PROVIDER_
DECLARED_RPM_LIMIT`, 모든 수치형 값 `> 0`. 배선 경로: `.env.example` 주석 추가 →
`settings.py` 필드 → dispatcher가 `settings`에서 읽어 명시적으로 전달(현재처럼
함수 기본값에 암묵 의존하지 않음) → `docker-compose.yml`의 `ops-scheduler`
`environment:` 블록. **이번 문서화 턴에서 `.env`/`.env.example`/compose/migration
실제 수정 없음** — 구현 PR 대상.

## 14. 관측(감사) SQL 요구사항(보정 4 — 60초 경계 규칙을 §6 판단 SQL과 일치시킴)

**정정 사유**: 이전 초안의 `RANGE BETWEEN INTERVAL '60 seconds' PRECEDING AND
CURRENT ROW` window frame은 **정확히 60초 이전 행을 포함**하는데(Postgres RANGE
frame은 경곗값 포함), §6의 coordinator 판단 SQL은 `reserved_at > now() -
interval '60 seconds'`로 **경곗값을 제외**한다 — 이 불일치가 있으면 coordinator가
"13개 미만이라 승인"한 상황을 감사 SQL이 "실제로는 14개였다"고 다르게 셀 수
있었다. 아래는 self-join으로 **동일한 `>` 반열림 규칙**을 적용한 정정판이다.

```sql
-- 임의 sliding 60초 구간 reservation 수 최댓값(13 초과 여부 검증)
-- ── §6 판단 SQL과 동일한 반열림 구간 (t-60초, t] 규칙을 self-join으로 재현
SELECT max(window_count) FROM (
  SELECT anchor.reserved_at,
         count(candidate.attempt_id) AS window_count
  FROM fdc_provider_attempts anchor
  JOIN fdc_provider_attempts candidate
    ON candidate.quota_scope = anchor.quota_scope
   AND candidate.reserved_at > anchor.reserved_at - interval '60 seconds'
   AND candidate.reserved_at <= anchor.reserved_at
   AND candidate.outcome IN ('reservation_granted','http_started','http_succeeded',
                              'http_failed_retryable','http_failed_final',
                              'reserved_but_http_not_started')
  WHERE anchor.quota_scope = 'gemini:shared-operational'
  GROUP BY anchor.reserved_at
) w;
-- 정확히 60초 이전(anchor.reserved_at - 60초)의 reservation은 `>` 조건에 의해
-- 이번 window에서 제외된다 — §6 coordinator 판단과 동일한 규칙.

-- 실제 HTTP 시작 수 최댓값도 같은 self-join 패턴을 http_started_at 기준으로 적용
-- reserved_at은 있으나 http_started_at 없는 attempt(reserved_but_http_not_started)
-- caller_id별 quota 소비량
-- job별 permit_consumed_count와 attempt 행 수 정합성(HAVING 불일치)
-- 재기동 뒤 미완료 job 및 마지막 상태(status NOT IN 종결상태)
-- provider_queue_timeout reason code가 신규 경로에서 생성되지 않았는지(기대값 0)

-- (보정) job별 queue_poll_count = reservation_denied_count + dispatch_attempt_no 정합성 검증
SELECT job_id, queue_poll_count, reservation_denied_count, dispatch_attempt_no
FROM fdc_queue_jobs
WHERE queue_poll_count <> reservation_denied_count + dispatch_attempt_no;
-- 기대 결과: 0 rows. 1행이라도 나오면 coordinator 호출 지점이 두 카운터 중
--하나를 누락하고 있다는 뜻이다.
```

fake clock 기반 테스트(§15)도 이 self-join 규칙과 동일한 경계(정확히 60초 전
= 제외)로 어서션을 작성해야 한다 — coordinator, 감사 SQL, 테스트 셋 모두 같은
반열림 규칙을 쓰는 것이 13 RPM strict 계약의 일부다.

(전체 SQL 원문은 이전 설계 검토 세션 로그에 보존, 구현 PR에서 뷰/함수로 정리 예정.)

## 15. 테스트 · shadow · 단계적 전환 계획

**필수 테스트 시나리오**(구현 PR 대상, fake clock/fake PG repository/fake provider,
실제 sleep·외부 API 없음): (1) 동시 2 caller가 합산 13건까지만 승인, (2) reservation
0건 상태에서 phantom insert 미발생, (3) DB 장애 시 fail-closed, (4) worker slot
확보 전 reservation 미소비, (5) reservation 후 HTTP 전 실패 시 quota 60초 소비 +
`reserved_but_http_not_started` 기록 + `pre_http_execution_failure_count` 증가
(보정 3), (6) `generate_structured_once(grant)`가 전달받은 grant만 소비하고
coordinator에게 새 reservation을 절대 요청하지 않음(보정 1의 핵심 검증), (7) 임의
60초 구간 reservation/HTTP 시작 수 ≤ 13이며 **정확히 60초 전 reservation은 제외**
(보정 4의 경계 규칙, §14 self-join과 동일 어서션), (8) 운영 시간대 `caller_id=
"manual:*"` reservation이 fail-closed로 거부됨 + 비운영 시간대는 승인되나 FDC
FIFO/worker slot을 점유하지 않음(보정 2, A안), (9) coordinator 없는 raw 호출
차단, (10) fake provider는 coordinator 없이도 정상 동작, (11) job 상태와 attempt
기록 수치 일관(`provider_retry_count`/`pre_http_execution_failure_count`/
`queue_reenqueue_count` 각각 별도 검증), (12) 40개/120개 극단 조건의 dispatch
스케줄이 §10 계산과 일치, (13) reservation 거부 시 `dispatch_attempt_no`는
증가하지 않고 `reservation_denied_count`만 증가함 + 승인 시 반대(§9 보정 규칙
직접 검증), (14) 임의 job에 대해 `queue_poll_count = reservation_denied_count
+ dispatch_attempt_no` 항등식이 항상 성립, (15) DB connection 실패를 fake
repository로 재현했을 때 Gemini HTTP 시도가 0회임을 확인, (16) lock timeout/
transaction 오류 시 local worker slot이 즉시 반환됨, (17) coordinator 오류가
`reservation_denied_count`/`dispatch_attempt_no`/`queue_poll_count` 어느 것도
증가시키지 않아 (14)의 항등식이 오류 경로에서도 깨지지 않음(A안 핵심 검증),
(18) 지수 backoff이 고정 간격이 아니라 매 실패마다 증가하며 상한
(`FDC_COORDINATOR_ERROR_BACKOFF_MAX_SECONDS`)에서 멈추고, fake DB가
"복구"(성공 응답으로 전환)되면 다음 폴링에서 즉시 정상 재개됨, (19)
coordinator 오류가 반복되는 동안에도 `CANCELLED`(시장 종료/운영자/프로세스
종료 3사유 외)가 자동으로 발동하지 않음(job이 순번·오류 어느 이유로도
자동 제거되지 않는다는 계약의 직접 검증).

**단계적 도입**: ① lifecycle 관측(quota_state/queue_jobs/attempts 스키마 + shadow
기록, 실제 dispatch 동작은 미변경) → ② held_position lane 한정 실전 전환 → ③ 전체
lane(core 포함) 전환. 각 단계에서 §14 SQL로 실측(FDC 대상 수/permit grant 수/queue
대기 분포/timeout/cancellation/HTTP attempt·429/cycle wall-clock/stale 차단/최종
decision·order 영향/lane 공정성)을 수행한다.

## 16. 위험 · 롤백 · 확정된 구현 계약 vs 구현 후 실측 필요

### 확정된 구현 계약(이번 문서로 확정, 구현 PR은 이를 그대로 따른다)
- Cycle-scoped(순차 유지), dispatcher 완전 소유 permit(FDC one-shot은 발급받은
  `ReservationGrant`를 소비만 하고 재요청하지 않음 — 보정 1), PostgreSQL
  anchor-row atomic reservation(§6), FDC one-shot 인터페이스 신설(공용
  `generate_structured()` 불변), 즉시 저장(배치 종료 대기 안 함), `CANCELLED`
  사유 3종 한정, `fdc_queue_jobs`+`fdc_provider_attempts`(`job_id` nullable)+
  `fdc_quota_state` 3-테이블 스키마, 운영 시간 수동 호출 기술적 fail-closed
  차단 + 비운영 시간 수동 호출은 coordinator만 공유하고 FDC FIFO/worker slot은
  점유하지 않음(A안 — 보정 2), `provider_retry_count`/`pre_http_execution_
  failure_count`/`queue_reenqueue_count` 3분리 accounting(보정 3), coordinator
  판단·감사 SQL·테스트 전부 동일한 `(t-60초, t]` 반열림 경계 규칙 사용(보정 4),
  `dispatch_attempt_no`는 reservation **성공 시에만** 증가하고 `reservation_
  denied_count`는 `fdc_queue_jobs`에 저장해 `queue_poll_count = reservation_
  denied_count + dispatch_attempt_no`를 항상 만족(accounting 정합성 보정),
  coordinator 오류(DB unavailable/lock timeout/transaction 오류)는 위 세
  카운터 어디에도 포함하지 않고 프로세스 로그/in-memory counter로만 관측하며
  (A안), 그 오류로 job이 `CANCELLED`/`FDC_FAILED_FINAL`로 자동 전이되지
  않고 지수 backoff 후 계속 재시도(4차 보정).

### 구현 후 실측 필요(이번 문서로 확정하지 않음, 값·성능은 구현 후 검증)
- `FDC_WORKER_CONCURRENCY=5`가 13 RPM을 실제로 소진하기에 충분한지.
- PG 행 잠금이 사이클 실제 트래픽에서 유발하는 지연 정도(이론상 미미하나 실측 없음).
- `MAX_RETRIES`→`max_http_attempts` 리네이밍의 전체 참조처 영향 범위.
- 두 분석 스크립트를 `LiveGeminiProviderClient`로 전환했을 때 기존 사용 방식(비교
  검증 등)에 미치는 영향.
- Gemini의 실제 quota 적용 단위(API 키/프로젝트/모델) — 외부 provider 정책, 이
  문서로 확정 불가.
- §11에서 "운영 시간 판정은 기존 market-hours 관련 코드/설정을 재사용한다"고
  명시했으나, 정확히 어느 기존 함수/설정을 재사용할지는 구현 PR에서 확인이
  필요하다(이번 문서화 턴에서 코드 근거로 특정하지 않음, 보정 2 관련).
- coordinator 오류 시 dispatcher 프로세스 로그/in-memory counter만으로
  운영자가 "DB 장애로 몇 개 job이 얼마나 오래 대기했는지"를 사후 파악하기에
  충분한지는 구현 후 실제 장애 상황(또는 fault-injection 테스트)으로 검증이
  필요하다 — 이번 설계는 "저장 불가능한 상황에서는 로그로만 관측한다"는
  원칙만 확정했고, 그 로그의 구체적 포맷/보존 기간/알림 연동은 구현 PR 대상.
- `FDC_COORDINATOR_ERROR_BACKOFF_INITIAL_SECONDS=1`/`_MAX_SECONDS=30`이
  적정한 값인지는 실제 DB 장애 복구 시간 분포에 대한 실측 없이 제안한
  보수적 시작값이다.

### 롤백
전부 신규 테이블·신규 인터페이스 추가이며 기존 `fdc_rate_limiter.py`/`run_agent_
subprocess.py`의 기존 경로를 즉시 제거하지 않고 병행 가능(①단계 shadow 방식) —
문제 발생 시 신규 dispatcher 호출부만 되돌리면 기존 경로로 즉시 복귀 가능하다(구현
PR에서 feature flag로 전환 여부를 감쌀 것을 권고).
