#!/usr/bin/env python3
"""Postgres-backed Phase 2 endpoint manual curl verification with seed data."""

import os, subprocess, sys, time, json, uuid as uuid_mod, asyncio
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")

import asyncpg

DSN = (
    f"postgresql://{os.environ['DATABASE_USER']}:{os.environ['DATABASE_PASSWORD']}"
    f"@{os.environ['DATABASE_HOST']}:{os.environ['DATABASE_PORT']}"
    f"/{os.environ['DATABASE_NAME']}"
)

async def seed():
    conn = await asyncpg.connect(DSN, statement_cache_size=0)
    
    client_id = "11111111-1111-1111-1111-111111111111"
    account_id = "22222222-2222-2222-2222-222222222222"
    instrument_id = "33333333-3333-3333-3333-333333333333"
    broker_account_id = "44444444-4444-4444-4444-444444444444"
    order_id = "55555555-5555-5555-5555-555555555555"
    position_snapshot_id = "88888888-8888-8888-8888-888888888888"
    cash_balance_snapshot_id = "99999999-9999-9999-9999-999999999999"
    broker_order_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    
    now = datetime.now(timezone.utc)
    
    # Clean up
    for t in ["broker_orders", "cash_balance_snapshots", "position_snapshots",
              "order_requests", "accounts", "broker_accounts", "clients", "instruments"]:
        try:
            await conn.execute(f'DELETE FROM trading."{t}"')
        except Exception:
            pass
    
    # clients
    await conn.execute(
        "INSERT INTO trading.clients (client_id, client_code, name, status, base_currency, created_at) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        client_id, "API_TEST", "API Test Client", "active", "KRW", now
    )
    
    # broker_accounts
    await conn.execute(
        "INSERT INTO trading.broker_accounts (broker_account_id, broker_name, account_ref, "
        "environment, credential_ref, status, created_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        broker_account_id, "KIS", "ref-123", "paper", "cred-1", "active", now
    )
    
    # accounts
    await conn.execute(
        "INSERT INTO trading.accounts (account_id, client_id, broker_account_id, environment, "
        "account_alias, account_masked, status, risk_profile, created_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, '{}', $8)",
        account_id, client_id, broker_account_id, "paper", "API-ACCT-001", "****1234", "active", now
    )
    
    # instruments
    await conn.execute(
        "INSERT INTO trading.instruments (instrument_id, symbol, market_code, asset_class, "
        "currency, name, tick_size, lot_size, is_active, created_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, TRUE, $9)",
        instrument_id, "AAPL", "NASDAQ", "us_stock", "USD", "Apple Inc.", 0.01, 1, now
    )
    
    # order_requests (minimal fields for broker_orders FK)
    await conn.execute(
        "INSERT INTO trading.order_requests (order_request_id, account_id, instrument_id, client_order_id, "
        "idempotency_key, correlation_id, side, order_type, requested_quantity, status, "
        "requested_price, time_in_force, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $13)",
        order_id, account_id, instrument_id, "API-ORDER-001", f"idem-{order_id}", "corr-001",
        "buy", "limit", 100, "acknowledged", 150.00, "day", now
    )
    
    # position_snapshots
    await conn.execute(
        "INSERT INTO trading.position_snapshots (position_snapshot_id, account_id, instrument_id, "
        "quantity, average_price, market_price, unrealized_pnl, source_of_truth, snapshot_at, created_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
        position_snapshot_id, account_id, instrument_id, 100, 150.00, 155.00, 500.00, "broker", now, now
    )
    
    # cash_balance_snapshots
    await conn.execute(
        "INSERT INTO trading.cash_balance_snapshots (cash_balance_snapshot_id, account_id, currency, "
        "available_cash, settled_cash, unsettled_cash, source_of_truth, snapshot_at, created_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
        cash_balance_snapshot_id, account_id, "KRW", 1000000.00, 1000000.00, 0.00, "broker", now, now
    )
    
    # broker_orders
    await conn.execute(
        "INSERT INTO trading.broker_orders (broker_order_id, order_request_id, broker_name, "
        "broker_status, broker_native_order_id, last_synced_at, created_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        broker_order_id, order_id, "KIS", "filled", "KIS-12345", now, now
    )
    
    await conn.close()
    print("Seed complete.")
    return {"account_id": account_id, "order_id": order_id, "instrument_id": instrument_id,
            "client_id": client_id, "broker_order_id": broker_order_id}

ids = asyncio.run(seed())

# ── Start uvicorn server ────────────────────────────────────────────────────
env = os.environ.copy()
env["API_RUNTIME_MODE"] = "postgres"

proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn",
     "agent_trading.api.app:create_app_from_env",
     "--factory", "--host", "0.0.0.0", "--port", "8001"],
    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
print(f"Server PID: {proc.pid}")
time.sleep(3)

import http.client

def api_get(path):
    conn = http.client.HTTPConnection("localhost", 8001, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read().decode()
    conn.close()
    return resp.status, json.loads(body) if body else None

acct_id = ids["account_id"]
order_id = ids["order_id"]
instr_id = ids["instrument_id"]
client_id = ids["client_id"]

all_ok = True

# 1. GET /accounts/{id}
print("\n" + "="*60)
status, data = api_get(f"/accounts/{acct_id}")
print(f"GET /accounts/{acct_id} → {status}")
print(json.dumps(data, indent=2, default=str))
ok = status == 200 and data["account_id"] == acct_id and data["risk_profile"] == {}
print(f"  {'✅' if ok else '❌'} account_id/risk_profile correct")
all_ok = all_ok and ok

# 2. GET /instruments/{id}
print("\n" + "="*60)
status, data = api_get(f"/instruments/{instr_id}")
print(f"GET /instruments/{instr_id} → {status}")
print(json.dumps(data, indent=2, default=str))
ok = status == 200 and data["instrument_id"] == instr_id
print(f"  {'✅' if ok else '❌'} instrument_id correct")
all_ok = all_ok and ok

# 3. GET /cash-balances?account_id=... (existing → non-null)
print("\n" + "="*60)
status, data = api_get(f"/cash-balances?account_id={acct_id}")
print(f"GET /cash-balances?account_id={acct_id} → {status}")
print(json.dumps(data, indent=2, default=str))
ok = status == 200 and data is not None and data["currency"] == "KRW"
print(f"  {'✅' if ok else '❌'} cash-balance non-null with correct currency")
all_ok = all_ok and ok

# 4. GET /cash-balances?account_id=... (absent → 200 null)
print("\n" + "="*60)
fake_uuid = str(uuid_mod.uuid4())
status, data = api_get(f"/cash-balances?account_id={fake_uuid}")
print(f"GET /cash-balances?account_id={fake_uuid} (no data) → {status}")
print(f"Response: {data}")
ok = status == 200 and data is None
print(f"  {'✅' if ok else '❌'} cash-balance absent → 200 null")
all_ok = all_ok and ok

# 5. GET /positions?account_id=...
print("\n" + "="*60)
status, data = api_get(f"/positions?account_id={acct_id}")
print(f"GET /positions?account_id={acct_id} → {status}, count={len(data) if data else 0}")
print(json.dumps(data, indent=2, default=str))
ok = status == 200 and len(data) >= 1 and data[0]["source_of_truth"] == "broker"
print(f"  {'✅' if ok else '❌'} positions list returned")
all_ok = all_ok and ok

# 6. GET /clients/{id} (P1)
print("\n" + "="*60)
status, data = api_get(f"/clients/{client_id}")
print(f"GET /clients/{client_id} → {status}")
print(json.dumps(data, indent=2, default=str))
ok = status == 200 and data["client_code"] == "API_TEST"
print(f"  {'✅' if ok else '❌'} client detail correct")
all_ok = all_ok and ok

# 7. GET /orders/{id}/broker-orders (P1)
print("\n" + "="*60)
status, data = api_get(f"/orders/{order_id}/broker-orders")
print(f"GET /orders/{order_id}/broker-orders → {status}, count={len(data) if data else 0}")
print(json.dumps(data, indent=2, default=str))
ok = status == 200 and len(data) >= 1 and data[0]["broker_name"] == "KIS"
print(f"  {'✅' if ok else '❌'} broker-orders correct")
all_ok = all_ok and ok

# 8. GET /accounts?client_id=... (list)
print("\n" + "="*60)
status, data = api_get(f"/accounts?client_id={client_id}")
print(f"GET /accounts?client_id={client_id} → {status}, count={len(data) if data else 0}")
print(json.dumps(data, indent=2, default=str))
ok = status == 200 and len(data) >= 1
print(f"  {'✅' if ok else '❌'} accounts list correct")
all_ok = all_ok and ok

# Cleanup
proc.terminate()
proc.wait()

print("\n" + "="*60)
if all_ok:
    print("✅ All Phase 2 Postgres curl verifications passed!")
else:
    print("❌ Some verifications failed!")
