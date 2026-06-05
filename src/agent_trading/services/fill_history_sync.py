from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.brokers.rate_limit import BudgetExhaustedError
from agent_trading.domain.entities import BrokerFillSnapshotEntity, FillSyncRunEntity
from agent_trading.domain.enums import Environment
from agent_trading.repositories.contracts import (
    AccountRepository,
    BrokerOrderRepository,
    BrokerAccountRepository,
    BrokerFillSnapshotRepository,
)
from agent_trading.repositories.filters import AccountLookup

logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))
_GF = KISRestClient._get_kis_field
_VTTC0081R_RETRY_WAIT_SECONDS = 3.0
_VTTC0081R_MAX_ATTEMPTS = 2


@dataclass(slots=True, frozen=True)
class AccountFillSyncResult:
    account_id: UUID
    fills_synced: int = 0
    fills_skipped: int = 0
    retried_days: int = 0
    retry_count: int = 0
    errors: list[str] = field(default_factory=list)

    def _add_error(self, msg: str) -> None:
        self.errors.append(msg)


@dataclass(slots=True, frozen=True)
class FillBatchSyncResult:
    total_accounts: int = 0
    succeeded: int = 0
    partial: int = 0
    failed: int = 0
    skipped: int = 0
    total_fills_synced: int = 0
    total_fills_skipped: int = 0
    retried_accounts: int = 0
    retried_days: int = 0
    total_retries: int = 0
    account_results: list[tuple[UUID, AccountFillSyncResult]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def _incr(self, field_name: str, delta: int = 1) -> None:
        object.__setattr__(self, field_name, getattr(self, field_name) + delta)

    def _add_result(self, account_id: UUID, result: AccountFillSyncResult) -> None:
        self.account_results.append((account_id, result))

    def _add_error(self, msg: str) -> None:
        self.errors.append(msg)


def build_fill_sync_run_entity(
    batch: FillBatchSyncResult,
    *,
    trigger_type: str,
    scope: str,
    dry_run: bool = False,
    started_at: datetime | None = None,
    env_filter: str | None = None,
    summary_json: dict[str, object] | None = None,
    fill_sync_run_id: UUID | None = None,
) -> FillSyncRunEntity:
    error_count = len(batch.errors)
    now = datetime.now(timezone.utc)
    if batch.failed == 0 and batch.partial == 0 and error_count == 0:
        status = "completed"
    elif batch.succeeded > 0 or batch.partial > 0:
        status = "partial"
    else:
        status = "failed"
    effective_summary = summary_json or {
        "retried_accounts": batch.retried_accounts,
        "retried_days": batch.retried_days,
        "total_retries": batch.total_retries,
    }
    return FillSyncRunEntity(
        fill_sync_run_id=fill_sync_run_id or uuid4(),
        trigger_type=trigger_type,
        scope=scope,
        dry_run=dry_run,
        total_accounts=batch.total_accounts,
        succeeded_accounts=batch.succeeded,
        partial_accounts=batch.partial,
        failed_accounts=batch.failed,
        skipped_accounts=batch.skipped,
        fills_synced_total=batch.total_fills_synced,
        fills_skipped_total=batch.total_fills_skipped,
        error_count=error_count,
        status=status,
        started_at=started_at or now,
        env_filter=env_filter,
        summary_json=effective_summary,
        completed_at=now,
    )


def _parse_decimal(raw: Any) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw))
    except Exception:
        return None


def _get_kis_value(item: dict[str, Any], *fields: str, default: Any = "") -> Any:
    for field in fields:
        value = _GF(item, field, None)
        if value not in (None, ""):
            return value
    return default


def _side_from_code(code: str | None) -> str:
    if code == "01":
        return "sell"
    return "buy"


def _build_fill_timestamp(order_day: date, fill_time: str | None) -> datetime | None:
    if not fill_time:
        return None
    value = fill_time.strip()
    if len(value) != 6 or not value.isdigit():
        return None
    dt = datetime.combine(
        order_day,
        time(hour=int(value[0:2]), minute=int(value[2:4]), second=int(value[4:6])),
        tzinfo=_KST,
    )
    return dt.astimezone(timezone.utc)


def _build_dedupe_key(
    *,
    account_id: UUID,
    broker_native_order_id: str,
    broker_fill_id: str | None,
    symbol: str,
    side: str,
    order_day: date,
    filled_quantity: Decimal,
    fill_price: Decimal,
    fill_time: str | None,
) -> str:
    broker_fill_component = broker_fill_id or ""
    return "|".join(
        [
            str(account_id),
            broker_native_order_id,
            broker_fill_component,
            symbol,
            side,
            order_day.isoformat(),
            str(filled_quantity),
            str(fill_price),
            fill_time or "",
        ]
    )


async def _fetch_daily_ccld_with_retry(
    *,
    rest_client: KISRestClient,
    order_day: date,
    after_hours: bool,
) -> tuple[list[dict[str, Any]], int]:
    """Fetch VTTC0081R rows with one bounded retry on budget exhaustion.

    Fill sync is a background observability path.  A single inquiry/global
    budget miss in paper mode should not cause the entire account sync to fail
    immediately when the next token is only moments away.
    """
    last_exc: Exception | None = None
    for attempt in range(1, _VTTC0081R_MAX_ATTEMPTS + 1):
        try:
            return (
                await rest_client.inquire_daily_ccld(
                strt_dt=order_day.strftime("%Y%m%d"),
                end_dt=order_day.strftime("%Y%m%d"),
                after_hours=after_hours,
                ),
                attempt - 1,
            )
        except BudgetExhaustedError as exc:
            last_exc = exc
            if exc.bucket not in {"inquiry", "global"} or attempt >= _VTTC0081R_MAX_ATTEMPTS:
                raise
            wait_fn = getattr(rest_client, "_wait_for_inquiry_budget", None)
            if wait_fn is None:
                raise
            if not await wait_fn(timeout=_VTTC0081R_RETRY_WAIT_SECONDS):
                raise
            logger.info(
                "VTTC0081R budget retry: order_day=%s bucket=%s attempt=%s/%s",
                order_day.isoformat(),
                exc.bucket,
                attempt + 1,
                _VTTC0081R_MAX_ATTEMPTS,
            )
    if last_exc is not None:
        raise last_exc
    return [], 0


async def sync_fill_history_for_account(
    *,
    rest_client: KISRestClient,
    fill_repo: BrokerFillSnapshotRepository,
    broker_order_repo: BrokerOrderRepository,
    account_id: UUID,
    order_day: date,
    fill_sync_run_id: UUID,
    after_hours: bool = False,
) -> AccountFillSyncResult:
    result = AccountFillSyncResult(account_id=account_id)
    linked_order_cache: dict[str, UUID | None] = {}
    try:
        records, retry_count = await _fetch_daily_ccld_with_retry(
            rest_client=rest_client,
            order_day=order_day,
            after_hours=after_hours,
        )
    except Exception as exc:
        result._add_error(f"VTTC0081R failed: {exc}")
        return result
    if retry_count > 0:
        object.__setattr__(result, "retried_days", 1)
        object.__setattr__(result, "retry_count", retry_count)

    for item in records:
        filled_quantity = _parse_decimal(
            _get_kis_value(item, "TOT_CCLD_QTY", "CCLD_QTY", default="0"),
        )
        if filled_quantity is None:
            object.__setattr__(result, "fills_skipped", result.fills_skipped + 1)
            continue
        fill_price = _parse_decimal(
            _get_kis_value(item, "AVG_PRVS", "CCLD_UNPR", default="0"),
        ) or Decimal("0")
        ordered_quantity = _parse_decimal(_get_kis_value(item, "ORD_QTY", default=None))
        broker_native_order_id = str(_get_kis_value(item, "ODNO", default="")).strip()
        symbol = str(_get_kis_value(item, "PDNO", default="")).strip()
        if not broker_native_order_id or not symbol:
            object.__setattr__(result, "fills_skipped", result.fills_skipped + 1)
            continue
        order_request_id = linked_order_cache.get(broker_native_order_id)
        if broker_native_order_id not in linked_order_cache:
            linked_broker_order = await broker_order_repo.get_by_native_order_id(
                "koreainvestment",
                broker_native_order_id,
            )
            order_request_id = (
                linked_broker_order.order_request_id
                if linked_broker_order is not None
                else None
            )
            linked_order_cache[broker_native_order_id] = order_request_id
        side = _side_from_code(str(_get_kis_value(item, "SLL_BUY_DVSN_CD", default="")))
        broker_fill_id = str(_get_kis_value(item, "CCLD_NUM", default="")).strip() or None
        fill_time = str(_get_kis_value(item, "CCLD_TMD", "INFM_TMD", default="")).strip() or None
        snapshot = BrokerFillSnapshotEntity(
            broker_fill_snapshot_id=uuid4(),
            fill_sync_run_id=fill_sync_run_id,
            account_id=account_id,
            order_request_id=order_request_id,
            broker_name="koreainvestment",
            broker_native_order_id=broker_native_order_id,
            broker_fill_id=broker_fill_id,
            symbol=symbol,
            side=side,
            order_date=order_day,
            order_status_code=str(
                _get_kis_value(item, "ORD_STAT", "CCLD_CNDT_NAME", "ORD_DVSN_NAME", default=""),
            ).strip() or None,
            cancel_yn=str(_get_kis_value(item, "CNCL_YN", default="")).strip() or None,
            ordered_quantity=ordered_quantity,
            filled_quantity=filled_quantity,
            fill_price=fill_price,
            order_time=str(_get_kis_value(item, "ORD_TMD", default="")).strip() or None,
            fill_time=fill_time,
            fill_timestamp=_build_fill_timestamp(order_day, fill_time),
            dedupe_key=_build_dedupe_key(
                account_id=account_id,
                broker_native_order_id=broker_native_order_id,
                broker_fill_id=broker_fill_id,
                symbol=symbol,
                side=side,
                order_day=order_day,
                filled_quantity=filled_quantity,
                fill_price=fill_price,
                fill_time=fill_time,
            ),
            raw_payload_json=item,
            updated_at=datetime.now(timezone.utc),
        )
        await fill_repo.upsert(snapshot)
        object.__setattr__(result, "fills_synced", result.fills_synced + 1)
    return result


async def sync_all_fill_history(
    *,
    rest_client: KISRestClient,
    broker_account_repo: BrokerAccountRepository,
    account_repo: AccountRepository,
    fill_repo: BrokerFillSnapshotRepository,
    broker_order_repo: BrokerOrderRepository,
    broker_name: str,
    env: Environment,
    account_number: str | None,
    fill_sync_run_id: UUID,
    order_day: date,
    after_hours: bool = False,
    lookback_days: int = 2,
) -> FillBatchSyncResult:
    batch = FillBatchSyncResult()
    broker_accounts = await broker_account_repo.list_by_broker_and_env(broker_name, env)
    for broker_account in broker_accounts:
        if account_number is not None and broker_account.account_ref != account_number:
            continue
        batch._incr("total_accounts")
        account = await account_repo.find_one(
            AccountLookup(broker_account_id=broker_account.broker_account_id),
        )
        if account is None:
            batch._incr("skipped")
            batch._add_error(
                f"No account found for broker_account_id={broker_account.broker_account_id}",
            )
            continue
        result = AccountFillSyncResult(account_id=account.account_id)
        for offset in range(max(1, lookback_days)):
            day = order_day - timedelta(days=offset)
            per_day = await sync_fill_history_for_account(
                rest_client=rest_client,
                fill_repo=fill_repo,
                broker_order_repo=broker_order_repo,
                account_id=account.account_id,
                order_day=day,
                fill_sync_run_id=fill_sync_run_id,
                after_hours=after_hours,
            )
            object.__setattr__(result, "fills_synced", result.fills_synced + per_day.fills_synced)
            object.__setattr__(result, "fills_skipped", result.fills_skipped + per_day.fills_skipped)
            object.__setattr__(result, "retried_days", result.retried_days + per_day.retried_days)
            object.__setattr__(result, "retry_count", result.retry_count + per_day.retry_count)
            if per_day.errors:
                result.errors.extend(per_day.errors)
        batch._add_result(account.account_id, result)
        batch._incr("total_fills_synced", result.fills_synced)
        batch._incr("total_fills_skipped", result.fills_skipped)
        if result.retried_days > 0:
            batch._incr("retried_accounts")
            batch._incr("retried_days", result.retried_days)
            batch._incr("total_retries", result.retry_count)
        if result.errors and result.fills_synced > 0:
            batch._incr("partial")
            batch.errors.extend(result.errors)
        elif result.errors:
            batch._incr("failed")
            batch.errors.extend(result.errors)
        else:
            batch._incr("succeeded")
    return batch
