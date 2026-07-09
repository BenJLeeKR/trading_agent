from __future__ import annotations

import asyncio
import json
import os
from datetime import date
from statistics import mean

import asyncpg


ACTIVE_ROWS = [
    ("2026-07-06", "000080", "KRX"),
    ("2026-07-06", "000100", "KRX"),
    ("2026-07-06", "000120", "KRX"),
    ("2026-07-06", "000210", "KRX"),
    ("2026-07-06", "000670", "KRX"),
    ("2026-07-06", "000720", "KRX"),
    ("2026-07-06", "000880", "KRX"),
    ("2026-07-07", "000210", "KRX"),
    ("2026-07-07", "000670", "KRX"),
    ("2026-07-07", "000720", "KRX"),
    ("2026-07-07", "001040", "KRX"),
    ("2026-07-07", "001430", "KRX"),
    ("2026-07-07", "001680", "KRX"),
    ("2026-07-07", "002030", "KRX"),
    ("2026-07-08", "000100", "KRX"),
    ("2026-07-08", "000210", "KRX"),
    ("2026-07-08", "000670", "KRX"),
    ("2026-07-08", "000720", "KRX"),
    ("2026-07-08", "001430", "KRX"),
    ("2026-07-08", "002030", "KRX"),
]


def _bucket_return_3m(value: float | None) -> str:
    if value is None:
        return "missing"
    if value <= -15:
        return "<=-15"
    if value <= -10:
        return "(-15,-10]"
    if value <= -5:
        return "(-10,-5]"
    if value <= -2:
        return "(-5,-2]"
    return ">-2"


def _bucket_sma60(value: float | None) -> str:
    if value is None:
        return "missing"
    if value <= -12:
        return "<=-12"
    if value <= -8:
        return "(-12,-8]"
    if value <= -3:
        return "(-8,-3]"
    if value <= -1:
        return "(-3,-1]"
    return ">-1"


async def main() -> None:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    rows: list[dict[str, object]] = []
    for trade_date, symbol, market in ACTIVE_ROWS:
        row = await conn.fetchrow(
            """
            SELECT
                s.return_3m_pct,
                s.price_vs_sma_60_pct,
                s.slow_score,
                s.overall_score,
                s.component_scores_json
            FROM trading.signal_feature_snapshots s
            JOIN trading.instruments i ON i.instrument_id = s.instrument_id
            WHERE i.symbol = $1
              AND i.market_code = $2
              AND (s.snapshot_at AT TIME ZONE 'Asia/Seoul')::date = $3
            ORDER BY s.created_at DESC
            LIMIT 1
            """,
            symbol,
            market,
            date.fromisoformat(trade_date),
        )
        if row is None:
            rows.append(
                {
                    "trade_date": trade_date,
                    "symbol": symbol,
                    "market": market,
                    "missing": True,
                }
            )
            continue
        component_scores = row["component_scores_json"]
        if isinstance(component_scores, str):
            component_scores = json.loads(component_scores)
        rows.append(
            {
                "trade_date": trade_date,
                "symbol": symbol,
                "market": market,
                "return_3m_pct": (
                    float(row["return_3m_pct"])
                    if row["return_3m_pct"] is not None
                    else None
                ),
                "price_vs_sma_60_pct": (
                    float(row["price_vs_sma_60_pct"])
                    if row["price_vs_sma_60_pct"] is not None
                    else None
                ),
                "slow_score": (
                    float(row["slow_score"]) if row["slow_score"] is not None else None
                ),
                "overall_score": (
                    float(row["overall_score"])
                    if row["overall_score"] is not None
                    else None
                ),
                "slow_momentum": (
                    component_scores.get("slow_momentum")
                    if isinstance(component_scores, dict)
                    else None
                ),
                "slow_trend": (
                    component_scores.get("slow_trend")
                    if isinstance(component_scores, dict)
                    else None
                ),
                "shadow_reason_codes_v2": (
                    component_scores.get("shadow_reason_codes_v2")
                    if isinstance(component_scores, dict)
                    else None
                ),
            }
        )
    await conn.close()

    matched = [row for row in rows if not row.get("missing")]
    return_buckets: dict[str, int] = {}
    sma60_buckets: dict[str, int] = {}
    slow_momentum_counts: dict[str, int] = {}
    slow_trend_counts: dict[str, int] = {}

    for row in matched:
        return_bucket = _bucket_return_3m(row["return_3m_pct"])  # type: ignore[arg-type]
        sma60_bucket = _bucket_sma60(row["price_vs_sma_60_pct"])  # type: ignore[arg-type]
        return_buckets[return_bucket] = return_buckets.get(return_bucket, 0) + 1
        sma60_buckets[sma60_bucket] = sma60_buckets.get(sma60_bucket, 0) + 1
        slow_momentum_key = str(row["slow_momentum"])
        slow_trend_key = str(row["slow_trend"])
        slow_momentum_counts[slow_momentum_key] = (
            slow_momentum_counts.get(slow_momentum_key, 0) + 1
        )
        slow_trend_counts[slow_trend_key] = (
            slow_trend_counts.get(slow_trend_key, 0) + 1
        )

    payload = {
        "matched_count": len(matched),
        "avg_return_3m_pct": round(
            mean(
                row["return_3m_pct"]
                for row in matched
                if row["return_3m_pct"] is not None
            ),
            4,
        ),
        "avg_price_vs_sma_60_pct": round(
            mean(
                row["price_vs_sma_60_pct"]
                for row in matched
                if row["price_vs_sma_60_pct"] is not None
            ),
            4,
        ),
        "return_3m_buckets": return_buckets,
        "price_vs_sma60_buckets": sma60_buckets,
        "slow_momentum_counts": slow_momentum_counts,
        "slow_trend_counts": slow_trend_counts,
        "rows": matched,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
