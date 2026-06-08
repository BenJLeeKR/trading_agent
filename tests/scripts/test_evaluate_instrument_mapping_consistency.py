from __future__ import annotations

from datetime import datetime, timezone

from scripts.evaluate_instrument_mapping_consistency import (
    MappingConsistencyReport,
    MappingGap,
    _parse_args,
)


def test_parse_args_defaults() -> None:
    args = _parse_args([])
    assert args.lookback_days == 7
    assert args.limit == 20
    assert args.output == "text"


def test_report_has_gap_and_text_rendering() -> None:
    now = datetime(2026, 6, 8, 8, 0, 0, tzinfo=timezone.utc)
    report = MappingConsistencyReport(
        generated_at=now,
        lookback_days=7,
        active_instrument_count=1234,
        unmapped_external_event_symbols=(
            MappingGap(symbol="A00001", row_count=3, last_seen_at=now),
        ),
        unmapped_broker_fill_symbols=(
            MappingGap(symbol="A00002", row_count=2, last_seen_at=now),
        ),
    )
    text = report.to_text()
    assert report.has_gap is True
    assert "A00001" in text
    assert "A00002" in text
    assert "active_instrument_count: 1234" in text


def test_report_json_serializes_datetimes() -> None:
    now = datetime(2026, 6, 8, 8, 0, 0, tzinfo=timezone.utc)
    report = MappingConsistencyReport(
        generated_at=now,
        lookback_days=3,
        active_instrument_count=10,
        unmapped_external_event_symbols=(),
        unmapped_broker_fill_symbols=(),
    )
    payload = report.to_json()
    assert "\"has_gap\": false" in payload
    assert "2026-06-08T08:00:00+00:00" in payload
