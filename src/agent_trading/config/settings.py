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
    "deepseek": "deepseek-v4-pro",
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
# KIS environment variable resolution (preferred name → legacy fallback)
# ---------------------------------------------------------------------------


def _resolve_kis_api_key() -> str:
    """Resolve KIS API key: ``KIS_APP_KEY`` preferred, fallback ``KIS_API_KEY``."""
    return os.getenv("KIS_APP_KEY") or os.getenv("KIS_API_KEY", "")


def _resolve_kis_api_secret() -> str:
    """Resolve KIS API secret: ``KIS_APP_SECRET`` preferred, fallback ``KIS_API_SECRET``."""
    return os.getenv("KIS_APP_SECRET") or os.getenv("KIS_API_SECRET", "")


def _resolve_kis_account_number() -> str:
    """Resolve KIS account number: ``KIS_ACCOUNT_NO`` preferred, fallback ``KIS_ACCOUNT_NUMBER``."""
    return os.getenv("KIS_ACCOUNT_NO") or os.getenv("KIS_ACCOUNT_NUMBER", "")


def _resolve_kis_env() -> str:
    """Read ``KIS_ENV`` and normalize ``"real"`` → ``"live"``.

    Returns ``"paper"`` when unset.
    """
    raw = os.getenv("KIS_ENV", "paper")
    return raw.strip().lower().replace("real", "live")


def _resolve_kis_real_rest_rps() -> int:
    """Resolve KIS real/live REST RPS: ``KIS_REAL_REST_RPS``, default 15.

    Clamped to ``max(1, value)`` to ensure a positive safety baseline.
    """
    raw = os.getenv("KIS_REAL_REST_RPS", "15")
    return max(1, int(raw))


def _resolve_kis_paper_rest_rps() -> int:
    """Resolve KIS paper REST RPS: ``KIS_PAPER_REST_RPS``, default 1.

    Clamped to ``max(1, value)`` to ensure a positive safety baseline.
    """
    raw = os.getenv("KIS_PAPER_REST_RPS", "1")
    return max(1, int(raw))


# ---------------------------------------------------------------------------
# Application settings
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class AppSettings:
    environment: Environment = Environment.PAPER
    app_name: str = "agent-trading"
    timezone: str = "Asia/Seoul"

    # ---- KIS API credentials (read from environment) -------------------------
    # Preferred naming (한국투자증권 actual): KIS_APP_KEY / KIS_APP_SECRET / KIS_ACCOUNT_NO
    # Legacy fallback:                       KIS_API_KEY / KIS_API_SECRET / KIS_ACCOUNT_NUMBER
    kis_api_key: str = field(default_factory=_resolve_kis_api_key)
    kis_api_secret: str = field(default_factory=_resolve_kis_api_secret)
    kis_account_number: str = field(default_factory=_resolve_kis_account_number)
    kis_account_product_code: str = field(default_factory=lambda: os.getenv("KIS_ACCOUNT_PRODUCT_CODE", "01"))
    kis_env: str = field(default_factory=_resolve_kis_env)
    kis_base_url: str = field(default_factory=lambda: os.getenv("KIS_BASE_URL", ""))

    # ---- KIS REST rate limit safety budget (env override) --------------------
    # ``KIS_REAL_REST_RPS`` (default 15) and ``KIS_PAPER_REST_RPS`` (default 1)
    # control the per-environment token-bucket refill rates in
    # ``RateLimitBudgetManager``.  These are **safety budget scaling baselines**,
    # not exact RPS guarantees — the 5-bucket distribution spreads the total
    # conservatively across AUTH / ORDER / INQUIRY / MARKET_DATA / RECONCILIATION.
    kis_real_rest_rps: int = field(default_factory=_resolve_kis_real_rest_rps)
    kis_paper_rest_rps: int = field(default_factory=_resolve_kis_paper_rest_rps)

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
