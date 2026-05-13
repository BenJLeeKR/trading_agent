#!/usr/bin/env python3
"""Temporary script: UPDATE smoke_test_v1 event for APPROVE re-verification."""

import asyncio

import asyncpg


async def main() -> None:
    # Docker Compose default connection
    conn = await asyncpg.connect(
        host="localhost",
        port=5432,
        user="trading",
        password="trading",
        database="trading",
    )
    try:
        result = await conn.execute("""
            UPDATE external_events 
            SET 
                published_at = NOW(),
                ingested_at = NOW(),
                headline = '삼성전자, 1분기 연결기준 영업이익 시장 기대치 상회',
                body_summary = '삼성전자 1분기 잠정실적 발표: 매출 77조, 영업이익 9.8조로 컨센서스 8% 상회. 반도체 부문 호조 지속, HBM3E 양산 본격화.',
                severity = 'high',
                direction = 'positive',
                metadata = '{"importance": "high", "purpose": "smoke_test"}'
            WHERE event_id = '1f1ccf81-6da9-42d7-9e5f-9cd655027767'
        """)
        print(f"UPDATE result: {result}")

        row = await conn.fetchrow(
            "SELECT event_id, published_at, ingested_at, headline, severity, direction, metadata::text "
            "FROM external_events "
            "WHERE event_id = '1f1ccf81-6da9-42d7-9e5f-9cd655027767'"
        )
        print("Updated row:")
        for k, v in row.items():
            print(f"  {k}: {v}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
