"""Tests for ``scripts/ar_fdc_output_measurement.py``(2026-08-27 PR A).

``--with-provider`` 경로가 운영 시간(거래일) fail-closed 차단을 DB
연결(``postgres_runtime()``)보다 먼저 확인하는지만 검증한다. 이 스크립트의
실제 quota/permit-adapter 로직은
``tests/scripts/test_fdc_manual_provider_gate.py``가 이미 좁게 검증한다.
fake clock/fake DB만 사용 — 실제 sleep/DB/HTTP 없음.
"""

from __future__ import annotations

import inspect

import pytest

from scripts import ar_fdc_output_measurement as script
from scripts.fdc_manual_provider_gate import MarketHoursBlockedError


class TestArFdcQuotaScopeSeparation:
    """2026-08-27 리뷰 보정: AR과 FDC는 서로 다른 provider client
    파라미터를 쓴다 — ``measure_symbol()``의 시그니처 자체가 단일
    ``provider_client``(AR/FDC 공용)로 되돌아가지 않도록 구조적으로
    강제한다."""

    def test_measure_symbol_has_separate_ar_and_fdc_client_params(self) -> None:
        sig = inspect.signature(script.measure_symbol)
        assert "ar_provider_client" in sig.parameters
        assert "fdc_provider_client" in sig.parameters
        assert "provider_client" not in sig.parameters  # 옛 단일 파라미터 제거됨
        assert "coordinator" not in sig.parameters  # AR 경로에 노출되지 않음


@pytest.mark.asyncio
async def test_with_provider_market_hours_blocked_returns_1_before_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sys.argv", ["ar_fdc_output_measurement.py", "--with-provider"])

    async def _blocked(*, script_name: str) -> None:
        raise MarketHoursBlockedError(f"{script_name}: blocked for test")

    monkeypatch.setattr(script, "assert_not_market_hours", _blocked)

    def _postgres_runtime_should_not_be_called(*args, **kwargs):
        raise AssertionError(
            "postgres_runtime()이 호출됐다 — 운영 시간 차단이 DB 연결보다 "
            "먼저 일어나야 한다"
        )

    monkeypatch.setattr(script, "postgres_runtime", _postgres_runtime_should_not_be_called)

    exit_code = await script.main()

    assert exit_code == 1


@pytest.mark.asyncio
async def test_without_provider_flag_skips_market_hours_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--with-provider`` 없이 read-only 측정만 할 때는 운영 시간
    확인 자체를 하지 않는다(HTTP를 전혀 내지 않으므로 대상이 아님) —
    기존 read-only 동작 보존."""
    monkeypatch.setattr("sys.argv", ["ar_fdc_output_measurement.py"])

    called = False

    async def _spy(*, script_name: str) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(script, "assert_not_market_hours", _spy)

    class _FakeRuntime:
        async def __aenter__(self):
            raise RuntimeError("DB unavailable in test — expected to short-circuit before this")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(script, "postgres_runtime", lambda: _FakeRuntime())

    with pytest.raises(RuntimeError, match="DB unavailable"):
        await script.main()

    assert called is False
