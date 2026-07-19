#!/usr/bin/env python3
"""보유기간/Churn 제어가 R3b BUY 빈도를 얼마나 깎는지 정량 검증
(SPPV-2.75). 운영 함수(`_build_entry_score`, `classify_market_regime`)
를 그대로 재사용하고, 실제 운영 DB의 `guardrail_evaluations`
(pre_ai_gate_v1)/`signal_feature_snapshots`/`trade_decisions`를
read-only로 조회한다. 신규 KIS 호출 없음(전부 이미 저장된 DB 데이터).

**표본 범위에 대한 명시적 결정**: 이 세션의 요청은 "최근 12개월 /
3년 pooled 둘 다 가능하면"이었으나, 보유기간/Churn guard는 실제
운영 중 발생한 **진짜 거래 이력**(symbol_trade_states, 최근 BUY/SELL
시각)에 의존하는 stateful guard다. 이 real state는 paper 운영이
실제로 시작된 시점(2026-05-13, `trade_decisions` 최초 레코드) 이후
에만 존재하며, 3년치 합성 상태를 만들 수 없다(만들면 실제로 발생한
guard 판정이 아니라 가상의 재구성이 된다). 따라서 이 스크립트는
**실제 운영 2개월 창(2026-05-13~2026-07-16)** 전체를 그대로 쓴다 —
이는 축소가 아니라, guard의 정의 자체가 요구하는 유일하게 유효한
표본이다.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter, defaultdict
from datetime import date as _date

sys.path.insert(0, "scripts")
sys.path.insert(0, "src")


CHURN_RELATED_CODES = {
    "holding_profile_earliest_reentry_guard",
    "holding_profile_earliest_reduce_guard",
    "held_position_recent_risk_sell_cooldown",
    "held_position_recent_hold_no_change",
    "same_symbol_reentry_cooldown",
}


async def main() -> None:
    from agent_trading.db.connection import create_pool
    from agent_trading.db.transaction import transaction
    from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories
    from agent_trading.services.market_regime import classify_market_regime
    from agent_trading.services.deterministic_trigger_engine import _build_entry_score
    from agent_trading.services.strategy_selection import select_strategy

    await create_pool()

    async with transaction() as tx:
        conn = tx.connection

        # ── 표 A: 전체 pre_ai_gate_v1 차단 사유 분포 (원시 이벤트, 교집합 포함) ──
        raw_rows = await conn.fetch(
            "SELECT blocking_rule_codes, rule_results, created_at "
            "FROM guardrail_evaluations WHERE rule_set_version='pre_ai_gate_v1'"
        )
        print(f"[표 A] pre_ai_gate_v1 원시 이벤트 총 {len(raw_rows)}건 "
              f"(2026-05-13~2026-07-16 실제 운영 창)")
        code_counter: Counter[str] = Counter()
        combo_counter: Counter[tuple[str, ...]] = Counter()
        for r in raw_rows:
            codes = tuple(sorted(r["blocking_rule_codes"] or []))
            combo_counter[codes] += 1
            for c in codes:
                code_counter[c] += 1
        print("  개별 사유별 원시 이벤트 건수(중복 카운트 가능):")
        for code, cnt in code_counter.most_common():
            tag = "churn 관련" if code in CHURN_RELATED_CODES else "churn 무관(budget/유동성 등)"
            print(f"    {code}: {cnt}  [{tag}]")
        print("  조합(교집합) 분포:")
        for combo, cnt in combo_counter.most_common():
            print(f"    {combo}: {cnt}")

        # ── churn 관련 사유만 별도로, 5분 cycle 반복을 (symbol, date) 단위로 dedupe ──
        episodes: dict[str, set[tuple[str, str]]] = defaultdict(set)
        detail_rows: dict[str, list[dict]] = defaultdict(list)
        for r in raw_rows:
            codes = r["blocking_rule_codes"] or []
            rr = json.loads(r["rule_results"]) if isinstance(r["rule_results"], str) else r["rule_results"]
            sym = rr.get("symbol")
            date_str = r["created_at"].date().isoformat()
            for code in codes:
                if code in CHURN_RELATED_CODES:
                    episodes[code].add((sym, date_str))
                    detail_rows[code].append({"symbol": sym, "date": date_str, "created_at": r["created_at"]})

        print()
        print("[표 A-보정] churn 관련 사유별 distinct (symbol, date) episode 수:")
        for code, eps in episodes.items():
            print(f"  {code}: {len(eps)}건, distinct symbols={len({s for s, _ in eps})}")

        # ── 표 B: churn 관련 차단 episode의 entry_score 재계산 + forward return ──
        print()
        print("[표 B] churn 관련 차단 episode의 R3b entry_score 재계산(운영 함수 재사용)")
        all_results = []
        for code, eps in episodes.items():
            for sym, date_str in sorted(eps):
                instrument = await conn.fetchrow(
                    "SELECT instrument_id FROM instruments WHERE symbol=$1 LIMIT 1", sym
                )
                if instrument is None:
                    continue
                inst_id = instrument["instrument_id"]
                snap_row = await conn.fetchrow(
                    "SELECT * FROM signal_feature_snapshots WHERE instrument_id=$1 "
                    "AND timeframe='1d' AND snapshot_at::date <= $2::date "
                    "ORDER BY snapshot_at DESC LIMIT 1",
                    inst_id, _date.fromisoformat(date_str),
                )
                if snap_row is None:
                    continue
                from types import SimpleNamespace
                snap = SimpleNamespace(
                    overall_score=float(snap_row["overall_score"]) if snap_row["overall_score"] is not None else None,
                    fast_score=float(snap_row["fast_score"]) if snap_row["fast_score"] is not None else None,
                    slow_score=float(snap_row["slow_score"]) if snap_row["slow_score"] is not None else None,
                    return_1m_pct=float(snap_row["return_1m_pct"]) if snap_row["return_1m_pct"] is not None else None,
                    return_3m_pct=float(snap_row["return_3m_pct"]) if snap_row["return_3m_pct"] is not None else None,
                    price_vs_sma_20_pct=float(snap_row["price_vs_sma_20_pct"]) if snap_row["price_vs_sma_20_pct"] is not None else None,
                    price_vs_sma_60_pct=float(snap_row["price_vs_sma_60_pct"]) if snap_row["price_vs_sma_60_pct"] is not None else None,
                    volatility_20d_pct=float(snap_row["volatility_20d_pct"]) if snap_row["volatility_20d_pct"] is not None else None,
                    atr_14_pct=float(snap_row["atr_14_pct"]) if snap_row["atr_14_pct"] is not None else None,
                    volume_surge_ratio=float(snap_row["volume_surge_ratio"]) if snap_row["volume_surge_ratio"] is not None else None,
                    average_volume_20d=float(snap_row["average_volume_20d"]) if snap_row["average_volume_20d"] is not None else None,
                    average_turnover_20d=float(snap_row["average_turnover_20d"]) if snap_row["average_turnover_20d"] is not None else None,
                    turnover_surge_ratio=float(snap_row["turnover_surge_ratio"]) if snap_row["turnover_surge_ratio"] is not None else None,
                    rsi_14=float(snap_row["rsi_14"]) if snap_row["rsi_14"] is not None else None,
                    sma_5=float(snap_row["sma_5"]) if snap_row["sma_5"] is not None else None,
                    sma_20=float(snap_row["sma_20"]) if snap_row["sma_20"] is not None else None,
                    sma_60=float(snap_row["sma_60"]) if snap_row["sma_60"] is not None else None,
                    component_scores_json=None,
                )
                market_regime = classify_market_regime(snap)
                strategy_selection = select_strategy(market_regime=market_regime, source_type="core")
                reason_codes: list[str] = []
                entry_score = _build_entry_score(
                    overall=snap.overall_score, fast=snap.fast_score, slow=snap.slow_score,
                    signal_feature_snapshot=snap, market_regime=market_regime,
                    strategy_selection=strategy_selection, portfolio_allocation=None,
                    source_type="core", reason_codes=reason_codes,
                )
                # forward return (T+5): 같은 instrument의 이후 daily snapshot의
                # sma_5(근사 가격 proxy) 변화 대신, price_vs_sma_20_pct 계열이 아닌
                # 실제 종가가 없으므로 이후 overall_score 시계열이 아닌 원시 종가가
                # 필요 — bars 캐시가 없으므로 sma_5(5일 이동평균, 종가 근사)를
                # 종가 proxy로 사용해 근사 T+5 수익률을 계산한다(한계는 보고서에
                # 명시).
                fwd_row = await conn.fetchrow(
                    "SELECT sma_5 FROM signal_feature_snapshots WHERE instrument_id=$1 "
                    "AND timeframe='1d' AND snapshot_at::date > $2::date "
                    "ORDER BY snapshot_at ASC LIMIT 1 OFFSET 4",
                    inst_id, _date.fromisoformat(date_str),
                )
                fwd_ret = None
                if fwd_row is not None and fwd_row["sma_5"] is not None and snap.sma_5:
                    fwd_ret = float(fwd_row["sma_5"]) / float(snap.sma_5) - 1.0
                all_results.append({
                    "code": code, "symbol": sym, "date": date_str,
                    "entry_score": entry_score, "is_r3b_candidate": entry_score >= 0.65,
                    "fwd_5d_sma_proxy_return": fwd_ret,
                })

        for code in episodes:
            subset = [r for r in all_results if r["code"] == code]
            cand_subset = [r for r in subset if r["is_r3b_candidate"]]
            print(f"  [{code}] episode={len(subset)}, entry_score>=0.65(candidate)={len(cand_subset)}")
            scores = [r["entry_score"] for r in subset]
            if scores:
                print(f"    entry_score 분포: min={min(scores):.3f} max={max(scores):.3f} "
                      f"avg={sum(scores)/len(scores):.3f}")
            fwd = [r["fwd_5d_sma_proxy_return"] for r in cand_subset if r["fwd_5d_sma_proxy_return"] is not None]
            print(f"    candidate 중 T+5 근사 수익률 계산 가능 표본: {len(fwd)}/{len(cand_subset)}")
            if fwd:
                avg = sum(fwd) / len(fwd)
                pos = sum(1 for f in fwd if f > 0) / len(fwd)
                print(f"    T+5 근사 평균수익률={avg*100:.2f}% 양수비율={pos*100:.1f}%")

        # ── 표 C 참고: 실제 BUY 발생 건수(같은 창) ──
        buy_rows = await conn.fetchrow(
            "SELECT count(*) c FROM trade_decisions WHERE decision='BUY'"
        )
        print()
        print(f"[표 C 참고] 같은 창(2026-05-13~07-16) 실제 trade_decisions BUY 건수: {buy_rows['c']}")

        await tx.rollback()

    out = {"episodes": {code: len(eps) for code, eps in episodes.items()}, "detail": all_results}
    with open("tmp/churn_guard_r3b_impact_summary.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print("\n[산출물] tmp/churn_guard_r3b_impact_summary.json 저장")


if __name__ == "__main__":
    asyncio.run(main())
