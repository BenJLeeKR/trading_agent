#!/usr/bin/env python3
"""
Backfill: ``broker_fill_snapshots`` 기반 과거 체결 synthetic ``fill_events`` 복원.

설계 근거: docs/00_foundational_design/detailed_design/16_broker_fill_
snapshot_historical_backfill_design.md, 실행 계획:
docs/40_action_plans/broker_fill_snapshot_historical_backfill_action_plan.md

이 스크립트는 계좌×종목 하나에 대해 16번 문서의 원가 완결성 기준을
판정하고(:func:`agent_trading.services.historical_fill_backfill.
build_backfill_plan`), 결과를 리포트로 출력한다. ``--mode apply``를
명시하지 않으면 **절대 DB에 쓰지 않는다** — 기본값은 항상 dry-run이다.

사용법::

    # dry-run(기본값): 계산 결과만 리포트, DB 변경 없음
    python3 scripts/backfill_broker_fill_snapshot_historical_fills.py \\
        --account-id <uuid> --instrument-id <uuid> --start-date 2026-08-01

    # apply: 실제로 fill_events에 append (dry-run과 완전히 같은 계산 결과를
    # 그대로 반영한다 — 계획 재계산 없이 build_backfill_plan()의 출력을
    # apply_backfill_plan()에 그대로 넘긴다)
    python3 scripts/backfill_broker_fill_snapshot_historical_fills.py \\
        --account-id <uuid> --instrument-id <uuid> --start-date 2026-08-01 \\
        --mode apply

idempotency
-----------
같은 대상을 다시 실행해도 안전하다. ``apply_backfill_plan()``이
``broker_fill_id`` 우선(``fill_events`` UNIQUE 제약에 의존) +
``(fill_timestamp, fill_price, fill_quantity)`` composite key fallback으로
이미 append된 synthetic fill을 재판별해 skip한다(16번 문서 §6.1). 대상이
원가 완결성 기준을 만족하지 못하면(``eligible=False``) apply 모드에서도
아무것도 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date
from typing import Optional
from uuid import UUID

from agent_trading.db.connection import DatabaseConfig, close_pool, create_pool
from agent_trading.db.transaction import transaction
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories
from agent_trading.services.historical_fill_backfill import (
    BackfillPlan,
    apply_backfill_plan,
    build_backfill_plan,
)

logger = logging.getLogger(__name__)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "broker_fill_snapshots 기반 과거 체결 synthetic fill backfill "
            "(계좌 1개 x 종목 1개 단위)"
        ),
    )
    parser.add_argument("--account-id", type=str, required=True, help="대상 account_id")
    parser.add_argument("--instrument-id", type=str, required=True, help="대상 instrument_id")
    parser.add_argument(
        "--start-date",
        type=str,
        required=True,
        help="backfill 기간 하한(KST 날짜, 예: 2026-08-01). "
        "실제 원가 완결성 시작점(완전 청산 지점)은 이보다 이전일 수 있다 — "
        "이 값은 대상 filled 주문을 찾는 창(window)의 하한일 뿐이다.",
    )
    parser.add_argument(
        "--mode",
        choices=("dry-run", "apply"),
        default="dry-run",
        help="dry-run(기본값): 계산 결과만 리포트, DB 변경 없음. "
        "apply: 실제 fill_events append + recompute_queue 등록.",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="상세 로그 출력")
    return parser.parse_args(argv)


def _print_plan_report(plan: BackfillPlan) -> None:
    lines = [
        "=== broker_fill_snapshots historical backfill — dry-run 리포트 ===",
        f"  account_id:          {plan.account_id}",
        f"  instrument_id:       {plan.instrument_id}",
        f"  start_date(KST 하한): {plan.start_date.isoformat()}",
        f"  eligible:            {plan.eligible}",
    ]
    if not plan.eligible:
        lines.append(f"  exclusion_reason:    {plan.exclusion_reason}")
        if plan.zero_crossing_at is not None:
            lines.append(f"  zero_crossing_at:    {plan.zero_crossing_at.isoformat()}")
        print("\n".join(lines))
        return

    lines.append(f"  zero_crossing_at:    {plan.zero_crossing_at.isoformat()}")
    lines.append(f"  대상 주문 수:         {len(plan.order_details)}")
    buy_count = sum(1 for d in plan.order_details if d.side.value == "buy")
    sell_count = sum(1 for d in plan.order_details if d.side.value == "sell")
    lines.append(f"    - 매수:            {buy_count}")
    lines.append(f"    - 매도:            {sell_count}")
    lines.append(f"  생성 예정 synthetic fill 수: {len(plan.synthetic_fills)}")
    lines.append(f"  예상 최종 잔량:       {plan.expected_final_quantity}")
    lines.append(f"  브로커 보고 잔량:     {plan.broker_reported_quantity}")
    lines.append(f"  잔량 정합성 일치:     {plan.broker_reported_quantity_matches}")
    lines.append("  주문별 상세:")
    for detail in plan.order_details:
        lines.append(
            f"    - order={detail.order_request_id} side={detail.side.value} "
            f"requested={detail.requested_quantity} "
            f"snapshot_count={detail.snapshot_count} "
            f"final_cumulative={detail.final_cumulative_quantity} "
            f"synthetic_fills={len(detail.candidates)}"
        )
    lines.append("  append 예정 fill_events 핵심 필드 요약:")
    for candidate in plan.synthetic_fills:
        lines.append(
            f"    - order={candidate.order_request_id} "
            f"side={candidate.side.value} "
            f"qty={candidate.fill_quantity} price={candidate.fill_price} "
            f"fee={candidate.fee} tax={candidate.tax} "
            f"fee_tax_source={candidate.fee_tax_source.value} "
            f"fill_timestamp={candidate.fill_timestamp.isoformat()} "
            f"broker_fill_id={candidate.broker_fill_id} "
            f"source_snapshot={candidate.source_broker_fill_snapshot_id}"
        )
    print("\n".join(lines))


async def run_backfill(repos: RepositoryContainer, args: argparse.Namespace) -> int:
    """계획 계산 + 리포트 출력 + (apply 모드면) 실제 반영까지 수행한다.

    ``repos``를 인자로 받아 DB 연결 준비/커밋 책임과 분리한다 —
    ``tests/scripts/test_backfill_broker_fill_snapshot_historical_fills.py``가
    in-memory ``RepositoryContainer``로 이 함수만 독립적으로 검증할 수
    있게 하기 위함이다(``scripts/backfill_reconcile_required_orders.py``의
    ``run_backfill(repos, args)`` 관례와 동일).
    """
    account_id = UUID(args.account_id)
    instrument_id = UUID(args.instrument_id)
    start_date = date.fromisoformat(args.start_date)

    plan = await build_backfill_plan(
        repos,
        account_id=account_id,
        instrument_id=instrument_id,
        start_date=start_date,
    )
    _print_plan_report(plan)

    if args.mode == "dry-run":
        logger.info("dry-run 모드 — DB에 아무것도 쓰지 않았다.")
        return 0 if plan.eligible else 1

    # --mode apply
    result = await apply_backfill_plan(repos, plan)
    print(
        "=== apply 결과 ===\n"
        f"  applied:                {result.applied}\n"
        f"  fills_appended:         {result.fills_appended}\n"
        f"  fills_skipped_duplicate:{result.fills_skipped_duplicate}\n"
        f"  recompute_queue_item_id:{result.recompute_queue_item_id}"
    )
    if result.applied:
        logger.info("apply 완료.")
    else:
        logger.info("적용 대상 없음(eligible=False 또는 신규 fill 없음) — 아무것도 쓰지 않았다.")
    return 0 if plan.eligible else 1


async def _run(args: argparse.Namespace) -> int:
    """DB에 연결해 :func:`run_backfill`을 실행하고, apply 모드에서 실제로
    반영된 경우에만 commit한다."""
    config = DatabaseConfig()
    await create_pool(config)
    try:
        async with transaction() as tx:
            repos: RepositoryContainer = build_postgres_repositories(tx)
            exit_code = await run_backfill(repos, args)
            if args.mode == "apply" and exit_code == 0:
                # eligible=False였으면 exit_code=1이라 여기 도달하지 않고,
                # 어떤 DB write도 시도되지 않은 채 트랜잭션이 롤백된다.
                # eligible=True이면 fills_appended=0(전부 중복)이어도
                # commit 자체는 안전하다(변경 없는 트랜잭션의 no-op commit).
                await tx.commit()
            return exit_code
    finally:
        await close_pool()


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
