"""Audit log inspection endpoint: ``GET /audit-logs``.

Results are sorted by ``created_at`` descending (newest first).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import AuditLogEntry
from agent_trading.repositories.container import RepositoryContainer

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("", response_model=list[AuditLogEntry])
async def list_audit_logs(
    correlation_id: str = Query(..., description="Filter by correlation_id (required)"),
    repos: RepositoryContainer = Depends(get_repos),
) -> list[AuditLogEntry]:
    """List audit log entries filtered by ``correlation_id``.

    ``correlation_id`` is **required** to prevent unbounded scans.
    Results are sorted by ``created_at`` ascending (oldest first).
    """
    entries = await repos.audit_logs.list_by_correlation_id(correlation_id)
    return [
        AuditLogEntry(
            audit_log_id=str(e.audit_log_id),
            actor_type=e.actor_type,
            actor_id=e.actor_id,
            action=e.action,
            target_entity_type=e.target_entity_type,
            target_entity_id=e.target_entity_id,
            created_at=e.created_at,
            correlation_id=e.correlation_id,
            before_json=e.before_json,
            after_json=e.after_json,
        )
        for e in entries
    ]
