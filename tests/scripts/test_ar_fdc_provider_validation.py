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

    exit_code = await script.main()

    assert exit_code == 1


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
