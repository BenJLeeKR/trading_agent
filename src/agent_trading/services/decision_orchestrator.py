from __future__ import annotations

import asyncio
import logging
import os
import time as time_module
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from agent_trading.brokers.base import BrokerAdapter
from agent_trading.config.settings import resolve_policy_git_sha
from agent_trading.domain.entities import (
    AccountEntity,
    CashBalanceSnapshotEntity,
    ConfigVersionEntity,
    DecisionContextEntity,
    ExternalEventEntity,
    InstrumentEntity,
    PositionSnapshotEntity,
    RiskLimitSnapshotEntity,
    SignalFeatureSnapshotEntity,
    SymbolTradeStateEntity,
    TradeDecisionEntity,
)
from agent_trading.domain.enums import DecisionType, OrderSide
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.services.loss_cut_shadow import evaluate_loss_cut_shadow
from agent_trading.services.shadow_bots import (
    AR_SHADOW_RULE_SET_VERSION,
    EI_SHADOW_RULE_SET_VERSION,
    compute_shadow_event_bot,
    compute_shadow_risk_bot,
    risk_score_bucket,
)
from agent_trading.services.order_manager import OrderManager
from agent_trading.services.order_sync_service import OrderSyncService
from agent_trading.services.reverse_trade_hysteresis import (
    evaluate_symbol_state_sell_hysteresis,
    evaluate_symbol_state_buy_hysteresis,
)
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import AccountLookup
from agent_trading.services.ai_agents.base import (
    AgentExecutionRequest,
    ProviderAIAgent,
)
from agent_trading.services.ai_agents.event_interpretation import (
    StubEventInterpretationAgent,
)
from agent_trading.services.ai_agents.ai_risk import StubAIRiskAgent
from agent_trading.services.ai_agents.ai_compliance import StubAIComplianceAgent
from agent_trading.services.ai_agents.final_decision_composer import (
    StubFinalDecisionComposerAgent,
)
from agent_trading.services.ai_agents.recorder import AgentRunRecorder
from agent_trading.services.ai_agents.schemas import (
    AIRiskOutput,
    EventInterpretationOutput,
    FinalDecisionComposerOutput,
)
from agent_trading.services.common_types import (
    AgentExecutionBundle,
    AIDecisionInputs,
    AIPolicyContextView,
    AssembledContext,
    OrderIntent,
    PhaseTraceEntry,
    ScoreCalculator,
    ScoreResult as ScoreResult,
    StubScoreCalculator,
    SubmitResult,
    dataclass_to_dict,
    event_sort_key,
)
from agent_trading.services.decision_factory import (
    build_trade_decision_entity,
    DecisionContextService,
)
from agent_trading.services.deterministic_trigger_engine import (
    assess_deterministic_triggers,
)
from agent_trading.services.execution_service import (
    ExecutionService,
)
from agent_trading.services.compliance_validator import (
    ComplianceValidationInput,
    evaluate_compliance_rules,
)
from agent_trading.services.instrument_profile import (
    derive_primary_index_membership,
    normalize_index_memberships,
)
from agent_trading.services.holding_profile_policy import (
    derive_holding_profile_policy,
    parse_datetime_or_none,
    serialize_holding_profile_policy,
)
from agent_trading.services.expected_value_gate import (
    evaluate_expected_value_gate,
)
from agent_trading.services.market_regime import classify_market_regime
from agent_trading.services.portfolio_allocation import assess_portfolio_allocation
from agent_trading.services.source_policy import evaluate_action_envelope
from agent_trading.services.sizing_engine import (
    SizingInputs,
)
from agent_trading.services.strategy_selection import select_strategy
from agent_trading.services.translation import (
    build_submit_order_request_from_decision as build_submit_order_request_from_decision,
    calculate_max_order_value,
)
from agent_trading.services.decision_agent_runner import (
    DecisionAgentRunner,
    _should_skip_final_decision_composer,
)
from agent_trading.services.validators import ValidationContext, ValidationResult

logger = logging.getLogger(__name__)

_PRE_AI_SHORT_CIRCUIT_SOURCE_TYPES = frozenset({"core"})
_PRE_AI_ELIGIBILITY_BLOCK_REASONS = frozenset(
    {
        "eligibility_low_average_volume",
        "eligibility_low_turnover",
        "eligibility_allocation_blocked",
        "eligibility_risk_off_block",
        "eligibility_core_risk_off_guard_blocked",
        "eligibility_core_risk_off_ranking_blocked",
        "eligibility_core_risk_off_signal_blocked",
        "eligibility_core_risk_off_activity_blocked",
        "eligibility_core_risk_off_strategy_blocked",
        "eligibility_participation_rate_blocked",
    }
)
_AI_OVERRIDE_EXECUTION_INFEASIBLE_REASONS = frozenset(
    {
        "eligibility_low_average_volume",
        "eligibility_low_turnover",
        "eligibility_participation_rate_blocked",
    }
)
# held_position FDC skip shadow 관측 대상 — deterministic_trigger가 이미
# "행동 불필요"(NO_ACTION) 또는 "지켜보기"(WATCH)로 판정한 구간만 본다.
# REDUCE_CANDIDATE/SELL_CANDIDATE는 실측상 FDC가 실제로 HOLD로 되돌리는
# 비율이 낮지 않아(2026-08-19 실측 9.1%) 대상에서 제외한다.
_HELD_POSITION_FDC_SKIP_SHADOW_PRIMARY_CANDIDATES = frozenset({"NO_ACTION", "WATCH"})
HELD_POSITION_FDC_SKIP_SHADOW_RULE_SET_VERSION = "held_position_fdc_skip_shadow_v1"

# held_position REDUCE skip shadow 관측 대상(2026-08-20) — 위 NO_ACTION/
# WATCH 관측과는 별도 key로 분리한다. REDUCE_CANDIDATE/SELL_CANDIDATE
# 전체는 FDC가 실제로 HOLD로 되돌리는 비율이 12%/5.9%(2026-08-20 실측)로
# 낮지 않아 관측 대상에 넣지 않는다 — 그 안에서도 `ar_output.risk_opinion
# in ("reject","reduce")`인 하위 구간만 본다. 이 조건은
# `_check_held_position_sell_override()`의 무조건 발동 분기(FDC 출력과
# 무관하게 개입)와 정확히 겹치고, 같은 날 실측상 이 하위 구간(72건)에서
# FDC가 HOLD로 되돌린 사례가 0건이었다 — 다만 EXIT/REDUCE 세부 선택까지
# override와 FDC가 일치하는지는 아직 검증되지 않아, NO_ACTION/WATCH보다
# 더 보수적으로(별도 key + 실행 의미 필드까지) 관측한다.
_HELD_POSITION_REDUCE_SKIP_SHADOW_PRIMARY_CANDIDATES = frozenset(
    {"REDUCE_CANDIDATE", "SELL_CANDIDATE"}
)
_HELD_POSITION_REDUCE_SKIP_SHADOW_RISK_OPINIONS = frozenset({"reject", "reduce"})
HELD_POSITION_REDUCE_SKIP_SHADOW_RULE_SET_VERSION = "held_position_reduce_skip_shadow_v1"


def _held_position_action_class(decision_type: str) -> str:
    """decision_type을 "실행 의미" 기준으로 뭉뚱그린다.

    REDUCE/EXIT는 둘 다 실제 매도 주문으로 이어질 수 있는 actionable
    분류이고, HOLD/WATCH는 둘 다 non-actionable이다(``translation.py``
    의 ``actionable_types``와 일치). shadow와 실제 결과가 REDUCE vs
    EXIT처럼 세부 라벨은 달라도 "매도를 시도했는가"라는 실행 의미가
    같은지를 별도로 보기 위한 헬퍼다.
    """
    return "SELL_ACTIONABLE" if decision_type in {"REDUCE", "EXIT"} else "NON_ACTIONABLE"

# Per-agent timeout: each LLM call is capped at 30s so that a single
# hanging agent cannot stall the entire decision cycle beyond 90s.
# Reduced from 35s to 30s in Phase 5.7 to align with deepseek-chat
# P99 latency (~15.9s) with 1.9x safety margin.
_PER_AGENT_TIMEOUT = 30  # seconds per agent

# Phase 4: subprocess isolation for agent calls.
# When True, _run_agents() delegates to _run_agents_in_subprocess()
# which runs all 3 agents in a separate subprocess with SIGKILL-guaranteed
# timeout.  Set to False in tests for compatibility.
# Can be overridden via the AGENT_SUBPROCESS_ISOLATION env var.
_USE_SUBPROCESS_ISOLATION: bool = (
    os.environ.get("AGENT_SUBPROCESS_ISOLATION", "1") == "1"
)

# EV gate near-miss 조건부 완화(SPPV-2.87/2.88) — 근소부족 허용 폭(bps).
# 전역 minimum_required_edge_bps 자체는 절대 바꾸지 않는다.
_EV_GATE_NEAR_MISS_THRESHOLD_BPS = Decimal("2.0")


def resolve_ev_gate_near_miss_override(
    *,
    enabled: bool,
    decision_type: str,
    expected_value_gate_passed: bool,
    source_type: str,
    minimum_required_edge_bps: Decimal | None,
    edge_after_cost_bps: Decimal | None,
    deterministic_trigger_reason_codes: tuple[str, ...],
) -> tuple[bool, Decimal | None, Decimal | None]:
    """EV gate near-miss 조건부 완화 적용 여부를 순수하게 판정한다.

    5개 조건(모두 AND)을 만족할 때만 ``(True, deficit_bps, threshold_bps)``
    를 반환한다. 전역 threshold나 EV 계산 로직은 건드리지 않으며, 이
    함수는 판정만 하고 부작용(mutation/로깅)은 호출부에서 처리한다.
    기본값 ``enabled=False``이면 항상 ``(False, None, None)``.
    """
    if not enabled:
        return False, None, None
    if (decision_type or "").strip().upper() not in {"APPROVE", "BUY"}:
        return False, None, None
    if expected_value_gate_passed is not False:
        return False, None, None
    if source_type != "core":
        return False, None, None
    if minimum_required_edge_bps is None or edge_after_cost_bps is None:
        return False, None, None
    if "trigger_r3b_alpha_percentile" not in deterministic_trigger_reason_codes:
        return False, None, None
    deficit_bps = minimum_required_edge_bps - edge_after_cost_bps
    if deficit_bps > _EV_GATE_NEAR_MISS_THRESHOLD_BPS:
        return False, None, None
    return True, deficit_bps, _EV_GATE_NEAR_MISS_THRESHOLD_BPS


@dataclass(slots=True, frozen=True)
class DeterministicDerivationBundle:
    """assemble()의 deterministic 파생 계산 결과 묶음."""

    source_type: str
    signal_feature_snapshot: SignalFeatureSnapshotEntity | None = None
    market_regime: Any | None = None
    strategy_selection: Any | None = None
    portfolio_allocation: Any | None = None
    deterministic_trigger: Any | None = None


@dataclass(slots=True, frozen=True)
class FdcReadyShadowEvent:
    """FDC cycle-scoped batch queue lifecycle shadow(Phase 1, 2026-08-25
    2차 보정) — ``assemble()``이 노출하는 **DB에 쓰지 않는** FDC-ready
    관측값.

    2차 보정 이전에는 ``assemble()``이 이 시점에 바로 shadow 큐에 DB
    등록(``FdcQuotaCoordinator.register_shadow_job_and_judge()``)까지
    했으나, 그러면 ``enqueue_sequence``가 "실제 FDC-ready 순서"가 아니라
    "``assemble()`` 도착 순서"(=기존 limiter 대기·provider 응답·subprocess
    종료 순서에 좌우됨)를 반영하게 되는 구조적 결함이 있었다. 이제
    ``assemble()``은 이 이벤트만 만들어 ``pending_fdc_ready_shadow_event``
    로 노출하고, 실제 DB 등록은 호출자(``run_decision_loop.py``)가 사이클의
    모든 심볼 처리(``asyncio.gather``)가 끝난 뒤 이 이벤트들을
    ``(fdc_ready_at, cycle_index)`` 기준으로 정렬해 순차 재생할 때 비로소
    일어난다 — 상세: docs/40_action_plans/fdc_cycle_scoped_batch_queue_
    gemini_shared_13rpm_quota_design_2026-08-25.md §11(2차 보정).
    """

    decision_cycle_id: str | None
    decision_context_id: UUID | None
    symbol: str
    source_type: str
    fdc_ready_at: datetime


class DecisionOrchestratorService:
    """Deterministic stub for order intent assembly.

    Scope (Milestone 6)
    -------------------
    * Assemble P1 fields (``decision_context_id``, ``order_intent_id``)
      into the ``SubmitOrderRequest`` before it reaches the
      ``OrderManager``.
    * No LLM calls, no AI judgment, no portfolio calculations.

    Milestone 7 additions
    ---------------------
    * Active context resolution from ``DecisionContextRepository``.
    * ID generation for ``decision_id`` and ``correlation_id`` when not
      provided.
    * Minimal assembly of ``SubmitOrderRequest`` from context + intent.

    Priority 3 additions
    --------------------
    * ``AssembledContext`` dataclass — aggregates decision context,
      config version, recent external events, and score.
    * ``OrderIntent`` extended with ``context``, ``config_version_id``,
      ``reason_codes``.
    * Config version lookup via ``decision_context.config_version_id``.
    * External event query stub (``list_by_symbol``).
    * ``ScoreCalculator`` protocol + ``StubScoreCalculator``.
    * No actual LLM calls, no event-driven judgment.

    Priority 4 additions
    --------------------
    * Three v1 Provider AI Agent stubs (Event Interpretation, AI Risk,
      Final Decision Composer) wired into the ``assemble()`` flow.
    * ``AgentRunRecorder`` — in-memory stub that records each agent run.
    * ``_run_agents()`` — private method that executes the three agents
      sequentially and records their outputs.
    * No actual Provider API calls — all agents return default structured
      outputs (safe fallback on exception).

    Priority A additions (AI Decision Backend Contract)
    ---------------------------------------------------
    * ``AIDecisionInputs`` dataclass — normalised aggregate of EI/AR/FDC
      agent outputs, carried on ``OrderIntent.ai_backend_inputs``.
    * ``_run_agents()`` now returns ``AIDecisionInputs`` (not ``None``).
    * ``assemble()`` passes the normalised contract to ``OrderIntent``.
    * ``AgentRunRecorder`` continues to record every run for audit/replay.
    * Raw agent outputs are **not** carried on ``OrderIntent`` — only
      normalised fields via ``AIDecisionInputs``.
    """

    def __init__(
        self,
        repos: RepositoryContainer,
        *,
        stale_threshold_seconds: int = 900,
        score_calculator: ScoreCalculator | None = None,
        event_interpretation_agent: ProviderAIAgent | None = None,
        ai_risk_agent: ProviderAIAgent | None = None,
        ai_compliance_agent: ProviderAIAgent | None = None,
        final_decision_agent: ProviderAIAgent | None = None,
        agent_recorder: AgentRunRecorder | None = None,
        # --- Phase 5.5: post-submit sync ---
        sync_service: OrderSyncService | None = None,
        snapshot_refresh_cb: Callable[[UUID], Awaitable[None]] | None = None,
        # --- Phase 4: subprocess isolation ---
        use_subprocess_isolation: bool | None = None,
        # --- Provider configuration for subprocess agent creation ---
        llm_provider: str = "",
        provider_api_key: str = "",
        provider_base_url: str = "",
        provider_model_id: str = "",
        provider_timeout_seconds: int = 60,
        # --- `§21 게이트`(regime_switch_v1) config 기반 gate (SPPV-2.60) ---
        regime_switch_v1_trigger_status: str | None = None,
        regime_switch_v1_gate_override_enabled: bool = False,
        # --- entry_score R3b alpha 교체 config 기반 스위치 (SPPV-2.67) ---
        r3b_alpha_enabled: bool = False,
        # --- EV gate near-miss 조건부 완화 config 기반 스위치 (SPPV-2.87/2.88) ---
        ev_gate_near_miss_override_enabled: bool = False,
        # --- 손실률 기반 Loss-cut shadow 관측 (관측 전용, 결정 미개입) ---
        loss_cut_shadow_enabled: bool = False,
        loss_cut_shadow_soft_threshold_pct: Decimal = Decimal("7"),
        loss_cut_shadow_hard_threshold_pct: Decimal = Decimal("12"),
        # --- AR(ai_risk)/EI(event_interpretation) shadow bot 관측 (관측 전용, 결정 미개입) ---
        ar_shadow_bot_enabled: bool = False,
        ei_shadow_bot_enabled: bool = False,
        # --- held_position FDC 호출 shadow-skip 관측 (관측 전용, 결정 미개입) ---
        held_position_fdc_skip_shadow_enabled: bool = False,
        # --- held_position REDUCE/SELL_CANDIDATE shadow-skip 관측 (관측 전용, 결정 미개입) ---
        held_position_reduce_skip_shadow_enabled: bool = False,
        # --- FDC cycle-scoped batch queue lifecycle shadow (Phase 1, 관측 전용, 결정 미개입) ---
        fdc_batch_queue_lifecycle_shadow_enabled: bool = False,
    ) -> None:
        self._repos = repos
        self._decision_context_service = DecisionContextService(repos)
        self._stale_threshold_seconds = stale_threshold_seconds
        self._score_calculator = score_calculator or StubScoreCalculator()
        self._event_interpretation_agent = (
            event_interpretation_agent or StubEventInterpretationAgent()
        )
        self._ai_risk_agent = ai_risk_agent or StubAIRiskAgent()
        self._ai_compliance_agent = ai_compliance_agent or StubAIComplianceAgent()
        self._final_decision_agent = final_decision_agent or StubFinalDecisionComposerAgent()
        self._agent_recorder = agent_recorder or AgentRunRecorder(repo=self._repos.agent_runs)
        # --- Phase 5.5 ---
        self._sync_service = sync_service
        self._snapshot_refresh_cb = snapshot_refresh_cb
        # --- Phase 4: subprocess isolation ---
        # Default to module-level constant; tests can override via constructor.
        self._use_subprocess_isolation = (
            _USE_SUBPROCESS_ISOLATION if use_subprocess_isolation is None
            else use_subprocess_isolation
        )
        # --- Provider configuration for subprocess ---
        self._llm_provider = llm_provider
        self._provider_api_key = provider_api_key
        self._provider_base_url = provider_base_url
        self._provider_model_id = provider_model_id
        self._provider_timeout_seconds = provider_timeout_seconds
        # --- `§21 게이트`(regime_switch_v1) config 기반 gate (SPPV-2.60) ---
        # 둘 다 기본값이면 assess_deterministic_triggers()의 게이트 체크가
        # 완전히 비활성화되어 기존 동작과 100% 동일하다(하위 호환).
        # paper/real/production 같은 environment 값은 여기서도 참조하지
        # 않는다 — 오직 호출자가 넘긴 config 값만 그대로 보존한다.
        self._regime_switch_v1_trigger_status = regime_switch_v1_trigger_status
        self._regime_switch_v1_gate_override_enabled = (
            regime_switch_v1_gate_override_enabled
        )
        # --- entry_score R3b alpha 교체 config 기반 스위치 (SPPV-2.67) ---
        # `r3b_alpha_percentile` 자체는 종목별 값이라 요청
        # metadata(`request.metadata["r3b_alpha_percentile"]`)로 개별
        # 전달되고(§_extract_r3b_alpha_percentile), 이 스위치는
        # `AppSettings.entry_score_r3b_alpha_enabled`(기본값 False)를
        # 그대로 보존하는 mode-agnostic config다. 기본값이면 percentile이
        # 전달돼도 무시되어(§_build_entry_score의 and 조건) 기존 동작이
        # 100% 그대로 유지된다.
        self._r3b_alpha_enabled = r3b_alpha_enabled
        # --- EV gate near-miss 조건부 완화 (SPPV-2.87/2.88) ---
        # 기본값 False — 전역 threshold/EV 계산 로직은 그대로 두고,
        # 아래 5개 조건을 모두 만족하는 매우 좁은 경우에만 예외 통과를
        # 적용한다(§_check_ai_buy_override_gate 이후 적용 지점 참고).
        self._ev_gate_near_miss_override_enabled = ev_gate_near_miss_override_enabled
        # --- 손실률 기반 Loss-cut shadow 관측 (관측 전용, 결정 미개입) ---
        # 기본값 False — 이 스위치가 True여도 아래 _record_loss_cut_
        # shadow_observation()은 guard 목록(§_check_*)에 전혀 포함되지
        # 않고, 그 목록이 전부 끝난 뒤(§assemble() 최말단)에만 호출된다.
        # decision_type/side/주문 제출을 절대 바꾸지 않는다(설계 문서
        # §3.6, §4.3).
        self._loss_cut_shadow_enabled = loss_cut_shadow_enabled
        self._loss_cut_shadow_soft_threshold_pct = loss_cut_shadow_soft_threshold_pct
        self._loss_cut_shadow_hard_threshold_pct = loss_cut_shadow_hard_threshold_pct
        # AR/EI shadow bot 관측도 loss_cut_shadow와 동일한 원칙을 따른다:
        # 결정 mutating guard 목록에 속하지 않고, assemble() 최말단에서
        # 관측 전용으로만 호출되며 decision_type/side/주문 제출을 절대
        # 바꾸지 않는다.
        self._ar_shadow_bot_enabled = ar_shadow_bot_enabled
        self._ei_shadow_bot_enabled = ei_shadow_bot_enabled
        # held_position FDC skip shadow 관측도 동일한 원칙을 따른다: 결정
        # mutating guard 목록에 속하지 않고, assemble() 최말단에서 관측
        # 전용으로만 호출되며 FDC 호출 여부/decision_type/side/주문
        # 제출을 절대 바꾸지 않는다.
        self._held_position_fdc_skip_shadow_enabled = (
            held_position_fdc_skip_shadow_enabled
        )
        # held_position REDUCE/SELL_CANDIDATE shadow 관측도 동일한 원칙을
        # 따른다 — 별도 key(shadow_held_position_reduce_skip)에만 기록하고
        # FDC 호출 여부/decision_type/side/주문 제출을 절대 바꾸지 않는다.
        self._held_position_reduce_skip_shadow_enabled = (
            held_position_reduce_skip_shadow_enabled
        )
        # FDC cycle-scoped batch queue lifecycle shadow(Phase 1, 2026-08-25
        # 2차 보정) — 동일한 관측 전용 원칙. FDC-ready(fdc_skipped=False)로
        # 확정된 건에 한해 "같은 cycle 내 앞선 shadow FDC-ready job까지
        # 포함한 FIFO 가상 큐에서 지금 승인 가능한가"를 관측하고, 실제 FDC
        # 호출 여부/decision_type/side/주문 제출을 절대 바꾸지 않는다.
        # 2차 보정: 이 orchestrator는 더 이상 DB에 직접 쓰지 않는다 —
        # ``assemble()``은 ``pending_fdc_ready_shadow_event``만 노출하고,
        # 실제 shadow 큐 DB 등록은 호출자(``run_decision_loop.py``)가
        # 사이클 종료 후 정렬·재생한다(``FdcReadyShadowEvent`` 참고).
        self._fdc_batch_queue_lifecycle_shadow_enabled = (
            fdc_batch_queue_lifecycle_shadow_enabled
        )
        self.pending_fdc_ready_shadow_event: FdcReadyShadowEvent | None = None
        # --- Execution Service (execution pipeline state: sell guard, quote CB, fresh check) ---
        self._execution_service = ExecutionService(
            repos=repos,
            stale_threshold_seconds=stale_threshold_seconds,
            sync_service=sync_service,
            snapshot_refresh_cb=snapshot_refresh_cb,
        )

        # Initialize DecisionAgentRunner (Phase 5 refactoring)
        self._agent_runner = DecisionAgentRunner(
            repos=self._repos,
            event_interpretation_agent=self._event_interpretation_agent,
            ai_risk_agent=self._ai_risk_agent,
            ai_compliance_agent=self._ai_compliance_agent,
            final_decision_composer_agent=self._final_decision_agent,
            agent_run_recorder=self._agent_recorder,
            score_calculator=self._score_calculator,
            subprocess_timeout=90,
            llm_provider=self._llm_provider,
            provider_api_key=self._provider_api_key,
            provider_base_url=self._provider_base_url,
            provider_model_id=self._provider_model_id,
            provider_timeout_seconds=self._provider_timeout_seconds,
        )

    def _check_held_position_sell_override(
        self,
        source_type: str,
        ar_output: AIRiskOutput | None,
        fdc_output: FinalDecisionComposerOutput | None,
    ) -> tuple[str, str, str] | None:
        """보유 포지션 + 강한 리스크 신호 → REDUCE/EXIT sell override 판단.

        Args:
            source_type: 출처 타입 (``"held_position"`` 등)
            ar_output: AI Risk agent 출력
            fdc_output: FDC agent 출력

        Returns:
            ``(decision_type, side, rationale)`` 튜플 (override 필요 시),
            ``None`` (override 불필요 시)
        """
        # held position이 아니면 override 절대 안 함
        if source_type != "held_position":
            return None

        if ar_output is None or fdc_output is None:
            return None

        # FDC가 이미 REDUCE/EXIT로 판단했으면 override 불필요
        if fdc_output.decision_type in ("REDUCE", "EXIT"):
            return None

        # AI risk가 강한 부정 신호인지 확인
        risk_override = False
        override_reason = ""

        if ar_output.risk_opinion in ("reject", "reduce"):
            risk_override = True
            override_reason = f"리스크 경고({ar_output.risk_opinion})"
        elif ar_output.risk_opinion == "review" and ar_output.risk_score >= 0.8:
            risk_override = True
            override_reason = f"리스크 검토 필요(score:{ar_output.risk_score:.1f})"
        elif ar_output.risk_score >= 0.8:
            risk_override = True
            override_reason = f"리스크 점수高危({ar_output.risk_score:.1f})"

        if not risk_override:
            return None

        # FDC가 HOLD인데 risk 신호가 강하면 → REDUCE로 전환
        # FDC가 APPROVE/BUY여도 held position + risk 신호면 → REDUCE
        rationale = (
            f"[held_position_override] 보유 포지션 {override_reason}. "
            f"FDC={fdc_output.decision_type}→REDUCE 전환. "
            f"AR opinion={ar_output.risk_opinion} score={ar_output.risk_score:.2f}"
        )

        # 과집중(risk_flags에 concentration 관련)이면 EXIT 고려
        risk_flags_lower = tuple(f.lower() for f in ar_output.risk_flags)
        if any("concent" in f or "expos" in f or "over" in f for f in risk_flags_lower):
            return ("EXIT", "SELL", rationale)

        return ("REDUCE", "SELL", rationale)

    def _apply_held_position_sell_override(
        self,
        *,
        agent_bundle: AgentExecutionBundle,
        assembled_context: AssembledContext,
        derivation: Any,
        symbol: str,
    ) -> None:
        """``_check_held_position_sell_override()`` 판정을 실제로 적용한다.

        ``decision_type``/``side``/``composer_output.summary``를 override하는
        기존 동작에 더해, override로 바뀐 ``decision_type`` 기준으로
        ``evaluate_expected_value_gate()``를 재호출해 EV 게이트 8개 필드를
        다시 채운다(2026-08-19).

        배경: ``decision_agent_runner.py``에서 EV 게이트는 override *이전*
        (FDC 원본 ``decision_type``, 대개 ``HOLD``) 시점에 딱 한 번만
        계산된다. ``evaluate_expected_value_gate()``는 ``decision_type``이
        non-actionable(HOLD/WATCH)이면 8개 bps 필드를 전부 ``None``으로
        두고 ``reason_codes=("expected_value_not_required_non_actionable",)``
        로 트리비얼 통과시킨다(``expected_value_gate.py`` 참고). override가
        ``decision_type``을 EXIT/REDUCE(actionable)로 바꿔도 이 값은 그대로
        남아있어, ``translation.py::_has_required_expected_value_anchor()``가
        8개 필드 전부 non-None을 요구하는 SELL/EXIT/REDUCE 경로에서 항상
        ``False``를 반환하고 ``build_submit_order_request_from_decision()``이
        주문을 만들지 못한다 — EV 게이트가 SELL을 막으려는 정책적 판단이
        아니라, 평가가 override *이전* 시점에 멈춰 있는 정합성 문제다.

        이 메서드는 새 계산식을 만들지 않고 기존 ``evaluate_expected_value_
        gate()``를 override된 ``decision_type``으로 다시 호출할 뿐이다 —
        threshold(SELL/EXIT/REDUCE 5bps 등)와 계산 로직은 전혀 건드리지
        않으며, 기존에 FDC가 직접 REDUCE/EXIT를 판단했을 때와 완전히
        동일한 잣대가 적용된다. SELL/EXIT/REDUCE(``is_entry=False``)는
        ``_resolve_score_anchor()``가 ``deterministic_trigger.exit_score``를
        우선 사용하므로, FDC가 429 fallback으로 confidence=0/conviction=0인
        상태여도 유효하게 재계산된다.
        """
        override = self._check_held_position_sell_override(
            source_type=derivation.source_type,
            ar_output=agent_bundle.risk_output,
            fdc_output=agent_bundle.composer_output,
        )
        if override is None:
            return

        override_dt, override_side, override_rationale = override
        # frozen dataclass 수정을 위해 object.__setattr__ 사용
        object.__setattr__(agent_bundle.ai_inputs, "decision_type", override_dt)
        object.__setattr__(agent_bundle.ai_inputs, "side", override_side)

        recomputed_ev = evaluate_expected_value_gate(
            decision_type=override_dt,
            confidence=agent_bundle.ai_inputs.confidence,
            conviction=agent_bundle.ai_inputs.conviction,
            risk_score=agent_bundle.ai_inputs.risk_score,
            context=assembled_context,
        )
        object.__setattr__(
            agent_bundle.ai_inputs,
            "expected_return_bps", recomputed_ev.expected_return_bps,
        )
        object.__setattr__(
            agent_bundle.ai_inputs,
            "expected_downside_bps", recomputed_ev.expected_downside_bps,
        )
        object.__setattr__(
            agent_bundle.ai_inputs,
            "net_expected_value_bps", recomputed_ev.net_expected_value_bps,
        )
        object.__setattr__(
            agent_bundle.ai_inputs,
            "final_trade_score", recomputed_ev.final_trade_score,
        )
        object.__setattr__(
            agent_bundle.ai_inputs,
            "minimum_required_edge_bps", recomputed_ev.minimum_required_edge_bps,
        )
        object.__setattr__(
            agent_bundle.ai_inputs,
            "edge_after_cost_bps", recomputed_ev.edge_after_cost_bps,
        )
        object.__setattr__(
            agent_bundle.ai_inputs,
            "estimated_round_trip_cost_bps",
            recomputed_ev.estimated_round_trip_cost_bps,
        )
        object.__setattr__(
            agent_bundle.ai_inputs,
            "slippage_buffer_bps", recomputed_ev.slippage_buffer_bps,
        )
        object.__setattr__(
            agent_bundle.ai_inputs,
            "expected_value_gate_passed", recomputed_ev.expected_value_gate_passed,
        )
        object.__setattr__(
            agent_bundle.ai_inputs,
            "expected_value_gate_reason_codes", recomputed_ev.reason_codes,
        )
        logger.info(
            "Held position sell override EV gate 재계산: symbol=%s "
            "decision_type=%s edge_after_cost_bps=%s "
            "expected_value_gate_passed=%s reason_codes=%s",
            symbol, override_dt,
            recomputed_ev.edge_after_cost_bps,
            recomputed_ev.expected_value_gate_passed,
            recomputed_ev.reason_codes,
        )

        # ★ composer_output도 함께 override
        # _ensure_trade_decision()에서 composer_output.decision_type/side를
        # trade_decisions에 저장하므로, override 값을 반영해야 함
        if agent_bundle.composer_output is not None:
            object.__setattr__(
                agent_bundle.composer_output, "decision_type", override_dt,
            )
            object.__setattr__(
                agent_bundle.composer_output, "side", override_side,
            )
            fdc_summary = agent_bundle.composer_output.summary
            object.__setattr__(
                agent_bundle.composer_output, "summary",
                (fdc_summary + f" | {override_rationale}") if fdc_summary else override_rationale,
            )
        logger.info(
            "Held position sell override: symbol=%s source_type=%s "
            "decision_type=%s side=%s rationale=%s",
            symbol, derivation.source_type, override_dt, override_side,
            override_rationale,
        )

    def _check_watch_candidate_upgrade_guard(
        self,
        *,
        source_type: str,
        deterministic_trigger: Any | None,
        fdc_output: FinalDecisionComposerOutput | None,
        position_snapshot: PositionSnapshotEntity | None = None,
    ) -> tuple[str, str] | None:
        """결정적 WATCH 후보가 AI 단계에서 진입/매도로 승격되는 것을 제한한다."""
        if deterministic_trigger is None or fdc_output is None:
            return None

        guarded_source_types = {"core", "held_position"}
        if source_type not in guarded_source_types:
            return None

        if source_type == "core":
            has_position = (
                position_snapshot is not None
                and position_snapshot.quantity is not None
                and position_snapshot.quantity > 0
            )
            if has_position:
                return None

        primary_candidate = (
            getattr(deterministic_trigger, "primary_candidate", "") or ""
        ).strip().upper()
        if primary_candidate != "WATCH":
            return None

        decision_type = (fdc_output.decision_type or "").strip().upper()
        if decision_type not in {"APPROVE", "BUY", "SELL", "EXIT", "REDUCE"}:
            return None

        if source_type == "held_position":
            decision_side = (fdc_output.side or "").strip().upper()
            if decision_type in {"REDUCE", "EXIT"} and decision_side == "SELL":
                return None

        rationale = (
            f"[watch_candidate_guard] source_type={source_type} "
            f"deterministic_trigger=WATCH 이므로 FDC={decision_type}를 WATCH로 제한"
        )
        return ("WATCH", rationale)

    def _check_buy_eligibility_upgrade_guard(
        self,
        *,
        source_type: str,
        deterministic_trigger: Any | None,
        fdc_output: FinalDecisionComposerOutput | None,
        position_snapshot: PositionSnapshotEntity | None = None,
    ) -> tuple[str, str] | None:
        """BUY 적격성 실패 상태에서 AI의 진입 승격을 제한한다."""
        if deterministic_trigger is None or fdc_output is None:
            return None

        if source_type != "core":
            return None

        has_position = (
            position_snapshot is not None
            and position_snapshot.quantity is not None
            and position_snapshot.quantity > 0
        )
        if has_position:
            return None

        if bool(getattr(deterministic_trigger, "eligibility_passed", False)):
            return None

        decision_type = (fdc_output.decision_type or "").strip().upper()
        if decision_type not in {"APPROVE", "BUY"}:
            return None

        eligibility_reasons = tuple(
            getattr(deterministic_trigger, "eligibility_reasons", ()) or ()
        )
        has_execution_feasibility_block = any(
            reason in {
                "eligibility_low_average_volume",
                "eligibility_low_turnover",
                "eligibility_participation_rate_blocked",
            }
            for reason in eligibility_reasons
        )
        if not has_execution_feasibility_block:
            return None

        downgrade_decision = (
            "WATCH"
            if (getattr(deterministic_trigger, "watch_candidate", False))
            else "HOLD"
        )
        rationale = (
            f"[buy_eligibility_guard] source_type={source_type} "
            f"eligibility_reasons={','.join(eligibility_reasons)} "
            f"이므로 FDC={decision_type} 진입 승격을 {downgrade_decision}로 제한"
        )
        return (downgrade_decision, rationale)

    def _check_source_policy_upgrade_guard(
        self,
        *,
        source_type: str,
        deterministic_trigger: Any | None,
        fdc_output: FinalDecisionComposerOutput | None,
        position_snapshot: PositionSnapshotEntity | None = None,
    ) -> tuple[str, str, tuple[str, ...]] | None:
        """source_type 정책상 금지된 신규 BUY 승격을 제한한다."""
        if fdc_output is None:
            return None

        has_position = (
            position_snapshot is not None
            and position_snapshot.quantity is not None
            and position_snapshot.quantity > 0
        )
        envelope = evaluate_action_envelope(
            source_type=source_type,
            has_position=has_position,
        )
        if envelope.allow_new_buy:
            return None

        decision_type = (fdc_output.decision_type or "").strip().upper()
        if decision_type not in {"APPROVE", "BUY"}:
            return None

        downgrade_decision = "HOLD"
        if (
            deterministic_trigger is not None
            and bool(getattr(deterministic_trigger, "watch_candidate", False))
        ):
            downgrade_decision = "WATCH"

        rationale = (
            f"[source_policy_guard] source_type={source_type} "
            f"reason_codes={','.join(envelope.reason_codes)} "
            f"이므로 FDC={decision_type} 진입 승격을 {downgrade_decision}로 제한"
        )
        return (
            downgrade_decision,
            rationale,
            ("source_policy_guard",) + envelope.reason_codes,
        )

    async def _check_ai_buy_override_gate(
        self,
        *,
        source_type: str,
        deterministic_trigger: Any | None,
        fdc_output: FinalDecisionComposerOutput | None,
        ai_inputs: AIDecisionInputs,
        position_snapshot: PositionSnapshotEntity | None,
        decision_context: DecisionContextEntity | None,
        instrument: InstrumentEntity | None,
    ) -> tuple[str, str, tuple[str, ...]] | None:
        """BUY/APPROVE override는 eligibility + EV + state 통과 시에만 허용한다."""
        if fdc_output is None or deterministic_trigger is None:
            return None

        decision_type = (fdc_output.decision_type or "").strip().upper()
        if decision_type not in {"APPROVE", "BUY"}:
            return None

        has_position = (
            position_snapshot is not None
            and position_snapshot.quantity is not None
            and position_snapshot.quantity > 0
        )
        if has_position:
            return None

        if bool(getattr(deterministic_trigger, "buy_candidate", False)):
            return None

        downgrade_decision = (
            "WATCH"
            if bool(getattr(deterministic_trigger, "watch_candidate", False))
            else "HOLD"
        )
        normalized_source_type = (source_type or "core").strip().lower()
        # R5-f 확인(2026-08-04): 이 함수는 호출자(assemble())에서 항상
        # _check_source_policy_upgrade_guard()가 먼저 실행된 뒤에만
        # 호출된다. 그 가드가 evaluate_action_envelope(source_type,
        # has_position)로 allow_new_buy=False를 확인하면 decision_type을
        # 이미 HOLD/WATCH로 낮추고, 이 함수는 바로 위 decision_type 체크
        # (APPROVE/BUY 아니면 return None)에서 먼저 빠진다. source_type/
        # has_position은 두 호출 사이에 바뀌지 않고(같은 position_
        # snapshot/derivation.source_type을 그대로 재사용), evaluate_
        # action_envelope()는 이 두 값에만 의존하는 순수 함수라, 이
        # 지점에 decision_type이 APPROVE/BUY로 남아 있다는 것 자체가
        # 이미 그 가드의 동일한 envelope 평가가 allow_new_buy=True였음을
        # 뜻한다 — 여기서 다시 확인해도 절대 다른 결과가 나올 수 없다
        # (5개 source_type 전수 검토 결과 반례 없음). 과거의 재확인
        # 분기는 이 지점에서 참이 될 수 없는 조건이라 제거했다.

        eligibility_passed = bool(
            getattr(deterministic_trigger, "eligibility_passed", False)
        )
        eligibility_reasons = tuple(
            getattr(deterministic_trigger, "eligibility_reasons", ()) or ()
        )
        if (
            not eligibility_passed
            and decision_context is not None
            and decision_context.signal_feature_snapshot_id is None
            and eligibility_reasons
            and set(eligibility_reasons).issubset(
                {
                    "eligibility_source_type_allowed",
                    "eligibility_low_feature_coverage",
                }
            )
        ):
            return None
        if not eligibility_passed:
            rationale = (
                f"[ai_override_gate] source_type={normalized_source_type} "
                f"eligibility_passed=false reasons={','.join(eligibility_reasons)} "
                f"FDC={decision_type} -> {downgrade_decision}"
            )
            return (
                downgrade_decision,
                rationale,
                ("ai_override_gate", "ai_override_eligibility_blocked"),
            )
        if any(
            reason in _AI_OVERRIDE_EXECUTION_INFEASIBLE_REASONS
            for reason in eligibility_reasons
        ):
            rationale = (
                f"[ai_override_gate] source_type={normalized_source_type} "
                f"execution_infeasible reasons={','.join(eligibility_reasons)} "
                f"FDC={decision_type} -> {downgrade_decision}"
            )
            return (
                downgrade_decision,
                rationale,
                ("ai_override_gate", "ai_override_execution_infeasible"),
            )

        if not ai_inputs.expected_value_gate_passed:
            rationale = (
                f"[ai_override_gate] source_type={normalized_source_type} "
                f"expected_value_gate_passed=false FDC={decision_type} -> {downgrade_decision}"
            )
            return (
                downgrade_decision,
                rationale,
                ("ai_override_gate", "ai_override_expected_value_blocked"),
            )

        if (
            decision_context is None
            or instrument is None
        ):
            return None

        symbol_state = await self._repos.symbol_trade_states.get_by_account_and_instrument(
            decision_context.account_id,
            instrument.instrument_id,
        )
        if symbol_state is None:
            return None

        recent_events = await self._repos.external_events.list_by_symbol(
            instrument.symbol,
            datetime.now(timezone.utc) - timedelta(hours=24),
            include_seeded_news=True,
        )

        hysteresis_decision = evaluate_symbol_state_buy_hysteresis(
            symbol_state=symbol_state,
            current_signal_feature_snapshot_id=(
                str(decision_context.signal_feature_snapshot_id)
                if decision_context.signal_feature_snapshot_id is not None
                else None
            ),
            now_utc=datetime.now(timezone.utc),
            current_edge_after_cost_bps=ai_inputs.edge_after_cost_bps,
            recent_events=recent_events,
        )
        if hysteresis_decision.blocked:
            detail_code = hysteresis_decision.detail_code or "ai_override_gate"
            if detail_code == "ai_override_state_pending_conflict":
                rationale = (
                    f"[ai_override_gate] symbol_state={symbol_state.state} "
                    f"pending conflict FDC={decision_type} -> {downgrade_decision}"
                )
            elif detail_code == "ai_override_reverse_same_signal_feature_blocked":
                rationale = (
                    f"[ai_override_gate] same_signal_feature_snapshot_id="
                    f"{hysteresis_decision.details.get('current_signal_feature_snapshot_id')} "
                    f"reentry cooldown active FDC={decision_type} -> {downgrade_decision}"
                )
            elif detail_code == "ai_override_reverse_feature_change_blocked":
                rationale = (
                    f"[ai_override_gate] signal_feature_snapshot change missing "
                    f"current={hysteresis_decision.details.get('current_signal_feature_snapshot_id')} "
                    f"last={hysteresis_decision.details.get('last_signal_feature_snapshot_id')} "
                    f"FDC={decision_type} -> {downgrade_decision}"
                )
            elif detail_code == "ai_override_reverse_event_novelty_blocked":
                rationale = (
                    f"[ai_override_gate] event novelty insufficient "
                    f"reentry_novelty={hysteresis_decision.details.get('reentry_event_novelty')} "
                    f"FDC={decision_type} -> {downgrade_decision}"
                )
            elif detail_code == "ai_override_reverse_edge_regression_blocked":
                rationale = (
                    f"[ai_override_gate] edge_after_cost regression "
                    f"current={hysteresis_decision.details.get('current_edge_after_cost_bps')} "
                    f"last_exit={hysteresis_decision.details.get('last_exit_edge_after_cost_bps')} "
                    f"FDC={decision_type} -> {downgrade_decision}"
                )
            else:
                rationale = (
                    f"[ai_override_gate] earliest_reentry_at="
                    f"{hysteresis_decision.details.get('earliest_reentry_at')} "
                    f"FDC={decision_type} -> {downgrade_decision}"
                )
            return (
                downgrade_decision,
                rationale,
                ("ai_override_gate", detail_code),
            )
        return None

    async def _record_loss_cut_shadow_observation(
        self,
        *,
        trade_decision_id: UUID | None,
        position_snapshot: PositionSnapshotEntity | None,
        source_type: str,
        composer_output: FinalDecisionComposerOutput | None,
    ) -> None:
        """손실률 기반 loss-cut shadow 관측을 기록한다 (관측 전용, 결정 미개입).

        이 메서드는 ``assemble()``의 결정 확정 이후(트레이드 결정 mutation이
        모두 끝난 뒤) 호출되며, 반환값이 없고 어떤 결정 필드도 mutate하지
        않는다 — 그 자체로 이 관측이 실주문 판단에 영향을 줄 수 없음을
        보장한다. 관측 결과 저장 실패는 로그로 남기되 예외를 전파하지
        않는다(실주문 판단 흐름과 무관하게 독립적으로 처리).
        """
        if not self._loss_cut_shadow_enabled:
            return
        if trade_decision_id is None:
            return

        has_position = (
            position_snapshot is not None
            and position_snapshot.quantity is not None
            and position_snapshot.quantity > 0
        )
        if not has_position:
            return

        verdict = evaluate_loss_cut_shadow(
            average_price=position_snapshot.average_price,
            market_price=position_snapshot.market_price,
            soft_threshold_pct=self._loss_cut_shadow_soft_threshold_pct,
            hard_threshold_pct=self._loss_cut_shadow_hard_threshold_pct,
        )

        payload: dict[str, object] = {
            "account_id": str(position_snapshot.account_id),
            "instrument_id": str(position_snapshot.instrument_id),
            "source_type": source_type,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "average_price": str(position_snapshot.average_price),
            "market_price": (
                str(position_snapshot.market_price)
                if position_snapshot.market_price is not None
                else None
            ),
            "loss_pct": (
                str(verdict.loss_pct) if verdict.loss_pct is not None else None
            ),
            "triggered": verdict.triggered,
            "tier": verdict.tier,
            "skipped_reason": verdict.skipped_reason,
            "soft_threshold_pct": str(self._loss_cut_shadow_soft_threshold_pct),
            "hard_threshold_pct": str(self._loss_cut_shadow_hard_threshold_pct),
            "actual_decision_type": (
                composer_output.decision_type if composer_output is not None else None
            ),
            "actual_side": (
                composer_output.side if composer_output is not None else None
            ),
            # shadow 관측이 실제 결정에 영향을 주지 않았음을 명시하는 필드.
            "shadow_only": True,
            "decision_unaffected_by_shadow": True,
        }

        try:
            await self._repos.trade_decisions.sync_loss_cut_shadow_observation(
                trade_decision_id,
                loss_cut_shadow_payload=payload,
            )
        except Exception:
            logger.warning(
                "loss_cut_shadow observation sync failed: trade_decision_id=%s",
                trade_decision_id,
                exc_info=True,
            )

    async def _record_ar_shadow_bot_observation(
        self,
        *,
        trade_decision_id: UUID | None,
        assembled_context: AssembledContext,
        ai_policy_context: AIPolicyContextView,
        ar_output: AIRiskOutput | None,
        composer_output: FinalDecisionComposerOutput | None,
    ) -> None:
        """AR(``ai_risk``) shadow bot 관측을 기록한다(관측 전용, 결정 미개입).

        ``_record_loss_cut_shadow_observation()``과 동일한 원칙 — 이
        메서드는 ``assemble()``의 결정 확정 이후에만 호출되며, 반환값이
        없고 어떤 결정 필드도 mutate하지 않는다. held_position override/
        FDC skip "would trigger" 비교는 실제 override/skip 판정 함수를
        그대로 재사용해(bot 산출값을 담은 synthetic ``AIRiskOutput``만
        바꿔치기) 로직 drift 없이 재현한다.
        """
        if not self._ar_shadow_bot_enabled:
            return
        if trade_decision_id is None or ar_output is None:
            return

        source_type = (assembled_context.source_type or "core").strip().lower()

        try:
            bot_result = compute_shadow_risk_bot(
                portfolio_allocation=assembled_context.portfolio_allocation,
                market_regime=assembled_context.market_regime,
                deterministic_trigger=assembled_context.deterministic_trigger,
                recent_events=assembled_context.recent_events,
            )
            bot_ar_output = AIRiskOutput(
                risk_opinion=bot_result.risk_opinion,
                risk_score=bot_result.risk_score,
                risk_flags=bot_result.risk_flags,
                reason_codes=bot_result.reason_codes,
                confidence=bot_result.confidence,
            )
            ai_opinion = (ar_output.risk_opinion or "allow").strip().lower()
            ai_score = float(ar_output.risk_score or 0.0)

            held_override_ai = self._check_held_position_sell_override(
                source_type=source_type,
                ar_output=ar_output,
                fdc_output=composer_output,
            ) is not None
            held_override_bot = self._check_held_position_sell_override(
                source_type=source_type,
                ar_output=bot_ar_output,
                fdc_output=composer_output,
            ) is not None

            fdc_skip_ai = _should_skip_final_decision_composer(
                ai_policy_context, ar_output,
            )
            fdc_skip_bot = _should_skip_final_decision_composer(
                ai_policy_context, bot_ar_output,
            )

            exec_risk_off_ai = ai_opinion != "allow" or ai_score >= 0.6
            exec_risk_off_bot = (
                bot_result.risk_opinion != "allow" or bot_result.risk_score >= 0.6
            )

            payload: dict[str, object] = {
                "rule_set_version": AR_SHADOW_RULE_SET_VERSION,
                "bot_risk_opinion": bot_result.risk_opinion,
                "bot_risk_score": bot_result.risk_score,
                "bot_reason_codes": list(bot_result.reason_codes),
                "bot_risk_flags": list(bot_result.risk_flags),
                "bot_confidence": bot_result.confidence,
                "ai_risk_opinion": ai_opinion,
                "ai_risk_score_bucket": risk_score_bucket(ai_score),
                "bot_risk_score_bucket": risk_score_bucket(bot_result.risk_score),
                "opinion_agreement": ai_opinion == bot_result.risk_opinion,
                "score_bucket_agreement": (
                    risk_score_bucket(ai_score)
                    == risk_score_bucket(bot_result.risk_score)
                ),
                "held_position_override_ai_would_trigger": held_override_ai,
                "held_position_override_bot_would_trigger": held_override_bot,
                "held_position_override_agreement": (
                    held_override_ai == held_override_bot
                ),
                "fdc_skip_ai_would_trigger": fdc_skip_ai,
                "fdc_skip_bot_would_trigger": fdc_skip_bot,
                "fdc_skip_agreement": fdc_skip_ai == fdc_skip_bot,
                "execution_risk_off_ai_would_trigger": exec_risk_off_ai,
                "execution_risk_off_bot_would_trigger": exec_risk_off_bot,
                "execution_risk_off_agreement": (
                    exec_risk_off_ai == exec_risk_off_bot
                ),
                "shadow_only": True,
                "decision_unaffected_by_shadow": True,
            }
        except Exception as exc:
            logger.warning(
                "shadow_risk_bot computation failed: trade_decision_id=%s",
                trade_decision_id,
                exc_info=True,
            )
            payload = {
                "rule_set_version": AR_SHADOW_RULE_SET_VERSION,
                "shadow_error": str(exc),
                "shadow_only": True,
                "decision_unaffected_by_shadow": True,
            }

        try:
            await self._repos.trade_decisions.sync_shadow_risk_bot_observation(
                trade_decision_id,
                shadow_risk_bot_payload=payload,
            )
        except Exception:
            logger.warning(
                "shadow_risk_bot observation sync failed: trade_decision_id=%s",
                trade_decision_id,
                exc_info=True,
            )

    async def _record_ei_shadow_bot_observation(
        self,
        *,
        trade_decision_id: UUID | None,
        assembled_context: AssembledContext,
        event_output: EventInterpretationOutput | None,
    ) -> None:
        """EI(``event_interpretation``) shadow bot 관측을 기록한다(관측
        전용, 결정 미개입). 정형 이벤트 필드(``direction``/``severity``/
        ``source_reliability_tier``)만 사용하고 비정형 헤드라인/본문 텍스트
        해석은 하지 않는다.
        """
        if not self._ei_shadow_bot_enabled:
            return
        if trade_decision_id is None:
            return

        try:
            bot_result = compute_shadow_event_bot(assembled_context.recent_events)

            ai_detected = event_output.detected_event_count if event_output else 0
            ai_interpreted = (
                event_output.interpreted_event_count if event_output else 0
            )
            ai_bias = (
                event_output.aggregate_view.overall_bias
                if event_output is not None
                else "neutral"
            )
            ai_conflict = (
                event_output.aggregate_view.event_conflict
                if event_output is not None
                else False
            )
            ai_no_material_events = (
                event_output.aggregate_view.no_material_events
                if event_output is not None
                else True
            )

            payload: dict[str, object] = {
                "rule_set_version": EI_SHADOW_RULE_SET_VERSION,
                "bot_detected_event_count": bot_result.detected_event_count,
                "bot_interpreted_event_count": bot_result.interpreted_event_count,
                "bot_event_bias": bot_result.event_bias,
                "bot_event_conflict": bot_result.event_conflict,
                "bot_evidence_strength": bot_result.evidence_strength,
                "bot_no_material_events": bot_result.no_material_events,
                "bot_reason_codes": list(bot_result.reason_codes),
                "ai_detected_event_count": ai_detected,
                "ai_interpreted_event_count": ai_interpreted,
                "ai_event_bias": ai_bias,
                "ai_event_conflict": ai_conflict,
                "ai_no_material_events": ai_no_material_events,
                "event_count_agreement": ai_detected == bot_result.detected_event_count,
                "bias_agreement": ai_bias == bot_result.event_bias,
                "conflict_agreement": ai_conflict == bot_result.event_conflict,
                "no_material_events_agreement": (
                    ai_no_material_events == bot_result.no_material_events
                ),
                "shadow_only": True,
                "decision_unaffected_by_shadow": True,
            }
        except Exception as exc:
            logger.warning(
                "shadow_event_bot computation failed: trade_decision_id=%s",
                trade_decision_id,
                exc_info=True,
            )
            payload = {
                "rule_set_version": EI_SHADOW_RULE_SET_VERSION,
                "shadow_error": str(exc),
                "shadow_only": True,
                "decision_unaffected_by_shadow": True,
            }

        try:
            await self._repos.trade_decisions.sync_shadow_event_bot_observation(
                trade_decision_id,
                shadow_event_bot_payload=payload,
            )
        except Exception:
            logger.warning(
                "shadow_event_bot observation sync failed: trade_decision_id=%s",
                trade_decision_id,
                exc_info=True,
            )

    async def _record_held_position_fdc_skip_shadow_observation(
        self,
        *,
        trade_decision_id: UUID | None,
        assembled_context: AssembledContext,
        ar_output: AIRiskOutput | None,
        composer_output: FinalDecisionComposerOutput | None,
        fdc_raw_decision_type: str | None,
        fdc_skipped: bool = False,
    ) -> None:
        """``held_position`` FDC 호출 shadow-skip 관측을 기록한다(관측
        전용, 결정 미개입).

        ``deterministic_trigger.primary_candidate``가 ``NO_ACTION``/
        ``WATCH``인 held_position 결정에 한해 "FDC를 실제로 호출하지
        않고 결정론적으로 HOLD/WATCH를 골랐다면, 실제 최종 결과와
        같았을까"를 비교해 기록한다. ``_check_held_position_sell_
        override()``를 그대로 재사용해(가상 FDC 출력만 바꿔치기) shadow
        최종값을 계산한다 — ``_record_ar_shadow_bot_observation()``과
        동일한 "실제 판정 함수 재사용" 원칙이다.

        ``_apply_held_position_sell_override()``가 이미 적용된 이후
        시점에서 호출되므로, ``composer_output.decision_type``은
        override가 개입했다면 그 결과(post-override)를 담고 있다.
        ``fdc_raw_decision_type``은 override 적용 *이전*(FDC 원본 출력)
        값을 호출자가 별도로 캡처해 전달해야 한다.
        """
        if not self._held_position_fdc_skip_shadow_enabled:
            return
        # 실제 FDC 생략 결과를 shadow 표본으로 기록하면, "FDC를 호출했다면
        # 무엇을 골랐을까"라는 관측의 분모가 오염된다. NO_ACTION 실제 skip
        # 이후에도 WATCH 및 REDUCE shadow 표본은 계속 독립적으로 축적한다.
        if fdc_skipped:
            return
        if trade_decision_id is None or composer_output is None:
            return

        source_type = (assembled_context.source_type or "core").strip().lower()
        if source_type != "held_position":
            return

        deterministic_trigger = assembled_context.deterministic_trigger
        if deterministic_trigger is None:
            return

        primary_candidate = (
            getattr(deterministic_trigger, "primary_candidate", "") or ""
        ).strip().upper()
        if primary_candidate not in _HELD_POSITION_FDC_SKIP_SHADOW_PRIMARY_CANDIDATES:
            return

        try:
            shadow_decision_type = "WATCH" if primary_candidate == "WATCH" else "HOLD"
            shadow_fdc_output = FinalDecisionComposerOutput(
                decision_type=shadow_decision_type, side="", confidence=0.0,
            )
            shadow_override = self._check_held_position_sell_override(
                source_type=source_type,
                ar_output=ar_output,
                fdc_output=shadow_fdc_output,
            )
            shadow_final_decision_type = (
                shadow_override[0] if shadow_override is not None
                else shadow_decision_type
            )
            actual_final_decision_type = (
                composer_output.decision_type or ""
            ).strip().upper()

            payload: dict[str, object] = {
                "rule_set_version": HELD_POSITION_FDC_SKIP_SHADOW_RULE_SET_VERSION,
                "primary_candidate": primary_candidate,
                "shadow_skip_candidate": True,
                "shadow_decision_type": shadow_decision_type,
                "shadow_final_decision_type": shadow_final_decision_type,
                "actual_fdc_raw_decision_type": (
                    (fdc_raw_decision_type or "").strip().upper() or None
                ),
                "actual_final_decision_type": actual_final_decision_type,
                "held_position_override_applied": shadow_override is not None,
                "agreement": shadow_final_decision_type == actual_final_decision_type,
                "provider_rate_limit_observed": (
                    "provider_rate_limit" in (composer_output.reason_codes or ())
                ),
                "shadow_only": True,
                "decision_unaffected_by_shadow": True,
            }
        except Exception as exc:
            logger.warning(
                "shadow_held_position_fdc_skip computation failed: "
                "trade_decision_id=%s",
                trade_decision_id,
                exc_info=True,
            )
            payload = {
                "rule_set_version": HELD_POSITION_FDC_SKIP_SHADOW_RULE_SET_VERSION,
                "shadow_error": str(exc),
                "shadow_only": True,
                "decision_unaffected_by_shadow": True,
            }

        try:
            await self._repos.trade_decisions.sync_shadow_held_position_fdc_skip_observation(
                trade_decision_id,
                shadow_held_position_fdc_skip_payload=payload,
            )
        except Exception:
            logger.warning(
                "shadow_held_position_fdc_skip observation sync failed: "
                "trade_decision_id=%s",
                trade_decision_id,
                exc_info=True,
            )

    async def _record_held_position_reduce_skip_shadow_observation(
        self,
        *,
        trade_decision_id: UUID | None,
        assembled_context: AssembledContext,
        ar_output: AIRiskOutput | None,
        composer_output: FinalDecisionComposerOutput | None,
        fdc_raw_decision_type: str | None,
    ) -> None:
        """``held_position`` REDUCE/SELL_CANDIDATE shadow-skip 관측을
        기록한다(관측 전용, 결정 미개입).

        ``_record_held_position_fdc_skip_shadow_observation()``(NO_ACTION/
        WATCH 전용)과 별도 key(``shadow_held_position_reduce_skip``)에
        기록한다 — 이 구간은 REDUCE_CANDIDATE/SELL_CANDIDATE 전체로 보면
        FDC가 실제로 HOLD로 되돌리는 비율이 낮지 않아(2026-08-20 실측
        12.0%/5.9%) 훨씬 더 보수적으로 좁힌 하위 구간만 관측한다:
        ``ar_output.risk_opinion in ("reject", "reduce")`` — 이 조건은
        ``_check_held_position_sell_override()``의 무조건 발동(FDC 출력과
        무관) 분기와 정확히 겹치고, 같은 날 실측상 이 하위 구간(72건)
        에서는 FDC가 HOLD로 되돌린 사례가 0건이었다.

        shadow 최종값은 위 메서드와 동일하게 ``_check_held_position_sell_
        override()``를 재사용해 계산한다. 다만 REDUCE 대 EXIT처럼 세부
        라벨이 갈리더라도 "매도를 시도했는가"라는 실행 의미는 같을 수
        있으므로, 엄격한 라벨 일치(``agreement``/``agreement_decision_
        only``)와 실행 의미 일치(``agreement_execution_meaning``)를
        구분해 기록한다.
        """
        if not self._held_position_reduce_skip_shadow_enabled:
            return
        if trade_decision_id is None or composer_output is None:
            return

        source_type = (assembled_context.source_type or "core").strip().lower()
        if source_type != "held_position":
            return

        deterministic_trigger = assembled_context.deterministic_trigger
        if deterministic_trigger is None:
            return

        primary_candidate = (
            getattr(deterministic_trigger, "primary_candidate", "") or ""
        ).strip().upper()
        if primary_candidate not in _HELD_POSITION_REDUCE_SKIP_SHADOW_PRIMARY_CANDIDATES:
            return

        if ar_output is None:
            return
        risk_opinion = (ar_output.risk_opinion or "").strip().lower()
        if risk_opinion not in _HELD_POSITION_REDUCE_SKIP_SHADOW_RISK_OPINIONS:
            return

        try:
            # FDC를 생략했다면 non-actionable(HOLD)로 시작했을 것이라 가정하고,
            # 실제 AR 출력으로 override를 재적용해 최종값을 시뮬레이션한다.
            shadow_decision_type = "HOLD"
            shadow_fdc_output = FinalDecisionComposerOutput(
                decision_type=shadow_decision_type, side="", confidence=0.0,
            )
            shadow_override = self._check_held_position_sell_override(
                source_type=source_type,
                ar_output=ar_output,
                fdc_output=shadow_fdc_output,
            )
            if shadow_override is not None:
                shadow_final_decision_type, shadow_final_side, _ = shadow_override
            else:
                shadow_final_decision_type = shadow_decision_type
                shadow_final_side = ""

            actual_final_decision_type = (
                composer_output.decision_type or ""
            ).strip().upper()
            actual_final_side = (composer_output.side or "").strip().upper()

            agreement_decision_only = (
                shadow_final_decision_type == actual_final_decision_type
            )
            agreement_execution_meaning = _held_position_action_class(
                shadow_final_decision_type
            ) == _held_position_action_class(actual_final_decision_type)

            payload: dict[str, object] = {
                "rule_set_version": HELD_POSITION_REDUCE_SKIP_SHADOW_RULE_SET_VERSION,
                "primary_candidate": primary_candidate,
                "risk_opinion": risk_opinion,
                "risk_score": ar_output.risk_score,
                "shadow_skip_candidate": True,
                "shadow_decision_type": shadow_decision_type,
                "shadow_final_decision_type": shadow_final_decision_type,
                "shadow_final_side": shadow_final_side or None,
                "actual_fdc_raw_decision_type": (
                    (fdc_raw_decision_type or "").strip().upper() or None
                ),
                "actual_final_decision_type": actual_final_decision_type,
                "actual_final_side": actual_final_side or None,
                "held_position_override_applied": shadow_override is not None,
                "agreement": agreement_decision_only,
                "agreement_decision_only": agreement_decision_only,
                "agreement_execution_meaning": agreement_execution_meaning,
                "provider_rate_limit_observed": (
                    "provider_rate_limit" in (composer_output.reason_codes or ())
                ),
                "shadow_only": True,
                "decision_unaffected_by_shadow": True,
            }
        except Exception as exc:
            logger.warning(
                "shadow_held_position_reduce_skip computation failed: "
                "trade_decision_id=%s",
                trade_decision_id,
                exc_info=True,
            )
            payload = {
                "rule_set_version": HELD_POSITION_REDUCE_SKIP_SHADOW_RULE_SET_VERSION,
                "shadow_error": str(exc),
                "shadow_only": True,
                "decision_unaffected_by_shadow": True,
            }

        try:
            await self._repos.trade_decisions.sync_shadow_held_position_reduce_skip_observation(
                trade_decision_id,
                shadow_held_position_reduce_skip_payload=payload,
            )
        except Exception:
            logger.warning(
                "shadow_held_position_reduce_skip observation sync failed: "
                "trade_decision_id=%s",
                trade_decision_id,
                exc_info=True,
            )

    def _capture_fdc_ready_shadow_event(
        self,
        *,
        decision_cycle_id: str | None,
        assembled_context: AssembledContext,
        symbol: str,
        resolved_context_id: UUID | None,
        fdc_ready_at_raw: str,
    ) -> None:
        """FDC cycle-scoped batch queue **lifecycle shadow**(Phase 1,
        2026-08-25 2차 보정) — "같은 cycle 내 앞선 shadow FDC-ready job
        까지 포함한 FIFO 가상 13 RPM 큐에서 지금 승인 가능한가"를 판단할
        수 있도록 관측값만 ``self.pending_fdc_ready_shadow_event``에
        노출한다. **DB에 아무것도 쓰지 않는다** — 이 메서드는 동기 함수고
        `await`가 전혀 없다.

        설계 근거: docs/40_action_plans/fdc_cycle_scoped_batch_queue_
        gemini_shared_13rpm_quota_design_2026-08-25.md §11(2차 보정).

        2차 보정 이유: 1차 보정까지는 이 메서드가 ``assemble()`` 끝(기존
        FDC 호출·strict limiter 대기·저장이 이미 끝난 시점)에서 바로
        DB에 shadow job을 등록하고 ``enqueue_sequence``를 발급받았다.
        그런데 여러 심볼이 동시에(semaphore 상한 내에서) 처리되는 실제
        운영 구조에서는 "``assemble()``에 먼저 도착한 순서"가 "실제
        `fdc_ready_at` 순서"와 다를 수 있다 — 나중에 FDC-ready가 된
        심볼이 먼저 처리를 끝내고 먼저 ``assemble()``에 도착하면, 더
        이른 `fdc_ready_at`을 가진 다른 심볼보다 먼저 작은
        `enqueue_sequence`를 받는 역전이 발생했다. 이는 "FDC-ready 도착
        순서대로 FIFO 처리한다"는 shadow의 검증 목적에 맞지 않는다.

        2차 보정 후에는 이 메서드가 DB 등록을 전혀 하지 않고, `decision_
        cycle_id`(호출자가 넘긴 **진짜 cycle-scoped** 식별자 — `request.
        correlation_id`는 심볼별로 다른 문자열이라 쓰지 않는다)·심볼·
        `fdc_ready_at`만 담은 ``FdcReadyShadowEvent``를 만들어 노출한다.
        실제 DB 등록(및 그에 따른 `enqueue_sequence` 발급)은 호출자
        (`run_decision_loop.py`)가 사이클의 모든 심볼 처리가 끝난 뒤, 이
        이벤트들을 `(fdc_ready_at, cycle_index)` 기준으로 정렬해 순차
        재생할 때 비로소 일어난다 — 그 시점에는 완료 순서와 무관하게
        진짜 FDC-ready 순서가 보장된다.

        ``fdc_ready_at_raw``는 ``AIDecisionInputs.fdc_ready_at``(ISO-8601
        UTC 문자열)를 그대로 전달받는다 — 이 값은 `_check_fdc_skip()`
        (subprocess 경로) 또는 `_should_skip_final_decision_composer()`
        (in-process 경로)가 "FDC 호출이 필요하다"고 판정한 **직후, 실제
        permit 대기/HTTP 호출이 시작되기 직전**에 캡처된다. 빈
        문자열이면 그 건은 결정론적으로 skip된 것이라 FDC-ready가
        아니므로 대상에서 제외한다.
        """
        self.pending_fdc_ready_shadow_event = None
        if not self._fdc_batch_queue_lifecycle_shadow_enabled:
            return
        if not fdc_ready_at_raw:
            return

        try:
            fdc_ready_at = datetime.fromisoformat(fdc_ready_at_raw)
        except ValueError:
            logger.warning(
                "fdc_batch_queue_lifecycle_shadow: invalid fdc_ready_at=%r "
                "symbol=%s — skipping shadow event capture",
                fdc_ready_at_raw,
                symbol,
            )
            return

        self.pending_fdc_ready_shadow_event = FdcReadyShadowEvent(
            decision_cycle_id=decision_cycle_id,
            decision_context_id=resolved_context_id,
            symbol=symbol,
            source_type=(assembled_context.source_type or "core"),
            fdc_ready_at=fdc_ready_at,
        )

    async def _check_held_position_exit_hysteresis_gate(
        self,
        *,
        source_type: str,
        fdc_output: FinalDecisionComposerOutput | None,
        ai_inputs: AIDecisionInputs,
        risk_output: AIRiskOutput | None,
        decision_context: DecisionContextEntity | None,
        instrument: InstrumentEntity | None,
        position_snapshot: PositionSnapshotEntity | None,
    ) -> tuple[str, str, tuple[str, ...]] | None:
        if source_type != "held_position" or fdc_output is None:
            return None
        decision_type = (fdc_output.decision_type or "").strip().upper()
        decision_side = (fdc_output.side or "").strip().upper()
        has_position = (
            position_snapshot is not None
            and position_snapshot.quantity is not None
            and position_snapshot.quantity > 0
        )
        if not has_position:
            return None
        if decision_type not in {"REDUCE", "EXIT", "SELL"} or decision_side != "SELL":
            return None
        if decision_context is None or instrument is None:
            return None

        symbol_state = await self._repos.symbol_trade_states.get_by_account_and_instrument(
            decision_context.account_id,
            instrument.instrument_id,
        )
        if symbol_state is None:
            return None
        recent_events = await self._repos.external_events.list_by_symbol(
            instrument.symbol,
            datetime.now(timezone.utc) - timedelta(hours=24),
            include_seeded_news=True,
        )
        hysteresis = evaluate_symbol_state_sell_hysteresis(
            symbol_state=symbol_state,
            current_edge_after_cost_bps=ai_inputs.edge_after_cost_bps,
            risk_output=risk_output,
            recent_events=recent_events,
            now_utc=datetime.now(timezone.utc),
        )
        if not hysteresis.blocked:
            return None
        rationale = (
            f"[held_position_exit_hysteresis] early reduce blocked "
            f"edge_collapse={hysteresis.details.get('exit_edge_collapse_passed')} "
            f"downside_shock={hysteresis.details.get('exit_downside_shock_passed')} "
            f"thesis_invalidation={hysteresis.details.get('exit_thesis_invalidation_passed')} "
            f"holding_profile_breach={hysteresis.details.get('exit_holding_profile_breach_passed')} "
            f"FDC={decision_type} -> WATCH"
        )
        return ("WATCH", rationale, ("held_position_exit_hysteresis_blocked",))

    async def _ensure_or_create_decision_context(
        self,
        request: SubmitOrderRequest,
        existing_context_id: UUID | None,
    ) -> UUID | None:
        """Thin wrapper — delegates to DecisionContextService.ensure_or_create()."""
        return await self._decision_context_service.ensure_or_create(
            request=request,
            existing_context_id=existing_context_id,
        )

    async def _ensure_trade_decision(
        self,
        *,
        decision_context_id: UUID | None,
        request: SubmitOrderRequest,
        assembled_context: AssembledContext,
        agent_bundle: AgentExecutionBundle,
        instrument: InstrumentEntity | None = None,
        fdc_run_id: UUID | None = None,
    ) -> TradeDecisionEntity | None:
        """Thin wrapper — delegates to build_trade_decision_entity() + repository add."""
        resolved_instrument = instrument
        if resolved_instrument is None:
            try:
                resolved_instrument = await self._repos.instruments.get_by_symbol(
                    symbol=request.symbol,
                    market_code=request.market,
                )
                if resolved_instrument is None:
                    resolved_instrument = await self._repos.instruments.get_by_symbol_any_market(
                        request.symbol
                    )
            except Exception:
                resolved_instrument = None
        td_entity = build_trade_decision_entity(
            decision_context_id=decision_context_id,
            request=request,
            assembled_context=assembled_context,
            agent_bundle=agent_bundle,
            instrument_id=(
                resolved_instrument.instrument_id
                if resolved_instrument is not None
                else None
            ),
            fdc_run_id=fdc_run_id,
            policy_git_sha=resolve_policy_git_sha(),
        )
        if td_entity is not None:
            td_entity = await self._repos.trade_decisions.add(td_entity)
            await self._persist_symbol_trade_state_from_decision(
                trade_decision=td_entity,
                assembled_context=assembled_context,
                instrument=resolved_instrument,
                composer_output=agent_bundle.composer_output,
            )
        return td_entity

    async def _persist_symbol_trade_state_from_decision(
        self,
        *,
        trade_decision: TradeDecisionEntity,
        assembled_context: AssembledContext,
        instrument: InstrumentEntity | None,
        composer_output: FinalDecisionComposerOutput | None,
    ) -> None:
        decision_context = assembled_context.decision_context
        if decision_context is None or instrument is None:
            return

        now = trade_decision.created_at
        current_state = await self._repos.symbol_trade_states.get_by_account_and_instrument(
            decision_context.account_id,
            instrument.instrument_id,
        )
        policy_payload = trade_decision.decision_json.get("holding_profile_policy")
        serialized_policy_payload: dict[str, object] | None = None
        if isinstance(policy_payload, dict):
            serialized_policy_payload = dict(policy_payload)
            holding_profile = policy_payload.get("holding_profile")
            minimum_hold_until = parse_datetime_or_none(
                policy_payload.get("minimum_hold_until")
            )
            reentry_cooldown_until = parse_datetime_or_none(
                policy_payload.get("reentry_cooldown_until")
            )
            sell_cooldown_until = parse_datetime_or_none(
                policy_payload.get("sell_cooldown_until")
            )
            thesis_state_hash = policy_payload.get("thesis_state_hash")
            policy_metadata = (
                dict(policy_payload.get("metadata"))
                if isinstance(policy_payload.get("metadata"), dict)
                else {}
            )
        else:
            fallback_policy = derive_holding_profile_policy(
                source_type=assembled_context.source_type,
                decision_type=(
                    composer_output.decision_type
                    if composer_output is not None
                    else trade_decision.decision_type.value
                ),
                side=(
                    composer_output.side
                    if composer_output is not None and composer_output.side
                    else trade_decision.side
                ),
                time_horizon=(
                    composer_output.time_horizon
                    if composer_output is not None
                    else None
                ),
                quantity=trade_decision.quantity,
                max_order_value=trade_decision.max_order_value,
                signal_feature_snapshot_id=(
                    str(assembled_context.signal_feature_snapshot.signal_feature_snapshot_id)
                    if assembled_context.signal_feature_snapshot is not None
                    else (
                        str(decision_context.signal_feature_snapshot_id)
                        if decision_context.signal_feature_snapshot_id is not None
                        else None
                    )
                ),
                reason_codes=trade_decision.reason_codes,
                now_utc=now,
            )
            serialized_policy = serialize_holding_profile_policy(fallback_policy)
            serialized_policy_payload = dict(serialized_policy)
            holding_profile = serialized_policy.get("holding_profile")
            minimum_hold_until = parse_datetime_or_none(
                serialized_policy.get("minimum_hold_until")
            )
            reentry_cooldown_until = parse_datetime_or_none(
                serialized_policy.get("reentry_cooldown_until")
            )
            sell_cooldown_until = parse_datetime_or_none(
                serialized_policy.get("sell_cooldown_until")
            )
            thesis_state_hash = serialized_policy.get("thesis_state_hash")
            policy_metadata = (
                dict(serialized_policy.get("metadata"))
                if isinstance(serialized_policy.get("metadata"), dict)
                else {}
            )

        state_value = current_state.state if current_state is not None else "flat"
        last_entry_at = current_state.last_entry_at if current_state is not None else None
        last_reduce_at = current_state.last_reduce_at if current_state is not None else None
        last_exit_at = current_state.last_exit_at if current_state is not None else None
        if trade_decision.side == OrderSide.BUY and trade_decision.decision_type in {
            DecisionType.APPROVE,
            DecisionType.BUY,
        }:
            state_value = "entry_pending"
            last_entry_at = now
        elif trade_decision.side == OrderSide.SELL and trade_decision.decision_type == DecisionType.REDUCE:
            state_value = "reduce_pending"
            last_reduce_at = now
        elif trade_decision.side == OrderSide.SELL and trade_decision.decision_type in {
            DecisionType.SELL,
            DecisionType.EXIT,
        }:
            state_value = "exit_pending"
            last_exit_at = now

        merged_metadata = dict(current_state.metadata_json) if current_state is not None else {}
        merged_metadata["holding_profile_policy"] = (
            serialized_policy_payload
            if serialized_policy_payload is not None
            else policy_metadata
        )
        expected_value_anchor_payload = (
            dict(trade_decision.decision_json.get("expected_value_anchor"))
            if isinstance(trade_decision.decision_json.get("expected_value_anchor"), dict)
            else None
        )
        if expected_value_anchor_payload is not None:
            merged_metadata["expected_value_anchor"] = expected_value_anchor_payload
        merged_metadata["last_trade_decision_id"] = str(trade_decision.trade_decision_id)
        current_edge_after_cost_bps = (
            trade_decision.decision_json.get("expected_value_gate", {}).get("edge_after_cost_bps")
            if isinstance(trade_decision.decision_json.get("expected_value_gate"), dict)
            else None
        )
        if trade_decision.side == OrderSide.BUY and trade_decision.decision_type in {
            DecisionType.APPROVE,
            DecisionType.BUY,
        }:
            merged_metadata["last_entry_edge_after_cost_bps"] = current_edge_after_cost_bps
            if isinstance(merged_metadata.get("holding_profile_policy"), dict):
                merged_metadata["holding_profile_policy"]["last_entry_edge_after_cost_bps"] = current_edge_after_cost_bps
        elif trade_decision.side == OrderSide.SELL and trade_decision.decision_type == DecisionType.REDUCE:
            merged_metadata["last_reduce_edge_after_cost_bps"] = current_edge_after_cost_bps
            if isinstance(merged_metadata.get("holding_profile_policy"), dict):
                merged_metadata["holding_profile_policy"]["last_reduce_edge_after_cost_bps"] = current_edge_after_cost_bps
        elif trade_decision.side == OrderSide.SELL and trade_decision.decision_type in {
            DecisionType.SELL,
            DecisionType.EXIT,
        }:
            merged_metadata["last_exit_edge_after_cost_bps"] = current_edge_after_cost_bps
            if isinstance(merged_metadata.get("holding_profile_policy"), dict):
                merged_metadata["holding_profile_policy"]["last_exit_edge_after_cost_bps"] = current_edge_after_cost_bps
        if expected_value_anchor_payload is not None:
            if isinstance(merged_metadata.get("holding_profile_policy"), dict):
                merged_metadata["holding_profile_policy"]["expected_value_anchor"] = (
                    expected_value_anchor_payload
                )

        await self._repos.symbol_trade_states.upsert(
            SymbolTradeStateEntity(
                symbol_trade_state_id=(
                    current_state.symbol_trade_state_id
                    if current_state is not None
                    else uuid4()
                ),
                account_id=decision_context.account_id,
                instrument_id=instrument.instrument_id,
                symbol=trade_decision.symbol,
                market=trade_decision.market,
                state=state_value,
                holding_profile=(
                    str(holding_profile)
                    if holding_profile is not None
                    else (
                        current_state.holding_profile
                        if current_state is not None
                        else None
                    )
                ),
                position_quantity=(
                    assembled_context.position_snapshot.quantity
                    if assembled_context.position_snapshot is not None
                    else (
                        current_state.position_quantity
                        if current_state is not None
                        else Decimal("0")
                    )
                ),
                last_entry_order_request_id=(
                    current_state.last_entry_order_request_id
                    if current_state is not None
                    else None
                ),
                last_exit_order_request_id=(
                    current_state.last_exit_order_request_id
                    if current_state is not None
                    else None
                ),
                last_entry_source_type=trade_decision.source_type,
                last_entry_at=last_entry_at,
                last_reduce_at=last_reduce_at,
                last_exit_at=last_exit_at,
                minimum_hold_until=minimum_hold_until,
                reentry_cooldown_until=reentry_cooldown_until,
                sell_cooldown_until=sell_cooldown_until,
                last_signal_feature_snapshot_id=decision_context.signal_feature_snapshot_id,
                last_decision_context_id=trade_decision.decision_context_id,
                last_reason_codes=list(trade_decision.reason_codes or ()),
                thesis_state_hash=(
                    str(thesis_state_hash)
                    if thesis_state_hash is not None
                    else (
                        current_state.thesis_state_hash
                        if current_state is not None
                        else None
                    )
                ),
                metadata_json=merged_metadata,
                created_at=(
                    current_state.created_at
                    if current_state is not None
                    else now
                ),
                updated_at=now,
            )
        )

    # ------------------------------------------------------------------
    # Sizing input builder — public delegation to ExecutionService boundary
    # ------------------------------------------------------------------

    def build_sizing_inputs(
        self,
        intent: OrderIntent,
        reference_price: Decimal | None = None,
    ) -> SizingInputs:
        """Build ``SizingInputs`` from an ``OrderIntent``.

        Public delegation method — forwards to
        ``ExecutionService._build_sizing_inputs()`` (a ``@staticmethod``)
        to avoid duplicating the sizing-input mapping logic.  External
        callers (scripts, tests) must use this method instead of reaching
        into execution-boundary internals directly.
        """
        return ExecutionService._build_sizing_inputs(
            intent=intent,
            reference_price=reference_price,
        )

    def _extract_source_type(
        self,
        request: SubmitOrderRequest,
    ) -> str:
        """요청 metadata에서 source_type을 안전하게 추출한다."""
        source_type = "core"
        try:
            if request.metadata and isinstance(request.metadata, dict):
                source_type = request.metadata.get("source_type", "core") or "core"
        except Exception:
            pass
        return source_type

    async def _derive_deterministic_context_components(
        self,
        *,
        request: SubmitOrderRequest,
        config_version: ConfigVersionEntity | None,
        instrument: InstrumentEntity | None,
        position_snapshot: PositionSnapshotEntity | None,
        cash_balance_snapshot: CashBalanceSnapshotEntity | None,
        risk_limit_snapshot: RiskLimitSnapshotEntity | None,
        deterministic_trigger_override: dict[str, object] | None = None,
        r3b_alpha_percentile: float | None = None,
    ) -> DeterministicDerivationBundle:
        """assemble()의 deterministic 파생 계산 단계를 별도 helper로 분리한다."""
        signal_feature_snapshot: SignalFeatureSnapshotEntity | None = None
        instrument_for_signal = instrument
        if instrument_for_signal is None:
            try:
                instrument_for_signal = await self._repos.instruments.get_by_symbol(
                    symbol=request.symbol,
                    market_code=request.market,
                )
            except Exception:
                instrument_for_signal = None
        if instrument_for_signal is not None:
            try:
                signal_feature_snapshot = (
                    await self._repos.signal_feature_snapshots.get_latest_by_instrument(
                        instrument_for_signal.instrument_id,
                    )
                )
            except Exception:
                pass

        market_regime = classify_market_regime(signal_feature_snapshot)
        source_type = self._extract_source_type(request)
        strategy_selection = select_strategy(
            market_regime=market_regime,
            source_type=source_type,
        )
        portfolio_allocation = assess_portfolio_allocation(
            symbol=request.symbol,
            source_type=source_type,
            config_version=config_version,
            position_snapshot=position_snapshot,
            cash_balance_snapshot=cash_balance_snapshot,
            risk_limit_snapshot=risk_limit_snapshot,
            market_regime=market_regime,
            strategy_selection=strategy_selection,
        )
        deterministic_trigger = assess_deterministic_triggers(
            source_type=source_type,
            signal_feature_snapshot=signal_feature_snapshot,
            market_regime=market_regime,
            strategy_selection=strategy_selection,
            portfolio_allocation=portfolio_allocation,
            position_snapshot=position_snapshot,
            deterministic_trigger_override=deterministic_trigger_override,
            regime_switch_v1_trigger_status=self._regime_switch_v1_trigger_status,
            regime_switch_v1_gate_override_enabled=(
                self._regime_switch_v1_gate_override_enabled
            ),
            r3b_alpha_percentile=r3b_alpha_percentile,
            r3b_alpha_enabled=self._r3b_alpha_enabled,
        )
        return DeterministicDerivationBundle(
            source_type=source_type,
            signal_feature_snapshot=signal_feature_snapshot,
            market_regime=market_regime,
            strategy_selection=strategy_selection,
            portfolio_allocation=portfolio_allocation,
            deterministic_trigger=deterministic_trigger,
        )

    @staticmethod
    def _extract_deterministic_trigger_override(
        request: SubmitOrderRequest,
    ) -> dict[str, object] | None:
        metadata = request.metadata if isinstance(request.metadata, dict) else {}
        raw = metadata.get("deterministic_trigger_override")
        if not isinstance(raw, dict):
            return None
        return dict(raw)

    @staticmethod
    def _extract_r3b_alpha_percentile(
        request: SubmitOrderRequest,
    ) -> float | None:
        """cycle precompute 호출부가 `request.metadata["r3b_alpha_
        percentile"]`로 미리 주입한 당일 candidate_percentile을 꺼낸다
        (SPPV-2.67). 아직 이 값을 채우는 cycle precompute 배선은 별도
        단계(§54.5)로 남아 있어, 현재는 metadata에 값이 없으면 항상
        ``None``을 반환하고 기존 동작이 100% 유지된다."""
        metadata = request.metadata if isinstance(request.metadata, dict) else {}
        raw = metadata.get("r3b_alpha_percentile")
        if not isinstance(raw, (int, float)):
            return None
        return float(raw)

    async def _attach_signal_feature_snapshot_to_context(
        self,
        decision_context: DecisionContextEntity | None,
        signal_feature_snapshot: SignalFeatureSnapshotEntity | None,
    ) -> DecisionContextEntity | None:
        """decision_context에 실제 사용한 signal feature snapshot 식별자를 고정한다."""
        if (
            decision_context is None
            or signal_feature_snapshot is None
            or decision_context.signal_feature_snapshot_id
            == signal_feature_snapshot.signal_feature_snapshot_id
        ):
            return decision_context
        try:
            updated = await self._repos.decision_contexts.attach_signal_feature_snapshot(
                decision_context.decision_context_id,
                signal_feature_snapshot.signal_feature_snapshot_id,
            )
            return updated or decision_context
        except Exception:
            return decision_context

    async def _select_usable_cash_snapshot(
        self,
        account_id: UUID,
    ) -> CashBalanceSnapshotEntity | None:
        try:
            snapshots = await self._repos.cash_balance_snapshots.list_by_account(
                account_id,
            )
        except Exception:
            return None

        latest_any = snapshots[0] if snapshots else None
        for snapshot in snapshots:
            if snapshot.fetch_status == "success":
                return snapshot
        return latest_any

    async def _attach_cash_balance_snapshot_to_context(
        self,
        decision_context: DecisionContextEntity | None,
        cash_balance_snapshot: CashBalanceSnapshotEntity | None,
    ) -> DecisionContextEntity | None:
        if (
            decision_context is None
            or cash_balance_snapshot is None
            or decision_context.cash_balance_snapshot_id
            == cash_balance_snapshot.cash_balance_snapshot_id
        ):
            return decision_context
        try:
            updated = await self._repos.decision_contexts.attach_cash_balance_snapshot(
                decision_context.decision_context_id,
                cash_balance_snapshot.cash_balance_snapshot_id,
            )
            return updated or decision_context
        except Exception:
            return decision_context

    async def derive_deterministic_trigger_for_request(
        self,
        request: SubmitOrderRequest,
    ) -> DeterministicDerivationBundle:
        """DecisionContext 생성 없이 cycle prepass용 deterministic 계산만 수행한다."""
        account: AccountEntity | None = None
        config_version: ConfigVersionEntity | None = None
        instrument: InstrumentEntity | None = None
        position_snapshot: PositionSnapshotEntity | None = None
        cash_balance_snapshot: CashBalanceSnapshotEntity | None = None
        risk_limit_snapshot: RiskLimitSnapshotEntity | None = None

        try:
            account = await self._repos.accounts.find_one(
                AccountLookup(account_alias=request.account_ref)
            )
        except Exception:
            account = None

        if account is not None:
            try:
                config_version = await self._repos.config_versions.get_active(
                    client_id=account.client_id,
                    environment=account.environment,
                )
            except Exception:
                config_version = None

        try:
            instrument = await self._repos.instruments.get_by_symbol(
                symbol=request.symbol,
                market_code=request.market,
            )
            if instrument is None:
                instrument = await self._repos.instruments.get_by_symbol_any_market(
                    request.symbol
                )
        except Exception:
            instrument = None

        if account is not None:
            if instrument is not None:
                try:
                    snapshots = await self._repos.position_snapshots.list_latest_by_account(
                        account.account_id
                    )
                    for snapshot in snapshots:
                        if snapshot.instrument_id == instrument.instrument_id:
                            position_snapshot = snapshot
                            break
                except Exception:
                    position_snapshot = None
            try:
                cash_balance_snapshot = await self._select_usable_cash_snapshot(
                    account.account_id
                )
            except Exception:
                cash_balance_snapshot = None
            try:
                risk_limit_snapshot = await self._repos.risk_limit_snapshots.get_latest_by_account(
                    account.account_id
                )
            except Exception:
                risk_limit_snapshot = None

        return await self._derive_deterministic_context_components(
            request=request,
            config_version=config_version,
            instrument=instrument,
            position_snapshot=position_snapshot,
            cash_balance_snapshot=cash_balance_snapshot,
            risk_limit_snapshot=risk_limit_snapshot,
            deterministic_trigger_override=self._extract_deterministic_trigger_override(
                request
            ),
            r3b_alpha_percentile=self._extract_r3b_alpha_percentile(request),
        )

    def _build_ai_policy_context_view(
        self,
        assembled_context: AssembledContext,
    ) -> AIPolicyContextView:
        """내부 assembled context를 AI Policy Stage 전용 입력 뷰로 축소한다."""
        return AIPolicyContextView(
            decision_context=assembled_context.decision_context,
            recent_events=assembled_context.recent_events,
            score=assembled_context.score,
            position_snapshot=assembled_context.position_snapshot,
            cash_balance_snapshot=assembled_context.cash_balance_snapshot,
            risk_limit_snapshot=assembled_context.risk_limit_snapshot,
            signal_feature_snapshot=assembled_context.signal_feature_snapshot,
            market_regime=assembled_context.market_regime,
            strategy_selection=assembled_context.strategy_selection,
            portfolio_allocation=assembled_context.portfolio_allocation,
            deterministic_trigger=assembled_context.deterministic_trigger,
            instrument_market_segment=assembled_context.instrument_market_segment,
            instrument_index_memberships=assembled_context.instrument_index_memberships,
            primary_index_membership=assembled_context.primary_index_membership,
            source_type=assembled_context.source_type,
        )

    @staticmethod
    def _extract_instrument_market_segment(
        instrument: InstrumentEntity | None,
        request: SubmitOrderRequest,
    ) -> str | None:
        if instrument is not None and instrument.market_segment:
            value = str(instrument.market_segment).strip().upper()
            if value:
                return value
        metadata = request.metadata if isinstance(request.metadata, dict) else {}
        raw = metadata.get("market_segment")
        if raw is None:
            return None
        value = str(raw).strip().upper()
        return value or None

    @staticmethod
    def _extract_instrument_index_memberships(
        instrument: InstrumentEntity | None,
        request: SubmitOrderRequest,
    ) -> tuple[str, ...]:
        candidates: object | None = None
        if instrument is not None and isinstance(instrument.metadata, dict):
            candidates = instrument.metadata.get("index_memberships")
        if candidates is None and isinstance(request.metadata, dict):
            candidates = request.metadata.get("index_memberships")
        if candidates is None:
            return ()
        if isinstance(candidates, str):
            raw_values = [candidates]
        elif isinstance(candidates, (list, tuple, set, frozenset)):
            raw_values = list(candidates)
        else:
            return ()
        return normalize_index_memberships(raw_values)

    def _build_short_circuit_agent_bundle(
        self,
        *,
        decision_type: str,
        rationale: str,
        reason_codes: tuple[str, ...],
        validation_result: ValidationResult,
    ) -> AgentExecutionBundle:
        """AI 호출 없이 deterministic policy stage에서 종료할 bundle 생성."""
        event_output = EventInterpretationOutput()
        risk_output = AIRiskOutput(
            reason_codes=("pre_ai_short_circuit",),
            summary="AI 호출 전 deterministic short-circuit 적용",
        )
        composer_output = FinalDecisionComposerOutput(
            decision_type=decision_type,
            side="",
            confidence=0.0,
            conviction=0.0,
            reason_codes=reason_codes,
            summary=rationale,
        )
        ai_inputs = AIDecisionInputs(
            decision_type=decision_type,
            confidence=0.0,
            conviction=0.0,
            reason_codes=reason_codes,
            side="",
            risk_opinion=risk_output.risk_opinion,
            risk_score=risk_output.risk_score,
            risk_confidence=risk_output.confidence,
            size_adjustment_factor=risk_output.size_adjustment_factor,
            risk_reason_codes=risk_output.reason_codes,
            risk_flags=risk_output.risk_flags,
            event_bias=event_output.aggregate_view.overall_bias,
            event_conflict=event_output.aggregate_view.event_conflict,
            event_reason_codes=event_output.aggregate_view.top_reason_codes,
            evidence_strength=event_output.aggregate_view.evidence_strength,
            no_material_events=event_output.aggregate_view.no_material_events,
            detected_event_count=event_output.detected_event_count,
            interpreted_event_count=event_output.interpreted_event_count,
            source_agent_names=(),
            schema_versions=(
                ("event_interpretation", event_output.schema_version),
                ("ai_risk", risk_output.schema_version),
                ("final_decision_composer", composer_output.schema_version),
            ),
            ei_skipped=True,
            ar_skipped=True,
            fdc_skipped=True,
            skip_reason_codes=reason_codes,
        )
        expected_value = evaluate_expected_value_gate(
            decision_type=ai_inputs.decision_type,
            confidence=ai_inputs.confidence,
            conviction=ai_inputs.conviction,
            risk_score=ai_inputs.risk_score,
            context=AssembledContext(source_type="core"),
        )
        ai_inputs = replace(
            ai_inputs,
            expected_return_bps=expected_value.expected_return_bps,
            expected_downside_bps=expected_value.expected_downside_bps,
            net_expected_value_bps=expected_value.net_expected_value_bps,
            final_trade_score=expected_value.final_trade_score,
            minimum_required_edge_bps=expected_value.minimum_required_edge_bps,
            edge_after_cost_bps=expected_value.edge_after_cost_bps,
            estimated_round_trip_cost_bps=expected_value.estimated_round_trip_cost_bps,
            slippage_buffer_bps=expected_value.slippage_buffer_bps,
            expected_value_gate_passed=expected_value.expected_value_gate_passed,
            expected_value_gate_reason_codes=expected_value.reason_codes,
            validator_rule_set_version=validation_result.rule_set_version,
            validator_stop_reason=validation_result.stop_reason,
            validator_blocking_rule_codes=validation_result.blocking_rule_codes,
        )
        return AgentExecutionBundle(
            ai_inputs=ai_inputs,
            event_output=event_output,
            risk_output=risk_output,
            composer_output=composer_output,
        )

    def _build_decision_policy_validation_result(
        self,
        *,
        blocking_rule_codes: tuple[str, ...],
        rule_results: dict[str, object] | None = None,
    ) -> ValidationResult:
        """decision_orchestrator의 deterministic 차단 결과를 공통 계약으로 표현한다."""
        return ValidationResult.blocked(
            rule_set_version="decision_policy_validator_v1",
            blocking_rule_codes=blocking_rule_codes,
            rule_results=rule_results or {},
            stop_reason=blocking_rule_codes[0] if blocking_rule_codes else None,
        )

    def _build_expected_value_anchor_metadata(
        self,
        *,
        ai_inputs: AIDecisionInputs,
        source_type: str,
        decision_type: str,
        symbol_state: SymbolTradeStateEntity | None,
    ) -> dict[str, object]:
        def _to_decimal(value: object | None) -> Decimal | None:
            if value in (None, ""):
                return None
            if isinstance(value, Decimal):
                return value
            try:
                return Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError):
                return None

        def _to_str(value: Decimal | None) -> str | None:
            return str(value) if value is not None else None

        current_edge = ai_inputs.edge_after_cost_bps
        state_meta = dict(symbol_state.metadata_json) if symbol_state is not None else {}
        policy_meta = (
            dict(state_meta.get("holding_profile_policy"))
            if isinstance(state_meta.get("holding_profile_policy"), dict)
            else {}
        )
        last_entry_edge = _to_decimal(
            policy_meta.get("last_entry_edge_after_cost_bps")
            or state_meta.get("last_entry_edge_after_cost_bps")
        )
        last_reduce_edge = _to_decimal(
            policy_meta.get("last_reduce_edge_after_cost_bps")
            or state_meta.get("last_reduce_edge_after_cost_bps")
        )
        last_exit_edge = _to_decimal(
            policy_meta.get("last_exit_edge_after_cost_bps")
            or state_meta.get("last_exit_edge_after_cost_bps")
        )
        delta_vs_last_entry = (
            current_edge - last_entry_edge
            if current_edge is not None and last_entry_edge is not None
            else None
        )
        delta_vs_last_reduce = (
            current_edge - last_reduce_edge
            if current_edge is not None and last_reduce_edge is not None
            else None
        )
        delta_vs_last_exit = (
            current_edge - last_exit_edge
            if current_edge is not None and last_exit_edge is not None
            else None
        )
        normalized_decision_type = (decision_type or "").strip().upper()
        anchor_required = normalized_decision_type in {
            "APPROVE",
            "BUY",
            "SELL",
            "EXIT",
            "REDUCE",
        }
        anchor_passed = (
            anchor_required
            and ai_inputs.expected_value_gate_passed
            and current_edge is not None
            and ai_inputs.expected_return_bps is not None
            and ai_inputs.expected_downside_bps is not None
            and ai_inputs.net_expected_value_bps is not None
            and ai_inputs.final_trade_score is not None
        )
        return {
            "decision_type": normalized_decision_type,
            "source_type": source_type,
            "anchor_required": anchor_required,
            "anchor_passed": anchor_passed,
            "expected_value_gate_passed": ai_inputs.expected_value_gate_passed,
            "current_edge_after_cost_bps": _to_str(current_edge),
            "last_entry_edge_after_cost_bps": _to_str(last_entry_edge),
            "last_reduce_edge_after_cost_bps": _to_str(last_reduce_edge),
            "last_exit_edge_after_cost_bps": _to_str(last_exit_edge),
            "edge_vs_last_entry_delta_bps": _to_str(delta_vs_last_entry),
            "edge_vs_last_reduce_delta_bps": _to_str(delta_vs_last_reduce),
            "edge_vs_last_exit_delta_bps": _to_str(delta_vs_last_exit),
            "reentry_edge_improved_vs_last_exit": (
                delta_vs_last_exit is not None and delta_vs_last_exit > 0
            ),
            "exit_edge_deteriorated_vs_last_entry": (
                delta_vs_last_entry is not None and delta_vs_last_entry < 0
            ),
        }

    def _build_compliance_validation_result(
        self,
        *,
        source_type: str,
        has_position: bool,
        intent_action: str = "new_buy",
        context_metadata: dict[str, object] | None = None,
    ) -> ValidationResult:
        return evaluate_compliance_rules(
            context=ValidationContext(
                source_type=source_type,
                metadata=dict(context_metadata or {}),
            ),
            validation_input=ComplianceValidationInput(
                source_type=source_type,
                has_position=has_position,
                intent_action=intent_action,
            ),
        )

    def _apply_validation_result_to_ai_inputs(
        self,
        ai_inputs: AIDecisionInputs,
        *,
        validation_result: ValidationResult,
    ) -> None:
        """최종 AI 입력 계약에 validator 메타데이터를 누적한다."""
        existing_codes = tuple(ai_inputs.validator_blocking_rule_codes or ())
        merged_codes = tuple(
            dict.fromkeys(existing_codes + tuple(validation_result.blocking_rule_codes))
        )
        object.__setattr__(
            ai_inputs,
            "validator_rule_set_version",
            validation_result.rule_set_version,
        )
        object.__setattr__(
            ai_inputs,
            "validator_stop_reason",
            validation_result.stop_reason,
        )
        object.__setattr__(
            ai_inputs,
            "validator_blocking_rule_codes",
            merged_codes,
        )

    def _evaluate_pre_agent_short_circuit(
        self,
        *,
        assembled_context: AIPolicyContextView,
    ) -> AgentExecutionBundle | None:
        """AI 호출 전 deterministic context만으로 종료 가능한 경우를 판정한다."""
        source_type = (assembled_context.source_type or "core").strip().lower()

        position_snapshot = assembled_context.position_snapshot
        has_position = (
            position_snapshot is not None
            and position_snapshot.quantity is not None
            and position_snapshot.quantity > 0
        )

        deterministic_trigger = assembled_context.deterministic_trigger
        if deterministic_trigger is None:
            return None

        envelope = evaluate_action_envelope(
            source_type=source_type,
            has_position=has_position,
        )
        if (
            source_type == "reconciliation_overlay"
            and not has_position
            and not envelope.allow_new_buy
        ):
            decision_type = (
                "WATCH" if bool(deterministic_trigger.watch_candidate) else "HOLD"
            )
            rationale = (
                "[pre_ai_short_circuit] source policy상 신규 진입 금지. "
                f"source_type={source_type} "
                f"reason_codes={','.join(envelope.reason_codes)} "
                f"이므로 AI 호출 없이 {decision_type}로 종료"
            )
            reason_codes = (
                "pre_ai_short_circuit",
                "source_policy_buy_blocked",
            ) + envelope.reason_codes
            compliance_result = self._build_compliance_validation_result(
                source_type=source_type,
                has_position=has_position,
                intent_action="new_buy",
                context_metadata={
                    "decision_type": decision_type,
                    "pre_ai_short_circuit": True,
                },
            )
            return self._build_short_circuit_agent_bundle(
                decision_type=decision_type,
                rationale=rationale,
                reason_codes=reason_codes,
                validation_result=compliance_result,
            )

        if source_type not in _PRE_AI_SHORT_CIRCUIT_SOURCE_TYPES:
            return None
        if has_position:
            return None

        eligibility_reasons = tuple(
            deterministic_trigger.eligibility_reasons or ()
        )
        blocking_reasons = tuple(
            reason
            for reason in eligibility_reasons
            if reason in _PRE_AI_ELIGIBILITY_BLOCK_REASONS
        )
        risk_off_exception_eligible = bool(
            getattr(deterministic_trigger, "risk_off_exception_eligible", False)
        )
        if blocking_reasons:
            residual_blocking_reasons = tuple(
                reason
                for reason in blocking_reasons
                if not (
                    reason == "eligibility_risk_off_block"
                    and risk_off_exception_eligible
                )
            )
            if not residual_blocking_reasons:
                return None
            decision_type = (
                "WATCH" if bool(deterministic_trigger.watch_candidate) else "HOLD"
            )
            rationale = (
                "[pre_ai_short_circuit] core 신규 진입 비적격 종목. "
                f"eligibility_reasons={','.join(residual_blocking_reasons)} "
                f"이므로 AI 호출 없이 {decision_type}로 종료"
            )
            reason_codes = ("pre_ai_short_circuit",) + residual_blocking_reasons
            validation_result = self._build_decision_policy_validation_result(
                blocking_rule_codes=reason_codes,
                rule_results={
                    "source_type": source_type,
                    "decision_type": decision_type,
                    "eligibility_reasons": residual_blocking_reasons,
                },
            )
            return self._build_short_circuit_agent_bundle(
                decision_type=decision_type,
                rationale=rationale,
                reason_codes=reason_codes,
                validation_result=validation_result,
            )

        primary_candidate = (
            getattr(deterministic_trigger, "primary_candidate", "") or ""
        ).strip().upper()
        if primary_candidate == "NO_ACTION" and not assembled_context.recent_events:
            rationale = (
                "[pre_ai_short_circuit] deterministic_trigger=NO_ACTION 이고 "
                "recent_events=0 이므로 AI 호출 없이 HOLD로 종료"
            )
            validation_result = self._build_decision_policy_validation_result(
                blocking_rule_codes=(
                    "pre_ai_short_circuit",
                    "pre_ai_no_action_no_event",
                ),
                rule_results={
                    "source_type": source_type,
                    "decision_type": "HOLD",
                    "recent_event_count": 0,
                },
            )
            return self._build_short_circuit_agent_bundle(
                decision_type="HOLD",
                rationale=rationale,
                reason_codes=(
                    "pre_ai_short_circuit",
                    "pre_ai_no_action_no_event",
                ),
                validation_result=validation_result,
            )

        return None

    async def assemble(
        self,
        request: SubmitOrderRequest,
        *,
        decision_context_id: UUID | None = None,
        order_intent_id: UUID | None = None,
        seeded_events: list[ExternalEventEntity] | None = None,
        decision_cycle_id: str | None = None,
    ) -> OrderIntent:
        """Assemble a structured order intent from a raw request.

        Parameters
        ----------
        request : SubmitOrderRequest
            The partially populated order request from the decision layer.
        decision_context_id : UUID | None
            The active decision context ID (P0 field). If not provided,
            the service resolves the most recent active context.
        order_intent_id : UUID | None
            The order intent ID (P1 field, optional). If not provided,
            a new UUID is generated.
        seeded_events : list[ExternalEventEntity] | None
            Transient seeded news events (T3) to inject alongside authoritative
            events. Passed from ``_run_one_cycle()`` — not persisted to DB.
        decision_cycle_id : str | None
            **진짜 cycle-scoped** 식별자(``request.correlation_id``는
            심볼별로 다른 값이라 이 용도로 쓰지 않는다) — FDC batch queue
            lifecycle shadow(Phase 1)가 같은 사이클의 FDC-ready job을
            묶는 데만 사용한다(``FdcReadyShadowEvent.decision_cycle_id``).

        Returns
        -------
        OrderIntent
            A structured intent with P1 fields and assembled context attached.
        """
        # --- Resolve or create active decision context ---
        # Ensures a valid decision_context_id exists before agent execution,
        # so that Postgres-backed agent run persistence works correctly.
        resolved_context_id = await self._ensure_or_create_decision_context(
            request, decision_context_id
        )

        # --- Resolve full DecisionContextEntity ---
        decision_context: DecisionContextEntity | None = None
        if resolved_context_id is not None:
            decision_context = await self._decision_context_service.resolve(
                resolved_context_id
            )

        # --- Resolve config version from decision context ---
        config_version: ConfigVersionEntity | None = None
        config_version_id: UUID | None = None
        if decision_context is not None and decision_context.config_version_id is not None:
            try:
                config_version = await self._repos.config_versions.get(
                    decision_context.config_version_id
                )
                if config_version is not None:
                    config_version_id = config_version.config_version_id
            except Exception:
                pass

        # --- Query recent external events (stub) ---
        recent_events: tuple[ExternalEventEntity, ...] = ()
        try:
            events = await self._repos.external_events.list_by_symbol(
                symbol=request.symbol,
                since=datetime.now(timezone.utc) - timedelta(hours=72),
                include_seeded_news=True,
            )
            events = list(events)

            # Inject seeded news events as lower-priority supplement
            # Dedup by event_id: seeded_events may overlap with list_by_symbol
            # results since both originate from external_events table.
            if seeded_events:
                existing_ids = {e.event_id for e in events}
                symbol_seeded = [
                    e for e in seeded_events
                    if e.symbol == request.symbol and e.event_id not in existing_ids
                ]
                if symbol_seeded:
                    events.extend(symbol_seeded)

            # Sort: importance desc → T1/T2 first → T3/T4 later → published_at desc
            events.sort(key=event_sort_key, reverse=True)
            recent_events = tuple(events)

            logger.info(
                "assemble() recent_events: symbol=%s count=%d "
                "(list_by_symbol=%d seeded_supplement=%d)",
                request.symbol,
                len(recent_events),
                len(events) - (len(symbol_seeded) if seeded_events else 0),
                len(symbol_seeded) if seeded_events else 0,
            )
        except Exception:
            logger.warning(
                "assemble() failed to query recent_events: symbol=%s",
                request.symbol,
                exc_info=True,
            )

        # --- Resolve instrument for position filtering ---
        instrument: InstrumentEntity | None = None
        try:
            instrument = await self._repos.instruments.get_by_symbol(
                symbol=request.symbol,
                market_code=request.market,
            )
            if instrument is None:
                instrument = await self._repos.instruments.get_by_symbol_any_market(
                    request.symbol
                )
        except Exception:
            pass

        # --- Query position snapshot ---
        # Priority:
        #   1. decision_context.position_snapshot_id → get(id) → accept regardless of
        #      instrument lookup success (strongest source of truth for replay).
        #   2. If no explicit ID, account latest snapshots → symbol-filter by instrument.
        position_snapshot: PositionSnapshotEntity | None = None
        if decision_context is not None:
            if decision_context.position_snapshot_id is not None:
                try:
                    pos = await self._repos.position_snapshots.get(
                        decision_context.position_snapshot_id
                    )
                    if pos is not None:
                        position_snapshot = pos
                except Exception:
                    pass
            if position_snapshot is None and decision_context.account_id is not None:
                try:
                    snaps = await self._repos.position_snapshots.list_latest_by_account(
                        decision_context.account_id
                    )
                    for s in snaps:
                        if instrument is not None and s.instrument_id == instrument.instrument_id:
                            position_snapshot = s
                            break
                except Exception:
                    pass

        # --- Query cash balance snapshot ---
        # Priority: decision_context.cash_balance_snapshot_id → account latest
        cash_balance_snapshot: CashBalanceSnapshotEntity | None = None
        if decision_context is not None:
            if decision_context.cash_balance_snapshot_id is not None:
                try:
                    cash_balance_snapshot = await self._repos.cash_balance_snapshots.get(
                        decision_context.cash_balance_snapshot_id
                    )
                except Exception:
                    pass
            if cash_balance_snapshot is None and decision_context.account_id is not None:
                try:
                    cash_balance_snapshot = await self._repos.cash_balance_snapshots.get_latest_by_account(
                        decision_context.account_id
                    )
                except Exception:
                    pass
            if decision_context.account_id is not None and (
                cash_balance_snapshot is None
                or cash_balance_snapshot.fetch_status != "success"
            ):
                replacement_cash = await self._select_usable_cash_snapshot(
                    decision_context.account_id,
                )
                if replacement_cash is not None:
                    cash_balance_snapshot = replacement_cash

        # --- Query risk limit snapshot ---
        risk_limit_snapshot: RiskLimitSnapshotEntity | None = None
        if decision_context is not None and decision_context.account_id is not None:
            try:
                risk_limit_snapshot = await self._repos.risk_limit_snapshots.get_latest_by_account(
                    decision_context.account_id
                )
            except Exception:
                pass

        derivation = await self._derive_deterministic_context_components(
            request=request,
            config_version=config_version,
            instrument=instrument,
            position_snapshot=position_snapshot,
            cash_balance_snapshot=cash_balance_snapshot,
            risk_limit_snapshot=risk_limit_snapshot,
            deterministic_trigger_override=self._extract_deterministic_trigger_override(
                request
            ),
            r3b_alpha_percentile=self._extract_r3b_alpha_percentile(request),
        )
        decision_context = await self._attach_signal_feature_snapshot_to_context(
            decision_context,
            derivation.signal_feature_snapshot,
        )
        decision_context = await self._attach_cash_balance_snapshot_to_context(
            decision_context,
            cash_balance_snapshot,
        )
        instrument_market_segment = self._extract_instrument_market_segment(
            instrument,
            request,
        )
        instrument_index_memberships = self._extract_instrument_index_memberships(
            instrument,
            request,
        )
        primary_index_membership = derive_primary_index_membership(
            instrument_index_memberships
        )

        # --- Assemble context (without score yet) ---
        assembled_context = AssembledContext(
            decision_context=decision_context,
            config_version=config_version,
            recent_events=recent_events,
            position_snapshot=position_snapshot,
            cash_balance_snapshot=cash_balance_snapshot,
            risk_limit_snapshot=risk_limit_snapshot,
            signal_feature_snapshot=derivation.signal_feature_snapshot,
            market_regime=derivation.market_regime,
            strategy_selection=derivation.strategy_selection,
            portfolio_allocation=derivation.portfolio_allocation,
            deterministic_trigger=derivation.deterministic_trigger,
            instrument_market_segment=instrument_market_segment,
            instrument_index_memberships=instrument_index_memberships,
            primary_index_membership=primary_index_membership,
            source_type=derivation.source_type,
        )

        # --- Calculate score ---
        score_result = await self._score_calculator.calculate(assembled_context)

        # --- Rebuild context with score ---
        assembled_context = AssembledContext(
            decision_context=decision_context,
            config_version=config_version,
            recent_events=recent_events,
            score=score_result,
            position_snapshot=position_snapshot,
            cash_balance_snapshot=cash_balance_snapshot,
            risk_limit_snapshot=risk_limit_snapshot,
            signal_feature_snapshot=derivation.signal_feature_snapshot,
            market_regime=derivation.market_regime,
            strategy_selection=derivation.strategy_selection,
            portfolio_allocation=derivation.portfolio_allocation,
            deterministic_trigger=derivation.deterministic_trigger,
            instrument_market_segment=instrument_market_segment,
            instrument_index_memberships=instrument_index_memberships,
            primary_index_membership=primary_index_membership,
            source_type=derivation.source_type,
        )

        # --- Generate order_intent_id if not provided ---
        resolved_intent_id = order_intent_id or uuid4()

        # --- Generate correlation_id if not provided ---
        correlation_id = request.correlation_id
        if not correlation_id:
            correlation_id = str(uuid4())

        # --- Run AI agents → persistence bundle + normalised backend inputs ---
        # Phase 4: subprocess isolation — when enabled, agents run in a separate
        # subprocess with SIGKILL-guaranteed timeout.  When disabled (tests),
        # the original in-process _run_agents() is used.
        ai_policy_context = self._build_ai_policy_context_view(assembled_context)

        # Build shared AgentExecutionRequest for the agent runner wrappers.
        agent_request = AgentExecutionRequest(
            decision_context_id=resolved_context_id,
            correlation_id=correlation_id,
            context=ai_policy_context,
            symbol=request.symbol,
            market=request.market,
            source_type=assembled_context.source_type,
        )
        short_circuit_bundle = self._evaluate_pre_agent_short_circuit(
            assembled_context=ai_policy_context,
        )
        if short_circuit_bundle is not None:
            agent_bundle = short_circuit_bundle
            _fdc_run_id = None
            logger.info(
                "Pre-agent short-circuit applied: symbol=%s source_type=%s "
                "decision_type=%s reason_codes=%s",
                request.symbol,
                assembled_context.source_type,
                agent_bundle.ai_inputs.decision_type,
                agent_bundle.ai_inputs.reason_codes,
            )
        elif self._use_subprocess_isolation:
            agent_bundle = await self._run_agents_in_subprocess(
                request=agent_request,
                assembled_context=ai_policy_context,
            )
            # ── Phase 5.6: Rehydrate AgentRunEntity records from subprocess output ──
            # The subprocess path does NOT call recorder.record() internally
            # (unlike _run_agents()).  We rehydrate here so that AgentRuns
            # persistence works identically for both paths.
            _fdc_run_id = await self._rehydrate_subprocess_agent_runs(
                resolved_context_id=resolved_context_id,
                agent_bundle=agent_bundle,
            )
        else:
            agent_bundle = await self._run_agents(
                request=agent_request,
                assembled_context=ai_policy_context,
            )
            # In-process path: _run_agents() already calls recorder.record()
            # internally, so we extract the FDC run_id from the recorder's
            # in-memory buffer for _ensure_trade_decision linkage.
            _fdc_run_id = None
            try:
                _recent = await self._agent_recorder.list_by_decision_context(
                    resolved_context_id
                ) if resolved_context_id else []
                if _recent:
                    _fdc_run_id = _recent[0].agent_run_id
            except Exception:
                pass

        # ── Held position sell override ──
        # 보유 포지션(held_position) 종목에 대해 AI risk가 강한 부정 신호를 보내면
        # FDC의 HOLD/APPROVE/BUY 결정을 REDUCE/EXIT sell로 override한다.
        # recording 이후, _ensure_trade_decision() 이전에 수행하여
        # override된 값이 DB에 저장되도록 한다.
        # held_position_fdc_skip_shadow 관측(assemble() 최말단)이 override
        # 적용 *이전* FDC 원본 출력과 비교할 수 있도록, override로
        # composer_output이 mutate되기 직전 값을 미리 캡처해 둔다.
        _fdc_raw_decision_type = (
            agent_bundle.composer_output.decision_type
            if agent_bundle.composer_output is not None
            else None
        )
        self._apply_held_position_sell_override(
            agent_bundle=agent_bundle,
            assembled_context=assembled_context,
            derivation=derivation,
            symbol=request.symbol,
        )

        source_policy_guard = self._check_source_policy_upgrade_guard(
            source_type=derivation.source_type,
            deterministic_trigger=derivation.deterministic_trigger,
            fdc_output=agent_bundle.composer_output,
            position_snapshot=position_snapshot,
        )
        if source_policy_guard is not None:
            guarded_dt, guard_rationale, guard_reason_codes = source_policy_guard
            validation_result = (
                self._build_compliance_validation_result(
                    source_type=derivation.source_type,
                    has_position=(
                        position_snapshot is not None
                        and position_snapshot.quantity is not None
                        and position_snapshot.quantity > 0
                    ),
                    intent_action="new_buy",
                    context_metadata={"guarded_decision_type": guarded_dt},
                )
                if "source_policy_guard" in guard_reason_codes
                or any(code.startswith("policy_") for code in guard_reason_codes)
                else self._build_decision_policy_validation_result(
                    blocking_rule_codes=guard_reason_codes,
                    rule_results={
                        "source_type": derivation.source_type,
                        "guarded_decision_type": guarded_dt,
                    },
                )
            )
            object.__setattr__(agent_bundle.ai_inputs, "decision_type", guarded_dt)
            object.__setattr__(agent_bundle.ai_inputs, "side", "")
            self._apply_validation_result_to_ai_inputs(
                agent_bundle.ai_inputs,
                validation_result=validation_result,
            )
            existing_reason_codes = tuple(agent_bundle.ai_inputs.reason_codes or ())
            merged_reason_codes = tuple(
                dict.fromkeys(existing_reason_codes + guard_reason_codes)
            )
            object.__setattr__(
                agent_bundle.ai_inputs,
                "reason_codes",
                merged_reason_codes,
            )
            if agent_bundle.composer_output is not None:
                object.__setattr__(agent_bundle.composer_output, "decision_type", guarded_dt)
                object.__setattr__(agent_bundle.composer_output, "side", "")
                composer_reason_codes = tuple(agent_bundle.composer_output.reason_codes or ())
                merged_composer_reason_codes = tuple(
                    dict.fromkeys(composer_reason_codes + guard_reason_codes)
                )
                object.__setattr__(
                    agent_bundle.composer_output,
                    "reason_codes",
                    merged_composer_reason_codes,
                )
                fdc_summary = agent_bundle.composer_output.summary
                object.__setattr__(
                    agent_bundle.composer_output,
                    "summary",
                    (fdc_summary + f" | {guard_rationale}") if fdc_summary else guard_rationale,
                )
            logger.info(
                "Source policy upgrade guard: symbol=%s source_type=%s rationale=%s",
                request.symbol,
                derivation.source_type,
                guard_rationale,
            )

        watch_guard = self._check_watch_candidate_upgrade_guard(
            source_type=derivation.source_type,
            deterministic_trigger=derivation.deterministic_trigger,
            fdc_output=agent_bundle.composer_output,
            position_snapshot=position_snapshot,
        )
        if watch_guard is not None:
            guarded_dt, guard_rationale = watch_guard
            validation_result = self._build_decision_policy_validation_result(
                blocking_rule_codes=("watch_candidate_guard",),
                rule_results={
                    "source_type": derivation.source_type,
                    "guarded_decision_type": guarded_dt,
                },
            )
            object.__setattr__(agent_bundle.ai_inputs, "decision_type", guarded_dt)
            object.__setattr__(agent_bundle.ai_inputs, "side", "")
            self._apply_validation_result_to_ai_inputs(
                agent_bundle.ai_inputs,
                validation_result=validation_result,
            )
            existing_reason_codes = tuple(agent_bundle.ai_inputs.reason_codes or ())
            if "watch_candidate_guard" not in existing_reason_codes:
                object.__setattr__(
                    agent_bundle.ai_inputs,
                    "reason_codes",
                    existing_reason_codes + ("watch_candidate_guard",),
                )
            if agent_bundle.composer_output is not None:
                object.__setattr__(agent_bundle.composer_output, "decision_type", guarded_dt)
                object.__setattr__(agent_bundle.composer_output, "side", "")
                composer_reason_codes = tuple(agent_bundle.composer_output.reason_codes or ())
                if "watch_candidate_guard" not in composer_reason_codes:
                    object.__setattr__(
                        agent_bundle.composer_output,
                        "reason_codes",
                        composer_reason_codes + ("watch_candidate_guard",),
                    )
                fdc_summary = agent_bundle.composer_output.summary
                object.__setattr__(
                    agent_bundle.composer_output,
                    "summary",
                    (fdc_summary + f" | {guard_rationale}") if fdc_summary else guard_rationale,
                )
            logger.info(
                "Watch candidate upgrade guard: symbol=%s source_type=%s rationale=%s",
                request.symbol,
                derivation.source_type,
                guard_rationale,
            )

        held_position_exit_gate = await self._check_held_position_exit_hysteresis_gate(
            source_type=derivation.source_type,
            fdc_output=agent_bundle.composer_output,
            ai_inputs=agent_bundle.ai_inputs,
            risk_output=agent_bundle.risk_output,
            decision_context=decision_context,
            instrument=instrument,
            position_snapshot=position_snapshot,
        )
        if held_position_exit_gate is not None:
            guarded_dt, guard_rationale, guard_reason_codes = held_position_exit_gate
            validation_result = self._build_decision_policy_validation_result(
                blocking_rule_codes=guard_reason_codes,
                rule_results={
                    "source_type": derivation.source_type,
                    "guarded_decision_type": guarded_dt,
                },
            )
            object.__setattr__(agent_bundle.ai_inputs, "decision_type", guarded_dt)
            object.__setattr__(agent_bundle.ai_inputs, "side", "")
            self._apply_validation_result_to_ai_inputs(
                agent_bundle.ai_inputs,
                validation_result=validation_result,
            )
            existing_reason_codes = tuple(agent_bundle.ai_inputs.reason_codes or ())
            merged_reason_codes = tuple(
                dict.fromkeys(existing_reason_codes + guard_reason_codes)
            )
            object.__setattr__(
                agent_bundle.ai_inputs,
                "reason_codes",
                merged_reason_codes,
            )
            if agent_bundle.composer_output is not None:
                object.__setattr__(agent_bundle.composer_output, "decision_type", guarded_dt)
                object.__setattr__(agent_bundle.composer_output, "side", "")
                composer_reason_codes = tuple(agent_bundle.composer_output.reason_codes or ())
                merged_composer_reason_codes = tuple(
                    dict.fromkeys(composer_reason_codes + guard_reason_codes)
                )
                object.__setattr__(
                    agent_bundle.composer_output,
                    "reason_codes",
                    merged_composer_reason_codes,
                )
                fdc_summary = agent_bundle.composer_output.summary
                object.__setattr__(
                    agent_bundle.composer_output,
                    "summary",
                    (fdc_summary + f" | {guard_rationale}") if fdc_summary else guard_rationale,
                )
            logger.info(
                "Held position exit hysteresis gate: symbol=%s source_type=%s rationale=%s",
                request.symbol,
                derivation.source_type,
                guard_rationale,
            )

        buy_eligibility_guard = self._check_buy_eligibility_upgrade_guard(
            source_type=derivation.source_type,
            deterministic_trigger=derivation.deterministic_trigger,
            fdc_output=agent_bundle.composer_output,
            position_snapshot=position_snapshot,
        )
        if buy_eligibility_guard is not None:
            guarded_dt, guard_rationale = buy_eligibility_guard
            validation_result = self._build_decision_policy_validation_result(
                blocking_rule_codes=("buy_eligibility_guard",),
                rule_results={
                    "source_type": derivation.source_type,
                    "guarded_decision_type": guarded_dt,
                },
            )
            object.__setattr__(agent_bundle.ai_inputs, "decision_type", guarded_dt)
            object.__setattr__(agent_bundle.ai_inputs, "side", "")
            self._apply_validation_result_to_ai_inputs(
                agent_bundle.ai_inputs,
                validation_result=validation_result,
            )
            existing_reason_codes = tuple(agent_bundle.ai_inputs.reason_codes or ())
            if "buy_eligibility_guard" not in existing_reason_codes:
                object.__setattr__(
                    agent_bundle.ai_inputs,
                    "reason_codes",
                    existing_reason_codes + ("buy_eligibility_guard",),
                )
            if agent_bundle.composer_output is not None:
                object.__setattr__(agent_bundle.composer_output, "decision_type", guarded_dt)
                object.__setattr__(agent_bundle.composer_output, "side", "")
                composer_reason_codes = tuple(agent_bundle.composer_output.reason_codes or ())
                if "buy_eligibility_guard" not in composer_reason_codes:
                    object.__setattr__(
                        agent_bundle.composer_output,
                        "reason_codes",
                        composer_reason_codes + ("buy_eligibility_guard",),
                    )
                fdc_summary = agent_bundle.composer_output.summary
                object.__setattr__(
                    agent_bundle.composer_output,
                    "summary",
                    (fdc_summary + f" | {guard_rationale}") if fdc_summary else guard_rationale,
                )
            logger.info(
                "Buy eligibility upgrade guard: symbol=%s source_type=%s rationale=%s",
                request.symbol,
                derivation.source_type,
                guard_rationale,
            )

        ai_override_gate = await self._check_ai_buy_override_gate(
            source_type=derivation.source_type,
            deterministic_trigger=derivation.deterministic_trigger,
            fdc_output=agent_bundle.composer_output,
            ai_inputs=agent_bundle.ai_inputs,
            position_snapshot=position_snapshot,
            decision_context=decision_context,
            instrument=instrument,
        )
        if ai_override_gate is not None:
            guarded_dt, guard_rationale, guard_reason_codes = ai_override_gate
            validation_result = self._build_decision_policy_validation_result(
                blocking_rule_codes=guard_reason_codes,
                rule_results={
                    "source_type": derivation.source_type,
                    "guarded_decision_type": guarded_dt,
                },
            )
            object.__setattr__(agent_bundle.ai_inputs, "decision_type", guarded_dt)
            object.__setattr__(agent_bundle.ai_inputs, "side", "")
            self._apply_validation_result_to_ai_inputs(
                agent_bundle.ai_inputs,
                validation_result=validation_result,
            )
            existing_reason_codes = tuple(agent_bundle.ai_inputs.reason_codes or ())
            merged_reason_codes = tuple(
                dict.fromkeys(existing_reason_codes + guard_reason_codes)
            )
            object.__setattr__(
                agent_bundle.ai_inputs,
                "reason_codes",
                merged_reason_codes,
            )
            if agent_bundle.composer_output is not None:
                object.__setattr__(agent_bundle.composer_output, "decision_type", guarded_dt)
                object.__setattr__(agent_bundle.composer_output, "side", "")
                composer_reason_codes = tuple(agent_bundle.composer_output.reason_codes or ())
                merged_composer_reason_codes = tuple(
                    dict.fromkeys(composer_reason_codes + guard_reason_codes)
                )
                object.__setattr__(
                    agent_bundle.composer_output,
                    "reason_codes",
                    merged_composer_reason_codes,
                )
                fdc_summary = agent_bundle.composer_output.summary
                object.__setattr__(
                    agent_bundle.composer_output,
                    "summary",
                    (fdc_summary + f" | {guard_rationale}") if fdc_summary else guard_rationale,
                )
            logger.info(
                "AI override gate blocked: symbol=%s source_type=%s rationale=%s",
                request.symbol,
                derivation.source_type,
                guard_rationale,
            )

        # --- EV gate near-miss 조건부 완화 (SPPV-2.87/2.88, 기본값 False) ---
        # 전역 threshold나 EV 계산 로직은 전혀 바꾸지 않는다. 판정 자체는
        # 순수 함수 resolve_ev_gate_near_miss_override()에 위임한다.
        _deterministic_reason_codes = tuple(
            getattr(derivation.deterministic_trigger, "reason_codes", ()) or ()
        )
        (
            _near_miss_applied,
            _near_miss_deficit_bps,
            _near_miss_threshold_bps,
        ) = resolve_ev_gate_near_miss_override(
            enabled=self._ev_gate_near_miss_override_enabled,
            decision_type=agent_bundle.ai_inputs.decision_type,
            expected_value_gate_passed=agent_bundle.ai_inputs.expected_value_gate_passed,
            source_type=derivation.source_type,
            minimum_required_edge_bps=agent_bundle.ai_inputs.minimum_required_edge_bps,
            edge_after_cost_bps=agent_bundle.ai_inputs.edge_after_cost_bps,
            deterministic_trigger_reason_codes=_deterministic_reason_codes,
        )
        if _near_miss_applied:
            object.__setattr__(
                agent_bundle.ai_inputs,
                "ev_gate_near_miss_override_applied",
                True,
            )
            object.__setattr__(
                agent_bundle.ai_inputs,
                "ev_gate_near_miss_deficit_bps",
                _near_miss_deficit_bps,
            )
            object.__setattr__(
                agent_bundle.ai_inputs,
                "ev_gate_near_miss_threshold_bps",
                _near_miss_threshold_bps,
            )
            logger.info(
                "EV gate near-miss override applied: symbol=%s "
                "deficit_bps=%s threshold_bps=%s",
                request.symbol,
                _near_miss_deficit_bps,
                _near_miss_threshold_bps,
            )

        # --- Persist or reuse trade decision when a concrete context exists ---
        td_entity = await self._ensure_trade_decision(
            decision_context_id=resolved_context_id,
            request=request,
            assembled_context=assembled_context,
            agent_bundle=agent_bundle,
            instrument=instrument,
            fdc_run_id=_fdc_run_id,
        )
        if td_entity is not None:
            trade_decision_id = td_entity.trade_decision_id
        else:
            trade_decision_id = None

        # --- Loss-cut shadow 관측 (관측 전용 — 이 시점 이후 decision_type/side
        # 를 mutate하는 코드는 없으므로, 여기서 관측해도 실주문 판단에 영향 없음) ---
        await self._record_loss_cut_shadow_observation(
            trade_decision_id=trade_decision_id,
            position_snapshot=assembled_context.position_snapshot,
            source_type=assembled_context.source_type,
            composer_output=agent_bundle.composer_output,
        )

        # --- AR/EI shadow bot 관측 (관측 전용, loss_cut_shadow와 동일 원칙 —
        # 이 시점 이후 decision_type/side/주문 수량을 mutate하는 코드는
        # 없으므로 여기서 관측해도 실주문 판단에 영향 없음) ---
        await self._record_ar_shadow_bot_observation(
            trade_decision_id=trade_decision_id,
            assembled_context=assembled_context,
            ai_policy_context=ai_policy_context,
            ar_output=agent_bundle.risk_output,
            composer_output=agent_bundle.composer_output,
        )
        await self._record_ei_shadow_bot_observation(
            trade_decision_id=trade_decision_id,
            assembled_context=assembled_context,
            event_output=agent_bundle.event_output,
        )
        await self._record_held_position_fdc_skip_shadow_observation(
            trade_decision_id=trade_decision_id,
            assembled_context=assembled_context,
            ar_output=agent_bundle.risk_output,
            composer_output=agent_bundle.composer_output,
            fdc_raw_decision_type=_fdc_raw_decision_type,
            fdc_skipped=agent_bundle.ai_inputs.fdc_skipped,
        )
        await self._record_held_position_reduce_skip_shadow_observation(
            trade_decision_id=trade_decision_id,
            assembled_context=assembled_context,
            ar_output=agent_bundle.risk_output,
            composer_output=agent_bundle.composer_output,
            fdc_raw_decision_type=_fdc_raw_decision_type,
        )
        self._capture_fdc_ready_shadow_event(
            decision_cycle_id=decision_cycle_id,
            assembled_context=assembled_context,
            symbol=request.symbol,
            resolved_context_id=resolved_context_id,
            fdc_ready_at_raw=agent_bundle.ai_inputs.fdc_ready_at,
        )

        # --- Generate decision_id if not provided ---
        decision_id = request.decision_id
        if trade_decision_id is not None:
            decision_id = str(trade_decision_id)
        elif not decision_id:
            decision_id = str(uuid4())

        # --- Assemble the final SubmitOrderRequest ---
        assembled_request = SubmitOrderRequest(
            client_order_id=request.client_order_id,
            correlation_id=correlation_id,
            account_ref=request.account_ref,
            symbol=request.symbol,
            market=request.market,
            side=request.side,
            order_type=request.order_type,
            time_in_force=request.time_in_force,
            quantity=request.quantity,
            price=request.price,
            decision_id=decision_id,
            strategy_id=request.strategy_id,
            idempotency_key=request.idempotency_key,
            price_band_lower=request.price_band_lower,
            price_band_upper=request.price_band_upper,
            max_slippage_bps=request.max_slippage_bps,
            allow_partial_fill=request.allow_partial_fill,
            decision_context_id=str(resolved_context_id) if resolved_context_id else None,
            order_intent_id=str(resolved_intent_id),
            client_timestamp=request.client_timestamp,
            metadata=request.metadata,
        )

        # --- REDUCE/EXIT + sell side override ---
        # FDC가 REDUCE/EXIT + side="sell"을 결정하면, assembled_request.side를
        # OrderSide.SELL로 오버라이드한다. BUY/APPROVE decision_type일 때는
        # side가 오버라이드되지 않도록 조건 검사.
        fdc_side = agent_bundle.ai_inputs.side if agent_bundle else ""
        if agent_bundle.ai_inputs.decision_type in ("REDUCE", "EXIT") and fdc_side.lower() == OrderSide.SELL.value:
            assembled_request = replace(assembled_request, side=OrderSide.SELL)

        assembled_metadata = dict(assembled_request.metadata or {})
        signal_feature_snapshot_id = (
            str(assembled_context.signal_feature_snapshot.signal_feature_snapshot_id)
            if assembled_context.signal_feature_snapshot is not None
            else (
                str(assembled_context.decision_context.signal_feature_snapshot_id)
                if assembled_context.decision_context is not None
                and assembled_context.decision_context.signal_feature_snapshot_id is not None
                else None
            )
        )
        current_symbol_state = None
        if (
            assembled_context.decision_context is not None
            and instrument is not None
        ):
            current_symbol_state = await self._repos.symbol_trade_states.get_by_account_and_instrument(
                assembled_context.decision_context.account_id,
                instrument.instrument_id,
            )
        holding_profile_policy = derive_holding_profile_policy(
            source_type=assembled_context.source_type,
            decision_type=agent_bundle.ai_inputs.decision_type,
            side=agent_bundle.ai_inputs.side or assembled_request.side,
            time_horizon=(
                agent_bundle.composer_output.time_horizon
                if agent_bundle.composer_output is not None
                else None
            ),
            quantity=assembled_request.quantity,
            max_order_value=calculate_max_order_value(
                assembled_request.price,
                assembled_request.quantity,
            ),
            signal_feature_snapshot_id=signal_feature_snapshot_id,
            reason_codes=agent_bundle.ai_inputs.reason_codes,
        )
        assembled_metadata["holding_profile_policy"] = serialize_holding_profile_policy(
            holding_profile_policy
        )
        assembled_metadata["expected_value_anchor"] = self._build_expected_value_anchor_metadata(
            ai_inputs=agent_bundle.ai_inputs,
            source_type=assembled_context.source_type,
            decision_type=agent_bundle.ai_inputs.decision_type,
            symbol_state=current_symbol_state,
        )
        assembled_request = replace(assembled_request, metadata=assembled_metadata)

        return OrderIntent(
            decision_context_id=resolved_context_id,
            order_intent_id=resolved_intent_id,
            request=assembled_request,
            context=assembled_context,
            config_version_id=config_version_id,
            reason_codes=score_result.reason_codes,
            ai_backend_inputs=agent_bundle.ai_inputs,
            trade_decision_id=trade_decision_id,
        )

    # ------------------------------------------------------------------
    # Full pipeline: assemble → validate → create_order → submit_order
    # ------------------------------------------------------------------

    async def assemble_and_submit(
        self,
        request: SubmitOrderRequest,
        *,
        order_manager: OrderManager,
        broker: BrokerAdapter,
        decision_context_id: UUID | None = None,
        order_intent_id: UUID | None = None,
        seeded_events: list[ExternalEventEntity] | None = None,
        actor_type: str = "system",
        actor_id: str = "decision_orchestrator",
        decision_cycle_id: str | None = None,
    ) -> SubmitResult:
        """Execute the full AI decision → order submit pipeline.

        This is the **primary entry point** for paper trading.  It chains:

        1. ``assemble()`` → runs EI/AR/FDC agents, persists ``TradeDecisionEntity``,
           returns ``OrderIntent``.
        2. ``build_submit_order_request_from_decision()`` → validates the intent
           and builds a ``SubmitOrderRequest`` (or signals ``SKIPPED`` when the
           decision is HOLD).
        3. ``OrderManager.create_order()`` → validates, persists a ``DRAFT`` order.
        4. ``OrderManager.transition_to(PENDING_SUBMIT)`` → moves the order to
           submit-ready state.
        5. ``OrderManager.submit_order_to_broker()`` → blocking lock check,
           broker submission, result handling (SUBMITTED / RECONCILE_REQUIRED /
           REJECTED).

        Parameters
        ----------
        request : SubmitOrderRequest
            Initial order request (minimal fields — side, symbol, market, etc.).
        order_manager : OrderManager
            Fully configured ``OrderManager`` with repository and reconciliation
            service wired in.
        broker : BrokerAdapter
            The broker adapter to submit orders through.
        decision_context_id : UUID | None
            Optional explicit decision context ID.  Auto-resolved when ``None``.
        order_intent_id : UUID | None
            Optional explicit order intent ID.  Auto-generated when ``None``.
        seeded_events : list[ExternalEventEntity] | None
            Transient seeded news events (T3) to inject into assemble context.
        actor_type, actor_id :
            Identity used for audit-log entries.

        Returns
        -------
        SubmitResult
            Structured result with status, intent, order, and error details.
        """
        # ── Phase trace accumulator (EXE-001) ──
        _phase_start = time_module.monotonic()
        _phase_trace: list[PhaseTraceEntry] = []

        def _add_phase(phase: str, status: str) -> None:
            """현재 단계 추적을 기록하고 타이머를 재설정한다."""
            nonlocal _phase_start
            now = time_module.monotonic()
            elapsed = int((now - _phase_start) * 1000)
            _phase_trace.append(PhaseTraceEntry(phase=phase, elapsed_ms=elapsed, status=status))
            _phase_start = now

        # ── Phase 1: Decision pipeline (AI assemble → TD resolve) ──
        intent, trade_decision_id, pipeline_result = await self._run_decision_pipeline(
            request,
            decision_context_id=decision_context_id,
            order_intent_id=order_intent_id,
            seeded_events=seeded_events,
            decision_cycle_id=decision_cycle_id,
            _add_phase=_add_phase,
            _phase_trace=_phase_trace,
        )
        if pipeline_result is not None:
            return pipeline_result

        # ── Phase 1.5–5.5: Execution pipeline (sizing → guard → translate → create → submit) ──
        return await self._execution_service.run_execution_pipeline(
            intent,
            trade_decision_id,
            request,
            order_manager,
            broker,
            actor_type=actor_type,
            actor_id=actor_id,
            _add_phase=_add_phase,
            _phase_trace=_phase_trace,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------


    async def _run_decision_pipeline(
        self,
        request: SubmitOrderRequest,
        *,
        decision_context_id: UUID | None = None,
        order_intent_id: UUID | None = None,
        seeded_events: list[ExternalEventEntity] | None = None,
        decision_cycle_id: str | None = None,
        _add_phase: Callable[[str, str], None],
        _phase_trace: list[PhaseTraceEntry],
    ) -> tuple[OrderIntent | None, UUID | None, SubmitResult | None]:
        """Decision pipeline: AI assemble → TD resolve.

        Returns ``(intent, trade_decision_id, None)`` on success,
        or ``(None, None, submit_result)`` on error (caller should return
        the ``submit_result`` immediately).

        Note
        ----
        ``ExecutionAttemptEntity`` creation has moved to
        ``ExecutionService.run_execution_pipeline()``.
        """
        _symbol = request.symbol
        _add_phase("ai_assemble", "start")
        logger.info(
            "PHASE_TRACE symbol=%s phase=assemble_start elapsed_ms=0 status=start",
            _symbol,
        )
        _assemble_t0 = time_module.monotonic()
        logger.info("Phase 1: assemble() — running AI agents …")
        try:
            intent = await self.assemble(
                request,
                decision_context_id=decision_context_id,
                order_intent_id=order_intent_id,
                seeded_events=seeded_events,
                decision_cycle_id=decision_cycle_id,
            )
            _assemble_elapsed = time_module.monotonic() - _assemble_t0
            logger.info(
                "PHASE_TRACE symbol=%s phase=assemble_done elapsed_ms=%d status=ok",
                _symbol, int(_assemble_elapsed * 1000),
            )
            _add_phase("ai_assemble", "ok")
        except asyncio.TimeoutError:
            logger.error(
                "Phase 1 TIMEOUT: assemble() exceeded timeout. "
                "decision_context_id=%s symbol=%s",
                decision_context_id,
                request.symbol,
            )
            return None, None, SubmitResult(
                status="ERROR",
                error_phase="ai_timeout",
                error_message=f"assemble() timed out for symbol={request.symbol}",
                decision_context_id=decision_context_id,
            )
        except Exception as exc:
            logger.exception(
                "Phase 1 FAILED (ai): assemble() raised unexpectedly. "
                "decision_context_id=%s",
                decision_context_id,
            )
            return None, None, SubmitResult(
                status="ERROR",
                error_phase="ai",
                error_message=f"assemble() failed: {exc}",
                decision_context_id=decision_context_id,
            )

        # trade_decision_id is already stored on the intent by assemble()
        trade_decision_id = intent.trade_decision_id

        # NOTE: ExecutionAttemptEntity creation has moved to
        # ExecutionService.run_execution_pipeline().

        return intent, trade_decision_id, None






    # ------------------------------------------------------------------
    # AI Agent execution — thin wrappers delegating to DecisionAgentRunner
    # ------------------------------------------------------------------

    async def _run_agents(
        self,
        request: AgentExecutionRequest,
        assembled_context: AIPolicyContextView,
    ) -> AgentExecutionBundle:
        """Thin wrapper — delegates to DecisionAgentRunner.run_agents()."""
        return await self._agent_runner.run_agents(
            request=request,
            assembled_context=assembled_context,
        )

    # ------------------------------------------------------------------
    # Phase 4: Subprocess isolation for agent calls — thin wrapper
    # ------------------------------------------------------------------

    async def _run_agents_in_subprocess(
        self,
        request: AgentExecutionRequest,
        assembled_context: AIPolicyContextView,
    ) -> AgentExecutionBundle:
        """Thin wrapper — delegates to DecisionAgentRunner.run_agents_in_subprocess()."""
        return await self._agent_runner.run_agents_in_subprocess(
            request=request,
            assembled_context=assembled_context,
        )

    async def _rehydrate_subprocess_agent_runs(
        self,
        *,
        resolved_context_id: UUID | None,
        agent_bundle: AgentExecutionBundle,
    ) -> UUID | None:
        """subprocess 결과로부터 4개 AgentRunEntity를 rehydrate한다.

        subprocess 경로(``_run_agents_in_subprocess``)는 내부에서
        ``recorder.record()``를 호출하지 않으므로(in-process 경로인
        ``_run_agents()``와 달리), 여기서 EI/AR/AC/FDC 4개를 모두
        기록해야 두 경로의 ``agent_runs`` 영속화 결과가 동일해진다.

        2026-08-16 수정: 이전에는 EI/AR/FDC 3개만 기록하고 AC(AI
        Compliance) record가 누락되어 있었다(subprocess rehydrate
        누락 버그) — ``agent_runs``에 ``ai_compliance`` row가 전혀
        쌓이지 않던 원인이 이것이었다. AC가 deterministic bot으로
        전환된 지금은 4개 모두 기록한다.
        """
        fdc_run_id: UUID | None = None
        try:
            # ★ subprocess 경로: EI 실패 시 error metadata를 __error__로 주입
            ei_structured = dataclass_to_dict(agent_bundle.event_output)
            if agent_bundle.ei_error_metadata is not None:
                ei_structured["__error__"] = agent_bundle.ei_error_metadata
            await self._agent_recorder.record(
                decision_context_id=resolved_context_id,
                agent_type=self._event_interpretation_agent.agent_name,
                structured_output=ei_structured,
            )
            await self._agent_recorder.record(
                decision_context_id=resolved_context_id,
                agent_type=self._ai_risk_agent.agent_name,
                structured_output=dataclass_to_dict(agent_bundle.risk_output),
            )
            await self._agent_recorder.record(
                decision_context_id=resolved_context_id,
                agent_type=self._ai_compliance_agent.agent_name,
                structured_output=dataclass_to_dict(agent_bundle.compliance_output),
            )
            # 2026-08-21: strict FDC rate limiter + retry-inclusive permit
            # 관측성 메타데이터를 FDC structured_output에 side-channel로
            # 주입한다 — EI의 ``__error__`` 주입과 동일한 패턴이다.
            # ``FinalDecisionComposerOutput`` 자체(LLM 응답 스키마)는
            # 건드리지 않는다.
            fdc_structured = dataclass_to_dict(agent_bundle.composer_output)
            if agent_bundle.provider_observability is not None:
                fdc_structured["__provider_observability__"] = (
                    agent_bundle.provider_observability
                )
            fdc_run = await self._agent_recorder.record(
                decision_context_id=resolved_context_id,
                agent_type=self._final_decision_agent.agent_name,
                structured_output=fdc_structured,
            )
            fdc_run_id = fdc_run.agent_run_id
            logger.info(
                'Rehydrated %d agent runs from subprocess output '
                '(decision_context_id=%s fdc_run_id=%s)',
                4, resolved_context_id, fdc_run_id,
            )
        except Exception:
            logger.warning(
                'Failed to rehydrate agent runs from subprocess output — '
                'AgentRuns will be missing for this cycle. '
                'decision_context_id=%s',
                resolved_context_id,
                exc_info=True,
            )
        return fdc_run_id
