# Intraday Cash Sync & Submit Observability Report

**Date**: 2026-05-15 (KST)
**Observation Window**: 09:59 ~ 10:17 KST
**Author**: Roo (Code Mode)

---

## 1. Executive Summary

| Question | Answer |
|----------|--------|
| Does pre-market (08:00 KST) sync refresh cash snapshots? | **No** — pre-market sync at 08:00:02 KST completed in 0.79s with `cash_synced_count=0`. Cash snapshots only become fresh after 09:00 KST when intraday snapshot sync starts. |
| When does the first fresh cash snapshot appear? | **09:00:08 KST** — first intraday sync after market open. Cash age drops from ~12h stale to <1s fresh. |
| Do APPROVE orders escape `pending_submit`? | **No (still)** — after `logger` fix, orders now reach KIS API but are rejected with `모의투자 상/하한가 오류` (msg_cd=40270000). |
| Are `reason_code` / `reason_detail` populated on `pending_submit` orders? | **No** — all 29 `pending_submit` orders have `status_reason_code=NULL` and `status_reason_message=NULL`. |
| Do new logging patterns appear in scheduler log? | **YES** — after scheduler restart at 10:03 KST, new patterns confirmed: `Phase 5: submit_order_to_broker`, `Phase 5 FAILED (order_submit)` with symbol/decision_type, `Cycle 1 submit result` with error details, `Broker submit RAISED` with full BrokerError context. |
| What is the root cause of submit failure? | **Two root causes identified**: (1) `name 'logger' is not defined` — **FIXED** at 10:13 KST. (2) `모의투자 상/하한가 오류` (msg_cd=40270000) — `KIS_SMOKE_PRICE=280500` is outside daily price limit band for symbols 000880 and 001230. **Still open.** |

---

## 2. Cash Snapshot Freshness Timeline

### 2.1 `cash_balance_snapshots` Hourly Distribution (Last 24h)

| Hour (KST) | Count | First Snapshot | Last Snapshot |
|------------|-------|----------------|---------------|
| 2026-05-14 10:00 | 19 | 10:03:55 | 10:55:19 |
| 2026-05-14 11:00 | 12 | 11:00:30 | 11:56:36 |
| 2026-05-14 12:00 | 13 | 12:01:42 | 12:58:26 |
| 2026-05-14 13:00 | 11 | 13:03:37 | 13:55:20 |
| 2026-05-14 14:00 | 12 | 14:00:42 | 14:57:57 |
| 2026-05-14 15:00 | 8 | 15:03:22 | 15:59:38 |
| 2026-05-14 16:00 | 7 | 16:04:38 | 16:59:44 |
| 2026-05-14 17:00 | 5 | 17:29:46 | 17:54:49 |
| 2026-05-14 18:00 | 9 | 18:04:50 | 18:54:55 |
| 2026-05-14 19:00 | 6 | 19:04:56 | 19:55:00 |
| 2026-05-14 20:00 | 11 | 20:00:01 | 20:55:06 |
| 2026-05-14 21:00 | 7 | 21:05:07 | 21:55:12 |
| **2026-05-15 09:00** | **21** | **09:00:08** | **09:57:26** |
| 2026-05-15 10:00 | 1 | 10:00:47 | 10:00:47 |

**Key Finding**: There is a **~12-hour gap** in cash snapshots between 21:55 KST (last evening sync) and 09:00 KST (first intraday sync next day). The pre-market sync at 08:00 KST does NOT produce a fresh cash snapshot.

### 2.2 `position_snapshots` vs `cash_balance_snapshots` Comparison

| Time Range | Position Snapshots | Cash Snapshots | Gap |
|------------|-------------------|----------------|-----|
| 2026-05-14 22:00~23:00 | 25 (continuous) | **0** | Positions sync overnight, cash does not |
| 2026-05-15 00:00~02:00 | 27 (continuous) | **0** | Same pattern |
| 2026-05-15 07:00~08:00 | 17 (continuous) | **0** | Same pattern |
| 2026-05-15 08:00~09:00 | 15 | **0** | Pre-market sync (08:00-08:57) produces positions but NO cash |
| 2026-05-15 09:00~10:00 | 24 | 21 | Both sync after market open |

**Root Cause Confirmed**: The KIS API (`get_cash_balance()`) returns empty/zero before market open (09:00 KST). The `sync_kis_account_snapshots()` function correctly calls both `get_positions()` and `get_cash_balance()`, but the cash endpoint returns no data during pre-market hours. This results in `cash_balance_synced=False` / `cash_synced_count=0` for all pre-market and early intraday syncs until 09:00 KST.

---

## 3. `snapshot_sync_runs` — Cash Sync Zero Pattern

### 3.1 Today (2026-05-15) Pre-Market to Market Open

| Time (KST) | Status | Cash Synced | Positions | Trigger |
|------------|--------|-------------|-----------|---------|
| 08:00:02 | pre_snapshot_sync | **0** | 1 | scheduler |
| 08:47:24 | partial | **0** | 1 | scheduler |
| 08:50:00 | partial | **0** | 1 | scheduler |
| 08:52:24 | partial | **0** | 1 | scheduler |
| 08:55:02 | partial | **0** | 1 | scheduler |
| 08:57:24 | partial | **0** | 1 | scheduler |
| **09:00:06** | **completed** | **1** | **1** | **scheduler ← First cash sync success** |
| 09:02:25 | completed | 1 | 1 | scheduler |
| 09:05:09 | completed | 1 | 1 | scheduler |
| 09:07:29 | partial | **0** | 1 | scheduler (intermittent KIS failure) |
| 09:10:13 | completed | 1 | 1 | scheduler |
| ... | ... | ... | ... | ... |

**Pattern**: From 08:00 to 08:57 KST, all syncs show `cash_synced_count=0`. After 09:00 KST, most syncs show `cash_synced_count=1` with occasional intermittent `partial` failures.

### 3.2 Yesterday (2026-05-14) Same Pattern

The identical pattern was observed on 2026-05-14: pre-market sync at 08:00:02 KST with `cash_synced_count=0`, first successful cash sync at 09:00:06 KST.

---

## 4. Order Status Distribution

### 4.1 `order_requests` Status (Last 24h)

| Status | Count |
|--------|-------|
| `pending_submit` | **29** |
| `submitted` | **0** |
| `reconcile_required` | **0** |
| `rejected` | **0** |
| `filled` | **0** |
| `cancelled` | **0** |

**All 29 orders are stuck in `pending_submit`**. Zero orders have ever transitioned out.

### 4.2 `pending_submit` Orders Detail

All 29 orders share identical characteristics:
- **Side**: `buy`
- **Type**: `limit`
- **Quantity**: 10.00000000
- **`status_reason_code`**: `NULL` (not populated)
- **`status_reason_message`**: `NULL` (not populated)
- **Time range**: 2026-05-14 14:12 ~ 2026-05-15 09:57 KST

### 4.3 `broker_orders` Status (Last 24h)

**No broker_orders exist** — zero orders reached the broker adapter.

### 4.4 `order_state_events` Status (Last 24h)

**No order_state_events exist** — no state transitions were recorded.

---

## 5. Trade Decisions Analysis

### 5.1 Decision Type Distribution (Last 24h)

| Decision Type | Count |
|---------------|-------|
| `hold` | 890 |
| `reduce` | 17 |
| `approve` | **15** |

### 5.2 APPROVE Decision Time Series

| Time (KST) | Symbol | Side | Has Order? | Order Status |
|------------|--------|------|------------|--------------|
| 2026-05-14 14:12 | 000880 | buy | Yes | `pending_submit` |
| 2026-05-14 14:12 | 001440 | buy | Yes | `pending_submit` |
| 2026-05-14 23:06 | 000880 | buy | **No** | N/A |
| 2026-05-15 08:51 | 000880 | buy | Yes | `pending_submit` |
| 2026-05-15 08:56 | 000880 | buy | Yes | `pending_submit` |
| 2026-05-15 09:01 | 000880 | buy | Yes | `pending_submit` |
| 2026-05-15 09:06 | 000880 | buy | Yes | `pending_submit` |
| 2026-05-15 09:16 | 000880 | buy | Yes | `pending_submit` |
| 2026-05-15 09:22 | 000880 | buy | Yes | `pending_submit` |
| 2026-05-15 09:24 | 000880 | buy | **No** | N/A |
| 2026-05-15 09:27 | 000880 | buy | Yes | `pending_submit` |
| 2026-05-15 09:29 | 000880 | buy | **No** | N/A |
| 2026-05-15 09:32 | 000880 | buy | Yes | `pending_submit` |
| 2026-05-15 09:33 | 000880 | buy | **No** | N/A |
| 2026-05-15 09:42 | 000880 | buy | Yes | `pending_submit` |

**Key Finding**: 11 out of 15 APPROVE decisions have corresponding `order_requests`, all in `pending_submit`. 4 APPROVE decisions have NO order — these are cases where the pipeline failed before `create_order` (likely Phase 4c stale snapshot guardrail blocking).

### 5.3 Symbol Concentration

- **000880** (not identified): 14 out of 15 APPROVE decisions
- **001440** (not identified): 1 out of 15 APPROVE decisions

The system is repeatedly generating APPROVE decisions for the same symbol (`000880`) every ~5 minutes, but all resulting orders remain stuck in `pending_submit`.

---

## 6. Scheduler `decision_submit_gate` Failure Pattern — ROOT CAUSE IDENTIFIED

Every `decision_submit_gate` task consistently fails:
- **returncode=1**
- **Duration**: ~183-189 seconds (consistent)
- **Frequency**: Every ~3 minutes

### 6.1 Root Cause #1: `name 'logger' is not defined` in `order_manager.py` (FIXED)

After scheduler restart at 10:03 KST, the new logging revealed the exact failure:

```
2026-05-15 10:05:48 [INFO] paper-decision-loop: Phase 5: submit_order_to_broker — order_id=fc1fb812... broker=KoreaInvestmentAdapter symbol=000880 decision_type=BUY quantity=10
2026-05-15 10:05:48 [ERROR] paper-decision-loop: Phase 5 FAILED (order_submit): order_id=fc1fb812... symbol=000880 decision_type=BUY trade_decision_id=9e7ab77b...
    submitted_order = await order_manager.submit_order_to_broker(
  File ".../order_manager.py", line 410, in submit_order_to_broker
2026-05-15 10:05:48 [INFO] paper-decision-loop: Cycle 1 submit result: status=ERROR error_phase=order_submit error_message=submit_order_to_broker() failed: name 'logger' is not defined
```

**The `submit_order_to_broker()` method in `order_manager.py` was missing `import logging` and `logger = logging.getLogger(__name__)`.** The new logging code added in the previous session references `logger.exception()` but `logger` was never imported.

### 6.2 Fix #1 Applied (10:13 KST)

Added to [`src/agent_trading/services/order_manager.py`](src/agent_trading/services/order_manager.py):
- `import logging` (line 5)
- `logger = logging.getLogger(__name__)` (line 24)

### 6.3 Pipeline Actually Reaches Phase 5

The new logging confirms that the pipeline **does** progress past Phase 4c (stale snapshot guardrail) and reaches Phase 5 (broker submit). The guardrail is NOT the primary blocker — the broker submit itself was failing due to the `logger` bug.

### 6.4 Fix #1 Verification — ✅ SUCCESS (10:15 KST)

After the `logger` fix, the next `decision_submit_gate` cycle (10:14-10:17 KST) confirmed:

| Log Pattern | Status | Details |
|------------|--------|---------|
| `Phase 5: submit_order_to_broker` | ✅ **Still working** | `order_id=68a8b227... symbol=000880 decision_type=APPROVE quantity=10` |
| `Phase 5 FAILED (order_submit)` | ✅ **Still working** | But with **different error** (see below) |
| `NameError: name 'logger' is not defined` | ❌ **GONE** | `logger` fix successful |
| `Broker submit RAISED` | ✅ **New log pattern** | `order_id=68a8b227... symbol=000880 broker=KoreaInvestmentAdapter — BrokerError: ...` |
| `HTTP Request: POST ... order-cash` | ✅ **New log pattern** | KIS API was actually called: `HTTP/1.1 200 OK` |
| `Cycle 1 submit result` | ✅ **Still working** | `status=ERROR error_phase=order_submit error_message=...` |

**The `NameError` is completely resolved.** The pipeline now progresses past the `logger.exception()` call and reaches the actual KIS API call.

### 6.5 Root Cause #2: `모의투자 상/하한가 오류` (msg_cd=40270000) — NEW DISCOVERY

After the `logger` fix, a **new error** emerged at 10:15:23 KST:

```
2026-05-15 10:15:23 [INFO] paper-decision-loop: Phase 5: submit_order_to_broker — order_id=68a8b227-0587-42bf-96a7-5186d72d30a9 broker=KoreaInvestmentAdapter symbol=000880 decision_type=APPROVE quantity=10
2026-05-15 10:15:23 [INFO] paper-decision-loop: HTTP Request: POST https://openapivts.koreainvestment.com:29443/uapi/domestic-stock/v1/trading/order-cash "HTTP/1.1 200 OK"
2026-05-15 10:15:23 [ERROR] paper-decision-loop: Broker submit RAISED: order_id=68a8b227... symbol=000880 broker=KoreaInvestmentAdapter — BrokerError: koreainvestment | api_error | KIS order_cash: business error (rt_cd=1, msg_cd=40270000): 모의투자 상/하한가 오류
```

**Full stack trace:**
```
File "order_manager.py:422", submit_order_to_broker → broker.submit_order(request)
File "adapter.py:214", submit_order → self._rest.submit_order(request)
File "rest_client.py:786", submit_order → self._request(...)
File "rest_client.py:641", _raise_on_error → BrokerError: 모의투자 상/하한가 오류
```

**Cause**: The `KIS_SMOKE_PRICE=280500` env var is used as the `requested_price` for ALL symbols in the paper decision loop ([`run_paper_decision_loop.py:537-548`](scripts/run_paper_decision_loop.py:537)). This fixed price of 280500 won won is outside the daily price limit band for symbols whose current market price differs significantly. KIS mock trading API rejects orders where the requested price exceeds the daily upper/lower price limit.

**Affected orders (10:15-10:17 KST cycle):**
| Time | Symbol | Decision | Quantity | Price | Error |
|------|--------|----------|----------|-------|-------|
| 10:15:23 | 000880 | APPROVE | 10 | 280500 | 모의투자 상/하한가 오류 |
| 10:15:45 | 001230 | REDUCE | 10 | 280500 | 모의투자 상/하한가 오류 |

**Note**: `KIS_SMOKE_PRICE=280500` was set for smoke testing and is intentionally a fixed price. The paper decision loop uses this price for all symbols because it's a paper/smoke environment. The KIS mock API enforces real price limits even in the mock environment.

### 6.6 Phase 4c (stale_snapshot_guardrail) — PASSED (no log output)

Phase 4c did NOT output any log messages, which means `freshness.is_stale` was `False`. This confirms:
- Cash snapshots were fresh (last sync at ~10:12 KST, well within 900s threshold)
- Position snapshots were fresh
- The guardrail correctly allowed the pipeline to proceed

This is the **expected behavior** during market hours when snapshot sync is running continuously.

---

## 7. New Logging Effectiveness — CONFIRMED WORKING

### 7.1 Changes Deployed

| Change | File | Status |
|--------|------|--------|
| `_run_command()` stderr → ERROR level | `run_near_real_ops_scheduler.py` | ✅ Deployed (scheduler restarted 10:03 KST) |
| `_parse_snapshot_sync_summary()` | `run_near_real_ops_scheduler.py` | ✅ Deployed |
| Pre-market cash sync validation | `run_near_real_ops_scheduler.py` | ✅ Deployed (but pre-market already passed) |
| Phase 5 symbol/decision_type logging | `decision_orchestrator.py` | ✅ Deployed (host code) |
| Snapshot freshness WARNING log | `decision_orchestrator.py` | ✅ Deployed (host code) |
| Broker submit logging | `order_manager.py` | ✅ Deployed (host code) |
| Submit result INFO log | `run_paper_decision_loop.py` | ✅ Deployed (host code) |
| Cash sync WARNING when cash=0 | `run_snapshot_sync_loop.py` | ✅ Deployed (host code) |

### 7.2 Confirmed Log Outputs

| # | Expected Pattern | Status | Details |
|---|-----------------|--------|---------|
| 1 | `CASH_SYNC_ZERO` warning | ⏳ Not yet (pre-market already passed) | Will appear tomorrow 08:00 KST |
| 2 | `snapshot_sync_summary` metrics | ⏳ Not yet (pre-market already passed) | Will appear tomorrow 08:00 KST |
| 3 | **`Phase 5 FAILED`** with symbol/decision_type | ✅ **Confirmed** | `symbol=000880 decision_type=BUY trade_decision_id=...` |
| 4 | `snapshot.*stale` WARNING | ⏳ Not observed | May appear when snapshots are stale |
| 5 | **`submit_order_to_broker`** INFO log | ✅ **Confirmed** | `order_id=... broker=KoreaInvestmentAdapter symbol=000880 decision_type=BUY quantity=10` |
| 6 | **`Cycle 1 submit result`** INFO log | ✅ **Confirmed** | `status=ERROR error_phase=order_submit error_message=...` |

---

## 8. Answers to Specific Questions (Updated)

### Q1: Pre-market (08:00 KST) cash sync — does it refresh cash snapshots?

**No.** The pre-market snapshot sync at 08:00:02 KST completed in 0.79s with `cash_synced_count=0`. The KIS API does not return cash balance data before market open (09:00 KST). The `_run_pre_market()` function calls `run_snapshot_sync_loop.py --max-cycles 1` which internally calls `sync_kis_account_snapshots()`, but the cash balance endpoint returns empty.

### Q2: When does the first fresh cash snapshot appear?

**09:00:08 KST** — the first intraday snapshot sync after market open. Cash age drops from ~12 hours stale to <1 second fresh at this point.

### Q3: Do APPROVE orders escape `pending_submit`?

**No (still).** After the `logger` fix, orders now progress past Phase 5 and reach the KIS API, but KIS rejects them with `모의투자 상/하한가 오류` (msg_cd=40270000). The orders remain in `pending_submit` because the broker submit raises an exception before the status can be transitioned to `SUBMITTED`.

### Q4: Why are orders stuck in `pending_submit`? (UPDATED — Two Root Causes)

**Root Cause #1 (FIXED)**: `name 'logger' is not defined` in [`order_manager.py`](src/agent_trading/services/order_manager.py). Fixed at 10:13 KST by adding `import logging` and `logger = logging.getLogger(__name__)`.

**Root Cause #2 (NEW)**: `모의투자 상/하한가 오류` (msg_cd=40270000) from KIS mock API. The `KIS_SMOKE_PRICE=280500` env var provides a fixed price that is outside the daily price limit band for symbols 000880 and 001230.

The current sequence is:
1. ✅ Phase 1-4: assemble, size, validate, create_order → all succeed
2. ✅ Phase 4c: stale snapshot guardrail → passes (cash is fresh during market hours)
3. ✅ Phase 5: `submit_order_to_broker()` called → INFO log printed
4. ✅ `logger` fix → `logger.exception()` works correctly now
5. ✅ KIS API called → `POST /uapi/domestic-stock/v1/trading/order-cash` → HTTP 200
6. ❌ KIS returns business error: `모의투자 상/하한가 오류` (rt_cd=1, msg_cd=40270000)
7. ❌ `BrokerError` raised → caught by `assemble_and_submit()` → status=ERROR
8. ❌ Order remains in `pending_submit` (never transitioned to `SUBMITTED`)

### Q5: Are `reason_code` / `reason_detail` populated?

**No.** All 29 `pending_submit` orders have `status_reason_code=NULL` and `status_reason_message=NULL`. The new logging changes add context to log messages but do not populate these DB columns.

---

## 9. Recommendations (Updated)

1. **Immediate (DONE)**: Fix `name 'logger' is not defined` in `order_manager.py`. ✅ Fixed at 10:13 KST. **Verified working** — `NameError` gone, pipeline now reaches KIS API.

2. **Immediate**: Fix `모의투자 상/하한가 오류` (msg_cd=40270000) — the `KIS_SMOKE_PRICE=280500` is outside the daily price limit band for some symbols. Options:
   - Use a per-symbol market price from the cash/position snapshot instead of a fixed smoke price
   - Set `KIS_SMOKE_PRICE` to a value within the daily limit band for all target symbols
   - Implement price validation before submitting to KIS, with automatic adjustment to the nearest valid price

3. **Short-term**: Populate `status_reason_code` and `status_reason_message` on `order_requests` when Phase 5 broker submit fails. Currently these columns are never written.

4. **Medium-term**: Implement a deterministic retry/fallback for cash sync during pre-market. Options:
   - Use previous day's closing cash balance as fallback
   - Skip cash freshness check during pre-market (08:00-09:00 KST)
   - Reduce freshness threshold from 900s to allow overnight cash snapshots

5. **Observability**: Add a health check endpoint that reports cash snapshot age and alerts when cash has been stale for >1 hour during market hours.

---

## 10. Appendix: DB Schema Reference

### `snapshot_sync_runs`
| Column | Type | Description |
|--------|------|-------------|
| `cash_synced_count` | integer | Number of accounts with cash synced |
| `positions_synced_total` | integer | Total positions synced |
| `status` | varchar | `completed`, `partial`, `failed` |
| `trigger_type` | varchar | `scheduler`, `manual` |
| `succeeded_accounts` | integer | Fully succeeded accounts |
| `partial_accounts` | integer | Partially succeeded accounts |
| `failed_accounts` | integer | Failed accounts |

### `order_requests` (relevant columns)
| Column | Type | Description |
|--------|------|-------------|
| `status` | varchar | `pending_submit`, `submitted`, etc. |
| `status_reason_code` | varchar | **Always NULL** — not populated |
| `status_reason_message` | text | **Always NULL** — not populated |
| `trade_decision_id` | uuid | FK to `trade_decisions` |

### `trade_decisions` (relevant columns)
| Column | Type | Description |
|--------|------|-------------|
| `decision_type` | varchar | `approve`, `hold`, `reduce` |
| `decision` | varchar | **Always NULL** — not populated |
| `symbol` | varchar | Trading symbol |
| `side` | varchar | `buy`, `sell` |
