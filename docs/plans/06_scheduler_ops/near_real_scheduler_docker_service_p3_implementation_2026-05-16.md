# P3: `run_near_real_ops_scheduler` → Docker Scheduler Service 승격 — 구현 보고서

**작성일**: 2026-05-16  
**담당자**: Roo (Code Mode)  
**관련 이슈**: P3 — near-real ops scheduler Docker 서비스화

---

## 1. 개요

기존 `scripts/run_ops_scheduler.py`는 수동/장기 실행 스크립트로만 동작했습니다.  
이를 Docker Compose 기반 전용 스케줄러 서비스로 승격하여 다음 요구사항을 충족합니다.

---

## 2. 변경 파일 요약

| 파일 | 변경 유형 | 설명 |
|------|-----------|------|
| `docker-compose.yml` | 수정 | `near-real-scheduler` 서비스 추가, `snapshot-sync.restart` → `"no"` |
| `src/agent_trading/services/market_session.py` | 수정 | `try_scheduler_lock()` asynccontextmanager + `SCHEDULER_ADVISORY_LOCK_KEY` 상수 추가 |
| `scripts/run_ops_scheduler.py` | 수정 | DSN 빌드, Heartbeat, Startup 로깅, Advisory Lock 통합 |
| `tests/services/test_market_session.py` | 수정 | `try_scheduler_lock` 5개 테스트 추가 |
| `tests/scripts/test_run_ops_scheduler.py` | 수정 | `_build_dsn` 5개, `_heartbeat_task` 3개, `_log_startup_info` 2개 테스트 추가 |

---

## 3. 상세 구현 내역

### 3.1 `docker-compose.yml` — `near-real-scheduler` 서비스

- **Container name**: `agent_trading-scheduler`
- **Command**: `python3 scripts/run_ops_scheduler.py`
- **Restart policy**: `unless-stopped`
- **Depends on**: `db` (health check 통과 후)
- **환경 변수**:
  - `DATABASE_URL` — asyncpg 직접 연결 DSN (우선순위 1)
  - DB 호스트/포트/이름/유저/패스워드 — `_build_dsn()` fallback (우선순위 2~3)
  - `KIS_PAPER_*` — 모의투자 API 자격증명
  - `KIS_LIVE_INFO_*` — 076/163 실전 시장 정보
  - `SCHEDULER_AFTER_HOURS_WINDOW`, `SCHEDULER_INSTANCE_ID` — 스케줄러 전용 설정
- **볼륨 마운트**: `logs/`, `.cache/`, `data/`
- **Healthcheck**: 60초 간격으로 `trading.market_sessions.last_heartbeat_at` 최근 120초 이내 확인
- **네트워크**: `default`

### 3.2 `docker-compose.yml` — `snapshot-sync` 역할 정리

- `restart: "no"` (기존 `unless-stopped`)
- 상단에 주석 추가: manual/debug 전용, primary orchestration은 `near-real-scheduler`가 담당

### 3.3 `market_session.py` — `try_scheduler_lock()`

- **상수**: `SCHEDULER_ADVISORY_LOCK_KEY = 0x4E454152_5245414C` ("NEAR_REAL" 인코딩)
- **함수**: `try_scheduler_lock(pool)` asynccontextmanager
  - `pg_try_advisory_lock()` — non-blocking lock 시도
  - `pg_advisory_unlock()` — 컨텍스트 종료 시 unlock
  - `acquired: bool` yield — True면 lock 획득 성공, False면 다른 인스턴스가 선점
- **장점**:
  - 컨테이너 강제 종료 시 PostgreSQL이 자동으로 lock 해제
  - 분산 환경에서도 duplicate 실행 방지
  - Non-blocking이므로 lock 대기 없이 즉시 판단 가능

### 3.4 `run_ops_scheduler.py` — 주요 변경사항

#### 3.4.1 `_build_dsn(env)`

환경변수로부터 asyncpg DSN을 3단계 우선순위로 해석:

1. `DATABASE_URL` (최우선)
2. `DATABASE_DSN` (2순위)
3. `DATABASE_HOST` + `DATABASE_PORT` + `DATABASE_NAME` + `DATABASE_USER` + `DATABASE_PASSWORD` 조합 (3순위)

```python
def _build_dsn(env: dict[str, str]) -> str | None:
    dsn = env.get("DATABASE_URL") or env.get("DATABASE_DSN")
    if dsn:
        return dsn
    host = env.get("DATABASE_HOST")
    if not host:
        return None
    port = env.get("DATABASE_PORT", "5432")
    name = env.get("DATABASE_NAME", "trading")
    user = env.get("DATABASE_USER", "trading")
    password = env.get("DATABASE_PASSWORD", "trading")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"
```

#### 3.4.2 `_heartbeat_task(state, pool)`

10초 간격으로 `trading.market_sessions.last_heartbeat_at`을 갱신하는 백그라운드 태스크:

- `session_db_id`가 `None`이면 heartbeat skip (session이 아직 persist되지 않은 상태)
- `CancelledError`는 그대로 상위로 전파 (정상 종료)
- 기타 Exception은 `logger.debug`로 무시 (일시적 DB 불안정 대응)

#### 3.4.3 `_log_startup_info(env, state, pool_ok)`

스케줄러 시작 시 다음 정보를 한 번에 로깅:

- KIS 환경 (`KIS_ENV`)
- Live-info 설정 (`KIS_LIVE_INFO_ENABLED`, APP_KEY 존재 여부)
- Session source (`session_source`)
- After-hours window
- Instance ID
- Run date
- DB pool 연결 상태
- Advisory lock key (hex)

#### 3.4.4 Advisory Lock 통합 (`_run_scheduler`)

```python
async with try_scheduler_lock(pool) as acquired:
    if not acquired:
        logger.warning("Scheduler lock held by another instance — exiting")
        return 1
    # ... _run_with_lock() 내부 로직 ...
```

Lock 획득 실패 시 즉시 exit code 1 반환.

---

## 4. 테스트 결과

### 4.1 신규 테스트 (15개)

| 테스트 클래스 | 테스트명 | 설명 |
|--------------|----------|------|
| `TestTrySchedulerLock` (5) | `test_acquires_lock` | Lock 획득 성공 |
| | `test_lock_already_held` | Lock 이미 선점 → False |
| | `test_lock_acquire_query_uses_correct_key` | SQL에 올바른 lock key 전달 |
| | `test_lock_release_query_uses_correct_key` | SQL에 올바른 unlock key 전달 |
| | `test_lock_released_on_exception` | 예외 발생 시에도 unlock 실행 |
| `TestBuildDsn` (5) | `test_falls_back_to_individual_vars` | 개별 변수 조합 |
| | `test_uses_defaults_when_missing` | 기본값 사용 |
| | `test_database_url_takes_priority` | DATABASE_URL 우선순위 |
| | `test_uses_database_dsn_as_second_priority` | DATABASE_DSN 2순위 |
| `TestHeartbeatTask` (3) | `test_updates_db_when_session_exists` | DB heartbeat UPDATE |
| | `test_skips_when_no_session` | session 없으면 skip |
| | `test_handles_db_error_gracefully` | DB 에러 시 태스크 유지 |
| `TestLogStartupInfo` (2) | `test_logs_all_fields` | 모든 필드 로깅 |
| | `test_logs_pool_not_connected` | pool 미연결 상태 로깅 |

### 4.2 전체 테스트 결과

```
90 passed in 5.38s
```

기존 75개 + 신규 15개 = **90/90 통과**

---

## 5. Docker 빌드 검증

### 5.1 Compose 설정 검증

```bash
$ docker compose config -q
# Exit code: 0 (유효한 설정)
```

### 5.2 이미지 빌드

```bash
$ docker compose build near-real-scheduler
# Image: agent_trading-app:latest
# Build time: 6.8s
# Exit code: 0 (성공)
```

---

## 6. 아키텍처 다이어그램

```
┌──────────────────────────────────────────────────┐
│                   Docker Compose                  │
│                                                    │
│  ┌──────────┐    ┌──────────────┐                 │
│  │    db    │◄───│  near-real-   │                 │
│  │PostgreSQL│    │  scheduler   │                 │
│  │  :5432   │    │  :healthcheck│                 │
│  └────┬─────┘    └──────┬───────┘                 │
│       │                 │                          │
│       │   advisory      │ advisory lock            │
│       │   lock (SELECT  │ (pg_try_advisory_lock)   │
│       │   pg_try_       │ + heartbeat              │
│       │   advisory_lock)│ (UPDATE last_heartbeat_at)│
│       │                 │                          │
│  ┌────┴─────┐    ┌──────┴───────┐                 │
│  │   app    │    │ snapshot-sync│                 │
│  │ (dev)    │    │ (manual)     │                 │
│  └──────────┘    └──────────────┘                 │
└──────────────────────────────────────────────────┘
```

---

## 7. 완료 기준 검증

| # | 기준 | 상태 |
|---|------|------|
| 1 | `docker-compose.yml`에 `near-real-scheduler` 서비스 정의 | ✅ |
| 2 | `DATABASE_URL` 또는 개별 DB 변수로 연결 가능 | ✅ |
| 3 | DB Advisory Lock (`try_scheduler_lock`)으로 중복 실행 방지 | ✅ |
| 4 | `last_heartbeat_at` 10초 간격 갱신 | ✅ |
| 5 | 컨테이너 강제 종료 시 lock 자동 해제 (PG 세션 종료) | ✅ |
| 6 | `docker compose config -q` 통과 | ✅ |
| 7 | `docker compose build near-real-scheduler` 통과 | ✅ |
| 8 | 모든 신규 테스트 통과 (15개) | ✅ |
| 9 | 모든 기존 테스트 회귀 없음 (75개) | ✅ |
| 10 | `snapshot-sync.restart: "no"` + 주석 정리 | ✅ |

---

## 8. 운영 참고사항

1. **Lock 경합**: 동일 PG 클러스터 내에서는 오직 하나의 scheduler 인스턴스만 lock 획득 가능
2. **Healthcheck 실패**: heartbeat이 120초 이상 갱신되지 않으면 컨테이너 재시작 필요
3. **로그 위치**: `logs/` 볼륨 마운트 — 호스트에서 직접 확인 가능
4. **수동 실행**: `docker compose run --rm near-real-scheduler python3 scripts/run_ops_scheduler.py --once`
