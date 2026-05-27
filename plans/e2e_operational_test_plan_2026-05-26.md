# E2E Operational Test Plan — 2026-05-26 (화)

## 1. 개요

### 1.1 목적
2026-05-26(화) KST 정규 거래일을 대상으로, 최근 리팩토링된 운영 파이프라인(`run_ops_scheduler` 중심 4-loop 분해 구조)이 실제 운영 경로에서 정상 동작함을 검증한다.

### 1.2 범위
- **Session Gate** — 076 API + 163 WebSocket combined market session provider
- **스냅샷 Sync** — KIS paper 계좌 position/cash balance 주기적 동기화
- **Event Ingestion** — 외부 이벤트 수집 (NAVER news, KIS disclosure)
- **Decision Loop** — AI 판단 → 예산 내 제한적 submit (건당 1회, 최대 1건)
- **Post-submit Sync** — 주문 상태 broker-terminal 수렴
- **Reconciliation** — Broker truth 조회 및 정합성 검증
- **After-hours** — 장후 스냅샷 모드 + 16:00 KST recovery batch

### 1.3 제약사항
- `python3` 만 사용 (docker compose exec 또는 직접 실행)
- `.env` 파일 수정 불가 (기존 paper credentials 그대로 사용)
- 실제 submit 경로 테스트하되 **소량/제한적** 실행 (기본 예산: 1건)
- Dry-run → 실제 submit 순차적 전환

### 1.4 사전 상태 (2026-05-25 KST 기준)
| 항목 | 값 |
|------|-----|
| APP_ENV | paper |
| KIS_ENV | paper |
| KIS 계좌 | 50186448 (모의투자) |
| Broker Account ID | `7f39fc04-346a-5484-90ab-80e8a1d04a15` |
| Account ID | `a44a02d1-7f32-5a62-99f7-235abeb58284` |
| market_sessions 건수 | 11 (2026-05-25 KST 건: source=unknown, phase=null) |
| session_events 건수 | 0 |
| order_requests 건수 | 200 (대부분 expired/rejected, 2건 filled) |
| reconciliation_runs | 13건, 전부 failed (일부 completed_at=null ⇒ stuck 위험) |
| position_snapshots | 4494건 |
| trading_sessions | empty |

---

## 2. Phase 0 — 사전 준비 (KST 07:30–07:50)

### 2.1 환경 헬스체크
```bash
# Docker 컨테이너 상태 확인
docker ps

# PostgreSQL 연결 확인
python3 -c "
import asyncio, os; from agent_trading.db.connection import create_pool, DatabaseConfig
dsn = os.environ.get('DATABASE_URL', 'postgresql://trading:trading@localhost:5432/trading')
pool = asyncio.run(create_pool(DatabaseConfig(dsn=dsn)))
row = asyncio.run(pool.fetchrow('SELECT count(*) as cnt FROM trading.market_sessions'))
print(f'market_sessions: {row[\"cnt\"]}')
asyncio.run(pool.close())
"
```

### 2.2 API 헬스체크
```bash
# FastAPI inspection API가 실행 중인지 확인
curl -s http://localhost:8000/health/readyz -H "Authorization: Bearer dev-token-123"

# Market sessions latest 조회 (사전 seed 확인)
curl -s http://localhost:8000/market-sessions/latest -H "Authorization: Bearer dev-token-123"

# Reconciliation summary
curl -s http://localhost:8000/reconciliation/summary -H "Authorization: Bearer dev-token-123"
```

### 2.3 DB 사전 스냅샷 (검증 기준 저장)
```sql
-- 실행 전 스냅샷 저장용 쿼리
SELECT run_date, is_trading_day, market_phase, source, checked_at
FROM trading.market_sessions ORDER BY run_date DESC;

SELECT status, count(*) FROM trading.order_requests GROUP BY status;
SELECT status, count(*) FROM trading.reconciliation_runs GROUP BY status;
SELECT count(*) FROM trading.position_snapshots;
SELECT count(*) FROM trading.session_events;
SELECT count(*) FROM trading.trading_sessions;
```

### ✅ 검증 기준 (Phase 0)
- [ ] `docker ps` 에 db, api 컨테이너가 running 상태
- [ ] `/health/readyz` 가 200 응답
- [ ] `/market-sessions/latest` 가 `status=ok` 반환
- [ ] DB 연결 정상

---

## 3. Phase 1 — Ops Scheduler 단일 실행 (KST 07:50–08:10)

### 3.1 Scheduler `--once` 모드 실행 (Session Gate 검증)
```bash
cd /workspace/agent_trading
python3 -m scripts.run_ops_scheduler --once 2>&1 | tee logs/ops_scheduler_once_20260526.log
```

### 3.2 검증 항목
```sql
-- 1. market_sessions upsert 확인 (run_date=2026-05-26, source=scheduler)
SELECT run_date, is_trading_day, market_phase, source, checked_at
FROM trading.market_sessions WHERE run_date = '2026-05-25'::date;  -- KST 2026-05-26

-- 2. session_events INSERT 확인 (phase transition 기록)
SELECT * FROM trading.session_events
ORDER BY occurred_at DESC LIMIT 5;

-- 3. Session gate 정상 동작 (is_trading_day=true여야 함)
SELECT is_trading_day, market_phase, source, reason FROM trading.market_sessions
WHERE run_date = '2026-05-25'::date;
```

### ✅ 검증 기준 (Phase 1)
- [ ] `run_ops_scheduler --once` 가 exit code 0 으로 종료
- [ ] `market_sessions` 에 `run_date=2026-05-25` (KST 2026-05-26) 행이 `source=scheduler` 로 upsert 됨
- [ ] `is_trading_day=true` (화요일 정규 거래일)
- [ ] `market_phase` 가 시간대에 따라 적절히 설정됨
- [ ] `session_events` 에 phase transition 이벤트가 기록됨

### ⚠️ 주의사항
- KST 08:00 이전(Pre-market) 실행: market_phase는 `PRE_MARKET`
- KST 08:50 이후(Intraday) 실행: market_phase는 `OPEN` 예상
- 076 API 장운영정보 조회 실패 시 fallback 로직이 동작해야 함

---

## 4. Phase 2 — 스냅샷 Sync 검증 (KST 08:10–08:30)

### 4.1 단일 스냅샷 Sync
```bash
# 계좌별 단일 sync (dry-run 먼저)
python3 -m scripts.sync_kis_snapshots --account-ref 50186448 --dry-run --output json

# 실제 sync 실행
python3 -m scripts.sync_kis_snapshots --account-ref 50186448 --output json 2>&1 | tee logs/snapshot_sync_20260526.log
```

### 4.2 스냅샷 Sync Loop 단일 사이클
```bash
python3 -m scripts.run_snapshot_sync_loop --once --fetch-positions --output json 2>&1 | tee logs/snapshot_sync_loop_once_20260526.log
```

### 4.3 검증 항목
```sql
-- snapshot_sync_runs 생성 확인
SELECT * FROM trading.snapshot_sync_runs ORDER BY started_at DESC LIMIT 3;

-- position_snapshots 업데이트 확인
SELECT account_id, count(*) as cnt, max(snapshot_at) as latest
FROM trading.position_snapshots
GROUP BY account_id;

-- cash_balance_snapshots 업데이트 확인
SELECT * FROM trading.cash_balance_snapshots ORDER BY snapshot_at DESC LIMIT 3;
```

### ✅ 검증 기준 (Phase 2)
- [ ] KIS paper API 인증 성공 (access token 발급)
- [ ] `snapshot_sync_runs` 에 `status=completed` 행 생성
- [ ] `position_snapshots` 에 신규 행 추가 또는 기존 행 업데이트
- [ ] `cash_balance_snapshots` 에 신규 행 생성
- [ ] Dry-run 모드에서는 실제 DB 변경 없음

---

## 5. Phase 3 — Event Ingestion 검증 (KST 08:30–08:40)

### 5.1 Event Ingestion 단일 사이클
```bash
# Dry-run
python3 -m scripts.run_event_ingestion_loop --once --dry-run --output json 2>&1 | tee logs/event_ingestion_dryrun_20260526.log

# 실제 실행
python3 -m scripts.run_event_ingestion_loop --once --output json 2>&1 | tee logs/event_ingestion_once_20260526.log
```

### 5.2 검증 항목
```sql
-- external_events 수집 확인
SELECT source, event_type, count(*) as cnt
FROM trading.external_events
WHERE created_at >= NOW() - INTERVAL '1 hour'
GROUP BY source, event_type
ORDER BY cnt DESC;

-- T3 seeded events 수집 확인 (seeded_news source)
SELECT symbol, source, count(*) as cnt
FROM trading.external_events
WHERE source = 'seeded_news'
  AND created_at >= NOW() - INTERVAL '1 hour'
GROUP BY symbol;
```

### ✅ 검증 기준 (Phase 3)
- [ ] Event ingestion 정상 실행 (exit code 0)
- [ ] `external_events` 테이블에 신규 이벤트 INSERT 됨
- [ ] Per-source error isolation: 일부 source 실패해도 전체 중단되지 않음
- [ ] T3 news pipeline (NAVER + KIS disclosure) 에서 이벤트 수집됨

---

## 6. Phase 4 — Decision Loop (Dry-run) (KST 08:40–09:00)

### 6.1 Decision Loop 단일 사이클 (Dry-run)
```bash
# Dry-run: submit 없이 decision만 생성
python3 -m scripts.run_decision_loop --count 1 --dry-run --output json 2>&1 | tee logs/decision_loop_dryrun_20260526.log
```

### 6.2 검증 항목
```sql
-- trade_decisions 생성 확인
SELECT * FROM trading.trade_decisions
WHERE created_at >= NOW() - INTERVAL '30 minutes'
ORDER BY created_at DESC LIMIT 5;

-- decision_contexts 생성 확인
SELECT * FROM trading.decision_contexts
WHERE created_at >= NOW() - INTERVAL '30 minutes'
ORDER BY created_at DESC LIMIT 5;
```

### ✅ 검증 기준 (Phase 4)
- [ ] Decision loop 정상 실행 (exit code 0)
- [ ] `trade_decisions` 에 신규 decision 생성됨 (dry-run 모드)
- [ ] Universe composition 정상 동작 (symbol 목록 조회)
- [ ] Per-agent hard timeout(420초) 초과 시 graceful timeout 처리
- [ ] T3 seeded events 가 decision context에 포함됨
- [ ] `order_requests` 에 dry-run 모드에서는 INSERT 없음

---

## 7. Phase 5 — 실제 Submit (제한적, KST 09:00–09:30)

### 7.1 Orchestrator 단일 Submit
```bash
# run_orchestrator_once.py 로 단일 decision → submit
python3 -m scripts.run_orchestrator_once --submit --output json 2>&1 | tee logs/orchestrator_submit_20260526.log
```

### 7.2 Decision Loop 실제 Submit (count=1, 예산 소진)
```bash
# Decision loop: count=1, submit 활성화
python3 -m scripts.run_decision_loop --count 1 --submit --output json 2>&1 | tee logs/decision_loop_submit_20260526.log
```

### 7.3 검증 항목
```sql
-- order_requests INSERT 확인
SELECT order_request_id, side, order_type, status, requested_quantity, submitted_at
FROM trading.order_requests
WHERE created_at >= NOW() - INTERVAL '1 hour'
ORDER BY created_at DESC;

-- trade_decisions → order_request 연결 확인
SELECT td.trade_decision_id, td.symbol, td.side, td.decision_type,
       o_r.order_request_id, o_r.status as order_status
FROM trading.trade_decisions td
LEFT JOIN trading.order_requests o_r ON o_r.trade_decision_id = td.trade_decision_id
WHERE td.created_at >= NOW() - INTERVAL '1 hour'
ORDER BY td.created_at DESC;

-- submit budget 소진 확인 (예산: 1건)
SELECT run_date, total_submit_budget, used_submit_budget
FROM trading.market_sessions
WHERE run_date = '2026-05-25'::date;
```

### ✅ 검증 기준 (Phase 5)
- [ ] 실제 submit 경로 진입 성공 (broker API 호출)
- [ ] `order_requests` 에 신규 행 INSERT (`status=submitted` or `acknowledged`)
- [ ] Submit budget 차감 확인 (used_submit_budget 증가)
- [ ] `held_position` sell special lane: 별도 예산 체계 정상 동작
- [ ] Dry-run과 실제 submit의 로직 분기점 정상 동작

### ⚠️ 위험 관리
- **최대 1건 submit** 으로 제한 (기본 예산)
- Submit 후 즉시 post-submit sync 진입
- 예산 소진 시 추가 submit 차단 확인 (budget gate)
- Broker API 오류 발생 시 graceful error handling 확인

---

## 8. Phase 6 — Post-submit Sync (KST 09:30–09:50)

### 8.1 Post-submit Sync 단일 실행
```bash
python3 -m scripts.run_post_submit_sync_loop --once --output json 2>&1 | tee logs/post_submit_sync_once_20260526.log
```

### 8.2 검증 항목
```sql
-- order 상태 변화 확인 (submitted → acknowledged → filled/partial/rejected)
SELECT order_request_id, side, status, requested_quantity, submitted_at, updated_at
FROM trading.order_requests
WHERE created_at >= NOW() - INTERVAL '2 hours'
ORDER BY updated_at DESC;

-- broker_orders 상태 확인 (broker terminal 상태)
SELECT * FROM trading.broker_orders
WHERE created_at >= NOW() - INTERVAL '2 hours'
ORDER BY created_at DESC LIMIT 5;

-- snapshot refresh callback 정상 동작 확인
SELECT account_id, max(snapshot_at) as last_snapshot
FROM trading.position_snapshots
GROUP BY account_id;
```

### ✅ 검증 기준 (Phase 6)
- [ ] Post-submit sync 정상 실행 (exit code 0)
- [ ] Active order (`SUBMITTED`/`ACKNOWLEDGED`/`PARTIALLY_FILLED`) 상태 수렴
- [ ] Order 상태가 broker-terminal 상태와 일치
- [ ] Snapshot refresh callback 이 post-sync 후 호출됨
- [ ] 구조화된 cycle summary 출력 (orders/updated/filled/errors)

---

## 9. Phase 7 — Reconciliation (KST 09:50–10:10)

### 9.1 Reconciliation Worker 단일 실행
```bash
python3 -m scripts.run_reconciliation_worker --once --dry-run --output json 2>&1 | tee logs/reconciliation_dryrun_20260526.log

# 실제 실행 (reconcile_required 상태 해소)
python3 -m scripts.run_reconciliation_worker --once --output json 2>&1 | tee logs/reconciliation_once_20260526.log
```

### 9.2 검증 항목
```sql
-- reconciliation_runs 상태 확인
SELECT reconciliation_run_id, trigger_type, status, started_at, completed_at
FROM trading.reconciliation_runs
WHERE started_at >= NOW() - INTERVAL '2 hours'
ORDER BY started_at DESC;

-- 기존 failed reconciliation_runs 처리 확인 (is_active=false 인 것)
SELECT status, count(*) as cnt
FROM trading.reconciliation_runs
WHERE is_active = false
GROUP BY status;

-- order_blocking_locks 확인
SELECT * FROM trading.order_blocking_locks
WHERE locked_at >= NOW() - INTERVAL '2 hours'
ORDER BY locked_at DESC LIMIT 5;
```

### ✅ 검증 기준 (Phase 7)
- [ ] Reconciliation worker 정상 실행
- [ ] 기존 failed reconciliation run 재처리 시도
- [ ] 신규 reconciliation run 생성 및 처리
- [ ] Dry-run 모드에서는 실제 DB 변경 없음
- [ ] Blocking lock 정리 확인

---

## 10. Phase 8 — After-hours 모드 (KST 16:00–16:30)

### 10.1 After-hours 스냅샷 Sync
```bash
# After-hours 모드로 스냅샷 sync
python3 -m scripts.run_snapshot_sync_loop --once --after-hours --fetch-positions --output json 2>&1 | tee logs/snapshot_sync_afterhours_20260526.log
```

### 10.2 Recovery Batch (Post-submit)
```bash
# Recovery 모드 post-submit sync
python3 -m scripts.run_post_submit_sync_loop --once --recovery --output json 2>&1 | tee logs/post_submit_recovery_20260526.log
```

### 10.3 검증 항목
```sql
-- After-hours 스냅샷 확인 (cash balance만 업데이트될 수 있음)
SELECT account_id, max(snapshot_sync_run_id) as last_run
FROM trading.position_snapshots
GROUP BY account_id;

SELECT * FROM trading.cash_balance_snapshots
ORDER BY snapshot_at DESC LIMIT 3;

-- 최종 market_sessions 상태 확인
SELECT * FROM trading.market_sessions
WHERE run_date = '2026-05-25'::date
ORDER BY checked_at DESC LIMIT 1;
```

### ✅ 검증 기준 (Phase 8)
- [ ] After-hours 모드에서는 스냅샷 sync만 실행 (decision loop skip)
- [ ] Recovery batch 가 16:00 KST 이후 정상 실행
- [ ] Cash balance 스냅샷 업데이트 (position은 정규장 스냅샷 유지)
- [ ] Market phase 가 `after_hours` 로 전환

---

## 11. Phase 9 — 사후 검증 (KST 16:30–17:00)

### 11.1 종합 DB 상태 수집
```sql
-- 1. 전체 테이블 건수 변화
SELECT 'market_sessions' as tbl, count(*) FROM trading.market_sessions
UNION ALL SELECT 'session_events', count(*) FROM trading.session_events
UNION ALL SELECT 'order_requests', count(*) FROM trading.order_requests
UNION ALL SELECT 'reconciliation_runs', count(*) FROM trading.reconciliation_runs
UNION ALL SELECT 'position_snapshots', count(*) FROM trading.position_snapshots
UNION ALL SELECT 'cash_balance_snapshots', count(*) FROM trading.cash_balance_snapshots
UNION ALL SELECT 'external_events', count(*) FROM trading.external_events
UNION ALL SELECT 'trade_decisions', count(*) FROM trading.trade_decisions
UNION ALL SELECT 'snapshot_sync_runs', count(*) FROM trading.snapshot_sync_runs
UNION ALL SELECT 'broker_orders', count(*) FROM trading.broker_orders;

-- 2. 당일(order_requests) 주문 상태 분포
SELECT status, count(*), min(created_at) as first, max(created_at) as last
FROM trading.order_requests
WHERE created_at >= '2026-05-25 15:00:00+00'::timestamptz  -- KST 2026-05-26 00:00
GROUP BY status
ORDER BY status;

-- 3. 당일 reconciliation_runs 상태 분포
SELECT status, count(*)
FROM trading.reconciliation_runs
WHERE started_at >= '2026-05-25 15:00:00+00'::timestamptz
GROUP BY status;

-- 4. 최종 session_events (phase transition history)
SELECT * FROM trading.session_events
ORDER BY occurred_at ASC;
```

### 11.2 종합 API 검증
```bash
# Market sessions 최종 상태
curl -s http://localhost:8000/market-sessions/latest -H "Authorization: Bearer dev-token-123" | python3 -m json.tool

# Recent session events
curl -s "http://localhost:8000/market-sessions/events/recent?limit=10" -H "Authorization: Bearer dev-token-123" | python3 -m json.tool

# Reconciliation summary
curl -s "http://localhost:8000/reconciliation/summary?include_historical=true" -H "Authorization: Bearer dev-token-123" | python3 -m json.tool

# Account snapshots (가장 최근)
curl -s "http://localhost:8000/account-snapshots/latest?account_id=a44a02d1-7f32-5a62-99f7-235abeb58284" -H "Authorization: Bearer dev-token-123" | python3 -m json.tool
```

### ✅ 검증 기준 (Phase 9)
- [ ] 당일 order_requests 에 최소 1건의 submitted/acknowledged 상태 주문 존재
- [ ] session_events 에 phase transition 이력 존재
- [ ] Reconciliation runs 에 completed 상태 행 존재
- [ ] API endpoint 정상 응답
- [ ] 전체 파이프라인이 예외 없이 완료

---

## 12. 시간표 요약

| KST 시간 | Phase | 실행 내용 | 예상 소요 | 담당 |
|----------|-------|-----------|-----------|------|
| 07:30–07:50 | Phase 0 | 사전 준비 (헬스체크, DB 스냅샷) | 20분 | |
| 07:50–08:10 | Phase 1 | Ops Scheduler --once | 20분 | |
| 08:10–08:30 | Phase 2 | 스냅샷 Sync (sync_kis_snapshots + loop) | 20분 | |
| 08:30–08:40 | Phase 3 | Event Ingestion --once | 10분 | |
| 08:40–09:00 | Phase 4 | Decision Loop Dry-run | 20분 | |
| 09:00–09:30 | Phase 5 | 실제 Submit (제한적, 최대 1건) | 30분 | |
| 09:30–09:50 | Phase 6 | Post-submit Sync | 20분 | |
| 09:50–10:10 | Phase 7 | Reconciliation | 20분 | |
| 16:00–16:30 | Phase 8 | After-hours 모드 | 30분 | |
| 16:30–17:00 | Phase 9 | 사후 검증 (DB, API, 로그) | 30분 | |

---

## 13. 위험 관리

### 13.1 식별된 위험
| 위험 | 영향 | 완화 방안 |
|------|------|-----------|
| KIS paper API 인증 실패 | 모든 broker 의존 작업 불가 | Dry-run으로 대체, token cache 확인 |
| Submit budget 초과 | 추가 submit 차단 | 기본 예산 1건만 소진 |
| Reconciliation stuck (기존 failed run) | 신규 reconciliation block | 직접 SQL로 기존 run 정리 (`UPDATE ... SET is_active=false`) |
| DB migration 누락 | 특정 테이블/컬럼 없음 | `python3 -m agent_trading.db.migrations.run` 실행 |
| 076 API/163 WebSocket 장애 | Session gate fallback | Fallback 로직 동작 확인 |
| LLM API timeout | Decision loop 지연 | Per-agent hard timeout(420초) graceful 처리 확인 |

### 13.2 비상 복구
```bash
# 기존 reconciliation run 강제 종료
python3 -c "
import asyncio, os
from agent_trading.db.connection import create_pool, DatabaseConfig
dsn = os.environ.get('DATABASE_URL', 'postgresql://trading:trading@localhost:5432/trading')
async def fix():
    pool = await create_pool(DatabaseConfig(dsn=dsn))
    await pool.execute(\"UPDATE trading.reconciliation_runs SET is_active=false, status='failed' WHERE is_active=true AND completed_at IS NULL\")
    await pool.close()
asyncio.run(fix())
print('Done')
"

# Market session 수동 seed (fallback)
python3 -c "
import asyncio, os
from agent_trading.db.connection import create_pool, DatabaseConfig
from datetime import date
dsn = os.environ.get('DATABASE_URL', 'postgresql://trading:trading@localhost:5432/trading')
async def seed():
    pool = await create_pool(DatabaseConfig(dsn=dsn))
    await pool.execute(\"\"\"
        INSERT INTO trading.market_sessions (run_date, is_trading_day, source, reason)
        VALUES ('2026-05-25', true, 'manual', 'Fallback seed for 2026-05-26 KST')
        ON CONFLICT (run_date) DO NOTHING
    \"\"\")
    await pool.close()
asyncio.run(seed())
print('Seeded')
"
```

---

## 14. 성공/실패 기준

### 14.1 성공 기준
1. **모든 Phase 가 exit code 0 으로 완료**
2. **Session gate** 가 정규 거래일을 정확히 식별 (`is_trading_day=true`)
3. **스냅샷 Sync** 가 position + cash balance 를 정상 조회/저장
4. **Event ingestion** 이 외부 이벤트를 수집하여 `external_events` 에 저장
5. **Decision loop** 가 universe composition → AI decision → submit 경로를 정상 완료
6. **Submit budget** 이 정확히 차감되고 초과 시 차단됨
7. **Post-submit sync** 가 active order 상태를 broker-terminal 로 수렴
8. **Reconciliation** 이 pending run 을 정상 처리
9. **After-hours** 모드에서 snapshot-only 동작 + recovery batch 실행
10. **모든 API endpoint** 가 정상 응답

### 14.2 부분 성공
- 실제 submit 이 KIS paper API 정책/환경 문제로 실패하더라도, dry-run 까지의 경로가 정상 → **부분 성공**
- 일부 source 의 event ingestion 실패해도 다른 source 는 정상 → **부분 성공**
- Reconciliation 기존 failed run 처리 실패해도 신규 run 생성은 정상 → **부분 성공**

### 14.3 실패 기준
- Session gate 가 거래일을 오판 (`is_trading_day` 오류)
- 모든 broker API 호출이 인증/연결 실패
- Decision loop 의 per-agent hard timeout 이 모든 symbol 에서 만료
- DB connection pool 이 고갈되어 모든 작업 중단
- Docker 컨테이너 비정상 종료

---

## 15. DB 컬럼명 참조 (실행 시 쿼리 작성용)

| 테이블 | PK 컬럼 | 주요 상태 컬럼 |
|--------|---------|---------------|
| `trading.market_sessions` | `id` (BIGSERIAL) | `run_date`, `is_trading_day`, `market_phase`, `source`, `checked_at` |
| `trading.session_events` | `id` (BIGSERIAL) | `market_session_id`, `previous_phase`, `new_phase`, `trigger_source`, `occurred_at` |
| `trading.order_requests` | `order_request_id` (UUID) | `side`, `order_type`, `status`, `requested_quantity`, `submitted_at` |
| `trading.reconciliation_runs` | `reconciliation_run_id` (UUID) | `trigger_type`, `status`, `started_at`, `completed_at` |
| `trading.position_snapshots` | `position_snapshot_id` (UUID) | `account_id`, `quantity`, `snapshot_at`, `snapshot_sync_run_id` |
| `trading.cash_balance_snapshots` | (FK: account_id) | `account_id`, `snapshot_at`, `snapshot_sync_run_id` |
| `trading.snapshot_sync_runs` | (FK: multiple) | `account_id`, `status`, `started_at` |
| `trading.broker_accounts` | `broker_account_id` (UUID) | `account_ref`, `environment`, `status` |
| `trading.trade_decisions` | `trade_decision_id` (UUID) | `symbol`, `side`, `decision_type`, `status` |
| `trading.external_events` | (FK: multiple) | `source`, `event_type`, `symbol` |
| `trading.trading_sessions` | `trading_session_id` (UUID) | `session_date`, `status`, `opened_at` |
| `trading.order_blocking_locks` | (FK: multiple) | `symbol`, `side`, `reason`, `is_active` |
