from __future__ import annotations

from scripts.analyze_trigger_proxy_attribution import (
    _coerce_json_list,
    _coerce_json_mapping,
)


def test_coerce_json_mapping_accepts_serialized_json() -> None:
    payload = _coerce_json_mapping('{"active": true, "shadow_floor_bucket": "mild_relax"}')
    assert payload == {
        "active": True,
        "shadow_floor_bucket": "mild_relax",
    }


def test_coerce_json_list_accepts_serialized_json() -> None:
    payload = _coerce_json_list('["a", "b", "c"]')
    assert payload == ["a", "b", "c"]


def test_coerce_json_mapping_rejects_non_mapping_json() -> None:
    payload = _coerce_json_mapping('["not", "mapping"]')
    assert payload == {}
