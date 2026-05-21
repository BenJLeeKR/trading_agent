# Post-Submit Sync Aborted Transaction Root Cause & Boundary Fix

**Date**: 2026-05-19  
**Author**: Roo (Code Mode)  
**Status**: Complete  

---

## 1. Executive Summary

`PostSubmitSyncRunner.run_sync_cycle()`은 단일 PostgreSQL 트랜잭션 내에서 모든 active order를 순차적으로 sync한다.  
한 order의 sync 과정에서 DB write가 실패하면 PostgreSQL 트랜잭션이 **aborted** 상태가 되고,  
이후 모든 SQL 문이 `InFailedSQLTransactionError`로 실패한다.

**문제의 연쇄**:

1. **최초 SQL 실패**: `sync_order_post_submit()` 내부의 DB write (예: `broker_orders.update()`, `fill_events.add()`, `_update_last_synced_at()`)가 실패
2. **예외 은폐**: `except Exception` 블록이 DB 에러를 catch하고 로깅만 수행 → 트랜잭션은 aborted 상태로 유지
3. **2차 증상**: 다음 order의 `broker_orders.list_by_order_request()`가 `InFailedSQLTransactionError`로 실패
4. **전체 실패**: 모든 후속 order가 실패하고, 최종 `tx.commit()`도 실패

**핵심 발견**: 겉으로 보이는 `InFailedSQLTransactionError` at line 838은 **원인이 아니라 증상**이다.  
진짜 원인은 이전 order의 DB write 실패와 이를 은폐하는 `except Exception` 패턴이다.

---

## 2. Root Cause Analysis

### 2.1 트랜잭션 구조

```
_run_one_cycle()
  └── async with transaction() as tx:          ← 단일 트랜잭션
        └── runner.run_sync_cycle()
              ├── Step 2: for each order:
              │     └── sync_order_post_submit()
              │           ├── broker_orders.update()       ← DB write
              │           ├── _try_transition()            ← DB write (order_manager.transition_to)
              │           ├── _sync_fills()
              │           │     └── fill_events.add()      ← DB write
              │           └── _update_last_synced_at()
              │                 └── broker_orders.update()  ← DB write ← **여기서 예외 은폐**
              └── Step 3: _sync_reconcile_required_orders()
                    └── transition_to_authoritative()
                          ├── broker_orders.update()       ← DB write
                          └── _try_transition()            ← DB write
```

### 2.2 최초 SQL 실패 지점

`sync_order_post_submit()` 내부에서 DB write가 실패할 수 있는 지점:

| 위치 | 함수 | DB write | 예외 처리 |
|------|------|----------|-----------|
| Line 218 | `sync_order_post_submit` | `broker_orders.update()` | `run_sync_cycle`의 `except Exception` (line 852) |
| Line 478 | `_sync_fills` | `fill_events.add()` | `run_sync_cycle`의 `except Exception` (line 852) |
| Line 496 | `_update_last_synced_at` | `broker_orders.update()` | **자체 `except Exception` (line 501) — 가장 위험** |
| Line 642 | `transition_to_authoritative` | `broker_orders.update()` | `_sync_reconcile_required_orders`의 `except Exception` (line 572) |

### 2.3 예외 은폐 체인

```
DB write 실패 (예: constraint violation)
  → _update_last_synced_at()의 except Exception이 catch (line 501)
    → 로그만 남기고 조용히 return
      → 트랜잭션은 aborted 상태
        → 다음 order의 broker_orders.list_by_order_request() (line 838)
          → InFailedSQLTransactionError
            → run_sync_cycle()의 except Exception이 catch (line 852)
              → errors 목록에 추가하고 continue
                → 모든 후속 order도 동일한 에러
```

### 2.4 문제가 되는 `except Exception` 블록

| 파일 | 라인 | 문제 |
|------|------|------|
| `order_sync_service.py` | 501 (`_update_last_synced_at`) | **DB 에러를 catch하고 조용히 return → 트랜잭션 broken 상태를 완전히 은폐** |
| `order_sync_service.py` | 852 (`run_sync_cycle` Step 2) | 모든 예외를 catch하고 continue → broken transaction 위험 인지 불가 |
| `order_sync_service.py` | 882 (`run_sync_cycle` Step 3) | 모든 예외를 catch → broken transaction 위험 인지 불가 |
| `order_sync_service.py` | 572 (`_sync_reconcile_required_orders`) | 모든 예외를 catch → broken transaction 위험 인지 불가 |
| `order_sync_service.py` | 632 (`transition_to_authoritative`) | `resolve_unknown_state` 예외만 catch → 상대적으로 안전 |

---

## 3. Fix Design

### 3.1 설계 원칙

1. **Per-order isolation**: 한 order의 실패가 다른 order에 영향을 주지 않아야 함
2. **First-failure visibility**: 최초 SQL 실패 지점이 로그에 명확히 표시되어야 함
3. **No silent broken transaction**: DB write 실패를 catch하더라도 broken transaction 상태를 은폐하지 않아야 함
4. **Minimal change**: 기존 트랜잭션 구조를 유지하면서 savepoint만 추가

### 3.2 Savepoint 기반 per-order isolation

```python
# Before: 모든 order가 단일 트랜잭션 내에서 실행
for order in orders:
    result = await sync_order_post_submit(...)  # 실패시 전체 트랜잭션 중단

# After: 각 order를 savepoint로 격리
for order in orders:
    async with tx_manager.savepoint(name=f"order_sync_{id}"):
        result = await sync_order_post_submit(...)  # 실패시 savepoint만 rollback
```

### 3.3 변경된 파일

#### [`src/agent_trading/db/transaction.py`](src/agent_trading/db/transaction.py)
- `TransactionManager`에 `savepoint()` context manager 추가
- `SAVEPOINT` / `ROLLBACK TO SAVEPOINT` / `RELEASE SAVEPOINT` SQL 명령어 사용
- 예외 발생 시 savepoint rollback 후 예외 재발생 (caller가 처리)
- Auto-incrementing savepoint name (`sp_1`, `sp_2`, ...)

#### [`src/agent_trading/services/order_sync_service.py`](src/agent_trading/services/order_sync_service.py)
- `PostSubmitSyncRunner.run_sync_cycle()`에 `tx_manager` 파라미터 추가
- `tx_manager`가 제공되면 각 order sync를 savepoint로 감쌈
- `_sync_single_order()` 메서드 분리 (savepoint 내부 로직)
- `_update_last_synced_at()`에서 `asyncpg.PostgresError`는 재발생 (savepoint가 처리)
- `asyncpg.PostgresError`는 `logger.error`로 명확히 로깅

#### [`scripts/run_post_submit_sync_loop.py`](scripts/run_post_submit_sync_loop.py)
- `_run_one_cycle()`에서 `tx_manager=tx`를 `run_sync_cycle()`에 전달

### 3.4 예외 처리 흐름 (After)

```
DB write 실패 (예: constraint violation)
  → _update_last_synced_at()가 asyncpg.PostgresError를 재발생 (line 501 → raise)
    → savepoint context manager가 예외를 catch
      → ROLLBACK TO SAVEPOINT 실행 (해당 order의 DB 변경만 취소)
        → 예외 재발생
          → _sync_single_order()의 except asyncpg.PostgresError가 catch
            → errors 목록에 추가하고 continue
              → 다음 order는 새로운 savepoint에서 정상 실행
```

---

## 4. Test Results

### 4.1 Savepoint 단위 테스트 (`tests/db/test_transaction.py`)

11개 테스트 전부 통과:

| 테스트 | 설명 |
|--------|------|
| `test_savepoint_auto_name` | 이름 미지정시 auto-incrementing name 생성 |
| `test_savepoint_custom_name` | 지정한 이름으로 savepoint 생성 |
| `test_savepoint_release_on_success` | 성공시 RELEASE SAVEPOINT 호출 |
| `test_savepoint_rollback_on_exception` | 예외 발생시 ROLLBACK TO SAVEPOINT 호출 |
| `test_outer_transaction_survives_savepoint_failure` | Savepoint 실패 후 외부 트랜잭션 정상 |
| `test_multiple_savepoints_sequential` | 여러 savepoint 순차적 사용 (실패→성공→실패→성공) |
| `test_savepoint_does_not_commit_outer` | Savepoint 성공이 외부 트랜잭션을 커밋하지 않음 |
| `test_savepoint_rollback_undoes_writes` | Savepoint rollback이 내부 write를 취소 |
| `test_savepoint_no_connection_error` | Connection 없는 상태에서 RuntimeError |
| `test_savepoint_release_failure_swallowed` | RELEASE 실패는 무시 |
| `test_savepoint_rollback_then_continue` | Rollback 후에도 정상 SQL 실행 가능 |

### 4.2 PostSubmitSyncRunner 통합 테스트 (`tests/services/test_order_sync_service.py`)

6개 테스트 전부 통과 (기존 36개도 모두 통과):

| 테스트 | 설명 |
|--------|------|
| `test_single_order_sync_success` | 단일 order sync 성공 |
| `test_multiple_orders_all_succeed` | 다수 order 모두 성공 |
| `test_one_order_fails_others_succeed` | **한 order 실패시 다른 order 정상 동작 (핵심)** |
| `test_all_orders_fail` | 모든 order 실패시에도 cycle 정상 종료 |
| `test_no_active_orders` | Active order 없으면 빈 결과 |
| `test_skip_orders_without_broker_orders` | BrokerOrder 없는 OrderRequest skip |

---

## 5. Operational Verification Plan

### 5.1 Docker 재빌드

```bash
docker compose build ops-scheduler
docker compose up -d ops-scheduler
```

### 5.2 사전 검증

```bash
# 1. reconcile_required baseline
docker exec agent_trading-db-1 psql -U postgres -d agent_trading \
  -c "SELECT COUNT(*) FROM order_requests WHERE status = 'reconcile_required';"
docker exec agent_trading-db-1 psql -U postgres -d agent_trading \
  -c "SELECT COUNT(*) FROM broker_orders WHERE reconcile_required = true;"

# 2. Health check
curl -s http://localhost:8000/health | python3 -m json.tool
```

### 5.3 Sync cycle 실행

```bash
docker exec agent_trading-ops-scheduler-1 \
  python3 scripts/run_post_submit_sync_loop.py --once
```

### 5.4 사후 검증

```bash
# 3. reconcile_required count 감소 확인
docker exec agent_trading-db-1 psql -U postgres -d agent_trading \
  -c "SELECT COUNT(*) FROM order_requests WHERE status = 'reconcile_required';"
docker exec agent_trading-db-1 psql -U postgres -d agent_trading \
  -c "SELECT COUNT(*) FROM broker_orders WHERE reconcile_required = true;"

# 4. 로그에서 InFailedSQLTransactionError 확인
docker logs agent_trading-ops-scheduler-1 2>&1 | grep -i "InFailedSQLTransactionError" || echo "No aborted transaction errors found"

# 5. Inspection API 호출
curl -s "http://localhost:8000/api/v1/inspection/reconciliation?limit=10" | python3 -m json.tool
```

---

## 6. Risk Assessment

| 리스크 | 영향 | 완화 |
|--------|------|------|
| Savepoint 이름 충돌 | Savepoint 생성 실패 | UUID 기반 고유 이름 사용 (`order_sync_{id.hex[:8]}`) |
| RELEASE SAVEPOINT 실패 | Savepoint 누적 | `finally` 블록에서 try/except로 무시 |
| ROLLBACK TO SAVEPOINT 실패 | 트랜잭션 복구 불가 | 매우 드문 케이스; 전체 트랜잭션 rollback 필요 |
| 기존 `except Exception` 패턴 | 여전히 broken transaction 위험 | `_update_last_synced_at`의 `asyncpg.PostgresError`는 재발생하도록 수정 |
| Memory in-memory repo 테스트 | Savepoint isolation 검증 불가 | Mock 기반 단위 테스트로 대체 |

---

## 7. Future Improvements

1. **`_sync_fills()`의 `fill_events.add()` 실패 처리**: 현재 `except Exception`이 없어 예외가 상위로 전파되지만, savepoint가 보호함
2. **`_sync_reconcile_required_orders()`에도 savepoint 적용**: 현재 Step 3는 savepoint 외부에서 실행됨
3. **`run_post_submit_sync_loop.py`의 `except Exception` (line 268)**: cycle 전체 실패시에도 로깅 개선 가능
4. **Savepoint name 충돌 방지**: 현재 UUID hex prefix 사용으로 충분히 고유하지만, 완전한 UUID 사용도 고려 가능
