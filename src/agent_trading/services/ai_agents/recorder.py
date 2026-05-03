"""In-memory stub recorder for AI Agent execution runs.

The ``AgentRunRecorder`` stores ``AgentRunEntity`` instances in a plain
list.  This is a **stub** — the real implementation will persist runs via
a dedicated ``AgentRunRepository`` (added in a later milestone).

Current limitations (accepted for v1)
-------------------------------------
* No persistence — runs are lost on process restart.
* No repository protocol or container entry yet.
* ``raw_output`` is stored inside ``structured_output_json`` under a
  ``"__debug_raw_output__"`` key rather than in ``raw_output_uri``,
  because the URI-based storage layer does not exist yet.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from agent_trading.domain.entities import AgentRunEntity

logger = logging.getLogger(__name__)


class AgentRunRecorder:
    """In-memory stub for recording AI Agent execution runs.

    Parameters
    ----------
    max_runs
        Maximum number of runs to keep in memory.  When the limit is
        reached, the oldest runs are evicted.  ``0`` means unlimited.
    """

    def __init__(self, max_runs: int = 0) -> None:
        self._max_runs = max_runs
        self._runs: list[AgentRunEntity] = []

    async def record(
        self,
        decision_context_id: UUID | None,
        agent_type: str,
        *,
        model_id: str | None = None,
        prompt_id: str | None = None,
        raw_output: str | None = None,
        structured_output: dict[str, object] | None = None,
    ) -> AgentRunEntity:
        """Create and store an ``AgentRunEntity``.

        Parameters
        ----------
        decision_context_id
            The decision context this run belongs to (may be ``None``).
        agent_type
            Agent identifier (e.g. ``"event_interpretation"``).
        model_id
            Optional model identifier (stored as-is; real agents will
            look up the actual UUID from a model registry).
        prompt_id
            Optional prompt identifier (same caveat as ``model_id``).
        raw_output
            Optional raw text output from the Provider.  Stored inside
            ``structured_output_json["__debug_raw_output__"]`` because
            the URI-based storage layer does not exist yet.
        structured_output
            The structured output dict (JSON-compatible).

        Returns
        -------
        AgentRunEntity
            The newly created entity (already appended to the internal
            list).
        """
        now = datetime.now(timezone.utc)

        # Embed raw output inside structured_output_json for now
        output_dict: dict[str, object] = dict(structured_output or {})
        if raw_output is not None:
            output_dict["__debug_raw_output__"] = raw_output

        # --- Schema alignment consistency checks ---
        # Verify that structured_output["agent_name"] matches agent_type
        stored_agent_name = output_dict.get("agent_name")
        if stored_agent_name is not None and stored_agent_name != agent_type:
            logger.warning(
                "Agent name mismatch in structured_output: "
                "output.agent_name=%r != agent_type=%r — "
                "overwriting output.agent_name to match",
                stored_agent_name,
                agent_type,
            )
            output_dict["agent_name"] = agent_type

        # ── decision_context_id: payload 의미 vs storage ID 분리 ──
        #
        # structured_output["decision_context_id"]는 payload 의미를
        # 유지합니다:
        #   - explicit context ID가 있으면 → payload에 기록
        #   - context ID가 없으면 (None) → payload는 null 유지
        #
        # AgentRunEntity.decision_context_id는 내부 storage 식별자로,
        # None이 전달되면 synthetic UUID를 생성합니다.
        if decision_context_id is not None:
            # 실제 context가 있을 때만 일치 검증 후 payload에 기록
            expected = str(decision_context_id)
            stored = output_dict.get("decision_context_id")
            if stored != expected:
                if stored is not None:
                    logger.warning(
                        "decision_context_id mismatch in structured_output: "
                        "output.decision_context_id=%r != expected=%r — "
                        "overwriting output.decision_context_id to match",
                        stored,
                        expected,
                    )
                output_dict["decision_context_id"] = expected
        else:
            # context가 없으면 payload는 null로 유지 (synthetic UUID 금지)
            stored = output_dict.get("decision_context_id")
            if stored is not None:
                logger.warning(
                    "decision_context_id set in structured_output (%r) but "
                    "no decision context was provided — removing from payload "
                    "to preserve uuid-or-null semantics",
                    stored,
                )
                output_dict.pop("decision_context_id", None)

        # Entity는 항상 non-null UUID 필요 → synthetic fallback
        resolved_entity_ctx_id: UUID = decision_context_id or uuid4()

        run = AgentRunEntity(
            agent_run_id=uuid4(),
            decision_context_id=resolved_entity_ctx_id,
            agent_type=agent_type,
            started_at=now,
            model_id=None,  # UUID lookup deferred
            prompt_id=None,  # UUID lookup deferred
            raw_output_uri=None,  # URI storage deferred
            structured_output_json=output_dict or None,
            status="completed",
            completed_at=now,
            created_at=now,
        )

        self._runs.append(run)

        # Evict oldest runs when over limit
        if self._max_runs > 0 and len(self._runs) > self._max_runs:
            self._runs = self._runs[-self._max_runs :]

        logger.debug(
            "Recorded agent run: agent_type=%s decision_context_id=%s run_id=%s",
            agent_type,
            decision_context_id,
            run.agent_run_id,
        )
        return run

    def list_by_decision_context(
        self, decision_context_id: UUID
    ) -> Sequence[AgentRunEntity]:
        """Return all runs for a given decision context, ordered by start time."""
        return tuple(
            r
            for r in self._runs
            if r.decision_context_id == decision_context_id
        )

    def list_all(self) -> Sequence[AgentRunEntity]:
        """Return all recorded runs (ordered by insertion)."""
        return tuple(self._runs)

    def clear(self) -> None:
        """Remove all recorded runs (useful in tests)."""
        self._runs.clear()
