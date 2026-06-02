"""Tests for FileBackedGlobalBucket."""

from __future__ import annotations

import os
import tempfile
import time

import pytest

from agent_trading.brokers.shared_budget import FileBackedGlobalBucket


class TestFileBackedGlobalBucket:
    """``FileBackedGlobalBucket`` unit tests."""

    def setup_method(self) -> None:
        """Create a temporary file for each test."""
        self.tmp = tempfile.NamedTemporaryFile(delete=False)
        self.path = self.tmp.name
        self.tmp.close()

    def teardown_method(self) -> None:
        """Clean up the temporary file."""
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_consume_success(self) -> None:
        """Single token consumption succeeds when bucket is full."""
        bucket = FileBackedGlobalBucket(capacity=1.0, refill_rate=1.0)
        bucket._FILE_PATH = self.path
        assert bucket.try_consume(1) is True

    def test_consume_exhausted(self) -> None:
        """Consumption fails when bucket is exhausted (no refill)."""
        bucket = FileBackedGlobalBucket(capacity=1.0, refill_rate=0.0)  # No refill
        bucket._FILE_PATH = self.path
        assert bucket.try_consume(1) is True
        assert bucket.try_consume(1) is False

    def test_refill_over_time(self) -> None:
        """Bucket refills after sufficient time passes."""
        bucket = FileBackedGlobalBucket(capacity=1.0, refill_rate=1.0)
        bucket._FILE_PATH = self.path
        assert bucket.try_consume(1) is True
        assert bucket.try_consume(1) is False  # Exhausted

        # Manually simulate time passing by rewriting the file
        now = time.time()
        with open(self.path, "w") as f:
            f.write(f"0.0,{now - 1.0}")

        assert bucket.try_consume(1) is True  # Refilled

    def test_capacity_property(self) -> None:
        """``capacity`` property returns the configured capacity."""
        bucket = FileBackedGlobalBucket(capacity=2.0, refill_rate=1.0)
        assert bucket.capacity == 2

    def test_remaining_property_full(self) -> None:
        """``remaining`` returns capacity when file is empty/fresh."""
        bucket = FileBackedGlobalBucket(capacity=3.0, refill_rate=1.0)
        bucket._FILE_PATH = self.path
        assert bucket.remaining == 3

    def test_remaining_property_after_consume(self) -> None:
        """``remaining`` reflects consumed tokens."""
        bucket = FileBackedGlobalBucket(capacity=2.0, refill_rate=0.0)
        bucket._FILE_PATH = self.path
        bucket.try_consume(1)
        assert bucket.remaining == 1

    def test_remaining_property_applies_elapsed_refill(self) -> None:
        """``remaining`` should reflect elapsed refill time even before consume."""
        bucket = FileBackedGlobalBucket(capacity=1.0, refill_rate=1.0)
        bucket._FILE_PATH = self.path
        now = time.time()
        with open(self.path, "w") as f:
            f.write(f"0.0,{now - 1.2}")
        assert bucket.remaining == 1

    def test_remaining_property_file_not_found(self) -> None:
        """``remaining`` returns capacity when file does not exist."""
        bucket = FileBackedGlobalBucket(capacity=5.0, refill_rate=1.0)
        # Use a non-existent path
        bucket._FILE_PATH = "/tmp/.nonexistent_test_budget_file"
        assert bucket.remaining == 5

    def test_custom_file_path(self) -> None:
        """Custom ``file_path`` is used when provided."""
        bucket = FileBackedGlobalBucket(
            capacity=1.0,
            refill_rate=1.0,
            file_path=self.path,
        )
        assert bucket._FILE_PATH == self.path
        assert bucket.try_consume(1) is True

    def test_async_consume(self) -> None:
        """Async ``consume()`` works correctly."""
        bucket = FileBackedGlobalBucket(capacity=1.0, refill_rate=0.0)
        bucket._FILE_PATH = self.path

        import asyncio

        result = asyncio.run(bucket.consume(1.0))
        assert result is True

        result = asyncio.run(bucket.consume(1.0))
        assert result is False

    def test_wait_until_available(self) -> None:
        """``wait_until_available()`` blocks until tokens are available."""
        bucket = FileBackedGlobalBucket(capacity=1.0, refill_rate=1.0)
        bucket._FILE_PATH = self.path

        # Exhaust the bucket
        assert bucket.try_consume(1) is True

        # Manually set the file to 0 tokens, 1 second ago
        now = time.time()
        with open(self.path, "w") as f:
            f.write(f"0.0,{now - 1.0}")

        # wait_until_available should succeed after refill
        import asyncio

        asyncio.run(bucket.wait_until_available(1.0))
        # After wait, the token should be consumed
        assert bucket.try_consume(1) is False  # Second consume should fail

    def test_concurrent_access_same_file(self) -> None:
        """Two buckets pointing to the same file share the budget."""
        bucket_a = FileBackedGlobalBucket(capacity=1.0, refill_rate=0.0)
        bucket_b = FileBackedGlobalBucket(capacity=1.0, refill_rate=0.0)
        bucket_a._FILE_PATH = self.path
        bucket_b._FILE_PATH = self.path

        # First consume from bucket_a
        assert bucket_a.try_consume(1) is True
        # Second consume from bucket_b should see the same file state
        assert bucket_b.try_consume(1) is False

    def test_fail_open_on_os_error(self) -> None:
        """On OSError, ``try_consume()`` returns True (fail open)."""
        bucket = FileBackedGlobalBucket(capacity=1.0, refill_rate=1.0)
        # Point to a directory path that cannot be opened as a file
        bucket._FILE_PATH = "/tmp/"
        # Should return True (fail open) rather than crashing
        assert bucket.try_consume(1) is True

    def test_release_returns_token(self) -> None:
        """``release()`` should restore a consumed token."""
        bucket = FileBackedGlobalBucket(capacity=1.0, refill_rate=0.0)
        bucket._FILE_PATH = self.path
        assert bucket.try_consume(1) is True
        assert bucket.remaining == 0
        bucket.release(1)
        assert bucket.remaining == 1

    def test_refill_noop_compatibility(self) -> None:
        """``_refill()`` exists for ``OperationBucket`` compatibility and does not crash."""
        bucket = FileBackedGlobalBucket(capacity=1.0, refill_rate=1.0)
        bucket._FILE_PATH = self.path
        bucket._refill()
        assert bucket.capacity == 1
