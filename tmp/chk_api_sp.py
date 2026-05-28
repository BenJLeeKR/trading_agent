import os
import time
import statistics
from dataclasses import dataclass, asdict
from typing import Optional, Callable, Dict, Any, List

import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

from openai import OpenAI
from google import genai
from google.genai import types

# 현재 파일 기준 한 단계 상위 폴더의 .env 로드
#env_path = Path(__file__).resolve().parent.parent / ".env"
#load_dotenv(env_path)

load_dotenv()


# =========================
# 설정값
# =========================

PROMPT = """
다음 문장을 5문장 이내로 요약해줘.

인공지능 API의 응답 속도는 모델 크기, 서버 부하, 네트워크 지연, 출력 토큰 수,
추론 방식, 지역별 라우팅, 스트리밍 여부 등에 따라 달라질 수 있다.
따라서 공정한 비교를 위해서는 동일한 프롬프트, 동일한 출력 토큰 제한,
반복 측정, 워밍업 호출, 실패율 측정이 필요하다.
"""

RUNS = 5
WARMUP = 1
MAX_OUTPUT_TOKENS = 300
TEMPERATURE = 0


MODELS = {
    "openai": "gpt-5.5",
    "deepseek": "deepseek-chat",
    "gemini": "gemini-3.5-flash",
}


# =========================
# 결과 구조
# =========================

@dataclass
class BenchResult:
    provider: str
    model: str
    run_index: int
    ok: bool
    latency_sec: Optional[float]
    output_tokens: Optional[int]
    tokens_per_sec: Optional[float]
    text_chars: Optional[int]
    error: Optional[str]


# =========================
# 클라이언트
# =========================

openai_client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY")
)

deepseek_client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

gemini_client = genai.Client(
    api_key=os.environ.get("GEMINI_API_KEY")
)


# =========================
# 각 API 호출 함수
# =========================

def call_openai(prompt: str, model: str) -> Dict[str, Any]:
    """
    OpenAI Responses API 기준.
    """
    response = openai_client.responses.create(
        model=model,
        input=prompt,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        temperature=TEMPERATURE,
    )

    text = getattr(response, "output_text", "") or ""

    usage = getattr(response, "usage", None)
    output_tokens = None

    if usage is not None:
        output_tokens = getattr(usage, "output_tokens", None)

    return {
        "text": text,
        "output_tokens": output_tokens,
    }


def call_deepseek(prompt: str, model: str) -> Dict[str, Any]:
    """
    DeepSeek는 OpenAI 호환 Chat Completions 형식 사용.
    """
    response = deepseek_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": prompt}
        ],
        max_tokens=MAX_OUTPUT_TOKENS,
        temperature=TEMPERATURE,
    )

    text = response.choices[0].message.content or ""

    output_tokens = None
    if response.usage is not None:
        output_tokens = getattr(response.usage, "completion_tokens", None)

    return {
        "text": text,
        "output_tokens": output_tokens,
    }


def call_gemini(prompt: str, model: str) -> Dict[str, Any]:
    """
    Google Gen AI SDK 기준.
    """
    response = gemini_client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=MAX_OUTPUT_TOKENS,
            temperature=TEMPERATURE,
        ),
    )

    text = response.text or ""

    output_tokens = None
    usage = getattr(response, "usage_metadata", None)

    if usage is not None:
        output_tokens = getattr(usage, "candidates_token_count", None)

    return {
        "text": text,
        "output_tokens": output_tokens,
    }


CALLERS: Dict[str, Callable[[str, str], Dict[str, Any]]] = {
    "openai": call_openai,
    "deepseek": call_deepseek,
    "gemini": call_gemini,
}


# =========================
# 벤치마크 함수
# =========================

def benchmark_one(provider: str, model: str, run_index: int) -> BenchResult:
    caller = CALLERS[provider]

    start = time.perf_counter()

    try:
        result = caller(PROMPT, model)
        end = time.perf_counter()

        latency = end - start
        text = result.get("text", "")
        output_tokens = result.get("output_tokens")

        tokens_per_sec = None
        if output_tokens is not None and latency > 0:
            tokens_per_sec = output_tokens / latency

        return BenchResult(
            provider=provider,
            model=model,
            run_index=run_index,
            ok=True,
            latency_sec=latency,
            output_tokens=output_tokens,
            tokens_per_sec=tokens_per_sec,
            text_chars=len(text),
            error=None,
        )

    except Exception as e:
        end = time.perf_counter()

        return BenchResult(
            provider=provider,
            model=model,
            run_index=run_index,
            ok=False,
            latency_sec=end - start,
            output_tokens=None,
            tokens_per_sec=None,
            text_chars=None,
            error=str(e),
        )


def run_benchmark() -> pd.DataFrame:
    results: List[BenchResult] = []

    for provider, model in MODELS.items():
        print(f"\n===== {provider} / {model} =====")

        for i in range(WARMUP):
            print(f"Warmup {i + 1}/{WARMUP}")
            _ = benchmark_one(provider, model, run_index=-1)

        for i in range(RUNS):
            print(f"Run {i + 1}/{RUNS}")
            result = benchmark_one(provider, model, run_index=i + 1)
            results.append(result)

            if result.ok:
                print(
                    f"  latency={result.latency_sec:.3f}s, "
                    f"tokens={result.output_tokens}, "
                    f"tok/s={result.tokens_per_sec}"
                )
            else:
                print(f"  ERROR: {result.error}")

    return pd.DataFrame([asdict(r) for r in results])


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    for (provider, model), group in df.groupby(["provider", "model"]):
        ok_group = group[group["ok"] == True]

        total = len(group)
        success = len(ok_group)
        fail = total - success

        if success == 0:
            rows.append({
                "provider": provider,
                "model": model,
                "success": success,
                "fail": fail,
                "avg_latency_sec": None,
                "median_latency_sec": None,
                "min_latency_sec": None,
                "max_latency_sec": None,
                "avg_output_tokens": None,
                "avg_tokens_per_sec": None,
            })
            continue

        rows.append({
            "provider": provider,
            "model": model,
            "success": success,
            "fail": fail,
            "avg_latency_sec": ok_group["latency_sec"].mean(),
            "median_latency_sec": ok_group["latency_sec"].median(),
            "min_latency_sec": ok_group["latency_sec"].min(),
            "max_latency_sec": ok_group["latency_sec"].max(),
            "avg_output_tokens": ok_group["output_tokens"].mean(),
            "avg_tokens_per_sec": ok_group["tokens_per_sec"].mean(),
        })

    summary_df = pd.DataFrame(rows)

    return summary_df.sort_values(
        by=["avg_latency_sec"],
        ascending=True,
        na_position="last"
    )


if __name__ == "__main__":
    raw_df = run_benchmark()
    summary_df = summarize(raw_df)

    print("\n\n===== RAW RESULTS =====")
    print(raw_df.to_string(index=False))

    print("\n\n===== SUMMARY =====")
    print(summary_df.to_string(index=False))

    raw_df.to_csv("api_speed_raw_results.csv", index=False, encoding="utf-8-sig")
    summary_df.to_csv("api_speed_summary.csv", index=False, encoding="utf-8-sig")

    print("\nCSV 저장 완료:")
    print("- api_speed_raw_results.csv")
    print("- api_speed_summary.csv")