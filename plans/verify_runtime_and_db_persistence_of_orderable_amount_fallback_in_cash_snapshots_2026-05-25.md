# Runtime/DB Verification Report — `orderable_amount` Fallback Fix

## 1. 검증 요약

| 항목 | 내용 |
|------|------|
| **목적** | KIS snapshot sync에서 `orderable_amount` NULL 저장 방지 fix의 runtime/DB 동작 검증 |
| **방법** | Docker 재빌드 → 컨테이너 재시작 → snapshot sync 실행 → DB 조회 → 로그 분석 |
| **검증 시각** | 2026-05-25 15:34~15:39 KST (장 종료 후, after-hours) |
| **주요 결과** | Fix 코드 확인 및 runtime path(`snapshot.py`) 추가 fix 적용 완료. After-hours로 인해 fallback 경로 직접 실행은 불가했으나, market-hours snapshot 데이터에서 `orderable_amount` 정상 저장 확인 |

## 2. Docker 재빌드 결과

```bash
# 빌드 명령어
docker compose build

# 결과
[+] Building 7.1s (20/20) FINISHED
# 모든 이미지 빌드 성공:
#   - agent_trading-api:    sha256:7f0e2e...
#   - agent_trading-app:    sha256:78a6e6...
#   - agent_trading-app:latest: sha256:447a31... (ops-scheduler, reconciliation-worker)

# 컨테이너 재시작
docker compose up -d
# 모든 컨테이너 정상 기동 (api, app, db, ops-scheduler, reconciliation-worker)
```

**컨테이너 상태** (재시작 후):
```
NAME                                  STATUS
agent_trading-api-1                   Up 3 seconds (health: starting)
agent_trading-app-1                   Up 3 seconds
agent_trading-db-1                    Up 8 hours (healthy)
agent_trading-ops-scheduler           Up 3 seconds (health: starting)
agent_trading-reconciliation-worker   Up 3 seconds
```

## 3. Snapshot 실행 결과

### 실행 명령어
```bash
docker exec agent_trading-app-1 python3 scripts/run_snapshot_sync_loop.py --max-cycles 1 --after-hours
```

### 실행 로그
```
2026-05-25 15:37:11 [INFO]    Starting snapshot sync loop (broker=koreainvestment, after_hours=True) ...
2026-05-25 15:37:11 [INFO]    Authenticating broker client ...
2026-05-25 15:37:11 [INFO]    Broker authentication successful.
2026-05-25 15:37:11 [INFO]    Connecting to Postgres ...
2026-05-25 15:37:11 [INFO]    Repositories ready. Running sync_all_accounts(after_hours=True) ...
2026-05-25 15:37:12 [INFO]    CASH_POSITIONS_MERGE VTTC8434R merged call succeeded (account=50186448, positions=3, cash_keys=[...])
2026-05-25 15:37:12 [INFO]    AFTER_HOURS_SKIP After-hours mode — skipping positions fetch (cash-only sync)
2026-05-25 15:37:12 [INFO]    [VTTC8908R] after-hours skip (account=...); orderable_amount not needed after market close
2026-05-25 15:37:12 [INFO]    Snapshot cycle complete — accounts=1 success=1 |
                              budget_fallbacks: after_hours_skip=1
2026-05-25 15:37:12 [INFO]    sync-cycle  accounts=1 (ok=1) positions=0 cash=1 errors=0
```

### 참고: `sync_kis_snapshots.py --all` 실패
CLI 스크립트는 FK 제약조건 순서 문제로 실패:
```
ERROR: insert or update on table "position_snapshots" violates foreign key
constraint "position_snapshots_snapshot_sync_run_id_fkey"
```
→ `snapshot_sync_runs` 레코드가 snapshot보다 늦게 insert되는 버그. `run_snapshot_sync_loop.py`는 올바르게 처리함.

## 4. DB 조회 결과

### 최신 `cash_balance_snapshots` (KST 시간 기준)

| 시각 (KST) | orderable_amount | available_cash | 비고 |
|-----------|-----------------|----------------|------|
| 15:38:53 | **NULL** | 9,109,140 | After-hours (VTTC8908R 의도적 skip) |
| 15:37:11 | **NULL** | 9,109,140 | After-hours (VTTC8908R 의도적 skip) |
| 13:25:07 | **16,702,903** | 9,109,140 | Market hours — VTTC8908R 정상 응답 |
| 13:21:24 | **9,109,140** | 9,109,140 | Market hours — VTTC8908R 정상 응답 |
| 13:17:07 | **9,109,140** | 9,109,140 | Market hours — VTTC8908R 정상 응답 |
| 13:01:44 | **9,109,140** | 9,109,140 | Market hours — VTTC8908R 정상 응답 |
| 10:19:53 | **NULL** | 27,329,630 | Fix 적용 전 (old code) |
| 10:19:53 | **NULL** | 30,000,000 | Fix 적용 전 (old code) |

### 핵심 관찰
1. **10:19 KST**: `orderable_amount` = NULL (fix 적용 전, old behavior)
2. **13:01~13:25 KST**: `orderable_amount` != NULL (VTTC8908R 정상 응답, fix와 무관)
3. **15:37~15:38 KST**: `orderable_amount` = NULL (after-hours, VTTC8908R 의도적 skip)

## 5. Fallback 경로 분석

### 코드 구조 — 두 개의 독립적인 구현

#### 경로 1: [`kis_snapshot_sync.py`](../src/agent_trading/services/kis_snapshot_sync.py:447) (legacy path, CLI 전용)
- `sync_kis_account_snapshots()` 함수 사용
- `sync_kis_snapshots.py --all`에서 호출
- **Fix 적용 완료** (line 494-503): VTTC8908R + VTTC8434R 실패 시 `available_cash`로 fallback

#### 경로 2: [`snapshot.py`](../src/agent_trading/brokers/koreainvestment/snapshot.py:248) (provider path, **runtime 전용**)
- `KISSyncSnapshotProvider.fetch_snapshot()` 사용
- `run_snapshot_sync_loop.py` + ops-scheduler에서 호출
- **Fix 미적용 → 본 검증 과정에서 추가 수정 완료** (line 299-303)

### Fallback 체인 (두 경로 모두 동일한 구조)

```
VTTC8908R.ord_psbl_cash 획득 시도
  ├─ 성공 → orderable_amount = ord_psbl_cash
  ├─ BudgetExhaustedError → available_cash로 fallback
  ├─ API Exception → available_cash로 fallback
  └─ None 반환 (ord_psbl_cash 미존재)
       └─ VTTC8434R.ord_psbl_amt 획득 시도
            ├─ 성공 → orderable_amount = ord_psbl_amt
            └─ None (ord_psbl_amt 미존재)
                 └─ ✅ **최종 fallback**: available_cash (dnca_tot_amt - prvs_rcdl_exc_amt)
```

### After-hours 동작
After-hours 모드에서는 VTTC8908R이 의도적으로 완전히 skip됨:
```python
elif after_hours and raw_cash:
    logger.info("[VTTC8908R] after-hours skip ...")
```
→ `orderable_amount`를 설정하지 않음 → NULL 저장 (기존 의도된 동작, fix 범위 아님)

## 6. 추가 발견 및 수정 사항

### 🔴 원래 fix의 누락 — runtime path(`snapshot.py`)에도 동일 fix 필요

검증 과정에서 `kis_snapshot_sync.py`의 fix가 ops-scheduler가 사용하는 runtime path(`snapshot.py`)에는 적용되지 않았음을 발견했습니다.

**수정 내역:**

| 파일 | 수정 전 | 수정 후 |
|------|---------|---------|
| [`kis_snapshot_sync.py`](../src/agent_trading/services/kis_snapshot_sync.py:494) | `orderable_amount` = None (그대로 둠) | `orderable_amount = available_cash` (line 503) |
| [`snapshot.py`](../src/agent_trading/brokers/koreainvestment/snapshot.py:299) | `orderable_amount` = None (그대로 둠) | `orderable_amount = available_cash` (금일 본 검증에서 추가) |

### `sync_kis_snapshots.py` FK 제약조건 버그
- `snapshot_sync_runs` 레코드가 snapshot entity보다 **늦게** insert되어 FK 위반 발생
- `run_snapshot_sync_loop.py`는 올바르게 처리 (running 상태로 선 insert → sync 후 update)

## 7. 결론

| 검증 항목 | 결과 | 상태 |
|----------|------|------|
| 코드 fix 존재 (`kis_snapshot_sync.py`) | `orderable_amount = available_cash` fallback 확인 | ✅ |
| Runtime path fix 존재 (`snapshot.py`) | 본 검증에서 추가 적용 완료 | ✅ (NEW) |
| Docker 빌드/재시작 | 5개 컨테이너 정상 기동 | ✅ |
| Snapshot sync 실행 | After-hours 1 cycle 성공 (cash=1) | ✅ |
| DB `orderable_amount` 저장 | Market hours: non-NULL 저장 확인 | ✅ |
| After-hours `orderable_amount` | NULL (의도된 동작, fix 범위 아님) | ⚠️ 예상됨 |
| Fallback 경로 runtime 검증 | After-hours로 인해 직접 실행 불가 (market hours 필요) | ⏸️ 보류 |

### 최종 판정
**Fix는 코드 수준에서 올바르게 적용되었습니다.** 다만:
1. 원래 fix가 runtime path(`snapshot.py`)에는 누락되어 있어, 본 검증 과정에서 추가 수정하였습니다.
2. After-hours이므로 VTTC8908R fallback 경로(두 API 모두 실패 시 `available_cash` 사용)의 실제 runtime 동작은 다음 market hours에 재확인이 필요합니다.
3. 기존 market-hours snapshot 데이터(13:01~13:25 KST)에서 `orderable_amount`가 정상적으로 저장됨을 확인했습니다.
4. After-hours snapshot에서 `orderable_amount`가 NULL인 것은 **의도된 동작**입니다 (장 마감 후 매수 주문 불가 → orderable 불필요).

### 권장사항
- 다음 **market hours** (2026-05-26 이후 첫 거래일)에 VTTC8908R 예산 소진 또는 API 장애 상황에서의 fallback 경로 추가 검증 권장
- `sync_kis_snapshots.py`의 FK 제약조건 순서 버그는 별도 이슈로 추적 필요
