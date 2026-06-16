"""Replay test harness — shared helpers for deterministic replay verification.

This module provides reusable building blocks for replay-style tests:

* ``ReplayBundle`` — dataclass encapsulating all inputs and expected outputs.
* ``_make_request()`` — ``SubmitOrderRequest`` factory.
* ``_make_sizing_inputs()`` — ``SizingInputs`` factory.
* ``_build_repos()`` — fully seeded ``RepositoryContainer`` factory.
* ``_make_stub_fdc()`` — stub ``ProviderAIAgent`` factory.
* ``REPLAY_SCENARIOS`` — canonical list of all replay scenarios.

Usage
-----
Replay tests import from this harness and use ``@pytest.mark.parametrize``
with ``REPLAY_SCENARIOS``.  The same scenarios can also be consumed by
``scripts/replay_verification.py`` for operational verification outside
of pytest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from agent_trading.brokers.base import BrokerAdapter
from agent_trading.domain.entities import (
    AccountEntity,
    CashBalanceSnapshotEntity,
    ConfigVersionEntity,
    InstrumentEntity,
    PositionSnapshotEntity,
)
from agent_trading.domain.enums import AssetClass, Environment, OrderSide, OrderType, TimeInForce
from agent_trading.domain.models import SubmitOrderRequest
from agent_trading.repositories.bootstrap import build_in_memory_repositories
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.ai_agents.schemas import FinalDecisionComposerOutput
from agent_trading.services.sizing_engine import SizingInputs

# ---------------------------------------------------------------------------
# ReplayBundle dataclass
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class ReplayBundle:
    """Deterministic replay bundle — encapsulates all inputs and expected outputs.

    Parameters
    ----------
    name
        Human-readable scenario name; MUST end with ``_submit`` (pipeline
        proceeds to broker) or ``_guard`` (pipeline stops at guardrail) so
        that test infrastructure can distinguish intent.
    request
        The ``SubmitOrderRequest`` that triggers the pipeline.
    repos
        Fully seeded ``RepositoryContainer`` (account, config, instrument,
        snapshots, etc.).
    stub_fdc
        A stub ``ProviderAIAgent`` that returns a canned
        ``FinalDecisionComposerOutput``.
    expected_status
        Expected ``SubmitResult.status`` (``"SUBMITTED"``, ``"SKIPPED"``, etc.).
    expected_quantity
        Expected ``SubmitResult.submit_response.quantity`` (``None`` when no order created).
    expected_guardrail_rule
        Expected guardrail blocking rule code (``"stale_snapshot_account"``,
        ``"stale_snapshot_run"``, or ``None`` when no guardrail block).
    expected_submit_call_count
        Expected number of ``broker.submit_order()`` calls.
        ``0`` for guard-blocked scenarios, ``1`` for submit scenarios.
    """

    name: str  # MUST end with _submit or _guard
    request: SubmitOrderRequest
    repos: RepositoryContainer
    stub_fdc: BrokerAdapter  # actually ProviderAIAgent, but type-erased for simplicity
    expected_status: str
    expected_quantity: Decimal | None
    expected_guardrail_rule: str | None
    expected_submit_call_count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(**kwargs: object) -> SubmitOrderRequest:
    """Build a minimal ``SubmitOrderRequest`` for test use."""
    overrides: dict[str, object] = {
        "client_order_id": "REPLAY-TEST-001",
        "correlation_id": "corr-replay-001",
        "account_ref": "test-account",
        "strategy_id": str(uuid4()),
        "symbol": "005930",
        "market": "KRX",
        "side": OrderSide.BUY,
        "order_type": OrderType.LIMIT,
        "quantity": Decimal("10"),
        "price": Decimal("50000"),
        "time_in_force": TimeInForce.DAY,
    }
    overrides.update(kwargs)
    return SubmitOrderRequest(**overrides)  # type: ignore[arg-type]


def _make_sizing_inputs(**overrides: object) -> SizingInputs:
    """Build a standard ``SizingInputs`` for replay testing."""
    defaults: dict[str, object] = {
        "decision_type": "BUY",
        "side": OrderSide.BUY,
        "requested_quantity": Decimal("10"),
        "requested_price": Decimal("50000"),
        "available_cash": Decimal("1000000"),
        "current_position_qty": Decimal("0"),
        "nav": Decimal("5000000"),
        "max_single_position_pct": Decimal("0.1"),
        "min_cash_buffer_pct": Decimal("0.05"),
        "max_order_value": Decimal("50000000"),
        "min_order_qty": Decimal("1"),
        "max_order_qty": Decimal("1000"),
        "lot_size": Decimal("1"),
    }
    defaults.update(overrides)
    return SizingInputs(**defaults)  # type: ignore[arg-type]


def _build_repos(
    *,
    seed_cash: Decimal | None = None,
    seed_position_qty: Decimal | None = None,
    seed_instrument_symbol: str = "005930",
    seed_account_alias: str = "test-account",
) -> RepositoryContainer:
    """Build a fully seeded ``RepositoryContainer`` for replay testing.

    Parameters
    ----------
    seed_cash
        If set, seeds a ``CashBalanceSnapshotEntity`` with this amount.
    seed_position_qty
        If set, seeds a ``PositionSnapshotEntity`` with this quantity.
    seed_instrument_symbol
        Symbol for the seeded instrument.
    seed_account_alias
        Alias for the seeded account.
    """
    repos = build_in_memory_repositories()
    now = datetime.now(timezone.utc)

    account = AccountEntity(
        account_id=uuid4(),
        client_id=uuid4(),
        broker_account_id=uuid4(),
        environment=Environment.PAPER,
        account_alias=seed_account_alias,
        account_masked="test-****",
        status="active",
    )
    repos.accounts._items[account.account_id] = account

    config_version = ConfigVersionEntity(
        config_version_id=uuid4(),
        client_id=account.client_id,
        environment=Environment.PAPER,
        version_tag="v1.0",
        config_json={},
        checksum="abc123",
        activated_at=now,
    )
    repos.config_versions._items[config_version.config_version_id] = config_version

    instrument = InstrumentEntity(
        instrument_id=uuid4(),
        symbol=seed_instrument_symbol,
        market_code="KRX",
        asset_class=AssetClass.KR_STOCK,
        currency="KRW",
        name="Samsung Electronics",
    )
    repos.instruments._items[instrument.instrument_id] = instrument

    if seed_cash is not None:
        cash_snapshot = CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=account.account_id,
            currency="KRW",
            available_cash=seed_cash,
            settled_cash=Decimal("0"),
            unsettled_cash=Decimal("0"),
            source_of_truth="broker",
            snapshot_at=now,
        )
        repos.cash_balance_snapshots._items[cash_snapshot.cash_balance_snapshot_id] = cash_snapshot

    if seed_position_qty is not None:
        pos_snapshot = PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=account.account_id,
            instrument_id=instrument.instrument_id,
            quantity=seed_position_qty,
            average_price=Decimal("50000"),
            market_price=Decimal("50000"),
            unrealized_pnl=Decimal("0"),
            source_of_truth="broker",
            snapshot_at=now,
        )
        repos.position_snapshots._items[pos_snapshot.position_snapshot_id] = pos_snapshot

    return repos


def _make_stub_fdc(
    decision_type: str = "APPROVE",
    side: str = "BUY",
    symbol: str = "005930",
    confidence: float = 0.8,
    conviction: float = 0.7,
    summary: str = "Replay test stub",
) -> object:
    """Build a stub FDC agent returning a canned output.

    Returns an object that satisfies the ``ProviderAIAgent`` protocol
    (``agent_name``, ``schema_version`` properties + ``run()`` method).
    """

    class _StubFDCAgent:
        @property
        def agent_name(self) -> str:
            return "final_decision_composer"

        @property
        def schema_version(self) -> str:
            return "1.0.0"

        async def run(self, request: object) -> FinalDecisionComposerOutput:
            return FinalDecisionComposerOutput(
                decision_type=decision_type,
                side=side,
                symbol=symbol,
                confidence=confidence,
                conviction=conviction,
                summary=summary,
            )

    return _StubFDCAgent()


# ---------------------------------------------------------------------------
# Replay scenarios
# ---------------------------------------------------------------------------

# Naming convention:
#   _submit  → pipeline proceeds through to broker submission
#   _guard   → pipeline stops at guardrail (Phase 4c)

# ── Scenario A: Happy path BUY ────────────────────────────────────────
# seed_cash=1,000,000, requested qty=10, price=50,000 (LIMIT).
# _resolve_buy_target_quantity():
#   20% of 1,000,000 = 200,000 → int(200,000 / 50,000) = 4주
#   ↓ capped by requested_quantity=10 (allocation can reduce, not increase)
#   cash constraint allows 20주, 4 ≤ 20 → no additional cap.
# Expected: SUBMITTED, qty=4, broker called once.
HAPPY_BUY = ReplayBundle(
    name="happy_buy_submit",
    request=_make_request(client_order_id="RP-HAPPY-001"),
    repos=_build_repos(
        seed_cash=Decimal("1000000"),
        seed_position_qty=Decimal("0"),
    ),
    stub_fdc=_make_stub_fdc(decision_type="APPROVE", side="BUY"),
    expected_status="SUBMITTED",
    expected_quantity=Decimal("4"),
    expected_guardrail_rule=None,
    expected_submit_call_count=1,
)

# ── Scenario B: REDUCE with position ──────────────────────────────────
# Current position = 10주. Request = SELL 5주 (부분 매도).
# Expected: SUBMITTED, qty=5 (requested quantity preserved), broker called once.
REDUCE_WITH_POSITION = ReplayBundle(
    name="reduce_with_position_submit",
    request=_make_request(
        client_order_id="RP-REDUCE-001",
        side=OrderSide.SELL,
        quantity=Decimal("5"),
    ),
    repos=_build_repos(
        seed_cash=Decimal("1000000"),
        seed_position_qty=Decimal("10"),
    ),
    stub_fdc=_make_stub_fdc(decision_type="REDUCE", side="SELL"),
    expected_status="SUBMITTED",
    expected_quantity=Decimal("5"),
    expected_guardrail_rule=None,
    expected_submit_call_count=1,
)

# ── Scenario C: EXIT full liquidation ─────────────────────────────────
# Current position = 10주. Request = SELL 10주 (전량 매도).
# Expected: SUBMITTED, qty=10 (full position), broker called once.
EXIT_FULL_LIQUIDATION = ReplayBundle(
    name="exit_full_liquidation_submit",
    request=_make_request(
        client_order_id="RP-EXIT-001",
        side=OrderSide.SELL,
        quantity=Decimal("10"),
    ),
    repos=_build_repos(
        seed_cash=Decimal("1000000"),
        seed_position_qty=Decimal("10"),
    ),
    stub_fdc=_make_stub_fdc(decision_type="EXIT", side="SELL"),
    expected_status="SUBMITTED",
    expected_quantity=Decimal("10"),
    expected_guardrail_rule=None,
    expected_submit_call_count=1,
)

# ── Scenario D: Stale snapshot guard (account-level) ──────────────────
# Cash snapshot이 전혀 없음 → _check_account_snapshot_freshness()가
# is_stale=True를 반환. stale_snapshot_account blocking rule code로 기록됨.
# Expected: SKIPPED, no order created, broker NOT called.
STALE_SNAPSHOT_GUARD = ReplayBundle(
    name="stale_snapshot_account_guard",
    request=_make_request(client_order_id="RP-STALE-001"),
    repos=_build_repos(
        seed_cash=None,
        seed_position_qty=None,
    ),
    stub_fdc=_make_stub_fdc(decision_type="APPROVE", side="BUY"),
    expected_status="SKIPPED",
    expected_quantity=None,
    expected_guardrail_rule="stale_snapshot_account",
    expected_submit_call_count=0,
)

# ── Scenario E: Cash constraint — quantity capped ─────────────────────
# 계산 근거:
#   seed_cash=100,000, requested qty=100, price=50,000 (LIMIT).
#   _resolve_buy_target_quantity():
#     20% of 100,000 = 20,000 → int(20,000 / 50,000) = 0 → min 1주
#     ↓ well within requested_quantity=100, so cap not triggered
#   cash constraint allows 2주 (100,000/50,000), 1 ≤ 2 → no additional cap.
#   lot_size=1 → 영향 없음.
#   최종 quantity = 1 (allocation-based, capped by requested_quantity).
# Expected: SUBMITTED, qty=1, broker called once.
CASH_CONSTRAINT_CAPPED = ReplayBundle(
    name="cash_constraint_capped_submit",
    request=_make_request(
        client_order_id="RP-CASH-CAP-001",
        quantity=Decimal("100"),
        price=Decimal("50000"),
    ),
    repos=_build_repos(
        seed_cash=Decimal("100000"),
        seed_position_qty=Decimal("0"),
    ),
    stub_fdc=_make_stub_fdc(decision_type="APPROVE", side="BUY"),
    expected_status="SUBMITTED",
    expected_quantity=Decimal("1"),
    expected_guardrail_rule=None,
    expected_submit_call_count=1,
)

# ── Canonical scenario list ───────────────────────────────────────────
# Used by both pytest parametrize and replay_verification.py.
REPLAY_SCENARIOS: list[ReplayBundle] = [
    HAPPY_BUY,
    REDUCE_WITH_POSITION,
    EXIT_FULL_LIQUIDATION,
    STALE_SNAPSHOT_GUARD,
    CASH_CONSTRAINT_CAPPED,
]
