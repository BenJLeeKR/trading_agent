# Snapshot Sync Runtime Writer 정밀 추적 보고

## 최신 row null 직접 원인

**`agent_trading-snapshot-sync-1` 컨테이너가 24시간 전의 구버전 코드로 실행 중이었음.**

컨테이너는 bind mount (`/workspace/agent_trading/scripts` → `/app/scripts`, `/workspace/agent_trading/src` → `/app/src`)를 사용하지만, Python 프로세스는 시작 시점에 모든 모듈을 메모리에 로드하므로 파일이 변경되어도 재시작 전까지는 반영되지 않음.

| 항목 | 상세 |
|------|------|
| 컨테이너 | `agent_trading-snapshot-sync-1` (23시간 57분 실행) |
| 명령어 | `python3 scripts/run_snapshot_sync_loop.py --after-hours` |
| 실행 중이던 코드 | `summary_json=counters` **없는** 구버전 |
| 구버전 코드가 저장한 값 | `summary_json=None` → DB `null` |

## 실제 row 생성 실행 경로

```
agent_trading-snapshot-sync-1 (standalone container, 24h uptime)
  └─ python3 scripts/run_snapshot_sync_loop.py --after-hours    (PID 1)
       └─ _run_one_cycle()  [300초 간격 무한 루프]
            ├─ sync_all_accounts()            ← snapshot_sync.py
            ├─ get_budget_fallback_counters() ← ❌ 구버전에서 누락
            ├─ build_sync_run_entity(..., summary_json=counters) ← ❌ 구버전에서 누락
            └─ repos.snapshot_sync_runs.add(run_entity)
                 └─ json.dumps(run.summary_json) ← ❌ 구버전: run.summary_json=None → raw None 전달
```

### 보조 경로 (영향 없음)

- `run_near_real_ops_scheduler.py` (ops-scheduler 컨테이너) — `run_snapshot_sync_loop.py`를 subprocess로 실행하지만, **scheduler가 즉시 end_time 도달로 idle 모드 진입**하여 snapshot sync를 실행하지 않음. 로그에 `tasks: 0` 확인됨.
- `sync_kis_snapshots.py` — manual 전용 스크립트, 주기적 실행 없음.

## 적용한 수정 (이전 작업에서 완료)

### 1. `scripts/run_snapshot_sync_loop.py` (commit HEAD)

```python
# 추가된 import
from agent_trading.services.snapshot_sync import get_budget_fallback_counters

# _run_one_cycle() 내 추가
counters = get_budget_fallback_counters()
run_entity = build_sync_run_entity(
    ...
    summary_json=counters,  # 추가됨
)
```

### 2. `src/agent_trading/repositories/postgres/snapshot_sync_runs.py` (commit HEAD)

```python
# 변경 전
run.summary_json,

# 변경 후
json.dumps(run.summary_json) if run.summary_json is not None else json.dumps({}),
```

### 3. 컨테이너 재시작

```bash
docker compose restart snapshot-sync
```

기존 컨테이너는 24시간 전 구버전 코드를 메모리에 로드한 상태였으므로, 재시작을 통해 최신 코드 반영.

## 엔드투엔드 검증

### DB 검증 결과

| 시간 (KST) | summary_json | 결과 |
|-----------|-------------|------|
| 2026-05-23 21:35:41 | `{"after_hours_skip":1, "VTTC8908R_pre_check":0, ...}` | ✅ |
| 2026-05-23 21:30:41 | `{"after_hours_skip":1, "VTTC8908R_pre_check":0, ...}` | ✅ |
| 2026-05-23 21:25:40 | `{"after_hours_skip":1, "VTTC8908R_pre_check":0, ...}` | ✅ |
| 2026-05-23 21:21:35 | `null` (구버전) | 개선됨 |
| 2026-05-23 20:20:02 | `{"after_hours_skip":0, "VTTC8908R_pre_check":1, ...}` | 기존 유일 non-null |

### non_null count 증가

- 수정 전: 1개 (1877개 중)
- 수정 후: 4개 (1880개 중, 계속 증가 중) 📈

### 테스트 결과

- 101 passed, 1 failed (`test_external_events` — snapshot sync와 무관)
- snapshot sync 관련 테스트는 모두 통과

## 근본 원인 요약

코드 변경사항이 정확했음에도 DB에 반영되지 않은 이유는 **`agent_trading-snapshot-sync-1` standalone 컨테이너가 24시간 전에 시작되어 메모리에 구버전 코드를 로드한 상태로 계속 실행 중이었기 때문.** bind mount로 파일은 동기화되지만, 이미 실행 중인 Python 프로세스는 재시작 전까지 변경사항을 인식하지 못함.

→ `docker compose restart snapshot-sync` 한 번으로 완전 해결.
