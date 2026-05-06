"""PostgreSQL-backed ``AgentRunRepository`` integration tests.

Verifies:
* ``add()`` persists an agent run and returns it with server defaults.
* ``list_by_decision_context()`` returns runs ordered by ``started_at DESC``.
* ``list_all()`` returns recent runs ordered by ``started_at DESC``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import AgentRunEntity, DecisionContextEntity
from agent_trading.repositories.container import RepositoryContainer


@pytest.fixture
async def seeded_decision_context(
    seeded_postgres_data: RepositoryContainer,
) -> UUID:
    """Return the decision_context_id already seeded by ``seeded_postgres_data``."""
    conn = seeded_postgres_data.unit_of_work.connection
    row = await conn.fetchrow(
        "SELECT decision_context_id FROM trading.decision_contexts LIMIT 1"
    )
    assert row is not None, "seeded_postgres_data must seed a decision_context"
    return row["decision_context_id"]


def _make_run(
    decision_context_id: UUID,
    agent_type: str = "event_interpretation",
    *,
    started_at: datetime | None = None,
) -> AgentRunEntity:
    """Helper: build a minimal ``AgentRunEntity`` for testing."""
    now = started_at or datetime.now(timezone.utc)
    return AgentRunEntity(
        agent_run_id=uuid4(),
        decision_context_id=decision_context_id,
        agent_type=agent_type,
        started_at=now,
        status="completed",
        completed_at=now,
        created_at=now,
    )


@pytest.mark.asyncio
async def test_add_and_list_all(
    seeded_postgres_data: RepositoryContainer,
    seeded_decision_context: UUID,
) -> None:
    """``add()`` persists a run; ``list_all()`` returns it."""
    repos = seeded_postgres_data
    run = _make_run(seeded_decision_context)

    added = await repos.agent_runs.add(run)
    assert added.agent_run_id == run.agent_run_id
    assert added.agent_type == "event_interpretation"
    assert added.status == "completed"

    runs = await repos.agent_runs.list_all()
    assert len(runs) >= 1
    assert any(r.agent_run_id == run.agent_run_id for r in runs)


@pytest.mark.asyncio
async def test_list_by_decision_context(
    seeded_postgres_data: RepositoryContainer,
    seeded_decision_context: UUID,
) -> None:
    """``list_by_decision_context()`` returns only matching runs."""
    repos = seeded_postgres_data

    # Add 2 runs for this context
    run1 = _make_run(seeded_decision_context, "event_interpretation")
    run2 = _make_run(seeded_decision_context, "ai_risk")
    await repos.agent_runs.add(run1)
    await repos.agent_runs.add(run2)

    # Add a run for a different context (should not appear)
    other_ctx_id = uuid4()
    # Satisfy FK: copy fields from the existing seeded decision_context
    conn = repos.unit_of_work.connection
    src = await conn.fetchrow(
        "SELECT account_id, strategy_id, config_version_id, market_timestamp, "
        "correlation_id FROM trading.decision_contexts WHERE decision_context_id = $1",
        seeded_decision_context,
    )
    assert src is not None
    other_ctx = DecisionContextEntity(
        decision_context_id=other_ctx_id,
        account_id=src["account_id"],
        strategy_id=src["strategy_id"],
        config_version_id=src["config_version_id"],
        market_timestamp=src["market_timestamp"],
        correlation_id=f"OTHER_{other_ctx_id.hex[:8]}",
    )
    await repos.decision_contexts.add(other_ctx)
    run3 = _make_run(other_ctx_id, "final_decision_composer")
    await repos.agent_runs.add(run3)

    runs = await repos.agent_runs.list_by_decision_context(seeded_decision_context)
    assert len(runs) == 2
    assert all(r.decision_context_id == seeded_decision_context for r in runs)
    agent_types = {r.agent_type for r in runs}
    assert agent_types == {"event_interpretation", "ai_risk"}


@pytest.mark.asyncio
async def test_list_all_ordering(
    seeded_postgres_data: RepositoryContainer,
    seeded_decision_context: UUID,
) -> None:
    """``list_all()`` returns runs ordered by ``started_at DESC``."""
    repos = seeded_postgres_data

    now = datetime.now(timezone.utc)
    run_old = _make_run(seeded_decision_context, "event_interpretation", started_at=now)
    run_new = _make_run(
        seeded_decision_context,
        "ai_risk",
        started_at=datetime.now(timezone.utc),
    )
    await repos.agent_runs.add(run_old)
    await repos.agent_runs.add(run_new)

    runs = await repos.agent_runs.list_all()
    # The most recent run should be first
    assert runs[0].started_at >= runs[-1].started_at


@pytest.mark.asyncio
async def test_list_all_limit(
    seeded_postgres_data: RepositoryContainer,
    seeded_decision_context: UUID,
) -> None:
    """``list_all(limit=1)`` returns at most 1 run."""
    repos = seeded_postgres_data

    for i in range(3):
        run = _make_run(seeded_decision_context, f"agent_{i}")
        await repos.agent_runs.add(run)

    runs = await repos.agent_runs.list_all(limit=1)
    assert len(runs) == 1


@pytest.mark.asyncio
async def test_list_by_decision_context_empty(
    seeded_postgres_data: RepositoryContainer,
) -> None:
    """``list_by_decision_context()`` returns empty list for unknown context."""
    repos = seeded_postgres_data
    runs = await repos.agent_runs.list_by_decision_context(uuid4())
    assert runs == []
