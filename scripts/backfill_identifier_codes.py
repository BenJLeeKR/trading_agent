#!/usr/bin/env python3
"""One-off script to backfill ``broker_account_code`` and ``account_code``.

These columns were added as nullable in migration ``0010``.  Existing rows
still have ``NULL``, so the Admin UI shows ``—`` for Broker Code / Account
Code.  This script fills them in using deterministic rules.

Usage
-----
    python scripts/backfill_identifier_codes.py          # real UPDATE
    python scripts/backfill_identifier_codes.py --dry-run # preview only

Rules
-----
broker_account_code:
    {BROKER_SHORT}-{ENV}-****{ACCOUNT_REF_LAST4}

    BROKER_SHORT is resolved via an explicit mapping:
        KoreaInvestment → KIS
        kis             → KIS
        (others)        → broker_name[:4].upper()

    ACCOUNT_REF_LAST4 is the last 4 digits extracted from account_ref.
    Non-digit characters are stripped first.  If no digits remain,
    fall back to '0000'.  If fewer than 4 digits, left-pad with zeros.

account_code:
    {CLIENT_CODE}-{ENV}-{ALIAS_FIRST_WORD}

    ALIAS_FIRST_WORD is the first word of account_alias after stripping
    non-alphanumeric characters (excluding spaces).  Uppercased.

Both updates are idempotent (``WHERE … IS NULL``).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from agent_trading.db.connection import DatabaseConfig, create_pool, close_pool
from agent_trading.db.transaction import TransactionManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill_identifier_codes")


# ── SQL templates ──────────────────────────────────────────────────────────

_BROKER_ACCOUNT_CODE_SQL = """
UPDATE trading.broker_accounts
SET broker_account_code =
    CASE
        WHEN LOWER(broker_name) = 'koreainvestment' THEN 'KIS'
        ELSE UPPER(LEFT(broker_name, 4))
    END
    || '-' || UPPER(environment)
    || '-****' ||
    CASE
        -- Extract only digits, then take last 4 (or pad)
        WHEN account_ref ~ '\\d'
        THEN
            CASE
                WHEN LENGTH(REGEXP_REPLACE(account_ref, '[^0-9]', '', 'g')) >= 4
                THEN RIGHT(REGEXP_REPLACE(account_ref, '[^0-9]', '', 'g'), 4)
                ELSE LPAD(REGEXP_REPLACE(account_ref, '[^0-9]', '', 'g'), 4, '0')
            END
        ELSE '0000'
    END
WHERE broker_account_code IS NULL
"""

_ACCOUNT_CODE_SQL = """
UPDATE trading.accounts a
SET account_code =
    c.client_code || '-'
    || UPPER(a.environment) || '-'
    || UPPER(SPLIT_PART(REGEXP_REPLACE(a.account_alias, '[^a-zA-Z\\uAC00-\\uD7AF ]', '', 'g'), ' ', 1))
FROM trading.clients c
WHERE a.client_id = c.client_id
  AND a.account_code IS NULL
"""

# ── account_masked: derive from broker_account_ref ─────────────────────────
# ``account_masked`` should reflect the last 4 digits of the authoritative
# ``broker_account_ref``, not the KIS account number (which is an auth
# parameter, not an identity).  This SQL updates rows where ``account_masked``
# is NULL or inconsistent with ``broker_account_ref``.
#
# Rules:
#   - broker_account_ref has ≥4 digits → "****" + last 4 digits
#   - broker_account_ref has <4 digits → "****" + zero-padded to 4
#   - broker_account_ref is NULL/empty/no digits → "****0000"
#
# Idempotent: only rows where ``account_masked IS DISTINCT FROM`` the
# computed value are touched.

_ACCOUNT_MASKED_SQL = """
UPDATE trading.accounts a
SET account_masked = '****' ||
    CASE
        WHEN ba.account_ref IS NULL OR ba.account_ref = '' THEN '0000'
        WHEN ba.account_ref !~ '\\d' THEN '0000'
        WHEN LENGTH(REGEXP_REPLACE(ba.account_ref, '[^0-9]', '', 'g')) >= 4
        THEN RIGHT(REGEXP_REPLACE(ba.account_ref, '[^0-9]', '', 'g'), 4)
        ELSE LPAD(REGEXP_REPLACE(ba.account_ref, '[^0-9]', '', 'g'), 4, '0')
    END
FROM trading.broker_accounts ba
WHERE a.broker_account_id = ba.broker_account_id
  AND (a.account_masked IS NULL
       OR a.account_masked IS DISTINCT FROM
          ('****' ||
          CASE
              WHEN ba.account_ref IS NULL OR ba.account_ref = '' THEN '0000'
              WHEN ba.account_ref !~ '\\d' THEN '0000'
              WHEN LENGTH(REGEXP_REPLACE(ba.account_ref, '[^0-9]', '', 'g')) >= 4
              THEN RIGHT(REGEXP_REPLACE(ba.account_ref, '[^0-9]', '', 'g'), 4)
              ELSE LPAD(REGEXP_REPLACE(ba.account_ref, '[^0-9]', '', 'g'), 4, '0')
          END))
"""


# ── Core logic ─────────────────────────────────────────────────────────────

async def backfill_broker_account_codes(tx: TransactionManager, dry_run: bool) -> int:
    """Backfill ``broker_account_code`` for rows where it is NULL.

    Returns the number of rows that *would be* updated (dry-run) or *were*
    updated (real run).
    """
    if dry_run:
        row = await tx.connection.fetchrow(
            "SELECT count(*) AS cnt FROM trading.broker_accounts WHERE broker_account_code IS NULL"
        )
        count = row["cnt"] if row else 0
        logger.info("[DRY-RUN] broker_accounts to update: %d", count)
        return count

    result = await tx.connection.execute(_BROKER_ACCOUNT_CODE_SQL)
    # result looks like "UPDATE 3"
    count = int(result.split()[-1]) if result else 0
    logger.info("Updated broker_accounts: %d", count)
    return count


async def backfill_account_codes(tx: TransactionManager, dry_run: bool) -> int:
    """Backfill ``account_code`` for rows where it is NULL.

    Returns the number of rows that *would be* updated (dry-run) or *were*
    updated (real run).
    """
    if dry_run:
        row = await tx.connection.fetchrow(
            "SELECT count(*) AS cnt FROM trading.accounts WHERE account_code IS NULL"
        )
        count = row["cnt"] if row else 0
        logger.info("[DRY-RUN] accounts to update: %d", count)
        return count

    result = await tx.connection.execute(_ACCOUNT_CODE_SQL)
    count = int(result.split()[-1]) if result else 0
    logger.info("Updated accounts: %d", count)
    return count


async def backfill_account_masked(tx: TransactionManager, dry_run: bool) -> int:
    """Backfill ``account_masked`` from ``broker_account_ref``.

    Only touches rows where ``account_masked`` is NULL or inconsistent
    with the authoritative source (``broker_account_ref`` last 4 digits).

    Returns the number of rows that *would be* updated (dry-run) or *were*
    updated (real run).
    """
    if dry_run:
        row = await tx.connection.fetchrow(
            "SELECT count(*) AS cnt FROM trading.accounts a "
            "JOIN trading.broker_accounts ba ON a.broker_account_id = ba.broker_account_id "
            "WHERE a.account_masked IS NULL "
            "   OR a.account_masked IS DISTINCT FROM "
            "      ('****' || "
            "      CASE "
            "          WHEN ba.account_ref IS NULL OR ba.account_ref = '' THEN '0000' "
            "          WHEN ba.account_ref !~ '\\d' THEN '0000' "
            "          WHEN LENGTH(REGEXP_REPLACE(ba.account_ref, '[^0-9]', '', 'g')) >= 4 "
            "          THEN RIGHT(REGEXP_REPLACE(ba.account_ref, '[^0-9]', '', 'g'), 4) "
            "          ELSE LPAD(REGEXP_REPLACE(ba.account_ref, '[^0-9]', '', 'g'), 4, '0') "
            "      END)"
        )
        count = row["cnt"] if row else 0
        logger.info("[DRY-RUN] accounts.account_masked to update: %d", count)
        return count

    result = await tx.connection.execute(_ACCOUNT_MASKED_SQL)
    count = int(result.split()[-1]) if result else 0
    logger.info("Updated accounts.account_masked: %d", count)
    return count


async def _run(dry_run: bool) -> int:
    """Execute the backfill.  Returns 0 on success, 1 on error."""
    await create_pool()
    try:
        tx = TransactionManager()
        await tx.__aenter__()
        try:
            broker_count = await backfill_broker_account_codes(tx, dry_run)
            account_count = await backfill_account_codes(tx, dry_run)
            masked_count = await backfill_account_masked(tx, dry_run)

            if not dry_run:
                await tx.commit()
                logger.info(
                    "Backfill complete: %d broker_accounts, %d accounts, %d account_masked",
                    broker_count,
                    account_count,
                    masked_count,
                )
            else:
                logger.info(
                    "Dry-run complete: %d broker_accounts, %d accounts, %d account_masked would be updated",
                    broker_count,
                    account_count,
                    masked_count,
                )
        except BaseException:
            await tx.rollback()
            raise
        finally:
            await tx.__aexit__(None, None, None)
    finally:
        await close_pool()
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill broker_account_code and account_code for existing rows."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the number of rows that would be updated without making changes.",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = _parse_args()
    exit_code = asyncio.run(_run(dry_run=args.dry_run))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
