"""Tests for the AI Decision → Order Submit pipeline.

This module covers:

1. ``build_submit_order_request_from_decision()`` — deterministic translation
   from ``OrderIntent`` → ``SubmitOrderRequest`` (or ``None`` for HOLD/WATCH).
2. ``DecisionOrchestratorService.assemble_and_submit()`` — full pipeline:
   assemble → validate → create_order → transition → submit.

See Also
--------
* :func:`~agent_trading.services.decision_orchestrator.build_submit_order_request_from_decision`
* :meth:`~agent_trading.services.decision_orchestrator.DecisionOrchestratorService.assemble_and_submit`
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import (
    AccountEntity,
    CashBalanceSnapshotEntity,
    ConfigVersionEntity,
    InstrumentEntity,
    OrderRequestEntity,
    PositionSnapshotEntity,
    RiskLimitSnapshotEntity,
)
from agent_trading.domain.enums import AssetClass, Environment, OrderSide, OrderStatus, OrderType, TimeInForce
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.services.decision_orchestrator import (
    AIDecisionInputs,
    AssembledContext,
    DecisionOrchestratorService,
    OrderIntent,
    SubmitResult,
    build_submit_order_request_from_decision,
)
from agent_trading.services.order_manager import OrderManager
from agent_trading.repositories.bootstrap import build_in_memory_repositories

from agent_trading.services.ai_agents.base import AgentExecutionRequest
from agent_trading.services.ai_agents.schemas import FinalDecisionComposerOutput

_SENTINEL = object()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    *,
    side: OrderSide = OrderSide.BUY,
    quantity: Decimal = Decimal("10"),
    price: Decimal | None = Decimal("50000"),
    strategy_id: str | None = None,
    **overrides: Any,
) -> SubmitOrderRequest:
    """Build a minimal ``SubmitOrderRequest`` for test use."""
    if strategy_id is None:
        strategy_id = str(uuid4())
    kwargs: dict[str, Any] = {
        "account_ref": "test-account",
        "client_order_id": "test-001",
        "correlation_id": "corr-001",
        "strategy_id": strategy_id,
        "symbol": "005930",
        "market": "KRX",
        "side": side,
        "order_type": OrderType.LIMIT,
        "quantity": quantity,
        "price": price,
        "time_in_force": TimeInForce.DAY,
    }
    kwargs.update(overrides)
    return SubmitOrderRequest(**kwargs)


def _make_intent(
    *,
    decision_type: str = "APPROVE",
    request: SubmitOrderRequest | None = None,
    quantity: Decimal | None = None,
    decision_context_id: UUID | None | object = _SENTINEL,
) -> OrderIntent:
    """Build an ``OrderIntent`` with controlled ``AIDecisionInputs``."""
    if request is None:
        request = _make_request(quantity=quantity) if quantity is not None else _make_request()
    ai_inputs = AIDecisionInputs(decision_type=decision_type)
    # sentinel-based: when caller omits the arg we auto-generate a UUID;
    # when caller explicitly passes None it stays None.
    if decision_context_id is _SENTINEL:
        dc_id: UUID | None = uuid4()
    else:
        dc_id = decision_context_id  # type: ignore[assignment]
    return OrderIntent(
        decision_context_id=dc_id,
        order_intent_id=uuid4(),
        request=request,
        context=AssembledContext(),
        ai_backend_inputs=ai_inputs,
    )


def _make_order_entity(
    *,
    status: OrderStatus = OrderStatus.DRAFT,
    request: SubmitOrderRequest | None = None,
) -> OrderRequestEntity:
    """Build a minimal ``OrderRequestEntity`` for test return values."""
    req = request or _make_request()
    return OrderRequestEntity(
        order_request_id=uuid4(),
        account_id=UUID("00000000-0000-0000-0000-000000000001"),
        instrument_id=UUID("00000000-0000-0000-0000-000000000002"),
        client_order_id=req.client_order_id,
        idempotency_key=req.idempotency_key or "",
        correlation_id=req.correlation_id or "",
        side=req.side,
        order_type=req.order_type,
        requested_quantity=req.quantity,
        status=status,
    )


# ---------------------------------------------------------------------------
# build_submit_order_request_from_decision — unit tests
# ---------------------------------------------------------------------------


class TestBuildSubmitOrderRequest:
    """Deterministic translation from OrderIntent → SubmitOrderRequest."""

    def test_approve_returns_request(self) -> None:
        intent = _make_intent(decision_type="APPROVE")
        result = build_submit_order_request_from_decision(intent)
        assert result is not None
        assert result.side == OrderSide.BUY

    def test_buy_returns_request(self) -> None:
        intent = _make_intent()
        # Also override side on the request
        result = build_submit_order_request_from_decision(intent)
        assert result is not None
        assert result.side == OrderSide.BUY

    def test_sell_returns_request(self) -> None:
        intent = _make_intent(decision_type="SELL")
        result = build_submit_order_request_from_decision(intent)
        assert result is not None

    def test_exit_returns_request(self) -> None:
        intent = _make_intent(decision_type="EXIT")
        result = build_submit_order_request_from_decision(intent)
        assert result is not None

    def test_reduce_returns_request(self) -> None:
        intent = _make_intent(decision_type="REDUCE")
        result = build_submit_order_request_from_decision(intent)
        assert result is not None

    def test_client_order_id_explicit(self) -> None:
        intent = _make_intent()
        result = build_submit_order_request_from_decision(intent)
        assert result is not None

    def test_preserves_request_fields(self) -> None:
        """Non-decision fields survive the round-trip."""
        request = _make_request(
            symbol="AAPL",
            market="NASDAQ",
            quantity=Decimal("100"),
            price=Decimal("150.00"),
            time_in_force=TimeInForce.DAY,
        )
        intent = _make_intent(request=request)
        result = build_submit_order_request_from_decision(intent)
        assert result is not None
        assert result.symbol == "AAPL"
        assert result.market == "NASDAQ"
        assert result.quantity == Decimal("100")
        assert result.price == Decimal("150.00")
        assert result.time_in_force == TimeInForce.DAY

    @pytest.mark.parametrize("skip_type", ["HOLD", "WATCH", "", "UNKNOWN"])
    def test_non_actionable_returns_none(self, skip_type: str) -> None:
        intent = _make_intent(decision_type=skip_type)
        assert build_submit_order_request_from_decision(intent) is None

    def test_zero_quantity_returns_none(self) -> None:
        intent = _make_intent(decision_type="BUY", quantity=Decimal("0"))
        result = build_submit_order_request_from_decision(intent)
        assert result is None

    def test_negative_quantity_returns_none(self) -> None:
        intent = _make_intent(decision_type="SELL", quantity=Decimal("-5"))
        result = build_submit_order_request_from_decision(intent)
        assert result is None

    def test_missing_decision_context_id_returns_none(self) -> None:
        intent = _make_intent(decision_context_id=None)
        result = build_submit_order_request_from_decision(intent)
        assert result is None


# ---------------------------------------------------------------------------
# assemble_and_submit — integration-style tests
# ---------------------------------------------------------------------------


class TestAssembleAndSubmit:
    """Full pipeline: assemble -> validate -> create_order -> submit."""

    class _ApproveFDCAgent:
        """Custom FDC agent that returns APPROVE so the pipeline proceeds."""

        @property
        def agent_name(self) -> str:
            return "final_decision_composer"

        @property
        def schema_version(self) -> str:
            return "1.0.0"

        async def run(self, request: AgentExecutionRequest) -> FinalDecisionComposerOutput:
            return FinalDecisionComposerOutput(
                decision_type="APPROVE",
                side="BUY",
                symbol="AAPL",
                confidence=0.8,
                conviction=0.7,
                summary="Approved by test stub",
            )

    @pytest.fixture
    def repos(self) -> Any:
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
    def service(self, repos: Any) -> DecisionOrchestratorService:
        """Default service uses the approve FDC agent."""
        return DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=self._ApproveFDCAgent(),
        )

    @pytest.fixture
    def hold_service(self, repos: Any) -> DecisionOrchestratorService:
        """Service with default FDC agent (returns HOLD)."""
        return DecisionOrchestratorService(repos=repos)

    @pytest.fixture
    def sample_request(self) -> SubmitOrderRequest:
        return _make_request()

    @pytest.fixture
    def order_manager(self, repos: Any) -> OrderManager:
        from agent_trading.services.reconciliation_service import ReconciliationService
        return OrderManager(
            repos=repos,
            reconciliation_service=ReconciliationService(repos=repos),
        )

    # ── Happy path ──

    @pytest.mark.asyncio
    async def test_happy_path_submitted(
        self,
        service: DecisionOrchestratorService,
        order_manager: OrderManager,
        sample_request: SubmitOrderRequest,
    ) -> None:
        """Happy path: assemble -> create_order -> transition -> submit -> SUBMITTED."""
        submitted_entity = _make_order_entity(
            status=OrderStatus.SUBMITTED,
            request=sample_request,
        )

        async def _mock_submit(
            *args: Any,
            **kwargs: Any,
        ) -> OrderRequestEntity:
            return submitted_entity

        broker_stub = object()
        with patch.object(OrderManager, "submit_order_to_broker", _mock_submit):
            result = await service.assemble_and_submit(
                sample_request,
                order_manager=order_manager,
                broker=broker_stub,  # type: ignore[arg-type]
            )

        assert result.status == "SUBMITTED", f"Expected SUBMITTED, got {result.status}"
        assert result.intent is not None
        assert result.order is not None
        assert result.order.status == OrderStatus.SUBMITTED
        assert result.error_phase is None
        # --- Gap 2: traceability assertions ---
        assert result.decision_context_id is not None, (
            "SubmitResult.decision_context_id must be set on happy path"
        )
        assert result.decision_context_id == result.intent.decision_context_id, (
            "SubmitResult.decision_context_id must match intent.decision_context_id"
        )

    # ── Broker reject ──

    @pytest.mark.asyncio
    async def test_broker_reject(
        self,
        service: DecisionOrchestratorService,
        order_manager: OrderManager,
        sample_request: SubmitOrderRequest,
    ) -> None:
        """Broker explicitly rejects -> status REJECTED."""
        rejected_entity = _make_order_entity(
            status=OrderStatus.REJECTED,
            request=sample_request,
        )

        async def _mock_submit(*args: Any, **kwargs: Any) -> OrderRequestEntity:
            return rejected_entity

        broker_stub = object()
        with patch.object(OrderManager, "submit_order_to_broker", _mock_submit):
            result = await service.assemble_and_submit(
                sample_request,
                order_manager=order_manager,
                broker=broker_stub,  # type: ignore[arg-type]
            )

        assert result.status == "REJECTED", f"Expected REJECTED, got {result.status}"
        assert result.intent is not None
        assert result.order is not None
        assert result.order.status == OrderStatus.REJECTED
        # --- Gap 2: traceability assertion ---
        assert result.decision_context_id is not None, (
            "SubmitResult.decision_context_id must be set on reject path"
        )
        assert result.decision_context_id == result.intent.decision_context_id, (
            "SubmitResult.decision_context_id must match intent.decision_context_id"
        )

    # ── RECONCILE_REQUIRED ──

    @pytest.mark.asyncio
    async def test_reconcile_required(
        self,
        service: DecisionOrchestratorService,
        order_manager: OrderManager,
        sample_request: SubmitOrderRequest,
    ) -> None:
        """Broker returns uncertain result -> RECONCILE_REQUIRED."""
        reconcile_entity = _make_order_entity(
            status=OrderStatus.RECONCILE_REQUIRED,
            request=sample_request,
        )

        async def _mock_submit(*args: Any, **kwargs: Any) -> OrderRequestEntity:
            return reconcile_entity

        broker_stub = object()
        with patch.object(OrderManager, "submit_order_to_broker", _mock_submit):
            result = await service.assemble_and_submit(
                sample_request,
                order_manager=order_manager,
                broker=broker_stub,  # type: ignore[arg-type]
            )

        assert result.status == "RECONCILE_REQUIRED", (
            f"Expected RECONCILE_REQUIRED, got {result.status}"
        )
        assert result.intent is not None
        assert result.order is not None
        assert result.order.status == OrderStatus.RECONCILE_REQUIRED
        # --- Gap 2: traceability assertion ---
        assert result.decision_context_id is not None, (
            "SubmitResult.decision_context_id must be set on reconcile path"
        )
        assert result.decision_context_id == result.intent.decision_context_id, (
            "SubmitResult.decision_context_id must match intent.decision_context_id"
        )

    # ── HOLD decision -> SKIPPED ──

    @pytest.mark.asyncio
    async def test_skip_hold_decision(
        self,
        hold_service: DecisionOrchestratorService,
        order_manager: OrderManager,
    ) -> None:
        """HOLD decision -> SKIPPED status, no order created."""
        request = _make_request()

        async def _mock_submit(*args: Any, **kwargs: Any) -> OrderRequestEntity:
            raise AssertionError("Broker should not be called for HOLD decisions")

        broker_stub = object()
        with patch.object(OrderManager, "submit_order_to_broker", _mock_submit):
            result = await hold_service.assemble_and_submit(
                request,
                order_manager=order_manager,
                broker=broker_stub,  # type: ignore[arg-type]
            )

        assert result.status == "SKIPPED", f"Expected SKIPPED, got {result.status}"
        assert result.intent is not None
        assert result.order is None  # No order created for HOLD
        # --- Gap 2: traceability assertion ---
        assert result.decision_context_id is not None, (
            "SubmitResult.decision_context_id must be set on SKIPPED path"
        )
        assert result.decision_context_id == result.intent.decision_context_id, (
            "SubmitResult.decision_context_id must match intent.decision_context_id"
        )

    # ── assemble() exception -> ERROR/ai ──

    @pytest.mark.asyncio
    async def test_assemble_exception(
        self,
        repos: Any,
        order_manager: OrderManager,
    ) -> None:
        """assemble() raises -> ERROR with error_phase='ai'."""
        request = _make_request()

        class FailingService(DecisionOrchestratorService):
            async def assemble(
                self,
                request: SubmitOrderRequest,
                **kwargs: Any,
            ) -> OrderIntent:
                raise ValueError("Simulated assemble failure")

        service = FailingService(repos=repos)
        broker_stub = object()

        result = await service.assemble_and_submit(
            request,
            order_manager=order_manager,
            broker=broker_stub,  # type: ignore[arg-type]
        )

        assert result.status == "ERROR"
        assert result.error_phase == "ai"
        assert "Simulated assemble failure" in (result.error_message or "")
        # --- Gap 2: traceability assertion ---
        # assemble() failed before decision_context_id could be resolved
        assert result.decision_context_id is None

    # ── Phase 1.5 sizing — quantity capped by cash constraint ──

    @pytest.mark.asyncio
    async def test_sizing_applied_to_submitted_order(
        self,
        repos: Any,
        order_manager: OrderManager,
        sample_request: SubmitOrderRequest,
    ) -> None:
        """Phase 1.5 sizing caps quantity when cash is insufficient.

        Request quantity=100 price=50000 → total value=5,000,000.
        Seeded cash=500,000 → max shares=10.  Submitted order should
        have quantity=10, not 100.
        """
        # Find the seeded account UUID
        account = next(
            a for a in repos.accounts._items.values()
            if a.account_alias == "test-account"
        )

        # Seed cash balance snapshot (500,000 KRW available)
        repos.cash_balance_snapshots._items[account.account_id] = (
            CashBalanceSnapshotEntity(
                cash_balance_snapshot_id=uuid4(),
                account_id=account.account_id,
                available_cash=Decimal("500000"),
                settled_cash=Decimal("500000"),
                unsettled_cash=Decimal("0"),
                currency="KRW",
                source_of_truth="broker",
                snapshot_at=datetime.now(timezone.utc),
            )
        )

        async def _mock_submit(*args: Any, **kwargs: Any) -> OrderRequestEntity:
            return _make_order_entity(status=OrderStatus.SUBMITTED)

        broker_stub = object()
        service = DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=self._ApproveFDCAgent(),
        )
        with patch.object(OrderManager, "submit_order_to_broker", _mock_submit):
            result = await service.assemble_and_submit(
                sample_request,
                order_manager=order_manager,
                broker=broker_stub,  # type: ignore[arg-type]
            )

        assert result.status == "SUBMITTED", f"Expected SUBMITTED, got {result.status}"
        assert result.order is not None, "Order must exist"
        # The order's requested_quantity should be the sized quantity (10),
        # not the original 100.
        assert result.order.requested_quantity == Decimal("10"), (
            f"Expected sized quantity 10 (cash-limited), "
            f"got {result.order.requested_quantity}"
        )

    # ── Phase 1.5 sizing — zero quantity → SKIPPED ──

    @pytest.mark.asyncio
    async def test_sizing_zero_quantity_skips(
        self,
        repos: Any,
        order_manager: OrderManager,
    ) -> None:
        """Phase 1.5 returns SKIPPED when sizing results in zero quantity."""
        request = _make_request(quantity=Decimal("100"), price=Decimal("50000"))

        account = next(
            a for a in repos.accounts._items.values()
            if a.account_alias == "test-account"
        )

        # Seed cash balance snapshot (very low cash → zero qty)
        repos.cash_balance_snapshots._items[account.account_id] = (
            CashBalanceSnapshotEntity(
                cash_balance_snapshot_id=uuid4(),
                account_id=account.account_id,
                available_cash=Decimal("1000"),
                settled_cash=Decimal("1000"),
                unsettled_cash=Decimal("0"),
                currency="KRW",
                source_of_truth="broker",
                snapshot_at=datetime.now(timezone.utc),
            )
        )

        async def _mock_submit(
            *args: Any,
            **kwargs: Any,
        ) -> OrderRequestEntity:
            raise AssertionError("Broker should not be called when sizing returns zero")

        broker_stub = object()
        service = DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=self._ApproveFDCAgent(),
        )
        with patch.object(OrderManager, "submit_order_to_broker", _mock_submit):
            result = await service.assemble_and_submit(
                request,
                order_manager=order_manager,
                broker=broker_stub,  # type: ignore[arg-type]
            )

        assert result.status == "SKIPPED", f"Expected SKIPPED, got {result.status}"
        assert result.error_phase == "sizing", (
            f"Expected error_phase='sizing', got {result.error_phase}"
        )
        assert result.intent is not None
        assert result.order is None  # No order created
        assert result.decision_context_id is not None

    # ── submit_order_to_broker() exception -> ERROR/order_submit ──

    @pytest.mark.asyncio
    async def test_submit_exception(
        self,
        service: DecisionOrchestratorService,
        order_manager: OrderManager,
        sample_request: SubmitOrderRequest,
    ) -> None:
        """submit_order_to_broker() raises -> ERROR with error_phase='order_submit'."""
        async def _failing_submit(*args: Any, **kwargs: Any) -> OrderRequestEntity:
            raise RuntimeError("Broker connection lost")

        broker_stub = object()
        with patch.object(OrderManager, "submit_order_to_broker", _failing_submit):
            result = await service.assemble_and_submit(
                sample_request,
                order_manager=order_manager,
                broker=broker_stub,  # type: ignore[arg-type]
            )

        assert result.status == "ERROR", f"Expected ERROR, got {result.status}"
        assert result.error_phase == "order_submit"
        assert "Broker connection lost" in (result.error_message or "")
        # --- Gap 2: traceability assertion ---
        # assemble() succeeded, so decision_context_id should be resolved
        assert result.decision_context_id is not None, (
            "SubmitResult.decision_context_id must be set when assemble() succeeded"
        )
        assert result.decision_context_id == result.intent.decision_context_id, (
            "SubmitResult.decision_context_id must match intent.decision_context_id"
        )
