from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

DEFAULT_SIGNAL_FEATURE_AFTER_MARKET_FREEZE_PURPOSE = "signal_feature_after_market"
DEFAULT_SIGNAL_FEATURE_AFTER_MARKET_TRIGGER_TYPE = "after_market_scheduler"


@dataclass(slots=True, frozen=True)
class SignalFeatureBatchRuntimeSpec:
    command_name_prefix: str
    input_path: str
    freeze_purpose: str = DEFAULT_SIGNAL_FEATURE_AFTER_MARKET_FREEZE_PURPOSE
    trigger_type: str = DEFAULT_SIGNAL_FEATURE_AFTER_MARKET_TRIGGER_TYPE

    @property
    def retry_input_path(self) -> str:
        path = Path(self.input_path)
        if path.suffix:
            return str(path.with_name(f"{path.stem}.tail_retry{path.suffix}"))
        return f"{self.input_path}.tail_retry.json"

    @property
    def primary_input_name(self) -> str:
        return f"{self.command_name_prefix}_input"

    @property
    def primary_batch_name(self) -> str:
        return f"{self.command_name_prefix}_batch"

    @property
    def retry_input_name(self) -> str:
        return f"{self.command_name_prefix}_input_tail_retry"

    @property
    def retry_batch_name(self) -> str:
        return f"{self.command_name_prefix}_batch_tail_retry"

    def build_input_command(
        self,
        *,
        python_bin: str,
        output_path: str | None = None,
        retry_from_input: str | None = None,
    ) -> list[str]:
        argv = [
            python_bin,
            "-m",
            "scripts.generate_signal_feature_snapshot_input",
            "--output",
            output_path or self.input_path,
            "--output-format",
            "json",
            "--freeze-purpose",
            self.freeze_purpose,
            "--trigger-type",
            self.trigger_type,
        ]
        if retry_from_input:
            argv.extend(["--retry-from-input", retry_from_input])
        return argv

    def build_batch_command(
        self,
        *,
        python_bin: str,
        input_path: str | None = None,
    ) -> list[str]:
        return [
            python_bin,
            "-m",
            "scripts.build_signal_feature_snapshots",
            "--input",
            input_path or self.input_path,
            "--output",
            "json",
            "--trigger-type",
            self.trigger_type,
        ]


def should_run_signal_feature_tail_retry(
    metrics: Mapping[str, Any] | None,
) -> bool:
    return _coerce_metric_int(metrics, "fetch_error_count") > 0


def should_run_signal_feature_retry_batch(
    metrics: Mapping[str, Any] | None,
) -> bool:
    return _coerce_metric_int(metrics, "generated_count") > 0


def _coerce_metric_int(
    metrics: Mapping[str, Any] | None,
    key: str,
) -> int:
    if metrics is None:
        return 0
    try:
        return int(metrics.get(key, 0))
    except (TypeError, ValueError):
        return 0
