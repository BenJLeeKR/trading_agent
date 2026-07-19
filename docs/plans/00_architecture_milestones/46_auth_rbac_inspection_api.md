# Plan 46 — Auth / RBAC for Inspection API

**Date:** 2026-05-04  
**Status:** Draft  
**Designer:** Architect

---

## Revision History

| Rev | Date | Author | Changes |
|-----|------|--------|---------|
| 1.0 | 2026-05-04 | Architect | Initial draft |
| 1.1 | 2026-05-04 | Architect | 기본값 auth-enabled 전환, 명시적 disable만 허용, create_app_from_env startup fail |

---

## 1. Why Now

현재 inspection API는 인증/인가 없이 모든 endpoint에 접근 가능한 상태다.
orders / audit-logs / reconciliation / trade-decisions 등 운영 민감 정보를
노출하고 있으므로, **최소한의 운영 보안 경계**를 추가해야 한다.

**목표:** read-only inspection API의 현재 성격은 유지하되,
"운용자가 열어도 되는 수준"의 기본 보안 경계를 만든다.

---

## 2. 설계 원칙

1. **작고 교체 가능한 auth layer** — 완전한 IAM이 아니라, 현재 단계에 맞는 최소한의 인증
2. **Future-proof** — 향후 JWT/OIDC로 교체 가능해야 함
3. **Swagger-friendly** — `/docs`에서 Authorize 버튼으로 쉽게 테스트 가능
4. **Test compatibility with explicit opt-out** — 기존 테스트는 `auth_enabled=False` 명시적 전달로 무인증 유지
5. **Safe default** — `auth_enabled=True`가 기본값, production에서 무방비 노출 방지
6. **Read-only 유지** — inspection API의 read-only 성격 변경 없음

---

## 3. 인증 방식: Static Bearer Token

### 3.1 선택 이유

| 방식 | 장점 | 단점 |
|------|------|------|
| **Static Bearer Token** ✅ | Swagger Authorize 지원, 프록시 친화적, JWT 교체 용이 | token rotation 어려움 |
| Basic Auth | 구현 단순 | Base64 인코딩만, Swagger에서 덜 직관적 |
| API Key Header | 간단함 | Swagger에서 표준 scheme 아님 |
| OAuth/OIDC | 완전한 IAM | **현재 단계에서 과함** |

### 3.2 동작 방식

```
Authorization: Bearer <INSPECTION_API_TOKEN>
```

- token 값은 환경 변수 `INSPECTION_API_TOKEN`에서 읽음
- `create_app()`에 `auth_token: str | None` 파라미터로 전달
- `create_app_from_env()`에서 env var → `create_app()` 전달

### 3.3 Token 미설치 정책 — Safe Default

**원칙:** `auth_enabled=True`가 기본값이며, token이 없으면 auth-on 상태에서 동작할 수 없으므로
startup fail 처리한다. 무인증 허용은 호출자가 명시적으로 `auth_enabled=False`를 선언할 때만 가능하다.

| 경로 | 동작 |
|------|------|
| `create_app(auth_enabled=True, auth_token=None)` | **Startup fail** — `ValueError` 발생 (안전 기본값) |
| `create_app(auth_enabled=True, auth_token="...")` | 정상 동작 |
| `create_app(auth_enabled=False)` | **무인증 허용** (개발/테스트 전용) |
| `create_app_from_env()` (운영) | `INSPECTION_API_TOKEN` 미설정 시 **startup fail** |
| 기존 테스트 fixture (`client`, `empty_client`) | `create_app(auth_enabled=False)`로 명시적 무인증 |

> **설계 이유:** "테스트 호환"을 이유로 production default를 약하게 만들지 않는다.
> 무인증이 필요한 테스트는 명시적으로 `auth_enabled=False`를 전달해야 한다.

---

## 4. 최소 RBAC 모델

### 4.1 역할 정의

| 역할 | 권한 | 비고 |
|------|------|------|
| `viewer` | 모든 read-only inspection endpoint 접근 | **이번 Phase의 실질적 역할** |
| `admin` | Reserved — 향후 write/admin endpoint 대비 | 구조만 정의, 현재는 `viewer`와 동일한 접근 |

### 4.2 역할 할당

- `INSPECTION_API_ROLE` 환경 변수로 설정 (기본값: `viewer`)
- 현재 Phase에서는 모든 보호 endpoint가 `viewer` 역할 이상이면 접근 가능
- `admin` 역할은 향후 `require_admin()` dependency에서 사용 예정

---

## 5. 공개/보호 Endpoint 정책

### 5.1 공개 허용 (Public)

| Endpoint | 이유 |
|----------|------|
| `GET /health` | Load balancer / k8s probe |
| `GET /health/readyz` | Readiness probe |
| `GET /docs` | Swagger UI — 운영 편의상 공개 |
| `GET /openapi.json` | OpenAPI spec 조회 |

### 5.2 보호 대상 (Protected — viewer role 필요)

| Router | Prefix/Path | Endpoints |
|--------|-------------|-----------|
| orders | `/orders*` | list, get, events, broker-orders |
| audit-logs | `/audit-logs*` | list |
| reconciliation | `/reconciliation/*` | runs, locks |
| decisions | `/trade-decisions*`, `/decision-contexts/*` | list, get |
| accounts | `/accounts*` | list, get |
| instruments | `/instruments/*` | get |
| positions | `/positions*`, `/cash-balances*` | list, get |
| clients | `/clients/*` | get |

### 5.3 Swagger UI / Docs 정책

- **공개:** `/docs`, `/openapi.json`
- Authorize 버튼을 통해 Bearer token 입력 후 protected endpoint 호출 가능
- OpenAPI spec에 `bearer` security scheme 포함

---

## 6. FastAPI 구현 상세

### 6.1 신규 파일: [`src/agent_trading/api/security.py`](src/agent_trading/api/security.py)

```python
"""Bearer token authentication + minimum RBAC for inspection API."""

from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(slots=True, frozen=True)
class Principal:
    """Authenticated principal with role."""

    token: str
    role: str


_INSPECTION_TOKEN: str | None = None
_INSPECTION_ROLE: str = "viewer"


def configure_security(*, token: str | None, role: str = "viewer") -> None:
    """Configure the global security settings (called once at startup)."""
    global _INSPECTION_TOKEN, _INSPECTION_ROLE
    _INSPECTION_TOKEN = token
    _INSPECTION_ROLE = role


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> Principal:
    """Extract and validate the bearer token from the request.

    Returns ``Principal`` on success.
    Raises ``401`` when the token is missing or invalid.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization scheme — use Bearer",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if _INSPECTION_TOKEN is None:
        # Security module not configured — deny all
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication not configured",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.credentials != _INSPECTION_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return Principal(token=credentials.credentials, role=_INSPECTION_ROLE)


async def require_viewer(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    """Require at least ``viewer`` role."""
    if principal.role not in ("viewer", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions — viewer role required",
        )
    return principal
```

### 6.2 [`src/agent_trading/api/app.py`](src/agent_trading/api/app.py) 변경

```python
def create_app(
    repos: RepositoryContainer | None = None,
    *,
    runtime_mode: str = "in_memory",
    auth_enabled: bool = True,  # NEW — safe default
    auth_token: str | None = None,  # NEW
) -> FastAPI:
```

**변경 내용:**
1. `auth_enabled: bool = True`, `auth_token: str | None = None` 파라미터 추가
2. `auth_enabled=True` + `auth_token=None` → `ValueError` startup fail
3. lifespan 시작 시 `configure_security(token=auth_token)` 호출
4. `auth_enabled=True`인 경우에만 보호 대상 router에 `dependencies=[Depends(require_viewer)]` 적용
5. OpenAPI security scheme 등록

```python
from agent_trading.api.security import configure_security, require_viewer

# In lifespan:
configure_security(token=auth_token)

# OpenAPI security scheme:
app = FastAPI(
    ...
    swagger_ui_parameters={"persistAuthorization": True},
)

# Register security scheme in OpenAPI
from fastapi.openapi.utils import get_openapi

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",  # format only, not actual JWT
        }
    }
    openapi_schema["security"] = [{"BearerAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi
```

**Protected router 등록 (변경):**

```python
from agent_trading.api.security import require_viewer

# 보호 대상은 dependencies=[Depends(require_viewer)] 추가
app.include_router(orders_router, dependencies=[Depends(require_viewer)])
app.include_router(audit_logs_router, dependencies=[Depends(require_viewer)])
app.include_router(reconciliation_router, dependencies=[Depends(require_viewer)])
app.include_router(decisions_router, dependencies=[Depends(require_viewer)])
app.include_router(accounts_router, dependencies=[Depends(require_viewer)])
app.include_router(instruments_router, dependencies=[Depends(require_viewer)])
app.include_router(positions_router, dependencies=[Depends(require_viewer)])
app.include_router(clients_router, dependencies=[Depends(require_viewer)])

# health_router는 dependencies 없이 공개 유지
app.include_router(health_router)
```

### 6.3 Health Router — 변경 없음

[`src/agent_trading/api/routes/health.py`](src/agent_trading/api/routes/health.py)는
현재 상태 유지. 공개 endpoint로 남음.

### 6.4 다른 Route 파일 — 변경 없음

모든 route 파일은 변경 불필요. 인증은 `app.py`의 `include_router()` 수준에서
일괄 적용되므로 각 route 파일은 자신의 비즈니스 로직에만 집중한다.

---

## 7. OpenAPI / Swagger 통합

### 7.1 Security Scheme

```yaml
components:
  securitySchemes:
    BearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT
security:
  - BearerAuth: []
```

### 7.2 Swagger UI Authorize 버튼

- `/docs` 페이지에 Authorize 버튼 표시
- Bearer token 입력 후 모든 protected endpoint 호출 가능
- `persistAuthorization: true`로 페이지 새로고침 시에도 token 유지

### 7.3 Health / Docs / OpenAPI는 보호되지 않음

- `/health` — probe용
- `/health/readyz` — probe용
- `/docs` — Swagger UI
- `/openapi.json` — OpenAPI spec

---

## 8. Docker / 실행 환경

### 8.1 [`docker-compose.yml`](docker-compose.yml) 변경

```yaml
api:
  environment:
    ...
    INSPECTION_API_TOKEN: "${INSPECTION_API_TOKEN:-}"  # .env 또는 환경 변수
    INSPECTION_API_ROLE: "viewer"
```

### 8.2 `.env` 파일 (로컬 개발)

```env
# Inspection API Auth
INSPECTION_API_TOKEN=dev-token-123
INSPECTION_API_ROLE=viewer
```

### 8.3 `make run-api` 경로

```makefile
run-api:
	INSPECTION_API_TOKEN=dev-token-123 \
	uvicorn agent_trading.api.app:create_app_from_env \
	--factory --reload --host 0.0.0.0 --port 8000
```

---

## 9. 테스트 전략

### 9.1 Test Auth Fixture — [`tests/api/conftest.py`](tests/api/conftest.py)

```python
@pytest.fixture
async def auth_client() -> TestClient:
    """FastAPI TestClient with auth enabled (token: test-token)."""
    app = create_app(auth_token="test-token")
    with TestClient(app) as tc:
        yield tc
```

### 9.2 기존 Fixture — `auth_enabled=False`로 변경 필요

`client`와 `empty_client` fixture는 `auth_enabled=True`가 기본값이므로
명시적으로 `auth_enabled=False`를 전달해야 한다.

```python
# 기존: app = create_app(repos=seeded_repos)
# 변경:
app = create_app(repos=seeded_repos, auth_enabled=False)
```

`postgres_client` fixture도 동일한 변경 필요:

```python
# 기존: app = create_app(repos=repos, runtime_mode="postgres")
# 변경:
app = create_app(repos=repos, runtime_mode="postgres", auth_enabled=False)
```

### 9.3 신규 테스트 파일: [`tests/api/test_auth.py`](tests/api/test_auth.py)

#### A. 공개 endpoint 테스트
- `test_health_public_without_token` — `/health` 토큰 없이 200
- `test_health_readyz_public_without_token` — `/health/readyz` 토큰 없이 200
- `test_docs_public_without_token` — `/docs` 토큰 없이 200
- `test_openapi_json_public_without_token` — `/openapi.json` 토큰 없이 200

#### B. 보호 endpoint 무인증 접근 → 401
- `test_orders_unauthorized` — 토큰 없이 `/orders` → 401
- `test_accounts_unauthorized`
- `test_instruments_unauthorized`
- `test_reconciliation_unauthorized`
- `test_audit_logs_unauthorized`
- `test_trade_decisions_unauthorized`
- `test_positions_unauthorized`
- `test_cash_balances_unauthorized`
- `test_clients_unauthorized`

#### C. 보호 endpoint 인증 접근 → 200
- `test_orders_authorized` — 올바른 Bearer token → 200
- `test_accounts_authorized`
- 대표 endpoint 2~3개만 (orders, accounts, instruments)

#### D. 잘못된 토큰 → 401
- `test_invalid_token` — 잘못된 Bearer token → 401

#### E. OpenAPI security scheme 검증
- `test_openapi_security_scheme` — OpenAPI spec에 bearer scheme 존재 확인

### 9.4 기존 Test 영향 없음 확인

- `test_inspection.py` — `client`, `empty_client` fixture 사용 → 변경 없음
- `test_health.py` — `client`, `empty_client` fixture 사용 → 변경 없음
- `test_postgres_inspection.py` — `create_app(runtime_mode="postgres")` → 변경 없음

---

## 10. 변경 파일 요약

| 파일 | 상태 | 설명 |
|------|------|------|
| `src/agent_trading/api/security.py` | **신규** | Principal, verify_token, get_current_principal, require_viewer |
| `src/agent_trading/api/app.py` | 수정 | auth_token 파라미터, router dependencies, OpenAPI security scheme |
| `tests/api/conftest.py` | 수정 | `auth_client` fixture 추가 |
| `tests/api/test_auth.py` | **신규** | Auth/RBAC 테스트 (공개/401/200/OpenAPI) |
| `docker-compose.yml` | 수정 | `INSPECTION_API_TOKEN` env 추가 |
| `Makefile` | 수정 | `run-api`에 token 추가 |
| `plans/41_inspection_api_manual_verification.md` | 수정 | 인증 사용법 추가 |
| `plans/46_auth_rbac_inspection_api.md` | **신규** | 본 문서 |

---

## 11. 실행 순서

| 단계 | 작업 | 담당 |
|------|------|------|
| 1 | `security.py` 생성 — Principal, verify_token, get_current_principal, require_viewer | Code |
| 2 | `app.py` 수정 — auth_token param, router dependencies, OpenAPI scheme | Code |
| 3 | `conftest.py` 수정 — `auth_client` fixture 추가 | Code |
| 4 | `test_auth.py` 생성 — 공개/401/200/OpenAPI 테스트 | Code |
| 5 | `docker-compose.yml` 수정 — INSPECTION_API_TOKEN env | Code |
| 6 | `Makefile` 수정 — `run-api`에 token 추가 | Code |
| 7 | `plans/41_inspection_api_manual_verification.md` — 인증 사용법 추가 | Code |
| 8 | pytest 실행 — 기존 39개 + 신규 auth 테스트 전부 통과 확인 | Code |
| 9 | Postgres pytest 실행 — 회귀 없음 확인 | Code |

---

## 12. 검증 포인트

1. ✅ 보호된 endpoint는 토큰 없이 401 반환
2. ✅ `/health`, `/health/readyz`는 토큰 없이도 200
3. ✅ 올바른 Bearer token으로 모든 보호 endpoint 정상 응답
4. ✅ 잘못된 Bearer token → 401
5. ✅ OpenAPI spec에 bearer security scheme 존재
6. ✅ Swagger UI에서 Authorize 버튼 사용 가능
7. ✅ 기존 in-memory 39개 테스트 회귀 없음
8. ✅ 기존 Postgres 테스트 회귀 없음

---

## 13. 남은 후속 작업

1. **Token rotation** — static token을 주기적으로 교체하는 프로세스
2. **JWT/OIDC** — external IdP 연동으로 업그레이드 (향후 필요 시)
3. **Admin write endpoint** — Phase 2+에서 write endpoint 추가 시 `require_admin()` 활용
4. **Audit logging for auth failures** — 인증 실패를 audit log에 기록

---

## 14. Risk Assessment

| Risk | 영향 | 대응 |
|------|------|------|
| Token 노출 | 모든 API 접근 가능 | static token이므로 빠른 교체 필요. HTTPS 전송 강제 |
| Token 미설정 운영 배포 | API 무인증 상태 | startup warning 로그, docker-compose에 env 필수화 |
| 기존 테스트 실패 | CI/CD 중단 | `create_app(auth_token=None)`으로 backward-compatible 설계 |
| Swagger 노출로 API 구조 노출 | 정보 노출 | `/docs`는 공개 정책 — 운영 환경에서 추가 고려 필요 |
