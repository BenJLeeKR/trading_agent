from __future__ import annotations

from agent_trading.services.common_types import AssembledContext


def append_shared_deterministic_context_sections(
    lines: list[str],
    context: AssembledContext,
    *,
    profile: str,
    include_portfolio_allocation: bool = True,
) -> None:
    """Signal/regime/strategy/portfolio/trigger section을 공통 렌더링한다."""
    indent = "  " if profile == "ai_risk" else ""

    _append_signal_feature_snapshot(
        lines,
        context=context,
        indent=indent,
    )
    _append_instrument_profile(
        lines,
        context=context,
        indent=indent,
    )
    _append_market_regime(
        lines,
        context=context,
        indent=indent,
    )
    _append_strategy_selection(
        lines,
        context=context,
        indent=indent,
    )
    if include_portfolio_allocation:
        _append_portfolio_allocation(
            lines,
            context=context,
            indent=indent,
            profile=profile,
        )
    _append_deterministic_trigger(
        lines,
        context=context,
        indent=indent,
    )


def _append_signal_feature_snapshot(
    lines: list[str],
    *,
    context: AssembledContext,
    indent: str,
) -> None:
    signal_snapshot = context.signal_feature_snapshot
    if signal_snapshot is None:
        return

    lines.append("")
    lines.append("=== Signal Feature Snapshot ===")
    lines.append(f"{indent}Snapshot at: {signal_snapshot.snapshot_at}")
    lines.append(f"{indent}Timeframe: {signal_snapshot.timeframe}")
    lines.append(
        f"{indent}Feature set version: {signal_snapshot.feature_set_version}"
    )
    lines.append(f"{indent}Bar count: {signal_snapshot.bar_count}")
    if signal_snapshot.overall_score is not None:
        lines.append(f"{indent}Overall score: {signal_snapshot.overall_score}")
    if signal_snapshot.fast_score is not None:
        lines.append(f"{indent}Fast score: {signal_snapshot.fast_score}")
    if signal_snapshot.slow_score is not None:
        lines.append(f"{indent}Slow score: {signal_snapshot.slow_score}")
    if signal_snapshot.return_1m_pct is not None:
        lines.append(f"{indent}Return 1M %: {signal_snapshot.return_1m_pct}")
    if signal_snapshot.return_3m_pct is not None:
        lines.append(f"{indent}Return 3M %: {signal_snapshot.return_3m_pct}")
    if signal_snapshot.price_vs_sma_20_pct is not None:
        lines.append(
            f"{indent}Price vs SMA20 %: {signal_snapshot.price_vs_sma_20_pct}"
        )
    if signal_snapshot.price_vs_sma_60_pct is not None:
        lines.append(
            f"{indent}Price vs SMA60 %: {signal_snapshot.price_vs_sma_60_pct}"
        )
    if signal_snapshot.rsi_14 is not None:
        lines.append(f"{indent}RSI14: {signal_snapshot.rsi_14}")
    if signal_snapshot.atr_14_pct is not None:
        lines.append(f"{indent}ATR14 %: {signal_snapshot.atr_14_pct}")
    if signal_snapshot.volatility_20d_pct is not None:
        lines.append(
            f"{indent}Volatility 20D %: {signal_snapshot.volatility_20d_pct}"
        )
    if signal_snapshot.volume_surge_ratio is not None:
        lines.append(
            f"{indent}Volume surge ratio: {signal_snapshot.volume_surge_ratio}"
        )
    if signal_snapshot.reason_codes:
        lines.append(
            f"{indent}Signal reason codes: "
            f"{', '.join(signal_snapshot.reason_codes)}"
        )


def _append_instrument_profile(
    lines: list[str],
    *,
    context: AssembledContext,
    indent: str,
) -> None:
    market_segment = context.instrument_market_segment
    index_memberships = context.instrument_index_memberships
    if not market_segment and not index_memberships:
        return

    lines.append("")
    lines.append("=== Instrument Profile ===")
    if market_segment:
        lines.append(f"{indent}Market segment: {market_segment}")
    if index_memberships:
        lines.append(
            f"{indent}Index memberships: {', '.join(index_memberships)}"
        )


def _append_market_regime(
    lines: list[str],
    *,
    context: AssembledContext,
    indent: str,
) -> None:
    market_regime = context.market_regime
    if market_regime is None:
        return

    lines.append("")
    lines.append("=== Market Regime ===")
    lines.append(f"{indent}Regime label: {market_regime.regime_label}")
    lines.append(
        f"{indent}Volatility regime: {market_regime.volatility_regime}"
    )
    lines.append(f"{indent}Risk tone: {market_regime.risk_tone}")
    lines.append(f"{indent}Confidence: {market_regime.confidence}")
    lines.append(f"{indent}Half-life hours: {market_regime.half_life_hours}")
    if market_regime.reason_codes:
        lines.append(
            f"{indent}Regime reason codes: "
            f"{', '.join(market_regime.reason_codes)}"
        )
    if market_regime.strategy_weights:
        strategy_weights = ", ".join(
            f"{key}={value:.2f}"
            for key, value in market_regime.strategy_weights.items()
        )
        lines.append(f"{indent}Strategy weights: {strategy_weights}")


def _append_strategy_selection(
    lines: list[str],
    *,
    context: AssembledContext,
    indent: str,
) -> None:
    strategy_selection = context.strategy_selection
    if strategy_selection is None:
        return

    lines.append("")
    lines.append("=== Strategy Selection ===")
    lines.append(
        f"{indent}Preferred strategy: {strategy_selection.preferred_strategy}"
    )
    lines.append(
        f"{indent}Allowed strategies: "
        f"{', '.join(strategy_selection.allowed_strategies)}"
    )
    lines.append(
        f"{indent}Preferred execution style: "
        f"{strategy_selection.preferred_entry_style}"
    )
    lines.append(
        f"{indent}Preferred time horizon: "
        f"{strategy_selection.preferred_time_horizon}"
    )
    lines.append(f"{indent}Confidence: {strategy_selection.confidence}")
    if strategy_selection.reason_codes:
        lines.append(
            f"{indent}Strategy selection reasons: "
            f"{', '.join(strategy_selection.reason_codes)}"
        )


def _append_portfolio_allocation(
    lines: list[str],
    *,
    context: AssembledContext,
    indent: str,
    profile: str,
) -> None:
    portfolio_allocation = context.portfolio_allocation
    if portfolio_allocation is None:
        return

    lines.append("")
    lines.append("=== Portfolio Allocation ===")
    if profile == "ai_risk":
        lines.append(
            f"{indent}Target weight: {portfolio_allocation.target_weight_pct:.1f}%"
        )
        if portfolio_allocation.current_weight_pct is not None:
            lines.append(
                f"{indent}Current weight: "
                f"{portfolio_allocation.current_weight_pct:.1f}%"
            )
        else:
            lines.append(f"{indent}Current weight: N/A")
        lines.append(
            f"{indent}Allocation bias: {portfolio_allocation.allocation_bias}"
        )
        lines.append(
            f"{indent}Max new capital budget: "
            f"{portfolio_allocation.max_new_capital_pct:.1f}%"
        )
        if portfolio_allocation.available_allocation_cash is not None:
            lines.append(
                f"{indent}Available allocation cash: "
                f"{portfolio_allocation.available_allocation_cash}"
            )
        if portfolio_allocation.recommended_max_order_value is not None:
            lines.append(
                f"{indent}Recommended max order value: "
                f"{portfolio_allocation.recommended_max_order_value}"
            )
    else:
        lines.append(
            f"{indent}Target weight: {portfolio_allocation.target_weight_pct}"
        )
        lines.append(
            f"{indent}Max single position limit: "
            f"{portfolio_allocation.max_single_position_pct}"
        )
        if portfolio_allocation.current_weight_pct is not None:
            lines.append(
                f"{indent}Current weight: {portfolio_allocation.current_weight_pct}"
            )
        if portfolio_allocation.remaining_concentration_pct is not None:
            lines.append(
                f"{indent}Remaining concentration budget: "
                f"{portfolio_allocation.remaining_concentration_pct}"
            )
        if portfolio_allocation.remaining_gross_budget_pct is not None:
            lines.append(
                f"{indent}Remaining gross budget: "
                f"{portfolio_allocation.remaining_gross_budget_pct}"
            )
        lines.append(
            f"{indent}Max new capital budget: "
            f"{portfolio_allocation.max_new_capital_pct}"
        )
        lines.append(
            f"{indent}Allocation bias: {portfolio_allocation.allocation_bias}"
        )
        if portfolio_allocation.recommended_max_order_value is not None:
            lines.append(
                f"{indent}Recommended max order value: "
                f"{portfolio_allocation.recommended_max_order_value}"
            )
    if portfolio_allocation.reason_codes:
        lines.append(
            f"{indent}Portfolio reason codes: "
            f"{', '.join(portfolio_allocation.reason_codes)}"
        )


def _append_deterministic_trigger(
    lines: list[str],
    *,
    context: AssembledContext,
    indent: str,
) -> None:
    deterministic_trigger = context.deterministic_trigger
    if deterministic_trigger is None:
        return

    lines.append("")
    lines.append("=== Deterministic Trigger ===")
    lines.append(
        f"{indent}Primary candidate: "
        f"{deterministic_trigger.primary_candidate}"
    )
    lines.append(
        f"{indent}Candidate set: "
        f"{', '.join(deterministic_trigger.candidate_set)}"
    )
    lines.append(
        f"{indent}Candidate confidence: "
        f"{deterministic_trigger.candidate_confidence}"
    )
    if deterministic_trigger.entry_score is not None:
        lines.append(f"{indent}Entry score: {deterministic_trigger.entry_score}")
    if deterministic_trigger.exit_score is not None:
        lines.append(f"{indent}Exit score: {deterministic_trigger.exit_score}")
    if deterministic_trigger.watch_score is not None:
        lines.append(f"{indent}Watch score: {deterministic_trigger.watch_score}")
    if deterministic_trigger.reason_codes:
        lines.append(
            f"{indent}Trigger reason codes: "
            f"{', '.join(deterministic_trigger.reason_codes)}"
        )
