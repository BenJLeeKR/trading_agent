from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from scripts.evaluate_kis_live_readonly_smoke import evaluate_live_readonly_smoke


async def test_live_readonly_smoke_blocked_without_credentials(monkeypatch) -> None:
    monkeypatch.delenv("KIS_LIVE_INFO_APP_KEY", raising=False)
    monkeypatch.delenv("KIS_LIVE_INFO_APP_SECRET", raising=False)

    result = await evaluate_live_readonly_smoke("005930")

    assert result.overall_status == "BLOCKED"
    assert result.live_info_credentials_present is False


async def test_live_readonly_smoke_ready_with_mocked_client(monkeypatch) -> None:
    monkeypatch.setenv("KIS_LIVE_INFO_APP_KEY", "live-key")
    monkeypatch.setenv("KIS_LIVE_INFO_APP_SECRET", "live-secret")

    client = SimpleNamespace(
        authenticate=AsyncMock(return_value="token"),
        get_approval_key=AsyncMock(return_value="approval-key-123"),
        get_quote=AsyncMock(return_value={"stck_prpr": "72100"}),
        budget_manager=SimpleNamespace(snapshot=lambda: {"global_rest": {"capacity": 18}}),
    )

    with patch(
        "scripts.evaluate_kis_live_readonly_smoke._build_kis_live_quote_client",
        return_value=client,
    ):
        result = await evaluate_live_readonly_smoke("005930")

    assert result.overall_status == "READY"
    assert result.auth_ok is True
    assert result.approval_ok is True
    assert result.quote_ok is True
    assert result.quote_last_price == "72100"
