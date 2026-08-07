#!/usr/bin/env python3
"""앞단(universe selection)/뒤단(decision eligibility) `signal_feature_snapshot`
정합도 실측 — read-only.

``docs/20_system_analysis/universe_selection_structural_audit.md`` §10이
소스 코드 기준으로 확인한 사실("두 경로는 같은 테이블·같은 timeframe·같은
최신-1건 로직을 쓰지만, 물리적으로 항상 같은 row라고 단정할 수는 없다")을
**실측으로 계량화**한다. 이 스크립트는 신선도 로직을 바꾸려는 것이 아니라,
앞단/뒤단이 실제로 얼마나 자주 같은 `signal_feature_snapshot_id`를 보는지
측정하는 read-only 도구다.

**[핵심 제약 — 반드시 읽을 것]** 앞단(universe selection)이 compose 시점에
실제로 어떤 `signal_feature_snapshot_id`를 봤는지는 **DB에 저장되지
않는다**(``UniverseSelectionService._core_signal_score_cache``는 프로세스
메모리에만 존재하고 영속화되지 않는다). 따라서 이 스크립트는 그 값을
**재구성(reconstruction)**한다 — ``universe_freeze_runs.frozen_at``(그
거래일의 freeze materialize 시각)을 as-of 커트오프로 써서, "그 시각 기준
가장 최근 snapshot"을 다시 조회해 "앞단이 봤을 값"을 추정한다. 이는 앞단의
원본 쿼리(``list_latest_by_instrument_ids``, as-of 필터 없음)를 그대로
재실행하는 것과 다르다 — 그대로 재실행하면 "지금 시점의 최신값"이 나와
과거 실측이 불가능하므로, `frozen_at`을 대신 as-of 컷오프로 쓴다. 이
재구성이 실제 compose 당시의 판단과 100% 같다는 보장은 없다(아래 "복원
한계" 참고).

뒤단(decision/eligibility) 값은 재구성이 아니라 **실제로 영속화된 값**이다
— ``trading.decision_contexts.signal_feature_snapshot_id`` 컬럼에 decision
생성 시점 실제로 쓰인 snapshot id가 기록되어 있다.

read-only 원칙, 외부 API/KIS 호출 없음, DB 쓰기 없음.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence
from uuid import UUID

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(str(_REPO_ROOT / ".env"))

from agent_trading.db.connection import close_pool, create_pool, get_pool  # noqa: E402

KST = timezone(timedelta(hours=9))
FREEZE_PURPOSE = "decision_loop_intraday"
TIMEFRAME = "1d"


async def resolve_account_id(conn: Any, account_alias: str) -> UUID:
    row = await conn.fetchrow(
        "SELECT account_id FROM trading.accounts WHERE account_alias = $1", account_alias
    )
    if row is None:
        raise SystemExit(f"account_alias='{account_alias}'를 찾지 못했습니다.")
    return row["account_id"]


async def fetch_daily_freeze_anchors(
    conn: Any, date_from: date, date_to: date
) -> list[dict[str, Any]]:
    """거래일별 최신 `decision_loop_intraday` freeze run(1건)을 가져온다.

    같은 거래일에 freeze가 여러 번 materialize됐을 수 있으므로(재시도 등),
    ``freeze_sequence DESC``로 가장 최근 것만 채택한다 — 이는
    ``UniverseFreezeRunRepository.get_latest()``와 동일한 tie-break다.
    """
    rows = await conn.fetch(
        """
        SELECT DISTINCT ON (business_date)
            universe_freeze_run_id, business_date, frozen_at
        FROM trading.universe_freeze_runs
        WHERE freeze_purpose = $1
          AND business_date >= $2
          AND business_date <= $3
        ORDER BY business_date, freeze_sequence DESC, frozen_at DESC
        """,
        FREEZE_PURPOSE,
        date_from,
        date_to,
    )
    return [dict(r) for r in rows]


async def fetch_core_freeze_items(
    conn: Any, universe_freeze_run_id: UUID
) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT instrument_id, symbol
        FROM trading.universe_freeze_run_items
        WHERE universe_freeze_run_id = $1 AND source_type = 'core'
        """,
        universe_freeze_run_id,
    )
    return [dict(r) for r in rows]


async def fetch_front_end_snapshot(
    conn: Any, instrument_id: UUID, as_of: datetime
) -> dict[str, Any] | None:
    """앞단이 그 시각(`frozen_at`) 기준으로 봤을 snapshot을 재구성한다.

    universe_selection의 원본 쿼리(``list_latest_by_instrument_ids``)와
    동일한 정렬·tie-break(``snapshot_at DESC, signal_feature_snapshot_id
    DESC``)를 쓰되, ``snapshot_at <= as_of`` 커트오프를 추가해 "그 시각
    기준 최신"을 재현한다.
    """
    row = await conn.fetchrow(
        """
        SELECT signal_feature_snapshot_id, snapshot_at
        FROM trading.signal_feature_snapshots
        WHERE instrument_id = $1 AND timeframe = $2 AND snapshot_at <= $3
        ORDER BY snapshot_at DESC, signal_feature_snapshot_id DESC
        LIMIT 1
        """,
        instrument_id,
        TIMEFRAME,
        as_of,
    )
    return dict(row) if row else None


async def fetch_back_end_snapshot_ids(
    conn: Any, account_id: UUID, symbol: str, business_date: date
) -> list[dict[str, Any]]:
    """그 거래일 그 종목(core)의 실제 decision들이 쓴
    `signal_feature_snapshot_id`(영속화된 값)를 전부 가져온다."""
    rows = await conn.fetch(
        """
        SELECT DISTINCT dc.signal_feature_snapshot_id
        FROM trading.trade_decisions td
        JOIN trading.decision_contexts dc
            ON dc.decision_context_id = td.decision_context_id
        WHERE dc.account_id = $1
          AND td.source_type = 'core'
          AND td.symbol = $2
          AND (td.created_at AT TIME ZONE 'Asia/Seoul')::date = $3
          AND dc.signal_feature_snapshot_id IS NOT NULL
        """,
        account_id,
        symbol,
        business_date,
    )
    return [dict(r) for r in rows]


async def fetch_snapshot_at_by_id(
    conn: Any, snapshot_ids: Sequence[UUID]
) -> dict[UUID, datetime]:
    if not snapshot_ids:
        return {}
    rows = await conn.fetch(
        """
        SELECT signal_feature_snapshot_id, snapshot_at
        FROM trading.signal_feature_snapshots
        WHERE signal_feature_snapshot_id = ANY($1::uuid[])
        """,
        list(snapshot_ids),
    )
    return {r["signal_feature_snapshot_id"]: r["snapshot_at"] for r in rows}


def _classify_mismatch(
    front_id: UUID | None,
    front_snapshot_at: datetime | None,
    back_ids: list[UUID],
    snapshot_at_lookup: dict[UUID, datetime],
) -> str:
    if front_id is None and not back_ids:
        return "둘 다 없음(데이터 없음)"
    if front_id is None and back_ids:
        return "앞단 없음/뒤단만 있음"
    if front_id is not None and not back_ids:
        return "뒤단 없음/앞단만 있음"
    if front_id in back_ids:
        return "일치"
    # 불일치 — snapshot_at이 같은지(=tie-break 차이) 다른지(=타이밍 차이) 구분
    for back_id in back_ids:
        back_at = snapshot_at_lookup.get(back_id)
        if back_at is not None and front_snapshot_at is not None and back_at == front_snapshot_at:
            return "불일치(snapshot_at은 같고 id만 다름 — tie-break 차이 실증)"
    return "불일치(snapshot_at 자체가 다름 — 타이밍 차이로 추정)"


async def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="앞단/뒤단 signal_feature_snapshot 정합도 실측(read-only)"
    )
    parser.add_argument("--date-from", required=True, help="YYYY-MM-DD (KST 기준)")
    parser.add_argument("--date-to", required=True, help="YYYY-MM-DD (KST 기준)")
    parser.add_argument("--account-alias", default="Entrypoint Paper")
    parser.add_argument("--output-json", default=None)
    args = parser.parse_args(argv)

    date_from = datetime.strptime(args.date_from, "%Y-%m-%d").date()
    date_to = datetime.strptime(args.date_to, "%Y-%m-%d").date()

    await create_pool()
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            account_id = await resolve_account_id(conn, args.account_alias)
            anchors = await fetch_daily_freeze_anchors(conn, date_from, date_to)
            print(f"[수집] 거래일별 freeze anchor {len(anchors)}건")

            comparisons: list[dict[str, Any]] = []
            for anchor in anchors:
                business_date: date = anchor["business_date"]
                frozen_at: datetime = anchor["frozen_at"]
                items = await fetch_core_freeze_items(conn, anchor["universe_freeze_run_id"])
                for item in items:
                    front = await fetch_front_end_snapshot(
                        conn, item["instrument_id"], frozen_at
                    )
                    front_id = front["signal_feature_snapshot_id"] if front else None
                    front_at = front["snapshot_at"] if front else None

                    back_rows = await fetch_back_end_snapshot_ids(
                        conn, account_id, item["symbol"], business_date
                    )
                    back_ids = [r["signal_feature_snapshot_id"] for r in back_rows]
                    snapshot_at_lookup = await fetch_snapshot_at_by_id(conn, back_ids)

                    classification = _classify_mismatch(
                        front_id, front_at, back_ids, snapshot_at_lookup
                    )
                    comparisons.append(
                        {
                            "business_date": business_date.isoformat(),
                            "symbol": item["symbol"],
                            "front_end_snapshot_id": str(front_id) if front_id else None,
                            "front_end_snapshot_at": (
                                front_at.isoformat() if front_at else None
                            ),
                            "back_end_snapshot_ids": [str(b) for b in back_ids],
                            "back_end_snapshot_id_count": len(back_ids),
                            "classification": classification,
                        }
                    )

        print(f"[수집] 종목x거래일 비교 {len(comparisons)}건")

        total = len(comparisons)
        by_classification = Counter(c["classification"] for c in comparisons)
        by_date: dict[str, Counter] = defaultdict(Counter)
        by_symbol_mismatch: Counter = Counter()
        for c in comparisons:
            by_date[c["business_date"]][c["classification"]] += 1
            if c["classification"].startswith("불일치"):
                by_symbol_mismatch[c["symbol"]] += 1

        match_count = by_classification.get("일치", 0)
        mismatch_count = sum(
            v for k, v in by_classification.items() if k.startswith("불일치")
        )
        tie_break_count = by_classification.get(
            "불일치(snapshot_at은 같고 id만 다름 — tie-break 차이 실증)", 0
        )

        summary = {
            "date_range": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "account_alias": args.account_alias,
            "total_comparisons": total,
            "match_count": match_count,
            "match_rate": round(match_count / total, 4) if total else None,
            "mismatch_count": mismatch_count,
            "mismatch_rate": round(mismatch_count / total, 4) if total else None,
            "tie_break_evidenced_mismatch_count": tie_break_count,
            "classification_distribution": dict(by_classification),
            "by_date": {d: dict(c) for d, c in sorted(by_date.items())},
            "top_repeated_mismatch_symbols": by_symbol_mismatch.most_common(15),
        }

        print("\n=== 요약 ===")
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))

        if args.output_json:
            os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
            with open(args.output_json, "w", encoding="utf-8") as f:
                json.dump(
                    {"summary": summary, "comparisons": comparisons},
                    f,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
            print(f"\n[출력] 결과 JSON 저장: {args.output_json}")
    finally:
        await close_pool()

    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
