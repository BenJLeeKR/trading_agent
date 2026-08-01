#!/usr/bin/env python3
"""KIS `CTPF1002R`(주식기본조회) 실전 API로 ETF 종목 정보를 조회해
``trading.instruments``에 없는 ETF 종목을 채워 넣는다.

배경
----
``trading.instruments``는 현재 KIS 실시간 API를 자동으로 호출해 채워지지
않고, 사람이 준비한 정규화 CSV(``scripts/sync_kis_instrument_master.py``)나
하드코딩된 seed(``scripts/seed_instrument_master.py``)로만 적재된다. 이
스크립트는 그 갭 중에서도 ETF 종목만을 대상으로, KIS의 실전 전용 TR_ID
``CTPF1002R``(주식기본조회, ``KISRestClient.get_stock_basic_info()``)를
직접 호출해 종목명/시장구분/자산군을 채우는 별도 경로다.

``CTPF1002R``은 모의투자를 지원하지 않으므로(KIS 공식 문서:
``reference_docs/kis_openapi_full_20260503_markdown/103_주식기본조회.md``),
실전 계좌 크레덴셜(``KIS_LIVE_INFO_APP_KEY``/``_APP_SECRET``)로만 동작한다.
이 크레덴셜은 실시간 현재가 조회 화면(``kis_realtime_quote_source.py``)이
쓰는 것과 동일한 read-only disclosure/live-info 계좌이며, 트레이딩 계좌와는
완전히 분리되어 있다(``runtime.bootstrap._build_kis_live_quote_client()``).

필드 매핑 근거
--------------
``PRDT_TYPE_CD``(상품유형코드)는 "300: 주식, ETF, ETN, ELW"로 ETF 전용 코드가
따로 없다 — 기본값 "300"을 그대로 쓴다. 응답에서:

- ``scty_grp_id_cd``(증권그룹ID코드) == "EF" → ETF 여부 확인(안전장치, 기본
  활성 — ``--allow-non-etf``로 우회 가능)
- ``prdt_abrv_name``(상품약어명) → ``instruments.name`` (없으면 ``prdt_name``)
- ``excg_dvsn_cd``(거래소구분코드) "02"=증권거래소→KOSPI, "03"=코스닥→KOSDAQ
  → ``instruments.market_segment``
- ``lstg_abol_dt``(상장폐지일자) 존재 여부 → ``instruments.is_active``
- ``market_code``/``exchange_code``는 기존 국내 instrument 저장 관례
  (``scripts/sync_kis_instrument_master.py`` ``_canonicalize_storage_market``)와
  동일하게 "KRX"로 통일한다.

기존 스크립트와의 관계
----------------------
- ``_make_instrument_id``/``_classify``/``_enforce_update_policy``를
  ``scripts.sync_kis_instrument_master``에서 그대로 재사용한다 — 새 로직을
  추가하지 않고 기존 upsert 분류(insert/update/promote/skip) 및 장중 적용
  차단 정책을 그대로 따른다.
- ``scripts/seed_placeholder_instruments_from_mapping_gaps.py``와 동일한
  ``create_pool()`` → ``TransactionManager`` → ``commit()``/rollback 패턴을
  따른다.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.config.settings import AppSettings
from agent_trading.db.connection import close_pool, create_pool
from agent_trading.db.transaction import TransactionManager
from agent_trading.domain.entities import InstrumentEntity
from agent_trading.repositories.contracts import InstrumentRepository
from agent_trading.repositories.postgres.instruments import PostgresInstrumentRepository
from agent_trading.runtime.bootstrap import _build_kis_live_quote_client
from scripts.sync_kis_instrument_master import (
    _classify,
    _enforce_update_policy,
    _make_instrument_id,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill_etf_instruments_from_kis")

# KIS CTPF1002R PRDT_TYPE_CD — ETF 전용 코드는 없고 "주식/ETF/ETN/ELW" 공통값이다.
# (reference_docs/kis_openapi_full_20260503_markdown/103_주식기본조회.md)
DEFAULT_PRODUCT_TYPE_CODE = "300"

# scty_grp_id_cd(증권그룹ID코드) 중 ETF를 뜻하는 값.
ETF_SECURITY_GROUP_CODE = "EF"

# excg_dvsn_cd(거래소구분코드) → market_segment 매핑.
_EXCHANGE_DIVISION_TO_SEGMENT: dict[str, str] = {
    "02": "KOSPI",  # 증권거래소
    "03": "KOSDAQ",  # 코스닥
}

_SYMBOL_LEN = 6


@dataclass(frozen=True, slots=True)
class BackfillCounters:
    inserted: int = 0
    updated: int = 0
    skipped_existing_canonical: int = 0
    skipped_empty_payload: int = 0
    skipped_non_etf: int = 0
    errors: int = 0


def _validate_etf_symbol(raw: str) -> str | None:
    """6자리 종목코드만 허용한다.

    KRX ETF 코드는 6자리이지만 순수 숫자만 있는 게 아니다 — 최근 상장분 중에는
    영숫자 혼합 코드(예: ``0000D0``, ``0001P0``)가 다수 존재한다(KIS 공식
    종목정보파일 실측으로 확인, 2026-07 기준 KOSPI EF(ETF) 1145건 중 277건이
    영숫자 혼합). ETN 전용 ``Q`` 접두사와는 별개이며, ETN 여부는 이 함수가
    아니라 ``scty_grp_id_cd``(증권그룹ID코드) 조회로 걸러진다.
    """
    symbol = raw.strip().upper()
    if len(symbol) != _SYMBOL_LEN or not symbol.isalnum():
        return None
    return symbol


def _load_symbols_file(path: str) -> list[str]:
    """줄바꿈으로 구분된 종목코드 목록을 읽는다.

    ``#``으로 시작하는 줄과 빈 줄은 무시한다. CSV 헤더(``symbol`` 컬럼)가
    있어도 첫 컬럼만 취급하므로 자연스럽게 동작한다.
    """
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"symbols-file not found: {path}")
    symbols: list[str] = []
    with target.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            candidate = line.split(",", 1)[0].strip()
            if not candidate or candidate.startswith("#") or candidate.lower() == "symbol":
                continue
            symbols.append(candidate)
    return symbols


def _collect_symbols(args: argparse.Namespace) -> list[str]:
    raw_symbols: list[str] = []
    if args.symbols:
        raw_symbols.extend(part.strip() for part in args.symbols.split(",") if part.strip())
    if args.symbols_file:
        raw_symbols.extend(_load_symbols_file(args.symbols_file))

    seen: set[str] = set()
    normalized: list[str] = []
    for raw in raw_symbols:
        symbol = _validate_etf_symbol(raw)
        if symbol is None:
            logger.warning("INVALID symbol=%r — 6자리 숫자가 아니어서 건너뜀", raw)
            continue
        if symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)
    return normalized


def _derive_market_segment(payload: dict[str, str]) -> str | None:
    excg_dvsn_cd = str(payload.get("excg_dvsn_cd", "")).strip()
    segment = _EXCHANGE_DIVISION_TO_SEGMENT.get(excg_dvsn_cd)
    if segment is not None:
        return segment
    # excg_dvsn_cd가 예상 밖 값일 때의 2차 근거 — 상장일자 필드 존재 여부.
    if str(payload.get("kosdaq_mket_lstg_dt", "")).strip():
        return "KOSDAQ"
    if str(payload.get("scts_mket_lstg_dt", "")).strip():
        return "KOSPI"
    return None


def _build_etf_instrument(
    symbol: str,
    payload: dict[str, str],
    *,
    market_code: str,
    currency: str,
    source_tag: str,
) -> InstrumentEntity:
    name = (
        str(payload.get("prdt_abrv_name", "")).strip()
        or str(payload.get("prdt_name", "")).strip()
        or f"ETF{symbol}"
    )
    market_segment = _derive_market_segment(payload)
    is_active = not str(payload.get("lstg_abol_dt", "")).strip()

    # 주의: 타임스탬프처럼 매 호출마다 달라지는 값은 metadata에 넣지 않는다 —
    # ``_classify()``가 기존/신규 InstrumentEntity의 metadata 전체를 비교해
    # insert/update/skip을 판단하므로(scripts/sync_kis_instrument_master.py),
    # 변동값이 섞이면 실제 내용이 그대로여도 재실행할 때마다 "update"로
    # 오분류되어 이 스크립트의 멱등성(변경 없으면 skip)이 깨진다.
    metadata: dict[str, object] = {
        "sync_source": "kis_ctpf1002r_live",
        "source_tag": source_tag,
        "prdt_name": payload.get("prdt_name"),
        "prdt_eng_name": payload.get("prdt_eng_name"),
        "std_pdno": payload.get("std_pdno"),  # ISIN
        "mket_id_cd": payload.get("mket_id_cd"),
        "excg_dvsn_cd": payload.get("excg_dvsn_cd"),
        "scty_grp_id_cd": payload.get("scty_grp_id_cd"),
        "etf_dvsn_cd": payload.get("etf_dvsn_cd"),
        "etf_type_cd": payload.get("etf_type_cd"),
        "kospi200_item_yn": payload.get("kospi200_item_yn"),
    }
    metadata = {k: v for k, v in metadata.items() if v not in (None, "")}

    return InstrumentEntity(
        instrument_id=_make_instrument_id(symbol, market_code),
        symbol=symbol,
        market_code=market_code,
        asset_class="kr_etf",
        currency=currency,
        name=name,
        tick_size=Decimal("1"),
        lot_size=Decimal("1"),
        is_active=is_active,
        exchange_code="KRX" if market_code == "KRX" else market_code,
        market_segment=market_segment,
        metadata=metadata,
    )


async def _backfill(
    client: KISRestClient,
    repo: InstrumentRepository,
    symbols: list[str],
    *,
    args: argparse.Namespace,
) -> BackfillCounters:
    inserted = updated = 0
    skipped_existing_canonical = skipped_empty_payload = skipped_non_etf = errors = 0

    for symbol in symbols:
        try:
            payload = await client.get_stock_basic_info(
                symbol, product_type_code=args.product_type_code
            )
        except Exception:
            logger.exception("ERROR symbol=%s — CTPF1002R 조회 실패", symbol)
            errors += 1
            continue

        if not payload:
            logger.warning(
                "SKIP(empty_payload) symbol=%s — KIS가 빈 응답을 반환했습니다 "
                "(잘못된 종목코드이거나 실전 계좌 크레덴셜 미설정일 수 있음)",
                symbol,
            )
            skipped_empty_payload += 1
            continue

        scty_grp_id_cd = str(payload.get("scty_grp_id_cd", "")).strip()
        if scty_grp_id_cd != ETF_SECURITY_GROUP_CODE and not args.allow_non_etf:
            logger.warning(
                "SKIP(non_etf) symbol=%s scty_grp_id_cd=%s — ETF가 아닌 것으로 보여 건너뜀 "
                "(강제로 넣으려면 --allow-non-etf)",
                symbol,
                scty_grp_id_cd or "(empty)",
            )
            skipped_non_etf += 1
            continue

        instrument = _build_etf_instrument(
            symbol,
            payload,
            market_code=args.market_code,
            currency=args.currency,
            source_tag=args.source_tag,
        )
        existing = await repo.get_by_symbol_any_market(symbol)
        action = _classify(existing, instrument)

        logger.info(
            "%s %s/%s %s (market_segment=%s asset_class=%s)",
            action.upper(),
            instrument.market_code,
            instrument.symbol,
            instrument.name,
            instrument.market_segment,
            instrument.asset_class,
        )

        if action == "insert":
            inserted += 1
            if args.apply:
                await repo.upsert_by_symbol(instrument)
        elif action in {"update", "promote"}:
            updated += 1
            if args.apply:
                await repo.upsert_by_symbol(instrument)
        else:
            skipped_existing_canonical += 1

    return BackfillCounters(
        inserted=inserted,
        updated=updated,
        skipped_existing_canonical=skipped_existing_canonical,
        skipped_empty_payload=skipped_empty_payload,
        skipped_non_etf=skipped_non_etf,
        errors=errors,
    )


async def _run(args: argparse.Namespace) -> int:
    await _enforce_update_policy(args)

    symbols = _collect_symbols(args)
    if not symbols:
        raise SystemExit(
            "조회할 ETF 종목코드가 없습니다. --symbols 또는 --symbols-file을 지정하세요."
        )
    logger.info("대상 ETF 종목 수: %d", len(symbols))

    await create_pool()
    client: KISRestClient | None = None
    try:
        settings = AppSettings()
        client = _build_kis_live_quote_client(settings)
        if client is None:
            raise SystemExit(
                "KIS 실전 read-only 클라이언트를 만들 수 없습니다 — "
                "KIS_LIVE_INFO_APP_KEY / KIS_LIVE_INFO_APP_SECRET 설정이 필요합니다 "
                "(CTPF1002R는 모의투자 미지원이라 실전 계좌 크레덴셜만 동작합니다)."
            )

        tx = TransactionManager()
        await tx.__aenter__()
        try:
            repo: InstrumentRepository = PostgresInstrumentRepository(tx)
            counters = await _backfill(client, repo, symbols, args=args)
            logger.info(
                "Summary: inserted=%d updated=%d skipped_existing_canonical=%d "
                "skipped_empty_payload=%d skipped_non_etf=%d errors=%d",
                counters.inserted,
                counters.updated,
                counters.skipped_existing_canonical,
                counters.skipped_empty_payload,
                counters.skipped_non_etf,
                counters.errors,
            )
            if args.apply:
                await tx.commit()
                logger.info("Changes committed to database.")
            else:
                logger.info("Dry-run complete. Use --apply to persist changes.")
        except BaseException:
            await tx.rollback()
            raise
        finally:
            await tx.__aexit__(None, None, None)
    finally:
        if client is not None:
            await client.close()
        await close_pool()
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "KIS CTPF1002R(주식기본조회) 실전 API로 ETF 종목 정보를 조회해 "
            "trading.instruments에 없는 ETF를 채워 넣는다."
        ),
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help="쉼표로 구분한 ETF 종목코드 목록 (예: '069500,102110').",
    )
    parser.add_argument(
        "--symbols-file",
        default=None,
        help="줄바꿈으로 구분된 ETF 종목코드 목록 파일 경로 (# 주석/빈 줄 무시).",
    )
    parser.add_argument("--apply", action="store_true", help="DB에 실제로 반영한다.")
    parser.add_argument(
        "--allow-non-etf",
        action="store_true",
        help="scty_grp_id_cd != 'EF'인 종목도 강제로 적재한다(기본은 건너뜀).",
    )
    parser.add_argument("--market-code", default="KRX", help="저장할 market_code (기본 KRX).")
    parser.add_argument("--currency", default="KRW")
    parser.add_argument("--product-type-code", default=DEFAULT_PRODUCT_TYPE_CODE)
    parser.add_argument("--source-tag", default="kis_ctpf1002r_live")
    parser.add_argument(
        "--allow-intraday-apply",
        action="store_true",
        help="거래일 장중 --apply를 막는 기본 정책을 override한다.",
    )
    parser.add_argument(
        "--ignore-update-policy",
        action="store_true",
        help="update policy gate를 전부 우회한다(긴급 수동 조치 전용).",
    )
    parser.add_argument(
        "--now-kst",
        default=None,
        help="테스트용: 현재 KST 시각을 override한다(ISO-8601).",
    )
    return parser.parse_args(argv)


def main() -> None:
    raise SystemExit(asyncio.run(_run(_parse_args())))


if __name__ == "__main__":
    main()
