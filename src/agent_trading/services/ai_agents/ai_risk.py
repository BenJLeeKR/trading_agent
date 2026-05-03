"""Stub implementation of the AI Risk Agent.

This agent evaluates risk factors for the current trading context and
produces a structured ``AIRiskOutput``.  The stub always returns default
/ zero-risk values — no actual Provider API call is made.

Safe-fallback policy
--------------------
If an unexpected exception occurs during ``run()``, the agent logs a
warning and returns a default ``AIRiskOutput``.  This ensures that the
calling orchestrator can always proceed.
"""

from __future__ import annotations

import logging

from agent_trading.services.ai_agents.base import (
    AgentExecutionRequest,
    ProviderAIAgent,
)
from agent_trading.services.ai_agents.schemas import AIRiskOutput

logger = logging.getLogger(__name__)


class StubAIRiskAgent:
    """Stub AI Risk Agent — returns default (zero-risk) output.

    This agent conforms to the ``ProviderAIAgent`` protocol.

    Parameters
    ----------
    schema_version
        Version string reported via the ``schema_version`` property.
    """

    def __init__(self, schema_version: str = "v1") -> None:
        self._schema_version = schema_version

    @property
    def agent_name(self) -> str:
        return "ai_risk"

    @property
    def schema_version(self) -> str:
        return self._schema_version

    async def run(self, request: AgentExecutionRequest) -> AIRiskOutput:
        """Execute the agent and return a structured output.

        The stub implementation:
        * Logs the request for observability.
        * Returns a default ``AIRiskOutput`` (zero risk, low level).

        Safe fallback: any exception is caught, a warning is logged, and
        a default output is returned.
        """
        logger.debug(
            "StubAIRiskAgent.run() called: "
            "decision_context_id=%s correlation_id=%s",
            request.decision_context_id,
            request.correlation_id,
        )

        try:
            # --- Stub: no actual Provider call ---
            return AIRiskOutput()
        except Exception:
            logger.warning(
                "StubAIRiskAgent.run() failed — "
                "returning default output (safe fallback).",
                exc_info=True,
            )
            return AIRiskOutput()
