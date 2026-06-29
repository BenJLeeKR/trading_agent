from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from scripts.build_instrument_status_snapshots import (
    TargetInstrument,
    _build_snapshot_entity,
    _derive_status_reason_codes,
    _parse_business_date,
    _resolve_snapshot_at,
)


def test_parse_business_date_defaults_to_kst_today(monkeypatch) -> None:
    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2026, 6, 29, 10, 0, 0)
            if tz is None:
                return value
            return value.replace(tzinfo=tz)

    monkeypatch.setattr(
        "scripts.build_instrument_status_snapshots.datetime",
        _FixedDatetime,
    )

    assert _parse_business_date(None) == date(2026, 6, 29)


def test_resolve_snapshot_at_defaults_to_0505_kst() -> None:
    snapshot_at = _resolve_snapshot_at(None, business_date=date(2026, 6, 29))
    assert snapshot_at.tzinfo == timezone.utc
    assert snapshot_at.isoformat() == "2026-06-28T20:05:00+00:00"


def test_derive_status_reason_codes_marks_restricted_status() -> None:
    reasons = _derive_status_reason_codes(
        {
            "tr_stop_yn": "Y",
            "admn_item_yn": "Y",
            "nxt_tr_stop_yn": "N",
            "temp_stop_yn": "Y",
            "iscd_stat_cls_code": "05",
        }
    )

    assert reasons == [
        "trading_halt",
        "administrative_issue",
        "temporary_halt",
        "status_code:05",
        "restricted_status:05",
    ]


def test_build_snapshot_entity_maps_payload_fields() -> None:
    target = TargetInstrument(
        instrument_id=uuid4(),
        symbol="000660",
        market_code="KRX",
        market_segment="KOSPI",
        target_sources=("active_membership",),
    )
    snapshot = _build_snapshot_entity(
        target=target,
        snapshot_at=datetime(2026, 6, 29, 20, 5, tzinfo=timezone.utc),
        source_type="kis_stock_basic_info",
        status_scope="instrument",
        payload={
            "tr_stop_yn": "N",
            "admn_item_yn": "N",
            "nxt_tr_stop_yn": "Y",
            "mket_id_cd": "STK",
            "scty_grp_id_cd": "ST",
            "excg_dvsn_cd": "KRX",
            "prdt_type_cd": "300",
        },
    )

    assert snapshot.instrument_id == target.instrument_id
    assert snapshot.nxt_tr_stop_yn == "Y"
    assert snapshot.mket_id_cd == "STK"
    assert snapshot.status_reason_codes == ["next_session_halt"]
