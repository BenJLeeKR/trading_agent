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
import sys
from typing import Any, Sequence
from uuid import uuid4
from zoneinfo import ZoneInfo

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_trading.brokers.rate_limit import BudgetExhaustedError
from agent_trading.brokers.errors import BrokerError
from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.config.settings import AppSettings
from agent_trading.db.connection import DatabaseConfig, close_pool, create_pool
from agent_trading.db.transaction import transaction
from agent_trading.domain.enums import BrokerErrorType
from agent_trading.domain.entities import (
    UniverseFreezeRunEntity,
    UniverseFreezeRunItemEntity,
)
from agent_trading.repositories.contracts import AccountLookup
from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories
from agent_trading.runtime.bootstrap import _build_kis_live_quote_client
from agent_trading.services.signal_feature_batch_runtime import (
    DEFAULT_SIGNAL_FEATURE_AFTER_MARKET_FREEZE_PURPOSE,
    DEFAULT_SIGNAL_FEATURE_AFTER_MARKET_TRIGGER_TYPE,
)
from agent_trading.services.universe_selection import UniverseSelectionService
from agent_trading.services.universe_selection_types import (
    CompositionContext,
    FALLBACK_ACCOUNT_ID,
)
from scripts.run_decision_loop import (
    ACCOUNT_ALIAS,
    DEFAULT_EVENT_LOOKBACK_HOURS,
    UniverseSymbol,
)

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
DEFAULT_SIGNAL_FEATURE_FREEZE_PURPOSE = (
    DEFAULT_SIGNAL_FEATURE_AFTER_MARKET_FREEZE_PURPOSE
)
DEFAULT_SIGNAL_FEATURE_TRIGGER_TYPE = (
    DEFAULT_SIGNAL_FEATURE_AFTER_MARKET_TRIGGER_TYPE
)
DEFAULT_SIGNAL_FEATURE_SELECTION_VERSION = "universe_selection.freeze.v1"
DEFAULT_SIGNAL_FEATURE_UNIVERSE_MAX_CAP = 80
DEFAULT_SIGNAL_FEATURE_CORE_CAP = 80
DEFAULT_SIGNAL_FEATURE_MARKET_OVERLAY_CAP = 10
DEFAULT_SIGNAL_FEATURE_PRE_POOL_SIZE = 80
DEFAULT_SIGNAL_FEATURE_BATCH_SIZE = 15
DEFAULT_SIGNAL_FEATURE_BATCH_PAUSE_SECONDS = 1.0
DEFAULT_SIGNAL_FEATURE_BUDGET_RETRY_ATTEMPTS = 6
DEFAULT_SIGNAL_FEATURE_BUDGET_RETRY_SLEEP_SECONDS = 1.0
DEFAULT_SIGNAL_FEATURE_TRANSIENT_RETRY_ATTEMPTS = 3
DEFAULT_SIGNAL_FEATURE_TRANSIENT_RETRY_SLEEP_SECONDS = 1.5
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


@dataclass(slots=True, frozen=True)
class SignalFeatureFetchError:
    symbol: str
    market: str
    error_code: str
    error_message: str


@dataclass(slots=True, frozen=True)
class UniverseFreezeResolution:
    universe_freeze_run_id: str
    universe: tuple[UniverseSymbol, ...]
    reused_existing: bool
    errors: tuple[str, ...] = ()


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
        "--freeze-purpose",
        default=DEFAULT_SIGNAL_FEATURE_FREEZE_PURPOSE,
        help="universe freeze purpose 값",
    )
    parser.add_argument(
        "--trigger-type",
        default=DEFAULT_SIGNAL_FEATURE_TRIGGER_TYPE,
        help="batch run trigger_type 값",
    )
    parser.add_argument(
        "--retry-from-input",
        default=None,
        help="기존 signal_feature_input.v2 JSON 경로. 지정 시 fetch_error_rows만 재시도",
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
    parser.add_argument(
        "--transient-retry-attempts",
        type=int,
        default=DEFAULT_SIGNAL_FEATURE_TRANSIENT_RETRY_ATTEMPTS,
        help="timeout / 5xx / retryable broker 오류 재시도 횟수",
    )
    parser.add_argument(
        "--transient-retry-sleep-seconds",
        type=float,
        default=DEFAULT_SIGNAL_FEATURE_TRANSIENT_RETRY_SLEEP_SECONDS,
        help="transient broker 오류 재시도 기본 대기 시간(초)",
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
    transient_retry_attempts: int = DEFAULT_SIGNAL_FEATURE_TRANSIENT_RETRY_ATTEMPTS,
    transient_retry_sleep_seconds: float = DEFAULT_SIGNAL_FEATURE_TRANSIENT_RETRY_SLEEP_SECONDS,
) -> tuple[list[SignalFeatureInputRow], list[SignalFeatureFetchError]]:
    start_date = end_date - timedelta(days=lookback_days)
    start_date_str = start_date.strftime("%Y%m%d")
    end_date_str = end_date.strftime("%Y%m%d")

    rows: list[SignalFeatureInputRow] = []
    errors: list[SignalFeatureFetchError] = []
    normalized_batch_size = batch_size if batch_size > 0 else 0
    normalized_batch_pause_seconds = max(0.0, batch_pause_seconds)
    normalized_budget_retry_attempts = max(1, budget_retry_attempts)
    normalized_budget_retry_sleep_seconds = max(0.1, budget_retry_sleep_seconds)
    normalized_transient_retry_attempts = max(1, transient_retry_attempts)
    normalized_transient_retry_sleep_seconds = max(0.1, transient_retry_sleep_seconds)

    for index, item in enumerate(universe, start=1):
        normalized_market = str(item.market or "").strip().upper()
        if normalized_market not in _SUPPORTED_SIGNAL_FEATURE_MARKETS:
            errors.append(
                SignalFeatureFetchError(
                    symbol=item.symbol,
                    market=str(item.market),
                    error_code="unsupported_market",
                    error_message="지원하지 않는 market 코드",
                )
            )
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
                transient_retry_attempts=normalized_transient_retry_attempts,
                transient_retry_sleep_seconds=normalized_transient_retry_sleep_seconds,
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
                errors.append(
                    SignalFeatureFetchError(
                        symbol=item.symbol,
                        market=normalized_market,
                        error_code="insufficient_bars",
                        error_message=f"insufficient_bars={len(bars)}",
                    )
                )
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
            error_code, error_message = _classify_signal_feature_fetch_error(exc)
            errors.append(
                SignalFeatureFetchError(
                    symbol=item.symbol,
                    market=normalized_market,
                    error_code=error_code,
                    error_message=error_message,
                )
            )
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
    transient_retry_attempts: int,
    transient_retry_sleep_seconds: float,
) -> list[dict[str, Any]]:
    max_attempts = max(budget_retry_attempts, transient_retry_attempts)
    for attempt in range(1, max_attempts + 1):
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
        except Exception as exc:
            retry_code, retry_message = _classify_retryable_signal_feature_fetch_exception(exc)
            if retry_code is None or attempt >= transient_retry_attempts:
                raise
            wait_seconds = normalized_retry_sleep_seconds(
                transient_retry_sleep_seconds,
                attempt=attempt,
            )
            logger.info(
                "signal feature 입력 생성 transient 재시도: symbol=%s code=%s attempt=%s/%s sleep=%.2fs msg=%s",
                symbol,
                retry_code,
                attempt,
                transient_retry_attempts,
                wait_seconds,
                retry_message,
            )
            await asyncio.sleep(wait_seconds)
    return []


def normalized_retry_sleep_seconds(base_seconds: float, *, attempt: int) -> float:
    normalized_base_seconds = max(0.1, base_seconds)
    return normalized_base_seconds * float(attempt)


def _classify_retryable_signal_feature_fetch_exception(
    exc: Exception,
) -> tuple[str | None, str]:
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout", "asyncio timeout"
    if isinstance(exc, BrokerError):
        raw_message = str(exc.raw_message or exc)
        if exc.error_type == BrokerErrorType.RATE_LIMIT:
            return "rate_limit", raw_message
        if exc.error_type == BrokerErrorType.TIMEOUT:
            return "timeout", raw_message
        if exc.error_type == BrokerErrorType.TEMPORARY_BROKER:
            return "temporary_broker", raw_message
        if exc.retryable and _looks_like_http_5xx(raw_message):
            return "http_5xx", raw_message
        if exc.retryable and exc.error_type == BrokerErrorType.API_ERROR:
            return "retryable_api_error", raw_message
    return None, str(exc)


def _classify_signal_feature_fetch_error(exc: Exception) -> tuple[str, str]:
    retry_code, retry_message = _classify_retryable_signal_feature_fetch_exception(exc)
    if retry_code is not None:
        return retry_code, retry_message
    if isinstance(exc, BudgetExhaustedError):
        return f"budget_exhausted_{exc.bucket}", str(exc)
    return type(exc).__name__, str(exc)


def _looks_like_http_5xx(message: str) -> bool:
    normalized = str(message or "").lower()
    return (
        "http 500" in normalized
        or "http 502" in normalized
        or "http 503" in normalized
        or "http 504" in normalized
        or "non-json response (http 5" in normalized
    )


def _write_rows(
    path: str,
    rows: Sequence[SignalFeatureInputRow],
    *,
    fetch_errors: Sequence[SignalFeatureFetchError] | None = None,
    universe: Sequence[UniverseSymbol] | None = None,
    universe_freeze_run_id: str | None = None,
    universe_freeze_reused: bool | None = None,
    freeze_purpose: str | None = None,
    trigger_type: str | None = None,
    generated_at: str | None = None,
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "signal_feature_input.v2",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "universe_metadata": {
            "universe_freeze_run_id": universe_freeze_run_id,
            "universe_freeze_reused": universe_freeze_reused,
            "freeze_purpose": freeze_purpose,
            "trigger_type": trigger_type,
            "universe_count": len(universe or ()),
            "symbols": [
                {
                    "symbol": item.symbol,
                    "market": item.market,
                    "source_type": item.source_type,
                    "inclusion_reason": item.inclusion_reason,
                }
                for item in (universe or ())
            ],
        },
        "fetch_success_rows": [asdict(row) for row in rows],
        "fetch_error_rows": [asdict(error) for error in (fetch_errors or ())],
    }
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_retry_universe_from_input(
    path: str,
) -> tuple[
    tuple[UniverseSymbol, ...],
    str | None,
    bool | None,
    str | None,
    str | None,
]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("retry-from-input 은 signal_feature_input.v2 객체여야 합니다.")

    universe_metadata = raw.get("universe_metadata")
    if not isinstance(universe_metadata, dict):
        raise ValueError("retry-from-input 에 universe_metadata 객체가 필요합니다.")

    error_rows = raw.get("fetch_error_rows")
    if not isinstance(error_rows, list):
        raise ValueError("retry-from-input 에 fetch_error_rows 리스트가 필요합니다.")

    symbol_metadata_map: dict[tuple[str, str], dict[str, Any]] = {}
    raw_symbols = universe_metadata.get("symbols")
    if isinstance(raw_symbols, list):
        for item in raw_symbols:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol", "")).strip()
            market = str(item.get("market", "")).strip().upper()
            if not symbol or not market:
                continue
            symbol_metadata_map[(symbol, market)] = item

    seen: set[tuple[str, str]] = set()
    retry_universe: list[UniverseSymbol] = []
    for item in error_rows:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol", "")).strip()
        market = str(item.get("market", "")).strip().upper()
        if not symbol or not market:
            continue
        key = (symbol, market)
        if key in seen:
            continue
        seen.add(key)
        metadata = symbol_metadata_map.get(key, {})
        retry_universe.append(
            UniverseSymbol(
                symbol=symbol,
                market=market,
                source_type=str(metadata.get("source_type") or "tail_retry"),
                inclusion_reason=str(
                    metadata.get("inclusion_reason") or "signal_feature_tail_retry"
                ),
            )
        )

    return (
        tuple(retry_universe),
        (
            str(universe_metadata.get("universe_freeze_run_id"))
            if universe_metadata.get("universe_freeze_run_id")
            else None
        ),
        (
            bool(universe_metadata.get("universe_freeze_reused"))
            if universe_metadata.get("universe_freeze_reused") is not None
            else None
        ),
        (
            str(universe_metadata.get("freeze_purpose"))
            if universe_metadata.get("freeze_purpose")
            else None
        ),
        (
            str(universe_metadata.get("trigger_type"))
            if universe_metadata.get("trigger_type")
            else None
        ),
    )


async def _resolve_frozen_universe(
    *,
    repos: Any,
    end_date: date,
    freeze_purpose: str,
    universe_max_cap: int,
    core_cap: int,
    market_overlay_cap: int,
    pre_pool_size: int,
) -> UniverseFreezeResolution:
    existing_run = await repos.universe_freeze_runs.get_latest(
        end_date,
        freeze_purpose,
    )
    if existing_run is not None:
        existing_items = await repos.universe_freeze_run_items.list_by_run(
            existing_run.universe_freeze_run_id,
        )
        if existing_items:
            return UniverseFreezeResolution(
                universe_freeze_run_id=str(existing_run.universe_freeze_run_id),
                universe=tuple(
                    UniverseSymbol(
                        symbol=item.symbol,
                        market=item.market_code,
                        source_type=item.source_type,
                        inclusion_reason=item.inclusion_reason,
                    )
                    for item in existing_items
                ),
                reused_existing=True,
            )

    # 장후 feature 배치는 이미 장이 종료된 뒤 실행되므로,
    # 여기서 live market_overlay를 다시 구성하면 quote/budget 대기로
    # 입력 생성 전체가 timeout되기 쉽다.
    # 또한 run_decision_loop._read_trading_universe()는 내부에서
    # postgres_runtime()를 다시 열어 nested pool shutdown 지연을 유발할 수 있다.
    # 따라서 현재 transaction에 연결된 repos만 사용해 universe를 직접 compose한다.
    account_id = FALLBACK_ACCOUNT_ID
    try:
        account = await repos.accounts.find_one(
            AccountLookup(account_alias=ACCOUNT_ALIAS)
        )
        if account is not None:
            account_id = account.account_id
    except Exception:
        logger.warning(
            "signal feature freeze account lookup failed — fallback account 사용"
        )

    selector = UniverseSelectionService(
        repos,
        kis_client=None,
    )
    composition_context = CompositionContext(
        account_id=account_id,
        since=datetime.now(timezone.utc) - timedelta(hours=DEFAULT_EVENT_LOOKBACK_HOURS),
        max_cap=universe_max_cap,
        core_cap=core_cap,
        exclude_held_from_cap=True,
        market_overlay_cap=0,
        pre_pool_size=0,
    )
    selected = await selector.compose(composition_context)
    composed_universe = tuple(
        UniverseSymbol(
            symbol=item.symbol,
            market=item.market,
            source_type=item.source_type.value,
            inclusion_reason=item.inclusion_reason,
        )
        for item in selected
    )

    freeze_run_id = uuid4()
    freeze_items: list[UniverseFreezeRunItemEntity] = []
    errors: list[str] = []
    for rank, item in enumerate(composed_universe, start=1):
        instrument = await repos.instruments.get_by_symbol(
            symbol=item.symbol,
            market_code=item.market,
        )
        if instrument is None:
            errors.append(f"{item.symbol}:{item.market}:instrument_not_found_for_freeze")
            continue
        freeze_items.append(
            UniverseFreezeRunItemEntity(
                universe_freeze_run_item_id=uuid4(),
                universe_freeze_run_id=freeze_run_id,
                instrument_id=instrument.instrument_id,
                symbol=item.symbol,
                market_code=item.market,
                source_type=item.source_type,
                inclusion_reason=item.inclusion_reason,
                rank=rank,
                cap_bucket=item.source_type,
                metadata_json={},
            )
        )

    if not freeze_items:
        raise RuntimeError("universe_freeze_materialization_failed:no_items")

    freeze_sequence = 1 if existing_run is None else existing_run.freeze_sequence + 1
    freeze_run = UniverseFreezeRunEntity(
        universe_freeze_run_id=freeze_run_id,
        business_date=end_date,
        freeze_purpose=freeze_purpose,
        freeze_sequence=freeze_sequence,
        frozen_at=datetime.now(timezone.utc),
        selection_version=DEFAULT_SIGNAL_FEATURE_SELECTION_VERSION,
        selection_params_json={
            "universe_max_cap": universe_max_cap,
            "core_cap": core_cap,
            "market_overlay_cap": market_overlay_cap,
            "pre_pool_size": pre_pool_size,
        },
        target_count=len(freeze_items),
        status="materialized",
    )
    await repos.universe_freeze_runs.add(freeze_run)
    await repos.universe_freeze_run_items.add_many(freeze_items)

    return UniverseFreezeResolution(
        universe_freeze_run_id=str(freeze_run_id),
        universe=tuple(
            UniverseSymbol(
                symbol=item.symbol,
                market=item.market_code,
                source_type=item.source_type,
                inclusion_reason=item.inclusion_reason,
            )
            for item in freeze_items
        ),
        reused_existing=False,
        errors=tuple(errors),
    )


async def _run(args: argparse.Namespace) -> int:
    end_date = _parse_end_date(args.end_date)
    retry_source_input = str(args.retry_from_input).strip() if args.retry_from_input else None
    if retry_source_input:
        (
            retry_universe,
            retry_freeze_run_id,
            retry_freeze_reused,
            retry_freeze_purpose,
            retry_trigger_type,
        ) = _load_retry_universe_from_input(retry_source_input)
        freeze = UniverseFreezeResolution(
            universe_freeze_run_id=retry_freeze_run_id or f"retry:{end_date.isoformat()}",
            universe=retry_universe,
            reused_existing=bool(retry_freeze_reused),
        )
        freeze_purpose = retry_freeze_purpose or args.freeze_purpose
        trigger_type = retry_trigger_type or args.trigger_type
    else:
        await create_pool(DatabaseConfig())
        try:
            async with transaction() as tx:
                repos = build_postgres_repositories(tx)
                freeze = await _resolve_frozen_universe(
                    repos=repos,
                    end_date=end_date,
                    freeze_purpose=args.freeze_purpose,
                    universe_max_cap=args.universe_max_cap,
                    core_cap=args.core_cap,
                    market_overlay_cap=args.market_overlay_cap,
                    pre_pool_size=args.pre_pool_size,
                )
        finally:
            try:
                await asyncio.wait_for(close_pool(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(
                    "signal feature input DB pool close timeout — "
                    "process exit에 정리를 위임합니다."
                )
        freeze_purpose = args.freeze_purpose
        trigger_type = args.trigger_type
    settings = AppSettings()
    client = _build_chart_client(settings)
    try:
        rows, errors = await _build_rows(
            client,
            universe=freeze.universe,
            end_date=end_date,
            lookback_days=args.lookback_days,
            timeframe=args.timeframe,
            feature_set_version=args.feature_set_version,
            batch_size=args.batch_size,
            batch_pause_seconds=args.batch_pause_seconds,
            budget_retry_attempts=args.budget_retry_attempts,
            budget_retry_sleep_seconds=args.budget_retry_sleep_seconds,
            transient_retry_attempts=args.transient_retry_attempts,
            transient_retry_sleep_seconds=args.transient_retry_sleep_seconds,
        )
    finally:
        await client.close()

    all_errors = list(freeze.errors) + [
        f"{error.symbol}:{error.market}:{error.error_code}:{error.error_message}"
        for error in errors
    ]
    _write_rows(
        args.output,
        rows,
        fetch_errors=errors,
        universe=freeze.universe,
        universe_freeze_run_id=freeze.universe_freeze_run_id,
        universe_freeze_reused=freeze.reused_existing,
        freeze_purpose=freeze_purpose,
        trigger_type=trigger_type,
    )
    payload = {
        "output": args.output,
        "universe_count": len(freeze.universe),
        "generated_count": len(rows),
        "error_count": len(all_errors),
        "universe_max_cap": args.universe_max_cap,
        "market_overlay_cap": args.market_overlay_cap,
        "pre_pool_size": args.pre_pool_size,
        "universe_freeze_run_id": freeze.universe_freeze_run_id,
        "universe_freeze_reused": freeze.reused_existing,
        "freeze_purpose": freeze_purpose,
        "trigger_type": trigger_type,
        "fetch_success_count": len(rows),
        "fetch_error_count": len(errors),
        "retry_mode": bool(retry_source_input),
        "retry_source_input": retry_source_input,
        "errors": all_errors,
    }
    if args.output_format == "json":
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print("=== Signal Feature Snapshot Input Generation ===")
        print(f"output: {args.output}")
        print(f"universe_count: {len(freeze.universe)}")
        print(f"generated_count: {len(rows)}")
        print(f"error_count: {len(all_errors)}")
        print(f"universe_max_cap: {args.universe_max_cap}")
        print(f"market_overlay_cap: {args.market_overlay_cap}")
        print(f"pre_pool_size: {args.pre_pool_size}")
        print(f"universe_freeze_run_id: {freeze.universe_freeze_run_id}")
        print(f"universe_freeze_reused: {freeze.reused_existing}")
        print(f"freeze_purpose: {freeze_purpose}")
        print(f"trigger_type: {trigger_type}")
        print(f"retry_mode: {bool(retry_source_input)}")
        for error in all_errors:
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
