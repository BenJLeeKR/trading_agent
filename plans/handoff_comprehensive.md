# Handoff — 전체 작업 인수인계

> **작성**: 2026-05-13 17:42 KST (UTC+09:00)
> **이전 Task 완료 항목**: 스냅샷 리셋 + DB 기반 Submit Budget Safeguard

---

## 1. 달성한 목표

### 1.1 Broker Snapshot 데이터 초기화

**문제**: Admin UI에서 `005930 10주 @₩267,000` 허위 포지션이 표시되고 있었음. 이 데이터는 KIS API가 아닌 이전 테스트/sync에서 쌓인 스냅샷.

**해결**: Python asyncpg 스크립트로 3개 snapshot 테이블 데이터 완전 삭제.

| 테이블 | 삭제 건수 |
|--------|:---------:|
| `position_snapshots` | 22 |
| `cash_balance_snapshots` | 20 |
| `snapshot_sync_runs` | 52 |
| **합계** | **94** |

**동작 방식**: `BEGIN` → `DELETE` 3건 → pre-commit 검증 → `COMMIT` → 최종 검증

**보존 확인**:
- Reference 6개 테이블: intact
- `external_events` 300건 (OpenDART): intact
- FK 참조 테이블 (`decision_contexts`, `reconciliation_position_links`): 0건이므로 FK 충돌 없음

**Sync 미실행**: 리셋 직후 sync를 실행하지 않음. 2026-05-14 08:00 KST Pre-Market에서 `run_snapshot_sync_loop.py`가 KIS API로부터 reload 예정.

**보고서**: [`plans/pre_ops_snapshot_reset_report.md`](plans/pre_ops_snapshot_reset_report.md)

---

### 1.2 DB 기반 Submit Budget Safeguard

**문제**: [`SchedulerState.submit_count`](scripts/run_near_real_ops_scheduler.py:95)가 인메모리 변수라 프로세스 crash/restart 시 `0`으로 초기화되어 이미 submit한 날에도 다시 submit 시도 가능.

**해결**: `trading.order_requests` 테이블을 조회하여 당일 budget 소비 상태의 order count를 확인하는 안전장치 추가.

**핵심 변경** ([`_run_intraday_due_tasks()`](scripts/run_near_real_ops_scheduler.py:395)):

```python
# Before: 인메모리만 의존
dry_run = state.submit_count >= max_submit_per_day

# After: DB 기반 effective count
db_submit_count = await _get_db_submit_count(state.run_date)
effective_submit_count = max(state.submit_count, db_submit_count)
dry_run = effective_submit_count >= max_submit_per_day
```

**Budget 소비 상태** (5개):

| 상태 | 설명 |
|------|------|
| `submitted` | 브로커에 제출됨 |
| `acknowledged` | 브로커 접수 확인 |
| `partially_filled` | 부분 체결 |
| `filled` | 전량 체결 |
| `reconcile_required` | 정합성 확인 필요 (submit 시도 자체는 소비한 것으로 간주) |

**안전장치**:
- DB 쿼리 실패 → `DEFAULT_MAX_SUBMIT_PER_DAY=1` 반환 → conservative dry-run (submit 차단)
- DSN 해결: `DATABASE_DSN` 우선, 없으면 `DATABASE_HOST/PORT/USER/PASSWORD/NAME` 조합
- KST 시간 경계: `run_date` KST `00:00:00 ~ 23:59:59`

**Crash/Restart Survivability**:

| 시나리오 | `state.submit_count` | `db_submit_count` | `effective` | 결과 |
|---|---|---|---|---|
| 최초 실행 | 0 | 0 | 0 | `--submit` |
| 1회 submit 성공 후 | 1 | 1 | 1 | `--dry-run` |
| **Crash → 재시작** | **0** | **1** | **1** | **`--dry-run` ✅** |
| DB 장애 fallback | 0 | 1 | 1 | `--dry-run` ✅ |

---

## 2. 변경된 파일 전체 목록

| # | 파일 | 변경 유형 | 요약 |
|---|------|-----------|------|
| 1 | [`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py) | **수정** | `_get_db_submit_count()` 추가 + `_BUDGET_CONSUMING_STATUSES` 상수 + 분기 로직 변경 (~60줄) |
| 2 | [`tests/scripts/test_run_near_real_ops_scheduler.py`](tests/scripts/test_run_near_real_ops_scheduler.py) | **수정** | `TestDbSubmitBudget` 클래스 추가 (5개 테스트, 18/18 통과) |
| 3 | [`plans/near_real_internal_scheduler_p0.md`](plans/near_real_internal_scheduler_p0.md) | **수정** | Submit 안전장치 섹션에 DB budget 설명 추가, P0 한계 #2 해결 ✅ |
| 4 | [`plans/near_real_scheduler_runbook_2026-05-14.md`](plans/near_real_scheduler_runbook_2026-05-14.md) | **수정** | 4개 섹션 업데이트 (3.3/5.3/6/8.1) |
| 5 | [`plans/pre_ops_snapshot_reset_report.md`](plans/pre_ops_snapshot_reset_report.md) | **신규** | 스냅샷 리셋 실행 보고서 |
| 6 | [`plans/db_submit_budget_safeguard.md`](plans/db_submit_budget_safeguard.md) | **신규** | DB budget 안전장치 설계 문서 |

---

## 3. 코드 구조 설명

### 3.1 `_get_db_submit_count(run_date)` — [`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py)

```python
async def _get_db_submit_count(run_date: date) -> int:
```

| 단계 | 설명 |
|------|------|
| 1 | `load_dotenv()`로 `.env` 재로드 (멱등) |
| 2 | DSN 해결: `DATABASE_DSN` 또는 개별 필드 조합 |
| 3 | `asyncpg.connect(dsn)`으로 DB 연결 |
| 4 | KST midnight/day-end 계산: `run_date` 기준 KST `00:00:00 ~ 23:59:59` |
| 5 | `SELECT COUNT(*) FROM trading.order_requests WHERE created_at >= $1 AND < $2 AND status = ANY($3)` |
| 6 | 정상: count 반환 / 실패: `DEFAULT_MAX_SUBMIT_PER_DAY=1` 반환 |

### 3.2 `_BUDGET_CONSUMING_STATUSES` — 모듈 레벨 상수

```python
_BUDGET_CONSUMING_STATUSES: frozenset[str] = frozenset({
    "submitted", "acknowledged", "partially_filled",
    "filled", "reconcile_required",
})
```

### 3.3 `_run_intraday_due_tasks()` 변경점

```
Before (line 366): dry_run = state.submit_count >= max_submit_per_day
After  (line 395): 
    db_submit_count = await _get_db_submit_count(state.run_date)
    effective_submit_count = max(state.submit_count, db_submit_count)
    dry_run = effective_submit_count >= max_submit_per_day
```

---

## 4. DB 최종 상태 (2026-05-13 17:40 KST)

| 구분 | 테이블 | 건수 | 비고 |
|------|--------|:----:|------|
| Operational | `position_snapshots` | 0 | 리셋 완료 |
| Operational | `cash_balance_snapshots` | 0 | 리셋 완료 |
| Operational | `snapshot_sync_runs` | 0 | 리셋 완료 |
| Operational | `order_requests` | 0 | 정상 |
| Operational | `broker_orders` | 0 | 정상 |
| Operational | 기타 7개 테이블 | 0 | 정상 |
| Reference | 6개 테이블 | intact | 보존 |
| External | `external_events` | 300 | OpenDART 보존 |

---

## 5. 실행 검증 결과

### Smoke 검증 (`--once --skip-pre-market`)

```
2026-05-13 17:39:02 [INFO] near-real-scheduler: db_submit_count=0 run_date=2026-05-13
                                                statuses=['acknowledged', 'filled',
                                                'partially_filled', 'reconcile_required', 'submitted']
2026-05-13 17:39:10 [INFO] near-real-scheduler:   submit_count         : 0
2026-05-13 17:39:10 [INFO] near-real-scheduler:   failed_tasks         : 0
```

### 단위 테스트 (18/18 통과)

```
tests/scripts/test_run_near_real_ops_scheduler.py .............. 18 passed
```

---

## 6. 다음 작업자가 알아야 할 사항

### 6.1 Pre-Market 2026-05-14 준비 완료

스냅샷 데이터가 초기화된 상태이므로, 2026-05-14 08:00 KST Pre-Market에서 `run_snapshot_sync_loop.py`가 KIS API로부터 실제 포지션/현금을 reload합니다. **별도 조치 불필요**.

운영 절차: [`plans/near_real_scheduler_runbook_2026-05-14.md`](plans/near_real_scheduler_runbook_2026-05-14.md)

### 6.2 P0 한계 (미해결)

| # | 한계 | 영향 |
|---|------|------|
| 1 | **중복 실행 방지 장치 없음** | 동일 `run_date`에 2개 프로세스 실행 시 최대 2회 submit 가능 |
| 3 | **pre_market_done/end_of_day_done 인메모리** | 프로세스 재시작 시 phase 재실행 (멱등하나 비효율) |
| 4 | **`_is_submit_consuming_result()` stdout 파싱 의존** | JSON 출력 형식 변경 시 오탐 가능 |
| 5 | **`run_date` 검증 없음** | 과거 날짜로 실행 가능 |
| 6 | **`--skip-pre-market` + `--once` 첫 tick 중복** | intraday tasks가 `next_run_at=now`로 설정되어 Pre-Market 경계에서 snapshot/event 중복 실행 |

### 6.3 해결된 P0 한계

| # | 한계 | 해결 방법 |
|---|------|-----------|
| 2 | ~~submit_count 인메모리~~ | `_get_db_submit_count()`가 `trading.order_requests` 조회 → crash/restart survivable ✅ |

### 6.4 비상 대응 변경사항

**Before**: crash 후 재시작 시 `--max-submit-per-day 0` 필요
**After**: crash 후에도 일반 실행(`--max-submit-per-day` 미지정)으로 복구 가능 (DB가 budget 보존)

---

## 7. 참고 문서

| 문서 | 설명 |
|------|------|
| [`plans/pre_ops_snapshot_reset_report.md`](plans/pre_ops_snapshot_reset_report.md) | 스냅샷 리셋 실행 보고서 |
| [`plans/db_submit_budget_safeguard.md`](plans/db_submit_budget_safeguard.md) | DB budget 안전장치 설계 문서 |
| [`plans/near_real_internal_scheduler_p0.md`](plans/near_real_internal_scheduler_p0.md) | 스케줄러 P0 설계 (DB budget 업데이트 완료) |
| [`plans/near_real_scheduler_runbook_2026-05-14.md`](plans/near_real_scheduler_runbook_2026-05-14.md) | 2026-05-14 운영 Runbook (4개 섹션 업데이트 완료) |
| [`plans/paper_one_month_ops_checklist.md`](plans/paper_one_month_ops_checklist.md) | 1개월 운영 체크리스트 |
| [`plans/paper_daily_ops_report_2026-05-13.md`](plans/paper_daily_ops_report_2026-05-13.md) | 2026-05-13 일일 운영 보고서 |
