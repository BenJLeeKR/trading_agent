"""Tests for ``GET /snapshot-sync-runs`` inspection endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from agent_trading.api.app import create_app
from agent_trading.domain.entities import SnapshotSyncRunEntity
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer


# ── Helpers ────────────────────────────────────────────────────────────────


def _make_run(
    started_at: datetime | None = None,
    trigger_type: str = "manual",
    scope: str = "all",
    status: str = "completed",
    dry_run: bool = False,
) -> SnapshotSyncRunEntity:
    """Build a ``SnapshotSyncRunEntity`` with sensible defaults for testing."""
    return SnapshotSyncRunEntity(
        snapshot_sync_run_id=uuid4(),
        trigger_type=trigger_type,
        scope=scope,
        dry_run=dry_run,
        total_accounts=5,
        succeeded_accounts=5,
        partial_accounts=0,
        failed_accounts=0,
        skipped_accounts=0,
        positions_synced_total=42,
        positions_skipped_total=0,
        cash_synced_count=5,
        error_count=0,
        status=status,
        started_at=started_at or datetime.now(timezone.utc),
        env_filter=None,
        status_filter=None,
        summary_json=None,
        completed_at=datetime.now(timezone.utc),
    )


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def empty_client() -> TestClient:
    """FastAPI ``TestClient`` with empty in-memory repos (no auth)."""
    app = create_app(auth_enabled=False)
    with TestClient(app) as tc:
        yield tc


@pytest.fixture
async def repos_with_data() -> RepositoryContainer:
    """In-memory repos pre-seeded with three snapshot sync runs."""
    repos = build_in_memory_repositories()
    now = datetime.now(timezone.utc)

    runs = [
        _make_run(
            started_at=now - timedelta(hours=2),
            trigger_type="scheduler",
            status="completed",
        ),
        _make_run(
            started_at=now - timedelta(hours=1),
            trigger_type="manual",
            status="partial",
            scope="batch",
        ),
        _make_run(
            started_at=now,
            trigger_type="manual",
            status="failed",
            scope="single",
        ),
    ]
    for r in runs:
        await repos.snapshot_sync_runs.add(r)
    return repos


@pytest.fixture
def client_with_data(repos_with_data: RepositoryContainer) -> TestClient:
    """FastAPI ``TestClient`` with pre-seeded snapshot sync runs."""
    app = create_app(repos=repos_with_data, auth_enabled=False)
    with TestClient(app) as tc:
        yield tc


# ── Test: List ─────────────────────────────────────────────────────────────


class TestListSnapshotSyncRuns:
    """``GET /snapshot-sync-runs`` — list behaviour."""

    def test_list_empty(self, empty_client: TestClient) -> None:
        """Empty repository returns an empty list."""
        response = empty_client.get("/snapshot-sync-runs")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_with_data(self, client_with_data: TestClient) -> None:
        """Returns all runs when no filters are applied."""
        response = client_with_data.get("/snapshot-sync-runs")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3

        # Verify top-level fields on the first item
        first = data[0]
        assert "snapshot_sync_run_id" in first
        assert first["trigger_type"] in ("manual", "scheduler")
        assert first["scope"] in ("all", "batch", "single")
        assert isinstance(first["dry_run"], bool)
        assert isinstance(first["total_accounts"], int)
        assert isinstance(first["succeeded_accounts"], int)
        assert isinstance(first["status"], str)
        assert isinstance(first["started_at"], str)

    def test_list_sorted_desc(self, client_with_data: TestClient) -> None:
        """Results are sorted by ``started_at`` descending (newest first)."""
        response = client_with_data.get("/snapshot-sync-runs")
        assert response.status_code == 200
        data = response.json()
        timestamps = [d["started_at"] for d in data]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_list_filter_trigger_type(
        self, client_with_data: TestClient
    ) -> None:
        """``trigger_type`` query param filters correctly."""
        response = client_with_data.get("/snapshot-sync-runs?trigger_type=manual")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert all(d["trigger_type"] == "manual" for d in data)

    def test_list_filter_status(self, client_with_data: TestClient) -> None:
        """``status`` query param filters correctly."""
        response = client_with_data.get("/snapshot-sync-runs?status=completed")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["status"] == "completed"

    def test_list_limit(self, repos_with_data: RepositoryContainer) -> None:
        """``limit`` param caps the number of returned records."""
        app = create_app(repos=repos_with_data, auth_enabled=False)
        with TestClient(app) as tc:
            response = tc.get("/snapshot-sync-runs?limit=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2


# ── Test: Get by ID ────────────────────────────────────────────────────────


class TestGetSnapshotSyncRun:
    """``GET /snapshot-sync-runs/{run_id}`` — single-run retrieval."""

    async def test_get_by_id(self, repos_with_data: RepositoryContainer) -> None:
        """Returns a single run by UUID."""
        app = create_app(repos=repos_with_data, auth_enabled=False)
        with TestClient(app) as tc:
            # Fetch the list first to get a valid ID
            list_resp = tc.get("/snapshot-sync-runs")
            run_id = list_resp.json()[0]["snapshot_sync_run_id"]

            response = tc.get(f"/snapshot-sync-runs/{run_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["snapshot_sync_run_id"] == run_id
        assert isinstance(data["trigger_type"], str)
        assert isinstance(data["scope"], str)
        assert isinstance(data["status"], str)

    def test_get_by_id_not_found(self, empty_client: TestClient) -> None:
        """Non-existent UUID returns 404."""
        fake_id = uuid4()
        response = empty_client.get(f"/snapshot-sync-runs/{fake_id}")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_by_id_invalid_uuid(self, empty_client: TestClient) -> None:
        """Malformed UUID returns 400."""
        response = empty_client.get("/snapshot-sync-runs/not-a-uuid")
        assert response.status_code == 400
        assert "invalid uuid" in response.json()["detail"].lower()


# ── Test: Auth ─────────────────────────────────────────────────────────────


class TestSnapshotSyncRunAuth:
    """Authentication enforcement for snapshot-sync-runs endpoints."""

    def test_auth_required_for_list(self) -> None:
        """``GET /snapshot-sync-runs`` requires auth when enabled."""
        app = create_app(auth_token="valid-token")
        with TestClient(app) as tc:
            response = tc.get("/snapshot-sync-runs")
        assert response.status_code == 401

    def test_auth_required_for_get(self) -> None:
        """``GET /snapshot-sync-runs/{id}`` requires auth when enabled."""
        app = create_app(auth_token="valid-token")
        with TestClient(app) as tc:
            response = tc.get(f"/snapshot-sync-runs/{uuid4()}")
        assert response.status_code == 401

    def test_auth_passes_with_valid_token(self) -> None:
        """Valid Bearer token grants access."""
        app = create_app(auth_token="valid-token")
        with TestClient(app) as tc:
            response = tc.get(
                "/snapshot-sync-runs",
                headers={"Authorization": "Bearer valid-token"},
            )
        assert response.status_code == 200


# ── Test: Health Summary ──────────────────────────────────────────────────


class TestSnapshotSyncRunHealthSummary:
    """``GET /snapshot-sync-runs/summary`` — freshness/health summary."""

    def test_summary_empty(self, empty_client: TestClient) -> None:
        """No runs → all fields are None/0/True."""
        response = empty_client.get("/snapshot-sync-runs/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["last_run_started_at"] is None
        assert data["last_run_completed_at"] is None
        assert data["last_status"] is None
        assert data["last_successful_run_at"] is None
        assert data["consecutive_failures"] == 0
        assert data["is_stale"] is True
        assert data["stale_threshold_seconds"] == 900

    def test_summary_fresh_completed(self) -> None:
        """Recent completed run → not stale."""
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)
        run = _make_run(
            started_at=now - timedelta(seconds=10),
            status="completed",
        )
        repos.snapshot_sync_runs._items[run.snapshot_sync_run_id] = run  # type: ignore[attr-defined]

        app = create_app(repos=repos, auth_enabled=False)
        with TestClient(app) as tc:
            response = tc.get("/snapshot-sync-runs/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["last_status"] == "completed"
        assert data["last_successful_run_at"] is not None
        assert data["consecutive_failures"] == 0
        assert data["is_stale"] is False
        assert data["stale_threshold_seconds"] == 900

    def test_summary_stale_old_completed(self) -> None:
        """Old completed run (2000s ago, threshold 900) → stale."""
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)
        run = _make_run(
            started_at=now - timedelta(seconds=2000),
            status="completed",
        )
        repos.snapshot_sync_runs._items[run.snapshot_sync_run_id] = run  # type: ignore[attr-defined]

        app = create_app(repos=repos, auth_enabled=False)
        with TestClient(app) as tc:
            response = tc.get("/snapshot-sync-runs/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["last_status"] == "completed"
        assert data["is_stale"] is True

    def test_summary_consecutive_failures(self) -> None:
        """3 failed runs followed by 1 completed → consecutive_failures=3."""
        repos = build_in_memory_repositories()
        now = datetime.now(timezone.utc)
        # Insert in chronological order; _items dict will sort by started_at DESC
        completed = _make_run(
            started_at=now - timedelta(hours=4),
            status="completed",
        )
        repos.snapshot_sync_runs._items[completed.snapshot_sync_run_id] = completed  # type: ignore[attr-defined]

        for i in range(3):
            failed_run = _make_run(
                started_at=now - timedelta(hours=3 - i),
                status="failed",
            )
            repos.snapshot_sync_runs._items[failed_run.snapshot_sync_run_id] = failed_run  # type: ignore[attr-defined]

        app = create_app(repos=repos, auth_enabled=False)
        with TestClient(app) as tc:
            response = tc.get("/snapshot-sync-runs/summary")
        assert response.status_code == 200
        data = response.json()
        assert data["last_status"] == "failed"
        assert data["consecutive_failures"] == 3
        assert data["last_successful_run_at"] is not None
        assert data["is_stale"] is True

    def test_summary_auth_required(self) -> None:
        """``GET /snapshot-sync-runs/summary`` requires auth when enabled."""
        app = create_app(auth_token="valid-token")
        with TestClient(app) as tc:
            response = tc.get("/snapshot-sync-runs/summary")
        assert response.status_code == 401

    def test_summary_auth_passes(self) -> None:
        """Valid Bearer token grants access to summary endpoint."""
        app = create_app(auth_token="valid-token")
        with TestClient(app) as tc:
            response = tc.get(
                "/snapshot-sync-runs/summary",
                headers={"Authorization": "Bearer valid-token"},
            )
        assert response.status_code == 200
