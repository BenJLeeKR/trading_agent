from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent_trading.repositories.postgres.order_submission_attempts import (
    PostgresOrderSubmissionAttemptRepository,
)


@pytest.mark.asyncio
async def test_list_recent_failures_joins_instruments_for_symbol() -> None:
    connection = SimpleNamespace(fetch=AsyncMock(return_value=[]))
    tx = SimpleNamespace(connection=connection)
    repo = PostgresOrderSubmissionAttemptRepository(tx)

    await repo.list_recent_failures(limit=5)

    connection.fetch.assert_awaited_once()
    sql, limit = connection.fetch.await_args.args
    assert "JOIN trading.order_requests o" in sql
    assert "LEFT JOIN trading.instruments i ON i.instrument_id = o.instrument_id" in sql
    assert "i.symbol" in sql
    assert "o.symbol" not in sql
    assert limit == 5
