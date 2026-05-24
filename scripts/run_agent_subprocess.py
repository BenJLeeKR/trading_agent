#!/usr/bin/env python3
"""Subprocess entry point for running 3 agents (EI/AR/FDC) with isolation.

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
from datetime import datetime
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
    EventInterpretationAgent,
)
from agent_trading.services.ai_agents.ai_risk import AIRiskAgent
from agent_trading.services.ai_agents.final_decision_composer import (
    FinalDecisionComposerAgent,
)
from agent_trading.services.ai_agents.schemas import (
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
)
from agent_trading.services.common_types import dataclass_to_dict
from agent_trading.services.decision_orchestrator import (
    AssembledContext,
    ScoreResult,
)
from agent_trading.services.translation import (
    is_missing_agent_symbol,
    normalize_decision_type,
)

logger = logging.getLogger(__name__)

# Configure logging to stderr so parent can capture subprocess diagnostics.
# Without this, all logger.info() calls are silently dropped.
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# File-based diagnostic logging (bypasses pipe — survives timeout).
# ★ 반드시 /workspace/agent_trading/logs 경로 사용 (운영 정책)
import os as _os
_DIAG_LOG_DIR = "/workspace/agent_trading/logs"
_os.makedirs(_DIAG_LOG_DIR, exist_ok=True)
_DIAG_LOG = f"{_DIAG_LOG_DIR}/subprocess_diag_{os.getpid()}.log"


def _diag(msg: str) -> None:
    """Write a timestamped diagnostic message to a file.

    This file survives the parent's timeout+kill cycle, providing
    visibility into what the subprocess was doing before it hung.
    """
    try:
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

    # Provider configuration hints
    model_id: str | None = None
    prompt_id: str | None = None

    # --- Provider configuration for AI client creation ---
    llm_provider: str = "deepseek"
    provider_api_key: str = ""
    provider_base_url: str = ""
    provider_model_id: str = ""
    provider_timeout_seconds: int = 120


@dataclass(slots=True, frozen=True)
class AgentSubprocessOutput:
    """Output payload serialized back to the parent orchestrator.

    Contains the structured outputs of all 3 agents, or error details
    if the subprocess failed before completing all agents.
    """

    success: bool
    event_output: dict[str, Any] = field(default_factory=dict)
    risk_output: dict[str, Any] = field(default_factory=dict)
    composer_output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_seconds: float = 0.0
    # ★ EI 실패 시 error metadata (orchestrator가 structured_output_json["__error__"]에 주입)
    ei_error_metadata: dict[str, Any] | None = None


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


def _reconstruct_context(raw: dict[str, Any]) -> AssembledContext:
    """Reconstruct an ``AssembledContext`` from a JSON-safe dict.

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

    # ── Build AssembledContext with reconstructed fields ─────────────
    return AssembledContext(
        decision_context=decision_context,
        config_version=raw.get("config_version"),  # None-safe
        recent_events=recent_events,
        score=score,
        position_snapshot=position_snapshot,
        cash_balance_snapshot=cash_balance_snapshot,
        risk_limit_snapshot=risk_limit_snapshot,
        source_type=raw.get("source_type", "core"),
    )


def _reconstruct_request(
    inp: AgentSubprocessInput,
    *,
    event_output: EventInterpretationOutput | None = None,
    risk_output: AIRiskOutput | None = None,
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

    # Condition 2: 유의미한 이벤트 없음 + 미보유 → 결정론적 HOLD
    # ★ is_degraded가 True이면 skip하지 않음 (degraded 상태에서는 FDC가 필요)
    no_material = (
        hasattr(event_output, "aggregate_view")
        and event_output.aggregate_view.no_material_events
        and not event_output.is_degraded
    )
    if no_material and not has_position:
        return (True, "no_material_events_no_position", FinalDecisionComposerOutput(
            symbol=symbol,
            decision_type="HOLD",
            confidence=0.0,
            summary=f"{symbol} — 유의미한 이벤트 없음. FDC 생략.",
            reason_codes=("no_material_events", "no_position"),
        ))

    # Condition 3: 최근 이벤트 0건 + 미보유 → 결정론적 HOLD
    if not context.recent_events and not has_position:
        return (True, "no_events_no_position", FinalDecisionComposerOutput(
            symbol=symbol,
            decision_type="HOLD",
            confidence=0.0,
            summary=f"{symbol} — 최근 이벤트 없음. FDC 생략.",
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

    # --- 생략 불가 → 정상 FDC 호출 ---
    return (False, "", FinalDecisionComposerOutput())


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

    # ── 1b. Create provider client (if configured) ─────────────────────
    provider_client: AIProviderClient | None = None
    if inp.provider_api_key and inp.provider_base_url:
        from agent_trading.services.ai_agents import OpenAICompatibleClient
        logger.info(
            "Creating OpenAICompatibleClient: base_url=%s model_id=%s timeout=%s",
            inp.provider_base_url,
            inp.provider_model_id or "deepseek-chat",
            inp.provider_timeout_seconds,
        )
        _diag("Creating OpenAICompatibleClient ...")
        provider_client = OpenAICompatibleClient(
            api_key=inp.provider_api_key,
            base_url=inp.provider_base_url,
            model_id=inp.provider_model_id or "deepseek-chat",
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

    # ── 2. Run agents sequentially ─────────────────────────────────────
    try:
        # --- 2a. Event Interpretation Agent ---
        logger.info("Starting EventInterpretationAgent.run() ...")
        _diag("Starting EventInterpretationAgent.run() ...")
        ei_agent = EventInterpretationAgent(provider_client=provider_client)
        request = _reconstruct_request(inp)
        input_event_count = len(request.context.recent_events)
        _diag(f"Context reconstructed: events={input_event_count}")
        event_output: EventInterpretationOutput = await ei_agent.run(request)
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
        ar_agent = AIRiskAgent(provider_client=provider_client)
        request_with_ei = _reconstruct_request(inp, event_output=event_output)
        risk_output: AIRiskOutput = await ar_agent.run(request_with_ei)
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

        # --- 2c. FDC Skip Check (결정론적 비행동 조건이면 FDC 생략) ---
        skip_fdc, skip_reason, skip_output = _check_fdc_skip(
            inp=inp,
            request=request_with_ei,
            event_output=event_output,
            risk_output=risk_output,
        )

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
        else:
            # --- 2c. Final Decision Composer Agent ---
            logger.info("Starting FinalDecisionComposerAgent.run() ...")
            _diag("Starting FinalDecisionComposerAgent.run() ...")
            fdc_agent = FinalDecisionComposerAgent(provider_client=provider_client)
            request_with_ei_ar = _reconstruct_request(
                inp, event_output=event_output, risk_output=risk_output,
            )
            composer_output: FinalDecisionComposerOutput = await fdc_agent.run(request_with_ei_ar)
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
        output = AgentSubprocessOutput(
            success=True,
            event_output=dataclass_to_dict(event_output),
            risk_output=dataclass_to_dict(risk_output),
            composer_output=dataclass_to_dict(composer_output),
            duration_seconds=duration,
            ei_error_metadata=ei_error_metadata,
        )
        _write_output(output)
        if skip_fdc:
            _diag(f"SUCCESS: FDC skipped — all 3 agents completed in {duration:.2f}s")
        else:
            _diag(f"SUCCESS: all 3 agents completed in {duration:.2f}s")

    except Exception as exc:
        duration = time.monotonic() - t0
        _diag(f"EXCEPTION after {duration:.2f}s: {exc}")
        logger.exception("Agent subprocess failed after %.2fs", duration)
        _write_error_output(str(exc), duration=duration)
        sys.exit(1)


def _write_output(output: AgentSubprocessOutput) -> None:
    """Serialize output to stdout as JSON."""
    json.dump(
        {
            "success": output.success,
            "event_output": output.event_output,
            "risk_output": output.risk_output,
            "composer_output": output.composer_output,
            "error": output.error,
            "duration_seconds": output.duration_seconds,
            "ei_error_metadata": output.ei_error_metadata,
        },
        sys.stdout,
        default=str,
        ensure_ascii=False,
    )
    sys.stdout.flush()


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
