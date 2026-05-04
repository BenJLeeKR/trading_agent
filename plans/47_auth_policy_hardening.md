# Plan 47 — Auth Policy Hardening for Inspection API (Pre-UI Security Pass)

**Date:** 2026-05-04  
**Status:** Draft  
**Designer:** Architect

---

## Revision History

| Rev | Date | Author | Changes |
|-----|------|--------|---------|
| 1.0 | 2026-05-04 | Architect | Initial draft |

---

## 1. Why Now

Plan 46으로 최소 Auth/RBAC를 추가했으나, Admin UI 착수 전에 아래 항목을 운영 기준으로 명확히 고정할 필요가 있다.

- 인증 정책이 코드에는 반영됐지만 문서/운영 기준이 아직 암묵적
- `create_app_from_env()`에 role 전달 버그 존재
- whitespace-only token 방어 미흡
- BACKLOG/README에 Plan 46 승격/목록 미반영
- Admin UI 설계 전에 보안 baseline을 확정해야 이후 작업이 흔들리지 않음

---

## 2. 설계 원칙

1. **정책 정리 중심** — 새 인증 시스템 도입이 아니라, 기존 auth layer를 운영 가능한 정책으로 굳힘
2. **최소 코드 변경** — 발견된 버그 수정 + 1줄 validation hardening만 수행
3. **문서 우선** — 코드보다 정책 문서와 테스트 보강에 집중
4. **Admin UI 전초 작업** — UI 착수 전에 보안 결정을 명시적으로 확정

---

## 3. Docs/OpenAPI 공개 정책

### 결정: Option A 유지 (공개, 향후 보호 옵션 예약)

| Endpoint | 정책 | 근거 |
|----------|------|------|
| `/docs` (Swagger UI) | **공개** | API 발견성(discoverability) 유지. 실제 데이터는 token 없이 조회 불가 |
| `/openapi.json` | **공개** | 코드 생성 도구와의 호환성 유지 |
| `/health` | **공개** (기존不变) | Load balancer / k8s probe, 운영 도구 호환성 |
| `/health/readyz` | **공개** (기존不变) | 동일 |

**단, 다음은 문서에 명시:**
- "문서는 공개지만, 보호 endpoint 호출에는 `Authorization: Bearer <token>`이 필요합니다"
- "향후 보안 요구사항이 강화되면 `/docs`와 `/openapi.json`도 보호 대상에 포함할 수 있습니다"

**Future backlog:**
- `/docs` 보호 옵션 → BACKLOG에 등록

---

## 4. Token 운영 정책

### 4.1 필수 정책

| 항목 | 정책 | 근거 |
|------|------|------|
| `INSPECTION_API_TOKEN` | **필수** (auth-enabled 모드) | 설정 없으면 startup fail |
| Token 형식 | 최소 1자 이상의 non-whitespace 문자열 | 빈 문자열/whitespace-only 거부 |
| Token 길이 | 최소 길이 제한 없음 (과도한 제약 피함) | UUID, 임의 문자열, JWT 모두 허용 |
| Token 값 저장 | 환경 변수 또는 secret manager | `.env` 파일, docker secret, K8s Secret 등 |
| Token 교체 | 현재는 수동 (환경 변수 재설정 + 재시작) | 향후 external auth로 교체 가능 |

### 4.2 실행 경로별 정책

| 경로 | Token 설정 | 동작 |
|------|-----------|------|
| `make run-api` | **직접 설정 필요** | `INSPECTION_API_TOKEN="..." make run-api` |
| `make run-api-dev` | 자동 주입 (`dev-token-123`) | 개발 편의 전용, 절대 운영 사용 금지 |
| `docker compose up -d db api` | `${INSPECTION_API_TOKEN:-}` (empty→startup fail) | `.env` 또는 shell env로 주입 필요 |
| `create_app_from_env()` | `INSPECTION_API_TOKEN` env var | 미설정 시 `ValueError` (startup fail) |
| `create_app(auth_enabled=False)` | 불필요 | **개발/테스트 전용**, 운영 사용 금지 |

### 4.3 Token 검증 로직 (hardening)

**Current** (`app.py:72`):
```python
if auth_enabled and not auth_token:
    raise ValueError(...)
```

**After hardening:**
```python
if auth_enabled and (not auth_token or not auth_token.strip()):
    raise ValueError(...)
```

`"  "` (whitespace-only)가 token으로 설정되는 것을 방지. 빈 문자열은 기존 `not auth_token`에서 이미 차단됨.

---

## 5. RBAC 정리

### 5.1 현재 상태

| 역할 | 코드 | 실제 Enforcement |
|------|------|-----------------|
| `viewer` | `require_viewer()`에서 허용 | **모든 보호 endpoint의 실질적 역할** |
| `admin` | `require_viewer()`에서 허용 | 구조만 정의, 현재는 `viewer`와 동일하게 접근 가능 |
| 기타 역할 | `require_viewer()`에서 **403** | 향후 `require_admin()` 용으로 예약 |

### 5.2 발견된 버그

**`create_app_from_env()`에서 role 미전달** ([`app.py:226`](../src/agent_trading/api/app.py:226)):

```python
def create_app_from_env() -> FastAPI:
    ...
    role = os.getenv("INSPECTION_API_ROLE", "viewer")
    return create_app(runtime_mode=mode, auth_token=token)  # ← role 누락
```

`create_app()`은 현재 `role` 파라미터가 없으므로, `create_app()`에 role을 받을 수 있도록 수정하거나 — 현재 Phase에서는 이 버그의 실질적 영향이 없음 (`viewer`가 기본값이므로). 하지만 코드 일관성을 위해 `create_app()`에 `auth_role` 파라미터를 추가하고 `create_app_from_env()`에서 전달해야 함.

### 5.3 정리

- `viewer`가 유일한 실질적 역할임을 문서에 명시
- `admin`은 "reserved for future use (write/admin endpoints)"로 명확히 표기
- 무리한 role matrix 확장 하지 않음
- 필요한 경우 `require_admin()` dependency는 향후 별도 Plan에서 추가

---

## 6. 변경 사항 상세

### 6.1 [`src/agent_trading/api/app.py`](../src/agent_trading/api/app.py)

#### 6.1.1 Whitespace-only token 검증 (line 72)

```python
# Before:
if auth_enabled and not auth_token:

# After:
if auth_enabled and (not auth_token or not auth_token.strip()):
```

#### 6.1.2 `create_app()`에 `auth_role` 파라미터 추가

```python
_VALID_ROLES = frozenset({"viewer", "admin"})

def create_app(
    repos: RepositoryContainer | None = None,
    *,
    runtime_mode: str = "in_memory",
    auth_enabled: bool = True,
    auth_token: str | None = None,
    auth_role: str = "viewer",            # ← 추가
) -> FastAPI:
```

**`auth_role` 허용값 검증** (startup 시):
```python
if auth_role not in _VALID_ROLES:
    raise ValueError(
        f"Invalid auth_role={auth_role!r}. Allowed values: {sorted(_VALID_ROLES)}"
    )
```

lifespan에서 `configure_security(token=auth_token, role=auth_role)`로 전달.

#### 6.1.3 `create_app_from_env()`에서 role 전달 (line 226)

```python
# Before:
return create_app(runtime_mode=mode, auth_token=token)

# After:
return create_app(runtime_mode=mode, auth_token=token, auth_role=role)
```

### 6.2 [`tests/api/test_auth.py`](../tests/api/test_auth.py) — 테스트 보강

#### A. Whitespace token startup fail 검증

```python
def test_whitespace_token_raises_value_error(self) -> None:
    """create_app with whitespace-only token raises ValueError."""
    with pytest.raises(ValueError, match="auth_token must be provided"):
        create_app(auth_enabled=True, auth_token="   ")
```

#### B. Role field 검증

```python
def test_principal_role_defaults_to_viewer(self, auth_client: TestClient) -> None:
    """Principal role defaults to 'viewer'."""
    # This indirectly tests that configure_security(role="viewer") is called
    # by checking that a valid token returns 200 (viewer access)
    resp = auth_client.get("/orders", headers=_auth_header())
    assert resp.status_code == 200
```

#### C. Docs 정책 명시 테스트 (이미 존재 — 유지)

### 6.3 [`plans/41_inspection_api_manual_verification.md`](../plans/41_inspection_api_manual_verification.md)

- Rev 6 추가: Plan 47 정책 반영
- Section 1.1: token 운영 정책 표 추가 (run-api / run-api-dev / docker 구분)
- Section 5 (현재 한계): docs 공개 정책 명시, docs 보호는 future backlog임을 표기

### 6.4 [`plans/BACKLOG.md`](../plans/BACKLOG.md)

- Medium-term #2 "Auth / RBAC for admin API" → `✅ Plan 46으로 승격`
- 새 항목 추가: "Docs/OpenAPI 보호 옵션 (inspection API)"

### 6.5 [`plans/README.md`](../plans/README.md)

- Plan 46, Plan 47 목록 추가

---

## 7. 변경 파일 요약

| 파일 | 변경 유형 | 설명 |
|------|-----------|------|
| `src/agent_trading/api/app.py` | 수정 | whitespace token 검증 강화, `auth_role` 파라미터 추가, `create_app_from_env()` 버그 수정 |
| `tests/api/test_auth.py` | 수정 | whitespace token startup fail 테스트 추가, role field 검증 |
| `plans/47_auth_policy_hardening.md` | **신규** | 본 설계 문서 |
| `plans/41_inspection_api_manual_verification.md` | 수정 | Rev 6 — 정책 결정 문서화 |
| `plans/BACKLOG.md` | 수정 | Auth/RBAC 승격 기록, docs 보호 옵션 추가 |
| `plans/README.md` | 수정 | Plan 46, 47 목록 추가 |

---

## 8. 실행 순서

1. `plans/47_auth_policy_hardening.md` — 사용자 리뷰
2. `src/agent_trading/api/app.py` — whitespace token 검증 + `auth_role` 파라미터 + role 전달 버그 수정
3. `tests/api/test_auth.py` — 테스트 보강
4. `plans/41_inspection_api_manual_verification.md` — Rev 6 업데이트
5. `plans/BACKLOG.md` — 승격 기록
6. `plans/README.md` — 목록 추가
7. pytest 검증

---

## 9. 검증 포인트

1. `make run-api` (token 없음) → startup fail (safe default 유지)
2. `create_app(auth_enabled=True, auth_token="   ")` → `ValueError` (whitespace 차단)
3. `create_app_from_env(INSPECTION_API_ROLE=admin)` → role이 Principal에 전달됨
4. 기존 auth 테스트 19개 + health 3개 + inspection 39개 회귀 없음
5. Docs 정책이 문서에 명시적으로 고정됨
6. BACKLOG/README에 Plan 46, 47 반영

---

## 10. 남은 후속 작업

1. **Docs 보호 옵션** — 향후 보안 요구사항 강화 시 `/docs`, `/openapi.json`도 auth 보호. BACKLOG에 등록
2. **`require_admin()` dependency** — write/admin endpoint 추가 시 admin 역할 enforcement 구현
3. **Admin UI 설계** — Plan 47 완료 후 Admin UI 착수. 인증 정책이 고정되었으므로 UI 설계 시 auth 연동 방식을 결정 가능

---

## 11. Risk Assessment

| 리스크 | 영향 | 완화 |
|--------|------|------|
| `auth_role` 파라미터 추가로 기존 호출자 영향 | 낮음 — 기본값이 `"viewer"`이므로 기존 호출(파라미터 미지정)은 동일하게 동작 |
| Whitespace token 검증으로 기존 token 거부 | 낮음 — whitespace-only token은 운영 환경에서 실수로 설정할 가능성이 있으므로 오히려 조기 발견에 도움 |
| 문서 업데이트 누락 | 낮음 — 변경 파일 목록에 포함하여 추적 |
