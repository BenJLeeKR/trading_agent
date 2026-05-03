"""AI Agent execution layer — protocol, schema, agents, provider client, and recorder.

This package defines the execution structure for the v1 Provider AI Agent set.

Package layout
--------------
base.py
    ``AgentExecutionRequest``, ``ProviderAIAgent`` protocol,
    ``AIProviderClient`` protocol, ``RawProviderResponse``.
schemas.py
    Structured output dataclasses for the three v1 agents.
recorder.py
    ``AgentRunRecorder`` — in-memory stub for recording agent runs.
provider_client.py
    ``OpenAICompatibleClient`` — HTTP-based OpenAI-compatible provider client.
event_interpretation.py
    ``StubEventInterpretationAgent`` and ``EventInterpretationAgent`` (real).
ai_risk.py
    ``StubAIRiskAgent``.
final_decision_composer.py
    ``StubFinalDecisionComposerAgent``.
"""

from agent_trading.services.ai_agents.base import (
    AgentExecutionRequest,
    AIProviderClient,
    ProviderAIAgent,
    RawProviderResponse,
)
from agent_trading.services.ai_agents.schemas import (
    AIRiskOutput,
    EventInterpretationOutput,
    FinalDecisionComposerOutput,
)
from agent_trading.services.ai_agents.recorder import AgentRunRecorder
from agent_trading.services.ai_agents.provider_client import (
    OpenAICompatibleClient,
)
from agent_trading.services.ai_agents.event_interpretation import (
    EventInterpretationAgent,
    StubEventInterpretationAgent,
)
from agent_trading.services.ai_agents.ai_risk import AIRiskAgent, StubAIRiskAgent
from agent_trading.services.ai_agents.final_decision_composer import (
    StubFinalDecisionComposerAgent,
)

__all__ = [
    "AgentExecutionRequest",
    "AIProviderClient",
    "ProviderAIAgent",
    "RawProviderResponse",
    "EventInterpretationOutput",
    "AIRiskOutput",
    "FinalDecisionComposerOutput",
    "AgentRunRecorder",
    "OpenAICompatibleClient",
    "EventInterpretationAgent",
    "StubEventInterpretationAgent",
    "AIRiskAgent",
    "StubAIRiskAgent",
    "StubFinalDecisionComposerAgent",
]
