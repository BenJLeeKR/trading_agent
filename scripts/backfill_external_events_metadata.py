#!/usr/bin/env python3
"""One-off script to backfill ``metadata`` for existing ``external_events`` rows.

OpenDART 이벤트의 ``event_type`` prefix에서 ``corp_cls``를 추출하여
``metadata`` JSONB 컬럼에 저장한다. 또한 ``issuer_code``가 8자리
``corp_code``로 저장된 경우, ``symbol``(6자리 stock_code)이 존재하면
``issuer_code``를 ``symbol`` 값으로 보정한다.

Background
----------
P0 정책 변경으로, 신규 이벤트는 ``_raw_from_item()``에서 ``metadata``에
``corp_cls``, ``corp_code``, ``stock_code``를 저장하고 ``issuer_code``는
``stock_code`` 우선으로 저장한다. 기존 902건의 이벤트는 이 정보가 없으므로
이 스크립트로 보강한다.

Usage
-----
    # Dry-run (preview only, 기본값)
    python3 scripts/backfill_external_events_metadata.py

    # 실제 UPDATE 실행
    python3 scripts/backfill_external_events_metadata.py --apply

Safety
------
- ``--dry-run``이 기본값 (``--apply`` 명시 시에만 실제 UPDATE)
- ``WHERE source_name = 'opendart'`` 이중 보호
- 트랜잭션 단위 실행
- 보강 건수 + issuer_code 보정 건수 모두 보고
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from agent_trading.db.connection import close_pool, create_pool
from agent_trading.db.transaction import TransactionManager, transaction

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill_external_events_metadata")

# ── SQL templates ──────────────────────────────────────────────────────────

_SELECT_ALL_OPENDART_SQL = """
SELECT event_id, event_type, symbol, issuer_code, metadata
FROM trading.external_events
WHERE source_name = 'opendart'
ORDER BY event_id
"""

_UPDATE_METADATA_SQL = """
UPDATE trading.external_events
SET metadata = $1::jsonb
WHERE event_id = $2
"""

_UPDATE_ISSUER_CODE_SQL = """
UPDATE trading.external_events
SET issuer_code = $1
WHERE event_id = $2
  AND issuer_code IS DISTINCT FROM $1
"""

_COUNT_BY_CORP_CLS_SQL = """
SELECT
  CASE
    WHEN event_type LIKE 'Y|%' THEN 'Y-상장(KOSPI)'
    WHEN event_type LIKE 'K|%' THEN 'K-코스닥'
    WHEN event_type LIKE 'N|%' THEN 'N-코넥스'
    WHEN event_type LIKE 'E|%' THEN 'E-기타(비상장)'
    ELSE '기타'
  END AS corp_cls_group,
  COUNT(*) AS total,
  COUNT(*) FILTER (WHERE symbol IS NULL) AS null_symbol,
  COUNT(*) FILTER (WHERE symbol IS NOT NULL) AS has_symbol
FROM trading.external_events
WHERE source_name = 'opendart'
GROUP BY corp_cls_group
ORDER BY corp_cls_group
"""


def _extract_corp_cls_from_event_type(event_type: str) -> str | None:
    """Extract corp_cls from event_type prefix (first character).

    OpenDART event_type format: ``{corp_cls}|{report_nm}``
    corp_cls values: Y(상장), K(코스닥), N(코넥스), E(기타/비상장)
    """
    if not event_type or "|" not in event_type:
        return None
    prefix = event_type[0]
    if prefix in ("Y", "K", "N", "E"):
        return prefix
    return None


async def _backfill_metadata(tx: TransactionManager, apply: bool) -> int:
    """Backfill metadata.corp_cls/corp_code/stock_code for existing rows.

    Returns the number of rows that would be / were updated.
    """
    rows = await tx.connection.fetch(_SELECT_ALL_OPENDART_SQL)
    total = len(rows)
    metadata_updates = 0
    issuer_code_updates = 0

    logger.info("Found %d OpenDART events to inspect.", total)

    for row in rows:
        event_id = row["event_id"]
        event_type: str = row["event_type"] or ""
        symbol: str | None = row["symbol"]
        issuer_code: str | None = row["issuer_code"]
        raw_metadata = row["metadata"]
        # asyncpg may return JSONB as str; normalize to dict
        current_metadata: dict = {}
        if raw_metadata is not None:
            if isinstance(raw_metadata, str):
                current_metadata = json.loads(raw_metadata)
            elif isinstance(raw_metadata, dict):
                current_metadata = raw_metadata
            else:
                current_metadata = dict(raw_metadata)

        # ── Extract corp_cls from event_type prefix ──────────────
        corp_cls = _extract_corp_cls_from_event_type(event_type)

        # ── Build enriched metadata ──────────────────────────────
        new_metadata = dict(current_metadata)

        changed = False

        # corp_cls
        if corp_cls and "corp_cls" not in new_metadata:
            new_metadata["corp_cls"] = corp_cls
            changed = True

        # corp_code: issuer_code가 8자리면 corp_code로 간주
        if issuer_code and len(issuer_code) == 8 and "corp_code" not in new_metadata:
            new_metadata["corp_code"] = issuer_code
            changed = True

        # stock_code: symbol이 있으면 stock_code로 저장
        if symbol and "stock_code" not in new_metadata:
            new_metadata["stock_code"] = symbol
            changed = True

        # ── issuer_code 보정: symbol이 있고 issuer_code가 8자리 corp_code면 교체 ──
        needs_issuer_fix = (
            symbol is not None
            and issuer_code is not None
            and len(issuer_code) == 8
            and issuer_code != symbol
        )

        if changed:
            metadata_updates += 1
            if apply:
                await tx.connection.execute(
                    _UPDATE_METADATA_SQL,
                    json.dumps(new_metadata),
                    event_id,
                )

        if needs_issuer_fix:
            issuer_code_updates += 1
            if apply:
                await tx.connection.execute(
                    _UPDATE_ISSUER_CODE_SQL,
                    symbol,
                    event_id,
                )

        if changed or needs_issuer_fix:
            logger.debug(
                "event_id=%s corp_cls=%s symbol=%s issuer=%s→%s metadata_update=%s issuer_fix=%s",
                event_id,
                corp_cls or "?",
                symbol or "NULL",
                issuer_code or "NULL",
                symbol if needs_issuer_fix else "(keep)",
                changed,
                needs_issuer_fix,
            )

    logger.info(
        "Metadata updates: %d / %d rows (would %s)",
        metadata_updates,
        total,
        "UPDATE" if apply else "DRY-RUN",
    )
    logger.info(
        "Issuer-code fixes: %d / %d rows (would %s)",
        issuer_code_updates,
        total,
        "UPDATE" if apply else "DRY-RUN",
    )

    return metadata_updates + issuer_code_updates


async def _print_summary(tx: TransactionManager) -> None:
    """Print before/after summary by corp_cls group."""
    rows = await tx.connection.fetch(_COUNT_BY_CORP_CLS_SQL)
    print()
    print("─" * 70)
    print(f"{'corp_cls':<25} {'Total':>8} {'NULL-symbol':>12} {'Has symbol':>12}")
    print("─" * 70)
    for row in rows:
        print(
            f"{row['corp_cls_group']:<25} {row['total']:>8} "
            f"{row['null_symbol']:>12} {row['has_symbol']:>12}"
        )
    print("─" * 70)
    print()


async def _run(apply: bool) -> int:
    """Execute the backfill. Returns 0 on success, 1 on error."""
    await create_pool()
    try:
        async with transaction() as tx:
            # Before summary
            print("\n=== Before: corp_cls distribution ===")
            await _print_summary(tx)

            # Backfill
            total_updates = await _backfill_metadata(tx, apply=apply)

            # After summary (same data, but shows current state)
            print("=== After: corp_cls distribution ===")
            await _print_summary(tx)

            if apply:
                await tx.commit()
                logger.info("Backfill committed successfully. %d rows affected.", total_updates)
            else:
                # Dry-run: context manager exit will auto-rollback
                logger.info(
                    "Dry-run complete. %d rows would be updated. "
                    "Run with --apply to persist.",
                    total_updates,
                )
    finally:
        await close_pool()

    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill metadata (corp_cls/corp_code/stock_code) for existing OpenDART events."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes (default: dry-run only)",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = _parse_args()
    sys.exit(asyncio.run(_run(apply=args.apply)))


if __name__ == "__main__":
    main()
