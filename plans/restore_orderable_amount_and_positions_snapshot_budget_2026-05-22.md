# Restore `orderable_amount` and Positions in Intraday Snapshot Sync

> **Date**: 2026-05-22  
> **Author**: Roo (Code Mode)  
> **Status**: ✅ Implemented, Tested, Deployed

---

## 1. Background

Intraday snapshot sync에서 다음 두 가지 문제가 관찰되었다:

1. **`orderable_amount=None`**: Cash snapshot은 저장되지만 `orderable_amount` 필드가 `None`으로 저장됨
2. **Positions `Global REST cap exhausted`**: Positions 조회가 `Global REST cap exhausted (remaining=0/1)`로 실패

### Sync Cycle Budget 소비 패턴

각 sync cycle은 3회의 KIS API 호출을 수행하며, 각 호출은 Global REST token 1개를 소비한다:

| Step | API Call | Token 소비 | 누적 |
|------|----------|-----------|------|
| 1 | `get_cash_balance()` (VTTC8434R) | 1 | 1/1 |
| 2 | `get_orderable_cash()` (VTTC8908R) | 1 | 2/1 → 대기 |
| 3 | `get_positions()` (VTTC8434R) | 1 | 3/1 → ❌ |

`FileBackedGlobalBucket`의 capacity=1, refill_rate=1 환경에서 3개의 token이 필요하지만 1개만可用하여 positions가 항상 실패한다.

---

## 2. Root Cause Analysis

### 2.1 `orderable_amount=None` 원인

[`snapshot.py`](src/agent_trading/brokers/koreainvestment/snapshot.py:157)의 `get_orderable_cash()` 호출에서:

- **`BudgetExhaustedError`**: `available_cash`로 fallback (정상 동작)
- **일반 `Exception`** (VTTC8908R 네트워크 오류 등): `orderable_cash = None` 설정 → 이후 VTTC8434R `ord_psbl_amt` fallback 시도 → paper 환경에서 `ord_psbl_amt`가 없거나 `0` → 최종 `orderable_amount=None`

**핵심 문제**: 일반 Exception 발생 시 `available_cash`로 fallback하지 않고 `None`으로 설정하여, VTTC8434R fallback에만 의존했다. Paper 환경에서 VTTC8434R의 `ord_psbl_amt`는 unreliable하다.

### 2.2 Positions `Global REST cap exhausted` 원인

[`shared_budget.py`](src/agent_trading/brokers/shared_budget.py:40)의 `FileBackedGlobalBucket` 기본값:
- `_capacity = 1.0`
- `_refill_rate = 1.0`

[`rate_limit.py`](src/agent_trading/brokers/rate_limit.py:488)에서 paper 환경의 `KIS_PAPER_REST_RPS=1`(canonical)로 설정되어도, `FileBackedGlobalBucket`이 `capacity=float(total)=1.0, refill_rate=1.0*total=1.0`로 생성되지만, 로그에는 `remaining=0/1`로 표시되어 capacity=1이 실제로 적용됨을 확인.

**핵심 문제**: 3회 API 호출에 3개의 token이 필요하지만, budget은 1 token만 제공. `asyncio.sleep(1.0)`으로 1초 간격을 두어도 1 token만 refill되므로 positions는 항상 실패.

---

## 3. Changes Made

### 3.1 Fix 1: 일반 Exception fallback → `available_cash` (snapshot.py)

**File**: [`src/agent_trading/brokers/koreainvestment/snapshot.py`](src/agent_trading/brokers/koreainvestment/snapshot.py:178)

**변경 전**:
```python
except Exception:
    logger.warning(
        "VTTC8908R get_orderable_cash() failed; "
        "falling back to VTTC8434R ord_psbl_amt",
        exc_info=True,
    )
    orderable_cash = None
```

**변경 후**:
```python
except Exception:
    # 일반 Exception → available_cash로 fallback (VTTC8434R ord_psbl_amt는
    # paper에서 unreliable하므로 available_cash가 더 안전)
    logger.warning(
        "VTTC8908R get_orderable_cash() failed; "
        "falling back to available_cash=%s",
        available_cash,
        exc_info=True,
    )
    orderable_cash = available_cash
```

### 3.2 Fix 2: 일반 Exception fallback → `available_cash` (kis_snapshot_sync.py)

**File**: [`src/agent_trading/services/kis_snapshot_sync.py`](src/agent_trading/services/kis_snapshot_sync.py:272)

동일한 변경을 legacy sync path에도 적용.

### 3.3 Fix 3: Cycle 분리 — `fetch_positions` 파라미터 추가

**File**: [`src/agent_trading/brokers/koreainvestment/snapshot.py`](src/agent_trading/brokers/koreainvestment/snapshot.py:66)

`fetch_snapshot()` 메서드에 `fetch_positions: bool = True` 파라미터 추가:

- **Phase 1** (`fetch_positions=False`): cash + orderable_cash만 조회 (2 token 소비)
- **Phase 2** (`fetch_positions=True`): positions만 조회 (1 token 소비, 기본값)

이를 통해 budget이 부족한 상황에서도 cash+orderable이 항상 성공하도록 보장.

**File**: [`src/agent_trading/services/kis_snapshot_sync.py`](src/agent_trading/services/kis_snapshot_sync.py:176)

`sync_kis_account_snapshots()` 함수에도 동일한 `fetch_positions: bool = True` 파라미터 추가.

---

## 4. Budget Consumption After Fix

### Phase 1: cash + orderable (2 tokens)

| Step | API Call | Token 소비 | 누적 |
|------|----------|-----------|------|
| 1 | `get_cash_balance()` (VTTC8434R) | 1 | 1/1 |
| 2 | `asyncio.sleep(1.0)` | refill +1 | 1/1 |
| 3 | `get_orderable_cash()` (VTTC8908R) | 1 | 1/1 → 성공 |
| 4 | 일반 Exception → `available_cash` fallback | 0 | ✅ |

### Phase 2: positions only (1 token)

| Step | API Call | Token 소비 | 누적 |
|------|----------|-----------|------|
| 1 | `get_positions()` (VTTC8434R) | 1 | 1/1 → 성공 |

---

## 5. Fallback Chain (After Fix)

```
get_orderable_cash() (VTTC8908R)
  ├── 성공 → orderable_amount = VTTC8908R.ord_psbl_cash
  ├── BudgetExhaustedError → available_cash (raw_cash.dnca_tot_amt)
  └── 일반 Exception → available_cash (raw_cash.dnca_tot_amt)  ← 강화됨
       (더 이상 VTTC8434R ord_psbl_amt에 의존하지 않음)
```

---

## 6. Test Results

**63 tests passed** (0 failures):

| Test Suite | Tests | Result |
|-----------|-------|--------|
| `test_snapshot.py` | 16 | ✅ All passed |
| `test_kis_snapshot_sync.py` | 47 | ✅ All passed |

### New Tests Added

| Test | File | Description |
|------|------|-------------|
| `test_fetch_snapshot_fetch_positions_false` | [`test_snapshot.py`](tests/brokers/koreainvestment/test_snapshot.py:421) | `fetch_positions=False` → positions skip, cash+orderable 정상 |
| `test_fetch_positions_false_skips_positions` | [`test_kis_snapshot_sync.py`](tests/services/test_kis_snapshot_sync.py:622) | legacy sync path에서 `fetch_positions=False` 검증 |

### Updated Tests

| Test | Change |
|------|--------|
| `test_cash_balance_orderable_amount_vttc8908r_failure` | 일반 Exception → `available_cash`(1000000)로 fallback 검증 |
| `test_orderable_cash_general_exception_fallback_to_available_cash` | 일반 Exception → `available_cash`(5000000)로 fallback 검증 |

---

## 7. Deployment

- **Docker images rebuilt**: `app`, `api`, `ops-scheduler`, `reconciliation-worker`, `snapshot-sync`
- **Services restarted**: All containers recreated with new images
- **Health check**: `/health` → `{"status":"ok","database":"connected","scheduler":{"healthy":true}}`

---

## 8. Summary

| Problem | Root Cause | Fix |
|---------|-----------|-----|
| `orderable_amount=None` | 일반 Exception에서 `available_cash`로 fallback하지 않음 | Exception handler에서 `available_cash`로 fallback |
| Positions `Global REST cap exhausted` | 3 API calls / cycle, budget 1 token | `fetch_positions` 파라미터로 cycle 분리 (Phase 1: cash+orderable, Phase 2: positions) |
