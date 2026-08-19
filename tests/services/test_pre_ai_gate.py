"""Tests for ``pre_ai_gate.py``의 held_position 스킵(HELD_POSITION_RECENT_HOLD_NO_CHANGE).

배경(2026-08-19): 이 스킵은 ``HELD_POSITION_SKIP_HOLD_TTL``(20분)을
"직전 판단이 hold였는가"를 조회하는 lookback으로도 그대로 썼는데,
실측(오늘 held_position 4개 종목 전부)상 decision loop 사이클 간격이
항상 31~35분(운영 설정 30분 + 실행 오버헤드)이라 20분 lookback에
직전 사이클의 판단이 단 한 번도 걸리지 않았다 — 이 스킵이 최근
구조적으로 0건만 기록된 근본 원인이었다(``guardrail_evaluations``
실측으로 확인, seeded news 가설은 반증됨 — 같은 실측에서
``recent_events``는 매 사이클 0건으로 정상이었다).

이 파일은 새로 도입한 ``HELD_POSITION_SKIP_HOLD_NO_CHANGE_LOOKBACK``
(40분, 이 판정 전용)이 실제로 문제를 고치는지, 그리고 buy/sell
reverse-trade 쿨다운(``HELD_POSITION_SKIP_HOLD_TTL``, 20분 그대로)에는
영향을 주지 않는지를 검증한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from agent_trading.domain.entities import TradeDecisionEntity
from agent_trading.domain.enums import DecisionType, EntryStyle, OrderSide
from agent_trading.services import pre_ai_gate


def _make_hold_decision(*, created_at: datetime, symbol: str) -> TradeDecisionEntity:
    """``held_position`` + ``HOLD`` + ``side=buy`` 판단 1건(테스트용 최소 구성)."""
    return TradeDecisionEntity(
        trade_decision_id=uuid4(),
        decision_context_id=None,
        decision_type=DecisionType.HOLD,
        side=OrderSide.BUY,
        strategy_id=uuid4(),
        symbol=symbol,
        market="KRX",
        entry_style=EntryStyle.LIMIT,
        created_at=created_at,
        source_type="held_position",
    )


class _FakeRepos:
    """``evaluate_held_position_skip_reason()``가 필요로 하는 최소 repos stub."""

    def __init__(self, *, decisions: list[TradeDecisionEntity]) -> None:
        self.trade_decisions = AsyncMock()
        self.trade_decisions.list_all = AsyncMock(return_value=decisions)
        self.external_events = AsyncMock()
        self.external_events.list_by_symbol = AsyncMock(return_value=())
        self.orders = AsyncMock()
        self.orders.list = AsyncMock(return_value=[])


class TestHeldPositionHoldNoChangeLookback:
    """``HELD_POSITION_SKIP_HOLD_NO_CHANGE_LOOKBACK`` 도입 효과 검증."""

    @pytest.fixture
    def now_utc(self) -> datetime:
        # 05:00 UTC = 14:00 KST — HELD_POSITION_SKIP_DISABLE_AFTER(14:30 KST)
        # 이전이어야 pre-AI 스킵 로직 자체가 비활성화되지 않는다.
        return datetime(2026, 8, 19, 5, 0, 0, tzinfo=timezone.utc)

    async def test_hold_32min_ago_now_triggers_skip(self, now_utc: datetime) -> None:
        """수정 후: 32분 전 hold 판단 + 최근 이벤트/주문 없음 → 스킵 발동해야 한다.

        32분은 새 lookback(40분) 안이지만 기존 HELD_POSITION_SKIP_HOLD_TTL
        (20분) 밖이다 — 이 테스트가 통과하면 곧 이번 수정의 핵심 효과다.
        """
        symbol = "196170"
        decision = _make_hold_decision(
            created_at=now_utc - timedelta(minutes=32), symbol=symbol,
        )
        repos = _FakeRepos(decisions=[decision])

        stop_reason, details = await pre_ai_gate.evaluate_held_position_skip_reason(
            repos,
            account_id=uuid4(),
            instrument_id=None,
            symbol=symbol,
            matched_qty=Decimal("10"),
            db_conn=None,
            now_utc=now_utc,
        )

        assert stop_reason == "held_position_recent_hold_no_change"
        assert details["latest_held_decision_type"] == "hold"

    async def test_hold_32min_ago_did_not_trigger_under_old_ttl(
        self, now_utc: datetime, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """(버그 재현) 옛 20분 TTL을 이 판정에 그대로 썼다면 32분 전 판단은
        절대 걸리지 않았을 것 — 이번 수정의 필요성 자체를 증명하는 대조군."""
        monkeypatch.setattr(
            pre_ai_gate,
            "HELD_POSITION_SKIP_HOLD_NO_CHANGE_LOOKBACK",
            pre_ai_gate.HELD_POSITION_SKIP_HOLD_TTL,  # 20분으로 되돌림
        )
        symbol = "196170"
        decision = _make_hold_decision(
            created_at=now_utc - timedelta(minutes=32), symbol=symbol,
        )
        repos = _FakeRepos(decisions=[decision])

        stop_reason, details = await pre_ai_gate.evaluate_held_position_skip_reason(
            repos,
            account_id=uuid4(),
            instrument_id=None,
            symbol=symbol,
            matched_qty=Decimal("10"),
            db_conn=None,
            now_utc=now_utc,
        )

        assert stop_reason is None
        assert details["latest_held_decision_type"] is None

    async def test_hold_45min_ago_still_does_not_trigger(self, now_utc: datetime) -> None:
        """45분 전 판단은 새 lookback(40분)도 벗어나므로 여전히 스킵되면 안
        된다 — TTL을 무한정 늘린 게 아님을 확인하는 회귀 테스트."""
        symbol = "196170"
        decision = _make_hold_decision(
            created_at=now_utc - timedelta(minutes=45), symbol=symbol,
        )
        repos = _FakeRepos(decisions=[decision])

        stop_reason, details = await pre_ai_gate.evaluate_held_position_skip_reason(
            repos,
            account_id=uuid4(),
            instrument_id=None,
            symbol=symbol,
            matched_qty=Decimal("10"),
            db_conn=None,
            now_utc=now_utc,
        )

        assert stop_reason is None
        assert details["latest_held_decision_type"] is None

    async def test_recent_event_still_blocks_skip_regardless_of_lookback(
        self, now_utc: datetime,
    ) -> None:
        """최근 이벤트가 있으면(30분 이내) lookback 확대와 무관하게 여전히
        스킵하지 않아야 한다 — 이번 수정이 이벤트 판정 자체는 손대지
        않았음을 확인."""
        symbol = "196170"
        decision = _make_hold_decision(
            created_at=now_utc - timedelta(minutes=32), symbol=symbol,
        )
        repos = _FakeRepos(decisions=[decision])
        repos.external_events.list_by_symbol = AsyncMock(
            return_value=(object(),)  # 최근 이벤트 1건 존재
        )

        stop_reason, _details = await pre_ai_gate.evaluate_held_position_skip_reason(
            repos,
            account_id=uuid4(),
            instrument_id=None,
            symbol=symbol,
            matched_qty=Decimal("10"),
            db_conn=None,
            now_utc=now_utc,
        )

        assert stop_reason is None

    async def test_reduce_decision_type_unaffected_by_hold_lookback_widening(
        self, now_utc: datetime,
    ) -> None:
        """decision_type이 hold가 아니면(예: reduce) lookback이 넓어져도
        HELD_POSITION_RECENT_HOLD_NO_CHANGE는 발동하지 않는다 — 이 판정이
        오직 'hold' 케이스에만 적용됨을 재확인(회귀 없음)."""
        symbol = "196170"
        decision = TradeDecisionEntity(
            trade_decision_id=uuid4(),
            decision_context_id=None,
            decision_type=DecisionType.REDUCE,
            side=OrderSide.BUY,
            strategy_id=uuid4(),
            symbol=symbol,
            market="KRX",
            entry_style=EntryStyle.LIMIT,
            created_at=now_utc - timedelta(minutes=32),
            source_type="held_position",
        )
        repos = _FakeRepos(decisions=[decision])

        stop_reason, details = await pre_ai_gate.evaluate_held_position_skip_reason(
            repos,
            account_id=uuid4(),
            instrument_id=None,
            symbol=symbol,
            matched_qty=Decimal("10"),
            db_conn=None,
            now_utc=now_utc,
        )

        assert stop_reason is None
        assert details["latest_held_decision_type"] == "reduce"
