#!/usr/bin/env python3
"""Exit Criteria evaluation — 자동/부분자동/수동 3층 검증.

Layer A (자동 판정)
  GateEvaluationService.evaluate() 8 checks + health endpoint 2 checks
  → PASS / WARN / FAIL

Layer B (부분 자동)
  테스트/스크립트 실행 결과 + snapshot sync scheduler 상태
  → OK / FAIL / CHECK / NOT_RUN

Layer C (수동 검증)
  운영자 체크리스트 템플릿
  → PENDING

최종 종합 규칙
  1. Layer A FAIL 존재 → FAIL (exit 2)
  2. Layer A 통과 + Layer B FAIL → HOLD (exit 1)
  3. Layer A/B 양호 + Layer C 미완료 → HOLD (exit 1)
  4. 모두 양호/완료 → PASS (exit 0)

Usage
-----
.. code-block:: bash

    # 기본 실행 (Layer A만, text 출력)
    python -m scripts.evaluate_exit_criteria \\
        --account-id <UUID> \\
        --start-date 2026-04-01 \\
        --end-date 2026-05-01

    # 벤치마크 + semi-auto 검증 + JSON 출력
    python -m scripts.evaluate_exit_criteria \\
        --account-id <UUID> \\
        --start-date 2026-04-01 \\
        --end-date 2026-05-01 \\
        --benchmark-code KOSPI \\
        --run-semi \\
        --output json

    # Manual 체크리스트 템플릿 출력
    python -m scripts.evaluate_exit_criteria \\
        --account-id <UUID> \\
        --start-date 2026-04-01 \\
        --end-date 2026-05-01 \\
        --manual-template
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Sequence
from uuid import UUID

from agent_trading.config.settings import AppSettings
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.contracts import SnapshotSyncHealthSummary
from agent_trading.services.benchmark_comparison import (
    InMemoryBenchmarkPriceRepository,
    _DEFAULT_BENCHMARK_PRICES,
)
from agent_trading.services.gate_evaluation import (
    GateStatus,
    OverallStatus,
    GateEvaluationService,
    GateEvaluation,
    compute_reason_code_summary,
)
from agent_trading.services.risk_metric_constants import GateReasonCode

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dataclasses for Layer results
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class AutoCheckResult:
    """단일 Layer A check 결과."""

    code: str
    status: str  # PASS / WARN / FAIL
    measured_value: str | None
    threshold: str | None
    message: str
    reason_code: str | None = None


@dataclass(slots=True, frozen=True)
class SemiCheckResult:
    """단일 Layer B check 결과."""

    code: str
    status: str  # OK / FAIL / CHECK / NOT_RUN
    detail: str


@dataclass(slots=True, frozen=True)
class ManualCheckResult:
    """단일 Layer C check 결과."""

    code: str
    label: str
    checklist: str
    status: str = "PENDING"  # PENDING / DONE / SKIPPED


# ---------------------------------------------------------------------------
# Evaluation result containers
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class LayerAResult:
    """Layer A: 자동 판정 결과."""

    status: str  # PASS / WARN / FAIL
    checks: Sequence[AutoCheckResult]
    gate_evaluation: GateEvaluation | None
    # --- 신규: reason_code 요약 집계 (read-only additive) ---
    reason_code_counts: dict[str, int] = field(default_factory=dict)
    warn_reason_codes: list[str] = field(default_factory=list)
    fail_reason_codes: list[str] = field(default_factory=list)
    display_only_count: int = 0


@dataclass(slots=True, frozen=True)
class LayerBResult:
    """Layer B: 부분 자동 결과."""

    status: str  # OK / CHECK / FAIL
    checks: Sequence[SemiCheckResult]


@dataclass(slots=True, frozen=True)
class LayerCResult:
    """Layer C: 수동 검증 템플릿."""

    status: str  # PENDING / DONE
    checks: Sequence[ManualCheckResult]


@dataclass(slots=True, frozen=True)
class FinalOverall:
    """최종 종합 판정."""

    status: str  # PASS / HOLD / FAIL
    exit_code: int
    reason: str


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


class PaperExitEvaluator:
    """Paper Exit Criteria 평가자.

    Layer A/B/C를 순차적으로 평가하고 최종 종합 판정을 생성한다.
    """

    def __init__(
        self,
        repos: RepositoryContainer,
        settings: AppSettings | None = None,
        benchmark_price_repo: InMemoryBenchmarkPriceRepository | None = None,
    ) -> None:
        self._repos = repos
        self._settings = settings or AppSettings()
        self._bench_price_repo = benchmark_price_repo

        self._gate_service = GateEvaluationService(
            repos=repos,
            settings=self._settings,
            benchmark_price_repo=benchmark_price_repo,
        )

    # ------------------------------------------------------------------
    # Layer A: 자동 판정
    # ------------------------------------------------------------------

    async def evaluate_auto(
        self,
        account_id: UUID,
        start_date: date,
        end_date: date,
        strategy_id: UUID | None = None,
        benchmark_code: str | None = None,
    ) -> LayerAResult:
        """Layer A 평가 — GateEvaluationService 재사용 + health/readyz 대응."""
        gate_eval = await self._gate_service.evaluate(
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            strategy_id=strategy_id,
            benchmark_code=benchmark_code,
        )

        checks: list[AutoCheckResult] = []
        for c in gate_eval.checks:
            checks.append(
                AutoCheckResult(
                    code=c.code,
                    status=c.status.value,
                    measured_value=self._fmt_decimal(c.measured_value),
                    threshold=self._fmt_decimal(c.threshold),
                    message=c.message,
                    reason_code=c.reason_code,  # propagate from GateCheck
                )
            )

        # A9: HEALTH_ENDPOINT — snapshot staleness
        health_stale: bool | None = None
        try:
            health_summary = await self._repos.snapshot_sync_runs.get_sync_health_summary(
                stale_threshold_seconds=self._settings.kis_snapshot_stale_threshold_seconds,
            )
            health_stale = health_summary.is_stale
        except Exception:
            health_stale = None

        if health_stale is True:
            health_status = "FAIL"
            health_msg = "snapshot_sync_stale = True → FAIL"
            health_reason = GateReasonCode.SNAPSHOT_STALE.value
        elif health_stale is False:
            health_status = "PASS"
            health_msg = "snapshot_sync_stale = False"
            health_reason = None
        else:
            health_status = "FAIL"
            health_msg = "health endpoint unavailable → FAIL"
            health_reason = GateReasonCode.HEALTH_UNAVAILABLE.value

        checks.append(
            AutoCheckResult(
                code="HEALTH_ENDPOINT",
                status=health_status,
                measured_value=str(health_stale) if health_stale is not None else None,
                threshold="False",
                message=health_msg + " (stale→FAIL)",
                reason_code=health_reason,
            )
        )

        # A10: READYZ_ENDPOINT — readyz degraded/not_ready
        if health_stale is True:
            readyz_status = "WARN"
            readyz_msg = "snapshot_sync_stale → degraded → HOLD"
            readyz_reason = GateReasonCode.SNAPSHOT_STALE.value
        elif health_stale is False:
            readyz_status = "PASS"
            readyz_msg = "snapshot_sync_fresh → ok"
            readyz_reason = None
        else:
            readyz_status = "FAIL"
            readyz_msg = "health endpoint unavailable → not_ready → FAIL"
            readyz_reason = GateReasonCode.HEALTH_UNAVAILABLE.value

        checks.append(
            AutoCheckResult(
                code="READYZ_ENDPOINT",
                status=readyz_status,
                measured_value="degraded" if health_stale else "ok",
                threshold="ok",
                message=readyz_msg + " (not_ready→FAIL, degraded→HOLD)",
                reason_code=readyz_reason,
            )
        )

        # Layer A overall
        has_fail = any(c.status == "FAIL" for c in checks)
        has_warn = any(c.status == "WARN" for c in checks)
        if has_fail:
            a_status = "FAIL"
        elif has_warn:
            a_status = "WARN"
        else:
            a_status = "PASS"

        summary_data = compute_reason_code_summary(checks)
        return LayerAResult(
            status=a_status,
            checks=checks,
            gate_evaluation=gate_eval,
            **summary_data,
        )

    # ------------------------------------------------------------------
    # Layer B: 부분 자동
    # ------------------------------------------------------------------

    async def evaluate_semi(
        self,
        account_id: UUID,
        start_date: date,
        end_date: date,
        run_semi: bool = False,
    ) -> LayerBResult:
        """Layer B 평가.

        Parameters
        ----------
        run_semi:
            True면 subprocess로 테스트/스크립트를 실행한다.
            False면 B1~B3/B5는 NOT_RUN, B4(snapshot sync)만 평가한다.
        """
        checks: list[SemiCheckResult] = []

        # B1: Service test suite
        if run_semi:
            b1_ok, b1_detail = await self._run_pytest("tests/services/")
            checks.append(
                SemiCheckResult(
                    code="SERVICE_TESTS",
                    status="OK" if b1_ok else "FAIL",
                    detail=b1_detail,
                )
            )
        else:
            checks.append(
                SemiCheckResult(
                    code="SERVICE_TESTS",
                    status="NOT_RUN",
                    detail="--run-semi 미실행, 수동 확인 필요",
                )
            )

        # B2: Paper loop verification
        if run_semi:
            b2_ok, b2_detail = await self._run_script(
                "python -m scripts.verify_decision_loop --count 1",
            )
            checks.append(
                SemiCheckResult(
                    code="VERIFY_PAPER_LOOP",
                    status="OK" if b2_ok else "FAIL",
                    detail=b2_detail,
                )
            )
        else:
            checks.append(
                SemiCheckResult(
                    code="VERIFY_PAPER_LOOP",
                    status="NOT_RUN",
                    detail="--run-semi 미실행, 수동 확인 필요",
                )
            )

        # B3: Decision loop dry-run
        if run_semi:
            b3_ok, b3_detail = await self._run_script(
                "python -m scripts.run_decision_loop --count 1 --dry-run",
            )
            checks.append(
                SemiCheckResult(
                    code="DECISION_LOOP_DRY",
                    status="OK" if b3_ok else "FAIL",
                    detail=b3_detail,
                )
            )
        else:
            checks.append(
                SemiCheckResult(
                    code="DECISION_LOOP_DRY",
                    status="NOT_RUN",
                    detail="--run-semi 미실행, 수동 확인 필요",
                )
            )

        # B4: Snapshot sync scheduler (항상 자동 수집)
        b4_status, b4_detail = await self._check_snapshot_sync()
        checks.append(
            SemiCheckResult(
                code="SNAPSHOT_SYNC_SCHEDULER",
                status=b4_status,
                detail=b4_detail,
            )
        )

        # B5: 개별 테스트 파일
        if run_semi:
            b5_results: list[str] = []
            b5_all_ok = True
            test_targets = [
                ("safe_order_path", "tests/services/test_safe_order_path_e2e.py"),
                ("sizing_engine", "tests/services/test_sizing_engine.py"),
                ("pipeline", "tests/services/test_decision_submit_pipeline.py"),
                ("scenarios", "tests/services/test_decision_loop_scenarios.py"),
            ]
            for label, path in test_targets:
                ok, detail = await self._run_pytest(path)
                b5_results.append(f"{label}: {detail}")
                if not ok:
                    b5_all_ok = False

            checks.append(
                SemiCheckResult(
                    code="TEST_SUITE_DETAIL",
                    status="OK" if b5_all_ok else "FAIL",
                    detail="; ".join(b5_results),
                )
            )
        else:
            checks.append(
                SemiCheckResult(
                    code="TEST_SUITE_DETAIL",
                    status="NOT_RUN",
                    detail="--run-semi 미실행, 수동 확인 필요",
                )
            )

        # Layer B overall
        has_fail = any(c.status == "FAIL" for c in checks)
        has_check = any(c.status in ("CHECK", "NOT_RUN") for c in checks)
        if has_fail:
            b_status = "FAIL"
        elif has_check:
            b_status = "CHECK"
        else:
            b_status = "OK"

        return LayerBResult(status=b_status, checks=checks)

    # ------------------------------------------------------------------
    # Layer C: 수동 검증 템플릿
    # ------------------------------------------------------------------

    def build_manual_template(
        self,
        auto_result: LayerAResult,
        semi_result: LayerBResult | None = None,
    ) -> LayerCResult:
        """Layer C 수동 검증 체크리스트 템플릿 생성."""
        checks: list[ManualCheckResult] = [
            ManualCheckResult(
                code="BROKER_SUBMIT_SMOKE",
                label="Broker submit smoke 검토",
                checklist=(
                    "KIS paper 대상 ENABLE_KIS_PAPER_SUBMIT_SMOKE=true 테스트를 "
                    "실행했는가? 실행 결과 C3 케이스가 PASS했는가?"
                ),
            ),
            ManualCheckResult(
                code="PIPELINE_ERROR_RATE",
                label="Pipeline 오류율 검토",
                checklist=(
                    "최근 10회 decision cycle 중 pipeline error(pipeline 예외/타임아웃)가 "
                    "1회 미만인가? (< 10%)"
                ),
            ),
            ManualCheckResult(
                code="RECONCILIATION_DEGRADE",
                label="Reconciliation 상태 검토",
                checklist=(
                    "admin UI ReconciliationView에서 미해결 mismatch 건수가 0인가? "
                    "활성 lock이 있는가?"
                ),
            ),
            ManualCheckResult(
                code="AUDIT_LOG_CONTINUITY",
                label="Audit log 연속성 확인",
                checklist=(
                    "audit log가 최근 24시간 동안 1시간 이상의 갭 없이 "
                    "연속 기록되고 있는가?"
                ),
            ),
            ManualCheckResult(
                code="FINAL_OPERATOR_DECISION",
                label="최종 운영 판단",
                checklist=(
                    "위 Layer A/B/C 모든 정보를 종합하여, paper 운용을 종료하고 "
                    "live 검토를 시작해도 되는가?"
                ),
            ),
        ]

        return LayerCResult(status="PENDING", checks=checks)

    # ------------------------------------------------------------------
    # Overall decision
    # ------------------------------------------------------------------

    @staticmethod
    def _determine_overall(
        auto: LayerAResult,
        semi: LayerBResult,
        manual: LayerCResult,
    ) -> FinalOverall:
        """최종 종합 판정 규칙.

        1. Layer A FAIL 존재 → FAIL (exit 2)
        2. Layer A 통과 + Layer B FAIL → HOLD (exit 1)
        3. Layer A/B 양호 + Layer C 미완료 → HOLD (exit 1)
        4. 모두 양호/완료 → PASS (exit 0)
        """
        # Rule 1
        if auto.status == "FAIL":
            return FinalOverall(
                status="FAIL",
                exit_code=2,
                reason=(
                    f"Layer A 자동 판정 FAIL (Gate: {auto.gate_evaluation.overall_status.value}). "
                    "성과/안정성/건강도 지표 불충족. 원인 분석 후 재평가 필요."
                ),
            )

        # Rule 2
        if semi.status == "FAIL":
            return FinalOverall(
                status="HOLD",
                exit_code=1,
                reason=(
                    "Layer A 자동 판정은 PASS지만 Layer B 부분 자동 검증에 FAIL 존재. "
                    "테스트/스크립트 검증 실패 원인 분석 필요."
                ),
            )

        # Rule 3
        if manual.status == "PENDING":
            return FinalOverall(
                status="HOLD",
                exit_code=1,
                reason=(
                    "Layer A/B 자동/부분자동 항목 모두 양호. "
                    "Layer C 수동 검증 미완료 — 운영자 체크리스트 완료 후 최종 PASS."
                ),
            )

        # Rule 4
        return FinalOverall(
            status="PASS",
            exit_code=0,
            reason=(
                "모든 Layer(A/B/C) 양호. Paper Exit Criteria 통과 — "
                "paper 종료 및 live 검토 자격 획득."
            ),
        )

    # ------------------------------------------------------------------
    # 출력 포맷
    # ------------------------------------------------------------------

    @staticmethod
    def _build_reason_code_text_summary(
        result: LayerAResult,
    ) -> str:
        """Build one-line reason_code text summary (counts only, no detail codes)."""
        parts = []
        if result.warn_reason_codes:
            parts.append(f"warn={len(result.warn_reason_codes)}")
        if result.fail_reason_codes:
            parts.append(f"fail={len(result.fail_reason_codes)}")
        if result.display_only_count:
            parts.append(f"display_only={result.display_only_count}")
        if not parts:
            return ""
        return f"reason_codes: {', '.join(parts)}"

    def to_text(
        self,
        auto: LayerAResult,
        semi: LayerBResult,
        manual: LayerCResult,
        overall: FinalOverall,
        account_id: UUID,
        start_date: date,
        end_date: date,
    ) -> str:
        """텍스트 보고서 생성."""
        lines: list[str] = []
        _hl = "━" * 54

        lines.append(f"┏{_hl}┓")
        lines.append(f"┃         Paper Exit Criteria Evaluation{' ' : >22}┃")
        lines.append(
            f"┃         {start_date.isoformat()} ~ {end_date.isoformat()}"
            f"{' ' : >17}┃"
        )
        lines.append(
            f"┃         Account: {str(account_id)[:8]}...{' ' : >28}┃"
        )
        lines.append(f"┗{_hl}┛")
        lines.append("")

        # Layer A
        a_ok = sum(1 for c in auto.checks if c.status == "PASS")
        a_total = len(auto.checks)
        a_label = f"Layer A: 자동 판정 — {auto.status}  ({a_ok}/{a_total} pass)"
        lines.append(f"[{a_label}]")
        for c in auto.checks:
            icon = self._status_icon(c.status)
            lines.append(
                f"  {icon} {c.code:20s} {c.message}"
            )
        # Reason code summary line (counts only)
        rc_summary = self._build_reason_code_text_summary(auto)
        if rc_summary:
            lines.append(f"  {rc_summary}")
        lines.append("")

        # Layer B
        b_ok = sum(1 for c in semi.checks if c.status == "OK")
        b_not_run = sum(1 for c in semi.checks if c.status == "NOT_RUN")
        b_total = len(semi.checks)
        b_label = (
            f"Layer B: 부분 자동 — {semi.status}  "
            f"({b_ok}/{b_total} ok, {b_not_run} not_run)"
        )
        lines.append(f"[{b_label}]")
        for c in semi.checks:
            icon = self._status_icon(c.status)
            if c.status == "NOT_RUN":
                icon = "⚪"
            lines.append(f"  {icon} {c.code:25s} {c.detail}")
        lines.append("")

        # Layer C
        c_pending = sum(1 for c in manual.checks if c.status == "PENDING")
        lines.append(f"[Layer C: 수동 검증 — {manual.status}]  ({c_pending} items pending)")
        for c in manual.checks:
            lines.append(f"  ⬜ {c.code:25s} — {c.checklist}")
        lines.append("")

        # Overall
        lines.append(f"{_hl}")
        overall_icon = self._status_icon(overall.status)
        lines.append(
            f"Overall: {overall_icon} {overall.status} "
            f"(자동: {auto.status}, 부분자동: {semi.status}, 수동: {manual.status})"
        )
        lines.append(f"→ {overall.reason}")
        lines.append(f"{_hl}")

        return "\n".join(lines)

    def to_json(
        self,
        auto: LayerAResult,
        semi: LayerBResult,
        manual: LayerCResult,
        overall: FinalOverall,
        account_id: UUID,
        start_date: date,
        end_date: date,
        strategy_id: UUID | None = None,
        benchmark_code: str | None = None,
    ) -> str:
        """JSON 보고서 생성."""
        doc: dict[str, Any] = {
            "metadata": {
                "account_id": str(account_id),
                "strategy_id": str(strategy_id) if strategy_id else None,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "benchmark_code": benchmark_code,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "overall": overall.status,
                "exit_code": overall.exit_code,
                "reason": overall.reason,
            },
            "layers": {
                "auto": {
                    "status": auto.status,
                    "summary": f"{sum(1 for c in auto.checks if c.status == 'PASS')}/{len(auto.checks)} pass",
                    "checks": [
                        {
                            "code": c.code,
                            "status": c.status,
                            "measured_value": c.measured_value,
                            "threshold": c.threshold,
                            "message": c.message,
                            "reason_code": c.reason_code,
                        }
                        for c in auto.checks
                    ],
                    "reason_code_summary": {
                        "reason_code_counts": auto.reason_code_counts,
                        "warn_reason_codes": auto.warn_reason_codes,
                        "fail_reason_codes": auto.fail_reason_codes,
                        "display_only_count": auto.display_only_count,
                    },
                },
                "semi": {
                    "status": semi.status,
                    "summary": (
                        f"{sum(1 for c in semi.checks if c.status == 'OK')}/{len(semi.checks)} ok, "
                        f"{sum(1 for c in semi.checks if c.status == 'NOT_RUN')} not_run"
                    ),
                    "checks": [
                        {
                            "code": c.code,
                            "status": c.status,
                            "detail": c.detail,
                        }
                        for c in semi.checks
                    ],
                },
                "manual": {
                    "status": manual.status,
                    "summary": f"{sum(1 for c in manual.checks if c.status == 'PENDING')} items pending",
                    "checks": [
                        {
                            "code": c.code,
                            "label": c.label,
                            "checklist": c.checklist,
                            "status": c.status,
                        }
                        for c in manual.checks
                    ],
                },
            },
        }
        return json.dumps(doc, indent=2, ensure_ascii=False)

    def to_manual_template(
        self,
        auto: LayerAResult,
        semi: LayerBResult,
        manual: LayerCResult,
        overall: FinalOverall,
        account_id: UUID,
        start_date: date,
        end_date: date,
    ) -> str:
        """Manual 체크리스트 마크다운 템플릿 생성."""
        lines: list[str] = []
        lines.append("# Paper Exit Criteria — Manual Checklist")
        lines.append("")
        lines.append(f"Account ID: `{account_id}`")
        lines.append(f"Period: {start_date.isoformat()} ~ {end_date.isoformat()}")
        lines.append(
            f"Generated: {datetime.now(timezone.utc).isoformat()}"
        )
        lines.append("")

        # Layer A summary
        lines.append(f"## Layer A: Auto ({auto.status})")
        a_pass = sum(1 for c in auto.checks if c.status == "PASS")
        lines.append(f"All {a_pass}/{len(auto.checks)} auto checks passed.")
        if auto.gate_evaluation:
            lines.append(f"Gate status: {auto.gate_evaluation.overall_status.value}.")
        lines.append("")

        # Layer B summary
        lines.append(f"## Layer B: Semi-Auto ({semi.status})")
        lines.append("| Code | Status | Detail |")
        lines.append("|------|--------|--------|")
        for c in semi.checks:
            icon = "✅" if c.status == "OK" else "⚠" if c.status in ("CHECK", "NOT_RUN") else "❌"
            lines.append(f"| {c.code} | {icon} {c.status} | {c.detail} |")
        lines.append("")

        # Layer C checklist
        lines.append("## Layer C: Manual Verification")
        lines.append("")
        for c in manual.checks:
            lines.append(f"- [ ] **{c.label}** (`{c.code}`)")
            lines.append(f"  - Checklist: {c.checklist}")
            lines.append(f"  - Result: ")
            lines.append(f"  - Notes: ")
            lines.append("")
        lines.append("- [ ] **최종 운영 판단** (`FINAL_OPERATOR_DECISION`)")
        lines.append("  - Decision: GO / NO-GO")
        lines.append("  - Reason: ")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _status_icon(status: str) -> str:
        if status == "PASS" or status == "OK":
            return "✅"
        if status == "WARN" or status == "CHECK":
            return "⚠"
        if status == "FAIL":
            return "❌"
        return "⬜"

    @staticmethod
    def _fmt_decimal(value: Decimal | int | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return str(value)
        return str(value)

    async def _check_snapshot_sync(self) -> tuple[str, str]:
        """B4: Snapshot sync scheduler 상태 확인."""
        try:
            health_summary = await self._repos.snapshot_sync_runs.get_sync_health_summary(
                stale_threshold_seconds=self._settings.kis_snapshot_stale_threshold_seconds,
            )
        except Exception as exc:
            return "FAIL", f"snapshot_sync health check error: {exc}"

        if health_summary.last_successful_run_at is None:
            return "CHECK", "snapshot_sync: last_successful_run_at 없음 (아직 실행 안 됨)"

        now = datetime.now(timezone.utc)
        # Replace tzinfo for naive datetime comparison
        last_ok = health_summary.last_successful_run_at
        if last_ok.tzinfo is None:
            last_ok = last_ok.replace(tzinfo=timezone.utc)

        hours_ago = (now - last_ok).total_seconds() / 3600
        detail = (
            f"snapshot_sync last_successful_run_at: "
            f"{health_summary.last_successful_run_at.isoformat()} "
            f"(약 {hours_ago:.1f}시간 전)"
        )

        if health_summary.is_stale:
            return "CHECK", detail + " → stale (확인 필요)"
        return "OK", detail

    @staticmethod
    async def _run_pytest(path: str) -> tuple[bool, str]:
        """pytest를 subprocess로 실행."""
        try:
            result = subprocess.run(
                ["python", "-m", "pytest", path, "-v", "--tb=short"],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return False, f"TIMEOUT: pytest {path} (120s)"
        except FileNotFoundError:
            return False, f"pytest not found"

        passed = result.returncode == 0
        # Extract summary line
        last_line = ""
        for line in result.stdout.splitlines():
            if "passed" in line or "failed" in line or "error" in line:
                last_line = line.strip()
        if not last_line:
            last_line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "no output"

        return passed, last_line

    @staticmethod
    async def _run_script(command: str) -> tuple[bool, str]:
        """CLI 명령어를 subprocess로 실행."""
        try:
            result = subprocess.run(
                command.split(),
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            return False, f"TIMEOUT: {command} (60s)"
        except FileNotFoundError:
            return False, f"command not found: {command}"

        passed = result.returncode == 0
        detail = f"exit {result.returncode}"
        if result.stdout.strip():
            last_lines = result.stdout.strip().splitlines()[-3:]
            detail += f" | {'; '.join(last_lines)}"
        if result.stderr.strip():
            detail += f" | stderr: {result.stderr.strip()[:200]}"

        return passed, detail


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Paper Exit Criteria Evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m scripts.evaluate_exit_criteria \\\n"
            "      --account-id <UUID> \\\n"
            "      --start-date 2026-04-01 --end-date 2026-05-01\n\n"
            "  python -m scripts.evaluate_exit_criteria \\\n"
            "      --account-id <UUID> \\\n"
            "      --start-date 2026-04-01 --end-date 2026-05-01 \\\n"
            "      --benchmark-code KOSPI --run-semi --output json\n\n"
            "  python -m scripts.evaluate_exit_criteria \\\n"
            "      --account-id <UUID> \\\n"
            "      --start-date 2026-04-01 --end-date 2026-05-01 \\\n"
            "      --manual-template"
        ),
    )
    parser.add_argument(
        "--account-id",
        required=True,
        help="Account UUID",
    )
    parser.add_argument(
        "--start-date",
        required=True,
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        required=True,
        help="End date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--strategy-id",
        default=None,
        help="Optional strategy UUID",
    )
    parser.add_argument(
        "--benchmark-code",
        default=None,
        choices=["KOSPI", "KOSDAQ"],
        help="Optional benchmark code (e.g. KOSPI)",
    )
    parser.add_argument(
        "--run-semi",
        action="store_true",
        help="Run Layer B semi-auto verification (tests/scripts)",
    )
    parser.add_argument(
        "--output",
        default="text",
        choices=["text", "json"],
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--manual-template",
        action="store_true",
        help="Print manual checklist template and exit",
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Returns exit code (0=PASS, 1=HOLD, 2=FAIL).
    """
    args = _parse_args(argv)

    # Validate
    try:
        account_id = UUID(args.account_id)
    except ValueError:
        print(f"ERROR: Invalid account_id UUID: {args.account_id}", file=sys.stderr)
        return 2

    try:
        start_date = date.fromisoformat(args.start_date)
    except ValueError:
        print(f"ERROR: Invalid start_date: {args.start_date}", file=sys.stderr)
        return 2

    try:
        end_date = date.fromisoformat(args.end_date)
    except ValueError:
        print(f"ERROR: Invalid end_date: {args.end_date}", file=sys.stderr)
        return 2

    if start_date > end_date:
        print("ERROR: start_date must be on or before end_date", file=sys.stderr)
        return 2

    strategy_id: UUID | None = None
    if args.strategy_id:
        try:
            strategy_id = UUID(args.strategy_id)
        except ValueError:
            print(f"ERROR: Invalid strategy_id UUID: {args.strategy_id}", file=sys.stderr)
            return 2

    # Build dependencies
    from agent_trading.repositories.bootstrap import build_in_memory_repositories

    repos = build_in_memory_repositories()
    settings = AppSettings()

    benchmark_price_repo: InMemoryBenchmarkPriceRepository | None = None
    if args.benchmark_code:
        benchmark_price_repo = InMemoryBenchmarkPriceRepository(
            prices=_DEFAULT_BENCHMARK_PRICES,
        )

    evaluator = PaperExitEvaluator(
        repos=repos,
        settings=settings,
        benchmark_price_repo=benchmark_price_repo,
    )

    # Evaluate Layer A
    auto_result = await evaluator.evaluate_auto(
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
        strategy_id=strategy_id,
        benchmark_code=args.benchmark_code,
    )

    # Evaluate Layer B
    semi_result = await evaluator.evaluate_semi(
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
        run_semi=args.run_semi,
    )

    # Build Layer C template
    manual_result = evaluator.build_manual_template(
        auto_result=auto_result,
        semi_result=semi_result,
    )

    # Overall
    overall = PaperExitEvaluator._determine_overall(auto_result, semi_result, manual_result)

    # Output
    if args.manual_template:
        print(
            evaluator.to_manual_template(
                auto=auto_result,
                semi=semi_result,
                manual=manual_result,
                overall=overall,
                account_id=account_id,
                start_date=start_date,
                end_date=end_date,
            )
        )
    elif args.output == "json":
        print(
            evaluator.to_json(
                auto=auto_result,
                semi=semi_result,
                manual=manual_result,
                overall=overall,
                account_id=account_id,
                start_date=start_date,
                end_date=end_date,
                strategy_id=strategy_id,
                benchmark_code=args.benchmark_code,
            )
        )
    else:
        print(
            evaluator.to_text(
                auto=auto_result,
                semi=semi_result,
                manual=manual_result,
                overall=overall,
                account_id=account_id,
                start_date=start_date,
                end_date=end_date,
            )
        )

    return overall.exit_code


if __name__ == "__main__":
    import asyncio

    sys.exit(asyncio.run(main()))
