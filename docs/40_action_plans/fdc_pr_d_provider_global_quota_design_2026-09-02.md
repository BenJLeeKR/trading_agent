# PR D 사전 설계: Gemini provider 전체 13 RPM quota 통합

- 작성일: 2026-09-02
- 상태: 설계 검토용 초안 (코드 미반영, BUY actual-dispatch 미연결)
- 선행 문서: `docs/40_action_plans/fdc_actual_dispatch_buy_core_lane_extension_design_2026-09-01.md` (§4, §8, §9 — PR D 스코프/AC/대안이 이미 정의돼 있음. 이 문서는 그 정의를 실제 코드 지점까지 추적해 구현 가능한 Task Spec으로 구체화한다.)
- 조사 방법: 전체 read-only (코드/문서/설정 수정 없음, DB write 없음, 외부 호출 없음)

---

## 0. 배경 요약

FDC(Gemini) 호출 경로가 현재 두 개로 나뉘어 있고 서로의 HTTP 소비를 회계하지 않는다.

| | legacy `mode="full"` | held_position actual-dispatch |
|---|---|---|
| Limiter | `fdc_rate_limiter.py` (파일 기반, `flock`) | `FdcQuotaCoordinator` (Postgres, anchor row) |
| Target RPM | 10 | 13 |
| DB 기록 | 없음 | `fdc_provider_attempts`, `fdc_queue_jobs` |
| 재시작 생존 | OS 임시 디렉터리 파일 (컨테이너 재생성 시 소실 가능) | Postgres (durable) |
| 실행 위치 | 종목별 일반 subprocess | `complete_fdc_actual_dispatch()`가 별도로 스폰하는 전용 subprocess |
| 우회 차단 | — | `LiveGeminiProviderClient.generate_structured()`가 `RuntimeError`를 던지도록 오버라이드돼 legacy 경로로의 우회 자체를 코드로 차단(`provider_client.py:552-579`) |

두 경로가 동시에 살아있는 한, provider 전체 실제 HTTP 시작 건수가 물리적으로 13 RPM을 넘을 수 있다. BUY/core actual-dispatch(`FDC_ACTUAL_DISPATCH_BUY_ENABLED`)를 실행 경로에 연결하기 전에 이 통합이 선행돼야 한다.

---

## 1. 현재 호출 경로 지도

### 1.1 legacy `mode="full"` — permit → HTTP → fallback

```
OpenAICompatibleClient.generate_structured()          provider_client.py:416  (retry loop, MAX_RETRIES)
  └─ _FdcPermitAccumulator.acquire()                   run_agent_subprocess.py:376-389
       └─ wait_for_fdc_slot()                          fdc_rate_limiter.py:598-739
            └─ _poll_ticket()                          fdc_rate_limiter.py:490-558  (flock 임계구역, 실제 permit 판정)
  └─ (grant) _single_http_attempt()                    provider_client.py:289
       └─ client.post()                                실제 HTTP
  └─ (실패) FinalDecisionComposerAgent.run() except     final_decision_composer.py:291-327
       └─ _classify_provider_exception()                final_decision_composer.py:71-101
            └─ decision_type="HOLD", reason_codes=(marker,)  (에러를 성공으로 위장하지 않음)
```

- attempt마다 새 permit 획득(하나의 permit이 재시도까지 커버하지 않음). 단 최초 attempt만 FIFO 재등록 허용(`allow_requeue=True`), 이후 429/5xx 재시도는 `allow_requeue=False`.
- **DB 기록 없음** — 전부 `tempfile.gettempdir()/agent_trading_fdc_rate_limiter_state.json` 파일 상태로만 관리.

### 1.2 held_position actual-dispatch — reservation → HTTP → 결과 기록

```
complete_fdc_actual_dispatch()                         decision_agent_runner.py:387
  └─ async with worker_semaphore:                       decision_agent_runner.py:514
  └─ coordinator.try_reserve()                           decision_agent_runner.py:515
       └─ FdcQuotaCoordinator.try_reserve()               services/fdc_quota_coordinator.py:114-160
            └─ PostgresFdcQuotaRepository.try_reserve()    repositories/postgres/fdc_quota.py:76-196
                 (anchor row FOR UPDATE + window count SQL)
  └─ (grant) _spawn_agent_subprocess_impl(mode="fdc_only")  decision_agent_runner.py:553  (별도 신규 subprocess)
       └─ _run_fdc_only_mode()                             run_agent_subprocess.py:1246-
            └─ PreGrantedFdcProviderClient                  fdc_manual_provider_gate.py:538-602
                 └─ execute_fdc_one_shot_attempt()           fdc_manual_provider_gate.py:~280
                      └─ record_attempt_outcome("http_started")  fdc_manual_provider_gate.py:319-323
                      └─ client.post()                       실제 HTTP
                      └─ record_attempt_outcome("http_succeeded"/"http_failed_*")  fdc_manual_provider_gate.py:345-377
  └─ (subprocess 비정상 종료) get_attempt_http_lifecycle()로 tri-state 판정 후 fail-closed  decision_agent_runner.py:560-599
```

- window count SQL(`repositories/postgres/fdc_quota.py:113-121`)은 `quota_scope`/`mode='real'`/`outcome`/`reserved_at`만 필터링 — **`source_type`은 관여하지 않는다.** held_position과 BUY(현재는 shadow만)는 같은 `quota_scope="gemini:shared-operational"`를 공유한다.
- durable-resume: `list_resumable_real_jobs()`(`fdc_quota.py:432-486`, `status='QUEUED'`를 `enqueue_sequence ASC`로 재개, payload 누락 시 즉시 `FDC_FAILED_FINAL`로 FIFO head 차단 방지) + `cancel_stale_real_jobs()`(`fdc_quota.py:488-547`, `RESERVATION_GRANTED`인데 HTTP 시작 여부 불명 job을 상태별로 `CANCELLED`/`FDC_FAILED_FINAL`) — 둘 다 `run_decision_loop.py:3811-3906`에서 `settings.fdc_actual_dispatch_enabled`일 때만 루프 진입 시 1회 실행.

### 1.3 공유/비공유 상태

| 상태 | legacy | actual-dispatch(held_position/BUY-shadow) |
|---|---|---|
| 파일(`fdc_rate_limiter` state json) | 사용 | 미사용 |
| `fdc_quota_state`/`fdc_queue_jobs`/`fdc_provider_attempts` (Postgres) | 미기록 | 사용 |
| `quota_scope="gemini:shared-operational"` | 무관 | held_position ↔ BUY(shadow) 간 공유 |

두 경로는 서로의 존재를 코드 수준에서 전혀 모른다 — 이것이 통합 설계의 출발점이다.

---

## 2. 확정 사실 / 해석 / NOT VERIFIED

### 확정 사실 (코드로 직접 확인)
- legacy와 actual-dispatch는 서로 다른 회계 체계를 쓰며 어느 쪽도 상대의 실제 HTTP 소비를 관측하지 못한다.
- `LiveGeminiProviderClient.generate_structured()`는 호출 시 `RuntimeError`를 던지도록 오버라이드돼 있어(`provider_client.py:552-579`), actual-dispatch 경로가 legacy 10 RPM limiter를 거치는 것을 코드로 원천 차단한다.
- `FdcQuotaCoordinator`의 window 판정은 `source_type` 무관, `quota_scope` 전역 공유다(PR C 조사 결과와 일치, 재확인 완료).
- `FDC_ACTUAL_DISPATCH_BUY_ENABLED`는 현재 어떤 런타임 조건 분기에서도 읽히지 않는다(설정 파싱 결과로만 존재) — PR B/#364 주장이 여전히 사실.
- legacy 경로는 실패를 삼켜 성공으로 위장하지 않고 `reason_codes`에 provider fallback 마커를 남긴 채 `HOLD`를 반환한다.
- `fdc_provider_attempts` 테이블에는 `source_type` 컬럼이 없다(그 값은 `fdc_queue_jobs`에만 존재).

### 해석 (코드에서 직접 보이진 않지만 구조상 합리적으로 추론)
- legacy limiter가 파일 기반으로 설계된 이유는 "서로 다른 OS subprocess 간에도 공유돼야 한다"는 요구 때문으로 보인다(모듈 docstring 근거) — 이는 PR D에서 legacy를 Postgres로 옮기는 안이 자연스러운 이유가 된다.
- 두 경로가 물리적으로 별도 subprocess에서 실행되는 구조 자체는 유지하되, 회계만 통합하는 것이 프로세스 아키텍처 변경 없이 가능한 최소 변경으로 보인다.

### NOT VERIFIED
- 컨테이너 재생성 시 legacy 상태 파일이 실제로 소실되는지(OS 임시 디렉터리 마운트 방식에 의존, 이번 조사에서 컨테이너 마운트 설정까지는 확인하지 않음).
- 운영 환경에서 legacy `mode="full"` 호출 빈도(실제 트래픽 패턴) — 이는 PR D의 안전 여유(margin) 설계에 영향을 주지만 로그 조회 없이는 확정할 수 없음.

---

## 3. 설계 대안 비교 (최소 3개)

기존 설계 문서(§4, line 361-379)가 이미 3개 대안을 명시하고 "정적 분할"(예: coordinator 8 + legacy 5)을 기각했다는 사실을 그대로 계승한다 — 13 RPM에 여유가 없어 정적 분할은 처음부터 배제.

### 대안 A — legacy를 coordinator로 완전 흡수 (`try_reserve()` 직접 호출)

legacy `mode="full"` 호출도 `_FdcPermitAccumulator.acquire()` 대신 `FdcQuotaCoordinator.try_reserve()`를 호출하도록 교체.

- **정확성**: 최고 — 단일 회계 경로, 이중 관리 리스크 없음.
- **재시작 내구성**: 최고 — 처음부터 Postgres 기반.
- **429 재시도 회계**: `try_reserve()`가 attempt 단위 API가 아니라 job 단위이므로, legacy의 "attempt마다 새 permit" 의미론을 그대로 옮기려면 `record_attempt_outcome()` 스타일의 attempt-level API가 legacy 호출부에도 필요 — **coordinator API를 job-lease 전제에서 attempt-lease도 지원하도록 확장**해야 함.
- **held_position 영향**: 중간 — coordinator가 legacy 트래픽까지 흡수하면서 FIFO 큐 안에 두 lane의 job이 섞이므로, FIFO 공정성 계약(현재 held_position REDUCE/SELL 전용 가정)을 재검증해야 함.
- **구현 범위**: 큼 — legacy 호출부(`provider_client.py`, `run_agent_subprocess.py`) 전체 재작성, `fdc_only`가 아닌 `mode="full"` subprocess에도 coordinator 연결 필요.
- **rollback 난이도**: 높음 — 원복하려면 legacy 코드 경로 전체를 되살려야 함.

### 대안 B — legacy limiter를 Postgres-backed로 재작성해 같은 DB window 공유 (coordinator API는 그대로, 별도 "legacy-compatible" 얇은 어댑터만 추가)

`fdc_rate_limiter.py`의 파일 기반 `_poll_ticket()`을 Postgres 테이블(같은 `quota_scope`, `mode='real'`, 별도 `caller_id`)에 대한 단순 INSERT/SELECT로 교체하되, legacy 호출부의 API 시그니처(`wait_for_fdc_slot()`)는 유지.

- **정확성**: 높음 — 같은 window SQL을 재사용하므로 회계 일원화.
- **재시작 내구성**: 높음 — Postgres 기반으로 전환.
- **429 재시도 회계**: legacy의 "attempt마다 permit" 의미론을 그대로 유지하기 쉬움(어댑터가 `wait_for_fdc_slot()` 호출마다 attempt 행을 하나씩 남기면 됨) — coordinator의 job 단위 API를 억지로 재해석할 필요 없음.
- **held_position 영향**: 낮음 — held_position의 `try_reserve()`/`register_real_job()` 흐름은 전혀 건드리지 않고, legacy 쪽만 같은 window SQL을 공유하는 새 경량 경로를 추가.
- **구현 범위**: 중간 — `fdc_rate_limiter.py` 내부 구현 교체(공개 API 유지) + 신규 attempt-lease 함수(`try_reserve_attempt_lease()` 같은 경량 API)를 repository에 추가.
- **rollback 난이도**: 중간 — `fdc_rate_limiter.py` 내부만 되돌리면 되므로 A보다 국소적.

### 대안 C — legacy·actual 둘 다 감시하는 별도 global coordinator 신설 (제3의 심판)

`FdcQuotaCoordinator`와는 별개로, provider 전체 HTTP 시작만 감시하는 "global HTTP gate"를 신설하고 legacy/actual 양쪽이 HTTP 직전에 이 gate를 통과하도록 만듦. 기존 `FdcQuotaCoordinator`는 held_position/BUY용 FIFO·durable-resume 책임만 유지, global gate는 순수 rate-limit 책임만 담당(책임 분리).

- **정확성**: 높음 — 단일 gate가 물리적 HTTP 시작만 정확히 카운트.
- **재시작 내구성**: gate 자체를 Postgres에 두면 높음.
- **429 재시도 회계**: gate 통과 시점을 "HTTP 시작 직전"으로 고정하면 재시도마다 정확히 1회씩 반영 가능 — 설계상 가장 명확.
- **held_position 영향**: 가장 낮음 — 기존 `try_reserve()`/FIFO 로직은 전혀 변경하지 않고, `try_reserve()` grant 이후 실제 HTTP 직전에 gate를 한 번 더 통과시키는 방식이면 기존 계약 100% 보존.
- **구현 범위**: 중간~큼 — 신규 테이블/컴포넌트 하나 추가, 기존 `record_attempt_outcome()`의 `http_started` 시점과 gate 통과 시점을 정합시켜야 함(이중 관문이 서로 다른 판정을 내리면 안 됨).
- **rollback 난이도**: 낮음 — 신규 컴포넌트이므로 gate 호출부만 제거하면 기존 동작으로 즉시 복귀.

#### 대안 C 상세 — actual reservation과 global gate의 이중 관문 상태 전이 계약 (보정 1)

**전제 사실(코드로 확인, `repositories/postgres/fdc_quota.py`)**: `try_reserve()`가 grant를 내는 순간(`outcome='reservation_granted'` INSERT, `fdc_queue_jobs.status='RESERVATION_GRANTED'`, `permit_consumed_count += 1`, `fdc_quota.py:161-184`) **이미 actual coordinator 자신의 13 RPM window 슬롯을 소비한 것으로 집계된다** — `_QUOTA_CONSUMING_OUTCOMES`(`fdc_quota.py:35-42`)에 `reservation_granted`와 `reserved_but_http_not_started`가 모두 포함되기 때문이다. 즉 **물리적 HTTP가 실제로 시작됐는지와 무관하게, reservation 자체가 actual coordinator 슬롯을 소비한다.** 이것이 이중 관문 설계의 전제다.

**실행 순서**: `coordinator.try_reserve()` grant(부모 프로세스) → `fdc_only` subprocess 스폰 → subprocess 내부에서 `record_attempt_outcome("http_started")`를 호출하기 직전에 **global gate를 통과**(신설) → 통과 시에만 실제 `client.post()`.

**global gate가 대기/거부/timeout/프로세스 종료될 때의 전이 규칙**은 기존에 이미 구현돼 있는 "HTTP 시작 전 실패"(`AttemptHttpLifecycle.NOT_STARTED`) 처리 경로를 **그대로 재사용**한다 — 새 상태를 만들지 않는다:

| 상황 | `fdc_provider_attempts.outcome` | `http_started_at` | `fdc_queue_jobs.status` | `permit_consumed_count` | `queue_reenqueue_count` | `provider_retry_count` |
|---|---|---|---|---|---|---|
| gate 통과 대기 중(아직 결과 없음) | `reservation_granted`(변경 없음) | NULL | `RESERVATION_GRANTED`(변경 없음) | 이미 반영됨(변경 없음) | 변경 없음 | 변경 없음 |
| gate가 timeout/거부해 HTTP를 시작하지 못함 | `reserved_but_http_not_started`로 갱신(subprocess가 `record_attempt_outcome(outcome="reserved_but_http_not_started")` 호출, 기존 `decision_agent_runner.py:590-594`와 동일 패턴) | NULL 유지 | `apply_retry_failure(reason="pre_http_execution_failure", will_retry=...)`가 `will_retry=True`면 `QUEUED`로 되돌리고 `enqueue_sequence`를 새로 발급(FIFO tail 재등록, `fdc_quota.py:637-640`) | 재시도 시 **새 `try_reserve()`가 새 attempt_no로 재차 소비**(중복 아님 — 새로운 실행 기회이므로 정당) | `will_retry=True`일 때만 +1(`fdc_quota.py:636`) | 변경 없음(이 경로는 `reason="pre_http_execution_failure"`이지 `"provider_retryable_failure"`가 아니므로 이 counter는 증가하지 않음, `fdc_quota.py:631-632`) |
| gate 통과 후 물리적 HTTP 시작 | `http_started`로 갱신, 이후 성공/실패 최종 outcome | 실제 시각 기록 | 변경 없음(subprocess 종료 후 부모가 최종 처리) | 변경 없음 | 변경 없음 | HTTP 시작 후 429/5xx 재시도면 +1(`"provider_retryable_failure"` 경로) |
| gate 대기 중 subprocess 강제 종료(SIGKILL/timeout) | 부모가 `get_attempt_http_lifecycle()`로 조회 — `http_started_at`이 NULL이면 `NOT_STARTED`로 판정(기존 로직 그대로) | NULL(gate 대기 중이었으므로 애초에 안 채워짐) | 위 "gate 거부" 행과 동일하게 `apply_retry_failure` 경로로 합류 | 위와 동일 | 위와 동일 | 위와 동일 |

**gate 실패 시 새 actual reservation이 필요한가(질문 3의 확정)**: **그렇다.** 기존 `while True` 재시도 루프(`decision_agent_runner.py:498-501`, `provider_attempt_no` 증가)가 이미 "HTTP 시작 전 실패 → 새 attempt_no로 새 `try_reserve()`"를 정상 흐름으로 다루고 있으므로, gate 거부도 이 흐름에 합류시키는 것이 최소 변경이다. gate가 막았다고 해서 기존 reservation을 "부활"시켜 재사용하지 않는다 — 새 reservation을 받아 actual coordinator의 FIFO/window 판정을 다시 통과해야 한다(다른 job에게 새치기 기회를 주지 않기 위해 `enqueue_sequence`도 새로 발급되어 FIFO 뒤로 밀린다).

**global gate와 actual coordinator가 각각 13 RPM을 독립 판단해도 충돌하지 않는 이유**: 두 판정은 서로 다른 질문에 답한다. actual coordinator의 window(`fdc_quota.py:113-121`)는 "이 quota_scope 안에서 최근 60초간 몇 개의 **reservation**이 소비됐는가"(actual/BUY 레인 사이의 공정성·FIFO 판단)를 답하고, global gate는 "provider 전체(legacy 포함)에서 최근 60초간 몇 건의 **물리적 HTTP가 실제로 시작됐는가**"를 답한다. reservation은 HTTP 시작의 필요조건이지 충분조건이 아니므로(위 표의 "gate 대기/거부" 행), actual coordinator가 자신의 window 안에서 13개까지 reservation을 내주더라도 그중 일부가 gate에서 대기하며 물리적 HTTP 총량은 legacy 몫까지 합쳐 여전히 13을 넘지 않게 gate가 최종 관문 역할을 한다. 즉 **actual coordinator = "누가 다음 실행 기회를 가질 자격이 있는가"(entitlement), global gate = "지금 물리적으로 내보내도 되는가"(physical throttle)**로 책임이 완전히 분리되어 있어 두 판정이 서로의 결과를 뒤집거나 이중 집계할 여지가 없다.

**held_position SELL의 FIFO head 영구 차단 방지 규칙**: gate 대기가 아무리 길어져도, 위 표의 "gate가 timeout/거부" 행이 곧 기존 `apply_retry_failure(will_retry=...)` 예산 판정(`provider_attempt_no < max_provider_attempts`, `decision_agent_runner.py:612,669`)에 그대로 편입되므로, 기존 durable-resume/fail-closed 계약(예산 소진 시 `mark_job_terminal(status="FDC_FAILED_FINAL")`)이 변경 없이 그대로 적용된다. gate 대기가 FIFO head를 "새로운 방식으로" 영구 차단할 방법이 구조적으로 없다 — gate는 기존 lifecycle 상태 밖의 새로운 정지 상태를 만들지 않고, 기존 "HTTP 시작 전 실패" 카테고리 안으로만 합류하기 때문이다.

### 비교 요약표

| 기준 | A (완전 흡수) | B (legacy를 Postgres화) | C (별도 global gate) |
|---|---|---|---|
| 정확성 | 최고 | 높음 | 높음 |
| 재시작 내구성 | 최고 | 높음 | 높음 |
| 429 재시도 회계 정확성 | API 재설계 필요 | 자연스러움 | 가장 명확 |
| held_position 계약 보존 | 재검증 필요(중간 리스크) | 낮은 리스크 | 가장 낮은 리스크 |
| 구현 범위 | 큼 | 중간 | 중간~큼 |
| rollback 난이도 | 높음 | 중간 | 낮음 |

---

## 4. 권고안

**대안 C(별도 global HTTP-start gate 신설)를 권고한다.**

근거:
1. 기존 `FdcQuotaCoordinator`의 FIFO/durable-resume/fail-closed 계약(held_position REDUCE/SELL이 이미 운영 중)을 **전혀 건드리지 않고** provider 전체 13 RPM 통합을 달성할 수 있다 — 질문 7의 "약화되지 않는가"에 가장 안전하게 답할 수 있는 대안.
2. 429 재시도 회계를 "HTTP 시작 직전 gate 통과"로 정의하면, legacy의 "attempt마다 permit" 의미론과 actual-dispatch의 `record_attempt_outcome("http_started")` 의미론이 **동일한 물리적 시점**(HTTP 시작 직전)에서 자연스럽게 만난다 — 대안 A/B처럼 job-lease와 attempt-lease 개념을 섞어 재해석할 필요가 없다.
3. rollback이 가장 쉽다 — 신규 컴포넌트이므로 문제가 생기면 gate 호출부(2곳: legacy `_single_http_attempt()` 직전, actual `PreGrantedFdcProviderClient`의 `client.post()` 직전)만 제거하면 기존 동작(각자 회계)으로 즉시 복귀 가능.
4. 대안 B도 유력하지만, `fdc_rate_limiter.py`의 내부 구현을 통째로 교체하는 작업은 legacy 경로의 회귀 리스크(파일 기반 flock 동시성 가정이 암묵적으로 의존하는 다른 부분이 있을 수 있음)가 C보다 크다고 판단.

단, gate 신설은 **기존 `fdc_provider_attempts`를 그대로 재사용**(신규 테이블 대신 `caller_id`/`mode='real'` 조합으로 legacy 시도도 같은 테이블에 남기는 방식)하는 쪽을 우선 검토할 것을 권고한다 — 신규 스키마 추가는 migration 리스크를 늘리므로, PR D 구현 단계에서 "기존 테이블 재사용 가능 여부"를 최우선으로 재확인해야 한다(§5 참고).

### 4.1 FDC 전용 gate 주입 경계 (보정 2)

`provider_client.py`의 공용 메서드(`OpenAICompatibleClient._single_http_attempt()`/`generate_structured()`)는 legacy FDC뿐 아니라 **EI(Event Interpretation)/AR(AI Risk)/AC(AI Compliance) 및 일반 호출도 그대로 쓰는 공유 base class**다(`bootstrap.py:466`, `run_agent_subprocess.py:1407`, `ar_fdc_provider_validation.py:426`, `ar_fdc_output_measurement.py:1108`가 모두 이 클래스를 직접 인스턴스화한다). 이 공용 메서드 안에 gate 호출을 무조건 넣으면 FDC가 아닌 EI/AR/AC 호출까지 global gate 제한을 받게 되어 §0의 목표(**Gemini FDC 호출만** 통합)를 벗어난다. **이는 금지한다.**

**확정한 주입 경계 — 이미 존재하는 FDC 전용 어댑터 계층에만 gate를 추가한다:**

1. **legacy `mode="full"` 경로**: `_FdcPermitAccumulator.acquire()`(`scripts/run_agent_subprocess.py:376-389`)에 global gate 호출을 추가한다. 이 클래스는 이미 "`provider_client.py`는 이 클래스도 `fdc_rate_limiter.py`도 전혀 알지 못한다"는 것을 설계 전제로 삼는 얕은 어댑터이며(`run_agent_subprocess.py:340-348` docstring), `PermitCallback` 계약을 만족하는 `acquire()` 메서드 하나만 노출한다. **순서 확정(더 이상 미정이 아님): `wait_for_fdc_slot()`으로 legacy limiter permit을 먼저 획득한 뒤, 같은 `acquire()` 안에서 global gate를 추가로 통과시킨다(§4.2 참고).** 공용 `generate_structured()`/`_single_http_attempt()`는 여전히 "permit callback 하나를 호출했다"는 사실만 알 뿐 그 안에 legacy limiter가 있는지 global gate가 있는지 전혀 추론하지 않는다.
2. **actual-dispatch(`mode="fdc_only"`) 경로**: `PreGrantedFdcProviderClient`(`scripts/fdc_manual_provider_gate.py:538-602`)의 `execute_fdc_one_shot_attempt()` 안, `record_attempt_outcome(outcome="http_started")` 직전(§4의 대안 C 상세 표와 동일 지점)에 global gate 통과를 추가한다. 이 클래스 역시 이미 FDC 전용이며 `LiveGeminiProviderClient.generate_structured()`가 `RuntimeError`를 던지도록 막아둔 것과 대칭적으로, 공용 client 클래스를 우회해 FDC 전용 gate 로직만 여기 둔다.
3. 공용 `OpenAICompatibleClient`/`LiveGeminiProviderClient` 클래스 자체는 이번 PR에서 **한 줄도 수정하지 않는다** — "공용 HTTP 메서드는 FDC 전용 여부를 추론하지 않는다"는 계약을 코드 구조로 강제한다.

### 4.2 legacy limiter → global gate 순서 확정과 실패 상태 전이 계약 (2026-09-03 보정)

**확정한 순서(둘 중 하나, 구현 시 재검토 아님)**:

1. `wait_for_fdc_slot()`으로 legacy limiter permit을 먼저 획득한다(기존 FIFO/재대기 의미론 그대로 — 최초 요청만 `allow_requeue=True`).
2. legacy limiter가 grant한 **뒤**, 같은 `_FdcPermitAccumulator.acquire()` 안에서 FDC 전용 adapter를 통해 global HTTP-start gate를 통과시킨다.
3. gate까지 통과한 뒤에만 `acquire()`가 `PermitResult(granted=True, ...)`를 반환하고, 그제서야 `provider_client.py`의 재시도 루프가 실제 `client.post()`(§4.1이 금지하는 공용 클래스 자체는 무수정)를 호출한다.

legacy limiter를 먼저 두는 이유: legacy 고유의 FIFO 재대기(`allow_requeue`)·큐 포지션 관측성은 legacy limiter 내부 상태에만 의존하므로, 이를 gate보다 먼저 통과시켜야 기존 legacy 관측 필드(`queue_position_at_first_wait`, `requeue_count` 등)의 의미가 gate 개입으로 왜곡되지 않는다. gate는 legacy 고유 로직을 전혀 모른 채 "이미 legacy 심사를 통과한 요청" 위에만 얹히는 마지막 관문이다.

**legacy limiter permit 획득 후 global gate가 timeout/거부할 때**:

- **실제 HTTP는 0건**이다 — gate 통과 실패 시 `acquire()`는 `client.post()`를 호출하는 지점(`provider_client.py:426` 이후)에 도달하지 못하도록 `PermitResult(granted=False, denial_reason=...)`를 반환한다. 이는 **기존 `PermitDeniedError` 메커니즘을 그대로 재사용**한다(`provider_client.py:74`, `:426` — `acquire_permit()`이 `granted=False`를 반환하면 즉시 `PermitDeniedError`를 던지고 HTTP를 시작하지 않는 것은 이미 구현돼 있는 동작이다).
- **fallback reason 처리**: 기존 `provider_queue_timeout`(legacy limiter 자신의 큐 timeout)과 **혼동하지 않도록, global gate 전용 새 `denial_reason` 값**(예: `"global_gate_timeout"`/`"global_gate_denied"`)을 추가하고, `_classify_provider_exception()`(`final_decision_composer.py:71-101`)의 매핑 딕셔너리에 이에 대응하는 새 마커(예: `"provider_global_gate_unavailable"`)를 추가한다 — `provider_queue_timeout`은 "legacy 자신의 FIFO 큐가 찼다"는 의미이고 새 마커는 "legacy 심사는 통과했으나 provider 전체 합산 관문에서 막혔다"는 의미로 원인을 구분해 관측한다. 어느 쪽이든 `decision_type="HOLD"` fallback 정책 자체는 동일하게 유지된다(에러를 성공으로 위장하지 않음).
- **global gate 기록은 "HTTP 시작"과 구분되는 보수적 소비 규칙을 따른다**: gate가 **grant를 내주는 시점**(HTTP 시작 전, 물리적 전송 여부와 무관)에 이미 자신의 window 슬롯을 소비한 것으로 집계한다 — actual-dispatch의 `try_reserve()`가 `reservation_granted` 시점에 이미 슬롯을 소비하는 것과 **동일한 보수적 원칙**(§4 대안 C 상세)이다. 즉 gate 통과 직후 HTTP 시작 전에 legacy 쪽에서 실패(process kill 등)해도, 그 슬롯은 환불되지 않고 그대로 소비된 채로 남는다.
- **과대 집계 여부와 처리 방식(확정)**: gate grant 후 HTTP 시작 전 실패는 provider 전체 "실제 물리적 HTTP 시작 수"를 **과대 집계하지 않는다** — gate의 window는 "실제 HTTP 시작 수"가 아니라 "gate가 내준 grant 수"를 세는 것으로 **의도적으로 재정의**되며, grant는 HTTP 시작의 상한(ceiling)이지 하한이 아니다. 이 설계는 정확히 13건의 물리적 HTTP만 보장하는 대신, 아주 드물게 "grant는 받았지만 HTTP를 못 띄운" 슬롯 낭비를 허용해 **13 RPM을 절대 넘지 않는 안전한 방향으로만 오차가 생기게** 만든다(과소 활용은 허용, 과다 사용은 구조적으로 불가능). legacy는 job/큐 개념이 없어 재시도가 필요하면 상위 호출자가 `generate_structured()`를 처음부터 다시 호출하며, 그 새 시도는 legacy limiter와 gate를 처음부터 다시 통과한다(기존 reservation/grant 재사용 없음 — actual-dispatch의 "새 attempt_no로 재시도"와 동일한 원칙).

**global gate가 provider 전체 실제 HTTP 시작을 13 RPM 이하로 강제하기 위한 세부 실패 규칙**:

| 상황 | 처리 |
|---|---|
| gate grant 후 `client.post()` 사이에서 예외 발생(HTTP 시작 전) | gate 슬롯은 소비된 채 유지(환불 없음, 위 보수적 규칙). legacy는 `PermitDeniedError`가 아닌 일반 예외 경로로 흘러 기존 `_classify_provider_exception()`의 다른 분류(예: `provider_error`)로 fallback HOLD 처리. |
| process kill(legacy 호출 프로세스 자체가 죽음) | legacy에는 durable job 개념이 없으므로 별도 정리(cleanup) 대상이 없다 — 다음 호출이 다시 처음부터 gate를 통과해야 한다. gate 쪽 slot은 자연히 60초 window가 지나면 자동으로 만료(sliding window)되므로 별도 복구 로직이 필요 없다. |
| 429/5xx 재시도 | `provider_client.py`의 `MAX_RETRIES` 루프가 매 attempt마다 `acquire_permit()`(=`_FdcPermitAccumulator.acquire()`)을 다시 호출하므로, **legacy limiter와 global gate 모두 attempt마다 정확히 1회씩** 다시 통과해야 한다 — 이중 계산도 누락도 없다(호출 지점이 하나이므로 구조적으로 보장됨). |
| global gate 자체의 DB 오류(예: lock timeout, connection error) | **fail-closed** — gate는 오류 시 grant하지 않고 거부로 취급한다(`denial_reason="global_gate_error"` → `_classify_provider_exception()`에 새 마커 추가, 예: `"provider_global_gate_unavailable"`). 기존 `FdcQuotaCoordinator`의 `_classify_error()`(`fdc_quota.py:45-53`)가 이미 이 방향(오류=거부)으로 설계돼 있어 동일한 철학을 그대로 계승한다. |

**책임 분리(재확인)**: legacy limiter는 legacy FDC 고유의 대기/재시도/FIFO 재대기 의미론을 그대로 보존하는 것만 책임지고, global gate는 legacy+actual을 합산한 provider 전체 물리적 HTTP 시작 상한만 책임진다. 어느 한쪽이 거부해도 다른 쪽이 그 실패를 성공으로 바꾸지 않는다 — legacy limiter가 grant해도 gate가 거부하면 여전히 HOLD fallback이고, gate가 grant해도(legacy는 애초에 gate 이전에 이미 grant했으므로 이 순서에서는 항상 legacy가 먼저 통과된 상태) 이후 실제 HTTP가 429/5xx로 실패하면 여전히 기존 legacy 재시도/소진 규칙이 그대로 적용된다.

---

## 5. PR D 구현 Task Spec

### 5.1 목표
provider(Gemini) 전체로 나가는 실제 HTTP 호출(legacy `mode="full"` + held_position/BUY actual-dispatch, 429/5xx 재시도 포함)이 하나의 원자적 60초 sliding window에서 13 RPM 이하로 강제되도록 만든다. BUY actual-dispatch는 이번 PR에서 연결하지 않는다.

### 5.2 허용 변경 파일 (예상, 구현 착수 시 재확인)
- `src/agent_trading/services/ai_agents/fdc_rate_limiter.py` (legacy 파일 기반 flock 로직 자체 — 대안 확정 후 필요 시)
- `scripts/run_agent_subprocess.py` (`_FdcPermitAccumulator.acquire()`에 global gate 통과 호출 추가 — §4.1의 legacy 주입 경계)
- `scripts/fdc_manual_provider_gate.py` (`execute_fdc_one_shot_attempt()`의 `record_attempt_outcome(outcome="http_started")` 직전에 global gate 통과 호출 추가 — §4.1의 actual 주입 경계)
- `src/agent_trading/repositories/postgres/fdc_quota.py` (gate용 window 판정 함수 추가 — 신규 테이블이 필요하면 여기; `apply_retry_failure()`/`get_attempt_http_lifecycle()` 등 기존 함수는 재사용만 하고 시그니처를 바꾸지 않는다)
- `src/agent_trading/services/fdc_quota_coordinator.py` 또는 신규 모듈(예: `fdc_provider_global_gate.py`) — gate 컴포넌트 본체
- migration 파일 (신규 테이블이 필요한 경우만 — §5.7 참고)
- `src/agent_trading/config/settings.py` + `.env.example` + `docker-compose.yml` + `scripts/harness/contracts/runtime_env_wiring.json` (gate on/off shadow 플래그, 예: `FDC_PROVIDER_GLOBAL_QUOTA_GATE_ENABLED`)
- 관련 테스트 파일 전부

### 5.3 금지 변경
- `FDC_ACTUAL_DISPATCH_BUY_ENABLED`를 runtime 조건 분기에서 읽는 코드 추가 금지 — 이번 PR은 BUY actual-dispatch를 연결하지 않는다.
- **`src/agent_trading/services/ai_agents/provider_client.py`의 `OpenAICompatibleClient`/`LiveGeminiProviderClient` 공용 클래스 수정 금지**(§4.1 보정 2) — `_single_http_attempt()`/`generate_structured()`/`generate_structured_once()`에 gate 호출을 직접 삽입하지 않는다. EI/AR/AC가 같은 클래스를 공유하므로, 이 파일을 건드리면 FDC 외 호출까지 제한될 위험이 있다. gate는 반드시 `_FdcPermitAccumulator`(legacy)와 `PreGrantedFdcProviderClient`/`execute_fdc_one_shot_attempt()`(actual) 두 FDC 전용 어댑터 안에서만 호출한다.
- `FdcQuotaCoordinator.try_reserve()`의 FIFO/window 판정 SQL 자체를 변경하지 않는다(§4 권고안이 기존 계약을 건드리지 않는 이유이기도 함) — 단, gate가 별도 함수로 추가되는 것은 허용.
- held_position REDUCE/SELL의 durable-resume/fail-closed 로직 변경 금지. gate 거부/timeout은 반드시 기존 `apply_retry_failure(reason="pre_http_execution_failure", ...)` 경로로만 합류시키고(§4의 대안 C 상세 표), 새로운 job 상태나 새로운 종결 사유를 만들지 않는다.
- `_is_fdc_actual_dispatch_target()`/`_is_fdc_actual_dispatch_buy_target()` 판정 로직 변경 금지.

### 5.4 세부 Acceptance Criteria
1. legacy `mode="full"` 경로와 held_position actual-dispatch 경로를 동시에 시뮬레이션해도(단위/통합 테스트에서 fake clock 사용), provider 전체 HTTP 시작 시각 기준 sliding 60초 윈도우 내 시작 건수가 13을 초과하지 않는다.
2. 429/5xx로 인한 모든 재시도가 gate 통과 시점 기준으로 정확히 1회씩 회계에 반영된다(재시도 2회 발생 시 window에 2건 기록, 0건도 3건도 아님).
3. gate를 우회해 HTTP를 보낼 수 있는 코드 경로가 0건이다(`rg`로 `client.post()`/`generate_structured_once()` 호출부 전수 조사해 gate 미경유 호출 없음을 확인하는 정적 검사 테스트 포함).
4. gate 플래그가 꺼져 있으면 완전 no-op(기존 두 경로가 지금과 동일하게 독립 동작).
5. held_position REDUCE/SELL의 기존 FIFO 순서, durable-resume, fail-closed 테스트(PR A~C에서 이미 있는 테스트)가 gate 도입 후에도 전부 그대로 통과한다(회귀 없음).
6. legacy fallback HOLD 의미론(`reason_codes`에 provider fallback 마커)이 gate로 인한 대기/거부 상황에서도 동일하게 유지된다 — gate가 permit을 못 주는 경우도 기존 legacy 429/timeout과 동일한 fallback 경로로 흡수되어야 한다.
7. 프로세스(subprocess) 강제 종료/timeout 시 gate 쪽에도 permit 누락/중복 소비가 없다 — 기존 `cancel_stale_real_jobs()`류 정리 로직과 동등한 정리 메커니즘을 gate 쪽에도 마련(또는 기존 로직 재사용 가능함을 증명).
8. **(보정 1 신설)** actual job이 `try_reserve()` grant를 받은 뒤 global gate에서 대기/거부되면, `fdc_provider_attempts.outcome`이 `reserved_but_http_not_started`로, `fdc_queue_jobs`가 `apply_retry_failure(reason="pre_http_execution_failure", will_retry=...)` 경로로 전이되며(§4 대안 C 상세 표와 정확히 일치), `will_retry=True`인 경우 새 `try_reserve()`(새 `attempt_no`, 새 `enqueue_sequence`)로만 재시도된다 — 기존 reservation을 재사용하지 않는다.
9. **(보정 1 신설)** actual coordinator의 window(엔타이틀먼트 판정)와 global gate의 window(물리적 HTTP 총량 판정)가 각각 독립적으로 13 RPM을 판단하되, 어느 한쪽의 grant/거부가 다른 쪽의 카운트를 이중 반영하거나 상쇄하지 않는다(§4 대안 C 상세의 책임 분리 서술 참고).
10. **(보정 2 신설)** `OpenAICompatibleClient`/`LiveGeminiProviderClient`(EI/AR/AC 및 일반 호출이 공유하는 클래스)는 gate 도입 전후로 코드 변경이 0건이며, gate 호출은 `_FdcPermitAccumulator.acquire()`와 `PreGrantedFdcProviderClient`/`execute_fdc_one_shot_attempt()` 두 곳에서만 이뤄진다.
11. **(2026-09-03 보정 신설)** legacy `mode="full"` 경로에서 `_FdcPermitAccumulator.acquire()`는 항상 `wait_for_fdc_slot()` grant를 먼저 확인한 뒤에만 global gate를 호출한다(순서 역전 없음) — legacy limiter가 거부하면 gate는 아예 호출되지 않는다.
12. **(2026-09-03 보정 신설)** legacy limiter grant 후 global gate가 timeout/거부/DB 오류를 내면 실제 HTTP는 0건이며, `PermitDeniedError` 기존 메커니즘을 통해 `decision_type="HOLD"` fallback으로 귀결되고, `reason_codes`에 legacy 자신의 `provider_queue_timeout`과 구분되는 gate 전용 마커(예: `provider_global_gate_unavailable`)가 남는다.
13. **(2026-09-03 보정 신설)** global gate의 window 슬롯은 grant 시점에 소비되며(HTTP 실제 시작 여부와 무관, 보수적 소비), gate grant 후 HTTP 시작 전에 실패해도 window count가 환불되지 않는다 — 이 규칙으로 인해 provider 전체 실제 HTTP 시작 수가 13을 넘는 방향으로는 절대 오차가 나지 않음을 테스트로 증명한다.

### 5.5 단위/통합 테스트 목록 (최소)
- gate 단독: 60초 sliding window 13 RPM 강제(정상/경계값/초과 케이스), 429 재시도 2~3회 시나리오, legacy+actual 동시 시뮬레이션 혼합 케이스
- gate off 시 완전 no-op 검증(기존 두 경로 동작 불변)
- 정적 검사: HTTP 발신 호출부 전수 gate-경유 검증
- held_position 기존 회귀 테스트 스위트 전체 재실행(변경 없이 통과 확인)
- legacy fallback HOLD 마커 보존 테스트(gate 거부/대기 상황 포함)
- 프로세스 재시작/강제종료 시 gate 상태 정리 테스트
- **(보정 1 신설)** legacy가 global gate window를 이미 점유한 상태에서, actual job이 `try_reserve()` reservation은 받았지만 global gate에서 대기하는 시나리오 — reservation은 성공했으나 HTTP는 아직 시작되지 않은 중간 상태를 직접 검증
- **(보정 1 신설)** global gate 거부/timeout 시 `fdc_provider_attempts.outcome`/`http_started_at`/`fdc_queue_jobs.status`/`permit_consumed_count`/`queue_reenqueue_count`/`provider_retry_count`가 §4 대안 C 상세 표와 정확히 일치하는지 검증
- **(보정 1 신설)** global gate 대기 중 subprocess가 강제 종료되는 시나리오 — `get_attempt_http_lifecycle()`이 `NOT_STARTED`로 판정하고 기존 recovery 경로(재개 또는 fail-closed 종결)로 정확히 합류하는지 검증
- **(보정 1 신설)** 재시도 시나리오에서 global gate 기록(gate 자체의 통과/거부 로그 또는 카운터)과 actual `fdc_provider_attempts` 기록이 각각 정확히 1회씩만 남는지 검증(이중 기록 없음)
- **(보정 1 신설)** 위 모든 이중 관문 시나리오에서 실제 HTTP 시작 시각 기준 60초 window 최대 13건이 유지되는지 종합 검증
- **(보정 2 신설)** FDC 최초 호출과 429/5xx 재시도가 매번 gate를 통과하는지 검증(호출 횟수만큼 gate 통과 기록이 남는지)
- **(보정 2 신설)** EI/AR/AC 호출 시나리오에서 gate mock이 0회 호출되는지 검증(공용 클래스 경로에는 gate가 전혀 개입하지 않음을 직접 증명)
- **(보정 2 신설)** gate off 상태에서 legacy FDC의 기존 limiter(`wait_for_fdc_slot()`)/fallback HOLD 의미론이 gate 도입 이전과 동일하게 유지되는지 검증
- **(보정 2 신설)** actual `PreGrantedFdcProviderClient`가 global gate를 통과하지 못하면 `client.post()`(실제 HTTP)를 전혀 호출하지 않는지 검증(mock으로 HTTP 호출 0회 확인)
- **(2026-09-03 보정 신설)** legacy limiter grant 후 global gate timeout 시나리오 — `wait_for_fdc_slot()`은 성공(grant)했지만 gate가 timeout으로 거부하는 경우, `client.post()` 호출 0회 및 `PermitDeniedError`를 통한 HOLD fallback을 직접 검증
- **(2026-09-03 보정 신설)** global gate grant 후 HTTP 시작 전 실패 시나리오 — gate window count가 환불되지 않고 그대로 소비된 채 유지되는지 검증
- **(2026-09-03 보정 신설)** 429 재시도 3회 시나리오에서 legacy limiter 호출 횟수와 global gate 호출 횟수가 각각 정확히 3회(attempt 수만큼)씩만 기록되는지 검증(이중 계산/누락 없음)
- **(2026-09-03 보정 신설)** EI/AR/AC 호출 경로에서 global gate mock이 0회 호출되는지 검증(legacy/actual 전용 주입 경계 재확인 — 보정 2 테스트와 중복 방지를 위해 별도 시나리오로 유지하되 동일 assertion 재사용 가능)
- **(2026-09-03 보정 신설)** legacy+actual+gate를 모두 동시에 시뮬레이션해도 실제 HTTP 시작 시각 기준 60초 window 최대 13건이 유지되는지(legacy limiter grant 후 gate timeout으로 낭비되는 슬롯이 있어도 물리적 HTTP 총량이 13을 넘지 않음을 종합 검증)

### 5.6 Harness 검증 명령

`accept migration`은 존재하지 않는 명령이다(harness에 없음) — 아래는 실제 존재가 확인된 명령만 남긴 것이며, §5.2의 예상 변경 파일이 실제로 확정된 뒤 `accept backend-file`/`accept script-file` 대상은 재조정한다.

```bash
bash scripts/harness/run.sh accept backend-file src/agent_trading/repositories/postgres/fdc_quota.py
bash scripts/harness/run.sh accept script-file scripts/run_agent_subprocess.py
bash scripts/harness/run.sh accept script-file scripts/fdc_manual_provider_gate.py
bash scripts/harness/run.sh test-file tests/services/test_fdc_quota_coordinator.py
bash scripts/harness/run.sh accept env
bash scripts/harness/run.sh accept db-structure
bash scripts/harness/run.sh accept no-bypass
bash scripts/harness/run.sh accept architecture
```

`accept db-structure`는 migration 파일명/번호 연속성과 Repository Protocol wiring만 정적으로 검사하며 DB 접속·외부 네트워크·전체 테스트를 실행하지 않는다(`database_connection_run=0`/`external_network_run=0`/`full_test_run=0` 지표로 harness 자체가 보증, `scripts/harness/README.md:314-323`) — 신규 테이블/migration이 실제로 추가되는 경우 이 명령으로 검증한다. `provider_client.py`는 §5.3에서 수정 자체를 금지하므로 이 파일에 대한 `accept backend-file`은 이 목록에 포함하지 않는다.

### 5.7 migration 필요 여부
**미확정 — PR D 구현 착수 시 최우선으로 재확인할 사항.** 권고안(대안 C)은 기존 `fdc_provider_attempts` 재사용을 우선 검토하도록 권고했으나, `mode` CHECK 제약이 `'shadow'|'real'`만 허용하고 legacy 전용 구분자가 없어 `caller_id` 컬럼만으로 legacy/actual을 구분할 수 있는지, 혹은 gate 전용 신규 경량 테이블(예: `fdc_provider_http_starts`)이 필요한지는 스키마 제약 조건을 다시 정밀히 검토해야 한다. 신규 테이블이 필요하면 최소 컬럼(gate_scope, started_at, caller_id 정도)으로 범위를 최소화할 것. 신규 테이블/migration 파일 작성 후에는 §5.6의 `accept db-structure`(migration 파일명·번호 연속성, Repository Protocol wiring 정적 검사)로 검증한다 — `accept migration`이라는 명령은 harness에 존재하지 않는다.

### 5.8 shadow/actual rollout 순서
1. **Phase D-1 (shadow)**: gate를 신설하되 `FDC_PROVIDER_GLOBAL_QUOTA_GATE_ENABLED=false` 기본값으로 배선만 완료, 실제 HTTP 경로에는 연결하지 않음(PR C와 동일한 패턴 — 배선 검증만).
2. **Phase D-2 (shadow-observe)**: gate를 관측 전용으로 켜서(HTTP를 막지 않고 window 카운트만 기록) legacy+actual 합산 실제 트래픽이 13 RPM 안에 들어오는지 스테이징/운영에서 최소 수일 관측.
3. **Phase D-3 (enforce)**: 관측 결과 문제 없으면 gate를 실제 강제(permit 거부 가능) 모드로 전환.
4. **PR D 완료 후에도 `FDC_ACTUAL_DISPATCH_BUY_ENABLED`는 여전히 runtime에서 읽지 않는 상태를 유지** — BUY actual-dispatch 연결은 PR D 이후의 별도 PR E 범위(§6 참고).

### 5.9 즉시 중단 및 rollback 조건
- gate 강제 모드 전환 후 provider 전체 429 비율이 도입 전 대비 유의미하게 증가하면 즉시 관측 모드로 롤백.
- held_position REDUCE/SELL의 실제 dispatch 성공률이 gate 도입 전후로 하락하면 즉시 `FDC_PROVIDER_GLOBAL_QUOTA_GATE_ENABLED=false`로 롤백(no-op 복귀가 설계상 보장돼야 함 — AC 4).
- gate 자체의 버그로 인해 정상 permit이 부당하게 거부되는 사례가 1건이라도 확인되면 강제 모드를 즉시 중단.

---

## 6. BUY actual-dispatch 활성화의 명시적 선행 조건

BUY/core lane actual-dispatch(`FDC_ACTUAL_DISPATCH_BUY_ENABLED`를 실제 실행 경로에 연결하는 PR E)를 시작하기 전에 다음이 모두 충족돼야 한다:

1. PR D(본 설계)가 병합되고, gate가 최소 Phase D-2(shadow-observe)까지 완료되어 legacy+actual 합산 실제 트래픽이 13 RPM 이내임이 운영/스테이징 관측으로 확인됨.
2. held_position REDUCE/SELL의 기존 회귀 테스트 스위트가 gate 도입 후에도 전부 통과 상태 유지.
3. PR D의 AC 3(gate 우회 경로 0건)이 정적 검사로 지속 강제됨(harness `accept no-bypass`/`accept architecture` 등에 편입 권장).
4. BUY/core PR C의 shadow 관측(`FDC_ACTUAL_DISPATCH_BUY_SHADOW_ENABLED`)이 최소 1주 이상 운영에서 관측되어, BUY 후보 발생 빈도와 FDC-ready 타이밍 분포가 gate의 13 RPM 여유 안에서 감당 가능한 수준임이 데이터로 확인됨.
5. gate의 rollback 절차(§5.9)가 실제로 1회 이상 드릴(dry-run) 형태로 검증됨.

이 문서는 설계 검토용이며 코드 변경을 포함하지 않는다. BUY actual-dispatch 연결이나 `FDC_ACTUAL_DISPATCH_BUY_ENABLED`의 runtime 조건 분기 추가는 이번 작업 범위에서 수행하지 않았다.
