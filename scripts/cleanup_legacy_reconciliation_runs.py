#!/usr/bin/env python3
"""
Legacy reconciliation run 정리 스크립트.

``status='started'``이면서 ``reconciliation_order_links = 0건``인
legacy reconciliation run을 식별하여 ``halted`` 상태로 마감한다.

- 관련 ``RECONCILE_REQUIRED`` 주문이 있을 경우
  ``ReconciliationService.trigger_and_link()``로 replacement run을 생성한 후
  legacy run을 ``halted``로 마감한다 (``superseded_by`` 기록).

사용법::

    # Dry-run: 변경 없이 대상만 확인
    python3 scripts/cleanup_legacy_reconciliation_runs.py --dry-run

    # 실제 실행
    python3 scripts/cleanup_legacy_reconciliation_runs.py

    # 특정 run_id만 처리
    python3 scripts/cleanup_legacy_reconciliation_runs.py --run-id <uuid>

    # 특정 계정만 처리
    python3 scripts/cleanup_legacy_reconciliation_runs.py --account-id <uuid>

    # 최대 10건만 처리
    python3 scripts/cleanup_legacy_reconciliation_runs.py --limit 10

    # 상세 로그 출력
    python3 scripts/cleanup_legacy_reconciliation_runs.py --verbose

Idempotency
-----------
- ``ReconciliationService.trigger_and_link()``는 active run이 이미 존재하면
  재사용하므로 중복 실행에 안전하다.
- 이미 ``halted`` 상태인 run은 ``list_legacy_runs()``에서 제외되므로
  재처리되지 않는다.
- ``--dry-run`` 모드에서는 DB 변경 없이 대상만 식별한다.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
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
안전한 값 중 하나를 사용.
"""


# ── CLI 인자 ────────────────────────────────────────────────────────────────


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Legacy reconciliation run 정리",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="변경 없이 대상만 조회",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="최대 처리 건수 (기본: 50)",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="특정 reconciliation_run_id만 처리",
    )
    parser.add_argument(
        "--account-id",
        type=str,
        default=None,
        help="특정 account_id만 처리",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="상세 로그 출력",
    )
    return parser.parse_args(argv)


# ── 핵심 cleanup 로직 ─────────────────────────────────────────────────────


async def cleanup_legacy_runs(
    repos: RepositoryContainer,
    args: argparse.Namespace,
) -> int:
    """Legacy reconciliation run 정리 로직을 실행한다.

    Parameters
    ----------
    repos : RepositoryContainer
        사용할 repository container.
    args : argparse.Namespace
        CLI 인자.

    Returns
    -------
    int
        종료 코드 (0 = 성공, 1 = 하나 이상 실패).
    """
    recon_service = ReconciliationService(repos)

    # ── Legacy run 조회 ──
    account_id: UUID | None = UUID(args.account_id) if args.account_id else None
    run_id: UUID | None = UUID(args.run_id) if args.run_id else None

    legacy_runs = await recon_service.list_legacy_runs(
        limit=args.limit,
        account_id=account_id,
        run_id=run_id,
    )

    total = len(legacy_runs)
    scanned = 0
    cleaned = 0
    replaced = 0
    skipped = 0
    failed = 0

    logger.info("Found %d legacy reconciliation run(s) to clean", total)

    for run in legacy_runs:
        scanned += 1

        # ── 해당 account의 RECONCILE_REQUIRED 주문 확인 ──
        query = OrderQuery(
            account_id=run.account_id,
            status=OrderStatus.RECONCILE_REQUIRED,
            limit=5,
        )
        pending_orders = await repos.orders.list(query)

        if pending_orders:
            # ── 주문 있음: replacement 생성 ──
            order = pending_orders[0]

            # Idempotency: 다른 active run이 이미 존재하는지 확인
            active_run = await recon_service.get_active_run(run.account_id)
            if active_run is not None and active_run.reconciliation_run_id != run.reconciliation_run_id:
                skipped += 1
                logger.info(
                    "[%d/%d] SKIP (active run exists) legacy_run=%s account=%s active_run=%s",
                    scanned, total,
                    run.reconciliation_run_id, run.account_id,
                    active_run.reconciliation_run_id,
                )
                continue

            if args.dry_run:
                skipped += 1
                logger.info(
                    "[%d/%d] DRY-RUN (would replace) legacy_run=%s account=%s order=%s",
                    scanned, total,
                    run.reconciliation_run_id, run.account_id,
                    order.order_request_id,
                )
                continue

            try:
                # Step 1: Legacy run을 먼저 halted로 마감 (trigger가 재사용하지 못하도록)
                await recon_service.halt_run(
                    reconciliation_run_id=run.reconciliation_run_id,
                    summary_json={
                        "reason": "legacy_run_replaced_pending",
                    },
                )

                # Step 2: Instrument 조회
                symbol: str | None = None
                instrument = await repos.instruments.get(order.instrument_id)
                if instrument is not None:
                    symbol = instrument.symbol

                side = order.side.value if order.side else None

                # Step 3: 이제 active run이 없으므로 trigger_and_link가 새 run 생성
                replacement_run = await recon_service.trigger_and_link(
                    account_id=order.account_id,
                    trigger_type=TRIGGER_TYPE,
                    order_request_id=order.order_request_id,
                    instrument_id=order.instrument_id,
                    symbol=symbol,
                    side=side,
                )

                # Step 4: Legacy run summary 업데이트 (superseded_by 기록)
                await repos.reconciliations.update_run_status(
                    reconciliation_run_id=run.reconciliation_run_id,
                    status="halted",
                    completed_at=run.completed_at,
                    summary_json={
                        "reason": "legacy_run_replaced",
                        "superseded_by": str(replacement_run.reconciliation_run_id),
                        "replacement_trigger_type": TRIGGER_TYPE,
                        "halted_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                replaced += 1
                logger.info(
                    "[%d/%d] REPLACED legacy_run=%s account=%s replacement=%s",
                    scanned, total,
                    run.reconciliation_run_id, run.account_id,
                    replacement_run.reconciliation_run_id,
                )

            except Exception as exc:
                failed += 1
                logger.exception(
                    "[%d/%d] FAILED legacy_run=%s account=%s error=%s",
                    scanned, total,
                    run.reconciliation_run_id, run.account_id, exc,
                )

        else:
            # ── 주문 없음: 단순 halted ──
            if args.dry_run:
                skipped += 1
                logger.info(
                    "[%d/%d] DRY-RUN (would halt) legacy_run=%s account=%s (no pending orders)",
                    scanned, total,
                    run.reconciliation_run_id, run.account_id,
                )
                continue

            try:
                await recon_service.halt_run(
                    reconciliation_run_id=run.reconciliation_run_id,
                    summary_json={
                        "reason": "legacy_run_without_links",
                        "cleanup_script": "cleanup_legacy_reconciliation_runs.py",
                    },
                )
                cleaned += 1
                logger.info(
                    "[%d/%d] HALTED legacy_run=%s account=%s (no pending orders)",
                    scanned, total,
                    run.reconciliation_run_id, run.account_id,
                )

            except Exception as exc:
                failed += 1
                logger.exception(
                    "[%d/%d] FAILED legacy_run=%s account=%s error=%s",
                    scanned, total,
                    run.reconciliation_run_id, run.account_id, exc,
                )

    # ── Summary ──
    summary_lines = [
        "=== Legacy Reconciliation Run Cleanup Summary ===",
        f"  Scanned : {scanned}",
        f"  Cleaned : {cleaned}   (link 없이 halted)",
        f"  Replaced: {replaced}   (replacement linked run 생성)",
        f"  Skipped : {skipped}",
        f"  Failed  : {failed}",
    ]
    if args.dry_run:
        summary_lines.append(f"  Dry-run : True (변경 없음)")
    summary = "\n".join(summary_lines)
    logger.info("\n" + summary)
    print(summary)  # stdout에도 출력

    return 0 if failed == 0 else 1


# ── DB-backed 실행 ──────────────────────────────────────────────────────────


async def _run(args: argparse.Namespace) -> int:
    """DB에 연결하여 cleanup을 실행한다."""
    config = DatabaseConfig()
    await create_pool(config)
    try:
        async with transaction() as tx:
            repos = build_postgres_repositories(tx)
            exit_code = await cleanup_legacy_runs(repos, args)

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
