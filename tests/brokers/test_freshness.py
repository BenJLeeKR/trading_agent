"""Tests for FreshnessBudget."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent_trading.brokers.freshness import FreshnessBudget


class TestFreshnessBudget:
    """FreshnessBudget deterministic stale marking."""

    def test_fresh_event_not_stale(self) -> None:
        """Event ingested within freshness window is not stale."""
        budget = FreshnessBudget(freshness_max_seconds=600)  # 10 minutes
        published = datetime.now(timezone.utc) - timedelta(minutes=5)
        ingested = datetime.now(timezone.utc)
        assert not budget.is_stale(published, ingested)

    def test_stale_event_detected(self) -> None:
        """Event ingested beyond freshness window is stale."""
        budget = FreshnessBudget(freshness_max_seconds=600)  # 10 minutes
        published = datetime.now(timezone.utc) - timedelta(minutes=15)
        ingested = datetime.now(timezone.utc)
        assert budget.is_stale(published, ingested)

    def test_exact_boundary_not_stale(self) -> None:
        """Event at exactly freshness_max_seconds is not stale (strict >)."""
        budget = FreshnessBudget(freshness_max_seconds=600)
        published = datetime(2024, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
        ingested = datetime(2024, 1, 1, 9, 10, 0, tzinfo=timezone.utc)  # exactly 600s later
        assert not budget.is_stale(published, ingested)

    def test_deterministic_same_input_same_result(self) -> None:
        """Same inputs always produce the same stale classification."""
        budget = FreshnessBudget(freshness_max_seconds=300)
        published = datetime(2024, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
        ingested = datetime(2024, 1, 1, 9, 10, 0, tzinfo=timezone.utc)
        result1 = budget.is_stale(published, ingested)
        result2 = budget.is_stale(published, ingested)
        assert result1 == result2

    def test_stale_metadata_fresh(self) -> None:
        """stale_metadata returns {'stale': False} for fresh events."""
        budget = FreshnessBudget(freshness_max_seconds=600)
        published = datetime.now(timezone.utc) - timedelta(minutes=5)
        ingested = datetime.now(timezone.utc)
        meta = budget.stale_metadata(published, ingested)
        assert meta == {"stale": False}

    def test_stale_metadata_stale(self) -> None:
        """stale_metadata returns {'stale': True} for stale events."""
        budget = FreshnessBudget(freshness_max_seconds=600)
        published = datetime.now(timezone.utc) - timedelta(minutes=15)
        ingested = datetime.now(timezone.utc)
        meta = budget.stale_metadata(published, ingested)
        assert meta == {"stale": True}

    def test_replay_same_classification(self) -> None:
        """Replay with same inputs produces same stale classification.

        This ensures replay reproducibility.
        """
        budget = FreshnessBudget(freshness_max_seconds=600)
        published = datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        ingested = datetime(2024, 6, 15, 10, 35, 0, tzinfo=timezone.utc)

        # First pass
        meta1 = budget.stale_metadata(published, ingested)

        # Replay with same inputs
        meta2 = budget.stale_metadata(published, ingested)

        assert meta1 == meta2
        assert meta1 == {"stale": False}
