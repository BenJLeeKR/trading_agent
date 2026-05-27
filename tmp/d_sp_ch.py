import os
import time
import statistics
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

# 현재 파일 기준 한 단계 상위 폴더의 .env 로드
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)

client = OpenAI(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com",
)

MODELS = [
    "deepseek-chat",
    "deepseek-reasoner",
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    # 필요하면 /models 조회 결과를 보고 여기에 추가
]

PROMPTS = {
    "simple": "한국어로 300자 이내로 REST API와 WebSocket의 차이를 설명해줘.",
    "reasoning": (
        "다음 상황을 분석해줘. 사용자가 주식 자동매매 시스템을 만들고 있다. "
        "실시간 시세, 뉴스, 공시, 주문 API를 각각 어떤 기준으로 분리 설계해야 하는지 "
        "논리적으로 단계별로 설명해줘."
    ),
    "coding": (
        "Python으로 재시도, 지수 백오프, 타임아웃 처리가 포함된 API 호출 함수를 작성해줘. "
        "간단한 사용 예시도 포함해줘."
    ),
}

REPEAT = 5
MAX_TOKENS = 800


def run_once(model: str, prompt_name: str, prompt: str):
    start = time.perf_counter()
    first_token_time = None
    output_text = ""

    stream = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a precise Korean technical assistant."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=MAX_TOKENS,
        temperature=0.2,
        stream=True,
    )

    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            if first_token_time is None:
                first_token_time = time.perf_counter()
            output_text += delta

    end = time.perf_counter()

    ttft = None if first_token_time is None else first_token_time - start
    total_latency = end - start

    # 정확한 토큰 수는 usage가 stream에서 안 잡힐 수 있어 문자 기반 근사도 함께 기록
    approx_output_chars = len(output_text)
    approx_tokens = max(1, approx_output_chars / 2.8)  # 한국어 기준 아주 거친 근사
    tokens_per_sec = approx_tokens / total_latency if total_latency > 0 else None

    return {
        "model": model,
        "prompt_type": prompt_name,
        "ttft_sec": ttft,
        "total_latency_sec": total_latency,
        "approx_output_chars": approx_output_chars,
        "approx_output_tokens": approx_tokens,
        "approx_tokens_per_sec": tokens_per_sec,
        "output_preview": output_text[:120].replace("\n", " "),
    }


def summarize(df: pd.DataFrame):
    rows = []

    for (model, prompt_type), g in df.groupby(["model", "prompt_type"]):
        rows.append({
            "model": model,
            "prompt_type": prompt_type,
            "runs": len(g),
            "avg_ttft_sec": g["ttft_sec"].mean(),
            "median_ttft_sec": g["ttft_sec"].median(),
            "p95_ttft_sec": g["ttft_sec"].quantile(0.95),
            "avg_total_latency_sec": g["total_latency_sec"].mean(),
            "median_total_latency_sec": g["total_latency_sec"].median(),
            "p95_total_latency_sec": g["total_latency_sec"].quantile(0.95),
            "avg_tokens_per_sec": g["approx_tokens_per_sec"].mean(),
            "median_tokens_per_sec": g["approx_tokens_per_sec"].median(),
        })

    return pd.DataFrame(rows)


def main():
    results = []

    for model in MODELS:
        for prompt_name, prompt in PROMPTS.items():
            for i in range(REPEAT):
                print(f"Running: model={model}, prompt={prompt_name}, run={i + 1}/{REPEAT}")
                try:
                    result = run_once(model, prompt_name, prompt)
                    result["run"] = i + 1
                    results.append(result)
                except Exception as e:
                    results.append({
                        "model": model,
                        "prompt_type": prompt_name,
                        "run": i + 1,
                        "error": repr(e),
                    })
                time.sleep(1)

    df = pd.DataFrame(results)
    df.to_csv("deepseek_latency_raw.csv", index=False, encoding="utf-8-sig")

    ok = df[df["error"].isna()] if "error" in df.columns else df
    summary = summarize(ok)
    summary.to_csv("deepseek_latency_summary.csv", index=False, encoding="utf-8-sig")

    print("\n=== Summary ===")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()