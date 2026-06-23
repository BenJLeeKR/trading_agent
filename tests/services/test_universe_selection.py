"""Tests for ``agent_trading.services.universe_selection`` — Universe Selection Service.

검증 범위
---------
1. ``SourceType.priority`` — 우선순위 정수 매핑 정확성
2. ``LiquidityFilter.check()`` — tick_size, inactive, unknown 필터링
3. ``UniverseSelectionService.compose()`` — 4-source composition
4. Held position override (보유 종목 강제 포함)
5. Event overlay promotion (고중요도 이벤트 promotion)
6. Priority sorting (held > event > market > core)
7. Daily cap 적용 (max_cap, exclude_held_from_cap)
8. Empty universe fallback (빈 universe → 빈 리스트)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Sequence
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import (
    ExternalEventEntity,
    InstrumentEntity,
    OrderRequestEntity,
    PositionSnapshotEntity,
    ReconciliationRunEntity,
)
from agent_trading.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.universe_selection import (
    LiquidityFilter,
    UniverseSelectionService,
)
from agent_trading.services.universe_selection_types import (
    INCLUSION_REASON_CORE,
    INCLUSION_REASON_EVENT,
    INCLUSION_REASON_HELD,
    INCLUSION_REASON_MANUAL,
    INCLUSION_REASON_RECONCILIATION,
    CompositionContext,
    MarketDataSnapshot,
    SelectedSymbol,
    SourceType,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ACCOUNT_ID = UUID("a44a02d1-7f32-5a62-99f7-235abeb58284")
FALLBACK_ACCOUNT_ID = UUID("00000000-0000-0000-0000-000000000001")
NOW = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_instrument(
    symbol: str,
    market_code: str = "KRX",
    is_active: bool = True,
    tick_size: Decimal | None = None,
    *,
    name: str | None = None,
    asset_class: str = "KR_STOCK",
    metadata: dict[str, object] | None = None,
) -> InstrumentEntity:
    normalized_market_segment = "KOSDAQ" if market_code == "KOSDAQ" else "KOSPI"
    return InstrumentEntity(
        instrument_id=uuid4(),
        symbol=symbol,
        market_code=market_code,
        name=name or f"Test-{symbol}",
        is_active=is_active,
        asset_class=asset_class,
        currency="KRW",
        tick_size=tick_size,
        exchange_code="KRX",
        market_segment=normalized_market_segment,
        metadata={"core_universe": True} if metadata is None else metadata,
    )


def _make_position(
    instrument_id: UUID,
    quantity: Decimal = Decimal("10"),
) -> PositionSnapshotEntity:
    return PositionSnapshotEntity(
        position_snapshot_id=uuid4(),
        account_id=ACCOUNT_ID,
        instrument_id=instrument_id,
        quantity=quantity,
        average_price=Decimal("50000"),
        market_price=Decimal("51000"),
        unrealized_pnl=Decimal("1000"),
        source_of_truth="test",
        snapshot_at=NOW,
        created_at=NOW,
    )


def _make_event(
    symbol: str,
    severity: str = "high",
    event_type: str = "disclosure",
    market: str = "KRX",
) -> ExternalEventEntity:
    return ExternalEventEntity(
        event_id=uuid4(),
        symbol=symbol,
        market=market,
        source_name="opendart",
        event_type=event_type,
        severity=severity,
        headline=f"Test event for {symbol}",
        published_at=NOW,
        ingested_at=NOW,
        dedup_key_hash=f"hash-{symbol}-{event_type}",
    )


def _make_order(
    instrument_id: UUID,
    *,
    status: OrderStatus = OrderStatus.PENDING_SUBMIT,
    account_id: UUID = ACCOUNT_ID,
) -> OrderRequestEntity:
    return OrderRequestEntity(
        order_request_id=uuid4(),
        account_id=account_id,
        instrument_id=instrument_id,
        client_order_id=f"coid-{uuid4()}",
        idempotency_key=f"idem-{uuid4()}",
        correlation_id=f"corr-{uuid4()}",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        requested_quantity=Decimal("3"),
        status=status,
        time_in_force=TimeInForce.DAY,
        created_at=NOW,
        updated_at=NOW,
    )


def _make_reconciliation_run(
    *,
    account_id: UUID = ACCOUNT_ID,
    status: str = "started",
) -> ReconciliationRunEntity:
    return ReconciliationRunEntity(
        reconciliation_run_id=uuid4(),
        account_id=account_id,
        trigger_type="order_submit",
        status=status,
        started_at=NOW,
        created_at=NOW,
    )


# ---------------------------------------------------------------------------
# SourceType priority
# ---------------------------------------------------------------------------


class TestSourceTypePriority:
    """``SourceType.priority`` — 우선순위 정수 매핑."""

    def test_held_position_highest_priority(self) -> None:
        """HELD_POSITION이 가장 높은 우선순위(0)를 가져야 함."""
        assert SourceType.HELD_POSITION.priority == 0

    def test_event_overlay_priority(self) -> None:
        """EVENT_OVERLAY 우선순위는 2."""
        assert SourceType.EVENT_OVERLAY.priority == 2

    def test_market_overlay_priority(self) -> None:
        """MARKET_OVERLAY 우선순위는 3."""
        assert SourceType.MARKET_OVERLAY.priority == 3

    def test_manual_priority(self) -> None:
        """MANUAL 우선순위는 4."""
        assert SourceType.MANUAL.priority == 4

    def test_reconciliation_overlay_priority(self) -> None:
        """RECONCILIATION_OVERLAY 우선순위는 1."""
        assert SourceType.RECONCILIATION_OVERLAY.priority == 1

    def test_core_lowest_priority(self) -> None:
        """CORE가 가장 낮은 우선순위(5)를 가져야 함."""
        assert SourceType.CORE.priority == 5

    def test_selected_symbol_priority_delegates(self) -> None:
        """SelectedSymbol.priority가 SourceType.priority에 위임."""
        held = SelectedSymbol("005930", "KRX", SourceType.HELD_POSITION, INCLUSION_REASON_HELD)
        core = SelectedSymbol("005930", "KRX", SourceType.CORE, INCLUSION_REASON_CORE)
        assert held.priority < core.priority  # held가 더 높은 우선순위


# ---------------------------------------------------------------------------
# LiquidityFilter
# ---------------------------------------------------------------------------


class TestLiquidityFilter:
    """``LiquidityFilter.check()`` — 결정론적 사전 필터."""

    @pytest.mark.asyncio
    async def test_unknown_instrument_excluded(self) -> None:
        """등록되지 않은 종목은 unknown_instrument로 제외."""
        repos = build_in_memory_repositories()
        lf = LiquidityFilter(repos)
        result = await lf.check("UNKNOWN", "KRX")
        assert result.passed is False
        assert result.fail_reason == "unknown_instrument"

    @pytest.mark.asyncio
    async def test_inactive_instrument_excluded(self) -> None:
        """비활성 종목은 inactive_instrument로 제외."""
        repos = build_in_memory_repositories()
        inst = _make_instrument("005930", is_active=False)
        await repos.instruments.add(inst)
        lf = LiquidityFilter(repos)
        result = await lf.check("005930", "KRX")
        assert result.passed is False
        assert result.fail_reason == "inactive_instrument"

    @pytest.mark.asyncio
    async def test_tick_size_too_large_excluded(self) -> None:
        """tick_size >= 1000은 tick_size_too_large로 제외."""
        repos = build_in_memory_repositories()
        inst = _make_instrument("005930", tick_size=Decimal("1000"))
        await repos.instruments.add(inst)
        lf = LiquidityFilter(repos)
        result = await lf.check("005930", "KRX")
        assert result.passed is False
        assert result.fail_reason == "tick_size_too_large"

    @pytest.mark.asyncio
    async def test_tick_size_below_threshold_passes(self) -> None:
        """tick_size < 1000은 통과."""
        repos = build_in_memory_repositories()
        inst = _make_instrument("005930", tick_size=Decimal("500"))
        await repos.instruments.add(inst)
        lf = LiquidityFilter(repos)
        result = await lf.check("005930", "KRX")
        assert result.passed is True
        assert result.fail_reason is None

    @pytest.mark.asyncio
    async def test_tick_size_none_passes(self) -> None:
        """tick_size가 None이면 통과 (정보 부족)."""
        repos = build_in_memory_repositories()
        inst = _make_instrument("005930", tick_size=None)
        await repos.instruments.add(inst)
        lf = LiquidityFilter(repos)
        result = await lf.check("005930", "KRX")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_active_instrument_with_small_tick_passes(self) -> None:
        """정상 활성 종목은 모든 필터 통과."""
        repos = build_in_memory_repositories()
        inst = _make_instrument("005930", is_active=True, tick_size=Decimal("50"))
        await repos.instruments.add(inst)
        lf = LiquidityFilter(repos)
        result = await lf.check("005930", "KRX")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_registered_kosdaq_instrument_passes(self) -> None:
        """등록된 KOSDAQ 종목은 한국주식 지원 시장으로 통과."""
        repos = build_in_memory_repositories()
        inst = _make_instrument("090150", market_code="KOSDAQ", tick_size=Decimal("50"))
        await repos.instruments.add(inst)
        lf = LiquidityFilter(repos)
        result = await lf.check("090150", "KOSDAQ")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_registered_kosdaq_instrument_passes_via_krx_alias(self) -> None:
        """이벤트/수동 입력이 KRX alias여도 등록된 KOSDAQ 종목은 lookup 가능해야 한다."""
        repos = build_in_memory_repositories()
        inst = _make_instrument("090150", market_code="KOSDAQ", tick_size=Decimal("50"))
        await repos.instruments.add(inst)
        lf = LiquidityFilter(repos)
        result = await lf.check("090150", "KRX")
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_preferred_share_excluded(self) -> None:
        """우선주/특수주는 공통 eligibility에서 제외."""
        repos = build_in_memory_repositories()
        inst = _make_instrument("000227", name="유유제약2우B", tick_size=Decimal("50"))
        await repos.instruments.add(inst)
        lf = LiquidityFilter(repos)
        result = await lf.check("000227", "KRX")
        assert result.passed is False
        assert result.fail_reason == "preferred_share_class"

    @pytest.mark.asyncio
    async def test_non_standard_symbol_excluded(self) -> None:
        """6자리 숫자 symbol이 아니면 공통 eligibility에서 제외."""
        repos = build_in_memory_repositories()
        inst = _make_instrument("00088K", name="한화3우B", tick_size=Decimal("50"))
        await repos.instruments.add(inst)
        lf = LiquidityFilter(repos)
        result = await lf.check("00088K", "KRX")
        assert result.passed is False
        assert result.fail_reason == "non_standard_symbol"

    @pytest.mark.asyncio
    async def test_metadata_excluded_instrument_rejected(self) -> None:
        """운영 제외 metadata가 명시되면 공통 eligibility에서 제외."""
        repos = build_in_memory_repositories()
        inst = _make_instrument(
            "005930",
            tick_size=Decimal("50"),
            metadata={"core_universe": True, "exclude_from_trading_universe": True},
        )
        await repos.instruments.add(inst)
        lf = LiquidityFilter(repos)
        result = await lf.check("005930", "KRX")
        assert result.passed is False
        assert result.fail_reason == "metadata_excluded"


# ---------------------------------------------------------------------------
# UniverseSelectionService — compose()
# ---------------------------------------------------------------------------


class TestUniverseSelectionServiceCompose:
    """``UniverseSelectionService.compose()`` — 4-source composition."""

    @pytest.mark.asyncio
    async def test_core_universe_loaded(self) -> None:
        """Core Universe가 DB active KRX instruments에서 로드됨."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(_make_instrument("005930"))
        await repos.instruments.add(_make_instrument("000660"))

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        symbols = {s.symbol for s in result}
        assert "005930" in symbols
        assert "000660" in symbols
        assert all(s.source_type == SourceType.CORE for s in result)

    @pytest.mark.asyncio
    async def test_core_universe_loads_registered_kosdaq_seed(self) -> None:
        """명시적 core flag가 있으면 KOSDAQ 종목도 core universe에 포함된다."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(
            _make_instrument(
                "090150",
                market_code="KOSDAQ",
                metadata={"core_universe": True},
            )
        )

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        assert any(
            item.symbol == "090150" and item.market == "KOSDAQ"
            for item in result
        )

    @pytest.mark.asyncio
    async def test_core_universe_prefers_index_membership_before_allowlist(self) -> None:
        """KOSPI index_memberships가 있으면 allowlist 없이도 core seed로 승격된다."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(
            _make_instrument(
                "123456",
                market_code="KOSPI",
                metadata={
                    "market_segment": "KOSPI",
                    "index_memberships": ["KOSPI200"],
                },
            )
        )

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        assert any(
            item.symbol == "123456" and item.source_type == SourceType.CORE
            for item in result
        )

    @pytest.mark.asyncio
    async def test_core_universe_prefers_membership_table_before_metadata_fallback(self) -> None:
        repos = build_in_memory_repositories()
        instrument = _make_instrument(
            "123457",
            market_code="KOSPI",
            metadata={"market_segment": "KOSPI"},
        )
        await repos.instruments.add(instrument)
        await repos.instrument_index_memberships.sync_current_memberships(
            instrument.instrument_id,
            ["KOSPI200"],
            effective_from=NOW.date(),
            source_tag="test",
            metadata={"source": "test"},
        )

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        assert any(
            item.symbol == "123457" and item.source_type == SourceType.CORE
            for item in result
        )

    @pytest.mark.asyncio
    async def test_core_universe_selected_symbol_carries_market_profile(self) -> None:
        repos = build_in_memory_repositories()
        instrument = _make_instrument(
            "123458",
            market_code="KRX",
            metadata={"market_segment": "KOSPI"},
        )
        await repos.instruments.add(instrument)
        await repos.instrument_index_memberships.sync_current_memberships(
            instrument.instrument_id,
            ["KOSPI100", "KOSPI200"],
            effective_from=NOW.date(),
            source_tag="test",
            metadata={"source": "test"},
        )

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        selected = next(item for item in result if item.symbol == "123458")
        assert selected.market_segment == "KOSPI"
        assert selected.index_memberships == ("KOSPI100", "KOSPI200")

    @pytest.mark.asyncio
    async def test_explicit_core_false_overrides_index_membership(self) -> None:
        """명시적 core_universe=False면 index_memberships가 있어도 core 승격하지 않는다."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(
            _make_instrument(
                "123456",
                market_code="KOSPI",
                metadata={
                    "core_universe": False,
                    "market_segment": "KOSPI",
                    "index_memberships": ["KOSPI200"],
                },
            )
        )

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        assert all(item.symbol != "123456" for item in result)

    @pytest.mark.asyncio
    async def test_kosdaq_discovery_seed_is_not_promoted_to_core_by_default(self) -> None:
        """KOSDAQ discovery seed는 명시적 core flag 없이는 주문 core로 승격되지 않는다."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(
            _make_instrument(
                "090150",
                market_code="KOSDAQ",
                metadata={"core_universe": False},
            )
        )

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        assert all(item.symbol != "090150" for item in result)

    @pytest.mark.asyncio
    async def test_inactive_instruments_excluded_from_core(self) -> None:
        """비활성 instrument는 Core Universe에서 제외됨."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(_make_instrument("005930", is_active=True))
        await repos.instruments.add(_make_instrument("000660", is_active=False))

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        symbols = {s.symbol for s in result}
        assert "005930" in symbols
        assert "000660" not in symbols

    @pytest.mark.asyncio
    async def test_held_position_overrides_core(self) -> None:
        """보유 종목이 Core Universe를 override하고 HELD_POSITION source_type을 가짐."""
        repos = build_in_memory_repositories()
        # Core에 005930 등록
        inst = _make_instrument("005930")
        await repos.instruments.add(inst)
        # 보유 포지션 추가 (instrument_id로 연결)
        pos = _make_position(instrument_id=inst.instrument_id, quantity=Decimal("10"))
        await repos.position_snapshots.add(pos)

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        # 005930이 HELD_POSITION source_type으로 override되어야 함
        held = [s for s in result if s.symbol == "005930"]
        assert len(held) == 1
        assert held[0].source_type == SourceType.HELD_POSITION
        assert held[0].inclusion_reason == INCLUSION_REASON_HELD

    @pytest.mark.asyncio
    async def test_zero_quantity_position_not_included(self) -> None:
        """수량 0인 포지션은 universe에 포함되지 않음."""
        repos = build_in_memory_repositories()
        inst = _make_instrument("005930")
        await repos.instruments.add(inst)
        pos = _make_position(instrument_id=inst.instrument_id, quantity=Decimal("0"))
        await repos.position_snapshots.add(pos)

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        # 005930이 CORE로는 있지만 HELD_POSITION으로 override되지는 않음
        core = [s for s in result if s.symbol == "005930"]
        assert len(core) == 1
        assert core[0].source_type == SourceType.CORE

    @pytest.mark.asyncio
    async def test_event_overlay_promotion(self) -> None:
        """고중요도 이벤트가 있는 종목은 EVENT_OVERLAY로 promotion."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(_make_instrument("005930"))
        await repos.instruments.add(_make_instrument("000660"))
        # 005930에 고중요도 이벤트 추가
        await repos.external_events.add(_make_event("005930", severity="high"))

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        event = [s for s in result if s.symbol == "005930"]
        assert len(event) == 1
        assert event[0].source_type == SourceType.EVENT_OVERLAY
        assert event[0].inclusion_reason == "high_importance_event:disclosure_material"

    @pytest.mark.asyncio
    async def test_medium_severity_management_issue_promoted(self) -> None:
        """management_issue는 medium severity여도 overlay 대상이다."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(_make_instrument("005930", metadata={"core_universe": False}))
        await repos.external_events.add(
            _make_event("005930", severity="medium", event_type="management_issue")
        )

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        event = [s for s in result if s.symbol == "005930"]
        assert len(event) == 1
        assert event[0].source_type == SourceType.EVENT_OVERLAY
        assert event[0].inclusion_reason == "high_importance_event:management_issue"

    @pytest.mark.asyncio
    async def test_prefixed_disclosure_reason_normalized(self) -> None:
        """Y|disclosure 같은 legacy 타입도 표준 reason으로 정규화한다."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(_make_instrument("005930"))
        await repos.external_events.add(
            _make_event("005930", severity="high", event_type="Y|disclosure")
        )

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        event = [s for s in result if s.symbol == "005930"]
        assert len(event) == 1
        assert event[0].inclusion_reason == "high_importance_event:disclosure_material"

    @pytest.mark.asyncio
    async def test_seeded_news_high_importance_promoted(self) -> None:
        """seeded_news는 metadata importance가 high면 overlay 대상이다."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(_make_instrument("005930", metadata={"core_universe": False}))
        await repos.external_events.add(
            ExternalEventEntity(
                event_id=uuid4(),
                symbol="005930",
                market="KRX",
                source_name="naver_news_seeded",
                event_type="seeded_news",
                severity="medium",
                headline="Seeded news",
                published_at=NOW,
                ingested_at=NOW,
                dedup_key_hash="hash-seeded-news",
                metadata={"importance": "high"},
            )
        )

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        event = [s for s in result if s.symbol == "005930"]
        assert len(event) == 1
        assert event[0].source_type == SourceType.EVENT_OVERLAY
        assert event[0].inclusion_reason == "high_importance_event:news_breaking"

    @pytest.mark.asyncio
    async def test_open_order_symbol_force_included_as_reconciliation_overlay(self) -> None:
        """미체결/활성 주문 종목은 reconciliation overlay로 강제 포함."""
        repos = build_in_memory_repositories()
        inst = _make_instrument(
            "299999",
            tick_size=Decimal("50"),
            metadata={"core_universe": False},
        )
        await repos.instruments.add(inst)
        await repos.orders.add(
            _make_order(inst.instrument_id, status=OrderStatus.PENDING_SUBMIT)
        )

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        selected = [s for s in result if s.symbol == "299999"]
        assert len(selected) == 1
        assert selected[0].source_type == SourceType.RECONCILIATION_OVERLAY
        assert selected[0].inclusion_reason == (
            f"{INCLUSION_REASON_RECONCILIATION}:{OrderStatus.PENDING_SUBMIT.value}"
        )

    @pytest.mark.asyncio
    async def test_reconciliation_run_link_symbol_force_included(self) -> None:
        """진행 중 reconciliation run에 연결된 주문 종목은 강제 포함."""
        repos = build_in_memory_repositories()
        inst = _make_instrument(
            "288888",
            tick_size=Decimal("50"),
            metadata={"core_universe": False},
        )
        await repos.instruments.add(inst)
        order = _make_order(inst.instrument_id, status=OrderStatus.RECONCILE_REQUIRED)
        await repos.orders.add(order)
        run = _make_reconciliation_run()
        await repos.reconciliations.add_run(run)
        await repos.reconciliations.attach_order_mismatch(
            run.reconciliation_run_id,
            order.order_request_id,
            "broker_order_missing",
            {"symbol": "288888"},
        )

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        selected = [s for s in result if s.symbol == "288888"]
        assert len(selected) == 1
        assert selected[0].source_type == SourceType.RECONCILIATION_OVERLAY
        assert selected[0].inclusion_reason == (
            f"{INCLUSION_REASON_RECONCILIATION}:broker_order_missing"
        )

    @pytest.mark.asyncio
    async def test_held_position_keeps_priority_over_reconciliation_overlay(self) -> None:
        """보유 종목은 reconciliation overlay보다 높은 우선순위를 유지."""
        repos = build_in_memory_repositories()
        inst = _make_instrument("005930", tick_size=Decimal("50"))
        await repos.instruments.add(inst)
        await repos.position_snapshots.add(_make_position(inst.instrument_id, quantity=Decimal("7")))
        await repos.orders.add(
            _make_order(inst.instrument_id, status=OrderStatus.RECONCILE_REQUIRED)
        )

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        selected = next(s for s in result if s.symbol == "005930")
        assert selected.source_type == SourceType.HELD_POSITION

    @pytest.mark.asyncio
    async def test_reconciliation_overlay_excluded_from_cap(self) -> None:
        """reconciliation overlay는 held와 동일하게 일반 cap에서 제외."""
        repos = build_in_memory_repositories()
        recon_inst = _make_instrument(
            "288888",
            tick_size=Decimal("50"),
            metadata={"core_universe": False},
        )
        core1 = _make_instrument("005930", tick_size=Decimal("50"))
        core2 = _make_instrument("000660", tick_size=Decimal("50"))
        await repos.instruments.add(recon_inst)
        await repos.instruments.add(core1)
        await repos.instruments.add(core2)
        await repos.orders.add(
            _make_order(recon_inst.instrument_id, status=OrderStatus.RECONCILE_REQUIRED)
        )

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(
            account_id=ACCOUNT_ID,
            since=NOW,
            max_cap=1,
            exclude_held_from_cap=True,
        )
        result = await svc.compose(ctx)

        assert len(result) == 2
        source_types = {item.symbol: item.source_type for item in result}
        assert source_types["288888"] == SourceType.RECONCILIATION_OVERLAY
        assert sum(1 for item in result if item.source_type == SourceType.CORE) == 1

    @pytest.mark.asyncio
    async def test_manual_watchlist_promotes_core(self) -> None:
        """manual watchlist symbol은 core를 override하고 MANUAL source_type을 가짐."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(_make_instrument("005930"))

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(
            account_id=FALLBACK_ACCOUNT_ID,
            since=NOW,
            manual_symbols=(("005930", "KRX"),),
        )
        result = await svc.compose(ctx)

        selected = [s for s in result if s.symbol == "005930"]
        assert len(selected) == 1
        assert selected[0].source_type == SourceType.MANUAL
        assert selected[0].inclusion_reason == INCLUSION_REASON_MANUAL

    @pytest.mark.asyncio
    async def test_event_overlay_overrides_manual_watchlist(self) -> None:
        """event overlay는 manual watchlist보다 우선해야 함."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(_make_instrument("005930"))
        await repos.external_events.add(_make_event("005930", severity="high"))

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(
            account_id=FALLBACK_ACCOUNT_ID,
            since=NOW,
            manual_symbols=(("005930", "KRX"),),
        )
        result = await svc.compose(ctx)

        selected = [s for s in result if s.symbol == "005930"]
        assert len(selected) == 1
        assert selected[0].source_type == SourceType.EVENT_OVERLAY

    @pytest.mark.asyncio
    async def test_low_severity_event_does_not_promote(self) -> None:
        """low/medium severity 이벤트는 promotion하지 않음."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(_make_instrument("005930"))
        await repos.external_events.add(_make_event("005930", severity="low"))

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        core = [s for s in result if s.symbol == "005930"]
        assert len(core) == 1
        assert core[0].source_type == SourceType.CORE  # promotion되지 않음

    @pytest.mark.asyncio
    async def test_priority_sorting(self) -> None:
        """결과가 held > event > market > core 순으로 정렬됨."""
        repos = build_in_memory_repositories()
        # Core: 005930, 000660
        inst1 = _make_instrument("005930")
        inst2 = _make_instrument("000660")
        await repos.instruments.add(inst1)
        await repos.instruments.add(inst2)
        # Held: 000660 (override)
        pos = _make_position(instrument_id=inst2.instrument_id, quantity=Decimal("10"))
        await repos.position_snapshots.add(pos)
        # Event: 005930 (override)
        await repos.external_events.add(_make_event("005930", severity="high"))

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        # 정렬 순서: held(000660) → event(005930)
        assert len(result) >= 2
        assert result[0].source_type == SourceType.HELD_POSITION
        assert result[1].source_type == SourceType.EVENT_OVERLAY

    @pytest.mark.asyncio
    async def test_daily_cap_limits_non_held(self) -> None:
        """max_cap=1일 때 held를 제외한 나머지 중 1개만 포함."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(_make_instrument("005930"))
        await repos.instruments.add(_make_instrument("000660"))
        await repos.instruments.add(_make_instrument("010130"))

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(
            account_id=FALLBACK_ACCOUNT_ID,
            since=NOW,
            max_cap=1,
            exclude_held_from_cap=True,
        )
        result = await svc.compose(ctx)

        # held가 없으므로 1개만 포함
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_daily_cap_with_held_excluded(self) -> None:
        """held 종목은 cap에서 제외 (exclude_held_from_cap=True)."""
        repos = build_in_memory_repositories()
        inst1 = _make_instrument("005930")
        inst2 = _make_instrument("000660")
        await repos.instruments.add(inst1)
        await repos.instruments.add(inst2)
        # 005930 보유
        pos = _make_position(instrument_id=inst1.instrument_id, quantity=Decimal("10"))
        await repos.position_snapshots.add(pos)

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(
            account_id=ACCOUNT_ID,
            since=NOW,
            max_cap=1,
            exclude_held_from_cap=True,
        )
        result = await svc.compose(ctx)

        # held(005930) + 1 non-held(000660) = 2
        assert len(result) == 2
        assert result[0].source_type == SourceType.HELD_POSITION

    @pytest.mark.asyncio
    async def test_core_cap_limits_only_core_symbols(self) -> None:
        """core_cap 도달 시에도 event overlay는 유지되고 core만 추가 제한된다."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(_make_instrument("005930"))
        await repos.instruments.add(_make_instrument("000660"))
        await repos.instruments.add(_make_instrument("035420"))
        await repos.external_events.add(_make_event("000660", severity="high"))

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(
            account_id=FALLBACK_ACCOUNT_ID,
            since=NOW,
            max_cap=3,
            core_cap=1,
            exclude_held_from_cap=True,
        )
        result = await svc.compose(ctx)

        symbols = [item.symbol for item in result]
        source_types = {item.symbol: item.source_type for item in result}
        assert len(result) == 2
        assert "000660" in symbols
        assert source_types["000660"] == SourceType.EVENT_OVERLAY
        assert sum(1 for item in result if item.source_type == SourceType.CORE) == 1

    @pytest.mark.asyncio
    async def test_event_overlay_cap_limits_event_symbols(self) -> None:
        """event_overlay_cap 도달 시 추가 event 편입만 제한된다."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(_make_instrument("005930"))
        await repos.instruments.add(_make_instrument("000660"))
        await repos.instruments.add(_make_instrument("035420"))
        await repos.external_events.add(_make_event("005930", severity="high"))
        await repos.external_events.add(_make_event("000660", severity="high"))

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(
            account_id=FALLBACK_ACCOUNT_ID,
            since=NOW,
            max_cap=3,
            event_overlay_cap=1,
            exclude_held_from_cap=True,
        )
        result = await svc.compose(ctx)

        assert sum(1 for item in result if item.source_type == SourceType.EVENT_OVERLAY) == 1
        assert sum(1 for item in result if item.source_type == SourceType.CORE) == 1

    @pytest.mark.asyncio
    async def test_reconciliation_overlay_reserve_limits_cap_exemption(self) -> None:
        """reconciliation reserve 초과분은 일반 max_cap을 소비한다."""
        repos = build_in_memory_repositories()
        inst1 = _make_instrument("299999", metadata={"core_universe": False})
        inst2 = _make_instrument("288888", metadata={"core_universe": False})
        inst3 = _make_instrument("005930")
        await repos.instruments.add(inst1)
        await repos.instruments.add(inst2)
        await repos.instruments.add(inst3)
        await repos.orders.add(_make_order(inst1.instrument_id, status=OrderStatus.PENDING_SUBMIT))
        await repos.orders.add(_make_order(inst2.instrument_id, status=OrderStatus.SUBMITTED))

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(
            account_id=ACCOUNT_ID,
            since=NOW,
            max_cap=1,
            reconciliation_overlay_reserve=1,
            exclude_held_from_cap=True,
        )
        result = await svc.compose(ctx)

        assert sum(
            1 for item in result if item.source_type == SourceType.RECONCILIATION_OVERLAY
        ) == 2
        assert all(item.symbol != "005930" for item in result)

    @pytest.mark.asyncio
    async def test_empty_universe_returns_empty_list(self) -> None:
        """DB에 instrument가 없으면 빈 리스트 반환."""
        repos = build_in_memory_repositories()
        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)
        assert result == []

    @pytest.mark.asyncio
    async def test_non_core_seed_instrument_not_loaded_into_core(self) -> None:
        """core seed가 아닌 종목은 core universe에 자동 편입되지 않음."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(
            _make_instrument(
                "299999",
                tick_size=Decimal("50"),
                metadata={"core_universe": False},
            )
        )

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)
        assert result == []

    @pytest.mark.asyncio
    async def test_liquidity_filter_excludes_tick_size_too_large(self) -> None:
        """tick_size >= 1000인 종목이 liquidity filter에 의해 제외됨."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(_make_instrument("005930", tick_size=Decimal("50")))
        await repos.instruments.add(_make_instrument("000660", tick_size=Decimal("1000")))

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        symbols = {s.symbol for s in result}
        assert "005930" in symbols
        assert "000660" not in symbols  # tick_size_too_large로 제외

    @pytest.mark.asyncio
    async def test_market_overlay_stub_noop(self) -> None:
        """P1 Market-Driven Overlay는 stub으로 아무것도 추가하지 않음."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(_make_instrument("005930"))

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        # MARKET_OVERLAY source_type이 없어야 함
        market_types = [s for s in result if s.source_type == SourceType.MARKET_OVERLAY]
        assert len(market_types) == 0

    @pytest.mark.asyncio
    async def test_compose_with_custom_liquidity_filter(self) -> None:
        """커스텀 LiquidityFilter를 주입할 수 있음."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(_make_instrument("005930"))

        # 모든 종목을 제외하는 LiquidityFilter
        class RejectAllFilter(LiquidityFilter):
            async def check(self, symbol: str, market: str) -> ...:  # type: ignore[override]
                from agent_trading.services.universe_selection_types import LiquidityFilterResult
                return LiquidityFilterResult(False, "reject_all")

        svc = UniverseSelectionService(repos, liquidity_filter=RejectAllFilter(repos))
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)
        assert result == []


# ---------------------------------------------------------------------------
# P2 bugfix: Source priority overwrite
# ---------------------------------------------------------------------------

# Priority hierarchy (lower number = higher priority):
#   HELD_POSITION(0) > EVENT_OVERLAY(1) > MARKET_OVERLAY(2) > MANUAL(3) > CORE(4)
# - HELD_POSITION(0): highest — never overwritten (mandatory override).
# - EVENT_OVERLAY(1) > MARKET_OVERLAY(2): event wins over market on same symbol.
# - MARKET_OVERLAY(2) > MANUAL(3): market signal beats manual inclusion.
# - MANUAL(3): reserved for future operator override; current precedence
#   follows ``SourceType.priority()``.
# - CORE(4): lowest — always eligible for promotion.
# First-writer wins on equal priority (lower number = higher priority).


class TestSourcePriorityOverwrite:
    """``_upsert_with_priority()`` — priority 기반 merge 정확성."""

    @pytest.mark.asyncio
    async def test_held_not_overwritten_by_event(self) -> None:
        """HELD_POSITION(0)은 EVENT_OVERLAY(2)로 덮어쓰면 안 됨."""
        repos = build_in_memory_repositories()
        inst = _make_instrument("005930")
        await repos.instruments.add(inst)
        # Held position
        pos = _make_position(instrument_id=inst.instrument_id, quantity=Decimal("10"))
        await repos.position_snapshots.add(pos)
        # High-severity event on same symbol
        await repos.external_events.add(_make_event("005930", severity="high"))

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        selected = next(s for s in result if s.symbol == "005930")
        assert selected.source_type == SourceType.HELD_POSITION

    @pytest.mark.asyncio
    async def test_core_promoted_by_event(self) -> None:
        """CORE(3)는 EVENT_OVERLAY(2)로 승격 가능."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(_make_instrument("005930"))
        await repos.external_events.add(_make_event("005930", severity="high"))

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        selected = next(s for s in result if s.symbol == "005930")
        assert selected.source_type == SourceType.EVENT_OVERLAY

    @pytest.mark.asyncio
    async def test_core_promoted_by_market(self) -> None:
        """CORE(3)는 MARKET_OVERLAY(2)로 승격 가능."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(_make_instrument("005930"))

        class _MockKIS:
            async def get_quotes_batch(self, symbols, **kwargs):
                return {sym: {"output": {"stck_prpr": "50000", "prdy_ctrt": "2.5",
                                         "acml_tr_pbmn": "500000000000",
                                         "stck_hgpr": "55000", "stck_lwpr": "48000",
                                         "stck_oprc": "49000"}} for sym in symbols}

        svc = UniverseSelectionService(repos, kis_client=_MockKIS())
        ctx = CompositionContext(
            account_id=FALLBACK_ACCOUNT_ID, since=NOW,
            market_overlay_cap=5, pre_pool_size=50,
        )
        result = await svc.compose(ctx)

        selected = next(s for s in result if s.symbol == "005930")
        assert selected.source_type == SourceType.MARKET_OVERLAY

    @pytest.mark.asyncio
    async def test_event_not_overwritten_by_market(self) -> None:
        """EVENT_OVERLAY(2)는 MARKET_OVERLAY(2)로 덮어쓰면 안 됨 (first-writer)."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(_make_instrument("005930"))
        await repos.external_events.add(_make_event("005930", severity="high"))

        class _MockKIS:
            async def get_quotes_batch(self, symbols, **kwargs):
                return {sym: {"output": {"stck_prpr": "50000", "prdy_ctrt": "2.5",
                                         "acml_tr_pbmn": "500000000000",
                                         "stck_hgpr": "55000", "stck_lwpr": "48000",
                                         "stck_oprc": "49000"}} for sym in symbols}

        svc = UniverseSelectionService(repos, kis_client=_MockKIS())
        ctx = CompositionContext(
            account_id=FALLBACK_ACCOUNT_ID, since=NOW,
            market_overlay_cap=5, pre_pool_size=50,
        )
        result = await svc.compose(ctx)

        selected = next(s for s in result if s.symbol == "005930")
        assert selected.source_type == SourceType.EVENT_OVERLAY  # first-writer wins


class TestEventLookback:
    """``CompositionContext.since`` — lookback window로 이벤트 필터링."""

    @pytest.mark.asyncio
    async def test_recent_event_included(self) -> None:
        """최근 이벤트 (lookback 내) → EVENT_OVERLAY promotion."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(_make_instrument("005930"))

        from datetime import timedelta
        from agent_trading.domain.entities import ExternalEventEntity

        recent_event = ExternalEventEntity(
            event_id=uuid4(), symbol="005930", market="KRX",
            source_name="opendart", event_type="disclosure",
            severity="high", headline="Recent event",
            published_at=NOW - timedelta(hours=1),  # 1시간 전
            ingested_at=NOW,
            dedup_key_hash="hash-recent",
        )
        await repos.external_events.add(recent_event)

        svc = UniverseSelectionService(repos)
        # lookback 2시간 = 최근 1시간 전 이벤트 포함
        ctx = CompositionContext(
            account_id=FALLBACK_ACCOUNT_ID,
            since=NOW - timedelta(hours=2),
        )
        result = await svc.compose(ctx)

        selected = next(s for s in result if s.symbol == "005930")
        assert selected.source_type == SourceType.EVENT_OVERLAY

    @pytest.mark.asyncio
    async def test_old_event_excluded(self) -> None:
        """오래된 이벤트 (lookback 밖) → CORE 유지."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(_make_instrument("005930"))

        from datetime import timedelta
        from agent_trading.domain.entities import ExternalEventEntity

        old_event = ExternalEventEntity(
            event_id=uuid4(), symbol="005930", market="KRX",
            source_name="opendart", event_type="disclosure",
            severity="high", headline="Old event",
            published_at=NOW - timedelta(hours=48),  # 48시간 전
            ingested_at=NOW,
            dedup_key_hash="hash-old",
        )
        await repos.external_events.add(old_event)

        svc = UniverseSelectionService(repos)
        # lookback 24시간 = 48시간 전 이벤트 제외
        ctx = CompositionContext(
            account_id=FALLBACK_ACCOUNT_ID,
            since=NOW - timedelta(hours=24),
        )
        result = await svc.compose(ctx)

        selected = next(s for s in result if s.symbol == "005930")
        assert selected.source_type == SourceType.CORE  # promotion되지 않음


# ---------------------------------------------------------------------------
# P2: Market-Driven Overlay
# ---------------------------------------------------------------------------


class TestMarketOverlay:
    """P2 minimum: ``_add_market_overlay()`` — pre-pool, score, cap."""

    @pytest.mark.asyncio
    async def test_no_kis_client_is_noop(self) -> None:
        """KIS client가 없으면 market overlay는 no-op (P1 호환)."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(_make_instrument("005930"))
        await repos.instruments.add(_make_instrument("000660"))

        svc = UniverseSelectionService(repos, kis_client=None)
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        market_types = [s for s in result if s.source_type == SourceType.MARKET_OVERLAY]
        assert len(market_types) == 0

    @pytest.mark.asyncio
    async def test_pre_pool_cap_applied(self) -> None:
        """pre_pool_size=2일 때 2개만 quote batch에 포함됨."""
        repos = build_in_memory_repositories()
        # 5개 instrument 등록
        for sym in ["005930", "000660", "010130", "012450", "016360"]:
            await repos.instruments.add(_make_instrument(sym))

        # Mock KIS client: get_quotes_batch가 호출된 symbols 기록
        class _MockKIS:
            def __init__(self) -> None:
                self.called_symbols: list[str] = []

            async def get_quotes_batch(
                self, symbols: Sequence[str], **kwargs: object
            ) -> dict[str, dict[str, object]]:
                self.called_symbols = list(symbols)
                # Return empty (no overlay added, but we verify pre-pool size)
                return {}

        mock_kis = _MockKIS()
        svc = UniverseSelectionService(repos, kis_client=mock_kis)  # type: ignore[arg-type]
        ctx = CompositionContext(
            account_id=FALLBACK_ACCOUNT_ID,
            since=NOW,
            pre_pool_size=2,
        )
        await svc.compose(ctx)

        assert len(mock_kis.called_symbols) == 2

    @pytest.mark.asyncio
    async def test_market_overlay_prefers_ranking_seed_pool(self) -> None:
        """랭킹 seed가 있으면 core fallback보다 우선 사용한다."""
        repos = build_in_memory_repositories()
        for sym in ["005930", "000660", "010130", "012450"]:
            await repos.instruments.add(_make_instrument(sym))

        class _MockKIS:
            def __init__(self) -> None:
                self.called_symbols: list[str] = []

            async def get_market_overlay_seed_symbols(self, *, limit: int = 60) -> list[str]:
                assert limit >= 30
                return ["010130", "012450"]

            async def get_quotes_batch(
                self, symbols: Sequence[str], **kwargs: object
            ) -> dict[str, dict[str, object]]:
                self.called_symbols = list(symbols)
                return {
                    "010130": {
                        "stck_prpr": "30000",
                        "prdy_ctrt": "4.5",
                        "acml_tr_pbmn": "800000000000",
                        "stck_hgpr": "30100",
                        "stck_oprc": "29000",
                        "stck_lwpr": "28900",
                    },
                    "012450": {
                        "stck_prpr": "15000",
                        "prdy_ctrt": "2.0",
                        "acml_tr_pbmn": "400000000000",
                        "stck_hgpr": "15100",
                        "stck_oprc": "14500",
                        "stck_lwpr": "14400",
                    },
                }

        mock_kis = _MockKIS()
        svc = UniverseSelectionService(repos, kis_client=mock_kis)  # type: ignore[arg-type]
        ctx = CompositionContext(
            account_id=FALLBACK_ACCOUNT_ID,
            since=NOW,
            pre_pool_size=5,
            market_overlay_cap=2,
        )
        _, diagnostics = await svc.compose_with_diagnostics(ctx)

        assert mock_kis.called_symbols == ["010130", "012450"]
        assert diagnostics.seed_pool_source == "kis_ranking"
        assert diagnostics.seed_pool_count == 2
        assert diagnostics.pre_pool_candidate_count == 2
        assert diagnostics.quote_success_rate == 1.0
        assert diagnostics.filter_pass_rate == 1.0
        assert diagnostics.scored_capture_rate == 1.0
        assert diagnostics.overlay_capture_rate == 1.0

    @pytest.mark.asyncio
    async def test_market_overlay_falls_back_to_core_seed_pool(self) -> None:
        """랭킹 seed가 비면 approved core fallback으로 동작한다."""
        repos = build_in_memory_repositories()
        for sym in ["005930", "000660", "010130"]:
            await repos.instruments.add(_make_instrument(sym))

        class _MockKIS:
            def __init__(self) -> None:
                self.called_symbols: list[str] = []

            async def get_market_overlay_seed_symbols(self, *, limit: int = 60) -> list[str]:
                return []

            async def get_quotes_batch(
                self, symbols: Sequence[str], **kwargs: object
            ) -> dict[str, dict[str, object]]:
                self.called_symbols = list(symbols)
                return {}

        mock_kis = _MockKIS()
        svc = UniverseSelectionService(repos, kis_client=mock_kis)  # type: ignore[arg-type]
        ctx = CompositionContext(
            account_id=FALLBACK_ACCOUNT_ID,
            since=NOW,
            pre_pool_size=2,
        )
        _, diagnostics = await svc.compose_with_diagnostics(ctx)

        assert len(mock_kis.called_symbols) == 2
        assert diagnostics.seed_pool_source == "core_fallback"
        assert diagnostics.seed_pool_count == 3

    @pytest.mark.asyncio
    async def test_market_overlay_fallback_includes_discovery_pool_segment(self) -> None:
        """탐색 풀 segment metadata가 있으면 core가 아니어도 fallback seed에 포함된다."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(
            _make_instrument("005930", metadata={"core_universe": True})
        )
        await repos.instruments.add(
            _make_instrument(
                "123456",
                metadata={
                    "core_universe": False,
                    "market_segment": "KOSDAQ150",
                },
            )
        )

        class _MockKIS:
            def __init__(self) -> None:
                self.called_symbols: list[str] = []

            async def get_market_overlay_seed_symbols(self, *, limit: int = 60) -> list[str]:
                return []

            async def get_quotes_batch(
                self, symbols: Sequence[str], **kwargs: object
            ) -> dict[str, dict[str, object]]:
                self.called_symbols = list(symbols)
                return {}

        mock_kis = _MockKIS()
        svc = UniverseSelectionService(repos, kis_client=mock_kis)  # type: ignore[arg-type]
        ctx = CompositionContext(
            account_id=FALLBACK_ACCOUNT_ID,
            since=NOW,
            pre_pool_size=10,
        )
        _, diagnostics = await svc.compose_with_diagnostics(ctx)

        assert "005930" in mock_kis.called_symbols
        assert "123456" in mock_kis.called_symbols
        assert diagnostics.seed_pool_source == "core_fallback"
        assert diagnostics.seed_pool_count == 2

    @pytest.mark.asyncio
    async def test_market_overlay_fallback_includes_kosdaq_index_membership_seed(self) -> None:
        """KOSDAQ index_memberships가 있으면 discovery fallback seed에 포함된다."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(
            _make_instrument(
                "123456",
                market_code="KOSDAQ",
                metadata={
                    "core_universe": False,
                    "market_segment": "KOSDAQ",
                    "index_memberships": ["KOSDAQ150"],
                },
            )
        )

        class _MockKIS:
            def __init__(self) -> None:
                self.called_symbols: list[str] = []

            async def get_market_overlay_seed_symbols(self, *, limit: int = 60) -> list[str]:
                return []

            async def get_quotes_batch(
                self, symbols: Sequence[str], **kwargs: object
            ) -> dict[str, dict[str, object]]:
                self.called_symbols = list(symbols)
                return {}

        mock_kis = _MockKIS()
        svc = UniverseSelectionService(repos, kis_client=mock_kis)  # type: ignore[arg-type]
        ctx = CompositionContext(
            account_id=FALLBACK_ACCOUNT_ID,
            since=NOW,
            pre_pool_size=10,
        )
        _, diagnostics = await svc.compose_with_diagnostics(ctx)

        assert "123456" in mock_kis.called_symbols
        assert diagnostics.seed_pool_source == "core_fallback"

    @pytest.mark.asyncio
    async def test_market_overlay_fallback_prefers_membership_table_before_metadata_fallback(self) -> None:
        repos = build_in_memory_repositories()
        instrument = _make_instrument(
            "123458",
            market_code="KOSDAQ",
            metadata={
                "core_universe": False,
                "market_segment": "KOSDAQ",
            },
        )
        await repos.instruments.add(instrument)
        await repos.instrument_index_memberships.sync_current_memberships(
            instrument.instrument_id,
            ["KOSDAQ150"],
            effective_from=NOW.date(),
            source_tag="test",
            metadata={"source": "test"},
        )

        class _MockKIS:
            def __init__(self) -> None:
                self.called_symbols: list[str] = []

            async def get_market_overlay_seed_symbols(self, *, limit: int = 60) -> list[str]:
                return []

            async def get_quotes_batch(
                self, symbols: Sequence[str], **kwargs: object
            ) -> dict[str, dict[str, object]]:
                self.called_symbols = list(symbols)
                return {}

        mock_kis = _MockKIS()
        svc = UniverseSelectionService(repos, kis_client=mock_kis)  # type: ignore[arg-type]
        ctx = CompositionContext(
            account_id=FALLBACK_ACCOUNT_ID,
            since=NOW,
            pre_pool_size=10,
        )
        _, diagnostics = await svc.compose_with_diagnostics(ctx)

        assert "123458" in mock_kis.called_symbols
        assert diagnostics.seed_pool_source == "core_fallback"

    @pytest.mark.asyncio
    async def test_market_overlay_fallback_includes_discovery_seed_allowlist(self) -> None:
        """discovery seed allowlist KOSDAQ 종목은 core가 아니어도 fallback seed에 포함된다."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(
            _make_instrument("005930", metadata={"core_universe": True})
        )
        await repos.instruments.add(
            _make_instrument(
                "090150",
                market_code="KOSDAQ",
                metadata={"core_universe": False},
            )
        )

        class _MockKIS:
            def __init__(self) -> None:
                self.called_symbols: list[str] = []

            async def get_market_overlay_seed_symbols(self, *, limit: int = 60) -> list[str]:
                return []

            async def get_quotes_batch(
                self, symbols: Sequence[str], **kwargs: object
            ) -> dict[str, dict[str, object]]:
                self.called_symbols = list(symbols)
                return {}

        mock_kis = _MockKIS()
        svc = UniverseSelectionService(repos, kis_client=mock_kis)  # type: ignore[arg-type]
        ctx = CompositionContext(
            account_id=FALLBACK_ACCOUNT_ID,
            since=NOW,
            pre_pool_size=10,
        )
        _, diagnostics = await svc.compose_with_diagnostics(ctx)

        assert "005930" in mock_kis.called_symbols
        assert "090150" in mock_kis.called_symbols
        assert diagnostics.seed_pool_source == "core_fallback"
        assert diagnostics.seed_pool_count == 2

    @pytest.mark.asyncio
    async def test_market_overlay_adds_top_n(self) -> None:
        """Market overlay가 top-N symbols을 추가함."""
        repos = build_in_memory_repositories()
        for sym in ["005930", "000660", "010130"]:
            await repos.instruments.add(_make_instrument(sym))

        class _MockKIS:
            async def get_quotes_batch(
                self, symbols: Sequence[str], **kwargs: object
            ) -> dict[str, dict[str, object]]:
                # Return mock quotes — 005930 has highest turnover
                return {
                    "005930": {
                        "stck_prpr": "65000",
                        "prdy_ctrt": "2.5",
                        "acml_tr_pbmn": "5000000000000",  # 5조
                        "stck_hgpr": "66000",
                        "stck_oprc": "64000",
                        "stck_lwpr": "63500",
                    },
                    "000660": {
                        "stck_prpr": "120000",
                        "prdy_ctrt": "1.2",
                        "acml_tr_pbmn": "3000000000000",  # 3조
                        "stck_hgpr": "121000",
                        "stck_oprc": "119000",
                        "stck_lwpr": "118500",
                    },
                    "010130": {
                        "stck_prpr": "30000",
                        "prdy_ctrt": "0.5",
                        "acml_tr_pbmn": "500000000000",  # 5000억
                        "stck_hgpr": "30500",
                        "stck_oprc": "29900",
                        "stck_lwpr": "29800",
                    },
                }

        svc = UniverseSelectionService(repos, kis_client=_MockKIS())  # type: ignore[arg-type]
        ctx = CompositionContext(
            account_id=FALLBACK_ACCOUNT_ID,
            since=NOW,
            market_overlay_cap=2,
            pre_pool_size=3,
        )
        result = await svc.compose(ctx)

        market_symbols = [s for s in result if s.source_type == SourceType.MARKET_OVERLAY]
        # market_overlay_cap=2이므로 최대 2개
        assert len(market_symbols) <= 2
        # 적어도 1개 이상의 market overlay symbol이 있어야 함
        assert len(market_symbols) >= 1

    @pytest.mark.asyncio
    async def test_market_overlay_diagnostics_expose_quote_and_filter_rates(self) -> None:
        """quote 성공률과 filter 통과율을 장중 실측용 비율로 노출한다."""
        repos = build_in_memory_repositories()
        for sym in ["005930", "000660", "010130"]:
            await repos.instruments.add(_make_instrument(sym))

        class _MockKIS:
            env = "real"

            async def get_quotes_batch(
                self, symbols: Sequence[str], **kwargs: object
            ) -> dict[str, dict[str, object] | None]:
                return {
                    "005930": {
                        "stck_prpr": "70000",
                        "prdy_ctrt": "4.0",
                        "acml_tr_pbmn": "800000000000",
                        "stck_hgpr": "70500",
                        "stck_oprc": "68000",
                        "stck_lwpr": "67900",
                        "iscd_stat_cls_code": "",
                    },
                    "000660": {
                        "stck_prpr": "200000",
                        "prdy_ctrt": "2.0",
                        "acml_tr_pbmn": "500000000",
                        "stck_hgpr": "201000",
                        "stck_oprc": "196000",
                        "stck_lwpr": "195000",
                        "iscd_stat_cls_code": "",
                    },
                    "010130": None,
                }

        svc = UniverseSelectionService(repos, kis_client=_MockKIS())  # type: ignore[arg-type]
        ctx = CompositionContext(
            account_id=FALLBACK_ACCOUNT_ID,
            since=NOW,
            market_overlay_cap=2,
            pre_pool_size=3,
        )
        _, diagnostics = await svc.compose_with_diagnostics(ctx)

        assert diagnostics.quotes_requested_count == 3
        assert diagnostics.quotes_received_count == 2
        assert diagnostics.filtered_out_count == 1
        assert diagnostics.scored_candidate_count == 1
        assert diagnostics.added_count == 1
        assert diagnostics.quote_success_rate == pytest.approx(2 / 3)
        assert diagnostics.filter_pass_rate == pytest.approx(1 / 2)
        assert diagnostics.scored_capture_rate == 1.0

    @pytest.mark.asyncio
    async def test_partial_quote_failure_does_not_crash(self) -> None:
        """일부 quote 실패 시 compose가 중단되지 않고 정상 동작."""
        repos = build_in_memory_repositories()
        for sym in ["005930", "000660", "010130"]:
            await repos.instruments.add(_make_instrument(sym))

        class _MockKIS:
            async def get_quotes_batch(
                self, symbols: Sequence[str], **kwargs: object
            ) -> dict[str, dict[str, object]]:
                # 000660만 실패 (반환에서 제외)
                return {
                    "005930": {
                        "stck_prpr": "65000",
                        "prdy_ctrt": "2.5",
                        "acml_tr_pbmn": "5000000000000",
                        "stck_hgpr": "66000",
                        "stck_oprc": "64000",
                        "stck_lwpr": "63500",
                    },
                    "010130": {
                        "stck_prpr": "30000",
                        "prdy_ctrt": "0.5",
                        "acml_tr_pbmn": "500000000000",
                        "stck_hgpr": "30500",
                        "stck_oprc": "29900",
                        "stck_lwpr": "29800",
                    },
                }

        svc = UniverseSelectionService(repos, kis_client=_MockKIS())  # type: ignore[arg-type]
        ctx = CompositionContext(
            account_id=FALLBACK_ACCOUNT_ID,
            since=NOW,
            market_overlay_cap=5,
            pre_pool_size=3,
        )
        # compose가 예외 없이 완료되어야 함
        result = await svc.compose(ctx)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_market_overlay_preserves_held_priority(self) -> None:
        """Market overlay symbol이 held position priority를 침범하지 않음."""
        repos = build_in_memory_repositories()
        inst = _make_instrument("005930")
        await repos.instruments.add(inst)
        await repos.instruments.add(_make_instrument("000660"))

        # 005930을 held position으로 추가
        pos = _make_position(instrument_id=inst.instrument_id, quantity=Decimal("10"))
        await repos.position_snapshots.add(pos)

        class _MockKIS:
            async def get_quotes_batch(
                self, symbols: Sequence[str], **kwargs: object
            ) -> dict[str, dict[str, object]]:
                return {
                    "000660": {
                        "stck_prpr": "120000",
                        "prdy_ctrt": "3.5",
                        "acml_tr_pbmn": "3000000000000",
                        "stck_hgpr": "121000",
                        "stck_oprc": "119000",
                        "stck_lwpr": "118500",
                    },
                }

        svc = UniverseSelectionService(repos, kis_client=_MockKIS())  # type: ignore[arg-type]
        ctx = CompositionContext(
            account_id=ACCOUNT_ID,
            since=NOW,
            market_overlay_cap=5,
            pre_pool_size=2,
        )
        result = await svc.compose(ctx)

        # 첫 번째는 HELD_POSITION이어야 함
        assert result[0].source_type == SourceType.HELD_POSITION
        # MARKET_OVERLAY가 존재하면 HELD_POSITION보다 뒤에 있어야 함
        market_indices = [
            i for i, s in enumerate(result) if s.source_type == SourceType.MARKET_OVERLAY
        ]
        if market_indices:
            assert market_indices[0] > 0


# ---------------------------------------------------------------------------
# P2: Score calculation
# ---------------------------------------------------------------------------


class TestMarketScore:
    """``_calc_market_score()`` — P2 composite score pure function."""

    def test_high_turnover_scores_high(self) -> None:
        """거래대금이 높을수록 score가 높음."""
        from agent_trading.services.universe_selection import _calc_market_score

        high = _calc_market_score(MarketDataSnapshot(
            symbol="005930", market="KRX",
            acc_trade_amount=Decimal("5000000000000"),  # 5조
            change_rate=Decimal("2.5"),
            current_price=Decimal("65000"),
            high_price=Decimal("66000"),
        ))
        low = _calc_market_score(MarketDataSnapshot(
            symbol="010130", market="KRX",
            acc_trade_amount=Decimal("500000000000"),  # 5000억
            change_rate=Decimal("0.5"),
            current_price=Decimal("30000"),
            high_price=Decimal("30500"),
        ))
        assert high > low

    def test_all_none_returns_zero(self) -> None:
        """모든 필드가 None이면 score=0."""
        from agent_trading.services.universe_selection import _calc_market_score

        score = _calc_market_score(MarketDataSnapshot(
            symbol="005930", market="KRX",
        ))
        assert score == 0.0

    def test_near_high_boost(self) -> None:
        """당일 고가에 근접할수록 score가 높음."""
        from agent_trading.services.universe_selection import _calc_market_score

        near = _calc_market_score(MarketDataSnapshot(
            symbol="005930", market="KRX",
            current_price=Decimal("65000"),
            high_price=Decimal("65500"),  # 99.2% 근접
            acc_trade_amount=Decimal("1000000000000"),
            change_rate=Decimal("1.0"),
        ))
        far = _calc_market_score(MarketDataSnapshot(
            symbol="005930", market="KRX",
            current_price=Decimal("50000"),
            high_price=Decimal("65500"),  # 76.3% — 80% 미만
            acc_trade_amount=Decimal("1000000000000"),
            change_rate=Decimal("1.0"),
        ))
        assert near > far


# ---------------------------------------------------------------------------
# P2: Liquidity Filter F4 + F5
# ---------------------------------------------------------------------------


class TestLiquidityFilterP2:
    """P2 Liquidity Filter 확장 (F4, F5)."""

    def test_f4_none_passes(self) -> None:
        """iscd_stat_cls_code가 None이면 PASS."""
        from agent_trading.services.universe_selection import _check_iscd_stat_cls_code

        result = _check_iscd_stat_cls_code(None)
        assert result.passed is True

    def test_f4_empty_passes(self) -> None:
        """iscd_stat_cls_code가 empty string이면 PASS."""
        from agent_trading.services.universe_selection import _check_iscd_stat_cls_code

        result = _check_iscd_stat_cls_code("")
        assert result.passed is True

    def test_f4_suspended_rejected(self) -> None:
        """알려진 정지 코드는 REJECT."""
        from agent_trading.services.universe_selection import _check_iscd_stat_cls_code

        for code in ("01", "02", "03", "04", "05"):
            result = _check_iscd_stat_cls_code(code)
            assert result.passed is False
            assert result.fail_reason is not None
            assert "suspended_status" in result.fail_reason

    def test_f4_unknown_code_passes_guarded(self) -> None:
        """알 수 없는 코드는 guarded PASS."""
        from agent_trading.services.universe_selection import _check_iscd_stat_cls_code

        result = _check_iscd_stat_cls_code("99")
        assert result.passed is True

    def test_f5_none_passes(self) -> None:
        """acml_tr_pbmn이 None이면 PASS."""
        from agent_trading.services.universe_selection import _check_acc_trade_amount

        result = _check_acc_trade_amount(None)
        assert result.passed is True

    def test_f5_below_threshold_rejected(self) -> None:
        """threshold 미만이면 REJECT."""
        from agent_trading.services.universe_selection import _check_acc_trade_amount

        result = _check_acc_trade_amount(
            Decimal("500000000"),  # 5억 < 10억
            threshold=Decimal("1000000000"),
        )
        assert result.passed is False
        assert "low_volume" in (result.fail_reason or "")

    def test_f5_above_threshold_passes(self) -> None:
        """threshold 이상이면 PASS."""
        from agent_trading.services.universe_selection import _check_acc_trade_amount

        result = _check_acc_trade_amount(
            Decimal("2000000000"),  # 20억 >= 10억
            threshold=Decimal("1000000000"),
        )
        assert result.passed is True


# ---------------------------------------------------------------------------
# P2: MarketDataSnapshot parsing
# ---------------------------------------------------------------------------


class TestParseQuoteToSnapshot:
    """``_parse_quote_to_snapshot()`` — KIS 응답 파싱."""

    def test_parse_valid_response(self) -> None:
        """정상 KIS 응답을 올바르게 파싱."""
        from agent_trading.services.universe_selection import _parse_quote_to_snapshot

        raw = {
            "stck_prpr": "65000",
            "prdy_ctrt": "2.50",
            "acml_tr_pbmn": "5000000000000",
            "stck_hgpr": "66000",
            "stck_lwpr": "63500",
            "stck_oprc": "64000",
            "iscd_stat_cls_code": "",
        }
        snapshot = _parse_quote_to_snapshot("005930", "KRX", raw)

        assert snapshot.symbol == "005930"
        assert snapshot.market == "KRX"
        assert snapshot.current_price == Decimal("65000")
        assert snapshot.change_rate == Decimal("2.50")
        assert snapshot.acc_trade_amount == Decimal("5000000000000")
        assert snapshot.high_price == Decimal("66000")
        assert snapshot.low_price == Decimal("63500")
        assert snapshot.open_price == Decimal("64000")
        assert snapshot.iscd_stat_cls_code == ""

    def test_parse_missing_fields(self) -> None:
        """누락된 필드는 None으로 처리."""
        from agent_trading.services.universe_selection import _parse_quote_to_snapshot

        raw: dict[str, object] = {}
        snapshot = _parse_quote_to_snapshot("005930", "KRX", raw)

        assert snapshot.current_price is None
        assert snapshot.change_rate is None
        assert snapshot.acc_trade_amount is None
        assert snapshot.high_price is None
        assert snapshot.iscd_stat_cls_code is None

    def test_parse_comma_separated_numbers(self) -> None:
        """콤마가 포함된 숫자 문자열도 정상 파싱."""
        from agent_trading.services.universe_selection import _parse_quote_to_snapshot

        raw = {
            "stck_prpr": "65,000",
            "acml_tr_pbmn": "5,000,000,000,000",
        }
        snapshot = _parse_quote_to_snapshot("005930", "KRX", raw)

        assert snapshot.current_price == Decimal("65000")
        assert snapshot.acc_trade_amount == Decimal("5000000000000")


# ---------------------------------------------------------------------------
# P2: CompositionContext defaults
# ---------------------------------------------------------------------------


class TestCompositionContextP2:
    """``CompositionContext`` P2 필드 기본값."""

    def test_market_overlay_cap_default(self) -> None:
        """market_overlay_cap 기본값은 5."""
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        assert ctx.market_overlay_cap == 5

    def test_pre_pool_size_default(self) -> None:
        """pre_pool_size 기본값은 50."""
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        assert ctx.pre_pool_size == 50

    def test_core_cap_default(self) -> None:
        """core_cap 기본값은 None."""
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        assert ctx.core_cap is None

    def test_event_overlay_cap_default(self) -> None:
        """event_overlay_cap 기본값은 None."""
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        assert ctx.event_overlay_cap is None

    def test_reconciliation_overlay_reserve_default(self) -> None:
        """reconciliation_overlay_reserve 기본값은 None."""
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        assert ctx.reconciliation_overlay_reserve is None

    def test_custom_values(self) -> None:
        """커스텀 값 전달 가능."""
        ctx = CompositionContext(
            account_id=FALLBACK_ACCOUNT_ID,
            since=NOW,
            core_cap=15,
            event_overlay_cap=4,
            market_overlay_cap=10,
            reconciliation_overlay_reserve=3,
            pre_pool_size=100,
        )
        assert ctx.core_cap == 15
        assert ctx.event_overlay_cap == 4
        assert ctx.market_overlay_cap == 10
        assert ctx.reconciliation_overlay_reserve == 3
        assert ctx.pre_pool_size == 100


# ---------------------------------------------------------------------------
# Held position — _add_held_positions 단위 테스트
# ---------------------------------------------------------------------------


class TestAddHeldPositions:
    """``_add_held_positions()`` 단위 검증.

    실제 계정의 포지션 스냅샷 기준으로 held_position이 추가되는지,
    source_type='held_position'이 정상 전파되는지 검증.
    """

    @pytest.mark.asyncio
    async def test_add_held_positions_with_real_account(self) -> None:
        """실제 계정의 포지션 스냅샷 기준으로 held_position이 추가되는지 검증."""
        repos = build_in_memory_repositories()
        inst = _make_instrument("005930")
        await repos.instruments.add(inst)
        pos = _make_position(instrument_id=inst.instrument_id, quantity=Decimal("10"))
        await repos.position_snapshots.add(pos)

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        # held_position source_type이 포함되어야 함
        held = [s for s in result if s.source_type == SourceType.HELD_POSITION]
        assert len(held) >= 1
        assert held[0].symbol == "005930"
        assert held[0].inclusion_reason == INCLUSION_REASON_HELD

    @pytest.mark.asyncio
    async def test_add_held_positions_fallback_account_no_positions(self) -> None:
        """Fallback 계정(FALLBACK_ACCOUNT_ID)으로는 held_position이 추가되지 않음."""
        repos = build_in_memory_repositories()
        inst = _make_instrument("005930")
        await repos.instruments.add(inst)
        pos = _make_position(instrument_id=inst.instrument_id, quantity=Decimal("10"))
        await repos.position_snapshots.add(pos)

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        # fallback 계정에는 포지션이 없으므로 HELD_POSITION이 없어야 함
        held = [s for s in result if s.source_type == SourceType.HELD_POSITION]
        assert len(held) == 0

    @pytest.mark.asyncio
    async def test_multiple_held_positions(self) -> None:
        """여러 보유 포지션이 모두 HELD_POSITION으로 추가되는지 검증."""
        repos = build_in_memory_repositories()
        inst1 = _make_instrument("005930")
        inst2 = _make_instrument("000660")
        await repos.instruments.add(inst1)
        await repos.instruments.add(inst2)
        await repos.position_snapshots.add(
            _make_position(instrument_id=inst1.instrument_id, quantity=Decimal("5"))
        )
        await repos.position_snapshots.add(
            _make_position(instrument_id=inst2.instrument_id, quantity=Decimal("3"))
        )

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        held_symbols = {s.symbol for s in result if s.source_type == SourceType.HELD_POSITION}
        assert "005930" in held_symbols
        assert "000660" in held_symbols


# ---------------------------------------------------------------------------
# SourceType 전파 검증 — UniverseSymbol → trade_decision.source_type
# ---------------------------------------------------------------------------


class TestSourceTypePropagation:
    """``UniverseSymbol.source_type`` → request metadata → trade_decision.source_type 경로 검증.

    ``compose()``가 반환한 ``SelectedSymbol``의 ``source_type``이
    ``UniverseSymbol``로 올바르게 전파되는지 확인.
    """

    @pytest.mark.asyncio
    async def test_source_type_propagation_core(self) -> None:
        """Core source_type이 UniverseSymbol에 올바르게 전파됨."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(_make_instrument("005930"))

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        core = [s for s in result if s.symbol == "005930"]
        assert len(core) == 1
        assert core[0].source_type == SourceType.CORE

    @pytest.mark.asyncio
    async def test_source_type_propagation_held(self) -> None:
        """Held_position source_type이 UniverseSymbol에 올바르게 전파됨."""
        repos = build_in_memory_repositories()
        inst = _make_instrument("005930")
        await repos.instruments.add(inst)
        await repos.position_snapshots.add(
            _make_position(instrument_id=inst.instrument_id, quantity=Decimal("10"))
        )

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        held = [s for s in result if s.symbol == "005930"]
        assert len(held) == 1
        assert held[0].source_type == SourceType.HELD_POSITION

    @pytest.mark.asyncio
    async def test_source_type_propagation_event(self) -> None:
        """Event_overlay source_type이 UniverseSymbol에 올바르게 전파됨."""
        repos = build_in_memory_repositories()
        await repos.instruments.add(_make_instrument("005930"))
        await repos.external_events.add(_make_event("005930", severity="high"))

        svc = UniverseSelectionService(repos)
        ctx = CompositionContext(account_id=FALLBACK_ACCOUNT_ID, since=NOW)
        result = await svc.compose(ctx)

        event = [s for s in result if s.symbol == "005930"]
        assert len(event) == 1
        assert event[0].source_type == SourceType.EVENT_OVERLAY
