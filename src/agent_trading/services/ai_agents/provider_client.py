"""HTTP-based OpenAI-compatible provider client.

Implements the ``AIProviderClient`` protocol using raw HTTP calls
(no SDK dependency).  Works with DeepSeek, OpenAI, Ollama, or any
OpenAI-compatible chat completion endpoint.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from agent_trading.services.ai_agents.base import AIProviderClient, RawProviderResponse

logger = logging.getLogger(__name__)


class OpenAICompatibleClient:
    """HTTP-based OpenAI-compatible provider client.

    Implements ``AIProviderClient`` protocol.  Uses ``httpx.AsyncClient``
    to send chat completion requests and parse JSON responses.

    Parameters
    ----------
    api_key
        The API key for authentication (``Authorization: Bearer <key>``).
    base_url
        The base URL of the OpenAI-compatible endpoint
        (e.g. ``"https://api.deepseek.com"``).
    timeout_seconds
        Timeout for HTTP requests in seconds.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        timeout_seconds: int = 30,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy-initialise the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(self._timeout),
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        return self._client

    async def generate_structured(
        self,
        *,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        response_format: type,
        temperature: float = 0.0,
        seed: int | None = None,
    ) -> RawProviderResponse:
        """Send a chat completion request and return the parsed response.

        Parameters
        ----------
        model_id
            The model identifier (e.g. ``"deepseek-chat"``).
        system_prompt
            The system-level instruction for the model.
        user_prompt
            The user / context prompt.
        response_format
            A dataclass type to parse the JSON response into.
        temperature
            Sampling temperature (default ``0.0``).
        seed
            Optional seed for reproducible sampling.

        Returns
        -------
        RawProviderResponse
            Wrapper containing both the parsed dataclass instance and the
            raw JSON string from the provider.

        Raises
        ------
        httpx.HTTPStatusError
            On HTTP 4xx/5xx responses.
        json.JSONDecodeError
            On invalid JSON in the response body.
        TypeError / ValueError
            On dataclass construction failure.
        """
        client = await self._get_client()

        body: dict[str, Any] = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        if seed is not None:
            body["seed"] = seed

        response = await client.post("/v1/chat/completions", json=body)
        response.raise_for_status()
        data = response.json()
        raw_content: str = data["choices"][0]["message"]["content"]

        # Parse JSON into the target dataclass
        parsed_dict = json.loads(raw_content)
        parsed = response_format(**parsed_dict)

        return RawProviderResponse(parsed=parsed, raw_content=raw_content)

    async def close(self) -> None:
        """Release the underlying HTTP client connection."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
