import os
os.environ["KIS_PAPER_REST_RPS"] = "1"
os.environ["KIS_ENV"] = "paper"
from agent_trading.config.settings import AppSettings
settings = AppSettings()
print(f"kis_paper_rest_rps = {settings.kis_paper_rest_rps}")
assert settings.kis_paper_rest_rps == 1, f"Expected 1, got {settings.kis_paper_rest_rps}"
print("PASS: settings.kis_paper_rest_rps == 1")

from agent_trading.brokers.rate_limit import build_kis_budget_manager
bm = build_kis_budget_manager(
    kis_env=settings.kis_env,
    paper_rest_rps=settings.kis_paper_rest_rps,
)
# global_rest is an OperationBucket; capacity is its burst limit
global_cap = bm.global_rest.capacity if bm.global_rest else 0
print(f"global_rest_capacity = {global_cap}")
assert global_cap == 1, f"Expected 1, got {global_cap}"
print("PASS: global_rest_capacity == 1")

# Operation bucket capacities 확인 - 직접 속성 접근
for name in ("order", "inquiry", "reconciliation", "market_data", "auth"):
    bucket = getattr(bm, name, None)
    if bucket:
        print(f"  {name}: capacity={bucket.capacity}, refill={bucket.refill_rate}/s")
print("DONE")
