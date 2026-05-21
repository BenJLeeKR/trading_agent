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
    RiskLimitSnapshotEntity,
    SnapshotSyncRunEntity,
)
from agent_trading.domain.enums import Environment
from agent_trading.repositories.contracts import (
    AccountRepository,
    BrokerAccountRepository,
    CashBalanceSnapshotRepository,
    InstrumentRepository,
    PositionSnapshotRepository,
    RiskLimitSnapshotRepository,
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
    risk_limit_snapshot: RiskLimitSnapshotEntity | None = None


class SnapshotFetchProvider(Protocol):
    """Protocol for fetching positions and cash balance for snapshot sync.

    Implementations wrap a broker-specific REST client and handle field-name
    mapping from broker-native response format to domain entities.
    """

    async def fetch_snapshot(
        self,
        account_id: UUID,
        instrument_repo: InstrumentRepository,
        *,
        after_hours: bool = False,
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
        after_hours:
            When ``True``, the provider should skip fetching positions
            (since they don't change after market close) and only query
            cash balance with after-hours API parameters.

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
    risk_limit_snapshot_repo: RiskLimitSnapshotRepository,
    account_id: UUID,
    *,
    after_hours: bool = False,
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
    after_hours:
        When ``True``, passes ``after_hours=True`` to the provider's
        ``fetch_snapshot()`` so that broker-specific after-hours parameters
        (e.g. KIS ``AFHR_FLPR_YN=Y``) are applied.

    Returns
    -------
    SyncResult
        Summary of what was synced, skipped, or errored.
    """
    result = SyncResult()

    # ── 1. Fetch via provider ─────────────────────────────────────────
    try:
        fetched = await fetch_provider.fetch_snapshot(
            account_id, instrument_repo, after_hours=after_hours,
        )
    except Exception as exc:
        msg = f"Snapshot fetch failed for account_id={account_id}: {exc}"
        logger.error(msg)
        result._add_error(msg)
        return result

    # ── 2. Persist positions ──────────────────────────────────────────
    current_instrument_ids: set[UUID] = set()
    for pos in fetched.positions:
        try:
            await position_snapshot_repo.add(pos)
            current_instrument_ids.add(pos.instrument_id)
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

    # ── 2b. Zero-out positions missing from broker response ──────────
    # broker 응답에서 사라진 종목 = 전량 매도 → quantity=0으로 기록
    # 장 마감 후(after_hours)에는 snapshot이 비어있을 수 있으므로 zero-out 건너뜀
    if not after_hours:
        try:
            latest_snapshots = await position_snapshot_repo.list_latest_by_account(
                account_id,
            )

            zeroed_count = 0
            for snap in latest_snapshots:
                if snap.quantity == Decimal("0"):
                    continue  # 이미 0 처리됨
                if snap.instrument_id in current_instrument_ids:
                    continue  # broker 응답에 있는 종목

                # broker 응답에 없고 quantity>0인 종목 → quantity=0 snapshot 추가
                zero_snapshot = PositionSnapshotEntity(
                    position_snapshot_id=uuid4(),
                    account_id=account_id,
                    instrument_id=snap.instrument_id,
                    quantity=Decimal("0"),
                    average_price=snap.average_price,
                    market_price=snap.market_price,
                    unrealized_pnl=snap.unrealized_pnl,
                    source_of_truth=snap.source_of_truth,
                    snapshot_at=datetime.now(tz=timezone.utc),
                )
                await position_snapshot_repo.add(zero_snapshot)
                zeroed_count += 1

            if zeroed_count > 0:
                logger.info(
                    "[ZERO_OUT] account=%s: zeroed %d positions missing from broker response",
                    account_id, zeroed_count,
                )
        except Exception:
            logger.exception(
                "[ZERO_OUT] failed for account=%s", account_id,
            )
            # zero-out 실패는 치명적이지 않음 — 다음 cycle에서 재시도

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

    # ── 4. Persist risk_limit_snapshot ────────────────────────────────
    if fetched.risk_limit_snapshot is not None:
        try:
            await risk_limit_snapshot_repo.add(fetched.risk_limit_snapshot)
        except Exception:
            logger.exception(
                "Failed to persist risk_limit_snapshot for account %s", account_id
            )
            result._add_error("risk_limit_snapshot_persist_failed")

    # ── 5. Collect provider errors ────────────────────────────────────
    for err in fetched.errors:
        result._add_error(err)

    return result


async def sync_accounts_by_ids(
    fetch_provider: SnapshotFetchProvider,
    instrument_repo: InstrumentRepository,
    position_snapshot_repo: PositionSnapshotRepository,
    cash_balance_snapshot_repo: CashBalanceSnapshotRepository,
    risk_limit_snapshot_repo: RiskLimitSnapshotRepository,
    account_ids: Sequence[UUID],
    *,
    after_hours: bool = False,
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
    after_hours:
        When ``True``, passes through to ``sync_account_snapshots()``
        for after-hours cash inquiry.

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
                risk_limit_snapshot_repo=risk_limit_snapshot_repo,
                account_id=account_id,
                after_hours=after_hours,
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
    risk_limit_snapshot_repo: RiskLimitSnapshotRepository,
    broker_account_repo: BrokerAccountRepository,
    account_repo: AccountRepository,
    *,
    broker_name: str = "koreainvestment",
    account_number: str | None = None,
    env: Environment | None = None,
    account_status: str | None = None,
    after_hours: bool = False,
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
    after_hours:
        When ``True``, passes through to ``sync_account_snapshots()``
        for after-hours cash inquiry (AFHR_FLPR_YN=Y).

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
                risk_limit_snapshot_repo=risk_limit_snapshot_repo,
                account_id=account.account_id,
                after_hours=after_hours,
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
