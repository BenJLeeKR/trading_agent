from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from scripts.evaluate_kis_live_combined_submit_smoke import (
    evaluate_live_combined_submit_smoke,
)


class _FakeSubmitResult:
    def __init__(self, broker_order_id: str = "1234567890") -> None:
        self.broker_order_id = broker_order_id


class _FakeAdapter:
    def __init__(self, *, validation_errors: list[str] | None = None) -> None:
        self._validation_errors = validation_errors or []
        self.submitted_requests = []

    def _validate_order_request(self, request):  # noqa: ANN001, SLF001
        return list(self._validation_errors)

    async def submit_order(self, request):  # noqa: ANN001
        self.submitted_requests.append(request)
        return _FakeSubmitResult()


@pytest.mark.asyncio
async def test_combined_smoke_ready_in_dry_run_when_preflight_is_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_preflight(**kwargs):
        return SimpleNamespace(overall_status="READY")

    monkeypatch.setattr(
        "scripts.evaluate_kis_live_combined_submit_smoke.AppSettings",
        lambda: SimpleNamespace(kis_env="live"),
    )
    monkeypatch.setattr(
        "scripts.evaluate_kis_live_combined_submit_smoke.evaluate_live_submit_preflight",
        _fake_preflight,
    )
    monkeypatch.setattr(
        "scripts.evaluate_kis_live_combined_submit_smoke._build_kis_adapter",
        lambda settings: _FakeAdapter(),
    )

    result = await evaluate_live_combined_submit_smoke(
        symbol="005930",
        quantity=Decimal("1"),
        price=Decimal("1"),
        execute_live_order=False,
        confirmation_phrase="",
    )

    assert result.overall_status == "READY"
    assert result.submitted is False
    assert result.request_validation_ok is True


@pytest.mark.asyncio
async def test_combined_smoke_blocked_when_confirmation_phrase_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_preflight(**kwargs):
        return SimpleNamespace(overall_status="READY")

    monkeypatch.setattr(
        "scripts.evaluate_kis_live_combined_submit_smoke.AppSettings",
        lambda: SimpleNamespace(kis_env="live"),
    )
    monkeypatch.setattr(
        "scripts.evaluate_kis_live_combined_submit_smoke.evaluate_live_submit_preflight",
        _fake_preflight,
    )
    monkeypatch.setattr(
        "scripts.evaluate_kis_live_combined_submit_smoke._build_kis_adapter",
        lambda settings: _FakeAdapter(),
    )

    result = await evaluate_live_combined_submit_smoke(
        symbol="005930",
        quantity=Decimal("1"),
        price=Decimal("1"),
        execute_live_order=True,
        confirmation_phrase="WRONG",
    )

    assert result.overall_status == "BLOCKED"
    assert result.submitted is False
    assert result.execution_enabled is False


@pytest.mark.asyncio
async def test_combined_smoke_executes_only_with_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _FakeAdapter()
    async def _fake_preflight(**kwargs):
        return SimpleNamespace(overall_status="READY")

    monkeypatch.setattr(
        "scripts.evaluate_kis_live_combined_submit_smoke.AppSettings",
        lambda: SimpleNamespace(kis_env="live"),
    )
    monkeypatch.setattr(
        "scripts.evaluate_kis_live_combined_submit_smoke.evaluate_live_submit_preflight",
        _fake_preflight,
    )
    monkeypatch.setattr(
        "scripts.evaluate_kis_live_combined_submit_smoke._build_kis_adapter",
        lambda settings: adapter,
    )

    result = await evaluate_live_combined_submit_smoke(
        symbol="005930",
        quantity=Decimal("1"),
        price=Decimal("1"),
        execute_live_order=True,
        confirmation_phrase="SUBMIT_REAL_ORDER",
    )

    assert result.overall_status == "EXECUTED"
    assert result.submitted is True
    assert result.execution_enabled is True
    assert result.broker_order_id == "1234567890"
    assert len(adapter.submitted_requests) == 1
