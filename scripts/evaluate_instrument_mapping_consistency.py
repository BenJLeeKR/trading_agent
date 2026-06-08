#!/usr/bin/env python3
"""Audit symbol -> instrument master mapping consistency.

Focus scope for Priority Map item 9:
- recent ``external_events`` symbols missing from ``trading.instruments``
- recent ``broker_fill_snapshots`` symbols missing from ``trading.instruments``

This is a read-only operator tool.  It does not mutate DB state.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

KST = timezone(timedelta(hours=9))


@dataclass(frozen=True, slots=True)
class MappingGap:
    symbol: str
    row_count: int
    last_seen_at: datetime


@dataclass(frozen=True, slots=True)
class MappingConsistencyReport:
    generated_at: datetime
    lookback_days: int
    active_instrument_count: int
    unmapped_external_event_symbols: tuple[MappingGap, ...]
    unmapped_broker_fill_symbols: tuple[MappingGap, ...]

    @property
    def has_gap(self) -> bool:
        return bool(self.unmapped_external_event_symbols or self.unmapped_broker_fill_symbols)

    def to_json(self) -> str:
        payload = {
            "generated_at": self.generated_at.isoformat(),
            "lookback_days": self.lookback_days,
            "active_instrument_count": self.active_instrument_count,
            "has_gap": self.has_gap,
            "unmapped_external_event_symbols": [asdict(item) for item in self.unmapped_external_event_symbols],
            "unmapped_broker_fill_symbols": [asdict(item) for item in self.unmapped_broker_fill_symbols],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)

    def to_text(self) -> str:
        lines = [
            "=== Instrument Mapping Consistency ===",
            f"generated_at: {self.generated_at.astimezone(KST).strftime('%Y-%m-%d %H:%M:%S')} KST",
            f"lookback_days: {self.lookback_days}",
            f"active_instrument_count: {self.active_instrument_count}",
            f"has_gap: {self.has_gap}",
            "",
            "[unmapped_external_event_symbols]",
        ]
        if self.unmapped_external_event_symbols:
            for item in self.unmapped_external_event_symbols:
                lines.append(
                    f"- {item.symbol}: rows={item.row_count} "
                    f"last_seen={item.last_seen_at.astimezone(KST).strftime('%Y-%m-%d %H:%M')}"
                )
        else:
            lines.append("- none")
        lines.extend(["", "[unmapped_broker_fill_symbols]"])
        if self.unmapped_broker_fill_symbols:
            for item in self.unmapped_broker_fill_symbols:
                lines.append(
                    f"- {item.symbol}: rows={item.row_count} "
                    f"last_seen={item.last_seen_at.astimezone(KST).strftime('%Y-%m-%d %H:%M')}"
                )
        else:
            lines.append("- none")
        return "\n".join(lines)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _dsn_from_env() -> str:
    return (
        os.getenv("DATABASE_URL")
        or os.getenv("APP_DATABASE_URL")
        or "postgresql://postgres:postgres@db:5432/agent_trading"
    )


def _row_to_gap(row: asyncpg.Record) -> MappingGap:
    return MappingGap(
        symbol=str(row["symbol"]),
        row_count=int(row["row_count"]),
        last_seen_at=row["last_seen_at"],
    )


async def _query_unmapped_external_event_symbols(
    conn: asyncpg.Connection,
    *,
    since: datetime,
    limit: int,
) -> tuple[MappingGap, ...]:
    rows = await conn.fetch(
        """
        SELECT
            e.symbol,
            COUNT(*)::int AS row_count,
            MAX(COALESCE(e.created_at, e.ingested_at, e.published_at)) AS last_seen_at
        FROM trading.external_events e
        LEFT JOIN trading.instruments i ON i.symbol = e.symbol
        WHERE e.symbol IS NOT NULL
          AND BTRIM(e.symbol) != ''
          AND COALESCE(e.created_at, e.ingested_at, e.published_at) >= $1
          AND i.instrument_id IS NULL
        GROUP BY e.symbol
        ORDER BY row_count DESC, last_seen_at DESC, e.symbol ASC
        LIMIT $2
        """,
        since,
        limit,
    )
    return tuple(_row_to_gap(row) for row in rows)


async def _query_unmapped_broker_fill_symbols(
    conn: asyncpg.Connection,
    *,
    since: datetime,
    limit: int,
) -> tuple[MappingGap, ...]:
    rows = await conn.fetch(
        """
        SELECT
            bfs.symbol,
            COUNT(*)::int AS row_count,
            MAX(COALESCE(bfs.fill_timestamp, bfs.created_at)) AS last_seen_at
        FROM trading.broker_fill_snapshots bfs
        LEFT JOIN trading.instruments i ON i.symbol = bfs.symbol
        WHERE bfs.symbol IS NOT NULL
          AND BTRIM(bfs.symbol) != ''
          AND COALESCE(bfs.fill_timestamp, bfs.created_at) >= $1
          AND i.instrument_id IS NULL
        GROUP BY bfs.symbol
        ORDER BY row_count DESC, last_seen_at DESC, bfs.symbol ASC
        LIMIT $2
        """,
        since,
        limit,
    )
    return tuple(_row_to_gap(row) for row in rows)


async def _query_active_instrument_count(conn: asyncpg.Connection) -> int:
    row = await conn.fetchrow(
        """
        SELECT COUNT(*)::int AS cnt
        FROM trading.instruments
        WHERE is_active = true
        """
    )
    return int(row["cnt"]) if row else 0


async def evaluate_mapping_consistency(
    *,
    dsn: str,
    lookback_days: int,
    limit: int,
) -> MappingConsistencyReport:
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    conn = await asyncpg.connect(dsn)
    try:
        active_instrument_count = await _query_active_instrument_count(conn)
        unmapped_external_event_symbols = await _query_unmapped_external_event_symbols(
            conn,
            since=since,
            limit=limit,
        )
        unmapped_broker_fill_symbols = await _query_unmapped_broker_fill_symbols(
            conn,
            since=since,
            limit=limit,
        )
    finally:
        await conn.close()

    return MappingConsistencyReport(
        generated_at=datetime.now(timezone.utc),
        lookback_days=lookback_days,
        active_instrument_count=active_instrument_count,
        unmapped_external_event_symbols=unmapped_external_event_symbols,
        unmapped_broker_fill_symbols=unmapped_broker_fill_symbols,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit recent symbol -> instrument master mapping consistency.",
    )
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", choices=("text", "json"), default="text")
    return parser.parse_args(argv)


async def _run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = await evaluate_mapping_consistency(
        dsn=_dsn_from_env(),
        lookback_days=args.lookback_days,
        limit=args.limit,
    )
    if args.output == "json":
        print(report.to_json())
    else:
        print(report.to_text())
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
