"""Tests for ``scripts/ar_fdc_provider_validation.py``(2026-08-27 PR A).

이 스크립트의 실제 quota/one-shot 로직은
``tests/scripts/test_fdc_manual_provider_gate.py``가 이미 좁게
검증한다 — 여기서는 ``main()``이 그 로직을 실제로 호출하는 배관과,
운영 시간(거래일) fail-closed 차단이 DB 연결보다 먼저 일어나는지만
검증한다(fake clock/fake DB/fake provider, 실제 sleep/DB/HTTP 없음).
"""

from __future__ import annotations

import inspect
import json

import pytest

from scripts import ar_fdc_provider_validation as script
from scripts.fdc_manual_provider_gate import MarketHoursBlockedError


class TestArFdcQuotaScopeSeparation:
    """2026-08-27 리뷰 보정: AR 호출은 FDC 공용 13 RPM coordinator의
    대상이 아니다 — ``_call_ar()``의 시그니처 자체가 coordinator를
    받지 않도록 구조적으로 강제한다(실수로 다시 연결할 방법이 없다)."""

    def test_call_ar_has_no_coordinator_parameter(self) -> None:
        sig = inspect.signature(script._call_ar)
        assert "coordinator" not in sig.parameters
        assert "manual_run_id" not in sig.parameters

    def test_call_fdc_still_requires_coordinator(self) -> None:
        sig = inspect.signature(script._call_fdc)
        assert "coordinator" in sig.parameters
        assert "manual_run_id" in sig.parameters


@pytest.mark.asyncio
async def test_market_hours_blocked_returns_1_before_any_db_connection(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """운영 시간(거래일)이면 artifact를 로드한 뒤에도 DB(TransactionManager)
    를 전혀 열지 않고 즉시 실패로 종료해야 한다."""
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(
        json.dumps({
            "meta": {"symbol": "030200", "event_count": 1},
            "prompts": {}, "system_prompts": {},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(script, "ARTIFACT_PATH", artifact_path)

    async def _blocked(*, script_name: str) -> None:
        raise MarketHoursBlockedError(f"{script_name}: blocked for test")

    monkeypatch.setattr(script, "assert_not_market_hours", _blocked)

    def _tx_manager_should_not_be_called(*args, **kwargs):
        raise AssertionError(
            "TransactionManager()가 호출됐다 — 운영 시간 차단이 DB 연결보다 "
            "먼저 일어나야 한다"
        )

    monkeypatch.setattr(script, "TransactionManager", _tx_manager_should_not_be_called)

    async def _create_pool_should_not_be_called(*args, **kwargs):
        raise AssertionError(
            "create_pool()이 호출됐다 — 운영 시간 차단이 DB pool 초기화보다 "
            "먼저 일어나야 한다(2026-08-27 3차 리뷰 보정)"
        )

    monkeypatch.setattr(script, "create_pool", _create_pool_should_not_be_called)

    exit_code = await script.main()

    assert exit_code == 1


def _writable_artifact(tmp_path):
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text(
        json.dumps({
            "meta": {"symbol": "030200", "event_count": 1},
            "prompts": {}, "system_prompts": {},
        }),
        encoding="utf-8",
    )
    return artifact_path


class _FakeAmbientTx:
    """``TransactionManager()``를 흉내낸다 — repo 생성자를 채우는
    용도로만 쓰이며, 실제 DB 연결을 열지 않는다."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.mark.asyncio
async def test_non_trading_day_reaches_pool_init_and_coordinator_construction(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """비거래일 허용 경로가 DB pool 초기화(create_pool) 후 coordinator
    구성까지 도달하는지, 정상 종료 시 close_pool()이 호출되는지 확인한다
    (2026-08-27 3차 리뷰 보정)."""
    monkeypatch.setattr(script, "ARTIFACT_PATH", _writable_artifact(tmp_path))

    async def _allowed(*, script_name: str) -> None:
        return None  # 예외 없음 = 비거래일

    monkeypatch.setattr(script, "assert_not_market_hours", _allowed)

    pool_calls: list[str] = []

    async def _fake_create_pool(*args, **kwargs):
        pool_calls.append("create")

    async def _fake_close_pool(*args, **kwargs):
        pool_calls.append("close")

    monkeypatch.setattr(script, "create_pool", _fake_create_pool)
    monkeypatch.setattr(script, "close_pool", _fake_close_pool)
    monkeypatch.setattr(script, "TransactionManager", lambda: _FakeAmbientTx())
    monkeypatch.setattr(script, "PostgresFdcQuotaRepository", lambda tx: object())

    captured_coordinator_kwargs: dict = {}

    class _FakeCoordinator:
        def __init__(self, **kwargs):
            captured_coordinator_kwargs.update(kwargs)

    monkeypatch.setattr(script, "FdcQuotaCoordinator", _FakeCoordinator)

    class _FakeLiveClient:
        def __init__(self, **kwargs):
            pass

        async def close(self):
            pass

    monkeypatch.setattr(script, "LiveGeminiProviderClient", _FakeLiveClient)

    class _FakeArClient:
        def __init__(self, **kwargs):
            pass

        async def close(self):
            pass

    monkeypatch.setattr(script, "OpenAICompatibleClient", _FakeArClient)

    async def _fake_call_ar(*args, **kwargs):
        return {"run": "ar", "success": True, "used_fallback": False, "duration_seconds": 0.0,
                "parsed_output": {"risk_opinion": "allow", "risk_score": 0.0, "reason_codes": []},
                "raw_response_preview": ""}

    async def _fake_call_fdc(*args, **kwargs):
        return {"run": "fdc", "success": True, "used_fallback": False, "duration_seconds": 0.0,
                "parsed_output": {"decision_type": "HOLD", "confidence": 0.5},
                "raw_response_preview": ""}

    monkeypatch.setattr(script, "_call_ar", _fake_call_ar)
    monkeypatch.setattr(script, "_call_fdc", _fake_call_fdc)

    # provider_api_key가 비어있으면 그 자리에서 조기 반환하므로 채운다.
    class _FakeSettings:
        provider_api_key = "fake-key"
        provider_base_url = "https://fake"
        provider_model_id = "fake-model"
        fdc_provider_target_rpm = 13
        fdc_provider_rate_window_seconds = 60
        gemini_provider_declared_rpm_limit = 15

    monkeypatch.setattr(script, "AppSettings", lambda: _FakeSettings())

    exit_code = await script.main()

    assert exit_code == 0
    assert pool_calls == ["create", "close"]
    assert "manual_call_policy" in captured_coordinator_kwargs
    assert captured_coordinator_kwargs["manual_call_policy"] is not None


@pytest.mark.asyncio
async def test_pool_is_closed_even_when_call_raises(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AR/FDC 호출 중 예외가 발생해도(조기 반환 경로) close_pool()이
    반드시 호출돼야 한다."""
    monkeypatch.setattr(script, "ARTIFACT_PATH", _writable_artifact(tmp_path))

    async def _allowed(*, script_name: str) -> None:
        return None

    monkeypatch.setattr(script, "assert_not_market_hours", _allowed)

    pool_calls: list[str] = []

    async def _fake_create_pool(*args, **kwargs):
        pool_calls.append("create")

    async def _fake_close_pool(*args, **kwargs):
        pool_calls.append("close")

    monkeypatch.setattr(script, "create_pool", _fake_create_pool)
    monkeypatch.setattr(script, "close_pool", _fake_close_pool)
    monkeypatch.setattr(script, "TransactionManager", lambda: _FakeAmbientTx())
    monkeypatch.setattr(script, "PostgresFdcQuotaRepository", lambda tx: object())
    monkeypatch.setattr(script, "FdcQuotaCoordinator", lambda **kwargs: object())

    class _FakeClient:
        def __init__(self, **kwargs):
            pass

        async def close(self):
            pass

    monkeypatch.setattr(script, "LiveGeminiProviderClient", _FakeClient)
    monkeypatch.setattr(script, "OpenAICompatibleClient", _FakeClient)

    import asyncio as _asyncio

    async def _raising_call_ar(*args, **kwargs):
        raise _asyncio.TimeoutError()

    monkeypatch.setattr(script, "_call_ar", _raising_call_ar)

    class _FakeSettings:
        provider_api_key = "fake-key"
        provider_base_url = "https://fake"
        provider_model_id = "fake-model"
        fdc_provider_target_rpm = 13
        fdc_provider_rate_window_seconds = 60
        gemini_provider_declared_rpm_limit = 15

    monkeypatch.setattr(script, "AppSettings", lambda: _FakeSettings())

    exit_code = await script.main()

    assert exit_code == 1
    assert pool_calls == ["create", "close"]


@pytest.mark.asyncio
async def test_missing_artifact_returns_1_before_market_hours_check(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """artifact가 없으면 운영 시간 확인조차 하지 않고 즉시 실패한다
    (기존 동작 보존 — Phase 1 선행 조건 안내가 그대로 나가야 한다)."""
    missing_path = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(script, "ARTIFACT_PATH", missing_path)

    called = False

    async def _spy(*, script_name: str) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(script, "assert_not_market_hours", _spy)

    exit_code = await script.main()

    assert exit_code == 1
    assert called is False
