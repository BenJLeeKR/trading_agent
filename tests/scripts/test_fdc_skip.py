"""Tests for ``_check_fdc_skip()`` — FDC 생략 조건 판정 로직.

``_check_fdc_skip()``는 EI/AR 실행 후 FDC(FinalDecisionComposer) 호출 전에
비행동(non-actionable) 조건을 검사하여 FDC API 호출을 생략한다.

Test coverage
-------------
* 조건 1: risk_opinion == "reject" → HOLD
* 조건 2: no_material_events + 미보유 → HOLD
* 조건 3: 최근 이벤트 0건 + 미보유 → HOLD
* 조건 4: orderable_amount <= 0 + 미보유 → WATCH
* 조건 5(2026-08-19, C2): buy_candidate=False + eligibility_passed=False +
  미보유 → downstream `_check_ai_buy_override_gate()`와 동일하게 강제
  WATCH/HOLD (단, eligibility_passed=True에 의존하는 EV gate/hysteresis
  분기와 signal_feature_snapshot_id 없음 예외는 명시적으로 스코프 밖)
* 생략 불가: has_position이면 조건 2/3/4/5에서도 skip=False
* 생략 불가: 모든 조건 통과 → skip=False
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import (
    CashBalanceSnapshotEntity,
    DecisionContextEntity,
    ExternalEventEntity,
    PositionSnapshotEntity,
)
from agent_trading.services.deterministic_trigger_engine import (
    DeterministicTriggerAssessment,
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
from scripts.run_agent_subprocess import (
    AgentSubprocessOutput,
    _build_agent_triplet,
    _build_ar_timeout_fallback,
    _build_ei_timeout_fallback,
    _build_fdc_timeout_fallback,
    _run_fdc_with_outer_timeout,
)
from agent_trading.services.ai_agents.event_interpretation import (
    DeterministicEventInterpretationAgent,
)
from agent_trading.services.ai_agents.ai_risk import DeterministicAIRiskAgent
from agent_trading.services.ai_agents.ai_compliance import (
    DeterministicAIComplianceAgent,
)
from agent_trading.services.ai_agents.final_decision_composer import (
    FinalDecisionComposerAgent,
    StubFinalDecisionComposerAgent,
)


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


def _make_context_with_events(source_type: str = "core") -> AssembledContext:
    """최근 이벤트 1건이 있지만 포지션/현금은 없는 컨텍스트."""
    return AssembledContext(
        source_type=source_type,
        recent_events=(
            ExternalEventEntity(
                event_id=uuid4(),
                event_type="test_event",
                source_name="test",
                published_at=datetime(2026, 5, 22, tzinfo=timezone.utc),
            ),
        ),
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


def _make_request(
    context: AssembledContext,
    *,
    decision_context_id: UUID | None = None,
    symbol: str = "005930",
) -> AgentExecutionRequest:
    """Timeout fallback 테스트용 request helper."""
    return AgentExecutionRequest(
        decision_context_id=decision_context_id,
        correlation_id="test-timeout-fallback",
        context=context,
        symbol=symbol,
        market="KRX",
    )


def test_build_agent_triplet_uses_stub_agents_when_provider_missing() -> None:
    """PR #277(2026-08-16) 이후 EI/AR/AC는 provider 유무와 무관하게 항상
    deterministic bot을 반환한다 — provider_client=None일 때 Stub으로
    내려가는 것은 FDC뿐이다(``_build_agent_triplet()`` docstring 참고).
    또한 이 함수는 이제 4-tuple(EI/AR/AC/FDC)을 반환한다(AC 추가)."""
    ei_agent, ar_agent, ac_agent, fdc_agent = _build_agent_triplet(
        provider_client=None,
        model_id="gemini-3.5-flash",
    )

    assert isinstance(ei_agent, DeterministicEventInterpretationAgent)
    assert isinstance(ar_agent, DeterministicAIRiskAgent)
    assert isinstance(ac_agent, DeterministicAIComplianceAgent)
    assert isinstance(fdc_agent, StubFinalDecisionComposerAgent)


class _DummyProviderClient:
    async def generate_structured(
        self,
        *,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        response_format: type,
        temperature: float = 0.0,
        seed: int | None = None,
    ):
        raise AssertionError("이 테스트에서는 실제 provider 호출이 발생하면 안 됩니다.")


def test_build_agent_triplet_uses_real_agents_when_provider_exists() -> None:
    """provider_client가 있어도 EI/AR/AC는 여전히 deterministic bot이다
    (2026-08-16/17 전환 이후 고정 동작) — provider에 반응해 Real로
    바뀌는 것은 FDC뿐이다."""
    ei_agent, ar_agent, ac_agent, fdc_agent = _build_agent_triplet(
        provider_client=_DummyProviderClient(),
        model_id="gemini-3.5-flash",
    )

    assert isinstance(ei_agent, DeterministicEventInterpretationAgent)
    assert isinstance(ar_agent, DeterministicAIRiskAgent)
    assert isinstance(ac_agent, DeterministicAIComplianceAgent)
    assert isinstance(fdc_agent, FinalDecisionComposerAgent)


# =========================================================================
# Test: Condition 1 — Risk "reject"
# =========================================================================


def test_build_ei_timeout_fallback_marks_degraded_with_events() -> None:
    """EI timeout fallback은 degraded + detected_event_count를 보존해야 한다."""
    context = _make_context_with_events()
    request = _make_request(context)

    output = _build_ei_timeout_fallback(
        request,
        symbol="005930",
        input_event_count=1,
    )

    assert output.symbol == "005930"
    assert output.detected_event_count == 1
    assert output.aggregate_view.interpretation_incomplete is True
    assert output.aggregate_view.degraded_reason == "timeout"
    assert output.aggregate_view.no_material_events is False


def test_build_ar_timeout_fallback_preserves_symbol_and_context() -> None:
    """AR timeout fallback은 symbol과 decision_context_id를 보존해야 한다."""
    ctx_id = uuid4()
    request = _make_request(_make_empty_context(), decision_context_id=ctx_id)

    output = _build_ar_timeout_fallback(request, symbol="000660")

    assert output.symbol == "000660"
    assert output.decision_context_id == str(ctx_id)
    assert output.risk_opinion == "allow"


def test_build_fdc_timeout_fallback_preserves_symbol_and_context() -> None:
    """FDC timeout fallback은 symbol과 decision_context_id를 보존해야 한다."""
    ctx_id = uuid4()
    request = _make_request(_make_empty_context(), decision_context_id=ctx_id)

    output = _build_fdc_timeout_fallback(request, symbol="000660")

    assert output.symbol == "000660"
    assert output.decision_context_id == str(ctx_id)
    assert output.decision_type == "HOLD"


def test_build_fdc_timeout_fallback_reason_codes_not_empty() -> None:
    """2026-08-21 결함 수정: reason_codes가 더 이상 비어있으면 안 된다 —
    비어 있으면 정상 HOLD와 timeout fallback을 DB만으로 구분할 수 없다."""
    request = _make_request(_make_empty_context())

    output = _build_fdc_timeout_fallback(request, symbol="000660")

    assert output.reason_codes == ("provider_timeout",)
    assert output.summary
    assert "000660" in output.summary


class _SlowFdcAgent:
    """실제 70초 sleep 없이 outer timeout 취소 경로를 재현하는 fake agent.

    ``asyncio.wait_for()``가 매우 짧은 timeout으로 이 ``run()``을 취소하면
    ``CancelledError``가 전파되고, ``last_provider_observation``은
    (실제 ``FinalDecisionComposerAgent``와 동일하게) ``None``으로 남는다
    — ``except Exception`` 블록에 도달하지 못하기 때문이다.
    """

    def __init__(self) -> None:
        self.last_provider_observation = None

    async def run(self, request: AgentExecutionRequest) -> FinalDecisionComposerOutput:
        import asyncio

        await asyncio.sleep(10)  # 아래 테스트의 매우 짧은 timeout보다 항상 길다
        raise AssertionError("outer timeout보다 먼저 취소돼야 하는 코루틴이 끝까지 실행됨")


class TestRunFdcWithOuterTimeout:
    """2026-08-21 PR #311 코드 검토 후속 수정 회귀 테스트.

    outer ``asyncio.wait_for(fdc_agent.run(...), timeout=_FDC_PER_AGENT_
    TIMEOUT)``가 실제로 timeout됐을 때 ``provider_final_status``/
    ``provider_execution_seconds``가 빈 기본값("", 0.0)으로 남던 결함을
    ``_run_fdc_with_outer_timeout()`` 신설로 수정했다 — 이 헬퍼가 실제
    outer timeout 흐름(취소 → fallback → 관측값 계산)을 전부 재현하는지
    검증한다. 실제 70초 sleep은 사용하지 않고 controlled coroutine +
    매우 짧은 test-only timeout으로 동일한 취소 경로를 재현한다.
    """

    @pytest.mark.asyncio
    async def test_outer_timeout_sets_provider_timeout_status_and_positive_execution_seconds(
        self,
    ) -> None:
        request = _make_request(_make_empty_context())
        slow_agent = _SlowFdcAgent()

        composer_output, observation_fields = await _run_fdc_with_outer_timeout(
            slow_agent,
            request,
            timeout_seconds=0.05,
            symbol="005930",
        )

        assert composer_output.decision_type == "HOLD"
        assert composer_output.reason_codes == ("provider_timeout",)
        assert composer_output.symbol == "005930"

        assert observation_fields["provider_final_status"] == "provider_timeout"
        assert observation_fields["provider_execution_seconds"] > 0
        # 취소 전 실제로 관측된 HTTP 시도가 없으므로(last_provider_
        # observation=None) 임의로 추정하지 않고 0으로 남아야 한다.
        assert observation_fields["provider_http_attempt_count"] == 0
        assert observation_fields["provider_http_429_count"] == 0

    @pytest.mark.asyncio
    async def test_outer_timeout_fields_survive_full_subprocess_round_trip(
        self,
    ) -> None:
        """outer timeout 관측값이 ``AgentSubprocessOutput`` →
        ``write_agent_subprocess_output()`` → stdout JSON →
        ``deserialize_agent_output()`` → ``AgentExecutionBundle.
        provider_observability``까지 손실 없이 보존돼야 하며, 기존
        ``provider_queue_timeout``/실제 429 재시도 케이스와 혼동되지
        않아야 한다(``rate_limiter_queue_timeout``/``rate_limiter_
        state_file_error``는 이 경로와 무관하므로 False로 남아야 함)."""
        import json
        from io import StringIO

        from agent_trading.services.ai_agents.schemas import (
            AIComplianceOutput,
            AIRiskOutput as _AIRiskOutput,
            EventInterpretationOutput as _EventInterpretationOutput,
        )
        from agent_trading.services.ai_agents.subprocess_io import (
            write_agent_subprocess_output,
        )
        from agent_trading.services.common_types import dataclass_to_dict
        from agent_trading.services.subprocess_helpers import deserialize_agent_output

        request = _make_request(_make_empty_context())
        slow_agent = _SlowFdcAgent()

        composer_output, observation_fields = await _run_fdc_with_outer_timeout(
            slow_agent,
            request,
            timeout_seconds=0.05,
            symbol="005930",
        )

        fake_output = AgentSubprocessOutput(
            success=True,
            event_output=dataclass_to_dict(_EventInterpretationOutput()),
            risk_output=dataclass_to_dict(_AIRiskOutput()),
            compliance_output=dataclass_to_dict(AIComplianceOutput()),
            composer_output=dataclass_to_dict(composer_output),
            duration_seconds=0.05,
            provider_http_attempt_count=observation_fields["provider_http_attempt_count"],
            provider_http_429_count=observation_fields["provider_http_429_count"],
            provider_execution_seconds=observation_fields["provider_execution_seconds"],
            provider_final_status=observation_fields["provider_final_status"],
            # outer timeout은 permit 대기/상태 파일 오류와 무관하므로
            # rate_limiter_* 는 "정상 진행" 기본값을 그대로 둔다.
        )

        stream = StringIO()
        write_agent_subprocess_output(fake_output, stream)
        raw_json = stream.getvalue()

        payload = json.loads(raw_json)
        assert payload["provider_final_status"] == "provider_timeout"
        assert payload["provider_execution_seconds"] > 0
        assert payload["rate_limiter_queue_timeout"] is False
        assert payload["rate_limiter_state_file_error"] is False

        bundle = deserialize_agent_output(raw_json)
        assert bundle.composer_output.reason_codes == ("provider_timeout",)
        assert bundle.composer_output.decision_type == "HOLD"

        obs = bundle.provider_observability
        assert obs is not None
        assert obs["provider_final_status"] == "provider_timeout"
        assert obs["provider_execution_seconds"] > 0
        assert obs["provider_http_attempt_count"] == 0
        assert obs["provider_http_429_count"] == 0
        assert obs["rate_limiter_queue_timeout"] is False
        assert obs["rate_limiter_state_file_error"] is False

    @pytest.mark.asyncio
    async def test_successful_run_within_timeout_uses_agent_observation_unaffected(
        self,
    ) -> None:
        """timeout에 걸리지 않는 정상 경로는 기존과 동일하게
        ``fdc_agent.last_provider_observation``의 실제 값을 그대로
        사용해야 한다(이번 수정이 성공 경로를 건드리지 않았음을 확인)."""
        from dataclasses import dataclass

        @dataclass
        class _FakeObservation:
            http_attempt_count: int = 2
            http_429_count: int = 1
            execution_seconds: float = 3.4
            provider_final_status: str = "success"

        class _FastFdcAgent:
            def __init__(self) -> None:
                self.last_provider_observation = _FakeObservation()

            async def run(self, request: AgentExecutionRequest) -> FinalDecisionComposerOutput:
                return FinalDecisionComposerOutput(symbol="005930", decision_type="APPROVE")

        request = _make_request(_make_empty_context())
        fast_agent = _FastFdcAgent()

        composer_output, observation_fields = await _run_fdc_with_outer_timeout(
            fast_agent,
            request,
            timeout_seconds=5.0,
            symbol="005930",
        )

        assert composer_output.decision_type == "APPROVE"
        assert observation_fields["provider_final_status"] == "success"
        assert observation_fields["provider_http_attempt_count"] == 2
        assert observation_fields["provider_http_429_count"] == 1
        assert observation_fields["provider_execution_seconds"] == 3.4


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
    """no_material_events 단독으로는 FDC를 생략하지 않는다."""

    def test_no_material_no_position(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        no_material_event_output: EventInterpretationOutput,
        risk_allow_output: AIRiskOutput,
    ) -> None:
        """이벤트가 존재하면 no_material_events=True여도 FDC까지 전달."""
        context = _make_context_with_events()
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

    def test_no_material_without_recent_events_still_skips_by_no_events_rule(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        no_material_event_output: EventInterpretationOutput,
        risk_allow_output: AIRiskOutput,
    ) -> None:
        """recent_events가 비어 있으면 no_material 여부와 무관하게 no_events rule 적용."""
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
        assert reason == "no_events_no_position"
        assert output.decision_type == "HOLD"


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

    def test_no_events_summary_discloses_deterministic_skip(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        default_event_output: EventInterpretationOutput,
        risk_allow_output: AIRiskOutput,
    ) -> None:
        """2026-08-19: summary 첫 문장이 [결정론적 판단 근거]로 시작하고
        상세 설명(이벤트 없음/미보유/HOLD 확정)을 포함해야 한다."""
        context = _make_empty_context()
        request = AgentExecutionRequest(
            decision_context_id=None, correlation_id="test", context=context,
        )
        _, _, output = _check_fdc_skip(
            sample_subprocess_input, request,
            default_event_output, risk_allow_output,
        )
        assert output.summary.startswith("[결정론적 판단 근거]")
        assert "FDC" in output.summary
        assert "HOLD" in output.summary

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


# =========================================================================
# Test: Degraded 상태에서 FDC skip 방지
# =========================================================================


class TestFdcSkipDegraded:
    """degraded 상태(is_degraded=True)에서는 FDC skip하지 않음."""

    def test_fdc_skip_does_not_skip_when_self_contradiction_degraded(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        risk_allow_output: AIRiskOutput,
    ) -> None:
        """Self-contradiction (degraded) 상태에서는 skip=False.

        no_material_events=True이지만 is_degraded=True이므로
        Condition 2가 보호되어 FDC skip하지 않음.
        """
        context = _make_context_with_events()
        # Self-contradiction 상태: no_material_events=True + is_degraded=True
        degraded_output = EventInterpretationOutput(
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
                interpretation_incomplete=True,
                degraded_reason="self_contradiction_corrected",
            ),
        )
        request = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="test",
            context=context,
        )
        skip, reason, output = _check_fdc_skip(
            sample_subprocess_input, request,
            degraded_output, risk_allow_output,
        )
        assert skip is False, (
            "Should NOT skip FDC when is_degraded=True"
        )
        assert reason == "", (
            f"Expected empty reason, got: {reason}"
        )

    def test_fdc_skip_does_not_skip_when_provider_failure_degraded(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        risk_allow_output: AIRiskOutput,
    ) -> None:
        """Provider failure (degraded) 상태에서도 skip=False."""
        context = _make_context_with_events()
        degraded_output = EventInterpretationOutput(
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
                interpretation_incomplete=True,
                degraded_reason="provider_error",
            ),
        )
        request = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="test",
            context=context,
        )
        skip, reason, output = _check_fdc_skip(
            sample_subprocess_input, request,
            degraded_output, risk_allow_output,
        )
        assert skip is False, (
            "Should NOT skip FDC when is_degraded=True (provider_error)"
        )

    def test_fdc_skip_normal_no_material_events_with_recent_events_no_longer_skips(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        no_material_event_output: EventInterpretationOutput,
        risk_allow_output: AIRiskOutput,
    ) -> None:
        """recent_events가 있으면 정상 no_material_events라도 FDC를 생략하지 않는다."""
        context = _make_context_with_events()
        request = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="test",
            context=context,
        )
        skip, reason, output = _check_fdc_skip(
            sample_subprocess_input, request,
            no_material_event_output, risk_allow_output,
        )
        assert skip is False, (
            "Should NOT skip FDC when recent_events exist even if no_material_events=True"
        )
        assert reason == "", (
            f"Expected empty reason, got: {reason}"
        )

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


# =========================================================================
# Test: Condition 5 — buy_candidate=False + eligibility_passed=False
# (2026-08-19, C2: FDC 호출량 절감)
# =========================================================================


def _make_deterministic_trigger(
    *,
    buy_candidate: bool = False,
    watch_candidate: bool = False,
    eligibility_passed: bool = False,
    eligibility_reasons: tuple = (),
) -> DeterministicTriggerAssessment:
    return DeterministicTriggerAssessment(
        trigger_version="v1",
        primary_candidate="none",
        candidate_set=(),
        watch_candidate=watch_candidate,
        buy_candidate=buy_candidate,
        sell_candidate=False,
        reduce_candidate=False,
        candidate_confidence=0.0,
        entry_score=None,
        exit_score=None,
        watch_score=None,
        eligibility_passed=eligibility_passed,
        eligibility_reasons=eligibility_reasons,
    )


def _make_decision_context(
    *, signal_feature_snapshot_id: UUID | None = None,
) -> DecisionContextEntity:
    return DecisionContextEntity(
        decision_context_id=uuid4(),
        account_id=uuid4(),
        strategy_id=uuid4(),
        config_version_id=uuid4(),
        market_timestamp=datetime.now(timezone.utc),
        correlation_id="test",
        signal_feature_snapshot_id=signal_feature_snapshot_id,
    )


def _make_eligibility_blocked_context(
    *,
    watch_candidate: bool = False,
    eligibility_reasons: tuple = ("eligibility_low_momentum",),
    has_position: bool = False,
    decision_context: DecisionContextEntity | None = None,
) -> AssembledContext:
    position_snapshot = None
    if has_position:
        position_snapshot = PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=uuid4(),
            instrument_id=uuid4(),
            quantity=Decimal("10"),
            average_price=Decimal("50000"),
            market_price=Decimal("50000"),
            unrealized_pnl=Decimal("0"),
            source_of_truth="KIS",
            snapshot_at=datetime.now(timezone.utc),
        )
    return AssembledContext(
        source_type="core",
        decision_context=(
            decision_context
            if decision_context is not None
            else _make_decision_context(signal_feature_snapshot_id=uuid4())
        ),
        recent_events=(
            ExternalEventEntity(
                event_id=uuid4(),
                event_type="test_event",
                source_name="test",
                published_at=datetime.now(timezone.utc),
            ),
        ),
        position_snapshot=position_snapshot,
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
        deterministic_trigger=_make_deterministic_trigger(
            buy_candidate=False,
            watch_candidate=watch_candidate,
            eligibility_passed=False,
            eligibility_reasons=eligibility_reasons,
        ),
    )


class TestFdcSkipBuyCandidateEligibilityBlocked:
    """C2(2026-08-19): buy_candidate=False + eligibility_passed=False →
    downstream `_check_ai_buy_override_gate()`가 어차피 WATCH/HOLD로
    강등할 구간을 FDC 호출 전에 결정론적으로 확정한다.

    동치성 근거는 scripts/run_agent_subprocess.py의 Condition 4 주석과
    docs/30_work_log/2026-08-19_c2_fdc_skip_buy_candidate_false.md 참고.
    """

    def test_skips_and_forces_hold_when_watch_candidate_false(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        default_event_output: EventInterpretationOutput,
        risk_allow_output: AIRiskOutput,
    ) -> None:
        context = _make_eligibility_blocked_context(watch_candidate=False)
        request = AgentExecutionRequest(
            decision_context_id=None, correlation_id="test", context=context,
        )
        skip, reason, output = _check_fdc_skip(
            sample_subprocess_input, request,
            default_event_output, risk_allow_output,
        )
        assert skip is True
        assert reason == "buy_candidate_eligibility_blocked"
        assert output.decision_type == "HOLD"
        assert "buy_candidate_eligibility_blocked" in output.reason_codes
        assert "ai_override_eligibility_blocked" in output.reason_codes
        assert "forced_hold" in output.reason_codes

    def test_skips_and_forces_watch_when_watch_candidate_true(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        default_event_output: EventInterpretationOutput,
        risk_allow_output: AIRiskOutput,
    ) -> None:
        context = _make_eligibility_blocked_context(watch_candidate=True)
        request = AgentExecutionRequest(
            decision_context_id=None, correlation_id="test", context=context,
        )
        skip, reason, output = _check_fdc_skip(
            sample_subprocess_input, request,
            default_event_output, risk_allow_output,
        )
        assert skip is True
        assert reason == "buy_candidate_eligibility_blocked"
        assert output.decision_type == "WATCH"
        assert "forced_watch_candidate" in output.reason_codes

    def test_summary_discloses_deterministic_skip(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        default_event_output: EventInterpretationOutput,
        risk_allow_output: AIRiskOutput,
    ) -> None:
        """summary 첫 문장이 규칙 기반 생략임을 명확히 밝히고, 강제된 최종
        결과(WATCH/HOLD)를 포함해야 한다(설명 가능성 요구사항). 2026-08-19
        축약 이후로는 source_type/buy_candidate/eligibility_reasons 같은
        코드성 항목은 summary에 노출하지 않는다(UI '근거' 컬럼 가독성)."""
        context = _make_eligibility_blocked_context(
            watch_candidate=True,
            eligibility_reasons=("eligibility_low_momentum", "eligibility_low_score"),
        )
        request = AgentExecutionRequest(
            decision_context_id=None, correlation_id="test", context=context,
        )
        _, _, output = _check_fdc_skip(
            sample_subprocess_input, request,
            default_event_output, risk_allow_output,
        )
        assert output.summary.startswith("[규칙 기반 생략]")
        assert "FDC" in output.summary
        assert "WATCH" in output.summary
        assert len(output.summary) <= 160

    def test_does_not_trigger_when_position_held(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        default_event_output: EventInterpretationOutput,
        risk_allow_output: AIRiskOutput,
    ) -> None:
        """보유 포지션이 있으면(has_position=True) 새 조건이 절대 발동하지
        않아야 한다 — held_position 경로 오적용 방지 요구사항."""
        context = _make_eligibility_blocked_context(has_position=True)
        request = AgentExecutionRequest(
            decision_context_id=None, correlation_id="test", context=context,
        )
        skip, reason, output = _check_fdc_skip(
            sample_subprocess_input, request,
            default_event_output, risk_allow_output,
        )
        assert skip is False
        assert reason == ""

    def test_does_not_trigger_when_buy_candidate_true(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        default_event_output: EventInterpretationOutput,
        risk_allow_output: AIRiskOutput,
    ) -> None:
        """buy_candidate=True면 (구조상 eligibility_passed=True를 내포)
        새 조건이 발동하지 않아야 한다."""
        context = AssembledContext(
            source_type="core",
            decision_context=_make_decision_context(signal_feature_snapshot_id=uuid4()),
            recent_events=(
                ExternalEventEntity(
                    event_id=uuid4(), event_type="test_event", source_name="test",
                    published_at=datetime.now(timezone.utc),
                ),
            ),
            position_snapshot=None,
            cash_balance_snapshot=CashBalanceSnapshotEntity(
                cash_balance_snapshot_id=uuid4(), account_id=uuid4(), currency="KRW",
                available_cash=Decimal("10000000"), settled_cash=Decimal("10000000"),
                unsettled_cash=Decimal("0"), source_of_truth="KIS",
                snapshot_at=datetime.now(timezone.utc), total_asset=Decimal("10000000"),
                orderable_amount=Decimal("5000000"),
            ),
            deterministic_trigger=_make_deterministic_trigger(
                buy_candidate=True, watch_candidate=True, eligibility_passed=True,
            ),
        )
        request = AgentExecutionRequest(
            decision_context_id=None, correlation_id="test", context=context,
        )
        skip, reason, output = _check_fdc_skip(
            sample_subprocess_input, request,
            default_event_output, risk_allow_output,
        )
        assert skip is False
        assert reason == ""

    def test_does_not_trigger_when_eligibility_passed_true_and_buy_candidate_false(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        default_event_output: EventInterpretationOutput,
        risk_allow_output: AIRiskOutput,
    ) -> None:
        """eligibility_passed=True인데 entry_score 부족으로 buy_candidate=False인
        경우는 downstream에서 EV gate/hysteresis에 의존하는 분기라 동치성이
        없으므로, 새 조건이 절대 발동하지 않아야 한다(스코프 밖 명시적 배제)."""
        context = AssembledContext(
            source_type="core",
            decision_context=_make_decision_context(signal_feature_snapshot_id=uuid4()),
            recent_events=(
                ExternalEventEntity(
                    event_id=uuid4(), event_type="test_event", source_name="test",
                    published_at=datetime.now(timezone.utc),
                ),
            ),
            position_snapshot=None,
            cash_balance_snapshot=CashBalanceSnapshotEntity(
                cash_balance_snapshot_id=uuid4(), account_id=uuid4(), currency="KRW",
                available_cash=Decimal("10000000"), settled_cash=Decimal("10000000"),
                unsettled_cash=Decimal("0"), source_of_truth="KIS",
                snapshot_at=datetime.now(timezone.utc), total_asset=Decimal("10000000"),
                orderable_amount=Decimal("5000000"),
            ),
            deterministic_trigger=_make_deterministic_trigger(
                buy_candidate=False, watch_candidate=True, eligibility_passed=True,
                eligibility_reasons=(),
            ),
        )
        request = AgentExecutionRequest(
            decision_context_id=None, correlation_id="test", context=context,
        )
        skip, reason, output = _check_fdc_skip(
            sample_subprocess_input, request,
            default_event_output, risk_allow_output,
        )
        assert skip is False
        assert reason == ""

    def test_does_not_trigger_for_low_feature_coverage_exception(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        default_event_output: EventInterpretationOutput,
        risk_allow_output: AIRiskOutput,
    ) -> None:
        """downstream의 좁은 예외(signal_feature_snapshot_id=None +
        eligibility_reasons가 {source_type_allowed, low_feature_coverage}의
        부분집합)와 동일하게, 이 케이스에서는 새 조건이 발동하지 않아야
        한다 — 이 경우 downstream 게이트도 강등하지 않고 FDC의 원래
        결정을 그대로 두기 때문이다."""
        decision_context = _make_decision_context(signal_feature_snapshot_id=None)
        context = _make_eligibility_blocked_context(
            watch_candidate=True,
            eligibility_reasons=("eligibility_low_feature_coverage",),
            decision_context=decision_context,
        )
        request = AgentExecutionRequest(
            decision_context_id=None, correlation_id="test", context=context,
        )
        skip, reason, output = _check_fdc_skip(
            sample_subprocess_input, request,
            default_event_output, risk_allow_output,
        )
        assert skip is False
        assert reason == ""

    def test_triggers_when_signal_feature_snapshot_present_even_with_low_feature_coverage_reason(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        default_event_output: EventInterpretationOutput,
        risk_allow_output: AIRiskOutput,
    ) -> None:
        """예외 조건은 signal_feature_snapshot_id가 None일 때만 적용된다 —
        snapshot_id가 있으면(정상 케이스) eligibility_reasons가 같아도
        예외가 아니므로 skip이 발동해야 한다."""
        decision_context = _make_decision_context(signal_feature_snapshot_id=uuid4())
        context = _make_eligibility_blocked_context(
            watch_candidate=False,
            eligibility_reasons=("eligibility_low_feature_coverage",),
            decision_context=decision_context,
        )
        request = AgentExecutionRequest(
            decision_context_id=None, correlation_id="test", context=context,
        )
        skip, reason, output = _check_fdc_skip(
            sample_subprocess_input, request,
            default_event_output, risk_allow_output,
        )
        assert skip is True
        assert reason == "buy_candidate_eligibility_blocked"
        assert output.decision_type == "HOLD"

    def test_existing_conditions_unaffected_when_no_deterministic_trigger(
        self,
        sample_subprocess_input: AgentSubprocessInput,
        default_event_output: EventInterpretationOutput,
        risk_allow_output: AIRiskOutput,
    ) -> None:
        """deterministic_trigger가 없으면(None) 새 조건은 절대 발동하지
        않고, 기존 조건들의 판정만 그대로 유지되어야 한다(회귀 없음)."""
        context = _make_empty_context()
        request = AgentExecutionRequest(
            decision_context_id=None, correlation_id="test", context=context,
        )
        skip, reason, output = _check_fdc_skip(
            sample_subprocess_input, request,
            default_event_output, risk_allow_output,
        )
        # deterministic_trigger=None인 빈 컨텍스트는 기존 조건 3
        # (no_events_no_position)이 먼저 발동해야 한다 — 새 조건 때문에
        # 다른 결과로 바뀌면 안 된다.
        assert skip is True
        assert reason == "no_events_no_position"


class TestDiagLogLazyDirCreation:
    """diag 로그 디렉터리 생성이 import-time이 아니라 실제 기록 시점
    (``_diag()`` 호출 시)에만 일어나는지 검증(2026-08-18 KST).

    이 모듈(``scripts.run_agent_subprocess``)이 top-level에서
    ``os.makedirs()``를 호출하던 시절에는, read-only 파일시스템
    마운트 환경(harness ``accept-backend-file`` 검증 컨테이너)에서
    이 파일을 단순히 import하는 것만으로 collection 자체가
    실패했다 — 바로 이 파일(이 테스트 파일)이 그 실패의 재현
    지점이었다. 이 테스트가 여기서 정상 수집/실행된다는 사실 자체가
    import-time side effect가 사라졌다는 1차 증거이며, 아래 테스트는
    그 동작을 명시적으로 검증한다.
    """

    def test_diag_defers_dir_creation_to_ensure_helper(self, monkeypatch) -> None:
        """``_diag()``는 파일을 열기 전에 ``_ensure_diag_log_dir()``를
        호출해 디렉터리 생성을 그 시점까지 늦춰야 한다."""
        import scripts.run_agent_subprocess as run_agent_subprocess_module

        calls: list[str] = []
        monkeypatch.setattr(
            run_agent_subprocess_module,
            "_ensure_diag_log_dir",
            lambda: calls.append("called"),
        )
        run_agent_subprocess_module._diag("test message")
        assert calls == ["called"]

    def test_diag_is_best_effort_when_dir_creation_fails(self, monkeypatch) -> None:
        """``_ensure_diag_log_dir()``가 실패해도(예: read-only fs)
        ``_diag()``는 예외를 밖으로 전파하지 않아야 한다(기존
        best-effort 계약 유지)."""
        import scripts.run_agent_subprocess as run_agent_subprocess_module

        def _raise() -> None:
            raise OSError("Read-only file system")

        monkeypatch.setattr(
            run_agent_subprocess_module, "_ensure_diag_log_dir", _raise,
        )
        run_agent_subprocess_module._diag("test message")  # must not raise
