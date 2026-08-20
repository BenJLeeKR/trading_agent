"""DB-free tests for ``PostgresGuardrailEvaluationRepository`` (Stage A-2,
2026-08-20).

Kept in a separate file from ``test_postgres_guardrail_evaluations.py``
on purpose: that file uses the ``seeded_postgres_data`` fixture (a real
Postgres connection) and does not import
``agent_trading.repositories.postgres.guardrail_evaluations`` directly, so
the harness's import-graph test discovery does not select it as a
candidate for ``accept backend-file``. This file imports the concrete
Postgres repository class directly and uses a fake ``connection``
(``SimpleNamespace``) to capture the SQL/params actually passed to
``fetchrow()`` — no live DB needed, so it is a "safe" import-graph
candidate that runs directly under ``accept backend-file``.

Covers the ``policy_git_sha`` column added in migration 0065, the
``decision_cycle_id`` column added in migration 0066(Stage A-1b), and the
``gate_phase=pass2_general_lane_drop`` rule_results payload used by the
Stage A-1a Pass 2 drop recording path (``scripts/run_decision_loop.py``).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from agent_trading.domain.entities import GuardrailEvaluationEntity
from agent_trading.repositories.postgres.guardrail_evaluations import (
    PostgresGuardrailEvaluationRepository,
)


def _make_entity(**overrides: object) -> GuardrailEvaluationEntity:
    defaults: dict[str, object] = dict(
        guardrail_evaluation_id=uuid4(),
        rule_set_version="pass2_general_lane_drop_v1",
        overall_passed=False,
        evaluated_at=datetime.now(timezone.utc),
        decision_context_id=None,
        trade_decision_id=None,
        order_request_id=None,
        rule_results={"gate_phase": "pass2_general_lane_drop", "cycle": 7},
        blocking_rule_codes=["submit_budget_consumed_core"],
        warning_rule_codes=None,
        policy_git_sha=None,
        decision_cycle_id=None,
    )
    defaults.update(overrides)
    return GuardrailEvaluationEntity(**defaults)  # type: ignore[arg-type]


def _fake_row(entity: GuardrailEvaluationEntity) -> dict[str, object]:
    """Minimal fake ``asyncpg``-like row for ``row_to_entity()`` to parse."""
    return {
        "guardrail_evaluation_id": entity.guardrail_evaluation_id,
        "decision_context_id": entity.decision_context_id,
        "trade_decision_id": entity.trade_decision_id,
        "order_request_id": entity.order_request_id,
        "rule_set_version": entity.rule_set_version,
        "overall_passed": entity.overall_passed,
        "evaluated_at": entity.evaluated_at,
        "rule_results": entity.rule_results,
        "blocking_rule_codes": entity.blocking_rule_codes,
        "warning_rule_codes": entity.warning_rule_codes,
        "created_at": datetime.now(timezone.utc),
        "policy_git_sha": entity.policy_git_sha,
        "decision_cycle_id": entity.decision_cycle_id,
    }


@pytest.mark.asyncio
async def test_add_includes_policy_git_sha_in_insert_params() -> None:
    """``policy_git_sha``가 INSERT의 SQL 컬럼 목록과 파라미터로
    함께 전달되는지 검증한다."""
    entity = _make_entity(policy_git_sha="abc123def456")
    connection = SimpleNamespace(
        fetchrow=AsyncMock(return_value=_fake_row(entity))
    )
    tx = SimpleNamespace(connection=connection)
    repo = PostgresGuardrailEvaluationRepository(tx)

    result = await repo.add(entity)

    connection.fetchrow.assert_awaited_once()
    sql, *params = connection.fetchrow.await_args.args
    assert "policy_git_sha" in sql
    assert len(params) == 12
    assert params[-2] == "abc123def456"
    assert result.policy_git_sha == "abc123def456"


@pytest.mark.asyncio
async def test_add_allows_policy_git_sha_none() -> None:
    """``policy_git_sha``가 없어도(None) 기존 계약을 깨지 않고 그대로
    NULL로 전달돼야 한다(하위 호환)."""
    entity = _make_entity(policy_git_sha=None)
    connection = SimpleNamespace(
        fetchrow=AsyncMock(return_value=_fake_row(entity))
    )
    tx = SimpleNamespace(connection=connection)
    repo = PostgresGuardrailEvaluationRepository(tx)

    result = await repo.add(entity)

    connection.fetchrow.assert_awaited_once()
    _, *params = connection.fetchrow.await_args.args
    assert params[-2] is None
    assert result.policy_git_sha is None


@pytest.mark.asyncio
async def test_add_includes_decision_cycle_id_in_insert_params() -> None:
    """Stage A-1b(2026-08-20): ``decision_cycle_id``가 INSERT의 SQL
    컬럼 목록과 마지막 파라미터로 함께 전달되는지 검증한다."""
    entity = _make_entity(
        decision_cycle_id="decision_submit_gate:2026-08-20T09:05:12+09:00#1"
    )
    connection = SimpleNamespace(
        fetchrow=AsyncMock(return_value=_fake_row(entity))
    )
    tx = SimpleNamespace(connection=connection)
    repo = PostgresGuardrailEvaluationRepository(tx)

    result = await repo.add(entity)

    connection.fetchrow.assert_awaited_once()
    sql, *params = connection.fetchrow.await_args.args
    assert "decision_cycle_id" in sql
    assert len(params) == 12
    assert params[-1] == "decision_submit_gate:2026-08-20T09:05:12+09:00#1"
    assert result.decision_cycle_id == (
        "decision_submit_gate:2026-08-20T09:05:12+09:00#1"
    )


@pytest.mark.asyncio
async def test_add_allows_decision_cycle_id_none() -> None:
    """``decision_cycle_id``가 없어도(None) 기존 계약을 깨지 않고
    NULL로 전달돼야 한다(하위 호환 — 수동/단독 실행 등)."""
    entity = _make_entity(decision_cycle_id=None)
    connection = SimpleNamespace(
        fetchrow=AsyncMock(return_value=_fake_row(entity))
    )
    tx = SimpleNamespace(connection=connection)
    repo = PostgresGuardrailEvaluationRepository(tx)

    result = await repo.add(entity)

    connection.fetchrow.assert_awaited_once()
    _, *params = connection.fetchrow.await_args.args
    assert params[-1] is None
    assert result.decision_cycle_id is None


@pytest.mark.asyncio
async def test_add_stores_policy_git_sha_and_decision_cycle_id_together() -> None:
    """두 관측성 필드가 서로 간섭 없이 함께 저장되는지 검증한다."""
    entity = _make_entity(
        policy_git_sha="abc123def456",
        decision_cycle_id="decision_submit_gate:2026-08-20T09:05:12+09:00#1",
    )
    connection = SimpleNamespace(
        fetchrow=AsyncMock(return_value=_fake_row(entity))
    )
    tx = SimpleNamespace(connection=connection)
    repo = PostgresGuardrailEvaluationRepository(tx)

    result = await repo.add(entity)

    connection.fetchrow.assert_awaited_once()
    _, *params = connection.fetchrow.await_args.args
    assert params[-2] == "abc123def456"
    assert params[-1] == "decision_submit_gate:2026-08-20T09:05:12+09:00#1"
    assert result.policy_git_sha == "abc123def456"
    assert result.decision_cycle_id == (
        "decision_submit_gate:2026-08-20T09:05:12+09:00#1"
    )


@pytest.mark.asyncio
async def test_add_serializes_pass2_general_lane_drop_gate_phase() -> None:
    """Stage A-1a(Pass 2 drop 기록)가 만드는 ``gate_phase=
    pass2_general_lane_drop`` 값이 ``rule_results`` jsonb payload에
    그대로 직렬화돼 저장 경로로 전달되는지 검증한다."""
    entity = _make_entity(
        rule_results={
            "gate_phase": "pass2_general_lane_drop",
            "cycle": 12,
            "context_metadata": {"gate_phase": "pass2_general_lane_drop"},
        },
        blocking_rule_codes=["submit_budget_consumed_core"],
    )
    connection = SimpleNamespace(
        fetchrow=AsyncMock(return_value=_fake_row(entity))
    )
    tx = SimpleNamespace(connection=connection)
    repo = PostgresGuardrailEvaluationRepository(tx)

    await repo.add(entity)

    connection.fetchrow.assert_awaited_once()
    _, *params = connection.fetchrow.await_args.args
    # rule_results is the 8th positional param ($8::jsonb) → index 7.
    rule_results_payload = json.loads(params[7])
    assert rule_results_payload["gate_phase"] == "pass2_general_lane_drop"
    assert rule_results_payload["context_metadata"]["gate_phase"] == (
        "pass2_general_lane_drop"
    )
