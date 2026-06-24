from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts.build_index_membership_seed_from_source_package import (
    SeedBuildSummary,
    _build_seed_rows,
    _load_manifest,
    _write_seed_csv,
)


def test_load_manifest_reads_entries(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "source_name": "krx_manual",
                "source_ref": "ops-sheet-2026w26",
                "as_of_date": "2026-06-24",
                "entries": [
                    {
                        "membership_code": "KOSPI100",
                        "csv_path": "kospi100.csv",
                        "note": "검증완료",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    loaded = _load_manifest(str(manifest))
    assert loaded.source_name == "krx_manual"
    assert loaded.entries[0].membership_code == "KOSPI100"
    assert loaded.entries[0].csv_path == "kospi100.csv"


def test_load_manifest_rejects_unsupported_code(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "source_name": "krx_manual",
                "source_ref": "ops-sheet-2026w26",
                "as_of_date": "2026-06-24",
                "entries": [{"membership_code": "KOSPI50", "csv_path": "bad.csv"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="지원하지 않는 membership_code"):
        _load_manifest(str(manifest))


def test_build_seed_rows_merges_multiple_source_files(tmp_path: Path) -> None:
    (tmp_path / "kospi100.csv").write_text(
        "symbol\n005930\n000660\n",
        encoding="utf-8",
    )
    (tmp_path / "kospi200.csv").write_text(
        "symbol\n005930\n373220\n",
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "source_name": "krx_manual",
                "source_ref": "ops-sheet-2026w26",
                "as_of_date": "2026-06-24",
                "entries": [
                    {
                        "membership_code": "KOSPI100",
                        "csv_path": "kospi100.csv",
                        "note": "검증완료",
                    },
                    {
                        "membership_code": "KOSPI200",
                        "csv_path": "kospi200.csv",
                        "note": "검증완료",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manifest = _load_manifest(str(manifest_path))
    rows, summary = _build_seed_rows(manifest, manifest_path=str(manifest_path))
    assert rows == [
        {
            "symbol": "000660",
            "membership_code": "KOSPI100",
            "source_name": "krx_manual",
            "source_ref": "ops-sheet-2026w26",
            "as_of_date": "2026-06-24",
            "note": "검증완료",
        },
        {
            "symbol": "005930",
            "membership_code": "KOSPI100",
            "source_name": "krx_manual",
            "source_ref": "ops-sheet-2026w26",
            "as_of_date": "2026-06-24",
            "note": "검증완료",
        },
        {
            "symbol": "005930",
            "membership_code": "KOSPI200",
            "source_name": "krx_manual",
            "source_ref": "ops-sheet-2026w26",
            "as_of_date": "2026-06-24",
            "note": "검증완료",
        },
        {
            "symbol": "373220",
            "membership_code": "KOSPI200",
            "source_name": "krx_manual",
            "source_ref": "ops-sheet-2026w26",
            "as_of_date": "2026-06-24",
            "note": "검증완료",
        },
    ]
    assert summary == SeedBuildSummary(
        source_file_count=2,
        input_symbol_count=4,
        output_row_count=4,
    )


def test_write_seed_csv_writes_expected_columns(tmp_path: Path) -> None:
    output = tmp_path / "seed.csv"
    _write_seed_csv(
        str(output),
        [
            {
                "symbol": "005930",
                "membership_code": "KOSPI100",
                "source_name": "krx_manual",
                "source_ref": "ops-sheet-2026w26",
                "as_of_date": "2026-06-24",
                "note": "검증완료",
            }
        ],
    )
    with output.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    assert rows == [
        {
            "symbol": "005930",
            "membership_code": "KOSPI100",
            "source_name": "krx_manual",
            "source_ref": "ops-sheet-2026w26",
            "as_of_date": "2026-06-24",
            "note": "검증완료",
        }
    ]
