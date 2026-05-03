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

> **호환성**: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` 도 지원하지만
> `DATABASE_*` prefix가 우선합니다.

---

## Make 명령어

| 명령어 | 설명 |
|--------|------|
| `make install` | 의존성 설치 (`pip install -e ".[dev]"`) |
| `make run` | 앱 실행 |
| `make migrate` | 로컬 마이그레이션 실행 |
| `make test` | 로컬 테스트 실행 |
| `make lint` | ruff 정적 분석 |
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
