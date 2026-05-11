#!/usr/bin/env python3
"""Phase 4a: DB seed for smoke test — instruments 1 row + external_events 1 row.

Usage:
    set -a; . /workspace/agent_trading/.env; set +a
    python3 scripts/seed_smoke_test.py

Cleanup:
    python3 scripts/seed_smoke_test.py --cleanup
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid

from agent_trading.db.connection import create_pool
from agent_trading.db.transaction import transaction


INSTRUMENT_ID = "44444444-4444-4444-4444-444444444444"
SYMBOL = "005930"
MARKET = "KRX"


async def _seed_instrument() -> bool:
    """INSERT 005930/KRX instrument if not exists. Returns True if inserted."""
    async with transaction() as tx:
        existing = await tx.connection.fetchrow(
            "SELECT instrument_id FROM instruments WHERE symbol = $1 AND market_code = $2",
            SYMBOL, MARKET,
        )
        if existing:
            print(f"[SKIP] instruments 005930/KRX already exists: {existing['instrument_id']}")
            return False

        await tx.connection.execute(
            """
            INSERT INTO instruments (
                instrument_id, symbol, market_code, asset_class, currency,
                name, tick_size, lot_size, is_active, metadata, created_at, updated_at
            ) VALUES (
                $1, $2, $3, 'kr_stock', 'KRW',
                'Samsung Electronics Co., Ltd.',
                100.00000000, 1.00000000, true,
                $4::jsonb, NOW(), NOW()
            )
            """,
            INSTRUMENT_ID, SYMBOL, MARKET,
            json.dumps({"purpose": "smoke_test", "version": "v1"}),
        )
        await tx.commit()
        print(f"[INSERT] instruments: {SYMBOL}/{MARKET} ({INSTRUMENT_ID})")
        return True


async def _seed_event() -> bool:
    """INSERT one bullish external_event for 005930. Returns True if inserted."""
    async with transaction() as tx:
        event_id = str(uuid.uuid4())
        metadata = json.dumps({
            "purpose": "smoke_test",
            "version": "v1",
            "synthetic": True,
        })

        await tx.connection.execute(
            """
            INSERT INTO external_events (
                event_id, event_type, source_name, source_reliability_tier,
                source_event_id, symbol, market,
                published_at, ingested_at, effective_at,
                severity, direction, headline, body_summary,
                metadata, created_at
            ) VALUES (
                $1::uuid, 'technical_setup', 'smoke_test_v1', 'T3',
                'smoke-001', $2, $3,
                NOW(), NOW(), NOW(),
                'medium', 'bullish',
                'Smoke Test: Bullish technical setup detected for 005930',
                'Simulated price momentum signal. This is a synthetic event for pipeline validation. '
                'Resistance breakout observed on above-average volume. '
                'Not based on actual market data.',
                $4::jsonb, NOW()
            )
            """,
            event_id, SYMBOL, MARKET, metadata,
        )
        await tx.commit()
        print(f"[INSERT] external_events: {SYMBOL} bullish/medium (event_id={event_id})")
        return True


async def _cleanup() -> None:
    """Remove all smoke_test seed rows."""
    async with transaction() as tx:
        ev_result = await tx.connection.execute(
            "DELETE FROM external_events WHERE metadata->>'purpose' = 'smoke_test'"
        )
        inst_result = await tx.connection.execute(
            "DELETE FROM instruments WHERE metadata->>'purpose' = 'smoke_test'"
        )
        await tx.commit()
    print(f"[CLEANUP] external_events: {ev_result.replace('DELETE ', '')} rows deleted")
    print(f"[CLEANUP] instruments: {inst_result.replace('DELETE ', '')} rows deleted")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Seed smoke test data")
    parser.add_argument("--cleanup", action="store_true", help="Remove smoke_test seed rows")
    args = parser.parse_args()

    await create_pool()

    if args.cleanup:
        await _cleanup()
        return 0

    await _seed_instrument()
    await _seed_event()
    print("[DONE] Phase 4a seed complete")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
