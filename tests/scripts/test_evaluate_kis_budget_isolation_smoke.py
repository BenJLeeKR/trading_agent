from __future__ import annotations

from unittest.mock import patch

from agent_trading.brokers.rate_limit import BudgetExhaustedError
from scripts.evaluate_kis_budget_isolation_smoke import evaluate_budget_isolation_smoke


class _FakeBudgetManager:
    def __init__(self, remaining: int, bucket_class_name: str, file_path: str | None = None) -> None:
        self._remaining = remaining
        self.session_id = "session-1"
        if bucket_class_name == "FileBackedGlobalBucket":
            self.global_rest = type(
                "FileBackedGlobalBucket",
                (),
                {"remaining": remaining, "capacity": 1, "refill_rate": 1.0, "_FILE_PATH": file_path or "/tmp/paper"},
            )()
        else:
            self.global_rest = type(
                "OperationBucket",
                (),
                {"remaining": remaining, "capacity": 18, "refill_rate": 18.0},
            )()

    def snapshot(self) -> dict[str, object]:
        return {
            "global": {
                "remaining": self.global_rest.remaining,
                "capacity": self.global_rest.capacity,
                "refill_rate": self.global_rest.refill_rate,
            }
        }


class _FakePaperClient:
    def __init__(self, rows: list[dict[str, object]] | Exception) -> None:
        self.budget_manager = _FakeBudgetManager(
            remaining=1,
            bucket_class_name="FileBackedGlobalBucket",
            file_path="/tmp/shared-paper-budget",
        )
        self._rows = rows
        self.env = "paper"

    async def _wait_for_inquiry_budget(self, timeout: float) -> None:
        return None

    async def inquire_daily_ccld(self, **_: object) -> list[dict[str, object]]:
        if isinstance(self._rows, Exception):
            raise self._rows
        return self._rows


class _FakeLiveClient:
    def __init__(self) -> None:
        self.budget_manager = _FakeBudgetManager(
            remaining=18,
            bucket_class_name="OperationBucket",
        )
        self.env = "live"

    async def authenticate(self) -> str:
        return "token"

    async def get_approval_key(self) -> str:
        return "approval"

    async def get_quote(self, symbol: str) -> dict[str, object]:
        return {"symbol": symbol, "stck_prpr": "70000"}


class _FakeAdapter:
    def __init__(self, rest_client: _FakePaperClient) -> None:
        self._rest = rest_client


class TestEvaluateKisBudgetIsolationSmoke:
    async def test_ready_when_live_and_paper_are_isolated(self) -> None:
        paper_client = _FakePaperClient(rows=[{"ODNO": "1"}])
        live_client = _FakeLiveClient()
        with (
            patch(
                "scripts.evaluate_kis_budget_isolation_smoke._build_kis_adapter",
                return_value=_FakeAdapter(paper_client),
            ),
            patch(
                "scripts.evaluate_kis_budget_isolation_smoke._build_kis_live_quote_client",
                return_value=live_client,
            ),
        ):
            result = await evaluate_budget_isolation_smoke("005930")

        assert result.overall_status == "READY"
        assert result.live_quote_ok is True
        assert result.paper_truth_query_ok is True
        assert result.isolation_ok is True
        assert result.paper_shared_global_budget is True
        assert result.live_shared_global_budget is False
        assert result.paper_only_policy_isolated is True
        assert result.paper_rows_count == 1

    async def test_warn_on_paper_budget_exhaustion(self) -> None:
        paper_client = _FakePaperClient(rows=BudgetExhaustedError("inquiry", "exhausted"))
        live_client = _FakeLiveClient()
        with (
            patch(
                "scripts.evaluate_kis_budget_isolation_smoke._build_kis_adapter",
                return_value=_FakeAdapter(paper_client),
            ),
            patch(
                "scripts.evaluate_kis_budget_isolation_smoke._build_kis_live_quote_client",
                return_value=live_client,
            ),
        ):
            result = await evaluate_budget_isolation_smoke("005930")

        assert result.overall_status == "WARN"
        assert result.live_quote_ok is True
        assert result.paper_truth_query_ok is False
        assert "budget exhaustion" in result.message

    async def test_blocked_when_live_client_missing(self) -> None:
        paper_client = _FakePaperClient(rows=[])
        with (
            patch(
                "scripts.evaluate_kis_budget_isolation_smoke._build_kis_adapter",
                return_value=_FakeAdapter(paper_client),
            ),
            patch(
                "scripts.evaluate_kis_budget_isolation_smoke._build_kis_live_quote_client",
                return_value=None,
            ),
        ):
            result = await evaluate_budget_isolation_smoke("005930")

        assert result.overall_status == "BLOCKED"
        assert result.live_quote_client_built is False
