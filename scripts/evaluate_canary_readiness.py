#!/usr/bin/env python3
"""Canary Readiness evaluation — Exit Criteria 이후 Live 검토 자격 판정.

Paper Exit Criteria (Layer A)를 재사용하여 paper 단계 합격 여부를 확인하고,
그 위에 **live-specific 추가 기준**을 적용하여 최종 canary 진입 가능성을 평가한다.

Live Gate는 Paper Exit을 **전제**한다:
  - Paper Exit FAIL/HOLD → Live Gate **BLOCKED** (paper 자격 미달)
  - Paper Exit PASS + Live auto FAIL → **BLOCKED** (live 안전 기준 미달)
  - Paper Exit PASS + Live auto WARN → **HOLD** (주의 항목 해결 필요)
  - Paper Exit PASS + Live auto PASS + Manual 미완료 → **HOLD**
  - Paper Exit PASS + Live auto PASS + Manual 완료 → **READY** (canary 진입 가능)

Usage
-----
.. code-block:: bash

    # 기본 실행 (text 출력)
    python -m scripts.evaluate_canary_readiness \\
        --account-id <UUID> \\
        --start-date 2026-04-01 \\
        --end-date 2026-05-01

    # JSON 출력 + 수동 체크리스트 템플릿
    python -m scripts.evaluate_canary_readiness \\
        --account-id <UUID> \\
        --start-date 2026-04-01 \\
        --end-date 2026-05-01 \\
        --benchmark-code KOSPI \\
        --output json \\
        --manual-template

제약 조건
---------
- 읽기 전용(read-only) 평가 — live API key를 사용한 주문 실행 금지
- broker submit semantics 변경 금지
- hard guardrail/reconciliation 경계 변경 금지
- paper exit criteria semantics 변경 금지
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Sequence
from uuid import UUID

from agent_trading.config.settings import AppSettings
from agent_trading.domain.enums import OrderStatus
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import OrderQuery
from agent_trading.services.benchmark_comparison import (
    InMemoryBenchmarkPriceRepository,
    _DEFAULT_BENCHMARK_PRICES,
)
from agent_trading.services.gate_evaluation import (
    GateStatus,
    GateEvaluationService,
    GateEvaluation,
    compute_reason_code_summary,
)
from agent_trading.services.performance_summary import PerformanceSummaryService
from agent_trading.services.risk_metric_constants import GateReasonCode
from scripts.evaluate_exit_criteria import (
    PaperExitEvaluator,
    AutoCheckResult,
    LayerAResult,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class LiveGateCheck:
    """단일 Live Gate check 결과."""

    code: str
    label: str
    layer: str  # "auto" | "manual"
    status: str  # PASS | WARN | FAIL | PENDING
    measured_value: str | None
    threshold: str | None
    message: str
    reason_code: str | None = None


@dataclass(slots=True, frozen=True)
class LiveCanaryReadinessEvaluation:
    """완전한 Live Gate 평가 결과."""

    account_id: UUID
    strategy_id: UUID | None
    overall_status: str  # READY | HOLD | BLOCKED
    paper_exit_status: str  # PASS | HOLD | FAIL
    checks: Sequence[LiveGateCheck]
    generated_at: datetime
    summary_reason: str
    # --- 신규: reason_code 요약 집계 (read-only additive) ---
    reason_code_counts: dict[str, int] = field(default_factory=dict)
    warn_reason_codes: list[str] = field(default_factory=list)
    fail_reason_codes: list[str] = field(default_factory=list)
    display_only_count: int = 0


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


class LiveGateEvaluator:
    """Live Gate / Canary Readiness 평가자.

    PaperExitEvaluator를 재사용하여 Layer A를 평가하고,
    live-specific 8개 auto check + 6개 manual check를 추가로 수행한다.
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
        self._perf_service = PerformanceSummaryService(repos)

    # ------------------------------------------------------------------
    # Paper Exit 평가 (Layer A 재사용)
    # ------------------------------------------------------------------

    async def evaluate_exit_criteria(
        self,
        account_id: UUID,
        start_date: date,
        end_date: date,
        strategy_id: UUID | None = None,
        benchmark_code: str | None = None,
    ) -> tuple[str, LayerAResult]:
        """PaperExitEvaluator의 Layer A만 실행.

        Returns
        -------
        (overall_status, layer_a_result)
            overall_status: "PASS" | "HOLD" | "FAIL"
        """
        evaluator = PaperExitEvaluator(
            repos=self._repos,
            settings=self._settings,
            benchmark_price_repo=self._bench_price_repo,
        )
        auto = await evaluator.evaluate_auto(
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            strategy_id=strategy_id,
            benchmark_code=benchmark_code,
        )

        # Layer A 기준으로 paper exit 상태 결정
        if auto.status == "FAIL":
            return "FAIL", auto
        elif auto.status == "WARN":
            return "HOLD", auto
        else:
            return "PASS", auto

    # ------------------------------------------------------------------
    # Live-Specific Auto Checks (8개)
    # ------------------------------------------------------------------

    async def evaluate_live_auto(
        self,
        account_id: UUID,
        start_date: date,
        end_date: date,
        strategy_id: UUID | None = None,
        benchmark_code: str | None = None,
    ) -> list[LiveGateCheck]:
        """Live-specific 8개 auto check 실행."""
        checks: list[LiveGateCheck] = []

        # -- 1. LG_FILLED_ORDERS: paper보다 엄격한 최소 체결 건수 --
        metrics = await self._perf_service.get_performance_metrics(
            account_id, start_date, end_date, strategy_id,
        )
        lg_min_orders = self._settings.live_gate_min_filled_orders
        filled = metrics.total_filled_orders
        if filled < lg_min_orders:
            checks.append(LiveGateCheck(
                code="LG_FILLED_ORDERS",
                label="Live 최소 체결 건수",
                layer="auto",
                status="FAIL",
                measured_value=str(filled),
                threshold=str(lg_min_orders),
                message=(
                    f"체결 건수 {filled}건이 live 최소 기준 {lg_min_orders}건에 미달합니다. "
                    f"(paper gate 기준: {self._settings.paper_gate_min_filled_orders}건)"
                ),
                reason_code=GateReasonCode.METRIC_BELOW_THRESHOLD.value,
            ))
        else:
            checks.append(LiveGateCheck(
                code="LG_FILLED_ORDERS",
                label="Live 최소 체결 건수",
                layer="auto",
                status="PASS",
                measured_value=str(filled),
                threshold=str(lg_min_orders),
                message=f"체결 건수 {filled}건 — live 기준 통과",
            ))

        # -- 2. LG_MAX_DRAWDOWN: paper보다 엄격한 최대 손실 폭 --
        lg_max_dd = self._settings.live_gate_max_drawdown_pct
        dd = metrics.max_drawdown_pct
        if dd is not None and dd > lg_max_dd:
            checks.append(LiveGateCheck(
                code="LG_MAX_DRAWDOWN",
                label="Live 최대 손실 폭",
                layer="auto",
                status="FAIL",
                measured_value=f"{dd}%",
                threshold=f"{lg_max_dd}%",
                message=(
                    f"최대 손실 폭 {dd}%이(가) live 허용 기준 {lg_max_dd}%을 초과했습니다. "
                    f"(paper gate 기준: {self._settings.paper_gate_max_drawdown_pct}%)"
                ),
                reason_code=GateReasonCode.METRIC_BELOW_THRESHOLD.value,
            ))
        else:
            dd_str = f"{dd}%" if dd is not None else "N/A"
            checks.append(LiveGateCheck(
                code="LG_MAX_DRAWDOWN",
                label="Live 최대 손실 폭",
                layer="auto",
                status="PASS",
                measured_value=dd_str,
                threshold=f"{lg_max_dd}%",
                message=(
                    f"최대 손실 폭 {dd_str} — live 기준 통과"
                    if dd is not None
                    else "손실 폭 데이터 없음 — PASS"
                ),
            ))

        # -- 3. LG_EXCESS_RETURN: paper보다 엄격한 초과수익 --
        lg_min_excess = self._settings.live_gate_min_excess_return_pct
        if benchmark_code is not None:
            from agent_trading.services.benchmark_comparison import (
                BenchmarkComparisonService,
            )
            bench_service = BenchmarkComparisonService(
                self._repos, self._bench_price_repo,
            )
            try:
                bench = await bench_service.get_benchmark_comparison(
                    account_id, start_date, end_date, benchmark_code, strategy_id,
                )
                excess = bench.excess_return_pct
            except Exception:
                excess = None

            if excess is not None and excess < lg_min_excess:
                checks.append(LiveGateCheck(
                    code="LG_EXCESS_RETURN",
                    label="Live 벤치마크 대비 초과수익",
                    layer="auto",
                    status="FAIL",
                    measured_value=f"{excess}%p",
                    threshold=f"{lg_min_excess}%p",
                    message=(
                        f"초과수익 {excess}%p이(가) live 최소 기준 {lg_min_excess}%p에 미달합니다. "
                        f"(paper gate 기준: {self._settings.paper_gate_min_excess_return_pct}%p)"
                    ),
                    reason_code=GateReasonCode.METRIC_BELOW_THRESHOLD.value,
                ))
            elif excess is not None:
                checks.append(LiveGateCheck(
                    code="LG_EXCESS_RETURN",
                    label="Live 벤치마크 대비 초과수익",
                    layer="auto",
                    status="PASS",
                    measured_value=f"{excess}%p",
                    threshold=f"{lg_min_excess}%p",
                    message=f"초과수익 {excess}%p — live 기준 통과",
                ))
            else:
                checks.append(LiveGateCheck(
                    code="LG_EXCESS_RETURN",
                    label="Live 벤치마크 대비 초과수익",
                    layer="auto",
                    status="WARN",
                    measured_value=None,
                    threshold=f"{lg_min_excess}%p",
                    message="벤치마크 데이터를 불러올 수 없습니다 — 수동 확인 필요",
                    reason_code=GateReasonCode.BENCHMARK_UNAVAILABLE.value,
                ))
        else:
            checks.append(LiveGateCheck(
                code="LG_EXCESS_RETURN",
                label="Live 벤치마크 대비 초과수익",
                layer="auto",
                status="WARN",
                measured_value=None,
                threshold=f"{lg_min_excess}%p",
                message="벤치마크 코드 미지정 — 수동 확인 필요",
                reason_code=GateReasonCode.BENCHMARK_CODE_MISSING.value,
            ))

        # -- 4. LG_WIN_RATE: paper gate threshold 재사용 --
        win_rate = metrics.win_rate
        paper_win_threshold = self._settings.paper_gate_min_win_rate_pct
        if win_rate is not None and win_rate < paper_win_threshold:
            checks.append(LiveGateCheck(
                code="LG_WIN_RATE",
                label="Live 최소 승률",
                layer="auto",
                status="WARN",
                measured_value=f"{win_rate}%",
                threshold=f"{paper_win_threshold}%",
                message=(
                    f"승률 {win_rate}%이(가) 기준 {paper_win_threshold}%에 미달합니다. "
                    "(paper gate threshold 재사용)"
                ),
                reason_code=GateReasonCode.METRIC_BELOW_THRESHOLD.value,
            ))
        else:
            wr_str = f"{win_rate}%" if win_rate is not None else "N/A"
            checks.append(LiveGateCheck(
                code="LG_WIN_RATE",
                label="Live 최소 승률",
                layer="auto",
                status="PASS",
                measured_value=wr_str,
                threshold=f"{paper_win_threshold}%",
                message=f"승률 {wr_str} — 기준 통과",
            ))

        # -- 5. LG_RECENT_RECONCILE: 최근 reconcile_required 발생 횟수 --
        max_reconcile = self._settings.live_gate_max_recent_reconcile_required
        # 최근 50개 order 중 RECONCILE_REQUIRED 상태 조회
        recent_orders = await self._repos.orders.list(OrderQuery(
            account_id=account_id,
            statuses=[OrderStatus.RECONCILE_REQUIRED],
            limit=50,
        ))
        reconcile_count = len(recent_orders)
        if reconcile_count > max_reconcile:
            checks.append(LiveGateCheck(
                code="LG_RECENT_RECONCILE",
                label="최근 Reconcile Required 발생",
                layer="auto",
                status="FAIL",
                measured_value=str(reconcile_count),
                threshold=str(max_reconcile),
                message=(
                    f"최근 RECONCILE_REQUIRED 상태 {reconcile_count}건 — "
                    f"허용 기준 {max_reconcile}건 초과"
                ),
                reason_code=GateReasonCode.EXCESSIVE_RECONCILE_REQUIRED.value,
            ))
        else:
            checks.append(LiveGateCheck(
                code="LG_RECENT_RECONCILE",
                label="최근 Reconcile Required 발생",
                layer="auto",
                status="PASS",
                measured_value=str(reconcile_count),
                threshold=str(max_reconcile),
                message=f"RECONCILE_REQUIRED {reconcile_count}건 — 기준 이내",
            ))

        # -- 6. LG_RECENT_BLOCKING_LOCKS: 활성 차단 lock --
        max_locks = self._settings.live_gate_max_recent_blocking_locks
        active_locks = await self._repos.reconciliations.list_all_active_locks()
        account_locks = [lk for lk in active_locks if lk.account_id == account_id]
        lock_count = len(account_locks)
        if lock_count > max_locks:
            checks.append(LiveGateCheck(
                code="LG_RECENT_BLOCKING_LOCKS",
                label="최근 차단 Lock 존재",
                layer="auto",
                status="FAIL",
                measured_value=str(lock_count),
                threshold=str(max_locks),
                message=(
                    f"활성 차단 lock {lock_count}개 — "
                    f"허용 기준 {max_locks}개 초과. 해결 후 재평가 필요."
                ),
                reason_code=GateReasonCode.BLOCKING_LOCK_PRESENT.value,
            ))
        else:
            checks.append(LiveGateCheck(
                code="LG_RECENT_BLOCKING_LOCKS",
                label="최근 차단 Lock 존재",
                layer="auto",
                status="PASS",
                measured_value=str(lock_count),
                threshold=str(max_locks),
                message=(
                    f"활성 차단 lock {lock_count}개 — 기준 이내"
                ),
            ))

        # -- 7. LG_READYZ: snapshot sync freshness (readyz 대응) --
        health = await self._repos.snapshot_sync_runs.get_sync_health_summary(
            stale_threshold_seconds=self._settings.kis_snapshot_stale_threshold_seconds,
        )
        if health.is_stale:
            checks.append(LiveGateCheck(
                code="LG_READYZ",
                label="Snapshot Sync Freshness",
                layer="auto",
                status="WARN",
                measured_value="stale",
                threshold="fresh",
                message=(
                    "스냅샷 동기화가 최신 상태가 아닙니다. "
                    "readyz degraded 상태 — 확인 필요."
                ),
                reason_code=GateReasonCode.SNAPSHOT_STALE.value,
            ))
        else:
            checks.append(LiveGateCheck(
                code="LG_READYZ",
                label="Snapshot Sync Freshness",
                layer="auto",
                status="PASS",
                measured_value="fresh",
                threshold="fresh",
                message="스냅샷 동기화 정상",
            ))

        # -- 8. LG_POST_SUBMIT_SYNC: post-submit sync 최근 성공률 --
        # 간접 지표: snapshot sync health로 post-submit sync 상태를 간접 평가
        # (직접 broker_orders 조회는 post-submit sync 전용 repo가 없으므로,
        #  더 정밀한 측정은 향후 백로그)
        sync_detail = (
            f"최근 성공: {health.last_successful_run_at.isoformat() if health.last_successful_run_at else '없음'}, "
            f"연속 실패: {health.consecutive_failures}"
        )
        if health.consecutive_failures > 0:
            checks.append(LiveGateCheck(
                code="LG_POST_SUBMIT_SYNC",
                label="Post-Submit Sync 상태",
                layer="auto",
                status="WARN" if health.consecutive_failures <= 2 else "FAIL",
                measured_value=f"연속실패 {health.consecutive_failures}회",
                threshold="연속실패 0회",
                message=f"Post-submit sync 연속 실패 {health.consecutive_failures}회 — 확인 필요",
                reason_code=GateReasonCode.SYNC_FAILURE.value,
            ))
        else:
            checks.append(LiveGateCheck(
                code="LG_POST_SUBMIT_SYNC",
                label="Post-Submit Sync 상태",
                layer="auto",
                status="PASS",
                measured_value=sync_detail,
                threshold="연속실패 0회",
                message="Post-submit sync 정상",
            ))

        # -- 9. LG_SHARPE_RATIO: display only, always PASS (first turn) --
        sr = metrics.sharpe_ratio
        if sr is not None:
            checks.append(LiveGateCheck(
                code="LG_SHARPE_RATIO",
                label="Live Sharpe Ratio",
                layer="auto",
                status="PASS",
                measured_value=f"{sr:.4f}",
                threshold="N/A",
                message="Sharpe Ratio 정보 표시 (현재 gate 미적용)",
                reason_code=GateReasonCode.DISPLAY_ONLY.value,
            ))
        else:
            checks.append(LiveGateCheck(
                code="LG_SHARPE_RATIO",
                label="Live Sharpe Ratio",
                layer="auto",
                status="PASS",
                measured_value="N/A",
                threshold="N/A",
                message="Sharpe Ratio 데이터 없음 — 정보 표시",
                reason_code=GateReasonCode.DISPLAY_ONLY.value,
            ))

        # -- 10. LG_SORTINO_RATIO: display only, always PASS (first turn) --
        sortino = metrics.sortino_ratio
        if sortino is not None:
            checks.append(LiveGateCheck(
                code="LG_SORTINO_RATIO",
                label="Live Sortino Ratio",
                layer="auto",
                status="PASS",
                measured_value=f"{sortino:.4f}",
                threshold="N/A",
                message="Sortino Ratio 정보 표시 (현재 gate 미적용)",
                reason_code=GateReasonCode.DISPLAY_ONLY.value,
            ))
        else:
            checks.append(LiveGateCheck(
                code="LG_SORTINO_RATIO",
                label="Live Sortino Ratio",
                layer="auto",
                status="PASS",
                measured_value="N/A",
                threshold="N/A",
                message="Sortino Ratio 데이터 없음 — 정보 표시",
                reason_code=GateReasonCode.DISPLAY_ONLY.value,
            ))

        # -- 11. LG_CALMAR_RATIO: display only, always PASS (first turn) --
        calmar = metrics.calmar_ratio
        if calmar is not None:
            checks.append(LiveGateCheck(
                code="LG_CALMAR_RATIO",
                label="Live Calmar Ratio",
                layer="auto",
                status="PASS",
                measured_value=f"{calmar:.4f}",
                threshold="N/A",
                message="Calmar Ratio 정보 표시 (현재 gate 미적용)",
                reason_code=GateReasonCode.DISPLAY_ONLY.value,
            ))
        else:
            checks.append(LiveGateCheck(
                code="LG_CALMAR_RATIO",
                label="Live Calmar Ratio",
                layer="auto",
                status="PASS",
                measured_value="N/A",
                threshold="N/A",
                message="Calmar Ratio 데이터 없음 — 정보 표시",
                reason_code=GateReasonCode.DISPLAY_ONLY.value,
            ))

        return checks

    # ------------------------------------------------------------------
    # Manual Checklist Template
    # ------------------------------------------------------------------

    def build_manual_template(
        self,
        account_id: UUID,
        start_date: date,
        end_date: date,
    ) -> list[LiveGateCheck]:
        """6개 수동 체크리스트 템플릿 생성."""
        checks: list[LiveGateCheck] = [
            LiveGateCheck(
                code="LG_MANUAL_CREDENTIAL",
                label="Live credential 확인",
                layer="manual",
                status="PENDING",
                measured_value=None,
                threshold=None,
                message=(
                    "KIS live API key/secret이 유효한가? "
                    "Live 계좌번호가 올바른가? KIS_ENV=live로 설정되었는가?"
                ),
            ),
            LiveGateCheck(
                code="LG_MANUAL_ACCOUNT_MASKING",
                label="계좌 정보 마스킹 준비",
                layer="manual",
                status="PENDING",
                measured_value=None,
                threshold=None,
                message=(
                    "Admin UI에서 live 계좌번호가 마스킹 처리되었는가? "
                    "로그에 계좌번호 전체가 노출되지 않도록 조치되었는가?"
                ),
            ),
            LiveGateCheck(
                code="LG_MANUAL_OPERATOR_APPROVAL",
                label="운영자 승인",
                layer="manual",
                status="PENDING",
                measured_value=None,
                threshold=None,
                message=(
                    "운영자가 live canary 진입을 승인했는가? "
                    "승인 일시와 사유가 기록되었는가?"
                ),
            ),
            LiveGateCheck(
                code="LG_MANUAL_PAPER_LOG_REVIEW",
                label="Paper 운영 로그 리뷰",
                layer="manual",
                status="PENDING",
                measured_value=None,
                threshold=None,
                message=(
                    "최근 24시간 paper decision cycle 로그에 이상 징후가 없는가? "
                    "최근 72시간 내 unresolved reconciliation mismatch가 없는가? "
                    "예상치 못한 ERROR/WARNING 로그가 없는가?"
                ),
            ),
            LiveGateCheck(
                code="LG_MANUAL_RATE_LIMIT_REVIEW",
                label="Rate limit 설정 검토",
                layer="manual",
                status="PENDING",
                measured_value=None,
                threshold=None,
                message=(
                    "KIS_REAL_REST_RPS 값이 live 환경에 적절한가? (기본 18) "
                    "Rate limit budget이 paper 대비 충분히 확보되었는가?"
                ),
            ),
            LiveGateCheck(
                code="LG_MANUAL_FINAL_DECISION",
                label="최종 canary 진입 판단",
                layer="manual",
                status="PENDING",
                measured_value=None,
                threshold=None,
                message=(
                    "위 모든 항목을 종합하여 live canary 진입이 가능한가? "
                    "Canary 진입 시 rollback 계획이 준비되었는가?"
                ),
            ),
        ]
        return checks

    # ------------------------------------------------------------------
    # Overall Decision
    # ------------------------------------------------------------------

    @staticmethod
    def _determine_overall(
        paper_exit_status: str,
        live_checks: list[LiveGateCheck],
        manual_checks: list[LiveGateCheck],
    ) -> tuple[str, str]:
        """최종 종합 판정 규칙.

        Returns
        -------
        (overall_status, summary_reason)
        """
        auto_checks = [c for c in live_checks if c.layer == "auto"]
        manual_check_statuses = [c.status for c in manual_checks]

        has_auto_fail = any(c.status == "FAIL" for c in auto_checks)
        has_auto_warn = any(c.status == "WARN" for c in auto_checks)
        all_manual_done = all(s == "DONE" for s in manual_check_statuses)
        has_manual_pending = any(s == "PENDING" for s in manual_check_statuses)

        # Rule 1: Paper exit FAIL/HOLD → BLOCKED
        if paper_exit_status in ("FAIL", "HOLD"):
            return (
                "BLOCKED",
                f"Paper Exit 상태가 {paper_exit_status}입니다. "
                "Paper 단계 자격 미달 — live 검토 불가. "
                "Paper Exit Criteria를 먼저 통과해야 합니다.",
            )

        # Rule 2: Paper PASS + Live auto FAIL → BLOCKED
        if has_auto_fail:
            fail_codes = [c.code for c in auto_checks if c.status == "FAIL"]
            return (
                "BLOCKED",
                f"Paper Exit은 PASS지만 Live-specific auto check {len(fail_codes)}개 FAIL: "
                f"{', '.join(fail_codes)}. "
                "Live 안전 기준 미달 — 원인 분석 후 재평가 필요.",
            )

        # Rule 3: Paper PASS + Live auto WARN → HOLD
        if has_auto_warn:
            warn_codes = [c.code for c in auto_checks if c.status == "WARN"]
            return (
                "HOLD",
                f"Live-specific auto check {len(warn_codes)}개 WARN: "
                f"{', '.join(warn_codes)}. "
                "주의 항목 해결 후 재평가 필요.",
            )

        # Rule 4: Paper PASS + Live auto PASS + Manual PENDING → HOLD
        if has_manual_pending:
            pending_items = [c.code for c in manual_checks if c.status == "PENDING"]
            return (
                "HOLD",
                f"Auto check 모두 PASS. 수동 체크리스트 {len(pending_items)}개 미완료: "
                f"{', '.join(pending_items)}. "
                "운영자 확인 완료 후 최종 READY.",
            )

        # Rule 5: All pass + Manual done → READY
        return (
            "READY",
            "모든 조건 충족 — Live Canary 진입 가능. "
            "Paper Exit PASS + Live-specific auto check 모두 PASS + 수동 확인 완료.",
        )

    # ------------------------------------------------------------------
    # Output Format
    # ------------------------------------------------------------------

    def to_text(
        self,
        paper_exit_status: str,
        paper_exit_auto: LayerAResult | None,
        live_checks: list[LiveGateCheck],
        manual_checks: list[LiveGateCheck],
        overall_status: str,
        summary_reason: str,
        account_id: UUID,
        start_date: date,
        end_date: date,
        *,
        reason_code_counts: dict[str, int] | None = None,
        warn_reason_codes: list[str] | None = None,
        fail_reason_codes: list[str] | None = None,
        display_only_count: int = 0,
    ) -> str:
        """텍스트 보고서 생성."""
        lines: list[str] = []
        _hl = "━" * 54

        lines.append(f"┏{_hl}┓")
        lines.append(f"┃     Live Gate / Canary Readiness Evaluation{' ' : >18}┃")
        lines.append(
            f"┃     {start_date.isoformat()} ~ {end_date.isoformat()}"
            f"{' ' : >19}┃"
        )
        lines.append(
            f"┃     Account: {str(account_id)[:8]}...{' ' : >28}┃"
        )
        lines.append(f"┗{_hl}┛")
        lines.append("")

        # ── Paper Exit Status ──
        pe_icon = self._status_icon(paper_exit_status)
        lines.append(f"[Paper Exit Status]  {pe_icon} {paper_exit_status}")
        if paper_exit_auto is not None:
            a_ok = sum(1 for c in paper_exit_auto.checks if c.status == "PASS")
            a_total = len(paper_exit_auto.checks)
            lines.append(f"  Layer A: {a_ok}/{a_total} pass")
            for c in paper_exit_auto.checks:
                icon = self._status_icon(c.status)
                lines.append(f"    {icon} {c.code:20s} {c.message}")
        lines.append("")

        # ── Live-Specific Auto Checks ──
        auto_checks = [c for c in live_checks if c.layer == "auto"]
        a_pass = sum(1 for c in auto_checks if c.status == "PASS")
        a_warn = sum(1 for c in auto_checks if c.status == "WARN")
        a_fail = sum(1 for c in auto_checks if c.status == "FAIL")
        a_total = len(auto_checks)
        lines.append(
            f"[Live-Specific Auto Checks]  "
            f"{a_pass}/{a_total} pass, {a_warn} warn, {a_fail} fail"
        )
        # Reason code summary line (counts only)
        if warn_reason_codes or fail_reason_codes or display_only_count:
            parts = []
            if warn_reason_codes:
                parts.append(f"warn={len(warn_reason_codes)}")
            if fail_reason_codes:
                parts.append(f"fail={len(fail_reason_codes)}")
            if display_only_count:
                parts.append(f"display_only={display_only_count}")
            lines.append(f"  reason_codes: {', '.join(parts)}")
        for c in auto_checks:
            icon = self._status_icon(c.status)
            mv = f" (实测: {c.measured_value}, 阈值: {c.threshold})" if c.measured_value else ""
            lines.append(f"  {icon} {c.code:28s} {c.message}{mv}")
        lines.append("")

        # ── Manual Checks ──
        m_pending = sum(1 for c in manual_checks if c.status == "PENDING")
        m_done = sum(1 for c in manual_checks if c.status == "DONE")
        m_total = len(manual_checks)
        lines.append(
            f"[Manual Checks]  {m_done}/{m_total} done, {m_pending} pending"
        )
        for c in manual_checks:
            icon = "✅" if c.status == "DONE" else "⬜"
            lines.append(f"  {icon} {c.code:30s} — {c.message}")
        lines.append("")

        # ── Overall ──
        lines.append(f"{_hl}")
        ov_icon = self._status_icon(overall_status)
        lines.append(
            f"Overall: {ov_icon} {overall_status}  "
            f"(Paper Exit: {paper_exit_status}, "
            f"Live Auto: {a_pass}/{a_total} pass, "
            f"Manual: {m_done}/{m_total} done)"
        )
        lines.append(f"→ {summary_reason}")
        lines.append(f"{_hl}")

        return "\n".join(lines)

    def to_json(
        self,
        paper_exit_status: str,
        paper_exit_auto: LayerAResult | None,
        live_checks: list[LiveGateCheck],
        manual_checks: list[LiveGateCheck],
        overall_status: str,
        summary_reason: str,
        account_id: UUID,
        start_date: date,
        end_date: date,
        strategy_id: UUID | None = None,
        benchmark_code: str | None = None,
        *,
        reason_code_counts: dict[str, int] | None = None,
        warn_reason_codes: list[str] | None = None,
        fail_reason_codes: list[str] | None = None,
        display_only_count: int = 0,
    ) -> str:
        """JSON 보고서 생성."""
        all_checks = list(live_checks) + list(manual_checks)
        auto_checks = [c for c in live_checks if c.layer == "auto"]

        doc: dict[str, Any] = {
            "metadata": {
                "account_id": str(account_id),
                "strategy_id": str(strategy_id) if strategy_id else None,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "benchmark_code": benchmark_code,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "evaluation_type": "live_gate",
                "overall": overall_status,
                "paper_exit_status": paper_exit_status,
                "reason": summary_reason,
            },
            "paper_exit": {
                "status": paper_exit_status,
                "layer_a_checks": [
                    {
                        "code": c.code,
                        "status": c.status,
                        "measured_value": c.measured_value,
                        "threshold": c.threshold,
                        "message": c.message,
                        "reason_code": c.reason_code,
                    }
                    for c in (paper_exit_auto.checks if paper_exit_auto else [])
                ] if paper_exit_auto else [],
            },
            "live_gate": {
                "auto_checks": [
                    {
                        "code": c.code,
                        "label": c.label,
                        "status": c.status,
                        "measured_value": c.measured_value,
                        "threshold": c.threshold,
                        "message": c.message,
                        "reason_code": c.reason_code,
                    }
                    for c in auto_checks
                ],
                "auto_summary": {
                    "total": len(auto_checks),
                    "pass": sum(1 for c in auto_checks if c.status == "PASS"),
                    "warn": sum(1 for c in auto_checks if c.status == "WARN"),
                    "fail": sum(1 for c in auto_checks if c.status == "FAIL"),
                },
                "manual_checks": [
                    {
                        "code": c.code,
                        "label": c.label,
                        "status": c.status,
                        "message": c.message,
                    }
                    for c in manual_checks
                ],
                "manual_summary": {
                    "total": len(manual_checks),
                    "pending": sum(1 for c in manual_checks if c.status == "PENDING"),
                    "done": sum(1 for c in manual_checks if c.status == "DONE"),
                },
                "reason_code_summary": {
                    "reason_code_counts": reason_code_counts or {},
                    "warn_reason_codes": warn_reason_codes or [],
                    "fail_reason_codes": fail_reason_codes or [],
                    "display_only_count": display_only_count,
                },
            },
        }
        return json.dumps(doc, indent=2, ensure_ascii=False)

    def to_manual_template(
        self,
        paper_exit_status: str,
        overall_status: str,
        summary_reason: str,
        manual_checks: list[LiveGateCheck],
        account_id: UUID,
        start_date: date,
        end_date: date,
    ) -> str:
        """Manual 체크리스트 마크다운 템플릿 생성."""
        lines: list[str] = []
        lines.append("# Live Gate / Canary Readiness — Manual Checklist")
        lines.append("")
        lines.append(f"Account ID: `{account_id}`")
        lines.append(f"Period: {start_date.isoformat()} ~ {end_date.isoformat()}")
        lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
        lines.append("")
        lines.append("## Evaluation Context")
        lines.append("")
        lines.append(f"- **Paper Exit Status**: {paper_exit_status}")
        lines.append(f"- **Live Gate Overall**: {overall_status}")
        lines.append(f"- **Summary**: {summary_reason}")
        lines.append("")
        lines.append("## Manual Checks")
        lines.append("")
        for c in manual_checks:
            lines.append(f"### {c.code} — {c.label}")
            lines.append("")
            lines.append(f"- [ ] {c.message}")
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append(
            "모든 항목 완료 후 `evaluate_canary_readiness.py`를 다시 실행하여 "
            "최종 READY 상태를 확인하세요."
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _status_icon(status: str) -> str:
        mapping = {
            "PASS": "✅",
            "WARN": "⚠️",
            "FAIL": "❌",
            "PENDING": "⬜",
            "DONE": "✅",
            "BLOCKED": "🔴",
            "HOLD": "🟡",
            "READY": "🟢",
        }
        return mapping.get(status, "❓")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Live Gate / Canary Readiness Evaluation",
    )
    parser.add_argument(
        "--account-id",
        type=UUID,
        required=True,
        help="대상 계좌 UUID",
    )
    parser.add_argument(
        "--start-date",
        type=date.fromisoformat,
        required=True,
        help="평가 기간 시작 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        required=True,
        help="평가 기간 종료 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--strategy-id",
        type=UUID,
        default=None,
        help="전략 UUID (선택)",
    )
    parser.add_argument(
        "--benchmark-code",
        type=str,
        default=None,
        help="벤치마크 코드 (예: KOSPI)",
    )
    parser.add_argument(
        "--output",
        type=str,
        choices=["text", "json"],
        default="text",
        help="출력 포맷 (기본: text)",
    )
    parser.add_argument(
        "--manual-template",
        action="store_true",
        help="수동 체크리스트 템플릿 출력",
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Returns
    -------
    int
        Exit code: 0 = READY, 1 = HOLD, 2 = BLOCKED, 3 = error
    """
    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s | %(message)s",
    )

    settings = AppSettings()

    # In-memory repositories with seed data
    from agent_trading.repositories.bootstrap import build_in_memory_repositories

    repos = build_in_memory_repositories()

    logger.info(
        "Evaluating live gate for account %s (%s ~ %s)",
        args.account_id,
        args.start_date,
        args.end_date,
    )

    # Benchmark price repo
    bench_price_repo = InMemoryBenchmarkPriceRepository(
        prices=_DEFAULT_BENCHMARK_PRICES,
    )

    evaluator = LiveGateEvaluator(
        repos=repos,
        settings=settings,
        benchmark_price_repo=bench_price_repo,
    )

    try:
        # 1. Paper Exit 평가 (Layer A)
        paper_exit_status, paper_exit_auto = await evaluator.evaluate_exit_criteria(
            account_id=args.account_id,
            start_date=args.start_date,
            end_date=args.end_date,
            strategy_id=args.strategy_id,
            benchmark_code=args.benchmark_code,
        )

        # 2. Live-Specific Auto Checks
        live_checks = await evaluator.evaluate_live_auto(
            account_id=args.account_id,
            start_date=args.start_date,
            end_date=args.end_date,
            strategy_id=args.strategy_id,
            benchmark_code=args.benchmark_code,
        )

        # 3. Manual Checklist Template
        manual_checks = evaluator.build_manual_template(
            account_id=args.account_id,
            start_date=args.start_date,
            end_date=args.end_date,
        )

        # 4. Overall Decision
        overall_status, summary_reason = evaluator._determine_overall(
            paper_exit_status=paper_exit_status,
            live_checks=live_checks,
            manual_checks=manual_checks,
        )

        # 5. Reason code summary
        all_checks_for_summary: list[LiveGateCheck] = list(live_checks) + list(manual_checks)
        summary_data = compute_reason_code_summary(all_checks_for_summary)

        # 6. Output
        if args.output == "json":
            output = evaluator.to_json(
                paper_exit_status=paper_exit_status,
                paper_exit_auto=paper_exit_auto,
                live_checks=live_checks,
                manual_checks=manual_checks,
                overall_status=overall_status,
                summary_reason=summary_reason,
                account_id=args.account_id,
                start_date=args.start_date,
                end_date=args.end_date,
                strategy_id=args.strategy_id,
                benchmark_code=args.benchmark_code,
                **summary_data,
            )
        else:
            output = evaluator.to_text(
                paper_exit_status=paper_exit_status,
                paper_exit_auto=paper_exit_auto,
                live_checks=live_checks,
                manual_checks=manual_checks,
                overall_status=overall_status,
                summary_reason=summary_reason,
                account_id=args.account_id,
                start_date=args.start_date,
                end_date=args.end_date,
                **summary_data,
            )

        print(output)

        # Manual template append
        if args.manual_template:
            print()
            print(evaluator.to_manual_template(
                paper_exit_status=paper_exit_status,
                overall_status=overall_status,
                summary_reason=summary_reason,
                manual_checks=manual_checks,
                account_id=args.account_id,
                start_date=args.start_date,
                end_date=args.end_date,
            ))

    except Exception as exc:
        logger.error("Evaluation failed: %s", exc)
        return 3

    # Exit code
    exit_map = {"READY": 0, "HOLD": 1, "BLOCKED": 2}
    return exit_map.get(overall_status, 3)


if __name__ == "__main__":
    sys.exit(main())
