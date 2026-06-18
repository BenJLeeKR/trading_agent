import asyncio
from agent_trading.config.settings import get_settings
from agent_trading.db.connection import get_db_pool
from agent_trading.repositories.postgres.decision_contexts import PostgresDecisionContextRepository

async def main():
    settings = get_settings()
    pool = await get_db_pool(settings.db_dsn)
    repo = PostgresDecisionContextRepository(pool)
    
    # We don't have direct access to universe generation logs in DB if not saved,
    # but we can check the most recent decision context for 000227
    async with pool.acquire() as conn:
        records = await conn.fetch("""
            SELECT id, created_at, symbol, market_code, snapshot_data->'universe_inclusion_reason' as reason,
                   snapshot_data->'signal_feature' as signal_feature
            FROM decision_contexts 
            WHERE symbol = '000227'
            ORDER BY created_at DESC 
            LIMIT 5
        """)
        for r in records:
            print(f"Context ID: {r['id']}, Time: {r['created_at']}, Reason: {r['reason']}")
            # print(f"Signal: {r['signal_feature']}")

asyncio.run(main())
