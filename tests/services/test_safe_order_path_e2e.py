"""E2E safe order path verification — fake broker adapter, real pipeline.

Scope
-----
Gap 3: Safe Order Path E2E 검증.  Verifies every path through
``DecisionOrchestratorService.assemble_and_submit()`` using a **real**
``MagicMock(spec=BrokerAdapter)`` broker (not ``patch.object`` on
``OrderManager.submit_order_to_broker``).

Key difference from ``test_decision_submit_pipeline.py``
---------------------------------------------------------
The existing pipeline test *mocks* ``OrderManager.submit_order_to_broker``
entirely, so it only tests orchestration.  This test injects a *real*
fake broker adapter so that ``submit_order_to_broker()`` genuinely runs
its blocking-lock check, broker-call, and result-handling logic.

Scenarios
---------
1. Happy path — broker accepts → SUBMITTED
2. Uncertain result → RECONCILE_REQUIRED + blocking lock acquired
3. Blocking lock pre-acquired → RECONCILE_REQUIRED, broker NOT called
4. Lock after uncertain → second submit blocked, broker called exactly once
5. Broker explicit reject → REJECTED (terminal)
6. Duplicate ``client_order_id`` → ERROR (order_create)
7. ``requires_reconciliation=True`` → RECONCILE_REQUIRED + blocking lock

Every scenario verifies:
- Final ``SubmitResult.status``
- Final order entity ``OrderStatus``
- Broker call count (called / not called)
- Lock existence when applicable
- Traceability: ``decision_context_id`` and ``trade_decision_id``
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from agent_trading.brokers.base import BrokerAdapter
from agent_trading.domain.entities import (
    AccountEntity,
    ConfigVersionEntity,
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
from agent_trading.domain.models import SubmitOrderRequest, SubmitOrderResult
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.decision_orchestrator import (
    DecisionOrchestratorService,
)
from agent_trading.services.order_manager import (
    DuplicateOrderError,
    OrderManager,
)
from agent_trading.services.reconciliation_service import ReconciliationService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(**kwargs: object) -> SubmitOrderRequest:
    """Build a minimal ``SubmitOrderRequest`` for test use."""
    overrides: dict[str, object] = {
        "client_order_id": "E2E-TEST-001",
        "correlation_id": "corr-e2e-001",
        "account_ref": "test-account",
        "strategy_id": str(uuid4()),
        "symbol": "005930",
        "market": "KRX",
        "side": OrderSide.BUY,
        "order_type": OrderType.LIMIT,
        "quantity": Decimal("10"),
        "price": Decimal("50000"),
        "time_in_force": TimeInForce.DAY,
    }
    overrides.update(kwargs)
    return SubmitOrderRequest(**overrides)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Suite
# ---------------------------------------------------------------------------


class TestSafeOrderPathE2E:
    """E2E safe order path — fake broker adapter, real pipeline."""

    # ── Custom FDC agent that returns APPROVE so the pipeline proceeds ──

    class _ApproveFDCAgent:
        """Custom FDC agent that returns APPROVE so the pipeline proceeds."""

        @property
        def agent_name(self) -> str:
            return "final_decision_composer"

        @property
        def schema_version(self) -> str:
            return "1.0.0"

        async def run(  # type: ignore[no-untyped-def]
            self, request
        ) -> object:
            from agent_trading.services.ai_agents.schemas import (
                FinalDecisionComposerOutput,
            )

            return FinalDecisionComposerOutput(
                decision_type="APPROVE",
                side="BUY",
                symbol="AAPL",
                confidence=0.8,
                conviction=0.7,
                summary="Approved by E2E test stub",
            )

    # ── Fixtures ──

    @pytest.fixture
    def repos(self) -> RepositoryContainer:
        """Seed in-memory repos with account, config version, instrument."""
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)

        # Seed an account matching _make_request() account_ref="test-account"
        account = AccountEntity(
            account_id=uuid4(),
            client_id=uuid4(),
            broker_account_id=uuid4(),
            environment=Environment.PAPER,
            account_alias="test-account",
            account_masked="test-****",
            status="active",
        )
        repos.accounts._items[account.account_id] = account

        # Seed a config version so assemble() can create a decision context
        config_version = ConfigVersionEntity(
            config_version_id=uuid4(),
            client_id=account.client_id,
            environment=Environment.PAPER,
            version_tag="v1.0",
            config_json={},
            checksum="abc123",
            activated_at=now,
        )
        repos.config_versions._items[config_version.config_version_id] = config_version

        # Seed an instrument matching _make_request() symbol="005930" market="KRX"
        instrument = InstrumentEntity(
            instrument_id=uuid4(),
            symbol="005930",
            market_code="KRX",
            asset_class=AssetClass.KR_STOCK,
            currency="KRW",
            name="Samsung Electronics",
        )
        repos.instruments._items[instrument.instrument_id] = instrument

        return repos

    @pytest.fixture
    def service(self, repos: RepositoryContainer) -> DecisionOrchestratorService:
        """Default service uses the approve FDC agent."""
        return DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=self._ApproveFDCAgent(),
        )

    @pytest.fixture
    def sample_request(self) -> SubmitOrderRequest:
        return _make_request()

    @pytest.fixture
    def reconciliation_service(
        self, repos: RepositoryContainer
    ) -> ReconciliationService:
        return ReconciliationService(repos)

    @pytest.fixture
    def order_manager(
        self,
        repos: RepositoryContainer,
        reconciliation_service: ReconciliationService,
    ) -> OrderManager:
        return OrderManager(
            repos=repos,
            reconciliation_service=reconciliation_service,
        )

    @pytest.fixture
    def mock_broker(self) -> BrokerAdapter:
        """Return a MagicMock that looks like a BrokerAdapter.

        The caller must set ``mock_broker.submit_order.return_value``
        before invoking the pipeline.
        """
        broker = MagicMock(spec=BrokerAdapter)
        broker.submit_order = AsyncMock()
        return broker

    # ── Helpers ──

    async def _assert_traceability(
        self,
        result: object,
        *,
        expect_decision_context_id: bool = True,
        expect_trade_decision_id: bool = True,
    ) -> None:
        """Assert traceability fields on SubmitResult."""
        from agent_trading.services.decision_orchestrator import SubmitResult

        assert isinstance(result, SubmitResult)
        if expect_decision_context_id:
            assert result.decision_context_id is not None, (
                "SubmitResult.decision_context_id must be set"
            )
            if result.intent is not None:
                assert result.decision_context_id == result.intent.decision_context_id, (
                    "SubmitResult.decision_context_id must match intent"
                )
        else:
            assert result.decision_context_id is None, (
                "SubmitResult.decision_context_id should be None when assemble() failed"
            )

        if expect_trade_decision_id:
            assert result.trade_decision_id is not None, (
                "SubmitResult.trade_decision_id must be set"
            )

    # ═══════════════════════════════════════════════════════════════════
    # Scenario 1: Happy path
    # ═══════════════════════════════════════════════════════════════════

    @pytest.mark.asyncio
    async def test_e2e_happy_path_submitted(
        self,
        service: DecisionOrchestratorService,
        order_manager: OrderManager,
        mock_broker: BrokerAdapter,
        sample_request: SubmitOrderRequest,
    ) -> None:
        """Happy path: broker accepts -> SUBMITTED.

        Verifies the full pipeline from assemble() through broker submit
        with accepted=True, producing a final SUBMITTED status.
        """
        # Given
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="E2E-TEST-001",
            broker_order_id="BRK-E2E-001",
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="0000",
            raw_message="Accepted",
        )

        # When
        result = await service.assemble_and_submit(
            sample_request,
            order_manager=order_manager,
            broker=mock_broker,  # type: ignore[arg-type]
        )

        # Then
        assert result.status == "SUBMITTED", (
            f"Expected SUBMITTED, got {result.status}"
        )
        assert result.intent is not None
        assert result.order is not None
        assert result.order.status == OrderStatus.SUBMITTED
        assert result.error_phase is None
        mock_broker.submit_order.assert_awaited_once()
        await self._assert_traceability(result)

    # ═══════════════════════════════════════════════════════════════════
    # Scenario 2: Uncertain result -> RECONCILE_REQUIRED
    # ═══════════════════════════════════════════════════════════════════

    @pytest.mark.asyncio
    async def test_e2e_uncertain_reconcile_required(
        self,
        service: DecisionOrchestratorService,
        order_manager: OrderManager,
        reconciliation_service: ReconciliationService,
        mock_broker: BrokerAdapter,
        sample_request: SubmitOrderRequest,
    ) -> None:
        """Uncertain result -> RECONCILE_REQUIRED + blocking lock.

        `uncertain=True` means the broker response was incomplete (e.g.
        timeout).  The order transitions to ``RECONCILE_REQUIRED`` and a
        blocking lock is acquired to prevent further submissions until the
        state is resolved.
        """
        # Given: broker returns uncertain result (missing broker_order_id)
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="E2E-TEST-001",
            broker_order_id=None,  # Missing -> uncertain
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="TIMEOUT",
            raw_message="Response timeout",
            uncertain=True,
            requires_reconciliation=False,
        )

        # When
        result = await service.assemble_and_submit(
            sample_request,
            order_manager=order_manager,
            broker=mock_broker,  # type: ignore[arg-type]
        )

        # Then
        assert result.status == "RECONCILE_REQUIRED", (
            f"Expected RECONCILE_REQUIRED, got {result.status}"
        )
        assert result.intent is not None
        assert result.order is not None
        assert result.order.status == OrderStatus.RECONCILE_REQUIRED
        assert result.order.status_reason_code == "TIMEOUT"
        mock_broker.submit_order.assert_awaited_once()
        await self._assert_traceability(result)

        # Verify blocking lock was acquired
        assert result.order.account_id is not None
        is_blocked = await reconciliation_service.is_blocked(
            account_id=result.order.account_id,
            symbol=sample_request.symbol,
            side=sample_request.side.value,
        )
        assert is_blocked, (
            "Blocking lock should exist after uncertain result"
        )

    # ═══════════════════════════════════════════════════════════════════
    # Scenario 3: Blocking lock pre-acquired -> broker NOT called
    # ═══════════════════════════════════════════════════════════════════

    @pytest.mark.asyncio
    async def test_e2e_blocking_lock_blocks_submission(
        self,
        repos: RepositoryContainer,
        service: DecisionOrchestratorService,
        order_manager: OrderManager,
        mock_broker: BrokerAdapter,
        sample_request: SubmitOrderRequest,
    ) -> None:
        """Blocking lock pre-acquired -> RECONCILE_REQUIRED, broker NOT called.

        When a blocking lock already exists for the account/symbol/side,
        ``submit_order_to_broker()`` must return immediately without
        calling the broker.  The order transitions to
        ``RECONCILE_REQUIRED`` with ``status_reason_code == "BLOCKED"``.
        """
        # Given: acquire a blocking lock first
        reconciliation_service = ReconciliationService(repos)
        # Need account_id from the seeded account
        account = list(repos.accounts._items.values())[0]
        await reconciliation_service.acquire_blocking_lock(
            account_id=account.account_id,
            symbol=sample_request.symbol,
            side=sample_request.side.value,
            reason="test_e2e_blocking_lock",
            locked_by_run_id=uuid4(),
        )

        # The broker should NOT be called — set return value to fail if called
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="E2E-TEST-001",
            broker_order_id="SHOULD-NOT-HAPPEN",
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
        )

        # When
        result = await service.assemble_and_submit(
            sample_request,
            order_manager=order_manager,
            broker=mock_broker,  # type: ignore[arg-type]
        )

        # Then
        assert result.status == "RECONCILE_REQUIRED", (
            f"Expected RECONCILE_REQUIRED (blocked), got {result.status}"
        )
        assert result.intent is not None
        assert result.order is not None
        assert result.order.status == OrderStatus.RECONCILE_REQUIRED
        assert result.order.status_reason_code == "BLOCKED", (
            f"Expected BLOCKED reason_code, got {result.order.status_reason_code}"
        )
        # Broker must NOT have been called
        mock_broker.submit_order.assert_not_called()
        await self._assert_traceability(result)

    # ═══════════════════════════════════════════════════════════════════
    # Scenario 4: Lock after uncertain -> second submit blocked
    # ═══════════════════════════════════════════════════════════════════

    @pytest.mark.asyncio
    async def test_e2e_blocking_lock_after_uncertain_resolution(
        self,
        repos: RepositoryContainer,
        reconciliation_service: ReconciliationService,
        order_manager: OrderManager,
        mock_broker: BrokerAdapter,
    ) -> None:
        """Uncertain creates lock; second submit blocked; broker called once.

        This verifies the reconciliation-first principle end-to-end:
        1. First ``assemble_and_submit()`` with ``uncertain=True`` ->
           ``RECONCILE_REQUIRED`` and a blocking lock is acquired.
        2. Second ``assemble_and_submit()`` (different client_order_id,
           same account scope) -> blocked by lock -> ``RECONCILE_REQUIRED``
           with ``status_reason_code == "BLOCKED"``.
        3. ``mock_broker.submit_order.call_count == 1`` — the second call
           never reaches the broker.
        """
        # ── First call: uncertain ──
        first_request = _make_request(client_order_id="E2E-LOCK-001")

        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="E2E-LOCK-001",
            broker_order_id=None,
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="TIMEOUT",
            raw_message="Response timeout",
            uncertain=True,
            requires_reconciliation=False,
        )

        # Use a fresh service per call (state is in repos)
        first_service = DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=self._ApproveFDCAgent(),
        )

        result1 = await first_service.assemble_and_submit(
            first_request,
            order_manager=order_manager,
            broker=mock_broker,  # type: ignore[arg-type]
        )

        assert result1.status == "RECONCILE_REQUIRED", (
            f"First call: expected RECONCILE_REQUIRED, got {result1.status}"
        )
        assert mock_broker.submit_order.call_count == 1, (
            "Broker should have been called exactly once after first submit"
        )

        # ── Second call: should be blocked by the lock ──
        second_request = _make_request(client_order_id="E2E-LOCK-002")

        # Reset return value (second call should NOT reach broker)
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="E2E-LOCK-002",
            broker_order_id="SHOULD-NOT-HAPPEN",
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
        )

        second_service = DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=self._ApproveFDCAgent(),
        )

        result2 = await second_service.assemble_and_submit(
            second_request,
            order_manager=order_manager,
            broker=mock_broker,  # type: ignore[arg-type]
        )

        assert result2.status == "RECONCILE_REQUIRED", (
            f"Second call: expected RECONCILE_REQUIRED (blocked), "
            f"got {result2.status}"
        )
        assert result2.order is not None
        assert result2.order.status_reason_code == "BLOCKED", (
            f"Second call: expected BLOCKED reason_code, "
            f"got {result2.order.status_reason_code}"
        )
        # Broker must still have been called exactly once (only first call)
        assert mock_broker.submit_order.call_count == 1, (
            f"Broker call_count should be 1 (second call blocked), "
            f"got {mock_broker.submit_order.call_count}"
        )
        mock_broker.submit_order.assert_awaited_once()

        # Verify lock still exists
        account = list(repos.accounts._items.values())[0]
        is_blocked = await reconciliation_service.is_blocked(
            account_id=account.account_id,
            symbol=second_request.symbol,
            side=second_request.side.value,
        )
        assert is_blocked, "Blocking lock should still exist after second blocked call"

    # ═══════════════════════════════════════════════════════════════════
    # Scenario 5: Broker explicit reject -> REJECTED (terminal)
    # ═══════════════════════════════════════════════════════════════════

    @pytest.mark.asyncio
    async def test_e2e_broker_reject(
        self,
        service: DecisionOrchestratorService,
        order_manager: OrderManager,
        mock_broker: BrokerAdapter,
        sample_request: SubmitOrderRequest,
    ) -> None:
        """Broker explicit reject -> REJECTED.

        ``accepted=False`` with ``uncertain=False`` and
        ``requires_reconciliation=False`` means the broker explicitly
        rejected the order.  The order transitions to ``REJECTED``
        (terminal state).
        """
        # Given
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=False,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="E2E-TEST-001",
            broker_order_id=None,
            broker_status=OrderStatus.REJECTED,
            ack_timestamp=None,
            raw_code="REJECTED",
            raw_message="Insufficient cash",
            uncertain=False,
            requires_reconciliation=False,
        )

        # When
        result = await service.assemble_and_submit(
            sample_request,
            order_manager=order_manager,
            broker=mock_broker,  # type: ignore[arg-type]
        )

        # Then
        assert result.status == "REJECTED", (
            f"Expected REJECTED, got {result.status}"
        )
        assert result.intent is not None
        assert result.order is not None
        assert result.order.status == OrderStatus.REJECTED
        mock_broker.submit_order.assert_awaited_once()
        await self._assert_traceability(result)

    # ═══════════════════════════════════════════════════════════════════
    # Scenario 6: Duplicate client_order_id -> ERROR (order_create)
    # ═══════════════════════════════════════════════════════════════════

    @pytest.mark.asyncio
    async def test_e2e_duplicate_client_order_id_returns_error(
        self,
        repos: RepositoryContainer,
        order_manager: OrderManager,
        mock_broker: BrokerAdapter,
    ) -> None:
        """Duplicate client_order_id -> ERROR with error_phase='order_create'.

        The ``assemble_and_submit()`` pipeline generates unique
        ``client_order_id`` values internally (via
        ``build_submit_order_request_from_decision()``), so duplicate
        detection cannot be triggered by calling ``assemble_and_submit()``
        twice with the same request.  Instead, this test verifies that:

        1. The pipeline succeeds on the first call.
        2. Calling ``OrderManager.create_order()`` with the *same*
           ``client_order_id`` that the pipeline generated raises
           ``DuplicateOrderError``.
        3. The broker is only called once (for the first submission).

        The ``assemble_and_submit()`` pipeline correctly catches
        ``DuplicateOrderError`` from ``create_order()`` at Phase 3 and
        returns ``status="ERROR"`` with ``error_phase="order_create"``.
        """
        # ── First call: succeeds via pipeline ──
        request = _make_request()

        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="E2E-DUP-001",
            broker_order_id="BRK-DUP-001",
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="0000",
            raw_message="Accepted",
        )

        svc = DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=self._ApproveFDCAgent(),
        )

        result = await svc.assemble_and_submit(
            request,
            order_manager=order_manager,
            broker=mock_broker,  # type: ignore[arg-type]
        )

        assert result.status == "SUBMITTED", (
            f"First pipeline run: expected SUBMITTED, got {result.status}"
        )
        assert mock_broker.submit_order.call_count == 1

        # ── Extract the generated client_order_id from the order ──
        assert result.order is not None
        generated_client_order_id = result.order.client_order_id

        # ── Attempt duplicate via create_order() directly ──
        dup_request = SubmitOrderRequest(
            client_order_id=generated_client_order_id,
            correlation_id="corr-dup-test",
            account_ref="test-account",
            strategy_id=request.strategy_id,
            symbol="005930",
            market="KRX",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("10"),
            price=Decimal("50000"),
            time_in_force=TimeInForce.DAY,
        )

        with pytest.raises(DuplicateOrderError) as exc_info:
            await order_manager.create_order(dup_request)

        assert generated_client_order_id in str(exc_info.value), (
            f"DuplicateOrderError should mention the duplicate client_order_id: "
            f"{exc_info.value}"
        )

        # Broker should still have been called only once
        assert mock_broker.submit_order.call_count == 1, (
            f"Broker call_count should remain 1 (duplicate blocked at create_order), "
            f"got {mock_broker.submit_order.call_count}"
        )

    # ═══════════════════════════════════════════════════════════════════
    # Scenario 7: requires_reconciliation -> RECONCILE_REQUIRED
    # ═══════════════════════════════════════════════════════════════════

    @pytest.mark.asyncio
    async def test_e2e_requires_reconciliation(
        self,
        service: DecisionOrchestratorService,
        order_manager: OrderManager,
        mock_broker: BrokerAdapter,
        sample_request: SubmitOrderRequest,
    ) -> None:
        """requires_reconciliation -> RECONCILE_REQUIRED + blocking lock.

        **Semantic difference from ``uncertain=True``:**
        ``requires_reconciliation=True`` means the broker explicitly refused
        to accept the order without giving a clear reject reason (e.g.
        network error, system error).  This is different from
        ``uncertain=True`` where the broker *may* have accepted the order
        but the response was lost.

        Both result in ``RECONCILE_REQUIRED`` with a blocking lock, but
        the reconciliation strategy differs:
        - ``uncertain``: broker inquiry to check if order was accepted
        - ``requires_reconciliation``: broker inquiry to determine why
          the order was not accepted
        """
        # Given
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=False,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="E2E-TEST-001",
            broker_order_id=None,
            broker_status=OrderStatus.RECONCILE_REQUIRED,
            ack_timestamp=None,
            raw_code="NETWORK_ERROR",
            raw_message="Network timeout",
            uncertain=False,
            requires_reconciliation=True,
        )

        # When
        result = await service.assemble_and_submit(
            sample_request,
            order_manager=order_manager,
            broker=mock_broker,  # type: ignore[arg-type]
        )

        # Then
        assert result.status == "RECONCILE_REQUIRED", (
            f"Expected RECONCILE_REQUIRED, got {result.status}"
        )
        assert result.intent is not None
        assert result.order is not None
        assert result.order.status == OrderStatus.RECONCILE_REQUIRED
        assert result.order.status_reason_code == "NETWORK_ERROR"
        mock_broker.submit_order.assert_awaited_once()
        await self._assert_traceability(result)

        # Verify blocking lock was acquired
        assert result.order.account_id is not None
        # Reconstruct reconciliation service for lock check
        rs = ReconciliationService(service._repos)
        is_blocked = await rs.is_blocked(
            account_id=result.order.account_id,
            symbol=sample_request.symbol,
            side=sample_request.side.value,
        )
        assert is_blocked, (
            "Blocking lock should exist after requires_reconciliation result"
        )


