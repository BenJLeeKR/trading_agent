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

## 승인 없이 실행 가능한 명령

| 목적 | 표준 명령 | Make alias |
|------|-----------|------------|
| 하네스 사용법 | `bash scripts/harness/run.sh status` | `make harness-status` |
| 환경 계약 | `bash scripts/harness/run.sh accept env` | `make accept-env` |
| 문서 계약 | `bash scripts/harness/run.sh accept docs` | `make accept-docs` |
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
- `semantic_check_failed_count`: Harness Engineering 필수 문구와 라우팅 규칙 실패 수.

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

## 보고 기준

- exit code만 보고하지 않는다.
- `*_count`, `*_run`, `route_count`, `test_file_count`처럼 출력된 원문 지표를 함께 보고한다.
- `.env` 값, 토큰, 계좌 정보, API secret은 출력하지 않는다.
- 전체 테스트나 전체 빌드를 실행하지 않은 경우 `full_test_run=0`, `full_build_run=0`처럼 실제 카운트로 남긴다.
