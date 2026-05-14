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

from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import (
    ExternalEventEntity,
    InstrumentEntity,
    PositionSnapshotEntity,
)
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
) -> InstrumentEntity:
    return InstrumentEntity(
        instrument_id=uuid4(),
        symbol=symbol,
        market_code=market_code,
        name=f"Test-{symbol}",
        is_active=is_active,
        asset_class="KR_STOCK",
        currency="KRW",
        tick_size=tick_size,
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


# ---------------------------------------------------------------------------
# SourceType priority
# ---------------------------------------------------------------------------


class TestSourceTypePriority:
    """``SourceType.priority`` — 우선순위 정수 매핑."""

    def test_held_position_highest_priority(self) -> None:
        """HELD_POSITION이 가장 높은 우선순위(0)를 가져야 함."""
        assert SourceType.HELD_POSITION.priority == 0

    def test_event_overlay_priority(self) -> None:
        """EVENT_OVERLAY 우선순위는 1."""
        assert SourceType.EVENT_OVERLAY.priority == 1

    def test_market_overlay_priority(self) -> None:
        """MARKET_OVERLAY 우선순위는 2."""
        assert SourceType.MARKET_OVERLAY.priority == 2

    def test_manual_priority(self) -> None:
        """MANUAL 우선순위는 3."""
        assert SourceType.MANUAL.priority == 3

    def test_core_lowest_priority(self) -> None:
        """CORE가 가장 낮은 우선순위(4)를 가져야 함."""
        assert SourceType.CORE.priority == 4

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
        assert "high_importance_event" in event[0].inclusion_reason

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
    async def test_empty_universe_returns_empty_list(self) -> None:
        """DB에 instrument가 없으면 빈 리스트 반환."""
        repos = build_in_memory_repositories()
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

    def test_custom_values(self) -> None:
        """커스텀 값 전달 가능."""
        ctx = CompositionContext(
            account_id=FALLBACK_ACCOUNT_ID,
            since=NOW,
            market_overlay_cap=10,
            pre_pool_size=100,
        )
        assert ctx.market_overlay_cap == 10
        assert ctx.pre_pool_size == 100
