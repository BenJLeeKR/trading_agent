#!/usr/bin/env python3
"""membership seed CSV가 현재 instrument master에 해상되는지 점검한다."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from agent_trading.db.connection import close_pool, create_pool
from agent_trading.db.transaction import TransactionManager
from agent_trading.repositories.postgres.instruments import PostgresInstrumentRepository


@dataclass(slots=True, frozen=True)
class SeedResolutionItem:
    symbol: str
    membership_codes: tuple[str, ...]
    resolved: bool
    placeholder: bool
    instrument_id: str | None
    market_segment: str | None
    instrument_name: str | None


@dataclass(slots=True, frozen=True)
class SeedResolutionSummary:
    target_symbol_count: int = 0
    resolved_symbol_count: int = 0
    unresolved_symbol_count: int = 0
    placeholder_symbol_count: int = 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="membership seed CSV의 instrument master 해상도를 점검한다.",
    )
    parser.add_argument(
        "--csv",
        default="data/instrument_master/source/index_membership_seed.csv",
        help="검증 대상 membership seed CSV 경로",
    )
    parser.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="출력 포맷",
    )
    parser.add_argument(
        "--fail-on-unresolved",
        action="store_true",
        help="미해상 symbol이 하나라도 있으면 종료코드 1을 반환한다.",
    )
    parser.add_argument(
        "--fail-on-placeholder",
        action="store_true",
        help="placeholder instrument에만 해상되는 symbol이 있으면 종료코드 1을 반환한다.",
    )
    return parser.parse_args()


def _load_seed_symbols(path: str) -> list[tuple[str, tuple[str, ...]]]:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"seed CSV 파일이 없습니다: {path}")
    grouped: dict[str, list[str]] = {}
    with target.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = str(row.get("symbol", "")).strip().upper()
            membership_code = str(row.get("membership_code", "")).strip().upper()
            if not symbol or not membership_code:
                continue
            grouped.setdefault(symbol, [])
            if membership_code not in grouped[symbol]:
                grouped[symbol].append(membership_code)
    return [(symbol, tuple(codes)) for symbol, codes in sorted(grouped.items())]


async def _resolve_seed_items(
    instrument_repo,
    seed_symbols: Sequence[tuple[str, tuple[str, ...]]],
) -> tuple[SeedResolutionSummary, list[SeedResolutionItem]]:
    items: list[SeedResolutionItem] = []
    resolved_count = 0
    unresolved_count = 0
    placeholder_count = 0
    for symbol, membership_codes in seed_symbols:
        instrument = await instrument_repo.get_by_symbol_any_market(symbol)
        if instrument is None:
            unresolved_count += 1
            items.append(
                SeedResolutionItem(
                    symbol=symbol,
                    membership_codes=membership_codes,
                    resolved=False,
                    placeholder=False,
                    instrument_id=None,
                    market_segment=None,
                    instrument_name=None,
                )
            )
            continue
        resolved_count += 1
        is_placeholder = bool((instrument.metadata or {}).get("placeholder"))
        if is_placeholder:
            placeholder_count += 1
        items.append(
            SeedResolutionItem(
                symbol=symbol,
                membership_codes=membership_codes,
                resolved=True,
                placeholder=is_placeholder,
                instrument_id=str(instrument.instrument_id),
                market_segment=instrument.market_segment,
                instrument_name=instrument.name,
            )
        )
    return (
        SeedResolutionSummary(
            target_symbol_count=len(seed_symbols),
            resolved_symbol_count=resolved_count,
            unresolved_symbol_count=unresolved_count,
            placeholder_symbol_count=placeholder_count,
        ),
        items,
    )


async def _run(args: argparse.Namespace) -> tuple[SeedResolutionSummary, list[SeedResolutionItem]]:
    seed_symbols = _load_seed_symbols(args.csv)
    await create_pool()
    tx = TransactionManager()
    await tx.__aenter__()
    try:
        instrument_repo = PostgresInstrumentRepository(tx)
        summary, items = await _resolve_seed_items(instrument_repo, seed_symbols)
        await tx.rollback()
        return summary, items
    finally:
        await tx.__aexit__(None, None, None)
        await close_pool()


def _print_result(
    output: str,
    *,
    csv_path: str,
    summary: SeedResolutionSummary,
    items: Sequence[SeedResolutionItem],
) -> None:
    payload = {
        "csv_path": csv_path,
        "summary": asdict(summary),
        "items": [asdict(item) for item in items],
    }
    if output == "json":
        print(json.dumps(payload, ensure_ascii=False))
        return
    print("=== Index Membership Seed Resolution ===")
    print(f"csv_path: {csv_path}")
    for key, value in payload["summary"].items():
        print(f"{key}: {value}")
    for item in items:
        print(
            f"{item.symbol}: resolved={item.resolved} placeholder={item.placeholder} "
            f"memberships={','.join(item.membership_codes)} market_segment={item.market_segment or '-'} "
            f"name={item.instrument_name or '-'}"
        )


def main() -> int:
    args = _parse_args()
    summary, items = asyncio.run(_run(args))
    _print_result(
        args.output,
        csv_path=args.csv,
        summary=summary,
        items=items,
    )
    if args.fail_on_unresolved and summary.unresolved_symbol_count > 0:
        return 1
    if args.fail_on_placeholder and summary.placeholder_symbol_count > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
