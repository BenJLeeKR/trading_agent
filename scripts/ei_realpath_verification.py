#!/usr/bin/env python3
"""EI 실경로 검증: Postgres + OpenDART 데이터 → _build_user_prompt() 출력 확인.

Read-only verification script.
- No DB writes.
- No external provider/API calls.
- Only queries Postgres, builds EI prompt, and verifies tags.

사용법:
    python -m scripts.ei_realpath_verification

Exit code:
    0 — all checks passed
    1 — one or more checks failed
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import UUID

from agent_trading.runtime.bootstrap import postgres_runtime
from agent_trading.services.ai_agents.base import AgentExecutionRequest
from agent_trading.services.ai_agents.event_interpretation import EventInterpretationAgent
from agent_trading.services.decision_orchestrator import AssembledContext, ScoreResult

logger = logging.getLogger(__name__)

CHECK_MARK = "\u2705"
CROSS_MARK = "\u274c"
SEP = "=" * 70


async def verify() -> int:
    """실경로 검증 메인 로직."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=72)

    print(SEP)
    print("  EI 실경로 검증 시작")
    print(SEP)
    print(f"  현재 시각 (UTC): {now.strftime('%Y-%m-%d %H:%M:%S')}Z")
    print(f"  72h since       : {since.strftime('%Y-%m-%d %H:%M:%S')}Z")
    print(SEP)

    # ── 1. Postgres 연결 ──
    print("\n[1/5] Postgres 연결 ...")
    async with postgres_runtime() as runtime:
        repos = runtime["repositories"]

        # ── 2. list_by_symbol() 호출 ──
        print(f"\n[2/5] list_by_symbol(symbol='030200', since={since.strftime('%Y-%m-%d %H:%M')}) ...")
        events = await repos.external_events.list_by_symbol(symbol="030200", since=since)
        print(f"  조회 결과: {len(events)}건")
        for ev in events:
            pub = ev.published_at.strftime("%Y-%m-%d %H:%MZ") if ev.published_at else "N/A"
            ing = ev.ingested_at.strftime("%Y-%m-%d %H:%MZ") if ev.ingested_at else "N/A"
            print(f"    event_id={str(ev.event_id)[:8]} type={ev.event_type} "
                  f"published={pub} ingested={ing}")

        if not events:
            print(f"  {CROSS_MARK} symbol=030200에 event 없음. 검증 중단.")
            return 1

        # ── 3. AssembledContext 구성 ──
        print(f"\n[3/5] AssembledContext 구성 ...")
        score = ScoreResult(score=75.0, threshold=60.0, reason_codes=["REASON_001"])
        context = AssembledContext(
            recent_events=tuple(events),
            score=score,
        )
        print(f"  완료: events={len(context.recent_events)}, score={score.score}")

        # ── 4. AgentExecutionRequest 생성 ──
        print(f"\n[4/5] AgentExecutionRequest 생성 ...")
        request = AgentExecutionRequest(
            decision_context_id=UUID("00000000-0000-0000-0000-000000000001"),
            correlation_id="ei-realpath-verify-001",
            context=context,
        )
        print(f"  완료: correlation_id={request.correlation_id}")

        # ── 5. _build_user_prompt() 호출 → 출력 ──
        print(f"\n[5/5] _build_user_prompt() 호출 ...")
        agent = EventInterpretationAgent(provider_client=AsyncMock())
        prompt = agent._build_user_prompt(request)

        # Prompt 출력 (header + events block 분리)
        lines = prompt.split("\n")
        print(f"\n{SEP}")
        print("  [PROMPT HEADER]")
        print(SEP)
        for line in lines:
            if line.startswith("  [src:"):
                break
            print(f"  {line}")
        print(f"\n  --- recent events block ({len(events)} events) ---")
        for line in lines:
            if line.startswith("  [src:") or line.startswith("  [tier:") or line.startswith("  ⚠"):
                print(f"  {line}")
        print(f"\n  (prompt total length: {len(prompt)} chars, {len(lines)} lines)")
        print(SEP)

        # ── 검증 리포트 ──
        print(f"\n\n{SEP}")
        print("  검증 리포트")
        print(SEP)
        print(f"  사용 DB      : Postgres (실경로)")
        print(f"  대상 symbol  : 030200")
        print(f"  Event 수     : {len(events)}")

        checks: list[tuple[str, bool]] = [
            # Presence
            ('[src:opendart] 태그 존재', "[src:opendart]" in prompt),
            ('[tier:T1] 태그 존재', "[tier:T1]" in prompt),
            ('event_type 태그 존재 (임원ㆍ주요주주특정증권등소유상황보고서)',
             "임원ㆍ주요주주특정증권등소유상황보고서" in prompt),
            ('[2026-05-11] published_at 태그 존재', "[2026-05-11]" in prompt),
            ('[issuer:00190321] 태그 존재', "[issuer:00190321]" in prompt),
            # Absence
            ('⚠️STALE 미표시 (ingested_at 24h 이내)', "⚠️STALE" not in prompt),
            ('[severity:medium] 미표시 (default 생략)', "[severity:medium]" not in prompt),
            ('[severity:...] 미표시 (모든 severity 태그 생략)',
             "[severity:" not in prompt),
            ('[positive] / [negative] 미표시 (direction=neutral 생략)',
             "[positive]" not in prompt and "[negative]" not in prompt),
            # Header correctness
            ('Recent events header = (5)', "Recent events (5):" in prompt),
        ]

        all_pass = True
        for desc, passed in checks:
            icon = CHECK_MARK if passed else CROSS_MARK
            print(f"  {icon} {desc}")
            if not passed:
                all_pass = False

        print(f"\n  {'=' * 40}")
        print(f"  총 {len(checks)}개 항목 검증")
        if all_pass:
            print(f"  결과: {CHECK_MARK} ALL PASS")
        else:
            print(f"  결과: {CROSS_MARK} FAIL")
        print(f"  {'=' * 40}")

        return 0 if all_pass else 1


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    return asyncio.run(verify())


if __name__ == "__main__":
    sys.exit(main())
