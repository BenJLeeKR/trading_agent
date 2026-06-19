#!/usr/bin/env python3
"""국내주식 instrument canonical 정합성 정리 스크립트."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass

from agent_trading.db.connection import close_pool, create_pool
from agent_trading.db.transaction import TransactionManager


_REFERENCE_TABLES: tuple[str, ...] = (
    "feature_snapshots",
    "market_data_snapshots",
    "order_requests",
    "position_snapshots",
    "signal_feature_snapshots",
    "trade_decisions",
    "universe_freeze_run_items",
)


@dataclass(slots=True, frozen=True)
class ReconcileSummary:
    updated_feature_snapshots: int = 0
    updated_market_data_snapshots: int = 0
    updated_order_requests: int = 0
    updated_position_snapshots: int = 0
    updated_signal_feature_snapshots: int = 0
    updated_trade_decisions: int = 0
    updated_universe_freeze_run_items: int = 0
    deleted_legacy_rows: int = 0
    deleted_orphan_canonical_rows: int = 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="국내주식 canonical instrument 정합성을 정리한다.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="실제 DB 변경을 커밋한다. 미지정 시 dry-run으로 롤백한다.",
    )
    parser.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="실행 결과 출력 형식",
    )
    return parser.parse_args()


def _summary_key(table_name: str) -> str:
    return f"updated_{table_name}"


async def _update_reference_table(tx: TransactionManager, table_name: str) -> int:
    query = f"""
        WITH mapping AS (
            SELECT
                legacy.instrument_id AS legacy_instrument_id,
                canonical.instrument_id AS canonical_instrument_id
            FROM trading.instruments legacy
            JOIN trading.instruments canonical
              ON canonical.symbol = legacy.symbol
             AND canonical.market_code = 'KRX'
            WHERE legacy.market_code IN ('KOSPI', 'KOSDAQ')
        )
        UPDATE trading.{table_name} AS target
           SET instrument_id = mapping.canonical_instrument_id
          FROM mapping
         WHERE target.instrument_id = mapping.legacy_instrument_id
    """
    result = await tx.connection.execute(query)
    return int(str(result).split()[-1])


async def _delete_legacy_rows(tx: TransactionManager) -> int:
    result = await tx.connection.execute(
        """
        DELETE FROM trading.instruments legacy
         WHERE legacy.market_code IN ('KOSPI', 'KOSDAQ')
           AND EXISTS (
               SELECT 1
                 FROM trading.instruments canonical
                WHERE canonical.symbol = legacy.symbol
                  AND canonical.market_code = 'KRX'
           )
        """
    )
    return int(str(result).split()[-1])


async def _delete_orphan_canonical_rows(tx: TransactionManager) -> int:
    result = await tx.connection.execute(
        """
        DELETE FROM trading.instruments canonical
         WHERE canonical.market_code = 'KRX'
           AND canonical.exchange_code IS NULL
           AND canonical.market_segment IS NULL
           AND canonical.metadata = '{}'::jsonb
           AND NOT EXISTS (
               SELECT 1
                 FROM trading.feature_snapshots fs
                WHERE fs.instrument_id = canonical.instrument_id
           )
           AND NOT EXISTS (
               SELECT 1
                 FROM trading.market_data_snapshots mds
                WHERE mds.instrument_id = canonical.instrument_id
           )
           AND NOT EXISTS (
               SELECT 1
                 FROM trading.order_requests o
                WHERE o.instrument_id = canonical.instrument_id
           )
           AND NOT EXISTS (
               SELECT 1
                 FROM trading.position_snapshots ps
                WHERE ps.instrument_id = canonical.instrument_id
           )
           AND NOT EXISTS (
               SELECT 1
                 FROM trading.signal_feature_snapshots sfs
                WHERE sfs.instrument_id = canonical.instrument_id
           )
           AND NOT EXISTS (
               SELECT 1
                 FROM trading.trade_decisions td
                WHERE td.instrument_id = canonical.instrument_id
           )
           AND NOT EXISTS (
               SELECT 1
                 FROM trading.universe_freeze_run_items ufri
                WHERE ufri.instrument_id = canonical.instrument_id
           )
           AND NOT EXISTS (
               SELECT 1
                 FROM trading.instrument_index_memberships iim
                WHERE iim.instrument_id = canonical.instrument_id
           )
        """
    )
    return int(str(result).split()[-1])


async def _run(args: argparse.Namespace) -> ReconcileSummary:
    await create_pool()
    tx = TransactionManager()
    await tx.__aenter__()
    try:
        summary_kwargs: dict[str, int] = {}
        for table_name in _REFERENCE_TABLES:
            summary_kwargs[_summary_key(table_name)] = await _update_reference_table(
                tx,
                table_name,
            )
        summary_kwargs["deleted_legacy_rows"] = await _delete_legacy_rows(tx)
        summary_kwargs["deleted_orphan_canonical_rows"] = await _delete_orphan_canonical_rows(tx)
        summary = ReconcileSummary(**summary_kwargs)
        if args.apply:
            await tx.commit()
        else:
            await tx.rollback()
        return summary
    except BaseException:
        await tx.rollback()
        raise
    finally:
        await tx.__aexit__(None, None, None)
        await close_pool()


def _print_summary(args: argparse.Namespace, summary: ReconcileSummary) -> None:
    payload = {
        "apply": args.apply,
        "summary": asdict(summary),
    }
    if args.output == "json":
        print(json.dumps(payload, ensure_ascii=False))
        return
    print("=== Instrument Canonical Reconcile ===")
    print(f"apply: {args.apply}")
    for key, value in payload["summary"].items():
        print(f"{key}: {value}")


def main() -> None:
    args = _parse_args()
    summary = asyncio.run(_run(args))
    _print_summary(args, summary)


if __name__ == "__main__":
    main()
