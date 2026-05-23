"""Apply Phase 7.3 P1+P2 changes to decision_orchestrator.py."""
import re

with open("src/agent_trading/services/decision_orchestrator.py", "r") as f:
    content = f.read()

# ============================================================
# Change 1: Replace imports
# ============================================================
old_imports = (
    "from agent_trading.services.sizing_engine import (\n"
    "    SizingInputs,\n"
    "    calculate_sizing,\n"
    ")\n"
    "from agent_trading.services.sell_guard import (\n"
    "    AvailableSellQtyResolver,\n"
    "    SellAvailability,\n"
    ")"
)
new_imports = (
    "from agent_trading.services.execution_service import (\n"
    "    AccountSnapshotFreshness,\n"
    "    ExecutionService,\n"
    "    PhaseTraceEntry,\n"
    "    SubmitResult,\n"
    ")\n"
    "from agent_trading.services.sizing_engine import (\n"
    "    SizingInputs,\n"
    "    calculate_sizing,\n"
    ")"
)
assert old_imports in content, "Change 1 FAILED!"
content = content.replace(old_imports, new_imports)
print("Change 1: imports updated OK")

# ============================================================
# Change 2: Remove AccountSnapshotFreshness dataclass (regex)
# ============================================================
pattern2 = re.compile(
    r'@dataclass\(slots=True, frozen=True\)\n'
    r'class AccountSnapshotFreshness:\n'
    r'.*?'
    r'\n(?=@dataclass)',
    re.DOTALL
)
match = pattern2.search(content)
assert match, "Change 2 FAILED!"
content = content[:match.start()] + content[match.end():]
print("Change 2: AccountSnapshotFreshness removed OK")

# ============================================================
# Change 3: Remove PhaseTraceEntry + SubmitResult dataclasses (regex)
# ============================================================
pattern3 = re.compile(
    r'# ---------------------------------------------------------------------------\n'
    r'# Phase trace entry \u2014 per-phase timing/diagnostics for the submit pipeline\n'
    r'# ---------------------------------------------------------------------------\n'
    r'\n'
    r'\n'
    r'@dataclass\(slots=True, frozen=True\)\n'
    r'class PhaseTraceEntry:\n'
    r'.*?'
    r'\n# ---------------------------------------------------------------------------\n'
    r'# Stub score calculator \(default when no real calculator is configured\)\n'
    r'# ---------------------------------------------------------------------------',
    re.DOTALL
)
match = pattern3.search(content)
assert match, "Change 3 FAILED!"
replacement3 = (
    "# ---------------------------------------------------------------------------\n"
    "# Stub score calculator (default when no real calculator is configured)\n"
    "# ---------------------------------------------------------------------------"
)
content = content[:match.start()] + replacement3 + content[match.end():]
print("Change 3: PhaseTraceEntry/SubmitResult removed OK")

# ============================================================
# Change 4: Update __init__ (regex to avoid Korean unicode mismatch)
# ============================================================
pattern4 = re.compile(
    r'        # --- Phase 1\.5\+: Duplicate Sell Guard ---\n'
    r'        self\._sell_guard_resolver = AvailableSellQtyResolver\(repos=repos\)\n'
    r'        # --- Provider configuration for subprocess ---\n'
    r'        self\._llm_provider = llm_provider\n'
    r'        self\._provider_api_key = provider_api_key\n'
    r'        self\._provider_base_url = provider_base_url\n'
    r'        self\._provider_model_id = provider_model_id\n'
    r'        self\._provider_timeout_seconds = provider_timeout_seconds\n'
    r'        # --- EXE-002: quote circuit breaker \+ cache state ---\n'
    r'        self\._quote_failures: dict\[str, int\] = \{\}  # symbol .*\n'
    r'        self\._quote_skip_until: dict\[str, datetime\] = \{\}  # symbol .*\n'
    r'        self\._quote_cache: dict\[str, tuple\[Quote, datetime\]\] = \{\}  # symbol .*'
)
new_init = (
    "        # --- Provider configuration for subprocess ---\n"
    "        self._llm_provider = llm_provider\n"
    "        self._provider_api_key = provider_api_key\n"
    "        self._provider_base_url = provider_base_url\n"
    "        self._provider_model_id = provider_model_id\n"
    "        self._provider_timeout_seconds = provider_timeout_seconds\n"
    "        # --- Execution Service (execution pipeline state: sell guard, quote CB, fresh check) ---\n"
    "        self._execution_service = ExecutionService(\n"
    "            repos=repos,\n"
    "            stale_threshold_seconds=stale_threshold_seconds,\n"
    "            sync_service=sync_service,\n"
    "            snapshot_refresh_cb=snapshot_refresh_cb,\n"
    "        )"
)
match4 = pattern4.search(content)
assert match4, "Change 4 FAILED!"
content = content[:match4.start()] + new_init + content[match4.end():]
print("Change 4: __init__ updated OK")

# ============================================================
# Change 5: Update delegation to ExecutionService
# ============================================================
assert "return await self._run_execution_pipeline(" in content, "Change 5 FAILED!"
content = content.replace(
    "return await self._run_execution_pipeline(",
    "return await self._execution_service.run_execution_pipeline(",
)
print("Change 5: delegation updated OK")

# ============================================================
# Change 6: Remove _run_execution_pipeline method
# ============================================================
start6 = "    async def _run_execution_pipeline(\n"
end6 = "\n    async def _run_decision_pipeline("
idx6s = content.find(start6)
idx6e = content.find(end6)
assert idx6s != -1, "Change 6 FAILED: start!"
assert idx6e != -1, "Change 6 FAILED: end!"
content = content[:idx6s] + content[idx6e:]
print("Change 6: _run_execution_pipeline removed OK")

# ============================================================
# Change 7: Remove _build_sizing_inputs method
# ============================================================
start7 = "    def _build_sizing_inputs(\n"
end7 = "\n    async def _check_account_snapshot_freshness("
idx7s = content.find(start7)
idx7e = content.find(end7)
assert idx7s != -1, "Change 7 FAILED: start!"
assert idx7e != -1, "Change 7 FAILED: end!"
content = content[:idx7s] + content[idx7e:]
print("Change 7: _build_sizing_inputs removed OK")

# ============================================================
# Change 8: Remove _check_account_snapshot_freshness method
# ============================================================
start8 = "    async def _check_account_snapshot_freshness(\n"
end8 = "\n    async def _ensure_or_create_decision_context("
idx8s = content.find(start8)
idx8e = content.find(end8)
assert idx8s != -1, "Change 8 FAILED: start!"
assert idx8e != -1, "Change 8 FAILED: end!"
content = content[:idx8s] + content[idx8e:]
print("Change 8: _check_account_snapshot_freshness removed OK")

# ============================================================
# Change 9: Remove module-level _phase_trace_to_dicts function
# ============================================================
start9 = "\n\ndef _phase_trace_to_dicts("
end9 = "\n\n# ---------------------------------------------------------------------------\n# Helper: convert a frozen dataclass to a plain dict"
idx9s = content.find(start9)
idx9e = content.find(end9)
assert idx9s != -1, "Change 9 FAILED: start!"
assert idx9e != -1, "Change 9 FAILED: end!"
content = content[:idx9s] + content[idx9e:]
print("Change 9: _phase_trace_to_dicts removed OK")

# ============================================================
# Write result
# ============================================================
with open("src/agent_trading/services/decision_orchestrator.py", "w") as f:
    f.write(content)

new_lines = content.splitlines()
print(f"\nAll 9 changes applied successfully! New file: {len(new_lines)} lines")
