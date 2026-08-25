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
