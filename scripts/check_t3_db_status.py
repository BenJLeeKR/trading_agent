#!/usr/bin/env python3
"""T3 적재 현황 DB 직접 확인 스크립트.

사용법:
    python scripts/check_t3_db_status.py

환경변수 (선택):
    DATABASE_DSN or DATABASE_HOST/USER/PASSWORD/NAME
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_trading.db.connection import create_pool, get_pool, close_pool


KST = timezone(timedelta(hours=9))


async def main() -> None:
    await create_pool()
    pool = await get_pool()

    now_kst = datetime.now(KST)
    yesterday_kst = now_kst - timedelta(hours=24)
    two_days_ago_kst = now_kst - timedelta(hours=48)

    async with pool.acquire() as conn:
        # 1. external_events 전체 현황
        print("=" * 70)
        print(f"[1] external_events 테이블 전체 현황 (as of {now_kst.strftime('%Y-%m-%d %H:%M:%S')} KST)")
        print("=" * 70)

        total = await conn.fetchval("SELECT COUNT(*) FROM trading.external_events")
        print(f"  전체 레코드 수: {total}")

        # 2. source_reliability_tier 분포
        print(f"\n{'=' * 70}")
        print("[2] source_reliability_tier 분포")
        print("=" * 70)
        rows = await conn.fetch("""
            SELECT source_reliability_tier, COUNT(*) as cnt
            FROM trading.external_events
            GROUP BY source_reliability_tier
            ORDER BY cnt DESC
        """)
        for r in rows:
            print(f"  {r['source_reliability_tier']:>5}: {r['cnt']}")

        # 3. T3 events 상세
        print(f"\n{'=' * 70}")
        print("[3] T3 events (source_reliability_tier = 'T3') 상세")
        print("=" * 70)

        t3_total = await conn.fetchval(
            "SELECT COUNT(*) FROM trading.external_events WHERE source_reliability_tier = 'T3'"
        )
        print(f"  T3 전체: {t3_total}")

        t3_24h = await conn.fetchval(
            "SELECT COUNT(*) FROM trading.external_events "
            "WHERE source_reliability_tier = 'T3' "
            "AND COALESCE(created_at, ingested_at) >= $1",
            yesterday_kst,
        )
        print(f"  T3 (최근 24시간): {t3_24h}")

        t3_48h = await conn.fetchval(
            "SELECT COUNT(*) FROM trading.external_events "
            "WHERE source_reliability_tier = 'T3' "
            "AND COALESCE(created_at, ingested_at) >= $1",
            two_days_ago_kst,
        )
        print(f"  T3 (최근 48시간): {t3_48h}")

        # 4. T3 event_type 분포
        print(f"\n{'=' * 70}")
        print("[4] T3 event_type 분포")
        print("=" * 70)
        rows = await conn.fetch("""
            SELECT event_type, COUNT(*) as cnt
            FROM trading.external_events
            WHERE source_reliability_tier = 'T3'
            GROUP BY event_type
            ORDER BY cnt DESC
        """)
        for r in rows:
            print(f"  {r['event_type']:>30}: {r['cnt']}")

        # 5. T3 source_name 분포
        print(f"\n{'=' * 70}")
        print("[5] T3 source_name 분포")
        print("=" * 70)
        rows = await conn.fetch("""
            SELECT source_name, COUNT(*) as cnt
            FROM trading.external_events
            WHERE source_reliability_tier = 'T3'
            GROUP BY source_name
            ORDER BY cnt DESC
        """)
        for r in rows:
            print(f"  {r['source_name']:>30}: {r['cnt']}")

        # 6. T3 symbol 분포 (TOP 20)
        print(f"\n{'=' * 70}")
        print("[6] T3 symbol 분포 (TOP 20)")
        print("=" * 70)
        rows = await conn.fetch("""
            SELECT symbol, COUNT(*) as cnt
            FROM trading.external_events
            WHERE source_reliability_tier = 'T3'
            GROUP BY symbol
            ORDER BY cnt DESC
            LIMIT 20
        """)
        for r in rows:
            print(f"  {r['symbol']:>10}: {r['cnt']}")

        # 7. T3 created_at 시간 분포 (시간별)
        print(f"\n{'=' * 70}")
        print("[7] T3 created_at 시간별 분포 (최근 48시간)")
        print("=" * 70)
        rows = await conn.fetch("""
            SELECT
                date_trunc('hour', COALESCE(created_at, ingested_at) AT TIME ZONE 'Asia/Seoul') as hour_kst,
                COUNT(*) as cnt
            FROM trading.external_events
            WHERE source_reliability_tier = 'T3'
              AND COALESCE(created_at, ingested_at) >= $1
            GROUP BY hour_kst
            ORDER BY hour_kst
        """, two_days_ago_kst)
        for r in rows:
            print(f"  {r['hour_kst'].strftime('%Y-%m-%d %H:00'):>20}: {r['cnt']}")

        # 8. T3 dedup_key_hash 중복 현황
        print(f"\n{'=' * 70}")
        print("[8] T3 dedup_key_hash 중복 현황")
        print("=" * 70)
        dup_count = await conn.fetchval("""
            SELECT COUNT(*) FROM (
                SELECT dedup_key_hash
                FROM trading.external_events
                WHERE source_reliability_tier = 'T3'
                  AND dedup_key_hash IS NOT NULL
                GROUP BY dedup_key_hash
                HAVING COUNT(*) > 1
            ) dup
        """)
        print(f"  중복 dedup_key_hash 수: {dup_count}")

        # 9. T3 events 중 seeded_news 여부
        print(f"\n{'=' * 70}")
        print("[9] T3 events 중 seeded_news (event_type = 'seeded_news')")
        print("=" * 70)
        seeded_news_count = await conn.fetchval("""
            SELECT COUNT(*) FROM trading.external_events
            WHERE source_reliability_tier = 'T3'
              AND event_type = 'seeded_news'
        """)
        print(f"  seeded_news T3 events: {seeded_news_count}")

        seeded_news_24h = await conn.fetchval("""
            SELECT COUNT(*) FROM trading.external_events
            WHERE source_reliability_tier = 'T3'
              AND event_type = 'seeded_news'
              AND COALESCE(created_at, ingested_at) >= $1
        """, yesterday_kst)
        print(f"  seeded_news T3 (최근 24시간): {seeded_news_24h}")

        # 10. T3 events 샘플 (최근 10건)
        print(f"\n{'=' * 70}")
        print("[10] T3 events 샘플 (최근 10건)")
        print("=" * 70)
        rows = await conn.fetch("""
            SELECT event_id, symbol, event_type, source_name,
                   headline, created_at AT TIME ZONE 'Asia/Seoul' as created_at_kst
            FROM trading.external_events
            WHERE source_reliability_tier = 'T3'
            ORDER BY COALESCE(created_at, ingested_at) DESC
            LIMIT 10
        """)
        for r in rows:
            print(f"  {r['event_id']}")
            print(f"    symbol={r['symbol']}, event_type={r['event_type']}, source={r['source_name']}")
            print(f"    headline={r['headline']}")
            print(f"    created_at={r['created_at_kst'].strftime('%Y-%m-%d %H:%M:%S') if r['created_at_kst'] else 'N/A'}")

        # 11. T3 pipeline 관련 trade_decisions 확인
        print(f"\n{'=' * 70}")
        print("[11] trade_decisions T3 관련 현황")
        print("=" * 70)
        t3_skip = await conn.fetchval("""
            SELECT COUNT(*) FROM trading.trade_decisions
            WHERE source_type = 'T3'
              AND decision = 'skip'
              AND created_at >= $1
        """, yesterday_kst)
        print(f"  T3 skip (최근 24시간): {t3_skip}")

        t3_trigger = await conn.fetchval("""
            SELECT COUNT(*) FROM trading.trade_decisions
            WHERE source_type = 'T3'
              AND decision != 'skip'
              AND created_at >= $1
        """, yesterday_kst)
        print(f"  T3 non-skip (최근 24시간): {t3_trigger}")

        t3_total_decisions = await conn.fetchval("""
            SELECT COUNT(*) FROM trading.trade_decisions
            WHERE source_type = 'T3'
              AND created_at >= $1
        """, yesterday_kst)
        print(f"  T3 total decisions (최근 24시간): {t3_total_decisions}")

        # 12. T3 events가 없는 symbol 목록 (유니버스 symbol 중)
        print(f"\n{'=' * 70}")
        print("[12] T3 events가 전혀 없는 symbol (유니버스 기준)")
        print("=" * 70)
        rows = await conn.fetch("""
            SELECT DISTINCT i.symbol
            FROM trading.instruments i
            WHERE NOT EXISTS (
                SELECT 1 FROM trading.external_events e
                WHERE e.symbol = i.symbol
                  AND e.source_reliability_tier = 'T3'
            )
            ORDER BY i.symbol
        """)
        if rows:
            symbols = [r['symbol'] for r in rows]
            print(f"  T3 events 없는 symbol ({len(symbols)}개): {', '.join(symbols)}")
        else:
            print("  모든 instrument에 T3 events 존재")

    await close_pool()
    print(f"\n{'=' * 70}")
    print("DB 확인 완료")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
