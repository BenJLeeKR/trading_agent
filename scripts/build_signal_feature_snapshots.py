#!/usr/bin/env python3
"""JSON 일봉 입력으로 signal feature snapshot을 계산/적재한다."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from uuid import UUID, uuid4

from agent_trading.domain.entities import (
    InstrumentEntity,
    SignalFeatureBatchRunEntity,
    SignalFeatureBatchRunItemEntity,
)
from agent_trading.runtime.bootstrap import postgres_runtime
from agent_trading.services.signal_backbone import PriceBar
from agent_trading.services.signal_feature_pipeline import (
    SignalFeatureBatchResult,
    SignalFeatureBatchRow,
    SignalFeaturePipelineService,
)


@dataclass(slots=True, frozen=True)
class RawSignalInputRow:
    symbol: str
    market: str
    timeframe: str
    feature_set_version: str
    bars: tuple[PriceBar, ...]
    instrument_id: str | None = None


@dataclass(slots=True, frozen=True)
class LoadedSignalInput:
    rows: tuple[RawSignalInputRow, ...]
    universe_metadata: dict[str, object]
    fetch_error_rows: tuple[dict[str, object], ...]


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Signal feature snapshot 배치 계산",
    )
    parser.add_argument(
        "--input",
        required=True,
        help="입력 JSON 파일 경로",
    )
    parser.add_argument(
        "--default-market",
        default="KRX",
        help="market 누락 시 사용할 기본값",
    )
    parser.add_argument(
        "--default-timeframe",
        default="1d",
        help="timeframe 누락 시 사용할 기본값",
    )
    parser.add_argument(
        "--feature-set-version",
        default="signal_backbone_v1",
        help="feature_set_version 기본값",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DB 저장 없이 계산만 수행",
    )
    parser.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="출력 형식",
    )
    parser.add_argument(
        "--trigger-type",
        default="after_market_scheduler",
        help="signal_feature_batch_runs.trigger_type 값",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _load_rows(
    path: str,
    *,
    default_market: str,
    default_timeframe: str,
    feature_set_version: str,
) -> LoadedSignalInput:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    universe_metadata: dict[str, object] = {}
    fetch_error_rows: tuple[dict[str, object], ...] = ()
    if isinstance(raw, dict):
        raw_rows = raw.get("fetch_success_rows")
        if not isinstance(raw_rows, list):
            raise ValueError("입력 JSON 객체에는 fetch_success_rows 리스트가 필요합니다.")
        universe_metadata = (
            dict(raw.get("universe_metadata", {}))
            if isinstance(raw.get("universe_metadata"), dict)
            else {}
        )
        fetch_error_rows_raw = raw.get("fetch_error_rows", [])
        if isinstance(fetch_error_rows_raw, list):
            fetch_error_rows = tuple(
                item for item in fetch_error_rows_raw if isinstance(item, dict)
            )
    elif isinstance(raw, list):
        raw_rows = raw
    else:
        raise ValueError("입력 JSON 최상위는 리스트 또는 객체여야 합니다.")

    rows: list[RawSignalInputRow] = []
    for item in raw_rows:
        if not isinstance(item, dict):
            raise ValueError("각 입력 row는 객체여야 합니다.")
        symbol = str(item.get("symbol", "")).strip()
        if not symbol:
            raise ValueError("symbol은 필수입니다.")
        bars_raw = item.get("bars")
        if not isinstance(bars_raw, list) or not bars_raw:
            raise ValueError(f"{symbol}: bars는 비어 있지 않은 리스트여야 합니다.")
        rows.append(
            RawSignalInputRow(
                symbol=symbol,
                market=str(item.get("market") or default_market),
                timeframe=str(item.get("timeframe") or default_timeframe),
                feature_set_version=str(
                    item.get("feature_set_version") or feature_set_version
                ),
                bars=tuple(_parse_bar(symbol, bar) for bar in bars_raw),
                instrument_id=(
                    str(item["instrument_id"]).strip()
                    if item.get("instrument_id")
                    else None
                ),
            )
        )
    return LoadedSignalInput(
        rows=tuple(rows),
        universe_metadata=universe_metadata,
        fetch_error_rows=fetch_error_rows,
    )


def _parse_bar(symbol: str, raw: Any) -> PriceBar:
    if not isinstance(raw, dict):
        raise ValueError(f"{symbol}: bar row는 객체여야 합니다.")
    return PriceBar(
        timestamp=_parse_timestamp(symbol, raw.get("timestamp")),
        open_price=float(raw["open_price"]),
        high_price=float(raw["high_price"]),
        low_price=float(raw["low_price"]),
        close_price=float(raw["close_price"]),
        volume=float(raw["volume"]),
        turnover=float(raw["turnover"]) if raw.get("turnover") is not None else None,
    )


def _parse_timestamp(symbol: str, raw: Any) -> datetime:
    if not isinstance(raw, str):
        raise ValueError(f"{symbol}: timestamp는 ISO 문자열이어야 합니다.")
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{symbol}: timestamp 파싱 실패 ({raw})") from exc


async def _run(args: argparse.Namespace) -> int:
    loaded = _load_rows(
        args.input,
        default_market=args.default_market,
        default_timeframe=args.default_timeframe,
        feature_set_version=args.feature_set_version,
    )
    raw_rows = list(loaded.rows)
    universe_metadata = loaded.universe_metadata
    fetch_error_rows = loaded.fetch_error_rows
    started_at = datetime.now(timezone.utc)

    async with postgres_runtime(run_migrations=False) as runtime:
        repos = runtime["repositories"]
        service = SignalFeaturePipelineService(repos)
        batch_rows: list[SignalFeatureBatchRow] = []
        skipped_symbols: list[str] = []
        skipped_items: list[SignalFeatureBatchRunItemEntity] = []
        raw_row_by_symbol: dict[tuple[str, str, str], RawSignalInputRow] = {
            (row.symbol, row.market, row.timeframe): row
            for row in raw_rows
        }
        instrument_by_key: dict[tuple[str, str, str], InstrumentEntity] = {}

        for row in raw_rows:
            instrument = await repos.instruments.get_by_symbol(
                symbol=row.symbol,
                market_code=row.market,
            )
            if instrument is None:
                skipped_symbols.append(f"{row.symbol}:{row.market}:instrument_not_found")
                skipped_items.append(
                    SignalFeatureBatchRunItemEntity(
                        signal_feature_batch_run_item_id=uuid4(),
                        signal_feature_batch_run_id=uuid4(),
                        instrument_id=None,
                        symbol=row.symbol,
                        market_code=row.market,
                        timeframe=row.timeframe,
                        feature_set_version=row.feature_set_version,
                        status="skipped_instrument_not_found",
                        error_code="instrument_not_found",
                        error_message="instrument_not_found",
                        metadata_json={},
                    )
                )
                continue
            instrument_by_key[(row.symbol, row.market, row.timeframe)] = instrument
            batch_rows.append(
                SignalFeatureBatchRow(
                    instrument=instrument,
                    bars=row.bars,
                    timeframe=row.timeframe,
                    feature_set_version=row.feature_set_version,
                )
            )

        result = await service.compute_many(
            batch_rows,
            persist=not args.dry_run,
        )
        if skipped_symbols:
            result = SignalFeatureBatchResult(
                processed=result.processed + len(skipped_symbols),
                persisted=result.persisted,
                skipped=result.skipped + len(skipped_symbols),
                errors=result.errors + tuple(skipped_symbols),
                snapshots=result.snapshots,
            )

        batch_run = _build_batch_run_entity(
            input_path=args.input,
            loaded=loaded,
            result=result,
            dry_run=args.dry_run,
            trigger_type=args.trigger_type,
            started_at=started_at,
        )
        saved_batch_run = await repos.signal_feature_batch_runs.add(batch_run)
        run_items = _build_batch_run_items(
            batch_run_id=saved_batch_run.signal_feature_batch_run_id,
            loaded=loaded,
            result=result,
            skipped_items=skipped_items,
            raw_row_by_symbol=raw_row_by_symbol,
            instrument_by_key=instrument_by_key,
        )
        if run_items:
            await repos.signal_feature_batch_run_items.add_many(run_items)

    _print_result(result, output=args.output)
    return 0 if not result.errors else 1


def _build_batch_run_entity(
    *,
    input_path: str,
    loaded: LoadedSignalInput,
    result: SignalFeatureBatchResult,
    dry_run: bool,
    trigger_type: str,
    started_at: datetime,
) -> SignalFeatureBatchRunEntity:
    universe_metadata = loaded.universe_metadata
    fetch_error_rows = loaded.fetch_error_rows
    target_count = int(
        universe_metadata.get("universe_count")
        or len(universe_metadata.get("symbols", []))
        or len(loaded.rows)
    )
    fetch_error_count = len(fetch_error_rows)
    persist_error_count = len(result.errors)
    skipped_count = len(
        [error for error in result.errors if error.endswith("instrument_not_found")]
    )
    final_missing_count = fetch_error_count + persist_error_count
    status = "completed" if final_missing_count == 0 else "completed_with_errors"
    resolved_trigger_type = str(
        universe_metadata.get("trigger_type")
        or trigger_type
        or ("manual" if dry_run else "scheduler")
    )
    return SignalFeatureBatchRunEntity(
        signal_feature_batch_run_id=uuid4(),
        business_date=_resolve_business_date(loaded),
        universe_freeze_run_id=_parse_optional_uuid(
            universe_metadata.get("universe_freeze_run_id")
        ),
        trigger_type=resolved_trigger_type,
        timeframe=_first_value_or_default(loaded.rows, "timeframe", "1d"),
        feature_set_version=_first_value_or_default(
            loaded.rows,
            "feature_set_version",
            "signal_backbone_v1",
        ),
        input_uri=input_path,
        dry_run=dry_run,
        target_count=target_count,
        fetch_success_count=len(loaded.rows),
        fetch_error_count=fetch_error_count,
        persist_success_count=result.persisted,
        persist_error_count=persist_error_count,
        skipped_count=skipped_count,
        final_missing_count=final_missing_count,
        status=status,
        summary_json={
            "failed_symbols_sample": _collect_failed_symbols_sample(
                fetch_error_rows=fetch_error_rows,
                result=result,
            ),
            "universe_freeze_run_id": (
                str(universe_metadata.get("universe_freeze_run_id"))
                if universe_metadata.get("universe_freeze_run_id")
                else None
            ),
            "universe_freeze_reused": universe_metadata.get("universe_freeze_reused"),
            "trigger_type": resolved_trigger_type,
            "fetch_error_symbols": [
                str(item.get("symbol"))
                for item in fetch_error_rows[:20]
                if item.get("symbol")
            ],
        },
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
    )


def _build_batch_run_items(
    *,
    batch_run_id: UUID,
    loaded: LoadedSignalInput,
    result: SignalFeatureBatchResult,
    skipped_items: Sequence[SignalFeatureBatchRunItemEntity],
    raw_row_by_symbol: dict[tuple[str, str, str], RawSignalInputRow],
    instrument_by_key: dict[tuple[str, str, str], InstrumentEntity],
) -> tuple[SignalFeatureBatchRunItemEntity, ...]:
    items: list[SignalFeatureBatchRunItemEntity] = []
    snapshot_by_instrument: dict[UUID, Any] = {
        snapshot.instrument_id: snapshot for snapshot in result.snapshots
    }
    skipped_keys = {
        (item.symbol, item.market_code, item.timeframe)
        for item in skipped_items
    }
    for raw_row in loaded.rows:
        key = (raw_row.symbol, raw_row.market, raw_row.timeframe)
        instrument = instrument_by_key.get(key)
        instrument_id = instrument.instrument_id if instrument is not None else None
        snapshot = (
            snapshot_by_instrument.get(instrument_id)
            if instrument_id is not None
            else None
        )
        if snapshot is not None:
            items.append(
                SignalFeatureBatchRunItemEntity(
                    signal_feature_batch_run_item_id=uuid4(),
                    signal_feature_batch_run_id=batch_run_id,
                    instrument_id=instrument_id,
                    symbol=raw_row.symbol,
                    market_code=raw_row.market,
                    timeframe=raw_row.timeframe,
                    feature_set_version=raw_row.feature_set_version,
                    status="persisted" if result.persisted > 0 else "computed",
                    signal_feature_snapshot_id=snapshot.signal_feature_snapshot_id,
                    snapshot_at=snapshot.snapshot_at,
                    metadata_json={},
                )
            )
    for skipped_item in skipped_items:
        items.append(
            SignalFeatureBatchRunItemEntity(
                signal_feature_batch_run_item_id=uuid4(),
                signal_feature_batch_run_id=batch_run_id,
                instrument_id=skipped_item.instrument_id,
                symbol=skipped_item.symbol,
                market_code=skipped_item.market_code,
                timeframe=skipped_item.timeframe,
                feature_set_version=skipped_item.feature_set_version,
                status=skipped_item.status,
                error_code=skipped_item.error_code,
                error_message=skipped_item.error_message,
                metadata_json=skipped_item.metadata_json,
            )
        )
    for error in result.errors:
        symbol, market_code, timeframe, error_code, error_message = _parse_batch_error(error)
        if (symbol, market_code, timeframe) in skipped_keys:
            continue
        raw_row = raw_row_by_symbol.get((symbol, market_code, timeframe))
        if raw_row is None:
            raw_row = next(
                (
                    candidate
                    for candidate in raw_row_by_symbol.values()
                    if candidate.symbol == symbol and candidate.timeframe == timeframe
                ),
                None,
            )
        if raw_row is None:
            continue
        instrument = instrument_by_key.get(
            (raw_row.symbol, raw_row.market, raw_row.timeframe)
        )
        items.append(
            SignalFeatureBatchRunItemEntity(
                signal_feature_batch_run_item_id=uuid4(),
                signal_feature_batch_run_id=batch_run_id,
                instrument_id=instrument.instrument_id if instrument is not None else None,
                symbol=symbol,
                market_code=raw_row.market,
                timeframe=timeframe,
                feature_set_version=raw_row.feature_set_version,
                status="error",
                error_code=error_code,
                error_message=error_message,
                metadata_json={},
            )
        )
    for fetch_error in loaded.fetch_error_rows:
        items.append(
            SignalFeatureBatchRunItemEntity(
                signal_feature_batch_run_item_id=uuid4(),
                signal_feature_batch_run_id=batch_run_id,
                instrument_id=_parse_optional_uuid(fetch_error.get("instrument_id")),
                symbol=str(fetch_error.get("symbol", "")),
                market_code=str(fetch_error.get("market", "KRX")),
                timeframe=str(fetch_error.get("timeframe", "1d")),
                feature_set_version=str(
                    fetch_error.get("feature_set_version", "signal_backbone_v1")
                ),
                status="fetch_error",
                error_code=str(fetch_error.get("error_code", "fetch_error")),
                error_message=str(fetch_error.get("error_message", "fetch_error")),
                metadata_json={
                    key: value
                    for key, value in fetch_error.items()
                    if key
                    not in {
                        "instrument_id",
                        "symbol",
                        "market",
                        "timeframe",
                        "feature_set_version",
                        "error_code",
                        "error_message",
                    }
                },
            )
        )
    return tuple(items)


def _resolve_business_date(loaded: LoadedSignalInput) -> date:
    raw = loaded.universe_metadata.get("business_date")
    if isinstance(raw, str):
        return date.fromisoformat(raw)
    if loaded.rows:
        return loaded.rows[0].bars[-1].timestamp.date()
    return datetime.now(timezone.utc).date()


def _parse_optional_uuid(raw: object) -> UUID | None:
    if raw is None:
        return None
    try:
        return UUID(str(raw))
    except (TypeError, ValueError):
        return None


def _first_value_or_default(
    rows: Sequence[RawSignalInputRow],
    field_name: str,
    default: str,
) -> str:
    if not rows:
        return default
    return str(getattr(rows[0], field_name, default) or default)


def _collect_failed_symbols_sample(
    *,
    fetch_error_rows: Sequence[dict[str, object]],
    result: SignalFeatureBatchResult,
) -> list[str]:
    sample = [
        str(row.get("symbol"))
        for row in fetch_error_rows[:10]
        if row.get("symbol")
    ]
    for error in result.errors:
        symbol = error.split(":", 1)[0].strip()
        if symbol and symbol not in sample:
            sample.append(symbol)
        if len(sample) >= 10:
            break
    return sample


def _parse_batch_error(error: str) -> tuple[str, str, str, str, str]:
    parts = error.split(":", 2)
    if len(parts) == 3:
        symbol, middle, message = parts
        if middle == "KRX" or middle == "KOSPI" or middle == "KOSDAQ":
            return symbol, middle, "1d", "instrument_not_found", message
        return symbol, "KRX", middle, "compute_error", message
    if len(parts) == 2:
        return parts[0], "KRX", "1d", "compute_error", parts[1]
    return error, "KRX", "1d", "compute_error", error


def _print_result(
    result: SignalFeatureBatchResult,
    *,
    output: str,
) -> None:
    if output == "json":
        print(_result_to_json(result))
        return

    print("=== Signal Feature Snapshot Batch ===")
    print(f"processed: {result.processed}")
    print(f"persisted: {result.persisted}")
    print(f"skipped: {result.skipped}")
    print(f"errors: {len(result.errors)}")
    for snapshot in result.snapshots:
        print(
            f"- instrument_id={snapshot.instrument_id} "
            f"timeframe={snapshot.timeframe} "
            f"snapshot_at={snapshot.snapshot_at.isoformat()} "
            f"overall_score={snapshot.overall_score}"
        )
    for error in result.errors:
        print(f"! {error}")


def _result_to_json(result: SignalFeatureBatchResult) -> str:
    payload = {
        "processed": result.processed,
        "persisted": result.persisted,
        "skipped": result.skipped,
        "errors": list(result.errors),
        "snapshots": [
            {
                **asdict(snapshot),
                "signal_feature_snapshot_id": str(snapshot.signal_feature_snapshot_id),
                "instrument_id": str(snapshot.instrument_id),
                "snapshot_at": snapshot.snapshot_at.isoformat(),
                "created_at": (
                    snapshot.created_at.isoformat()
                    if snapshot.created_at is not None
                    else None
                ),
            }
            for snapshot in result.snapshots
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_run(_parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
