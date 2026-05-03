from __future__ import annotations

from typing import Protocol


class Repository(Protocol):
    """Marker protocol for repository types."""


class UnitOfWork(Protocol):
    """Minimal transaction boundary for repository-backed services."""

    async def commit(self) -> None:
        """Persist the current transactional work."""

    async def rollback(self) -> None:
        """Rollback the current transactional work."""

