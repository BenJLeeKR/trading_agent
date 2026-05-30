"""Tests for ``_try_truth_probe()`` QTY_MISMATCH conflict detection (Phase 7f).

실제 ODNO 사례 (0000031736 BUY conflict, 0000001073 SELL clear)의
qty mismatch 검증 로직이 올바르게 동작하는지 검증한다.

실행: ``uv run pytest tests/services/test_truth_probe_conflict.py -v``
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from logging import WARNING, INFO
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from agent_trading.brokers.base import BrokerAdapter
from agent_trading.domain.entities import (
    BrokerOrderEntity,
    OrderRequestEntity,
)
from agent_trading.domain.enums import (
    BrokerName,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from agent_trading.domain.models import OrderStatusResult
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.order_manager import OrderManager
from agent_trading.services.order_sync_service import (
    OrderSyncService,
    SyncOrderResult,
    TruthProbeReason,
)

pytestmark = pytest.mark.asyncio


# ── Helpers ──


def _make_order(
    repos: RepositoryContainer,
    *,
    status: OrderStatus = OrderStatus.RECONCILE_REQUIRED,
    client_order_id: str = "TRUTH-001",
    requested_quantity: Decimal = Decimal("10"),
    side: OrderSide = OrderSide.BUY,
) -> OrderRequestEntity:
    """Create and persist an order with the given status."""
    now = datetime.now(timezone.utc)
    order = OrderRequestEntity(
        order_request_id=uuid4(),
        account_id=uuid4(),
        instrument_id=uuid4(),
        client_order_id=client_order_id,
        idempotency_key="idem-truth-001",
        correlation_id="corr-truth-001",
        side=side,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        requested_price=Decimal("50000"),
        requested_quantity=requested_quantity,
        status=status,
        trade_decision_id=None,
        submitted_at=None,
        status_reason_code=None,
        status_reason_message=None,
        created_at=now,
        updated_at=now,
    )
    repos.orders._items[order.order_request_id] = order  # type: ignore[attr-defined]
    return order


def _make_broker_order(
    repos: RepositoryContainer,
    order: OrderRequestEntity,
    *,
    broker_native_order_id: str = "BRK-TRUTH-001",
    broker_status: str = "reconcile_required",
) -> BrokerOrderEntity:
    """Create and persist a broker order linked to ``order``."""
    now = datetime.now(timezone.utc)
    broker_order = BrokerOrderEntity(
        broker_order_id=uuid4(),
        order_request_id=order.order_request_id,
        broker_name=BrokerName.KOREA_INVESTMENT.value,
        broker_status=broker_status,
        broker_native_order_id=broker_native_order_id,
        created_at=now,
        updated_at=now,
        last_synced_at=None,
    )
    repos.broker_orders._items[broker_order.broker_order_id] = broker_order  # type: ignore[attr-defined]
    return broker_order


def _build_result(
    status: OrderStatus,
    filled_quantity: Decimal | None = Decimal("0"),
    *,
    raw_code: str = "",
    raw_message: str = "",
) -> OrderStatusResult:
    """Helper to build an ``OrderStatusResult`` with the given parameters."""
    return OrderStatusResult(
        broker_name=BrokerName.KOREA_INVESTMENT,
        client_order_id="",
        broker_order_id="BRK-TRUTH-001",
        status=status,
        filled_quantity=filled_quantity,  # type: ignore[arg-type]
        remaining_quantity=Decimal("0"),
        average_fill_price=Decimal("50000"),
        last_updated_at=datetime.now(timezone.utc),
        raw_code=raw_code,
        raw_message=raw_message,
    )


# ═════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════


@pytest.fixture
def repos() -> RepositoryContainer:
    return build_in_memory_repositories()


@pytest.fixture
def order_manager(repos: RepositoryContainer) -> OrderManager:
    return OrderManager(repos=repos)


@pytest.fixture
def sync_service(
    repos: RepositoryContainer,
    order_manager: OrderManager,
) -> OrderSyncService:
    return OrderSyncService(repos=repos, order_manager=order_manager)


# ═════════════════════════════════════════════════════════════════════
# Test: _try_truth_probe() — qty mismatch conflict detection
# ═════════════════════════════════════════════════════════════════════


class TestTryTruthProbeQtyMismatch:
    """``_try_truth_probe()``의 qty mismatch 검증 로직 단위 테스트."""

    # ── Case a: FILLED + qty match → (FILLED, None) — regression ──

    async def test_filled_qty_match(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """FILLED이고 qty가 일치하면 conflict 없이 (FILLED, None) 반환."""
        order = _make_order(repos, requested_quantity=Decimal("1"))
        broker_order = _make_broker_order(repos, order)
        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state.return_value = _build_result(
            status=OrderStatus.FILLED,
            filled_quantity=Decimal("1"),
        )

        probe_status, probe_reason = await sync_service._try_truth_probe(
            order=order,
            broker_order=broker_order,
            broker=broker,
            account_ref="test-account",
        )

        assert probe_status == OrderStatus.FILLED
        assert probe_reason is None

    # ── Case b: FILLED + qty mismatch → (FILLED, QTY_MISMATCH) — conflict detection ──

    async def test_filled_qty_mismatch(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """FILLED이지만 qty mismatch → (FILLED, QTY_MISMATCH) 반환.
        
        실제 사례: KIS truth ord_qty=1, DB requested_quantity=12 → conflict.
        """
        order = _make_order(repos, requested_quantity=Decimal("12"))
        broker_order = _make_broker_order(repos, order)
        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state.return_value = _build_result(
            status=OrderStatus.FILLED,
            filled_quantity=Decimal("1"),
        )

        probe_status, probe_reason = await sync_service._try_truth_probe(
            order=order,
            broker_order=broker_order,
            broker=broker,
            account_ref="test-account",
        )

        assert probe_status == OrderStatus.FILLED
        assert probe_reason == TruthProbeReason.QTY_MISMATCH

    # ── Case c: EXPIRED + qty match → (EXPIRED, None) — regression ──

    async def test_expired_qty_match(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """EXPIRED이고 qty가 일치하면 conflict 없이 (EXPIRED, None) 반환."""
        order = _make_order(repos, requested_quantity=Decimal("0"))
        broker_order = _make_broker_order(repos, order)
        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state.return_value = _build_result(
            status=OrderStatus.EXPIRED,
            filled_quantity=Decimal("0"),
        )

        probe_status, probe_reason = await sync_service._try_truth_probe(
            order=order,
            broker_order=broker_order,
            broker=broker,
            account_ref="test-account",
        )

        assert probe_status == OrderStatus.EXPIRED
        assert probe_reason is None

    # ── Case d: EXPIRED + qty mismatch → (EXPIRED, QTY_MISMATCH) — conflict detection ──

    async def test_expired_qty_mismatch(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """EXPIRED이지만 qty mismatch → (EXPIRED, QTY_MISMATCH) 반환."""
        order = _make_order(repos, requested_quantity=Decimal("5"))
        broker_order = _make_broker_order(repos, order)
        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state.return_value = _build_result(
            status=OrderStatus.EXPIRED,
            filled_quantity=Decimal("0"),
        )

        probe_status, probe_reason = await sync_service._try_truth_probe(
            order=order,
            broker_order=broker_order,
            broker=broker,
            account_ref="test-account",
        )

        assert probe_status == OrderStatus.EXPIRED
        assert probe_reason == TruthProbeReason.QTY_MISMATCH

    # ── Case e: filled_quantity=None → (FILLED, None) — None-safe ──

    async def test_filled_quantity_none(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """filled_quantity가 None이면 qty mismatch 검증 skip → (FILLED, None)."""
        order = _make_order(repos, requested_quantity=Decimal("12"))
        broker_order = _make_broker_order(repos, order)
        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state.return_value = _build_result(
            status=OrderStatus.FILLED,
            filled_quantity=None,
        )

        probe_status, probe_reason = await sync_service._try_truth_probe(
            order=order,
            broker_order=broker_order,
            broker=broker,
            account_ref="test-account",
        )

        assert probe_status == OrderStatus.FILLED
        assert probe_reason is None

    # ── Case f: Non-terminal status → (None, NOT_TERMINAL) — 기존 logic 유지 ──

    async def test_non_terminal_status(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """Non-terminal status면 (None, NOT_TERMINAL) 반환 — 기존 경로 유지."""
        order = _make_order(repos, requested_quantity=Decimal("10"))
        broker_order = _make_broker_order(repos, order)
        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state.return_value = _build_result(
            status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=Decimal("5"),
        )

        probe_status, probe_reason = await sync_service._try_truth_probe(
            order=order,
            broker_order=broker_order,
            broker=broker,
            account_ref="test-account",
        )

        assert probe_status is None
        assert probe_reason == TruthProbeReason.NOT_TERMINAL

    # ── Case g: API failure → (None, API_FAILURE) — 기존 logic 유지 ──

    async def test_api_failure(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """resolve_unknown_state()가 예외를 던지면 (None, API_FAILURE) 반환."""
        order = _make_order(repos, requested_quantity=Decimal("10"))
        broker_order = _make_broker_order(repos, order)
        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state.side_effect = RuntimeError("KIS API timeout")

        probe_status, probe_reason = await sync_service._try_truth_probe(
            order=order,
            broker_order=broker_order,
            broker=broker,
            account_ref="test-account",
        )

        assert probe_status is None
        assert probe_reason == TruthProbeReason.API_FAILURE


# ═════════════════════════════════════════════════════════════════════
# Test: sync_order_post_submit() caller 로직 — WARNING log + error field
# ═════════════════════════════════════════════════════════════════════


class TestTruthProbeCallerIntegration:
    """``sync_order_post_submit()``에서 truth probe 결과에 따른 caller 동작 검증."""

    # ── Case 1: probe_reason=None → INFO log + error=None ──

    async def test_probe_clean_info_log_no_error(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """probe_reason이 None이면 INFO log가 남고 SyncOrderResult.error는 None."""
        order = _make_order(repos, status=OrderStatus.RECONCILE_REQUIRED, requested_quantity=Decimal("1"))
        broker_order = _make_broker_order(repos, order, broker_native_order_id="BRK-TRUTH-002")
        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state.return_value = _build_result(
            status=OrderStatus.FILLED,
            filled_quantity=Decimal("1"),
        )
        # get_order_status는 호출되지 않아야 함 (truth probe가 status 반환)
        broker.get_order_status = AsyncMock()  # type: ignore[method-assign]

        caplog.set_level(INFO)
        result: SyncOrderResult = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,
            broker_order_id=broker_order.broker_order_id,
        )

        # probe가 FILLED를 반환했으므로 status_changed=True
        assert result.current_status == OrderStatus.FILLED
        assert result.error is None  # conflict 없음 → error=None

        # INFO log 확인: "Truth probe resolved order ...: filled (ODNO=...)"
        assert any(
            "Truth probe resolved" in record.message and record.levelno == INFO
            for record in caplog.records
        ), "INFO log가 남지 않음"

        # WARNING log가 없어야 함
        assert not any(
            "conflict" in record.message and record.levelno == WARNING
            for record in caplog.records
        ), "conflict WARNING log가 남지 않아야 함"

        # get_order_status는 호출되지 않아야 함
        broker.get_order_status.assert_not_awaited()

    # ── Case 2: probe_reason=QTY_MISMATCH → WARNING log + error="truth_probe_conflict:qty_mismatch" ──

    async def test_probe_qty_mismatch_warning_log_and_error(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """qty mismatch시 WARNING log와 SyncOrderResult.error 필드 확인.
        
        실제 사례 시뮬레이션: KIS truth ord_qty=1, DB requested_quantity=12.
        """
        order = _make_order(repos, status=OrderStatus.RECONCILE_REQUIRED, requested_quantity=Decimal("12"))
        broker_order = _make_broker_order(repos, order, broker_native_order_id="BRK-TRUTH-003")
        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state.return_value = _build_result(
            status=OrderStatus.FILLED,
            filled_quantity=Decimal("1"),
        )
        broker.get_order_status = AsyncMock()  # type: ignore[method-assign]

        caplog.set_level(WARNING)
        result: SyncOrderResult = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,
            broker_order_id=broker_order.broker_order_id,
        )

        assert result.current_status == OrderStatus.FILLED
        assert result.error == "truth_probe_conflict:qty_mismatch"

        # WARNING log 확인: "Truth probe resolved order ...: filled (conflict: qty_mismatch, ODNO=...)"
        assert any(
            "conflict" in record.message and "qty_mismatch" in record.message
            and record.levelno == WARNING
            for record in caplog.records
        ), "qty mismatch WARNING log가 남지 않음"

        # get_order_status는 호출되지 않아야 함
        broker.get_order_status.assert_not_awaited()

    # ── Case 3: probe_reason=API_FAILURE (via _try_truth_probe exception) → WARNING ──

    async def test_probe_api_failure_warning_log_and_error(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """truth probe가 API_FAILURE로 fallback되면 WARNING log + error 필드 확인."""
        order = _make_order(repos, status=OrderStatus.RECONCILE_REQUIRED, requested_quantity=Decimal("10"))
        broker_order = _make_broker_order(repos, order, broker_native_order_id="BRK-TRUTH-004")
        broker = AsyncMock(spec=BrokerAdapter)
        # resolve_unknown_state가 예외 → caller가 API_FAILURE로 캐치
        broker.resolve_unknown_state.side_effect = RuntimeError("KIS API timeout")
        # get_order_status도 실패 (fallback까지 실패)
        broker.get_order_status.side_effect = RuntimeError("KIS API timeout")
        # get_fills mock (호출되지 않아야 함)
        broker.get_fills = AsyncMock()  # type: ignore[method-assign]

        caplog.set_level(WARNING)
        result: SyncOrderResult = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,
            broker_order_id=broker_order.broker_order_id,
        )

        # probe_status=None이므로 get_order_status로 fallback → 그것도 실패
        assert result.error is not None
        assert "truth_probe" in result.error or "get_order_status failed" in result.error
        assert result.status_changed is False
        assert result.current_status == OrderStatus.RECONCILE_REQUIRED

    # ── Case 4: probe_reason=NOT_TERMINAL → fallback to get_order_status ──

    async def test_probe_not_terminal_fallthrough(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """probe_reason이 NOT_TERMINAL이면 get_order_status로 fallback."""
        order = _make_order(repos, status=OrderStatus.RECONCILE_REQUIRED, requested_quantity=Decimal("10"))
        broker_order = _make_broker_order(repos, order, broker_native_order_id="BRK-TRUTH-005")
        broker = AsyncMock(spec=BrokerAdapter)
        # truth probe가 PARTIALLY_FILLED 반환 (NOT_TERMINAL)
        broker.resolve_unknown_state.return_value = _build_result(
            status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=Decimal("5"),
        )
        # get_order_status는 ACKNOWLEDGED 반환 (fallthrough)
        broker.get_order_status.return_value = _build_result(
            status=OrderStatus.ACKNOWLEDGED,
        )
        broker.get_fills = AsyncMock(return_value=[])  # type: ignore[method-assign]

        result: SyncOrderResult = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,
            broker_order_id=broker_order.broker_order_id,
        )

        # get_order_status로 fallthrough → ACKNOWLEDGED
        assert result.current_status == OrderStatus.ACKNOWLEDGED
        assert result.status_changed is True
        # error에는 truth_probe reason이 포함되지 않음 (fallthrough 성공)
        assert result.error is None or "truth_probe" not in (result.error or "")

    # ── Case 5: broker_native_order_id가 None → truth probe skip ──

    async def test_no_odno_skips_truth_probe(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
    ) -> None:
        """broker_native_order_id가 None이면 truth probe를 skip하고 get_order_status로 직접."""
        order = _make_order(repos, status=OrderStatus.RECONCILE_REQUIRED, requested_quantity=Decimal("10"))
        broker_order = _make_broker_order(
            repos, order,
            broker_native_order_id="",  # ODNO 없음
        )
        broker = AsyncMock(spec=BrokerAdapter)
        # get_order_status만 호출됨
        broker.get_order_status.return_value = _build_result(
            status=OrderStatus.ACKNOWLEDGED,
        )
        broker.get_fills = AsyncMock(return_value=[])  # type: ignore[method-assign]

        result: SyncOrderResult = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,
            broker_order_id=broker_order.broker_order_id,
        )

        # resolve_unknown_state는 호출되지 않음
        broker.resolve_unknown_state.assert_not_awaited()
        assert result.current_status == OrderStatus.ACKNOWLEDGED


# ═════════════════════════════════════════════════════════════════════
# Test: 실제 ODNO 사례 매핑 (Case validation)
# ═════════════════════════════════════════════════════════════════════


class TestRealOdnocases:
    """실제 ODNO 사례를 기반으로 한 검증."""

    async def test_case_0000031736_buy_conflict(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """``0000031736`` — BUY conflict, QTY_MISMATCH expected.
        
        KIS truth: ord_qty=1, tot_ccld_qty=1 → filled_quantity=Decimal("1")
        DB: requested_quantity=12, status=expired (API_FAILURE로 fallback)
        기대: (FILLED, QTY_MISMATCH) + WARNING log + error="truth_probe_conflict:qty_mismatch"
        """
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="0000031736",
            requested_quantity=Decimal("12"),
            side=OrderSide.BUY,
        )
        broker_order = _make_broker_order(
            repos, order,
            broker_native_order_id="0000031736",
        )
        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state.return_value = _build_result(
            status=OrderStatus.FILLED,
            filled_quantity=Decimal("1"),
        )
        broker.get_order_status = AsyncMock()  # type: ignore[method-assign]

        caplog.set_level(WARNING)

        result: SyncOrderResult = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,
            broker_order_id=broker_order.broker_order_id,
        )

        # qty mismatch → FILLED이지만 error 기록
        assert result.current_status == OrderStatus.FILLED
        assert result.error == "truth_probe_conflict:qty_mismatch"

        # WARNING log 확인
        assert any(
            "conflict" in record.message and "qty_mismatch" in record.message
            and record.levelno == WARNING
            for record in caplog.records
        ), "qty mismatch WARNING log가 남지 않음"

    async def test_case_0000001073_sell_clear(
        self,
        sync_service: OrderSyncService,
        repos: RepositoryContainer,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """``0000001073`` — SELL clear, None reason expected.
        
        KIS truth: ord_qty=1, tot_ccld_qty=1 → filled_quantity=Decimal("1")
        DB: requested_quantity=1
        기대: (FILLED, None) — qty 일치, conflict 없음, zero regression
        """
        order = _make_order(
            repos,
            status=OrderStatus.RECONCILE_REQUIRED,
            client_order_id="0000001073",
            requested_quantity=Decimal("1"),
            side=OrderSide.SELL,
        )
        broker_order = _make_broker_order(
            repos, order,
            broker_native_order_id="0000001073",
        )
        broker = AsyncMock(spec=BrokerAdapter)
        broker.resolve_unknown_state.return_value = _build_result(
            status=OrderStatus.FILLED,
            filled_quantity=Decimal("1"),
        )
        broker.get_order_status = AsyncMock()  # type: ignore[method-assign]

        caplog.set_level(INFO)

        result: SyncOrderResult = await sync_service.sync_order_post_submit(
            account_ref="test-account",
            broker=broker,
            broker_order_id=broker_order.broker_order_id,
        )

        # qty 일치 → FILLED, error=None
        assert result.current_status == OrderStatus.FILLED
        assert result.error is None

        # INFO log 확인 (WARNING 없음)
        assert any(
            "Truth probe resolved" in record.message and record.levelno == INFO
            for record in caplog.records
        ), "INFO log가 남지 않음"

        assert not any(
            record.levelno == WARNING
            for record in caplog.records
        ), "WARNING log가 남지 않아야 함"
