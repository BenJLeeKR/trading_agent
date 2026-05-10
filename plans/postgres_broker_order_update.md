# Postgres BrokerOrderRepository.update() 구현

## 1. 현재 상태

### InMemoryBrokerOrderRepository.update() (memory.py:411-429)
- `broker_order_id`로 lookup, 없으면 `ValueError` 발생
- 갱신 필드: `broker_status`, `last_synced_at`, `updated_at` (keyword-only, 각각 optional)
- `dataclasses.replace()`로 immutable entity 교체

### BrokerOrderRepository Protocol (contracts.py:308-333)
- 동일 signature: `update(broker_order_id, *, broker_status, last_synced_at, updated_at)`

### PostgresBrokerOrderRepository (postgres/broker_orders.py) — **MISSING**
- `add()`, `get_by_native_order_id()`, `list_by_order_request()` 만 구현
- **`get()` 없음** → `OrderSyncService`가 `repos.broker_orders.get()` 호출 시 실패
- **`update()` 없음** → `OrderSyncService`가 `repos.broker_orders.update()` 호출 시 `AttributeError`

### OrderSyncService 호출 지점
1. `sync_order_post_submit()` line 214: `broker_status` + `updated_at` 갱신
2. `_update_last_synced_at()` line 440: `last_synced_at` + `updated_at` 갱신
3. `sync_order_post_submit()` line 121: `repos.broker_orders.get()`로 entity 조회

### DB Schema (broker_orders table)
```sql
broker_order_id UUID PRIMARY KEY
order_request_id UUID NOT NULL
broker_name VARCHAR(64) NOT NULL
broker_native_order_id VARCHAR(128)
broker_status VARCHAR(64) NOT NULL
request_payload_uri TEXT
response_payload_uri TEXT
last_synced_at TIMESTAMPTZ
created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

## 2. 세부 작업

### Step 1: PostgresBrokerOrderRepository.get() 구현
- `SELECT * FROM trading.broker_orders WHERE broker_order_id = $1`
- `row_to_entity()`로 변환
- 없으면 `None` 반환

### Step 2: PostgresBrokerOrderRepository.update() 구현
- 동적 SET 절 생성: 제공된 인자만 UPDATE
- 기본: `updated_at = NOW()` (항상 갱신)
- SQL: `UPDATE trading.broker_orders SET (필드 동적) WHERE broker_order_id = $1`
- 없으면 `ValueError` 발생 (InMemory와 일관성)

```python
async def update(
    self,
    broker_order_id: UUID,
    *,
    broker_status: str | None = None,
    last_synced_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> None:
    # Build dynamic SET clause
    sets: list[str] = []
    params: list[object] = []
    param_idx = 1

    if broker_status is not None:
        sets.append(f"broker_status = ${param_idx}")
        params.append(broker_status)
        param_idx += 1
    if last_synced_at is not None:
        sets.append(f"last_synced_at = ${param_idx}")
        params.append(last_synced_at)
        param_idx += 1
    # Always update updated_at
    sets.append(f"updated_at = ${param_idx}")
    params.append(updated_at or datetime.now(timezone.utc))
    param_idx += 1

    params.append(broker_order_id)
    sql = f"""
        UPDATE trading.broker_orders
        SET {', '.join(sets)}
        WHERE broker_order_id = ${param_idx}
    """
    result = await self._tx.connection.execute(sql, *params)
    if result == "UPDATE 0":
        raise ValueError(f"BrokerOrder not found: {broker_order_id}")
```

### Step 3: post-submit sync 경로 점검
- `OrderSyncService`는 `get()` → entity 확인 → `update()` 호출
- Postgres에서도 동일하게 동작 확인 (특히 `last_synced_at` 반영)
- `_update_last_synced_at()`의 `try/except Exception`이 `ValueError`도 캐치하므로 안전

### Step 4: 테스트
`tests/repositories/test_postgres_broker_orders.py`에 5개 테스트 추가:
1. `test_update_status` — status 변경 후 get()으로 확인
2. `test_update_last_synced_at` — last_synced_at 변경 확인
3. `test_update_multiple_fields` — 동시에 여러 필드 갱신
4. `test_update_not_found` — 존재하지 않는 UUID → ValueError
5. `test_get_by_id` — broker_order_id로 조회

### Step 5: BACKLOG.md #16 상태 업데이트
- #16: `Postgres BrokerOrderRepository.update() 구현` → ❌ 미착수 → ✅ 승격됨

## 3. 변경 파일 목록
| 파일 | 변경 |
|------|------|
| `src/agent_trading/repositories/postgres/broker_orders.py` | `get()` + `update()` 구현 |
| `tests/repositories/test_postgres_broker_orders.py` | 5개 신규 테스트 추가 |
| `plans/BACKLOG.md` | #16 상태 업데이트 |

## 4. No-Go Items
- Admin UI 변경 금지
- broker submit semantics 변경 금지
- hard guardrail / reconciliation 경계 변경 금지
- destructive schema 변경 금지
- `broker_native_order_id` / `request_payload_uri` / `response_payload_uri` update는 현재 protocol 범위 밖이므로 제외
