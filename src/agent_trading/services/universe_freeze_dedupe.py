from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import replace
from typing import TypeVar

from agent_trading.domain.entities import UniverseFreezeRunItemEntity

TUniverseSymbol = TypeVar("TUniverseSymbol")


def dedupe_universe_symbols_by_symbol_market(
    items: Iterable[TUniverseSymbol],
) -> tuple[tuple[TUniverseSymbol, ...], int]:
    """symbol/market 기준으로 순서를 유지하며 중복을 제거한다."""
    deduped: list[TUniverseSymbol] = []
    seen: set[tuple[str, str]] = set()
    skipped = 0
    for item in items:
        symbol = str(getattr(item, "symbol", "")).strip().upper()
        market = str(
            getattr(item, "market", getattr(item, "market_code", ""))
        ).strip().upper()
        key = (symbol, market)
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        deduped.append(item)
    return tuple(deduped), skipped


def dedupe_universe_freeze_run_items(
    items: Sequence[UniverseFreezeRunItemEntity],
) -> tuple[tuple[UniverseFreezeRunItemEntity, ...], int]:
    """freeze item 적재 직전에 중복 symbol/market, instrument를 제거한다."""
    deduped: list[UniverseFreezeRunItemEntity] = []
    seen_symbol_market: set[tuple[str, str]] = set()
    seen_instrument_ids: set[object] = set()
    skipped = 0
    next_rank = 1
    for item in items:
        symbol_key = (item.symbol.strip().upper(), item.market_code.strip().upper())
        instrument_key = item.instrument_id
        if symbol_key in seen_symbol_market or instrument_key in seen_instrument_ids:
            skipped += 1
            continue
        seen_symbol_market.add(symbol_key)
        seen_instrument_ids.add(instrument_key)
        deduped.append(replace(item, rank=next_rank))
        next_rank += 1
    return tuple(deduped), skipped
