#!/usr/bin/env python3
"""
Backfill: 기존 RECONCILE_REQUIRED 상태 주문에 reconciliation run 생성 + order link.

RECONCILE_REQUIRED로 stuck된 기존 주문들을 찾아
``ReconciliationService.trigger_and_link()``를 호출하여 reconciliation run을 생성하고
order와의 link도 함께 생성한다.

사용법::

    # Dry-run: 주문만 조회하고 실제 trigger는 실행하지 않음
    python3 scripts/backfill_reconcile_required_orders.py --dry-run

    # 최대 10건만 처리
    python3 scripts/backfill_reconcile_required_orders.py --limit 10

    # 특정 주문만 처리
    python3 scripts/backfill_reconcile_required_orders.py --order-id 400353e9-...

    # 특정 계정의 모든 stuck 주문 처리
    python3 scripts/backfill_reconcile_required_orders.py --account-id <uuid>

    # 상세 로그 출력
    python3 scripts/backfill_reconcile_required_orders.py --verbose

idempotency
-----------
- ``ReconciliationService.trigger_and_link()``는 active reconciliation run이 이미 존재하면
  재사용하므로 중복 실행에 안전하다.
- ``--dry-run`` 모드에서는 DB 변경 없이 대상 주문만 식별한다.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Optional
from uuid import UUID

from agent_trading.db.connection import DatabaseConfig, create_pool, close_pool
from agent_trading.db.transaction import transaction
from agent_trading.domain.enums import OrderStatus
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import OrderQuery
from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories
from agent_trading.services.reconciliation_service import ReconciliationService

logger = logging.getLogger(__name__)

TRIGGER_TYPE = "requires_reconciliation"
"""``trigger_type`` 값.

DB CHECK 제약 조건(``ck_reconciliation_runs_trigger``)에 포함된
안전한 값 중 하나를 사용. ``"backfill_reconcile_required"``는 제약 조건에
없으므로 ``"requires_reconciliation"``을 사용한다.
"""


# ── CLI 인자 ────────────────────────────────────────────────────────────────


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill reconciliation runs for stuck RECONCILE_REQUIRED orders",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="주문만 조회하고 실제 trigger는 실행하지 않음",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="최대 처리 건수 (기본: 전체)",
    )
    parser.add_argument(
        "--order-id",
        type=str,
        default=None,
        help="특정 order_request_id만 처리 (쉼표로 구분하여 여러 개 가능)",
    )
    parser.add_argument(
        "--account-id",
        type=str,
        default=None,
        help="특정 account_id만 처리 (쉼표로 구분하여 여러 개 가능)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="상세 로그 출력",
    )
    return parser.parse_args(argv)


# ── 핵심 backfill 로직 ─────────────────────────────────────────────────────


async def run_backfill(
    repos: RepositoryContainer,
    args: argparse.Namespace,
) -> int:
    """Backfill 로직을 실행한다.

    Parameters
    ----------
    repos : RepositoryContainer
        사용할 repository container. (Postgres 또는 in-memory)
    args : argparse.Namespace
        CLI 인자.

    Returns
    -------
    int
        종료 코드 (0 = 성공, 1 = 하나 이상 실패).
    """
    recon_service = ReconciliationService(repos)

    # ── Stuck 주문 조회 ──
    query = OrderQuery(status=OrderStatus.RECONCILE_REQUIRED, limit=args.limit or 1000)
    orders = await repos.orders.list(query)

    # ── 필터 적용 ──
    if args.order_id:
        target_uuids = [UUID(s.strip()) for s in args.order_id.split(",")]
        orders = [o for o in orders if o.order_request_id in target_uuids]
    if args.account_id:
        target_account_uuids = [UUID(s.strip()) for s in args.account_id.split(",")]
        orders = [o for o in orders if o.account_id in target_account_uuids]

    # ── Summary counters ──
    total = len(orders)
    scanned = 0
    triggered = 0
    reused = 0
    skipped = 0
    failed = 0

    logger.info("Found %d stuck RECONCILE_REQUIRED order(s)", total)

    for order in orders:
        scanned += 1

        # BrokerOrder 조회 (로깅용 broker_native_order_id 확보)
        broker_orders = await repos.broker_orders.list_by_order_request(
            order.order_request_id,
        )
        broker_native_ids = [
            bo.broker_native_order_id
            for bo in broker_orders
            if bo.broker_native_order_id
        ]

        # Idempotency check: active reconciliation run이 이미 존재하면 skip
        active_run = await recon_service.get_active_run(order.account_id)
        if active_run is not None:
            reused += 1
            logger.info(
                "[%d/%d] REUSE order=%s account=%s broker_native_ids=%s active_run=%s",
                scanned, total,
                order.order_request_id, order.account_id,
                broker_native_ids, active_run.reconciliation_run_id,
            )
            continue

        # Instrument 조회: instrument_id → symbol 변환
        # (order_blocking_locks.symbol이 NOT NULL이므로 symbol 필수)
        symbol: str | None = None
        instrument = await repos.instruments.get(order.instrument_id)
        if instrument is not None:
            symbol = instrument.symbol
        else:
            logger.warning(
                "[%d/%d] INSTRUMENT NOT FOUND instrument_id=%s order=%s — skipping",
                scanned, total,
                order.instrument_id, order.order_request_id,
            )
            skipped += 1
            continue

        side = order.side.value if order.side else None

        if args.dry_run:
            skipped += 1
            logger.info(
                "[%d/%d] DRY-RUN order=%s account=%s broker_native_ids=%s "
                "(would trigger trigger_type=%s symbol=%s side=%s)",
                scanned, total,
                order.order_request_id, order.account_id,
                broker_native_ids,
                TRIGGER_TYPE, symbol, side,
            )
            continue

        # Trigger reconciliation + order link
        try:
            run = await recon_service.trigger_and_link(
                account_id=order.account_id,
                trigger_type=TRIGGER_TYPE,
                order_request_id=order.order_request_id,
                instrument_id=order.instrument_id,
                symbol=symbol,
                side=side,
            )
            triggered += 1
            logger.info(
                "[%d/%d] TRIGGERED order=%s account=%s broker_native_ids=%s run=%s",
                scanned, total,
                order.order_request_id, order.account_id,
                broker_native_ids, run.reconciliation_run_id,
            )
        except Exception as exc:
            failed += 1
            logger.exception(
                "[%d/%d] FAILED order=%s account=%s error=%s",
                scanned, total,
                order.order_request_id, order.account_id, exc,
            )

    # ── Summary ──
    summary_lines = [
        "=== Backfill Summary ===",
        f"  scanned:   {scanned}",
        f"  triggered: {triggered}",
        f"  reused:    {reused}",
        f"  skipped:   {skipped} (dry-run)",
        f"  failed:    {failed}",
        f"  total:     {total}",
    ]
    summary = "\n".join(summary_lines)
    logger.info("\n" + summary)
    print(summary)  # stdout에도 출력

    return 0 if failed == 0 else 1


# ── DB-backed 실행 ──────────────────────────────────────────────────────────


async def _run(args: argparse.Namespace) -> int:
    """DB에 연결하여 backfill을 실행한다."""
    config = DatabaseConfig()
    await create_pool(config)
    try:
        async with transaction() as tx:
            repos = build_postgres_repositories(tx)
            exit_code = await run_backfill(repos, args)

            # 실제 실행에서는 commit 필요
            if not args.dry_run:
                await tx.commit()

            return exit_code
    finally:
        await close_pool()


# ── Entry point ─────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
