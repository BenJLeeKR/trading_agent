"""Replay 결정론적 검증 — 동일 입력 → 동일 출력.

목적
----
이 모듈은 backend engine의 결정론적 특성을 검증한다.
즉, 동일한 입력 상태가 주어졌을 때 ``assemble()``, ``calculate_sizing()``,
``build_submit_order_request_from_decision()``이 항상 동일한 결과를
생성하는지 확인한다.

범위 (사용자 피드백 반영)
-------------------------
- **검증 대상**: ``SizingResult.quantity``, ``SubmitOrderRequest`` 필드,
  ``SubmitResult.status`` — 모두 deterministic backend 영역
- **검증 제외**: broker 호출 결과 재현 (broker는 외부 시스템이므로 재현 대상 아님)
- **검증 제외**: AI agent 출력 재현 (LLM은 비결정론적)
- **검증 제외**: 전체 historical backtest (후속 작업)

핵심 설계
---------
1. ``assemble()``을 stub agent로 2회 호출하여 동일한 ``OrderIntent`` 출력 확인
2. ``calculate_sizing()``을 동일 ``SizingInputs``로 2회 호출하여 동일 결과 확인
3. ``build_submit_order_request_from_decision()``을 동일 ``OrderIntent``로
   2회 호출하여 동일 ``SubmitOrderRequest`` 확인
4. ``assemble_and_submit()``을 동일 입력으로 2회 호출하여 동일 최종 상태 확인
   (단, submit 결과는 mock broker이므로 status만 검증)
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
    CashBalanceSnapshotEntity,
    ConfigVersionEntity,
    InstrumentEntity,
    PositionSnapshotEntity,
    RiskLimitSnapshotEntity,
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
    build_submit_order_request_from_decision,
)
from agent_trading.services.order_manager import OrderManager
from agent_trading.services.reconciliation_service import ReconciliationService
from agent_trading.services.sizing_engine import (
    SizingInputs,
    SizingResult,
    calculate_sizing,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(**kwargs: object) -> SubmitOrderRequest:
    """Build a minimal ``SubmitOrderRequest`` for test use."""
    overrides: dict[str, object] = {
        "client_order_id": "REPLAY-TEST-001",
        "correlation_id": "corr-replay-001",
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


def _make_sizing_inputs(**overrides: object) -> SizingInputs:
    """Build a standard ``SizingInputs`` for replay testing."""
    defaults: dict[str, object] = {
        "decision_type": "BUY",
        "side": OrderSide.BUY,
        "requested_quantity": Decimal("10"),
        "requested_price": Decimal("50000"),
        "available_cash": Decimal("1000000"),
        "current_position_qty": Decimal("0"),
        "nav": Decimal("5000000"),
        "max_single_position_pct": Decimal("0.1"),
        "min_cash_buffer_pct": Decimal("0.05"),
        "max_order_value": Decimal("50000000"),
        "min_order_qty": Decimal("1"),
        "max_order_qty": Decimal("1000"),
        "lot_size": Decimal("1"),
    }
    defaults.update(overrides)
    return SizingInputs(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Suite
# ---------------------------------------------------------------------------


class TestReplayDeterministicSizing:
    """``calculate_sizing()`` 결정론적 검증.

    동일 ``SizingInputs`` → 항상 동일 ``SizingResult``.
    """

    @pytest.mark.asyncio
    async def test_replay_sizing_identity(self) -> None:
        """동일 SizingInputs로 2회 호출 → 동일 SizingResult."""
        inputs = _make_sizing_inputs()

        result1 = calculate_sizing(inputs)
        result2 = calculate_sizing(inputs)

        assert result1.quantity == result2.quantity, (
            f"Sizing quantity mismatch: {result1.quantity} vs {result2.quantity}"
        )
        assert result1.applied_constraints == result2.applied_constraints, (
            f"Sizing constraints mismatch: {result1.applied_constraints} "
            f"vs {result2.applied_constraints}"
        )
        assert result1.skip_reason == result2.skip_reason, (
            f"Sizing skip_reason mismatch: {result1.skip_reason} "
            f"vs {result2.skip_reason}"
        )

    @pytest.mark.asyncio
    async def test_replay_sizing_cash_constraint(self) -> None:
        """Cash constraint 적용 시에도 결정론적 결과."""
        inputs = _make_sizing_inputs(
            available_cash=Decimal("1000"),  # 매우 적은 현금
            requested_quantity=Decimal("100"),
            requested_price=Decimal("50000"),  # 5M KRW 필요 → cash 부족
        )

        result1 = calculate_sizing(inputs)
        result2 = calculate_sizing(inputs)

        assert result1.quantity == result2.quantity
        assert "cash_limit" in result1.applied_constraints
        assert result1.applied_constraints == result2.applied_constraints

    @pytest.mark.asyncio
    async def test_replay_sizing_zero_quantity(self) -> None:
        """Zero quantity 결과도 결정론적."""
        inputs = _make_sizing_inputs(
            available_cash=Decimal("100"),
            requested_quantity=Decimal("1"),
            requested_price=Decimal("1000000"),  # 1M KRW → cash 부족
            min_order_qty=Decimal("10"),  # 최소 주문량 10 → 1 < 10
        )

        result1 = calculate_sizing(inputs)
        result2 = calculate_sizing(inputs)

        assert result1.quantity == Decimal("0")
        assert result2.quantity == Decimal("0")
        assert result1.skip_reason == result2.skip_reason


class TestReplayDeterministicBuildSubmitRequest:
    """``build_submit_order_request_from_decision()`` 결정론적 검증.

    동일 ``OrderIntent`` → 항상 동일 ``SubmitOrderRequest`` (또는 ``None``).
    """

    @pytest.fixture
    def repos(self) -> RepositoryContainer:
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

        return repos

    class _ApproveStubFDC:
        """APPROVE 반환 stub — build_submit_order_request가 None을 반환하지 않도록."""

        @property
        def agent_name(self) -> str:
            return "final_decision_composer"

        @property
        def schema_version(self) -> str:
            return "1.0.0"

        async def run(self, request: object) -> object:
            from agent_trading.services.ai_agents.schemas import (
                FinalDecisionComposerOutput,
            )
            return FinalDecisionComposerOutput(
                decision_type="APPROVE",
                side="BUY",
                symbol="005930",
                confidence=0.8,
                conviction=0.7,
                summary="Replay test stub",
            )

    @pytest.mark.asyncio
    async def test_replay_build_request_identity(
        self,
        repos: RepositoryContainer,
    ) -> None:
        """동일 OrderIntent로 2회 호출 → 동일 SubmitOrderRequest."""
        request = _make_request()
        service = DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=self._ApproveStubFDC(),
        )
        intent = await service.assemble(request)

        submit1 = build_submit_order_request_from_decision(intent)
        submit2 = build_submit_order_request_from_decision(intent)

        assert submit1 is not None
        assert submit2 is not None
        assert submit1.client_order_id == submit2.client_order_id
        assert submit1.quantity == submit2.quantity
        assert submit1.side == submit2.side
        assert submit1.price == submit2.price
        assert submit1.symbol == submit2.symbol

    @pytest.mark.asyncio
    async def test_replay_build_request_hold_returns_none(
        self,
        repos: RepositoryContainer,
    ) -> None:
        """HOLD 결정 → 항상 None 반환 (결정론적)."""
        request = _make_request()

        class _HoldFDCAgent:
            @property
            def agent_name(self) -> str:
                return "final_decision_composer"

            @property
            def schema_version(self) -> str:
                return "1.0.0"

            async def run(self, _request: object) -> object:
                from agent_trading.services.ai_agents.schemas import (
                    FinalDecisionComposerOutput,
                )
                return FinalDecisionComposerOutput(
                    decision_type="HOLD",
                    side="BUY",
                    symbol="005930",
                    confidence=0.0,
                    conviction=0.0,
                    summary="HOLD",
                )

        service = DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=_HoldFDCAgent(),
        )
        intent = await service.assemble(request)

        submit1 = build_submit_order_request_from_decision(intent)
        submit2 = build_submit_order_request_from_decision(intent)

        assert submit1 is None
        assert submit2 is None


class TestReplayDeterministicAssemble:
    """``assemble()`` 결정론적 검증 (동일 stub agent → 동일 OrderIntent).

    AI agent는 stub으로 대체하여 비결정론적 요소 제거.
    """

    class _StubFDC:
        """APPROVE 반환 stub — 항상 동일 출력."""

        @property
        def agent_name(self) -> str:
            return "final_decision_composer"

        @property
        def schema_version(self) -> str:
            return "1.0.0"

        async def run(self, request: object) -> object:
            from agent_trading.services.ai_agents.schemas import (
                FinalDecisionComposerOutput,
            )
            return FinalDecisionComposerOutput(
                decision_type="APPROVE",
                side="BUY",
                symbol="005930",
                confidence=0.8,
                conviction=0.7,
                summary="Replay test stub",
            )

    @pytest.fixture
    def repos(self) -> RepositoryContainer:
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

        return repos

    @pytest.mark.asyncio
    async def test_replay_assemble_identity(
        self,
        repos: RepositoryContainer,
    ) -> None:
        """동일 입력으로 assemble() 2회 → 동일 OrderIntent 결정론적 결정."""
        request1 = _make_request(client_order_id="REPLAY-ASSEMBLE-001")
        request2 = _make_request(client_order_id="REPLAY-ASSEMBLE-001")

        service = DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=self._StubFDC(),
        )

        intent1 = await service.assemble(request1)
        intent2 = await service.assemble(request2)

        assert intent1 is not None
        assert intent2 is not None
        assert intent1.ai_backend_inputs.decision_type == "APPROVE"
        assert intent1.ai_backend_inputs.decision_type == intent2.ai_backend_inputs.decision_type
        assert intent1.request.side == intent2.request.side
        assert intent1.request.quantity == intent2.request.quantity
        assert intent1.request.price == intent2.request.price

    @pytest.mark.asyncio
    async def test_replay_assemble_with_sizing(
        self,
        repos: RepositoryContainer,
    ) -> None:
        """동일 입력 → 동일 sizing 결과.

        assemble() 결과에 sizing engine을 적용해도 항상 동일한
        ``SizingResult.quantity``가 나와야 함.
        """
        request = _make_request(client_order_id="REPLAY-SIZING-001")

        service = DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=self._StubFDC(),
        )

        intent = await service.assemble(request)
        sizing_inputs = service._build_sizing_inputs(intent)

        # 동일 SizingInputs로 2회 실행
        result1 = calculate_sizing(sizing_inputs)
        result2 = calculate_sizing(sizing_inputs)

        assert result1.quantity == result2.quantity, (
            f"Sizing replay mismatch: {result1.quantity} vs {result2.quantity}"
        )
        assert result1.applied_constraints == result2.applied_constraints, (
            f"Constraints replay mismatch: {result1.applied_constraints} "
            f"vs {result2.applied_constraints}"
        )


class TestReplayDeterministicPipeline:
    """``assemble_and_submit()`` 결정론적 pipeline 검증.

    동일 입력 → 동일 ``SubmitResult`` (mock broker 사용).
    """

    class _StubFDC:
        @property
        def agent_name(self) -> str:
            return "final_decision_composer"

        @property
        def schema_version(self) -> str:
            return "1.0.0"

        async def run(self, request: object) -> object:
            from agent_trading.services.ai_agents.schemas import (
                FinalDecisionComposerOutput,
            )
            return FinalDecisionComposerOutput(
                decision_type="APPROVE",
                side="BUY",
                symbol="005930",
                confidence=0.8,
                conviction=0.7,
                summary="Replay pipeline stub",
            )

    @pytest.fixture
    def repos(self) -> RepositoryContainer:
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

        return repos

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
        broker = MagicMock(spec=BrokerAdapter)
        broker.submit_order = AsyncMock()
        return broker

    @pytest.mark.asyncio
    async def test_replay_pipeline_status_identity(
        self,
        repos: RepositoryContainer,
        order_manager: OrderManager,
        mock_broker: BrokerAdapter,
    ) -> None:
        """동일 pipeline 입력 → 동일 SubmitResult.status (SUBMITTED)."""
        request = _make_request(client_order_id="REPLAY-PIPELINE-STATUS-001")
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="REPLAY-PIPELINE-STATUS-001",
            broker_order_id="BRK-REPLAY-001",
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="0000",
            raw_message="Accepted",
        )

        service = DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=self._StubFDC(),
        )

        result1 = await service.assemble_and_submit(
            request,
            order_manager=order_manager,
            broker=mock_broker,  # type: ignore[arg-type]
        )
        # Reset mock for second call (but it won't be called again due to
        # duplicate client_order_id protection in Phase 3)

        # Create fresh repos/manager for second run
        repos2 = build_in_memory_repositories()
        now = datetime.now(timezone.utc)
        account = list(repos.accounts._items.values())[0]
        repos2.accounts._items[account.account_id] = account
        config_version = list(repos.config_versions._items.values())[0]
        repos2.config_versions._items[config_version.config_version_id] = config_version
        instrument = list(repos.instruments._items.values())[0]
        repos2.instruments._items[instrument.instrument_id] = instrument

        mock_broker2 = MagicMock(spec=BrokerAdapter)
        mock_broker2.submit_order = AsyncMock()
        mock_broker2.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="REPLAY-PIPELINE-STATUS-001",
            broker_order_id="BRK-REPLAY-002",
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="0000",
            raw_message="Accepted",
        )

        rs2 = ReconciliationService(repos2)
        om2 = OrderManager(repos=repos2, reconciliation_service=rs2)

        service2 = DecisionOrchestratorService(
            repos=repos2,
            final_decision_agent=self._StubFDC(),
        )

        result2 = await service2.assemble_and_submit(
            request,
            order_manager=om2,
            broker=mock_broker2,  # type: ignore[arg-type]
        )

        # Both should be SUBMITTED (same input → same result status)
        assert result1.status == "SUBMITTED", (
            f"First run: expected SUBMITTED, got {result1.status}"
        )
        assert result2.status == "SUBMITTED", (
            f"Second run: expected SUBMITTED, got {result2.status}"
        )

    @pytest.mark.asyncio
    async def test_replay_pipeline_hold_identity(
        self,
        repos: RepositoryContainer,
        order_manager: OrderManager,
        mock_broker: BrokerAdapter,
    ) -> None:
        """HOLD 결정 → 2회 모두 SKIPPED (결정론적)."""
        request = _make_request(client_order_id="REPLAY-HOLD-001")

        class _HoldFDC:
            @property
            def agent_name(self) -> str:
                return "final_decision_composer"

            @property
            def schema_version(self) -> str:
                return "1.0.0"

            async def run(self, _request: object) -> object:
                from agent_trading.services.ai_agents.schemas import (
                    FinalDecisionComposerOutput,
                )
                return FinalDecisionComposerOutput(
                    decision_type="HOLD",
                    side="BUY",
                    symbol="005930",
                    confidence=0.0,
                    conviction=0.0,
                    summary="HOLD",
                )

        service = DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=_HoldFDC(),
        )

        result1 = await service.assemble_and_submit(
            request,
            order_manager=order_manager,
            broker=mock_broker,  # type: ignore[arg-type]
        )

        # Create fresh repos/manager for second run
        repos2 = build_in_memory_repositories()
        now = datetime.now(timezone.utc)
        account = list(repos.accounts._items.values())[0]
        repos2.accounts._items[account.account_id] = account
        config_version = list(repos.config_versions._items.values())[0]
        repos2.config_versions._items[config_version.config_version_id] = config_version
        instrument = list(repos.instruments._items.values())[0]
        repos2.instruments._items[instrument.instrument_id] = instrument

        mock_broker2 = MagicMock(spec=BrokerAdapter)
        mock_broker2.submit_order = AsyncMock()

        rs2 = ReconciliationService(repos2)
        om2 = OrderManager(repos=repos2, reconciliation_service=rs2)

        service2 = DecisionOrchestratorService(
            repos=repos2,
            final_decision_agent=_HoldFDC(),
        )

        result2 = await service2.assemble_and_submit(
            request,
            order_manager=om2,
            broker=mock_broker2,  # type: ignore[arg-type]
        )

        assert result1.status == "SKIPPED", (
            f"First run: expected SKIPPED, got {result1.status}"
        )
        assert result2.status == "SKIPPED", (
            f"Second run: expected SKIPPED, got {result2.status}"
        )
        mock_broker.submit_order.assert_not_called()
        mock_broker2.submit_order.assert_not_called()
