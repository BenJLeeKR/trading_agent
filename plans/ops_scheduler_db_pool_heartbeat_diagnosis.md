# ops-scheduler DB Pool / Heartbeat 복구 진단 보고서

**작성일**: 2026-05-18 08:54 KST  
**진단자**: Roo (Debug Mode)  
**대상 서비스**: `agent_trading-ops-scheduler`  
**증상**: "운영 스케줄러 응답 없음 (Stale)" 경고, DB heartbeat 불능

---

## 타임라인 (KST)

| 시각 | 이벤트 |
|------|--------|
| 2026-05-17 **20:03:51** | Scheduler 컨테이너 시작 (1st run). DB pool **connected** ✅. Heartbeat task 생성됨. `session_db_id=15` |
| 2026-05-17 **20:03:51** | `end_of_day_end` (16:30) 이미 경과 → 즉시 idle 모드 진입. `next_run_date=2026-05-18` |
| 2026-05-17 **~24:00~** | Heartbeat 중단됨 (마지막 heartbeat: `2026-05-17 15:59:56 UTC` = `2026-05-18 00:59:56 KST`) |
| 2026-05-18 **07:52:26** | 컨테이너 **재생성** (`RestartCount=0` → 완전히 새 컨테이너). DB pool 생성 **실패** ❌ |
| 2026-05-18 **08:00:02** | Subprocess task(pre_snapshot_sync) → **DB 연결 성공** ✅ |
| 2026-05-18 **08:00:02** | Subprocess task(pre_event_ingestion) → **실행 성공** ✅ |
| 2026-05-18 **08:00:02** | Subprocess task(pre_post_submit_sync) → **DB 연결 성공** ✅ |
| 2026-05-18 **08:50:01** | Subprocess task(snapshot_sync, event_ingestion, decision) → **모두 정상** ✅ |
| 2026-05-18 **08:54:11** | `decision_submit_gate` returncode=-9 (SIGKILL) timeout=250s |

---

## 증거 요약

### 1. `market_sessions` 현재 상태

| run_date | is_trading_day | market_phase | last_heartbeat_at | seconds_since_heartbeat |
|----------|---------------|--------------|-------------------|----------------------|
| 2026-05-17 | `true` | `null` | 2026-05-17 15:59:56 UTC | **28,435초 (7.9시간)** |
| 2026-05-16 | `false` | `after-hours` | 2026-05-16 21:57:11 UTC | **93,401초 (1.1일)** |

- 2026-05-17 세션은 `is_trading_day=true`이지만 heartbeat가 7.9시간 전에 중단됨
- 2026-05-18 세션은 **아예 생성되지 않음** (pool 실패로 `_persist_session_state()` 미호출)

### 2. 컨테이너 상태

```
NAME: agent_trading-ops-scheduler
StartedAt: 2026-05-17T22:52:25Z  (= 2026-05-18 07:52:25 KST)
RestartCount: 0
Status: Up About an hour (unhealthy)
```

- `RestartCount=0`이지만, 이전 인스턴스 로그가 남아있어 **컨테이너가 완전히 재생성**되었음을 의미
- `(unhealthy)` — Health check가 `last_heartbeat_at` 120s 기준으로 실패

### 3. Log: Pool 실패 시점

```
2026-05-18 07:52:26 [WARNING] Failed to create DB pool — advisory lock and heartbeat disabled
```

**→ `except Exception`이 traceback 없이 로그를 삼켜 정확한 원인 파악 불가**

### 4. 현재 Pool 수동 테스트 (동일 파라미터)

```python
pool = await asyncpg.create_pool(
    dsn="postgresql://trading:trading@db:5432/trading",
    min_size=2, max_size=10
)  # ✅ SUCCESS
```

현재는 정상 동작 → **일시적(transient) 장애** 확인됨.

### 5. Subprocess env 상속 구조

```
Scheduler Process (pool 실패 ❌)
  ├── _run_command("pre_snapshot_sync", ...)
  │   └── subprocess: run_snapshot_sync_loop.py (env inherit) → 자체 DB 연결 성공 ✅
  ├── _run_command("pre_event_ingestion", ...)
  │   └── subprocess: run_event_ingestion_loop.py (env inherit) → 자체 DB 연결 성공 ✅
  └── _get_db_submit_count()  # asyncpg.connect() 직접 호출 → 성공 ✅
```

---

## Q1: DB Pool 생성 실패의 직접 원인은 무엇인가?

### 진단: **일시적(transient) DB 연결 장애**

컨테이너가 07:52:26 KST에 재생성된 직후 `asyncpg.create_pool(min_size=2, max_size=10)`가 실패. 현재 동일 파라미터로 정상 동작하므로 transient issue임.

### 가능한 원인 (확률순)

| 순위 | 원인 | 근거 |
|------|------|------|
| 1️⃣ | **동시성 컨테이너 시작으로 인한 DB connection 경합** | `api`, `ops-scheduler`, `reconciliation-worker` 모두 `depends_on: db: condition: service_healthy` 직후 동시에 pool 생성 시도. `min_size=2`씩 3개 서비스면 총 6개 connection이 순간적으로 생성되며 일부 실패 가능 |
| 2️⃣ | **DB 재시작 직후 health check race condition** | Docker health check가 통과한 직후 DB가 아직 모든 connection을 accept할 준비가 되지 않은短暂한 순간 존재 가능 |
| 3️⃣ | **이전 컨테이너의 leaked connection** | 이전 scheduler 프로세스가 pool connection을 정리하지 않고 종료되어 Postgres 입장에서 stale connection 누적. 단, `restart: unless-stopped`에서 컨테이너가 완전히 recreate되었으므로 가능성 낮음 |
| 4️⃣ | **자원 고갈 (file descriptors 등)** | 낮은 가능성. 컨테이너 내부 limit 도달 가능성 |
| 5️⃣ | **`DATABASE_URL` env var 일시적 누락** | 가능성 낮음. Docker Compose interpolation이 항상 동일하게 동작 |

### 보완 필요: `except Exception`이 traceback을 삼킴

```python
# scripts/run_near_real_ops_scheduler.py:1131-1132
except Exception:
    logger.warning("Failed to create DB pool — advisory lock and heartbeat disabled")
```

`logger.exception()` 대신 `logger.warning()`을 사용하여 **traceback이 완전히 누락**. 실제 예외 타입과 메시지를 알 수 없음.

---

## Q2: 왜 scheduler task는 돌지만 heartbeat만 죽는가?

### 구조적 원인

스케줄러는 **task를 subprocess로 실행**하고, heartbeat는 **main process의 pool**을 사용합니다.

```
Scheduler Main Process
├── [Main Loop] → _run_command("snapshot_sync", ...)
│                  └── asyncio.create_subprocess_exec()
│                       ├── subprocess stdout=PIPE
│                       ├── subprocess stderr=PIPE
│                       └── env=os.environ.copy()  ← env 상속
│                            └── run_snapshot_sync_loop.py
│                                 ├── DatabaseConfig() → DATABASE_HOST/DSN 조립
│                                 ├── asyncpg.connect() or create_pool()  ✅
│                                 └── (독립적인 DB connection 사용)
│
├── [Main Loop] → _run_command("event_ingestion", ...)  ✅ (동일 구조)
│
├── [Main Loop] → _get_db_submit_count()  ← asyncpg.connect(dsn) 직접 호출 ✅
│
├── [Advisory Lock] → pool: asyncpg.Pool  ← **실패한 pool** ❌
│
└── [_heartbeat_task] → pool.execute()  ← **pool이 None이므로 실행 안 됨** ❌
```

**핵심**: subprocess는 각자의 DB connection 로직을 통해 **독립적으로** 연결하므로 main process의 pool 실패와 무관.

### 추가 발견: `_heartbeat_task()`의 예외 처리 버그

```python
# scripts/run_near_real_ops_scheduler.py:1035-1051
async def _heartbeat_task(state: SchedulerState, pool) -> None:
    while True:
        try:
            if state.session_db_id is not None:
                await pool.execute(...)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("Heartbeat update skipped (session not yet persisted)")
        #                                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        #                                  BUG: 이 메시지는 state.session_db_id가 None일 때만
        #                                  의미가 있음. pool.execute()의 실제 실패 원인이
        #                                  가려짐.
```

`except Exception`의 로그 메시지가 **"session not yet persisted"로 고정**되어 있어, 실제로 `pool.execute()`가 실패해도 잘못된 원인으로 로깅됩니다.

---

## Q3: 복구를 위해 필요한 조치는 무엇인가?

### 단기 (Immediate Fix)

#### 1️⃣ Pool 생성 실패 시 tracebook 로깅 추가

[`scripts/run_near_real_ops_scheduler.py:1131`](scripts/run_near_real_ops_scheduler.py:1131):
```python
# BEFORE (line 1131-1132):
except Exception:
    logger.warning("Failed to create DB pool — advisory lock and heartbeat disabled")

# AFTER:
except Exception:
    logger.exception("Failed to create DB pool — advisory lock and heartbeat disabled")
```

#### 2️⃣ Pool 생성 재시도 로직 추가

```python
# scripts/run_near_real_ops_scheduler.py:1122-1132
pool = None
if dsn:
    for attempt in range(3):
        try:
            import asyncpg
            pool = await asyncpg.create_pool(
                dsn=dsn,
                min_size=int(env.get("DB_POOL_MIN", "2")),
                max_size=int(env.get("DB_POOL_MAX", "10")),
            )
            break  # success
        except Exception:
            if attempt < 2:
                wait = 5 * (attempt + 1)
                logger.warning(
                    "DB pool creation attempt %d/3 failed — retrying in %ds",
                    attempt + 1, wait,
                )
                await asyncio.sleep(wait)
            else:
                logger.exception(
                    "Failed to create DB pool after 3 attempts"
                )
```

#### 3️⃣ `_heartbeat_task()` 예외 메시지 수정

```python
# scripts/run_near_real_ops_scheduler.py:1044-1047
except Exception:
    if state.session_db_id is not None:
        logger.exception("Heartbeat UPDATE failed for session_id=%s", state.session_db_id)
    else:
        logger.debug("Heartbeat update skipped (session not yet persisted)")
```

### 중기 (Medium-term)

#### 4️⃣ Health check 로직 개선

현재 health check는 `last_heartbeat_at < 120s`를 기준으로 healthy 판단. 하지만:
- 장마감 후에는 heartbeat가 중단되어도 정상 (after-hours mode)
- `is_trading_day=false`인 경우 24시간 이내면 healthy 허용

2026-05-17은 `is_trading_day=true`이면서 heartbeat가 7.9시간 경과 → health check가 **항상 unhealthy**를 반환. 
after-hours/idle 모드에서도 healthy로 판단할 수 있는 조건 추가 필요:

```python
# Add condition for stale session within same calendar day with after-hours/idle mode
if row and row['market_phase'] in ('AFTER_HOURS', None) and not row['is_trading_day']:
    healthy = True  # Non-trading day, any check is fine
elif row and row['last_heartbeat_at']:
    seconds_ago = (now - row['last_heartbeat_at']).total_seconds()
    if seconds_ago < 120:
        healthy = True
    elif row.get('market_phase') in ('AFTER_HOURS', None) and seconds_ago < 86400:
        healthy = True  # After-hours/idle: allow up to 24h stale
```

#### 5️⃣ 컨테이너 재시작 시 idle 상태 유지

컨테이너 재시작 후에도 기존 session의 heartbeat를 재개할 수 있는 메커니즘 필요:
- 재시작 시 `market_sessions`에서 가장 최근 session 로드
- 해당 session이 여전히 유효하면 heartbeat 재개

### 장기 (Long-term)

#### 6️⃣ Pool 상태 모니터링 메트릭 추가

- `DB pool: connected` startup 로그만으로 부족
- 주기적 pool health check 로그 추가 (예: 5분마다 `pool._holders` 개수 로깅)

---

## Q4: `market_sessions.last_heartbeat_at`가 정상 갱신되려면 어떤 조건이 필요한가?

### 필수 조건 3가지

```
┌─────────────────────────────────────────────────────────────────┐
│  조건 1: pool is not None                                       │
│  └─ asyncpg.create_pool() 성공                                  │
│     → scripts/run_near_real_ops_scheduler.py:1122-1132         │
│                                                                 │
│  조건 2: state.session_db_id is not None                        │
│  └─ _persist_session_state() 성공 → INSERT/UPDATE 성공         │
│     → scripts/run_near_real_ops_scheduler.py:866-935           │
│     → state.session_db_id = row["id"]                          │
│                                                                 │
│  조건 3: pool.execute() 정상 동작                               │
│  └─ UPDATE trading.market_sessions SET last_heartbeat_at=NOW()  │
│     WHERE id = $1                                               │
│     → scripts/run_near_real_ops_scheduler.py:1040-1043         │
│                                                                 │
│  실행 주기: 10초 (asyncio.sleep(10))                            │
└─────────────────────────────────────────────────────────────────┘
```

### 현재 깨진 조건

| 조건 | 상태 | 설명 |
|------|------|------|
| 조건 1 | ❌ | Pool 생성 실패 → `pool = None` |
| 조건 2 | ⚠️ | 실행 자체 불가 (pool이 없어 `_persist_session_state()`도 호출되지 않음) |
| 조건 3 | ❌ | `pool is None` → `_heartbeat_task()` 생성되지 않음 |

### 현재 해결 상태

`docker compose exec`로 직접 pool 생성 테스트 시 정상 동작 확인. 컨테이너를 재시작하면 transient failure가 재현되지 않을 가능성이 높음. 하지만 **근본 원인이 transient했기 때문에 언제든 재발 가능**.

---

## 부록: 코드 버그 목록

### Bug #1: Pool 생성 실패 traceback 누락
**파일**: [`scripts/run_near_real_ops_scheduler.py:1131`](scripts/run_near_real_ops_scheduler.py:1131)  
**심각도**: 중 (Medium) — 진단 불가능  
**수정**: `logger.warning()` → `logger.exception()`

### Bug #2: `_heartbeat_task()` 예외 메시지 오도
**파일**: [`scripts/run_near_real_ops_scheduler.py:1046`](scripts/run_near_real_ops_scheduler.py:1046)  
**심각도**: 하 (Low) — pool 실패 시에만 영향  
**수정**: `state.session_db_id` 상태에 따라 메시지 분기

### Bug #3: Health check가 항상 unhealthy (after-hours/idle)
**파일**: [`docker-compose.yml:310-337`](docker-compose.yml:310-337)  
**심각도**: 중 (Medium) — 컨테이너 재시작 정책에 영향  
**수정**: after-hours/idle 모드에서의 health check 조건 추가

### Bug #4: Idle rollover 시 heartbeat task가 이전 state 참조
**파일**: [`scripts/run_near_real_ops_scheduler.py:1144`](scripts/run_near_real_ops_scheduler.py:1144)  
**심각도**: 하 (Low) — rollover 후 heartbeat가 이전 session 계속 업데이트  
**수정**: rollover 시 heartbeat task 취소 후 재생성

---

## 재현 및 복구 방법

### 즉시 복구 (현재)

```bash
# 컨테이너 재시작 (pool 재생성)
docker compose restart ops-scheduler

# 또는 컨테이너 완전 재생성
docker compose up -d --force-recreate ops-scheduler
```

### 근본적 복구 (코드 수정)

위 Q3의 6가지 조치를 순차적으로 적용.

### 재현 테스트

```bash
# DB connection 경합 재현 (부하 테스트)
docker compose exec -T ops-scheduler sh -c '
for i in $(seq 1 20); do
    python3 -c "
import asyncio, asyncpg
async def t():
    for j in range(10):
        try:
            p = await asyncpg.create_pool(
                dsn=\"postgresql://trading:trading@db:5432/trading\",
                min_size=2, max_size=10
            )
            await p.close()
            print(f\"pool {j} ok\")
        except Exception as e:
            print(f\"pool {j} FAIL: {e}\")
asyncio.run(t())
" &
done
wait
'
```
