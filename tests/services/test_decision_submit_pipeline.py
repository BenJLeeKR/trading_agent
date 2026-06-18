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

import asyncio
from dataclasses import replace
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
    TradeDecisionEntity,
)
from agent_trading.domain.enums import (
    AssetClass,
    DecisionType,
    EntryStyle,
    Environment,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from agent_trading.domain.models import Quote, SubmitOrderRequest
from agent_trading.services.common_types import (
    AIDecisionInputs,
    AgentExecutionBundle,
    AssembledContext,
    OrderIntent,
    PhaseTraceEntry,
    SubmitResult,
)
from agent_trading.services.decision_orchestrator import (
    DecisionOrchestratorService,
)
from agent_trading.services.translation import (
    build_submit_order_request_from_decision,
    normalize_decision_type,
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

    def test_held_position_buy_returns_none(self) -> None:
        request = _make_request(
            side=OrderSide.BUY,
            metadata={"source_type": "held_position"},
        )
        intent = _make_intent(decision_type="APPROVE", request=request)
        assert build_submit_order_request_from_decision(intent) is None

    def test_held_position_sell_returns_request(self) -> None:
        request = _make_request(
            side=OrderSide.SELL,
            metadata={"source_type": "held_position"},
        )
        intent = _make_intent(decision_type="REDUCE", request=request)
        result = build_submit_order_request_from_decision(intent)
        assert result is not None
        assert result.side == OrderSide.SELL

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

    # ── Normalization tests: normalize_decision_type() unit tests ──
    # These test the normalization function directly.
    # build_submit_order_request_from_decision() receives already-normalized
    # values from _run_agents(), so it is tested with canonical values.

    def test_entry_normalized_to_approve(self) -> None:
        """``entry`` → ``APPROVE`` (actionable)."""
        assert normalize_decision_type("entry") == "APPROVE"

    def test_entry_uppercase_normalized_to_approve(self) -> None:
        """``ENTRY`` → ``APPROVE``."""
        assert normalize_decision_type("ENTRY") == "APPROVE"

    def test_entry_mixed_case_normalized_to_approve(self) -> None:
        """``Entry`` → ``APPROVE``."""
        assert normalize_decision_type("Entry") == "APPROVE"

    def test_no_action_normalized_to_hold(self) -> None:
        """``no_action`` → ``HOLD`` (non-actionable)."""
        assert normalize_decision_type("no_action") == "HOLD"

    def test_no_trade_normalized_to_hold(self) -> None:
        """``no_trade`` → ``HOLD``."""
        assert normalize_decision_type("no_trade") == "HOLD"

    def test_none_normalized_to_hold(self) -> None:
        """``none`` → ``HOLD``."""
        assert normalize_decision_type("none") == "HOLD"

    def test_approve_passthrough(self) -> None:
        """``APPROVE`` passes through unchanged."""
        assert normalize_decision_type("APPROVE") == "APPROVE"

    def test_hold_passthrough(self) -> None:
        """``HOLD`` passes through unchanged."""
        assert normalize_decision_type("HOLD") == "HOLD"

    def test_buy_passthrough(self) -> None:
        """``BUY`` passes through unchanged (actionable_types compatible)."""
        assert normalize_decision_type("BUY") == "BUY"

    def test_sell_passthrough(self) -> None:
        """``SELL`` passes through unchanged."""
        assert normalize_decision_type("SELL") == "SELL"

    def test_unknown_fallback_to_hold(self) -> None:
        """Unknown value falls back to ``HOLD``."""
        assert normalize_decision_type("foobar") == "HOLD"

    def test_empty_fallback_to_hold(self) -> None:
        """Empty string falls back to ``HOLD``."""
        assert normalize_decision_type("") == "HOLD"

    def test_whitespace_fallback_to_hold(self) -> None:
        """Whitespace-only string falls back to ``HOLD``."""
        assert normalize_decision_type("  ") == "HOLD"


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
        assert result.order_intent is not None
        assert result.submit_response is not None
        assert result.submit_response.status == OrderStatus.SUBMITTED
        assert result.error_phase is None
        # --- Gap 2: traceability assertions ---
        assert result.decision_context_id is not None, (
            "SubmitResult.decision_context_id must be set on happy path"
        )
        assert result.decision_context_id == result.order_intent.decision_context_id, (
            "SubmitResult.decision_context_id must match order_intent.decision_context_id"
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
        assert result.stop_reason == "order_rejected"
        assert result.order_intent is not None
        assert result.submit_response is not None
        assert result.submit_response.status == OrderStatus.REJECTED
        # --- Gap 2: traceability assertion ---
        assert result.decision_context_id is not None, (
            "SubmitResult.decision_context_id must be set on reject path"
        )
        assert result.decision_context_id == result.order_intent.decision_context_id, (
            "SubmitResult.decision_context_id must match order_intent.decision_context_id"
        )

    # ── RECONCILE_REQUIRED ──

    @pytest.mark.asyncio
    async def test_reconcile_required(
        self,
        service: DecisionOrchestratorService,
        order_manager: OrderManager,
        sample_request: SubmitOrderRequest,
        repos: Any,
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
        assert result.stop_reason == "order_reconcile_required"
        assert result.order_intent is not None
        assert result.submit_response is not None
        assert result.submit_response.status == OrderStatus.RECONCILE_REQUIRED
        evaluations = list(repos.guardrail_evaluations._items.values())  # type: ignore[attr-defined]
        assert len(evaluations) == 1
        assert evaluations[0].rule_set_version == "broker_submit_outcome_v1"
        assert evaluations[0].blocking_rule_codes == ["order_reconcile_required"]
        # --- Gap 2: traceability assertion ---
        assert result.decision_context_id is not None, (
            "SubmitResult.decision_context_id must be set on reconcile path"
        )
        assert result.decision_context_id == result.order_intent.decision_context_id, (
            "SubmitResult.decision_context_id must match order_intent.decision_context_id"
        )

    @pytest.mark.asyncio
    async def test_low_liquidity_market_buy_forces_limit_order(
        self,
        service: DecisionOrchestratorService,
        order_manager: OrderManager,
    ) -> None:
        request = _make_request(
            order_type=OrderType.MARKET,
            price=None,
            quantity=Decimal("1"),
            metadata={"source_type": "market_overlay"},
        )
        submitted_requests: list[SubmitOrderRequest] = []

        async def _mock_submit(
            _self: Any,
            _order: OrderRequestEntity,
            _broker: Any,
            submit_request: SubmitOrderRequest,
            *_args: Any,
            **_kwargs: Any,
        ) -> OrderRequestEntity:
            submitted_requests.append(submit_request)
            return _make_order_entity(
                status=OrderStatus.SUBMITTED,
                request=submit_request,
            )

        broker_mock = MagicMock()
        broker_mock.get_quote = AsyncMock(
            return_value=Quote(
                symbol="005930",
                market="KRX",
                bid=Decimal("50000"),
                ask=Decimal("50010"),
                last=Decimal("50005"),
                as_of=datetime.now(timezone.utc),
                accumulated_volume=Decimal("2500"),
                accumulated_turnover=Decimal("40000000"),
            )
        )

        with patch.object(OrderManager, "submit_order_to_broker", _mock_submit):
            result = await service.assemble_and_submit(
                request,
                order_manager=order_manager,
                broker=broker_mock,
            )

        assert result.status == "SUBMITTED"
        assert len(submitted_requests) == 1
        assert submitted_requests[0].order_type == OrderType.LIMIT
        assert submitted_requests[0].price == Decimal("50010")

    @pytest.mark.asyncio
    async def test_severe_low_liquidity_market_buy_is_blocked(
        self,
        service: DecisionOrchestratorService,
        order_manager: OrderManager,
        repos: Any,
    ) -> None:
        request = _make_request(
            order_type=OrderType.MARKET,
            price=None,
            quantity=Decimal("1"),
            metadata={"source_type": "market_overlay"},
        )

        async def _mock_submit(*args: Any, **kwargs: Any) -> OrderRequestEntity:
            raise AssertionError("Broker should not be called for severe low-liquidity BUY")

        broker_mock = MagicMock()
        broker_mock.get_quote = AsyncMock(
            return_value=Quote(
                symbol="005930",
                market="KRX",
                bid=Decimal("50000"),
                ask=Decimal("50010"),
                last=Decimal("50005"),
                as_of=datetime.now(timezone.utc),
                accumulated_volume=Decimal("100"),
                accumulated_turnover=Decimal("2000000"),
            )
        )

        with patch.object(OrderManager, "submit_order_to_broker", _mock_submit):
            result = await service.assemble_and_submit(
                request,
                order_manager=order_manager,
                broker=broker_mock,
            )

        assert result.status == "SKIPPED"
        assert result.stop_reason == "low_liquidity_execution_blocked"
        evaluations = list(repos.guardrail_evaluations._items.values())  # type: ignore[attr-defined]
        assert len(evaluations) == 1
        assert evaluations[0].rule_set_version == "buy_execution_liquidity_v1"
        assert evaluations[0].blocking_rule_codes == ["low_liquidity_execution_blocked"]

    @pytest.mark.asyncio
    async def test_rejected_records_broker_submit_outcome_guardrail(
        self,
        service: DecisionOrchestratorService,
        order_manager: OrderManager,
        sample_request: SubmitOrderRequest,
        repos: Any,
    ) -> None:
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

        assert result.status == "REJECTED"
        assert result.stop_reason == "order_rejected"
        evaluations = list(repos.guardrail_evaluations._items.values())  # type: ignore[attr-defined]
        assert len(evaluations) == 1
        assert evaluations[0].rule_set_version == "broker_submit_outcome_v1"
        assert evaluations[0].blocking_rule_codes == ["order_rejected"]

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
        assert result.order_intent is not None
        assert result.submit_response is None  # No order created for HOLD
        # --- Gap 2: traceability assertion ---
        assert result.decision_context_id is not None, (
            "SubmitResult.decision_context_id must be set on SKIPPED path"
        )
        assert result.decision_context_id == result.order_intent.decision_context_id, (
            "SubmitResult.decision_context_id must match order_intent.decision_context_id"
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
        assert result.submit_response is not None, "Order must exist"
        # The order's requested_quantity should be the sized quantity (10),
        # not the original 100.
        assert result.submit_response.requested_quantity == Decimal("10"), (
            f"Expected sized quantity 10 (cash-limited), "
            f"got {result.submit_response.requested_quantity}"
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
        assert result.order_intent is not None
        assert result.submit_response is None  # No order created
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
        assert result.decision_context_id == result.order_intent.decision_context_id, (
            "SubmitResult.decision_context_id must match order_intent.decision_context_id"
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

    @pytest.mark.asyncio
    async def test_assemble_includes_seeded_news(self) -> None:
        """``assemble()`` calls ``list_by_symbol()`` with ``include_seeded_news=True``.

        EI가 persisted seeded 뉴스를 읽을 수 있도록 assemble()이
        include_seeded_news=True를 전달하는지 검증.
        """
        repos = build_in_memory_repositories()
        svc = DecisionOrchestratorService(repos=repos)
        now = datetime.now(timezone.utc)

        # Seed a listed event (Y| prefix)
        listed_event = ExternalEventEntity(
            event_id=uuid4(),
            event_type="K|분기보고서 (2026.03)",
            source_name="opendart",
            published_at=now - timedelta(hours=2),
            source_reliability_tier="T1",
            symbol="005930",
            issuer_code="00123456",
            ingested_at=now - timedelta(hours=2),
            headline="분기보고서",
        )
        await repos.external_events.add(listed_event)

        # Seed a seeded_news event (event_type='seeded_news')
        seeded_event = ExternalEventEntity(
            event_id=uuid4(),
            event_type="seeded_news",
            source_name="naver_news_seeded",
            published_at=now - timedelta(hours=1),
            source_reliability_tier="T3",
            symbol="005930",
            ingested_at=now - timedelta(hours=1),
            headline="Seeded news headline",
        )
        await repos.external_events.add(seeded_event)

        request = _make_request()
        intent = await svc.assemble(request)

        # Both events should be included (listed + seeded_news)
        event_ids = {e.event_id for e in intent.context.recent_events}
        assert listed_event.event_id in event_ids, (
            "Listed event must be included in recent_events"
        )
        assert seeded_event.event_id in event_ids, (
            "Seeded news event must be included in recent_events when include_seeded_news=True"
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

        # Prompt의 event 줄 수는 10개여야 함 ([:MAX_EVENTS_EI] slice)
        event_lines = [line for line in prompt.split("\n") if line.startswith("  [src:")]
        assert len(event_lines) == 10, (
            f"Expected 10 event lines in prompt, got {len(event_lines)}"
        )

        # event_0 ~ event_9는 있어야 함
        assert "event_0" in prompt
        assert "event_9" in prompt
        # event_10 ~ event_24는 없어야 함
        assert "event_10" not in prompt


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


class TestPhase5BrokerSubmitFailureLogging:
    """Phase 5 broker submit failure must log symbol/decision_type/order_id."""

    async def _setup_orchestrator(
        self,
        repos: Any,
        *,
        stale_snapshot: bool = False,
    ) -> DecisionOrchestratorService:
        """Set up orchestrator with optional stale snapshot."""
        now = datetime.now(timezone.utc)
        client_id = uuid4()
        account_id = uuid4()

        # Seed account matching _make_request() account_ref="test-account"
        account = AccountEntity(
            account_id=account_id,
            client_id=client_id,
            broker_account_id=uuid4(),
            environment=Environment.PAPER,
            account_alias="test-account",
            account_masked="test-****",
            status="active",
        )
        await repos.accounts.add(account)

        # Seed config version so _ensure_or_create_decision_context succeeds
        config_version = ConfigVersionEntity(
            config_version_id=uuid4(),
            client_id=client_id,
            environment=Environment.PAPER,
            version_tag="v1.0",
            config_json={},
            checksum="abc123",
            activated_at=now,
        )
        await repos.config_versions.add(config_version)

        # Seed instrument matching _make_request() symbol="005930" market="KRX"
        instrument = InstrumentEntity(
            instrument_id=uuid4(),
            symbol="005930",
            market_code="KRX",
            asset_class=AssetClass.KR_STOCK,
            currency="KRW",
            name="Samsung Electronics",
        )
        await repos.instruments.add(instrument)

        if not stale_snapshot:
            cash = CashBalanceSnapshotEntity(
                cash_balance_snapshot_id=uuid4(),
                account_id=account_id,
                currency="KRW",
                available_cash=Decimal("1000000"),
                settled_cash=Decimal("1000000"),
                unsettled_cash=None,
                source_of_truth="broker",
                snapshot_at=now,
            )
            await repos.cash_balance_snapshots.add(cash)

        # Seed a fresh position snapshot so Phase 4c guardrail passes
        pos = PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=account_id,
            instrument_id=instrument.instrument_id,
            quantity=Decimal("10"),
            average_price=Decimal("50000"),
            market_price=Decimal("50000"),
            unrealized_pnl=Decimal("0"),
            source_of_truth="broker",
            snapshot_at=now,
        )
        await repos.position_snapshots.add(pos)

        svc = DecisionOrchestratorService(
            repos=repos,
            event_interpretation_agent=AsyncMock(),
            ai_risk_agent=AsyncMock(),
            final_decision_agent=AsyncMock(),
            score_calculator=AsyncMock(),
            stale_threshold_seconds=900,
        )
        return svc

    @patch(
        "agent_trading.services.decision_orchestrator.DecisionOrchestratorService._run_agents"
    )
    @patch(
        "agent_trading.services.decision_orchestrator.DecisionOrchestratorService._ensure_trade_decision"
    )
    async def test_broker_submit_exception_logs_symbol_and_decision_type(
        self,
        mock_ensure_trade: AsyncMock,
        mock_run_agents: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Phase 5 broker submit exception must include symbol/decision_type in log."""
        import logging

        caplog.set_level(logging.INFO)

        repos = build_in_memory_repositories()
        svc = await self._setup_orchestrator(repos)

        # Mock agents to return AgentExecutionBundle with BUY decision_type
        mock_run_agents.return_value = AgentExecutionBundle(
            ai_inputs=AIDecisionInputs(
                decision_type="BUY",
                confidence=0.8,
                conviction=0.7,
            ),
        )
        trade_decision_id = uuid4()
        mock_ensure_trade.return_value = TradeDecisionEntity(
            trade_decision_id=trade_decision_id,
            decision_context_id=uuid4(),
            decision_type=DecisionType.BUY,
            side=OrderSide.BUY,
            strategy_id=uuid4(),
            symbol="005930",
            market="KRX",
            entry_style=EntryStyle.LIMIT,
            created_at=datetime.now(timezone.utc),
        )

        # Mock order_manager.submit_order_to_broker to raise
        mock_order_manager = AsyncMock(spec=OrderManager)
        mock_order_manager.submit_order_to_broker.side_effect = RuntimeError(
            "KIS API connection refused"
        )

        mock_broker = AsyncMock()
        mock_broker.__class__.__name__ = "MockBrokerAdapter"

        request = _make_request()
        result = await svc.assemble_and_submit(
            request,
            order_manager=mock_order_manager,
            broker=mock_broker,
        )

        assert result is not None
        assert result.status == "ERROR"
        assert result.error_phase == "order_submit"
        assert "KIS API connection refused" in str(result.error_message)

        # Verify log contains symbol and decision_type
        assert any(
            "Phase 5 FAILED" in record.message and "005930" in record.message
            for record in caplog.records
        ), "Phase 5 FAILED log must contain symbol"
        assert any(
            "Phase 5 FAILED" in record.message and "BUY" in record.message
            for record in caplog.records
        ), "Phase 5 FAILED log must contain decision_type"


class TestEIPostProcessingGuard:
    """EI post-processing guard 검증.

    ``EventInterpretationAgent.run()``에서 input events > 0인데
    output event_count=0이면 deterministic 보정이 적용되는지 확인.
    """

    @pytest.mark.asyncio
    async def test_self_contradiction_guard_preserves_llm_output(
        self,
    ) -> None:
        """Self-contradiction guard: LLM 응답 유지 + degraded 플래그만 설정.

        input events > 0, output event_count=0 → guard가 LLM 값을 유지하고
        degraded 플래그만 추가.
        """
        from agent_trading.services.ai_agents.base import RawProviderResponse
        from agent_trading.services.ai_agents.schemas import (
            AggregateEventView,
            EventInterpretationOutput,
        )
        from agent_trading.services.common_types import ScoreResult
        from agent_trading.domain.entities import ExternalEventEntity

        # Provider가 events=[], event_count=0, no_material_events=True 반환
        provider_output = EventInterpretationOutput(
            symbol="005930",
            events=(),
            aggregate_view=AggregateEventView(
                overall_bias="neutral",
                event_count=0,
                no_material_events=True,
                evidence_strength="none",
            ),
        )

        mock_provider = AsyncMock()
        mock_provider.generate_structured.return_value = RawProviderResponse(
            parsed=provider_output,
            raw_content='{"symbol":"005930","events":[],"aggregate_view":{"event_count":0,"no_material_events":true}}',
        )

        agent = EventInterpretationAgent(provider_client=mock_provider)

        # input events > 0인 request 생성 (ExternalEventEntity 사용)
        now = datetime.now(timezone.utc)
        input_events = (
            ExternalEventEntity(
                event_id=uuid4(),
                event_type="seeded_news",
                source_name="naver_news_seeded",
                source_reliability_tier="T3",
                published_at=now,
                headline="Test event 1",
                body_summary="Test summary",
                severity="medium",
                direction="neutral",
            ),
        )

        request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="test-correlation",
            context=AssembledContext(
                score=ScoreResult(score=0.5, threshold=0.3),
                recent_events=input_events,
            ),
            symbol="005930",
            market="KRX",
        )

        result = await agent.run(request)

        # LLM 응답이 유지되어야 함 (override되지 않음)
        # Phase 3-1: detected_event_count가 primary field
        assert result.detected_event_count == 0, (
            f"Expected detected_event_count=0 (LLM preserved), got {result.detected_event_count}"
        )
        assert result.aggregate_view.no_material_events is True, (
            "Expected no_material_events=True (LLM preserved)"
        )
        # events tuple은 그대로 유지 (LLM이 반환한 그대로)
        assert len(result.events) == 0, (
            "events tuple should remain empty (LLM output preserved)"
        )
        # Degraded 플래그가 설정되어야 함
        assert result.aggregate_view.interpretation_incomplete is True, (
            "Expected interpretation_incomplete=True"
        )
        assert result.aggregate_view.degraded_reason == "self_contradiction_corrected", (
            f"Expected degraded_reason='self_contradiction_corrected', got {result.aggregate_view.degraded_reason}"
        )
        assert result.is_degraded is True, (
            "Expected is_degraded=True"
        )
        # Summary 확인 (Case 3: self-contradiction)
        assert result.summary is not None, "Summary should be set"
        assert "입력 이벤트 감지됨" in result.summary, (
            f"Expected '입력 이벤트 감지됨' in summary, got: {result.summary}"
        )
        assert "세부 이벤트 추출 누락" in result.summary, (
            f"Expected '세부 이벤트 추출 누락' in summary, got: {result.summary}"
        )
        # ★ Phase 1: 신규 필드 검증
        assert result.detected_event_count == 0, (
            f"detected_event_count should be 0 (LLM raw preserved), got {result.detected_event_count}"
        )
        assert result.interpreted_event_count == 0, (
            f"interpreted_event_count should be 0 (no events), got {result.interpreted_event_count}"
        )
        assert result.summary_basis == "detected_only", (
            f"summary_basis should be 'detected_only', got {result.summary_basis}"
        )

    @pytest.mark.asyncio
    async def test_guard_does_not_correct_when_input_events_zero(
        self,
    ) -> None:
        """input events = 0 → guard가 보정하지 않음 (정상 케이스)."""
        from agent_trading.services.ai_agents.base import RawProviderResponse
        from agent_trading.services.ai_agents.schemas import (
            AggregateEventView,
            EventInterpretationOutput,
        )
        from agent_trading.services.common_types import ScoreResult

        provider_output = EventInterpretationOutput(
            symbol="005930",
            events=(),
            aggregate_view=AggregateEventView(
                overall_bias="neutral",
                event_count=0,
                no_material_events=True,
                evidence_strength="none",
            ),
        )

        mock_provider = AsyncMock()
        mock_provider.generate_structured.return_value = RawProviderResponse(
            parsed=provider_output,
            raw_content='{"symbol":"005930","events":[],"aggregate_view":{"event_count":0,"no_material_events":true}}',
        )

        agent = EventInterpretationAgent(provider_client=mock_provider)

        # input events = 0
        request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="test-correlation",
            context=AssembledContext(
                score=ScoreResult(score=0.5, threshold=0.3),
                recent_events=(),
            ),
            symbol="005930",
            market="KRX",
        )

        result = await agent.run(request)

        # Guard가 보정하지 않아야 함
        # Phase 3-1: detected_event_count가 primary field
        assert result.detected_event_count == 0, (
            "detected_event_count should remain 0 when input events is 0"
        )
        assert result.aggregate_view.no_material_events is True, (
            "no_material_events should remain True when input events is 0"
        )
        # ★ Phase 1: 신규 필드 검증
        assert result.detected_event_count == 0, (
            f"detected_event_count should be 0 (no input, LLM returned 0), got {result.detected_event_count}"
        )
        assert result.interpreted_event_count == 0, (
            f"interpreted_event_count should be 0 (no events), got {result.interpreted_event_count}"
        )
        assert result.summary_basis == "none", (
            f"summary_basis should be 'none', got {result.summary_basis}"
        )

    @pytest.mark.asyncio
    async def test_guard_preserves_llm_events_when_output_has_events(
        self,
    ) -> None:
        """LLM이 정상적으로 events를 반환하면 guard가 개입하지 않음."""
        from agent_trading.services.ai_agents.base import RawProviderResponse
        from agent_trading.services.ai_agents.schemas import (
            AggregateEventView,
            EventInterpretationOutput,
            InterpretedEvent,
        )
        from agent_trading.services.common_types import ScoreResult
        from agent_trading.domain.entities import ExternalEventEntity

        # LLM이 정상적으로 1개 event를 반환
        llm_event = InterpretedEvent(
            source_event_id="src-001",
            event_type="K|분기보고서",
            source_name="opendart",
            source_reliability_tier="T1",
            impact_direction="positive",
            summary="LLM analysis",
        )

        provider_output = EventInterpretationOutput(
            symbol="005930",
            events=(llm_event,),
            aggregate_view=AggregateEventView(
                overall_bias="positive",
                event_count=1,
                no_material_events=False,
                evidence_strength="moderate",
                top_reason_codes=("earnings",),
            ),
        )

        mock_provider = AsyncMock()
        mock_provider.generate_structured.return_value = RawProviderResponse(
            parsed=provider_output,
            raw_content='{"symbol":"005930","events":[{"source_event_id":"src-001","event_type":"K|분기보고서"}],"aggregate_view":{"event_count":1,"no_material_events":false}}',
        )

        agent = EventInterpretationAgent(provider_client=mock_provider)

        # input events > 0 (ExternalEventEntity 사용)
        now = datetime.now(timezone.utc)
        input_events = (
            ExternalEventEntity(
                event_id=uuid4(),
                event_type="seeded_news",
                source_name="naver_news_seeded",
                source_reliability_tier="T3",
                published_at=now,
                headline="Input event",
                body_summary="Input summary",
                severity="medium",
                direction="neutral",
            ),
        )

        request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="test-correlation",
            context=AssembledContext(
                score=ScoreResult(score=0.5, threshold=0.3),
                recent_events=input_events,
            ),
            symbol="005930",
            market="KRX",
        )

        result = await agent.run(request)

        # LLM이 반환한 events가 그대로 유지되어야 함
        assert len(result.events) == 1, (
            "LLM events should be preserved"
        )
        assert result.events[0].summary == "LLM analysis", (
            "LLM event summary should be preserved"
        )
        assert result.detected_event_count == 1, (
            "detected_event_count should remain 1 (LLM output preserved)"
        )
        assert result.aggregate_view.no_material_events is False, (
            "no_material_events should remain False"
        )
        # ★ Phase 1: 신규 필드 검증
        assert result.detected_event_count == 1, (
            f"detected_event_count should be 1 (LLM raw event_count), got {result.detected_event_count}"
        )
        assert result.interpreted_event_count == 1, (
            f"interpreted_event_count should be 1 (1 event), got {result.interpreted_event_count}"
        )
        assert result.summary_basis == "interpreted", (
            f"summary_basis should be 'interpreted', got {result.summary_basis}"
        )

    @pytest.mark.asyncio
    async def test_exception_fallback_sets_degraded_flags_with_input(
        self,
    ) -> None:
        """Provider exception + input_events>0 → fallback에 degraded flags 설정.

        - event_count=0 (LLM 응답 없음 → 0)
        - no_material_events=True (fallback-safe)
        - interpretation_incomplete=True
        - degraded_reason='provider_error'
        - summary: "(1건) 입력 이벤트 감지됨. AI 분석 실패."
        """
        from agent_trading.services.ai_agents.base import RawProviderResponse
        from agent_trading.services.ai_agents.schemas import (
            AggregateEventView,
            EventInterpretationOutput,
        )
        from agent_trading.services.common_types import ScoreResult
        from agent_trading.domain.entities import ExternalEventEntity

        # Provider가 exception을 던지는 상황 시뮬레이션
        mock_provider = AsyncMock()
        mock_provider.generate_structured.side_effect = RuntimeError(
            "Provider API timeout"
        )

        agent = EventInterpretationAgent(provider_client=mock_provider)

        # input events > 0인 request 생성
        now = datetime.now(timezone.utc)
        input_events = (
            ExternalEventEntity(
                event_id=uuid4(),
                event_type="seeded_news",
                source_name="naver_news_seeded",
                source_reliability_tier="T3",
                published_at=now,
                headline="Test event 1",
                body_summary="Test summary",
                severity="medium",
                direction="neutral",
            ),
        )

        request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="test-correlation",
            context=AssembledContext(
                score=ScoreResult(score=0.5, threshold=0.3),
                recent_events=input_events,
            ),
            symbol="000810",
            market="KRX",
        )

        result = await agent.run(request)

        # Degraded flags 확인
        assert result.aggregate_view.interpretation_incomplete is True, (
            "Expected interpretation_incomplete=True"
        )
        assert result.aggregate_view.degraded_reason == "provider_error", (
            f"Expected degraded_reason='provider_error', got {result.aggregate_view.degraded_reason}"
        )
        # detected_event_count는 input_event_count 보존 (Phase 1: exception fallback에서 input 보존)
        assert result.detected_event_count == 1, (
            f"Expected detected_event_count=1 (input_event_count preserved), got {result.detected_event_count}"
        )
        # no_material_events는 False (Phase 1: input이 있으므로 False)
        assert result.aggregate_view.no_material_events is False, (
            f"Expected no_material_events=False (input_event_count preserved), got {result.aggregate_view.no_material_events}"
        )
        # symbol이 빈 값이 아닌 request.symbol로 설정되어야 함
        assert result.symbol == "000810", (
            f"Expected symbol='000810' from fallback, got '{result.symbol}'"
        )
        # evidence_strength는 fallback에서 'weak'으로 설정
        assert result.aggregate_view.evidence_strength == "weak", (
            f"Expected evidence_strength='weak' from fallback, got '{result.aggregate_view.evidence_strength}'"
        )
        # Summary 확인 (Case 4: provider failure)
        assert result.summary is not None and len(result.summary) > 0, (
            f"Summary should be set, got: '{result.summary}'"
        )
        assert "입력 이벤트 감지됨" in result.summary, (
            f"Expected '입력 이벤트 감지됨' in summary, got: {result.summary}"
        )
        assert "AI 분석 실패" in result.summary, (
            f"Expected 'AI 분석 실패' in summary, got: {result.summary}"
        )
        # ★ Phase 1: 신규 필드 검증
        assert result.detected_event_count == 1, (
            f"detected_event_count should be 1 (input preserved), got {result.detected_event_count}"
        )
        assert result.interpreted_event_count == 0, (
            f"interpreted_event_count should be 0 (fallback, no events), got {result.interpreted_event_count}"
        )
        # Fallback: detected=1, input_event_count=1, events=() → "detected_only"
        assert result.summary_basis == "detected_only", (
            f"summary_basis should be 'detected_only', got {result.summary_basis}"
        )

    @pytest.mark.asyncio
    async def test_exception_fallback_sets_degraded_flags_no_input(
        self,
    ) -> None:
        """Provider exception + input events=0 → fallback에 degraded flags 설정."""
        from agent_trading.services.ai_agents.base import RawProviderResponse
        from agent_trading.services.ai_agents.schemas import (
            AggregateEventView,
            EventInterpretationOutput,
        )
        from agent_trading.services.common_types import ScoreResult

        mock_provider = AsyncMock()
        mock_provider.generate_structured.side_effect = RuntimeError(
            "Provider API timeout"
        )

        agent = EventInterpretationAgent(provider_client=mock_provider)

        # input events = 0
        request = AgentExecutionRequest(
            decision_context_id=uuid4(),
            correlation_id="test-correlation",
            context=AssembledContext(
                score=ScoreResult(score=0.5, threshold=0.3),
                recent_events=(),
            ),
            symbol="000150",
            market="KRX",
        )

        result = await agent.run(request)

        # Degraded flags 확인
        assert result.aggregate_view.interpretation_incomplete is True, (
            "Expected interpretation_incomplete=True"
        )
        assert result.aggregate_view.degraded_reason == "provider_error", (
            f"Expected degraded_reason='provider_error', got {result.aggregate_view.degraded_reason}"
        )
        # detected_event_count=0 유지
        assert result.detected_event_count == 0, (
            f"Expected detected_event_count=0 when input events=0, got {result.detected_event_count}"
        )
        assert result.aggregate_view.no_material_events is True, (
            "Expected no_material_events=True when input events=0"
        )
        # symbol 보존
        assert result.symbol == "000150", (
            f"Expected symbol='000150', got '{result.symbol}'"
        )
        # Summary 확인
        assert result.summary is not None and len(result.summary) > 0, (
            f"Summary should be set, got: '{result.summary}'"
        )
        # ★ Phase 1: 신규 필드 검증
        assert result.detected_event_count == 0, (
            f"detected_event_count should be 0 (no input, no LLM), got {result.detected_event_count}"
        )
        assert result.interpreted_event_count == 0, (
            f"interpreted_event_count should be 0 (fallback), got {result.interpreted_event_count}"
        )
        assert result.summary_basis == "none", (
            f"summary_basis should be 'none', got {result.summary_basis}"
        )

    # ------------------------------------------------------------------
    # Round 12: Summary 보정 + 진단 로깅 테스트
    # ------------------------------------------------------------------

    def test_summary_case2_degraded_with_events(
        self,
    ) -> None:
        """Degraded + events 있음 → summary에 "(일부 해석 누락)" 포함.

        Case 2: degraded 상태에서 events가 있으면 "(일부 해석 누락)"을 추가.
        """
        from agent_trading.services.ai_agents.event_interpretation import (
            _build_summary_text,
        )
        from agent_trading.services.ai_agents.schemas import (
            AggregateEventView,
            EventInterpretationOutput,
            InterpretedEvent,
        )

        output = EventInterpretationOutput(
            symbol="000150",
            events=(
                InterpretedEvent(
                    source_event_id="evt-001",
                    event_type="earnings",
                    source_name="DART",
                    source_reliability_tier="tier1",
                    stale=False,
                    impact_direction="positive",
                    impact_horizon="short_term",
                    confidence=0.8,
                    novelty="routine",
                    supports_entry=True,
                    supports_exit=False,
                    risk_flags=(),
                    reason_codes=("earnings_surprise",),
                    summary="호실적 발표: 매출 15% 증가",
                ),
            ),
            aggregate_view=AggregateEventView(
                overall_bias="positive",
                event_conflict=False,
                top_reason_codes=("earnings_surprise",),
                opposing_evidence=(),
                evidence_strength="moderate",
                event_count=1,
                no_material_events=False,
                interpretation_incomplete=True,
                degraded_reason="partial_failure",
            ),
        )

        summary = _build_summary_text(output)

        # 정상 요약 포맷 유지
        assert "(1건)" in summary, (
            f"Expected '(1건)' in summary, got: {summary}"
        )
        assert "호실적" in summary, (
            f"Expected event summary in output, got: {summary}"
        )
        # "(일부 해석 누락)" 포함
        assert "일부 해석 누락" in summary, (
            f"Expected '(일부 해석 누락)' in summary, got: {summary}"
        )

    def test_summary_case3_self_contradiction(
        self,
    ) -> None:
        """Self-contradiction → "(N건) 입력 이벤트 감지됨. 세부 이벤트 추출 누락."

        Case 3: events=[], input>0, degraded, degraded_reason="self_contradiction_corrected"
        """
        from agent_trading.services.ai_agents.event_interpretation import (
            _build_summary_text,
        )
        from agent_trading.services.ai_agents.schemas import (
            AggregateEventView,
            EventInterpretationOutput,
        )

        output = EventInterpretationOutput(
            symbol="000150",
            events=(),
            aggregate_view=AggregateEventView(
                overall_bias="neutral",
                event_conflict=False,
                top_reason_codes=(),
                opposing_evidence=(),
                evidence_strength="none",
                event_count=0,  # LLM 응답 유지
                no_material_events=True,  # LLM 응답 유지
                interpretation_incomplete=True,
                degraded_reason="self_contradiction_corrected",
            ),
        )

        # input_event_count=3 전달
        summary = _build_summary_text(output, input_event_count=3)

        assert "(3건)" in summary, (
            f"Expected '(3건)' in summary, got: {summary}"
        )
        assert "입력 이벤트 감지됨" in summary, (
            f"Expected '입력 이벤트 감지됨' in summary, got: {summary}"
        )
        assert "세부 이벤트 추출 누락" in summary, (
            f"Expected '세부 이벤트 추출 누락' in summary, got: {summary}"
        )

    def test_summary_preserves_no_events_when_no_material_events_true(
        self,
    ) -> None:
        """no_material_events=True, events=[] → "유의미한 신규 이벤트 없음" 유지."""
        from agent_trading.services.ai_agents.event_interpretation import (
            _build_summary_text,
        )
        from agent_trading.services.ai_agents.schemas import (
            AggregateEventView,
            EventInterpretationOutput,
        )

        output = EventInterpretationOutput(
            symbol="000150",
            events=(),
            aggregate_view=AggregateEventView(
                overall_bias="neutral",
                event_conflict=False,
                top_reason_codes=(),
                opposing_evidence=(),
                evidence_strength="none",
                event_count=0,
                no_material_events=True,
            ),
        )

        summary = _build_summary_text(output)

        assert "유의미한 신규 이벤트 없음" in summary, (
            f"Expected '유의미한 신규 이벤트 없음' in summary, got: {summary}"
        )
        assert "전반 중립" in summary, (
            f"Expected '전반 중립' in summary, got: {summary}"
        )

    def test_summary_normal_path_with_events(
        self,
    ) -> None:
        """정상 events 존재 시 기존 상세 요약 경로 유지."""
        from agent_trading.services.ai_agents.event_interpretation import (
            _build_summary_text,
        )
        from agent_trading.services.ai_agents.schemas import (
            AggregateEventView,
            EventInterpretationOutput,
            InterpretedEvent,
        )

        output = EventInterpretationOutput(
            symbol="000150",
            events=(
                InterpretedEvent(
                    source_event_id="evt-001",
                    event_type="earnings",
                    source_name="DART",
                    source_reliability_tier="tier1",
                    stale=False,
                    impact_direction="positive",
                    impact_horizon="short_term",
                    confidence=0.8,
                    novelty="routine",
                    supports_entry=True,
                    supports_exit=False,
                    risk_flags=(),
                    reason_codes=("earnings_surprise",),
                    summary="호실적 발표: 매출 15% 증가",
                ),
            ),
            aggregate_view=AggregateEventView(
                overall_bias="positive",
                event_conflict=False,
                top_reason_codes=("earnings_surprise",),
                opposing_evidence=(),
                evidence_strength="moderate",
                event_count=1,
                no_material_events=False,
            ),
        )

        summary = _build_summary_text(output)

        # 정상 경로: (1건) 형식
        assert "(1건)" in summary, (
            f"Expected '(1건)' in summary, got: {summary}"
        )
        # "유의미한 신규 이벤트 없음"이 아니어야 함
        assert "유의미한 신규 이벤트 없음" not in summary, (
            f"Expected normal summary, got: {summary}"
        )
        # 이벤트 요약 포함
        assert "호실적" in summary, (
            f"Expected event summary in output, got: {summary}"
        )

    def test_summary_case4_provider_failure(
        self,
    ) -> None:
        """Provider failure → "(N건) 입력 이벤트 감지됨. AI 분석 실패."

        Case 4: events=[], degraded, degraded_reason="provider_error",
        input_event_count > 0
        """
        from agent_trading.services.ai_agents.event_interpretation import (
            _build_summary_text,
        )
        from agent_trading.services.ai_agents.schemas import (
            AggregateEventView,
            EventInterpretationOutput,
        )

        output = EventInterpretationOutput(
            symbol="000150",
            events=(),
            aggregate_view=AggregateEventView(
                overall_bias="neutral",
                event_conflict=False,
                top_reason_codes=(),
                opposing_evidence=(),
                evidence_strength="none",
                event_count=0,
                no_material_events=True,
                interpretation_incomplete=True,
                degraded_reason="provider_error",
            ),
        )

        # input_event_count > 0인 경우
        summary = _build_summary_text(output, input_event_count=2)

        assert "(2건)" in summary, (
            f"Expected '(2건)' in summary, got: {summary}"
        )
        assert "입력 이벤트 감지됨" in summary, (
            f"Expected '입력 이벤트 감지됨' in summary, got: {summary}"
        )
        assert "AI 분석 실패" in summary, (
            f"Expected 'AI 분석 실패' in summary, got: {summary}"
        )

    def test_summary_case5_true_no_event(
        self,
    ) -> None:
        """진짜 no-event → "유의미한 신규 이벤트 없음. 전반 중립."

        Case 5: no_material_events=True, events=[], not degraded,
        input_event_count=0
        """
        from agent_trading.services.ai_agents.event_interpretation import (
            _build_summary_text,
        )
        from agent_trading.services.ai_agents.schemas import (
            AggregateEventView,
            EventInterpretationOutput,
        )

        output = EventInterpretationOutput(
            symbol="000150",
            events=(),
            aggregate_view=AggregateEventView(
                overall_bias="neutral",
                event_conflict=False,
                top_reason_codes=(),
                opposing_evidence=(),
                evidence_strength="none",
                event_count=0,
                no_material_events=True,
                interpretation_incomplete=False,
                degraded_reason=None,
            ),
        )

        summary = _build_summary_text(output)

        assert "유의미한 신규 이벤트 없음" in summary, (
            f"Expected '유의미한 신규 이벤트 없음' in summary, got: {summary}"
        )
        assert "전반 중립" in summary, (
            f"Expected '전반 중립' in summary, got: {summary}"
        )


# ---------------------------------------------------------------------------
# EXE-001: PhaseTraceEntry + SubmitResult.phase_trace 검증
# ---------------------------------------------------------------------------


class TestPhaseTrace:
    """EXE-001: PhaseTraceEntry + SubmitResult.phase_trace 검증"""

    class _ApproveFDCAgent:
        """APPROVE를 반환하는 FDC agent stub (pipeline 진행용)."""

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
        instrument = InstrumentEntity(
            instrument_id=uuid4(),
            symbol="005930",
            market_code="KRX",
            asset_class=AssetClass.KR_STOCK,
            currency="KRW",
            name="Samsung Electronics",
        )
        repos.instruments._items[instrument.instrument_id] = instrument
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
        return DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=self._ApproveFDCAgent(),
        )

    @pytest.fixture
    def hold_service(self, repos: Any) -> DecisionOrchestratorService:
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

    @pytest.mark.asyncio
    async def test_phase_trace_in_submit_result(
        self,
        service: DecisionOrchestratorService,
        order_manager: OrderManager,
        sample_request: SubmitOrderRequest,
    ) -> None:
        """성공 submit에서 phase_trace가 올바르게 누적되는지 검증."""
        submitted_entity = _make_order_entity(status=OrderStatus.SUBMITTED, request=sample_request)

        async def _mock_submit(*args: Any, **kwargs: Any) -> OrderRequestEntity:
            return submitted_entity

        broker_stub = object()
        with patch.object(OrderManager, "submit_order_to_broker", _mock_submit):
            result = await service.assemble_and_submit(
                sample_request,
                order_manager=order_manager,
                broker=broker_stub,
            )

        assert result.phase_trace is not None
        assert len(result.phase_trace) > 0
        # 첫 번째는 ai_assemble start
        assert result.phase_trace[0].phase == "ai_assemble"
        assert result.phase_trace[0].status == "start"
        # 마지막은 broker_submit ok
        assert result.phase_trace[-1].status in ("ok", "reconcile")

    @pytest.mark.asyncio
    async def test_phase_trace_elapsed_ms_positive(
        self,
        service: DecisionOrchestratorService,
        order_manager: OrderManager,
        sample_request: SubmitOrderRequest,
    ) -> None:
        """elapsed_ms가 양수인지 검증."""
        submitted_entity = _make_order_entity(status=OrderStatus.SUBMITTED, request=sample_request)

        async def _mock_submit(*args: Any, **kwargs: Any) -> OrderRequestEntity:
            return submitted_entity

        broker_stub = object()
        with patch.object(OrderManager, "submit_order_to_broker", _mock_submit):
            result = await service.assemble_and_submit(
                sample_request,
                order_manager=order_manager,
                broker=broker_stub,
            )

        for entry in result.phase_trace:
            assert entry.elapsed_ms >= 0, (
                f"phase={entry.phase} elapsed_ms={entry.elapsed_ms}"
            )

    @pytest.mark.asyncio
    async def test_phase_trace_in_skipped_result(
        self,
        hold_service: DecisionOrchestratorService,
        order_manager: OrderManager,
    ) -> None:
        """SKIPPED result에도 phase_trace가 포함되는지 검증 (HOLD decision)."""
        request = _make_request()

        async def _mock_submit(*args: Any, **kwargs: Any) -> OrderRequestEntity:
            raise AssertionError("Broker should not be called for HOLD decisions")

        broker_stub = object()
        with patch.object(OrderManager, "submit_order_to_broker", _mock_submit):
            result = await hold_service.assemble_and_submit(
                request,
                order_manager=order_manager,
                broker=broker_stub,
            )

        assert result.status == "SKIPPED"
        assert len(result.phase_trace) > 0
        # sizing 단계에서 skipped 상태 확인 (HOLD decision은 sizing에서 skip됨)
        assert any(
            pt.status == "skipped" for pt in result.phase_trace
        ), f"No skipped phase in phase_trace: {result.phase_trace}"

    @pytest.mark.asyncio
    async def test_buy_duplicate_guard_records_guardrail_evaluation(
        self,
        service: DecisionOrchestratorService,
        order_manager: OrderManager,
        sample_request: SubmitOrderRequest,
        repos: Any,
    ) -> None:
        broker_stub = object()
        with patch.object(
            service._execution_service,  # type: ignore[attr-defined]
            "_has_recent_active_buy_order",
            AsyncMock(return_value=(True, "existing-order-1")),
        ):
            result = await service.assemble_and_submit(
                sample_request,
                order_manager=order_manager,
                broker=broker_stub,
            )

        assert result.status == "SKIPPED"
        assert result.stop_reason == "recent_active_buy_order"
        evaluations = list(repos.guardrail_evaluations._items.values())  # type: ignore[attr-defined]
        assert len(evaluations) == 1
        assert evaluations[0].rule_set_version == "buy_duplicate_guard_v1"
        assert evaluations[0].blocking_rule_codes == ["recent_active_buy_order"]

    @pytest.mark.asyncio
    async def test_sell_guard_records_guardrail_evaluation(
        self,
        repos: Any,
        order_manager: OrderManager,
    ) -> None:
        class _ReduceFDCAgent:
            @property
            def agent_name(self) -> str:
                return "final_decision_composer"

            @property
            def schema_version(self) -> str:
                return "1.0.0"

            async def run(self, request: AgentExecutionRequest) -> FinalDecisionComposerOutput:
                return FinalDecisionComposerOutput(
                    decision_type="REDUCE",
                    side="SELL",
                    symbol="005930",
                    confidence=0.8,
                    conviction=0.7,
                    summary="Reduce by test stub",
                )

        service = DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=_ReduceFDCAgent(),
        )
        request = _make_request(
            side=OrderSide.SELL,
            metadata={"source_type": "held_position"},
        )
        broker_stub = object()
        with patch(
            "agent_trading.services.execution_service.AvailableSellQtyResolver.resolve",
            AsyncMock(
                return_value=MagicMock(
                    is_blocked=True,
                    blocking_reason="duplicate sell blocked",
                    available_sell_qty=Decimal("0"),
                )
            ),
        ):
            result = await service.assemble_and_submit(
                request,
                order_manager=order_manager,
                broker=broker_stub,
            )

        assert result.status == "SKIPPED"
        assert result.stop_reason == "sell_guard_blocked"
        evaluations = list(repos.guardrail_evaluations._items.values())  # type: ignore[attr-defined]
        assert len(evaluations) == 1
        assert evaluations[0].rule_set_version == "sell_guard_v1"
        assert evaluations[0].blocking_rule_codes == ["sell_guard_blocked"]



# ---------------------------------------------------------------------------
# EXE-002: quote_resolution circuit breaker + cache 검증
# ---------------------------------------------------------------------------


class TestQuoteCircuitBreaker:
    """EXE-002: quote_resolution circuit breaker + cache 검증"""

    class _ApproveFDCAgent:
        """APPROVE를 반환하는 FDC agent stub."""

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

    class _ReduceSellFDCAgent:
        def __init__(self, *, source_symbol: str = "005930") -> None:
            self._source_symbol = source_symbol

        @property
        def agent_name(self) -> str:
            return "final_decision_composer"

        @property
        def schema_version(self) -> str:
            return "1.0.0"

        async def run(self, request: AgentExecutionRequest) -> FinalDecisionComposerOutput:
            return FinalDecisionComposerOutput(
                decision_type="REDUCE",
                side="SELL",
                symbol=self._source_symbol,
                confidence=0.8,
                conviction=0.7,
                summary="Reduce by test stub",
            )

    @pytest.fixture
    def repos(self) -> Any:
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)
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
        instrument = InstrumentEntity(
            instrument_id=uuid4(),
            symbol="005930",
            market_code="KRX",
            asset_class=AssetClass.KR_STOCK,
            currency="KRW",
            name="Samsung Electronics",
        )
        repos.instruments._items[instrument.instrument_id] = instrument
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
        return DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=self._ApproveFDCAgent(),
        )

    @pytest.fixture
    def order_manager(self, repos: Any) -> OrderManager:
        from agent_trading.services.reconciliation_service import ReconciliationService
        return OrderManager(
            repos=repos,
            reconciliation_service=ReconciliationService(repos=repos),
        )

    @pytest.mark.asyncio
    async def test_quote_cache_hit(
        self,
        service: DecisionOrchestratorService,
        order_manager: OrderManager,
    ) -> None:
        """동일 symbol 연속 호출 시 cache hit.

        MARKET order(price=None)로 quote_resolution 경로를 활성화하고,
        broker.get_quote()가 Quote를 반환하도록 mock한다.
        첫 번째 호출 → cache miss → get_quote() 호출.
        두 번째 호출 → cache hit (5s TTL 이내).
        """
        # MARKET order: price=None으로 quote resolution 경로 진입
        request = _make_request(price=None)

        submitted_entity = _make_order_entity(status=OrderStatus.SUBMITTED, request=request)

        async def _mock_submit(*args: Any, **kwargs: Any) -> OrderRequestEntity:
            return submitted_entity

        # get_quote()가 정상 Quote를 반환하도록 mock
        mock_quote = Quote(
            symbol="005930",
            market="KRX",
            bid=Decimal("50000"),
            ask=Decimal("50100"),
            last=Decimal("50050"),
            as_of=datetime.now(timezone.utc),
        )

        broker_mock = MagicMock()
        broker_mock.get_quote = AsyncMock(return_value=mock_quote)

        with patch.object(OrderManager, "submit_order_to_broker", _mock_submit):
            # 1st call — cache miss
            result1 = await service.assemble_and_submit(
                request,
                order_manager=order_manager,
                broker=broker_mock,
            )
            assert result1.status == "SUBMITTED"
            order_manager.repos.orders._items.clear()

            # 2nd call — should be cache hit (within 5s TTL)
            result2 = await service.assemble_and_submit(
                request,
                order_manager=order_manager,
                broker=broker_mock,
            )
            assert result2.status == "SUBMITTED"

        # 두 번째 호출에서 cache_hit phase trace 확인
        cache_hit_found = any(
            "cache_hit" in pt.status for pt in result2.phase_trace
        )
        assert cache_hit_found, (
            f"No cache_hit in phase_trace: {result2.phase_trace}"
        )

    @pytest.mark.asyncio
    async def test_core_reduce_sell_does_not_bypass_stale_snapshot_guard(
        self,
        repos: Any,
        order_manager: OrderManager,
    ) -> None:
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=1000)
        repos.cash_balance_snapshots._items = {
            snapshot_id: replace(cash_snapshot, snapshot_at=stale_time)
            for snapshot_id, cash_snapshot in repos.cash_balance_snapshots._items.items()
        }

        service = DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=self._ReduceSellFDCAgent(),
            stale_threshold_seconds=300,
        )
        request = _make_request(
            side=OrderSide.SELL,
            price=Decimal("50000"),
            metadata={"source_type": "core"},
        )
        broker_mock = MagicMock()
        broker_mock.submit_order = AsyncMock()

        result = await service.assemble_and_submit(
            request,
            order_manager=order_manager,
            broker=broker_mock,
        )

        assert result.status == "SKIPPED"
        assert result.error_phase == "stale_snapshot"
        assert result.stop_reason == "stale_snapshot"
        broker_mock.submit_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_held_position_reduce_sell_bypasses_stale_snapshot_guard(
        self,
        repos: Any,
        order_manager: OrderManager,
    ) -> None:
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=1000)
        repos.cash_balance_snapshots._items = {
            snapshot_id: replace(cash_snapshot, snapshot_at=stale_time)
            for snapshot_id, cash_snapshot in repos.cash_balance_snapshots._items.items()
        }

        service = DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=self._ReduceSellFDCAgent(),
            stale_threshold_seconds=300,
        )
        request = _make_request(
            side=OrderSide.SELL,
            price=Decimal("50000"),
            metadata={"source_type": "held_position"},
        )
        submitted_entity = _make_order_entity(status=OrderStatus.SUBMITTED, request=request)

        async def _mock_submit(*args: Any, **kwargs: Any) -> OrderRequestEntity:
            return submitted_entity

        broker_mock = MagicMock()
        broker_mock.submit_order = AsyncMock()

        with patch.object(OrderManager, "submit_order_to_broker", _mock_submit):
            result = await service.assemble_and_submit(
                request,
                order_manager=order_manager,
                broker=broker_mock,
            )

        assert result.status == "SUBMITTED"

    @pytest.mark.asyncio
    async def test_quote_circuit_breaker_after_failures(
        self,
        service: DecisionOrchestratorService,
        order_manager: OrderManager,
    ) -> None:
        """연속 quote 실패 → circuit breaker open.

        broker.get_quote()가 TimeoutError를 4회 발생시키고,
        4번째 호출에서 circuit_breaker_skip이 phase_trace에 기록되는지 검증.
        """
        request = _make_request(price=None)

        submitted_entity = _make_order_entity(status=OrderStatus.SUBMITTED, request=request)

        async def _mock_submit(*args: Any, **kwargs: Any) -> OrderRequestEntity:
            return submitted_entity

        broker_mock = MagicMock()
        broker_mock.get_quote = AsyncMock(side_effect=asyncio.TimeoutError("quote timeout"))

        with patch.object(OrderManager, "submit_order_to_broker", _mock_submit):
            for i in range(4):
                result = await service.assemble_and_submit(
                    request,
                    order_manager=order_manager,
                    broker=broker_mock,
                )
                # 실패해도 pipeline은 계속 진행 (empty quote fallback)
                assert result.status == "SUBMITTED", (
                    f"Call {i+1}: expected SUBMITTED, got {result.status}"
                )
                order_manager.repos.orders._items.clear()

        # 4번째 호출에서는 circuit_breaker_skip 확인
        circuit_breaker_found = any(
            "circuit_breaker_skip" in pt.status for pt in result.phase_trace
        )
        assert circuit_breaker_found, (
            f"No circuit_breaker_skip in phase_trace: {result.phase_trace}"
        )

    @pytest.mark.asyncio
    async def test_market_buy_quote_timeout_uses_price_band_fallback_for_sizing(
        self,
        repos: Any,
        order_manager: OrderManager,
    ) -> None:
        """MARKET BUY quote timeout 시 price band fallback으로 1주 고정을 피해야 함."""
        repos.position_snapshots._items.clear()
        request = _make_request(
            price=None,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
            price_band_lower=Decimal("49000"),
            price_band_upper=Decimal("51000"),
        )
        submitted_requests: list[SubmitOrderRequest] = []

        async def _mock_submit(
            _self: Any,
            order: OrderRequestEntity,
            _broker: Any,
            submit_request: SubmitOrderRequest,
            *_args: Any,
            **_kwargs: Any,
        ) -> OrderRequestEntity:
            submitted_requests.append(submit_request)
            return _make_order_entity(status=OrderStatus.SUBMITTED, request=submit_request)

        broker_mock = MagicMock()
        broker_mock.get_quote = AsyncMock(side_effect=asyncio.TimeoutError("quote timeout"))
        service = DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=self._ApproveFDCAgent(),
        )

        with patch.object(OrderManager, "submit_order_to_broker", _mock_submit):
            result = await service.assemble_and_submit(
                request,
                order_manager=order_manager,
                broker=broker_mock,
        )

        assert result.status == "SUBMITTED", f"Expected SUBMITTED, got {result.status}"
        assert len(submitted_requests) == 1
        assert submitted_requests[0].quantity == Decimal("4"), (
            f"Expected fallback-sized quantity 4, got "
            f"{submitted_requests[0].quantity}"
        )

    @pytest.mark.asyncio
    async def test_market_buy_quote_timeout_without_fallback_price_skips(
        self,
        repos: Any,
        order_manager: OrderManager,
    ) -> None:
        """MARKET BUY quote timeout + fallback price 부재 → 1주 제출 대신 skip."""
        repos.position_snapshots._items.clear()
        request = _make_request(
            price=None,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
            price_band_lower=None,
            price_band_upper=None,
        )

        async def _mock_submit(*args: Any, **kwargs: Any) -> OrderRequestEntity:
            raise AssertionError("Broker should not be called without a sizing reference price")

        broker_mock = MagicMock()
        broker_mock.get_quote = AsyncMock(side_effect=asyncio.TimeoutError("quote timeout"))
        service = DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=self._ApproveFDCAgent(),
        )

        with patch.object(OrderManager, "submit_order_to_broker", _mock_submit):
            result = await service.assemble_and_submit(
                request,
                order_manager=order_manager,
                broker=broker_mock,
            )

        assert result.status == "SKIPPED", f"Expected SKIPPED, got {result.status}"
        assert result.error_phase == "sizing"
        assert result.error_message == "missing_reference_price_for_market_buy"
        assert result.stop_reason == "missing_reference_price_for_market_buy"
