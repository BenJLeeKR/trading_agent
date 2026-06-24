#!/usr/bin/env python3
"""KIS 지수/업종 카탈로그를 membership seed 검증 자료로 점검한다."""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SUPPORTED_MEMBERSHIP_CODES = (
    "KOSPI100",
    "KOSPI200",
    "KOSDAQ50",
    "KOSDAQ150",
)

_ALIAS_MAP: dict[str, tuple[str, ...]] = {
    "KOSPI100": ("KOSPI100", "KOSPI 100", "코스피100", "코스피 100"),
    "KOSPI200": ("KOSPI200", "KOSPI 200", "코스피200", "코스피 200"),
    "KOSDAQ50": ("KOSDAQ50", "KOSDAQ 50", "코스닥50", "코스닥 50"),
    "KOSDAQ150": ("KOSDAQ150", "KOSDAQ 150", "코스닥150", "코스닥 150"),
}


@dataclass(slots=True, frozen=True)
class MembershipCatalogMatch:
    membership_code: str
    matched: bool
    match_count: int
    sample_names: tuple[str, ...]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="KIS 카탈로그 덤프를 membership seed 검증 자료로 점검한다.",
    )
    parser.add_argument(
        "--catalog",
        default="logs/kis_index_category_catalog.json",
        help="export_kis_index_category_catalog.py 결과 파일 경로",
    )
    parser.add_argument(
        "--seed-csv",
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
        "--fail-on-missing",
        action="store_true",
        help="seed CSV에 있는 membership code가 catalog에서 하나도 매칭되지 않으면 종료코드 1을 반환한다.",
    )
    return parser.parse_args()


def _normalize_for_match(raw: object) -> str:
    return "".join(str(raw or "").upper().split())


def _load_catalog_rows(path: str) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"catalog 파일이 없습니다: {path}")
    if target.suffix.lower() == ".json":
        raw = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return [row for row in raw if isinstance(row, dict)]
        raise ValueError(f"catalog JSON 형식이 올바르지 않습니다: {path}")
    if target.suffix.lower() == ".csv":
        with target.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            return [dict(row) for row in reader]
    raise ValueError(f"지원하지 않는 catalog 파일 형식입니다: {path}")


def _load_seed_membership_codes(path: str) -> list[str]:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"seed CSV 파일이 없습니다: {path}")
    with target.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        codes: list[str] = []
        for row in reader:
            code = str(row.get("membership_code", "")).strip().upper()
            if code and code not in codes:
                codes.append(code)
        return codes


def _row_search_text(row: dict[str, Any]) -> str:
    return " ".join(_normalize_for_match(value) for value in row.values())


def _extract_sample_name(row: dict[str, Any]) -> str:
    for key in ("hts_kor_isnm", "bstp_cls_name", "name", "index_name"):
        value = str(row.get(key, "")).strip()
        if value:
            return value
    for value in row.values():
        text = str(value).strip()
        if text:
            return text
    return ""


def _match_membership_codes(
    rows: Sequence[dict[str, Any]],
    membership_codes: Iterable[str],
) -> list[MembershipCatalogMatch]:
    matches: list[MembershipCatalogMatch] = []
    indexed_rows = [(_row_search_text(row), row) for row in rows]
    for membership_code in membership_codes:
        normalized_code = str(membership_code).strip().upper()
        aliases = _ALIAS_MAP.get(normalized_code, (normalized_code,))
        normalized_aliases = tuple(_normalize_for_match(alias) for alias in aliases)
        matched_rows: list[dict[str, Any]] = []
        sample_names: list[str] = []
        for search_text, row in indexed_rows:
            if any(alias in search_text for alias in normalized_aliases):
                matched_rows.append(row)
                sample_name = _extract_sample_name(row)
                if sample_name and sample_name not in sample_names:
                    sample_names.append(sample_name)
        matches.append(
            MembershipCatalogMatch(
                membership_code=normalized_code,
                matched=bool(matched_rows),
                match_count=len(matched_rows),
                sample_names=tuple(sample_names[:5]),
            )
        )
    return matches


def _print_result(
    output: str,
    *,
    catalog_path: str,
    seed_csv_path: str,
    catalog_row_count: int,
    matches: Sequence[MembershipCatalogMatch],
) -> None:
    payload = {
        "catalog_path": catalog_path,
        "seed_csv_path": seed_csv_path,
        "catalog_row_count": catalog_row_count,
        "matches": [asdict(item) for item in matches],
    }
    if output == "json":
        print(json.dumps(payload, ensure_ascii=False))
        return
    print("=== KIS Index Membership Catalog Validation ===")
    print(f"catalog_path: {catalog_path}")
    print(f"seed_csv_path: {seed_csv_path}")
    print(f"catalog_row_count: {catalog_row_count}")
    for item in matches:
        sample_names = ", ".join(item.sample_names) if item.sample_names else "-"
        print(
            f"{item.membership_code}: matched={item.matched} "
            f"match_count={item.match_count} sample_names={sample_names}"
        )


def main() -> int:
    args = _parse_args()
    rows = _load_catalog_rows(args.catalog)
    seed_codes = _load_seed_membership_codes(args.seed_csv)
    matches = _match_membership_codes(rows, seed_codes)
    _print_result(
        args.output,
        catalog_path=args.catalog,
        seed_csv_path=args.seed_csv,
        catalog_row_count=len(rows),
        matches=matches,
    )
    if args.fail_on_missing and any(not item.matched for item in matches):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
