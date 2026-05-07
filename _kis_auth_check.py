#!/usr/bin/env python3
"""KIS Paper auth check — minimal token issuance test.

Reads .env directly, uses explicit KIS_BASE_URL.
"""
import os, sys, json, httpx
from pathlib import Path

# Load .env manually (minimal, no python-dotenv dependency)
env_path = Path(__file__).resolve().parent / ".env"
if not env_path.exists():
    print("FAIL: .env not found")
    sys.exit(1)

env_vars: dict[str, str] = {}
for line in env_path.read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, _, val = line.partition("=")
    key = key.strip()
    val = val.strip().strip('"').strip("'")
    env_vars[key] = val

kis_env = env_vars.get("KIS_ENV", "")
kis_base_url = env_vars.get("KIS_BASE_URL", "")
kis_api_key = env_vars.get("KIS_API_KEY", "")
kis_api_secret = env_vars.get("KIS_API_SECRET", "")

print("=" * 60)
print("KIS Paper Auth Check")
print("=" * 60)
print(f"  KIS_ENV       = {kis_env!r}")
print(f"  KIS_BASE_URL  = {kis_base_url!r}")
print(f"  KIS_API_KEY   = {'***set***' if kis_api_key else '***MISSING***'}")
print(f"  KIS_API_SECRET= {'***set***' if kis_api_secret else '***MISSING***'}")
print()

if not kis_api_key or not kis_api_secret:
    print("FAIL: KIS credentials missing")
    sys.exit(1)

# Build token URL
token_url = f"{kis_base_url}/oauth2/tokenP"
print(f"  POST {token_url}")
print()

body = {
    "grant_type": "client_credentials",
    "appkey": kis_api_key,
    "appsecret": kis_api_secret,
}

with httpx.Client(timeout=15) as client:
    resp = client.post(token_url, json=body)

print(f"  HTTP {resp.status_code}")
print(f"  Headers: content-type={resp.headers.get('content-type', 'N/A')}")

try:
    data = resp.json()
except Exception:
    data = {"_raw": resp.text[:500]}

print(f"  Response body keys: {list(data.keys()) if isinstance(data, dict) else 'N/A'}")

if resp.status_code == 200:
    if "access_token" in data:
        token_prefix = data["access_token"][:20] if data.get("access_token") else "NONE"
        print(f"\n  ✅ AUTH SUCCESS — access_token starts with: {token_prefix}...")
    else:
        print(f"\n  ⚠️  HTTP 200 but no access_token in response: {json.dumps(data, indent=2, ensure_ascii=False)[:300]}")
elif resp.status_code == 403:
    err_code = data.get("error_code", data.get("code", "N/A"))
    err_msg = data.get("error_message", data.get("message", data.get("msg", "N/A")))
    print(f"\n  ❌ AUTH FAILED (HTTP 403)")
    print(f"     error_code : {err_code}")
    print(f"     error_msg  : {err_msg}")
else:
    print(f"\n  ❌ AUTH FAILED (HTTP {resp.status_code})")
    print(f"     {json.dumps(data, indent=2, ensure_ascii=False)[:500]}")

# Also test what URL the CODE would use (KIS_API_BASE_URLS dict)
from agent_trading.brokers.koreainvestment.rest_client import KIS_API_BASE_URLS
code_url = KIS_API_BASE_URLS.get(kis_env, "UNKNOWN")
print()
print("-" * 60)
print("Code path (KIS_API_BASE_URLS):")
print(f"  KIS_ENV={kis_env!r} -> base_url={code_url!r}")
print(f"  .env KIS_BASE_URL  = {kis_base_url!r}")
print(f"  Match: {'✅ YES - identical' if code_url == kis_base_url else '❌ DIFFERENT'}")
print("=" * 60)
