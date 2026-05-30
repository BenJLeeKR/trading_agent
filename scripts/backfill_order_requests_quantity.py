#!/usr/bin/env python3
"""
Backfill order_requests.requested_quantity from trade_decisions.quantity.

Background
----------
Phase 7에서 ``trade_decisions.quantity``는 BUY에 대해 보정(backfill) 완료되었지만,
``order_requests.requested_quantity``는 여전히 왜곡된 값(대부분 1)으로 남아 있음.

이 스크립트는 BUY 주문에 대해 ``order_requests.requested_quantity``를
``trade_decisions.quantity`` 값으로 동기화합니다.

보정 조건
    - BUY 주문만 대상 (SELL은 Phase 7 보정 대상이 아니었음)
    - ``requested_quantity != td.quantity``인 경우만 UPDATE
    - 기간: 2026-05-27 ~ 2026-05-30 (KST)

Usage
-----
    # Dry-run (default): preview only, no changes
    python scripts/backfill_order_requests_quantity.py

    # Apply with safety limit
    python scripts/backfill_order_requests_quantity.py --apply --limit 100

    # Full apply
    python scripts/backfill_order_requests_quantity.py --apply

    # Skip backup table creation
    python scripts/backfill_order_requests_quantity.py --apply --no-backup
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from agent_trading.db.connection import DatabaseConfig, create_pool, close_pool
from agent_trading.db.transaction import TransactionManager

logger = logging.getLogger("backfill_order_requests_quantity")

# ── Constants ──────────────────────────────────────────────

BACKUP_TABLE = "order_requests_bak_phase7b"
SAFETY_THRESHOLD = 500

# Date range for the backfill (KST 2026-05-27 ~ 2026-05-30)
# KST = UTC+9, so KST 2026-05-27 00:00:00 = UTC 2026-05-26 15:00:00
# KST 2026-05-30 00:00:00 = UTC 2026-05-29 15:00:00
_START_DATE = datetime(2026, 5, 26, 15, 0, 0, tzinfo=timezone.utc)  # KST 2026-05-27 00:00:00
_END_DATE = datetime(2026, 5, 29, 15, 0, 0, tzinfo=timezone.utc)    # KST 2026-05-30 00:00:00


# ── Core Logic ─────────────────────────────────────────────


async def find_target_rows(
    conn: Any,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Find order_requests with mismatched requested_quantity vs td.quantity.

    Returns a list of dicts with order details for reporting.
    """
    base_conditions = [
        "or2.requested_quantity != td.quantity",
        "LOWER(or2.side) = 'buy'",
        "or2.created_at >= $1",
        "or2.created_at < $2",
    ]
    base_params: list[Any] = [_START_DATE, _END_DATE]
    base_where = " AND ".join(base_conditions)

    if limit is not None:
        sql = f"""
        SELECT or2.order_request_id,
               or2.requested_quantity AS old_qty,
               td.quantity AS new_qty,
               or2.side,
               td.symbol,
               or2.status,
               or2.created_at
        FROM trading.order_requests or2
        JOIN trading.trade_decisions td ON or2.trade_decision_id = td.trade_decision_id
        WHERE {base_where}
        ORDER BY or2.created_at
        LIMIT ${len(base_params) + 1}
        """
        params = list(base_params) + [limit]
    else:
        sql = f"""
        SELECT or2.order_request_id,
               or2.requested_quantity AS old_qty,
               td.quantity AS new_qty,
               or2.side,
               td.symbol,
               or2.status,
               or2.created_at
        FROM trading.order_requests or2
        JOIN trading.trade_decisions td ON or2.trade_decision_id = td.trade_decision_id
        WHERE {base_where}
        ORDER BY or2.created_at
        """
        params = list(base_params)

    rows = await conn.fetch(sql, *params)
    return [dict(r) for r in rows]


async def create_backup_table(conn: Any) -> bool:
    """Create backup table ``order_requests_bak_phase7b`` if it doesn't exist.

    Returns True if the backup table was created, False if it already existed.
    """
    exists = await conn.fetchval(
        """
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_schema = 'trading'
              AND table_name = $1
        )
        """,
        BACKUP_TABLE,
    )
    if exists:
        logger.info("Backup table %s already exists — skipping creation", BACKUP_TABLE)
        return False

    await conn.execute(
        f"""
        CREATE TABLE trading.{BACKUP_TABLE} AS
        SELECT *
        FROM trading.order_requests
        WHERE created_at >= $1
          AND created_at < $2
        """,
        _START_DATE,
        _END_DATE,
    )
    count = await conn.fetchval(f"SELECT COUNT(*) FROM trading.{BACKUP_TABLE}")
    logger.info("Backup table %s created with %d rows", BACKUP_TABLE, count)
    return True


async def apply_backfill(
    conn: Any,
    rows: list[dict[str, Any]],
    *,
    dry_run: bool,
) -> int:
    """Apply the backfill UPDATE or preview in dry-run mode.

    Parameters
    ----------
    conn:
        Database connection (inside a transaction).
    rows:
        Target rows from ``find_target_rows()``.
    dry_run:
        If True, only preview; if False, execute UPDATE.

    Returns
    -------
    int
        Number of rows that would be / were updated.
    """
    if dry_run:
        logger.info("DRY-RUN: Would update %d rows", len(rows))
        for r in rows[:10]:
            logger.info(
                "  %s: qty %s → %s (%s %s, status=%s)",
                r["order_request_id"],
                r["old_qty"],
                r["new_qty"],
                r["side"],
                r["symbol"],
                r["status"],
            )
        if len(rows) > 10:
            logger.info("  ... and %d more rows", len(rows) - 10)
        return len(rows)

    result = await conn.execute(
        """
        UPDATE trading.order_requests or2
        SET requested_quantity = td.quantity
        FROM trading.trade_decisions td
        WHERE or2.trade_decision_id = td.trade_decision_id
          AND or2.requested_quantity != td.quantity
          AND LOWER(or2.side) = 'buy'
          AND or2.created_at >= $1
          AND or2.created_at < $2
        """,
        _START_DATE,
        _END_DATE,
    )
    # Parse "UPDATE N" result
    count = int(result.split()[-1]) if result.startswith("UPDATE") else 0
    return count


async def verify(conn: Any) -> dict[str, Any]:
    """Verify the backfill result by checking remaining mismatches."""
    remaining = await conn.fetchval(
        """
        SELECT COUNT(*)
        FROM trading.order_requests or2
        JOIN trading.trade_decisions td ON or2.trade_decision_id = td.trade_decision_id
        WHERE or2.requested_quantity != td.quantity
          AND LOWER(or2.side) = 'buy'
          AND or2.created_at >= $1
          AND or2.created_at < $2
        """,
        _START_DATE,
        _END_DATE,
    )
    return {"remaining_mismatch": remaining}


def _format_summary(
    target_count: int,
    updated_count: int,
    verify_result: dict[str, Any],
    dry_run: bool,
) -> str:
    """Format a human-readable summary of the backfill result."""
    mode = "DRY-RUN" if dry_run else "APPLY"
    lines: list[str] = [
        f"===== {mode} Summary =====",
        f"Target rows (mismatch): {target_count}",
        f"Updated rows: {updated_count}",
        "",
    ]

    if not dry_run:
        remaining = verify_result.get("remaining_mismatch", -1)
        lines.append(f"Remaining mismatch after update: {remaining}")
        if remaining == 0:
            lines.append("✅ All BUY order_requests.requested_quantity are now synchronized.")
        else:
            lines.append(f"⚠ {remaining} rows still have mismatched quantities.")
        lines.append("")

    # Safety threshold info
    if target_count > SAFETY_THRESHOLD:
        lines.append(
            f"⚠ SAFETY THRESHOLD: {target_count} rows exceeds {SAFETY_THRESHOLD}!\n"
            "  Use --apply to proceed, or --limit N to cap the change."
        )
        lines.append("")

    lines.append(f"Backup table: {BACKUP_TABLE}")

    return "\n".join(lines)


# ── CLI ────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Backfill order_requests.requested_quantity from "
            "trade_decisions.quantity for BUY orders."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s                        # Dry-run preview\n"
            "  %(prog)s --apply --limit 100    # Apply to first 100 rows\n"
            "  %(prog)s --apply                # Apply to all rows\n"
            "  %(prog)s --apply --no-backup    # Apply without backup\n"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Preview changes without applying (default).",
    )
    parser.add_argument(
        "--apply",
        action="store_false",
        dest="dry_run",
        help="Actually apply the backfill updates.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of rows to process.",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        default=True,
        help="Create backup table before applying updates (default: True).",
    )
    parser.add_argument(
        "--no-backup",
        action="store_false",
        dest="backup",
        help="Skip backup table creation.",
    )
    parser.add_argument(
        "--safety-threshold",
        type=int,
        default=SAFETY_THRESHOLD,
        help=f"Maximum rows allowed before aborting (default: {SAFETY_THRESHOLD}).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args(argv)


# ── Main entry point ───────────────────────────────────────


async def _run(args: argparse.Namespace) -> int:
    """Execute the backfill. Returns 0 on success, 1 on error/abort."""
    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    dry_run = args.dry_run
    limit = args.limit
    do_backup = args.backup
    safety_threshold = args.safety_threshold

    logger.info(
        "Backfill order_requests.requested_quantity (mode=%s, limit=%s)",
        "DRY-RUN" if dry_run else "APPLY",
        limit or "ALL",
    )

    await create_pool()
    try:
        tx = TransactionManager()
        await tx.__aenter__()
        try:
            conn = tx.connection

            # Phase 1: Find target rows
            logger.info("Finding target rows...")
            rows = await find_target_rows(conn, limit=limit)
            logger.info("Found %d target rows", len(rows))

            if not rows:
                logger.info("No rows to process.")
                await tx.rollback()
                print("No rows match the backfill criteria.")
                return 0

            # Phase 2: Safety threshold check
            if len(rows) > safety_threshold:
                msg = (
                    f"ABORTING: {len(rows)} rows exceeds safety threshold "
                    f"({safety_threshold}). Use --safety-threshold to override."
                )
                logger.error(msg)
                await tx.rollback()
                print(f"\n{msg}\n")
                return 1

            # Phase 3: Create backup table (only in --apply mode)
            if not dry_run and do_backup:
                logger.info("Creating backup table %s...", BACKUP_TABLE)
                await create_backup_table(conn)

            # Phase 4: Apply backfill
            logger.info(
                "Applying backfill (%s)...",
                "dry-run preview" if dry_run else "actual UPDATE",
            )
            updated = await apply_backfill(conn, rows, dry_run=dry_run)

            # Phase 5: Verify
            verify_result = await verify(conn) if not dry_run else {}

            # Phase 6: Print summary
            summary = _format_summary(len(rows), updated, verify_result, dry_run)
            print(f"\n{summary}\n")

            # Phase 7: Commit or rollback
            if not dry_run:
                if updated > 0:
                    await tx.commit()
                    logger.info(
                        "Backfill committed: %d rows updated, "
                        "remaining mismatch: %d",
                        updated,
                        verify_result.get("remaining_mismatch", -1),
                    )
                else:
                    await tx.rollback()
                    logger.info("No updates to apply — rolled back.")
            else:
                await tx.rollback()
                logger.info("Dry-run complete — no changes made.")

        except BaseException:
            logger.exception("Error during backfill — rolling back")
            await tx.rollback()
            raise
        finally:
            await tx.__aexit__(None, None, None)

    finally:
        await close_pool()

    return 0


def main() -> None:
    args = parse_args()
    exit_code = asyncio.run(_run(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
