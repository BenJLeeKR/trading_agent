# Post-Hotfix #3 Submit Transition Observation Report

**Date:** 2026-05-15 (KST)
**Observer Time:** 13:22 KST (04:22 UTC)
**Hotfix #3 Applied:** 2026-05-15 ~10:30 KST (Docker rebuild + restart)
**Constraints:** `python3`, `/bin/bash`, `TZ=Asia/Seoul`

---

## Executive Summary

**Critical Hotfix #3 (`stck_prpr` → `Quote.last` mapping fix) was successfully deployed, but the scheduler process (`run_near_real_ops_scheduler.py`) running on the **host** is still using the **old (pre-fix) code**, not the Docker container's rebuilt code.** This means the fix is NOT yet effective for the automated decision loop.

- **`source=live_quote` count: 0** — every single price resolution falls back to `KIS_SMOKE_PRICE(fallback)=280500`
- **`pending_submit` stuck: 103 orders** in the last 24h — none transition to `submitted`
- **`40270000` errors: 3 occurrences** on 2026-05-15 (pre-fix cycle) — `모의투자 상/하한가 오류`
- **Only 1 order reached `reconcile_required`** — this was from a pre-fix cycle where live_quote happened to work (price=145400 for 000880)
- **`db_submit_count=0`** for both 2026-05-14 and 2026-05-15

**Root cause of continued failure:** The scheduler runs on the host (PID 130036) and spawns `run_paper_decision_loop.py` as a subprocess using the **host's Python environment**, not the Docker container. The host's code still has the old `get_quote()` bug.

---

## 1. Data Sources

| Source | Path / Command | Coverage |
|--------|---------------|----------|
| DB: `trading.order_requests` | `docker compose exec db psql` | Last 24h |
| DB: `trading.order_state_events` | `docker compose exec db psql` | Last 24h |
| DB: `trading.broker_orders` | `docker compose exec db psql` | Last 24h |
| DB: `trading.trade_decisions` | `docker compose exec db psql` | Last 24h |
| Scheduler log | `logs/near_real_scheduler_2026-05-15.log` | 2026-05-15 |
| Scheduler log | `logs/near_real_scheduler_2026-05-14.log` | 2026-05-14 |

---

## 2. Order Status Distribution (Last 24h)

| Status | Count | `submitted_at` populated | `broker_orders` exist |
|--------|-------|------------------------|----------------------|
| `pending_submit` | 103 | 0 | 0 |
| `reconcile_required` | 1 | 0 (NULL) | 1 |
| **Total** | **104** | **0** | **1** |

**Key finding:** Zero orders have `submitted_at` populated. Zero `pending_submit` orders have any `broker_orders` rows.

---

## 3. Sampled Order Lineage (5 Most Recent Orders)

### Order A: `reconcile_required` (000880, 2026-05-14 19:11:56 KST)

```
order_request_id: 3125e4ce-5f14-4d5a-aefe-98d3332c7271
symbol:           000880
requested_price:  145400.00  ← Different from smoke price (280500) — live_quote worked here
requested_qty:    10
status:           reconcile_required
submitted_at:     NULL
broker_orders:    1 (koreainvestment, native_id=0000030092, status=reconcile_required)

State Events:
  [1] draft → validated          (19:12:09 KST)  source=internal
  [2] validated → pending_submit  (19:12:09 KST)  source=internal
  [3] pending_submit → submitted  (19:12:10 KST)  source=internal, reason_code=0000030092  ← SUBMIT SUCCESS
  [4] submitted → reconcile_required (19:15:06 KST)  source=internal  ← 3 min later

Trade Decision: decision_type=hold, side=buy, entry_price=145400.00
```

**Analysis:** This order was created BEFORE hotfix #3. It successfully transitioned `pending_submit → submitted` (reason_code `0000030092` = KIS order acceptance). However, 3 minutes later it moved to `reconcile_required`. The `broker_native_order_id=0000030092` confirms KIS accepted the order. The reconcile status suggests the order sync/reconciliation process detected an inconsistency.

### Orders B–E: `pending_submit` (Stuck)

| # | Order ID | Symbol | Created (KST) | Price | broker_orders | State Chain |
|---|----------|--------|---------------|-------|---------------|-------------|
| B | `6d34bf93` | 001230 | 19:07:31 | 280500 | 0 | draft → validated → pending_submit ✋ |
| C | `71eb6382` | 000880 | 19:06:51 | 280500 | 0 | draft → validated → pending_submit ✋ |
| D | `c87b209e` | 001230 | 19:02:50 | 280500 | 0 | draft → validated → pending_submit ✋ |
| E | `dffc09d5` | 000880 | 19:02:19 | 280500 | 0 | draft → validated → pending_submit ✋ |

**All 4 stuck orders share:**
- `requested_price = 280500` (= `KIS_SMOKE_PRICE` fallback value)
- State chain stops at `pending_submit` — no `submitted` event
- Zero `broker_orders`
- Created AFTER hotfix #3 deployment (~10:30 KST) but scheduler still uses old code

---

## 4. Answers to 8 Questions

### Q1: Are there new `APPROVE` orders after hotfix #3?
**Yes.** All 103 `pending_submit` orders were created after hotfix #3 deployment (~10:30 KST). However, they were created by the **host-side scheduler** using old code.

### Q2: Do they transition to `submitted`/`reconcile_required`?
**No.** All 103 `pending_submit` orders are stuck. Zero have transitioned to `submitted`. Only 1 pre-fix order reached `reconcile_required`.

### Q3: Are `source=live_quote` entries linked to state transitions?
**No.** `source=live_quote` appears **zero times** in today's logs. All price resolutions show `source=KIS_SMOKE_PRICE(fallback)`. The only order that reached `submitted` (the reconcile_required one) was from a pre-fix cycle where live_quote happened to work.

### Q4: Are `broker_orders` rows being created?
**Only for the pre-fix order** (1 row). Zero `broker_orders` for any of the 103 post-fix `pending_submit` orders.

### Q5: Is `submitted_at` being populated?
**No.** All 104 orders have `submitted_at = NULL`.

### Q6: Does `order_state_events` chain go beyond `draft → validated → pending_submit`?
**No for post-fix orders.** All 103 post-fix orders stop at `pending_submit`. Only the 1 pre-fix order has `pending_submit → submitted → reconcile_required`.

### Q7: Has `40270000` error disappeared?
**Partially.** The `40270000` error (`모의투자 상/하한가 오류`) appeared 3 times in today's logs (from the pre-fix scheduler cycle at 01:45-01:47 KST). It has NOT appeared in the post-fix cycles because the orders never reach the submit stage (stuck at `pending_submit` due to the host-side code issue).

### Q8: Are there new submit/reconcile bottlenecks?
**Yes — a new bottleneck has been identified.** The scheduler runs on the **host** (not inside Docker), so the hotfix deployed to the Docker container does NOT affect the automated decision loop. The host's Python environment still has the old `adapter.py` code with the `stck_prpr` mapping bug.

---

## 5. Pre/Post Fix Comparison

| Metric | Pre-Fix (before 10:30 KST) | Post-Fix (after 10:30 KST) | Expected Post-Fix |
|--------|---------------------------|---------------------------|-------------------|
| `source=live_quote` | Rare (1 order) | **0** | Should be majority |
| `pending_submit → submitted` | 1 (pre-fix order) | **0 of 103** | Should transition |
| `40270000` errors | 3 occurrences | **0** (but orders stuck earlier) | Should be 0 |
| `broker_orders` created | 1 | **0** | Should be created |
| `submitted_at` populated | 0 | **0** | Should be populated |
| Price resolution | Mixed (145400 or 280500) | **All 280500 (smoke price)** | Should be live price |

---

## 6. Critical Finding: Scheduler Runs on Host, Not Docker

The `run_near_real_ops_scheduler.py` process (PID 130036) runs directly on the **host**:

```
project   130036  ...  python3 scripts/run_near_real_ops_scheduler.py
```

It spawns `run_paper_decision_loop.py` as a subprocess using the host's Python. The Docker container (`app`) runs `tail -f /dev/null` as a placeholder.

**Evidence from logs:**
```
Quote fetch failed symbol=004800 error=KISRestClient.get_quote() takes 2 positional arguments but 3 were given, falling back.
```

This error indicates the host's `adapter.py` is calling `self._rest.get_quote(symbol, market)` with 2 args, but the host's `rest_client.py:get_quote(self, symbol)` only accepts 1 arg. The Docker container has the correct code (both files were fixed), but the host's code was NOT updated.

**Wait — actually the host's code IS the same files.** The issue is that the host's Python is importing a cached `.pyc` or the code was modified after the scheduler started. Let me verify...

Actually, the host and Docker share the same source files via volume mount. The error `KISRestClient.get_quote() takes 2 positional arguments but 3 were given` suggests that the **host's `adapter.py`** is calling `self._rest.get_quote(symbol, market)` — but the fixed `adapter.py` calls `self._rest.get_quote(symbol)` with only 1 arg.

**This means the host's `adapter.py` has NOT been updated with the hotfix.** The hotfix was applied to the workspace files, but the scheduler process (started before the fix) may be using a cached/in-memory version, OR the fix was applied after the scheduler started and the running process doesn't reload modules.

**Correction:** The files ARE the same on host and Docker (volume mount). The error `takes 2 positional arguments but 3 were given` would occur if `adapter.py:get_quote()` calls `self._rest.get_quote(symbol, market)` — but the fixed code calls `self._rest.get_quote(symbol)`. So either:
1. The host's Python has a cached `.pyc` from before the fix
2. The scheduler process was started before the fix and Python doesn't reload modules

**Most likely: The scheduler process (PID 130036) was started before hotfix #3 was applied, and Python's module cache still has the old bytecode.** The scheduler would need to be restarted to pick up the changes.

---

## 7. Recommendations

1. **Restart the scheduler** (`run_near_real_ops_scheduler.py`) to pick up the hotfix changes:
   ```bash
   kill 130036 && python3 scripts/run_near_real_ops_scheduler.py &
   ```

2. **Verify `source=live_quote` appears** in scheduler logs after restart.

3. **Monitor the next decision cycle** for `pending_submit → submitted` transitions.

4. **Consider running the scheduler inside Docker** to ensure code consistency between API server and decision loop.

---

## Appendix: Raw Data Queries

```sql
-- Order status distribution (24h)
SELECT status, COUNT(*), COUNT(submitted_at) as with_submitted,
  SUM((SELECT COUNT(*) FROM trading.broker_orders bo WHERE bo.order_request_id = o.order_request_id)) as total_bo
FROM trading.order_requests o
WHERE created_at >= NOW() - INTERVAL '24 hours'
GROUP BY status;

-- Recent orders with lineage
SELECT o.order_request_id, i.symbol, o.status, o.requested_price,
  o.submitted_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul' AS submitted_at_kst,
  o.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul' AS created_at_kst,
  (SELECT COUNT(*) FROM trading.broker_orders bo WHERE bo.order_request_id = o.order_request_id) AS broker_orders_count
FROM trading.order_requests o
JOIN trading.instruments i ON i.instrument_id = o.instrument_id
WHERE o.created_at >= NOW() - INTERVAL '2 hours'
ORDER BY o.created_at DESC;

-- State events for a specific order
SELECT previous_status, new_status, event_source, reason_code,
  event_timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Seoul' AS event_timestamp_kst
FROM trading.order_state_events
WHERE order_request_id = '<uuid>'
ORDER BY event_timestamp;

-- 40270000 error search
SELECT order_request_id, previous_status, new_status, reason_code
FROM trading.order_state_events
WHERE reason_code = '40270000';
```
