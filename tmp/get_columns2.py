import asyncio
import asyncpg
async def main():
    conn = await asyncpg.connect("postgresql://trading:trading@localhost:5432/trading")
    records = await conn.fetch("SELECT column_name FROM information_schema.columns WHERE table_schema='trading' AND table_name='order_requests';")
    print("Columns in order_requests:", [r['column_name'] for r in records])
    await conn.close()
asyncio.run(main())
