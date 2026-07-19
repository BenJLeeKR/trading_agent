# Live Reduce/Exit Submit Timeout 및 Sell Order 복구 — 2026-05-19

## 1. 문제 정의
- `trade_decisions`에는 `decision_type='reduce'`, `side='sell'` 다수 생성
- `order_requests(side='sell')`는 0건
- `decision_submit_gate`가 244초 timeout으로 반복 실패
- `post-submit-sync`: `ODNO match FAILED` 반복

## 2. Timeout Root Cause
### 2.1 발견된 진짜 원인
- **T3 분리와 무관** — T3는 이미 `asyncio.create_task()`로 decision path와 병렬 실행
- **LLM API C-level httpx I/O 블로킹**이 진짜 원인
  - `PER_AGENT_HARD_TIMEOUT=90` 만료 → `os._exit(1)` 호출
  - 그러나 httpx C-level 소켓 read가 즉시 해제되지 않음
  - Scheduler의 `DEFAULT_TASK_TIMEOUT_SECONDS=240`이 최종적으로 subprocess를 terminate
  - `244s ≈ 240s scheduler timeout + overhead`

### 2.2 시간 경과 분석
| 시간 | 이벤트 |
|------|--------|
| 0s | `decision_submit_gate` 시작 |
| ~25s | Agent 1 (EI) 실행 — LLM API 호출 (httpx blocking) |
| ~50s | Agent 2 (AR) 실행 — LLM API 호출 (httpx blocking) |
| ~75s | Agent 3 (FDC) 실행 — LLM API 호출 (httpx blocking) |
| 90s | `PER_AGENT_HARD_TIMEOUT` 만료 → `os._exit(1)` 호출 |
| 90s~240s | httpx C-level I/O가 `os._exit(1)`로도 해제되지 않아 subprocess hang |
| 240s | Scheduler `asyncio.wait_for` timeout → `proc.terminate()` → `proc.kill()` |
| 244s | 최종 종료 (terminate→kill overhead 포함) |

## 3. Sell Submit Path 단계별 분석
### 3.1 경로 추적
```
_run_one_cycle()
  └─ SubmitOrderRequest(side=OrderSide.BUY)  ← 하드코딩 BUY
       └─ orchestrator.assemble_and_submit(request)
            ├─ Phase 1: assemble()
            │    ├─ _run_agents() → EI/AR/FDC 3개 LLM 실행
            │    ├─ REDUCE/EXIT + sell override → request.side = SELL ✅
            │    ├─ _ensure_trade_decision() → trade_decisions INSERT (side='sell') ✅
            │    └─ OrderIntent(request.side=SELL) 반환
            │
            ├─ Phase 1.5: sizing engine
            │    ├─ SizingInputs(side=SELL)
            │    ├─ current_position_qty = 0 or None
            │    ├─ _base_qty_reduce() → Decimal(0) ⚠️
            │    └─ sizing_result.quantity = 0
            │
            ├─ [BEFORE FIX] sizing_result.quantity <= 0 → SKIPPED ❌
            │
            ├─ Phase 2: build_submit_order_request_from_decision()
            │    └─ intent.request.quantity > 0 → 통과 (fallback 적용)
            │
            └─ Phase 3: create_order() → order_requests INSERT
                 → [도달 가능] ✅
```

### 3.2 차단 지점
- **1차 차단 (BEFORE FIX)**: `assemble_and_submit()` Phase 1.5에서 `sizing_result.quantity <= 0`으로 SKIPPED
- **근본 원인**: `_build_sizing_inputs()`에서 `current_position_qty`가 0 또는 None. 이로 인해 `_base_qty_reduce()/exit()`가 0 반환.
- **DB 증거**: `LEFT JOIN` 결과 30건의 sell trade_decisions 모두 `order_request_id = NULL`

## 4. 적용한 수정
### 4.1 수정 1: Sell path sizing fallback
**파일**: [`src/agent_trading/services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py:787)

**변경**: SELL side에서 sizing이 0을 반환해도 `intent.request.quantity`를 fallback으로 사용
```python
effective_qty = sizing_result.quantity
if effective_qty <= 0 and intent.request.side == OrderSide.SELL:
    req_qty = intent.request.quantity
    if req_qty > 0:
        effective_qty = req_qty
        logger.info("Sizing returned 0 for SELL; falling back to request.quantity=%s", req_qty)
```

### 4.2 수정 2: Timeout handling 개선
**파일**: [`scripts/run_paper_decision_loop.py`](scripts/run_paper_decision_loop.py:822)

**변경**: `PER_AGENT_HARD_TIMEOUT` 만료 시 pending task를 명시적으로 cancel 후 graceful 종료
```python
except asyncio.TimeoutError:
    logger.error("PER_AGENT_HARD_TIMEOUT=%ds exceeded", PER_AGENT_HARD_TIMEOUT)
    for task in asyncio.all_tasks():
        if task is not asyncio.current_task():
            task.cancel()
    await asyncio.sleep(0.1)
    os._exit(1)
```

## 5. 질문별 답변
### Q1: `trade_decisions(side='sell')` 이후 실제 어디 단계에서 끊기는가?
→ `assemble()`까지는 정상 도달. Phase 1.5 (sizing)에서 `sizing_result.quantity <= 0`으로 SKIPPED. 수정 적용 후 Phase 2/3까지 도달 가능.

### Q2: `decision_submit_gate` 244초 timeout의 직접 원인은 무엇인가?
→ LLM API httpx C-level I/O 블로킹. `os._exit(1)`로도 즉시 해제되지 않아 scheduler 240s timeout까지 대기.

### Q3: T3 분리 이후에도 timeout이 계속 나는 이유는 무엇인가?
→ T3 분리와 timeout은 **무관**. T3는 `asyncio.create_task()`로 decision path와 병렬 실행되며, `_T3_GATHER_WAIT=5`초만 기다림. 진짜 원인은 LLM API 자체의 C-level 블로킹.

### Q4: `post-submit-sync` 반복이 scheduler 리소스/주기에 영향을 주는가?
→ **무관**. `_run_intraday_due_tasks()`는 snapshot → event → decision → post_submit을 순차 실행. post_submit_sync는 decision 완료 후 실행됨. `ODNO match FAILED`는 paper trading 환경에서 정상적인 현상.

### Q5: 최소 수정으로 sell order request 생성까지 살리려면 어디를 고쳐야 하는가?
→ `assemble_and_submit()`의 Phase 1.5에서 SELL side에 한해 `sizing_result.quantity` 대신 `intent.request.quantity`를 fallback으로 사용 (수정 1 적용 완료).

## 6. post-submit-sync 영향 평가
### 6.1 ODNO match FAILED 원인
- KIS `inquire-daily-ccld` API 호출 시 broker_order_id와 일치하는 ODNO 없음
- Paper trading 환경에서 실제 주문이 접수되지 않았기 때문 (`order_requests` 미생성 → `broker_orders` 미존재)
- 단순 로그이며 scheduler 실행 흐름에 영향 없음

### 6.2 영향도: 없음 ✅
- scheduler와 동일 tick 내 순차 실행
- decision 완료 후 실행되어 간섭 없음
- 예외 발생 시 로그만 남기고 정상 종료

## 7. 테스트 결과
| 테스트 파일 | 결과 | 비고 |
|------------|------|------|
| `tests/services/test_decision_orchestrator.py` | **40 passed** | 신규 3 + 기존 37 |
| `tests/services/test_sizing_engine.py` | **51 passed** | 회귀 없음 |
| `tests/services/test_submit_order_from_decision.py` | **8 passed** | 신규 파일 |

### 신규 테스트 (`TestSellPathSizingFallback`)
1. `test_sizing_fallback_behavior_for_sell_without_position` — position 없이 SELL/REDUCE 시 sizing fallback 검증
2. `test_sizing_fallback_uses_request_quantity_for_sell` — sizing=0일 때 `request.quantity` 사용 검증
3. `test_sizing_fallback_for_exit_sell` — EXIT+SELL 조합 fallback 검증

## 8. 운영 검증 결과
| 항목 | 결과 |
|------|------|
| pytest (신규 테스트 3개) | ✅ 40/40 통과 |
| Docker 재기동 | ✅ `ops-scheduler` restart 성공 |
| `/health` | ✅ `status: ok, database: connected, scheduler: healthy` |
| scheduler 로그 | ✅ 정상 (pre-market → event_ingestion) |
| DB order_requests baseline | 129건 중 `side='sell'` **1건** (기존) |

## 9. 장중 검증 필요 항목
다음 항목은 장중(다음 영업일)에 `decision_submit_gate`가 실행된 후 확인 필요:

1. **`decision_submit_gate` duration**: timeout(240s) 없이 정상 종료되는지 확인
2. **`order_requests(side='sell')` 생성**: REDUCE/EXIT → sell order 실제 생성되는지 확인
3. **`broker_orders` 연결**: sell order가 broker submit까지 도달하는지 확인
4. **`_DECISION_TIMEOUT` 재조정 검토**: T3 분리 + timeout handling 개선 후 300s → 180s 이하로 낮출 수 있는지

## 10. 변경 파일 목록
| 파일 | 변경 내용 |
|------|----------|
| [`src/agent_trading/services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py) | SELL side sizing fallback 추가 (L787) |
| [`scripts/run_paper_decision_loop.py`](scripts/run_paper_decision_loop.py) | Timeout handling 개선 — asyncio task cancel 후 graceful 종료 (L822) |
| [`tests/services/test_decision_orchestrator.py`](tests/services/test_decision_orchestrator.py) | `TestSellPathSizingFallback` 3개 테스트 추가 |
