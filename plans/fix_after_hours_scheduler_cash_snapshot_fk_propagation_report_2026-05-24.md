# after-hours 스케줄러 cash snapshot FK NULL 문제 — 근본 원인 분석 및 해결 보고서

## 요약

**문제**: after-hours 스케줄러가 저장하는 `cash_balance_snapshots`의 `snapshot_sync_run_id` FK가 `NULL`로 저장됨.
**원인**: `snapshot-sync-1` 컨테이너가 two-phase fix 적용 **이전** (2026-05-22)에 시작되어, Python 프로세스가 구버전 코드를 메모리에 유지.
**해결**: `docker compose restart snapshot-sync` 실행 → 연속 3회 after-hours cycle FK 정상 검증 완료.

---

## 1. 문제 정의

### 1.1 증상
- ops-scheduler after-hours cycle로 저장된 `cash_balance_snapshots`의 `snapshot_sync_run_id`가 `NULL`
- `position_snapshots`은 정상적으로 FK 설정됨
- 수동 `docker exec` 실행 시 FK 정상 설정

### 1.2 사용자 요구사항
- "특정 수동 실행 1건 성공으로 완료 판정하지 말 것"
- "연속 최신 row 기준 non-null 증명"
- 최소 2~3회 연속 after-hours cycle 후 DB 최신 cash row FK non-null 확인

---

## 2. DB 상태 증상 확인 (2026-05-24 00:02 UTC)

```sql
SELECT cash_balance_snapshot_id, snapshot_sync_run_id, created_at
FROM trading.cash_balance_snapshots
WHERE created_at >= '2026-05-23 21:30:00+00'
ORDER BY created_at DESC;
```

결과: 31개 cash snapshot 중 **3개만 FK 설정**, 나머지 28개는 NULL.
FK 설정된 3개는 모두 수동 `docker exec` 또는 ops-scheduler 정규(비 after-hours) subprocess 실행.

---

## 3. 코드 경로 분석

### 3.1 Two-phase fix 적용 위치

[`scripts/run_snapshot_sync_loop.py`](scripts/run_snapshot_sync_loop.py:183) — `_run_one_cycle()`:

```
Phase 1: INSERT sync run (status='running')  ← FK 참조 대상 생성
Phase 2: sync_all_accounts(... snapshot_sync_run_id=run_id)  ← snapshot 저장 시 FK 설정
Phase 3: UPDATE sync run (status, summary)  ← 실행 결과 기록
```

### 3.2 after-hours 실행 경로

**경로 A** — ops-scheduler subprocess:
[`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py:646) → `_snapshot_command()` → `asyncio.create_subprocess_exec()` → 새 Python 프로세스 → 최신 코드 로드 → FK 정상

**경로 B** — snapshot-sync-1 독립 컨테이너:
`docker-compose.yml` → `profiles: ["debug"]` → 항상 실행 중인 데몬 프로세스
→ Python 프로세스 재시작 전까지 메모리에 **구버전 코드** 유지

### 3.3 `SnapshotSyncRunEntity` FK 할당 위치

[`src/agent_trading/services/snapshot_sync.py`](src/agent_trading/services/snapshot_sync.py:239):

```python
if snapshot_sync_run_id is not None:
    for pos in fetched.positions:
        object.__setattr__(pos, "snapshot_sync_run_id", snapshot_sync_run_id)
    if fetched.cash_balance is not None:
        object.__setattr__(fetched.cash_balance, "snapshot_sync_run_id", snapshot_sync_run_id)
```

이 코드는 **이미 two-phase fix가 적용된 `_run_one_cycle()`에서만** 호출됨.
구버전 코드에서는 `snapshot_sync_run_id` 파라미터 자체가 존재하지 않음.

---

## 4. 근본 원인

### 4.1 컨테이너 생성 시점 차이

| 컨테이너 | 생성 시간 | Fix 적용 |
|---------|-----------|---------|
| `agent_trading-ops-scheduler-1` | 2026-05-23T10:50:35 | ✅ (fix 이후 재시작) |
| `agent_trading-snapshot-sync-1` | 2026-05-22T12:39:53 | ❌ (fix 이전 코드) |

### 4.2 Python 프로세스 모듈 캐싱

- `docker-compose.yml`의 `volumes`로 호스트 파일이 컨테이너에 bind mount됨
- `./scripts:/app/scripts`, `./src:/app/src`
- **그러나** Python은 프로세스 시작 시 모듈을 한 번 로드하여 메모리에 캐싱
- bind mount로 파일 내용이 변경되어도 **실행 중인 프로세스는 재시작 전까지 구버전 코드 사용**
- `docker exec`는 **새 프로세스**를 생성하므로 항상 최신 코드 로드

### 4.3 확인 근거

1. `snapshot-sync-1` 컨테이너 로그에서 `DEBUG_FK` 로그 **0건** (컨테이너 재시작 전)
2. ops-scheduler 로그에서 `DEBUG_FK` 로그 정상 출력 (최신 코드)
3. 컨테이너 재시작 직후 첫 cycle부터 `DEBUG_FK` 로그 출력 시작
4. `docker ps` 출력에서 컨테이너 생성 시간 `12:39:53` (fix PR 이전)

---

## 5. 해결 조치

### 5.1 컨테이너 재시작

```bash
docker compose restart snapshot-sync
```

### 5.2 연속 검증 결과

| 시간 (UTC) | Cycle | 경로 | FK | 비고 |
|-----------|-------|------|----|------|
| 00:16:08 | - | snapshot-sync-1 | ❌ NULL | 재시작 **전** 구버전 코드 |
| 00:16:19 | - | ops-scheduler subprocess | ✅ | 정규 task |
| **00:19:08** | **1** | **snapshot-sync-1** | **✅** | **재시작 후 첫 cycle** |
| 00:24:09 | 2 | snapshot-sync-1 | ✅ | 연속 성공 |
| 00:26:27 | - | ops-scheduler subprocess | ✅ | 정규 task |
| **00:29:09** | **3** | **snapshot-sync-1** | **✅** | **연속 3회 성공** |

---

## 6. 장기 조치 제안

### 6.1 `docker-compose.yml` 개선

```yaml
snapshot-sync:
  restart: unless-stopped
  healthcheck:
    test: ["CMD", "python3", "-c", "import sys; sys.exit(0)"]
    interval: 30s
    timeout: 5s
    retries: 3
```

### 6.2 배포 프로세스 개선

- 코드 변경 후 `snapshot-sync` 컨테이너 재시작을 배포 스크립트에 포함
- 또는 `docker compose up -d --force-recreate snapshot-sync` 사용

### 6.3 모니터링

- after-hours cash snapshot FK NULL 여부를 ops-alert에 포함
- `snapshot_sync_run_id IS NULL` 쿼리로 조기 감지

---

## 7. 관련 파일

| 파일 | 설명 |
|------|------|
| [`scripts/run_snapshot_sync_loop.py`](scripts/run_snapshot_sync_loop.py:183) | Two-phase fix 적용 (sync run 선 INSERT → snapshot → UPDATE) |
| [`src/agent_trading/services/snapshot_sync.py`](src/agent_trading/services/snapshot_sync.py:239) | FK 할당 로직 (`snapshot_sync_run_id` 파라미터) |
| [`src/agent_trading/repositories/postgres/cash_balance_snapshots.py`](src/agent_trading/repositories/postgres/cash_balance_snapshots.py:24) | Cash snapshot 저장 (변경 없음, entity의 FK 필드 직접 사용) |
| [`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py:646) | ops-scheduler after-hours subprocess 실행 |
| [`docker-compose.yml`](docker-compose.yml) | snapshot-sync 컨테이너 정의 |
| [`src/agent_trading/domain/entities.py`](src/agent_trading/domain/entities.py:138) | `CashBalanceSnapshotEntity` (`snapshot_sync_run_id` 필드) |

---

## 8. 결론

**근본 원인**: after-hours 전용 `snapshot-sync-1` 컨테이너가 2026-05-22 (two-phase fix 적용 이전)에 시작되어, Python 프로세스가 구버전 코드를 메모리에 유지함으로써 `snapshot_sync_run_id` FK를 cash snapshot에 설정하지 못함.

**해결**: `docker compose restart snapshot-sync` 실행. 이후 **연속 3회** after-hours cycle에서 FK 정상 설정 확인 완료.

**재발 방지**: 배포 프로세스에 snapshot-sync 컨테이너 재시작 포함 필요.
