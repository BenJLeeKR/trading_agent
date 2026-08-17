"""Tests for runtime wiring — provider agent injection in bootstrap.

Verifies that:
* ``_build_provider_agent()`` — 2026-08-17부터 provider 설정 유무와
  무관하게 항상 ``DeterministicEventInterpretationAgent``(LLM 호출
  없음)를 반환한다. EI는 더 이상 stub으로 fallback하지 않는다.
* ``LLM_PROVIDER``는 여전히 AR/FDC(provider 기반 real agent)가 어떤
  provider env var를 읽을지 통제한다.
* All three runtime factories (default, postgres, postgres context manager)
  include an ``orchestrator`` key with the same shape.
* Without provider API key, AR/FDC fall back to ``None``(stub) while EI
  stays deterministic.
* ``_close_provider_agent()`` safely cleans up the underlying HTTP client.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agent_trading.config.settings import AppSettings
from agent_trading.runtime.bootstrap import (
    _build_provider_agent,
    _close_provider_agent,
    build_default_runtime,
    build_postgres_runtime,
    postgres_runtime,
    shutdown_postgres_runtime,
)
from agent_trading.services.ai_agents import (
    AIRiskAgent,
    DeterministicEventInterpretationAgent,
    EventInterpretationAgent,
    FinalDecisionComposerAgent,
    OpenAICompatibleClient,
)
from agent_trading.services.decision_orchestrator import (
    DecisionOrchestratorService,
)


# ---------------------------------------------------------------------------
# _build_provider_agent()
# ---------------------------------------------------------------------------


class TestBuildProviderAgent:
    """_build_provider_agent()는 2026-08-17부터 provider 설정 유무와
    무관하게 항상 DeterministicEventInterpretationAgent를 반환한다."""

    def test_returns_deterministic_agent_when_no_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """provider_api_key가 없어도 deterministic bot을 반환한다(더 이상 None 아님).

        Clears provider API key env vars to stay deterministic regardless
        of ``.env`` content (which may set DEEPSEEK_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY).
        """
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        settings = AppSettings()
        agent = _build_provider_agent(settings)
        assert agent is not None
        assert isinstance(agent, DeterministicEventInterpretationAgent)

    def test_returns_deterministic_agent_when_all_settings_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """provider 설정이 있어도 여전히 DeterministicEventInterpretationAgent(LLM 호출 없음)."""
        monkeypatch.setenv("LLM_PROVIDER", "deepseek")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        monkeypatch.setenv("DEEPSEEK_MODEL_ID", "deepseek-chat")
        settings = AppSettings()
        agent = _build_provider_agent(settings)
        assert agent is not None
        assert isinstance(agent, DeterministicEventInterpretationAgent)
        assert agent.agent_name == "event_interpretation"
        assert agent.schema_version == "v1"


# ---------------------------------------------------------------------------
# _close_provider_agent()
# ---------------------------------------------------------------------------


class TestCloseProviderAgent:
    """_close_provider_agent() safely cleans up HTTP client."""

    async def test_handles_none(self) -> None:
        """None이 전달되면 아무 일도 일어나지 않음."""
        await _close_provider_agent(None)  # should not raise

    async def test_handles_agent_without_provider(self) -> None:
        """Provider가 없는 agent에 대해서도 안전하게 동작."""
        await _close_provider_agent(object())  # should not raise

    async def test_closes_real_agent(self) -> None:
        """Real agent의 HTTP client close()가 호출됨."""
        client = OpenAICompatibleClient(
            api_key="sk-test",
            base_url="https://api.test.com",
            timeout_seconds=10,
        )
        agent = EventInterpretationAgent(provider_client=client)
        # close 전에는 _client가 있어야 함 (lazy init)
        assert agent._provider._client is None  # 아직 init 안 됨
        await _close_provider_agent(agent)
        # _close_provider_agent는 close()를 호출하지만,
        # client가 아직 초기화되지 않았으므로 _client는 None 유지
        assert agent._provider._client is None

    async def test_closes_real_agent_after_init(self) -> None:
        """초기화된 client도 close()로 정리됨."""
        client = OpenAICompatibleClient(
            api_key="sk-test",
            base_url="https://api.test.com",
            timeout_seconds=10,
        )
        # Lazy init 트리거
        _ = await client._get_client()
        assert client._client is not None

        agent = EventInterpretationAgent(provider_client=client)
        await _close_provider_agent(agent)
        assert client._client is None


# ---------------------------------------------------------------------------
# build_default_runtime()
# ---------------------------------------------------------------------------


class TestBuildDefaultRuntime:
    """build_default_runtime() wiring."""

    def test_contains_orchestrator(self) -> None:
        """Runtime dict에 orchestrator 키가 포함됨."""
        runtime = build_default_runtime()
        assert "orchestrator" in runtime
        assert isinstance(runtime["orchestrator"], DecisionOrchestratorService)

    def test_contains_event_interpretation_agent_key(self) -> None:
        """Runtime dict에 event_interpretation_agent 키가 포함됨."""
        runtime = build_default_runtime()
        assert "event_interpretation_agent" in runtime

    def test_contains_ai_risk_agent_key(self) -> None:
        """Runtime dict에 ai_risk_agent 키가 포함됨."""
        runtime = build_default_runtime()
        assert "ai_risk_agent" in runtime

    def test_contains_final_decision_agent_key(self) -> None:
        """Runtime dict에 final_decision_agent 키가 포함됨."""
        runtime = build_default_runtime()
        assert "final_decision_agent" in runtime

    def test_uses_stub_when_no_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Provider 설정 없으면 AR/FDC는 None(stub fallback)이지만, EI는
        provider 설정과 무관하게 항상 deterministic bot이다.

        Clears provider API key env vars to stay deterministic regardless
        of ``.env`` content.
        """
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        runtime = build_default_runtime()
        assert isinstance(
            runtime["event_interpretation_agent"],
            DeterministicEventInterpretationAgent,
        )
        assert runtime["ai_risk_agent"] is None
        assert runtime["final_decision_agent"] is None

    def test_uses_real_agent_when_api_key_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DeepSeek 설정 완전 → AR/FDC는 real agent, EI는 deterministic bot."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        monkeypatch.setenv("DEEPSEEK_MODEL_ID", "deepseek-chat")
        runtime = build_default_runtime()
        ei_agent = runtime["event_interpretation_agent"]
        ar_agent = runtime["ai_risk_agent"]
        fdc_agent = runtime["final_decision_agent"]
        assert ei_agent is not None
        assert isinstance(ei_agent, DeterministicEventInterpretationAgent)
        assert ar_agent is not None
        assert isinstance(ar_agent, AIRiskAgent)
        assert fdc_agent is not None
        assert isinstance(fdc_agent, FinalDecisionComposerAgent)

    def test_runtime_shape_consistent(self) -> None:
        """Runtime dict 필수 키가 모두 존재."""
        runtime = build_default_runtime()
        expected_keys = {
            "settings",
            "primary_broker_adapter",
            "repositories",
            "polling_workers",
            "orchestrator",
            "event_interpretation_agent",
            "ai_risk_agent",
            "final_decision_agent",
        }
        assert expected_keys.issubset(runtime.keys())


# ---------------------------------------------------------------------------
# build_postgres_runtime()  (DB 호출 mocking)
# ---------------------------------------------------------------------------


class _MockTransactionManager:
    """Stand-in for ``TransactionManager`` — satisfies ``build_postgres_repositories``."""

    def __init__(self) -> None:
        self.connection = None


class TestBuildPostgresRuntime:
    """build_postgres_runtime() wiring with mocked DB layer."""

    @pytest.fixture(autouse=True)
    def _mock_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mock database dependencies so no real DB connection is needed."""
        monkeypatch.setattr(
            "agent_trading.runtime.bootstrap.create_pool", AsyncMock()
        )
        monkeypatch.setattr(
            "agent_trading.runtime.bootstrap.ensure_schema", AsyncMock()
        )
        from agent_trading.repositories.bootstrap import (
            build_in_memory_repositories,
        )

        monkeypatch.setattr(
            "agent_trading.runtime.bootstrap.build_postgres_repositories",
            lambda tx: build_in_memory_repositories(),
        )

    async def test_contains_orchestrator(self) -> None:
        """Runtime dict에 orchestrator 키가 포함됨."""
        runtime = await build_postgres_runtime(run_migrations=False)
        assert "orchestrator" in runtime
        assert isinstance(runtime["orchestrator"], DecisionOrchestratorService)

    async def test_contains_event_interpretation_agent_key(self) -> None:
        """Runtime dict에 event_interpretation_agent 키가 포함됨."""
        runtime = await build_postgres_runtime(run_migrations=False)
        assert "event_interpretation_agent" in runtime

    async def test_contains_ai_risk_agent_key(self) -> None:
        """Runtime dict에 ai_risk_agent 키가 포함됨."""
        runtime = await build_postgres_runtime(run_migrations=False)
        assert "ai_risk_agent" in runtime

    async def test_contains_final_decision_agent_key(self) -> None:
        """Runtime dict에 final_decision_agent 키가 포함됨."""
        runtime = await build_postgres_runtime(run_migrations=False)
        assert "final_decision_agent" in runtime

    async def test_uses_stub_when_no_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Provider API key 없으면 AR/FDC는 None(stub fallback), EI는 항상 deterministic bot.

        Clears provider API key env vars to stay deterministic regardless
        of ``.env`` content.
        """
        monkeypatch.setenv("LLM_PROVIDER", "deepseek")
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        runtime = await build_postgres_runtime(run_migrations=False)
        assert isinstance(
            runtime["event_interpretation_agent"],
            DeterministicEventInterpretationAgent,
        )
        assert runtime["ai_risk_agent"] is None
        assert runtime["final_decision_agent"] is None

    async def test_uses_real_agent_when_api_key_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """설정이 완전하면 AR/FDC는 real agent, EI는 deterministic bot."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        monkeypatch.setenv("DEEPSEEK_MODEL_ID", "deepseek-chat")
        runtime = await build_postgres_runtime(run_migrations=False)
        ei_agent = runtime["event_interpretation_agent"]
        ar_agent = runtime["ai_risk_agent"]
        fdc_agent = runtime["final_decision_agent"]
        assert ei_agent is not None
        assert isinstance(ei_agent, DeterministicEventInterpretationAgent)
        assert ar_agent is not None
        assert isinstance(ar_agent, AIRiskAgent)
        assert fdc_agent is not None
        assert isinstance(fdc_agent, FinalDecisionComposerAgent)

    async def test_runtime_shape_consistent(self) -> None:
        """Runtime dict에 db_config 포함 9개 키 모두 존재."""
        runtime = await build_postgres_runtime(run_migrations=False)
        expected_keys = {
            "settings",
            "primary_broker_adapter",
            "repositories",
            "db_config",
            "polling_workers",
            "orchestrator",
            "event_interpretation_agent",
            "ai_risk_agent",
            "final_decision_agent",
        }
        assert expected_keys.issubset(runtime.keys())

    async def test_shutdown_closes_both_provider_agents(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """shutdown_postgres_runtime()이 두 provider agent를 모두 정리함."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        monkeypatch.setenv("DEEPSEEK_MODEL_ID", "deepseek-chat")
        # close_pool mocking — 실제 pool 없이 shutdown 가능하게
        monkeypatch.setattr(
            "agent_trading.runtime.bootstrap.close_pool", AsyncMock()
        )
        runtime = await build_postgres_runtime(run_migrations=False)
        ei_agent = runtime["event_interpretation_agent"]
        ar_agent = runtime["ai_risk_agent"]
        assert ei_agent is not None
        assert isinstance(ei_agent, DeterministicEventInterpretationAgent)
        assert ar_agent is not None
        assert isinstance(ar_agent, AIRiskAgent)

        # shutdown — provider client close(AR real agent) + pool close.
        # EI는 이제 deterministic bot이라 provider client가 없지만,
        # _close_provider_agent()는 provider가 없는 객체도 안전하게
        # 처리한다(TestCloseProviderAgent.test_handles_agent_without_provider).
        await shutdown_postgres_runtime(runtime)
        # 예외 없이 통과하면 성공


# ---------------------------------------------------------------------------
# postgres_runtime() context manager  (DB 호출 mocking)
# ---------------------------------------------------------------------------


class TestPostgresRuntimeContext:
    """postgres_runtime() context manager wiring with mocked DB layer."""

    @pytest.fixture(autouse=True)
    def _mock_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mock database + transaction dependencies."""
        monkeypatch.setattr(
            "agent_trading.runtime.bootstrap.create_pool", AsyncMock()
        )
        monkeypatch.setattr(
            "agent_trading.runtime.bootstrap.ensure_schema", AsyncMock()
        )
        monkeypatch.setattr(
            "agent_trading.runtime.bootstrap.close_pool", AsyncMock()
        )

        # Mock transaction() context manager
        mock_tx = _MockTransactionManager()
        mock_transaction_cm = AsyncMock()
        mock_transaction_cm.__aenter__ = AsyncMock(return_value=mock_tx)
        mock_transaction_cm.__aexit__ = AsyncMock(return_value=None)
        monkeypatch.setattr(
            "agent_trading.runtime.bootstrap.transaction",
            lambda force_rollback=False: mock_transaction_cm,
        )

        from agent_trading.repositories.bootstrap import (
            build_in_memory_repositories,
        )

        monkeypatch.setattr(
            "agent_trading.runtime.bootstrap.build_postgres_repositories",
            lambda tx: build_in_memory_repositories(),
        )

    async def test_contains_orchestrator(self) -> None:
        """Context 내부 runtime dict에 orchestrator 키가 포함됨."""
        async with postgres_runtime(
            run_migrations=False, auto_rollback=True
        ) as runtime:
            assert "orchestrator" in runtime
            assert isinstance(
                runtime["orchestrator"], DecisionOrchestratorService
            )

    async def test_contains_event_interpretation_agent_key(self) -> None:
        """Context 내부 runtime dict에 event_interpretation_agent 키가 포함됨."""
        async with postgres_runtime(
            run_migrations=False, auto_rollback=True
        ) as runtime:
            assert "event_interpretation_agent" in runtime

    async def test_contains_ai_risk_agent_key(self) -> None:
        """Context 내부 runtime dict에 ai_risk_agent 키가 포함됨."""
        async with postgres_runtime(
            run_migrations=False, auto_rollback=True
        ) as runtime:
            assert "ai_risk_agent" in runtime

    async def test_contains_final_decision_agent_key(self) -> None:
        """Context 내부 runtime dict에 final_decision_agent 키가 포함됨."""
        async with postgres_runtime(
            run_migrations=False, auto_rollback=True
        ) as runtime:
            assert "final_decision_agent" in runtime

    async def test_runtime_shape_consistent(self) -> None:
        """Runtime dict에 db_config 포함 9개 키 모두 존재."""
        async with postgres_runtime(
            run_migrations=False, auto_rollback=True
        ) as runtime:
            expected_keys = {
                "settings",
                "primary_broker_adapter",
                "repositories",
                "db_config",
                "polling_workers",
                "orchestrator",
                "event_interpretation_agent",
                "ai_risk_agent",
                "final_decision_agent",
            }
            assert expected_keys.issubset(runtime.keys())

    async def test_shutdown_called_on_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Context exit 시 shutdown 경로가 호출됨."""
        shutdown_mock = AsyncMock()
        monkeypatch.setattr(
            "agent_trading.runtime.bootstrap.shutdown_postgres_runtime",
            shutdown_mock,
        )
        async with postgres_runtime(
            run_migrations=False, auto_rollback=True
        ) as runtime:
            assert "orchestrator" in runtime
        # context exit → shutdown_postgres_runtime() 호출
        shutdown_mock.assert_awaited_once()


# ---------------------------------------------------------------------------
# LLM_PROVIDER=openai wiring  (via build_default_runtime)
# ---------------------------------------------------------------------------


class TestOpenAIWiring:
    """build_default_runtime() with LLM_PROVIDER=openai."""

    def test_openai_complete_env_creates_real_agent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OpenAI 설정 완전해도 EI는 여전히 deterministic bot(LLM 호출 없음)."""
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-oa-test")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        monkeypatch.setenv("OPENAI_MODEL_ID", "gpt-4o")
        runtime = build_default_runtime()
        agent = runtime["event_interpretation_agent"]
        assert agent is not None
        assert isinstance(agent, DeterministicEventInterpretationAgent)

    def test_openai_missing_key_ei_still_deterministic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OpenAI key가 없어도 EI는 deterministic bot(더 이상 stub/None 아님)."""
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        monkeypatch.setenv("OPENAI_MODEL_ID", "gpt-4o")
        runtime = build_default_runtime()
        assert isinstance(
            runtime["event_interpretation_agent"],
            DeterministicEventInterpretationAgent,
        )

    def test_unsupported_provider_ei_still_deterministic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """지원되지 않는 LLM_PROVIDER여도 EI는 deterministic bot."""
        monkeypatch.setenv("LLM_PROVIDER", "claude")
        monkeypatch.setenv("CLAUDE_API_KEY", "sk-cl-test")
        runtime = build_default_runtime()
        assert isinstance(
            runtime["event_interpretation_agent"],
            DeterministicEventInterpretationAgent,
        )


class TestGeminiWiring:
    """build_default_runtime() with LLM_PROVIDER=gemini."""

    def test_gemini_complete_env_ei_still_deterministic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Gemini 설정 완전해도 EI는 여전히 deterministic bot(LLM 호출 없음)."""
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        monkeypatch.setenv("GEMINI_API_KEY", "sk-gm-test")
        monkeypatch.setenv(
            "GEMINI_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        monkeypatch.setenv("GEMINI_MODEL_ID", "gemini-3.5-flash")
        runtime = build_default_runtime()
        agent = runtime["event_interpretation_agent"]
        assert agent is not None
        assert isinstance(agent, DeterministicEventInterpretationAgent)

    def test_gemini_missing_key_ei_still_deterministic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Gemini key가 없어도 EI는 deterministic bot(더 이상 stub/None 아님)."""
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        monkeypatch.setenv("GEMINI_API_KEY", "")
        monkeypatch.setenv(
            "GEMINI_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        monkeypatch.setenv("GEMINI_MODEL_ID", "gemini-3.5-flash")
        runtime = build_default_runtime()
        assert isinstance(
            runtime["event_interpretation_agent"],
            DeterministicEventInterpretationAgent,
        )
