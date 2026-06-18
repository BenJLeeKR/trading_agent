from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from decimal import Decimal

from agent_trading.domain.enums import Environment

logger = logging.getLogger(__name__)

KIS_DEFAULT_REST_URLS: dict[str, str] = {
    "live": "https://openapi.koreainvestment.com:9443",
    "paper": "https://openapivts.koreainvestment.com:29443",
}

KIS_DEFAULT_WS_URLS: dict[str, str] = {
    "live": "ws://ops.koreainvestment.com:21000",
    "paper": "ws://ops.koreainvestment.com:31000",
}

# ---------------------------------------------------------------------------
# LLM Provider environment variable resolution
# ---------------------------------------------------------------------------

_SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"deepseek", "openai", "gemini"})

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
    "gemini": {
        "api_key": "GEMINI_API_KEY",
        "base_url": "GEMINI_BASE_URL",
        "model_id": "GEMINI_MODEL_ID",
        "timeout": "GEMINI_TIMEOUT_SECONDS",
    },
}

_PROVIDER_BASE_URL_DEFAULTS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}

_PROVIDER_MODEL_ID_DEFAULTS: dict[str, str] = {
    "deepseek": "deepseek-chat",
    "openai": "gpt-4o",
    "gemini": "gemini-3.5-flash",
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


def resolve_provider_runtime_config() -> dict[str, str | int]:
    """현재 ``LLM_PROVIDER`` 기준 provider 런타임 설정을 반환한다."""
    return {
        "llm_provider": _resolve_llm_provider(),
        "provider_api_key": _resolve_provider_api_key(),
        "provider_base_url": _resolve_provider_base_url(),
        "provider_model_id": _resolve_provider_model_id(),
        "provider_timeout_seconds": _resolve_provider_timeout(),
    }


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


def _resolve_kis_base_url() -> str:
    """Resolve KIS REST base URL with env-aware safety normalization.

    ``KIS_BASE_URL`` is treated as an explicit override only when it matches
    the selected ``KIS_ENV`` family.  This prevents a common misconfiguration
    where ``KIS_ENV=live`` is paired with the paper VTS endpoint from an old
    ``.env`` template.
    """
    raw = os.getenv("KIS_BASE_URL", "").strip()
    env = _resolve_kis_env()
    if not raw:
        return KIS_DEFAULT_REST_URLS[env]
    if env == "live" and "openapivts.koreainvestment.com" in raw:
        logger.warning(
            "KIS_BASE_URL=%r points to paper VTS while KIS_ENV=live. "
            "Ignoring explicit override and using live default base URL.",
            raw,
        )
        return KIS_DEFAULT_REST_URLS[env]
    if env == "paper" and "openapi.koreainvestment.com:9443" in raw and "openapivts" not in raw:
        logger.warning(
            "KIS_BASE_URL=%r points to live REST while KIS_ENV=paper. "
            "Ignoring explicit override and using paper default base URL.",
            raw,
        )
        return KIS_DEFAULT_REST_URLS[env]
    return raw


def _resolve_kis_ws_url() -> str:
    """Resolve KIS WebSocket URL with env-aware safety normalization."""
    raw = os.getenv("KIS_WS_URL", "").strip()
    env = _resolve_kis_env()
    if not raw:
        return KIS_DEFAULT_WS_URLS[env]
    if env == "live" and raw.endswith(":31000"):
        logger.warning(
            "KIS_WS_URL=%r looks like the paper websocket endpoint while KIS_ENV=live. "
            "Ignoring explicit override.",
            raw,
        )
        return KIS_DEFAULT_WS_URLS[env]
    if env == "paper" and raw.endswith(":21000"):
        logger.warning(
            "KIS_WS_URL=%r looks like the live websocket endpoint while KIS_ENV=paper. "
            "Ignoring explicit override.",
            raw,
        )
        return KIS_DEFAULT_WS_URLS[env]
    return raw


def _resolve_kis_real_rest_rps() -> int:
    """Resolve KIS real/live REST RPS: ``KIS_REAL_REST_RPS``, default 18.

    Updated to 18 per KIS official notice (2026-04-20): 실전 REST 계좌당
    초당 18건.  ``KIS_REAL_REST_RPS`` env var overrides the default.

    Clamped to ``max(1, value)`` to ensure a positive safety baseline.
    """
    raw = os.getenv("KIS_REAL_REST_RPS", "18")
    return max(1, int(raw))


def _resolve_kis_paper_rest_rps() -> int:
    """Resolve KIS paper REST RPS: ``KIS_PAPER_REST_RPS`` env var; defaults to ``"1"`` for paper.

    Clamped to ``max(1, value)`` to ensure a positive safety baseline.
    """
    raw = os.getenv("KIS_PAPER_REST_RPS", "1")
    return max(1, int(raw))


def _resolve_kis_dev_token_cache_enabled() -> bool:
    """Resolve dev token cache enabled flag from ``KIS_DEV_TOKEN_CACHE_ENABLED``.

    Disabled by default.  Must be explicitly set to ``"true"`` for paper/dev.
    When ``KIS_ENV=live``, this setting is **ignored** — the cache is
    always disabled in production.
    """
    raw = os.getenv("KIS_DEV_TOKEN_CACHE_ENABLED", "false")
    return raw.strip().lower() == "true"


def _resolve_kis_dev_token_cache_path() -> str:
    """Resolve dev token cache file path from ``KIS_DEV_TOKEN_CACHE_PATH``.

    Default: ``.cache/kis_token.json`` (relative to project root or cwd).
    """
    return os.getenv("KIS_DEV_TOKEN_CACHE_PATH", ".cache/kis_token.json")


def _resolve_kis_shared_budget_file() -> str:
    """Resolve shared paper global budget file from ``KIS_SHARED_BUDGET_FILE``.

    Default: ``.cache/kis_paper_global_budget.json``.
    The file is only used in ``KIS_ENV=paper`` paths that opt into the
    shared cross-process global REST bucket.
    """
    return os.getenv(
        "KIS_SHARED_BUDGET_FILE",
        ".cache/kis_paper_global_budget.json",
    )


def _resolve_kis_live_token_cache_enabled() -> bool:
    """Resolve live-info token cache enabled flag from ``KIS_LIVE_TOKEN_CACHE_ENABLED``.

    Live-info token cache is used for WebSocket approval key persistence.
    Disabled by default.
    """
    raw = os.getenv("KIS_LIVE_TOKEN_CACHE_ENABLED", "false")
    return raw.strip().lower() == "true"


def _resolve_kis_live_token_cache_path() -> str:
    """Resolve live-info token cache file path from ``KIS_LIVE_TOKEN_CACHE_PATH``.

    Default: ``.cache/kis_live_token.json`` (separate from dev token cache).
    """
    return os.getenv("KIS_LIVE_TOKEN_CACHE_PATH", ".cache/kis_live_token.json")


def _resolve_kis_approval_key_cache_enabled() -> bool:
    """Resolve REST trading approval-key file cache enabled flag.

    Disabled by default for conservative rollout.
    """
    raw = os.getenv("KIS_APPROVAL_KEY_CACHE_ENABLED", "false")
    return raw.strip().lower() == "true"


def _resolve_kis_approval_key_cache_path() -> str:
    """Resolve REST trading approval-key cache file path."""
    return os.getenv(
        "KIS_APPROVAL_KEY_CACHE_PATH",
        ".cache/kis_rest_approval_key.json",
    )


# ---------------------------------------------------------------------------
# KIS disclosure (live 전용 공시 제목) 설정
# ---------------------------------------------------------------------------


def _resolve_kis_live_app_key() -> str | None:
    """Resolve live disclosure API key from ``KIS_LIVE_INFO_APP_KEY``.

    Uses the same credential as the live-info read-only client.
    Returns ``None`` when unset (disclosure 기능 비활성화).
    """
    return os.getenv("KIS_LIVE_INFO_APP_KEY") or None


def _resolve_kis_live_app_secret() -> str | None:
    """Resolve live disclosure API secret from ``KIS_LIVE_INFO_APP_SECRET``.

    Uses the same credential as the live-info read-only client.
    Returns ``None`` when unset (disclosure 기능 비활성화).
    """
    return os.getenv("KIS_LIVE_INFO_APP_SECRET") or None


def _resolve_kis_disclosure_token_cache_path() -> str:
    """Resolve disclosure token cache file path from ``KIS_DISCLOSURE_TOKEN_CACHE_PATH``.

    Default: ``.cache/kis_disclosure_token.json`` (기본 dev/paper cache와 충돌 방지).
    """
    return os.getenv("KIS_DISCLOSURE_TOKEN_CACHE_PATH", ".cache/kis_disclosure_token.json")


def _resolve_kis_disclosure_token_cache_enabled() -> bool:
    """Resolve disclosure token cache enabled flag from ``KIS_DISCLOSURE_TOKEN_CACHE_ENABLED``.

    Enabled by default (live token 만료 86400s 고려).
    """
    raw = os.getenv("KIS_DISCLOSURE_TOKEN_CACHE_ENABLED", "true")
    return raw.strip().lower() == "true"


# ---------------------------------------------------------------------------
# NAVER Search API settings (news search)
# ---------------------------------------------------------------------------


def _resolve_naver_client_id() -> str:
    """Resolve NAVER Search API client ID from ``NAVER_CLIENT_ID``.

    Returns empty string when unset (news search 기능 비활성화).
    """
    return os.getenv("NAVER_CLIENT_ID", "")


def _resolve_naver_client_secret() -> str:
    """Resolve NAVER Search API client secret from ``NAVER_CLIENT_SECRET``.

    Returns empty string when unset (news search 기능 비활성화).
    """
    return os.getenv("NAVER_CLIENT_SECRET", "")


def _resolve_naver_search_api_url() -> str:
    """Resolve NAVER Search API base URL from ``NAVER_SEARCH_API_URL``.

    Default: ``https://openapi.naver.com/v1/search/news.json``.
    """
    return os.getenv(
        "NAVER_SEARCH_API_URL",
        "https://openapi.naver.com/v1/search/news.json",
    )


# ---------------------------------------------------------------------------
# KIS snapshot sync settings
# ---------------------------------------------------------------------------


def _resolve_kis_snapshot_stale_threshold_seconds() -> int:
    """Resolve stale threshold for KIS snapshot sync freshness check.

    ``SNAPSHOT_STALE_THRESHOLD_SECONDS`` (preferred) or
    ``KIS_SNAPSHOT_STALE_THRESHOLD_SECONDS`` (fallback) env var,
    default ``900`` (15 min).  Clamped to ``max(1, value)``.
    """
    raw = (
        os.getenv("SNAPSHOT_STALE_THRESHOLD_SECONDS")
        or os.getenv("KIS_SNAPSHOT_STALE_THRESHOLD_SECONDS", "900")
    )
    return max(1, int(raw))


def _resolve_kis_snapshot_startup_grace_seconds() -> int:
    """Resolve startup grace period for snapshot sync readiness check.

    ``SNAPSHOT_STARTUP_GRACE_SECONDS`` (preferred) or
    ``KIS_SNAPSHOT_STARTUP_GRACE_SECONDS`` (fallback) env var,
    default ``600`` (10 min).
    During this window after process boot, ``/health/readyz`` skips the
    snapshot-sync-stale check and returns ``"ok"`` instead of ``"degraded"``.
    Clamped to ``max(0, value)``.
    """
    raw = (
        os.getenv("SNAPSHOT_STARTUP_GRACE_SECONDS")
        or os.getenv("KIS_SNAPSHOT_STARTUP_GRACE_SECONDS", "600")
    )
    return max(0, int(raw))


# ---------------------------------------------------------------------------
# Application settings
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class AppSettings:
    # ── Mode Switch ─────────────────────────────────────────────────────
    # Paper↔Live 전환 시 아래 항목만 변경하면 됩니다:
    #   1. environment → LIVE (또는 PAPER)
    #   2. KIS API key/secret → live 환경 값
    #   3. KIS_ACCOUNT_NUMBER → live 계좌
    #   4. KIS_ACCOUNT_PRODUCT_CODE → live 상품코드
    #   5. KIS_ENV → live
    #   6. KIS_BASE_URL, KIS_WS_URL → live endpoint
    #   7. KIS_REAL_REST_RPS → 적절한 live rate limit (기본값 15)
    # 나머지 설정 (cache, staleness threshold, grace period,
    # paper gate thresholds, LLM provider 등)은 변경 불필요.
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
    kis_base_url: str = field(default_factory=_resolve_kis_base_url)
    kis_ws_url: str = field(default_factory=_resolve_kis_ws_url)

    # ---- KIS REST rate limit safety budget (env override) --------------------
    # ``KIS_REAL_REST_RPS`` (default 15) and ``KIS_PAPER_REST_RPS`` (default 1)
    # control the per-environment token-bucket refill rates in
    # ``RateLimitBudgetManager``.  These are **safety budget scaling baselines**,
    # not exact RPS guarantees — the 5-bucket distribution spreads the total
    # conservatively across AUTH / ORDER / INQUIRY / MARKET_DATA / RECONCILIATION.
    kis_real_rest_rps: int = field(default_factory=_resolve_kis_real_rest_rps)
    kis_paper_rest_rps: int = field(default_factory=_resolve_kis_paper_rest_rps)

    # ---- KIS dev token cache (paper/dev only; disabled in live) ---------------
    kis_dev_token_cache_enabled: bool = field(default_factory=_resolve_kis_dev_token_cache_enabled)
    kis_dev_token_cache_path: str = field(default_factory=_resolve_kis_dev_token_cache_path)
    kis_shared_budget_file: str = field(default_factory=_resolve_kis_shared_budget_file)

    # ---- KIS live-info token cache (WebSocket approval key persistence) ------
    kis_live_token_cache_enabled: bool = field(default_factory=_resolve_kis_live_token_cache_enabled)
    kis_live_token_cache_path: str = field(default_factory=_resolve_kis_live_token_cache_path)

    # ---- KIS trading REST approval-key file cache ----------------------------
    kis_approval_key_cache_enabled: bool = field(default_factory=_resolve_kis_approval_key_cache_enabled)
    kis_approval_key_cache_path: str = field(default_factory=_resolve_kis_approval_key_cache_path)

    # ---- KIS live-info WebSocket URL (163 market state) -----------------------
    kis_live_info_base_url: str = field(default_factory=lambda: os.getenv("KIS_LIVE_INFO_BASE_URL", ""))
    kis_live_info_ws_url: str = field(default_factory=lambda: os.getenv("KIS_LIVE_INFO_WS_URL", ""))

    # ---- KIS disclosure (live 전용 공시 제목) 설정 ----------------------------
    kis_live_app_key: str | None = field(default_factory=_resolve_kis_live_app_key)
    """Live 환경 KIS API Key (공시 조회 전용). None이면 disclosure 기능 비활성화."""

    kis_live_app_secret: str | None = field(default_factory=_resolve_kis_live_app_secret)
    """Live 환경 KIS API Secret (공시 조회 전용). None이면 disclosure 기능 비활성화."""

    kis_disclosure_token_cache_path: str = field(default_factory=_resolve_kis_disclosure_token_cache_path)
    """Disclosure 전용 token cache 파일 경로. 기본 KIS cache와 충돌 방지."""

    kis_disclosure_token_cache_enabled: bool = field(default_factory=_resolve_kis_disclosure_token_cache_enabled)
    """Disclosure token cache 사용 여부. False면 매번 재인증."""

    # ---- KIS snapshot sync stale threshold -----------------------------------
    kis_snapshot_stale_threshold_seconds: int = field(
        default_factory=_resolve_kis_snapshot_stale_threshold_seconds,
    )

    # ---- KIS snapshot sync startup grace period ------------------------------
    kis_snapshot_startup_grace_seconds: int = field(
        default_factory=_resolve_kis_snapshot_startup_grace_seconds,
    )

    # ---- Paper Go/No-Go Gate thresholds -------------------------------------
    paper_gate_min_return_pct: Decimal = field(
        default_factory=lambda: Decimal(os.getenv("PAPER_GATE_MIN_RETURN_PCT", "0.0")),
    )
    paper_gate_min_excess_return_pct: Decimal = field(
        default_factory=lambda: Decimal(os.getenv("PAPER_GATE_MIN_EXCESS_RETURN_PCT", "-5.0")),
    )
    paper_gate_max_drawdown_pct: Decimal = field(
        default_factory=lambda: Decimal(os.getenv("PAPER_GATE_MAX_DRAWDOWN_PCT", "20.0")),
    )
    paper_gate_min_win_rate_pct: Decimal = field(
        default_factory=lambda: Decimal(os.getenv("PAPER_GATE_MIN_WIN_RATE_PCT", "0.0")),
    )
    paper_gate_min_filled_orders: int = field(
        default_factory=lambda: max(1, int(os.getenv("PAPER_GATE_MIN_FILLED_ORDERS", "3"))),
    )
    paper_gate_max_consecutive_failures: int = field(
        default_factory=lambda: max(0, int(os.getenv("PAPER_GATE_MAX_CONSECUTIVE_FAILURES", "3"))),
    )

    # ---- Risk-Adjusted Gate thresholds (Paper, WARN-only) --------------------
    # 음수 Sharpe/Sortino/Calmar만 WARN (기본값 0.0).
    paper_gate_min_sharpe_ratio: Decimal = field(
        default_factory=lambda: Decimal(os.getenv("PAPER_GATE_MIN_SHARPE_RATIO", "0.0")),
    )
    paper_gate_min_sortino_ratio: Decimal = field(
        default_factory=lambda: Decimal(os.getenv("PAPER_GATE_MIN_SORTINO_RATIO", "0.0")),
    )
    paper_gate_min_calmar_ratio: Decimal = field(
        default_factory=lambda: Decimal(os.getenv("PAPER_GATE_MIN_CALMAR_RATIO", "0.0")),
    )

    # ---- Live Gate thresholds (paper보다 엄격) --------------------------------
    # Paper Exit 통과 후 Live 검토 자격을 판정하기 위한 추가 임계값.
    # Paper Gate threshold보다 더 엄격한 기준을 적용한다.
    live_gate_min_filled_orders: int = field(
        default_factory=lambda: max(1, int(os.getenv("LIVE_GATE_MIN_FILLED_ORDERS", "10"))),
    )
    live_gate_max_drawdown_pct: Decimal = field(
        default_factory=lambda: Decimal(os.getenv("LIVE_GATE_MAX_DRAWDOWN_PCT", "10.0")),
    )
    live_gate_min_excess_return_pct: Decimal = field(
        default_factory=lambda: Decimal(os.getenv("LIVE_GATE_MIN_EXCESS_RETURN_PCT", "0.0")),
    )
    live_gate_max_recent_reconcile_required: int = field(
        default_factory=lambda: max(0, int(os.getenv("LIVE_GATE_MAX_RECENT_RECONCILE_REQUIRED", "2"))),
    )
    live_gate_max_recent_blocking_locks: int = field(
        default_factory=lambda: max(0, int(os.getenv("LIVE_GATE_MAX_RECENT_BLOCKING_LOCKS", "1"))),
    )

    # ---- OpenDART API credentials (read from environment) --------------------
    opendart_api_key: str = field(default_factory=lambda: os.getenv("OPENDART_API_KEY", ""))

    # ---- NAVER Search API (news search) --------------------------------------
    # NEWS SEARCH 기능 활성화 조건:
    #   ``NAVER_CLIENT_ID`` + ``NAVER_CLIENT_SECRET`` 모두 설정되어야 함.
    # 둘 중 하나라도 비어 있으면 ``seeded_news_service``는 ``[]``를 반환한다.
    naver_client_id: str = field(default_factory=_resolve_naver_client_id)
    """NAVER Search API Client ID (``NAVER_CLIENT_ID`` env)."""

    naver_client_secret: str = field(default_factory=_resolve_naver_client_secret)
    """NAVER Search API Client Secret (``NAVER_CLIENT_SECRET`` env)."""

    naver_search_api_url: str = field(default_factory=_resolve_naver_search_api_url)
    """NAVER Search API endpoint URL (``NAVER_SEARCH_API_URL`` env).

    Default: ``https://openapi.naver.com/v1/search/news.json``.
    """

    # ---- Provider AI (OpenAI-compatible) ------------------------------------
    # External env var names are provider-specific; internal fields are
    # provider-agnostic.  ``LLM_PROVIDER`` controls which set of env vars
    # is read (``DEEPSEEK_*`` or ``OPENAI_*``).
    llm_provider: str = field(default_factory=_resolve_llm_provider)
    provider_api_key: str = field(default_factory=_resolve_provider_api_key)
    provider_base_url: str = field(default_factory=_resolve_provider_base_url)
    provider_model_id: str = field(default_factory=_resolve_provider_model_id)
    provider_timeout_seconds: int = field(default_factory=_resolve_provider_timeout)

    # ---- Execution Attempt Primary Truth ------------------------------------
    execution_attempt_primary_truth: bool = True
    """When ``True``, :class:`ExecutionAttemptEntity` is the authoritative
    source for execution status.  The ``trade_decisions`` bridge write is
    conditional with try/except warning-only on failure (P1).
    """
