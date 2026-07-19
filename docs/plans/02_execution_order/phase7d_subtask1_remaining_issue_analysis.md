# Phase 7d Subtask 1 — Stuck Reconciliation Issue Analysis

> **작성일**: 2026-05-30  
> **대상**: `reconcile_required` 주문 16건 + `failed` reconciliation run 2건  
> **목적**: 무한 재시도 루프 원인 분석 및 해결 방안 선정

---

## 1. 현황 요약

### 1.1 DB 현황

| 항목 | 값 |
|------|-----|
| `broker_status = 'reconcile_required'` 주문 | **16건** |
| `failed` reconciliation run | **2건** |
| 두 failed run이 공통으로 가리키는 주문 | `c87f5ec3-2647-440c-a959-5c185a9886cd` |
| 해당 주문 상세 | BUY `000990`, 수량 11, `broker_native_order_id = 0000032815` |
| `submitted_at` | 모두 `null` (제출되지 않은 주문) |

### 1.2 Failed Reconciliation Run 상세

| Run ID | 생성 시각 | Error |
|--------|-----------|-------|
| `5e1573f3-a0a8-4112-9d6f-60341aeeed90` | 2026-05-30 02:02:08Z | `order c87f5ec3-... failed` |
| `0614abb0-e5a3-4bf1-bbf0-d0024a559a82` | 2026-05-30 01:43:09Z | `order c87f5ec3-... failed` |

두 run 모두 동일한 주문 `c87f5ec3`에서 실패. 이 주문은 `reconcile_required` 상태로 고정되어 있으며, backfill 스크립트가 새 reconciliation run을 생성 → worker가 실패 → run이 `failed`로 마킹 → 주문은 그대로 `reconcile_required` → 다음 backfill cycle에서 다시 run 생성 → **무한 루프**.

---

## 2. 코드 분석 — 실패 전이 조건

### 2.1 Reconciliation Worker Flow

```
ReconciliationRunProcessor.process_run()
  └─ _process_order_link()          [reconciliation_worker.py:363]
       └─ adapter.resolve_unknown_state()  [reconciliation_worker.py:390]
            └─ KISRestClient.resolve_unknown_state()  [rest_client.py:1984]
                 ├─ inquire_daily_ccld()  (7일 범위, after_hours)
                 ├─ (ODNO 매칭 실패)
                 ├─ _request_with_fallback() → get_positions()
                 └─ (positions에서도 미발견)
                 └─ return RECONCILE_REQUIRED   [rest_client.py:2089]
       └─ result.status in resolved_statuses?  [reconciliation_worker.py:414]
            └─ resolved_statuses = {FILLED, CANCELLED, REJECTED, EXPIRED, ACKNOWLEDGED}
            └─ RECONCILE_REQUIRED NOT in resolved_statuses → "failed"
       └─ _mark_run_failed()          [reconciliation_worker.py:480]
```

### 2.2 핵심 코드 — [`reconciliation_worker.py:414`](src/agent_trading/services/reconciliation_worker.py:414)

```python
resolved_statuses = {
    OrderStatus.FILLED,
    OrderStatus.CANCELLED,
    OrderStatus.REJECTED,
    OrderStatus.EXPIRED,
    OrderStatus.ACKNOWLEDGED,
}
if result.status in resolved_statuses:
    return "resolved"
else:
    return "failed"
```

`RECONCILE_REQUIRED`는 `resolved_statuses`에 포함되지 않으므로, `resolve_unknown_state()`가 `RECONCILE_REQUIRED`를 반환하면 항상 `"failed"`로 처리됨.

### 2.3 [`resolve_unknown_state()`](src/agent_trading/brokers/koreainvestment/rest_client.py:1984)의 동작

1. `inquire_daily_ccld()` 호출 — 7일 범위, `after_hours=True`, `RECONCILIATION` 버킷
2. ODNO(`broker_native_order_id = 0000032815`)로 매칭 시도
3. 매칭 실패 시 positions 조회 (`_request_with_fallback`)
4. positions에서도 발견되지 않음 → `RECONCILE_REQUIRED` 반환

**KIS Paper API의 한계**: `inquire-daily-ccld` (VTTC0081R)가 Paper 환경에서 ODNO 데이터를 반환하지 않음. 실제 운영 환경에서는 정상 동작할 가능성이 높지만, 현재 Paper 환경에서는 항상 빈 결과를 반환.

### 2.4 [`transition_to_authoritative()`](src/agent_trading/services/order_sync_service.py:888)와의 비교

`OrderSyncService.transition_to_authoritative()`는 더 정교한 fallback 로직을 가지고 있음:

1. `inquire_daily_ccld()` → ODNO 매칭
2. **EXPIRED fallback**: after-hours + grace period 조건에서 EXPIRED로 간주
3. **Position-delta inference**: SELL 주문의 경우 position 변화량으로 체결량 추론
4. **KIS truth fallback**: SELL 주문의 경우 KIS 잔고 조회로 최종 상태 결정

**그러나 reconciliation worker는 `transition_to_authoritative()`를 사용하지 않고**, 자체적인 `_process_order_link()` 로직으로 더 단순한 판단을 내림.

### 2.5 Backfill 스크립트 동작

[`backfill_reconcile_required_orders.py`](scripts/backfill_reconcile_required_orders.py):
- `broker_status = 'reconcile_required'`인 주문을 찾아 `ReconciliationService.trigger()` 호출
- `trigger_type = "requires_reconciliation"`으로 reconciliation run 생성
- Idempotent: 동일 계정에 active run이 이미 있으면 재사용
- `--dry-run`, `--limit`, `--order-id`, `--account-id` 필터 지원

---

## 3. 해결 방안 후보 평가

### Candidate A: Reconciliation Worker에 EXPIRED Fallback 추가

**아이디어**: `_process_order_link()`에서 `resolve_unknown_state()`가 `RECONCILE_REQUIRED`를 반환했을 때, `transition_to_authoritative()`의 EXPIRED fallback 로직을 적용하여 주문을 EXPIRED로 전이시킨 후 reconciliation run을 resolved 처리.

**장점**:
- 근본 원인 해결: stuck 주문이 실제로 해소됨
- 기존 `transition_to_authoritative()`의 EXPIRED fallback 로직 재사용 가능
- 무한 루프 완전 차단

**단점**:
- `transition_to_authoritative()`는 복잡한 메서드(700+ lines)로, reconciliation worker에서 호출 시 사이드 이펙트 위험
- `transition_to_authoritative()`는 `OrderSyncService`에 속해 있어 의존성 주입 필요
- after-hours 조건, grace period 등 시간 기반 조건이 있어 장중/장후 동작이 달라짐
- Paper API가 데이터를 반환하지 않는 근본 문제는 해결하지 않음 (운영 환경에서도 동일 문제 발생 가능)

**구현 복잡도**: 중간~높음  
**리스크**: 중간 (기존 `transition_to_authoritative()` 로직과의 충돌 가능성)

### Candidate B: Stuck `reconcile_required` 직접 정리

**아이디어**: 별도 스크립트나 migration을 통해 stuck된 `reconcile_required` 주문을 강제로 EXPIRED 또는 FAILED로 전이. reconciliation run도 정리.

**장점**:
- 즉시 해결 가능 (1회성 스크립트 실행)
- 구현非常简单 (단순 UPDATE 쿼리)
- 코드 변경 불필요

**단점**:
- **근본 원인 해결 안 됨**: 동일 조건에서 새로운 stuck 주문이 계속 발생
- 데이터 정합성 위험: 강제 상태 전이는 실제 broker 상태와 불일치 가능성
- 수동 개입 필요: 문제 재발 시마다 스크립트 실행
- 운영 환경에서는 더 큰 리스크

**구현 복잡도**: 낮음  
**리스크**: 높음 (데이터 정합성, 근본 미해결)

### Candidate C: Failed Reconciliation Run 재시도 + 모니터링 보강

**아이디어**: `failed` 상태의 reconciliation run을 재시도하는 메커니즘 추가 + 모니터링/알림 보강. 주문 상태는 변경하지 않고, reconciliation run만 재시도.

**장점**:
- 최소한의 코드 변경
- 모니터링 보강으로 문제 인지 개선
- 재시도로 일시적 문제 해결 가능

**단점**:
- **근본 원인 해결 안 됨**: `resolve_unknown_state()`가 계속 `RECONCILE_REQUIRED`를 반환하면 재시도도 계속 실패
- 무한 재시도 루프 지속 (단순히 주기가 빨라질 뿐)
- 모니터링만으로는 문제 해결 불가
- 운영 환경에서도 동일한 패턴으로 stuck 발생 가능

**구현 복잡도**: 낮음  
**리스크**: 중간 (근본 미해결로 인한 지속적 장애)

---

## 4. 최종 선택: **Candidate A**

### 4.1 선정 이유

| 평가 항목 | A (Fallback 추가) | B (직접 정리) | C (재시도+모니터링) |
|-----------|:---:|:---:|:---:|
| 근본 원인 해결 | ✅ | ❌ | ❌ |
| 무한 루프 차단 | ✅ | ✅ (1회성) | ❌ |
| 데이터 정합성 | ✅ | ⚠️ 위험 | ✅ |
| 구현 복잡도 | 중간 | 낮음 | 낮음 |
| 운영 안정성 | 높음 | 낮음 | 중간 |

**결론**: Candidate A만이 근본 원인을 해결하고 무한 루프를 영구적으로 차단할 수 있음. Candidate B는 응급 처치용, Candidate C는 증상 완화용에 불과.

### 4.2 상세 설계

#### 4.2.1 수정 대상

[`src/agent_trading/services/reconciliation_worker.py`](src/agent_trading/services/reconciliation_worker.py) — `_process_order_link()` 메서드

#### 4.2.2 수정 로직

```python
# 현재 (변경 전)
async def _process_order_link(self, ...) -> str:
    result = await adapter.resolve_unknown_state(...)
    resolved_statuses = {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
        OrderStatus.ACKNOWLEDGED,
    }
    if result.status in resolved_statuses:
        return "resolved"
    else:
        return "failed"
```

```python
# 변경 후
async def _process_order_link(self, ...) -> str:
    result = await adapter.resolve_unknown_state(...)
    resolved_statuses = {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
        OrderStatus.ACKNOWLEDGED,
    }
    if result.status in resolved_statuses:
        return "resolved"
    
    # ── EXPIRED fallback: resolve_unknown_state()가 RECONCILE_REQUIRED를 반환했을 때 ──
    # KIS Paper API가 데이터를 반환하지 않는 경우, after-hours 조건에서
    # 미체결 주문을 EXPIRED로 간주하여 stuck 상태 해소
    if result.status == OrderStatus.RECONCILE_REQUIRED:
        if await self._try_expired_fallback(order, broker_order, adapter):
            return "resolved"
    
    return "failed"
```

#### 4.2.3 `_try_expired_fallback()` 설계

```python
async def _try_expired_fallback(
    self,
    order: OrderRequestEntity,
    broker_order: BrokerOrderEntity,
    adapter: KoreaInvestmentAdapter,
) -> bool:
    """RECONCILE_REQUIRED 상태에서 EXPIRED fallback을 시도한다.
    
    조건:
    1. after-hours (장외 시간) 또는
    2. 주문 생성 후 grace period 경과 (예: 30분)
    3. SELL 주문은 position-delta 검증 (선택 사항)
    
    성공 시: 주문을 EXPIRED로 전이하고 True 반환
    실패 시: False 반환 (기존 failed 처리 유지)
    """
    # 조건 1: after-hours 여부 확인
    if not self._is_after_hours():
        # 장중에는 fallback하지 않고 기존 failed 처리 유지
        return False
    
    # 조건 2: grace period 경과 확인 (주문 생성 후 30분)
    now = datetime.now(timezone.utc)
    if broker_order.created_at and (now - broker_order.created_at).total_seconds() < 1800:
        return False
    
    # 조건 3: SELL 주문의 경우 position-delta 검증 (선택 사항)
    if order.side == OrderSide.SELL:
        # position 변화량으로 체결 여부 확인
        # (구현 복잡도를 고려해 Phase 2로 연기 가능)
        pass
    
    # EXPIRED로 전이
    async with transaction() as tx:
        await tx.broker_orders.update_status(
            broker_order_id=broker_order.broker_order_id,
            broker_status=OrderStatus.EXPIRED.value,
        )
        await tx.orders.update_status(
            order_id=order.order_request_id,
            status=OrderStatus.EXPIRED,
        )
    
    logger.info(
        "Expired fallback applied for order %s (broker_native_order_id=%s)",
        order.order_request_id, broker_order.broker_native_order_id,
    )
    return True
```

#### 4.2.4 `_is_after_hours()` — 재사용

[`PostSubmitSyncRunner._is_after_hours()`](src/agent_trading/services/order_sync_service.py:2362)의 로직을 참고:

```python
@staticmethod
def _is_after_hours() -> bool:
    """Check if current time is outside KIS regular trading hours (08:30-15:30 KST)."""
    now = datetime.now(timezone.utc)
    kst = now + timedelta(hours=9)
    if kst.weekday() >= 5:  # 토/일
        return True
    if kst.hour < 8 or (kst.hour == 8 and kst.minute < 30):
        return True
    if kst.hour > 15 or (kst.hour == 15 and kst.minute > 30):
        return True
    if kst.hour == 15 and kst.minute == 30:  # 15:30 KST 정각
        return True
    return False
```

#### 4.2.5 `ReconciliationRunProcessor`에 필요한 의존성 추가

```python
@dataclass
class ReconciliationRunProcessor:
    ...
    # 추가 의존성 없음 — 이미 broker_orders_repo, orders_repo 보유
    # transaction() 컨텍스트는 process_run() 내부에서 사용 가능
```

#### 4.2.6 테스트 계획

| 테스트 케이스 | 설명 |
|--------------|------|
| `test_expired_fallback_after_hours` | 장후 시간에 `RECONCILE_REQUIRED` → EXPIRED fallback 적용 |
| `test_expired_fallback_during_hours` | 장중에는 fallback 미적용 → 기존 failed 유지 |
| `test_expired_fallback_grace_period` | grace period 내에는 fallback 미적용 |
| `test_expired_fallback_resolved_statuses` | 기존 resolved_statuses (FILLED 등)는 fallback 영향 없음 |
| `test_expired_fallback_db_update` | EXPIRED 전이 후 DB 상태 검증 |

---

## 5. 실행 계획

### Phase 1 (즉시) — 응급 조치

1. **Candidate B 병행**: stuck 주문 16건 중 `submitted_at = null`이고 장기간 stuck된 주문은 강제 EXPIRED 처리
   - 단, `c87f5ec3` 주문은 분석 대상으로 보존
   - 나머지 15건은 `broker_status = 'EXPIRED'`로 UPDATE

### Phase 2 (코드 변경) — 근본 해결

1. `reconciliation_worker.py`에 `_try_expired_fallback()` 구현
2. `_process_order_link()`에 fallback 호출 추가
3. 단위 테스트 작성
4. PR → 리뷰 → 머지

### Phase 3 (사후) — 모니터링

1. `reconcile_required` 주문 수 알림 (threshold: 5건 이상)
2. `failed` reconciliation run 알림
3. EXPIRED fallback 적용 로그 모니터링 대시보드 추가

---

## 6. 리스크 및 고려사항

### 6.1 KIS Paper API 한계

현재 Paper 환경에서 `inquire-daily-ccld`가 ODNO 데이터를 반환하지 않는 문제는 **운영 환경에서도 동일하게 발생할 가능성**이 있음. 이는 KIS API의 특성(체결 내역 조회는 실제 체결이 있어야만 데이터 반환) 때문으로, 운영 환경에서도 미체결 주문은 동일한 패턴으로 stuck될 수 있음.

### 6.2 EXPIRED Fallback의 안전성

- **장중 fallback 금지**: 장중에는 실제로 체결될 가능성이 있으므로 fallback하지 않음
- **Grace period**: 주문 생성 후 최소 30분 경과 필요 (네트워크 지연, API 응답 지연 고려)
- **SELL 주문 position 검증**: Phase 2에서 선택적으로 구현 (position-delta로 실제 체결 여부 확인)

### 6.3 `transition_to_authoritative()` 재사용 vs 별도 구현

`transition_to_authoritative()`는 700+ lines의 복잡한 메서드로, reconciliation worker에서 직접 호출하기에는 사이드 이펙트가 큼. 대신 핵심 로직(EXPIRED fallback 조건 판단)만 추출하여 `_try_expired_fallback()`으로 별도 구현하는 것이 안전함.

---

## 7. 결론

| 항목 | 내용 |
|------|------|
| **근본 원인** | Reconciliation worker가 `resolve_unknown_state()`의 `RECONCILE_REQUIRED` 결과를 `resolved_statuses`에서 찾지 못해 항상 `failed` 처리 |
| **선택 방안** | **Candidate A** — EXPIRED fallback을 reconciliation worker에 추가 |
| **핵심 변경** | `_process_order_link()`에서 `RECONCILE_REQUIRED` 수신 시 after-hours 조건에서 EXPIRED로 전이 |
| **기대 효과** | 무한 재시도 루프 차단, stuck 주문 자동 해소, 운영 환경 대비 |
| **리스크** | 장중 fallback 방지, grace period 적용으로 안전성 확보 |
