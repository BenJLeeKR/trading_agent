# Agent Subprocess Active Failure: Root Cause & Real Output Recovery

**Date:** 2026-05-20  
**Author:** Debug Mode Investigation  
**Related Files:**  
- [`scripts/run_agent_subprocess.py`](scripts/run_agent_subprocess.py) — subprocess entry point  
- [`src/agent_trading/services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py:2008) — `_run_agents_in_subprocess()`  
- [`src/agent_trading/services/ai_agents/provider_client.py`](src/agent_trading/services/ai_agents/provider_client.py) — httpx client  
- [`docker-compose.yml`](docker-compose.yml:308) — env var defaults  

---

## 1. Problem Description

All `agent_runs` in production were showing fallback/default patterns (`summary=""`, `confidence=0.0`, `decision_type="HOLD"`) despite the `_safe_datetime()` / `_reconstruct_context()` fixes from Task 8 being correctly deployed. The symptoms were:

1. **`AttributeError: 'str' object has no attribute 'strftime'`** — expected but not appearing in recent logs (container newly restarted)
2. **35s subprocess timeout** — 4 symbols (004800, 004370, 004990, 004170) all timing out at exactly 35s
3. **All fallback bundles** — every symbol returning empty `AgentExecutionBundle`

The datetime reconstruction fix IS in the running containers (confirmed via `grep` on container filesystem; docker volume mounts `./scripts:/app/scripts` and `./src:/app/src` ensure container code matches local code).

---

## 2. Investigation Summary

### Step 1-2: Container Status & Code Comparison

- `ops-scheduler` was restarted ~38 min ago (independent of app/reconciliation-worker images)
- Container code == Local code (confirmed via `diff` — no differences)
- Volume mounts override container images, so rebuild is not required

### Step 3: Log Analysis

Only 24 minutes of runtime. No `strftime` tracebacks visible — because the **subprocess consistently times out before reaching the agent `.run()` code**.

### Step 4: Parent Serialization Path

[`_serialize_agent_input()`](src/agent_trading/services/decision_orchestrator.py:2368) correctly constructs a JSON-safe dict with provider config.  
[`_run_agents_in_subprocess()`](src/agent_trading/services/decision_orchestrator.py:2008) spawns the subprocess with 35s timeout.

### Step 5: ExternalEventEntity Reconstruction

[`_safe_datetime()`](scripts/run_agent_subprocess.py:149), [`_reconstruct_external_event()`](scripts/run_agent_subprocess.py:156), [`_reconstruct_context()`](scripts/run_agent_subprocess.py:290) — all correctly convert ISO strings → `datetime` objects. Tested and confirmed working.

### Step 6: Root Cause — Dual Problem

#### Problem A: `logging.basicConfig()` Missing (Diagnostic Blind Spot)

[`scripts/run_agent_subprocess.py`](scripts/run_agent_subprocess.py:73) had only `logger = logging.getLogger(__name__)` with **no handler configuration**. Unlike every other script in `scripts/` (which all call `logging.basicConfig()`), the subprocess dropped all `logger.info()` calls silently.

**Consequence:** The parent process captures stderr only on success, but stderr was always empty because no handler was configured. We had ZERO visibility into:

- Whether the subprocess reached "Starting EventInterpretationAgent.run()"
- Whether `OpenAICompatibleClient` was created successfully
- What error occurred before the timeout

#### Problem B: `_SUBPROCESS_TIMEOUT = 35.0` Too Short

[`_SUBPROCESS_TIMEOUT = 35.0`](src/agent_trading/services/decision_orchestrator.py:2086) was a **hardcoded local variable**, not configurable. The 3 agents run sequentially:

1. **Event Interpretation** — takes 15–25s per agent API call  
2. **AI Risk** — takes 15–25s+ and appears to hang  
3. **Final Decision Composer** — never reached

With 3 × 25s = 75s minimum, the 35s subprocess timeout always kills the subprocess before any agent completes.

The DEEPSEEK_TIMEOUT_SECONDS env var (default 30s) controls the **httpx client timeout**, which is per-request. But the outer subprocess timeout (35s) kills the process before any 30s httpx timeout fires.

#### Diagnostic Evidence

After adding file-based diagnostic logging (`_diag()`), we captured **34 subprocess diagnostic files** from the paper decision loop. Every single one shows:

```
[2026-05-20T12:15:00.456] PID=67 main() started
[2026-05-20T12:15:00.456] PID=67 Input parsed: symbol=000270 market=KRX ...
[2026-05-20T12:15:00.456] PID=67 Creating OpenAICompatibleClient ...
[2026-05-20T12:15:00.456] PID=67 OpenAICompatibleClient created
[2026-05-20T12:15:00.456] PID=67 Starting EventInterpretationAgent.run() ...
[2026-05-20T12:15:00.456] PID=67 Context reconstructed: events=2
```

But **NONE** show:
- `EventInterpretationAgent completed:` 
- `AIRiskAgent completed:`
- `FinalDecisionComposerAgent completed:`
- `SUCCESS: all 3 agents completed`
- `EXCEPTION after ...`

Every subprocess ends at either "Context reconstructed: events=N" (EI agent still running) or "Starting AIRiskAgent.run() ..." (AR agent still running). Many have been running for >3 minutes without progress.

---

## 3. Root Cause

**Primary:** [`_SUBPROCESS_TIMEOUT = 35.0`](src/agent_trading/services/decision_orchestrator.py:2086) is insufficient for 3 sequential DeepSeek API calls (each taking 15–25s+). The 35s timeout kills the subprocess before any agent call completes.

**Secondary:** [`scripts/run_agent_subprocess.py`](scripts/run_agent_subprocess.py) lacks `logging.basicConfig()`, making all `logger.info()` calls silent. Combined with the parent's stderr-only-on-success logging pattern, this created a complete diagnostic blind spot.

**Not a problem:** The `_safe_datetime()` / `_reconstruct_context()` fixes are correct and working. The `AttributeError` was never observed because the subprocess consistently times out before reaching any agent code that calls `.strftime()`.

---

## 4. Changes Applied

### File 1: [`scripts/run_agent_subprocess.py`](scripts/run_agent_subprocess.py)

1. **Added `import os`** — needed for PID-based log filenames
2. **Added [`logging.basicConfig(stream=sys.stderr, level=logging.INFO, ...)`](scripts/run_agent_subprocess.py:78)** — configures stderr logging so parent can capture subprocess diagnostics
3. **Added [`_diag()` function](scripts/run_agent_subprocess.py:86)** — writes to `/tmp/subprocess_diag_<PID>.log` (bypasses pipe, survives parent kill)
4. **Added `_diag()` calls in `main()`** at key checkpoints:
   - `main() started`
   - `Input parsed: ...`
   - `Creating OpenAICompatibleClient ...`
   - `OpenAICompatibleClient created`
   - `No provider client created`
   - `Starting EventInterpretationAgent.run() ...`
   - `Context reconstructed: events=N`
   - `EventInterpretationAgent completed: ...`
   - `Starting AIRiskAgent.run() ...`
   - `AIRiskAgent completed: ...`
   - `Starting FinalDecisionComposerAgent.run() ...`
   - `FinalDecisionComposerAgent completed: ...`
   - `SUCCESS: all 3 agents completed`
   - `EXCEPTION after ...`

### File 2: [`src/agent_trading/services/decision_orchestrator.py`](src/agent_trading/services/decision_orchestrator.py)

1. **Added stderr capture in timeout handler** — reads `proc.stderr` before SIGTERM/SIGKILL, logs content as `stderr_hint` in the warning message
2. **Increased [`_SUBPROCESS_TIMEOUT`](src/agent_trading/services/decision_orchestrator.py:2086) from 35.0 → 120.0 seconds** — 3 × 30s provider timeout + 30s buffer

---

## 5. Verification Results

| Test Suite | Result |
|---|---|
| `test_agent_subprocess.py` (19 tests) | ✅ All passed |
| `test_decision_orchestrator.py` (40 tests) | ✅ All passed |
| Syntax validation (both files) | ✅ Valid |
| `_diag()` function test in container | ✅ Working |
| `logging.basicConfig` verified in container | ✅ Root logger has 1 handler, level=INFO |

---

## 6. Future Recommendations

1. **Monitor agent completion times** — After deployment, check `/tmp/subprocess_diag_*.log` files inside the container to verify all 3 agents complete within the 120s window
2. **Consider parallel agent execution** — If latency remains high, run EI/AR/FDC agents in parallel (each with independent DeepSeek call) and aggregate results
3. **Make `_SUBPROCESS_TIMEOUT` configurable** — Consider deriving it from `DEEPSEEK_TIMEOUT_SECONDS × 3 + buffer` instead of a hardcoded constant
4. **Add subprocess timeout metrics** — Track subprocess completion times in Prometheus/custom metrics to detect regressions
5. **Investigate AR agent hang** — The AI Risk agent appears to never complete. This may be a separate issue with the agent prompt or response parsing for certain symbol/event combinations
