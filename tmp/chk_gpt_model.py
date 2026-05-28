import os
import time
from dataclasses import dataclass, asdict
from typing import Optional, List

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])


CANDIDATE_MODELS = [
    "gpt-5.5",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5.1",
    "gpt-5.1-mini",
    "gpt-5.1-nano",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "gpt-4o",
    "gpt-4o-mini",
]


@dataclass
class ModelCheckResult:
    model: str
    visible_in_models_list: bool
    callable: bool
    status: str
    latency_sec: Optional[float]
    error_code: Optional[str]
    error_type: Optional[str]
    error_message: Optional[str]


def get_visible_models() -> set[str]:
    """
    현재 API Key/Project에서 models.list()에 보이는 모델 목록을 가져옵니다.
    단, 보인다고 해서 반드시 Responses API 호출이 성공한다는 뜻은 아닙니다.
    """
    models = client.models.list()
    return {m.id for m in models.data}


def classify_openai_error(e: Exception):
    """
    OpenAI SDK 예외에서 code/type/message를 최대한 안전하게 추출합니다.
    """
    error_code = None
    error_type = None
    error_message = str(e)

    body = getattr(e, "body", None)

    if isinstance(body, dict):
        err = body.get("error", {})
        error_code = err.get("code")
        error_type = err.get("type")
        error_message = err.get("message", error_message)

    return error_code, error_type, error_message


def test_model(model: str, visible_models: set[str]) -> ModelCheckResult:
    start = time.perf_counter()

    try:
        response = client.responses.create(
            model=model,
            input="ping",
            max_output_tokens=16,
            reasoning={"effort": "none"},
            text={"verbosity": "low"},
        )

        latency = time.perf_counter() - start

        return ModelCheckResult(
            model=model,
            visible_in_models_list=model in visible_models,
            callable=True,
            status="OK",
            latency_sec=latency,
            error_code=None,
            error_type=None,
            error_message=None,
        )

    except Exception as e:
        latency = time.perf_counter() - start
        error_code, error_type, error_message = classify_openai_error(e)

        if error_code == "insufficient_quota" or error_type == "insufficient_quota":
            status = "NO_QUOTA"
        elif error_code == "model_not_found":
            status = "MODEL_NOT_FOUND_OR_NO_ACCESS"
        elif error_type == "invalid_request_error":
            status = "INVALID_REQUEST"
        elif "rate limit" in str(e).lower():
            status = "RATE_LIMIT"
        else:
            status = "ERROR"

        return ModelCheckResult(
            model=model,
            visible_in_models_list=model in visible_models,
            callable=False,
            status=status,
            latency_sec=latency,
            error_code=error_code,
            error_type=error_type,
            error_message=error_message,
        )


def main():
    visible_models = get_visible_models()

    print(f"models.list()에서 확인된 모델 수: {len(visible_models)}")
    print()

    results: List[ModelCheckResult] = []

    for model in CANDIDATE_MODELS:
        print(f"Checking {model} ...")
        result = test_model(model, visible_models)
        results.append(result)

        if result.callable:
            print(f"  OK / {result.latency_sec:.3f}s")
        else:
            print(f"  {result.status} / {result.error_code} / {result.error_message}")

        time.sleep(0.5)

    df = pd.DataFrame([asdict(r) for r in results])

    print("\n===== RESULT =====")
    print(df.to_string(index=False))

    df.to_csv("openai_model_quota_check.csv", index=False, encoding="utf-8-sig")
    print("\nCSV 저장 완료: openai_model_quota_check.csv")


if __name__ == "__main__":
    main()