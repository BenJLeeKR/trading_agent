from __future__ import annotations

from agent_trading.services.signal_feature_batch_runtime import (
    SignalFeatureBatchRuntimeSpec,
    should_run_signal_feature_retry_batch,
    should_run_signal_feature_tail_retry,
)


def test_runtime_spec_builds_primary_and_retry_commands() -> None:
    spec = SignalFeatureBatchRuntimeSpec(
        command_name_prefix="after_market_signal_feature",
        input_path="data/signal_feature_snapshot_input.json",
        freeze_purpose="signal_feature_after_market",
        trigger_type="after_market_scheduler",
    )

    assert spec.retry_input_path == "data/signal_feature_snapshot_input.tail_retry.json"
    assert spec.primary_input_name == "after_market_signal_feature_input"
    assert spec.retry_batch_name == "after_market_signal_feature_batch_tail_retry"
    assert spec.build_input_command(python_bin="python3") == [
        "python3",
        "-m",
        "scripts.generate_signal_feature_snapshot_input",
        "--output",
        "data/signal_feature_snapshot_input.json",
        "--output-format",
        "json",
        "--freeze-purpose",
        "signal_feature_after_market",
        "--trigger-type",
        "after_market_scheduler",
    ]
    assert spec.build_batch_command(python_bin="python3") == [
        "python3",
        "-m",
        "scripts.build_signal_feature_snapshots",
        "--input",
        "data/signal_feature_snapshot_input.json",
        "--output",
        "json",
        "--trigger-type",
        "after_market_scheduler",
    ]


def test_runtime_retry_predicates_follow_metrics() -> None:
    assert should_run_signal_feature_tail_retry({"fetch_error_count": 1}) is True
    assert should_run_signal_feature_tail_retry({"fetch_error_count": 0}) is False
    assert should_run_signal_feature_retry_batch({"generated_count": 1}) is True
    assert should_run_signal_feature_retry_batch({"generated_count": 0}) is False
