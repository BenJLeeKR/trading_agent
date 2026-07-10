from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

from agent_trading.brokers.koreainvestment.adapter import KoreaInvestmentAdapter
from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.brokers.koreainvestment.token_cache import CachePurpose
from agent_trading.brokers.rate_limit import RateLimitBudgetManager, build_kis_budget_manager
from agent_trading.brokers.polling_worker import PollingConfig, PollingWorker
from agent_trading.brokers.source_adapter import SourceAdapter
from agent_trading.config.settings import AppSettings
from agent_trading.db.connection import DatabaseConfig, close_pool, create_pool
from agent_trading.db.migrations.run import ensure_schema, run_all_migrations
from agent_trading.db.transaction import transaction
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.contracts import ExternalEventRepository
from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories
from agent_trading.services.ai_agents import (
    AIComplianceAgent,
    AIRiskAgent,
    EventInterpretationAgent,
    FinalDecisionComposerAgent,
    OpenAICompatibleClient,
)
from agent_trading.services.ai_agents.recorder import AgentRunRecorder
from agent_trading.services.decision_orchestrator import (
    DecisionOrchestratorService,
)
from agent_trading.services.seeded_news_service import (
    SeededNewsCandidateService,
)
from agent_trading.services.order_manager import OrderManager
from agent_trading.services.reconciliation_service import ReconciliationService

logger = logging.getLogger(__name__)


def _build_kis_live_quote_client(settings: AppSettings) -> KISRestClient | None:
    """Build a live read-only KIS client for quote/orderbook/market-data.

    Orders, positions, cash, and truth queries remain on the primary paper/live
    trading client.  This auxiliary client is only for market-data reads so
    paper trading can still use live quote fidelity.
    """
    if not settings.kis_live_app_key or not settings.kis_live_app_secret:
        logger.warning(
            "Live quote client disabled: "
            "kis_live_app_key or kis_live_app_secret not configured. "
            "Falling back to primary KIS client for quotes.",
        )
        return None

    budget_manager: RateLimitBudgetManager = build_kis_budget_manager(
        kis_env="live",
        real_rest_rps=settings.kis_real_rest_rps,
        paper_rest_rps=settings.kis_paper_rest_rps,
    )

    return KISRestClient(
        env="live",
        api_key=settings.kis_live_app_key,
        api_secret=settings.kis_live_app_secret,
        account_number="",
        account_product_code="",
        base_url=settings.kis_live_info_base_url,
        budget_manager=budget_manager,
        dev_token_cache_path=settings.kis_disclosure_token_cache_path,
        dev_token_cache_enabled=settings.kis_disclosure_token_cache_enabled,
        cache_purpose=CachePurpose.LIVE_DISCLOSURE_ACCESS_TOKEN,
        approval_cache_enabled=settings.kis_approval_key_cache_enabled,
        approval_cache_path=settings.kis_approval_key_cache_path,
    )


def build_realtime_quote_source(
    settings: AppSettings,
) -> "KisRealtimeQuoteSource | None":
    """Build an (unconnected) KIS-backed realtime-quote source, or ``None``.

    This is for the Admin UI "실시간 현재가" screen only
    (``plan_docs/detailed_design/11_kis_realtime_quote_operations_screen.md``).

    **2026-07-10 credential 통합**: 이 화면은 원래 ``KIS_REALTIME_QUOTE_*``라는
    전용 appkey를 썼지만, ``ops-scheduler``에서 163 WS 의존이 제거되면서
    ``KIS_LIVE_INFO_*``가 더 이상 별도 프로세스와 WS 세션을 공유할 필요가
    없어져(§4.2 WebSocket Session 1개 원칙 — 이제 이 화면이 ``KIS_LIVE_INFO_*``
    appkey의 유일한 WS 소비자다) 통합했다. **최종 authoritative credential은
    ``KIS_LIVE_INFO_APP_KEY``/``_APP_SECRET``/``_BASE_URL``/``_WS_URL``**이며
    (``_build_kis_live_quote_client()``가 쓰는 것과 동일한 disclosure/live-info
    계좌), 여전히 ``_build_kis_adapter()``(트레이딩 계좌)와는 완전히 분리되어
    있다. 짧은 하위 호환을 위해 ``KIS_LIVE_INFO_*``가 비어 있으면 legacy
    ``KIS_REALTIME_QUOTE_*``로 fallback한다(신규 배포에서는 설정할 필요 없음).

    - approval-key 파일 캐시는 여전히 이 화면 전용 경로
      (``KIS_LIVE_INFO_APPROVAL_CACHE_PATH``, legacy 경로로 fallback 가능)를
      쓴다 — 트레이딩/공시 계좌의 캐시 파일과 섞이지 않는다.
    - 자체 ``RateLimitBudgetManager`` 인스턴스를 새로 만든다(프로세스 내
      budget은 여전히 공유하지 않는다 — 다만 REST rate limit 자체는 계좌
      단위이므로, 같은 ``KIS_LIVE_INFO_*`` 계좌로 REST를 호출하는 다른 프로세스
      — 예: ``ops-scheduler``가 구동하는 ``run_decision_loop.py`` 서브프로세스의
      ``_build_kis_live_quote_client()`` — 와는 프로세스 경계를 넘어선 공유
      budget이 없다는 기존 한계가 그대로 유지된다. 이건 이번 통합이 새로
      만든 문제가 아니라 원래부터 있던 제약이다).
    - ``account_number``/``account_product_code``는 여전히 빈 문자열 —
      이 클라이언트는 read-only 시세 엔드포인트(``oauth2/Approval``,
      ``inquire-price``)만 호출하고, 주문/잔고 엔드포인트는 호출하지 않는다.

    Returns ``None`` when neither ``KIS_LIVE_INFO_*`` nor the legacy
    ``KIS_REALTIME_QUOTE_*`` fallback are configured — the caller
    (``api/app.py`` lifespan) falls back to ``InMemoryMockQuoteSource`` in
    that case. This function only constructs objects (no network I/O); the
    caller must ``await source.connect()`` inside an async context before use.
    """
    app_key = settings.kis_live_app_key
    app_secret = settings.kis_live_app_secret
    base_url = settings.kis_live_info_base_url
    ws_url = settings.kis_live_info_ws_url
    approval_cache_path = settings.kis_live_info_approval_cache_path

    if not app_key or not app_secret:
        # 짧은 하위 호환: KIS_LIVE_INFO_*가 비어 있고 legacy
        # KIS_REALTIME_QUOTE_*가 설정되어 있으면 그걸로 fallback한다.
        if settings.kis_realtime_quote_app_key and settings.kis_realtime_quote_app_secret:
            logger.warning(
                "Realtime-quote source: using deprecated KIS_REALTIME_QUOTE_* "
                "credentials — set KIS_LIVE_INFO_APP_KEY/_APP_SECRET instead "
                "(authoritative as of 2026-07-10)."
            )
            app_key = settings.kis_realtime_quote_app_key
            app_secret = settings.kis_realtime_quote_app_secret
            base_url = settings.kis_realtime_quote_base_url
            ws_url = settings.kis_realtime_quote_ws_url
            approval_cache_path = settings.kis_realtime_quote_approval_cache_path

    if not app_key or not app_secret:
        logger.info(
            "Realtime-quote source: mock (KIS_LIVE_INFO_APP_KEY/_APP_SECRET not configured)."
        )
        return None

    from agent_trading.services.kis_realtime_quote_source import KisRealtimeQuoteSource

    # Independent budget manager — never shared with the trading account's
    # RateLimitBudgetManager instance.
    budget_manager = build_kis_budget_manager(
        kis_env="live",
        real_rest_rps=settings.kis_real_rest_rps,
        paper_rest_rps=settings.kis_paper_rest_rps,
    )

    rest_client = KISRestClient(
        env="live",
        api_key=app_key,
        api_secret=app_secret,
        account_number="",
        account_product_code="",
        base_url=base_url,
        budget_manager=budget_manager,
        dev_token_cache_enabled=False,  # this client never calls authenticate()
        approval_cache_enabled=True,
        approval_cache_path=approval_cache_path,
    )

    try:
        return KisRealtimeQuoteSource(
            rest_client=rest_client,
            ws_url=ws_url,
        )
    except Exception:
        logger.exception(
            "Failed to construct KisRealtimeQuoteSource — realtime-quote "
            "screen will fall back to mock."
        )
        return None


def _build_kis_adapter(settings: AppSettings) -> KoreaInvestmentAdapter:
    """Build a KoreaInvestmentAdapter with a configured KISRestClient.

    The ``RateLimitBudgetManager`` is created via ``build_kis_budget_manager()``
    using the environment-specific REST RPS settings, providing a safety budget
    baseline for all KIS REST API calls.
    """
    budget_manager = build_kis_budget_manager(
        kis_env=settings.kis_env,
        real_rest_rps=settings.kis_real_rest_rps,
        paper_rest_rps=settings.kis_paper_rest_rps,
        shared_budget_file=settings.kis_shared_budget_file,
    )
    rest_client = KISRestClient(
        api_key=settings.kis_api_key,
        api_secret=settings.kis_api_secret,
        account_number=settings.kis_account_number,
        account_product_code=settings.kis_account_product_code,
        env=settings.kis_env,
        base_url=settings.kis_base_url,
        budget_manager=budget_manager,
        dev_token_cache_enabled=settings.kis_dev_token_cache_enabled,
        dev_token_cache_path=settings.kis_dev_token_cache_path,
        approval_cache_enabled=settings.kis_approval_key_cache_enabled,
        approval_cache_path=settings.kis_approval_key_cache_path,
    )
    live_quote_client = _build_kis_live_quote_client(settings)
    return KoreaInvestmentAdapter(
        rest_client=rest_client,
        quote_rest_client=live_quote_client,
        ws_url=settings.kis_ws_url,
    )


def build_api_broker_adapter(
    settings: AppSettings,
) -> KoreaInvestmentAdapter | None:
    """Build a broker adapter for the inspection API server.

    This is a graceful wrapper around ``_build_kis_adapter`` intended for use
    by ``create_app_from_env()``.  If KIS credentials are missing or the
    adapter cannot be constructed, the function logs a warning and returns
    ``None`` — the API server will still start, but ``/broker-capacity`` will
    return 503 ("Broker adapter not configured").

    Returns
    -------
    KoreaInvestmentAdapter | None
        The adapter instance, or ``None`` if the build fails.
    """
    # Check whether KIS credentials are present before attempting to build.
    if not settings.kis_api_key or not settings.kis_api_secret:
        logger.warning(
            "KIS_API_KEY / KIS_APP_KEY and KIS_API_SECRET / KIS_APP_SECRET are "
            "both empty — broker adapter will not be available. "
            "GET /broker-capacity will return 503."
        )
        return None

    try:
        return _build_kis_adapter(settings)
    except Exception:
        logger.exception(
            "Failed to build broker adapter for API server. "
            "GET /broker-capacity will return 503."
        )
        return None


def _build_polling_workers(
    repos: RepositoryContainer,
    settings: AppSettings,
) -> list[PollingWorker]:
    """Build configured polling workers for external event sources.

    v1: OpenDART only (T1_REGULATORY).
    Additional sources (KRX KIND, news feeds) are added in later milestones.

    OpenDART polling worker includes an ``OpenDartSymbolResolver`` for
    corp_code → stock_code fallback when ``/list.json`` returns empty
    ``stock_code``.
    """
    workers: list[PollingWorker] = []
    external_event_repo: ExternalEventRepository | None = getattr(
        repos, "external_events", None
    )
    if external_event_repo is None:
        return workers
    
    
    def _build_live_disclosure_client(
        settings: AppSettings,
    ) -> KISRestClient | None:
        """Build a live-only KISRestClient for 공시(제목) seed collection.
    
        Uses a dedicated live API key/secret (``kis_live_app_key`` /
        ``kis_live_app_secret``) and a dedicated token cache path
        (``.cache/kis_disclosure_token.json``) to avoid conflict with
        the primary dev/paper client.
    
        Returns ``None`` when live credentials are not configured (graceful disable).
    
        Parameters
        ----------
        settings : AppSettings
            Application settings with disclosure-specific fields.
    
        Returns
        -------
        KISRestClient | None
            Configured client, or ``None`` if disclosure is disabled.
        """
        if not settings.kis_live_app_key or not settings.kis_live_app_secret:
            logger.warning(
                "Live disclosure client disabled: "
                "kis_live_app_key or kis_live_app_secret not configured. "
                "Set KIS_LIVE_INFO_APP_KEY / KIS_LIVE_INFO_APP_SECRET to enable.",
            )
            return None
    
        cache_path = settings.kis_disclosure_token_cache_path or ".cache/kis_disclosure_token.json"
    
        client = KISRestClient(
            env="live",
            api_key=settings.kis_live_app_key,
            api_secret=settings.kis_live_app_secret,
            # Disclosure API uses query params, not account info
            account_number="",
            account_product_code="",
            base_url="",  # KIS_API_BASE_URLS["live"] will be used
            dev_token_cache_path=cache_path,
            dev_token_cache_enabled=settings.kis_disclosure_token_cache_enabled,
            cache_purpose=CachePurpose.LIVE_DISCLOSURE_ACCESS_TOKEN,
            approval_cache_enabled=settings.kis_approval_key_cache_enabled,
            approval_cache_path=settings.kis_approval_key_cache_path,
        )
    
        logger.info(
            "Live disclosure client created: env=live, "
            "cache_path=%s, cache_enabled=%s",
            cache_path,
            settings.kis_disclosure_token_cache_enabled,
        )
        return client

    # OpenDART polling worker (T1_REGULATORY)
    if settings.opendart_api_key:
        from agent_trading.brokers.opendart_adapter import OpenDartSourceAdapter
        from agent_trading.services.symbol_resolver import OpenDartSymbolResolver

        symbol_resolver = OpenDartSymbolResolver(
            api_key=settings.opendart_api_key,
        )
        adapter: SourceAdapter = OpenDartSourceAdapter(
            api_key=settings.opendart_api_key,
            symbol_resolver=symbol_resolver,
        )
        config = PollingConfig(
            source_name="opendart",
            interval_seconds=300,  # 5 minutes during market hours
            freshness_max_seconds=600,  # 10 minutes max lag
        )
        workers.append(PollingWorker(adapter, config, external_event_repo))

    return workers


def _build_live_disclosure_client(
    settings: AppSettings,
) -> KISRestClient | None:
    """Build a ``KISRestClient`` dedicated to the live-only disclosure API.

    Returns ``None`` (and logs a warning) when live credentials are missing.
    The returned client uses its own token cache path so it does not interfere
    with the primary live/paper client's token.
    """
    if not settings.kis_live_app_key or not settings.kis_live_app_secret:
        logger.warning(
            "Live disclosure client disabled: "
            "kis_live_app_key or kis_live_app_secret not configured. "
            "Set KIS_LIVE_INFO_APP_KEY / KIS_LIVE_INFO_APP_SECRET to enable.",
        )
        return None

    cache_path = settings.kis_disclosure_token_cache_path or ".cache/kis_disclosure_token.json"

    client = KISRestClient(
        env="live",
        api_key=settings.kis_live_app_key,
        api_secret=settings.kis_live_app_secret,
        account_number="",
        account_product_code="",
        base_url="",
        dev_token_cache_path=cache_path,
        dev_token_cache_enabled=settings.kis_disclosure_token_cache_enabled,
        cache_purpose=CachePurpose.LIVE_DISCLOSURE_ACCESS_TOKEN,
        approval_cache_enabled=settings.kis_approval_key_cache_enabled,
        approval_cache_path=settings.kis_approval_key_cache_path,
    )

    logger.info(
        "Live disclosure client created: env=live, "
        "cache_path=%s, cache_enabled=%s",
        cache_path,
        settings.kis_disclosure_token_cache_enabled,
    )
    return client


def _build_provider_agent(settings: AppSettings) -> EventInterpretationAgent | None:
    """Build a real ``EventInterpretationAgent`` if provider settings are complete."""
    if not settings.provider_api_key:
        logger.info(
            "Provider API key not configured — "
            "using stub EventInterpretationAgent"
        )
        return None
    if not settings.provider_base_url:
        logger.warning(
            "provider_base_url is empty — "
            "using stub EventInterpretationAgent"
        )
        return None
    if not settings.provider_model_id:
        logger.warning(
            "provider_model_id is empty — "
            "using stub EventInterpretationAgent"
        )
        return None

    client = OpenAICompatibleClient(
        api_key=settings.provider_api_key,
        base_url=settings.provider_base_url,
        timeout_seconds=settings.provider_timeout_seconds,
    )
    return EventInterpretationAgent(
        provider_client=client,
        model_id=settings.provider_model_id,
    )


def _build_ai_risk_agent(settings: AppSettings) -> AIRiskAgent | None:
    """Build a real ``AIRiskAgent`` if provider settings are complete.

    Returns ``None`` when settings are incomplete — caller falls back to
    ``StubAIRiskAgent``.
    """
    if not settings.provider_api_key:
        logger.info(
            "Provider API key not configured — "
            "using stub AIRiskAgent"
        )
        return None
    if not settings.provider_base_url:
        logger.warning(
            "provider_base_url is empty — "
            "using stub AIRiskAgent"
        )
        return None
    if not settings.provider_model_id:
        logger.warning(
            "provider_model_id is empty — "
            "using stub AIRiskAgent"
        )
        return None

    client = OpenAICompatibleClient(
        api_key=settings.provider_api_key,
        base_url=settings.provider_base_url,
        timeout_seconds=settings.provider_timeout_seconds,
    )
    return AIRiskAgent(
        provider_client=client,
        model_id=settings.provider_model_id,
    )


def _build_ai_compliance_agent(settings: AppSettings) -> AIComplianceAgent | None:
    """Build a real ``AIComplianceAgent`` if provider settings are complete."""
    if not settings.provider_api_key:
        logger.info(
            "Provider API key not configured — "
            "using stub AIComplianceAgent"
        )
        return None
    if not settings.provider_base_url:
        logger.warning(
            "provider_base_url is empty — "
            "using stub AIComplianceAgent"
        )
        return None
    if not settings.provider_model_id:
        logger.warning(
            "provider_model_id is empty — "
            "using stub AIComplianceAgent"
        )
        return None

    client = OpenAICompatibleClient(
        api_key=settings.provider_api_key,
        base_url=settings.provider_base_url,
        timeout_seconds=settings.provider_timeout_seconds,
    )
    return AIComplianceAgent(
        provider_client=client,
        model_id=settings.provider_model_id,
    )


def _build_final_decision_agent(
    settings: AppSettings,
) -> FinalDecisionComposerAgent | None:
    """Build a real ``FinalDecisionComposerAgent`` if provider settings are complete.

    Returns ``None`` when settings are incomplete — caller falls back to
    ``StubFinalDecisionComposerAgent``.
    """
    if not settings.provider_api_key:
        logger.info(
            "Provider API key not configured — "
            "using stub FinalDecisionComposerAgent"
        )
        return None
    if not settings.provider_base_url:
        logger.warning(
            "provider_base_url is empty — "
            "using stub FinalDecisionComposerAgent"
        )
        return None
    if not settings.provider_model_id:
        logger.warning(
            "provider_model_id is empty — "
            "using stub FinalDecisionComposerAgent"
        )
        return None

    client = OpenAICompatibleClient(
        api_key=settings.provider_api_key,
        base_url=settings.provider_base_url,
        timeout_seconds=settings.provider_timeout_seconds,
    )
    return FinalDecisionComposerAgent(
        provider_client=client,
        model_id=settings.provider_model_id,
    )


def _build_naver_search_adapter(
    settings: AppSettings,
) -> NaverNewsSearchAdapter | None:
    """Build NAVER News Search Adapter if credentials are configured.

    Returns ``None`` (and logs a warning) when NAVER credentials are missing.
    The caller (``_build_seeded_news_service``) handles ``None`` gracefully.
    """
    if not settings.naver_client_id or not settings.naver_client_secret:
        logger.warning(
            "NAVER search adapter disabled: "
            "NAVER_CLIENT_ID or NAVER_CLIENT_SECRET not configured. "
            "Set NAVER_CLIENT_ID / NAVER_CLIENT_SECRET to enable.",
        )
        return None

    from agent_trading.brokers.naver_news_adapter import NaverNewsSearchAdapter

    return NaverNewsSearchAdapter(
        client_id=settings.naver_client_id,
        client_secret=settings.naver_client_secret,
        api_url=settings.naver_search_api_url,
    )


def _build_seeded_news_service(
    settings: AppSettings,
) -> SeededNewsCandidateService | None:
    """Build SeededNewsCandidateService if NAVER credentials are configured.

    Returns ``None`` when NAVER is disabled — caller must handle gracefully.
    """
    naver_adapter = _build_naver_search_adapter(settings)
    if naver_adapter is None:
        return None

    return SeededNewsCandidateService(
        search_adapter=naver_adapter,
    )


async def _close_provider_agent(agent: object | None) -> None:
    """Safely close the provider agent's underlying HTTP client.

    Uses ``hasattr`` + ``callable`` checks to avoid direct private
    attribute access assumptions.
    """
    if agent is None:
        return
    provider = getattr(agent, "_provider", None)
    if provider is not None and callable(getattr(provider, "close", None)):
        await provider.close()


def _build_orchestrator(
    repos: RepositoryContainer,
    settings: AppSettings,
    event_interpretation_agent: EventInterpretationAgent | None = None,
    ai_risk_agent: AIRiskAgent | None = None,
    ai_compliance_agent: AIComplianceAgent | None = None,
    final_decision_agent: FinalDecisionComposerAgent | None = None,
) -> DecisionOrchestratorService:
    """Build a ``DecisionOrchestratorService`` with provider agent injection.

    When provider settings are complete, the real agents are injected.
    Otherwise the orchestrator falls back to stub agents.

    Parameters
    ----------
    repos:
        Repository container for the orchestrator's data access.
    settings:
        Application settings (used to build provider agents when not
        explicitly provided).
    event_interpretation_agent:
        Pre-built EI agent.  When ``None``, built via ``_build_provider_agent(settings)``.
    ai_risk_agent:
        Pre-built AR agent.  When ``None``, built via ``_build_ai_risk_agent(settings)``.
    final_decision_agent:
        Pre-built FDC agent.  When ``None``, built via ``_build_final_decision_agent(settings)``.
    """
    if event_interpretation_agent is None:
        event_interpretation_agent = _build_provider_agent(settings)
    if ai_risk_agent is None:
        ai_risk_agent = _build_ai_risk_agent(settings)
    if ai_compliance_agent is None:
        ai_compliance_agent = _build_ai_compliance_agent(settings)
    if final_decision_agent is None:
        final_decision_agent = _build_final_decision_agent(settings)
    return DecisionOrchestratorService(
        repos=repos,
        event_interpretation_agent=event_interpretation_agent,
        ai_risk_agent=ai_risk_agent,
        ai_compliance_agent=ai_compliance_agent,
        final_decision_agent=final_decision_agent,
        agent_recorder=AgentRunRecorder(repo=repos.agent_runs),
        # Provider configuration for subprocess agent creation
        llm_provider=settings.llm_provider,
        provider_api_key=settings.provider_api_key or "",
        provider_base_url=settings.provider_base_url or "",
        provider_model_id=settings.provider_model_id or "",
        provider_timeout_seconds=settings.provider_timeout_seconds or 120,
    )


def _build_order_manager(repos: RepositoryContainer) -> OrderManager:
    """Build an ``OrderManager`` wired with a ``ReconciliationService``.

    The reconciliation service is always built so that ``submit_order_to_broker()``
    can acquire blocking locks on uncertain results.
    """
    reconciliation_service = ReconciliationService(repos=repos)
    return OrderManager(
        repos=repos,
        reconciliation_service=reconciliation_service,
    )


def build_default_runtime() -> dict[str, object]:
    """Compose the initial runtime dependencies for local development.

    Uses in-memory repositories — no database required.
    """
    settings = AppSettings()
    broker_adapter = _build_kis_adapter(settings)
    repositories = build_in_memory_repositories()
    polling_workers = _build_polling_workers(repositories, settings)
    event_interpretation_agent = _build_provider_agent(settings)
    ai_risk_agent = _build_ai_risk_agent(settings)
    ai_compliance_agent = _build_ai_compliance_agent(settings)
    final_decision_agent = _build_final_decision_agent(settings)
    orchestrator = _build_orchestrator(
        repositories, settings,
        event_interpretation_agent=event_interpretation_agent,
        ai_risk_agent=ai_risk_agent,
        ai_compliance_agent=ai_compliance_agent,
        final_decision_agent=final_decision_agent,
    )
    order_manager = _build_order_manager(repositories)

    # Build live disclosure seed service
    from agent_trading.services.disclosure_seed_service import LiveDisclosureSeedService

    disclosure_client = _build_live_disclosure_client(settings)
    disclosure_seed_service = LiveDisclosureSeedService(client=disclosure_client)

    # Build seeded news service (NAVER news candidate MVP)
    seeded_news_service = _build_seeded_news_service(settings)

    return {
        "settings": settings,
        "primary_broker_adapter": broker_adapter,
        "repositories": repositories,
        "polling_workers": polling_workers,
        "orchestrator": orchestrator,
        "order_manager": order_manager,
        "event_interpretation_agent": event_interpretation_agent,
        "ai_risk_agent": ai_risk_agent,
        "ai_compliance_agent": ai_compliance_agent,
        "final_decision_agent": final_decision_agent,
        "disclosure_seed_service": disclosure_seed_service,
        "disclosure_client": disclosure_client,
        "seeded_news_service": seeded_news_service,
    }


async def build_postgres_runtime(
    db_config: DatabaseConfig | None = None,
    *,
    run_migrations: bool = True,
) -> dict[str, Any]:
    """Compose runtime dependencies backed by PostgreSQL.

    This factory:
      1. Creates the asyncpg connection pool.
      2. Optionally runs pending schema migrations.
      3. Opens a transaction and assembles a PostgreSQL-backed
         ``RepositoryContainer``.
      4. Returns the runtime dictionary.

    The caller **must** call ``shutdown_postgres_runtime()`` when done
    to close the connection pool.

    Parameters
    ----------
    db_config : DatabaseConfig or None
        Database connection parameters.  Falls back to environment
        variables / defaults when ``None``.
    run_migrations : bool
        Whether to apply pending DDL migrations before returning
        (default ``True``).

    Returns
    -------
    dict[str, Any]
        Runtime dictionary with keys ``settings``, ``primary_broker_adapter``,
        ``repositories``, and ``db_config``.
    """
    config = db_config or DatabaseConfig()
    await create_pool(config)

    if run_migrations:
        await ensure_schema(config)

    # NOTE: build_postgres_runtime no longer opens a transaction itself.
    # The caller is responsible for providing a transaction via
    # ``async with transaction() as tx:`` and passing it to
    # ``build_postgres_repositories(tx)``.
    # This avoids the problematic ``transaction().__aenter__()`` pattern
    # which prevented proper connection release to the pool.
    repositories = build_postgres_repositories(None)

    settings = AppSettings()
    broker_adapter = _build_kis_adapter(settings)
    polling_workers = _build_polling_workers(repositories, settings)
    event_interpretation_agent = _build_provider_agent(settings)
    ai_risk_agent = _build_ai_risk_agent(settings)
    ai_compliance_agent = _build_ai_compliance_agent(settings)
    final_decision_agent = _build_final_decision_agent(settings)
    orchestrator = _build_orchestrator(
        repositories, settings,
        event_interpretation_agent=event_interpretation_agent,
        ai_risk_agent=ai_risk_agent,
        ai_compliance_agent=ai_compliance_agent,
        final_decision_agent=final_decision_agent,
    )
    order_manager = _build_order_manager(repositories)

    # Build live disclosure seed service
    from agent_trading.services.disclosure_seed_service import LiveDisclosureSeedService

    disclosure_client = _build_live_disclosure_client(settings)
    disclosure_seed_service = LiveDisclosureSeedService(client=disclosure_client)

    # Build seeded news service (NAVER news candidate MVP)
    seeded_news_service = _build_seeded_news_service(settings)

    return {
        "settings": settings,
        "primary_broker_adapter": broker_adapter,
        "repositories": repositories,
        "db_config": config,
        "polling_workers": polling_workers,
        "orchestrator": orchestrator,
        "order_manager": order_manager,
        "event_interpretation_agent": event_interpretation_agent,
        "ai_risk_agent": ai_risk_agent,
        "ai_compliance_agent": ai_compliance_agent,
        "final_decision_agent": final_decision_agent,
        "disclosure_seed_service": disclosure_seed_service,
        "disclosure_client": disclosure_client,
        "seeded_news_service": seeded_news_service,
    }


async def shutdown_postgres_runtime(runtime: dict[str, Any]) -> None:
    """Clean up a PostgreSQL runtime.

    Closes the underlying HTTP clients of all provider agents (if any),
    closes the disclosure client, then closes the connection pool.
    Any open database transaction must be closed by the caller before
    calling this function.
    """
    for key in ("event_interpretation_agent", "ai_risk_agent", "ai_compliance_agent", "final_decision_agent"):
        agent = runtime.get(key)
        await _close_provider_agent(agent)

    # Close disclosure client if present
    disclosure_client: KISRestClient | None = runtime.get("disclosure_client")
    if disclosure_client:
        await disclosure_client.close()

    # Close seeded news service if present
    seeded_news_service = runtime.get("seeded_news_service")
    if seeded_news_service is not None and hasattr(seeded_news_service, "close"):
        await seeded_news_service.close()

    await close_pool()


@asynccontextmanager
async def postgres_runtime(
    db_config: DatabaseConfig | None = None,
    *,
    run_migrations: bool = True,
    auto_rollback: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    """Async context manager that yields a PostgreSQL-backed runtime.

    Usage::

        async with postgres_runtime() as runtime:
            repos: RepositoryContainer = runtime["repositories"]
            # ... work with repos ...

    The connection pool and transaction are automatically cleaned up
    when the context exits.

    Parameters
    ----------
    db_config : DatabaseConfig | None
        Database connection configuration.  Defaults to ``DatabaseConfig()``.
    run_migrations : bool
        Whether to apply pending migrations on entry (default ``True``).
    auto_rollback : bool
        If ``True``, the transaction is always rolled back on exit
        regardless of whether an exception occurred.  This is useful
        for test fixtures where each test needs a clean state.
    """
    config = db_config or DatabaseConfig()
    await create_pool(config)

    if run_migrations:
        await run_all_migrations(config=config)

    settings = AppSettings()
    broker_adapter = _build_kis_adapter(settings)

    async with transaction(force_rollback=auto_rollback) as tx:
        repositories = build_postgres_repositories(tx)
        polling_workers = _build_polling_workers(repositories, settings)
        event_interpretation_agent = _build_provider_agent(settings)
        ai_risk_agent = _build_ai_risk_agent(settings)
        ai_compliance_agent = _build_ai_compliance_agent(settings)
        final_decision_agent = _build_final_decision_agent(settings)
        orchestrator = _build_orchestrator(
            repositories, settings,
            event_interpretation_agent=event_interpretation_agent,
            ai_risk_agent=ai_risk_agent,
            ai_compliance_agent=ai_compliance_agent,
            final_decision_agent=final_decision_agent,
        )
        order_manager = _build_order_manager(repositories)
        # Build live disclosure seed service
        from agent_trading.services.disclosure_seed_service import LiveDisclosureSeedService

        disclosure_client = _build_live_disclosure_client(settings)
        disclosure_seed_service = LiveDisclosureSeedService(client=disclosure_client)

        # Build seeded news service (NAVER news candidate MVP)
        seeded_news_service = _build_seeded_news_service(settings)

        runtime: dict[str, Any] = {
            "settings": settings,
            "primary_broker_adapter": broker_adapter,
            "repositories": repositories,
            "db_config": config,
            "polling_workers": polling_workers,
            "orchestrator": orchestrator,
            "order_manager": order_manager,
            "event_interpretation_agent": event_interpretation_agent,
            "ai_risk_agent": ai_risk_agent,
            "ai_compliance_agent": ai_compliance_agent,
            "final_decision_agent": final_decision_agent,
            "disclosure_seed_service": disclosure_seed_service,
            "disclosure_client": disclosure_client,
            "seeded_news_service": seeded_news_service,
        }
        yield runtime

    await shutdown_postgres_runtime(runtime)
