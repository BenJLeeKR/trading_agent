from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from agent_trading.domain.entities import ExternalEventEntity, SymbolTradeStateEntity
from agent_trading.domain.enums import PipelineStopReason
from agent_trading.services.reverse_trade_hysteresis import (
    evaluate_recent_reverse_trade,
    evaluate_symbol_state_sell_hysteresis,
    evaluate_symbol_state_buy_hysteresis,
)


def test_recent_reverse_trade_blocks_same_signal_feature_snapshot() -> None:
    decision = evaluate_recent_reverse_trade(
        current_signal_feature_snapshot_id="snap-1",
        last_signal_feature_snapshot_id="snap-1",
        recent_opposite_order_count=1,
        latest_decision_type="exit",
        eligible_decision_types={"reduce", "exit", "sell"},
        cooldown_stop_reason=PipelineStopReason.SAME_SYMBOL_REENTRY_COOLDOWN.value,
        details={"reentry_recent_sell_order_count": "1"},
        snapshot_unchanged_detail_key="reentry_signal_feature_snapshot_unchanged",
        activity_flag_detail_key="reverse_activity_detected",
    )

    assert decision.blocked is True
    assert (
        decision.stop_reason
        == PipelineStopReason.REVERSE_TRADE_SAME_SIGNAL_FEATURE_SNAPSHOT.value
    )
    assert decision.details["reentry_signal_feature_snapshot_unchanged"] == "true"
    assert decision.details["reverse_activity_detected"] == "true"


def test_recent_reverse_trade_blocks_cooldown_when_snapshot_changed() -> None:
    decision = evaluate_recent_reverse_trade(
        current_signal_feature_snapshot_id="snap-2",
        last_signal_feature_snapshot_id="snap-1",
        recent_opposite_order_count=1,
        latest_decision_type="buy",
        eligible_decision_types={"approve", "buy"},
        cooldown_stop_reason=PipelineStopReason.HELD_POSITION_RECENT_BUY_SELL_COOLDOWN.value,
        details={"recent_buy_order_count": "1"},
        snapshot_unchanged_detail_key="buy_signal_feature_snapshot_unchanged",
        activity_flag_detail_key="buy_cooldown_position_unchanged_or_increased",
    )

    assert decision.blocked is True
    assert (
        decision.stop_reason
        == PipelineStopReason.HELD_POSITION_RECENT_BUY_SELL_COOLDOWN.value
    )
    assert decision.details["buy_signal_feature_snapshot_unchanged"] == "false"
    assert decision.details["buy_cooldown_position_unchanged_or_increased"] == "true"


def test_symbol_state_buy_hysteresis_blocks_same_snapshot_during_cooldown() -> None:
    now = datetime.now(timezone.utc)
    snapshot_id = uuid4()
    decision = evaluate_symbol_state_buy_hysteresis(
        symbol_state=SymbolTradeStateEntity(
            symbol_trade_state_id=uuid4(),
            account_id=uuid4(),
            instrument_id=uuid4(),
            symbol="000000",
            market="KOSPI",
            state="flat_cooldown",
            reentry_cooldown_until=now + timedelta(minutes=10),
            last_signal_feature_snapshot_id=snapshot_id,
            created_at=now,
            updated_at=now,
        ),
        current_signal_feature_snapshot_id=str(snapshot_id),
        now_utc=now,
    )

    assert decision.blocked is True
    assert decision.stop_reason == "ai_override_gate"
    assert decision.detail_code == "ai_override_reverse_same_signal_feature_blocked"


def test_symbol_state_buy_hysteresis_allows_when_cooldown_expired() -> None:
    now = datetime.now(timezone.utc)
    decision = evaluate_symbol_state_buy_hysteresis(
        symbol_state=SymbolTradeStateEntity(
            symbol_trade_state_id=uuid4(),
            account_id=uuid4(),
            instrument_id=uuid4(),
            symbol="000000",
            market="KOSPI",
            state="flat_cooldown",
            reentry_cooldown_until=now - timedelta(minutes=1),
            created_at=now,
            updated_at=now,
        ),
        current_signal_feature_snapshot_id=None,
        now_utc=now,
    )

    assert decision.blocked is False


def test_recent_reverse_trade_allows_when_event_novelty_present() -> None:
    decision = evaluate_recent_reverse_trade(
        current_signal_feature_snapshot_id="snap-2",
        last_signal_feature_snapshot_id="snap-1",
        recent_opposite_order_count=1,
        latest_decision_type="exit",
        eligible_decision_types={"reduce", "exit", "sell"},
        cooldown_stop_reason=PipelineStopReason.SAME_SYMBOL_REENTRY_COOLDOWN.value,
        event_novelty_passed=True,
        event_novelty_label="high",
    )

    assert decision.blocked is False
    assert decision.details["reentry_event_novelty_passed"] == "true"
    assert decision.details["reentry_event_novelty"] == "high"


def test_symbol_state_buy_hysteresis_blocks_without_event_novelty_and_edge() -> None:
    now = datetime.now(timezone.utc)
    decision = evaluate_symbol_state_buy_hysteresis(
        symbol_state=SymbolTradeStateEntity(
            symbol_trade_state_id=uuid4(),
            account_id=uuid4(),
            instrument_id=uuid4(),
            symbol="000000",
            market="KOSPI",
            state="flat_cooldown",
            reentry_cooldown_until=now + timedelta(minutes=10),
            last_signal_feature_snapshot_id=uuid4(),
            metadata_json={
                "holding_profile_policy": {
                    "last_exit_edge_after_cost_bps": "20",
                }
            },
            last_exit_at=now - timedelta(minutes=5),
            created_at=now,
            updated_at=now,
        ),
        current_signal_feature_snapshot_id=str(uuid4()),
        current_edge_after_cost_bps=Decimal("25"),
        recent_events=(),
        now_utc=now,
    )

    assert decision.blocked is True
    assert decision.detail_code == "ai_override_reverse_event_novelty_blocked"


def test_symbol_state_buy_hysteresis_allows_when_three_axes_pass() -> None:
    now = datetime.now(timezone.utc)
    snapshot_id = uuid4()
    decision = evaluate_symbol_state_buy_hysteresis(
        symbol_state=SymbolTradeStateEntity(
            symbol_trade_state_id=uuid4(),
            account_id=uuid4(),
            instrument_id=uuid4(),
            symbol="000000",
            market="KOSPI",
            state="flat_cooldown",
            reentry_cooldown_until=now + timedelta(minutes=10),
            last_signal_feature_snapshot_id=snapshot_id,
            metadata_json={
                "holding_profile_policy": {
                    "last_exit_edge_after_cost_bps": "20",
                }
            },
            last_exit_at=now - timedelta(minutes=5),
            created_at=now,
            updated_at=now,
        ),
        current_signal_feature_snapshot_id=str(uuid4()),
        current_edge_after_cost_bps=Decimal("35"),
        recent_events=(
            ExternalEventEntity(
                event_id=uuid4(),
                event_type="news",
                source_name="naver",
                published_at=now - timedelta(minutes=1),
                symbol="000000",
                market="KOSPI",
                severity="high",
                direction="positive",
                metadata={"novelty": "high", "supports_entry": True},
            ),
        ),
        now_utc=now,
    )

    assert decision.blocked is False


def test_symbol_state_sell_hysteresis_blocks_early_reduce_without_strong_reason() -> None:
    now = datetime.now(timezone.utc)
    decision = evaluate_symbol_state_sell_hysteresis(
        symbol_state=SymbolTradeStateEntity(
            symbol_trade_state_id=uuid4(),
            account_id=uuid4(),
            instrument_id=uuid4(),
            symbol="000000",
            market="KOSPI",
            state="held_active",
            holding_profile="core_swing",
            minimum_hold_until=now + timedelta(minutes=30),
            metadata_json={
                "holding_profile_policy": {
                    "last_entry_edge_after_cost_bps": "40",
                }
            },
            created_at=now,
            updated_at=now,
        ),
        current_edge_after_cost_bps=Decimal("30"),
        risk_output=None,
        recent_events=(),
        now_utc=now,
    )

    assert decision.blocked is True
    assert decision.detail_code == "held_position_exit_hysteresis_blocked"


def test_symbol_state_sell_hysteresis_allows_early_reduce_on_edge_collapse() -> None:
    now = datetime.now(timezone.utc)
    decision = evaluate_symbol_state_sell_hysteresis(
        symbol_state=SymbolTradeStateEntity(
            symbol_trade_state_id=uuid4(),
            account_id=uuid4(),
            instrument_id=uuid4(),
            symbol="000000",
            market="KOSPI",
            state="held_active",
            holding_profile="core_swing",
            minimum_hold_until=now + timedelta(minutes=30),
            metadata_json={
                "holding_profile_policy": {
                    "last_entry_edge_after_cost_bps": "40",
                }
            },
            created_at=now,
            updated_at=now,
        ),
        current_edge_after_cost_bps=Decimal("5"),
        risk_output=None,
        recent_events=(),
        now_utc=now,
    )

    assert decision.blocked is False
