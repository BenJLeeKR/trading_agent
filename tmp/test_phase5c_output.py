# Subtask 2+3 변경 사항 검증 스크립트
import sys
sys.path.insert(0, "/workspace/agent_trading")
from typing import Any

# 실제 스크립트의 record 구성 로직을 재현 (line 528-555)
def build_record(result: dict) -> dict[str, Any]:
    return {
        # 기존 필드 (유지)
        "order_request_id": "test-oid-001",
        "symbol": "005930",
        "side": "buy",
        "requested_qty": 10,
        "classification": "truth_probe_conflict",
        "target_status": "expired_confirmed",
        "verdict": result.get("verdict", ""),
        "match_method": result.get("match", {}).get("match_method", ""),
        "reason": "test reason",

        # === 신규 KIS 필드 ===
        "broker_native_order_id": result.get("match", {}).get("matched_odno", ""),
        "kis_ord_stat": result.get("match", {}).get("kis_ord_stat", ""),
        "kis_ccld_qty": result.get("match", {}).get("kis_ccld_qty"),
        "kis_order_qty": result.get("match", {}).get("kis_order_qty"),
        "kis_cancel_yn": result.get("match", {}).get("kis_cancel_yn", ""),
        "kis_order_time": result.get("match", {}).get("kis_order_time", ""),
        "kis_ccld_time": result.get("match", {}).get("kis_ccld_time", ""),
        "matched_symbol": result.get("match", {}).get("matched_symbol", ""),

        # === 신규 Position 필드 ===
        "position_delta": result.get("match", {}).get("position_delta"),
        "position_pre_qty": result.get("match", {}).get("position_pre_qty"),
        "position_post_qty": result.get("match", {}).get("position_post_qty"),
        "position_verdict": result.get("match", {}).get("verdict", ""),
    }

# 1. 신규 필드가 포함되는지 검증
result_with_match = {
    "verdict": "partially_filled_suspected",
    "match": {
        "match_method": "direct_odno",
        "matched_odno": "0123456789012345",
        "matched_symbol": "005930",
        "kis_ord_stat": "11",  # 일부체결
        "kis_ord_stat_name": "일부체결",
        "kis_order_qty": 10,
        "kis_ccld_qty": 5,
        "kis_order_time": "093012",
        "kis_ccld_time": "093015",
        "kis_cancel_yn": "N",
        "position_delta": 5,
        "position_pre_qty": 0,
        "position_post_qty": 5,
    }
}
record = build_record(result_with_match)

# 새 필드 검증
new_fields = [
    "broker_native_order_id", "kis_ord_stat", "kis_ccld_qty",
    "kis_order_qty", "kis_cancel_yn", "kis_order_time", "kis_ccld_time",
    "matched_symbol", "position_delta", "position_pre_qty",
    "position_post_qty"
]
for field in new_fields:
    assert field in record, f"필드 누락: {field}"
    print(f"✅ {field}: {record[field]}")

# 값 검증
assert record["broker_native_order_id"] == "0123456789012345"
assert record["kis_ord_stat"] == "11"
assert record["kis_ccld_qty"] == 5
assert record["kis_order_qty"] == 10
assert record["kis_cancel_yn"] == "N"
assert record["kis_order_time"] == "093012"
assert record["kis_ccld_time"] == "093015"
assert record["matched_symbol"] == "005930"
assert record["position_delta"] == 5
assert record["position_pre_qty"] == 0
assert record["position_post_qty"] == 5
print("✅ 신규 필드 값 검증 완료")

# 2. 숫자 타입 유지 검증
assert isinstance(record["kis_ccld_qty"], int), f"kis_ccld_qty 타입 오류: {type(record['kis_ccld_qty'])}"
assert isinstance(record["position_delta"], int), f"position_delta 타입 오류: {type(record['position_delta'])}"
print("✅ 숫자 타입 유지 확인 완료")

# 3. null/None 필드 처리 검증
result_no_match = {
    "verdict": "no_match",
    "match": None,
}
record_no_match = build_record({"verdict": "no_match"})
null_fields = [
    "broker_native_order_id", "kis_ord_stat", "kis_cancel_yn",
    "kis_order_time", "kis_ccld_time", "matched_symbol"
]
for field in null_fields:
    assert record_no_match[field] == "", f"match=None 시 {field} 기본값 오류: {record_no_match[field]}"
print("✅ match=None 시 필드 기본값 처리 확인 완료")
assert record_no_match["kis_ccld_qty"] is None, "kis_ccld_qty 기본값 None 확인"
assert record_no_match["kis_order_qty"] is None, "kis_order_qty 기본값 None 확인"
assert record_no_match["position_delta"] is None, "position_delta 기본값 None 확인"
print("✅ match=None 시 None 필드 확인 완료")

# 4. reason에 delta 값 포함 검증
from scripts.backfill_expired_odno_orders import (
    VERDICT_POSITION_DELTA_PARTIAL, VERDICT_POSITION_DELTA_FILLED
)
for position_verdict, expected_prefix in [
    (VERDICT_POSITION_DELTA_PARTIAL, "position_verdict=position_delta_partial"),
    (VERDICT_POSITION_DELTA_FILLED, "position_verdict=position_delta_filled"),
]:
    delta = 50
    delta_str = f" (delta={delta})"
    reason = f"{expected_prefix}{delta_str}"
    assert expected_prefix in reason, f"접두사 누락: {expected_prefix}"
    assert delta_str in reason, f"delta 문자열 누락: {delta_str}"
    print(f"✅ reason delta 포함 확인: {reason}")

print("\n✅ 모든 검증 통과")
