#!/usr/bin/env python3
"""One-off script to backfill ``symbol`` for existing ``external_events`` rows.

OpenDART ``/list.json`` API가 ``stock_code``를 빈 값으로 반환하는 경우,
기존에는 ``symbol=NULL``로 저장되었다. 이 스크립트는 ``/company.json`` API를
사용하여 ``corp_code → stock_code`` 매핑을 시도하고, 성공한 경우에만 UPDATE한다.

Usage
-----
    # Dry-run (preview only, 기본값)
    python3 scripts/backfill_external_events_symbol.py

    # 실제 UPDATE 실행
    python3 scripts/backfill_external_events_symbol.py --apply

Safety
------
- ``--dry-run``이 기본값 (``--apply`` 명시 시에만 실제 UPDATE)
- ``WHERE symbol IS NULL AND source_name = 'opendart'`` 이중 보호
- 트랜잭션 단위 실행
- 업데이트 건수 + unresolved 건수 모두 보고
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from agent_trading.db.connection import DatabaseConfig, close_pool, create_pool
from agent_trading.db.transaction import TransactionManager
from agent_trading.services.symbol_resolver import OpenDartSymbolResolver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill_external_events_symbol")

# ── SQL templates ──────────────────────────────────────────────────────────

_SELECT_NULL_SYMBOL_SQL = """
SELECT DISTINCT issuer_code
FROM trading.external_events
WHERE symbol IS NULL
  AND issuer_code IS NOT NULL
  AND source_name = 'opendart'
ORDER BY issuer_code
"""

_COUNT_NULL_SYMBOL_SQL = """
SELECT count(*) AS cnt
FROM trading.external_events
WHERE symbol IS NULL
  AND source_name = 'opendart'
"""

_UPDATE_SYMBOL_SQL = """
UPDATE trading.external_events
SET symbol = $1
WHERE issuer_code = $2
  AND symbol IS NULL
  AND source_name = 'opendart'
"""


async def _resolve_and_update(
    tx: TransactionManager,
    resolver: OpenDartSymbolResolver,
    apply: bool,
) -> tuple[int, int]:
    """Resolve NULL-symbol events and optionally update them.

    Parameters
    ----------
    tx : TransactionManager
        Database transaction manager.
    resolver : OpenDartSymbolResolver
        Resolver for corp_code → stock_code.
    apply : bool
        If True, execute UPDATE. If False, dry-run (preview only).

    Returns
    -------
    tuple[int, int]
        (updated_count, unresolved_count)
    """
    # 1. 고유 issuer_code 추출
    rows = await tx.connection.fetch(_SELECT_NULL_SYMBOL_SQL)
    corp_codes: list[str] = [row["issuer_code"] for row in rows if row["issuer_code"]]

    if not corp_codes:
        logger.info("No NULL-symbol OpenDART events found. Nothing to do.")
        return 0, 0

    logger.info("Found %d unique issuer_codes with NULL symbol", len(corp_codes))

    # 2. 각 issuer_code에 대해 symbol resolve
    resolved_count = 0
    unresolved_count = 0

    for corp_code in corp_codes:
        symbol = await resolver.resolve(corp_code)
        if symbol:
            resolved_count += 1
            if apply:
                result = await tx.connection.execute(
                    _UPDATE_SYMBOL_SQL,
                    symbol,
                    corp_code,
                )
                # result looks like "UPDATE 3"
                updated = int(result.split()[-1]) if result else 0
                logger.debug(
                    "Resolved corp_code=%s → symbol=%s (updated %d rows)",
                    corp_code,
                    symbol,
                    updated,
                )
            else:
                logger.debug(
                    "[DRY-RUN] Would update corp_code=%s → symbol=%s",
                    corp_code,
                    symbol,
                )
        else:
            unresolved_count += 1
            logger.debug(
                "Unresolved corp_code=%s (no stock_code from /company.json)",
                corp_code,
            )

    return resolved_count, unresolved_count


async def _run(apply: bool) -> int:
    """Execute the backfill. Returns 0 on success, 1 on error."""
    await create_pool()
    try:
        tx = TransactionManager()
        await tx.__aenter__()
        try:
            # OpenDartSymbolResolver 생성 (설정은 환경변수에서 읽음)
            from agent_trading.config.settings import AppSettings

            settings = AppSettings()  # type: ignore[call-arg]
            if not settings.opendart_api_key:
                logger.error(
                    "OPENDART_API_KEY is not set. Cannot resolve symbols."
                )
                return 1

            resolver = OpenDartSymbolResolver(
                api_key=settings.opendart_api_key,
            )

            # NULL-symbol 이벤트 총 건수 조회
            count_row = await tx.connection.fetchrow(_COUNT_NULL_SYMBOL_SQL)
            total_null = count_row["cnt"] if count_row else 0
            logger.info(
                "Total NULL-symbol OpenDART events in DB: %d",
                total_null,
            )

            # Resolve + Update
            resolved, unresolved = await _resolve_and_update(tx, resolver, apply)

            if apply:
                await tx.commit()
                logger.info(
                    "Backfill complete: %d resolved, %d unresolved "
                    "(total NULL-symbol before: %d)",
                    resolved,
                    unresolved,
                    total_null,
                )
            else:
                logger.info(
                    "[DRY-RUN] Dry-run complete: %d would be resolved, "
                    "%d would remain unresolved (total NULL-symbol: %d). "
                    "Run with --apply to execute.",
                    resolved,
                    unresolved,
                    total_null,
                )

            await resolver.close()

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
        description="Backfill symbol for existing NULL-symbol OpenDART external_events."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="실제 UPDATE를 실행합니다. 지정하지 않으면 dry-run (preview only).",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = _parse_args()
    exit_code = asyncio.run(_run(apply=args.apply))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
