#!/usr/bin/env python3
"""T3 재검증 - DB 재집계 스크립트 (v2)"""

import asyncio
import os
from datetime import datetime, timezone, timedelta

# .env 파일 직접 파싱
env_path = '/workspace/agent_trading/.env'
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, val = line.split('=', 1)
            os.environ[key.strip()] = val.strip()

# DB_DSN 구성
dsn = f"postgresql://{os.environ['DATABASE_USER']}:{os.environ['DATABASE_PASSWORD']}@{os.environ['DATABASE_HOST']}:{os.environ['DATABASE_PORT']}/{os.environ['DATABASE_NAME']}"
os.environ['DB_DSN'] = dsn

from agent_trading.db.connection import create_pool

async def check():
    pool = await create_pool()
    
    now = datetime.now(timezone.utc)
    print(f"=== 현재 시각 (UTC): {now} ===")
    print(f"=== 현재 시각 (KST): {now + timedelta(hours=9)} ===")
    print()
    
    # ============================================================
    # 1. external_events 일별 분포 (최근 7일)
    # ============================================================
    print("=" * 60)
    print("1. external_events 일별 분포 (최근 7일)")
    print("=" * 60)
    rows = await pool.fetch("""
        SELECT 
            DATE(created_at AT TIME ZONE 'Asia/Seoul') as kst_date,
            source_reliability_tier,
            COUNT(*) as cnt
        FROM trading.external_events
        WHERE created_at >= NOW() - INTERVAL '7 days'
        GROUP BY kst_date, source_reliability_tier
        ORDER BY kst_date DESC, source_reliability_tier
    """)
    print(f"{'KST 날짜':<15} {'Tier':<10} {'건수':<10}")
    print("-" * 35)
    for r in rows:
        print(f"{str(r['kst_date']):<15} {r['source_reliability_tier']:<10} {r['cnt']:<10}")
    
    # ============================================================
    # 2. T3만 별도 분포 (최근 7일)
    # ============================================================
    print()
    print("=" * 60)
    print("2. T3 external_events 일별 분포 (최근 7일)")
    print("=" * 60)
    rows = await pool.fetch("""
        SELECT 
            DATE(created_at AT TIME ZONE 'Asia/Seoul') as kst_date,
            COUNT(*) as cnt
        FROM trading.external_events
        WHERE source_reliability_tier = 'T3'
          AND created_at >= NOW() - INTERVAL '7 days'
        GROUP BY kst_date
        ORDER BY kst_date DESC
    """)
    print(f"{'KST 날짜':<15} {'T3 건수':<10}")
    print("-" * 25)
    for r in rows:
        print(f"{str(r['kst_date']):<15} {r['cnt']:<10}")
    
    # ============================================================
    # 3. trade_decisions source_type별 분포 (최근 7일)
    # ============================================================
    print()
    print("=" * 60)
    print("3. trade_decisions source_type별 분포 (최근 7일)")
    print("=" * 60)
    rows = await pool.fetch("""
        SELECT 
            DATE(created_at AT TIME ZONE 'Asia/Seoul') as kst_date,
            source_type,
            COUNT(*) as decision_cnt,
            COUNT(DISTINCT symbol) as unique_symbols
        FROM trading.trade_decisions
        WHERE created_at >= NOW() - INTERVAL '7 days'
        GROUP BY kst_date, source_type
        ORDER BY kst_date DESC, source_type
    """)
    print(f"{'KST 날짜':<15} {'source_type':<20} {'decisions':<12} {'unique_symbols':<15}")
    print("-" * 62)
    for r in rows:
        print(f"{str(r['kst_date']):<15} {r['source_type']:<20} {r['decision_cnt']:<12} {r['unique_symbols']:<15}")
    
    # ============================================================
    # 4. T3 freshness 상태 (전체 symbol)
    # ============================================================
    print()
    print("=" * 60)
    print("4. T3 freshness 상태 (전체 symbol)")
    print("=" * 60)
    rows = await pool.fetch("""
        SELECT 
            symbol,
            COUNT(*) as total_events,
            MAX(created_at) as latest_created_at,
            MAX(published_at) as latest_published_at,
            NOW() - MAX(created_at) as since_last_event
        FROM trading.external_events
        WHERE source_reliability_tier = 'T3'
        GROUP BY symbol
        ORDER BY symbol
    """)
    print(f"{'symbol':<10} {'total':<8} {'latest_created_at':<30} {'latest_published_at':<30} {'since_last_event':<20}")
    print("-" * 98)
    for r in rows:
        since = str(r['since_last_event']).split('.')[0] if r['since_last_event'] else 'N/A'
        print(f"{r['symbol']:<10} {r['total_events']:<8} {str(r['latest_created_at']):<30} {str(r['latest_published_at']):<30} {since:<20}")
    
    # ============================================================
    # 5. T3 이벤트가 전혀 없는 symbol 목록
    # ============================================================
    print()
    print("=" * 60)
    print("5. T3 이벤트가 전혀 없는 symbol")
    print("=" * 60)
    rows = await pool.fetch("""
        SELECT DISTINCT symbol
        FROM trading.external_events
        WHERE source_reliability_tier = 'T3'
    """)
    symbols_with_t3 = set(r['symbol'] for r in rows)
    
    all_symbols = await pool.fetch("""
        SELECT DISTINCT symbol FROM trading.external_events
    """)
    all_symbols_set = set(r['symbol'] for r in all_symbols)
    
    no_t3 = all_symbols_set - symbols_with_t3
    # None 값 제거 후 정렬
    no_t3_filtered = {s for s in no_t3 if s is not None}
    if no_t3_filtered:
        for sym in sorted(no_t3_filtered):
            print(f"  {sym}")
    else:
        print("  (모든 symbol에 T3 이벤트가 존재함)")
    if None in no_t3:
        print(f"  (symbol=NULL인 레코드 존재)")
    
    # ============================================================
    # 6. 5/26 T3 이벤트 symbol별 분포
    # ============================================================
    print()
    print("=" * 60)
    print("6. 5/26 T3 이벤트 symbol별 분포")
    print("=" * 60)
    rows = await pool.fetch("""
        SELECT 
            symbol, COUNT(*) as cnt,
            MIN(created_at) as earliest, 
            MAX(created_at) as latest,
            MIN(published_at) as earliest_published,
            MAX(published_at) as latest_published
        FROM trading.external_events
        WHERE source_reliability_tier = 'T3'
          AND created_at >= '2026-05-26 00:00:00+00'
          AND created_at < '2026-05-27 00:00:00+00'
        GROUP BY symbol
        ORDER BY cnt DESC
    """)
    print(f"{'symbol':<10} {'건수':<8} {'earliest_created':<30} {'latest_created':<30} {'earliest_published':<30} {'latest_published':<30}")
    print("-" * 138)
    for r in rows:
        print(f"{r['symbol']:<10} {r['cnt']:<8} {str(r['earliest']):<30} {str(r['latest']):<30} {str(r['earliest_published']):<30} {str(r['latest_published']):<30}")
    
    # ============================================================
    # 7. 5/27 T3 이벤트 symbol별 분포
    # ============================================================
    print()
    print("=" * 60)
    print("7. 5/27 T3 이벤트 symbol별 분포")
    print("=" * 60)
    rows = await pool.fetch("""
        SELECT 
            symbol, COUNT(*) as cnt,
            MIN(created_at) as earliest, 
            MAX(created_at) as latest
        FROM trading.external_events
        WHERE source_reliability_tier = 'T3'
          AND created_at >= '2026-05-27 00:00:00+00'
          AND created_at < '2026-05-28 00:00:00+00'
        GROUP BY symbol
        ORDER BY cnt DESC
    """)
    if rows:
        print(f"{'symbol':<10} {'건수':<8} {'earliest':<30} {'latest':<30}")
        print("-" * 78)
        for r in rows:
            print(f"{r['symbol']:<10} {r['cnt']:<8} {str(r['earliest']):<30} {str(r['latest']):<30}")
    else:
        print("  (5/27 T3 이벤트 없음)")
    
    # ============================================================
    # 8. 5/28 T3 이벤트 symbol별 분포
    # ============================================================
    print()
    print("=" * 60)
    print("8. 5/28 T3 이벤트 symbol별 분포")
    print("=" * 60)
    rows = await pool.fetch("""
        SELECT 
            symbol, COUNT(*) as cnt,
            MIN(created_at) as earliest, 
            MAX(created_at) as latest
        FROM trading.external_events
        WHERE source_reliability_tier = 'T3'
          AND created_at >= '2026-05-28 00:00:00+00'
        GROUP BY symbol
        ORDER BY cnt DESC
    """)
    if rows:
        print(f"{'symbol':<10} {'건수':<8} {'earliest':<30} {'latest':<30}")
        print("-" * 78)
        for r in rows:
            print(f"{r['symbol']:<10} {r['cnt']:<8} {str(r['earliest']):<30} {str(r['latest']):<30}")
    else:
        print("  (5/28 T3 이벤트 없음)")
    
    # ============================================================
    # 9. T3 published_at NULL 비율
    # ============================================================
    print()
    print("=" * 60)
    print("9. T3 published_at NULL 비율")
    print("=" * 60)
    rows = await pool.fetch("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN published_at IS NULL THEN 1 ELSE 0 END) as null_published,
            ROUND(SUM(CASE WHEN published_at IS NULL THEN 1 ELSE 0 END)::numeric / COUNT(*) * 100, 2) as null_pct
        FROM trading.external_events
        WHERE source_reliability_tier = 'T3'
    """)
    for r in rows:
        print(f"  Total T3 events: {r['total']}")
        print(f"  published_at IS NULL: {r['null_published']} ({r['null_pct']}%)")
    
    # ============================================================
    # 10. T3 전체 통계
    # ============================================================
    print()
    print("=" * 60)
    print("10. T3 전체 통계")
    print("=" * 60)
    rows = await pool.fetch("""
        SELECT 
            COUNT(*) as total_events,
            COUNT(DISTINCT symbol) as unique_symbols,
            MIN(created_at) as earliest_event,
            MAX(created_at) as latest_event,
            MIN(published_at) as earliest_published,
            MAX(published_at) as latest_published
        FROM trading.external_events
        WHERE source_reliability_tier = 'T3'
    """)
    for r in rows:
        print(f"  Total T3 events: {r['total_events']}")
        print(f"  Unique symbols: {r['unique_symbols']}")
        print(f"  Earliest event: {r['earliest_event']}")
        print(f"  Latest event: {r['latest_event']}")
        print(f"  Earliest published: {r['earliest_published']}")
        print(f"  Latest published: {r['latest_published']}")
    
    await pool.close()

asyncio.run(check())
