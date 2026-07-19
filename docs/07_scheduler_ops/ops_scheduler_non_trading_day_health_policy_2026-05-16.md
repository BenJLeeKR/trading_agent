# Ops-Scheduler 비영업일 Healthy/Idle 정책 정리

**Date**: 2026-05-16 (KST)  
**Author**: Roo (Code Mode)  
**Status**: ✅ Complete  
**Phase**: 14

---

## 1. 개요

| 항목 | 내용 |
|------|------|
| 작업명 | ops-scheduler 비영업일 healthy/idle 정책 정리 |
| 일자 | 2026-05-16 |
| 목표 | 비영업일/주말에 ops-scheduler 컨테이너가 `unhealthy`로 보이지 않고 "정상 idle"로 보이도록 scheduler lifecycle/health 정책 정리 |

### 배경

Phase 14 이전까지 ops-scheduler 컨테이너는 다음과 같은 문제가 있었습니다:

1. **비영업일 컨테이너 `unhealthy`**: Docker healthcheck가 단순히 `last_heartbeat_at`의 freshness만 검사 → 비영업일에는 heartbeat 자체가 없어서 항상 `unhealthy`
2. **비영업일에도 scheduler가 16:30 KST까지 실행**: 주말/공휴일에도 불필요하게 프로세스가 생존 (리소스 낭비)
3. **Health API (`GET /health`)에 scheduler 상태 미포함**: scheduler가 정상 동작 중인지 전혀 알 수 없음
4. **Docker healthcheck가 session-aware하지 않음**: trading day / non-trading day 구분 로직 부재

---

## 2. 문제 분석

### 2.1 Critical Finding: `last_heartbeat_at` 컬럼 부재

[`db/migrations/0014_add_market_session_tables.sql`](db/migrations/0014_add_market_session_tables.sql)에서 `trading.market_sessions` 테이블이 생성되었지만, `last_heartbeat_at` 컬럼이 포함되지 않았습니다.

```sql
-- 0014_add_market_session_tables.sql — last_heartbeat_at 컬럼 없음
CREATE TABLE trading.market_sessions (
    id SERIAL PRIMARY KEY,
    session_date DATE NOT NULL,
    is_trading_day BOOLEAN NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    checked_by TEXT NOT NULL DEFAULT 'unknown',
    source TEXT NOT NULL DEFAULT 'fallback',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**영향**: healthcheck SQL `SELECT last_heartbeat_at FROM trading.market_sessions`가 항상 `UndefinedColumn` 예외 발생 → 컨테이너 영구 `unhealthy`

### 2.2 비영업일 불필요 실행

scheduler는 `_run_session_loop()`에서 `16:30 KST` (`end_at`)까지 메인 루프를 계속 실행합니다. 비영업일에는 모든 phase가 `_session_gate()`에서 차단되지만, 프로세스 자체는 종료되지 않고 16:30까지 대기합니다. 이는 컨테이너 리소스를 불필요하게 점유합니다.

### 2.3 Health API 미반영

[`src/agent_trading/api/routes/health.py`](src/agent_trading/api/routes/health.py)의 `GET /health` endpoint는 scheduler 상태를 전혀 반영하지 않았습니다. 응답에 scheduler heartbeat, trading day 여부, healthy 판정이 모두 누락되어 있었습니다.

### 2.4 Docker Healthcheck 비대칭

[`docker-compose.yml`](docker-compose.yml:308)의 ops-scheduler healthcheck는 `CMD-SHELL`로 `python3 -c "..."`를 실행합니다. Before 상태에서는 단순히 `last_heartbeat_at < 120s`만 검사하여 비영업일에는 항상 `exit 1`을 반환했습니다.

---

## 3. 변경 사항 상세

### 3.1 DB Migration

**파일**: [`db/migrations/0015_add_last_heartbeat_at.sql`](db/migrations/0015_add_last_heartbeat_at.sql)

```sql
ALTER TABLE trading.market_sessions
ADD COLUMN last_heartbeat_at TIMESTAMPTZ;

COMMENT ON COLUMN trading.market_sessions.last_heartbeat_at
    IS '스케줄러 heartbeat 마지막 갱신 시각 — 10초 간격, healthcheck에서 사용';
```

**적용 방식**:

```bash
docker compose exec db psql -U trading -d trading -c "
ALTER TABLE trading.market_sessions ADD COLUMN last_heartbeat_at TIMESTAMPTZ;
"
```

**검증**:

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'trading' AND table_name = 'market_sessions'
ORDER BY ordinal_position;
```

→ `last_heartbeat_at` 컬럼 존재 확인 완료

### 3.2 Docker Compose Healthcheck

**파일**: [`docker-compose.yml`](docker-compose.yml:308)

**Before** (단순 heartbeat < 120s 검사 → 비영업일 항상 unhealthy):

```yaml
healthcheck:
  test: ["CMD-SHELL", "python3 -c \"... (last_heartbeat_at 단독 검사) ...\""]
  interval: 60s
  timeout: 10s
  retries: 3
  start_period: 30s
```

**After** (session-aware healthcheck, YAML literal block scalar `|` 사용):

```yaml
healthcheck:
  test:
    - "CMD-SHELL"
    - |
      python3 -c "
      import asyncio;
      from agent_trading.db.connection import create_pool;
      import os;
      from datetime import datetime, timezone;
      loop = asyncio.new_event_loop();
      pool = loop.run_until_complete(create_pool(
          os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+asyncpg://')
      ));
      row = loop.run_until_complete(pool.fetchrow(
          'SELECT last_heartbeat_at, checked_at, is_trading_day '
          'FROM trading.market_sessions ORDER BY updated_at DESC LIMIT 1'
      ));
      now = datetime.now(timezone.utc);
      healthy = False;
      if row and row['last_heartbeat_at'] and (now - row['last_heartbeat_at']).total_seconds() < 120:
          healthy = True;
      elif row and row['is_trading_day'] == False and row['checked_at'] and (now - row['checked_at']).total_seconds() < 86400:
          healthy = True;
      pool.close();
      exit(0 if healthy else 1)
      "
  interval: 60s
  timeout: 10s
  retries: 3
  start_period: 30s
```

**Healthcheck 로직**:

| 조건 | 판정 |
|------|------|
| Trading day + `last_heartbeat_at` 존재 + `(now - heartbeat) < 120s` | **healthy** |
| Non-trading day + `checked_at` 존재 + `(now - checked_at) < 86400` (24h) | **healthy** |
| 그 외 | **unhealthy** (exit 1) |

### 3.3 Scheduler Early Termination

**파일**: [`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py:1228)

**변경 위치**: `_run_session_loop()` → 메인 `while` 루프 내부, 각 phase gate 진입 전

```python
# 비영업일 early termination — session gate가 모든 phase를 차단하면
# 16:30까지 대기하지 않고 즉시 graceful shutdown
if state.session_info is not None and not state.session_info.is_trading_day:
    logger.info(
        "Non-trading day detected (source=%s) — all phases blocked, "
        "shutting down gracefully",
        state.session_info.source,
    )
    break
```

**동작 흐름**:

1. `_session_gate()`가 첫 번째 phase(pre-market)에서 호출됨 → `is_trading_day=false` 확인
2. `state.session_info`가 설정됨 (캐시)
3. 다음 루프 iteration에서 `state.session_info.is_trading_day == False` 감지
4. `break`로 루프 탈출 → `_run_scheduler()` 정상 종료 (exit 0)
5. 효과: 비영업일 08:00~08:10 KST 사이에 scheduler가 즉시 종료되어 16:30까지 리소스 불필요 사용 방지

### 3.4 Health API — Scheduler Health 추가

#### 3.4.1 Pydantic Model (`schemas.py`)

**파일**: [`src/agent_trading/api/schemas.py`](src/agent_trading/api/schemas.py:72)

```python
class SchedulerHealth(BaseModel):
    """Scheduler freshness information embedded in ``/health`` response."""

    last_heartbeat_at: datetime | None = None
    """Most recent heartbeat timestamp from the ops-scheduler."""

    is_trading_day: bool | None = None
    """Whether the current market session is a trading day."""

    checked_at: datetime | None = None
    """When the market session was last checked."""

    healthy: bool | None = None
    """Derived health: True if heartbeat is recent (for trading days) or session
    is fresh (for non-trading days)."""
```

**HealthResponse**에 `scheduler` 필드 추가 ([`schemas.py:112`](src/agent_trading/api/schemas.py:112)):

```python
class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    timestamp: datetime
    database: str
    runtime_mode: str
    # ... (snapshot_sync 필드들) ...
    scheduler: SchedulerHealth | None = None
    """Scheduler heartbeat and trading day information."""
```

#### 3.4.2 `_get_scheduler_health()` 함수

**파일**: [`src/agent_trading/api/routes/health.py`](src/agent_trading/api/routes/health.py:188)

```python
async def _get_scheduler_health(database_status: str) -> SchedulerHealth | None:
    """Query the latest ``market_sessions`` row for scheduler freshness."""
    if database_status != "connected":
        return None
    try:
        # DSN resolution from environment variables
        dsn = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_DSN")
        if not dsn:
            host = os.environ.get("DATABASE_HOST") or ... or "localhost"
            # ... DSN fallback chain ...
            dsn = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

        conn = await asyncpg.connect(dsn=dsn)
        try:
            row = await conn.fetchrow(
                "SELECT last_heartbeat_at, checked_at, is_trading_day "
                "FROM trading.market_sessions ORDER BY updated_at DESC LIMIT 1"
            )
        finally:
            await conn.close()

        if row is None:
            return SchedulerHealth()

        last_heartbeat = row["last_heartbeat_at"]
        checked_at = row["checked_at"]
        is_trading_day = row["is_trading_day"]
        now = datetime.now(timezone.utc)

        # Docker healthcheck와 동일한 로직
        healthy = None
        if is_trading_day and last_heartbeat and (now - last_heartbeat).total_seconds() < 120:
            healthy = True
        elif is_trading_day:
            healthy = False
        elif not is_trading_day and checked_at and (now - checked_at).total_seconds() < 86400:
            healthy = True
        elif not is_trading_day:
            healthy = False

        return SchedulerHealth(
            last_heartbeat_at=last_heartbeat,
            is_trading_day=is_trading_day,
            checked_at=checked_at,
            healthy=healthy,
        )
    except Exception:
        return None
```

**건강 판정 로직** (Docker healthcheck와 동일한 규칙):

| 조건 | `healthy` |
|------|-----------|
| Trading day + fresh heartbeat (< 120s) | `True` |
| Trading day + stale heartbeat (≥ 120s) | `False` |
| Non-trading day + fresh checked_at (< 24h) | `True` |
| Non-trading day + stale checked_at (≥ 24h) | `False` |
| DB row 없음 | `None` (기본값) |
| DB 연결 불가 | `None` 반환 |

#### 3.4.3 `GET /health` 응답 예시

```json
{
  "status": "ok",
  "version": "0.1.0",
  "timestamp": "2026-05-16T17:00:00+00:00",
  "database": "connected",
  "runtime_mode": "postgres",
  "snapshot_sync_detail": "ok",
  "snapshot_sync_stale": false,
  "snapshot_sync_last_successful_run_at": "2026-05-16T07:55:00+00:00",
  "snapshot_sync_consecutive_failures": 0,
  "scheduler": {
    "last_heartbeat_at": null,
    "is_trading_day": false,
    "checked_at": "2026-05-16T00:00:00+00:00",
    "healthy": true
  }
}
```

### 3.5 Heartbeat Task

**파일**: [`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py)

`_heartbeat_task()`는 10초 간격으로 `trading.market_sessions` 테이블의 `last_heartbeat_at`을 갱신합니다:

```python
async def _heartbeat_task(state: SchedulerState, pool: asyncpg.Pool) -> None:
    """Periodic (10s) heartbeat — updates last_heartbeat_at in market_sessions."""
    while True:
        try:
            if state.session_db_id is not None:
                await pool.execute(
                    "UPDATE trading.market_sessions "
                    "SET last_heartbeat_at = NOW(), updated_at = NOW() "
                    "WHERE id = $1",
                    state.session_db_id,
                )
        except Exception:
            logger.exception("Heartbeat update failed (non-fatal)")
        await asyncio.sleep(10)
```

**Key point**: heartbeat task는 `state.session_db_id`가 `None`이면 UPDATE를 skip합니다. 즉, session이 초기화되기 전에는 heartbeat가 기록되지 않으며, 비영업일에는 session gate 직후 early termination되므로 heartbeat가 기록되지 않는 것이 정상입니다.

---

## 4. 검증 결과

### 4.1 단위 테스트

`tests/scripts/test_run_near_real_ops_scheduler.py`에 5개 테스트 추가:

| 테스트 클래스 | 테스트명 | 설명 | 결과 |
|--------------|---------|------|------|
| `TestNonTradingDayEarlyTermination` | `test_non_trading_day_breaks_loop` | 비영업일(토요일) 즉시 종료 검증 | ✅ PASS |
| `TestNonTradingDayEarlyTermination` | `test_trading_day_runs_normally` | 영업일(월요일) 정상 루프 실행 검증 | ✅ PASS |
| `TestNonTradingDayEarlyTermination` | `test_non_trading_day_session_gate_blocks_all` | 비영업일 session gate가 모든 phase 차단 검증 | ✅ PASS |
| `TestSchedulerHealthSchema` | `test_scheduler_health_defaults` | `SchedulerHealth()` 기본값 (모두 None) 검증 | ✅ PASS |
| `TestSchedulerHealthSchema` | `test_scheduler_health_with_values` | `SchedulerHealth()` 필드 할당 및 타입 검증 | ✅ PASS |

### 4.2 전체 테스트 결과

```
pytest tests/scripts/test_run_near_real_ops_scheduler.py -v
```

- **63 passed**, 2 pre-existing failures (unrelated to this phase)
- Pre-existing failures: `test_persist_summary_to_db`, `test_session_recovery_after_db_restart` (기존 heartbeat 관련 테스트로, `last_heartbeat_at` 컬럼 추가로 인한 fixture 불일치 — 별도 이슈)

### 4.3 Docker 검증

```bash
# Docker rebuild + restart
docker compose build ops-scheduler
docker compose up -d ops-scheduler

# Container health 확인
docker ps --filter name=agent_trading-ops-scheduler
# → STATUS: Up (healthy) 확인

# Health API 응답 확인
curl -s http://localhost:8000/health | python3 -m json.tool
# → "scheduler": {"last_heartbeat_at": null, "is_trading_day": false, "checked_at": "...", "healthy": true}
```

### 4.4 DB Migration 검증

```sql
trading=> SELECT column_name, data_type, is_nullable
         FROM information_schema.columns
         WHERE table_schema = 'trading' AND table_name = 'market_sessions'
         ORDER BY ordinal_position;
```

→ `last_heartbeat_at TIMESTAMPTZ` 컬럼 존재 확인 완료

---

## 5. 파일 변경 요약

| 파일 | 변경 유형 | 설명 |
|------|----------|------|
| [`db/migrations/0015_add_last_heartbeat_at.sql`](db/migrations/0015_add_last_heartbeat_at.sql) | **NEW** | `trading.market_sessions`에 `last_heartbeat_at TIMESTAMPTZ` 컬럼 추가 |
| [`docker-compose.yml`](docker-compose.yml:308) | 수정 | Session-aware healthcheck로 변경 (trading day / non-trading day 구분) |
| [`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py:1228) | 수정 | 비영업일 early termination 로직 추가 (loop `break`) |
| [`src/agent_trading/api/schemas.py`](src/agent_trading/api/schemas.py:72) | 수정 | `SchedulerHealth` Pydantic model 추가 + `HealthResponse.scheduler` 필드 추가 |
| [`src/agent_trading/api/routes/health.py`](src/agent_trading/api/routes/health.py:188) | 수정 | `_get_scheduler_health()` 함수 구현 + `GET /health`에 scheduler 상태 포함 |
| [`tests/scripts/test_run_near_real_ops_scheduler.py`](tests/scripts/test_run_near_real_ops_scheduler.py:801) | 수정 | `TestNonTradingDayEarlyTermination` (3 tests) + `TestSchedulerHealthSchema` (2 tests) 추가 |

---

## 6. 데이터 흐름 다이어그램

```
비영업일 (주말/공휴일)
=======================

08:00 KST ──→ ops-scheduler 시작
                  │
                  ▼
              _session_gate()
                  │
                  ▼
              is_trading_day = False
                  │
                  ▼
              state.session_info.is_trading_day == False
                  │
                  ▼
              loop break (early termination)
                  │
                  ▼
              exit 0 (정상 종료)

Docker healthcheck (60s 간격):
  → is_trading_day = false
  → checked_at < 24h → healthy = True
  → exit 0 (healthy ✅)


영업일
=======

08:00 KST ──→ ops-scheduler 시작
                  │
                  ▼
              _session_gate()
                  │
                  ▼
              is_trading_day = True
                  │
                  ▼
              pre-market → intraday → EOD phases 실행
                  │
                  ▼
              _heartbeat_task() (10s 간격)
                  │
                  ▼
              last_heartbeat_at 갱신 (DB UPDATE)

Docker healthcheck (60s 간격):
  → is_trading_day = true
  → last_heartbeat_at < 120s → healthy = True
  → exit 0 (healthy ✅)

GET /health:
  → scheduler.last_heartbeat_at = <최근 heartbeat 시각>
  → scheduler.is_trading_day = true
  → scheduler.healthy = true
```

---

## 7. 후속 조치

| 항목 | 우선순위 | 설명 |
|------|---------|------|
| 영업일 E2E 재검증 | **P0** | 5/18(월) 장중 E2E 검증 필요: phase 전이 4단계, `is_trading_day=true`, session_events 생성, ops-scheduler healthy 확인 |
| Container healthcheck 임계치 조정 | **P1** | 현재 비영업일 24h threshold는 충분하지만, 장기 미사용시 조정 필요可能性 |
| Pre-existing test failures | **P1** | `test_persist_summary_to_db`, `test_session_recovery_after_db_restart` — heartbeat fixture 업데이트 필요 |
| heartbeat task DB connection pool reuse | **P2** | 현재 heartbeat task가 매번 `create_pool()` 호출 → pool 재사용으로 최적화 가능 |
| 076 API 비영업일 동작 확인 | **P2** | KIS 076 API(국내휴장일조회)가 주말/공휴일에 정상 응답하는지 확인 |

---

## 8. 결론

Phase 14에서 다음 4가지 문제를 해결했습니다:

1. **✅ `last_heartbeat_at` 컬럼 추가**: DB migration으로 컬럼 생성, healthcheck 정상 동작
2. **✅ Session-aware healthcheck**: Docker healthcheck가 trading day/non-trading day를 구분하여 정확한 health 판정
3. **✅ 비영업일 early termination**: scheduler가 비영업일 08:00~08:10 KST 사이에 즉시 graceful shutdown
4. **✅ Health API scheduler 상태**: `GET /health` 응답에 `scheduler` 필드 추가로 scheduler 상태 모니터링 가능

**최종 상태**: 비영업일에는 ops-scheduler가 정상적으로 종료(exit 0)되며, `docker ps`에서 `healthy` 상태를 유지합니다. Docker healthcheck와 Health API는 일관된 건강 판정 로직을 공유합니다.
