"""Docker 재배포 후 검증 스크립트 v3 - decision_context_id 추적"""
import asyncio
import asyncpg

DSN = "postgresql://trading:trading@db:5432/trading"


async def main():
    conn = await asyncpg.connect(DSN)

    # held_position trade_decisions와 동일한 decision_context_id의 다른 레코드 확인
    rows = await conn.fetch("""
        SELECT td.trade_decision_id,
               td.symbol,
               td.source_type,
               td.decision_type,
               td.side,
               td.decision_context_id,
               td.created_at
        FROM trade_decisions td
        WHERE td.source_type = 'held_position'
        ORDER BY td.created_at DESC
    """)
    print(f"=== held_position trade_decisions: {len(rows)} ===")
    for r in rows:
        # 동일한 decision_context_id의 다른 레코드 확인
        others = await conn.fetch("""
            SELECT source_type, decision_type, side, created_at
            FROM trade_decisions
            WHERE decision_context_id = $1::uuid
              AND trade_decision_id != $2::uuid
            ORDER BY created_at
        """, r['decision_context_id'], r['trade_decision_id'])
        
        print(f"  Symbol: {r['symbol']}")
        print(f"    source_type: {r['source_type']}, decision_type: {r['decision_type']}, side: {r['side']}")
        print(f"    ctx_id: {r['decision_context_id']}")
        print(f"    created_at: {r['created_at']}")
        if others:
            print(f"    SAME CTX - other records:")
            for o in others:
                print(f"      source={o['source_type']}, type={o['decision_type']}, side={o['side']}, at={o['created_at']}")
        else:
            print(f"    (no other records with same ctx_id)")
        print()

    await conn.close()


asyncio.run(main())
