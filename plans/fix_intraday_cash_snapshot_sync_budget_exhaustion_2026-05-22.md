# 장중 Snapshot Sync Budget Exhaustion 복구 보고서

## 1. Root Cause

### 문제 증상 (2026-05-21 08:50:04 KST)
- ops-scheduler가 `snapshot_sync` 시작
- `get_positions()` 호출 → inquiry bucket 소모 (remaining=0/1)
- `get_cash_balance()` 호출 → **BudgetExhaustedError** (remaining=0/1)
- 결과: `cash=0`, `CASH_SYNC_ZERO`, stale cash guardrail로 submit 차단

### 근본 원인

[`fetch_snapshot()`](src/agent_trading/brokers/koreainvestment/snapshot.py:64)과 [`sync_kis_account_snapshots()`](src/agent_trading/services/kis_snapshot_sync.py:176) 모두 **positions → cash_balance → orderable_cash** 순서로 3회의 INQUIRY bucket을 소모.

**Paper 환경 budget 설정** ([`rate_limit.py`](src/agent_trading/brokers/rate_limit.py:487-505)):
| Bucket | Capacity | Refill Rate | 비고 |
|--------|----------|-------------|------|
| inquiry | 1 | 0.5/sec (2초에 1토큰) | |
| global_rest | 1 | 1.0/sec | |
| order | 1 | 0.1/sec | |
| auth | 1 | 0.017/sec (≈1분에 1토큰) | |

`KIS_PAPER_REST_RPS=1` ([`docker-compose.yml`](docker-compose.yml:65)) 기준:
- `inquiry_capacity=1` → **burst 1회만 허용**
- `inquiry_refill_rate=0.5` → **2초에 1토큰 회복**
- 첫 번째 `get_positions()`에서 유일한 inquiry token 소진
- 이후 `get_cash_balance()`는 BudgetExhaustedError 발생

### 영향
- cash_balance_snapshots 테이블에 오늘 날짜 row 없음
- stale cash guardrail이 submit 차단
- positions는 성공했지만 cash=0으로 기록되어 CASH_SYNC_ZERO 트리거

---

## 2. 적용한 구조 변경

### P0 — Cash 조회 우선 순서 변경

**변경 전** (두 파일 모두 동일):
```
1. get_positions()     → INQUIRY bucket 소모
2. get_cash_balance()  → INQUIRY bucket 소모 → BudgetExhaustedError
3. get_orderable_cash()→ INQUIRY bucket 소모 (실행되지 않음)
```

**변경 후**:
```
1. get_cash_balance()  → INQUIRY bucket 소모 (우선)
2. get_orderable_cash()→ INQUIRY bucket 소모 (fallback 처리)
3. get_positions()     → INQUIRY bucket 소모 (마지막)
```

**근거**: submit에 cash/orderable_amount가 positions보다 중요. positions 실패해도 기존 position_snapshot 유지 가능.

### P1 — orderable_cash BudgetExhaustedError fallback

**변경 전**: `get_orderable_cash()` 실패 시 `except Exception`으로만 처리 → `orderable_cash = None`

**변경 후**:
```python
try:
    orderable_cash = await self._rest.get_orderable_cash(...)
except BudgetExhaustedError:
    # Budget 소진 → raw_cash(available_cash)로 fallback (CASH_SYNC_ZERO 방지)
    orderable_cash = available_cash
except Exception:
    # 일반 예외 → 기존처럼 VTTC8434R ord_psbl_amt fallback
    orderable_cash = None
```

### P1 — BudgetExhaustedError 명시적 처리

**변경 전**: 모든 KIS API 호출이 `except Exception`으로 처리 → BudgetExhaustedError도 Exception으로 catch되어 구분 불가

**변경 후**: `BudgetExhaustedError`를 `except Exception`보다 먼저 catch하여 budget exhaustion 상황을 명확히 로깅

### 수정된 파일

| 파일 | 변경 내용 |
|------|----------|
| [`snapshot.py`](src/agent_trading/brokers/koreainvestment/snapshot.py) | `fetch_snapshot()`: cash 우선 조회, BudgetExhaustedError 명시적 처리, orderable_cash fallback |
| [`kis_snapshot_sync.py`](src/agent_trading/services/kis_snapshot_sync.py) | `sync_kis_account_snapshots()`: 동일한 구조 변경 |

---

## 3. 테스트 결과

### 기존 테스트 (회귀 테스트)
```
tests/brokers/koreainvestment/test_snapshot.py ............ 15 passed
tests/services/test_kis_snapshot_sync.py ................. 46 passed
```

### 신규 테스트 케이스 (4개)

| 테스트 | 설명 | 결과 |
|--------|------|------|
| `test_cash_balance_budget_exhausted_cash_not_saved` | cash 조회 BudgetExhaustedError → cash 미저장, errors 기록 | ✅ |
| `test_orderable_cash_budget_exhausted_fallback_to_raw_cash` | orderable_cash BudgetExhaustedError → available_cash로 fallback 저장 | ✅ |
| `test_positions_budget_exhausted_cash_still_saved` | positions BudgetExhaustedError → cash는 정상 저장 (cash 우선) | ✅ |
| `test_orderable_cash_general_exception_fallback_to_ord_psbl_amt` | orderable_cash 일반 예외 → VTTC8434R ord_psbl_amt fallback | ✅ |

---

## 4. 운영 검증 결과

### 확인된 사항
- ✅ 코드 수정 완료 (snapshot.py + kis_snapshot_sync.py)
- ✅ 모든 기존 테스트 통과 (61개)
- ✅ 신규 budget exhaustion 복구 테스트 4개 통과
- ✅ BudgetExhaustedError 명시적 처리 추가
- ✅ orderable_cash fallback 로직 개선

### 내일(2026-05-22) 장중 확인 필요 항목

1. **cash_balance_snapshots 테이블 확인**
   ```sql
   SELECT COUNT(*) FROM cash_balance_snapshots WHERE snapshot_at::date = CURRENT_DATE;
   ```
   - 예상: 0 (오늘은 이미 장 마감)
   - 내일 장중: 1 이상 (cash snapshot 정상 생성)

2. **ops-scheduler 로그 확인**
   - `08:50:04` snapshot_sync 로그에서 `BudgetExhaustedError` 없이 cash 조회 성공 확인
   - orderable_cash fallback 로그 확인 (필요시)

3. **CASH_SYNC_ZERO guardrail 해소 확인**
   - cash > 0으로 저장되어 stale cash guardrail이 submit을 차단하지 않는지 확인

4. **Docker 재빌드/재기동** (코드 배포 후)
   ```bash
   docker compose build app
   docker compose up -d
   curl http://localhost:8000/health/readyz
   ```

---

## 5. 전/후 로그 비교 (시뮬레이션)

### 변경 전 (문제 발생 시점)
```
08:50:04 [snapshot_sync] Starting snapshot sync
08:50:04 [KIS] get_positions() → INQUIRY consume (remaining=0/1)
08:50:05 [KIS] get_cash_balance() → BudgetExhaustedError: [inquiry] exhausted (remaining=0/1)
08:50:05 [snapshot_sync] cash=0 → CASH_SYNC_ZERO → submit blocked
```

### 변경 후 (예상)
```
08:50:04 [snapshot_sync] Starting snapshot sync
08:50:04 [KIS] get_cash_balance() → INQUIRY consume (remaining=0/1) → SUCCESS
08:50:05 [KIS] get_orderable_cash() → BudgetExhaustedError → fallback to raw_cash=5000000
08:50:05 [snapshot_sync] cash=5000000 saved → CASH_SYNC_ZERO 방지
08:50:06 [KIS] get_positions() → INQUIRY consume (refilled) → SUCCESS
```

---

## 6. 추가 권장 사항

### P2 — Paper inquiry budget 조정 검토
현재 `inquiry_capacity=1`은 너무 빡빡함. 최소 `inquiry_capacity=3`으로 올려서 한 cycle 내 3회 호출을 허용하는 것이 안전.

[`rate_limit.py`](src/agent_trading/brokers/rate_limit.py:497-498):
```python
# 현재
inquiry_capacity=max(1, int(total * 1)),       # total=1 → capacity=1
inquiry_refill_rate=0.5 * total,                # 0.5/sec
# 제안
inquiry_capacity=max(3, int(total * 3)),        # total=1 → capacity=3
inquiry_refill_rate=1.0 * total,                # 1.0/sec
```

단, `.env` 수정 금지 제약으로 인해 이 변경은 별도 논의 필요.

### P3 — Snapshot sync 전용 budget bucket 검토
snapshot sync가 inquiry bucket을 공유하면서 일반 order/inquiry와 경합. snapshot sync 전용 bucket을 분리하면 문제 근본 해결 가능.
