#!/usr/bin/env python3
"""UNIV-1 진단용 read-only shadow 스크립트.

``UniverseSelectionService.compose_with_diagnostics()``를 실제 라이브
read-only KIS client(``_build_kis_live_quote_client``)로 직접 호출해,
market_overlay가 실제로 core 대비 새로운 심볼을 얼마나 편입하는지 확인한다.

DB에 어떤 것도 쓰지 않는다(freeze 생성/주문 제출 없음) — 순수 관측용.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("diagnose_market_overlay_shadow")


async def main() -> None:
    from agent_trading.config.settings import AppSettings
    from agent_trading.runtime.bootstrap import _build_kis_live_quote_client, postgres_runtime
    from agent_trading.services.universe_selection import UniverseSelectionService
    from agent_trading.services.universe_selection_types import CompositionContext

    settings = AppSettings()
    kis_client = _build_kis_live_quote_client(settings)
    print(f"kis_client: {kis_client!r}")
    print(f"kis_client.env: {getattr(kis_client, 'env', None)}")

    async with postgres_runtime(run_migrations=False) as runtime:
        repos = runtime["repositories"]
        selector = UniverseSelectionService(repos, kis_client=kis_client)

        ctx = CompositionContext(
            account_id=uuid4(),  # 보유 포지션 없는 더미 계좌 — held_position overlay는 0건이어야 정상
            since=datetime.now(timezone.utc) - timedelta(hours=24),
            max_cap=30,
            core_cap=None,
            market_overlay_cap=5,
            pre_pool_size=50,
        )

        selected, diagnostics = await selector.compose_with_diagnostics(ctx)

        by_source: dict[str, list[str]] = {}
        for item in selected:
            by_source.setdefault(item.source_type.value, []).append(item.symbol)

        print("=== source_type별 편입 종목 수 ===")
        for source_type, symbols in sorted(by_source.items()):
            print(f"  {source_type}: {len(symbols)}건 — {symbols}")

        print("\n=== market_overlay diagnostics ===")
        print(json.dumps(
            {
                "enabled": diagnostics.enabled,
                "skipped_reason": diagnostics.skipped_reason,
                "seed_pool_source": diagnostics.seed_pool_source,
                "effective_pre_pool_size": diagnostics.effective_pre_pool_size,
                "pre_pool_candidate_count": diagnostics.pre_pool_candidate_count,
                "quotes_requested_count": diagnostics.quotes_requested_count,
                "quotes_received_count": diagnostics.quotes_received_count,
                "filtered_out_count": diagnostics.filtered_out_count,
                "scored_candidate_count": diagnostics.scored_candidate_count,
                "added_count": diagnostics.added_count,
            },
            ensure_ascii=False,
            indent=2,
        ))

        core_symbols = set(by_source.get("core", []))
        overlay_symbols = set(by_source.get("market_overlay", []))
        new_vs_core = overlay_symbols - core_symbols

        print("\n=== market_overlay가 core 대비 실제로 새로 추가한 심볼 ===")
        print(f"  market_overlay 총 {len(overlay_symbols)}건 중 "
              f"core와 겹치지 않는 신규 {len(new_vs_core)}건: {sorted(new_vs_core)}")


if __name__ == "__main__":
    asyncio.run(main())
