"""Process-shared token bucket backed by a flock-protected file.

All subprocesses (snapshot sync, post-submit sync, decision loop)
share the same 1 RPS global budget via this file, ensuring the KIS
paper environment's 1 RPS constraint is honoured across processes.
"""

from __future__ import annotations

import asyncio
import fcntl
import logging
import time

logger = logging.getLogger(__name__)


class FileBackedGlobalBucket:
    """Process-shared token bucket backed by a flock-protected file.

    This bucket is designed as a drop-in replacement for
    ``OperationBucket`` in the global REST tier of
    ``RateLimitBudgetManager``.  It exposes the same ``try_consume()``
    interface so that ``consume_or_raise()`` can use it transparently.

    All subprocesses that call KIS REST APIs share the same file,
    so the aggregate call rate never exceeds the configured capacity
    (1 RPS for paper).

    Attributes
    ----------
    capacity : int
        Maximum token count (burst limit).  Mirrors ``OperationBucket``
        interface for compatibility with ``RateLimitBudgetManager``.
    remaining : int
        Approximate remaining tokens (best-effort, read from file).
        Used only for error/log messages.
    """

    _FILE_PATH = "/tmp/.kis_paper_global_budget"
    _capacity: float = 1.0
    _refill_rate: float = 1.0  # 1 token/second = 1 RPS

    def __init__(
        self,
        capacity: float = 1.0,
        refill_rate: float = 1.0,
        file_path: str | None = None,
    ) -> None:
        self._capacity = capacity
        self._refill_rate = refill_rate
        if file_path is not None:
            self._FILE_PATH = file_path

    # ------------------------------------------------------------------
    # Duck-typing attributes for ``OperationBucket`` compatibility
    # ------------------------------------------------------------------

    @property
    def capacity(self) -> int:
        """Maximum token count (burst limit)."""
        return int(self._capacity)

    @property
    def remaining(self) -> int:
        """Approximate remaining tokens (best-effort read from file).

        Used only for error/log messages in ``consume_or_raise()``.
        Returns the capacity if the file cannot be read.
        """
        try:
            with open(self._FILE_PATH, "r") as f:
                fcntl.flock(f, fcntl.LOCK_SH)
                try:
                    raw = f.read().strip()
                    if raw:
                        tokens_str, _ = raw.split(",", 1)
                        return max(0, int(float(tokens_str)))
                    return self.capacity
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except (OSError, ValueError, FileNotFoundError):
            return self.capacity

    # ------------------------------------------------------------------
    # Public API — matches ``OperationBucket.try_consume()`` signature
    # ------------------------------------------------------------------

    def try_consume(self, tokens: int = 1) -> bool:
        """Try to consume *tokens* from the shared budget.

        Returns ``True`` if the tokens were consumed, ``False`` if the
        budget is exhausted.

        This is a **synchronous** method so that it can be called from
        ``RateLimitBudgetManager.consume_or_raise()`` which is itself
        synchronous.

        Uses ``fcntl.flock`` for atomic read-modify-write across
        processes.
        """
        return self._consume_sync(float(tokens))

    async def consume(self, tokens: float = 1.0) -> bool:
        """Async wrapper around ``try_consume()``.

        Runs the flock-protected I/O in a thread to avoid blocking the
        event loop.
        """
        return await asyncio.to_thread(self._consume_sync, tokens)

    async def wait_until_available(self, tokens: float = 1.0) -> None:
        """Block until tokens are available.  Polls with ``asyncio.sleep``."""
        while True:
            if await self.consume(tokens):
                return
            await asyncio.sleep(0.5)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _consume_sync(self, tokens: float) -> bool:
        """Synchronous token consumption with flock protection."""
        try:
            with open(self._FILE_PATH, "a+") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    f.seek(0)
                    raw = f.read().strip()
                    if raw:
                        last_tokens_str, last_time_str = raw.split(",", 1)
                        current_tokens = float(last_tokens_str)
                        last_time = float(last_time_str)
                    else:
                        current_tokens = self._capacity
                        last_time = time.time()

                    now = time.time()
                    elapsed = now - last_time
                    current_tokens = min(
                        self._capacity,
                        current_tokens + elapsed * self._refill_rate,
                    )

                    if current_tokens >= tokens:
                        current_tokens -= tokens
                        f.seek(0)
                        f.truncate()
                        f.write(f"{current_tokens},{now}")
                        return True
                    else:
                        # Write current state anyway for next caller
                        f.seek(0)
                        f.truncate()
                        f.write(f"{current_tokens},{now}")
                        return False
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except (OSError, ValueError) as exc:
            logger.warning(
                "FileBackedGlobalBucket error: %s — allowing passthrough",
                exc,
            )
            return True  # Fail open: allow call on error
