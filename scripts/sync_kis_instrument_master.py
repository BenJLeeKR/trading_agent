#!/usr/bin/env python3
"""Sync instrument master from a normalized KIS master CSV file.

Phase 1 scope
-------------
- Input: normalized CSV exported from/derived from KIS 종목정보파일
- Output: upsert into ``trading.instruments``
- Optional: deactivate active instruments missing from the input set

This script does not download from KIS directly yet.  It opens the
instrument-master ingestion path using a deterministic, operator-friendly
CSV contract first.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from agent_trading.db.connection import create_pool, close_pool
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import InstrumentEntity
from agent_trading.repositories.contracts import (
    InstrumentIndexMembershipRepository,
    InstrumentRepository,
)
from agent_trading.repositories.postgres.instrument_index_memberships import (
    PostgresInstrumentIndexMembershipRepository,
)
from agent_trading.repositories.postgres.instruments import PostgresInstrumentRepository
from agent_trading.services.market_session import SessionInfo, create_session_provider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sync_kis_instrument_master")

KST = ZoneInfo("Asia/Seoul")
# ops-scheduler catch-up window와 동일하게 08:50 KST까지 장전 apply를 허용한다.
# 07:50 정시 실행을 기본으로 유지하되, 재기동/일시 장애 후 08:50 이전 복구 시에도
# 같은 거래일 장전 instrument master sync를 완료할 수 있어야 한다.
PRE_MARKET_SYNC_CUTOFF = time(8, 50)
AFTER_HOURS_SYNC_START = time(15, 30, 30)


@dataclass(frozen=True, slots=True)
class SyncCounters:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    deactivated: int = 0


@dataclass(frozen=True, slots=True)
class UpdatePolicyDecision:
    allowed: bool
    code: str
    message: str


def _make_instrument_id(symbol: str, market_code: str) -> uuid.UUID:
    """Build a deterministic UUID that preserves historical KRX seed ids."""
    namespace_key = f"{market_code.lower()}/{symbol}"
    return uuid.uuid5(uuid.NAMESPACE_DNS, namespace_key)


def _parse_bool(raw: str | None, default: bool = True) -> bool:
    if raw is None:
        return default
    return raw.strip().upper() in {"TRUE", "1", "YES", "Y"}


def _parse_decimal(raw: str | None, default: str) -> Decimal:
    value = (raw or "").strip() or default
    return Decimal(value)


def _normalize_header_map(fieldnames: Sequence[str]) -> dict[str, str]:
    return {name.strip().lower(): name for name in fieldnames}


def _extract_metadata(record: dict[str, str], headers: dict[str, str], *, source_tag: str) -> dict[str, object]:
    metadata: dict[str, object] = {
        "sync_source": "kis_master_file",
        "source_tag": source_tag,
    }
    passthrough_fields = (
        "name_kr",
        "short_name",
        "isin_code",
        "standard_code",
        "exchange_code",
        "listing_date",
        "delisting_date",
        "source_updated_at",
        "par_value",
        "listing_shares",
    )
    for field in passthrough_fields:
        original = headers.get(field)
        if not original:
            continue
        raw = record.get(original, "").strip()
        if raw:
            metadata[field] = raw

    for lowered, original in headers.items():
        if not lowered.startswith("metadata_"):
            continue
        raw = record.get(original, "").strip()
        if raw:
            metadata[lowered.removeprefix("metadata_")] = raw
    index_memberships: list[str] = []
    raw_memberships = metadata.get("index_memberships")
    if isinstance(raw_memberships, str):
        for part in raw_memberships.split("|"):
            for item in part.split(","):
                value = str(item).strip().upper()
                if value and value not in index_memberships:
                    index_memberships.append(value)
    elif isinstance(raw_memberships, Sequence):
        for item in raw_memberships:
            value = str(item).strip().upper()
            if value and value not in index_memberships:
                index_memberships.append(value)
    for key in ("segment", "universe_segment"):
        raw = metadata.get(key)
        if raw is None:
            continue
        value = str(raw).strip().upper()
        if value and value not in index_memberships:
            index_memberships.append(value)
    if index_memberships:
        metadata["index_memberships"] = index_memberships
    return metadata


def _canonicalize_storage_market(
    market_code: str,
    *,
    asset_class: str,
) -> tuple[str, str | None]:
    normalized_market_code = market_code.upper()
    normalized_asset_class = asset_class.lower()
    if normalized_asset_class in {"kr_stock", "kr_etf", "kr_futures", "kr_options"}:
        if normalized_market_code in {"KRX", "KOSPI", "KOSDAQ"}:
            market_segment = "KOSDAQ" if normalized_market_code == "KOSDAQ" else "KOSPI"
            return "KRX", market_segment
    return normalized_market_code, None


def _build_instrument(
    record: dict[str, str],
    headers: dict[str, str],
    *,
    default_market_code: str,
    default_asset_class: str,
    default_currency: str,
    source_tag: str,
) -> InstrumentEntity:
    symbol = record[headers["symbol"]].strip()
    name = record[headers["name"]].strip()
    market_code = (
        record.get(headers.get("market_code", ""), "").strip() or default_market_code
    ).upper()
    asset_class = (
        record.get(headers.get("asset_class", ""), "").strip() or default_asset_class
    ).lower()
    storage_market_code, canonical_market_segment = _canonicalize_storage_market(
        market_code,
        asset_class=asset_class,
    )
    market_segment = (
        record.get(headers.get("market_segment", ""), "").strip()
        or canonical_market_segment
        or market_code
    ).upper()
    currency = (
        record.get(headers.get("currency", ""), "").strip() or default_currency
    ).upper()
    tick_size = _parse_decimal(record.get(headers.get("tick_size", "")), "1")
    lot_size = _parse_decimal(record.get(headers.get("lot_size", "")), "1")
    is_active = _parse_bool(record.get(headers.get("is_active", "")), True)
    metadata = _extract_metadata(record, headers, source_tag=source_tag)
    metadata.setdefault("source_market_code", market_code)
    metadata.setdefault("canonical_storage_market_code", storage_market_code)
    return InstrumentEntity(
        instrument_id=_make_instrument_id(symbol, storage_market_code),
        symbol=symbol,
        market_code=storage_market_code,
        asset_class=asset_class,
        currency=currency,
        name=name,
        tick_size=tick_size,
        lot_size=lot_size,
        is_active=is_active,
        exchange_code="KRX" if storage_market_code == "KRX" else storage_market_code,
        market_segment=market_segment,
        metadata=metadata,
    )


def _load_csv(
    path: str,
    *,
    default_market_code: str,
    default_asset_class: str,
    default_currency: str,
    source_tag: str,
) -> list[InstrumentEntity]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"Empty CSV file: {path}")
        headers = _normalize_header_map(reader.fieldnames)
        for required in ("symbol", "name"):
            if required not in headers:
                raise ValueError(f"Missing required column '{required}' in CSV: {path}")
        items: list[InstrumentEntity] = []
        for record in reader:
            items.append(
                _build_instrument(
                    record,
                    headers,
                    default_market_code=default_market_code,
                    default_asset_class=default_asset_class,
                    default_currency=default_currency,
                    source_tag=source_tag,
                )
            )
    return items


def _classify(existing: InstrumentEntity | None, incoming: InstrumentEntity) -> str:
    if existing is None:
        return "insert"
    existing_is_placeholder = bool((existing.metadata or {}).get("placeholder"))
    incoming_is_placeholder = bool((incoming.metadata or {}).get("placeholder"))
    if existing_is_placeholder and not incoming_is_placeholder:
        return "promote"
    comparable = (
        "name",
        "asset_class",
        "currency",
        "tick_size",
        "lot_size",
        "is_active",
        "exchange_code",
        "market_segment",
        "metadata",
    )
    for field in comparable:
        if getattr(existing, field) != getattr(incoming, field):
            return "update"
    return "skip"


def _extract_index_memberships(metadata: dict[str, object] | None) -> list[str]:
    raw = (metadata or {}).get("index_memberships")
    if raw is None:
        return []
    if isinstance(raw, str):
        values = [part for chunk in raw.split("|") for part in chunk.split(",")]
    elif isinstance(raw, Sequence):
        values = list(raw)
    else:
        return []
    normalized: list[str] = []
    for value in values:
        item = str(value).strip().upper()
        if item and item not in normalized:
            normalized.append(item)
    return normalized


def _has_explicit_index_membership_payload(metadata: dict[str, object] | None) -> bool:
    raw = (metadata or {}).get("index_memberships")
    if raw is None:
        return False
    if isinstance(raw, str):
        return bool(raw.strip())
    if isinstance(raw, Sequence):
        return any(str(item).strip() for item in raw)
    return False


async def _sync_instruments(
    repo: InstrumentRepository,
    instruments: Sequence[InstrumentEntity],
    *,
    dry_run: bool,
    deactivate_missing: bool,
    deactivate_market_code: str | None,
    membership_repo: InstrumentIndexMembershipRepository | None = None,
    membership_effective_from: date | None = None,
    sync_index_memberships: bool = False,
) -> SyncCounters:
    inserted = updated = skipped = deactivated = 0
    seen_by_market: dict[str, set[str]] = {}
    effective_from = membership_effective_from or datetime.now(KST).date()

    for instrument in instruments:
        seen_by_market.setdefault(instrument.market_code, set()).add(instrument.symbol)
        existing = await repo.get_by_symbol(instrument.symbol, instrument.market_code)
        action = _classify(existing, instrument)
        logger.info("%s %s/%s %s", action.upper(), instrument.market_code, instrument.symbol, instrument.name)
        persisted = existing
        if action == "insert":
            inserted += 1
            if not dry_run:
                persisted = await repo.upsert_by_symbol(instrument)
        elif action in {"update", "promote"}:
            updated += 1
            if not dry_run:
                persisted = await repo.upsert_by_symbol(instrument)
        else:
            skipped += 1
        if (
            not dry_run
            and membership_repo is not None
            and persisted is not None
            and sync_index_memberships
            and _has_explicit_index_membership_payload(instrument.metadata)
        ):
            await membership_repo.sync_current_memberships(
                persisted.instrument_id,
                _extract_index_memberships(instrument.metadata),
                effective_from=effective_from,
                source_tag=str(instrument.metadata.get("source_tag", "")) or None,
                metadata={
                    "sync_source": str(instrument.metadata.get("sync_source", "kis_master_file")),
                    "source_market_code": instrument.metadata.get("source_market_code"),
                    "market_segment": instrument.market_segment,
                },
            )

    if deactivate_missing and deactivate_market_code:
        seen_symbols = seen_by_market.get(deactivate_market_code, set())
        active_items = await repo.list_active_by_market(deactivate_market_code)
        for existing in active_items:
            if existing.symbol in seen_symbols:
                continue
            deactivated += 1
            logger.info("DEACTIVATE %s/%s %s", existing.market_code, existing.symbol, existing.name)
            if dry_run:
                continue
            merged_metadata = dict(existing.metadata or {})
            merged_metadata.update(
                {
                    "sync_source": "kis_master_file",
                    "deactivated_by_sync": True,
                    "deactivated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            await repo.upsert_by_symbol(
                InstrumentEntity(
                    instrument_id=existing.instrument_id,
                    symbol=existing.symbol,
                    market_code=existing.market_code,
                    asset_class=existing.asset_class,
                    currency=existing.currency,
                    name=existing.name,
                    tick_size=existing.tick_size,
                    lot_size=existing.lot_size,
                    is_active=False,
                    exchange_code=existing.exchange_code,
                    market_segment=existing.market_segment,
                    metadata=merged_metadata,
                    created_at=existing.created_at,
                    updated_at=existing.updated_at,
                )
            )
            if membership_repo is not None and sync_index_memberships:
                await membership_repo.sync_current_memberships(
                    existing.instrument_id,
                    [],
                    effective_from=effective_from,
                    source_tag="kis_master_sync_deactivate",
                    metadata={"sync_source": "kis_master_file", "deactivated": True},
                )

    return SyncCounters(
        inserted=inserted,
        updated=updated,
        skipped=skipped,
        deactivated=deactivated,
    )


def _evaluate_update_policy(
    *,
    now_kst: datetime,
    session_info: SessionInfo,
    allow_intraday_apply: bool,
) -> UpdatePolicyDecision:
    if not session_info.is_trading_day:
        return UpdatePolicyDecision(
            allowed=True,
            code="NON_TRADING_DAY_ALLOWED",
            message=(
                "비거래일이므로 instrument master apply를 허용합니다 "
                f"(source={session_info.source}, reason_code={session_info.reason_code})."
            ),
        )

    if allow_intraday_apply:
        return UpdatePolicyDecision(
            allowed=True,
            code="INTRADAY_OVERRIDE_ALLOWED",
            message="--allow-intraday-apply override가 있어 거래일 장중 apply를 허용합니다.",
        )

    current_time = now_kst.timetz().replace(tzinfo=None)
    if current_time < PRE_MARKET_SYNC_CUTOFF:
        return UpdatePolicyDecision(
            allowed=True,
            code="PRE_MARKET_ALLOWED",
            message=(
                "거래일 장전 maintenance window이므로 instrument master apply를 허용합니다 "
                f"({current_time.isoformat(timespec='seconds')} < {PRE_MARKET_SYNC_CUTOFF.isoformat(timespec='seconds')})."
            ),
        )
    if current_time >= AFTER_HOURS_SYNC_START:
        return UpdatePolicyDecision(
            allowed=True,
            code="AFTER_HOURS_ALLOWED",
            message=(
                "거래일 장후 maintenance window이므로 instrument master apply를 허용합니다 "
                f"({current_time.isoformat(timespec='seconds')} >= {AFTER_HOURS_SYNC_START.isoformat(timespec='seconds')})."
            ),
        )
    return UpdatePolicyDecision(
        allowed=False,
        code="INTRADAY_APPLY_BLOCKED",
        message=(
            "거래일 장중에는 instrument master apply를 차단합니다. "
            f"현재 KST={now_kst.isoformat(timespec='seconds')} "
            f"(허용 window: < {PRE_MARKET_SYNC_CUTOFF.isoformat(timespec='seconds')} "
            f"or >= {AFTER_HOURS_SYNC_START.isoformat(timespec='seconds')}). "
            "필요 시 --allow-intraday-apply 로 override 하세요."
        ),
    )


async def _close_session_provider(provider) -> None:
    if provider is None:
        return
    try:
        inner = getattr(provider, "_client", None)
        if inner is not None and hasattr(inner, "close"):
            await inner.close()
    except Exception:
        logger.debug("Session provider close ignored", exc_info=True)


async def _enforce_update_policy(args: argparse.Namespace) -> None:
    if not args.apply:
        return
    if args.ignore_update_policy:
        logger.warning("Instrument master update policy bypassed via --ignore-update-policy")
        return

    if args.now_kst:
        parsed_now = datetime.fromisoformat(args.now_kst)
        now_kst = (
            parsed_now.replace(tzinfo=KST)
            if parsed_now.tzinfo is None
            else parsed_now.astimezone(KST)
        )
    else:
        now_kst = datetime.now(KST)
    provider = await create_session_provider()
    try:
        session_info = await provider.get_session_info(now_kst.date())
    finally:
        await _close_session_provider(provider)

    decision = _evaluate_update_policy(
        now_kst=now_kst,
        session_info=session_info,
        allow_intraday_apply=args.allow_intraday_apply,
    )
    if decision.allowed:
        logger.info("Instrument master update policy: %s — %s", decision.code, decision.message)
        return
    raise SystemExit(decision.message)


async def _run(args: argparse.Namespace) -> int:
    await _enforce_update_policy(args)
    instruments = _load_csv(
        args.csv,
        default_market_code=args.default_market_code,
        default_asset_class=args.default_asset_class,
        default_currency=args.default_currency,
        source_tag=args.source_tag,
    )
    logger.info("Loaded %d instruments from %s", len(instruments), args.csv)

    await create_pool()
    try:
        tx = TransactionManager()
        await tx.__aenter__()
        try:
            repo: InstrumentRepository = PostgresInstrumentRepository(tx)
            membership_repo: InstrumentIndexMembershipRepository = PostgresInstrumentIndexMembershipRepository(tx)
            counters = await _sync_instruments(
                repo,
                instruments,
                dry_run=not args.apply,
                deactivate_missing=args.deactivate_missing,
                deactivate_market_code=args.deactivate_market_code,
                membership_repo=membership_repo,
                sync_index_memberships=args.sync_index_memberships,
            )
            logger.info(
                "Summary: inserted=%d updated=%d skipped=%d deactivated=%d",
                counters.inserted,
                counters.updated,
                counters.skipped,
                counters.deactivated,
            )
            if args.apply:
                await tx.commit()
                logger.info("Changes committed to database.")
            else:
                logger.info("Dry-run complete. Use --apply to persist changes.")
        except BaseException:
            await tx.rollback()
            raise
        finally:
            await tx.__aexit__(None, None, None)
    finally:
        await close_pool()
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync trading.instruments from a normalized KIS master CSV file.",
    )
    parser.add_argument("--csv", required=True, help="Path to normalized KIS master CSV.")
    parser.add_argument("--apply", action="store_true", help="Persist DB changes.")
    parser.add_argument(
        "--deactivate-missing",
        action="store_true",
        help="Deactivate currently active rows missing from the input set.",
    )
    parser.add_argument(
        "--deactivate-market-code",
        default="KRX",
        help="누락 종목 비활성화 대상 market_code (예: KRX, KOSPI, KOSDAQ).",
    )
    parser.add_argument(
        "--default-market-code",
        default="KRX",
        help="CSV에 market_code가 비어 있을 때 사용할 기본 market_code.",
    )
    parser.add_argument("--default-asset-class", default="kr_stock")
    parser.add_argument("--default-currency", default="KRW")
    parser.add_argument("--source-tag", default="kis_master_csv")
    parser.add_argument(
        "--allow-intraday-apply",
        action="store_true",
        help="Override the default policy that blocks --apply during trading-day intraday hours.",
    )
    parser.add_argument(
        "--sync-index-memberships",
        action="store_true",
        help=(
            "metadata_index_memberships를 authoritative source로 간주해 "
            "instrument_index_memberships까지 동기화한다. "
            "기본값은 비활성이다."
        ),
    )
    parser.add_argument(
        "--ignore-update-policy",
        action="store_true",
        help="Bypass the instrument master update policy gate entirely (manual emergency use only).",
    )
    parser.add_argument(
        "--now-kst",
        default=None,
        help="Testing hook: override current KST timestamp (ISO-8601).",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = _parse_args()
    if args.deactivate_missing and not args.deactivate_market_code:
        raise SystemExit("--deactivate-missing requires --deactivate-market-code")
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
