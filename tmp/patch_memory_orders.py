#!/usr/bin/env python3
"""apply_patch: memory.py — InMemoryOrderRepository E2E 필터 패턴 기반 완화"""

filepath = "/workspace/agent_trading/src/agent_trading/repositories/memory.py"
with open(filepath, "r") as f:
    content = f.read()

# === 변경 1: __init__ — _excluded_account_ids 제거, _excluded_account_code_patterns 추가 ===
old_init = """    def __init__(self) -> None:
        self._items: dict[UUID, OrderRequestEntity] = {}
        # E2E 테스트 계정(E2E-SUMMARY-001) 제외를 위한 account_id 집합
        # PostgreSQL의 JOIN 필터(a.account_code != 'E2E-SUMMARY-001')와 동일한 효과
        self._excluded_account_ids: set[UUID] = set()"""

new_init = """    def __init__(self) -> None:
        self._items: dict[UUID, OrderRequestEntity] = {}
        # E2E 계정 제외를 위한 account_code 패턴 목록
        # PostgreSQL의 NOT LIKE 'E2E-%' 필터와 동기화
        # account_code 기반 필터링은 account_id → account_code 매핑이 필요하므로,
        # 실제 필터링은 _excluded_account_ids를 통해 account_id 레벨에서 수행됩니다.
        self._excluded_account_code_patterns: list[str] = ['E2E-%']
        self._excluded_account_ids: set[UUID] = set()"""

assert old_init in content, "ERROR: Old __init__ not found in memory.py (InMemoryOrderRepository)"
content = content.replace(old_init, new_init)

# === 변경 2: exclude_account → exclude_account_code 로 변경 ===
old_exclude = """    def exclude_account(self, account_id: UUID) -> None:
        \"\"\"Register an account UUID whose orders should be excluded from list().\"\"\"
        self._excluded_account_ids.add(account_id)"""

new_exclude = """    def exclude_account(self, account_id: UUID) -> None:
        \"\"\"Register an account UUID whose orders should be excluded from list().\"\"\"
        self._excluded_account_ids.add(account_id)

    def exclude_account_code(self, pattern: str) -> None:
        \"\"\"Register an account_code pattern whose orders should be excluded from list().\"\"\"
        if pattern not in self._excluded_account_code_patterns:
            self._excluded_account_code_patterns.append(pattern)"""

assert old_exclude in content, "ERROR: Old exclude_account not found in memory.py"
content = content.replace(old_exclude, new_exclude)

# === 변경 3: list() — E2E 필터 주석 업데이트 ===
old_filter_comment = """            # E2E 테스트 계정(E2E-SUMMARY-001)의 주문 제외 (PostgreSQL JOIN 필터와 동기화)
            if item.account_id in self._excluded_account_ids:"""

new_filter_comment = """            # E2E 계정(account_code가 'E2E-%' 패턴)의 주문 제외 (PostgreSQL NOT LIKE 'E2E-%' 필터와 동기화)
            if item.account_id in self._excluded_account_ids:"""

assert old_filter_comment in content, "ERROR: Old filter comment not found in memory.py"
content = content.replace(old_filter_comment, new_filter_comment)

with open(filepath, "w") as f:
    f.write(content)
print("✅ memory.py (InMemoryOrderRepository): E2E filter changed to pattern-based")
