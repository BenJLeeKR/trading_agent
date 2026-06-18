#!/usr/bin/env python3
"""JSON 일봉 입력으로 signal feature snapshot을 계산/적재한다."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

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
    return parser.parse_args(list(argv) if argv is not None else None)


def _load_rows(
    path: str,
    *,
    default_market: str,
    default_timeframe: str,
    feature_set_version: str,
) -> list[RawSignalInputRow]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("입력 JSON 최상위는 리스트여야 합니다.")

    rows: list[RawSignalInputRow] = []
    for item in raw:
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
            )
        )
    return rows


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
    raw_rows = _load_rows(
        args.input,
        default_market=args.default_market,
        default_timeframe=args.default_timeframe,
        feature_set_version=args.feature_set_version,
    )

    async with postgres_runtime(run_migrations=False) as runtime:
        repos = runtime["repositories"]
        service = SignalFeaturePipelineService(repos)
        batch_rows: list[SignalFeatureBatchRow] = []
        skipped_symbols: list[str] = []

        for row in raw_rows:
            instrument = await repos.instruments.get_by_symbol(
                symbol=row.symbol,
                market_code=row.market,
            )
            if instrument is None:
                skipped_symbols.append(f"{row.symbol}:{row.market}:instrument_not_found")
                continue
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

    _print_result(result, output=args.output)
    return 0 if not result.errors else 1


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
