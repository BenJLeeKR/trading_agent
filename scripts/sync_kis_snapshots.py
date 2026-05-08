#!/usr/bin/env python3
"""CLI script to sync KIS account positions/cash-balance into snapshot tables.

Usage
-----
    # Single account (by UUID)
    python scripts/sync_kis_snapshots.py --account-id <UUID>

    # Multiple accounts
    python scripts/sync_kis_snapshots.py \\
        --account-id <UUID1> --account-id <UUID2>

    # Auto-discover all KIS accounts (with optional filters)
    python scripts/sync_kis_snapshots.py --all
    python scripts/sync_kis_snapshots.py --all --env paper
    python scripts/sync_kis_snapshots.py --all --status active
    python scripts/sync_kis_snapshots.py --all --env live --status active

    # Lookup by account reference string
    python scripts/sync_kis_snapshots.py --account-ref 50186448

    # Dry-run (KIS fetch performed, DB persist rolled back)
    python scripts/sync_kis_snapshots.py --all --dry-run

    # JSON output (stdout = pure JSON, warnings/logs to stderr)
    python scripts/sync_kis_snapshots.py --all --format json

Requires the usual KIS environment variables (``KIS_API_KEY``, ``KIS_API_SECRET``,
``KIS_ACCOUNT_NUMBER``, ``KIS_ACCOUNT_PRODUCT_CODE``, etc.) and a running
Postgres database (``DATABASE_URL``).

Exit codes
----------
* 0 — All accounts succeeded.
* 1 — Partial or full failure (one or more accounts failed).
* 2 — Usage error (missing or invalid arguments).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from uuid import UUID

from agent_trading.config.settings import AppSettings
from agent_trading.db.connection import DatabaseConfig, create_pool
from agent_trading.domain.enums import Environment
from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories
from agent_trading.services.kis_snapshot_sync import (
    BatchSyncResult,
    SyncResult,
    build_sync_run_entity,
    sync_all_kis_accounts,
    sync_kis_account_snapshots,
    sync_kis_accounts_by_ids,
)

# ── KISRestClient import (lazy to avoid circular issues at module level) ──

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sync_kis_snapshots")


# ── Helpers ────────────────────────────────────────────────────────────────


def _emit_json(obj: object) -> None:
    """Write a JSON-serializable object to stdout and flush.

    Warnings and log messages go to stderr; stdout contains only pure JSON.
    """
    json.dump(obj, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    sys.stdout.flush()


def _sync_result_to_dict(account_id: UUID, result: SyncResult) -> dict[str, object]:
    return {
        "account_id": str(account_id),
        "positions_synced": result.positions_synced,
        "positions_skipped": result.positions_skipped,
        "cash_balance_synced": result.cash_balance_synced,
        "errors": result.errors,
    }


def _batch_result_to_dict(batch: BatchSyncResult) -> dict[str, object]:
    return {
        "status": "success" if batch.failed == 0 and not batch.errors else (
            "partial" if batch.partial > 0 else "failure"
        ),
        "total_accounts": batch.total_accounts,
        "succeeded": batch.succeeded,
        "partial": batch.partial,
        "failed": batch.failed,
        "skipped": batch.skipped,
        "total_positions_synced": batch.total_positions_synced,
        "total_positions_skipped": batch.total_positions_skipped,
        "total_cash_synced": batch.total_cash_synced,
        "account_results": [
            _sync_result_to_dict(aid, r) for aid, r in batch.account_results
        ],
        "errors": batch.errors,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync KIS account positions/cash-balance into snapshot tables."
    )
    parser.add_argument(
        "--account-id",
        type=UUID,
        action="append",
        dest="account_ids",
        default=[],
        help="AccountEntity.account_id (UUID). May be specified multiple times. "
             "Mutually exclusive with --all and --account-ref.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Discover and sync all KIS accounts automatically. "
             "May be combined with --env and/or --status for filtering. "
             "Mutually exclusive with --account-id and --account-ref.",
    )
    parser.add_argument(
        "--env",
        choices=["paper", "live"],
        default=None,
        help="Filter by KIS environment (paper|live). "
             "Only applicable with --all.",
    )
    parser.add_argument(
        "--status",
        type=str,
        default=None,
        help="Filter by AccountEntity.status value (e.g. active, inactive). "
             "Must match the exact status string stored in the DB. "
             "Only applicable with --all.",
    )
    parser.add_argument(
        "--account-ref",
        type=str,
        default=None,
        help="Lookup by KIS account reference string (e.g. 50186448). "
             "Resolves broker_account via BrokerAccountRepository.get_by_ref, "
             "then syncs the linked AccountEntity. "
             "Mutually exclusive with --account-id and --all.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform KIS fetch but roll back the DB transaction. "
             "Useful for testing connectivity and data format without persisting.",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format. 'json' writes pure JSON to stdout "
             "(warnings/logs go to stderr); 'text' prints human-readable tables.",
    )
    return parser.parse_args(argv)


def _print_sync_result(
    account_id: UUID,
    result: SyncResult,
    fmt: str = "text",
) -> None:
    """Print a single account sync result."""
    if fmt == "json":
        _emit_json(_sync_result_to_dict(account_id, result))
        return

    status = "✅" if not result.errors else (
        "⚠️" if result.positions_synced > 0 or result.cash_balance_synced else "❌"
    )
    print(
        f"  {status} account_id={account_id} "
        f"— positions={result.positions_synced}, "
        f"skipped={result.positions_skipped}, "
        f"cash={'yes' if result.cash_balance_synced else 'no'}"
    )
    for err in result.errors:
        print(f"       ⚠  {err}")


def _print_batch_summary(
    batch: BatchSyncResult,
    fmt: str = "text",
    dry_run: bool = False,
) -> None:
    """Print a formatted batch summary."""
    if fmt == "json":
        data = _batch_result_to_dict(batch)
        data["dry_run"] = dry_run
        _emit_json(data)
        return

    print("\n" + "=" * 60)
    print("  KIS Snapshot Sync — Batch Summary")
    print("=" * 60)
    if dry_run:
        print("  🏁  DRY RUN — no data was persisted")
        print("=" * 60)
    print(f"  Total accounts       : {batch.total_accounts}")
    print(f"  Succeeded            : {batch.succeeded}")
    print(f"  Partial              : {batch.partial}")
    print(f"  Failed               : {batch.failed}")
    print(f"  Skipped              : {batch.skipped}")
    print(f"  Positions synced     : {batch.total_positions_synced}")
    print(f"  Positions skipped    : {batch.total_positions_skipped}")
    print(f"  Cash synced          : {batch.total_cash_synced}")

    if batch.account_results:
        print(f"\n  --- Account Details ---")
        for account_id, result in batch.account_results:
            _print_sync_result(account_id, result, fmt="text")

    if batch.errors:
        print(f"\n  --- Batch Errors ---")
        for err in batch.errors:
            print(f"    - {err}")

    print("=" * 60 + "\n")


# ── Execution helpers ──────────────────────────────────────────────────────


async def _run_single(
    rest_client: Any,
    repos: Any,
    account_id: UUID,
    fmt: str = "text",
) -> tuple[int, SyncResult]:
    """Run sync for a single account."""
    logger.info("Syncing snapshots for account_id=%s ...", account_id)
    result = await sync_kis_account_snapshots(
        rest_client=rest_client,
        instrument_repo=repos.instruments,
        position_snapshot_repo=repos.position_snapshots,
        cash_balance_snapshot_repo=repos.cash_balance_snapshots,
        account_id=account_id,
    )

    if fmt == "text":
        print("\n" + "=" * 60)
        print("  KIS Snapshot Sync — Summary")
        print("=" * 60)
    _print_sync_result(account_id, result, fmt=fmt)
    if fmt == "text":
        print("=" * 60 + "\n")

    if result.errors:
        logger.warning("Sync completed with %d warning(s).", len(result.errors))
        return 1, result
    logger.info("Sync completed successfully.")
    return 0, result


async def _run_single_by_ref(
    rest_client: Any,
    repos: Any,
    account_ref: str,
    env: Environment | None,
    fmt: str = "text",
) -> tuple[int, SyncResult]:
    """Lookup account by reference string, then sync.

    Steps:
    1. Resolve ``account_ref`` → ``BrokerAccountEntity`` via ``get_by_ref``.
    2. Resolve broker account → ``AccountEntity`` via ``find_one``.
    3. Sync snapshots for the resolved account.
    """
    from agent_trading.repositories.filters import AccountLookup

    # 1. Resolve account_ref → BrokerAccountEntity
    logger.info("Looking up broker account by ref=%s ...", account_ref)
    resolved_env = env or Environment.PAPER
    broker_account = await repos.broker_accounts.get_by_ref(
        "koreainvestment",
        account_ref,
        resolved_env,
    )
    if broker_account is None:
        logger.error(
            "No BrokerAccountEntity found for broker_name=koreainvestment, "
            "account_ref=%s, env=%s",
            account_ref,
            resolved_env.value,
        )
        return 2, SyncResult()

    # 2. Resolve broker account → AccountEntity
    lookup = AccountLookup(broker_account_id=broker_account.broker_account_id)
    account = await repos.accounts.find_one(lookup)
    if account is None:
        logger.error(
            "No AccountEntity found for broker_account_id=%s (ref=%s)",
            broker_account.broker_account_id,
            account_ref,
        )
        return 2, SyncResult()

    # 3. Sync
    return await _run_single(rest_client, repos, account.account_id, fmt=fmt)


async def _run_multi(
    rest_client: Any,
    repos: Any,
    account_ids: list[UUID],
    fmt: str = "text",
) -> tuple[int, BatchSyncResult]:
    """Run sync for multiple account IDs."""
    logger.info("Syncing snapshots for %d account(s) ...", len(account_ids))
    batch = await sync_kis_accounts_by_ids(
        rest_client=rest_client,
        instrument_repo=repos.instruments,
        position_snapshot_repo=repos.position_snapshots,
        cash_balance_snapshot_repo=repos.cash_balance_snapshots,
        account_ids=account_ids,
    )
    _print_batch_summary(batch, fmt=fmt)

    if batch.failed > 0 or batch.errors:
        logger.warning(
            "Batch sync completed with %d failed, %d partial, %d error(s).",
            batch.failed,
            batch.partial,
            len(batch.errors),
        )
        return 1, batch
    logger.info("Batch sync completed successfully.")
    return 0, batch


async def _run_all(
    rest_client: Any,
    repos: Any,
    settings: AppSettings,
    env: Environment | None = None,
    account_status: str | None = None,
    fmt: str = "text",
) -> tuple[int, BatchSyncResult]:
    """Auto-discover and sync all KIS accounts (with optional filters)."""
    logger.info("Discovering all KIS accounts (env=%s, status=%s) ...", env, account_status)
    batch = await sync_all_kis_accounts(
        rest_client=rest_client,
        instrument_repo=repos.instruments,
        position_snapshot_repo=repos.position_snapshots,
        cash_balance_snapshot_repo=repos.cash_balance_snapshots,
        broker_account_repo=repos.broker_accounts,
        account_repo=repos.accounts,
        kis_account_number=settings.kis_account_number,
        env=env,
        account_status=account_status,
    )
    _print_batch_summary(batch, fmt=fmt)

    if batch.failed > 0 or batch.errors:
        logger.warning(
            "Auto-discover sync completed with %d failed, %d partial, %d error(s).",
            batch.failed,
            batch.partial,
            len(batch.errors),
        )
        return 1, batch
    logger.info("Auto-discover sync completed successfully.")
    return 0, batch


async def _run(args: argparse.Namespace) -> int:
    from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
    from agent_trading.brokers.rate_limit import build_kis_budget_manager
    from agent_trading.db.transaction import transaction

    settings = AppSettings()
    started_at = datetime.now(timezone.utc)

    # Resolve env filter
    env: Environment | None = Environment(args.env) if args.env else None

    # Resolve scope
    scope: str
    env_filter: str | None = str(env.value) if env else None
    status_filter: str | None = args.status
    if args.all:
        scope = "all"
    elif args.account_ref:
        scope = "single"
    elif args.account_ids:
        scope = "single" if len(args.account_ids) == 1 else "batch"
    else:
        scope = "single"

    # ── 1. KIS REST client ─────────────────────────────────────────────
    logger.info("Creating KISRestClient (env=%s) ...", settings.kis_env)
    budget_manager = build_kis_budget_manager(
        kis_env=settings.kis_env,
        real_rest_rps=settings.kis_real_rest_rps,
        paper_rest_rps=settings.kis_paper_rest_rps,
    )
    rest_client = KISRestClient(
        api_key=settings.kis_api_key,
        api_secret=settings.kis_api_secret,
        account_number=settings.kis_account_number,
        account_product_code=settings.kis_account_product_code,
        env=settings.kis_env,
        base_url=settings.kis_base_url,
        budget_manager=budget_manager,
    )

    try:
        logger.info("Authenticating with KIS ...")
        await rest_client.authenticate()
        logger.info("KIS authentication successful.")

        # ── 2. Postgres connection + transaction ──────────────────────
        logger.info("Connecting to Postgres ...")
        db_config = DatabaseConfig()
        await create_pool(db_config)

        async with transaction() as tx:
            repos = build_postgres_repositories(tx)
            logger.info("Postgres repositories ready.")

            # ── 3. Route to appropriate sync mode ─────────────────────
            batch: BatchSyncResult
            if args.account_ref:
                exit_code, sync_result = await _run_single_by_ref(
                    rest_client, repos, args.account_ref, env, fmt=args.format,
                )
                batch = BatchSyncResult(
                    total_accounts=1,
                    succeeded=1 if not sync_result.errors else 0,
                    partial=0,
                    failed=1 if sync_result.errors else 0,
                    skipped=0,
                    total_positions_synced=sync_result.positions_synced,
                    total_positions_skipped=sync_result.positions_skipped,
                    total_cash_synced=1 if sync_result.cash_balance_synced else 0,
                    errors=sync_result.errors,
                )
            elif args.all:
                exit_code, batch = await _run_all(
                    rest_client, repos, settings,
                    env=env,
                    account_status=args.status,
                    fmt=args.format,
                )
            elif args.account_ids:
                if len(args.account_ids) == 1:
                    exit_code, sync_result = await _run_single(
                        rest_client, repos, args.account_ids[0], fmt=args.format,
                    )
                    batch = BatchSyncResult(
                        total_accounts=1,
                        succeeded=1 if not sync_result.errors else 0,
                        partial=0,
                        failed=1 if sync_result.errors else 0,
                        skipped=0,
                        total_positions_synced=sync_result.positions_synced,
                        total_positions_skipped=sync_result.positions_skipped,
                        total_cash_synced=1 if sync_result.cash_balance_synced else 0,
                        errors=sync_result.errors,
                    )
                else:
                    exit_code, batch = await _run_multi(
                        rest_client, repos, args.account_ids, fmt=args.format,
                    )
            else:
                logger.error("Either --account-id, --all, or --account-ref is required.")
                return 2

            # ── 4. Save execution history ────────────────────────────
            run_entity = build_sync_run_entity(
                batch,
                trigger_type="manual",
                scope=scope,
                env_filter=env_filter,
                status_filter=status_filter,
                dry_run=args.dry_run,
                started_at=started_at,
            )
            await repos.snapshot_sync_runs.add(run_entity)

            if args.dry_run:
                logger.info("DRY RUN — rolling back transaction (no data persisted)")
                await tx.rollback()
            else:
                await tx.commit()

        return exit_code

    finally:
        await rest_client.close()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # Validate mutually exclusive modes
    modes = [bool(args.account_ids), bool(args.all), bool(args.account_ref)]
    if sum(modes) != 1:
        print(
            "Error: Exactly one of --account-id, --all, or --account-ref must be specified.",
            file=sys.stderr,
        )
        print("Usage:", file=sys.stderr)
        print("  python scripts/sync_kis_snapshots.py --account-id <UUID>", file=sys.stderr)
        print("  python scripts/sync_kis_snapshots.py --all [--env paper|live] [--status <val>]", file=sys.stderr)
        print("  python scripts/sync_kis_snapshots.py --account-ref <str>", file=sys.stderr)
        return 2

    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
