"""Import-safe helpers for ``scripts/run_agent_subprocess.py`` stdout JSON.

Extracted from ``scripts/run_agent_subprocess.py::_write_output()`` so the
exact JSON payload shape (in particular, which keys are written) can be
round-trip tested without importing that script module.

``scripts/run_agent_subprocess.py`` executes filesystem side effects at
import time (diagnostic log directory creation under ``/workspace/...``),
which fails inside read-only sandboxes (e.g. this repo's dev-validation
harness container). This module has **zero import-time side effects** — no
filesystem access, no env var reads, no subprocess execution — so tests can
import it directly regardless of that constraint.

``output`` below is duck-typed: any object exposing ``success``,
``event_output``, ``risk_output``, ``compliance_output``,
``composer_output``, ``error``, ``duration_seconds``, ``ei_error_metadata``
works (e.g. the real ``AgentSubprocessOutput`` dataclass, or a lightweight
stand-in built in a test without importing ``scripts.run_agent_subprocess``).
"""

from __future__ import annotations

import json
from typing import Any, Protocol, TextIO


class AgentSubprocessOutputLike(Protocol):
    """Structural type for the subprocess output payload.

    Matches ``scripts/run_agent_subprocess.py::AgentSubprocessOutput`` by
    shape only — this module never imports that class.
    """

    success: bool
    event_output: dict[str, Any]
    risk_output: dict[str, Any]
    compliance_output: dict[str, Any]
    composer_output: dict[str, Any]
    error: str | None
    duration_seconds: float
    ei_error_metadata: dict[str, Any] | None


def build_agent_subprocess_output_payload(
    output: AgentSubprocessOutputLike,
) -> dict[str, Any]:
    """Build the JSON-safe payload dict written to subprocess stdout.

    This is the single source of truth for which keys the subprocess
    contract includes. ``compliance_output`` must be present — its absence
    (2026-08-17 회귀) caused the parent process to always reconstruct AC's
    output as ``AIComplianceOutput()`` defaults.
    """
    return {
        "success": output.success,
        "event_output": output.event_output,
        "risk_output": output.risk_output,
        "compliance_output": output.compliance_output,
        "composer_output": output.composer_output,
        "error": output.error,
        "duration_seconds": output.duration_seconds,
        "ei_error_metadata": output.ei_error_metadata,
    }


def write_agent_subprocess_output(
    output: AgentSubprocessOutputLike,
    stream: TextIO,
) -> None:
    """Serialize ``output`` to ``stream`` as JSON (subprocess stdout contract).

    Preserves the exact serialization options used by the original
    ``_write_output()`` (``default=str``, ``ensure_ascii=False``) and
    flushes ``stream`` afterward.
    """
    json.dump(
        build_agent_subprocess_output_payload(output),
        stream,
        default=str,
        ensure_ascii=False,
    )
    stream.flush()
