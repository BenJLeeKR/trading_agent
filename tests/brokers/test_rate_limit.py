"""Tests for KIS environment-aware rate limit budget factory.

Verifies that:
1. ``build_kis_budget_manager()`` creates per-bucket safety-scaled capacities for paper env.
2. ``build_kis_budget_manager()`` creates per-bucket safety-scaled capacities for live env.
3. Custom RPS overrides scale bucket capacities relative to the environment baseline.
"""

from __future__ import annotations

import pytest

from agent_trading.brokers.rate_limit import (
    BucketType,
    RateLimitBudgetManager,
    build_kis_budget_manager,
)


class TestBuildKisBudgetManager:
    """``build_kis_budget_manager()`` factory function tests."""

    def test_paper_budget_default_rps(self) -> None:
        """Paper env with default 1 RPS creates conservative buckets."""
        mgr = build_kis_budget_manager(kis_env="paper")
        assert isinstance(mgr, RateLimitBudgetManager)
        snap = mgr.snapshot()
        # Paper baseline capacities (1 RPS): all buckets = 1
        assert snap["auth"]["capacity"] == 1
        assert snap["order"]["capacity"] == 1
        assert snap["inquiry"]["capacity"] == 1
        assert snap["market_data"]["capacity"] == 1
        assert snap["reconciliation"]["capacity"] == 1

    def test_live_budget_default_rps(self) -> None:
        """Live env with default 15 RPS creates scaled buckets."""
        mgr = build_kis_budget_manager(kis_env="live")
        assert isinstance(mgr, RateLimitBudgetManager)
        snap = mgr.snapshot()
        # Live baseline capacities (15 RPS): auth=5, order=5, inquiry=10,
        # market_data=20, reconciliation=5
        assert snap["auth"]["capacity"] == 5
        assert snap["order"]["capacity"] == 5
        assert snap["inquiry"]["capacity"] == 10
        assert snap["market_data"]["capacity"] == 20
        assert snap["reconciliation"]["capacity"] == 5

    def test_real_env_treated_as_live(self) -> None:
        """``real`` input is normalised to ``live`` internally."""
        mgr_real = build_kis_budget_manager(kis_env="real")
        mgr_live = build_kis_budget_manager(kis_env="live")
        snap_real = mgr_real.snapshot()
        snap_live = mgr_live.snapshot()
        for key in ("auth", "order", "inquiry", "market_data", "reconciliation"):
            assert snap_real[key]["capacity"] == snap_live[key]["capacity"]

    def test_custom_paper_rps_scales_buckets(self) -> None:
        """Custom ``paper_rest_rps=3`` scales bucket capacities relative to baseline."""
        mgr = build_kis_budget_manager(kis_env="paper", paper_rest_rps=3)
        snap = mgr.snapshot()
        # With 3 RPS (3x default): all capacities = 3
        assert snap["auth"]["capacity"] == 3
        assert snap["order"]["capacity"] == 3
        assert snap["inquiry"]["capacity"] == 3
        assert snap["market_data"]["capacity"] == 3
        assert snap["reconciliation"]["capacity"] == 3

    def test_custom_live_rps_scales_buckets(self) -> None:
        """Custom ``real_rest_rps=30`` scales live bucket capacities relative to baseline."""
        mgr = build_kis_budget_manager(kis_env="live", real_rest_rps=30)
        snap = mgr.snapshot()
        # With 30 RPS (2x default): auth=10, order=10, inquiry=20,
        # market_data=40, reconciliation=10
        assert snap["auth"]["capacity"] == 10
        assert snap["order"]["capacity"] == 10
        assert snap["inquiry"]["capacity"] == 20
        assert snap["market_data"]["capacity"] == 40
        assert snap["reconciliation"]["capacity"] == 10

    def test_capacity_positive(self) -> None:
        """All bucket capacities are at least 1."""
        for env in ("paper", "live"):
            mgr = build_kis_budget_manager(kis_env=env)
            snap = mgr.snapshot()
            for key in ("auth", "order", "inquiry", "market_data", "reconciliation"):
                assert snap[key]["capacity"] >= 1, f"{env}.{key}.capacity < 1"
