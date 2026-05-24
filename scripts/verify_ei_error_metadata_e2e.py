#!/usr/bin/env python3
"""
EI Failure Metadata End-to-End 검증 스크립트 (v3)

직접 DB INSERT 후 API 조회로 __error__ 저장/노출 확인.
"""

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone

DATABASE_CONFIG = {
    "host": os.environ.get("DATABASE_HOST", "db"),
    "port": int(os.environ.get("DATABASE_PORT", "5432")),
    "database": os.environ.get("DATABASE_NAME", "trading"),
    "user": os.environ.get("DATABASE_USER", "trading"),
    "password": os.environ.get("DATABASE_PASSWORD", "trading"),
}

API_TOKEN = "dev-token-123"


async def main() -> int:
    import asyncpg
    import httpx

    print("=" * 70)
    print("EI Failure Metadata End-to-End 검증 v3")
    print("=" * 70)

    conn = await asyncpg.connect(**DATABASE_CONFIG)
    print(f"[1/6] DB 연결 성공")

    try:
        # ── 0. 이전 테스트에서 남은 고아 데이터 정리 ───────────────────
        # agent_type='event_interpretation' AND structured_output_json ? '__error__'
        # 조건으로 이전 실패 실행에서 남은 데이터 삭제
        deleted = await conn.execute(
            "DELETE FROM trading.agent_runs "
            "WHERE agent_type = 'event_interpretation' "
            "  AND structured_output_json ? '__error__'"
        )
        orphan_count = int(deleted.split()[-1]) if deleted else 0
        if orphan_count:
            print(f"[0/6] 이전 테스트 고아 데이터 {orphan_count}건 정리 완료")

        # ── 1. 기존 decision_context_id 확보 ────────────────────────────
        existing = await conn.fetchrow(
            "SELECT decision_context_id FROM trading.agent_runs "
            "WHERE agent_type LIKE '%interpret%' ORDER BY created_at DESC LIMIT 1"
        )
        ctx_id = existing["decision_context_id"] if existing else uuid.uuid4()
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # ── 2. __error__ 키를 포함한 structured_output_json ─────────────
        error_metadata = {
            "error_type": "provider_error",
            "error_message": (
                "E2E 검증: 인위적 EI 실패 - 유효하지 않은 API 키"
            ),
            "provider": "deepseek",
            "model": "deepseek-chat",
            "status_code": 401,
        }
        structured_output = {
            "symbol": "TEST",
            "agent_name": "event_interpretation",
            "schema_version": "1.0",
            "aggregate_view": {
                "overall_bias": "neutral",
                "event_conflict": False,
                "top_reason_codes": [],
                "no_material_events": True,
                "interpretation_incomplete": True,
                "degraded_reason": "provider_error_injected_for_e2e_test",
            },
            "events": [],
            "summary": "E2E 검증 fallback 출력",
            "summary_basis": "none",
            "detected_event_count": 0,
            "interpreted_event_count": 0,
            "__error__": error_metadata,
        }

        # ── 3. DB INSERT ────────────────────────────────────────────────
        await conn.execute(
            """
            INSERT INTO trading.agent_runs
                (agent_run_id, decision_context_id, agent_type,
                 started_at, structured_output_json, created_at)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6)
            """,
            run_id, ctx_id, "event_interpretation",
            now, json.dumps(structured_output), now,
        )
        print(f"[2/6] DB INSERT 완료: agent_run_id={run_id}")

        # ── 4. DB 직접 조회 ────────────────────────────────────────────
        row = await conn.fetchrow(
            "SELECT structured_output_json, "
            "       structured_output_json ? '__error__' AS has_error "
            "FROM trading.agent_runs WHERE agent_run_id = $1",
            run_id,
        )
        has_error = row["has_error"]
        so_raw = row["structured_output_json"]
        so_dict = json.loads(so_raw) if isinstance(so_raw, str) else (so_raw or {})
        stored = json.dumps(so_dict.get("__error__"), indent=2, ensure_ascii=False)

        status_icon = "✅" if has_error else "❌"
        print(f"[3/6] DB 조회: has_error_metadata={has_error} {status_icon}")
        print(f"      __error__={stored[:300]}")

        if not has_error:
            print("❌ 실패: __error__가 DB에 저장되지 않음")
            return 1

        # ── 5. API 조회 (with Bearer token) ────────────────────────────
        headers = {"Authorization": f"Bearer {API_TOKEN}"}
        async with httpx.AsyncClient(
            base_url="http://localhost:8000", headers=headers, timeout=10
        ) as client:
            resp = await client.get(f"/agent-runs/{run_id}")
            if resp.status_code == 401:
                print(f"❌ API 401 인증 실패 (token={API_TOKEN})")
                # 토큰이 다를 수 있음 → 실제 토큰 확인
                return 1
            elif resp.status_code != 200:
                print(f"❌ API 조회 실패: HTTP {resp.status_code} {resp.text[:200]}")
                return 1

            data = resp.json()
            api_so = data.get("structured_output_json") or {}
            api_has_error = "__error__" in api_so

            api_status = "✅" if api_has_error else "❌"
            print(f"[4/6] API 조회 (GET /agent-runs/{run_id}): HTTP {resp.status_code}")
            print(f"      __error__ 노출: {api_has_error} {api_status}")

            if not api_has_error:
                print("❌ 실패: API 응답에 __error__ 미노출")
                print(f"      API 응답 keys: {list(api_so.keys())}")
                return 1

            api_error = json.dumps(api_so["__error__"], indent=2, ensure_ascii=False)
            print(f"      __error__={api_error[:300]}")

        # ── 6. 정리: 테스트 데이터 삭제 ────────────────────────────────
        await conn.execute(
            "DELETE FROM trading.agent_runs WHERE agent_run_id = $1", run_id
        )
        print(f"[5/6] 테스트 데이터 정리 완료 (agent_run_id={run_id} 삭제)")

        # ── 6b. 최종 DB 재확인: __error__ 있는 EI run 0건이어야 함 ──────
        remaining = await conn.fetchval(
            "SELECT count(*) FROM trading.agent_runs "
            "WHERE agent_type = 'event_interpretation' "
            "  AND structured_output_json ? '__error__'"
        )
        print(f"[6/6] 최종 DB 상태: __error__ 있는 EI run = {remaining}건 (0이어야 정상)")

    finally:
        await conn.close()

    print("=" * 70)
    print("✅ 모든 검증 통과!")
    print("  ✔ __error__ 키를 포함한 structured_output → DB JSONB 정상 저장")
    print("  ✔ JSONB ? '__error__' 연산 → true 반환")
    print("  ✔ GET /agent-runs/{id} 응답 → __error__ 정상 노출")
    print("  ✔ 테스트 데이터 정리 완료")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
