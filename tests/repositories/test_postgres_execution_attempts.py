"""PostgreSQL integration tests for ``ExecutionAttemptEntity`` CRUD.

Tests cover:

1. ``test_add_and_read`` — ``add()`` → ``get()`` round-trip with all fields
2. ``test_get_not_found`` — unknown UUID returns ``None``
3. ``test_update_status`` — ``update_status()`` modifies status + completed_at
4. ``test_list_by_trade_decision`` — multiple attempts filtered by TD
5. ``test_phase_trace_jsonb`` — JSONB ``phase_trace`` round-trip

Fixtures
--------
* ``seeded_postgres_data`` — full Postgres repos with client/account/instrument/strategy/ctx
* ``seeded_decision_context`` — the decision_context_id from the seeded data
* ``seeded_strategy_id`` — the strategy_id from the seeded data
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import ExecutionAttemptEntity
from agent_trading.repositories.container import RepositoryContainer


@pytest.fixture
async def seeded_decision_context(
    seeded_postgres_data: RepositoryContainer,
) -> UUID:
    """Return the decision_context_id already seeded by ``seeded_postgres_data``.

    Filters by ``correlation_id = 'test-correlation'`` to avoid picking up
    pre-existing rows left by application runs (e.g. ``paper-loop-*``).
    """
    conn = seeded_postgres_data.unit_of_work.connection
    row = await conn.fetchrow(
        "SELECT decision_context_id FROM trading.decision_contexts "
        "WHERE correlation_id = 'test-correlation' LIMIT 1"
    )
    assert row is not None, "seeded_postgres_data must seed a decision_context"
    return row["decision_context_id"]


@pytest.fixture
async def seeded_strategy_id(
    seeded_postgres_data: RepositoryContainer,
) -> UUID:
    """Return the strategy_id already seeded by ``seeded_postgres_data``."""
    conn = seeded_postgres_data.unit_of_work.connection
    row = await conn.fetchrow(
        "SELECT strategy_id FROM trading.strategies LIMIT 1"
    )
    assert row is not None, "seeded_postgres_data must seed a strategy"
    return row["strategy_id"]


@pytest.fixture
async def seeded_trade_decision(
    seeded_postgres_data: RepositoryContainer,
    seeded_decision_context: UUID,
    seeded_strategy_id: UUID,
) -> UUID:
    """Insert a minimal ``TradeDecisionEntity`` and return its ID."""
    from agent_trading.domain.entities import TradeDecisionEntity
    from agent_trading.domain.enums import DecisionType, EntryStyle, OrderSide

    repos = seeded_postgres_data
    td_id = uuid4()
    decision = TradeDecisionEntity(
        trade_decision_id=td_id,
        decision_context_id=seeded_decision_context,
        decision_type=DecisionType.APPROVE,
        side=OrderSide.BUY,
        strategy_id=seeded_strategy_id,
        symbol="AAPL",
        market="NASDAQ",
        entry_style=EntryStyle.LIMIT,
        created_at=datetime.now(timezone.utc),
    )
    await repos.trade_decisions.add(decision)
    return td_id


def _make_attempt(
    trade_decision_id: UUID,
    decision_context_id: UUID,
    *,
    execution_attempt_id: UUID | None = None,
    status: str = "running",
    stop_phase: str | None = None,
    stop_reason: str | None = None,
    phase_trace: list[dict[str, object]] | None = None,
) -> ExecutionAttemptEntity:
    """Helper: build a minimal ``ExecutionAttemptEntity`` for testing."""
    now = datetime.now(timezone.utc)
    return ExecutionAttemptEntity(
        execution_attempt_id=execution_attempt_id or uuid4(),
        trade_decision_id=trade_decision_id,
        decision_context_id=decision_context_id,
        status=status,
        stop_phase=stop_phase,
        stop_reason=stop_reason,
        phase_trace=phase_trace,
        started_at=now,
        completed_at=None,
        created_at=now,
    )


# ============================================================================
# Test 1: Full round-trip — add + read-back with all fields
# ============================================================================


@pytest.mark.asyncio
async def test_add_and_read(
    seeded_postgres_data: RepositoryContainer,
    seeded_decision_context: UUID,
    seeded_trade_decision: UUID,
) -> None:
    """``add()`` → ``get()`` round-trip: 모든 필드 보존 확인."""
    repos = seeded_postgres_data
    td_id = seeded_trade_decision

    phase_trace: list[dict[str, object]] = [
        {"phase": "ai_assemble", "elapsed_ms": 1200, "status": "ok"},
        {"phase": "sizing/AAPL", "elapsed_ms": 45, "status": "ok"},
        {"phase": "broker_submit/AAPL", "elapsed_ms": 3500, "status": "ok"},
    ]

    attempt = _make_attempt(
        trade_decision_id=td_id,
        decision_context_id=seeded_decision_context,
        status="submitted",
        stop_phase="broker_submit",
        stop_reason="order_submitted",
        phase_trace=phase_trace,
    )

    saved = await repos.execution_attempts.add(attempt)
    assert saved.execution_attempt_id == attempt.execution_attempt_id
    assert saved.trade_decision_id == td_id
    assert saved.decision_context_id == seeded_decision_context
    assert saved.status == "submitted"
    assert saved.stop_phase == "broker_submit"
    assert saved.stop_reason == "order_submitted"
    assert saved.phase_trace == phase_trace
    assert saved.started_at is not None
    assert saved.created_at is not None

    # Read back via get()
    fetched = await repos.execution_attempts.get(attempt.execution_attempt_id)
    assert fetched is not None
    assert fetched.execution_attempt_id == attempt.execution_attempt_id
    assert fetched.trade_decision_id == td_id
    assert fetched.decision_context_id == seeded_decision_context
    assert fetched.status == "submitted"
    assert fetched.stop_phase == "broker_submit"
    assert fetched.stop_reason == "order_submitted"
    assert fetched.phase_trace == phase_trace


# ============================================================================
# Test 2: get() returns None for unknown UUID
# ============================================================================


@pytest.mark.asyncio
async def test_get_not_found(
    seeded_postgres_data: RepositoryContainer,
) -> None:
    """존재하지 않는 UUID로 ``get()`` → ``None`` 반환."""
    repos = seeded_postgres_data
    result = await repos.execution_attempts.get(uuid4())
    assert result is None


# ============================================================================
# Test 3: update_status() — 상태 변경 + completed_at 설정
# ============================================================================


@pytest.mark.asyncio
async def test_update_status(
    seeded_postgres_data: RepositoryContainer,
    seeded_decision_context: UUID,
    seeded_trade_decision: UUID,
) -> None:
    """``update_status()``로 상태 변경 + ``completed_at`` 설정 → ``get()`` 확인."""
    repos = seeded_postgres_data
    td_id = seeded_trade_decision

    attempt = _make_attempt(
        trade_decision_id=td_id,
        decision_context_id=seeded_decision_context,
        status="running",
    )
    saved = await repos.execution_attempts.add(attempt)

    # 상태 변경: running → submitted
    completed_at = datetime.now(timezone.utc)
    await repos.execution_attempts.update_status(
        saved.execution_attempt_id,
        "submitted",
        stop_phase="broker_submit",
        stop_reason="order_submitted",
        completed_at=completed_at,
    )

    fetched = await repos.execution_attempts.get(saved.execution_attempt_id)
    assert fetched is not None
    assert fetched.status == "submitted"
    assert fetched.stop_phase == "broker_submit"
    assert fetched.stop_reason == "order_submitted"
    assert fetched.completed_at is not None
    # completed_at가 설정된 시간과 근사값인지 확인
    assert abs((fetched.completed_at - completed_at).total_seconds()) < 5


# ============================================================================
# Test 4: list_by_trade_decision() — 동일 TD로 2개 attempt 추가
# ============================================================================


@pytest.mark.asyncio
async def test_list_by_trade_decision(
    seeded_postgres_data: RepositoryContainer,
    seeded_decision_context: UUID,
    seeded_trade_decision: UUID,
) -> None:
    """동일 ``trade_decision_id``로 2개 attempt 추가 → 2개 반환 확인."""
    repos = seeded_postgres_data
    td_id = seeded_trade_decision

    attempt1 = _make_attempt(
        trade_decision_id=td_id,
        decision_context_id=seeded_decision_context,
        status="running",
    )
    attempt2 = _make_attempt(
        trade_decision_id=td_id,
        decision_context_id=seeded_decision_context,
        status="failed",
    )

    await repos.execution_attempts.add(attempt1)
    await repos.execution_attempts.add(attempt2)

    results = await repos.execution_attempts.list_by_trade_decision(td_id)
    assert len(results) == 2

    # started_at DESC 정렬 확인
    assert results[0].started_at >= results[1].started_at

    attempt_ids = {r.execution_attempt_id for r in results}
    assert attempt_ids == {attempt1.execution_attempt_id, attempt2.execution_attempt_id}


# ============================================================================
# Test 5: phase_trace JSONB round-trip
# ============================================================================


@pytest.mark.asyncio
async def test_phase_trace_jsonb(
    seeded_postgres_data: RepositoryContainer,
    seeded_decision_context: UUID,
    seeded_trade_decision: UUID,
) -> None:
    """``phase_trace`` 포함 add → ``get()``으로 JSONB 필드 정상 조회."""
    repos = seeded_postgres_data
    td_id = seeded_trade_decision

    phase_trace: list[dict[str, object]] = [
        {"phase": "ai_assemble", "elapsed_ms": 500, "status": "ok"},
        {"phase": "quote_resolution/AAPL", "elapsed_ms": 200, "status": "ok"},
        {"phase": "sizing/AAPL", "elapsed_ms": 30, "status": "skipped"},
    ]

    attempt = _make_attempt(
        trade_decision_id=td_id,
        decision_context_id=seeded_decision_context,
        status="stopped",
        stop_phase="sizing",
        stop_reason="sizing_rejected",
        phase_trace=phase_trace,
    )

    saved = await repos.execution_attempts.add(attempt)
    fetched = await repos.execution_attempts.get(saved.execution_attempt_id)

    assert fetched is not None
    assert fetched.phase_trace == phase_trace
    assert fetched.phase_trace is not None
    assert len(fetched.phase_trace) == 3
    assert fetched.phase_trace[0]["phase"] == "ai_assemble"
    assert fetched.phase_trace[0]["elapsed_ms"] == 500
    assert fetched.phase_trace[1]["status"] == "ok"
    assert fetched.phase_trace[2]["status"] == "skipped"
