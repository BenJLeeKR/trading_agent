from __future__ import annotations

import json
from pathlib import Path

from scripts.validate_kis_index_membership_catalog import (
    MembershipCatalogMatch,
    _load_catalog_rows,
    _load_seed_membership_codes,
    _match_membership_codes,
)


def test_load_catalog_rows_supports_json(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            [
                {"hts_kor_isnm": "코스피 100", "bcdt_code": "X001"},
                {"hts_kor_isnm": "코스닥 150", "bcdt_code": "X002"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    rows = _load_catalog_rows(str(path))
    assert rows == [
        {"hts_kor_isnm": "코스피 100", "bcdt_code": "X001"},
        {"hts_kor_isnm": "코스닥 150", "bcdt_code": "X002"},
    ]


def test_load_catalog_rows_supports_csv(tmp_path: Path) -> None:
    path = tmp_path / "catalog.csv"
    path.write_text(
        "hts_kor_isnm,bcdt_code\n코스피 200,X001\n",
        encoding="utf-8",
    )
    rows = _load_catalog_rows(str(path))
    assert rows == [{"hts_kor_isnm": "코스피 200", "bcdt_code": "X001"}]


def test_load_seed_membership_codes_dedupes(tmp_path: Path) -> None:
    path = tmp_path / "seed.csv"
    path.write_text(
        "symbol,membership_code\n005930,KOSPI200\n000660,KOSPI200\n090150,KOSDAQ50\n",
        encoding="utf-8",
    )
    assert _load_seed_membership_codes(str(path)) == ["KOSPI200", "KOSDAQ50"]


def test_match_membership_codes_uses_alias_matching() -> None:
    rows = [
        {"hts_kor_isnm": "코스피 100", "bcdt_code": "X001"},
        {"hts_kor_isnm": "코스닥150", "bcdt_code": "X002"},
        {"hts_kor_isnm": "기타 업종", "bcdt_code": "X003"},
    ]
    assert _match_membership_codes(rows, ["KOSPI100", "KOSDAQ150"]) == [
        MembershipCatalogMatch(
            membership_code="KOSPI100",
            matched=True,
            match_count=1,
            sample_names=("코스피 100",),
        ),
        MembershipCatalogMatch(
            membership_code="KOSDAQ150",
            matched=True,
            match_count=1,
            sample_names=("코스닥150",),
        ),
    ]


def test_match_membership_codes_reports_missing() -> None:
    rows = [{"hts_kor_isnm": "코스피 200", "bcdt_code": "X001"}]
    matches = _match_membership_codes(rows, ["KOSPI200", "KOSDAQ50"])
    assert matches[0].matched is True
    assert matches[1] == MembershipCatalogMatch(
        membership_code="KOSDAQ50",
        matched=False,
        match_count=0,
        sample_names=(),
    )
