#!/usr/bin/env python3
"""유니버스 기반 signal feature snapshot 입력 JSON 생성."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from agent_trading.brokers.rate_limit import BudgetExhaustedError
from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.config.settings import AppSettings
from agent_trading.runtime.bootstrap import _build_kis_live_quote_client
from scripts.run_decision_loop import UniverseSymbol, _read_trading_universe

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
DEFAULT_SIGNAL_FEATURE_UNIVERSE_MAX_CAP = 80
DEFAULT_SIGNAL_FEATURE_CORE_CAP = 80
DEFAULT_SIGNAL_FEATURE_MARKET_OVERLAY_CAP = 10
DEFAULT_SIGNAL_FEATURE_PRE_POOL_SIZE = 80
DEFAULT_SIGNAL_FEATURE_BATCH_SIZE = 15
DEFAULT_SIGNAL_FEATURE_BATCH_PAUSE_SECONDS = 1.0
DEFAULT_SIGNAL_FEATURE_BUDGET_RETRY_ATTEMPTS = 6
DEFAULT_SIGNAL_FEATURE_BUDGET_RETRY_SLEEP_SECONDS = 1.0
_SUPPORTED_SIGNAL_FEATURE_MARKETS: frozenset[str] = frozenset({
    "KRX",
    "KOSPI",
    "KOSDAQ",
})


@dataclass(slots=True, frozen=True)
class SignalFeatureInputBar:
    timestamp: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    turnover: float | None = None


@dataclass(slots=True, frozen=True)
class SignalFeatureInputRow:
    symbol: str
    market: str
    timeframe: str
    feature_set_version: str
    bars: tuple[SignalFeatureInputBar, ...]


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Signal feature snapshot 입력 JSON 생성",
    )
    parser.add_argument(
        "--output",
        default="data/signal_feature_snapshot_input.json",
        help="생성할 입력 JSON 파일 경로",
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="조회 종료일자 YYYY-MM-DD 또는 YYYYMMDD (기본: 오늘 KST)",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=180,
        help="시작일 산출용 calendar lookback days",
    )
    parser.add_argument(
        "--timeframe",
        default="1d",
        help="출력 timeframe",
    )
    parser.add_argument(
        "--feature-set-version",
        default="signal_backbone_v1",
        help="출력 feature_set_version",
    )
    parser.add_argument(
        "--universe-max-cap",
        type=int,
        default=DEFAULT_SIGNAL_FEATURE_UNIVERSE_MAX_CAP,
        help="feature 배치용 trading universe non-held cap",
    )
    parser.add_argument(
        "--core-cap",
        type=int,
        default=DEFAULT_SIGNAL_FEATURE_CORE_CAP,
        help="feature 배치용 core source_type cap",
    )
    parser.add_argument(
        "--market-overlay-cap",
        type=int,
        default=DEFAULT_SIGNAL_FEATURE_MARKET_OVERLAY_CAP,
        help="feature 배치용 market overlay cap",
    )
    parser.add_argument(
        "--pre-pool-size",
        type=int,
        default=DEFAULT_SIGNAL_FEATURE_PRE_POOL_SIZE,
        help="feature 배치용 market overlay pre-pool size",
    )
    parser.add_argument(
        "--output-format",
        choices=("text", "json"),
        default="text",
        help="stdout 출력 형식",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_SIGNAL_FEATURE_BATCH_SIZE,
        help="이 수량마다 batch pause 적용 (0 이하면 비활성화)",
    )
    parser.add_argument(
        "--batch-pause-seconds",
        type=float,
        default=DEFAULT_SIGNAL_FEATURE_BATCH_PAUSE_SECONDS,
        help="batch-size 단위 대기 시간(초)",
    )
    parser.add_argument(
        "--budget-retry-attempts",
        type=int,
        default=DEFAULT_SIGNAL_FEATURE_BUDGET_RETRY_ATTEMPTS,
        help="market_data/global budget exhaustion 재시도 횟수",
    )
    parser.add_argument(
        "--budget-retry-sleep-seconds",
        type=float,
        default=DEFAULT_SIGNAL_FEATURE_BUDGET_RETRY_SLEEP_SECONDS,
        help="budget exhaustion 재시도 기본 대기 시간(초)",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _parse_end_date(raw: str | None) -> date:
    if raw is None or not raw.strip():
        return datetime.now(KST).date()
    value = raw.strip()
    if len(value) == 8 and value.isdigit():
        return date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:8]}")
    return date.fromisoformat(value)


def _build_chart_client(settings: AppSettings) -> KISRestClient:
    """Signal feature 입력 생성은 항상 live market data client를 사용한다."""
    client = _build_kis_live_quote_client(settings)
    if client is None:
        raise RuntimeError(
            "live_market_data_client_not_configured: "
            "KIS_LIVE_INFO_APP_KEY / KIS_LIVE_INFO_APP_SECRET 설정이 필요합니다."
        )
    return client


def _normalize_bar(raw: dict[str, Any]) -> SignalFeatureInputBar:
    bsop_date = str(raw.get("stck_bsop_date", "")).strip()
    if len(bsop_date) != 8:
        raise ValueError(f"invalid stck_bsop_date={bsop_date!r}")
    timestamp = datetime(
        year=int(bsop_date[:4]),
        month=int(bsop_date[4:6]),
        day=int(bsop_date[6:8]),
        tzinfo=timezone.utc,
    ).isoformat()
    turnover_raw = raw.get("acml_tr_pbmn")
    return SignalFeatureInputBar(
        timestamp=timestamp,
        open_price=float(raw.get("stck_oprc", 0) or 0),
        high_price=float(raw.get("stck_hgpr", 0) or 0),
        low_price=float(raw.get("stck_lwpr", 0) or 0),
        close_price=float(raw.get("stck_clpr", 0) or 0),
        volume=float(raw.get("acml_vol", 0) or 0),
        turnover=float(turnover_raw) if turnover_raw not in (None, "") else None,
    )


async def _build_rows(
    client: KISRestClient,
    *,
    universe: Sequence[UniverseSymbol],
    end_date: date,
    lookback_days: int,
    timeframe: str,
    feature_set_version: str,
    batch_size: int = DEFAULT_SIGNAL_FEATURE_BATCH_SIZE,
    batch_pause_seconds: float = DEFAULT_SIGNAL_FEATURE_BATCH_PAUSE_SECONDS,
    budget_retry_attempts: int = DEFAULT_SIGNAL_FEATURE_BUDGET_RETRY_ATTEMPTS,
    budget_retry_sleep_seconds: float = DEFAULT_SIGNAL_FEATURE_BUDGET_RETRY_SLEEP_SECONDS,
) -> tuple[list[SignalFeatureInputRow], list[str]]:
    start_date = end_date - timedelta(days=lookback_days)
    start_date_str = start_date.strftime("%Y%m%d")
    end_date_str = end_date.strftime("%Y%m%d")

    rows: list[SignalFeatureInputRow] = []
    errors: list[str] = []
    normalized_batch_size = batch_size if batch_size > 0 else 0
    normalized_batch_pause_seconds = max(0.0, batch_pause_seconds)
    normalized_budget_retry_attempts = max(1, budget_retry_attempts)
    normalized_budget_retry_sleep_seconds = max(0.1, budget_retry_sleep_seconds)

    for index, item in enumerate(universe, start=1):
        normalized_market = str(item.market or "").strip().upper()
        if normalized_market not in _SUPPORTED_SIGNAL_FEATURE_MARKETS:
            errors.append(f"{item.symbol}:{item.market}:unsupported_market")
            continue
        try:
            raw_bars = await _fetch_daily_bars_with_budget_retry(
                client=client,
                symbol=item.symbol,
                market=normalized_market,
                start_date=start_date_str,
                end_date=end_date_str,
                budget_retry_attempts=normalized_budget_retry_attempts,
                budget_retry_sleep_seconds=normalized_budget_retry_sleep_seconds,
            )
            bars = tuple(
                _normalize_bar(raw)
                for raw in sorted(
                    raw_bars,
                    key=lambda x: str(x.get("stck_bsop_date", "")),
                )
                if isinstance(raw, dict)
            )
            if len(bars) < 20:
                errors.append(f"{item.symbol}:{item.market}:insufficient_bars={len(bars)}")
                continue
            rows.append(
                SignalFeatureInputRow(
                    symbol=item.symbol,
                    market=normalized_market,
                    timeframe=timeframe,
                    feature_set_version=feature_set_version,
                    bars=bars,
                )
            )
        except Exception as exc:
            errors.append(f"{item.symbol}:{item.market}:{type(exc).__name__}:{exc}")
        if (
            normalized_batch_size > 0
            and normalized_batch_pause_seconds > 0
            and index < len(universe)
            and index % normalized_batch_size == 0
        ):
            logger.info(
                "signal feature 입력 생성 batch pause: processed=%s/%s sleep=%.2fs",
                index,
                len(universe),
                normalized_batch_pause_seconds,
            )
            await asyncio.sleep(normalized_batch_pause_seconds)
    return rows, errors


def _estimate_budget_retry_sleep_seconds(
    client: KISRestClient,
    minimum_seconds: float,
) -> float:
    budget_manager = getattr(client, "budget_manager", None)
    if budget_manager is None:
        return minimum_seconds

    candidates = [minimum_seconds]
    market_data = getattr(budget_manager, "market_data", None)
    refill_rate = float(getattr(market_data, "refill_rate", 0.0) or 0.0)
    if refill_rate > 0:
        candidates.append(1.0 / refill_rate)

    global_rest = getattr(budget_manager, "global_rest", None)
    global_refill_rate = float(getattr(global_rest, "refill_rate", 0.0) or 0.0)
    if global_refill_rate > 0:
        candidates.append(1.0 / global_refill_rate)

    return max(candidates)


async def _fetch_daily_bars_with_budget_retry(
    *,
    client: KISRestClient,
    symbol: str,
    market: str,
    start_date: str,
    end_date: str,
    budget_retry_attempts: int,
    budget_retry_sleep_seconds: float,
) -> list[dict[str, Any]]:
    for attempt in range(1, budget_retry_attempts + 1):
        try:
            return await client.inquire_daily_itemchartprice(
                symbol=symbol,
                market_code=market,
                start_date=start_date,
                end_date=end_date,
                period_div_code="D",
                adjusted_price=True,
            )
        except BudgetExhaustedError as exc:
            if exc.bucket not in {"market_data", "global"} or attempt >= budget_retry_attempts:
                raise
            wait_seconds = _estimate_budget_retry_sleep_seconds(
                client,
                budget_retry_sleep_seconds,
            )
            logger.info(
                "signal feature 입력 생성 budget 대기: symbol=%s bucket=%s attempt=%s/%s sleep=%.2fs",
                symbol,
                exc.bucket,
                attempt,
                budget_retry_attempts,
                wait_seconds,
            )
            await asyncio.sleep(wait_seconds)
    return []


def _write_rows(path: str, rows: Sequence[SignalFeatureInputRow]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def _run(args: argparse.Namespace) -> int:
    settings = AppSettings()
    universe = await _read_trading_universe(
        max_cap=args.universe_max_cap,
        core_cap=args.core_cap,
        market_overlay_cap=args.market_overlay_cap,
        pre_pool_size=args.pre_pool_size,
    )
    end_date = _parse_end_date(args.end_date)
    client = _build_chart_client(settings)
    try:
        rows, errors = await _build_rows(
            client,
            universe=universe,
            end_date=end_date,
            lookback_days=args.lookback_days,
            timeframe=args.timeframe,
            feature_set_version=args.feature_set_version,
            batch_size=args.batch_size,
            batch_pause_seconds=args.batch_pause_seconds,
            budget_retry_attempts=args.budget_retry_attempts,
            budget_retry_sleep_seconds=args.budget_retry_sleep_seconds,
        )
    finally:
        await client.close()

    _write_rows(args.output, rows)
    payload = {
        "output": args.output,
        "universe_count": len(universe),
        "generated_count": len(rows),
        "error_count": len(errors),
        "universe_max_cap": args.universe_max_cap,
        "market_overlay_cap": args.market_overlay_cap,
        "pre_pool_size": args.pre_pool_size,
        "errors": errors,
    }
    if args.output_format == "json":
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print("=== Signal Feature Snapshot Input Generation ===")
        print(f"output: {args.output}")
        print(f"universe_count: {len(universe)}")
        print(f"generated_count: {len(rows)}")
        print(f"error_count: {len(errors)}")
        print(f"universe_max_cap: {args.universe_max_cap}")
        print(f"market_overlay_cap: {args.market_overlay_cap}")
        print(f"pre_pool_size: {args.pre_pool_size}")
        for error in errors:
            print(f"! {error}")
    return 0 if rows else 1


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] signal-feature-input: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    args = _parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
