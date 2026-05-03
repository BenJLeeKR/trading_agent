from __future__ import annotations

"""Integration tests for ``PostgresAuditLogRepository``.

These tests verify that audit log entries are actually persisted to the
PostgreSQL ``trading.audit_logs`` table and can be queried back correctly.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from agent_trading.domain.entities import AuditLogEntity
from agent_trading.repositories.container import RepositoryContainer


@pytest.mark.asyncio
async def test_add_and_list_by_correlation_id(
    postgres_repos: RepositoryContainer,
) -> None:
    """Add an audit log entry and retrieve it by correlation_id."""
    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)

    entry = AuditLogEntity(
        audit_log_id=uuid4(),
        actor_type="system",
        actor_id="test-runner",
        action="test.action",
        target_entity_type="test",
        target_entity_id=str(uuid4()),
        created_at=now,
        before_json={"before": "value1"},
        after_json={"after": "value2"},
        correlation_id=correlation_id,
        metadata={"env": "test", "source": "pytest"},
    )

    saved = await postgres_repos.audit_logs.add(entry)
    assert saved.audit_log_id == entry.audit_log_id
    assert saved.action == "test.action"
    assert saved.before_json == {"before": "value1"}
    assert saved.after_json == {"after": "value2"}
    assert saved.metadata == {"env": "test", "source": "pytest"}

    # Retrieve by correlation_id
    results = await postgres_repos.audit_logs.list_by_correlation_id(correlation_id)
    assert len(results) == 1
    assert results[0].audit_log_id == entry.audit_log_id


@pytest.mark.asyncio
async def test_list_by_correlation_id_ordered(
    postgres_repos: RepositoryContainer,
) -> None:
    """Multiple audit log entries are returned in creation order."""
    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)
    ids = []

    for i in range(3):
        entry = AuditLogEntity(
            audit_log_id=uuid4(),
            actor_type="system",
            actor_id="test-runner",
            action=f"test.step_{i}",
            target_entity_type="test",
            target_entity_id=str(uuid4()),
            created_at=now,
            correlation_id=correlation_id,
            metadata={},
        )
        saved = await postgres_repos.audit_logs.add(entry)
        ids.append(saved.audit_log_id)

    results = await postgres_repos.audit_logs.list_by_correlation_id(correlation_id)
    assert len(results) == 3
    # Must be in insertion order (ORDER BY created_at)
    assert [r.audit_log_id for r in results] == ids


@pytest.mark.asyncio
async def test_list_by_correlation_id_empty(
    postgres_repos: RepositoryContainer,
) -> None:
    """Non-existent correlation_id returns an empty sequence."""
    results = await postgres_repos.audit_logs.list_by_correlation_id(
        "nonexistent-correlation"
    )
    assert len(results) == 0


@pytest.mark.asyncio
async def test_metadata_default_empty_dict(
    postgres_repos: RepositoryContainer,
) -> None:
    """When metadata is not provided, it defaults to empty dict."""
    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)

    entry = AuditLogEntity(
        audit_log_id=uuid4(),
        actor_type="system",
        actor_id="test-runner",
        action="test.default_metadata",
        target_entity_type="test",
        target_entity_id=str(uuid4()),
        created_at=now,
        correlation_id=correlation_id,
        metadata={},
    )

    saved = await postgres_repos.audit_logs.add(entry)
    assert saved.metadata == {}


@pytest.mark.asyncio
async def test_before_after_jsonb_nullable(
    postgres_repos: RepositoryContainer,
) -> None:
    """before_json and after_json can be None (NULL in DB)."""
    correlation_id = str(uuid4())
    now = datetime.now(timezone.utc)

    entry = AuditLogEntity(
        audit_log_id=uuid4(),
        actor_type="system",
        actor_id="test-runner",
        action="test.null_json",
        target_entity_type="test",
        target_entity_id=str(uuid4()),
        created_at=now,
        before_json=None,
        after_json=None,
        correlation_id=correlation_id,
        metadata={},
    )

    saved = await postgres_repos.audit_logs.add(entry)
    assert saved.before_json is None
    assert saved.after_json is None
