import json
import sys

# Read JSON from log file (starting from line 373 which is "{")
with open("/workspace/agent_trading/logs/backfill_container_dry_run_v3_20260531.log", "r") as f:
    lines = f.readlines()

# Find JSON start
json_start = None
for i, line in enumerate(lines):
    if line.strip() == "{":
        json_start = i
        break

if json_start is None:
    print("ERROR: Could not find JSON start")
    sys.exit(1)

json_text = "".join(lines[json_start:])

try:
    data = json.loads(json_text)
except json.JSONDecodeError as e:
    print(f"ERROR: JSON decode failed: {e}")
    sys.exit(1)

# Use 'orders' key (not 'records')
records = data.get("orders", data.get("records", []))
total = len(records)
print(f"Total records: {total}")
print()

# Top-level summary
print("=== Top-Level Summary ===")
print(f"  total: {data.get('total')}")
print(f"  auto_fix_safe: {data.get('auto_fix_safe')}")
print(f"  truth_probe_conflict: {data.get('truth_probe_conflict')}")
print(f"  manual: {data.get('manual')}")
print(f"  date_range: {data.get('date_range')}")
print()

# Classification breakdown from actual records
classifications = {}
for r in records:
    c = r.get("classification", "unknown")
    classifications[c] = classifications.get(c, 0) + 1

print("=== Classification Breakdown (from orders) ===")
for c in ["auto_fix_safe", "truth_probe_conflict", "manual"]:
    print(f"  {c}: {classifications.get(c, 0)}")
print(f"  total: {sum(classifications.values())}")
print()

# Auto-fix safe breakdown by target_status
auto_fix_records = [r for r in records if r.get("classification") == "auto_fix_safe"]
af_by_status = {}
for r in auto_fix_records:
    ts = r.get("target_status", "unknown")
    af_by_status[ts] = af_by_status.get(ts, 0) + 1

print("=== Auto-fix Safe Breakdown ===")
for ts in ["filled_confirmed", "partially_filled_suspected", "expired_confirmed"]:
    print(f"  {ts}: {af_by_status.get(ts, 0)}")
print()

# Auto-fix safe details
print("=== Auto-fix Safe Details ===")
for r in auto_fix_records:
    print(f"  order_request_id={r.get('order_request_id')} symbol={r.get('symbol')} side={r.get('side')} qty={r.get('requested_qty')} verdict={r.get('verdict')} target={r.get('target_status')} reason={r.get('reason')}")
print()

# Truth probe conflict breakdown
conflict_records = [r for r in records if r.get("classification") == "truth_probe_conflict"]
conflict_by_reason = {}
for r in conflict_records:
    reason = r.get("reason", "unknown")
    conflict_by_reason[reason] = conflict_by_reason.get(reason, 0) + 1

print("=== Truth Probe Conflict Breakdown (by reason) ===")
for reason, count in sorted(conflict_by_reason.items()):
    print(f"  {reason}: {count}")
print(f"  total: {len(conflict_records)}")
print()

# Map reasons to categories
position_delta_partial = sum(1 for r in conflict_records if "position_delta_partial" in r.get("reason", ""))
expired_confirmed_cat = sum(1 for r in conflict_records if "expired_confirmed" in r.get("reason", "") or r.get("verdict") == "expired_confirmed")
position_delta_filled = sum(1 for r in conflict_records if "position_delta_filled" in r.get("reason", ""))

print("=== Truth Probe Conflict Categories ===")
print(f"  position_delta_partial: {position_delta_partial}")
print(f"  expired_confirmed (match_verdict): {expired_confirmed_cat}")
print(f"  position_delta_filled: {position_delta_filled}")

# Check for expired_confirmed in auto_fix_safe
print()
print("=== Auto-fix Safe Records with target_status=expired_confirmed ===")
expired_auto_fix = [r for r in auto_fix_records if r.get("target_status") == "expired_confirmed"]
print(f"  Count: {len(expired_auto_fix)}")
for r in expired_auto_fix:
    print(f"  order_request_id={r.get('order_request_id')} symbol={r.get('symbol')} side={r.get('side')} qty={r.get('requested_qty')} verdict={r.get('verdict')} reason={r.get('reason')}")

# Also dump conflict details for expired_confirmed records
print()
print("=== Conflict Records with verdict=expired_confirmed ===")
expired_conflict = [r for r in conflict_records if r.get("verdict") == "expired_confirmed"]
print(f"  Count: {len(expired_conflict)}")
for r in expired_conflict:
    print(f"  order_request_id={r.get('order_request_id')} symbol={r.get('symbol')} side={r.get('side')} qty={r.get('requested_qty')} reason={r.get('reason')}")

