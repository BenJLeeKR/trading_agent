#!/usr/bin/env python3
"""Evaluate current market_overlay runtime activation and operating effect.

This script combines:
- current trading-universe preview diagnostics
- recent market_overlay decision / order funnel metrics
- a compact bottleneck-stage inference

The result can be printed as text/json and optionally persisted into
``trading.operations_day_runs.summary_json`` for the current KST date.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from agent_trading.db.transaction import transaction as db_transaction
from agent_trading.runtime.bootstrap import _build_kis_live_quote_client, postgres_runtime
from agent_trading.services.universe_selection import UniverseSelectionService
from agent_trading.services.universe_selection_types import (
    CompositionContext,
    MarketOverlayDiagnostics,
    SourceType,
)
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


@dataclass(slots=True, frozen=True)
class MarketOverlayCheck:
    code: str
    label: str
    status: str
    measured_value: str | None
    threshold: str | None
    message: str


@dataclass(slots=True, frozen=True)
class MarketOverlayRecentSample:
    symbol: str | None
    decision_type: str | None
    side: str | None
    inclusion_reason: str | None
    created_at: datetime | None
    order_status: str | None


@dataclass(slots=True, frozen=True)
class MarketOverlayRuntimeInputs:
    target_date: date
    account_id: UUID | None
    account_label: str | None
    kis_env: str | None
    preview_total_count: int
    preview_market_overlay_count: int
    preview_source_type_counts: dict[str, int]
    diagnostics: MarketOverlayDiagnostics
    decision_count: int
    order_count: int
    decision_type_counts: dict[str, int]
    order_status_counts: dict[str, int]
    recent_samples: Sequence[MarketOverlayRecentSample] = field(default_factory=tuple)


@dataclass(slots=True, frozen=True)
class MarketOverlayRuntimeEvaluation:
    target_date: date
    generated_at: datetime
    overall_status: str
    bottleneck_stage: str
    account_id: UUID | None
    account_label: str | None
    kis_env: str | None
    preview_market_overlay_count: int
    decision_count: int
    order_count: int
    checks: Sequence[MarketOverlayCheck] = field(default_factory=tuple)
    recent_samples: Sequence[MarketOverlayRecentSample] = field(default_factory=tuple)

    def to_json(self) -> str:
        return json.dumps(
            {
                "target_date": self.target_date.isoformat(),
                "generated_at": self.generated_at.isoformat(),
                "overall_status": self.overall_status,
                "bottleneck_stage": self.bottleneck_stage,
                "account_id": str(self.account_id) if self.account_id else None,
                "account_label": self.account_label,
                "kis_env": self.kis_env,
                "preview_market_overlay_count": self.preview_market_overlay_count,
                "decision_count": self.decision_count,
                "order_count": self.order_count,
                "checks": [asdict(check) for check in self.checks],
                "recent_samples": [
                    {
                        "symbol": sample.symbol,
                        "decision_type": sample.decision_type,
                        "side": sample.side,
                        "inclusion_reason": sample.inclusion_reason,
                        "created_at": sample.created_at.isoformat() if sample.created_at else None,
                        "order_status": sample.order_status,
                    }
                    for sample in self.recent_samples
                ],
            },
            ensure_ascii=False,
            indent=2,
        )

    def to_text(self) -> str:
        lines = [
            "=== Market Overlay Runtime Validation ===",
            f"date: {self.target_date.isoformat()} (Asia/Seoul)",
            f"overall: {self.overall_status}",
            f"bottleneck_stage: {self.bottleneck_stage}",
            f"account: {self.account_label or self.account_id or 'N/A'}",
            f"kis_env: {self.kis_env or 'N/A'}",
            f"preview_market_overlay: {self.preview_market_overlay_count}",
            f"decision_count: {self.decision_count}",
            f"order_count: {self.order_count}",
            "",
            "[checks]",
        ]
        for check in self.checks:
            lines.append(
                f"- {check.code} [{check.status}] {check.label}: "
                f"value={check.measured_value or 'N/A'} threshold={check.threshold or 'N/A'}"
            )
            lines.append(f"  {check.message}")
        if self.recent_samples:
            lines.append("")
            lines.append("[recent_samples]")
            for sample in self.recent_samples:
                lines.append(
                    f"- {sample.symbol or '-'} | {sample.decision_type or '-'} | "
                    f"{sample.side or '-'} | {sample.inclusion_reason or '-'} | "
                    f"order={sample.order_status or '-'}"
                )
        return "\n".join(lines)


class MarketOverlayRuntimeEvaluator:
    def evaluate(
        self,
        inputs: MarketOverlayRuntimeInputs,
    ) -> MarketOverlayRuntimeEvaluation:
        checks = [
            self._build_preview_check(inputs),
            self._build_quote_quality_check(inputs),
            self._build_decision_funnel_check(inputs),
            self._build_order_conversion_check(inputs),
        ]
        overall = self._determine_overall(checks)
        bottleneck_stage = self._infer_bottleneck_stage(inputs)
        return MarketOverlayRuntimeEvaluation(
            target_date=inputs.target_date,
            generated_at=datetime.now(timezone.utc),
            overall_status=overall,
            bottleneck_stage=bottleneck_stage,
            account_id=inputs.account_id,
            account_label=inputs.account_label,
            kis_env=inputs.kis_env,
            preview_market_overlay_count=inputs.preview_market_overlay_count,
            decision_count=inputs.decision_count,
            order_count=inputs.order_count,
            checks=checks,
            recent_samples=inputs.recent_samples,
        )

    def _build_preview_check(self, inputs: MarketOverlayRuntimeInputs) -> MarketOverlayCheck:
        diagnostics = inputs.diagnostics
        if inputs.account_id is None:
            return MarketOverlayCheck(
                code="MKT_OVR_ACCOUNT",
                label="preview 계좌 선택",
                status="BLOCKED",
                measured_value="missing",
                threshold="active account",
                message="활성 계좌를 찾지 못해 trading-universe preview를 계산하지 못했습니다.",
            )
        if not diagnostics.enabled:
            return MarketOverlayCheck(
                code="MKT_OVR_PREVIEW",
                label="preview market_overlay 편입",
                status="BLOCKED",
                measured_value=diagnostics.skipped_reason or "disabled",
                threshold="enabled",
                message=(
                    "market_overlay preview가 비활성 상태입니다. "
                    f"skipped_reason={diagnostics.skipped_reason or 'unknown'}."
                ),
            )
        if inputs.preview_market_overlay_count > 0:
            return MarketOverlayCheck(
                code="MKT_OVR_PREVIEW",
                label="preview market_overlay 편입",
                status="READY",
                measured_value=str(inputs.preview_market_overlay_count),
                threshold=">0",
                message="현재 preview 기준 market_overlay 심볼이 실제로 편입되었습니다.",
            )
        return MarketOverlayCheck(
            code="MKT_OVR_PREVIEW",
            label="preview market_overlay 편입",
            status="WARN",
            measured_value="0",
            threshold=">0",
            message=(
                "현재 preview 기준 market_overlay 편입이 0건입니다. "
                "Universe selection 단계에서 후보 생성이 약하거나 필터링되고 있을 수 있습니다."
            ),
        )

    def _build_quote_quality_check(self, inputs: MarketOverlayRuntimeInputs) -> MarketOverlayCheck:
        diagnostics = inputs.diagnostics
        requested = diagnostics.quotes_requested_count
        received = diagnostics.quotes_received_count
        if not diagnostics.enabled or requested <= 0:
            return MarketOverlayCheck(
                code="MKT_OVR_QUOTES",
                label="quote fetch 품질",
                status="WARN",
                measured_value=f"{received}/{requested}",
                threshold="requested>0",
                message="quote fetch 품질을 평가할 요청 표본이 없습니다.",
            )
        if received == 0:
            return MarketOverlayCheck(
                code="MKT_OVR_QUOTES",
                label="quote fetch 품질",
                status="BLOCKED",
                measured_value=f"{received}/{requested}",
                threshold=">0",
                message="quote 요청은 있었지만 성공 수신이 0건입니다. universe selection 단계가 사실상 차단되고 있습니다.",
            )
        ratio = received / requested if requested else 0.0
        if ratio < 0.5:
            return MarketOverlayCheck(
                code="MKT_OVR_QUOTES",
                label="quote fetch 품질",
                status="WARN",
                measured_value=f"{received}/{requested}",
                threshold=">=50%",
                message="quote 수신률이 낮습니다. KIS 응답 품질 또는 예산/시간 제약을 점검해야 합니다.",
            )
        return MarketOverlayCheck(
            code="MKT_OVR_QUOTES",
            label="quote fetch 품질",
            status="READY",
            measured_value=f"{received}/{requested}",
            threshold=">=50%",
            message="quote 수신률이 운영 점검 기준을 충족합니다.",
        )

    def _build_decision_funnel_check(self, inputs: MarketOverlayRuntimeInputs) -> MarketOverlayCheck:
        if inputs.preview_market_overlay_count > 0 and inputs.decision_count == 0:
            return MarketOverlayCheck(
                code="MKT_OVR_DECISION",
                label="recent decision funnel",
                status="WARN",
                measured_value="0",
                threshold=">0 when preview active",
                message=(
                    "preview에는 market_overlay가 보이지만 최근 lookback 구간에는 "
                    "market_overlay decision이 없습니다. decision loop skip 또는 미실행 여부를 확인해야 합니다."
                ),
            )
        if inputs.decision_count > 0:
            return MarketOverlayCheck(
                code="MKT_OVR_DECISION",
                label="recent decision funnel",
                status="READY",
                measured_value=str(inputs.decision_count),
                threshold=">0",
                message="최근 lookback 구간에 market_overlay decision이 실제로 생성되었습니다.",
            )
        return MarketOverlayCheck(
            code="MKT_OVR_DECISION",
            label="recent decision funnel",
            status="WARN",
            measured_value="0",
            threshold=">0",
            message="최근 lookback 구간에 market_overlay decision이 아직 관측되지 않았습니다.",
        )

    def _build_order_conversion_check(self, inputs: MarketOverlayRuntimeInputs) -> MarketOverlayCheck:
        if inputs.decision_count <= 0:
            return MarketOverlayCheck(
                code="MKT_OVR_CONVERSION",
                label="decision → order 전환",
                status="WARN",
                measured_value="0/0",
                threshold="order>0 when decisions exist",
                message="decision 표본이 없어 order 전환 효과를 아직 평가할 수 없습니다.",
            )
        if inputs.order_count > 0:
            return MarketOverlayCheck(
                code="MKT_OVR_CONVERSION",
                label="decision → order 전환",
                status="READY",
                measured_value=f"{inputs.order_count}/{inputs.decision_count}",
                threshold=">0",
                message="market_overlay decision이 실제 주문 전환까지 이어졌습니다.",
            )
        normalized_types = {key.lower() for key in inputs.decision_type_counts}
        if normalized_types and normalized_types.issubset({"hold", "watch"}):
            return MarketOverlayCheck(
                code="MKT_OVR_CONVERSION",
                label="decision → order 전환",
                status="WARN",
                measured_value=f"{inputs.order_count}/{inputs.decision_count}",
                threshold=">0",
                message="decision은 있었지만 모두 HOLD/WATCH 중심이라 order 전환이 없었습니다.",
            )
        return MarketOverlayCheck(
            code="MKT_OVR_CONVERSION",
            label="decision → order 전환",
            status="WARN",
            measured_value=f"{inputs.order_count}/{inputs.decision_count}",
            threshold=">0",
            message="decision은 있었지만 order 생성으로 이어지지 않았습니다. submit gate 또는 후속 차단을 점검해야 합니다.",
        )

    def _infer_bottleneck_stage(self, inputs: MarketOverlayRuntimeInputs) -> str:
        diagnostics = inputs.diagnostics
        if inputs.account_id is None:
            return "account_resolution"
        if not diagnostics.enabled or diagnostics.quotes_received_count == 0:
            return "universe_selection"
        if inputs.preview_market_overlay_count > 0 and inputs.decision_count == 0:
            return "decision_loop"
        if inputs.decision_count > 0 and inputs.order_count == 0:
            return "order_conversion"
        if inputs.preview_market_overlay_count == 0 and inputs.decision_count > 0:
            return "historical_only"
        return "active"

    @staticmethod
    def _determine_overall(checks: Sequence[MarketOverlayCheck]) -> str:
        if any(check.status == "BLOCKED" for check in checks):
            return "BLOCKED"
        if any(check.status == "WARN" for check in checks):
            return "WARN"
        return "READY"


def _build_persisted_summary(
    evaluation: MarketOverlayRuntimeEvaluation,
) -> dict[str, object]:
    return build_evaluation_entry(
        overall_status=evaluation.overall_status,
        generated_at=evaluation.generated_at,
        checks=evaluation.checks,
        extra={
            "target_date": evaluation.target_date.isoformat(),
            "bottleneck_stage": evaluation.bottleneck_stage,
            "account_id": str(evaluation.account_id) if evaluation.account_id else None,
            "account_label": evaluation.account_label,
            "kis_env": evaluation.kis_env,
            "preview_market_overlay_count": evaluation.preview_market_overlay_count,
            "decision_count": evaluation.decision_count,
            "order_count": evaluation.order_count,
        },
    )


async def _resolve_preview_account(account_id: str | None) -> tuple[UUID | None, str | None]:
    if account_id:
        try:
            parsed = UUID(account_id)
        except ValueError:
            raise SystemExit(f"Invalid --account-id UUID: {account_id}")
        async with db_transaction() as tx:
            row = await tx.connection.fetchrow(
                """
                SELECT account_id, COALESCE(account_alias, account_code, broker_account_id) AS account_label
                FROM trading.accounts
                WHERE account_id = $1
                LIMIT 1
                """,
                parsed,
            )
        if row is None:
            return None, None
        return parsed, str(row["account_label"]) if row["account_label"] is not None else None

    async with db_transaction() as tx:
        row = await tx.connection.fetchrow(
            """
            SELECT account_id, COALESCE(account_alias, account_code, broker_account_id) AS account_label
            FROM trading.accounts
            WHERE LOWER(COALESCE(status, '')) = 'active'
            ORDER BY updated_at DESC NULLS LAST, created_at DESC, account_id ASC
            LIMIT 1
            """
        )
    if row is None:
        return None, None
    return row["account_id"], str(row["account_label"]) if row["account_label"] is not None else None


async def _fetch_funnel_metrics(
    since: datetime,
    sample_limit: int,
) -> tuple[int, int, dict[str, int], dict[str, int], list[MarketOverlayRecentSample]]:
    async with db_transaction() as tx:
        summary_row = await tx.connection.fetchrow(
            """
            WITH overlay_decisions AS (
                SELECT td.trade_decision_id
                FROM trading.trade_decisions td
                WHERE td.created_at >= $1
                  AND LOWER(COALESCE(td.source_type, '')) = 'market_overlay'
            ),
            latest_orders AS (
                SELECT DISTINCT ON (o.trade_decision_id)
                    o.trade_decision_id
                FROM trading.order_requests o
                JOIN overlay_decisions od
                  ON od.trade_decision_id = o.trade_decision_id
                ORDER BY o.trade_decision_id, o.created_at DESC, o.order_request_id DESC
            )
            SELECT
                (SELECT COUNT(*)::int FROM overlay_decisions) AS decision_count,
                (SELECT COUNT(*)::int FROM latest_orders) AS order_count
            """,
            since,
        )
        decision_rows = await tx.connection.fetch(
            """
            SELECT
                LOWER(COALESCE(td.decision_type::text, 'unknown')) AS decision_type,
                COUNT(*)::int AS decision_count
            FROM trading.trade_decisions td
            WHERE td.created_at >= $1
              AND LOWER(COALESCE(td.source_type, '')) = 'market_overlay'
            GROUP BY LOWER(COALESCE(td.decision_type::text, 'unknown'))
            ORDER BY decision_count DESC, decision_type ASC
            """,
            since,
        )
        order_rows = await tx.connection.fetch(
            """
            WITH latest_orders AS (
                SELECT DISTINCT ON (o.trade_decision_id)
                    o.trade_decision_id,
                    LOWER(COALESCE(o.status::text, 'unknown')) AS order_status
                FROM trading.order_requests o
                JOIN trading.trade_decisions td
                  ON td.trade_decision_id = o.trade_decision_id
                WHERE o.created_at >= $1
                  AND LOWER(COALESCE(td.source_type, '')) = 'market_overlay'
                ORDER BY o.trade_decision_id, o.created_at DESC, o.order_request_id DESC
            )
            SELECT order_status, COUNT(*)::int AS order_count
            FROM latest_orders
            GROUP BY order_status
            ORDER BY order_count DESC, order_status ASC
            """,
            since,
        )
        sample_rows = await tx.connection.fetch(
            """
            WITH latest_orders AS (
                SELECT DISTINCT ON (o.trade_decision_id)
                    o.trade_decision_id,
                    LOWER(COALESCE(o.status::text, '')) AS order_status
                FROM trading.order_requests o
                ORDER BY o.trade_decision_id, o.created_at DESC, o.order_request_id DESC
            )
            SELECT
                td.symbol,
                LOWER(COALESCE(td.decision_type::text, '')) AS decision_type,
                LOWER(COALESCE(td.side::text, '')) AS side,
                COALESCE(td.decision_json->>'inclusion_reason', '') AS inclusion_reason,
                td.created_at,
                lo.order_status
            FROM trading.trade_decisions td
            LEFT JOIN latest_orders lo
              ON lo.trade_decision_id = td.trade_decision_id
            WHERE td.created_at >= $1
              AND LOWER(COALESCE(td.source_type, '')) = 'market_overlay'
            ORDER BY td.created_at DESC, td.trade_decision_id DESC
            LIMIT $2
            """,
            since,
            sample_limit,
        )
    return (
        int((summary_row or {}).get("decision_count") or 0),
        int((summary_row or {}).get("order_count") or 0),
        {str(row["decision_type"]): int(row["decision_count"] or 0) for row in decision_rows},
        {str(row["order_status"]): int(row["order_count"] or 0) for row in order_rows},
        [
            MarketOverlayRecentSample(
                symbol=row["symbol"],
                decision_type=row["decision_type"] or None,
                side=row["side"] or None,
                inclusion_reason=row["inclusion_reason"] or None,
                created_at=row["created_at"],
                order_status=row["order_status"] or None,
            )
            for row in sample_rows
        ],
    )


async def _fetch_inputs(
    *,
    target_date: date,
    account_id: str | None,
    lookback_days: int,
    sample_limit: int,
) -> MarketOverlayRuntimeInputs:
    preview_account_id, account_label = await _resolve_preview_account(account_id)
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    decision_count, order_count, decision_type_counts, order_status_counts, recent_samples = (
        await _fetch_funnel_metrics(since, sample_limit)
    )

    preview_total_count = 0
    preview_market_overlay_count = 0
    preview_source_type_counts: dict[str, int] = {}
    diagnostics = MarketOverlayDiagnostics(enabled=False, skipped_reason="no_preview_account")
    kis_env: str | None = None

    if preview_account_id is not None:
        async with postgres_runtime(run_migrations=False) as runtime:
            repos = runtime["repositories"]
            settings = runtime["settings"]
            kis_client = _build_kis_live_quote_client(settings)
            kis_env = getattr(kis_client, "env", None) if kis_client is not None else None
            service = UniverseSelectionService(repos=repos, kis_client=kis_client)
            selected, diagnostics = await service.compose_with_diagnostics(
                CompositionContext(
                    account_id=preview_account_id,
                    since=datetime.now(timezone.utc) - timedelta(hours=24),
                    max_cap=30,
                    exclude_held_from_cap=True,
                    market_overlay_cap=5,
                    pre_pool_size=50,
                )
            )
            preview_total_count = len(selected)
            preview_source_type_counts = dict(Counter(item.source_type.value for item in selected))
            preview_market_overlay_count = sum(
                1 for item in selected if item.source_type == SourceType.MARKET_OVERLAY
            )
            if kis_client is not None:
                await kis_client.close()

    return MarketOverlayRuntimeInputs(
        target_date=target_date,
        account_id=preview_account_id,
        account_label=account_label,
        kis_env=kis_env,
        preview_total_count=preview_total_count,
        preview_market_overlay_count=preview_market_overlay_count,
        preview_source_type_counts=preview_source_type_counts,
        diagnostics=diagnostics,
        decision_count=decision_count,
        order_count=order_count,
        decision_type_counts=decision_type_counts,
        order_status_counts=order_status_counts,
        recent_samples=recent_samples,
    )


async def _run_async(args: argparse.Namespace) -> int:
    target_date = date.fromisoformat(args.date) if args.date else datetime.now(_KST).date()
    inputs = await _fetch_inputs(
        target_date=target_date,
        account_id=args.account_id,
        lookback_days=args.lookback_days,
        sample_limit=args.sample_limit,
    )
    evaluation = MarketOverlayRuntimeEvaluator().evaluate(inputs)
    if args.persist:
        await persist_operations_day_evaluation(
            dsn=build_dsn_from_env(),
            run_date=target_date,
            key="market_overlay_runtime_validation",
            payload=_build_persisted_summary(evaluation),
            is_trading_day=True,
        )
    if args.output == "json":
        print(evaluation.to_json())
    else:
        print(evaluation.to_text())
    return 0 if evaluation.overall_status == "READY" else 1


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate market_overlay runtime activation and operating effect.")
    parser.add_argument("--date", help="Target KST date (YYYY-MM-DD). Default: today in Asia/Seoul.")
    parser.add_argument("--account-id", help="Preview account UUID. Default: latest active account.")
    parser.add_argument("--lookback-days", type=int, default=14)
    parser.add_argument("--sample-limit", type=int, default=5)
    parser.add_argument("--output", choices=("text", "json"), default="text")
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
