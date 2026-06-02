"""Broker-aware snapshot sync component factory.

Assembles broker-specific REST client and ``SnapshotFetchProvider``
from a broker name and application settings.  CLI and scheduler scripts
use this factory instead of directly importing broker-specific classes.

Usage::

    from agent_trading.brokers.snapshot_factory import (
        AuthenticatableSnapshotClient,
        SnapshotSyncComponents,
        build_snapshot_sync_components,
    )

    components = build_snapshot_sync_components("koreainvestment", settings)
    # components.provider  → KISSyncSnapshotProvider (SnapshotFetchProvider)
    # components.client    → KISRestClient (AuthenticatableSnapshotClient)
    # components.broker_name → "koreainvestment"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from agent_trading.config.settings import AppSettings
from agent_trading.services.snapshot_sync import SnapshotFetchProvider


class AuthenticatableSnapshotClient(Protocol):
    """Minimal client contract required by the snapshot sync scheduler.

    A broker-specific REST client must provide these two methods for
    the scheduler lifecycle: authentication before use and clean
    teardown after.
    """

    async def authenticate(self) -> object:
        """Obtain or refresh an access token / session.

        Returns the current valid token or session identifier.
        """
        ...

    async def close(self) -> None:
        """Explicitly close the underlying HTTP client."""
        ...


@dataclass(slots=True, frozen=True)
class SnapshotSyncComponents:
    """Broker-specific components assembled by the factory.

    Attributes
    ----------
    provider:
        A ``SnapshotFetchProvider``-compatible instance for fetching
        positions and cash balance.
    client:
        The underlying broker-specific REST client.  The scheduler
        calls ``.authenticate()`` and ``.close()`` on this object.
        Conforms to ``AuthenticatableSnapshotClient`` protocol.
    broker_name:
        Normalised broker name (e.g. ``"koreainvestment"``).
    """
    provider: SnapshotFetchProvider
    client: AuthenticatableSnapshotClient = field(repr=False)
    broker_name: str


def build_snapshot_sync_components(
    broker_name: str,
    settings: AppSettings,
) -> SnapshotSyncComponents:
    """Build broker-specific snapshot sync components.

    Parameters
    ----------
    broker_name:
        Broker identifier.  Currently only ``"koreainvestment"`` is
        supported.
    settings:
        Application settings used for broker credentials and configuration.

    Returns
    -------
    SnapshotSyncComponents
        Assembled provider, client, and broker name.

    Raises
    ------
    ValueError
        If the broker name is not supported.
    """
    if broker_name == "koreainvestment":
        return _build_kis_components(settings)

    raise ValueError(
        f"Unsupported broker: {broker_name!r}. "
        f"Only 'koreainvestment' is supported."
    )


# ── KIS implementation ─────────────────────────────────────────────────────


def _build_kis_components(settings: AppSettings) -> SnapshotSyncComponents:
    """Build KIS-specific snapshot sync components."""
    # Late imports to keep module-level import fast and avoid circular
    # dependencies at import time.
    from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
    from agent_trading.brokers.koreainvestment.snapshot import (
        KISSyncSnapshotProvider,
    )
    from agent_trading.brokers.rate_limit import build_kis_budget_manager

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
    )
    return SnapshotSyncComponents(
        provider=KISSyncSnapshotProvider(rest_client),
        client=rest_client,
        broker_name="koreainvestment",
    )
