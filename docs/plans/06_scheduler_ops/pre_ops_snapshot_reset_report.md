# KIS Paper 스냅샷 초기화 실행 보고서 — 2026-05-13

> **실행일시**: 2026-05-13 17:19–17:21 KST (UTC+9)  
> **실행자**: Roo (Code mode)  
> **대상**: PostgreSQL `trading` schema — snapshot 3개 테이블 전량 삭제  
> **결과**: ✅ **성공 — 94건 삭제, COMMIT 완료**

---

## 1. 실행 전/후 Row Count 비교

| 테이블 | 실행 전 | 실행 후 | 삭제 건수 | 비고 |
|--------|---------|---------|-----------|------|
| `position_snapshots` | 22 | 0 | 22 | ✅ 전량 삭제 |
| `cash_balance_snapshots` | 20 | 0 | 20 | ✅ 전량 삭제 |
| `snapshot_sync_runs` | 52 | 0 | 52 | ✅ 전량 삭제 |
| **합계** | **94** | **0** | **94** | |

## 2. 보존 데이터 검증

### Reference Data (6 tables) — 모두 보존 ✅

| 테이블 | 건수 | 상태 |
|--------|------|------|
| `clients` | 1 | ✅ |
| `accounts` | 1 | ✅ |
| `broker_accounts` | 1 | ✅ |
| `strategies` | 1 | ✅ |
| `config_versions` | 1 | ✅ |
| `instruments` | 2 | ✅ (005930, AAPL) |

### External Events — OpenDART 300건 보존 ✅

| Source | 건수 | 상태 |
|--------|------|------|
| `opendart` | 300 | ✅ 실 데이터 보존 |

### Operational Tables — 모두 0건 (이전 Cleanup 유지) ✅

| 테이블 | 건수 | 상태 |
|--------|------|------|
| `decision_contexts` | 0 | ✅ |
| `trade_decisions` | 0 | ✅ |
| `agent_runs` | 0 | ✅ |
| `order_requests` | 0 | ✅ |
| `broker_orders` | 0 | ✅ |
| `order_state_events` | 0 | ✅ |
| `fill_events` | 0 | ✅ |
| `guardrail_evaluations` | 0 | ✅ |
| `audit_logs` | 0 | ✅ |
| `position_snapshots` | 0 | ✅ |
| `cash_balance_snapshots` | 0 | ✅ |
| `snapshot_sync_runs` | 0 | ✅ |

## 3. 실행 SQL

```sql
BEGIN;

DELETE FROM trading.position_snapshots;       -- 22 rows
DELETE FROM trading.cash_balance_snapshots;    -- 20 rows
DELETE FROM trading.snapshot_sync_runs;        -- 52 rows

-- Post-check (all 0, reference data intact)
-- COMMIT

COMMIT;
```

### FK 안전성

- `decision_contexts.position_snapshot_id` → 0건 (이미 삭제됨)
- `reconciliation_position_links.position_snapshot_id` → 0건 (존재하지 않음)
- `decision_contexts.cash_balance_snapshot_id` → 0건 (이미 삭제됨)
- **FK 충돌 없이 단일 DELETE 3문으로 처리 가능**

## 4. 트랜잭션 처리

| 단계 | 상태 |
|------|------|
| Pre-check (before counts) | ✅ 통과 |
| BEGIN | ✅ |
| DELETE position_snapshots (22건) | ✅ |
| DELETE cash_balance_snapshots (20건) | ✅ |
| DELETE snapshot_sync_runs (52건) | ✅ |
| Post-check (within transaction) | ✅ 전 항목 통과 |
| COMMIT | ✅ |
| Final verification (after COMMIT) | ✅ 전 항목 통과 |

## 5. Admin UI 상태

- `GET /positions` → 빈 배열 (`[]`)
- `GET /cash-balances` → `null`
- 계좌 화면에서 포지션/현금 스냅샷 영역이 **"스냅샷 없음"** 상태로 표시됨

## 6. 익일 (2026-05-14) Pre-Market 재적재 계획

### Pre-Market 첫 Snapshot Sync Cycle에서 자동 재적재될 항목

| 항목 | 재적재 방식 | 예상 소요 |
|------|-------------|-----------|
| `position_snapshots` | `sync_kis_snapshots.py` → KIS `/inquire-balance` | ~1s (1 position) |
| `cash_balance_snapshots` | `sync_kis_snapshots.py` → KIS `/inquire-psbl-order` | ~1s (1 RPS) |
| `snapshot_sync_runs` | Sync 실행 시 자동 기록 | ~0.5s |

### 실행 명령어 (Pre-Market 시)

```bash
cd /workspace/agent_trading
python3 -m dotenv -f .env run python3 scripts/sync_kis_snapshots.py --all --env paper --format json
```

> **참고**: Pre-Market 스케줄러(`run_near_real_ops_scheduler.py`)가 08:00 KST에 자동으로 첫 sync를 실행합니다. 수동 실행은 디버깅 목적으로만 필요합니다.

## 7. 최종 DB 상태 요약

| 구분 | 건수 |
|------|------|
| Reference data | 7건 (6개 테이블) |
| External events (OpenDART) | 300건 |
| Snapshot data | **0건** ✅ |
| Operational data | **0건** ✅ |
| **Total** | **307건** |

---

*보고서 작성일: 2026-05-13 17:21 KST*
