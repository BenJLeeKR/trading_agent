from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from agent_trading.repositories.contracts import FillSyncHealthSummary, SnapshotSyncHealthSummary
from scripts.evaluate_intraday_operational_validation import (
    IntradayOperationalEvaluator,
    IntradayValidationInputs,
    _INTRADAY_CUTOFF,
    _build_persisted_summary,
)


def _snapshot_health(*, is_stale: bool = False, last_status: str | None = "completed") -> SnapshotSyncHealthSummary:
    now = datetime.now(timezone.utc)
    return SnapshotSyncHealthSummary(
        last_run_started_at=now,
        last_run_completed_at=now,
        last_status=last_status,
        last_successful_run_at=now,
        consecutive_failures=0,
        is_stale=is_stale,
        stale_threshold_seconds=1800,
        after_hours=False,
    )


def _fill_health(
    *,
    is_stale: bool = False,
    last_status: str | None = "completed",
    total_retries: int = 0,
) -> FillSyncHealthSummary:
    now = datetime.now(timezone.utc)
    return FillSyncHealthSummary(
        last_run_started_at=now,
        last_run_completed_at=now,
        last_status=last_status,
        last_successful_run_at=now,
        consecutive_failures=0,
        is_stale=is_stale,
        stale_threshold_seconds=1800,
        retried_accounts=1 if total_retries else 0,
        retried_days=1 if total_retries else 0,
        total_retries=total_retries,
    )


def _inputs(**overrides: object) -> IntradayValidationInputs:
    base: dict[str, object] = {
        "target_date": date(2026, 6, 4),
        "is_trading_day": True,
        "market_reason_code": "KIS_HOLIDAY_TRADING_DAY",
        "operations_day_healthy": True,
        "operations_day_stale_seconds": 10,
        "operations_day_status": "intraday",
        "operations_day_summary_json": {
            "command_health": {
                "post_submit_sync": {
                    "last_metrics": {
                        "refresh": {
                            "scheduled": 2,
                            "completed": 2,
                            "degraded": 0,
                            "failed": 0,
                            "avg_elapsed_ms": 1200,
                            "max_elapsed_ms": 1800,
                        }
                    }
                }
            },
            "decision_loop": {
                "name": "decision_submit_gate",
                "ok": True,
                "timed_out": False,
                "duration_seconds": 41.3,
            }
        },
        "blocking_unresolved_count": 0,
        "warning_unresolved_count": 0,
        "truth_probe_pending_count": 0,
        "snapshot_health": _snapshot_health(),
        "fill_health": _fill_health(),
        "buy_block_summary": SimpleNamespace(
            total_buy_decisions=10,
            buy_orders_created_count=2,
            submit_budget_consumed_count=0,
            general_submit_disabled_count=0,
            sizing_rejected_count=0,
            missing_reference_price_count=0,
        ),
    }
    base.update(overrides)
    return IntradayValidationInputs(**base)


def test_intraday_evaluation_ready_when_core_signals_are_healthy() -> None:
    with patch.object(
        IntradayOperationalEvaluator,
        "_expected_scheduler_status",
        return_value="intraday",
    ):
        evaluation = IntradayOperationalEvaluator().evaluate(_inputs())
    assert evaluation.overall_status == "READY"


def test_intraday_evaluation_blocked_when_buy_lane_is_gate_blocked() -> None:
    evaluation = IntradayOperationalEvaluator().evaluate(
        _inputs(
            buy_block_summary=SimpleNamespace(
                total_buy_decisions=12,
                buy_orders_created_count=0,
                submit_budget_consumed_count=12,
                general_submit_disabled_count=0,
                sizing_rejected_count=0,
                missing_reference_price_count=0,
            )
        )
    )
    assert evaluation.overall_status == "BLOCKED"
    buy_lane_check = next(check for check in evaluation.checks if check.code == "INTRA_BUY_LANE")
    assert buy_lane_check.status == "BLOCKED"


def test_intraday_evaluation_warns_on_fill_sync_retry() -> None:
    evaluation = IntradayOperationalEvaluator().evaluate(
        _inputs(fill_health=_fill_health(total_retries=1))
    )
    assert evaluation.overall_status == "WARN"
    fill_check = next(check for check in evaluation.checks if check.code == "INTRA_FILL_SYNC_HEALTH")
    assert fill_check.status == "WARN"


def test_intraday_evaluation_warns_when_scheduler_phase_mismatches_current_window() -> None:
    with patch.object(
        IntradayOperationalEvaluator,
        "_expected_scheduler_status",
        return_value="intraday",
    ):
        evaluation = IntradayOperationalEvaluator().evaluate(
            _inputs(operations_day_status="pre_market")
        )

    ops_check = next(check for check in evaluation.checks if check.code == "INTRA_OPERATIONS_DAY")
    assert ops_check.status == "WARN"


def test_intraday_evaluation_warns_on_fill_refresh_degraded() -> None:
    evaluation = IntradayOperationalEvaluator().evaluate(
        _inputs(
            operations_day_summary_json={
                "decision_loop": {
                    "name": "decision_submit_gate",
                    "ok": True,
                    "timed_out": False,
                    "duration_seconds": 41.3,
                },
                "command_health": {
                    "post_submit_sync": {
                        "last_metrics": {
                            "refresh": {
                                "scheduled": 1,
                                "completed": 0,
                                "degraded": 1,
                                "failed": 0,
                                "avg_elapsed_ms": 2200,
                                "max_elapsed_ms": 2200,
                            }
                        }
                    }
                },
            }
        )
    )
    refresh_check = next(check for check in evaluation.checks if check.code == "INTRA_FILL_REFRESH")
    assert refresh_check.status == "WARN"


def test_intraday_evaluation_ready_when_fill_refresh_metrics_are_healthy() -> None:
    evaluation = IntradayOperationalEvaluator().evaluate(_inputs())
    refresh_check = next(check for check in evaluation.checks if check.code == "INTRA_FILL_REFRESH")
    assert refresh_check.status == "READY"


def test_intraday_evaluation_warns_on_buy_lane_bias_after_some_orders_created() -> None:
    evaluation = IntradayOperationalEvaluator().evaluate(
        _inputs(
            buy_block_summary=SimpleNamespace(
                total_buy_decisions=20,
                buy_orders_created_count=2,
                submit_budget_consumed_count=5,
                general_submit_disabled_count=2,
                sizing_rejected_count=0,
                missing_reference_price_count=0,
            )
        )
    )
    bias_check = next(check for check in evaluation.checks if check.code == "INTRA_BUY_LANE_BIAS")
    assert bias_check.status == "WARN"


def test_intraday_cutoff_is_153030() -> None:
    assert _INTRADAY_CUTOFF.isoformat() == "15:30:30"


def test_build_persisted_summary_indexes_warn_codes() -> None:
    evaluation = IntradayOperationalEvaluator().evaluate(
        _inputs(fill_health=_fill_health(total_retries=1))
    )
    payload = _build_persisted_summary(evaluation)

    assert payload["overall_status"] == "WARN"
    assert payload["buy_orders_created_count"] == 2
    assert "INTRA_FILL_SYNC_HEALTH" in payload["warn_codes"]
