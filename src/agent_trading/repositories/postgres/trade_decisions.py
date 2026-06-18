from __future__ import annotations

import json
from decimal import Decimal
from uuid import UUID

from agent_trading.db.row_mapper import row_to_entity
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import TradeDecisionEntity
from agent_trading.repositories.contracts import TradeDecisionRow


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
        """최신 TD 반환 (ORDER BY created_at DESC, trade_decision_id DESC LIMIT 1)."""
        row = await self._tx.connection.fetchrow(
            "SELECT * FROM trading.trade_decisions "
            "WHERE decision_context_id = $1 "
            "ORDER BY created_at DESC, trade_decision_id DESC "
            "LIMIT 1",
            decision_context_id,
        )
        if row is None:
            return None
        return row_to_entity(row, TradeDecisionEntity)

    async def list_by_context(
        self, decision_context_id: UUID
    ) -> list[TradeDecisionEntity]:
        """주어진 decision_context에 속한 모든 TD를 최신순으로 반환."""
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.trade_decisions "
            "WHERE decision_context_id = $1 "
            "ORDER BY created_at DESC, trade_decision_id DESC",
            decision_context_id,
        )
        return [row_to_entity(row, TradeDecisionEntity) for row in rows]

    async def list_all(self) -> list[TradeDecisionEntity]:
        rows = await self._tx.connection.fetch(
            "SELECT * FROM trading.trade_decisions ORDER BY created_at DESC",
        )
        return [row_to_entity(row, TradeDecisionEntity) for row in rows]

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
        """
        where_parts: list[str] = []
        params: list[object] = []
        param_idx = 1
        execution_status_expr = """
            CASE
                WHEN eas.status IS NOT NULL THEN
                    CASE
                        WHEN eas.status IN ('running', 'stopped') THEN 'pipeline_stopped'
                        WHEN eas.status = 'submitted' THEN 'submitted'
                        WHEN eas.status = 'failed' THEN 'rejected'
                        WHEN eas.status = 'non_trade' THEN 'non_trade'
                        WHEN eas.status = 'reconcile_required' THEN 'reconcile_required'
                        ELSE 'pipeline_stopped'
                    END
                WHEN o.order_request_id IS NOT NULL THEN
                    CASE
                        WHEN o.status IN ('SUBMITTED', 'REJECTED', 'RECONCILE_REQUIRED') THEN LOWER(o.status)
                        ELSE 'order_created'
                    END
                WHEN LOWER(CAST(td.decision_type AS text)) IN ('hold', 'watch') THEN 'non_trade'
                ELSE 'trade_decision_only'
            END
        """

        if decision_context_id is not None:
            where_parts.append(f"td.decision_context_id = ${param_idx}")
            params.append(decision_context_id)
            param_idx += 1
        if created_date_kst is not None:
            where_parts.append(f"(td.created_at AT TIME ZONE 'Asia/Seoul')::date = ${param_idx}")
            params.append(created_date_kst)
            param_idx += 1
        if side is not None:
            where_parts.append(f"LOWER(CAST(td.side AS text)) = ${param_idx}")
            params.append(side.lower())
            param_idx += 1
        if source_type is not None:
            where_parts.append(f"LOWER(COALESCE(td.source_type, '')) = ${param_idx}")
            params.append(source_type.lower())
            param_idx += 1
        if decision_type is not None:
            where_parts.append(f"LOWER(CAST(td.decision_type AS text)) = ${param_idx}")
            params.append(decision_type.lower())
            param_idx += 1
        if execution_status is not None:
            where_parts.append(f"{execution_status_expr} = ${param_idx}")
            params.append(execution_status.lower())
            param_idx += 1
        if latest_stop_reason is not None:
            where_parts.append(
                "("
                "SELECT LOWER(COALESCE(ea2.stop_reason, '')) "
                "FROM trading.execution_attempts ea2 "
                "WHERE ea2.trade_decision_id = td.trade_decision_id "
                "ORDER BY ea2.started_at DESC LIMIT 1"
                f") = ${param_idx}"
            )
            params.append(latest_stop_reason.lower())
            param_idx += 1
        if latest_stop_reason_prefix is not None:
            where_parts.append(
                "("
                "SELECT LOWER(COALESCE(ea2.stop_reason, '')) "
                "FROM trading.execution_attempts ea2 "
                "WHERE ea2.trade_decision_id = td.trade_decision_id "
                "ORDER BY ea2.started_at DESC LIMIT 1"
                f") LIKE ${param_idx}"
            )
            params.append(f"{latest_stop_reason_prefix.lower()}%")
            param_idx += 1
        if has_order is True:
            where_parts.append(
                "EXISTS (SELECT 1 FROM trading.order_requests o2 "
                "WHERE o2.trade_decision_id = td.trade_decision_id)"
            )
        elif has_order is False:
            where_parts.append(
                "NOT EXISTS (SELECT 1 FROM trading.order_requests o2 "
                "WHERE o2.trade_decision_id = td.trade_decision_id)"
            )
        where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

        # Total count query
        base_from_sql = """
            FROM trading.trade_decisions td
            LEFT JOIN trading.order_requests o
                ON td.trade_decision_id = o.trade_decision_id
            LEFT JOIN LATERAL (
                SELECT
                    ea.execution_attempt_id,
                    ea.status,
                    ea.stop_phase,
                    ea.stop_reason,
                    ea.completed_at,
                    jsonb_array_length(ea.phase_trace) AS phase_count,
                    ea.phase_trace
                FROM trading.execution_attempts ea
                WHERE ea.trade_decision_id = td.trade_decision_id
                ORDER BY ea.started_at DESC
                LIMIT 1
            ) eas ON TRUE
        """

        count_sql = f"SELECT COUNT(DISTINCT td.trade_decision_id) {base_from_sql} {where_clause}"
        total_row = await self._tx.connection.fetchval(count_sql, *params)
        total_count = total_row if total_row is not None else 0

        # Paginated query with LEFT JOIN for instrument_name AND order_requests
        # phase_trace는 LEFT JOIN LATERAL의 execution_attempts에서 조회
        # execution_attempt_status is resolved via LEFT JOIN LATERAL to get the
        # latest execution_attempt status per trade_decision (P2).
        items_sql = f"""
            SELECT td.*, i.name AS _instrument_name,
                   o.order_request_id AS _order_request_id,
                   o.status AS _order_status,
                   eas.execution_attempt_id AS _latest_execution_attempt_id,
                   eas.status AS _execution_attempt_status,
                   eas.stop_phase AS _latest_stop_phase,
                   eas.stop_reason AS _latest_stop_reason,
                   eas.completed_at AS _latest_completed_at,
                   eas.phase_count AS _latest_phase_count,
                   eas.phase_trace AS _phase_trace
            FROM trading.trade_decisions td
            LEFT JOIN trading.instruments i
                ON td.symbol = i.symbol AND td.market = i.market_code
            LEFT JOIN trading.order_requests o
                ON td.trade_decision_id = o.trade_decision_id
            LEFT JOIN LATERAL (
                SELECT
                    ea.execution_attempt_id,
                    ea.status,
                    ea.stop_phase,
                    ea.stop_reason,
                    ea.completed_at,
                    jsonb_array_length(ea.phase_trace) AS phase_count,
                    ea.phase_trace
                FROM trading.execution_attempts ea
                WHERE ea.trade_decision_id = td.trade_decision_id
                ORDER BY ea.started_at DESC
                LIMIT 1
            ) eas ON TRUE
            {where_clause}
            ORDER BY td.created_at DESC, td.trade_decision_id DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """
        params.append(limit)
        params.append(offset)

        rows = await self._tx.connection.fetch(items_sql, *params)
        items: list[TradeDecisionRow] = []
        for row in rows:
            entity = row_to_entity(row, TradeDecisionEntity)
            # _order_request_id, _order_status, _instrument_name are unknown to
            # row_to_entity so they are automatically dropped from TradeDecisionEntity.
            # We read them separately from the raw row.
            order_request_id: str | None = row.get("_order_request_id")
            order_status: str | None = row.get("_order_status")
            instrument_name: str | None = row.get("_instrument_name")
            execution_attempt_status: str | None = row.get("_execution_attempt_status")
            # Phase 5: Latest execution attempt summary fields
            latest_execution_attempt_id: str | None = row.get("_latest_execution_attempt_id")
            latest_stop_phase: str | None = row.get("_latest_stop_phase")
            latest_stop_reason: str | None = row.get("_latest_stop_reason")
            latest_completed_at: datetime | None = row.get("_latest_completed_at")
            latest_phase_count: int | None = row.get("_latest_phase_count")
            # Convert UUID to string if needed
            if order_request_id is not None:
                order_request_id = str(order_request_id)
            # Convert execution_attempt_id (UUID) to string if needed
            if latest_execution_attempt_id is not None:
                latest_execution_attempt_id = str(latest_execution_attempt_id)
            items.append(TradeDecisionRow(
                entity=entity,
                order_request_id=order_request_id,
                order_status=order_status,
                instrument_name=instrument_name,
                phase_trace=row.get("_phase_trace"),  # execution_attempts 출처 (LEFT JOIN LATERAL)
                execution_attempt_status=execution_attempt_status,
                latest_execution_attempt_id=latest_execution_attempt_id,
                latest_stop_phase=latest_stop_phase,
                latest_stop_reason=latest_stop_reason,
                latest_completed_at=latest_completed_at,
                latest_phase_count=latest_phase_count,
            ))
        return items, total_count

    async def sync_execution_sizing(
        self,
        trade_decision_id: UUID,
        *,
        quantity: Decimal,
        max_order_value: Decimal | None,
        target_notional: Decimal | None,
        execution_sizing_payload: dict[str, object],
    ) -> TradeDecisionEntity | None:
        row = await self._tx.connection.fetchrow(
            """
            UPDATE trading.trade_decisions
            SET quantity = $2,
                target_quantity = $2,
                max_order_value = $3,
                target_notional = $4,
                decision_json = jsonb_set(
                    COALESCE(decision_json, '{}'::jsonb),
                    '{execution_sizing}',
                    $5::jsonb,
                    true
                )
            WHERE trade_decision_id = $1
            RETURNING *
            """,
            trade_decision_id,
            quantity,
            max_order_value,
            target_notional,
            json.dumps(execution_sizing_payload),
        )
        if row is None:
            return None
        return row_to_entity(row, TradeDecisionEntity)
