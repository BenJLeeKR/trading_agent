#!/usr/bin/env python3
"""apply_patch: postgres/orders.py — E2E 필터 패턴 기반 완화"""

filepath = "/workspace/agent_trading/src/agent_trading/repositories/postgres/orders.py"
with open(filepath, "r") as f:
    content = f.read()

# Replace hardcoded E2E account_code filter with pattern-based filter
old = """conditions.append("a.account_code != 'E2E-SUMMARY-001'")"""
new = """conditions.append("a.account_code NOT LIKE 'E2E-%'")"""
assert old in content, "ERROR: Old text not found in orders.py"
content = content.replace(old, new)

with open(filepath, "w") as f:
    f.write(content)
print("✅ orders.py (postgres): E2E filter changed to NOT LIKE 'E2E-%'")
