"""
Tests for the ops scheduler (canonical entrypoint).

These tests verify that the canonical entrypoint works correctly,
including backward compatibility with the legacy wrapper.
"""

from __future__ import annotations

# Re-export all tests from the legacy test module for backward compatibility
from tests.scripts.test_run_near_real_ops_scheduler import *  # noqa: F401, F403
