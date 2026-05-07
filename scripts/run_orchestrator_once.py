#!/usr/bin/env python3
"""Minimal orchestrator entrypoint: seed prerequisites, run ``assemble()``,
print results, and exit — **without** broker submit.

Usage
-----
.. code-block:: bash

    # Requires a running Postgres (e.g. ``docker compose up -d db``).
    python -m scripts.run_orchestrator_once

Environment variables
---------------------
Same as the main application (``DATABASE_URL``, etc.).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

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

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — deterministic IDs for idempotent seeding
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


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------
async def _seed_if_empty(repos: RepositoryContainer) -> bool:
    """Idempotent seed: insert FK chain only when the client does not exist.

    Returns ``True`` if seeding was performed, ``False`` if already seeded.
    """
    existing = await repos.clients.get_by_code(CLIENT_CODE)
    if existing is not None:
        logger.info("Seed already exists (client=%s) — skipping.", existing.client_id)
        return False

    logger.info("Seeding prerequisite FK chain …")

    # 1. BrokerAccount (FK target for Account.broker_account_id)
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

    # 2. Client
    client = ClientEntity(
        client_id=CLIENT_ID,
        client_code=CLIENT_CODE,
        name="Entrypoint Client",
        status="active",
        base_currency="KRW",
    )
    await repos.clients.add(client)

    # 3. Account (references broker_account + client)
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

    # 4. Strategy (references client)
    strategy = StrategyEntity(
        strategy_id=STRATEGY_ID,
        client_id=CLIENT_ID,
        strategy_code=STRATEGY_CODE,
        name="Entrypoint Strategy",
        asset_class=AssetClass.KR_STOCK.value,
        status="active",
    )
    await repos.strategies.add(strategy)

    # 5. ConfigVersion (references client; activated_at MUST be set)
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

    logger.info(
        "Seed complete: broker_account=%s client=%s account=%s strategy=%s config_version=%s",
        BROKER_ACCOUNT_ID,
        CLIENT_ID,
        ACCOUNT_ID,
        STRATEGY_ID,
        CONFIG_VERSION_ID,
    )
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    async with postgres_runtime() as runtime:
        repos: RepositoryContainer = runtime["repositories"]
        orchestrator = runtime["orchestrator"]

        # Step 1: idempotent seed
        seeded = await _seed_if_empty(repos)
        if seeded:
            logger.info("Prerequisite rows inserted.")
        else:
            logger.info("Using existing seed data.")

        # Step 2: build SubmitOrderRequest with valid UUID strategy_id
        request = SubmitOrderRequest(
            account_ref=ACCOUNT_ALIAS,
            client_order_id="entrypoint-001",
            correlation_id="entrypoint-correlation-001",
            strategy_id=str(STRATEGY_ID),
            symbol=SYMBOL,
            market=MARKET,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("10"),
            price=Decimal("50000"),
        )

        # Step 3: run orchestrator.assemble() — NO broker submit
        logger.info("Calling orchestrator.assemble() …")
        intent = await orchestrator.assemble(request)

        # Step 4: print results
        dc_id = intent.decision_context_id
        logger.info("=" * 60)
        logger.info("Orchestrator assemble completed.")
        logger.info("  decision_context_id : %s", dc_id)
        logger.info("  order_intent_id     : %s", intent.order_intent_id)
        logger.info("  config_version_id   : %s", intent.config_version_id)
        logger.info("  reason_codes        : %s", intent.reason_codes)

        # Step 5: verify DB rows
        if dc_id is not None:
            # decision_contexts
            ctx = await repos.decision_contexts.get(dc_id)
            logger.info("  decision_contexts   : %s row(s)", 1 if ctx else 0)

            # trade_decisions
            decisions = await repos.trade_decisions.list_all()
            logger.info("  trade_decisions     : %s row(s)", len(decisions))
            for d in decisions:
                logger.info("    trade_decision_id=%s type=%s side=%s symbol=%s",
                            d.trade_decision_id, d.decision_type, d.side, d.symbol)

            # agent_runs
            runs = await repos.agent_runs.list_by_decision_context(dc_id)
            logger.info("  agent_runs          : %s row(s)", len(runs))
            agent_types = [r.agent_type for r in runs]
            for at in sorted(agent_types):
                logger.info("    agent_type=%s", at)
        else:
            logger.warning("No decision context was created — check prerequisites.")

        logger.info("=" * 60)
        logger.info("Done. No broker submit was performed.")


if __name__ == "__main__":
    asyncio.run(main())
