"""KIS 국내업종 구분별전체시세를 이용해 지수/업종 코드 카탈로그를 덤프한다.

이 스크립트의 목적은 `KOSPI100`, `KOSPI200`, `KOSDAQ150` 같은
지수 코드가 KIS에서 어떤 `bstp_cls_code`로 노출되는지 운영자가 확인하고,
향후 `index_membership_seed` 원천 파일 확보 전까지 보조 검증 자료로 활용하는 것이다.

주의:
- 이 API는 지수의 `구성종목 목록`을 반환하지 않는다.
- 따라서 `instrument_index_memberships`를 직접 생성하는 authoritative source로
  사용하면 안 된다.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
from pathlib import Path
from typing import Any

from agent_trading.brokers.koreainvestment.rest_client import KISRestClient


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="KIS FHPUP02140000 지수/업종 코드 카탈로그 조회"
    )
    parser.add_argument(
        "--output",
        default="logs/kis_index_category_catalog.json",
        help="출력 파일 경로",
    )
    parser.add_argument(
        "--format",
        choices=("json", "csv"),
        default="json",
        help="출력 포맷",
    )
    parser.add_argument(
        "--index-code",
        default="0001",
        help="기준 지수 코드. 기본값은 코스피 종합(0001)",
    )
    parser.add_argument(
        "--market-class-code",
        default="K2",
        help="FID_MRKT_CLS_CODE. 기본값은 K2",
    )
    parser.add_argument(
        "--belonging-class-code",
        default="0",
        help="FID_BLNG_CLS_CODE. 기본값은 0",
    )
    return parser.parse_args()


def _build_client() -> KISRestClient:
    api_key = os.environ.get("KIS_APP_KEY") or os.environ.get("KIS_API_KEY")
    api_secret = os.environ.get("KIS_APP_SECRET") or os.environ.get("KIS_API_SECRET")
    account_number = os.environ.get("KIS_ACCOUNT_NUMBER", "")
    account_product_code = os.environ.get("KIS_ACCOUNT_PRODUCT_CODE", "01")
    env = os.environ.get("KIS_ENV", "live")

    if not api_key or not api_secret:
        raise SystemExit("KIS_APP_KEY/KIS_APP_SECRET 또는 KIS_API_KEY/KIS_API_SECRET가 필요합니다.")

    return KISRestClient(
        api_key=api_key,
        api_secret=api_secret,
        account_number=account_number,
        account_product_code=account_product_code,
        env=env,
        budget_manager=None,
        dev_token_cache_enabled=True,
    )


def _write_json(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = sorted({key for row in rows for key in row.keys()})
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


async def _run() -> None:
    args = _parse_args()
    client = _build_client()
    rows = await client.get_index_category_quotes(
        index_code=str(args.index_code),
        market_class_code=str(args.market_class_code),
        belonging_class_code=str(args.belonging_class_code),
    )

    output_path = Path(args.output)
    if args.format == "csv":
        _write_csv(output_path, rows)
    else:
        _write_json(output_path, rows)

    print(
        json.dumps(
            {
                "output_path": str(output_path),
                "row_count": len(rows),
                "market_class_code": args.market_class_code,
                "index_code": args.index_code,
                "belonging_class_code": args.belonging_class_code,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(_run())
