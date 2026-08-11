#!/usr/bin/env python3
"""Loss-cut shadow 관측 결과를 조회하는 read-only dump 스크립트.

``trade_decisions.decision_json->'loss_cut_shadow'``에 기록된 shadow
관측(손실률 기반 loss-cut이 있었으면 발동했을지 여부를 관측만 하고
실제 결정에는 개입하지 않는 기록)을 최근 순으로 조회해 출력한다.

이 스크립트는 순수 조회 전용이다 — DB write, 주문 경로, 실주문
결정에는 어떤 영향도 주지 않는다. ``GET /trade-decisions/{id}``
API도 동일한 ``decision_json`` 필드를 통해 이 정보를 노출하지만,
이 스크립트는 ``triggered=true`` 관측만 모아 한번에 훑어보는 용도의
보조 read path다.

Usage:
    python scripts/dump_loss_cut_shadow_observations.py
    python scripts/dump_loss_cut_shadow_observations.py --only-triggered
    python scripts/dump_loss_cut_shadow_observations.py --limit 50 --format json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Any

import asyncpg
from agent_trading.db.connection import get_pool
from agent_trading.runtime.bootstrap import postgres_runtime

logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Dump loss_cut_shadow observations recorded in "
            "trade_decisions.decision_json (read-only, no writes)."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum rows to return (default 100).",
    )
    parser.add_argument(
        "--only-triggered",
        action="store_true",
        help="Only show observations where triggered=true (soft or hard).",
    )
    parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="Output format (default table).",
    )
    return parser.parse_args()


async def fetch_loss_cut_shadow_observations(
    pool: asyncpg.Pool,
    *,
    limit: int,
    only_triggered: bool,
) -> list[dict[str, Any]]:
    """decision_json->'loss_cut_shadow'가 존재하는 trade_decisions 행을 조회한다."""
    where_extra = ""
    if only_triggered:
        where_extra = (
            "AND (decision_json->'loss_cut_shadow'->>'triggered')::boolean IS TRUE"
        )
    query = f"""
        SELECT
            trade_decision_id,
            decision_context_id,
            decision_type,
            side,
            created_at,
            decision_json->'loss_cut_shadow' AS loss_cut_shadow
        FROM trading.trade_decisions
        WHERE decision_json ? 'loss_cut_shadow'
        {where_extra}
        ORDER BY created_at DESC
        LIMIT $1
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, limit)
    return [dict(row) for row in rows]


def _print_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("No loss_cut_shadow observations found.")
        return
    for row in rows:
        shadow = row["loss_cut_shadow"]
        if isinstance(shadow, str):
            shadow = json.loads(shadow)
        print(
            f"trade_decision_id={row['trade_decision_id']} "
            f"decision_type={row['decision_type']} side={row['side']} "
            f"created_at={row['created_at']} "
            f"account_id={shadow.get('account_id')} "
            f"instrument_id={shadow.get('instrument_id')} "
            f"source_type={shadow.get('source_type')} "
            f"loss_pct={shadow.get('loss_pct')} "
            f"triggered={shadow.get('triggered')} tier={shadow.get('tier')} "
            f"actual_decision_type={shadow.get('actual_decision_type')} "
            f"shadow_only={shadow.get('shadow_only')}"
        )


def _print_json(rows: list[dict[str, Any]]) -> None:
    out = []
    for row in rows:
        shadow = row["loss_cut_shadow"]
        if isinstance(shadow, str):
            shadow = json.loads(shadow)
        out.append(
            {
                "trade_decision_id": str(row["trade_decision_id"]),
                "decision_context_id": str(row["decision_context_id"]),
                "decision_type": row["decision_type"],
                "side": row["side"],
                "created_at": row["created_at"].isoformat(),
                "loss_cut_shadow": shadow,
            }
        )
    print(json.dumps(out, ensure_ascii=False, indent=2))


async def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    async with postgres_runtime(run_migrations=False):
        pool = await get_pool()
        rows = await fetch_loss_cut_shadow_observations(
            pool, limit=args.limit, only_triggered=args.only_triggered
        )

    if args.format == "json":
        _print_json(rows)
    else:
        _print_table(rows)


if __name__ == "__main__":
    asyncio.run(main())
