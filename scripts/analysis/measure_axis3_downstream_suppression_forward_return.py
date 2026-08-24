#!/usr/bin/env python3
"""`SPPV-3` 축 3(downstream 분리 순수 deterministic 성과) 재현 분석 도구 — read-only.

``docs/40_action_plans/post_sppv3_policy_evaluation_design_2026-08-20.md``
§16.4~16.6이 확정한 축 3 계약(population/dedupe/가상 진입가/horizon/층화)을
같은 명령으로 재현 가능하게 코드화한다. 이 스크립트는 **정책 결론을 내리지
않는다** — 축 1이 이미 Hold로 종합 판정됐고(같은 문서 §16.3/§16.7), 축 3은
그 자체로 표본이 축적되기 전까지 정책 변경 근거가 아니라 관측 도구다.

분석 질문
---------
deterministic 레이어에서 ``BUY_CANDIDATE``였던 종목이 downstream에서
``matched``(매수 의도 유지)로 남은 경우와 ``downgraded``(매수 의도 하향)
로 바뀐 경우의 가상 forward return을 같은 규약으로 비교할 수 있는가?

고정 계약(요약, 상세는 위 문서 §16.4)
--------------------------------------
- **population**: ``candidate_intent='buy' AND primary_candidate=
  'BUY_CANDIDATE'``인 ``trade_decisions`` 행만 대상. ``alignment_status``가
  ``matched``/``downgraded``인 것만 주 population, ``diverged``(실거래
  REDUCE)/``suppressed``·``upgraded``·``promoted_from_no_action``(watch
  기원, 구조적으로 buy-intent에는 나타나지 않음)은 명시적으로 제외한다.
- **dedupe**: (symbol, KST 거래일) 단위로 그날의 모든 cycle을 모아 대표
  라벨(그날 가장 많이 등장한 ``alignment_status``) + 오염도(비-지배 cycle
  비율)로 압축한다. 정확히 50:50 동률은 ``mixed_tie``로 별도 제외한다.
- **가상 진입가**: 결정일(KST 거래일) 종가. 1차 소스는
  ``instrument_status_snapshots``(``source_type='kis_stock_basic_info'``)
  의 ``raw_payload_json->>'thdt_clpr'``이며, 실제 거래일은 같은 payload의
  ``clpr_chng_dt``(KIS가 직접 제공하는 종가 갱신일)로 판별한다 — 달력
  추정을 쓰지 않는다. 대체 소스는 ``signal_feature_snapshots``
  (``timeframe='1d'``)의 ``sma_20 * (1 + price_vs_sma_20_pct/100)`` 파생
  값이며, 1차 소스가 없는 (instrument, trade_date)에만 보완적으로 쓴다.
  결정이 그날 장중에 이뤄졌다면 "결정일 종가"에는 결정 이후의 장중 변동이
  일부 포함되는 약한 look-ahead가 있다 — 장중 tick 데이터가 없어 제거할
  수 없고, 결과 메타데이터에 명시만 한다.
- **horizon**: T+1/T+5/T+20(기본값, ``--horizons``로 변경 가능)을 종목별
  실제 거래일 순서(가격 소스에 실제로 존재하는 거래일 리스트에서의 위치)
  로 계산한다. ``--as-of-date`` 기준으로 아직 그만큼의 거래일이 쌓이지
  않았으면 수익률을 0/NULL로 채우지 않고 ``horizon_not_arrived``로
  별도 집계한다. 실제 주문/체결/실현손익(``realized_pnl_events`` 등)은
  이 가상 forward return 분석과 절대 섞지 않는다(이번 스크립트는 그
  테이블들을 조회하지 않는다).
- **층화**: ``risk_tone``/``regime_label``/``source_type``/
  ``policy_git_sha``를 보조 층화 변수로 출력한다. ``policy_git_sha``가
  NULL인 표본은 ``unknown_pre_fingerprint`` 버킷으로 명시적으로 분리하고,
  NULL 구간과 실제 SHA 구간을 같은 정책으로 합치지 않는다. 특정 SHA의
  표본이 충분하지 않으면(현재 항상 그렇다) 정책별 성과 결론을 내리지
  않는다 — 분포만 보고한다.

DB는 read-only transaction(``conn.transaction(readonly=True)``) 안에서
SELECT/CTE만 실행한다. ``CREATE TEMP TABLE``/``CREATE TABLE``/쓰기 SQL은
전혀 만들지 않는다. 외부 API·KIS 호출 없음, 컨테이너 재기동 없음.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(str(_REPO_ROOT / ".env"))

from agent_trading.db.connection import close_pool, create_pool, get_pool  # noqa: E402

KST = timezone(timedelta(hours=9))

DEDUPE_CONTRACT_VERSION = "axis3-dedupe-v1"

# 주 population에 속하지 않는 alignment_status와, 그것이 왜 buy-intent
# population에서 제외되는지(§16.4). ``suppressed``/``upgraded``/
# ``promoted_from_no_action``은 구조적으로 candidate_intent='buy'에서는
# 발생하지 않는다(watch/no_action 기원 전용) — 그래도 명시적으로 0건임을
# 보고한다.
PRIMARY_STATUSES = ("matched", "downgraded")
KNOWN_NON_PRIMARY_STATUSES = (
    "diverged",
    "suppressed",
    "upgraded",
    "promoted_from_no_action",
)

BUY_RAW_SQL = """
    SELECT
        td.trade_decision_id,
        td.instrument_id,
        td.symbol,
        (td.created_at AT TIME ZONE 'Asia/Seoul')::date AS kst_date,
        td.created_at,
        td.decision_json -> 'candidate_vs_final' ->> 'alignment_status' AS alignment_status,
        td.regime_label,
        td.decision_json -> 'deterministic_trigger' -> 'metadata' ->> 'risk_tone' AS risk_tone,
        td.source_type,
        td.policy_git_sha
    FROM trading.trade_decisions td
    WHERE td.decision_json -> 'candidate_vs_final' ->> 'candidate_intent' = 'buy'
      AND td.decision_json -> 'candidate_vs_final' ->> 'primary_candidate' = 'BUY_CANDIDATE'
      AND (td.created_at AT TIME ZONE 'Asia/Seoul')::date >= $1
      AND (td.created_at AT TIME ZONE 'Asia/Seoul')::date <= $2
      AND td.created_at <= $3
"""

# 1차 소스(kis_stock_basic_info) + 대체 소스(signal_feature_snapshots 파생)
# 종가 시계열. 대체 소스는 1차 소스가 없는 (instrument, trade_date)에만
# 채택한다(NOT EXISTS). as_of 이후 시점의 가격은 조회하지 않는다 —
# 재현성(같은 as-of면 같은 결과)과 look-ahead 방지를 함께 만족한다.
CLOSE_SQL = """
    WITH primary_close AS (
        SELECT DISTINCT
            instrument_id,
            to_date(raw_payload_json ->> 'clpr_chng_dt', 'YYYYMMDD') AS trade_date,
            (raw_payload_json ->> 'thdt_clpr')::numeric AS close_price,
            'kis_stock_basic_info' AS price_source
        FROM trading.instrument_status_snapshots
        WHERE source_type = 'kis_stock_basic_info'
          AND raw_payload_json ->> 'clpr_chng_dt' IS NOT NULL
          AND raw_payload_json ->> 'clpr_chng_dt' <> ''
          AND to_date(raw_payload_json ->> 'clpr_chng_dt', 'YYYYMMDD') <= $1
    ),
    fallback_close AS (
        SELECT
            instrument_id,
            (snapshot_at AT TIME ZONE 'Asia/Seoul')::date AS trade_date,
            (sma_20 * (1 + price_vs_sma_20_pct / 100.0)) AS close_price,
            'signal_feature_snapshots_derived' AS price_source
        FROM trading.signal_feature_snapshots
        WHERE timeframe = '1d'
          AND sma_20 IS NOT NULL
          AND price_vs_sma_20_pct IS NOT NULL
          AND (snapshot_at AT TIME ZONE 'Asia/Seoul')::date <= $1
    )
    SELECT instrument_id, trade_date, close_price, price_source FROM primary_close
    UNION ALL
    SELECT f.instrument_id, f.trade_date, f.close_price, f.price_source
    FROM fallback_close f
    WHERE NOT EXISTS (
        SELECT 1 FROM primary_close p
        WHERE p.instrument_id = f.instrument_id AND p.trade_date = f.trade_date
    )
"""


@dataclass
class DedupedUnit:
    """(symbol, KST 거래일) 단위로 압축된 독립 분석 단위."""

    instrument_id: str
    symbol: str
    kst_date: date
    final_status: str  # matched | downgraded | diverged | mixed_tie
    dominant_status: str
    dominant_n: int
    total_n: int
    contamination_rate: float
    risk_tone: str | None
    regime_label: str | None
    source_type: str | None
    policy_git_sha: str | None


def classify_and_dedupe(rows: Sequence[dict[str, Any]]) -> list[DedupedUnit]:
    """원시 buy-intent cycle 행을 (symbol, KST 거래일) 단위로 dedupe한다.

    같은 날 여러 cycle이 서로 다른 ``alignment_status``를 보일 수 있다
    (§22.3 표준안). 그날 가장 많이 등장한 라벨을 대표로 채택하고, 정확히
    동률이면 ``mixed_tie``로 표시해 어느 쪽 라벨도 임의로 강제하지 않는다.
    층화 변수(``risk_tone``/``regime_label``/``source_type``/
    ``policy_git_sha``)는 그날의 대표 라벨과 같은 cycle에서 가져온 값을
    쓴다(가장 이른 ``created_at``의 cycle을 대표로 채택 — 구조적 필드라
    하루 안에서 거의 항상 동일하다).
    """
    grouped: dict[tuple[str, date], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        grouped[(r["instrument_id"], r["kst_date"])].append(r)

    units: list[DedupedUnit] = []
    for (instrument_id, kst_date), day_rows in grouped.items():
        counts = Counter(r["alignment_status"] for r in day_rows)
        total_n = sum(counts.values())
        max_n = max(counts.values())
        top_statuses = [status for status, n in counts.items() if n == max_n]
        is_tie = len(top_statuses) > 1
        dominant_status = sorted(top_statuses)[0]
        final_status = "mixed_tie" if is_tie else dominant_status
        contamination_rate = round(1.0 - (max_n / total_n), 4) if total_n else 0.0

        repr_row = min(day_rows, key=lambda r: r["created_at"])
        units.append(
            DedupedUnit(
                instrument_id=instrument_id,
                symbol=repr_row["symbol"],
                kst_date=kst_date,
                final_status=final_status,
                dominant_status=dominant_status,
                dominant_n=max_n,
                total_n=total_n,
                contamination_rate=contamination_rate,
                risk_tone=repr_row.get("risk_tone"),
                regime_label=repr_row.get("regime_label"),
                source_type=repr_row.get("source_type"),
                policy_git_sha=repr_row.get("policy_git_sha"),
            )
        )
    return units


@dataclass
class CloseBar:
    trade_date: date
    close_price: float
    price_source: str


def build_close_index(
    close_rows: Sequence[dict[str, Any]],
) -> dict[str, list[CloseBar]]:
    """instrument_id별로 거래일 오름차순 정렬된 종가 리스트를 만든다.

    이 리스트에서의 "위치"가 곧 "실제 거래일 순서"다 — 달력일이 아니라
    가격 소스에 실제로 존재하는 거래일만 카운트하므로 주말/휴장일이
    자동으로 skip된다.
    """
    by_instrument: dict[str, list[CloseBar]] = defaultdict(list)
    for r in close_rows:
        by_instrument[r["instrument_id"]].append(
            CloseBar(
                trade_date=r["trade_date"],
                close_price=float(r["close_price"]),
                price_source=r["price_source"],
            )
        )
    for bars in by_instrument.values():
        bars.sort(key=lambda b: b.trade_date)
    return dict(by_instrument)


@dataclass
class ForwardReturnResult:
    horizon: int
    decision_close: float | None
    decision_close_source: str | None
    target_close: float | None
    target_close_source: str | None
    target_trade_date: str | None
    return_pct: float | None
    exclusion_reason: str | None  # None | price_source_missing | horizon_not_arrived


def compute_forward_return(
    close_index: dict[str, list[CloseBar]],
    instrument_id: str,
    decision_date: date,
    horizon: int,
) -> ForwardReturnResult:
    """종목별 실제 거래일 순서로 T+N forward return을 계산한다.

    결정일 자체의 종가가 없으면 ``price_source_missing``, 결정일 종가는
    있지만 그로부터 ``horizon``번째 거래일 바가 아직 쌓이지 않았으면
    ``horizon_not_arrived``로 구분한다 — 둘 다 수익률을 0/NULL로 채우지
    않고 명시적 제외 사유로만 남긴다.
    """
    bars = close_index.get(instrument_id, [])
    decision_idx: int | None = None
    for i, bar in enumerate(bars):
        if bar.trade_date == decision_date:
            decision_idx = i
            break

    if decision_idx is None:
        return ForwardReturnResult(
            horizon=horizon,
            decision_close=None,
            decision_close_source=None,
            target_close=None,
            target_close_source=None,
            target_trade_date=None,
            return_pct=None,
            exclusion_reason="price_source_missing",
        )

    decision_bar = bars[decision_idx]
    target_idx = decision_idx + horizon
    if target_idx >= len(bars):
        return ForwardReturnResult(
            horizon=horizon,
            decision_close=decision_bar.close_price,
            decision_close_source=decision_bar.price_source,
            target_close=None,
            target_close_source=None,
            target_trade_date=None,
            return_pct=None,
            exclusion_reason="horizon_not_arrived",
        )

    target_bar = bars[target_idx]
    return_pct = round(
        (target_bar.close_price / decision_bar.close_price - 1.0) * 100.0, 4
    )
    return ForwardReturnResult(
        horizon=horizon,
        decision_close=decision_bar.close_price,
        decision_close_source=decision_bar.price_source,
        target_close=target_bar.close_price,
        target_close_source=target_bar.price_source,
        target_trade_date=target_bar.trade_date.isoformat(),
        return_pct=return_pct,
        exclusion_reason=None,
    )


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def summarize_horizon_group(
    units: list[DedupedUnit],
    results_by_unit: dict[tuple[str, date], dict[int, ForwardReturnResult]],
    final_status: str,
    horizon: int,
) -> dict[str, Any]:
    """한 (final_status, horizon) 조합에 대한 통계 요약을 만든다."""
    group_units = [u for u in units if u.final_status == final_status]
    returns: list[float] = []
    symbols: set[str] = set()
    price_source_missing = 0
    horizon_not_arrived = 0
    risk_tone_dist: Counter[str] = Counter()
    regime_label_dist: Counter[str] = Counter()
    source_type_dist: Counter[str] = Counter()
    policy_sha_dist: Counter[str] = Counter()
    symbol_counter: Counter[str] = Counter()

    for u in group_units:
        key = (u.instrument_id, u.kst_date)
        r = results_by_unit.get(key, {}).get(horizon)
        symbol_counter[u.symbol] += 1
        risk_tone_dist[u.risk_tone or "unknown"] += 1
        regime_label_dist[u.regime_label or "unknown"] += 1
        source_type_dist[u.source_type or "unknown"] += 1
        policy_sha_dist[
            "unknown_pre_fingerprint" if not u.policy_git_sha else u.policy_git_sha[:12]
        ] += 1
        if r is None:
            continue
        if r.exclusion_reason == "price_source_missing":
            price_source_missing += 1
        elif r.exclusion_reason == "horizon_not_arrived":
            horizon_not_arrived += 1
        elif r.return_pct is not None:
            returns.append(r.return_pct)
            symbols.add(u.symbol)

    n = len(returns)
    positive_rate = round(100.0 * sum(1 for x in returns if x > 0) / n, 1) if n else None
    return {
        "final_status": final_status,
        "horizon": horizon,
        "unit_count_in_group": len(group_units),
        "n_with_return": n,
        "distinct_symbol_count": len(symbols),
        "mean_return_pct": round(sum(returns) / n, 4) if n else None,
        "median_return_pct": (
            round(_median(returns), 4) if returns else None
        ),
        "positive_rate_pct": positive_rate,
        "min_return_pct": round(min(returns), 4) if returns else None,
        "max_return_pct": round(max(returns), 4) if returns else None,
        "excluded_price_source_missing": price_source_missing,
        "excluded_horizon_not_arrived": horizon_not_arrived,
        "risk_tone_distribution": dict(risk_tone_dist),
        "regime_label_distribution": dict(regime_label_dist),
        "source_type_distribution": dict(source_type_dist),
        "policy_git_sha_distribution": dict(policy_sha_dist),
        "top_repeated_symbols": symbol_counter.most_common(10),
        "statistical_note": (
            "표본이 작아(n<40) 신뢰구간/유의성 검정을 적용하지 않았다 — "
            "방향성 관찰로만 해석할 것"
            if n < 40
            else "표본 규모가 커도 이 스크립트는 신뢰구간을 자동 계산하지 않는다 — "
            "필요하면 별도 통계 검정을 추가 적용할 것"
        ),
    }


def _resolve_script_git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        sha = out.stdout.strip()
        return sha or None
    except Exception:
        return None


async def fetch_population(
    conn: Any, start_date: date, end_date: date, as_of_ts: datetime
) -> list[dict[str, Any]]:
    rows = await conn.fetch(BUY_RAW_SQL, start_date, end_date, as_of_ts)
    return [dict(r) for r in rows]


async def fetch_close_series(conn: Any, as_of_date: date) -> list[dict[str, Any]]:
    rows = await conn.fetch(CLOSE_SQL, as_of_date)
    return [dict(r) for r in rows]


def run_analysis(
    raw_rows: list[dict[str, Any]],
    close_rows: list[dict[str, Any]],
    horizons: list[int],
) -> dict[str, Any]:
    """DB에서 가져온 두 결과 집합만으로 전체 분석을 수행하는 순수 함수.

    DB I/O와 분리해 단위 테스트가 실제 커넥션 없이 이 함수만으로 dedupe/
    forward-return/집계 로직 전체를 검증할 수 있게 한다.
    """
    units = classify_and_dedupe(raw_rows)
    close_index = build_close_index(close_rows)

    exclusion_counts: Counter[str] = Counter()
    for status in KNOWN_NON_PRIMARY_STATUSES:
        exclusion_counts[status] = 0  # 항목이 0건이어도 명시적으로 보고
    for u in units:
        if u.final_status == "mixed_tie":
            exclusion_counts["mixed_tie"] += 1
        elif u.final_status not in PRIMARY_STATUSES:
            exclusion_counts[u.final_status] += 1

    results_by_unit: dict[tuple[str, date], dict[int, ForwardReturnResult]] = {}
    for u in units:
        if u.final_status not in PRIMARY_STATUSES:
            continue
        key = (u.instrument_id, u.kst_date)
        results_by_unit[key] = {
            h: compute_forward_return(close_index, u.instrument_id, u.kst_date, h)
            for h in horizons
        }

    price_source_usage: Counter[str] = Counter()
    for per_horizon in results_by_unit.values():
        for r in per_horizon.values():
            if r.decision_close_source:
                price_source_usage[r.decision_close_source] += 1
            if r.target_close_source:
                price_source_usage[r.target_close_source] += 1

    horizon_summaries = [
        summarize_horizon_group(units, results_by_unit, status, h)
        for status in PRIMARY_STATUSES
        for h in horizons
    ]

    unit_records = [
        {
            "symbol": u.symbol,
            "kst_date": u.kst_date.isoformat(),
            "final_status": u.final_status,
            "dominant_status": u.dominant_status,
            "dominant_n": u.dominant_n,
            "total_n": u.total_n,
            "contamination_rate": u.contamination_rate,
            "risk_tone": u.risk_tone,
            "regime_label": u.regime_label,
            "source_type": u.source_type,
            "policy_git_sha_bucket": (
                "unknown_pre_fingerprint"
                if not u.policy_git_sha
                else u.policy_git_sha[:12]
            ),
            "forward_returns": (
                {
                    str(h): asdict(r)
                    for h, r in results_by_unit.get(
                        (u.instrument_id, u.kst_date), {}
                    ).items()
                }
                if u.final_status in PRIMARY_STATUSES
                else {}
            ),
        }
        for u in sorted(units, key=lambda x: (x.symbol, x.kst_date))
    ]

    return {
        "raw_row_count": len(raw_rows),
        "deduped_unit_count": len(units),
        "primary_population_unit_count": sum(
            1 for u in units if u.final_status in PRIMARY_STATUSES
        ),
        "exclusion_counts": dict(exclusion_counts),
        "price_source_usage_counts": dict(price_source_usage),
        "horizon_summaries": horizon_summaries,
        "units": unit_records,
    }


async def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "SPPV-3 축 3(downstream 분리 순수 deterministic 성과) 재현 분석 "
            "도구(read-only) — matched/downgraded의 가상 forward return 비교"
        )
    )
    parser.add_argument("--start-date", required=True, help="population 시작일(YYYY-MM-DD, KST)")
    parser.add_argument("--end-date", required=True, help="population 종료일(YYYY-MM-DD, KST)")
    parser.add_argument(
        "--as-of-date",
        default=None,
        help=(
            "평가 기준일(YYYY-MM-DD, KST). 이 날짜 이후의 가격/결정 데이터는 "
            "조회하지 않는다(재현성 + look-ahead 방지). 생략하면 실행 시각의 "
            "KST 날짜를 쓴다."
        ),
    )
    parser.add_argument(
        "--horizons",
        default="1,5,20",
        help="쉼표로 구분한 forward horizon(거래일 수, 기본 1,5,20)",
    )
    parser.add_argument("--output-json", default=None, help="결과 JSON 저장 경로(선택)")
    args = parser.parse_args(argv)

    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    end_date = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    if args.as_of_date:
        as_of_date = datetime.strptime(args.as_of_date, "%Y-%m-%d").date()
    else:
        as_of_date = datetime.now(tz=KST).date()
    as_of_ts = datetime.combine(as_of_date, datetime.max.time(), tzinfo=KST)
    horizons = [int(h.strip()) for h in args.horizons.split(",") if h.strip()]

    query_executed_at_kst = datetime.now(tz=KST).isoformat()

    await create_pool()
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction(readonly=True):
                raw_rows = await fetch_population(conn, start_date, end_date, as_of_ts)
                close_rows = await fetch_close_series(conn, as_of_date)
    finally:
        await close_pool()

    analysis = run_analysis(raw_rows, close_rows, horizons)

    result = {
        "reproducibility_metadata": {
            "query_executed_at_kst": query_executed_at_kst,
            "input_date_range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
            "as_of_date": as_of_date.isoformat(),
            "horizons": horizons,
            "dedupe_contract_version": DEDUPE_CONTRACT_VERSION,
            "script_git_sha": _resolve_script_git_sha(),
            "look_ahead_caveat": (
                "가상 진입가는 결정일 KST 종가를 근사로 쓴다 — 결정이 그날 "
                "장중에 이뤄졌다면 결정 이후의 장중 변동이 일부 포함되는 "
                "약한 look-ahead가 있다(장중 tick 데이터 부재로 제거 불가)."
            ),
            "historical_snapshot_note": (
                "2026-08-24 11:51 KST에 수행된 축 3 최초 실측 보고"
                "(post_sppv3_policy_evaluation_design_2026-08-20.md §16.5)는 "
                "이 도구 도입 이전의 ad hoc 조회 결과이며 historical snapshot "
                "으로만 취급한다 — 이 스크립트의 새 실행 결과와 그대로 병합하지 "
                "않는다. 표본 누적/as-of 시점/규약 미세 차이로 수치가 달라질 수 "
                "있다."
            ),
            "policy_conclusion_caveat": (
                "이 스크립트의 출력은 관측 지표다. 표본이 §16.6 기준(risk_on "
                "downgraded 15~20건 이상, 국면 다양성 1건 이상 등)을 충족하기 "
                "전까지 이 결과만으로 정책/threshold/gate를 변경하지 않는다."
            ),
        },
        **analysis,
    }

    print("=== 재현성 메타데이터 ===")
    print(json.dumps(result["reproducibility_metadata"], ensure_ascii=False, indent=2))
    print(
        f"\n[population] 원시 행 {result['raw_row_count']}건 -> "
        f"dedupe 후 {result['deduped_unit_count']}개 단위 "
        f"(주 population {result['primary_population_unit_count']}개)"
    )
    print("\n=== 제외 건수(사유별) ===")
    print(json.dumps(result["exclusion_counts"], ensure_ascii=False, indent=2))
    print("\n=== 가격 소스 사용 건수 ===")
    print(json.dumps(result["price_source_usage_counts"], ensure_ascii=False, indent=2))
    print("\n=== horizon별 요약 ===")
    for s in result["horizon_summaries"]:
        print(
            f"- {s['final_status']} T+{s['horizon']}: n={s['n_with_return']} "
            f"(symbols={s['distinct_symbol_count']}), "
            f"mean={s['mean_return_pct']}%, median={s['median_return_pct']}%, "
            f"positive_rate={s['positive_rate_pct']}%, "
            f"excluded(price_missing={s['excluded_price_source_missing']}, "
            f"horizon_not_arrived={s['excluded_horizon_not_arrived']})"
        )

    if args.output_json:
        os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n[출력] 결과 JSON 저장: {args.output_json}")

    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
