#!/usr/bin/env python3
"""apply_patch: memory.py — AccountRepository E2E 필터 제거"""

filepath = "/workspace/agent_trading/src/agent_trading/repositories/memory.py"
with open(filepath, "r") as f:
    content = f.read()

# Remove E2E filter from InMemoryAccountRepository.list_by_client
old = """            if item.client_id == client_id and item.account_code != 'E2E-SUMMARY-001'"""
new = """            if item.client_id == client_id"""
assert old in content, "ERROR: Old text not found in memory.py (AccountRepository)"
content = content.replace(old, new)

with open(filepath, "w") as f:
    f.write(content)
print("✅ memory.py (AccountRepository): E2E filter removed")
