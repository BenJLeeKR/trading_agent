from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from agent_trading.domain.entities import GuardrailEvaluationEntity, OrderRequestEntity
from agent_trading.domain.enums import OrderSide, OrderType, TimeInForce
from agent_trading.repositories.container import RepositoryContainer


@pytest.fixture
async def seeded_order(
    seeded_postgres_data: RepositoryContainer,
    sample_order: OrderRequestEntity,
) -> UUID:
    """Create a persisted order request for FK references."""
    saved = await seeded_postgres_data.orders.add(sample_order)
    return saved.order_request_id


@pytest.fixture
async def seeded_decision_context(
    seeded_postgres_data: RepositoryContainer,
) -> UUID:
    """Return the decision_context_id already seeded by ``seeded_postgres_data``.

    The ``seeded_postgres_data`` fixture seeds exactly one
    ``DecisionContextEntity`` via raw SQL, so we query it back
    using the connection directly.
    """
    conn = seeded_postgres_data.unit_of_work.connection
    row = await conn.fetchrow(
        "SELECT decision_context_id FROM trading.decision_contexts LIMIT 1"
    )
    assert row is not None, "seeded_postgres_data must seed a decision_context"
    return row["decision_context_id"]


@pytest.mark.asyncio
async def test_add_and_get_by_decision_context(
    seeded_postgres_data: RepositoryContainer,
    seeded_order: UUID,
    seeded_decision_context: UUID,
) -> None:
    decision_context_id = seeded_decision_context
    now = datetime.now(timezone.utc)

    evaluation = GuardrailEvaluationEntity(
        guardrail_evaluation_id=uuid4(),
        decision_context_id=decision_context_id,
        trade_decision_id=None,
        order_request_id=seeded_order,
        rule_set_version="v1.0",
        overall_passed=True,
        evaluated_at=now,
        rule_results={"max_position_size": {"passed": True, "value": "0.05"}},
        blocking_rule_codes=None,
        warning_rule_codes=None,
    )
    saved = await seeded_postgres_data.guardrail_evaluations.add(evaluation)
    assert saved.guardrail_evaluation_id == evaluation.guardrail_evaluation_id
    assert saved.overall_passed is True

    results = await seeded_postgres_data.guardrail_evaluations.get_by_decision_context(
        decision_context_id
    )
    assert len(results) == 1
    assert results[0].rule_set_version == "v1.0"


@pytest.mark.asyncio
async def test_add_and_get_by_order_request(
    seeded_postgres_data: RepositoryContainer,
    seeded_order: UUID,
) -> None:
    order_request_id = seeded_order
    now = datetime.now(timezone.utc)

    evaluation = GuardrailEvaluationEntity(
        guardrail_evaluation_id=uuid4(),
        decision_context_id=None,
        trade_decision_id=None,
        order_request_id=order_request_id,
        rule_set_version="v1.0",
        overall_passed=False,
        evaluated_at=now,
        rule_results={"kill_switch": {"passed": False, "reason": "kill_switch_active"}},
        blocking_rule_codes=["kill_switch"],
        warning_rule_codes=None,
    )
    await seeded_postgres_data.guardrail_evaluations.add(evaluation)

    results = await seeded_postgres_data.guardrail_evaluations.get_by_order_request(
        order_request_id
    )
    assert len(results) == 1
    assert results[0].overall_passed is False
    assert results[0].blocking_rule_codes == ["kill_switch"]


@pytest.mark.asyncio
async def test_get_by_decision_context_empty(
    seeded_postgres_data: RepositoryContainer,
) -> None:
    results = await seeded_postgres_data.guardrail_evaluations.get_by_decision_context(
        uuid4()
    )
    assert len(results) == 0


@pytest.mark.asyncio
async def test_rule_results_jsonb(
    seeded_postgres_data: RepositoryContainer,
    seeded_order: UUID,
    seeded_decision_context: UUID,
) -> None:
    """Verify that complex rule_results JSONB is stored and retrieved correctly."""
    decision_context_id = seeded_decision_context
    now = datetime.now(timezone.utc)

    complex_results = {
        "max_position_size": {"passed": True, "current_pct": "4.5", "limit_pct": "10.0"},
        "daily_loss_limit": {"passed": True, "used_pct": "2.1", "limit_pct": "5.0"},
        "sector_exposure": {"passed": False, "current_pct": "35.0", "limit_pct": "30.0"},
    }

    evaluation = GuardrailEvaluationEntity(
        guardrail_evaluation_id=uuid4(),
        decision_context_id=decision_context_id,
        order_request_id=seeded_order,
        rule_set_version="v1.0",
        overall_passed=False,
        evaluated_at=now,
        rule_results=complex_results,
        blocking_rule_codes=["sector_exposure"],
        warning_rule_codes=None,
    )
    await seeded_postgres_data.guardrail_evaluations.add(evaluation)

    results = await seeded_postgres_data.guardrail_evaluations.get_by_decision_context(
        decision_context_id
    )
    assert len(results) == 1
    assert results[0].rule_results["sector_exposure"]["passed"] is False
    assert results[0].rule_results["max_position_size"]["passed"] is True
