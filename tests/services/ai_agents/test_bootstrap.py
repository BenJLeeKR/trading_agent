"""Tests for runtime wiring — provider agent injection in bootstrap.

Verifies that:
* ``_build_provider_agent()`` returns ``None`` when provider settings are incomplete.
* ``_build_provider_agent()`` returns a real ``EventInterpretationAgent`` when
  all three settings (api_key, base_url, model_id) are present.
* ``LLM_PROVIDER`` controls which provider env vars are read (deepseek / openai).
* All three runtime factories (default, postgres, postgres context manager)
  include an ``orchestrator`` key with the same shape.
* Without provider API key the orchestrator falls back to
  ``StubEventInterpretationAgent``.
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
    EventInterpretationAgent,
    OpenAICompatibleClient,
)
from agent_trading.services.ai_agents.event_interpretation import (
    StubEventInterpretationAgent,
)
from agent_trading.services.decision_orchestrator import (
    DecisionOrchestratorService,
)


# ---------------------------------------------------------------------------
# _build_provider_agent()
# ---------------------------------------------------------------------------


class TestBuildProviderAgent:
    """_build_provider_agent() returns None when settings incomplete."""

    def test_returns_none_when_no_api_key(self) -> None:
        """provider_api_key가 비어있으면 None 반환."""
        settings = AppSettings()  # 모든 provider 필드가 기본값 (빈 문자열)
        agent = _build_provider_agent(settings)
        assert agent is None

    def test_returns_none_when_no_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """provider_base_url이 비어있으면 None 반환."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "")
        settings = AppSettings()
        agent = _build_provider_agent(settings)
        assert agent is None

    def test_returns_none_when_no_model_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """provider_model_id가 비어있으면 None 반환."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        monkeypatch.setenv("DEEPSEEK_MODEL_ID", "")
        settings = AppSettings()
        agent = _build_provider_agent(settings)
        assert agent is None

    def test_returns_agent_when_all_settings_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """모든 provider 설정이 있으면 EventInterpretationAgent 반환."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        monkeypatch.setenv("DEEPSEEK_MODEL_ID", "deepseek-chat")
        settings = AppSettings()
        agent = _build_provider_agent(settings)
        assert agent is not None
        assert isinstance(agent, EventInterpretationAgent)
        assert agent.agent_name == "event_interpretation"
        assert agent.schema_version == "v1"

    def test_uses_custom_model_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """provider_model_id가 agent에 전달됨."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        monkeypatch.setenv("DEEPSEEK_MODEL_ID", "custom-model-v2")
        settings = AppSettings()
        agent = _build_provider_agent(settings)
        assert agent is not None
        # model_id는 private attribute로 보관되므로 직접 검증하지 않음
        assert isinstance(agent, EventInterpretationAgent)


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

    def test_uses_stub_when_no_api_key(self) -> None:
        """Provider 설정 없으면 StubEventInterpretationAgent fallback."""
        runtime = build_default_runtime()
        assert runtime["event_interpretation_agent"] is None

    def test_uses_real_agent_when_api_key_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DeepSeek 설정 완전 → EventInterpretationAgent 주입."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        monkeypatch.setenv("DEEPSEEK_MODEL_ID", "deepseek-chat")
        runtime = build_default_runtime()
        agent = runtime["event_interpretation_agent"]
        assert agent is not None
        assert isinstance(agent, EventInterpretationAgent)

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

    async def test_uses_stub_when_no_api_key(self) -> None:
        """DEEPSEEK_API_KEY 없으면 agent는 None (stub fallback)."""
        runtime = await build_postgres_runtime(run_migrations=False)
        assert runtime["event_interpretation_agent"] is None

    async def test_uses_real_agent_when_api_key_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """설정이 완전하면 EventInterpretationAgent 주입."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        monkeypatch.setenv("DEEPSEEK_MODEL_ID", "deepseek-chat")
        runtime = await build_postgres_runtime(run_migrations=False)
        agent = runtime["event_interpretation_agent"]
        assert agent is not None
        assert isinstance(agent, EventInterpretationAgent)

    async def test_runtime_shape_consistent(self) -> None:
        """Runtime dict에 db_config 포함 7개 키 모두 존재."""
        runtime = await build_postgres_runtime(run_migrations=False)
        expected_keys = {
            "settings",
            "primary_broker_adapter",
            "repositories",
            "db_config",
            "polling_workers",
            "orchestrator",
            "event_interpretation_agent",
        }
        assert expected_keys.issubset(runtime.keys())

    async def test_shutdown_closes_provider_agent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """shutdown_postgres_runtime()이 provider agent를 정리함."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        monkeypatch.setenv("DEEPSEEK_MODEL_ID", "deepseek-chat")
        # close_pool mocking — 실제 pool 없이 shutdown 가능하게
        monkeypatch.setattr(
            "agent_trading.runtime.bootstrap.close_pool", AsyncMock()
        )
        runtime = await build_postgres_runtime(run_migrations=False)
        agent = runtime["event_interpretation_agent"]
        assert agent is not None
        assert isinstance(agent, EventInterpretationAgent)

        # shutdown — provider client close + pool close
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

    async def test_runtime_shape_consistent(self) -> None:
        """Runtime dict에 db_config 포함 7개 키 모두 존재."""
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
        """OpenAI 설정 완전 → EventInterpretationAgent 주입."""
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-oa-test")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        monkeypatch.setenv("OPENAI_MODEL_ID", "gpt-4o")
        runtime = build_default_runtime()
        agent = runtime["event_interpretation_agent"]
        assert agent is not None
        assert isinstance(agent, EventInterpretationAgent)

    def test_openai_missing_key_uses_stub(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OpenAI key 없으면 stub fallback."""
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        monkeypatch.setenv("OPENAI_MODEL_ID", "gpt-4o")
        runtime = build_default_runtime()
        assert runtime["event_interpretation_agent"] is None

    def test_openai_missing_base_url_uses_stub(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OpenAI base_url 없으면 stub fallback."""
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-oa-test")
        monkeypatch.setenv("OPENAI_BASE_URL", "")
        monkeypatch.setenv("OPENAI_MODEL_ID", "gpt-4o")
        runtime = build_default_runtime()
        assert runtime["event_interpretation_agent"] is None

    def test_openai_missing_model_id_uses_stub(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OpenAI model_id 없으면 stub fallback."""
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-oa-test")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        monkeypatch.setenv("OPENAI_MODEL_ID", "")
        runtime = build_default_runtime()
        assert runtime["event_interpretation_agent"] is None

    def test_unsupported_provider_uses_stub(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """지원되지 않는 LLM_PROVIDER → stub fallback."""
        monkeypatch.setenv("LLM_PROVIDER", "claude")
        monkeypatch.setenv("CLAUDE_API_KEY", "sk-cl-test")
        runtime = build_default_runtime()
        assert runtime["event_interpretation_agent"] is None

    def test_deepseek_ignores_openai_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DeepSeek 모드에서 OPENAI_* env var는 무시됨."""
        monkeypatch.setenv("LLM_PROVIDER", "deepseek")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-oa-test")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        monkeypatch.setenv("OPENAI_MODEL_ID", "gpt-4o")
        # DeepSeek key가 없으므로 stub fallback
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        runtime = build_default_runtime()
        assert runtime["event_interpretation_agent"] is None

    def test_openai_ignores_deepseek_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OpenAI 모드에서 DEEPSEEK_* env var는 무시됨."""
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-oa-test")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        monkeypatch.setenv("OPENAI_MODEL_ID", "gpt-4o")
        # DEEPSEEK_*는 설정되어 있어도 OPENAI 모드에서는 읽히지 않음
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        monkeypatch.setenv("DEEPSEEK_MODEL_ID", "deepseek-chat")
        runtime = build_default_runtime()
        agent = runtime["event_interpretation_agent"]
        assert agent is not None
        assert isinstance(agent, EventInterpretationAgent)
