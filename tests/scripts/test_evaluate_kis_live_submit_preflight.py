from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from scripts.evaluate_kis_live_submit_preflight import evaluate_live_submit_preflight


class _FakeOrderableCashResult:
    def __init__(self, amount: Decimal | None, source: str) -> None:
        self.amount = amount
        self.source = source


class _FakeClient:
    def __init__(
        self,
        *,
        orderable_amount: Decimal | None = Decimal("1000000"),
        orderable_source: str = "vttc8908r",
    ) -> None:
        self.budget_manager = SimpleNamespace(snapshot=lambda: {"global": {"remaining": 5}})
        self._orderable_amount = orderable_amount
        self._orderable_source = orderable_source

    async def authenticate(self) -> str:
        return "token"

    async def get_approval_key(self) -> str:
        return "approval"

    async def get_cash_and_positions(self, *, after_hours: bool = False):
        return SimpleNamespace(
            cash_balance={"dnca_tot_amt": "1234567"},
            positions=[{"pdno": "005930"}],
        )

    async def get_orderable_cash_result(self, **_: object):
        return _FakeOrderableCashResult(self._orderable_amount, self._orderable_source)


class _FakeAdapter:
    def __init__(self, client: _FakeClient) -> None:
        self._rest = client


@pytest.mark.asyncio
async def test_live_submit_preflight_blocked_when_kis_env_is_not_live(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        kis_env="paper",
        kis_api_key="key",
        kis_api_secret="secret",
        kis_account_number="12345678",
        kis_account_product_code="01",
    )
    monkeypatch.setattr(
        "scripts.evaluate_kis_live_submit_preflight.AppSettings",
        lambda: settings,
    )

    result = await evaluate_live_submit_preflight(symbol="005930", price="1")

    assert result.overall_status == "BLOCKED"
    assert result.message.startswith("KIS_ENV=live 가 아니므로")


@pytest.mark.asyncio
async def test_live_submit_preflight_ready_when_live_account_checks_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        kis_env="live",
        kis_api_key="key",
        kis_api_secret="secret",
        kis_account_number="12345678",
        kis_account_product_code="01",
    )
    monkeypatch.setattr(
        "scripts.evaluate_kis_live_submit_preflight.AppSettings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "scripts.evaluate_kis_live_submit_preflight._build_kis_adapter",
        lambda _settings: _FakeAdapter(_FakeClient()),
    )

    result = await evaluate_live_submit_preflight(symbol="005930", price="1")

    assert result.overall_status == "READY"
    assert result.auth_ok is True
    assert result.approval_ok is True
    assert result.cash_positions_ok is True
    assert result.orderable_cash_ok is True
    assert result.orderable_cash_source == "vttc8908r"
    assert result.orderable_cash_amount == "1000000"


@pytest.mark.asyncio
async def test_live_submit_preflight_warn_when_orderable_cash_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        kis_env="live",
        kis_api_key="key",
        kis_api_secret="secret",
        kis_account_number="12345678",
        kis_account_product_code="01",
    )
    monkeypatch.setattr(
        "scripts.evaluate_kis_live_submit_preflight.AppSettings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "scripts.evaluate_kis_live_submit_preflight._build_kis_adapter",
        lambda _settings: _FakeAdapter(
            _FakeClient(orderable_amount=None, orderable_source="missing_field"),
        ),
    )

    result = await evaluate_live_submit_preflight(symbol="005930", price="1")

    assert result.overall_status == "WARN"
    assert result.orderable_cash_ok is False
    assert result.orderable_cash_source == "missing_field"
