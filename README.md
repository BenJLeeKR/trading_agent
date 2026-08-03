# Agent Trading System

멀티 에이전트 트레이딩 시스템 — PostgreSQL 기반 주문 저장/조회 엔진.

## 작업 지침

이 README는 프로젝트 설치와 실행 안내를 담당한다. 에이전트 작업 규칙과 Harness Engineering 원칙은 다음 문서를 우선한다.

- [`AGENTS.md`](./AGENTS.md): Codex 및 공통 에이전트 작업 규칙
- [`CLAUDE.md`](./CLAUDE.md): Claude Code용 지침 라우터
- [`docs/99_meta_handover/agent_workspace_guide.md`](./docs/99_meta_handover/agent_workspace_guide.md): 작업 방식과 문서 분리 기준
- [`scripts/harness/README.md`](./scripts/harness/README.md): 하네스 실행기와 accept 출력 지표 안내

---

## 요구사항

- **Python** 3.14.6
- **Node.js** 20.20.2 / **npm** 10.8.2
- **Docker** (선택사항 — PostgreSQL 컨테이너 실행용)
- **PostgreSQL** 16.14 (Docker 미사용 시 로컬 설치 필요)

---

## 빠른 시작 (로컬)

### 1. 가상환경 생성 및 의존성 설치

```bash
python3 -m venv .venv
make install
```

### 2. 환경변수 설정

```bash
cp .env.example .env
# 필요시 .env 파일 편집 (기본값으로 로컬 개발 가능)
```

### 3. PostgreSQL 실행

Docker 사용:

```bash
bash scripts/harness/docker_compose_env.sh up -d db
```

### 4. 마이그레이션 실행

```bash
make migrate
```

성공 시 `trading` 스키마에 24개 테이블이 생성됩니다.

### 5. 기본 하네스 검증

```bash
make accept-docs
make accept-env
make accept-backend-runtime
```

각 명령의 출력에서 `*_failed_count=0`, `*_missing_count=0`, `runtime_version_mismatch_count=0` 같은 지표를 확인한다.

전체 테스트는 Ubuntu 서버 부하 제한 대상이다. 필요한 경우에만 사용자 승인 후 다음처럼 실행한다.

```bash
HARNESS_ALLOW_HEAVY=1 make heavy-full-test
```

---

## Docker 환경

> **⚠️ `api` 컨테이너는 기동 시 더 이상 자동으로 DB migration을 실행하지 않습니다.**
> "api 재기동"과 "DB migration 실행"은 분리된 절차입니다 — migration은 아래처럼
> 명시적으로 먼저 실행한 뒤 `api`를 올려야 합니다.

### 1. 빌드

```bash
bash scripts/harness/docker_compose_env.sh build
```

### 2. 마이그레이션 (api보다 먼저 실행)

**표준 경로**는 `docker-compose.yml`의 one-shot `migrate` service입니다 —
`api`와 동일한 `DATABASE_*` 환경변수를 재사용하며, migration만 실행하고
종료됩니다:

```bash
bash scripts/harness/docker_compose_env.sh run --rm migrate
```

`make docker-migrate`는 위 명령의 convenience alias입니다(내부적으로 동일한
`bash scripts/harness/docker_compose_env.sh run --rm migrate`를 호출합니다) — 별도의 실행 경로가 아닙니다:

```bash
make docker-migrate
```

성공(exit code 0)을 확인한 뒤에만 다음 단계로 진행하세요.

### 3. 서비스 기동

```bash
bash scripts/harness/docker_compose_env.sh up -d
# 또는 api만: bash scripts/harness/docker_compose_env.sh up -d api
```

`migrate` 서비스는 `profiles: [migrate]`로 분리돼 있어 `bash scripts/harness/docker_compose_env.sh up -d`
대상에 포함되지 않습니다 — 매번 재기동할 때마다 migration이 재실행되는 일은
없습니다.

### 4. 테스트

```bash
make docker-test
```

### 5. 셸 접속

```bash
make docker-shell
```

### 6. 종료

```bash
make docker-down
```

---

## Inspection API 실행

Inspection API는 FastAPI 기반의 읽기 전용 조회 API입니다. **실행 방식에 따라 DB 연결 여부가 결정됩니다.**

### 실행 방식 비교

| 방식 | 명령 | DB 연결 | Auth | 환경변수 |
|------|------|---------|------|----------|
| In-memory (개발용) | `bash scripts/harness/run.sh run api-inmemory` | ❌ (in-memory mock) | ❌ (비활성) | 무시됨 |
| Postgres (운영용) | `bash scripts/harness/run.sh run api-postgres` | ✅ PostgreSQL | ✅ Bearer token | `API_RUNTIME_MODE`, `INSPECTION_API_TOKEN` |

### ⚠️ 잘못된 실행 방식 — 항상 in-memory

```bash
# ❌ 아래 방식은 INSPECTION_API_TOKEN을 설정해도 in_memory 모드로 실행됩니다.
#    module-level app = create_app(auth_enabled=False) 가 고정되어 있기 때문입니다.
uvicorn agent_trading.api.app:app --reload --host 0.0.0.0 --port 9000

# ❌ API_RUNTIME_MODE=postgres 도 module-level app에서는 무시됩니다.
API_RUNTIME_MODE=postgres \
uvicorn agent_trading.api.app:app --reload --host 0.0.0.0 --port 9000
```

### ✅ 올바른 실행 방식 — Postgres + Auth

`create_app_from_env`를 `--factory` 플래그와 함께 사용해야 환경변수가 적용됩니다.

```bash
# 1. .env 또는 export로 DATABASE_* 환경변수 로드
#    값은 터미널에 출력하지 않습니다.
set -a; source .env; set +a

# 2. 사용자가 직접 INSPECTION_API_TOKEN 설정
export INSPECTION_API_TOKEN=<token>

# 3. Postgres-backed 모드로 실행
bash scripts/harness/run.sh run api-postgres

# 또는 Makefile target 사용
make run-api-postgres
```

> **참고**: `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD`, `INSPECTION_API_TOKEN` 환경변수가 설정되어 있어야 Postgres 모드가 실행됩니다. `.env` 파일은 사용자가 직접 관리하고, 값은 문서·보고서·로그에 출력하지 않습니다.

### Docker Compose (권장)

```bash
bash scripts/harness/docker_compose_env.sh up -d db api
```

`docker-compose.yml`은 이미 올바른 방식(`create_app_from_env --factory`)을 사용하고 있습니다.

---

## 프로젝트 구조

```text
├── src/agent_trading/      # 백엔드 애플리케이션 코드
├── scripts/                # 운영·검증·스모크 실행 스크립트
├── tests/                  # pytest 기반 테스트
├── db/migrations/          # PostgreSQL 스키마 마이그레이션
├── admin_ui/               # 운영 대시보드 UI
├── docs/                   # 설계·분석·운영 문서
├── data/                   # 로컬 데이터와 스냅샷 입력
├── logs/                   # 런타임 로그와 운영 산출물
├── docker-compose.yml      # 로컬/서버 Docker 구성
├── Makefile                # 표준 실행 명령
└── pyproject.toml          # Python 패키지와 의존성 정의
```

---

## 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `APP_ENV` | `paper` | 실행 환경 (`paper` / `live`) |
| `APP_TIMEZONE` | `Asia/Seoul` | 시스템 타임존 |
| `DATABASE_HOST` | `localhost` | PostgreSQL 호스트 |
| `DATABASE_PORT` | `5432` | PostgreSQL 포트 |
| `DATABASE_NAME` | `trading` | 데이터베이스 이름 |
| `DATABASE_USER` | `trading` | 데이터베이스 사용자 |
| `DATABASE_PASSWORD` | `trading` | 데이터베이스 비밀번호 |
| `DATABASE_SCHEMA` | `trading` | 스키마 이름 |
| `API_RUNTIME_MODE` | `in_memory` | Inspection API 런타임 모드 (`postgres` / `in_memory`). `create_app_from_env --factory` 방식에서만 읽힘. |
| `INSPECTION_API_TOKEN` | — | Inspection API Bearer token. **운영 필수.** 미설정 시 startup fail. `create_app_from_env --factory` 방식에서만 읽힘. |
| `INSPECTION_API_ROLE` | `viewer` | 인증된 사용자 역할 (`viewer` / `admin`). `create_app_from_env --factory` 방식에서만 읽힘. |

> **호환성**: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` 도 지원하지만
> `DATABASE_*` prefix가 우선합니다.
>
> **⚠️ 중요**: `API_RUNTIME_MODE`, `INSPECTION_API_TOKEN`, `INSPECTION_API_ROLE`은
> `uvicorn agent_trading.api.app:app` (module-level app) 방식에서는 **무시됩니다**.
> 반드시 `uvicorn agent_trading.api.app:create_app_from_env --factory` 방식으로 실행해야
> 이 환경변수들이 적용됩니다.

---

## Make 명령어

| 명령어 | 설명 |
|--------|------|
| `make install` | 의존성 설치 (`python3 -m pip install -e ".[dev]"`) |
| `make run` | 앱 실행 |
| `make migrate` | 로컬 마이그레이션 실행 |
| `make harness-status` | 하네스 기준 프로젝트 상태 확인 |
| `make env-check` | `make accept-env`의 호환 alias |
| `make check-file FILE=...` | 단일 Python 파일 컴파일 확인 |
| `make test-one TEST=...` | 단일 pytest 테스트 실행 |
| `make test-file TEST=...` | 단일 pytest 파일 실행 |
| `make lint-path TARGET=...` | 지정 경로 ruff 정적 분석 |
| `make docs-check` | `make accept-docs`의 호환 alias |
| `make accept-docs` | 핵심 문서 하네스 판정기 실행 |
| `make accept-ci` | CI workflow가 같은 하네스를 쓰는지 판정 |
| `make accept-env` | 운영 환경 재현성 하네스 판정기 실행 |
| `make accept-backend-file FILE=...` | 단일 백엔드 Python 파일 하네스 판정기 실행 |
| `make accept-backend-runtime` | 백엔드 런타임 import/factory 계약 판정기 실행 |
| `make accept-admin-ui` | Admin UI 하네스 판정기 실행 (`accept frontend`) |
| `make accept-ops-report SUMMARY_JSON=...` | 운영 `summary_json` 커버리지 판정기 실행 (`accept ops-report`) |
| `make dump-ops-report DATE=...` | `operations_day_runs.summary_json` 파일 덤프 — `HARNESS_ALLOW_OPS_DUMP=1` 필요 |
| `make admin-test-one TEST=...` | 단일 Admin UI 테스트 selector 실행 |
| `make heavy-full-test` | 전체 로컬 테스트 실행 — `HARNESS_ALLOW_HEAVY=1` 없이는 차단 |
| `make heavy-docker-test` | Docker 컨테이너에서 전체 테스트 실행 — `HARNESS_ALLOW_HEAVY=1` 없이는 차단 |
| `make heavy-smoke` | smoke 테스트 실행 — `HARNESS_ALLOW_HEAVY=1` 없이는 차단 |
| `make heavy-admin-build` | Admin UI 전체 빌드 — `HARNESS_ALLOW_HEAVY=1` 없이는 차단 |
| `make heavy-admin-test-all` | Admin UI 전체 테스트 — `HARNESS_ALLOW_HEAVY=1` 없이는 차단 |
| `make test` | `make heavy-full-test`의 호환 alias |
| `make lint` | ruff 정적 분석 |
| `make run-api-inmemory` | `bash scripts/harness/run.sh run api-inmemory`의 alias |
| `make run-api-postgres` | 외부 env 로드 후 `bash scripts/harness/run.sh run api-postgres` 실행 |
| `make docker-up` | Docker 서비스 시작 |
| `make docker-down` | Docker 서비스 종료 |
| `make docker-build` | Docker 이미지 빌드 |
| `make docker-migrate` | 마이그레이션 실행 — `bash scripts/harness/docker_compose_env.sh run --rm migrate`의 alias |
| `make docker-test` | `make heavy-docker-test`의 호환 alias |
| `make docker-shell` | Docker 컨테이너 셸 접속 |

`make accept-backend-file`은 import 기반으로 직접 대응 테스트를 찾으며, 테스트가 없으면 실패한다. 불가피한 무테스트 우회는 `HARNESS_ALLOW_NO_TEST=1`을 명시한다.
`make accept-ops-report`는 기본적으로 `failed_count=0`, `timed_out_count=0`을 요구한다. 운영상 허용 범위가 필요한 경우 `HARNESS_OPS_ALLOWED_FAILED_COUNT`, `HARNESS_OPS_ALLOWED_TIMED_OUT_COUNT`를 명시한다.
`make dump-ops-report`는 DB를 조회하므로 기본 차단한다. 필요한 경우 `HARNESS_ALLOW_OPS_DUMP=1`을 명시하고, 출력 파일을 `accept-ops-report`에 전달한다.
전체 테스트, smoke, Admin UI 전체 빌드/테스트는 `make heavy-*` target을 우선 사용한다. 기존 `make full-test`, `make docker-test-safe`, `make smoke-safe`, `make admin-build`, `make admin-test-all`은 호환 alias다.

## CI 검증 기준

GitHub Actions는 사람과 AI가 쓰는 동일한 하네스를 사용한다. 기본 PR/push gate는 [`.github/workflows/harness.yml`](./.github/workflows/harness.yml)에서 `bash scripts/harness/run.sh ...`를 호출하며, 개별 `pytest`, `ruff`, `npm test` 명령을 CI 정답 판정기로 중복 정의하지 않는다.

GitHub ruleset `Require Harness on main`은 기본 브랜치에 `Safe harness contracts` 상태 검사를 필수 항목으로 요구한다.

L4/L5 계층의 전체 테스트, smoke, Admin UI 전체 빌드/테스트는 기본 PR/push에서 실행하지 않고 `workflow_dispatch`와 `HARNESS_ALLOW_HEAVY=1`이 있을 때만 실행한다.

## 환경 재현성 기준

- Python 버전은 [`.python-version`](./.python-version)과 `Dockerfile` 기준으로 고정한다.
- Python 패키지는 [`requirements.lock`](./requirements.lock)을 constraints로 사용한다.
- Node.js 버전은 [`admin_ui/.nvmrc`](./admin_ui/.nvmrc), npm 버전은 [`admin_ui/.npm-version`](./admin_ui/.npm-version) 기준으로 고정한다.
- Admin UI 의존성 설치는 `package-lock.json` 기반 `npm ci`를 사용한다.
- PostgreSQL 서버 버전은 [`.postgres-version`](./.postgres-version) 기준으로 확인한다.
- 환경 기준 검증은 `make accept-env` 또는 `bash scripts/harness/run.sh accept env`를 사용한다. `make env-check`와 `bash scripts/harness/run.sh env-check`는 호환 alias다.
- 운영 비밀값은 저장소 `.env`가 아니라 `/etc/agent_trading/*.env`에 저장하고, Docker/배포 표준 경로는 `bash scripts/harness/docker_compose_env.sh ...`가 이를 읽는다.

## Agent Role Boundaries

현재 멀티 에이전트 설계는 모든 책임을 LLM agent로 구현하는 방향이 아니다. 리스크, 주문 수량, 최종 차단, 정합성 반영은 AI 의견과 deterministic backend 집행을 분리한다.

상세 기준:

- [`docs/00_foundational_design/agents/README.md`](./docs/00_foundational_design/agents/README.md)
- [`docs/00_foundational_design/agents/01_agent_inventory_and_status.md`](./docs/00_foundational_design/agents/01_agent_inventory_and_status.md)
- [`docs/00_foundational_design/agents/02_agent_target_shapes.md`](./docs/00_foundational_design/agents/02_agent_target_shapes.md)
- [`docs/00_foundational_design/agents/03_risk_role_boundaries.md`](./docs/00_foundational_design/agents/03_risk_role_boundaries.md)

---

## 라이선스

내부 프로젝트 — 라이선스 미정
