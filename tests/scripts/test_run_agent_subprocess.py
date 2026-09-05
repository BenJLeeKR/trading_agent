"""Tests for ``scripts/run_agent_subprocess.py``의 ``mode``(2026-08-27,
held_position 실제 dispatcher — PR #359 리뷰 보정) 배선.

§17 설계를 코드 수준으로 구현한다 — 실제 dispatcher/FIFO 대기/quota
reservation 로직 자체는 ``tests/scripts/test_fdc_manual_provider_gate.py``
(``run_real_dispatch_job()``)와 ``tests/services/test_fdc_quota_
coordinator.py``(FIFO 공정성)가 검증했으므로 중복하지 않는다. 이 파일은
다음만 검증한다:

1. ``mode="full"``(기본값): 기존 동작 100% 보존(EI/AR/AC/FDC를 한
   subprocess에서 순차 실행).
2. ``mode="pre_fdc"``: FDC skip이면 기존과 동일한 완전한 output, FDC-
   ready면 FDC를 호출하지 않고 ``requires_fdc_dispatch=True``로 즉시
   반환.
3. ``mode="fdc_only"``: EI/AR/AC를 전혀 호출하지 않고, 이미 확보한
   grant로 FDC one-shot만 실행(``_run_fdc_only_mode()``).

fake/mock만 사용 — 실제 sleep/DB/HTTP/Gemini 없음.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from agent_trading.services.ai_agents.schemas import (
    AIComplianceOutput,
    AIRiskOutput,
    EventInterpretationOutput,
    FinalDecisionComposerOutput,
)
from scripts import run_agent_subprocess as script


# ===========================================================================
# main() wiring — mode="full"/"pre_fdc"
# ===========================================================================


def _base_payload(
    *,
    mode: str,
    source_type: str = "held_position",
    primary_candidate: str = "SELL_CANDIDATE",
    quantity: str | None = "10",
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
        "mode": mode,
    }


class _FakeStdinBuffer:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw


def _install_common_main_stubs(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """EI/AR/AC/FDC를 실제로 실행하지 않고 즉시 안전한 output을
    반환하도록 한다 — 이 테스트가 검증하는 것은 mode 배선이지 agent
    로직이 아니다."""

    class _FakeEventInterpretationAgent:
        async def run(self, request: Any) -> EventInterpretationOutput:
            return EventInterpretationOutput(
                agent_name="event_interpretation", schema_version="v1",
                symbol=request.symbol or "005930",
            )

    class _FakeAIRiskAgent:
        async def run(self, request: Any) -> AIRiskOutput:
            return AIRiskOutput(
                agent_name="ai_risk", schema_version="v1",
                risk_opinion="allow", risk_score=0.1, confidence=0.9,
            )

    class _FakeAIComplianceAgent:
        async def run(self, request: Any) -> AIComplianceOutput:
            return AIComplianceOutput(
                agent_name="ai_compliance", schema_version="v1",
                compliance_opinion="allow", compliance_score=0.1, confidence=0.9,
            )

    captured: dict[str, Any] = {"fdc_run_count": 0}

    class _FakeFdcAgent:
        def __init__(self, **kwargs: Any) -> None:
            captured["triplet_kwargs"] = kwargs
            self.last_provider_observation = None

        async def run(self, request: Any) -> FinalDecisionComposerOutput:
            captured["fdc_run_count"] += 1
            return FinalDecisionComposerOutput(
                agent_name="final_decision_composer", schema_version="v1",
                decision_type="HOLD", confidence=0.5,
                symbol=request.symbol or "005930",
            )

    def _fake_build_agent_triplet(
        *, provider_client: Any, model_id: Any, acquire_permit: Any = None,
    ) -> tuple[Any, Any, Any, Any]:
        captured["build_agent_triplet_acquire_permit"] = acquire_permit
        return (
            _FakeEventInterpretationAgent(), _FakeAIRiskAgent(),
            _FakeAIComplianceAgent(), _FakeFdcAgent(),
        )

    monkeypatch.setattr(script, "_build_agent_triplet", _fake_build_agent_triplet)

    written: dict[str, Any] = {}

    def _fake_write_output(output: Any) -> None:
        written["output"] = output

    monkeypatch.setattr(script, "_write_output", _fake_write_output)
    captured["written"] = written
    return captured


@pytest.mark.asyncio
async def test_mode_full_calls_fdc_and_produces_full_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mode="full"(기본값)은 기존과 동일하게 FDC를 호출해 완전한
    output을 만든다 — held_position SELL_CANDIDATE라도 mode="full"이면
    (이 스크립트 관점에서는) 그냥 정상 실행이다(게이팅은 상위
    DecisionAgentRunner의 책임)."""
    payload = _base_payload(mode="full")
    monkeypatch.setattr(
        script.sys, "stdin", SimpleNamespace(buffer=_FakeStdinBuffer(payload))
    )
    captured = _install_common_main_stubs(monkeypatch)

    await script.main()

    assert captured["fdc_run_count"] == 1
    output = captured["written"]["output"]
    assert output.success is True
    assert output.requires_fdc_dispatch is False
    assert output.composer_output["decision_type"] == "HOLD"


@pytest.mark.asyncio
async def test_mode_full_flag_off_never_opens_db_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PR D(2026-09-03) 회귀 방지 — FDC_PROVIDER_GLOBAL_GATE_ENABLED가
    꺼져 있으면(기본값) legacy mode="full" 경로는 여전히 DB pool을 전혀
    열지 않는다(기존 동작 100% 보존)."""
    payload = _base_payload(mode="full")
    monkeypatch.setattr(
        script.sys, "stdin", SimpleNamespace(buffer=_FakeStdinBuffer(payload))
    )
    captured = _install_common_main_stubs(monkeypatch)

    import agent_trading.config.settings as settings_module
    monkeypatch.setattr(
        settings_module, "_resolve_fdc_provider_global_gate_enabled", lambda: False,
    )
    pool_calls: list[str] = []

    async def _fake_create_pool(*args: Any, **kwargs: Any) -> None:
        pool_calls.append("create")

    import agent_trading.db.connection as db_connection_module
    monkeypatch.setattr(db_connection_module, "create_pool", _fake_create_pool)

    await script.main()

    assert captured["fdc_run_count"] == 1
    assert pool_calls == [], "flag off면 legacy 경로는 DB pool을 열면 안 된다"


@pytest.mark.asyncio
async def test_mode_full_flag_on_opens_and_closes_db_pool_and_wires_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """flag on이면 legacy mode="full" 경로가 DB pool을 열어 global gate를
    구성하고, subprocess 종료 전 반드시 pool을 닫는다."""
    payload = _base_payload(mode="full")
    monkeypatch.setattr(
        script.sys, "stdin", SimpleNamespace(buffer=_FakeStdinBuffer(payload))
    )
    captured = _install_common_main_stubs(monkeypatch)

    import agent_trading.config.settings as settings_module
    monkeypatch.setattr(
        settings_module, "_resolve_fdc_provider_global_gate_enabled", lambda: True,
    )
    pool_calls: list[str] = []

    async def _fake_create_pool(*args: Any, **kwargs: Any) -> None:
        pool_calls.append("create")

    async def _fake_close_pool(*args: Any, **kwargs: Any) -> None:
        pool_calls.append("close")

    import agent_trading.db.connection as db_connection_module
    monkeypatch.setattr(db_connection_module, "create_pool", _fake_create_pool)
    monkeypatch.setattr(db_connection_module, "close_pool", _fake_close_pool)

    class _FakeAmbientTx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    import agent_trading.db.transaction as db_transaction_module
    monkeypatch.setattr(
        db_transaction_module, "TransactionManager", lambda: _FakeAmbientTx()
    )

    from agent_trading.repositories.memory import InMemoryFdcQuotaRepository

    import agent_trading.repositories.postgres.fdc_quota as fdc_quota_module
    monkeypatch.setattr(
        fdc_quota_module, "PostgresFdcQuotaRepository",
        lambda tx: InMemoryFdcQuotaRepository(),
    )

    await script.main()

    assert captured["fdc_run_count"] == 1
    assert pool_calls == ["create", "close"], (
        "flag on이면 legacy 경로가 DB pool을 열고 반드시 닫아야 한다"
    )
    # _build_agent_triplet()에 넘어간 acquire_permit이 실제로 구성된
    # _FdcPermitAccumulator.acquire 메서드다(gate가 wiring됐다는 증거).
    assert captured["build_agent_triplet_acquire_permit"] is not None


@pytest.mark.asyncio
async def test_mode_pre_fdc_skips_fdc_when_deterministic_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mode="pre_fdc"라도 결정론적 skip 조건(risk reject 등)이면 FDC를
    부르지 않고 완전한 output을 즉시 만든다 — requires_fdc_dispatch는
    False."""
    payload = _base_payload(mode="pre_fdc")
    monkeypatch.setattr(
        script.sys, "stdin", SimpleNamespace(buffer=_FakeStdinBuffer(payload))
    )
    captured = _install_common_main_stubs(monkeypatch)

    def _fake_check_fdc_skip(*, inp, request, event_output, risk_output):
        return (
            True, "risk_reject",
            FinalDecisionComposerOutput(
                symbol="005930", decision_type="HOLD", confidence=0.0,
                reason_codes=("risk_rejected",),
            ),
        )

    monkeypatch.setattr(script, "_check_fdc_skip", _fake_check_fdc_skip)

    await script.main()

    assert captured["fdc_run_count"] == 0
    output = captured["written"]["output"]
    assert output.success is True
    assert output.fdc_skipped is True
    assert output.requires_fdc_dispatch is False


@pytest.mark.asyncio
async def test_mode_pre_fdc_ready_does_not_call_fdc_and_flags_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mode="pre_fdc" + FDC-ready(skip 아님)면 FDC를 전혀 호출하지 않고
    requires_fdc_dispatch=True로 즉시 반환한다 — composer_output은
    비어 있다."""
    payload = _base_payload(mode="pre_fdc")
    monkeypatch.setattr(
        script.sys, "stdin", SimpleNamespace(buffer=_FakeStdinBuffer(payload))
    )
    captured = _install_common_main_stubs(monkeypatch)

    def _fake_check_fdc_skip(*, inp, request, event_output, risk_output):
        return (False, "", FinalDecisionComposerOutput())

    monkeypatch.setattr(script, "_check_fdc_skip", _fake_check_fdc_skip)

    await script.main()

    assert captured["fdc_run_count"] == 0  # FDC agent는 호출되지 않는다
    output = captured["written"]["output"]
    assert output.success is True
    assert output.fdc_skipped is False
    assert output.requires_fdc_dispatch is True
    # composer_output은 placeholder일 뿐 신뢰 대상이 아니다 — 호출자
    # (DecisionAgentRunner)는 requires_fdc_dispatch=True를 보면 이 값을
    # 무시하고 fdc_only 결과로 교체한다.
    # EI/AR/AC 결과는 그대로 채워져 있다(다음 fdc_only 호출의 carryover로 쓰임).
    assert output.event_output
    assert output.risk_output
    assert output.compliance_output


# ===========================================================================
# mode="fdc_only" — _run_fdc_only_mode()
# ===========================================================================


@pytest.mark.asyncio
async def test_fdc_only_mode_missing_reservation_fields_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """reservation_id/job_id/quota_scope 중 하나라도 없으면 즉시
    실패한다(방어적 검증) — 실제 DB pool도 열지 않는다."""
    payload = _base_payload(mode="fdc_only")
    monkeypatch.setattr(
        script.sys, "stdin", SimpleNamespace(buffer=_FakeStdinBuffer(payload))
    )

    written_errors: list[str] = []
    monkeypatch.setattr(
        script, "_write_error_output",
        lambda msg, **kwargs: written_errors.append(msg),
    )

    async def _should_not_be_called(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("create_pool()이 호출됐다 — 사전 검증이 먼저 실패해야 한다")

    import agent_trading.db.connection as db_connection_module
    monkeypatch.setattr(db_connection_module, "create_pool", _should_not_be_called)

    with pytest.raises(SystemExit) as exc_info:
        await script.main()

    assert exc_info.value.code == 1
    assert written_errors


@pytest.mark.asyncio
async def test_fdc_only_mode_success_calls_fdc_once_and_closes_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mode="fdc_only" 정상 경로 — EI/AR/AC는 호출되지 않고 FDC만
    정확히 1회 실행되며, DB pool은 반드시 정리된다."""
    payload = _base_payload(mode="fdc_only")
    payload["event_interpretation_output"] = {"symbol": "005930"}
    payload["ai_risk_output"] = {"risk_opinion": "allow"}
    payload["ai_compliance_output"] = {"compliance_opinion": "allow"}
    payload["reservation_id"] = "11111111-1111-1111-1111-111111111111"
    payload["reservation_job_id"] = "22222222-2222-2222-2222-222222222222"
    payload["reservation_quota_scope"] = "gemini:shared-operational"
    payload["reservation_attempt_no"] = 1
    payload["reservation_window_count_before_grant"] = 3
    monkeypatch.setattr(
        script.sys, "stdin", SimpleNamespace(buffer=_FakeStdinBuffer(payload))
    )

    pool_calls: list[str] = []

    async def _fake_create_pool(*args: Any, **kwargs: Any) -> None:
        pool_calls.append("create")

    async def _fake_close_pool(*args: Any, **kwargs: Any) -> None:
        pool_calls.append("close")

    import agent_trading.db.connection as db_connection_module
    monkeypatch.setattr(db_connection_module, "create_pool", _fake_create_pool)
    monkeypatch.setattr(db_connection_module, "close_pool", _fake_close_pool)

    class _FakeAmbientTx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    import agent_trading.db.transaction as db_transaction_module
    monkeypatch.setattr(
        db_transaction_module, "TransactionManager", lambda: _FakeAmbientTx()
    )

    fdc_run_count = 0

    class _FakeFdcAgent:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def run(self, request: Any) -> FinalDecisionComposerOutput:
            nonlocal fdc_run_count
            fdc_run_count += 1
            return FinalDecisionComposerOutput(
                symbol="005930", decision_type="HOLD", confidence=0.5,
            )

    monkeypatch.setattr(script, "FinalDecisionComposerAgent", _FakeFdcAgent)

    written: dict[str, Any] = {}
    monkeypatch.setattr(
        script, "_write_output", lambda output: written.update(output=output)
    )

    await script.main()

    assert fdc_run_count == 1
    assert pool_calls == ["create", "close"]
    output = written["output"]
    assert output.success is True
    assert output.composer_output["decision_type"] == "HOLD"


@pytest.mark.asyncio
async def test_fdc_only_mode_flag_on_wires_global_gate_into_pre_granted_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PR D(2026-09-03) — flag on이면 ``_run_fdc_only_mode()``가
    ``FdcProviderGlobalGate``를 구성해 ``PreGrantedFdcProviderClient``에
    전달한다(flag off인 기존 테스트는 ``global_gate=None``으로 여전히
    통과 — 회귀 없음)."""
    payload = _base_payload(mode="fdc_only")
    payload["event_interpretation_output"] = {"symbol": "005930"}
    payload["ai_risk_output"] = {"risk_opinion": "allow"}
    payload["ai_compliance_output"] = {"compliance_opinion": "allow"}
    payload["reservation_id"] = "11111111-1111-1111-1111-111111111111"
    payload["reservation_job_id"] = "22222222-2222-2222-2222-222222222222"
    payload["reservation_quota_scope"] = "gemini:shared-operational"
    payload["reservation_attempt_no"] = 1
    payload["reservation_window_count_before_grant"] = 3
    monkeypatch.setattr(
        script.sys, "stdin", SimpleNamespace(buffer=_FakeStdinBuffer(payload))
    )

    import agent_trading.config.settings as settings_module
    monkeypatch.setattr(
        settings_module, "_resolve_fdc_provider_global_gate_enabled", lambda: True,
    )

    async def _fake_create_pool(*args: Any, **kwargs: Any) -> None:
        return None

    async def _fake_close_pool(*args: Any, **kwargs: Any) -> None:
        return None

    import agent_trading.db.connection as db_connection_module
    monkeypatch.setattr(db_connection_module, "create_pool", _fake_create_pool)
    monkeypatch.setattr(db_connection_module, "close_pool", _fake_close_pool)

    class _FakeAmbientTx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    import agent_trading.db.transaction as db_transaction_module
    monkeypatch.setattr(
        db_transaction_module, "TransactionManager", lambda: _FakeAmbientTx()
    )

    from agent_trading.repositories.memory import InMemoryFdcQuotaRepository

    import agent_trading.repositories.postgres.fdc_quota as fdc_quota_module
    monkeypatch.setattr(
        fdc_quota_module, "PostgresFdcQuotaRepository",
        lambda tx: InMemoryFdcQuotaRepository(),
    )

    import scripts.fdc_manual_provider_gate as gate_module

    captured_kwargs: dict[str, Any] = {}
    real_pre_granted_client = gate_module.PreGrantedFdcProviderClient

    class _CapturingPreGrantedClient(real_pre_granted_client):
        def __init__(self, **kwargs: Any) -> None:
            captured_kwargs.update(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(
        gate_module, "PreGrantedFdcProviderClient", _CapturingPreGrantedClient,
    )

    class _FakeFdcAgent:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def run(self, request: Any) -> FinalDecisionComposerOutput:
            return FinalDecisionComposerOutput(
                symbol="005930", decision_type="HOLD", confidence=0.5,
            )

    monkeypatch.setattr(script, "FinalDecisionComposerAgent", _FakeFdcAgent)
    monkeypatch.setattr(script, "_write_output", lambda output: None)

    await script.main()

    from agent_trading.services.fdc_provider_global_gate import FdcProviderGlobalGate

    assert isinstance(captured_kwargs.get("global_gate"), FdcProviderGlobalGate), (
        "flag on이면 PreGrantedFdcProviderClient가 실제 FdcProviderGlobalGate "
        "인스턴스를 받아야 한다"
    )


@pytest.mark.asyncio
async def test_fdc_only_mode_pool_closed_even_when_fdc_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FDC 실행 중 예외가 나도(예: LiveGeminiProviderClient 구성 실패)
    DB pool은 반드시 정리된다."""
    payload = _base_payload(mode="fdc_only")
    payload["event_interpretation_output"] = {"symbol": "005930"}
    payload["ai_risk_output"] = {"risk_opinion": "allow"}
    payload["ai_compliance_output"] = {"compliance_opinion": "allow"}
    payload["reservation_id"] = "11111111-1111-1111-1111-111111111111"
    payload["reservation_job_id"] = "22222222-2222-2222-2222-222222222222"
    payload["reservation_quota_scope"] = "gemini:shared-operational"
    monkeypatch.setattr(
        script.sys, "stdin", SimpleNamespace(buffer=_FakeStdinBuffer(payload))
    )

    pool_calls: list[str] = []

    async def _fake_create_pool(*args: Any, **kwargs: Any) -> None:
        pool_calls.append("create")

    async def _fake_close_pool(*args: Any, **kwargs: Any) -> None:
        pool_calls.append("close")

    import agent_trading.db.connection as db_connection_module
    monkeypatch.setattr(db_connection_module, "create_pool", _fake_create_pool)
    monkeypatch.setattr(db_connection_module, "close_pool", _fake_close_pool)

    class _FakeAmbientTx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    import agent_trading.db.transaction as db_transaction_module
    monkeypatch.setattr(
        db_transaction_module, "TransactionManager", lambda: _FakeAmbientTx()
    )

    def _raising_repo(tx: Any) -> Any:
        raise RuntimeError("simulated repo construction failure")

    import agent_trading.repositories.postgres.fdc_quota as fdc_quota_module
    monkeypatch.setattr(
        fdc_quota_module, "PostgresFdcQuotaRepository", _raising_repo
    )

    written_errors: list[str] = []
    monkeypatch.setattr(
        script, "_write_error_output",
        lambda msg, **kwargs: written_errors.append(msg),
    )

    with pytest.raises(SystemExit) as exc_info:
        await script.main()

    assert exc_info.value.code == 1
    assert pool_calls == ["create", "close"]
    assert written_errors


# ===========================================================================
# _FdcPermitAccumulator.acquire() — PR D(2026-09-03) global gate 주입
# ===========================================================================
#
# legacy limiter(wait_for_fdc_slot())는 파일 기반이라 여기서는 monkeypatch로
# 결과를 직접 통제한다 — 실제 파일 I/O 없음. global gate는 InMemoryFdcQuota
# Repository로 실제 window 로직을 그대로 실행한다(mock으로 gate 판정
# 자체를 대체하지 않는다).


def _fake_rate_limit_result(
    *, granted: bool, queue_timeout: bool = False, state_file_error: bool = False,
) -> Any:
    from agent_trading.services.ai_agents.fdc_rate_limiter import FdcRateLimitResult

    return FdcRateLimitResult(
        granted=granted, waited_seconds=0.0,
        queue_timeout=queue_timeout, state_file_error=state_file_error,
    )


class TestFdcPermitAccumulatorGlobalGate:
    @pytest.mark.asyncio
    async def test_legacy_denied_gate_never_called(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """legacy limiter가 거부하면 global gate는 아예 호출되지 않는다
        (§4.2 확정 순서 — legacy 먼저, grant 후에만 gate)."""
        async def _fake_wait_for_fdc_slot(**kwargs: Any) -> Any:
            return _fake_rate_limit_result(granted=False, queue_timeout=True)

        monkeypatch.setattr(script, "wait_for_fdc_slot", _fake_wait_for_fdc_slot)

        gate_call_count = {"n": 0}

        class _CountingGate:
            async def acquire(self, **kwargs: Any) -> Any:
                gate_call_count["n"] += 1
                raise AssertionError("gate should not be called when legacy denies")

        accumulator = script._FdcPermitAccumulator(
            lane="held_position", global_gate=_CountingGate(),
        )
        result = await accumulator.acquire()

        assert result.granted is False
        assert result.denial_reason == "queue_timeout"
        assert gate_call_count["n"] == 0

    @pytest.mark.asyncio
    async def test_legacy_granted_gate_granted_final_result_granted(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from agent_trading.repositories.memory import InMemoryFdcQuotaRepository
        from agent_trading.services.fdc_provider_global_gate import (
            FdcProviderGlobalGate,
        )

        async def _fake_wait_for_fdc_slot(**kwargs: Any) -> Any:
            return _fake_rate_limit_result(granted=True)

        monkeypatch.setattr(script, "wait_for_fdc_slot", _fake_wait_for_fdc_slot)

        global_gate = FdcProviderGlobalGate(
            repo=InMemoryFdcQuotaRepository(), target_rpm=13, window_seconds=60,
        )
        accumulator = script._FdcPermitAccumulator(
            lane="held_position", global_gate=global_gate,
        )
        result = await accumulator.acquire()

        assert result.granted is True
        assert result.denial_reason is None

    @pytest.mark.asyncio
    async def test_legacy_granted_gate_denied_final_result_denied_with_gate_reason(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """legacy는 grant했지만 gate window가 가득 찼으면 최종 결과는
        거부이며, denial_reason은 gate의 것("global_gate_timeout")으로
        치환된다 — legacy 자신의 queue_timeout/state_file_error와
        혼동되지 않는다."""
        from agent_trading.repositories.memory import InMemoryFdcQuotaRepository
        from agent_trading.services.fdc_provider_global_gate import (
            FdcProviderGlobalGate,
        )

        async def _fake_wait_for_fdc_slot(**kwargs: Any) -> Any:
            return _fake_rate_limit_result(granted=True)

        monkeypatch.setattr(script, "wait_for_fdc_slot", _fake_wait_for_fdc_slot)

        global_gate = FdcProviderGlobalGate(
            repo=InMemoryFdcQuotaRepository(), target_rpm=1, window_seconds=60,
        )
        # target_rpm=1인 정상 설정에서 첫 grant로 window를 채워 포화
        # 상태를 만든다(invalid config에 의존하지 않는다).
        prefill = await global_gate.acquire(caller_lane="legacy", caller_id="prefill")
        assert prefill.granted is True

        accumulator = script._FdcPermitAccumulator(
            lane="held_position", global_gate=global_gate,
        )
        result = await accumulator.acquire()

        assert result.granted is False
        assert result.denial_reason == "global_gate_timeout"

    @pytest.mark.asyncio
    async def test_global_gate_none_is_full_noop_regression(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``global_gate=None``(기본값, flag off)이면 기존(PR D 이전)
        동작과 100% 동일하다 — gate 관련 코드가 전혀 실행되지 않는다."""
        async def _fake_wait_for_fdc_slot(**kwargs: Any) -> Any:
            return _fake_rate_limit_result(granted=True)

        monkeypatch.setattr(script, "wait_for_fdc_slot", _fake_wait_for_fdc_slot)

        accumulator = script._FdcPermitAccumulator(lane="held_position")
        result = await accumulator.acquire()

        assert result.granted is True
        assert result.denial_reason is None

    @pytest.mark.asyncio
    async def test_429_retry_calls_gate_once_per_attempt(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """provider_client.py의 재시도 루프가 매 attempt마다 acquire()
        (=이 accumulator)를 다시 호출하므로, gate도 attempt마다 정확히
        1회씩 통과한다(이중 계산/누락 없음)."""
        from agent_trading.repositories.memory import InMemoryFdcQuotaRepository
        from agent_trading.services.fdc_provider_global_gate import (
            FdcProviderGlobalGate,
        )

        async def _fake_wait_for_fdc_slot(**kwargs: Any) -> Any:
            return _fake_rate_limit_result(granted=True)

        monkeypatch.setattr(script, "wait_for_fdc_slot", _fake_wait_for_fdc_slot)

        gate_call_count = {"n": 0}
        inner_repo = InMemoryFdcQuotaRepository()

        class _CountingGateRepo:
            async def try_acquire_provider_global_gate_permit(self, **kwargs: Any):
                gate_call_count["n"] += 1
                return await inner_repo.try_acquire_provider_global_gate_permit(**kwargs)

        global_gate = FdcProviderGlobalGate(
            repo=_CountingGateRepo(), target_rpm=13, window_seconds=60,
        )
        accumulator = script._FdcPermitAccumulator(
            lane="held_position", global_gate=global_gate,
        )

        # provider_client.py의 MAX_RETRIES 루프가 매 attempt(최초+429
        # 재시도 2회)마다 acquire()를 호출하는 것을 그대로 재현한다.
        for _ in range(3):
            result = await accumulator.acquire()
            assert result.granted is True

        assert gate_call_count["n"] == 3


# ===========================================================================
# _LegacyFdcHttpStartRecorder — 2026-09-06 재설계(lazy pool open, 공용
# provider client 계약 변경 없이 FDC 전용 서브클래스로만 배선)
# ===========================================================================


def _patch_recorder_db(
    monkeypatch: pytest.MonkeyPatch,
    *,
    create_pool_raises: bool = False,
    write_raises: bool = False,
) -> dict[str, Any]:
    """recorder의 lazy import 대상(``create_pool``/``TransactionManager``/
    ``PostgresFdcQuotaRepository``)을 실제 DB 없이 통제한다."""
    calls: dict[str, Any] = {"create_pool": 0, "record_calls": []}

    async def _fake_create_pool(*args: Any, **kwargs: Any) -> None:
        calls["create_pool"] += 1
        if create_pool_raises:
            raise ConnectionError("db unreachable (test)")

    import agent_trading.db.connection as db_connection_module
    monkeypatch.setattr(db_connection_module, "create_pool", _fake_create_pool)

    class _FakeAmbientTx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    import agent_trading.db.transaction as db_transaction_module
    monkeypatch.setattr(
        db_transaction_module, "TransactionManager", lambda: _FakeAmbientTx()
    )

    class _FakeRepo:
        def __init__(self, tx: Any) -> None:
            pass

        async def record_legacy_http_start_event(self, **kwargs: Any) -> None:
            if write_raises:
                raise RuntimeError("insert failed (test)")
            calls["record_calls"].append(kwargs)

    import agent_trading.repositories.postgres.fdc_quota as fdc_quota_module
    monkeypatch.setattr(fdc_quota_module, "PostgresFdcQuotaRepository", _FakeRepo)

    return calls


class TestLegacyFdcHttpStartRecorder:
    @pytest.mark.asyncio
    async def test_success_records_one_event_and_marks_pool_opened(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls = _patch_recorder_db(monkeypatch)
        recorder = script._LegacyFdcHttpStartRecorder(
            provider_scope="gemini:provider-global",
            decision_context_id="dc-1", correlation_id="corr-1",
        )
        assert recorder.pool_opened is False

        await recorder()

        assert recorder.pool_opened is True
        assert len(calls["record_calls"]) == 1
        event = calls["record_calls"][0]
        assert event["provider_scope"] == "gemini:provider-global"
        assert event["decision_context_id"] == "dc-1"
        assert event["correlation_id"] == "corr-1"
        assert event["attempt_no"] == 1

    @pytest.mark.asyncio
    async def test_attempt_no_increments_per_call(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls = _patch_recorder_db(monkeypatch)
        recorder = script._LegacyFdcHttpStartRecorder(
            provider_scope="gemini:provider-global",
            decision_context_id=None, correlation_id=None,
        )
        await recorder()
        await recorder()
        await recorder()

        attempt_nos = [e["attempt_no"] for e in calls["record_calls"]]
        assert attempt_nos == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_create_pool_failure_is_swallowed_fail_open(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Finding 1 핵심 계약 — pool 생성 자체가 실패해도 recorder는
        예외를 던지지 않는다(fail-open). ``pool_opened``는 False로
        남는다(실제로 열리지 않았으므로)."""
        calls = _patch_recorder_db(monkeypatch, create_pool_raises=True)
        recorder = script._LegacyFdcHttpStartRecorder(
            provider_scope="gemini:provider-global",
            decision_context_id=None, correlation_id=None,
        )

        await recorder()  # 예외가 전파되지 않아야 한다.

        assert recorder.pool_opened is False
        assert calls["record_calls"] == []
        assert calls["create_pool"] == 1

    @pytest.mark.asyncio
    async def test_repo_write_failure_after_pool_open_is_swallowed_fail_open(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """pool은 성공적으로 열렸지만 INSERT 자체가 실패하는 경우 —
        여전히 예외를 삼킨다(fail-open). ``pool_opened``는 True로
        남는다(실제로 pool은 열렸으므로 — main()이 이 값으로 close_pool
        여부를 판단한다)."""
        calls = _patch_recorder_db(monkeypatch, write_raises=True)
        recorder = script._LegacyFdcHttpStartRecorder(
            provider_scope="gemini:provider-global",
            decision_context_id=None, correlation_id=None,
        )

        await recorder()  # 예외가 전파되지 않아야 한다.

        assert recorder.pool_opened is True
        assert calls["record_calls"] == []


# ===========================================================================
# _LegacyObservedProviderClient — 2026-09-06 신설. 공용
# OpenAICompatibleClient.generate_structured()는 전혀 건드리지 않고
# _single_http_attempt()만 오버라이드해 client.post() 직전 recorder를
# 주입한다.
# ===========================================================================


def _make_observed_client(
    handler: Any, *, recorder: Any,
) -> Any:
    import httpx

    client = script._LegacyObservedProviderClient(
        http_start_recorder=recorder,
        api_key="test-key", base_url="https://fake.example", timeout_seconds=10,
    )
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://fake.example",
    )
    return client


class TestLegacyObservedProviderClient:
    @pytest.mark.asyncio
    async def test_recorder_called_exactly_once_before_post_on_success(self) -> None:
        import httpx

        call_order: list[str] = []

        def handler(req: httpx.Request) -> httpx.Response:
            call_order.append("post")
            return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

        async def _recorder() -> None:
            call_order.append("recorder")

        client = _make_observed_client(handler, recorder=_recorder)
        from agent_trading.services.ai_agents.base import RawProviderResponse
        from dataclasses import dataclass

        @dataclass(slots=True, frozen=True)
        class _Out:
            symbol: str = ""

        result = await client.generate_structured(
            model_id="m", system_prompt="s", user_prompt="u", response_format=_Out,
        )
        assert isinstance(result, RawProviderResponse)
        assert call_order == ["recorder", "post"]

    @pytest.mark.asyncio
    async def test_recorder_called_once_per_physical_retry(self) -> None:
        import httpx
        from dataclasses import dataclass

        @dataclass(slots=True, frozen=True)
        class _Out:
            symbol: str = ""

        http_call_count = [0]
        recorder_calls = [0]

        def handler(req: httpx.Request) -> httpx.Response:
            http_call_count[0] += 1
            if http_call_count[0] < 3:
                return httpx.Response(429, json={"error": "rate limited"})
            return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

        async def _recorder() -> None:
            recorder_calls[0] += 1

        client = _make_observed_client(handler, recorder=_recorder)
        result = await client.generate_structured(
            model_id="m", system_prompt="s", user_prompt="u", response_format=_Out,
        )
        assert http_call_count[0] == 3
        assert recorder_calls[0] == 3
        assert result.http_attempt_count == 3

    @pytest.mark.asyncio
    async def test_permit_denied_recorder_never_called(self) -> None:
        import httpx
        from dataclasses import dataclass
        from agent_trading.services.ai_agents.provider_client import (
            PermitDeniedError, PermitResult,
        )

        @dataclass(slots=True, frozen=True)
        class _Out:
            symbol: str = ""

        recorder_called = False

        async def _recorder() -> None:
            nonlocal recorder_called
            recorder_called = True

        post_called = False

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal post_called
            post_called = True
            return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

        async def _deny_permit() -> PermitResult:
            return PermitResult(granted=False, waited_seconds=0.0, denial_reason="queue_timeout")

        client = _make_observed_client(handler, recorder=_recorder)
        with pytest.raises(PermitDeniedError):
            await client.generate_structured(
                model_id="m", system_prompt="s", user_prompt="u", response_format=_Out,
                acquire_permit=_deny_permit,
            )
        assert recorder_called is False
        assert post_called is False

    @pytest.mark.asyncio
    async def test_real_lazy_recorder_pool_failure_does_not_block_http_success(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Finding 1 통합 증명 — recorder가 실제(lazy) DB 경로를 쓰더라도
        pool 생성 실패가 HTTP 자체를 막지 않는다."""
        import httpx
        from dataclasses import dataclass

        @dataclass(slots=True, frozen=True)
        class _Out:
            symbol: str = ""

        calls = _patch_recorder_db(monkeypatch, create_pool_raises=True)

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

        recorder = script._LegacyFdcHttpStartRecorder(
            provider_scope="gemini:provider-global",
            decision_context_id="dc-1", correlation_id="corr-1",
        )
        client = _make_observed_client(handler, recorder=recorder)
        result = await client.generate_structured(
            model_id="m", system_prompt="s", user_prompt="u", response_format=_Out,
        )
        assert result is not None
        assert calls["create_pool"] == 1
        assert calls["record_calls"] == []
        assert recorder.pool_opened is False

    @pytest.mark.asyncio
    async def test_real_lazy_recorder_write_failure_does_not_block_http_success(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import httpx
        from dataclasses import dataclass

        @dataclass(slots=True, frozen=True)
        class _Out:
            symbol: str = ""

        calls = _patch_recorder_db(monkeypatch, write_raises=True)

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

        recorder = script._LegacyFdcHttpStartRecorder(
            provider_scope="gemini:provider-global",
            decision_context_id="dc-1", correlation_id="corr-1",
        )
        client = _make_observed_client(handler, recorder=recorder)
        result = await client.generate_structured(
            model_id="m", system_prompt="s", user_prompt="u", response_format=_Out,
        )
        assert result is not None
        assert calls["record_calls"] == []
        assert recorder.pool_opened is True


# ===========================================================================
# main() 배선 — 2026-09-06 보정: deterministic FDC skip 경로에서는 DB
# pool 생성도, recorder 호출도 전혀 일어나지 않는다(recorder가 실제
# FDC 전용 서브클라이언트 안에 있으므로 fdc_agent.run()이 호출되지
# 않으면 자동으로 보장된다 — 아래는 이를 create_pool spy로 명시 증명).
# ===========================================================================


@pytest.mark.asyncio
async def test_mode_full_deterministic_skip_never_touches_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _base_payload(mode="full")
    monkeypatch.setattr(
        script.sys, "stdin", SimpleNamespace(buffer=_FakeStdinBuffer(payload))
    )
    captured = _install_common_main_stubs(monkeypatch)

    def _fake_check_fdc_skip(*, inp, request, event_output, risk_output):
        return (
            True, "test_skip",
            FinalDecisionComposerOutput(symbol="005930", decision_type="HOLD"),
        )

    monkeypatch.setattr(script, "_check_fdc_skip", _fake_check_fdc_skip)

    pool_create_calls: list[str] = []

    async def _fake_create_pool(*args: Any, **kwargs: Any) -> None:
        pool_create_calls.append("create")

    import agent_trading.db.connection as db_connection_module
    monkeypatch.setattr(db_connection_module, "create_pool", _fake_create_pool)

    await script.main()

    assert captured["fdc_run_count"] == 0
    assert pool_create_calls == [], "deterministic skip이면 DB pool을 전혀 열면 안 된다"
