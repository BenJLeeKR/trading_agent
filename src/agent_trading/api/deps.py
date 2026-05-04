"""FastAPI dependency injection — provides ``RepositoryContainer`` to routes."""

from __future__ import annotations

from fastapi import Request

from agent_trading.repositories.container import RepositoryContainer


def get_repos(request: Request) -> RepositoryContainer:
    """``Depends`` callable that extracts the ``RepositoryContainer`` from app state.

    Usage::

        @router.get("/orders")
        async def list_orders(
            repos: RepositoryContainer = Depends(get_repos),
        ):
            ...
    """
    return request.app.state.repos
