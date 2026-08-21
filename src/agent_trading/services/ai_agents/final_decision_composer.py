"""Stub and real implementations of the Final Decision Composer Agent.

This agent synthesises the outputs of the Event Interpretation and AI Risk
agents into a final structured decision (``FinalDecisionComposerOutput``).

Safe-fallback policy
--------------------
If an unexpected exception occurs during ``run()``, the agent logs a
warning and returns a default ``FinalDecisionComposerOutput``.  This
ensures that the calling orchestrator can always proceed.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import socket
from datetime import datetime, timezone

import httpx

from agent_trading.config.settings import _resolve_provider_model_id
from agent_trading.services.ai_agents._prompt_config import (
    MAX_EVENTS_FDC,
    MAX_INTERPRETED_EVENTS,
)
from agent_trading.services.ai_agents.prompt_context_projection import (
    append_shared_deterministic_context_sections,
)
from agent_trading.services.ai_agents.base import (
    AgentExecutionRequest,
    AIProviderClient,
    RawProviderResponse,
)
from agent_trading.services.ai_agents.provider_client import (
    PermitCallback,
    PermitDeniedError,
)
from agent_trading.services.ai_agents.schemas import (
    FinalDecisionComposerOutput,
    generate_json_schema,
)
from agent_trading.services.source_policy import allowed_fdc_decision_types

logger = logging.getLogger(__name__)


@dataclasses.dataclass(slots=True, frozen=True)
class ProviderCallObservation:
    """FDC provider 호출 1회의 관측성 스냅샷(성공/실패 공통).

    ``FinalDecisionComposerOutput``(LLM 응답 스키마)에는 절대 담지
    않는다 — 이 필드들이 늘어나면 ``generate_json_schema()``를 통해
    그대로 Gemini 프롬프트에 노출되기 때문이다(2026-08-21). 대신
    ``FinalDecisionComposerAgent.last_provider_observation``으로만
    노출하고, 호출자(``run_agent_subprocess.py``)가 이를 읽어
    ``AgentSubprocessOutput``(내부 전용 envelope)에 옮겨 담는다.
    """

    http_attempt_count: int = 0
    http_429_count: int = 0
    execution_seconds: float = 0.0
    rate_limiter_waited_seconds: float = 0.0
    rate_limiter_queue_timeout: bool = False
    rate_limiter_state_file_error: bool = False
    provider_final_status: str = ""


def _classify_provider_exception(exc: Exception) -> str:
    """예외를 fallback ``reason_codes`` 마커로 분류한다(관측성 전용).

    2026-08-18 결정: FDC provider 호출 실패 시 fallback이 정상 HOLD와
    저장값만으로 구분되지 않던 문제(429 재시도 소진 시 ``reason_codes``가
    항상 빈 튜플)를 고치기 위한 분류다. 이 마커는 관측 용도이며,
    ``decision_type="HOLD"`` fallback 정책 자체를 바꾸지 않는다.

    2026-08-21 추가: ``PermitDeniedError``(rate limiter가 permit을
    거부해 HTTP 요청을 아예 보내지 않은 경우)를 최우선으로 분류한다.
    이 경우는 실제 Gemini 호출이 없었으므로 ``provider_rate_limit``
    (실제 429)과 DB에서 명확히 구분돼야 한다.
    """
    if isinstance(exc, PermitDeniedError):
        return {
            "queue_timeout": "provider_queue_timeout",
            "state_file_error": "provider_limiter_unavailable",
        }.get(exc.result.denial_reason or "", "provider_limiter_unavailable")
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 429:
            return "provider_rate_limit"
        if 500 <= status < 600:
            return "provider_error"
    if isinstance(exc, (json.JSONDecodeError, TypeError, ValueError)):
        return "provider_parse_error"
    if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
        return "provider_timeout"
    if isinstance(exc, (httpx.TransportError, socket.gaierror)):
        return "provider_error"
    return "provider_error"


class StubFinalDecisionComposerAgent:
    """Stub Final Decision Composer — returns default ("hold") output.

    This agent conforms to the ``ProviderAIAgent`` protocol.

    Parameters
    ----------
    schema_version
        Version string reported via the ``schema_version`` property.
    """

    def __init__(self, schema_version: str = "v1") -> None:
        self._schema_version = schema_version
        # Stub은 provider 호출이 없으므로 관측값도 없다(None) — 호출자가
        # 실제 agent와 동일한 속성 접근 경로로 안전하게 읽을 수 있게 한다.
        self.last_provider_observation: ProviderCallObservation | None = None

    @property
    def agent_name(self) -> str:
        return "final_decision_composer"

    @property
    def schema_version(self) -> str:
        return self._schema_version

    async def run(
        self, request: AgentExecutionRequest
    ) -> FinalDecisionComposerOutput:
        """Execute the agent and return a structured output.

        The stub implementation:
        * Logs the request for observability.
        * Returns a default ``FinalDecisionComposerOutput`` (hold action,
          zero adjustments, full consensus).

        Safe fallback: any exception is caught, a warning is logged, and
        a default output is returned.
        """
        logger.debug(
            "StubFinalDecisionComposerAgent.run() called: "
            "decision_context_id=%s correlation_id=%s",
            request.decision_context_id,
            request.correlation_id,
        )

        try:
            # --- Stub: no actual Provider call ---
            return FinalDecisionComposerOutput()
        except Exception:
            logger.warning(
                "StubFinalDecisionComposerAgent.run() failed — "
                "returning default output (safe fallback).",
                exc_info=True,
            )
            return FinalDecisionComposerOutput()


class FinalDecisionComposerAgent:
    """Real Final Decision Composer — calls a Provider via AIProviderClient.

    Conforms to the ``ProviderAIAgent`` protocol.

    This agent receives an ``AgentExecutionRequest`` that may carry:
    * ``event_interpretation_output`` — output from the Event Interpretation
      Agent (aggregate view, interpreted events).
    * ``ai_risk_output`` — output from the AI Risk Agent (risk opinion,
      risk score, size adjustment factor, reason codes, opposing evidence).

    The prompt is built from the assembled context plus both agent outputs.
    When either output is ``None`` (not provided by the orchestrator), the
    prompt simply omits that section — preserving backward compatibility.

    Parameters
    ----------
    provider_client
        The ``AIProviderClient`` instance used to call the external Provider.
    model_id
        The model identifier (e.g. ``"deepseek-v4-pro"``).
    schema_version
        Version string reported via the ``schema_version`` property.
    """

    def __init__(
        self,
        provider_client: AIProviderClient,
        *,
        model_id: str | None = None,
        schema_version: str = "v1",
        acquire_permit: PermitCallback | None = None,
    ) -> None:
        self._provider = provider_client
        self._model_id = model_id or _resolve_provider_model_id()
        self._schema_version = schema_version
        # 2026-08-21: rate limiter permit 콜백 — ``None``이면 기존 동작과
        # 100% 동일(permit 체크 없이 즉시 호출). 실제 콜백은
        # ``run_agent_subprocess.py``가 ``fdc_rate_limiter.wait_for_fdc_slot()``
        # 을 감싸서 주입한다(이 클래스/파일은 그 구현을 import하지 않는다).
        self._acquire_permit = acquire_permit
        self.last_provider_observation: ProviderCallObservation | None = None

    @property
    def agent_name(self) -> str:
        return "final_decision_composer"

    @property
    def schema_version(self) -> str:
        return self._schema_version

    async def run(
        self, request: AgentExecutionRequest
    ) -> FinalDecisionComposerOutput:
        """Execute the agent and return a structured output.

        Builds a system prompt with the expected JSON schema, sends the
        request context to the Provider, parses the response, and returns
        a validated ``FinalDecisionComposerOutput``.

        Safe fallback: any exception is caught, a warning is logged, and
        a default output (``decision_type="HOLD"``) is returned with
        agent identity preserved.
        """
        logger.debug(
            "FinalDecisionComposerAgent.run() called: "
            "decision_context_id=%s correlation_id=%s model_id=%s",
            request.decision_context_id,
            request.correlation_id,
            self._model_id,
        )

        loop = asyncio.get_event_loop()
        started_at = loop.time()
        try:
            system_prompt = self._build_system_prompt(source_type=request.source_type)
            user_prompt = self._build_user_prompt(request)

            raw_response: RawProviderResponse = await self._provider.generate_structured(
                model_id=self._model_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format=FinalDecisionComposerOutput,
                acquire_permit=self._acquire_permit,
            )
            self.last_provider_observation = ProviderCallObservation(
                http_attempt_count=raw_response.http_attempt_count,
                http_429_count=raw_response.http_429_count,
                execution_seconds=loop.time() - started_at,
                provider_final_status="success",
            )

            result: FinalDecisionComposerOutput = raw_response.parsed  # type: ignore[assignment]

            # Override metadata fields from request / agent identity
            result = FinalDecisionComposerOutput(
                schema_version=result.schema_version or self._schema_version,
                agent_name=result.agent_name or self.agent_name,
                decision_context_id=(
                    str(request.decision_context_id)
                    if request.decision_context_id
                    else None
                ),
                symbol=result.symbol,
                decision_type=result.decision_type,
                side=result.side,
                entry_style=result.entry_style,
                time_horizon=result.time_horizon,
                confidence=result.confidence,
                conviction=result.conviction,
                reason_codes=result.reason_codes,
                opposing_evidence=result.opposing_evidence,
                execution_preferences=result.execution_preferences,
                sizing_hint=result.sizing_hint,
                exit_plan_hint=result.exit_plan_hint,
                summary=result.summary,
            )
            result = self._guard_held_position_decision_type(
                result, source_type=request.source_type,
            )

            logger.info(
                "FinalDecisionComposerAgent succeeded: "
                "symbol=%s decision_type=%s confidence=%.2f",
                result.symbol,
                result.decision_type,
                result.confidence,
            )
            return result

        except Exception as exc:
            reason_marker = _classify_provider_exception(exc)
            permit_result = exc.result if isinstance(exc, PermitDeniedError) else None
            self.last_provider_observation = ProviderCallObservation(
                http_attempt_count=getattr(exc, "http_attempt_count", 0),
                http_429_count=getattr(exc, "http_429_count", 0),
                execution_seconds=loop.time() - started_at,
                rate_limiter_waited_seconds=(
                    permit_result.waited_seconds if permit_result else 0.0
                ),
                rate_limiter_queue_timeout=reason_marker == "provider_queue_timeout",
                rate_limiter_state_file_error=reason_marker == "provider_limiter_unavailable",
                provider_final_status=reason_marker,
            )
            logger.warning(
                "FinalDecisionComposerAgent failed — returning default HOLD output "
                "(safe fallback). decision_context_id=%s reason=%s",
                request.decision_context_id,
                reason_marker,
                exc_info=True,
            )
            # Preserve agent identity and request metadata in fallback output.
            # 2026-08-18: reason_codes/summary에 fallback 사유를 남겨
            # decision_json/agent_runs 저장값만으로 정상 HOLD와 구분 가능하게
            # 한다(decision_type="HOLD" fallback 정책 자체는 그대로 유지).
            fallback = FinalDecisionComposerOutput(
                schema_version=self._schema_version,
                agent_name=self.agent_name,
                decision_context_id=(
                    str(request.decision_context_id)
                    if request.decision_context_id
                    else None
                ),
                reason_codes=(reason_marker,),
                summary=f"provider fallback: {reason_marker}",
            )
            return fallback

    def _build_system_prompt(self, *, source_type: str | None = None) -> str:
        """Build the system prompt describing the expected output schema.

        ``source_type``이 ``"held_position"``이면 ``decision_type`` 허용
        목록을 ``REDUCE``/``EXIT``/``HOLD``/``WATCH``로 좁힌다(2026-08-18
        KST 추가) — 신규 매수(APPROVE/BUY)는 이 lane에서 의미론적으로
        허용 대상이 아니므로, 모델이 매번 "왜 안 사는지"를 추론/서술하는
        토큰 낭비를 프롬프트 단계에서부터 줄인다. 나머지 source_type
        (``None`` 포함, 기존 호출부 하위 호환)은 기존 전체 허용 목록을
        그대로 유지한다.
        """
        schema_json = json.dumps(
            generate_json_schema(FinalDecisionComposerOutput), indent=2
        )
        allowed_decision_types = allowed_fdc_decision_types(source_type)
        normalized_source_type = (source_type or "core").strip().lower()

        held_position_scope_section = ""
        if normalized_source_type == "held_position":
            held_position_scope_section = (
                "## Held Position Decision Scope (source_type=held_position)\n"
                "- This symbol is ALREADY HELD. Valid decision_type is ONLY: "
                "REDUCE, EXIT, HOLD, WATCH.\n"
                "- APPROVE and BUY are INVALID for source_type=held_position — "
                "do NOT consider or reason about additional buying for an "
                "already-held symbol. Only evaluate whether to reduce/exit the "
                "position, or continue holding/watching it.\n\n"
            )

        return (
            "You are a Final Decision Composer for a trading system. "
            "Synthesise the outputs of the Event Interpretation Agent and "
            "the AI Risk Agent, together with the assembled trading context, "
            "to produce a structured final decision.\n\n"
            "Output must be valid JSON matching this schema:\n"
            f"{schema_json}\n\n"
            "IMPORTANT: The following fields MUST use canonical English enum values:\n"
            f"- decision_type: one of {', '.join(allowed_decision_types)}\n"
            "- side: BUY or SELL\n"
            "- entry_style: LIMIT, MARKET, VWAP, TWAP\n"
            "- time_horizon: short, swing, long\n"
            "- reason_codes: machine-readable English codes\n\n"
            f"{held_position_scope_section}"
            "## No-Event Policy\n"
            "- no_material_events + evidence_strength=none (core): "
            "insufficient information to act → HOLD. "
            "WATCH may be considered as a valid non-HOLD option "
            "(monitor without entering).\n"
            "- no_material_events + evidence_strength=none (market_overlay): "
            "can be APPROVED or WATCHed.\n"
            "- no_material_events + evidence_strength=weak: "
            "WATCH viable for non-core; for core, "
            "WATCH may be considered (monitor without entering) "
            "as a valid non-HOLD option.\n"
            "- evidence_strength=moderate/strong: "
            "Evaluate normally → APPROVE/REDUCE/EXIT.\n"
            "- 'negative signal' (bearish bias): "
            "HOLD/REDUCE regardless of source. "
            "IMPORTANT: 'negative signal' is NOT the same as 'no event'.\n\n"
            "## Source Type Consideration\n"
            "- core → conservative; WATCH may be viable when evidence is weak.\n"
            "- held_position → need clear signal; additional buying "
            "(APPROVE/BUY) is out of scope — see Held Position Decision "
            "Scope above;\n"
            "- event_overlay → consider events; market_overlay → no-event OK.\n\n"
            "Narrative fields (summary, opposing_evidence) MUST be written in Korean. "
            "Machine-readable fields listed above MUST remain in English."
        )

    def _guard_held_position_decision_type(
        self,
        result: FinalDecisionComposerOutput,
        *,
        source_type: str | None,
    ) -> FinalDecisionComposerOutput:
        """held_position에서 허용 범위 밖 ``decision_type``을 정규화한다.

        이 검증은 ``decision_orchestrator._check_source_policy_upgrade_
        guard()``(오케스트레이터 레벨 최종 안전판)와는 **다른 계층**이다.
        여기서는 FDC 에이전트 출력이 애초에 스키마상 유효한 선택지를
        반환했는지를 에이전트 경계에서 확인한다 — 오케스트레이터 guard가
        실행되기 전에 한 번 더 방어하는 것이며, 의도적으로 중복을
        허용한다(두 계층의 목적이 다름: 여기는 "AI 선택지 제한",
        오케스트레이터 쪽은 "최종 제출 안전판"). ``deterministic_trigger``의
        WATCH/HOLD 세부 판단은 오케스트레이터 guard가 여전히 authoritative
        하게 담당하므로, 여기서는 안전한 기본값(HOLD)으로만 정규화한다.
        """
        allowed = allowed_fdc_decision_types(source_type)
        normalized_type = (result.decision_type or "").strip().upper()
        if not normalized_type or normalized_type in allowed:
            return result

        logger.warning(
            "FDC returned out-of-scope decision_type for source_type=%s: "
            "decision_type=%s allowed=%s — normalizing to HOLD.",
            source_type,
            result.decision_type,
            allowed,
        )
        guarded_reason_codes = tuple(
            dict.fromkeys(
                tuple(result.reason_codes or ())
                + ("fdc_held_position_decision_type_guard",)
            )
        )
        guard_note = (
            f"[fdc_held_position_decision_type_guard] decision_type="
            f"{normalized_type} is invalid for source_type={source_type} "
            "— normalized to HOLD."
        )
        guarded_summary = (
            f"{result.summary} | {guard_note}" if result.summary else guard_note
        )
        return dataclasses.replace(
            result,
            decision_type="HOLD",
            side="",
            reason_codes=guarded_reason_codes,
            summary=guarded_summary,
        )

    def _build_user_prompt(self, request: AgentExecutionRequest) -> str:
        """Build the user prompt with the current request context.

        The prompt includes:
        * Assembled context score and reason codes.
        * Event Interpretation output (aggregate view, events summary) —
          only when ``event_interpretation_output`` is provided.
        * AI Risk output (risk opinion, risk score, size adjustment factor,
          reason codes, opposing evidence) — only when ``ai_risk_output``
          is provided.
        * AI Compliance output (compliance opinion, policy flags, reason codes,
          opposing evidence) — only when ``ai_compliance_output`` is provided.
        * Recent external events.

        When either agent output is ``None``, the corresponding section is
        omitted — the flow never breaks.
        """
        context = request.context
        score = context.score
        events = context.recent_events or []

        lines: list[str] = [
            f"Correlation ID: {request.correlation_id}",
        ]

        # Symbol source priority:
        #   1. explicit request.symbol
        #   2. context.recent_events first non-None e.symbol
        #   3. Fallback "(not available)"
        symbol: str = "(not available)"
        if request.symbol:
            symbol = request.symbol
        elif events:
            for e in events:
                if e.symbol:
                    symbol = e.symbol
                    break
        lines.append(f"Symbol: {symbol}")
        if request.market:
            lines.append(f"Market: {request.market}")
        lines.append(f"Source type: {request.source_type}")

        # Decision context
        dc = context.decision_context
        if dc:
            lines.append(f"Account ID: {dc.account_id}")

        # === Assembled context score ===
        if score:
            lines.append("")
            lines.append("=== Assembled Context Score ===")
            lines.append(f"Score: {score.score} (threshold: {score.threshold})")
            if score.reason_codes:
                lines.append(f"Reason codes: {', '.join(score.reason_codes)}")

        append_shared_deterministic_context_sections(
            lines,
            context,
            profile="final_decision_composer",
        )

        # === Event Interpretation output (if available) ===
        ei_output = request.event_interpretation_output
        if ei_output is not None:
            lines.append("")
            lines.append("=== Event Interpretation Output ===")
            lines.append(f"Overall bias: {ei_output.aggregate_view.overall_bias}")
            lines.append(f"Event conflict: {ei_output.aggregate_view.event_conflict}")
            lines.append(f"Evidence strength: {ei_output.aggregate_view.evidence_strength}")
            lines.append(f"Event count: {ei_output.detected_event_count}")
            lines.append(f"No material events: {ei_output.aggregate_view.no_material_events}")
            if ei_output.aggregate_view.top_reason_codes:
                lines.append(
                    "Top reason codes: "
                    f"{', '.join(ei_output.aggregate_view.top_reason_codes)}"
                )

            # Interpreted events summary (max 10)
            interpreted = ei_output.events or ()
            if interpreted:
                lines.append(f"Interpreted events ({len(interpreted)}):")
                for ie in interpreted[:MAX_INTERPRETED_EVENTS]:
                    if isinstance(ie, dict):
                        summary = ie.get("summary") or "(no summary)"
                        lines.append(f"  - [{ie.get('event_type', '?')}] {summary}")
                        lines.append(
                            f"    impact={ie.get('impact_direction', '?')} "
                            f"confidence={ie.get('confidence', '?')}"
                        )
                    else:
                        summary = ie.summary or "(no summary)"
                        lines.append(f"  - [{ie.event_type}] {summary}")
                        lines.append(
                            f"    impact={ie.impact_direction} "
                            f"confidence={ie.confidence}"
                        )

        # === AI Risk output (if available) ===
        ar_output = request.ai_risk_output
        if ar_output is not None:
            lines.append("")
            lines.append("=== AI Risk Output ===")
            lines.append(f"Risk opinion: {ar_output.risk_opinion}")
            lines.append(f"Risk score: {ar_output.risk_score}")
            lines.append(f"Confidence: {ar_output.confidence}")
            lines.append(f"Size adjustment factor: {ar_output.size_adjustment_factor}")
            if ar_output.reason_codes:
                lines.append(f"Reason codes: {', '.join(ar_output.reason_codes)}")
            if ar_output.opposing_evidence:
                lines.append("Opposing evidence:")
                for oe in ar_output.opposing_evidence:
                    lines.append(f"  - {oe}")

        ac_output = request.ai_compliance_output
        if ac_output is not None:
            lines.append("")
            lines.append("=== AI Compliance Output ===")
            lines.append(f"Compliance opinion: {ac_output.compliance_opinion}")
            lines.append(f"Compliance score: {ac_output.compliance_score}")
            lines.append(f"Confidence: {ac_output.confidence}")
            if ac_output.policy_flags:
                lines.append(f"Policy flags: {', '.join(ac_output.policy_flags)}")
            if ac_output.reason_codes:
                lines.append(f"Reason codes: {', '.join(ac_output.reason_codes)}")
            if ac_output.opposing_evidence:
                lines.append("Opposing evidence:")
                for oe in ac_output.opposing_evidence:
                    lines.append(f"  - {oe}")


        # === Recent events ===
        lines.append("")
        lines.append(f"Recent events ({len(events)}):")
        now = datetime.now(timezone.utc)
        for e in events[:MAX_EVENTS_FDC]:
            headline = e.headline or "(no headline)"

            parts: list[str] = []
            if e.source_name:
                parts.append(f"[src:{e.source_name}]")
            if e.source_reliability_tier:
                parts.append(f"[tier:{e.source_reliability_tier}]")
            if e.event_type:
                parts.append(f"[{e.event_type}]")
            if e.published_at:
                parts.append(f"[{e.published_at.strftime('%Y-%m-%d')}]")
            if e.issuer_code:
                parts.append(f"[issuer:{e.issuer_code}]")
            if e.severity and e.severity != "medium":
                parts.append(f"[severity:{e.severity}]")
            if e.direction and e.direction not in ("neutral", ""):
                parts.append(f"[{e.direction}]")

            stale_mark = ""
            if e.ingested_at and (now - e.ingested_at).total_seconds() > 86400:
                stale_mark = " ⚠️STALE"

            tagged = " ".join(parts)
            lines.append(f"  {tagged}{stale_mark} {headline}")

        return "\n".join(lines)
