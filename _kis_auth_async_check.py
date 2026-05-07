#!/usr/bin/env python3
"""KIS Paper auth check — async httpx test to match KISRestClient behavior."""
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

async def test_auth():
    print("=" * 60)
    print("Async httpx auth test (matching KISRestClient behavior)")
    print("=" * 60)
    
    # Test 1: json=body with explicit full URL
    print("\n--- Test 1: json=body, explicit full URL ---")
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        body = {
            "grant_type": "client_credentials",
            "appkey": kis_api_key,
            "appsecret": kis_api_secret,
        }
        url = f"{kis_base_url}/oauth2/tokenP"
        resp = await client.post(url, json=body)
        print(f"  HTTP {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"  ✅ SUCCESS - access_token: {data.get('access_token', 'N/A')[:30]}...")
        else:
            print(f"  ❌ FAILED - {resp.text[:300]}")
    
    # Test 2: json=body with base_url on client
    print("\n--- Test 2: json=body, base_url on client ---")
    async with httpx.AsyncClient(base_url=kis_base_url, timeout=httpx.Timeout(15.0)) as client:
        body = {
            "grant_type": "client_credentials",
            "appkey": kis_api_key,
            "appsecret": kis_api_secret,
        }
        resp = await client.post("/oauth2/tokenP", json=body)
        print(f"  HTTP {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"  ✅ SUCCESS - access_token: {data.get('access_token', 'N/A')[:30]}...")
        else:
            print(f"  ❌ FAILED - {resp.text[:300]}")
    
    # Test 3: data=body (form-encoded) with base_url on client
    print("\n--- Test 3: data=body (form), base_url on client ---")
    async with httpx.AsyncClient(base_url=kis_base_url, timeout=httpx.Timeout(15.0)) as client:
        body = {
            "grant_type": "client_credentials",
            "appkey": kis_api_key,
            "appsecret": kis_api_secret,
        }
        resp = await client.post("/oauth2/tokenP", data=body)
        print(f"  HTTP {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"  ✅ SUCCESS - access_token: {data.get('access_token', 'N/A')[:30]}...")
        else:
            print(f"  ❌ FAILED - {resp.text[:300]}")
    
    # Test 4: json=body with content-type header explicitly
    print("\n--- Test 4: json=body, explicit content-type ---")
    async with httpx.AsyncClient(base_url=kis_base_url, timeout=httpx.Timeout(15.0)) as client:
        body = {
            "grant_type": "client_credentials",
            "appkey": kis_api_key,
            "appsecret": kis_api_secret,
        }
        resp = await client.post(
            "/oauth2/tokenP", 
            json=body,
            headers={"content-type": "application/json"}
        )
        print(f"  HTTP {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"  ✅ SUCCESS - access_token: {data.get('access_token', 'N/A')[:30]}...")
        else:
            print(f"  ❌ FAILED - {resp.text[:300]}")

asyncio.run(test_auth())
