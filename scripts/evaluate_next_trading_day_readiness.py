#!/usr/bin/env python3
"""다음 거래일 장중 운영 준비 상태 평가.

최근 작업에서 추가된 주문 truth / fill sync / snapshot refresh 신호를
한 번에 모아, 다음 거래일 장중 실운영 검증 전에 현재 런타임이
READY / WARN / BLOCKED 중 어느 상태인지 읽기 쉽게 출력한다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from agent_trading.domain.entities import MarketSessionEntity
from agent_trading.domain.enums import OrderStatus
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.contracts import FillSyncHealthSummary, SnapshotSyncHealthSummary
from agent_trading.repositories.filters import OrderQuery
from agent_trading.runtime.bootstrap import postgres_runtime
try:
    from scripts.operations_day_run_evaluation_store import (
        build_dsn_from_env,
        build_evaluation_entry,
        persist_operations_day_evaluation,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution path
    from operations_day_run_evaluation_store import (
        build_dsn_from_env,
        build_evaluation_entry,
        persist_operations_day_evaluation,
    )

_KST = timezone(timedelta(hours=9))
_BLOCKING_UNRESOLVED = (
    OrderStatus.PENDING_SUBMIT,
    OrderStatus.SUBMITTED,
    OrderStatus.ACKNOWLEDGED,
    OrderStatus.RECONCILE_REQUIRED,
)
_WARNING_UNRESOLVED = (OrderStatus.PARTIALLY_FILLED,)


@dataclass(slots=True, frozen=True)
class ReadinessCheck:
    code: str
    label: str
    status: str
    measured_value: str | None
    threshold: str | None
    message: str


@dataclass(slots=True, frozen=True)
class NextTradingDayReadinessEvaluation:
    target_date: date
    generated_at: datetime
    overall_status: str
    blocking_unresolved_count: int
    warning_unresolved_count: int
    truth_probe_pending_count: int
    is_trading_day: bool | None = None
    checks: Sequence[ReadinessCheck] = field(default_factory=tuple)

    def to_json(self) -> str:
        return json.dumps(
            {
                "target_date": self.target_date.isoformat(),
                "generated_at": self.generated_at.isoformat(),
                "overall_status": self.overall_status,
                "blocking_unresolved_count": self.blocking_unresolved_count,
                "warning_unresolved_count": self.warning_unresolved_count,
                "truth_probe_pending_count": self.truth_probe_pending_count,
                "is_trading_day": self.is_trading_day,
                "checks": [asdict(check) for check in self.checks],
            },
            ensure_ascii=False,
            indent=2,
        )

    def to_text(self) -> str:
        lines = [
            "=== Next Trading Day Readiness ===",
            f"date: {self.target_date.isoformat()} (Asia/Seoul)",
            f"overall: {self.overall_status}",
            f"is_trading_day: {self.is_trading_day}",
            f"blocking_unresolved: {self.blocking_unresolved_count}",
            f"warning_unresolved: {self.warning_unresolved_count}",
            f"truth_probe_pending: {self.truth_probe_pending_count}",
            "",
            "[checks]",
        ]
        for check in self.checks:
            lines.append(
                f"- {check.code} [{check.status}] {check.label}: "
                f"value={check.measured_value or 'N/A'} threshold={check.threshold or 'N/A'}"
            )
            lines.append(f"  {check.message}")
        return "\n".join(lines)


class NextTradingDayReadinessEvaluator:
    def __init__(self, repos: RepositoryContainer) -> None:
        self._repos = repos

    async def evaluate(
        self,
        *,
        target_date: date,
        snapshot_stale_threshold_seconds: int = 1800,
        fill_stale_threshold_seconds: int = 1800,
    ) -> NextTradingDayReadinessEvaluation:
        unresolved = await self._repos.orders.list(
            OrderQuery(
                statuses=[*_BLOCKING_UNRESOLVED, *_WARNING_UNRESOLVED],
                limit=5000,
            )
        )
        blocking_unresolved = [
            order for order in unresolved if order.status in _BLOCKING_UNRESOLVED
        ]
        warning_unresolved = [
            order for order in unresolved if order.status in _WARNING_UNRESOLVED
        ]
        truth_probe_pending = [
            order
            for order in unresolved
            if order.status_reason_code == "truth_probe_fill_snapshot_incomplete"
        ]

        snapshot_health = await self._repos.snapshot_sync_runs.get_sync_health_summary(
            stale_threshold_seconds=snapshot_stale_threshold_seconds,
        )
        fill_health = await self._repos.fill_sync_runs.get_sync_health_summary(
            stale_threshold_seconds=fill_stale_threshold_seconds,
        )
        session = await self._repos.market_session_repo.get_by_run_date(target_date)
        is_trading_day = session.is_trading_day if session is not None else None

        checks = [
            self._build_market_session_check(session),
            self._build_unresolved_check(blocking_unresolved),
            self._build_partial_check(warning_unresolved),
            self._build_truth_probe_pending_check(truth_probe_pending),
            self._build_snapshot_health_check(snapshot_health, is_trading_day=is_trading_day),
            self._build_fill_sync_health_check(fill_health, is_trading_day=is_trading_day),
            self._build_fill_sync_retry_check(fill_health, is_trading_day=is_trading_day),
        ]
        overall = self._determine_overall(checks)
        return NextTradingDayReadinessEvaluation(
            target_date=target_date,
            generated_at=datetime.now(timezone.utc),
            overall_status=overall,
            blocking_unresolved_count=len(blocking_unresolved),
            warning_unresolved_count=len(warning_unresolved),
            truth_probe_pending_count=len(truth_probe_pending),
            is_trading_day=is_trading_day,
            checks=checks,
        )

    def _build_market_session_check(
        self,
        session: MarketSessionEntity | None,
    ) -> ReadinessCheck:
        if session is None:
            return ReadinessCheck(
                code="NTD_MARKET_SESSION",
                label="market session availability",
                status="WARN",
                measured_value="missing",
                threshold="stored",
                message="target_date의 market_sessions row가 없어 거래일 여부를 저장 기준으로 확인하지 못했습니다.",
            )
        if session.is_trading_day:
            return ReadinessCheck(
                code="NTD_MARKET_SESSION",
                label="market session availability",
                status="READY",
                measured_value="trading_day",
                threshold="trading_day",
                message="target_date가 거래일로 저장되어 있습니다.",
            )
        return ReadinessCheck(
            code="NTD_MARKET_SESSION",
            label="market session availability",
            status="READY",
            measured_value="non_trading_day",
            threshold="trading_day",
            message="target_date가 비거래일로 저장되어 있어 stale sync 신호를 차단 사유로 보지 않습니다.",
        )

    def _build_unresolved_check(
        self,
        blocking_unresolved: Sequence[object],
    ) -> ReadinessCheck:
        if blocking_unresolved:
            return ReadinessCheck(
                code="NTD_UNRESOLVED_BLOCKING",
                label="미해결 주문(차단성)",
                status="BLOCKED",
                measured_value=str(len(blocking_unresolved)),
                threshold="0",
                message=(
                    "submitted/acknowledged/reconcile_required/pending_submit 주문이 "
                    f"{len(blocking_unresolved)}건 남아 있습니다."
                ),
            )
        return ReadinessCheck(
            code="NTD_UNRESOLVED_BLOCKING",
            label="미해결 주문(차단성)",
            status="READY",
            measured_value="0",
            threshold="0",
            message="차단성 미해결 주문이 없습니다.",
        )

    def _build_partial_check(
        self,
        warning_unresolved: Sequence[object],
    ) -> ReadinessCheck:
        if warning_unresolved:
            return ReadinessCheck(
                code="NTD_PARTIALLY_FILLED_OPEN",
                label="부분체결 잔존",
                status="WARN",
                measured_value=str(len(warning_unresolved)),
                threshold="0",
                message=(
                    f"partially_filled 주문이 {len(warning_unresolved)}건 남아 있어 "
                    "장중 추가 수렴 여부를 확인해야 합니다."
                ),
            )
        return ReadinessCheck(
            code="NTD_PARTIALLY_FILLED_OPEN",
            label="부분체결 잔존",
            status="READY",
            measured_value="0",
            threshold="0",
            message="부분체결 잔존 주문이 없습니다.",
        )

    def _build_truth_probe_pending_check(
        self,
        truth_probe_pending: Sequence[object],
    ) -> ReadinessCheck:
        if truth_probe_pending:
            return ReadinessCheck(
                code="NTD_TRUTH_PROBE_PENDING",
                label="fill snapshot pending convergence",
                status="WARN",
                measured_value=str(len(truth_probe_pending)),
                threshold="0",
                message=(
                    "truth_probe_fill_snapshot_incomplete 주문이 "
                    f"{len(truth_probe_pending)}건 있습니다."
                ),
            )
        return ReadinessCheck(
            code="NTD_TRUTH_PROBE_PENDING",
            label="fill snapshot pending convergence",
            status="READY",
            measured_value="0",
            threshold="0",
            message="fill snapshot pending convergence 주문이 없습니다.",
        )

    def _build_snapshot_health_check(
        self,
        snapshot_health: SnapshotSyncHealthSummary,
        *,
        is_trading_day: bool | None,
    ) -> ReadinessCheck:
        if is_trading_day is False:
            return ReadinessCheck(
                code="NTD_SNAPSHOT_SYNC",
                label="snapshot sync freshness",
                status="READY",
                measured_value=snapshot_health.last_status or "no_history",
                threshold="fresh",
                message="비거래일이므로 snapshot sync stale 여부를 차단 사유로 보지 않습니다.",
            )
        if snapshot_health.is_stale:
            return ReadinessCheck(
                code="NTD_SNAPSHOT_SYNC",
                label="snapshot sync freshness",
                status="BLOCKED",
                measured_value=snapshot_health.last_status or "no_history",
                threshold="fresh",
                message="snapshot sync가 stale 상태입니다.",
            )
        return ReadinessCheck(
            code="NTD_SNAPSHOT_SYNC",
            label="snapshot sync freshness",
            status="READY",
            measured_value=snapshot_health.last_status or "completed",
            threshold="fresh",
            message="snapshot sync freshness가 정상입니다.",
        )

    def _build_fill_sync_health_check(
        self,
        fill_health: FillSyncHealthSummary,
        *,
        is_trading_day: bool | None,
    ) -> ReadinessCheck:
        if is_trading_day is False:
            return ReadinessCheck(
                code="NTD_FILL_SYNC",
                label="fill sync freshness",
                status="READY",
                measured_value=fill_health.last_status or "no_history",
                threshold="completed/fresh",
                message="비거래일이므로 fill sync stale 여부를 차단 사유로 보지 않습니다.",
            )
        if fill_health.is_stale or fill_health.consecutive_failures > 0 or fill_health.last_status == "failed":
            return ReadinessCheck(
                code="NTD_FILL_SYNC",
                label="fill sync freshness",
                status="BLOCKED",
                measured_value=fill_health.last_status or "no_history",
                threshold="completed/fresh",
                message=(
                    "fill sync가 stale 이거나 최근 실패가 남아 있습니다. "
                    f"(consecutive_failures={fill_health.consecutive_failures})"
                ),
            )
        return ReadinessCheck(
            code="NTD_FILL_SYNC",
            label="fill sync freshness",
            status="READY",
            measured_value=fill_health.last_status or "completed",
            threshold="completed/fresh",
            message="fill sync freshness가 정상입니다.",
        )

    def _build_fill_sync_retry_check(
        self,
        fill_health: FillSyncHealthSummary,
        *,
        is_trading_day: bool | None,
    ) -> ReadinessCheck:
        if is_trading_day is False:
            return ReadinessCheck(
                code="NTD_FILL_SYNC_RETRY",
                label="최근 fill sync retry",
                status="READY",
                measured_value=str(fill_health.total_retries),
                threshold="0",
                message="비거래일이므로 fill sync retry는 참고 정보로만 취급합니다.",
            )
        if fill_health.total_retries > 0:
            return ReadinessCheck(
                code="NTD_FILL_SYNC_RETRY",
                label="최근 fill sync retry",
                status="WARN",
                measured_value=str(fill_health.total_retries),
                threshold="0",
                message=(
                    "최근 fill sync가 retry로 복구됐습니다. "
                    f"(accounts={fill_health.retried_accounts}, days={fill_health.retried_days})"
                ),
            )
        return ReadinessCheck(
            code="NTD_FILL_SYNC_RETRY",
            label="최근 fill sync retry",
            status="READY",
            measured_value="0",
            threshold="0",
            message="최근 fill sync retry가 없습니다.",
        )

    def _determine_overall(self, checks: Sequence[ReadinessCheck]) -> str:
        statuses = {check.status for check in checks}
        if "BLOCKED" in statuses:
            return "BLOCKED"
        if "WARN" in statuses:
            return "WARN"
        return "READY"


def _build_persisted_summary(
    evaluation: NextTradingDayReadinessEvaluation,
) -> dict[str, object]:
    return build_evaluation_entry(
        overall_status=evaluation.overall_status,
        generated_at=evaluation.generated_at,
        checks=evaluation.checks,
        extra={
            "target_date": evaluation.target_date.isoformat(),
            "is_trading_day": evaluation.is_trading_day,
            "blocking_unresolved_count": evaluation.blocking_unresolved_count,
            "warning_unresolved_count": evaluation.warning_unresolved_count,
            "truth_probe_pending_count": evaluation.truth_probe_pending_count,
        },
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate next trading day operational readiness.",
    )
    parser.add_argument("--date", type=str, default=None, help="KST target date (YYYY-MM-DD).")
    parser.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output format.",
    )
    parser.add_argument(
        "--persist",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Persist compact evaluation summary into operations_day_runs.summary_json.",
    )
    return parser.parse_args(argv)


async def _run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    target_date = (
        date.fromisoformat(args.date)
        if args.date
        else datetime.now(_KST).date()
    )
    async with postgres_runtime(run_migrations=False) as runtime:
        repos: RepositoryContainer = runtime["repositories"]
        evaluator = NextTradingDayReadinessEvaluator(repos)
        evaluation = await evaluator.evaluate(target_date=target_date)
    if args.persist:
        await persist_operations_day_evaluation(
            dsn=build_dsn_from_env(),
            run_date=target_date,
            key="next_trading_day_readiness",
            payload=_build_persisted_summary(evaluation),
            is_trading_day=evaluation.is_trading_day,
        )
    if args.output == "json":
        print(evaluation.to_json())
    else:
        print(evaluation.to_text())
    return 0 if evaluation.overall_status != "BLOCKED" else 2


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(argv))


if __name__ == "__main__":
    raise SystemExit(main())
