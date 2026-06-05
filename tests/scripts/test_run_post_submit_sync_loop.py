"""Tests for ``scripts.run_post_submit_sync_loop`` — post-submit sync scheduler."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import scripts.run_post_submit_sync_loop as module
from scripts.run_post_submit_sync_loop import _parse_args
from agent_trading.services.order_sync_service import SyncCycleResult


class TestParseArgsAfterHours:
    """``--after-hours`` CLI 플래그 파싱 테스트."""

    def test_parse_args_after_hours_default(self) -> None:
        """``--after-hours`` 기본값이 False인지 검증."""
        args = _parse_args([])
        assert args.after_hours is False

    def test_parse_args_after_hours_enabled(self) -> None:
        """``--after-hours`` 플래그가 True로 파싱되는지 검증."""
        args = _parse_args(["--after-hours"])
        assert args.after_hours is True


class TestBuildRefreshCallback:
    """``_build_refresh_callback()`` — snapshot sync 경로 및 dedupe 검증."""

    @pytest.mark.asyncio
    async def test_refresh_callback_uses_broker_agnostic_sync_and_dedupes(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repos = SimpleNamespace(
            instruments=object(),
            position_snapshots=object(),
            cash_balance_snapshots=object(),
            risk_limit_snapshots=object(),
        )
        rest_client = object()
        broker = SimpleNamespace(_rest_client=rest_client)

        sync_mock = AsyncMock(
            return_value=SimpleNamespace(
                positions_synced=2,
                cash_balance_synced=True,
                orderable_amount_synced=True,
                risk_limit_snapshot_synced=True,
                errors=[],
            )
        )
        provider_clients: list[object] = []

        class DummyProvider:
            def __init__(self, client: object) -> None:
                provider_clients.append(client)

        monkeypatch.setattr(module, "sync_account_snapshots", sync_mock)
        monkeypatch.setattr(
            "agent_trading.brokers.koreainvestment.snapshot.KISSyncSnapshotProvider",
            DummyProvider,
        )

        cb = module._build_refresh_callback(repos, broker, after_hours=True)
        account_id = uuid4()

        await asyncio.gather(cb(account_id), cb(account_id))

        assert provider_clients == [rest_client]
        assert sync_mock.await_count == 1
        kwargs = sync_mock.await_args.kwargs
        assert kwargs["fetch_provider"].__class__ is DummyProvider
        assert kwargs["instrument_repo"] is repos.instruments
        assert kwargs["position_snapshot_repo"] is repos.position_snapshots
        assert kwargs["cash_balance_snapshot_repo"] is repos.cash_balance_snapshots
        assert kwargs["risk_limit_snapshot_repo"] is repos.risk_limit_snapshots
        assert kwargs["account_id"] == account_id
        assert kwargs["after_hours"] is False
        assert kwargs["fetch_positions"] is True
        stats = getattr(cb, "_stats")
        assert stats.scheduled_count == 1
        assert stats.deduped_count == 1
        assert stats.completed_count == 1
        assert stats.degraded_count == 0
        assert stats.failed_count == 0
        assert stats.total_elapsed_ms >= 0
        assert stats.max_elapsed_ms >= 0

    @pytest.mark.asyncio
    async def test_refresh_callback_logs_degraded_when_partial_sync_has_errors(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level("INFO", logger="post_submit_sync_loop")
        repos = SimpleNamespace(
            instruments=object(),
            position_snapshots=object(),
            cash_balance_snapshots=object(),
            risk_limit_snapshots=object(),
        )
        rest_client = object()
        broker = SimpleNamespace(_rest=rest_client)

        sync_mock = AsyncMock(
            return_value=SimpleNamespace(
                positions_synced=0,
                cash_balance_synced=True,
                orderable_amount_synced=False,
                risk_limit_snapshot_synced=False,
                errors=["VTTC8908R budget exhausted"],
            )
        )

        class DummyProvider:
            def __init__(self, client: object) -> None:
                self.client = client

        monkeypatch.setattr(module, "sync_account_snapshots", sync_mock)
        monkeypatch.setattr(
            "agent_trading.brokers.koreainvestment.snapshot.KISSyncSnapshotProvider",
            DummyProvider,
        )

        cb = module._build_refresh_callback(repos, broker, after_hours=False)
        await cb(uuid4())

        assert "Snapshot refresh degraded" in caplog.text
        assert "orderable=False" in caplog.text
        assert "risk_limit=False" in caplog.text
        assert "VTTC8908R budget exhausted" in caplog.text
        assert "elapsed_ms=" in caplog.text

    @pytest.mark.asyncio
    async def test_refresh_callback_logs_degraded_when_cash_synced_but_orderable_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level("INFO", logger="post_submit_sync_loop")
        repos = SimpleNamespace(
            instruments=object(),
            position_snapshots=object(),
            cash_balance_snapshots=object(),
            risk_limit_snapshots=object(),
        )
        broker = SimpleNamespace(_rest=object())

        sync_mock = AsyncMock(
            return_value=SimpleNamespace(
                positions_synced=0,
                cash_balance_synced=True,
                orderable_amount_synced=False,
                risk_limit_snapshot_synced=True,
                errors=[],
            )
        )

        class DummyProvider:
            def __init__(self, client: object) -> None:
                self.client = client

        monkeypatch.setattr(module, "sync_account_snapshots", sync_mock)
        monkeypatch.setattr(
            "agent_trading.brokers.koreainvestment.snapshot.KISSyncSnapshotProvider",
            DummyProvider,
        )

        cb = module._build_refresh_callback(repos, broker, after_hours=False)
        await cb(uuid4())

        assert "Snapshot refresh degraded" in caplog.text
        assert "cash=True" in caplog.text
        assert "orderable=False" in caplog.text
        assert "risk_limit=True" in caplog.text

    @pytest.mark.asyncio
    async def test_refresh_callback_skips_when_adapter_has_no_rest_client(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        repos = SimpleNamespace(
            instruments=object(),
            position_snapshots=object(),
            cash_balance_snapshots=object(),
            risk_limit_snapshots=object(),
        )
        sync_mock = AsyncMock()
        monkeypatch.setattr(module, "sync_account_snapshots", sync_mock)

        cb = module._build_refresh_callback(repos, SimpleNamespace(), after_hours=False)
        await cb(uuid4())

        assert sync_mock.await_count == 0
        assert "has no _rest_client/_rest" in caplog.text
        stats = getattr(cb, "_stats")
        assert stats.failed_count == 1


class TestLogCycleSummary:
    @pytest.mark.asyncio
    async def test_logs_refresh_summary_when_stats_present(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level("INFO", logger="post_submit_sync_loop")
        result = SyncCycleResult(
            total_orders=1,
            updated=1,
            filled=1,
            partial=0,
            snapshots_refreshed=1,
            errors=[],
        )
        stats = module.SnapshotRefreshStats(
            scheduled_count=2,
            deduped_count=1,
            completed_count=1,
            degraded_count=1,
            failed_count=0,
            total_elapsed_ms=350,
            max_elapsed_ms=250,
        )

        module._log_cycle_summary(result, elapsed=1.23, refresh_stats=stats)

        assert "sync-cycle-refresh" in caplog.text
        assert "scheduled=2" in caplog.text
        assert "deduped=1" in caplog.text
        assert "completed=1" in caplog.text
        assert "degraded=1" in caplog.text
        assert "avg_elapsed_ms=175" in caplog.text
        assert "max_elapsed_ms=250" in caplog.text
