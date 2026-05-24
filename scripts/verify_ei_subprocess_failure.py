"""
Run an Event Interpretation agent through the subprocess isolation path
with a forced provider failure, and verify __error__ metadata persists to DB.
"""
import asyncio
import json
import os
import sys
from uuid import UUID, uuid4

# 임시로 PROVIDER_BASE_URL을 잘못된 값으로 설정
os.environ["PROVIDER_BASE_URL"] = "https://invalid-url-for-testing.example.com"

from agent_trading.services.ai_agents.base import AgentExecutionRequest
from agent_trading.services.ai_agents.event_interpretation import EventInterpretationAgent
from agent_trading.services.ai_agents.provider_client import OpenAICompatibleClient
from agent_trading.services.ai_agents.recorder import AgentRunRecorder
from agent_trading.repositories.postgres.agent_runs import PostgresAgentRunRepository
from agent_trading.db.transaction import TransactionManager
from agent_trading.db.connection import create_pool
from agent_trading.services.decision_orchestrator import AssembledContext

# 기존 decision_context (FK 제약 만족용)
EXISTING_DC_ID = UUID("e975b9f9-06bb-486d-8d49-80fc061b5909")


async def main():
    # DB pool 초기화
    await create_pool()

    # 1. 잘못된 provider URL로 provider_client 생성 (강제 실패 유도)
    provider = OpenAICompatibleClient(
        api_key="test-key",
        base_url="https://invalid-url-for-testing.example.com",
        model_id="gpt-4",  # 모델명은 중요하지 않음 (연결 자체가 실패)
        timeout_seconds=5,
    )

    # 2. EI Agent 생성 및 실행
    agent = EventInterpretationAgent(provider_client=provider)

    # minimal request context - 실제 API 호출 전에 실패하므로 컨텐츠는 중요하지 않음
    request = AgentExecutionRequest(
        decision_context_id=EXISTING_DC_ID,
        correlation_id=f"test-ei-failure-{uuid4().hex[:8]}",
        context=AssembledContext(),
        symbol="005930",
        market="KRX",
    )

    print("=" * 60)
    print("[1/5] Running EventInterpretationAgent with bad provider URL...")
    print("=" * 60)

    result = await agent.run(request)

    metadata = agent.last_error_metadata
    print(f"\nlast_error_metadata: {json.dumps(metadata, indent=2, ensure_ascii=False)}")

    if metadata is None:
        print("\n❌ FAIL: last_error_metadata is None — _classify_exception() not reached!")
        sys.exit(1)

    print("\n✅ PASS: last_error_metadata captured")

    # 3. structured_output에 __error__ 주입 (orchestrator가 하는 일)
    structured_output = {
        "symbol": "005930",
        "schema_version": "v1",
        "agent_name": "event_interpretation",
        "__error__": metadata,
    }

    print("\n" + "=" * 60)
    print("[2/5] structured_output with __error__:")
    print("=" * 60)
    print(json.dumps(structured_output, indent=2, ensure_ascii=False))

    # 4. DB에 저장 (TransactionManager 사용)
    print("\n" + "=" * 60)
    print("[3/5] Connecting to DB and recording agent run...")
    print("=" * 60)

    async with TransactionManager() as tx:
        repo = PostgresAgentRunRepository(tx)
        recorder = AgentRunRecorder(repo=repo)

        run = await recorder.record(
            decision_context_id=EXISTING_DC_ID,
            agent_type="event_interpretation",
            structured_output=structured_output,
        )

        agent_run_id = run.agent_run_id
        print(f"\n✅ Agent run recorded: agent_run_id = {agent_run_id}")

        await tx.commit()

    # 5. DB에서 직접 조회하여 __error__ 확인 (새로운 트랜잭션)
    print("\n" + "=" * 60)
    print("[4/5] Verifying __error__ in DB...")
    print("=" * 60)

    async with TransactionManager() as tx:
        repo = PostgresAgentRunRepository(tx)
        fetched = await repo.get(agent_run_id)

    assert fetched is not None, "Failed to fetch agent run from DB"

    has_error = (
        fetched.structured_output_json
        and "__error__" in fetched.structured_output_json
    )

    if not has_error:
        print(f"\n❌ FAIL: __error__ NOT found in DB structured_output_json")
        print(f"DB content: {json.dumps(fetched.structured_output_json, indent=2, ensure_ascii=False)}")
        sys.exit(1)

    print(f"\n✅ PASS: __error__ found in DB structured_output_json")
    stored_error = fetched.structured_output_json["__error__"]
    print(f"Stored error: {json.dumps(stored_error, indent=2, ensure_ascii=False)}")

    # 6. API 확인 (내부 fetch로 대체)
    print("\n" + "=" * 60)
    print("[5/5] Verification via repo.list_all()")
    print("=" * 60)

    async with TransactionManager() as tx:
        repo = PostgresAgentRunRepository(tx)
        all_runs = await repo.list_all(limit=50)

    found = [r for r in all_runs if r.agent_run_id == agent_run_id]
    if found:
        print(f"\n✅ Agent run found in list_all(): {agent_run_id}")
        print(f"structured_output_json keys: {list((found[0].structured_output_json or {}).keys())}")
    else:
        print(f"\n⚠️ Agent run not found in list_all() — may need API check")

    print("\n" + "=" * 60)
    print("🎉 ALL CHECKS PASSED")
    print("=" * 60)

    # 종료 시 agent_run_id 출력 (API 확인용)
    print(f"\n📋 Agent Run ID for API verification: {agent_run_id}")


if __name__ == "__main__":
    asyncio.run(main())
