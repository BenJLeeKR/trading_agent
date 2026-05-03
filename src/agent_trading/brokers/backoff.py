"""Backoff strategies and circuit breaker for broker API safety.

This module implements **safety backoff** — not performance optimisation.
When a broker returns rate-limit errors, auth failures, or network
timeouts, the backoff strategy ensures the system does not amplify the
problem by retrying aggressively.

Circuit breaker states
----------------------
- ``CLOSED`` — normal operation, requests pass through.
- ``OPEN`` — requests are blocked immediately (fail-fast).
- ``HALF_OPEN`` — a single probe request is allowed to test recovery.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class BackoffStrategy:
    """Base class for backoff strategies."""

    def __call__(self, attempt: int) -> float:
        """Return the delay in seconds for the given *attempt* number."""
        raise NotImplementedError


@dataclass(slots=True)
class ExponentialBackoff(BackoffStrategy):
    """Exponential backoff with optional jitter.

    ``delay = min(base_delay * multiplier^attempt, max_delay) + jitter``
    """

    base_delay: float = 1.0
    multiplier: float = 2.0
    max_delay: float = 60.0
    jitter: float = 0.1

    def __call__(self, attempt: int) -> float:
        delay = min(self.base_delay * (self.multiplier ** attempt), self.max_delay)
        if self.jitter > 0:
            delay += random.uniform(0, self.jitter)
        return delay


@dataclass(slots=True)
class LinearBackoff(BackoffStrategy):
    """Fixed-interval backoff (e.g., for auth retries)."""

    delay: float = 5.0

    def __call__(self, attempt: int) -> float:
        return self.delay


@dataclass(slots=True)
class CircuitBreaker:
    """Circuit breaker for broker API calls.

    Parameters
    ----------
    failure_threshold : int
        Number of consecutive failures before opening the circuit.
    recovery_timeout : float
        Seconds to wait before transitioning from OPEN to HALF_OPEN.
    half_open_max_retries : int
        Number of probe attempts in HALF_OPEN state before deciding.
    backoff_strategy : BackoffStrategy
        Strategy for computing retry delays.
    """

    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max_retries: int = 1
    backoff_strategy: BackoffStrategy = field(default_factory=ExponentialBackoff)

    _state: CircuitState = CircuitState.CLOSED
    _failure_count: int = 0
    _last_failure_time: float = 0.0
    _half_open_attempts: int = 0

    @property
    def state(self) -> CircuitState:
        self._check_timeout()
        return self._state

    def _check_timeout(self) -> None:
        """Transition from OPEN to HALF_OPEN if recovery timeout elapsed."""
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_attempts = 0

    def call(self, fn: Callable[[], object]) -> object:
        """Execute *fn* with circuit breaker protection.

        Returns the result of *fn* on success.
        Raises ``CircuitBreakerOpenError`` if the circuit is open.
        Re-raises the original exception on failure.
        """
        if self.state == CircuitState.OPEN:
            raise CircuitBreakerOpenError(
                f"Circuit breaker is OPEN (failure_count={self._failure_count})"
            )

        try:
            result = fn()
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise

    async def async_call(self, fn: Callable[[], object]) -> object:
        """Async variant of :meth:`call`."""
        if self.state == CircuitState.OPEN:
            raise CircuitBreakerOpenError(
                f"Circuit breaker is OPEN (failure_count={self._failure_count})"
            )

        try:
            result = await fn()
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            self._half_open_attempts += 1
            if self._half_open_attempts >= self.half_open_max_retries:
                # Probe succeeded — close the circuit.
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._half_open_attempts = 0
        else:
            # Normal success — reset failure count.
            self._failure_count = 0

    def _on_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            # Probe failed — back to OPEN.
            self._state = CircuitState.OPEN
            self._half_open_attempts = 0
        elif self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN

    def reset(self) -> None:
        """Manually reset the circuit breaker to CLOSED."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._half_open_attempts = 0


class CircuitBreakerOpenError(RuntimeError):
    """Raised when a request is blocked by an open circuit breaker."""
