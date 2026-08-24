#!/usr/bin/env python3
"""SPPV-3 독립 OOS 검증용 신규 point-in-time bar cache 수집 — read-only 연구용.

``docs/10_signal_research_sppv/[DESIGN] signal_predictive_power_validation.md``
§37.4/§41.4가 명시한 "cache를 `2026-07-14` 이후 거래일까지 갱신"을 실행한다.
`overnight_reversal_v1`/`intraday_reversal_v1`(§41)과 `low_volatility_
rank_20d`(§36.2, 이미 Watch로 판정된 §39.4)의 **첫 진짜 independent
out-of-sample 검증**에 쓸 데이터를 모은다.

**이 스크립트는 운영 경로가 아니다.** OOS 신호 계산·forward return·
Go/Watch/Hold/No-Go 판정을 전혀 수행하지 않는다 — 오직 (1) 기존 base
cache를 읽기 전용으로 참조하고, (2) `2026-07-15` 이후 신규 거래일만
KIS에서 조회(historical daily bar, read-only)하고, (3) 그 둘을 provenance
태그를 붙여 새 cache 디렉터리에 저장하고, (4) 감사 가능한 manifest를
남기는 것까지만 한다.

허용된 KIS 호출: `inquire_daily_itemchartprice`(국내주식 기간별시세,
read-only)뿐이다. 이 스크립트가 쓰는 클라이언트(`_build_kis_live_quote_
client()`)는 `account_number`/`account_product_code`가 항상 빈
문자열이라 애초에 주문·잔고·체결·계좌 엔드포인트를 호출할 방법이
구조적으로 없다(§자체 read-only 계약, ``agent_trading.runtime.
bootstrap`` 참고).

DB 연결·write 없음, `.env` 수정 없음, 컨테이너 재기동/compose 명령
없음, universe 확장·축소 없음, 기존 cache 덮어쓰기·삭제 없음.

기존 base cache
---------------
``logs/_bars_cache_core87_3y_2026-07-14/``(§36.1) — **절대 수정·삭제
하지 않는다.** 이 스크립트는 이 디렉터리를 오직 읽기 전용으로만 연다.

신규 cache
----------
``logs/_bars_cache_core87_3y_<실제 수집 실행일>/`` — 종목별 JSON 파일은
기존 파일과 같은 "거래일자(YYYYMMDD) → KIS 원본 필드 dict" 구조를
그대로 유지해(``_rows_to_bars()`` 등 기존 소비 코드와 호환), 각 원본
row에 ``_cache_provenance``(``"base_cache"`` 또는 ``"oos_new"``)와
``_collected_at_kst``(신규 행만 실제 수집 시각, base 행은 ``null``)를
추가로 붙인다. 이 provenance 태그가 향후 분석에서 "`2026-07-15` 이후만
OOS로 쓰고, 그 이전은 5/20/60일 lookback의 warm-up 용도로만 쓴다"는
§41.3/§41.4 계약을 코드 레벨에서 강제할 수 있게 해준다.

디렉터리 최상위에 비밀값 없는 ``manifest.json``을 남긴다(§ manifest
섹션 참고) — cache 식별자, 수집 시각, 대상 기간, symbol별 수집 현황,
중복/실패 집계, checksum, ``ready_for_oos`` 판정을 담는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
if os.path.join(_REPO_ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(_REPO_ROOT, ".env"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("build_sppv3_oos_bar_cache")

KST = timezone(timedelta(hours=9))

# ── 고정 계약(§41.4) — 실행 결과를 보고 바꾸지 않음 ─────────────────────────
BASE_CACHE_DIR = os.path.join(_REPO_ROOT, "logs", "_bars_cache_core87_3y_2026-07-14")
BASE_CACHE_AS_OF_DATE = "2026-07-14"
OOS_START_DATE = "20260715"  # YYYYMMDD, KIS 응답 날짜 포맷과 동일한 문자열 비교 사용
NEW_CACHE_DIR_PREFIX = os.path.join(_REPO_ROOT, "logs", "_bars_cache_core87_3y_")
_WINDOW_DAYS = 100  # KIS 100거래일 제한 보수적으로 잡음(v4와 동일 관례)
_SLEEP_SECONDS = 0.3
MARKET_CODE = "J"


# ── 순수 함수(DB/네트워크 미사용, 단위 테스트 대상) ─────────────────────────


def merge_kis_windows(window_responses: list[list[dict[str, Any]]]) -> tuple[dict[str, dict], int]:
    """여러 슬라이딩 윈도 응답을 거래일(``stck_bsop_date``) 기준으로 합친다.

    같은 날짜가 둘 이상의 윈도에 나타나면(윈도 경계가 겹칠 때) **나중에
    처리된 윈도의 값으로 결정론적으로 덮어쓴다** — 윈도는 항상 시간
    오름차순으로 순회하므로 "가장 최근에 조회한 응답이 이긴다"는 뜻이다.
    중복 발생 건수를 함께 반환한다.
    """
    merged: dict[str, dict] = {}
    duplicate_count = 0
    for rows in window_responses:
        for raw in rows:
            d = str(raw.get("stck_bsop_date", "")).strip()
            if not d:
                continue
            if d in merged:
                duplicate_count += 1
            merged[d] = raw
    return merged, duplicate_count


@dataclass(slots=True, frozen=True)
class MergeStats:
    base_bar_count: int
    new_bar_added_count: int
    new_bar_discarded_pre_oos_count: int
    overlap_with_base_discarded_count: int


def build_symbol_cache_entry(
    base_bars: dict[str, dict],
    new_merged: dict[str, dict],
    oos_start_date: str,
    collected_at_kst_iso: str,
) -> tuple[dict[str, dict], MergeStats]:
    """base cache(변경 없이 그대로 유지)와 신규 조회 결과를 provenance
    태그를 붙여 하나의 종목별 bar dict로 합친다.

    - base cache에 있던 날짜는 절대 건드리지 않는다(값 그대로 복사,
      ``_cache_provenance="base_cache"``, ``_collected_at_kst=None``).
    - 신규 조회 결과 중 ``oos_start_date`` **이전** 날짜는 전부 버린다
      (§41.3 "기존 static cache로는 재계산하지 않는다"는 계약 — 문자열
      비교는 YYYYMMDD 형식이 사전식 순서와 시간 순서가 같으므로 안전).
    - 신규 조회 결과 중 base cache와 날짜가 겹치면(정상적으로는 발생하지
      않아야 하나 방어적으로) **base cache 값을 그대로 유지**하고 신규
      값은 버린다 — "기존 cache의 `2026-07-14` 이하 데이터는 변경하지
      않는다"는 원칙을 어떤 경로로도 깨지 않기 위함이다.
    - 그 외 신규 날짜만 ``_cache_provenance="oos_new"``,
      ``_collected_at_kst=<실행 시각>``으로 추가한다.
    """
    combined: dict[str, dict] = {}
    for d, raw in base_bars.items():
        combined[d] = {**raw, "_cache_provenance": "base_cache", "_collected_at_kst": None}

    new_bar_added = 0
    new_bar_discarded_pre_oos = 0
    overlap_with_base_discarded = 0
    for d, raw in new_merged.items():
        if d < oos_start_date:
            new_bar_discarded_pre_oos += 1
            continue
        if d in base_bars:
            overlap_with_base_discarded += 1
            continue
        combined[d] = {**raw, "_cache_provenance": "oos_new", "_collected_at_kst": collected_at_kst_iso}
        new_bar_added += 1

    stats = MergeStats(
        base_bar_count=len(base_bars),
        new_bar_added_count=new_bar_added,
        new_bar_discarded_pre_oos_count=new_bar_discarded_pre_oos,
        overlap_with_base_discarded_count=overlap_with_base_discarded,
    )
    return combined, stats


@dataclass(slots=True, frozen=True)
class SymbolCollectionResult:
    symbol: str
    fetch_status: str  # "ok" | "failed"
    error_summary: str | None
    base_last_trade_date: str | None
    new_first_trade_date: str | None
    new_last_trade_date: str | None
    merge_stats: MergeStats
    duplicate_within_new_fetch_count: int
    file_sha256: str | None


def determine_ready_for_oos(
    results: list[SymbolCollectionResult], required_symbols: set[str]
) -> tuple[bool, list[str]]:
    """§ 완전성 정책: 87종목+벤치마크(=``required_symbols``) 전부가
    ``fetch_status="ok"``여야 ``ready_for_oos=True``다.

    "신규 bar 0건"은 그 자체로 실패가 아니다(해당 기간에 거래정지·
    관리종목 등으로 실제 거래일이 없었을 수 있음) — 실패로 잘못
    분류하지 않되, 감사 목적으로 별도 경고 목록(``symbols_with_zero_
    new_bars``)에 남긴다(반환값 두 번째 항목).
    """
    by_symbol = {r.symbol: r for r in results}
    missing = sorted(required_symbols - set(by_symbol))
    failed = sorted(sym for sym, r in by_symbol.items() if r.fetch_status != "ok")
    zero_new_bars = sorted(
        sym
        for sym, r in by_symbol.items()
        if r.fetch_status == "ok" and r.merge_stats.new_bar_added_count == 0
    )
    ready = not missing and not failed
    return ready, zero_new_bars if ready else (missing + failed)


def build_manifest(
    *,
    cache_id: str,
    generated_at_kst_iso: str,
    generated_at_utc_iso: str,
    base_cache_path: str,
    base_cache_as_of_date: str,
    oos_start_date: str,
    oos_end_date: str,
    universe_symbols: list[str],
    benchmark_symbol: str,
    results: list[SymbolCollectionResult],
    ready_for_oos: bool,
    ready_for_oos_notes: list[str],
) -> dict[str, Any]:
    """비밀값이 전혀 포함되지 않는 감사용 manifest를 조립한다(순수 함수)."""
    total_base_bars = sum(r.merge_stats.base_bar_count for r in results)
    total_new_bars = sum(r.merge_stats.new_bar_added_count for r in results)
    total_duplicates = sum(r.duplicate_within_new_fetch_count for r in results)

    return {
        "cache_id": cache_id,
        "generated_at_kst": generated_at_kst_iso,
        "generated_at_utc": generated_at_utc_iso,
        "base_cache_path": base_cache_path,
        "base_cache_as_of_date": base_cache_as_of_date,
        "base_cache_immutability_note": (
            "base_cache_path는 이 실행 동안 읽기 전용으로만 열렸다 — "
            "쓰기/삭제 API를 이 스크립트 어디에서도 호출하지 않는다."
        ),
        "oos_collection_window": {"start_date": oos_start_date, "end_date": oos_end_date},
        "universe_symbol_count": len(universe_symbols),
        "benchmark_symbol": benchmark_symbol,
        "kis_call_kind": (
            "historical_daily_bar_read_only "
            "(inquire_daily_itemchartprice; 주문/잔고/체결/계좌 API 미사용, "
            "이 클라이언트는 account_number가 비어 있어 구조적으로 호출 불가)"
        ),
        "totals": {
            "base_bar_count": total_base_bars,
            "new_bar_added_count": total_new_bars,
            "duplicate_within_new_fetch_count": total_duplicates,
        },
        "symbols": [
            {
                "symbol": r.symbol,
                "fetch_status": r.fetch_status,
                "error_summary": r.error_summary,
                "base_last_trade_date": r.base_last_trade_date,
                "new_first_trade_date": r.new_first_trade_date,
                "new_last_trade_date": r.new_last_trade_date,
                "base_bar_count": r.merge_stats.base_bar_count,
                "new_bar_added_count": r.merge_stats.new_bar_added_count,
                "new_bar_discarded_pre_oos_count": r.merge_stats.new_bar_discarded_pre_oos_count,
                "overlap_with_base_discarded_count": r.merge_stats.overlap_with_base_discarded_count,
                "duplicate_within_new_fetch_count": r.duplicate_within_new_fetch_count,
                "file_sha256": r.file_sha256,
            }
            for r in results
        ],
        "ready_for_oos": ready_for_oos,
        "ready_for_oos_policy": (
            "universe_symbols + benchmark 전원이 fetch_status='ok'여야 "
            "True다. 신규 bar 0건은 그 자체로 실패가 아니므로(거래정지 등 "
            "가능) ready_for_oos 판정에 포함하지 않는다."
        ),
        "ready_for_oos_notes": ready_for_oos_notes,
        "oos_label_boundary_note": (
            f"이 cache로 이후 분석할 때 `_cache_provenance='oos_new'`이고 "
            f"거래일이 '{oos_start_date}' 이상인 행만 OOS 표본으로 쓴다. "
            "`_cache_provenance='base_cache'' 행은 5/20/60일 lookback의 "
            "warm-up 용도로만 허용되며, 그 자체를 OOS 표본으로 집계하면 "
            "안 된다."
        ),
        "no_signal_or_verdict_note": (
            "이 manifest와 cache는 성과 계산·후보 판정을 전혀 수행하지 "
            "않는다 — bar 수집 및 provenance 기록까지만 다룬다."
        ),
    }


def sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_base_bars(symbol: str) -> dict[str, dict]:
    path = os.path.join(BASE_CACHE_DIR, f"{symbol}.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── I/O 레이어(KIS 호출 포함, 단위 테스트 대상 아님) ────────────────────────


async def fetch_symbol_new_bars(
    client: Any, symbol: str, start_date: date, end_date: date
) -> tuple[dict[str, dict], int, str | None]:
    """``start_date``~``end_date`` 구간의 신규 일봉을 슬라이딩 조회한다.

    실패 시 원본 예외 메시지(URL/토큰 등이 섞여 있을 수 있음)를 그대로
    남기지 않고, 예외 타입 이름만 안전하게 기록한다.
    """
    import asyncio

    window_responses: list[list[dict[str, Any]]] = []
    window_start = start_date
    try:
        while window_start <= end_date:
            window_end = min(window_start + timedelta(days=_WINDOW_DAYS), end_date)
            raw_rows = await client.inquire_daily_itemchartprice(
                symbol=symbol,
                market_code=MARKET_CODE,
                start_date=window_start.strftime("%Y%m%d"),
                end_date=window_end.strftime("%Y%m%d"),
                period_div_code="D",
                adjusted_price=True,
            )
            window_responses.append(raw_rows)
            await asyncio.sleep(_SLEEP_SECONDS)
            window_start = window_end + timedelta(days=1)
    except Exception as exc:  # noqa: BLE001 - 안전한 요약만 남기기 위해 의도적으로 광범위하게 포착
        return {}, 0, type(exc).__name__

    merged, duplicate_count = merge_kis_windows(window_responses)
    return merged, duplicate_count, None


async def collect_one_symbol(
    client: Any,
    symbol: str,
    oos_start_date_obj: date,
    oos_end_date_obj: date,
    new_cache_dir: str,
    collected_at_kst_iso: str,
) -> SymbolCollectionResult:
    base_bars = load_base_bars(symbol)
    base_last_trade_date = max(base_bars.keys()) if base_bars else None

    new_merged, duplicate_count, error_summary = await fetch_symbol_new_bars(
        client, symbol, oos_start_date_obj, oos_end_date_obj
    )
    if error_summary is not None:
        return SymbolCollectionResult(
            symbol=symbol,
            fetch_status="failed",
            error_summary=error_summary,
            base_last_trade_date=base_last_trade_date,
            new_first_trade_date=None,
            new_last_trade_date=None,
            merge_stats=MergeStats(len(base_bars), 0, 0, 0),
            duplicate_within_new_fetch_count=duplicate_count,
            file_sha256=None,
        )

    combined, stats = build_symbol_cache_entry(base_bars, new_merged, OOS_START_DATE, collected_at_kst_iso)

    new_dates = sorted(
        d for d, r in combined.items() if r.get("_cache_provenance") == "oos_new"
    )

    out_path = os.path.join(new_cache_dir, f"{symbol}.json")
    os.makedirs(new_cache_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False)
    file_sha256 = sha256_of_file(out_path)

    return SymbolCollectionResult(
        symbol=symbol,
        fetch_status="ok",
        error_summary=None,
        base_last_trade_date=base_last_trade_date,
        new_first_trade_date=new_dates[0] if new_dates else None,
        new_last_trade_date=new_dates[-1] if new_dates else None,
        merge_stats=stats,
        duplicate_within_new_fetch_count=duplicate_count,
        file_sha256=file_sha256,
    )


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "SPPV-3 독립 OOS 검증용 신규 bar cache 수집(read-only KIS "
            "historical daily bar) — 신호 계산/판정 없음"
        )
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="수집 종료일(YYYY-MM-DD, KST). 생략하면 실행 시각의 KST 오늘 날짜.",
    )
    args = parser.parse_args(argv)

    from agent_trading.config.settings import AppSettings
    from agent_trading.runtime.bootstrap import _build_kis_live_quote_client
    from agent_trading.services.core_universe_seed import APPROVED_CORE_UNIVERSE_SYMBOLS

    universe = sorted(APPROVED_CORE_UNIVERSE_SYMBOLS)
    benchmark_symbol = "069500"
    if benchmark_symbol not in universe:
        raise SystemExit(
            f"벤치마크 {benchmark_symbol}이 APPROVED_CORE_UNIVERSE_SYMBOLS에 없습니다 — "
            "universe 정의가 §36.1 기준과 어긋났을 수 있어 중단합니다."
        )

    settings = AppSettings()
    client = _build_kis_live_quote_client(settings)
    if client is None:
        raise SystemExit("KIS live quote client 생성 실패 — KIS_LIVE_INFO_* 확인")

    oos_start_date_obj = datetime.strptime(OOS_START_DATE, "%Y%m%d").date()
    end_date_obj = (
        datetime.strptime(args.end_date, "%Y-%m-%d").date()
        if args.end_date
        else datetime.now(KST).date()
    )
    if end_date_obj < oos_start_date_obj:
        raise SystemExit(
            f"--end-date({end_date_obj.isoformat()})가 OOS 시작일"
            f"({oos_start_date_obj.isoformat()})보다 이전일 수 없습니다."
        )

    now_kst = datetime.now(KST)
    collected_at_kst_iso = now_kst.isoformat()
    cache_run_date = now_kst.strftime("%Y-%m-%d")
    new_cache_dir = f"{NEW_CACHE_DIR_PREFIX}{cache_run_date}"

    logger.info(
        "SPPV-3 OOS cache 수집 시작 — universe=%d종목(벤치마크 포함), "
        "구간=%s~%s, 신규 cache=%s",
        len(universe),
        OOS_START_DATE,
        end_date_obj.strftime("%Y%m%d"),
        new_cache_dir,
    )

    results: list[SymbolCollectionResult] = []
    try:
        for idx, symbol in enumerate(universe, start=1):
            result = await collect_one_symbol(
                client, symbol, oos_start_date_obj, end_date_obj, new_cache_dir, collected_at_kst_iso
            )
            results.append(result)
            if idx % 20 == 0 or idx == len(universe):
                logger.info("[%d/%d] 수집 진행 — 최근: %s(%s)", idx, len(universe), symbol, result.fetch_status)
    finally:
        close = getattr(client, "close", None)
        if close is not None:
            await close()

    ready_for_oos, notes = determine_ready_for_oos(results, set(universe))

    manifest = build_manifest(
        cache_id=f"sppv3_oos_bar_cache_{cache_run_date}",
        generated_at_kst_iso=collected_at_kst_iso,
        generated_at_utc_iso=now_kst.astimezone(timezone.utc).isoformat(),
        base_cache_path=BASE_CACHE_DIR,
        base_cache_as_of_date=BASE_CACHE_AS_OF_DATE,
        oos_start_date=OOS_START_DATE,
        oos_end_date=end_date_obj.strftime("%Y%m%d"),
        universe_symbols=universe,
        benchmark_symbol=benchmark_symbol,
        results=results,
        ready_for_oos=ready_for_oos,
        ready_for_oos_notes=notes,
    )

    manifest_path = os.path.join(new_cache_dir, "manifest.json")
    os.makedirs(new_cache_dir, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({k: v for k, v in manifest.items() if k != "symbols"}, ensure_ascii=False, indent=2))
    print(f"\n[출력] manifest 저장: {manifest_path}")
    print(f"[출력] ready_for_oos={ready_for_oos}")

    return 0 if ready_for_oos else 1


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
