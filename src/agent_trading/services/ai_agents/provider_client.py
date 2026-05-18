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


def _coerce_nested_json_strings(
    dataclass_type: type, data: dict[str, Any]
) -> dict[str, Any]:
    """Recursively coerce JSON-string fields into dicts for nested dataclass fields.

    Some providers (e.g. DeepSeek) may return nested objects as serialised JSON
    strings instead of proper nested JSON objects.  This function detects such
    fields by inspecting the dataclass type's field annotations and, when a field
    value is a string but the target type is a dataclass (or tuple of dataclasses),
    parses the string with ``json.loads`` and recurses.

    .. note::
        Uses ``typing.get_type_hints()`` to resolve string annotations that arise
        from ``from __future__ import annotations``, which makes all annotations
        strings at runtime.
    """
    import dataclasses
    import typing

    # Resolve string annotations to actual types (handles ``from __future__ import annotations``).
    try:
        resolved_hints = typing.get_type_hints(dataclass_type)
    except Exception:
        resolved_hints = {}

    for f in dataclasses.fields(dataclass_type):
        # Use the resolved type hint if available, otherwise fall back to f.type
        field_type = resolved_hints.get(f.name, f.type)
        origin = getattr(field_type, "__origin__", None)
        value = data.get(f.name)

        if value is None or isinstance(value, (int, float, bool)):
            continue

        # Nested dataclass field — value should be a dict, but may be a JSON string
        if hasattr(field_type, "__dataclass_fields__"):
            if isinstance(value, str):
                try:
                    data[f.name] = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    pass  # leave as-is, will fail at construction
            if isinstance(data.get(f.name), dict):
                coerced = _coerce_nested_json_strings(
                    field_type, data[f.name]
                )
                try:
                    data[f.name] = field_type(**coerced)
                except (TypeError, ValueError):
                    data[f.name] = coerced  # fallback: keep as dict

        # Tuple of dataclasses — value should be a list, but items may be JSON strings
        elif origin is tuple:
            args = getattr(field_type, "__args__", ())
            if args and hasattr(args[0], "__dataclass_fields__") and isinstance(value, list):
                elem_type = args[0]
                coerced: list[dict[str, Any]] = []
                for item in value:
                    if isinstance(item, str):
                        try:
                            item = json.loads(item)
                        except (json.JSONDecodeError, TypeError):
                            pass
                    if isinstance(item, dict):
                        coerced.append(_coerce_nested_json_strings(elem_type, item))
                    else:
                        coerced.append(item)  # type: ignore[arg-type]
                data[f.name] = coerced

    return data


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
        """Lazy-initialise the HTTP client with granular timeouts.

        Timeout breakdown
        -----------------
        * ``connect=10.0``  — fail fast on network issues
        * ``read=25.0``    — aligned with per-agent timeout (25s) in
                             ``decision_orchestrator._run_agents()``
        * ``write=10.0``   — generous write window
        * ``pool=10.0``    — connection pool acquisition timeout
        """
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=25.0,
                    write=10.0,
                    pool=10.0,
                ),
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
            The model identifier (e.g. ``"deepseek-v4-pro"``).
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

        # Recursively coerce nested JSON strings into dicts for nested dataclass fields.
        # Some providers (e.g. DeepSeek) may return nested objects as serialised JSON
        # strings instead of proper nested JSON objects.
        parsed_dict = _coerce_nested_json_strings(response_format, parsed_dict)

        parsed = response_format(**parsed_dict)

        return RawProviderResponse(parsed=parsed, raw_content=raw_content)

    async def close(self) -> None:
        """Release the underlying HTTP client connection."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
