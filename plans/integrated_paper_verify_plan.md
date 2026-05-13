# 통합 검증 계획 — Importance 정렬 + Paper Submit + Post-Submit Sync

> **목적**: 장중 paper submit 1회 실행으로 OpenDART importance 정렬, submit 경로, post-submit sync를 통합 검증
>
> **일시**: 2026-05-13 09:16 KST (수요일, 장중)
>
> **제약**: 코드 수정 금지, submit 1회, 동일 명령 반복 실행 금지

---

## 사전 조건 확인

| 항목 | 상태 | 근거 |
|------|------|------|
| 장중 여부 | ✅ **장중** | 09:16 KST 수요일 (08:30-15:30) |
| KIS_ENV | ✅ paper | .env 확인 완료 |
| KIS_PAPER_REST_RPS | ⚠️ **1** (2 권장) | .env: `KIS_PAPER_REST_RPS=1` |
| DB events with importance | **0건** | 모든 기존 이벤트는 코드 변경 전 수집 |
| symbol=005930 OpenDART events | **없음** | synthetic smoke test만 존재 |

---

## 실행 순서 (8단계)

### Step 0: 장중 재확인 + Env 로드
```bash
cd /workspace/agent_trading
TZ='Asia/Seoul' date '+%Y-%m-%d %H:%M:%S %A'
bash -c 'set -a && source .env && set +a && export KIS_SMOKE_PRICE=268500 && env | grep -E "KIS_ENV|KIS_APP_KEY|KIS_ACCOUNT_NO|KIS_PAPER_REST_RPS|KIS_SMOKE_PRICE|DEEPSEEK"'
```

### Step 1: Snapshot Sync
```bash
cd /workspace/agent_trading && bash -c 'set -a && source .env && set +a && export KIS_SMOKE_PRICE=268500 && python3 scripts/sync_kis_snapshots.py --all --env paper --format json'
```

### Step 2: OpenDART 이벤트 재수집 (중요)
**목적**: importance 분류 코드가 적용된 신규 이벤트를 DB에 적재

```bash
cd /workspace/agent_trading && bash -c 'set -a && source .env && set +a && python3 scripts/run_event_ingestion_loop.py --count 1'
```

**확인**: 수집된 이벤트 중 `metadata.importance`가 `"high"`, `"medium"`, `"low"`로 분류된 건이 있는지 확인

### Step 3: Importance 정렬 사전 확인 (DB 쿼리)
```sql
SELECT symbol, event_type, headline, metadata->>'importance' AS importance, published_at
FROM external_events
WHERE symbol='005930' AND metadata ? 'importance'
ORDER BY published_at DESC
LIMIT 20;
```

### Step 4: Dry-run 1회
```bash
cd /workspace/agent_trading && bash -c 'set -a && source .env && set +a && export KIS_SMOKE_PRICE=268500 && python3 scripts/run_orchestrator_once.py --dry-run --output text'
```

**기록 항목**:
- `decision_type` (APPROVE / HOLD / REJECT / WATCH)
- `sizing_quantity`
- `reason_codes`
- `recent_events` 상위 5건 (headline, importance, published_at)

### Step 5: Importance 정렬 검증
- `recent_events` 상위에 `importance=high` 공시가 우선 오는지 확인
- 같은 importance 내 최신순인지 확인
- importance가 없는 이벤트는 `"low"` fallback 처리 확인

### Step 6: Submit 1회
```bash
cd /workspace/agent_trading && bash -c 'set -a && source .env && set +a && export KIS_SMOKE_PRICE=268500 && python3 scripts/run_orchestrator_once.py --submit --output text'
```

**기록 항목**:
- `decision_context_id`
- `trade_decision_id`
- `order_intent_id`
- `order_request_id`
- broker native order ID(ODNO) 존재 여부
- business reject/error 여부

> `decision_type`이 `APPROVE`가 아니면 기록 후 중단 (재시도 금지)

### Step 7: Post-Submit Sync 1회
```bash
cd /workspace/agent_trading && bash -c 'set -a && source .env && set +a && python3 scripts/run_post_submit_sync_loop.py --once
```

**기록 항목**:
- sync 대상 수
- updated 수
- errors 수
- elapsed time

### Step 8: DB 상태 수렴 확인
```sql
-- order_requests
SELECT order_request_id, status, price, side, requested_quantity, created_at
FROM order_requests ORDER BY created_at DESC LIMIT 5;

-- broker_orders
SELECT broker_order_id, broker_native_order_id, broker_status, last_synced_at
FROM broker_orders ORDER BY submitted_at DESC LIMIT 5;

-- order_state_events count
SELECT COUNT(*) FROM order_state_events;
```

---

## 판정 기준

| 판정 | 조건 |
|------|------|
| ✅ **성공** | submit 성공 + ODNO 발급 + sync 실행 + `last_synced_at` 갱신 + `order_state_events` 기록 |
| ⚠️ **부분성공** | importance 정렬 또는 sync 일부만 확인 / submit 미성공 또는 AI가 APPROVE 미발생 |
| ❌ **실패** | 장중인데 실행 경로 자체 실패 / sync loop 실패 / 상태 추적 불가 |

---

## 리스크

1. **KIS_PAPER_REST_RPS=1** — snapshot sync에서 rate limit 도달 가능. sync에 실패하면 snapshot stale → submit 차단 가능.
2. **AI 확률성** — `decision_type=APPROVE`가 나오지 않으면 submit 불가 (과거 log상 APPROVE율 ~60%)
3. **기존 이벤트 importance 부재** — Step 2에서 신규 수집해도 005930 symbol에 importance 이벤트가 없으면 "low" fallback만 확인 가능
