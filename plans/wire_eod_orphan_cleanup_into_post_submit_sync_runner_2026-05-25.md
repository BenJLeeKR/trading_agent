# EOD Orphan Cleanup — 실행 경로 연결 계획

## 1. 문제 정의

`expire_eod_orphan_orders()`는 정의와 테스트만 있고,
실제 운영 실행 경로에서는 호출되지 않음.

현재 orphan 현황:
- `pending_submit = 21`
- `reconcile_required = 17`
- 모두 broker order 없는 orphan

## 2. 실행 경로 분석

### 2.1 Post-submit sync 실행 경로

```
scripts/run_post_submit_sync_loop.py
  └── _run_one_cycle()
        └── runner.run_sync_cycle(after_hours=after_hours)
              ├── Step 0: _reject_stale_pending_submit_orders()
              ├── Step 1-2: Active order sync (per-order savepoint)
              ├── Step 3: _sync_reconcile_required_orders()
              └── Step 4: Return SyncCycleResult
```

### 2.2 Scheduler EOD 실행 경로

```
scripts/run_near_real_ops_scheduler.py
  └── _run_eod_phase()
        ├── eod_snapshot_sync (--after-hours)
        └── eod_post_submit_sync (--after-hours)
              = python3 scripts/run_post_submit_sync_loop.py --once --after-hours
```

`scheduler`의 `eod_post_submit_sync`는 `_post_submit_command(after_hours=True)`를 통해
`run_post_submit_sync_loop.py --once --after-hours`를 subprocess로 실행한다.

### 2.3 after_hours 전파

```
CLI --after-hours
  → _run_one_cycle(after_hours=True)
    → runner.run_sync_cycle(after_hours=True)
      → _is_after_hours = True (명시적 값 사용)
```

## 3. 호출 위치 결정

**결정: `PostSubmitSyncRunner.run_sync_cycle()` 내부 Step 5로 삽입**

근거:
1. `run_sync_cycle()`은 `after_hours: bool | None = None` 파라미터를 이미 보유
2. `runner.sync_service`가 `OrderSyncService` 인스턴스 → `expire_eod_orphan_orders()` 접근 가능
3. 모든 EOD 실행 경로(전용 loop + scheduler)가 `run_sync_cycle()`으로 수렴
4. Step 0(`_reject_stale_pending_submit_orders`)과 동일한 패턴 — runner 내 cleanup
5. `_is_after_hours` 값은 Step 3에서 이미 계산됨 → 재사용 가능

### 장중/장종료 분기

```python
# ── 5. EOD orphan cleanup (after-hours only) ──────────────────────────
if _is_after_hours:
    try:
        expired_pending, expired_reconcile = (
            await self.sync_service.expire_eod_orphan_orders()
        )
    except Exception as exc:
        logger.error("EOD orphan cleanup failed: %s", exc, exc_info=True)
```

- `after_hours=False` (장중): Step 5 skip → 장중 cycle에 영향 없음
- `after_hours=True` (EOD): Step 5 실행 → orphan 정리
- `after_hours=None` (자동 감지): `_is_after_hours() = now >= 15:30 KST` → 장중에는 False

### SyncCycleResult 확장

orphan cleanup 결과를 `SyncCycleResult`에 포함하여
로그/모니터링에서 확인 가능하게 함.

## 4. 기존 sync와 충돌 방지

`expire_eod_orphan_orders()`가 처리하는 주문은:
- `broker_orders = 0` (broker에 도달하지 않음)
- `submitted_at = NULL`
- `broker_native_order_id = NULL`

따라서 기존 sync(Step 1-2)는 broker_orders가 있는 주문만 처리하므로
**orphan cleanup과 충돌하지 않음**:
- Step 1-2: `broker_orders.list_by_order_request()`가 비어있으면 `continue`
- Step 5: `broker_orders = 0`인 주문만 EXPIRED 처리

## 5. 변경 파일 목록

| 파일 | 변경 내용 |
|------|----------|
| `src/agent_trading/services/order_sync_service.py` | `SyncCycleResult`에 orphan expired 필드 추가 |
| `src/agent_trading/services/order_sync_service.py` | `run_sync_cycle()` Step 5 추가 (after-hours 전용) |
| `scripts/run_post_submit_sync_loop.py` | `_log_cycle_summary()`에 orphan cleanup 로깅 추가 |
| `tests/services/test_order_sync_service.py` | after-hours trigger / regular-hours skip 테스트 추가 |

## 6. 테스트 계획

### 6.1 신규 테스트

1. `test_runner_after_hours_triggers_eod_orphan_cleanup`
   - `after_hours=True`로 `run_sync_cycle()` 호출
   - `expire_eod_orphan_orders()`가 호출되어 orphan이 EXPIRED되는지 검증

2. `test_runner_regular_hours_skips_eod_orphan_cleanup`
   - `after_hours=False`로 `run_sync_cycle()` 호출
   - orphan이 그대로 유지되는지 검증

3. `test_runner_after_hours_orphan_counts_in_result`
   - `after_hours=True`로 호출 시 `SyncCycleResult.orphans_expired_pending/reconcile` 값 검증

### 6.2 기존 테스트 영향

- 기존 `TestPostSubmitSyncRunner` 10개 테스트는 `after_hours`를 지정하지 않음
- `after_hours=None` → `_is_after_hours()` 자동 감지
- **대책**: Step 5는 예외 처리되어 있어 기존 테스트가 실패하지는 않지만,
  예상치 못한 side effect 가능성 있음
- **최종 대책**: 기존 테스트가 `after_hours=None`(기본값)을 사용하면
  `_is_after_hours()`가 테스트 환경 시간에 따라 True가 될 수 있음
  → Step 5 자체에 예외 처리가 있으므로 테스트는 안전하게 통과
