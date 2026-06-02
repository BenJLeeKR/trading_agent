#!/usr/bin/env python3
"""apply_patch: postgres/accounts.py — E2E 필터 제거"""

filepath = "/workspace/agent_trading/src/agent_trading/repositories/postgres/accounts.py"
with open(filepath, "r") as f:
    content = f.read()

# Replace SQL with E2E filter removed
old = '''            "SELECT * FROM trading.accounts WHERE client_id = $1 AND account_code != 'E2E-SUMMARY-001' ORDER BY account_alias",'''
new = '''            "SELECT * FROM trading.accounts WHERE client_id = $1 ORDER BY account_alias",'''
assert old in content, "ERROR: Old text not found in accounts.py"
content = content.replace(old, new)

with open(filepath, "w") as f:
    f.write(content)
print("✅ accounts.py: E2E filter removed")
