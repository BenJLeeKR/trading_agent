# Harness Runner

## 문서 목적

이 문서는 AI 에이전트와 사람이 같은 방식으로 검증 명령을 실행하도록 [`run.sh`](./run.sh)의 표준 진입점, 부하 제한, 출력 지표 해석 기준을 정리한다.

하네스의 상위 작업 규칙은 루트 [`AGENTS.md`](../../AGENTS.md)를 따른다. Make target은 [`Makefile`](../../Makefile)의 convenience alias이며, 정답 판정의 기준은 `run.sh` 출력 지표다.

## 기본 실행 원칙

- 프로젝트 루트는 `run.sh` 위치 기준으로 계산한다.
- 셸은 `bash`만 사용한다.
- Python 실행은 `python3`만 사용한다.
- `.env` 파일은 직접 수정하지 않고, 출력에도 비밀값을 노출하지 않는다.
- 기본 timeout은 `HARNESS_SAFE_TIMEOUT_SECONDS`이며 기본값은 `90`초다.
- 무거운 검증 timeout은 `HARNESS_HEAVY_TIMEOUT_SECONDS`이며 기본값은 `900`초다.

## CI 공동 사용 원칙

GitHub Actions도 사람과 AI가 쓰는 동일한 하네스를 사용한다. CI workflow는 `pytest`, `ruff`, `npm`, `docker` 기반 검증 명령을 직접 정답 판정기로 삼지 않고, 준비 단계 이후 `bash scripts/harness/run.sh ...`만 호출한다.

- 기본 PR/push gate는 `.github/workflows/harness.yml`의 `safe` job이다.
- `safe` job은 `check quick`, `accept db-structure`, `accept architecture`, `accept style`, `accept no-bypass`, `type-check backend`, `type-check frontend`, `security scan`을 실행한다.
- 운영 배포는 `.github/workflows/harness.yml`의 `deploy` job에서 `needs: safe` 성공 뒤에만 실행한다.
- 문서만 변경된 `main` push는 `changes` job에서 `deploy_required=0`으로 판정해 운영 재기동을 실행하지 않는다.
- 수동 재배포는 `workflow_dispatch`의 `deploy_main=true` 입력으로만 연다.
- 수동 재배포는 과거 workflow run을 재개하지 않고, 실행 시점의 최신 `origin/main` SHA를 다시 fetch한 뒤 그 SHA를 배포한다.
- `market_hours_guard` job은 `Asia/Seoul` 기준 평일 `09:00-15:30 KST`를 장중으로 계산한다.
- 장중에는 자동 배포를 막고 `deploy_skipped_by_market_hours_count=1`을 출력한다.
- 장중 수동 재배포는 `allow_market_hours_deploy=true`일 때만 허용하고 `deploy_market_hours_override_count=1`을 출력한다.
- 거래소 휴장일 캘린더는 아직 연동하지 않았으므로 1차 가드는 평일 시간대 기준이다.
- 배포 재기동 뒤에는 `nginx-proxy`를 reload해 Docker DNS가 새 frontend 컨테이너 IP를 다시 해석하게 한다.
- CI workflow 자체의 정합성 판정은 `accept ci`가 담당한다.
- GitHub ruleset `Require Harness on main`은 기본 브랜치에 `Safe harness contracts` 상태 검사를 필수 항목으로 요구한다.
- CI의 PostgreSQL 버전 판정은 `.postgres-version`과 같은 버전의 `trading_db` 컨테이너를 시작한 뒤 `accept env`가 확인한다.
- CI의 Node.js/npm 판정은 `.nvmrc`, `.npm-version`과 일치하는 pin 이미지 또는 setup-node 환경을 기준으로 확인한다.
- `HARNESS_ALLOW_HEAVY=1`이 필요한 L4/L5 검증은 기본 PR/push에서 실행하지 않고 `workflow_dispatch` 입력으로만 실행한다.

## 승인 없이 실행 가능한 명령

| 목적 | 표준 명령 | Make alias |
|------|-----------|------------|
| 하네스 사용법 | `bash scripts/harness/run.sh status` | `make harness-status` |
| 빠른 계층 검증 | `bash scripts/harness/run.sh check quick` | `make check-quick` |
| 변경 백엔드 파일 검증 | `bash scripts/harness/run.sh check changed` | `make check-changed` |
| 백엔드 타입 검사 | `bash scripts/harness/run.sh type-check backend` | `make type-check-backend` |
| Frontend 타입 검사 | `bash scripts/harness/run.sh type-check frontend` | `make type-check-frontend` |
| read-only 보안 검사 | `bash scripts/harness/run.sh security scan` | `make security-scan` |
| 환경 계약 | `bash scripts/harness/run.sh accept env` | `make accept-env` |
| 문서 계약 | `bash scripts/harness/run.sh accept docs` | `make accept-docs` |
| CI 계약 | `bash scripts/harness/run.sh accept ci` | `make accept-ci` |
| DB 저장소 구조 계약 | `bash scripts/harness/run.sh accept db-structure` | `make accept-db-structure` |
| 아키텍처 계층 구조 계약 | `bash scripts/harness/run.sh accept architecture` | `make accept-architecture` |
| 코드 스타일 baseline 계약 | `bash scripts/harness/run.sh accept style` | `make accept-style` |
| 우회 행동 검사 | `bash scripts/harness/run.sh accept no-bypass` | `make accept-no-bypass` |
| 단일 백엔드 파일 | `bash scripts/harness/run.sh accept backend-file <file>` | `make accept-backend-file FILE=<file>` |
| 백엔드 런타임 계약 | `bash scripts/harness/run.sh accept backend-runtime` | `make accept-backend-runtime` |
| Admin UI 계약 | `bash scripts/harness/run.sh accept frontend` | `make accept-admin-ui` |
| 운영 리포트 JSON 계약 | `bash scripts/harness/run.sh accept ops-report <summary_json>` | `make accept-ops-report SUMMARY_JSON=<summary_json>` |
| Python 컴파일 | `bash scripts/harness/run.sh py-compile <python_file>` | `make check-file FILE=<python_file>` |
| 단일 pytest selector | `bash scripts/harness/run.sh test-one <selector>` | `make test-one TEST=<selector>` |
| 단일 pytest 파일 | `bash scripts/harness/run.sh test-file <tests/path.py>` | `make test-file TEST=<tests/path.py>` |
| 경로별 ruff | `bash scripts/harness/run.sh lint-path <path>` | `make lint-path TARGET=<path>` |
| 단일 Admin UI 테스트 | `bash scripts/harness/run.sh admin-test-one <selector>` | `make admin-test-one TEST=<selector>` |

`docs-check`와 `env-check`는 각각 `accept docs`, `accept env`의 호환 alias다. 신규 문서와 보고에서는 `accept ...` 이름을 우선 사용한다.

## 검증 계층

| 계층 | 목적 | 기본 실행 조건 | 현재 진입점 |
|------|------|----------------|-------------|
| L0 | 문법·포맷 검사 | 승인 없이 실행 | `py-compile`, `git diff --check` |
| L1 | Lint | 승인 없이 실행 | `lint-path`, `make lint` |
| L2 | 타입 검사 | 승인 없이 실행, 도구 미설치·스크립트 누락은 카운트로 보고 | `type-check backend`, `type-check frontend` |
| L3 | 단위 테스트 | 단일 파일·단일 selector만 승인 없이 실행 | `test-one`, `test-file`, `admin-test-one` |
| L4 | 통합 테스트 | `HARNESS_ALLOW_HEAVY=1` 필요 | `full-test`, `docker-test` |
| L5 | E2E·smoke 테스트 | `HARNESS_ALLOW_HEAVY=1` 필요 | `smoke`, broker/KIS 연동 테스트 |
| L6 | 성능·보안 검사 | read-only secret scan은 승인 없이 실행, dependency audit·성능 검사는 별도 승인 필요 | `security scan` |

`check quick`은 커밋 전 기본 스냅샷용 계층 묶음이다. 현재 범위는 `accept docs`, `accept ci`, `accept no-bypass`, `accept env`, `accept backend-runtime`, `accept frontend`, `lint-path src/agent_trading`, `git diff --check`이며 전체 테스트, 전체 빌드, DB 연결, 외부 네트워크 호출을 실행하지 않는다.

현재 2026-07-29 기준 계측은 다음과 같다.

- `quick_step_count=8`
- `ci_safe_step_count=8`
- `local_ci_command_gap_count=6`
- `quick_only_command_count=0`

해석:

- raw 호출 수는 둘 다 `8`이지만, `safe` job은 `check quick` 외에 `accept db-structure`, `accept architecture`, `accept style`, `type-check backend`, `type-check frontend`, `security scan`을 추가로 강제한다.
- 즉, 현재 로컬 기본 스냅샷과 CI safe gate 사이에는 고유 명령 기준 `6`개의 차이가 있다.
- 이 차이를 줄일지, `check full` 같은 별도 로컬 계약으로 분리할지는 P2 후속 단계에서 결정한다.

`check changed`는 Git 변경 목록에서 `src/agent_trading/**/*.py` 파일만 골라 각 파일에 `accept backend-file`을 적용한다. 문서만 변경된 경우 `changed_backend_file_count=0`으로 보고하며 전체 테스트를 실행하지 않는다.

`type-check backend`는 `mypy` 또는 `pyright`가 설치된 경우에만 실행한다. 둘 다 없으면 `backend_type_tool_missing_count=1`, `backend_type_check_run=0`으로 보고한다. `type-check frontend`는 `admin_ui/package.json`의 `typecheck`, `type-check`, `check:types` script 중 하나가 있을 때만 실행한다. script가 없으면 `frontend_typecheck_script_missing_count=1`, `frontend_type_check_run=0`으로 보고한다.

`security scan`은 Git 변경 파일과 untracked 후보 파일을 대상으로 secret key/value 패턴을 read-only로 검사한다. `.env` 값은 읽거나 출력하지 않고, secret 후보가 있으면 값 대신 `path:line:kind`만 출력한다. 네트워크 기반 dependency audit과 성능 검사는 실행하지 않고 `dependency_audit_run=0`, `external_network_run=0`으로 보고한다.

### L4/L5 무거운 계층 기준

L4/L5는 코드 변경의 일반 검증 경로가 아니라 사용자가 명시적으로 승인한 수동 검증 경로다. 에이전트는 승인 없이 이 계층을 실행하지 않고, 필요하다고 판단하면 예상 부하와 대체 가능한 L0~L3 검증을 먼저 보고한다.

| 계층 | 포함 범위 | 실행 예 | 보고해야 하는 카운트 |
|------|-----------|---------|----------------------|
| L4 통합 테스트 | 전체 pytest, Docker 기반 전체 테스트, DB·컨테이너가 필요한 통합 검증 | `HARNESS_ALLOW_HEAVY=1 bash scripts/harness/run.sh full-test`, `HARNESS_ALLOW_HEAVY=1 bash scripts/harness/run.sh docker-test` | `full_test_run`, `docker_test_run`, `failed_step_count`, 테스트 통과·실패 수 |
| L5 E2E·smoke 테스트 | smoke, broker/KIS 연동, 외부 API 가능 경로, Admin UI 전체 빌드·전체 테스트 | `HARNESS_ALLOW_HEAVY=1 bash scripts/harness/run.sh smoke`, `HARNESS_ALLOW_HEAVY=1 bash scripts/harness/run.sh admin-build`, `HARNESS_ALLOW_HEAVY=1 bash scripts/harness/run.sh admin-test-all` | `smoke_run`, `admin_build_run`, `admin_test_run`, 외부 연동 실행 여부 |

`check quick`에는 L4/L5 명령과 L6 `security scan`을 포함하지 않는다. `check quick`은 빠른 커밋 전 스냅샷으로 유지하고, 보안 스냅샷은 사용자가 별도로 요청했을 때 `security scan`으로 실행한다.

## 수동 실행 명령

| 목적 | 표준 명령 | Make alias |
|------|-----------|------------|
| Inspection API in-memory 실행 | `bash scripts/harness/run.sh run api-inmemory` | `make run-api-inmemory` |
| Inspection API Postgres/Auth 실행 | `bash scripts/harness/run.sh run api-postgres` | `make run-api-postgres` |

`run api-postgres`는 `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD`, `INSPECTION_API_TOKEN` 누락 여부만 검사하고 값은 출력하지 않는다.

## 승인 플래그가 필요한 명령

| 목적 | 필요한 플래그 | 명령 |
|------|---------------|------|
| 운영 리포트 DB 덤프 | `HARNESS_ALLOW_OPS_DUMP=1` | `bash scripts/harness/run.sh dump ops-report [YYYY-MM-DD]` |
| 전체 pytest | `HARNESS_ALLOW_HEAVY=1` | `bash scripts/harness/run.sh full-test` 또는 `make heavy-full-test` |
| Docker 전체 테스트 | `HARNESS_ALLOW_HEAVY=1` | `bash scripts/harness/run.sh docker-test` 또는 `make heavy-docker-test` |
| smoke 실행 | `HARNESS_ALLOW_HEAVY=1` | `bash scripts/harness/run.sh smoke` 또는 `make heavy-smoke` |
| Admin UI 전체 빌드 | `HARNESS_ALLOW_HEAVY=1` | `bash scripts/harness/run.sh admin-build` 또는 `make heavy-admin-build` |
| Admin UI 전체 테스트 | `HARNESS_ALLOW_HEAVY=1` | `bash scripts/harness/run.sh admin-test-all` 또는 `make heavy-admin-test-all` |

승인 플래그가 필요한 명령은 새 서비스 기동, 장시간 테스트, 전체 빌드, DB 조회/쓰기, 외부 API 호출 가능성을 포함할 수 있으므로 사용자 승인 없이 실행하지 않는다.

Makefile에서는 승인 필요 명령을 `heavy-*` target으로 노출한다. 기존 `full-test`, `docker-test-safe`, `smoke-safe`, `admin-build`, `admin-test-all`은 호환 alias이며 신규 문서와 보고에서는 `heavy-*` 이름을 우선 사용한다.

## 핵심 accept 출력 지표

### `accept docs`

- `required_file_missing_count`: 필수 문서와 하네스 파일 누락 수.
- `markdown_link_missing_count`: 핵심 문서의 깨진 상대 링크 수.
- `deprecated_reference_count`: 오래된 문서 경로 참조 수.
- `documented_make_target_missing_count`: 핵심 문서가 안내하지만 `Makefile`에 없는 target 수.
- `semantic_check_failed_count`: Harness Engineering 필수 문구와 라우팅 규칙 실패 수.

### `accept ci`

- `required_file_missing_count`: CI workflow와 관련 문서·Makefile 누락 수.
- `workflow_file_count`: `.github/workflows/` 아래에서 검사한 workflow 파일 수.
- `harness_command_count`: CI workflow에서 `bash scripts/harness/run.sh ...`를 호출한 수.
- `required_harness_command_missing_count`: 기본 CI gate에 필요한 하네스 명령 누락 수.
- `direct_verifier_command_count`: CI workflow가 `pytest`, `ruff`, `npm test`, `tsc`, `vitest` 같은 정답 판정기를 직접 호출한 수.
- `safe_forbidden_heavy_command_count`: 기본 PR/push `safe` job에 L4/L5 heavy 명령 또는 `HARNESS_ALLOW_HEAVY`가 섞인 수.
- `deploy_workflow_count`: 운영 배포에 영향을 주는 workflow 수.
- `ungated_deploy_workflow_count`: `safe` 또는 동등한 하네스 성공 조건 없이 배포하는 workflow 수.
- `deploy_without_change_detector_count`: 문서-only 변경을 배포 대상에서 제외하는 change detector 없이 배포하는 workflow 수.
- `deploy_missing_migration_count`: 배포 재기동 전에 `docker compose run --rm migrate`를 실행하지 않는 workflow 수.
- `deploy_missing_proxy_reload_count`: 배포 재기동 뒤 `nginx-proxy` reload를 실행하지 않는 workflow 수.
- `destructive_deploy_clean_command_count`: 배포 workflow에서 `git clean -fdx` 또는 `logs/`, `tmp/`, `data/`를 직접 삭제하는 명령 수.
- `quick_step_count`: `check quick`가 실행하는 단계 수.
- `ci_safe_step_count`: CI `safe` job이 직접 호출하는 하네스 단계 수.
- `local_ci_command_gap_count`: CI `safe`가 `check quick`보다 추가로 강제하는 고유 명령 수.
- `quick_only_command_count`: `check quick`에만 있고 CI `safe` 확장 집합에는 없는 고유 명령 수.
- `deploy_manual_dispatch_input_count`: `workflow_dispatch`에 선언된 수동 재배포 입력 수. 현재 계약 값은 `2`다.
- `deploy_manual_dispatch_support_count`: deploy job이 `workflow_dispatch`의 `deploy_main=true` 경로를 실제로 지원하는지 나타내는 수.
- `deploy_target_sha_pin_count`: 수동 재배포가 최신 `origin/main` SHA를 fetch·출력·reset 하는 계약을 만족하는 workflow 수.
- `deploy_market_hours_guard_count`: 장 시간 guard job이 `Asia/Seoul` 기준으로 선언된 workflow 수.
- `deploy_market_hours_skip_metric_count`: 장중 차단 지표 `deploy_skipped_by_market_hours_count`를 출력하는 workflow 수.
- `deploy_market_hours_override_metric_count`: 장중 승인 지표 `deploy_market_hours_override_count`를 출력하는 workflow 수.
- `deploy_job_depends_on_market_guard_count`: deploy job이 장 시간 guard 출력 `allow_deploy`를 실제 조건으로 사용하는 workflow 수.
- `ci_contract_failed_count`: `workflow_dispatch` 수동 재배포 입력, 최신 `origin/main` SHA 고정, heavy 수동 실행 조건, version pin 같은 CI 계약 실패 수.
- `runtime_tracked_file_count`: Git이 추적 중인 `logs/`, `tmp/`, `data/` 파일 수. 현재는 정리 진행을 위한 정보 지표이며, 합의된 허용 목록 정리 후 실패 지표로 전환한다.
- `legacy_docker_compose_count`: workflow 안에서 v1 `docker-compose` 명령을 사용하는 수.

### `accept env`

- `required_file_missing_count`: 버전 고정 파일, lockfile, `.env.example` 누락 수.
- `runtime_version_mismatch_count`: Python, Node.js, npm, PostgreSQL 실제 버전과 고정 버전 불일치 수.
- `static_pin_failed_count`: Dockerfile, pyproject, npm 설정 같은 정적 pin 검증 실패 수.
- `lockfile_failed_count`: Python 또는 Admin UI lockfile 재현성 실패 수.
- `tracked_env_file_count`: git 추적 대상에 포함된 `.env` 파일 수.
- `env_values`: 항상 `redacted`로 출력돼야 한다.

### `accept backend-file`

- `test_discovery_mode`: 변경 파일에 대응하는 테스트 탐색 방식.
- `matched_by_import_count`: import graph로 연결된 테스트 후보 수.
- `safe_test_candidate_count`: 안전 selector로 실행 가능한 후보 수.
- `selected_test_count`: 실제 실행 대상으로 선택된 테스트 수.
- `tests_run_count`: 실행한 pytest selector 수.
- `test_failed_count`: 실패한 selector 수.
- `no_test_policy`: 직접 대응 테스트가 없을 때의 판정 정책.

직접 대응 테스트가 없으면 기본적으로 실패한다. 불가피한 경우에만 `HARNESS_ALLOW_NO_TEST=1`로 명시 우회하고 보고서에 사유를 남긴다.

### `accept db-structure`

- `migration_file_count`: 검사한 SQL migration 파일 수.
- `migration_filename_violation_count`: `0001_name.sql` 형식에 맞지 않는 migration 파일 수.
- `migration_duplicate_number_count`: 같은 번호를 사용하는 migration 번호 수.
- `migration_sequence_gap_count`: migration 번호 연속성 누락 수.
- `repository_protocol_count`: `contracts.py`의 Repository Protocol 수.
- `container_bound_protocol_count`: `RepositoryContainer`에 연결된 Repository Protocol 수.
- `memory_bound_protocol_count`: InMemory 구현이 존재하는 Repository Protocol 수.
- `postgres_class_bound_protocol_count`: Postgres 구현 class가 존재하는 Repository Protocol 수.
- `postgres_bootstrap_bound_protocol_count`: Postgres bootstrap에서 wiring된 Repository Protocol 수.
- `database_connection_run`, `external_network_run`, `full_test_run`: 이 검사가 DB 접속, 외부 네트워크, 전체 테스트를 실행하지 않았음을 나타내는 0/1 지표.

### `accept architecture`

- `python_source_file_count`: 검사한 backend Python 파일 수.
- `backend_import_checked_count`: `agent_trading.*` 또는 `asyncpg` import 검사 건수.
- `domain_forbidden_import_count`: `domain/`에서 상위 계층을 import한 건수.
- `repository_forbidden_import_count`: `repositories/`에서 service, api, broker, runtime 계층을 import한 건수.
- `service_api_import_violation_count`: `services/`에서 API 계층을 import한 건수.
- `broker_forbidden_import_observed_count`: `brokers/`에서 api, repository, service 계층을 import한 관측 건수. 현재는 실패 조건이 아니다.
- `broker_forbidden_import_baseline`: 허용되는 기존 broker 계층 역참조 baseline 수.
- `broker_forbidden_import_excess_count`: broker 계층 역참조가 baseline보다 증가한 수. 실패 조건이다.
- `db_forbidden_import_count`: `db/`에서 api, broker, service 계층을 import한 건수.
- `legacy_direct_db_import_observed_count`: service/API 계층의 기존 직접 DB import 관측 건수.
- `legacy_direct_db_import_baseline`: 허용되는 기존 service/API 직접 DB import baseline 수.
- `legacy_direct_db_import_excess_count`: service/API 직접 DB import가 baseline보다 증가한 수. 실패 조건이다.
- `api_db_boundary_import_observed_count`: 명시 허용된 API DB 경계(`src/agent_trading/api/deps.py`)의 DB import 관측 건수. 실패 조건이 아니다.
- `frontend_direct_fetch_observed_count`: `admin_ui/src/api/`와 테스트를 제외한 직접 `fetch()` 관측 건수. 실패 조건이다.
- `architecture_violation_count`: 현재 실패 조건으로 강제하는 계층 위반 총수.
- `database_connection_run`, `external_network_run`, `full_test_run`: 이 검사가 DB 접속, 외부 네트워크, 전체 테스트를 실행하지 않았음을 나타내는 0/1 지표.

### `accept style`

- `ruff_default_exit_code`: `pyproject.toml` 기본 ruff 규칙 실행 exit code.
- `ruff_default_violation_count`: 기본 ruff 규칙 위반 수.
- `ruff_f_violation_count`: `ruff --select F` 관측 위반 수.
- `ruff_f_baseline`: 허용되는 기존 `F` 계열 baseline 수.
- `ruff_f_excess_count`: `F` 계열 위반이 baseline보다 증가한 수. 실패 조건이다.
- `database_connection_run`, `external_network_run`, `full_test_run`: 이 검사가 DB 접속, 외부 네트워크, 전체 테스트를 실행하지 않았음을 나타내는 0/1 지표.

### `accept no-bypass`

- `changed_file_count`: 검사 대상으로 잡힌 변경 파일 수.
- `scanned_file_count`: 텍스트로 판정해 검사한 변경 파일 수.
- `added_line_count`: 검사한 추가 라인 수.
- `hard_bypass_count`: 실패 조건으로 강제하는 우회 후보 수.
- `review_bypass_count`: 실패시키지 않고 검토 대상으로 표시한 우회 후보 수.
- `allowlisted_bypass_count`: 정책 문서나 하네스 설명에서 발견되어 예외 처리한 설명성 패턴 수.
- `new_bypass_candidate_count`: `hard_bypass_count + review_bypass_count`.
- `database_connection_run`, `external_network_run`, `full_test_run`: 이 검사가 DB 접속, 외부 네트워크, 전체 테스트를 실행하지 않았음을 나타내는 0/1 지표.

세부 정책은 `docs/20_harness_engineering/no_bypass_policy.md`를 따른다. 현재는 `hard_bypass_count > 0`일 때만 실패하고, `review_bypass_count > 0`은 보고와 리뷰 대상으로 남긴다.
CI에서는 PR 기준 `origin/<base>`와 비교하고, `main` push 기준에서는 `HEAD^`와 비교한다. 이를 위해 `safe` job의 checkout은 `fetch-depth: 0`을 사용한다.

### `accept backend-runtime`

- `static_contract_failed_count`: API factory, runtime mode, auth, dependency pin 정적 계약 실패 수.
- `runtime_probe_failed_count`: app factory와 runtime probe 실패 수.
- `import_failed_count`: 핵심 backend module import 실패 수.
- `factory_check_failed_count`: FastAPI app factory 계약 실패 수.
- `route_count`: 로드된 API route 수.
- `app_server_started`, `database_connection_run`, `external_network_run`, `full_test_run`: 부하가 큰 동작 실행 여부를 나타내는 0/1 지표.

### `accept frontend`

- `static_contract_failed_count`: Vite, API client, 타입 생성, 테스트 설정 계약 실패 수.
- `dependency_drift_count`: `package.json`과 `package-lock.json` 불일치 수.
- `test_file_count`: Admin UI 테스트 파일 수.
- `component_file_count`: Admin UI component 파일 수.
- `full_build_run`, `full_test_run`: 전체 빌드와 전체 테스트 실행 여부를 나타내는 0/1 지표.

### `accept ops-report`

- `session_profile`: `decision_loop` 또는 `non_trading_day`.
- `required_path_missing_count`: 필수 JSON 경로 누락 수.
- `counter_type_failed_count`: 카운터 필드 타입 오류 수.
- `counter_inconsistency_count`: 카운터 합계 불일치 수.
- `command_failure_policy_failed_count`: `failed_count`, `timed_out_count` 허용 임계값 초과 수.
- `decision_metric_missing_count`: decision loop metric 누락 수.
- `decision_coverage_failed_count`: held position 처리 등 운영 커버리지 실패 수.
- `decision_health_failed_count`: command health 실패 수.
- `secret_key_hit_count`: secret으로 의심되는 key 또는 value 노출 수.

기본 임계값은 `failed_count=0`, `timed_out_count=0`이다. 임계값을 바꾼 경우 `HARNESS_OPS_ALLOWED_FAILED_COUNT`, `HARNESS_OPS_ALLOWED_TIMED_OUT_COUNT` 값을 보고서에 남긴다.

### `security scan`

- `changed_file_count`: Git 변경 파일 수.
- `untracked_file_count`: Git에 아직 추적되지 않은 후보 파일 수.
- `candidate_file_count`: secret scan 후보 파일 수.
- `scanned_file_count`: secret 패턴을 검사한 텍스트 파일 수.
- `tracked_env_file_count`: Git 추적 대상에 포함된 `.env` 계열 파일 수.
- `secret_hit_count`: secret 후보 패턴 수. 값은 출력하지 않는다.
- `dependency_audit_run`: 네트워크 또는 registry audit 실행 여부를 나타내는 0/1 지표.

## 보고 기준

- AI가 완료를 주장할 수 있는 최소 조건은 [`docs/20_harness_engineering/definition_of_done.md`](../../docs/20_harness_engineering/definition_of_done.md)를 따른다.
- exit code만 보고하지 않는다.
- `*_count`, `*_run`, `route_count`, `test_file_count`처럼 출력된 원문 지표를 함께 보고한다.
- `.env` 값, 토큰, 계좌 정보, API secret은 출력하지 않는다.
- 전체 테스트나 전체 빌드를 실행하지 않은 경우 `full_test_run=0`, `full_build_run=0`처럼 실제 카운트로 남긴다.
