"""KISRestClient auth/approval strict 1 rps cap unit tests.

Tests the ``asyncio.Lock`` + monotonic cooldown enforcement added to
``KISRestClient.authenticate()`` and ``get_approval_key()`` per KIS notice
2026-04-20.

Key behaviours under test
-------------------------
1. Cache hit -> no HTTP call, no lock contention visible to caller.
2. Concurrent cache-miss callers -> single HTTP call (lock serialises).
3. Successive rapid calls -> minimum 1-second gap enforced via cooldown.
4. Auth and approval paths have **independent** locks and cooldowns.
5. Failure does **not** advance the cooldown timestamp.
"""

from __future__ import annotations

import asyncio
import time
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
    containing a fake token/approval key.
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
    mock_http_client: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> KISRestClient:
    """A ``KISRestClient`` with mocked HTTP transport.

    ``_get_client()`` is monkeypatched at the **class level** to return
    ``mock_http_client`` so that no real network calls are made.  Class-level
    patching is required because ``KISRestClient`` uses ``@dataclass(slots=True)``;
    instance-level ``setattr`` on slot attributes is forbidden.
    """
    c = KISRestClient(
        api_key="dummy-key",
        api_secret="dummy-secret",
        account_number="12345678",
        account_product_code="01",
        env="paper",
    )

    async def _mock_get_client(self) -> AsyncMock:
        return mock_http_client

    # Class-level patch — replaces the slot descriptor with a regular method.
    monkeypatch.setattr(KISRestClient, "_get_client", _mock_get_client)
    return c


# ---------------------------------------------------------------------------
# Cache-hit tests
# ---------------------------------------------------------------------------


class TestCacheHit:
    """When a valid token/approval key is already cached, no HTTP call is made."""

    async def test_authenticate_returns_cached_token(
        self, client: KISRestClient, mock_http_client: AsyncMock
    ) -> None:
        """Token is cached and still valid -> return immediately, no HTTP call."""
        future = time.time() + 3600  # 1 hour from now
        object.__setattr__(client, "_access_token", "cached-token")
        object.__setattr__(client, "_token_expires_at", future)

        mock_http_client.post.reset_mock()
        result = await client.authenticate()
        assert result == "cached-token"
        assert (
            mock_http_client.post.await_count == 0
        ), "HTTP client should not be accessed when cache is valid"

    async def test_get_approval_key_returns_cached_key(
        self, client: KISRestClient, mock_http_client: AsyncMock
    ) -> None:
        """Approval key is cached and still valid -> return immediately, no HTTP call."""
        future = time.time() + 3600
        object.__setattr__(client, "_approval_key", "cached-approval-key")
        object.__setattr__(client, "_approval_key_expires_at", future)

        mock_http_client.post.reset_mock()
        result = await client.get_approval_key()
        assert result == "cached-approval-key"
        assert (
            mock_http_client.post.await_count == 0
        ), "HTTP client should not be accessed when cache is valid"


# ---------------------------------------------------------------------------
# Single-flight (concurrency) tests
# ---------------------------------------------------------------------------


class TestSingleFlight:
    """Concurrent callers are serialised by ``asyncio.Lock`` -- only one HTTP call."""

    async def test_concurrent_authenticate_single_http_call(
        self, client: KISRestClient, mock_http_client: AsyncMock
    ) -> None:
        """3 concurrent ``authenticate()`` calls -> only 1 HTTP POST."""
        # Ensure cache is empty so all 3 callers hit the lock
        object.__setattr__(client, "_access_token", None)
        object.__setattr__(client, "_token_expires_at", 0.0)

        mock_http_client.post.reset_mock()

        async def _call() -> str:
            return await client.authenticate()

        results = await asyncio.gather(_call(), _call(), _call())

        assert all(
            r == "test-access-token-xxxxxxxxxxxxxxxxxxxxxx" for r in results
        ), "All callers should receive the same token"
        # Only 1 HTTP call should have been made
        assert mock_http_client.post.await_count == 1, (
            f"Expected 1 HTTP call, got {mock_http_client.post.await_count}"
        )

    async def test_concurrent_get_approval_key_single_http_call(
        self, client: KISRestClient, mock_http_client: AsyncMock
    ) -> None:
        """3 concurrent ``get_approval_key()`` calls -> only 1 HTTP POST."""
        object.__setattr__(client, "_approval_key", None)
        object.__setattr__(client, "_approval_key_expires_at", 0.0)

        mock_http_client.post.reset_mock()

        async def _call() -> str:
            return await client.get_approval_key()

        results = await asyncio.gather(_call(), _call(), _call())

        assert all(
            r == "test-approval-key-xxxxxxxx" for r in results
        ), "All callers should receive the same approval key"
        assert mock_http_client.post.await_count == 1, (
            f"Expected 1 HTTP call, got {mock_http_client.post.await_count}"
        )

    async def test_concurrent_auth_and_approval_independent(
        self, client: KISRestClient, mock_http_client: AsyncMock
    ) -> None:
        """Auth and approval locks are independent -- both can proceed concurrently."""
        # Clear both caches
        object.__setattr__(client, "_access_token", None)
        object.__setattr__(client, "_token_expires_at", 0.0)
        object.__setattr__(client, "_approval_key", None)
        object.__setattr__(client, "_approval_key_expires_at", 0.0)

        mock_http_client.post.reset_mock()

        async def _do_auth() -> str:
            return await client.authenticate()

        async def _do_approval() -> str:
            return await client.get_approval_key()

        auth_result, approval_result = await asyncio.gather(_do_auth(), _do_approval())

        assert auth_result == "test-access-token-xxxxxxxxxxxxxxxxxxxxxx"
        assert approval_result == "test-approval-key-xxxxxxxx"
        # 2 HTTP calls total (one for each endpoint)
        assert mock_http_client.post.await_count == 2, (
            f"Expected 2 HTTP calls, got {mock_http_client.post.await_count}"
        )


# ---------------------------------------------------------------------------
# Cooldown (1 rps) tests
# ---------------------------------------------------------------------------


class TestCooldown:
    """Successive rapid HTTP calls are spaced at least 1 second apart."""

    async def test_authenticate_enforces_1s_cooldown(
        self, client: KISRestClient, mock_http_client: AsyncMock
    ) -> None:
        """Second call within 1 second sleeps before making HTTP request."""
        # Force first cache miss
        object.__setattr__(client, "_access_token", None)
        object.__setattr__(client, "_token_expires_at", 0.0)
        mock_http_client.post.reset_mock()

        # First call -- sets _last_auth_call_time
        result1 = await client.authenticate()
        assert result1 == "test-access-token-xxxxxxxxxxxxxxxxxxxxxx"

        # Force second cache miss
        object.__setattr__(client, "_token_expires_at", 0.0)

        # Spy on asyncio.sleep
        sleep_called = False
        sleep_duration = 0.0
        original_sleep = asyncio.sleep

        async def _sleep_spy(delay: float, *args: object, **kwargs: object) -> None:
            nonlocal sleep_called, sleep_duration
            sleep_called = True
            sleep_duration = delay
            await original_sleep(delay)

        object.__setattr__(client, "_access_token", None)
        mock_http_client.post.reset_mock()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(asyncio, "sleep", _sleep_spy)
            result2 = await client.authenticate()

        assert result2 == "test-access-token-xxxxxxxxxxxxxxxxxxxxxx"
        assert sleep_called, "asyncio.sleep should have been called for cooldown"
        assert 0.9 <= sleep_duration <= 1.1, (
            f"Expected ~1.0s cooldown, got {sleep_duration:.3f}s"
        )

    async def test_approval_key_independent_cooldown(
        self, client: KISRestClient, mock_http_client: AsyncMock
    ) -> None:
        """Auth cooldown does not affect approval key cooldown (independent)."""
        # Set auth cooldown to recent (would block auth but not approval)
        object.__setattr__(client, "_last_auth_call_time", time.monotonic())

        # Approval cache is empty -> should proceed without cooldown
        object.__setattr__(client, "_approval_key", None)
        object.__setattr__(client, "_approval_key_expires_at", 0.0)
        mock_http_client.post.reset_mock()

        result = await client.get_approval_key()
        assert result == "test-approval-key-xxxxxxxx"
        assert mock_http_client.post.await_count == 1, (
            "Approval key call should not be blocked by auth cooldown"
        )

    async def test_cooldown_skipped_on_first_call(
        self, client: KISRestClient, mock_http_client: AsyncMock
    ) -> None:
        """First call always proceeds immediately (_last_*_call_time == 0.0)."""
        assert client._last_auth_call_time == 0.0
        mock_http_client.post.reset_mock()
        result = await client.authenticate()
        assert result is not None
        assert mock_http_client.post.await_count == 1


# ---------------------------------------------------------------------------
# Failure does not update cooldown timestamp
# ---------------------------------------------------------------------------


class TestFailureDoesNotAdvanceCooldown:
    """If the HTTP call fails, ``_last_*_call_time`` is **not** updated,
    allowing immediate retry."""

    async def test_authenticate_failure_does_not_update_cooldown(
        self, client: KISRestClient, mock_http_client: AsyncMock
    ) -> None:
        """Failed authenticate() should not advance _last_auth_call_time."""
        object.__setattr__(client, "_access_token", None)
        object.__setattr__(client, "_token_expires_at", 0.0)

        # Make the mock raise an error (403 response with EGW00133)
        async def _mock_post_error(*args: object, **kwargs: object) -> httpx.Response:
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 403
            resp.json.return_value = {
                "rt_cd": "1",
                "msg_cd": "EGW00133",
                "msg1": "Rate limit exceeded",
            }
            resp.raise_for_status = MagicMock()
            return resp

        mock_http_client.post.side_effect = _mock_post_error

        with pytest.raises(Exception):
            await client.authenticate()

        # _last_auth_call_time should still be 0.0 (never updated on failure)
        assert client._last_auth_call_time == 0.0, (
            "Cooldown timestamp should not advance on failure"
        )
