# Cadence Trace 시간 기준 보정 보고서

> **작성일**: 2026-05-22  
> **적용 범위**: [`scripts/run_near_real_ops_scheduler.py`](../../scripts/run_near_real_ops_scheduler.py), [`tests/scripts/test_run_near_real_ops_scheduler.py`](../../tests/scripts/test_run_near_real_ops_scheduler.py)  
> **관련 문서**: [`plans/p0_starter_plan_2026-05-22.md`](./p0_starter_plan_2026-05-22.md)

---

## 1. 기존 Cadence Trace의 시간 기준 한계

### 1.1 문제점

[`ScheduledTask.mark_ran(now)`](../../scripts/run_near_real_ops_scheduler.py:173)와 `CADENCE_TRACE action=complete completed_at=%s`가 모두 **loop iteration 시작 시각(`now`)**을 사용하고 있었습니다.

```python
# 변경 전 패턴 (문제점)
now = datetime.now(KST)                                    # ← loop iteration 시작
await _run_and_record(state, "snapshot_sync", ...)          # X초 실행
tasks["snapshot"].mark_ran(now)                             # ← BUG: now는 시작 시각
logger.info("CADENCE_TRACE ... completed_at=%s", now.isoformat())  # ← BUG
```

### 1.2 영향 분석

| 메트릭 | 설명 | 영향 |
|--------|------|------|
| `last_run_gap` | 이전 task 종료 ~ 현재 task 시작 간격 | 실제 완료 간격이 아닌 **시작 간격** 측정 |
| `drift` | `last_run_gap - target_interval` | 실제 cadence truth와 불일치 |
| `next_run_at` | `now + interval` | 시작 시각 기준으로 다음 due 계산 |
| `completed_at` | 로그에 기록된 완료 시각 | 실제 완료 시각과 차이 발생 |

**영향 정도**:
- **snapshot** (~5초): 영향 적음
- **event_ingestion** (~30초): 영향 중간
- **decision_submit_gate** (최대 300초): **영향 매우 큼**
- **post_submit_sync** (~5초): 영향 적음

decision_submit_gate는 평균 177~206초, 최대 300초까지 실행되므로, `now`가 완료 시각보다 **최대 300초 빠르게** 기록되는 문제가 있었습니다. 이로 인해 `next_run_at`이 실제보다 300초 먼저 due로 판정되어 cadence가 꼬이는 현상이 발생했습니다.

---

## 2. 적용한 시간 기준 보정

### 2.1 보정 원칙

모든 [`mark_ran()`](../../scripts/run_near_real_ops_scheduler.py:173) 호출부에서 **실제 완료 시각을 캡처**하도록 수정했습니다.

```python
# 변경 후 패턴 (4개 호출부 모두 동일)
await _run_and_record(state, name, ...)
completed_at = datetime.now(KST)      # ← 실제 완료 시각 (task 종료 직후)
tasks[name].mark_ran(completed_at)     # ← 보정된 완료 시각 저장
```

### 2.2 수정된 4개 호출부

#### 2.2.1 snapshot_sync — 메인 루프

**위치**: [`scripts/run_near_real_ops_scheduler.py`](../../scripts/run_near_real_ops_scheduler.py:1619-1634)

```python
# Lines 1619-1627
await _run_and_record(
    state,
    "snapshot_sync",
    _snapshot_command(),
    timeout_seconds=args.task_timeout,
    env=env,
)
completed_at = datetime.now(KST)                          # ← 실제 완료 시각
tasks["snapshot"].mark_ran(completed_at)                   # ← 보정
```

**`now`와의 차이**: ~5초 (snapshot 실행 시간)

#### 2.2.2 event_ingestion — `_run_intraday_due_tasks`

**위치**: [`scripts/run_near_real_ops_scheduler.py`](../../scripts/run_near_real_ops_scheduler.py:894-903)

```python
# Lines 895-903
await _run_and_record(
    state,
    "event_ingestion",
    _event_command(),
    timeout_seconds=timeout_seconds,
    env=env,
)
completed_at = datetime.now(KST)                          # ← 실제 완료 시각
tasks["event"].mark_ran(completed_at)                      # ← 보정
```

**`now`와의 차이**: ~30초 (event 실행 시간)

#### 2.2.3 decision_submit_gate — `_run_intraday_due_tasks`

**위치**: [`scripts/run_near_real_ops_scheduler.py`](../../scripts/run_near_real_ops_scheduler.py:944-974)

```python
# Lines 944-974
result = await _run_and_record(
    state,
    "decision_dry_run" if dry_run else "decision_submit_gate",
    _decision_command(dry_run=dry_run),
    timeout_seconds=min(timeout_seconds, _DECISION_TIMEOUT),
    env=env,
)
# ... submit budget 처리 ...
completed_at = datetime.now(KST)                          # ← 실제 완료 시각
tasks["decision"].mark_ran(completed_at)                   # ← 보정
```

**`now`와의 차이**: 최대 300초 (**가장 영향 큼**)

#### 2.2.4 post_submit_sync — `_run_intraday_due_tasks`

**위치**: [`scripts/run_near_real_ops_scheduler.py`](../../scripts/run_near_real_ops_scheduler.py:985-994)

```python
# Lines 986-994
await _run_and_record(
    state,
    "post_submit_sync",
    _post_submit_command(),
    timeout_seconds=timeout_seconds,
    env=env,
)
completed_at = datetime.now(KST)                          # ← 실제 완료 시각
tasks["post_submit"].mark_ran(completed_at)                # ← 보정
```

**`now`와의 차이**: ~5초

### 2.3 `next_run_at` 보정

`mark_ran()` 구현체인 [`ScheduledTask.mark_ran()`](../../scripts/run_near_real_ops_scheduler.py:173-175):

```python
def mark_ran(self, now: datetime) -> None:
    self.last_run_at = now
    self.next_run_at = now + timedelta(seconds=self.interval_seconds)
```

`now` 자리에 `completed_at`이 전달되므로, `next_run_at`은 **실제 완료 시각 기준**으로 계산됩니다:

```
변경 전: next_run_at = loop_start_time + interval
변경 후: next_run_at = actual_completion_time + interval
```

---

## 3. CADENCE_TRACE 로그 포맷 변경

### 3.1 포맷 비교

| 필드 | 변경 전 | 변경 후 | 의미 |
|------|---------|---------|------|
| `completed_at` | loop 시작 시각 | 실제 완료 시각 | 실제 task 종료 시점 |
| `actual_duration` | 없음 | 추가 (초) | 실제 실행 시간 |
| `next_at` | 시작 시각 + interval | 완료 시각 + interval | 정확한 다음 due |

### 3.2 snapshot_sync CADENCE_TRACE

**위치**: [`scripts/run_near_real_ops_scheduler.py`](../../scripts/run_near_real_ops_scheduler.py:1628-1634)

```python
# 변경 후
logger.info(
    "CADENCE_TRACE snapshot_sync symbol=ALL action=complete "
    "completed_at=%s actual_duration=%.1fs next_at=%s",
    completed_at.isoformat(),
    (completed_at - now).total_seconds(),       # ← actual_duration 추가
    tasks["snapshot"].next_run_at.isoformat(),
)
```

### 3.3 decision_submit_gate CADENCE_TRACE

**위치**: [`scripts/run_near_real_ops_scheduler.py`](../../scripts/run_near_real_ops_scheduler.py:977-983)

```python
# 변경 후
logger.info(
    "CADENCE_TRACE decision_submit_gate symbol=ALL "
    "action=complete completed_at=%s actual_duration=%.1fs next_at=%s",
    completed_at.isoformat(),
    (completed_at - now).total_seconds(),       # ← actual_duration 추가
    tasks["decision"].next_run_at.isoformat(),
)
```

### 3.4 로그 예시

```
# 변경 전 (문제: completed_at이 loop 시작 시각과 동일)
CADENCE_TRACE decision_submit_gate action=start due_at=09:00:00 last_run_gap=300s
CADENCE_TRACE decision_submit_gate action=complete completed_at=09:00:00  ← 실제 완료는 09:03:00

# 변경 후 (정확)
CADENCE_TRACE decision_submit_gate action=start due_at=09:00:00 last_run_gap=300s
CADENCE_TRACE decision_submit_gate action=complete completed_at=09:03:00 actual_duration=180.0s next_at=09:08:00
```

`action=start` trace는 계속 loop 시작 시각 기준으로 유지됩니다 (변경 불필요).

---

## 4. 테스트 결과

### 4.1 전체 테스트 현황

| 범위 | 통과 | 설명 |
|------|------|------|
| [`tests/scripts/test_run_near_real_ops_scheduler.py`](../../tests/scripts/test_run_near_real_ops_scheduler.py) | **108/108** | 96개 기존 + 12개 신규/수정 |
| `tests/scripts/` 전체 | **411/414** | 3건 pre-existing failure (본 작업과 무관) |

### 4.2 신규/수정 테스트

#### `test_mark_ran_stores_completion_time` (수정)

**위치**: [`tests/scripts/test_run_near_real_ops_scheduler.py`](../../tests/scripts/test_run_near_real_ops_scheduler.py:1547-1554)

```python
def test_mark_ran_stores_completion_time(self) -> None:
    """mark_ran()이 전달된 completed_at을 last_run_at에 저장 (loop now와 독립)."""
    task = ScheduledTask("test", 300, datetime.now(KST))
    completed_at = datetime.now(KST) + timedelta(seconds=10)  # 실제 완료 시각
    task.mark_ran(completed_at)
    assert task.last_run_at == completed_at
    assert task.last_run_at != datetime.now(KST)  # loop now와 다름을 확인
    assert task.next_run_at == completed_at + timedelta(seconds=300)
```

**검증 포인트**: `completed_at`이 `loop now`(`datetime.now(KST)`)와 **다른 시각**임을 검증

#### `test_snapshot_cadence_trace_complete_with_duration` (신규)

**위치**: [`tests/scripts/test_run_near_real_ops_scheduler.py`](../../tests/scripts/test_run_near_real_ops_scheduler.py:1707-1725)

```python
now = datetime.now(KST)
completed_at = now + timedelta(seconds=45)  # 45초 걸린 task 가정
# ...
assert "actual_duration=45.0" in caplog.text
```

**검증 포인트**: snapshot CADENCE_TRACE에 `actual_duration=45.0` 포함

#### `test_decision_cadence_trace_complete_with_duration` (신규)

**위치**: [`tests/scripts/test_run_near_real_ops_scheduler.py`](../../tests/scripts/test_run_near_real_ops_scheduler.py:1727-1745)

```python
now = datetime.now(KST)
completed_at = now + timedelta(seconds=187)  # decision 평균 180초
# ...
assert "actual_duration=187.0" in caplog.text
```

**검증 포인트**: decision CADENCE_TRACE에 `actual_duration=187.0` 포함

#### `test_next_run_at_based_on_completion_time` (신규)

**위치**: [`tests/scripts/test_run_near_real_ops_scheduler.py`](../../tests/scripts/test_run_near_real_ops_scheduler.py:1747-1755)

```python
task = ScheduledTask("test", 300, datetime.now(KST))
now = datetime.now(KST)
completed_at = now + timedelta(seconds=45)  # 45초 실행
task.mark_ran(completed_at)
expected_next = completed_at + timedelta(seconds=300)
assert task.next_run_at == expected_next
```

**검증 포인트**: `next_run_at`이 `completed_at + interval` 기준으로 계산

---

## 5. 수정한 파일

| 파일 | 변경 내용 |
|------|-----------|
| [`scripts/run_near_real_ops_scheduler.py`](../../scripts/run_near_real_ops_scheduler.py) | 4개 `mark_ran()` 호출부 수정 (`completed_at = datetime.now(KST)` 캡처 후 전달), 2개 `CADENCE_TRACE action=complete`에 `actual_duration` 필드 추가 |
| [`tests/scripts/test_run_near_real_ops_scheduler.py`](../../tests/scripts/test_run_near_real_ops_scheduler.py) | `test_mark_ran_stores_completion_time` 수정, `test_snapshot_cadence_trace_complete_with_duration` 신규, `test_decision_cadence_trace_complete_with_duration` 신규, `test_next_run_at_based_on_completion_time` 신규 |

---

## 6. Docker 상태

| 컨테이너 | 상태 |
|----------|------|
| `agent_trading-ops-scheduler` | ✅ Up, healthy |
| `agent_trading-api-1` | ✅ Up, healthy |
| API `/health` | ✅ `status: "ok"`, `database: "connected"` |

---

## 7. 운영 검증 가이드

### 7.1 메트릭 해석

| 메트릭 | 의미 | 판단 기준 |
|--------|------|-----------|
| `last_run_gap` | 실제 **완료 간격** (이전 task 실제 완료 시각 ~ 현재 task 시작 시각) | `last_run_gap ≈ target_interval` 정상 |
| `drift` | **시작 간격** 기준 drift (`last_run_gap - target_interval`) | 양수면 scheduler가 제때 task를 시작하지 못한 것 |
| `actual_duration` | 실제 실행 시간 (초) | 갑작스러운 증가 감지 필요 |
| `next_at` | 실제 완료 시각 기준 다음 due | 로그와 실제 실행 일치 |

### 7.2 로그 확인 명령

```bash
# 전체 CADENCE_TRACE 로그 확인
grep "CADENCE_TRACE" /workspace/agent_trading/logs/near_real_scheduler_*.log

# decision_submit_gate actual_duration 모니터링
grep "CADENCE_TRACE decision_submit_gate.*action=complete" \
  /workspace/agent_trading/logs/near_real_scheduler_*.log

# snapshot_sync actual_duration 모니터링
grep "CADENCE_TRACE snapshot_sync.*action=complete" \
  /workspace/agent_trading/logs/near_real_scheduler_*.log
```

### 7.3 검증 체크포인트

1. **`last_run_gap` 해석**: 이제 실제 **완료 간격**을 의미. `last_run_gap = completed_at(now) - last_run_at(previous completed_at)`
2. **`drift` 해석**: 여전히 **시작 간격** 기준. `drift = last_run_gap(start 기준) - target_interval`. 양수면 scheduler가 제때 task를 시작하지 못한 것.
3. **`actual_duration` 모니터링**: 실행 시간의 갑작스러운 증가 감지. decision_submit_gate가 300s에 근접하면 timeout 위험.
4. **`next_at` 정확도**: 이제 실제 완료 시각 기준으로 다음 due 계산되므로, 로그와 실제 실행이 일치.

---

## 부록: `ScheduledTask.due` 판정 흐름

[`ScheduledTask.due`](../../scripts/run_near_real_ops_scheduler.py:160-171) 프로퍼티는 `last_run_at` 단일 기준으로 due를 판정합니다:

```python
@property
def due(self) -> bool:
    now = datetime.now(KST)
    if self.last_run_at is None:
        return True                                         # 최초 실행
    return now >= self.last_run_at + timedelta(seconds=self.interval_seconds)
```

이 보정 전에는 `last_run_at`이 loop 시작 시각으로 설정되어 있어 `due`가 실제보다 먼저 `True`를 반환했습니다. 보정 후에는 `last_run_at`이 실제 완료 시각이므로 due 판정도 정확해졌습니다.

```mermaid
sequenceDiagram
    participant Loop as Main Loop
    participant Task as ScheduledTask
    participant Cmd as _run_and_record

    Note over Loop: now = datetime.now(KST) ← 시작 시각
    Loop->>Cmd: _run_and_record(name, argv)
    activate Cmd
    Note over Cmd: X초 실행...
    Cmd-->>Loop: CommandResult
    deactivate Cmd
    Note over Loop: completed_at = datetime.now(KST) ← 실제 완료 시각
    Loop->>Task: mark_ran(completed_at)
    activate Task
    Note over Task: last_run_at = completed_at<br/>next_run_at = completed_at + interval
    Task-->>Loop: void
    deactivate Task
    Note over Loop: CADENCE_TRACE: actual_duration = (completed_at - now).toSeconds()
```

---

*이 보고서는 Cadence Trace 시간 기준 보정 작업의 설계, 구현, 테스트 결과를 문서화합니다.*
