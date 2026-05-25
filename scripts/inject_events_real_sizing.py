#!/usr/bin/env python3
"""Inject 4 bullish seeded_news events for 005930 to force BUY decision."""
import asyncio
import asyncpg
import uuid
from datetime import datetime, timezone

EVENTS = [
    ("삼성전자 HBM3 12단 양산 발표",
     "삼성전자가 업계 최초로 HBM3 12단 제품 양산에 성공하며 AI 반도체 시장 선점",
     0.95),
    ("삼성전자 3분기 가이던스 상향",
     "삼성전자가 3분기 실적 가이던스를 상향 조정, 영업이익 15조 전망",
     0.90),
    ("삼성전자 자사주 10조 매입 발표",
     "삼성전자가 10조원 규모의 자사주 매입 계획 발표, 주주환원 정책 강화",
     0.88),
    ("삼성전자 파운드리 2nm 수주 성공",
     "삼성전자 파운드리가 2nm 공정 대규모 수주에 성공하며 TSMC 추격",
     0.92),
]

INSERT_SQL = """
INSERT INTO trading.external_events
    (event_id, event_type, source_name, source_reliability_tier,
     symbol, market, direction, headline, body_summary,
     published_at, ingested_at, severity, metadata)
VALUES
    ($1::uuid, 'seeded_news', 'smoke_test_real_sizing', 'T1',
     '005930', 'KRX', 'bullish', $2::text, $3::text,
     $4::timestamptz, $4::timestamptz, 'high',
     jsonb_build_object(
         'source', 'smoke_test_real_sizing',
         'importance', 'high',
         'event_index', $5::text,
         'is_relevant', true,
         'impact_score', $6::text
     ))
"""


async def main():
    conn = await asyncpg.connect(
        "postgresql://trading:trading@db:5432/trading"
    )
    now = datetime.now(timezone.utc)
    for i, (headline, body, score) in enumerate(EVENTS):
        eid = str(uuid.uuid4())
        await conn.execute(
            INSERT_SQL,
            eid, headline, body, now, str(i), str(score),
        )
        print(f"  Injected [{i}]: {headline[:30]}...")
    await conn.close()
    print("4 events injected successfully")


if __name__ == "__main__":
    asyncio.run(main())
