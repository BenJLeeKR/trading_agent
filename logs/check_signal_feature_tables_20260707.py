import asyncio
import asyncpg
import json
import os
from datetime import date

RUN_DATE = date(2026, 7, 6)

TABLES = [
    'operations_day_runs',
    'signal_feature_batch_runs',
    'signal_feature_batch_run_items',
    'signal_feature_snapshots',
    'trade_decisions',
]

async def main() -> None:
    conn = await asyncpg.connect(
        host=os.environ['DATABASE_HOST'],
        port=int(os.environ.get('DATABASE_PORT', '5432')),
        user=os.environ['DATABASE_USER'],
        password=os.environ['DATABASE_PASSWORD'],
        database=os.environ['DATABASE_NAME'],
    )
    try:
        payload: dict[str, object] = {}

        schema = {}
        for table in TABLES:
            rows = await conn.fetch(
                """
                select column_name, data_type
                from information_schema.columns
                where table_schema = 'trading' and table_name = $1
                order by ordinal_position
                """,
                table,
            )
            schema[table] = [dict(r) for r in rows]
        payload['schema'] = schema

        payload['operations_day_runs'] = [
            dict(r)
            for r in await conn.fetch(
                """
                select run_date, scheduler_status, summary_json
                from trading.operations_day_runs
                where run_date = $1::date
                """,
                RUN_DATE,
            )
        ]

        payload['signal_feature_batch_runs'] = [
            dict(r)
            for r in await conn.fetch(
                """
                select *
                from trading.signal_feature_batch_runs
                where trade_date = $1::date
                order by created_at desc
                limit 5
                """,
                RUN_DATE,
            )
        ]

        payload['signal_feature_batch_run_items_agg'] = [
            dict(r)
            for r in await conn.fetch(
                """
                select signal_feature_batch_run_id,
                       count(*) as item_count,
                       count(*) filter (where status = 'persisted') as persisted_count,
                       count(*) filter (where status <> 'persisted') as non_persisted_count
                from trading.signal_feature_batch_run_items
                where trade_date = $1::date
                group by signal_feature_batch_run_id
                order by signal_feature_batch_run_id desc
                """,
                RUN_DATE,
            )
        ]

        payload['signal_feature_snapshots_summary'] = [
            dict(r)
            for r in await conn.fetch(
                """
                select trade_date,
                       count(*) as snapshot_count,
                       min(snapshot_at) as min_snapshot_at,
                       max(snapshot_at) as max_snapshot_at,
                       min(created_at) as first_created_at,
                       max(created_at) as last_created_at
                from trading.signal_feature_snapshots
                where trade_date = $1::date
                group by trade_date
                """,
                RUN_DATE,
            )
        ]

        payload['signal_feature_snapshots_recent'] = [
            dict(r)
            for r in await conn.fetch(
                """
                select *
                from trading.signal_feature_snapshots
                where trade_date = $1::date
                order by created_at desc
                limit 10
                """,
                RUN_DATE,
            )
        ]

        print(json.dumps(payload, ensure_ascii=False, default=str, indent=2))
    finally:
        await conn.close()

asyncio.run(main())
