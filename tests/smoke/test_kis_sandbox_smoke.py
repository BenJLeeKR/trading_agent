"""KIS Sandbox read-only smoke tests.

Requirements (6 conditions):
  1. Read-only only — no submit_order / cancel_order / amend_order calls.
  2. Paper credential only — KIS_ENV must be "paper"; live env → pytest.fail().
  3. Full credential set skip — KIS_API_KEY + KIS_API_SECRET + KIS_ACCOUNT_NUMBER.
  4. WS smoke pass condition — first message (ack or data) received, not just connect.
  5. Level 1: auth + quote/orderbook.
  6. Level 2: positions + cash balance + fills.
  7. Level 3: WebSocket receive (@pytest.mark.slow).

Usage:
    # Skip guard: credentials not set → all tests skipped automatically.
    # Live guard: KIS_ENV=live → pytest.fail() with explicit message.

    pytest tests/smoke/test_kis_sandbox_smoke.py -v -m smoke
    pytest tests/smoke/test_kis_sandbox_smoke.py -v -m slow   # includes WS

KIS capability notice (2026-04-20):
    - 실전 REST: 계좌당 초당 18건 (이전 15 → 18 상향)
    - 모의 REST: 계좌당 초당 1건
    - Auth/Approval key: 1 rps
    - WebSocket 등록: 계좌당 41건
    - 동시호출 권장 간격: 100~150ms
    - 상세: plan_docs/detailed_design/10_broker_rate_limit_and_capacity_policy.md §12
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, AsyncIterator

import pytest

from agent_trading.brokers.base import SubscriptionBudget
from agent_trading.brokers.errors import BrokerError
from agent_trading.brokers.koreainvestment.adapter import KoreaInvestmentAdapter
from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.brokers.koreainvestment.websocket_client import KISWebSocketClient

# =========================================================================
# Skip / fail guards
# =========================================================================

_REQUIRED_ENV_VARS: tuple[str, ...] = (
    "KIS_APP_KEY",
    "KIS_APP_SECRET",
    "KIS_ACCOUNT_NO",
)

# Legacy fallback names for the same credentials (checked in _credentials_configured)
_LEGACY_ENV_VARS: tuple[str, ...] = (
    "KIS_API_KEY",
    "KIS_API_SECRET",
    "KIS_ACCOUNT_NUMBER",
)

_WS_FIRST_MSG_TIMEOUT: float = 15.0  # seconds


def _credentials_configured() -> bool:
    """Return True when preferred or legacy env vars are fully set.

    Checks preferred names (``KIS_APP_KEY``, …) first; falls back to
    legacy names (``KIS_API_KEY``, …) for backward compatibility.
    """
    preferred = all(bool(os.getenv(v)) for v in _REQUIRED_ENV_VARS)
    if preferred:
        return True
    return all(bool(os.getenv(v)) for v in _LEGACY_ENV_VARS)


def _check_paper_env() -> None:
    """Fail immediately if KIS_ENV is set to something other than 'paper'."""
    env = os.getenv("KIS_ENV", "paper")
    if env != "paper":
        pytest.fail(
            f"Live KIS environment detected: KIS_ENV={env!r}. "
            f"Smoke tests are read-only and must run against paper/sandbox only. "
            f"Set KIS_ENV=paper (or unset it) to proceed."
        )


# =========================================================================
# Read-only guard fixture (autouse, function-scoped)
# =========================================================================

@pytest.fixture(autouse=True)
def _read_only_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block write operations on KISRestClient and KoreaInvestmentAdapter.

    Uses ``monkeypatch.setattr()`` at the class level, which is safe for
    ``slots=True`` dataclasses.  The patch is automatically reverted after
    each test function.

    Note
    ----
    ``KISRestClient`` only has ``submit_order`` and ``cancel_order``
    (no ``amend_order``).  ``KoreaInvestmentAdapter`` has all three.
    Each class is patched only for methods it actually defines.
    """

    async def _block(*args: object, **kwargs: object) -> None:
        pytest.fail(
            "Read-only violation: submit_order/cancel_order/amend_order "
            "called during smoke test."
        )

    # KISRestClient: submit_order, cancel_order (no amend_order)
    for op in ("submit_order", "cancel_order"):
        monkeypatch.setattr(KISRestClient, op, _block)
    # KoreaInvestmentAdapter: submit_order, cancel_order, amend_order
    for op in ("submit_order", "cancel_order", "amend_order"):
        monkeypatch.setattr(KoreaInvestmentAdapter, op, _block)


# =========================================================================
# Fixtures
# =========================================================================

# Module-level pacing: minimum 1-second gap between consecutive REST API
# calls across ALL tests in this module.  KIS Paper sandbox enforces a
# global REST 1 rps limit (EGW00201: 초당 거래건수 초과).  Without this
# spacing, cumulative API calls from earlier tests (e.g. test_authentication,
# test_get_quote) trigger the per-second rate limit before the account-level
# tests even start.
_last_api_call: float = 0.0


@pytest.fixture(autouse=True)
async def _space_api_calls() -> None:
    """Ensure >=1.0s between consecutive REST API calls across the module.

    KIS Paper sandbox enforces a **global** REST 1 rps limit
    (EGW00201: 초당 거래건수 초과).  This module-scoped autouse fixture
    enforces a minimum 1-second gap between **every** test function that
    makes a REST API call, so that the smoke suite respects the sandbox
    pacing constraint regardless of which test class the call belongs to.

    The 1-second gap is conservative relative to the 1 rps limit, providing
    headroom for timing jitter in CI and async scheduling.
    """
    global _last_api_call
    now = time.time()
    elapsed = now - _last_api_call
    if elapsed < 1.0:
        await asyncio.sleep(1.0 - elapsed)
    _last_api_call = time.time()


@pytest.fixture(scope="module")
async def kis_rest_client() -> AsyncIterator[KISRestClient]:
    """Module-scoped KISRestClient for read-only smoke tests.

    ``scope="module"`` ensures the access token is obtained once and reused
    across all tests in the module, avoiding KIS Paper's 1-token-per-minute
    rate limit (EGW00133) on the ``oauth2/tokenP`` endpoint.

    Note on KIS Paper rate limits
    -----------------------------
    KIS Paper sandbox enforces a **1-token-per-minute** rate limit
    (EGW00133) on **each** auth endpoint:
    - ``oauth2/tokenP`` (called by ``authenticate()``)
    - ``oauth2/Approval`` (called by ``get_approval_key()``)

    Within a single pytest process with ``scope="module"``, the token is
    cached in ``KISRestClient`` so only the **first** call to each endpoint
    hits the network.  However, running the same smoke suite twice within
    1 minute will trigger rate limits on the second run because a new
    ``KISRestClient`` instance starts with an empty cache.

    ``KISRestClient.close()`` wraps ``RuntimeError`` for Python 3.14
    compatibility (httpx/httpcore/anyio event-loop-closed during teardown).

    Eager authentication
    --------------------
    This fixture calls ``authenticate()`` eagerly (before yielding the
    client) so that EGW00133 (1-token-per-minute rate limit) is caught
    early.  If the rate limit is active, the **entire module** is skipped
    via ``pytest.skip()`` with a clear explanation, instead of letting
    every test fail with an opaque 403.

    Raises ``pytest.fail`` if KIS_ENV is not "paper", or if authentication
    fails for a reason other than EGW00133 (e.g. invalid credentials).
    """
    _check_paper_env()

    api_key = os.getenv("KIS_APP_KEY") or os.getenv("KIS_API_KEY", "")
    api_secret = os.getenv("KIS_APP_SECRET") or os.getenv("KIS_API_SECRET", "")
    account_number = os.getenv("KIS_ACCOUNT_NO") or os.getenv("KIS_ACCOUNT_NUMBER", "")
    account_product_code = os.getenv("KIS_ACCOUNT_PRODUCT_CODE", "01")
    env = os.getenv("KIS_ENV", "paper")

    client = KISRestClient(
        api_key=api_key,
        api_secret=api_secret,
        account_number=account_number,
        account_product_code=account_product_code,
        env=env,
    )

    # Eager authenticate — catch EGW00133 (rate limit) early and skip the
    # entire module with a clear message instead of opaque 403 failures.
    try:
        await client.authenticate()
    except BrokerError as e:
        # Prefer structured raw_message (contains "msg_cd=EGW00133") over
        # string matching; fall back to str(e) if raw_message is None.
        msg = e.raw_message or str(e)
        if "EGW00133" in msg:
            pytest.skip(
                "KIS Paper token rate limit hit (EGW00133: 1 token/min). "
                "Wait ~60 seconds before rerunning the smoke suite."
            )
        pytest.fail(
            f"KIS authentication/setup failed (not a rate-limit issue): {msg}"
        )

    yield client

    try:
        await client.close()
    except RuntimeError:
        # Python 3.14+: httpx/httpcore may raise RuntimeError('Event loop is closed')
        # during teardown when the event loop has already been shut down.
        # This is safe to ignore — the client's transport is already closed.
        pass


@pytest.fixture(scope="module")
async def kis_ws_client(
    kis_rest_client: KISRestClient,
) -> AsyncIterator[KISWebSocketClient]:
    """Module-scoped KISWebSocketClient for WS smoke tests.

    Requires a valid approval key from the REST client.
    """
    try:
        approval_key = await kis_rest_client.get_approval_key()
    except RuntimeError:
        # Python 3.14+: httpx/httpcore may raise RuntimeError('Event loop is closed')
        # during HTTP request teardown.  This is an infrastructure issue, not a
        # credential or API problem — skip the WebSocket tests gracefully.
        pytest.skip(
            "KIS WebSocket approval key acquisition failed: "
            "event loop closed during HTTP request "
            "(Python 3.14 httpx/httpcore teardown issue). "
            "This is an infrastructure issue, not a credential problem."
        )
    env = os.getenv("KIS_ENV", "paper")

    budget = SubscriptionBudget(
        max_subscriptions=25,
        critical_limit=5,
        optional_limit=20,
    )

    client = KISWebSocketClient(
        rest_client=kis_rest_client,
        approval_key=approval_key,
        env=env,
        subscription_budget=budget,
    )

    yield client

    if client._connected:
        try:
            await client.disconnect()
        except RuntimeError:
            # Python 3.14+: websockets/httpcore may raise RuntimeError
            # ('Event loop is closed') during teardown. Safe to ignore.
            pass


# =========================================================================
# Helper: wait for first WebSocket message with timeout
# =========================================================================


async def _wait_first_message(
    ws_client: KISWebSocketClient,
    *,
    timeout: float = _WS_FIRST_MSG_TIMEOUT,
) -> dict[str, Any]:
    """Wait for the first message from the WebSocket with a timeout.

    Returns the first message dict.  Raises ``TimeoutError`` if no message
    arrives within *timeout* seconds.
    """
    async def _first() -> dict[str, Any]:
        async for msg in ws_client.messages():
            return msg
        raise RuntimeError("WebSocket message iterator ended without yielding")

    return await asyncio.wait_for(_first(), timeout=timeout)


# =========================================================================
# Smoke tests — Level 1: Authentication + Quote/Orderbook
# =========================================================================


pytestmark = pytest.mark.skipif(
    not _credentials_configured(),
    reason="KIS API credentials not configured; set KIS_API_KEY, "
    "KIS_API_SECRET, and KIS_ACCOUNT_NUMBER",
)


class TestKISPaperSmokeAuth:
    """Level 1a: Authentication and approval key."""

    @pytest.mark.smoke
    async def test_authentication(self, kis_rest_client: KISRestClient) -> None:
        """Obtain an access token from KIS oauth2/tokenP.

        This is the **first** auth API call in the module.  The token is
        cached in ``KISRestClient._access_token`` so all subsequent tests
        reuse it without hitting the network.
        """
        token = await kis_rest_client.authenticate()
        assert token, "Access token should be a non-empty string"
        assert isinstance(token, str), f"Expected str, got {type(token)}"
        assert len(token) > 20, f"Token seems too short: {len(token)} chars"

    @pytest.mark.smoke
    async def test_approval_key(self, kis_rest_client: KISRestClient) -> None:
        """Obtain a WebSocket approval key from KIS oauth2/approval.

        Calls ``authenticate()`` first (cached — no network) to demonstrate
        token reuse, then calls ``get_approval_key()`` which hits the
        ``oauth2/Approval`` endpoint.

        Note
        ----
        KIS Paper enforces a **1-token-per-minute** rate limit per auth
        endpoint.  ``get_approval_key()`` hits a **different** endpoint
        (``oauth2/Approval``) than ``authenticate()`` (``oauth2/tokenP``),
        so this call is **not** rate-limited by the previous auth call.
        However, running the full smoke suite twice within 1 minute will
        trigger EGW00133 on the second run.
        """
        # Call authenticate() first — it's cached from test_authentication,
        # so this is a no-op that verifies token reuse works correctly.
        token = await kis_rest_client.authenticate()
        assert token, "Cached access token should still be valid"

        approval_key = await kis_rest_client.get_approval_key()
        assert approval_key, "Approval key should be a non-empty string"
        assert isinstance(approval_key, str), (
            f"Expected str, got {type(approval_key)}"
        )
        assert len(approval_key) > 10, (
            f"Approval key seems too short: {len(approval_key)} chars"
        )


class TestKISPaperSmokeMarketData:
    """Level 1b: Market data queries (quote + orderbook)."""

    @pytest.mark.smoke
    async def test_get_quote(self, kis_rest_client: KISRestClient) -> None:
        """Fetch a real-time quote for a liquid Korean stock."""
        # 삼성전자 — most liquid KOSPI stock
        quote = await kis_rest_client.get_quote("005930")
        assert isinstance(quote, dict), f"Expected dict, got {type(quote)}"
        # KIS quote response should contain price fields
        assert "output" in quote or any(
            k for k in quote if "stck_prpr" in k or "last" in k.lower()
        ), f"Unexpected quote structure: {list(quote.keys())}"

    @pytest.mark.smoke
    async def test_get_orderbook(self, kis_rest_client: KISRestClient) -> None:
        """Fetch a real-time orderbook (호가) for a liquid Korean stock."""
        orderbook = await kis_rest_client.get_orderbook("005930")
        assert isinstance(orderbook, dict), f"Expected dict, got {type(orderbook)}"
        # KIS orderbook response should contain bid/ask arrays
        keys = list(orderbook.keys())
        assert any("ask" in k.lower() or "bid" in k.lower() for k in keys), (
            f"Unexpected orderbook structure: {keys}"
        )


# =========================================================================
# Smoke tests — Level 2: Account queries (positions, cash, fills)
# =========================================================================


class TestKISPaperSmokeAccount:
    """Level 2: Account-related read-only queries.

    REST API call spacing is handled by the module-level ``_space_api_calls``
    autouse fixture, which enforces a minimum 1-second gap between
    **every** test function in the module.  This ensures that cumulative
    API calls from earlier test classes (e.g. ``test_authentication``,
    ``test_get_quote``) do not trigger KIS Paper's global REST 1 rps limit
    (EGW00201: 초당 거래건수 초과) before the account-level tests run.
    """

    @pytest.mark.smoke
    async def test_get_positions(self, kis_rest_client: KISRestClient) -> None:
        """Fetch current positions (잔고)."""
        positions = await kis_rest_client.get_positions()
        assert isinstance(positions, (list, dict)), (
            f"Expected list or dict, got {type(positions)}"
        )
        # Paper account may be empty — that's fine, just check structure
        if isinstance(positions, list):
            for item in positions:
                assert isinstance(item, dict), (
                    f"Each position should be a dict, got {type(item)}"
                )

    @pytest.mark.smoke
    async def test_get_cash_balance(self, kis_rest_client: KISRestClient) -> None:
        """Fetch cash balance (예수금)."""
        balance = await kis_rest_client.get_cash_balance()
        assert isinstance(balance, dict), f"Expected dict, got {type(balance)}"
        # Should contain some balance-related keys
        keys = list(balance.keys())
        assert len(keys) > 0, "Cash balance response should not be empty"

    @pytest.mark.smoke
    async def test_get_fills(self, kis_rest_client: KISRestClient) -> None:
        """Fetch recent fills (체결 내역)."""
        fills = await kis_rest_client.get_fills()
        assert isinstance(fills, (list, dict)), (
            f"Expected list or dict, got {type(fills)}"
        )
        # Paper account may have no fills — check structure only
        if isinstance(fills, list):
            for item in fills:
                assert isinstance(item, dict), (
                    f"Each fill should be a dict, got {type(item)}"
                )


# =========================================================================
# Smoke tests — Level 3: WebSocket receive (slow)
# =========================================================================


class TestKISPaperSmokeWebSocket:
    """Level 3: WebSocket connection and message reception.

    Pass condition: receive at least one message (ack or data) within 15 s.
    """

    @pytest.mark.slow
    @pytest.mark.smoke
    async def test_websocket_receive(self, kis_ws_client: KISWebSocketClient) -> None:
        """Connect to KIS WebSocket, subscribe to a channel, and verify reception.

        Pass condition: first message (ack or data) received within 15 s.
        """
        await kis_ws_client.connect()

        # Subscribe to a liquid stock's trade price channel
        await kis_ws_client.subscribe("H0STCNT0", "005930", critical=False)

        # Wait for the first message with a 15-second timeout
        try:
            received = await _wait_first_message(kis_ws_client, timeout=15.0)
        except TimeoutError:
            pytest.fail(
                "No message received from WebSocket within 15 seconds. "
                "Expected at least an ack or a data message."
            )

        assert isinstance(received, dict), (
            f"Expected dict message, got {type(received)}"
        )
        assert len(received) > 0, "Received message should not be empty"
