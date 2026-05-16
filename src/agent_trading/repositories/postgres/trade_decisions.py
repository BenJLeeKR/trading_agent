from __future__ import annotations

import json
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import TradeDecisionEntity


class PostgresTradeDecisionRepository:
    """PostgreSQL implementation of ``TradeDecisionRepository``.

    Stores AI trading decisions in the ``trading.trade_decisions`` table.

    Milestone 5 expands the table with P0 (core decision) and P1 (extended
    analysis) fields while preserving backward compatibility with legacy
    columns (``agent_run_id``, ``instrument_id``, etc.).
    """

    __slots__ = ("_tx",)

    def __init__(self, tx: TransactionManager) -> None:
        self._tx = tx

    async def add(self, decision: TradeDecisionEntity) -> TradeDecisionEntity:
        row = await self._tx.connection.fetchrow(
            """
            INSERT INTO trading.trade_decisions
                (trade_decision_id,
                 decision_context_id,
                 -- P0: Core decision fields
                 decision_type, side,
                 strategy_id, symbol, market,
                 entry_style, entry_price,
                 quantity, max_order_value,
                 price_band_lower, price_band_upper,
                 -- P1: Extended analysis fields
                 expected_return_bps, expected_downside_bps,
                 net_expected_value_bps, final_trade_score,
                 minimum_required_edge_bps,
                 regime_label, strategy_fit_score,
                 risk_check_passed, compliance_check_passed, execution_check_passed,
                 failed_rule_codes, reason_codes,
                 opposing_evidence, exit_plan_json,
                 calculation_version,
                 agent_version_json, model_version_json, prompt_version_json,
                 -- Legacy fields
                 agent_run_id, instrument_id,
                 target_quantity, target_notional, limit_price,
                 confidence, rationale_summary, decision_json,
                 -- Axis 2: Source type
                 source_type,
                 -- Metadata
                 created_at)
            VALUES ($1, $2,
                    $3, $4,
                    $5, $6, $7,
                    $8, $9,
                    $10, $11,
                    $12, $13,
                    $14, $15,
                    $16, $17,
                    $18,
                    $19, $20,
                    $21, $22, $23,
                    $24::jsonb, $25::jsonb,
                    $26::jsonb, $27::jsonb,
                    $28,
                    $29::jsonb, $30::jsonb, $31::jsonb,
                    $32, $33,
                    $34, $35, $36,
                    $37, $38, $39::jsonb,
                    $40,
                    $41)
            RETURNING *
            """,
            # PK
            decision.trade_decision_id,
            decision.decision_context_id,
            # P0
            decision.decision_type.value if decision.decision_type else None,
            decision.side.value if decision.side else None,
            decision.strategy_id,
            decision.symbol,
            decision.market,
            decision.entry_style.value if decision.entry_style else None,
            decision.entry_price,
            decision.quantity,
            decision.max_order_value,
            decision.price_band_lower,
            decision.price_band_upper,
            # P1
            decision.expected_return_bps,
            decision.expected_downside_bps,
            decision.net_expected_value_bps,
            decision.final_trade_score,
            decision.minimum_required_edge_bps,
            decision.regime_label,
            decision.strategy_fit_score,
            decision.risk_check_passed,
            decision.compliance_check_passed,
            decision.execution_check_passed,
            json.dumps(decision.failed_rule_codes or []),
            json.dumps(decision.reason_codes or []),
            json.dumps(decision.opposing_evidence),
            json.dumps(decision.exit_plan_json),
            decision.calculation_version,
            json.dumps(decision.agent_version_json),
            json.dumps(decision.model_version_json),
            json.dumps(decision.prompt_version_json),
            # Legacy
            decision.agent_run_id,
            decision.instrument_id,
            decision.target_quantity,
            decision.target_notional,
            decision.limit_price,
            decision.confidence,
            decision.rationale_summary,
            json.dumps(decision.decision_json),
            # Axis 2: Source type
            decision.source_type,
            # Metadata
            decision.created_at,
        )
        return row_to_entity(row, TradeDecisionEntity)

    async def get(self, trade_decision_id: UUID) -> TradeDecisionEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.trade_decisions WHERE trade_decision_id = $1",
            trade_decision_id,
        )
        if row is None:
            return None
        return row_to_entity(row, TradeDecisionEntity)

    async def get_by_context(
        self, decision_context_id: UUID
    ) -> TradeDecisionEntity | None:
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.trade_decisions "
            "WHERE decision_context_id = $1",
            decision_context_id,
        )
        if row is None:
            return None
        return row_to_entity(row, TradeDecisionEntity)

    async def list_all(self) -> list[TradeDecisionEntity]:
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.trade_decisions ORDER BY created_at DESC",
        )
        return [row_to_entity(row, TradeDecisionEntity) for row in rows]
