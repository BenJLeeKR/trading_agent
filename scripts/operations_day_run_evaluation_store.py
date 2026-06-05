from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any


def build_dsn_from_env(env: Mapping[str, str] | None = None) -> str | None:
    """Build a Postgres DSN from environment variables."""
    source = env or os.environ
    dsn = source.get("DATABASE_URL") or source.get("DATABASE_DSN")
    if dsn:
        return dsn

    host = source.get("DATABASE_HOST") or source.get("DB_HOST") or "localhost"
    port = source.get("DATABASE_PORT") or source.get("DB_PORT") or "5432"
    user = source.get("DATABASE_USER") or source.get("DB_USER") or "trading"
    password = source.get("DATABASE_PASSWORD") or source.get("DB_PASSWORD") or "trading"
    database = source.get("DATABASE_NAME") or source.get("DB_NAME") or "trading"
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def build_evaluation_entry(
    *,
    overall_status: str,
    generated_at: datetime,
    checks: Sequence[object],
    extra: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    """Build a compact summary payload for ``operations_day_runs.summary_json``."""
    counts = {"READY": 0, "WARN": 0, "BLOCKED": 0}
    blocked_codes: list[str] = []
    warn_codes: list[str] = []

    for check in checks:
        status = str(getattr(check, "status", "") or "").upper()
        code = str(getattr(check, "code", "") or "")
        if status in counts:
            counts[status] += 1
        if status == "BLOCKED" and code:
            blocked_codes.append(code)
        elif status == "WARN" and code:
            warn_codes.append(code)

    payload: dict[str, object] = {
        "overall_status": overall_status,
        "generated_at": generated_at.isoformat(),
        "check_counts": {
            "ready": counts["READY"],
            "warn": counts["WARN"],
            "blocked": counts["BLOCKED"],
        },
        "blocked_codes": blocked_codes,
        "warn_codes": warn_codes,
    }
    if extra:
        payload.update(dict(extra))
    return payload


def _normalize_summary_json(raw: object) -> dict[str, object]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


async def persist_operations_day_evaluation(
    *,
    dsn: str | None,
    run_date: date,
    key: str,
    payload: Mapping[str, Any],
    is_trading_day: bool | None,
) -> None:
    """Merge an evaluation payload into ``operations_day_runs.summary_json``."""
    if dsn is None:
        return

    import asyncpg

    conn = await asyncpg.connect(dsn=dsn)
    try:
        row = await conn.fetchrow(
            "SELECT summary_json FROM trading.operations_day_runs WHERE run_date = $1",
            run_date,
        )
        summary_json = _normalize_summary_json(row["summary_json"]) if row is not None else {}
        summary_json[key] = dict(payload)

        if row is not None:
            await conn.execute(
                """
                UPDATE trading.operations_day_runs
                SET summary_json = $2::jsonb,
                    updated_at = NOW()
                WHERE run_date = $1
                """,
                run_date,
                json.dumps(summary_json),
            )
            return

        await conn.execute(
            """
            INSERT INTO trading.operations_day_runs
                (run_date, scheduler_status, is_trading_day, summary_json)
            VALUES
                ($1, $2, $3, $4::jsonb)
            ON CONFLICT (run_date) DO UPDATE SET
                summary_json = EXCLUDED.summary_json,
                updated_at = NOW()
            """,
            run_date,
            "evaluation_only",
            True if is_trading_day is None else bool(is_trading_day),
            json.dumps(summary_json),
        )
    finally:
        await conn.close()
