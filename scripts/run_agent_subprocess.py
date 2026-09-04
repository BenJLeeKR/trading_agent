#!/usr/bin/env python3
"""Subprocess entry point for running agents (EI/AR/AC/FDC) with isolation.

stdin: JSON-serialized AgentSubprocessInput
stdout: JSON-serialized AgentSubprocessOutput (or error)

Usage:
    python3 scripts/run_agent_subprocess.py < input.json

Design rationale
----------------
Phase 4 subprocess isolation: C-level httpx I/O blocking can bypass
asyncio.wait_for() and httpx.Timeout.  The only reliable timeout is the
scheduler's subprocess-level SIGTERM/SIGKILL.  By running the 3 agents
in a separate subprocess, the parent can SIGKILL the child when the
combined timeout (35s) is exceeded, forcibly releasing any C-level
blocking.

This module is intentionally self-contained — it imports the agent
classes directly and does not depend on the orchestrator's runtime
bootstrap.  Environment variables (API keys, endpoints) are inherited
from the parent process.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

# ---------------------------------------------------------------------------
# Agent imports — these trigger httpx client creation, which is fine in a
# short-lived subprocess.  The subprocess exits after one cycle.
# ---------------------------------------------------------------------------
from agent_trading.services.ai_agents.base import (
    AgentExecutionRequest,
    AIProviderClient,
)
from agent_trading.services.ai_agents.event_interpretation import (
    DeterministicEventInterpretationAgent,
)
from agent_trading.services.ai_agents.ai_risk import DeterministicAIRiskAgent
from agent_trading.services.ai_agents.ai_compliance import (
    DeterministicAIComplianceAgent,
)
from agent_trading.services.ai_agents.final_decision_composer import (
    FinalDecisionComposerAgent,
    StubFinalDecisionComposerAgent,
)
from agent_trading.services.ai_agents.subprocess_io import (
    write_agent_subprocess_output,
)
from agent_trading.services.ai_agents.fdc_rate_limiter import (
    DEFAULT_MAX_WAIT_SECONDS as _FDC_MAX_WAIT_SECONDS,
    wait_for_fdc_slot,
)
from agent_trading.services.ai_agents.provider_client import (
    PermitCallback,
    PermitResult,
)
from agent_trading.services.fdc_provider_global_gate import FdcProviderGlobalGate
from agent_trading.services.ai_agents.schemas import (
    AIComplianceOutput,
    AIRiskOutput,
    EventInterpretationOutput,
    FinalDecisionComposerOutput,
    AggregateEventView,
)
from agent_trading.domain.entities import (
    CashBalanceSnapshotEntity,
    DecisionContextEntity,
    ExternalEventEntity,
    PositionSnapshotEntity,
    RiskLimitSnapshotEntity,
    SignalFeatureSnapshotEntity,
)
from agent_trading.services.common_types import dataclass_to_dict, dict_to_dataclass
from agent_trading.services.market_regime import MarketRegimeAssessment
from agent_trading.services.deterministic_trigger_engine import (
    DeterministicTriggerAssessment,
)
from agent_trading.services.portfolio_allocation import PortfolioAllocationAssessment
from agent_trading.services.strategy_selection import StrategySelectionAssessment
from agent_trading.services.common_types import (
    AIPolicyContextView,
    ScoreResult,
)
from agent_trading.services.translation import (
    is_missing_agent_symbol,
    normalize_decision_type,
)
from agent_trading.config.settings import _resolve_provider_model_id

logger = logging.getLogger(__name__)
_PER_AGENT_TIMEOUT = 30
# 2026-08-21 신설(strict FDC rate limiter + retry-inclusive permit 전환).
#
# 배경: 기존에는 FDC rate limiter 대기가 이 30초 per-agent timeout **밖**
# (subprocess 전체 90초 예산의 여유분)에서 단 1회만 일어났다. 이번
# 전환으로 permit 획득이 `provider_client.py`의 재시도 루프 안으로
# 들어가면서 최초 요청 + 매 재시도(`MAX_RETRIES=3`)마다 permit을 다시
# 획득한다 — 즉 이 대기가 이제는 FDC 호출 자체의 timeout **예산 안에서**
# 최대 3회 반복될 수 있으므로, 공유 30초로는 부족하다.
#
# 계산 근거: subprocess 전체 timeout(``DecisionAgentRunner.
# subprocess_timeout``, 기본 90초) - EI/AR/AC 소요(수 ms, 무시 가능) -
# 프로세스 spawn/직렬화 오버헤드 및 SIGTERM 유예 등 안전마진(약 20초)
# = 70초. 이 70초는 strict queue 대기(permit 획득)와 provider 실행
# 시간을 합친 **상한**이다 — `fdc_rate_limiter.DEFAULT_MAX_WAIT_SECONDS`
# (18.0초)는 Gemini HTTP 왕복을 약 3초/회로 가정한 설계 목표치일 뿐,
# 이 70초 자체가 "최악 시간을 보장"하지는 않는다(자세한 계산과 그
# 한계는 ``fdc_rate_limiter.py``의 ``DEFAULT_MAX_WAIT_SECONDS`` 주석
# 참고). 실제 HTTP 왕복이 이 가정보다 오래 걸려도, 아래
# ``asyncio.wait_for(..., timeout=_FDC_PER_AGENT_TIMEOUT)``가 70초에서
# 확정적으로 강제 종료해 `provider_timeout` fallback으로 귀결시킨다 —
# 즉 시간 상한 자체의 보장은 이 상수(및 그 `asyncio.wait_for` 적용)가
# 담당하고, `DEFAULT_MAX_WAIT_SECONDS` 산식은 그 예산을 나누는 설계
# 목표치에 불과하다. EI/AR/AC는 재시도/permit 대기가 없으므로 기존
# 공유 ``_PER_AGENT_TIMEOUT=30``을 그대로 유지한다.
_FDC_PER_AGENT_TIMEOUT = 70

# Configure logging to stderr so parent can capture subprocess diagnostics.
# Without this, all logger.info() calls are silently dropped.
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# File-based diagnostic logging (bypasses pipe — survives timeout).
# ★ 반드시 /workspace/agent_trading/logs 경로 사용 (운영 정책)
# 2026-08-18 KST: 디렉터리 생성을 모듈 import 시점(top-level)에서 실제
# 로그 기록 직전으로 늦췄다 — import-time에 파일시스템 write가 일어나면
# read-only 마운트 환경(예: harness accept-backend-file 검증 컨테이너)
# 에서 이 모듈을 import하는 것만으로 collection 자체가 실패했다. 경로/
# 파일명 규칙과 로그 내용 계약, "best-effort로 실패를 무시한다"는 기존
# 의미론은 그대로 유지한다.
import os as _os
_DIAG_LOG_DIR = "/workspace/agent_trading/logs"
_DIAG_LOG = f"{_DIAG_LOG_DIR}/subprocess_diag_{os.getpid()}.log"


def _ensure_diag_log_dir() -> None:
    """Diag 로그 디렉터리가 존재하도록 보장한다(최초 기록 시점에만 호출).

    실패해도(예: read-only 파일시스템) 호출자(``_diag()``)가 통째로
    best-effort로 무시하므로 여기서는 예외를 그대로 전파한다.
    """
    _os.makedirs(_DIAG_LOG_DIR, exist_ok=True)


def _diag(msg: str) -> None:
    """Write a timestamped diagnostic message to a file.

    This file survives the parent's timeout+kill cycle, providing
    visibility into what the subprocess was doing before it hung.
    """
    try:
        _ensure_diag_log_dir()
        with open(_DIAG_LOG, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] PID={os.getpid()} {msg}\n")
    except Exception:
        pass  # best-effort


# ---------------------------------------------------------------------------
# Serialization contracts
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class AgentSubprocessInput:
    """Input payload serialized from the parent orchestrator.

    This is a flat, JSON-safe representation of the data needed to
    reconstruct ``AgentExecutionRequest`` inside the subprocess.
    """

    decision_context_id: str | None
    correlation_id: str
    symbol: str | None
    market: str | None
    source_type: str

    # AssembledContext fields (JSON-safe)
    context: dict[str, Any] = field(default_factory=dict)

    # Agent output overrides (from previous runs in same cycle)
    event_interpretation_output: dict[str, Any] | None = None
    ai_risk_output: dict[str, Any] | None = None
    ai_compliance_output: dict[str, Any] | None = None

    # Provider configuration hints
    model_id: str | None = None
    prompt_id: str | None = None

    # --- Provider configuration for AI client creation ---
    llm_provider: str = ""
    provider_api_key: str = ""
    provider_base_url: str = ""
    provider_model_id: str = ""
    provider_timeout_seconds: int = 60

    # --- Fields from serialize_agent_input (top-level keys) ---
    score: dict[str, Any] | None = None
    positional_args: tuple[Any, ...] = ()

    # --- subprocess 실행 모드(2026-08-27, held_position 실제 dispatcher
    # 신설 — PR #359 리뷰 보정) ---
    # "full"(기본값, 기존 동작): EI/AR/AC/FDC를 한 subprocess에서 순차
    #   실행한다 — flag=false·비대상 lane은 항상 이 모드만 쓰이므로
    #   기존 동작과 100% 동일하다.
    # "pre_fdc": EI/AR/AC + FDC skip 판정까지만 수행한다. FDC-ready면
    #   FDC를 호출하지 않고 즉시 반환한다(``AgentSubprocessOutput.
    #   requires_fdc_dispatch=True``) — 호출자(``DecisionAgentRunner``)가
    #   quota reservation을 기다린 뒤 별도로 "fdc_only" subprocess를
    #   스폰한다.
    # "fdc_only": 이미 확보한 reservation grant로 FDC one-shot만
    #   실행한다. EI/AR/AC는 전혀 호출하지 않는다 — 대신
    #   ``event_interpretation_output``/``ai_risk_output``/
    #   ``ai_compliance_output``(위 필드, pre_fdc의 결과)로 프롬프트를
    #   재구성한다.
    mode: str = "full"

    # --- "fdc_only" 전용: 호출자가 이미 확보한 reservation grant ---
    # (``FdcQuotaCoordinator.try_reserve()``가 GRANTED했을 때만 이
    # 필드들이 채워진다 — DENIED/오류 상태로는 이 모드가 호출되지 않는다.)
    reservation_id: str | None = None
    reservation_job_id: str | None = None
    reservation_attempt_no: int = 1
    reservation_quota_scope: str | None = None
    reservation_window_count_before_grant: int = 0


@dataclass(slots=True, frozen=True)
class AgentSubprocessOutput:
    """Output payload serialized back to the parent orchestrator.

    Contains the structured outputs of all agents, or error details
    if the subprocess failed before completing all agents.
    """

    success: bool
    event_output: dict[str, Any] = field(default_factory=dict)
    risk_output: dict[str, Any] = field(default_factory=dict)
    compliance_output: dict[str, Any] = field(default_factory=dict)
    composer_output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_seconds: float = 0.0
    # ★ EI 실패 시 error metadata (orchestrator가 structured_output_json["__error__"]에 주입)
    ei_error_metadata: dict[str, Any] | None = None
    # 2026-08-17 관측성 수정: in-process 경로(decision_agent_runner.py)의
    # AIDecisionInputs.ei_skipped/ar_skipped/fdc_skipped/skip_reason_codes와
    # 대응 — 이 subprocess가 실제로 EI/FDC를 생략했는지를 부모 프로세스에
    # 전달한다. AR은 이 스크립트에서 생략 로직이 없으므로 항상 False다.
    ei_skipped: bool = False
    ar_skipped: bool = False
    fdc_skipped: bool = False
    skip_reason_codes: tuple[str, ...] = ()
    # FDC cycle-scoped batch queue lifecycle shadow(Phase 1) 전용 —
    # AIDecisionInputs.fdc_ready_at와 동일한 의미(ISO-8601 UTC, 빈
    # 문자열이면 fdc_skipped=True).
    fdc_ready_at: str = ""
    # 2026-08-21 신설: strict FDC rate limiter + retry-inclusive permit
    # 관측성 필드. 새 DB 테이블/마이그레이션 없이, 이 subprocess ↔ 부모
    # 프로세스 간 기존 JSON round-trip 경로(``agent_runs.structured_
    # output_json`` 등)를 그대로 재사용한다. FDC가 생략(``fdc_skipped``)
    # 되거나 provider 미설정(Stub)이면 모두 기본값을 유지한다.
    rate_limiter_waited_seconds: float = 0.0
    rate_limiter_slot_acquired: bool = True
    rate_limiter_queue_timeout: bool = False
    rate_limiter_state_file_error: bool = False
    provider_http_attempt_count: int = 0
    provider_http_429_count: int = 0
    provider_execution_seconds: float = 0.0
    provider_final_status: str = ""
    # 2026-08-21(2차) 신설: in-cycle FIFO 재대기열 관측성 필드.
    # ``rate_limiter_queue_position_at_first_wait``는 대기가 전혀
    # 없었으면(즉시 grant) ``-1``을 sentinel로 쓴다(0은 "내 앞에 대기자가
    # 0명"이라는 실제 의미 있는 값이므로 구분 필요).
    rate_limiter_queue_ticket: str = ""
    rate_limiter_queue_position_at_first_wait: int = -1
    rate_limiter_requeue_count: int = 0
    rate_limiter_final_waited_seconds: float = 0.0
    rate_limiter_queue_deadline_exceeded: bool = False
    # 2026-08-27 신설(held_position 실제 dispatcher, PR #359 리뷰 보정) —
    # mode="pre_fdc"에서 FDC-ready(=fdc_skipped=False)로 확정됐지만 FDC를
    # 아직 호출하지 않았을 때만 True. 이 경우 composer_output은 비어
    # 있고, 호출자가 quota reservation을 기다린 뒤 별도로 mode="fdc_only"
    # subprocess를 스폰해야 한다. mode="full"/"fdc_only" 출력에서는 항상
    # False다(기존 동작·계약 불변).
    requires_fdc_dispatch: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_uuid(value: str | None) -> UUID | None:
    """JSON-safe dict → UUID 변환 (None-safe)."""
    if value is None:
        return None
    return UUID(value) if isinstance(value, str) else value


def _safe_decimal(value: str | float | None) -> Decimal | None:
    """JSON-safe dict → Decimal 변환 (None-safe)."""
    if value is None:
        return None
    return Decimal(str(value)) if not isinstance(value, Decimal) else value


def _safe_datetime(value: object) -> datetime | None:
    """ISO format str → datetime 변환 (None-safe).

    ``datetime`` 객체는 그대로 반환 (passthrough).
    ``str``은 ``datetime.fromisoformat()``으로 파싱.
    그 외 값 (``None`` 포함)은 ``None`` 반환.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


class _FdcPermitAccumulator:
    """FDC 1회 호출(최초 요청 + 매 재시도) 동안의 permit 판정을 누적한다.

    ``provider_client.py``는 이 클래스도, ``fdc_rate_limiter.py``도
    전혀 알지 못한다 — 이 accumulator의 ``acquire`` 메서드가
    ``PermitCallback`` 모양(``provider_client.PermitResult`` 반환)을
    만족하는 얕은 어댑터 역할을 하며, 실제 구현(``wait_for_fdc_slot``)은
    이 파일(최상위 호출자)에서만 안다. 여러 permit 호출의 대기 시간을
    합산해 최종 관측성 필드로 노출한다.

    2026-08-21(2차) in-cycle FIFO 재대기 도입: **최초 HTTP 요청**의
    permit 획득(``acquire()``의 첫 호출)에만 ``allow_requeue=True``를
    전달해 1회 재대기(FIFO tail 재등록)를 허용한다. 그 이후의 모든
    호출(``provider_client.py``의 429/5xx 재시도 permit 획득)은
    ``allow_requeue=False``로 호출해 재대기를 허용하지 않는다 —
    재시도마다 최대 36초(18+18)씩 재대기를 허용하면
    ``_FDC_PER_AGENT_TIMEOUT``(70초) 예산을 초과할 수 있기 때문이다
    (``fdc_rate_limiter.py`` 모듈 docstring "2026-08-21(2차)" 절의
    예산 계산 참고). ``provider_client.py``는 이 구분을 전혀 모른다 —
    이 accumulator가 호출 횟수(``self._call_count``)만으로 내부적으로
    판단한다.
    """

    def __init__(
        self, *, lane: str = "unknown", global_gate: FdcProviderGlobalGate | None = None,
    ) -> None:
        self.total_waited_seconds = 0.0
        self.slot_acquired = False
        self.queue_timeout = False
        self.state_file_error = False
        self.lane = lane
        self.last_queue_ticket: str | None = None
        self.queue_position_at_first_wait: int | None = None
        self.requeue_count = 0
        self.final_waited_seconds = 0.0
        self.queue_deadline_exceeded = False
        self._call_count = 0
        self._global_gate = global_gate

    async def acquire(self) -> PermitResult:
        self._call_count += 1
        allow_requeue = self._call_count == 1
        result = await wait_for_fdc_slot(
            max_wait_seconds=_FDC_MAX_WAIT_SECONDS,
            allow_requeue=allow_requeue,
            lane=self.lane,
        )
        self.total_waited_seconds += result.waited_seconds
        self.final_waited_seconds = result.final_waited_seconds
        if result.granted:
            self.slot_acquired = True
        if result.queue_timeout:
            self.queue_timeout = True
        if result.state_file_error:
            self.state_file_error = True
        if self.queue_position_at_first_wait is None:
            self.queue_position_at_first_wait = result.queue_position_at_first_wait
        self.last_queue_ticket = result.queue_ticket
        self.requeue_count = max(self.requeue_count, result.requeue_count)
        if result.queue_deadline_exceeded:
            self.queue_deadline_exceeded = True
        denial_reason: str | None = None
        if result.queue_timeout:
            denial_reason = "queue_timeout"
        elif result.state_file_error:
            denial_reason = "state_file_error"

        # PR D(2026-09-03) — legacy limiter가 거부하면 global gate는
        # 아예 호출하지 않는다(§4.2 설계 문서 확정 순서: legacy limiter
        # 먼저, grant 후에만 global gate). ``self._global_gate``가
        # ``None``이면(flag off) 이 블록 전체가 완전 no-op이다.
        if result.granted and denial_reason is None and self._global_gate is not None:
            gate_result = await self._global_gate.acquire(
                caller_lane="legacy", caller_id=f"legacy:{self.lane}",
            )
            if not gate_result.granted:
                return PermitResult(
                    granted=False,
                    waited_seconds=result.waited_seconds,
                    denial_reason=gate_result.denial_reason,
                )

        return PermitResult(
            granted=result.granted,
            waited_seconds=result.waited_seconds,
            denial_reason=denial_reason,
        )


def _build_agent_triplet(
    *,
    provider_client: AIProviderClient | None,
    model_id: str | None,
    acquire_permit: PermitCallback | None = None,
) -> tuple[
    DeterministicEventInterpretationAgent,
    DeterministicAIRiskAgent,
    DeterministicAIComplianceAgent,
    FinalDecisionComposerAgent | StubFinalDecisionComposerAgent,
]:
    """Provider 설정 유무에 따라 subprocess용 agent 4종을 생성한다.

    Provider 설정이 비어 있으면 bootstrap/orchestrator와 동일하게
    real agent + ``None`` provider 조합을 만들지 않고 즉시 stub으로 내린다.
    이렇게 해야 FDC가 ``NoneType.generate_structured``로 깨지지 않는다.

    AI Compliance는 2026-08-16부터, Event Interpretation은 2026-08-17
    부터, AI Risk는 2026-08-17(PR2)부터 provider 설정 유무와 무관하게
    항상 각각의 deterministic bot(LLM 호출 없음)을 반환한다 —
    in-process 경로(``runtime/bootstrap.py``)와 동일한 wiring이다.
    FDC는 이번 전환 대상이 아니므로 기존 provider/stub 판단을 그대로
    유지한다.
    """
    if provider_client is None:
        logger.info(
            "Provider client unavailable in agent subprocess — using stub agents"
        )
        _diag("Provider client unavailable — using stub agents")
        return (
            DeterministicEventInterpretationAgent(),
            DeterministicAIRiskAgent(),
            DeterministicAIComplianceAgent(),
            StubFinalDecisionComposerAgent(),
        )

    return (
        DeterministicEventInterpretationAgent(),
        DeterministicAIRiskAgent(),
        DeterministicAIComplianceAgent(),
        FinalDecisionComposerAgent(
            provider_client=provider_client,
            model_id=model_id,
            acquire_permit=acquire_permit,
        ),
    )


def _reconstruct_external_event(d: dict[str, Any] | None) -> ExternalEventEntity | None:
    """JSON-safe dict → ExternalEventEntity 변환 (datetime/UUID 복원)."""
    if d is None:
        return None
    if not isinstance(d, dict):
        return d  # 이미 엔티티 인스턴스인 경우
    return ExternalEventEntity(
        event_id=_safe_uuid(d.get("event_id")),
        event_type=d.get("event_type", ""),
        source_name=d.get("source_name", ""),
        published_at=_safe_datetime(d.get("published_at")),
        source_reliability_tier=d.get("source_reliability_tier", "T3"),
        source_event_id=d.get("source_event_id"),
        issuer_code=d.get("issuer_code"),
        symbol=d.get("symbol"),
        market=d.get("market"),
        ingested_at=_safe_datetime(d.get("ingested_at")),
        effective_at=_safe_datetime(d.get("effective_at")),
        severity=d.get("severity", "medium"),
        direction=d.get("direction", "neutral"),
        headline=d.get("headline"),
        body_summary=d.get("body_summary"),
        raw_payload_uri=d.get("raw_payload_uri"),
        dedup_key_hash=d.get("dedup_key_hash"),
        supersedes_event_id=_safe_uuid(d.get("supersedes_event_id")),
        metadata=d.get("metadata", {}),
        created_at=_safe_datetime(d.get("created_at")),
    )


def _reconstruct_decision_context(
    d: dict[str, Any] | None,
) -> DecisionContextEntity | None:
    """JSON-safe dict → DecisionContextEntity 변환 (datetime/UUID 복원)."""
    if d is None:
        return None
    if not isinstance(d, dict):
        return d  # 이미 엔티티 인스턴스인 경우
    return DecisionContextEntity(
        decision_context_id=_safe_uuid(d.get("decision_context_id")),
        account_id=_safe_uuid(d.get("account_id")),
        strategy_id=_safe_uuid(d.get("strategy_id")),
        config_version_id=_safe_uuid(d.get("config_version_id")),
        market_timestamp=_safe_datetime(d.get("market_timestamp")),
        correlation_id=d.get("correlation_id", ""),
        strategy_version_id=_safe_uuid(d.get("strategy_version_id")),
        trading_session_id=_safe_uuid(d.get("trading_session_id")),
        feature_snapshot_id=_safe_uuid(d.get("feature_snapshot_id")),
        signal_feature_snapshot_id=_safe_uuid(d.get("signal_feature_snapshot_id")),
        position_snapshot_id=_safe_uuid(d.get("position_snapshot_id")),
        cash_balance_snapshot_id=_safe_uuid(d.get("cash_balance_snapshot_id")),
        input_bundle_uri=d.get("input_bundle_uri"),
        created_at=_safe_datetime(d.get("created_at")),
    )


def _reconstruct_position_snapshot(
    d: dict[str, Any] | None,
) -> PositionSnapshotEntity | None:
    """JSON-safe dict → PositionSnapshotEntity 변환."""
    if d is None:
        return None
    if not isinstance(d, dict):
        return d  # 이미 엔티티 인스턴스인 경우
    return PositionSnapshotEntity(
        position_snapshot_id=_safe_uuid(d.get("position_snapshot_id")),
        account_id=_safe_uuid(d.get("account_id")),
        instrument_id=_safe_uuid(d.get("instrument_id")),
        quantity=_safe_decimal(d.get("quantity")),
        average_price=_safe_decimal(d.get("average_price")),
        market_price=_safe_decimal(d.get("market_price")),
        unrealized_pnl=_safe_decimal(d.get("unrealized_pnl")),
        source_of_truth=d.get("source_of_truth", ""),
        snapshot_at=_safe_datetime(d.get("snapshot_at")),
        purchase_amount=_safe_decimal(d.get("purchase_amount")),
        evaluation_amount=_safe_decimal(d.get("evaluation_amount")),
        created_at=_safe_datetime(d.get("created_at")),
    )


def _reconstruct_cash_balance_snapshot(
    d: dict[str, Any] | None,
) -> CashBalanceSnapshotEntity | None:
    """JSON-safe dict → CashBalanceSnapshotEntity 변환."""
    if d is None:
        return None
    if not isinstance(d, dict):
        return d  # 이미 엔티티 인스턴스인 경우
    return CashBalanceSnapshotEntity(
        cash_balance_snapshot_id=_safe_uuid(d.get("cash_balance_snapshot_id")),
        account_id=_safe_uuid(d.get("account_id")),
        currency=d.get("currency", ""),
        available_cash=_safe_decimal(d.get("available_cash")),
        settled_cash=_safe_decimal(d.get("settled_cash")),
        unsettled_cash=_safe_decimal(d.get("unsettled_cash")),
        source_of_truth=d.get("source_of_truth", ""),
        snapshot_at=_safe_datetime(d.get("snapshot_at")),
        total_asset=_safe_decimal(d.get("total_asset")),
        settlement_amount=_safe_decimal(d.get("settlement_amount")),
        total_unrealized_pnl=_safe_decimal(d.get("total_unrealized_pnl")),
        orderable_amount=_safe_decimal(d.get("orderable_amount")),
        created_at=_safe_datetime(d.get("created_at")),
    )


def _reconstruct_risk_limit_snapshot(
    d: dict[str, Any] | None,
) -> RiskLimitSnapshotEntity | None:
    """JSON-safe dict → RiskLimitSnapshotEntity 변환."""
    if d is None:
        return None
    if not isinstance(d, dict):
        return d  # 이미 엔티티 인스턴스인 경우
    return RiskLimitSnapshotEntity(
        risk_limit_snapshot_id=_safe_uuid(d.get("risk_limit_snapshot_id")),
        account_id=_safe_uuid(d.get("account_id")),
        snapshot_at=_safe_datetime(d.get("snapshot_at")),
        nav=_safe_decimal(d.get("nav")),
        cash_available=_safe_decimal(d.get("cash_available")),
        gross_exposure_pct=_safe_decimal(d.get("gross_exposure_pct")),
        net_exposure_pct=_safe_decimal(d.get("net_exposure_pct")),
        daily_realized_pnl=_safe_decimal(d.get("daily_realized_pnl")),
        daily_unrealized_pnl=_safe_decimal(d.get("daily_unrealized_pnl")),
        daily_loss_used_pct=_safe_decimal(d.get("daily_loss_used_pct")),
        max_daily_loss_limit_pct=_safe_decimal(d.get("max_daily_loss_limit_pct")),
        symbol_exposure_json=d.get("symbol_exposure_json", {}),
        sector_exposure_json=d.get("sector_exposure_json", {}),
        open_order_exposure_json=d.get("open_order_exposure_json", {}),
        drawdown_state=d.get("drawdown_state"),
        kill_switch_active=bool(d.get("kill_switch_active", False)),
        blocked_reason_codes=d.get("blocked_reason_codes"),
        created_at=_safe_datetime(d.get("created_at")),
    )


def _reconstruct_signal_feature_snapshot(
    d: dict[str, Any] | None,
) -> SignalFeatureSnapshotEntity | None:
    """JSON-safe dict → SignalFeatureSnapshotEntity 변환."""
    if d is None:
        return None
    if not isinstance(d, dict):
        return d
    return SignalFeatureSnapshotEntity(
        signal_feature_snapshot_id=_safe_uuid(d.get("signal_feature_snapshot_id")),
        instrument_id=_safe_uuid(d.get("instrument_id")),
        timeframe=d.get("timeframe", "1d"),
        snapshot_at=_safe_datetime(d.get("snapshot_at")),
        feature_set_version=d.get("feature_set_version", "signal_backbone_v1"),
        bar_count=int(d.get("bar_count", 0)),
        sma_5=_safe_decimal(d.get("sma_5")),
        sma_20=_safe_decimal(d.get("sma_20")),
        sma_60=_safe_decimal(d.get("sma_60")),
        price_vs_sma_20_pct=_safe_decimal(d.get("price_vs_sma_20_pct")),
        price_vs_sma_60_pct=_safe_decimal(d.get("price_vs_sma_60_pct")),
        return_1m_pct=_safe_decimal(d.get("return_1m_pct")),
        return_3m_pct=_safe_decimal(d.get("return_3m_pct")),
        volatility_20d_pct=_safe_decimal(d.get("volatility_20d_pct")),
        atr_14_pct=_safe_decimal(d.get("atr_14_pct")),
        rsi_14=_safe_decimal(d.get("rsi_14")),
        average_volume_20d=_safe_decimal(d.get("average_volume_20d")),
        volume_surge_ratio=_safe_decimal(d.get("volume_surge_ratio")),
        fast_score=_safe_decimal(d.get("fast_score")),
        slow_score=_safe_decimal(d.get("slow_score")),
        overall_score=_safe_decimal(d.get("overall_score")),
        component_scores_json=d.get("component_scores_json", {}),
        reason_codes=d.get("reason_codes"),
        created_at=_safe_datetime(d.get("created_at")),
    )


def _reconstruct_market_regime(
    d: dict[str, Any] | None,
) -> MarketRegimeAssessment | None:
    """JSON-safe dict → MarketRegimeAssessment 변환."""
    if d is None:
        return None
    if not isinstance(d, dict):
        return d
    strategy_weights_raw = d.get("strategy_weights", {})
    strategy_weights = (
        {
            str(key): float(value)
            for key, value in strategy_weights_raw.items()
        }
        if isinstance(strategy_weights_raw, dict)
        else {}
    )
    reason_codes_raw = d.get("reason_codes", ())
    reason_codes = tuple(reason_codes_raw) if isinstance(reason_codes_raw, (list, tuple)) else ()
    return MarketRegimeAssessment(
        regime_label=d.get("regime_label", "range_bound"),
        volatility_regime=d.get("volatility_regime", "normal_volatility"),
        risk_tone=d.get("risk_tone", "neutral"),
        confidence=float(d.get("confidence", 0.0)),
        half_life_hours=int(d.get("half_life_hours", 0)),
        strategy_weights=strategy_weights,
        reason_codes=reason_codes,
    )


def _reconstruct_strategy_selection(
    d: dict[str, Any] | None,
) -> StrategySelectionAssessment | None:
    """JSON-safe dict → StrategySelectionAssessment 변환."""
    if d is None:
        return None
    if not isinstance(d, dict):
        return d
    allowed_raw = d.get("allowed_strategies", ())
    allowed = tuple(allowed_raw) if isinstance(allowed_raw, (list, tuple)) else ()
    reasons_raw = d.get("reason_codes", ())
    reasons = tuple(reasons_raw) if isinstance(reasons_raw, (list, tuple)) else ()
    metadata_raw = d.get("metadata", {})
    metadata = dict(metadata_raw) if isinstance(metadata_raw, dict) else {}
    return StrategySelectionAssessment(
        preferred_strategy=d.get("preferred_strategy", "swing_momentum"),
        allowed_strategies=allowed,
        preferred_entry_style=d.get("preferred_entry_style", "LIMIT"),
        preferred_time_horizon=d.get("preferred_time_horizon", "swing"),
        confidence=float(d.get("confidence", 0.0)),
        reason_codes=reasons,
        metadata=metadata,
    )


def _reconstruct_portfolio_allocation(
    d: dict[str, Any] | None,
) -> PortfolioAllocationAssessment | None:
    """JSON-safe dict → PortfolioAllocationAssessment 변환."""
    if d is None:
        return None
    if not isinstance(d, dict):
        return d
    reasons_raw = d.get("reason_codes", ())
    reasons = tuple(reasons_raw) if isinstance(reasons_raw, (list, tuple)) else ()
    metadata_raw = d.get("metadata", {})
    metadata = dict(metadata_raw) if isinstance(metadata_raw, dict) else {}
    return PortfolioAllocationAssessment(
        target_weight_pct=float(d.get("target_weight_pct", 0.0)),
        current_weight_pct=(
            float(d.get("current_weight_pct"))
            if d.get("current_weight_pct") is not None
            else None
        ),
        max_single_position_pct=float(d.get("max_single_position_pct", 0.0)),
        remaining_concentration_pct=(
            float(d.get("remaining_concentration_pct"))
            if d.get("remaining_concentration_pct") is not None
            else None
        ),
        remaining_gross_budget_pct=(
            float(d.get("remaining_gross_budget_pct"))
            if d.get("remaining_gross_budget_pct") is not None
            else None
        ),
        max_new_capital_pct=float(d.get("max_new_capital_pct", 0.0)),
        orderable_cash=_safe_decimal(d.get("orderable_cash")),
        available_allocation_cash=_safe_decimal(d.get("available_allocation_cash")),
        recommended_max_order_value=_safe_decimal(d.get("recommended_max_order_value")),
        allocation_bias=d.get("allocation_bias", "neutral"),
        confidence=float(d.get("confidence", 0.0)),
        reason_codes=reasons,
        metadata=metadata,
    )


def _reconstruct_deterministic_trigger(
    d: dict[str, Any] | None,
) -> DeterministicTriggerAssessment | None:
    """JSON-safe dict → DeterministicTriggerAssessment 변환."""
    if d is None:
        return None
    if not isinstance(d, dict):
        return d
    candidate_set_raw = d.get("candidate_set", ())
    candidate_set = (
        tuple(candidate_set_raw)
        if isinstance(candidate_set_raw, (list, tuple))
        else ()
    )
    reasons_raw = d.get("reason_codes", ())
    reasons = tuple(reasons_raw) if isinstance(reasons_raw, (list, tuple)) else ()
    thresholds_raw = d.get("thresholds", {})
    thresholds = (
        {str(key): float(value) for key, value in thresholds_raw.items()}
        if isinstance(thresholds_raw, dict)
        else {}
    )
    metadata_raw = d.get("metadata", {})
    metadata = dict(metadata_raw) if isinstance(metadata_raw, dict) else {}
    return DeterministicTriggerAssessment(
        trigger_version=d.get("trigger_version", "deterministic_trigger_v1"),
        primary_candidate=d.get("primary_candidate", "NO_ACTION"),
        candidate_set=candidate_set,
        watch_candidate=bool(d.get("watch_candidate", False)),
        buy_candidate=bool(d.get("buy_candidate", False)),
        sell_candidate=bool(d.get("sell_candidate", False)),
        reduce_candidate=bool(d.get("reduce_candidate", False)),
        candidate_confidence=float(d.get("candidate_confidence", 0.0)),
        entry_score=(
            float(d.get("entry_score"))
            if d.get("entry_score") is not None
            else None
        ),
        exit_score=(
            float(d.get("exit_score"))
            if d.get("exit_score") is not None
            else None
        ),
        watch_score=(
            float(d.get("watch_score"))
            if d.get("watch_score") is not None
            else None
        ),
        reason_codes=reasons,
        thresholds=thresholds,
        metadata=metadata,
    )


def _reconstruct_context(raw: dict[str, Any]) -> AIPolicyContextView:
    """Reconstruct an ``AIPolicyContextView`` from a JSON-safe dict.

    Nested dataclass fields (``ScoreResult``, ``ExternalEventEntity``,
    ``DecisionContextEntity``) are reconstructed from their dict
    representations so that downstream agent code can access attributes
    via dot notation (e.g. ``score.score``, ``decision_context.account_id``).

    Snapshot fields (``position_snapshot``, ``cash_balance_snapshot``,
    ``risk_limit_snapshot``) are also reconstructed because JSON
    serialization converts UUID → str, Decimal → str, datetime → str.
    """
    # ── Reconstruct nested dataclass fields ──────────────────────────
    score: ScoreResult | None = None
    score_raw = raw.get("score")
    if isinstance(score_raw, dict):
        score = ScoreResult(
            score=score_raw.get("score", 0.0),
            threshold=score_raw.get("threshold", 0.0),
            reason_codes=tuple(score_raw.get("reason_codes", ())),
        )
    elif score_raw is None:
        score = ScoreResult()
    else:
        score = score_raw  # already a ScoreResult instance

    recent_events_raw = raw.get("recent_events", ())
    if isinstance(recent_events_raw, (list, tuple)):
        recent_events_list: list[ExternalEventEntity] = []
        for ev in recent_events_raw:
            reconstructed = _reconstruct_external_event(ev) if isinstance(ev, dict) else ev
            if reconstructed is not None:
                recent_events_list.append(reconstructed)
        recent_events = tuple(recent_events_list)
        _diag(
            f"_reconstruct_context: recent_events_raw count={len(recent_events_raw)} "
            f"→ reconstructed count={len(recent_events)}"
        )
    else:
        recent_events = recent_events_raw  # already a tuple of ExternalEventEntity
        _diag(
            f"_reconstruct_context: recent_events already ExternalEventEntity tuple, "
            f"count={len(recent_events)}"
        )

    # Reconstruct DecisionContextEntity (used by AIRiskAgent)
    decision_context_raw = raw.get("decision_context")
    decision_context = _reconstruct_decision_context(decision_context_raw)

    # ── Reconstruct snapshot fields (JSON-safe dict → dataclass) ─────
    position_snapshot = _reconstruct_position_snapshot(
        raw.get("position_snapshot")
    )
    cash_balance_snapshot = _reconstruct_cash_balance_snapshot(
        raw.get("cash_balance_snapshot")
    )
    risk_limit_snapshot = _reconstruct_risk_limit_snapshot(
        raw.get("risk_limit_snapshot")
    )
    signal_feature_snapshot = _reconstruct_signal_feature_snapshot(
        raw.get("signal_feature_snapshot")
    )
    market_regime = _reconstruct_market_regime(
        raw.get("market_regime")
    )
    strategy_selection = _reconstruct_strategy_selection(
        raw.get("strategy_selection")
    )
    portfolio_allocation = _reconstruct_portfolio_allocation(
        raw.get("portfolio_allocation")
    )
    deterministic_trigger = _reconstruct_deterministic_trigger(
        raw.get("deterministic_trigger")
    )

    # ── Build AI Policy context view with reconstructed fields ───────
    return AIPolicyContextView(
        decision_context=decision_context,
        recent_events=recent_events,
        score=score,
        position_snapshot=position_snapshot,
        cash_balance_snapshot=cash_balance_snapshot,
        risk_limit_snapshot=risk_limit_snapshot,
        signal_feature_snapshot=signal_feature_snapshot,
        market_regime=market_regime,
        strategy_selection=strategy_selection,
        portfolio_allocation=portfolio_allocation,
        deterministic_trigger=deterministic_trigger,
        source_type=raw.get("source_type", "core"),
    )


def _reconstruct_request(
    inp: AgentSubprocessInput,
    *,
    event_output: EventInterpretationOutput | None = None,
    risk_output: AIRiskOutput | None = None,
    compliance_output: AIComplianceOutput | None = None,
) -> AgentExecutionRequest:
    """Reconstruct an ``AgentExecutionRequest`` from subprocess input."""
    context = _reconstruct_context(inp.context)
    return AgentExecutionRequest(
        decision_context_id=UUID(inp.decision_context_id) if inp.decision_context_id else None,
        correlation_id=inp.correlation_id,
        context=context,
        symbol=inp.symbol,
        market=inp.market,
        event_interpretation_output=event_output,
        ai_risk_output=risk_output,
        ai_compliance_output=compliance_output,
        model_id=inp.model_id,
        prompt_id=inp.prompt_id,
        source_type=inp.source_type,
    )


# ---------------------------------------------------------------------------
# FDC Skip Logic — 비행동(non-actionable) 조건에서 FDC 호출 생략
# ---------------------------------------------------------------------------
# 관찰된 병목: FDC(FinalDecisionComposer)가 50-80s 소요.
# EI/AR 결과만으로 비행동이 명확하면 FDC를 생략하고 결정론적 HOLD/WATCH로 종료.


def _check_fdc_skip(
    inp: AgentSubprocessInput,
    request: AgentExecutionRequest,
    event_output: EventInterpretationOutput,
    risk_output: AIRiskOutput,
) -> tuple[bool, str, FinalDecisionComposerOutput]:
    """EI/AR 결과를 기반으로 FDC 생략 조건을 판정한다.

    Parameters
    ----------
    inp
        원본 subprocess 입력 (symbol, market 등).
    request
        재구성된 AgentExecutionRequest (context 포함).
    event_output
        EventInterpretationAgent 실행 결과.
    risk_output
        AIRiskAgent 실행 결과.

    Returns
    -------
    (skip, reason, deterministic_output)
        skip=True이면 FDC 호출 없이 deterministic_output 사용.
        skip=False이면 정상 FDC 호출.
    """
    context = request.context

    # --- 보유 포지션 유무 ---
    has_position = (
        context.position_snapshot is not None
        and context.position_snapshot.quantity is not None
        and context.position_snapshot.quantity > 0
    )

    symbol = inp.symbol or event_output.symbol or "(unknown)"

    # Condition 1: Risk "reject" → 결정론적 HOLD
    if risk_output.risk_opinion == "reject":
        return (True, "risk_reject", FinalDecisionComposerOutput(
            symbol=symbol,
            decision_type="HOLD",
            confidence=0.0,
            summary=f"{symbol} — 리스크 평가 'reject'. FDC 생략.",
            reason_codes=("risk_rejected",),
        ))

    # Condition 2: held_position + NO_ACTION → 결정론적 기본 HOLD
    #
    # 2026-08-21: held_position의 NO_ACTION은 shadow 관측에서 FDC 원본과
    # 최종 실행 의미가 일치했다. EI/AR는 이미 실행된 뒤이므로, 이 조건은
    # FDC만 생략한다. 특히 이후 orchestrator의 held_position sell override
    # 는 이 HOLD를 REDUCE/EXIT로 바꿀 수 있으므로 summary에서 최종 HOLD를
    # 확정했다고 표현하지 않는다.
    deterministic_trigger = context.deterministic_trigger
    primary_candidate = (
        getattr(deterministic_trigger, "primary_candidate", "") or ""
    ).strip().upper()
    if (
        (context.source_type or "core").strip().lower() == "held_position"
        and has_position
        and primary_candidate == "NO_ACTION"
    ):
        return (True, "held_position_no_action", FinalDecisionComposerOutput(
            symbol=symbol,
            decision_type="HOLD",
            confidence=0.0,
            summary=(
                f"[규칙 기반 FDC 생략] {symbol} — 보유 포지션의 결정론적 "
                "후보가 NO_ACTION으로 확인되어 FDC 호출 없이 기본 HOLD를 "
                "전달했습니다. 이후 held_position 리스크 override와 기존 "
                "주문 gate는 동일하게 적용됩니다."
            ),
            reason_codes=("held_position_no_action", "fdc_skipped"),
        ))

    # Condition 3: 최근 이벤트 0건 + 미보유 → 결정론적 HOLD
    # 주의:
    # - recent_events가 실제로 존재하는데 EI가 no_material_events=True로 판단한 경우는
    #   deterministic skip으로 잘라내지 않는다.
    # - 이런 케이스는 FDC까지 전달해 최종 HOLD/WATCH/BUY를 AI가 조합하도록 둔다.
    # - "이벤트는 있었지만 중요하지 않다"는 것도 최종 판단의 일부이며,
    #   앞단 short-circuit 사유로 덮어쓰면 운영 화면에서 AI 판단 내용이 사라진다.
    if not context.recent_events and not has_position:
        return (True, "no_events_no_position", FinalDecisionComposerOutput(
            symbol=symbol,
            decision_type="HOLD",
            confidence=0.0,
            summary=(
                f"[결정론적 판단 근거] {symbol} — 최근 72시간 내 특별한 이벤트가 "
                f"없고 보유 중인 포지션도 없어, 신규 진입 신호가 없다고 판단해 "
                f"FDC 호출을 생략하고 HOLD로 확정했습니다."
            ),
            reason_codes=("no_events", "no_position"),
        ))

    # Condition 4: 주문 가능 잔고 부족 + 미보유 → 결정론적 WATCH
    cash = context.cash_balance_snapshot
    if (
        cash is not None
        and cash.orderable_amount is not None
        and cash.orderable_amount <= 0
        and not has_position
    ):
        return (True, "cash_shortage", FinalDecisionComposerOutput(
            symbol=symbol,
            decision_type="WATCH",
            confidence=0.5,
            summary=f"{symbol} — 주문 가능 잔고 부족 (orderable_amount={cash.orderable_amount}). 진입 불가 — WATCH.",
            reason_codes=("insufficient_cash",),
        ))

    # Condition 5: 미보유 신규 진입 + deterministic eligibility 탈락
    # → downstream `_check_ai_buy_override_gate()`(decision_orchestrator.py)가
    #   FDC의 실제 decision_type과 무관하게 반드시 WATCH/HOLD로 강등하는 구간을
    #   미리 결정론적으로 확정한다.
    #
    # 동치성 근거(2026-08-19, 코드 직접 대조로 검증):
    #   `_check_ai_buy_override_gate()`는 has_position=False +
    #   deterministic_trigger.buy_candidate=False일 때만 개입하며, 그중
    #   eligibility_passed=False인 경우 — 단, decision_context.
    #   signal_feature_snapshot_id가 None이고 eligibility_reasons가 오직
    #   {"eligibility_source_type_allowed", "eligibility_low_feature_coverage"}
    #   의 부분집합인 좁은 예외 케이스는 제외 — 는 FDC의 confidence/conviction과
    #   무관하게 항상 downgrade_decision(watch_candidate 여부로 WATCH/HOLD)으로
    #   강제 전환된다. 이 분기는 FDC 출력에 의존하지 않으므로 upstream에서
    #   안전하게 재현 가능하다.
    #
    #   반대로 eligibility_passed=True 상태에서의 강등(EV gate 미통과,
    #   symbol_state 기반 hysteresis)은 FDC 자신의 confidence/conviction 출력이나
    #   DB(symbol_trade_states, 24시간 이벤트) 조회에 의존하고, hysteresis가
    #   "차단 안 함"으로 판정되면 FDC의 원래 결정이 그대로 유지되는 경로도 있어
    #   — 이 두 분기는 절대 upstream에서 미리 확정할 수 없다(동치성 없음).
    #   `_AI_OVERRIDE_EXECUTION_INFEASIBLE_REASONS` 분기 역시 eligibility_passed=
    #   True인 상태에서만 도달 가능해 이 조건의 범위 밖이다.
    #   그래서 이 스킵 조건은 eligibility_passed=False 분기 하나로만 좁게
    #   한정한다 — 의도적으로 좁은 범위이며, 넓히지 않는다.
    if (
        not has_position
        and deterministic_trigger is not None
        and not bool(getattr(deterministic_trigger, "buy_candidate", False))
        and not bool(getattr(deterministic_trigger, "eligibility_passed", False))
    ):
        eligibility_reasons = tuple(
            getattr(deterministic_trigger, "eligibility_reasons", ()) or ()
        )
        decision_context = context.decision_context
        is_low_feature_coverage_exception = (
            decision_context is not None
            and getattr(decision_context, "signal_feature_snapshot_id", None) is None
            and bool(eligibility_reasons)
            and set(eligibility_reasons).issubset(
                {
                    "eligibility_source_type_allowed",
                    "eligibility_low_feature_coverage",
                }
            )
        )
        if not is_low_feature_coverage_exception:
            watch_candidate = bool(
                getattr(deterministic_trigger, "watch_candidate", False)
            )
            forced_decision_type = "WATCH" if watch_candidate else "HOLD"
            summary = (
                f"[규칙 기반 생략] {symbol} — 신규 진입 자격을 충족하지 못한 "
                f"종목으로, AI가 실제로 매수 판단을 내려도 규칙에 의해 최종 "
                f"결과가 {forced_decision_type}로 강제 확정되므로 FDC 호출 "
                f"자체를 생략했습니다."
            )
            return (True, "buy_candidate_eligibility_blocked", FinalDecisionComposerOutput(
                symbol=symbol,
                decision_type=forced_decision_type,
                confidence=0.0,
                summary=summary,
                reason_codes=(
                    "buy_candidate_eligibility_blocked",
                    "ai_override_eligibility_blocked",
                    "forced_watch_candidate" if watch_candidate else "forced_hold",
                ),
            ))

    # --- 생략 불가 → 정상 FDC 호출 ---
    return (False, "", FinalDecisionComposerOutput())


def _build_ei_timeout_fallback(
    request: AgentExecutionRequest,
    *,
    symbol: str,
    input_event_count: int,
) -> EventInterpretationOutput:
    """EI timeout 시 안전한 fallback output을 생성한다."""
    from agent_trading.services.ai_agents.event_interpretation import (
        _finalize_ei_output,
    )

    if input_event_count > 0:
        fallback = EventInterpretationOutput(
            symbol=symbol,
            aggregate_view=AggregateEventView(
                overall_bias="neutral",
                event_conflict=False,
                top_reason_codes=(),
                opposing_evidence=(),
                evidence_strength="weak",
                no_material_events=False,
                interpretation_incomplete=True,
                degraded_reason="timeout",
            ),
            detected_event_count=input_event_count,
        )
        return _finalize_ei_output(fallback, input_event_count=input_event_count)

    fallback = EventInterpretationOutput(
        symbol=symbol,
        aggregate_view=AggregateEventView(
            interpretation_incomplete=True,
            degraded_reason="timeout",
        ),
    )
    return _finalize_ei_output(
        fallback,
        recent_events=request.context.recent_events or (),
    )


def _build_ar_timeout_fallback(
    request: AgentExecutionRequest,
    *,
    symbol: str,
) -> AIRiskOutput:
    """AR timeout 시 안전한 fallback output을 생성한다."""
    return AIRiskOutput(
        decision_context_id=(
            str(request.decision_context_id)
            if request.decision_context_id
            else None
        ),
        symbol=symbol,
    )


def _build_fdc_timeout_fallback(
    request: AgentExecutionRequest,
    *,
    symbol: str,
) -> FinalDecisionComposerOutput:
    """FDC timeout 시 안전한 fallback output을 생성한다.

    2026-08-21 결함 수정: 이전에는 ``reason_codes``/``summary``가 모두
    비어 있어, DB(``decision_json``/``agent_runs``)만 보면 정상 HOLD와
    timeout fallback을 구분할 수 없었다. ``provider_timeout``을
    reason code로 남겨 이 구분을 가능하게 한다(``decision_type="HOLD"``
    fallback 정책 자체는 그대로 유지).
    """
    return FinalDecisionComposerOutput(
        decision_context_id=(
            str(request.decision_context_id)
            if request.decision_context_id
            else None
        ),
        symbol=symbol,
        reason_codes=("provider_timeout",),
        summary=(
            f"[규칙 기반 fallback] {symbol} — FDC per-agent timeout"
            f"({_FDC_PER_AGENT_TIMEOUT}초) 초과로 HOLD 반환."
        ),
    )


async def _run_fdc_with_outer_timeout(
    fdc_agent: FinalDecisionComposerAgent | StubFinalDecisionComposerAgent,
    request: AgentExecutionRequest,
    *,
    timeout_seconds: float,
    symbol: str,
) -> tuple[FinalDecisionComposerOutput, dict[str, object]]:
    """FDC를 outer timeout(``_FDC_PER_AGENT_TIMEOUT``)으로 감싸 실행한다.

    2026-08-21 결함 수정(PR #311 코드 검토): outer
    ``asyncio.wait_for(fdc_agent.run(...), timeout=...)``가 실제로
    timeout됐을 때, ``fdc_agent.last_provider_observation``은 거의
    항상 ``None``으로 남는다 — ``asyncio.wait_for()``의 취소는
    ``asyncio.CancelledError``(``BaseException`` 서브클래스)를 발생시켜
    ``final_decision_composer.py::run()``의 ``except Exception as exc:``
    블록을 통과하지 않으므로, 그 블록 안에서만 채워지는
    ``self.last_provider_observation``이 이 경로에서는 설정될 기회가
    없기 때문이다. 이 함수는 그 사실을 명시적으로 반영해, outer
    timeout 시에는 ``last_provider_observation``에 의존하지 않고
    ``provider_final_status``/``provider_execution_seconds``를 직접
    계산한다(``http_attempt_count``/``http_429_count``는 취소 전 실제로
    관측된 값이 없으므로 추정하지 않고 0으로 남긴다 — ``observation``이
    드문 경합으로 이미 채워져 있는 경우에만 그 실제 값을 그대로 쓴다).

    반환값은 ``(composer_output, observation_fields)`` — 두 번째 값은
    ``AgentSubprocessOutput``에 그대로 대입 가능한
    ``provider_http_attempt_count``/``provider_http_429_count``/
    ``provider_execution_seconds``/``provider_final_status`` 4개 키를
    담은 dict다. ``rate_limiter_*`` 필드는 이 함수의 책임이 아니다
    (``_FdcPermitAccumulator``가 별도로 담당).
    """
    started_at = time.monotonic()
    try:
        composer_output = await asyncio.wait_for(
            fdc_agent.run(request), timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        composer_output = _build_fdc_timeout_fallback(request, symbol=symbol)
        # outer timeout 자체가 확정적 사실이므로 provider_final_status/
        # provider_execution_seconds는 여기서 직접 계산한다 — 아래
        # 성공 경로처럼 last_provider_observation의 값으로 덮어쓰지 않는다.
        observation = getattr(fdc_agent, "last_provider_observation", None)
        return composer_output, {
            "provider_http_attempt_count": (
                observation.http_attempt_count if observation is not None else 0
            ),
            "provider_http_429_count": (
                observation.http_429_count if observation is not None else 0
            ),
            "provider_execution_seconds": time.monotonic() - started_at,
            "provider_final_status": "provider_timeout",
        }

    observation = getattr(fdc_agent, "last_provider_observation", None)
    if observation is not None:
        return composer_output, {
            "provider_http_attempt_count": observation.http_attempt_count,
            "provider_http_429_count": observation.http_429_count,
            "provider_execution_seconds": observation.execution_seconds,
            "provider_final_status": observation.provider_final_status,
        }
    return composer_output, {
        "provider_http_attempt_count": 0,
        "provider_http_429_count": 0,
        "provider_execution_seconds": 0.0,
        "provider_final_status": "",
    }


# ---------------------------------------------------------------------------
# mode="fdc_only" — 이미 확보한 reservation grant로 FDC one-shot만 실행
# (2026-08-27 신설, held_position 실제 dispatcher — PR #359 리뷰 보정)
# ---------------------------------------------------------------------------


async def _run_fdc_only_mode(inp: AgentSubprocessInput, t0: float) -> None:
    """EI/AR/AC를 전혀 호출하지 않고, 이미 확보한 reservation grant로
    FDC one-shot만 실행한다. 결과를 stdout에 쓰고, 실패하면
    ``sys.exit(1)``(기존 ``main()``과 동일한 오류 처리 계약).

    DB pool은 이 함수가 독자적으로 열고 닫는다(PR A의
    ``ar_fdc_provider_validation.py``와 동일 패턴) — reservation 자체는
    호출자(``DecisionAgentRunner``)가 이미 얻었으므로 여기서는
    ``try_reserve()``를 호출하지 않지만, ``record_attempt_outcome()``
    (HTTP 시작/완료 기록)에는 여전히 DB 접근이 필요하다.
    """
    pool_opened = False
    try:
        if not (
            inp.reservation_id and inp.reservation_job_id
            and inp.reservation_quota_scope
        ):
            raise ValueError(
                "mode='fdc_only'는 reservation_id/reservation_job_id/"
                "reservation_quota_scope가 모두 필요하다"
            )
        if not (inp.provider_api_key and inp.provider_base_url):
            raise ValueError("mode='fdc_only'는 provider 설정이 필요하다")

        from agent_trading.config.settings import (
            _resolve_fdc_provider_global_gate_enabled,
            _resolve_fdc_provider_rate_window_seconds,
            _resolve_fdc_provider_target_rpm,
            _resolve_gemini_provider_declared_rpm_limit,
        )
        from agent_trading.db.connection import close_pool, create_pool
        from agent_trading.db.transaction import TransactionManager
        from agent_trading.repositories.contracts import ReservationGrant
        from agent_trading.repositories.postgres.fdc_quota import (
            PostgresFdcQuotaRepository,
        )
        from agent_trading.services.ai_agents.provider_client import (
            LiveGeminiProviderClient,
        )
        from agent_trading.services.fdc_quota_coordinator import FdcQuotaCoordinator
        from scripts.fdc_manual_provider_gate import PreGrantedFdcProviderClient

        await create_pool()
        pool_opened = True

        async with TransactionManager() as ambient_tx:
            repo = PostgresFdcQuotaRepository(ambient_tx)
        coordinator = FdcQuotaCoordinator(
            repo=repo,
            target_rpm=_resolve_fdc_provider_target_rpm(),
            window_seconds=_resolve_fdc_provider_rate_window_seconds(),
            declared_rpm_limit=_resolve_gemini_provider_declared_rpm_limit(),
        )
        # PR D(2026-09-03) — flag가 꺼져 있으면 global_gate=None이라
        # execute_fdc_one_shot_attempt()가 gate 호출 자체를 하지 않는다
        # (완전 no-op, 기존 동작 그대로).
        global_gate = (
            FdcProviderGlobalGate(
                repo=repo,
                target_rpm=_resolve_fdc_provider_target_rpm(),
                window_seconds=_resolve_fdc_provider_rate_window_seconds(),
            )
            if _resolve_fdc_provider_global_gate_enabled()
            else None
        )
        live_client = LiveGeminiProviderClient(
            coordinator=coordinator,
            api_key=inp.provider_api_key,
            base_url=inp.provider_base_url,
            timeout_seconds=inp.provider_timeout_seconds,
        )
        grant = ReservationGrant(
            reservation_id=UUID(inp.reservation_id),
            quota_scope=inp.reservation_quota_scope,
            job_id=UUID(inp.reservation_job_id),
            attempt_no=inp.reservation_attempt_no,
            window_count_before_grant=inp.reservation_window_count_before_grant,
        )
        pre_granted_client = PreGrantedFdcProviderClient(
            coordinator=coordinator, live_client=live_client,
            grant=grant, job_id=grant.job_id, global_gate=global_gate,
        )
        fdc_agent = FinalDecisionComposerAgent(
            provider_client=pre_granted_client,
            model_id=inp.provider_model_id,
        )

        event_output = dict_to_dataclass(
            inp.event_interpretation_output or {}, EventInterpretationOutput,
        )
        risk_output = dict_to_dataclass(inp.ai_risk_output or {}, AIRiskOutput)
        compliance_output = dict_to_dataclass(
            inp.ai_compliance_output or {}, AIComplianceOutput,
        )
        request = _reconstruct_request(
            inp, event_output=event_output, risk_output=risk_output,
            compliance_output=compliance_output,
        )

        composer_output, observation_fields = await _run_fdc_with_outer_timeout(
            fdc_agent, request, timeout_seconds=_FDC_PER_AGENT_TIMEOUT,
            symbol=inp.symbol or "",
        )

        if is_missing_agent_symbol(composer_output.symbol) and inp.symbol:
            from dataclasses import replace
            composer_output = replace(composer_output, symbol=inp.symbol)
        normalized_dt = normalize_decision_type(composer_output.decision_type)
        if normalized_dt != composer_output.decision_type:
            from dataclasses import replace
            composer_output = replace(composer_output, decision_type=normalized_dt)

        duration = time.monotonic() - t0
        output = AgentSubprocessOutput(
            success=True,
            composer_output=dataclass_to_dict(composer_output),
            duration_seconds=duration,
            fdc_skipped=False,
            provider_http_attempt_count=observation_fields["provider_http_attempt_count"],
            provider_http_429_count=observation_fields["provider_http_429_count"],
            provider_execution_seconds=observation_fields["provider_execution_seconds"],
            provider_final_status=observation_fields["provider_final_status"],
        )
        _write_output(output)
        _diag(f"SUCCESS: fdc_only completed in {duration:.2f}s")
    except Exception as exc:
        duration = time.monotonic() - t0
        _diag(f"EXCEPTION (fdc_only) after {duration:.2f}s: {exc}")
        logger.exception("fdc_only subprocess failed after %.2fs", duration)
        _write_error_output(str(exc), duration=duration)
        sys.exit(1)
    finally:
        if pool_opened:
            await close_pool()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    """Entry point: read stdin, run agents, write stdout."""
    t0 = time.monotonic()
    _diag("main() started")

    # ── 1. Read & parse input ──────────────────────────────────────────
    try:
        raw = sys.stdin.buffer.read()
        data: dict[str, Any] = json.loads(raw)
        inp = AgentSubprocessInput(**data)
        _diag(f"Input parsed: symbol={inp.symbol} market={inp.market} correlation_id={inp.correlation_id}")
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        _diag(f"Failed to parse input: {exc}")
        _write_error_output(f"Failed to parse input: {exc}")
        sys.exit(1)

    if inp.mode == "fdc_only":
        # EI/AR/AC를 전혀 호출하지 않는다 — 별도 함수로 완전히 분리해
        # 처리한다(2026-08-27 신설, held_position 실제 dispatcher).
        await _run_fdc_only_mode(inp, t0)
        return

    # ── 1b. Create provider client (if configured) ─────────────────────
    provider_client: AIProviderClient | None = None
    if inp.provider_api_key and inp.provider_base_url:
        from agent_trading.services.ai_agents import OpenAICompatibleClient
        logger.info(
            "Creating OpenAICompatibleClient: base_url=%s model_id=%s timeout=%s",
            inp.provider_base_url,
            inp.provider_model_id or _resolve_provider_model_id(),
            inp.provider_timeout_seconds,
        )
        _diag("Creating OpenAICompatibleClient ...")
        provider_client = OpenAICompatibleClient(
            api_key=inp.provider_api_key,
            base_url=inp.provider_base_url,
            model_id=inp.provider_model_id or _resolve_provider_model_id(),
            timeout_seconds=inp.provider_timeout_seconds,
        )
        _diag("OpenAICompatibleClient created")
    else:
        logger.info(
            "No provider client created: api_key=%s base_url=%s",
            "set" if inp.provider_api_key else "not set",
            "set" if inp.provider_base_url else "not set",
        )
        _diag("No provider client created")
    # PR D(2026-09-03) — flag가 켜져 있고 legacy FDC 호출이 실제로
    # 있을 때만(provider_client가 있을 때만) DB pool을 연다. flag가
    # 꺼져 있으면(기본값) 이 블록 전체가 아무 것도 하지 않는다 — legacy
    # 경로는 지금처럼 DB에 전혀 접속하지 않는다.
    global_gate_pool_opened = False
    fdc_global_gate: FdcProviderGlobalGate | None = None
    if provider_client is not None:
        from agent_trading.config.settings import (
            _resolve_fdc_provider_global_gate_enabled,
            _resolve_fdc_provider_rate_window_seconds,
            _resolve_fdc_provider_target_rpm,
        )
        if _resolve_fdc_provider_global_gate_enabled():
            from agent_trading.db.connection import create_pool
            from agent_trading.db.transaction import TransactionManager
            from agent_trading.repositories.postgres.fdc_quota import (
                PostgresFdcQuotaRepository,
            )
            await create_pool()
            global_gate_pool_opened = True
            async with TransactionManager() as _gate_ambient_tx:
                _gate_repo = PostgresFdcQuotaRepository(_gate_ambient_tx)
            fdc_global_gate = FdcProviderGlobalGate(
                repo=_gate_repo,
                target_rpm=_resolve_fdc_provider_target_rpm(),
                window_seconds=_resolve_fdc_provider_rate_window_seconds(),
            )
    # 2026-08-21: FDC 1회 호출(최초 요청 + 재시도 전부) 동안의 permit
    # 판정을 누적할 accumulator. provider 미설정(Stub 경로)이면 애초에
    # HTTP 호출이 없으므로 만들지 않는다 — Stub은 permit 대기 없이
    # 기존 동작을 그대로 유지한다.
    fdc_permit_accumulator = (
        _FdcPermitAccumulator(
            lane=inp.source_type or "unknown", global_gate=fdc_global_gate,
        )
        if provider_client is not None else None
    )
    ei_agent, ar_agent, ac_agent, fdc_agent = _build_agent_triplet(
        provider_client=provider_client,
        model_id=inp.provider_model_id,
        acquire_permit=(
            fdc_permit_accumulator.acquire
            if fdc_permit_accumulator is not None
            else None
        ),
    )

    # ── 2. Run agents sequentially ─────────────────────────────────────
    try:
        # --- 2a. Event Interpretation Agent ---
        logger.info("Starting EventInterpretationAgent.run() ...")
        _diag("Starting EventInterpretationAgent.run() ...")
        request = _reconstruct_request(inp)
        input_event_count = len(request.context.recent_events)
        _diag(f"Context reconstructed: events={input_event_count}")
        try:
            event_output = await asyncio.wait_for(
                ei_agent.run(request),
                timeout=_PER_AGENT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "EventInterpretationAgent timed out after %ss — using fallback output. symbol=%s decision_context_id=%s",
                _PER_AGENT_TIMEOUT,
                inp.symbol,
                inp.decision_context_id,
            )
            event_output = _build_ei_timeout_fallback(
                request,
                symbol=inp.symbol or "",
                input_event_count=input_event_count,
            )
        _diag(
            f"EventInterpretationAgent completed: symbol={event_output.symbol} "
            f"input_events={input_event_count} "
            f"output_events={len(event_output.events)} "
            f"detected_event_count={event_output.detected_event_count} "
            f"no_material_events={event_output.aggregate_view.no_material_events}"
        )
        logger.info(
            "EventInterpretationAgent completed: symbol=%s "
            "input_events=%d output_events=%d detected_event_count=%s no_material_events=%s",
            event_output.symbol,
            input_event_count,
            len(event_output.events),
            event_output.detected_event_count,
            event_output.aggregate_view.no_material_events,
        )

        if is_missing_agent_symbol(event_output.symbol) and inp.symbol:
            from dataclasses import replace
            event_output = replace(event_output, symbol=inp.symbol)

        # --- 2b. AI Risk Agent ---
        logger.info("Starting AIRiskAgent.run() ...")
        _diag("Starting AIRiskAgent.run() ...")
        request_with_ei = _reconstruct_request(inp, event_output=event_output)
        try:
            risk_output = await asyncio.wait_for(
                ar_agent.run(request_with_ei),
                timeout=_PER_AGENT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "AIRiskAgent timed out after %ss — using fallback output. symbol=%s decision_context_id=%s",
                _PER_AGENT_TIMEOUT,
                inp.symbol,
                inp.decision_context_id,
            )
            risk_output = _build_ar_timeout_fallback(
                request_with_ei,
                symbol=inp.symbol or event_output.symbol or "",
            )
        _diag(f"AIRiskAgent completed: symbol={risk_output.symbol} risk_opinion={risk_output.risk_opinion}")
        logger.info(
            "AIRiskAgent completed: summary_len=%s symbol=%s risk_opinion=%s",
            len(risk_output.summary) if risk_output.summary else 0,
            risk_output.symbol,
            risk_output.risk_opinion,
        )

        if is_missing_agent_symbol(risk_output.symbol) and inp.symbol:
            from dataclasses import replace
            risk_output = replace(risk_output, symbol=inp.symbol)

        # --- 2c. AI Compliance Agent ---
        logger.info("Starting AIComplianceAgent.run() ...")
        _diag("Starting AIComplianceAgent.run() ...")
        request_with_ei_ar = _reconstruct_request(
            inp, event_output=event_output, risk_output=risk_output,
        )
        try:
            compliance_output = await asyncio.wait_for(
                ac_agent.run(request_with_ei_ar),
                timeout=_PER_AGENT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "AIComplianceAgent timed out after %ss — using fallback output. symbol=%s decision_context_id=%s",
                _PER_AGENT_TIMEOUT,
                inp.symbol,
                inp.decision_context_id,
            )
            compliance_output = AIComplianceOutput(
                decision_context_id=inp.decision_context_id,
                symbol=inp.symbol or event_output.symbol or "",
            )
        _diag(
            f"AIComplianceAgent completed: symbol={compliance_output.symbol} "
            f"compliance_opinion={compliance_output.compliance_opinion}"
        )
        logger.info(
            "AIComplianceAgent completed: summary_len=%s symbol=%s compliance_opinion=%s",
            len(compliance_output.summary) if compliance_output.summary else 0,
            compliance_output.symbol,
            compliance_output.compliance_opinion,
        )

        if is_missing_agent_symbol(compliance_output.symbol) and inp.symbol:
            from dataclasses import replace
            compliance_output = replace(compliance_output, symbol=inp.symbol)

        # --- 2d. FDC Skip Check (결정론적 비행동 조건이면 FDC 생략) ---
        skip_fdc, skip_reason, skip_output = _check_fdc_skip(
            inp=inp,
            request=request_with_ei,
            event_output=event_output,
            risk_output=risk_output,
        )

        # FDC cycle-scoped batch queue lifecycle shadow(Phase 1) 전용 —
        # "FDC 호출이 필요하다"는 결정론적 판정이 끝난 직후, 실제 permit
        # 대기/HTTP 호출(아래 FDC 실행 블록)이 시작되기 **직전**에 캡처한
        # 타임스탬프. 이 값이 shadow 가상 FIFO 큐의 "언제 이 job이
        # FDC-ready였는지"를 결정한다 — 이 시점 이후 실제로 걸리는
        # permit 대기/HTTP 시간은 이 값에 전혀 반영되지 않는다(의도적:
        # shadow는 "가상 13 RPM 큐라면 이 시점에 승인 가능했을까"를
        # 관측하는 것이지, 기존 10 RPM limiter의 실제 대기 시간을
        # 관측하는 것이 아니다).
        fdc_ready_at = "" if skip_fdc else datetime.now(timezone.utc).isoformat()

        # 2026-08-21: FDC가 생략되면 provider 호출/permit 대기가 전혀
        # 없으므로 관측성 필드는 모두 기본값(호출 없음)으로 남는다.
        fdc_provider_http_attempt_count = 0
        fdc_provider_http_429_count = 0
        fdc_provider_execution_seconds = 0.0
        fdc_provider_final_status = ""
        fdc_rate_limiter_waited_seconds = 0.0
        fdc_rate_limiter_slot_acquired = True
        fdc_rate_limiter_queue_timeout = False
        fdc_rate_limiter_state_file_error = False
        fdc_rate_limiter_queue_ticket = ""
        fdc_rate_limiter_queue_position_at_first_wait = -1
        fdc_rate_limiter_requeue_count = 0
        fdc_rate_limiter_final_waited_seconds = 0.0
        fdc_rate_limiter_queue_deadline_exceeded = False

        if skip_fdc:
            composer_output = skip_output
            # ★ FDC skip 시 degraded 플래그 설정 (full pipeline 미완료)
            from dataclasses import replace
            degraded_av = replace(
                event_output.aggregate_view,
                interpretation_incomplete=True,
                degraded_reason=f"fdc_skipped:{skip_reason}",
            )
            object.__setattr__(event_output, "aggregate_view", degraded_av)
            # ★ 신규: FDC skip은 EI 분석 결과와 무관하므로 summary_basis="none"
            object.__setattr__(event_output, "summary_basis", "none")
            # ★ 신규: interpreted_event_count 동기화
            object.__setattr__(
                event_output,
                "interpreted_event_count",
                len(event_output.events),
            )
            _diag(f"FDC skipped: reason={skip_reason} symbol={composer_output.symbol}")
            logger.info(
                "FDC skipped: reason=%s symbol=%s decision_type=%s",
                skip_reason,
                composer_output.symbol,
                composer_output.decision_type,
            )
        elif inp.mode == "pre_fdc":
            # FDC-ready지만 mode="pre_fdc"라 FDC를 호출하지 않는다
            # (2026-08-27, held_position 실제 dispatcher 신설 — PR #359
            # 리뷰 보정). 호출자(``DecisionAgentRunner``)가 quota
            # reservation을 기다린 뒤 별도 "fdc_only" subprocess를
            # 스폰한다. composer_output은 빈 상태로 남기고, 아래
            # ``requires_fdc_dispatch=True`` 플래그로 호출자에게 알린다.
            composer_output = FinalDecisionComposerOutput(
                symbol=inp.symbol or event_output.symbol or "",
            )
            _diag(
                f"FDC dispatch required (mode=pre_fdc): symbol={composer_output.symbol}"
            )
            logger.info(
                "FDC dispatch required (mode=pre_fdc): symbol=%s",
                composer_output.symbol,
            )
        else:
            # --- 2d. Final Decision Composer Agent ---
            # 2026-08-21 전환: rate limiter permit 획득은 더 이상 여기서
            # 외부적으로 1회만 일어나지 않는다 — ``fdc_agent``에 주입된
            # ``acquire_permit``(위 ``fdc_permit_accumulator.acquire``)이
            # ``provider_client.py``의 재시도 루프 안에서 최초 요청 +
            # 매 재시도마다 각각 호출된다. StubFinalDecisionComposerAgent
            # (provider 미설정)는 애초에 permit 콜백을 받지 않으므로 대기가
            # 전혀 없다.
            logger.info("Starting FinalDecisionComposerAgent.run() ...")
            _diag("Starting FinalDecisionComposerAgent.run() ...")
            request_with_ei_ar_ac = _reconstruct_request(
                inp,
                event_output=event_output,
                risk_output=risk_output,
                compliance_output=compliance_output,
            )
            composer_output, _fdc_provider_observation_fields = await _run_fdc_with_outer_timeout(
                fdc_agent,
                request_with_ei_ar_ac,
                timeout_seconds=_FDC_PER_AGENT_TIMEOUT,
                symbol=inp.symbol or event_output.symbol or "",
            )
            fdc_provider_http_attempt_count = _fdc_provider_observation_fields[
                "provider_http_attempt_count"
            ]
            fdc_provider_http_429_count = _fdc_provider_observation_fields[
                "provider_http_429_count"
            ]
            fdc_provider_execution_seconds = _fdc_provider_observation_fields[
                "provider_execution_seconds"
            ]
            fdc_provider_final_status = _fdc_provider_observation_fields[
                "provider_final_status"
            ]
            if fdc_provider_final_status == "provider_timeout":
                logger.warning(
                    "FinalDecisionComposerAgent timed out after %ss — using fallback output. symbol=%s decision_context_id=%s",
                    _FDC_PER_AGENT_TIMEOUT,
                    inp.symbol,
                    inp.decision_context_id,
                )
            if fdc_permit_accumulator is not None:
                fdc_rate_limiter_waited_seconds = fdc_permit_accumulator.total_waited_seconds
                fdc_rate_limiter_slot_acquired = fdc_permit_accumulator.slot_acquired
                fdc_rate_limiter_queue_timeout = fdc_permit_accumulator.queue_timeout
                fdc_rate_limiter_state_file_error = fdc_permit_accumulator.state_file_error
                fdc_rate_limiter_queue_ticket = fdc_permit_accumulator.last_queue_ticket or ""
                fdc_rate_limiter_queue_position_at_first_wait = (
                    fdc_permit_accumulator.queue_position_at_first_wait
                    if fdc_permit_accumulator.queue_position_at_first_wait is not None
                    else -1
                )
                fdc_rate_limiter_requeue_count = fdc_permit_accumulator.requeue_count
                fdc_rate_limiter_final_waited_seconds = fdc_permit_accumulator.final_waited_seconds
                fdc_rate_limiter_queue_deadline_exceeded = (
                    fdc_permit_accumulator.queue_deadline_exceeded
                )
            else:
                fdc_rate_limiter_waited_seconds = 0.0
                fdc_rate_limiter_slot_acquired = True
                fdc_rate_limiter_queue_timeout = False
                fdc_rate_limiter_state_file_error = False
                fdc_rate_limiter_queue_ticket = ""
                fdc_rate_limiter_queue_position_at_first_wait = -1
                fdc_rate_limiter_requeue_count = 0
                fdc_rate_limiter_final_waited_seconds = 0.0
                fdc_rate_limiter_queue_deadline_exceeded = False
            _diag(
                "FDC provider observation: "
                f"http_attempts={fdc_provider_http_attempt_count} "
                f"http_429={fdc_provider_http_429_count} "
                f"exec_seconds={fdc_provider_execution_seconds:.1f} "
                f"final_status={fdc_provider_final_status} "
                f"limiter_waited={fdc_rate_limiter_waited_seconds:.1f}s "
                f"slot_acquired={fdc_rate_limiter_slot_acquired} "
                f"queue_timeout={fdc_rate_limiter_queue_timeout} "
                f"state_file_error={fdc_rate_limiter_state_file_error} "
                f"queue_ticket={fdc_rate_limiter_queue_ticket} "
                f"queue_position_at_first_wait={fdc_rate_limiter_queue_position_at_first_wait} "
                f"requeue_count={fdc_rate_limiter_requeue_count} "
                f"final_waited_seconds={fdc_rate_limiter_final_waited_seconds:.1f} "
                f"queue_deadline_exceeded={fdc_rate_limiter_queue_deadline_exceeded}"
            )
            _diag(f"FinalDecisionComposerAgent completed: symbol={composer_output.symbol} decision_type={composer_output.decision_type}")
            logger.info(
                "FinalDecisionComposerAgent completed: summary_len=%s symbol=%s decision_type=%s confidence=%s",
                len(composer_output.summary) if composer_output.summary else 0,
                composer_output.symbol,
                composer_output.decision_type,
                composer_output.confidence,
            )

        if is_missing_agent_symbol(composer_output.symbol) and inp.symbol:
            from dataclasses import replace
            composer_output = replace(composer_output, symbol=inp.symbol)

        # --- Normalize decision_type ---
        normalized_dt = normalize_decision_type(composer_output.decision_type)
        if normalized_dt != composer_output.decision_type:
            from dataclasses import replace
            composer_output = replace(composer_output, decision_type=normalized_dt)

        duration = time.monotonic() - t0

        # ★ EI 실패 시 error metadata 캡처 → orchestrator가 __error__ 주입에 사용
        ei_error_metadata: dict[str, Any] | None = getattr(ei_agent, "last_error_metadata", None)

        # ── 3. Serialize output ────────────────────────────────────────
        # 2026-08-17: fdc_skipped/skip_reason_codes는 위 "FDC Skip Check"
        # (skip_fdc/skip_reason)의 실제 결과를 그대로 반영한다 — 이 스크립트는
        # EI를 생략하는 로직이 없으므로 ei_skipped는 항상 False, AR도 항상
        # 실행되므로 ar_skipped도 항상 False다.
        output = AgentSubprocessOutput(
            success=True,
            event_output=dataclass_to_dict(event_output),
            risk_output=dataclass_to_dict(risk_output),
            compliance_output=dataclass_to_dict(compliance_output),
            composer_output=dataclass_to_dict(composer_output),
            duration_seconds=duration,
            ei_error_metadata=ei_error_metadata,
            ei_skipped=False,
            ar_skipped=False,
            fdc_skipped=skip_fdc,
            skip_reason_codes=(skip_reason,) if skip_fdc and skip_reason else (),
            fdc_ready_at=fdc_ready_at,
            rate_limiter_waited_seconds=fdc_rate_limiter_waited_seconds,
            rate_limiter_slot_acquired=fdc_rate_limiter_slot_acquired,
            rate_limiter_queue_timeout=fdc_rate_limiter_queue_timeout,
            rate_limiter_state_file_error=fdc_rate_limiter_state_file_error,
            provider_http_attempt_count=fdc_provider_http_attempt_count,
            provider_http_429_count=fdc_provider_http_429_count,
            provider_execution_seconds=fdc_provider_execution_seconds,
            provider_final_status=fdc_provider_final_status,
            rate_limiter_queue_ticket=fdc_rate_limiter_queue_ticket,
            rate_limiter_queue_position_at_first_wait=(
                fdc_rate_limiter_queue_position_at_first_wait
            ),
            rate_limiter_requeue_count=fdc_rate_limiter_requeue_count,
            rate_limiter_final_waited_seconds=fdc_rate_limiter_final_waited_seconds,
            rate_limiter_queue_deadline_exceeded=fdc_rate_limiter_queue_deadline_exceeded,
            requires_fdc_dispatch=(inp.mode == "pre_fdc" and not skip_fdc),
        )
        _write_output(output)
        if skip_fdc:
            _diag(f"SUCCESS: FDC skipped — all 3 agents completed in {duration:.2f}s")
        elif inp.mode == "pre_fdc":
            _diag(f"SUCCESS: pre_fdc completed, FDC dispatch required, in {duration:.2f}s")
        else:
            _diag(f"SUCCESS: all 3 agents completed in {duration:.2f}s")

    except Exception as exc:
        duration = time.monotonic() - t0
        _diag(f"EXCEPTION after {duration:.2f}s: {exc}")
        logger.exception("Agent subprocess failed after %.2fs", duration)
        _write_error_output(str(exc), duration=duration)
        sys.exit(1)
    finally:
        # PR D(2026-09-03) — global gate 때문에 이 subprocess가 DB pool을
        # 열었을 때만(flag on + legacy provider 호출 있음) 닫는다. flag가
        # 꺼져 있으면 global_gate_pool_opened가 False라 이 블록은 아무
        # 것도 하지 않는다(기존 동작 그대로).
        if global_gate_pool_opened:
            from agent_trading.db.connection import close_pool
            await close_pool()


def _write_output(output: AgentSubprocessOutput) -> None:
    """Serialize output to stdout as JSON.

    Thin wrapper around ``agent_trading.services.ai_agents.subprocess_io.
    write_agent_subprocess_output()`` — the actual payload-shape logic lives
    there (import-safe, no filesystem/env side effects) so it can be
    round-trip tested without importing this script module.

    2026-08-17 버그 수정 이력: ``compliance_output``이 한때 이 payload에서
    누락되어 있었다 — ``AgentSubprocessOutput``에는 채워지지만 stdout
    JSON에 쓰이지 않아, 부모 프로세스(``subprocess_helpers.py::
    deserialize_agent_output()``)가 항상 default ``AIComplianceOutput()``
    (``compliance_opinion="allow"``)으로 복원하는 결과를 낳았다. AC가
    deterministic bot으로 전환된 뒤에도 실제 계산 결과가 ``agent_runs``/
    ``decision_json``에 반영되지 않던 근본 원인이었다.
    """
    write_agent_subprocess_output(output, sys.stdout)


def _write_error_output(
    message: str,
    duration: float = 0.0,
) -> None:
    """Write an error output to stdout as JSON."""
    json.dump(
        {
            "success": False,
            "event_output": {},
            "risk_output": {},
            "composer_output": {},
            "error": message,
            "duration_seconds": duration,
        },
        sys.stdout,
        default=str,
        ensure_ascii=False,
    )
    sys.stdout.flush()


if __name__ == "__main__":
    asyncio.run(main())
