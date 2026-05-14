# Near-Real 100-Symbol Latency Measurement Report

**Date**: 2026-05-14 KST  
**Author**: Roo (automated measurement)  
**Status**: ✅ Complete

---

## 1. Verification: Scheduler → DB Universe Path

### Execution Path Analysis

```
run_near_real_ops_scheduler.py
  └─ _build_base_env() → os.environ.copy()  ← TRADING_UNIVERSE_SYMBOLS 미설정
      └─ _decision_command(dry_run=True|False)
          └─ subprocess: python3 -m scripts.run_paper_decision_loop --count 1 --output json [--dry-run|--submit]
              └─ _read_trading_universe()
                  ├─ os.getenv("TRADING_UNIVERSE_SYMBOLS") → None  ← 상속된 env에 없음
                  ├─ asyncpg.connect() → DB query → 100 KRX symbols  ✅
                  └─ fallback: (UniverseSymbol("005930", "KRX"),)  ← 사용되지 않음
```

**결론**: Scheduler가 subprocess로 decision loop을 호출할 때, `_build_base_env()`는 `os.environ.copy()`를 사용하므로 `TRADING_UNIVERSE_SYMBOLS`가 설정되어 있지 않습니다. 따라서 `_read_trading_universe()`의 Priority 1이 skip되고, Priority 2 (DB query)가 실행되어 **100개 KRX 종목이 로드됩니다.**

### Actual Dry-Run Evidence

```
2026-05-14 14:13:05 [INFO] paper-decision-loop: Trading universe from DB: 100 KRX symbols loaded.
2026-05-14 14:13:05 [INFO] paper-decision-loop: Trading universe (100): 000030:KRX, 000100:KRX, ..., 377300:KRX
```

**✅ Scheduler 경로에서도 DB 100종목 universe가 정상 적용됨을 확인.**

---

## 2. Latency Measurement Results

### 2.1 Decision Loop — 100 Symbols Dry-Run

| Metric | Value |
|--------|-------|
| **Total symbols** | 100 |
| **Total cycle elapsed** | **5.355 seconds** |
| **Symbols per second** | ~18.7 |
| **Per-symbol avg duration** | **~0.054 seconds** (54 ms) |
| **Min per-symbol duration** | 0.047 s (352820) |
| **Max per-symbol duration** | 0.069 s (005490) |
| **Success rate** | 100% (100/100) |
| **Submit occurred?** | **No** (--dry-run) |

**Per-symbol breakdown (sample)**:

| Symbol | Duration (s) |
|--------|-------------|
| 000030 | 0.055 |
| 005930 | 0.059 |
| 207940 | 0.057 |
| 373220 | 0.051 |
| 377300 | 0.049 |

All symbols show consistent ~50ms latency — no outliers.

### 2.2 Snapshot Sync — 1 Cycle

| Metric | Value |
|--------|-------|
| **Cycle elapsed** | **1.3 seconds** |
| **Outcome** | Failed at KIS oauth2 (AppKey missing in this env) |
| **Realistic estimate** | ~3–8s (with valid KIS credentials: auth + positions + cash + 100 positions) |

### 2.3 Event Ingestion — 1 Cycle

| Metric | Value |
|--------|-------|
| **Cycle elapsed** | **0.032 seconds** |
| **New events** | 0 (no polling workers configured) |
| **Realistic estimate** | ~1–5s (with OpenDART + other sources) |

---

## 3. KIS REST Call Estimate (100 Symbols, Dry-Run)

Current dry-run mode uses **stub agents** — no actual KIS REST calls are made during the decision loop itself. The only KIS calls happen in **snapshot sync**.

| Component | KIS Calls per Cycle | Notes |
|-----------|-------------------|-------|
| Snapshot sync | ~3–5 | oauth2 token + positions + cash + order status |
| Event ingestion | 0 | OpenDART only, not KIS |
| Decision loop (dry-run) | **0** | Stub agents, no quote/orderbook fetch |
| Decision loop (real AI) | **100+** | 1 quote per symbol = 100 calls |
| **Total (current dry-run)** | **~3–5** | |
| **Total (real AI estimate)** | **~103–105** | |

**Important**: When real AI agents are configured, each symbol's `_run_one_cycle()` calls `orchestrator.assemble()` which fetches `InstrumentEntity` from DB (not KIS). However, the `KoreaInvestmentAdapter.get_quote()` would be called per symbol if the AI needs market data — that would add **100 KIS REST calls per cycle**.

---

## 4. AI Agent Call Estimate (100 Symbols)

| Agent | Calls per Symbol | Total per Cycle |
|-------|-----------------|-----------------|
| EventInterpretationAgent | 2 | 200 |
| AIRiskAgent | 2 | 200 |
| FinalDecisionComposerAgent | 2 | 200 |
| **Total** | **6** | **600** |

Each symbol gets 2 calls per agent type (one for `assemble()`, one for `assemble_and_submit()`). With stub agents, each call is instant. With real LLM providers, each call would take **1–5 seconds**.

---

## 5. 5-Minute Cycle Feasibility Assessment

### Current Dry-Run Profile

```
Snapshot sync:   1.3s  (est. 3–8s real)
Event ingestion: 0.03s (est. 1–5s real)
Decision loop:   5.4s  (100 symbols, stub agents)
─────────────────────────────────────
Total:           6.7s  (est. 9–18s real)
```

**✅ 5-minute interval is SAFE** — even with 3× safety margin, total is under 20 seconds.

### Real AI Agent Profile (Estimated)

```
Snapshot sync:          ~5s
Event ingestion:        ~3s
Decision loop (100sym): ~100–500s  ← 1–5s per symbol × 100
─────────────────────────────────────
Total:                  ~108–508s
```

**⚠️ 5-minute interval is AT RISK** with real LLM agents:
- At 1s/agent-call × 600 calls = 600s (10 min) — **exceeds 5 min**
- At 0.5s/agent-call × 600 calls = 300s (5 min) — **at boundary**
- With parallelization (3 agents per symbol): 100–200s — **feasible**

### Bottleneck Analysis

| Component | Current | Real AI | Bottleneck? |
|-----------|---------|---------|-------------|
| **DB I/O** | ~0.05s/sym | ~0.05s/sym | ❌ No |
| **Stub agents** | ~0.001s/call | — | ❌ No |
| **LLM API calls** | — | 1–5s/call | **✅ YES — primary bottleneck** |
| **KIS REST (quote)** | 0 | ~0.3s/call | ⚠️ Secondary |
| **OpenDART fetch** | 0 | ~1–3s | ⚠️ Per-symbol if configured |

---

## 6. Recommendations

### Immediate (P0 — This Sprint)

| # | Action | Rationale |
|---|--------|-----------|
| 1 | **Keep 5-min interval for dry-run** | Current 6.7s total is safe |
| 2 | **Add `--dry-run` safeguard to scheduler** | Scheduler tried `--submit` when `db_submit_count=0` — needs explicit dry-run mode |
| 3 | **Measure with real AI agents** | Stub agents hide the real bottleneck |

### Short-term (Next Sprint)

| # | Action | Rationale |
|---|--------|-----------|
| 4 | **Universe reduction strategy** | 100 symbols × 6 agent calls = 600 LLM calls. Consider 20–30 symbol subset for paper |
| 5 | **Adaptive scheduling** | If decision cycle > interval, skip next cycle instead of queueing |
| 6 | **Phase separation** | Snapshot sync + event ingestion in parallel, decision loop sequential |

### Medium-term

| # | Action | Rationale |
|---|--------|-----------|
| 7 | **Parallel symbol processing** | Run `_run_one_cycle()` for multiple symbols concurrently (asyncio.gather with semaphore) |
| 8 | **KIS quote batching** | If KIS supports batch quote API, reduce 100 calls to 1 |
| 9 | **AI agent caching** | Cache identical contexts across symbols to reduce LLM calls |

---

## 7. Risk Register

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Decision cycle exceeds 5-min interval | Cycle overlap, missed ticks | Medium (real AI) | Adaptive scheduling, universe reduction |
| KIS rate limit (RPS) exceeded | Order rejection | Low (paper) | Rate limiter already in place |
| DB connection pool exhaustion | Crash | Low | Pool size = 10, 100 sequential queries fine |
| Scheduler submits accidentally | Real money risk | **High** | **Add explicit `--dry-run` mode to scheduler** |

---

## 8. Appendix: Raw Measurement Commands

```bash
# Decision loop dry-run (100 symbols)
python3 -m scripts.run_paper_decision_loop --count 1 --dry-run --output json

# Snapshot sync (1 cycle)
python3 scripts/run_snapshot_sync_loop.py --max-cycles 1

# Event ingestion (1 cycle)
python3 scripts/run_event_ingestion_loop.py --count 1 --output json

# Scheduler once (WARNING: may submit!)
python3 -m scripts.run_near_real_ops_scheduler --once --skip-pre-market
```
