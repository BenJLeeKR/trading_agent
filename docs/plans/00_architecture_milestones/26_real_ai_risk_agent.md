# Plan 26: Real AIRiskAgent Implementation

## 1. Goal

Move `AIRiskAgent` from stub-only to stub + real implementation, following the same pattern as `EventInterpretationAgent` (Plan 21-25).

## 2. Scope

### Included
- Real `AIRiskAgent` class in `src/agent_trading/services/ai_agents/ai_risk.py`
- `_generate_json_schema()` moved to `schemas.py` for sharing between agents
- Bootstrap helper `_build_ai_risk_agent()` for runtime wiring
- `ai_risk_agent` key in runtime dictionaries
- Unit tests (mock provider), orchestrator integration tests, bootstrap tests

### Excluded (deferred)
- `FinalDecisionComposerAgent` real implementation
- Provider multi-call optimization
- Order execution path changes
- Scoring / threshold / hard guardrail changes
- Replay format changes
- BrokerAdapter / OrderManager contract changes
- Smoke tests (will add in a follow-up, like Plan 25 did for EI)

## 3. Design

### 3.1 Input to AIRiskAgent

`AgentExecutionRequest.context: AssembledContext` provides:
- `decision_context` — account/strategy/correlation context
- `config_version` — governing config
- `recent_events` — external events (already available from EI agent context)
- `score` — deterministic score

Plus `request.symbol`, `request.side` from the `AgentExecutionRequest` itself.

**What is NOT yet available (explicitly empty)**:
- Event Interpretation Agent output (not piped to AIRisk yet — v1 runs agents independently on same context)
- Position data (no position lookup in orchestrator yet)
- Risk limit snapshots
- Real score calculation

### 3.2 Output

`AIRiskOutput` schema (already defined in `schemas.py`):
- `risk_opinion`: `"allow"` | `"reduce"` | `"reject"` | `"review"`
- `risk_score`: 0.0–1.0
- `confidence`: 0.0–1.0
- `size_adjustment_factor`: 0.0–1.0
- `max_holding_horizon`: `"short"` | `"swing"` | `"long"`
- `risk_flags`, `reason_codes`, `opposing_evidence`, `summary`

### 3.3 Safe Fallback Policy

Same as `EventInterpretationAgent`:
- Provider error / timeout → log warning → return `AIRiskOutput()` (default: `risk_opinion="allow"`, zero risk)
- Parse failure → log warning → return default
- Guarantees orchestrator `assemble()` always proceeds

### 3.4 Prompt Design

**System prompt**: Describe the AIRiskOutput JSON schema and instruct the model to assess risk based on the trading context.

**User prompt**: Include:
- Correlation ID
- Symbol and proposed side
- Score (if available)
- Recent events (if any)
- Decision context info (if available)

### 3.5 Bootstrap Wiring

- Add `_build_ai_risk_agent(settings)` → `AIRiskAgent | None`
- Add `ai_risk_agent` key to all three runtime dicts (`build_default_runtime`, `build_postgres_runtime`, `postgres_runtime`)
- Update `_build_orchestrator()` signature to accept `ai_risk_agent` parameter
- `_close_provider_agent()` already works generically via `_provider` attribute — no change needed

## 4. Files to Change

| File | Change |
|------|--------|
| `src/agent_trading/services/ai_agents/schemas.py` | Add `generate_json_schema()` utility function |
| `src/agent_trading/services/ai_agents/event_interpretation.py` | Remove local `_generate_json_schema()`, import from `schemas.py` |
| `src/agent_trading/services/ai_agents/ai_risk.py` | Add `AIRiskAgent` class |
| `src/agent_trading/services/ai_agents/__init__.py` | Export `AIRiskAgent` |
| `src/agent_trading/runtime/bootstrap.py` | Add `_build_ai_risk_agent()`, update runtime dicts |
| `tests/services/ai_agents/test_agents.py` | Add `TestAIRiskAgent` class |
| `tests/services/ai_agents/test_orchestrator_agents.py` | Add real EI + real AR + stub FDC test |
| `tests/services/ai_agents/test_bootstrap.py` | Add ai_risk_agent key tests |
| `plans/README.md` | Add entry 26 |

## 5. Test Plan

### A. Unit Tests (`test_agents.py`)
- Protocol conformance (`isinstance(agent, ProviderAIAgent)`)
- `agent_name == "ai_risk"`
- `schema_version` default and custom
- Successful provider call → `AIRiskOutput` with preserved fields
- Provider error → safe fallback to default `AIRiskOutput`
- Parse error → safe fallback
- `decision_context_id` set when provided
- `decision_context_id` None when not provided

### B. Orchestrator Integration (`test_orchestrator_agents.py`)
- Real EI (mock provider) + Real AR (mock provider) + Stub FDC
- `assemble()` succeeds
- Recorder has 3 runs with correct agent_types
- AR output in `structured_output_json` has `risk_opinion`, `risk_score`

### C. Bootstrap Tests (`test_bootstrap.py`)
- `_build_ai_risk_agent()` returns None when settings incomplete
- `_build_ai_risk_agent()` returns `AIRiskAgent` when settings complete
- Runtime dicts contain `ai_risk_agent` key
- Orchestrator injected with real AR agent

## 6. Completion Criteria
- [x] Real `AIRiskAgent` implemented
- [x] Stub and real coexist
- [x] Orchestrator accepts real AR via injection
- [x] Bootstrap wiring for AR agent
- [x] All tests green (existing + new)
- [x] Readiness for FinalDecisionComposerAgent real implementation
