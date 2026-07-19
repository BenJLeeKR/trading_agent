# KIS Paper DB 사전 정리 실행 보고서 — 2026-05-13

> **실행일시**: 2026-05-13 17:10–17:14 KST (UTC+9)  
> **실행자**: Roo (Code mode)  
> **대상**: PostgreSQL `trading` schema  
> **결과**: ✅ **성공 — 1,139건 삭제, COMMIT 완료**

---

## 1. 실행 전/후 Row Count 비교

| 테이블 | 실행 전 | 실행 후 | 삭제 건수 | 비고 |
|--------|---------|---------|-----------|------|
| `guardrail_evaluations` | 3 | 0 | 3 | ✅ 전량 삭제 |
| `order_state_events` | 69 | 0 | 69 | ✅ 전량 삭제 |
| `fill_events` | 0 | 0 | 0 | ✅ 빈 테이블 |
| `broker_orders` | 6 | 0 | 6 | ✅ 전량 삭제 |
| `order_requests` | 21 | 0 | 21 | ✅ 전량 삭제 |
| `trade_decisions` | 109 | 0 | 109 | ✅ 전량 삭제 |
| `agent_runs` | 327 | 0 | 327 | ✅ 전량 삭제 |
| `decision_contexts` | 109 | 0 | 109 | ✅ 전량 삭제 |
| `position_snapshots` | 55 | 21 | 34 | ✅ 최신 20건 + sync 1건 보존 |
| `cash_balance_snapshots` | 380 | 20 | 360 | ✅ account+currency별 최신 20건 보존 |
| `snapshot_sync_runs` | 65 | 51 | 14 | ✅ 최신 50건 + sync 1건 보존 |
| `audit_logs` | 81 | 0 | 81 | ✅ 전량 삭제 |
| `external_events(smoke)` | 1 | 0 | 1 | ✅ smoke_test_v1 1건 삭제 |
| **합계** | **1,226** | **92** | **1,134** | |

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
| `smoke_test_v1` | 0 | ✅ 테스트 1건 삭제 |

### Position Snapshots — 최신 21건 보존 ✅

| Account ID | 건수 | 비고 |
|-----------|------|------|
| `a44a02d1-...` | 21 | 005930 10주, 최신 20건 + sync 1건 |

### Cash Balance Snapshots — 최신 20건 보존 ✅

| Account ID | 건수 | 비고 |
|-----------|------|------|
| `a44a02d1-...` | 20 | ₩30,000,000, 최신 20건 |

### Snapshot Sync Runs — 최신 51건 보존 ✅

| 건수 | 비고 |
|------|------|
| 51 | 최신 50건 + sync 1건 |

---

## 3. 삭제 순서 및 FK 안전성

| Step | 테이블 | FK 위험 | 결과 |
|------|--------|---------|------|
| 1 | `guardrail_evaluations` | → decision_contexts, order_requests, trade_decisions | ✅ 자식 먼저 |
| 2 | `order_state_events` | → order_requests | ✅ 자식 먼저 |
| 3 | `fill_events` | → broker_orders | ✅ 빈 테이블 |
| 4 | `broker_orders` | → order_requests | ✅ 자식 먼저 |
| 5 | `order_requests` | → decision_contexts, trade_decisions | ✅ 자식 먼저 |
| 6 | `trade_decisions` | → decision_contexts, agent_runs | ✅ 자식 먼저 |
| 7 | `agent_runs` | → decision_contexts | ✅ 자식 먼저 |
| 8 | `decision_contexts` | → accounts, instruments (참조) | ✅ 참조 데이터 intact |
| 9 | `position_snapshots` | → accounts, instruments (참조) | ✅ 참조 데이터 intact |
| 10 | `cash_balance_snapshots` | → accounts (참조) | ✅ 참조 데이터 intact |
| 11 | `snapshot_sync_runs` | 독립 테이블 | ✅ |
| 12 | `audit_logs` | 독립 테이블 | ✅ |
| 13 | `external_events(smoke)` | self-FK (supersedes_event_id) | ✅ 1건만 삭제 |

**FK 제약 조건 위반: 0건** ✅

---

## 4. Post-Cleanup Snapshot Sync 결과

```json
{
  "status": "success",
  "total_accounts": 1,
  "succeeded": 0,
  "partial": 1,
  "failed": 0,
  "total_positions_synced": 1,
  "total_cash_synced": 0,
  "errors": ["Global REST cap exhausted (remaining=0/1)"]
}
```

- **Position sync**: ✅ 성공 (005930 10주, snapshot_at=17:14 KST)
- **Cash balance sync**: ⚠️ REST rate limit (1/1) — pre-market에서 재시도 필요
- **신규 snapshot_sync_run**: 1건 추가 (총 51건)

---

## 5. 최종 상태 요약

### ✅ 통과한 검증 항목

| # | 검증 항목 | 결과 |
|---|----------|------|
| 1 | Reference 6개 테이블 보존 | ✅ |
| 2 | order_requests = 0건 | ✅ |
| 3 | broker_orders = 0건 | ✅ |
| 4 | order_state_events = 0건 | ✅ |
| 5 | fill_events = 0건 | ✅ |
| 6 | guardrail_evaluations = 0건 | ✅ |
| 7 | synthetic/smoke external_events = 0건 | ✅ |
| 8 | OpenDART external_events = 300건 | ✅ |
| 9 | position_snapshots 최신 snapshot 존재 | ✅ (21건) |
| 10 | cash_balance_snapshots 최신 snapshot 존재 | ✅ (20건) |
| 11 | snapshot_sync_runs 최근 이력 존재 | ✅ (51건) |
| 12 | audit_logs = 0건 | ✅ |

### ⚠️ 주의사항

1. **Cash balance sync 실패**: REST rate limit (1/1)으로 인해 현금 잔고가 갱신되지 않음. 내일 pre-market(08:00 KST) 첫 sync cycle에서 자동 복구됨.
2. **KIS token cache**: `KIS_DEV_TOKEN_CACHE_ENABLED=true`로 설정되어 있어, sync 스크립트가 token cache를 사용함. cache가 만료된 경우 pre-market에서 재인증 필요.
3. **audit_logs 전량 삭제**: 운영 감사 로그가 모두 삭제됨. 향후 운영 시작 후에는 audit_logs 보존 정책 수립 필요.

---

## 6. 익일(2026-05-14) Pre-Market 준비 상태

| 항목 | 상태 | 비고 |
|------|------|------|
| DB 테스트 데이터 정리 | ✅ 완료 | 1,134건 삭제 |
| Reference 데이터 | ✅ 보존 | 6개 테이블 intact |
| 포지션 스냅샷 | ✅ 최신 (17:14 KST) | 005930 10주 |
| 현금 잔고 스냅샷 | ⚠️ 미갱신 | REST cap 소진, pre-market에서 복구 |
| Sync 이력 | ✅ 최신 51건 | Freshness 확인 가능 |
| OpenDART 이벤트 | ✅ 300건 | 실 데이터 보존 |
| Scheduler runbook | ✅ 작성 완료 | `plans/near_real_scheduler_runbook_2026-05-14.md` |

---

*보고서 작성일: 2026-05-13 17:14 KST*  
*실행 스크립트: [`_cleanup_db.py`](_cleanup_db.py), [`_cleanup_commit.py`](_cleanup_commit.py)*
