"""Phase 4 push relay — in-process fan-out on top of ``RealtimeQuoteSource``.

See ``plan_docs/detailed_design/11_kis_realtime_quote_operations_screen.md`` §Phase 4
and ``plans/[DESIGN]_kis_realtime_quote_operations_screen_plan.md``.

Design
------
``RealtimeQuoteSource`` (``KisRealtimeQuoteSource`` / ``InMemoryMockQuoteSource``)
stays a **pull-based truth source** — ``get_snapshots()`` is unchanged, and
Phase 1-3 callers (the existing REST bootstrap/subscribe/snapshot endpoints)
keep working exactly as before. ``QuoteBroadcaster`` is a separate fan-out
layer bolted on top, used only by the new SSE stream endpoint:

- **True push** — ``KisRealtimeQuoteSource`` exposes ``add_listener()``
  (added alongside this module, not part of the ``RealtimeQuoteSource``
  Protocol). The broadcaster registers a callback that fires synchronously
  on every WS trade/orderbook tick, so subscribers get pushed immediately —
  no polling on the hot path.
- **Fallback poll** — ``InMemoryMockQuoteSource`` has no native push events
  (Phase 1 mock generates snapshots on read, not on a timer). When the
  active source doesn't support ``add_listener`` (duck-typed check), the
  broadcaster falls back to polling ``get_snapshots()`` on a short interval
  for any symbol with active subscribers. This is the "degraded fallback"
  path required to keep Phase 1 mock parity — subscribers never need to know
  which path is active, both funnel into the same ``BroadcastEvent`` stream.
- **Heartbeat** — a periodic status-only event (no new snapshot) keeps SSE
  connections alive through idle periods and lets clients independently
  detect staleness between ticks.

Single-process assumption
--------------------------
One ``QuoteBroadcaster`` instance lives in ``app.state``, fanning out via
in-memory ``asyncio.Queue`` objects. This assumes a single ``api`` process
(``uvicorn --workers 1``, already required by the existing "1 appkey = 1 WS
session" constraint — see ``kis_realtime_quote_source.py`` module docstring).
Multi-worker/cross-process fan-out would need an external pub/sub backend
(e.g. Redis) and is explicitly out of scope for Phase 4 — see the design doc's
"후속 과제" section.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator, Literal

from agent_trading.services.realtime_quote_source import (
    ConnectionState,
    QuoteSnapshot,
    RealtimeQuoteSource,
)

logger = logging.getLogger(__name__)

StreamStatus = Literal["connected", "reconnecting", "disconnected", "stale", "no_data_yet"]
"""6가지 상태 모델 중 5개 — 'degraded'는 이 계층의 관심사가 아니라 프론트가
(연결 문제 + snapshot 조회 오류 등을 종합해) 표시하는 UI 레벨 상태로 유지한다
(기존 Phase 1-3 ``degraded`` 배너 로직과 동일 — RealtimeQuoteView.tsx 참고)."""

DEFAULT_STALE_AFTER_SECONDS = 10.0
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class BroadcastEvent:
    """One event delivered to a stream subscriber — a snapshot push or a
    status-only heartbeat (``snapshot`` may repeat the last-known value)."""

    symbol: str
    status: StreamStatus
    snapshot: QuoteSnapshot | None
    generated_at: datetime


class QuoteBroadcaster:
    """App-process-local fan-out layer — see module docstring."""

    def __init__(
        self,
        source: RealtimeQuoteSource,
        *,
        stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        heartbeat_interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        self._source = source
        self._stale_after = stale_after_seconds
        self._poll_interval = poll_interval_seconds
        self._heartbeat_interval = heartbeat_interval_seconds

        self._latest: dict[str, QuoteSnapshot] = {}
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._poll_tasks: dict[str, asyncio.Task] = {}
        self._heartbeat_tasks: dict[str, asyncio.Task] = {}

        self._supports_push = hasattr(source, "add_listener")
        if self._supports_push:
            source.add_listener(self._on_source_push)

    def close(self) -> None:
        """Detach the push listener and cancel all background tasks (app shutdown)."""
        if self._supports_push:
            try:
                self._source.remove_listener(self._on_source_push)
            except Exception:
                logger.exception("Failed to detach realtime-quote broadcaster listener")
        for task in (*self._poll_tasks.values(), *self._heartbeat_tasks.values()):
            task.cancel()
        self._poll_tasks.clear()
        self._heartbeat_tasks.clear()

    @property
    def supports_push(self) -> bool:
        """Whether the underlying source delivers true push (vs. poll fallback)."""
        return self._supports_push

    # ------------------------------------------------------------------
    # True push path (KisRealtimeQuoteSource.add_listener callback)
    # ------------------------------------------------------------------

    def _on_source_push(self, symbol: str, snapshot: QuoteSnapshot) -> None:
        self._latest[symbol] = snapshot
        self._publish(symbol)

    # ------------------------------------------------------------------
    # Fallback poll path (InMemoryMockQuoteSource — no native push events)
    # ------------------------------------------------------------------

    async def _poll_loop(self, symbol: str) -> None:
        try:
            while True:
                await asyncio.sleep(self._poll_interval)
                snapshot = self._source.get_snapshots([symbol]).get(symbol)
                if snapshot is not None:
                    self._latest[symbol] = snapshot
                self._publish(symbol)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Realtime-quote broadcaster poll loop failed for %s", symbol)

    async def _heartbeat_loop(self, symbol: str) -> None:
        """Status-only tick so idle SSE connections stay alive and clients can
        detect staleness independent of the underlying push/poll cadence."""
        try:
            while True:
                await asyncio.sleep(self._heartbeat_interval)
                self._publish(symbol)
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # Subscriber-facing stream
    # ------------------------------------------------------------------

    def _status_for(self, symbol: str) -> StreamStatus:
        state = self._source.connection_state()
        if state == ConnectionState.DISCONNECTED:
            return "disconnected"
        if state == ConnectionState.RECONNECTING:
            return "reconnecting"
        snapshot = self._latest.get(symbol)
        if snapshot is None:
            return "no_data_yet"
        age = (datetime.now(timezone.utc) - snapshot.updated_at).total_seconds()
        if age > self._stale_after:
            return "stale"
        return "connected"

    def _make_event(self, symbol: str) -> BroadcastEvent:
        return BroadcastEvent(
            symbol=symbol,
            status=self._status_for(symbol),
            snapshot=self._latest.get(symbol),
            generated_at=datetime.now(timezone.utc),
        )

    def _publish(self, symbol: str) -> None:
        queues = self._subscribers.get(symbol)
        if not queues:
            return
        event = self._make_event(symbol)
        for queue in list(queues):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "Realtime-quote broadcaster queue full for %s, dropping event", symbol
                )

    async def stream(self, symbol: str) -> AsyncIterator[BroadcastEvent]:
        """Yield events for ``symbol`` until the caller stops iterating.

        Always yields the current cached state immediately on subscribe —
        this is what makes "재접속 시 최신 snapshot 재전달" work: a fresh
        ``stream()`` call (new SSE connection after a drop) is instantly
        caught up, not left waiting for the next tick.
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        symbol_queues = self._subscribers.setdefault(symbol, set())
        symbol_queues.add(queue)

        if not self._supports_push and symbol not in self._poll_tasks:
            self._poll_tasks[symbol] = asyncio.create_task(self._poll_loop(symbol))
        if symbol not in self._heartbeat_tasks:
            self._heartbeat_tasks[symbol] = asyncio.create_task(self._heartbeat_loop(symbol))

        try:
            yield self._make_event(symbol)
            while True:
                event = await queue.get()
                yield event
        finally:
            symbol_queues.discard(queue)
            if not symbol_queues:
                self._subscribers.pop(symbol, None)
                poll_task = self._poll_tasks.pop(symbol, None)
                if poll_task is not None:
                    poll_task.cancel()
                heartbeat_task = self._heartbeat_tasks.pop(symbol, None)
                if heartbeat_task is not None:
                    heartbeat_task.cancel()
