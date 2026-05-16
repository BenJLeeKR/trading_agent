#!/usr/bin/env python3
"""
Operations Scheduler — KIS market session aware trading scheduler.

This is the canonical entrypoint for the trading operations scheduler.
It is environment-neutral: the same script works for both paper and live
trading environments, differentiated only by the KIS_ENV setting.

Usage:
    python3 scripts/run_ops_scheduler.py [--after-hours]

See Also:
    scripts/run_near_real_ops_scheduler.py (legacy wrapper, kept for compatibility)
"""

from __future__ import annotations

# Re-export from the canonical implementation module
from scripts.run_near_real_ops_scheduler import (  # noqa: F401  # backward compatibility
    NearRealOpsScheduler,
    main,
    __main__,
)

if __name__ == "__main__":
    main()
