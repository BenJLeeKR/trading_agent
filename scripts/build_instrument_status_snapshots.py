#!/usr/bin/env python3
"""KIS CTPF1002R 기반 instrument status snapshot 배치를 적재한다."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Sequence
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from agent_trading.brokers.errors import BrokerError
from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.config.settings import AppSettings
from agent_trading.db.connection import close_pool, create_pool
from agent_trading.db.migrations.run import run_all_migrations
from agent_trading.db.transaction import transaction
from agent_trading.domain.entities import InstrumentStatusSnapshotEntity
from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories
from agent_trading.runtime.bootstrap import _build_kis_live_quote_client
from agent_trading.services.signal_feature_batch_runtime import (
    DEFAULT_SIGNAL_FEATURE_AFTER_MARKET_FREEZE_PURPOSE,
)

logger = logging.getLogger("build_instrument_status_snapshots")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

KST = ZoneInfo("Asia/Seoul")
DEFAULT_PRE_MARKET_SNAPSHOT_TIME = time(5, 5)
DEFAULT_DECISION_LOOP_INTRADAY_FREEZE_PURPOSE = "decision_loop_intraday"
DEFAULT_FREEZE_PURPOSES = (
    DEFAULT_DECISION_LOOP_INTRADAY_FREEZE_PURPOSE,
    DEFAULT_SIGNAL_FEATURE_AFTER_MARKET_FREEZE_PURPOSE,
)
HALT_STATUS_CODES = frozenset({"01", "02", "03", "04", "05"})


@dataclass(slots=True, frozen=True)
class TargetInstrument:
    instrument_id: UUID
    symbol: str
    market_code: str
    market_segment: str | None = None
    target_sources: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class BatchResult:
    target_count: int
    persisted_count: int
    skipped_count: int
    error_count: int
    rows: tuple[dict[str, object], ...]


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="KIS instrument status snapshot 적재 배치",
    )
    parser.add_argument(
        "--business-date",
        help="대상 거래일 (YYYY-MM-DD). 기본값은 오늘 KST.",
    )
    parser.add_argument(
        "--snapshot-at",
        help="snapshot_at ISO 시각. 미지정 시 business_date 05:05 KST.",
    )
    parser.add_argument(
        "--freeze-purpose",
        dest="freeze_purposes",
        action="append",
        default=[],
        help="대상 universe_freeze purpose. 여러 번 지정 가능.",
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=[],
        help="대상 symbol override. 지정 시 freeze/membership 조회 대신 이 집합만 사용.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="최종 대상 개수 제한. 0 이하이면 전체.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=1.0,
        help="종목 간 pacing sleep 초.",
    )
    parser.add_argument(
        "--status-scope",
        default="instrument",
        choices=("instrument", "market_overlay_probe", "submit_preflight"),
        help="저장할 status_scope",
    )
    parser.add_argument(
        "--source-type",
        default="kis_stock_basic_info",
        choices=("kis_stock_basic_info", "kis_inquire_price", "composed_status"),
        help="저장할 source_type",
    )
    parser.add_argument(
        "--run-migrations",
        action="store_true",
        help="실행 전 DB migration 적용",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DB 저장 없이 조회/매핑만 수행",
    )
    parser.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="결과 출력 형식",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _parse_business_date(raw: str | None) -> date:
    if raw is None or not raw.strip():
        return datetime.now(KST).date()
    return date.fromisoformat(raw.strip())


def _resolve_snapshot_at(raw: str | None, *, business_date: date) -> datetime:
    if raw and raw.strip():
        parsed = datetime.fromisoformat(raw.strip())
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=KST)
        return parsed.astimezone(timezone.utc)
    local = datetime.combine(
        business_date,
        DEFAULT_PRE_MARKET_SNAPSHOT_TIME,
        tzinfo=KST,
    )
    return local.astimezone(timezone.utc)


def _normalize_str(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text.upper() if text else None


def _payload_value(payload: dict[str, Any], key: str) -> str | None:
    candidates = (
        key,
        key.lower(),
        key.upper(),
    )
    for candidate in candidates:
        if candidate in payload:
            return _normalize_str(payload.get(candidate))
    return None


def _derive_status_reason_codes(payload: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    if _payload_value(payload, "tr_stop_yn") == "Y":
        codes.append("trading_halt")
    if _payload_value(payload, "admn_item_yn") == "Y":
        codes.append("administrative_issue")
    if _payload_value(payload, "nxt_tr_stop_yn") == "Y":
        codes.append("next_session_halt")
    if _payload_value(payload, "temp_stop_yn") == "Y":
        codes.append("temporary_halt")
    status_code = _payload_value(payload, "iscd_stat_cls_code")
    if status_code:
        codes.append(f"status_code:{status_code}")
        if status_code in HALT_STATUS_CODES:
            codes.append(f"restricted_status:{status_code}")
    if not codes:
        codes.append("status_normal")
    return codes


def _build_snapshot_entity(
    *,
    target: TargetInstrument,
    snapshot_at: datetime,
    source_type: str,
    status_scope: str,
    payload: dict[str, Any],
) -> InstrumentStatusSnapshotEntity:
    return InstrumentStatusSnapshotEntity(
        instrument_status_snapshot_id=uuid4(),
        instrument_id=target.instrument_id,
        snapshot_at=snapshot_at,
        source_type=source_type,
        status_scope=status_scope,
        tr_stop_yn=_payload_value(payload, "tr_stop_yn"),
        admn_item_yn=_payload_value(payload, "admn_item_yn"),
        nxt_tr_stop_yn=_payload_value(payload, "nxt_tr_stop_yn"),
        temp_stop_yn=_payload_value(payload, "temp_stop_yn"),
        iscd_stat_cls_code=_payload_value(payload, "iscd_stat_cls_code"),
        mket_id_cd=_payload_value(payload, "mket_id_cd"),
        scty_grp_id_cd=_payload_value(payload, "scty_grp_id_cd"),
        excg_dvsn_cd=_payload_value(payload, "excg_dvsn_cd"),
        prdt_type_cd=_payload_value(payload, "prdt_type_cd"),
        status_reason_codes=_derive_status_reason_codes(payload),
        raw_payload_json=dict(payload),
    )


async def _list_targets(
    *,
    business_date: date,
    freeze_purposes: Sequence[str],
    symbols: Sequence[str],
    limit: int,
) -> tuple[TargetInstrument, ...]:
    normalized_symbols = [
        str(symbol).strip().upper()
        for symbol in symbols
        if str(symbol).strip()
    ]
    normalized_freeze_purposes = [
        str(purpose).strip()
        for purpose in freeze_purposes
        if str(purpose).strip()
    ] or list(DEFAULT_FREEZE_PURPOSES)
    normalized_limit = max(0, int(limit))

    async with transaction() as tx:
        conn = tx.connection
        if normalized_symbols:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (i.symbol)
                       i.instrument_id,
                       i.symbol,
                       i.market_code,
                       i.market_segment
                  FROM trading.instruments i
                 WHERE i.symbol = ANY($1::text[])
                 ORDER BY i.symbol,
                          CASE
                              WHEN i.market_code = 'KRX' AND i.market_segment IN ('KOSPI', 'KOSDAQ') THEN 0
                              WHEN i.market_code IN ('KOSPI', 'KOSDAQ') THEN 1
                              ELSE 2
                          END,
                          i.updated_at DESC NULLS LAST,
                          i.created_at DESC NULLS LAST
                """,
                normalized_symbols,
            )
            items = tuple(
                TargetInstrument(
                    instrument_id=row["instrument_id"],
                    symbol=str(row["symbol"]),
                    market_code=str(row["market_code"]),
                    market_segment=(
                        str(row["market_segment"])
                        if row["market_segment"] is not None
                        else None
                    ),
                    target_sources=("manual_symbol_override",),
                )
                for row in rows
            )
            if normalized_limit > 0:
                return items[:normalized_limit]
            return items

        rows = await conn.fetch(
            """
            WITH latest_freeze_runs AS (
                SELECT DISTINCT ON (ufr.freeze_purpose)
                       ufr.universe_freeze_run_id,
                       ufr.freeze_purpose
                  FROM trading.universe_freeze_runs ufr
                 WHERE ufr.business_date = $1
                   AND ufr.freeze_purpose = ANY($2::text[])
                 ORDER BY ufr.freeze_purpose, ufr.freeze_sequence DESC, ufr.frozen_at DESC
            ),
            freeze_targets AS (
                SELECT ufri.instrument_id,
                       'freeze:' || lfr.freeze_purpose AS target_source
                  FROM latest_freeze_runs lfr
                  JOIN trading.universe_freeze_run_items ufri
                    ON ufri.universe_freeze_run_id = lfr.universe_freeze_run_id
            ),
            membership_targets AS (
                SELECT iim.instrument_id,
                       'active_membership' AS target_source
                  FROM trading.instrument_index_memberships iim
                 WHERE iim.effective_to IS NULL
            ),
            latest_positions AS (
                SELECT DISTINCT ON (ps.account_id, ps.instrument_id)
                       ps.instrument_id,
                       ps.quantity
                  FROM trading.position_snapshots ps
                 ORDER BY ps.account_id, ps.instrument_id, ps.snapshot_at DESC, ps.created_at DESC
            ),
            held_targets AS (
                SELECT lp.instrument_id,
                       'held_position' AS target_source
                  FROM latest_positions lp
                 WHERE lp.quantity > 0
            ),
            target_instruments AS (
                SELECT instrument_id, target_source FROM freeze_targets
                UNION ALL
                SELECT instrument_id, target_source FROM membership_targets
                UNION ALL
                SELECT instrument_id, target_source FROM held_targets
            )
            SELECT i.instrument_id,
                   i.symbol,
                   i.market_code,
                   i.market_segment,
                   ARRAY_AGG(DISTINCT ti.target_source ORDER BY ti.target_source) AS target_sources
              FROM target_instruments ti
              JOIN trading.instruments i
                ON i.instrument_id = ti.instrument_id
             WHERE i.is_active = TRUE
               AND i.market_code = 'KRX'
               AND i.market_segment IN ('KOSPI', 'KOSDAQ')
             GROUP BY i.instrument_id, i.symbol, i.market_code, i.market_segment
             ORDER BY i.symbol
            """,
            business_date,
            normalized_freeze_purposes,
        )
        items = tuple(
            TargetInstrument(
                instrument_id=row["instrument_id"],
                symbol=str(row["symbol"]),
                market_code=str(row["market_code"]),
                market_segment=(
                    str(row["market_segment"])
                    if row["market_segment"] is not None
                    else None
                ),
                target_sources=tuple(
                    str(value)
                    for value in (row["target_sources"] or [])
                    if str(value).strip()
                ),
            )
            for row in rows
        )
        if normalized_limit > 0:
            return items[:normalized_limit]
        return items


async def _run(args: argparse.Namespace) -> int:
    business_date = _parse_business_date(args.business_date)
    snapshot_at = _resolve_snapshot_at(args.snapshot_at, business_date=business_date)

    if args.run_migrations:
        await run_all_migrations()

    await create_pool()
    client: KISRestClient | None = None
    try:
        settings = AppSettings()
        client = _build_kis_live_quote_client(settings)
        if client is None:
            raise RuntimeError(
                "instrument_status_snapshot_live_client_not_configured: "
                "KIS_LIVE_INFO_APP_KEY / KIS_LIVE_INFO_APP_SECRET 설정이 필요합니다."
            )
        targets = await _list_targets(
            business_date=business_date,
            freeze_purposes=args.freeze_purposes,
            symbols=args.symbols,
            limit=args.limit,
        )
        logger.info(
            "instrument status snapshot target count=%s business_date=%s snapshot_at=%s",
            len(targets),
            business_date.isoformat(),
            snapshot_at.isoformat(),
        )

        persisted_count = 0
        skipped_count = 0
        error_count = 0
        rows: list[dict[str, object]] = []

        async with transaction() as tx:
            repos = build_postgres_repositories(tx)
            for index, target in enumerate(targets, start=1):
                try:
                    payload = await client.get_stock_basic_info(target.symbol)
                    if not payload:
                        skipped_count += 1
                        rows.append(
                            {
                                "symbol": target.symbol,
                                "market_code": target.market_code,
                                "status": "skipped_empty_payload",
                                "target_sources": list(target.target_sources),
                            }
                        )
                    else:
                        entity = _build_snapshot_entity(
                            target=target,
                            snapshot_at=snapshot_at,
                            source_type=args.source_type,
                            status_scope=args.status_scope,
                            payload=payload,
                        )
                        if not args.dry_run:
                            await repos.instrument_status_snapshots.add(entity)
                            persisted_count += 1
                        rows.append(
                            {
                                "symbol": target.symbol,
                                "market_code": target.market_code,
                                "status": "persisted" if not args.dry_run else "dry_run_mapped",
                                "status_reason_codes": entity.status_reason_codes,
                                "target_sources": list(target.target_sources),
                            }
                        )
                except BrokerError as exc:
                    error_count += 1
                    rows.append(
                        {
                            "symbol": target.symbol,
                            "market_code": target.market_code,
                            "status": "broker_error",
                            "error": str(exc),
                            "target_sources": list(target.target_sources),
                        }
                    )
                    logger.warning(
                        "instrument status snapshot broker_error symbol=%s index=%s/%s: %s",
                        target.symbol,
                        index,
                        len(targets),
                        exc,
                    )
                except Exception as exc:
                    error_count += 1
                    rows.append(
                        {
                            "symbol": target.symbol,
                            "market_code": target.market_code,
                            "status": "error",
                            "error": str(exc),
                            "target_sources": list(target.target_sources),
                        }
                    )
                    logger.exception(
                        "instrument status snapshot error symbol=%s index=%s/%s",
                        target.symbol,
                        index,
                        len(targets),
                    )
                if index < len(targets) and args.sleep_seconds > 0:
                    await asyncio.sleep(max(0.0, args.sleep_seconds))

        result = BatchResult(
            target_count=len(targets),
            persisted_count=persisted_count,
            skipped_count=skipped_count,
            error_count=error_count,
            rows=tuple(rows),
        )
    finally:
        if client is not None:
            await client.close()
        await close_pool()

    if args.output == "json":
        print(
            json.dumps(
                {
                    "business_date": business_date.isoformat(),
                    "snapshot_at": snapshot_at.isoformat(),
                    "target_count": result.target_count,
                    "persisted_count": result.persisted_count,
                    "skipped_count": result.skipped_count,
                    "error_count": result.error_count,
                    "rows": list(result.rows),
                },
                ensure_ascii=False,
            )
        )
    else:
        print(f"business_date: {business_date.isoformat()}")
        print(f"snapshot_at: {snapshot_at.isoformat()}")
        print(f"target_count: {result.target_count}")
        print(f"persisted_count: {result.persisted_count}")
        print(f"skipped_count: {result.skipped_count}")
        print(f"error_count: {result.error_count}")
    return 0 if result.error_count == 0 else 1


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_run(_parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
