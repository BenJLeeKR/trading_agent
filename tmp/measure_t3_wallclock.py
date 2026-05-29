#!/usr/bin/env python3
"""
T3 Wall Clock Measurement Script
=================================
Phase 5f — Sub Task 3: Measure actual wall-clock elapsed time for 40 seeds
with _SEED_PACING_DELAY=0.125 under various NAVER API latency scenarios.

Usage:
    python3 tmp/measure_t3_wallclock.py

Requirements:
    - Python 3.10+ (asyncio)
    - Standard library only (no external dependencies)
"""

import asyncio
import time
import sys

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SEED_COUNT = 40
SEED_PACING_DELAY = 0.125  # seconds between seeds (current)
LEGACY_PACING_DELAY = 0.5  # seconds between seeds (before change)
T3_TIMEOUT = 30.0          # seconds

# ---------------------------------------------------------------------------
# Simulated seed processing
# ---------------------------------------------------------------------------

async def process_seed(seed_index: int, api_latency: float) -> None:
    """Simulate processing a single seed with the given API latency."""
    # Simulate NAVER API call
    await asyncio.sleep(api_latency)


async def run_scenario(
    pacing_delay: float,
    api_latency: float,
    seed_count: int = SEED_COUNT,
    step1_extra: float = 0.0,
) -> float:
    """
    Run a full scenario: process `seed_count` seeds sequentially with
    `pacing_delay` between each and `api_latency` per API call.

    Returns total elapsed wall-clock time in seconds.
    """
    start = time.monotonic()

    for i in range(seed_count):
        await process_seed(i, api_latency)
        if i < seed_count - 1:
            await asyncio.sleep(pacing_delay)

    elapsed = time.monotonic() - start
    return elapsed + step1_extra


def format_result(
    label: str,
    pacing: float,
    api_latency: float,
    step1: float,
    measured: float,
    timeout: float,
) -> str:
    """Format a single scenario result line."""
    theoretical_pacing = (SEED_COUNT - 1) * pacing
    theoretical_api = SEED_COUNT * api_latency
    theoretical_total = theoretical_pacing + theoretical_api + step1

    pct_of_budget = (measured / timeout) * 100
    status = "✅ OK" if measured <= timeout else "❌ TIMEOUT"
    if measured <= timeout and pct_of_budget > 85:
        status = "⚠️ NEAR LIMIT"

    lines = [
        f"\n[{label}]",
        f"  Pacing delay : {theoretical_pacing:.3f}s (theoretical)",
        f"  API latency  : {theoretical_api:.3f}s (theoretical)",
        f"  Step 1 extra : {step1:.3f}s",
        f"  Total        : {measured:.3f}s (measured)",
        f"  Theoretical  : {theoretical_total:.3f}s (expected)",
        f"  Diff         : {measured - theoretical_total:+.3f}s ({((measured / theoretical_total) - 1) * 100:+.2f}%)",
        f"  Timeout ({timeout:.0f}s): {status} ({pct_of_budget:.1f}% of budget)",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    header = (
        "=" * 68 + "\n"
        f"  T3 Wall Clock Measurement ({SEED_COUNT} seeds, _SEED_PACING_DELAY={SEED_PACING_DELAY})\n"
        + "=" * 68
    )
    print(header)

    results = []

    # --- Scenario 1: Pacing only (0ms API latency) ---
    print("\n" + "-" * 68)
    print("  [Scenario 1] Pacing only (0ms API latency)")
    print("-" * 68)
    t = await run_scenario(SEED_PACING_DELAY, 0.0)
    results.append(("1", SEED_PACING_DELAY, 0.0, 0.0, t))
    print(format_result("Scenario 1", SEED_PACING_DELAY, 0.0, 0.0, t, T3_TIMEOUT))

    # --- Scenario 2: Pacing + Low latency (0.2s) ---
    print("\n" + "-" * 68)
    print("  [Scenario 2] Pacing + Low latency (0.2s)")
    print("-" * 68)
    t = await run_scenario(SEED_PACING_DELAY, 0.2)
    results.append(("2", SEED_PACING_DELAY, 0.2, 0.0, t))
    print(format_result("Scenario 2", SEED_PACING_DELAY, 0.2, 0.0, t, T3_TIMEOUT))

    # --- Scenario 3: Pacing + Medium latency (0.35s) ---
    print("\n" + "-" * 68)
    print("  [Scenario 3] Pacing + Medium latency (0.35s)")
    print("-" * 68)
    t = await run_scenario(SEED_PACING_DELAY, 0.35)
    results.append(("3", SEED_PACING_DELAY, 0.35, 0.0, t))
    print(format_result("Scenario 3", SEED_PACING_DELAY, 0.35, 0.0, t, T3_TIMEOUT))

    # --- Scenario 4: Pacing + High latency (0.5s) ---
    print("\n" + "-" * 68)
    print("  [Scenario 4] Pacing + High latency (0.5s)")
    print("-" * 68)
    t = await run_scenario(SEED_PACING_DELAY, 0.5)
    results.append(("4", SEED_PACING_DELAY, 0.5, 0.0, t))
    print(format_result("Scenario 4", SEED_PACING_DELAY, 0.5, 0.0, t, T3_TIMEOUT))

    # --- Scenario 5: Legacy 0.5s pacing + 0.2s latency ---
    print("\n" + "-" * 68)
    print("  [Scenario 5] Legacy 0.5s pacing + 0.2s latency (for comparison)")
    print("-" * 68)
    t = await run_scenario(LEGACY_PACING_DELAY, 0.2)
    results.append(("5", LEGACY_PACING_DELAY, 0.2, 0.0, t))
    print(format_result("Scenario 5", LEGACY_PACING_DELAY, 0.2, 0.0, t, T3_TIMEOUT))

    # --- Scenario 6a: Step 1 (3s) + Scenario 2 (low latency) ---
    print("\n" + "-" * 68)
    print("  [Scenario 6a] Step 1 (3s) + Pacing + Low latency (0.2s)")
    print("-" * 68)
    t = await run_scenario(SEED_PACING_DELAY, 0.2, step1_extra=3.0)
    results.append(("6a", SEED_PACING_DELAY, 0.2, 3.0, t))
    print(format_result("Scenario 6a", SEED_PACING_DELAY, 0.2, 3.0, t, T3_TIMEOUT))

    # --- Scenario 6b: Step 1 (3s) + Scenario 3 (medium latency) ---
    print("\n" + "-" * 68)
    print("  [Scenario 6b] Step 1 (3s) + Pacing + Medium latency (0.35s)")
    print("-" * 68)
    t = await run_scenario(SEED_PACING_DELAY, 0.35, step1_extra=3.0)
    results.append(("6b", SEED_PACING_DELAY, 0.35, 3.0, t))
    print(format_result("Scenario 6b", SEED_PACING_DELAY, 0.35, 3.0, t, T3_TIMEOUT))

    # --- Summary Table ---
    print("\n" + "=" * 68)
    print("  Summary")
    print("=" * 68)
    header_row = (
        f"| {'Scenario':<8} | {'Pacing':<7} | {'API Lat':<8} | {'Step1':<6} | "
        f"{'Total Est':<10} | {'Total Meas':<11} | {'Timeout?':<8} |"
    )
    sep = "|" + "-" * 8 + "|" + "-" * 7 + "|" + "-" * 8 + "|" + "-" * 6 + "|" + "-" * 10 + "|" + "-" * 11 + "|" + "-" * 8 + "|"
    print(header_row)
    print(sep)

    for sc_id, pacing, api_lat, step1, measured in results:
        theoretical_pacing = (SEED_COUNT - 1) * pacing
        theoretical_api = SEED_COUNT * api_lat
        theoretical_total = theoretical_pacing + theoretical_api + step1

        if measured <= T3_TIMEOUT:
            status = "✅"
        else:
            status = "❌"

        print(
            f"| {sc_id:<8} | {pacing:<7} | {api_lat:<8} | {step1:<6} | "
            f"{theoretical_total:<10.3f} | {measured:<11.3f} | {status:<8} |"
        )

    print("=" * 68)
    print()


if __name__ == "__main__":
    asyncio.run(main())
