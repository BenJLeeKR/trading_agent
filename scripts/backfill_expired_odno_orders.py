#!/usr/bin/env python3
"""Backfill: expired 상태 + ODNO 있음 → verify_order_truth 분류 후 auto_fix_safe만 보정.

2026-05-28 ~ 2026-05-29 기간의 expired+ODNO 주문들을
``verify_order_truth`` 진단 결과에 따라 3분류(``auto_fix_safe``, ``truth_probe_conflict``, ``manual``)하고
auto_fix_safe 케이스에 한해 FILLED / PARTIALLY_FILLED 로 상태를 업데이트한다.

Usage
-----
    # Dry-run (변경 없음)
    python3 scripts/backfill_expired_odno_orders.py --dry-run

    # 실제 적용
    python3 scripts/backfill_expired_odno_orders.py

    # 특정 일자 범위
    python3 scripts/backfill_expired_odno_orders.py \\
        --from-date 2026-05-28 --to-date 2026-05-29

    # 특정 주문만 처리
    python3 scripts/backfill_expired_odno_orders.py \\
        --order-ids <uuid1> <uuid2>

    # JSON 출력
    python3 scripts/backfill_expired_odno_orders.py --dry-run --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_trading.db.connection import DatabaseConfig, close_pool, create_pool

logger = logging.getLogger(__name__)

# ── Verdict constants (from verify_order_truth.py) ─────────────────────────
VERDICT_FILLED = "filled_confirmed"
VERDICT_PARTIAL = "partially_filled_suspected"
VERDICT_EXPIRED = "expired_confirmed"
VERDICT_PAPER_MISSING = "paper_truth_missing"
VERDICT_MANUAL = "needs_manual_reconciliation"
VERDICT_POSITION_DELTA_FILLED = "position_delta_filled"
VERDICT_POSITION_DELTA_PARTIAL = "position_delta_partial"

# ── Classification constants ──────────────────────────────────────────────
CLASS_AUTO_FIX_SAFE = "auto_fix_safe"
CLASS_TRUTH_PROBE_CONFLICT = "truth_probe_conflict"
CLASS_MANUAL = "manual"

# KIS ORD_STAT codes that indicate fill/partial-fill
KIS_FILL_CODES = {"21", "22", "11", "12"}

# ── Logging / tmp / paths ────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
TMP_DIR = os.path.join(BASE_DIR, "tmp")
VERIFY_SCRIPT = os.path.join(BASE_DIR, "scripts", "verify_order_truth.py")

os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(TMP_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill expired+ODNO orders based on verify_order_truth classification",
    )
    parser.add_argument(
        "--from-date",
        type=str,
        default="2026-05-28",
        help="조회 시작일 (YYYY-MM-DD, 기본: 2026-05-28)",
    )
    parser.add_argument(
        "--to-date",
        type=str,
        default="2026-05-29",
        help="조회 종료일 (YYYY-MM-DD, 기본: 2026-05-29)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="변경 없이 분류만 표시 (기본: False)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="JSON 출력 (기본: False)",
    )
    parser.add_argument(
        "--order-ids",
        type=str,
        nargs="*",
        default=None,
        help="특정 주문 UUID만 처리 (공백 구분)",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=os.path.join(LOGS_DIR, "backfill_expired_odno_orders.log"),
        help="로그 파일 경로 (기본: logs/backfill_expired_odno_orders.log)",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# 1. DB inventory query
# ---------------------------------------------------------------------------
async def _query_inventory(
    from_date: str | date,
    to_date: str | date,
    order_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """DB에서 expired + ODNO 있는 주문 목록을 조회한다."""
    # 문자열 날짜를 date 객체로 변환 (asyncpg는 date/datetime 객체를 요구함)
    if isinstance(from_date, str):
        from_date = date.fromisoformat(from_date)
    if isinstance(to_date, str):
        to_date = date.fromisoformat(to_date)

    pool = await create_pool()

    sql = """
        SELECT
            o.order_request_id,
            o.side,
            o.requested_quantity,
            o.status,
            o.created_at,
            bo.broker_order_id,
            bo.broker_native_order_id,
            bo.broker_status,
            i.symbol
        FROM trading.order_requests o
        JOIN trading.broker_orders bo ON bo.order_request_id = o.order_request_id
        JOIN trading.instruments i ON i.instrument_id = o.instrument_id
        WHERE o.status = 'expired'
          AND bo.broker_native_order_id IS NOT NULL
          AND bo.broker_native_order_id != ''
          AND o.created_at >= $1::timestamptz
          AND o.created_at < $2::timestamptz
        ORDER BY o.created_at DESC
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, from_date, to_date)

    results: list[dict[str, Any]] = []
    for row in rows:
        rec = dict(row)
        rec["order_request_id"] = str(rec["order_request_id"])
        rec["broker_order_id"] = str(rec["broker_order_id"])
        results.append(rec)

    # 특정 order_ids 필터
    if order_ids:
        order_id_set = set(order_ids)
        results = [r for r in results if r["order_request_id"] in order_id_set]

    return results


# ---------------------------------------------------------------------------
# 2. verify_order_truth subprocess 호출
# ---------------------------------------------------------------------------
async def _run_verify_order_truth(order_request_id: str) -> dict[str, Any]:
    """``verify_order_truth.py``를 subprocess로 호출하고 JSON 결과를 파싱한다.

    Returns
    -------
    dict
        성공 시: 파싱된 JSON dict.
        실패 시: ``{"error": "<reason>", "verdict": "needs_manual_reconciliation"}``
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            VERIFY_SCRIPT,
            order_request_id,
            "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=BASE_DIR,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)

        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="replace").strip()
            return {
                "error": f"verify_order_truth exited code={proc.returncode}: {err_msg}",
                "verdict": VERDICT_MANUAL,
            }

        raw = stdout.decode("utf-8", errors="replace").strip()
        if not raw:
            return {
                "error": "verify_order_truth returned empty output",
                "verdict": VERDICT_MANUAL,
            }

        # JSON 파싱 - 첫 번째 JSON 블록 찾기
        # verify_order_truth.py는 print(json.dumps(...))로 출력하므로
        # stdout 전체가 JSON이다.
        try:
            result: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as e:
            return {
                "error": f"JSON parse error: {e}. Raw output: {raw[:500]}",
                "verdict": VERDICT_MANUAL,
            }

        return result

    except asyncio.TimeoutError:
        return {
            "error": "verify_order_truth timed out after 120s",
            "verdict": VERDICT_MANUAL,
        }
    except Exception as e:
        return {
            "error": f"Subprocess error: {e}",
            "verdict": VERDICT_MANUAL,
        }


# ---------------------------------------------------------------------------
# 3. Classification
# ---------------------------------------------------------------------------
def _parse_qty(raw: Any) -> int | None:
    """수량 값을 안전하게 정수로 파싱한다."""
    if raw is None:
        return None
    try:
        return int(float(str(raw)))
    except (ValueError, TypeError):
        return None


def _classify(result: dict[str, Any], requested_quantity: Any) -> tuple[str, str | None, str | None]:
    """verify_order_truth 결과를 3분류한다.

    Parameters
    ----------
    result : dict
        ``_run_verify_order_truth()`` 반환값 (verify_order_truth.py의 JSON 출력).
    requested_quantity : Any
        DB의 ``order_requests.requested_quantity`` 값.

    Returns
    -------
    tuple[str, str | None, str | None]
        ``(classification, target_status, reason)``
    """
    # ── 1. manual 조건 체크 ──
    error = result.get("error")
    if error:
        return (CLASS_MANUAL, None, f"Error: {error}")

    verdict = result.get("verdict", "")
    match = result.get("match", {})
    if not isinstance(match, dict):
        return (CLASS_MANUAL, None, f"match is not a dict: {match}")

    matched = match.get("matched", False)

    # Verdict가 manual이면 manual
    if verdict == VERDICT_MANUAL:
        reason = match.get("reason", "verdict=needs_manual_reconciliation")
        return (CLASS_MANUAL, None, reason)

    # ODNO 매칭 실패 → manual
    if not matched:
        reason = match.get("reason", "ODNO matching failed")
        return (CLASS_MANUAL, None, reason)

    # ── 2. truth_probe_conflict 조건 체크 ──
    match_verdict = match.get("verdict", "")
    kis_ord_stat = match.get("kis_ord_stat", "")
    kis_ccld_qty_raw = match.get("kis_ccld_qty")
    kis_order_qty_raw = match.get("kis_order_qty")
    position_delta = match.get("position_delta", 0)
    position_verdict = match.get("position_verdict", "")

    kis_ccld_qty = _parse_qty(kis_ccld_qty_raw)
    kis_order_qty = _parse_qty(kis_order_qty_raw)
    req_qty = _parse_qty(requested_quantity)

    reasons: list[str] = []

    # 2a. position-delta 기반 판정이면 conflict
    if position_verdict in (VERDICT_POSITION_DELTA_FILLED, VERDICT_POSITION_DELTA_PARTIAL):
        reasons.append(f"position_verdict={position_verdict}")

    # 2b. match verdict가 paper_truth_missing / position_delta_* 이면 conflict
    if match_verdict in (VERDICT_PAPER_MISSING, VERDICT_POSITION_DELTA_FILLED, VERDICT_POSITION_DELTA_PARTIAL):
        reasons.append(f"match_verdict={match_verdict}")

    # 2c. ORD_STAT이 체결코드(21,22,11,12)가 아닌데 ccld_qty > 0 이면 conflict
    if kis_ord_stat and kis_ord_stat not in KIS_FILL_CODES and kis_ccld_qty is not None and kis_ccld_qty > 0:
        reasons.append(f"kis_ord_stat={kis_ord_stat} is not fill code but kis_ccld_qty={kis_ccld_qty}>0")

    # 2d. qty mismatch — filled_confirmed인데 ccld_qty != requested_quantity 면 conflict
    #     partially_filled_suspected인 경우 ccld_qty < requested_quantity 는 정상.
    if verdict == VERDICT_FILLED and kis_ccld_qty is not None and req_qty is not None and kis_ccld_qty != req_qty:
        reasons.append(f"qty mismatch: KIS ccld={kis_ccld_qty}, DB requested={req_qty} (verdict={verdict})")
    #     partially_filled 인데 ccld_qty > requested_quantity 면 conflict (말이 안 됨)
    if verdict == VERDICT_PARTIAL and kis_ccld_qty is not None and req_qty is not None and kis_ccld_qty > req_qty:
        reasons.append(f"qty mismatch: KIS ccld={kis_ccld_qty} > DB requested={req_qty} (verdict={verdict})")

    # 2e. position_delta는 있는데 KIS 매칭이 실패한 경우
    # (matched == True 이므로 이미 위에서 걸러졌지만, position_delta != 0 확인)
    if position_delta and isinstance(position_delta, (int, float)) and position_delta != 0:
        # position_verdict가 비어있는데 delta가 있으면 conflict
        if not position_verdict:
            reasons.append(f"position_delta={position_delta} but no position_verdict")

    if reasons:
        return (CLASS_TRUTH_PROBE_CONFLICT, None, "; ".join(reasons))

    # ── 3. auto_fix_safe 조건 체크 ──
    # 3a. direct_odno 매칭
    match_method = match.get("match_method", "")
    if match_method != "direct_odno":
        return (CLASS_MANUAL, None, f"match_method={match_method} is not direct_odno")

    # 3b. verdict가 filled_confirmed 또는 partially_filled_suspected
    if verdict == VERDICT_EXPIRED:
        # 이미 expired → 변경 불필요 (auto_fix_safe지만 target_status=None)
        return (CLASS_AUTO_FIX_SAFE, None, "Already expired confirmed, no change needed")

    if verdict not in (VERDICT_FILLED, VERDICT_PARTIAL):
        return (CLASS_MANUAL, None, f"Unexpected verdict={verdict} for direct_odno match")

    # 3c. target_status 결정 (위에서 qty mismatch를 이미 체크했으므로 여기서는 중복 체크 불필요)
    target_status: str | None = None
    if verdict == VERDICT_FILLED:
        target_status = "filled"
    elif verdict == VERDICT_PARTIAL:
        target_status = "partially_filled"
    else:
        # expired_confirmed는 target_status=None
        pass

    return (CLASS_AUTO_FIX_SAFE, target_status, None)


# ---------------------------------------------------------------------------
# 4. Apply fix
# ---------------------------------------------------------------------------
async def _apply_fix(
    order_request_id: str,
    target_status: str,
    conn,
) -> bool:
    """auto_fix_safe 케이스에 대해 DB 업데이트를 수행한다.

    Returns
    -------
    bool
        업데이트 성공 여부 (영향받은 row가 1이면 True).
    """
    sql = """
        UPDATE trading.order_requests
        SET status = $1::text,
            updated_at = NOW()
        WHERE order_request_id = $2::uuid
          AND status = 'expired'
    """
    result = await conn.execute(sql, target_status, order_request_id)
    # asyncpg execute returns e.g. "UPDATE 1"
    parts = result.split()
    if len(parts) == 2 and parts[0].upper() == "UPDATE":
        return int(parts[1]) >= 1
    return False


# ---------------------------------------------------------------------------
# 5. Main orchestrator
# ---------------------------------------------------------------------------
async def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # Logging setup
    log_level = logging.INFO
    log_format = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(
        level=log_level,
        format=log_format,
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(args.log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )

    from_date = args.from_date
    to_date = args.to_date
    dry_run = args.dry_run
    use_json = args.json
    order_ids = args.order_ids

    logger.info("Starting backfill_expired_odno_orders (dry_run=%s, from=%s, to=%s)",
                dry_run, from_date, to_date)

    # ── 1. DB inventory 조회 ──
    inventory = await _query_inventory(from_date, to_date, order_ids)
    total = len(inventory)
    logger.info("Found %d expired+ODNO order(s) in date range %s ~ %s",
                total, from_date, to_date)

    if total == 0:
        msg = "No orders to process."
        if use_json:
            print(json.dumps({"total": 0, "message": msg}, indent=2))
        else:
            print(msg)
        return 0

    # ── 2. 각 주문에 대해 verify_order_truth 실행 → 분류 ──
    orders_output: list[dict[str, Any]] = []
    counts: dict[str, int] = {
        CLASS_AUTO_FIX_SAFE: 0,
        CLASS_TRUTH_PROBE_CONFLICT: 0,
        CLASS_MANUAL: 0,
    }
    applied_filled = 0
    applied_partial = 0

    # DB pool for update (dry-run이 아니면)
    pool = await create_pool()

    for i, inv in enumerate(inventory):
        oid = inv["order_request_id"]
        symbol = inv["symbol"]
        side = inv["side"]
        req_qty = inv["requested_quantity"]
        broker_native_odno = inv["broker_native_order_id"]

        logger.info("[%d/%d] Processing order=%s symbol=%s side=%s odno=%s",
                    i + 1, total, oid, symbol, side, broker_native_odno)

        # verify_order_truth 실행
        result = await _run_verify_order_truth(oid)

        # 분류
        classification, target_status, reason = _classify(result, req_qty)
        counts[classification] = counts.get(classification, 0) + 1

        # auto_fix_safe이고 target_status가 있으면 적용 시도
        applied = False
        if classification == CLASS_AUTO_FIX_SAFE and target_status is not None:
            if not dry_run:
                async with pool.acquire() as conn:
                    applied = await _apply_fix(oid, target_status, conn)
                if applied:
                    if target_status == "filled":
                        applied_filled += 1
                    elif target_status == "partially_filled":
                        applied_partial += 1
                    logger.info("  → APPLIED: status=%s ✅", target_status)
                else:
                    logger.warning("  → APPLY FAILED (no matching expired row for order=%s)", oid)
            else:
                # dry-run: 적용하지 않음
                applied = True  # would-apply 표시
                if target_status == "filled":
                    applied_filled += 1
                elif target_status == "partially_filled":
                    applied_partial += 1
                logger.info("  → WOULD APPLY (dry-run): status=%s", target_status)
        elif classification == CLASS_AUTO_FIX_SAFE and target_status is None:
            logger.info("  → SKIP (already expired, no change needed)")
        elif classification == CLASS_TRUTH_PROBE_CONFLICT:
            logger.info("  → SKIP (conflict): %s", reason)
        else:
            logger.info("  → SKIP (manual): %s", reason)

        # 출력용 record
        record: dict[str, Any] = {
            "order_request_id": oid,
            "symbol": symbol,
            "side": side,
            "requested_qty": req_qty,
            "classification": classification,
            "target_status": target_status,
            "verdict": result.get("verdict", ""),
            "match_method": result.get("match", {}).get("match_method", ""),
            "reason": reason,
        }
        orders_output.append(record)

    # ── DB pool 정리 ──
    await close_pool()

    # ── 3. 요약 출력 ──
    if use_json:
        _print_json_summary(
            from_date=from_date,
            to_date=to_date,
            dry_run=dry_run,
            total=total,
            counts=counts,
            applied_filled=applied_filled,
            applied_partial=applied_partial,
            orders=orders_output,
        )
    else:
        _print_human_summary(
            from_date=from_date,
            to_date=to_date,
            dry_run=dry_run,
            total=total,
            counts=counts,
            applied_filled=applied_filled,
            applied_partial=applied_partial,
            orders=orders_output,
        )

    return 0


# ---------------------------------------------------------------------------
# 출력 포맷
# ---------------------------------------------------------------------------
def _print_human_summary(
    from_date: str,
    to_date: str,
    dry_run: bool,
    total: int,
    counts: dict[str, int],
    applied_filled: int,
    applied_partial: int,
    orders: list[dict[str, Any]],
) -> None:
    """Human-readable 보고서 출력."""
    mode = "DRY-RUN" if dry_run else "APPLY"
    print()
    print("=== ODNO Expired Orders Backfill Report ===")
    print(f"Date Range: {from_date} ~ {to_date}")
    print(f"Mode: {mode}")
    print()
    print("Order Summary:")
    print(f"  Total expired + ODNO: {total}")
    print(f"  auto_fix_safe:        {counts.get(CLASS_AUTO_FIX_SAFE, 0)}  "
          f"→ FILLED({applied_filled}), PARTIALLY_FILLED({applied_partial})")
    print(f"  truth_probe_conflict: {counts.get(CLASS_TRUTH_PROBE_CONFLICT, 0)}")
    print(f"  manual:               {counts.get(CLASS_MANUAL, 0)}")
    print()
    print("Details:")

    for rec in orders:
        oid = rec["order_request_id"]
        symbol = rec["symbol"]
        side = rec["side"]
        qty = rec["requested_qty"]
        classification = rec["classification"]
        target_status = rec["target_status"]
        verdict = rec["verdict"]
        match_method = rec.get("match_method", "")
        reason = rec.get("reason")

        tag = f"[{classification}]"
        if classification == CLASS_AUTO_FIX_SAFE:
            if target_status:
                print(f"  {tag} {oid}")
                print(f"    Symbol: {symbol}, Side: {side}, Qty: {qty}→{qty}")
                print(f"    Verdict: {verdict}, Match: {match_method}")
                status_str = target_status.upper()
                action = "WOULD APPLY" if dry_run else "APPLIED"
                print(f"    → {status_str} ✅ ({action})")
            else:
                print(f"  {tag} {oid}")
                print(f"    Symbol: {symbol}, Side: {side}, Qty: {qty}")
                print(f"    Verdict: {verdict}, Match: {match_method}")
                print(f"    → SKIP (already expired, no change needed)")
        elif classification == CLASS_TRUTH_PROBE_CONFLICT:
            print(f"  {tag} {oid}")
            print(f"    Symbol: {symbol}, Side: {side}, Qty: {qty}")
            print(f"    Verdict: {verdict}, Match: {match_method}")
            print(f"    Reason: {reason}")
            print(f"    → SKIP (conflict)")
        else:
            print(f"  {tag} {oid}")
            print(f"    Symbol: {symbol}, Side: {side}, Qty: {qty}")
            print(f"    Verdict: {verdict}")
            print(f"    Reason: {reason}")
            print(f"    → SKIP (manual)")
        print()

    print("Summary:")
    if dry_run:
        print(f"  Would apply: {applied_filled} orders → FILLED")
        print(f"  Would apply: {applied_partial} orders → PARTIALLY_FILLED")
    else:
        print(f"  Applied: {applied_filled} orders → FILLED")
        print(f"  Applied: {applied_partial} orders → PARTIALLY_FILLED")
    print(f"  Skipped (conflict): {counts.get(CLASS_TRUTH_PROBE_CONFLICT, 0)} orders")
    print(f"  Skipped (manual): {counts.get(CLASS_MANUAL, 0)} orders")
    print()


def _print_json_summary(
    from_date: str,
    to_date: str,
    dry_run: bool,
    total: int,
    counts: dict[str, int],
    applied_filled: int,
    applied_partial: int,
    orders: list[dict[str, Any]],
) -> None:
    """JSON 형식 보고서 출력."""
    summary: dict[str, Any] = {
        "date_range": {"from": from_date, "to": to_date},
        "dry_run": dry_run,
        "total": total,
        "auto_fix_safe": counts.get(CLASS_AUTO_FIX_SAFE, 0),
        "truth_probe_conflict": counts.get(CLASS_TRUTH_PROBE_CONFLICT, 0),
        "manual": counts.get(CLASS_MANUAL, 0),
        "applied": {
            "filled": applied_filled,
            "partially_filled": applied_partial,
        },
        "orders": orders,
    }

    # JSON 직렬화 가능하도록 변환
    def _serialize(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _serialize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_serialize(v) for v in obj]
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, float):
            return obj
        if isinstance(obj, int):
            return obj
        if obj is None:
            return None
        return str(obj)

    print(json.dumps(_serialize(summary), indent=2, ensure_ascii=False))


# ── Entry point ──────────────────────────────────────────────────────────
def entry_point(argv: list[str] | None = None) -> int:
    return asyncio.run(main(argv))


if __name__ == "__main__":
    sys.exit(entry_point())
