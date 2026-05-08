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

CLIENT_CODE = "EPC001"
ACCOUNT_ALIAS = "Entrypoint Paper"
STRATEGY_CODE = "ENTRYPOINT_STRAT"
SYMBOL = "005930"
MARKET = "KRX"


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------
async def _seed_if_empty(repos: RepositoryContainer) -> bool:
    """Idempotent seed: insert FK chain only when prerequisite rows exist.

    Checks each entity by PK (deterministic UUID) to avoid
    ``UniqueViolationError`` on re-run (e.g. after manual backfill).

    Returns ``True`` if seeding was performed, ``False`` if already seeded.
    """
    existing = await repos.clients.get(CLIENT_ID)
    if existing is not None:
        logger.info("Seed already exists (client=%s) — skipping.", CLIENT_ID)
        return False

    logger.info("Seeding prerequisite FK chain …")

    # 1. BrokerAccount (FK target for Account.broker_account_id)
    existing_ba = await repos.broker_accounts.get(BROKER_ACCOUNT_ID)
    if existing_ba is None:
        broker_account = BrokerAccountEntity(
            broker_account_id=BROKER_ACCOUNT_ID,
            broker_name="KoreaInvestment",
            account_ref="50045678",
            environment=Environment.PAPER,
            credential_ref="entrypoint-cred",
            base_url="https://mock.broker/api",
            status="active",
            broker_account_code="KIS-PAPER-****5678",
        )
        await repos.broker_accounts.add(broker_account)
    else:
        logger.info("BrokerAccount %s already exists — skipping.", BROKER_ACCOUNT_ID)

    # 2. Client
    existing_client = await repos.clients.get(CLIENT_ID)
    if existing_client is None:
        client = ClientEntity(
            client_id=CLIENT_ID,
            client_code=CLIENT_CODE,
            name="Entrypoint Client",
            status="active",
            base_currency="KRW",
        )
        await repos.clients.add(client)
    else:
        logger.info("Client %s already exists — skipping.", CLIENT_ID)

    # 3. Account (references broker_account + client)
    existing_account = await repos.accounts.get(ACCOUNT_ID)
    if existing_account is None:
        account = AccountEntity(
            account_id=ACCOUNT_ID,
            client_id=CLIENT_ID,
            broker_account_id=BROKER_ACCOUNT_ID,
            environment=Environment.PAPER,
            account_alias=ACCOUNT_ALIAS,
            account_masked="****5678",
            status="active",
            account_code="EPC001-PAPER-ENTRYPOINT",
        )
        await repos.accounts.add(account)
    else:
        logger.info("Account %s already exists — skipping.", ACCOUNT_ID)

    # 4. Strategy (references client)
    existing_strategy = await repos.strategies.get(STRATEGY_ID)
    if existing_strategy is None:
        strategy = StrategyEntity(
            strategy_id=STRATEGY_ID,
            client_id=CLIENT_ID,
            strategy_code=STRATEGY_CODE,
            name="Entrypoint Strategy",
            asset_class=AssetClass.KR_STOCK.value,
            status="active",
        )
        await repos.strategies.add(strategy)
    else:
        logger.info("Strategy %s already exists — skipping.", STRATEGY_ID)

    # 5. ConfigVersion (references client; activated_at MUST be set)
    existing_cv = await repos.config_versions.get(CONFIG_VERSION_ID)
    if existing_cv is None:
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
    else:
        logger.info("ConfigVersion %s already exists — skipping.", CONFIG_VERSION_ID)

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
