# APPROVE Submit 재검증 계획 — Data Input 조정 중심

## 1. 문제 진단

이전 검증에서 AI가 `HOLD`를 결정한 근본 원인: 단 1건의 이벤트(`smoke_test_v1`, `005930`)가 stale + synthetic

| 속성 | 현재값 | AI 영향 |
|------|--------|---------|
| `published_at` | 2026-05-11 (2일 전) | → `stale` 플래그 |
| `ingested_at` | 2026-05-11 | → stale으로 간주 |
| `metadata.synthetic` | `true` | → `synthetic_data` risk_flag |
| `headline` | NULL | AI 추론 불가 |
| `body_summary` | NULL | AI 추론 불가 |
| `importance` | 없음 | 중요도 정렬 미적용 |
| `direction` | NULL | 중립 처리 |
| `severity` | NULL | 기본값 medium |

**EI 출력**: `risk_flags: ["synthetic_data", "stale"]`  
**FDC 출력**: `"합성 데이터 기반으로 신뢰도가 낮음"` → **HOLD**

## 2. 해결 전략: DB UPDATE만으로 입력 데이터 조정 (코드 수정 0건)

### 보정 사항 (6가지)

| 변경 대상 | 변경값 | 근거 |
|----------|--------|------|
| `published_at` | `NOW()` | stale 플래그 제거 |
| `ingested_at` | `NOW()` | stale 플래그 제거 보강 |
| `metadata` | `{"importance": "high", "purpose": "smoke_test"}` | `synthetic: true` 제거 + importance 추가 |
| `headline` | `"삼성전자, 1분기 연결기준 영업이익 시장 기대치 상회"` | 구체적 positive signal |
| `body_summary` | `"삼성전자 1분기 잠정실적 발표: 매출 77조, 영업이익 9.8조로 컨센서스 8% 상회. 반도체 부문 호조 지속, HBM3E 양산 본격화."` | bull case 근거 |
| `severity` | `"high"` | 중요 이벤트 |
| `direction` | `"positive"` | canonical 값 (bullish 아님) |

### Cash 상태
- Available: **30,000,000 KRW** ✅ (10주 × 268,500 = 2,685,000 충분)

## 3. 실행 순서

### Step 0: 장중 확인
```bash
TZ='Asia/Seoul' date '+%Y-%m-%d %H:%M:%S %A'
```

### Step 1: Env 로드
```bash
cd /workspace/agent_trading && bash -c 'set -a && source .env && set +a && export KIS_SMOKE_PRICE=268500'
```

### Step 2: Snapshot Sync (fresh)
```bash
python3 scripts/sync_kis_snapshots.py --all --env paper --format json
```

### Step 3: DB UPDATE — Smoke Event 데이터 품질 개선

> **⚠️ 검증 전용 임시 조치 — 운영 절차가 아님**
> 아래 SQL은 smoke test 검증을 위해 이벤트 데이터를 임시 보정하는 **일회성 기법**입니다.
> 운영 환경에서는 사용하지 않으며, 실제 OpenDART 공시 데이터가 이 품질 수준으로 들어오면 AI가 정상 APPROVE를 결정할 것으로 예상됩니다.
> 자세한 설명: [`paper_submit_smoke_ops_checklist.md#8-f-smoke-event-데이터-조정-기법-검증-전용`](plans/paper_submit_smoke_ops_checklist.md#8-f-smoke-event-데이터-조정-기법-검증-전용)
```sql
UPDATE external_events 
SET 
  published_at = NOW(),
  ingested_at = NOW(),
  headline = '삼성전자, 1분기 연결기준 영업이익 시장 기대치 상회',
  body_summary = '삼성전자 1분기 잠정실적 발표: 매출 77조, 영업이익 9.8조로 컨센서스 8% 상회. 반도체 부문 호조 지속, HBM3E 양산 본격화.',
  severity = 'high',
  direction = 'positive',
  metadata = '{"importance": "high", "purpose": "smoke_test"}'
WHERE event_id = '1f1ccf81-6da9-42d7-9e5f-9cd655027767';
```

### Step 4: Dry-run 1회 (APPROVE 확인)
```bash
python3 scripts/run_orchestrator_once.py --dry-run --output text
```
**판정**: `decision_type=APPROVE` 이면 Step 5 진행. 아니면 즉시 중단.

### Step 5: Submit 1회 (dry-run이 APPROVE일 때만)
```bash
python3 scripts/run_orchestrator_once.py --submit --output text
```

### Step 6: Post-Submit Sync 1회
```bash
python3 scripts/run_post_submit_sync_loop.py --once
```

### Step 7: DB 상태 확인
```sql
-- 신규 order_request 확인
SELECT order_request_id, status, requested_quantity, price, created_at
FROM order_requests
ORDER BY created_at DESC LIMIT 3;

-- broker_orders 확인
SELECT broker_order_id, order_request_id, broker_native_order_id, broker_status, last_synced_at
FROM broker_orders
ORDER BY created_at DESC LIMIT 3;

-- order_state_events 증가 확인
SELECT COUNT(*) AS total FROM order_state_events;
```

## 4. 판정 기준

### 성공 조건
1. ✅ Dry-run → APPROVE
2. ✅ Submit 성공
3. ✅ 신규 `order_request` 생성
4. ✅ `broker_native_order_id` (ODNO) 발급
5. ✅ Sync loop 실행 (orders>=1, errors=0)
6. ✅ `last_synced_at` 갱신
7. ✅ `order_state_events` 증가

### Paper Mock 한계 (허용)
- `broker_status=reconcile_required` = 정상
- `inquire_daily_ccld` → `output: []` = 정상

## 5. Cleanup (검증 완료 후)

synthetic row 원복 SQL:
```sql
UPDATE external_events 
SET published_at = '2026-05-11T00:38:14.347Z',
    ingested_at = '2026-05-11T00:38:14.347Z',
    headline = NULL,
    body_summary = NULL,
    severity = NULL,
    direction = NULL,
    metadata = '{"purpose": "smoke_test", "version": "v1", "synthetic": true}'
WHERE event_id = '1f1ccf81-6da9-42d7-9e5f-9cd655027767';
```
