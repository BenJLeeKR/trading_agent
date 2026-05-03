"""Stub implementation of the Final Decision Composer Agent.

This agent synthesises the outputs of the Event Interpretation and AI Risk
agents into a final structured decision (``FinalDecisionComposerOutput``).
The stub always returns default / "hold" values — no actual Provider API
call is made.

Safe-fallback policy
--------------------
If an unexpected exception occurs during ``run()``, the agent logs a
warning and returns a default ``FinalDecisionComposerOutput``.  This
ensures that the calling orchestrator can always proceed.
"""

from __future__ import annotations

import logging

from agent_trading.services.ai_agents.base import (
    AgentExecutionRequest,
    ProviderAIAgent,
)
from agent_trading.services.ai_agents.schemas import (
    FinalDecisionComposerOutput,
)

logger = logging.getLogger(__name__)


class StubFinalDecisionComposerAgent:
    """Stub Final Decision Composer — returns default ("hold") output.

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
        return "final_decision_composer"

    @property
    def schema_version(self) -> str:
        return self._schema_version

    async def run(
        self, request: AgentExecutionRequest
    ) -> FinalDecisionComposerOutput:
        """Execute the agent and return a structured output.

        The stub implementation:
        * Logs the request for observability.
        * Returns a default ``FinalDecisionComposerOutput`` (hold action,
          zero adjustments, full consensus).

        Safe fallback: any exception is caught, a warning is logged, and
        a default output is returned.
        """
        logger.debug(
            "StubFinalDecisionComposerAgent.run() called: "
            "decision_context_id=%s correlation_id=%s",
            request.decision_context_id,
            request.correlation_id,
        )

        try:
            # --- Stub: no actual Provider call ---
            return FinalDecisionComposerOutput()
        except Exception:
            logger.warning(
                "StubFinalDecisionComposerAgent.run() failed — "
                "returning default output (safe fallback).",
                exc_info=True,
            )
            return FinalDecisionComposerOutput()
