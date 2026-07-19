# KIS Paper DB 사전 정리 계획 — 2026-05-13 (승인됨)

> **상태**: 사용자 승인 완료 (2026-05-13 17:09 KST) — 실행 대기 중
> **수정 Group C**: 보존 기준 완화 반영

> **목표**: 내일(2026-05-14) near-real 운영 시작 전 PostgreSQL의 테스트/리허설 데이터를 안전하게 정리하되, KIS 계좌 상태와 운영 기준 데이터는 보존한다.
>
> **원칙**: 문서 작성 후 DELETE 실행은 사용자 승인 이후 진행한다. 무조건 전체 TRUNCATE는 금지하며, 명확한 조건(`created_at`, `client_order_id LIKE`, `source_event_id LIKE`) 기반으로만 삭제한다.

---

## 목차

1. [DB 현황 총괄](#1-db-현황-총괄)
2. [보존 대상 (절대 삭제 금지)](#2-보존-대상-절대-삭제-금지)
3. [삭제 대상 분류](#3-삭제-대상-분류)
4. [FK 관계 및 삭제 순서](#4-fk-관계-및-삭제-순서)
5. [Dry-Run SQL (사전 검증)](#5-dry-run-sql-사전-검증)
6. [Cleanup SQL (실제 삭제)](#6-cleanup-sql-실제-삭제)
7. [삭제 후 검증 SQL](#7-삭제-후-검증-sql)
8. [복구 시나리오](#8-복구-시나리오)
9. [실행 절차](#9-실행-절차)
10. [Post-Cleanup 동기화](#10-post-cleanup-동기화)

---

## 1. DB 현황 총괄

### 1.1 Reference Data (6 tables)

| 테이블 | Rows | 날짜 범위 | 비고 |
|--------|------|-----------|------|
| `clients` | 1 | — | 단일 클라이언트 |
| `accounts` | 1 | — | 단일 계좌 (a44a02d1-...) |
| `broker_accounts` | 1 | — | KIS Paper 계좌 |
| `strategies` | 1 | — | 단일 전략 |
| `config_versions` | 1 | — | 단일 설정 버전 |
| `instruments` | 2 | — | 005930 (삼성전자), AAPL |

### 1.2 Delete-Candidate Tables (13 tables)

| # | 테이블 | Rows | 날짜 범위 | 상태 분포 | 비고 |
|---|--------|------|-----------|-----------|------|
| 1 | `decision_contexts` | **109** | 2026-05-08 ~ 2026-05-13 | — | 모든 결정 컨텍스트 (테스트) |
| 2 | `trade_decisions` | **109** | 2026-05-08 ~ 2026-05-13 | decision=null (109/109) | 결정 없음 = 모두 dry-run |
| 3 | `agent_runs` | **327** | 2026-05-08 ~ 2026-05-13 | event_interpretation=109, ai_risk=109, final_decision_composer=109 | 3개 에이전트 × 109 사이클 |
| 4 | `order_requests` | **21** | 2026-05-11 ~ 2026-05-13 | rejected=15, reconcile_required=6 | 모두 테스트 주문 |
| 5 | `broker_orders` | **6** | 2026-05-11 ~ 2026-05-13 | — | broker 전송 6건 |
| 6 | `order_state_events` | **69** | 2026-05-11 ~ 2026-05-13 | — | order_requests 이력 |
| 7 | `fill_events` | **0** | — | — | 체결 없음 |
| 8 | `snapshot_sync_runs` | **65** | 2026-05-10 ~ 2026-05-13 | completed=55, partial=9, failed=1 | 5분 간격 sync 이력 |
| 9 | `position_snapshots` | **55** | 2026-05-13 (오늘만) | 1 symbol(005930), 10주, ₩267,000 | 5분 간격 스냅샷 |
| 10 | `cash_balance_snapshots` | **380** | 2026-05-08 ~ 2026-05-13 | available_cash=₩30,000,000 | 반복 스냅샷 |
| 11 | `external_events` | **301** | 2026-05-11 ~ 2026-05-13 | opendart=300, smoke_test_v1=1 | 실 데이터 + 테스트 1건 |
| 12 | `audit_logs` | **81** | 2026-05-11 ~ 2026-05-13 | order.create, order.status_change | 주문 감사 로그 |
| 13 | `guardrail_evaluations` | **3** | 2026-05-11 | — | 가드레일 평가 3건 |

### 1.3 비어있는 테이블 (처리 불필요)

`compliance_decisions`(0), `feature_snapshots`(0), `market_data_snapshots`(0), `model_registry`(0), `order_blocking_locks`(0), `prompt_registry`(0), `reconciliation_runs`(0), `reconciliation_order_links`(0), `reconciliation_position_links`(0), `replay_bundles`(0), `risk_decisions`(0), `risk_limit_snapshots`(0), `strategy_versions`(0), `trading_sessions`(0)

---

## 2. 보존 대상 (절대 삭제 금지)

| 테이블 | 보존 사유 |
|--------|----------|
| `clients` | 운영 기준 데이터 |
| `accounts` | 운영 기준 데이터 |
| `broker_accounts` | KIS 계좌 연결 정보 |
| `strategies` | 운영 전략 정의 |
| `config_versions` | 설정 버전 |
| `instruments` | 종목 마스터 (005930, AAPL) |
| `external_events` (opendart 300건) | 실 OpenDART 수집 데이터 — 운영에 필요 |
| `position_snapshots` (최신 1건) | 현재 포지션 상태 유지 (005930 10주) |
| `cash_balance_snapshots` (최신 1건) | 현재 현금 잔고 유지 (₩30,000,000) |
| `snapshot_sync_runs` (최근 2건) | Freshness 확인용 — pre-market에서 필요 |
| `audit_logs` (operational) | 추후 논의 — 현재는 전량 삭제 후보 |

---

## 3. 삭제 대상 분류

### 🟢 Group A — 무조건 삭제 (테스트 쓰레기 데이터)

| 테이블 | 조건 | 예상 삭제 건수 |
|--------|------|---------------|
| `order_requests` | `created_at < '2026-05-14'` (전량) | 21 |
| `broker_orders` | `created_at < '2026-05-14'` (전량) | 6 |
| `order_state_events` | `created_at < '2026-05-14'` (전량) | 69 |
| `guardrail_evaluations` | `created_at < '2026-05-14'` (전량) | 3 |
| `fill_events` | (비어있음, 안전) | 0 |
| `external_events` | `source_name = 'smoke_test_v1'` | 1 |
| `audit_logs` | `created_at < '2026-05-14'` (전량) | 81 |

### 🟡 Group B — 조건부 삭제 (테스트 결정 데이터)

| 테이블 | 조건 | 예상 삭제 건수 |
|--------|------|---------------|
| `decision_contexts` | `created_at < '2026-05-14'` (전량) | 109 |
| `trade_decisions` | `created_at < '2026-05-14'` (전량) | 109 |
| `agent_runs` | `started_at < '2026-05-14'` (전량) | 327 |

### 🔵 Group C — 선별 삭제 (히스토리 보존 완화)

> **수정 (2026-05-13 사용자 승인)**: 최신 1~2건 대신 아래 기준으로 보존

| 테이블 | 보존 조건 | 예상 삭제 건수 |
|--------|----------|---------------|
| `position_snapshots` | account_id + instrument_id별 최신 20건 보존 | 35 (55 - 20) |
| `cash_balance_snapshots` | account_id + currency별 최신 20건 보존 | 360 (380 - 20) |
| `snapshot_sync_runs` | 최신 50건 보존 | 15 (65 - 50) |

---

## 4. FK 관계 및 삭제 순서

### 4.1 FK 의존성 그래프

```
guardrail_evaluations ──FK──→ decision_contexts, order_requests, trade_decisions
order_state_events    ──FK──→ order_requests
fill_events           ──FK──→ broker_orders
broker_orders         ──FK──→ order_requests
order_requests        ──FK──→ decision_contexts, trade_decisions
trade_decisions       ──FK──→ decision_contexts, agent_runs, instruments*, strategies*
agent_runs            ──FK──→ decision_contexts
decision_contexts     ──FK──→ accounts*, cash_balance_snapshots, config_versions*, position_snapshots
position_snapshots    ──FK──→ accounts*, instruments*
cash_balance_snapshots──FK──→ accounts*

* reference data — 삭제 금지, FK만 참조
```

### 4.2 삭제 순서 (의존성 역순)

```
Step 1: guardrail_evaluations   (3 rows)   — 자식 테이블 먼저
Step 2: order_state_events      (69 rows)  — order_requests의 자식
Step 3: fill_events             (0 rows)   — broker_orders의 자식
Step 4: broker_orders           (6 rows)   — order_requests의 자식
Step 5: order_requests          (21 rows)  — decision_contexts, trade_decisions의 자식
Step 6: trade_decisions         (109 rows) — decision_contexts, agent_runs의 자식
Step 7: agent_runs              (327 rows) — decision_contexts의 자식
Step 8: decision_contexts       (109 rows) — 최상위 (참조 데이터 FK는 만족)
Step 9: position_snapshots      (54 rows)  — 오래된 스냅샷 정리
Step 10: cash_balance_snapshots (379 rows) — 오래된 스냅샷 정리
Step 11: snapshot_sync_runs     (63 rows)  — 오래된 sync 이력 정리
Step 12: audit_logs             (81 rows)  — 독립 테이블
Step 13: external_events        (1 row)    — smoke_test 1건
```

### 4.3 FK 제약 조건 참고사항

- `decision_contexts.cash_balance_snapshot_id` → `cash_balance_snapshots`: **nullable**로 추정되므로 스냅샷 먼저 삭제해도 무방 (CASCADE 영향 없음)
- `decision_contexts.position_snapshot_id` → `position_snapshots`: 위와 동일
- `decision_contexts.account_id` → `accounts`: reference data (1건) — 삭제 안 함
- `order_requests.trade_decision_id` → `trade_decisions`: nullable (decision=null 케이스는 trade_decision_id도 null일 가능성 높음)
- `audit_logs`는 FK 제약 없음 — 아무 때나 삭제 가능

---

## 5. Dry-Run SQL (사전 검증)

> 다음 SQL로 **실제 삭제 전 예상 대상 건수를 확인**한다.

### 5.1 Group A — 무조건 삭제

```sql
-- order_requests (예상: 21건)
SELECT COUNT(*) FROM order_requests
WHERE created_at < '2026-05-14'::timestamptz;

-- broker_orders (예상: 6건)
SELECT COUNT(*) FROM broker_orders bo
WHERE EXISTS (
    SELECT 1 FROM order_requests o
    WHERE o.order_request_id = bo.order_request_id
    AND o.created_at < '2026-05-14'::timestamptz
);

-- order_state_events (예상: 69건)
SELECT COUNT(*) FROM order_state_events ose
WHERE EXISTS (
    SELECT 1 FROM order_requests o
    WHERE o.order_request_id = ose.order_request_id
    AND o.created_at < '2026-05-14'::timestamptz
);

-- guardrail_evaluations (예상: 3건)
SELECT COUNT(*) FROM guardrail_evaluations
WHERE created_at < '2026-05-14'::timestamptz;

-- fill_events (예상: 0건)
SELECT COUNT(*) FROM fill_events;

-- external_events smoke_test (예상: 1건)
SELECT COUNT(*) FROM external_events
WHERE source_name = 'smoke_test_v1';

-- audit_logs (예상: 81건)
SELECT COUNT(*) FROM audit_logs
WHERE created_at < '2026-05-14'::timestamptz;
```

### 5.2 Group B — 조건부 삭제

```sql
-- decision_contexts (예상: 109건)
SELECT COUNT(*) FROM decision_contexts
WHERE created_at < '2026-05-14'::timestamptz;

-- trade_decisions (예상: 109건)
SELECT COUNT(*) FROM trade_decisions td
WHERE EXISTS (
    SELECT 1 FROM decision_contexts dc
    WHERE dc.decision_context_id = td.decision_context_id
    AND dc.created_at < '2026-05-14'::timestamptz
);

-- agent_runs (예상: 327건)
SELECT COUNT(*) FROM agent_runs ar
WHERE EXISTS (
    SELECT 1 FROM decision_contexts dc
    WHERE dc.decision_context_id = ar.decision_context_id
    AND dc.created_at < '2026-05-14'::timestamptz
);
```

### 5.3 Group C — 선별 삭제

```sql
-- position_snapshots — account_id + instrument_id별 최신 20건 보존 (예상: 35건)
WITH ranked AS (
    SELECT position_snapshot_id,
           ROW_NUMBER() OVER (
               PARTITION BY account_id, instrument_id
               ORDER BY snapshot_at DESC
           ) AS rn
    FROM position_snapshots
)
SELECT COUNT(*) FROM ranked WHERE rn > 20;

-- cash_balance_snapshots — account_id + currency별 최신 20건 보존 (예상: 360건)
WITH ranked AS (
    SELECT cash_balance_snapshot_id,
           ROW_NUMBER() OVER (
               PARTITION BY account_id, currency
               ORDER BY snapshot_at DESC
           ) AS rn
    FROM cash_balance_snapshots
)
SELECT COUNT(*) FROM ranked WHERE rn > 20;

-- snapshot_sync_runs — 최신 50건 보존 (예상: 15건)
WITH keep AS (
    SELECT snapshot_sync_run_id
    FROM snapshot_sync_runs
    ORDER BY started_at DESC
    LIMIT 50
)
SELECT COUNT(*) FROM snapshot_sync_runs
WHERE snapshot_sync_run_id NOT IN (SELECT snapshot_sync_run_id FROM keep);
```

---

## 6. Cleanup SQL (실제 삭제)

> ⚠️ **실행 전 반드시 사용자 승인 필요**  
> ⚠️ **BEGIN / ROLLBACK 래퍼 필수 — COMMIT 전 건수 확인**

### 6.1 전체 Cleanup (트랜잭션 블록)

```sql
BEGIN;

-- === Step 1: guardrail_evaluations ===
DELETE FROM guardrail_evaluations
WHERE created_at < '2026-05-14'::timestamptz;

-- === Step 2: order_state_events ===
DELETE FROM order_state_events ose
USING order_requests o
WHERE o.order_request_id = ose.order_request_id
  AND o.created_at < '2026-05-14'::timestamptz;

-- === Step 3: fill_events ===
DELETE FROM fill_events;  -- 0건

-- === Step 4: broker_orders ===
DELETE FROM broker_orders bo
USING order_requests o
WHERE o.order_request_id = bo.order_request_id
  AND o.created_at < '2026-05-14'::timestamptz;

-- === Step 5: order_requests ===
DELETE FROM order_requests
WHERE created_at < '2026-05-14'::timestamptz;

-- === Step 6: trade_decisions ===
DELETE FROM trade_decisions td
USING decision_contexts dc
WHERE dc.decision_context_id = td.decision_context_id
  AND dc.created_at < '2026-05-14'::timestamptz;

-- === Step 7: agent_runs ===
DELETE FROM agent_runs ar
USING decision_contexts dc
WHERE dc.decision_context_id = ar.decision_context_id
  AND dc.created_at < '2026-05-14'::timestamptz;

-- === Step 8: decision_contexts ===
DELETE FROM decision_contexts
WHERE created_at < '2026-05-14'::timestamptz;

-- === Step 9: position_snapshots (account_id + instrument_id별 최신 20건 보존) ===
WITH ranked AS (
    SELECT position_snapshot_id,
           ROW_NUMBER() OVER (
               PARTITION BY account_id, instrument_id
               ORDER BY snapshot_at DESC
           ) AS rn
    FROM position_snapshots
)
DELETE FROM position_snapshots ps
USING ranked r
WHERE ps.position_snapshot_id = r.position_snapshot_id
  AND r.rn > 20;

-- === Step 10: cash_balance_snapshots (account_id + currency별 최신 20건 보존) ===
WITH ranked AS (
    SELECT cash_balance_snapshot_id,
           ROW_NUMBER() OVER (
               PARTITION BY account_id, currency
               ORDER BY snapshot_at DESC
           ) AS rn
    FROM cash_balance_snapshots
)
DELETE FROM cash_balance_snapshots cbs
USING ranked r
WHERE cbs.cash_balance_snapshot_id = r.cash_balance_snapshot_id
  AND r.rn > 20;

-- === Step 11: snapshot_sync_runs (최신 50건 보존) ===
WITH keep AS (
    SELECT snapshot_sync_run_id
    FROM snapshot_sync_runs
    ORDER BY started_at DESC
    LIMIT 50
)
DELETE FROM snapshot_sync_runs
WHERE snapshot_sync_run_id NOT IN (SELECT snapshot_sync_run_id FROM keep);

-- === Step 12: audit_logs ===
DELETE FROM audit_logs
WHERE created_at < '2026-05-14'::timestamptz;

-- === Step 13: external_events (smoke_test만) ===
DELETE FROM external_events
WHERE source_name = 'smoke_test_v1';

-- === COMMIT 전 최종 건수 확인 ===
SELECT 'decision_contexts' AS tbl, COUNT(*) FROM decision_contexts
UNION ALL SELECT 'trade_decisions', COUNT(*) FROM trade_decisions
UNION ALL SELECT 'agent_runs', COUNT(*) FROM agent_runs
UNION ALL SELECT 'order_requests', COUNT(*) FROM order_requests
UNION ALL SELECT 'broker_orders', COUNT(*) FROM broker_orders
UNION ALL SELECT 'order_state_events', COUNT(*) FROM order_state_events
UNION ALL SELECT 'guardrail_evaluations', COUNT(*) FROM guardrail_evaluations
UNION ALL SELECT 'snapshot_sync_runs', COUNT(*) FROM snapshot_sync_runs
UNION ALL SELECT 'position_snapshots', COUNT(*) FROM position_snapshots
UNION ALL SELECT 'cash_balance_snapshots', COUNT(*) FROM cash_balance_snapshots
UNION ALL SELECT 'external_events', COUNT(*) FROM external_events
UNION ALL SELECT 'audit_logs', COUNT(*) FROM audit_logs
ORDER BY tbl;

-- 검증 후 COMMIT (또는 ROLLBACK)
-- COMMIT;
-- ROLLBACK;
```

---

## 7. 삭제 후 검증 SQL

> Cleanup 완료 후 예상되는 최종 상태를 확인한다.

```sql
-- 1) Reference data는 intact
SELECT 'clients', COUNT(*) FROM clients
UNION ALL SELECT 'accounts', COUNT(*) FROM accounts
UNION ALL SELECT 'broker_accounts', COUNT(*) FROM broker_accounts
UNION ALL SELECT 'strategies', COUNT(*) FROM strategies
UNION ALL SELECT 'config_versions', COUNT(*) FROM config_versions
UNION ALL SELECT 'instruments', COUNT(*) FROM instruments;

-- 2) Delete-candidate 테이블이 깨끗해졌는지 확인
SELECT 'decision_contexts', COUNT(*) FROM decision_contexts
UNION ALL SELECT 'trade_decisions', COUNT(*) FROM trade_decisions
UNION ALL SELECT 'agent_runs', COUNT(*) FROM agent_runs
UNION ALL SELECT 'order_requests', COUNT(*) FROM order_requests
UNION ALL SELECT 'broker_orders', COUNT(*) FROM broker_orders
UNION ALL SELECT 'order_state_events', COUNT(*) FROM order_state_events
UNION ALL SELECT 'fill_events', COUNT(*) FROM fill_events
UNION ALL SELECT 'guardrail_evaluations', COUNT(*) FROM guardrail_evaluations;

-- 3) 스냅샷이 각 account당 1건만 남았는지 확인
SELECT account_id, COUNT(*) FROM position_snapshots GROUP BY account_id;
SELECT account_id, COUNT(*) FROM cash_balance_snapshots GROUP BY account_id;

-- 4) snapshot_sync_runs가 최근 2건만 남았는지 확인
SELECT COUNT(*) FROM snapshot_sync_runs;

-- 5) external_events에 opendart 데이터만 남았는지 확인
SELECT source_name, COUNT(*) FROM external_events GROUP BY source_name;

-- 6) 전체 테이블 row count 스캔 (빈 테이블 확인)
SELECT table_name,
       (xpath('/row/c/text()', query_to_xml('SELECT count(*) AS c FROM trading.'||table_name, FALSE, TRUE, '')))[1]::text::int AS row_count
FROM information_schema.tables
WHERE table_schema = 'trading'
  AND table_type = 'BASE TABLE'
ORDER BY table_name;
```

---

## 8. 복구 시나리오

### 8.1 실수로 COMMIT한 경우

> PostgreSQL은 `information_schema`에 과거 데이터 스냅샷을 보관하지 않으므로, COMMIT 후에는 **복구 불가**. 따라서 반드시 사전 백업 또는 BEGIN/ROLLBACK 검증 절차를 수행해야 한다.

**권장 사전 백업**:

```bash
# 2026-05-14 07:50 KST 이전에 실행 (pg_dump 필요 시)
pg_dump --dbname="$DATABASE_URL" \
  --schema=trading \
  --data-only \
  --table=trading.decision_contexts \
  --table=trading.trade_decisions \
  --table=trading.agent_runs \
  --table=trading.order_requests \
  --table=trading.broker_orders \
  --table=trading.order_state_events \
  --table=trading.guardrail_evaluations \
  --table=trading.snapshot_sync_runs \
  --table=trading.position_snapshots \
  --table=trading.cash_balance_snapshots \
  --table=trading.audit_logs \
  --file=/tmp/pre_cleanup_backup_2026-05-14.sql
```

> **참고**: 현재 환경에 `pg_dump`가 설치되어 있지 않을 수 있음. 사용 가능 여부 확인 필요.

### 8.2 대체 백업 방법 — `CREATE TABLE AS` 스냅샷

```sql
BEGIN;
-- 각 테이블 백업 (동일 트랜잭션 내)
CREATE TABLE trading._backup_decision_contexts AS SELECT * FROM decision_contexts;
CREATE TABLE trading._backup_trade_decisions AS SELECT * FROM trade_decisions;
CREATE TABLE trading._backup_agent_runs AS SELECT * FROM agent_runs;
CREATE TABLE trading._backup_order_requests AS SELECT * FROM order_requests;
CREATE TABLE trading._backup_broker_orders AS SELECT * FROM broker_orders;
CREATE TABLE trading._backup_order_state_events AS SELECT * FROM order_state_events;
-- ... 필요시 추가
COMMIT;

-- Cleanup 실행
-- ... (위 6번 SQL)

-- 복구 필요시:
-- INSERT INTO decision_contexts SELECT * FROM trading._backup_decision_contexts;
-- 등
```

### 8.3 잘못 삭제한 경우 확인

```sql
-- position_snapshots가 0건이 된 경우 (최신이 삭제됨)
-- → pre-market snapshot_sync로 자동 복구 (KIS에서 다시 조회)
-- 단, EOD 마감가 기준이 아닌 시점 데이터로 복구됨

-- cash_balance_snapshots가 0건이 된 경우
-- → 위와 동일, pre-market에서 자동 복구
```

---

## 9. 실행 절차

### 9.1 사전 준비 (본 문서 작성 완료 = READY)

- [x] DB 현황 조사 완료 (MCP PostgreSQL)
- [x] FK 관계 분석 완료
- [x] 보존/삭제 분류 완료
- [x] Dry-run SQL 작성 완료
- [x] Cleanup SQL 작성 완료
- [x] 검증 SQL 작성 완료
- [ ] ⏳ **사용자 승인 대기**

### 9.2 실행 순서

```
1. 사용자로부터 "DELETE 실행 승인" 획득 ──── [대기 중]
2. [선택] pg_dump 또는 CREATE TABLE AS 백업
3. BEGIN;
4. Dry-run SQL (SELECT COUNT) 실행 → 예상치 확인
5. Cleanup SQL 순차 실행
6. 검증 SQL 실행
7. COMMIT; (이상 없을 시)
8. [선택] DROP TABLE _backup_*;
9. Post-Cleanup 동기화 실행
```

### 9.3 실행 전 체크리스트

- [ ] `.env` 파일 수정 금지 — 환경 변수 그대로 사용
- [ ] KIS_ENV=paper 유지 — 변경 금지
- [ ] 운영 중인 스케줄러/루프가 없는지 확인
- [ ] `pg_dump` 또는 `CREATE TABLE AS` 백업 완료
- [ ] BEGIN/ROLLBACK 으로 먼저 검증 (COMMIT 전)

---

## 10. Post-Cleanup 동기화

> Cleanup 완료 후, 내일 pre-market 시작 전에 반드시 동기화가 필요하다.

### 10.1 Snapshot Sync (포지션/현금)

```bash
# 단발 1회 실행 — 최신 KIS 상태로 스냅샷 갱신
cd /workspace/agent_trading && python3 -m dotenv -f .env -- python3 scripts/run_snapshot_sync_loop.py --max-cycles 1
```

### 10.2 Event Ingestion (외부 이벤트)

```bash
# 단발 1회 실행 — 최신 OpenDART 이벤트 수집
cd /workspace/agent_trading && python3 -m dotenv -f .env -- python3 scripts/run_event_ingestion_loop.py --count 1
```

### 10.3 Decision Pipeline 준비 확인

```bash
# Dry-run 1회 — decision pipeline 정상 작동 확인
cd /workspace/agent_trading && python3 -m dotenv -f .env -- python3 scripts/run_paper_decision_loop.py --max-cycles 1 --dry-run
```

---

## 부록 A: 삭제 조건 상세 분석

### client_order_id 패턴

모든 `order_requests`의 `client_order_id`는 `dc-{uuid}-{timestamp}` 패턴:
- `dc-dd401836-0044447789` (reconcile_required, 05-13)
- `dc-bcac6425-0706534740` (rejected, 05-11)
- 공통점: `dc-` 접두사, 모두 테스트 주문

### correlation_id 패턴

모든 `correlation_id`는 `entrypoint-correlation-{uuid}` 패턴:
- `entrypoint-correlation-1913e173-...` (05-13)
- `entrypoint-correlation-bcac6425-...` (05-11)
- 모두 테스트 실행에서 생성

### external_events smoke_test

- 1건: `source_name='smoke_test_v1'`, `source_event_id`가 `smoke%` 패턴과 일치하지 않으나 별도 식별 가능
- 나머지 300건: 모두 `opendart` source, 실 OpenDART 수집 데이터

---

## 부록 B: FK 관계 전체 목록 (49개)

| Source Table | FK Column | Target Table | 비고 |
|-------------|-----------|-------------|------|
| `accounts` | `broker_account_id` | `broker_accounts` | 보존 |
| `accounts` | `client_id` | `clients` | 보존 |
| `agent_runs` | `decision_context_id` | `decision_contexts` | **삭제 대상** |
| `agent_runs` | `model_id` | `model_registry` | 비어있음 |
| `agent_runs` | `prompt_id` | `prompt_registry` | 비어있음 |
| `broker_orders` | `order_request_id` | `order_requests` | **삭제 대상** |
| `cash_balance_snapshots` | `account_id` | `accounts` | 보존 |
| `compliance_decisions` | `agent_run_id` | `agent_runs` | 비어있음 |
| `compliance_decisions` | `decision_context_id` | `decision_contexts` | 비어있음 |
| `config_versions` | `client_id` | `clients` | 보존 |
| `decision_contexts` | `account_id` | `accounts` | 보존 (참조) |
| `decision_contexts` | `cash_balance_snapshot_id` | `cash_balance_snapshots` | **삭제 대상** (nullable) |
| `decision_contexts` | `config_version_id` | `config_versions` | 보존 (참조) |
| `decision_contexts` | `feature_snapshot_id` | `feature_snapshots` | 비어있음 |
| `decision_contexts` | `position_snapshot_id` | `position_snapshots` | **삭제 대상** (nullable) |
| `decision_contexts` | `strategy_id` | `strategies` | 보존 |
| `decision_contexts` | `strategy_version_id` | `strategy_versions` | 비어있음 |
| `decision_contexts` | `trading_session_id` | `trading_sessions` | 비어있음 |
| `external_events` | `supersedes_event_id` | `external_events` | self-FK |
| `fill_events` | `broker_order_id` | `broker_orders` | 비어있음 |
| `guardrail_evaluations` | `decision_context_id` | `decision_contexts` | **삭제 대상** |
| `guardrail_evaluations` | `order_request_id` | `order_requests` | **삭제 대상** |
| `guardrail_evaluations` | `trade_decision_id` | `trade_decisions` | **삭제 대상** |
| `order_requests` | `account_id` | `accounts` | 보존 |
| `order_requests` | `decision_context_id` | `decision_contexts` | **삭제 대상** |
| `order_requests` | `instrument_id` | `instruments` | 보존 |
| `order_requests` | `trade_decision_id` | `trade_decisions` | **삭제 대상** |
| `order_state_events` | `order_request_id` | `order_requests` | **삭제 대상** |
| `position_snapshots` | `account_id` | `accounts` | 보존 |
| `position_snapshots` | `instrument_id` | `instruments` | 보존 |
| `trade_decisions` | `agent_run_id` | `agent_runs` | **삭제 대상** |
| `trade_decisions` | `decision_context_id` | `decision_contexts` | **삭제 대상** |
| `trade_decisions` | `instrument_id` | `instruments` | 보존 |
| `trade_decisions` | `strategy_id` | `strategies` | 보존 |

---

*문서 작성일: 2026-05-13 17:05 KST*  
*다음 단계: 사용자 승인 대기 → Code 모드에서 DELETE 실행*
