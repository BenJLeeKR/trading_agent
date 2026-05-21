"""Replay 결정론적 검증 — 동일 입력 → 동일 출력.

목적
----
이 모듈은 backend engine의 결정론적 특성을 검증한다.
즉, 동일한 입력 상태가 주어졌을 때 ``assemble()``, ``calculate_sizing()``,
``build_submit_order_request_from_decision()``, ``assemble_and_submit()``이
항상 동일한 결과를 생성하는지 확인한다.

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
5. ``ReplayBundle`` parametrize 테스트로 5개 시나리오 결정론적 검증
   (REDUCE/EXIT/stale guard/cash constraint 포함)

리팩터 노트
-----------
- 공유 헬퍼(``_make_request``, ``_make_sizing_inputs``, ``_build_repos``,
  ``_make_stub_fdc``, ``ReplayBundle``, ``REPLAY_SCENARIOS``)는
  ``replay_test_harness.py``에서 import.
- 3개 중복 ``repos`` fixture를 ``_build_repos()`` 호출로 대체.
- 3개 중복 ``_StubFDC`` 클래스를 ``_make_stub_fdc()`` 호출로 대체.
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
)
from agent_trading.domain.enums import BrokerName, Environment, OrderSide, OrderStatus
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
from tests.services.replay_test_harness import (
    REPLAY_SCENARIOS,
    ReplayBundle,
    _build_repos,
    _make_request,
    _make_sizing_inputs,
    _make_stub_fdc,
)

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
        return _build_repos(
            seed_cash=Decimal("1000000"),
            seed_position_qty=Decimal("10"),
        )

    @pytest.mark.asyncio
    async def test_replay_build_request_identity(
        self,
        repos: RepositoryContainer,
    ) -> None:
        """동일 OrderIntent로 2회 호출 → 동일 SubmitOrderRequest."""
        request = _make_request(client_order_id="REPLAY-BUILD-001")
        service = DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=_make_stub_fdc(),  # type: ignore[arg-type]
            use_subprocess_isolation=False,
        )
        intent = await service.assemble(request)

        # Pass explicit client_order_id from the request to avoid
        # timestamp-based auto-generation (which is non-deterministic
        # at microsecond precision).
        explicit_cid = intent.request.client_order_id
        submit1 = build_submit_order_request_from_decision(intent, client_order_id=explicit_cid)
        submit2 = build_submit_order_request_from_decision(intent, client_order_id=explicit_cid)

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
        hold_fdc = _make_stub_fdc(decision_type="HOLD", confidence=0.0, conviction=0.0, summary="HOLD")
        service = DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=hold_fdc,  # type: ignore[arg-type]
            use_subprocess_isolation=False,
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

    @pytest.fixture
    def repos(self) -> RepositoryContainer:
        return _build_repos(
            seed_cash=Decimal("1000000"),
            seed_position_qty=Decimal("10"),
        )

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
            final_decision_agent=_make_stub_fdc(),  # type: ignore[arg-type]
            use_subprocess_isolation=False,
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
            final_decision_agent=_make_stub_fdc(),  # type: ignore[arg-type]
            use_subprocess_isolation=False,
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

    @pytest.fixture
    def repos(self) -> RepositoryContainer:
        return _build_repos(
            seed_cash=Decimal("1000000"),
            seed_position_qty=Decimal("10"),
        )

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
            final_decision_agent=_make_stub_fdc(),  # type: ignore[arg-type]
            use_subprocess_isolation=False,
        )

        result1 = await service.assemble_and_submit(
            request,
            order_manager=order_manager,
            broker=mock_broker,  # type: ignore[arg-type]
        )

        # Create fresh repos/manager for second run
        repos2 = _build_repos(
            seed_cash=Decimal("1000000"),
            seed_position_qty=Decimal("10"),
        )

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
            final_decision_agent=_make_stub_fdc(),  # type: ignore[arg-type]
            use_subprocess_isolation=False,
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
        hold_fdc = _make_stub_fdc(decision_type="HOLD", confidence=0.0, conviction=0.0, summary="HOLD")

        service = DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=hold_fdc,  # type: ignore[arg-type]
        )

        result1 = await service.assemble_and_submit(
            request,
            order_manager=order_manager,
            broker=mock_broker,  # type: ignore[arg-type]
        )

        # Create fresh repos/manager for second run
        repos2 = _build_repos(
            seed_cash=Decimal("1000000"),
            seed_position_qty=Decimal("10"),
        )

        mock_broker2 = MagicMock(spec=BrokerAdapter)
        mock_broker2.submit_order = AsyncMock()

        rs2 = ReconciliationService(repos2)
        om2 = OrderManager(repos=repos2, reconciliation_service=rs2)

        service2 = DecisionOrchestratorService(
            repos=repos2,
            final_decision_agent=hold_fdc,  # type: ignore[arg-type]
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


# ---------------------------------------------------------------------------
# Parametrized replay scenarios
# ---------------------------------------------------------------------------


class TestReplayDeterministicParametrized:
    """``assemble_and_submit()`` 결정론적 검증 — parametrized scenarios.

    ``REPLAY_SCENARIOS`` 리스트를 ``@pytest.mark.parametrize``로 전달하여
    각 시나리오별로 동일 입력 → 동일 출력을 검증한다.

    시나리오 naming convention:
    - ``_submit``: pipeline이 broker submission까지 진행
    - ``_guard``: pipeline이 guardrail(Phase 4c)에서 중단
    """

    @pytest.mark.parametrize(
        "bundle",
        REPLAY_SCENARIOS,
        ids=lambda b: b.name,
    )
    @pytest.mark.asyncio
    async def test_replay_scenario(
        self,
        bundle: ReplayBundle,
    ) -> None:
        """동일 ReplayBundle → 결정론적 결과."""
        # ── Given ──
        mock_broker = MagicMock(spec=BrokerAdapter)
        mock_broker.submit_order = AsyncMock()
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id=bundle.request.client_order_id,
            broker_order_id="BRK-REPLAY-001",
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="0000",
            raw_message="Accepted",
        )

        rs = ReconciliationService(bundle.repos)
        om = OrderManager(repos=bundle.repos, reconciliation_service=rs)

        service = DecisionOrchestratorService(
            repos=bundle.repos,
            final_decision_agent=bundle.stub_fdc,  # type: ignore[arg-type]
            use_subprocess_isolation=False,
        )

        # ── When ──
        result = await service.assemble_and_submit(
            bundle.request,
            order_manager=om,
            broker=mock_broker,  # type: ignore[arg-type]
        )

        # ── Then: status ──
        assert result.status == bundle.expected_status, (
            f"[{bundle.name}] Expected status {bundle.expected_status}, "
            f"got {result.status}"
        )

        # ── Then: quantity ──
        # NOTE: Pipeline creates the Order at Phase 4b (before guardrail).
        # For guard-blocked scenarios (Phase 4c blocks), result.order is NOT
        # None — the order exists in PENDING_SUBMIT status.  We only verify
        # quantity when a submit scenario expects it.
        if bundle.expected_quantity is not None:
            assert result.order is not None, (
                f"[{bundle.name}] Expected order but got None"
            )
            assert result.order.requested_quantity == bundle.expected_quantity, (
                f"[{bundle.name}] Expected qty {bundle.expected_quantity}, "
                f"got {result.order.requested_quantity}"
            )

        # ── Then: guardrail rule ──
        if bundle.expected_guardrail_rule is not None:
            assert result.decision_context_id is not None, (
                f"[{bundle.name}] Expected decision_context_id for guardrail lookup"
            )
            guardrails = await bundle.repos.guardrail_evaluations.get_by_decision_context(
                result.decision_context_id
            )
            matching = [
                g for g in guardrails
                if g.blocking_rule_codes is not None
                and bundle.expected_guardrail_rule in g.blocking_rule_codes
            ]
            assert matching, (
                f"[{bundle.name}] Expected guardrail {bundle.expected_guardrail_rule}, "
                f"found: {[g.blocking_rule_codes for g in guardrails]}"
            )

        # ── Then: submit vs guard 분리 ──
        # _submit 시나리오: broker.submit_order()가 1회 호출되어야 함
        # _guard 시나리오: broker.submit_order()가 0회 호출되어야 함
        if bundle.name.endswith("_submit"):
            assert mock_broker.submit_order.await_count == 1, (
                f"[{bundle.name}] Submit scenario: expected 1 submit call, "
                f"got {mock_broker.submit_order.await_count}"
            )
        elif bundle.name.endswith("_guard"):
            assert mock_broker.submit_order.await_count == 0, (
                f"[{bundle.name}] Guard scenario: expected 0 submit calls, "
                f"got {mock_broker.submit_order.await_count}"
            )
        else:
            # Fallback: use expected_submit_call_count
            assert mock_broker.submit_order.await_count == bundle.expected_submit_call_count, (
                f"[{bundle.name}] Expected {bundle.expected_submit_call_count} submit calls, "
                f"got {mock_broker.submit_order.await_count}"
            )

    @pytest.mark.parametrize(
        "bundle",
        REPLAY_SCENARIOS,
        ids=lambda b: b.name,
    )
    @pytest.mark.asyncio
    async def test_replay_scenario_second_run_identity(
        self,
        bundle: ReplayBundle,
    ) -> None:
        """동일 ReplayBundle을 fresh repos로 2회 실행 → 동일 status.

        2회차에도 동일한 ``SubmitResult.status``가 나오는지 검증하여
        결정론적 특성을 확인한다.

        Note: bundle.repos는 이전 parametrized 테스트에서 mutate되었을 수
        있으므로(OrderRequestEntity 등이 추가됨), 첫 번째 실행에서도
        ``_build_repos()``로 fresh repos를 생성하여 사용한다.
        """
        # ── First run (fresh repos, same inputs) ──
        repos1 = _build_repos(
            seed_cash=bundle.repos.cash_balance_snapshots._items[
                next(iter(bundle.repos.cash_balance_snapshots._items), None)
            ].available_cash if bundle.repos.cash_balance_snapshots._items else None,
            seed_position_qty=next(
                (p.quantity for p in bundle.repos.position_snapshots._items.values()),
                None,
            ),
        )
        mock_broker1 = MagicMock(spec=BrokerAdapter)
        mock_broker1.submit_order = AsyncMock()
        mock_broker1.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id=bundle.request.client_order_id,
            broker_order_id="BRK-REPLAY-001",
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="0000",
            raw_message="Accepted",
        )
        rs1 = ReconciliationService(repos1)
        om1 = OrderManager(repos=repos1, reconciliation_service=rs1)
        service1 = DecisionOrchestratorService(
            repos=repos1,
            final_decision_agent=bundle.stub_fdc,  # type: ignore[arg-type]
            use_subprocess_isolation=False,
        )
        result1 = await service1.assemble_and_submit(
            bundle.request,
            order_manager=om1,
            broker=mock_broker1,  # type: ignore[arg-type]
        )

        # ── Second run (fresh repos, same inputs) ──
        repos2 = _build_repos(
            seed_cash=bundle.repos.cash_balance_snapshots._items[
                next(iter(bundle.repos.cash_balance_snapshots._items), None)
            ].available_cash if bundle.repos.cash_balance_snapshots._items else None,
            seed_position_qty=next(
                (p.quantity for p in bundle.repos.position_snapshots._items.values()),
                None,
            ),
        )
        mock_broker2 = MagicMock(spec=BrokerAdapter)
        mock_broker2.submit_order = AsyncMock()
        mock_broker2.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id=bundle.request.client_order_id,
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
            final_decision_agent=bundle.stub_fdc,  # type: ignore[arg-type]
            use_subprocess_isolation=False,
        )
        result2 = await service2.assemble_and_submit(
            bundle.request,
            order_manager=om2,
            broker=mock_broker2,  # type: ignore[arg-type]
        )

        # ── Then: same status ──
        assert result1.status == result2.status, (
            f"[{bundle.name}] Status mismatch: {result1.status} vs {result2.status}"
        )
        assert result1.status == bundle.expected_status, (
            f"[{bundle.name}] Expected {bundle.expected_status}, "
            f"got {result1.status}"
        )
