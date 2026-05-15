# Cash Snapshot Freshness Gap Analysis — 2026-05-15

> **관측일**: 2026-05-15 (금) 17:51 KST  
> **목적**: AccountsView 상단 금액(총자산/현금잔고/미실현손익)이 최신 포지션과 불일치하는 원인 규명  
> **범위**: 관측/분석만 — 코드 수정 불가

---

## 1. 대상 계좌

| 항목 | 값 |
|------|-----|
| account_id | `a44a02d1-7f32-5a62-99f7-235abeb58284` |
| account_alias | `Entrypoint Paper` |
| environment | `paper` |
| status | `active` |
| KIS account_ref | 설정 파일 참조 |

---

## 2. Position vs Cash Snapshot 시각 비교

### 2.1 최신 position snapshot

| snapshot_at (UTC) | snapshot_at (KST) | instrument_id | quantity | market_price | unrealized_pnl |
|-------------------|-------------------|---------------|----------|-------------|----------------|
| 2026-05-15 08:43:45 | **17:43 KST** | 000880 | 10 | 141,400 | -40,000 |
| 2026-05-15 08:43:45 | **17:43 KST** | (기타) | 10 | 270,500 | +35,000 |

→ **Position snapshots는 장 마감 후에도 5분 간격으로 정상 갱신 중**

### 2.2 최신 cash snapshot

| snapshot_at (UTC) | snapshot_at (KST) | available_cash | settled_cash | total_asset | settlement_amount | total_unrealized_pnl |
|-------------------|-------------------|----------------|-------------|-------------|-------------------|---------------------|
| 2026-05-15 06:31:10 | **15:31 KST** | 27,329,630 | 27,329,630 | NULL | NULL | NULL |

→ **마지막 cash snapshot: 15:31 KST (EOD 직후)**  
→ **2h 12m 갭** (cash 마지막 갱신 ~ 현재)

### 2.3 Cash snapshot 통계

| 지표 | 값 |
|------|-----|
| 총 row 수 | 328 |
| EOD 윈도우 row 수 (15:30-15:35 KST) | 1 |
| Post-EOD row 수 (15:35 KST 이후) | **0** |
| total_asset NOT NULL | **0** (전부 NULL) |
| settlement_amount NOT NULL | **0** (전부 NULL) |
| total_unrealized_pnl NOT NULL | **0** (전부 NULL) |
| settled_cash NOT NULL | 328 (모든 row) |
| source_of_truth | 전부 `broker` |

---

## 3. Snapshot Sync Run 현황

최근 20개 `snapshot_sync_runs` (최신순):

| 항목 | 모든 20개 run |
|------|--------------|
| status | `partial` |
| cash_synced_count | **0** |
| error_count | **0** |
| positions_synced_total | 2 |
| succeeded_accounts | 0 |
| partial_accounts | 1 |

→ **모든 snapshot sync run이 cash_synced_count=0으로 기록됨**

---

## 4. Log 분석 결과

### 4.1 로그 패턴 출처 확인

로그 `accounts=1 positions=2 cash=1 errors=0` 형식은 [`scripts/run_snapshot_sync_loop.py`](/workspace/agent_trading/scripts/run_snapshot_sync_loop.py:117)의 [`_log_sync_summary()`](/workspace/agent_trading/scripts/run_snapshot_sync_loop.py:104)에서 출력됨:

```python
logger.info(
    "sync-cycle  "
    "accounts=%d (ok=%d partial=%d fail=%d skip=%d)  "
    "positions=%d (skipped=%d)  "
    "cash=%d  "
    "errors=%d",
    total, succeeded, partial, failed, skipped,
    positions_synced, positions_skipped,
    cash_synced,     # <-- batch.total_cash_synced
    len(errors),
)
```

`cash_synced`는 `BatchSyncResult.total_cash_synced`이며, 이 값은 [`sync_account_snapshots()`](/workspace/agent_trading/services/snapshot_sync.py:187)에서 `result.cash_balance_synced=True` 시 [`sync_all_accounts()`](/workspace/agent_trading/services/snapshot_sync.py:254)에서 increment됨.

### 4.2 장중 Cash Sync 타임라인

| 시간 (KST) | 단계 | cash= | 비고 |
|-----------|------|-------|------|
| 08:00-08:50 | Pre-market | 1 | 정상 sync |
| 09:00-09:55 | Market | 1 | 5min cycle cash=1 |
| 10:03-10:49 | Market | **FAIL** | `authenticate()` 7회 연속 실패 |
| 10:50 이후 | Market | 1 | 복구 후 정상 |
| 13:27-14:52 | Market | 1 | 정상 |
| 14:57-15:03 | Market | **FAIL** | `authenticate()` 재실패 |
| 15:08-15:25 | Market | 1 | 정상 |
| 15:31:10 | **EOD** | 1 | **마지막 cash snapshot 생성** |
| 15:31 이후 | Post-EOD | - | cash snapshot 0개 (확인 완료) |

### 4.3 CRITICAL: Log `cash=1` vs DB `cash_synced_count=0` 불일치

| 출처 | 값 | 근거 |
|------|-----|------|
| near_real_scheduler log | `cash=1` | ops scheduler가 snapshot sync subprocess stdout에서 파싱 |
| snapshot_sync_runs.cash_synced_count | **0** | 직접 DB 조회 결과 (최근 20개 전부) |
| cash_balance_snapshots | **328 rows 존재** | DB에 cash snapshot은 존재함 |

**이것이 이 분석의 핵심 발견이다.**

로그와 DB가 일치한다면 20번의 run 각각에서 `cash=1`이므로 `cash_synced_count`는 20에 가까워야 한다. 하지만 실제로는 **전부 0**이다.

#### 가능한 원인

| # | 가설 | 설명 | 가능성 |
|---|------|------|--------|
| 1 | **Counter bug** | `batch._incr("total_cash_synced")`가 의도한 대로 동작하지 않거나, 별도의 `batch` 인스턴스가 사용됨 | 중 |
| 2 | **다른 코드 경로** | 로그상 `cash=1`은 별도 프로세스(post-submit sync 등)에서 출력된 것 | 중 |
| 3 | **Transaction 분리** | Subprocess는 cash sync 성공 후 log를 출력하지만, `snapshot_sync_runs` persist가 다른 transaction에서 실패 | 저 |
| 4 | **KIS API empty response** | `get_cash_balance()`가 성공했지만 빈 dict `{}` 반환 → `if raw_cash:`가 False → cash entity 미생성 | 저 (로그상 cash=1) |

---

## 5. 데이터 흐름 분석

### 5.1 정상 경로 (Broker-agnostic, snapshot_sync.py)

```
KISSyncSnapshotProvider.fetch_snapshot()
  ↓ KISRestClient.get_cash_balance() → dict
  ↓ if raw_cash: → CashBalanceSnapshotEntity 생성
  ↓ return FetchedSnapshot(cash_balance=entity)

sync_account_snapshots()
  ↓ cash = fetched.cash_balance
  ↓ if cash is not None:
  ↓   cash_balance_snapshot_repo.add(cash)
  ↓   result._set("cash_balance_synced", True)   ← 여기서 True

sync_all_accounts()
  ↓ if result.cash_balance_synced:
  ↓   batch._incr("total_cash_synced")            ← 여기서 +1

build_sync_run_entity()
  ↓ cash_synced_count = batch.total_cash_synced   ← DB에 저장

_log_sync_summary()
  ↓ logger.info("cash=%d", cash_synced)           ← 로그 출력
```

### 5.2 KIS-specific 경로 (kis_snapshot_sync.py)

```
sync_kis_account_snapshots()
  ↓ rest_client.get_cash_balance() → dict
  ↓ if raw_cash: → entity 생성
  ↓   cash_balance_snapshot_repo.add(entity)
  ↓   result._set("cash_balance_synced", True)
```

두 경로 모두 동일한 `SyncResult.cash_balance_synced`를 사용하므로 동작 방식은 동일하다.

---

## 6. KIS output2 필드 NULL 현황

Migration [`0012_add_kis_output2_fields.sql`](/workspace/agent_trading/db/migrations/0012_add_kis_output2_fields.sql)은 nullable 컬럼을 ADD했을 뿐이다. 따라서 **모든 기존 row의 total_asset, settlement_amount, total_unrealized_pnl은 NULL**이다.

이는 예상된 동작이다:
- 신규 migration (nullable + additive)은 **과거 데이터를 backfill하지 않음**
- KIS output2 필드는 migration 적용 **이후** 생성되는 snapshot부터 채워짐
- 현재 DB의 328개 row는 전부 migration 적용 전 데이터

**즉, AccountsView가 KIS 필드를 사용하지 못하고 fallback 계산값을 사용하는 것은 migration 적용 시점의 자연스러운 결과**이며 별도 버그가 아니다.

---

## 7. 종합 분석

### 7.1 핵심 질문: "왜 포지션 스냅샷은 최신인데 cash snapshot은 장 종료 직후 값에 머무는가?"

**직접적 원인: Cash snapshot이 15:31 KST(EOD) 이후 생성되지 않음**

| 항목 | 상태 |
|------|------|
| Position snapshot 최신 | ✅ 17:43 KST (5분 간격 갱신 중) |
| Cash snapshot 최신 | ❌ 15:31 KST (EOD 이후 갱신 없음) |
| Gap | **2h 12m** |

**1차 가설: EOD 이후 cash API가 빈 응답 반환**

Near-real scheduler는 post-EOD 단계에서 `_run_end_of_day()` 이후에도 `_run_intraday_due_tasks()`를 통해 snapshot sync를 계속 실행한다. 만약 KIS paper API가 장 종료 후 (15:30 KST 이후) `get_cash_balance()`에 대해 빈 dict `{}`를 반환한다면:

- [`KISSyncSnapshotProvider.fetch_snapshot()`](/workspace/agent_trading/brokers/koreainvestment/snapshot.py:150): `if raw_cash:` → `{}`는 falsy → cash entity 미생성
- 동시에 position API는 계속 유효한 데이터 반환 → position snapshot은 계속 갱신
- `cash_balance_synced`는 `False`로 유지 → log의 `total_cash_synced` 증가 없음

**그러나 로그상 `cash=1`이 지속적으로 관측되었으므로 이 가설과 모순된다.**

**2차 가설: Log `cash=1`과 DB `cash_synced_count=0`의 불일치가 핵심**

두 값이 서로 다른 정보를 나타낼 가능성:
- `cash=1` 로그는 `batch.total_cash_synced`에서 왔으며, 이는 `result.cash_balance_synced`가 `True`일 때만 증가
- `cash_synced_count=0`은 `snapshot_sync_runs` 테이블의 DB 값
- `cash_balance_snapshots` 테이블에 328개 row가 존재하는 것은 cash API가 **과거에는** 정상 응답했음을 증명

가장 유력한 설명 중 하나: **near-real ops scheduler가 파싱한 `cash=1` 로그가 snapshot_sync_runs 테이블과는 다른 실행 인스턴스에서 온 것일 수 있음.** 즉, `run_snapshot_sync_loop.py`가 subprocess로 실행될 때 cash=1을 포함한 로그를 출력하지만, 어떤 이유로 `build_sync_run_entity()` 이전에 subprocess가 중단되거나 crash되어 run entity가 저장되지 않을 수 있음. 다만 subprocess 로그는 commit 이후에 출력되므로 (`tx.commit()` 후 `_log_sync_summary()` 호출) 이 가능성은 낮다.

### 7.2 Root Cause Classification

```
P0 ── cash snapshot 갱신 중단 (15:31 KST 이후 0건)
        └── 원인 미확인 (KIS API 제한? 스케줄러 버그?)
        
P1 ── cash_synced_count=0 vs log cash=1 불일치
        └── 카운터 버그 또는 코드 경로 차이
        
P2 ── KIS output2 필드 전부 NULL
        └── Migration 적용 시점의 자연스러운 상태 (버그 아님)
        
P3 ── Authentication failure 윈도우 (10:03-10:49, 14:57-15:03)
        └── snapshot sync 자체가 실패하여 cash/position 모두 미갱신
```

---

## 8. 향후 필요한 조치

### 8.1 확인 필요 사항 (in order of priority)

1. **`KISRestClient.get_cash_balance()` 응답 검증**: EOD 전후 응답 형상 비교 (paper API가 장 후 빈 dict 반환하는지)
2. **Post-EOD sync cycle 로그 직접 확인**: `run_snapshot_sync_loop.py` 로그에서 `cash=0` + `CASH_SYNC_ZERO` 경고 발생하는지
3. **Cash persist 예외 로그 확인**: cash entity 생성 후 `cash_balance_snapshot_repo.add()` 실패 로그 존재 여부
4. **KIS paper API get_cash_balance 응답 상세**: output2 필드에 `dnca_tot_amt` 등이 정상 포함되는지
5. **`snapshot_sync_runs`와 log의 cycle count 일치 여부**: 같은 회차인지 확인

### 8.2 권장 개선 (코드 수정이 허용될 경우)

1. EOD phase log: snapshot sync 결과를 로그에 상세 기록 (cash=0 사유)
2. `get_cash_balance()` empty response 감지 및 명시적 WARNING 로그
3. `snapshot_sync_runs`의 `summary_json`에 `cash_empty_response` 같은 상세 정보 포함
4. Post-EOD cash sync skip 조건 확인 및 필요시 재설계

---

## 9. AccountsView 영향 평가

| AccountsView 카드 | 현재 표시값 | KIS 필드 | Fallback | 정확성 |
|------------------|------------|----------|----------|--------|
| 총자산 | fallback 계산값 | `total_asset` (NULL) | position 평가금액 합계 + available_cash | **보통** |
| 현금잔고 | 27,329,630원 | `settlement_amount` (NULL) | available_cash | **양호** (15:31 KST 기준) |
| 미실현손익 | -5,000원 | `total_unrealized_pnl` (NULL) | position PnL 합계 | **양호** (17:43 KST 기준) |

AccountsView가 표시하는 금액의 정확성:
- **현금잔고**: 마지막 cash snapshot (15:31 KST)의 available_cash = 27,329,630원. 장 마감 후에는 현금 변동이 없으므로 정확.
- **미실현손익**: 가장 최신 position snapshot (17:43 KST)의 PnL을 합산하므로 정확.
- **총자산**: fallback = position 평가금액 합 + available_cash. Position 평가금액은 최신이나, 이 계산은 `total_asset` (KIS 총평가금액 = 유가증권 평가금액 합계 + D+2 예수금)과 미묘하게 다를 수 있음.

**결론: AccountsView 금액 부정확성의 주 원인은 cash snapshot 갱신 중단보다는 `total_asset` NULL로 인한 fallback 계산 방식의 한계다.**
