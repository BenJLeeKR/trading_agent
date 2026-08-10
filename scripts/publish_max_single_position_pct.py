#!/usr/bin/env python3
"""CLI로 ``risk.max_single_position_pct``의 활성 config_version을 안전하게

교체(신규 버전 발행)한다 — Admin API(``POST
/config-versions/risk/max-single-position-pct``)와 완전히 동일한 서비스
함수(``agent_trading.services.config_version_admin.publish_max_single_position_pct``)
를 그대로 재사용하는 얇은 CLI 래퍼다. 검증/immutable-append 로직은 API와
1:1로 동일하다 — 이 스크립트는 인자 파싱 + DB 커넥션 획득만 담당한다.

이 스크립트는 **기존 활성 config_version을 UPDATE하지 않는다.** 그 값을
그대로 복제한 뒤 대상 키만 바꾼 **새 row**를 추가하고, 그 새 row가
``activated_at`` 기준 최신이 되어 ``get_active()``가 그것을 가리키게
한다. 과거 버전은 그대로 남아 replay 시 그 시점의 실제 설정을
재현할 수 있다.

Usage
-----
.. code-block:: bash

    # dry-run (기본) — 무엇이 바뀔지만 보여주고 아무것도 쓰지 않음
    python -m scripts.publish_max_single_position_pct \\
        --client-id <UUID> --environment paper --max-single-position-pct 15 \\
        --activated-by ops-jay --reason "increase concentration cap"

    # 실제 발행
    python -m scripts.publish_max_single_position_pct \\
        --client-id <UUID> --environment paper --max-single-position-pct 15 \\
        --activated-by ops-jay --reason "increase concentration cap" --apply

Environment variables
---------------------
Same as the main application (``DATABASE_URL``, etc.) — 이 스크립트는
``postgres_runtime()``을 통해 실제 DB에 연결한다(dry-run 모드도 현재
활성 버전을 조회하기 위해 DB 연결이 필요하다).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from decimal import Decimal, InvalidOperation
from uuid import UUID

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from agent_trading.domain.enums import Environment
from agent_trading.runtime.bootstrap import postgres_runtime
from agent_trading.services.config_version_admin import (
    ALLOWED_ENVIRONMENTS,
    ConfigVersionAdminError,
    publish_max_single_position_pct,
    validate_environment,
)

logger = logging.getLogger(__name__)


def _load_local_dotenv() -> bool:
    if load_dotenv is None:
        return False
    return load_dotenv()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Publish a new config_version with risk.max_single_position_pct "
            "changed (immutable append-only — does not modify existing rows)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --client-id <UUID> --environment paper "
            "--max-single-position-pct 15 --activated-by ops-jay   # dry-run preview\n"
            "  %(prog)s --client-id <UUID> --environment paper "
            "--max-single-position-pct 15 --activated-by ops-jay --apply\n"
        ),
    )
    parser.add_argument("--client-id", required=True, help="Client UUID")
    parser.add_argument(
        "--environment",
        required=True,
        choices=sorted(e.value for e in ALLOWED_ENVIRONMENTS),
        help=(
            "Target environment — only 'paper'/'live' (not 'real': "
            "config_versions.environment's DB CHECK constraint does not accept it)"
        ),
    )
    parser.add_argument(
        "--max-single-position-pct",
        required=True,
        help="New value, 0 < x <= 100 (NAV 대비 단일 종목 최대 비중 %%)",
    )
    parser.add_argument(
        "--activated-by",
        required=True,
        help="Operator identifier — stored in config_versions.activated_by and audit log",
    )
    parser.add_argument("--reason", default=None, help="Optional reason (audit trail)")
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
        validate_environment(environment)
    except (ValueError, ConfigVersionAdminError) as exc:
        logger.error("Invalid --environment: %s (%s)", args.environment, exc)
        return 1

    try:
        new_value = Decimal(args.max_single_position_pct)
    except InvalidOperation:
        logger.error(
            "Invalid --max-single-position-pct (must be a decimal number): %s",
            args.max_single_position_pct,
        )
        return 1

    async with postgres_runtime() as runtime:
        repos = runtime["repositories"]

        if args.dry_run:
            active = await repos.config_versions.get_active(client_id, environment)
            if active is None:
                logger.error(
                    "No active config_version for client_id=%s environment=%s — "
                    "cannot preview (this path only updates an existing active version).",
                    client_id, environment.value,
                )
                return 1
            current_risk = active.config_json.get("risk", {}) if isinstance(active.config_json, dict) else {}
            current_value = current_risk.get("max_single_position_pct") if isinstance(current_risk, dict) else None
            print("DRY-RUN — no changes written.")
            print(f"  client_id                 = {client_id}")
            print(f"  environment               = {environment.value}")
            print(f"  current active version    = {active.config_version_id} (version_tag={active.version_tag})")
            print(f"  current max_single_position_pct = {current_value}")
            print(f"  new max_single_position_pct     = {new_value}")
            print("Re-run with --apply to publish this change.")
            return 0

        try:
            result = await publish_max_single_position_pct(
                repos,
                client_id=client_id,
                environment=environment,
                max_single_position_pct=new_value,
                activated_by=args.activated_by,
                reason=args.reason,
            )
        except ConfigVersionAdminError as exc:
            logger.error("Publish rejected: %s", exc)
            return 1

        print(
            json.dumps(
                {
                    "config_version_id": str(result.new.config_version_id),
                    "previous_config_version_id": str(result.previous.config_version_id),
                    "version_tag": result.new.version_tag,
                    "previous_max_single_position_pct": result.previous_max_single_position_pct,
                    "new_max_single_position_pct": result.new_max_single_position_pct,
                    "activated_at": result.new.activated_at.isoformat() if result.new.activated_at else None,
                },
                indent=2,
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
