"""Tests for ``scripts/run_agent_subprocess.py``의 FDC 실제 dispatch
게이팅(2026-08-27, held_position lane REDUCE_CANDIDATE/SELL_CANDIDATE
한정).

이 파일은 다음만 검증한다 — FDC quota 예약/기록/HTTP one-shot 메커니즘
자체는 ``tests/scripts/test_fdc_manual_provider_gate.py``/
``tests/services/test_fdc_quota_coordinator.py``가 이미 검증했으므로
중복하지 않는다.

1. ``_is_fdc_actual_dispatch_target()`` — 대상 lane/후보 판별 순수 함수.
2. ``main()``의 배선 — flag=false/비대상 lane이면
   ``_build_actual_dispatch_fdc_client()``가 전혀 호출되지 않고 기존
   ``OpenAICompatibleClient`` + 10 RPM strict limiter 경로가 그대로
   유지되는지, flag=true + 대상 lane이면 정확히 1회 호출되고 그 결과가
   ``_build_agent_triplet()``에 ``acquire_permit=None``과 함께 전달되는지.
3. DB pool이 열린 뒤에는(성공/실패 모두) ``close_pool()``이 호출되는지.

fake/mock만 사용 — 실제 sleep/DB/HTTP/Gemini 없음.
"""

from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from agent_trading.services.ai_agents.base import AgentExecutionRequest
from agent_trading.services.ai_agents.schemas import (
    AIComplianceOutput,
    AIRiskOutput,
    EventInterpretationOutput,
    FinalDecisionComposerOutput,
)
from agent_trading.services.common_types import AssembledContext
from scripts import run_agent_subprocess as script


# ===========================================================================
# _is_fdc_actual_dispatch_target()
# ===========================================================================


def _make_request(
    *,
    source_type: str,
    primary_candidate: str | None,
    quantity: Decimal | None = None,
) -> AgentExecutionRequest:
    position_snapshot = (
        SimpleNamespace(quantity=quantity) if quantity is not None else None
    )
    deterministic_trigger = (
        SimpleNamespace(primary_candidate=primary_candidate)
        if primary_candidate is not None
        else None
    )
    context = AssembledContext(
        source_type=source_type,
        position_snapshot=position_snapshot,
        deterministic_trigger=deterministic_trigger,
    )
    return AgentExecutionRequest(
        decision_context_id=None,
        correlation_id="test-corr",
        context=context,
        source_type=source_type,
    )


class TestIsFdcActualDispatchTarget:
    def test_held_position_sell_candidate_with_position_is_target(self) -> None:
        request = _make_request(
            source_type="held_position",
            primary_candidate="SELL_CANDIDATE",
            quantity=Decimal("10"),
        )
        assert script._is_fdc_actual_dispatch_target(request) is True

    def test_held_position_reduce_candidate_with_position_is_target(self) -> None:
        request = _make_request(
            source_type="held_position",
            primary_candidate="REDUCE_CANDIDATE",
            quantity=Decimal("5"),
        )
        assert script._is_fdc_actual_dispatch_target(request) is True

    def test_held_position_no_action_is_not_target(self) -> None:
        """held_position이어도 NO_ACTION(원래 FDC 자체가 skip되는 경로)은
        대상이 아니다."""
        request = _make_request(
            source_type="held_position",
            primary_candidate="NO_ACTION",
            quantity=Decimal("10"),
        )
        assert script._is_fdc_actual_dispatch_target(request) is False

    def test_held_position_watch_is_not_target(self) -> None:
        request = _make_request(
            source_type="held_position",
            primary_candidate="WATCH",
            quantity=Decimal("10"),
        )
        assert script._is_fdc_actual_dispatch_target(request) is False

    def test_held_position_without_position_is_not_target(self) -> None:
        request = _make_request(
            source_type="held_position",
            primary_candidate="SELL_CANDIDATE",
            quantity=None,
        )
        assert script._is_fdc_actual_dispatch_target(request) is False

    def test_held_position_zero_quantity_is_not_target(self) -> None:
        request = _make_request(
            source_type="held_position",
            primary_candidate="SELL_CANDIDATE",
            quantity=Decimal("0"),
        )
        assert script._is_fdc_actual_dispatch_target(request) is False

    def test_core_lane_buy_candidate_is_not_target(self) -> None:
        request = _make_request(
            source_type="core",
            primary_candidate="BUY_CANDIDATE",
            quantity=None,
        )
        assert script._is_fdc_actual_dispatch_target(request) is False

    def test_core_lane_with_sell_candidate_string_is_still_rejected(self) -> None:
        """deterministic_trigger_engine.py 구조상 core lane은 SELL_
        CANDIDATE를 만들 수 없지만, source_type 체크를 별도 방어선으로
        유지한다(이중 방어 — 만에 하나 상위 계층이 잘못된 조합을 넘겨도
        여기서 한 번 더 막는다)."""
        request = _make_request(
            source_type="core",
            primary_candidate="SELL_CANDIDATE",
            quantity=Decimal("10"),
        )
        assert script._is_fdc_actual_dispatch_target(request) is False

    def test_no_deterministic_trigger_is_not_target(self) -> None:
        request = _make_request(
            source_type="held_position",
            primary_candidate=None,
            quantity=Decimal("10"),
        )
        assert script._is_fdc_actual_dispatch_target(request) is False


# ===========================================================================
# main() wiring — flag/lane 게이팅
# ===========================================================================


def _base_payload(
    *,
    fdc_actual_dispatch_enabled: bool,
    source_type: str,
    primary_candidate: str,
    quantity: str | None,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "source_type": source_type,
        "deterministic_trigger": {"primary_candidate": primary_candidate},
    }
    if quantity is not None:
        context["position_snapshot"] = {"quantity": quantity}
    return {
        "decision_context_id": None,
        "correlation_id": "test-main-corr",
        "symbol": "005930",
        "market": "KRX",
        "source_type": source_type,
        "context": context,
        "llm_provider": "gemini",
        "provider_api_key": "fake-key",
        "provider_base_url": "https://fake.example",
        "provider_model_id": "fake-model",
        "provider_timeout_seconds": 30,
        "fdc_actual_dispatch_enabled": fdc_actual_dispatch_enabled,
    }


class _FakeStdinBuffer:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw


def _install_common_main_stubs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    captured_triplet_kwargs: dict[str, Any],
) -> None:
    """EI/AR/AC/FDC를 실제로 실행하지 않고 즉시 안전한 output을 반환하도록
    한다 — 이 테스트가 검증하는 것은 게이팅 배선이지 agent 로직이 아니다."""

    class _FakeEventInterpretationAgent:
        async def run(self, request: Any) -> EventInterpretationOutput:
            return EventInterpretationOutput(
                agent_name="event_interpretation",
                schema_version="v1",
                symbol=request.symbol or "005930",
            )

    class _FakeAIRiskAgent:
        async def run(self, request: Any) -> AIRiskOutput:
            return AIRiskOutput(
                agent_name="ai_risk",
                schema_version="v1",
                risk_opinion="allow",
                risk_score=0.1,
                confidence=0.9,
            )

    class _FakeAIComplianceAgent:
        async def run(self, request: Any) -> AIComplianceOutput:
            return AIComplianceOutput(
                agent_name="ai_compliance",
                schema_version="v1",
                compliance_opinion="allow",
                compliance_score=0.1,
                confidence=0.9,
            )

    class _FakeFdcAgent:
        def __init__(self, **kwargs: Any) -> None:
            captured_triplet_kwargs.update(kwargs)
            self.last_provider_observation = None

        async def run(self, request: Any) -> FinalDecisionComposerOutput:
            return FinalDecisionComposerOutput(
                agent_name="final_decision_composer",
                schema_version="v1",
                decision_type="HOLD",
                confidence=0.5,
                symbol=request.symbol or "005930",
            )

    def _fake_build_agent_triplet(
        *, provider_client: Any, model_id: Any, acquire_permit: Any = None,
    ) -> tuple[Any, Any, Any, Any]:
        captured_triplet_kwargs["provider_client"] = provider_client
        captured_triplet_kwargs["acquire_permit"] = acquire_permit
        return (
            _FakeEventInterpretationAgent(),
            _FakeAIRiskAgent(),
            _FakeAIComplianceAgent(),
            _FakeFdcAgent(),
        )

    monkeypatch.setattr(script, "_build_agent_triplet", _fake_build_agent_triplet)

    written: dict[str, Any] = {}

    def _fake_write_output(output: Any) -> None:
        written["output"] = output

    monkeypatch.setattr(script, "_write_output", _fake_write_output)


@pytest.mark.asyncio
async def test_flag_false_completes_without_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """flag=false 정상 경로는 예외 없이 완료되고 기존 provider_client가
    그대로 agent triplet에 전달된다(레거시 accumulator 사용)."""
    payload = _base_payload(
        fdc_actual_dispatch_enabled=False,
        source_type="held_position",
        primary_candidate="SELL_CANDIDATE",
        quantity="10",
    )
    monkeypatch.setattr(
        script.sys, "stdin", SimpleNamespace(buffer=_FakeStdinBuffer(payload))
    )

    def _should_not_be_called(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("flag=false에서 호출되면 안 된다")

    monkeypatch.setattr(
        script, "_build_actual_dispatch_fdc_client", _should_not_be_called
    )

    captured: dict[str, Any] = {}
    _install_common_main_stubs(monkeypatch, captured_triplet_kwargs=captured)

    await script.main()

    assert captured["provider_client"] is not None
    assert captured["provider_client"].__class__.__name__ == "OpenAICompatibleClient"
    # 레거시 경로는 acquire_permit이 accumulator.acquire (None이 아님)
    assert captured["acquire_permit"] is not None


@pytest.mark.asyncio
async def test_flag_true_non_target_lane_never_builds_actual_dispatch_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """flag=true여도 BUY_CANDIDATE(core lane)면 대상이 아니므로 기존
    경로가 그대로 유지된다."""
    payload = _base_payload(
        fdc_actual_dispatch_enabled=True,
        source_type="core",
        primary_candidate="BUY_CANDIDATE",
        quantity=None,
    )
    monkeypatch.setattr(
        script.sys, "stdin", SimpleNamespace(buffer=_FakeStdinBuffer(payload))
    )

    def _should_not_be_called(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(
            "비대상 lane(BUY_CANDIDATE)에서 _build_actual_dispatch_fdc_"
            "client()가 호출됐다"
        )

    monkeypatch.setattr(
        script, "_build_actual_dispatch_fdc_client", _should_not_be_called
    )

    captured: dict[str, Any] = {}
    _install_common_main_stubs(monkeypatch, captured_triplet_kwargs=captured)

    await script.main()

    assert captured["provider_client"].__class__.__name__ == "OpenAICompatibleClient"
    assert captured["acquire_permit"] is not None


@pytest.mark.asyncio
async def test_flag_true_target_lane_builds_actual_dispatch_client_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """flag=true + held_position SELL_CANDIDATE(보유 포지션)면 정확히
    1회 ``_build_actual_dispatch_fdc_client()``가 호출되고, 그 결과가
    ``acquire_permit=None``과 함께 agent triplet에 전달된다(기존 10 RPM
    limiter를 거치지 않음)."""
    payload = _base_payload(
        fdc_actual_dispatch_enabled=True,
        source_type="held_position",
        primary_candidate="SELL_CANDIDATE",
        quantity="10",
    )
    monkeypatch.setattr(
        script.sys, "stdin", SimpleNamespace(buffer=_FakeStdinBuffer(payload))
    )

    call_count = 0
    _fake_client = object()
    _fake_coordinator = object()

    async def _fake_build_actual_dispatch_fdc_client(inp: Any) -> tuple[Any, Any]:
        nonlocal call_count
        call_count += 1
        return _fake_client, _fake_coordinator

    monkeypatch.setattr(
        script, "_build_actual_dispatch_fdc_client",
        _fake_build_actual_dispatch_fdc_client,
    )

    pool_calls: list[str] = []

    async def _fake_create_pool(*args: Any, **kwargs: Any) -> None:
        pool_calls.append("create")

    async def _fake_close_pool(*args: Any, **kwargs: Any) -> None:
        pool_calls.append("close")

    import agent_trading.db.connection as db_connection_module
    monkeypatch.setattr(db_connection_module, "create_pool", _fake_create_pool)
    monkeypatch.setattr(db_connection_module, "close_pool", _fake_close_pool)

    captured: dict[str, Any] = {}
    _install_common_main_stubs(monkeypatch, captured_triplet_kwargs=captured)

    await script.main()

    assert call_count == 1
    assert captured["provider_client"] is _fake_client
    assert captured["acquire_permit"] is None
    assert pool_calls == ["create", "close"]


@pytest.mark.asyncio
async def test_pool_closed_even_when_client_build_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB pool 생성 뒤 client 구성이 실패해도 close_pool()이 호출된다
    (leak 없음) — main()은 실패로 종료(sys.exit(1))하되 pool은 반드시
    정리한다."""
    payload = _base_payload(
        fdc_actual_dispatch_enabled=True,
        source_type="held_position",
        primary_candidate="REDUCE_CANDIDATE",
        quantity="5",
    )
    monkeypatch.setattr(
        script.sys, "stdin", SimpleNamespace(buffer=_FakeStdinBuffer(payload))
    )

    async def _raising_build(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("simulated coordinator construction failure")

    monkeypatch.setattr(
        script, "_build_actual_dispatch_fdc_client", _raising_build
    )

    pool_calls: list[str] = []

    async def _fake_create_pool(*args: Any, **kwargs: Any) -> None:
        pool_calls.append("create")

    async def _fake_close_pool(*args: Any, **kwargs: Any) -> None:
        pool_calls.append("close")

    import agent_trading.db.connection as db_connection_module
    monkeypatch.setattr(db_connection_module, "create_pool", _fake_create_pool)
    monkeypatch.setattr(db_connection_module, "close_pool", _fake_close_pool)

    written_errors: list[str] = []
    monkeypatch.setattr(
        script, "_write_error_output",
        lambda msg, **kwargs: written_errors.append(msg),
    )

    with pytest.raises(SystemExit) as exc_info:
        await script.main()

    assert exc_info.value.code == 1
    assert pool_calls == ["create", "close"]
    assert written_errors  # 실패가 기록됨 — 조용히 누락되지 않음
