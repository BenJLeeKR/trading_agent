"""DB-free tests for ``PostgresTradeDecisionRepository`` (Stage A-2,
2026-08-20).

Kept in a separate file from ``test_postgres_trade_decisions.py`` on
purpose: that file uses the ``seeded_postgres_data`` fixture (a real
Postgres connection) and does not import
``agent_trading.repositories.postgres.trade_decisions`` directly, so the
harness's import-graph test discovery does not select it as a candidate
for ``accept backend-file``. This file imports the concrete Postgres
repository class directly and uses a fake ``connection``
(``SimpleNamespace``) to capture the SQL/params actually passed to
``fetchrow()`` — no live DB needed, so it is a "safe" import-graph
candidate that runs directly under ``accept backend-file``.

Covers the ``policy_git_sha`` column added in migration 0065.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from agent_trading.domain.entities import TradeDecisionEntity
from agent_trading.domain.enums import DecisionType, EntryStyle, OrderSide
from agent_trading.repositories.postgres.trade_decisions import (
    PostgresTradeDecisionRepository,
)


def _make_entity(**overrides: object) -> TradeDecisionEntity:
    defaults: dict[str, object] = dict(
        trade_decision_id=uuid4(),
        decision_context_id=uuid4(),
        decision_type=DecisionType.APPROVE,
        side=OrderSide.BUY,
        strategy_id=uuid4(),
        symbol="005930",
        market="KRX",
        entry_style=EntryStyle.LIMIT,
        created_at=datetime.now(timezone.utc),
        entry_price=Decimal("70000"),
        quantity=Decimal("1"),
        policy_git_sha=None,
    )
    defaults.update(overrides)
    return TradeDecisionEntity(**defaults)  # type: ignore[arg-type]


def _fake_row(entity: TradeDecisionEntity) -> dict[str, object]:
    """Minimal fake ``asyncpg``-like row for ``row_to_entity()`` to parse —
    must cover every field ``TradeDecisionEntity`` requires without a
    default (the P0 required set)."""
    return {
        "trade_decision_id": entity.trade_decision_id,
        "decision_context_id": entity.decision_context_id,
        "decision_type": entity.decision_type,
        "side": entity.side,
        "strategy_id": entity.strategy_id,
        "symbol": entity.symbol,
        "market": entity.market,
        "entry_style": entity.entry_style,
        "created_at": entity.created_at,
        "policy_git_sha": entity.policy_git_sha,
    }


@pytest.mark.asyncio
async def test_add_includes_policy_git_sha_in_insert_params() -> None:
    """``policy_git_sha``가 INSERT의 SQL 컬럼 목록과 마지막 파라미터로
    함께 전달되는지 검증한다."""
    entity = _make_entity(policy_git_sha="abc123def456")
    connection = SimpleNamespace(
        fetchrow=AsyncMock(return_value=_fake_row(entity))
    )
    tx = SimpleNamespace(connection=connection)
    repo = PostgresTradeDecisionRepository(tx)

    result = await repo.add(entity)

    connection.fetchrow.assert_awaited_once()
    sql, *params = connection.fetchrow.await_args.args
    assert "policy_git_sha" in sql
    assert len(params) == 42
    assert params[-1] == "abc123def456"
    assert result.policy_git_sha == "abc123def456"


@pytest.mark.asyncio
async def test_add_allows_policy_git_sha_none() -> None:
    """``policy_git_sha``가 없어도(None) 기존 계약을 깨지 않고 그대로
    NULL로 전달돼야 한다(하위 호환)."""
    entity = _make_entity(policy_git_sha=None)
    connection = SimpleNamespace(
        fetchrow=AsyncMock(return_value=_fake_row(entity))
    )
    tx = SimpleNamespace(connection=connection)
    repo = PostgresTradeDecisionRepository(tx)

    result = await repo.add(entity)

    connection.fetchrow.assert_awaited_once()
    _, *params = connection.fetchrow.await_args.args
    assert params[-1] is None
    assert result.policy_git_sha is None


@pytest.mark.asyncio
async def test_add_preserves_required_p0_fields_in_insert_params() -> None:
    """기존 필수(P0) 필드 계약(decision_type/side/symbol/market/entry_
    style 등)이 ``policy_git_sha`` 추가로 흔들리지 않았는지 검증한다."""
    entity = _make_entity(
        symbol="000660",
        market="KRX",
        decision_type=DecisionType.REDUCE,
        side=OrderSide.SELL,
    )
    connection = SimpleNamespace(
        fetchrow=AsyncMock(return_value=_fake_row(entity))
    )
    tx = SimpleNamespace(connection=connection)
    repo = PostgresTradeDecisionRepository(tx)

    result = await repo.add(entity)

    connection.fetchrow.assert_awaited_once()
    _, *params = connection.fetchrow.await_args.args
    # P0 순서: trade_decision_id, decision_context_id, decision_type, side, ...
    assert params[0] == entity.trade_decision_id
    assert params[1] == entity.decision_context_id
    assert params[2] == "reduce"
    assert params[3] == "sell"
    assert params[5] == "000660"
    assert params[6] == "KRX"
    assert result.symbol == "000660"
    assert result.decision_type == DecisionType.REDUCE
