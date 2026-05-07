#!/usr/bin/env python3
"""Debug: check what KIS oauth2/tokenP actually returns when using base_url."""
import asyncio, json, httpx
from pathlib import Path

env_path = Path(__file__).resolve().parent / ".env"
env_vars: dict[str, str] = {}
for line in env_path.read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, _, val = line.partition("=")
    env_vars[key.strip()] = val.strip().strip('"').strip("'")

kis_base_url = env_vars.get("KIS_BASE_URL", "")
kis_api_key = env_vars.get("KIS_API_KEY", "")
kis_api_secret = env_vars.get("KIS_API_SECRET", "")

async def main():
    print("=" * 60)
    print("Debug: KIS oauth2/tokenP response with base_url")
    print("=" * 60)
    print(f"Base URL: {kis_base_url}")
    print(f"API Key: {kis_api_key[:8]}...{kis_api_key[-4:]}")
    print()

    # Test: reuse same client (like KISRestClient does)
    print("--- Test: reuse same client with base_url ---")
    async with httpx.AsyncClient(base_url=kis_base_url, timeout=httpx.Timeout(15.0)) as client:
        body = {
            "grant_type": "client_credentials",
            "appkey": kis_api_key,
            "appsecret": kis_api_secret,
        }
        
        # First attempt
        print("\nAttempt 1:")
        resp = await client.post("/oauth2/tokenP", json=body)
        print(f"  HTTP {resp.status_code}")
        print(f"  Response headers: {dict(resp.headers)}")
        print(f"  Response body: {resp.text[:500]}")
        
        if resp.status_code == 200:
            data = resp.json()
            print(f"  ✅ SUCCESS - access_token: {data.get('access_token', 'N/A')[:30]}...")
        else:
            print(f"  ❌ FAILED")
            try:
                data = resp.json()
                print(f"  Parsed JSON: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}")
            except Exception:
                print(f"  Raw text: {resp.text[:500]}")
        
        # Second attempt (to check rate limit)
        print("\nAttempt 2 (immediately after):")
        resp2 = await client.post("/oauth2/tokenP", json=body)
        print(f"  HTTP {resp2.status_code}")
        print(f"  Response body: {resp2.text[:500]}")
        if resp2.status_code == 200:
            data2 = resp2.json()
            print(f"  ✅ SUCCESS - access_token: {data2.get('access_token', 'N/A')[:30]}...")
        else:
            print(f"  ❌ FAILED")
            try:
                data2 = resp2.json()
                print(f"  Parsed JSON: {json.dumps(data2, indent=2, ensure_ascii=False)[:500]}")
            except Exception:
                print(f"  Raw text: {resp2.text[:500]}")

asyncio.run(main())
