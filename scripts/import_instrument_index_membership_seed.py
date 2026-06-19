#!/usr/bin/env python3
"""운영 CSV 기반 instrument index membership 보강 스크립트."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

from agent_trading.db.connection import close_pool, create_pool
from agent_trading.db.transaction import TransactionManager
from agent_trading.repositories.postgres.instrument_index_memberships import (
    PostgresInstrumentIndexMembershipRepository,
)
from agent_trading.repositories.postgres.instruments import PostgresInstrumentRepository


DEFAULT_SEED_CSV_PATH = "data/instrument_master/source/index_membership_seed.csv"
DEFAULT_SOURCE_TAG = "index_membership_seed_csv"


@dataclass(slots=True, frozen=True)
class MembershipSeedRow:
    symbol: str
    membership_code: str


@dataclass(slots=True, frozen=True)
class MembershipSeedSummary:
    target_symbol_count: int = 0
    resolved_symbol_count: int = 0
    skipped_symbol_count: int = 0
    updated_symbol_count: int = 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="운영 CSV를 이용해 instrument index membership을 보강한다.",
    )
    parser.add_argument(
        "--csv",
        default=DEFAULT_SEED_CSV_PATH,
        help="membership seed CSV 경로",
    )
    parser.add_argument(
        "--effective-from",
        default=None,
        help="membership effective_from. YYYY-MM-DD, 기본값은 오늘",
    )
    parser.add_argument(
        "--source-tag",
        default=DEFAULT_SOURCE_TAG,
        help="membership source_tag",
    )
    parser.add_argument(
        "--replace-listed-symbols",
        action="store_true",
        help="CSV에 나온 symbol은 파일 값을 authoritative set으로 간주해 기존 active membership을 교체한다.",
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


def _parse_effective_from(raw: str | None) -> date:
    if raw is None or not raw.strip():
        return datetime.now().date()
    return date.fromisoformat(raw.strip())


def _load_seed_rows(path: str) -> tuple[list[MembershipSeedRow], dict[str, list[str]]]:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"membership seed CSV가 없습니다: {path}")

    with target.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"빈 CSV 파일입니다: {path}")
        required = {"symbol", "membership_code"}
        missing = required - {str(name).strip() for name in reader.fieldnames}
        if missing:
            missing_columns = ", ".join(sorted(missing))
            raise ValueError(f"필수 컬럼이 없습니다: {missing_columns}")

        rows: list[MembershipSeedRow] = []
        grouped: dict[str, list[str]] = defaultdict(list)
        for raw in reader:
            symbol = str(raw.get("symbol", "")).strip().upper()
            membership_code = str(raw.get("membership_code", "")).strip().upper()
            if not symbol or not membership_code:
                continue
            row = MembershipSeedRow(symbol=symbol, membership_code=membership_code)
            rows.append(row)
            if membership_code not in grouped[symbol]:
                grouped[symbol].append(membership_code)
    return rows, dict(grouped)


async def _apply_seed(
    instrument_repo,
    membership_repo,
    *,
    grouped_memberships: dict[str, list[str]],
    effective_from: date,
    source_tag: str,
    replace_listed_symbols: bool,
) -> MembershipSeedSummary:
    resolved_symbol_count = 0
    skipped_symbol_count = 0
    updated_symbol_count = 0

    for symbol, seed_codes in grouped_memberships.items():
        instrument = await instrument_repo.get_by_symbol_any_market(symbol)
        if instrument is None:
            skipped_symbol_count += 1
            continue
        resolved_symbol_count += 1
        if replace_listed_symbols:
            final_codes = list(seed_codes)
        else:
            existing = await membership_repo.list_active_by_instrument(instrument.instrument_id)
            final_codes = list(seed_codes)
            for item in existing:
                code = str(item.membership_code).strip().upper()
                if code and code not in final_codes:
                    final_codes.append(code)

        await membership_repo.sync_current_memberships(
            instrument.instrument_id,
            final_codes,
            effective_from=effective_from,
            source_tag=source_tag,
            metadata={
                "sync_source": "index_membership_seed_file",
                "replace_listed_symbols": replace_listed_symbols,
            },
        )
        updated_symbol_count += 1

    return MembershipSeedSummary(
        target_symbol_count=len(grouped_memberships),
        resolved_symbol_count=resolved_symbol_count,
        skipped_symbol_count=skipped_symbol_count,
        updated_symbol_count=updated_symbol_count,
    )


async def _run(args: argparse.Namespace) -> tuple[MembershipSeedSummary, list[MembershipSeedRow]]:
    rows, grouped = _load_seed_rows(args.csv)
    effective_from = _parse_effective_from(args.effective_from)
    await create_pool()
    tx = TransactionManager()
    await tx.__aenter__()
    try:
        instrument_repo = PostgresInstrumentRepository(tx)
        membership_repo = PostgresInstrumentIndexMembershipRepository(tx)
        summary = await _apply_seed(
            instrument_repo,
            membership_repo,
            grouped_memberships=grouped,
            effective_from=effective_from,
            source_tag=args.source_tag,
            replace_listed_symbols=args.replace_listed_symbols,
        )
        if args.apply:
            await tx.commit()
        else:
            await tx.rollback()
        return summary, rows
    except BaseException:
        await tx.rollback()
        raise
    finally:
        await tx.__aexit__(None, None, None)
        await close_pool()


def _print_result(
    args: argparse.Namespace,
    summary: MembershipSeedSummary,
    rows: Sequence[MembershipSeedRow],
) -> None:
    payload = {
        "apply": args.apply,
        "csv": args.csv,
        "source_tag": args.source_tag,
        "replace_listed_symbols": args.replace_listed_symbols,
        "input_row_count": len(rows),
        "summary": asdict(summary),
    }
    if args.output == "json":
        print(json.dumps(payload, ensure_ascii=False))
        return
    print("=== Instrument Index Membership Seed Import ===")
    for key, value in payload.items():
        if key == "summary":
            continue
        print(f"{key}: {value}")
    for key, value in payload["summary"].items():
        print(f"{key}: {value}")


def main() -> None:
    args = _parse_args()
    summary, rows = asyncio.run(_run(args))
    _print_result(args, summary, rows)


if __name__ == "__main__":
    main()
