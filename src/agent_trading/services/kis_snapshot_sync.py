from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
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

logger = logging.getLogger(__name__)

# KIS inquire-balance output position field names
_KIS_PDNO = "pdno"  # 종목코드
_KIS_HLDG_QTY = "hldg_qty"  # 보유수량
_KIS_PCHS_AVG_PRIC = "pchs_avg_pric"  # 매입평균가
_KIS_PRPR = "prpr"  # 현재가
_KIS_EVL_PFLS_AMT = "evlu_pfls_amt"  # 평가손익

# KIS inquire-balance output2 (cash summary) field names
_KIS_DNCA_TOT_AMT = "dnca_tot_amt"  # 예수금총액
_KIS_NXDY_EXCC_AMT = "nxdy_excc_amt"  # 익일초과액
_KIS_ORD_PSBL_AMT = "ord_psbl_amt"  # 주문가능금액 (fallback용)
_KIS_TOT_EVL_AMT = "tot_evlu_amt"  # 총평가금액 (유가증권 평가금액 합계 + D+2 예수금)
_KIS_PRVS_RCDL_EXCC_AMT = "prvs_rcdl_excc_amt"  # 가수도정산금액 (D+2 예수금 기준)
_KIS_EVL_PFLS_SMTL_AMT = "evlu_pfls_smtl_amt"  # 평가손익합계금액 (계좌 총괄)

_SOURCE_OF_TRUTH = "broker"
_DEFAULT_MARKET_CODE = "KRX"


@dataclass(slots=True, frozen=True)
class SyncResult:
    """Result of a single KIS account snapshot sync operation.

    Uses ``object.__setattr__`` internally because the dataclass is frozen
    (immutable by contract for callers), but the sync function needs to
    accumulate counters.
    """

    positions_synced: int = 0
    positions_skipped: int = 0
    cash_balance_synced: bool = False
    errors: list[str] = field(default_factory=list)

    def _incr(self, field_name: str, delta: int = 1) -> None:
        object.__setattr__(self, field_name, getattr(self, field_name) + delta)

    def _set(self, field_name: str, value: object) -> None:
        object.__setattr__(self, field_name, value)

    def _add_error(self, msg: str) -> None:
        self.errors.append(msg)


@dataclass(slots=True, frozen=True)
class BatchSyncResult:
    """Aggregate result for batch KIS snapshot sync across multiple accounts."""

    total_accounts: int = 0
    succeeded: int = 0
    partial: int = 0
    failed: int = 0
    skipped: int = 0
    total_positions_synced: int = 0
    total_positions_skipped: int = 0
    total_cash_synced: int = 0
    account_results: list[tuple[UUID, SyncResult]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def _incr(self, field_name: str, delta: int = 1) -> None:
        object.__setattr__(self, field_name, getattr(self, field_name) + delta)

    def _set(self, field_name: str, value: object) -> None:
        object.__setattr__(self, field_name, value)

    def _add_error(self, msg: str) -> None:
        self.errors.append(msg)


def build_sync_run_entity(
    batch: BatchSyncResult,
    *,
    trigger_type: str,
    scope: str,
    env_filter: str | None = None,
    status_filter: str | None = None,
    dry_run: bool = False,
    started_at: datetime | None = None,
    summary_json: dict[str, object] | None = None,
    after_hours: bool = False,
) -> SnapshotSyncRunEntity:
    """Build a ``SnapshotSyncRunEntity`` from a ``BatchSyncResult`` + metadata.

    Parameters
    ----------
    batch : BatchSyncResult
        The result of a completed snapshot sync run.
    trigger_type : str
        ``"manual"`` or ``"scheduler"``.
    scope : str
        ``"single"``, ``"batch"``, or ``"all"``.
    env_filter : str | None
        The environment filter used (``"paper"`` / ``"live"`` / ``None``).
    status_filter : str | None
        The account status filter used, or ``None``.
    dry_run : bool
        Whether this was a dry run (KIS fetch performed, DB rolled back).
    started_at : datetime | None
        When the run started. Defaults to ``datetime.now(timezone.utc)``.
    summary_json : dict[str, object] | None
        Optional structured summary data.
    after_hours : bool
        Whether this sync was an after-hours cash-only run.

    Returns
    -------
    SnapshotSyncRunEntity
        A run-level summary entity ready for persistence.
    """
    error_count = len(batch.errors)
    now = datetime.now(timezone.utc)

    # Determine run status
    # "completed": no failures, no partial accounts, no errors
    # "partial":   some partial or successful accounts (but not all clean)
    # "failed":    all accounts failed
    if batch.failed == 0 and batch.partial == 0 and error_count == 0:
        status = "completed"
    elif batch.partial > 0 or batch.succeeded > 0:
        status = "partial"
    else:
        status = "failed"

    return SnapshotSyncRunEntity(
        snapshot_sync_run_id=uuid4(),
        trigger_type=trigger_type,
        scope=scope,
        env_filter=env_filter,
        status_filter=status_filter,
        dry_run=dry_run,
        total_accounts=batch.total_accounts,
        succeeded_accounts=batch.succeeded,
        partial_accounts=batch.partial,
        failed_accounts=batch.failed,
        skipped_accounts=batch.skipped,
        positions_synced_total=batch.total_positions_synced,
        positions_skipped_total=batch.total_positions_skipped,
        cash_synced_count=batch.total_cash_synced,
        error_count=error_count,
        status=status,
        started_at=started_at or now,
        completed_at=now,
        summary_json=summary_json,
        after_hours=after_hours,
    )


async def sync_kis_account_snapshots(
    rest_client: KISRestClient,
    instrument_repo: InstrumentRepository,
    position_snapshot_repo: PositionSnapshotRepository,
    cash_balance_snapshot_repo: CashBalanceSnapshotRepository,
    account_id: UUID,
) -> SyncResult:
    """Fetch KIS positions and cash balance, then store as snapshots.

    Parameters
    ----------
    rest_client:
        Authenticated KIS REST client.
    instrument_repo:
        Repository for resolving ``pdno`` (KIS product code) to
        ``instrument_id`` (UUID).
    position_snapshot_repo:
        Repository for persisting position snapshots.
    cash_balance_snapshot_repo:
        Repository for persisting cash-balance snapshots.
    account_id:
        The ``AccountEntity.account_id`` (UUID) to associate with the
        snapshots.

    Returns
    -------
    SyncResult
        Summary of what was synced, skipped, or errored.
    """
    result = SyncResult()
    snapshot_at = datetime.now(tz=timezone.utc)

    # ── 1. Sync positions ──────────────────────────────────────────────
    try:
        raw_positions: Sequence[dict[str, Any]] = await rest_client.get_positions()
    except Exception as exc:
        msg = f"Failed to fetch positions from KIS: {exc}"
        logger.error(msg)
        result._add_error(msg)
        raw_positions = []

    # pdno → instrument_id 매핑을 수집 (zero-out 로직에서 사용)
    pdno_to_instrument_id: dict[str, UUID] = {}

    for raw in raw_positions:
        pdno = raw.get(_KIS_PDNO, "")
        if not pdno:
            result._incr("positions_skipped")
            result._add_error("Position row missing 'pdno' — skipped")
            continue

        # Resolve instrument_id via symbol lookup
        try:
            instrument = await instrument_repo.get_by_symbol(pdno, _DEFAULT_MARKET_CODE)
        except Exception as exc:
            logger.warning("Instrument lookup failed for pdno=%s: %s", pdno, exc)
            instrument = None

        if instrument is None:
            logger.warning(
                "Skipping position pdno=%s — instrument not found in DB", pdno
            )
            result._incr("positions_skipped")
            result._add_error(f"Instrument not found for pdno={pdno} — skipped")
            continue

        pdno_to_instrument_id[pdno] = instrument.instrument_id

        # Map KIS raw fields → PositionSnapshotEntity
        try:
            entity = PositionSnapshotEntity(
                position_snapshot_id=uuid4(),
                account_id=account_id,
                instrument_id=instrument.instrument_id,
                quantity=_safe_decimal(raw.get(_KIS_HLDG_QTY, "0")),
                average_price=_safe_decimal(raw.get(_KIS_PCHS_AVG_PRIC, "0")),
                market_price=_safe_optional_decimal(raw.get(_KIS_PRPR)),
                unrealized_pnl=_safe_optional_decimal(raw.get(_KIS_EVL_PFLS_AMT)),
                source_of_truth=_SOURCE_OF_TRUTH,
                snapshot_at=snapshot_at,
            )
        except Exception as exc:
            logger.warning("Failed to build PositionSnapshotEntity for pdno=%s: %s", pdno, exc)
            result._incr("positions_skipped")
            result._add_error(f"Mapping error for pdno={pdno}: {exc}")
            continue

        try:
            await position_snapshot_repo.add(entity)
            result._incr("positions_synced")
        except Exception as exc:
            logger.error("Failed to persist position snapshot pdno=%s: %s", pdno, exc)
            result._add_error(f"Persist error for pdno={pdno}: {exc}")

    # ── 1b. Zero-out positions missing from KIS response ───────────────
    # KIS 응답에서 사라진 종목 = 전량 매도 → quantity=0으로 기록
    try:
        current_instrument_ids = set(pdno_to_instrument_id.values())
        latest_snapshots = await position_snapshot_repo.list_latest_by_account(account_id)

        zeroed_count = 0
        for snap in latest_snapshots:
            if snap.quantity == Decimal("0"):
                continue  # 이미 0 처리됨
            if snap.instrument_id in current_instrument_ids:
                continue  # KIS 응답에 있는 종목

            # KIS 응답에 없고 quantity>0인 종목 → quantity=0 snapshot 추가
            zero_snapshot = PositionSnapshotEntity(
                position_snapshot_id=uuid4(),
                account_id=account_id,
                instrument_id=snap.instrument_id,
                quantity=Decimal("0"),
                average_price=snap.average_price,
                market_price=snap.market_price,
                unrealized_pnl=snap.unrealized_pnl,
                source_of_truth=_SOURCE_OF_TRUTH,
                snapshot_at=snapshot_at,
            )
            await position_snapshot_repo.add(zero_snapshot)
            zeroed_count += 1

        if zeroed_count > 0:
            logger.info(
                "[ZERO_OUT] account=%s: zeroed %d positions missing from KIS response",
                account_id, zeroed_count,
            )
    except Exception:
        logger.exception(
            "[ZERO_OUT] failed for account=%s", account_id,
        )
        # zero-out 실패는 치명적이지 않음 — 다음 cycle에서 재시도

    # ── 2. Sync cash balance ───────────────────────────────────────────
    # Paper 1 RPS pacing: ensure at least 1s between consecutive KIS calls
    await asyncio.sleep(1.0)
    try:
        raw_cash: dict[str, Any] = await rest_client.get_cash_balance()
    except Exception as exc:
        msg = f"Failed to fetch cash balance from KIS: {exc}"
        logger.error(msg)
        result._add_error(msg)
        raw_cash = {}

    if raw_cash:
        try:
            available_cash = _safe_decimal(raw_cash.get(_KIS_DNCA_TOT_AMT, "0"))
            # settled_cash: prefer nxdy_excc_amt, fall back to dnca_tot_amt
            settled_raw = raw_cash.get(_KIS_NXDY_EXCC_AMT)
            if settled_raw is not None and str(settled_raw).strip():
                settled_cash = _safe_decimal(settled_raw)
            else:
                settled_cash = available_cash

            # unsettled_cash: difference if both are positive
            if available_cash > 0 and settled_cash > 0 and settled_cash < available_cash:
                unsettled_cash = available_cash - settled_cash
            else:
                unsettled_cash = None

            # KIS output2 account-level summary fields
            total_asset = _safe_optional_decimal(raw_cash.get(_KIS_TOT_EVL_AMT))
            settlement_amount = _safe_optional_decimal(raw_cash.get(_KIS_PRVS_RCDL_EXCC_AMT))
            total_unrealized_pnl = _safe_optional_decimal(raw_cash.get(_KIS_EVL_PFLS_SMTL_AMT))

            # ── orderable_amount: prefer VTTC8908R over VTTC8434R ──
            # get_cash_balance() uses VTTC8434R (inquire-balance) which
            # does NOT return ord_psbl_cash in paper environment.
            # get_orderable_cash() uses VTTC8908R (inquire-psbl-order)
            # which provides ord_psbl_cash even in paper mode.
            orderable_amount: Decimal | None = None

            # Paper 1 RPS pacing: ensure at least 1s between consecutive KIS calls
            await asyncio.sleep(1.0)

            try:
                orderable_cash = await rest_client.get_orderable_cash(
                    account_ref="",
                )
            except Exception:
                logger.warning(
                    "VTTC8908R get_orderable_cash() failed (legacy sync path); "
                    "falling back to VTTC8434R ord_psbl_amt",
                    exc_info=True,
                )
                orderable_cash = None

            if orderable_cash is not None:
                orderable_amount = orderable_cash
                logger.info(
                    "orderable_amount=%s (source: VTTC8908R, legacy sync path)",
                    orderable_cash,
                )
            else:
                # Fallback: use ord_psbl_amt from VTTC8434R output2
                orderable_amount = _safe_optional_decimal(
                    raw_cash.get(_KIS_ORD_PSBL_AMT)
                )
                if orderable_amount is not None:
                    logger.info(
                        "orderable_amount=%s (source: VTTC8434R fallback, legacy sync path)",
                        orderable_amount,
                    )
                else:
                    logger.info(
                        "orderable_amount=None (VTTC8908R unavailable, "
                        "VTTC8434R ord_psbl_amt also missing, legacy sync path)"
                    )

            cash_entity = CashBalanceSnapshotEntity(
                cash_balance_snapshot_id=uuid4(),
                account_id=account_id,
                currency="KRW",
                available_cash=available_cash,
                settled_cash=settled_cash,
                unsettled_cash=unsettled_cash,
                total_asset=total_asset,
                settlement_amount=settlement_amount,
                total_unrealized_pnl=total_unrealized_pnl,
                orderable_amount=orderable_amount,
                source_of_truth=_SOURCE_OF_TRUTH,
                snapshot_at=snapshot_at,
            )
        except Exception as exc:
            msg = f"Failed to map cash balance: {exc}"
            logger.error(msg)
            result._add_error(msg)
            cash_entity = None

        if cash_entity is not None:
            try:
                await cash_balance_snapshot_repo.add(cash_entity)
                result._set("cash_balance_synced", True)
            except Exception as exc:
                msg = f"Failed to persist cash balance snapshot: {exc}"
                logger.error(msg)
                result._add_error(msg)
    else:
        logger.warning(
            "Cash balance empty for account_id=%s env=%s broker=koreainvestment endpoint=inquire-balance",
            account_id,
            getattr(rest_client, "env", "unknown"),
        )

    return result


# ── Batch sync functions ────────────────────────────────────────────────


async def sync_kis_accounts_by_ids(
    rest_client: KISRestClient,
    instrument_repo: InstrumentRepository,
    position_snapshot_repo: PositionSnapshotRepository,
    cash_balance_snapshot_repo: CashBalanceSnapshotRepository,
    account_ids: Sequence[UUID],
) -> BatchSyncResult:
    """Sync snapshots for multiple account IDs sequentially.

    Calls ``sync_kis_account_snapshots()`` for each account and
    aggregates results into a ``BatchSyncResult``.

    Parameters
    ----------
    rest_client:
        Authenticated KIS REST client.
    instrument_repo:
        Repository for resolving ``pdno`` to ``instrument_id``.
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
            result = await sync_kis_account_snapshots(
                rest_client=rest_client,
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
            # Some errors but at least partial success
            if result.positions_synced > 0 or result.cash_balance_synced:
                batch._incr("partial")
            else:
                batch._incr("failed")
        else:
            batch._incr("succeeded")

    return batch


async def sync_all_kis_accounts(
    rest_client: KISRestClient,
    instrument_repo: InstrumentRepository,
    position_snapshot_repo: PositionSnapshotRepository,
    cash_balance_snapshot_repo: CashBalanceSnapshotRepository,
    broker_account_repo: BrokerAccountRepository,
    account_repo: AccountRepository,
    *,
    kis_account_number: str | None = None,
    env: Environment | None = None,
    account_status: str | None = None,
) -> BatchSyncResult:
    """Discover all KIS accounts and sync snapshots for each.

    Uses ``BrokerAccountRepository.list_by_broker("koreainvestment")`` to
    discover all KIS broker accounts, then resolves each to an
    ``AccountEntity`` via ``AccountRepository.find_one()``.

    When ``env`` is provided, only broker accounts whose ``environment``
    matches the given value are discovered (via
    ``BrokerAccountRepository.list_by_broker_and_env``).

    When ``account_status`` is provided, only accounts whose
    ``AccountEntity.status`` matches the given value are synced.
    Non-matching accounts are reported as skipped.

    Parameters
    ----------
    rest_client:
        Authenticated KIS REST client.
    instrument_repo:
        Repository for resolving ``pdno`` to ``instrument_id``.
    position_snapshot_repo:
        Repository for persisting position snapshots.
    cash_balance_snapshot_repo:
        Repository for persisting cash-balance snapshots.
    broker_account_repo:
        Repository for listing KIS broker accounts.
    account_repo:
        Repository for resolving broker accounts to ``AccountEntity``.
    kis_account_number:
        Optional KIS account number (from settings). When provided,
        only broker accounts whose ``account_ref`` matches this value
        will be synced. Non-matching accounts are reported as skipped.
    env:
        Optional environment filter. When provided, only broker accounts
        whose ``environment`` matches this value are discovered.
    account_status:
        Optional account status filter. When provided, only accounts
        whose ``AccountEntity.status`` matches this value are synced.

    Returns
    -------
    BatchSyncResult
        Aggregated summary across all discovered accounts.
    """
    if env is not None:
        broker_accounts = await broker_account_repo.list_by_broker_and_env(
            "koreainvestment", env
        )
    else:
        broker_accounts = await broker_account_repo.list_by_broker("koreainvestment")
    batch = BatchSyncResult(total_accounts=len(broker_accounts))

    for ba in broker_accounts:
        # Filter by KIS account number if provided
        if kis_account_number is not None and ba.account_ref != kis_account_number:
            logger.info(
                "Skipping broker_account_id=%s (account_ref=%s) — "
                "does not match KIS_ACCOUNT_NUMBER=%s",
                ba.broker_account_id,
                ba.account_ref,
                kis_account_number,
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
                "No AccountEntity found for broker_account_id=%s (account_ref=%s) — skipping",
                ba.broker_account_id,
                ba.account_ref,
            )
            batch._incr("skipped")
            continue

        # Filter by account status if provided
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
            result = await sync_kis_account_snapshots(
                rest_client=rest_client,
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


# ── Helpers ─────────────────────────────────────────────────────────────


def _safe_decimal(value: object) -> Decimal:
    """Convert a KIS string-or-number to ``Decimal``, defaulting to ``0``."""
    try:
        return Decimal(str(value))
    except (ValueError, TypeError, ArithmeticError):
        return Decimal("0")


def _safe_optional_decimal(value: object) -> Decimal | None:
    """Convert a KIS string-or-number to ``Decimal | None``."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return Decimal(s)
    except (ValueError, TypeError, ArithmeticError):
        return None
