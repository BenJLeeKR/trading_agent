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
    manual_call_policy=None,
) -> FdcQuotaCoordinator:
    return FdcQuotaCoordinator(
        repo=repo or InMemoryFdcQuotaRepository(),
        target_rpm=target_rpm,
        window_seconds=window_seconds,
        quota_scope=quota_scope,
        declared_rpm_limit=declared_rpm_limit,
        manual_call_policy=manual_call_policy,
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


class TestManualCallPolicy:
    """``FdcQuotaCoordinator``의 중앙 fail-closed 경계(2026-08-27 3차
    리뷰 보정 신설) — ``caller_id``가 ``"manual:"``로 시작하는
    reservation 요청만 대상이며, repository에 위임하기 **전에** 정책을
    확인한다."""

    @pytest.mark.asyncio
    async def test_manual_caller_without_policy_is_fail_closed(self) -> None:
        """정책이 주입되지 않았으면 manual: caller는 무조건 거부되고,
        repository는 전혀 호출되지 않는다(quota window 미소비)."""
        repo = InMemoryFdcQuotaRepository()
        coordinator = _make_coordinator(repo=repo, manual_call_policy=None)

        result = await coordinator.try_reserve(job_id=None, caller_id="manual:test-script")

        assert isinstance(result, CoordinatorError)
        assert result.error_class == CoordinatorErrorClass.MANUAL_CALL_POLICY_REJECTED
        assert repo._attempts["test:default"] == []  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_manual_caller_policy_rejects_sends_no_reservation(self) -> None:
        repo = InMemoryFdcQuotaRepository()

        async def _deny() -> bool:
            return False

        coordinator = _make_coordinator(repo=repo, manual_call_policy=_deny)

        result = await coordinator.try_reserve(job_id=None, caller_id="manual:test-script")

        assert isinstance(result, CoordinatorError)
        assert result.error_class == CoordinatorErrorClass.MANUAL_CALL_POLICY_REJECTED
        assert repo._attempts["test:default"] == []  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_manual_caller_policy_allows_reservation_succeeds(self) -> None:
        repo = InMemoryFdcQuotaRepository()

        async def _allow() -> bool:
            return True

        coordinator = _make_coordinator(repo=repo, manual_call_policy=_allow)

        result = await coordinator.try_reserve(job_id=None, caller_id="manual:test-script")

        assert isinstance(result, ReservationGrant)

    @pytest.mark.asyncio
    async def test_non_manual_caller_bypasses_policy_check_entirely(self) -> None:
        """``ops-scheduler`` 같은 manual: 이 아닌 caller는 정책이
        없어도(또는 거부하는 정책이 있어도) 전혀 영향을 받지 않는다."""
        repo = InMemoryFdcQuotaRepository()

        async def _deny() -> bool:
            return False

        coordinator = _make_coordinator(repo=repo, manual_call_policy=_deny)

        result = await coordinator.try_reserve(job_id=None, caller_id="ops-scheduler")

        assert isinstance(result, ReservationGrant)

    @pytest.mark.asyncio
    async def test_manual_caller_policy_is_reevaluated_each_call(self) -> None:
        """정책 콜백이 매 ``try_reserve()`` 호출마다 다시 평가되는지
        (한 번 허용됐다고 캐시되지 않는지) 확인한다."""
        repo = InMemoryFdcQuotaRepository()
        call_count = 0

        async def _flip() -> bool:
            nonlocal call_count
            call_count += 1
            return call_count == 1  # 첫 호출만 허용, 이후는 거부

        coordinator = _make_coordinator(repo=repo, manual_call_policy=_flip)

        first = await coordinator.try_reserve(job_id=None, caller_id="manual:test-script")
        second = await coordinator.try_reserve(job_id=None, caller_id="manual:test-script")

        assert isinstance(first, ReservationGrant)
        assert isinstance(second, CoordinatorError)
        assert call_count == 2


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
            # 2026-08-27(held_position 실제 dispatcher, FIFO 공정성
            # 검사 신설) — register_real_job()이 실제로 채우는 필드를
            # 최소한으로 맞춘다: status="QUEUED"·quota_scope·
            # enqueue_sequence가 없으면 try_reserve()의 FIFO 순번 검사가
            # KeyError를 낸다.
            "status": "QUEUED", "quota_scope": "scope-c", "enqueue_sequence": 1,
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


class TestRealJobRegistrationAndFifoFairness:
    """2026-08-27(held_position 실제 dispatcher, PR #359 리뷰 보정) —
    ``register_real_job()``이 만든 job을 ``try_reserve(job_id=...)``가
    FIFO 순서대로만 grant하는지 검증한다. quota window에 여유가 있어도
    나보다 먼저 등록되고 아직 QUEUED인 job이 있으면 순번을 양보해야
    한다 — "늦게 등록된 job이 먼저 grant받는" 새치기 방지가 핵심."""

    @pytest.mark.asyncio
    async def test_register_real_job_returns_queued_job_id(self) -> None:
        repo = InMemoryFdcQuotaRepository()
        job_id = await repo.register_real_job(
            decision_cycle_id="cycle-1", decision_context_id=None,
            symbol="005930", source_type="held_position",
            quota_scope="scope-fifo", fdc_ready_at=datetime.now(timezone.utc),
        )
        assert job_id in repo._jobs  # type: ignore[attr-defined]
        assert repo._jobs[job_id]["status"] == "QUEUED"  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_later_registered_job_denied_until_earlier_job_resolved(
        self,
    ) -> None:
        """target_rpm이 커서 window 자체는 여유가 있어도, 먼저 등록된
        job A가 아직 QUEUED인 동안 나중에 등록된 job B는 거부된다."""
        repo = InMemoryFdcQuotaRepository()
        coordinator = _make_coordinator(repo=repo, target_rpm=13, quota_scope="scope-fifo-2")

        job_a = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="A",
            source_type="held_position", quota_scope="scope-fifo-2",
            fdc_ready_at=datetime.now(timezone.utc),
        )
        job_b = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="B",
            source_type="held_position", quota_scope="scope-fifo-2",
            fdc_ready_at=datetime.now(timezone.utc),
        )

        # B가 먼저 폴링해도 A가 아직 QUEUED이므로 거부돼야 한다(새치기 방지).
        result_b = await coordinator.try_reserve(job_id=job_b, caller_id="ops-scheduler")
        assert isinstance(result_b, ReservationDenied)

        # A는 정상적으로 grant된다.
        result_a = await coordinator.try_reserve(job_id=job_a, caller_id="ops-scheduler")
        assert isinstance(result_a, ReservationGrant)

        # A가 더 이상 QUEUED가 아니므로(RESERVATION_GRANTED), 이제 B도 grant된다.
        result_b_retry = await coordinator.try_reserve(job_id=job_b, caller_id="ops-scheduler")
        assert isinstance(result_b_retry, ReservationGrant)

    @pytest.mark.asyncio
    async def test_concurrent_polling_never_lets_later_job_win_first(self) -> None:
        """여러 job이 동시에(asyncio.gather) try_reserve()를 폴링해도,
        FIFO 순서대로만 grant된다 — 실행 완료 순서와 무관하다."""
        repo = InMemoryFdcQuotaRepository()
        coordinator = _make_coordinator(repo=repo, target_rpm=13, quota_scope="scope-fifo-3")

        job_ids = []
        for i in range(5):
            job_id = await repo.register_real_job(
                decision_cycle_id="c1", decision_context_id=None, symbol=f"S{i}",
                source_type="held_position", quota_scope="scope-fifo-3",
                fdc_ready_at=datetime.now(timezone.utc),
            )
            job_ids.append(job_id)

        # 등록 역순으로 동시에 폴링(가장 늦게 등록된 job부터 요청) —
        # 그래도 FIFO 순서(job_ids[0]부터)로만 grant돼야 한다.
        results = await asyncio.gather(*[
            coordinator.try_reserve(job_id=jid, caller_id="ops-scheduler")
            for jid in reversed(job_ids)
        ])
        # reversed(job_ids)의 첫 항목은 job_ids[4](가장 늦게 등록됨) —
        # 이 항목만 유일하게 "앞서 QUEUED인 job 없음" 조건을 만족하지
        # 못하므로 거부돼야 하고, 가장 먼저 등록된 job_ids[0](reversed
        # 순서의 마지막 항목)만 즉시 grant돼야 한다.
        result_by_job = dict(zip(reversed(job_ids), results))
        assert isinstance(result_by_job[job_ids[0]], ReservationGrant)
        for jid in job_ids[1:]:
            assert isinstance(result_by_job[jid], ReservationDenied)

    @pytest.mark.asyncio
    async def test_non_job_reservation_unaffected_by_fifo_check(self) -> None:
        """job_id=None(기존 manual 스크립트 경로)은 FIFO 검사 대상이
        아니다 — 하위 호환 보존."""
        repo = InMemoryFdcQuotaRepository()
        coordinator = _make_coordinator(repo=repo, target_rpm=13, quota_scope="scope-fifo-4")

        # 등록된 QUEUED real job이 있어도 job_id=None 호출은 영향받지 않는다.
        await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="A",
            source_type="held_position", quota_scope="scope-fifo-4",
            fdc_ready_at=datetime.now(timezone.utc),
        )
        result = await coordinator.try_reserve(job_id=None, caller_id="ops-scheduler:other")
        assert isinstance(result, ReservationGrant)


class TestIncompleteCarryoverDoesNotPermanentlyBlockFifo:
    """2026-08-28 5차 리뷰 보정 — durable resume 정보(``pre_fdc_result``/
    ``correlation_id``)가 없는 불완전한 ``QUEUED`` row를
    ``list_resumable_real_jobs()``가 조용히 건너뛰면, ``try_reserve()``의
    FIFO admission("나보다 먼저 등록된 QUEUED job이 있으면 양보")이 그
    불완전한 row 하나 때문에 뒤따르는 모든 real job을 영구 대기시킨다
    (§17.3/§17.7). ``list_resumable_real_jobs()``가 그 row를 즉시
    ``FDC_FAILED_FINAL``로 정리해 FIFO head를 비워야 한다."""

    @pytest.mark.asyncio
    async def test_incomplete_head_row_is_resolved_and_following_row_then_grants(
        self,
    ) -> None:
        repo = InMemoryFdcQuotaRepository()
        coordinator = _make_coordinator(
            repo=repo, target_rpm=13, quota_scope="scope-fifo-incomplete",
        )

        # 불완전한 선행 row(migration 이전 데이터/부분 실패를 재현) —
        # pre_fdc_result/correlation_id를 채우지 않는다.
        incomplete_job = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="INCOMPLETE",
            source_type="held_position", quota_scope="scope-fifo-incomplete",
            fdc_ready_at=datetime.now(timezone.utc),
        )
        # 정상 후속 row.
        normal_job = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="NORMAL",
            source_type="held_position", quota_scope="scope-fifo-incomplete",
            fdc_ready_at=datetime.now(timezone.utc),
            pre_fdc_result={"requires_fdc_dispatch": True}, correlation_id="c-normal",
        )

        # 정리 전: 불완전한 선행 row가 QUEUED로 남아 있어 후속 row가
        # FIFO에 막힌다.
        blocked = await coordinator.try_reserve(
            job_id=normal_job, caller_id="ops-scheduler",
        )
        assert isinstance(blocked, ReservationDenied)

        # list_resumable_real_jobs()가 불완전한 row를 발견 즉시
        # FDC_FAILED_FINAL로 종결하고, resumable 목록에는 정상 row만
        # 남는다.
        resumable = await repo.list_resumable_real_jobs(
            quota_scope="scope-fifo-incomplete",
        )
        assert [r.job_id for r in resumable] == [normal_job]
        assert repo._jobs[incomplete_job]["status"] == "FDC_FAILED_FINAL"  # type: ignore[attr-defined]
        assert repo._jobs[incomplete_job]["failure_or_cancel_reason"] == (  # type: ignore[attr-defined]
            "fdc_carryover_payload_missing_data_integrity_error"
        )

        # 정리 후: 정상 후속 row는 더 이상 FIFO에 막히지 않고 grant된다.
        granted = await coordinator.try_reserve(
            job_id=normal_job, caller_id="ops-scheduler",
        )
        assert isinstance(granted, ReservationGrant)

    @pytest.mark.asyncio
    async def test_missing_correlation_id_gets_distinct_reason(self) -> None:
        repo = InMemoryFdcQuotaRepository()
        job_id = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="A",
            source_type="held_position", quota_scope="scope-fifo-incomplete-2",
            fdc_ready_at=datetime.now(timezone.utc),
            pre_fdc_result={"requires_fdc_dispatch": True}, correlation_id=None,
        )

        resumable = await repo.list_resumable_real_jobs(
            quota_scope="scope-fifo-incomplete-2",
        )

        assert resumable == []
        assert repo._jobs[job_id]["status"] == "FDC_FAILED_FINAL"  # type: ignore[attr-defined]
        assert repo._jobs[job_id]["failure_or_cancel_reason"] == (  # type: ignore[attr-defined]
            "fdc_carryover_correlation_id_missing_data_integrity_error"
        )

    @pytest.mark.asyncio
    async def test_cleanup_is_idempotent(self) -> None:
        repo = InMemoryFdcQuotaRepository()
        job_id = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="A",
            source_type="held_position", quota_scope="scope-fifo-incomplete-3",
            fdc_ready_at=datetime.now(timezone.utc),
        )

        first = await repo.list_resumable_real_jobs(
            quota_scope="scope-fifo-incomplete-3",
        )
        second = await repo.list_resumable_real_jobs(
            quota_scope="scope-fifo-incomplete-3",
        )

        assert first == []
        assert second == []
        assert repo._jobs[job_id]["status"] == "FDC_FAILED_FINAL"  # type: ignore[attr-defined]


class TestCancelStaleRealJobs:
    """2026-08-27 — 재기동 recovery scan(§17.7)이 non-terminal real job만
    ``CANCELLED``로 전이시키는지 검증한다.

    2026-08-28 4차 리뷰 보정 — ``status='QUEUED'``는 더 이상 이 메서드의
    대상이 아니다(``list_resumable_real_jobs()``가 durable하게 안전하게
    재개한다). 이 메서드는 이제 ``status='RESERVATION_GRANTED'``(실제로
    reservation을 받은 뒤 process crash로 결과가 불명확하게 남은 job)
    만 다룬다."""

    @pytest.mark.asyncio
    async def test_queued_job_is_left_untouched_for_durable_resume(self) -> None:
        repo = InMemoryFdcQuotaRepository()
        job_queued = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="A",
            source_type="held_position", quota_scope="scope-recovery",
            fdc_ready_at=datetime.now(timezone.utc),
            pre_fdc_result={"requires_fdc_dispatch": True}, correlation_id="c-a",
        )
        job_granted = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="B",
            source_type="held_position", quota_scope="scope-recovery",
            fdc_ready_at=datetime.now(timezone.utc),
        )
        await repo.mark_job_status(job_id=job_granted, status="RESERVATION_GRANTED")
        job_succeeded = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="C",
            source_type="held_position", quota_scope="scope-recovery",
            fdc_ready_at=datetime.now(timezone.utc),
        )
        await repo.mark_job_terminal(job_id=job_succeeded, status="FDC_SUCCEEDED")

        affected = await repo.cancel_stale_real_jobs(quota_scope="scope-recovery")

        # RESERVATION_GRANTED(attempt 행 없음 → NOT_FOUND 취급)만 전이된다.
        assert affected == 1
        assert repo._jobs[job_queued]["status"] == "QUEUED"  # type: ignore[attr-defined]
        assert repo._jobs[job_queued]["failure_or_cancel_reason"] is None  # type: ignore[attr-defined]
        assert repo._jobs[job_granted]["status"] == "CANCELLED"  # type: ignore[attr-defined]
        assert repo._jobs[job_succeeded]["status"] == "FDC_SUCCEEDED"  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_second_call_is_idempotent(self) -> None:
        repo = InMemoryFdcQuotaRepository()
        job_granted = await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="A",
            source_type="held_position", quota_scope="scope-recovery-2",
            fdc_ready_at=datetime.now(timezone.utc),
        )
        await repo.mark_job_status(job_id=job_granted, status="RESERVATION_GRANTED")

        first = await repo.cancel_stale_real_jobs(quota_scope="scope-recovery-2")
        second = await repo.cancel_stale_real_jobs(quota_scope="scope-recovery-2")

        assert first == 1
        assert second == 0

    @pytest.mark.asyncio
    async def test_does_not_touch_other_quota_scope(self) -> None:
        repo = InMemoryFdcQuotaRepository()
        await repo.register_real_job(
            decision_cycle_id="c1", decision_context_id=None, symbol="A",
            source_type="held_position", quota_scope="scope-a",
            fdc_ready_at=datetime.now(timezone.utc),
        )
        affected = await repo.cancel_stale_real_jobs(quota_scope="scope-b")
        assert affected == 0


class TestRecordAttemptOutcome:
    """``record_attempt_outcome()``(2026-08-27 PR A 신설) — ``try_reserve()``
    가 발급한 reservation의 실제 HTTP 결과를 기록한다. 새 reservation을
    발급하지 않으며, 이미 소비된 window 슬롯의 상태만 갱신한다."""

    @pytest.mark.asyncio
    async def test_updates_outcome_of_existing_reservation(self) -> None:
        repo = InMemoryFdcQuotaRepository()
        coordinator = _make_coordinator(repo=repo, target_rpm=13, quota_scope="scope-outcome-1")

        grant = await coordinator.try_reserve(job_id=None, caller_id="test-caller")
        assert isinstance(grant, ReservationGrant)
        assert repo._attempts_by_id[grant.reservation_id].outcome == "reservation_granted"  # type: ignore[attr-defined]

        await coordinator.record_attempt_outcome(
            reservation_id=grant.reservation_id, outcome="http_succeeded",
        )

        assert repo._attempts_by_id[grant.reservation_id].outcome == "http_succeeded"  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_does_not_create_new_reservation_or_change_window_count(self) -> None:
        """outcome 갱신은 window 판단에 쓰이는 ``_QUOTA_CONSUMING_OUTCOMES``
        집합 밖으로 나가지 않는 한(``http_succeeded``도 그 집합의 일부다)
        window_count에 영향을 주지 않는다 — 새 attempt 행이 생기지 않는다."""
        repo = InMemoryFdcQuotaRepository()
        coordinator = _make_coordinator(repo=repo, target_rpm=1, quota_scope="scope-outcome-2")

        grant = await coordinator.try_reserve(job_id=None, caller_id="test-caller")
        assert isinstance(grant, ReservationGrant)
        before_count = len(repo._attempts["scope-outcome-2"])  # type: ignore[attr-defined]

        await coordinator.record_attempt_outcome(
            reservation_id=grant.reservation_id, outcome="http_succeeded",
        )

        after_count = len(repo._attempts["scope-outcome-2"])  # type: ignore[attr-defined]
        assert after_count == before_count == 1

        # target_rpm=1이므로 두 번째 reservation은 여전히 거부돼야 한다
        # (outcome 갱신이 window를 "비우지" 않았다는 뜻).
        second = await coordinator.try_reserve(job_id=None, caller_id="test-caller")
        assert isinstance(second, ReservationDenied)

    @pytest.mark.asyncio
    async def test_unknown_reservation_id_raises(self) -> None:
        repo = InMemoryFdcQuotaRepository()
        coordinator = _make_coordinator(repo=repo, target_rpm=13, quota_scope="scope-outcome-3")

        with pytest.raises(ValueError, match="unknown reservation_id"):
            await coordinator.record_attempt_outcome(
                reservation_id=uuid4(), outcome="http_succeeded",
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
        assert attempts[0].mode == "shadow"
        assert attempts[0].outcome == "shadow_would_grant"
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


async def _always_allow_manual_call_policy() -> bool:
    return True


def _postgres_coordinator(*, quota_scope: str, target_rpm: int = 13, lock_timeout_ms: int = 3000):
    from agent_trading.db.transaction import TransactionManager
    from agent_trading.repositories.postgres.fdc_quota import PostgresFdcQuotaRepository

    tx = TransactionManager()
    repo = PostgresFdcQuotaRepository(tx)
    return FdcQuotaCoordinator(
        repo=repo, target_rpm=target_rpm, quota_scope=quota_scope,
        lock_timeout_ms=lock_timeout_ms,
        manual_call_policy=_always_allow_manual_call_policy,
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
class TestPostgresRecordAttemptOutcome:
    """``record_attempt_outcome()``(2026-08-27 PR A 신설)의 실제 PostgreSQL
    UPDATE 동작 — 새 행을 만들지 않고 기존 attempt 행만 갱신하는지."""

    @pytest.mark.asyncio
    async def test_updates_outcome_http_status_and_429_flag(
        self, db_ready, quota_scope: str,
    ) -> None:
        from agent_trading.db.connection import connection

        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)
        grant = await coordinator.try_reserve(job_id=None, caller_id="test-caller")
        assert isinstance(grant, ReservationGrant)

        await coordinator.record_attempt_outcome(
            reservation_id=grant.reservation_id,
            outcome="http_failed_retryable",
            http_status=429,
            error_class="httpx.HTTPStatusError",
            http_429_observed=True,
        )

        async with connection() as conn:
            row = await conn.fetchrow(
                "SELECT outcome, http_status, error_class, http_429_observed "
                "FROM trading.fdc_provider_attempts WHERE attempt_id = $1",
                grant.reservation_id,
            )
        assert row is not None
        assert row["outcome"] == "http_failed_retryable"
        assert row["http_status"] == 429
        assert row["error_class"] == "httpx.HTTPStatusError"
        assert row["http_429_observed"] is True

    @pytest.mark.asyncio
    async def test_does_not_insert_a_new_row(
        self, db_ready, quota_scope: str,
    ) -> None:
        from agent_trading.db.connection import connection

        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)
        grant = await coordinator.try_reserve(job_id=None, caller_id="test-caller")
        assert isinstance(grant, ReservationGrant)

        async with connection() as conn:
            before = await conn.fetchval(
                "SELECT count(*) FROM trading.fdc_provider_attempts WHERE quota_scope = $1",
                quota_scope,
            )

        await coordinator.record_attempt_outcome(
            reservation_id=grant.reservation_id, outcome="http_succeeded",
        )

        async with connection() as conn:
            after = await conn.fetchval(
                "SELECT count(*) FROM trading.fdc_provider_attempts WHERE quota_scope = $1",
                quota_scope,
            )
        assert after == before == 1

    @pytest.mark.asyncio
    async def test_reservation_row_starts_with_null_http_started_at(
        self, db_ready, quota_scope: str,
    ) -> None:
        """2026-08-27 리뷰 보정 검증: ``try_reserve()`` 직후(HTTP를 시작
        하기 전)에는 ``http_started_at``이 NULL이어야 한다 — 실제로
        HTTP를 시작하지 못한 경우에만 이 상태로 남는다는 계약의 기준선."""
        from agent_trading.db.connection import connection

        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)
        grant = await coordinator.try_reserve(job_id=None, caller_id="test-caller")
        assert isinstance(grant, ReservationGrant)

        async with connection() as conn:
            row = await conn.fetchrow(
                "SELECT http_started_at, outcome FROM trading.fdc_provider_attempts "
                "WHERE attempt_id = $1",
                grant.reservation_id,
            )
        assert row is not None
        assert row["http_started_at"] is None
        assert row["outcome"] == "reservation_granted"

    @pytest.mark.asyncio
    async def test_unknown_reservation_id_raises_value_error(
        self, db_ready, quota_scope: str,
    ) -> None:
        """2026-08-27 리뷰 보정: 대응 행이 없는 ``reservation_id``로
        outcome을 기록하려 하면 조용히 0행 갱신하고 성공한 척하지 않고
        명시적으로 실패한다(감사 기록 누락 은폐 방지)."""
        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)

        with pytest.raises(ValueError, match="no fdc_provider_attempts row"):
            await coordinator.record_attempt_outcome(
                reservation_id=uuid4(), outcome="http_succeeded",
            )


@pytestmark_db
class TestPostgresCallWithCoordinatorLifecycle:
    """``scripts/fdc_manual_provider_gate.py::call_with_coordinator()``가
    실제 PostgreSQL 위에서 attempt별로 정확한 lifecycle을 기록하는지
    검증한다(2026-08-27 리뷰 보정 핵심 — 이전 permit adapter 방식은 이
    수준의 정확도를 낼 수 없었다). 실제 HTTP는 fake client(duck-typed
    ``generate_structured_once()``)로 대체한다 — 외부 Gemini 호출 없음.
    """

    @pytest.mark.asyncio
    async def test_success_records_http_started_at_and_completed_at(
        self, db_ready, quota_scope: str,
    ) -> None:
        from dataclasses import dataclass

        from agent_trading.db.connection import connection
        from agent_trading.services.ai_agents.base import RawProviderResponse
        from scripts.fdc_manual_provider_gate import call_with_coordinator

        @dataclass(slots=True, frozen=True)
        class _Output:
            symbol: str = "AAPL"

        class _FakeLiveClient:
            def __init__(self) -> None:
                self.calls = 0

            async def generate_structured_once(self, grant, *, on_http_start=None, **kwargs):
                if on_http_start is not None:
                    await on_http_start()
                self.calls += 1
                return RawProviderResponse(
                    parsed=_Output(), raw_content="{}",
                    http_attempt_count=1, http_429_count=0,
                )

        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)
        fake_client = _FakeLiveClient()

        result = await call_with_coordinator(
            coordinator=coordinator, client=fake_client, caller_id="manual:test",
            manual_run_id="run-pg-1", model_id="m", system_prompt="s",
            user_prompt="u", response_format=_Output,
        )

        assert result.parsed.symbol == "AAPL"
        assert fake_client.calls == 1

        async with connection() as conn:
            row = await conn.fetchrow(
                "SELECT outcome, http_started_at, completed_at "
                "FROM trading.fdc_provider_attempts WHERE quota_scope = $1",
                quota_scope,
            )
        assert row is not None
        assert row["outcome"] == "http_succeeded"
        assert row["http_started_at"] is not None
        assert row["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_non_manual_caller_id_succeeds_without_manual_call_policy(
        self, db_ready, quota_scope: str,
    ) -> None:
        """2026-08-27(held_position 실제 dispatch): ``manual:`` 접두사가
        아닌 caller_id(ops-scheduler 운영 경로)는 ``manual_call_policy``를
        주입하지 않아도(=``None``) 실제 PostgreSQL 위에서 정상적으로
        reservation/기록이 되는지 확인한다 — §11 fail-closed 정책은
        ``manual:`` 접두사 caller에만 적용되고, 비-manual 호출자는 완전히
        영향받지 않는다는 계약을 InMemory(``TestManualCallPolicy``)뿐
        아니라 실제 lock/transaction 경로에서도 재확인한다."""
        from dataclasses import dataclass

        from agent_trading.db.connection import connection
        from agent_trading.db.transaction import TransactionManager
        from agent_trading.repositories.postgres.fdc_quota import (
            PostgresFdcQuotaRepository,
        )
        from agent_trading.services.ai_agents.base import RawProviderResponse
        from scripts.fdc_manual_provider_gate import call_with_coordinator

        @dataclass(slots=True, frozen=True)
        class _Output:
            symbol: str = "005930"

        class _FakeLiveClient:
            def __init__(self) -> None:
                self.calls = 0

            async def generate_structured_once(self, grant, *, on_http_start=None, **kwargs):
                if on_http_start is not None:
                    await on_http_start()
                self.calls += 1
                return RawProviderResponse(
                    parsed=_Output(), raw_content="{}",
                    http_attempt_count=1, http_429_count=0,
                )

        # manual_call_policy를 명시적으로 주입하지 않는다(None) —
        # scripts/run_agent_subprocess.py::_build_actual_dispatch_fdc_
        # client()가 실제로 그렇게 구성한다(ops-scheduler 운영 경로는
        # §11 fail-closed 정책의 대상이 아니므로). 이 파일의 다른 대부분
        # 테스트가 쓰는 ``_postgres_coordinator()`` 헬퍼는 always-allow
        # 정책을 기본 주입하므로 여기서는 일부러 쓰지 않는다.
        tx = TransactionManager()
        repo = PostgresFdcQuotaRepository(tx)
        coordinator = FdcQuotaCoordinator(
            repo=repo, target_rpm=13, quota_scope=quota_scope,
        )
        fake_client = _FakeLiveClient()

        result = await call_with_coordinator(
            coordinator=coordinator, client=fake_client,
            caller_id="ops-scheduler:held_position_reduce_sell",
            manual_run_id="cycle-corr-1", model_id="m", system_prompt="s",
            user_prompt="u", response_format=_Output,
        )

        assert result.parsed.symbol == "005930"
        assert fake_client.calls == 1

        async with connection() as conn:
            row = await conn.fetchrow(
                "SELECT outcome, http_started_at, completed_at "
                "FROM trading.fdc_provider_attempts WHERE quota_scope = $1",
                quota_scope,
            )
        assert row is not None
        assert row["outcome"] == "http_succeeded"
        assert row["http_started_at"] is not None
        assert row["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_429_retry_creates_new_attempt_row_per_reservation(
        self, db_ready, quota_scope: str,
    ) -> None:
        """429 재시도 시 같은 grant를 재사용하지 않고 매번 새 reservation
        (=새 ``fdc_provider_attempts`` 행)을 얻는지, 각 행의
        outcome/429/timestamp가 정확한지 검증한다."""
        from dataclasses import dataclass

        import httpx

        from agent_trading.db.connection import connection
        from agent_trading.services.ai_agents.base import RawProviderResponse
        from scripts.fdc_manual_provider_gate import call_with_coordinator

        @dataclass(slots=True, frozen=True)
        class _Output:
            symbol: str = "AAPL"

        def _make_429() -> httpx.HTTPStatusError:
            req = httpx.Request("POST", "https://x/v1/chat/completions")
            resp = httpx.Response(429, request=req)
            exc = httpx.HTTPStatusError("429", request=req, response=resp)
            exc.http_attempt_count = 1  # type: ignore[attr-defined]
            exc.http_429_count = 1  # type: ignore[attr-defined]
            return exc

        class _FakeLiveClient:
            def __init__(self) -> None:
                self._outcomes = [_make_429(), RawProviderResponse(
                    parsed=_Output(), raw_content="{}",
                    http_attempt_count=1, http_429_count=0,
                )]
                self.grants_seen = []

            async def generate_structured_once(self, grant, *, on_http_start=None, **kwargs):
                if on_http_start is not None:
                    await on_http_start()
                self.grants_seen.append(grant.reservation_id)
                outcome = self._outcomes.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome

        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)
        fake_client = _FakeLiveClient()

        result = await call_with_coordinator(
            coordinator=coordinator, client=fake_client, caller_id="manual:test",
            manual_run_id="run-pg-2", model_id="m", system_prompt="s",
            user_prompt="u", response_format=_Output, max_attempts=3,
        )

        assert result.parsed.symbol == "AAPL"
        assert len(fake_client.grants_seen) == 2
        assert fake_client.grants_seen[0] != fake_client.grants_seen[1]  # 새 reservation

        async with connection() as conn:
            rows = await conn.fetch(
                "SELECT attempt_id, outcome, http_status, http_429_observed, "
                "http_started_at, completed_at FROM trading.fdc_provider_attempts "
                "WHERE quota_scope = $1 ORDER BY attempt_no",
                quota_scope,
            )
        assert len(rows) == 2  # 재시도마다 별도 행

        first, second = rows
        assert first["attempt_id"] == fake_client.grants_seen[0]
        assert first["outcome"] == "http_failed_retryable"
        assert first["http_status"] == 429
        assert first["http_429_observed"] is True
        assert first["http_started_at"] is not None
        assert first["completed_at"] is not None

        assert second["attempt_id"] == fake_client.grants_seen[1]
        assert second["outcome"] == "http_succeeded"
        assert second["http_429_observed"] is False
        assert second["http_started_at"] is not None
        assert second["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_non_retryable_failure_records_http_started_at_not_null(
        self, db_ready, quota_scope: str,
    ) -> None:
        """HTTP 시작 **후** 실패(non-retryable 4xx 등)는 http_started_at
        이 NULL이 아니어야 한다 — reservation만 받고 HTTP 자체를 시도조차
        못한 경우(별도 시나리오, RESERVED_BUT_HTTP_NOT_STARTED 계열)와
        구분된다."""
        from dataclasses import dataclass

        import httpx

        from agent_trading.db.connection import connection
        from scripts.fdc_manual_provider_gate import call_with_coordinator

        @dataclass(slots=True, frozen=True)
        class _Output:
            symbol: str = "AAPL"

        class _FakeLiveClient:
            async def generate_structured_once(self, grant, *, on_http_start=None, **kwargs):
                if on_http_start is not None:
                    await on_http_start()
                req = httpx.Request("POST", "https://x/v1/chat/completions")
                resp = httpx.Response(400, request=req)
                exc = httpx.HTTPStatusError("400", request=req, response=resp)
                exc.http_attempt_count = 1  # type: ignore[attr-defined]
                exc.http_429_count = 0  # type: ignore[attr-defined]
                raise exc

        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)

        with pytest.raises(httpx.HTTPStatusError):
            await call_with_coordinator(
                coordinator=coordinator, client=_FakeLiveClient(), caller_id="manual:test",
                manual_run_id="run-pg-3", model_id="m", system_prompt="s",
                user_prompt="u", response_format=_Output, max_attempts=3,
            )

        async with connection() as conn:
            row = await conn.fetchrow(
                "SELECT outcome, http_status, http_started_at, completed_at "
                "FROM trading.fdc_provider_attempts WHERE quota_scope = $1",
                quota_scope,
            )
        assert row is not None
        assert row["outcome"] == "http_failed_final"
        assert row["http_status"] == 400
        assert row["http_started_at"] is not None
        assert row["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_on_http_start_hook_db_failure_sends_zero_http(
        self, db_ready, quota_scope: str,
    ) -> None:
        """``on_http_start`` 콜백(coordinator DB 기록) 자체가 실패하면
        실제 HTTP 요청에 해당하는 실행이 **0회**여야 하고, 그 attempt는
        ``reserved_but_http_not_started``로 기록되며 ``http_started_at``
        은 NULL이어야 한다."""
        from dataclasses import dataclass

        from agent_trading.db.connection import connection
        from agent_trading.services.ai_agents.base import RawProviderResponse
        from scripts.fdc_manual_provider_gate import call_with_coordinator

        @dataclass(slots=True, frozen=True)
        class _Output:
            symbol: str = "AAPL"

        class _FailingHookThenSuccessClient:
            """1번째 attempt는 on_http_start 훅 자체가 예외를 던지도록
            강제하고(coordinator DB 기록 실패를 시뮬레이션), 2번째
            attempt는 정상 진행한다."""

            def __init__(self) -> None:
                self.attempt_index = 0
                self.http_post_equivalent_calls = 0

            async def generate_structured_once(self, grant, *, on_http_start=None, **kwargs):
                self.attempt_index += 1
                if self.attempt_index == 1:
                    # 훅 자체를 실패시킨다 — call_with_coordinator가 넘긴
                    # 실제 on_http_start(coordinator.record_attempt_outcome)
                    # 대신, DB 기록이 실패한 상황을 그대로 재현하기 위해
                    # 원래 훅을 호출하지 않고 즉시 예외를 던진다.
                    raise RuntimeError("simulated on_http_start DB failure")
                if on_http_start is not None:
                    await on_http_start()
                self.http_post_equivalent_calls += 1
                return RawProviderResponse(
                    parsed=_Output(), raw_content="{}",
                    http_attempt_count=1, http_429_count=0,
                )

        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)
        fake_client = _FailingHookThenSuccessClient()

        result = await call_with_coordinator(
            coordinator=coordinator, client=fake_client, caller_id="manual:test",
            manual_run_id="run-pg-5", model_id="m", system_prompt="s",
            user_prompt="u", response_format=_Output, max_attempts=3,
        )

        assert result.parsed.symbol == "AAPL"
        assert fake_client.http_post_equivalent_calls == 1  # 1번째는 HTTP 실행 자체가 없었다

        async with connection() as conn:
            rows = await conn.fetch(
                "SELECT outcome, http_started_at, completed_at "
                "FROM trading.fdc_provider_attempts WHERE quota_scope = $1 "
                "ORDER BY attempt_no",
                quota_scope,
            )
        assert len(rows) == 2
        failed_row, success_row = rows
        assert failed_row["outcome"] == "reserved_but_http_not_started"
        assert failed_row["http_started_at"] is None
        assert success_row["outcome"] == "http_succeeded"
        assert success_row["http_started_at"] is not None

    @pytest.mark.asyncio
    async def test_duplicate_http_started_recording_fails_closed_on_postgres(
        self, db_ready, quota_scope: str,
    ) -> None:
        """실제 PostgreSQL 위에서도 같은 reservation에 HTTP 시작을 두 번
        기록하려 하면 명시적으로 실패한다."""
        from datetime import datetime, timezone

        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)
        grant = await coordinator.try_reserve(job_id=None, caller_id="manual:test")
        assert isinstance(grant, ReservationGrant)

        await coordinator.record_attempt_outcome(
            reservation_id=grant.reservation_id, outcome="http_started",
            http_started_at=datetime.now(timezone.utc),
        )

        with pytest.raises(ValueError, match="already has http_started_at"):
            await coordinator.record_attempt_outcome(
                reservation_id=grant.reservation_id, outcome="http_started",
                http_started_at=datetime.now(timezone.utc),
            )


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


@pytestmark_db
class TestPostgresRealJobDispatch:
    """2026-08-27 신설(PR #359 리뷰 보정) — held_position 실제 dispatcher가
    실제 PostgreSQL row-lock/transaction 위에서 FIFO 순번·no-queue-jumping·
    quota-full 시 fallback 없는 대기·429 재시도 새 reservation을 지키는지
    검증한다. 실제 HTTP는 fake client로 대체한다 — 외부 Gemini 호출 없음."""

    @pytest.mark.asyncio
    async def test_13_concurrent_jobs_all_granted_http_at_most_once_each(
        self, db_ready, quota_scope: str,
    ) -> None:
        from dataclasses import dataclass

        from agent_trading.services.ai_agents.base import RawProviderResponse
        from scripts.fdc_manual_provider_gate import run_real_dispatch_job

        @dataclass(slots=True, frozen=True)
        class _Output:
            symbol: str = "AAPL"

        class _FakeLiveClient:
            def __init__(self) -> None:
                self.calls = 0

            async def generate_structured_once(self, grant, *, on_http_start=None, **kwargs):
                if on_http_start is not None:
                    await on_http_start()
                self.calls += 1
                return RawProviderResponse(
                    parsed=_Output(), raw_content="{}",
                    http_attempt_count=1, http_429_count=0,
                )

        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)
        job_ids = [
            await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
                decision_cycle_id="c1", decision_context_id=None, symbol=f"S{i}",
                source_type="held_position", quota_scope=quota_scope,
                fdc_ready_at=datetime.now(timezone.utc),
            )
            for i in range(13)
        ]
        clients = [_FakeLiveClient() for _ in range(13)]

        results = await asyncio.gather(*[
            run_real_dispatch_job(
                coordinator=coordinator, client=clients[i], job_id=job_ids[i],
                caller_id="ops-scheduler:held_position_reduce_sell",
                manual_run_id=f"cycle-{i}", model_id="m", system_prompt="s",
                user_prompt="u", response_format=_Output,
                poll_interval_seconds=0.05,
            )
            for i in range(13)
        ])

        assert all(r.parsed.symbol == "AAPL" for r in results)
        assert all(c.calls == 1 for c in clients)  # HTTP는 각 job당 정확히 1회

    @pytest.mark.asyncio
    async def test_14th_job_stays_queued_until_slot_frees_not_lost(
        self, db_ready, quota_scope: str,
    ) -> None:
        """quota가 가득 차면 fallback HOLD로 끝나지 않고 QUEUED로 남아
        있다가, window가 지나 slot이 회복되면 승인·성공한다."""
        from dataclasses import dataclass

        from agent_trading.services.ai_agents.base import RawProviderResponse
        from scripts.fdc_manual_provider_gate import run_real_dispatch_job

        @dataclass(slots=True, frozen=True)
        class _Output:
            symbol: str = "AAPL"

        class _FakeLiveClient:
            def __init__(self) -> None:
                self.calls = 0

            async def generate_structured_once(self, grant, *, on_http_start=None, **kwargs):
                if on_http_start is not None:
                    await on_http_start()
                self.calls += 1
                return RawProviderResponse(
                    parsed=_Output(), raw_content="{}",
                    http_attempt_count=1, http_429_count=0,
                )

        # 짧은 window(2초)로 실측 가능한 시간 안에 slot 회복을 재현한다.
        coordinator = _postgres_coordinator(
            quota_scope=quota_scope, target_rpm=1,
        )
        coordinator._window_seconds = 2  # type: ignore[attr-defined]

        filler_job = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="FILLER",
            source_type="held_position", quota_scope=quota_scope,
            fdc_ready_at=datetime.now(timezone.utc),
        )
        filler_client = _FakeLiveClient()
        # window를 채운다(target_rpm=1이므로 이 1건으로 가득 참).
        filler_result = await run_real_dispatch_job(
            coordinator=coordinator, client=filler_client, job_id=filler_job,
            caller_id="ops-scheduler:held_position_reduce_sell",
            manual_run_id="cycle-filler", model_id="m", system_prompt="s",
            user_prompt="u", response_format=_Output, poll_interval_seconds=0.1,
        )
        assert filler_result.parsed.symbol == "AAPL"

        queued_job = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="QUEUED",
            source_type="held_position", quota_scope=quota_scope,
            fdc_ready_at=datetime.now(timezone.utc),
        )
        queued_client = _FakeLiveClient()

        # window(2초)가 지나야 승인되므로, 이 호출은 즉시 반환되지 않고
        # 대기 후 성공해야 한다 — fallback으로 즉시 포기하지 않는다.
        result = await run_real_dispatch_job(
            coordinator=coordinator, client=queued_client, job_id=queued_job,
            caller_id="ops-scheduler:held_position_reduce_sell",
            manual_run_id="cycle-queued", model_id="m", system_prompt="s",
            user_prompt="u", response_format=_Output, poll_interval_seconds=0.3,
        )

        assert result.parsed.symbol == "AAPL"
        assert queued_client.calls == 1

    @pytest.mark.asyncio
    async def test_fifo_order_preserved_under_concurrent_polling(
        self, db_ready, quota_scope: str,
    ) -> None:
        """동시에 여러 job이 try_reserve()를 폴링해도 grant된 job 집합은
        항상 FIFO 앞쪽부터 연속된 prefix를 이룬다(중간이 비거나 뒤집히지
        않음) — 실제 PostgreSQL row-lock 위에서 새치기가 발생하지 않는지
        확인한다.

        (구현 노트) 각 `try_reserve()` 호출은 독립된 connection/
        transaction으로 anchor 행 잠금을 놓고 경쟁한다 — 어느 호출이
        먼저 잠금을 얻는지는 Python 쪽 제출 순서와 무관하다. 이 설계가
        보장하는 것은 "나보다 먼저 등록되고 아직 QUEUED인 job이 있으면
        거부"이므로, job_ids[0]이 먼저 grant되어 상태가 바뀌면 같은
        동시 묶음 안에서 job_ids[1]도 곧바로 grant될 수 있다(정상 —
        불필요하게 한 바퀴 더 기다리게 하지 않는다). 따라서 "정확히
        1개만 grant"가 아니라 "grant된 집합이 앞쪽부터 연속된 prefix"가
        올바른 불변식이다.
        """
        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)
        job_ids = [
            await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
                decision_cycle_id="c1", decision_context_id=None, symbol=f"S{i}",
                source_type="held_position", quota_scope=quota_scope,
                fdc_ready_at=datetime.now(timezone.utc),
            )
            for i in range(5)
        ]

        results = await asyncio.gather(*[
            coordinator.try_reserve(
                job_id=jid, caller_id="ops-scheduler:held_position_reduce_sell",
            )
            for jid in reversed(job_ids)
        ])
        result_by_job = dict(zip(reversed(job_ids), results))

        granted_indices = {
            i for i, jid in enumerate(job_ids)
            if isinstance(result_by_job[jid], ReservationGrant)
        }
        assert granted_indices, "적어도 job_ids[0]은 grant돼야 한다"
        assert granted_indices == set(range(len(granted_indices))), (
            f"grant된 인덱스가 앞쪽 prefix가 아니다(새치기 의심): {granted_indices}"
        )
        # prefix 밖의 나머지는 전부 명시적으로 거부됐어야 한다(오류 아님).
        for i, jid in enumerate(job_ids):
            if i not in granted_indices:
                assert isinstance(result_by_job[jid], ReservationDenied)

    @pytest.mark.asyncio
    async def test_40_concurrent_jobs_only_target_rpm_granted_no_reordering(
        self, db_ready, quota_scope: str,
    ) -> None:
        """40개 동시 job 등록·폴링에서도 target_rpm(13)을 절대 넘지 않고,
        grant된 job 집합은 항상 FIFO 앞쪽부터 연속된 prefix를 이룬다
        (순서 역전·중간 새치기 없음). 40-way 동시 접속 자체의 connection/
        lock 경합으로 일부 호출이 ``CoordinatorError``(fail-closed)를
        받을 수 있으므로 그 경우는 실패로 보지 않는다 — 실제 dispatcher
        (``run_real_dispatch_job()``)도 이 경우 재시도로 흡수한다."""
        coordinator = _postgres_coordinator(
            quota_scope=quota_scope, target_rpm=13, lock_timeout_ms=15000,
        )
        job_ids = [
            await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
                decision_cycle_id="c1", decision_context_id=None, symbol=f"S{i}",
                source_type="held_position", quota_scope=quota_scope,
                fdc_ready_at=datetime.now(timezone.utc),
            )
            for i in range(40)
        ]

        results = await asyncio.gather(*[
            coordinator.try_reserve(
                job_id=jid, caller_id="ops-scheduler:held_position_reduce_sell",
            )
            for jid in job_ids
        ])
        result_by_job = dict(zip(job_ids, results))

        granted_indices = {
            i for i, jid in enumerate(job_ids)
            if isinstance(result_by_job[jid], ReservationGrant)
        }
        assert len(granted_indices) <= 13  # window 상한을 절대 넘지 않는다
        assert granted_indices == set(range(len(granted_indices))), (
            f"grant된 인덱스가 앞쪽 prefix가 아니다(새치기 의심): {granted_indices}"
        )

    @pytest.mark.asyncio
    async def test_lock_timeout_and_coordinator_unavailable_send_zero_http(
        self, db_ready, quota_scope: str,
    ) -> None:
        """anchor 행 잠금이 lock_timeout 안에 풀리지 않으면 coordinator
        오류가 반환되고, HTTP는 전혀 나가지 않는다."""
        from dataclasses import dataclass

        from agent_trading.db.transaction import TransactionManager

        @dataclass(slots=True, frozen=True)
        class _Output:
            symbol: str = "AAPL"

        class _CountingClient:
            def __init__(self) -> None:
                self.calls = 0

            async def generate_structured_once(self, grant, *, on_http_start=None, **kwargs):
                self.calls += 1
                raise AssertionError("HTTP가 호출되면 안 된다")

        job_id = None
        async with TransactionManager() as holder_tx:
            await holder_tx.connection.execute(
                "SELECT * FROM trading.fdc_quota_state WHERE quota_scope = $1 FOR UPDATE",
                quota_scope,
            )
            coordinator = _postgres_coordinator(
                quota_scope=quota_scope, target_rpm=13, lock_timeout_ms=200,
            )
            job_id = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
                decision_cycle_id="c1", decision_context_id=None, symbol="LOCKED",
                source_type="held_position", quota_scope=quota_scope,
                fdc_ready_at=datetime.now(timezone.utc),
            )
            client = _CountingClient()
            result = await coordinator.try_reserve(
                job_id=job_id, caller_id="ops-scheduler:held_position_reduce_sell",
            )
            assert isinstance(result, CoordinatorError)
            assert result.error_class == CoordinatorErrorClass.COORDINATOR_LOCK_TIMEOUT
            assert client.calls == 0
            await holder_tx.rollback()

    @pytest.mark.asyncio
    async def test_provider_retry_uses_new_reservation_and_attempt_row(
        self, db_ready, quota_scope: str,
    ) -> None:
        from dataclasses import dataclass

        import httpx

        from agent_trading.db.connection import connection
        from agent_trading.services.ai_agents.base import RawProviderResponse
        from scripts.fdc_manual_provider_gate import run_real_dispatch_job

        @dataclass(slots=True, frozen=True)
        class _Output:
            symbol: str = "AAPL"

        def _make_429() -> httpx.HTTPStatusError:
            req = httpx.Request("POST", "https://x/v1/chat/completions")
            resp = httpx.Response(429, request=req)
            exc = httpx.HTTPStatusError("429", request=req, response=resp)
            exc.http_attempt_count = 1  # type: ignore[attr-defined]
            exc.http_429_count = 1  # type: ignore[attr-defined]
            return exc

        class _FakeLiveClient:
            def __init__(self) -> None:
                self._outcomes = [_make_429(), RawProviderResponse(
                    parsed=_Output(), raw_content="{}",
                    http_attempt_count=1, http_429_count=0,
                )]
                self.calls = 0

            async def generate_structured_once(self, grant, *, on_http_start=None, **kwargs):
                if on_http_start is not None:
                    await on_http_start()
                self.calls += 1
                outcome = self._outcomes.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome

        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)
        job_id = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="005930",
            source_type="held_position", quota_scope=quota_scope,
            fdc_ready_at=datetime.now(timezone.utc),
        )
        client = _FakeLiveClient()

        result = await run_real_dispatch_job(
            coordinator=coordinator, client=client, job_id=job_id,
            caller_id="ops-scheduler:held_position_reduce_sell",
            manual_run_id="cycle-1", model_id="m", system_prompt="s",
            user_prompt="u", response_format=_Output,
        )

        assert result.parsed.symbol == "AAPL"
        assert client.calls == 2
        async with connection() as conn:
            rows = await conn.fetch(
                "SELECT attempt_id, outcome FROM trading.fdc_provider_attempts "
                "WHERE job_id = $1 ORDER BY reserved_at",
                job_id,
            )
        assert len(rows) == 2  # 새 reservation = 새 attempt 행
        assert rows[0]["attempt_id"] != rows[1]["attempt_id"]
        assert rows[0]["outcome"] == "http_failed_retryable"
        assert rows[1]["outcome"] == "http_succeeded"

    @pytest.mark.asyncio
    async def test_recovery_scan_idempotent_against_real_db(
        self, db_ready, quota_scope: str,
    ) -> None:
        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)
        job_queued = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="A",
            source_type="held_position", quota_scope=quota_scope,
            fdc_ready_at=datetime.now(timezone.utc),
        )
        job_granted_result = await coordinator.try_reserve(
            job_id=job_queued, caller_id="ops-scheduler:held_position_reduce_sell",
        )
        assert isinstance(job_granted_result, ReservationGrant)

        first = await coordinator._repo.cancel_stale_real_jobs(  # type: ignore[attr-defined]
            quota_scope=quota_scope,
        )
        second = await coordinator._repo.cancel_stale_real_jobs(  # type: ignore[attr-defined]
            quota_scope=quota_scope,
        )

        assert first == 1
        assert second == 0

        from agent_trading.db.connection import connection
        async with connection() as conn:
            row = await conn.fetchrow(
                "SELECT status, failure_or_cancel_reason FROM trading.fdc_queue_jobs "
                "WHERE job_id = $1",
                job_queued,
            )
        assert row["status"] == "CANCELLED"
        assert row["failure_or_cancel_reason"] == "process_terminated_carryover_lost"

    @pytest.mark.asyncio
    async def test_list_resumable_real_jobs_round_trips_pre_fdc_result_via_real_db(
        self, db_ready, quota_scope: str,
    ) -> None:
        """2026-08-28 4차 리뷰 보정 — durable carryover: QUEUED job의
        pre_fdc_result_json/correlation_id가 실제 PostgreSQL JSONB 컬럼을
        거쳐 그대로 왕복하는지, 그리고 recovery scan(cancel_stale_real_
        jobs)이 이 QUEUED job을 더 이상 건드리지 않는지 검증한다."""
        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)
        pre_fdc_result = {
            "success": True,
            "event_output": {"symbol": "A"},
            "requires_fdc_dispatch": True,
        }
        job_id = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="A",
            source_type="held_position", quota_scope=quota_scope,
            fdc_ready_at=datetime.now(timezone.utc),
            pre_fdc_result=pre_fdc_result, correlation_id="orig-corr-real-db",
        )

        resumable = await coordinator._repo.list_resumable_real_jobs(  # type: ignore[attr-defined]
            quota_scope=quota_scope,
        )

        assert len(resumable) == 1
        assert resumable[0].job_id == job_id
        assert resumable[0].pre_fdc_result == pre_fdc_result
        assert resumable[0].correlation_id == "orig-corr-real-db"

        # QUEUED는 더 이상 recovery scan 대상이 아니다.
        cancelled = await coordinator._repo.cancel_stale_real_jobs(  # type: ignore[attr-defined]
            quota_scope=quota_scope,
        )
        assert cancelled == 0

        from agent_trading.db.connection import connection
        async with connection() as conn:
            row = await conn.fetchrow(
                "SELECT status FROM trading.fdc_queue_jobs WHERE job_id = $1",
                job_id,
            )
        assert row["status"] == "QUEUED"

    @pytest.mark.asyncio
    async def test_incomplete_carryover_row_is_cleaned_up_and_unblocks_fifo_on_real_db(
        self, db_ready, quota_scope: str,
    ) -> None:
        """2026-08-28 5차 리뷰 보정 — 실제 PostgreSQL에서도 불완전한
        QUEUED row(pre_fdc_result_json/correlation_id 없음)가
        list_resumable_real_jobs()로 즉시 FDC_FAILED_FINAL 종결되고,
        그 뒤 정상 후속 row가 FIFO admission을 통과해 grant되는지
        검증한다."""
        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)

        incomplete_job = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="INCOMPLETE",
            source_type="held_position", quota_scope=quota_scope,
            fdc_ready_at=datetime.now(timezone.utc),
        )
        normal_job = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="NORMAL",
            source_type="held_position", quota_scope=quota_scope,
            fdc_ready_at=datetime.now(timezone.utc),
            pre_fdc_result={"requires_fdc_dispatch": True}, correlation_id="c-normal",
        )

        blocked = await coordinator.try_reserve(
            job_id=normal_job, caller_id="ops-scheduler",
        )
        assert isinstance(blocked, ReservationDenied)

        resumable = await coordinator._repo.list_resumable_real_jobs(  # type: ignore[attr-defined]
            quota_scope=quota_scope,
        )
        assert [r.job_id for r in resumable] == [normal_job]

        from agent_trading.db.connection import connection
        async with connection() as conn:
            row = await conn.fetchrow(
                "SELECT status, failure_or_cancel_reason FROM "
                "trading.fdc_queue_jobs WHERE job_id = $1",
                incomplete_job,
            )
        assert row["status"] == "FDC_FAILED_FINAL"
        assert row["failure_or_cancel_reason"] == (
            "fdc_carryover_payload_missing_data_integrity_error"
        )

        granted = await coordinator.try_reserve(
            job_id=normal_job, caller_id="ops-scheduler",
        )
        assert isinstance(granted, ReservationGrant)

    @pytest.mark.asyncio
    async def test_job_counters_consistent_in_real_db(
        self, db_ready, quota_scope: str,
    ) -> None:
        """queue_poll_count = reservation_denied_count + dispatch_attempt_no
        항등식이 실제 fdc_queue_jobs row에서도 성립한다."""
        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=1)
        filler_job = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="FILLER",
            source_type="held_position", quota_scope=quota_scope,
            fdc_ready_at=datetime.now(timezone.utc),
        )
        await coordinator.try_reserve(
            job_id=filler_job, caller_id="ops-scheduler:held_position_reduce_sell",
        )

        target_job = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="TARGET",
            source_type="held_position", quota_scope=quota_scope,
            fdc_ready_at=datetime.now(timezone.utc),
        )
        # target_rpm=1이 이미 filler로 소진돼 거부된다.
        denied = await coordinator.try_reserve(
            job_id=target_job, caller_id="ops-scheduler:held_position_reduce_sell",
        )
        assert isinstance(denied, ReservationDenied)

        from agent_trading.db.connection import connection
        async with connection() as conn:
            row = await conn.fetchrow(
                "SELECT queue_poll_count, reservation_denied_count, "
                "dispatch_attempt_no FROM trading.fdc_queue_jobs WHERE job_id = $1",
                target_job,
            )
        assert row["queue_poll_count"] == (
            row["reservation_denied_count"] + row["dispatch_attempt_no"]
        )
        assert row["reservation_denied_count"] == 1
        assert row["dispatch_attempt_no"] == 0

    @pytest.mark.asyncio
    async def test_retry_reenqueues_to_fifo_tail_and_lets_waiting_job_go_first_real_db(
        self, db_ready, quota_scope: str,
    ) -> None:
        """2026-08-28 6차 리뷰 보정 — A가 먼저 grant된 뒤 retryable 실패,
        B가 이미 QUEUED인 경우: A가 FIFO tail로 재등록되고, A의 재시도는
        B보다 뒤 순서가 돼야 한다(실제 PostgreSQL)."""
        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)
        job_a = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="A",
            source_type="held_position", quota_scope=quota_scope,
            fdc_ready_at=datetime.now(timezone.utc),
        )
        job_b = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="B",
            source_type="held_position", quota_scope=quota_scope,
            fdc_ready_at=datetime.now(timezone.utc),
        )

        grant_a1 = await coordinator.try_reserve(
            job_id=job_a, caller_id="ops-scheduler:held_position_reduce_sell",
        )
        assert isinstance(grant_a1, ReservationGrant)

        await coordinator._repo.apply_retry_failure(  # type: ignore[attr-defined]
            job_id=job_a, reason="provider_retryable_failure", will_retry=True,
        )

        # A의 재시도가 B보다 먼저 폴링해도, B가 아직 QUEUED인 한 거부된다.
        denied_a2 = await coordinator.try_reserve(
            job_id=job_a, caller_id="ops-scheduler:held_position_reduce_sell",
        )
        assert isinstance(denied_a2, ReservationDenied)

        grant_b = await coordinator.try_reserve(
            job_id=job_b, caller_id="ops-scheduler:held_position_reduce_sell",
        )
        assert isinstance(grant_b, ReservationGrant)

        grant_a2 = await coordinator.try_reserve(
            job_id=job_a, caller_id="ops-scheduler:held_position_reduce_sell",
            attempt_no=2,
        )
        assert isinstance(grant_a2, ReservationGrant)

        from agent_trading.db.connection import connection
        async with connection() as conn:
            row_a = await conn.fetchrow(
                "SELECT status, provider_retry_count, queue_reenqueue_count, "
                "pre_http_execution_failure_count FROM trading.fdc_queue_jobs "
                "WHERE job_id = $1",
                job_a,
            )
        assert row_a["status"] == "RESERVATION_GRANTED"
        assert row_a["provider_retry_count"] == 1
        assert row_a["queue_reenqueue_count"] == 1
        assert row_a["pre_http_execution_failure_count"] == 0

    @pytest.mark.asyncio
    async def test_pre_http_failure_retry_counters_and_no_queue_jump_real_db(
        self, db_ready, quota_scope: str,
    ) -> None:
        """HTTP 시작 전 실패 후 재시도 — pre-HTTP counter/reenqueue
        counter가 정확히 증가하고, 후속 job을 앞지르지 않는다."""
        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)
        job_a = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="A",
            source_type="held_position", quota_scope=quota_scope,
            fdc_ready_at=datetime.now(timezone.utc),
        )
        job_b = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="B",
            source_type="held_position", quota_scope=quota_scope,
            fdc_ready_at=datetime.now(timezone.utc),
        )

        grant_a1 = await coordinator.try_reserve(
            job_id=job_a, caller_id="ops-scheduler:held_position_reduce_sell",
        )
        assert isinstance(grant_a1, ReservationGrant)

        # HTTP 시작 전 worker/subprocess 생성 실패 재현.
        await coordinator._repo.apply_retry_failure(  # type: ignore[attr-defined]
            job_id=job_a, reason="pre_http_execution_failure", will_retry=True,
        )

        denied_a2 = await coordinator.try_reserve(
            job_id=job_a, caller_id="ops-scheduler:held_position_reduce_sell",
            attempt_no=2,
        )
        assert isinstance(denied_a2, ReservationDenied)  # B가 아직 QUEUED

        grant_b = await coordinator.try_reserve(
            job_id=job_b, caller_id="ops-scheduler:held_position_reduce_sell",
        )
        assert isinstance(grant_b, ReservationGrant)

        from agent_trading.db.connection import connection
        async with connection() as conn:
            row_a = await conn.fetchrow(
                "SELECT status, pre_http_execution_failure_count, "
                "reserved_but_http_not_started_count, queue_reenqueue_count, "
                "provider_retry_count FROM trading.fdc_queue_jobs WHERE job_id = $1",
                job_a,
            )
        assert row_a["status"] == "QUEUED"
        assert row_a["pre_http_execution_failure_count"] == 1
        assert row_a["reserved_but_http_not_started_count"] == 1
        assert row_a["queue_reenqueue_count"] == 1
        assert row_a["provider_retry_count"] == 0

    @pytest.mark.asyncio
    async def test_provider_429_retry_counters_and_no_duplicate_http_start_real_db(
        self, db_ready, quota_scope: str,
    ) -> None:
        """provider 429 후 재시도 — provider_retry_count/queue_reenqueue_
        count/http_attempt_count/http_429_count가 실제 값과 일치하고,
        새 reservation/attempt가 쓰이며, 동일 reservation의 HTTP 시작
        중복 기록은 불가능하다."""
        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)
        job_id = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="A",
            source_type="held_position", quota_scope=quota_scope,
            fdc_ready_at=datetime.now(timezone.utc),
        )

        grant1 = await coordinator.try_reserve(
            job_id=job_id, caller_id="ops-scheduler:held_position_reduce_sell",
        )
        assert isinstance(grant1, ReservationGrant)
        await coordinator.record_attempt_outcome(
            reservation_id=grant1.reservation_id, outcome="http_started",
            http_started_at=datetime.now(timezone.utc),
        )
        # 동일 reservation의 HTTP 시작 중복 기록은 불가능하다.
        with pytest.raises(ValueError):
            await coordinator.record_attempt_outcome(
                reservation_id=grant1.reservation_id, outcome="http_started",
                http_started_at=datetime.now(timezone.utc),
            )
        await coordinator.record_attempt_outcome(
            reservation_id=grant1.reservation_id, outcome="http_failed_retryable",
            http_status=429, http_429_observed=True,
        )
        await coordinator._repo.record_http_attempt_counters(  # type: ignore[attr-defined]
            job_id=job_id, http_429_observed=True,
        )
        await coordinator._repo.apply_retry_failure(  # type: ignore[attr-defined]
            job_id=job_id, reason="provider_retryable_failure", will_retry=True,
        )

        grant2 = await coordinator.try_reserve(
            job_id=job_id, caller_id="ops-scheduler:held_position_reduce_sell",
            attempt_no=2,
        )
        assert isinstance(grant2, ReservationGrant)
        assert grant2.reservation_id != grant1.reservation_id  # 새 reservation
        await coordinator.record_attempt_outcome(
            reservation_id=grant2.reservation_id, outcome="http_succeeded",
            http_started_at=datetime.now(timezone.utc),
        )
        await coordinator._repo.record_http_attempt_counters(  # type: ignore[attr-defined]
            job_id=job_id, http_429_observed=False,
        )

        from agent_trading.db.connection import connection
        async with connection() as conn:
            row = await conn.fetchrow(
                "SELECT provider_retry_count, queue_reenqueue_count, "
                "http_attempt_count, http_429_count, permit_consumed_count "
                "FROM trading.fdc_queue_jobs WHERE job_id = $1",
                job_id,
            )
            attempt_rows = await conn.fetch(
                "SELECT attempt_id FROM trading.fdc_provider_attempts "
                "WHERE job_id = $1",
                job_id,
            )
        assert row["provider_retry_count"] == 1
        assert row["queue_reenqueue_count"] == 1
        assert row["http_attempt_count"] == 2
        assert row["http_429_count"] == 1
        assert row["permit_consumed_count"] == 2
        assert row["http_attempt_count"] <= row["permit_consumed_count"]
        assert len(attempt_rows) == 2  # 새 reservation = 새 attempt 행

    @pytest.mark.asyncio
    async def test_provider_429_exhaustion_counts_only_actual_reenqueues_real_db(
        self, db_ready, quota_scope: str,
    ) -> None:
        """2026-08-28 7차 리뷰 보정 — 최대 HTTP 시도 3회 모두 retryable
        429로 실패하면: 실제 HTTP 시도 3회, 실제 FIFO tail 재등록은
        2회뿐이다(마지막 3차 실패는 재등록 없이 곧바로 FDC_FAILED_
        FINAL로 종결) — 실제 PostgreSQL로 검증한다."""
        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)
        job_id = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="A",
            source_type="held_position", quota_scope=quota_scope,
            fdc_ready_at=datetime.now(timezone.utc),
        )

        for attempt_no in (1, 2, 3):
            grant = await coordinator.try_reserve(
                job_id=job_id, caller_id="ops-scheduler:held_position_reduce_sell",
                attempt_no=attempt_no,
            )
            assert isinstance(grant, ReservationGrant)
            await coordinator.record_attempt_outcome(
                reservation_id=grant.reservation_id, outcome="http_started",
                http_started_at=datetime.now(timezone.utc),
            )
            await coordinator.record_attempt_outcome(
                reservation_id=grant.reservation_id, outcome="http_failed_retryable",
                http_status=429, http_429_observed=True,
            )
            await coordinator._repo.record_http_attempt_counters(  # type: ignore[attr-defined]
                job_id=job_id, http_429_observed=True,
            )
            will_retry = attempt_no < 3
            await coordinator._repo.apply_retry_failure(  # type: ignore[attr-defined]
                job_id=job_id, reason="provider_retryable_failure",
                will_retry=will_retry,
            )
        await coordinator._repo.mark_job_terminal(  # type: ignore[attr-defined]
            job_id=job_id, status="FDC_FAILED_FINAL", reason="provider_rate_limit",
        )

        from agent_trading.db.connection import connection
        async with connection() as conn:
            row = await conn.fetchrow(
                "SELECT status, failure_or_cancel_reason, provider_retry_count, "
                "queue_reenqueue_count, http_attempt_count, http_429_count, "
                "permit_consumed_count FROM trading.fdc_queue_jobs WHERE job_id = $1",
                job_id,
            )
            attempt_rows = await conn.fetch(
                "SELECT attempt_id FROM trading.fdc_provider_attempts WHERE job_id = $1",
                job_id,
            )
        assert row["status"] == "FDC_FAILED_FINAL"
        assert row["failure_or_cancel_reason"] == "provider_rate_limit"
        assert row["provider_retry_count"] == 2  # 실제 재등록은 2회뿐
        assert row["queue_reenqueue_count"] == 2
        assert row["http_attempt_count"] == 3  # HTTP 시도 자체는 3회
        assert row["http_429_count"] == 3
        assert row["permit_consumed_count"] == 3
        assert len(attempt_rows) == 3  # 시도마다 새 attempt 행

    @pytest.mark.asyncio
    async def test_pre_http_failure_exhaustion_counts_only_actual_reenqueues_real_db(
        self, db_ready, quota_scope: str,
    ) -> None:
        """pre-HTTP 실패가 최대 횟수까지 소진되는 경우도 동일 원칙이
        적용된다 — pre_http_execution_failure_count는 실제 재등록
        횟수(2회)와 일치하고, reserved_but_http_not_started_count는
        attempt 단위 관측값이므로 3회 전부 반영된다."""
        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)
        job_id = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="A",
            source_type="held_position", quota_scope=quota_scope,
            fdc_ready_at=datetime.now(timezone.utc),
        )

        for attempt_no in (1, 2, 3):
            grant = await coordinator.try_reserve(
                job_id=job_id, caller_id="ops-scheduler:held_position_reduce_sell",
                attempt_no=attempt_no,
            )
            assert isinstance(grant, ReservationGrant)
            # HTTP 시작 전 worker/subprocess 생성 실패 재현.
            await coordinator.record_attempt_outcome(
                reservation_id=grant.reservation_id,
                outcome="reserved_but_http_not_started",
                error_class="FdcOnlySubprocessCrashOrTimeout",
            )
            will_retry = attempt_no < 3
            await coordinator._repo.apply_retry_failure(  # type: ignore[attr-defined]
                job_id=job_id, reason="pre_http_execution_failure",
                will_retry=will_retry,
            )
        await coordinator._repo.mark_job_terminal(  # type: ignore[attr-defined]
            job_id=job_id, status="FDC_FAILED_FINAL",
            reason="fdc_only_subprocess_exhausted",
        )

        from agent_trading.db.connection import connection
        async with connection() as conn:
            row = await conn.fetchrow(
                "SELECT status, failure_or_cancel_reason, "
                "pre_http_execution_failure_count, reserved_but_http_not_started_count, "
                "queue_reenqueue_count, provider_retry_count, http_attempt_count "
                "FROM trading.fdc_queue_jobs WHERE job_id = $1",
                job_id,
            )
        assert row["status"] == "FDC_FAILED_FINAL"
        assert row["failure_or_cancel_reason"] == "fdc_only_subprocess_exhausted"
        assert row["pre_http_execution_failure_count"] == 2  # 실제 재등록은 2회뿐
        assert row["reserved_but_http_not_started_count"] == 3  # attempt 단위 관측값
        assert row["queue_reenqueue_count"] == 2
        assert row["provider_retry_count"] == 0
        assert row["http_attempt_count"] == 0  # HTTP는 한 번도 시작되지 않았다

    @pytest.mark.asyncio
    async def test_success_and_nonretryable_failure_do_not_touch_retry_counters_real_db(
        self, db_ready, quota_scope: str,
    ) -> None:
        """성공 및 non-retryable 실패 — retry/requeue counter가 증가하지
        않고, terminal status와 attempt outcome이 일치한다."""
        coordinator = _postgres_coordinator(quota_scope=quota_scope, target_rpm=13)

        job_success = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="SUCCESS",
            source_type="held_position", quota_scope=quota_scope,
            fdc_ready_at=datetime.now(timezone.utc),
        )
        grant_s = await coordinator.try_reserve(
            job_id=job_success, caller_id="ops-scheduler:held_position_reduce_sell",
        )
        assert isinstance(grant_s, ReservationGrant)
        await coordinator.record_attempt_outcome(
            reservation_id=grant_s.reservation_id, outcome="http_succeeded",
            http_started_at=datetime.now(timezone.utc),
        )
        await coordinator._repo.record_http_attempt_counters(  # type: ignore[attr-defined]
            job_id=job_success, http_429_observed=False,
        )
        await coordinator._repo.mark_job_terminal(  # type: ignore[attr-defined]
            job_id=job_success, status="FDC_SUCCEEDED",
        )

        job_nonretryable = await coordinator._repo.register_real_job(  # type: ignore[attr-defined]
            decision_cycle_id="c1", decision_context_id=None, symbol="NONRETRYABLE",
            source_type="held_position", quota_scope=quota_scope,
            fdc_ready_at=datetime.now(timezone.utc),
        )
        grant_n = await coordinator.try_reserve(
            job_id=job_nonretryable, caller_id="ops-scheduler:held_position_reduce_sell",
        )
        assert isinstance(grant_n, ReservationGrant)
        await coordinator.record_attempt_outcome(
            reservation_id=grant_n.reservation_id, outcome="http_failed_final",
            http_status=400, http_started_at=datetime.now(timezone.utc),
        )
        await coordinator._repo.record_http_attempt_counters(  # type: ignore[attr-defined]
            job_id=job_nonretryable, http_429_observed=False,
        )
        await coordinator._repo.mark_job_terminal(  # type: ignore[attr-defined]
            job_id=job_nonretryable, status="FDC_FAILED_FINAL",
            reason="provider_nonretryable",
        )

        from agent_trading.db.connection import connection
        async with connection() as conn:
            row_s = await conn.fetchrow(
                "SELECT status, provider_retry_count, pre_http_execution_failure_count, "
                "queue_reenqueue_count, http_attempt_count FROM trading.fdc_queue_jobs "
                "WHERE job_id = $1",
                job_success,
            )
            row_n = await conn.fetchrow(
                "SELECT status, failure_or_cancel_reason, provider_retry_count, "
                "queue_reenqueue_count, http_attempt_count FROM trading.fdc_queue_jobs "
                "WHERE job_id = $1",
                job_nonretryable,
            )
        assert row_s["status"] == "FDC_SUCCEEDED"
        assert row_s["provider_retry_count"] == 0
        assert row_s["pre_http_execution_failure_count"] == 0
        assert row_s["queue_reenqueue_count"] == 0
        assert row_s["http_attempt_count"] == 1

        assert row_n["status"] == "FDC_FAILED_FINAL"
        assert row_n["failure_or_cancel_reason"] == "provider_nonretryable"
        assert row_n["provider_retry_count"] == 0
        assert row_n["queue_reenqueue_count"] == 0
        assert row_n["http_attempt_count"] == 1
