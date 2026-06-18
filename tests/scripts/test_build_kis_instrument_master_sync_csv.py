from __future__ import annotations

import csv

from scripts.build_kis_instrument_master_sync_csv import (
    _build_normalized_row,
    _dedupe_rows,
    _load_rows_from_csv,
    _normalize_market_code,
    _normalize_segment_value,
    _parse_args,
)


def test_parse_args_defaults() -> None:
    args = _parse_args(["--input", "a.csv", "--output", "out.csv"])
    assert args.input == ["a.csv"]
    assert args.output == "out.csv"
    assert args.default_market_code == "KRX"
    assert args.asset_class == "kr_stock"
    assert args.currency == "KRW"
    assert args.tick_size == "100"
    assert args.lot_size == "1"
    assert args.archive_dir is None
    assert args.archive_label is None


def test_normalize_market_code_maps_kospi_and_kosdaq() -> None:
    assert _normalize_market_code("KOSPI", default_market_code="KRX") == "KOSPI"
    assert _normalize_market_code("거래소", default_market_code="KRX") == "KOSPI"
    assert _normalize_market_code("KOSDAQ", default_market_code="KRX") == "KOSDAQ"
    assert _normalize_market_code("코스닥", default_market_code="KRX") == "KOSDAQ"


def test_normalize_segment_value_maps_known_aliases() -> None:
    assert _normalize_segment_value("KOSPI 100") == "KOSPI100"
    assert _normalize_segment_value("KOSDAQ-150") == "KOSDAQ150"
    assert _normalize_segment_value("KOSPI_LARGE") == "KOSPI_LARGE"


def test_build_normalized_row_from_simple_seed_shape() -> None:
    row = {"code": "005930", "name": "삼성전자", "market": "KOSPI"}
    headers = {"code": "code", "name": "name", "market": "market"}
    normalized = _build_normalized_row(
        row,
        headers,
        source_file="kospi.csv",
        default_market_code="KRX",
        asset_class="kr_stock",
        currency="KRW",
        tick_size="100",
        lot_size="1",
    )
    assert normalized is not None
    assert normalized["symbol"] == "005930"
    assert normalized["name"] == "삼성전자"
    assert normalized["market_code"] == "KOSPI"
    assert normalized["exchange_code"] == "KOSPI"
    assert normalized["metadata_market_segment"] == "KOSPI"
    assert normalized["metadata_segment"] == ""
    assert normalized["source_file"] == "kospi.csv"


def test_load_rows_from_csv_merges_kospi_and_kosdaq(tmp_path) -> None:
    kospi = tmp_path / "kospi.csv"
    kospi.write_text(
        "code,name,market\n005930,삼성전자,KOSPI\n000660,SK하이닉스,KOSPI\n",
        encoding="utf-8",
    )
    kosdaq = tmp_path / "kosdaq.csv"
    kosdaq.write_text(
        "code,name,market\n091990,셀트리온헬스케어,KOSDAQ\n035720,카카오,KOSDAQ\n",
        encoding="utf-8",
    )

    rows = _load_rows_from_csv(
        kospi,
        default_market_code="KRX",
        asset_class="kr_stock",
        currency="KRW",
        tick_size="100",
        lot_size="1",
    ) + _load_rows_from_csv(
        kosdaq,
        default_market_code="KRX",
        asset_class="kr_stock",
        currency="KRW",
        tick_size="100",
        lot_size="1",
    )

    deduped = _dedupe_rows(rows)
    assert len(deduped) == 4
    market_codes = {(row["symbol"], row["market_code"]) for row in deduped}
    assert ("005930", "KOSPI") in market_codes
    assert ("091990", "KOSDAQ") in market_codes


def test_load_rows_from_csv_supports_kis_style_headers(tmp_path) -> None:
    path = tmp_path / "kis_like.csv"
    path.write_text(
        "stck_shrn_iscd,hts_kor_isnm,market_code,segment,exchange_code\n123456,테스트,KOSDAQ,KOSDAQ 150,코스닥\n",
        encoding="utf-8",
    )
    rows = _load_rows_from_csv(
        path,
        default_market_code="KRX",
        asset_class="kr_stock",
        currency="KRW",
        tick_size="100",
        lot_size="1",
    )
    assert rows == [
        {
            "symbol": "123456",
            "name": "테스트",
            "market_code": "KOSDAQ",
            "asset_class": "kr_stock",
            "currency": "KRW",
            "tick_size": "100",
            "lot_size": "1",
            "is_active": "TRUE",
            "name_kr": "테스트",
            "exchange_code": "KOSDAQ",
            "metadata_market_segment": "KOSDAQ",
            "metadata_segment": "KOSDAQ150",
            "metadata_universe_segment": "KOSDAQ150",
            "metadata_kospi_kosdaq_cls_name": "",
            "metadata_mrkt_trtm_cls_name": "",
            "source_file": "kis_like.csv",
        }
    ]


def test_build_normalized_row_preserves_segment_and_market_labels() -> None:
    row = {
        "code": "005930",
        "name": "삼성전자",
        "kospi_kosdaq_cls_name": "거래소",
        "mrkt_trtm_cls_name": "거래소",
        "market_segment": "KOSPI 100",
    }
    headers = {
        "code": "code",
        "name": "name",
        "kospi_kosdaq_cls_name": "kospi_kosdaq_cls_name",
        "mrkt_trtm_cls_name": "mrkt_trtm_cls_name",
        "market_segment": "market_segment",
    }
    normalized = _build_normalized_row(
        row,
        headers,
        source_file="kospi.csv",
        default_market_code="KRX",
        asset_class="kr_stock",
        currency="KRW",
        tick_size="100",
        lot_size="1",
    )
    assert normalized is not None
    assert normalized["market_code"] == "KOSPI"
    assert normalized["exchange_code"] == "KOSPI"
    assert normalized["metadata_market_segment"] == "KOSPI"
    assert normalized["metadata_segment"] == "KOSPI100"
    assert normalized["metadata_universe_segment"] == "KOSPI100"
    assert normalized["metadata_kospi_kosdaq_cls_name"] == "거래소"
    assert normalized["metadata_mrkt_trtm_cls_name"] == "거래소"


def test_cli_writes_output_file(tmp_path) -> None:
    source = tmp_path / "master.csv"
    source.write_text(
        "code,name,market\n005930,삼성전자,KOSPI\n091990,셀트리온헬스케어,KOSDAQ\n",
        encoding="utf-8",
    )
    output = tmp_path / "normalized.csv"

    from scripts.build_kis_instrument_master_sync_csv import main

    rc = main(["--input", str(source), "--output", str(output)])
    assert rc == 0

    with output.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert rows[0]["market_code"] in {"KOSPI", "KOSDAQ"}


def test_cli_archives_source_files(tmp_path) -> None:
    source1 = tmp_path / "kospi.csv"
    source1.write_text("code,name,market\n005930,삼성전자,KOSPI\n", encoding="utf-8")
    source2 = tmp_path / "kosdaq.csv"
    source2.write_text("code,name,market\n091990,셀트리온헬스케어,KOSDAQ\n", encoding="utf-8")
    output = tmp_path / "normalized.csv"
    archive_dir = tmp_path / "archive"

    from scripts.build_kis_instrument_master_sync_csv import main

    rc = main(
        [
            "--input",
            str(source1),
            "--input",
            str(source2),
            "--output",
            str(output),
            "--archive-dir",
            str(archive_dir),
            "--archive-label",
            "2026-06-18",
        ]
    )
    assert rc == 0
    assert (archive_dir / "2026-06-18" / "kospi.csv").exists()
    assert (archive_dir / "2026-06-18" / "kosdaq.csv").exists()
