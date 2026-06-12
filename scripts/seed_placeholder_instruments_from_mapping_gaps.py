#!/usr/bin/env python3
"""Seed inactive placeholder instruments from recent mapping gaps.

Purpose
-------
- Close the last gap in instrument-master maintenance: when runtime tables
  reference symbols missing from ``trading.instruments``, seed safe
  placeholder rows so downstream snapshot/event/fill paths can converge.
- Placeholders are intentionally **inactive** and carry metadata showing that
  they were auto-seeded from mapping gaps, not canonical KIS master data.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from agent_trading.db.connection import close_pool, create_pool
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import InstrumentEntity
from agent_trading.repositories.contracts import InstrumentRepository
from agent_trading.repositories.postgres.instruments import PostgresInstrumentRepository
from scripts.sync_kis_instrument_master import _enforce_update_policy, _make_instrument_id

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("seed_placeholder_instruments_from_mapping_gaps")


@dataclass(frozen=True, slots=True)
class MappingGap:
    symbol: str
    sources: tuple[str, ...]
    occurrence_count: int
    latest_observed_at: datetime


@dataclass(frozen=True, slots=True)
class SeedCounters:
    inserted: int = 0
    skipped_existing: int = 0


def _build_placeholder_instrument(
    gap: MappingGap,
    *,
    market_code: str,
    asset_class: str,
    currency: str,
    source_tag: str,
) -> InstrumentEntity:
    metadata = {
        "placeholder": True,
        "placeholder_source": "mapping_gap_auto_seed",
        "source_tag": source_tag,
        "sources": list(gap.sources),
        "occurrence_count": gap.occurrence_count,
        "latest_observed_at": gap.latest_observed_at.isoformat(),
        "canonical_master_pending": True,
    }
    return InstrumentEntity(
        instrument_id=_make_instrument_id(gap.symbol, market_code),
        symbol=gap.symbol,
        market_code=market_code,
        asset_class=asset_class,
        currency=currency,
        name=f"[PLACEHOLDER] {gap.symbol}",
        tick_size=Decimal("1"),
        lot_size=Decimal("1"),
        is_active=False,
        metadata=metadata,
    )


async def _query_mapping_gaps(
    tx: TransactionManager,
    *,
    lookback_days: int,
) -> list[MappingGap]:
    rows = await tx.connection.fetch(
        """
        WITH recent_external AS (
            SELECT
                e.symbol,
                'external_events'::text AS source_name,
                COUNT(*)::int AS occurrence_count,
                MAX(COALESCE(e.published_at, e.created_at)) AS latest_observed_at
            FROM trading.external_events e
            LEFT JOIN trading.instruments i ON i.symbol = e.symbol
            WHERE e.symbol IS NOT NULL
              AND e.symbol <> ''
              AND COALESCE(e.published_at, e.created_at) >= NOW() - ($1 * interval '1 day')
              AND i.instrument_id IS NULL
            GROUP BY e.symbol
        ),
        recent_fills AS (
            SELECT
                bfs.symbol,
                'broker_fill_snapshots'::text AS source_name,
                COUNT(*)::int AS occurrence_count,
                MAX(COALESCE(bfs.fill_timestamp, bfs.created_at)) AS latest_observed_at
            FROM trading.broker_fill_snapshots bfs
            LEFT JOIN trading.instruments i ON i.symbol = bfs.symbol
            WHERE bfs.symbol IS NOT NULL
              AND bfs.symbol <> ''
              AND COALESCE(bfs.fill_timestamp, bfs.created_at) >= NOW() - ($1 * interval '1 day')
              AND i.instrument_id IS NULL
            GROUP BY bfs.symbol
        ),
        recent_snapshot_errors AS (
            SELECT
                substring(err.error_text FROM 'pdno=([0-9A-Z]+)') AS symbol,
                'snapshot_sync_runs'::text AS source_name,
                COUNT(*)::int AS occurrence_count,
                MAX(ssr.started_at) AS latest_observed_at
            FROM trading.snapshot_sync_runs ssr
            CROSS JOIN LATERAL jsonb_array_elements_text(ssr.summary_json->'errors') AS err(error_text)
            LEFT JOIN trading.instruments i
              ON i.symbol = substring(err.error_text FROM 'pdno=([0-9A-Z]+)')
            WHERE ssr.started_at >= NOW() - ($1 * interval '1 day')
              AND ssr.summary_json IS NOT NULL
              AND jsonb_typeof(ssr.summary_json->'errors') = 'array'
              AND err.error_text LIKE 'Instrument not found for pdno=%'
              AND i.instrument_id IS NULL
            GROUP BY substring(err.error_text FROM 'pdno=([0-9A-Z]+)')
        ),
        unioned AS (
            SELECT * FROM recent_external
            UNION ALL
            SELECT * FROM recent_fills
            UNION ALL
            SELECT * FROM recent_snapshot_errors
        )
        SELECT
            symbol,
            ARRAY_AGG(source_name ORDER BY source_name) AS sources,
            SUM(occurrence_count)::int AS occurrence_count,
            MAX(latest_observed_at) AS latest_observed_at
        FROM unioned
        WHERE symbol IS NOT NULL
          AND symbol <> ''
        GROUP BY symbol
        ORDER BY MAX(latest_observed_at) DESC, symbol ASC
        """
        ,
        lookback_days,
    )
    return [
        MappingGap(
            symbol=row["symbol"],
            sources=tuple(row["sources"]),
            occurrence_count=row["occurrence_count"],
            latest_observed_at=row["latest_observed_at"],
        )
        for row in rows
    ]


async def _seed_placeholders(
    repo: InstrumentRepository,
    gaps: list[MappingGap],
    *,
    dry_run: bool,
    market_code: str,
    asset_class: str,
    currency: str,
    source_tag: str,
) -> SeedCounters:
    inserted = 0
    skipped_existing = 0
    for gap in gaps:
        existing = await repo.get_by_symbol_any_market(gap.symbol)
        if existing is not None:
            skipped_existing += 1
            logger.info(
                "SKIP existing instrument symbol=%s market=%s name=%s",
                existing.symbol,
                existing.market_code,
                existing.name,
            )
            continue
        placeholder = _build_placeholder_instrument(
            gap,
            market_code=market_code,
            asset_class=asset_class,
            currency=currency,
            source_tag=source_tag,
        )
        inserted += 1
        logger.info(
            "PLACEHOLDER %s/%s sources=%s count=%d latest=%s",
            placeholder.market_code,
            placeholder.symbol,
            ",".join(gap.sources),
            gap.occurrence_count,
            gap.latest_observed_at.isoformat(),
        )
        if not dry_run:
            await repo.upsert_by_symbol(placeholder)
    return SeedCounters(inserted=inserted, skipped_existing=skipped_existing)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed inactive placeholder instruments from recent mapping gaps.",
    )
    parser.add_argument("--lookback-days", type=int, default=14)
    parser.add_argument("--apply", action="store_true", help="Persist placeholder rows.")
    parser.add_argument("--default-market-code", default="KRX")
    parser.add_argument("--default-asset-class", default="kr_stock")
    parser.add_argument("--default-currency", default="KRW")
    parser.add_argument("--source-tag", default="mapping_gap_placeholder")
    parser.add_argument(
        "--allow-intraday-apply",
        action="store_true",
        help="Override the default policy that blocks --apply during trading-day intraday hours.",
    )
    parser.add_argument(
        "--ignore-update-policy",
        action="store_true",
        help="Bypass the instrument master update policy gate entirely (manual emergency use only).",
    )
    parser.add_argument(
        "--now-kst",
        default=None,
        help="Testing hook: override current KST timestamp (ISO-8601).",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    await _enforce_update_policy(args)
    await create_pool()
    try:
        tx = TransactionManager()
        await tx.__aenter__()
        try:
            gaps = await _query_mapping_gaps(tx, lookback_days=args.lookback_days)
            logger.info("Found %d unmapped symbols across runtime tables", len(gaps))
            repo: InstrumentRepository = PostgresInstrumentRepository(tx)
            counters = await _seed_placeholders(
                repo,
                gaps,
                dry_run=not args.apply,
                market_code=args.default_market_code,
                asset_class=args.default_asset_class,
                currency=args.default_currency,
                source_tag=args.source_tag,
            )
            logger.info(
                "Summary: inserted=%d skipped_existing=%d",
                counters.inserted,
                counters.skipped_existing,
            )
            if args.apply:
                await tx.commit()
                logger.info("Placeholder instruments committed to database.")
            else:
                logger.info("Dry-run complete. Use --apply to persist placeholders.")
        except BaseException:
            await tx.rollback()
            raise
        finally:
            await tx.__aexit__(None, None, None)
    finally:
        await close_pool()
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run(_parse_args())))


if __name__ == "__main__":
    main()
