#!/usr/bin/env python3
"""SPPV-2.72 — 벤치마크(069500) signal_feature_snapshot 배치 미포함
문제 해소 검증(운영 데이터 경로 수정 턴, 신규 KIS 호출 1건 — 벤치마크
일봉 조회, 매매/주문 경로 없음).

§60(SPPV-2.71)이 확인한 실제 차단 요소: `data/signal_feature_
snapshot_input.json`(일일 signal feature 배치 입력)에 벤치마크
(069500)가 애초에 포함되지 않아, `signal_feature_snapshots` 테이블에
벤치마크 스냅샷이 전체 이력 통틀어 0건이었다. 이 스크립트는 그 수정
(`generate_signal_feature_snapshot_input.py`의 `_with_regime_
benchmark_symbol()`, SPPV-2.72)이 실제로 동작하는지, 전체 80종목
재수집 없이 **벤치마크 1종목만** 대상으로 최소 재현한다:

1. 실제 `_build_rows()`(운영 코드 그대로)를 벤치마크 1종목 universe로
   호출 — 실제 KIS 일봉 조회 1건 발생(read-only 시세 조회, 매매/주문
   없음).
2. 그 결과를 실제 `_write_rows()`로 JSON에 저장(운영 코드 그대로,
   별도 파일 — 기존 `data/signal_feature_snapshot_input.json`은
   덮어쓰지 않는다).
3. 실제 `build_signal_feature_snapshots.py`의 핵심 처리 함수를 그
   JSON에 대해 호출해 벤치마크의 `signal_feature_snapshot`을 DB에
   실제로 upsert한다(이것이 이번 턴의 핵심 목표 — 이 DB row가 있어야
   `_build_r3b_alpha_percentile_overrides_for_cycle()`이 더 이상
   조기 종료하지 않는다).
4. DB에서 직접 재조회해 실제로 row가 생겼는지 확인.
5. `_build_r3b_alpha_percentile_overrides_for_cycle()`(수정 없음,
   §58 그대로)을 실제 core 종목 몇 개 + 벤치마크로 호출해, 더 이상
   빈 dict가 아님을 확인한다.

DB write 있음(§목표 자체가 벤치마크 signal_feature_snapshot을 DB에
쌓는 것) — 그 외 주문 경로/broker submit/실시간 구독 없음. `.env`
미변경.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date

sys.path.insert(0, "scripts")
sys.path.insert(0, "src")


async def main() -> None:
    from generate_signal_feature_snapshot_input import (
        _build_chart_client,
        _build_rows,
        _write_rows,
    )
    from run_decision_loop import (
        UniverseSymbol,
        _R3B_ALPHA_BENCHMARK_MARKET,
        _R3B_ALPHA_BENCHMARK_SYMBOL,
        _build_r3b_alpha_percentile_overrides_for_cycle,
    )
    from agent_trading.config.settings import AppSettings
    from agent_trading.db.connection import create_pool
    from agent_trading.db.transaction import transaction
    from agent_trading.repositories.postgres.bootstrap import build_postgres_repositories

    settings = AppSettings()
    client = _build_chart_client(settings)
    benchmark_universe = (
        UniverseSymbol(
            symbol=_R3B_ALPHA_BENCHMARK_SYMBOL,
            market=_R3B_ALPHA_BENCHMARK_MARKET,
            source_type="regime_benchmark",
            inclusion_reason="regime_benchmark_snapshot",
        ),
    )

    print(f"[1] 벤치마크({_R3B_ALPHA_BENCHMARK_SYMBOL}) 실제 일봉 조회 시작(KIS 호출 1건)...")
    try:
        rows, errors = await _build_rows(
            client,
            universe=benchmark_universe,
            end_date=date.today(),
            lookback_days=180,
            timeframe="1d",
            feature_set_version="signal_backbone_v1",
        )
    finally:
        await client.close()

    print(f"[1] rows={len(rows)} errors={len(errors)}")
    for err in errors:
        print(f"[1]   error: {err.symbol} {err.error_code} {err.error_message}")
    assert len(rows) == 1, "벤치마크 1종목 row가 정확히 1건 생성돼야 한다"
    assert rows[0].symbol == _R3B_ALPHA_BENCHMARK_SYMBOL

    output_path = "tmp/r3b_benchmark_snapshot_input_test.json"
    _write_rows(
        output_path,
        rows,
        fetch_errors=errors,
        universe=benchmark_universe,
        universe_freeze_run_id="r3b-benchmark-fix-verify",
        universe_freeze_reused=False,
        freeze_purpose="r3b_benchmark_fix_verify",
        trigger_type="manual_verify",
    )
    print(f"[2] 입력 JSON 저장: {output_path}")

    print("[3] build_signal_feature_snapshots.py를 실제 CLI 그대로 실행(subprocess)...")
    import subprocess

    proc = subprocess.run(
        [
            sys.executable,
            "scripts/build_signal_feature_snapshots.py",
            "--input",
            output_path,
            "--feature-set-version",
            "signal_backbone_v1",
            "--trigger-type",
            "manual_verify",
        ],
        cwd="/app" if __import__("pathlib").Path("/app").exists() else ".",
        capture_output=True,
        text=True,
    )
    print(proc.stdout)
    if proc.returncode not in (0, 1):
        print(proc.stderr)
        raise SystemExit(f"build_signal_feature_snapshots.py 비정상 종료: {proc.returncode}")

    await create_pool()

    async with transaction() as tx:
        repos = build_postgres_repositories(tx)
        instrument = await repos.instruments.get_by_symbol(
            symbol=_R3B_ALPHA_BENCHMARK_SYMBOL,
            market_code=_R3B_ALPHA_BENCHMARK_MARKET,
        )
        row = await tx.connection.fetchrow(
            "SELECT count(*) as cnt FROM signal_feature_snapshots WHERE instrument_id = $1",
            instrument.instrument_id,
        )
        print(f"[4] DB 재조회 — 벤치마크 signal_feature_snapshot 전체 건수: {row['cnt']}")
        assert row["cnt"] >= 1, "DB에 벤치마크 snapshot이 실제로 존재해야 한다"
        await tx.rollback()

    # build_candidate_percentiles()는 당일 유효 신호 5건 미만이면 빈
    # dict를 반환하도록 설계돼 있다(§67, 통계적으로 무의미한 소표본
    # 방지) — 이 검증에서는 실제 DB에 최신 signal_feature_snapshot이
    # 있는 실제 core 종목 10개를 사용해 이 조건을 충족시킨다.
    core_universe = tuple(
        UniverseSymbol(symbol=sym, market="KRX", source_type="core")
        for sym in (
            "000810", "001450", "000270", "000720", "001040",
            "001440", "000080", "000100", "000660", "001680",
        )
    )
    import os

    # _build_r3b_alpha_percentile_overrides_for_cycle()은 §58 그대로
    # AppSettings().entry_score_r3b_alpha_enabled가 True일 때만 실제
    # 계산을 수행한다(기본값 False면 DB 조회 자체를 건너뛴다) — 이
    # 검증에서만 프로세스 환경변수로 일시 활성화하고 즉시 해제한다.
    # `.env` 파일은 전혀 건드리지 않는다.
    os.environ["ENTRY_SCORE_R3B_ALPHA_ENABLED"] = "true"
    try:
        async with transaction() as tx:
            repos = build_postgres_repositories(tx)
            percentiles = await _build_r3b_alpha_percentile_overrides_for_cycle(
                repos, universe=core_universe
            )
            await tx.commit()
    finally:
        os.environ.pop("ENTRY_SCORE_R3B_ALPHA_ENABLED", None)
    print(f"[5] _build_r3b_alpha_percentile_overrides_for_cycle() 결과: {percentiles}")
    print(
        f"[5] 더 이상 빈 dict가 아님(벤치마크 스냅샷 결측으로 인한 조기 종료 해소): "
        f"{'예' if len(percentiles) > 0 else '아니오'}"
    )
    assert len(percentiles) > 0, (
        "벤치마크 스냅샷을 채웠는데도 precompute 결과가 여전히 빈 dict — 수정이 "
        "실제로 조기 종료를 해소하지 못했다는 뜻"
    )

    print()
    print("=== 결론: 벤치마크 signal_feature_snapshot이 DB에 실제로 생성됨 ===")


if __name__ == "__main__":
    asyncio.run(main())
