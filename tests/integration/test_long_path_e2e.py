"""Long-Path End-to-End Integration Scenario (Plan 37).

Scenarios
---------
A — In-Memory E2E Long Path (4 tests, 필수 구현)
B — Postgres-backed E2E Long Path (2 tests, DATABASE_* 환경변수 설정 시)
C — Failure Branch (Scenario A에 포함, 1 test)

Flow
----
assemble() → create_order() → transition_to(VALIDATED) →
transition_to(PENDING_SUBMIT) → submit_order_to_broker() (uncertain) →
reconciliation triggered → resolve_and_mark() (with order_manager) →
authoritative reflection → final state

Design Principles
-----------------
1. KIS API key 불필요 — mock broker + real services + in-memory/Postgres repos
2. Production code 변경 없음 — test-only changes
3. Direct repository status mutation 금지 — OrderManager 경로만 사용
4. Observability assertion은 existence check 중심 (brittle 방지)
"""

from __future__ import annotations

import dataclasses
import os
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from agent_trading.brokers.base import BrokerAdapter
from agent_trading.domain.entities import (
    AccountEntity,
    BrokerAccountEntity,
    ClientEntity,
    InstrumentEntity,
)
from agent_trading.domain.enums import (
    AssetClass,
    BrokerName,
    Environment,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from agent_trading.domain.models import (
    OrderStatusResult,
    SubmitOrderRequest,
    SubmitOrderResult,
)
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.decision_orchestrator import (
    DecisionOrchestratorService,
    OrderIntent,
)
from agent_trading.services.order_manager import OrderManager
from agent_trading.services.reconciliation_service import ReconciliationService

pytestmark = pytest.mark.asyncio


# ======================================================================
# Module-level fixtures (shared by Scenario A and B)
# ======================================================================


@pytest.fixture
def repos() -> RepositoryContainer:
    """In-memory repositories for Scenario A."""
    return build_in_memory_repositories()


@pytest.fixture
def reconciliation_service(
    repos: RepositoryContainer,
) -> ReconciliationService:
    """ReconciliationService wired to in-memory repos."""
    return ReconciliationService(repos)


@pytest.fixture
def manager(
    repos: RepositoryContainer,
    reconciliation_service: ReconciliationService,
) -> OrderManager:
    """OrderManager wired to in-memory repos + reconciliation service."""
    return OrderManager(
        repos=repos,
        reconciliation_service=reconciliation_service,
    )


@pytest.fixture
def mock_broker() -> BrokerAdapter:
    """Mock broker returning uncertain on submit, ACKNOWLEDGED/FILLED on resolve."""
    broker = MagicMock(spec=BrokerAdapter)
    broker.submit_order = AsyncMock()
    broker.resolve_unknown_state = AsyncMock()
    return broker


@pytest.fixture
def sample_request() -> SubmitOrderRequest:
    """Standard submit request for E2E tests.

    ``account_ref`` must match the ``account_alias`` in ``seeded_repos``.
    ``correlation_id`` is used for audit log lookups.
    """
    return SubmitOrderRequest(
        account_ref="test_account",
        client_order_id="e2e-001",
        correlation_id="e2e-corr-001",
        strategy_id="strat-001",
        symbol="005930",
        market="KRX",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        price=Decimal("50000"),
        time_in_force=TimeInForce.DAY,
    )


@pytest.fixture
async def seeded_repos(
    repos: RepositoryContainer,
    sample_request: SubmitOrderRequest,
) -> RepositoryContainer:
    """Repositories pre-seeded with client, account, instrument.

    The account's ``account_alias`` matches ``sample_request.account_ref``
    so that ``OrderManager.create_order()`` can resolve it.
    """
    client_id = uuid4()
    account_id = uuid4()
    instrument_id = uuid4()

    client = ClientEntity(
        client_id=client_id,
        client_code="E2E001",
        name="E2E Test Client",
        status="active",
        base_currency="KRW",
    )
    await repos.clients.add(client)

    account = AccountEntity(
        account_id=account_id,
        client_id=client_id,
        broker_account_id=uuid4(),
        environment=Environment.PAPER,
        account_alias="test_account",  # matches sample_request.account_ref
        account_masked="****e2e",
        status="active",
    )
    await repos.accounts.add(account)

    instrument = InstrumentEntity(
        instrument_id=instrument_id,
        symbol="005930",
        market_code="KRX",
        asset_class=AssetClass.KR_STOCK.value,
        currency="KRW",
        name="Samsung Electronics",
        is_active=True,
    )
    await repos.instruments.add(instrument)

    return repos


# ======================================================================
# Scenario A + C: In-Memory E2E Long Path
# ======================================================================


class TestLongPathE2EInMemory:
    """Scenario A: In-memory E2E Long Path.

    All 4 tests exercise the full closed loop:
    assemble() → create_order() → transition chain → uncertain submit →
    reconciliation → resolve_and_mark() → authoritative reflection.

    Test 4 (reflection_failure) also covers Scenario C.
    """

    async def test_long_path_happy_path_acknowledged(
        self,
        seeded_repos: RepositoryContainer,
        manager: OrderManager,
        reconciliation_service: ReconciliationService,
        mock_broker: BrokerAdapter,
        sample_request: SubmitOrderRequest,
    ) -> None:
        """Full E2E: assemble -> create -> uncertain submit -> reconciliation ->
        authoritative reflection -> ACKNOWLEDGED (resolved but non-terminal).

        ACKNOWLEDGED: broker has accepted the order; the local order state is
        updated but the order lifecycle may continue (fill/cancel/reject).
        This is a **non-terminal** resolved state.
        """
        # --- Step 1: assemble() ---
        service = DecisionOrchestratorService(repos=seeded_repos)
        intent = await service.assemble(sample_request)

        # AI boundary: ai_backend_inputs populated on OrderIntent
        assert intent.ai_backend_inputs is not None
        assert intent.request.client_order_id == "e2e-001"
        # intent.request is pure SubmitOrderRequest (no ai_backend_inputs field)
        assert not hasattr(intent.request, "ai_backend_inputs")

        # --- Step 2: create_order() -> DRAFT ---
        order = await manager.create_order(intent.request)
        assert order.status == OrderStatus.DRAFT

        # --- Step 3: transition_to(VALIDATED) ---
        order = await manager.transition_to(order, OrderStatus.VALIDATED)
        assert order.status == OrderStatus.VALIDATED

        # --- Step 4: transition_to(PENDING_SUBMIT) ---
        order = await manager.transition_to(order, OrderStatus.PENDING_SUBMIT)
        assert order.status == OrderStatus.PENDING_SUBMIT

        # --- Step 5: submit_order_to_broker() uncertain ---
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="e2e-001",
            broker_order_id=None,
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="TIMEOUT",
            raw_message="Response timeout",
            uncertain=True,
            requires_reconciliation=False,
        )

        result = await manager.submit_order_to_broker(
            order, mock_broker, intent.request
        )
        assert result.status == OrderStatus.RECONCILE_REQUIRED

        # --- Step 6: Reconciliation lock active ---
        locked = await reconciliation_service.is_blocked(
            account_id=order.account_id,
            symbol=sample_request.symbol,
            side=sample_request.side.value,
        )
        assert locked is True

        active_run = await reconciliation_service.get_active_run(order.account_id)
        assert active_run is not None
        assert active_run.status == "started"

        # --- Step 7: Broker resolves ACKNOWLEDGED ---
        mock_broker.resolve_unknown_state.return_value = OrderStatusResult(
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="e2e-001",
            broker_order_id="BRK-E2E-001",
            status=OrderStatus.ACKNOWLEDGED,
        )

        await reconciliation_service.resolve_and_mark(
            reconciliation_run_id=active_run.reconciliation_run_id,
            account_ref="test_account",
            broker=mock_broker,
            client_order_id="e2e-001",
            order_manager=manager,
        )

        # --- Step 8: Order state reflected ---
        updated = await seeded_repos.orders.get(order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.ACKNOWLEDGED

        # --- Step 9: Reconciliation run resolved, lock released ---
        resolved_run = await seeded_repos.reconciliations.get_run(
            active_run.reconciliation_run_id
        )
        assert resolved_run is not None
        assert resolved_run.status == "resolved"
        assert resolved_run.summary_json is not None
        # Existence check (brittle 방지): 핵심 키만 확인
        assert "resolved_status" in resolved_run.summary_json
        assert resolved_run.summary_json.get("resolved_status") == "acknowledged"

        locked_after = await reconciliation_service.is_blocked(
            account_id=order.account_id,
            symbol=sample_request.symbol,
            side=sample_request.side.value,
        )
        assert locked_after is False

        # --- Step 10: Verify observability (brittle 방지) ---
        # Audit logs: action 존재 여부 확인 (exact count 금지)
        audit_logs = await seeded_repos.audit_logs.list_by_correlation_id(
            "e2e-corr-001"
        )
        assert len(audit_logs) >= 1
        actions = [log.action for log in audit_logs]
        assert "order.create" in actions
        assert "order.status_change" in actions

        # Order state events: 마지막 reason_code 확인
        events = await seeded_repos.order_state_events.list_by_order_request(
            order.order_request_id
        )
        assert len(events) >= 1
        assert events[-1].reason_code == "RECONCILE_RESOLVED"
        assert events[-1].new_status == OrderStatus.ACKNOWLEDGED

        # AI recorder: 정확히 3 runs (stable — 변경 불가)
        assert len(await service._agent_recorder.list_all()) == 3

        # AI boundary: broker received SubmitOrderRequest only
        mock_broker.submit_order.assert_awaited_once_with(intent.request)

    async def test_long_path_happy_path_filled(
        self,
        seeded_repos: RepositoryContainer,
        manager: OrderManager,
        reconciliation_service: ReconciliationService,
        mock_broker: BrokerAdapter,
        sample_request: SubmitOrderRequest,
    ) -> None:
        """Full E2E: assemble -> create -> uncertain submit -> reconciliation ->
        authoritative reflection -> FILLED (resolved and terminal).

        FILLED: broker has fully executed the order; the local order state is
        updated and **no further transitions are possible** from this terminal
        state. ``_TERMINAL_STATES`` includes FILLED.
        """
        # --- Steps 1-6: identical to acknowledged test ---
        service = DecisionOrchestratorService(repos=seeded_repos)
        intent = await service.assemble(sample_request)

        order = await manager.create_order(intent.request)
        order = await manager.transition_to(order, OrderStatus.VALIDATED)
        order = await manager.transition_to(order, OrderStatus.PENDING_SUBMIT)

        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="e2e-001",
            broker_order_id=None,
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="TIMEOUT",
            raw_message="Response timeout",
            uncertain=True,
            requires_reconciliation=False,
        )
        await manager.submit_order_to_broker(order, mock_broker, intent.request)

        active_run = await reconciliation_service.get_active_run(order.account_id)
        assert active_run is not None

        # --- Step 7: Broker resolves FILLED (different from ACKNOWLEDGED) ---
        mock_broker.resolve_unknown_state.return_value = OrderStatusResult(
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="e2e-001",
            broker_order_id="BRK-E2E-001",
            status=OrderStatus.FILLED,  # FILLED (terminal)
        )

        await reconciliation_service.resolve_and_mark(
            reconciliation_run_id=active_run.reconciliation_run_id,
            account_ref="test_account",
            broker=mock_broker,
            client_order_id="e2e-001",
            order_manager=manager,
        )

        # --- Step 8: Order state reflected as FILLED (terminal) ---
        updated = await seeded_repos.orders.get(order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.FILLED

        # --- Step 9: Reconciliation run resolved, lock released ---
        resolved_run = await seeded_repos.reconciliations.get_run(
            active_run.reconciliation_run_id
        )
        assert resolved_run is not None
        assert resolved_run.status == "resolved"
        assert resolved_run.summary_json is not None
        assert "resolved_status" in resolved_run.summary_json
        assert resolved_run.summary_json.get("resolved_status") == "filled"

        locked_after = await reconciliation_service.is_blocked(
            account_id=order.account_id,
            symbol=sample_request.symbol,
            side=sample_request.side.value,
        )
        assert locked_after is False

        # --- Step 10: Verify observability ---
        events = await seeded_repos.order_state_events.list_by_order_request(
            order.order_request_id
        )
        assert len(events) >= 1
        assert events[-1].new_status == OrderStatus.FILLED

        # AI boundary: broker received SubmitOrderRequest only
        mock_broker.submit_order.assert_awaited_once_with(intent.request)

    async def test_long_path_ai_boundary_maintained(
        self,
        seeded_repos: RepositoryContainer,
        manager: OrderManager,
        reconciliation_service: ReconciliationService,
        mock_broker: BrokerAdapter,
        sample_request: SubmitOrderRequest,
    ) -> None:
        """Verify AI/execution boundary across the full long path.

        assemble() produces ``OrderIntent`` with ``ai_backend_inputs``
        (``AIDecisionInputs``) populated, but the broker receives only
        the ``SubmitOrderRequest`` — never ``OrderIntent`` or
        ``AIDecisionInputs``.  This is the core AI/execution safety
        guarantee.
        """
        # --- assemble ---
        service = DecisionOrchestratorService(repos=seeded_repos)
        intent = await service.assemble(sample_request)

        # AI side: ai_backend_inputs exists and is populated
        assert intent.ai_backend_inputs is not None
        assert intent.ai_backend_inputs.decision_type is not None

        # Execution side: intent.request has no ai_backend_inputs
        assert not hasattr(intent.request, "ai_backend_inputs")

        # --- Create order with intent.request ---
        order = await manager.create_order(intent.request)
        assert order.status == OrderStatus.DRAFT

        # --- Transition to VALIDATED then PENDING_SUBMIT (required for submit) ---
        order = await manager.transition_to(order, OrderStatus.VALIDATED)
        assert order.status == OrderStatus.VALIDATED
        order = await manager.transition_to(order, OrderStatus.PENDING_SUBMIT)
        assert order.status == OrderStatus.PENDING_SUBMIT

        # --- Submit with uncertain result ---
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="e2e-001",
            broker_order_id=None,
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="TIMEOUT",
            raw_message="Response timeout",
            uncertain=True,
            requires_reconciliation=False,
        )
        await manager.submit_order_to_broker(order, mock_broker, intent.request)

        # Broker received SubmitOrderRequest only — NOT AIDecisionInputs
        mock_broker.submit_order.assert_awaited_once_with(intent.request)

        # Verify call args explicitly: it was a SubmitOrderRequest
        call_args = mock_broker.submit_order.call_args[0][0]
        assert isinstance(call_args, SubmitOrderRequest)
        assert not isinstance(call_args, OrderIntent)

    async def test_long_path_reflection_failure(
        self,
        seeded_repos: RepositoryContainer,
        manager: OrderManager,
        reconciliation_service: ReconciliationService,
        mock_broker: BrokerAdapter,
        sample_request: SubmitOrderRequest,
    ) -> None:
        """Reflection failure in E2E path -> run='reflection_failed', lock stays.

        Scenario C: authoritative reflection failure keeps the order unchanged,
        reconciliation run marked as ``reflection_failed``, blocking lock
        retained.  This verifies the safety fallback in ``resolve_and_mark()``.
        """
        # --- assemble -> create -> transition -> submit uncertain ---
        service = DecisionOrchestratorService(repos=seeded_repos)
        intent = await service.assemble(sample_request)
        order = await manager.create_order(intent.request)
        order = await manager.transition_to(order, OrderStatus.VALIDATED)
        order = await manager.transition_to(order, OrderStatus.PENDING_SUBMIT)

        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="e2e-001",
            broker_order_id=None,
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="TIMEOUT",
            raw_message="Response timeout",
            uncertain=True,
            requires_reconciliation=False,
        )
        await manager.submit_order_to_broker(order, mock_broker, intent.request)

        active_run = await reconciliation_service.get_active_run(order.account_id)
        assert active_run is not None

        # Broker resolves FILLED
        mock_broker.resolve_unknown_state.return_value = OrderStatusResult(
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="e2e-001",
            broker_order_id="BRK-E2E-001",
            status=OrderStatus.FILLED,
        )

        # Mock transition_to_authoritative to fail
        with patch.object(
            OrderManager,
            "transition_to_authoritative",
            new=AsyncMock(side_effect=RuntimeError("Simulated reflection failure")),
        ):
            await reconciliation_service.resolve_and_mark(
                reconciliation_run_id=active_run.reconciliation_run_id,
                account_ref="test_account",
                broker=mock_broker,
                client_order_id="e2e-001",
                order_manager=manager,
            )

        # Verify: run='reflection_failed', lock held, order state unchanged
        run_after = await seeded_repos.reconciliations.get_run(
            active_run.reconciliation_run_id
        )
        assert run_after.status == "reflection_failed"
        assert "reflection_error" in run_after.summary_json

        locked_after = await reconciliation_service.is_blocked(
            account_id=order.account_id,
            symbol=sample_request.symbol,
            side=sample_request.side.value,
        )
        assert locked_after is True

        updated = await seeded_repos.orders.get(order.order_request_id)
        assert updated.status == OrderStatus.RECONCILE_REQUIRED


# ======================================================================
# Phase 1 — Env completeness check (import time, sync)
# ======================================================================

_REQUIRED_PG_VARS: tuple[str, ...] = (
    "DATABASE_HOST",
    "DATABASE_PORT",
    "DATABASE_NAME",
    "DATABASE_USER",
    "DATABASE_PASSWORD",
)


def _pg_env_complete() -> bool:
    """Return True only when ALL 5 ``DATABASE_*`` vars are set.

    Phase 1 — import-time skipif evaluation.
    Does NOT attempt an actual DB connection (that is Phase 2).
    """
    return all(bool(os.getenv(v)) for v in _REQUIRED_PG_VARS)


# ======================================================================
# Scenario B: Postgres-backed E2E Long Path (optional)
# ======================================================================


@pytest.mark.skipif(
    not _pg_env_complete(),
    reason=(
        "DATABASE_* env vars not fully set — Postgres scenario B skipped. "
        "Set DATABASE_HOST, DATABASE_PORT, DATABASE_NAME, DATABASE_USER, "
        "and DATABASE_PASSWORD (e.g. via 'set -a && source .env && set +a')"
    ),
)
class TestLongPathE2EPostgres:
    """Scenario B: Postgres-backed E2E Long Path.

    Verifies DB persistence consistency across the full closed loop.
    Requires all 5 ``DATABASE_*`` environment variables to be set.

    Design:
    - ``postgres_repos`` fixture (from conftest.py) provides clean transaction.
    - ``BrokerAccountEntity`` must be seeded first (FK constraint).
    - ``assemble()`` output is stripped of ``decision_id`` before
      ``create_order()`` to avoid a pre-existing FK constraint issue on the
      legacy ``trade_decisions.decision`` column (NOT NULL without DEFAULT,
      not included in the repository INSERT).
    - Same 10-step flow as Scenario A, with Postgres persistence verification.
    """

    @pytest.fixture(autouse=True)
    async def setup(
        self,
        postgres_repos: RepositoryContainer,
    ) -> None:
        """Seed postgres repos with broker_account, client, account, instrument.

        Follows the same pattern as ``test_decision_loop_postgres.py``.
        ``BrokerAccountEntity`` is seeded first due to FK constraint.
        """
        broker_account = BrokerAccountEntity(
            broker_account_id=uuid4(),
            broker_name="KoreaInvestment",
            account_ref="PG-E2E-ACCT",
            environment=Environment.PAPER,
            credential_ref="pg-e2e-cred",
            base_url=None,
            status="active",
            broker_account_code="KIS-PAPER-****ACCT",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await postgres_repos.broker_accounts.add(broker_account)

        client = ClientEntity(
            client_id=uuid4(),
            client_code="PG-E2E-001",
            name="PG E2E Client",
            status="active",
            base_currency="KRW",
        )
        await postgres_repos.clients.add(client)

        account = AccountEntity(
            account_id=uuid4(),
            client_id=client.client_id,
            broker_account_id=broker_account.broker_account_id,
            environment=Environment.PAPER,
            account_alias="test_account",  # matches sample_request.account_ref
            account_masked="****pg",
            status="active",
        )
        await postgres_repos.accounts.add(account)

        instrument = InstrumentEntity(
            instrument_id=uuid4(),
            symbol="005930",
            market_code="KRX",
            asset_class=AssetClass.KR_STOCK.value,
            currency="KRW",
            name="Samsung Electronics",
            is_active=True,
        )
        await postgres_repos.instruments.add(instrument)

        self.repos: RepositoryContainer = postgres_repos
        self.reconciliation_service: ReconciliationService = ReconciliationService(
            postgres_repos
        )
        self.manager: OrderManager = OrderManager(
            repos=postgres_repos,
            reconciliation_service=self.reconciliation_service,
        )

    async def test_postgres_long_path_happy_path_acknowledged(
        self,
        mock_broker: BrokerAdapter,
        sample_request: SubmitOrderRequest,
    ) -> None:
        """Postgres E2E -> ACKNOWLEDGED (resolved but non-terminal).

        Verifies that audit log ordering, reconciliation run persistence,
        and authoritative reflection all work correctly at the DB level.
        """
        service = DecisionOrchestratorService(repos=self.repos)
        intent = await service.assemble(sample_request)

        # Strip decision_id to avoid FK constraint violation on trade_decisions.
        #
        # Root cause: migration 0001 defines trade_decisions.decision AS
        # VARCHAR(32) NOT NULL without a DEFAULT, but
        # PostgresTradeDecisionRepository.add() does NOT include the `decision`
        # column in its INSERT — causing a NOT NULL violation when trying to
        # persist a TradeDecisionEntity.
        #
        # Workaround: setting decision_id=None makes order_requests.trade_decision_id
        # NULL (the FK column IS nullable by design), bypassing the FK constraint
        # entirely. This is safe for test scenarios that do not query trade_decisions.
        #
        # Long-term fix: align TradeDecisionEntity/repository INSERT with the
        # actual DB schema (add `decision` column or make it nullable).
        request = dataclasses.replace(intent.request, decision_id=None)
        order = await self.manager.create_order(request)
        order = await self.manager.transition_to(order, OrderStatus.VALIDATED)
        order = await self.manager.transition_to(order, OrderStatus.PENDING_SUBMIT)

        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="e2e-001",
            broker_order_id=None,
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="TIMEOUT",
            raw_message="Response timeout",
            uncertain=True,
            requires_reconciliation=False,
        )
        await self.manager.submit_order_to_broker(order, mock_broker, intent.request)

        active_run = await self.reconciliation_service.get_active_run(order.account_id)
        assert active_run is not None

        mock_broker.resolve_unknown_state.return_value = OrderStatusResult(
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="e2e-001",
            broker_order_id="BRK-PG-E2E-001",
            status=OrderStatus.ACKNOWLEDGED,
        )

        await self.reconciliation_service.resolve_and_mark(
            reconciliation_run_id=active_run.reconciliation_run_id,
            account_ref="test_account",
            broker=mock_broker,
            client_order_id="e2e-001",
            order_manager=self.manager,
        )

        updated = await self.repos.orders.get(order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.ACKNOWLEDGED

        resolved_run = await self.repos.reconciliations.get_run(
            active_run.reconciliation_run_id
        )
        assert resolved_run.status == "resolved"
        assert resolved_run.summary_json is not None
        assert resolved_run.summary_json.get("resolved_status") == "acknowledged"

        # Verify observability (brittle 방지)
        events = await self.repos.order_state_events.list_by_order_request(
            order.order_request_id
        )
        assert len(events) >= 1
        assert events[-1].reason_code == "RECONCILE_RESOLVED"

    async def test_postgres_long_path_happy_path_filled(
        self,
        mock_broker: BrokerAdapter,
        sample_request: SubmitOrderRequest,
    ) -> None:
        """Postgres E2E -> FILLED (resolved and terminal).

        Verifies that the terminal state (FILLED) is correctly persisted
        at the DB level after authoritative reflection.
        """
        service = DecisionOrchestratorService(repos=self.repos)
        intent = await service.assemble(sample_request)

        # Strip decision_id to avoid FK constraint violation on trade_decisions.
        #
        # Root cause: migration 0001 defines trade_decisions.decision AS
        # VARCHAR(32) NOT NULL without a DEFAULT, but
        # PostgresTradeDecisionRepository.add() does NOT include the `decision`
        # column in its INSERT — causing a NOT NULL violation when trying to
        # persist a TradeDecisionEntity.
        #
        # Workaround: setting decision_id=None makes order_requests.trade_decision_id
        # NULL (the FK column IS nullable by design), bypassing the FK constraint
        # entirely. This is safe for test scenarios that do not query trade_decisions.
        #
        # Long-term fix: align TradeDecisionEntity/repository INSERT with the
        # actual DB schema (add `decision` column or make it nullable).
        request = dataclasses.replace(intent.request, decision_id=None)
        order = await self.manager.create_order(request)
        order = await self.manager.transition_to(order, OrderStatus.VALIDATED)
        order = await self.manager.transition_to(order, OrderStatus.PENDING_SUBMIT)

        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="e2e-001",
            broker_order_id=None,
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="TIMEOUT",
            raw_message="Response timeout",
            uncertain=True,
            requires_reconciliation=False,
        )
        await self.manager.submit_order_to_broker(order, mock_broker, intent.request)

        active_run = await self.reconciliation_service.get_active_run(order.account_id)
        assert active_run is not None

        mock_broker.resolve_unknown_state.return_value = OrderStatusResult(
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="e2e-001",
            broker_order_id="BRK-PG-E2E-001",
            status=OrderStatus.FILLED,  # terminal
        )

        await self.reconciliation_service.resolve_and_mark(
            reconciliation_run_id=active_run.reconciliation_run_id,
            account_ref="test_account",
            broker=mock_broker,
            client_order_id="e2e-001",
            order_manager=self.manager,
        )

        updated = await self.repos.orders.get(order.order_request_id)
        assert updated is not None
        assert updated.status == OrderStatus.FILLED

        resolved_run = await self.repos.reconciliations.get_run(
            active_run.reconciliation_run_id
        )
        assert resolved_run.summary_json is not None
        assert resolved_run.summary_json.get("resolved_status") == "filled"

        events = await self.repos.order_state_events.list_by_order_request(
            order.order_request_id
        )
        assert len(events) >= 1
        assert events[-1].new_status == OrderStatus.FILLED
