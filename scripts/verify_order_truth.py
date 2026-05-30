#!/usr/bin/env python3
"""KIS ODNO 기반 Truth 진단 스크립트.

Read-only. DB 상태를 변경하지 않음.
VTTC0081R (inquire-daily-ccld) raw 조회 + ODNO 매칭 + 판정

Usage
-----
    # 단일 주문 진단 (human-readable)
    python scripts/verify_order_truth.py <order_request_id>

    # 특정 broker_native_order_id(ODNO)로 진단
    python scripts/verify_order_truth.py --odno <ODNO>

    # JSON 출력 (machine-readable)
    python scripts/verify_order_truth.py <order_request_id> --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.brokers.rate_limit import BucketType
from agent_trading.config.settings import AppSettings
from agent_trading.domain.entities import (
    BrokerAccountEntity,
    BrokerOrderEntity,
    OrderRequestEntity,
    PositionSnapshotEntity,
)
from agent_trading.domain.enums import OrderSide
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.runtime.bootstrap import postgres_runtime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 판정 타입 (verdict constants)
# ---------------------------------------------------------------------------
VERDICT_FILLED = "filled_confirmed"
VERDICT_PARTIAL = "partially_filled_suspected"
VERDICT_EXPIRED = "expired_confirmed"
VERDICT_PAPER_MISSING = "paper_truth_missing"
VERDICT_MANUAL = "needs_manual_reconciliation"

# Position-snapshot-delta 기반 판정 (VTTC0081R ODNO가 빈 문자열인 paper fallback)
VERDICT_POSITION_DELTA_FILLED = "position_delta_filled"
VERDICT_POSITION_DELTA_PARTIAL = "position_delta_partial"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify order truth via KIS VTTC0081R (inquire-daily-ccld)",
    )
    parser.add_argument(
        "order_request_id",
        nargs="?",
        type=str,
        default=None,
        help="Order request UUID to diagnose",
    )
    parser.add_argument(
        "--odno",
        type=str,
        default=None,
        help="Broker native order ID (ODNO) to diagnose (alternative to order_request_id)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output as JSON (machine-readable)",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _format_kst(dt: datetime | None) -> str:
    if dt is None:
        return "N/A"
    return dt.astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S KST")


def _get_kis_field(item: dict[str, Any], field: str, default: Any = "") -> Any:
    """KIS 응답 필드를 대소문자 무관하게 읽는다."""
    value = item.get(field)
    if value is not None and value != "":
        return value
    return item.get(field.lower(), default)


def _classify_ccld_status(
    ord_stat: str,
    ccld_qty: int,
    ord_qty: int,
) -> str:
    """ORD_STAT + 체결수량 기반 판정 분류.

    Parameters
    ----------
    ord_stat:
        KIS ORD_STAT 코드 (예: "00", "01", "11", "21", "88", "89").
    ccld_qty:
        체결 수량 (CCLD_QTY).
    ord_qty:
        주문 수량 (ORD_QTY).

    Returns
    -------
    str
        ``VERDICT_FILLED`` | ``VERDICT_PARTIAL`` | ``VERDICT_EXPIRED``
    """
    # 21/22 = 전량체결 (full fill)
    if ord_stat in ("21", "22"):
        return VERDICT_FILLED
    # 11/12 = 일부체결 (partial fill)
    if ord_stat in ("11", "12"):
        return VERDICT_PARTIAL
    # 88/89 = 취소/만료 (expired), 80 = 거절 (rejected)
    if ord_stat in ("88", "89", "80"):
        if ccld_qty == 0:
            return VERDICT_EXPIRED
        if ccld_qty < ord_qty:
            return VERDICT_PARTIAL
        return VERDICT_FILLED
    # 00, 01, 02, 05, 07 = 접수/체결/취소/미체결/정정 (일반 상태)
    if ccld_qty == 0:
        return VERDICT_EXPIRED  # 체결 없음 → 만료/취소로 간주
    if ccld_qty < ord_qty:
        return VERDICT_PARTIAL
    return VERDICT_FILLED


# ---------------------------------------------------------------------------
# Core diagnostic logic
# ---------------------------------------------------------------------------
async def _build_rest_client(
    settings: AppSettings,
    broker_account: BrokerAccountEntity,
) -> KISRestClient:
    """Build a KISRestClient following the same pattern as
    ``_build_adapter_for_broker_account()`` in reconciliation_worker.py."""
    return KISRestClient(
        api_key=settings.kis_api_key,
        api_secret=settings.kis_api_secret,
        account_number=broker_account.account_ref,
        account_product_code=settings.kis_account_product_code,
        env=settings.kis_env,
        base_url=settings.kis_base_url,
        dev_token_cache_enabled=settings.kis_dev_token_cache_enabled,
        dev_token_cache_path=settings.kis_dev_token_cache_path,
    )


async def _inquire_and_match(
    settings: AppSettings,
    broker_account: BrokerAccountEntity,
    broker_order: BrokerOrderEntity | None,
    symbol: str,
    order_side: OrderSide,
    order_created_at: datetime,
) -> dict[str, Any]:
    """Build KIS client -> authenticate -> call VTTC0081R -> match -> return verdict.

    Returns
    -------
    dict with keys:
        "inquiry" — VTTC0081R call metadata
        "match" — matched record details (or failure reason)
        "verdict" — final verdict string
        "all_raw_records" — summarised raw records
    """
    # ── 1. Build KIS client & authenticate ──
    try:
        rest_client = await _build_rest_client(settings, broker_account)
        # Authenticate explicitly to get access token
        # (KISRestClient lazy-authenticates on first API call, but let's be explicit)
        await rest_client._get_client()  # ensure HTTP client is initialized
    except Exception as e:
        return {
            "inquiry": {"error": f"Failed to build/authenticate KIS client: {e}"},
            "match": {"matched": False, "verdict": VERDICT_MANUAL, "reason": f"KIS client error: {e}"},
            "verdict": VERDICT_MANUAL,
            "all_raw_records": [],
        }

    # ── 2. Determine date range (±3 days around order creation, KST) ──
    kst_created = order_created_at.astimezone(timezone(timedelta(hours=9)))
    strt_dt = (kst_created - timedelta(days=3)).strftime("%Y%m%d")
    end_dt = (kst_created + timedelta(days=3)).strftime("%Y%m%d")

    broker_order_id = broker_order.broker_native_order_id if broker_order else None

    # ── 3. Call VTTC0081R ──
    # NOTE: We do NOT pass broker_order_id as a filter — we want ALL records
    # in the date range so we can detect empty-ODNO (paper) scenarios.
    try:
        raw_records = await rest_client.inquire_daily_ccld(
            broker_order_id=broker_order_id,  # ODNO 필터링 — 서버 측에서 미리 필터링
            symbol=None,           # 모든 심볼 조회 (paper fallback에서 symbol+side 역매칭)
            order_side=None,       # 모든 사이드 조회
            strt_dt=strt_dt,
            end_dt=end_dt,
            after_hours=True,
            bucket=BucketType.RECONCILIATION,
        )
    except Exception as e:
        return {
            "inquiry": {"strt_dt": strt_dt, "end_dt": end_dt, "error": str(e)},
            "match": {"matched": False, "verdict": VERDICT_MANUAL, "reason": f"VTTC0081R call failed: {e}"},
            "verdict": VERDICT_MANUAL,
            "all_raw_records": [],
        }
    finally:
        await rest_client.close()

    # ── 4. ODNO 매칭 시도 ──
    matched: dict[str, Any] | None = None
    all_odno_empty = True

    for item in raw_records:
        odno = _get_kis_field(item, "ODNO")
        if odno:
            all_odno_empty = False
            if broker_order_id and odno == broker_order_id:
                matched = item
                break

    # ── 5. Paper fallback: 모든 ODNO가 비어있으면 symbol+side 역순 매칭 ──
    if matched is None and all_odno_empty and broker_order_id:
        side_code = "01" if order_side == OrderSide.SELL else "02"
        candidates = [
            item
            for item in raw_records
            if _get_kis_field(item, "PDNO") == symbol
            and _get_kis_field(item, "SLL_BUY_DVSN_CD") == side_code
        ]
        if len(candidates) == 1:
            matched = candidates[0]
        elif len(candidates) > 1:
            # Sort by ORD_TMD descending (latest first), pick latest
            candidates.sort(key=lambda x: _get_kis_field(x, "ORD_TMD"), reverse=True)
            matched = candidates[0]

    # ── 6. 보조 매칭: ODNO 실패 시 symbol+side로 모든 레코드 표시 ──
    match_info = _build_match_info(
        matched=matched,
        all_records=raw_records,
        broker_order_id=broker_order_id,
        symbol=symbol,
        order_side=order_side,
    )

    return {
        "inquiry": {
            "strt_dt": strt_dt,
            "end_dt": end_dt,
            "records_found": len(raw_records),
        },
        "match": match_info,
        "verdict": match_info["verdict"],
        "all_raw_records": _summarize_records(raw_records),
    }


def _build_match_info(
    matched: dict[str, Any] | None,
    all_records: list[dict[str, Any]],
    broker_order_id: str | None,
    symbol: str,
    order_side: OrderSide,
) -> dict[str, Any]:
    """Build the 'match' subsection of the report."""
    if matched is None:
        reason = "No matching record found"
        if not all_records:
            reason = "No records returned from VTTC0081R"
        elif broker_order_id:
            # Check if ODNO exists in any of the records
            odnos_in_results = {_get_kis_field(item, "ODNO") for item in all_records if _get_kis_field(item, "ODNO")}
            if odnos_in_results:
                reason = (
                    f"ODNO {broker_order_id} not found in {len(all_records)} records. "
                    f"Available ODNOs: {sorted(odnos_in_results)}"
                )
            else:
                reason = (
                    f"All {len(all_records)} records have empty ODNO (paper scenario). "
                    "No symbol+side match found."
                )
        else:
            reason = "No broker_native_order_id available for matching"
        return {
            "matched": False,
            "verdict": VERDICT_MANUAL,
            "reason": reason,
        }

    odno = _get_kis_field(matched, "ODNO")
    pdno = _get_kis_field(matched, "PDNO")
    ord_qty = int(_get_kis_field(matched, "ORD_QTY", "0"))
    ccld_qty = int(_get_kis_field(matched, "CCLD_QTY", "0"))
    ord_stat = _get_kis_field(matched, "ORD_STAT")
    ord_tmd = _get_kis_field(matched, "ORD_TMD")
    ccld_tmd = _get_kis_field(matched, "CCLD_TMD")
    cncl_yn = _get_kis_field(matched, "CNCL_YN", "N")

    verdict = _classify_ccld_status(ord_stat, ccld_qty, ord_qty)

    # Determine match method
    if odno and odno == broker_order_id:
        match_method = "direct_odno"
    elif odno and odno != broker_order_id:
        match_method = "symbol_side_fallback"
    else:
        match_method = "symbol_side_only"

    return {
        "matched": True,
        "match_method": match_method,
        "matched_odno": odno,
        "matched_symbol": pdno,
        "kis_ord_stat": ord_stat,
        "kis_ord_stat_name": _ord_stat_label(ord_stat),
        "kis_order_qty": ord_qty,
        "kis_ccld_qty": ccld_qty,
        "kis_order_time": ord_tmd,
        "kis_ccld_time": ccld_tmd,
        "kis_cancel_yn": cncl_yn,
        "verdict": verdict,
    }


def _ord_stat_label(ord_stat: str) -> str:
    """Human-readable label for KIS ORD_STAT codes."""
    labels = {
        "00": "접수(SUBMITTED)",
        "01": "체결(FILLED/부분체결)",
        "02": "취소(CANCELLED)",
        "03": "거절(REJECTED)",
        "05": "미체결(ACKNOWLEDGED)",
        "07": "정정(ACKNOWLEDGED)",
        "11": "일부체결-1(PARTIAL)",
        "12": "일부체결-2(PARTIAL)",
        "21": "전량체결-1(FULL)",
        "22": "전량체결-2(FULL)",
        "80": "거절(REJECTED)",
        "88": "취소(CANCELLED)",
        "89": "만료(EXPIRED)",
    }
    return labels.get(ord_stat, f"UNKNOWN({ord_stat})")


def _summarize_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summarise raw records for display — key fields only."""
    summary = []
    for item in records:
        summary.append({
            "ODNO": _get_kis_field(item, "ODNO"),
            "PDNO": _get_kis_field(item, "PDNO"),
            "ORD_QTY": _get_kis_field(item, "ORD_QTY", "0"),
            "CCLD_QTY": _get_kis_field(item, "CCLD_QTY", "0"),
            "ORD_STAT": _get_kis_field(item, "ORD_STAT"),
            "SLL_BUY_DVSN_CD": _get_kis_field(item, "SLL_BUY_DVSN_CD"),
            "ORD_TMD": _get_kis_field(item, "ORD_TMD"),
            "CCLD_TMD": _get_kis_field(item, "CCLD_TMD"),
        })
    return summary


# ---------------------------------------------------------------------------
# Position snapshot delta inference
# ---------------------------------------------------------------------------
async def _get_position_delta(
    repos: RepositoryContainer,
    account_id: UUID,
    instrument_id: UUID,
    order_time: datetime,
) -> int:
    """Compute position quantity delta around the order time.

    Steps
    -----
    1. Fetch the latest position snapshot strictly before ``order_time``.
    2. Fetch the absolute latest position snapshot via ``list_latest_by_account``.
    3. If the latest snapshot is after ``order_time``, use it as post-qty.
       Otherwise there is no post-order data → delta = 0.
    4. ``delta = post_qty - pre_qty``

    Parameters
    ----------
    repos:
        Repository container with ``position_snapshots``.
    account_id:
        The account UUID (``order.account_id``).
    instrument_id:
        The instrument UUID (``order.instrument_id``).
    order_time:
        The order creation timestamp (used as the cut-off).

    Returns
    -------
    int
        ``post_qty - pre_qty``.
        Positive → BUY filled (position increased).
        Negative → SELL filled (position decreased).
        Zero → no change or no data.
    """
    # ── Pre-order snapshot (strictly before order_time) ──
    pre_snap = await repos.position_snapshots.get_latest_by_account_and_instrument_before(
        account_id, instrument_id, order_time,
    )
    pre_qty = int(pre_snap.quantity) if pre_snap else 0

    # ── Post-order snapshot (absolute latest per instrument) ──
    latest_snapshots = await repos.position_snapshots.list_latest_by_account(account_id)
    post_snap: PositionSnapshotEntity | None = None
    for snap in latest_snapshots:
        if snap.instrument_id == instrument_id:
            post_snap = snap
            break

    if post_snap is None:
        return 0  # No snapshot at all for this instrument

    # If the latest snapshot is at or before order_time, no post-order data
    if post_snap.snapshot_at <= order_time:
        return 0

    post_qty = int(post_snap.quantity)
    return post_qty - pre_qty


async def _infer_buy_fill_from_position(
    repos: RepositoryContainer,
    order: OrderRequestEntity,
    order_time: datetime,
) -> tuple[str, str, int, int, int]:
    """Infer BUY fill status from position snapshot delta.

    Parameters
    ----------
    repos:
        Repository container.
    order:
        The order request entity (provides ``account_id`` and ``instrument_id``).
    order_time:
        The order creation timestamp (cut-off for pre/post snapshot).

    Returns
    -------
    tuple[str, str, int, int, int]
        ``(verdict, reason, delta, pre_qty, post_qty)``.
        *verdict* is empty ``""`` when delta <= 0 (fallback to VTTC0081R).
    """
    # Resolve UUIDs from the order entity
    account_id = order.account_id
    instrument_id = order.instrument_id

    # ── Pre-order snapshot ──
    pre_snap = await repos.position_snapshots.get_latest_by_account_and_instrument_before(
        account_id, instrument_id, order_time,
    )
    pre_qty = int(pre_snap.quantity) if pre_snap else 0

    # ── Post-order snapshot ──
    latest_snapshots = await repos.position_snapshots.list_latest_by_account(account_id)
    post_snap: PositionSnapshotEntity | None = None
    for snap in latest_snapshots:
        if snap.instrument_id == instrument_id:
            post_snap = snap
            break

    if post_snap is None or post_snap.snapshot_at <= order_time:
        # No post-order data → cannot infer
        return ("", "No post-order position snapshot available", 0, pre_qty, 0)

    post_qty = int(post_snap.quantity)
    delta = post_qty - pre_qty
    requested_qty = int(order.requested_quantity)

    # ── 판정 로직 ──
    if delta >= requested_qty:
        reason = (
            f"Position delta ({delta:+d}) >= requested quantity ({requested_qty})"
        )
        return (VERDICT_POSITION_DELTA_FILLED, reason, delta, pre_qty, post_qty)

    if delta > 0:
        reason = (
            f"Position delta ({delta:+d}) < requested quantity ({requested_qty})"
        )
        return (VERDICT_POSITION_DELTA_PARTIAL, reason, delta, pre_qty, post_qty)

    # delta <= 0 → fallback to VTTC0081R
    reason = f"Position delta ({delta:+d}) <= 0, fallback to VTTC0081R result"
    return ("", reason, delta, pre_qty, post_qty)


# ---------------------------------------------------------------------------
# Single-order diagnosis
# ---------------------------------------------------------------------------
async def diagnose_by_order_request_id(
    repos: RepositoryContainer,
    settings: AppSettings,
    broker_account: BrokerAccountEntity,
    order_request_id: str,
) -> dict[str, Any]:
    """Diagnose a single order by its order_request_id (UUID str)."""
    oid = UUID(order_request_id)

    # 1. Get order request
    order = await repos.orders.get(oid)
    if order is None:
        return {"error": f"Order {order_request_id} not found", "verdict": VERDICT_MANUAL}

    # 2. Get broker order(s)
    broker_orders = await repos.broker_orders.list_by_order_request(oid)
    broker_order = broker_orders[0] if broker_orders else None

    # 3. Get instrument for symbol
    instrument = await repos.instruments.get(order.instrument_id)
    symbol = instrument.symbol if instrument else "UNKNOWN"

    # ── 4. Position delta inference (before VTTC0081R) ──
    position_verdict, position_reason, position_delta, position_pre_qty, position_post_qty = (
        await _infer_buy_fill_from_position(
            repos=repos,
            order=order,
            order_time=order.created_at,
        )
    )

    # ── 5. Call VTTC0081R + match ──
    inquiry_result = await _inquire_and_match(
        settings=settings,
        broker_account=broker_account,
        broker_order=broker_order,
        symbol=symbol,
        order_side=order.side,
        order_created_at=order.created_at,
    )

    # ── 6. Add position-delta info to match result ──
    match_info: dict[str, Any] = inquiry_result.get("match", {})
    if isinstance(match_info, dict):
        match_info["position_delta"] = position_delta
        match_info["position_pre_qty"] = position_pre_qty
        match_info["position_post_qty"] = position_post_qty
        match_info["position_verdict"] = position_verdict
        match_info["position_reason"] = position_reason

    # ── 7. Combined verdict ──
    # position-delta 가 중분히 크면 VTTC0081R 결과보다 우선
    if position_verdict == VERDICT_POSITION_DELTA_FILLED:
        final_verdict = VERDICT_POSITION_DELTA_FILLED
    elif position_verdict == VERDICT_POSITION_DELTA_PARTIAL:
        final_verdict = VERDICT_POSITION_DELTA_PARTIAL
    else:
        final_verdict = match_info.get("verdict", VERDICT_MANUAL)
    inquiry_result["verdict"] = final_verdict

    # ── 8. Build full report ──
    report: dict[str, Any] = {
        "order_request_id": order_request_id,
        "db_status": str(order.status.value) if hasattr(order.status, "value") else str(order.status),
        "symbol": symbol,
        "side": str(order.side),
        "requested_quantity": str(order.requested_quantity),
        "created_at": _format_kst(order.created_at),
    }

    if broker_order:
        report["broker_order"] = {
            "broker_native_order_id": broker_order.broker_native_order_id,
            "broker_status": broker_order.broker_status,
            "last_synced_at": _format_kst(broker_order.last_synced_at),
        }
    else:
        report["broker_order"] = None

    report.update(inquiry_result)
    return report


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    async with postgres_runtime(run_migrations=False) as runtime:
        repos: RepositoryContainer = runtime["repositories"]
        settings: AppSettings = runtime["settings"]

        # Get broker account — use koreainvestment
        broker_accounts = await repos.broker_accounts.list_by_broker("koreainvestment")
        if not broker_accounts:
            result = {"error": "No koreainvestment broker account found", "verdict": VERDICT_MANUAL}
            if args.json:
                print(json.dumps(result, indent=2, default=str))
            else:
                print("\nERROR: No koreainvestment broker account found in DB.\n")
            return 1
        broker_account = broker_accounts[0]

        if args.order_request_id:
            report = await diagnose_by_order_request_id(
                repos=repos,
                settings=settings,
                broker_account=broker_account,
                order_request_id=args.order_request_id,
            )
        elif args.odno:
            # Search by ODNO via broker_orders repository
            broker_order = await repos.broker_orders.get_by_native_order_id(
                "koreainvestment", args.odno,
            )
            if broker_order is None:
                report = {
                    "error": f"No orders found with ODNO {args.odno}",
                    "verdict": VERDICT_MANUAL,
                }
            else:
                report = await diagnose_by_order_request_id(
                    repos=repos,
                    settings=settings,
                    broker_account=broker_account,
                    order_request_id=str(broker_order.order_request_id),
                )
        else:
            print("Error: Provide either order_request_id or --odno")
            return 1

        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            _print_report(report)

    return 0


def _print_report(report: dict[str, Any]) -> None:
    """Print human-readable report to stdout."""
    verdict = report.get("verdict", VERDICT_MANUAL)

    print(f"\n{'=' * 60}")
    print(f"  Order Truth Verification Report")
    print(f"{'=' * 60}")
    print(f"  Verdict: {verdict}")

    if "error" in report:
        print(f"  ERROR: {report['error']}")
        print(f"{'=' * 60}\n")
        return

    oid = report.get("order_request_id", "N/A")
    print(f"  Order ID: {oid}")

    print(f"\n  [DB State]")
    print(f"    Status:   {report.get('db_status', 'N/A')}")
    print(f"    Symbol:   {report.get('symbol', 'N/A')}")
    print(f"    Side:     {report.get('side', 'N/A')}")
    print(f"    Qty:      {report.get('requested_quantity', 'N/A')}")
    print(f"    Created:  {report.get('created_at', 'N/A')}")

    bo = report.get("broker_order")
    if bo:
        print(f"\n  [Broker Order]")
        print(f"    ODNO:          {bo.get('broker_native_order_id', 'N/A')}")
        print(f"    Broker Status: {bo.get('broker_status', 'N/A')}")
        print(f"    Last Synced:   {bo.get('last_synced_at', 'N/A')}")

    inquiry = report.get("inquiry", {})
    print(f"\n  [VTTC0081R Inquiry]")
    if "error" in inquiry:
        print(f"    ERROR: {inquiry['error']}")
    else:
        print(f"    Date Range:    {inquiry.get('strt_dt', 'N/A')} ~ {inquiry.get('end_dt', 'N/A')}")
        print(f"    Records Found: {inquiry.get('records_found', 0)}")

    match = report.get("match", {})
    print(f"\n  [Match Result]")
    if match.get("matched"):
        print(f"    Method:       {match.get('match_method', 'N/A')}")
        print(f"    ODNO:         {match.get('matched_odno', 'N/A')}")
        print(f"    Symbol:       {match.get('matched_symbol', 'N/A')}")
        print(f"    KIS ORD_STAT: {match.get('kis_ord_stat', 'N/A')} ({match.get('kis_ord_stat_name', 'N/A')})")
        print(f"    Order Qty:    {match.get('kis_order_qty', 0)}")
        print(f"    Filled Qty:   {match.get('kis_ccld_qty', 0)}")
        print(f"    Order Time:   {match.get('kis_order_time', 'N/A')}")
        print(f"    Fill Time:    {match.get('kis_ccld_time', 'N/A')}")
        print(f"    Cancel YN:    {match.get('kis_cancel_yn', 'N/A')}")
    else:
        print(f"    Matched: NO")
        print(f"    Reason:  {match.get('reason', 'N/A')}")

    # ── Position Delta Inference ──
    pos_verdict = match.get("position_verdict", "")
    pos_delta = match.get("position_delta", 0)
    pos_pre_qty = match.get("position_pre_qty", 0)
    pos_post_qty = match.get("position_post_qty", 0)
    pos_reason = match.get("position_reason", "")

    if pos_verdict or pos_delta != 0:
        req_qty = int(float(report.get("requested_quantity", 0)))
        print(f"\n  [Position Delta Inference]")
        print(f"    Pre-order qty:  {pos_pre_qty}")
        print(f"    Post-order qty: {pos_post_qty}")
        print(f"    Delta:          {pos_delta:+d}")
        if pos_verdict:
            print(f"    Verdict:        {pos_verdict} ({pos_reason})")
        else:
            print(f"    Inference:      {pos_reason}")

    records = report.get("all_raw_records", [])
    if records:
        print(f"\n  [All VTTC0081R Records ({len(records)})]")
        for i, rec in enumerate(records):
            print(
                f"    {i + 1}. ODNO={rec.get('ODNO', '')} "
                f"SYM={rec.get('PDNO', '')} "
                f"ORD={rec.get('ORD_QTY', '')} "
                f"FILL={rec.get('CCLD_QTY', '')} "
                f"STAT={rec.get('ORD_STAT', '')} "
                f"SIDE={rec.get('SLL_BUY_DVSN_CD', '')} "
                f"TM={rec.get('ORD_TMD', '')} "
                f"CCLD_TM={rec.get('CCLD_TMD', '')}",
            )

    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
