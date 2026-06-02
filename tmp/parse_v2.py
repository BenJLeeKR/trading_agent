import json
import sys

with open("/workspace/agent_trading/logs/backfill_container_dry_run_v2_20260531.log", "r") as f:
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

print("=== V2 Top-Level Summary ===")
print(f"  total: {data.get('total')}")
print(f"  auto_fix_safe: {data.get('auto_fix_safe')}")
print(f"  truth_probe_conflict: {data.get('truth_probe_conflict')}")
print(f"  manual: {data.get('manual')}")
print(f"  date_range: {data.get('date_range')}")
print()

records = data.get("orders", data.get("records", []))

# Truth probe conflict breakdown by reason
conflict_records = [r for r in records if r.get("classification") == "truth_probe_conflict"]
conflict_by_reason = {}
for r in conflict_records:
    reason = r.get("reason", "unknown")
    conflict_by_reason[reason] = conflict_by_reason.get(reason, 0) + 1

print("=== V2 Truth Probe Conflict Breakdown (by reason) ===")
for reason, count in sorted(conflict_by_reason.items()):
    print(f"  {reason}: {count}")
print(f"  total: {len(conflict_records)}")
print()

# Categories
position_delta_partial = sum(1 for r in conflict_records if "position_delta_partial" in r.get("reason", ""))
expired_confirmed_cat = sum(1 for r in conflict_records if r.get("verdict") == "expired_confirmed")
position_delta_filled = sum(1 for r in conflict_records if "position_delta_filled" in r.get("reason", ""))
print("=== V2 Conflict Categories ===")
print(f"  position_delta_partial: {position_delta_partial}")
print(f"  expired_confirmed: {expired_confirmed_cat}")
print(f"  position_delta_filled: {position_delta_filled}")

# Auto-fix safe details
auto_fix_records = [r for r in records if r.get("classification") == "auto_fix_safe"]
print(f"\n=== V2 Auto-fix Safe Count: {len(auto_fix_records)} ===")
for r in auto_fix_records:
    print(f"  order_request_id={r.get('order_request_id')} symbol={r.get('symbol')} side={r.get('side')} verdict={r.get('verdict')} reason={r.get('reason')}")

# Show expired_confirmed records in v2 conflict
print(f"\n=== V2 Expired Confirmed in Conflict ===")
exp_conflict = [r for r in conflict_records if r.get("verdict") == "expired_confirmed"]
print(f"  Count: {len(exp_conflict)}")
for r in exp_conflict:
    print(f"  order_request_id={r.get('order_request_id')} symbol={r.get('symbol')} side={r.get('side')} qty={r.get('requested_qty')} target={r.get('target_status')} reason={r.get('reason')}")

