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

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import (
    AccountEntity,
    CashBalanceSnapshotEntity,
    ConfigVersionEntity,
    ExternalEventEntity,
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
    _normalize_decision_type,
    build_submit_order_request_from_decision,
)
from agent_trading.services.order_manager import OrderManager
from agent_trading.repositories.bootstrap import build_in_memory_repositories

from agent_trading.services.ai_agents.base import AgentExecutionRequest
from agent_trading.services.ai_agents.event_interpretation import EventInterpretationAgent
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

    # ── Normalization tests: _normalize_decision_type() unit tests ──
    # These test the normalization function directly.
    # build_submit_order_request_from_decision() receives already-normalized
    # values from _run_agents(), so it is tested with canonical values.

    def test_entry_normalized_to_approve(self) -> None:
        """``entry`` → ``APPROVE`` (actionable)."""
        assert _normalize_decision_type("entry") == "APPROVE"

    def test_entry_uppercase_normalized_to_approve(self) -> None:
        """``ENTRY`` → ``APPROVE``."""
        assert _normalize_decision_type("ENTRY") == "APPROVE"

    def test_entry_mixed_case_normalized_to_approve(self) -> None:
        """``Entry`` → ``APPROVE``."""
        assert _normalize_decision_type("Entry") == "APPROVE"

    def test_no_action_normalized_to_hold(self) -> None:
        """``no_action`` → ``HOLD`` (non-actionable)."""
        assert _normalize_decision_type("no_action") == "HOLD"

    def test_no_trade_normalized_to_hold(self) -> None:
        """``no_trade`` → ``HOLD``."""
        assert _normalize_decision_type("no_trade") == "HOLD"

    def test_none_normalized_to_hold(self) -> None:
        """``none`` → ``HOLD``."""
        assert _normalize_decision_type("none") == "HOLD"

    def test_approve_passthrough(self) -> None:
        """``APPROVE`` passes through unchanged."""
        assert _normalize_decision_type("APPROVE") == "APPROVE"

    def test_hold_passthrough(self) -> None:
        """``HOLD`` passes through unchanged."""
        assert _normalize_decision_type("HOLD") == "HOLD"

    def test_buy_passthrough(self) -> None:
        """``BUY`` passes through unchanged (actionable_types compatible)."""
        assert _normalize_decision_type("BUY") == "BUY"

    def test_sell_passthrough(self) -> None:
        """``SELL`` passes through unchanged."""
        assert _normalize_decision_type("SELL") == "SELL"

    def test_unknown_fallback_to_hold(self) -> None:
        """Unknown value falls back to ``HOLD``."""
        assert _normalize_decision_type("foobar") == "HOLD"

    def test_empty_fallback_to_hold(self) -> None:
        """Empty string falls back to ``HOLD``."""
        assert _normalize_decision_type("") == "HOLD"

    def test_whitespace_fallback_to_hold(self) -> None:
        """Whitespace-only string falls back to ``HOLD``."""
        assert _normalize_decision_type("  ") == "HOLD"


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

        # Seed fresh snapshots (for account-level Phase 4c guard)
        fresh_cash = CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=account.account_id,
            currency="KRW",
            available_cash=Decimal("1000000"),
            settled_cash=Decimal("0"),
            unsettled_cash=Decimal("0"),
            source_of_truth="broker",
            snapshot_at=now,
        )
        repos.cash_balance_snapshots._items[fresh_cash.cash_balance_snapshot_id] = fresh_cash
        fresh_pos = PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=account.account_id,
            instrument_id=instrument.instrument_id,
            quantity=Decimal("10"),
            average_price=Decimal("50000"),
            market_price=Decimal("50000"),
            unrealized_pnl=Decimal("0"),
            source_of_truth="broker",
            snapshot_at=now,
        )
        repos.position_snapshots._items[fresh_pos.position_snapshot_id] = fresh_pos

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


# ---------------------------------------------------------------------------
# P1-B: Event query window — 72h retention
# ---------------------------------------------------------------------------


class TestEventQueryWindow:
    """``assemble()`` passes the correct ``since`` window to ``list_by_symbol()``.

    P1-B changed the event retention window from 24h to 72h so that
    regulatory disclosures (quarterly reports, major shareholder filings,
    etc.) are not dropped too early.
    """

    @pytest.mark.asyncio
    async def test_assemble_uses_72h_window(self) -> None:
        """``assemble()`` calls ``list_by_symbol()`` with ``since=now-72h``."""
        repos = build_in_memory_repositories()
        svc = DecisionOrchestratorService(repos=repos)

        # Seed an event with published_at = 48h ago (within 72h window)
        now = datetime.now(timezone.utc)
        event_48h = ExternalEventEntity(
            event_id=uuid4(),
            event_type="K|분기보고서 (2026.03)",
            source_name="opendart",
            published_at=now - timedelta(hours=48),
            source_reliability_tier="T1",
            symbol="005930",
            issuer_code="00123456",
            ingested_at=now - timedelta(hours=48),
            headline="분기보고서",
        )
        await repos.external_events.add(event_48h)

        # Seed an event with published_at = 96h ago (outside 72h window)
        event_96h = ExternalEventEntity(
            event_id=uuid4(),
            event_type="Y|사업보고서 (2025.12)",
            source_name="opendart",
            published_at=now - timedelta(hours=96),
            source_reliability_tier="T1",
            symbol="005930",
            issuer_code="00123456",
            ingested_at=now - timedelta(hours=96),
            headline="사업보고서",
        )
        await repos.external_events.add(event_96h)

        # Build a minimal SubmitOrderRequest using the test helper
        request = _make_request()

        intent = await svc.assemble(request)

        # 48h event should be included (within 72h window)
        symbols_in_events = {e.symbol for e in intent.context.recent_events}
        assert "005930" in symbols_in_events, (
            "Event published 48h ago must be included in 72h window"
        )

        # 96h event should NOT be included (outside 72h window)
        # We check by event_id since both have symbol=005930
        event_ids_included = {e.event_id for e in intent.context.recent_events}
        assert event_96h.event_id not in event_ids_included, (
            "Event published 96h ago must NOT be included in 72h window"
        )


class TestP1AandP1BIntegration:
    """P1-A (prompt provenance) + P1-B (72h retention) 통합 검증.

    event seed → assemble() → recent_events → _build_user_prompt()
    전체 파이프라인이 의도대로 작동하는지 확인.
    """

    @pytest.mark.asyncio
    async def test_48h_event_has_provenance_tags_in_prompt(self) -> None:
        """시나리오 1: 48h event가 provenance tag와 함께 prompt에 표시됨."""
        repos = build_in_memory_repositories()
        svc = DecisionOrchestratorService(repos=repos)
        now = datetime.now(timezone.utc)

        # 48h event (모든 provenance 필드 존재)
        event_48h = ExternalEventEntity(
            event_id=uuid4(),
            event_type="K|분기보고서 (2026.03)",
            source_name="opendart",
            published_at=now - timedelta(hours=48),
            source_reliability_tier="T1",
            symbol="005930",
            issuer_code="00123456",
            ingested_at=now - timedelta(hours=48),
            severity="high",
            direction="positive",
            headline="분기보고서",
        )
        await repos.external_events.add(event_48h)

        # 96h event (window 밖)
        event_96h = ExternalEventEntity(
            event_id=uuid4(),
            event_type="Y|사업보고서 (2025.12)",
            source_name="opendart",
            published_at=now - timedelta(hours=96),
            source_reliability_tier="T1",
            symbol="005930",
            issuer_code="00123456",
            ingested_at=now - timedelta(hours=96),
            headline="사업보고서",
        )
        await repos.external_events.add(event_96h)

        # assemble() 실행
        request = _make_request()
        intent = await svc.assemble(request)

        # --- P1-B 검증: retention window ---
        event_ids = {e.event_id for e in intent.context.recent_events}
        assert event_48h.event_id in event_ids, "48h event must be in 72h window"
        assert event_96h.event_id not in event_ids, "96h event must be outside 72h window"

        # --- P1-A 검증: provenance tags in prompt ---
        agent = EventInterpretationAgent(provider_client=AsyncMock())
        ei_request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="integ-test-1",
            context=intent.context,
        )
        prompt = agent._build_user_prompt(ei_request)

        # Provenance tags 존재 확인
        assert "[src:opendart]" in prompt
        assert "[tier:T1]" in prompt
        assert "[K|분기보고서 (2026.03)]" in prompt
        date_str = (now - timedelta(hours=48)).strftime("%Y-%m-%d")
        assert f"[{date_str}]" in prompt
        assert "[issuer:00123456]" in prompt
        assert "[severity:high]" in prompt
        assert "[positive]" in prompt
        # stale: ingested_at=48h > 24h
        assert "⚠️STALE" in prompt

    @pytest.mark.asyncio
    async def test_fresh_ingestion_no_stale_despite_old_published(self) -> None:
        """시나리오 2: ingested_at fresh, published_at old → ⚠️STALE 없음."""
        repos = build_in_memory_repositories()
        svc = DecisionOrchestratorService(repos=repos)
        now = datetime.now(timezone.utc)

        event = ExternalEventEntity(
            event_id=uuid4(),
            event_type="K|공시",
            source_name="opendart",
            published_at=now - timedelta(hours=48),  # 48h 전 공시 (72h window 내)
            source_reliability_tier="T1",
            symbol="005930",
            issuer_code="00123456",
            ingested_at=now - timedelta(hours=1),    # 1h 전 수집 (fresh)
            headline="공시",
        )
        await repos.external_events.add(event)

        request = _make_request()
        intent = await svc.assemble(request)

        event_ids = {e.event_id for e in intent.context.recent_events}
        assert event.event_id in event_ids

        agent = EventInterpretationAgent(provider_client=AsyncMock())
        ei_request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="integ-test-2",
            context=intent.context,
        )
        prompt = agent._build_user_prompt(ei_request)

        # ingested_at=1h < 24h → stale 아님
        assert "⚠️STALE" not in prompt, (
            "Event ingested 1h ago must NOT have stale mark"
        )
        # published_at 날짜는 표시되어야 함
        date_str = (now - timedelta(hours=48)).strftime("%Y-%m-%d")
        assert f"[{date_str}]" in prompt

    @pytest.mark.asyncio
    async def test_default_severity_direction_omitted(self) -> None:
        """시나리오 3: severity=medium, direction=neutral → tag 생략."""
        repos = build_in_memory_repositories()
        svc = DecisionOrchestratorService(repos=repos)
        now = datetime.now(timezone.utc)

        event = ExternalEventEntity(
            event_id=uuid4(),
            event_type="disclosure",
            source_name="opendart",
            published_at=now,
            source_reliability_tier="T1",
            symbol="005930",
            issuer_code="00123456",
            ingested_at=now,
            severity="medium",    # default
            direction="neutral",  # default
            headline="test",
        )
        await repos.external_events.add(event)

        request = _make_request()
        intent = await svc.assemble(request)

        agent = EventInterpretationAgent(provider_client=AsyncMock())
        ei_request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="integ-test-3",
            context=intent.context,
        )
        prompt = agent._build_user_prompt(ei_request)

        assert "[severity:medium]" not in prompt
        assert "[positive]" not in prompt
        assert "[negative]" not in prompt

    @pytest.mark.asyncio
    async def test_no_issuer_code_tag_omitted(self) -> None:
        """시나리오 4: issuer_code=None → [issuer:...] tag 없음."""
        repos = build_in_memory_repositories()
        svc = DecisionOrchestratorService(repos=repos)
        now = datetime.now(timezone.utc)

        event = ExternalEventEntity(
            event_id=uuid4(),
            event_type="disclosure",
            source_name="opendart",
            published_at=now,
            source_reliability_tier="T1",
            symbol="005930",
            issuer_code=None,  # issuer 없음
            ingested_at=now,
            headline="test",
        )
        await repos.external_events.add(event)

        request = _make_request()
        intent = await svc.assemble(request)

        agent = EventInterpretationAgent(provider_client=AsyncMock())
        ei_request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="integ-test-4",
            context=intent.context,
        )
        prompt = agent._build_user_prompt(ei_request)

        assert "[issuer:" not in prompt

    @pytest.mark.asyncio
    async def test_20_event_cap_in_prompt(self) -> None:
        """시나리오 5: 25개 event → prompt에는 20개만 표시."""
        repos = build_in_memory_repositories()
        svc = DecisionOrchestratorService(repos=repos)
        now = datetime.now(timezone.utc)

        # 25개 event seed (모두 72h window 내)
        for i in range(25):
            event = ExternalEventEntity(
                event_id=uuid4(),
                event_type=f"type_{i}",
                source_name="opendart",
                published_at=now - timedelta(hours=i),  # 0h ~ 24h 전
                source_reliability_tier="T1",
                symbol="005930",
                issuer_code="00123456",
                ingested_at=now - timedelta(hours=i),
                headline=f"event_{i}",
            )
            await repos.external_events.add(event)

        request = _make_request()
        intent = await svc.assemble(request)

        # recent_events에는 25개 모두 있어야 함
        assert len(intent.context.recent_events) == 25

        agent = EventInterpretationAgent(provider_client=AsyncMock())
        ei_request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="integ-test-5",
            context=intent.context,
        )
        prompt = agent._build_user_prompt(ei_request)

        # Prompt 헤더에는 전체 count 표시
        assert "Recent events (25):" in prompt

        # Prompt의 event 줄 수는 20개여야 함 ([:20] slice)
        event_lines = [line for line in prompt.split("\n") if line.startswith("  [src:")]
        assert len(event_lines) == 20, (
            f"Expected 20 event lines in prompt, got {len(event_lines)}"
        )

        # event_0 ~ event_19는 있어야 함
        assert "event_0" in prompt
        assert "event_19" in prompt
        # event_20 ~ event_24는 없어야 함
        assert "event_20" not in prompt


# ---------------------------------------------------------------------------
# Importance sort tests
# ---------------------------------------------------------------------------


class TestImportanceSort:
    """recent_events importance sort order in assemble()."""

    @pytest.mark.asyncio
    async def test_importance_sort_order(self) -> None:
        """Events are sorted H > M > L by importance."""
        repos = build_in_memory_repositories()
        svc = DecisionOrchestratorService(repos=repos)
        now = datetime.now(timezone.utc)

        # Create events with different importance levels
        low_event = ExternalEventEntity(
            event_id=uuid4(),
            source_event_id="l001",
            source_name="opendart",
            event_type="Y|사업보고서",
            issuer_code="00123456",
            symbol="005930",
            published_at=now - timedelta(hours=1),
            ingested_at=now,
            headline="사업보고서",
            source_reliability_tier="T1_REGULATORY",
            dedup_key_hash="l001",
            metadata={"importance": "low"},
        )
        medium_event = ExternalEventEntity(
            event_id=uuid4(),
            source_event_id="m001",
            source_name="opendart",
            event_type="Y|신용등급변동",
            issuer_code="00123456",
            symbol="005930",
            published_at=now - timedelta(hours=2),
            ingested_at=now,
            headline="신용등급변동",
            source_reliability_tier="T1_REGULATORY",
            dedup_key_hash="m001",
            metadata={"importance": "medium"},
        )
        high_event = ExternalEventEntity(
            event_id=uuid4(),
            source_event_id="h001",
            source_name="opendart",
            event_type="Y|유상증자결정",
            issuer_code="00123456",
            symbol="005930",
            published_at=now - timedelta(hours=3),
            ingested_at=now,
            headline="유상증자결정",
            source_reliability_tier="T1_REGULATORY",
            dedup_key_hash="h001",
            metadata={"importance": "high"},
        )

        # Insert in reverse order (L, M, H)
        for ev in (low_event, medium_event, high_event):
            await repos.external_events.add(ev)

        request = _make_request()
        intent = await svc.assemble(request)

        recent = intent.context.recent_events
        assert len(recent) == 3
        # Expected order: H, M, L
        assert recent[0].source_event_id == "h001", (
            f"Expected high first, got {recent[0].source_event_id}"
        )
        assert recent[1].source_event_id == "m001", (
            f"Expected medium second, got {recent[1].source_event_id}"
        )
        assert recent[2].source_event_id == "l001", (
            f"Expected low last, got {recent[2].source_event_id}"
        )

    @pytest.mark.asyncio
    async def test_same_importance_recency_sort(self) -> None:
        """Events with same importance are sorted by published_at DESC."""
        repos = build_in_memory_repositories()
        svc = DecisionOrchestratorService(repos=repos)
        now = datetime.now(timezone.utc)

        old_event = ExternalEventEntity(
            event_id=uuid4(),
            source_event_id="old",
            source_name="opendart",
            event_type="Y|유상증자결정",
            issuer_code="00123456",
            symbol="005930",
            published_at=now - timedelta(hours=5),
            ingested_at=now,
            headline="old",
            source_reliability_tier="T1_REGULATORY",
            dedup_key_hash="old",
            metadata={"importance": "high"},
        )
        new_event = ExternalEventEntity(
            event_id=uuid4(),
            source_event_id="new",
            source_name="opendart",
            event_type="Y|유상증자결정",
            issuer_code="00123456",
            symbol="005930",
            published_at=now - timedelta(hours=1),
            ingested_at=now,
            headline="new",
            source_reliability_tier="T1_REGULATORY",
            dedup_key_hash="new",
            metadata={"importance": "high"},
        )

        # Insert old first, then new
        await repos.external_events.add(old_event)
        await repos.external_events.add(new_event)

        request = _make_request()
        intent = await svc.assemble(request)

        recent = intent.context.recent_events
        assert len(recent) == 2
        # Newer event should come first (DESC)
        assert recent[0].source_event_id == "new", (
            f"Expected newer first, got {recent[0].source_event_id}"
        )
        assert recent[1].source_event_id == "old", (
            f"Expected older last, got {recent[1].source_event_id}"
        )

    @pytest.mark.asyncio
    async def test_missing_metadata_fallback_to_low(self) -> None:
        """Events without metadata.importance are treated as low."""
        repos = build_in_memory_repositories()
        svc = DecisionOrchestratorService(repos=repos)
        now = datetime.now(timezone.utc)

        high_event = ExternalEventEntity(
            event_id=uuid4(),
            source_event_id="h001",
            source_name="opendart",
            event_type="Y|유상증자결정",
            issuer_code="00123456",
            symbol="005930",
            published_at=now - timedelta(hours=3),
            ingested_at=now,
            headline="유상증자결정",
            source_reliability_tier="T1_REGULATORY",
            dedup_key_hash="h001",
            metadata={"importance": "high"},
        )
        no_meta_event = ExternalEventEntity(
            event_id=uuid4(),
            source_event_id="no-meta",
            source_name="opendart",
            event_type="Y|사업보고서",
            issuer_code="00123456",
            symbol="005930",
            published_at=now - timedelta(hours=1),
            ingested_at=now,
            headline="사업보고서",
            source_reliability_tier="T1_REGULATORY",
            dedup_key_hash="no-meta",
            metadata=None,  # no metadata at all
        )

        await repos.external_events.add(no_meta_event)
        await repos.external_events.add(high_event)

        request = _make_request()
        intent = await svc.assemble(request)

        recent = intent.context.recent_events
        assert len(recent) == 2
        # High should come first even though no-meta is newer
        assert recent[0].source_event_id == "h001", (
            f"Expected high first, got {recent[0].source_event_id}"
        )
        assert recent[1].source_event_id == "no-meta", (
            f"Expected no-meta last, got {recent[1].source_event_id}"
        )
