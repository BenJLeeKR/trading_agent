from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import AccountEntity, TradeDecisionEntity
from agent_trading.domain.enums import DecisionType, EntryStyle, OrderSide
from agent_trading.repositories.container import RepositoryContainer


@pytest.fixture
async def seeded_decision_context(
    seeded_postgres_data: RepositoryContainer,
) -> UUID:
    """Return the decision_context_id already seeded by ``seeded_postgres_data``.

    Filters by ``correlation_id = 'test-correlation'`` to avoid picking up
    pre-existing rows left by application runs (e.g. ``paper-loop-*``).
    """
    conn = seeded_postgres_data.unit_of_work.connection
    row = await conn.fetchrow(
        "SELECT decision_context_id FROM trading.decision_contexts "
        "WHERE correlation_id = 'test-correlation' LIMIT 1"
    )
    assert row is not None, "seeded_postgres_data must seed a decision_context"
    return row["decision_context_id"]


@pytest.fixture
async def seeded_strategy_id(
    seeded_postgres_data: RepositoryContainer,
) -> UUID:
    """Return the strategy_id already seeded by ``seeded_postgres_data``."""
    conn = seeded_postgres_data.unit_of_work.connection
    row = await conn.fetchrow(
        "SELECT strategy_id FROM trading.strategies LIMIT 1"
    )
    assert row is not None, "seeded_postgres_data must seed a strategy"
    return row["strategy_id"]


def _make_full_decision(
    decision_context_id: UUID,
    strategy_id: UUID,
    *,
    trade_decision_id: UUID | None = None,
    source_type: str | None = "market_overlay",
) -> TradeDecisionEntity:
    """Helper: build a fully populated TradeDecisionEntity for testing.

    Parameters
    ----------
    source_type : str | None
        Origin of this symbol's inclusion. Default ``"market_overlay"``
        so that source_type round-trip tests are meaningful.
    """
    now = datetime.now(timezone.utc)
    return TradeDecisionEntity(
        trade_decision_id=trade_decision_id or uuid4(),
        decision_context_id=decision_context_id,
        decision_type=DecisionType.APPROVE,
        side=OrderSide.BUY,
        strategy_id=strategy_id,
        symbol="AAPL",
        market="NASDAQ",
        entry_style=EntryStyle.LIMIT,
        entry_price=Decimal("150.00"),
        quantity=Decimal("100"),
        max_order_value=Decimal("15000.00"),
        price_band_lower=Decimal("145.00"),
        price_band_upper=Decimal("155.00"),
        # P1 fields
        expected_return_bps=Decimal("50.00"),
        expected_downside_bps=Decimal("20.00"),
        net_expected_value_bps=Decimal("30.00"),
        final_trade_score=Decimal("0.85"),
        minimum_required_edge_bps=Decimal("10.00"),
        regime_label="bullish",
        strategy_fit_score=Decimal("0.90"),
        risk_check_passed=True,
        compliance_check_passed=True,
        execution_check_passed=True,
        failed_rule_codes=[],
        reason_codes=["RSI_OVERSOLD", "TREND_FOLLOWING"],
        opposing_evidence={"news_sentiment": "negative"},
        exit_plan_json={"stop_loss": "145.00"},
        calculation_version="v2.1",
        agent_version_json={"ei": "1.0", "ar": "1.0", "fdc": "1.0"},
        model_version_json={"gpt": "4.0"},
        prompt_version_json={"system": "v3", "user": "v3"},
        # Legacy fields
        agent_run_id=None,
        instrument_id=None,
        target_quantity=Decimal("100"),
        target_notional=Decimal("15000.00"),
        limit_price=Decimal("150.00"),
        confidence=Decimal("0.80"),
        rationale_summary="Strong buy signal on RSI oversold + trend confirmation",
        decision_json={"source": "test", "reason": "synthetic"},
        # Axis 2: Source type
        source_type=source_type,
        created_at=now,
    )


def _make_minimal_decision(
    decision_context_id: UUID,
    strategy_id: UUID,
    *,
    trade_decision_id: UUID | None = None,
) -> TradeDecisionEntity:
    """Helper: build a TradeDecisionEntity with only required P0 fields."""
    now = datetime.now(timezone.utc)
    return TradeDecisionEntity(
        trade_decision_id=trade_decision_id or uuid4(),
        decision_context_id=decision_context_id,
        decision_type=DecisionType.APPROVE,
        side=OrderSide.BUY,
        strategy_id=strategy_id,
        symbol="AAPL",
        market="NASDAQ",
        entry_style=EntryStyle.LIMIT,
        created_at=now,
    )


# ============================================================================
# Test 1: Full round-trip — add + read-back with all fields
# ============================================================================


@pytest.mark.asyncio
async def test_add_and_read_back(
    seeded_postgres_data: RepositoryContainer,
    seeded_decision_context: UUID,
    seeded_strategy_id: UUID,
) -> None:
    """Verify that ``add()`` succeeds and ``get_by_context()`` returns
    an equivalent entity with all P0/P1/legacy fields preserved."""
    repos = seeded_postgres_data

    # Create a fully populated decision
    decision = _make_full_decision(
        decision_context_id=seeded_decision_context,
        strategy_id=seeded_strategy_id,
    )

    # Add via repository
    saved = await repos.trade_decisions.add(decision)
    assert saved.trade_decision_id == decision.trade_decision_id
    assert saved.decision_type == DecisionType.APPROVE
    assert saved.side == OrderSide.BUY
    assert saved.symbol == "AAPL"

    # Read back via get_by_context
    fetched = await repos.trade_decisions.get_by_context(seeded_decision_context)
    assert fetched is not None
    assert fetched.trade_decision_id == decision.trade_decision_id
    assert fetched.decision_type == DecisionType.APPROVE
    assert fetched.side == OrderSide.BUY
    assert fetched.strategy_id == seeded_strategy_id
    assert fetched.symbol == "AAPL"
    assert fetched.market == "NASDAQ"
    assert fetched.entry_style == EntryStyle.LIMIT
    assert fetched.entry_price == Decimal("150.00")
    assert fetched.quantity == Decimal("100")
    assert fetched.max_order_value == Decimal("15000.00")
    assert fetched.price_band_lower == Decimal("145.00")
    assert fetched.price_band_upper == Decimal("155.00")
    assert fetched.expected_return_bps == Decimal("50.00")
    assert fetched.net_expected_value_bps == Decimal("30.00")
    assert fetched.final_trade_score == Decimal("0.85")
    assert fetched.risk_check_passed is True
    assert fetched.compliance_check_passed is True
    assert fetched.execution_check_passed is True
    assert fetched.failed_rule_codes == []
    assert fetched.reason_codes == ["RSI_OVERSOLD", "TREND_FOLLOWING"]
    assert fetched.opposing_evidence == {"news_sentiment": "negative"}
    assert fetched.exit_plan_json == {"stop_loss": "145.00"}
    assert fetched.calculation_version == "v2.1"
    # Legacy fields
    assert fetched.target_quantity == Decimal("100")
    assert fetched.target_notional == Decimal("15000.00")
    assert fetched.limit_price == Decimal("150.00")
    assert fetched.confidence == Decimal("0.80")
    assert fetched.rationale_summary == "Strong buy signal on RSI oversold + trend confirmation"
    # Axis 2: Source type
    assert fetched.source_type == "market_overlay"


# ============================================================================
# Test 2: Minimal fields only — ensure no NOT NULL surprises
# ============================================================================


@pytest.mark.asyncio
async def test_add_minimal_fields(
    seeded_postgres_data: RepositoryContainer,
    seeded_decision_context: UUID,
    seeded_strategy_id: UUID,
) -> None:
    """Verify that ``add()`` succeeds with only required P0 fields.
    This ensures no hidden ``NOT NULL`` constraint blocks the INSERT."""
    repos = seeded_postgres_data

    decision = _make_minimal_decision(
        decision_context_id=seeded_decision_context,
        strategy_id=seeded_strategy_id,
    )

    saved = await repos.trade_decisions.add(decision)
    assert saved.trade_decision_id == decision.trade_decision_id
    assert saved.decision_type == DecisionType.APPROVE
    assert saved.side == OrderSide.BUY

    # Read back to confirm persistence
    fetched = await repos.trade_decisions.get_by_context(seeded_decision_context)
    assert fetched is not None
    assert fetched.trade_decision_id == decision.trade_decision_id
    # P0 optional fields should be None
    assert fetched.entry_price is None
    assert fetched.quantity is None
    assert fetched.max_order_value is None
    # P1 fields should be None
    assert fetched.expected_return_bps is None
    assert fetched.final_trade_score is None
    # Legacy fields should be None
    assert fetched.target_quantity is None
    assert fetched.limit_price is None
    assert fetched.confidence is None
    assert fetched.rationale_summary is None


# ============================================================================
# Test 3: Verify decision column is nullable (post-migration assertion)
# ============================================================================


@pytest.mark.asyncio
async def test_decision_column_nullable(
    seeded_postgres_data: RepositoryContainer,
    seeded_decision_context: UUID,
    seeded_strategy_id: UUID,
) -> None:
    """Directly insert a row with ``decision = NULL`` to prove the
    ``NOT NULL`` constraint has been lifted by migration 0009.

    If this test fails with a ``NOT NULL`` constraint violation,
    migration 0009 has not been applied."""
    repos = seeded_postgres_data
    conn = repos.unit_of_work.connection
    trade_decision_id = uuid4()
    now = datetime.now(timezone.utc)

    # Insert a row omitting the 'decision' column (NULL by omission)
    row = await conn.fetchrow(
        """
        INSERT INTO trading.trade_decisions
            (trade_decision_id, decision_context_id,
             decision_type, side, strategy_id, symbol, market,
             entry_style, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING trade_decision_id, decision
        """,
        trade_decision_id,
        seeded_decision_context,
        "approve",
        "buy",
        seeded_strategy_id,
        "AAPL",
        "NASDAQ",
        "limit",
        now,
    )
    assert row is not None, "INSERT with NULL decision should succeed"
    assert row["trade_decision_id"] == trade_decision_id
    assert row["decision"] is None, (
        f"Expected decision=NULL, got {row['decision']!r}. "
        "Migration 0009 (DROP NOT NULL) may not have been applied."
    )

    # Confirm read-back via repository also works
    fetched = await repos.trade_decisions.get_by_context(seeded_decision_context)
    assert fetched is not None
    # The second insert created a new row, but get_by_context returns the first
    # one by UNIQUE constraint (decision_context_id is UNIQUE).
    # We just verify the query doesn't crash.


# ============================================================================
# Test 4: Source type round-trip — all five values
# ============================================================================


@pytest.mark.asyncio
async def test_source_type_round_trip(
    seeded_postgres_data: RepositoryContainer,
    seeded_decision_context: UUID,
    seeded_strategy_id: UUID,
    sample_account: AccountEntity,
) -> None:
    """Verify that ``source_type`` is preserved through add → read-back
    for all five expected values."""
    repos = seeded_postgres_data
    account_id = sample_account.account_id

    # Resolve the config_version_id from the seeded decision_context
    conn = repos.unit_of_work.connection
    dc_row = await conn.fetchrow(
        "SELECT config_version_id FROM trading.decision_contexts "
        "WHERE decision_context_id = $1",
        seeded_decision_context,
    )
    assert dc_row is not None, "seeded decision_context must have a config_version_id"
    config_version_id: UUID = dc_row["config_version_id"]

    for expected_st in ("core", "held_position", "event_overlay", "market_overlay", "manual"):
        # Use a fresh context for each iteration (unique constraint)
        ctx_id = uuid4()
        await conn.execute(
            "INSERT INTO trading.decision_contexts "
            "(decision_context_id, account_id, strategy_id, config_version_id, "
            " market_timestamp, correlation_id, created_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7)",
            ctx_id,
            account_id,
            seeded_strategy_id,
            config_version_id,
            datetime.now(timezone.utc),
            f"source-type-test-{expected_st}",
            datetime.now(timezone.utc),
        )

        decision = _make_full_decision(
            decision_context_id=ctx_id,
            strategy_id=seeded_strategy_id,
            source_type=expected_st,
        )
        saved = await repos.trade_decisions.add(decision)
        assert saved.source_type == expected_st, (
            f"Saved source_type mismatch: expected={expected_st!r} got={saved.source_type!r}"
        )

        fetched = await repos.trade_decisions.get_by_context(ctx_id)
        assert fetched is not None
        assert fetched.source_type == expected_st, (
            f"Fetched source_type mismatch: expected={expected_st!r} got={fetched.source_type!r}"
        )


# ============================================================================
# Test 5: NULL source_type compatibility (existing rows)
# ============================================================================


@pytest.mark.asyncio
async def test_source_type_null_compatibility(
    seeded_postgres_data: RepositoryContainer,
    seeded_decision_context: UUID,
    seeded_strategy_id: UUID,
    sample_account: AccountEntity,
) -> None:
    """Verify that a row with ``source_type = NULL`` can be inserted directly
    (simulating existing rows that predate migration 0013) and read back
    successfully with ``source_type = None``."""
    repos = seeded_postgres_data
    conn = repos.unit_of_work.connection
    now = datetime.now(timezone.utc)
    account_id = sample_account.account_id

    # Resolve the config_version_id from the seeded decision_context
    dc_row = await conn.fetchrow(
        "SELECT config_version_id FROM trading.decision_contexts "
        "WHERE decision_context_id = $1",
        seeded_decision_context,
    )
    assert dc_row is not None, "seeded decision_context must have a config_version_id"
    config_version_id: UUID = dc_row["config_version_id"]

    # Insert a row via raw SQL, omitting source_type (NULL by omission)
    td_id = uuid4()
    ctx_id = uuid4()
    await conn.execute(
        "INSERT INTO trading.decision_contexts "
        "(decision_context_id, account_id, strategy_id, config_version_id, "
        " market_timestamp, correlation_id, created_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        ctx_id,
        account_id,
        seeded_strategy_id,
        config_version_id,
        now,
        "null-source-type-test",
        now,
    )

    row = await conn.fetchrow(
        """
        INSERT INTO trading.trade_decisions
            (trade_decision_id, decision_context_id,
             decision_type, side, strategy_id, symbol, market,
             entry_style, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING trade_decision_id, source_type
        """,
        td_id,
        ctx_id,
        "approve",
        "buy",
        seeded_strategy_id,
        "AAPL",
        "NASDAQ",
        "limit",
        now,
    )
    assert row is not None, "INSERT with NULL source_type should succeed"
    assert row["source_type"] is None, (
        f"Expected source_type=NULL, got {row['source_type']!r}. "
        "Migration 0013 may not have been applied."
    )

    # Read back via repository
    fetched = await repos.trade_decisions.get_by_context(ctx_id)
    assert fetched is not None
    assert fetched.source_type is None, (
        f"Expected source_type=None, got {fetched.source_type!r}"
    )
