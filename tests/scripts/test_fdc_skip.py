"""Tests for ``_check_fdc_skip()`` — FDC 생략 조건 판정 로직.

``_check_fdc_skip()``는 EI/AR 실행 후 FDC(FinalDecisionComposer) 호출 전에
비행동(non-actionable) 조건을 검사하여 FDC API 호출을 생략한다.

Test coverage
-------------
* 조건 1: risk_opinion == "reject" → HOLD
* 조건 2: no_material_events + 미보유 → HOLD
* 조건 3: 최근 이벤트 0건 + 미보유 → HOLD
* 조건 4: orderable_amount <= 0 + 미보유 → WATCH
* 생략 불가: has_position이면 조건 2/3/4에서도 skip=False
* 생략 불가: 모든 조건 통과 → skip=False
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import (
    CashBalanceSnapshotEntity,
    PositionSnapshotEntity,
)
from agent_trading.services.ai_agents.base import AgentExecutionRequest
from agent_trading.services.ai_agents.schemas import (
    AIRiskOutput,
    AggregateEventView,
    EventInterpretationOutput,
    FinalDecisionComposerOutput,
)
from agent_trading.services.decision_orchestrator import AssembledContext
from scripts.run_agent_subprocess import AgentSubprocessInput, _check_fdc_skip


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def sample_subprocess_input() -> AgentSubprocessInput:
    """기본 AgentSubprocessInput fixture."""
    return AgentSubprocessInput(
        decision_context_id=None,
        correlation_id="test-fdc-skip",
        symbol="005930",
        market="KRX",
        source_type="core",
    )


@pytest.fixture
def default_event_output() -> EventInterpretationOutput:
    """기본 EventInterpretationOutput — no_material_events=False."""
    return EventInterpretationOutput(
        agent_name="event_interpretation",
        schema_version="v1",
        symbol="005930",
        aggregate_view=AggregateEventView(
            overall_bias="neutral",
            event_conflict=False,
            top_reason_codes=(),
            opposing_evidence=(),
            evidence_strength="none",
            event_count=5,
            no_material_events=False,
        ),
    )


@pytest.fixture
def no_material_event_output() -> EventInterpretationOutput:
    """no_material_events=True인 EventInterpretationOutput."""
    return EventInterpretationOutput(
        agent_name="event_interpretation",
        schema_version="v1",
        symbol="005930",
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


@pytest.fixture
def risk_allow_output() -> AIRiskOutput:
    """risk_opinion="allow"인 AIRiskOutput."""
    return AIRiskOutput(
        agent_name="ai_risk",
        schema_version="v1",
        risk_opinion="allow",
        risk_score=0.3,
        confidence=0.85,
    )


@pytest.fixture
def risk_reject_output() -> AIRiskOutput:
    """risk_opinion="reject"인 AIRiskOutput."""
    return AIRiskOutput(
        agent_name="ai_risk",
        schema_version="v1",
        risk_opinion="reject",
        risk_score=0.9,
        confidence=0.95,
        reason_codes=("high_volatility", "concentration_risk"),
    )


def _make_empty_context(source_type: str = "core") -> AssembledContext:
    """보유 포지션/현금/이벤트가 없는 빈 컨텍스트."""
    return AssembledContext(
        source_type=source_type,
        recent_events=(),
        position_snapshot=None,
        cash_balance_snapshot=None,
    )


def _make_position_context(
    quantity: Decimal = Decimal("10"),
    avg_price: Decimal = Decimal("50000"),
    source_type: str = "core",
) -> AssembledContext:
    """보유 포지션이 있는 컨텍스트."""
    return AssembledContext(
        source_type=source_type,
        recent_events=(),
        position_snapshot=PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=uuid4(),
            instrument_id=uuid4(),
            quantity=quantity,
            average_price=avg_price,
            market_price=avg_price,
            unrealized_pnl=Decimal("0"),
            source_of_truth="KIS",
            snapshot_at=datetime.now(timezone.utc),
        ),
        cash_balance_snapshot=None,
    )


def _make_cash_shortage_context(
    orderable_amount: Decimal = Decimal("0"),
    include_event: bool = False,
) -> AssembledContext:
    """주문 가능 잔고가 부족한 컨텍스트.

    Parameters
    ----------
    orderable_amount
        주문 가능 잔고. 0 이하이면 조건 4(cash_shortage) 발동.
    include_event
        True이면 최근 이벤트 1건 포함 (조건 3 우회).
    """
    from agent_trading.domain.entities import ExternalEventEntity
    events: tuple = ()
    if include_event:
        events = (ExternalEventEntity(
            event_id=uuid4(),
            event_type="earnings",
            source_name="NAVER",
            published_at=datetime.now(timezone.utc),
            source_reliability_tier="tier1",
            headline="테스트 뉴스",
            symbol="005930",
            ingested_at=datetime.now(timezone.utc),
        ),)
    return AssembledContext(
        source_type="core",
        recent_events=events,
        position_snapshot=None,
        cash_balance_snapshot=CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=uuid4(),
            currency="KRW",
            available_cash=Decimal("0"),
            settled_cash=Decimal("0"),
            unsettled_cash=Decimal("0"),
            source_of_truth="KIS",
            snapshot_at=datetime.now(timezone.utc),
            total_asset=Decimal("1000000"),
            orderable_amount=orderable_amount,
        ),
    )


# =========================================================================
# Test: Condition 1 — Risk "reject"
# =========================================================================


class TestFdcSkipRiskReject:
    """risk_opinion == "reject" → 결정론적 HOLD."""

    def test_risk_reject_returns_hold(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        default_event_output: EventInterpretationOutput,
        risk_reject_output: AIRiskOutput,
    ) -> None:
        """Risk reject이면 skip=True, reason="risk_reject", decision_type=HOLD."""
        context = _make_empty_context()
        request = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="test",
            context=context,
        )
        skip, reason, output = _check_fdc_skip(
            sample_subprocess_input, request,
            default_event_output, risk_reject_output,
        )
        assert skip is True
        assert reason == "risk_reject"
        assert output.decision_type == "HOLD"
        assert "reject" in output.summary

    def test_risk_reject_even_with_position(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        default_event_output: EventInterpretationOutput,
        risk_reject_output: AIRiskOutput,
    ) -> None:
        """Risk reject이면 포지션 보유 여부와 무관하게 skip."""
        context = _make_position_context()
        request = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="test",
            context=context,
        )
        skip, reason, output = _check_fdc_skip(
            sample_subprocess_input, request,
            default_event_output, risk_reject_output,
        )
        assert skip is True
        assert reason == "risk_reject"
        assert output.decision_type == "HOLD"


# =========================================================================
# Test: Condition 2 — No material events + no position
# =========================================================================


class TestFdcSkipNoMaterialEvents:
    """no_material_events + 미보유 → 결정론적 HOLD."""

    def test_no_material_no_position(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        no_material_event_output: EventInterpretationOutput,
        risk_allow_output: AIRiskOutput,
    ) -> None:
        """no_material_events=True + 미보유 → skip."""
        context = _make_empty_context()
        request = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="test",
            context=context,
        )
        skip, reason, output = _check_fdc_skip(
            sample_subprocess_input, request,
            no_material_event_output, risk_allow_output,
        )
        assert skip is True
        assert reason == "no_material_events_no_position"
        assert output.decision_type == "HOLD"

    def test_no_material_with_position(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        no_material_event_output: EventInterpretationOutput,
        risk_allow_output: AIRiskOutput,
    ) -> None:
        """no_material_events=True지만 보유 중이면 skip=False."""
        context = _make_position_context()
        request = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="test",
            context=context,
        )
        skip, reason, output = _check_fdc_skip(
            sample_subprocess_input, request,
            no_material_event_output, risk_allow_output,
        )
        assert skip is False
        assert reason == ""


# =========================================================================
# Test: Condition 3 — No recent events + no position
# =========================================================================


class TestFdcSkipNoEvents:
    """최근 이벤트 0건 + 미보유 → 결정론적 HOLD."""

    def test_no_events_no_position(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        default_event_output: EventInterpretationOutput,
        risk_allow_output: AIRiskOutput,
    ) -> None:
        """recent_events=() + 미보유 → skip."""
        context = _make_empty_context()
        request = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="test",
            context=context,
        )
        skip, reason, output = _check_fdc_skip(
            sample_subprocess_input, request,
            default_event_output, risk_allow_output,
        )
        assert skip is True
        assert reason == "no_events_no_position"
        assert output.decision_type == "HOLD"

    def test_no_events_with_position(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        default_event_output: EventInterpretationOutput,
        risk_allow_output: AIRiskOutput,
    ) -> None:
        """recent_events=()지만 보유 중이면 skip=False."""
        context = _make_position_context()
        request = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="test",
            context=context,
        )
        skip, reason, output = _check_fdc_skip(
            sample_subprocess_input, request,
            default_event_output, risk_allow_output,
        )
        assert skip is False
        assert reason == ""


# =========================================================================
# Test: Condition 4 — Cash shortage + no position
# =========================================================================


class TestFdcSkipCashShortage:
    """orderable_amount <= 0 + 미보유 → 결정론적 WATCH."""

    @pytest.mark.parametrize("orderable_amount", [
        Decimal("0"),
        Decimal("-1000"),
    ])
    def test_cash_shortage_no_position(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        default_event_output: EventInterpretationOutput,
        risk_allow_output: AIRiskOutput,
        orderable_amount: Decimal,
    ) -> None:
        """orderable_amount<=0 + 미보유 → skip (WATCH).

        조건 3(no_events + no_position) 우회를 위해 이벤트 1건 포함.
        """
        context = _make_cash_shortage_context(
            orderable_amount=orderable_amount, include_event=True,
        )
        request = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="test",
            context=context,
        )
        skip, reason, output = _check_fdc_skip(
            sample_subprocess_input, request,
            default_event_output, risk_allow_output,
        )
        assert skip is True
        assert reason == "cash_shortage"
        assert output.decision_type == "WATCH"
        assert output.confidence == 0.5
        assert "orderable_amount" in output.summary

    def test_cash_shortage_with_position(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        default_event_output: EventInterpretationOutput,
        risk_allow_output: AIRiskOutput,
    ) -> None:
        """orderable_amount<=0지만 보유 중이면 skip=False.

        조건 3(no_events + no_position) 우회를 위해 이벤트 1건 포함.
        """
        context = _make_cash_shortage_context(
            orderable_amount=Decimal("0"), include_event=True,
        )
        # Override position — 보유 포지션 추가
        context = AssembledContext(
            source_type=context.source_type,
            recent_events=context.recent_events,
            position_snapshot=PositionSnapshotEntity(
                position_snapshot_id=uuid4(),
                account_id=uuid4(),
                instrument_id=uuid4(),
                quantity=Decimal("10"),
                average_price=Decimal("50000"),
                market_price=Decimal("50000"),
                unrealized_pnl=Decimal("0"),
                source_of_truth="KIS",
                snapshot_at=datetime.now(timezone.utc),
            ),
            cash_balance_snapshot=context.cash_balance_snapshot,
        )
        request = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="test",
            context=context,
        )
        skip, reason, output = _check_fdc_skip(
            sample_subprocess_input, request,
            default_event_output, risk_allow_output,
        )
        assert skip is False
        assert reason == ""

    def test_cash_shortage_none_orderable(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        default_event_output: EventInterpretationOutput,
        risk_allow_output: AIRiskOutput,
    ) -> None:
        """orderable_amount=None이면 조건 4 미적용 → 조건 3(no_events) 발동."""
        context = _make_cash_shortage_context(
            orderable_amount=Decimal("0"), include_event=False,
        )
        # cash_balance_snapshot이 None이면 조건 4 통과
        context = AssembledContext(
            source_type=context.source_type,
            recent_events=(),
            position_snapshot=None,
            cash_balance_snapshot=None,
        )
        request = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="test",
            context=context,
        )
        skip, reason, output = _check_fdc_skip(
            sample_subprocess_input, request,
            default_event_output, risk_allow_output,
        )
        # cash_balance_snapshot=None이므로 조건 4 미적용.
        # 대신 조건 3 (no_events + no_position)이 먼저 적용되어야 함
        assert skip is True
        assert reason == "no_events_no_position"


# =========================================================================
# Test: No skip — eligible for FDC
# =========================================================================


class TestFdcSkipEligible:
    """모든 조건 통과 → FDC 정상 호출."""

    def test_allow_with_events(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        risk_allow_output: AIRiskOutput,
    ) -> None:
        """risk=allow + 이벤트 존재 + 포지션 없음 + 현금 있음 → skip=False."""
        from agent_trading.domain.entities import ExternalEventEntity
        event = ExternalEventEntity(
            event_id=uuid4(),
            event_type="earnings",
            source_name="NAVER",
            published_at=datetime.now(timezone.utc),
            source_reliability_tier="tier1",
            headline="테스트 뉴스",
            symbol="005930",
            ingested_at=datetime.now(timezone.utc),
        )
        context = AssembledContext(
            source_type="core",
            recent_events=(event,),
            position_snapshot=None,
            cash_balance_snapshot=CashBalanceSnapshotEntity(
                cash_balance_snapshot_id=uuid4(),
                account_id=uuid4(),
                currency="KRW",
                available_cash=Decimal("10000000"),
                settled_cash=Decimal("10000000"),
                unsettled_cash=Decimal("0"),
                source_of_truth="KIS",
                snapshot_at=datetime.now(timezone.utc),
                total_asset=Decimal("10000000"),
                orderable_amount=Decimal("5000000"),
            ),
        )
        ei_output = EventInterpretationOutput(
            agent_name="event_interpretation",
            schema_version="v1",
            symbol="005930",
            aggregate_view=AggregateEventView(
                overall_bias="bullish",
                event_conflict=False,
                top_reason_codes=("positive_earnings",),
                opposing_evidence=(),
                evidence_strength="moderate",
                event_count=1,
                no_material_events=False,
            ),
        )
        request = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="test",
            context=context,
        )
        skip, reason, output = _check_fdc_skip(
            sample_subprocess_input, request,
            ei_output, risk_allow_output,
        )
        assert skip is False
        assert reason == ""

    def test_allow_with_position_and_no_events(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        default_event_output: EventInterpretationOutput,
        risk_allow_output: AIRiskOutput,
    ) -> None:
        """보유 포지션 있으면 조건 2/3/4 모두 우회 → skip=False."""
        context = _make_position_context()
        request = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="test",
            context=context,
        )
        skip, reason, output = _check_fdc_skip(
            sample_subprocess_input, request,
            default_event_output, risk_allow_output,
        )
        assert skip is False
        assert reason == ""
