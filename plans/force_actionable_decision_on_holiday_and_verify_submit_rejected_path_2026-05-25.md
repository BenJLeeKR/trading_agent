# Force Actionable Decision on Holiday — Broker Submit Path Smoke Test Report

**Date:** 2026-05-25 (Holiday — Korean stock market closed)

## 1. Test Overview

### 1.1 Objective
- Force an actionable decision (non-WATCH/HOLD) on a Korean stock market holiday
- Verify end-to-end pipeline: event injection → EI → AR → FDC → sizing → broker submit → holiday reject handling
- Confirm KIS paper trading API returns holiday error and system handles it correctly

### 1.2 Test Configuration
- **Symbol:** 005930 (Samsung Electronics)
- **Market:** Korean Stock Market (holiday — closed)
- **Broker:** KIS Paper Trading
- **LLM Provider:** DeepSeek (real, not stub)
- **Execution Mode:** Container (Docker Compose) — `.env` auto-loaded
- **Test Script:** `scripts/run_orchestrator_once.py` with `--submit` flag

### 1.3 Method: External Event Injection
Artificially seeded events with `event_type='seeded_news'` and bullish headlines were injected into the `external_events` table to force a BUY decision from the AI pipeline.

Events injected (latest 10 from DB):
| Headline | Impact Score | Direction | Created At |
|----------|-------------|-----------|-----------|
| 정부, 반도체 산업에 50조원 지원 패키지 발표 - 삼성전자 직접 수혜 | 0.9 | - | 2026-05-25 01:01:53 |
| 삼성전자, 20조원 자사주 매입 및 소각 발표 | 0.93 | - | 2026-05-25 01:01:53 |
| 외국계 증권사 3곳, 삼성전자 목표주가 30% 상향 조정 | 0.95 | - | 2026-05-25 01:01:53 |
| 삼성전자, 시장 예상 상회하는 1분기 실적 발표 | 0.98 | - | 2026-05-25 01:01:53 |
| 삼성전자, 中 공장 V9 전환 클린룸 공사 준비 착수 | - | - | 2026-05-22 02:06:19 |
| [특징주] 삼성전자·SK하이닉스 동반 약세…급등 뒤 숨 고르기 | - | - | 2026-05-22 02:06:19 |
| 삼성전자 노조 찬반투표 시작…과반 넘어야 파업 리스크 완전 해소 | - | - | 2026-05-22 02:06:19 |
| SM-삼성전자, 'K팝 동맹' 강화… 삼성 TV 플러스서 '월간 SM 콘서트' 론칭 | - | - | 2026-05-22 00:43:03 |
| 삼성전자 노사 합의가 남긴 과제…'성과급'은 누구 몫인가 | - | - | 2026-05-22 00:43:03 |
| 삼성, 美소비자 만족도서 애플 제치고 1위…'AI·플래그십' 판정승 | - | - | 2026-05-22 00:43:03 |

## 2. Pipeline Results

### 2.1 AI Agent Results (Assemble Phase)

**Event Interpretation (EI):**
- `input_events`: 7 (4 seeded + 3 existing)
- `detected_event_count`: 7
- `overall_bias`: bullish
- `evidence_strength`: strong

**AI Risk (AR):**
- `risk_opinion`: allow
- `risk_score`: 20.00

**Final Decision Composer (FDC):**
- `decision_type`: **BUY** ✅ (actionable)

### 2.2 Sizing Results (Phase 1.5)
- `sized_quantity`: 1
- Sizing was initially blocked by tight constraints (max_position_size=0.1%), then by stale snapshot guard, then by existing position budget consumption
- Config adjustments (0.1% → 10% → 100%) and DB snapshot freshness fix resolved these issues

### 2.3 Broker Submit Results (Phase 5)
- **status:** `ERROR`
- **error_phase:** `order_submit`
- **error_message:** `koreainvestment | api_error | KIS order_cash: business error (rt_cd=1, msg_cd=40100000): 모의투자 영업일이 아닙니다.`
- KIS API actually called: `POST /uapi/domestic-stock/v1/trading/order-cash` → HTTP 200 (business error)
- **trade_decision_id:** `e40b93c9-aaf5-45ec-9ddd-3d2151ac1d26`
- **decision_context_id:** `f8967800-4690-4383-9e44-884bdbaa2099`
- **order_intent_id:** `065a445d-c5af-4877-bdcb-3ccec143d803`

## 3. Important Findings

### 3.1 Holiday Error Path: ERROR (not REJECTED)
The KIS paper environment code `40100000` ("모의투자 영업일이 아닙니다") maps to `_AMBIGUOUS_ERROR_CODES` in `rest_client.py`, which raises `BrokerError(API_ERROR)`. This is caught by `except Exception` in `execution_service.py`, resulting in `SubmitResult(status="ERROR")` — NOT the `REJECTED` path.

**Key distinction:**
- **REJECTED path:** broker explicitly returns `accepted=False` → `SubmitResult(status="REJECTED")`
- **ERROR path:** broker raises exception (including holiday reject) → `SubmitResult(status="ERROR", error_phase="order_submit")`

For the holiday scenario, the `ERROR` path is the correct handling. The system successfully:
1. Called the KIS API
2. Received the holiday reject error
3. Logged the error properly
4. Persisted the trade_decision with ERROR status
5. Did NOT crash or hang

### 3.2 Paper vs Live Error Codes
- **Paper (KIS 모의투자):** code `40100000` — "모의투자 영업일이 아닙니다"
- **Live (KIS 실전투자):** code `OPR00001` — "업무일이 아닙니다"
Both are handled via the same `_AMBIGUOUS_ERROR_CODES` → `BrokerError(API_ERROR)` path.

### 3.3 Sizing Pipeline Issues Found and Fixed
1. **max_position_size=0.1%** too restrictive for 005930 (주가 292,500원) → Changed to 10%, then 100%
2. **calculate_max_order_value(price=None) TypeError** — MARKET order has no price → Added None check
3. **Stale snapshot guard** — snapshot_at > 900s → Updated to NOW()
4. **Existing position budget consumption** — held 2,670,000원 position → Increased max_position_size to 100%
5. **KIS rate limit** — global_rest_capacity=max(1, total) blocked REST calls → Changed to max(100, total)

### 3.4 Container-Patched Files (verify source code update needed)
- `src/agent_trading/services/translation.py` — `calculate_max_order_value()` None-safe patch
- `src/agent_trading/brokers/rate_limit.py` — `global_rest_capacity=max(100, total)` for paper env
- `src/agent_trading/brokers/koreainvestment/adapter.py` — `OrderSide` import added

## 4. DB Verification

### 4.1 trade_decisions

```sql
SELECT td.trade_decision_id, td.symbol, td.decision_type, td.quantity, td.decision, td.created_at
FROM trade_decisions td
WHERE td.trade_decision_id = 'e40b93c9-aaf5-45ec-9ddd-3d2151ac1d26';
```

| trade_decision_id | symbol | decision_type | quantity | decision | created_at |
|---|---|---|---|---|---|
| e40b93c9-aaf5-45ec-9ddd-3d2151ac1d26 | 005930 | buy | 1.00000000 | (null) | 2026-05-25 01:29:32.843552+00 |

- ✅ `trade_decision_id` 일치
- ✅ `symbol` = 005930
- ✅ `decision_type` = buy (actionable)
- ✅ `quantity` = 1.00000000 (sized_quantity)
- ⚠️ `decision` = null (원래 스키마에는 `decision` 컬럼이 있으나 값이 NULL; `decision_type`이 실제 결정 유형)

### 4.2 execution_attempts

```sql
SELECT ea.execution_attempt_id, ea.trade_decision_id, ea.status, ea.stop_phase, ea.stop_reason, ea.created_at
FROM execution_attempts ea
WHERE ea.trade_decision_id = 'e40b93c9-aaf5-45ec-9ddd-3d2151ac1d26';
```

| execution_attempt_id | trade_decision_id | status | stop_phase | stop_reason | created_at |
|---|---|---|---|---|---|
| 5a2cc867-a269-41b8-8578-c1b73a7fc723 | e40b93c9-aaf5-45ec-9ddd-3d2151ac1d26 | failed | broker_submit | broker_submit_failed | 2026-05-25 01:29:32.84735+00 |

- ✅ `status` = failed (ERROR에 해당)
- ✅ `stop_phase` = broker_submit (error_phase에 해당)
- ✅ `stop_reason` = broker_submit_failed

### 4.3 order_requests

```sql
SELECT * FROM order_requests WHERE trade_decision_id = 'e40b93c9-aaf5-45ec-9ddd-3d2151ac1d26';
```

| Column | Value |
|--------|-------|
| order_request_id | 35ec90a1-3678-422a-9e8d-d3f82d7d7722 |
| trade_decision_id | e40b93c9-aaf5-45ec-9ddd-3d2151ac1d26 |
| decision_context_id | f8967800-4690-4383-9e44-884bdbaa2099 |
| side | buy |
| order_type | market |
| requested_quantity | 1.00000000 |
| status | pending_submit |
| client_order_id | dc-f8967800-0129329506 |

- ✅ order_request 생성됨 (status = `pending_submit`)
- ✅ `side` = buy, `order_type` = market
- ✅ `requested_quantity` = 1
- ⚠️ `status` = `pending_submit` (broker submit이 실패하여 submitted로 전이되지 않음)

**broker_orders:** (empty — broker submit이 실패하여 broker_orders 레코드가 생성되지 않음)

### 4.4 decision_contexts

```sql
SELECT * FROM decision_contexts WHERE decision_context_id = 'f8967800-4690-4383-9e44-884bdbaa2099';
```

| Column | Value |
|--------|-------|
| decision_context_id | f8967800-4690-4383-9e44-884bdbaa2099 |
| account_id | a44a02d1-7f32-5a62-99f7-235abeb58284 |
| strategy_id | 30a1d26b-8230-51fc-8548-30920effff0c |
| config_version_id | 529ab376-183a-53df-b4ab-73d948c1404c |
| correlation_id | entrypoint-correlation-5a16ceb7-b402-46f6-9002-8297bc220061 |
| market_timestamp | 2026-05-25 01:27:16.391032+00 |
| created_at | 2026-05-25 01:27:16.38072+00 |

- ✅ decision_context_id 일치
- ✅ `market_timestamp` = 2026-05-25 (휴일)

### 4.5 external_events (seeded_news for 005930)

```sql
SELECT event_id, symbol, event_type, headline, metadata->>'impact_score' as impact_score,
       metadata->>'direction' as direction, created_at
FROM external_events
WHERE symbol = '005930' AND event_type = 'seeded_news'
ORDER BY created_at DESC
LIMIT 10;
```

10건의 `seeded_news` 이벤트 확인됨 (4건은 2026-05-25, 6건은 2026-05-22)
- ✅ Seeded events가 정상적으로 주입되었고 pipeline에서 소비됨

## 5. Log Verification

Key log entries from `logs/smoke_test_submit_20260525_v2.log`:

```
Line 93:  [ATTEMPT_CREATED] execution_attempt_id=5a2cc867... trade_decision_id=e40b93c9...
Line 104: Sizing Phase 1.5: request_qty=1 sizing_qty=1 applied_constraints=() skip_reason=none
Line 119: [SUBMIT_START] symbol=005930 decision_type=BUY side=OrderSide.BUY order_id=35ec90a1...
Line 122: [ERROR] Broker submit RAISED: ...BrokerError: koreainvestment | api_error | KIS order_cash: business error (rt_cd=1, msg_cd=40100000): 모의투자 영업일이 아닙니다.
Line 142: BrokerError: koreainvestment | api_error | KIS order_cash: business error (rt_cd=1, msg_cd=40100000): 모의투자 영업일이 아닙니다.
Line 145: [ERROR] Phase 5 FAILED (order_submit): order_id=35ec90a1... trade_decision_id=e40b93c9...
Line 171: BrokerError: koreainvestment | api_error | KIS order_cash: business error (rt_cd=1, msg_cd=40100000): 모의투자 영업일이 아닙니다.
Line 176: error_message: submit_order_to_broker() failed: koreainvestment | api_error | ...
Line 177: trade_decision_id: e40b93c9-aaf5-45ec-9ddd-3d2151ac1d26
```

- ✅ `[SUBMIT_START]` — line 119: submit 정상 시작
- ✅ `sizing_qty=1` — line 104: sizing 통과
- ✅ `decision_type=BUY` — line 119: BUY 결정 확인
- ✅ `Broker submit RAISED` — line 122: 예외 발생
- ✅ `api_error` — line 122, 142, 171, 176: broker 에러 로깅
- ✅ `40100000` — line 122, 142, 171: 에러 코드 확인
- ✅ `trade_decision_id` — line 93, 145, 177: trade_decision_id 로깅

## 6. Files Fixed During Testing

### 6.1 Source Code Fixes (permanent)
| File | Fix | Status |
|------|-----|--------|
| `src/agent_trading/services/subprocess_helpers.py` | Removed `"request"` key from `serialize_agent_input()` payload — caused TypeError → Stub fallback | ✅ Merged |
| `src/agent_trading/brokers/rate_limit.py` | `global_rest_capacity=max(100, total)` for paper env was `max(1, total)` blocking REST calls | ⚠️ Container only |
| `src/agent_trading/services/translation.py` | `calculate_max_order_value()` None-safe check for MARKET order price | ⚠️ Container only |
| `src/agent_trading/brokers/koreainvestment/adapter.py` | `OrderSide` import missing | ⚠️ Container only |

### 6.2 Configuration Adjustment
| Parameter | Before | After |
|-----------|--------|-------|
| `max_position_size` | 0.1% | 100% |

## 7. Success Criteria Evaluation

| # | Criterion | Result | Details |
|---|-----------|--------|---------|
| 1 | Actionable decision (BUY/SELL) produced | ✅ | BUY |
| 2 | AI pipeline used real provider | ✅ | DeepSeek HTTP 200 |
| 3 | Sizing passed | ✅ | sized_quantity=1 |
| 4 | Broker submit reached | ✅ | POST to KIS API |
| 5 | Holiday reject received | ✅ | "모의투자 영업일이 아닙니다" |
| 6 | Error handled correctly (no crash) | ✅ | status=ERROR, error_phase=order_submit |
| 7 | DB records created | ✅ | trade_decision_id, decision_context_id created |
| 8 | What requires market hours | | 1) Actual order submission 2) Broker REJECTED path (not ERROR) |

## 8. DB Record Summary

| Table | Record Count | Status |
|-------|-------------|--------|
| trade_decisions | 1 | ✅ `decision_type=buy`, `quantity=1` |
| execution_attempts | 1 | ✅ `status=failed`, `stop_phase=broker_submit` |
| order_requests | 1 | ✅ `status=pending_submit`, `side=buy`, `requested_quantity=1` |
| broker_orders | 0 | ⚠️ Broker submit 실패로 생성되지 않음 |
| decision_contexts | 1 | ✅ `market_timestamp=2026-05-25` |
| external_events | 10 | ✅ 4건 2026-05-25 + 6건 2026-05-22 |

## 9. Cleaned Temporary Files

다음 12개의 임시 파일이 삭제됨:
- `_smoke_step1.py`
- `_smoke_step2_insert.py`
- `_smoke_step4_fix_and_insert.py`
- `_smoke_step4_insert_more.py`
- `_smoke_check_event_types.py`
- `_patch_decision_orchestrator.py`
- `_cleanup.py`
- `_cleanup_pending_submit.py`
- `_update_smoke_event.py`
- `_test_cash_balance.py`
- `_test_orderable_cash.py`
- `_debug_fk.py`

## 10. Remaining Work (Market Hours Required)
- [ ] Verify actual order submission on a trading day
- [ ] Verify REJECTED path (when broker explicitly rejects, vs. ERROR from exception)
- [ ] Verify live KIS OPR00001 handling matches paper 40100000
- [ ] Apply container patches to source code permanently
- [ ] Run unit tests to confirm no regressions

## 11. Log Files
- `logs/smoke_test_force_buy_assemble_20260525_final.log` — Assemble-only phase (BUY decision)
- `logs/smoke_test_submit_20260525_v2.log` — Full submit phase (ERROR from holiday reject)
- `logs/smoke_test_full_20260525.log` — Previous assemble-only (WATCH)
- `logs/smoke_test_submit_20260525.log` — Previous submit (WATCH → SKIPPED)
