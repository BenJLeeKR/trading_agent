# Harness Runner

## 문서 목적

이 문서는 AI 에이전트와 사람이 같은 방식으로 검증 명령을 실행하도록 [`run.sh`](./run.sh)의 표준 진입점, 부하 제한, 출력 지표 해석 기준을 정리한다.

하네스의 상위 작업 규칙은 루트 [`AGENTS.md`](../../AGENTS.md)를 따른다. Make target은 [`Makefile`](../../Makefile)의 convenience alias이며, 정답 판정의 기준은 `run.sh` 출력 지표다.

## 기본 실행 원칙

- 프로젝트 루트는 `run.sh` 위치 기준으로 계산한다.
- 셸은 `bash`만 사용한다.
- Python 실행은 `python3`만 사용한다.
- `.env` 파일은 직접 수정하지 않고, 출력에도 비밀값을 노출하지 않는다.
- 사용자 보고, 문서, 완료 보고, 하네스 설명 문구에서는 `diff`를 단독 용어로 쓰지 않는다. 기본 용어는 `변경분`, `변경 차이`, `전후 차이`, `수정 내역`이다.
- `git diff` 같은 명령명이나 patch/diff 포맷 자체를 가리킬 때만 `diff`를 backtick으로 유지하고, 가능하면 같은 문장에 한국어 설명을 붙인다.
- 기본 timeout은 `HARNESS_SAFE_TIMEOUT_SECONDS`이며 기본값은 `90`초다.
- 무거운 검증 timeout은 `HARNESS_HEAVY_TIMEOUT_SECONDS`이며 기본값은 `900`초다.

## CI 공동 사용 원칙

GitHub Actions도 사람과 AI가 쓰는 동일한 하네스를 사용한다. CI workflow는 `pytest`, `ruff`, `npm`, `docker` 기반 검증 명령을 직접 정답 판정기로 삼지 않고, 준비 단계 이후 `bash scripts/harness/run.sh ...`만 호출한다.

- 기본 PR/push gate는 `.github/workflows/harness.yml`의 `safe` job이다.
- `safe` job은 `check quick`, `accept db-structure`, `accept architecture`, `accept style`, `accept no-bypass`, `type-check backend`, `type-check frontend`, `security scan`을 실행한다.
- `fdc_quota_postgres_integration` job(2026-08-25 신설)은 `safe`/`heavy`와 독립적으로 `tests/services/test_fdc_quota_coordinator.py` **한 파일만** 실제 PostgreSQL(CI 전용 ephemeral `trading_db_fdc_quota_ci` 컨테이너, job 종료 시 폐기)로 검증한다 — 전체 `pytest tests/`(heavy)를 돌리지 않고도 FDC quota migration/row lock/shadow FIFO SQL을 실행 확인하기 위함이다. `fdc_quota_postgres_relevant` job이 이 PR과 직접 관련된 파일(`db/migrations/*fdc_quota*.sql`, `repositories/postgres/fdc_quota.py`, `repositories/{memory,contracts}.py`, `services/fdc_quota_coordinator.py`, 테스트 파일 자체, 이 workflow 파일)이 바뀐 경우에만 `relevant=1`을 출력해 실행 여부를 좁힌다(`workflow_dispatch`는 항상 실행). 이 job은 `bash scripts/harness/run.sh test-file ...`의 exit code만 보지 않고, pytest 출력의 "N skipped" 카운트를 직접 파싱해 1건이라도 skip되면 즉시 실패 처리한다 — `DATABASE_HOST` 미전달로 조용히 skip되는 상황을 exit 0으로 통과시키지 않기 위함이다. `safe`/`heavy` job의 범위·timeout·실행 조건은 이 job 추가로 전혀 바뀌지 않는다.
- 운영 배포는 `.github/workflows/harness.yml`의 `sync_source`, `activate_runtime` job으로 분리돼 있고 둘 다 `needs: safe` 성공 뒤에만 실행한다.
- 문서만 변경된 `main` push는 `changes` job에서 `deploy_required=0`, `activate_required=0`으로 판정해 운영 재기동을 실행하지 않는다.
- 문서만 변경된 `main` push는 `docs/` 경로가 sync-only 허용 대상으로 잡히면 `sync_source`만 실행하고 `activate_runtime`은 실행하지 않는다.
- 이 경로는 `market_hours_guard`가 `skipped`여도 `sync_source`의 `always()` 조건으로 분기 평가가 계속 진행돼야 한다.
- `changes` job은 `activate_required`, `sync_only_candidate_count`, `sync_only_allowlist_count`, `sync_only_blocked_count`를 함께 출력해 장중 sync-only 후보와 runtime 영향 변경을 구분한다.
- runtime 영향 변경이 전부 `admin_ui/` 아래면 `frontend_only_activate=1`로 판정하고, `activate_runtime`은 `docker compose up -d --build frontend`만 실행한다. 프런트 전용 변경에는 DB 스키마 변경이 있을 수 없으므로 `migrate`를 실행하지 않고(`deploy_migration_run=0`), 단일 서비스 지정에 `--remove-orphans`를 함께 쓰지 않는다.
- `nginx-proxy`의 `proxy_pass`는 리터럴 호스트명을 쓰고 `resolver`가 없어 기동 시 1회만 DNS를 해석한다. `frontend`를 recreate하면 IP가 바뀌므로 `docker exec nginx-proxy nginx -s reload`는 프런트 전용 분기와 전체 배포 분기 **양쪽 모두**에서 실행한다.
- 관련 지표: `frontend_only_activate_count`, `non_frontend_runtime_file_count`(`changes` job), `deploy_frontend_only_activate_count`, `deploy_migration_run`(`activate_runtime` job).
- 배포 판정 경로는 세 갈래다. `deploy_relevant`이면서 `runtime_affecting`이면 전체 배포(재기동), `deploy_relevant`지만 runtime 영향이 없으면 장외 sync만, sync-only 허용 목록에 들면 장중에도 sync만 수행한다.
- `scripts/` 최상위 실행 스크립트는 `ops-scheduler`에 bind mount되고 decision loop가 매 사이클 subprocess로 새로 읽으므로 runtime 영향 대상이다. 재기동 없이 코드만 바뀌는 상태를 만들지 않는다.
- `scripts/harness/`와 `.github/workflows/`는 서버 런타임이 읽지 않으므로 재기동 대상이 아니며, 서버 사본이 낡지 않도록 sync-only 허용 목록에 둔다. `docs/`와 같은 취급이다.
- sync-only 허용 목록은 배포 게이트(`deploy_relevant`)와 재기동 판정(`runtime_affecting`) 양쪽에서 제외한다. 한쪽에만 빼면 `market_hours_guard`가 실행돼 장중 sync 경로가 성립하지 않는다.
- 수동 재배포는 `workflow_dispatch`의 `deploy_main=true` 입력으로만 연다.
- 수동 재배포는 과거 workflow run을 재개하지 않고, 실행 시점의 최신 `origin/main` SHA를 다시 fetch한 뒤 그 SHA를 배포한다.
- `market_hours_guard` job은 `Asia/Seoul` 기준 평일 `09:00-15:30 KST`를 장중으로 계산한다.
- 장중에는 자동 배포를 막고 `deploy_skipped_by_market_hours_count=1`을 출력한다.
- 장중이라도 `activate_required=0`, `sync_only_allowlist_count>0`, `sync_only_blocked_count=0`이면 `sync_source`만 실행하고 `deploy_sync_only_run_count=1`, `deploy_activate_skipped_by_market_hours_count=1`을 출력한다.
- `sync_source`의 `git reset --hard`는 이번 push의 변경분이 아니라 `origin/main` 트리 전체를 내려받는다. 따라서 sync-only 모드(`allow_deploy!=1`)에서는 서버 `HEAD`와 배포 대상 SHA 사이에 runtime 영향 파일이 남아 있는지 먼저 판정하고, 1건이라도 있으면 동기화하지 않고 실패로 끝낸다. `src/`와 `scripts/`는 `ops-scheduler`에 bind mount돼 있고 decision loop는 매 사이클 subprocess로 새로 spawn되므로, 이 검사가 없으면 장중에 차단해 둔 매매 코드가 재기동 없이 적용될 수 있다.
- 관련 지표: `deploy_sync_pending_runtime_file_count`, `deploy_sync_blocked_by_pending_runtime_count`. 차단 시 `DETAIL pending_runtime_files:`로 대상 파일을 나열한다.
- runtime 영향 경로 규칙은 `changes` job에 한 번만 정의하고 `runtime_affecting_pattern` output으로 `sync_source`에 전달한다. 같은 규칙을 두 곳에 중복 정의하지 않는다.
- 장중 수동 재배포는 `allow_market_hours_deploy=true`일 때만 허용하고 `deploy_market_hours_override_count=1`을 출력한다.
- 프런트 전용 변경(`frontend_only_activate=1`)은 장중에도 자동 배포를 허용하고 `deploy_market_hours_frontend_only_pass_count=1`을 출력한다. `admin_ui/`는 어떤 컨테이너에도 bind mount되지 않고 Admin UI는 read/inspect 전용이라 `ops-scheduler`·`reconciliation-worker`·`api`에 영향이 없다. 장중 차단을 유지하면 `allow_market_hours_deploy` override 사용이 습관이 되어 가드 자체가 무력해진다.
- 이때 `sync_source`의 대기 변경 판정은 계속 적용된다. 판정 기준은 `allow_deploy`가 아니라 **`activate_runtime`이 전체 재기동을 하는가**다. 프런트 전용은 `allow_deploy=1`이지만 `frontend`만 재빌드하므로, 함께 내려온 백엔드 변경이 bind mount된 `src/`·`scripts/`에 남아 재기동 없이 적용될 수 있다. 이 경로에서는 `admin_ui/` 변경만 대기 대상에서 제외한다(프런트 재빌드로 실제 반영되므로).
- 장중 source sync와 activate 분리 설계 초안은 `docs/80_harness_engineering/deploy_sync_activation_contract.md`를 따른다.
- 남은 실검증은 장 외 시간 `push main`에서 `activate_runtime=success`가 나오는 자연 경로 `1`건이며, 기대 조합은 `deploy_market_hours_override_count=0`, `Sync source after safe harness=success`, `Activate runtime after source sync=success`다.
- 거래소 휴장일 캘린더는 아직 연동하지 않았으므로 1차 가드는 평일 시간대 기준이다.
- 배포 재기동 뒤에는 `nginx-proxy`를 reload해 Docker DNS가 새 frontend 컨테이너 IP를 다시 해석하게 한다.
- CI workflow 자체의 정합성 판정은 `accept ci`가 담당한다.
- GitHub ruleset `Require Harness on main`은 기본 브랜치에 `Safe harness contracts` 상태 검사를 필수 항목으로 요구한다.
- CI의 PostgreSQL 버전 판정은 `.postgres-version`과 같은 버전의 `trading_db` 컨테이너를 시작한 뒤 `accept env`가 확인한다.
- CI의 Node.js/npm 판정은 `admin_ui/.nvmrc`, `admin_ui/.npm-version`과 일치하는 pin 이미지 또는 setup-node 환경을 기준으로 확인한다.
- `HARNESS_ALLOW_HEAVY=1`이 필요한 L4/L5 검증은 기본 PR/push에서 실행하지 않고 `workflow_dispatch` 입력으로만 실행한다.

## 승인 없이 실행 가능한 명령

| 목적 | 표준 명령 | Make alias |
|------|-----------|------------|
| 하네스 사용법 | `bash scripts/harness/run.sh status` | `make harness-status` |
| 빠른 계층 검증 | `bash scripts/harness/run.sh check quick` | `make check-quick` |
| CI 등가 로컬 검증 | `bash scripts/harness/run.sh check full` | `make check-full` |
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
| 단일 운영 스크립트 파일 | `bash scripts/harness/run.sh accept script-file <file>` | `make accept-script-file FILE=<file>` |
| 백엔드 런타임 계약 | `bash scripts/harness/run.sh accept backend-runtime` | `make accept-backend-runtime` |
| Admin UI 계약 | `bash scripts/harness/run.sh accept frontend` | `make accept-admin-ui` |
| 운영 리포트 JSON 계약 | `bash scripts/harness/run.sh accept ops-report <summary_json>` | `make accept-ops-report SUMMARY_JSON=<summary_json>` |
| Python 컴파일 | `bash scripts/harness/run.sh py-compile <python_file>` | `make check-file FILE=<python_file>` |
| 단일 pytest selector | `bash scripts/harness/run.sh test-one <selector>` | `make test-one TEST=<selector>` |
| 단일 pytest 파일 | `bash scripts/harness/run.sh test-file <tests/path.py>` | `make test-file TEST=<tests/path.py>` |
| 경로별 ruff | `bash scripts/harness/run.sh lint-path <path>` | `make lint-path TARGET=<path>` |
| 단일 Admin UI 테스트 | `bash scripts/harness/run.sh admin-test-one <selector>` | `make admin-test-one TEST=<selector>` |
| dev validation 이미지 재빌드 | `HARNESS_DEV_REBUILD_IMAGE=1 bash scripts/harness/docker_dev_exec.sh python3 --version` | `make dev-validation-image` |
| dev validation Python 확인 | `bash scripts/harness/docker_dev_exec.sh python3 --version` | `make dev-validation-python` |
| dev validation 임의 명령 | `bash scripts/harness/docker_dev_exec.sh <command...>` | `make dev-validation-exec CMD='<command...>'` |

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

Docker/배포 표준 명령은 `bash scripts/harness/docker_compose_env.sh ...`를 사용하며, 이 래퍼가 `/etc/agent_trading/*.env`를 우선 로드한다.

`/workspace/agent_trading_dev`의 Python 검증은 host `python3` 대신 `bash scripts/harness/docker_dev_exec.sh ...`가 띄우는 dev validation container를 사용한다. 이 컨테이너는 운영 컨테이너를 재사용하지 않고 `/workspace/agent_trading_dev`만 `/app`에 mount하며, 기본 `--network none`과 Dozzle 식별 label을 사용한다. 종료 후 더 오래 관찰해야 할 때만 `HARNESS_DEV_KEEP_CONTAINER=1`로 `--rm` 제거를 허용한다.
`accept frontend`의 Node/npm 버전 판정은 host fallback 없이 pinned `node:<version>-slim` probe만 사용한다. probe 실패 시 `host-node`나 `host-npm`로 우회하지 않고 계약 실패로 처리한다.
`/workspace/agent_trading_dev`의 `type-check frontend`, `admin-test-one`도 host Node/npm 대신 `bash scripts/harness/docker_dev_frontend_exec.sh ...`가 띄우는 frontend validation container를 사용한다.
직접 확인이 필요하면 `make dev-frontend-validation-node`, `make dev-frontend-validation-exec CMD='npm run test:run -- src/__tests__/alerts.test.ts'`를 사용한다.

현재 2026-07-29 기준 계측은 다음과 같다.

- `quick_step_count=8`
- `full_step_count=14`
- `ci_safe_step_count=8`
- `local_ci_command_gap_count=6`
- `quick_only_command_count=0`
- `full_ci_command_gap_count=0`
- `full_only_command_count=0`
- `pip_install_command_count=2`
- `pip_install_without_constraints_count=0`

해석:

- raw 호출 수는 둘 다 `8`이지만, `safe` job은 `check quick` 외에 `accept db-structure`, `accept architecture`, `accept style`, `type-check backend`, `type-check frontend`, `security scan`을 추가로 강제한다.
- 즉, 현재 로컬 기본 스냅샷과 CI safe gate 사이에는 고유 명령 기준 `6`개의 차이가 있다.
- 이 차이는 `check quick`을 가볍게 유지하고 `check full`을 CI safe 등가 계약으로 두는 방식으로 정리했다.
- 커밋 전 빠른 확인은 `check quick`, CI와 같은 범위의 로컬 확인은 `check full`을 사용한다.

`check changed`는 Git 변경 목록에서 `src/agent_trading/**/*.py` 파일을 골라 각 파일에 `accept backend-file`을 적용하고, 여기에 더해 **운영 경로 allowlist에 등록된 `scripts/*.py` 12개**를 골라 각 파일에 `accept script-file`을 적용한다. 문서만 변경된 경우 `changed_backend_file_count=0`, `script_allowlist_candidate_count=0`으로 보고하며 전체 테스트를 실행하지 않는다.

allowlist는 `scripts/harness/run.sh`의 `HARNESS_SCRIPT_ALLOWLIST` 배열에 하드코딩돼 있고, 기준은 `docker-compose.yml`의 command와 `run_ops_scheduler.py`의 subprocess 호출이다. 실행 구성이 바뀌면 이 배열도 함께 갱신해야 한다.

- `script_allowlist_size`: allowlist에 등록된 운영 경로 스크립트 수.
- `script_allowlist_candidate_count`: 변경 목록에서 allowlist에 걸린 파일 수.
- `script_allowlist_checked_count`: 실제로 `accept script-file`을 실행한 파일 수.
- `script_allowlist_failed_count`: 그중 판정에 실패한 파일 수. 0이 아니면 `check changed`가 FAIL이다.

`scripts/` 전체 자동 판정은 아직 도입하지 않았다. allowlist 밖 `scripts/*.py` 변경은 `skipped_non_backend_file_count`로 집계되며, 필요하면 `bash scripts/harness/run.sh accept script-file <file>`을 수동으로 실행한다.

`type-check backend`는 `mypy` 또는 `pyright`가 설치된 경우에만 실행한다. 둘 다 없으면 `backend_type_tool_missing_count=1`, `backend_type_check_run=0`으로 보고한다. `type-check frontend`는 `admin_ui/package.json`의 `typecheck`, `type-check`, `check:types` script 중 하나가 있을 때만 실행한다. script가 없으면 `frontend_typecheck_script_missing_count=1`, `frontend_type_check_run=0`으로 보고한다.

`security scan`은 Git 변경 파일과 untracked 후보 파일을 대상으로 secret key/value 패턴을 read-only로 검사한다. `.env` 값은 읽거나 출력하지 않고, secret 후보가 있으면 값 대신 `path:line:kind`만 출력한다. 네트워크 기반 dependency audit과 성능 검사는 실행하지 않고 `dependency_audit_run=0`, `external_network_run=0`으로 보고한다.

### L4/L5 무거운 계층 기준

L4/L5는 코드 변경의 일반 검증 경로가 아니라 사용자가 명시적으로 승인한 수동 검증 경로다. 에이전트는 승인 없이 이 계층을 실행하지 않고, 필요하다고 판단하면 예상 부하와 대체 가능한 L0~L3 검증을 먼저 보고한다.

| 계층 | 포함 범위 | 실행 예 | 보고해야 하는 카운트 |
|------|-----------|---------|----------------------|
| L4 통합 테스트 | 전체 pytest, Docker 기반 전체 테스트, DB·컨테이너가 필요한 통합 검증 | `HARNESS_ALLOW_HEAVY=1 bash scripts/harness/run.sh full-test`, `HARNESS_ALLOW_HEAVY=1 bash scripts/harness/run.sh docker-test` | `full_test_run`, `docker_test_run`, `failed_step_count`, 테스트 통과·실패 수 |
| L5 E2E·smoke 테스트 | smoke, broker/KIS 연동, 외부 API 가능 경로, Admin UI 전체 빌드·전체 테스트 | `HARNESS_ALLOW_HEAVY=1 bash scripts/harness/run.sh smoke`, `HARNESS_ALLOW_HEAVY=1 bash scripts/harness/run.sh admin-build`, `HARNESS_ALLOW_HEAVY=1 bash scripts/harness/run.sh admin-test-all` | `smoke_run`, `admin_build_run`, `admin_test_run`, 외부 연동 실행 여부 |

`check quick`에는 L4/L5 명령과 L6 `security scan`을 포함하지 않는다. `check quick`은 빠른 커밋 전 스냅샷으로 유지한다.

`check full`은 `check quick`에 `accept db-structure`, `accept architecture`, `accept style`, `type-check backend`, `type-check frontend`, `security scan`을 더한 로컬 CI-safe 등가 계약이다. L4/L5 heavy 명령은 여전히 포함하지 않는다.

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
- `documented_run_sh_command_missing_count`: 문서가 안내하지만 `scripts/harness/run.sh`가 실제로 지원하지 않는 명령 수.
- `run_sh_usage_dispatch_mismatch_count`: `scripts/harness/run.sh`의 사용법 블록과 실제 dispatch selector가 서로 어긋나는 명령 수.
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
- `deploy_missing_migration_count`: 배포 재기동 전에 최신 소스로 `migrate` 이미지를 재빌드하는 `docker compose run --build --rm migrate`(또는 `docker_compose_env.sh` 동등 명령)를 실행하지 않는 workflow 수.
- `deploy_missing_proxy_reload_count`: 배포 재기동 뒤 `nginx-proxy` reload를 실행하지 않는 workflow 수.
- `destructive_deploy_clean_command_count`: 배포 workflow에서 `git clean -fdx` 또는 `logs/`, `tmp/`, `data/`를 직접 삭제하는 명령 수.
- `quick_step_count`: `check quick`가 실행하는 단계 수.
- `full_step_count`: `check full`이 실행하는 단계 수.
- `ci_safe_step_count`: CI `safe` job이 직접 호출하는 하네스 단계 수.
- `local_ci_command_gap_count`: CI `safe`가 `check quick`보다 추가로 강제하는 고유 명령 수.
- `quick_only_command_count`: `check quick`에만 있고 CI `safe` 확장 집합에는 없는 고유 명령 수.
- `full_ci_command_gap_count`: CI `safe`가 `check full`보다 추가로 강제하는 고유 명령 수.
- `full_only_command_count`: `check full`에만 있고 CI `safe` 확장 집합에는 없는 고유 명령 수.
- `node20_target_action_count`: Node 20 대상 메이저(`actions/checkout@v4`, `actions/setup-python@v5`, `actions/setup-node@v4`)를 아직 사용하는 workflow step 수.
- `pip_install_command_count`: workflow 안의 Python dependency 설치 명령 수.
- `pip_install_without_constraints_count`: `requirements.lock` 제약 없이 실행되는 workflow의 `pip install` 명령 수.
- `deploy_manual_dispatch_input_count`: `workflow_dispatch`에 선언된 수동 재배포 입력 수. 현재 계약 값은 `2`다.
- `deploy_manual_dispatch_support_count`: deploy job이 `workflow_dispatch`의 `deploy_main=true` 경로를 실제로 지원하는지 나타내는 수.
- `deploy_target_sha_pin_count`: 수동 재배포가 최신 `origin/main` SHA를 fetch·출력·reset 하는 계약을 만족하는 workflow 수.
- `deploy_market_hours_guard_count`: 장 시간 guard job이 `Asia/Seoul` 기준으로 선언된 workflow 수.
- `deploy_market_hours_skip_metric_count`: 장중 차단 지표 `deploy_skipped_by_market_hours_count`를 출력하는 workflow 수.
- `deploy_market_hours_override_metric_count`: 장중 승인 지표 `deploy_market_hours_override_count`를 출력하는 workflow 수.
- `deploy_sync_job_present_count`: `sync_source` job이 workflow에 선언된 수.
- `deploy_activate_job_present_count`: `activate_runtime` job이 workflow에 선언된 수.
- `deploy_activate_guard_present_count`: `activate_runtime` job이 장 시간 guard와 `sync_source` 성공 조건을 함께 요구하는 workflow 수.
- `deploy_sync_skipped_guard_present_count`: `sync_source` job이 `always()`와 `market_hours_guard.result == 'skipped'` 보호 조건을 함께 가진 workflow 수.
- `deploy_sync_only_run_metric_count`: workflow가 `deploy_sync_only_run_count` 지표를 출력하는 수.
- `deploy_activate_run_metric_count`: workflow가 `deploy_activate_run_count` 지표를 출력하는 수.
- `deploy_activate_skipped_by_market_hours_metric_count`: workflow가 `deploy_activate_skipped_by_market_hours_count` 지표를 출력하는 수.
- `deploy_activate_required_output_count`: `changes` job이 `activate_required` 출력을 선언하고 기록하는 workflow 수.
- `deploy_sync_only_candidate_count_output_count`: `changes` job이 `sync_only_candidate_count` 출력을 선언하고 기록하는 workflow 수.
- `deploy_sync_only_allowlist_count_output_count`: `changes` job이 `sync_only_allowlist_count` 출력을 선언하고 기록하는 workflow 수.
- `deploy_sync_only_blocked_count_output_count`: `changes` job이 `sync_only_blocked_count` 출력을 선언하고 기록하는 workflow 수.
- `deploy_sync_only_allowlist_defined_count`: 장중 sync-only 허용 `docs/` 및 제한된 `scripts/` allowlist가 workflow에 정의된 수.
- `deploy_runtime_affecting_path_rule_count`: runtime-affecting 경로 denylist 규칙이 workflow에 정의된 수.
- `ci_contract_failed_count`: `workflow_dispatch` 수동 재배포 입력, 최신 `origin/main` SHA 고정, heavy 수동 실행 조건, version pin, Node 20 대상 액션 잔존 같은 CI 계약 실패 수.
- `runtime_tracked_file_count`: Git이 추적 중인 `logs/`, `tmp/`, `data/` 파일 수. 현재는 정리 진행을 위한 정보 지표이며, 합의된 허용 목록 정리 후 실패 지표로 전환한다.
- `legacy_docker_compose_count`: workflow 안에서 v1 `docker-compose` 명령을 사용하는 수.

### `accept env`

- `required_file_missing_count`: 버전 고정 파일, lockfile, `.env.example` 누락 수.
- `runtime_version_mismatch_count`: Python, Node.js, npm, PostgreSQL 실제 버전과 고정 버전 불일치 수.
- `static_pin_failed_count`: Dockerfile, pyproject, npm 설정 같은 정적 pin 검증 실패 수.
- `lockfile_failed_count`: Python 또는 Admin UI lockfile 재현성 실패 수.
- `tracked_env_file_count`: git 추적 대상에 포함된 `.env` 파일 수.
- `runtime_external_env_required_missing_count`: `/etc/agent_trading` 아래 필수 env 파일(`runtime.env`, `ai.env`, `kis.env`) 누락 수.
- `runtime_external_env_unreadable_count`: 외부 env 디렉터리 또는 파일을 현재 실행 계정이 읽지 못하는 경로 수.
- `runtime_external_env_loaded_file_count`: 외부 env에서 실제로 읽은 파일 수.
- `runtime_external_env_required_key_missing_count`: 외부 env에서 필수 런타임 키(`DATABASE_*`, `INSPECTION_API_TOKEN`)가 빠진 수.
- `runtime_external_env_dir_status`: `ci-skip`, `missing`, `ready`, `unreadable` 중 하나로 외부 env 디렉터리 상태를 출력한다.
- `runtime_env_wiring_required_count`: 배선 계약에서 `required_in_compose=true`로 등록된 키 수.
- `runtime_env_wiring_checked_service_count`: 그 키들이 요구하는 compose 서비스 수.
- `runtime_env_wiring_missing_count`: 계약이 요구하는 서비스의 `environment` 블록에 키가 없는 건수. 1건 이상이면 실패다.
- `runtime_env_wiring_contract_parse_failed_count`: 계약 파일이 없거나 형식이 어긋난 건수. 1건 이상이면 실패다.
- `env_values`: 항상 `redacted`로 출력돼야 한다.

#### 런타임 env 배선 계약

외부 env 파일에 값이 있다고 해서 컨테이너가 그 값을 받는 것은 아니다. `docker-compose.yml`의 해당 서비스 `environment:`에 키가 배선돼 있어야 실제로 주입된다. `accept env`는 [`scripts/harness/contracts/runtime_env_wiring.json`](./contracts/runtime_env_wiring.json)에 등록된 키만 이 배선을 강제한다.

`.env.example`의 모든 키를 강제하지 않는 이유는 그 파일에 배포 도구용, 로컬 개발용, 문서용 키가 섞여 있어 전수 검사의 오탐이 크기 때문이다. 계약 파일에는 **런타임에 compose-managed 서비스로 주입돼야 하는 키만** 올린다.

검사는 전역 문자열 검색이 아니라 `services:` → 서비스 블록 → `environment:` 순으로 범위를 좁혀 수행한다. 다른 서비스에 같은 키가 있거나 주석으로만 남아 있으면 통과하지 않는다.

**새 런타임 env 키를 추가할 때는 계약 파일과 `docker-compose.yml` 배선을 함께 갱신한다.** 외부 env 파일에 값을 넣는 것만으로는 끝나지 않는다. 아직 배선 전이거나 관측용으로만 등록하려면 `required_in_compose=false`로 두며, 이 경우 실패시키지 않는다.

### `accept backend-file`

- `test_discovery_mode`: 변경 파일에 대응하는 테스트 탐색 방식.
- `matched_by_import_count`: import graph로 연결된 테스트 후보 수.
- `safe_test_candidate_count`: 안전 selector로 실행 가능한 후보 수.
- `selected_test_count`: 실제 실행 대상으로 선택된 테스트 수.
- `tests_run_count`: 실행한 pytest selector 수.
- `test_failed_count`: 실패한 selector 수.
- `no_test_policy`: 직접 대응 테스트가 없을 때의 판정 정책.

직접 대응 테스트가 없으면 기본적으로 실패한다. 불가피한 경우에만 `HARNESS_ALLOW_NO_TEST=1`로 명시 우회하고 보고서에 사유를 남긴다.

### `accept script-file`

`scripts/` 아래 Python 파일 하나를 판정한다. `src/agent_trading/`만 대상으로 하는 `accept backend-file`이 다루지 못하던 운영 배치 스크립트를 위한 진입점이다. 판정 절차와 출력 형식은 `accept backend-file`과 같고, 테스트 탐색도 동일하게 import graph 우선 + 파일명 stem fallback 방식을 쓴다.

- `valid_script_file`: 대상 경로가 `scripts/` 아래 Python 파일인지 여부.
- `test_discovery_mode`: 대응 테스트 탐색 방식(`import_graph` / `stem_fallback` / `none`).
- `matched_by_import_count`: import graph로 연결된 테스트 후보 수.
- `safe_test_candidate_count`: 안전 selector로 실행 가능한 후보 수.
- `selected_test_candidate_count`: 실제 실행 대상으로 선택된 테스트 수.
- `dropped_test_candidate_count`: 실행 상한(`ACCEPT_SCRIPT_MAX_TEST_FILES`, 기본 3)에 걸려 제외된 후보 수.
- `tests_run_count`: 실행한 pytest selector 수.
- `test_failed_count`: 실패한 selector 수.
- `no_test_override`: `HARNESS_ALLOW_NO_TEST=1` 우회 사용 여부.

`accept backend-file`과 동일하게 **직접 대응 테스트가 없으면 기본 FAIL**이다. 불가피한 경우에만 `HARNESS_ALLOW_NO_TEST=1`로 명시 우회하고 보고서에 사유를 남긴다. `scripts/` 밖 경로를 넘기면 `valid_script_file=0`과 `invalid_path_scope=<file>`로 실패한다.

1차 도입에서 우선 확인한 핵심 운영 배치는 다음 4개다.

```bash
bash scripts/harness/run.sh accept script-file scripts/run_decision_loop.py
bash scripts/harness/run.sh accept script-file scripts/run_ops_scheduler.py
bash scripts/harness/run.sh accept script-file scripts/run_realized_pnl_recompute_worker.py
bash scripts/harness/run.sh accept script-file scripts/run_reconciliation_worker.py
```

`check changed`는 운영 경로 allowlist 12개에 한해 이 판정기를 자동 실행한다(위 `check changed` 절 참고). `accept style`, `type-check backend`, `accept architecture`의 대상 경로는 아직 `src/agent_trading` 기준이며 `scripts/`를 포함하지 않는다.

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

세부 정책은 `docs/80_harness_engineering/no_bypass_policy.md`를 따른다. 현재는 `hard_bypass_count > 0`일 때만 실패하고, `review_bypass_count > 0`은 보고와 리뷰 대상으로 남긴다.
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
- `dev_frontend_contract_failed_count`: `/workspace/agent_trading_dev`에서 frontend 검증을 host Node/npm이 아니라 `docker_dev_frontend_exec.sh` 경로로 강제하는 계약 실패 수.
- `runtime_probe_failed_count`: pinned `node:<version>-slim` probe 실패 수. host fallback 없이 그대로 실패로 본다.
- `dependency_drift_count`: `package.json`과 `package-lock.json` 불일치 수.
- `test_file_count`: Admin UI 테스트 파일 수.
- `component_file_count`: Admin UI component 파일 수.
- `full_build_run`, `full_test_run`: 전체 빌드와 전체 테스트 실행 여부를 나타내는 0/1 지표.

`accept frontend`는 Node/npm 런타임 판정을 host fallback 없이 pinned `node:<version>-slim` probe만으로 수행한다. 또한 `/workspace/agent_trading_dev` 기준 frontend 검증 계약은 `Dockerfile.dev-frontend-validation`, `scripts/harness/docker_dev_frontend_exec.sh`, `type-check frontend`/`admin-test-one`의 dev container 라우팅까지 함께 고정한다.

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

- AI가 완료를 주장할 수 있는 최소 조건은 [`docs/80_harness_engineering/definition_of_done.md`](../../docs/80_harness_engineering/definition_of_done.md)를 따른다.
- exit code만 보고하지 않는다.
- `*_count`, `*_run`, `route_count`, `test_file_count`처럼 출력된 원문 지표를 함께 보고한다.
- `.env` 값, 토큰, 계좌 정보, API secret은 출력하지 않는다.
- 전체 테스트나 전체 빌드를 실행하지 않은 경우 `full_test_run=0`, `full_build_run=0`처럼 실제 카운트로 남긴다.
