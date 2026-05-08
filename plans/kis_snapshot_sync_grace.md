# Snapshot Sync Startup Grace Period

## 1. 정책 결정

### Grace Period 동작 요약

| 조건 | Grace 내 | Grace 경과 후 |
|------|----------|--------------|
| Stale / No history | `/health`: `detail: "starting_up"`<br>`/readyz`: `"ok"` (skip check) | `/health`: `detail: "stale"` / `"no_history"`<br>`/readyz`: `"degraded"` |
| Fresh sync | `/health`: `detail: "ok"` (정상 표시)<br>`/readyz`: `"ok"` | 동일 |
| DB unreachable | `/readyz`: `"not_ready"` (503) — **grace 무관** | 동일 |

**핵심 원칙**:
- Grace period는 snapshot sync freshness check에만 적용된다. DB unreachable 같은 치명적 상태는 grace와 무관하게 즉시 `not_ready`.
- Grace 기간 내에도 snapshot sync가 이미 fresh 하다면 정상으로 표시한다 (restart 후 빠르게 sync 완료된 케이스).
- Grace 기간이 지나면 기존 정책 그대로 적용.

### 기본값

- `KIS_SNAPSHOT_STARTUP_GRA`CE_SECONDS` = `600` (10분)
- 운영 환경에서 scheduler interval (기본 300초) + α로 설정 가능

---

## 2. 변경 파일

| # | 파일 | 변경 내용 |
|---|------|----------|
| 1 | `src/agent_trading/config/settings.py` | `_resolve_kis_snapshot_startup_grace_seconds()` resolver + `AppSettings` 필드 추가 |
| 2 | `src/agent_trading/api/app.py` | lifespan 시작 시 `_app.state.started_at = datetime.now(timezone.utc)` 설정 |
| 3 | `src/agent_trading/api/routes/health.py` | `_is_within_grace()` helper + `/health`에 grace `"starting_up"` detail + `/readyz`에 grace skip 로직 |
| 4 | `tests/api/test_health.py` | Grace period 관련 테스트 5개 추가 |
| 5 | `tests/api/test_auth.py` | `empty_client` fixture의 readyz auth 테스트 — grace 내 `"ok"`로 복원 가능 |
| 6 | `plans/BACKLOG.md` | 승격 기록 추가 |

---

## 3. 상세 설계

### 3.1 settings.py — 설정 추가

```python
def _resolve_kis_snapshot_startup_grace_seconds() -> int:
    """Resolve startup grace period for snapshot sync readiness check.

    ``KIS_SNAPSHOT_STARTUP_GRACE_SECONDS`` env var, default ``600`` (10 min).
    Clamped to ``max(0, value)`` — ``0`` disables grace.
    """
    raw = os.getenv("KIS_SNAPSHOT_STARTUP_GRACE_SECONDS", "600")
    return max(0, int(raw))
```

AppSettings에 추가:
```python
kis_snapshot_startup_grace_seconds: int = field(
    default_factory=_resolve_kis_snapshot_startup_grace_seconds,
)
```

### 3.2 app.py — Startup Timestamp

lifespan 시작 부분에 `started_at` 추가:

```python
@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _app.state.started_at = datetime.now(timezone.utc)
    configure_security(token=auth_token, role=auth_role)
    _app.state.broker_adapter = broker_adapter
    # ... rest unchanged
```

**설계 이유**: lifespan은 `create_app()` 호출 시점이 아닌 첫 요청 직전에 실행된다. 이 시각을 startup 기준으로 삼는 것이 가장 정확하다. 모든 코드 경로 (repos 주입/postgres/default in-memory)에 공통으로 적용된다.

### 3.3 health.py — Grace Period Helper + Route 수정

```python
def _is_within_grace(request: Request, settings: object) -> bool:
    """Check if the app is still within the startup grace period."""
    grace_seconds = getattr(settings, "kis_snapshot_startup_grace_seconds", 0)
    if grace_seconds <= 0:
        return False
    started_at = getattr(request.app.state, "started_at", None)
    if started_at is None:
        return False
    elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
    return elapsed < grace_seconds
```

`/health` 엔드포인트 수정 (grace 내에 스냅샷 체크를 건너뛰되 `"starting_up"` detail 표시):

```python
# In /health endpoint, before snapshot sync check:
if repos is not None and hasattr(repos, "snapshot_sync_runs"):
    within_grace = _is_within_grace(request, settings)
    if within_grace:
        snapshot_detail = "starting_up"
        snapshot_stale = None
        snapshot_last_ok = None
        snapshot_failures = None
    else:
        # ... existing logic unchanged
```

`/readyz` 엔드포인트 수정:

```python
# Before snapshot sync freshness check (step 2):
repos = getattr(request.app.state, "repos", None)
if repos is not None and hasattr(repos, "snapshot_sync_runs"):
    # Skip snapshot sync check during startup grace period
    settings = AppSettings()
    if _is_within_grace(request, settings):
        pass  # Don't check snapshot sync freshness during grace
    else:
        # ... existing logic unchanged
```

### 3.4 Grace Period 내 health 응답 예시

```json
{
  "status": "ok",
  "version": "0.1.0",
  "timestamp": "2026-05-08T22:00:00Z",
  "database": "in_memory",
  "runtime_mode": "in_memory",
  "snapshot_sync_detail": "starting_up",
  "snapshot_sync_stale": null,
  "snapshot_sync_last_successful_run_at": null,
  "snapshot_sync_consecutive_failures": null
}
```

---

## 4. 테스트 계획

`tests/api/test_health.py`에 다음 테스트 추가:

| # | 테스트 | 시나리오 | 기대 |
|---|--------|---------|------|
| 1 | `test_readyz_grace_no_history` | Grace 내, no history | `status: "ok"` (grace skip) |
| 2 | `test_readyz_grace_stale` | Grace 내, stale data | `status: "ok"` (grace skip) |
| 3 | `test_readyz_grace_expired_stale` | Grace 경과 후, stale data | `status: "degraded"` |
| 4 | `test_health_grace_detail` | Grace 내, /health | `snapshot_sync_detail: "starting_up"` |
| 5 | `test_readyz_grace_db_unreachable` | Grace 내 + DB down | `status: "not_ready"` (grace 무관) |

**테스트 구현 방법**: `create_app(repos=repos, auth_enabled=False)`로 생성한 앱의 `app.state.started_at`을 테스트에서 조정. 예를 들어 grace를 600초로 설정하고 `started_at`을 `now - 100`초로 설정하면 grace 내, `now - 1000`초로 설정하면 grace 경과.

```python
# Grace 내 시뮬레이션
app = create_app(repos=repos, auth_enabled=False)
app.state.started_at = datetime.now(timezone.utc) - timedelta(seconds=60)  # 60초 전 기동
# → startup_grace_seconds=600 기준으로 아직 grace 내

# Grace 경과 시뮬레이션
app.state.started_at = datetime.now(timezone.utc) - timedelta(seconds=1000)  # 1000초 전 기동
# → startup_grace_seconds=600 기준으로 grace 경과
```

**Grace period 무효화 설정**: 환경변수 `KIS_SNAPSHOT_STARTUP_GRACE_SECONDS=0` 설정 시 테스트. 하지만 기존 테스트에 영향을 주지 않도록 `empty_client` fixture의 기본값이 600이므로, 기존 `empty_client`를 사용하는 테스트들은 grace 내에 있어 `"ok"`를 반환하게 된다.

→ `test_health_readyz`와 `test_health_readyz_public_without_token`는 다시 `"ok"`를 기대하게 변경된다.

---

## 5. 기존 테스트 영향

| 테스트 | 현재 기대값 | 변경 후 기대값 | 이유 |
|--------|-----------|--------------|------|
| `test_health_readyz` | `"degraded"` | `"ok"` | `empty_client`는 lifespan에서 `started_at` 설정 → grace 내 |
| `test_health_readyz_public_without_token` | `"ok"` 또는 `"degraded"` | `"ok"` | 동일 |

이는 **올바른 동작**이다: `empty_client` fixture는 방금 생성된 앱이므로 startup grace 내에 있어 snapshot sync stale로 인한 degraded가 발생하지 않아야 한다.
