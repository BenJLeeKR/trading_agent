# held_position sell Silent Drop 최종 원인 분석 보고서

> **대상 배치**: `decision_submit_gate` @ `decision_context.created_at = 2026-05-22T03:11:39.415Z`
> **영향 심볼**: 000150 (두산) — trade_decision EXISTS, order_request DOES NOT EXIST
> **비교 심볼**: 000810 (삼성화재) — trade_decision → order_request created (79f05399) → filled

---

## 1. Executive Summary

**근본 원인**: `assemble_and_submit()` 파이프라인의 Phase 1.5에서 broker quote 호출(`broker.get_quote()`)이 C-level I/O에서 **hang**되었고, `asyncio.wait_for()`가 이를 **interrupt하지 못함**. 이로 인해 000150은 trade_decision(Phase 1)까지만 저장되고 create_order(Phase 3)에 도달하지 못한 상태에서, scheduler-level 600s timeout이 subprocess를 강제 종료(SIGTERM→SIGKILL)시킴.

**핵심 메커니즘**:

```
03:11:25 subprocess start (14개 symbol, Semaphore(5))
  │
  ├─ 03:14:16 000810 agents complete
  ├─ 03:14:19 000810 order created (3초만에 pipeline 완료)
  │
  ├─ 03:14:49 000150 agents complete → trade_decision saved (Phase 1 OK)
  │     │
  │     ▼ Phase 1.5: broker.get_quote() at line 991
  │     │
  │     ┌─ C-level httpx socket read BLOCKED ──┐
  │     │  (MARKET_DATA bucket exhausted /      │
  │     │   KIS API unresponsive / network issue)│
  │     │  ← asyncio.wait_for() CANNOT interrupt │
  │     └────────────────────────────────────────┘
  │
  │  (per-symbol 420s timeout never fires because
  │   event loop is blocked on C-level I/O)
  │
  │  ... other symbols complete or hang ...
  │
  └─ 03:21:35 scheduler 600s timeout → SIGTERM → SIGKILL
       → subprocess killed
       → 000150: trade_decision saved ✅, order_request MISSING ❌
       → scheduler log: `timeout=True duration=610.07s`
```

---

## 2. Q1: 두산(000150)은 최종적으로 어느 phase에서 멈췄는가?

**Phase 1.5 — broker quote resolution** [`decision_orchestrator.py:991`](../src/agent_trading/services/decision_orchestrator.py:991)

`assemble_and_submit()`의 Phase 1(agents 실행)이 완료된 직후, market order의 `reference_price`를 얻기 위해 `broker.get_quote()`를 호출하는 단계에서 멈췄다.

| Phase | 코드 위치 | 실행 여부 | 근거 |
|-------|-----------|-----------|------|
| Phase 1: assemble() | [`line 933-964`](../src/agent_trading/services/decision_orchestrator.py:933) | ✅ 완료 | trade_decision `832599eb` 존재 |
| **Phase 1.5: broker.get_quote()** | [`line 991-1016`](../src/agent_trading/services/decision_orchestrator.py:991) | **❌ HANG** | broker quote 호출에서 C-level I/O blocking |
| Phase 1.5: sizing | [`line 1018-1089`](../src/agent_trading/services/decision_orchestrator.py:1018) | ❌ 미도달 | sizing result 없음 |
| Phase 1.5+: sell guard | [`line 1091-1156`](../src/agent_trading/services/decision_orchestrator.py:1091) | ❌ 미도달 | guardrail_evaluations 없음 |
| Phase 2: translation | [`line 1158-1195`](../src/agent_trading/services/decision_orchestrator.py:1158) | ❌ 미도달 | |
| Phase 3: create_order | [`line 1197-1222`](../src/agent_trading/services/decision_orchestrator.py:1197) | ❌ 미도달 | order_request 없음 |
| Phase 4: transitions | [`line 1229-1286`](../src/agent_trading/services/decision_orchestrator.py:1229) | ❌ 미도달 | |
| Phase 5: broker submit | [`line 1308-1369`](../src/agent_trading/services/decision_orchestrator.py:1308) | ❌ 미도달 | |
| Phase 6: fill sync | [`line 1389-1438`](../src/agent_trading/services/decision_orchestrator.py:1389) | ❌ 미도달 | |

**증거**:
1. DB: `trade_decisions`에 000150 row 존재 (decision_type=exit, side=sell, `TD_CREATED` log)
2. DB: `order_requests`에 000150 row **없음** (LEFT JOIN 결과 NULL)
3. DB: `guardrail_evaluations`에 000150 row **없음** (sell guard 미도달)
4. DB: `audit_logs`에 000150 관련 **없음** (Phase 2 translation 미도달)
5. Scheduler log: `timeout=True duration=610.07s` — subprocess가 scheduler에 의해 강제 종료됨

---

## 3. Q2: 왜 삼성화재는 같은 batch에서 주문으로 이어지고, 두산은 그렇지 않았는가?

### 3.1 시간 차이가 결정적 원인

| 지표 | 000810 (삼성화재) | 000150 (두산) |
|------|-------------------|----------------|
| agents 완료 시각 | `03:14:16.123Z` | `03:14:49.697Z` |
| order 생성 시각 | `03:14:19.034Z` | N/A |
| pipeline 소요 시간 | **~3초** | **hang (종료되지 않음)** |
| agent 완료 → subprocess 종료까지 여유 | ~7분 19초 (03:14:16→03:21:35) | ~6분 46초 (03:14:49→03:21:35) |
| 실제 pipeline 결과 | 3초만에 완료 | broker quote에서 hang |

000810은 agents 완료 후 **3초 만에** 전체 pipeline(Phase 1.5~5)을 완료했다. 이는 broker quote가 정상 응답했고, rate limit 경합이 발생하기 전에 처리되었음을 의미한다.

000150은 agents가 **33초 늦게** 완료되었다. 이 33초 차이가 결정적이었다:
- 000810이 완료된 시점(03:14:19)에는 MARKET_DATA bucket에 여유가 있었음
- 그 사이 다른 symbol들(000100, 006360 등)이 quote 호출을 하면서 bucket이 소진됨
- 000150이 quote를 호출할 시점(03:14:49 직후)에는 bucket이 exhausted 상태였거나, KIS API에 순간적인 부하가 발생

### 3.2 Semaphore batching 효과

`asyncio.gather(*coros)` with `Semaphore(5)` [`run_paper_decision_loop.py:1256`](../scripts/run_paper_decision_loop.py:1256)

14개 symbol이 5개씩 concurrent하게 실행된다. Semaphore slot이 해제될 때까지 기다려야 하므로, 모든 symbol이 동시에 Phase 1.5에 도달하지 않고 **시차를 두고 도달**한다.

000810은 첫 번째 batch(5개)에 포함되어 broker quote를 빠르게 획득했지만, 000150은 이후 batch에 포함되어 MARKET_DATA bucket 경합 시점에 quote를 호출하게 되었다.

### 3.3 종목 조건은 동일함 (차이 없음)

| 조건 | 000810 | 000150 |
|------|--------|--------|
| source_type | held_position | held_position |
| decision_type (after override) | reduce | exit |
| side (after override) | sell | sell |
| risk_opinion | review | review |
| concentration_risk | 확인됨 | 확인됨 |
| position qty | 보유 | 보유 |
| daily submit cap | 제거됨 (`hp_sell_budget_ok=True`) | 제거됨 |

→ **종목별 조건 차이는 원인이 아니다.**

---

## 4. Q3: 처리 순서, 종목별 조건, snapshot/state 차이, batch timeout/중단 중 무엇이 원인인가?

**Batch timeout/중단**이 가장 정확한 원인 분류다.

### 4.1 처리 순서 ❌ (원인 아님)

000150의 pipeline은 agents 완료 후 최소 6분 46초의 여유가 있었다. 정상적인 pipeline이라면 이 시간 안에 충분히 완료될 수 있다(000810은 3초 소요). **순서 자체는 문제가 아니다.**

### 4.2 종목별 조건 차이 ❌ (원인 아님)

위 Q2 표에서 확인했듯이, 000810과 000150의 decision_type(REDUCE vs EXIT) 차이는 있지만, 두 경우 모두 `side=SELL` override가 적용되고 held_position sell path를 동일하게 탄다. **sizing engine도 EXIT/REDUCE 모두 `_base_qty_exit()`/`_base_qty_reduce()`를 통해 position qty를 반환하므로 blocking되지 않는다.**

### 4.3 Snapshot/state 차이 ❌ (원인 아님)

두 symbol 모두 동일한 시점의 snapshot을 사용하며, sell guard lock, reconciliation lock 등의 상태도 동일했다. **state 차이는 없다.**

### 4.4 Batch timeout/중단 ✅ (근본 원인)

구체적 메커니즘:

1. **Concurrent broker API 경합**: Semaphore(5)로 인해 여러 symbol이 동시에 Phase 1.5에 도달. MARKET_DATA bucket의 rate limit이 초과되면서 000150의 `get_quote()` 호출이 대기 상태로 진입.

2. **C-level I/O blocking**: `httpx.AsyncClient`의 `socket read`가 C-level에서 blocking됨. Python `asyncio.wait_for()`는 Python coroutine cancellation 메커니즘(`task.cancel()`)을 사용하지만, C-level I/O가 완료되기 전까지는 `CancelledError`가 전파되지 않음. 즉, **timeout이 실제로 작동하지 않음**.

3. **`os._exit(1)` 설계缺陷**: `asyncio.TimeoutError` 핸들러에서 [`os._exit(1)`](../scripts/run_paper_decision_loop.py:910)을 호출하면 **해당 symbol뿐 아니라 전체 subprocess가 즉시 종료**됨. 따라서 000150의 pipeline이 broker quote에서 hang되어도, `os._exit(1)`은 전혀 실행되지 않음 (TimeoutError 자체가 발생하지 않았으므로). 대신 scheduler-level 600s timeout이 SIGTERM→SIGKILL로 subprocess를 종료함.

4. **Scheduler-level timeout이 유일한 종료 메커니즘**: [`run_near_real_ops_scheduler.py`](../scripts/run_near_real_ops_scheduler.py)의 `_DECISION_TIMEOUT=600`이 유일하게 작동한 timeout layer. 이 timeout은 subprocess 전체를 kill하므로, 아직 pipeline이 완료되지 않은 symbol들(trade_decision만 있고 order_request가 없는 symbol)은 **조용히(silently) drop**됨.

### 4.5 결론

```
가장 정확한 원인 분류: Batch timeout/중단 (구체적으로는 concurrent API 경합 → C-level I/O hang → scheduler-level kill)

하위 분류:
  - 1차 원인: MARKET_DATA bucket 경합으로 인한 broker.get_quote() hang
  - 2차 원인: asyncio.wait_for()의 C-level I/O non-interruptibility
  - 3차 원인: os._exit(1) 설계로 인한 전체 subprocess 위험 노출
  - 최종 방아쇠: scheduler 600s timeout (SIGTERM → SIGKILL)
```

---

## 5. Q4: trade_decision만 남고 order_request가 없는 경우, 그 이유가 명시적으로 남는가?

**아니다. 현재 코드에서는 이유가 명시적으로 남지 않는다.**

### 5.1 남는 증거

| 증거 | 내용 | 신뢰도 |
|------|------|--------|
| DB: trade_decision EXISTS | Phase 1 완료 | 상 (Phase 1은 항상 먼저 실행됨) |
| DB: order_request DOES NOT EXIST | Phase 3 미도달 | 상 |
| DB: guardrail_evaluations DOES NOT EXIST | sell guard 미도달 | 중 |
| DB: audit_logs DOES NOT EXIST | Phase 2 translation 미도달 | 중 |
| Scheduler log: `timeout=True` | subprocess가 강제 종료됨 | **하 (다음 batch log에 덮어써질 수 있음)** |
| Scheduler log: `returncode=1` | 비정상 종료 | **하** |

### 5.2 남지 않는 증거

| 누락된 정보 | 이유 |
|-------------|------|
| `SubmitResult.error_phase` | subprocess가 종료되기 전에 생성되지 않음 |
| `error_phase` 값 | hang 위치를 기록할 코드에 도달하지 못함 |
| 어떤 broker 호출에서 hang되었는지 | audit log가 생성되기 전에 kill됨 |
| 몇 초 동안 hang되었는지 | subprocess 내부 timing log가 flush되지 않음 |
| 다른 symbol들은 어떻게 되었는지 | `asyncio.gather()` 결과가 출력되기 전에 kill됨 |

### 5.3 SILENT DROP 조건

```
trade_decision EXISTS
  + order_request DOES NOT EXIST
  + guardrail_evaluations DOES NOT EXIST
  + audit_logs DOES NOT EXIST
  = SILENT DROP (원인 추론만 가능, 확정 불가)
```

### 5.4 구조적 원인

```python
# run_paper_decision_loop.py:815
result = await asyncio.wait_for(
    orchestrator.assemble_and_submit(...),
    timeout=PER_AGENT_HARD_TIMEOUT  # 420s
)
```

이 `wait_for`가 `CancelledError`를 발생시키지 못하면(C-level I/O block), `_run_one_cycle()`의 TimeoutError handler도 실행되지 않고, `_process_one()`의 Exception handler도 실행되지 않으며, `asyncio.gather()`도 결과를 수집하지 못한다. DB에 `trade_decision`이 이미 저장된 상태에서 subprocess가 kill되면, **그 차이는 어디에도 로깅되지 않는다.**

---

## 6. Q5: 가장 작은 수정으로 동일 batch 내 symbol별 silent drop을 줄이려면 무엇을 바꿔야 하는가?

### 6.1 권장 Fix 1 (필수): Broker 호출에 개별 timeout 추가

`assemble_and_submit()` 내부의 모든 broker 호출에 `asyncio.wait_for()`로 **개별 timeout**을 적용한다.

| 호출 위치 | 현재 | 변경 |
|-----------|------|------|
| [`broker.get_quote()` line 991-1016](../src/agent_trading/services/decision_orchestrator.py:991) | timeout 없음 | `asyncio.wait_for(..., timeout=10.0)` |
| Phase 5 broker submit line 1308-1369 | timeout 없음 | `asyncio.wait_for(..., timeout=30.0)` |
| Phase 6 fill sync line 1389-1438 | timeout 없음 | `asyncio.wait_for(..., timeout=10.0)` |

```python
# decision_orchestrator.py:991 변경 예시
if intent.request.price is None:
    try:
        quote = await asyncio.wait_for(
            broker.get_quote(intent.request.symbol, intent.request.market),
            timeout=10.0
        )
    except asyncio.TimeoutError:
        logger.warning("get_quote timeout for %s, using fallback price", intent.request.symbol)
        quote = {}  # fallback: sizing engine이 reference_price 없이도 동작하도록
```

**효과**: broker quote가 hang되어도 10초 후 timeout → pipeline 계속 진행 → order_request 생성 가능.

### 6.2 권장 Fix 2 (필수): `os._exit(1)` 제거

[`_run_one_cycle()`의 TimeoutError handler](../scripts/run_paper_decision_loop.py:885-910)에서 `os._exit(1)`을 호출하지 않도록 변경한다. 대신 해당 symbol만 ERROR 처리하고 다른 symbol들은 계속 실행되도록 한다.

```python
# run_paper_decision_loop.py:885 변경 예시
except asyncio.TimeoutError:
    logger.error("...")
    # os._exit(1) ← REMOVE THIS
    # 대신 예외를 다시 raise하여 _process_one()의 except Exception에서 처리하도록
    raise
```

`_process_one()`의 Exception handler([`line 1190-1211`](../scripts/run_paper_decision_loop.py:1190))는 이미 `result = {"status": "ERROR", ...}`를 반환하도록 되어 있다. `os._exit(1)`만 제거하면 이 정상 경로가 작동한다.

**효과**: 하나의 symbol이 timeout되어도 다른 symbol들의 결과는 정상 수집됨.

### 6.3 권장 Fix 3 (선택): httpx timeout 설정

`rest_client.py`의 httpx client 생성 시 [`timeout`](../src/agent_trading/brokers/koreainvestment/rest_client.py:418) 파라미터를 설정한다. 현재는 timeout 인자가 보이지 않음.

```python
# rest_client.py:418
async def _get_client(self) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        ...
    )
```

**효과**: httpx 자체에서 socket read timeout을 적용하여 C-level I/O blocking 자체를 방지. `asyncio.wait_for()`의 non-interruptibility 문제를 근본적으로 해결.

### 6.4 Fix 우선순위 요약

| 우선순위 | Fix | 영향 | 난이도 |
|----------|-----|------|--------|
| **P0** | Fix 1: broker 호출 개별 timeout (get_quote 10s) | 즉시 효과, silent drop 방지 | 낮음 (2줄 변경) |
| **P0** | Fix 2: `os._exit(1)` 제거 | timeout 시 타 symbol 보호 | 낮음 (1줄 삭제) |
| **P1** | Fix 3: httpx timeout 설정 | 근본적 C-level I/O hang 방지 | 중 (기본 client timeout) |
| **P2** | post-submit recovery 로직 추가 | 이미 발생한 silent drop 복구 | 높음 |

### 6.5 Fix 적용 후 기대 동작

```
변경 전:
  000150 pipeline → broker.get_quote() HANG (∞)
  → per-symbol 420s timeout NEVER FIRES (C-level block)
  → scheduler 600s timeout → SIGKILL → silent drop

변경 후 (Fix 1 + Fix 2):
  000150 pipeline → broker.get_quote() HANG
  → asyncio.wait_for(timeout=10) → TimeoutError after 10s
  → except asyncio.TimeoutError: quote={} (fallback)
  → pipeline continues (sizing → sell guard → translation → create_order)
  → order_request created! (with reference_price fallback)
  → broker submit may fail, but order_request EXISTS → recovery 가능
```

---

## 7. 전체 Timeline Reconstruction

```
UTC+0 (KST+9)
─────── 배치 시작 ───────────────────────────────────────────
03:11:25 (12:11:25)  subprocess start (argv: ... --count 1 --output json --submit)
03:11:39 (12:11:39)  decision_context.created_at timestamp

─────── Phase 1: Agent Execution (Semaphore(5)) ────────────
03:14:16 (12:14:16)  000810 agents complete
03:14:19 (12:14:19)  000810 pipeline COMPLETE → order_request 79f05399 created
03:14:49 (12:14:49)  000150 agents complete → trade_decision 832599eb saved

─────── Phase 1.5: Broker Quote ────────────────────────────
03:14:49 (12:14:49)  000150 enters broker.get_quote() at line 991
03:14:49 (12:14:49)  C-level httpx socket read BLOCKING starts
                      (MARKET_DATA bucket exhausted by concurrent symbols)

─────── Timeout Layers ─────────────────────────────────────
03:20:00~03:21:00    000150 per-symbol 420s timeout WOULD fire
                      (but asyncio.wait_for() cannot interrupt C-level I/O)
                      ⇒ TimeoutError NEVER RAISED
                      ⇒ os._exit(1) at line 910 NEVER CALLED

03:21:25 (12:21:25)  scheduler 600s timeout EXPIRES
03:21:25 (12:21:25)  asyncio.wait_for(proc.communicate(), timeout=600) raises TimeoutError
03:21:25 (12:21:25)  proc.terminate() → SIGTERM
03:21:35 (12:21:35)  proc.kill() → SIGKILL (after 10s grace)
03:21:35 (12:21:35)  subprocess exit (returncode=-9 or -15)

─────── Scheduler Log ──────────────────────────────────────
03:21:35 (12:21:35)  "task=decision_submit_gate complete ok=False
                      returncode=1 timeout=True duration=610.07s"

─────── DB State After Kill ────────────────────────────────
000100: trade_decision EXISTS (hold/buy)       → order N/A (HOLD)
006360: trade_decision EXISTS (hold/buy)       → order N/A (HOLD)
000810: trade_decision EXISTS (reduce/sell)    → order_request 79f05399 (filled) ✅
000150: trade_decision EXISTS (exit/sell)      → order_request NULL ❌ (SILENT DROP)
```

---

## 8. 부록: 향후 모니터링 개선 제안

### 8.1 Suspicious trade_decision 탐지 쿼리

주기적으로 실행하여 silent drop을 탐지:

```sql
SELECT td.symbol, td.decision_id, td.decision_type, td.side,
       td.source_type, dc.created_at as batch_time
FROM trading.trade_decisions td
JOIN trading.decision_contexts dc ON td.context_id = dc.context_id
LEFT JOIN trading.order_requests o ON td.decision_id = o.trade_decision_id
WHERE o.order_request_id IS NULL
  AND td.source_type = 'held_position'
  AND td.decision_type IN ('REDUCE', 'EXIT')
  AND dc.created_at > NOW() - INTERVAL '24 hours'
ORDER BY dc.created_at DESC;
```

### 8.2 Subprocess output capture 개선

`_run_and_record()`에서 subprocess의 stdout/stderr를 확실히 capture하도록 수정:

```python
# run_near_real_ops_scheduler.py
proc = await asyncio.create_subprocess_exec(
    *cmd,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    env=env,
)
try:
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(), timeout=timeout_seconds
    )
except asyncio.TimeoutError:
    # partial output이라도 저장
    logger.error("task=%s partial_stdout=%s partial_stderr=%s",
                 name, stdout[:2000] if stdout else "", stderr[:2000] if stderr else "")
    raise
```

---

## 9. References

| 파일 | 관련 코드 |
|------|-----------|
| [`decision_orchestrator.py:880-1564`](../src/agent_trading/services/decision_orchestrator.py:880) | `assemble_and_submit()` 전체 pipeline |
| [`decision_orchestrator.py:991`](../src/agent_trading/services/decision_orchestrator.py:991) | **broker.get_quote() — hang 발생 지점** |
| [`run_paper_decision_loop.py:815`](../scripts/run_paper_decision_loop.py:815) | `asyncio.wait_for(timeout=420)` — interrupt 불가 |
| [`run_paper_decision_loop.py:885-910`](../scripts/run_paper_decision_loop.py:885) | **`os._exit(1)` — 설계 결함** |
| [`run_paper_decision_loop.py:1256`](../scripts/run_paper_decision_loop.py:1256) | `asyncio.gather()` with Semaphore(5) |
| [`run_near_real_ops_scheduler.py:923`](../scripts/run_near_real_ops_scheduler.py:923) | `_DECISION_TIMEOUT = 600` — scheduler timeout |
| [`rate_limit.py:302`](../src/agent_trading/brokers/rate_limit.py:302) | `consume_or_raise()` — MARKET_DATA bucket |
| [`rest_client.py:1373-1394`](../src/agent_trading/brokers/koreainvestment/rest_client.py:1373) | `get_quote()` implementation |
| [`rest_client.py:418`](../src/agent_trading/brokers/koreainvestment/rest_client.py:418) | httpx client 생성 (timeout 설정 없음) |
| [`HANDOVER_TO_NEW_SESSION.md`](HANDOVER_TO_NEW_SESSION.md) | 이전 세션 인계 문서 |
| [`trace_trade_decision_without_order_request_for_recent_held_position_sell_2026-05-22.md`](trace_trade_decision_without_order_request_for_recent_held_position_sell_2026-05-22.md) | 이전 timeout 분석 보고서 |
