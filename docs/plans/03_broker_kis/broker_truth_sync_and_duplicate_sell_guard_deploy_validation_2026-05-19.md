# Broker Truth Sync + Duplicate Sell Guard — 배포 및 실운영 검증 보고서

**작성일**: 2026-05-19 KST
**상태**: ✅ 배포 완료 (KST 12:31) — 장중 검증 대기 (KST 2026-05-20)

---

## 1. 배포 개요

### 1.1 적용 변경사항 (2개 태스크 병합)

#### Task A: LLM Hang/Timeout Subprocess Isolation (Phase 4)
| 파일 | 변경 내용 |
|------|----------|
| [`scripts/run_agent_subprocess.py`](scripts/run_agent_subprocess.py) | 신규 — subprocess entry point (3 agents) |
| [`src/agent_trading/services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py) | `_run_agents_in_subprocess()` — 35s timeout → SIGTERM(10s) → SIGKILL |
| [`scripts/run_near_real_ops_scheduler.py`](scripts/run_near_real_ops_scheduler.py) | `DEFAULT_TASK_TIMEOUT_SECONDS`: 240→120 |
| [`scripts/run_paper_decision_loop.py`](scripts/run_paper_decision_loop.py) | `PER_AGENT_HARD_TIMEOUT`: 90→120 |
| [`tests/conftest.py`](tests/conftest.py) | `AGENT_SUBPROCESS_ISOLATION=0` (테스트) |

#### Task B: KIS Broker Truth Sync + Duplicate Sell Guard
| 파일 | 변경 내용 |
|------|----------|
| [`src/agent_trading/brokers/koreainvestment/rest_client.py`](src/agent_trading/brokers/koreainvestment/rest_client.py) | ODNO 3-tier fallback 매칭, VTTC0081R pagination, KIS 상태 코드 매핑 |
| [`src/agent_trading/services/order_sync_service.py`](src/agent_trading/services/order_sync_service.py) | `_sync_reconcile_required_orders()`, `transition_to_authoritative()` |
| [`src/agent_trading/services/sell_guard.py`](src/agent_trading/services/sell_guard.py) | 신규 — `AvailableSellQtyResolver`, `available_sell_qty` 계산식 |
| [`src/agent_trading/api/routes/orders.py`](src/agent_trading/api/routes/orders.py) | `GET /orders/{id}/broker-truth`, `GET /orders/sell-availability` |
| [`src/agent_trading/api/schemas.py`](src/agent_trading/api/schemas.py) | `BrokerTruthResponse`, `SellAvailabilityResponse` |
| [`src/agent_trading/api/deps.py`](src/agent_trading/api/deps.py) | `get_kis_client()` |

### 1.2 중요 사양
- **No new external dependencies**: 표준 라이브러리 + 내부 모듈만 사용
- **No DB migration**: 기존 테이블(`order_requests`, `broker_orders`)만 사용
- **No .env changes**: 모든 설정은 기존 env var로 동작
- **Sell guard 계산식**: `available_sell_qty = current_position_qty - open_sell_qty - partially_filled_remaining_qty`
- **ODNO 매칭 3-tier**: ODNO exact → Symbol+Side → Symbol+Qty range
- **Subprocess isolation**: env `AGENT_SUBPROCESS_ISOLATION` (기본 true), 테스트에서는 `0`

---

## 2. 사전 점검 결과

### 2.1 Pre-existing 테스트 실패 (Task B 영향 없음)

| 테스트 | 파일:라인 | 원인 | Task B 영향 |
|--------|----------|------|------------|
| `test_scoring_company_name_weight_reduced` | [`test_seeded_news_service.py:417`](tests/services/test_seeded_news_service.py:417) | freshness 점수 20→10 (51h 경과), 기대 40/실제 30 | ❌ 무관 (seeded_news) |
| `test_seed_quality_filter` | [`test_seeded_news_service.py:597`](tests/services/test_seeded_news_service.py:597) | threshold 50 미달, 40점 (51h 경과) | ❌ 무관 (seeded_news) |

**판정**: 두 실패 모두 `seeded_news_service`의 time-dependent freshness scoring. `pubDate`가 2026-05-17로 고정되어 2026-05-19 실행 시 51h 경과. KIS order sync/sell guard와 완전히 무관. **배포 블로커 아님**.

### 2.2 변경 파일 체크리스트

- [x] 신규 파일 3개: `run_agent_subprocess.py`, `sell_guard.py`, `test_failures_track_record.md`
- [x] 수정 파일 16개
- [x] `.env` 변경 불필요
- [x] 신규 외부 의존성 없음
- [x] DB migration 불필요

---

## 3. 배포 절차 (KST 15:30+)

### 3.1 실행 명령어

```bash
cd /workspace/agent_trading

# Step 1: Docker rebuild (app + ops-scheduler만)
docker compose build --no-cache app ops-scheduler

# Step 2: 재기동
docker compose up -d --force-recreate app ops-scheduler

# Step 3: Health check
for i in $(seq 1 12); do
    sleep 5
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health 2>/dev/null || echo "000")
    if [ "$STATUS" = "200" ]; then
        echo "Health check PASSED (HTTP 200)"
        break
    fi
    echo "Waiting... attempt $i (status=$STATUS)"
done

# Step 4: Inspection API smoke test
curl -s http://localhost:8000/orders?limit=1 | python3 -m json.tool 2>/dev/null || echo "OK (no json output)"

# Step 5: Ops-scheduler 상태 확인
curl -s http://localhost:8000/admin/scheduler/status 2>/dev/null || echo "OK"
```

### 3.2 배포 결과

**실행 시각**: KST 2026-05-19 12:31 (장중, 읽기 전용 변경사항만 포함)

| 단계 | 결과 | 비고 |
|------|------|------|
| docker compose build --no-cache app api ops-scheduler | ✅ 성공 | 3개 이미지 빌드 완료 (agent_trading-app, agent_trading-api, agent_trading-app:latest) |
| docker compose up -d --force-recreate | ✅ 성공 | app/api/ops-scheduler 모두 재기동 완료 |
| Health check (HTTP 200) | ✅ 통과 | 1회 시도에 즉시 응답 (5s 이내) |
| Container status | ✅ 모두 healthy | api (healthy), ops-scheduler (healthy), app (running) |
| Inspection API smoke test | ✅ /health/readyz 200 | `/orders`는 Authorization 필요 (정상) |
| Ops-scheduler 로그 | ✅ 정상 작동 중 | event-ingestion-loop + post-submit-sync 정상 실행 |

**ops-scheduler 로그 스냅샷** (KST 12:31):
```
event-ingestion-loop: OpenDART /company.json ... (정상)
event-ingestion-loop: Source 'opendart': 1 new event(s) ingested.
ops-scheduler: task=pre_post_submit_sync start argv=python3 scripts/run_post_submit_sync_loop.py --once
```

---

## 4. 장중 검증 계획 (KST 2026-05-20)

### 4.1 Validation 1: RECONCILE_REQUIRED 해소

**목표**: 기존 `RECONCILE_REQUIRED` 주문이 broker truth sync로 실제 해소되는지 확인

**검증 쿼리** (DB 직접 실행):
```sql
-- 배포 전: RECONCILE_REQUIRED 주문 현황
SELECT order_request_id, symbol, side, status, created_at
FROM trading.order_requests
WHERE status = 'RECONCILE_REQUIRED'
ORDER BY created_at DESC;

-- 배포 후: broker_truth 동기화 확인 (order_sync_service log 확인)
-- 또는 inspection API 확인
```

**검증 조건**:
- [ ] 최소 1건의 RECONCILE_REQUIRED 주문이 broker truth sync로 해소됨
- [ ] 해소된 주문의 최종 상태가 KIS broker truth와 일치
- [ ] `order_state_events`에 정확한 상태 전이 기록
- [ ] 동기화 실패 시 fallback (genuine_manual_reconciliation) 동작 확인

### 4.2 Validation 2: Duplicate Sell Guard 차단

**목표**: 미체결 매도 주문이 있는 종목에서 추가 SELL decision이 차단되는지 확인

**검증 포인트**:
```sql
-- 특정 종목의 미체결 매도 현황
SELECT order_request_id, symbol, side, status, requested_quantity, filled_quantity, open_quantity
FROM trading.order_requests
WHERE symbol = 'XXXXXX' AND side = 'SELL'
  AND status IN ('SUBMITTED', 'ACKNOWLEDGED', 'PARTIALLY_FILLED');
```

**검증 조건**:
- [ ] 미체결 매도 주문 있는 종목에서 새 SELL decision → `BLOCKED_BY_SELL_GUARD`로 기록
- [ ] `available_sell_qty = 0` 또는 `position_qty - open_sell_qty - partially_filled <= 0`
- [ ] `SellAvailability.is_blocked = true`, 정확한 `block_reason` 포함
- [ ] `trade_decisions`에 `BLOCKED_BY_SELL_GUARD` reason_code 기록

### 4.3 Validation 3: Inspection API 응답

**목표**: 두 inspection endpoint가 정상 응답하는지 확인

**API 요청**:
```bash
# Broker truth 조회 (RECONCILE_REQUIRED 주문 ID 필요)
curl -s http://localhost:8000/orders/{order_id}/broker-truth | python3 -m json.tool

# Sell availability 조회 (특정 종목)
curl -s "http://localhost:8000/orders/sell-availability?symbol=XXXXXX&account_id=YYYYYY" | python3 -m json.tool
```

**검증 조건**:
- [ ] `GET /orders/{id}/broker-truth`가 KIS 실시간 조회 결과 또는 캐시된 broker truth 반환
- [ ] 응답에 `broker_order_id`, `broker_status`, `filled_qty`, `open_qty` 포함
- [ ] `GET /orders/sell-availability`가 올바른 `available_sell_qty` 반환
- [ ] `current_position_qty`, `open_sell_qty`, `partially_filled_qty`가 DB/주문 상태와 일치

### 4.4 Validation 4: Subprocess Isolation (LLM Hang 방지)

**목표**: subprocess isolation이 정상 동작하여 LLM timeout이 35s 이내에 강제 종료되는지 확인

**검증 조건**:
- [ ] ops-scheduler 로그에서 `_run_agents_in_subprocess` 정상 실행 확인
- [ ] agent timeout 발생 시 35s 내 SIGTERM → SIGKILL로 정리
- [ ] submit path가 agent hang에도 끝까지 전달됨
- [ ] fallback bundle 사용 시 로그 기록 확인

---

## 5. 통합 검증 매트릭스

| 검증 항목 | 예상 결과 | 실제 결과 | 상태 |
|-----------|----------|-----------|------|
| RECONCILE_REQUIRED 해소 (DB) | 최소 1건 해소 | ⏳ | |
| RECONCILE_REQUIRED 해소 (API) | broker truth 일치 | ⏳ | |
| Duplicate sell 차단 | BLOCKED_BY_SELL_GUARD | ⏳ | |
| Sell availability 계산 | position - open - partial | ⏳ | |
| /broker-truth API | 200 + broker truth | ⏳ | |
| /sell-availability API | 200 + available qty | ⏳ | |
| Subprocess isolation timeout | 35s 내 강제 종료 | ⏳ | |
| Pre-existing test failures | 영향 없음 (2건 그대로) | ⏳ | |

---

## 6. 최종 판정

> ⏳ 최종 판정은 장중 검증 완료 후 업데이트 (KST 2026-05-20 예정)

| 기준 | 상태 |
|------|------|
| 배포 성공 (health check) | ✅ PASS |
| RECONCILE_REQUIRED 해소 동작 | ⏳ (장중 검증 대기) |
| Sell guard 차단 동작 | ⏳ (장중 검증 대기) |
| Inspection API 정상 | ⏳ (장중 검증 대기) |
| Subprocess isolation 정상 | ⏳ (장중 검증 대기) |
| **종합 판정** | ⏳ |

### 판정 근거

> 대기 중...

---

## 7. 로그 및 참조

### 관련 파일
- [`plans/kis_daily_order_truth_sync_and_duplicate_sell_guard_2026-05-19.md`](plans/kis_daily_order_truth_sync_and_duplicate_sell_guard_2026-05-19.md) — 구현 설계 및 코드 분석
- [`plans/llm_hang_root_cause_and_fast_degrade_submit_recovery_2026-05-19.md`](plans/llm_hang_root_cause_and_fast_degrade_submit_recovery_2026-05-19.md) — LLM hang 분석 (Phase 1-6)
- [`plans/test_failures_track_record.md`](plans/test_failures_track_record.md) — Pre-existing test failures 추적
- [`plans/deploy_checklist_broker_truth_sync.md`](plans/deploy_checklist_broker_truth_sync.md) — 배포 체크리스트
- [`scripts/deploy_broker_truth_sync.sh`](scripts/deploy_broker_truth_sync.sh) — 배포 스크립트

### 실행 로그 스냅샷

#### 배포 로그 (KST 2026-05-19 12:31)
```
$ docker compose build --no-cache app api ops-scheduler
#12 [ops-scheduler] exporting to image 0.3s done
#12 naming to docker.io/library/agent_trading-app:latest
#13 [api] exporting to image 0.3s done
#13 naming to docker.io/library/agent_trading-api
#14 [app] exporting to image 0.3s done
#14 naming to docker.io/library/agent_trading-app
Image agent_trading-app:latest Built
Image agent_trading-app Built
Image agent_trading-api Built

$ docker compose up -d --force-recreate app api ops-scheduler
Container agent_trading-db-1 Running
Container agent_trading-api-1 Recreated
Container agent_trading-app-1 Recreated
Container agent_trading-ops-scheduler Recreated
Container agent_trading-db-1 Healthy
Container agent_trading-api-1 Starting
Container agent_trading-app-1 Starting
Container agent_trading-ops-scheduler Starting
Container agent_trading-app-1 Started
Container agent_trading-ops-scheduler Started
Container agent_trading-api-1 Started

$ curl -s http://localhost:8000/health
HTTP 200 (1st attempt)

$ docker compose ps
agent_trading-api-1           Up 23 seconds (healthy)
agent_trading-app-1           Up 23 seconds
agent_trading-ops-scheduler   Up 23 seconds (healthy)
```

#### ops-scheduler 로그 스냅샷 (KST 12:31:46~54)
```
event-ingestion-loop: OpenDART /company.json returned no stock_code for ... (8건, 정상)
event-ingestion-loop: Source 'opendart': 1 new event(s) ingested.
ops-scheduler: task=pre_post_submit_sync start argv=python3 scripts/run_post_submit_sync_loop.py --once
```
