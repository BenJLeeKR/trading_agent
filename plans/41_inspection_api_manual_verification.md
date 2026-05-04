# Plan 41 — Inspection API Manual Verification Guide / Operator Checklist

> **목적**: Phase 1 read-only inspection API를 Swagger UI 기반으로 사람이 직접 점검하는 절차를 정의한다.
>
> **대상**: 시스템 운영자, 개발자, QA 담당자
>
> **전제 조건**: Plan 40 Phase 1 구현 완료 (in-memory 기본, FastAPI + Swagger UI 활성화)

---

## Revision History

| Rev | 날짜 | 변경 내용 |
|-----|------|-----------|
| 1 | 2026-05-04 | 최초 작성 |
| 2 | 2026-05-04 | Plan 42 반영: Postgres mode 실행 방법 추가, `/health` 응답 변화, 기능적 한계 업데이트 |
| 3 | 2026-05-04 | Plan 43 반영: Docker 실행 절차 추가 (`docker compose up -d db api`) |

---

## 목차

1. [실행 방법](#1-실행-방법)
2. [Swagger UI 접근 방법](#2-swagger-ui-접근-방법)
3. [Endpoint별 확인 포인트](#3-endpoint별-확인-포인트)
4. [운영 체크리스트 시나리오](#4-운영-체크리스트-시나리오)
5. [현재 한계](#5-현재-한계)
6. [다음 단계 연결](#6-다음-단계-연결)

---

## 1. 실행 방법

### 1.1 API 서버 실행

#### In-memory mode (기본)

```bash
# 기본 in-memory 모드로 실행 (추가 설정 불필요)
make run-api
```

또는 직접 uvicorn 실행:

```bash
uvicorn agent_trading.api.app:app --reload --host 0.0.0.0 --port 8000
```

#### Postgres mode (Plan 42+)

```bash
# 1. .env 파일에서 DB 환경 변수 로드
set -a && source .env && set +a

# 2. Postgres mode로 API 실행
# ⚠️ 기본 `app` 인스턴스는 in-memory. Postgres mode는 entry point 변경 필요.
#    아래는 참고용 — 추후 Phase 2에서 환경 변수 기반 전환 추가 예정.
uvicorn agent_trading.api.app:create_app --reload --host 0.0.0.0 --port 8000
```

> **현재 Postgres mode 실행 방법**: `create_app(runtime_mode="postgres")`를 직접 호출하는
> 스크립트 또는 테스트를 통해서만 실행 가능. `make run-api`는 기본 in-memory 모드로 동작.

#### Docker mode (Plan 43+)

```bash
# 1. 이미지 빌드
docker compose build

# 2. DB + API 서비스 기동 (Postgres mode, port 8000)
docker compose up -d db api

# 3. 헬스 체크 (컨테이너 healthcheck 상태 확인)
docker compose ps
# → api 컨테이너가 "(healthy)" 상태여야 정상

# 4. API 로그 확인 (uvicorn access log)
docker compose logs -f api

# 5. API 서버 재시작
make docker-restart-api

# 6. 종료
docker compose down
```

Docker mode(`api` 서비스)의 특징:
- **내부 동작**: `uvicorn agent_trading.api.app:create_app_from_env --factory --host 0.0.0.0 --port 8000`
- `create_app_from_env()`가 `API_RUNTIME_MODE=postgres`를 읽어 Postgres mode로 동작
- `app` 서비스와 동일한 이미지(`build: .`)를 공유하므로 별도 Dockerfile 불필요
- 컨테이너 내부 healthcheck: `127.0.0.1:8000/health/readyz` (Python urllib)
- `start_period: 10s` — DB 연결 + pool 생성 시간 확보

> **참고**: `docker compose up -d`는 모든 서비스(db + app + api)를 기동.
> `docker compose up -d db api`는 dev shell(`app`) 없이 DB + API만 실행.

Postgres mode에서의 내부 동작:
1. **Lifespan startup**: `DatabaseConfig()`로 `.env` 읽기 → `create_pool()`로 asyncpg pool 생성
2. **각 요청마다**: `TransactionManager` 열기 → `build_postgres_repositories(tx)` → repos 사용 후 트랜잭션 정리
3. **Lifespan shutdown**: `close_pool()`로 pool 정리

### 1.2 필요 환경

| 항목 | In-memory mode | Postgres mode |
|------|---------------|---------------|
| Python | >= 3.11 | >= 3.11 |
| 필수 패키지 | `fastapi>=0.110.0`, `uvicorn[standard]>=0.27.0` | 동일 + `asyncpg>=0.29.0` |
| `.env` 파일 | **불필요** | **필수** — `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD` |
| PostgreSQL | **불필요** | **필수** — 실행 중인 PostgreSQL 인스턴스 필요 |
| 초기 데이터 | **없음** | DB 마이그레이션 + 기존 데이터 존재 시 조회 가능 |

### 1.3 서버 종료

```bash
# 실행 중인 터미널에서 Ctrl+C
```

### 1.4 헬스 체크 (서버 기동 확인)

```bash
# 가장 빠른 기동 확인
curl -s http://localhost:8000/health/readyz
# → {"status":"ok"}

# 상세 상태 확인
curl -s http://localhost:8000/health | python3 -m json.tool
```

---

## 2. Swagger UI 접근 방법

| 도구 | URL | 설명 |
|------|-----|------|
| Swagger UI | `http://localhost:8000/docs` | 대화형 API 테스트 UI. "Try it out" 버튼으로 실제 요청 전송 가능 |
| OpenAPI JSON | `http://localhost:8000/openapi.json` | 기계 가독 가능한 API 명세. 코드 생성이나 도구 연동에 사용 |

**Swagger UI 사용 순서**:

1. 브라우저에서 `http://localhost:8000/docs` 열기
2. 각 endpoint 섹션(health, orders, audit, reconciliation, decisions) 확장
3. "Try it out" 클릭 → 파라미터 입력 → "Execute" 클릭
4. 응답 body, status code, 응답 시간 확인

---

## 3. Endpoint별 확인 포인트

### 3.1 `GET /health`

| 항목 | 내용 |
|------|------|
| **목적** | 서버 상태와 데이터베이스 연결 상태 확인 |
| **언제 보는가** | 서버 기동 직후, 장애 발생 시, 정기 상태 점검 |
| **파라미터** | 없음 |
| **정상 시 기대값 (in-memory)** | `{"status":"ok", "version":"...", "database":"in_memory", "runtime_mode":"in_memory"}` |
| **정상 시 기대값 (postgres)** | `{"status":"ok", "version":"...", "database":"connected", "runtime_mode":"postgres"}` |
| **이상 징후** | Postgres mode에서 `database`가 `"disconnected"`인 경우 → DB 연결 불가 |
| **Swagger 테스트** | `/docs` → `GET /health` → Try it out → Execute |

### 3.2 `GET /health/readyz`

| 항목 | 내용 |
|------|------|
| **목적** | Kubernetes readiness probe. 서버가 요청을 받을 준비가 되었는지 확인 |
| **언제 보는가** | 배포 직후, 컨테이너 재시작 후 |
| **파라미터** | 없음 |
| **정상 시 기대값** | `{"status":"ok"}` |
| **이상 징후** | 응답 없음(5xx/시간 초과) → 서버 자체가 응답 불가 상태 |
| **Swagger 테스트** | `/docs` → `GET /health/readyz` → Try it out → Execute |

### 3.3 `GET /orders`

| 항목 | 내용 |
|------|------|
| **목적** | 전체 주문 목록 조회 (필터링 가능) |
| **언제 보는가** | 시스템에 주문이 있는지 확인할 때, 특정 계좌/상태의 주문을 찾을 때 |
| **파라미터** | `account_id`(선택), `client_order_id`(선택), `status`(선택), `limit`(기본 100, 최대 1000) |
| **정렬 기준** | `created_at` **내림차순** (가장 최근 주문이 먼저) |
| **빈 응답** | `[]` — 데이터가 없으면 빈 배열 반환 |
| **정상 시 기대값** | `[{"order_request_id":"...", "side":"buy", "order_type":"limit", "status":"acknowledged", ...}]` |
| **이상 징후** | 500 에러, 예상보다 적은/많은 결과, 정렬 순서가 바뀐 경우 |
| **Swagger 테스트** | `/docs` → `GET /orders` → Try it out → limit=10 → Execute |

### 3.4 `GET /orders/{order_request_id}`

| 항목 | 내용 |
|------|------|
| **목적** | 특정 주문의 상세 정보 조회 (OrderSummary + instrument_id, time_in_force 등) |
| **언제 보는가** | 특정 주문의 전체 상태를 확인할 때 |
| **파라미터** | `order_request_id` (UUID, path parameter) |
| **정상 시 기대값** | OrderDetail 객체 (instrument_id, status_reason_code, submitted_at, time_in_force 포함) |
| **오류 응답** | `400` — UUID 형식이 잘못된 경우, `404` — 존재하지 않는 ID |
| **주의** | `time_in_force`는 enum 값(소문자, 예: `"day"`)으로 반환 |
| **Swagger 테스트** | `/docs` → `GET /orders/{order_request_id}` → 유효한 UUID 입력 → Execute |

### 3.5 `GET /orders/{order_request_id}/events`

| 항목 | 내용 |
|------|------|
| **목적** | 특정 주문의 상태 전이 이력 조회 |
| **언제 보는가** | 주문이 어떤 경로로 현재 상태에 도달했는지 추적할 때 |
| **파라미터** | `order_request_id` (UUID, path parameter) |
| **정렬 기준** | `event_timestamp` **오름차순** (가장 오래된 이벤트가 먼저) |
| **정상 시 기대값** | `[{"previous_status":null, "new_status":"pending_submit", "event_source":"internal", ...}, {"previous_status":"pending_submit", "new_status":"submitted", "event_source":"broker_rest", ...}]` |
| **이상 징후** | 이벤트가 하나도 없는 경우(비정상), 예상치 못한 상태 전이, 중복 이벤트 |
| **주요 활용** | 불명확 상태(submit 후 ambiguous) 발생 시 원인 추적 |
| **Swagger 테스트** | `/docs` → `GET /orders/{order_request_id}/events` → 유효한 UUID 입력 → Execute |

### 3.6 `GET /audit-logs`

| 항목 | 내용 |
|------|------|
| **목적** | 감사 로그 조회. 특정 `correlation_id`로 필터링하여 작업 추적 |
| **언제 보는가** | 특정 트랜잭션의 전체 audit trail 확인. 누가, 언제, 무엇을 변경했는지 추적 |
| **파라미터** | `correlation_id` (필수, string) |
| **정렬 기준** | `created_at` **오름차순** (가장 먼저 기록된 로그부터) |
| **정상 시 기대값** | `[{"audit_log_id":"...", "actor_type":"system", "action":"order.created", "target_entity_type":"order", ...}]` |
| **오류 응답** | `422` — `correlation_id` 누락 시 |
| **이상 징후** | 빈 배열(로그가 아직 기록되지 않음). 예상되는 액션이 누락된 경우 |
| **활용 팁** | 주문의 `correlation_id`를 복사하여 이 endpoint에 전달하면 해당 주문 관련 모든 audit 로그 확인 가능 |
| **Swagger 테스트** | `/docs` → `GET /audit-logs` → correlation_id 입력 → Execute |

### 3.7 `GET /reconciliation/runs`

| 항목 | 내용 |
|------|------|
| **목적** | 특정 계좌의 reconciliation 실행 이력 조회 |
| **언제 보는가** | 불명확 상태(submit 실패/ambiguous)가 발생했을 때 reconciliation이 실행되었는지, 결과는 무엇인지 확인 |
| **파라미터** | `account_id` (필수, UUID), `limit` (선택, 기본 20, 최대 100) |
| **정렬 기준** | `started_at` **내림차순** (가장 최근 실행이 먼저) |
| **정상 시 기대값** | `[{"trigger_type":"post_submit", "status":"started", "mismatch_count":0, ...}]` |
| **오류 응답** | `422` — `account_id` 누락 시 |
| **이상 징후** | `mismatch_count > 0` — 불일치 발생. `status`가 `completed`가 아닌 경우 |
| **Swagger 테스트** | `/docs` → `GET /reconciliation/runs` → account_id(UUID) 입력 → Execute |

### 3.8 `GET /reconciliation/locks`

| 항목 | 내용 |
|------|------|
| **목적** | 계좌별 활성 blocking lock 조회 |
| **언제 보는가** | 새 주문이 제출되지 않는 원인 진단. reconciliation lock이 남아 있는지 확인 |
| **파라미터** | `account_id` (필수, UUID) |
| **정상 시 기대값** | `[]` — lock이 없으면 빈 배열. lock이 있으면 `[{"reason":"reconciliation", "locked_by_run_id":"...", "expires_at":"...", ...}]` |
| **오류 응답** | `422` — `account_id` 누락 시, `400` — UUID 형식 오류 |
| **이상 징후** | 오래된 lock이 해제되지 않고 남아 있는 경우 → 수동 조치 필요 |
| **참고** | 현재 in-memory 전용. Postgres 모드에서는 항상 `[]` 반환 |
| **Swagger 테스트** | `/docs` → `GET /reconciliation/locks` → account_id(UUID) 입력 → Execute |

### 3.9 `GET /trade-decisions`

| 항목 | 내용 |
|------|------|
| **목적** | 특정 decision context에 속한 trade decision 조회 |
| **언제 보는가** | AI agent가 어떤 결정(approve/reject 등)을 내렸는지 확인할 때 |
| **파라미터** | `decision_context_id` (필수, UUID) |
| **정상 시 기대값** | 0~1개 항목. `[{"decision_type":"approve", "side":"buy", "symbol":"AAPL", "entry_style":"limit", ...}]` |
| **빈 응답** | `[]` — 해당 decision context에 결정이 없음 |
| **이상 징후** | `decision_type`이 `approve`가 아닌 경우(reject/watch/hold), 예상되는 결정이 없는 경우 |
| **활용 팁** | decision-contexts/{id}에서 조회한 ID를 여기에 전달하여 결정 내용 확인 가능 |
| **Swagger 테스트** | `/docs` → `GET /trade-decisions` → decision_context_id(UUID) 입력 → Execute |

### 3.10 `GET /decision-contexts/{decision_context_id}`

| 항목 | 내용 |
|------|------|
| **목적** | 특정 decision context의 상세 정보 조회 |
| **언제 보는가** | AI 의사결정이 어떤 맥락에서 이루어졌는지 확인할 때 (계좌, 전략, 설정 버전 등) |
| **파라미터** | `decision_context_id` (UUID, path parameter) |
| **정상 시 기대값** | `{"strategy_id":"...", "config_version_id":"...", "market_timestamp":"...", "correlation_id":"...", ...}` |
| **오류 응답** | `400` — UUID 형식 오류, `404` — 존재하지 않는 ID |
| **이상 징후** | `market_timestamp`가 비정상적으로 오래된 경우 (데이터 신선도 문제) |
| **Swagger 테스트** | `/docs` → `GET /decision-contexts/{decision_context_id}` → 유효한 UUID 입력 → Execute |

---

## 4. 운영 체크리스트 시나리오

각 시나리오는 Swagger UI 또는 `curl`로 실행할 수 있다. **(1)~(2)는 모든 점검의 전제 조건**이므로 항상 먼저 수행한다.

### 시나리오 1: 서버 기동 확인

```bash
# Step 1: readyz — 서버가 요청을 받을 수 있는지 확인
curl -s http://localhost:8000/health/readyz
# 기대: {"status":"ok"}

# Step 2: /health — 상세 상태 확인
curl -s http://localhost:8000/health | python3 -m json.tool
# 기대: status="ok", database="in_memory"

# Step 3: Swagger UI 접근 확인
# 브라우저에서 http://localhost:8000/docs 열기
# 10개 endpoint가 모두 표시되는지 확인
```

**판단**:
- `readyz`가 `{"status":"ok"}`가 아니면 → 서버 프로세스 확인 (`make run-api` 재실행)
- Swagger UI가 열리지 않으면 → 포트 충돌 확인 (`lsof -i :8000`)

---

### 시나리오 2: 주문 존재 여부 확인

```bash
# 전체 주문 목록 조회 (최대 10개)
curl -s "http://localhost:8000/orders?limit=10" | python3 -m json.tool

# 빈 응답일 경우 (시스템에 아직 주문 없음)
# 기대: []
```

**판단**:
- `[]` → 시스템이 아직 주문을 생성하지 않음 (정상, 서버 문제 아님)
- 데이터가 있으면 → `status` 필드로 현재 상태 확인
- 500 에러 → 서버 로그 확인

**Swagger UI** → `/orders` → Try it out → limit=10 → Execute

---

### 시나리오 3: 특정 주문의 상태 전이 이력 확인

```flow
1. GET /orders         → 주문 목록에서 대상 order_request_id 복사
2. GET /orders/{id}    → 주문 상세 정보 확인
3. GET /orders/{id}/events → 상태 전이 이력 확인
```

**확인 포인트**:
- 이벤트가 최소 1개 이상 존재하는가
- 이벤트가 `event_timestamp` 오름차순으로 정렬되어 있는가
- `new_status` 값이 현재 주문 상태와 일치하는가
- 예상치 못한 상태 전이(예: `draft` → `filled` 직행)가 없는가

**이상 징후 예시**:
```json
// 이벤트가 하나도 없음 — 비정상. 이벤트 저장 실패 의심
[]

// 상태 전이가 비정상적으로 짧거나 누락됨
// (ACKNOWLEDGED 없이 바로 PARTIALLY_FILLED)
```

**Swagger UI**: `/orders/{order_request_id}/events` → Try it out → UUID 입력 → Execute

---

### 시나리오 4: 불명확 상태 확인 — Reconciliation Run 조회

```flow
1. GET /orders         → 주문 목록에서 status=failed 또는 reconcile_required 확인
2. GET /orders/{id}    → 대상 주문의 account_id 확인
3. GET /reconciliation/runs?account_id={id} → reconciliation 실행 이력 조회
```

**확인 포인트**:
- reconciliation run이 존재하는가 (리스트가 비어 있지 않은가)
- `trigger_type`이 `post_submit`인가 (의도된 트리거)
- `status`가 `completed`인가 (실행 완료)
- `mismatch_count`가 0보다 큰가 (불일치 발견)

**이상 징후 예시**:
```json
// reconciliation이 실행되지 않음 — 문제 발생 가능
[]

// 불일치가 발견됨
{"mismatch_count": 2, "status": "completed"}
```

**Swagger UI**: `/reconciliation/runs` → Try it out → account_id(UUID) 입력 → Execute

---

### 시나리오 5: Blocking Lock 잔존 확인

```flow
1. GET /orders                     → 주문 목록 조회
2. (주문의 account_id 확인)
3. GET /reconciliation/locks?account_id={id} → blocking lock 확인
```

**확인 포인트**:
- lock 리스트가 비어 있는가 (`[]`) → 정상
- lock이 존재하는가 → active lock이 있으면 새 주문 제출 차단 가능
- `reason` 필드 확인: `"reconciliation"`  → reconciliation 진행 중
- `expires_at` 확인: 이미 만료되었지만 lock이 남아 있으면 수동 정리 필요

**이상 징후 예시**:
```json
// 오래된 lock이 해제되지 않음 — 수동 조치 필요
[{"reason": "reconciliation", "locked_by_run_id": "...", "expires_at": "..."}]
```

**Swagger UI**: `/reconciliation/locks` → Try it out → account_id(UUID) 입력 → Execute

---

### 시나리오 6: Audit Log로 상태 변경 추적

```flow
1. GET /orders              → 주문 목록에서 correlation_id 확인
2. GET /audit-logs?correlation_id={id} → audit 로그 조회
```

**확인 포인트**:
- audit 로그가 존재하는가
- `action` 값이 예상 workflow와 일치하는가 (예: `order.created` → `order.submitted` → `order.acknowledged`)
- `actor_type`/`actor_id`가 정확한가 (누가 변경을 수행했는가)
- `before_json`/`after_json`이 있는 경우 → 이전/이후 상태 비교 가능

**이상 징후 예시**:
```json
// audit 로그가 없음 — audit 저장 실패 의심
[]

// 예상되는 액션 순서와 다름 (예: acknowledged 없이 filled)
```

**Swagger UI**: `/audit-logs` → Try it out → correlation_id 입력 → Execute

---

### 시나리오 7: Trade Decision / Decision Context 참조 경로 확인

```flow
1. GET /orders/{id}                        → trade_decision_id 확인
2. (trade_decision_id로 decision_context 역추적 불가 — 직접 경로 불명)
   GET /trade-decisions?decision_context_id={id} → trade decision 조회
3. GET /decision-contexts/{id}             → decision context 상세 조회
```

**확인 포인트**:
- trade decision이 존재하는가 (`[]` 아니면 정상)
- `decision_type`이 무엇인가 (`approve`, `reject`, `hold`, `watch`, `exit`, `reduce`)
- decision context의 `market_timestamp`가 적절한가
- decision context가 어떤 `strategy_id` / `config_version_id`를 참조하는가

**이상 징후 예시**:
```json
// decision_context_id에 해당하는 trade decision이 없음
// → AI agent가 결정을 내리지 않았거나 저장 실패
[]

// decision_type이 "reject" 또는 "hold" — 주문이 생성되지 않은 이유 설명 가능
[{"decision_type": "reject", "symbol": "AAPL", ...}]
```

**Swagger UI**:
- `/trade-decisions` → Try it out → decision_context_id 입력 → Execute
- `/decision-contexts/{decision_context_id}` → Try it out → UUID 입력 → Execute

---

## 5. 현재 한계

### 5.1 기능적 한계

| 항목 | 상태 | 영향 |
|------|------|------|
| **Write API** | ❌ 없음 | 데이터 조회만 가능. 주문 생성/수정/취소 불가 |
| **Admin UI** | ❌ 없음 | Swagger UI가 유일한 operator interface. 시각화/대시보드 없음 |
| **인증/인가** | ❌ 없음 | 모든 endpoint가 인증 없이 접근 가능. 운영망에 노출 시 보안 위험 |
| **Postgres API 모드** | ✅ Plan 42 | `create_app(runtime_mode="postgres")`로 Postgres 데이터 조회 가능. 단, `make run-api`는 기본 in-memory 모드 |
| **페이징** | ❌ Phase 2 | `limit` 파라미터만 존재. cursor/token 기반 페이징 없음 |
| **정렬 커스터마이징** | ❌ 고정 | 각 endpoint의 정렬 기준이 고정되어 있음 (`/audit-logs`는 내림차순으로 고정된 것으로 보이나 실제로는 오름차순) |
| **KIS submit 관측** | ⚠️ 제한적 | 주문 상태는 조회 가능하지만 브로커 응답 원문은 `broker_api_call_log`에 저장되어 아직 API로 노출되지 않음 |
| **`trade_decisions.decision`** | ⚠️ 미노출 | legacy column은 API 응답에 포함되지 않음 (nullable로 전환 완료) |
| **Reconciliation lock in Postgres** | ⚠️ In-memory 전용 | Postgres 모드에서는 항상 빈 리스트 반환 |

### 5.2 운영상 한계

- **Persistent 저장 없음**: 서버 재시작 시 모든 in-memory 데이터 소멸. Postgres 연동 시점까지는 실 데이터 조회 불가
- **동시성**: 단일 프로세스/단일 스레드(uvicorn 기본). 대량 요청 시 성능 저하 가능
- **로깅/모니터링**: 별도의 request logging, metrics 수집 없음

---

## 6. 다음 단계 연결

### 6.1 Phase 2 Endpoint 후보

다음 endpoint들은 Phase 2에서 확장 예정이다 (`BACKLOG.md` Near-term #1 참조):

| Endpoint | 설명 | BACKLOG 링크 |
|----------|------|-------------|
| `GET /accounts` | 계좌 목록 조회 | [`BACKLOG.md`](BACKLOG.md:22) |
| `GET /positions` | 포지션 스냅샷 조회 | [`BACKLOG.md`](BACKLOG.md:22) |
| `GET /cash-balances` | 현금 잔고 조회 | [`BACKLOG.md`](BACKLOG.md:22) |
| `GET /guardrail-evaluations` | 가드레일 평가 결과 조회 | [`BACKLOG.md`](BACKLOG.md:22) |
| `GET /risk-limit-snapshots` | 리스크 한도 스냅샷 조회 | [`BACKLOG.md`](BACKLOG.md:22) |
| `GET /broker-orders` | 브로커 주문 조회 | [`BACKLOG.md`](BACKLOG.md:22) |
| `GET /agent-runs` | AI agent 실행 이력 조회 | [`BACKLOG.md`](BACKLOG.md:22) |

### 6.2 Admin UI로의 전환

Admin UI가 도입되면 (`BACKLOG.md` Medium-term #1):

- 이 가이드의 체크리스트 시나리오가 Admin UI의 대시보드/위젯으로 대체됨
- Swagger UI는 개발자용 디버깅 도구로 유지
- 운영 체크리스트는 Admin UI의 "Health Check" 페이지 또는 "System Status" 페이지로 이전

### 6.3 BACKLOG 항목 연결

| BACKLOG 항목 | 연관성 |
|-------------|--------|
| [Phase 2 API endpoints](BACKLOG.md:22) | 이 가이드의 endpoint별 확인 포인트 확장 |
| [Postgres-backed API mode](BACKLOG.md:23) | ✅ **Plan 42로 구현 완료**. `database` 필드가 `"connected"` 또는 `"disconnected"`로 표시. `runtime_mode`가 `"postgres"`로 설정됨. |
| [Auth/RBAC](BACKLOG.md:35) | 인증 추가 시 모든 endpoint에 Authorization header 필요 |
| [Admin UI](BACKLOG.md:34) | 이 가이드의 체크리스트 시나리오가 UI 대시보드로 대체 |
| [Operator intervention](BACKLOG.md:36) | write API 추가 시 이 가이드에 수동 조치 절차 추가 필요 |
| [Reconciliation lock list API](BACKLOG.md:24) | Postgres 모드에서 lock 조회가 가능해지면 이 가이드 업데이트 |

---

## Appendix: curl 명령어 모음

```bash
# 1. 서버 상태
curl -s http://localhost:8000/health/readyz
curl -s http://localhost:8000/health | python3 -m json.tool

# 2. 주문 조회
curl -s "http://localhost:8000/orders?limit=5" | python3 -m json.tool
curl -s "http://localhost:8000/orders/{UUID}/events" | python3 -m json.tool

# 3. 감사 로그
curl -s "http://localhost:8000/audit-logs?correlation_id={CORR_ID}" | python3 -m json.tool

# 4. Reconciliation
curl -s "http://localhost:8000/reconciliation/runs?account_id={UUID}" | python3 -m json.tool
curl -s "http://localhost:8000/reconciliation/locks?account_id={UUID}" | python3 -m json.tool

# 5. Decisions
curl -s "http://localhost:8000/trade-decisions?decision_context_id={UUID}" | python3 -m json.tool
curl -s "http://localhost:8000/decision-contexts/{UUID}" | python3 -m json.tool
```
