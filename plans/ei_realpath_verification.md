# EI 실경로 검증 — Postgres + OpenDART 데이터 기준 P1-A/P1-B Prompt 확인

## 목표

InMemory mock 테스트가 아닌 **실제 Postgres + OpenDART 적재 데이터를 기준**으로
`EventInterpretationAgent._build_user_prompt()`가 P1-A/P1-B 형식의 provenance-rich prompt를 정상 생성하는지 확인한다.

**본 스크립트는 read-only 검증 전용입니다.**
- DB write 없음
- 외부 side effect 없음 (provider 호출 없음, API 호출 없음)
- Postgres row 조회 + prompt 출력/검사만 수행

## 검증 대상 데이터

| 항목 | 값 |
|------|-----|
| Source | OpenDART (금융감독원) |
| Symbol | `030200` |
| Event 건수 | 5건 |
| `published_at` | `2026-05-11T00:00:00Z` (모두 72h window 내) |
| `ingested_at` | `2026-05-11T09:46:06.752Z` (24h 이내 → NOT stale) |
| `source_name` | `opendart` |
| `source_reliability_tier` | `T1` |
| `event_type` | `Y\|임원ㆍ주요주주특정증권등소유상황보고서` |
| `issuer_code` | `00190321` |
| `severity` | `medium` (default → 태그 생략되어야 함) |
| `direction` | `neutral` (default → 태그 생략되어야 함) |

## 검증 항목 (9개)

**Presence check (5개):**
1. `[src:opendart]` 태그 존재
2. `[tier:T1]` 태그 존재
3. `[Y\|임원ㆍ주요주주특정증권등소유상황보고서]` event_type 태그 존재
4. `[2026-05-11]` published_at 태그 존재
5. `[issuer:00190321]` issuer_code 태그 존재

**Absence check (4개):**
6. `⚠️STALE` 미표시 (ingested_at 24h 이내)
7. `[severity:medium]` 미표시 (default 생략)
8. `[severity:...]` 미표시 (모든 severity 태그)
9. `[positive]` / `[negative]` 미표시 (direction=neutral 생략)

## 스크립트: `scripts/ei_realpath_verification.py`

### 동작 순서

1. 현재 시각 출력 + `since=now-72h` 계산값 출력
2. `postgres_runtime()`으로 실제 Postgres 연결
3. `list_by_symbol(symbol="030200", since=since)` 호출 → event 목록 + 각 `published_at` 출력
4. `AssembledContext` + `ScoreResult` 구성
5. `AgentExecutionRequest` 생성
6. `EventInterpretationAgent._build_user_prompt()` 호출
7. Prompt 출력 (header + events block 분리)
8. 9개 검증 항목 pass/fail
9. `exit 0` (all pass) or `exit 1` (fail)

### 코드

```python
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
from uuid import UUID, uuid4

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
            print(f"    event_id={ev.event_id!s:.8s} type={ev.event_type} published={pub} ingested={ing}")

        if not events:
            print(f"  {CROSS_MARK} symbol=030200에 event 없음. 검증 중단.")
            return 1

        # ── 3. AssembledContext 구성 ──
        print(f"\n[3/5] AssembledContext 구성 ...")
        score = ScoreResult(score=75.0, threshold=60.0, reason_codes=["REASON_001"])
        context = AssembledContext(
            request_symbol="030200",
            request_side="BUY",
            request_quantity=10,
            recent_events=tuple(events),
            score=score,
            decision_context_id=UUID("00000000-0000-0000-0000-000000000001"),
            correlation_id="ei-realpath-verify-001",
        )
        print(f"  완료: events={len(context.recent_events)}, score={score.score}")

        # ── 4. AgentExecutionRequest 생성 ──
        print(f"\n[4/5] AgentExecutionRequest 생성 ...")
        request = AgentExecutionRequest(
            decision_context_id=context.decision_context_id,
            correlation_id=context.correlation_id,
            context=context,
        )
        print(f"  완료: correlation_id={request.correlation_id}")

        # ── 5. _build_user_prompt() 호출 → 출력 ──
        print(f"\n[5/5] _build_user_prompt() 호출 ...")
        agent = EventInterpretationAgent()
        prompt = agent._build_user_prompt(request)

        # Prompt 출력 (header + events block 분리)
        lines = prompt.split("\n")
        print(f"\n{'=' * 70}")
        print("  [PROMPT HEADER]")
        print(f"{'=' * 70}")
        for line in lines:
            if line.startswith("  [src:"):
                break
            print(f"  {line}")
        print(f"\n  --- recent events block ({len(events)} events) ---")
        for line in lines:
            if line.startswith("  [src:") or line.startswith("  [tier:") or line.startswith("  ⚠"):
                print(f"  {line}")
        print(f"\n  (prompt total length: {len(prompt)} chars, {len(lines)} lines)")
        print(f"{'=' * 70}")

        # ── 검증 리포트 ──
        print(f"\n\n{'=' * 70}")
        print("  검증 리포트")
        print(f"{'=' * 70}")
        print(f"  사용 DB      : Postgres (실경로)")
        print(f"  대상 symbol  : 030200")
        print(f"  Event 수     : {len(events)}")

        checks: list[tuple[str, bool]] = [
            # Presence
            ('[src:opendart] 태그 존재', "[src:opendart]" in prompt),
            ('[tier:T1] 태그 존재', "[tier:T1]" in prompt),
            ('event_type 태그 존재', "임원ㆍ주요주주특정증권등소유상황보고서" in prompt),
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
```

## 실행 방법

```bash
# .env 로드 (Postgres 연결 정보)
set -a; source .env; set +a

# 검증 스크립트 실행
python -m scripts.ei_realpath_verification

# exit code 확인
echo "Exit code: $?"
```

## 기대 출력 요약

### Prompt event line (정상 케이스)
```
  [src:opendart] [tier:T1] [Y|임원ㆍ주요주주특정증권등소유상황보고서] [2026-05-11] [issuer:00190321] 임원ㆍ주요주주특정증권등소유상황보고서
```

- `⚠️STALE` 없음 (ingested_at=09:46, 24h 이내)
- `[severity:medium]` 없음 (default 생략)
- `[severity:...]` 없음 (모든 severity 태그 생략)
- `[positive]` / `[negative]` 없음 (direction=neutral 생략)

## 위험 요소

| 리스크 | 설명 | 대응 |
|--------|------|------|
| Postgres 연결 실패 | `.env`에 `DATABASE_URL` 미설정 또는 DB 미실행 | `docker-compose up -d db` 확인 |
| symbol=030200 event 부재 | ingestion 이후 데이터 삭제 또는 미적재 | `run_event_ingestion_loop.py`로 재적재 |
| `EventInterpretationAgent()` 생성자 문제 | provider client 없이 생성 가능한지 확인 | `_build_user_prompt()`만 사용하므로 provider 불필요 |

## 완료 보고 형식

1. 생성한 스크립트 파일
2. 실제 실행 명령
3. 조회된 symbol / event count
4. 72h retention 확인 결과
5. provenance tag 확인 결과
6. 생략 태그 확인 결과
7. exit code
8. 남은 리스크 1개
9. 다음 직접 액션 1개
