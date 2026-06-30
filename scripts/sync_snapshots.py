#!/usr/bin/env python3
"""Broker-agnostic snapshot sync CLI.

Usage
-----
    python -m scripts.sync_snapshots --broker koreainvestment --account-ref <ref>
    python -m scripts.sync_snapshots --broker koreainvestment --all
    python -m scripts.sync_snapshots --broker koreainvestment --account-id <uuid>
    python -m scripts.sync_snapshots --broker koreainvestment --all --dry-run
    python -m scripts.sync_snapshots --help

Currently only ``--broker koreainvestment`` is supported.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from uuid import UUID

from agent_trading.brokers.snapshot_factory import build_snapshot_sync_components
from agent_trading.config.settings import AppSettings
from agent_trading.domain.enums import Environment
from agent_trading.services.snapshot_sync import (
    BatchSyncResult,
    SyncResult,
    sync_account_snapshots,
    sync_accounts_by_ids,
    sync_all_accounts,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sync_snapshots")


# ── Format helpers ────────────────────────────────────────────────────────


def _emit_json(obj: object) -> None:
    print(json.dumps(obj, indent=2, default=str))


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


# ── CLI ───────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Broker-agnostic snapshot sync CLI.",
    )
    parser.add_argument(
        "--broker",
        type=str,
        default="koreainvestment",
        help="Broker name (default: koreainvestment). "
        "Only 'koreainvestment' is currently supported.",
    )
    parser.add_argument(
        "--account-id",
        type=str,
        default=None,
        help="Sync a single account by UUID.",
    )
    parser.add_argument(
        "--account-ref",
        type=str,
        default=None,
        help="Sync a single account by broker account reference number.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="Auto-discover and sync all accounts for the given broker.",
    )
    parser.add_argument(
        "--env",
        type=str,
        default=None,
        choices=["paper", "live"],
        help="Filter by environment (paper/live). Implied by --all.",
    )
    parser.add_argument(
        "--status",
        type=str,
        default=None,
        help="Filter by account status (e.g. active, dormant).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Fetch data but roll back the transaction.",
    )
    parser.add_argument(
        "--format",
        type=str,
        default="text",
        choices=["text", "json"],
        help="Output format (default: text).",
    )

    args = parser.parse_args(argv)

    # Validate args
    mode_count = sum([bool(args.account_id), bool(args.account_ref), args.all])
    if mode_count == 0:
        parser.error("Specify --account-id, --account-ref, or --all.")
    if mode_count > 1:
        parser.error(
            "Use only one of --account-id, --account-ref, or --all."
        )

    return args


def _print_sync_result(
    account_id: UUID,
    result: SyncResult,
    fmt: str,
) -> None:
    if fmt == "json":
        _emit_json(_sync_result_to_dict(account_id, result))
        return

    print(f"  account_id={account_id}")
    print(f"    positions_synced={result.positions_synced}")
    print(f"    positions_skipped={result.positions_skipped}")
    print(f"    cash_balance_synced={result.cash_balance_synced}")
    if result.errors:
        print(f"    errors ({len(result.errors)}):")
        for err in result.errors:
            print(f"      - {err}")


def _print_batch_summary(
    batch: BatchSyncResult,
    fmt: str,
) -> None:
    if fmt == "json":
        _emit_json(_batch_result_to_dict(batch))
        return

    print(f"  total_accounts={batch.total_accounts}")
    print(f"  succeeded={batch.succeeded}")
    print(f"  partial={batch.partial}")
    print(f"  failed={batch.failed}")
    print(f"  skipped={batch.skipped}")
    print(f"  total_positions_synced={batch.total_positions_synced}")
    print(f"  total_positions_skipped={batch.total_positions_skipped}")
    print(f"  total_cash_synced={batch.total_cash_synced}")
    if batch.errors:
        print(f"  errors ({len(batch.errors)}):")
        for err in batch.errors[:5]:
            print(f"    - {err}")
        if len(batch.errors) > 5:
            print(f"    ... ({len(batch.errors) - 5} more)")


# ── Run modes ─────────────────────────────────────────────────────────────


async def _run_single(
    broker: str,
    account_id: UUID,
    settings: AppSettings,
    fmt: str,
) -> int:
    """Sync a single account by UUID."""
    repos = _build_repos()
    provider = build_snapshot_sync_components(broker, settings).provider

    result = await sync_account_snapshots(
        fetch_provider=provider,
        instrument_repo=repos["instruments"],
        position_snapshot_repo=repos["position_snapshots"],
        cash_balance_snapshot_repo=repos["cash_balance_snapshots"],
        risk_limit_snapshot_repo=repos["risk_limit_snapshots"],
        symbol_trade_state_repo=repos["symbol_trade_states"],
        order_repo=repos["orders"],
        account_id=account_id,
    )

    _print_sync_result(account_id, result, fmt)
    return 0 if not result.errors else 1


async def _run_single_by_ref(
    broker: str,
    account_ref: str,
    settings: AppSettings,
    fmt: str,
) -> int:
    """Sync a single account by broker account reference."""
    from uuid import UUID

    from agent_trading.repositories.filters import AccountLookup

    repos = _build_repos()
    broker_account_repo = repos["broker_accounts"]
    account_repo = repos["accounts"]

    # Resolve ref → BrokerAccountEntity
    ba = await broker_account_repo.get_by_ref(account_ref, broker)
    if ba is None:
        print(f"Broker account not found: ref={account_ref} broker={broker}")
        return 1

    # Resolve → AccountEntity
    lookup = AccountLookup(broker_account_id=ba.broker_account_id)
    account = await account_repo.find_one(lookup)
    if account is None:
        print(
            f"No AccountEntity found for broker_account_id={ba.broker_account_id}"
        )
        return 1

    provider = build_snapshot_sync_components(broker, settings).provider
    result = await sync_account_snapshots(
        fetch_provider=provider,
        instrument_repo=repos["instruments"],
        position_snapshot_repo=repos["position_snapshots"],
        cash_balance_snapshot_repo=repos["cash_balance_snapshots"],
        risk_limit_snapshot_repo=repos["risk_limit_snapshots"],
        symbol_trade_state_repo=repos["symbol_trade_states"],
        order_repo=repos["orders"],
        account_id=account.account_id,
    )

    _print_sync_result(account.account_id, result, fmt)
    return 0 if not result.errors else 1


async def _run_multi(
    broker: str,
    account_ids: list[UUID],
    settings: AppSettings,
    fmt: str,
) -> int:
    """Sync multiple accounts by UUID list."""
    repos = _build_repos()
    provider = build_snapshot_sync_components(broker, settings).provider

    batch = await sync_accounts_by_ids(
        fetch_provider=provider,
        instrument_repo=repos["instruments"],
        position_snapshot_repo=repos["position_snapshots"],
        cash_balance_snapshot_repo=repos["cash_balance_snapshots"],
        risk_limit_snapshot_repo=repos["risk_limit_snapshots"],
        symbol_trade_state_repo=repos["symbol_trade_states"],
        order_repo=repos["orders"],
        account_ids=account_ids,
    )

    _print_batch_summary(batch, fmt)
    return 0 if batch.failed == 0 else 1


async def _run_all(
    broker: str,
    settings: AppSettings,
    env: Environment | None,
    account_status: str | None,
    fmt: str,
) -> int:
    """Auto-discover and sync all accounts for the given broker."""
    repos = _build_repos()
    provider = build_snapshot_sync_components(broker, settings).provider

    batch = await sync_all_accounts(
        fetch_provider=provider,
        instrument_repo=repos["instruments"],
        position_snapshot_repo=repos["position_snapshots"],
        cash_balance_snapshot_repo=repos["cash_balance_snapshots"],
        risk_limit_snapshot_repo=repos["risk_limit_snapshots"],
        broker_account_repo=repos["broker_accounts"],
        account_repo=repos["accounts"],
        symbol_trade_state_repo=repos["symbol_trade_states"],
        order_repo=repos["orders"],
        broker_name=broker,
        account_number=settings.kis_account_number,
        env=env,
        account_status=account_status,
    )

    _print_batch_summary(batch, fmt)
    return 0 if batch.failed == 0 else 1


# ── Repository factory ────────────────────────────────────────────────────


def _build_repos() -> dict[str, object]:
    """Build in-memory repositories for snapshot sync.

    Returns a dict keyed by repository name for convenience.
    """
    from agent_trading.repositories.memory import (
        InMemoryAccountRepository,
        InMemoryBrokerAccountRepository,
        InMemoryCashBalanceSnapshotRepository,
        InMemoryInstrumentRepository,
        InMemoryPositionSnapshotRepository,
        InMemoryRiskLimitSnapshotRepository,
        InMemorySnapshotSyncRunRepository,
    )

    return {
        "broker_accounts": InMemoryBrokerAccountRepository(),
        "accounts": InMemoryAccountRepository(),
        "instruments": InMemoryInstrumentRepository(),
        "position_snapshots": InMemoryPositionSnapshotRepository(),
        "cash_balance_snapshots": InMemoryCashBalanceSnapshotRepository(),
        "risk_limit_snapshots": InMemoryRiskLimitSnapshotRepository(),
        "snapshot_sync_runs": InMemorySnapshotSyncRunRepository(),
    }


# ── Entry point ──────────────────────────────────────────────────────────


async def _run(args: argparse.Namespace) -> int:
    settings = AppSettings()

    # Validate broker (factory will raise ValueError for unsupported brokers)
    try:
        build_snapshot_sync_components(args.broker, settings)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    if args.account_id:
        uid = UUID(args.account_id)
        return await _run_single(args.broker, uid, settings, args.format)

    if args.account_ref:
        return await _run_single_by_ref(args.broker, args.account_ref, settings, args.format)

    if args.all:
        env: Environment | None = None
        if args.env:
            env = Environment(args.env)
        return await _run_all(args.broker, settings, env, args.status, args.format)

    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Parameters
    ----------
    argv:
        Optional argument list (defaults to ``sys.argv[1:]``).

    Returns
    -------
    int
        Exit code (0 = success, 1 = error).
    """
    args = _parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
