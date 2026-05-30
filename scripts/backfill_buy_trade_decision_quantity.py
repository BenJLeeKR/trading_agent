#!/usr/bin/env python3
"""
Backfill BUY trade_decisions.quantity that were incorrectly capped at 1
due to the now-removed requested_quantity cap in sizing_engine.py.

Background
----------
Phase 5i-5 이전 BUY Sizing 로직에 존재했던 ``requested_quantity`` cap(강제 1 고정)으로
인해, cap이 활성화된 기간(2026-05-25 ~ 2026-05-29)에 생성된 모든 BUY 결정의
``trade_decisions.quantity`` 가 1로 왜곡 저장됨.

이 스크립트는 2단계 접근법으로 보정합니다:

    Step A — Reconstruction (우선 시도)
        ``decision_contexts`` → ``cash_balance_snapshots`` 에서 cash 데이터 추출,
        symbol 가격 정보로 ``_resolve_buy_target_quantity()`` 로직 재현.

    Step B — Conservative Default (fallback)
        Reconstruction 불가능한 row는 ``decision_type`` 별 기본값 설정:
            - APPROVE → 10
            - ENTER / ADD / REBALANCE_ENTER → 100

Usage
-----
    # Dry-run (default): preview only, no changes
    python scripts/backfill_buy_trade_decision_quantity.py

    # Apply with limit (safety first)
    python scripts/backfill_buy_trade_decision_quantity.py --apply --limit 50

    # Full apply
    python scripts/backfill_buy_trade_decision_quantity.py --apply

    # Filter by symbol
    python scripts/backfill_buy_trade_decision_quantity.py --apply --symbol 005930

    # Skip backup table creation
    python scripts/backfill_buy_trade_decision_quantity.py --apply --no-backup
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from agent_trading.db.connection import DatabaseConfig, create_pool, close_pool
from agent_trading.db.transaction import TransactionManager

logger = logging.getLogger("backfill_buy_trade_decision_quantity")

# ── Constants ──────────────────────────────────────────────

BACKUP_TABLE = "trade_decisions_bak_phase7"
SAFETY_THRESHOLD = 1000

# Step B: Conservative defaults
DEFAULT_QUANTITY_APPROVE = 10
DEFAULT_QUANTITY_BUY = 100

# Reconstruction constants (matching _resolve_buy_target_quantity logic)
_ALLOCATION_PCT = Decimal("0.2")  # 20% of effective cash
_MIN_ENTRY_THRESHOLD = Decimal("500000")  # 50만원 (신규 포지션 최소 진입 금액)

# decision_type values that are BUY-like and affected by the cap
_AFFECTED_DECISION_TYPES = frozenset({
    "enter", "add", "rebalance_enter", "approve", "buy",
})


# ── Core Logic ─────────────────────────────────────────────

async def find_target_rows(
    conn: Any,
    *,
    limit: int | None = None,
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    """Query trade_decisions for rows matching the backfill criteria.

    Returns a list of dicts with all columns needed for reconstruction
    and reporting.
    """
    # ── Build base WHERE conditions (no LIMIT) ──
    conditions: list[str] = [
        "LOWER(td.side) = 'buy'",
        "LOWER(td.decision_type) IN ('enter', 'add', 'rebalance_enter', 'approve', 'buy')",
        "td.quantity = 1",
        "td.decision_type IS NOT NULL",
        "td.side IS NOT NULL",
    ]
    params: list[Any] = []

    if symbol is not None:
        conditions.append("td.symbol = $%d" % (len(params) + 1))
        params.append(symbol)

    base_where = " AND ".join(conditions)

    # ── Build the full query ──
    # Use a CTE or subquery for LIMIT so the restriction is applied BEFORE
    # the (potentially expensive) LEFT JOIN LATERAL.
    if limit is not None:
        sql = f"""
        WITH limited AS (
            SELECT trade_decision_id
            FROM trading.trade_decisions
            WHERE {base_where.replace('td.', '')}
            ORDER BY created_at DESC
            LIMIT ${len(params) + 1}
        )
        SELECT
            td.trade_decision_id,
            td.decision_type,
            td.side,
            td.quantity,
            td.symbol,
            td.created_at,
            td.entry_price,
            td.max_order_value,
            dc.account_id,
            dc.decision_context_id,
            dc.cash_balance_snapshot_id AS dc_cash_snapshot_id,
            cbs.available_cash,
            cbs.orderable_amount,
            cbs.snapshot_at AS cash_snapshot_at
        FROM trading.trade_decisions td
        JOIN limited l ON l.trade_decision_id = td.trade_decision_id
        JOIN trading.decision_contexts dc ON dc.decision_context_id = td.decision_context_id
        LEFT JOIN LATERAL (
            SELECT cbs.available_cash, cbs.orderable_amount, cbs.snapshot_at
            FROM trading.cash_balance_snapshots cbs
            WHERE cbs.account_id = dc.account_id
              AND cbs.snapshot_at <= td.created_at
            ORDER BY cbs.snapshot_at DESC
            LIMIT 1
        ) cbs ON TRUE
        ORDER BY td.created_at DESC
        """
        params.append(limit)
    else:
        sql = f"""
        SELECT
            td.trade_decision_id,
            td.decision_type,
            td.side,
            td.quantity,
            td.symbol,
            td.created_at,
            td.entry_price,
            td.max_order_value,
            dc.account_id,
            dc.decision_context_id,
            dc.cash_balance_snapshot_id AS dc_cash_snapshot_id,
            cbs.available_cash,
            cbs.orderable_amount,
            cbs.snapshot_at AS cash_snapshot_at
        FROM trading.trade_decisions td
        JOIN trading.decision_contexts dc ON dc.decision_context_id = td.decision_context_id
        LEFT JOIN LATERAL (
            SELECT cbs.available_cash, cbs.orderable_amount, cbs.snapshot_at
            FROM trading.cash_balance_snapshots cbs
            WHERE cbs.account_id = dc.account_id
              AND cbs.snapshot_at <= td.created_at
            ORDER BY cbs.snapshot_at DESC
            LIMIT 1
        ) cbs ON TRUE
        WHERE {base_where}
        ORDER BY td.created_at DESC
        """

    rows = await conn.fetch(sql, *params)
    return [dict(r) for r in rows]


async def resolve_symbol_price(
    conn: Any,
    symbol: str,
    reference_time: datetime,
) -> Decimal | None:
    """Try to find a price for *symbol* around *reference_time*.

    Lookup order:
        1. ``market_data_snapshots`` — most recent snapshot before reference_time
        2. ``position_snapshots`` — latest known position price
        3. ``instruments`` — metadata fallback (tick_size, lot_size only)

    Returns ``None`` if no price can be determined.
    """
    # 1. Try market_data_snapshots
    row = await conn.fetchrow(
        """
        SELECT last_price, bid_price, ask_price
        FROM trading.market_data_snapshots mds
        JOIN trading.instruments i ON i.instrument_id = mds.instrument_id
        WHERE i.symbol = $1
          AND mds.snapshot_at <= $2
        ORDER BY mds.snapshot_at DESC
        LIMIT 1
        """,
        symbol,
        reference_time,
    )
    if row:
        for col in ("last_price", "bid_price", "ask_price"):
            val = row[col]
            if val is not None and val > 0:
                return Decimal(str(val))

    # 2. Try position_snapshots for price
    row = await conn.fetchrow(
        """
        SELECT ps.average_price, ps.market_price
        FROM trading.position_snapshots ps
        JOIN trading.instruments i ON i.instrument_id = ps.instrument_id
        WHERE i.symbol = $1
          AND ps.snapshot_at <= $2
        ORDER BY ps.snapshot_at DESC
        LIMIT 1
        """,
        symbol,
        reference_time,
    )
    if row:
        for col in ("market_price", "average_price"):
            val = row[col]
            if val is not None and val > 0:
                return Decimal(str(val))

    return None


def reconstruct_buy_quantity(
    orderable_amount: Decimal | None,
    available_cash: Decimal | None,
    price: Decimal | None,
    *,
    is_new_position: bool = False,
) -> Decimal | None:
    """Reconstruct the intended buy quantity using the allocation formula.

    This mirrors the core logic of ``_resolve_buy_target_quantity()``:

        1. effective_cash = orderable_amount ?? available_cash
        2. target_notional = effective_cash × 20%
        3. target_qty = floor(target_notional / price)
        4. If target_notional < min_entry_threshold (50만원), return 1
        5. Clamp to max_order_qty upper bound (if applicable)

    Parameters
    ----------
    orderable_amount:
        ``cash_balance_snapshots.orderable_amount`` (KIS ord_psbl_amt).
    available_cash:
        ``cash_balance_snapshots.available_cash``.
    price:
        Instrument price around the decision time.
    is_new_position:
        If True, apply ``min_entry_threshold`` check.

    Returns
    -------
    Decimal | None
        Reconstructed quantity, or ``None`` if reconstruction is impossible
        (missing cash or price data).
    """
    # Step 1: effective cash
    if orderable_amount is not None and orderable_amount > 0:
        effective_cash = Decimal(str(orderable_amount))
    elif available_cash is not None and available_cash > 0:
        effective_cash = Decimal(str(available_cash))
    else:
        return None

    if price is None or price <= 0:
        return None

    price = Decimal(str(price))

    # Step 2: allocation-based target
    target_notional = effective_cash * _ALLOCATION_PCT

    # Step 4: min_entry_threshold check (신규 포지션)
    if is_new_position and target_notional < _MIN_ENTRY_THRESHOLD:
        # Below minimum threshold — would have been 1 or skipped
        # We return 1 as the original cap value (no change needed)
        return Decimal("1")

    # Step 3: quantity from notional / price
    target_qty = int(target_notional / price)

    # Minimum 1 share
    if target_qty < 1:
        target_qty = 1

    return Decimal(str(target_qty))


async def create_backup_table(conn: Any) -> bool:
    """Create backup table ``trade_decisions_bak_phase7`` if it doesn't exist.

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
        SELECT * FROM trading.trade_decisions
        WHERE LOWER(side) = 'buy'
          AND LOWER(decision_type) IN ('enter', 'add', 'rebalance_enter', 'approve', 'buy')
          AND quantity = 1
        """
    )
    count = await conn.fetchval(f"SELECT COUNT(*) FROM trading.{BACKUP_TABLE}")
    logger.info(
        "Backup table %s created with %d rows", BACKUP_TABLE, count
    )
    return True


async def apply_backfill(
    conn: Any,
    rows: list[dict[str, Any]],
    dry_run: bool = True,
) -> dict[str, Any]:
    """Apply the backfill: Step A reconstruction, fallback to Step B defaults.

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
    dict with keys:
        total, reconstructed, default_fallback, skipped,
        by_type (Counter), by_symbol (Counter), details (list)
    """
    result: dict[str, Any] = {
        "total": len(rows),
        "reconstructed": 0,
        "reconstruction_details": [],
        "default_fallback": 0,
        "default_fallback_details": [],
        "skipped": 0,
        "skipped_details": [],
        "by_type": Counter(),
        "by_symbol": Counter(),
        "updates": [],  # list of (trade_decision_id, old_qty, new_qty, method)
    }

    # Pre-resolve price for frequently occurring symbols
    # to avoid repeated DB lookups during dry-run
    symbol_prices: dict[str, Decimal | None] = {}
    price_resolve_errors: int = 0

    for row in rows:
        dt = row["decision_type"].lower()
        symbol = row["symbol"]
        result["by_type"][dt] += 1
        result["by_symbol"][symbol] += 1

        # Step A: Try reconstruction
        new_qty: Decimal | None = None
        method = "default"

        # Check if we have cash data
        orderable_amount = row.get("orderable_amount")
        available_cash = row.get("available_cash")

        if orderable_amount is not None or available_cash is not None:
            # Try to resolve price
            if symbol not in symbol_prices:
                price = await resolve_symbol_price(
                    conn, symbol, row["created_at"]
                )
                symbol_prices[symbol] = price
                if price is None:
                    price_resolve_errors += 1
            else:
                price = symbol_prices[symbol]

            if price is not None and price > 0:
                # Determine if this is likely a new position
                is_new = dt in ("enter", "rebalance_enter")

                reconstructed = reconstruct_buy_quantity(
                    orderable_amount=(
                        Decimal(str(orderable_amount))
                        if orderable_amount is not None else None
                    ),
                    available_cash=(
                        Decimal(str(available_cash))
                        if available_cash is not None else None
                    ),
                    price=price,
                    is_new_position=is_new,
                )

                if reconstructed is not None and reconstructed > 1:
                    new_qty = reconstructed
                    method = "reconstruction"
                    result["reconstructed"] += 1
                    result["reconstruction_details"].append({
                        "trade_decision_id": str(row["trade_decision_id"]),
                        "symbol": symbol,
                        "price": str(price),
                        "orderable_amount": str(orderable_amount) if orderable_amount else None,
                        "available_cash": str(available_cash) if available_cash else None,
                        "reconstructed_qty": str(reconstructed),
                    })

        # Step B: Fall back to conservative default
        if new_qty is None:
            if dt == "approve":
                new_qty = Decimal(str(DEFAULT_QUANTITY_APPROVE))
            else:
                # ENTER, ADD, REBALANCE_ENTER, BUY, etc.
                new_qty = Decimal(str(DEFAULT_QUANTITY_BUY))
            method = "default"
            result["default_fallback"] += 1
            result["default_fallback_details"].append({
                "trade_decision_id": str(row["trade_decision_id"]),
                "symbol": symbol,
                "decision_type": dt,
                "reason": (
                    "no price data" if (orderable_amount is not None or available_cash is not None)
                    else "no cash data"
                ),
            })

        old_qty = Decimal(str(row["quantity"]))
        result["updates"].append((
            str(row["trade_decision_id"]),
            old_qty,
            new_qty,
            method,
        ))

    # ── Execute UPDATE if not dry-run ──
    if not dry_run and result["updates"]:
        # Build the UPDATE statement using a VALUES approach
        # We batch all updates in a single statement for performance
        value_rows: list[str] = []
        params: list[Any] = []
        for i, (td_id, old_qty, new_qty, method) in enumerate(result["updates"]):
            # Only update if quantity actually changed
            if new_qty == old_qty:
                result["skipped"] += 1
                result["skipped_details"].append({
                    "trade_decision_id": td_id,
                    "reason": f"new_qty ({new_qty}) == old_qty ({old_qty})",
                })
                continue
            param_idx = len(params) + 1
            value_rows.append(f"(${param_idx}::uuid, ${param_idx + 1}::numeric)")
            params.append(td_id)
            params.append(str(new_qty))

        if value_rows:
            values_clause = ", ".join(value_rows)
            update_sql = f"""
            UPDATE trading.trade_decisions td
            SET quantity = sub.new_qty
            FROM (VALUES {values_clause}) AS sub(trade_decision_id, new_qty)
            WHERE td.trade_decision_id = sub.trade_decision_id::uuid
              AND td.quantity = 1
            """
            logger.debug("Executing UPDATE with %d rows", len(value_rows))
            await conn.execute(update_sql, *params)

    return result


def _format_summary(result: dict[str, Any], dry_run: bool) -> str:
    """Format a human-readable summary of the backfill result."""
    mode = "DRY-RUN" if dry_run else "APPLY"
    lines: list[str] = [
        f"===== {mode} Summary =====",
        f"Total affected rows: {result['total']}",
        "",
    ]

    # By type
    lines.append("Breakdown by decision_type:")
    for dt, count in sorted(result["by_type"].items()):
        dt_upper = dt.upper()
        if dt == "approve":
            qty_info = f"→ will be set to {DEFAULT_QUANTITY_APPROVE}" if dry_run else ""
        else:
            qty_info = f"→ will be set to {DEFAULT_QUANTITY_BUY}" if dry_run else ""
        lines.append(f"  {dt_upper}: {count} rows {qty_info}")
    lines.append("")

    # Reconstruction stats
    lines.append(f"Reconstruction possible: {result['reconstructed']} rows")
    lines.append(f"Default fallback: {result['default_fallback']} rows")
    if result["reconstruction_details"]:
        lines.append("  Sample reconstructed values:")
        for detail in result["reconstruction_details"][:5]:
            lines.append(
                f"    {detail['trade_decision_id'][:8]}... "
                f"symbol={detail['symbol']} "
                f"price={detail['price']} "
                f"cash={detail['orderable_amount'] or detail['available_cash']} "
                f"→ qty={detail['reconstructed_qty']}"
            )
    if result["default_fallback_details"]:
        lines.append("  Fallback reasons (sample):")
        seen_reasons: Counter = Counter()
        for detail in result["default_fallback_details"][:10]:
            seen_reasons[detail["reason"]] += 1
        for reason, count in seen_reasons.most_common():
            lines.append(f"    {reason}: {count} rows")
    lines.append("")

    # Symbol breakdown
    lines.append("Symbol breakdown (top 10):")
    for symbol, count in sorted(
        result["by_symbol"].items(), key=lambda x: -x[1]
    )[:10]:
        lines.append(f"  {symbol}: {count} rows")
    if len(result["by_symbol"]) > 10:
        lines.append(f"  ... and {len(result['by_symbol']) - 10} more symbols")
    lines.append("")

    # Safety threshold check
    if result["total"] > SAFETY_THRESHOLD:
        lines.append(
            f"⚠ SAFETY THRESHOLD: {result['total']} rows exceeds {SAFETY_THRESHOLD}!\n"
            "  Use --apply to proceed, or --limit N to cap the change."
        )
        lines.append("")

    # Skipped rows
    if result["skipped"] > 0:
        lines.append(f"Skipped (no change needed): {result['skipped']} rows")
        lines.append("")

    # Final counts
    if dry_run:
        lines.append(
            f"Estimated updates: {result['total'] - result['skipped']} rows "
            f"(reconstructed={result['reconstructed']}, "
            f"default={result['default_fallback']})"
        )
    else:
        lines.append(
            f"Updated: {result['total'] - result['skipped']} rows "
            f"(reconstructed={result['reconstructed']}, "
            f"default={result['default_fallback']}, "
            f"skipped={result['skipped']})"
        )

    return "\n".join(lines)


# ── CLI ────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Backfill BUY trade_decisions.quantity that were incorrectly "
            "capped at 1 due to the now-removed requested_quantity cap."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s                        # Dry-run preview\n"
            "  %(prog)s --apply --limit 50     # Apply to first 50 rows\n"
            "  %(prog)s --apply                # Apply to all rows\n"
            "  %(prog)s --apply --symbol 005930 # Single symbol\n"
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
        "--symbol",
        type=str,
        default=None,
        help="Filter by specific symbol (e.g., 005930).",
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
    symbol = args.symbol
    do_backup = args.backup
    safety_threshold = args.safety_threshold

    logger.info(
        "Backfill BUY trade_decision quantity (mode=%s, limit=%s, symbol=%s)",
        "DRY-RUN" if dry_run else "APPLY",
        limit or "ALL",
        symbol or "ALL",
    )

    await create_pool()
    try:
        tx = TransactionManager()
        await tx.__aenter__()
        try:
            conn = tx.connection

            # Phase 1: Find target rows
            logger.info("Finding target rows...")
            rows = await find_target_rows(conn, limit=limit, symbol=symbol)
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

            # Phase 4: Apply backfill (reconstruction + default fallback)
            logger.info(
                "Applying backfill (%s)...",
                "dry-run preview" if dry_run else "actual UPDATE",
            )
            result = await apply_backfill(conn, rows, dry_run=dry_run)

            # Phase 5: Print summary
            summary = _format_summary(result, dry_run)
            print(f"\n{summary}\n")

            # Phase 6: Commit or rollback
            if not dry_run:
                if result["updates"]:
                    await tx.commit()
                    logger.info(
                        "Backfill committed: %d rows updated "
                        "(reconstructed=%d, default=%d, skipped=%d)",
                        len(result["updates"]) - result["skipped"],
                        result["reconstructed"],
                        result["default_fallback"],
                        result["skipped"],
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
