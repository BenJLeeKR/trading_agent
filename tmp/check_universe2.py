import asyncio
import os
import asyncpg

async def main():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        # Fallback to components
        user = os.environ.get("POSTGRES_USER", "postgres")
        pw = os.environ.get("POSTGRES_PASSWORD", "postgres")
        db = os.environ.get("POSTGRES_DB", "postgres")
        host = os.environ.get("POSTGRES_HOST", "localhost")
        port = os.environ.get("POSTGRES_PORT", "5432")
        dsn = f"postgresql://{user}:{pw}@{host}:{port}/{db}"
    
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
        print(f"=== 오늘 시스템이 점검한(유니버스 편입) 종목 목록 (총 {len(symbols)}개) ===")
        for r in records:
            print(f"종목코드: {r['symbol']}, 판단 횟수: {r['cnt']}")
            
    finally:
        await conn.close()

if __name__ == '__main__':
    asyncio.run(main())
