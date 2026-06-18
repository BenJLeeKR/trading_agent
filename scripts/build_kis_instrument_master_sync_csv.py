#!/usr/bin/env python3
"""KIS 종목 master 원본 CSV를 sync용 normalized CSV로 변환한다."""

from __future__ import annotations

import argparse
import csv
import shutil
import sys
from collections.abc import Iterable
from pathlib import Path


_OUTPUT_FIELDS = (
    "symbol",
    "name",
    "market_code",
    "asset_class",
    "currency",
    "tick_size",
    "lot_size",
    "is_active",
    "name_kr",
    "exchange_code",
    "metadata_market_segment",
    "metadata_segment",
    "metadata_universe_segment",
    "metadata_kospi_kosdaq_cls_name",
    "metadata_mrkt_trtm_cls_name",
    "source_file",
)

_SYMBOL_FIELDS = (
    "symbol",
    "code",
    "stck_shrn_iscd",
    "mksc_shrn_iscd",
    "inter_shrn_iscd",
)
_NAME_FIELDS = (
    "name",
    "name_kr",
    "hts_kor_isnm",
    "prdt_abrv_name",
    "short_name",
)
_MARKET_FIELDS = (
    "market_code",
    "market",
    "kospi_kosdaq_cls_name",
    "mrkt_trtm_cls_name",
)
_EXCHANGE_FIELDS = (
    "exchange_code",
    "exchange",
    "market_code",
    "market",
    "kospi_kosdaq_cls_name",
)
_MARKET_SEGMENT_FIELDS = (
    "market_segment",
    "segment",
    "universe_segment",
)


def _normalize_segment_value(raw: str) -> str:
    value = (raw or "").strip().upper()
    if not value:
        return ""
    aliases = {
        "KOSPI 100": "KOSPI100",
        "KOSPI-100": "KOSPI100",
        "KOSDAQ 150": "KOSDAQ150",
        "KOSDAQ-150": "KOSDAQ150",
        "KOSPI LARGE": "KOSPI_LARGE",
        "KOSPI_LARGE": "KOSPI_LARGE",
        "KOSDAQ GROWTH": "KOSDAQ_GROWTH",
        "KOSDAQ_GROWTH": "KOSDAQ_GROWTH",
    }
    return aliases.get(value, value)


def _normalize_header_map(fieldnames: Iterable[str]) -> dict[str, str]:
    return {name.strip().lower(): name for name in fieldnames}


def _pick_value(row: dict[str, str], headers: dict[str, str], candidates: tuple[str, ...]) -> str:
    for candidate in candidates:
        original = headers.get(candidate)
        if not original:
            continue
        value = (row.get(original) or "").strip()
        if value:
            return value
    return ""


def _normalize_market_code(raw: str, *, default_market_code: str) -> str:
    value = (raw or "").strip().upper()
    if not value:
        return default_market_code.upper()
    aliases = {
        "KOSPI": "KOSPI",
        "거래소": "KOSPI",
        "STK": "KOSPI",
        "KOSDAQ": "KOSDAQ",
        "코스닥": "KOSDAQ",
        "KSQ": "KOSDAQ",
        "KRX": "KRX",
    }
    return aliases.get(value, value)


def _build_normalized_row(
    row: dict[str, str],
    headers: dict[str, str],
    *,
    source_file: str,
    default_market_code: str,
    asset_class: str,
    currency: str,
    tick_size: str,
    lot_size: str,
) -> dict[str, str] | None:
    symbol = _pick_value(row, headers, _SYMBOL_FIELDS)
    name = _pick_value(row, headers, _NAME_FIELDS)
    if not symbol or not name:
        return None

    market_code = _normalize_market_code(
        _pick_value(row, headers, _MARKET_FIELDS),
        default_market_code=default_market_code,
    )
    raw_exchange_code = _pick_value(row, headers, _EXCHANGE_FIELDS)
    exchange_code = _normalize_market_code(
        raw_exchange_code,
        default_market_code=market_code,
    )
    segment = _normalize_segment_value(
        _pick_value(row, headers, _MARKET_SEGMENT_FIELDS)
    )
    return {
        "symbol": symbol,
        "name": name,
        "market_code": market_code,
        "asset_class": asset_class,
        "currency": currency,
        "tick_size": tick_size,
        "lot_size": lot_size,
        "is_active": "TRUE",
        "name_kr": name,
        "exchange_code": exchange_code,
        "metadata_market_segment": market_code,
        "metadata_segment": segment,
        "metadata_universe_segment": segment,
        "metadata_kospi_kosdaq_cls_name": _pick_value(row, headers, ("kospi_kosdaq_cls_name",)),
        "metadata_mrkt_trtm_cls_name": _pick_value(row, headers, ("mrkt_trtm_cls_name",)),
        "source_file": source_file,
    }


def _load_rows_from_csv(
    path: Path,
    *,
    default_market_code: str,
    asset_class: str,
    currency: str,
    tick_size: str,
    lot_size: str,
) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"빈 CSV 파일입니다: {path}")
        headers = _normalize_header_map(reader.fieldnames)
        rows: list[dict[str, str]] = []
        for raw_row in reader:
            normalized = _build_normalized_row(
                raw_row,
                headers,
                source_file=path.name,
                default_market_code=default_market_code,
                asset_class=asset_class,
                currency=currency,
                tick_size=tick_size,
                lot_size=lot_size,
            )
            if normalized is not None:
                rows.append(normalized)
        return rows


def _dedupe_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        deduped[(row["symbol"], row["market_code"])] = row
    return list(deduped.values())


def _write_output(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _archive_source_files(
    source_paths: list[Path],
    *,
    archive_dir: Path,
    archive_label: str,
) -> list[str]:
    target_dir = archive_dir / archive_label
    target_dir.mkdir(parents=True, exist_ok=True)
    archived: list[str] = []
    for source_path in source_paths:
        target_path = target_dir / source_path.name
        shutil.copy2(source_path, target_path)
        archived.append(str(target_path))
    return archived


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="KIS instrument master 원본 CSV를 sync용 normalized CSV로 변환한다.",
    )
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        help="원본 CSV 경로. 여러 번 지정 가능.",
    )
    parser.add_argument("--output", required=True, help="출력 normalized CSV 경로.")
    parser.add_argument("--default-market-code", default="KRX")
    parser.add_argument("--asset-class", default="kr_stock")
    parser.add_argument("--currency", default="KRW")
    parser.add_argument("--tick-size", default="100")
    parser.add_argument("--lot-size", default="1")
    parser.add_argument(
        "--archive-dir",
        default=None,
        help="원본 CSV 보관 디렉터리. 지정 시 archive-label 하위로 복사한다.",
    )
    parser.add_argument(
        "--archive-label",
        default=None,
        help="원본 CSV 보관 하위 디렉터리명. 미지정 시 output 파일명 stem 사용.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    all_rows: list[dict[str, str]] = []
    source_paths: list[Path] = []
    for raw_path in args.input:
        path = Path(raw_path)
        if not path.exists():
            raise SystemExit(f"입력 CSV가 없습니다: {raw_path}")
        source_paths.append(path)
        all_rows.extend(
            _load_rows_from_csv(
                path,
                default_market_code=args.default_market_code,
                asset_class=args.asset_class,
                currency=args.currency,
                tick_size=args.tick_size,
                lot_size=args.lot_size,
            )
        )

    output_rows = sorted(
        _dedupe_rows(all_rows),
        key=lambda row: (row["market_code"], row["symbol"]),
    )
    output_path = Path(args.output)
    _write_output(output_path, output_rows)
    archived_paths: list[str] = []
    if args.archive_dir:
        archive_label = args.archive_label or output_path.stem
        archived_paths = _archive_source_files(
            source_paths,
            archive_dir=Path(args.archive_dir),
            archive_label=archive_label,
        )
    print(
        "{{"
        f'"inputs":{len(args.input)},'
        f'"rows":{len(output_rows)},'
        f'"output":"{args.output}",'
        f'"archived_count":{len(archived_paths)}'
        "}}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
