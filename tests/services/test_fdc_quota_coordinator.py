"""FDC quota coordinator tests.

Fast unit/concurrency tests (using ``InMemoryFdcQuotaRepository``) always
run — no DB required. Integration tests that need real PostgreSQL
row-lock/boundary behavior are skipped unless ``DATABASE_HOST`` is set —
same ``skipif`` pattern as ``tests/repositories/test_postgres_blocking_
locks.py``.

No external API calls, no real Gemini/provider calls anywhere in this
file.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from agent_trading.repositories.contracts import CoordinatorErrorClass
from agent_trading.repositories.memory import InMemoryFdcQuotaRepository
from agent_trading.services.fdc_quota_coordinator import (
    CoordinatorError,
    FdcQuotaCoordinator,
    ReservationDenied,
    ReservationGrant,
    ShadowJudgement,
)


def _make_coordinator(
    *, repo=None, target_rpm: int = 13, window_seconds: int = 60,
    quota_scope: str = "test:default", declared_rpm_limit: int | None = None,
) -> FdcQuotaCoordinator:
    return FdcQuotaCoordinator(
        repo=repo or InMemoryFdcQuotaRepository(),
        target_rpm=target_rpm,
        window_seconds=window_seconds,
        quota_scope=quota_scope,
        declared_rpm_limit=declared_rpm_limit,
    )


class TestFdcQuotaCoordinatorInit:
    def test_rejects_non_positive_target_rpm(self) -> None:
        with pytest.raises(ValueError):
            _make_coordinator(target_rpm=0)

    def test_rejects_non_positive_window_seconds(self) -> None:
        with pytest.raises(ValueError):
            _make_coordinator(target_rpm=13, window_seconds=0)

    def test_rejects_target_rpm_at_or_above_declared_limit(self) -> None:
        with pytest.raises(ValueError):
            _make_coordinator(target_rpm=15, declared_rpm_limit=15)
        with pytest.raises(ValueError):
            _make_coordinator(target_rpm=16, declared_rpm_limit=15)

    def test_accepts_target_rpm_below_declared_limit(self) -> None:
        _make_coordinator(target_rpm=13, declared_rpm_limit=15)

    def test_declared_limit_optional(self) -> None:
        _make_coordinator(target_rpm=13, declared_rpm_limit=None)


# ---------------------------------------------------------------------------
# Fast concurrency/logic tests against InMemoryFdcQuotaRepository — no DB.
# ---------------------------------------------------------------------------


class TestAtomicReservationLogic:
    @pytest.mark.asyncio
    async def test_concurrent_reservations_never_exceed_target_rpm(self) -> None:
        coordinator = _make_coordinator(target_rpm=2, quota_scope="scope-a")

        results = await asyncio.gather(
            *[
                coordinator.try_reserve(job_id=None, caller_id="test-caller")
                for _ in range(5)
            ]
        )

        granted = [r for r in results if isinstance(r, ReservationGrant)]
        denied = [r for r in results if isinstance(r, ReservationDenied)]
        assert len(granted) == 2, "정확히 target_rpm만큼만 승인돼야 한다"
        assert len(denied) == 3

    @pytest.mark.asyncio
    async def test_reservation_granted_counts_toward_window(self) -> None:
        coordinator = _make_coordinator(target_rpm=2, quota_scope="scope-b")

        first = await coordinator.try_reserve(job_id=None, caller_id="test-caller")
        second = await coordinator.try_reserve(job_id=None, caller_id="test-caller")
        third = await coordinator.try_reserve(job_id=None, caller_id="test-caller")

        assert isinstance(first, ReservationGrant)
        assert isinstance(second, ReservationGrant)
        assert isinstance(third, ReservationDenied)
        assert third.window_count == 2

    @pytest.mark.asyncio
    async def test_job_counters_updated_with_reservation(self) -> None:
        """job_id가 있으면 queue_poll_count/dispatch_attempt_no/
        reservation_denied_count/permit_consumed_count가 갱신되고,
        설계 문서 §9의 정합성 불변식을 만족한다."""
        repo = InMemoryFdcQuotaRepository()
        coordinator = _make_coordinator(repo=repo, target_rpm=1, quota_scope="scope-c")

        job_id = await coordinator.create_shadow_job(
            decision_cycle_id="cycle-1", decision_context_id=None,
            symbol="TESTSYM", source_type="held_position",
        )
        # 직접 mode='real'로 취급되도록 job 상태만 재사용 — try_reserve는
        # job_id가 repo._jobs에 존재하기만 하면 카운터를 갱신한다.
        first = await coordinator.try_reserve(job_id=job_id, caller_id="test-caller")
        second = await coordinator.try_reserve(job_id=job_id, caller_id="test-caller")

        assert isinstance(first, ReservationGrant)
        assert isinstance(second, ReservationDenied)

        job = repo._jobs[job_id]  # type: ignore[attr-defined]
        assert job["queue_poll_count"] == 2
        assert job["reservation_denied_count"] == 1
        assert job["dispatch_attempt_no"] == 1
        assert job["permit_consumed_count"] == 1
        assert job["queue_poll_count"] == (
            job["reservation_denied_count"] + job["dispatch_attempt_no"]
        )


class TestShadowJudgementLogic:
    @pytest.mark.asyncio
    async def test_shadow_judgement_reads_real_window_only(self) -> None:
        repo = InMemoryFdcQuotaRepository()
        coordinator = _make_coordinator(repo=repo, target_rpm=1, quota_scope="scope-d")

        granted = await coordinator.try_reserve(job_id=None, caller_id="ops-scheduler")
        assert isinstance(granted, ReservationGrant)

        job_id = await coordinator.create_shadow_job(
            decision_cycle_id="cycle-1", decision_context_id=None,
            symbol="005930", source_type="held_position",
        )
        judgement = await coordinator.judge_shadow_reservation(job_id=job_id)

        assert isinstance(judgement, ShadowJudgement)
        assert judgement.window_count == 1
        assert judgement.would_grant is False

    @pytest.mark.asyncio
    async def test_shadow_judgement_does_not_consume_real_quota(self) -> None:
        """shadow 판단을 여러 번 반복해도 이후 실제 reservation의
        window_count에 전혀 영향을 주지 않는다."""
        repo = InMemoryFdcQuotaRepository()
        coordinator = _make_coordinator(repo=repo, target_rpm=1, quota_scope="scope-e")

        job_id = await coordinator.create_shadow_job(
            decision_cycle_id="cycle-1", decision_context_id=None,
            symbol="005930", source_type="held_position",
        )
        for _ in range(5):
            judgement = await coordinator.judge_shadow_reservation(job_id=job_id)
            assert isinstance(judgement, ShadowJudgement)
            assert judgement.would_grant is True

        real_result = await coordinator.try_reserve(job_id=None, caller_id="ops-scheduler")
        assert isinstance(real_result, ReservationGrant)
        assert real_result.window_count_before_grant == 0, (
            "앞선 5번의 shadow 판단이 실제 quota를 전혀 소비하지 않았어야 한다"
        )

    @pytest.mark.asyncio
    async def test_shadow_rows_tagged_and_excluded_from_real_query(self) -> None:
        repo = InMemoryFdcQuotaRepository()
        coordinator = _make_coordinator(repo=repo, target_rpm=13, quota_scope="scope-f")

        job_id = await coordinator.create_shadow_job(
            decision_cycle_id="cycle-1", decision_context_id=None,
            symbol="005930", source_type="held_position",
        )
        await coordinator.judge_shadow_reservation(job_id=job_id)

        attempts = repo._attempts["scope-f"]  # type: ignore[attr-defined]
        assert len(attempts) == 1
        _, mode, outcome = attempts[0]
        assert mode == "shadow"
        assert outcome == "shadow_would_grant"
        assert repo._jobs[job_id]["mode"] == "shadow"  # type: ignore[attr-defined]
        assert repo._jobs[job_id]["status"] == "SHADOW_WOULD_GRANT"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Integration tests — real PostgreSQL row-lock/boundary behavior cannot be
# faked with the in-memory repo. Skipped unless DATABASE_HOST is set.
# ---------------------------------------------------------------------------


pytestmark_db = pytest.mark.skipif(
    not os.getenv("DATABASE_HOST"),
    reason="requires DATABASE_* env vars",
)


@pytest.fixture
async def quota_scope() -> str:
    return f"test:{uuid4()}"


@pytest.fixture
async def db_ready(quota_scope: str):
    """pool 생성 + migration 적용 + 이 테스트 전용 anchor 행 seed.

    ``try_reserve()``는 자신만의 독립 트랜잭션을 열어(설계상 의도적)
    실제로 commit하므로, teardown에서 이 quota_scope로 남긴 행만
    직접 정리한다(운영 데이터 무관).
    """
    from agent_trading.db.connection import close_pool, connection, create_pool
    from agent_trading.db.migrations.run import run_all_migrations

    await create_pool()
    await run_all_migrations()
    async with connection() as conn:
        await conn.execute(
            "INSERT INTO trading.fdc_quota_state (quota_scope) VALUES ($1) "
            "ON CONFLICT (quota_scope) DO NOTHING",
            quota_scope,
        )
    try:
        yield
    finally:
        async with connection() as conn:
            await conn.execute(
                "DELETE FROM trading.fdc_provider_attempts WHERE quota_scope = $1",
                quota_scope,
            )
            await conn.execute(
                "DELETE FROM trading.fdc_queue_jobs WHERE decision_cycle_id = $1",
                quota_scope,
            )
            await conn.execute(
                "DELETE FROM trading.fdc_quota_state WHERE quota_scope = $1",
                quota_scope,
            )
        await close_pool()


def _postgres_coordinator(*, quota_scope: str, target_rpm: int = 13, lock_timeout_ms: int = 3000):
    from agent_trading.db.transaction import TransactionManager
    from agent_trading.repositories.postgres.fdc_quota import PostgresFdcQuotaRepository

    tx = TransactionManager()
    repo = PostgresFdcQuotaRepository(tx)
    return FdcQuotaCoordinator(
        repo=repo, target_rpm=target_rpm, quota_scope=quota_scope,
        lock_timeout_ms=lock_timeout_ms,
    )


@pytestmark_db
class TestPostgresAtomicReservation:
    @pytest.mark.asyncio
    async def test_concurrent_reservations_never_exceed_target_rpm(
        self, db_ready, quota_scope: str,
    ) -> None:
        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=2)

        results = await asyncio.gather(
            *[
                coordinator.try_reserve(job_id=None, caller_id="test-caller")
                for _ in range(5)
            ]
        )
        granted = [r for r in results if isinstance(r, ReservationGrant)]
        errors = [r for r in results if isinstance(r, CoordinatorError)]
        assert not errors, f"unexpected coordinator errors: {errors}"
        assert len(granted) == 2

    @pytest.mark.asyncio
    async def test_exactly_60_seconds_old_reservation_excluded_from_window(
        self, db_ready, quota_scope: str,
    ) -> None:
        """(t-60초, t] 반열림 구간 — 정확히 60초 전 reservation은
        제외돼야 한다(설계 문서 §6 보정 4)."""
        from agent_trading.db.connection import connection

        exactly_60s_ago = datetime.now(timezone.utc) - timedelta(seconds=60)
        async with connection() as conn:
            await conn.execute(
                "INSERT INTO trading.fdc_provider_attempts "
                "(attempt_id, quota_scope, caller_id, mode, attempt_no, "
                " outcome, reserved_at) "
                "VALUES ($1, $2, 'test-caller', 'real', 1, "
                "'reservation_granted', $3)",
                uuid4(), quota_scope, exactly_60s_ago,
            )

        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=1)
        result = await coordinator.try_reserve(job_id=None, caller_id="test-caller")

        assert isinstance(result, ReservationGrant), (
            "정확히 60초 전 행은 창에서 제외돼 target_rpm=1이어도 승인돼야 한다"
        )

    @pytest.mark.asyncio
    async def test_lock_timeout_returns_coordinator_error_and_grants_nothing(
        self, db_ready, quota_scope: str,
    ) -> None:
        """anchor 행 잠금을 다른 트랜잭션이 쥐고 있으면, 짧은
        lock_timeout으로 COORDINATOR_LOCK_TIMEOUT을 반환하고 quota를
        소비하지 않는다(§6 coordinator 오류 경로 — fail-closed)."""
        from agent_trading.db.transaction import TransactionManager

        holder = TransactionManager()
        await holder.__aenter__()
        try:
            await holder.connection.fetchrow(
                "SELECT quota_scope FROM trading.fdc_quota_state "
                "WHERE quota_scope = $1 FOR UPDATE",
                quota_scope,
            )

            coordinator = _postgres_coordinator(
                quota_scope=quota_scope, target_rpm=13, lock_timeout_ms=200,
            )
            result = await coordinator.try_reserve(job_id=None, caller_id="test-caller")
            assert isinstance(result, CoordinatorError)
            assert result.error_class == CoordinatorErrorClass.COORDINATOR_LOCK_TIMEOUT
        finally:
            await holder.rollback()
            await holder.__aexit__(None, None, None)

        # 잠금 해제 후에는 정상적으로 승인된다(quota가 소비되지 않았음을 증명).
        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)
        result = await coordinator.try_reserve(job_id=None, caller_id="test-caller")
        assert isinstance(result, ReservationGrant)
