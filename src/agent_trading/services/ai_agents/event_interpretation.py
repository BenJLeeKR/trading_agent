"""Event Interpretation Agent — stub and real implementations.

This agent interprets recent external events and produces a structured
``EventInterpretationOutput``.

* ``StubEventInterpretationAgent`` — always returns default / empty values
  (no actual Provider API call).
* ``EventInterpretationAgent`` — calls a real Provider via
  ``AIProviderClient``.

Safe-fallback policy
--------------------
If an unexpected exception occurs during ``run()``, the agent logs a
warning and returns a default ``EventInterpretationOutput``.  This
ensures that the calling orchestrator can always proceed.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from agent_trading.services.ai_agents.base import (
    AIProviderClient,
    AgentExecutionRequest,
    ProviderAIAgent,
    RawProviderResponse,
)
from agent_trading.services.ai_agents.schemas import (
    EventInterpretationOutput,
    InterpretedEvent,
    AggregateEventView,
    generate_json_schema,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_ei_summary(
    output: EventInterpretationOutput,
    input_event_count: int = 0,
) -> str:
    """EI 출력에서 deterministic 한국어 요약 문자열 생성 (추가 LLM 호출 없음).

    ``aggregate_view``와 ``events`` 정보만 사용.

    Parameters
    ----------
    output
        EI 출력 객체.
    input_event_count
        LLM 호출 전 입력 이벤트 수. self-contradiction/provider-failure 케이스에서
        감지된 이벤트 수를 표시하는 데 사용.

    Notes
    -----
    Case 1 — 정상 + events 있음: ``(N건) {preview}, 전반 {bias}, 근거:{strength}``
    Case 2 — Degraded + events 있음: ``(N건) {preview}, 전반 {bias}, (일부 해석 누락)``
    Case 3 — Self-contradiction: ``(N건) 입력 이벤트 감지됨. 세부 이벤트 추출 누락.``
    Case 4 — Provider failure: ``(N건) 입력 이벤트 감지됨. AI 분석 실패.``
    Case 5 — 진짜 no-event: ``유의미한 신규 이벤트 없음. 전반 {bias}.``
    Case 6 — Fallback default: ``이벤트 분석을 수행할 수 없습니다.``
    """
    av = output.aggregate_view
    is_degraded = output.is_degraded
    degraded_reason = av.degraded_reason
    has_events = bool(output.events)
    _event_count = av.event_count  # LLM 응답 (신뢰)

    # 편의 변수
    bias_kor = {"positive": "긍정", "negative": "부정", "neutral": "중립"}
    bias_str = bias_kor.get(av.overall_bias, av.overall_bias)

    # ── Case 1: 정상 + events 있음 ──
    if has_events and not is_degraded:
        event_count_display = len(output.events)
        parts: list[str] = []
        parts.append(f"전반 {bias_str}")

        # 대표 이벤트 1건 요약 (있으면)
        first = output.events[0]
        if first.summary:
            preview = first.summary.split(".")[0] if "." in first.summary else first.summary
            if len(preview) > 80:
                preview = preview[:77] + "..."
            parts.insert(0, preview)

        # evidence strength
        if av.evidence_strength and av.evidence_strength not in ("none", ""):
            parts.append(f"근거:{av.evidence_strength}")

        return f"({event_count_display}건) " + ", ".join(parts)

    # ── Case 2: Degraded + events 있음 ──
    if has_events and is_degraded:
        event_count_display = len(output.events)
        parts = [f"전반 {bias_str}"]
        first = output.events[0]
        if first.summary:
            preview = first.summary.split(".")[0] if "." in first.summary else first.summary
            if len(preview) > 80:
                preview = preview[:77] + "..."
            parts.insert(0, preview)
        if av.evidence_strength and av.evidence_strength not in ("none", ""):
            parts.append(f"근거:{av.evidence_strength}")
        parts.append("(일부 해석 누락)")
        return f"({event_count_display}건) " + ", ".join(parts)

    # ── Case 3: Self-contradiction (events=[] + input>0) ──
    if is_degraded and degraded_reason == "self_contradiction_corrected":
        return (
            f"({input_event_count}건) 입력 이벤트 감지됨. "
            f"세부 이벤트 추출 누락."
        )

    # ── Case 4: Provider failure (events=[] + degraded) ──
    if is_degraded and not has_events and degraded_reason in ("provider_error",):
        return (
            f"({input_event_count}건) 입력 이벤트 감지됨. "
            f"AI 분석 실패."
        )

    # ── Case 5: 진짜 no-event (events=[] + input=0, 정상) ──
    if av.no_material_events and not has_events and not is_degraded:
        if av.overall_bias == "negative":
            return "유의미한 신규 이벤트 없음. 전반 부정적."
        elif av.overall_bias == "positive":
            return "유의미한 신규 이벤트 없음. 전반 긍정."
        else:
            return "유의미한 신규 이벤트 없음. 전반 중립."

    # ── Case 6: Fallback default ──
    return "이벤트 분석을 수행할 수 없습니다."


# ---------------------------------------------------------------------------
# Stub (existing, unchanged)
# ---------------------------------------------------------------------------


class StubEventInterpretationAgent:
    """Stub Event Interpretation Agent — returns default output.

    This agent conforms to the ``ProviderAIAgent`` protocol.

    Parameters
    ----------
    schema_version
        Version string reported via the ``schema_version`` property.
    """

    def __init__(self, schema_version: str = "v1") -> None:
        self._schema_version = schema_version

    @property
    def agent_name(self) -> str:
        return "event_interpretation"

    @property
    def schema_version(self) -> str:
        return self._schema_version

    async def run(self, request: AgentExecutionRequest) -> EventInterpretationOutput:
        """Execute the agent and return a structured output.

        The stub implementation:
        * Logs the request for observability.
        * Returns a default ``EventInterpretationOutput``.

        Safe fallback: any exception is caught, a warning is logged, and
        a default output is returned.
        """
        logger.debug(
            "StubEventInterpretationAgent.run() called: "
            "decision_context_id=%s correlation_id=%s",
            request.decision_context_id,
            request.correlation_id,
        )

        try:
            # --- Stub: no actual Provider call ---
            output = EventInterpretationOutput()
            # deterministic 한국어 summary 생성 (LLM 호출 없음)
            object.__setattr__(output, "summary", _build_ei_summary(output))
            return output
        except Exception:
            logger.warning(
                "StubEventInterpretationAgent.run() failed — "
                "returning default output (safe fallback).",
                exc_info=True,
            )
            fallback = EventInterpretationOutput(
                aggregate_view=AggregateEventView(
                    interpretation_incomplete=True,
                    degraded_reason="provider_error",
                ),
            )
            object.__setattr__(fallback, "summary", _build_ei_summary(fallback))
            return fallback


# ---------------------------------------------------------------------------
# Real implementation
# ---------------------------------------------------------------------------


class EventInterpretationAgent:
    """Real Event Interpretation Agent — calls a Provider via AIProviderClient.

    Conforms to the ``ProviderAIAgent`` protocol.

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
        model_id: str = "deepseek-v4-pro",
        schema_version: str = "v1",
    ) -> None:
        self._provider = provider_client
        self._model_id = model_id
        self._schema_version = schema_version

    @property
    def agent_name(self) -> str:
        return "event_interpretation"

    @property
    def schema_version(self) -> str:
        return self._schema_version

    async def run(
        self, request: AgentExecutionRequest
    ) -> EventInterpretationOutput:
        """Execute the agent and return a structured output.

        Builds a system prompt with the expected JSON schema, sends the
        request context to the Provider, parses the response, and returns
        a validated ``EventInterpretationOutput``.

        Safe fallback: any exception is caught, a warning is logged, and
        a default output is returned (with input_event_count preserved
        in aggregate_view to avoid silent event loss).
        """
        logger.debug(
            "EventInterpretationAgent.run() called: "
            "decision_context_id=%s correlation_id=%s model_id=%s",
            request.decision_context_id,
            request.correlation_id,
            self._model_id,
        )

        # ★ 입력 events 수와 symbol을 try 블록 밖에서 캡처 (exception 발생 시에도 사용)
        input_event_count = len(request.context.recent_events or ())
        request_symbol = request.symbol or ""

        try:
            system_prompt = self._build_system_prompt()
            user_prompt = self._build_user_prompt(request)

            raw_response: RawProviderResponse = await self._provider.generate_structured(
                model_id=self._model_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format=EventInterpretationOutput,
            )

            # ★ 운영 디버깅: raw response 로깅 (raw_content는 provider의 원본 JSON)
            logger.info(
                "EI raw_response: symbol=%s correlation_id=%s "
                "input_events=%d raw_content_len=%d",
                request_symbol,
                request.correlation_id,
                input_event_count,
                len(raw_response.raw_content),
            )
            logger.debug(
                "EI raw_response raw_content: symbol=%s raw_content=%s",
                request_symbol,
                raw_response.raw_content,
            )

            result: EventInterpretationOutput = raw_response.parsed  # type: ignore[assignment]

            # Override metadata fields from request / agent identity
            # ★ schema_version은 항상 agent 설정값 사용 (LLM 응답 무시)
            # LLM이 "v1"/"1.0"/"1" 등 다양한 형식으로 반환하는 것을 방지
            result = EventInterpretationOutput(
                schema_version=self._schema_version,
                agent_name=result.agent_name or self.agent_name,
                decision_context_id=(
                    str(request.decision_context_id)
                    if request.decision_context_id
                    else None
                ),
                symbol=result.symbol or request_symbol,
                issuer_code=result.issuer_code,
                events=result.events,
                aggregate_view=result.aggregate_view,
            )

            # ★ Deterministic post-processing guard:
            #   입력 events > 0인데 output event_count=0이면 LLM이 이벤트를 무시한 것.
            #   LLM 판단은 존중하되(LLM 응답 유지), 시스템이 개입했음을 표시.
            if input_event_count > 0 and result.aggregate_view.event_count == 0:
                logger.warning(
                    "EI self-contradiction detected: symbol=%s "
                    "input_events=%d but output event_count=0 — "
                    "preserving LLM output, marking as degraded",
                    request_symbol,
                    input_event_count,
                )
                # LLM 원본 응답 유지 + degraded 플래그만 추가
                corrected_av = AggregateEventView(
                    overall_bias=result.aggregate_view.overall_bias,
                    event_conflict=result.aggregate_view.event_conflict,
                    top_reason_codes=result.aggregate_view.top_reason_codes,
                    opposing_evidence=result.aggregate_view.opposing_evidence,
                    evidence_strength=result.aggregate_view.evidence_strength,
                    event_count=result.aggregate_view.event_count,  # LLM 응답 유지 (0)
                    no_material_events=result.aggregate_view.no_material_events,  # LLM 응답 유지 (True)
                    interpretation_incomplete=True,
                    degraded_reason="self_contradiction_corrected",
                )
                result = EventInterpretationOutput(
                    schema_version=result.schema_version,
                    agent_name=result.agent_name,
                    decision_context_id=result.decision_context_id,
                    symbol=result.symbol,
                    issuer_code=result.issuer_code,
                    events=result.events,
                    aggregate_view=corrected_av,
                )

            # ★ deterministic 한국어 summary 생성 (LLM 호출 없음)
            object.__setattr__(result, "summary", _build_ei_summary(result, input_event_count=input_event_count))

            # ★ 진단 로깅: 정상 경로에서 event_count=0인 경우 분류
            if result.aggregate_view.event_count == 0:
                if input_event_count > 0:
                    # provider가 events를 반환했지만 event_count=0 (LLM 판단)
                    logger.warning(
                        "EI diagnostic: provider_zero — symbol=%s "
                        "input_events=%d output_events=%d "
                        "aggregate_view.event_count=0",
                        request_symbol,
                        input_event_count,
                        len(result.events),
                    )
                else:
                    # 입력 events도 0, 출력도 0 — 정상 케이스
                    logger.info(
                        "EI diagnostic: no_input_events — symbol=%s "
                        "input_events=0 output_events=0",
                        request_symbol,
                    )

            logger.info(
                "EventInterpretationAgent succeeded: "
                "symbol=%s input_events=%d output_events=%d "
                "aggregate_view.event_count=%s "
                "no_material_events=%s overall_bias=%s evidence_strength=%s",
                request_symbol,
                input_event_count,
                len(result.events),
                result.aggregate_view.event_count,
                result.aggregate_view.no_material_events,
                result.aggregate_view.overall_bias,
                result.aggregate_view.evidence_strength,
            )
            return result

        except Exception:
            logger.warning(
                "EventInterpretationAgent failed — returning fallback output. "
                "symbol=%s input_events=%d decision_context_id=%s",
                request_symbol,
                input_event_count,
                request.decision_context_id,
                exc_info=True,
            )
            # ★ fallback: LLM 응답을 받지 못했으므로 모든 필드를 fallback-safe 값으로 설정.
            #   event_count=0, no_material_events=True (LLM 판단 없음 → fallback-safe).
            #   interpretation_incomplete=True + degraded_reason 설정.
            degraded_reason = "provider_error"
            if input_event_count > 0:
                logger.warning(
                    "EI diagnostic: fallback_applied — symbol=%s "
                    "input_events=%d aggregate_view is degraded",
                    request_symbol,
                    input_event_count,
                )
                fallback_av = AggregateEventView(
                    overall_bias="neutral",
                    event_conflict=False,
                    top_reason_codes=(),
                    opposing_evidence=(),
                    evidence_strength="weak",
                    event_count=0,                    # LLM 응답 없음 → 0
                    no_material_events=True,          # LLM 판단 없음 → True (fallback-safe)
                    interpretation_incomplete=True,
                    degraded_reason=degraded_reason,
                )
                fallback = EventInterpretationOutput(
                    symbol=request_symbol,
                    aggregate_view=fallback_av,
                )
                object.__setattr__(fallback, "summary", _build_ei_summary(fallback, input_event_count=input_event_count))
                return fallback
            logger.warning(
                "EI diagnostic: unknown_zero — symbol=%s "
                "input_events=0 exception occurred (no fallback correction needed)",
                request_symbol,
            )
            fallback = EventInterpretationOutput(
                symbol=request_symbol,
                aggregate_view=AggregateEventView(
                    interpretation_incomplete=True,
                    degraded_reason=degraded_reason,
                ),
            )
            object.__setattr__(fallback, "summary", _build_ei_summary(fallback))
            return fallback

    def _build_system_prompt(self) -> str:
        """Build the system prompt describing the expected output schema."""
        schema_json = json.dumps(
            generate_json_schema(EventInterpretationOutput), indent=2
        )
        return (
            "You are an Event Interpretation Agent for a trading system. "
            "Analyze the following external events and produce a structured "
            "interpretation output.\n\n"
            "Output must be valid JSON matching this schema:\n"
            f"{schema_json}\n\n"
            "## Evidence Strength Classification\n"
            "Set evidence_strength based on the number and quality of events:\n"
            "- 'none': No material events found for this symbol.\n"
            "- 'weak': 1-2 events available, low or medium importance only.\n"
            "- 'moderate': 2+ events available, may include high importance.\n"
            "- 'strong': 3+ events, multiple high-importance, consistent direction.\n\n"
            "Set no_material_events=True if event_count == 0.\n"
            "Set event_count to the actual count of events provided.\n"
            "IMPORTANT: 'lack of evidence' is NOT the same as 'negative signal'. "
            "When there are no events, set overall_bias='neutral' and "
            "evidence_strength='none' — do NOT infer a negative bias from absence.\n\n"
            "## CRITICAL: Event count MUST match input\n"
            "The 'Recent events (N):' section in the user prompt shows the actual "
            "events available for this symbol. You MUST follow these rules:\n"
            "- If the user prompt shows 'Recent events (N):' with N > 0, "
            "you MUST set event_count=N and no_material_events=false.\n"
            "- Do NOT return event_count=0 or no_material_events=true when "
            "events are provided in the prompt. Events are provided because "
            "they are relevant to this symbol.\n"
            "- If you believe none of the events are material, still set "
            "event_count=N (the actual count) and no_material_events=false. "
            "Use evidence_strength='weak' to indicate low materiality, "
            "but do NOT set event_count=0.\n"
            "- event_count=0 is ONLY valid when the user prompt shows "
            "'Recent events (0):' — i.e., truly no events available.\n\n"
            "top_reason_codes: A tuple of the most important reason codes "
            "aggregated across all events. Extract the top 3-5 reason codes "
            "from the individual event reason_codes. When events exist and "
            "no_material_events is False, this MUST contain at least one "
            "reason code. When no_material_events is True, this MUST be empty.\n\n"
            "Language requirement: All human-readable narrative fields "
            "(summary, opposing_evidence) MUST be written in Korean. "
            "Machine-readable fields (reason_codes, event_type, impact_direction, "
            "source_name, etc.) MUST remain in English."
        )

    def _build_user_prompt(self, request: AgentExecutionRequest) -> str:
        """Build the user prompt with provenance-rich event context."""
        context = request.context
        score = context.score
        events = context.recent_events or []
        now = datetime.now(timezone.utc)

        logger.info(
            "EI _build_user_prompt: symbol=%s correlation_id=%s "
            "recent_events=%d",
            request.symbol,
            request.correlation_id,
            len(events),
        )

        lines: list[str] = [
            f"Correlation ID: {request.correlation_id}",
        ]
        if request.symbol:
            lines.append(f"Symbol: {request.symbol}")
        if request.market:
            lines.append(f"Market: {request.market}")

        if score:
            score_line = f"Score: {score.score} (threshold: {score.threshold})"
            lines.append(score_line)
            if score.reason_codes:
                lines.append(f"Reason codes: {', '.join(score.reason_codes)}")

        lines.append(f"Recent events ({len(events)}):")
        for e in events[:20]:
            headline = e.headline or "(no headline)"
            summary = e.body_summary or ""

            # Provenance tags — only non-None/non-empty, non-default
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
            # Non-default severity only
            if e.severity and e.severity != "medium":
                parts.append(f"[severity:{e.severity}]")
            # Non-default direction only
            if e.direction and e.direction not in ("neutral", ""):
                parts.append(f"[{e.direction}]")

            # Stale check — based on ingested_at, not published_at
            stale_mark = ""
            if e.ingested_at and (now - e.ingested_at).total_seconds() > 86400:  # 24h
                stale_mark = " ⚠️STALE"

            tagged = " ".join(parts)
            body = f" — {summary[:200]}" if summary else ""
            lines.append(f"  {tagged}{stale_mark} {headline}{body}")

        return "\n".join(lines)
