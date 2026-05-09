"""Paper Go/No-Go Gate evaluation service.

Assesses paper-trading health across three axes:

1. **Performance** — cumulative return, benchmark excess return, max drawdown.
2. **Stability** — win rate, minimum filled-order sample size.
3. **Operational Health** — snapshot sync freshness, sync failure count,
   active reconciliation blocking locks.

Each check produces a ``PaperGateCheck`` with a ``PASS`` / ``WARN`` / ``FAIL``
status.  The overall evaluation aggregates them:

- Any ``FAIL``    → ``NO_GO``
- No ``FAIL`` but any ``WARN`` → ``HOLD``
- All ``PASS``    → ``GO``
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Sequence
from uuid import UUID

from agent_trading.config.settings import AppSettings
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.benchmark_comparison import (
    BenchmarkPriceRepository,
    BenchmarkComparisonService,
)
from agent_trading.services.performance_summary import PerformanceSummaryService


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class GateStatus(str, Enum):
    """Individual check result status."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class OverallStatus(str, Enum):
    """Aggregate gate evaluation result."""

    GO = "GO"
    HOLD = "HOLD"
    NO_GO = "NO_GO"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class PaperGateCheck:
    """Result of a single gate criterion check."""

    code: str
    label: str
    status: GateStatus
    measured_value: Decimal | int | None
    threshold: Decimal | int | None
    message: str


@dataclass(slots=True, frozen=True)
class PaperGoNoGoEvaluation:
    """Complete Go/No-Go evaluation result."""

    account_id: UUID
    strategy_id: UUID | None
    overall_status: OverallStatus
    checks: Sequence[PaperGateCheck]
    generated_at: datetime
    summary_reason: str


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class PaperGateService:
    """Paper Go/No-Go Gate evaluation service.

    Composes existing performance / benchmark / snapshot-sync / reconciliation
    services to produce a single ``PaperGoNoGoEvaluation``.
    """

    def __init__(
        self,
        repos: RepositoryContainer,
        settings: AppSettings | None = None,
        benchmark_price_repo: BenchmarkPriceRepository | None = None,
    ) -> None:
        self._repos = repos
        self._settings = settings or AppSettings()
        self._perf_service = PerformanceSummaryService(repos)
        self._bench_service: BenchmarkComparisonService | None = (
            BenchmarkComparisonService(repos, benchmark_price_repo)
            if benchmark_price_repo is not None
            else None
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        account_id: UUID,
        start_date: date,
        end_date: date,
        strategy_id: UUID | None = None,
        benchmark_code: str | None = None,
    ) -> PaperGoNoGoEvaluation:
        """Execute a full Go/No-Go evaluation for *account_id* over the period.

        Parameters
        ----------
        account_id:
            Target account UUID.
        start_date:
            Evaluation period start (inclusive).
        end_date:
            Evaluation period end (inclusive).
        strategy_id:
            Optional strategy UUID to scope performance metrics.
        benchmark_code:
            Optional benchmark code (e.g. ``"KOSPI"``).  When provided,
            the ``MIN_EXCESS_RETURN`` check is included; otherwise skipped.

        Returns
        -------
        PaperGoNoGoEvaluation
            Complete evaluation with overall status and individual checks.
        """
        checks: list[PaperGateCheck] = []

        # -- 1. Performance metrics --
        metrics = await self._perf_service.get_performance_metrics(
            account_id, start_date, end_date, strategy_id,
        )

        checks.append(self._check_min_return(metrics.cumulative_return_pct))
        checks.append(self._check_max_drawdown(metrics.max_drawdown_pct))

        # -- Optional: benchmark comparison --
        if benchmark_code is not None and self._bench_service is not None:
            try:
                bench = await self._bench_service.get_benchmark_comparison(
                    account_id, start_date, end_date, benchmark_code, strategy_id,
                )
                checks.append(self._check_excess_return(bench.excess_return_pct))
            except Exception:
                checks.append(self._check_excess_return_unavailable())

        # -- 2. Stability metrics --
        checks.append(self._check_win_rate(metrics.win_rate))
        checks.append(self._check_filled_orders(metrics.total_filled_orders))

        # -- 3. Snapshot sync health --
        health = await self._repos.snapshot_sync_runs.get_sync_health_summary(
            stale_threshold_seconds=self._settings.kis_snapshot_stale_threshold_seconds,
        )

        checks.append(self._check_snapshot_freshness(health.is_stale))
        checks.append(self._check_sync_failures(health.consecutive_failures))

        # -- 4. Reconciliation blocking locks --
        active_locks = await self._repos.reconciliations.list_all_active_locks()
        # Filter locks for this account
        account_locks = [lk for lk in active_locks if lk.account_id == account_id]
        checks.append(self._check_blocking_locks(len(account_locks)))

        # -- 5. Overall status --
        overall = self._determine_overall(checks)
        summary = self._build_summary(overall, checks, metrics.total_filled_orders)

        return PaperGoNoGoEvaluation(
            account_id=account_id,
            strategy_id=strategy_id,
            overall_status=overall,
            checks=checks,
            generated_at=datetime.now(timezone.utc),
            summary_reason=summary,
        )

    # ------------------------------------------------------------------
    # Individual check methods
    # ------------------------------------------------------------------

    def _check_min_return(self, value: Decimal | None) -> PaperGateCheck:
        threshold = self._settings.paper_gate_min_return_pct
        code = "MIN_RETURN"
        label = "최소 수익률"

        if value is None:
            return PaperGateCheck(
                code=code, label=label,
                status=GateStatus.FAIL,
                measured_value=None, threshold=threshold,
                message="수익률 데이터를 계산할 수 없습니다",
            )
        if value < threshold:
            return PaperGateCheck(
                code=code, label=label,
                status=GateStatus.FAIL,
                measured_value=value, threshold=threshold,
                message=f"누적 수익률 {value}%이(가) 최소 기준 {threshold}%에 미달합니다",
            )
        return PaperGateCheck(
            code=code, label=label,
            status=GateStatus.PASS,
            measured_value=value, threshold=threshold,
            message=f"누적 수익률 {value}% — 기준 통과",
        )

    def _check_max_drawdown(self, value: Decimal | None) -> PaperGateCheck:
        threshold = self._settings.paper_gate_max_drawdown_pct
        code = "MAX_DRAWDOWN"
        label = "최대 손실 폭"

        if value is None:
            return PaperGateCheck(
                code=code, label=label,
                status=GateStatus.PASS,
                measured_value=None, threshold=threshold,
                message="손실 폭 데이터가 없습니다",
            )
        if value > threshold:
            return PaperGateCheck(
                code=code, label=label,
                status=GateStatus.FAIL,
                measured_value=value, threshold=threshold,
                message=f"최대 손실 폭 {value}%이(가) 허용 기준 {threshold}%을 초과했습니다",
            )
        return PaperGateCheck(
            code=code, label=label,
            status=GateStatus.PASS,
            measured_value=value, threshold=threshold,
            message=f"최대 손실 폭 {value}% — 기준 통과",
        )

    def _check_excess_return(self, value: Decimal | None) -> PaperGateCheck:
        threshold = self._settings.paper_gate_min_excess_return_pct
        code = "MIN_EXCESS_RETURN"
        label = "벤치마크 대비 초과수익"

        if value is None:
            return PaperGateCheck(
                code=code, label=label,
                status=GateStatus.FAIL,
                measured_value=None, threshold=threshold,
                message="초과수익 데이터를 계산할 수 없습니다",
            )
        if value < threshold:
            return PaperGateCheck(
                code=code, label=label,
                status=GateStatus.FAIL,
                measured_value=value, threshold=threshold,
                message=f"초과수익 {value}%p이(가) 최소 기준 {threshold}%p에 미달합니다",
            )
        return PaperGateCheck(
            code=code, label=label,
            status=GateStatus.PASS,
            measured_value=value, threshold=threshold,
            message=f"초과수익 {value}%p — 기준 통과",
        )

    def _check_excess_return_unavailable(self) -> PaperGateCheck:
        """Benchmark data unavailable → WARN."""
        return PaperGateCheck(
            code="MIN_EXCESS_RETURN",
            label="벤치마크 대비 초과수익",
            status=GateStatus.WARN,
            measured_value=None,
            threshold=self._settings.paper_gate_min_excess_return_pct,
            message="벤치마크 가격 데이터를 불러올 수 없습니다",
        )

    def _check_win_rate(self, value: Decimal | None) -> PaperGateCheck:
        threshold = self._settings.paper_gate_min_win_rate_pct
        code = "MIN_WIN_RATE"
        label = "최소 승률"

        if value is None:
            return PaperGateCheck(
                code=code, label=label,
                status=GateStatus.PASS,
                measured_value=None, threshold=threshold,
                message="승률 데이터가 없습니다",
            )
        if value < threshold:
            return PaperGateCheck(
                code=code, label=label,
                status=GateStatus.WARN,
                measured_value=value, threshold=threshold,
                message=f"승률 {value}%이(가) 최소 기준 {threshold}%에 미달합니다",
            )
        return PaperGateCheck(
            code=code, label=label,
            status=GateStatus.PASS,
            measured_value=value, threshold=threshold,
            message=f"승률 {value}% — 기준 통과",
        )

    def _check_filled_orders(self, value: int) -> PaperGateCheck:
        threshold = self._settings.paper_gate_min_filled_orders
        code = "MIN_FILLED_ORDERS"
        label = "최소 체결 건수"

        if value < threshold:
            return PaperGateCheck(
                code=code, label=label,
                status=GateStatus.FAIL,
                measured_value=value, threshold=threshold,
                message=f"체결 건수 {value}건이(가) 최소 기준 {threshold}건에 미달합니다",
            )
        return PaperGateCheck(
            code=code, label=label,
            status=GateStatus.PASS,
            measured_value=value, threshold=threshold,
            message=f"체결 건수 {value}건 — 기준 통과",
        )

    def _check_snapshot_freshness(self, is_stale: bool) -> PaperGateCheck:
        code = "SNAPSHOT_FRESHNESS"
        label = "스냅샷 신선도"

        if is_stale:
            return PaperGateCheck(
                code=code, label=label,
                status=GateStatus.FAIL,
                measured_value=1, threshold=0,
                message="스냅샷이 최신 상태가 아닙니다",
            )
        return PaperGateCheck(
            code=code, label=label,
            status=GateStatus.PASS,
            measured_value=0, threshold=0,
            message="스냅샷 신선도 정상",
        )

    def _check_sync_failures(self, consecutive_failures: int) -> PaperGateCheck:
        threshold = self._settings.paper_gate_max_consecutive_failures
        code = "SYNC_FAILURES"
        label = "Sync 연속 실패"

        if consecutive_failures > threshold:
            return PaperGateCheck(
                code=code, label=label,
                status=GateStatus.FAIL,
                measured_value=consecutive_failures, threshold=threshold,
                message=f"연속 실패 {consecutive_failures}회 — 허용 기준 {threshold}회 초과",
            )
        return PaperGateCheck(
            code=code, label=label,
            status=GateStatus.PASS,
            measured_value=consecutive_failures, threshold=threshold,
            message=f"연속 실패 {consecutive_failures}회 — 기준 이내",
        )

    def _check_blocking_locks(self, lock_count: int) -> PaperGateCheck:
        code = "BLOCKING_LOCKS"
        label = "차단 락 존재"

        if lock_count > 0:
            return PaperGateCheck(
                code=code, label=label,
                status=GateStatus.FAIL,
                measured_value=lock_count, threshold=0,
                message=f"활성 차단 락 {lock_count}개 존재 — 해결 후 재평가 필요",
            )
        return PaperGateCheck(
            code=code, label=label,
            status=GateStatus.PASS,
            measured_value=0, threshold=0,
            message="차단 락 없음",
        )

    # ------------------------------------------------------------------
    # Aggregation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _determine_overall(checks: Sequence[PaperGateCheck]) -> OverallStatus:
        """Determine the aggregate gate status from individual checks."""
        has_fail = any(c.status == GateStatus.FAIL for c in checks)
        has_warn = any(c.status == GateStatus.WARN for c in checks)

        if has_fail:
            return OverallStatus.NO_GO
        if has_warn:
            return OverallStatus.HOLD
        return OverallStatus.GO

    @staticmethod
    def _build_summary(
        overall: OverallStatus,
        checks: Sequence[PaperGateCheck],
        total_orders: int,
    ) -> str:
        """Produce a human-readable summary of the evaluation result."""
        passed = sum(1 for c in checks if c.status == GateStatus.PASS)
        warned = sum(1 for c in checks if c.status == GateStatus.WARN)
        failed = sum(1 for c in checks if c.status == GateStatus.FAIL)
        total = len(checks)

        if overall == OverallStatus.GO:
            return (
                f"전체 {total}개 항목 통과 — Paper 운용 양호, live 검토 가능"
            )
        elif overall == OverallStatus.HOLD:
            return (
                f"{passed}/{total} 통과, {warned}개 주의 — 조건부 합격, "
                f"주의 항목 검토 후 재평가 권장"
            )
        else:
            return (
                f"{passed}/{total} 통과, {failed}개 실패 — Paper 운용 기준 미달, "
                f"실패 항목 조치 후 재평가 필요"
            )
