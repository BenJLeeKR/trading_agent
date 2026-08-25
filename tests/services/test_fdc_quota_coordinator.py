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
        설계 문서 §9의 정합성 불변식을 만족한다. (real 경로 전용 —
        shadow FIFO 큐와는 완전히 별개의 job 저장 구조를 쓴다.)"""
        repo = InMemoryFdcQuotaRepository()
        coordinator = _make_coordinator(repo=repo, target_rpm=1, quota_scope="scope-c")

        job_id = uuid4()
        repo._jobs[job_id] = {  # type: ignore[attr-defined]
            "queue_poll_count": 0, "reservation_denied_count": 0,
            "dispatch_attempt_no": 0, "permit_consumed_count": 0,
        }
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


def _shadow_job(**overrides):
    base = dict(
        decision_cycle_id="cycle-1", decision_context_id=None,
        symbol="005930", source_type="held_position",
    )
    base.update(overrides)
    return base


class TestShadowFifoQueueLogic:
    """가상 13 RPM shadow FIFO 큐 — 실제(mode='real') attempt는 전혀
    보지 않고, 같은 quota_scope의 mode='shadow' 행만으로 판단한다."""

    @pytest.mark.asyncio
    async def test_13_same_instant_jobs_all_would_grant(self) -> None:
        repo = InMemoryFdcQuotaRepository()
        coordinator = _make_coordinator(repo=repo, target_rpm=13, quota_scope="scope-fifo-a")
        t0 = datetime(2026, 8, 25, 9, 0, 0, tzinfo=timezone.utc)

        results = [
            await coordinator.register_shadow_job_and_judge(
                **_shadow_job(), fdc_ready_at=t0,
            )
            for _ in range(13)
        ]

        assert all(isinstance(r, ShadowJudgement) for r in results)
        assert all(r.would_grant for r in results), "13건 전부 SHADOW_WOULD_GRANT여야 한다"

    @pytest.mark.asyncio
    async def test_14th_same_instant_job_is_queued(self) -> None:
        repo = InMemoryFdcQuotaRepository()
        coordinator = _make_coordinator(repo=repo, target_rpm=13, quota_scope="scope-fifo-b")
        t0 = datetime(2026, 8, 25, 9, 0, 0, tzinfo=timezone.utc)

        results = [
            await coordinator.register_shadow_job_and_judge(
                **_shadow_job(), fdc_ready_at=t0,
            )
            for _ in range(14)
        ]

        assert all(r.would_grant for r in results[:13])
        assert results[13].would_grant is False, "14번째는 SHADOW_QUEUED여야 한다"
        assert results[13].window_count == 13

    @pytest.mark.asyncio
    async def test_40_concurrent_jobs_only_first_13_grant_no_timeout_state(self) -> None:
        """40건이 동시에 등록돼도 처음 13건만 즉시 grant, 나머지는
        queued — timeout/cancelled 같은 상태는 절대 나오지 않는다."""
        repo = InMemoryFdcQuotaRepository()
        coordinator = _make_coordinator(repo=repo, target_rpm=13, quota_scope="scope-fifo-c")
        t0 = datetime(2026, 8, 25, 9, 0, 0, tzinfo=timezone.utc)

        results = await asyncio.gather(
            *[
                coordinator.register_shadow_job_and_judge(**_shadow_job(), fdc_ready_at=t0)
                for _ in range(40)
            ]
        )

        assert all(isinstance(r, ShadowJudgement) for r in results), (
            "CoordinatorError 없이 전부 ShadowJudgement여야 한다(timeout/cancelled 없음)"
        )
        granted = [r for r in results if r.would_grant]
        queued = [r for r in results if not r.would_grant]
        assert len(granted) == 13
        assert len(queued) == 27

    @pytest.mark.asyncio
    async def test_fifo_no_queue_jumping(self) -> None:
        """앞서 등록된(enqueue_sequence가 더 작은) job이 queued인 상태에서
        뒤에 등록된 job이 먼저 grant되는 새치기가 없어야 한다."""
        repo = InMemoryFdcQuotaRepository()
        coordinator = _make_coordinator(repo=repo, target_rpm=1, quota_scope="scope-fifo-d")
        t0 = datetime(2026, 8, 25, 9, 0, 0, tzinfo=timezone.utc)

        first = await coordinator.register_shadow_job_and_judge(**_shadow_job(), fdc_ready_at=t0)
        second = await coordinator.register_shadow_job_and_judge(**_shadow_job(), fdc_ready_at=t0)
        third = await coordinator.register_shadow_job_and_judge(**_shadow_job(), fdc_ready_at=t0)

        assert first.would_grant is True
        assert second.would_grant is False
        assert third.would_grant is False
        assert first.enqueue_sequence < second.enqueue_sequence < third.enqueue_sequence

    @pytest.mark.asyncio
    async def test_exactly_60_seconds_old_shadow_grant_excluded(self) -> None:
        """(t-60초, t] 반열림 — 정확히 60초 전 shadow grant는 window에서
        제외된다(real 경로와 동일한 경계 규칙)."""
        repo = InMemoryFdcQuotaRepository()
        coordinator = _make_coordinator(repo=repo, target_rpm=1, quota_scope="scope-fifo-e")
        t0 = datetime(2026, 8, 25, 9, 0, 0, tzinfo=timezone.utc)

        first = await coordinator.register_shadow_job_and_judge(**_shadow_job(), fdc_ready_at=t0)
        assert first.would_grant is True

        exactly_60s_later = t0 + timedelta(seconds=60)
        second = await coordinator.register_shadow_job_and_judge(
            **_shadow_job(), fdc_ready_at=exactly_60s_later,
        )
        assert second.would_grant is True, (
            "정확히 60초 뒤(=이전 grant가 정확히 60초 전)면 window에서 "
            "제외돼 target_rpm=1이어도 승인돼야 한다"
        )

        just_under_60s_later = t0 + timedelta(seconds=59, milliseconds=999)
        repo3 = InMemoryFdcQuotaRepository()
        coordinator3 = _make_coordinator(repo=repo3, target_rpm=1, quota_scope="scope-fifo-e2")
        await coordinator3.register_shadow_job_and_judge(**_shadow_job(), fdc_ready_at=t0)
        third = await coordinator3.register_shadow_job_and_judge(
            **_shadow_job(), fdc_ready_at=just_under_60s_later,
        )
        assert third.would_grant is False, "59.999초 전이면 아직 window 안이라 거부돼야 한다"

    @pytest.mark.asyncio
    async def test_shadow_does_not_consume_or_read_real_quota(self) -> None:
        """shadow 등록/판단이 실제(mode='real') quota 집계에 전혀
        영향을 주지 않고, 그 역도 마찬가지다."""
        repo = InMemoryFdcQuotaRepository()
        coordinator = _make_coordinator(repo=repo, target_rpm=1, quota_scope="scope-fifo-f")
        t0 = datetime(2026, 8, 25, 9, 0, 0, tzinfo=timezone.utc)

        # 실제 real quota를 먼저 채운다.
        real_result = await coordinator.try_reserve(job_id=None, caller_id="ops-scheduler")
        assert isinstance(real_result, ReservationGrant)

        # shadow 판단은 real이 이미 가득 찼어도 영향받지 않는다(shadow
        # 큐는 비어 있으므로 target_rpm=1에서도 승인돼야 한다).
        shadow_result = await coordinator.register_shadow_job_and_judge(
            **_shadow_job(), fdc_ready_at=t0,
        )
        assert shadow_result.would_grant is True, "real quota가 shadow 판단에 영향을 주면 안 된다"

        # 반대로 shadow 등록을 여러 번 더 해도 real 쪽 window_count는 그대로다.
        for _ in range(5):
            await coordinator.register_shadow_job_and_judge(**_shadow_job(), fdc_ready_at=t0)
        real_result_2 = await coordinator.try_reserve(job_id=None, caller_id="ops-scheduler")
        assert isinstance(real_result_2, ReservationDenied)
        assert real_result_2.window_count == 1, "shadow 등록이 real window_count에 영향을 주면 안 된다"

    @pytest.mark.asyncio
    async def test_shadow_rows_tagged_shadow_mode(self) -> None:
        repo = InMemoryFdcQuotaRepository()
        coordinator = _make_coordinator(repo=repo, target_rpm=13, quota_scope="scope-fifo-g")
        t0 = datetime(2026, 8, 25, 9, 0, 0, tzinfo=timezone.utc)

        result = await coordinator.register_shadow_job_and_judge(**_shadow_job(), fdc_ready_at=t0)

        attempts = repo._attempts["scope-fifo-g"]  # type: ignore[attr-defined]
        assert len(attempts) == 1
        _, mode, outcome = attempts[0]
        assert mode == "shadow"
        assert outcome == "shadow_would_grant"
        shadow_jobs = repo._shadow_jobs["scope-fifo-g"]  # type: ignore[attr-defined]
        assert shadow_jobs[0]["job_id"] == result.job_id
        assert shadow_jobs[0]["status"] == "SHADOW_WOULD_GRANT"
        assert shadow_jobs[0]["mode"] == "shadow"


# ---------------------------------------------------------------------------
# Integration tests — real PostgreSQL row-lock/boundary behavior cannot be
# faked with the in-memory repo. Skipped unless DATABASE_HOST is set.
# ---------------------------------------------------------------------------


pytestmark_db = pytest.mark.skipif(
    not os.getenv("DATABASE_HOST"),
    reason="requires DATABASE_* env vars",
)


# 이 프로젝트의 pyproject.toml은 ``asyncio_default_fixture_loop_scope =
# "module"``이지만 테스트 자체는 기본값인 "function" loop scope로
# 실행된다. 두 async fixture(quota_scope/db_ready)가 기본값(module)을
# 그대로 따르면, 실제 PostgreSQL이 연결된 CI에서 fixture가 만든
# asyncpg pool/connection이 테스트 함수의 이벤트 루프와 다른 루프에
# 묶여 "attached to a different loop"/"another operation is in
# progress" 오류로 전부 실패한다(로컬/기존 CI에서는 DATABASE_HOST가
# 없어 이 두 fixture 자체가 실행된 적이 없어 발견되지 못했던 결함).
# 프로젝트 전역 설정을 바꾸지 않고, 이 파일의 DB 통합 fixture만
# 명시적으로 "function" loop scope로 고정해 테스트와 같은 루프를
# 쓰도록 한다.
import pytest_asyncio


@pytest_asyncio.fixture(loop_scope="function")
async def quota_scope() -> str:
    return f"test:{uuid4()}"


@pytest_asyncio.fixture(loop_scope="function")
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
                "DELETE FROM trading.fdc_queue_jobs WHERE quota_scope = $1",
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


@pytestmark_db
class TestPostgresShadowFifoQueue:
    """가상 13 RPM shadow FIFO 큐 — singleton anchor 행 잠금/60초 경계/
    동시성이 in-memory asyncio.Lock이 아니라 실제 PostgreSQL 행 잠금으로
    보장되는지 검증한다."""

    @pytest.mark.asyncio
    async def test_13_same_instant_jobs_all_would_grant(
        self, db_ready, quota_scope: str,
    ) -> None:
        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)
        t0 = datetime.now(timezone.utc)

        results = [
            await coordinator.register_shadow_job_and_judge(
                decision_cycle_id="cycle-1", decision_context_id=None,
                symbol="005930", source_type="held_position", fdc_ready_at=t0,
            )
            for _ in range(13)
        ]
        assert all(isinstance(r, ShadowJudgement) for r in results)
        assert all(r.would_grant for r in results)

    @pytest.mark.asyncio
    async def test_14th_job_is_queued_not_granted(
        self, db_ready, quota_scope: str,
    ) -> None:
        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)
        t0 = datetime.now(timezone.utc)

        results = [
            await coordinator.register_shadow_job_and_judge(
                decision_cycle_id="cycle-1", decision_context_id=None,
                symbol="005930", source_type="held_position", fdc_ready_at=t0,
            )
            for _ in range(14)
        ]
        assert all(r.would_grant for r in results[:13])
        assert results[13].would_grant is False

    @pytest.mark.asyncio
    async def test_concurrent_registration_no_queue_jumping(
        self, db_ready, quota_scope: str,
    ) -> None:
        """실제 anchor 행 잠금 하에서 동시 등록해도 새치기가 없는지 —
        승인된 job 수가 정확히 target_rpm과 같아야 한다."""
        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)
        t0 = datetime.now(timezone.utc)

        results = await asyncio.gather(
            *[
                coordinator.register_shadow_job_and_judge(
                    decision_cycle_id="cycle-1", decision_context_id=None,
                    symbol="005930", source_type="held_position", fdc_ready_at=t0,
                )
                for _ in range(40)
            ]
        )
        errors = [r for r in results if isinstance(r, CoordinatorError)]
        assert not errors, f"unexpected coordinator errors: {errors}"
        granted = [r for r in results if r.would_grant]
        assert len(granted) == 13

    @pytest.mark.asyncio
    async def test_exactly_60_seconds_boundary(
        self, db_ready, quota_scope: str,
    ) -> None:
        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=1)
        t0 = datetime.now(timezone.utc)

        first = await coordinator.register_shadow_job_and_judge(
            decision_cycle_id="cycle-1", decision_context_id=None,
            symbol="005930", source_type="held_position", fdc_ready_at=t0,
        )
        assert first.would_grant is True

        second = await coordinator.register_shadow_job_and_judge(
            decision_cycle_id="cycle-1", decision_context_id=None,
            symbol="005930", source_type="held_position",
            fdc_ready_at=t0 + timedelta(seconds=60),
        )
        assert second.would_grant is True, "정확히 60초 뒤는 window 밖이라 승인돼야 한다"

    @pytest.mark.asyncio
    async def test_shadow_does_not_affect_real_and_vice_versa(
        self, db_ready, quota_scope: str,
    ) -> None:
        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=1)
        t0 = datetime.now(timezone.utc)

        real_result = await coordinator.try_reserve(job_id=None, caller_id="test-caller")
        assert isinstance(real_result, ReservationGrant)

        shadow_result = await coordinator.register_shadow_job_and_judge(
            decision_cycle_id="cycle-1", decision_context_id=None,
            symbol="005930", source_type="held_position", fdc_ready_at=t0,
        )
        assert shadow_result.would_grant is True, "real quota가 shadow 판단에 영향을 주면 안 된다"

    @pytest.mark.asyncio
    async def test_sequential_replay_in_true_fdc_ready_order_grants_by_that_order(
        self, db_ready, quota_scope: str,
    ) -> None:
        """PR #351 2차 보정 — 실제 PostgreSQL에서도 ``enqueue_sequence``는
        "호출 순서"만 반영한다(재정렬 로직은 DB가 아니라 호출자
        `run_decision_loop.py::_replay_fdc_ready_shadow_events_for_cycle()`
        의 책임). 이 테스트는 그 호출자가 실제로 하는 일 — 진짜
        `fdc_ready_at` 오름차순으로 순차 호출 — 을 그대로 재현해, DB가
        그 호출 순서를 정확히 `enqueue_sequence` 오름차순으로 기록하는지
        검증한다. 심볼 A(가장 이른 fdc_ready_at)가 심볼 B(더 늦은
        fdc_ready_at)보다 먼저 호출되면(=애플리케이션 계층이 이미
        올바르게 정렬해 순차 호출했다는 전제), A가 항상 더 작은
        enqueue_sequence를 받아야 한다 — 그 반대(B를 먼저 호출했는데도
        A가 더 작은 sequence를 받는 것)는 DB 계층이 절대 재현할 수
        없으므로, 정렬 책임이 호출자에게 있다는 설계를 실제 DB로 확인한다."""
        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)
        t_a = datetime.now(timezone.utc)
        t_b = t_a + timedelta(seconds=1)

        # 애플리케이션 계층이 이미 (fdc_ready_at, cycle_index) 순으로
        # 정렬해 순차 호출한다고 가정 — A(이른 시각)를 먼저 호출.
        result_a = await coordinator.register_shadow_job_and_judge(
            decision_cycle_id="cycle-1", decision_context_id=None,
            symbol="005930", source_type="core", fdc_ready_at=t_a,
        )
        result_b = await coordinator.register_shadow_job_and_judge(
            decision_cycle_id="cycle-1", decision_context_id=None,
            symbol="000660", source_type="core", fdc_ready_at=t_b,
        )

        assert isinstance(result_a, ShadowJudgement)
        assert isinstance(result_b, ShadowJudgement)
        assert result_a.enqueue_sequence < result_b.enqueue_sequence
        assert result_a.would_grant is True
        assert result_b.would_grant is True

    @pytest.mark.asyncio
    async def test_14th_queued_state_unaffected_by_interleaved_real_reservation(
        self, db_ready, quota_scope: str,
    ) -> None:
        """13개가 이미 SHADOW_WOULD_GRANT로 확정된 뒤 14번째가
        SHADOW_QUEUED로 기록된 상태에서, 같은 quota_scope로 실제
        `mode='real'` reservation을 수행해도 이미 확정된 13개의 상태와
        14번째의 SHADOW_QUEUED 상태 어느 것도 바뀌지 않는다 —
        real/shadow 완전 분리의 상태 불변성 확인."""
        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)
        t0 = datetime.now(timezone.utc)

        results = [
            await coordinator.register_shadow_job_and_judge(
                decision_cycle_id="cycle-1", decision_context_id=None,
                symbol="005930", source_type="held_position", fdc_ready_at=t0,
            )
            for _ in range(14)
        ]
        assert all(r.would_grant for r in results[:13])
        assert results[13].would_grant is False
        job_ids_before = [r.job_id for r in results]

        real_result = await coordinator.try_reserve(job_id=None, caller_id="test-caller")
        assert isinstance(real_result, ReservationGrant)

        from agent_trading.db.connection import connection
        async with connection() as conn:
            rows = await conn.fetch(
                "SELECT job_id, status FROM trading.fdc_queue_jobs "
                "WHERE quota_scope = $1 AND mode = 'shadow' "
                "ORDER BY enqueue_sequence",
                quota_scope,
            )
        assert [row["job_id"] for row in rows] == job_ids_before
        statuses = [row["status"] for row in rows]
        assert statuses[:13] == ["SHADOW_WOULD_GRANT"] * 13
        assert statuses[13] == "SHADOW_QUEUED"

    @pytest.mark.asyncio
    async def test_real_reservations_do_not_affect_shadow_13_judgement(
        self, db_ready, quota_scope: str,
    ) -> None:
        """real reservation 13건이 이미 존재해도 shadow 판단은 여전히
        `mode='shadow'` 행만 세므로, 새 shadow 등록 13건은 전부
        SHADOW_WOULD_GRANT여야 한다."""
        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)

        real_results = await asyncio.gather(
            *[
                coordinator.try_reserve(job_id=None, caller_id="test-caller")
                for _ in range(13)
            ]
        )
        assert all(isinstance(r, ReservationGrant) for r in real_results)

        t0 = datetime.now(timezone.utc)
        shadow_results = [
            await coordinator.register_shadow_job_and_judge(
                decision_cycle_id="cycle-1", decision_context_id=None,
                symbol="005930", source_type="held_position", fdc_ready_at=t0,
            )
            for _ in range(13)
        ]
        assert all(r.would_grant for r in shadow_results), (
            "real reservation 13건이 이미 있어도 shadow 13개 판단에 영향을 주면 안 된다"
        )


@pytestmark_db
class TestPostgresAnchorRowFailClosed:
    """anchor 행(quota_scope)이 ``trading.fdc_quota_state``에 없으면
    ``SELECT ... FOR UPDATE``가 아무 행도 잠그지 못한 채 조용히 통과해
    버리는 fail-open 결함을 막는다 — migration/seed가 불완전한 경우
    quota를 판단/소비하지 않고 명확한 ``CoordinatorError``로 종료돼야
    한다."""

    @pytest.mark.asyncio
    async def test_try_reserve_fails_closed_when_anchor_row_missing(
        self, db_ready, quota_scope: str,
    ) -> None:
        missing_scope = f"missing-anchor-real:{uuid4()}"
        coordinator = _postgres_coordinator(quota_scope=missing_scope, target_rpm=13)

        result = await coordinator.try_reserve(job_id=None, caller_id="test-caller")

        assert isinstance(result, CoordinatorError)
        assert result.error_class == CoordinatorErrorClass.COORDINATOR_TRANSACTION_ERROR

        from agent_trading.db.connection import connection
        async with connection() as conn:
            count = await conn.fetchval(
                "SELECT count(*) FROM trading.fdc_provider_attempts WHERE quota_scope = $1",
                missing_scope,
            )
        assert count == 0, "anchor 행이 없으면 real quota를 절대 소비하면 안 된다"

    @pytest.mark.asyncio
    async def test_register_shadow_job_and_judge_fails_closed_when_anchor_row_missing(
        self, db_ready, quota_scope: str,
    ) -> None:
        missing_scope = f"missing-anchor-shadow:{uuid4()}"
        coordinator = _postgres_coordinator(quota_scope=missing_scope, target_rpm=13)

        result = await coordinator.register_shadow_job_and_judge(
            decision_cycle_id="cycle-1", decision_context_id=None,
            symbol="005930", source_type="held_position",
            fdc_ready_at=datetime.now(timezone.utc),
        )

        assert isinstance(result, CoordinatorError)
        assert result.error_class == CoordinatorErrorClass.COORDINATOR_TRANSACTION_ERROR

        from agent_trading.db.connection import connection
        async with connection() as conn:
            count = await conn.fetchval(
                "SELECT count(*) FROM trading.fdc_queue_jobs WHERE quota_scope = $1",
                missing_scope,
            )
        assert count == 0, "anchor 행이 없으면 shadow job도 절대 등록하면 안 된다"
