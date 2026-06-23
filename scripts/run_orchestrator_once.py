#!/usr/bin/env python3
"""Minimal orchestrator entrypoint: seed prerequisites, run ``assemble()``
or ``assemble_and_submit()``, print results, and exit.

**단발 실행 전용** — ``--interval`` 등 반복 실행 옵션 없음.
반복 실행(continuous loop)이 필요하면 ``verify_decision_loop.py`` 사용.

Usage
-----
.. code-block:: bash

    # assemble only (no broker submit):
    python -m scripts.run_orchestrator_once

    # full pipeline: assemble → validate → create_order → submit_order:
    python -m scripts.run_orchestrator_once --submit

    # dry-run: assemble + sizing only, no broker submit:
    python -m scripts.run_orchestrator_once --dry-run

    # JSON output for automated analysis:
    python -m scripts.run_orchestrator_once --submit --output json

Environment variables
---------------------
Same as the main application (``DATABASE_URL``, etc.).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID, uuid4

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

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
from agent_trading.services.common_types import SubmitResult

logger = logging.getLogger(__name__)


def _load_local_dotenv() -> bool:
    """프로젝트 루트의 ``.env``를 로드한다.

    ``python-dotenv``가 없거나 ``.env`` 파일이 없으면 조용히 건너뛴다.
    반환값은 실제 로드 시도 여부만 나타낸다.
    """
    if load_dotenv is None:
        return False

    dotenv_path = Path(__file__).resolve().parent.parent / ".env"
    if not dotenv_path.exists():
        return False

    load_dotenv(dotenv_path)
    return True

# ---------------------------------------------------------------------------
# Constants — deterministic IDs for idempotent seeding
# Generated via uuid5(NAMESPACE_DNS, "{entity_type}.entrypoint")
# to ensure realistic-looking UUIDs without repeating digit patterns.
# ---------------------------------------------------------------------------
CLIENT_ID = UUID("301961b4-75d9-533c-92b7-69a306cdd435")
BROKER_ACCOUNT_ID = UUID("7f39fc04-346a-5484-90ab-80e8a1d04a15")
ACCOUNT_ID = UUID("a44a02d1-7f32-5a62-99f7-235abeb58284")
STRATEGY_ID = UUID("30a1d26b-8230-51fc-8548-30920effff0c")
CONFIG_VERSION_ID = UUID("529ab376-183a-53df-b4ab-73d948c1404c")

CLIENT_CODE = "EPC001"
ACCOUNT_ALIAS = "Entrypoint Paper"
STRATEGY_CODE = "ENTRYPOINT_STRAT"
SYMBOL = "005930"
MARKET = "KRX"

# ---------------------------------------------------------------------------
# Env-driven broker metadata resolution
# Seed must reflect actual KIS paper account metadata so that re-seed alone
# produces correct values — no manual DB UPDATE required.
# ---------------------------------------------------------------------------

def _resolve_smoke_price() -> Decimal:
    """Return order price for smoke/test execution.

    .. note::
       초기 request는 ``MARKET`` + ``price=None``으로 전달된다.
       다만 실제 submit 직전에는 ``ExecutionService``가
       저유동성 BUY에 대해 ``LIMIT`` 강제 또는 submit 차단을
       적용할 수 있다. 이 함수의 반환값은 주로 quote 수집 및
       observability 용도로 유지된다.

    Priority:
    1. ``KIS_SMOKE_PRICE`` env var (for smoke runs with a specific price).
    2. ``Decimal("50000")`` safe default (dry-run / non-submit usage).

    Always logs the resolved price and its source for observability.
    """
    raw = os.environ.get("KIS_SMOKE_PRICE")
    if raw is not None:
        try:
            price = Decimal(raw)
            logger.info("Using KIS_SMOKE_PRICE=%s from env var", price)
            return price
        except (InvalidOperation, ValueError):
            logger.warning(
                "Invalid KIS_SMOKE_PRICE=%r, falling back to default 50000", raw,
            )
    logger.info("KIS_SMOKE_PRICE not set, using default price=50000")
    return Decimal("50000")


def _seed_account_ref() -> str:
    """Resolve broker ``account_ref`` from ``KIS_ACCOUNT_NO`` env var.

    Falls back to the current known paper account number so that the seed
    works in CI / offline environments too.
    """
    return os.getenv("KIS_ACCOUNT_NO") or os.getenv("KIS_ACCOUNT_NUMBER", "50186448")


def _seed_last4() -> str:
    """Return the last 4 digits of the resolved account ref.

    Non-digit characters are stripped first; if fewer than 4 digits remain,
    the value is zero-padded to length 4.
    """
    ref = _seed_account_ref()
    digits = re.sub(r"[^0-9]", "", ref)
    if len(digits) >= 4:
        return digits[-4:]
    return digits.zfill(4)


def _seed_broker_code() -> str:
    """Derive ``broker_account_code`` from ``KIS_ENV`` + ``_seed_last4()``.

    Format: ``KIS-{ENV}-****{last4}``  (e.g. ``KIS-PAPER-****6448``).
    """
    env = os.getenv("KIS_ENV", "paper").strip().lower().replace("real", "live")
    return f"KIS-{env.upper()}-****{_seed_last4()}"


def _seed_masked() -> str:
    """Derive ``account_masked`` from ``_seed_last4()``.

    Format: ``****{last4}`` (e.g. ``****6448``).
    """
    return f"****{_seed_last4()}"


def _seed_base_url() -> str:
    """Use ``KIS_BASE_URL`` from env, fall back to the official KIS paper URL."""
    return os.getenv("KIS_BASE_URL", "https://openapivts.koreainvestment.com:29443")


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------
async def _seed_if_empty(repos: RepositoryContainer) -> bool:
    """Idempotent seed: ensure prerequisite FK chain exists.

    Partial rows may already exist in production-like environments
    (for example ``clients``/``broker_accounts`` exist while ``accounts``
    was deleted or never inserted).  Therefore this helper must check
    and heal each entity independently instead of short-circuiting on
    the first existing row.

    Returns ``True`` if at least one row was inserted, ``False`` if the
    full prerequisite chain already existed.
    """
    inserted_any = False

    logger.info("Seeding prerequisite FK chain …")

    # 1. BrokerAccount (FK target for Account.broker_account_id)
    existing_ba = await repos.broker_accounts.get(BROKER_ACCOUNT_ID)
    if existing_ba is None:
        broker_account = BrokerAccountEntity(
            broker_account_id=BROKER_ACCOUNT_ID,
            broker_name="koreainvestment",
            account_ref=_seed_account_ref(),
            environment=Environment.PAPER,
            credential_ref="entrypoint-cred",
            base_url=_seed_base_url(),
            status="active",
            broker_account_code=_seed_broker_code(),
        )
        await repos.broker_accounts.add(broker_account)
        inserted_any = True
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
        inserted_any = True
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
            account_masked=_seed_masked(),
            status="active",
            account_code="EPC001-PAPER-ENTRYPOINT",
        )
        await repos.accounts.add(account)
        inserted_any = True
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
        inserted_any = True
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
            config_json={
                "risk": {
                    "max_single_position_pct": "10",    # 10% = NAV 대비 단일 종목 최대 10%
                    "min_cash_buffer_pct": "5",         # 5% = 최소 현금 보유 5%
                },
                "execution": {
                    "max_order_value": "50000000",      # 5천만원 = 1회 주문 최대 금액
                    "min_order_qty": "1",
                    "max_order_qty": "10000",
                },
            },
            checksum="entrypoint-checksum",
            activated_at=datetime.now(timezone.utc),
        )
        await repos.config_versions.add(config_version)
        inserted_any = True
    else:
        logger.info("ConfigVersion %s already exists — skipping.", CONFIG_VERSION_ID)

    if inserted_any:
        logger.info(
            "Seed complete: broker_account=%s client=%s account=%s strategy=%s config_version=%s",
            BROKER_ACCOUNT_ID,
            CLIENT_ID,
            ACCOUNT_ID,
            STRATEGY_ID,
            CONFIG_VERSION_ID,
        )
    else:
        logger.info(
            "Seed already exists and is complete: broker_account=%s client=%s account=%s strategy=%s config_version=%s",
            BROKER_ACCOUNT_ID,
            CLIENT_ID,
            ACCOUNT_ID,
            STRATEGY_ID,
            CONFIG_VERSION_ID,
        )
    return inserted_any


def _serialize_result(result: SubmitResult) -> dict[str, object]:
    """Serialize a ``SubmitResult`` to a JSON-compatible dict."""
    data: dict[str, object] = {
        "status": result.status,
        "error_phase": result.error_phase,
        "error_message": result.error_message,
        "trade_decision_id": str(result.trade_decision_id) if result.trade_decision_id else None,
        "decision_context_id": str(result.decision_context_id) if result.decision_context_id else None,
    }
    if result.order_intent is not None:
        data["order_intent_id"] = str(result.order_intent.order_intent_id)
        data["decision_type"] = result.order_intent.ai_backend_inputs.decision_type
        data["sized_quantity"] = str(result.order_intent.request.quantity)
    if result.submit_response is not None:
        data["order_id"] = str(result.submit_response.order_request_id)
        data["order_status"] = result.submit_response.status.value
        data["client_order_id"] = result.submit_response.client_order_id
        data["status_reason_code"] = result.submit_response.status_reason_code
        data["requested_quantity"] = str(result.submit_response.requested_quantity)
    return data


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main() -> int:
    """Run the orchestrator and return an exit code.

    Returns
    -------
    int
        ``0`` on success, ``1`` on failure.
    """
    dotenv_loaded = _load_local_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    if dotenv_loaded:
        logger.info("Loaded environment from project .env")

    parser = argparse.ArgumentParser(
        description="Run the orchestrator and optionally submit orders to the broker. "
                    "One-shot only — for continuous mode use ``verify_decision_loop.py``.",
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        default=False,
        help="Run the full assemble → submit pipeline (default: assemble only)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Run assemble + sizing only, no broker submit. Implies no --submit needed.",
    )
    parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format: ``text`` (human-readable) or ``json`` (machine-readable)",
    )
    args = parser.parse_args()

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
        resolved_price = _resolve_smoke_price()
        if args.submit:
            logger.info(
                "KIS_SMOKE_PRICE=%s (ignored under MARKET order policy — price=None is used).",
                resolved_price,
            )
        request = SubmitOrderRequest(
            account_ref=ACCOUNT_ALIAS,
            client_order_id="entrypoint-001",
            correlation_id=f"entrypoint-correlation-{uuid4()}",
            strategy_id=str(STRATEGY_ID),
            symbol=SYMBOL,
            market=MARKET,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
            price=None,
        )

        # ── Dry-run: assemble + sizing only, no broker submit ──
        if args.dry_run:
            logger.info("Dry-run mode: assemble + sizing only (no broker submit).")
            intent = await orchestrator.assemble(request)

            # Run sizing engine (same as Phase 1.5 in full pipeline)
            sizing_inputs = orchestrator.build_sizing_inputs(intent)
            from agent_trading.services.sizing_engine import calculate_sizing
            sizing_result = calculate_sizing(sizing_inputs)

            dc_id = intent.decision_context_id
            if args.output == "json":
                output: dict[str, object] = {
                    "mode": "dry-run",
                    "status": "assemble_complete",
                    "decision_context_id": str(dc_id) if dc_id else None,
                    "order_intent_id": str(intent.order_intent_id),
                    "decision_type": intent.ai_backend_inputs.decision_type,
                    "symbol": intent.request.symbol,
                    "side": intent.request.side.value,
                    "requested_quantity": str(intent.request.quantity),
                    "sizing": {
                        "quantity": str(sizing_result.quantity),
                        "applied_constraints": list(sizing_result.applied_constraints),
                        "skip_reason": sizing_result.skip_reason,
                    },
                    "config_version_id": str(intent.config_version_id) if intent.config_version_id else None,
                    "reason_codes": [str(rc) for rc in (intent.reason_codes or [])],
                }
                print(json.dumps(output, indent=2, ensure_ascii=False))
            else:
                logger.info("=" * 60)
                logger.info("Dry-run assemble complete.")
                logger.info("  decision_context_id : %s", dc_id)
                logger.info("  order_intent_id     : %s", intent.order_intent_id)
                logger.info("  decision_type       : %s", intent.ai_backend_inputs.decision_type)
                logger.info("  symbol              : %s", intent.request.symbol)
                logger.info("  side                : %s", intent.request.side)
                logger.info("  requested_quantity  : %s", intent.request.quantity)
                logger.info("  config_version_id   : %s", intent.config_version_id)
                logger.info("  reason_codes        : %s", intent.reason_codes)
                logger.info("  sizing_quantity     : %s", sizing_result.quantity)
                logger.info("  sizing_constraints  : %s", sizing_result.applied_constraints)
                if sizing_result.skip_reason:
                    logger.info("  sizing_skip_reason  : %s", sizing_result.skip_reason)
                logger.info("=" * 60)
            return 0

        if args.submit:
            # ── Full pipeline: assemble → validate → create_order → submit ──
            order_manager = runtime["order_manager"]
            broker = runtime["primary_broker_adapter"]
            logger.info(
                "Calling orchestrator.assemble_and_submit() with broker=%s …",
                broker.__class__.__name__,
            )
            result: SubmitResult = await orchestrator.assemble_and_submit(
                request,
                order_manager=order_manager,
                broker=broker,
            )

            if args.output == "json":
                print(json.dumps(_serialize_result(result), indent=2, ensure_ascii=False))
            else:
                logger.info("=" * 60)
                logger.info("Pipeline complete.")
                logger.info("  status              : %s", result.status)
                logger.info("  error_phase         : %s", result.error_phase)
                logger.info("  error_message       : %s", result.error_message)
                logger.info("  trade_decision_id   : %s", result.trade_decision_id)
                if result.order_intent is not None:
                    logger.info("  decision_context_id : %s", result.order_intent.decision_context_id)
                    logger.info("  order_intent_id     : %s", result.order_intent.order_intent_id)
                if result.submit_response is not None:
                    logger.info("  order_id            : %s", result.submit_response.order_request_id)
                    logger.info("  order_status        : %s", result.submit_response.status)
                    logger.info("  requested_quantity  : %s", result.submit_response.requested_quantity)
                logger.info("=" * 60)

            # Return exit code based on result status
            if result.status in ("SUBMITTED", "SKIPPED"):
                return 0
            if result.status == "RECONCILE_REQUIRED":
                # Recoverable — warn but return success
                logger.warning("Order requires reconciliation (code=%s)",
                               result.submit_response.status_reason_code if result.submit_response else "N/A")
                return 0
            # ERROR or REJECTED
            return 1
        else:
            # ── Assemble only (no broker submit) ──
            logger.info("Calling orchestrator.assemble() …")
            intent = await orchestrator.assemble(request)

            dc_id = intent.decision_context_id
            if args.output == "json":
                assemble_output: dict[str, object] = {
                    "mode": "assemble-only",
                    "status": "assemble_complete",
                    "decision_context_id": str(dc_id) if dc_id else None,
                    "order_intent_id": str(intent.order_intent_id),
                    "decision_type": intent.ai_backend_inputs.decision_type,
                    "symbol": intent.request.symbol,
                    "side": intent.request.side.value,
                    "requested_quantity": str(intent.request.quantity),
                    "config_version_id": str(intent.config_version_id) if intent.config_version_id else None,
                    "reason_codes": [str(rc) for rc in (intent.reason_codes or [])],
                }
                print(json.dumps(assemble_output, indent=2, ensure_ascii=False))
            else:
                logger.info("=" * 60)
                logger.info("Orchestrator assemble completed.")
                logger.info("  decision_context_id : %s", dc_id)
                logger.info("  order_intent_id     : %s", intent.order_intent_id)
                logger.info("  config_version_id   : %s", intent.config_version_id)
                logger.info("  reason_codes        : %s", intent.reason_codes)
                logger.info("  decision_type       : %s", intent.ai_backend_inputs.decision_type)
                logger.info("  symbol              : %s", intent.request.symbol)
                logger.info("  side                : %s", intent.request.side)
                logger.info("  requested_quantity  : %s", intent.request.quantity)

                if dc_id is not None:
                    ctx = await repos.decision_contexts.get(dc_id)
                    logger.info("  decision_contexts   : %s row(s)", 1 if ctx else 0)

                    decisions = await repos.trade_decisions.list_all()
                    logger.info("  trade_decisions     : %s row(s)", len(decisions))
                    for d in decisions:
                        logger.info("    trade_decision_id=%s type=%s side=%s symbol=%s",
                                    d.trade_decision_id, d.decision_type, d.side, d.symbol)

                    runs = await repos.agent_runs.list_by_decision_context(dc_id)
                    logger.info("  agent_runs          : %s row(s)", len(runs))
                    agent_types = [r.agent_type for r in runs]
                    for at in sorted(agent_types):
                        logger.info("    agent_type=%s", at)
                else:
                    logger.warning("No decision context was created — check prerequisites.")

                logger.info("=" * 60)
                logger.info("Done. No broker submit was performed.")

            return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
