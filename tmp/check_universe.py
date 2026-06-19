import asyncio
from datetime import datetime, timezone, timedelta
from agent_trading.repositories.postgres.core import PostgresDatabase
from agent_trading.repositories.postgres.decision_contexts import DecisionContextRepository

async def main():
    db = PostgresDatabase()
    await db.connect()
    try:
        repo = DecisionContextRepository(db)
        today = datetime.now(timezone.utc).date()
        start_of_day = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
        print(f"Fetching contexts since {start_of_day}...")
        
        # Directly query the DB
        async with db.acquire() as conn:
            records = await conn.fetch('''
                SELECT symbol, market_code, created_at 
                FROM trading.decision_contexts 
                WHERE created_at >= $1
                ORDER BY created_at DESC
            ''', start_of_day)
            
            symbols = set()
            print(f"Total decision contexts today: {len(records)}")
            for r in records:
                symbols.add(r['symbol'])
            
            print(f"Unique symbols in today's universe ({len(symbols)}):")
            print(sorted(list(symbols)))
    finally:
        await db.disconnect()

if __name__ == '__main__':
    asyncio.run(main())
