"""Tests for ``AgentExecutionRequest``, ``ProviderAIAgent`` protocol,
and ``AIProviderClient`` protocol.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from agent_trading.services.ai_agents.base import (
    AgentExecutionRequest,
    AIProviderClient,
    ProviderAIAgent,
)
from agent_trading.services.decision_orchestrator import AssembledContext


class TestAgentExecutionRequest:
    """AgentExecutionRequest dataclass field requirements."""

    def test_required_fields(self) -> None:
        """AgentExecutionRequest requires decision_context_id, correlation_id, context."""
        context = AssembledContext()
        req = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="corr-123",
            context=context,
        )
        assert req.decision_context_id is None
        assert req.correlation_id == "corr-123"
        assert req.context is context

    def test_decision_context_id_uuid_or_none(self) -> None:
        """decision_context_id accepts UUID or None."""
        context = AssembledContext()
        uid = uuid4()
        req_with = AgentExecutionRequest(
            decision_context_id=uid,
            correlation_id="corr-1",
            context=context,
        )
        assert req_with.decision_context_id == uid

        req_without = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="corr-2",
            context=context,
        )
        assert req_without.decision_context_id is None

    def test_optional_fields_default_none(self) -> None:
        """model_id and prompt_id default to None."""
        context = AssembledContext()
        req = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="corr-1",
            context=context,
        )
        assert req.model_id is None
        assert req.prompt_id is None

    def test_optional_fields_custom(self) -> None:
        """model_id and prompt_id can be set."""
        context = AssembledContext()
        req = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="corr-1",
            context=context,
            model_id="gpt-4o",
            prompt_id="prompt-v2",
        )
        assert req.model_id == "gpt-4o"
        assert req.prompt_id == "prompt-v2"

    def test_frozen(self) -> None:
        """AgentExecutionRequest is frozen."""
        context = AssembledContext()
        req = AgentExecutionRequest(
            decision_context_id=None,
            correlation_id="corr-1",
            context=context,
        )
        with pytest.raises(AttributeError):
            req.correlation_id = "changed"  # type: ignore[misc]


class TestProviderAIAgentProtocol:
    """ProviderAIAgent protocol conformance."""

    def test_protocol_attributes_exist(self) -> None:
        """ProviderAIAgent defines agent_name, schema_version, and run()."""
        assert hasattr(ProviderAIAgent, "agent_name")
        assert hasattr(ProviderAIAgent, "schema_version")
        assert hasattr(ProviderAIAgent, "run")

    def test_protocol_is_runtime_checkable(self) -> None:
        """ProviderAIAgent is runtime-checkable."""
        assert isinstance(ProviderAIAgent, type)


class TestAIProviderClientProtocol:
    """AIProviderClient protocol conformance."""

    def test_protocol_method_exists(self) -> None:
        """AIProviderClient defines generate_structured()."""
        assert hasattr(AIProviderClient, "generate_structured")

    def test_protocol_is_runtime_checkable(self) -> None:
        """AIProviderClient is runtime-checkable."""
        assert isinstance(AIProviderClient, type)
