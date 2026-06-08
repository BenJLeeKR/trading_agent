from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from agent_trading.api.deps import get_repos
from agent_trading.api.schemas import (
    FillHistoryItem,
    FillSyncRunHealthSummary,
    FillSyncRunSummary,
)
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import OrderQuery

router = APIRouter(tags=["fill-history"])
_KST = timezone(timedelta(hours=9))


def _fill_history_dedupe_key(row: object) -> tuple[str, str, str, str]:
    broker_fill_id = getattr(row, "broker_fill_id", None) or ""
    return (
        getattr(row, "broker_native_order_id"),
        broker_fill_id,
        getattr(row, "symbol"),
        getattr(row, "side"),
    )


def _fill_history_sort_key(row: object) -> tuple[datetime, datetime]:
    fallback = datetime.min.replace(tzinfo=timezone.utc)
    return (
        getattr(row, "fill_timestamp", None) or fallback,
        getattr(row, "created_at", None) or fallback,
    )


def _normalize_fill_history_rows(rows: list[object], *, limit: int) -> list[object]:
    """Collapse raw polling snapshots into visible final fill rows."""
    latest_by_key: dict[tuple[str, str, str, str], object] = {}
    for row in rows:
        filled_quantity = getattr(row, "filled_quantity", None)
        if filled_quantity is None or filled_quantity <= 0:
            continue
        key = _fill_history_dedupe_key(row)
        current = latest_by_key.get(key)
        if current is None or _fill_history_sort_key(row) > _fill_history_sort_key(current):
            latest_by_key[key] = row
    return sorted(
        latest_by_key.values(),
        key=_fill_history_sort_key,
        reverse=True,
    )[:limit]


def _to_run_summary(run: object) -> FillSyncRunSummary:
    return FillSyncRunSummary(
        fill_sync_run_id=str(run.fill_sync_run_id),  # type: ignore[attr-defined]
        trigger_type=run.trigger_type,  # type: ignore[attr-defined]
        scope=run.scope,  # type: ignore[attr-defined]
        dry_run=run.dry_run,  # type: ignore[attr-defined]
        total_accounts=run.total_accounts,  # type: ignore[attr-defined]
        succeeded_accounts=run.succeeded_accounts,  # type: ignore[attr-defined]
        partial_accounts=run.partial_accounts,  # type: ignore[attr-defined]
        failed_accounts=run.failed_accounts,  # type: ignore[attr-defined]
        skipped_accounts=run.skipped_accounts,  # type: ignore[attr-defined]
        fills_synced_total=run.fills_synced_total,  # type: ignore[attr-defined]
        fills_skipped_total=run.fills_skipped_total,  # type: ignore[attr-defined]
        error_count=run.error_count,  # type: ignore[attr-defined]
        status=run.status,  # type: ignore[attr-defined]
        started_at=run.started_at,  # type: ignore[attr-defined]
        completed_at=run.completed_at,  # type: ignore[attr-defined]
        env_filter=run.env_filter,  # type: ignore[attr-defined]
        summary_json=run.summary_json,  # type: ignore[attr-defined]
    )


@router.get("/fill-sync-runs", response_model=list[FillSyncRunSummary])
async def list_fill_sync_runs(
    limit: int = Query(30, ge=1, le=200),
    status: str | None = Query(None),
    repos: RepositoryContainer = Depends(get_repos),
) -> list[FillSyncRunSummary]:
    runs = await repos.fill_sync_runs.list_runs(limit=limit, status=status)
    return [_to_run_summary(run) for run in runs]


@router.get("/fill-sync-runs/summary", response_model=FillSyncRunHealthSummary)
async def get_fill_sync_health_summary(
    repos: RepositoryContainer = Depends(get_repos),
) -> FillSyncRunHealthSummary:
    summary = await repos.fill_sync_runs.get_sync_health_summary()
    return FillSyncRunHealthSummary(
        last_run_started_at=summary.last_run_started_at,
        last_run_completed_at=summary.last_run_completed_at,
        last_status=summary.last_status,
        last_successful_run_at=summary.last_successful_run_at,
        consecutive_failures=summary.consecutive_failures,
        is_stale=summary.is_stale,
        stale_threshold_seconds=summary.stale_threshold_seconds,
        retried_accounts=summary.retried_accounts,
        retried_days=summary.retried_days,
        total_retries=summary.total_retries,
    )


@router.get("/fill-history", response_model=list[FillHistoryItem])
async def list_fill_history(
    account_id: str | None = Query(None),
    order_request_id: str | None = Query(None),
    trade_decision_id: str | None = Query(None),
    symbol: str | None = Query(None),
    broker_native_order_id: str | None = Query(None),
    target_date: date | None = Query(None, alias="date"),
    limit: int = Query(200, ge=1, le=1000),
    repos: RepositoryContainer = Depends(get_repos),
) -> list[FillHistoryItem]:
    parsed_account_id: UUID | None = None
    parsed_order_request_id: UUID | None = None
    parsed_trade_decision_id: UUID | None = None
    if account_id is not None:
        try:
            parsed_account_id = UUID(account_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid UUID: {account_id}") from exc
    if order_request_id is not None:
        try:
            parsed_order_request_id = UUID(order_request_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid UUID: {order_request_id}") from exc
    if trade_decision_id is not None:
        try:
            parsed_trade_decision_id = UUID(trade_decision_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid UUID: {trade_decision_id}") from exc
    order_date = target_date or datetime.now(_KST).date()
    rows: list[object] = []
    if parsed_trade_decision_id is not None:
        matching_orders = await repos.orders.list(
            OrderQuery(
                trade_decision_id=parsed_trade_decision_id,
                limit=5000,
            )
        )
        order_request_ids = [order.order_request_id for order in matching_orders]
        if parsed_order_request_id is not None:
            order_request_ids = [
                oid for oid in order_request_ids if oid == parsed_order_request_id
            ]
        if not order_request_ids:
            return []
        for oid in order_request_ids:
            matched_rows = await repos.broker_fill_snapshots.list_recent(
                limit=limit,
                account_id=parsed_account_id,
                order_date=order_date,
                order_request_id=oid,
                symbol=symbol,
                broker_native_order_id=broker_native_order_id,
            )
            rows.extend(matched_rows)
        rows = _normalize_fill_history_rows(rows, limit=limit)
    else:
        rows = list(
            await repos.broker_fill_snapshots.list_recent(
                limit=limit,
                account_id=parsed_account_id,
                order_date=order_date,
                order_request_id=parsed_order_request_id,
                symbol=symbol,
                broker_native_order_id=broker_native_order_id,
            )
        )
        rows = _normalize_fill_history_rows(rows, limit=limit)
    account_cache: dict[UUID, object | None] = {}
    order_cache: dict[UUID, object | None] = {}
    instrument_name_cache: dict[str, str | None] = {}
    items: list[FillHistoryItem] = []
    for row in rows:
        account = account_cache.get(row.account_id)
        if row.account_id not in account_cache:
            account = await repos.accounts.get(row.account_id)
            account_cache[row.account_id] = account
        instrument_name = instrument_name_cache.get(row.symbol)
        if row.symbol not in instrument_name_cache:
            instrument = await repos.instruments.get_by_symbol_any_market(row.symbol)
            instrument_name = instrument.name if instrument is not None else None
            instrument_name_cache[row.symbol] = instrument_name
        linked_order = None
        if row.order_request_id is not None:
            linked_order = order_cache.get(row.order_request_id)
            if row.order_request_id not in order_cache:
                linked_order = await repos.orders.get(row.order_request_id)
                order_cache[row.order_request_id] = linked_order
        items.append(
            FillHistoryItem(
                broker_fill_snapshot_id=str(row.broker_fill_snapshot_id),
                fill_sync_run_id=str(row.fill_sync_run_id) if row.fill_sync_run_id else None,
                account_id=str(row.account_id),
                order_request_id=str(row.order_request_id) if row.order_request_id else None,
                trade_decision_id=str(linked_order.trade_decision_id)
                if linked_order is not None and linked_order.trade_decision_id is not None
                else None,
                account_alias=getattr(account, "account_alias", None),
                account_code=getattr(account, "account_code", None),
                broker_name=row.broker_name,
                broker_native_order_id=row.broker_native_order_id,
                broker_fill_id=row.broker_fill_id,
                symbol=row.symbol,
                instrument_name=instrument_name,
                side=row.side,
                order_date=row.order_date,
                order_status_code=row.order_status_code,
                cancel_yn=row.cancel_yn,
                ordered_quantity=float(row.ordered_quantity) if row.ordered_quantity is not None else None,
                filled_quantity=float(row.filled_quantity),
                fill_price=float(row.fill_price),
                order_time=row.order_time,
                fill_time=row.fill_time,
                fill_timestamp=row.fill_timestamp,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )
    return items
