#!/usr/bin/env python3
"""외부 membership 원천 패키지를 seed CSV로 정규화한다."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

SUPPORTED_MEMBERSHIP_CODES = frozenset(
    {
        "KOSPI100",
        "KOSPI200",
        "KOSDAQ50",
        "KOSDAQ150",
    }
)


@dataclass(slots=True, frozen=True)
class SourcePackageEntry:
    membership_code: str
    csv_path: str
    note: str | None = None


@dataclass(slots=True, frozen=True)
class SourcePackageManifest:
    source_name: str
    source_ref: str
    as_of_date: str
    entries: tuple[SourcePackageEntry, ...]


@dataclass(slots=True, frozen=True)
class SeedBuildSummary:
    source_file_count: int = 0
    input_symbol_count: int = 0
    output_row_count: int = 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="외부 membership source package를 seed CSV로 변환한다.",
    )
    parser.add_argument(
        "--manifest",
        default="data/instrument_master/source/index_membership_source_manifest.json",
        help="source package manifest JSON 경로",
    )
    parser.add_argument(
        "--output",
        default="data/instrument_master/source/index_membership_seed.csv",
        help="생성할 seed CSV 경로",
    )
    parser.add_argument(
        "--output-format",
        choices=("text", "json"),
        default="text",
        help="실행 결과 출력 형식",
    )
    return parser.parse_args()


def _load_manifest(path: str) -> SourcePackageManifest:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"manifest 파일이 없습니다: {path}")
    raw = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"manifest 형식이 올바르지 않습니다: {path}")
    entries_raw = raw.get("entries")
    if not isinstance(entries_raw, list) or not entries_raw:
        raise ValueError("manifest.entries는 비어 있지 않은 배열이어야 합니다.")
    entries: list[SourcePackageEntry] = []
    for item in entries_raw:
        if not isinstance(item, dict):
            raise ValueError("manifest.entries 항목은 object여야 합니다.")
        membership_code = str(item.get("membership_code", "")).strip().upper()
        csv_path = str(item.get("csv_path", "")).strip()
        if membership_code not in SUPPORTED_MEMBERSHIP_CODES:
            raise ValueError(f"지원하지 않는 membership_code입니다: {membership_code}")
        if not csv_path:
            raise ValueError(f"{membership_code} entry에 csv_path가 없습니다.")
        entries.append(
            SourcePackageEntry(
                membership_code=membership_code,
                csv_path=csv_path,
                note=str(item.get("note", "")).strip() or None,
            )
        )
    source_name = str(raw.get("source_name", "")).strip()
    source_ref = str(raw.get("source_ref", "")).strip()
    as_of_date = str(raw.get("as_of_date", "")).strip()
    if not source_name or not source_ref or not as_of_date:
        raise ValueError("manifest에는 source_name, source_ref, as_of_date가 필요합니다.")
    return SourcePackageManifest(
        source_name=source_name,
        source_ref=source_ref,
        as_of_date=as_of_date,
        entries=tuple(entries),
    )


def _load_symbols_from_entry(base_dir: Path, entry: SourcePackageEntry) -> list[str]:
    csv_path = (base_dir / entry.csv_path).resolve() if not Path(entry.csv_path).is_absolute() else Path(entry.csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(
            f"membership source CSV가 없습니다: membership_code={entry.membership_code} path={csv_path}"
        )
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"빈 source CSV입니다: {csv_path}")
        normalized_headers = {str(name).strip().lower() for name in reader.fieldnames}
        if "symbol" not in normalized_headers:
            raise ValueError(f"source CSV에 symbol 컬럼이 없습니다: {csv_path}")
        symbols: list[str] = []
        for row in reader:
            symbol = str(row.get("symbol", "")).strip().upper()
            if symbol and symbol not in symbols:
                symbols.append(symbol)
        return symbols


def _build_seed_rows(
    manifest: SourcePackageManifest,
    *,
    manifest_path: str,
) -> tuple[list[dict[str, str]], SeedBuildSummary]:
    base_dir = Path(manifest_path).resolve().parent
    symbol_codes: dict[str, list[str]] = defaultdict(list)
    row_notes: dict[tuple[str, str], str | None] = {}
    input_symbol_count = 0
    for entry in manifest.entries:
        symbols = _load_symbols_from_entry(base_dir, entry)
        input_symbol_count += len(symbols)
        for symbol in symbols:
            if entry.membership_code not in symbol_codes[symbol]:
                symbol_codes[symbol].append(entry.membership_code)
                row_notes[(symbol, entry.membership_code)] = entry.note
    rows: list[dict[str, str]] = []
    for symbol in sorted(symbol_codes):
        for membership_code in sorted(symbol_codes[symbol]):
            rows.append(
                {
                    "symbol": symbol,
                    "membership_code": membership_code,
                    "source_name": manifest.source_name,
                    "source_ref": manifest.source_ref,
                    "as_of_date": manifest.as_of_date,
                    "note": row_notes.get((symbol, membership_code)) or "",
                }
            )
    return rows, SeedBuildSummary(
        source_file_count=len(manifest.entries),
        input_symbol_count=input_symbol_count,
        output_row_count=len(rows),
    )


def _write_seed_csv(path: str, rows: Sequence[dict[str, str]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "symbol",
                "membership_code",
                "source_name",
                "source_ref",
                "as_of_date",
                "note",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _print_result(
    output_format: str,
    *,
    manifest_path: str,
    output_path: str,
    summary: SeedBuildSummary,
) -> None:
    payload = {
        "manifest_path": manifest_path,
        "output_path": output_path,
        "summary": asdict(summary),
    }
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False))
        return
    print("=== Index Membership Source Package Build ===")
    print(f"manifest_path: {manifest_path}")
    print(f"output_path: {output_path}")
    for key, value in payload["summary"].items():
        print(f"{key}: {value}")


def main() -> int:
    args = _parse_args()
    manifest = _load_manifest(args.manifest)
    rows, summary = _build_seed_rows(manifest, manifest_path=args.manifest)
    _write_seed_csv(args.output, rows)
    _print_result(
        args.output_format,
        manifest_path=args.manifest,
        output_path=args.output,
        summary=summary,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
