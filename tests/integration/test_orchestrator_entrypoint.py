"""Integration tests for ``scripts.run_orchestrator_once``.

Verifies that the entrypoint can:
1. Idempotently seed the FK chain.
2. Run ``orchestrator.assemble()`` and produce DB rows.
3. **Never** call broker submit.
4. Produce rows readable via the inspection API (``TestClient``).

Run with::

    pytest tests/integration/test_orchestrator_entrypoint.py -v --no-header
"""

from __future__ import annotations

from uuid import UUID

import pytest

from agent_trading.domain.entities import (
    AccountEntity,
    BrokerAccountEntity,
    ClientEntity,
    ConfigVersionEntity,
    StrategyEntity,
)
from agent_trading.domain.enums import AssetClass, Environment, OrderSide, OrderType
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.runtime.bootstrap import postgres_runtime

# ---------------------------------------------------------------------------
# Constants — must match scripts/run_orchestrator_once.py
# ---------------------------------------------------------------------------
CLIENT_ID = UUID("11111111-1111-1111-1111-111111111111")
BROKER_ACCOUNT_ID = UUID("22222222-2222-2222-2222-222222222222")
ACCOUNT_ID = UUID("33333333-3333-3333-3333-333333333333")
STRATEGY_ID = UUID("44444444-4444-4444-4444-444444444444")
CONFIG_VERSION_ID = UUID("55555555-5555-5555-5555-555555555555")

CLIENT_CODE = "ENTRYPOINT_CLIENT"
ACCOUNT_ALIAS = "entrypoint-account"
STRATEGY_CODE = "ENTRYPOINT_STRAT"
SYMBOL = "005930"
MARKET = "KRX"


def _pg_available() -> bool:
    """Check whether Postgres env vars are set (docker compose defaults)."""
    import os
    return bool(os.environ.get("DATABASE_HOST") or os.environ.get("DATABASE_URL"))


# ---------------------------------------------------------------------------
# Helpers — mirror scripts/run_orchestrator_once.py
# ---------------------------------------------------------------------------
async def _seed_if_empty(repos: RepositoryContainer) -> bool:
    """Idempotent seed — same logic as the entrypoint."""
    existing = await repos.clients.get_by_code(CLIENT_CODE)
    if existing is not None:
        return False

    broker_account = BrokerAccountEntity(
        broker_account_id=BROKER_ACCOUNT_ID,
        broker_name="ENTRYPOINT_BROKER",
        account_ref="entrypoint-broker-ref",
        environment=Environment.PAPER,
        credential_ref="entrypoint-cred",
        base_url="https://mock.broker/api",
        status="active",
    )
    await repos.broker_accounts.add(broker_account)

    client = ClientEntity(
        client_id=CLIENT_ID,
        client_code=CLIENT_CODE,
        name="Entrypoint Client",
        status="active",
        base_currency="KRW",
    )
    await repos.clients.add(client)

    account = AccountEntity(
        account_id=ACCOUNT_ID,
        client_id=CLIENT_ID,
        broker_account_id=BROKER_ACCOUNT_ID,
        environment=Environment.PAPER,
        account_alias=ACCOUNT_ALIAS,
        account_masked="****0001",
        status="active",
    )
    await repos.accounts.add(account)

    strategy = StrategyEntity(
        strategy_id=STRATEGY_ID,
        client_id=CLIENT_ID,
        strategy_code=STRATEGY_CODE,
        name="Entrypoint Strategy",
        asset_class=AssetClass.KR_STOCK.value,
        status="active",
    )
    await repos.strategies.add(strategy)

    from datetime import datetime, timezone
    config_version = ConfigVersionEntity(
        config_version_id=CONFIG_VERSION_ID,
        client_id=CLIENT_ID,
        environment=Environment.PAPER,
        version_tag="v1.0",
        config_json={"max_position_size": "0.1"},
        checksum="entrypoint-checksum",
        activated_at=datetime.now(timezone.utc),
    )
    await repos.config_versions.add(config_version)
    return True


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _pg_available(), reason="requires DATABASE_HOST or DATABASE_URL")
@pytest.mark.asyncio
async def test_entrypoint_seeds_and_assembles() -> None:
    """Seed → assemble → verify DB rows (decision_contexts, trade_decisions,
    agent_runs)."""
    async with postgres_runtime(auto_rollback=True) as runtime:
        repos: RepositoryContainer = runtime["repositories"]
        orchestrator = runtime["orchestrator"]

        # Seed
        seeded = await _seed_if_empty(repos)
        assert seeded is True, "Expected first-time seed"

        # Assemble
        request = SubmitOrderRequest(
            account_ref=ACCOUNT_ALIAS,
            client_order_id="test-entrypoint-001",
            correlation_id="test-correlation-001",
            strategy_id=str(STRATEGY_ID),
            symbol=SYMBOL,
            market=MARKET,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            price=50000,
        )
        intent = await orchestrator.assemble(request)

        # --- Assertions ---
        dc_id = intent.decision_context_id
        assert dc_id is not None, "decision_context_id must be created"

        # 1. decision_contexts
        ctx = await repos.decision_contexts.get(dc_id)
        assert ctx is not None, "decision_context must exist in DB"
        assert ctx.account_id == ACCOUNT_ID
        assert ctx.strategy_id == STRATEGY_ID

        # 2. trade_decisions
        decisions = await repos.trade_decisions.list_all()
        assert len(decisions) == 1, "Expected 1 trade_decision"
        td = decisions[0]
        assert td.decision_context_id == dc_id
        assert td.symbol == SYMBOL

        # 3. agent_runs — count AND agent_type diversity
        runs = await repos.agent_runs.list_by_decision_context(dc_id)
        assert len(runs) == 3, f"Expected 3 agent_runs, got {len(runs)}"

        agent_types = {r.agent_type for r in runs}
        expected_types = {"event_interpretation", "ai_risk", "final_decision_composer"}
        missing = expected_types - agent_types
        assert not missing, f"Missing agent_type(s): {missing}"


@pytest.mark.skipif(not _pg_available(), reason="requires DATABASE_HOST or DATABASE_URL")
@pytest.mark.asyncio
async def test_entrypoint_idempotent_seed() -> None:
    """Calling ``_seed_if_empty`` twice must not raise (idempotent)."""
    async with postgres_runtime(auto_rollback=True) as runtime:
        repos: RepositoryContainer = runtime["repositories"]

        # First call
        first = await _seed_if_empty(repos)
        assert first is True

        # Second call — must not raise and must return False
        second = await _seed_if_empty(repos)
        assert second is False, "Second seed must be skipped (idempotent)"


@pytest.mark.skipif(not _pg_available(), reason="requires DATABASE_HOST or DATABASE_URL")
@pytest.mark.asyncio
async def test_entrypoint_no_broker_submit() -> None:
    """Verify that ``assemble()`` does **not** call broker submit.

    We monkey-patch ``OrderManager.create_order`` to raise if called.
    Since the entrypoint only calls ``orchestrator.assemble()``, this
    should never be reached.
    """
    import agent_trading.services.order_manager as om_mod

    original = om_mod.OrderManager.create_order

    async def _block(*args: object, **kwargs: object) -> None:
        pytest.fail("Broker submit was called — this must never happen!")

    om_mod.OrderManager.create_order = _block  # type: ignore[method-assign]
    try:
        async with postgres_runtime(auto_rollback=True) as runtime:
            repos: RepositoryContainer = runtime["repositories"]
            orchestrator = runtime["orchestrator"]

            await _seed_if_empty(repos)

            request = SubmitOrderRequest(
                account_ref=ACCOUNT_ALIAS,
                client_order_id="test-entrypoint-002",
                correlation_id="test-correlation-002",
                strategy_id=str(STRATEGY_ID),
                symbol=SYMBOL,
                market=MARKET,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=10,
                price=50000,
            )
            intent = await orchestrator.assemble(request)
            assert intent.decision_context_id is not None
    finally:
        om_mod.OrderManager.create_order = original


@pytest.mark.skipif(not _pg_available(), reason="requires DATABASE_HOST or DATABASE_URL")
@pytest.mark.asyncio
async def test_entrypoint_readable_via_api() -> None:
    """Verify that generated rows are readable via the inspection API.

    Uses ``auto_rollback=False`` + explicit ``commit()`` so the seeded
    data is persisted.  Then uses ``httpx.AsyncClient`` with
    ``ASGITransport`` (same event loop) to call the app — the
    ``get_repos`` dependency opens a fresh ``TransactionManager`` per
    request, which can see the committed data.

    Uses a unique ``correlation_id`` per run to avoid unique-constraint
    collisions from previous committed runs.
    """
    import uuid
    from agent_trading.api.app import create_app
    from httpx import AsyncClient, ASGITransport

    uid = uuid.uuid4().hex[:8]
    correlation_id = f"test-readable-api-{uid}"

    async with postgres_runtime(auto_rollback=False) as runtime:
        repos: RepositoryContainer = runtime["repositories"]
        orchestrator = runtime["orchestrator"]

        await _seed_if_empty(repos)

        request = SubmitOrderRequest(
            account_ref=ACCOUNT_ALIAS,
            client_order_id=f"test-entrypoint-readable-{uid}",
            correlation_id=correlation_id,
            strategy_id=str(STRATEGY_ID),
            symbol=SYMBOL,
            market=MARKET,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            price=50000,
        )
        intent = await orchestrator.assemble(request)
        dc_id = intent.decision_context_id
        assert dc_id is not None

        # Commit so data is visible from other transactions.
        tx = repos.clients._tx  # TransactionManager
        await tx.commit()

        # Build a test app in postgres mode — get_repos will create a
        # fresh TransactionManager per request, seeing the committed data.
        app = create_app(runtime_mode="postgres", auth_enabled=False)

        # ASGITransport does NOT run the lifespan automatically, so we
        # set app.state directly so get_repos can find the runtime_mode.
        app.state.runtime_mode = "postgres"

        # Use httpx.AsyncClient with ASGITransport — same event loop,
        # no loop conflict like TestClient.
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # GET /trade-decisions
            resp = await client.get("/trade-decisions")
            assert resp.status_code == 200, f"trade-decisions: {resp.status_code} {resp.text}"
            data = resp.json()
            assert isinstance(data, list)
            assert len(data) >= 1, f"Expected at least 1 trade_decision, got {len(data)}"

            # GET /agent-runs
            resp2 = await client.get(f"/agent-runs?decision_context_id={dc_id}")
            assert resp2.status_code == 200, f"agent-runs: {resp2.status_code} {resp2.text}"
            runs = resp2.json()
            assert isinstance(runs, list)
            assert len(runs) == 3, f"Expected 3 agent_runs, got {len(runs)}"

            agent_types = {r["agent_type"] for r in runs}
            assert "event_interpretation" in agent_types
            assert "ai_risk" in agent_types
            assert "final_decision_composer" in agent_types
