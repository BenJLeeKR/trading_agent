#!/usr/bin/env python3
"""Measure deepseek-chat API latency with a minimal prompt."""
import os, sys, time, json
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

# .env 파일 로드 (tmp/d_sp_ch.py와 동일한 방식)
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)

# 환경변수에서 설정 읽기
api_key = os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or ""
base_url = os.environ.get("LLM_BASE_URL") or os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com"
model_id = os.environ.get("LLM_MODEL_ID") or os.environ.get("DEEPSEEK_MODEL_ID") or "deepseek-chat"

print(f"=== deepseek-chat Latency Measurement ===")
print(f"Model: {model_id}")
print(f"Base URL: {base_url}")
print(f"API Key set: {'yes' if api_key else 'no'}")

if not api_key:
    print("ERROR: No API key found")
    sys.exit(1)

client = OpenAI(api_key=api_key, base_url=base_url)

# Test 1: Minimal prompt (EI-style - short context)
prompt_short = "What is 2+2?"
print(f"\n--- Test 1: Short prompt ---")
for i in range(3):
    start = time.time()
    try:
        resp = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": prompt_short}],
            max_tokens=50,
            temperature=0.0,
        )
        elapsed = time.time() - start
        content = resp.choices[0].message.content
        tokens_in = resp.usage.prompt_tokens if resp.usage else '?'
        tokens_out = resp.usage.completion_tokens if resp.usage else '?'
        print(f"  Run {i+1}: {elapsed:.2f}s (in={tokens_in}, out={tokens_out}) | response: {content[:50]}")
    except Exception as e:
        elapsed = time.time() - start
        print(f"  Run {i+1}: FAILED after {elapsed:.2f}s - {e}")

# Test 2: Longer prompt (AR/FDC-style - with context)
prompt_long = "Analyze the following market events for Korean stock market today..." + (" x" * 500)
print(f"\n--- Test 2: Long prompt (~1K tokens) ---")
for i in range(3):
    start = time.time()
    try:
        resp = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": prompt_long}],
            max_tokens=200,
            temperature=0.0,
        )
        elapsed = time.time() - start
        tokens_in = resp.usage.prompt_tokens if resp.usage else '?'
        tokens_out = resp.usage.completion_tokens if resp.usage else '?'
        print(f"  Run {i+1}: {elapsed:.2f}s (in={tokens_in}, out={tokens_out})")
    except Exception as e:
        elapsed = time.time() - start
        print(f"  Run {i+1}: FAILED after {elapsed:.2f}s - {e}")

# Test 3: What does DEEPSEEK_MODEL_ID env var say?
print(f"\n--- Env Vars ---")
for var in ['LLM_PROVIDER', 'LLM_MODEL_ID', 'LLM_API_KEY', 'LLM_BASE_URL', 'DEEPSEEK_MODEL_ID', 'DEEPSEEK_API_KEY']:
    val = os.environ.get(var, '')
    masked = val[:8] + '...' if len(val) > 10 and ('KEY' in var or 'SECRET' in var) else val
    print(f"  {var}={masked}")

print(f"\n=== Measurement Complete ===")
