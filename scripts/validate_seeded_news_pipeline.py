#!/usr/bin/env python3
"""Validate KIS disclosure → NAVER news candidate pipeline with sample symbols.

Phase P-2f: 샘플 종목(005930, 000660, 035420, 005380)에 대해
seed 수집 → query 생성 → NAVER 검색 → hard gate → dedupe → score 파이프라인을
실행하고 각 단계별 메트릭을 출력한다.

NAVER API key가 없으면 graceful skip (WARNING 로그만 확인).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

sys.path.insert(0, "src")

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(name)s: %(message)s",
)


async def main() -> None:
    from agent_trading.config.settings import AppSettings
    from agent_trading.services.disclosure_seed_service import (
        LiveDisclosureSeedService,
    )
    from agent_trading.services.seeded_news_service import (
        SeededNewsCandidateService,
    )
    from agent_trading.runtime.bootstrap import (
        _build_live_disclosure_client,
        _build_naver_search_adapter,
    )

    # ★ SEEDED_NEWS_ENABLED=0 이면 NAVER 관련 경로를 모두 skip
    if os.environ.get("SEEDED_NEWS_ENABLED", "1") == "0":
        print("⚠️  SEEDED_NEWS_ENABLED=0 — seeded news pipeline disabled, SKIP")
        return

    settings = AppSettings()

    # --- 1. Build disclosure seed service ---
    disclosure_client = _build_live_disclosure_client(settings)
    seed_service = LiveDisclosureSeedService(disclosure_client)

    # --- 2. Build NAVER adapter ---
    naver_adapter = _build_naver_search_adapter(settings)
    if naver_adapter is None:
        print("\n⚠️  NAVER API key not configured — SKIP (graceful fallback)\n")
        print("=" * 60)
        print("샘플 검증 결과: SKIP (credential 미설정)")
        print("  NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 미설정으로")
        print("  NaverNewsSearchAdapter가 None 반환")
        print("=" * 60)
        return

    # --- 3. Build candidate service ---
    candidate_service = SeededNewsCandidateService(
        search_adapter=naver_adapter,
    )

    symbols = ["005930", "000660", "035420", "005380"]

    # --- 4. Fetch seeds from KIS ---
    print(f"\n{'='*90}")
    print(f"{'Step 1: KIS Disclosure Seeds 수집':^90}")
    print(f"{'='*90}")
    seeds = await seed_service.fetch_disclosure_titles(symbols)
    if not seeds:
        print("⚠️  No seeds returned from KIS disclosure API "
              "(credentials may not be configured)")
        # 그래도 pipeline 동작 확인을 위해 mock seed를 사용하지는 않음
        print("   → SKIP (실제 KIS live credential 필요)")
        print()
        print("=" * 60)
        print("샘플 검증 결과: SKIP (KIS live credential 미설정)")
        print("  KIS_LIVE_INFO_APP_KEY / KIS_LIVE_INFO_APP_SECRET 미설정으로")
        print("  LiveDisclosureSeedService가 [] 반환")
        print("=" * 60)
        return

    print(f"\n✅ {len(seeds)} seeds fetched")
    for s in seeds:
        hl = (s.headline or "")[:60]
        print(f"   {s.symbol} ({s.company_name}): {hl}...")

    # --- 5. Run pipeline ---
    print(f"\n{'='*90}")
    print(f"{'Step 2: Pipeline 실행 (query→search→gate→dedupe→score→global Top-N)':^90}")
    print(f"{'='*90}")

    results, metrics = await candidate_service.process_seeds(seeds)

    # --- 6. Print per-symbol breakdown with per-stage counts ---
    print(f"\n{'='*90}")
    print(f"{'Step 3: 종목별 Pipeline 결과 (단계별 Count)':^90}")
    print(f"{'='*90}")

    print(f"\n{'Symbol':<10} {'Seeds':<7} {'Raw':<8} {'HardGate':<9} "
          f"{'Deduped':<9} {'Threshold':<10} {'Top-N(global)':<14} {'Top Score':<10}")
    print(f"{'-'*85}")
    total_seeds = len(seeds)
    total_raw = 0
    total_gate = 0
    total_deduped = 0
    total_threshold = 0
    total_global = 0

    # Group seeds by symbol
    from collections import defaultdict
    seeds_by_symbol: dict[str, dict] = defaultdict(lambda: {
        "seeds": 0, "company": "", "top_score": 0.0,
    })
    for s in seeds:
        seeds_by_symbol[s.symbol]["seeds"] += 1
        seeds_by_symbol[s.symbol]["company"] = s.company_name or "-"

    for sym, info in seeds_by_symbol.items():
        pm = metrics.per_symbol.get(sym, {})
        raw = pm.get("raw", 0)
        gate_pass = pm.get("hard_gate_passed", 0)
        deduped = pm.get("deduped", 0)
        scored_before = pm.get("scored_before_threshold", 0)
        dropped = pm.get("dropped_low_confidence", 0)
        threshold = scored_before - dropped
        kept = pm.get("kept", 0)  # Already updated by global Top-N
        candidates_for_sym = [c for c in results if c.symbol == sym]
        top_score = max((c.confidence_score for c in candidates_for_sym), default=0.0)

        total_raw += raw
        total_gate += gate_pass
        total_deduped += deduped
        total_threshold += threshold
        total_global += kept

        print(f"{sym:<10} {info['seeds']:<7} {raw:<8} {gate_pass:<9} "
              f"{deduped:<9} {threshold:<10} {kept:<14} {top_score:<10.1f}")

    print(f"{'─'*85}")
    print(f"{'Total':<10} {total_seeds:<7} {total_raw:<8} {total_gate:<9} "
          f"{total_deduped:<9} {total_threshold:<10} {total_global:<14} {'':<10}")

    # --- 7. Print final candidates (after global Top-N) ---
    if results:
        print(f"\n{'='*90}")
        print(f"{'Step 4: 최종 후보 리스트 (Top-N Global 적용 후)':^90}")
        print(f"{'='*90}")
        for i, c in enumerate(results, 1):
            title = (c.related_news_title or "")[:80]
            print(f"\n  #{i} [{c.symbol}] ({c.company_name})")
            print(f"      Score:    {c.confidence_score:.1f}/100")
            print(f"      Seed:     {(c.seed_headline or '')[:60]}...")
            print(f"      Title:    {title}")
            print(f"      Link:     {c.link}")

        # --- 8. EI 전달 후보 수 ---
        print(f"\n{'='*90}")
        print(f"{'Step 5: EI 전달 후보':^90}")
        print(f"{'='*90}")
        print(f"\n✅ Total candidates delivered to EI: {len(results)} "
              f"(max {metrics.kept_count} per symbol globally)")
    else:
        print("\n⚠️  No candidates produced (all stages empty)")

    # --- 8. Cleanup ---
    if disclosure_client:
        await disclosure_client.close()
    await candidate_service.close()


if __name__ == "__main__":
    asyncio.run(main())
