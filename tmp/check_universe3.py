import asyncio
import asyncpg

async def main():
    dsn = "postgresql://trading:trading@localhost:5432/trading"
    conn = await asyncpg.connect(dsn)
    try:
        records = await conn.fetch('''
            SELECT symbol, COUNT(*) as cnt 
            FROM trading.decision_contexts 
            WHERE created_at >= CURRENT_DATE 
            GROUP BY symbol 
            ORDER BY symbol;
        ''')
        
        symbols = [r['symbol'] for r in records]
        print(f"=== 오늘 유니버스에 편입되어 평가된 종목 목록 (총 {len(symbols)}개) ===")
        print(f"[{', '.join(symbols)}]")
            
    finally:
        await conn.close()

if __name__ == '__main__':
    asyncio.run(main())
