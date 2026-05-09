"""Broker-agnostic snapshot sync runner.

Provides the ``SnapshotFetchProvider`` protocol for fetching snapshot data
and broker-agnostic runner functions (``sync_account_snapshots``,
``sync_accounts_by_ids``, ``sync_all_accounts``) that use any provider.

Also re-exports ``SyncResult``, ``BatchSyncResult``, and
``build_sync_run_entity`` from ``kis_snapshot_sync`` for backward
compatibility.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid4

from agent_trading.domain.entities import (
    CashBalanceSnapshotEntity,
    PositionSnapshotEntity,
    SnapshotSyncRunEntity,
)
from agent_trading.domain.enums import Environment
from agent_trading.repositories.contracts import (
    AccountRepository,
    BrokerAccountRepository,
    CashBalanceSnapshotRepository,
    InstrumentRepository,
    PositionSnapshotRepository,
)
from agent_trading.services.kis_snapshot_sync import (
    BatchSyncResult,
    SyncResult,
    build_sync_run_entity,
)

logger = logging.getLogger(__name__)


# ── Public helpers (moved from kis_snapshot_sync for broker-agnostic use) ──


def safe_decimal(value: object) -> Decimal:
    """Convert a string-or-number to ``Decimal``, defaulting to ``0``."""
    try:
        return Decimal(str(value))
    except (ValueError, TypeError, ArithmeticError):
        return Decimal("0")


def safe_optional_decimal(value: object) -> Decimal | None:
    """Convert a string-or-number to ``Decimal | None``."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return Decimal(s)
    except (ValueError, TypeError, ArithmeticError):
        return None


# ── Protocol ──────────────────────────────────────────────────────────────


@dataclass(slots=True, frozen=True)
class FetchedSnapshot:
    """Broker-agnostic snapshot fetch result.

    Attributes
    ----------
    positions:
        Position snapshots fetched from the broker.
    cash_balance:
        Optional cash balance snapshot.
    errors:
        Non-fatal errors encountered during fetch (e.g. instrument lookup
        failures, field mapping issues).
    """
    positions: Sequence[PositionSnapshotEntity]
    cash_balance: CashBalanceSnapshotEntity | None
    errors: list[str]


class SnapshotFetchProvider(Protocol):
    """Protocol for fetching positions and cash balance for snapshot sync.

    Implementations wrap a broker-specific REST client and handle field-name
    mapping from broker-native response format to domain entities.
    """

    async def fetch_snapshot(
        self,
        account_id: UUID,
        instrument_repo: InstrumentRepository,
    ) -> FetchedSnapshot:
        """Fetch current positions and cash balance for a single account.

        Parameters
        ----------
        account_id:
            The ``AccountEntity.account_id`` (UUID) to associate snapshots
            with.
        instrument_repo:
            Repository for resolving broker-native instrument codes (e.g.
            KIS ``pdno``) to ``InstrumentEntity.instrument_id``.

        Returns
        -------
        FetchedSnapshot
            Positions, optional cash balance, and any non-fatal errors.
        """
        ...


# ── Broker-agnostic runners ──────────────────────────────────────────────


async def sync_account_snapshots(
    fetch_provider: SnapshotFetchProvider,
    instrument_repo: InstrumentRepository,
    position_snapshot_repo: PositionSnapshotRepository,
    cash_balance_snapshot_repo: CashBalanceSnapshotRepository,
    account_id: UUID,
) -> SyncResult:
    """Broker-agnostic single-account snapshot sync.

    Uses ``SnapshotFetchProvider`` instead of a broker-specific REST client.
    Persists fetched snapshots and returns a ``SyncResult`` summary.

    Parameters
    ----------
    fetch_provider:
        Broker-specific implementation of ``SnapshotFetchProvider``.
    instrument_repo:
        Repository for resolving instrument codes to IDs.
    position_snapshot_repo:
        Repository for persisting position snapshots.
    cash_balance_snapshot_repo:
        Repository for persisting cash-balance snapshots.
    account_id:
        The account UUID to associate with the snapshots.

    Returns
    -------
    SyncResult
        Summary of what was synced, skipped, or errored.
    """
    result = SyncResult()

    # ── 1. Fetch via provider ─────────────────────────────────────────
    try:
        fetched = await fetch_provider.fetch_snapshot(account_id, instrument_repo)
    except Exception as exc:
        msg = f"Snapshot fetch failed for account_id={account_id}: {exc}"
        logger.error(msg)
        result._add_error(msg)
        return result

    # ── 2. Persist positions ──────────────────────────────────────────
    for pos in fetched.positions:
        try:
            await position_snapshot_repo.add(pos)
            result._incr("positions_synced")
        except Exception as exc:
            logger.error(
                "Failed to persist position snapshot for account_id=%s, "
                "instrument_id=%s: %s",
                account_id,
                pos.instrument_id,
                exc,
            )
            result._add_error(
                f"Persist error for instrument_id={pos.instrument_id}: {exc}"
            )

    # ── 3. Persist cash balance ───────────────────────────────────────
    cash = fetched.cash_balance
    if cash is not None:
        try:
            await cash_balance_snapshot_repo.add(cash)
            result._set("cash_balance_synced", True)
        except Exception as exc:
            logger.error(
                "Failed to persist cash balance for account_id=%s: %s",
                account_id,
                exc,
            )
            result._add_error(f"Cash balance persist error: {exc}")

    # ── 4. Collect provider errors ────────────────────────────────────
    for err in fetched.errors:
        result._add_error(err)

    return result


async def sync_accounts_by_ids(
    fetch_provider: SnapshotFetchProvider,
    instrument_repo: InstrumentRepository,
    position_snapshot_repo: PositionSnapshotRepository,
    cash_balance_snapshot_repo: CashBalanceSnapshotRepository,
    account_ids: Sequence[UUID],
) -> BatchSyncResult:
    """Broker-agnostic batch snapshot sync for specific account IDs.

    Calls ``sync_account_snapshots()`` for each account and aggregates
    results into a ``BatchSyncResult``.

    Parameters
    ----------
    fetch_provider:
        Broker-specific implementation of ``SnapshotFetchProvider``.
    instrument_repo:
        Repository for resolving instrument codes to IDs.
    position_snapshot_repo:
        Repository for persisting position snapshots.
    cash_balance_snapshot_repo:
        Repository for persisting cash-balance snapshots.
    account_ids:
        Sequence of ``AccountEntity.account_id`` (UUID) values to sync.

    Returns
    -------
    BatchSyncResult
        Aggregated summary across all accounts.
    """
    batch = BatchSyncResult(total_accounts=len(account_ids))

    for account_id in account_ids:
        try:
            result = await sync_account_snapshots(
                fetch_provider=fetch_provider,
                instrument_repo=instrument_repo,
                position_snapshot_repo=position_snapshot_repo,
                cash_balance_snapshot_repo=cash_balance_snapshot_repo,
                account_id=account_id,
            )
        except Exception as exc:
            msg = f"Unexpected error syncing account_id={account_id}: {exc}"
            logger.error(msg)
            batch._add_error(msg)
            batch._incr("failed")
            continue

        batch.account_results.append((account_id, result))
        batch._incr("total_positions_synced", result.positions_synced)
        batch._incr("total_positions_skipped", result.positions_skipped)
        if result.cash_balance_synced:
            batch._incr("total_cash_synced")

        if result.errors:
            if result.positions_synced > 0 or result.cash_balance_synced:
                batch._incr("partial")
            else:
                batch._incr("failed")
        else:
            batch._incr("succeeded")

    return batch


async def sync_all_accounts(
    fetch_provider: SnapshotFetchProvider,
    instrument_repo: InstrumentRepository,
    position_snapshot_repo: PositionSnapshotRepository,
    cash_balance_snapshot_repo: CashBalanceSnapshotRepository,
    broker_account_repo: BrokerAccountRepository,
    account_repo: AccountRepository,
    *,
    broker_name: str = "koreainvestment",
    account_number: str | None = None,
    env: Environment | None = None,
    account_status: str | None = None,
) -> BatchSyncResult:
    """Broker-agnostic auto-discover + batch snapshot sync.

    Discovers broker accounts via ``BrokerAccountRepository`` filtered by
    ``broker_name``, resolves each to an ``AccountEntity``, and syncs
    snapshots for all matching accounts.

    Parameters
    ----------
    fetch_provider:
        Broker-specific implementation of ``SnapshotFetchProvider``.
    instrument_repo:
        Repository for resolving instrument codes to IDs.
    position_snapshot_repo:
        Repository for persisting position snapshots.
    cash_balance_snapshot_repo:
        Repository for persisting cash-balance snapshots.
    broker_account_repo:
        Repository for listing broker accounts by broker name.
    account_repo:
        Repository for resolving broker accounts to ``AccountEntity``.
    broker_name:
        Broker name to discover accounts for (default: ``"koreainvestment"``).
    account_number:
        Optional broker account number filter. When provided, only broker
        accounts whose ``account_ref`` matches this value will be synced.
    env:
        Optional environment filter. When provided, only broker accounts
        whose ``environment`` matches are discovered.
    account_status:
        Optional account status filter. When provided, only accounts
        whose ``AccountEntity.status`` matches are synced.

    Returns
    -------
    BatchSyncResult
        Aggregated summary across all discovered accounts.
    """
    if env is not None:
        broker_accounts = await broker_account_repo.list_by_broker_and_env(
            broker_name, env
        )
    else:
        broker_accounts = await broker_account_repo.list_by_broker(broker_name)
    batch = BatchSyncResult(total_accounts=len(broker_accounts))

    for ba in broker_accounts:
        if account_number is not None and ba.account_ref != account_number:
            logger.info(
                "Skipping broker_account_id=%s (account_ref=%s) — "
                "does not match account_number=%s",
                ba.broker_account_id,
                ba.account_ref,
                account_number,
            )
            batch._incr("skipped")
            continue

        # Resolve broker account → AccountEntity
        try:
            from agent_trading.repositories.filters import AccountLookup

            lookup = AccountLookup(broker_account_id=ba.broker_account_id)
            account = await account_repo.find_one(lookup)
        except Exception as exc:
            msg = f"Failed to resolve broker_account_id={ba.broker_account_id}: {exc}"
            logger.error(msg)
            batch._add_error(msg)
            batch._incr("failed")
            continue

        if account is None:
            logger.warning(
                "No AccountEntity found for broker_account_id=%s "
                "(account_ref=%s) — skipping",
                ba.broker_account_id,
                ba.account_ref,
            )
            batch._incr("skipped")
            continue

        if account_status is not None and account.status != account_status:
            logger.info(
                "Skipping account_id=%s (status=%s) — "
                "does not match requested account_status=%s",
                account.account_id,
                account.status,
                account_status,
            )
            batch._incr("skipped")
            continue

        # Sync this account
        try:
            result = await sync_account_snapshots(
                fetch_provider=fetch_provider,
                instrument_repo=instrument_repo,
                position_snapshot_repo=position_snapshot_repo,
                cash_balance_snapshot_repo=cash_balance_snapshot_repo,
                account_id=account.account_id,
            )
        except Exception as exc:
            msg = f"Unexpected error syncing account_id={account.account_id}: {exc}"
            logger.error(msg)
            batch._add_error(msg)
            batch._incr("failed")
            continue

        batch.account_results.append((account.account_id, result))
        batch._incr("total_positions_synced", result.positions_synced)
        batch._incr("total_positions_skipped", result.positions_skipped)
        if result.cash_balance_synced:
            batch._incr("total_cash_synced")

        if result.errors:
            if result.positions_synced > 0 or result.cash_balance_synced:
                batch._incr("partial")
            else:
                batch._incr("failed")
        else:
            batch._incr("succeeded")

    return batch
