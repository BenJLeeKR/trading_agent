# KIS Snapshot Sync Cadence 리팩토링 — Scheduler Coupling 완화

## 1. 현재 9~12분대 gap의 직접 원인

### 구조적 문제: `_run_intraday_due_tasks()` 순차 실행

**직접 coupling**:
```
snapshot_sync → event_ingestion → decision_submit_gate(600s timeout) → post_submit_sync
```

- 모든 task 사이에 `asyncio.sleep()`이 없음
- `decision_submit_gate`가 600s timeout으로 설정되어 있어, 장기 실행 시 snapshot 다음 cycle이 10분+로 밀림

### 실제 관측 (2026-05-15 운영 로그)

| 항목 | 값 |
|------|-----|
| decision_submit_gate 평균 실행 시간 | ~180초 |
| snapshot cadence | ~5분 (현재는 decision이 빠르게 완료되어 유지 중) |
| 구조적 위험 | decision_submit_gate timeout(600s)에 걸리면 cadence가 즉시 10분+로 붕괴 |

## 2. 적용한 Cadence 구조 변경

### 변경 1: Snapshot due 체크를 메인 루프로 분리 (P0)

**변경 전**: `_run_intraday_due_tasks()` 내부에서 snapshot/event/decision/post_submit 순차 실행
**변경 후**: snapshot은 메인 루프에서 `_session_gate()`와 독립적으로 due 체크

```python
# 메인 루프
if intraday_at <= now < market_close_at:
    # snapshot은 별도 due 체크 (decision과 무관)
    if tasks["snapshot"].due:
        await _run_and_record(state, "snapshot_sync", _snapshot_command(), ...)
        tasks["snapshot"].mark_ran(now)
    
    # 나머지 task는 session_gate 조건
    if await _session_gate(...):
        await _run_intraday_due_tasks(state, tasks, ...)  # event/decision/post_submit만
```

**효과**: snapshot cadence가 `decision_submit_gate` timeout과 완전히 독립적

### 변경 2: `ScheduledTask` 리팩토링

- `due()` 메서드를 `@property`로 변경
- `last_run_at` 필드 추가 — `last_run_at + interval` 단일 기준으로 due 판단
- `mark_ran()`이 `last_run_at` 갱신

### 변경 3: `_DECISION_TIMEOUT` 600s → 300s (P1)

- 내부 subprocess의 `PER_AGENT_HARD_TIMEOUT=300s`와 일치
- 실제 운영 로그(180s) 기준으로 충분한 여유

### 변경 4: `fetch_positions` 파라미터 Plumbing (P2)

- `sync_accounts_by_ids()`에 `fetch_positions: bool = True` 추가
- `run_snapshot_sync_loop.py`에 `--fetch-positions` argparse 추가
- 향후 cash/positions cadence 분리 기반 마련

## 3. Trace/Log 변경 내용

### CADENCE_TRACE 로그 포맷

**snapshot 실행 시**:
```
CADENCE_TRACE snapshot_sync symbol=ALL action=start due_at=... last_run_gap=...s target_interval=...s drift=...s
CADENCE_TRACE snapshot_sync symbol=ALL action=complete completed_at=...
```

**decision_submit_gate 실행 시** (동일 포맷):
```
CADENCE_TRACE decision_submit_gate symbol=ALL action=start due_at=... last_run_gap=...s target_interval=...s drift=...s
```

### 검증 필드
- `last_run_gap`: 이전 실행과의 실제 간격 (초)
- `target_interval`: 목표 interval (snapshot=300s, decision=300s)
- `drift`: 실제 gap - 목표 interval (양수면 지연)

## 4. 테스트 결과

### 신규 테스트 (11개)

| 클래스 | 테스트 | 설명 |
|--------|--------|------|
| TestScheduledTask (6개) | due 최초 실행 True | `last_run_at=None` → `due=True` |
| | due interval 이내 False | 실행 후 300초 이내 → `due=False` |
| | due interval 경과 True | 실행 후 300초 경과 → `due=True` |
| | mark_ran 갱신 | `mark_ran()` 호출 시 `last_run_at` 갱신 |
| | 다중 cycle | due→mark_ran→due→mark_ran 반복 |
| TestBuildTasks (2개) | 4개 task 생성 | snapshot/event/decision/post_submit |
| | interval 차이 | post_submit 30s vs 나머지 300s |
| TestCadenceTraceLogging (3개) | snapshot trace 포맷 | `CADENCE_TRACE snapshot_sync` 문자열 검증 |
| | decision trace 포맷 | `CADENCE_TRACE decision_submit_gate` 문자열 검증 |
| | first run gap=0 | 최초 실행 시 `last_run_gap=0` |

### 전체 테스트 통과

| 범위 | 결과 |
|------|------|
| `test_run_near_real_ops_scheduler.py` | **105/105 통과** |
| `tests/scripts/` 전체 | **405/408 통과** (3건 pre-existing) |

## 5. 수정한 파일 목록

| 파일 | 변경 내용 |
|------|-----------|
| `scripts/run_near_real_ops_scheduler.py` | Snapshot 분리 + CADENCE trace + `_DECISION_TIMEOUT` 300s + `ScheduledTask` 리팩토링 |
| `scripts/run_snapshot_sync_loop.py` | `--fetch-positions` argparse 추가 |
| `src/agent_trading/services/snapshot_sync.py` | `sync_accounts_by_ids()`에 `fetch_positions` 파라미터 추가 |
| `tests/scripts/test_run_near_real_ops_scheduler.py` | 11개 신규 테스트 추가 |

## 6. 주말 후 운영 검증 포인트

### 확인할 로그 패턴

1. **Snapshot cadence 안정성**
   ```
   grep "CADENCE_TRACE snapshot_sync" logs/near_real_scheduler_*.log
   ```
   - `last_run_gap`이 300s(5분) 내외로 안정적인지 확인
   - `drift` 값이 0에 근접하는지 확인

2. **Decision gate 독립성**
   ```
   grep "CADENCE_TRACE decision_submit_gate" logs/near_real_scheduler_*.log
   ```
   - decision gate 실행 시간이 snapshot cadence에 영향을 주지 않는지 확인

3. **`_DECISION_TIMEOUT` 300s 적정성**
   - decision_submit_gate가 300s timeout에 걸리지 않는지 확인
   - HP sell 활성화 시 모니터링 필요

4. **비정상 케이스 모니터링**
   - `drift`가 지속적으로 60s 이상인 경우 → cadence 붕괴 징후
   - `action=start` 로그 없이 snapshot이 누락된 경우
