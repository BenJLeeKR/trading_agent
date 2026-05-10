# FillEvent.broker_fill_id 기반 Dedup 강화

> **보정사항 반영** (2026-05-10):
> 1. `broker_fill_id` uniqueness: DB `uq_fill_events_native (broker_order_id, broker_fill_id)` 조합 UNIQUE 준수
> 2. `broker_fill_id=""` → 반드시 `None`으로 정규화
> 3. Composite fallback key: `(broker_order_id, fill_timestamp, fill_price, fill_quantity)` — `broker_order_id` 포함
> 4. broker_fill_id 기반 dedup은 timestamp/price/qty와 무관하게 broker_fill_id만으로 중복 판정

## 1. Source Inventory 결과

### 현재 Fill 데이터 흐름 (3개 경로)

| 경로 | 소스 | 파일 위치 | Fill ID 가용성 |
|------|------|-----------|---------------|
| REST polling | `inquire_daily_ccld` 응답 | [`rest_client.py:889`](../src/agent_trading/brokers/koreainvestment/rest_client.py:889) | KIS `CCLD_NUM`(체결번호) 필드 존재하나 현재 미추출 |
| WS notification | `H0STCNI0` 메시지 | [`event_loop.py:238`](../src/agent_trading/services/event_loop.py:238) | WS data에 fill ID 없음 (`broker_order_id`, `stock_code`, `filled_qty`, `filled_price`, `filled_time`, `side`, `order_qty`) |
| Domain model | `FillEvent` dataclass | [`models.py:216`](../src/agent_trading/domain/models.py:216) | `broker_fill_id` 필드 **없음** |

### `broker_fill_id` Uniqueness 가정

| 항목 | 내용 |
|------|------|
| DB 제약 | `uq_fill_events_native (broker_order_id, broker_fill_id)` — broker_order_id와의 **조합 UNIQUE** |
| 단독 UNIQUE? | ❌ `broker_fill_id` 단독 UNIQUE가 아님. 동일 broker_fill_id가 다른 broker_order에서는 존재 가능 |
| dedup lookup key | `get_by_broker_fill_id(broker_fill_id)` + 호출자가 `broker_order_id` 일치도 확인해야 함 |
| 향후 검토 | KIS CCLD_NUM이 전역 고유라면 단독 UNIQUE로 전환 가능하나, 현재는 조합 UNIQUE 유지 |

### 이미 존재하는 것 (변경 불필요)

| 항목 | 위치 | 상태 |
|------|------|------|
| `fill_events.broker_fill_id VARCHAR(128)` 컬럼 | [`0001_initial_schema.sql:349`](../db/migrations/0001_initial_schema.sql:349) | ✅ 이미 존재, `uq_fill_events_native` UNIQUE 제약 있음 |
| `FillEventEntity.broker_fill_id: str \| None = None` | [`entities.py:284`](../src/agent_trading/domain/entities.py:284) | ✅ 이미 존재 |
| `PostgresFillEventRepository.add()` INSERT | [`fill_events.py:34`](../src/agent_trading/repositories/postgres/fill_events.py:34) | ✅ 이미 `broker_fill_id` 파라미터 전달 |
| `row_to_entity()` generic 변환 | [`row_mapper.py:58`](../src/agent_trading/db/row_mapper.py:58) | ✅ 자동 처리 |

### `broker_fill_id=""` 정규화 정책

`order_sync_service.py:423`에서 현재 `broker_fill_id=""` (빈 문자열)을 주입하고 있다.
이는 DB UNIQUE 제약 위반 가능성 + `bool(broker_fill_id)` falsy 문제를 유발한다.

**정규화 규칙**: broker_fill_id는 `str | None`이며, 빈 문자열은 `None`으로 저장한다.
- `FillEvent.broker_fill_id`가 `None`이거나 `""` → `FillEventEntity.broker_fill_id=None`
- `FillEvent.broker_fill_id`가 실제 값 → 그대로 전달
- InMemory/Postgres 모두 None을 정상 처리

### Composite Fallback Dedup Key

현재 dedup key: `(fill_timestamp, fill_price, fill_quantity)` — broker_order_id를 포함하지 않음

**위험**: 동일 timestamp/price/qty를 가진 다른 주문의 fill이 잘못 dedup될 가능성.

**보정**: fallback composite key에 `broker_order_id`를 포함시킨다.
- Fallback key: `(broker_order_id, fill_timestamp, fill_price, fill_quantity)`
- 이는 FillEventEntity 자체에 `broker_order_id`가 있으므로 안전하게 추가 가능
- `_sync_fills()`는 이미 단일 broker_order 기준으로만 호출되므로 실제 영향은 없지만, 명시적 포함으로 의미적 정확성 확보

### 변경 필요한 것

| 항목 | 현재 상태 | 목표 |
|------|-----------|------|
| [`domain/models.py FillEvent`](../src/agent_trading/domain/models.py:216) | `broker_fill_id` 필드 없음 | `broker_fill_id: str \| None = None` 필드 추가 |
| [`contracts.py FillEventRepository`](../src/agent_trading/repositories/contracts.py:336) | `add()`, `list_by_broker_order()`만 있음 | `get_by_broker_fill_id()` 메서드 추가 |
| [`memory.py InMemoryFillEventRepository`](../src/agent_trading/repositories/memory.py:432) | dict[UUID], broker_fill_id 인덱스 없음 | `get_by_broker_fill_id()` 구현 (broker_fill_id→entity dict) |
| [`postgres/fill_events.py`](../src/agent_trading/repositories/postgres/fill_events.py:54) | `list_by_broker_order()`만 있음 | `get_by_broker_fill_id()` SQL 구현 |
| [`order_sync_service.py _sync_fills()`](../src/agent_trading/services/order_sync_service.py:401) | `(timestamp, price, quantity)` composite dedup | `broker_fill_id` 우선 dedup + composite fallback |
| [`order_sync_service.py:423`](../src/agent_trading/services/order_sync_service.py:423) | `broker_fill_id=""` (empty string) | `broker_fill_id=fill.broker_fill_id` (broker 실제 값 사용) |
| [`rest_client.py get_fills()`](../src/agent_trading/brokers/koreainvestment/rest_client.py:933) | KIS `CCLD_NUM` 미추출 | FillEvent.broker_fill_id에 `CCLD_NUM` 매핑 |
| [`event_loop.py _handle_fill_notification()`](../src/agent_trading/services/event_loop.py:319) | WS data에 fill ID 없어 None 유지 | 변경 불필요 (WS는 None 유지) |
| [`tests/services/test_order_sync_service.py`](../tests/services/test_order_sync_service.py:350) | `TestSyncFillDedup` 1개 테스트 | broker_fill_id 기반 dedup 테스트 추가 |

### Dedup 로직 변경 상세

현재:
```python
# order_sync_service.py:401-406
existing_keys: set[tuple[datetime, Decimal, Decimal]] = {
    (f.fill_timestamp, f.fill_price, f.fill_quantity)
    for f in existing
}
for fill in fill_events:
    key = (fill.fill_timestamp, fill.fill_price, fill.fill_quantity)
    if key in existing_keys:
        skipped += 1
        continue
```

### Dedup 우선순위 규칙 (최종)

```
1st priority: broker_fill_id가 있는 fill → get_by_broker_fill_id()로 정확히 조회하여 중복 판정
   조건: broker_fill_id가 None이 아니고, 빈 문자열이 아님
   판정: 동일 broker_fill_id + 동일 broker_order_id → 중복 (timestamp/price/qty 무관)
   
2nd priority: broker_fill_id가 없는 fill → composite key (broker_order_id, timestamp, price, quantity) fallback
   조건: broker_fill_id가 None이거나 빈 문자열
   판정: 4개 필드 모두 일치 → 중복
```

목표:
```python
# 1. broker_fill_id가 있는 fill은 DB UNIQUE 제약 + PK lookup으로 1차 방어
# 2. broker_fill_id가 없는 fill은 기존 composite key fallback
existing_by_fill_id: dict[str, FillEventEntity] = {}
existing_composite: set[tuple] = set()
for f in existing:
    if f.broker_fill_id:
        existing_by_fill_id[f.broker_fill_id] = f
    else:
        existing_composite.add((f.fill_timestamp, f.fill_price, f.fill_quantity))

for fill in fill_events:
    if fill.broker_fill_id and fill.broker_fill_id in existing_by_fill_id:
        skipped += 1
        continue
    if not fill.broker_fill_id:
        key = (fill.fill_timestamp, fill.fill_price, fill.fill_quantity)
        if key in existing_composite:
            skipped += 1
            continue
```

## 2. 변경 파일 목록

| # | 파일 | 변경 유형 | 설명 |
|---|------|-----------|------|
| 1 | [`src/agent_trading/domain/models.py`](../src/agent_trading/domain/models.py:216) | 수정 | `FillEvent`에 `broker_fill_id: str \| None = None` 필드 추가 |
| 2 | [`src/agent_trading/repositories/contracts.py`](../src/agent_trading/repositories/contracts.py:336) | 수정 | `FillEventRepository`에 `get_by_broker_fill_id()` 추가 |
| 3 | [`src/agent_trading/repositories/memory.py`](../src/agent_trading/repositories/memory.py:432) | 수정 | `InMemoryFillEventRepository`에 `_by_fill_id` dict + `get_by_broker_fill_id()` 구현 |
| 4 | [`src/agent_trading/repositories/postgres/fill_events.py`](../src/agent_trading/repositories/postgres/fill_events.py:54) | 수정 | `get_by_broker_fill_id()` SQL: `SELECT * FROM trading.fill_events WHERE broker_fill_id = $1` |
| 5 | [`src/agent_trading/services/order_sync_service.py`](../src/agent_trading/services/order_sync_service.py:396) | 수정 | dedup 로직 broker_fill_id 우선 + composite fallback(4-field). `broker_fill_id=""`→None 정규화. `source_channel` 동적 할당 |
| 6 | [`src/agent_trading/brokers/koreainvestment/rest_client.py`](../src/agent_trading/brokers/koreainvestment/rest_client.py:933) | 수정 | `FillEvent` 생성 시 `broker_fill_id=item.get("CCLD_NUM")` 매핑 |
| 7 | [`tests/services/test_order_sync_service.py`](../tests/services/test_order_sync_service.py:350) | 수정 | `TestSyncFillDedup`에 broker_fill_id 기반 dedup 테스트 추가 |
| 8 | [`plans/BACKLOG.md`](../plans/BACKLOG.md:38) | 수정 | #18 상태 `❌ 미착수` → `✅ 승격됨` |

## 3. No-Go Items

- **Migration 추가 불필요**: `broker_fill_id` 컬럼은 이미 `0001_initial_schema.sql`에 존재
- **Entity 필드 추가 불필요**: `FillEventEntity.broker_fill_id`는 이미 존재
- **WS 핸들러 변경 불필요**: KIS WS H0STCNI0 메시지에 fill ID가 없으므로 None 유지
- **Pipeline Phase 5.5 경로 변경 불필요**: `_sync_fills()`만 보강하면 자동 적용
- **Postgres test 검증 불필요**: Postgres 환경 미구축으로 SKIP 처리됨 (기존 문제)
- **row_mapper.py 변경 불필요**: generic `row_to_entity()`가 자동 매핑

## 4. 실행 단계

### Step 1: `domain/models.py FillEvent` — `broker_fill_id` 필드 추가
```python
# order_sync_service.py _sync_fills() — 목표 dedup 로직
@dataclass(slots=True, frozen=True)
class FillEvent:
    broker_name: BrokerName
    broker_order_id: str
    symbol: str
    side: OrderSide
    fill_quantity: Decimal
    fill_price: Decimal
    fill_timestamp: datetime
    broker_fill_id: str | None = None  # ← 신규
    fee: Decimal | None = None
    tax: Decimal | None = None
```

### Step 2: `contracts.py FillEventRepository` — `get_by_broker_fill_id()` 추가
Protocol에 broker_fill_id 기반 단건 조회 메서드 추가. UNIQUE 제약이 있으므로 `Sequence`가 아닌 단일 `FillEventEntity | None` 반환.

```python
class FillEventRepository(Protocol):
    async def add(self, fill_event: FillEventEntity) -> FillEventEntity: ...
    async def list_by_broker_order(self, broker_order_id: UUID) -> Sequence[FillEventEntity]: ...
    async def get_by_broker_fill_id(self, broker_fill_id: str) -> FillEventEntity | None: ...
```

### Step 3: `memory.py InMemoryFillEventRepository` — `get_by_broker_fill_id()` 구현
broker_fill_id → entity 맵을 유지하며, broker_fill_id가 None인 항목은 인덱싱하지 않음.

```python
class InMemoryFillEventRepository:
    def __init__(self) -> None:
        self._items: dict[UUID, FillEventEntity] = {}
        self._by_fill_id: dict[str, FillEventEntity] = {}

    async def add(self, fill_event: FillEventEntity) -> FillEventEntity:
        self._items[fill_event.fill_event_id] = fill_event
        if fill_event.broker_fill_id:
            self._by_fill_id[fill_event.broker_fill_id] = fill_event
        return fill_event

    async def get_by_broker_fill_id(self, broker_fill_id: str) -> FillEventEntity | None:
        return self._by_fill_id.get(broker_fill_id)
```

### Step 4: `postgres/fill_events.py PostgresFillEventRepository` — `get_by_broker_fill_id()` 구현
```python
async def get_by_broker_fill_id(self, broker_fill_id: str) -> FillEventEntity | None:
    row = await self._tx.connection.fetchrow(
        "SELECT * FROM trading.fill_events WHERE broker_fill_id = $1",
        broker_fill_id,
    )
    return row_to_entity(row, FillEventEntity) if row else None
```

### Step 5: `order_sync_service.py _sync_fills()` — dedup 로직 개선
5a. existing fills를 broker_fill_id 유무로 분류
5b. broker_fill_id가 있는 fill은 `get_by_broker_fill_id()` + broker_order_id 일치 확인으로 정확히 중복 판정
5c. 없는 fill은 `(broker_order_id, timestamp, price, quantity)` 4-field composite fallback
5d. FillEventEntity 생성 시 `broker_fill_id=fill.broker_fill_id or None` 전달 (빈 문자열→None 정규화)
5e. `source_channel`을 호출 시점에 동적으로 설정 (현재 하드코딩 "polling")

### Step 6: `rest_client.py get_fills()` — KIS CCLD_NUM 매핑
KIS `inquire_daily_ccld` 응답의 `CCLD_NUM`(체결번호) 필드를 `FillEvent.broker_fill_id`로 전달.

```python
fill = FillEvent(
    event_id=uuid4(),
    broker_order_id=item.get("ODNO", ""),
    broker_fill_id=item.get("CCLD_NUM"),  # ← 신규
    symbol=item.get("PDNO", ""),
    ...
)
```

### Step 7: 테스트 추가

`test_order_sync_service.py`의 `TestSyncFillDedup` 클래스에 다음 테스트 시나리오 추가:

| # | 테스트 | 설명 |
|---|--------|------|
| 1 | `test_fill_dedup_by_broker_fill_id` | 동일 `broker_fill_id` fill 2회 sync → skipped=1 |
| 2 | `test_fill_dedup_composite_key_fallback` | `broker_fill_id=None` fill → composite key dedup 작동 |
| 3 | `test_fill_dedup_broker_fill_id_preferred` | 동일 timestamp/price/qty지만 다른 broker_fill_id → 별개 fill으로 처리 |
| 4 | `test_fill_dedup_broker_fill_id_overrides_timestamp` | 동일 broker_fill_id + 다른 timestamp/price/qty → broker_fill_id 우선 dedup |
| 5 | `test_fill_dedup_mixed_broker_fill_id` | 일부 fill은 ID 보유, 일부는 None → 각각 dedup 정상 |
| 6 | `test_inmemory_get_by_broker_fill_id` | InMemory repo `get_by_broker_fill_id()` 동작 검증 |

### Step 8: BACKLOG #18 상태 업데이트
`BACKLOG.md:38` — #18 상태를 `❌ 미착수` → `✅ 승격됨`으로 변경, 승격 기록 추가.

---

## 작업 예상 범위 요약

```
변경 파일: 7개 (models.py, contracts.py, memory.py, fill_events.py, order_sync_service.py, rest_client.py, test_order_sync_service.py)
신규 테스트: 6개 (broker_fill_id dedup 5 + InMemory repo 1)
Migration: 없음 (0001에 이미 존재)
DB 변경: 없음 (컬럼 이미 존재)
기존 semantics 변경: 없음 (broker_fill_id=None이면 기존 composite key 그대로 사용)
```

**핵심 설계 결정**:
1. broker_fill_id는 **optional** 유지. broker_fill_id가 있는 fill → broker_fill_id 기반 dedup 우선. 없는 fill → 4-field composite fallback.
2. DB UNIQUE 제약은 `(broker_order_id, broker_fill_id)` 조합. 단독 UNIQUE가 아니므로 `get_by_broker_fill_id()` 반환값이 반드시 같은 broker_order 소속인지 호출자가 확인.
3. 빈 문자열 `""`은 `None`으로 정규화. `broker_fill_id=""`인 기존 데이터는 향후 migration에서 정리 가능.
4. broker_fill_id가 있으면 timestamp/price/qty와 무관하게 중복 판정. 즉 broker_fill_id는 broker의 fill 식별자로서 절대적 신뢰.
5. 기존 fill 처리 semantics 완전 보존. broker_fill_id=None fill은 기존과 동일하게 composite key로 dedup.
