from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

from agent_trading.brokers.koreainvestment.adapter import KoreaInvestmentAdapter
from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.brokers.polling_worker import PollingConfig, PollingWorker
from agent_trading.brokers.source_adapter import SourceAdapter
from agent_trading.config.settings import AppSettings
from agent_trading.db.connection import DatabaseConfig, close_pool, create_pool
from agent_trading.db.migrations.run import ensure_schema
from agent_trading.db.transaction import transaction
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.contracts import ExternalEventRepository
from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories
from agent_trading.services.ai_agents import (
    AIRiskAgent,
    EventInterpretationAgent,
    FinalDecisionComposerAgent,
    OpenAICompatibleClient,
)
from agent_trading.services.decision_orchestrator import (
    DecisionOrchestratorService,
)

logger = logging.getLogger(__name__)


def _build_kis_adapter(settings: AppSettings) -> KoreaInvestmentAdapter:
    """Build a KoreaInvestmentAdapter with a configured KISRestClient."""
    rest_client = KISRestClient(
        api_key=settings.kis_api_key,
        api_secret=settings.kis_api_secret,
        account_number=settings.kis_account_number,
        account_product_code=settings.kis_account_product_code,
        env=settings.kis_env,
    )
    return KoreaInvestmentAdapter(rest_client=rest_client)


def _build_polling_workers(
    repos: RepositoryContainer,
    settings: AppSettings,
) -> list[PollingWorker]:
    """Build configured polling workers for external event sources.

    v1: OpenDART only (T1_REGULATORY).
    Additional sources (KRX KIND, news feeds) are added in later milestones.
    """
    workers: list[PollingWorker] = []
    external_event_repo: ExternalEventRepository | None = getattr(
        repos, "external_events", None
    )
    if external_event_repo is None:
        return workers

    # OpenDART polling worker (T1_REGULATORY)
    if settings.opendart_api_key:
        from agent_trading.brokers.opendart_adapter import OpenDartSourceAdapter

        adapter: SourceAdapter = OpenDartSourceAdapter(
            api_key=settings.opendart_api_key,
        )
        config = PollingConfig(
            source_name="opendart",
            interval_seconds=300,  # 5 minutes during market hours
            freshness_max_seconds=600,  # 10 minutes max lag
        )
        workers.append(PollingWorker(adapter, config, external_event_repo))

    return workers


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
    if final_decision_agent is None:
        final_decision_agent = _build_final_decision_agent(settings)
    return DecisionOrchestratorService(
        repos=repos,
        event_interpretation_agent=event_interpretation_agent,
        ai_risk_agent=ai_risk_agent,
        final_decision_agent=final_decision_agent,
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
    final_decision_agent = _build_final_decision_agent(settings)
    orchestrator = _build_orchestrator(
        repositories, settings,
        event_interpretation_agent=event_interpretation_agent,
        ai_risk_agent=ai_risk_agent,
        final_decision_agent=final_decision_agent,
    )
    return {
        "settings": settings,
        "primary_broker_adapter": broker_adapter,
        "repositories": repositories,
        "polling_workers": polling_workers,
        "orchestrator": orchestrator,
        "event_interpretation_agent": event_interpretation_agent,
        "ai_risk_agent": ai_risk_agent,
        "final_decision_agent": final_decision_agent,
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
    final_decision_agent = _build_final_decision_agent(settings)
    orchestrator = _build_orchestrator(
        repositories, settings,
        event_interpretation_agent=event_interpretation_agent,
        ai_risk_agent=ai_risk_agent,
        final_decision_agent=final_decision_agent,
    )

    return {
        "settings": settings,
        "primary_broker_adapter": broker_adapter,
        "repositories": repositories,
        "db_config": config,
        "polling_workers": polling_workers,
        "orchestrator": orchestrator,
        "event_interpretation_agent": event_interpretation_agent,
        "ai_risk_agent": ai_risk_agent,
        "final_decision_agent": final_decision_agent,
    }


async def shutdown_postgres_runtime(runtime: dict[str, Any]) -> None:
    """Clean up a PostgreSQL runtime.

    Closes the underlying HTTP clients of all provider agents (if any),
    then closes the connection pool.  Any open database transaction
    must be closed by the caller before calling this function.
    """
    for key in ("event_interpretation_agent", "ai_risk_agent", "final_decision_agent"):
        agent = runtime.get(key)
        await _close_provider_agent(agent)
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
        await ensure_schema(config)

    settings = AppSettings()
    broker_adapter = _build_kis_adapter(settings)

    async with transaction(force_rollback=auto_rollback) as tx:
        repositories = build_postgres_repositories(tx)
        polling_workers = _build_polling_workers(repositories, settings)
        event_interpretation_agent = _build_provider_agent(settings)
        ai_risk_agent = _build_ai_risk_agent(settings)
        final_decision_agent = _build_final_decision_agent(settings)
        orchestrator = _build_orchestrator(
            repositories, settings,
            event_interpretation_agent=event_interpretation_agent,
            ai_risk_agent=ai_risk_agent,
            final_decision_agent=final_decision_agent,
        )
        runtime: dict[str, Any] = {
            "settings": settings,
            "primary_broker_adapter": broker_adapter,
            "repositories": repositories,
            "db_config": config,
            "polling_workers": polling_workers,
            "orchestrator": orchestrator,
            "event_interpretation_agent": event_interpretation_agent,
            "ai_risk_agent": ai_risk_agent,
            "final_decision_agent": final_decision_agent,
        }
        yield runtime

    await shutdown_postgres_runtime(runtime)
