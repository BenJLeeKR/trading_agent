#!/usr/bin/env python3
"""현재 거래일 장중 운영 상태를 평가한다.

다음 항목을 한 번에 묶어 READY / WARN / BLOCKED 로 판정한다.

- market_sessions / operations_day_runs 현재 상태
- 최근 decision loop 결과
- 오늘 BUY lane 차단/주문 생성 상태
- 미해결 주문 / truth probe pending
- snapshot sync / fill sync freshness
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from agent_trading.api.routes.orders import get_buy_block_summary, get_truth_probe_pending_summary
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
_INTRADAY_CUTOFF = datetime.strptime("15:30:30", "%H:%M:%S").time()
_BLOCKING_UNRESOLVED = (
    OrderStatus.PENDING_SUBMIT,
    OrderStatus.SUBMITTED,
    OrderStatus.ACKNOWLEDGED,
    OrderStatus.RECONCILE_REQUIRED,
)
_WARNING_UNRESOLVED = (OrderStatus.PARTIALLY_FILLED,)


@dataclass(slots=True, frozen=True)
class IntradayCheck:
    code: str
    label: str
    status: str
    measured_value: str | None
    threshold: str | None
    message: str


@dataclass(slots=True, frozen=True)
class IntradayValidationInputs:
    target_date: date
    is_trading_day: bool | None
    market_reason_code: str | None
    operations_day_healthy: bool
    operations_day_stale_seconds: int | None
    operations_day_status: str | None
    operations_day_summary_json: dict[str, object]
    blocking_unresolved_count: int
    warning_unresolved_count: int
    truth_probe_pending_count: int
    snapshot_health: SnapshotSyncHealthSummary
    fill_health: FillSyncHealthSummary
    buy_block_summary: object


@dataclass(slots=True, frozen=True)
class IntradayOperationalEvaluation:
    target_date: date
    generated_at: datetime
    overall_status: str
    is_trading_day: bool | None
    operations_day_status: str | None
    buy_orders_created_count: int
    total_buy_decisions: int
    checks: Sequence[IntradayCheck] = field(default_factory=tuple)

    def to_json(self) -> str:
        return json.dumps(
            {
                "target_date": self.target_date.isoformat(),
                "generated_at": self.generated_at.isoformat(),
                "overall_status": self.overall_status,
                "is_trading_day": self.is_trading_day,
                "operations_day_status": self.operations_day_status,
                "buy_orders_created_count": self.buy_orders_created_count,
                "total_buy_decisions": self.total_buy_decisions,
                "checks": [asdict(check) for check in self.checks],
            },
            ensure_ascii=False,
            indent=2,
        )

    def to_text(self) -> str:
        lines = [
            "=== Intraday Operational Validation ===",
            f"date: {self.target_date.isoformat()} (Asia/Seoul)",
            f"overall: {self.overall_status}",
            f"is_trading_day: {self.is_trading_day}",
            f"operations_day_status: {self.operations_day_status}",
            f"buy_orders_created: {self.buy_orders_created_count}/{self.total_buy_decisions}",
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


class IntradayOperationalEvaluator:
    def evaluate(self, inputs: IntradayValidationInputs) -> IntradayOperationalEvaluation:
        buy_summary = inputs.buy_block_summary
        checks = [
            self._build_market_day_check(inputs),
            self._build_operations_day_check(inputs),
            self._build_decision_loop_check(inputs),
            self._build_buy_lane_check(inputs),
            self._build_buy_lane_bias_check(inputs),
            self._build_unresolved_check(inputs),
            self._build_truth_probe_pending_check(inputs),
            self._build_snapshot_health_check(inputs),
            self._build_fill_sync_health_check(inputs),
            self._build_fill_refresh_convergence_check(inputs),
        ]
        overall = self._determine_overall(checks)
        return IntradayOperationalEvaluation(
            target_date=inputs.target_date,
            generated_at=datetime.now(timezone.utc),
            overall_status=overall,
            is_trading_day=inputs.is_trading_day,
            operations_day_status=inputs.operations_day_status,
            buy_orders_created_count=int(getattr(buy_summary, "buy_orders_created_count", 0)),
            total_buy_decisions=int(getattr(buy_summary, "total_buy_decisions", 0)),
            checks=checks,
        )

    def _build_market_day_check(self, inputs: IntradayValidationInputs) -> IntradayCheck:
        if inputs.is_trading_day is None:
            return IntradayCheck(
                code="INTRA_MARKET_DAY",
                label="거래일 판정",
                status="WARN",
                measured_value="missing",
                threshold="stored",
                message="market_sessions 에 현재 날짜 row가 없어 거래일 여부를 저장 기준으로 확인하지 못했습니다.",
            )
        if inputs.is_trading_day:
            return IntradayCheck(
                code="INTRA_MARKET_DAY",
                label="거래일 판정",
                status="READY",
                measured_value="trading_day",
                threshold="trading_day",
                message=f"현재 날짜가 거래일로 저장되어 있습니다 (reason_code={inputs.market_reason_code}).",
            )
        return IntradayCheck(
            code="INTRA_MARKET_DAY",
            label="거래일 판정",
            status="READY",
            measured_value="non_trading_day",
            threshold="trading_day",
            message="현재 날짜가 비거래일로 저장되어 있어 장중 submit/refresh 검증은 참고 정보로만 봅니다.",
        )

    def _build_operations_day_check(self, inputs: IntradayValidationInputs) -> IntradayCheck:
        expected_phase = self._expected_scheduler_status(
            now_kst=datetime.now(_KST),
            is_trading_day=inputs.is_trading_day,
        )
        if not inputs.operations_day_status:
            return IntradayCheck(
                code="INTRA_OPERATIONS_DAY",
                label="operations_day_runs 상태",
                status="BLOCKED" if inputs.is_trading_day else "WARN",
                measured_value="missing",
                threshold="fresh row",
                message="operations_day_runs 최신 row를 찾지 못했습니다.",
            )
        if not inputs.operations_day_healthy:
            return IntradayCheck(
                code="INTRA_OPERATIONS_DAY",
                label="operations_day_runs 상태",
                status="BLOCKED" if inputs.is_trading_day else "WARN",
                measured_value=str(inputs.operations_day_stale_seconds),
                threshold="120s",
                message=(
                    f"operations_day_runs heartbeat가 stale 입니다 "
                    f"(status={inputs.operations_day_status})."
                ),
            )
        if (
            inputs.is_trading_day
            and expected_phase is not None
            and inputs.operations_day_status != expected_phase
        ):
            return IntradayCheck(
                code="INTRA_OPERATIONS_DAY",
                label="operations_day_runs 상태",
                status="WARN",
                measured_value=inputs.operations_day_status,
                threshold=expected_phase,
                message=(
                    "현재 KST 시간대와 scheduler_status가 어긋납니다. "
                    "재시작 직후 warm-up 중이거나 phase 전이가 지연됐을 수 있습니다."
                ),
            )
        return IntradayCheck(
            code="INTRA_OPERATIONS_DAY",
            label="operations_day_runs 상태",
            status="READY",
            measured_value=inputs.operations_day_status,
            threshold="fresh row",
            message="operations_day_runs heartbeat가 정상입니다.",
        )

    def _build_decision_loop_check(self, inputs: IntradayValidationInputs) -> IntradayCheck:
        decision_loop = inputs.operations_day_summary_json.get("decision_loop")
        if not isinstance(decision_loop, dict):
            return IntradayCheck(
                code="INTRA_DECISION_LOOP",
                label="최근 decision loop 결과",
                status="WARN",
                measured_value="missing",
                threshold="decision_submit_gate ok",
                message="operations_day_runs.summary_json 에 decision loop 결과가 없습니다.",
            )

        name = str(decision_loop.get("name") or "")
        ok = bool(decision_loop.get("ok"))
        timed_out = bool(decision_loop.get("timed_out"))
        duration_seconds = decision_loop.get("duration_seconds")
        measured = f"{name or 'unknown'} ok={ok} timeout={timed_out}"
        if timed_out or not ok:
            return IntradayCheck(
                code="INTRA_DECISION_LOOP",
                label="최근 decision loop 결과",
                status="BLOCKED",
                measured_value=measured,
                threshold="decision_submit_gate ok",
                message=f"최근 decision loop가 실패했습니다 (duration={duration_seconds}).",
            )
        if name == "decision_dry_run":
            return IntradayCheck(
                code="INTRA_DECISION_LOOP",
                label="최근 decision loop 결과",
                status="WARN",
                measured_value=measured,
                threshold="decision_submit_gate",
                message="최근 decision loop가 dry-run 경로였습니다. submit lane 정책/예산을 함께 확인해야 합니다.",
            )
        return IntradayCheck(
            code="INTRA_DECISION_LOOP",
            label="최근 decision loop 결과",
            status="READY",
            measured_value=measured,
            threshold="decision_submit_gate ok",
            message=f"최근 decision_submit_gate가 정상 종료했습니다 (duration={duration_seconds}).",
        )

    def _build_buy_lane_check(self, inputs: IntradayValidationInputs) -> IntradayCheck:
        buy_summary = inputs.buy_block_summary
        total_buy_decisions = int(getattr(buy_summary, "total_buy_decisions", 0))
        buy_orders_created_count = int(getattr(buy_summary, "buy_orders_created_count", 0))
        submit_budget_consumed_count = int(getattr(buy_summary, "submit_budget_consumed_count", 0))
        general_submit_disabled_count = int(getattr(buy_summary, "general_submit_disabled_count", 0))
        sizing_rejected_count = int(getattr(buy_summary, "sizing_rejected_count", 0))
        missing_reference_price_count = int(getattr(buy_summary, "missing_reference_price_count", 0))

        measured = (
            f"buy_orders={buy_orders_created_count}/{total_buy_decisions} "
            f"gate={general_submit_disabled_count} budget={submit_budget_consumed_count}"
        )
        if inputs.is_trading_day is False:
            return IntradayCheck(
                code="INTRA_BUY_LANE",
                label="BUY submit lane",
                status="READY",
                measured_value=measured,
                threshold="intraday only",
                message="비거래일이므로 BUY submit lane 지표는 참고 정보로만 봅니다.",
            )
        if total_buy_decisions == 0:
            return IntradayCheck(
                code="INTRA_BUY_LANE",
                label="BUY submit lane",
                status="WARN",
                measured_value=measured,
                threshold="approve BUY > 0",
                message="오늘 BUY approve decision 자체가 아직 없습니다.",
            )
        if buy_orders_created_count > 0:
            return IntradayCheck(
                code="INTRA_BUY_LANE",
                label="BUY submit lane",
                status="READY",
                measured_value=measured,
                threshold="buy_orders > 0",
                message="오늘 BUY decision 중 실제 order_request로 이어진 건이 있습니다.",
            )
        if submit_budget_consumed_count > 0 or general_submit_disabled_count > 0:
            return IntradayCheck(
                code="INTRA_BUY_LANE",
                label="BUY submit lane",
                status="BLOCKED",
                measured_value=measured,
                threshold="buy_orders > 0",
                message=(
                    "BUY approve decision은 있었지만 scheduler gate/budget 사유로 "
                    "주문이 생성되지 않았습니다."
                ),
            )
        if sizing_rejected_count > 0 or missing_reference_price_count > 0:
            return IntradayCheck(
                code="INTRA_BUY_LANE",
                label="BUY submit lane",
                status="WARN",
                measured_value=measured,
                threshold="buy_orders > 0",
                message=(
                    "BUY decision은 있었지만 sizing 또는 reference price 문제로 "
                    "주문이 생성되지 않았습니다."
                ),
            )
        return IntradayCheck(
            code="INTRA_BUY_LANE",
            label="BUY submit lane",
            status="WARN",
            measured_value=measured,
            threshold="buy_orders > 0",
            message="BUY submit lane 상태를 확정하기에 정보가 부족합니다.",
        )

    def _build_unresolved_check(self, inputs: IntradayValidationInputs) -> IntradayCheck:
        if inputs.blocking_unresolved_count > 0:
            return IntradayCheck(
                code="INTRA_UNRESOLVED",
                label="미해결 주문(차단성)",
                status="BLOCKED",
                measured_value=str(inputs.blocking_unresolved_count),
                threshold="0",
                message="submitted/acknowledged/reconcile_required/pending_submit 주문이 남아 있습니다.",
            )
        if inputs.warning_unresolved_count > 0:
            return IntradayCheck(
                code="INTRA_UNRESOLVED",
                label="미해결 주문(차단성)",
                status="WARN",
                measured_value=str(inputs.warning_unresolved_count),
                threshold="0",
                message="partially_filled 주문이 남아 있습니다.",
            )
        return IntradayCheck(
            code="INTRA_UNRESOLVED",
            label="미해결 주문(차단성)",
            status="READY",
            measured_value="0",
            threshold="0",
            message="차단성 미해결 주문이 없습니다.",
        )

    def _build_buy_lane_bias_check(self, inputs: IntradayValidationInputs) -> IntradayCheck:
        buy_summary = inputs.buy_block_summary
        total_buy_decisions = int(getattr(buy_summary, "total_buy_decisions", 0))
        buy_orders_created_count = int(getattr(buy_summary, "buy_orders_created_count", 0))
        submit_budget_consumed_count = int(getattr(buy_summary, "submit_budget_consumed_count", 0))
        general_submit_disabled_count = int(getattr(buy_summary, "general_submit_disabled_count", 0))
        blocked_total = submit_budget_consumed_count + general_submit_disabled_count

        measured = (
            f"buy_orders={buy_orders_created_count}/{total_buy_decisions} "
            f"blocked={blocked_total} (gate={general_submit_disabled_count}, budget={submit_budget_consumed_count})"
        )
        if inputs.is_trading_day is False:
            return IntradayCheck(
                code="INTRA_BUY_LANE_BIAS",
                label="BUY lane 차단 편향",
                status="READY",
                measured_value=measured,
                threshold="intraday only",
                message="비거래일이므로 BUY lane 차단 편향은 참고 정보로만 봅니다.",
            )
        if buy_orders_created_count <= 0:
            return IntradayCheck(
                code="INTRA_BUY_LANE_BIAS",
                label="BUY lane 차단 편향",
                status="READY",
                measured_value=measured,
                threshold="buy_orders > 0",
                message="실제 BUY 주문 생성이 없으므로 차단 편향 비율은 아직 평가하지 않습니다.",
            )

        # 일반 BUY lane이 실제로 열렸는데도 차단 수가 실주문 대비 과도하게 많으면 편향 경고.
        if blocked_total >= max(3, buy_orders_created_count * 3):
            return IntradayCheck(
                code="INTRA_BUY_LANE_BIAS",
                label="BUY lane 차단 편향",
                status="WARN",
                measured_value=measured,
                threshold="blocked < buy_orders * 3",
                message=(
                    "BUY 주문은 생성됐지만 같은 날짜에 scheduler gate/budget 차단 수가 과도하게 높습니다. "
                    "submit slot 소비/재할당 편향이 남아 있는지 재확인해야 합니다."
                ),
            )
        return IntradayCheck(
            code="INTRA_BUY_LANE_BIAS",
            label="BUY lane 차단 편향",
            status="READY",
            measured_value=measured,
            threshold="blocked < buy_orders * 3",
            message="BUY 주문 생성 대비 scheduler gate/budget 차단 수가 과도하지 않습니다.",
        )

    def _build_truth_probe_pending_check(self, inputs: IntradayValidationInputs) -> IntradayCheck:
        if inputs.truth_probe_pending_count > 0:
            return IntradayCheck(
                code="INTRA_TRUTH_PENDING",
                label="truth probe pending",
                status="WARN",
                measured_value=str(inputs.truth_probe_pending_count),
                threshold="0",
                message="다음 fill sync를 기다리는 truth probe pending 주문이 있습니다.",
            )
        return IntradayCheck(
            code="INTRA_TRUTH_PENDING",
            label="truth probe pending",
            status="READY",
            measured_value="0",
            threshold="0",
            message="truth probe pending 주문이 없습니다.",
        )

    def _build_snapshot_health_check(self, inputs: IntradayValidationInputs) -> IntradayCheck:
        health = inputs.snapshot_health
        if inputs.is_trading_day and (health.is_stale or health.last_status == "failed"):
            return IntradayCheck(
                code="INTRA_SNAPSHOT_HEALTH",
                label="snapshot sync freshness",
                status="BLOCKED",
                measured_value=health.last_status,
                threshold=f"not stale ({health.stale_threshold_seconds}s)",
                message="snapshot sync가 stale 이거나 최근 실패 상태입니다.",
            )
        return IntradayCheck(
            code="INTRA_SNAPSHOT_HEALTH",
            label="snapshot sync freshness",
            status="READY",
            measured_value=health.last_status,
            threshold=f"not stale ({health.stale_threshold_seconds}s)",
            message="snapshot sync freshness가 정상입니다.",
        )

    def _build_fill_sync_health_check(self, inputs: IntradayValidationInputs) -> IntradayCheck:
        health = inputs.fill_health
        if inputs.is_trading_day and (health.is_stale or health.last_status == "failed"):
            return IntradayCheck(
                code="INTRA_FILL_SYNC_HEALTH",
                label="fill sync freshness",
                status="WARN",
                measured_value=health.last_status,
                threshold=f"not stale ({health.stale_threshold_seconds}s)",
                message="fill sync가 stale 이거나 최근 실패 상태입니다.",
            )
        if inputs.is_trading_day and health.total_retries > 0:
            return IntradayCheck(
                code="INTRA_FILL_SYNC_HEALTH",
                label="fill sync freshness",
                status="WARN",
                measured_value=f"{health.last_status}, retries={health.total_retries}",
                threshold=f"no retry ({health.stale_threshold_seconds}s)",
                message="최근 fill sync가 retry로 복구됐습니다.",
            )
        return IntradayCheck(
            code="INTRA_FILL_SYNC_HEALTH",
            label="fill sync freshness",
            status="READY",
            measured_value=health.last_status,
            threshold=f"not stale ({health.stale_threshold_seconds}s)",
            message="fill sync freshness가 정상입니다.",
        )

    def _build_fill_refresh_convergence_check(self, inputs: IntradayValidationInputs) -> IntradayCheck:
        command_health = inputs.operations_day_summary_json.get("command_health")
        if not isinstance(command_health, dict):
            return IntradayCheck(
                code="INTRA_FILL_REFRESH",
                label="fill-triggered refresh 수렴",
                status="WARN",
                measured_value="missing",
                threshold="refresh metrics present",
                message="operations_day_runs.summary_json 에 post_submit_sync command_health가 없습니다.",
            )
        post_submit = command_health.get("post_submit_sync")
        if not isinstance(post_submit, dict):
            return IntradayCheck(
                code="INTRA_FILL_REFRESH",
                label="fill-triggered refresh 수렴",
                status="WARN",
                measured_value="missing",
                threshold="refresh metrics present",
                message="post_submit_sync command_health를 찾지 못했습니다.",
            )
        last_metrics = post_submit.get("last_metrics")
        if not isinstance(last_metrics, dict):
            return IntradayCheck(
                code="INTRA_FILL_REFRESH",
                label="fill-triggered refresh 수렴",
                status="WARN",
                measured_value="missing",
                threshold="refresh metrics present",
                message="post_submit_sync 요약에서 refresh metrics를 읽지 못했습니다.",
            )
        refresh = last_metrics.get("refresh")
        if not isinstance(refresh, dict):
            return IntradayCheck(
                code="INTRA_FILL_REFRESH",
                label="fill-triggered refresh 수렴",
                status="READY",
                measured_value="no_refresh",
                threshold="refresh on fill",
                message="최근 post-submit sync cycle에서 fill-triggered refresh가 발생하지 않았습니다.",
            )

        scheduled = int(refresh.get("scheduled", 0) or 0)
        completed = int(refresh.get("completed", 0) or 0)
        degraded = int(refresh.get("degraded", 0) or 0)
        failed = int(refresh.get("failed", 0) or 0)
        avg_elapsed_ms = int(refresh.get("avg_elapsed_ms", 0) or 0)
        measured = (
            f"scheduled={scheduled}, completed={completed}, degraded={degraded}, "
            f"failed={failed}, avg_ms={avg_elapsed_ms}"
        )
        if failed > 0:
            return IntradayCheck(
                code="INTRA_FILL_REFRESH",
                label="fill-triggered refresh 수렴",
                status="WARN",
                measured_value=measured,
                threshold="failed=0",
                message="최근 fill-triggered refresh에 실패 건이 있습니다.",
            )
        if degraded > 0:
            return IntradayCheck(
                code="INTRA_FILL_REFRESH",
                label="fill-triggered refresh 수렴",
                status="WARN",
                measured_value=measured,
                threshold="degraded=0",
                message="최근 fill-triggered refresh가 일부만 수렴(degraded)했습니다.",
            )
        if scheduled > 0 and avg_elapsed_ms > 5000:
            return IntradayCheck(
                code="INTRA_FILL_REFRESH",
                label="fill-triggered refresh 수렴",
                status="WARN",
                measured_value=measured,
                threshold="avg_elapsed_ms<=5000",
                message="최근 fill-triggered refresh 평균 소요시간이 길었습니다.",
            )
        return IntradayCheck(
            code="INTRA_FILL_REFRESH",
            label="fill-triggered refresh 수렴",
            status="READY",
            measured_value=measured,
            threshold="failed=0,degraded=0",
            message="최근 fill-triggered refresh 수렴 속도와 실패율이 정상 범위입니다.",
        )

    def _determine_overall(self, checks: Sequence[IntradayCheck]) -> str:
        if any(check.status == "BLOCKED" for check in checks):
            return "BLOCKED"
        if any(check.status == "WARN" for check in checks):
            return "WARN"
        return "READY"

    @staticmethod
    def _expected_scheduler_status(*, now_kst: datetime, is_trading_day: bool | None) -> str | None:
        if is_trading_day is not True:
            return None
        current = now_kst.timetz().replace(tzinfo=None)
        if current < datetime.strptime("09:00", "%H:%M").time():
            return "pre_market"
        if current < _INTRADAY_CUTOFF:
            return "intraday"
        return "after_hours"


def _build_persisted_summary(
    evaluation: IntradayOperationalEvaluation,
) -> dict[str, object]:
    return build_evaluation_entry(
        overall_status=evaluation.overall_status,
        generated_at=evaluation.generated_at,
        checks=evaluation.checks,
        extra={
            "target_date": evaluation.target_date.isoformat(),
            "is_trading_day": evaluation.is_trading_day,
            "operations_day_status": evaluation.operations_day_status,
            "buy_orders_created_count": evaluation.buy_orders_created_count,
            "total_buy_decisions": evaluation.total_buy_decisions,
        },
    )


async def _fetch_operations_day_status(run_date: date) -> tuple[str | None, bool, int | None, dict[str, object]]:
    from agent_trading.db.transaction import transaction as _db_transaction

    async with _db_transaction() as tx:
        row = await tx.connection.fetchrow(
            """
            SELECT scheduler_status, last_heartbeat_at, updated_at, created_at, summary_json
            FROM trading.operations_day_runs
            WHERE run_date = $1
            ORDER BY COALESCE(last_heartbeat_at, updated_at, created_at) DESC
            LIMIT 1
            """,
            run_date,
        )
    if row is None:
        return None, False, None, {}
    now = datetime.now(timezone.utc)
    freshness_ts = row["last_heartbeat_at"] or row["updated_at"] or row["created_at"]
    stale_seconds = int((now - freshness_ts).total_seconds()) if freshness_ts else None
    healthy = freshness_ts is not None and stale_seconds is not None and stale_seconds < 120
    raw_summary = row["summary_json"]
    if isinstance(raw_summary, str):
        try:
            summary_json = json.loads(raw_summary)
        except json.JSONDecodeError:
            summary_json = {}
    elif isinstance(raw_summary, dict):
        summary_json = raw_summary
    else:
        summary_json = {}
    return str(row["scheduler_status"]) if row["scheduler_status"] is not None else None, healthy, stale_seconds, summary_json


async def _fetch_inputs(
    *,
    target_date: date,
    snapshot_stale_threshold_seconds: int,
    fill_stale_threshold_seconds: int,
) -> IntradayValidationInputs:
    async with postgres_runtime(run_migrations=False) as runtime:
        repos: RepositoryContainer = runtime["repositories"]
        unresolved = await repos.orders.list(
            OrderQuery(
                statuses=[*_BLOCKING_UNRESOLVED, *_WARNING_UNRESOLVED],
                limit=5000,
            )
        )
        blocking_unresolved_count = sum(1 for order in unresolved if order.status in _BLOCKING_UNRESOLVED)
        warning_unresolved_count = sum(1 for order in unresolved if order.status in _WARNING_UNRESOLVED)
        truth_summary = await get_truth_probe_pending_summary(target_date=target_date, limit=20, repos=repos)
        buy_summary = await get_buy_block_summary(target_date=target_date, repos=repos)
        snapshot_health = await repos.snapshot_sync_runs.get_sync_health_summary(
            stale_threshold_seconds=snapshot_stale_threshold_seconds,
        )
        fill_health = await repos.fill_sync_runs.get_sync_health_summary(
            stale_threshold_seconds=fill_stale_threshold_seconds,
        )
        session = await repos.market_session_repo.get_by_run_date(target_date)
        operations_day_status, operations_day_healthy, operations_day_stale_seconds, operations_day_summary_json = (
            await _fetch_operations_day_status(target_date)
        )
        return IntradayValidationInputs(
            target_date=target_date,
            is_trading_day=session.is_trading_day if session is not None else None,
            market_reason_code=session.reason_code if session is not None else None,
            operations_day_healthy=operations_day_healthy,
            operations_day_stale_seconds=operations_day_stale_seconds,
            operations_day_status=operations_day_status,
            operations_day_summary_json=operations_day_summary_json,
            blocking_unresolved_count=blocking_unresolved_count,
            warning_unresolved_count=warning_unresolved_count,
            truth_probe_pending_count=truth_summary.total_count,
            snapshot_health=snapshot_health,
            fill_health=fill_health,
            buy_block_summary=buy_summary,
        )


async def _run_async(args: argparse.Namespace) -> int:
    target_date = date.fromisoformat(args.date) if args.date else datetime.now(_KST).date()
    inputs = await _fetch_inputs(
        target_date=target_date,
        snapshot_stale_threshold_seconds=args.snapshot_stale_threshold_seconds,
        fill_stale_threshold_seconds=args.fill_stale_threshold_seconds,
    )
    evaluation = IntradayOperationalEvaluator().evaluate(inputs)
    if args.persist:
        await persist_operations_day_evaluation(
            dsn=build_dsn_from_env(),
            run_date=target_date,
            key="intraday_validation",
            payload=_build_persisted_summary(evaluation),
            is_trading_day=evaluation.is_trading_day,
        )
    if args.output == "json":
        print(evaluation.to_json())
    else:
        print(evaluation.to_text())
    return 0 if evaluation.overall_status == "READY" else 1


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate current intraday operational validation status.")
    parser.add_argument("--date", help="Target KST date (YYYY-MM-DD). Default: today in Asia/Seoul.")
    parser.add_argument("--output", choices=("text", "json"), default="text")
    parser.add_argument("--snapshot-stale-threshold-seconds", type=int, default=1800)
    parser.add_argument("--fill-stale-threshold-seconds", type=int, default=1800)
    parser.add_argument(
        "--persist",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Persist compact evaluation summary into operations_day_runs.summary_json.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    return asyncio.run(_run_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
