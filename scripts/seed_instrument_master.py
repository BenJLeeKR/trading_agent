#!/usr/bin/env python3
"""Seed the ``trading.instruments`` table with KRX instrument data.

Supports two data sources:
  1. Built-in ``SEED_INSTRUMENTS`` tuple (10 symbols, for quick testing).
  2. External CSV file via ``--csv <path>`` (e.g. KOSPI200 full list).

The script uses deterministic UUIDs (``uuid5``) so repeated runs are
idempotent.

Usage
-----
    # Preview with built-in seed (default)
    python3 scripts/seed_instrument_master.py

    # Preview with external CSV
    python3 scripts/seed_instrument_master.py --csv data/kospi200.csv

    # Apply changes to the database
    python3 scripts/seed_instrument_master.py --csv data/kospi200.csv --apply

CSV format
----------
Required columns: ``symbol``, ``name``
Optional columns: ``market_code`` (default: KRX), ``asset_class`` (default: kr_stock),
                   ``currency`` (default: KRW), ``tick_size`` (default: 100),
                   ``lot_size`` (default: 1), ``is_active`` (default: TRUE)

See ``reference_docs/kospi200_instruments.csv`` for an example.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
import uuid
from decimal import Decimal
from typing import Sequence

from agent_trading.db.connection import DatabaseConfig, create_pool, close_pool
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import InstrumentEntity
from agent_trading.repositories.postgres.instruments import (
    PostgresInstrumentRepository,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("seed_instrument_master")

# ── Built-in seed data (10 symbols, for quick testing) ──────────────────────
# (symbol, market_code, asset_class, currency, name, tick_size, lot_size, is_active)

SEED_INSTRUMENTS: Sequence[tuple[str, str, str, str, str, str, str, bool]] = (
    ("005930", "KRX", "kr_stock", "KRW", "삼성전자", "100", "1", True),
    ("000660", "KRX", "kr_stock", "KRW", "SK하이닉스", "100", "1", True),
    ("035420", "KRX", "kr_stock", "KRW", "NAVER", "100", "1", True),
    ("005380", "KRX", "kr_stock", "KRW", "현대차", "100", "1", True),
    ("051910", "KRX", "kr_stock", "KRW", "LG화학", "1000", "1", True),
    ("207940", "KRX", "kr_stock", "KRW", "삼성바이오로직스", "1000", "1", True),
    ("000720", "KRX", "kr_stock", "KRW", "현대건설", "100", "1", True),
    ("030200", "KRX", "kr_stock", "KRW", "KT", "100", "1", True),
    ("018670", "KRX", "kr_stock", "KRW", "SK가스", "100", "1", True),
    ("402340", "KRX", "kr_stock", "KRW", "SK바이오팜", "100", "1", True),
)


def _make_instrument_id(symbol: str) -> uuid.UUID:
    """Deterministic UUID for a KRX symbol."""
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"krx/{symbol}")


def _make_instrument(
    symbol: str,
    market_code: str,
    asset_class: str,
    currency: str,
    name: str,
    tick_size_str: str,
    lot_size_str: str,
    is_active: bool,
) -> InstrumentEntity:
    """Build an ``InstrumentEntity`` from seed tuple values."""
    return InstrumentEntity(
        instrument_id=_make_instrument_id(symbol),
        symbol=symbol,
        market_code=market_code,
        asset_class=asset_class,
        currency=currency,
        name=name,
        tick_size=Decimal(tick_size_str),
        lot_size=Decimal(lot_size_str),
        is_active=is_active,
        metadata={},
    )


# ── Action labels ────────────────────────────────────────────────────────────

_ACTION_INSERT = "INSERT"
_ACTION_UPDATE = "UPDATE"
_ACTION_SKIP = "SKIP"


def _classify_action(
    existing: InstrumentEntity | None,
    seed: InstrumentEntity,
) -> tuple[str, list[str] | None]:
    """Determine the action for a seed instrument.

    Returns ``(action, diff_fields)`` where ``diff_fields`` is a list of
    changed field names (or ``None`` for INSERT / no diff).
    """
    if existing is None:
        return _ACTION_INSERT, None

    diffs: list[str] = []
    # Compare mutable fields only (instrument_id, created_at, updated_at are
    # managed by the database / repository).
    for field in ("name", "asset_class", "currency", "tick_size", "lot_size", "is_active"):
        existing_val = getattr(existing, field)
        seed_val = getattr(seed, field)
        if existing_val != seed_val:
            diffs.append(field)

    if not diffs:
        return _ACTION_SKIP, None

    return _ACTION_UPDATE, diffs


def _format_diff(
    action: str,
    seed: InstrumentEntity,
    existing: InstrumentEntity | None,
    diff_fields: list[str] | None,
) -> str:
    """Format a human-readable diff line."""
    symbol = seed.symbol
    name = seed.name
    if action == _ACTION_INSERT:
        return f"  {_ACTION_INSERT:8s} {symbol:>6s} {name}"

    if action == _ACTION_SKIP:
        return f"  {_ACTION_SKIP:8s} {symbol:>6s} {name}  (no changes)"

    # UPDATE: show changed fields
    assert diff_fields is not None
    assert existing is not None
    parts: list[str] = []
    for field in diff_fields:
        old_val = getattr(existing, field)
        new_val = getattr(seed, field)
        parts.append(f"{field}: {old_val!r} → {new_val!r}")
    return f"  {_ACTION_UPDATE:8s} {symbol:>6s} {name}  ({'; '.join(parts)})"


# ── CSV loader ────────────────────────────────────────────────────────────────


def _load_csv(path: str) -> Sequence[tuple[str, str, str, str, str, str, str, bool]]:
    """Load seed instruments from a CSV file.

    Expected columns (case-insensitive header):
      ``symbol`` (required), ``name`` (required),
      ``market_code`` (default: KRX), ``asset_class`` (default: kr_stock),
      ``currency`` (default: KRW), ``tick_size`` (default: 100),
      ``lot_size`` (default: 1), ``is_active`` (default: TRUE)

    Returns the same tuple format as ``SEED_INSTRUMENTS``.
    """
    rows: list[tuple[str, str, str, str, str, str, str, bool]] = []

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"Empty CSV file: {path}")

        # Normalise header names to lowercase
        norm_fieldnames = {h.strip().lower(): h for h in reader.fieldnames}

        for line_no, record in enumerate(reader, start=2):  # 1-indexed, skip header
            try:
                symbol = record[norm_fieldnames["symbol"]].strip()
                name = record[norm_fieldnames["name"]].strip()
            except KeyError as exc:
                raise ValueError(
                    f"Missing required column '{exc}' in CSV (line {line_no})"
                ) from exc

            market_code = record.get(norm_fieldnames.get("market_code", ""), "KRX").strip() or "KRX"
            asset_class = record.get(norm_fieldnames.get("asset_class", ""), "kr_stock").strip() or "kr_stock"
            currency = record.get(norm_fieldnames.get("currency", ""), "KRW").strip() or "KRW"
            tick_size = record.get(norm_fieldnames.get("tick_size", ""), "100").strip() or "100"
            lot_size = record.get(norm_fieldnames.get("lot_size", ""), "1").strip() or "1"

            raw_active = record.get(norm_fieldnames.get("is_active", ""), "TRUE").strip().upper()
            is_active = raw_active in ("TRUE", "1", "YES", "Y")

            rows.append((symbol, market_code, asset_class, currency, name, tick_size, lot_size, is_active))

    logger.info("Loaded %d instruments from %s", len(rows), path)
    return rows


# ── Core logic ───────────────────────────────────────────────────────────────


async def _seed_instruments(
    repo: InstrumentRepository,
    instruments: Sequence[tuple[str, str, str, str, str, str, str, bool]],
    dry_run: bool,
) -> tuple[int, int, int]:
    """Run the seed logic against a given repository.

    Args:
        repo: Instrument repository to upsert into.
        instruments: Sequence of ``(symbol, market_code, asset_class, currency,
                     name, tick_size, lot_size, is_active)`` tuples.
        dry_run: If True, only log what would happen; do not write.

    Returns ``(inserted, updated, skipped)``.
    """
    inserted = 0
    updated = 0
    skipped = 0

    for row in instruments:
        seed = _make_instrument(*row)
        existing = await repo.get_by_symbol(seed.symbol, seed.market_code)
        action, diff_fields = _classify_action(existing, seed)

        line = _format_diff(action, seed, existing, diff_fields)
        logger.info(line)

        if action == _ACTION_INSERT:
            inserted += 1
            if not dry_run:
                await repo.upsert_by_symbol(seed)
        elif action == _ACTION_UPDATE:
            updated += 1
            if not dry_run:
                await repo.upsert_by_symbol(seed)
        else:
            skipped += 1

    return inserted, updated, skipped


async def _run(
    dry_run: bool,
    csv_path: str | None = None,
) -> int:
    """Execute the seed.  Returns 0 on success, 1 on error."""
    # Load instruments
    if csv_path:
        instruments = _load_csv(csv_path)
    else:
        instruments = SEED_INSTRUMENTS

    await create_pool()
    try:
        tx = TransactionManager()
        await tx.__aenter__()
        try:
            repo: InstrumentRepository = PostgresInstrumentRepository(tx)

            logger.info(
                "=== KRX Instrument Master Seed (%s) ===",
                "DRY-RUN" if dry_run else "APPLY",
            )
            logger.info("Total seed instruments: %d", len(instruments))

            inserted, updated, skipped = await _seed_instruments(repo, instruments, dry_run)

            # Summary
            logger.info("=" * 50)
            logger.info("Summary: %d inserted, %d updated, %d skipped", inserted, updated, skipped)
            logger.info("Total:   %d", inserted + updated + skipped)

            if not dry_run:
                await tx.commit()
                logger.info("Changes committed to database.")
            else:
                logger.info("Dry-run complete.  Use --apply to persist changes.")

        except BaseException:
            await tx.rollback()
            raise
        finally:
            await tx.__aexit__(None, None, None)
    finally:
        await close_pool()
    return 0


# ── CLI ──────────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed trading.instruments with KRX instrument data.",
    )
    parser.add_argument(
        "--csv",
        type=str,
        default=None,
        help="Path to a CSV file with instrument data (overrides built-in seed).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Preview changes without writing to the database (default).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes to the database.  Overrides --dry-run.",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = _parse_args()
    # --apply overrides --dry-run
    dry_run = not args.apply
    exit_code = asyncio.run(_run(dry_run=dry_run, csv_path=args.csv))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
