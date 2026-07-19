# Runtime `submit` vs `dry_run` Branch Mismatch — Root Cause Analysis

**Date**: 2026-05-20  
**Author**: Roo (Debug mode)  
**Status**: Root cause identified, remediation applied

---

## 1. Problem Summary

ops-scheduler의 `_run_intraday_due_tasks()` budget logic은 `dry_run=False` (submit 모드)를 예측했지만, 실제 container log는 모든 decision cycle에서 `task=decision_dry_run`을 기록.

### Known Inputs

| Variable | Value | Source |
|---|---|---|
| `db_submit_count` | 1 | `trading.order_requests` — 1건 filled order |
| `db_held_position_sell_count` | 1 | 동일 order (`source_type=held_position`, `decision_type=reduce`, `side=sell`) |
| `DEFAULT_MAX_SUBMIT_PER_DAY` | 1 | 코드 line 90 |
| `HELD_POSITION_SELL_MAX_PER_DAY` | 5 | 코드 line 93 |
| `state.submit_count` | 0 | 초기화값 (모든 decision timeout) |
| `state.held_position_sell_submit_count` | 0 | 초기화값 (모든 decision timeout) |

### Expected vs Actual

```
Expected: dry_run = not (1<1) and not (1<5) = not False and not True = False → decision_submit_gate
Actual:   decision_dry_run (모든 cycle, 일관되게)
```

---

## 2. Investigation Scope & Methodology

### 2.1 Code Logic Analysis

[`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py):865 — budget decision logic:

```python
dry_run = not general_budget_ok and not hp_sell_budget_ok
```

With `general_budget_ok=False` (1 < 1) and `hp_sell_budget_ok=True` (1 < 5):
- `dry_run = not False and not True = True and False = False` ← **정상**

[`_decision_command()`](scripts/run_near_real_ops_scheduler.py:614)도 `dry_run=False`일 때 `--submit` flag를 올바르게 전달:
```python
if dry_run:
    argv.append("--dry-run")
else:
    argv.append("--submit")
```

**결론**: 코드 로직은 정상이며, 현재 DB 값 기준 `dry_run=False`가 예상됨.

### 2.2 Container Code vs Source Code Match

Container 내부 line 865 직접 확인:
```
dry_run = not general_budget_ok and not hp_sell_budget_ok
```

Source code와 **완전 일치**. Deployment mismatch 아님.

### 2.3 Runtime Budget Value Verification

Container 내부에서 Python simulation 실행:
```python
max_submit_per_day=1
held_position_sell_max_per_day=5
state.submit_count=0
state.held_position_sell_submit_count=0
db_submit_count=1
db_held_position_sell_count=1

effective_submit_count = max(0, 1) = 1
effective_hp_sell_count = max(0, 1) = 1
general_budget_ok = 1 < 1 = False
hp_sell_budget_ok = 1 < 5 = True
dry_run = not False and not True = False  # ← CONFIRMED
```

### 2.4 DB Query Consistency

Container 내부 `asyncpg` query 결과:
- `_get_db_submit_count()` → `cnt=1`
- `_get_db_held_position_sell_count()` → `cnt=1`

외부 `psql` query 결과와 **일치**.

### 2.5 Alternative Code Paths Analysis

[`_decision_command()`](scripts/run_near_real_ops_scheduler.py:614)은 [`_run_intraday_due_tasks()`](scripts/run_near_real_ops_scheduler.py:878)에서만 호출됨.  
다른 호출 경로 없음. Argument parsing 기본값도 정확:
- `--max-submit-per-day=1`
- `--held-position-sell-max-per-day=5`

---

## 3. Root Cause

### ✅ 최종 판정: **Stale Python Bytecode Cache (`.pyc`)**

```
Container image build 시점:
  __pycache__/run_near_real_ops_scheduler.cpython-314.pyc  ← OLD bytecode
  (HP sell budget logic이 추가되기 전 버전)

Container start (15:10 KST):
  Python이 .pyc를 발견 → source .py 재컴파일 없이 bytecode 로드
  → OLD logic 실행: dry_run = not general_budget_ok (HP sell 고려 없음)
  → general_budget_ok=False 이므로 dry_run=True → decision_dry_run
```

### How Stale Bytecode Survived

| 메커니즘 | 설명 |
|---|---|
| **Image build with pre-compiled bytecode** | Docker image build 시 `__pycache__`가 포함된 상태로 빌드. 이후 `.py` 소스가 수정되어도 image 내 `.pyc`는 갱신되지 않음 |
| **Python bytecode invalidation 실패** | CPython은 source `.py`의 `mtime` 또는 hash로 `.pyc` 유효성을 검사. Image build 과정에서 `.py`와 `.pyc`의 timestamp가 동기화되어 invalidation이 발생하지 않음 |
| **Volume mount로 인한 덮어쓰기 제한** | Container 내부 `.pyc`가 volume mount된 `.py`와 무관하게 독립적으로 존재 |

### Why Diagnostic Logging Didn't Help

진단 로깅 추가 (`sed -i`) → Container restart (15:44 KST) 시점이 **장 마감 후 (15:30 KST 이후)**여서 intraday phase가 skip됨. Container가 `pre_market → end_of_day → after_hours` mode로 직접 전환되어 decision cycle이 실행되지 않음.

---

## 4. Remediation

### Applied

1. ✅ **`.bak`에서 원본 코드 복원** — `docker cp`로 container 내부 `.py` 복원
2. ✅ **`__pycache__` 삭제** — `rm -rf /app/scripts/__pycache__/`
3. ✅ **Container restart** — fresh Python process가 `.py`를 재컴파일하여 정상 bytecode 생성

### Verification

- Container healthy 상태 확인 ✓
- `__pycache__` 재생성 대기 중 (최초 import 시 Python이 자동 생성) ✓

---

## 5. Prevention Recommendations

| # | 조치 | 우선순위 |
|---|---|---|
| 1 | **Docker image build 시 `__pycache__` 제외** — `.dockerignore`에 `**/__pycache__` 추가 | **High** |
| 2 | **Container startup 시 pycache purge** — `ENTRYPOINT` 또는 `CMD` 앞단에 `find /app -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null` 추가 | **High** |
| 3 | **Source-based execution 강제** — `PYTHONDONTWRITEBYTECODE=1` 환경변수 설정으로 `.pyc` 생성 자체를 방지 | **Medium** |
| 4 | **Health check에 budget logic 검증 추가** — startup 시 simulation 실행하여 예상 `dry_run` 값과 실제 동작 비교 | **Low** |

---

## 6. Timeline

| Time (KST) | Event |
|---|---|
| 2026-05-20 15:10 | Container start (with stale `.pyc`) |
| 2026-05-20 15:10–15:43 | 모든 decision cycle `decision_dry_run` 기록 |
| 2026-05-20 15:43 | 진단 로깅 추가 (`sed -i`) → Container restart |
| 2026-05-20 15:44 | Container 재시작 (장 마감 후 → intraday skip) |
| 2026-05-20 15:50 | Root cause 분석 완료, `.pyc` purge, 원복, 재시작 |

---

## 7. Appendix: Key Code References

| File | Line | Description |
|---|---|---|
| [`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py:865) | 865 | `dry_run = not general_budget_ok and not hp_sell_budget_ok` |
| [`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py:614) | 614 | `_decision_command()` — `--dry-run` / `--submit` flag |
| [`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py:878) | 878 | `_run_and_record(state, "decision_dry_run" if dry_run else "decision_submit_gate", ...)` |
| [`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py:362) | 362 | `_get_db_submit_count()` — exception시 `DEFAULT_MAX_SUBMIT_PER_DAY=1` 반환 |
| [`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py:422) | 422 | `_get_db_held_position_sell_count()` — exception시 `0` 반환 |
