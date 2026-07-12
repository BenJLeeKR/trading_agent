#!/usr/bin/env python3
"""UNIV-4 진단용 read-only staleness 감시 스크립트.

``[DESIGN] universe_sourcing_momentum_overlay_enablement_v1.md`` §2.3의
축소안 — KIS 지수 구성종목 전체 목록 API가 확인되지 않아 자동 갱신 대신,
현재 ``instrument_index_memberships``의 가장 최근 반영 시각을 조회해 21일
초과 시 경고만 남긴다. DB에 어떤 것도 쓰지 않는다(순수 관측용).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, timezone, datetime

from dotenv import load_dotenv

load_dotenv(".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("check_index_membership_staleness")


async def main() -> None:
    from agent_trading.runtime.bootstrap import postgres_runtime
    from agent_trading.services.index_membership_staleness import (
        evaluate_index_membership_staleness,
    )

    async with postgres_runtime(run_migrations=False) as runtime:
        repos = runtime["repositories"]
        latest = await repos.instrument_index_memberships.get_latest_effective_from()

        today = datetime.now(timezone.utc).date()
        report = evaluate_index_membership_staleness(latest, as_of=today)

        print(json.dumps(
            {
                "latest_effective_from": (
                    report.latest_effective_from.isoformat()
                    if report.latest_effective_from
                    else None
                ),
                "as_of": report.as_of.isoformat(),
                "age_days": report.age_days,
                "threshold_days": report.threshold_days,
                "is_stale": report.is_stale,
            },
            ensure_ascii=False,
            indent=2,
        ))

        if report.is_stale:
            logger.warning(
                "index_membership staleness: 마지막 반영 %s (age=%s일, threshold=%d일) "
                "— 21일 초과, 수동 업로드 절차 재실행 필요 "
                "([RUNBOOK] index_membership_source_package_apply.md 참고).",
                report.latest_effective_from,
                report.age_days,
                report.threshold_days,
            )
        else:
            logger.info(
                "index_membership staleness: 정상 (마지막 반영 %s, age=%d일).",
                report.latest_effective_from,
                report.age_days,
            )


if __name__ == "__main__":
    asyncio.run(main())
