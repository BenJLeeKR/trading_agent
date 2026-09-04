from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol
from uuid import UUID

from agent_trading.domain.entities import (
    AccountEntity,
    AgentRunEntity,
    AuditLogEntity,
    BlockingLockEntity,
    BrokerAccountEntity,
    BrokerFillSnapshotEntity,
    BrokerOrderEntity,
    CashBalanceSnapshotEntity,
    ClientEntity,
    ConfigVersionEntity,
    DecisionContextEntity,
    ExecutionAttemptEntity,
    ExternalEventEntity,
    FillEventEntity,
    FillSyncRunEntity,
    GuardrailEvaluationEntity,
    HistoricalBuyFeeOverlayEntity,
    HistoricalSellFeeTaxOverlayEntity,
    InstrumentEntity,
    InstrumentIndexMembershipEntity,
    InstrumentStatusSnapshotEntity,
    KisFillCumulativeStateEntity,
    MarketSessionEntity,
    OrderRequestEntity,
    OrderSubmissionAttemptEntity,
    OrderStateEventEntity,
    PositionCostBasisStateEntity,
    PositionSnapshotEntity,
    ReconciliationOrderLinkEntity,
    ReconciliationPositionLinkEntity,
    ReconciliationRunEntity,
    RealizedPnlComputationRunEntity,
    RealizedPnlDailyAggregateEntity,
    RealizedPnlEventEntity,
    RealizedPnlRecomputeQueueEntity,
    RiskLimitSnapshotEntity,
    SignalFeatureSnapshotEntity,
    SignalFeatureBatchRunEntity,
    SignalFeatureBatchRunItemEntity,
    SessionEventEntity,
    SnapshotSyncRunEntity,
    StrategyEntity,
    SymbolTradeStateEntity,
    TradeDecisionEntity,
    UniverseFreezeRunEntity,
    UniverseFreezeRunItemEntity,
)
from agent_trading.domain.enums import (
    Environment,
    OrderStatus,
    RealizedPnlComputationRunType,
)
from agent_trading.repositories.filters import AccountLookup, DecisionContextQuery, OrderQuery


@dataclass(slots=True, frozen=True)
class SnapshotSyncHealthSummary:
    """Freshness/health summary for the most recent snapshot sync runs.

    Computed by :meth:`SnapshotSyncRunRepository.get_sync_health_summary`.
    """

    last_run_started_at: datetime | None
    """``started_at`` of the most recent run, or ``None`` if no runs exist."""

    last_run_completed_at: datetime | None
    """``completed_at`` of the most recent run, or ``None`` if no runs exist."""

    last_status: str | None
    """``status`` of the most recent run (e.g. ``"completed"``, ``"failed"``)."""

    last_successful_run_at: datetime | None
    """``started_at`` of the most recent ``status == 'completed'`` run."""

    consecutive_failures: int
    """Number of consecutive ``status == 'failed'`` runs (reverse chronological)."""

    is_stale: bool
    """``True`` when ``now - last_successful_run_at > stale_threshold_seconds``."""

    stale_threshold_seconds: int
    """The threshold used for the staleness computation."""

    after_hours: bool = False
    """``True`` when the most recent run was an after-hours (cash-only) sync."""


@dataclass(slots=True, frozen=True)
class FillSyncHealthSummary:
    """Freshness/health summary for the most recent fill sync runs."""

    last_run_started_at: datetime | None
    last_run_completed_at: datetime | None
    last_status: str | None
    last_successful_run_at: datetime | None
    consecutive_failures: int
    is_stale: bool
    stale_threshold_seconds: int
    retried_accounts: int = 0
    retried_days: int = 0
    total_retries: int = 0


@dataclass(slots=True, frozen=True)
class TradeDecisionRow:
    """TradeDecisionEntity + resolved fields from LEFT JOINs.

    ``entity`` contains the full ``TradeDecisionEntity``.
    ``order_request_id`` / ``order_status`` are resolved via
    ``LEFT JOIN trading.order_requests``.
    ``instrument_name`` is resolved via ``LEFT JOIN trading.instruments``.
    ``phase_trace`` is the raw JSONB column from ``execution_attempts``
    (resolved via ``LEFT JOIN LATERAL`` at the row level).
    """

    entity: TradeDecisionEntity
    order_request_id: str | None = None
    order_status: str | None = None
    instrument_name: str | None = None
    phase_trace: list[dict[str, object]] | None = None
    """Raw phase_trace JSONB from ``execution_attempts``
    (resolved via ``LEFT JOIN LATERAL`` in ``list_all_paginated()``).
    """

    execution_attempt_status: str | None = None
    """Status of the latest ``ExecutionAttemptEntity`` for this trade decision,
    resolved via ``LEFT JOIN LATERAL`` on ``trading.execution_attempts``.

    ``None`` when no execution attempt exists yet.
    """

    latest_execution_attempt_id: str | None = None
    """ID of the latest ``ExecutionAttemptEntity`` for this trade decision,
    resolved via ``LEFT JOIN LATERAL`` on ``trading.execution_attempts``.

    ``None`` when no execution attempt exists yet.
    """

    latest_stop_phase: str | None = None
    """Stop phase of the latest ``ExecutionAttemptEntity`` for this trade decision,
    resolved via ``LEFT JOIN LATERAL`` on ``trading.execution_attempts``.

    ``None`` when no execution attempt exists yet.
    """

    latest_stop_reason: str | None = None
    """Stop reason of the latest ``ExecutionAttemptEntity`` for this trade decision,
    resolved via ``LEFT JOIN LATERAL`` on ``trading.execution_attempts``.

    ``None`` when no execution attempt exists yet.
    """

    latest_completed_at: datetime | None = None
    """Completed-at timestamp of the latest ``ExecutionAttemptEntity`` for this trade decision,
    resolved via ``LEFT JOIN LATERAL`` on ``trading.execution_attempts``.

    ``None`` when no execution attempt exists yet.
    """

    latest_phase_count: int | None = None
    """Number of phases in the latest ``ExecutionAttemptEntity`` for this trade decision,
    resolved via ``LEFT JOIN LATERAL`` (``jsonb_array_length(ea.phase_trace)``).

    ``None`` when no execution attempt exists yet.
    """
    signal_feature_snapshot_id: str | None = None
    """Point-in-time decision_context anchor to ``signal_feature_snapshots``."""


@dataclass(frozen=True, slots=True)
class CoreEligibilitySample:
    """UNIV-5 shadow: `core` 종목 1건의 최종 eligibility 판정 표본.

    ``core`` 동적 강등(demotion) shadow 관측 전용 — day-level 집계(같은
    거래일에 여러 decision이 있어도 그 날 1회로 취급)는 호출자
    (``UniverseSelectionService``)가 수행한다. 이 row 자체는 원시 표본이다.
    """

    symbol: str
    created_at: datetime
    last_eligibility_reason: str | None
    """``decision_json.deterministic_trigger.eligibility_reasons``의 마지막
    원소. ``eligibility_low_relative_activity``인지 여부만 shadow 판정에
    쓰인다."""


@dataclass(frozen=True, slots=True)
class LossCutShadowObservationRow:
    """``decision_json.loss_cut_shadow`` 관측 1건의 inspection용 원시 표본.

    이 row 자체는 이미 기록된 값을 그대로 옮긴 것뿐이다 — 여기서 어떤
    계산도 하지 않는다(집계는 호출자인 API route가 수행).
    ``account_id``는 ``decision_contexts`` JOIN으로 resolve된 값이다
    (``trade_decisions`` 테이블 자체에는 ``account_id`` 컬럼이 없음).
    """

    trade_decision_id: UUID
    decision_context_id: UUID
    account_id: UUID
    created_at: datetime
    symbol: str
    source_type: str
    actual_decision_type: str
    """관측 당시 실제 결정(``trade_decisions.decision_type``) — shadow
    판정과 무관하게 실제로 내려진 결정 그대로다."""
    loss_cut_shadow: dict[str, object]
    """``decision_json.loss_cut_shadow``를 그대로 담은 dict(``account_id``/
    ``instrument_id``/``average_price``/``market_price``/``loss_pct``/
    ``triggered``/``tier``/``skipped_reason``/``shadow_only`` 등)."""


class ClientRepository(Protocol):
    async def add(self, client: ClientEntity) -> ClientEntity:
        ...

    async def get(self, client_id: UUID) -> ClientEntity | None:
        ...

    async def get_by_code(self, client_code: str) -> ClientEntity | None:
        ...

    async def list_all(self) -> Sequence[ClientEntity]:
        ...


class BrokerAccountRepository(Protocol):
    async def add(self, broker_account: BrokerAccountEntity) -> BrokerAccountEntity:
        ...

    async def get(self, broker_account_id: UUID) -> BrokerAccountEntity | None:
        ...

    async def get_by_ref(
        self,
        broker_name: str,
        account_ref: str,
        environment: Environment,
    ) -> BrokerAccountEntity | None:
        ...

    async def list_by_broker(self, broker_name: str) -> Sequence[BrokerAccountEntity]:
        ...

    async def list_by_broker_and_env(
        self,
        broker_name: str,
        env: Environment,
    ) -> Sequence[BrokerAccountEntity]:
        """List broker accounts filtered by broker name and environment."""
        ...

    async def list_by_account_id(
        self,
        account_id: UUID,
    ) -> Sequence[BrokerAccountEntity]:
        """List broker accounts linked to the given account ID.

        Uses a JOIN with ``trading.accounts`` to resolve
        ``account_id → broker_account_id``.

        Parameters
        ----------
        account_id : UUID
            The account whose broker accounts to list.

        Returns
        -------
        Sequence[BrokerAccountEntity]
            Matching broker accounts (usually 0 or 1 per account).
        """
        ...


class AccountRepository(Protocol):
    async def add(self, account: AccountEntity) -> AccountEntity:
        ...

    async def get(self, account_id: UUID) -> AccountEntity | None:
        ...

    async def find_one(self, lookup: AccountLookup) -> AccountEntity | None:
        ...

    async def list_by_client(self, client_id: UUID) -> Sequence[AccountEntity]:
        ...

    async def update_metadata(
        self,
        account_id: UUID,
        *,
        account_masked: str | None = None,
    ) -> AccountEntity | None:
        """Update mutable metadata fields on an existing account.

        Currently supports ``account_masked`` only.  Returns the updated
        ``AccountEntity``, or ``None`` if the account does not exist.
        """
        ...


class StrategyRepository(Protocol):
    async def add(self, strategy: StrategyEntity) -> StrategyEntity:
        ...

    async def get(self, strategy_id: UUID) -> StrategyEntity | None:
        ...

    async def get_by_code(self, client_id: UUID, strategy_code: str) -> StrategyEntity | None:
        ...


class ConfigVersionRepository(Protocol):
    """Store for configuration version snapshots.

    ConfigVersion records freeze the configuration state at a point in time.
    This is a replay-critical repository — ``get_active()`` and
    ``get_active_at()`` are used to restore the configuration that was
    active at a given time during replay.
    """

    async def add(self, config_version: ConfigVersionEntity) -> ConfigVersionEntity:
        ...

    async def get(self, config_version_id: UUID) -> ConfigVersionEntity | None:
        ...

    async def get_active(
        self, client_id: UUID, environment: Environment
    ) -> ConfigVersionEntity | None:
        ...

    async def get_active_at(
        self, client_id: UUID, environment: Environment, at: datetime
    ) -> ConfigVersionEntity | None:
        """Return the config version that was active at the given timestamp.

        Selects the most recently activated version where ``activated_at <= at``.
        Returns ``None`` if no version was activated before the given timestamp.

        This is critical for replay: to reconstruct the system state at a
        specific point in time, we need the config that was governing at that time.
        """
        ...


class InstrumentRepository(Protocol):
    async def add(self, instrument: InstrumentEntity) -> InstrumentEntity:
        ...

    async def get(self, instrument_id: UUID) -> InstrumentEntity | None:
        ...

    async def get_by_symbol(self, symbol: str, market_code: str) -> InstrumentEntity | None:
        ...

    async def get_by_symbol_any_market(self, symbol: str) -> InstrumentEntity | None:
        """Lookup instrument by symbol across all markets.

        Returns the first matching instrument regardless of market,
        or ``None`` if not found.  Used when the caller does not know
        the market code (e.g. lock enrichment).
        """
        ...

    async def get_by_symbols_any_market(
        self, symbols: Sequence[str]
    ) -> dict[str, InstrumentEntity]:
        """Batch variant of ``get_by_symbol_any_market`` — one query for many
        symbols instead of one query per symbol (avoids N+1 when resolving a
        seed-symbol list, e.g. market-overlay seed pool resolution)."""
        ...

    async def get_many(
        self, instrument_ids: Sequence[UUID]
    ) -> dict[UUID, InstrumentEntity]:
        """Batch lookup — avoids N+1 when enriching a list of rows.

        Returns a dict keyed by ``instrument_id``; missing ids are simply
        absent from the result (never raises for unknown ids). Empty input
        returns an empty dict without a query.
        """
        ...

    async def upsert_by_symbol(self, instrument: InstrumentEntity) -> InstrumentEntity:
        """INSERT … ON CONFLICT (symbol, market_code) DO UPDATE … RETURNING *.

        If a row with the same ``(symbol, market_code)`` already exists,
        update its mutable fields and return the updated row.  Otherwise
        insert a new row.

        The caller is responsible for generating ``instrument_id`` when
        inserting a new instrument.  On conflict, the existing PK is
        preserved.
        """
        ...

    async def list_active_by_market(
        self, market_code: str, *, asset_class: str | None = None
    ) -> Sequence[InstrumentEntity]:
        """List all active instruments for a given market code.

        This is the primary method used by ``UniverseSelectionService``
        to build the Core Universe.  Returns only ``is_active=true``
        instruments, ordered by symbol.

        ``asset_class``: optional filter (e.g. ``"kr_stock"``) — when
        omitted (default), all asset classes are returned, matching the
        historical behavior relied on by ``sync_kis_instrument_master.py``'s
        deactivate-missing pass. ``UniverseSelectionService`` passes
        ``"kr_stock"`` explicitly so ETF/ETN rows never enter Core Universe
        composition (they were never eligible; excluding them at the query
        level also avoids scanning/scoring rows the caller would filter out
        anyway).
        """
        ...


class DecisionContextRepository(Protocol):
    async def add(self, context: DecisionContextEntity) -> DecisionContextEntity:
        ...

    async def get(self, decision_context_id: UUID) -> DecisionContextEntity | None:
        ...

    async def get_many(
        self, decision_context_ids: Sequence[UUID]
    ) -> dict[UUID, DecisionContextEntity]:
        """Batch lookup — avoids N+1 when enriching a list of trade decisions."""
        ...

    async def get_by_correlation_id(self, correlation_id: str) -> DecisionContextEntity | None:
        ...

    async def list(self, query: DecisionContextQuery) -> Sequence[DecisionContextEntity]:
        ...

    async def attach_signal_feature_snapshot(
        self,
        decision_context_id: UUID,
        signal_feature_snapshot_id: UUID,
    ) -> DecisionContextEntity | None:
        ...

    async def attach_cash_balance_snapshot(
        self,
        decision_context_id: UUID,
        cash_balance_snapshot_id: UUID,
    ) -> DecisionContextEntity | None:
        ...


class PositionSnapshotRepository(Protocol):
    async def add(self, snapshot: PositionSnapshotEntity) -> PositionSnapshotEntity:
        ...

    async def get(self, position_snapshot_id: UUID) -> PositionSnapshotEntity | None:
        ...

    async def list_latest_by_account(self, account_id: UUID) -> Sequence[PositionSnapshotEntity]:
        ...

    async def get_latest_by_account_and_instrument_before(
        self,
        account_id: UUID,
        instrument_id: UUID,
        before: datetime,
    ) -> PositionSnapshotEntity | None:
        """Return the most recent position snapshot for a given account and
        instrument whose ``snapshot_at`` is strictly before ``before``.

        Returns ``None`` if no such snapshot exists.
        """
        ...

    async def get_earliest_by_account_and_instrument_after(
        self,
        account_id: UUID,
        instrument_id: UUID,
        after: datetime,
    ) -> PositionSnapshotEntity | None:
        """Return the earliest position snapshot strictly after ``after``."""
        ...

    async def list_by_sync_run(
        self, account_id: UUID, sync_run_id: UUID,
    ) -> Sequence[PositionSnapshotEntity]:
        """Return all position snapshots for an account that were created
        during a specific snapshot sync run.

        Parameters
        ----------
        account_id:
            대상 계좌 UUID.
        sync_run_id:
            ``snapshot_sync_run_id`` FK 값.

        Returns
        -------
        Sequence[PositionSnapshotEntity]
            해당 sync run에 속한 position snapshot 목록.
        """
        ...

    async def get_latest_sync_run_id(
        self, account_id: UUID,
    ) -> UUID | None:
        """Return the latest ``snapshot_sync_run_id`` recorded for the
        given account (from any snapshot), or ``None`` if no FK data exists.

        Parameters
        ----------
        account_id:
            대상 계좌 UUID.

        Returns
        -------
        UUID | None
            가장 최신 ``snapshot_sync_run_id``. FK가 전혀 없으면 ``None``.
        """
        ...


class CashBalanceSnapshotRepository(Protocol):
    async def add(self, snapshot: CashBalanceSnapshotEntity) -> CashBalanceSnapshotEntity:
        ...

    async def get(self, cash_balance_snapshot_id: UUID) -> CashBalanceSnapshotEntity | None:
        ...

    async def get_latest_by_account(self, account_id: UUID) -> CashBalanceSnapshotEntity | None:
        ...

    async def get_latest_with_orderable_amount(
        self, account_id: UUID,
    ) -> CashBalanceSnapshotEntity | None:
        """계좌의 ``orderable_amount``가 ``NOT NULL``인 가장 최근 snapshot 1건을 반환합니다.

        ``_build_cash_balance_view()``의 백필 fallback 전용 조회다.
        최신 snapshot의 ``orderable_amount``가 ``NULL``일 때(예: 장 마감 후
        `orderable_amount`를 갱신하지 않는 경로), 화면에 보여줄 "가장 최근
        유효했던 주문가능금액" 하나만 필요하다 — 계좌의 전체 현금 이력을
        ``list_by_account()``로 다 읽어 Python에서 첫 non-null 값을 찾던
        방식은 이력이 많은 계좌에서 매 요청마다 수천 행을 왕복시키는
        비용이 크므로, DB에서 ``LIMIT 1``로 직접 걸러 받는다.

        Parameters
        ----------
        account_id:
            대상 계좌 UUID.

        Returns
        -------
        CashBalanceSnapshotEntity | None
            ``orderable_amount``가 있는 가장 최근 snapshot. 없으면 ``None``.
        """
        ...

    async def list_by_account(self, account_id: UUID) -> Sequence[CashBalanceSnapshotEntity]:
        """계좌의 모든 현금 snapshot을 snapshot_at DESC 정렬로 반환합니다.

        Parameters
        ----------
        account_id:
            대상 계좌 UUID.

        Returns
        -------
        Sequence[CashBalanceSnapshotEntity]
            snapshot_at 내림차순 정렬된 snapshot 목록.
            데이터가 없으면 빈 시퀀스.
        """
        ...

    async def get_by_sync_run(
        self, account_id: UUID, sync_run_id: UUID,
    ) -> CashBalanceSnapshotEntity | None:
        """Return the cash balance snapshot for an account that was created
        during a specific snapshot sync run.

        Parameters
        ----------
        account_id:
            대상 계좌 UUID.
        sync_run_id:
            ``snapshot_sync_run_id`` FK 값.

        Returns
        -------
        CashBalanceSnapshotEntity | None
            해당 sync run에 속한 cash balance snapshot. 없으면 ``None``.
        """
        ...

    async def get_latest_sync_run_id(
        self, account_id: UUID,
    ) -> UUID | None:
        """Return the latest ``snapshot_sync_run_id`` recorded for the
        given account (from any cash snapshot), or ``None`` if no FK data
        exists.

        Parameters
        ----------
        account_id:
            대상 계좌 UUID.

        Returns
        -------
        UUID | None
            가장 최신 ``snapshot_sync_run_id``. FK가 전혀 없으면 ``None``.
        """
        ...


class TradeDecisionRepository(Protocol):
    async def add(self, decision: TradeDecisionEntity) -> TradeDecisionEntity:
        ...

    async def get(self, trade_decision_id: UUID) -> TradeDecisionEntity | None:
        ...

    async def get_by_context(self, decision_context_id: UUID) -> TradeDecisionEntity | None:
        """최신 TD 반환 (ORDER BY created_at DESC, trade_decision_id DESC LIMIT 1).

        동일 decision_context_id에 여러 TD가 존재할 수 있으므로,
        가장 최근에 생성된 TD를 반환합니다.
        Tie-break: created_at DESC, trade_decision_id DESC.
        """
        ...

    async def list_by_context(self, decision_context_id: UUID) -> list[TradeDecisionEntity]:
        """주어진 decision_context에 속한 모든 TD를 최신순으로 반환."""
        ...

    async def list_all(self) -> Sequence[TradeDecisionEntity]:
        ...

    async def list_all_paginated(
        self,
        limit: int = 50,
        offset: int = 0,
        decision_context_id: UUID | None = None,
        created_date_kst: date | None = None,
        side: str | None = None,
        source_type: str | None = None,
        decision_type: str | None = None,
        execution_status: str | None = None,
        latest_stop_reason: str | None = None,
        latest_stop_reason_prefix: str | None = None,
        has_order: bool | None = None,
    ) -> tuple[list[TradeDecisionRow], int]:
        """서버사이드 페이지네이션: (items, total_count) 반환.

        각 item은 ``TradeDecisionRow`` (entity + order_request_id + order_status).
        ``instrument_name``은 SQL LEFT JOIN으로 한 번에 resolve (N+1 방지).

        ``decision_context_id``가 주어지면 해당 컨텍스트로 필터링.
        ``limit``: 페이지당 최대 row 수 (기본 50).
        ``offset``: 건너뛸 row 수.
        반환값: (해당 페이지의 TradeDecisionRow 리스트, 조건에 맞는 전체 row 수).
        """
        ...

    async def sync_execution_sizing(
        self,
        trade_decision_id: UUID,
        *,
        quantity: Decimal,
        max_order_value: Decimal | None,
        target_notional: Decimal | None,
        execution_sizing_payload: dict[str, object],
    ) -> TradeDecisionEntity | None:
        """Execution 단계의 deterministic sizing 결과를 TD에 반영한다."""
        ...

    async def sync_loss_cut_shadow_observation(
        self,
        trade_decision_id: UUID,
        *,
        loss_cut_shadow_payload: dict[str, object],
    ) -> TradeDecisionEntity | None:
        """Loss-cut **shadow 관측** 결과를 TD의 ``decision_json['loss_cut_
        shadow']``에 추가한다(관측 전용 — 다른 어떤 컬럼도 건드리지
        않는다).

        ``sync_execution_sizing()``과 같은 append-only jsonb 패치 패턴을
        따르되, 그 메서드와 달리 ``quantity``/``max_order_value``/
        ``target_notional`` 컬럼은 전혀 쓰지 않는다 — 이 메서드는 순수하게
        관측 metadata만 얹는다(``docs/00_foundational_design/detailed_
        design/13_loss_cut_policy_specification_and_config_path_
        design.md`` §3.6 shadow 단계).
        """
        ...

    async def sync_shadow_risk_bot_observation(
        self,
        trade_decision_id: UUID,
        *,
        shadow_risk_bot_payload: dict[str, object],
    ) -> TradeDecisionEntity | None:
        """AR(``ai_risk``) **shadow 관측** 결과를 TD의 ``decision_json[
        'shadow_risk_bot']``에 추가한다(관측 전용 — 다른 어떤 컬럼도
        건드리지 않는다). ``sync_loss_cut_shadow_observation()``과 동일한
        append-only jsonb 패치 패턴을 따른다.
        """
        ...

    async def sync_shadow_event_bot_observation(
        self,
        trade_decision_id: UUID,
        *,
        shadow_event_bot_payload: dict[str, object],
    ) -> TradeDecisionEntity | None:
        """EI(``event_interpretation``) **shadow 관측** 결과를 TD의
        ``decision_json['shadow_event_bot']``에 추가한다(관측 전용).
        """
        ...

    async def sync_shadow_held_position_fdc_skip_observation(
        self,
        trade_decision_id: UUID,
        *,
        shadow_held_position_fdc_skip_payload: dict[str, object],
    ) -> TradeDecisionEntity | None:
        """``held_position`` FDC 호출 **shadow-skip 관측** 결과를 TD의
        ``decision_json['shadow_held_position_fdc_skip']``에 추가한다
        (관측 전용 — 다른 어떤 컬럼도 건드리지 않는다). ``sync_shadow_
        risk_bot_observation()``과 동일한 append-only jsonb 패치 패턴을
        따른다.
        """
        ...

    async def sync_shadow_held_position_reduce_skip_observation(
        self,
        trade_decision_id: UUID,
        *,
        shadow_held_position_reduce_skip_payload: dict[str, object],
    ) -> TradeDecisionEntity | None:
        """``held_position`` REDUCE/SELL_CANDIDATE **shadow-skip 관측**
        결과를 TD의 ``decision_json['shadow_held_position_reduce_skip']``
        에 추가한다(관측 전용 — 다른 어떤 컬럼도 건드리지 않는다).
        ``sync_shadow_held_position_fdc_skip_observation()``과 동일한
        append-only jsonb 패치 패턴을 따르되 별도 key를 쓴다.
        """
        ...

    async def list_loss_cut_shadow_observations(
        self,
        account_id: UUID,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        source_type: str | None = None,
        triggered: bool | None = None,
        tier: str | None = None,
        symbol: str | None = None,
        before: datetime | None = None,
        limit: int | None = None,
    ) -> Sequence[LossCutShadowObservationRow]:
        """``decision_json.loss_cut_shadow``가 기록된 TD를 최신순으로 조회한다.

        읽기 전용 inspection 전용 메서드다 — 계산·집계는 전혀 하지 않고,
        이미 저장된 값을 필터링해 그대로 반환한다(집계는 호출자인 API
        route가 수행). ``account_id``는 ``decision_contexts`` JOIN으로
        resolve한다(``list_recent_core_eligibility_reasons()``와 동일한
        join 경로). ``start_date``/``end_date``는 KST 기준
        ``created_at`` 날짜에 적용한다. ``before``는 ``created_at`` 기준
        cursor pagination용(``before`` 이전 행만). ``limit``이 ``None``이면
        건수 제한 없이 전부 반환한다(summary 집계용).
        """
        ...

    async def list_recent_core_eligibility_reasons(
        self,
        account_id: UUID,
        symbols: Sequence[str],
        business_date_from: date,
        business_date_to: date,
    ) -> Sequence[CoreEligibilitySample]:
        """UNIV-5 shadow: `core` 종목의 최근 eligibility 판정 표본을 조회한다.

        ``core`` 동적 강등(demotion) shadow 관측 전용 — 순수 read 경로이며
        universe 선정/BUY 게이트 어디에도 영향을 주지 않는다.
        ``source_type='core'``, 주어진 ``symbols`` 목록, 날짜 범위(KST
        기준)로 필터링한 원시 표본을 반환한다. day-level dedup·streak 계산은
        호출자가 수행한다.
        """
        ...

class OrderRepository(Protocol):
    async def add(self, order: OrderRequestEntity) -> OrderRequestEntity:
        ...

    async def get(self, order_request_id: UUID) -> OrderRequestEntity | None:
        ...

    async def get_by_client_order_id(self, client_order_id: str) -> OrderRequestEntity | None:
        ...

    async def list(self, query: OrderQuery) -> Sequence[OrderRequestEntity]:
        ...

    async def count(self, query: OrderQuery) -> int:
        ...

    async def count_by_status(self, query: OrderQuery) -> dict[str, int]:
        ...

    async def update_status(
        self,
        order_request_id: UUID,
        status: OrderStatus,
        reason_code: str | None = None,
        reason_message: str | None = None,
        expected_version: int | None = None,
        submitted_at: datetime | None = None,
    ) -> None:
        ...


class BrokerOrderRepository(Protocol):
    async def add(self, broker_order: BrokerOrderEntity) -> BrokerOrderEntity:
        ...

    async def get_by_native_order_id(
        self,
        broker_name: str,
        broker_native_order_id: str,
    ) -> BrokerOrderEntity | None:
        ...

    async def list_by_order_request(self, order_request_id: UUID) -> Sequence[BrokerOrderEntity]:
        ...

    async def get(self, broker_order_id: UUID) -> BrokerOrderEntity | None:
        """Get a single broker order by its internal UUID.

        Parameters
        ----------
        broker_order_id:
            The internal ``BrokerOrderEntity.broker_order_id``.

        Returns
        -------
        BrokerOrderEntity | None
            The matching entity, or ``None`` if not found.
        """
        ...

    async def update(
        self,
        broker_order_id: UUID,
        *,
        broker_status: str | None = None,
        last_synced_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        """Update mutable fields on a BrokerOrderEntity.

        Parameters
        ----------
        broker_order_id:
            The UUID of the broker order to update.
        broker_status:
            New broker-side order status (e.g. ``"FILLED"``, ``"CANCELLED"``).
        last_synced_at:
            Timestamp of the last successful sync with the broker.
        updated_at:
            Timestamp of this update.  If not provided, the repository
            may set it to the current time.

        The entity is frozen (immutable), so implementations MUST
        use ``dataclasses.replace()`` internally.
        """
        ...


class FillEventRepository(Protocol):
    async def add(self, fill_event: FillEventEntity) -> FillEventEntity:
        ...

    async def list_by_broker_order(self, broker_order_id: UUID) -> Sequence[FillEventEntity]:
        ...

    async def get_by_broker_fill_id(self, broker_fill_id: str) -> FillEventEntity | None:
        """Look up a fill event by its broker-native fill identifier.

        ``broker_fill_id`` is unique per ``(broker_order_id, broker_fill_id)``
        (DB constraint ``uq_fill_events_native``).  Since the same
        ``broker_fill_id`` could theoretically appear under a different
        ``broker_order_id``, callers should verify the ``broker_order_id``
        match after retrieval.
        """
        ...


class FillSyncRunRepository(Protocol):
    async def add(self, run: FillSyncRunEntity) -> FillSyncRunEntity:
        ...

    async def list_runs(
        self,
        limit: int = 50,
        trigger_type: str | None = None,
        status: str | None = None,
    ) -> Sequence[FillSyncRunEntity]:
        ...

    async def get(self, run_id: UUID) -> FillSyncRunEntity | None:
        ...

    async def update_run(self, run: FillSyncRunEntity) -> FillSyncRunEntity:
        ...

    async def get_sync_health_summary(
        self,
        stale_threshold_seconds: int = 1800,
    ) -> FillSyncHealthSummary:
        ...


class BrokerFillSnapshotRepository(Protocol):
    async def upsert(self, snapshot: BrokerFillSnapshotEntity) -> BrokerFillSnapshotEntity:
        ...

    async def list_recent(
        self,
        *,
        limit: int = 200,
        account_id: UUID | None = None,
        order_date: date | None = None,
        order_request_id: UUID | None = None,
        symbol: str | None = None,
        broker_native_order_id: str | None = None,
    ) -> Sequence[BrokerFillSnapshotEntity]:
        ...

    async def list_recent_by_order_ids(
        self, order_request_ids: Sequence[UUID], *, limit_per_order: int = 20
    ) -> dict[UUID, list[BrokerFillSnapshotEntity]]:
        """Batch fill lookup for multiple orders — avoids N+1 when enriching
        a list of orders with their most recent fills.

        Returns a dict keyed by ``order_request_id``, each value newest-first
        and capped at ``limit_per_order``. Orders with no fills are simply
        absent from the result. Empty input returns an empty dict without a
        query.
        """
        ...


class KisFillCumulativeStateRepository(Protocol):
    """계좌×브로커주문번호 단위 KIS 누적 체결량 관측 상태 저장소.

    설계 근거: docs/00_foundational_design/detailed_design/14_kis_fill_
    normalization_and_incremental_interpretation_design.md 3.2절(안 C).
    ``fill_events``의 대체가 아니라, 누적→증분 해석의 기준점을 프로세스
    재시작에도 안전하게 보관하는 보조 상태다.
    """

    async def get(
        self,
        *,
        account_id: UUID,
        broker_name: str,
        broker_native_order_id: str,
    ) -> KisFillCumulativeStateEntity | None:
        """마지막으로 저장된 누적 관측 상태를 조회한다. 없으면 ``None``."""
        ...

    async def upsert(
        self, state: KisFillCumulativeStateEntity
    ) -> KisFillCumulativeStateEntity:
        """``(account_id, broker_name, broker_native_order_id)`` 단위로
        upsert한다. Postgres 구현은 이 호출을 단일 행 잠금(``SELECT ...
        FOR UPDATE`` 또는 동등한 원자적 upsert)으로 감싸 동시 폴러 간
        경쟁 조건을 막아야 한다(설계 문서 3.2절 "1차 방어선")."""
        ...


class PositionCostBasisStateRepository(Protocol):
    """계좌×종목 단위 이동평균 매입원가 상태 저장소.

    ``(account_id, instrument_id)``가 PK다. 실시간 반영/replay 계산 엔진이
    다음에 적용할 fill을 결정하기 위해 현재 상태를 조회·갱신하는 용도다.
    """

    async def get(
        self, account_id: UUID, instrument_id: UUID
    ) -> PositionCostBasisStateEntity | None:
        ...

    async def upsert(
        self, state: PositionCostBasisStateEntity
    ) -> PositionCostBasisStateEntity:
        ...

    async def list_recompute_required(
        self, limit: int = 100
    ) -> Sequence[PositionCostBasisStateEntity]:
        """재계산 대기(``recompute_required=True``) 상태를 오래된 순으로 반환한다."""
        ...

    async def list_by_account(
        self, account_id: UUID
    ) -> Sequence[PositionCostBasisStateEntity]:
        """계좌의 모든 계좌×종목 상태를 종목 필터 없이 반환한다.

        Inspection API가 ``instrument_id`` 없이 계좌 전체의 realized PnL
        종목 누계를 나열할 때 사용한다(조회 전용, read path 추가).
        """
        ...


class RealizedPnlEventRepository(Protocol):
    """매도 체결 기준 append-only 실현 손익 원장 저장소."""

    async def add(self, event: RealizedPnlEventEntity) -> RealizedPnlEventEntity:
        ...

    async def upsert(self, event: RealizedPnlEventEntity) -> RealizedPnlEventEntity:
        """``fill_event_id`` 기준으로 upsert한다(recompute/replay 전용).

        ``realized_pnl_event_id``는 ``fill_event_id``로부터 결정론적으로
        파생되므로(``realized_pnl_engine._derive_realized_pnl_event_id``),
        같은 fill을 다시 계산해 upsert해도 새 행이 생기지 않고 같은 행의
        계산값(``sell_quantity``/``sell_price``/``avg_cost_basis_before``/
        ``fee``/``tax``/``fee_tax_source``/``realized_pnl_gross``/
        ``realized_pnl_net``/``position_quantity_after``/``computation_run_id``)
        만 다시 쓴다. ``created_at``/``superseded_by_event_id``는 건드리지
        않는다. 실시간 반영 경로(``RealizedPnlLedgerService.apply_fill``)는
        여전히 ``add()``만 사용한다 — 이 메서드는 out-of-order 등으로
        과거에 잘못 계산된 값을 replay로 다시 정확하게 쓰는 recompute
        경로 전용이다.
        """
        ...

    async def get_by_fill_event_id(
        self, fill_event_id: UUID
    ) -> RealizedPnlEventEntity | None:
        """``fill_event_id`` UNIQUE 제약을 전제로 한 idempotency 조회다."""
        ...

    async def list_by_account_and_instrument(
        self,
        account_id: UUID,
        instrument_id: UUID,
        *,
        limit: int = 200,
        before: datetime | None = None,
    ) -> Sequence[RealizedPnlEventEntity]:
        """``fill_timestamp`` 최신순으로 반환한다.

        ``before``가 주어지면 그 시각보다 이전인 이벤트만 반환한다(페이지네이션).
        """
        ...

    async def list_by_account_and_instrument_since(
        self,
        account_id: UUID,
        instrument_id: UUID,
        *,
        since: datetime,
        limit: int = 20,
    ) -> Sequence[RealizedPnlEventEntity]:
        """``fill_timestamp >= since``인 이벤트를 오름차순(가장 오래된

        것부터)으로 반환한다 — loss-cut shadow sample 이후 실제로 어떤
        realized event가 이어졌는지 시간순으로 보기 위한 read-only
        조회다. ``list_by_account_and_instrument()``(최신순, ``before``
        커서)와는 정렬 방향과 경계 조건이 반대다 — 계산은 하지 않는다.
        """
        ...

    async def list_by_account(
        self,
        account_id: UUID,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> Sequence[RealizedPnlEventEntity]:
        """계좌의 모든 종목에 대한 realized_pnl_events를 종목 필터 없이

        단일 조회로 반환한다(``RealizedPnlDailyAggregateRepository.
        list_by_account()``와 동일한 목적 — 종목마다 반복 조회하는 N+1을
        피하기 위함). ``start_date``/``end_date``는 ``fill_timestamp``를
        KST 날짜로 변환한 값 기준이다(``realized_pnl_ledger_service.
        to_kst_trade_date()``와 동일 정책). 설계 문서 12번 13절의
        ``provenance_breakdown`` 집계 전용 경로이며, 계산은 하지 않는다
        — 정렬 순서도 보장하지 않는다.
        """
        ...


class RealizedPnlDailyAggregateRepository(Protocol):
    """조회 성능용 일자 집계 캐시 저장소.

    ``realized_pnl_events``에서 언제든 재생성 가능한 파생 데이터를 담는다.
    """

    async def upsert(
        self, aggregate: RealizedPnlDailyAggregateEntity
    ) -> RealizedPnlDailyAggregateEntity:
        ...

    async def list_by_account_and_instrument(
        self,
        account_id: UUID,
        instrument_id: UUID,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> Sequence[RealizedPnlDailyAggregateEntity]:
        """``trade_date`` 오름차순으로 반환한다."""
        ...

    async def list_by_account(
        self,
        account_id: UUID,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> Sequence[RealizedPnlDailyAggregateEntity]:
        """계좌의 모든 종목에 대한 일자 집계를 종목 필터 없이 단일 조회로 반환한다.

        ``GET /performance/realized-pnl/summary``(종목 "전체" 조회)가
        종목마다 :meth:`list_by_account_and_instrument`를 반복 호출하는
        N+1을 피하기 위한 전용 경로다. 정렬 순서는 보장하지 않는다 —
        호출자가 ``instrument_id``/``trade_date``별로 다시 묶어야 한다.
        """
        ...


class RealizedPnlComputationRunRepository(Protocol):
    """실현 손익 ledger 실시간 반영/백필 실행 이력 저장소."""

    async def add(
        self, run: RealizedPnlComputationRunEntity
    ) -> RealizedPnlComputationRunEntity:
        ...

    async def update_run(
        self, run: RealizedPnlComputationRunEntity
    ) -> RealizedPnlComputationRunEntity:
        ...

    async def get(
        self, computation_run_id: UUID
    ) -> RealizedPnlComputationRunEntity | None:
        ...

    async def list_runs(
        self,
        limit: int = 50,
        status: str | None = None,
        run_type: RealizedPnlComputationRunType | None = None,
    ) -> Sequence[RealizedPnlComputationRunEntity]:
        ...


class RealizedPnlRecomputeQueueRepository(Protocol):
    """ledger 갱신 실패 / out-of-order fill / anomaly 재계산 큐 저장소.

    "fill 저장 성공 후 ledger 실패"를 조용히 넘기지 않기 위한 관측 가능한
    복구 계약의 저장소다.
    """

    async def add(
        self, item: RealizedPnlRecomputeQueueEntity
    ) -> RealizedPnlRecomputeQueueEntity:
        ...

    async def list_pending(
        self, limit: int = 100
    ) -> Sequence[RealizedPnlRecomputeQueueEntity]:
        """미해결(``resolved_at IS NULL``) 항목을 ``requested_at`` 오름차순으로 반환한다."""
        ...

    async def mark_resolved(
        self,
        recompute_queue_id: UUID,
        *,
        resolved_by_computation_run_id: UUID,
        resolved_at: datetime | None = None,
    ) -> RealizedPnlRecomputeQueueEntity | None:
        ...


class HistoricalBuyFeeOverlayRepository(Protocol):
    """이미 존재하는 BUY ``fill_event``에 대한 소급 fee 추정 append-only 저장소.

    ``fill_events`` 원본은 이 저장소를 통해 절대 수정되지 않는다 —
    recompute 경로만 이 값을 조회해 병합한다(설계 근거: 16번 문서 §8.13).
    """

    async def add(
        self, overlay: HistoricalBuyFeeOverlayEntity
    ) -> HistoricalBuyFeeOverlayEntity:
        ...

    async def get_by_fill_event_id(
        self, fill_event_id: UUID
    ) -> HistoricalBuyFeeOverlayEntity | None:
        ...


class HistoricalSellFeeTaxOverlayRepository(Protocol):
    """이미 존재하는 SELL ``fill_event``에 대한 소급 매도 수수료+매도세
    추정 append-only 저장소.

    ``fill_events`` 원본은 이 저장소를 통해 절대 수정되지 않는다 —
    recompute 경로만 이 값을 조회해 병합한다(설계 근거: 16번 문서 §8.15).
    """

    async def add(
        self, overlay: HistoricalSellFeeTaxOverlayEntity
    ) -> HistoricalSellFeeTaxOverlayEntity:
        ...

    async def get_by_fill_event_id(
        self, fill_event_id: UUID
    ) -> HistoricalSellFeeTaxOverlayEntity | None:
        ...


class ReconciliationRepository(Protocol):
    """Store for reconciliation runs and mismatch tracking."""

    async def add_run(self, run: ReconciliationRunEntity) -> ReconciliationRunEntity:
        ...

    async def get_run(self, reconciliation_run_id: UUID) -> ReconciliationRunEntity | None:
        ...

    async def attach_order_mismatch(
        self,
        reconciliation_run_id: UUID,
        order_request_id: UUID,
        mismatch_type: str,
        details: dict[str, object],
    ) -> None:
        ...

    async def attach_position_mismatch(
        self,
        reconciliation_run_id: UUID,
        position_snapshot_id: UUID,
        mismatch_type: str,
        details: dict[str, object],
    ) -> None:
        ...

    # -- Milestone 6 extensions --
    async def list_runs_by_account(
        self, account_id: UUID, limit: int = 20
    ) -> Sequence[ReconciliationRunEntity]:
        ...

    async def get_active_run(
        self, account_id: UUID
    ) -> ReconciliationRunEntity | None:
        """Return the most recent reconciliation run that is still in progress."""
        ...

    async def update_run_status(
        self,
        reconciliation_run_id: UUID,
        status: str,
        completed_at: datetime | None = None,
        summary_json: dict[str, object] | None = None,
    ) -> None:
        ...

    # -- Plan 44: Lock inspection --
    async def list_locks(
        self, account_id: UUID
    ) -> Sequence[BlockingLockEntity]:
        """Return active (non-expired) blocking locks for an account.

        Active means ``expires_at > NOW()`` (physical DELETE, no soft-delete
        column exists yet). If ``resolved_at`` / ``deleted_at`` columns are
        added later, they should be included in the filter.
        """
        ...

    # -- Plan 64: Aggregate (all-account) queries for Dashboard --
    async def list_all_runs(
        self, limit: int = 20
    ) -> Sequence[ReconciliationRunEntity]:
        """Return reconciliation runs across all accounts, newest first."""
        ...

    async def list_all_active_locks(
        self,
    ) -> Sequence[BlockingLockEntity]:
        """Return active (non-expired) blocking locks across all accounts."""
        ...

    # -- Worker read path (Reconciliation Worker) --

    async def list_pending_runs(
        self,
        limit: int = 20,
        *,
        account_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> Sequence[ReconciliationRunEntity]:
        """Return reconciliation runs with ``status = 'started'``.

        Parameters
        ----------
        limit : int
            Maximum number of runs to return (default ``20``).
        account_id : UUID | None
            Optional filter by account.
        run_id : UUID | None
            Optional filter by specific run ID.

        Returns
        -------
        Sequence[ReconciliationRunEntity]
            Runs ordered by ``started_at`` ASC (FIFO).
        """
        ...

    async def get_run_order_links(
        self,
        reconciliation_run_id: UUID,
    ) -> Sequence[ReconciliationOrderLinkEntity]:
        """Return order links attached to a reconciliation run.

        Parameters
        ----------
        reconciliation_run_id : UUID
            The reconciliation run to look up.

        Returns
        -------
        Sequence[ReconciliationOrderLinkEntity]
            Links ordered by ``created_at`` ASC.
        """
        ...

    async def list_run_position_links(
        self,
        reconciliation_run_id: UUID,
    ) -> Sequence[ReconciliationPositionLinkEntity]:
        """Return position links attached to a reconciliation run.

        (Interface only — not yet used by the worker.)
        """
        ...

    # -- EOD orphan cleanup --

    async def get_latest_reconciliation_status_by_order(
        self, order_request_id: object
    ) -> str | None:
        """Return the latest reconciliation run status linked to an order,
        or ``None`` if no reconciliation run is linked.

        Used by EOD orphan cleanup to determine whether a
        ``reconcile_required`` order had a ``failed`` reconciliation run.
        """
        ...

    # -- Legacy run cleanup --

    async def list_legacy_runs(
        self,
        limit: int = 50,
        *,
        account_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> Sequence[ReconciliationRunEntity]:
        """Return legacy runs: ``status = 'started'`` AND no order links.

        Parameters
        ----------
        limit : int
            Maximum number of runs to return (default ``50``).
        account_id : UUID | None
            Optional filter by account.
        run_id : UUID | None
            Optional filter by specific run ID.

        Returns
        -------
        Sequence[ReconciliationRunEntity]
            Runs ordered by ``started_at`` ASC (oldest first).
        """
        ...

    # -- Plan: Active/historical run 판별 --

    async def list_all_runs_with_activity(
        self,
        limit: int = 50,
        active_only: bool = True,
        include_historical: bool = False,
    ) -> list[dict[str, Any]]:
        """Reconciliation run 목록을 order activity 정보와 함께 조회.

        각 run에 ``is_active`` 플래그를 포함하여 반환.

        ``active_only=True`` (기본값): ``is_active=true`` 인 run만 반환.
        ``include_historical=True`` 일 때만 ``is_active=false`` 인
        historical failed/partial run 을 결과에 포함한다.

        ``include_historical`` 은 ``active_only`` 보다 우선하지 않는다.
        ``active_only=True`` 이면 ``include_historical`` 과 관계없이 active run 만 반환.
        """
        ...

    async def get_historical_failed_run_count(self) -> int:
        """``is_active=false + status IN ('failed','partial')`` 조건의 run 수 반환."""
        ...


class AuditLogRepository(Protocol):
    async def add(self, audit_log: AuditLogEntity) -> AuditLogEntity:
        ...

    async def list_by_correlation_id(self, correlation_id: str) -> Sequence[AuditLogEntity]:
        ...


class OrderStateEventRepository(Protocol):
    """Append-only store for order status transition events."""

    async def add(self, event: OrderStateEventEntity) -> OrderStateEventEntity:
        ...

    async def list_by_order_request(
        self, order_request_id: UUID
    ) -> Sequence[OrderStateEventEntity]:
        ...

    async def list_recent(
        self, limit: int = 100
    ) -> Sequence[OrderStateEventEntity]:
        ...


class GuardrailEvaluationRepository(Protocol):
    """Store for guardrail rule evaluation results."""

    async def add(self, evaluation: GuardrailEvaluationEntity) -> GuardrailEvaluationEntity:
        ...

    async def get(
        self, guardrail_evaluation_id: UUID
    ) -> GuardrailEvaluationEntity | None:
        """Get a single guardrail evaluation by its UUID."""
        ...

    async def get_by_decision_context(
        self, decision_context_id: UUID
    ) -> Sequence[GuardrailEvaluationEntity]:
        ...

    async def get_by_decision_contexts(
        self, decision_context_ids: Sequence[UUID]
    ) -> dict[UUID, list[GuardrailEvaluationEntity]]:
        """Batch lookup — avoids N+1 when enriching a list of trade decisions."""
        ...

    async def get_by_order_request(
        self, order_request_id: UUID
    ) -> Sequence[GuardrailEvaluationEntity]:
        ...

    async def list_by_account(
        self, account_id: UUID, limit: int = 20
    ) -> Sequence[GuardrailEvaluationEntity]:
        """List guardrail evaluations for an account (via decision_context join)."""
        ...


class RiskLimitSnapshotRepository(Protocol):
    """Store for point-in-time risk limit snapshots."""

    async def add(self, snapshot: RiskLimitSnapshotEntity) -> RiskLimitSnapshotEntity:
        ...

    async def get_latest_by_account(
        self, account_id: UUID
    ) -> RiskLimitSnapshotEntity | None:
        ...

    async def list_by_account(
        self, account_id: UUID, limit: int = 20
    ) -> Sequence[RiskLimitSnapshotEntity]:
        ...


class SignalFeatureSnapshotRepository(Protocol):
    """Store for deterministic signal feature snapshots."""

    async def add(
        self, snapshot: SignalFeatureSnapshotEntity,
    ) -> SignalFeatureSnapshotEntity:
        ...

    async def get_latest_by_instrument(
        self,
        instrument_id: UUID,
        timeframe: str = "1d",
    ) -> SignalFeatureSnapshotEntity | None:
        ...

    async def list_by_instrument(
        self,
        instrument_id: UUID,
        timeframe: str = "1d",
        limit: int = 20,
    ) -> Sequence[SignalFeatureSnapshotEntity]:
        ...

    async def list_latest_by_instrument_ids(
        self,
        instrument_ids: Sequence[UUID],
        timeframe: str = "1d",
    ) -> Sequence[SignalFeatureSnapshotEntity]:
        """instrument_id별 최신 snapshot 1건씩을 한 번에 조회한다.

        universe 구성 단계에서 core 후보 전체(수백 건)의 신호 점수를 읽어야
        하는데, ``get_latest_by_instrument``를 종목마다 호출하면 N+1이 된다
        (SPPV-2.144 §132.2). ``instrument_status_snapshots``의
        ``list_latest_by_instrument_ids``와 동일한 계약이다.
        """
        ...


class UniverseFreezeRunRepository(Protocol):
    """Store for frozen trading-universe run metadata."""

    async def add(self, run: UniverseFreezeRunEntity) -> UniverseFreezeRunEntity:
        ...

    async def get(self, run_id: UUID) -> UniverseFreezeRunEntity | None:
        ...

    async def get_latest(
        self,
        business_date: date,
        freeze_purpose: str,
    ) -> UniverseFreezeRunEntity | None:
        ...


class InstrumentIndexMembershipRepository(Protocol):
    """Authoritative time-series store for instrument index memberships."""

    async def sync_current_memberships(
        self,
        instrument_id: UUID,
        membership_codes: Sequence[str],
        *,
        effective_from: date,
        source_tag: str | None = None,
        metadata: dict[str, object] | None = None,
        refresh_existing_metadata: bool = False,
    ) -> Sequence[InstrumentIndexMembershipEntity]:
        ...

    async def list_active_by_instrument(
        self,
        instrument_id: UUID,
    ) -> Sequence[InstrumentIndexMembershipEntity]:
        ...

    async def list_active_by_instruments(
        self,
        instrument_ids: Sequence[UUID],
    ) -> dict[UUID, Sequence[InstrumentIndexMembershipEntity]]:
        """Batch variant of ``list_active_by_instrument`` — one query for many
        instruments instead of one query per instrument (avoids N+1 when
        composing the trading universe over thousands of instruments)."""
        ...

    async def list_active_instrument_ids_by_membership_code(
        self,
        membership_code: str,
    ) -> Sequence[UUID]:
        ...

    async def get_latest_effective_from(self) -> date | None:
        """가장 최근에 반영된 membership 기준일을 반환한다.

        UNIV-4: 지수 편입 데이터 staleness 감시용 — 활성(``effective_to IS
        NULL``) row 전체 중 metadata의 ``as_of_date``가 있으면 그 값을 우선
        사용하고, 없으면 ``effective_from``을 사용한다. 데이터가 전혀 없으면
        ``None``."""
        ...


class InstrumentStatusSnapshotRepository(Protocol):
    """종목 상태 snapshot authoritative 저장소."""

    async def add(
        self,
        snapshot: InstrumentStatusSnapshotEntity,
    ) -> InstrumentStatusSnapshotEntity:
        ...

    async def get_latest_by_instrument(
        self,
        instrument_id: UUID,
    ) -> InstrumentStatusSnapshotEntity | None:
        ...

    async def get_latest_by_instrument_before(
        self,
        instrument_id: UUID,
        as_of: datetime,
    ) -> InstrumentStatusSnapshotEntity | None:
        ...

    async def list_latest_by_instrument_ids(
        self,
        instrument_ids: Sequence[UUID],
    ) -> Sequence[InstrumentStatusSnapshotEntity]:
        ...


class SymbolTradeStateRepository(Protocol):
    """Authoritative current state cache for symbol-level trade hysteresis."""

    async def upsert(
        self,
        state: SymbolTradeStateEntity,
    ) -> SymbolTradeStateEntity:
        ...

    async def get_by_account_and_instrument(
        self,
        account_id: UUID,
        instrument_id: UUID,
    ) -> SymbolTradeStateEntity | None:
        ...

    async def list_by_account(
        self,
        account_id: UUID,
    ) -> Sequence[SymbolTradeStateEntity]:
        ...


class UniverseFreezeRunItemRepository(Protocol):
    """Store for item rows materialised under one freeze run."""

    async def add(self, item: UniverseFreezeRunItemEntity) -> UniverseFreezeRunItemEntity:
        ...

    async def add_many(
        self,
        items: Sequence[UniverseFreezeRunItemEntity],
    ) -> Sequence[UniverseFreezeRunItemEntity]:
        ...

    async def list_by_run(
        self,
        universe_freeze_run_id: UUID,
    ) -> Sequence[UniverseFreezeRunItemEntity]:
        ...


class SignalFeatureBatchRunRepository(Protocol):
    """signal feature 배치 실행 메타데이터 저장소."""

    async def add(self, run: SignalFeatureBatchRunEntity) -> SignalFeatureBatchRunEntity:
        ...

    async def get(self, run_id: UUID) -> SignalFeatureBatchRunEntity | None:
        ...


class SignalFeatureBatchRunItemRepository(Protocol):
    """signal feature 배치 종목별 상태 저장소."""

    async def add(
        self,
        item: SignalFeatureBatchRunItemEntity,
    ) -> SignalFeatureBatchRunItemEntity:
        ...

    async def add_many(
        self,
        items: Sequence[SignalFeatureBatchRunItemEntity],
    ) -> Sequence[SignalFeatureBatchRunItemEntity]:
        ...


class ExternalEventRepository(Protocol):
    """Store for normalised external event data.

    This is a **foundation** protocol for Milestone 7. Actual polling
    workers and source adapters are deferred to a later milestone.

    Listed-event filtering (P0):
    By default, ``list_by_symbol`` and ``list_by_type`` return only
    **listed-entity events** (OpenDART corp_cls in Y/K/N). Non-listed
    (corp_cls=E) events are excluded from operational read paths.

    Pass ``include_non_listed=True`` to bypass this filter when
    administrative inspection is needed.

    Seeded-news filtering (P1):
    ``event_type='seeded_news'`` events (T3 reliability tier) are
    excluded from the default listed-event filter because they do not
    carry the ``Y|``/``K|``/``N|`` prefix.  Pass
    ``include_seeded_news=True`` to include them alongside listed
    events — this is the intended mode for EI decision context
    assembly.
    """

    async def add(self, event: ExternalEventEntity) -> ExternalEventEntity:
        ...

    async def get(self, event_id: UUID) -> ExternalEventEntity | None:
        ...

    async def find_by_dedup_key(self, dedup_key_hash: str) -> ExternalEventEntity | None:
        ...

    async def list_by_symbol(
        self,
        symbol: str,
        since: datetime,
        include_non_listed: bool = False,
        include_seeded_news: bool = False,
    ) -> Sequence[ExternalEventEntity]:
        ...

    async def has_fresh_t3_events(
        self,
        symbol: str,
        freshness_seconds: int = 3600,
    ) -> bool:
        """Check if T3 events exist for symbol within freshness window.

        Uses created_at (DB insert time) rather than published_at to determine
        whether a recent T3 fetch already populated events for this symbol.
        This prevents redundant T3 pipeline execution within the freshness window.
        """
        ...

    async def list_by_type(
        self,
        event_type: str,
        since: datetime,
        include_non_listed: bool = False,
        include_seeded_news: bool = False,
    ) -> Sequence[ExternalEventEntity]:
        ...


class SnapshotSyncRunRepository(Protocol):
    """Store for KIS snapshot sync execution history.

    Append-only: each sync run (manual or scheduler) creates one record.
    This is a run-level summary, not individual position/cash rows.
    """

    async def add(self, run: SnapshotSyncRunEntity) -> SnapshotSyncRunEntity:
        """Persist a new sync run record and return it with server defaults."""
        ...

    async def list_runs(
        self,
        limit: int = 50,
        trigger_type: str | None = None,
        status: str | None = None,
    ) -> Sequence[SnapshotSyncRunEntity]:
        """List sync runs, newest first.

        Parameters
        ----------
        limit:
            Maximum number of records to return (default ``50``).
        trigger_type:
            Optional filter by ``"manual"`` or ``"scheduler"``.
        status:
            Optional filter by ``"completed"``, ``"partial"``, or ``"failed"``.

        Returns
        -------
        Sequence[SnapshotSyncRunEntity]
            Runs ordered by ``started_at`` descending.
        """
        ...

    async def get(self, run_id: UUID) -> SnapshotSyncRunEntity | None:
        """Get a single sync run by its UUID.

        Parameters
        ----------
        run_id:
            The snapshot sync run's unique identifier.

        Returns
        -------
        SnapshotSyncRunEntity | None
            The matching run, or ``None`` if not found.
        """

    async def update_run(self, run: SnapshotSyncRunEntity) -> SnapshotSyncRunEntity:
        """Update an existing sync run record (e.g. from ``running`` → ``completed``).

        Parameters
        ----------
        run:
            The sync run entity with updated fields.  The ``snapshot_sync_run_id``
            is used to identify the row to update.

        Returns
        -------
        SnapshotSyncRunEntity
            The updated record as returned by the database.
        """
        ...

    async def get_sync_health_summary(
        self,
        stale_threshold_seconds: int = 900,
    ) -> SnapshotSyncHealthSummary:
        """Compute a freshness/staleness summary for snapshot sync runs.

        Parameters
        ----------
        stale_threshold_seconds:
            Seconds after which a sync is considered stale (default ``900``).

        Returns
        -------
        SnapshotSyncHealthSummary
            Aggregate health indicators (never ``None`` — even for empty data).
        """
        ...


class AgentRunRepository(Protocol):
    """Store for AI Agent execution run records."""

    async def add(self, run: AgentRunEntity) -> AgentRunEntity:
        """Persist a new agent run and return it with server defaults."""
        ...

    async def get(self, agent_run_id: UUID) -> AgentRunEntity | None:
        """Get a single agent run by its UUID."""
        ...

    async def list_by_decision_context(
        self, decision_context_id: UUID
    ) -> Sequence[AgentRunEntity]:
        """Return all runs for a decision context, ordered by started_at DESC."""
        ...

    async def list_by_decision_contexts(
        self, decision_context_ids: Sequence[UUID], *, agent_type: str | None = None
    ) -> dict[UUID, list[AgentRunEntity]]:
        """Batch lookup — avoids N+1 when enriching a list of trade decisions.

        Each value is ordered by ``started_at`` DESC, same as the single-id method.
        ``agent_type``: optional server-side filter — callers that only need
        one agent type (e.g. compliance inspection only cares about
        ``"ai_compliance"`` runs) should pass it so rows/columns for
        irrelevant types (and their potentially large ``structured_output_json``)
        aren't fetched at all.
        """
        ...

    async def list_all(self, limit: int = 100) -> Sequence[AgentRunEntity]:
        """Return recent runs ordered by started_at DESC."""
        ...


class ExecutionAttemptRepository(Protocol):
    async def add(
        self, attempt: ExecutionAttemptEntity
    ) -> ExecutionAttemptEntity:
        ...

    async def get(
        self, execution_attempt_id: UUID
    ) -> ExecutionAttemptEntity | None:
        ...

    async def update_status(
        self,
        execution_attempt_id: UUID,
        status: str,
        *,
        stop_phase: str | None = None,
        stop_reason: str | None = None,
        phase_trace: list[dict[str, object]] | None = None,
        order_request_id: UUID | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        ...

    async def list_by_trade_decision(
        self, trade_decision_id: UUID
    ) -> Sequence[ExecutionAttemptEntity]:
        ...


class MarketSessionRepository(Protocol):
    """Store for market session state and phase change events.

    ``market_sessions`` 테이블은 ``run_date`` 기준으로 1행이며,
    P2 scheduler가 주기적으로 upsert (INSERT … ON CONFLICT) 한다.
    """

    async def upsert(self, session: MarketSessionEntity) -> MarketSessionEntity:
        """Upsert a market session by ``run_date``.

        ``INSERT … ON CONFLICT (run_date) DO UPDATE`` semantics.
        Returns the entity with server-generated defaults (id, created_at, etc.).
        """
        ...

    async def get_by_run_date(self, run_date: date) -> MarketSessionEntity | None:
        """Get the session state for a specific run date."""
        ...

    async def list_recent(self, limit: int = 10) -> Sequence[MarketSessionEntity]:
        """Return recent sessions ordered by ``run_date DESC``."""
        ...

    async def add_event(self, event: SessionEventEntity) -> SessionEventEntity:
        """Append a phase-change event to the session_events log."""
        ...

    async def get_events(
        self, market_session_id: int, limit: int = 50
    ) -> Sequence[SessionEventEntity]:
        """Return events for a session, ordered by ``occurred_at DESC``."""
        ...


class OrderSubmissionAttemptRepository(Protocol):
    """Repository for ``trading.order_submission_attempts``.

    Records every broker submission attempt (success/rejection/exception)
    so that the submission history is never lost.
    """

    async def add(
        self, attempt: OrderSubmissionAttemptEntity
    ) -> OrderSubmissionAttemptEntity:
        """Insert a new submission attempt.

        Returns the entity with server-generated defaults (attempt_id,
        created_at, etc.).
        """
        ...

    async def list_by_order_request(
        self, order_request_id: UUID
    ) -> Sequence[OrderSubmissionAttemptEntity]:
        """Return all attempts for a given order, ordered by attempt_number ASC."""
        ...

    async def get_failure_summary(self) -> dict[str, Any]:
        """Return aggregated failure counts for the last 1h, 24h, and KST today.

        Returns a dict with keys:
        - last_1h_count, last_24h_count, rejected_count, exception_count,
          total_submissions_24h, failure_rate_pct_24h,
          today_count, rejected_count_today, exception_count_today,
          total_submissions_today, failure_rate_pct_today
        """
        ...

    async def list_recent_failures(
        self,
        limit: int = 10,
        *,
        submitted_from: datetime | None = None,
        submitted_to: datetime | None = None,
    ) -> Sequence[dict[str, Any]]:
        """Return the most recent submission failures (rejected or exception).

        Returns a list of dicts with keys:
        - order_request_id, symbol, side, latest_outcome,
          latest_error_type, latest_raw_code, latest_raw_message,
          last_submitted_at, created_at
        """
        ...


# ---------------------------------------------------------------------------
# FDC cycle-scoped batch queue — Gemini 공용 13 RPM quota coordinator (Phase 1)
# ---------------------------------------------------------------------------
#
# 설계 근거: docs/40_action_plans/fdc_cycle_scoped_batch_queue_gemini_
# shared_13rpm_quota_design_2026-08-25.md §6·§8·§9.


class CoordinatorErrorClass(str, Enum):
    """DB/coordinator 오류 4분류(설계 문서 §6 "coordinator 오류 경로",
    §11 "수동 provider 호출 정책" — PR A 2026-08-27 3차 리뷰 보정으로
    ``MANUAL_CALL_POLICY_REJECTED`` 추가).

    앞 3개는 DB row가 아니라 호출자의 프로세스 로그/메트릭 계층에서만
    쓰인다 — DB 자체가 unavailable인 경우 그 사실 자체를 DB에 영속
    기록할 방법이 없기 때문이다(A안, 설계 문서 §9의 4차 개정).
    ``MANUAL_CALL_POLICY_REJECTED``는 DB/coordinator 호출 자체의 실패가
    아니라, coordinator가 ``try_reserve()`` 위임 **이전**에 의도적으로
    거부한 경우다(§11 "coordinator 쪽에서 운영 시간대에는 caller_id가
    'manual:*'인 reservation 요청을 무조건 거부" 계약의 실제 구현).
    """

    COORDINATOR_UNAVAILABLE = "coordinator_unavailable"
    COORDINATOR_LOCK_TIMEOUT = "coordinator_lock_timeout"
    COORDINATOR_TRANSACTION_ERROR = "coordinator_transaction_error"
    MANUAL_CALL_POLICY_REJECTED = "manual_call_policy_rejected"


@dataclass(frozen=True, slots=True)
class ReservationGrant:
    """§6 트랜잭션이 성공(GRANTED)했을 때의 결과."""

    reservation_id: UUID
    quota_scope: str
    job_id: UUID | None
    attempt_no: int
    window_count_before_grant: int


@dataclass(frozen=True, slots=True)
class ReservationDenied:
    """§6 트랜잭션이 정상 완료됐으나 quota가 가득 차 거부(DENIED)된 결과."""

    quota_scope: str
    window_count: int


@dataclass(frozen=True, slots=True)
class CoordinatorError:
    """coordinator 호출 자체가 실패한 경우(§6 "coordinator 오류 경로").

    ``GRANTED``도 ``DENIED``도 아니므로 ``queue_poll_count``/
    ``reservation_denied_count``/``dispatch_attempt_no`` 중 어느 것도
    증가시키지 않는다.
    """

    error_class: CoordinatorErrorClass
    detail: str


ReservationResult = ReservationGrant | ReservationDenied | CoordinatorError


@dataclass(frozen=True, slots=True)
class ShadowJudgement:
    """shadow 가상 FIFO 큐 판단 결과 — 실제(mode='real') quota를 전혀
    소비하지 않고, 같은 quota_scope의 다른 mode='shadow' 행만 본다.

    ``would_grant=True``면 ``SHADOW_WOULD_GRANT``(가상 13 RPM 큐에서
    지금 승인 가능), ``False``면 ``SHADOW_QUEUED``(앞선 shadow grant가
    이미 window 용량을 다 써서 대기) — 이 상태는 실패나 timeout이
    아니다(설계 문서 §11 보정 — 자동 시간 진행 dispatcher가 없는
    Phase 1에서는 "즉시 승인 가능"과 "대기 상태" 두 가지만 신뢰성
    있게 관측한다).
    """

    job_id: UUID
    would_grant: bool
    window_count: int
    attempt_id: UUID
    enqueue_sequence: int


ShadowJudgementResult = ShadowJudgement | CoordinatorError


class AttemptHttpLifecycle(str, Enum):
    """``fdc_provider_attempts`` 행 하나의 HTTP 실행 lifecycle 3상태
    (2026-08-27 3차 리뷰 보정 — PR #359).

    이전에는 ``get_attempt_http_started_at() -> datetime | None``이
    "행이 아예 없음"과 "행은 있으나 ``http_started_at IS NULL``"을 모두
    ``None``으로 뭉뚱그려 반환했다 — crash 복구 판단에서 이 둘은 완전히
    다른 의미다. "행이 없음"은 ``try_reserve()``가 grant와 attempt 행을
    같은 트랜잭션에서 원자적으로 만드는 계약(§6)이 깨졌다는 데이터
    정합성 이상이므로, "HTTP 미시작이라 안전하게 재시도 가능"과 절대
    같은 방식으로 처리해서는 안 된다.
    """

    NOT_FOUND = "not_found"
    NOT_STARTED = "not_started"
    STARTED = "started"


@dataclass(frozen=True, slots=True)
class ResumableRealJob:
    """durable resume에 필요한 최소 정보(2026-08-28 4차 리뷰 보정 —
    PR #359). ``list_resumable_real_jobs()``가 반환한다.

    position/cash/risk snapshot 등 시간이 지나면 낡을 수 있는 context는
    의도적으로 포함하지 않는다 — override/EV-gate/sizing/submit은 재개
    시점에 항상 새로 조회한 context로 다시 계산된다(기존
    ``precomputed_agent_bundle`` 경로).
    """

    job_id: UUID
    symbol: str
    source_type: str
    quota_scope: str
    decision_cycle_id: str | None
    decision_context_id: UUID | None
    correlation_id: str | None
    pre_fdc_result: dict[str, Any]
    fdc_ready_at: datetime


@dataclass(frozen=True, slots=True)
class ProviderGlobalGateGranted:
    """PR D(2026-09-03) — provider 전체(legacy+actual) 물리적 HTTP-start
    global gate가 grant했을 때의 결과.

    ``fdc_provider_global_gate_grants``에 append-only로 1행이 INSERT된
    시점의 결과다 — 이 grant는 실제 HTTP가 시작되기 **전**에 이미
    window 슬롯을 소비한 것으로 집계된다(보수적 소비 규칙, 환불 없음)."""

    grant_id: UUID
    gate_scope: str
    window_count_before_grant: int


@dataclass(frozen=True, slots=True)
class ProviderGlobalGateDenied:
    """global gate가 window 포화로 거부한 결과 — DB/lock 오류가 아닌
    정상적인 "지금은 자리가 없다" 판정이다(``CoordinatorError``와 구분)."""

    gate_scope: str
    window_count: int


ProviderGlobalGateResult = (
    ProviderGlobalGateGranted | ProviderGlobalGateDenied | CoordinatorError
)


class FdcQuotaRepository(Protocol):
    """FDC 공용 13 RPM quota의 atomic reservation과 lifecycle shadow 관측.

    ``fdc_quota_state``(singleton anchor)/``fdc_queue_jobs``/
    ``fdc_provider_attempts`` 3개 테이블을 함께 다룬다 — 세 테이블이
    항상 하나의 원자적 단위(§6 트랜잭션)로 갱신되기 때문에 별도
    repository로 쪼개지 않는다.

    ``try_reserve()``는 Phase 1에서 실제 런타임 경로에 연결되지 않는다
    (단위/통합 테스트 전용). ``register_shadow_job_and_judge()``만
    Phase 1의 실제 관측 경로다.
    """

    async def try_reserve(
        self,
        *,
        quota_scope: str,
        target_rpm: int,
        window_seconds: int,
        job_id: UUID | None,
        caller_id: str,
        mode: str = "real",
        manual_run_id: str | None = None,
        attempt_no: int = 1,
        lock_timeout_ms: int = 3000,
    ) -> ReservationResult:
        """§6의 atomic reservation transaction 계약을 그대로 구현한다.

        anchor 행을 ``SELECT ... FOR UPDATE``로 잠근 뒤 ``(t-window_
        seconds, t]`` 구간의 유효 reservation 수를 세고, ``target_rpm``
        미만이면 새 attempt 행을 INSERT해 승인한다. 트랜잭션/행 잠금을
        쥔 채 네트워크 I/O(Gemini HTTP 호출)를 절대 수행하지 않는다.
        """
        ...

    async def record_attempt_outcome(
        self,
        *,
        reservation_id: UUID,
        outcome: str,
        http_status: int | None = None,
        error_class: str | None = None,
        http_429_observed: bool = False,
        http_started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        """``try_reserve()``가 발급한 ``reservation_id``(=``attempt_id``)
        행에 실제 HTTP 실행 결과(성공/실패/429/HTTP 미시작)를 기록한다
        (PR A 신설). ``outcome``은 기존 ``_QUOTA_CONSUMING_OUTCOMES``
        어휘(``http_started``/``http_succeeded``/``http_failed_
        retryable``/``http_failed_final``/``reserved_but_http_not_
        started``)를 그대로 쓴다. 새 reservation을 발급하지 않으며,
        이미 소비된 window 슬롯의 상태만 갱신한다.

        Raises
        ------
        ValueError
            ``reservation_id``에 대응하는 attempt 행이 존재하지 않아
            갱신된 행이 0개일 때(2026-08-27 리뷰 보정) — 감사 기록
            누락을 조용히 성공으로 위장하지 않는다.
        """
        ...

    async def register_shadow_job_and_judge(
        self,
        *,
        quota_scope: str,
        target_rpm: int,
        window_seconds: int,
        decision_cycle_id: str | None,
        decision_context_id: UUID | None,
        symbol: str,
        source_type: str,
        fdc_ready_at: datetime,
        caller_id: str = "ops-scheduler",
        lock_timeout_ms: int = 3000,
    ) -> ShadowJudgementResult:
        """FDC-ready job을 ``mode='shadow'`` FIFO 큐에 등록하고, "같은
        cycle 내 앞선 shadow FDC-ready job까지 포함한 FIFO 가상 13 RPM
        큐에서 지금 승인 가능한가"를 원자적으로 판단한다.

        등록(INSERT)과 판단(COUNT+상태 결정)을 하나의 트랜잭션으로
        묶는다 — anchor 행 잠금으로 동시 등록을 직렬화해, "뒤에 도착한
        job이 앞선 job보다 먼저 승인되는 새치기"를 원천 차단한다. FIFO
        순서는 DB가 발급하는 ``enqueue_sequence``(BIGSERIAL)로 정의되며
        Python 코루틴/subprocess의 완료 순서에 의존하지 않는다.
        ``fdc_ready_at``은 sliding window 경계 계산에만 쓰인다(어느
        60초 구간에 속하는지).

        ``mode='real'`` 행은 전혀 보지 않으며, 이 메서드가 만드는 모든
        행은 ``mode='shadow'``다 — 실제 quota를 절대 소비하지 않는다.
        """
        ...

    async def register_real_job(
        self,
        *,
        decision_cycle_id: str | None,
        decision_context_id: UUID | None,
        symbol: str,
        source_type: str,
        quota_scope: str,
        fdc_ready_at: datetime,
        pre_fdc_result: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> UUID:
        """실제(``mode='real'``) FDC dispatch 대상 job을 ``QUEUED``
        상태로 ``fdc_queue_jobs``에 등록한다(2026-08-27, held_position
        실제 dispatcher 신설).

        ``pre_fdc_result``/``correlation_id``(2026-08-28 4차 리뷰 보정
        — PR #359, durable carryover)를 함께 저장한다 — ops-scheduler는
        ``run_decision_loop.py --count 1``로 항상 단발 프로세스를
        spawn하므로, 이 job이 quota 포화로 이번 프로세스 안에서
        완결되지 못하면 프로세스 메모리만으로는 재개할 방법이 없다.
        ``status='QUEUED'``인 real job은 pre_fdc가 이미 완료된 뒤에만
        등록되므로 이 값들은 항상 채워져 있다 — 다음 프로세스가
        ``list_resumable_real_jobs()``로 이 값을 읽어 agent를 다시
        호출하지 않고 안전하게 재개한다.

        **왜 두 파라미터가 optional(기본값 ``None``)인가(2026-08-28 5차
        리뷰 보정)** — ``try_reserve()``의 FIFO/rate-limit 메커니즘 자체를
        검증하는 기존 테스트(``tests/services/test_fdc_quota_
        coordinator.py``, ``tests/scripts/test_fdc_manual_provider_
        gate.py``)들이 durable resume과 무관하게 이 메서드를 호출하며,
        NOT NULL로 강제하면 이 테스트들과 그 테스트들이 대변하는 기존
        (durable-resume 이전) 호출 패턴이 전부 깨진다 — 근거 없이 schema
        제약을 넓히지 않는다는 원칙에 따라 DB 컬럼도 nullable로 유지
        했다(migration ``0069``). 대신 **actual-dispatch 경로에서 이
        값이 누락되는 것은 별도로 막는다** — ``DecisionAgentRunner.
        _run_agents_in_subprocess_with_actual_dispatch()``는 이 메서드를
        호출하기 **전에** ``request.correlation_id``가 비어 있으면 즉시
        ``build_fallback_bundle()``로 fail-closed하고 아예 등록하지
        않는다(불완전한 row를 만들지 않는 것이 사후 정리보다 우선).
        그래도 불완전한 ``QUEUED`` row가 남아 있다면(migration 이전
        데이터, 수동 복구 오류 등) ``list_resumable_real_jobs()``가
        그 row를 발견 즉시 ``FDC_FAILED_FINAL``로 fail-closed 종결해
        FIFO head 차단을 막는다 — 두 계층(등록 시점 예방 + 조회 시점
        정리)이 함께 이 계약을 지킨다.

        이 메서드가 반환하는 ``job_id``는 이후 ``try_reserve(job_id=...)``
        에 그대로 전달돼야 한다 — ``job_id=None``으로 ``try_reserve()``를
        호출하면 이 job의 accounting(``queue_poll_count``/
        ``reservation_denied_count``/``dispatch_attempt_no``)이 전혀
        기록되지 않는다(§9 계약 위반).
        """
        ...

    async def list_resumable_real_jobs(
        self, *, quota_scope: str,
    ) -> list[ResumableRealJob]:
        """이 ``quota_scope``의 ``status='QUEUED'`` real job을 모두
        durable resume 정보와 함께 반환한다(2026-08-28 4차 리뷰 보정 —
        PR #359).

        ``status='QUEUED'``는 "reservation을 한 번도 받지 못한 채 등록만
        돼 있음"을 뜻하며, ``register_real_job()``이 pre_fdc 완료 직후
        에만 호출되므로 이 job들은 전부 재개에 필요한 ``pre_fdc_result``/
        ``correlation_id``를 이미 갖고 있어야 한다. 새 ``run_decision_
        loop.py`` 프로세스가 시작할 때(첫 cycle의 universe를 읽은 직후)
        이 목록을 조회해, 해당 symbol이 현재 universe에 여전히 존재하면
        agent를 다시 호출하지 않고 이 job을 이어서 완결한다 — 존재하지
        않으면(예: 포지션이 이미 청산됨) 호출자가 감사 가능한 이유로
        fail-closed 종결한다(``mark_job_terminal()``, 조용한 취소 금지).

        **2026-08-28 5차 리뷰 보정** — 이 메서드는 더 이상 완전히
        read-only가 아니다. ``pre_fdc_result_json`` 또는
        ``correlation_id``가 없는 ``QUEUED`` row(migration 이전 데이터,
        부분 실패, 수동 복구 오류, 향후 코드 결함 등으로 발생 가능)는
        조용히 건너뛰지 않고 그 자리에서 즉시 ``FDC_FAILED_FINAL``로
        전이시킨다(``reason="fdc_carryover_payload_missing_data_
        integrity_error"`` 또는 ``"fdc_carryover_correlation_id_
        missing_data_integrity_error"``). 이렇게 하지 않고 로그만 남긴
        채 건너뛰면, ``try_reserve()``의 FIFO admission("나보다 먼저
        등록된 QUEUED job이 있으면 양보")이 이 불완전한 row 하나 때문에
        뒤따르는 모든 held-position 실제 FDC job을 영구 대기시킨다(§17.3/
        §17.7). 이 정리는 idempotent다 — 한 번 terminal로 전이된 job은
        다음 호출부터 이 SELECT 자체에 다시 걸리지 않는다. 반환 순서는
        FIFO(``enqueue_sequence`` 오름차순)를 보장한다.
        """
        ...

    async def cancel_stale_real_jobs(
        self,
        *,
        quota_scope: str,
        reason: str = "process_terminated_carryover_lost",
    ) -> int:
        """재기동 recovery scan(§17.7) — **이 메서드는 새 프로세스가
        시작할 때만 호출된다**(``run_decision_loop.py``가 자기 자신의
        메인 루프에 진입하기 전 1회). 이 시점에는 이전에 이 job들을
        만들었던 프로세스가 이미 확실히 종료된 상태이므로, ``reason``
        기본값(§5 "프로세스 종료" 사유)을 여기서 쓰는 것은 정확하다 —
        **살아 있는 프로세스가 자신의 cycle deadline/timeout 때문에 이
        reason으로 job을 취소하는 것은 이 메서드의 용도가 아니다**(그런
        경우는 job을 건드리지 않고 다음 cycle의 dispatcher가 재시도하도록
        남겨둔다 — ``run_decision_loop.py``의 in-process carryover 참조).

        **2026-08-28 4차 리뷰 보정 — PR #359**: 이 메서드의 대상은 이제
        ``status='RESERVATION_GRANTED'`` job **만**이다(``status='QUEUED'``
        job은 더 이상 여기서 다루지 않는다 — durable resume 신설로
        ``list_resumable_real_jobs()``가 그 job들을 안전하게 재개하므로,
        "재개할 방법이 없어 취소한다"는 이전 전제가 더 이상 성립하지
        않는다). 즉 이 메서드는 이제 정확히 "reservation은 실제로
        받았지만(=grant가 anchor 행 잠금 하에 원자적으로 발급됨), 그
        결과(성공/실패/HTTP 시작 여부)가 process crash로 불명확하게 남은"
        job만 다룬다 — 문자 그대로 "process crash로 결과가 불명확한
        reservation"만 fail-closed로 정리하라는 요구와 일치한다.

        ``status='RESERVATION_GRANTED'``인 job에 대해 가장 최근 attempt의
        ``get_latest_real_job_attempt_lifecycle()``로 다음과 같이
        전이시킨다.

        - ``NOT_STARTED`` 또는 ``NOT_FOUND``: 실제 HTTP 호출이 나가지
          않았으므로 안전하게 ``CANCELLED``(``reason``)로 전이
          (``NOT_FOUND``는 데이터 정합성 이상이므로 ERROR 레벨로 별도
          로깅한다).
        - ``STARTED``: HTTP가 실제로 나갔을 수 있어 자동으로 안전하다고
          볼 수 없으므로 ``CANCELLED``가 아니라 ``FDC_FAILED_FINAL``
          (``reason="fdc_only_subprocess_crashed_after_http_start_
          result_unknown"``, ``complete_fdc_actual_dispatch()``의 라이브
          crash 판정과 동일한 reason)로 전이한다 — 중복 호출 위험을
          피하기 위한 fail-closed 처리다.

        idempotent — 이미 terminal인 job은 건드리지 않으므로, 두 번
        연속 호출해도 두 번째 호출의 영향 행 수는 0이다.
        reservation/attempt accounting 카운터(§9)는 전혀 변경하지
        않는다 — ``status``와 ``failure_or_cancel_reason``만 갱신한다.

        Returns
        -------
        int
            이번 호출로 상태가 바뀐(``CANCELLED`` 또는 ``FDC_FAILED_
            FINAL``) 행 수 합계.
        """
        ...

    async def mark_job_terminal(
        self,
        *,
        job_id: UUID,
        status: str,
        reason: str | None = None,
    ) -> None:
        """job을 종결 상태(``FDC_SUCCEEDED``/``FDC_FAILED_FINAL``/
        ``CANCELLED``)로 전이시킨다. attempt 단위 accounting과는 별개로
        job 단위 최종 상태만 기록한다."""
        ...

    async def mark_job_status(self, *, job_id: UUID, status: str) -> None:
        """job의 비종결(non-terminal) 상태 전이(``RETRY_QUEUED`` 등)를
        기록한다."""
        ...

    async def apply_retry_failure(
        self, *, job_id: UUID, reason: str, will_retry: bool,
    ) -> None:
        """FIFO tail 재등록 계약(2026-08-28 6차 리뷰 보정 — PR #359,
        설계 문서 §5/§9).

        ``complete_fdc_actual_dispatch()``가 retryable provider 실패
        (``reason="provider_retryable_failure"``, HTTP가 실제로
        시작된 뒤 429/5xx/timeout)나 HTTP 시작 전 subprocess 실패
        (``reason="pre_http_execution_failure"``)를 만났을 때 호출한다.

        이전 구현은 이 두 실패 후 같은 ``job_id``로 즉시 ``try_
        reserve()``를 재호출했는데, job의 ``enqueue_sequence``가
        그대로 유지돼 이미 앞서 있던 순번을 계속 지켰다 — 이 job의
        재시도가 정상적으로 대기 중이던 다른(뒤에 등록됐지만 아직 첫
        기회조차 받지 못한) job보다 매번 먼저 grant받는 FIFO 위반이
        가능했다.

        이 메서드는 job의 ``job_id``(audit identity)를 그대로 유지한
        채(새 row를 만들지 않는다), ``will_retry=True``일 때만
        ``enqueue_sequence``를 새로 발급해 FIFO tail로 옮기고
        ``status``를 ``QUEUED``로 되돌린다 — 이후 ``try_reserve()``의
        기존 FIFO admission 쿼리("나보다 작은 enqueue_sequence를 가진
        QUEUED job이 있으면 양보")가 변경 없이 이 새 위치를 그대로
        반영한다.

        **2026-08-28 7차 리뷰 보정 — counter 의미 정정**:
        ``provider_retry_count``/``pre_http_execution_failure_count``
        (및 파생 지표 ``queue_reenqueue_count``)는 ``will_retry=True``
        일 때만(=실제로 FIFO tail에 다시 섰을 때만) 증가한다.
        ``queue_reenqueue_count``는 문자 그대로 **"실제 FIFO tail
        재등록 횟수"**를 뜻해야 하며, "이 유형의 실패가 몇 번
        발생했는지"와 혼동해서는 안 된다 — 소진(``will_retry=False``)
        으로 이어지는 마지막 실패는 재등록이 아니라 종결이므로 이
        counter들을 건드리지 않는다(이전 라운드는 ``will_retry`` 값과
        무관하게 항상 증가시켰는데, 이는 "3회 실패 후 소진"이 실제로는
        FIFO tail에 2번만 재등록된 것을 3번 재등록된 것처럼 과대
        보고하는 결함이었다 — 이 보정으로 되돌렸다).

        ``reserved_but_http_not_started_count``는 예외다 — attempt
        단위 관측값(§9, "outcome='reserved_but_http_not_started'로
        기록된 attempt 수")이므로 ``reason="pre_http_execution_
        failure"``일 때마다 재등록 여부와 무관하게 항상 증가한다.

        ``will_retry=False``(소진)면 이 메서드는 위 예외를 제외하고는
        아무 것도 갱신하지 않는다 — 호출자가 곧바로 ``mark_job_
        terminal()``로 종결시키며, 실제 HTTP 시도/429 관측은 별도로
        ``record_http_attempt_counters()``가 이미 반영했다.
        """
        ...

    async def record_http_attempt_counters(
        self, *, job_id: UUID, http_429_observed: bool = False,
    ) -> None:
        """실제 HTTP 시도가 있었던 attempt마다 job 단위 ``http_attempt_
        count``/``http_429_count``를 갱신한다(2026-08-28 6차 리뷰 보정 —
        설계 문서 §9, 불변식 ``http_attempt_count <= permit_consumed_
        count``). ``http_started_at``이 채워진 attempt(성공, provider
        레벨 실패, crash-after-http-start 전부 포함)마다 정확히 1회
        호출돼야 한다 — HTTP가 시작되지 않은 경우(pre-HTTP 실패)는
        호출하지 않는다.
        """
        ...

    async def get_attempt_http_lifecycle(
        self, *, reservation_id: UUID,
    ) -> AttemptHttpLifecycle:
        """이 reservation(``attempt_id``)의 HTTP 실행 lifecycle을 3상태로
        조회한다(2026-08-27 3차 리뷰 보정 — PR #359, subprocess crash 후
        attempt lifecycle 판별용. 이전 ``get_attempt_http_started_at()``의
        ``datetime | None`` 반환을 대체 — "행이 없음"과 "행은 있으나
        미시작"을 더 이상 뭉뚱그리지 않는다).

        ``fdc_only`` subprocess가 결과 없이 crash/timeout됐을 때 호출자가
        이 값으로 판단한다 — ``NOT_STARTED``면 HTTP가 나가지 않았으므로
        새 reservation으로 안전하게 재시도할 수 있고, ``STARTED``면 HTTP가
        실제로 나갔을 수 있으므로 결과를 모르는 채 자동 재시도(중복 호출
        위험)하지 않는다. ``NOT_FOUND``는 ``try_reserve()``가 grant와
        attempt 행을 원자적으로 함께 만드는 계약(§6)이 깨졌다는 데이터
        정합성 이상이므로, 호출자는 이를 ``NOT_STARTED``와 절대 같은
        방식(자동 재시도)으로 처리해서는 안 되고 fail-closed로 다뤄야
        한다. 이 메서드 자체는 어떤 상태도 갱신하지 않는다(read-only).
        """
        ...

    async def get_latest_real_job_attempt_lifecycle(
        self, *, job_id: UUID,
    ) -> AttemptHttpLifecycle:
        """이 ``job_id``의 가장 최근(``reserved_at`` 기준) ``mode='real'``
        attempt 행을 찾아 그 HTTP 실행 lifecycle을 3상태로 반환한다
        (2026-08-27 3차 리뷰 보정 — PR #359, recovery scan 전용).

        재기동 recovery scan이 ``status='RESERVATION_GRANTED'``로 멈춰
        있는(=reservation은 받았지만 job이 종결되지 못한 채 프로세스가
        죽은) job을 일괄 ``CANCELLED``로 덮어쓰지 않고, ``complete_fdc_
        actual_dispatch()``의 crash 판정과 동일한 tri-state 규칙을
        적용하기 위해 쓰인다. 해당 job에 attempt 행이 하나도 없으면
        ``NOT_FOUND``를 반환한다(read-only, 상태를 갱신하지 않는다).
        """
        ...

    async def try_acquire_provider_global_gate_permit(
        self,
        *,
        gate_scope: str,
        target_rpm: int,
        window_seconds: int,
        caller_lane: str,
        caller_id: str,
        lock_timeout_ms: int = 3000,
    ) -> ProviderGlobalGateResult:
        """PR D(2026-09-03) — legacy `mode="full"` FDC와 held_position/
        BUY actual-dispatch FDC의 실제 provider HTTP 시작만 합산하는
        durable global gate.

        ``fdc_quota_state``/``fdc_provider_attempts``/``fdc_queue_jobs``
        (기존 actual coordinator의 FIFO/window 판정 테이블)를 전혀
        참조하지 않는다 — 별도의 ``fdc_provider_global_gate_state``
        (singleton anchor)/``fdc_provider_global_gate_grants``
        (append-only)만 다룬다. anchor 행을 ``SELECT ... FOR UPDATE``로
        잠근 뒤 ``(t-window_seconds, t]`` 구간의 grant 수를 세고,
        ``target_rpm`` 미만이면 새 grant 행을 INSERT해 승인한다.

        **grant는 실제 HTTP 시작 여부와 무관하게, 이 함수가 반환하는
        순간 이미 window 슬롯을 소비한 것으로 집계된다** — grant 후
        호출자가 실제 HTTP를 시작하지 못해도(pre-HTTP 실패) 이 슬롯은
        환불되지 않는다(보수적 소비 규칙 — provider 전체 실제 HTTP
        시작 수가 ``target_rpm``을 넘는 방향으로는 절대 오차가 나지
        않고, 아주 드물게 낭비되는 슬롯만 과소 활용으로 허용한다).

        anchor 행이 없거나(seed 누락) DB/lock 오류가 나면 ``Coordinator
        Error``를 반환한다(fail-closed — grant하지 않는다). ``caller_
        lane``(``"legacy"``|``"actual"``)은 감사 관측용일 뿐 window
        판정에는 영향을 주지 않는다 — ``gate_scope`` 전체를 lane 구분
        없이 합산한다(이것이 이 gate의 존재 이유다).
        """
        ...
