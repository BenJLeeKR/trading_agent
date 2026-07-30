# 권고사항 이후 Harness Engineering 후속 작업 계획

## 목적

이 문서는 배포 경로, 하네스 계약, 런타임 산출물 보호, CI 재현성에 대한 권고사항 이후의 후속 작업을 우선순위별로 추적하기 위한 실행 계획이다.

작업자는 각 항목을 진행할 때 체크리스트의 완료 여부, 검증 지표, 남은 판단 사항을 갱신한다. 완료된 작업은 [완료된 작업](#완료된-작업) 장으로 이동하거나 동일 항목의 상태를 `완료`로 바꾼다.

## 상태 표기

- `[ ]`: 미착수
- `[~]`: 진행 중
- `[x]`: 완료
- `[!]`: 보류 또는 사용자 결정 필요

## 우선순위별 작업 체크리스트

### P0 — 배포 런타임 산출물 보호

목표: 운영 서버 배포 중 `git reset --hard`가 런타임 쓰기 경로를 되돌리거나 운영 산출물을 훼손하지 못하게 한다.

- [x] `tmp/`, `logs/`, `data/`의 tracked 파일 목록을 목적별로 분류한다.
- [x] 런타임 산출물과 canonical 입력 데이터의 기준을 문서화한다.
- [x] `logs/`, `tmp/`는 원칙적으로 Git 추적 대상에서 제외한다.
- [x] `data/`는 전체 제외 여부를 바로 결정하지 않고 `data/runtime/`, `data/cache/`, `data/local/` 같은 mutable 하위 경로 분리를 먼저 검토한다.
- [x] 필요한 seed, example, fixture 파일은 `tests/fixtures/`, `docs/`, 또는 `*.example` 경로로 이동할지 결정한다. `logs/`는 대량 보존보다 코드 텍스트 전환 우선 정책으로 결정했고, 남은 `data/` tracked 파일 `10`개는 canonical 입력 허용 목록으로 유지한다.
- [x] `.gitignore`에 runtime write path 패턴을 추가한다.
- [x] 기존 tracked 런타임 파일은 `git rm --cached` 또는 경로 이동으로 정리한다. `tmp/` tracked 파일 `55`개, `logs/` tracked 파일 `2560`개, `data/instrument_master/archive/` tracked 파일 `33`개, `data/observations/` tracked 파일 `6`개, root JSON 후보 `21`개, `data/ar_fdc_*.json` tracked 파일 `2`개는 제거 완료했고, 남은 `data/` `10`개는 canonical 입력 허용 목록으로 유지한다.
- [x] 배포 workflow에 `git clean -fdx` 또는 동등한 파괴적 clean 명령이 들어가지 않도록 `accept ci` 검사에 추가한다.
- [x] `accept ci`에 tracked runtime write path 카운트 검사를 추가한다.

완료 기준:

- `runtime_tracked_file_count`가 합의된 허용 목록을 제외하고 `0`이다.
- `destructive_deploy_clean_command_count`가 `0`이다.
- 배포 job이 untracked/ignored runtime 파일을 삭제하지 않는다는 정적 검사 결과가 보고된다.

분류 상세는 [`runtime_write_path_inventory.md`](../30_work_log/runtime_write_path_inventory.md)를 따른다.
`data/` 상세 분리 판정은 [`data_runtime_canonical_split_review.md`](../30_work_log/data_runtime_canonical_split_review.md)를 따른다.
canonical data 허용 목록과 owner 기준은 [`canonical_data_contract.md`](../20_harness_engineering/canonical_data_contract.md)를 따른다.

### P1 — 장 시간 배포 가드와 수동 재배포 진입점

목표: 정규장 중 자동 배포를 기본 차단하되, 사용자 명시 승인이 있는 경우에만 배포할 수 있게 한다. 장중 차단으로 폐기된 배포는 장종료 후 최신 `origin/main` 기준으로 새로 재배포한다.

- [x] `workflow_dispatch`에 `deploy_main` 입력을 추가한다.
- [x] `workflow_dispatch`에 `allow_market_hours_deploy` 입력을 추가한다.
- [x] 수동 배포는 항상 최신 `origin/main` SHA를 대상으로 실행한다.
- [x] 폐기된 과거 workflow run을 장종료 후 자동 재개하지 않는다는 정책을 문서화한다.
- [x] KST 기준 정규장 시간대를 계산하는 guard를 deploy job 앞에 추가한다.
- [x] 장중 + 승인 없음이면 배포를 중단하고 `deploy_skipped_by_market_hours_count=1`을 출력한다.
- [x] 장중 + 승인 있음이면 `allow_market_hours_deploy=true` 입력과 함께 `deploy_market_hours_override_count=1`을 출력한다.
- [x] 장종료 후 수동 재배포는 `deploy_manual_dispatch_count=1`과 `deploy_target_sha=<sha>`를 출력한다.
- [x] `accept ci`가 수동 재배포 입력과 장 시간 guard 지표를 검사하도록 확장한다.

완료 기준:

- 자동 `push main` 배포와 수동 `workflow_dispatch` 배포가 모두 `Safe harness contracts` 이후에만 실행된다.
- 장중 무승인 배포 시도는 재기동 없이 skip 지표를 남긴다.
- 장종료 후 사용자가 AI에게 재배포를 요청하면 공식 dispatch 진입점으로 새 run을 실행할 수 있다.

### P2 — `check quick`과 CI safe 범위 불일치 해소

목표: 로컬의 빠른 검증과 CI 필수 검증이 과도하게 어긋나지 않게 한다.

- [x] 현재 `check quick` 단계 수와 CI `safe` job 단계 수를 카운트한다.
- [x] 부하가 작은 필수 계약을 `check quick`에 포함할지 판단한다.
- [x] 부하가 큰 항목은 `check full`을 신설해 CI safe와 등가로 둘지 판단한다.
- [x] `AGENTS.md`의 커밋 전 권장 명령이 실제 정책과 일치하도록 수정한다.
- [x] `scripts/harness/README.md`에 `check quick`과 `check full`의 역할 차이를 명시한다.
- [x] `accept ci`에 required harness command와 로컬 명령 간 괴리 카운트를 추가한다.

완료 기준:

- `quick_step_count`, `full_step_count`, `ci_safe_step_count`가 보고된다.
- 로컬에서 요구하는 명령과 CI required check 사이의 의도하지 않은 누락 수가 `0`이다.

### P3 — CI 환경 재현성 계약 강화

목표: CI가 로컬/운영과 같은 dependency lock 계약을 사용하게 한다.

- [x] `harness.yml`의 `pip install` 경로를 전수 확인한다.
- [x] 가능한 모든 `pip install`에 `--constraint requirements.lock`을 적용한다.
- [x] lock 적용이 불가능한 설치 경로는 명시 예외로 문서화한다. 현재 예외 경로 수는 `0`이다.
- [x] `accept ci`가 workflow의 Python dependency 설치에서 `requirements.lock` constraint 사용 여부를 검사하도록 확장한다.
- [x] Node.js와 PostgreSQL 버전 고정 문서가 실제 CI 설정과 일치하는지 확인한다.

완료 기준:

- `pip_install_without_constraints_count`가 `0`이거나, 예외 목록과 카운트가 함께 보고된다.
- CI에서 사용하는 Python/Node/PostgreSQL 버전 기준이 문서와 일치한다.

### P4 — 문서 자기검증과 중복 정리

목표: 문서가 하네스 명령과 실제 파일 경로를 잘못 안내하지 않게 한다.

- [x] `CLAUDE.md`의 명령 목록 중복을 줄이고 `AGENTS.md`, `scripts/harness/README.md` 링크 중심으로 정리한다.
- [x] `accept docs`가 문서 속 `bash scripts/harness/run.sh <command>` 문자열의 실존 여부를 검사하도록 확장한다.
- [x] `run.sh`의 command selector 목록을 파싱해 문서 내 명령과 대조한다.
- [x] `docs/99_meta_handover/agent_workspace_guide.md`에 `.claude/worktrees/` 그림자 사본 경고를 추가한다.
- [x] 코드 검색 시 `.claude/` 경로를 제외하라는 지침을 추가한다.
- [x] README의 `.nvmrc`, `.npm-version` 표기가 실제 `admin_ui/` 하위 경로를 가리키는지 확인한다.

완료 기준:

- `documented_run_sh_command_missing_count`가 `0`이다.
- `claude_command_duplication_count`가 감소하거나, 남은 중복이 의도된 예외로 문서화된다.

### P5 — 장중 배포 정책 고도화

목표: 장중에는 전체 배포를 일괄 차단하지 않고, runtime 영향이 없는 제한된 source sync 후보를 분리할 수 있도록 CI 분류 계약을 먼저 세분화한다.

- [x] `changes` job이 기존 `deploy_required` 외에 `activate_required`를 출력하도록 확장한다.
- [x] `changes` job이 `sync_only_candidate_count`, `sync_only_allowlist_count`, `sync_only_blocked_count`를 출력하도록 확장한다.
- [x] 장중 sync-only 허용 후보 `scripts/` allowlist `7`개를 workflow 정적 규칙으로 선언한다.
- [x] runtime-affecting 경로 denylist를 workflow 정적 규칙으로 선언한다.
- [x] `accept ci`가 위 신규 출력과 정적 규칙 존재 여부를 검사하도록 확장한다.
- [x] 실제 `sync_source` / `activate_runtime` job 분리와 장중 sync-only 실행 조건을 workflow에 반영한다.
- [x] `accept ci`가 `sync_source`, `activate_runtime`, activate guard, sync/activate 실행 지표 존재 여부를 검사하도록 확장한다.

완료 기준:

- `deploy_activate_required_output_count=1`
- `deploy_sync_only_candidate_count_output_count=1`
- `deploy_sync_only_allowlist_count_output_count=1`
- `deploy_sync_only_blocked_count_output_count=1`
- `deploy_sync_only_allowlist_defined_count=1`
- `deploy_runtime_affecting_path_rule_count=1`
- `deploy_sync_job_present_count=1`
- `deploy_activate_job_present_count=1`
- `deploy_activate_guard_present_count=1`
- `deploy_sync_only_run_metric_count=1`
- `deploy_activate_run_metric_count=1`
- `deploy_activate_skipped_by_market_hours_metric_count=1`

## 완료된 작업

### 배포 경로 하네스 종속화

- [x] 운영 배포 job을 `.github/workflows/harness.yml` 안에서 `Safe harness contracts` 이후에만 실행하도록 구성했다.
- [x] 문서-only 변경은 `deploy_required=0`으로 판정해 운영 재기동을 실행하지 않도록 구성했다.
- [x] 배포 재기동 전에 `docker compose run --rm migrate`를 실행하도록 구성했다.
- [x] `docker-compose` v1 명령 대신 `docker compose` v2 명령을 사용하도록 정리했다.
- [x] 배포 재기동 뒤 `nginx-proxy`를 reload해 Docker DNS stale upstream 문제를 줄이도록 구성했다.

### 하네스 계약과 문서 체계

- [x] `docs/20_harness_engineering/` 아래에 Harness Engineering 규칙성 문서를 모았다.
- [x] `Definition of Done` 문서를 추가해 AI가 완료를 주장할 수 있는 조건을 명시했다.
- [x] 우회 행동 금지 정책을 추가하고 hard fail과 review 대상의 차이를 문서화했다.
- [x] `CLAUDE.md`가 `AGENTS.md`와 Harness Engineering 문서를 참조하도록 정리했다.
- [x] 문서, 보고, 설명에서 중국어 사용 금지 규칙을 반영했다.

### 오류 메시지 보강 1차 범위

- [x] 기존 문자열 `detail` 응답을 유지하는 방향으로 오류 메시지 보강 범위를 제한했다.
- [x] 신규 구조화 응답은 opt-in 또는 helper 테스트에서만 고정한다는 원칙을 반영했다.

### P0 1차 — 배포 파괴 명령 차단과 runtime ignore 기준

- [x] `.gitignore`에 `logs/`, `tmp/`, `data/runtime/`, `data/cache/`, `data/local/`를 runtime write path로 등록했다.
- [x] `accept ci`에 `destructive_deploy_clean_command_count`를 추가해 배포 workflow의 `git clean -fdx` 또는 runtime 경로 직접 삭제 명령을 실패로 판정하게 했다.
- [x] `accept ci`에 `runtime_tracked_file_count`를 정보 지표로 추가했다.
- [x] 현재 tracked runtime path는 `tmp=55`, `logs=2560`, `data=72`, 합계 `2687`로 기록했다.
- [x] `data/` 전체 ignore와 tracked 파일 제거는 seed/canonical 데이터가 섞여 있어 후속 분류 뒤 진행하기로 남겼다.

### P0 2차 — tracked runtime 파일 분류

- [x] `logs/`, `tmp/`, `data/`의 tracked 파일을 경로·확장자 기준으로 분류했다.
- [x] `logs/`는 tracked `2560`개 중 루트 파일 `2384`개, bars cache `176`개로 분류했다.
- [x] `tmp/`는 tracked `55`개 중 Python 임시 스크립트 `40`개, 결과·백업·패치 파일 `15`개로 분류했다.
- [x] `data/`는 tracked `72`개 중 `instrument_master=42`, `observations=6`, 루트 JSON `24`개로 분류했다.
- [x] `logs/`와 `tmp/`는 전체 추적 제외 후보, `data/`는 하위 경로별 분류 대상으로 판정했다.
- [x] 분류 결과와 Codex 추천안을 [`runtime_write_path_inventory.md`](../30_work_log/runtime_write_path_inventory.md)에 기록했다.

### P0 3차 — tracked runtime 참조 감사

- [x] 코드·문서·테스트에서 `logs/`, `tmp/`, `data/` 경로 문자열 참조를 집계했다.
- [x] 경로 문자열 참조 라인은 `logs=864`, `tmp=103`, `data=307`로 기록했다.
- [x] 정확 참조된 tracked runtime 파일은 `182`개, 정확 참조 라인은 `507`개로 기록했다.
- [x] 정확 참조된 tracked 파일은 `logs=166`, `tmp=1`, `data=15`로 분류했다.
- [x] 즉시 전체 `git rm --cached -r logs tmp data`는 금지하고, `tmp/`부터 작은 PR로 정리하는 추천안을 남겼다.
- [x] 감사 결과는 [`runtime_write_path_reference_audit.md`](../30_work_log/runtime_write_path_reference_audit.md)에 기록했다.

### P0 4차 — `tmp/` tracked 파일 추적 제외

- [x] `tmp/` tracked 파일 `55`개를 Git 추적에서 제거했다.
- [x] `tmp/` 정확 참조 파일 `1`개와 참조 라인 `3`개를 문서 링크에서 역사적 파일명 코드 텍스트로 전환했다.
- [x] `tmp/measure_dschat_latency.py`는 `.env` 기반 외부 API 측정 스크립트라 정식 `scripts/` 경로로 승격하지 않았다.
- [x] `runtime_tracked_file_count`는 `2687`에서 `2632`로 감소했다.
- [x] `tmp_tracked_count`는 `55`에서 `0`으로 감소했다.
- [x] 처리 기록은 [`runtime_write_path_inventory.md`](../30_work_log/runtime_write_path_inventory.md)와 [`runtime_write_path_reference_audit.md`](../30_work_log/runtime_write_path_reference_audit.md)에 남겼다.

### P0 5차 — `logs/` 링크 정책 결정

- [x] `logs/` tracked 파일 `2560`개와 정확 참조 파일 `166`개를 재확인했다.
- [x] `logs/` 정확 참조 라인은 `413`개로 기록했다.
- [x] 정확 참조 파일 확장자 분포는 `.json=95`, `.log=68`, `.jsonl=2`, `.txt=1`로 기록했다.
- [x] 대표 산출물 대량 보존보다 Markdown 링크를 코드 텍스트로 전환하는 정책을 우선하기로 결정했다.
- [x] 정책 기준은 [`runtime_artifact_policy.md`](../20_harness_engineering/runtime_artifact_policy.md)에 기록했다.

### P0 6차 — `docs/03_execution_order` `logs/` Markdown 링크 전환

- [x] 저위험 후보인 `docs/30_work_log`와 `docs/99_meta_handover`에는 전환 대상 Markdown 링크가 `0`개임을 확인했다.
- [x] 전체 문서의 `logs/` Markdown 링크 `28`개 중 `20`개를 코드 텍스트로 전환했다.
- [x] `docs/03_execution_order`의 `logs/` Markdown 링크 `19`개를 전환했다.
- [x] `docs/20_harness_engineering/runtime_artifact_policy.md`의 예시 링크 `1`개를 전환했다.
- [x] 남은 `logs/` Markdown 링크는 `8`개다.
- [x] 처리 기록은 [`runtime_write_path_reference_audit.md`](../30_work_log/runtime_write_path_reference_audit.md)에 남겼다.

### P0 7차 — 남은 `logs/` Markdown 링크 전환

- [x] 남은 `logs/` Markdown 링크 `8`개를 모두 코드 텍스트로 전환했다.
- [x] 전환 대상 파일은 `6`개였다.
- [x] 경로별 전환 수는 `docs/04_broker_kis=2`, `docs/05_reconciliation_snapshot=1`, `docs/06_data_sources_news=2`, `docs/07_scheduler_ops=1`, `docs/10_signal_research_sppv=2`다.
- [x] 전환 후 전체 문서의 `logs/` Markdown 링크는 `0`개다.
- [x] 처리 기록은 [`runtime_write_path_reference_audit.md`](../30_work_log/runtime_write_path_reference_audit.md)에 남겼다.

### P0 8차 — `logs/` 추적 제외 전 최종 참조 재감사

- [x] `logs/` tracked 파일 `2560`개를 재확인했다.
- [x] 전체 문서의 `logs/` Markdown 링크가 `0`개임을 확인했다.
- [x] 정확 참조된 `logs/` tracked 파일은 `166`개, 정확 참조 라인은 `413`개로 기록했다.
- [x] 정확 참조는 코드 텍스트 또는 일반 텍스트로 남아 있으며, Markdown 링크 검증 대상이 아님을 기록했다.
- [x] runtime tracked 파일 총합은 `2632`개이며, 구성은 `logs=2560`, `tmp=0`, `data=72`로 기록했다.
- [x] 처리 기록은 [`runtime_write_path_reference_audit.md`](../30_work_log/runtime_write_path_reference_audit.md)에 남겼다.

### P0 9차 — `logs/` tracked 파일 추적 제외

- [x] `logs/` tracked 파일 `2560`개를 Git 추적에서 제거했다.
- [x] 작업트리의 `logs/` 실제 파일 `2617`개는 보존했다.
- [x] `logs_tracked_count`는 `2560`에서 `0`으로 감소했다.
- [x] `runtime_tracked_file_count`는 `2632`에서 `72`로 감소했다.
- [x] 남은 runtime tracked 파일은 `data=72`개로 기록했다.
- [x] 전체 문서의 `logs/` Markdown 링크는 `0`개로 유지됨을 확인했다.
- [x] 처리 기록은 [`runtime_write_path_reference_audit.md`](../30_work_log/runtime_write_path_reference_audit.md)에 남겼다.

### P0 10차 — `data/` runtime/canonical 분리 검토

- [x] 남은 runtime tracked 파일이 `data=72`개임을 재확인했다.
- [x] 경로별 구성은 `data/instrument_master=42`, `data/observations=6`, `data/` 루트 JSON `24`개로 기록했다.
- [x] 정확 참조된 tracked `data/` 파일은 `15`개, 정확 참조 라인은 `107`개로 기록했다.
- [x] `data/instrument_master/archive/` `33`개는 정확 참조가 `0`개라 다음 추적 제외 1순위로 판정했다.
- [x] `data/signal_feature_snapshot_input.json`은 스케줄러와 테스트 기본값이 직접 참조하므로 이번 범위에서 제거하지 않기로 했다.
- [x] 상세 판정은 [`data_runtime_canonical_split_review.md`](../30_work_log/data_runtime_canonical_split_review.md)에 남겼다.

### P0 11차 — `data/instrument_master/archive/` tracked 파일 추적 제외

- [x] `data/instrument_master/archive/` tracked 파일 `33`개를 Git 추적에서 제거했다.
- [x] 작업트리의 archive 실제 파일 `34`개는 보존했다.
- [x] `data/instrument_master/archive/` 정확 참조 파일은 `0`개로 재확인했다.
- [x] `.gitignore`에 `data/instrument_master/archive/`를 추가했다.
- [x] `runtime_tracked_file_count`는 `72`에서 `39`로 감소했다.
- [x] 처리 기록은 [`data_runtime_canonical_split_review.md`](../30_work_log/data_runtime_canonical_split_review.md)와 [`runtime_write_path_reference_audit.md`](../30_work_log/runtime_write_path_reference_audit.md)에 남겼다.

### P0 12차 — `data/observations/` Markdown 링크 전환

- [x] `data/observations/` tracked 파일 `6`개를 재확인했다.
- [x] 정확 참조된 `data/observations/` tracked 파일은 `6`개, 정확 참조 라인은 `13`개로 기록했다.
- [x] 전체 문서의 `data/observations/` Markdown 링크 `13`개를 코드 텍스트로 전환했다.
- [x] 전환 대상 문서는 `7`개였다.
- [x] 전환 후 전체 문서의 `data/observations/` Markdown 링크는 `0`개다.
- [x] 처리 기록은 [`data_runtime_canonical_split_review.md`](../30_work_log/data_runtime_canonical_split_review.md)와 [`runtime_write_path_reference_audit.md`](../30_work_log/runtime_write_path_reference_audit.md)에 남겼다.

### P0 13차 — `data/observations/` tracked 파일 추적 제외

- [x] `data/observations/` tracked 파일 `6`개를 Git 추적에서 제거했다.
- [x] 작업트리의 `data/observations/` 실제 파일 `6`개는 보존했다.
- [x] 전체 문서의 `data/observations/` Markdown 링크는 `0`개로 유지됐다.
- [x] `.gitignore`에 `data/observations/`를 추가했다.
- [x] `runtime_tracked_file_count`는 `39`에서 `33`으로 감소했다.
- [x] 처리 기록은 [`data_runtime_canonical_split_review.md`](../30_work_log/data_runtime_canonical_split_review.md)와 [`runtime_write_path_reference_audit.md`](../30_work_log/runtime_write_path_reference_audit.md)에 남겼다.

### P0 14차 — root JSON 기본 입력·분석 산출물 분리

- [x] top-level root JSON tracked 파일 `24`개를 재확인했다.
- [x] 정확 참조된 top-level root JSON 파일은 `3`개, 정확 참조 라인은 `46`개로 기록했다.
- [x] 정확 참조 없는 top-level root JSON 파일은 `21`개로 기록했다.
- [x] 분류 결과는 `signal_feature_default=1`, `signal_feature_historical=16`, `trigger_proxy_artifact=5`, `ar_fdc_artifact=2`로 기록했다.
- [x] top-level root JSON Markdown 링크는 `3`개이며 모두 `data/ar_fdc_*.json`을 가리킨다고 기록했다.
- [x] root JSON 파일은 이번 단계에서 제거하지 않고 wildcard 사용 여부와 Markdown 링크 정리를 다음 단계로 분리했다.

### P0 15차 — root JSON wildcard 사용 감사

- [x] 정확 참조가 없는 top-level root JSON 후보 `21`개를 재확인했다.
- [x] 후보 구성은 `signal_feature_historical=16`, `trigger_proxy_artifact=5`로 기록했다.
- [x] 코드·테스트·스크립트·CI의 root JSON wildcard 패턴 사용은 `0`건으로 기록했다.
- [x] 후보 파일 basename 부분 참조는 `0`건으로 기록했다.
- [x] 문서 예시와 과거 산출물명 참조는 제거 차단 근거로 보지 않는다고 기록했다.
- [x] root JSON 파일은 이번 단계에서 제거하지 않고, 다음 별도 PR에서 후보 `21`개를 추적 제외하기로 기록했다.

### P0 16차 — root JSON 후보 tracked 파일 추적 제외

- [x] 정확 참조와 wildcard 사용이 없는 root JSON 후보 `21`개를 Git 추적에서 제거했다.
- [x] 후보 구성은 `signal_feature_historical=16`, `trigger_proxy_artifact=5`로 기록했다.
- [x] 작업트리의 후보 실제 파일 `21`개는 보존했다.
- [x] `.gitignore`에 `data/signal_feature_snapshot_input_*.json`과 `data/trigger_proxy_attribution_*.json`를 추가했다.
- [x] 남은 top-level root JSON tracked 파일은 `3`개로 감소했다.
- [x] `runtime_tracked_file_count`는 `33`에서 `12`로 감소했다.
- [x] 처리 기록은 [`data_runtime_canonical_split_review.md`](../30_work_log/data_runtime_canonical_split_review.md)와 [`runtime_write_path_reference_audit.md`](../30_work_log/runtime_write_path_reference_audit.md)에 남겼다.

### P0 17차 — `data/ar_fdc_*.json` Markdown 링크 전환

- [x] `data/ar_fdc_*.json` tracked 파일 `2`개를 재확인했다.
- [x] 전환 전 전체 문서의 `data/ar_fdc_*.json` Markdown 링크 `3`개를 확인했다.
- [x] 전환 대상 문서 `2`개의 Markdown 링크 `3`개를 코드 텍스트로 전환했다.
- [x] 전환 후 전체 문서의 `data/ar_fdc_*.json` Markdown 링크는 `0`개로 감소했다.
- [x] 정확 참조된 `data/ar_fdc_*.json` tracked 파일은 `2`개, 정확 참조 라인은 `19`개로 기록했다.
- [x] 이번 단계에서는 `data/ar_fdc_*.json` tracked 파일 `2`개를 제거하지 않았다.
- [x] 처리 기록은 [`data_runtime_canonical_split_review.md`](../30_work_log/data_runtime_canonical_split_review.md)와 [`runtime_write_path_reference_audit.md`](../30_work_log/runtime_write_path_reference_audit.md)에 남겼다.

### P0 18차 — `data/ar_fdc_*.json` tracked 파일 추적 제외

- [x] `data/ar_fdc_*.json` tracked 파일 `2`개를 재확인했다.
- [x] `scripts/ar_fdc_output_measurement.py`가 `data/ar_fdc_prompts_{symbol}.json`을 생성한다고 기록했다.
- [x] `scripts/ar_fdc_provider_validation.py`가 `data/ar_fdc_prompts_030200.json`을 입력으로 읽고 `data/ar_fdc_provider_validation_030200.json`을 생성한다고 기록했다.
- [x] 전체 문서의 `data/ar_fdc_*.json` Markdown 링크는 `0`개로 유지했다.
- [x] `git rm --cached`로 `data/ar_fdc_*.json` tracked 파일 `2`개를 Git 추적에서 제거했다.
- [x] `.gitignore`에 `data/ar_fdc_*.json`을 추가했다.
- [x] `runtime_tracked_file_count`는 `12`에서 `10`으로 감소했다.
- [x] 처리 기록은 [`data_runtime_canonical_split_review.md`](../30_work_log/data_runtime_canonical_split_review.md)와 [`runtime_write_path_reference_audit.md`](../30_work_log/runtime_write_path_reference_audit.md)에 남겼다.

### P0 19차 — 남은 `data/` canonical 입력 허용 목록 문서화

- [x] 남은 `data/` tracked 파일 `10`개를 재확인했다.
- [x] 확장자 분포 `csv=7`, `json=3`을 기록했다.
- [x] `data/` runtime 산출물 tracked 파일은 `0`개로 분류했다.
- [x] 허용 목록 작성 전 full path 정확 참조가 `0`개였던 constituent CSV `3`개는 manifest `csv_path`와 문서 basename 참조를 근거로 source package 구성 파일로 유지했다.
- [x] owner 분류 `운영 데이터 관리자=5`, `스케줄러 운영자=3`, `Harness 문서 관리자=2`를 기록했다.
- [x] 허용 목록과 갱신 절차는 [`canonical_data_contract.md`](../20_harness_engineering/canonical_data_contract.md)에 기록했다.
- [x] 처리 기록은 [`data_runtime_canonical_split_review.md`](../30_work_log/data_runtime_canonical_split_review.md)와 [`runtime_write_path_reference_audit.md`](../30_work_log/runtime_write_path_reference_audit.md)에 남겼다.

## 작업 이력

| 일자 | 작업자 | 항목 | 변경 파일 수 | 검증 명령 | 주요 출력 지표 | 후속 조치 |
| --- | --- | --- | ---: | --- | --- | --- |
| 2026-07-29 | Codex | 권고사항 이후 후속 작업 계획 문서 생성 | 1 | 예정 | 예정 | `accept docs` 실행 |
| 2026-07-29 | Codex | P0 1차 — 배포 파괴 명령 차단과 runtime ignore 기준 | 4 | `bash scripts/harness/run.sh accept ci`; `bash scripts/harness/run.sh accept docs` | `destructive_deploy_clean_command_count=0`, `runtime_tracked_file_count=2687` | tracked runtime 파일 목적별 분류 |
| 2026-07-29 | Codex | P0 2차 — tracked runtime 파일 분류 | 2 | `bash scripts/harness/run.sh accept docs` | `runtime_tracked_file_count=2687`, `logs=2560`, `tmp=55`, `data=72` | `logs/`, `tmp/` 추적 제외 PR 범위 결정 |
| 2026-07-29 | Codex | P0 3차 — tracked runtime 참조 감사 | 3 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `exact_referenced_tracked_runtime_file_count=182`, `exact_reference_line_count=507` | `tmp/` 정리 PR부터 진행 |
| 2026-07-29 | Codex | 작업기록 문서 라우팅 정리 | 3 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `moved_work_log_document_count=2`, `updated_plan_link_count=4` | P0 `tmp/` 정리 PR |
| 2026-07-29 | Codex | P0 4차 — `tmp/` tracked 파일 추적 제외 | 60 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `tmp_tracked_count=0`, `runtime_tracked_file_count=2632` | `logs/` 링크 정책 결정 |
| 2026-07-29 | Codex | P0 5차 — `logs/` 링크 정책 결정 | 3 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `logs_exact_referenced_file_count=166`, `logs_exact_reference_line_count=413` | `logs/` Markdown 링크 전환 PR |
| 2026-07-29 | Codex | P0 6차 — `docs/03_execution_order` `logs/` Markdown 링크 전환 | 7 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `converted_markdown_logs_link_count=20`, `remaining_markdown_logs_link_count=8` | 나머지 8개 링크 전환 |
| 2026-07-29 | Codex | P0 7차 — 남은 `logs/` Markdown 링크 전환 | 8 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `converted_markdown_logs_link_count=8`, `remaining_markdown_logs_link_count=0` | `logs/` 추적 제외 준비 |
| 2026-07-29 | Codex | P0 8차 — `logs/` 추적 제외 전 최종 참조 재감사 | 2 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `markdown_logs_link_count=0`, `logs_exact_reference_line_count=413` | `logs/` 추적 제외 PR |
| 2026-07-29 | Codex | P0 9차 — `logs/` tracked 파일 추적 제외 | 2562 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `logs_tracked_count=0`, `runtime_tracked_file_count=72` | `data/` seed/canonical 분리 |
| 2026-07-29 | Codex | P0 10차 — `data/` runtime/canonical 분리 검토 | 3 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `data_tracked_count=72`, `data_exact_referenced_file_count=15`, `data_archive_exact_reference_count=0` | `data/instrument_master/archive/` 추적 제외 |
| 2026-07-29 | Codex | P0 11차 — `data/instrument_master/archive/` tracked 파일 추적 제외 | 37 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `archive_tracked_count=0`, `archive_files_on_disk_count=34`, `runtime_tracked_file_count=39` | `data/observations/` 링크 보존 정책 결정 |
| 2026-07-29 | Codex | P0 12차 — `data/observations/` Markdown 링크 전환 | 10 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `converted_observations_markdown_link_count=13`, `remaining_observations_markdown_link_count=0`, `runtime_tracked_file_count=39` | `data/observations/` tracked 파일 추적 제외 |
| 2026-07-29 | Codex | P0 13차 — `data/observations/` tracked 파일 추적 제외 | 10 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `observations_tracked_count=0`, `observations_files_on_disk_count=6`, `runtime_tracked_file_count=33` | root JSON 기본 입력·분석 산출물 분리 |
| 2026-07-29 | Codex | P0 14차 — root JSON 기본 입력·분석 산출물 분리 | 3 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `top_level_root_json_count=24`, `top_level_root_json_exact_referenced_file_count=3`, `top_level_root_json_zero_ref_count=21` | root JSON wildcard 사용 여부 감사 |
| 2026-07-29 | Codex | P0 15차 — root JSON wildcard 사용 감사 | 3 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `root_json_zero_ref_candidate_count=21`, `code_wildcard_pattern_line_count=0`, `candidate_basename_partial_ref_count=0` | root JSON 후보 `21`개 추적 제외 |
| 2026-07-29 | Codex | P0 16차 — root JSON 후보 tracked 파일 추적 제외 | 25 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `root_json_candidates_tracked_count=0`, `root_json_candidates_on_disk_count=21`, `runtime_tracked_file_count=12` | `data/ar_fdc_*.json` Markdown 링크 정리 |
| 2026-07-29 | Codex | P0 17차 — `data/ar_fdc_*.json` Markdown 링크 전환 | 5 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `converted_ar_fdc_markdown_link_count=3`, `remaining_ar_fdc_markdown_link_count=0`, `ar_fdc_exact_reference_line_count=19`, `runtime_tracked_file_count=12` | `data/ar_fdc_*.json` 생성 경로 감사 |
| 2026-07-29 | Codex | P0 18차 — `data/ar_fdc_*.json` tracked 파일 추적 제외 | 5 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `ar_fdc_tracked_count=0`, `ar_fdc_files_on_disk_count=2`, `runtime_tracked_file_count=10` | 남은 `data/` canonical 입력 `10`개 owner·갱신 절차 문서화 |
| 2026-07-29 | Codex | P0 19차 — 남은 `data/` canonical 입력 허용 목록 문서화 | 5 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `data_tracked_allowlist_count=10`, `runtime_artifact_tracked_count=0`, `canonical_data_owner_documented_count=10` | P0 닫기 후보, 다음 P1 장 시간 배포 가드 |
| 2026-07-29 | Codex | P1 1차 — 수동 재배포 입력과 최신 SHA 고정 | 4 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `deploy_manual_dispatch_input_count=2`, `deploy_manual_dispatch_requested_count=0`, `ci_contract_failed_count=0`, `deploy_workflow_count=1` | 장 시간 가드와 skip/override 지표 추가 |
| 2026-07-29 | Codex | P1 2차 — 장 시간 배포 가드와 override 지표 | 4 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `deploy_market_hours_guard_count=1`, `deploy_market_hours_skip_metric_count=1`, `deploy_market_hours_override_metric_count=1`, `deploy_job_depends_on_market_guard_count=1` | P1 닫기 후보, 다음 P2 quick/full 계층 정리 |
| 2026-07-29 | Codex | P2 1차 — quick/safe 단계 수와 괴리 계측 | 3 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `quick_step_count=8`, `ci_safe_step_count=8`, `local_ci_command_gap_count=6`, `quick_only_command_count=0` | `check quick` 확장 또는 `check full` 신설 판단 |
| 2026-07-29 | Codex | P2 2차 — `check full` 신설과 로컬/CI 정렬 | 5 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `full_step_count=14`, `full_ci_command_gap_count=0`, `full_only_command_count=0`, `local_ci_command_gap_count=6` | P2 닫기 후보, 다음 P3 dependency lock 계약 강화 |
| 2026-07-29 | Codex | P3 1차 — CI Python lock constraint 강제 | 4 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `pip_install_command_count=2`, `pip_install_without_constraints_count=0`, `ci_contract_failed_count=0` | Node/PostgreSQL 버전 고정 문서와 CI 일치 여부 확인 |
| 2026-07-29 | Codex | P3 2차 — Node/PostgreSQL 버전 문서와 CI 일치 확인 | 2 | `bash scripts/harness/run.sh accept env`; `bash scripts/harness/run.sh accept docs` | `runtime_version_mismatch_count=0`, `required_file_missing_count=0`, `semantic_check_failed_count=0` | P3 닫기 후보, 다음 P4 문서 자기검증 |
| 2026-07-29 | Codex | P4 1차 — 문서 속 `run.sh` 명령 실존 검사 추가 | 3 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `documented_run_sh_command_missing_count=0`, `semantic_check_failed_count=0`, `ci_contract_failed_count=0` | `run.sh` selector 파싱과 `CLAUDE.md` 중복 정리 |
| 2026-07-29 | Codex | P4 2차 — `run.sh` usage와 dispatch selector 정합성 검사 추가 | 3 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `run_sh_usage_dispatch_mismatch_count=0`, `documented_run_sh_command_missing_count=0`, `ci_contract_failed_count=0` | `CLAUDE.md` 중복 정리와 workspace guide 보강 |
| 2026-07-29 | Codex | P4 3차 — `.claude/worktrees` 경고와 검색 제외 지침 추가 | 2 | `bash scripts/harness/run.sh accept docs` | `documented_run_sh_command_missing_count=0`, `run_sh_usage_dispatch_mismatch_count=0`, `semantic_check_failed_count=0` | `CLAUDE.md` 중복 정리와 README 경로 재확인 |
| 2026-07-29 | Codex | P4 4차 — `CLAUDE.md` 링크 중심 정리와 README 경로 재확인 | 2 | `bash scripts/harness/run.sh accept docs` | `documented_run_sh_command_missing_count=0`, `run_sh_usage_dispatch_mismatch_count=0`, `semantic_check_failed_count=0` | P4 완료, 다음 우선순위 정의 필요 |
| 2026-07-29 | Codex | PR46 머지 후 `main` 동기화와 브랜치 정리 | 1 | `git reset --hard origin/main`; `git push origin --delete codex/add-check-full-profile` | `ahead_count=0`, `behind_count=0`, `remote_branch_count=0`, `local_branch_count=0` | 참고문서 기준 미완료 우선순위 없음 |
| 2026-07-29 | Codex | 장중 sync/activate 분리 설계 문서화 | 3 | `bash scripts/harness/run.sh accept docs` | `required_file_missing_count=0`, `documented_run_sh_command_missing_count=0`, `semantic_check_failed_count=0` | 후속 구현 작업 시 `harness.yml` 변경안으로 사용 |
| 2026-07-30 | Codex | P5 1차 — 장중 배포 분류 계약 출력과 CI 검사 추가 | 5 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `deploy_activate_required_output_count=1`, `deploy_sync_only_candidate_count_output_count=1`, `deploy_sync_only_allowlist_count_output_count=1`, `deploy_sync_only_blocked_count_output_count=1`, `deploy_sync_only_allowlist_defined_count=1`, `deploy_runtime_affecting_path_rule_count=1`, `ci_contract_failed_count=0` | 다음은 실제 `sync_source` / `activate_runtime` job 분리 |
| 2026-07-30 | Codex | P5 2차 — `sync_source` / `activate_runtime` job 분리와 장중 sync-only 조건 반영 | 5 | `bash scripts/harness/run.sh accept docs`; `bash scripts/harness/run.sh accept ci` | `deploy_sync_job_present_count=1`, `deploy_activate_job_present_count=1`, `deploy_activate_guard_present_count=1`, `deploy_sync_only_run_metric_count=1`, `deploy_activate_run_metric_count=1`, `deploy_activate_skipped_by_market_hours_metric_count=1`, `ci_contract_failed_count=0` | 다음은 수동 재배포 dispatch 문서 예시와 운영 runbook 정리 |
| 2026-07-30 | Codex | P5 3차 — GitHub Actions 실배포 run 검증 | 2 | `gh pr checks 47 --watch`; `gh run view 30503269894`; `gh run view 30503269269` | `pr_safe_harness_success_count=1`, `push_main_run_cancelled_count=1`, `dispatch_run_success_count=1`, `dispatch_sync_run_success_count=1`, `dispatch_activate_run_success_count=1`, `dispatch_market_override_count=1` | 장중 sync-only 전용 검증용 allowlist-only 샘플 변경 또는 운영 runbook 정리 |
| 2026-07-30 | Codex | P5 4차 — 장중 sync-only 자동 경로 실run 검증 | 2 | `bash scripts/harness/run.sh py-compile scripts/check_index_membership_staleness.py`; `gh pr checks 49 --watch`; `gh run view 30503894901` | `sync_only_pr_safe_harness_success_count=1`, `sync_only_push_run_success_count=1`, `sync_only_market_guard_success_count=1`, `sync_only_sync_source_success_count=1`, `sync_only_activate_skipped_count=1`, `sync_only_dispatch_run_count=0` | 다음은 장종료 activate 자연 경로 검증 또는 runbook 보강 |

## 갱신 규칙

- 새 작업을 시작하면 해당 체크박스를 `[~]`로 바꾸고 작업 이력에 행을 추가한다.
- 작업 완료 시 체크박스를 `[x]`로 바꾸고 검증 명령과 실제 출력 지표를 기록한다.
- 사용자 결정이 필요한 항목은 `[!]`로 표시하고 필요한 선택지를 작업 이력에 남긴다.
- 완료된 묶음 작업은 [완료된 작업](#완료된-작업)에 별도 Chapter로 추가한다.
- 단순히 성공 또는 정상이라고 쓰지 않고 카운트, exit code, skip 수, 실패 수를 기록한다.
