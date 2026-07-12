from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class DailyPriceBar:
    trade_date: str
    close_price: float
    high_price: float
    low_price: float


@dataclass(slots=True, frozen=True)
class TriggerProxyMetrics:
    forward_return_pct_by_horizon: dict[int, float | None]
    mfe_pct_by_horizon: dict[int, float | None]
    mae_pct_by_horizon: dict[int, float | None]


@dataclass(slots=True, frozen=True)
class TriggerProxyAggregateItem:
    bucket: str
    sample_count: int
    t1_return_pct_avg: float | None
    t3_return_pct_avg: float | None
    t5_return_pct_avg: float | None
    t3_mfe_pct_avg: float | None
    t3_mae_pct_avg: float | None
    t5_mfe_pct_avg: float | None
    t5_mae_pct_avg: float | None
    positive_t3_hit_count: int
    positive_t3_hit_rate: float | None


WATCH_TOP_K_BUY = 3
WATCH_TOP_K_WATCH = 8
WATCH_MIN_RANKING_SCORE = 0.50
WATCH_MIN_ENTRY_SCORE = 0.52
WATCH_MIN_PERCENTILE = 0.60
BUY_MIN_RANKING_SCORE = 0.55
BUY_CANDIDATE_THRESHOLD = 0.65
WATCH_CANDIDATE_THRESHOLD = 0.45
CORE_RISK_OFF_RANKING_MIN_SCORE = 0.48
CORE_RISK_OFF_SHADOW_MIN_SCORE = 0.22
CORE_RISK_OFF_FLOOR_REPORT_BUCKETS: tuple[str, ...] = (
    "strict_pass",
    "mild_relax",
    "moderate_relax",
    "deep_negative",
    "unknown",
    "inactive",
)

CORE_RISK_OFF_FLOOR_V2_REPORT_BUCKETS: tuple[str, ...] = CORE_RISK_OFF_FLOOR_REPORT_BUCKETS
CORE_RISK_OFF_FLOOR_V3_REPORT_BUCKETS: tuple[str, ...] = CORE_RISK_OFF_FLOOR_REPORT_BUCKETS
CORE_RISK_OFF_FLOOR_V5_REPORT_BUCKETS: tuple[str, ...] = CORE_RISK_OFF_FLOOR_REPORT_BUCKETS


def calculate_trigger_proxy_metrics(
    bars: Sequence[DailyPriceBar],
    *,
    horizons: Sequence[int] = (1, 3, 5),
) -> TriggerProxyMetrics:
    if not bars:
        return TriggerProxyMetrics(
            forward_return_pct_by_horizon={int(h): None for h in horizons},
            mfe_pct_by_horizon={int(h): None for h in horizons},
            mae_pct_by_horizon={int(h): None for h in horizons},
        )

    entry_close = float(bars[0].close_price)
    if entry_close <= 0:
        return TriggerProxyMetrics(
            forward_return_pct_by_horizon={int(h): None for h in horizons},
            mfe_pct_by_horizon={int(h): None for h in horizons},
            mae_pct_by_horizon={int(h): None for h in horizons},
        )

    forward: dict[int, float | None] = {}
    mfe: dict[int, float | None] = {}
    mae: dict[int, float | None] = {}

    for raw_horizon in horizons:
        horizon = int(raw_horizon)
        if horizon <= 0 or len(bars) <= horizon:
            forward[horizon] = None
            mfe[horizon] = None
            mae[horizon] = None
            continue

        end_bar = bars[horizon]
        window = bars[1 : horizon + 1]
        forward[horizon] = ((float(end_bar.close_price) / entry_close) - 1.0) * 100.0
        mfe[horizon] = ((max(float(bar.high_price) for bar in window) / entry_close) - 1.0) * 100.0
        mae[horizon] = ((min(float(bar.low_price) for bar in window) / entry_close) - 1.0) * 100.0

    return TriggerProxyMetrics(
        forward_return_pct_by_horizon=forward,
        mfe_pct_by_horizon=mfe,
        mae_pct_by_horizon=mae,
    )


def build_trigger_proxy_aggregate_items(
    rows: Iterable[Mapping[str, object]],
    *,
    bucket_key: str,
) -> list[TriggerProxyAggregateItem]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        bucket = str(row.get(bucket_key) or "unknown").strip() or "unknown"
        grouped[bucket].append(row)

    items: list[TriggerProxyAggregateItem] = []
    for bucket, bucket_rows in sorted(
        grouped.items(),
        key=lambda item: (-len(item[1]), item[0]),
    ):
        items.append(
            TriggerProxyAggregateItem(
                bucket=bucket,
                sample_count=len(bucket_rows),
                t1_return_pct_avg=_average(bucket_rows, "t1_return_pct"),
                t3_return_pct_avg=_average(bucket_rows, "t3_return_pct"),
                t5_return_pct_avg=_average(bucket_rows, "t5_return_pct"),
                t3_mfe_pct_avg=_average(bucket_rows, "t3_mfe_pct"),
                t3_mae_pct_avg=_average(bucket_rows, "t3_mae_pct"),
                t5_mfe_pct_avg=_average(bucket_rows, "t5_mfe_pct"),
                t5_mae_pct_avg=_average(bucket_rows, "t5_mae_pct"),
                positive_t3_hit_count=_positive_hit_count(bucket_rows, "t3_return_pct"),
                positive_t3_hit_rate=_positive_hit_rate(bucket_rows, "t3_return_pct"),
            )
        )
    return items


def explode_eligibility_reason_rows(
    rows: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    exploded: list[dict[str, object]] = []
    for row in rows:
        reasons = row.get("eligibility_reasons") or []
        if not isinstance(reasons, Sequence) or isinstance(reasons, (str, bytes)):
            reasons = []
        if not reasons:
            exploded.append({**row, "eligibility_reason": "none"})
            continue
        for reason in reasons:
            exploded.append({**row, "eligibility_reason": str(reason)})
    return exploded


def build_watch_projection_shadow_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    annotated: list[dict[str, object]] = [{**row} for row in rows]
    for row in annotated:
        row["shadow_buy_topk"] = False
        row["shadow_watch_topk"] = False
        row["shadow_buy_rank"] = None
        row["shadow_watch_rank"] = None
        row["shadow_ranking_percentile"] = None
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in annotated:
        trade_date = str(row.get("trade_date") or "").strip() or "unknown"
        grouped[trade_date].append(row)

    for trade_date_rows in grouped.values():
        eligible_rows = [
            row
            for row in trade_date_rows
            if _is_shadow_watch_eligible(row)
        ]
        eligible_rows.sort(
            key=lambda row: (
                -(_coerce_float(row.get("ranking_score")) or -999.0),
                -(_coerce_float(row.get("entry_score")) or -999.0),
                str(row.get("symbol") or ""),
            )
        )
        total = len(eligible_rows)
        buy_keys: set[tuple[str, str]] = set()
        buy_rank = 0
        for row in eligible_rows:
            ranking_score = _coerce_float(row.get("ranking_score"))
            if ranking_score is None or ranking_score < BUY_MIN_RANKING_SCORE:
                continue
            buy_rank += 1
            key = _symbol_day_key(row)
            row["shadow_buy_rank"] = buy_rank
            row["shadow_ranking_percentile"] = _descending_percentile(buy_rank, total)
            if buy_rank <= WATCH_TOP_K_BUY:
                buy_keys.add(key)
                row["shadow_buy_topk"] = True
            else:
                row["shadow_buy_topk"] = False

        watch_rank = 0
        for absolute_rank, row in enumerate(eligible_rows, start=1):
            key = _symbol_day_key(row)
            if row.get("shadow_ranking_percentile") is None:
                row["shadow_ranking_percentile"] = _descending_percentile(absolute_rank, total)
            if key in buy_keys:
                row["shadow_watch_topk"] = False
                continue
            ranking_score = _coerce_float(row.get("ranking_score"))
            entry_score = _coerce_float(row.get("entry_score"))
            percentile = _coerce_float(row.get("shadow_ranking_percentile"))
            if (
                ranking_score is None
                or entry_score is None
                or percentile is None
                or ranking_score < WATCH_MIN_RANKING_SCORE
                or entry_score < WATCH_MIN_ENTRY_SCORE
                or percentile < WATCH_MIN_PERCENTILE
            ):
                row["shadow_watch_topk"] = False
                continue
            watch_rank += 1
            row["shadow_watch_rank"] = watch_rank
            row["shadow_watch_topk"] = watch_rank <= WATCH_TOP_K_WATCH

    for row in annotated:
        legacy_watch = bool(row.get("watch_candidate"))
        shadow_watch = bool(row.get("shadow_watch_topk"))
        if legacy_watch and shadow_watch:
            bucket = "legacy_and_shadow_watch"
        elif legacy_watch:
            bucket = "legacy_watch_only"
        elif shadow_watch:
            bucket = "shadow_watch_only"
        else:
            bucket = "neither_watch"
        row["watch_projection_bucket"] = bucket
    return annotated


def build_shadow_experiment_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    experiment_key: str,
    bucket_key: str,
) -> list[dict[str, object]]:
    annotated: list[dict[str, object]] = []
    for row in rows:
        experiment = row.get(experiment_key)
        payload = experiment if isinstance(experiment, Mapping) else {}
        active = bool(payload.get("active"))
        would_pass = bool(payload.get("shadow_would_pass"))
        if not active:
            bucket = "inactive"
        elif would_pass:
            bucket = "shadow_would_pass"
        else:
            bucket = "shadow_blocked"
        annotated.append(
            {
                **row,
                bucket_key: bucket,
            }
        )
    return annotated


def build_core_risk_off_topk_projection_rows(
    rows: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    annotated: list[dict[str, object]] = []
    for row in rows:
        experiment = row.get("core_risk_off_experiment")
        payload = experiment if isinstance(experiment, Mapping) else {}
        active = bool(payload.get("active"))
        candidate = bool(payload.get("shadow_topk_candidate"))
        selected = bool(payload.get("shadow_topk_selected"))
        if not active:
            bucket = "inactive"
        elif selected:
            bucket = "shadow_topk_selected"
        elif candidate:
            bucket = "shadow_topk_candidate_only"
        else:
            bucket = "shadow_not_candidate"
        annotated.append(
            {
                **row,
                "core_risk_off_topk_bucket": bucket,
            }
        )
    return annotated


def build_core_risk_off_floor_bucket_rows(
    rows: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    annotated: list[dict[str, object]] = []
    for row in rows:
        experiment = row.get("core_risk_off_experiment")
        payload = experiment if isinstance(experiment, Mapping) else {}
        active = bool(payload.get("active"))
        if not active:
            bucket = "inactive"
        else:
            bucket = str(payload.get("shadow_floor_bucket") or "unknown").strip() or "unknown"
        annotated.append(
            {
                **row,
                "core_risk_off_floor_bucket": bucket,
            }
        )
    return annotated


def build_core_risk_off_floor_v2_bucket_rows(
    rows: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    annotated: list[dict[str, object]] = []
    for row in rows:
        experiment = row.get("core_risk_off_experiment")
        payload = experiment if isinstance(experiment, Mapping) else {}
        active = bool(payload.get("active"))
        if not active:
            bucket = "inactive"
        else:
            bucket = _resolve_shadow_floor_bucket(
                payload,
                bucket_field="shadow_floor_relax_v2_bucket",
                mild_overall_min=-0.15,
                mild_slow_min=-0.15,
                moderate_overall_min=-0.20,
                moderate_slow_min=-0.25,
                reason_prefix="shadow_core_risk_off_floor_v2",
            )
        annotated.append(
            {
                **row,
                "core_risk_off_floor_v2_bucket": bucket,
            }
        )
    return annotated


def build_core_risk_off_floor_v3_bucket_rows(
    rows: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    annotated: list[dict[str, object]] = []
    for row in rows:
        experiment = row.get("core_risk_off_experiment")
        payload = experiment if isinstance(experiment, Mapping) else {}
        active = bool(payload.get("active"))
        if not active:
            bucket = "inactive"
        else:
            bucket = _resolve_shadow_floor_bucket(
                payload,
                bucket_field="shadow_floor_relax_v3_bucket",
                mild_overall_min=-0.20,
                mild_slow_min=-0.15,
                moderate_overall_min=-0.25,
                moderate_slow_min=-0.25,
                reason_prefix="shadow_core_risk_off_floor_v3",
            )
        annotated.append({**row, "core_risk_off_floor_v3_bucket": bucket})
    return annotated


def build_core_risk_off_floor_v5_bucket_rows(
    rows: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    annotated: list[dict[str, object]] = []
    for row in rows:
        experiment = row.get("core_risk_off_experiment")
        payload = experiment if isinstance(experiment, Mapping) else {}
        active = bool(payload.get("active"))
        if not active:
            bucket = "inactive"
        else:
            bucket = _resolve_shadow_floor_bucket(
                payload,
                bucket_field="shadow_floor_relax_v5_bucket",
                overall_field="shadow_overall_score_v5",
                slow_field="shadow_slow_score_v5",
                mild_overall_min=-0.20,
                mild_slow_min=-0.15,
                moderate_overall_min=-0.25,
                moderate_slow_min=-0.25,
                reason_prefix="shadow_core_risk_off_floor_v5",
            )
        annotated.append({**row, "core_risk_off_floor_v5_bucket": bucket})
    return annotated


def build_core_risk_off_floor_report(
    rows: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    annotated = build_core_risk_off_floor_bucket_rows(rows)
    aggregate_items = build_trigger_proxy_aggregate_items(
        annotated,
        bucket_key="core_risk_off_floor_bucket",
    )
    by_bucket = {str(item.bucket): item for item in aggregate_items}
    report_items: list[dict[str, object]] = []
    for bucket in CORE_RISK_OFF_FLOOR_REPORT_BUCKETS:
        item = by_bucket.get(bucket)
        report_items.append(
            {
                "bucket": bucket,
                "sample_count": int(item.sample_count) if item is not None else 0,
                "t1_return_pct_avg": item.t1_return_pct_avg if item is not None else None,
                "t3_return_pct_avg": item.t3_return_pct_avg if item is not None else None,
                "t5_return_pct_avg": item.t5_return_pct_avg if item is not None else None,
                "positive_t3_hit_rate": (
                    item.positive_t3_hit_rate if item is not None else None
                ),
            }
        )

    active_rows = [
        row
        for row in annotated
        if str(row.get("core_risk_off_floor_bucket") or "") != "inactive"
    ]
    return {
        "bucket_order": list(CORE_RISK_OFF_FLOOR_REPORT_BUCKETS),
        "items": report_items,
        "active_sample_count": len(active_rows),
        "non_inactive_bucket_count": sum(
            1
            for item in report_items
            if item["bucket"] != "inactive" and int(item["sample_count"]) > 0
        ),
        "proxy_availability": {
            "t1_ready_count": sum(
                1 for row in active_rows if _coerce_float(row.get("t1_return_pct")) is not None
            ),
            "t3_ready_count": sum(
                1 for row in active_rows if _coerce_float(row.get("t3_return_pct")) is not None
            ),
            "t5_ready_count": sum(
                1 for row in active_rows if _coerce_float(row.get("t5_return_pct")) is not None
            ),
        },
    }


def build_core_risk_off_floor_v2_report(
    rows: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    annotated = build_core_risk_off_floor_v2_bucket_rows(rows)
    aggregate_items = build_trigger_proxy_aggregate_items(
        annotated,
        bucket_key="core_risk_off_floor_v2_bucket",
    )
    by_bucket = {str(item.bucket): item for item in aggregate_items}
    report_items: list[dict[str, object]] = []
    for bucket in CORE_RISK_OFF_FLOOR_V2_REPORT_BUCKETS:
        item = by_bucket.get(bucket)
        report_items.append(
            {
                "bucket": bucket,
                "sample_count": int(item.sample_count) if item is not None else 0,
                "t1_return_pct_avg": item.t1_return_pct_avg if item is not None else None,
                "t3_return_pct_avg": item.t3_return_pct_avg if item is not None else None,
                "t5_return_pct_avg": item.t5_return_pct_avg if item is not None else None,
                "positive_t3_hit_rate": (
                    item.positive_t3_hit_rate if item is not None else None
                ),
            }
        )

    active_rows = [
        row
        for row in annotated
        if str(row.get("core_risk_off_floor_v2_bucket") or "") != "inactive"
    ]
    return {
        "bucket_order": list(CORE_RISK_OFF_FLOOR_V2_REPORT_BUCKETS),
        "items": report_items,
        "active_sample_count": len(active_rows),
        "non_inactive_bucket_count": sum(
            1
            for item in report_items
            if item["bucket"] != "inactive" and int(item["sample_count"]) > 0
        ),
        "proxy_availability": {
            "t1_ready_count": sum(
                1 for row in active_rows if _coerce_float(row.get("t1_return_pct")) is not None
            ),
            "t3_ready_count": sum(
                1 for row in active_rows if _coerce_float(row.get("t3_return_pct")) is not None
            ),
            "t5_ready_count": sum(
                1 for row in active_rows if _coerce_float(row.get("t5_return_pct")) is not None
            ),
        },
    }


def build_core_risk_off_floor_v3_report(
    rows: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    annotated = build_core_risk_off_floor_v3_bucket_rows(rows)
    aggregate_items = build_trigger_proxy_aggregate_items(
        annotated,
        bucket_key="core_risk_off_floor_v3_bucket",
    )
    by_bucket = {str(item.bucket): item for item in aggregate_items}
    report_items: list[dict[str, object]] = []
    for bucket in CORE_RISK_OFF_FLOOR_V3_REPORT_BUCKETS:
        item = by_bucket.get(bucket)
        report_items.append(
            {
                "bucket": bucket,
                "sample_count": int(item.sample_count) if item is not None else 0,
                "t1_return_pct_avg": item.t1_return_pct_avg if item is not None else None,
                "t3_return_pct_avg": item.t3_return_pct_avg if item is not None else None,
                "t5_return_pct_avg": item.t5_return_pct_avg if item is not None else None,
                "positive_t3_hit_rate": (
                    item.positive_t3_hit_rate if item is not None else None
                ),
            }
        )
    active_rows = [
        row
        for row in annotated
        if str(row.get("core_risk_off_floor_v3_bucket") or "") != "inactive"
    ]
    return {
        "bucket_order": list(CORE_RISK_OFF_FLOOR_V3_REPORT_BUCKETS),
        "items": report_items,
        "active_sample_count": len(active_rows),
        "non_inactive_bucket_count": sum(
            1
            for item in report_items
            if item["bucket"] != "inactive" and int(item["sample_count"]) > 0
        ),
        "proxy_availability": {
            "t1_ready_count": sum(
                1 for row in active_rows if _coerce_float(row.get("t1_return_pct")) is not None
            ),
            "t3_ready_count": sum(
                1 for row in active_rows if _coerce_float(row.get("t3_return_pct")) is not None
            ),
            "t5_ready_count": sum(
                1 for row in active_rows if _coerce_float(row.get("t5_return_pct")) is not None
            ),
        },
    }


def build_core_risk_off_floor_v5_report(
    rows: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    annotated = build_core_risk_off_floor_v5_bucket_rows(rows)
    aggregate_items = build_trigger_proxy_aggregate_items(
        annotated,
        bucket_key="core_risk_off_floor_v5_bucket",
    )
    by_bucket = {str(item.bucket): item for item in aggregate_items}
    report_items: list[dict[str, object]] = []
    for bucket in CORE_RISK_OFF_FLOOR_V5_REPORT_BUCKETS:
        item = by_bucket.get(bucket)
        report_items.append(
            {
                "bucket": bucket,
                "sample_count": int(item.sample_count) if item is not None else 0,
                "t1_return_pct_avg": item.t1_return_pct_avg if item is not None else None,
                "t3_return_pct_avg": item.t3_return_pct_avg if item is not None else None,
                "t5_return_pct_avg": item.t5_return_pct_avg if item is not None else None,
                "positive_t3_hit_rate": (
                    item.positive_t3_hit_rate if item is not None else None
                ),
            }
        )
    active_rows = [
        row
        for row in annotated
        if str(row.get("core_risk_off_floor_v5_bucket") or "") != "inactive"
    ]
    return {
        "bucket_order": list(CORE_RISK_OFF_FLOOR_V5_REPORT_BUCKETS),
        "items": report_items,
        "active_sample_count": len(active_rows),
        "non_inactive_bucket_count": sum(
            1
            for item in report_items
            if item["bucket"] != "inactive" and int(item["sample_count"]) > 0
        ),
        "proxy_availability": {
            "t1_ready_count": sum(
                1 for row in active_rows if _coerce_float(row.get("t1_return_pct")) is not None
            ),
            "t3_ready_count": sum(
                1 for row in active_rows if _coerce_float(row.get("t3_return_pct")) is not None
            ),
            "t5_ready_count": sum(
                1 for row in active_rows if _coerce_float(row.get("t5_return_pct")) is not None
            ),
        },
    }


def build_core_risk_off_floor_diagnostic_rows(
    rows: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    return _build_core_risk_off_floor_diagnostic_rows(
        rows,
        bucket_field="shadow_floor_bucket",
        output_bucket_key="core_risk_off_floor_bucket",
        mild_overall_min=-0.10,
        mild_slow_min=-0.15,
        moderate_overall_min=-0.25,
        moderate_slow_min=-0.25,
    )


def build_core_risk_off_floor_v2_diagnostic_rows(
    rows: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    return _build_core_risk_off_floor_diagnostic_rows(
        rows,
        bucket_field="shadow_floor_relax_v2_bucket",
        output_bucket_key="core_risk_off_floor_v2_bucket",
        mild_overall_min=-0.15,
        mild_slow_min=-0.15,
        moderate_overall_min=-0.20,
        moderate_slow_min=-0.25,
    )


def build_core_risk_off_floor_v3_diagnostic_rows(
    rows: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    return _build_core_risk_off_floor_diagnostic_rows(
        rows,
        bucket_field="shadow_floor_relax_v3_bucket",
        output_bucket_key="core_risk_off_floor_v3_bucket",
        mild_overall_min=-0.20,
        mild_slow_min=-0.15,
        moderate_overall_min=-0.25,
        moderate_slow_min=-0.25,
    )


def build_core_risk_off_floor_v5_diagnostic_rows(
    rows: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    return _build_core_risk_off_floor_diagnostic_rows(
        rows,
        bucket_field="shadow_floor_relax_v5_bucket",
        output_bucket_key="core_risk_off_floor_v5_bucket",
        overall_field="shadow_overall_score_v5",
        slow_field="shadow_slow_score_v5",
        mild_overall_min=-0.20,
        mild_slow_min=-0.15,
        moderate_overall_min=-0.25,
        moderate_slow_min=-0.25,
    )


def _build_core_risk_off_floor_diagnostic_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    bucket_field: str,
    output_bucket_key: str,
    overall_field: str = "shadow_overall_score",
    slow_field: str = "shadow_slow_score",
    mild_overall_min: float,
    mild_slow_min: float,
    moderate_overall_min: float,
    moderate_slow_min: float,
) -> list[dict[str, object]]:
    annotated: list[dict[str, object]] = []
    for row in rows:
        experiment = row.get("core_risk_off_experiment")
        payload = experiment if isinstance(experiment, Mapping) else {}
        active = bool(payload.get("active"))
        shadow_floor_bucket = "inactive"
        if active:
            reason_prefix = "shadow_core_risk_off_floor"
            if bucket_field == "shadow_floor_relax_v2_bucket":
                reason_prefix = "shadow_core_risk_off_floor_v2"
            elif bucket_field == "shadow_floor_relax_v3_bucket":
                reason_prefix = "shadow_core_risk_off_floor_v3"
            elif bucket_field == "shadow_floor_relax_v5_bucket":
                reason_prefix = "shadow_core_risk_off_floor_v5"
            shadow_floor_bucket = _resolve_shadow_floor_bucket(
                payload,
                bucket_field=bucket_field,
                overall_field=overall_field,
                slow_field=slow_field,
                mild_overall_min=mild_overall_min,
                mild_slow_min=mild_slow_min,
                moderate_overall_min=moderate_overall_min,
                moderate_slow_min=moderate_slow_min,
                reason_prefix=reason_prefix,
            )
        shadow_overall_score = _coerce_float(payload.get(overall_field))
        shadow_slow_score = _coerce_float(payload.get(slow_field))
        shadow_entry_score = _coerce_float(payload.get("shadow_entry_score"))
        shadow_ranking_score = _coerce_float(
            payload.get("shadow_rank_candidate_score", payload.get("raw_ranking_score"))
        )
        shadow_overall_pass = bool(payload.get("shadow_overall_pass"))
        shadow_slow_pass = bool(payload.get("shadow_slow_pass"))
        shadow_signal_pass = bool(payload.get("shadow_signal_pass"))
        shadow_activity_pass = bool(payload.get("shadow_activity_pass"))
        shadow_strategy_pass = bool(payload.get("shadow_strategy_pass"))
        shadow_entry_observe_pass = bool(payload.get("shadow_entry_observe_pass"))
        shadow_topk_candidate = bool(payload.get("shadow_topk_candidate"))
        shadow_topk_selected = bool(payload.get("shadow_topk_selected"))
        shadow_component_scores_v5 = (
            dict(payload.get("shadow_component_scores_v5"))
            if isinstance(payload.get("shadow_component_scores_v5"), Mapping)
            else {}
        )
        shadow_reason_codes_v5 = payload.get("shadow_reason_codes_v5") or []
        if not isinstance(shadow_reason_codes_v5, Sequence) or isinstance(
            shadow_reason_codes_v5, (str, bytes)
        ):
            shadow_reason_codes_v5 = []
        shadow_slow_momentum_score = _coerce_float(
            shadow_component_scores_v5.get("slow_momentum")
        )
        shadow_slow_trend_score = _coerce_float(
            shadow_component_scores_v5.get("slow_trend")
        )
        price_vs_sma_60_pct = _coerce_float(row.get("price_vs_sma_60_pct"))
        return_3m_pct = _coerce_float(row.get("return_3m_pct"))
        final_decision_type = str(row.get("final_decision_type") or "").strip().lower()
        candidate_intent = str(row.get("candidate_intent") or "").strip().lower()
        primary_candidate = str(row.get("primary_candidate") or "").strip().lower()
        buy_candidate = bool(row.get("buy_candidate"))
        order_request_id = row.get("order_request_id")
        order_status = str(row.get("order_status") or "").strip().lower()
        execution_status = str(row.get("execution_status") or "").strip().lower()
        execution_stop_reason = str(row.get("execution_stop_reason") or "").strip().lower()
        submission_accepted = bool(row.get("submission_accepted"))
        submission_error_type = str(row.get("submission_error_type") or "").strip().lower()
        trigger_reason_codes = row.get("trigger_reason_codes") or []
        if not isinstance(trigger_reason_codes, Sequence) or isinstance(
            trigger_reason_codes, (str, bytes)
        ):
            trigger_reason_codes = []
        normalized_trigger_reason_codes = tuple(
            str(code).strip().lower()
            for code in trigger_reason_codes
            if str(code).strip()
        )
        overall_band = _classify_overall_band(shadow_overall_score)
        slow_band = _classify_slow_band(shadow_slow_score)
        slow_relax_candidate_band = _classify_slow_relax_candidate_band(
            shadow_slow_score
        )
        slow_momentum_band = _classify_slow_component_band(shadow_slow_momentum_score)
        slow_trend_band = _classify_slow_component_band(shadow_slow_trend_score)
        slow_trend_relax_candidate_band = _classify_slow_trend_relax_candidate_band(
            price_vs_sma_60_pct
        )
        moderate_gate_bucket = _classify_core_risk_off_moderate_gate(
            active=active,
            overall=shadow_overall_score,
            slow=shadow_slow_score,
            entry_score=shadow_entry_score,
            ranking_score=shadow_ranking_score,
            shadow_activity_pass=shadow_activity_pass,
            shadow_strategy_pass=shadow_strategy_pass,
            moderate_overall_min=moderate_overall_min,
            moderate_slow_min=moderate_slow_min,
        )
        blocking_reason = _classify_core_risk_off_blocking_reason(
            active=active,
            shadow_floor_bucket=shadow_floor_bucket,
            overall=shadow_overall_score,
            slow=shadow_slow_score,
            entry_score=shadow_entry_score,
            ranking_score=shadow_ranking_score,
            shadow_activity_pass=shadow_activity_pass,
            shadow_strategy_pass=shadow_strategy_pass,
            mild_overall_min=mild_overall_min,
            mild_slow_min=mild_slow_min,
        )
        projection_candidate = _is_shadow_relax_projection_candidate(
            active=active,
            shadow_floor_bucket=shadow_floor_bucket,
            slow_trend_relax_candidate_band=slow_trend_relax_candidate_band,
            slow_momentum_band=slow_momentum_band,
        )
        projection_selected = projection_candidate and shadow_topk_selected
        projection_buy_shape = _is_shadow_relax_projection_buy_shape(
            primary_candidate=primary_candidate,
            candidate_intent=candidate_intent,
            final_decision_type=final_decision_type,
        )
        actual_submitted = _is_projection_submitted(
            order_request_id=order_request_id,
            order_status=order_status,
            execution_status=execution_status,
            submission_accepted=submission_accepted,
        )
        projection_would_buy = projection_selected and projection_buy_shape
        projection_submitted = projection_would_buy and actual_submitted
        projection_block_reason = _classify_shadow_relax_projection_block_reason(
            active=active,
            shadow_floor_bucket=shadow_floor_bucket,
            slow_trend_relax_candidate_band=slow_trend_relax_candidate_band,
            slow_momentum_band=slow_momentum_band,
            shadow_topk_candidate=shadow_topk_candidate,
            shadow_topk_selected=shadow_topk_selected,
            projection_buy_shape=projection_buy_shape,
            order_request_id=order_request_id,
            order_status=order_status,
            execution_status=execution_status,
            execution_stop_reason=execution_stop_reason,
            submission_accepted=submission_accepted,
            submission_error_type=submission_error_type,
        )
        shadow_topk_candidate_gate_reason = _classify_shadow_topk_candidate_gate_reason(
            active=active,
            shadow_topk_candidate=shadow_topk_candidate,
            shadow_overall_pass=shadow_overall_pass,
            shadow_slow_pass=shadow_slow_pass,
            shadow_activity_pass=shadow_activity_pass,
            shadow_strategy_pass=shadow_strategy_pass,
            shadow_ranking_score=shadow_ranking_score,
            payload=payload,
        )
        eligibility_block_reason_primary = _classify_primary_eligibility_block_reason(
            row.get("eligibility_reasons") or [],
            eligibility_passed=bool(row.get("eligibility_passed")),
            shadow_activity_pass=shadow_activity_pass,
            shadow_strategy_pass=shadow_strategy_pass,
            shadow_overall_score=shadow_overall_score,
            shadow_slow_score=shadow_slow_score,
            shadow_ranking_score=shadow_ranking_score,
            payload=payload,
        )
        watch_primary_candidate_reason = _classify_watch_primary_candidate_reason(
            primary_candidate=primary_candidate,
            buy_candidate=buy_candidate,
            eligibility_passed=bool(row.get("eligibility_passed")),
            entry_score=shadow_entry_score,
            watch_score=_coerce_float(row.get("watch_score")),
            trigger_reason_codes=normalized_trigger_reason_codes,
        )
        deterministic_buy_shape_block_reason = _classify_deterministic_buy_shape_block_reason(
            primary_candidate=primary_candidate,
            buy_candidate=buy_candidate,
            eligibility_passed=bool(row.get("eligibility_passed")),
            entry_score=shadow_entry_score,
            watch_score=_coerce_float(row.get("watch_score")),
            ranking_score=shadow_ranking_score,
            trigger_reason_codes=normalized_trigger_reason_codes,
        )
        shadow_signal_floor_block_path = _classify_shadow_signal_floor_block_path(
            active=active,
            shadow_topk_candidate_gate_reason=shadow_topk_candidate_gate_reason,
            shadow_overall_pass=shadow_overall_pass,
            shadow_slow_pass=shadow_slow_pass,
            overall_band=overall_band,
            slow_band=slow_band,
            slow_momentum_band=slow_momentum_band,
            slow_trend_band=slow_trend_band,
        )
        shadow_signal_floor_miss_detail = _classify_shadow_signal_floor_miss_detail(
            active=active,
            shadow_topk_candidate_gate_reason=shadow_topk_candidate_gate_reason,
            shadow_overall_score=shadow_overall_score,
            shadow_slow_score=shadow_slow_score,
        )
        slow_floor_shadow_relax_path = _classify_slow_floor_shadow_relax_path(
            active=active,
            slow_trend_relax_candidate_band=slow_trend_relax_candidate_band,
            shadow_signal_floor_miss_detail=shadow_signal_floor_miss_detail,
            shadow_activity_pass=shadow_activity_pass,
            shadow_strategy_pass=shadow_strategy_pass,
            shadow_ranking_score=shadow_ranking_score,
        )
        slow_floor_relax_transition_stage = _classify_slow_floor_relax_transition_stage(
            slow_floor_shadow_relax_path=slow_floor_shadow_relax_path,
            projection_buy_shape=projection_buy_shape,
            shadow_topk_candidate=shadow_topk_candidate,
            shadow_topk_selected=shadow_topk_selected,
            projection_would_buy=projection_would_buy,
            projection_submitted=projection_submitted,
            watch_primary_candidate_reason=watch_primary_candidate_reason,
        )
        limited_slow_floor_shadow_path = _classify_limited_slow_floor_shadow_path(
            active=active,
            compound_bucket=f"{watch_primary_candidate_reason}|{deterministic_buy_shape_block_reason}",
            slow_trend_relax_candidate_band=slow_trend_relax_candidate_band,
            shadow_signal_floor_miss_detail=shadow_signal_floor_miss_detail,
            shadow_activity_pass=shadow_activity_pass,
            shadow_strategy_pass=shadow_strategy_pass,
            shadow_ranking_score=shadow_ranking_score,
        )
        limited_slow_floor_candidate_ready = (
            limited_slow_floor_shadow_path == "candidate_ready"
        )
        limited_slow_floor_would_buy = (
            limited_slow_floor_candidate_ready and projection_buy_shape
        )
        limited_slow_floor_transition_stage = _classify_limited_slow_floor_transition_stage(
            limited_slow_floor_shadow_path=limited_slow_floor_shadow_path,
            projection_buy_shape=projection_buy_shape,
            watch_primary_candidate_reason=watch_primary_candidate_reason,
            deterministic_buy_shape_block_reason=deterministic_buy_shape_block_reason,
        )
        buy_candidate_threshold_gap = _positive_gap(
            BUY_CANDIDATE_THRESHOLD,
            shadow_entry_score,
        )
        effective_entry_score = shadow_entry_score
        if effective_entry_score is None:
            effective_entry_score = _coerce_float(row.get("entry_score"))
        effective_ranking_score = shadow_ranking_score
        if effective_ranking_score is None:
            effective_ranking_score = _coerce_float(row.get("ranking_score"))
        effective_buy_candidate_threshold_gap = _positive_gap(
            BUY_CANDIDATE_THRESHOLD,
            effective_entry_score,
        )
        effective_buy_candidate_threshold_gap_band = _classify_buy_candidate_threshold_gap_band(
            buy_candidate_threshold_gap=effective_buy_candidate_threshold_gap,
        )
        effective_buy_ranking_gap = _positive_gap(
            BUY_MIN_RANKING_SCORE,
            effective_ranking_score,
        )
        effective_buy_ranking_gap_band = _classify_effective_ranking_gap_band(
            ranking_gap=effective_buy_ranking_gap,
        )
        effective_entry_score_band = _classify_effective_entry_score_band(
            effective_entry_score,
        )
        pre_buy_staging_cohort = _classify_pre_buy_staging_cohort(
            source_type=str(row.get("source_type") or "").strip().lower(),
            watch_primary_candidate_reason=watch_primary_candidate_reason,
            effective_entry_score=effective_entry_score,
        )
        pre_buy_staging_activity_gate = _classify_pre_buy_staging_activity_gate(
            pre_buy_staging_cohort=pre_buy_staging_cohort,
            eligibility_block_reason_primary=eligibility_block_reason_primary,
            shadow_activity_pass=shadow_activity_pass,
        )
        average_volume_20d = _coerce_float(row.get("average_volume_20d"))
        average_turnover_20d = _coerce_float(row.get("average_turnover_20d"))
        volume_surge_ratio = _coerce_float(row.get("volume_surge_ratio"))
        turnover_surge_ratio = _coerce_float(row.get("turnover_surge_ratio"))
        recommended_max_order_value = _coerce_float(
            row.get("recommended_max_order_value")
        )
        activity_participation_rate = None
        if (
            average_turnover_20d is not None
            and average_turnover_20d > 0
            and recommended_max_order_value is not None
            and recommended_max_order_value > 0
        ):
            activity_participation_rate = (
                recommended_max_order_value / average_turnover_20d
            )
        pre_buy_staging_activity_detail = _classify_pre_buy_staging_activity_detail(
            pre_buy_staging_activity_gate=pre_buy_staging_activity_gate,
            average_volume_20d=average_volume_20d,
            average_turnover_20d=average_turnover_20d,
            volume_surge_ratio=volume_surge_ratio,
            turnover_surge_ratio=turnover_surge_ratio,
            activity_participation_rate=activity_participation_rate,
        )
        pre_buy_boundary_first_order_bottleneck = (
            _classify_pre_buy_boundary_first_order_bottleneck(
                pre_buy_staging_activity_detail=pre_buy_staging_activity_detail,
                pre_buy_staging_activity_gate=pre_buy_staging_activity_gate,
                effective_buy_candidate_threshold_gap_band=effective_buy_candidate_threshold_gap_band,
                effective_buy_ranking_gap_band=effective_buy_ranking_gap_band,
            )
        )
        pre_buy_boundary_activity_counterfactual_next_gate = (
            _classify_pre_buy_boundary_activity_counterfactual_next_gate(
                pre_buy_staging_activity_detail=pre_buy_staging_activity_detail,
                pre_buy_staging_activity_gate=pre_buy_staging_activity_gate,
                shadow_signal_pass=shadow_signal_pass,
                effective_buy_candidate_threshold_gap_band=effective_buy_candidate_threshold_gap_band,
                effective_buy_ranking_gap_band=effective_buy_ranking_gap_band,
                shadow_strategy_pass=shadow_strategy_pass,
                shadow_topk_candidate=shadow_topk_candidate,
                shadow_topk_selected=shadow_topk_selected,
                projection_buy_shape=projection_buy_shape,
                projection_submitted=projection_submitted,
            )
        )
        pre_buy_boundary_activity_buy_shape_detail = (
            _classify_pre_buy_boundary_activity_buy_shape_detail(
                pre_buy_boundary_activity_counterfactual_next_gate=pre_buy_boundary_activity_counterfactual_next_gate,
                deterministic_buy_shape_block_reason=deterministic_buy_shape_block_reason,
                effective_buy_candidate_threshold_gap_band=effective_buy_candidate_threshold_gap_band,
            )
        )
        watch_candidate_threshold_gap = _positive_gap(
            WATCH_CANDIDATE_THRESHOLD,
            _coerce_float(row.get("watch_score")),
        )
        core_risk_off_ranking_min_gap = _positive_gap(
            CORE_RISK_OFF_RANKING_MIN_SCORE,
            shadow_ranking_score,
        )
        shadow_topk_ranking_min_gap = _positive_gap(
            CORE_RISK_OFF_SHADOW_MIN_SCORE,
            shadow_ranking_score,
        )
        watch_only_core_path_shadow_reason = _classify_watch_only_core_path_shadow_reason(
            limited_slow_floor_transition_stage=limited_slow_floor_transition_stage,
            deterministic_buy_shape_block_reason=deterministic_buy_shape_block_reason,
            buy_candidate_threshold_gap=buy_candidate_threshold_gap,
            watch_candidate_threshold_gap=watch_candidate_threshold_gap,
            core_risk_off_ranking_min_gap=core_risk_off_ranking_min_gap,
        )
        buy_candidate_threshold_gap_band = _classify_buy_candidate_threshold_gap_band(
            buy_candidate_threshold_gap=buy_candidate_threshold_gap,
        )
        watch_only_core_path_entry_gap_band = _classify_watch_only_core_path_entry_gap_band(
            limited_slow_floor_transition_stage=limited_slow_floor_transition_stage,
            buy_candidate_threshold_gap=buy_candidate_threshold_gap,
        )
        authoritative_buy_path = _is_authoritative_buy_path(
            primary_candidate=primary_candidate,
            candidate_intent=candidate_intent,
            buy_candidate=buy_candidate,
            final_decision_type=final_decision_type,
        )
        authoritative_submitted_path = authoritative_buy_path and actual_submitted
        momentum_reason_codes = tuple(
            str(code).strip().lower()
            for code in shadow_reason_codes_v5
            if str(code).strip().lower().startswith("momentum_")
        )
        annotated.append(
            {
                **row,
                "core_risk_off_active": active,
                output_bucket_key: shadow_floor_bucket,
                "shadow_floor_bucket": shadow_floor_bucket,
                "shadow_floor_bucket_field": bucket_field,
                "shadow_overall_score": shadow_overall_score,
                "shadow_slow_score": shadow_slow_score,
                "shadow_entry_score": shadow_entry_score,
                "shadow_ranking_score": shadow_ranking_score,
                "shadow_overall_pass": shadow_overall_pass,
                "shadow_slow_pass": shadow_slow_pass,
                "shadow_signal_pass": shadow_signal_pass,
                "shadow_activity_pass": shadow_activity_pass,
                "shadow_strategy_pass": shadow_strategy_pass,
                "shadow_entry_observe_pass": shadow_entry_observe_pass,
                "shadow_topk_candidate": shadow_topk_candidate,
                "shadow_topk_selected": shadow_topk_selected,
                "shadow_slow_momentum_score": shadow_slow_momentum_score,
                "shadow_slow_trend_score": shadow_slow_trend_score,
                "price_vs_sma_60_pct": price_vs_sma_60_pct,
                "return_3m_pct": return_3m_pct,
                "average_volume_20d": average_volume_20d,
                "average_turnover_20d": average_turnover_20d,
                "volume_surge_ratio": volume_surge_ratio,
                "turnover_surge_ratio": turnover_surge_ratio,
                "recommended_max_order_value": recommended_max_order_value,
                "activity_participation_rate": activity_participation_rate,
                "overall_band": overall_band,
                "slow_band": slow_band,
                "slow_relax_candidate_band": slow_relax_candidate_band,
                "slow_momentum_band": slow_momentum_band,
                "slow_trend_band": slow_trend_band,
                "slow_trend_relax_candidate_band": slow_trend_relax_candidate_band,
                "slow_component_path": f"{slow_momentum_band}|{slow_trend_band}",
                "slow_trend_path": (
                    f"{slow_trend_relax_candidate_band}|{slow_trend_band}"
                ),
                "moderate_gate_bucket": moderate_gate_bucket,
                "blocking_reason": blocking_reason,
                "shadow_relax_projection_candidate": projection_candidate,
                "shadow_relax_projection_selected": projection_selected,
                "shadow_relax_projection_would_buy": projection_would_buy,
                "shadow_relax_projection_submitted": projection_submitted,
                "shadow_relax_projection_block_reason": projection_block_reason,
                "shadow_relax_projection_path": (
                    f"{slow_trend_relax_candidate_band}|"
                    f"{slow_momentum_band}|"
                    f"{projection_block_reason}"
                ),
                "projection_buy_shape": projection_buy_shape,
                "actual_submitted": actual_submitted,
                "shadow_topk_candidate_gate_reason": shadow_topk_candidate_gate_reason,
                "eligibility_block_reason_primary": eligibility_block_reason_primary,
                "watch_primary_candidate_reason": watch_primary_candidate_reason,
                "deterministic_buy_shape_block_reason": deterministic_buy_shape_block_reason,
                "buy_candidate_threshold_gap": buy_candidate_threshold_gap,
                "buy_candidate_threshold_gap_band": buy_candidate_threshold_gap_band,
                "effective_entry_score": effective_entry_score,
                "effective_entry_score_band": effective_entry_score_band,
                "effective_ranking_score": effective_ranking_score,
                "effective_buy_candidate_threshold_gap": effective_buy_candidate_threshold_gap,
                "effective_buy_candidate_threshold_gap_band": effective_buy_candidate_threshold_gap_band,
                "effective_buy_ranking_gap": effective_buy_ranking_gap,
                "effective_buy_ranking_gap_band": effective_buy_ranking_gap_band,
                "pre_buy_staging_cohort": pre_buy_staging_cohort,
                "pre_buy_staging_activity_gate": pre_buy_staging_activity_gate,
                "pre_buy_staging_activity_detail": pre_buy_staging_activity_detail,
                "pre_buy_boundary_first_order_bottleneck": pre_buy_boundary_first_order_bottleneck,
                "pre_buy_boundary_activity_counterfactual_next_gate": pre_buy_boundary_activity_counterfactual_next_gate,
                "pre_buy_boundary_activity_buy_shape_detail": pre_buy_boundary_activity_buy_shape_detail,
                "watch_candidate_threshold_gap": watch_candidate_threshold_gap,
                "core_risk_off_ranking_min_gap": core_risk_off_ranking_min_gap,
                "shadow_topk_ranking_min_gap": shadow_topk_ranking_min_gap,
                "watch_only_core_path_shadow_reason": watch_only_core_path_shadow_reason,
                "watch_only_core_path_entry_gap_band": watch_only_core_path_entry_gap_band,
                "shadow_signal_floor_block_path": shadow_signal_floor_block_path,
                "shadow_signal_floor_miss_detail": shadow_signal_floor_miss_detail,
                "slow_floor_shadow_relax_path": slow_floor_shadow_relax_path,
                "slow_floor_relax_transition_stage": slow_floor_relax_transition_stage,
                "limited_slow_floor_shadow_path": limited_slow_floor_shadow_path,
                "limited_slow_floor_candidate_ready": limited_slow_floor_candidate_ready,
                "limited_slow_floor_would_buy": limited_slow_floor_would_buy,
                "limited_slow_floor_transition_stage": limited_slow_floor_transition_stage,
                "authoritative_buy_path": authoritative_buy_path,
                "authoritative_submitted_path": authoritative_submitted_path,
                "watch_eligibility_block_path": (
                    f"{watch_primary_candidate_reason}|{eligibility_block_reason_primary}"
                ),
                "momentum_reason_codes": momentum_reason_codes,
                "order_request_id": str(order_request_id) if order_request_id is not None else None,
                "order_status": order_status,
                "execution_status": execution_status,
                "execution_stop_reason": execution_stop_reason,
                "submission_accepted": submission_accepted,
                "submission_error_type": submission_error_type,
                "bucket_path": f"{overall_band}|{slow_band}|{moderate_gate_bucket}",
            }
        )
    return annotated


def build_core_risk_off_floor_diagnostics_report(
    rows: Iterable[Mapping[str, object]],
    *,
    sample_limit: int = 50,
) -> dict[str, object]:
    return _build_core_risk_off_floor_diagnostics_report(
        rows,
        sample_limit=sample_limit,
        bucket_key="core_risk_off_floor_bucket",
        bucket_field="shadow_floor_bucket",
        report_buckets=CORE_RISK_OFF_FLOOR_REPORT_BUCKETS,
        mild_overall_min=-0.10,
        mild_slow_min=-0.15,
        moderate_overall_min=-0.25,
        moderate_slow_min=-0.25,
    )


def build_core_risk_off_floor_v2_diagnostics_report(
    rows: Iterable[Mapping[str, object]],
    *,
    sample_limit: int = 50,
) -> dict[str, object]:
    return _build_core_risk_off_floor_diagnostics_report(
        rows,
        sample_limit=sample_limit,
        bucket_key="core_risk_off_floor_v2_bucket",
        bucket_field="shadow_floor_relax_v2_bucket",
        report_buckets=CORE_RISK_OFF_FLOOR_V2_REPORT_BUCKETS,
        mild_overall_min=-0.15,
        mild_slow_min=-0.15,
        moderate_overall_min=-0.20,
        moderate_slow_min=-0.25,
    )


def build_core_risk_off_floor_v3_diagnostics_report(
    rows: Iterable[Mapping[str, object]],
    *,
    sample_limit: int = 50,
) -> dict[str, object]:
    return _build_core_risk_off_floor_diagnostics_report(
        rows,
        sample_limit=sample_limit,
        bucket_key="core_risk_off_floor_v3_bucket",
        bucket_field="shadow_floor_relax_v3_bucket",
        report_buckets=CORE_RISK_OFF_FLOOR_V3_REPORT_BUCKETS,
        mild_overall_min=-0.20,
        mild_slow_min=-0.15,
        moderate_overall_min=-0.25,
        moderate_slow_min=-0.25,
    )


def build_core_risk_off_floor_v5_diagnostics_report(
    rows: Iterable[Mapping[str, object]],
    *,
    sample_limit: int = 50,
) -> dict[str, object]:
    return _build_core_risk_off_floor_diagnostics_report(
        rows,
        sample_limit=sample_limit,
        bucket_key="core_risk_off_floor_v5_bucket",
        bucket_field="shadow_floor_relax_v5_bucket",
        overall_field="shadow_overall_score_v5",
        slow_field="shadow_slow_score_v5",
        report_buckets=CORE_RISK_OFF_FLOOR_V5_REPORT_BUCKETS,
        mild_overall_min=-0.20,
        mild_slow_min=-0.15,
        moderate_overall_min=-0.25,
        moderate_slow_min=-0.25,
    )


def _build_core_risk_off_floor_diagnostics_report(
    rows: Iterable[Mapping[str, object]],
    *,
    sample_limit: int,
    bucket_key: str,
    bucket_field: str,
    overall_field: str = "shadow_overall_score",
    slow_field: str = "shadow_slow_score",
    report_buckets: Sequence[str],
    mild_overall_min: float,
    mild_slow_min: float,
    moderate_overall_min: float,
    moderate_slow_min: float,
) -> dict[str, object]:
    annotated = _build_core_risk_off_floor_diagnostic_rows(
        rows,
        bucket_field=bucket_field,
        output_bucket_key=bucket_key,
        overall_field=overall_field,
        slow_field=slow_field,
        mild_overall_min=mild_overall_min,
        mild_slow_min=mild_slow_min,
        moderate_overall_min=moderate_overall_min,
        moderate_slow_min=moderate_slow_min,
    )
    active_rows = [row for row in annotated if bool(row.get("core_risk_off_active"))]
    active_watch_reason_buy_shape_rows = _build_compound_bucket_rows(
        active_rows,
        first_key="watch_primary_candidate_reason",
        second_key="deterministic_buy_shape_block_reason",
    )
    active_transition_gap_rows = _build_compound_bucket_rows(
        active_rows,
        first_key="limited_slow_floor_transition_stage",
        second_key="buy_candidate_threshold_gap_band",
    )
    floor_items = build_trigger_proxy_aggregate_items(
        annotated,
        bucket_key=bucket_key,
    )
    floor_counts = {
        str(item.bucket): int(item.sample_count)
        for item in floor_items
    }
    return {
        "sample_count": len(annotated),
        "active_sample_count": len(active_rows),
        "bucket_counts": {
            bucket: int(floor_counts.get(bucket, 0))
            for bucket in report_buckets
        },
        "overall_band_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    annotated,
                    bucket_key="overall_band",
                )
            )
        ],
        "slow_band_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    annotated,
                    bucket_key="slow_band",
                )
            )
        ],
        "slow_relax_candidate_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    annotated,
                    bucket_key="slow_relax_candidate_band",
                )
            )
        ],
        "slow_momentum_band_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    annotated,
                    bucket_key="slow_momentum_band",
                )
            )
        ],
        "slow_momentum_band_trade_date_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    _build_trade_date_bucket_rows(
                        annotated,
                        bucket_key="slow_momentum_band",
                    ),
                    bucket_key="trade_date_bucket",
                )
            )
        ],
        "slow_trend_band_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    annotated,
                    bucket_key="slow_trend_band",
                )
            )
        ],
        "momentum_reason_code_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    _explode_reason_code_rows(
                        annotated,
                        codes_key="momentum_reason_codes",
                        output_key="momentum_reason_code",
                    ),
                    bucket_key="momentum_reason_code",
                )
            )
        ],
        "slow_trend_relax_candidate_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    annotated,
                    bucket_key="slow_trend_relax_candidate_band",
                )
            )
        ],
        "slow_trend_relax_candidate_report": _build_band_report(
            annotated,
            bucket_key="slow_trend_relax_candidate_band",
            bucket_order=(
                "trend_strict_ready",
                "trend_mild_candidate",
                "trend_moderate_candidate",
                "trend_edge_deep",
                "trend_deep_tail",
                "missing",
            ),
        ),
        "active_slow_trend_relax_candidate_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    active_rows,
                    bucket_key="slow_trend_relax_candidate_band",
                )
            )
        ],
        "active_slow_trend_relax_candidate_report": _build_band_report(
            active_rows,
            bucket_key="slow_trend_relax_candidate_band",
            bucket_order=(
                "trend_strict_ready",
                "trend_mild_candidate",
                "trend_moderate_candidate",
                "trend_edge_deep",
                "trend_deep_tail",
                "missing",
            ),
        ),
        "active_slow_trend_projection_items": _build_projection_band_items(
            active_rows,
            bucket_key="slow_trend_relax_candidate_band",
            bucket_order=(
                "trend_strict_ready",
                "trend_mild_candidate",
                "trend_moderate_candidate",
                "trend_edge_deep",
                "trend_deep_tail",
                "missing",
            ),
        ),
        "active_slow_trend_trade_date_band_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    _build_trade_date_bucket_rows(
                        active_rows,
                        bucket_key="slow_trend_relax_candidate_band",
                    ),
                    bucket_key="trade_date_bucket",
                )
            )
        ],
        "active_slow_trend_trade_date_projection_items": _build_trade_date_projection_items(
            active_rows,
            bucket_key="slow_trend_relax_candidate_band",
        ),
        "active_watch_primary_candidate_reason_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    active_rows,
                    bucket_key="watch_primary_candidate_reason",
                )
            )
        ],
        "active_deterministic_buy_shape_block_reason_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    active_rows,
                    bucket_key="deterministic_buy_shape_block_reason",
                )
            )
        ],
        "active_watch_reason_buy_shape_matrix_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    active_watch_reason_buy_shape_rows,
                    bucket_key="compound_bucket",
                )
            )
        ],
        "active_watch_reason_projection_items": _build_projection_band_items(
            active_rows,
            bucket_key="watch_primary_candidate_reason",
            bucket_order=(
                "non_watch_primary",
                "watch_with_eligibility_block",
                "watch_setup_but_ineligible",
                "core_watch_path_only",
                "watch_from_entry_setup",
                "watch_below_buy_threshold",
                "watch_other",
                "missing",
            ),
        ),
        "active_buy_shape_projection_items": _build_projection_band_items(
            active_rows,
            bucket_key="deterministic_buy_shape_block_reason",
            bucket_order=(
                "buy_shape_ready",
                "non_watch_primary",
                "watch_from_exit_setup",
                "watch_from_entry_setup",
                "core_watch_gap_bridge",
                "watch_with_eligibility_block",
                "entry_below_buy_threshold",
                "watch_threshold_only",
                "ranking_below_buy_projection_threshold",
                "watch_other",
                "missing",
            ),
        ),
        "active_core_watch_exit_projection_block_reason_items": _build_filtered_bucket_items(
            active_watch_reason_buy_shape_rows,
            bucket_key="shadow_relax_projection_block_reason",
            filter_key="compound_bucket",
            filter_value="core_watch_path_only|watch_from_exit_setup",
        ),
        "active_core_watch_exit_gate_reason_items": _build_filtered_bucket_items(
            active_watch_reason_buy_shape_rows,
            bucket_key="shadow_topk_candidate_gate_reason",
            filter_key="compound_bucket",
            filter_value="core_watch_path_only|watch_from_exit_setup",
        ),
        "active_core_watch_exit_eligibility_block_reason_items": _build_filtered_bucket_items(
            active_watch_reason_buy_shape_rows,
            bucket_key="eligibility_block_reason_primary",
            filter_key="compound_bucket",
            filter_value="core_watch_path_only|watch_from_exit_setup",
        ),
        "active_core_watch_exit_trade_date_projection_items": _build_trade_date_filtered_projection_items(
            active_watch_reason_buy_shape_rows,
            filter_key="compound_bucket",
            filter_value="core_watch_path_only|watch_from_exit_setup",
        ),
        "active_core_watch_exit_samples": [
            row
            for row in active_watch_reason_buy_shape_rows
            if str(row.get("compound_bucket") or "") == "core_watch_path_only|watch_from_exit_setup"
        ][: max(0, int(sample_limit))],
        "active_core_watch_exit_trend_moderate_projection_block_reason_items": _build_filtered_bucket_items_multi(
            active_watch_reason_buy_shape_rows,
            bucket_key="shadow_relax_projection_block_reason",
            filters=(
                ("compound_bucket", "core_watch_path_only|watch_from_exit_setup"),
                ("slow_trend_relax_candidate_band", "trend_moderate_candidate"),
            ),
        ),
        "active_core_watch_exit_trend_moderate_gate_reason_items": _build_filtered_bucket_items_multi(
            active_watch_reason_buy_shape_rows,
            bucket_key="shadow_topk_candidate_gate_reason",
            filters=(
                ("compound_bucket", "core_watch_path_only|watch_from_exit_setup"),
                ("slow_trend_relax_candidate_band", "trend_moderate_candidate"),
            ),
        ),
        "active_core_watch_exit_trend_moderate_eligibility_block_reason_items": _build_filtered_bucket_items_multi(
            active_watch_reason_buy_shape_rows,
            bucket_key="eligibility_block_reason_primary",
            filters=(
                ("compound_bucket", "core_watch_path_only|watch_from_exit_setup"),
                ("slow_trend_relax_candidate_band", "trend_moderate_candidate"),
            ),
        ),
        "active_core_watch_exit_trend_moderate_slow_floor_shadow_relax_path_items": _build_filtered_bucket_items_multi(
            active_watch_reason_buy_shape_rows,
            bucket_key="slow_floor_shadow_relax_path",
            filters=(
                ("compound_bucket", "core_watch_path_only|watch_from_exit_setup"),
                ("slow_trend_relax_candidate_band", "trend_moderate_candidate"),
            ),
        ),
        "active_core_watch_exit_trend_moderate_limited_slow_floor_path_items": _build_filtered_bucket_items_multi(
            active_watch_reason_buy_shape_rows,
            bucket_key="limited_slow_floor_shadow_path",
            filters=(
                ("compound_bucket", "core_watch_path_only|watch_from_exit_setup"),
                ("slow_trend_relax_candidate_band", "trend_moderate_candidate"),
            ),
        ),
        "active_core_watch_exit_trend_moderate_limited_slow_floor_transition_stage_items": _build_filtered_bucket_items_multi(
            active_watch_reason_buy_shape_rows,
            bucket_key="limited_slow_floor_transition_stage",
            filters=(
                ("compound_bucket", "core_watch_path_only|watch_from_exit_setup"),
                ("slow_trend_relax_candidate_band", "trend_moderate_candidate"),
            ),
        ),
        "active_core_watch_exit_trend_moderate_buy_gap_band_items": _build_filtered_bucket_items_multi(
            active_watch_reason_buy_shape_rows,
            bucket_key="buy_candidate_threshold_gap_band",
            filters=(
                ("compound_bucket", "core_watch_path_only|watch_from_exit_setup"),
                ("slow_trend_relax_candidate_band", "trend_moderate_candidate"),
            ),
        ),
        "active_core_watch_exit_trend_moderate_transition_stage_buy_gap_band_items": _build_filtered_bucket_items_multi(
            active_transition_gap_rows,
            bucket_key="compound_bucket",
            filters=(
                ("watch_primary_candidate_reason", "core_watch_path_only"),
                ("deterministic_buy_shape_block_reason", "watch_from_exit_setup"),
                ("slow_trend_relax_candidate_band", "trend_moderate_candidate"),
            ),
        ),
        "active_core_watch_exit_trend_moderate_buy_gap_projection_items": _build_projection_band_items_filtered_multi(
            active_watch_reason_buy_shape_rows,
            bucket_key="buy_candidate_threshold_gap_band",
            bucket_order=(
                "large_entry_gap",
                "moderate_entry_gap",
                "small_entry_gap",
                "entry_ready",
                "buy_gap_missing",
            ),
            filters=(
                ("compound_bucket", "core_watch_path_only|watch_from_exit_setup"),
                ("slow_trend_relax_candidate_band", "trend_moderate_candidate"),
            ),
        ),
        "active_core_watch_exit_trend_moderate_trade_date_buy_gap_band_items": _build_trade_date_filtered_bucket_items_multi(
            active_watch_reason_buy_shape_rows,
            filters=(
                ("compound_bucket", "core_watch_path_only|watch_from_exit_setup"),
                ("slow_trend_relax_candidate_band", "trend_moderate_candidate"),
            ),
            bucket_key="buy_candidate_threshold_gap_band",
        ),
        "active_core_watch_exit_trend_moderate_watch_only_core_path_shadow_reason_items": _build_filtered_bucket_items_multi(
            active_watch_reason_buy_shape_rows,
            bucket_key="watch_only_core_path_shadow_reason",
            filters=(
                ("compound_bucket", "core_watch_path_only|watch_from_exit_setup"),
                ("slow_trend_relax_candidate_band", "trend_moderate_candidate"),
                ("limited_slow_floor_transition_stage", "candidate_ready_watch_only_core_path"),
            ),
        ),
        "active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_band_items": _build_filtered_bucket_items_multi(
            active_watch_reason_buy_shape_rows,
            bucket_key="watch_only_core_path_entry_gap_band",
            filters=(
                ("compound_bucket", "core_watch_path_only|watch_from_exit_setup"),
                ("slow_trend_relax_candidate_band", "trend_moderate_candidate"),
                ("limited_slow_floor_transition_stage", "candidate_ready_watch_only_core_path"),
            ),
        ),
        "active_core_watch_exit_trend_moderate_watch_only_core_path_entry_gap_projection_items": _build_projection_band_items_filtered_multi(
            active_watch_reason_buy_shape_rows,
            bucket_key="watch_only_core_path_entry_gap_band",
            bucket_order=(
                "large_entry_gap",
                "moderate_entry_gap",
                "small_entry_gap",
                "entry_ready",
                "buy_gap_missing",
            ),
            filters=(
                ("compound_bucket", "core_watch_path_only|watch_from_exit_setup"),
                ("slow_trend_relax_candidate_band", "trend_moderate_candidate"),
                ("limited_slow_floor_transition_stage", "candidate_ready_watch_only_core_path"),
            ),
        ),
        "active_core_watch_exit_trend_moderate_watch_only_core_path_trade_date_entry_gap_band_items": _build_trade_date_filtered_bucket_items_multi(
            active_watch_reason_buy_shape_rows,
            filters=(
                ("compound_bucket", "core_watch_path_only|watch_from_exit_setup"),
                ("slow_trend_relax_candidate_band", "trend_moderate_candidate"),
                ("limited_slow_floor_transition_stage", "candidate_ready_watch_only_core_path"),
            ),
            bucket_key="watch_only_core_path_entry_gap_band",
        ),
        "active_core_watch_exit_trend_moderate_watch_only_core_path_trade_date_entry_gap_projection_items": _build_trade_date_filtered_projection_items_multi(
            active_watch_reason_buy_shape_rows,
            filters=(
                ("compound_bucket", "core_watch_path_only|watch_from_exit_setup"),
                ("slow_trend_relax_candidate_band", "trend_moderate_candidate"),
                ("limited_slow_floor_transition_stage", "candidate_ready_watch_only_core_path"),
                ("watch_only_core_path_entry_gap_band", "large_entry_gap"),
            ),
        ),
        "active_core_watch_exit_trend_moderate_signal_floor_miss_detail_items": _build_filtered_bucket_items_multi(
            active_watch_reason_buy_shape_rows,
            bucket_key="shadow_signal_floor_miss_detail",
            filters=(
                ("compound_bucket", "core_watch_path_only|watch_from_exit_setup"),
                ("slow_trend_relax_candidate_band", "trend_moderate_candidate"),
            ),
        ),
        "active_core_watch_exit_trend_moderate_trade_date_projection_items": _build_trade_date_filtered_projection_items_multi(
            active_watch_reason_buy_shape_rows,
            filters=(
                ("compound_bucket", "core_watch_path_only|watch_from_exit_setup"),
                ("slow_trend_relax_candidate_band", "trend_moderate_candidate"),
            ),
        ),
        "active_core_watch_exit_trend_moderate_effective_entry_score_band_items": _build_filtered_bucket_items_multi(
            active_watch_reason_buy_shape_rows,
            bucket_key="effective_entry_score_band",
            filters=(
                ("compound_bucket", "core_watch_path_only|watch_from_exit_setup"),
                ("slow_trend_relax_candidate_band", "trend_moderate_candidate"),
            ),
        ),
        "active_core_watch_exit_trend_moderate_effective_buy_ranking_gap_band_items": _build_filtered_bucket_items_multi(
            active_watch_reason_buy_shape_rows,
            bucket_key="effective_buy_ranking_gap_band",
            filters=(
                ("compound_bucket", "core_watch_path_only|watch_from_exit_setup"),
                ("slow_trend_relax_candidate_band", "trend_moderate_candidate"),
            ),
        ),
        "active_core_watch_exit_trend_moderate_samples": [
            row
            for row in active_watch_reason_buy_shape_rows
            if str(row.get("compound_bucket") or "") == "core_watch_path_only|watch_from_exit_setup"
            and str(row.get("slow_trend_relax_candidate_band") or "") == "trend_moderate_candidate"
        ][: max(0, int(sample_limit))],
        "pre_buy_staging_watch_from_entry_setup_report": _build_pre_buy_staging_comparison_report(
            annotated,
            cohort_value="watch_from_entry_setup",
            sample_limit=sample_limit,
        ),
        "pre_buy_staging_entry_score_ge_0_52_report": _build_pre_buy_staging_comparison_report(
            annotated,
            cohort_value="entry_score_ge_0_52",
            sample_limit=sample_limit,
        ),
        "pre_buy_staging_entry_score_0_55_to_0_65_report": _build_pre_buy_staging_comparison_report(
            annotated,
            cohort_value="entry_score_0_55_to_0_65",
            sample_limit=sample_limit,
        ),
        "pre_buy_staging_low_relative_activity_boundary_report": _build_pre_buy_staging_activity_detail_focus_report(
            annotated,
            activity_detail_value="low_relative_activity_max_0_95_to_1_10",
            sample_limit=sample_limit,
        ),
        "pre_buy_boundary_watch_from_entry_setup_small_entry_gap_report": _build_pre_buy_boundary_buy_shape_detail_report(
            annotated,
            buy_shape_detail_value="watch_from_entry_setup|small_entry_gap",
            sample_limit=sample_limit,
        ),
        "pre_buy_boundary_watch_from_entry_setup_moderate_entry_gap_report": _build_pre_buy_boundary_buy_shape_detail_report(
            annotated,
            buy_shape_detail_value="watch_from_entry_setup|moderate_entry_gap",
            sample_limit=sample_limit,
        ),
        "authoritative_core_buy_path_entry_score_band_items": _build_filtered_bucket_items_multi(
            annotated,
            bucket_key="effective_entry_score_band",
            filters=(
                ("source_type", "core"),
                ("authoritative_buy_path", "True"),
            ),
        ),
        "authoritative_core_buy_path_buy_gap_band_items": _build_filtered_bucket_items_multi(
            annotated,
            bucket_key="effective_buy_candidate_threshold_gap_band",
            filters=(
                ("source_type", "core"),
                ("authoritative_buy_path", "True"),
            ),
        ),
        "authoritative_core_buy_path_buy_ranking_gap_band_items": _build_filtered_bucket_items_multi(
            annotated,
            bucket_key="effective_buy_ranking_gap_band",
            filters=(
                ("source_type", "core"),
                ("authoritative_buy_path", "True"),
            ),
        ),
        "authoritative_core_buy_path_samples": [
            row
            for row in annotated
            if str(row.get("source_type") or "") == "core"
            and bool(row.get("authoritative_buy_path"))
        ][: max(0, int(sample_limit))],
        "authoritative_core_submitted_path_entry_score_band_items": _build_filtered_bucket_items_multi(
            annotated,
            bucket_key="effective_entry_score_band",
            filters=(
                ("source_type", "core"),
                ("authoritative_submitted_path", "True"),
            ),
        ),
        "authoritative_core_submitted_path_buy_gap_band_items": _build_filtered_bucket_items_multi(
            annotated,
            bucket_key="effective_buy_candidate_threshold_gap_band",
            filters=(
                ("source_type", "core"),
                ("authoritative_submitted_path", "True"),
            ),
        ),
        "authoritative_core_submitted_path_buy_ranking_gap_band_items": _build_filtered_bucket_items_multi(
            annotated,
            bucket_key="effective_buy_ranking_gap_band",
            filters=(
                ("source_type", "core"),
                ("authoritative_submitted_path", "True"),
            ),
        ),
        "authoritative_core_submitted_path_samples": [
            row
            for row in annotated
            if str(row.get("source_type") or "") == "core"
            and bool(row.get("authoritative_submitted_path"))
        ][: max(0, int(sample_limit))],
        "active_trend_moderate_gate_reason_items": _build_filtered_bucket_items(
            active_rows,
            bucket_key="shadow_topk_candidate_gate_reason",
            filter_key="slow_trend_relax_candidate_band",
            filter_value="trend_moderate_candidate",
        ),
        "active_trend_moderate_projection_block_reason_items": _build_filtered_bucket_items(
            active_rows,
            bucket_key="shadow_relax_projection_block_reason",
            filter_key="slow_trend_relax_candidate_band",
            filter_value="trend_moderate_candidate",
        ),
        "active_trend_moderate_deterministic_buy_shape_block_reason_items": _build_filtered_bucket_items(
            active_rows,
            bucket_key="deterministic_buy_shape_block_reason",
            filter_key="slow_trend_relax_candidate_band",
            filter_value="trend_moderate_candidate",
        ),
        "active_trend_moderate_signal_floor_miss_detail_items": _build_filtered_bucket_items(
            active_rows,
            bucket_key="shadow_signal_floor_miss_detail",
            filter_key="slow_trend_relax_candidate_band",
            filter_value="trend_moderate_candidate",
        ),
        "active_trend_moderate_slow_floor_shadow_relax_path_items": _build_filtered_bucket_items(
            active_rows,
            bucket_key="slow_floor_shadow_relax_path",
            filter_key="slow_trend_relax_candidate_band",
            filter_value="trend_moderate_candidate",
        ),
        "active_slow_floor_relax_ready_trade_date_band_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    [
                        row
                        for row in active_rows
                        if str(row.get("slow_floor_shadow_relax_path") or "missing")
                        == "slow_floor_relax_ready"
                    ],
                    bucket_key="trade_date",
                )
            )
        ],
        "active_slow_floor_relax_ready_trade_date_projection_items": _build_trade_date_filtered_projection_items(
            active_rows,
            filter_key="slow_floor_shadow_relax_path",
            filter_value="slow_floor_relax_ready",
        ),
        "active_slow_floor_relax_ready_projection_block_reason_items": _build_filtered_bucket_items(
            active_rows,
            bucket_key="shadow_relax_projection_block_reason",
            filter_key="slow_floor_shadow_relax_path",
            filter_value="slow_floor_relax_ready",
        ),
        "active_slow_floor_relax_ready_gate_reason_items": _build_filtered_bucket_items(
            active_rows,
            bucket_key="shadow_topk_candidate_gate_reason",
            filter_key="slow_floor_shadow_relax_path",
            filter_value="slow_floor_relax_ready",
        ),
        "active_slow_floor_relax_ready_watch_reason_items": _build_filtered_bucket_items(
            active_rows,
            bucket_key="watch_primary_candidate_reason",
            filter_key="slow_floor_shadow_relax_path",
            filter_value="slow_floor_relax_ready",
        ),
        "active_slow_floor_relax_ready_deterministic_buy_shape_block_reason_items": _build_filtered_bucket_items(
            active_rows,
            bucket_key="deterministic_buy_shape_block_reason",
            filter_key="slow_floor_shadow_relax_path",
            filter_value="slow_floor_relax_ready",
        ),
        "active_slow_floor_relax_ready_transition_stage_items": _build_filtered_bucket_items(
            active_rows,
            bucket_key="slow_floor_relax_transition_stage",
            filter_key="slow_floor_shadow_relax_path",
            filter_value="slow_floor_relax_ready",
        ),
        "active_slow_floor_relax_ready_trade_date_transition_stage_items": _build_trade_date_filtered_bucket_items(
            active_rows,
            filter_key="slow_floor_shadow_relax_path",
            filter_value="slow_floor_relax_ready",
            bucket_key="slow_floor_relax_transition_stage",
        ),
        "active_slow_floor_relax_ready_samples": [
            row
            for row in active_rows
            if str(row.get("slow_floor_shadow_relax_path") or "") == "slow_floor_relax_ready"
        ][: max(0, int(sample_limit))],
        "active_trend_moderate_eligibility_block_reason_items": _build_filtered_bucket_items(
            active_rows,
            bucket_key="eligibility_block_reason_primary",
            filter_key="slow_trend_relax_candidate_band",
            filter_value="trend_moderate_candidate",
        ),
        "slow_component_path_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    annotated,
                    bucket_key="slow_component_path",
                )
            )
        ],
        "slow_trend_path_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    annotated,
                    bucket_key="slow_trend_path",
                )
            )
        ],
        "shadow_relax_projection_summary": {
            "candidate_count": sum(
                1 for row in annotated if bool(row.get("shadow_relax_projection_candidate"))
            ),
            "selected_count": sum(
                1 for row in annotated if bool(row.get("shadow_relax_projection_selected"))
            ),
            "would_buy_count": sum(
                1 for row in annotated if bool(row.get("shadow_relax_projection_would_buy"))
            ),
            "submitted_count": sum(
                1 for row in annotated if bool(row.get("shadow_relax_projection_submitted"))
            ),
        },
        "shadow_relax_projection_block_reason_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    annotated,
                    bucket_key="shadow_relax_projection_block_reason",
                )
            )
        ],
        "shadow_topk_candidate_gate_reason_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    annotated,
                    bucket_key="shadow_topk_candidate_gate_reason",
                )
            )
        ],
        "watch_primary_candidate_reason_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    annotated,
                    bucket_key="watch_primary_candidate_reason",
                )
            )
        ],
        "eligibility_block_reason_primary_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    annotated,
                    bucket_key="eligibility_block_reason_primary",
                )
            )
        ],
        "shadow_signal_floor_block_path_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    annotated,
                    bucket_key="shadow_signal_floor_block_path",
                )
            )
        ],
        "shadow_signal_floor_miss_detail_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    annotated,
                    bucket_key="shadow_signal_floor_miss_detail",
                )
            )
        ],
        "slow_floor_shadow_relax_path_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    annotated,
                    bucket_key="slow_floor_shadow_relax_path",
                )
            )
        ],
        "watch_eligibility_block_path_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    annotated,
                    bucket_key="watch_eligibility_block_path",
                )
            )
        ],
        "shadow_relax_projection_path_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    annotated,
                    bucket_key="shadow_relax_projection_path",
                )
            )
        ],
        "moderate_gate_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    annotated,
                    bucket_key="moderate_gate_bucket",
                )
            )
        ],
        "blocking_reason_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    annotated,
                    bucket_key="blocking_reason",
                )
            )
        ],
        "bucket_path_items": [
            item_to_dict
            for item_to_dict in (
                _aggregate_item_asdict(item)
                for item in build_trigger_proxy_aggregate_items(
                    annotated,
                    bucket_key="bucket_path",
                )
            )
        ],
        "samples": annotated[: max(0, int(sample_limit))],
    }


def _is_shadow_watch_eligible(row: Mapping[str, object]) -> bool:
    if not bool(row.get("eligibility_passed")):
        return False
    source_type = str(row.get("source_type") or "").strip().lower()
    if source_type in {"held_position", "reconciliation_overlay"}:
        return False
    if _coerce_float(row.get("ranking_score")) is None:
        return False
    if _coerce_float(row.get("entry_score")) is None:
        return False
    return True


def _symbol_day_key(row: Mapping[str, object]) -> tuple[str, str]:
    return (
        str(row.get("trade_date") or ""),
        str(row.get("symbol") or ""),
    )


def _descending_percentile(rank: int, total: int) -> float:
    if total <= 1:
        return 1.0
    return max(0.0, 1.0 - float(rank - 1) / float(total - 1))


def _average(
    rows: Sequence[Mapping[str, object]],
    key: str,
) -> float | None:
    values = [_coerce_float(row.get(key)) for row in rows]
    concrete = [value for value in values if value is not None]
    if not concrete:
        return None
    return sum(concrete) / float(len(concrete))


def _positive_hit_count(
    rows: Sequence[Mapping[str, object]],
    key: str,
) -> int:
    values = [_coerce_float(row.get(key)) for row in rows]
    return sum(1 for value in values if value is not None and value > 0.0)


def _positive_hit_rate(
    rows: Sequence[Mapping[str, object]],
    key: str,
) -> float | None:
    values = [_coerce_float(row.get(key)) for row in rows]
    concrete = [value for value in values if value is not None]
    if not concrete:
        return None
    return float(sum(1 for value in concrete if value > 0.0)) / float(len(concrete))


def _coerce_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_gap(threshold: float, value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.0, threshold - value)


def _aggregate_item_asdict(item: TriggerProxyAggregateItem) -> dict[str, object]:
    return {
        "bucket": item.bucket,
        "sample_count": item.sample_count,
        "t1_return_pct_avg": item.t1_return_pct_avg,
        "t3_return_pct_avg": item.t3_return_pct_avg,
        "t5_return_pct_avg": item.t5_return_pct_avg,
        "t3_mfe_pct_avg": item.t3_mfe_pct_avg,
        "t3_mae_pct_avg": item.t3_mae_pct_avg,
        "t5_mfe_pct_avg": item.t5_mfe_pct_avg,
        "t5_mae_pct_avg": item.t5_mae_pct_avg,
        "positive_t3_hit_count": item.positive_t3_hit_count,
        "positive_t3_hit_rate": item.positive_t3_hit_rate,
    }


def _resolve_shadow_floor_bucket(
    payload: Mapping[str, object],
    *,
    bucket_field: str,
    overall_field: str = "shadow_overall_score",
    slow_field: str = "shadow_slow_score",
    mild_overall_min: float,
    mild_slow_min: float,
    moderate_overall_min: float,
    moderate_slow_min: float,
    reason_prefix: str,
) -> str:
    bucket = str(payload.get(bucket_field) or "").strip()
    if bucket:
        return bucket
    overall = _coerce_float(payload.get(overall_field))
    slow = _coerce_float(payload.get(slow_field))
    entry_score = _coerce_float(payload.get("shadow_entry_score")) or 0.0
    ranking_score = _coerce_float(
        payload.get("shadow_rank_candidate_score", payload.get("raw_ranking_score"))
    )
    shadow_activity_pass = bool(payload.get("shadow_activity_pass"))
    shadow_strategy_pass = bool(payload.get("shadow_strategy_pass"))
    derived_bucket, _, _ = _derive_shadow_floor_bucket(
        overall=overall,
        slow=slow,
        entry_score=entry_score,
        ranking_score=ranking_score,
        shadow_activity_pass=shadow_activity_pass,
        shadow_strategy_pass=shadow_strategy_pass,
        mild_overall_min=mild_overall_min,
        mild_slow_min=mild_slow_min,
        moderate_overall_min=moderate_overall_min,
        moderate_slow_min=moderate_slow_min,
        reason_prefix=reason_prefix,
    )
    return derived_bucket


def _classify_overall_band(overall: float | None) -> str:
    if overall is None:
        return "missing"
    if overall >= 0.0:
        return "strict_non_negative"
    if overall >= -0.10:
        return "mild_window"
    if overall >= -0.25:
        return "moderate_window"
    return "deep_negative"


def _classify_slow_band(slow: float | None) -> str:
    if slow is None:
        return "missing"
    if slow >= -0.05:
        return "strict_non_negative"
    if slow >= -0.15:
        return "mild_window"
    if slow >= -0.25:
        return "moderate_window"
    return "deep_negative"


def _classify_slow_relax_candidate_band(slow: float | None) -> str:
    if slow is None:
        return "missing"
    if slow >= -0.05:
        return "strict_ready"
    if slow >= -0.15:
        return "mild_candidate"
    if slow >= -0.25:
        return "moderate_candidate"
    if slow >= -0.40:
        return "edge_deep"
    return "deep_tail"


def _classify_slow_component_band(score: float | None) -> str:
    if score is None:
        return "missing"
    if score >= 0.45:
        return "positive"
    if score >= 0.0:
        return "neutral_to_flat"
    if score >= -0.25:
        return "micro_negative"
    if score >= -0.55:
        return "moderate_negative"
    return "deep_negative"


def _classify_slow_trend_relax_candidate_band(price_vs_sma_60_pct: float | None) -> str:
    if price_vs_sma_60_pct is None:
        return "missing"
    if price_vs_sma_60_pct >= -0.5:
        return "trend_strict_ready"
    if price_vs_sma_60_pct > -2.5:
        return "trend_mild_candidate"
    if price_vs_sma_60_pct > -6.0:
        return "trend_moderate_candidate"
    if price_vs_sma_60_pct > -12.0:
        return "trend_edge_deep"
    return "trend_deep_tail"


def _build_trade_date_bucket_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    bucket_key: str,
) -> list[dict[str, object]]:
    annotated: list[dict[str, object]] = []
    for row in rows:
        trade_date = str(row.get("trade_date") or "").strip() or "unknown"
        bucket = str(row.get(bucket_key) or "unknown").strip() or "unknown"
        annotated.append(
            {
                **row,
                "trade_date_bucket": f"{trade_date}|{bucket}",
            }
        )
    return annotated


def _explode_reason_code_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    codes_key: str,
    output_key: str,
) -> list[dict[str, object]]:
    exploded: list[dict[str, object]] = []
    for row in rows:
        codes = row.get(codes_key) or []
        if not isinstance(codes, Sequence) or isinstance(codes, (str, bytes)):
            codes = []
        if not codes:
            exploded.append({**row, output_key: "none"})
            continue
        for code in codes:
            normalized = str(code).strip().lower()
            if not normalized:
                continue
            exploded.append({**row, output_key: normalized})
    return exploded


def _is_shadow_relax_projection_candidate(
    *,
    active: bool,
    shadow_floor_bucket: str,
    slow_trend_relax_candidate_band: str,
    slow_momentum_band: str,
) -> bool:
    if not active:
        return False
    if shadow_floor_bucket != "deep_negative":
        return False
    if slow_trend_relax_candidate_band not in {
        "trend_mild_candidate",
        "trend_moderate_candidate",
        "trend_edge_deep",
    }:
        return False
    if slow_momentum_band == "deep_negative":
        return False
    return True


def _is_shadow_relax_projection_buy_shape(
    *,
    primary_candidate: str,
    candidate_intent: str,
    final_decision_type: str,
) -> bool:
    if primary_candidate == "buy_candidate":
        return True
    if candidate_intent == "buy":
        return True
    return final_decision_type in {"approve", "buy"}


def _is_authoritative_buy_path(
    *,
    primary_candidate: str,
    candidate_intent: str,
    buy_candidate: bool,
    final_decision_type: str,
) -> bool:
    if buy_candidate:
        return True
    if primary_candidate == "buy_candidate":
        return True
    if candidate_intent == "buy":
        return True
    return final_decision_type == "buy"


def _is_projection_submitted(
    *,
    order_request_id: object | None,
    order_status: str,
    execution_status: str,
    submission_accepted: bool,
) -> bool:
    if execution_status == "submitted":
        return True
    if submission_accepted:
        return True
    if order_request_id is None:
        return False
    return order_status in {"validated", "partially_filled", "filled", "expired"}


def _classify_shadow_relax_projection_block_reason(
    *,
    active: bool,
    shadow_floor_bucket: str,
    slow_trend_relax_candidate_band: str,
    slow_momentum_band: str,
    shadow_topk_candidate: bool,
    shadow_topk_selected: bool,
    projection_buy_shape: bool,
    order_request_id: object | None,
    order_status: str,
    execution_status: str,
    execution_stop_reason: str,
    submission_accepted: bool,
    submission_error_type: str,
) -> str:
    if not active:
        return "inactive"
    if shadow_floor_bucket != "deep_negative":
        return "non_deep_negative_bucket"
    if slow_trend_relax_candidate_band == "missing":
        return "trend_band_missing"
    if slow_trend_relax_candidate_band in {"trend_strict_ready", "trend_deep_tail"}:
        return "trend_outside_target"
    if slow_momentum_band == "deep_negative":
        return "momentum_deep_negative_guard"
    if not shadow_topk_candidate:
        return "shadow_topk_candidate_miss"
    if not shadow_topk_selected:
        return "shadow_topk_not_selected"
    if not projection_buy_shape:
        return "watch_only_or_non_buy_shape"
    if _is_projection_submitted(
        order_request_id=order_request_id,
        order_status=order_status,
        execution_status=execution_status,
        submission_accepted=submission_accepted,
    ):
        return "actual_submitted"
    if execution_stop_reason:
        return f"downstream_blocked:{execution_stop_reason}"
    if submission_error_type:
        return f"submission_error:{submission_error_type}"
    if order_request_id is not None:
        return f"order_created:{order_status or 'unknown'}"
    if execution_status and execution_status != "unknown":
        return f"execution_status:{execution_status}"
    return "buy_path_without_submit_trace"


def _classify_shadow_topk_candidate_gate_reason(
    *,
    active: bool,
    shadow_topk_candidate: bool,
    shadow_overall_pass: bool,
    shadow_slow_pass: bool,
    shadow_activity_pass: bool,
    shadow_strategy_pass: bool,
    shadow_ranking_score: float | None,
    payload: Mapping[str, object],
) -> str:
    if not active:
        return "inactive"
    if shadow_topk_candidate:
        return "shadow_topk_candidate_pass"
    shadow_min_score = _coerce_float(payload.get("shadow_min_score"))
    if shadow_ranking_score is None:
        return "ranking_missing"
    if shadow_min_score is not None and shadow_ranking_score < shadow_min_score:
        return "ranking_floor_miss"
    if not shadow_overall_pass and not shadow_slow_pass:
        return "signal_both_floor_miss"
    if not shadow_overall_pass:
        return "overall_floor_miss"
    if not shadow_slow_pass:
        return "slow_floor_miss"
    if not shadow_activity_pass:
        return "activity_floor_miss"
    if not shadow_strategy_pass:
        return "strategy_floor_miss"
    return "shadow_topk_candidate_unknown_miss"


def _classify_primary_eligibility_block_reason(
    eligibility_reasons: object,
    *,
    eligibility_passed: bool,
    shadow_activity_pass: bool,
    shadow_strategy_pass: bool,
    shadow_overall_score: float | None,
    shadow_slow_score: float | None,
    shadow_ranking_score: float | None,
    payload: Mapping[str, object],
) -> str:
    if not isinstance(eligibility_reasons, Sequence) or isinstance(
        eligibility_reasons, (str, bytes)
    ):
        return "none"
    blocked_reasons = [
        str(reason).strip().lower()
        for reason in eligibility_reasons
        if str(reason).strip().lower().startswith("eligibility_")
        and (
            str(reason).strip().lower().endswith("_blocked")
            or str(reason).strip().lower().endswith("_block")
            or str(reason).strip().lower().startswith("eligibility_negative_")
            or str(reason).strip().lower().startswith("eligibility_low_")
        )
    ]
    priority = (
        "eligibility_core_risk_off_ranking_blocked",
        "eligibility_negative_overall_floor",
        "eligibility_negative_slow_floor",
        "eligibility_low_relative_activity",
        "eligibility_low_turnover",
        "eligibility_low_average_volume",
        "eligibility_participation_rate_blocked",
        "eligibility_risk_off_block",
        "eligibility_execution_feasibility_blocked",
        "eligibility_allocation_blocked",
    )
    for code in priority:
        if code in blocked_reasons:
            return code
    if blocked_reasons:
        return blocked_reasons[0]
    if eligibility_passed:
        return "none"
    if not shadow_activity_pass:
        return "eligibility_low_relative_activity"
    if not shadow_strategy_pass:
        return "eligibility_strategy_blocked"
    if shadow_overall_score is not None and shadow_overall_score < -0.25:
        return "eligibility_negative_overall_floor"
    if shadow_slow_score is not None and shadow_slow_score < -0.25:
        return "eligibility_negative_slow_floor"
    shadow_min_score = _coerce_float(payload.get("shadow_min_score"))
    if (
        shadow_ranking_score is not None
        and shadow_min_score is not None
        and shadow_ranking_score < shadow_min_score
    ):
        return "eligibility_core_risk_off_ranking_blocked"
    return "none"


def _classify_shadow_signal_floor_block_path(
    *,
    active: bool,
    shadow_topk_candidate_gate_reason: str,
    shadow_overall_pass: bool,
    shadow_slow_pass: bool,
    overall_band: str,
    slow_band: str,
    slow_momentum_band: str,
    slow_trend_band: str,
) -> str:
    if not active:
        return "inactive"
    if shadow_topk_candidate_gate_reason not in {
        "signal_both_floor_miss",
        "overall_floor_miss",
        "slow_floor_miss",
    }:
        return "signal_gate_not_primary"
    overall_flag = "overall_pass" if shadow_overall_pass else "overall_fail"
    slow_flag = "slow_pass" if shadow_slow_pass else "slow_fail"
    return (
        f"{overall_flag}|{slow_flag}|"
        f"{overall_band}|{slow_band}|"
        f"{slow_momentum_band}|{slow_trend_band}"
    )


def _classify_shadow_signal_floor_miss_detail(
    *,
    active: bool,
    shadow_topk_candidate_gate_reason: str,
    shadow_overall_score: float | None,
    shadow_slow_score: float | None,
    strict_overall_min: float = 0.0,
    strict_slow_min: float = -0.05,
    relax_overall_min: float = -0.25,
    relax_slow_min: float = -0.25,
) -> str:
    if not active:
        return "inactive"
    if shadow_topk_candidate_gate_reason not in {
        "signal_both_floor_miss",
        "overall_floor_miss",
        "slow_floor_miss",
    }:
        return "signal_gate_not_primary"
    if shadow_overall_score is None or shadow_slow_score is None:
        return "signal_score_missing"

    overall_strict_fail = shadow_overall_score < strict_overall_min
    slow_strict_fail = shadow_slow_score < strict_slow_min
    overall_relax_fail = shadow_overall_score < relax_overall_min
    slow_relax_fail = shadow_slow_score < relax_slow_min

    if overall_strict_fail and slow_strict_fail:
        if not overall_relax_fail and not slow_relax_fail:
            return "double_near_miss"
        if not overall_relax_fail and slow_relax_fail:
            return "overall_near_slow_deep"
        if overall_relax_fail and not slow_relax_fail:
            return "overall_deep_slow_near"
        return "double_deep_miss"
    if overall_strict_fail:
        return "overall_deep_miss" if overall_relax_fail else "overall_near_miss"
    if slow_strict_fail:
        return "slow_deep_miss" if slow_relax_fail else "slow_near_miss"
    return "strict_floor_pass"


def _classify_slow_floor_shadow_relax_path(
    *,
    active: bool,
    slow_trend_relax_candidate_band: str,
    shadow_signal_floor_miss_detail: str,
    shadow_activity_pass: bool,
    shadow_strategy_pass: bool,
    shadow_ranking_score: float | None,
    ranking_min: float = 0.26,
) -> str:
    if not active:
        return "inactive"
    if slow_trend_relax_candidate_band != "trend_moderate_candidate":
        return "non_target_band"
    if shadow_signal_floor_miss_detail == "overall_deep_slow_near":
        return "overall_floor_first"
    if shadow_signal_floor_miss_detail != "overall_near_slow_deep":
        return f"non_target_miss_detail:{shadow_signal_floor_miss_detail}"
    if shadow_ranking_score is None:
        return "slow_floor_relax_ranking_missing"
    if shadow_ranking_score < ranking_min:
        return "slow_floor_relax_ranking_blocked"
    if not shadow_activity_pass:
        return "slow_floor_relax_activity_blocked"
    if not shadow_strategy_pass:
        return "slow_floor_relax_strategy_blocked"
    return "slow_floor_relax_ready"


def _classify_slow_floor_relax_transition_stage(
    *,
    slow_floor_shadow_relax_path: str,
    projection_buy_shape: bool,
    shadow_topk_candidate: bool,
    shadow_topk_selected: bool,
    projection_would_buy: bool,
    projection_submitted: bool,
    watch_primary_candidate_reason: str,
) -> str:
    if slow_floor_shadow_relax_path != "slow_floor_relax_ready":
        return "non_ready_path"
    if not projection_buy_shape:
        if watch_primary_candidate_reason == "core_watch_path_only":
            return "watch_only_core_path"
        return "watch_only_other"
    if not shadow_topk_candidate:
        return "buy_shape_gate_miss"
    if not shadow_topk_selected:
        return "buy_shape_not_selected"
    if not projection_would_buy:
        return "selected_without_buy_shape"
    if not projection_submitted:
        return "would_buy_not_submitted"
    return "submitted"


def _classify_limited_slow_floor_shadow_path(
    *,
    active: bool,
    compound_bucket: str,
    slow_trend_relax_candidate_band: str,
    shadow_signal_floor_miss_detail: str,
    shadow_activity_pass: bool,
    shadow_strategy_pass: bool,
    shadow_ranking_score: float | None,
    ranking_min: float = 0.26,
) -> str:
    if not active:
        return "inactive"
    if compound_bucket != "core_watch_path_only|watch_from_exit_setup":
        return "non_target_cohort"
    if slow_trend_relax_candidate_band != "trend_moderate_candidate":
        return "non_target_band"
    if shadow_signal_floor_miss_detail == "overall_deep_slow_near":
        return "overall_floor_first"
    if shadow_signal_floor_miss_detail != "overall_near_slow_deep":
        return f"non_target_miss_detail:{shadow_signal_floor_miss_detail}"
    if shadow_ranking_score is None:
        return "ranking_missing"
    if shadow_ranking_score < ranking_min:
        return "ranking_blocked"
    if not shadow_activity_pass:
        return "activity_blocked"
    if not shadow_strategy_pass:
        return "strategy_blocked"
    return "candidate_ready"


def _classify_limited_slow_floor_transition_stage(
    *,
    limited_slow_floor_shadow_path: str,
    projection_buy_shape: bool,
    watch_primary_candidate_reason: str,
    deterministic_buy_shape_block_reason: str,
) -> str:
    if limited_slow_floor_shadow_path != "candidate_ready":
        return limited_slow_floor_shadow_path
    if projection_buy_shape:
        return "candidate_ready_buy_shape"
    if watch_primary_candidate_reason == "core_watch_path_only":
        return "candidate_ready_watch_only_core_path"
    return f"candidate_ready_non_buy_shape:{deterministic_buy_shape_block_reason}"


def _classify_watch_only_core_path_shadow_reason(
    *,
    limited_slow_floor_transition_stage: str,
    deterministic_buy_shape_block_reason: str,
    buy_candidate_threshold_gap: float | None,
    watch_candidate_threshold_gap: float | None,
    core_risk_off_ranking_min_gap: float | None,
) -> str:
    if limited_slow_floor_transition_stage != "candidate_ready_watch_only_core_path":
        return limited_slow_floor_transition_stage
    if deterministic_buy_shape_block_reason != "watch_from_exit_setup":
        return f"non_exit_setup_shape:{deterministic_buy_shape_block_reason}"
    if buy_candidate_threshold_gap is None:
        return "exit_setup_buy_gap_missing"
    if buy_candidate_threshold_gap >= 0.25:
        return "exit_setup_large_entry_gap"
    if buy_candidate_threshold_gap > 0.0:
        return "exit_setup_moderate_entry_gap"
    if core_risk_off_ranking_min_gap is not None and core_risk_off_ranking_min_gap > 0.0:
        return "exit_setup_ranking_gap_after_entry_ready"
    if watch_candidate_threshold_gap is not None and watch_candidate_threshold_gap > 0.0:
        return "exit_setup_watch_gap_remaining"
    return "exit_setup_trigger_shape_only"


def _classify_watch_only_core_path_entry_gap_band(
    *,
    limited_slow_floor_transition_stage: str,
    buy_candidate_threshold_gap: float | None,
) -> str:
    if limited_slow_floor_transition_stage != "candidate_ready_watch_only_core_path":
        return limited_slow_floor_transition_stage
    return _classify_buy_candidate_threshold_gap_band(
        buy_candidate_threshold_gap=buy_candidate_threshold_gap
    )


def _classify_buy_candidate_threshold_gap_band(
    *,
    buy_candidate_threshold_gap: float | None,
) -> str:
    if buy_candidate_threshold_gap is None:
        return "buy_gap_missing"
    if buy_candidate_threshold_gap >= 0.25:
        return "large_entry_gap"
    if buy_candidate_threshold_gap >= 0.10:
        return "moderate_entry_gap"
    if buy_candidate_threshold_gap > 0.0:
        return "small_entry_gap"
    return "entry_ready"


def _classify_effective_entry_score_band(entry_score: float | None) -> str:
    if entry_score is None:
        return "entry_missing"
    if entry_score >= BUY_CANDIDATE_THRESHOLD:
        return "buy_ready"
    if entry_score >= BUY_MIN_RANKING_SCORE:
        return "near_buy_floor"
    if entry_score >= WATCH_CANDIDATE_THRESHOLD:
        return "watch_band"
    if entry_score >= 0.12:
        return "observe_band"
    return "below_observe_floor"


def _classify_effective_ranking_gap_band(
    *,
    ranking_gap: float | None,
) -> str:
    if ranking_gap is None:
        return "ranking_gap_missing"
    if ranking_gap <= 0.0:
        return "ranking_ready"
    if ranking_gap <= 0.05:
        return "small_ranking_gap"
    if ranking_gap <= 0.15:
        return "moderate_ranking_gap"
    return "large_ranking_gap"


def _classify_pre_buy_staging_cohort(
    *,
    source_type: str,
    watch_primary_candidate_reason: str,
    effective_entry_score: float | None,
) -> str:
    if source_type != "core":
        return "non_core"
    if watch_primary_candidate_reason == "watch_from_entry_setup":
        return "watch_from_entry_setup"
    if effective_entry_score is None:
        return "entry_missing"
    if 0.55 <= effective_entry_score < BUY_CANDIDATE_THRESHOLD:
        return "entry_score_0_55_to_0_65"
    if effective_entry_score >= WATCH_MIN_ENTRY_SCORE:
        return "entry_score_ge_0_52"
    return "outside_pre_buy_staging"


def _classify_pre_buy_staging_activity_gate(
    *,
    pre_buy_staging_cohort: str,
    eligibility_block_reason_primary: str,
    shadow_activity_pass: bool,
) -> str:
    if pre_buy_staging_cohort in {
        "non_core",
        "entry_missing",
        "outside_pre_buy_staging",
    }:
        return pre_buy_staging_cohort
    if eligibility_block_reason_primary in {
        "eligibility_low_average_volume",
        "eligibility_low_turnover",
        "eligibility_low_relative_activity",
        "eligibility_participation_rate_blocked",
    }:
        return eligibility_block_reason_primary
    if not shadow_activity_pass:
        return "shadow_activity_blocked_without_explicit_activity_reason"
    if eligibility_block_reason_primary not in {"none", "inactive"}:
        return f"non_activity_block:{eligibility_block_reason_primary}"
    return "activity_pass_or_not_primary_block"


def _classify_pre_buy_staging_activity_detail(
    *,
    pre_buy_staging_activity_gate: str,
    average_volume_20d: float | None,
    average_turnover_20d: float | None,
    volume_surge_ratio: float | None,
    turnover_surge_ratio: float | None,
    activity_participation_rate: float | None,
) -> str:
    if pre_buy_staging_activity_gate == "eligibility_low_relative_activity":
        if volume_surge_ratio is None or turnover_surge_ratio is None:
            return "low_relative_activity_missing_input"
        max_ratio = max(volume_surge_ratio, turnover_surge_ratio)
        if max_ratio < 0.80:
            return "low_relative_activity_max_lt_0_80"
        if max_ratio < 0.95:
            return "low_relative_activity_max_0_80_to_0_95"
        return "low_relative_activity_max_0_95_to_1_10"
    if pre_buy_staging_activity_gate == "eligibility_participation_rate_blocked":
        if activity_participation_rate is None:
            return "participation_rate_missing_input"
        if activity_participation_rate > 0.20:
            return "participation_rate_gt_20pct"
        if activity_participation_rate > 0.10:
            return "participation_rate_10_to_20pct"
        return "participation_rate_5_to_10pct"
    if pre_buy_staging_activity_gate == "eligibility_low_turnover":
        if average_turnover_20d is None:
            return "low_turnover_missing_input"
        if average_turnover_20d < 20_000_000.0:
            return "low_turnover_lt_20m"
        if average_turnover_20d < 50_000_000.0:
            return "low_turnover_20m_to_50m"
        return "low_turnover_ge_50m"
    if pre_buy_staging_activity_gate == "eligibility_low_average_volume":
        if average_volume_20d is None:
            return "low_average_volume_missing_input"
        if average_volume_20d < 1_000.0:
            return "low_average_volume_lt_1k"
        if average_volume_20d < 3_000.0:
            return "low_average_volume_1k_to_3k"
        return "low_average_volume_ge_3k"
    return pre_buy_staging_activity_gate


def _classify_pre_buy_boundary_first_order_bottleneck(
    *,
    pre_buy_staging_activity_detail: str,
    pre_buy_staging_activity_gate: str,
    effective_buy_candidate_threshold_gap_band: str,
    effective_buy_ranking_gap_band: str,
) -> str:
    if pre_buy_staging_activity_detail != "low_relative_activity_max_0_95_to_1_10":
        return "non_boundary"
    if pre_buy_staging_activity_gate != "eligibility_low_relative_activity":
        return "mixed_or_unclassified"

    ranking_ready_like = effective_buy_ranking_gap_band in {
        "ranking_ready",
        "small_ranking_gap",
    }
    if ranking_ready_like:
        if effective_buy_candidate_threshold_gap_band == "entry_ready":
            return "activity_first_entry_ready"
        if effective_buy_candidate_threshold_gap_band == "small_entry_gap":
            return "activity_first_small_entry_gap"
        if effective_buy_candidate_threshold_gap_band == "moderate_entry_gap":
            return "activity_first_moderate_entry_gap"
        if effective_buy_candidate_threshold_gap_band == "large_entry_gap":
            return "activity_with_large_entry_gap"
        return "mixed_or_unclassified"

    if effective_buy_candidate_threshold_gap_band == "entry_ready":
        return "ranking_gap_before_activity_entry_ready"
    if effective_buy_candidate_threshold_gap_band == "small_entry_gap":
        return "ranking_gap_before_activity_small_entry_gap"
    if effective_buy_candidate_threshold_gap_band == "moderate_entry_gap":
        return "ranking_gap_before_activity_moderate_entry_gap"
    return "mixed_or_unclassified"


def _classify_pre_buy_boundary_activity_counterfactual_next_gate(
    *,
    pre_buy_staging_activity_detail: str,
    pre_buy_staging_activity_gate: str,
    shadow_signal_pass: bool,
    effective_buy_candidate_threshold_gap_band: str,
    effective_buy_ranking_gap_band: str,
    shadow_strategy_pass: bool,
    shadow_topk_candidate: bool,
    shadow_topk_selected: bool,
    projection_buy_shape: bool,
    projection_submitted: bool,
) -> str:
    if pre_buy_staging_activity_detail != "low_relative_activity_max_0_95_to_1_10":
        return "non_boundary"
    if pre_buy_staging_activity_gate != "eligibility_low_relative_activity":
        return "mixed_or_unclassified"
    if not shadow_signal_pass:
        return "signal_before_activity_release"
    if effective_buy_candidate_threshold_gap_band == "large_entry_gap":
        return "buy_shape_after_activity_large_entry_gap"
    if effective_buy_candidate_threshold_gap_band == "moderate_entry_gap":
        return "buy_shape_after_activity_moderate_entry_gap"
    if effective_buy_candidate_threshold_gap_band == "small_entry_gap":
        return "buy_shape_after_activity_small_entry_gap"
    if effective_buy_ranking_gap_band not in {"ranking_ready", "small_ranking_gap"}:
        return "ranking_after_activity"
    if not shadow_strategy_pass:
        return "strategy_after_activity"
    if not shadow_topk_candidate:
        return "topk_candidate_after_activity_unknown"
    if not shadow_topk_selected:
        return "topk_selected_after_activity"
    if not projection_buy_shape:
        return "buy_shape_after_activity_entry_ready"
    if not projection_submitted:
        return "submit_after_activity"
    return "submitted_after_activity"


def _classify_pre_buy_boundary_activity_buy_shape_detail(
    *,
    pre_buy_boundary_activity_counterfactual_next_gate: str,
    deterministic_buy_shape_block_reason: str,
    effective_buy_candidate_threshold_gap_band: str,
) -> str:
    if pre_buy_boundary_activity_counterfactual_next_gate not in {
        "buy_shape_after_activity_large_entry_gap",
        "buy_shape_after_activity_moderate_entry_gap",
        "buy_shape_after_activity_small_entry_gap",
        "buy_shape_after_activity_entry_ready",
    }:
        return "non_buy_shape_after_activity"

    normalized_reason = deterministic_buy_shape_block_reason.strip().lower()
    if not normalized_reason:
        normalized_reason = "unknown_buy_shape_reason"
    return f"{normalized_reason}|{effective_buy_candidate_threshold_gap_band}"


def _classify_watch_primary_candidate_reason(
    *,
    primary_candidate: str,
    buy_candidate: bool,
    eligibility_passed: bool,
    entry_score: float | None,
    watch_score: float | None,
    trigger_reason_codes: Sequence[str],
) -> str:
    if primary_candidate != "watch":
        return "non_watch_primary"
    if buy_candidate:
        return "watch_despite_buy_candidate"
    if "trigger_core_watch_path" in trigger_reason_codes and "trigger_watch_from_entry_setup" not in trigger_reason_codes:
        return "core_watch_path_only"
    if not eligibility_passed and "trigger_watch_from_entry_setup" in trigger_reason_codes:
        return "watch_setup_but_ineligible"
    if "trigger_watch_from_entry_setup" in trigger_reason_codes:
        if entry_score is not None and entry_score < 0.65:
            return "watch_below_buy_threshold"
        return "watch_from_entry_setup"
    if watch_score is not None and watch_score >= 0.45 and not eligibility_passed:
        return "watch_with_eligibility_block"
    if entry_score is not None and entry_score < 0.65:
        return "watch_below_buy_threshold"
    return "watch_other"


def _classify_deterministic_buy_shape_block_reason(
    *,
    primary_candidate: str,
    buy_candidate: bool,
    eligibility_passed: bool,
    entry_score: float | None,
    watch_score: float | None,
    ranking_score: float | None,
    trigger_reason_codes: Sequence[str],
) -> str:
    if buy_candidate or primary_candidate == "buy_candidate":
        return "buy_shape_ready"
    if primary_candidate != "watch":
        return "non_watch_primary"
    normalized_codes = {str(code).strip().lower() for code in trigger_reason_codes if str(code).strip()}
    if "trigger_watch_from_exit_setup" in normalized_codes:
        return "watch_from_exit_setup"
    if "trigger_watch_from_entry_setup" in normalized_codes:
        return "watch_from_entry_setup"
    if "trigger_core_watch_path" in normalized_codes:
        return "core_watch_gap_bridge"
    if not eligibility_passed:
        return "watch_with_eligibility_block"
    if entry_score is not None and entry_score < BUY_CANDIDATE_THRESHOLD:
        return "entry_below_buy_threshold"
    if watch_score is not None and watch_score >= WATCH_CANDIDATE_THRESHOLD:
        return "watch_threshold_only"
    if ranking_score is not None and ranking_score < BUY_MIN_RANKING_SCORE:
        return "ranking_below_buy_projection_threshold"
    return "watch_other"


def _build_band_report(
    rows: Sequence[Mapping[str, object]],
    *,
    bucket_key: str,
    bucket_order: Sequence[str],
) -> dict[str, object]:
    aggregate_items = build_trigger_proxy_aggregate_items(rows, bucket_key=bucket_key)
    by_bucket = {str(item.bucket): item for item in aggregate_items}
    report_items: list[dict[str, object]] = []
    for bucket in bucket_order:
        item = by_bucket.get(bucket)
        report_items.append(
            {
                "bucket": bucket,
                "sample_count": int(item.sample_count) if item is not None else 0,
                "t1_return_pct_avg": item.t1_return_pct_avg if item is not None else None,
                "t3_return_pct_avg": item.t3_return_pct_avg if item is not None else None,
                "t5_return_pct_avg": item.t5_return_pct_avg if item is not None else None,
                "positive_t3_hit_rate": (
                    item.positive_t3_hit_rate if item is not None else None
                ),
            }
        )
    non_zero_buckets = sum(1 for item in report_items if int(item["sample_count"]) > 0)
    return {
        "bucket_order": list(bucket_order),
        "items": report_items,
        "non_zero_bucket_count": non_zero_buckets,
        "proxy_availability": {
            "t1_ready_count": sum(
                1 for row in rows if _coerce_float(row.get("t1_return_pct")) is not None
            ),
            "t3_ready_count": sum(
                1 for row in rows if _coerce_float(row.get("t3_return_pct")) is not None
            ),
            "t5_ready_count": sum(
                1 for row in rows if _coerce_float(row.get("t5_return_pct")) is not None
            ),
        },
    }


def _build_projection_band_items(
    rows: Sequence[Mapping[str, object]],
    *,
    bucket_key: str,
    bucket_order: Sequence[str],
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for bucket in bucket_order:
        bucket_rows = [
            row for row in rows if str(row.get(bucket_key) or "missing") == bucket
        ]
        items.append(
            {
                "bucket": bucket,
                "sample_count": len(bucket_rows),
                "candidate_count": sum(
                    1
                    for row in bucket_rows
                    if bool(row.get("shadow_relax_projection_candidate"))
                ),
                "selected_count": sum(
                    1
                    for row in bucket_rows
                    if bool(row.get("shadow_relax_projection_selected"))
                ),
                "would_buy_count": sum(
                    1
                    for row in bucket_rows
                    if bool(row.get("shadow_relax_projection_would_buy"))
                ),
                "submitted_count": sum(
                    1
                    for row in bucket_rows
                    if bool(row.get("shadow_relax_projection_submitted"))
                ),
            }
        )
    return items


def _build_trade_date_projection_items(
    rows: Sequence[Mapping[str, object]],
    *,
    bucket_key: str,
) -> list[dict[str, object]]:
    buckets: dict[str, list[Mapping[str, object]]] = {}
    for row in rows:
        trade_date = str(row.get("trade_date") or "").strip()
        bucket = str(row.get(bucket_key) or "missing").strip() or "missing"
        composite = f"{trade_date}|{bucket}"
        buckets.setdefault(composite, []).append(row)

    items: list[dict[str, object]] = []
    for composite in sorted(buckets):
        bucket_rows = buckets[composite]
        items.append(
            {
                "bucket": composite,
                "sample_count": len(bucket_rows),
                "candidate_count": sum(
                    1
                    for row in bucket_rows
                    if bool(row.get("shadow_relax_projection_candidate"))
                ),
                "selected_count": sum(
                    1
                    for row in bucket_rows
                    if bool(row.get("shadow_relax_projection_selected"))
                ),
                "would_buy_count": sum(
                    1
                    for row in bucket_rows
                    if bool(row.get("shadow_relax_projection_would_buy"))
                ),
                "submitted_count": sum(
                    1
                    for row in bucket_rows
                    if bool(row.get("shadow_relax_projection_submitted"))
                ),
            }
        )
    return items


def _build_trade_date_filtered_projection_items(
    rows: Sequence[Mapping[str, object]],
    *,
    filter_key: str,
    filter_value: str,
) -> list[dict[str, object]]:
    filtered_rows = [
        row
        for row in rows
        if str(row.get(filter_key) or "missing") == filter_value
    ]
    return _build_trade_date_projection_items(
        filtered_rows,
        bucket_key=filter_key,
    )


def _build_trade_date_filtered_bucket_items(
    rows: Sequence[Mapping[str, object]],
    *,
    filter_key: str,
    filter_value: str,
    bucket_key: str,
) -> list[dict[str, object]]:
    return [
        _aggregate_item_asdict(item)
        for item in build_trigger_proxy_aggregate_items(
            _build_trade_date_bucket_rows(
                [
                    row
                    for row in rows
                    if str(row.get(filter_key) or "missing") == filter_value
                ],
                bucket_key=bucket_key,
            ),
            bucket_key="trade_date_bucket",
        )
    ]


def _build_trade_date_filtered_projection_items_multi(
    rows: Sequence[Mapping[str, object]],
    *,
    filters: Sequence[tuple[str, str]],
) -> list[dict[str, object]]:
    filtered_rows = list(rows)
    for filter_key, filter_value in filters:
        filtered_rows = [
            row
            for row in filtered_rows
            if str(row.get(filter_key) or "missing") == filter_value
        ]
    if not filters:
        return _build_trade_date_projection_items(filtered_rows, bucket_key="trade_date")
    compound_key = "|".join(filter_value for _, filter_value in filters)
    filtered_with_bucket = [
        {
            **row,
            "filtered_bucket": compound_key,
        }
        for row in filtered_rows
    ]
    return _build_trade_date_projection_items(
        filtered_with_bucket,
        bucket_key="filtered_bucket",
    )


def _build_trade_date_filtered_bucket_items_multi(
    rows: Sequence[Mapping[str, object]],
    *,
    filters: Sequence[tuple[str, str]],
    bucket_key: str,
) -> list[dict[str, object]]:
    filtered_rows = list(rows)
    for filter_key, filter_value in filters:
        filtered_rows = [
            row
            for row in filtered_rows
            if str(row.get(filter_key) or "missing") == filter_value
        ]
    return [
        _aggregate_item_asdict(item)
        for item in build_trigger_proxy_aggregate_items(
            _build_trade_date_bucket_rows(
                filtered_rows,
                bucket_key=bucket_key,
            ),
            bucket_key="trade_date_bucket",
        )
    ]


def _build_compound_bucket_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    first_key: str,
    second_key: str,
) -> list[dict[str, object]]:
    compound_rows: list[dict[str, object]] = []
    for row in rows:
        first = str(row.get(first_key) or "missing")
        second = str(row.get(second_key) or "missing")
        compound_rows.append(
            {
                **row,
                "compound_bucket": f"{first}|{second}",
            }
        )
    return compound_rows


def _build_filtered_bucket_items(
    rows: Sequence[Mapping[str, object]],
    *,
    bucket_key: str,
    filter_key: str,
    filter_value: str,
) -> list[dict[str, object]]:
    filtered_rows = [
        row
        for row in rows
        if str(row.get(filter_key) or "missing") == filter_value
    ]
    return [
        _aggregate_item_asdict(item)
        for item in build_trigger_proxy_aggregate_items(
            filtered_rows,
            bucket_key=bucket_key,
        )
    ]


def _build_filtered_bucket_items_multi(
    rows: Sequence[Mapping[str, object]],
    *,
    bucket_key: str,
    filters: Sequence[tuple[str, str]],
) -> list[dict[str, object]]:
    filtered_rows = list(rows)
    for filter_key, filter_value in filters:
        filtered_rows = [
            row
            for row in filtered_rows
            if str(row.get(filter_key) or "missing") == filter_value
        ]
    return [
        _aggregate_item_asdict(item)
        for item in build_trigger_proxy_aggregate_items(
            filtered_rows,
            bucket_key=bucket_key,
        )
    ]


def _build_projection_band_items_filtered_multi(
    rows: Sequence[Mapping[str, object]],
    *,
    bucket_key: str,
    bucket_order: Sequence[str],
    filters: Sequence[tuple[str, str]],
) -> list[dict[str, object]]:
    filtered_rows = list(rows)
    for filter_key, filter_value in filters:
        filtered_rows = [
            row
            for row in filtered_rows
            if str(row.get(filter_key) or "missing") == filter_value
        ]
    return _build_projection_band_items(
        filtered_rows,
        bucket_key=bucket_key,
        bucket_order=bucket_order,
    )


def _build_filtered_samples_multi(
    rows: Sequence[Mapping[str, object]],
    *,
    filters: Sequence[tuple[str, str]],
    sample_limit: int,
) -> list[Mapping[str, object]]:
    filtered_rows = list(rows)
    for filter_key, filter_value in filters:
        filtered_rows = [
            row
            for row in filtered_rows
            if str(row.get(filter_key) or "missing") == filter_value
        ]
    return filtered_rows[: max(0, int(sample_limit))]


def _build_pre_buy_staging_comparison_report(
    rows: Sequence[Mapping[str, object]],
    *,
    cohort_value: str,
    sample_limit: int,
) -> dict[str, object]:
    filters = (
        ("source_type", "core"),
        ("pre_buy_staging_cohort", cohort_value),
    )
    return {
        "entry_score_band_items": _build_filtered_bucket_items_multi(
            rows,
            bucket_key="effective_entry_score_band",
            filters=filters,
        ),
        "buy_gap_band_items": _build_filtered_bucket_items_multi(
            rows,
            bucket_key="effective_buy_candidate_threshold_gap_band",
            filters=filters,
        ),
        "buy_ranking_gap_band_items": _build_filtered_bucket_items_multi(
            rows,
            bucket_key="effective_buy_ranking_gap_band",
            filters=filters,
        ),
        "activity_gate_items": _build_filtered_bucket_items_multi(
            rows,
            bucket_key="pre_buy_staging_activity_gate",
            filters=filters,
        ),
        "activity_detail_items": _build_filtered_bucket_items_multi(
            rows,
            bucket_key="pre_buy_staging_activity_detail",
            filters=filters,
        ),
        "watch_eligibility_path_items": _build_filtered_bucket_items_multi(
            rows,
            bucket_key="watch_eligibility_block_path",
            filters=filters,
        ),
        "projection_items": _build_projection_band_items_filtered_multi(
            rows,
            bucket_key="effective_entry_score_band",
            bucket_order=(
                "buy_ready",
                "near_buy_floor",
                "watch_band",
                "observe_band",
                "below_observe_floor",
                "entry_missing",
            ),
            filters=filters,
        ),
        "trade_date_projection_items": _build_trade_date_filtered_projection_items_multi(
            rows,
            filters=filters,
        ),
        "trade_date_activity_gate_items": _build_trade_date_filtered_bucket_items_multi(
            rows,
            filters=filters,
            bucket_key="pre_buy_staging_activity_gate",
        ),
        "trade_date_activity_detail_items": _build_trade_date_filtered_bucket_items_multi(
            rows,
            filters=filters,
            bucket_key="pre_buy_staging_activity_detail",
        ),
        "samples": _build_filtered_samples_multi(
            rows,
            filters=filters,
            sample_limit=sample_limit,
        ),
    }


def _build_pre_buy_staging_activity_detail_focus_report(
    rows: Sequence[Mapping[str, object]],
    *,
    activity_detail_value: str,
    sample_limit: int,
) -> dict[str, object]:
    filters = (
        ("source_type", "core"),
        ("pre_buy_staging_activity_detail", activity_detail_value),
    )
    return {
        "cohort_items": _build_filtered_bucket_items_multi(
            rows,
            bucket_key="pre_buy_staging_cohort",
            filters=filters,
        ),
        "entry_score_band_items": _build_filtered_bucket_items_multi(
            rows,
            bucket_key="effective_entry_score_band",
            filters=filters,
        ),
        "buy_gap_band_items": _build_filtered_bucket_items_multi(
            rows,
            bucket_key="effective_buy_candidate_threshold_gap_band",
            filters=filters,
        ),
        "buy_ranking_gap_band_items": _build_filtered_bucket_items_multi(
            rows,
            bucket_key="effective_buy_ranking_gap_band",
            filters=filters,
        ),
        "first_order_bottleneck_items": _build_filtered_bucket_items_multi(
            rows,
            bucket_key="pre_buy_boundary_first_order_bottleneck",
            filters=filters,
        ),
        "watch_eligibility_path_items": _build_filtered_bucket_items_multi(
            rows,
            bucket_key="watch_eligibility_block_path",
            filters=filters,
        ),
        "cohort_projection_items": _build_projection_band_items_filtered_multi(
            rows,
            bucket_key="pre_buy_staging_cohort",
            bucket_order=(
                "entry_score_0_55_to_0_65",
                "entry_score_ge_0_52",
                "watch_from_entry_setup",
            ),
            filters=filters,
        ),
        "first_order_bottleneck_projection_items": _build_projection_band_items_filtered_multi(
            rows,
            bucket_key="pre_buy_boundary_first_order_bottleneck",
            bucket_order=(
                "activity_first_entry_ready",
                "activity_first_small_entry_gap",
                "activity_first_moderate_entry_gap",
                "activity_with_large_entry_gap",
                "ranking_gap_before_activity_small_entry_gap",
                "ranking_gap_before_activity_moderate_entry_gap",
                "ranking_gap_before_activity_entry_ready",
                "mixed_or_unclassified",
            ),
            filters=filters,
        ),
        "activity_counterfactual_next_gate_items": _build_filtered_bucket_items_multi(
            rows,
            bucket_key="pre_buy_boundary_activity_counterfactual_next_gate",
            filters=filters,
        ),
        "activity_counterfactual_next_gate_projection_items": _build_projection_band_items_filtered_multi(
            rows,
            bucket_key="pre_buy_boundary_activity_counterfactual_next_gate",
            bucket_order=(
                "signal_before_activity_release",
                "buy_shape_after_activity_large_entry_gap",
                "buy_shape_after_activity_moderate_entry_gap",
                "buy_shape_after_activity_small_entry_gap",
                "ranking_after_activity",
                "strategy_after_activity",
                "topk_candidate_after_activity_unknown",
                "topk_selected_after_activity",
                "buy_shape_after_activity_entry_ready",
                "submit_after_activity",
                "submitted_after_activity",
                "mixed_or_unclassified",
            ),
            filters=filters,
        ),
        "activity_buy_shape_detail_items": _build_filtered_bucket_items_multi(
            rows,
            bucket_key="pre_buy_boundary_activity_buy_shape_detail",
            filters=filters,
        ),
        "activity_buy_shape_detail_projection_items": _build_projection_band_items_filtered_multi(
            rows,
            bucket_key="pre_buy_boundary_activity_buy_shape_detail",
            bucket_order=(
                "watch_from_entry_setup|entry_ready",
                "watch_from_entry_setup|small_entry_gap",
                "watch_from_entry_setup|moderate_entry_gap",
                "watch_from_entry_setup|large_entry_gap",
                "watch_from_exit_setup|entry_ready",
                "watch_from_exit_setup|small_entry_gap",
                "watch_from_exit_setup|moderate_entry_gap",
                "watch_from_exit_setup|large_entry_gap",
                "core_watch_gap_bridge|entry_ready",
                "core_watch_gap_bridge|small_entry_gap",
                "core_watch_gap_bridge|moderate_entry_gap",
                "core_watch_gap_bridge|large_entry_gap",
                "entry_below_buy_threshold|entry_ready",
                "entry_below_buy_threshold|small_entry_gap",
                "entry_below_buy_threshold|moderate_entry_gap",
                "entry_below_buy_threshold|large_entry_gap",
                "watch_threshold_only|entry_ready",
                "watch_threshold_only|small_entry_gap",
                "watch_threshold_only|moderate_entry_gap",
                "watch_threshold_only|large_entry_gap",
                "ranking_below_buy_projection_threshold|entry_ready",
                "ranking_below_buy_projection_threshold|small_entry_gap",
                "ranking_below_buy_projection_threshold|moderate_entry_gap",
                "ranking_below_buy_projection_threshold|large_entry_gap",
                "watch_other|entry_ready",
                "watch_other|small_entry_gap",
                "watch_other|moderate_entry_gap",
                "watch_other|large_entry_gap",
                "unknown_buy_shape_reason|entry_ready",
                "unknown_buy_shape_reason|small_entry_gap",
                "unknown_buy_shape_reason|moderate_entry_gap",
                "unknown_buy_shape_reason|large_entry_gap",
                "non_buy_shape_after_activity",
            ),
            filters=filters,
        ),
        "trade_date_cohort_items": _build_trade_date_filtered_bucket_items_multi(
            rows,
            filters=filters,
            bucket_key="pre_buy_staging_cohort",
        ),
        "trade_date_first_order_bottleneck_items": _build_trade_date_filtered_bucket_items_multi(
            rows,
            filters=filters,
            bucket_key="pre_buy_boundary_first_order_bottleneck",
        ),
        "trade_date_activity_counterfactual_next_gate_items": _build_trade_date_filtered_bucket_items_multi(
            rows,
            filters=filters,
            bucket_key="pre_buy_boundary_activity_counterfactual_next_gate",
        ),
        "trade_date_activity_buy_shape_detail_items": _build_trade_date_filtered_bucket_items_multi(
            rows,
            filters=filters,
            bucket_key="pre_buy_boundary_activity_buy_shape_detail",
        ),
        "trade_date_projection_items": _build_trade_date_filtered_projection_items_multi(
            rows,
            filters=filters,
        ),
        "samples": _build_filtered_samples_multi(
            rows,
            filters=filters,
            sample_limit=sample_limit,
        ),
    }


def _build_pre_buy_boundary_buy_shape_detail_report(
    rows: Sequence[Mapping[str, object]],
    *,
    buy_shape_detail_value: str,
    sample_limit: int,
) -> dict[str, object]:
    filters = (
        ("source_type", "core"),
        ("pre_buy_boundary_activity_buy_shape_detail", buy_shape_detail_value),
    )
    return {
        "cohort_items": _build_filtered_bucket_items_multi(
            rows,
            bucket_key="pre_buy_boundary_activity_buy_shape_detail",
            filters=filters,
        ),
        "entry_score_band_items": _build_filtered_bucket_items_multi(
            rows,
            bucket_key="effective_entry_score_band",
            filters=filters,
        ),
        "buy_gap_band_items": _build_filtered_bucket_items_multi(
            rows,
            bucket_key="effective_buy_candidate_threshold_gap_band",
            filters=filters,
        ),
        "buy_ranking_gap_band_items": _build_filtered_bucket_items_multi(
            rows,
            bucket_key="effective_buy_ranking_gap_band",
            filters=filters,
        ),
        "activity_gate_items": _build_filtered_bucket_items_multi(
            rows,
            bucket_key="pre_buy_staging_activity_gate",
            filters=filters,
        ),
        "watch_eligibility_path_items": _build_filtered_bucket_items_multi(
            rows,
            bucket_key="watch_eligibility_block_path",
            filters=filters,
        ),
        "projection_items": _build_projection_band_items_filtered_multi(
            rows,
            bucket_key="pre_buy_boundary_activity_buy_shape_detail",
            bucket_order=(buy_shape_detail_value,),
            filters=filters,
        ),
        "trade_date_projection_items": _build_trade_date_filtered_projection_items_multi(
            rows,
            filters=filters,
        ),
        "trade_date_entry_score_band_items": _build_trade_date_filtered_bucket_items_multi(
            rows,
            filters=filters,
            bucket_key="effective_entry_score_band",
        ),
        "trade_date_buy_gap_band_items": _build_trade_date_filtered_bucket_items_multi(
            rows,
            filters=filters,
            bucket_key="effective_buy_candidate_threshold_gap_band",
        ),
        "samples": _build_filtered_samples_multi(
            rows,
            filters=filters,
            sample_limit=sample_limit,
        ),
    }


def _classify_core_risk_off_moderate_gate(
    *,
    active: bool,
    overall: float | None,
    slow: float | None,
    entry_score: float | None,
    ranking_score: float | None,
    shadow_activity_pass: bool,
    shadow_strategy_pass: bool,
    moderate_overall_min: float = -0.25,
    moderate_slow_min: float = -0.25,
) -> str:
    if not active:
        return "inactive"
    if (
        overall is None
        or slow is None
        or overall < moderate_overall_min
        or slow < moderate_slow_min
    ):
        return "signal_window_miss"
    if entry_score is None or entry_score < 0.12:
        return "entry_below_0_12"
    if ranking_score is None or ranking_score < 0.26:
        return "ranking_below_0_26"
    if not shadow_activity_pass:
        return "activity_blocked"
    if not shadow_strategy_pass:
        return "strategy_blocked"
    return "moderate_ready"


def _classify_core_risk_off_blocking_reason(
    *,
    active: bool,
    shadow_floor_bucket: str,
    overall: float | None,
    slow: float | None,
    entry_score: float | None,
    ranking_score: float | None,
    shadow_activity_pass: bool,
    shadow_strategy_pass: bool,
    mild_overall_min: float = -0.10,
    mild_slow_min: float = -0.15,
) -> str:
    if not active:
        return "inactive"
    if overall is None:
        return "overall_missing"
    if slow is None:
        return "slow_missing"
    if shadow_floor_bucket == "strict_pass":
        return "strict_pass"
    if shadow_floor_bucket == "mild_relax":
        return "mild_relax_pass"
    if shadow_floor_bucket == "moderate_relax":
        return "moderate_relax_pass"
    if overall < mild_overall_min:
        return "overall_below_mild_floor"
    if slow < mild_slow_min:
        return "slow_below_mild_floor"
    if entry_score is None or entry_score < 0.12:
        return "entry_below_0_12"
    if ranking_score is None or ranking_score < 0.26:
        return "ranking_below_0_26"
    if not shadow_activity_pass:
        return "activity_blocked"
    if not shadow_strategy_pass:
        return "strategy_blocked"
    return "deep_negative_other"


def _derive_shadow_floor_bucket(
    *,
    overall: float | None,
    slow: float | None,
    entry_score: float,
    ranking_score: float | None,
    shadow_activity_pass: bool,
    shadow_strategy_pass: bool,
    mild_overall_min: float,
    mild_slow_min: float,
    moderate_overall_min: float,
    moderate_slow_min: float,
    reason_prefix: str,
) -> tuple[str, bool, tuple[str, ...]]:
    if overall is not None and overall >= 0.0 and slow is not None and slow >= -0.05:
        return ("strict_pass", True, (f"{reason_prefix}_strict_pass",))
    if overall is not None and overall >= mild_overall_min and slow is not None and slow >= mild_slow_min:
        return ("mild_relax", True, (f"{reason_prefix}_mild_relax_pass",))
    if (
        overall is not None
        and overall >= moderate_overall_min
        and slow is not None
        and slow >= moderate_slow_min
        and entry_score >= 0.12
        and ranking_score is not None
        and ranking_score >= 0.26
        and shadow_activity_pass
        and shadow_strategy_pass
    ):
        return ("moderate_relax", True, (f"{reason_prefix}_moderate_relax_pass",))
    return ("deep_negative", False, (f"{reason_prefix}_deep_negative",))
