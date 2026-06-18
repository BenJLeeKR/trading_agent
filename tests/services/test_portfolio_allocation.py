from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from agent_trading.domain.entities import (
    CashBalanceSnapshotEntity,
    ConfigVersionEntity,
    PositionSnapshotEntity,
    RiskLimitSnapshotEntity,
)
from agent_trading.domain.enums import Environment
from agent_trading.services.market_regime import MarketRegimeAssessment
from agent_trading.services.portfolio_allocation import assess_portfolio_allocation
from agent_trading.services.strategy_selection import StrategySelectionAssessment


def _make_config() -> ConfigVersionEntity:
    return ConfigVersionEntity(
        config_version_id=uuid4(),
        client_id=uuid4(),
        environment=Environment.PAPER,
        version_tag="v1",
        config_json={
            "risk": {
                "max_single_position_pct": "10",
                "max_gross_exposure_pct": "95",
            },
            "execution": {"max_order_value": "3000000"},
        },
        checksum="abc",
    )


def _make_regime(
    *,
    regime_label: str = "bullish_trend",
    volatility_regime: str = "normal_volatility",
    risk_tone: str = "risk_on",
) -> MarketRegimeAssessment:
    return MarketRegimeAssessment(
        regime_label=regime_label,
        volatility_regime=volatility_regime,
        risk_tone=risk_tone,
        confidence=0.8,
        half_life_hours=24,
        strategy_weights={"swing_momentum": 0.45},
        reason_codes=("trend_up",),
    )


def _make_strategy(*, time_horizon: str = "swing") -> StrategySelectionAssessment:
    return StrategySelectionAssessment(
        preferred_strategy="swing_momentum",
        allowed_strategies=("swing_momentum", "event_continuation"),
        preferred_entry_style="LIMIT",
        preferred_time_horizon=time_horizon,
        confidence=0.75,
        reason_codes=("bullish_trend_momentum",),
        metadata={"source_type": "core"},
    )


def test_assess_portfolio_allocation_builds_buy_budget() -> None:
    now = datetime.now(timezone.utc)
    result = assess_portfolio_allocation(
        symbol="005930",
        source_type="core",
        config_version=_make_config(),
        position_snapshot=PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=uuid4(),
            instrument_id=uuid4(),
            quantity=Decimal("100"),
            average_price=Decimal("50000"),
            market_price=Decimal("50000"),
            unrealized_pnl=Decimal("0"),
            source_of_truth="broker",
            snapshot_at=now,
        ),
        cash_balance_snapshot=CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=uuid4(),
            currency="KRW",
            available_cash=Decimal("8000000"),
            settled_cash=Decimal("8000000"),
            unsettled_cash=Decimal("0"),
            orderable_amount=Decimal("7000000"),
            source_of_truth="broker",
            snapshot_at=now,
            total_asset=Decimal("100000000"),
        ),
        risk_limit_snapshot=RiskLimitSnapshotEntity(
            risk_limit_snapshot_id=uuid4(),
            account_id=uuid4(),
            snapshot_at=now,
            nav=Decimal("100000000"),
            gross_exposure_pct=Decimal("40"),
            kill_switch_active=False,
            symbol_exposure_json={"005930": {"weight_pct": 5.0}},
        ),
        market_regime=_make_regime(),
        strategy_selection=_make_strategy(),
    )

    assert result is not None
    assert result.target_weight_pct == 8.0
    assert result.current_weight_pct == 5.0
    assert result.remaining_concentration_pct == 5.0
    assert result.max_new_capital_pct == 3.0
    assert result.recommended_max_order_value == Decimal("3000000")
    assert result.allocation_bias == "accumulate"


def test_assess_portfolio_allocation_caps_risk_off_held_position() -> None:
    now = datetime.now(timezone.utc)
    result = assess_portfolio_allocation(
        symbol="000660",
        source_type="held_position",
        config_version=_make_config(),
        position_snapshot=PositionSnapshotEntity(
            position_snapshot_id=uuid4(),
            account_id=uuid4(),
            instrument_id=uuid4(),
            quantity=Decimal("200"),
            average_price=Decimal("50000"),
            market_price=Decimal("60000"),
            unrealized_pnl=Decimal("0"),
            source_of_truth="broker",
            snapshot_at=now,
            evaluation_amount=Decimal("12000000"),
        ),
        cash_balance_snapshot=CashBalanceSnapshotEntity(
            cash_balance_snapshot_id=uuid4(),
            account_id=uuid4(),
            currency="KRW",
            available_cash=Decimal("1000000"),
            settled_cash=Decimal("1000000"),
            unsettled_cash=Decimal("0"),
            source_of_truth="broker",
            snapshot_at=now,
            total_asset=Decimal("60000000"),
        ),
        risk_limit_snapshot=RiskLimitSnapshotEntity(
            risk_limit_snapshot_id=uuid4(),
            account_id=uuid4(),
            snapshot_at=now,
            nav=Decimal("60000000"),
            gross_exposure_pct=Decimal("92"),
            kill_switch_active=False,
        ),
        market_regime=_make_regime(
            regime_label="bearish_trend",
            volatility_regime="high_volatility",
            risk_tone="risk_off",
        ),
        strategy_selection=_make_strategy(time_horizon="short"),
    )

    assert result is not None
    assert result.target_weight_pct == 2.5
    assert result.current_weight_pct == 20.0
    assert result.max_new_capital_pct == 0.0
    assert result.allocation_bias == "de_risk"
    assert "single_position_limit_reached" in result.reason_codes
    assert "portfolio_risk_off_cap" in result.reason_codes
