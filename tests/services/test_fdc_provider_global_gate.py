"""``FdcProviderGlobalGate``/``try_acquire_provider_global_gate_permit()``
테스트(PR D, 2026-09-03).

Fast unit tests(``InMemoryFdcQuotaRepository``)는 항상 실행된다 — DB
불필요. 실제 PostgreSQL row-lock/동시성/60초 sliding window 경계 검증은
``tests/services/test_fdc_quota_coordinator.py``와 동일한 ``skipif``
패턴으로 ``DATABASE_HOST``가 설정된 환경에서만 실행된다 — mock만으로
전체 global quota 정확성을 증명하지 않는다(설계 문서 §4.2/§5.5 요구).

No external API calls, no real Gemini/provider calls anywhere in this
file.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from agent_trading.repositories.contracts import (
    CoordinatorError,
    CoordinatorErrorClass,
    ProviderGlobalGateGranted,
)
from agent_trading.repositories.memory import InMemoryFdcQuotaRepository
from agent_trading.services.fdc_provider_global_gate import (
    DEFAULT_GATE_SCOPE,
    FdcProviderGlobalGate,
)


def _make_gate(
    *, repo=None, target_rpm: int = 13, window_seconds: int = 60,
    gate_scope: str = "test:global-gate",
) -> FdcProviderGlobalGate:
    return FdcProviderGlobalGate(
        repo=repo or InMemoryFdcQuotaRepository(),
        target_rpm=target_rpm,
        window_seconds=window_seconds,
        gate_scope=gate_scope,
    )


class TestFdcProviderGlobalGateAcquire:
    @pytest.mark.asyncio
    async def test_grant_returns_permit_result_granted_true(self) -> None:
        gate = _make_gate(target_rpm=13)
        result = await gate.acquire(caller_lane="legacy", caller_id="legacy:test")
        assert result.granted is True
        assert result.denial_reason is None

    @pytest.mark.asyncio
    async def test_13th_grant_succeeds_14th_denied_with_global_gate_timeout(self) -> None:
        """60초 sliding window 13건 경계 — 13번째까지는 grant, 14번째는
        거부되고 ``denial_reason="global_gate_timeout"``이어야 한다."""
        repo = InMemoryFdcQuotaRepository()
        gate = _make_gate(repo=repo, target_rpm=13)

        results = [
            await gate.acquire(caller_lane="legacy", caller_id=f"legacy:{i}")
            for i in range(14)
        ]
        assert all(r.granted for r in results[:13])
        assert results[13].granted is False
        assert results[13].denial_reason == "global_gate_timeout"

    @pytest.mark.asyncio
    async def test_legacy_and_actual_lanes_share_the_same_window(self) -> None:
        """legacy/actual lane 구분 없이 gate_scope 전체를 합산한다 —
        이것이 이 gate의 존재 이유다(설계 문서 §0/§4)."""
        repo = InMemoryFdcQuotaRepository()
        gate = _make_gate(repo=repo, target_rpm=2)

        r1 = await gate.acquire(caller_lane="legacy", caller_id="legacy:a")
        r2 = await gate.acquire(caller_lane="actual", caller_id="actual:job=1")
        r3 = await gate.acquire(caller_lane="legacy", caller_id="legacy:b")

        assert r1.granted and r2.granted
        assert r3.granted is False, (
            "legacy 1건 + actual 1건 = 이미 target_rpm(2) 도달 — 세 번째는 "
            "lane과 무관하게 거부돼야 한다"
        )

    @pytest.mark.asyncio
    async def test_grant_consumes_slot_even_if_caller_never_starts_http(self) -> None:
        """grant는 실제 HTTP 시작 여부와 무관하게 즉시 window 슬롯을
        소비한다(보수적 소비 규칙, 환불 없음) — grant만 받고 아무 후속
        조치를 하지 않아도 window count에는 그대로 반영된다."""
        repo = InMemoryFdcQuotaRepository()
        gate = _make_gate(repo=repo, target_rpm=1)

        first = await gate.acquire(caller_lane="legacy", caller_id="legacy:a")
        assert first.granted is True
        # "HTTP를 실제로 시작"하는 어떤 후속 동작도 호출하지 않았다 —
        # 그런데도 같은 window 안의 두 번째 시도는 거부돼야 한다.
        second = await gate.acquire(caller_lane="legacy", caller_id="legacy:b")
        assert second.granted is False

    @pytest.mark.asyncio
    async def test_coordinator_error_maps_to_global_gate_error(self) -> None:
        """gate 자체의 DB/lock/connection 오류는 fail-closed —
        ``denial_reason="global_gate_error"``로 매핑된다(정상 거부인
        "global_gate_timeout"과 구분)."""

        class _FailingRepo:
            async def try_acquire_provider_global_gate_permit(self, **kwargs):
                return CoordinatorError(
                    CoordinatorErrorClass.COORDINATOR_LOCK_TIMEOUT, "boom",
                )

        gate = _make_gate(repo=_FailingRepo())
        result = await gate.acquire(caller_lane="legacy", caller_id="legacy:test")
        assert result.granted is False
        assert result.denial_reason == "global_gate_error"

    @pytest.mark.asyncio
    async def test_default_gate_scope_constant(self) -> None:
        assert DEFAULT_GATE_SCOPE == "gemini:provider-global"

    # ── Finding 1 보정(2026-09-03) — global gate 자체의 rate 불변식.
    # FDC_PROVIDER_TARGET_RPM/FDC_PROVIDER_RATE_WINDOW_SECONDS가
    # "legacy+actual 합산 13 RPM"을 보장할 수 없는 값이면, gate는
    # repository/DB를 전혀 건드리지 않고 즉시 fail-closed(denial_
    # reason="global_gate_error")한다.

    @pytest.mark.asyncio
    async def test_target_rpm_14_fails_closed_without_touching_repo(self) -> None:
        call_count = {"n": 0}

        class _CountingRepo:
            async def try_acquire_provider_global_gate_permit(self, **kwargs):
                call_count["n"] += 1
                raise AssertionError("repository should not be called for invalid config")

        gate = FdcProviderGlobalGate(repo=_CountingRepo(), target_rpm=14, window_seconds=60)
        result = await gate.acquire(caller_lane="legacy", caller_id="legacy:test")

        assert result.granted is False
        assert result.denial_reason == "global_gate_error"
        assert call_count["n"] == 0

    @pytest.mark.asyncio
    async def test_window_seconds_30_fails_closed_without_touching_repo(self) -> None:
        call_count = {"n": 0}

        class _CountingRepo:
            async def try_acquire_provider_global_gate_permit(self, **kwargs):
                call_count["n"] += 1
                raise AssertionError("repository should not be called for invalid config")

        gate = FdcProviderGlobalGate(repo=_CountingRepo(), target_rpm=13, window_seconds=30)
        result = await gate.acquire(caller_lane="legacy", caller_id="legacy:test")

        assert result.granted is False
        assert result.denial_reason == "global_gate_error"
        assert call_count["n"] == 0

    @pytest.mark.asyncio
    async def test_target_rpm_below_13_is_allowed_more_conservative(self) -> None:
        """13보다 낮은 target은 더 보수적일 뿐 13 RPM 상한 계약을
        깨지 않으므로 허용된다(fail-closed 대상이 아니다)."""
        gate = _make_gate(target_rpm=1, window_seconds=60)
        result = await gate.acquire(caller_lane="legacy", caller_id="legacy:test")
        assert result.granted is True

    @pytest.mark.asyncio
    async def test_target_rpm_1_is_allowed_boundary(self) -> None:
        gate = _make_gate(target_rpm=1, window_seconds=60)
        result = await gate.acquire(caller_lane="legacy", caller_id="legacy:test")
        assert result.granted is True

    @pytest.mark.asyncio
    async def test_target_rpm_13_window_60_boundary_still_valid(self) -> None:
        """정상 경계(target=13, window=60)는 여전히 유효한 설정이다 —
        13번째까지 grant, 14번째부터 window 포화로 거부(§ 기존 테스트
        test_13th_grant_succeeds_14th_denied_with_global_gate_timeout
        과 동일 계약, 여기서는 유효성 검사 자체만 별도로 재확인)."""
        gate = _make_gate(target_rpm=13, window_seconds=60)
        result = await gate.acquire(caller_lane="legacy", caller_id="legacy:test")
        assert result.granted is True
        assert result.denial_reason is None


class TestInMemoryTryAcquireProviderGlobalGatePermit:
    """``InMemoryFdcQuotaRepository.try_acquire_provider_global_gate_
    permit()``이 actual coordinator의 ``_jobs``/``_attempts``/
    ``_shadow_jobs``와 완전히 독립적임을 직접 검증한다."""

    @pytest.mark.asyncio
    async def test_independent_from_actual_coordinator_window(self) -> None:
        repo = InMemoryFdcQuotaRepository()
        # actual coordinator의 자기 자신의 window를 먼저 가득 채운다.
        for _ in range(13):
            await repo.try_reserve(
                quota_scope="gemini:shared-operational", target_rpm=13,
                window_seconds=60, job_id=None, caller_id="actual:test",
            )
        # global gate는 별도 저장 구조이므로 여전히 grant돼야 한다.
        result = await repo.try_acquire_provider_global_gate_permit(
            gate_scope=DEFAULT_GATE_SCOPE, target_rpm=13, window_seconds=60,
            caller_lane="actual", caller_id="actual:test",
        )
        assert isinstance(result, ProviderGlobalGateGranted)

    @pytest.mark.asyncio
    async def test_window_count_before_grant_reported(self) -> None:
        repo = InMemoryFdcQuotaRepository()
        r1 = await repo.try_acquire_provider_global_gate_permit(
            gate_scope="test:scope", target_rpm=13, window_seconds=60,
            caller_lane="legacy", caller_id="legacy:a",
        )
        r2 = await repo.try_acquire_provider_global_gate_permit(
            gate_scope="test:scope", target_rpm=13, window_seconds=60,
            caller_lane="legacy", caller_id="legacy:b",
        )
        assert isinstance(r1, ProviderGlobalGateGranted)
        assert isinstance(r2, ProviderGlobalGateGranted)
        assert r1.window_count_before_grant == 0
        assert r2.window_count_before_grant == 1


# ---------------------------------------------------------------------------
# Integration tests — real PostgreSQL row-lock/boundary/concurrency behavior
# cannot be faked with the in-memory repo. Skipped unless DATABASE_HOST is
# set (same pattern as tests/services/test_fdc_quota_coordinator.py).
# ---------------------------------------------------------------------------


pytestmark_db = pytest.mark.skipif(
    not os.getenv("DATABASE_HOST"),
    reason="requires DATABASE_* env vars",
)

import pytest_asyncio


@pytest_asyncio.fixture(loop_scope="function")
async def gate_scope() -> str:
    return f"test-gate:{uuid4()}"


@pytest_asyncio.fixture(loop_scope="function")
async def gate_db_ready(gate_scope: str):
    """pool 생성 + migration 적용 + 이 테스트 전용 anchor 행 seed.

    ``try_acquire_provider_global_gate_permit()``은 자신만의 독립
    트랜잭션을 열어 실제로 commit하므로, teardown에서 이 gate_scope로
    남긴 행만 직접 정리한다(운영 데이터 무관)."""
    from agent_trading.db.connection import close_pool, connection, create_pool
    from agent_trading.db.migrations.run import run_all_migrations

    await create_pool()
    await run_all_migrations()
    async with connection() as conn:
        await conn.execute(
            "INSERT INTO trading.fdc_provider_global_gate_state (gate_scope) "
            "VALUES ($1) ON CONFLICT (gate_scope) DO NOTHING",
            gate_scope,
        )
    try:
        yield
    finally:
        async with connection() as conn:
            await conn.execute(
                "DELETE FROM trading.fdc_provider_global_gate_grants "
                "WHERE gate_scope = $1",
                gate_scope,
            )
            await conn.execute(
                "DELETE FROM trading.fdc_provider_global_gate_state "
                "WHERE gate_scope = $1",
                gate_scope,
            )
        await close_pool()


def _postgres_gate(*, gate_scope: str, target_rpm: int = 13) -> FdcProviderGlobalGate:
    from agent_trading.db.transaction import TransactionManager
    from agent_trading.repositories.postgres.fdc_quota import PostgresFdcQuotaRepository

    repo = PostgresFdcQuotaRepository(TransactionManager())
    return FdcProviderGlobalGate(
        repo=repo, target_rpm=target_rpm, window_seconds=60, gate_scope=gate_scope,
    )


@pytestmark_db
class TestPostgresGlobalGateAtomicWindow:
    @pytest.mark.asyncio
    async def test_concurrent_acquires_never_exceed_target_rpm(
        self, gate_db_ready, gate_scope: str,
    ) -> None:
        """실제 anchor 행 잠금 하에 동시 20건을 요청해도 정확히 target_
        rpm(=5)건만 grant된다 — asyncio.gather로 동시성 경쟁을 실제
        재현(mock으로는 증명 불가)."""
        gate = _postgres_gate(gate_scope=gate_scope, target_rpm=5)

        results = await asyncio.gather(*[
            gate.acquire(caller_lane="legacy" if i % 2 == 0 else "actual",
                         caller_id=f"caller-{i}")
            for i in range(20)
        ])
        granted = [r for r in results if r.granted]
        denied = [r for r in results if not r.granted]
        assert len(granted) == 5, (
            f"target_rpm=5인데 {len(granted)}건 grant됨 — 13 RPM 초과 방지 "
            "계약 위반 가능성"
        )
        assert len(denied) == 15
        assert all(r.denial_reason == "global_gate_timeout" for r in denied)

    @pytest.mark.asyncio
    async def test_exactly_60_seconds_old_grant_excluded_from_window(
        self, gate_db_ready, gate_scope: str,
    ) -> None:
        """(t-60초, t] 반열림 구간 — 정확히 60초 전 grant는 제외돼야
        한다(fdc_quota_coordinator의 기존 window 경계 계약과 동일)."""
        from agent_trading.db.connection import connection

        exactly_60s_ago = datetime.now(timezone.utc) - timedelta(seconds=60)
        async with connection() as conn:
            await conn.execute(
                "INSERT INTO trading.fdc_provider_global_gate_grants "
                "(grant_id, gate_scope, caller_lane, caller_id, granted_at) "
                "VALUES ($1, $2, 'legacy', 'legacy:old', $3)",
                uuid4(), gate_scope, exactly_60s_ago,
            )

        gate = _postgres_gate(gate_scope=gate_scope, target_rpm=1)
        result = await gate.acquire(caller_lane="legacy", caller_id="legacy:new")

        assert result.granted is True, (
            "정확히 60초 전 grant는 창에서 제외돼 target_rpm=1이어도 "
            "승인돼야 한다"
        )

    @pytest.mark.asyncio
    async def test_grant_not_refunded_after_denial_window_stays_full(
        self, gate_db_ready, gate_scope: str,
    ) -> None:
        """grant 후 호출자가 "HTTP를 시작하지 못했다"는 사실을 gate에
        전혀 알리지 않아도(환불 API 자체가 없음) window는 계속 가득 찬
        상태로 유지된다 — 보수적 소비 규칙의 직접 증거."""
        gate = _postgres_gate(gate_scope=gate_scope, target_rpm=1)

        first = await gate.acquire(caller_lane="actual", caller_id="actual:job=1")
        assert first.granted is True

        second = await gate.acquire(caller_lane="actual", caller_id="actual:job=1-retry")
        assert second.granted is False
        assert second.denial_reason == "global_gate_timeout"

    @pytest.mark.asyncio
    async def test_lock_timeout_returns_global_gate_error_and_grants_nothing(
        self, gate_db_ready, gate_scope: str,
    ) -> None:
        """anchor 행 잠금을 다른 트랜잭션이 쥐고 있으면 짧은 lock_
        timeout으로 실패하고, ``denial_reason="global_gate_error"``로
        분류되며 grant 행이 생기지 않는다(fail-closed)."""
        from agent_trading.db.connection import connection
        from agent_trading.db.transaction import TransactionManager
        from agent_trading.repositories.postgres.fdc_quota import (
            PostgresFdcQuotaRepository,
        )

        holder = TransactionManager()
        await holder.__aenter__()
        try:
            await holder.connection.fetchrow(
                "SELECT gate_scope FROM trading.fdc_provider_global_gate_state "
                "WHERE gate_scope = $1 FOR UPDATE",
                gate_scope,
            )
            repo = PostgresFdcQuotaRepository(TransactionManager())
            gate = FdcProviderGlobalGate(
                repo=repo, target_rpm=13, window_seconds=60, gate_scope=gate_scope,
            )
            result = await repo.try_acquire_provider_global_gate_permit(
                gate_scope=gate_scope, target_rpm=13, window_seconds=60,
                caller_lane="legacy", caller_id="legacy:test", lock_timeout_ms=200,
            )
            assert isinstance(result, CoordinatorError)
        finally:
            await holder.rollback()

        async with connection() as conn:
            count = await conn.fetchval(
                "SELECT count(*) FROM trading.fdc_provider_global_gate_grants "
                "WHERE gate_scope = $1",
                gate_scope,
            )
        assert count == 0
