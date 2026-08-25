# FDC cycle-scoped batch queue + Gemini 공용 13 RPM quota 설계 확정

## 배경

PR #313(in-cycle FIFO 재대기열)의 배포 후 실측(별도 read-only 조사)에서
재대기 128건 중 재대기 후 실제 HTTP 성공 사례가 0건임을 확인했다. 이후
여러 차례의 read-only 설계 검토를 거쳐, 근본 해결책으로 "cycle-scoped
strict batch queue + PostgreSQL 기반 공용 13 RPM quota coordinator"
아키텍처를 확정했다. 이번 턴은 그 설계를 문서로 확정하는 작업이며,
런타임 코드/migration/compose/`.env` 변경은 포함하지 않는다.

## 확정한 핵심 계약

1. **Cycle-scoped 순차 구조 유지**: 사이클 병행 실행이나 supersede 없이,
   기존처럼 한 사이클이 끝나야 다음 사이클이 시작된다. `run_decision_
   loop.py`의 `interval`이 "완료 후 sleep"이지 "고정 시작 간격"이 아님을
   코드로 재확인해, 사이클이 3~4분 늘어나도 코드 변경 없이 자연스럽게
   수용됨을 확인했다.
2. **PostgreSQL singleton anchor 행 잠금 기반 atomic reservation**: "최근
   reservation 행"이 아니라 "항상 존재하도록 seed된 고정 행"을 `FOR
   UPDATE`로 잠가 phantom insert 경쟁 조건을 원천 차단한다 — 이 저장소에
   이미 있는 `kis_fill_cumulative_state.py`의 행 잠금 관례를 그대로 재사용
   한다.
3. **dispatcher 완전 소유 permit ownership**: FDC provider client는 HTTP
   1회만 시도하는 one-shot 인터페이스로 축소하고, retry/backoff/FIFO
   재등록은 dispatcher가 전담한다. 기존 공용 `provider_client.
   generate_structured()`(EI/AR/AC 구식 클래스가 참조)는 무근거로 변경
   하지 않는다 — 운영에서 EI/AR/AC는 애초에 Gemini를 호출하지 않는다는
   것을 `runtime/bootstrap.py`로 확인했기 때문이다.
4. **quota 우회 경로 통제**: `scripts/ar_fdc_output_measurement.py
   --with-provider`, `scripts/ar_fdc_provider_validation.py` 두 스크립트가
   현재 limiter를 완전히 우회할 수 있다는 것을 코드로 확인했다.
   `LiveGeminiProviderClient`/`FakeProviderClient` 타입 분리로, live
   provider 호출은 coordinator 없이는 애초에 생성 자체가 불가능하도록
   강제하는 것으로 이 문제를 해소한다(플래그 기반 구분은 오설정 우회
   위험이 있어 배제).
5. **영속 스키마**: `fdc_quota_state`(singleton anchor), `fdc_queue_jobs`
   (job 최신 상태), `fdc_provider_attempts`(append-only, reservation
   1회=attempt 1행) 3-테이블 구조로, 재기동 후 미완료 job의 마지막 상태를
   DB에서 사후 확인할 수 있게 한다.
6. **즉시 저장 유지**: FDC job이 완료되는 즉시 기존 `assemble()`으로
   저장한다(배치 전체 종료를 기다리지 않음) — `decision_orchestrator.py`
   의 `assemble()`이 이미 종목별 즉시 저장 구조임을 코드로 재확인해,
   이 성질을 보존하는 것으로 확정했다.

## 문서화한 파일

- `docs/40_action_plans/fdc_cycle_scoped_batch_queue_gemini_shared_
  13rpm_quota_design_2026-08-25.md`(신규, 16개 장 구성: 배경/목표·비목표/
  현재 구조와 탈락 원인/확정 아키텍처/상태 전이도/atomic reservation
  transaction 계약/worker·retry·freshness·즉시 저장 계약/영속 스키마와
  migration 계획/accounting 정의/13 RPM 용량 계산/수동 provider 호출
  정책/live provider fail-closed 경계/설정 계약/관측 SQL 요구사항/
  테스트·단계적 도입 계획/위험·롤백·확정 계약 vs 실측 필요 사항 분리)
- `docs/99_meta_handover/[BACKLOG] backlog.md`(신규 섹션 추가)

## 명시적으로 보류한 사항 / 미확인 사항

- `FDC_WORKER_CONCURRENCY=5`가 13 RPM을 실제로 소진하기에 충분한지는
  구현 후 실측이 필요하다(문서에 "확정된 구현 계약"이 아니라 "구현 후
  실측 필요" 항목으로 명시적으로 분리 기재).
- PG 행 잠금이 실제 트래픽에서 유발하는 지연 정도는 실측하지 않았다.
- `MAX_RETRIES`→`max_http_attempts` 리네이밍의 전체 코드 참조 범위는
  전수 확인하지 않았다(구현 PR에서 확인 필요).
- Gemini의 실제 quota 적용 단위(API 키/프로젝트/모델)는 외부 provider
  정책이라 이 문서로 확정할 수 없다.

## 검증

`bash scripts/harness/run.sh accept docs` — PASS (상세는 완료 보고 참고).

## 변경 파일

- `docs/40_action_plans/fdc_cycle_scoped_batch_queue_gemini_shared_13rpm_quota_design_2026-08-25.md`(신규)
- `docs/99_meta_handover/[BACKLOG] backlog.md`(섹션 추가)
- `docs/30_work_log/2026-08-25_fdc_cycle_scoped_batch_queue_design.md`(본 문서, 신규)

## 다음 단계

사용자 승인 후 구현 PR 착수: migration 작성(`fdc_quota_state`/
`fdc_queue_jobs`/`fdc_provider_attempts`) → dispatcher/coordinator 코드
→ FDC one-shot 인터페이스(`generate_structured_once()`) → `Live
GeminiProviderClient`/`FakeProviderClient` 타입 분리 → 설정 배선
(`settings.py`/`.env.example`/compose) → 테스트(§15 시나리오) → 단계적
도입(①lifecycle 관측 shadow → ②held_position 한정 → ③전체 전환).
이번 문서화 턴에서는 미착수.

## 2차 개정(2026-08-25, 같은 날 후속) — 4개 계약 충돌 보정

최초 확정본에 남아있던 4개 계약 충돌을 사용자 지적에 따라 보정했다(같은
PR #350, 브랜치·PR 신규 생성 없이 기존 브랜치에 추가 커밋).

1. **reservation 단일 소유권 명확화**: "dispatcher가 permit을 완전히
   소유한다"와 "FDC one-shot도 coordinator를 호출한다"는 표현이 병존해
   이중 reservation처럼 읽히던 문제를 정정했다. 확정 계약: reservation을
   실제로 요청하는 주체는 dispatcher 하나뿐이고, `generate_structured_
   once(grant)`는 dispatcher가 발급받은 `ReservationGrant`를 값으로
   전달받아 검증·소비만 한다 — coordinator에 새 reservation을 절대
   요청하지 않는다. §12에 어느 함수가 reservation을 새로 요청하는지
   정리한 표를 추가했다.
2. **수동 provider 호출 정책과 job 모델 확정**: "수동 호출도 `fdc_queue_
   jobs.job_id`가 필요하다"는 미확정 서술을 폐기하고, A안(운영 시간
   기술적 fail-closed 차단 + 비운영 시간 수동 호출은 coordinator
   reservation만 공유하고 FDC FIFO/worker slot은 점유하지 않음)을
   채택했다. `fdc_provider_attempts.job_id`를 nullable로, 수동 호출은
   `manual_run_id`로 연결하도록 스키마를 수정했다. `fdc_queue_jobs`에는
   수동 호출 row를 만들지 않는다.
3. **retry/pre-HTTP 실패 계수 분리**: 단일 `retry_count`가 "실제 HTTP
   실패 후 재등록"과 "reservation 성공 후 HTTP 시작 전 실패로 인한
   재등록"을 혼재시켜 `retry_count ≤ max_http_attempts-1` 불변식이
   깨지던 문제를 `provider_retry_count`/`pre_http_execution_failure_
   count`/`queue_reenqueue_count` 3개 필드로 분리해 해소했다. 상태
   전이도·스키마·accounting 정의·테스트 계획 전부에 반영했다.
4. **sliding 60초 경계 규칙 일치**: coordinator 판단 SQL(`reserved_at >
   now() - interval '60 seconds'`, 반열림)과 이전 감사 SQL의 `RANGE
   BETWEEN ... PRECEDING` window frame(경곗값 포함)이 서로 다른 규칙을
   써서 경계에서 결과가 어긋날 수 있던 문제를 self-join 기반 감사 SQL로
   정정해 동일한 `(t-60초, t]` 반열림 규칙을 쓰도록 통일했다.

이번 개정은 §4·§5·§6·§7·§8·§9·§11·§12·§14·§15·§16을 수정했다. 런타임
코드/migration/compose/`.env` 변경은 이번에도 없다.

## 2차 검증

`bash scripts/harness/run.sh accept docs` — PASS(상세는 완료 보고 참고).

## 3차 개정(2026-08-25, 같은 날 후속) — accounting 정의·스키마 정합성 보정

2차 개정에서 도입한 `provider_retry_count`/`pre_http_execution_failure_
count`/`queue_reenqueue_count` 3분리와 별개로, accounting 표 자체에 남아있던
내부 모순 2건을 보정했다(같은 PR #350, 브랜치·PR 신규 생성 없이 추가 커밋).

1. **`dispatch_attempt_no` 정의 통일**: accounting 표는 "reservation을
   실제로 받아 worker 실행으로 넘어간 횟수"로 정의했으나, 사례 설명에는
   "reservation이 거부된 경우 `dispatch_attempt_no`만 증가"라는 모순된
   문장이 있었다. **"reservation 성공(`ReservationGrant` 발급) 시에만
   증가하고, 거부 시에는 증가하지 않는다"**로 통일했다. 거부 시에는
   `queue_poll_count`와 `reservation_denied_count`만 증가하도록 명시적
   불변식 블록을 §9에 추가했다.
2. **`reservation_denied_count` 스키마 누락 보완**: accounting 표에는
   있었으나 `fdc_queue_jobs` 컬럼 표에 누락돼 있던 `reservation_denied_
   count`를 스키마에 추가했다(A안 채택 — job 단위 누적 카운터로 저장,
   `fdc_provider_attempts`에는 넣지 않음 — 그 테이블은 "성공한 attempt
   1건=1행" 원칙이라 거부를 넣으면 원칙이 깨짐). 초기값 0, 원자적 증가
   시점, lane별 queue 혼잡 분석 용도, `queue_poll_count = reservation_
   denied_count + dispatch_attempt_no` 정합성 검증 SQL을 §8·§9·§14에
   추가했다.

이번 개정은 §8·§9·§14·§15·§16을 수정했다. 런타임 코드/migration/compose/
`.env` 변경은 이번에도 없다.

## 3차 검증

`bash scripts/harness/run.sh accept docs` — PASS(상세는 완료 보고 참고).

## 4차 개정(2026-08-25, 같은 날 후속) — coordinator 오류 경로와 accounting 항등식 충돌 보정

`queue_poll_count = reservation_denied_count + dispatch_attempt_no`
항등식과 DB/coordinator 오류(fail-closed) 경로가 서로 충돌하던 문제를
보정했다(같은 PR #350, 추가 커밋).

- coordinator 오류(DB unavailable/lock timeout/transaction 오류)는
  `GRANTED`도 `DENIED`도 아닌 "결론 자체를 못 받은" 시도라, 위 세 카운터
  중 어느 것도 증가시키지 않기로 확정했다(A안 — `reservation_error_count`
  를 추가하는 B안은 기각. 이유: DB 자체가 unavailable이면 그 오류 자체를
  `fdc_queue_jobs` row에 영속 기록할 방법이 없어, B안의 "오류도 영속
  카운터로 관리"라는 전제가 정확히 그 시나리오에서 성립하지 않는다).
- `COORDINATOR_UNAVAILABLE`/`COORDINATOR_LOCK_TIMEOUT`/`COORDINATOR_
  TRANSACTION_ERROR` 3종 오류 분류, worker slot 즉시 반환, 지수 backoff
  (초기 1초/상한 30초, 신규 설정 2건), DB 복구 후 자동 재개, DB 자체가
  내려간 동안의 최소 관측 근거(프로세스 로그/in-memory counter/사이클
  요약 로그 — 전부 휘발성, DB 영속 아님)를 §6에 상세 계약으로 추가했다.
- coordinator 오류가 아무리 지속돼도 `CANCELLED`(시장 종료/운영자/
  프로세스 종료 3사유 한정)가 자동으로 발동하지 않는다는 것을 명시하고,
  장기 장애 시 표준 대응은 운영자의 수동 `operator_cancel` 개입임을
  운영 절차로 문서화했다(자동 시간제한 신설 아님).

이번 개정은 §5·§6·§9·§13·§15·§16을 수정했다. 런타임 코드/migration/
compose/`.env` 변경은 이번에도 없다.

## 4차 검증

`bash scripts/harness/run.sh accept docs` — PASS(상세는 완료 보고 참고).
