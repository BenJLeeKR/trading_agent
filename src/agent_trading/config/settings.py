from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from agent_trading.domain.enums import Environment

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM Provider environment variable resolution
# ---------------------------------------------------------------------------

_SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"deepseek", "openai"})

_PROVIDER_ENV_MAP: dict[str, dict[str, str]] = {
    "deepseek": {
        "api_key": "DEEPSEEK_API_KEY",
        "base_url": "DEEPSEEK_BASE_URL",
        "model_id": "DEEPSEEK_MODEL_ID",
        "timeout": "DEEPSEEK_TIMEOUT_SECONDS",
    },
    "openai": {
        "api_key": "OPENAI_API_KEY",
        "base_url": "OPENAI_BASE_URL",
        "model_id": "OPENAI_MODEL_ID",
        "timeout": "OPENAI_TIMEOUT_SECONDS",
    },
}

_PROVIDER_BASE_URL_DEFAULTS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
    "openai": "https://api.openai.com/v1",
}

_PROVIDER_MODEL_ID_DEFAULTS: dict[str, str] = {
    "deepseek": "deepseek-chat",
    "openai": "gpt-4o",
}


def _resolve_llm_provider() -> str:
    """Read and normalize ``LLM_PROVIDER``.

    Returns a validated, lowercased provider name (e.g. ``"deepseek"``,
    ``"openai"``), or an empty string when the value is not in the
    supported set.
    """
    raw = os.getenv("LLM_PROVIDER", "deepseek")
    provider = raw.strip().lower()
    if provider not in _SUPPORTED_PROVIDERS:
        logger.warning(
            "Unsupported LLM_PROVIDER=%r — using stub EventInterpretationAgent. "
            "Supported providers: %s",
            raw,
            ", ".join(sorted(_SUPPORTED_PROVIDERS)),
        )
        return ""
    return provider


def _resolve_provider_api_key() -> str:
    """Resolve the provider-agnostic ``provider_api_key``."""
    provider = _resolve_llm_provider()
    if not provider:
        return ""
    env_var = _PROVIDER_ENV_MAP[provider]["api_key"]
    return os.getenv(env_var, "")


def _resolve_provider_base_url() -> str:
    """Resolve the provider-agnostic ``provider_base_url``."""
    provider = _resolve_llm_provider()
    if not provider:
        return ""
    env_var = _PROVIDER_ENV_MAP[provider]["base_url"]
    return os.getenv(env_var, _PROVIDER_BASE_URL_DEFAULTS.get(provider, ""))


def _resolve_provider_model_id() -> str:
    """Resolve the provider-agnostic ``provider_model_id``."""
    provider = _resolve_llm_provider()
    if not provider:
        return ""
    env_var = _PROVIDER_ENV_MAP[provider]["model_id"]
    return os.getenv(env_var, _PROVIDER_MODEL_ID_DEFAULTS.get(provider, ""))


def _resolve_provider_timeout() -> int:
    """Resolve the provider-agnostic ``provider_timeout_seconds``."""
    provider = _resolve_llm_provider()
    if not provider:
        return 30
    env_var = _PROVIDER_ENV_MAP[provider]["timeout"]
    return int(os.getenv(env_var, "30"))


# ---------------------------------------------------------------------------
# Application settings
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class AppSettings:
    environment: Environment = Environment.PAPER
    app_name: str = "agent-trading"
    timezone: str = "Asia/Seoul"

    # ---- KIS API credentials (read from environment) -------------------------
    kis_api_key: str = field(default_factory=lambda: os.getenv("KIS_API_KEY", ""))
    kis_api_secret: str = field(default_factory=lambda: os.getenv("KIS_API_SECRET", ""))
    kis_account_number: str = field(default_factory=lambda: os.getenv("KIS_ACCOUNT_NUMBER", ""))
    kis_account_product_code: str = field(default_factory=lambda: os.getenv("KIS_ACCOUNT_PRODUCT_CODE", "01"))
    kis_env: str = field(default_factory=lambda: os.getenv("KIS_ENV", "paper"))

    # ---- OpenDART API credentials (read from environment) --------------------
    opendart_api_key: str = field(default_factory=lambda: os.getenv("OPENDART_API_KEY", ""))

    # ---- Provider AI (OpenAI-compatible) ------------------------------------
    # External env var names are provider-specific; internal fields are
    # provider-agnostic.  ``LLM_PROVIDER`` controls which set of env vars
    # is read (``DEEPSEEK_*`` or ``OPENAI_*``).
    llm_provider: str = field(default_factory=_resolve_llm_provider)
    provider_api_key: str = field(default_factory=_resolve_provider_api_key)
    provider_base_url: str = field(default_factory=_resolve_provider_base_url)
    provider_model_id: str = field(default_factory=_resolve_provider_model_id)
    provider_timeout_seconds: int = field(default_factory=_resolve_provider_timeout)

