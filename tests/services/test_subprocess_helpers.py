from __future__ import annotations

import json
from uuid import uuid4

from agent_trading.services.ai_agents.base import AgentExecutionRequest
from agent_trading.services.common_types import AIPolicyContextView, ScoreResult
from agent_trading.services.subprocess_helpers import serialize_agent_input


def test_serialize_agent_input_prefers_injected_provider_runtime() -> None:
    request = AgentExecutionRequest(
        decision_context_id=uuid4(),
        correlation_id="corr-1",
        context=AIPolicyContextView(),
        symbol="005930",
        market="KRX",
    )
    provider_runtime = {
        "llm_provider": "gemini",
        "provider_api_key": "gemini-key",
        "provider_base_url": "https://example.test/v1beta/openai/",
        "provider_model_id": "gemini-3.5-flash",
        "provider_timeout_seconds": 77,
    }

    payload = json.loads(
        serialize_agent_input(
            request=request,
            context=AIPolicyContextView(),
            score=ScoreResult(),
            provider_runtime=provider_runtime,
        )
    )

    assert payload["llm_provider"] == "gemini"
    assert payload["provider_api_key"] == "gemini-key"
    assert payload["provider_base_url"] == "https://example.test/v1beta/openai/"
    assert payload["provider_model_id"] == "gemini-3.5-flash"
    assert payload["provider_timeout_seconds"] == 77
