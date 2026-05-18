"""Tests for KIS environment-aware rate limit budget factory.

Verifies that:
1. ``build_kis_budget_manager()`` creates per-bucket safety-scaled capacities for paper env.
2. ``build_kis_budget_manager()`` creates per-bucket safety-scaled capacities for live env.
3. Custom RPS overrides scale bucket capacities relative to the environment baseline.
"""

from __future__ import annotations

import pytest

from agent_trading.brokers.rate_limit import (
    BudgetExhaustedError,
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
        """Live env with default 18 RPS (per KIS notice 2026-04-20) creates scaled buckets."""
        mgr = build_kis_budget_manager(kis_env="live")
        assert isinstance(mgr, RateLimitBudgetManager)
        snap = mgr.snapshot()
        # Live baseline capacities (18 RPS, scale=18/15=1.2):
        # auth=6, order=6, inquiry=12, market_data=24, reconciliation=6
        assert snap["auth"]["capacity"] == 6
        assert snap["order"]["capacity"] == 6
        assert snap["inquiry"]["capacity"] == 12
        assert snap["market_data"]["capacity"] == 24
        assert snap["reconciliation"]["capacity"] == 6

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


class TestStrictGlobalRestCap:
    """``build_kis_budget_manager()`` global REST bucket (2-tier enforcement)."""

    def test_global_bucket_paper_default(self) -> None:
        """Paper env: global REST bucket capacity=1, refill_rate=1.0."""
        mgr = build_kis_budget_manager(kis_env="paper")
        snap = mgr.snapshot()
        assert "global" in snap
        assert snap["global"]["capacity"] == 1
        assert snap["global"]["refill_rate"] == 1.0

    def test_global_bucket_live_default(self) -> None:
        """Live env: global REST bucket capacity=18, refill_rate=18.0."""
        mgr = build_kis_budget_manager(kis_env="live")
        snap = mgr.snapshot()
        assert "global" in snap
        assert snap["global"]["capacity"] == 18
        assert snap["global"]["refill_rate"] == 18.0

    def test_global_bucket_custom_rps(self) -> None:
        """Custom ``real_rest_rps=30`` scales global bucket capacity proportionally."""
        mgr = build_kis_budget_manager(kis_env="live", real_rest_rps=30)
        snap = mgr.snapshot()
        assert "global" in snap
        assert snap["global"]["capacity"] == 30
        assert snap["global"]["refill_rate"] == 30.0

    def test_global_bucket_exhausted_blocks_operation(self) -> None:
        """Global bucket empty → ``consume_or_raise()`` raises ``BudgetExhaustedError``."""
        mgr = build_kis_budget_manager(kis_env="paper")  # global capacity=1
        # First call consumes the only token
        mgr.consume_or_raise(BucketType.INQUIRY)
        # Second call should fail on the global bucket (paper: 1 RPS)
        with pytest.raises(BudgetExhaustedError) as exc_info:
            mgr.consume_or_raise(BucketType.INQUIRY)
        assert exc_info.value.bucket == "global"

    def test_per_bucket_exhausted_independently(self) -> None:
        """Global bucket OK but per-bucket empty → raises for per-bucket."""
        mgr = build_kis_budget_manager(kis_env="paper")
        # Drain the inquiry bucket by consuming until exhausted
        # Paper inquiry capacity=1, refill_rate=0.5 — consume 1 to drain
        snap = mgr.snapshot()
        inquiry_cap = snap["inquiry"]["capacity"]
        for _ in range(inquiry_cap):
            mgr.consume_or_raise(BucketType.INQUIRY)  # consumes global + inquiry
        # Global is paper (1 rps) — already consumed above. Need to account for that.
        # Actually let's use a different approach: create a budget with large global,
        # then drain inquiry.
        mgr2 = build_kis_budget_manager(kis_env="live")  # global=18, inquiry=12
        for _ in range(12):
            mgr2.consume_or_raise(BucketType.INQUIRY)
        # Now inquiry is exhausted but global (18) still has tokens
        with pytest.raises(BudgetExhaustedError) as exc_info:
            mgr2.consume_or_raise(BucketType.INQUIRY)
        assert exc_info.value.bucket == "inquiry"

    def test_global_bucket_disabled_by_default(self) -> None:
        """``RateLimitBudgetManager()`` direct construction has no global bucket."""
        mgr = RateLimitBudgetManager()
        snap = mgr.snapshot()
        assert "global" not in snap


class TestSharedBudgetFile:
    """``build_kis_budget_manager()`` with ``shared_budget_file`` parameter."""

    def test_paper_with_shared_budget_file(self) -> None:
        """Paper env with ``shared_budget_file`` creates a ``FileBackedGlobalBucket``."""
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            path = tmp.name

        try:
            mgr = build_kis_budget_manager(
                kis_env="paper",
                shared_budget_file=path,
            )
            from agent_trading.brokers.shared_budget import FileBackedGlobalBucket

            assert isinstance(mgr.global_rest, FileBackedGlobalBucket)
            assert mgr.global_rest.capacity == 1
        finally:
            import os
            if os.path.exists(path):
                os.unlink(path)

    def test_paper_shared_budget_blocks_across_instances(self) -> None:
        """Two managers sharing the same file enforce cross-process budget."""
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            path = tmp.name

        try:
            mgr1 = build_kis_budget_manager(
                kis_env="paper",
                shared_budget_file=path,
            )
            mgr2 = build_kis_budget_manager(
                kis_env="paper",
                shared_budget_file=path,
            )

            # First consume from mgr1 should succeed
            mgr1.consume_or_raise(BucketType.INQUIRY)

            # Second consume from mgr2 should fail on global bucket
            from agent_trading.brokers.rate_limit import BudgetExhaustedError

            with pytest.raises(BudgetExhaustedError) as exc_info:
                mgr2.consume_or_raise(BucketType.INQUIRY)
            assert exc_info.value.bucket == "global"
        finally:
            import os
            if os.path.exists(path):
                os.unlink(path)

    def test_live_with_shared_budget_file_ignored(self) -> None:
        """Live env ignores ``shared_budget_file`` (only paper uses it)."""
        mgr = build_kis_budget_manager(
            kis_env="live",
            shared_budget_file="/tmp/.should_not_exist",
        )
        from agent_trading.brokers.rate_limit import OperationBucket

        assert isinstance(mgr.global_rest, OperationBucket)
        assert mgr.global_rest.capacity == 18
