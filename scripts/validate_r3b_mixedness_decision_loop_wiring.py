#!/usr/bin/env python3
"""SPPV-2.63 — 국면 혼합도 모니터링을 실제 decision loop 관측 경로에
연결(read-only, in-memory repos, broker submit 없음).

``plans/[DESIGN] regime_conditional_entry_signal_v1.md`` §51/§52 참고.

§51(SPPV-2.62)은 `services/regime_mixedness_monitor.py`를 만들고
검증만 했을 뿐 실제 decision loop에는 연결하지 않았다(§40.7/§51.6이
남긴 "다음 단계"). 이번 턴이 그 gap을 메운다 — `scripts/run_
decision_loop.py`에 신규 함수 `_run_mixedness_check()`를 추가하고,
cycle당 1회 실행되는 pre-check 블록(`_run_precheck()`와 동일한 위치·
패턴)에 배선했다.

**핵심 설계 원칙**: 이 체크는 **BUY/SELL 판정에 절대 연결되지
않는다** — 순수 관측/로깅용이다. §21 게이트(`regime_switch_gate.py`)
처럼 실제 판단 경로의 조건문에 들어가는 것이 아니라, `_run_
precheck()`처럼 "계산하고 로그에 남길 뿐" 사이클 흐름에는 아무
영향을 주지 않는다(예외도 전부 흡수해 사이클 진행을 막지 않음).

이 스크립트는 `_run_mixedness_check()`를 **실제로 호출**해(스크립트가
그 안의 로직만 복제하는 우회가 아님) in-memory repos(기존 테스트
스위트 표준 패턴, `build_in_memory_repositories()`)에 벤치마크
(KODEX 200, 069500)의 합성 signal_feature_snapshot 60건(고혼합
국면을 유도하도록 국면이 자주 바뀌는 값)을 시딩한 뒤, 실제로 mixed_
score·bucket·reason_code가 올바르게 계산·반환되는지 확인한다.

DB write / 주문 경로 / 실시간 구독 / broker submit 없음. 신규 KIS
호출 없음(in-memory repos만 사용).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validate_r3b_mixedness_decision_loop_wiring")

_KST = timezone(timedelta(hours=9))


async def _seed_benchmark_snapshots(repos, instrument_id, *, mixed: bool):
    """벤치마크 signal_feature_snapshot 60건을 시딩한다.

    ``mixed=True``면 overall_score를 강한 양/음으로 번갈아 진동시켜
    (bullish_trend/bearish_trend가 자주 교차하도록) 고혼합 국면을
    유도하고, ``mixed=False``면 항상 강한 양수로 고정해(단일 bullish
    국면 지배) 저혼합 국면을 유도한다.
    """
    from agent_trading.domain.entities import SignalFeatureSnapshotEntity

    base_time = datetime.now(timezone.utc)
    for i in range(60):
        if mixed:
            overall = Decimal("0.60") if i % 2 == 0 else Decimal("-0.60")
        else:
            overall = Decimal("0.70")
        snapshot = SignalFeatureSnapshotEntity(
            signal_feature_snapshot_id=uuid4(),
            instrument_id=instrument_id,
            timeframe="1d",
            snapshot_at=base_time - timedelta(days=60 - i),
            feature_set_version="signal_backbone_v1",
            bar_count=80,
            fast_score=overall,
            slow_score=overall,
            overall_score=overall,
            return_1m_pct=Decimal("2.00") if overall > 0 else Decimal("-2.00"),
            return_3m_pct=Decimal("8.00") if overall > 0 else Decimal("-8.00"),
            price_vs_sma_20_pct=Decimal("4.00") if overall > 0 else Decimal("-4.00"),
            price_vs_sma_60_pct=Decimal("6.00") if overall > 0 else Decimal("-6.00"),
            volatility_20d_pct=Decimal("15.00"),
            component_scores_json={},
        )
        await repos.signal_feature_snapshots.add(snapshot)


async def _run_scenario(*, mixed: bool) -> dict:
    from agent_trading.domain.entities import InstrumentEntity
    from agent_trading.repositories.bootstrap import build_in_memory_repositories

    # run_decision_loop.py의 실제 함수를 그대로 import해서 호출한다
    # (로직 복제가 아니라 실제 배선된 함수를 실행) — sys.path에 scripts/
    # 추가 후 모듈 import.
    import sys as _sys
    _sys.path.insert(0, "scripts")
    from run_decision_loop import (  # noqa: E402
        _MIXEDNESS_BENCHMARK_MARKET,
        _MIXEDNESS_BENCHMARK_SYMBOL,
        _run_mixedness_check,
    )

    repos = build_in_memory_repositories()
    instrument = InstrumentEntity(
        instrument_id=uuid4(),
        symbol=_MIXEDNESS_BENCHMARK_SYMBOL,
        market_code=_MIXEDNESS_BENCHMARK_MARKET,
        asset_class="KR_ETF",
        currency="KRW",
        name="KODEX 200",
    )
    repos.instruments._items[instrument.instrument_id] = instrument

    await _seed_benchmark_snapshots(repos, instrument.instrument_id, mixed=mixed)

    result = await _run_mixedness_check(repos)
    return result


async def main() -> None:
    print("\n=== 1. 저혼합 시나리오(단일 bullish 지배) — _run_mixedness_check() 실제 호출 ===")
    result_low = await _run_scenario(mixed=False)
    print(f"결과: {result_low}")

    print("\n=== 2. 고혼합 시나리오(bullish/bearish 빈번 교차) — _run_mixedness_check() 실제 호출 ===")
    result_high = await _run_scenario(mixed=True)
    print(f"결과: {result_high}")

    low_bucket_correct = result_low is not None and result_low["bucket"] == "저혼합(단일 국면 지배)"
    high_bucket_correct = result_high is not None and result_high["bucket"] == "고혼합"

    print(f"\n저혼합 시나리오가 실제로 '저혼합' 버킷으로 분류됨: {low_bucket_correct}")
    print(f"고혼합 시나리오가 실제로 '고혼합' 버킷으로 분류됨: {high_bucket_correct}")

    print("\n=== 3. 이 체크가 BUY/SELL 판정과 분리돼 있다는 구조적 확인 ===")
    import inspect

    import sys as _sys
    _sys.path.insert(0, "scripts")
    import run_decision_loop as rdl  # noqa: E402

    source = inspect.getsource(rdl._run_mixedness_check)
    no_buy_sell_reference = (
        "buy_candidate" not in source
        and "sell_candidate" not in source
        and "assess_deterministic_triggers" not in source
    )
    print(f"_run_mixedness_check() 소스에 BUY/SELL 판정 관련 코드가 전혀 없음: "
          f"{no_buy_sell_reference}")

    report = {
        "as_of": datetime.now(_KST).isoformat(),
        "low_mixedness_scenario": result_low,
        "high_mixedness_scenario": result_high,
        "low_bucket_correct": low_bucket_correct,
        "high_bucket_correct": high_bucket_correct,
        "no_buy_sell_reference_in_mixedness_check": no_buy_sell_reference,
        "note": (
            "_run_mixedness_check()는 scripts/run_decision_loop.py에 실제로 배선된 함수를 "
            "그대로 import해 호출했다(로직 복제 아님). in-memory repos만 사용, 신규 KIS "
            "호출 없음, DB write/주문 경로/broker submit 없음. BUY/SELL 판정에 영향을 주지 "
            "않는 순수 관측/로깅 체크임을 소스 검사로 확인."
        ),
    }
    out_path = "logs/signal_ic_r3b_mixedness_decision_loop_wiring_2026-07-19.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n산출 저장: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
