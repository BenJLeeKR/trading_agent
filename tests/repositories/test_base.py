from __future__ import annotations

import inspect
from typing import Protocol

from agent_trading.repositories.base import Repository, UnitOfWork


class TestRepositoryBaseContracts:
    def test_repository_is_marker_protocol(self) -> None:
        assert issubclass(Repository, Protocol)
        assert Repository.__annotations__ == {}

    def test_unit_of_work_declares_transaction_boundary(self) -> None:
        assert issubclass(UnitOfWork, Protocol)
        assert inspect.iscoroutinefunction(UnitOfWork.commit)
        assert inspect.iscoroutinefunction(UnitOfWork.rollback)
        assert UnitOfWork.commit.__annotations__["return"] == "None"
        assert UnitOfWork.rollback.__annotations__["return"] == "None"
