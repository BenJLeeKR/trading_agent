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
- [~] 런타임 산출물과 canonical 입력 데이터의 기준을 문서화한다.
- [x] `logs/`, `tmp/`는 원칙적으로 Git 추적 대상에서 제외한다.
- [ ] `data/`는 전체 제외 여부를 바로 결정하지 않고 `data/runtime/`, `data/cache/`, `data/local/` 같은 mutable 하위 경로 분리를 먼저 검토한다.
- [~] 필요한 seed, example, fixture 파일은 `tests/fixtures/`, `docs/`, 또는 `*.example` 경로로 이동할지 결정한다. `logs/`는 대량 보존보다 코드 텍스트 전환 우선 정책으로 결정했다.
- [x] `.gitignore`에 runtime write path 패턴을 추가한다.
- [~] 기존 tracked 런타임 파일은 `git rm --cached` 또는 경로 이동으로 정리한다. `tmp/` tracked 파일 `55`개는 제거 완료했고, `logs/`, `data/`는 남아 있다.
- [x] 배포 workflow에 `git clean -fdx` 또는 동등한 파괴적 clean 명령이 들어가지 않도록 `accept ci` 검사에 추가한다.
- [x] `accept ci`에 tracked runtime write path 카운트 검사를 추가한다.

완료 기준:

- `runtime_tracked_file_count`가 합의된 허용 목록을 제외하고 `0`이다.
- `destructive_deploy_clean_command_count`가 `0`이다.
- 배포 job이 untracked/ignored runtime 파일을 삭제하지 않는다는 정적 검사 결과가 보고된다.

분류 상세는 [`runtime_write_path_inventory.md`](../30_work_log/runtime_write_path_inventory.md)를 따른다.

### P1 — 장 시간 배포 가드와 수동 재배포 진입점

목표: 정규장 중 자동 배포를 기본 차단하되, 사용자 명시 승인이 있는 경우에만 배포할 수 있게 한다. 장중 차단으로 폐기된 배포는 장종료 후 최신 `origin/main` 기준으로 새로 재배포한다.

- [ ] `workflow_dispatch`에 `deploy_main` 입력을 추가한다.
- [ ] `workflow_dispatch`에 `allow_market_hours_deploy` 입력을 추가한다.
- [ ] 수동 배포는 항상 최신 `origin/main` SHA를 대상으로 실행한다.
- [ ] 폐기된 과거 workflow run을 장종료 후 자동 재개하지 않는다는 정책을 문서화한다.
- [ ] KST 기준 정규장 시간대를 계산하는 guard를 deploy job 앞에 추가한다.
- [ ] 장중 + 승인 없음이면 배포를 중단하고 `deploy_skipped_by_market_hours_count=1`을 출력한다.
- [ ] 장중 + 승인 있음이면 `allow_market_hours_deploy=true` 입력과 함께 `deploy_market_hours_override_count=1`을 출력한다.
- [ ] 장종료 후 수동 재배포는 `deploy_manual_dispatch_count=1`과 `deploy_target_sha=<sha>`를 출력한다.
- [ ] `accept ci`가 수동 재배포 입력과 장 시간 guard 지표를 검사하도록 확장한다.

완료 기준:

- 자동 `push main` 배포와 수동 `workflow_dispatch` 배포가 모두 `Safe harness contracts` 이후에만 실행된다.
- 장중 무승인 배포 시도는 재기동 없이 skip 지표를 남긴다.
- 장종료 후 사용자가 AI에게 재배포를 요청하면 공식 dispatch 진입점으로 새 run을 실행할 수 있다.

### P2 — `check quick`과 CI safe 범위 불일치 해소

목표: 로컬의 빠른 검증과 CI 필수 검증이 과도하게 어긋나지 않게 한다.

- [ ] 현재 `check quick` 단계 수와 CI `safe` job 단계 수를 카운트한다.
- [ ] 부하가 작은 필수 계약을 `check quick`에 포함할지 판단한다.
- [ ] 부하가 큰 항목은 `check full`을 신설해 CI safe와 등가로 둘지 판단한다.
- [ ] `AGENTS.md`의 커밋 전 권장 명령이 실제 정책과 일치하도록 수정한다.
- [ ] `scripts/harness/README.md`에 `check quick`과 `check full`의 역할 차이를 명시한다.
- [ ] `accept ci`에 required harness command와 로컬 명령 간 괴리 카운트를 추가한다.

완료 기준:

- `quick_step_count`, `full_step_count`, `ci_safe_step_count`가 보고된다.
- 로컬에서 요구하는 명령과 CI required check 사이의 의도하지 않은 누락 수가 `0`이다.

### P3 — CI 환경 재현성 계약 강화

목표: CI가 로컬/운영과 같은 dependency lock 계약을 사용하게 한다.

- [ ] `harness.yml`의 `pip install` 경로를 전수 확인한다.
- [ ] 가능한 모든 `pip install`에 `--constraint requirements.lock`을 적용한다.
- [ ] lock 적용이 불가능한 설치 경로는 명시 예외로 문서화한다.
- [ ] `accept ci`가 workflow의 Python dependency 설치에서 `requirements.lock` constraint 사용 여부를 검사하도록 확장한다.
- [ ] Node.js와 PostgreSQL 버전 고정 문서가 실제 CI 설정과 일치하는지 확인한다.

완료 기준:

- `pip_install_without_constraints_count`가 `0`이거나, 예외 목록과 카운트가 함께 보고된다.
- CI에서 사용하는 Python/Node/PostgreSQL 버전 기준이 문서와 일치한다.

### P4 — 문서 자기검증과 중복 정리

목표: 문서가 하네스 명령과 실제 파일 경로를 잘못 안내하지 않게 한다.

- [ ] `CLAUDE.md`의 명령 목록 중복을 줄이고 `AGENTS.md`, `scripts/harness/README.md` 링크 중심으로 정리한다.
- [ ] `accept docs`가 문서 속 `bash scripts/harness/run.sh <command>` 문자열의 실존 여부를 검사하도록 확장한다.
- [ ] `run.sh`의 command selector 목록을 파싱해 문서 내 명령과 대조한다.
- [ ] `docs/99_meta_handover/agent_workspace_guide.md`에 `.claude/worktrees/` 그림자 사본 경고를 추가한다.
- [ ] 코드 검색 시 `.claude/` 경로를 제외하라는 지침을 추가한다.
- [ ] README의 `.nvmrc`, `.npm-version` 표기가 실제 `admin_ui/` 하위 경로를 가리키는지 확인한다.

완료 기준:

- `documented_run_sh_command_missing_count`가 `0`이다.
- `claude_command_duplication_count`가 감소하거나, 남은 중복이 의도된 예외로 문서화된다.

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

## 갱신 규칙

- 새 작업을 시작하면 해당 체크박스를 `[~]`로 바꾸고 작업 이력에 행을 추가한다.
- 작업 완료 시 체크박스를 `[x]`로 바꾸고 검증 명령과 실제 출력 지표를 기록한다.
- 사용자 결정이 필요한 항목은 `[!]`로 표시하고 필요한 선택지를 작업 이력에 남긴다.
- 완료된 묶음 작업은 [완료된 작업](#완료된-작업)에 별도 Chapter로 추가한다.
- 단순히 성공 또는 정상이라고 쓰지 않고 카운트, exit code, skip 수, 실패 수를 기록한다.
