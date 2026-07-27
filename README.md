# Agent Trading System

멀티 에이전트 트레이딩 시스템 — PostgreSQL 기반 주문 저장/조회 엔진.

## 작업 지침

이 README는 프로젝트 설치와 실행 안내를 담당한다. 에이전트 작업 규칙과 Harness Engineering 원칙은 다음 문서를 우선한다.

- [`AGENTS.md`](./AGENTS.md): Codex 및 공통 에이전트 작업 규칙
- [`CLAUDE.md`](./CLAUDE.md): Claude Code용 지침 라우터
- [`docs/99_meta_handover/agent_workspace_guide.md`](./docs/99_meta_handover/agent_workspace_guide.md): 작업 방식과 문서 분리 기준

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
docker compose up -d db
```

또는 로컬 PostgreSQL에서 직접 `trading` 데이터베이스와 사용자를 생성:

```sql
CREATE USER trading WITH PASSWORD 'trading';
CREATE DATABASE trading OWNER trading;
```

### 4. 마이그레이션 실행

```bash
make migrate
```

성공 시 `trading` 스키마에 24개 테이블이 생성됩니다.

### 5. 테스트 실행

```bash
make test
```

예상 결과: **53 passed, 0 failed, 0 errors**

---

## Docker 환경

> **⚠️ `api` 컨테이너는 기동 시 더 이상 자동으로 DB migration을 실행하지 않습니다.**
> "api 재기동"과 "DB migration 실행"은 분리된 절차입니다 — migration은 아래처럼
> 명시적으로 먼저 실행한 뒤 `api`를 올려야 합니다.

### 1. 빌드

```bash
docker compose build
```

### 2. 마이그레이션 (api보다 먼저 실행)

**표준 경로**는 `docker-compose.yml`의 one-shot `migrate` service입니다 —
`api`와 동일한 `DATABASE_*` 환경변수를 재사용하며, migration만 실행하고
종료됩니다:

```bash
docker compose run --rm migrate
```

`make docker-migrate`는 위 명령의 convenience alias입니다(내부적으로 동일한
`docker compose run --rm migrate`를 호출합니다) — 별도의 실행 경로가 아닙니다:

```bash
make docker-migrate
```

성공(exit code 0)을 확인한 뒤에만 다음 단계로 진행하세요.

### 3. 서비스 기동

```bash
docker compose up -d
# 또는 api만: docker compose up -d api
```

`migrate` 서비스는 `profiles: [migrate]`로 분리돼 있어 `docker compose up -d`
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
| In-memory (개발용) | `make run-api-inmemory` | ❌ (in-memory mock) | ❌ (비활성) | 무시됨 |
| Postgres (운영용) | `make run-api-postgres` | ✅ PostgreSQL | ✅ Bearer token | `API_RUNTIME_MODE`, `INSPECTION_API_TOKEN` |

### ⚠️ 잘못된 실행 방식 — 항상 in-memory

```bash
# ❌ 아래 방식은 INSPECTION_API_TOKEN을 설정해도 in_memory 모드로 실행됩니다.
#    module-level app = create_app(auth_enabled=False) 가 고정되어 있기 때문입니다.
uvicorn agent_trading.api.app:app --reload --host 0.0.0.0 --port 9000

# ❌ 환경변수를 줘도 module-level app은 읽지 않습니다.
INSPECTION_API_TOKEN=dev-token-123 \
uvicorn agent_trading.api.app:app --reload --host 0.0.0.0 --port 9000

# ❌ API_RUNTIME_MODE=postgres 도 마찬가지로 무시됩니다.
API_RUNTIME_MODE=postgres INSPECTION_API_TOKEN=dev-token-123 \
uvicorn agent_trading.api.app:app --reload --host 0.0.0.0 --port 9000
```

### ✅ 올바른 실행 방식 — Postgres + Auth

`create_app_from_env`를 `--factory` 플래그와 함께 사용해야 환경변수가 적용됩니다.

```bash
# 1. .env 파일에서 DATABASE_* 환경변수 로드 (PostgreSQL 연결 정보)
source .env

# 2. Postgres-backed 모드로 실행
API_RUNTIME_MODE=postgres \
INSPECTION_API_TOKEN=dev-token-123 \
uvicorn agent_trading.api.app:create_app_from_env --factory --reload --host 0.0.0.0 --port 9000

# 또는 Makefile target 사용 (DATABASE_* 는 .env 또는 export 필요)
make run-api-postgres
```

> **참고**: `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD` 환경변수가 설정되어 있어야 Postgres 모드가 정상 동작합니다. `.env` 파일을 통해 로드하거나 직접 export 하세요.

### Docker Compose (권장)

```bash
docker compose up -d db api
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
| `make install` | 의존성 설치 (`pip install -e ".[dev]"`) |
| `make run` | 앱 실행 |
| `make migrate` | 로컬 마이그레이션 실행 |
| `make harness-status` | 하네스 기준 프로젝트 상태 확인 |
| `make env-check` | 운영 기준 Python/Node/npm/PostgreSQL 버전과 환경 템플릿 확인 |
| `make check-file FILE=...` | 단일 Python 파일 컴파일 확인 |
| `make test-one TEST=...` | 단일 pytest 테스트 실행 |
| `make test-file TEST=...` | 단일 pytest 파일 실행 |
| `make lint-path TARGET=...` | 지정 경로 ruff 정적 분석 |
| `make docs-check` | 핵심 문서 링크 검증 |
| `make accept-docs` | 핵심 문서 하네스 판정기 실행 |
| `make accept-env` | 운영 환경 재현성 하네스 판정기 실행 |
| `make accept-backend-file FILE=...` | 단일 백엔드 Python 파일 하네스 판정기 실행 |
| `make accept-backend-runtime` | 백엔드 런타임 import/factory 계약 판정기 실행 |
| `make accept-admin-ui` | Admin UI 하네스 판정기 실행 (`accept frontend`) |
| `make accept-ops-report SUMMARY_JSON=...` | 운영 `summary_json` 커버리지 판정기 실행 (`accept ops-report`) |
| `make admin-test-one TEST=...` | 단일 Admin UI 테스트 selector 실행 |
| `make test` | 전체 로컬 테스트 실행 — `HARNESS_ALLOW_HEAVY=1` 없이는 차단 |
| `make lint` | ruff 정적 분석 |
| `make run-api-inmemory` | Inspection API 실행 (in-memory, auth 비활성, module-level `app`) |
| `make run-api-postgres` | Inspection API 실행 (Postgres, auth 활성, `create_app_from_env --factory`, `.env` 필요) |
| `make docker-up` | Docker 서비스 시작 |
| `make docker-down` | Docker 서비스 종료 |
| `make docker-build` | Docker 이미지 빌드 |
| `make docker-migrate` | 마이그레이션 실행 — `docker compose run --rm migrate`의 alias (표준 경로는 `docker compose run --rm migrate` 자체) |
| `make docker-test` | Docker 컨테이너에서 전체 테스트 실행 — `HARNESS_ALLOW_HEAVY=1` 없이는 차단 |
| `make docker-shell` | Docker 컨테이너 셸 접속 |

`make accept-backend-file`은 import 기반으로 직접 대응 테스트를 찾으며, 테스트가 없으면 실패한다. 불가피한 무테스트 우회는 `HARNESS_ALLOW_NO_TEST=1`을 명시한다.

## 환경 재현성 기준

- Python 버전은 [`.python-version`](./.python-version)과 `Dockerfile` 기준으로 고정한다.
- Python 패키지는 [`requirements.lock`](./requirements.lock)을 constraints로 사용한다.
- Node.js 버전은 [`admin_ui/.nvmrc`](./admin_ui/.nvmrc), npm 버전은 [`admin_ui/.npm-version`](./admin_ui/.npm-version) 기준으로 고정한다.
- Admin UI 의존성 설치는 `package-lock.json` 기반 `npm ci`를 사용한다.
- PostgreSQL 서버 버전은 [`.postgres-version`](./.postgres-version) 기준으로 확인한다.
- 환경 기준 검증은 `make env-check` 또는 `bash scripts/harness/run.sh env-check`를 사용한다.

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
