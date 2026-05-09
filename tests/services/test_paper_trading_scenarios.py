"""사용자 통합테스트 시나리오 — Paper Trading Loop E2E 검증.

이 모듈은 5가지 사용자 시나리오를 자동화하여 paper trading loop의
운영 검증을 제공합니다.

시나리오
--------
1. 정상 진입 승인 → SUBMITTED
2. HOLD/WATCH → SKIPPED (미제출)
3. Uncertain Response → RECONCILE_REQUIRED + Lock
4. Stale Snapshot / Health Degraded → Submit 차단
5. Duplicate Lock + 재시도 차단 → broker 1회만 호출

핵심 설계 원칙
--------------
- ``test_safe_order_path_e2e.py``의 fixture 구조 재사용
- 각 시나리오는 독립적으로 실행 가능
- broker submit semantics 변경 금지 (fake broker adapter 사용)
- hard guardrail / reconciliation 경계 변경 금지
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
    SnapshotSyncRunEntity,
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
from agent_trading.repositories.filters import OrderQuery
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.decision_orchestrator import (
    DecisionOrchestratorService,
)
from agent_trading.services.order_manager import OrderManager
from agent_trading.services.reconciliation_service import ReconciliationService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(**kwargs: object) -> SubmitOrderRequest:
    """Build a minimal ``SubmitOrderRequest`` for test use."""
    overrides: dict[str, object] = {
        "client_order_id": "PAPER-SCENARIO-001",
        "correlation_id": "corr-paper-001",
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


class TestPaperTradingScenarios:
    """사용자 통합테스트 시나리오 — paper trading loop 검증."""

    # ── Custom FDC agent ──

    class _ApproveFDCAgent:
        """APPROVE를 반환하는 FDC agent (pipeline 진행용)."""

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
                summary="Approved by paper trading scenario test stub",
            )

    class _HoldFDCAgent:
        """HOLD를 반환하는 FDC agent (skip 검증용)."""

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
                decision_type="HOLD",
                side="BUY",
                symbol="005930",
                confidence=0.0,
                conviction=0.0,
                summary="HOLD — no action recommended",
            )

    # ── Fixtures ──

    @pytest.fixture
    def repos(self) -> RepositoryContainer:
        """Seed in-memory repos with account, config version, instrument."""
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
        """Return a MagicMock that looks like a BrokerAdapter."""
        broker = MagicMock(spec=BrokerAdapter)
        broker.submit_order = AsyncMock()
        return broker

    # ═════════════════════════════════════════════════════════════════════
    # Scenario 1: 정상 진입 승인 → SUBMITTED
    # ═════════════════════════════════════════════════════════════════════

    @pytest.mark.asyncio
    async def test_scenario_1_happy_path_submitted(
        self,
        repos: RepositoryContainer,
        order_manager: OrderManager,
        mock_broker: BrokerAdapter,
    ) -> None:
        """정상 진입 승인 → 제출 완료.

        Given:  account has sufficient cash, no blocking lock
        When:   submit request with BUY decision
        Then:   pipeline returns SUBMITTED
                order status = SUBMITTED
                broker called exactly once
                trade_decision_id present
                decision_context_id present
                audit log contains order.create + status changes
        """
        # Given
        # Seed fresh snapshots (for account-level Phase 4c guard)
        now = datetime.now(timezone.utc)
        account = list(repos.accounts._items.values())[0]
        instrument = list(repos.instruments._items.values())[0]
        cash_snapshot = CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=account.account_id,
            currency="KRW",
            available_cash=Decimal("1000000"),
            settled_cash=Decimal("0"),
            unsettled_cash=Decimal("0"),
            source_of_truth="broker",
            snapshot_at=now,
        )
        await repos.cash_balance_snapshots.add(cash_snapshot)
        position_snapshot = PositionSnapshotEntity(
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
        await repos.position_snapshots.add(position_snapshot)

        request = _make_request(client_order_id="SCENARIO-1-HAPPY-001")
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="SCENARIO-1-HAPPY-001",
            broker_order_id="BRK-SCENARIO-1-001",
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="0000",
            raw_message="Accepted",
        )

        service = DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=self._ApproveFDCAgent(),
        )

        # When
        result = await service.assemble_and_submit(
            request,
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

        # Traceability 검증
        assert result.trade_decision_id is not None, (
            "trade_decision_id must be present for traceability"
        )
        assert result.decision_context_id is not None, (
            "decision_context_id must be present for traceability"
        )
        if result.intent is not None:
            assert result.decision_context_id == result.intent.decision_context_id, (
                "SubmitResult.decision_context_id must match intent"
            )

        # Audit log 검증: order.create 이벤트 존재
        orders = await repos.orders.list(OrderQuery(correlation_id=request.correlation_id))
        assert len(orders) >= 1, "At least one order should exist"
        audit_entries = await repos.audit_logs.list_by_correlation_id(
            request.correlation_id
        )
        assert len(audit_entries) >= 1, (
            "Audit log should contain entries for the order lifecycle"
        )

    # ═════════════════════════════════════════════════════════════════════
    # Scenario 2: HOLD/WATCH → 미제출 (SKIPPED)
    # ═════════════════════════════════════════════════════════════════════

    @pytest.mark.asyncio
    async def test_scenario_2_hold_skipped(
        self,
        repos: RepositoryContainer,
        order_manager: OrderManager,
        mock_broker: BrokerAdapter,
    ) -> None:
        """HOLD/WATCH → 미제출 (SKIPPED).

        Given:  FDC agent returns HOLD decision_type
        When:   submit request
        Then:   pipeline returns SKIPPED
                no order created
                broker NOT called
                no blocking lock acquired
        """
        # Given: HOLD FDC agent
        request = _make_request(client_order_id="SCENARIO-2-HOLD-001")
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="SCENARIO-2-HOLD-001",
            broker_order_id="SHOULD-NOT-BE-CALLED",
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
        )

        service = DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=self._HoldFDCAgent(),
        )

        # When
        result = await service.assemble_and_submit(
            request,
            order_manager=order_manager,
            broker=mock_broker,  # type: ignore[arg-type]
        )

        # Then
        assert result.status == "SKIPPED", (
            f"Expected SKIPPED for HOLD decision, got {result.status}"
        )
        assert result.intent is not None
        assert result.order is None, "No order should be created for HOLD decision"
        mock_broker.submit_order.assert_not_called()

        # No blocking lock acquired
        account = list(repos.accounts._items.values())[0]
        rs = ReconciliationService(repos)
        is_blocked = await rs.is_blocked(
            account_id=account.account_id,
            symbol=request.symbol,
            side=request.side.value,
        )
        assert not is_blocked, (
            "No blocking lock should exist for HOLD decision"
        )

    # ═════════════════════════════════════════════════════════════════════
    # Scenario 3: Uncertain Response → RECONCILE_REQUIRED + Lock
    # ═════════════════════════════════════════════════════════════════════

    @pytest.mark.asyncio
    async def test_scenario_3_uncertain_reconcile(
        self,
        repos: RepositoryContainer,
        order_manager: OrderManager,
        mock_broker: BrokerAdapter,
    ) -> None:
        """Uncertain Response → RECONCILE_REQUIRED + Lock.

        Given:  broker returns uncertain=True (timeout / missing broker_order_id)
        When:   submit request
        Then:   pipeline returns RECONCILE_REQUIRED
                order status = RECONCILE_REQUIRED
                blocking lock acquired
                second submit attempt blocked (broker NOT called)
                lock persists until resolved
        """
        # Given: broker returns uncertain result
        # Seed fresh snapshots (for account-level Phase 4c guard)
        now = datetime.now(timezone.utc)
        account = list(repos.accounts._items.values())[0]
        instrument = list(repos.instruments._items.values())[0]
        cash_snapshot = CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=account.account_id,
            currency="KRW",
            available_cash=Decimal("1000000"),
            settled_cash=Decimal("0"),
            unsettled_cash=Decimal("0"),
            source_of_truth="broker",
            snapshot_at=now,
        )
        await repos.cash_balance_snapshots.add(cash_snapshot)
        position_snapshot = PositionSnapshotEntity(
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
        await repos.position_snapshots.add(position_snapshot)

        request = _make_request(client_order_id="SCENARIO-3-UNCERTAIN-001")
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="SCENARIO-3-UNCERTAIN-001",
            broker_order_id=None,  # Missing → uncertain
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="TIMEOUT",
            raw_message="Response timeout",
            uncertain=True,
            requires_reconciliation=False,
        )

        service = DecisionOrchestratorService(
            repos=repos,
            final_decision_agent=self._ApproveFDCAgent(),
        )
        rs = ReconciliationService(repos)

        # When — first call: uncertain
        result = await service.assemble_and_submit(
            request,
            order_manager=order_manager,
            broker=mock_broker,  # type: ignore[arg-type]
        )

        # Then — verify first call result
        assert result.status == "RECONCILE_REQUIRED", (
            f"Expected RECONCILE_REQUIRED, got {result.status}"
        )
        assert result.intent is not None
        assert result.order is not None
        assert result.order.status == OrderStatus.RECONCILE_REQUIRED
        assert result.order.status_reason_code == "TIMEOUT"
        mock_broker.submit_order.assert_awaited_once()

        # Blocking lock 검증
        assert result.order.account_id is not None
        is_blocked = await rs.is_blocked(
            account_id=result.order.account_id,
            symbol=request.symbol,
            side=request.side.value,
        )
        assert is_blocked, (
            "Blocking lock should exist after uncertain result"
        )

        # When — second call: should be blocked by lock
        second_request = _make_request(
            client_order_id="SCENARIO-3-UNCERTAIN-002"
        )
        mock_broker.submit_order.reset_mock()
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="SCENARIO-3-UNCERTAIN-002",
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

        # Then — verify second call blocked
        assert result2.status == "RECONCILE_REQUIRED", (
            f"Second call: expected RECONCILE_REQUIRED (blocked), "
            f"got {result2.status}"
        )
        assert result2.order is not None
        assert result2.order.status_reason_code == "BLOCKED", (
            f"Second call: expected BLOCKED reason_code, "
            f"got {result2.order.status_reason_code}"
        )
        mock_broker.submit_order.assert_not_called()

        # Lock still exists
        account = list(repos.accounts._items.values())[0]
        lock_still_exists = await rs.is_blocked(
            account_id=account.account_id,
            symbol=second_request.symbol,
            side=second_request.side.value,
        )
        assert lock_still_exists, (
            "Blocking lock should still exist after second blocked call"
        )

    # ═════════════════════════════════════════════════════════════════════
    # Scenario 4: Stale Snapshot / Health Degraded → Submit 차단
    # ═════════════════════════════════════════════════════════════════════

    @pytest.mark.asyncio
    async def test_scenario_4_stale_snapshot_guard(
        self,
        repos: RepositoryContainer,
        order_manager: OrderManager,
        mock_broker: BrokerAdapter,
    ) -> None:
        """Stale Snapshot (no_history) → Submit 차단 (account-level path).

        Given:  계좌에 cash/position snapshot 없음 → account-level
                staleness 감지 → STALE_SNAPSHOT_ACCOUNT
                stale_threshold_seconds=1
        When:   submit request (BUY, APPROVE)
        Then:   assemble() 정상 실행
                pipeline returns SubmitResult(status="SKIPPED", error_phase="stale_snapshot")
                broker.submit_order() 호출되지 않음
                guardrail_evaluations에 STALE_SNAPSHOT_ACCOUNT 기록 존재
        """
        # 계좌에 snapshot이 없으므로 account-level staleness가 먼저 차단
        # run-level run은 제거할 필요 없음 (account-level이 우선)

        request = _make_request(client_order_id="SCENARIO-4-STALE-001")
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="SCENARIO-4-STALE-001",
            broker_order_id="SHOULD-NOT-HAPPEN",
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
        )

        service = DecisionOrchestratorService(
            repos=repos,
            stale_threshold_seconds=1,
            final_decision_agent=self._ApproveFDCAgent(),
        )

        # assemble은 정상 실행 (snapshot staleness와 무관)
        intent = await service.assemble(request)
        assert intent is not None
        assert intent.request.quantity > 0

        # pipeline 실행 → guardrail 차단
        result = await service.assemble_and_submit(
            request,
            order_manager=order_manager,
            broker=mock_broker,  # type: ignore[arg-type]
        )
        assert result.status == "SKIPPED", (
            f"Expected SKIPPED (stale_snapshot), got {result.status}"
        )
        assert result.error_phase == "stale_snapshot", (
            f"Expected error_phase='stale_snapshot', got {result.error_phase}"
        )
        # broker 미호출 강력 검증
        mock_broker.submit_order.assert_not_called()

        # GuardrailEvaluation 기록 확인
        assert repos.guardrail_evaluations._items, (
            "Expected guardrail_evaluations to have at least one record"
        )
        eval_records = list(repos.guardrail_evaluations._items.values())
        stale_record = next(
            (
                e
                for e in eval_records
                if "STALE_SNAPSHOT_ACCOUNT" in (e.blocking_rule_codes or [])
            ),
            None,
        )
        assert stale_record is not None, (
            "Expected a GuardrailEvaluation with STALE_SNAPSHOT_ACCOUNT blocking_rule_code"
        )
        assert stale_record.overall_passed is False
        # decision_context_id는 pipeline 내부의 intent 기준이므로 result에서 확인
        assert stale_record.decision_context_id == result.decision_context_id, (
            f"Guardrail decision_context_id {stale_record.decision_context_id} "
            f"!= result.decision_context_id {result.decision_context_id}"
        )

    # ═════════════════════════════════════════════════════════════════════
    # Scenario 4b (대체): Fresh Snapshot → 정상 제출
    # ═════════════════════════════════════════════════════════════════════

    @pytest.mark.asyncio
    async def test_scenario_4b_fresh_snapshot_submitted(
        self,
        repos: RepositoryContainer,
        order_manager: OrderManager,
        mock_broker: BrokerAdapter,
    ) -> None:
        """Fresh Snapshot → 정상 SUBMITTED (account-level + run-level 모두 fresh).

        Given:  계좌에 fresh cash snapshot + fresh position snapshots 존재
                snapshot_sync_runs에 최근 완료된 run 존재
        When:   submit request (BUY, APPROVE)
        Then:   pipeline 정상 진행 → SUBMITTED
                broker.submit_order() 1회 호출
        """
        # Seed: account-level fresh snapshots
        now = datetime.now(timezone.utc)
        account = list(repos.accounts._items.values())[0]
        cash_snapshot = CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=account.account_id,
            currency="KRW",
            available_cash=Decimal("1000000"),
            settled_cash=Decimal("0"),
            unsettled_cash=Decimal("0"),
            source_of_truth="broker",
            snapshot_at=now,
        )
        await repos.cash_balance_snapshots.add(cash_snapshot)
        position_snapshot = PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=account.account_id,
            instrument_id=uuid4(),
            quantity=Decimal("10"),
            average_price=Decimal("50000"),
            market_price=Decimal("50000"),
            unrealized_pnl=Decimal("0"),
            source_of_truth="broker",
            snapshot_at=now,
        )
        await repos.position_snapshots.add(position_snapshot)

        # Seed: completed SnapshotSyncRunEntity — started_at = now (fresh)
        seed_run = SnapshotSyncRunEntity(
            snapshot_sync_run_id=uuid4(),
            trigger_type="scheduler",
            scope="all",
            dry_run=False,
            total_accounts=1,
            succeeded_accounts=1,
            partial_accounts=0,
            failed_accounts=0,
            skipped_accounts=0,
            positions_synced_total=10,
            positions_skipped_total=0,
            cash_synced_count=1,
            error_count=0,
            status="completed",
            started_at=now,
            completed_at=now,
        )
        await repos.snapshot_sync_runs.add(seed_run)

        request = _make_request(client_order_id="SCENARIO-4B-FRESH-001")
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="SCENARIO-4B-FRESH-001",
            broker_order_id="BRK-SCENARIO-4B-001",
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="0000",
            raw_message="Accepted",
        )

        service = DecisionOrchestratorService(
            repos=repos,
            stale_threshold_seconds=900,  # default — seed_run은 fresh
            final_decision_agent=self._ApproveFDCAgent(),
        )

        # assemble 정상 실행
        intent = await service.assemble(request)
        assert intent is not None
        assert intent.request.quantity > 0

        # pipeline 정상 실행 (fresh snapshot → SUBMITTED)
        result = await service.assemble_and_submit(
            request,
            order_manager=order_manager,
            broker=mock_broker,  # type: ignore[arg-type]
        )
        assert result.status == "SUBMITTED", (
            f"Expected SUBMITTED (fresh snapshot), got {result.status}"
        )
        mock_broker.submit_order.assert_awaited_once()

    # ═════════════════════════════════════════════════════════════════════
    # Scenario 5: Duplicate Lock + 재시도 차단 → broker 1회만 호출
    # ═════════════════════════════════════════════════════════════════════

    @pytest.mark.asyncio
    async def test_scenario_5_blocking_lock_blocks_retry(
        self,
        repos: RepositoryContainer,
        order_manager: OrderManager,
        mock_broker: BrokerAdapter,
    ) -> None:
        """Duplicate Lock + 재시도 차단 → broker 1회만 호출.

        Given:  first call returns uncertain → lock created
                second call with same account/symbol/side
        When:   submit request again
        Then:   pipeline returns RECONCILE_REQUIRED (status_reason_code="BLOCKED")
                broker NOT called (call_count unchanged)
                lock still in place
        """
        # ── First call: uncertain → lock created ──
        # Seed fresh snapshots (for account-level Phase 4c guard)
        now = datetime.now(timezone.utc)
        account = list(repos.accounts._items.values())[0]
        instrument = list(repos.instruments._items.values())[0]
        cash_snapshot = CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=account.account_id,
            currency="KRW",
            available_cash=Decimal("1000000"),
            settled_cash=Decimal("0"),
            unsettled_cash=Decimal("0"),
            source_of_truth="broker",
            snapshot_at=now,
        )
        await repos.cash_balance_snapshots.add(cash_snapshot)
        position_snapshot = PositionSnapshotEntity(
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
        await repos.position_snapshots.add(position_snapshot)

        first_request = _make_request(client_order_id="SCENARIO-5-LOCK-001")

        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="SCENARIO-5-LOCK-001",
            broker_order_id=None,
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
            raw_code="TIMEOUT",
            raw_message="Response timeout",
            uncertain=True,
            requires_reconciliation=False,
        )

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
        second_request = _make_request(client_order_id="SCENARIO-5-LOCK-002")

        # Reset mock return value (second call should NOT reach broker)
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="SCENARIO-5-LOCK-002",
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

        # Then
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
        rs = ReconciliationService(repos)
        is_blocked = await rs.is_blocked(
            account_id=account.account_id,
            symbol=second_request.symbol,
            side=second_request.side.value,
        )
        assert is_blocked, (
            "Blocking lock should still exist after second blocked call"
        )

    # ═════════════════════════════════════════════════════════════════════
    # Account-Level Snapshot Freshness Tests (6 cases)
    # ═════════════════════════════════════════════════════════════════════

    @pytest.mark.asyncio
    async def test_account_level_fresh_cash_and_positions(
        self,
        repos: RepositoryContainer,
        order_manager: OrderManager,
        mock_broker: BrokerAdapter,
    ) -> None:
        """Test 1: Cash + positions both fresh → SUBMITTED.

        Given:  account-level cash snapshot fresh
                account-level position snapshots fresh (max snapshot_at within threshold)
        When:   submit request (BUY, APPROVE)
        Then:   account-level freshness PASS → pipeline proceeds
                broker.submit_order() 1회 호출
        """
        now = datetime.now(timezone.utc)
        account = list(repos.accounts._items.values())[0]

        # Seed fresh cash snapshot
        cash_snapshot = CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=account.account_id,
            currency="KRW",
            available_cash=Decimal("1000000"),
            settled_cash=Decimal("0"),
            unsettled_cash=Decimal("0"),
            source_of_truth="broker",
            snapshot_at=now,
        )
        await repos.cash_balance_snapshots.add(cash_snapshot)

        # Seed fresh position snapshots
        position1 = PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=account.account_id,
            instrument_id=uuid4(),
            quantity=Decimal("10"),
            average_price=Decimal("50000"),
            market_price=Decimal("50000"),
            unrealized_pnl=Decimal("0"),
            source_of_truth="broker",
            snapshot_at=now,
        )
        await repos.position_snapshots.add(position1)

        request = _make_request(client_order_id="TEST-ACCT-FRESH-001")
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="TEST-ACCT-FRESH-001",
            broker_order_id="BRK-FRESH-001",
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=now,
            raw_code="0000",
            raw_message="Accepted",
        )

        service = DecisionOrchestratorService(
            repos=repos,
            stale_threshold_seconds=900,
            final_decision_agent=self._ApproveFDCAgent(),
        )

        result = await service.assemble_and_submit(
            request,
            order_manager=order_manager,
            broker=mock_broker,  # type: ignore[arg-type]
        )
        assert result.status == "SUBMITTED", (
            f"Expected SUBMITTED (both fresh), got {result.status}"
        )
        mock_broker.submit_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_account_level_stale_cash(
        self,
        repos: RepositoryContainer,
        order_manager: OrderManager,
        mock_broker: BrokerAdapter,
    ) -> None:
        """Test 2: Cash snapshot stale → STALE_SNAPSHOT_ACCOUNT 차단.

        Given:  cash snapshot exists but stale (> threshold)
                position snapshot fresh
        When:   submit request (BUY, APPROVE)
        Then:   pipeline returns SKIPPED (stale_snapshot)
                guardrail has STALE_SNAPSHOT_ACCOUNT
                broker.submit_order() 호출되지 않음
        """
        now = datetime.now(timezone.utc)
        stale_time = now - timedelta(seconds=1000)
        account = list(repos.accounts._items.values())[0]

        # Seed stale cash snapshot
        cash_snapshot = CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=account.account_id,
            currency="KRW",
            available_cash=Decimal("1000000"),
            settled_cash=Decimal("0"),
            unsettled_cash=Decimal("0"),
            source_of_truth="broker",
            snapshot_at=stale_time,
        )
        await repos.cash_balance_snapshots.add(cash_snapshot)

        # Seed fresh position snapshot
        position1 = PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=account.account_id,
            instrument_id=uuid4(),
            quantity=Decimal("10"),
            average_price=Decimal("50000"),
            market_price=Decimal("50000"),
            unrealized_pnl=Decimal("0"),
            source_of_truth="broker",
            snapshot_at=now,
        )
        await repos.position_snapshots.add(position1)

        request = _make_request(client_order_id="TEST-ACCT-STALE-CASH-001")
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="TEST-ACCT-STALE-CASH-001",
            broker_order_id="SHOULD-NOT-HAPPEN",
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=now,
        )

        service = DecisionOrchestratorService(
            repos=repos,
            stale_threshold_seconds=300,  # stale_time > 300s ago
            final_decision_agent=self._ApproveFDCAgent(),
        )

        result = await service.assemble_and_submit(
            request,
            order_manager=order_manager,
            broker=mock_broker,  # type: ignore[arg-type]
        )
        assert result.status == "SKIPPED", (
            f"Expected SKIPPED (stale cash), got {result.status}"
        )
        assert result.error_phase == "stale_snapshot"
        mock_broker.submit_order.assert_not_called()

        # GuardrailEvaluation에 STALE_SNAPSHOT_ACCOUNT 기록 확인
        eval_records = list(repos.guardrail_evaluations._items.values())
        stale_record = next(
            (e for e in eval_records if "STALE_SNAPSHOT_ACCOUNT" in (e.blocking_rule_codes or [])),
            None,
        )
        assert stale_record is not None, (
            "Expected GuardrailEvaluation with STALE_SNAPSHOT_ACCOUNT"
        )

    @pytest.mark.asyncio
    async def test_account_level_stale_positions(
        self,
        repos: RepositoryContainer,
        order_manager: OrderManager,
        mock_broker: BrokerAdapter,
    ) -> None:
        """Test 3: Positions stale (cash fresh) → STALE_SNAPSHOT_ACCOUNT 차단.

        Given:  cash snapshot fresh
                position snapshots exist but max snapshot_at stale (> threshold)
        When:   submit request (BUY, APPROVE)
        Then:   pipeline returns SKIPPED (stale_snapshot)
                guardrail has STALE_SNAPSHOT_ACCOUNT
                broker.submit_order() 호출되지 않음
        """
        now = datetime.now(timezone.utc)
        stale_time = now - timedelta(seconds=1000)
        account = list(repos.accounts._items.values())[0]

        # Seed fresh cash snapshot
        cash_snapshot = CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=account.account_id,
            currency="KRW",
            available_cash=Decimal("1000000"),
            settled_cash=Decimal("0"),
            unsettled_cash=Decimal("0"),
            source_of_truth="broker",
            snapshot_at=now,
        )
        await repos.cash_balance_snapshots.add(cash_snapshot)

        # Seed stale position snapshot
        position1 = PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=account.account_id,
            instrument_id=uuid4(),
            quantity=Decimal("10"),
            average_price=Decimal("50000"),
            market_price=Decimal("50000"),
            unrealized_pnl=Decimal("0"),
            source_of_truth="broker",
            snapshot_at=stale_time,
        )
        await repos.position_snapshots.add(position1)

        request = _make_request(client_order_id="TEST-ACCT-STALE-POS-001")
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="TEST-ACCT-STALE-POS-001",
            broker_order_id="SHOULD-NOT-HAPPEN",
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=now,
        )

        service = DecisionOrchestratorService(
            repos=repos,
            stale_threshold_seconds=300,
            final_decision_agent=self._ApproveFDCAgent(),
        )

        result = await service.assemble_and_submit(
            request,
            order_manager=order_manager,
            broker=mock_broker,  # type: ignore[arg-type]
        )
        assert result.status == "SKIPPED", (
            f"Expected SKIPPED (stale positions), got {result.status}"
        )
        assert result.error_phase == "stale_snapshot"
        mock_broker.submit_order.assert_not_called()

        # GuardrailEvaluation 확인
        eval_records = list(repos.guardrail_evaluations._items.values())
        stale_record = next(
            (e for e in eval_records if "STALE_SNAPSHOT_ACCOUNT" in (e.blocking_rule_codes or [])),
            None,
        )
        assert stale_record is not None

    @pytest.mark.asyncio
    async def test_account_level_no_cash_snapshot(
        self,
        repos: RepositoryContainer,
        order_manager: OrderManager,
        mock_broker: BrokerAdapter,
    ) -> None:
        """Test 4: No cash snapshot → STALE_SNAPSHOT_ACCOUNT 차단.

        Given:  cash snapshot None (never synced)
                position snapshots empty
        When:   submit request (BUY, APPROVE)
        Then:   pipeline returns SKIPPED (stale_snapshot)
                broker.submit_order() 호출되지 않음
        """
        # No snapshots seeded at all
        request = _make_request(client_order_id="TEST-ACCT-NO-CASH-001")
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="TEST-ACCT-NO-CASH-001",
            broker_order_id="SHOULD-NOT-HAPPEN",
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=datetime.now(timezone.utc),
        )

        service = DecisionOrchestratorService(
            repos=repos,
            stale_threshold_seconds=1,
            final_decision_agent=self._ApproveFDCAgent(),
        )

        result = await service.assemble_and_submit(
            request,
            order_manager=order_manager,
            broker=mock_broker,  # type: ignore[arg-type]
        )
        assert result.status == "SKIPPED", (
            f"Expected SKIPPED (no cash snapshot), got {result.status}"
        )
        assert result.error_phase == "stale_snapshot"
        mock_broker.submit_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_account_level_run_fresh_account_stale(
        self,
        repos: RepositoryContainer,
        order_manager: OrderManager,
        mock_broker: BrokerAdapter,
    ) -> None:
        """Test 5: Run-level fresh + account-level stale → account-level wins.

        Given:  run-level snapshot_sync_runs에 fresh run 존재
                account-level cash snapshot stale (> threshold)
        When:   submit request (BUY, APPROVE)
        Then:   account-level staleness이 run-level freshness보다 우선
                pipeline returns SKIPPED (STALE_SNAPSHOT_ACCOUNT)
                broker.submit_order() 호출되지 않음
        """
        now = datetime.now(timezone.utc)
        stale_time = now - timedelta(seconds=1000)
        account = list(repos.accounts._items.values())[0]

        # Seed: run-level fresh
        seed_run = SnapshotSyncRunEntity(
            snapshot_sync_run_id=uuid4(),
            trigger_type="scheduler",
            scope="all",
            dry_run=False,
            total_accounts=1,
            succeeded_accounts=1,
            partial_accounts=0,
            failed_accounts=0,
            skipped_accounts=0,
            positions_synced_total=10,
            positions_skipped_total=0,
            cash_synced_count=1,
            error_count=0,
            status="completed",
            started_at=now,
            completed_at=now,
        )
        await repos.snapshot_sync_runs.add(seed_run)

        # Seed: account-level stale cash snapshot
        cash_snapshot = CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=account.account_id,
            currency="KRW",
            available_cash=Decimal("1000000"),
            settled_cash=Decimal("0"),
            unsettled_cash=Decimal("0"),
            source_of_truth="broker",
            snapshot_at=stale_time,
        )
        await repos.cash_balance_snapshots.add(cash_snapshot)

        request = _make_request(client_order_id="TEST-ACCT-RUN-FRESH-001")
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="TEST-ACCT-RUN-FRESH-001",
            broker_order_id="SHOULD-NOT-HAPPEN",
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=now,
        )

        service = DecisionOrchestratorService(
            repos=repos,
            stale_threshold_seconds=300,
            final_decision_agent=self._ApproveFDCAgent(),
        )

        result = await service.assemble_and_submit(
            request,
            order_manager=order_manager,
            broker=mock_broker,  # type: ignore[arg-type]
        )
        assert result.status == "SKIPPED", (
            f"Expected SKIPPED (account-level wins over run-level), got {result.status}"
        )
        assert result.error_phase == "stale_snapshot"
        mock_broker.submit_order.assert_not_called()

        # Verify STALE_SNAPSHOT_ACCOUNT (not STALE_SNAPSHOT)
        eval_records = list(repos.guardrail_evaluations._items.values())
        stale_record = next(
            (e for e in eval_records if "STALE_SNAPSHOT_ACCOUNT" in (e.blocking_rule_codes or [])),
            None,
        )
        assert stale_record is not None, (
            "Expected STALE_SNAPSHOT_ACCOUNT blocking code"
        )

    @pytest.mark.asyncio
    async def test_account_level_fresh_cash_empty_positions(
        self,
        repos: RepositoryContainer,
        order_manager: OrderManager,
        mock_broker: BrokerAdapter,
    ) -> None:
        """Test 6: Cash fresh + empty positions → SUBMITTED (zero-position policy).

        Given:  cash snapshot fresh
                position snapshots empty list (no positions for this account)
        When:   submit request (BUY, APPROVE)
        Then:   zero-position account policy 적용 → PASS
                broker.submit_order() 1회 호출
        """
        now = datetime.now(timezone.utc)
        account = list(repos.accounts._items.values())[0]

        # Seed fresh cash snapshot only (no position snapshots)
        cash_snapshot = CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=account.account_id,
            currency="KRW",
            available_cash=Decimal("1000000"),
            settled_cash=Decimal("0"),
            unsettled_cash=Decimal("0"),
            source_of_truth="broker",
            snapshot_at=now,
        )
        await repos.cash_balance_snapshots.add(cash_snapshot)

        request = _make_request(client_order_id="TEST-ACCT-ZERO-POS-001")
        mock_broker.submit_order.return_value = SubmitOrderResult(
            accepted=True,
            broker_name=BrokerName.KOREA_INVESTMENT,
            client_order_id="TEST-ACCT-ZERO-POS-001",
            broker_order_id="BRK-ZERO-POS-001",
            broker_status=OrderStatus.ACKNOWLEDGED,
            ack_timestamp=now,
            raw_code="0000",
            raw_message="Accepted",
        )

        service = DecisionOrchestratorService(
            repos=repos,
            stale_threshold_seconds=900,
            final_decision_agent=self._ApproveFDCAgent(),
        )

        result = await service.assemble_and_submit(
            request,
            order_manager=order_manager,
            broker=mock_broker,  # type: ignore[arg-type]
        )
        assert result.status == "SUBMITTED", (
            f"Expected SUBMITTED (zero-position policy), got {result.status}"
        )
        mock_broker.submit_order.assert_called_once()
