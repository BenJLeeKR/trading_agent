# Admin UI Session API 500 Hotfix

**Date**: 2026-05-16  
**Author**: Roo (Code Mode)  
**Status**: ✅ Complete

---

## 1. Root Cause

`'Connection' object has no attribute 'acquire'`

[`get_db`](src/agent_trading/api/deps.py:52)는 async generator로, 내부에서 `pool.acquire()`를 호출한 후 **`asyncpg.Connection`** 을 직접 `yield`합니다:

```python
pool = await get_pool()
async with pool.acquire() as conn:
    yield conn  # ← 이미 Connection
```

그런데 [`sessions.py`](src/agent_trading/api/routes/sessions.py:31)의 두 endpoint가 `db.acquire()`를 다시 호출했습니다:

```python
async with db.acquire() as conn:  # ← 'Connection' object has no attribute 'acquire'
    row = await conn.fetchrow(...)
```

`acquire()`는 `asyncpg.Pool`의 메서드이지 `asyncpg.Connection`의 메서드가 아닙니다. `db`가 이미 Connection이므로 `db.acquire()`는 `AttributeError`를 발생시킵니다.

---

## 2. Dependency Contract

| 컴포넌트 | 반환/기대 타입 | 비고 |
|---|---|---|
| [`deps.py:get_db()`](src/agent_trading/api/deps.py:52) | `asyncpg.Connection` (via `yield`) | `pool.acquire()`를 이미 수행 |
| [`routes/sessions.py`](src/agent_trading/api/routes/sessions.py) (**before**) | `asyncpg.Pool` (잘못 기대) | `db.acquire()` 호출 → AttributeError |
| [`routes/sessions.py`](src/agent_trading/api/routes/sessions.py) (**after**) | `asyncpg.Connection` | `db`를 직접 사용 |
| 다른 모든 routes (`accounts.py`, `orders.py`, etc.) | `RepositoryContainer` (via `get_repos`) | `get_db` 미사용, 별도 패턴 |

**일관성 정리**: `get_db`는 오직 session routes에서만 사용되며, 다른 route들은 `get_repos` 패턴을 사용합니다. 따라서 `get_db` 자체의 동작은 올바르며, session routes만 수정하면 됩니다 (Options A 접근법).

---

## 3. 수정 내용

### 3.1 [`src/agent_trading/api/routes/sessions.py`](src/agent_trading/api/routes/sessions.py)

| 변경 전 | 변경 후 |
|---|---|
| `async with db.acquire() as conn:` 사용 | `db`를 직접 Connection으로 사용 |
| 응답: `{"status": "no_data", "data": None}` | 응답: `{"session": None, "source": None}` |
| 응답: `{"status": "ok", "data": {...}, "healthy": bool, "stale_seconds": int}` | 응답: `{"session": {...}, "stale": bool}` |
| 응답: `{"status": "ok", "data": [dict(r) for r in rows]}` | 응답: `{"events": [dict(r) for r in rows]}` |
| 하드코딩된 `stale_seconds = 120` | 상수 `STALE_THRESHOLD_SECONDS = 120` |
| docstring에 잘못된 `db.acquire()` 예제 포함 | docstring에 올바른 사용법 명시 |

### 3.2 [`src/agent_trading/api/deps.py`](src/agent_trading/api/deps.py:52)

| 변경 전 | 변경 후 |
|---|---|
| `async with db.acquire() as conn:` 예제 (잘못됨) | `db.fetchrow(...)` 예제 (올바름) + 경고문 |

### 3.3 [`tests/api/test_sessions.py`](tests/api/test_sessions.py)

| 변경 전 | 변경 후 |
|---|---|
| Mock: Pool mock + `acquire()` wrapper | Mock: Connection 직접 yield |
| `_make_mock_pool()` 헬퍼 | 제거 (불필요) |
| 응답 검증: `data["status"] == "no_data"` | 응답 검증: `data == {"session": None, "source": None}` |
| 응답 검증: `data["healthy"] is True` | 응답 검증: `data["stale"] is False` |
| 응답 검증: `data["status"] == "ok"` + `data["data"]` | 응답 검증: `data["session"]` + `data["stale"]` |
| 응답 검증: `data["status"] == "ok"` + `data["data"]` | 응답 검증: `data["events"]` |

---

## 4. 테스트 결과

### 4.1 Session 테스트 전용 (5/5 통과)

```
tests/api/test_sessions.py::test_get_latest_session_no_data PASSED
tests/api/test_sessions.py::test_get_latest_session_healthy PASSED
tests/api/test_sessions.py::test_get_latest_session_stale PASSED
tests/api/test_sessions.py::test_get_recent_events_not_empty PASSED
tests/api/test_sessions.py::test_get_recent_events_empty PASSED
```

### 4.2 추가된/수정된 테스트 목록

| # | 테스트명 | 시나리오 | 기대 |
|---|---|---|---|
| 1 | `test_get_latest_session_no_data` | 빈 테이블 | 200 + `{"session": null, "source": null}` |
| 2 | `test_get_latest_session_healthy` | 최신 heartbeat (< 120s) | 200 + `stale: false` |
| 3 | `test_get_latest_session_stale` | 오래된 heartbeat (>= 120s) | 200 + `stale: true` |
| 4 | `test_get_recent_events_not_empty` | 이벤트 존재 | 200 + `events: [...]` |
| 5 | `test_get_recent_events_empty` | 이벤트 없음 | 200 + `events: []` |

### 4.3 회귀 테스트 (API 테스트)

다른 API route 테스트들과 함께 실행하여 회귀 없음 확인:
- `test_auth.py` → 34 passed
- `test_agent_runs.py` → all passed
- `test_health.py` → 3 pre-existing failures (무관)

---

## 5. Endpoint 검증 결과

### 5.1 `/health`
```json
{"status":"ok","database":"connected","runtime_mode":"postgres"}
```

### 5.2 `GET /market-sessions/latest`
```json
{
  "session": {
    "id": 1,
    "run_date": "2026-05-16",
    "is_trading_day": true,
    "market_phase": null,
    "source": "gate_error_fallback",
    "checked_at": "2026-05-16T05:38:08.372706+00:00",
    ...
  },
  "stale": true
}
```
✅ 200 OK — stale heartbeat 정상 처리 (500 없음)

### 5.3 `GET /market-sessions/events/recent?limit=5`
```json
{"events": []}
```
✅ 200 OK — 빈 events 정상 처리 (500 없음)

---

## 6. 남은 Follow-up

| 항목 | 우선순위 | 상태 |
|---|---|---|
| Admin UI (port 8001) session 패널 500 확인 | Low | Docker compose에 8001 port 없음. `/admin` static mount로 제공되므로 브라우저에서 확인 필요 |
| `get_db` docstring의 `db.acquire()` 패턴 문서 동기화 | Done | 수정 완료 |
| `test_health.py` pre-existing failures 분석 | Low | `test_readyz_stale_sync` 등 3건 — session API와 무관 |

---

## 7. 요약

**Root Cause (한 줄)**: `get_db`는 `asyncpg.Connection`을 yield하지만, session routes가 `Connection.acquire()` (존재하지 않는 메서드)를 호출하여 `AttributeError` 발생.

**해결 방식 (Options A)**: `get_db` 자체는 변경하지 않고, session routes에서 `db.acquire()` 호출을 제거하고 `db`를 직접 Connection으로 사용. 응답 포맷을 no-data 상황에서도 500이 아닌 200을 반환하도록 개선.
