#!/usr/bin/env python3
"""Debug: test _coerce_nested_json_strings with actual types."""
import sys, json
sys.path.insert(0, "/workspace/agent_trading/src")

from agent_trading.services.ai_agents.schemas import EventInterpretationOutput, AggregateEventView
from agent_trading.services.ai_agents.provider_client import _coerce_nested_json_strings

# Simulate what DeepSeek returns: aggregate_view as a JSON string
# Uses the actual AggregateEventView schema fields
simulated_response = {
    "schema_version": "v1",
    "agent_name": "event_interpretation",
    "symbol": "005930",
    "issuer_code": "KR7005930003",
    "events": [],
    "aggregate_view": '{"overall_bias": "bullish", "event_conflict": false, "top_reason_codes": ["strong_momentum"], "opposing_evidence": []}'
}

print("=" * 60)
print("Before coercion:")
print(f"  aggregate_view type: {type(simulated_response['aggregate_view']).__name__}")
print(f"  aggregate_view value: {simulated_response['aggregate_view']!r}")
print()

# Apply coercion
coerced = _coerce_nested_json_strings(EventInterpretationOutput, simulated_response)

print("After coercion:")
print(f"  aggregate_view type: {type(coerced['aggregate_view']).__name__}")
if isinstance(coerced['aggregate_view'], dict):
    print(f"  aggregate_view keys: {list(coerced['aggregate_view'].keys())}")
print()

# Try to construct
try:
    obj = EventInterpretationOutput(**coerced)
    print(f"✅ Construction SUCCESS")
    print(f"  aggregate_view type: {type(obj.aggregate_view).__name__}")
    print(f"  overall_bias: {obj.aggregate_view.overall_bias}")
except Exception as e:
    print(f"❌ Construction FAILED: {e}")
