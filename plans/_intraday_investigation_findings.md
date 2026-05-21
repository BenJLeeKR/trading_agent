# Investigation Findings

## 1. Active Sync Cycle

### Active statuses considered by `run_sync_cycle()`

Defined at [`src/agent_trading/services/order_sync_service.py:1111-1116`](../src/agent_trading/services/order_sync_service.py:1111):

```python
_ACTIVE_SYNC_STATUSES: list[OrderStatus] = [
    OrderStatus.SUBMITTED,
    OrderStatus.ACKNOWLEDGED,
    OrderStatus.PARTIALLY_FILLED,
    OrderStatus.RECONCILE_REQUIRED,
]
```

Additionally, [`_SYNCABLE_STATUSES`](../src/agent_trading/services/order_sync_service.py:31) (used by `sync_order_post_submit()`) is identical:

```python
_SYNCABLE_STATUSES: frozenset[OrderStatus] = frozenset({
    OrderStatus.SUBMITTED,
    OrderStatus.ACKNOWLEDGED,
    OrderStatus.PARTIALLY_FILLED,
    OrderStatus.RECONCILE_REQUIRED,
})
```

### Polling pattern

- **Cycle interval**: Default 30 seconds (`DEFAULT_INTERVAL_SECONDS = 30` at [`scripts/run_post_submit_sync_loop.py:68`](../scripts/run_post_submit_sync_loop.py:68)), configurable via `POST_SUBMIT_SYNC_INTERVAL_SECONDS` env var (minimum 5s enforced at line 80-86).
- **Batch limit**: 200 orders per cycle (`_DEFAULT_BATCH_LIMIT = 200` at [`order_sync_service.py:1109`](../src/agent_trading/services/order_sync_service.py:1109)).
- **Per-order isolation**: Each order sync is wrapped in a DB savepoint (lines 1217-1239) so a single failure doesn't abort the entire cycle.
- **Reconciliation sub-cycle**: After syncing active orders, `_sync_reconcile_required_orders()` is called with `limit=50` (line 1274) to resolve any `RECONCILE_REQUIRED` orders via broker truth inquiry.
- **Graceful shutdown**: SIGTERM/SIGINT handlers complete the current cycle before exiting ([`run_post_submit_sync_loop.py:179-193`](../scripts/run_post_submit_sync_loop.py:179)).

### Market session awareness

**None.** The sync cycle runs identically regardless of whether the market is open (intraday) or closed (after-hours). There is no check for market hours, trading session, or calendar in either `run_sync_cycle()` or `sync_order_post_submit()`.

---

## 2. EXPIRED Fallback Path

### Code path trace

The EXPIRED fallback occurs in [`transition_to_authoritative()`](../src/agent_trading/services/order_sync_service.py:632) which is called from `_sync_reconcile_required_orders()` (line 602). There are **three distinct EXPIRED fallback paths**:

#### Path A: `resolve_unknown_state()` raises an exception (lines 677-779)

1. `broker.resolve_unknown_state()` is called (line 678)
2. If it raises an exception (e.g., `BudgetExhaustedError`, `BrokerError`, network error):
   - **Sell orders first**: Position-delta inference is attempted via `_infer_sell_order_fill_via_position()` (line 692). If inferred → transition to `FILLED`/`PARTIALLY_FILLED`.
   - **If inference fails or not a sell order**: Logs warning at line 740-746, then calls `_try_transition(order, OrderStatus.EXPIRED)` at line 748-749.
3. This is the **primary EXPIRED fallback** — triggered when broker truth is completely unavailable.

#### Path B: `resolve_unknown_state()` returns `RECONCILE_REQUIRED` (lines 802-905)

1. `resolve_unknown_state()` succeeds but returns `RECONCILE_REQUIRED` (broker has no record of the order)
2. `_is_genuine_manual_reconciliation()` is checked (line 803):
   - Returns `True` (skip) if: no `broker_order_id` in result, or order age > 24h
   - Returns `False` (auto-resolve) if: broker returned `CANCELLED`/`REJECTED`/`EXPIRED`
3. If **not** genuine manual reconciliation:
   - **Sell orders**: Position-delta inference attempted (line 818)
   - If inference fails: logs warning at line 865-871, then `_try_transition(order, OrderStatus.EXPIRED)` at line 873-874
4. This is the **secondary EXPIRED fallback** — triggered when broker truth inquiry succeeds but finds no record.

#### Path C: `_is_genuine_manual_reconciliation()` returns `False` for old orders (line 1058-1060)

If order age > 24h (`age.total_seconds() > 86400`), `_is_genuine_manual_reconciliation()` returns `True`, which means the order is **skipped** (left as `RECONCILE_REQUIRED` for manual handling). This prevents auto-EXPIRY of very old orders.

### All conditions that can trigger EXPIRED fallback

| # | Condition | Code Path | Line |
|---|-----------|-----------|------|
| 1 | `resolve_unknown_state()` raises any exception (network, budget, broker error) | Path A | 683-749 |
| 2 | `resolve_unknown_state()` returns `RECONCILE_REQUIRED` AND order is not genuine manual reconciliation AND sell-order position inference fails | Path B | 863-895 |
| 3 | `resolve_unknown_state()` returns `RECONCILE_REQUIRED` AND order is not genuine manual reconciliation AND order is not a sell order | Path B | 863-895 |
| 4 | `_try_transition()` itself fails (DB error, optimistic lock) | Both | 770-778, 896-904 |

### Key observation: No market session check

**None of these paths check whether the market is currently open.** The EXPIRED fallback can trigger during market hours (09:00-15:30 KST) just as easily as after-hours. This is the core problem — an unfilled order that was submitted during market hours could be prematurely EXPIRED by the next sync cycle if the KIS paper API returns no data.

---

## 3. Market Session Awareness

### Finding: No market session awareness exists

- [`transition_to_authoritative()`](../src/agent_trading/services/order_sync_service.py:632) — **No market session check.** The method unconditionally falls back to EXPIRED when broker truth is unavailable.
- [`run_sync_cycle()`](../src/agent_trading/services/order_sync_service.py:1145) — **No market session check.** Polls active orders identically regardless of time.
- [`sync_order_post_submit()`](../src/agent_trading/services/order_sync_service.py:90) — **No market session check.**
- [`scripts/run_post_submit_sync_loop.py`](../scripts/run_post_submit_sync_loop.py) — **No market session check.** The loop runs 24/7 with the same interval.

### Where market session IS checked (elsewhere)

The only market-session-aware code is in [`KISRestClient.inquire_daily_ccld()`](../src/agent_trading/brokers/koreainvestment/rest_client.py:939) via the `after_hours` parameter, which controls pagination limits (more conservative after-hours). However:
- `get_order_status()` (line 1068) always calls `inquire_daily_ccld()` with `after_hours=False` (line 1085)
- `resolve_unknown_state()` (line 1512) always calls with `after_hours=True` (line 1556)

So `resolve_unknown_state()` uses conservative pagination, but this is about API call budget, not about whether EXPIRED fallback is appropriate.

### Risk

During market hours (09:00-15:30 KST), an unfilled limit order is a normal condition. If the KIS paper API returns no data for that order (which is a known limitation of the paper environment), the sync cycle will:
1. Call `resolve_unknown_state()` → gets `RECONCILE_REQUIRED` or exception
2. Fall back to EXPIRED
3. The order is marked as expired even though it's still working at the broker

This is confirmed by the DB data (see Section 6).

---

## 4. `cancel_order()` Readiness

### Protocol definition

[`BrokerAdapter` protocol](../src/agent_trading/brokers/base.py:176):
```python
async def cancel_order(self, request: CancelOrderRequest) -> CancelOrderResult:
    """Cancel a working order."""
```

[`CancelOrderRequest`](../src/agent_trading/domain/models.py:161) fields:
- `account_ref: str`
- `client_order_id: str`
- `broker_order_id: str | None`
- `correlation_id: str`
- `reason: str | None = None`

Note: `CancelOrderRequest` does **not** have a `quantity` field.

### Adapter implementation

[`KoreaInvestmentAdapter.cancel_order()`](../src/agent_trading/brokers/koreainvestment/adapter.py:344):
```python
async def cancel_order(self, request: CancelOrderRequest) -> CancelOrderResult:
    try:
        return await self._rest.cancel_order(
            account_ref=request.account_ref,
            client_order_id=request.client_order_id,
            broker_order_id=request.broker_order_id,
            correlation_id=request.correlation_id,
            quantity=request.quantity,  # <-- BUG: CancelOrderRequest has no 'quantity' field!
        )
    except BudgetExhaustedError:
        return CancelOrderResult(...)
```

**BUG**: Line 351 passes `request.quantity` but `CancelOrderRequest` (defined at [`domain/models.py:161`](../src/agent_trading/domain/models.py:161)) has **no `quantity` field**. This would raise `AttributeError` at runtime.

### REST client implementation

[`KISRestClient.cancel_order()`](../src/agent_trading/brokers/koreainvestment/rest_client.py:893):
```python
async def cancel_order(
    self,
    broker_order_id: str,
    symbol: str,
    quantity: Decimal,
) -> CancelOrderResult:
```

Uses the `order_rvsecncl` endpoint (line 917) with `RVSE_CNCL_DVSN_CD = "02"` (cancel). The endpoint is defined at [`rest_client.py:62`](../src/agent_trading/brokers/koreainvestment/rest_client.py:62):
```python
"order_rvsecncl": "/uapi/domestic-stock/v1/trading/order-rvsecncl",
```

TR ID mapping at line 83:
```python
"order_rvsecncl": ("TTTC0013U", "VTTC0013U"),  # 정정취소
```

### Signature mismatch

There is a **critical signature mismatch** between the layers:

| Layer | Method Signature |
|-------|-----------------|
| `BrokerAdapter` protocol | `cancel_order(request: CancelOrderRequest)` |
| `KoreaInvestmentAdapter.cancel_order()` | `cancel_order(request: CancelOrderRequest)` — passes `request.quantity` (doesn't exist) |
| `KISRestClient.cancel_order()` | `cancel_order(broker_order_id: str, symbol: str, quantity: Decimal)` — needs `symbol` |

The adapter passes `request.quantity` (AttributeError) and doesn't pass `symbol` (missing parameter). **This code path is currently broken/unreachable.**

### Summary

| Aspect | Status |
|--------|--------|
| Protocol defined | ✅ Yes, at `base.py:176` |
| Adapter method exists | ✅ Yes, at `adapter.py:344` |
| REST client method exists | ✅ Yes, at `rest_client.py:893` |
| Correct KIS endpoint used | ✅ `order_rvsecncl` with `RVSE_CNCL_DVSN_CD=02` |
| Signature wiring correct | ❌ **No** — `CancelOrderRequest` lacks `quantity` and `symbol` fields |
| Budget exhaustion handled | ✅ Yes, returns `RECONCILE_REQUIRED` |
| **Production-ready** | ❌ **No — broken wiring** |

---

## 5. `amend_order()` Readiness

### Protocol definition

[`BrokerAdapter` protocol](../src/agent_trading/brokers/base.py:179):
```python
async def amend_order(self, request: AmendOrderRequest) -> AmendOrderResult:
    """Amend a working order if the broker supports it."""
```

[`AmendOrderRequest`](../src/agent_trading/domain/models.py:181) fields:
- `account_ref: str`
- `client_order_id: str`
- `broker_order_id: str | None`
- `correlation_id: str`
- `new_quantity: Decimal | None = None`
- `new_price: Decimal | None = None`

### Adapter implementation

[`KoreaInvestmentAdapter.amend_order()`](../src/agent_trading/brokers/koreainvestment/adapter.py:363):
```python
async def amend_order(self, request: AmendOrderRequest) -> AmendOrderResult:
    raise UnsupportedCapabilityError(
        broker_name=self.broker_name,
        error_type=BrokerErrorType.UNSUPPORTED_CAPABILITY,
        retryable=False,
        correlation_id=request.correlation_id,
        raw_message="Amend implementation is not available in the scaffold.",
    )
```

**This is a stub that always raises `UnsupportedCapabilityError`.**

### REST client: No amend endpoint

`KISRestClient` has **no `amend_order()` method**. The `order_rvsecncl` endpoint (line 62) supports both cancel (`RVSE_CNCL_DVSN_CD=02`) and revise/amend (`RVSE_CNCL_DVSN_CD=01`), but only the cancel path is implemented.

### What would be needed for amend

The KIS `order-rvsecncl` endpoint supports amend via `RVSE_CNCL_DVSN_CD = "01"` (정정). Parameters needed:
- `ORGN_ODNO`: Original order number
- `ORD_DVSN`: Order type (00=limit, 01=market)
- `ORD_QTY`: New quantity
- `ORD_UNPR`: New price
- `RVSE_CNCL_DVSN_CD`: "01" for amend

The endpoint and TR ID already exist in the mappings. Only the method implementation is missing.

### `supports_order_amend` capability flag

[`KoreaInvestmentAdapter.get_capabilities()`](../src/agent_trading/brokers/koreainvestment/adapter.py:99) returns `supports_order_amend=True`, which is **misleading** — the actual implementation raises `UnsupportedCapabilityError`.

### Summary

| Aspect | Status |
|--------|--------|
| Protocol defined | ✅ Yes, at `base.py:179` |
| Adapter method exists | ✅ Yes, but **stub** — raises `UnsupportedCapabilityError` |
| REST client method exists | ❌ **No** — not implemented |
| KIS endpoint available | ✅ `order_rvsecncl` with `RVSE_CNCL_DVSN_CD=01` |
| TR ID available | ✅ `TTTC0013U` / `VTTC0013U` |
| Capability flag correct | ❌ **No** — `supports_order_amend=True` is misleading |
| **Production-ready** | ❌ **No — not implemented** |

---

## 6. Sample Orders

### Open / Unfilled Orders

**No open/unfilled orders found.** Query:
```sql
SELECT o.order_request_id, o.side, o.status, o.requested_quantity, o.created_at,
       bo.broker_order_id, bo.broker_native_order_id, bo.broker_status, bo.last_synced_at
FROM trading.order_requests o
JOIN trading.broker_orders bo ON bo.order_request_id = o.order_request_id
WHERE o.status NOT IN ('filled', 'cancelled', 'rejected', 'expired')
ORDER BY o.created_at DESC
LIMIT 10;
```
**Result: 0 rows.** All orders that have been submitted to the broker are either `filled`, `rejected`, or `expired`.

### Pending Submit Orders

**16 orders** in `pending_submit` status — these have not yet been submitted to the broker (no `broker_orders` record). All are sell orders created on 2026-05-19 between 00:28 and 01:10 UTC (09:28-10:10 KST). These are queued but not yet sent.

### Recently EXPIRED Orders (during market hours)

**1 order** was EXPIRED that was created during market hours on 2026-05-19:

| Field | Value |
|-------|-------|
| `order_request_id` | `753c0ded-f8eb-4b27-bbde-d4d9627304bd` |
| `side` | sell |
| `status` | expired |
| `requested_quantity` | 10 |
| `requested_price` | 1,791,000 KRW |
| `created_at` | 2026-05-19 00:58:10 UTC (09:58 KST) |
| `updated_at` | 2026-05-19 08:14:55 UTC (17:14 KST) |
| `broker_native_order_id` | `0000011357` |
| `broker_status` | `reconcile_required` |

**This is the critical finding**: A sell order created at **09:58 KST** (during market hours) was EXPIRED at **17:14 KST** (after market close). The broker status is still `reconcile_required`, meaning the broker never confirmed the order's fate. The EXPIRED transition happened via the fallback path when the sync cycle ran after hours and `resolve_unknown_state()` failed or returned no record.

### All EXPIRED Orders (18 total)

All 18 expired orders share the same pattern:
- Created on 2026-05-18 (02:13-03:38 UTC = 11:13-12:38 KST) or 2026-05-19 (00:58 UTC = 09:58 KST)
- All updated_at = 2026-05-19 08:14:55 UTC (17:14 KST) — the exact time the batch EXPIRED transition ran
- All have `broker_status = 'reconcile_required'`
- All have valid `broker_native_order_id` values (KIS ODNOs like `0000011357`, `0000026321`, etc.)

### Order Status Distribution

| Status | Count |
|--------|-------|
| `rejected` | 97 |
| `expired` | 19 |
| `pending_submit` | 16 |
| `filled` | 7 |

**Total: 139 orders.** No orders are currently in `submitted`, `acknowledged`, `partially_filled`, or `reconcile_required` status — all non-terminal orders have been either filled, rejected, or expired.

---

## Key Findings Summary

1. **EXPIRED fallback is session-agnostic**: `transition_to_authoritative()` does not check whether the market is open. It will EXPIRE an unfilled order during market hours if broker truth is unavailable.

2. **Confirmed case**: Order `753c0ded` (sell, created 09:58 KST on 2026-05-19) was EXPIRED at 17:14 KST. This was a legitimate intraday order that was unfilled during market hours but got caught by the after-hours sync cycle's EXPIRED fallback.

3. **cancel_order() wiring is broken**: The adapter passes `request.quantity` which doesn't exist on `CancelOrderRequest`, and doesn't pass `symbol` which `KISRestClient.cancel_order()` requires.

4. **amend_order() is a stub**: Raises `UnsupportedCapabilityError` despite `supports_order_amend=True` in capabilities.

5. **No open orders currently**: All submitted orders have been resolved to terminal states (filled/rejected/expired). The 16 `pending_submit` orders are sell orders queued for submission.

### Recommended Policy Changes

1. **Add market session awareness** to `transition_to_authoritative()`: Skip EXPIRED fallback during market hours (09:00-15:30 KST). Instead, leave the order in `RECONCILE_REQUIRED` and retry on the next cycle.

2. **Fix cancel_order() wiring**: Add `quantity` and `symbol` to `CancelOrderRequest`, or change the adapter to resolve these from the order/broker_order entities.

3. **Implement amend_order()** in `KISRestClient` using `order_rvsecncl` with `RVSE_CNCL_DVSN_CD=01`.

4. **Consider a grace period**: Even after market close, don't immediately EXPIRE. Wait for the next day's settlement data before falling back.
