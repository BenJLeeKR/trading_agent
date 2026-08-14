#!/usr/bin/env python3
"""CLI로 ``execution.fee_tax`` 정책의 새 ``config_version``을 발행한다.

Admin API(``POST /config-versions/execution-fee-tax``)와 완전히 동일한 서비스
함수(``agent_trading.services.fee_tax_policy_admin.publish_fee_tax_policy`` /
``validate_and_preview_fee_tax_policy``)를 그대로 재사용하는 얇은 CLI
래퍼다 — 검증/append-only 로직/`activated_at` 단조 증가 규칙은 API와 1:1로
동일하다. ``scripts/publish_max_single_position_pct.py``와 동일한 패턴을
따른다.

이 스크립트가 필요한 이유
-------------------------
운영 API 서버는 단일 Bearer 토큰 + 단일 role(``INSPECTION_API_ROLE``)만
지원한다. 그 값이 ``admin``이 아니면(``viewer`` 기본값 포함) HTTP 경로로는
``require_admin`` 게이트를 통과할 수 없다. 이 스크립트는 HTTP 계층을 거치지
않고 ``postgres_runtime()``으로 DB에 직접 연결해 같은 서비스 함수를
호출하므로, 운영 API의 role 설정과 무관하게 사용할 수 있다(``.env``/런타임
환경변수를 바꾸는 우회가 아니다 — 이 저장소에서 이미 승인된 CLI 관리
경로 패턴을 그대로 따른 것이다).

Usage
-----
.. code-block:: bash

    # dry-run (기본) — 검증 + preview만 수행, 아무것도 쓰지 않음
    python -m scripts.publish_fee_tax_policy \\
        --client-id <UUID> --environment paper \\
        --fee-tax-json '{"enabled": true, ...}' \\
        --activated-by ops-jay

    # 실제 발행
    python -m scripts.publish_fee_tax_policy \\
        --client-id <UUID> --environment paper \\
        --fee-tax-json '{"enabled": true, ...}' \\
        --activated-by ops-jay --apply

``--fee-tax-json``은 ``execution.fee_tax`` 스키마 그대로의 JSON 문자열이거나
``@path/to/file.json``으로 파일을 가리킬 수 있다.

Environment variables
---------------------
Same as the main application (``DATABASE_URL``, etc.) — ``postgres_runtime()``
을 통해 실제 DB에 연결한다(dry-run 모드도 현재 활성 버전을 조회하기 위해
DB 연결이 필요하다).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from uuid import UUID

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from agent_trading.domain.enums import Environment
from agent_trading.runtime.bootstrap import postgres_runtime
from agent_trading.services.config_version_admin import ConfigVersionAdminError
from agent_trading.services.fee_tax_policy_admin import (
    FeeTaxPolicyAdminError,
    publish_fee_tax_policy,
)

logger = logging.getLogger(__name__)


def _load_local_dotenv() -> bool:
    if load_dotenv is None:
        return False
    return load_dotenv()


def _load_fee_tax_input(raw: str) -> dict:
    text = raw
    if raw.startswith("@"):
        with open(raw[1:], encoding="utf-8") as fh:
            text = fh.read()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--fee-tax-json is not valid JSON: {exc}") from exc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Publish a new config_version with an execution.fee_tax policy "
            "(immutable append-only — does not modify existing rows)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--client-id", required=True, help="Client UUID")
    parser.add_argument(
        "--environment",
        required=True,
        choices=["paper", "live"],
        help="Target environment — only 'paper'/'live' (not 'real')",
    )
    parser.add_argument(
        "--fee-tax-json",
        required=True,
        help=(
            "execution.fee_tax 스키마 그대로의 JSON 문자열, 또는 "
            "'@path/to/file.json'로 파일 지정"
        ),
    )
    parser.add_argument(
        "--activated-at",
        default=None,
        help=(
            "ISO 8601 타임스탬프(예: 2026-08-14T09:00:00+09:00). 생략하면 "
            "현재 시각. 지정 시 현재 활성 버전의 activated_at보다 반드시 "
            "이후여야 한다."
        ),
    )
    parser.add_argument(
        "--activated-by",
        required=True,
        help="Operator identifier — stored in config_versions.activated_by and audit log",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Preview the change without writing anything (default).",
    )
    parser.add_argument(
        "--apply",
        action="store_false",
        dest="dry_run",
        help="Actually publish the new config_version.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        client_id = UUID(args.client_id)
    except ValueError:
        logger.error("Invalid --client-id (must be a UUID): %s", args.client_id)
        return 1

    try:
        environment = Environment(args.environment)
    except ValueError:
        logger.error("Invalid --environment: %s", args.environment)
        return 1

    try:
        fee_tax_input = _load_fee_tax_input(args.fee_tax_json)
    except (ValueError, OSError) as exc:
        logger.error("%s", exc)
        return 1

    activated_at: datetime | None = None
    if args.activated_at:
        try:
            activated_at = datetime.fromisoformat(args.activated_at)
        except ValueError:
            logger.error("Invalid --activated-at (must be ISO 8601): %s", args.activated_at)
            return 1

    async with postgres_runtime() as runtime:
        repos = runtime["repositories"]

        try:
            result = await publish_fee_tax_policy(
                repos,
                client_id=client_id,
                environment=environment,
                fee_tax_input=fee_tax_input,
                activated_by=args.activated_by,
                activated_at=activated_at,
                dry_run=args.dry_run,
            )
        except (FeeTaxPolicyAdminError, ConfigVersionAdminError) as exc:
            logger.error("Rejected: %s", exc)
            return 1

        if args.dry_run:
            print("DRY-RUN — no changes written.")
            print(f"  client_id     = {client_id}")
            print(f"  environment   = {environment.value}")
            print(json.dumps(
                {
                    "normalized_fee_tax": result.normalized_fee_tax,
                    "sample_price": result.sample_price,
                    "sample_quantity": result.sample_quantity,
                    "sample_buy_fee": result.sample_buy_fee,
                    "sample_sell_fee": result.sample_sell_fee,
                    "sample_sell_tax": result.sample_sell_tax,
                },
                indent=2,
                ensure_ascii=False,
            ))
            print("Re-run with --apply to publish this change.")
            return 0

        print(
            json.dumps(
                {
                    "config_version_id": str(result.new.config_version_id),
                    "previous_config_version_id": (
                        str(result.previous.config_version_id)
                        if result.previous is not None
                        else None
                    ),
                    "version_tag": result.new.version_tag,
                    "activated_at": (
                        result.new.activated_at.isoformat() if result.new.activated_at else None
                    ),
                    "activated_by": result.new.activated_by,
                    "preview": {
                        "sample_buy_fee": result.preview.sample_buy_fee,
                        "sample_sell_fee": result.preview.sample_sell_fee,
                        "sample_sell_tax": result.preview.sample_sell_tax,
                    },
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0


def main() -> None:
    if _load_local_dotenv():
        logger.info("Loaded environment from project .env")
    args = parse_args()
    exit_code = asyncio.run(_run(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
