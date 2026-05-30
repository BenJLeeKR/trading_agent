#!/usr/bin/env python3
"""
scripts/retry_failed_reconciliation.py

``reconcile_required`` 상태의 주문 중 ``reconciliation_order_links``에 연결되지 않은
주문들을 찾아 새로운 reconciliation run을 생성하고 worker가 처리할 수 있도록
run을 ``started`` 상태로 설정합니다.

기존 failed reconciliation run(``5e1573f3``)과는 무관하게 **항상 새로운 run**을 생성합니다.

Usage::

    # Dry-run: 대상 주문만 확인 (DB 변경 없음)
    python3 scripts/retry_failed_reconciliation.py --dry-run

    # 최대 5건만 처리 (소규모 테스트)
    python3 scripts/retry_failed_reconciliation.py --limit 5

    # 전체 실행
    python3 scripts/retry_failed_reconciliation.py

    # 상세 로그
    python3 scripts/retry_failed_reconciliation.py --verbose
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import asyncpg

logger = logging.getLogger(__name__)

TRIGGER_TYPE = "requires_reconciliation"
"""``reconciliation_runs.trigger_type`` 값.

DB CHECK 제약 조건(``ck_reconciliation_runs_trigger``)에서 허용하는 값.
migration 0008에 의해 ``'requires_reconciliation'``이 추가되었다.
"""

STATUS_STARTED = "started"
"""새로 생성할 reconciliation run의 상태. worker가 폴링하여 처리할 수 있도록 ``started``로 설정."""

MISMATCH_TYPE = "pending_inquiry"
"""``reconciliation_order_links.mismatch_type`` 값. 재처리가 필요한 주문임을 나타낸다."""


# ── DB 연결 설정 ────────────────────────────────────────────────────────────


def _build_dsn() -> str:
    """``.env`` 환경 변수에서 DB 접속 정보를 읽어 DSN을 구성한다."""
    host = (
        os.getenv("DATABASE_HOST")
        or os.getenv("DB_HOST")
        or "localhost"
    )
    port = (
        os.getenv("DATABASE_PORT")
        or os.getenv("DB_PORT")
        or "5432"
    )
    user = (
        os.getenv("DATABASE_USER")
        or os.getenv("DB_USER")
        or "trading"
    )
    password = (
        os.getenv("DATABASE_PASSWORD")
        or os.getenv("DB_PASSWORD")
        or "trading"
    )
    database = (
        os.getenv("DATABASE_NAME")
        or os.getenv("DB_NAME")
        or "trading"
    )
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


# ── CLI ────────────────────────────────────────────────────────────────────


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="reconcile_required 주문 대상 새 reconciliation run 생성",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 INSERT 없이 대상 주문만 출력",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="처리할 최대 order 수 (기본: 전체)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="상세 로그 출력",
    )
    return parser.parse_args(argv)


# ── 핵심 로직 ──────────────────────────────────────────────────────────────


async def find_target_orders(
    conn: asyncpg.Connection,
    limit: int | None,
) -> list[dict]:
    """``reconcile_required`` 상태이면서 아직 ``requires_reconciliation`` run에
    연결되지 않은 주문을 조회한다.

    Parameters
    ----------
    conn : asyncpg.Connection
        DB connection.
    limit : int | None
        최대 조회 건수 (None = 전체).

    Returns
    -------
    list[dict]
        각 dict는 ``order_request_id``, ``account_id``, ``side``, ``created_at``,
        ``instrument_id`` 키를 가진다.
    """
    query = """
        SELECT
            o.order_request_id,
            o.account_id,
            o.side,
            o.instrument_id,
            o.created_at
        FROM trading.order_requests o
        WHERE o.status = 'reconcile_required'
          AND NOT EXISTS (
              SELECT 1
              FROM trading.reconciliation_order_links rol
              JOIN trading.reconciliation_runs rr
                  ON rr.reconciliation_run_id = rol.reconciliation_run_id
              WHERE rol.order_request_id = o.order_request_id
                AND rr.trigger_type = 'requires_reconciliation'
          )
        ORDER BY o.created_at
    """
    if limit is not None:
        query += f"\n        LIMIT {limit}"

    rows = await conn.fetch(query)
    return [
        {
            "order_request_id": row["order_request_id"],
            "account_id": row["account_id"],
            "side": row["side"],
            "instrument_id": row["instrument_id"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _group_by_account(orders: list[dict]) -> dict:
    """주문 목록을 ``account_id`` 기준으로 그룹핑한다."""
    groups: dict = defaultdict(list)
    for o in orders:
        groups[o["account_id"]].append(o)
    return dict(groups)


async def backup_current_state(conn: asyncpg.Connection) -> dict:
    """실행 전 현재 ``reconciliation_runs`` 및 ``reconciliation_order_links``
    상태를 조회하여 반환한다.

    Returns
    -------
    dict
        ``{"runs": [...], "links": [...]}`` 형태의 백업 데이터.
    """
    runs_rows = await conn.fetch(
        "SELECT * FROM trading.reconciliation_runs ORDER BY created_at DESC",
    )
    links_rows = await conn.fetch(
        "SELECT * FROM trading.reconciliation_order_links ORDER BY created_at DESC",
    )

    runs = [dict(row) for row in runs_rows]
    links = [dict(row) for row in links_rows]

    # UUID/날짜 직렬화
    def _serialize(rows: list[dict]) -> list[dict]:
        out = []
        for r in rows:
            item = {}
            for k, v in r.items():
                if isinstance(v, (datetime,)):
                    item[k] = v.isoformat()
                else:
                    item[k] = str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v
            out.append(item)
        return out

    return {
        "runs": _serialize(runs),
        "links": _serialize(links),
    }


async def run_retry(
    conn: asyncpg.Connection,
    args: argparse.Namespace,
) -> int:
    """재처리 로직을 실행한다.

    Parameters
    ----------
    conn : asyncpg.Connection
        DB connection.
    args : argparse.Namespace
        CLI 인자.

    Returns
    -------
    int
        종료 코드 (0 = 성공, 1 = 부분 실패).
    """
    now = datetime.now(timezone.utc)

    # ── Step 1: 대상 주문 조회 ──
    orders = await find_target_orders(conn, args.limit)
    total_orders = len(orders)

    if total_orders == 0:
        logger.info("처리할 reconcile_required 주문이 없습니다.")
        print("[OK] 처리할 reconcile_required 주문이 없습니다.")
        return 0

    # ── Step 2: Account별 그룹핑 ──
    groups = _group_by_account(orders)
    num_accounts = len(groups)

    logger.info(
        "Target orders: %d건 (accounts: %d개)",
        total_orders, num_accounts,
    )

    # Dry-run: 출력만 하고 종료
    if args.dry_run:
        _print_dry_run_summary(orders, groups, total_orders, num_accounts)
        return 0

    # ── Step 3: 백업 ──
    logger.info("Backing up current reconciliation state...")
    backup = await backup_current_state(conn)
    backup_json = json.dumps(backup, ensure_ascii=False, indent=2, default=str)
    logger.debug("Backup snapshot:\n%s", backup_json[:2000] if len(backup_json) > 2000 else backup_json)

    # ── Step 4: Account별 reconciliation run 생성 및 link ──
    runs_created = 0
    links_created = 0
    order_processed = 0
    failed_accounts = 0
    total_links_target = total_orders

    for account_id, account_orders in groups.items():
        try:
            # 4a. 새로운 reconciliation run 생성
            run_id = uuid4()
            await conn.execute(
                """
                INSERT INTO trading.reconciliation_runs
                    (reconciliation_run_id, account_id, trigger_type, status,
                     mismatch_count, summary_json, started_at)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
                """,
                run_id,
                account_id,
                TRIGGER_TYPE,
                STATUS_STARTED,
                0,                          # mismatch_count (추후 worker가 업데이트)
                json.dumps({
                    "retry_script": True,
                    "description": "Auto-created by retry_failed_reconciliation.py",
                    "order_count": len(account_orders),
                }),
                now,
            )
            runs_created += 1
            logger.info(
                "Created reconciliation run %s for account %s (%d orders)",
                run_id, account_id, len(account_orders),
            )

            # 4b. 각 order에 대해 link 생성
            for order in account_orders:
                try:
                    order_id = order["order_request_id"]
                    await conn.execute(
                        """
                        INSERT INTO trading.reconciliation_order_links
                            (reconciliation_run_id, order_request_id, mismatch_type, details_json)
                        VALUES ($1, $2, $3, $4::jsonb)
                        """,
                        run_id,
                        order_id,
                        MISMATCH_TYPE,
                        json.dumps({
                            "retry_origin": "retry_failed_reconciliation.py",
                            "side": order["side"],
                            "instrument_id": str(order["instrument_id"]),
                            "created_at": order["created_at"].isoformat() if order["created_at"] else None,
                        }),
                    )
                    links_created += 1
                    order_processed += 1
                except Exception as exc:
                    logger.exception(
                        "Failed to create link for order %s (run=%s): %s",
                        order_id, run_id, exc,
                    )
                    # 부분 실패 허용: 다음 order로 계속

        except Exception as exc:
            failed_accounts += 1
            logger.exception(
                "Failed to process account %s: %s",
                account_id, exc,
            )
            # 부분 실패 허용: 다음 account로 계속

    # ── Step 5: 요약 출력 ──
    exit_code = _print_summary(
        runs_created=runs_created,
        links_created=links_created,
        order_processed=order_processed,
        total_orders=total_orders,
        total_links_target=total_links_target,
        failed_accounts=failed_accounts,
        num_accounts=num_accounts,
    )

    return exit_code


def _print_dry_run_summary(
    orders: list[dict],
    groups: dict,
    total_orders: int,
    num_accounts: int,
) -> None:
    """Dry-run 모드의 상세 출력."""
    lines = [
        "[DRY-RUN] retry_failed_reconciliation.py",
        f"Target orders: {total_orders}건",
        f"Account별 분포 ({num_accounts}개):",
    ]
    for account_id, account_orders in groups.items():
        orders_detail = ", ".join(
            f"{o['order_request_id']}({o['side']})"
            for o in account_orders[:5]  # 최대 5개까지 표시
        )
        suffix = " ..." if len(account_orders) > 5 else ""
        lines.append(f"  {account_id}: {len(account_orders)}건 [{orders_detail}{suffix}]")

    lines.append("")
    lines.append("[DRY-RUN] Would create:")
    lines.append(f"  - {num_accounts} reconciliation run(s) ({STATUS_STARTED})")
    lines.append(f"  - {total_orders} reconciliation_order_links (mismatch_type={MISMATCH_TYPE})")

    output = "\n".join(lines)
    logger.info("\n" + output)
    print(output)


def _print_summary(
    runs_created: int,
    links_created: int,
    order_processed: int,
    total_orders: int,
    total_links_target: int,
    failed_accounts: int,
    num_accounts: int,
) -> int:
    """실행 요약을 출력하고 종료 코드를 반환한다."""
    lines = [
        "=== retry_failed_reconciliation Summary ===",
        f"  accounts processed:       {num_accounts}",
        f"  reconciliation runs created: {runs_created}",
        f"  target orders:            {total_orders}",
        f"  order links created:      {links_created} / {total_links_target}",
        f"  failed accounts:          {failed_accounts}",
    ]
    summary = "\n".join(lines)
    logger.info("\n" + summary)
    print(summary)

    return 1 if failed_accounts > 0 else 0


# ── Entry point ────────────────────────────────────────────────────────────


async def _run(args: argparse.Namespace) -> int:
    """DB에 연결하여 retry 로직을 실행한다."""
    dsn = _build_dsn()
    # DSN에서 password 마스킹 (로깅용)
    db_password = os.getenv("DATABASE_PASSWORD") or os.getenv("DB_PASSWORD") or "trading"
    safe_dsn = dsn.replace(db_password, "****")
    logger.debug("Connecting to database: %s", safe_dsn)

    conn: asyncpg.Connection = await asyncpg.connect(dsn)
    try:
        return await run_retry(conn, args)
    finally:
        await conn.close()


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
