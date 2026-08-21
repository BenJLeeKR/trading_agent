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
``composer_output``, ``error``, ``duration_seconds``, ``ei_error_metadata``,
``ei_skipped``, ``ar_skipped``, ``fdc_skipped``, ``skip_reason_codes``,
``rate_limiter_waited_seconds``, ``rate_limiter_slot_acquired``,
``rate_limiter_queue_timeout``, ``rate_limiter_state_file_error``,
``provider_http_attempt_count``, ``provider_http_429_count``,
``provider_execution_seconds``, ``provider_final_status`` works
(e.g. the real ``AgentSubprocessOutput`` dataclass, or a lightweight
stand-in built in a test without importing ``scripts.run_agent_subprocess``).

2026-08-21 결함 수정: strict FDC rate limiter + retry-inclusive permit
관측성 필드 8개(``rate_limiter_*``/``provider_*``)가
``AgentSubprocessOutput``에는 추가됐지만 이 모듈의
``AgentSubprocessOutputLike``/``build_agent_subprocess_output_payload()``
에는 반영되지 않아, 실제 stdout JSON에서 조용히 누락되고 있었다 — 부모
프로세스(``deserialize_agent_output()``)는 항상 키 부재 기본값만 보고
있었다. 이 모듈이 stdout JSON 페이로드의 단일 진실 공급원이므로, 여기
빠진 필드는 그 어떤 하위 경로에서도 복구할 수 없다.

2026-08-21(2차) 신설: in-cycle FIFO 재대기열 관측성 필드 5개
(``rate_limiter_queue_ticket``/``rate_limiter_queue_position_at_first_
wait``/``rate_limiter_requeue_count``/``rate_limiter_final_waited_
seconds``/``rate_limiter_queue_deadline_exceeded``) 추가 — 위와 같은
실수를 반복하지 않도록 이 모듈의 두 지점(Protocol과 payload 빌더)을
반드시 함께 수정했다.
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
    ei_skipped: bool
    ar_skipped: bool
    fdc_skipped: bool
    skip_reason_codes: tuple[str, ...]
    rate_limiter_waited_seconds: float
    rate_limiter_slot_acquired: bool
    rate_limiter_queue_timeout: bool
    rate_limiter_state_file_error: bool
    provider_http_attempt_count: int
    provider_http_429_count: int
    provider_execution_seconds: float
    provider_final_status: str
    rate_limiter_queue_ticket: str
    rate_limiter_queue_position_at_first_wait: int
    rate_limiter_requeue_count: int
    rate_limiter_final_waited_seconds: float
    rate_limiter_queue_deadline_exceeded: bool


def build_agent_subprocess_output_payload(
    output: AgentSubprocessOutputLike,
) -> dict[str, Any]:
    """Build the JSON-safe payload dict written to subprocess stdout.

    This is the single source of truth for which keys the subprocess
    contract includes. ``compliance_output`` must be present — its absence
    (2026-08-17 회귀) caused the parent process to always reconstruct AC's
    output as ``AIComplianceOutput()`` defaults. ``ei_skipped``/``ar_skipped``/
    ``fdc_skipped``/``skip_reason_codes``(2026-08-17 관측성 수정)가 없으면
    부모 프로세스가 실제 FDC 생략 여부와 무관하게 항상 default(False/())로
    ``decision_json.ai_call_path``를 채워, 운영 관측 데이터를 왜곡한다.
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
        "ei_skipped": output.ei_skipped,
        "ar_skipped": output.ar_skipped,
        "fdc_skipped": output.fdc_skipped,
        "skip_reason_codes": output.skip_reason_codes,
        "rate_limiter_waited_seconds": output.rate_limiter_waited_seconds,
        "rate_limiter_slot_acquired": output.rate_limiter_slot_acquired,
        "rate_limiter_queue_timeout": output.rate_limiter_queue_timeout,
        "rate_limiter_state_file_error": output.rate_limiter_state_file_error,
        "provider_http_attempt_count": output.provider_http_attempt_count,
        "provider_http_429_count": output.provider_http_429_count,
        "provider_execution_seconds": output.provider_execution_seconds,
        "provider_final_status": output.provider_final_status,
        "rate_limiter_queue_ticket": output.rate_limiter_queue_ticket,
        "rate_limiter_queue_position_at_first_wait": (
            output.rate_limiter_queue_position_at_first_wait
        ),
        "rate_limiter_requeue_count": output.rate_limiter_requeue_count,
        "rate_limiter_final_waited_seconds": output.rate_limiter_final_waited_seconds,
        "rate_limiter_queue_deadline_exceeded": output.rate_limiter_queue_deadline_exceeded,
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
