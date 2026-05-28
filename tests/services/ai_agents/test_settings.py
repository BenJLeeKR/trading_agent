"""Tests for LLM provider and KIS environment variable resolution.

Verifies that ``AppSettings`` resolves ``provider_*`` fields based on
the ``LLM_PROVIDER`` environment variable, and that KIS env vars follow
the preferred → fallback resolution chain.
"""

from __future__ import annotations

import logging

import pytest

from agent_trading.config.settings import (
    AppSettings,
    _resolve_kis_api_key,
    _resolve_kis_api_secret,
    _resolve_kis_account_number,
    _resolve_kis_env,
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


# ===========================================================================
# KIS resolver unit tests
# ===========================================================================


class TestResolveKisApiKey:
    """_resolve_kis_api_key() prefers KIS_APP_KEY, falls back to KIS_API_KEY."""

    def test_preferred_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KIS_APP_KEY set → returns KIS_APP_KEY."""
        monkeypatch.setenv("KIS_APP_KEY", "preferred-key")
        monkeypatch.setenv("KIS_API_KEY", "fallback-key")
        assert _resolve_kis_api_key() == "preferred-key"

    def test_fallback_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only KIS_API_KEY set → returns KIS_API_KEY."""
        monkeypatch.delenv("KIS_APP_KEY", raising=False)
        monkeypatch.setenv("KIS_API_KEY", "fallback-key")
        assert _resolve_kis_api_key() == "fallback-key"

    def test_both_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Neither set → empty string."""
        monkeypatch.delenv("KIS_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_API_KEY", raising=False)
        assert _resolve_kis_api_key() == ""


class TestResolveKisApiSecret:
    """_resolve_kis_api_secret() prefers KIS_APP_SECRET, falls back to KIS_API_SECRET."""

    def test_preferred_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KIS_APP_SECRET set → returns KIS_APP_SECRET."""
        monkeypatch.setenv("KIS_APP_SECRET", "preferred-secret")
        monkeypatch.setenv("KIS_API_SECRET", "fallback-secret")
        assert _resolve_kis_api_secret() == "preferred-secret"

    def test_fallback_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only KIS_API_SECRET set → returns KIS_API_SECRET."""
        monkeypatch.delenv("KIS_APP_SECRET", raising=False)
        monkeypatch.setenv("KIS_API_SECRET", "fallback-secret")
        assert _resolve_kis_api_secret() == "fallback-secret"

    def test_both_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Neither set → empty string."""
        monkeypatch.delenv("KIS_APP_SECRET", raising=False)
        monkeypatch.delenv("KIS_API_SECRET", raising=False)
        assert _resolve_kis_api_secret() == ""


class TestResolveKisAccountNumber:
    """_resolve_kis_account_number() prefers KIS_ACCOUNT_NO, falls back to KIS_ACCOUNT_NUMBER."""

    def test_preferred_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KIS_ACCOUNT_NO set → returns KIS_ACCOUNT_NO."""
        monkeypatch.setenv("KIS_ACCOUNT_NO", "preferred-acc")
        monkeypatch.setenv("KIS_ACCOUNT_NUMBER", "fallback-acc")
        assert _resolve_kis_account_number() == "preferred-acc"

    def test_fallback_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only KIS_ACCOUNT_NUMBER set → returns KIS_ACCOUNT_NUMBER."""
        monkeypatch.delenv("KIS_ACCOUNT_NO", raising=False)
        monkeypatch.setenv("KIS_ACCOUNT_NUMBER", "fallback-acc")
        assert _resolve_kis_account_number() == "fallback-acc"

    def test_both_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Neither set → empty string."""
        monkeypatch.delenv("KIS_ACCOUNT_NO", raising=False)
        monkeypatch.delenv("KIS_ACCOUNT_NUMBER", raising=False)
        assert _resolve_kis_account_number() == ""


class TestResolveKisEnv:
    """_resolve_kis_env() normalizes ``real`` → ``live``, defaults to ``paper``."""

    def test_default_paper(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KIS_ENV unset → 'paper'."""
        monkeypatch.delenv("KIS_ENV", raising=False)
        assert _resolve_kis_env() == "paper"

    def test_paper_explicit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KIS_ENV=paper → 'paper'."""
        monkeypatch.setenv("KIS_ENV", "paper")
        assert _resolve_kis_env() == "paper"

    def test_real_normalized_to_live(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KIS_ENV=real → 'live'."""
        monkeypatch.setenv("KIS_ENV", "real")
        assert _resolve_kis_env() == "live"

    def test_live_passthrough(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KIS_ENV=live → 'live'."""
        monkeypatch.setenv("KIS_ENV", "live")
        assert _resolve_kis_env() == "live"

    def test_real_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KIS_ENV=REAL → 'live' (case-insensitive)."""
        monkeypatch.setenv("KIS_ENV", "REAL")
        assert _resolve_kis_env() == "live"

    def test_real_with_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KIS_ENV='  real  ' → 'live' (stripped)."""
        monkeypatch.setenv("KIS_ENV", "  real  ")
        assert _resolve_kis_env() == "live"


class TestAppSettingsKisFields:
    """AppSettings KIS fields resolve correctly via resolver functions."""

    def test_preferred_names(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """All preferred names set → fields use preferred values."""
        monkeypatch.setenv("KIS_APP_KEY", "pk-key")
        monkeypatch.setenv("KIS_APP_SECRET", "pk-secret")
        monkeypatch.setenv("KIS_ACCOUNT_NO", "pk-acc")
        monkeypatch.setenv("KIS_ENV", "real")
        monkeypatch.setenv("KIS_BASE_URL", "https://custom.url:9443")
        settings = AppSettings()
        assert settings.kis_api_key == "pk-key"
        assert settings.kis_api_secret == "pk-secret"
        assert settings.kis_account_number == "pk-acc"
        assert settings.kis_env == "live"  # normalized
        assert settings.kis_base_url == "https://custom.url:9443"

    def test_fallback_names(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only legacy names set → fields use fallback values."""
        monkeypatch.delenv("KIS_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_APP_SECRET", raising=False)
        monkeypatch.delenv("KIS_ACCOUNT_NO", raising=False)
        monkeypatch.setenv("KIS_API_KEY", "legacy-key")
        monkeypatch.setenv("KIS_API_SECRET", "legacy-secret")
        monkeypatch.setenv("KIS_ACCOUNT_NUMBER", "legacy-acc")
        monkeypatch.setenv("KIS_ENV", "live")
        monkeypatch.delenv("KIS_BASE_URL", raising=False)
        monkeypatch.delenv("KIS_WS_URL", raising=False)
        settings = AppSettings()
        assert settings.kis_api_key == "legacy-key"
        assert settings.kis_api_secret == "legacy-secret"
        assert settings.kis_account_number == "legacy-acc"
        assert settings.kis_env == "live"
        assert settings.kis_base_url == ""
        assert settings.kis_ws_url == ""

    def test_all_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No KIS env vars set → empty strings + paper default."""
        monkeypatch.delenv("KIS_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_APP_SECRET", raising=False)
        monkeypatch.delenv("KIS_ACCOUNT_NO", raising=False)
        monkeypatch.delenv("KIS_API_KEY", raising=False)
        monkeypatch.delenv("KIS_API_SECRET", raising=False)
        monkeypatch.delenv("KIS_ACCOUNT_NUMBER", raising=False)
        monkeypatch.delenv("KIS_ENV", raising=False)
        monkeypatch.delenv("KIS_BASE_URL", raising=False)
        monkeypatch.delenv("KIS_WS_URL", raising=False)
        settings = AppSettings()
        assert settings.kis_api_key == ""
        assert settings.kis_api_secret == ""
        assert settings.kis_account_number == ""
        assert settings.kis_env == "paper"
        assert settings.kis_base_url == ""
        assert settings.kis_ws_url == ""

    # ------------------------------------------------------------------
    # KIS REST RPS resolver tests
    # ------------------------------------------------------------------

    def test_real_rest_rps_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``KIS_REAL_REST_RPS`` unset → defaults to 18 per KIS notice 2026-04-20."""
        monkeypatch.delenv("KIS_REAL_REST_RPS", raising=False)
        settings = AppSettings()
        assert settings.kis_real_rest_rps == 18

    def test_paper_rest_rps_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``KIS_PAPER_REST_RPS`` unset → defaults to 1."""
        monkeypatch.delenv("KIS_PAPER_REST_RPS", raising=False)
        settings = AppSettings()
        assert settings.kis_paper_rest_rps == 1


# ===========================================================================
# Schema generation tests  (generate_json_schema + typing.get_type_hints)
# ===========================================================================


class TestGenerateJsonSchemaTypeResolution:
    """generate_json_schema() correctly resolves string annotations."""

    def test_tuple_field_detected(self) -> None:
        """tuple[InterpretedEvent, ...] detected as array (not plain string)."""
        from agent_trading.services.ai_agents.schemas import (
            EventInterpretationOutput,
            generate_json_schema,
        )

        schema = generate_json_schema(EventInterpretationOutput)
        events_schema = schema["properties"]["events"]
        assert events_schema["type"] == "array"
        assert "items" in events_schema
        assert "$ref" in events_schema["items"]

    def test_nested_dataclass_detected(self) -> None:
        """AggregateEventView nested dataclass detected (not plain string)."""
        from agent_trading.services.ai_agents.schemas import (
            EventInterpretationOutput,
            generate_json_schema,
        )

        schema = generate_json_schema(EventInterpretationOutput)
        av_schema = schema["properties"]["aggregate_view"]
        assert "$ref" in av_schema
        assert "definitions" in schema
        assert "AggregateEventView" in schema["definitions"]

    def test_primitive_fields_resolved(self) -> None:
        """str, int, float, bool fields resolve correctly."""
        from agent_trading.services.ai_agents.schemas import (
            EventInterpretationOutput,
            generate_json_schema,
        )

        schema = generate_json_schema(EventInterpretationOutput)
        assert schema["properties"]["symbol"]["type"] == "string"
        assert schema["properties"]["schema_version"]["type"] == "string"


# ===========================================================================
# EventInterpretationOutput.__post_init__ defence tests
# ===========================================================================


class TestEventInterpretationOutputPostInit:
    """__post_init__() correctly handles malformed provider responses."""

    def test_aggregate_view_plain_string_fallback(self) -> None:
        """Plain string aggregate_view → default AggregateEventView."""
        from agent_trading.services.ai_agents.schemas import (
            AggregateEventView,
            EventInterpretationOutput,
        )

        output = EventInterpretationOutput(aggregate_view="중립적")  # type: ignore[arg-type]
        assert isinstance(output.aggregate_view, AggregateEventView)
        assert output.aggregate_view.overall_bias == "neutral"

    def test_aggregate_view_json_string_parsed(self) -> None:
        """JSON object string aggregate_view → parsed AggregateEventView."""
        from agent_trading.services.ai_agents.schemas import (
            AggregateEventView,
            EventInterpretationOutput,
        )

        output = EventInterpretationOutput(
            aggregate_view='{"overall_bias": "positive", "event_conflict": false}'
        )
        assert isinstance(output.aggregate_view, AggregateEventView)
        assert output.aggregate_view.overall_bias == "positive"
        assert output.aggregate_view.event_conflict is False

    def test_events_string_fallback(self) -> None:
        """String events field → empty tuple."""
        from agent_trading.services.ai_agents.schemas import (
            EventInterpretationOutput,
        )

        output = EventInterpretationOutput(events="최근 이벤트가 없습니다.")  # type: ignore[arg-type]
        assert output.events == ()

    def test_events_malformed_items_skipped(self) -> None:
        """List with malformed items: bad items skipped, good items kept."""
        from agent_trading.services.ai_agents.schemas import (
            EventInterpretationOutput,
            InterpretedEvent,
        )

        # Valid InterpretedEvent field, followed by an item with an unknown key
        output = EventInterpretationOutput(events=(  # type: ignore[arg-type]
            {"source_event_id": "evt-001", "summary": "good event"},
            {"unknown_field": "not a valid field"},
        ))
        assert len(output.events) == 1
        assert isinstance(output.events[0], InterpretedEvent)
        assert output.events[0].source_event_id == "evt-001"

    def test_events_all_malformed_returns_empty(self) -> None:
        """All events malformed → empty tuple."""
        from agent_trading.services.ai_agents.schemas import (
            EventInterpretationOutput,
        )

        output = EventInterpretationOutput(events=(  # type: ignore[arg-type]
            {"bad": "item1"},
            {"also": "bad"},
        ))
        assert output.events == ()

    def test_real_rest_rps_custom(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``KIS_REAL_REST_RPS`` set → uses env value."""
        monkeypatch.setenv("KIS_REAL_REST_RPS", "20")
        settings = AppSettings()
        assert settings.kis_real_rest_rps == 20

    def test_paper_rest_rps_custom(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``KIS_PAPER_REST_RPS`` set → uses env value."""
        monkeypatch.setenv("KIS_PAPER_REST_RPS", "3")
        settings = AppSettings()
        assert settings.kis_paper_rest_rps == 3

    # ------------------------------------------------------------------
    # KIS WS URL override tests
    # ------------------------------------------------------------------

    def test_kis_ws_url_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``KIS_WS_URL`` unset → defaults to empty string."""
        monkeypatch.delenv("KIS_WS_URL", raising=False)
        settings = AppSettings()
        assert settings.kis_ws_url == ""

    def test_kis_ws_url_custom(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``KIS_WS_URL`` set → uses env value."""
        monkeypatch.setenv("KIS_WS_URL", "ws://custom.url:31000")
        settings = AppSettings()
        assert settings.kis_ws_url == "ws://custom.url:31000"

    def test_rest_rps_clamp_positive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Zero or negative RPS values are clamped to 1."""
        monkeypatch.setenv("KIS_REAL_REST_RPS", "0")
        monkeypatch.setenv("KIS_PAPER_REST_RPS", "-5")
        settings = AppSettings()
        assert settings.kis_real_rest_rps == 1
        assert settings.kis_paper_rest_rps == 1
