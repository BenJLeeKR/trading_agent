#!/usr/bin/env python3
"""Debug: inspect what DeepSeek returns for aggregate_view."""
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

deepseek_key = env_vars.get("DEEPSEEK_API_KEY", "")
print(f"DEEPSEEK_API_KEY = {'***set***' if deepseek_key else '***MISSING***'}")

async def main():
    async with httpx.AsyncClient(
        base_url="https://api.deepseek.com",
        timeout=httpx.Timeout(60.0),
    ) as client:
        system = "You are a financial analyst. Respond in JSON."
        user = """Analyze this event: Samsung Electronics (005930) Q1 2026 earnings beat estimates by 12%.

Return JSON with this exact structure:
{
  "schema_version": "v1",
  "agent_name": "event_interpretation",
  "symbol": "005930",
  "issuer_code": "KR7005930003",
  "events": [
    {
      "headline": "Earnings Beat",
      "event_type": "earnings",
      "severity": "positive",
      "confidence": 0.85,
      "reasoning": "Q1 2026 earnings exceeded consensus by 12%"
    }
  ],
  "aggregate_view": {
    "overall_bias": "bullish",
    "confidence": 0.80,
    "summary": "Strong earnings beat signals positive outlook"
  }
}"""

        body = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }

        resp = await client.post("/v1/chat/completions", json=body)
        resp.raise_for_status()
        data = resp.json()
        raw = data["choices"][0]["message"]["content"]
        
        print("=" * 60)
        print("RAW JSON from DeepSeek:")
        print("=" * 60)
        print(raw[:2000])
        print()
        
        parsed = json.loads(raw)
        print("=" * 60)
        print("Parsed keys:", list(parsed.keys()))
        print()
        
        av = parsed.get("aggregate_view")
        print(f"aggregate_view type: {type(av).__name__}")
        print(f"aggregate_view value: {json.dumps(av, indent=2, ensure_ascii=False)[:500]}")
        
        if isinstance(av, str):
            print("\n⚠️  aggregate_view IS a string! Trying json.loads...")
            try:
                av2 = json.loads(av)
                print(f"  After json.loads: type={type(av2).__name__}")
                print(f"  overall_bias={av2.get('overall_bias')}")
            except Exception as e:
                print(f"  Failed to parse: {e}")

asyncio.run(main())
