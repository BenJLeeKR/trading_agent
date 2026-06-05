from __future__ import annotations

import json
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from scripts.operations_day_run_evaluation_store import (
    build_evaluation_entry,
    persist_operations_day_evaluation,
)


def test_build_evaluation_entry_indexes_warn_and_blocked_codes() -> None:
    payload = build_evaluation_entry(
        overall_status="WARN",
        generated_at=datetime(2026, 6, 4, tzinfo=timezone.utc),
        checks=(
            SimpleNamespace(code="CHK_READY", status="READY"),
            SimpleNamespace(code="CHK_WARN", status="WARN"),
            SimpleNamespace(code="CHK_BLOCKED", status="BLOCKED"),
        ),
        extra={"sample": 1},
    )

    assert payload["overall_status"] == "WARN"
    assert payload["check_counts"] == {"ready": 1, "warn": 1, "blocked": 1}
    assert payload["warn_codes"] == ["CHK_WARN"]
    assert payload["blocked_codes"] == ["CHK_BLOCKED"]
    assert payload["sample"] == 1


@pytest.mark.asyncio
async def test_persist_operations_day_evaluation_merges_existing_summary_json() -> None:
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"summary_json": {"existing": {"value": 1}}})
    conn.execute = AsyncMock()

    with patch("asyncpg.connect", new=AsyncMock(return_value=conn)):
        await persist_operations_day_evaluation(
            dsn="postgresql://localhost/test",
            run_date=date(2026, 6, 4),
            key="intraday_validation",
            payload={"overall_status": "READY"},
            is_trading_day=True,
        )

    update_sql = conn.execute.call_args.args[0]
    assert "UPDATE trading.operations_day_runs" in update_sql
    merged = json.loads(conn.execute.call_args.args[2])
    assert merged["existing"] == {"value": 1}
    assert merged["intraday_validation"]["overall_status"] == "READY"
