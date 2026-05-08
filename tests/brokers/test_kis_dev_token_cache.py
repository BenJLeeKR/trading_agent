"""KISRestClient dev token cache (file-based) unit tests.

Tests the ``_load_dev_token_cache()`` and ``_save_dev_token_cache()``
methods integrated into ``KISRestClient.authenticate()``.

Key behaviours under test
-------------------------
1. Cache hit from file -> no HTTP call.
2. Cache expired -> HTTP call, new token saved to file.
3. App key fingerprint mismatch -> file ignored, HTTP call.
4. Environment mismatch -> file ignored, HTTP call.
5. Cache disabled -> file never read.
6. Corrupted file -> graceful fallback, HTTP call.
7. Successful auth -> token saved to file.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from agent_trading.brokers.koreainvestment.rest_client import (
    KISRestClient,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_http_client() -> AsyncMock:
    """Return an ``AsyncMock`` for ``httpx.AsyncClient``.

    The mock's ``post`` method returns a 200 response with a JSON body
    containing a fake token.
    """
    client = AsyncMock(spec=httpx.AsyncClient)

    async def _mock_post(*args: object, **kwargs: object) -> httpx.Response:
        body = {
            "access_token": "test-access-token-xxxxxxxxxxxxxxxxxxxxxx",
            "access_token_token": "test-access-token-xxxxxxxxxxxxxxxxxxxxxx",
            "approval_key": "test-approval-key-xxxxxxxx",
            "expires_in": "86400",
        }
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = body
        resp.raise_for_status = MagicMock()
        return resp

    client.post.side_effect = _mock_post
    return client


@pytest.fixture
def client(
    mock_http_client: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> KISRestClient:
    """A ``KISRestClient`` with mocked HTTP transport and dev token cache enabled.

    The cache file path is isolated to ``tmp_path`` so tests don't interfere
    with each other or the real filesystem.
    """
    cache_path = tmp_path / "kis_token.json"
    c = KISRestClient(
        api_key="dummy-key",
        api_secret="dummy-secret",
        account_number="12345678",
        account_product_code="01",
        env="paper",
        dev_token_cache_enabled=True,
        dev_token_cache_path=str(cache_path),
    )

    async def _mock_get_client(self) -> AsyncMock:
        return mock_http_client

    # Class-level patch — required because KISRestClient uses @dataclass(slots=True)
    monkeypatch.setattr(KISRestClient, "_get_client", _mock_get_client)
    return c


def _write_cache(
    path: Path,
    *,
    access_token: str = "cached-token-abc123",
    expires_at: float | None = None,
    kis_env: str = "paper",
    base_url: str = "https://openapivts.koreainvestment.com:29443",
    app_key_fingerprint: str | None = None,
) -> None:
    """Write a dev token cache file with the given parameters."""
    if expires_at is None:
        expires_at = time.time() + 3600  # 1 hour from now
    if app_key_fingerprint is None:
        app_key_fingerprint = _fingerprint("dummy-key")

    data: dict[str, object] = {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_at": expires_at,
        "kis_env": kis_env,
        "base_url": base_url,
        "app_key_fingerprint": app_key_fingerprint,
        "created_at": time.time(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _fingerprint(api_key: str) -> str:
    """Compute the expected SHA256 fingerprint for an api_key."""
    import hashlib

    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Cache-hit tests
# ---------------------------------------------------------------------------


class TestCacheHitFromFile:
    """When a valid token exists in the file cache, no HTTP call is made."""

    async def test_cache_hit_loads_from_file(
        self, client: KISRestClient, mock_http_client: AsyncMock
    ) -> None:
        """File cache valid -> _access_token set, no HTTP call."""
        cache_path = Path(client.dev_token_cache_path)
        _write_cache(cache_path)

        mock_http_client.post.reset_mock()
        result = await client.authenticate()

        assert result == "cached-token-abc123"
        assert client._access_token == "cached-token-abc123"
        assert mock_http_client.post.await_count == 0

    async def test_cache_hit_returns_cached_token(
        self, client: KISRestClient, mock_http_client: AsyncMock
    ) -> None:
        """File cache hit returns the cached token directly."""
        cache_path = Path(client.dev_token_cache_path)
        _write_cache(cache_path)

        mock_http_client.post.reset_mock()
        result = await client.authenticate()

        assert result == "cached-token-abc123"
        assert mock_http_client.post.await_count == 0


# ---------------------------------------------------------------------------
# Cache expiry tests
# ---------------------------------------------------------------------------


class TestCacheExpired:
    """When the file cache is expired, an HTTP call is made and the file is updated."""

    async def test_cache_expired_makes_http_call(
        self, client: KISRestClient, mock_http_client: AsyncMock
    ) -> None:
        """File cache expired -> HTTP call, new token returned."""
        cache_path = Path(client.dev_token_cache_path)
        _write_cache(cache_path, expires_at=time.time() - 10)  # expired 10s ago

        mock_http_client.post.reset_mock()
        result = await client.authenticate()

        assert result == "test-access-token-xxxxxxxxxxxxxxxxxxxxxx"
        assert mock_http_client.post.await_count == 1

    async def test_cache_expired_updates_file(
        self, client: KISRestClient, mock_http_client: AsyncMock
    ) -> None:
        """After HTTP call, the file cache is updated with the new token."""
        cache_path = Path(client.dev_token_cache_path)
        _write_cache(cache_path, expires_at=time.time() - 10)

        await client.authenticate()

        # Verify file was updated
        assert cache_path.exists()
        data = json.loads(cache_path.read_text())
        assert data["access_token"] == "test-access-token-xxxxxxxxxxxxxxxxxxxxxx"
        assert data["kis_env"] == "paper"
        assert data["app_key_fingerprint"] == _fingerprint("dummy-key")


# ---------------------------------------------------------------------------
# Cache mismatch tests
# ---------------------------------------------------------------------------


class TestCacheMismatch:
    """When the file cache has mismatched metadata, it is ignored."""

    async def test_cache_app_key_mismatch_ignored(
        self, client: KISRestClient, mock_http_client: AsyncMock
    ) -> None:
        """App key fingerprint mismatch -> file ignored, HTTP call made."""
        cache_path = Path(client.dev_token_cache_path)
        _write_cache(cache_path, app_key_fingerprint="different-fingerprint")

        mock_http_client.post.reset_mock()
        result = await client.authenticate()

        assert result == "test-access-token-xxxxxxxxxxxxxxxxxxxxxx"
        assert mock_http_client.post.await_count == 1

    async def test_cache_env_mismatch_ignored(
        self, client: KISRestClient, mock_http_client: AsyncMock
    ) -> None:
        """Environment mismatch -> file ignored, HTTP call made."""
        cache_path = Path(client.dev_token_cache_path)
        _write_cache(cache_path, kis_env="live")

        mock_http_client.post.reset_mock()
        result = await client.authenticate()

        assert result == "test-access-token-xxxxxxxxxxxxxxxxxxxxxx"
        assert mock_http_client.post.await_count == 1

    async def test_cache_base_url_mismatch_ignored(
        self, client: KISRestClient, mock_http_client: AsyncMock
    ) -> None:
        """Base URL mismatch -> file ignored, HTTP call made."""
        cache_path = Path(client.dev_token_cache_path)
        _write_cache(cache_path, base_url="https://openapi.koreainvestment.com:9443")

        mock_http_client.post.reset_mock()
        result = await client.authenticate()

        assert result == "test-access-token-xxxxxxxxxxxxxxxxxxxxxx"
        assert mock_http_client.post.await_count == 1


# ---------------------------------------------------------------------------
# Cache disabled tests
# ---------------------------------------------------------------------------


class TestCacheDisabled:
    """When dev token cache is disabled, the file is never read."""

    async def test_cache_disabled_does_not_read_file(
        self, mock_http_client: AsyncMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """dev_token_cache_enabled=False -> file not read, HTTP call made."""
        cache_path = tmp_path / "kis_token.json"
        _write_cache(cache_path)

        c = KISRestClient(
            api_key="dummy-key",
            api_secret="dummy-secret",
            account_number="12345678",
            account_product_code="01",
            env="paper",
            dev_token_cache_enabled=False,  # explicitly disabled
            dev_token_cache_path=str(cache_path),
        )

        async def _mock_get_client(self) -> AsyncMock:
            return mock_http_client

        monkeypatch.setattr(KISRestClient, "_get_client", _mock_get_client)

        mock_http_client.post.reset_mock()
        result = await c.authenticate()

        assert result == "test-access-token-xxxxxxxxxxxxxxxxxxxxxx"
        assert mock_http_client.post.await_count == 1


# ---------------------------------------------------------------------------
# Corrupted file tests
# ---------------------------------------------------------------------------


class TestCacheCorrupted:
    """When the file cache is corrupted, it falls back gracefully."""

    async def test_cache_corrupted_file_graceful(
        self, client: KISRestClient, mock_http_client: AsyncMock
    ) -> None:
        """Corrupted JSON file -> graceful fallback, HTTP call made."""
        cache_path = Path(client.dev_token_cache_path)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text("this is not valid json")

        mock_http_client.post.reset_mock()
        result = await client.authenticate()

        assert result == "test-access-token-xxxxxxxxxxxxxxxxxxxxxx"
        assert mock_http_client.post.await_count == 1

    async def test_cache_empty_file_graceful(
        self, client: KISRestClient, mock_http_client: AsyncMock
    ) -> None:
        """Empty file -> graceful fallback, HTTP call made."""
        cache_path = Path(client.dev_token_cache_path)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text("")

        mock_http_client.post.reset_mock()
        result = await client.authenticate()

        assert result == "test-access-token-xxxxxxxxxxxxxxxxxxxxxx"
        assert mock_http_client.post.await_count == 1


# ---------------------------------------------------------------------------
# Save-after-auth tests
# ---------------------------------------------------------------------------


class TestSaveAfterAuth:
    """After a successful HTTP auth call, the token is saved to file."""

    async def test_cache_saves_after_successful_auth(
        self, client: KISRestClient, mock_http_client: AsyncMock
    ) -> None:
        """HTTP call success -> file cache created with correct data."""
        cache_path = Path(client.dev_token_cache_path)
        assert not cache_path.exists()

        await client.authenticate()

        assert cache_path.exists()
        data = json.loads(cache_path.read_text())
        assert data["access_token"] == "test-access-token-xxxxxxxxxxxxxxxxxxxxxx"
        assert data["kis_env"] == "paper"
        assert data["base_url"] == "https://openapivts.koreainvestment.com:29443"
        assert data["app_key_fingerprint"] == _fingerprint("dummy-key")
        assert "expires_at" in data
        assert "created_at" in data

    async def test_cache_save_does_not_raise_on_permission_error(
        self, client: KISRestClient, mock_http_client: AsyncMock
    ) -> None:
        """Permission error on save -> silent fallback, no exception."""
        cache_path = Path(client.dev_token_cache_path)
        # Make the parent directory read-only
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.parent.chmod(0o444)

        try:
            # Should not raise
            result = await client.authenticate()
            assert result == "test-access-token-xxxxxxxxxxxxxxxxxxxxxx"
        finally:
            # Restore permissions for cleanup
            cache_path.parent.chmod(0o755)
