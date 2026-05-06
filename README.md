# Agent Trading System

AI 멀티 에이전트 매매 시스템 — PostgreSQL 기반 주문 저장/조회 엔진.

> **현재 상태**: MVP 마일스톤 1 완료 (53 tests passing).  
> PostgreSQL 저장소 구현을 바로 시작할 수 있는 개발 환경이 준비되어 있습니다.

---

## 요구사항

- **Python** 3.11 이상
- **Docker** (선택사항 — PostgreSQL 컨테이너 실행용)
- **PostgreSQL** 16 (Docker 미사용 시 로컬 설치 필요)

---

## 빠른 시작 (로컬)

### 1. 가상환경 생성 및 의존성 설치

```bash
python -m venv .venv
source .venv/bin/activate
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

### 1. 빌드 및 실행

```bash
docker compose up -d
```

### 2. 마이그레이션

```bash
make docker-migrate
```

### 3. 테스트

```bash
make docker-test
```

### 4. 셸 접속

```bash
make docker-shell
```

### 5. 종료

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

[`docker-compose.yml`](docker-compose.yml:82-89)은 이미 올바른 방식(`create_app_from_env --factory`)을 사용하고 있습니다.

---

## 프로젝트 구조

```
├── pyproject.toml              # 프로젝트 정의 + 의존성
├── Dockerfile                  # 앱 컨테이너
├── docker-compose.yml          # PostgreSQL + App
├── Makefile                    # 태스크 실행기
├── .env.example                # 환경변수 템플릿
├── .gitignore
├── README.md
│
├── db/
│   └── migrations/
│       └── 0001_initial_schema.sql   # 초기 스키마 (24개 테이블)
│
├── src/
│   └── agent_trading/
│       ├── main.py                   # 앱 진입점
│       ├── db/                       # DB 연결 계층
│       │   ├── connection.py         #   asyncpg pool + DatabaseConfig
│       │   ├── transaction.py        #   TransactionManager (UnitOfWork)
│       │   ├── row_mapper.py         #   Record ↔ Entity 변환
│       │   └── migrations/run.py     #   SQL migration 실행기
│       ├── domain/                   # 도메인 모델 (변경 금지)
│       │   ├── entities.py           #   17개 dataclass entities
│       │   ├── enums.py              #   OrderStatus, OrderSide 등
│       │   └── models.py             #   SubmitOrderRequest 등
│       ├── repositories/             # 저장소 계층
│       │   ├── contracts.py          #   Protocol interfaces (변경 금지)
│       │   ├── memory.py             #   In-memory 구현
│       │   ├── postgres/             #   PostgreSQL 구현
│       │   └── ...
│       ├── services/
│       │   └── order_manager.py      #   주문 상태 전이 + idempotency
│       ├── brokers/                  # 브로커 어댑터 (KIS stub)
│       └── runtime/
│           └── bootstrap.py          #   Runtime 조립
│
└── tests/
    ├── conftest.py                   # 공통 fixture
    ├── repositories/                 # Repository contract tests
    ├── services/                     # 상태 전이 + idempotency tests
    └── smoke/                        # End-to-end smoke tests
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
| `make test` | 로컬 테스트 실행 |
| `make lint` | ruff 정적 분석 |
| `make run-api-inmemory` | Inspection API 실행 (in-memory, auth 비활성, module-level `app`) |
| `make run-api-postgres` | Inspection API 실행 (Postgres, auth 활성, `create_app_from_env --factory`, `.env` 필요) |
| `make docker-up` | Docker 서비스 시작 |
| `make docker-down` | Docker 서비스 종료 |
| `make docker-build` | Docker 이미지 빌드 |
| `make docker-migrate` | Docker 컨테이너에서 마이그레이션 |
| `make docker-test` | Docker 컨테이너에서 테스트 |
| `make docker-shell` | Docker 컨테이너 셸 접속 |

---

## 다음 단계

현재 MVP 마일스톤 1이 완료된 상태입니다. 다음으로 진행할 수 있는 작업:

1. **Milestone 2**: PostgreSQL 실제 연결 통합 테스트 + KIS Adapter 실제 API 연동
2. **PostgreSQL Repository 구현**: `PostgresClientRepository` 등 실제 DB 연동 코드
3. **Paper Trading Loop**: OrderManager + BrokerAdapter + Repository 조합

---

## 라이선스

내부 프로젝트 — 라이선스 미정
