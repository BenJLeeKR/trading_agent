"""Verify ORDER bucket refill_rate for paper env."""
import asyncio
import sys
sys.path.insert(0, '/workspace/agent_trading/src')

from agent_trading.brokers.rate_limit import build_kis_budget_manager

async def main():
    mgr = build_kis_budget_manager(kis_env="paper")
    snap = mgr.snapshot()
    
    print("=== Paper Budget Snapshot ===")
    for name, info in sorted(snap.items()):
        if isinstance(info, dict):
            print(f"  {name}: capacity={info.get('capacity', '?')}, "
                  f"remaining={info.get('remaining', '?')}, "
                  f"utilization={info.get('utilization', '?')}")
    
    # Check ORDER bucket refill_rate directly from the bucket object
    order_refill = mgr.order.refill_rate
    order_capacity = mgr.order.capacity
    expected_refill = 1.5  # 0.5 * 3 (paper_rest_rps=3)
    expected_capacity = 9  # max(3, int(3 * 3)) = 9
    
    print(f"\n=== ORDER Bucket Direct Check ===")
    print(f"  capacity: {order_capacity} (expected: {expected_capacity})")
    print(f"  refill_rate: {order_refill} (expected: {expected_refill})")
    
    if abs(order_refill - expected_refill) < 0.01:
        print("✅ ORDER refill_rate correct!")
    else:
        print(f"❌ ORDER refill_rate WRONG! Got {order_refill}, expected {expected_refill}")
        sys.exit(1)
    
    if order_capacity == expected_capacity:
        print("✅ ORDER capacity correct!")
    else:
        print(f"❌ ORDER capacity WRONG! Got {order_capacity}, expected {expected_capacity}")
        sys.exit(1)

asyncio.run(main())
