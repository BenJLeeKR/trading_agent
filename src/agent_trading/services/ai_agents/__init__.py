"""AI Agent execution layer — protocol, schema, agents, provider client, and recorder.

This package defines the execution structure for the v1 Provider AI Agent set.

Package layout
--------------
base.py
    ``AgentExecutionRequest``, ``ProviderAIAgent`` protocol,
    ``AIProviderClient`` protocol, ``RawProviderResponse``.
schemas.py
    Structured output dataclasses for the v1 agents.
recorder.py
    ``AgentRunRecorder`` — in-memory stub for recording agent runs.
provider_client.py
    ``OpenAICompatibleClient`` — HTTP-based OpenAI-compatible provider client.
event_interpretation.py
    ``StubEventInterpretationAgent``, ``EventInterpretationAgent``(LLM, 하위
    호환용) and ``DeterministicEventInterpretationAgent``(2026-08-17부터
    실제 wiring 대상, LLM 호출 없음).
ai_risk.py
    ``StubAIRiskAgent``, ``AIRiskAgent``(LLM, 하위 호환용) and
    ``DeterministicAIRiskAgent``(2026-08-17부터 실제 wiring 대상, LLM
    호출 없음).
ai_compliance.py
    ``StubAIComplianceAgent``, ``AIComplianceAgent``(LLM, 하위 호환용) and
    ``DeterministicAIComplianceAgent``(2026-08-16부터 실제 wiring 대상, LLM
    호출 없음).
final_decision_composer.py
    ``StubFinalDecisionComposerAgent`` and ``FinalDecisionComposerAgent`` (real).
"""

from agent_trading.services.ai_agents.base import (
    AgentExecutionRequest,
    AIProviderClient,
    ProviderAIAgent,
    RawProviderResponse,
)
from agent_trading.services.ai_agents.schemas import (
    AIRiskOutput,
    AIComplianceOutput,
    EventInterpretationOutput,
    FinalDecisionComposerOutput,
)
from agent_trading.services.ai_agents.recorder import AgentRunRecorder
from agent_trading.services.ai_agents.provider_client import (
    OpenAICompatibleClient,
)
from agent_trading.services.ai_agents.event_interpretation import (
    DeterministicEventInterpretationAgent,
    EventInterpretationAgent,
    StubEventInterpretationAgent,
)
from agent_trading.services.ai_agents.ai_risk import (
    AIRiskAgent,
    DeterministicAIRiskAgent,
    StubAIRiskAgent,
)
from agent_trading.services.ai_agents.ai_compliance import (
    AIComplianceAgent,
    DeterministicAIComplianceAgent,
    StubAIComplianceAgent,
)
from agent_trading.services.ai_agents.final_decision_composer import (
    FinalDecisionComposerAgent,
    StubFinalDecisionComposerAgent,
)

__all__ = [
    "AgentExecutionRequest",
    "AIProviderClient",
    "ProviderAIAgent",
    "RawProviderResponse",
    "EventInterpretationOutput",
    "AIRiskOutput",
    "AIComplianceOutput",
    "FinalDecisionComposerOutput",
    "AgentRunRecorder",
    "OpenAICompatibleClient",
    "EventInterpretationAgent",
    "DeterministicEventInterpretationAgent",
    "StubEventInterpretationAgent",
    "AIRiskAgent",
    "DeterministicAIRiskAgent",
    "StubAIRiskAgent",
    "AIComplianceAgent",
    "DeterministicAIComplianceAgent",
    "StubAIComplianceAgent",
    "FinalDecisionComposerAgent",
    "StubFinalDecisionComposerAgent",
]
