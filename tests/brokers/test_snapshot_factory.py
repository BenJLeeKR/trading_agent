"""Tests for ``snapshot_factory`` — broker-aware component assembly.

Verifies:
- ``build_snapshot_sync_components("koreainvestment", ...)`` returns
  ``SnapshotSyncComponents`` with the correct provider and client types.
- ``build_snapshot_sync_components("unsupported", ...)`` raises ``ValueError``.
- Returned provider conforms to ``SnapshotFetchProvider`` protocol.
"""

from __future__ import annotations

import pytest

from agent_trading.brokers.snapshot_factory import (
    SnapshotSyncComponents,
    build_snapshot_sync_components,
)
from agent_trading.config.settings import AppSettings
from agent_trading.services.snapshot_sync import SnapshotFetchProvider


class TestBuildKISComponents:
    """``build_snapshot_sync_components("koreainvestment", ...)``."""

    def test_returns_snapshot_sync_components(self) -> None:
        settings = AppSettings()
        components = build_snapshot_sync_components("koreainvestment", settings)
        assert isinstance(components, SnapshotSyncComponents)
        assert components.broker_name == "koreainvestment"

    def test_provider_is_snapshot_fetch_provider(self) -> None:
        """Structural subtyping: provider conforms to the protocol."""
        settings = AppSettings()
        components = build_snapshot_sync_components("koreainvestment", settings)
        # Verify structural subtyping
        provider: SnapshotFetchProvider = components.provider  # type: ignore[assignment]
        assert provider is not None

    def test_provider_is_kissyncsnapshot_provider(self) -> None:
        """Provider is a ``KISSyncSnapshotProvider`` instance."""
        settings = AppSettings()
        components = build_snapshot_sync_components("koreainvestment", settings)
        from agent_trading.brokers.koreainvestment.snapshot import (
            KISSyncSnapshotProvider,
        )
        assert isinstance(components.provider, KISSyncSnapshotProvider)

    def test_client_is_kis_rest_client(self) -> None:
        """Client is a ``KISRestClient`` instance."""
        settings = AppSettings()
        components = build_snapshot_sync_components("koreainvestment", settings)
        from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
        assert isinstance(components.client, KISRestClient)

    def test_client_is_authenticatable_snapshot_client(self) -> None:
        """Client structurally conforms to ``AuthenticatableSnapshotClient``."""
        settings = AppSettings()
        components = build_snapshot_sync_components("koreainvestment", settings)
        from agent_trading.brokers.snapshot_factory import (
            AuthenticatableSnapshotClient,
        )
        client: AuthenticatableSnapshotClient = components.client
        assert client is not None

    def test_client_has_authenticate_method(self) -> None:
        """Client has async ``authenticate()`` (needed by scheduler)."""
        settings = AppSettings()
        components = build_snapshot_sync_components("koreainvestment", settings)
        assert hasattr(components.client, "authenticate")
        assert callable(components.client.authenticate)

    def test_client_has_close_method(self) -> None:
        """Client has async ``close()`` (needed by scheduler)."""
        settings = AppSettings()
        components = build_snapshot_sync_components("koreainvestment", settings)
        assert hasattr(components.client, "close")
        assert callable(components.client.close)


class TestUnsupportedBroker:
    """``build_snapshot_sync_components`` with unsupported brokers."""

    def test_unsupported_raises_value_error(self) -> None:
        settings = AppSettings()
        with pytest.raises(ValueError, match="Unsupported broker"):
            build_snapshot_sync_components("unknown_broker", settings)

    def test_unsupported_includes_name_in_message(self) -> None:
        settings = AppSettings()
        with pytest.raises(ValueError) as exc_info:
            build_snapshot_sync_components("some_broker", settings)
        assert "some_broker" in str(exc_info.value)
