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
CORE_RISK_OFF_FLOOR_REPORT_BUCKETS: tuple[str, ...] = (
    "strict_pass",
    "mild_relax",
    "moderate_relax",
    "deep_negative",
    "inactive",
)


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
