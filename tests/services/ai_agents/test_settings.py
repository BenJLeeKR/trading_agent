"""Tests for LLM provider environment variable resolution.

Verifies that ``AppSettings`` resolves ``provider_*`` fields based on
the ``LLM_PROVIDER`` environment variable.
"""

from __future__ import annotations

import logging

import pytest

from agent_trading.config.settings import (
    AppSettings,
    _resolve_provider_api_key,
    _resolve_provider_base_url,
    _resolve_provider_model_id,
    _resolve_provider_timeout,
)
from agent_trading.services.ai_agents.event_interpretation import (
    StubEventInterpretationAgent,
)


# ===========================================================================
# Resolver unit tests  (module-level functions)
# ===========================================================================


class TestResolveProviderApiKey:
    """_resolve_provider_api_key() selects the correct env var."""

    def test_deepseek_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LLM_PROVIDER=deepseek → DEEPSEEK_API_KEY."""
        monkeypatch.setenv("LLM_PROVIDER", "deepseek")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")
        assert _resolve_provider_api_key() == "sk-ds-test"

    def test_openai_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LLM_PROVIDER=openai → OPENAI_API_KEY."""
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-oa-test")
        assert _resolve_provider_api_key() == "sk-oa-test"

    def test_deepseek_missing_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DeepSeek key missing → empty string."""
        monkeypatch.setenv("LLM_PROVIDER", "deepseek")
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        assert _resolve_provider_api_key() == ""

    def test_openai_missing_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """OpenAI key missing → empty string."""
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert _resolve_provider_api_key() == ""

    def test_unsupported_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unsupported provider → empty string (stub fallback)."""
        monkeypatch.setenv("LLM_PROVIDER", "claude")
        assert _resolve_provider_api_key() == ""


class TestResolveProviderBaseUrl:
    """_resolve_provider_base_url() uses provider-specific defaults."""

    def test_deepseek_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DeepSeek no env var → default https://api.deepseek.com."""
        monkeypatch.setenv("LLM_PROVIDER", "deepseek")
        monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
        assert _resolve_provider_base_url() == "https://api.deepseek.com"

    def test_openai_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """OpenAI no env var → default https://api.openai.com/v1."""
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        assert _resolve_provider_base_url() == "https://api.openai.com/v1"

    def test_deepseek_custom(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DeepSeek custom base_url."""
        monkeypatch.setenv("LLM_PROVIDER", "deepseek")
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://custom.deepseek.com")
        assert _resolve_provider_base_url() == "https://custom.deepseek.com"

    def test_openai_custom(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """OpenAI custom base_url."""
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://custom.openai.com")
        assert _resolve_provider_base_url() == "https://custom.openai.com"

    def test_unsupported_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unsupported provider → empty string."""
        monkeypatch.setenv("LLM_PROVIDER", "unknown")
        assert _resolve_provider_base_url() == ""


class TestResolveProviderModelId:
    """_resolve_provider_model_id() uses provider-specific defaults."""

    def test_deepseek_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DeepSeek no env var → default deepseek-chat."""
        monkeypatch.setenv("LLM_PROVIDER", "deepseek")
        monkeypatch.delenv("DEEPSEEK_MODEL_ID", raising=False)
        assert _resolve_provider_model_id() == "deepseek-chat"

    def test_openai_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """OpenAI no env var → default gpt-4o."""
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.delenv("OPENAI_MODEL_ID", raising=False)
        assert _resolve_provider_model_id() == "gpt-4o"


class TestResolveProviderTimeout:
    """_resolve_provider_timeout() defaults to 30."""

    def test_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No env var → 30."""
        monkeypatch.setenv("LLM_PROVIDER", "deepseek")
        monkeypatch.delenv("DEEPSEEK_TIMEOUT_SECONDS", raising=False)
        assert _resolve_provider_timeout() == 30

    def test_custom(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Custom timeout."""
        monkeypatch.setenv("LLM_PROVIDER", "deepseek")
        monkeypatch.setenv("DEEPSEEK_TIMEOUT_SECONDS", "60")
        assert _resolve_provider_timeout() == 60


# ===========================================================================
# AppSettings integration tests
# ===========================================================================


class TestAppSettingsProviderResolution:
    """AppSettings fields resolve based on LLM_PROVIDER."""

    def test_deepseek_complete_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DeepSeek complete env → all provider fields populated."""
        monkeypatch.setenv("LLM_PROVIDER", "deepseek")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-test")
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        monkeypatch.setenv("DEEPSEEK_MODEL_ID", "deepseek-chat")
        monkeypatch.setenv("DEEPSEEK_TIMEOUT_SECONDS", "30")
        settings = AppSettings()
        assert settings.llm_provider == "deepseek"
        assert settings.provider_api_key == "sk-ds-test"
        assert settings.provider_base_url == "https://api.deepseek.com"
        assert settings.provider_model_id == "deepseek-chat"
        assert settings.provider_timeout_seconds == 30

    def test_openai_complete_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OpenAI complete env → all provider fields populated."""
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-oa-test")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        monkeypatch.setenv("OPENAI_MODEL_ID", "gpt-4o")
        monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "60")
        settings = AppSettings()
        assert settings.llm_provider == "openai"
        assert settings.provider_api_key == "sk-oa-test"
        assert settings.provider_base_url == "https://api.openai.com/v1"
        assert settings.provider_model_id == "gpt-4o"
        assert settings.provider_timeout_seconds == 60

    def test_deepseek_missing_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DeepSeek key missing → empty api_key (stub fallback)."""
        monkeypatch.setenv("LLM_PROVIDER", "deepseek")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "")
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        monkeypatch.setenv("DEEPSEEK_MODEL_ID", "deepseek-chat")
        settings = AppSettings()
        assert settings.provider_api_key == ""
        # Triple validation catches this: _build_provider_agent() → None

    def test_openai_missing_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OpenAI key missing → empty api_key (stub fallback)."""
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        monkeypatch.setenv("OPENAI_MODEL_ID", "gpt-4o")
        settings = AppSettings()
        assert settings.provider_api_key == ""

    def test_unsupported_provider_stub_fallback(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Unsupported provider → warning log + empty fields."""
        monkeypatch.setenv("LLM_PROVIDER", "claude")
        with caplog.at_level(logging.WARNING):
            settings = AppSettings()
        assert settings.llm_provider == ""
        assert settings.provider_api_key == ""
        assert settings.provider_base_url == ""
        assert settings.provider_model_id == ""
        assert any("Unsupported LLM_PROVIDER" in msg for msg in caplog.messages)

    def test_deepseek_uses_only_deepseek_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DeepSeek mode ignores OPENAI_* env vars."""
        monkeypatch.setenv("LLM_PROVIDER", "deepseek")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-only")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-oa-should-not-read")
        settings = AppSettings()
        assert settings.provider_api_key == "sk-ds-only"

    def test_openai_uses_only_openai_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OpenAI mode ignores DEEPSEEK_* env vars."""
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-oa-only")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-should-not-read")
        settings = AppSettings()
        assert settings.provider_api_key == "sk-oa-only"
