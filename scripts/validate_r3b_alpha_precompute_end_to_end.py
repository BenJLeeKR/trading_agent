#!/usr/bin/env python3
"""SPPV-2.69 — R3b alpha cycle precompute 실제 발동 검증(read-only,
신규 KIS 호출 0건, `.env` 미변경).

`scripts/run_decision_loop.py`의 `_build_r3b_alpha_percentile_
overrides_for_cycle()`(cycle당 1회 precompute, SPPV-2.69 신규)이
실제로 (1) 호출되고, (2) 결과 percentile을 계산하고, (3) 그 값이
`decision_orchestrator.py`/`deterministic_trigger_engine.py` 배선을
거쳐 실제 entry_score에 반영되는지를 두 단계로 나눠 직접 실행 검증한다.

**1단계 — precompute 함수 자체(FakeRepos, DB 불필요)**: 실제 DB에는
core 종목 신호 스냅샷은 있지만 벤치마크(069500) 스냅샷이 아직 없어,
`_build_r3b_alpha_percentile_overrides_for_cycle()`을 그대로 호출하면
벤치마크 조회 단계에서 조기 종료된다. 이 스크립트는 `repos` 인자를
받는 이 함수의 실제 프로덕션 코드를 그대로 호출하되, `repos.
instruments`/`repos.signal_feature_snapshots`만 최소 stub으로
대체해 "cycle마다 universe 전체를 순회해 candidate_percentile을
실제로 계산하는" 로직 자체를 실행 증거로 남긴다 — `build_candidate_
percentiles()` 알고리즘은 SPPV-2.67에서 이미 200회 무작위 trial로
검증됐으므로 이 스크립트는 그 함수를 재검증하지 않고 "실제로
호출되는지, 결과가 올바른 형태로 나오는지"만 확인한다.

**2단계 — orchestrator→engine 반영(실제 DB)**: 실제 core 종목 하나를
골라, (a) `.env` 그대로(`entry_score_r3b_alpha_enabled=False`)일 때와
(b) 이 프로세스에서만 `os.environ`으로 일시적으로 활성화했을 때
`DecisionOrchestratorService.derive_deterministic_trigger_for_
request()`가 반환하는 entry_score/reason_codes를 비교한다.

DB write / 주문 경로 / 실시간 구독 / broker submit 없음. `.env`
파일은 전혀 수정하지 않는다(같은 프로세스의 `os.environ`만 일시
조작 — 스크립트 종료와 함께 사라진다).
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from decimal import Decimal

sys.path.insert(0, "scripts")
sys.path.insert(0, "src")


@dataclass
class _FakeInstrument:
    instrument_id: str
    symbol: str


@dataclass
class _FakeSnapshot:
    return_1m_pct: float | None
    return_3m_pct: float | None
    volatility_20d_pct: float | None


class _FakeInstrumentsRepo:
    def __init__(self, by_symbol: dict[str, _FakeInstrument]):
        self._by_symbol = by_symbol

    async def get_by_symbol(self, *, symbol: str, market_code: str):
        return self._by_symbol.get(symbol)


class _FakeSnapshotsRepo:
    def __init__(self, by_instrument_id: dict[str, _FakeSnapshot]):
        self._by_instrument_id = by_instrument_id

    async def get_latest_by_instrument(self, instrument_id: str, timeframe: str = "1d"):
        return self._by_instrument_id.get(instrument_id)


class _FakeRepos:
    def __init__(self, instruments, signal_feature_snapshots):
        self.instruments = instruments
        self.signal_feature_snapshots = signal_feature_snapshots


async def step1_precompute_function_actually_runs() -> dict[str, float]:
    """`_build_r3b_alpha_percentile_overrides_for_cycle`이 실제로
    universe를 순회하며 candidate_percentile을 계산하는지 확인한다."""
    from run_decision_loop import (
        UniverseSymbol,
        _build_r3b_alpha_percentile_overrides_for_cycle,
    )
    from agent_trading.services.market_regime import classify_market_regime

    # 벤치마크(069500) — bullish_trend으로 분류될 스냅샷 형태를 만든다.
    # classify_market_regime의 실제 판정 로직에 맡기지 않고, 함수가
    # 스냅샷을 그대로 넘겨 분류기를 호출하는지만 확인하면 되므로,
    # SimpleNamespace로 필요한 속성만 채운다.
    from types import SimpleNamespace

    bench_snapshot = SimpleNamespace(
        overall_score=0.7,
        fast_score=0.6,
        slow_score=0.6,
        return_1m_pct=5.0,
        return_3m_pct=20.0,
        price_vs_sma_20_pct=3.0,
        price_vs_sma_60_pct=6.0,
        volatility_20d_pct=8.0,
        atr_14_pct=1.5,
        volume_surge_ratio=1.0,
        average_volume_20d=1_000_000,
        average_turnover_20d=1_000_000,
        turnover_surge_ratio=1.0,
        rsi_14=60.0,
        sma_5=100.0,
        sma_20=98.0,
        sma_60=95.0,
        component_scores_json=None,
    )
    label = classify_market_regime(bench_snapshot).regime_label
    print(f"[1단계] 벤치마크 스냅샷 분류 결과 market_common_label={label}")

    instruments_by_symbol = {
        "069500": _FakeInstrument("bench-id", "069500"),
    }
    snapshots_by_id: dict[str, object] = {"bench-id": bench_snapshot}

    n = 20
    universe_items = []
    for i in range(n):
        sym = f"S{i:02d}"
        inst = _FakeInstrument(f"inst-{i}", sym)
        instruments_by_symbol[sym] = inst
        snapshots_by_id[f"inst-{i}"] = _FakeSnapshot(
            return_1m_pct=float(i - 10),
            return_3m_pct=float(20 - i),
            volatility_20d_pct=10.0,
        )
        universe_items.append(UniverseSymbol(symbol=sym, market="KRX", source_type="core"))

    repos = _FakeRepos(
        instruments=_FakeInstrumentsRepo(instruments_by_symbol),
        signal_feature_snapshots=_FakeSnapshotsRepo(snapshots_by_id),
    )

    os.environ["ENTRY_SCORE_R3B_ALPHA_ENABLED"] = "true"
    try:
        percentiles = await _build_r3b_alpha_percentile_overrides_for_cycle(
            repos, universe=tuple(universe_items)
        )
    finally:
        os.environ.pop("ENTRY_SCORE_R3B_ALPHA_ENABLED", None)

    print(f"[1단계] precompute 결과: {len(percentiles)}개 종목 percentile 부여")
    print(f"[1단계] 상세: {sorted(percentiles.items(), key=lambda kv: kv[1])}")
    assert len(percentiles) == max(1, int(n * 0.20)), "candidate pool 크기가 20% 규칙과 불일치"
    return percentiles


async def step2_orchestrator_engine_reflects_value() -> dict[str, object]:
    """실제 DB의 core 종목 하나로 orchestrator→engine 반영을 확인한다."""
    from agent_trading.db.connection import create_pool
    from agent_trading.db.transaction import transaction
    from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories
    from agent_trading.services.decision_orchestrator import DecisionOrchestratorService
    from agent_trading.services.common_types import SubmitOrderRequest
    from agent_trading.domain.entities import OrderSide, OrderType
    from decimal import Decimal as D

    await create_pool()

    async with transaction() as tx:
        repos = build_postgres_repositories(tx)
        rows = await tx.connection.fetch(
            """
            SELECT i.symbol, i.market_code
            FROM signal_feature_snapshots s
            JOIN instruments i ON i.instrument_id = s.instrument_id
            WHERE s.timeframe = '1d'
            ORDER BY s.snapshot_at DESC LIMIT 1
            """
        )
        symbol = rows[0]["symbol"]
        market = rows[0]["market_code"]
        print(f"[2단계] 검증 대상 종목: {symbol} ({market})")

        request = SubmitOrderRequest(
            account_ref="paper-account",
            client_order_id="r3b-e2e-verify-1",
            correlation_id="r3b-e2e-verify-1",
            strategy_id="00000000-0000-0000-0000-000000000000",
            symbol=symbol,
            market=market,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=D("1"),
            price=None,
            metadata={"source_type": "core", "r3b_alpha_percentile": None},
        )

        # (a) 비활성(기본값) — r3b_alpha_enabled=False
        orchestrator_off = DecisionOrchestratorService(
            repos=repos,
            r3b_alpha_enabled=False,
        )
        deriv_off = await orchestrator_off.derive_deterministic_trigger_for_request(request)
        entry_off = (
            deriv_off.deterministic_trigger.entry_score
            if deriv_off.deterministic_trigger is not None
            else None
        )
        reasons_off = (
            deriv_off.deterministic_trigger.reason_codes
            if deriv_off.deterministic_trigger is not None
            else ()
        )
        print(f"[2단계] (a) r3b_alpha_enabled=False → entry_score={entry_off}")
        print(f"[2단계]     reason_codes={reasons_off}")

        # (b) 활성 + percentile 주입 — request.metadata에 실제 값을 넣는다
        request_with_percentile = SubmitOrderRequest(
            account_ref="paper-account",
            client_order_id="r3b-e2e-verify-2",
            correlation_id="r3b-e2e-verify-2",
            strategy_id="00000000-0000-0000-0000-000000000000",
            symbol=symbol,
            market=market,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=D("1"),
            price=None,
            metadata={"source_type": "core", "r3b_alpha_percentile": 0.9},
        )
        orchestrator_on = DecisionOrchestratorService(
            repos=repos,
            r3b_alpha_enabled=True,
        )
        deriv_on = await orchestrator_on.derive_deterministic_trigger_for_request(
            request_with_percentile
        )
        entry_on = (
            deriv_on.deterministic_trigger.entry_score
            if deriv_on.deterministic_trigger is not None
            else None
        )
        reasons_on = (
            deriv_on.deterministic_trigger.reason_codes
            if deriv_on.deterministic_trigger is not None
            else ()
        )
        print(f"[2단계] (b) r3b_alpha_enabled=True + percentile=0.9 → entry_score={entry_on}")
        print(f"[2단계]     reason_codes={reasons_on}")

        assert "trigger_r3b_alpha_percentile" not in reasons_off, (
            "비활성 상태인데 r3b alpha reason_code가 발생함 — 하위호환 위반"
        )
        assert "trigger_r3b_alpha_percentile" in reasons_on, (
            "활성 상태인데 r3b alpha reason_code가 발생하지 않음 — 실제 미발동"
        )
        assert entry_off != entry_on, "활성/비활성 entry_score가 동일함 — alpha 교체 미반영"

        await tx.rollback()

    print("[2단계] 검증 결과: 활성 시에만 reason_code 발생 + entry_score 변화 확인됨")

    return {
        "symbol": symbol,
        "market": market,
        "off": {
            "r3b_alpha_enabled": False,
            "entry_score": entry_off,
            "reason_codes": list(reasons_off),
        },
        "on": {
            "r3b_alpha_enabled": True,
            "r3b_alpha_percentile_injected": 0.9,
            "entry_score": entry_on,
            "reason_codes": list(reasons_on),
        },
        "entry_score_changed": entry_off != entry_on,
        "alpha_reason_code_present_only_when_enabled": (
            "trigger_r3b_alpha_percentile" not in reasons_off
            and "trigger_r3b_alpha_percentile" in reasons_on
        ),
    }


async def main() -> None:
    import json

    step1_result = await step1_precompute_function_actually_runs()
    print()
    step2_result = await step2_orchestrator_engine_reflects_value()
    print()
    print("=== 전체 결론: precompute 호출 확인 + orchestrator/engine 실제 반영 확인 ===")

    summary = {
        "script": "validate_r3b_alpha_precompute_end_to_end.py",
        "step1_precompute_candidate_percentiles": {
            symbol: pct for symbol, pct in step1_result.items()
        },
        "step1_candidate_count": len(step1_result),
        "step2": step2_result,
    }
    # NOTE: 이 스크립트가 컨테이너 안에서 실행될 경우 `/app/logs`는
    # 호스트에 마운트되지 않은 컨테이너 전용 경로다(docker-compose.yml
    # 확인 결과 app 서비스는 logs를 바인드하지 않음) — 반드시 마운트된
    # `tmp/`에 쓰고, 호출부가 `mv`로 `logs/`에 옮겨야 호스트에 남는다.
    out_path = "tmp/r3b_alpha_precompute_end_to_end_summary.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"[산출물] JSON 요약 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
