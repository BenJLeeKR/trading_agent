"""Smoke tests for the DeepSeek provider connection.

These tests make real HTTP calls to the DeepSeek API and require
``DEEPSEEK_API_KEY`` to be set in the environment.  They are skipped
automatically when the credential is absent.

Markers
-------
* ``smoke`` — all tests in this module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import pytest

from agent_trading.services.ai_agents.base import RawProviderResponse
from agent_trading.services.ai_agents.provider_client import (
    OpenAICompatibleClient,
)


# ---------------------------------------------------------------------------
# Minimal output schema for smoke tests
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class _SimpleOutput:
    """Minimal dataclass for smoke test response parsing."""
    symbol: str = ""
    score: float = 0.0


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------


@pytest.mark.smoke
@pytest.mark.skipif(
    not os.getenv("DEEPSEEK_API_KEY"),
    reason="DEEPSEEK_API_KEY not set — skipping real API call",
)
class TestDeepSeekSmoke:
    """Smoke tests against the real DeepSeek API."""

    @pytest.mark.asyncio
    async def test_chat_completion(self) -> None:
        """Real API call returns a valid response."""
        client = OpenAICompatibleClient(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            timeout_seconds=30,
        )
        try:
            result: RawProviderResponse = await client.generate_structured(
                model_id=os.getenv("DEEPSEEK_MODEL_ID", "deepseek-v4-pro"),
                system_prompt="You are a helpful assistant. Output valid JSON.",
                user_prompt='Return {"symbol": "TEST", "score": 0.5}',
                response_format=_SimpleOutput,
                temperature=0.0,
            )
            assert isinstance(result, RawProviderResponse)
            assert isinstance(result.parsed, _SimpleOutput)
            assert result.raw_content is not None
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_structured_output(self) -> None:
        """Real API call with ``json_object`` mode returns valid JSON."""
        client = OpenAICompatibleClient(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            timeout_seconds=30,
        )
        try:
            result: RawProviderResponse = await client.generate_structured(
                model_id=os.getenv("DEEPSEEK_MODEL_ID", "deepseek-v4-pro"),
                system_prompt=(
                    "You are a test assistant. "
                    "Always respond with valid JSON matching the schema."
                ),
                user_prompt="Return a JSON object with symbol='SMOKE' and score=0.99.",
                response_format=_SimpleOutput,
                temperature=0.0,
            )
            parsed = result.parsed
            assert parsed.symbol == "SMOKE"
            assert parsed.score == 0.99
        finally:
            await client.close()
