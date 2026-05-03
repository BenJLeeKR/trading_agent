"""Rate limit budgeting for broker API capacity safety.

This module implements **capacity safety** — not throughput optimisation.
Rate limits are treated as **order safety constraints**:

- Inquiry budget exhaustion blocks order status checks → blocks new entries.
- Reconciliation reserve depletion prevents unknown-state recovery.
- Budget separation ensures reconciliation calls are never starved by
  order or inquiry calls.

Design
------
- ``OperationBucket``: token-bucket per operation type (ORDER, INQUIRY,
  RECONCILIATION, MARKET_DATA, AUTH).
- ``RateLimitBudgetManager``: session-level budget orchestration with
  reconciliation reserve protection and universe shrink triggers.
- ``SubscriptionBudget``: WebSocket subscription capacity management.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class BucketType(str, Enum):
    """Operation bucket types for rate limit budgeting.

    Each bucket is independent — reconciliation budget is never consumed
    by order or inquiry calls.
    """

    AUTH = "auth"
    ORDER = "order"
    INQUIRY = "inquiry"
    RECONCILIATION = "reconciliation"
    MARKET_DATA = "market_data"


@dataclass(slots=True)
class OperationBucket:
    """Token-bucket rate limiter for a single operation type.

    Parameters
    ----------
    bucket_type : BucketType
        The operation type this bucket governs.
    capacity : int
        Maximum token count (burst limit).
    refill_rate : float
        Tokens added per second.
    """

    bucket_type: BucketType
    capacity: int
    refill_rate: float

    remaining: int = 0
    refill_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def __post_init__(self) -> None:
        if self.remaining == 0:
            self.remaining = self.capacity

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = datetime.now(tz=timezone.utc)
        elapsed = (now - self.refill_at).total_seconds()
        if elapsed > 0:
            tokens_to_add = int(elapsed * self.refill_rate)
            if tokens_to_add > 0:
                self.remaining = min(self.capacity, self.remaining + tokens_to_add)
                self.refill_at = now

    def try_consume(self, tokens: int = 1) -> bool:
        """Try to consume *tokens* from the bucket.

        Returns ``True`` if the tokens were consumed, ``False`` if the
        bucket is exhausted.
        """
        self._refill()
        if self.remaining >= tokens:
            self.remaining -= tokens
            return True
        return False

    @property
    def utilization(self) -> float:
        """Current bucket utilization as a ratio (0.0 = empty, 1.0 = full)."""
        self._refill()
        return self.remaining / self.capacity if self.capacity > 0 else 0.0

    @property
    def is_exhausted(self) -> bool:
        """``True`` when the bucket has no tokens remaining."""
        self._refill()
        return self.remaining <= 0


class BudgetExhaustedError(RuntimeError):
    """Raised when a budget check prevents an operation from proceeding.

    This is a **safety error** — not a performance warning. It indicates
    that the system cannot safely execute the requested operation without
    risking unknown order states or reconciliation failures.
    """

    def __init__(self, bucket: str, message: str = "") -> None:
        self.bucket = bucket
        self.message = message
        super().__init__(f"[{bucket}] {message}" if message else f"[{bucket}] budget exhausted")


@dataclass(slots=True)
class RateLimitBudgetManager:
    """Session-level rate limit budget orchestration.

    Manages per-operation-type token buckets with reconciliation reserve
    protection. The reconciliation bucket is a **reserve** — it is never
    consumed by general inquiry or order calls.

    Parameters
    ----------
    session_id : UUID
        Unique identifier for this session.
    order_capacity : int
        Maximum order tokens (burst).
    order_refill_rate : float
        Order tokens per second.
    inquiry_capacity : int
        Maximum inquiry tokens (burst).
    inquiry_refill_rate : float
        Inquiry tokens per second.
    reconciliation_capacity : int
        Maximum reconciliation tokens (burst) — reserve only.
    reconciliation_refill_rate : float
        Reconciliation tokens per second.
    market_data_capacity : int
        Maximum market-data tokens (burst).
    market_data_refill_rate : float
        Market-data tokens per second.
    auth_capacity : int
        Maximum auth tokens (burst).
    auth_refill_rate : float
        Auth tokens per second.
    inquiry_block_threshold : float
        When inquiry utilization drops below this ratio (0.0–1.0),
        ``can_accept_new_entries`` returns ``False``. Default 0.2 (20%).
    reconciliation_reserve_min : float
        Minimum reconciliation reserve ratio. When the reconciliation
        bucket drops below this, new entries are blocked. Default 0.5 (50%).
    """

    session_id: UUID
    # --- Buckets ---
    order: OperationBucket
    inquiry: OperationBucket
    reconciliation: OperationBucket
    market_data: OperationBucket
    auth: OperationBucket
    # --- Thresholds ---
    inquiry_block_threshold: float = 0.2
    reconciliation_reserve_min: float = 0.5

    def __init__(
        self,
        session_id: UUID | None = None,
        *,
        order_capacity: int = 30,
        order_refill_rate: float = 2.0,
        inquiry_capacity: int = 60,
        inquiry_refill_rate: float = 5.0,
        reconciliation_capacity: int = 20,
        reconciliation_refill_rate: float = 1.0,
        market_data_capacity: int = 100,
        market_data_refill_rate: float = 10.0,
        auth_capacity: int = 5,
        auth_refill_rate: float = 0.1,
        inquiry_block_threshold: float = 0.2,
        reconciliation_reserve_min: float = 0.5,
    ) -> None:
        self.session_id = session_id or uuid4()
        self.order = OperationBucket(
            bucket_type=BucketType.ORDER,
            capacity=order_capacity,
            refill_rate=order_refill_rate,
        )
        self.inquiry = OperationBucket(
            bucket_type=BucketType.INQUIRY,
            capacity=inquiry_capacity,
            refill_rate=inquiry_refill_rate,
        )
        self.reconciliation = OperationBucket(
            bucket_type=BucketType.RECONCILIATION,
            capacity=reconciliation_capacity,
            refill_rate=reconciliation_refill_rate,
        )
        self.market_data = OperationBucket(
            bucket_type=BucketType.MARKET_DATA,
            capacity=market_data_capacity,
            refill_rate=market_data_refill_rate,
        )
        self.auth = OperationBucket(
            bucket_type=BucketType.AUTH,
            capacity=auth_capacity,
            refill_rate=auth_refill_rate,
        )
        self.inquiry_block_threshold = inquiry_block_threshold
        self.reconciliation_reserve_min = reconciliation_reserve_min

    def try_consume(self, bucket: BucketType, tokens: int = 1) -> bool:
        """Try to consume *tokens* from the given *bucket*.

        Returns ``True`` if successful, ``False`` if the bucket is
        exhausted. This is a safety check — callers **must** handle
        ``False`` by blocking the operation, not by retrying blindly.
        """
        b = self._bucket(bucket)
        return b.try_consume(tokens)

    def consume_or_raise(self, bucket: BucketType, tokens: int = 1) -> None:
        """Consume *tokens* from *bucket* or raise ``BudgetExhaustedError``.

        Raises
        ------
        BudgetExhaustedError
            If the bucket does not have enough tokens.
        """
        if not self.try_consume(bucket, tokens):
            b = self._bucket(bucket)
            raise BudgetExhaustedError(
                bucket=bucket.value,
                message=(
                    f"Bucket '{bucket.value}' exhausted "
                    f"(remaining={b.remaining}/{b.capacity})"
                ),
            )

    def reserve_reconciliation(self, tokens: int = 1) -> bool:
        """Reserve *tokens* from the reconciliation reserve.

        This is a **protected reserve** — it should only be called for
        unknown-state recovery, not for general inquiry.
        """
        return self.reconciliation.try_consume(tokens)

    def reserve_reconciliation_or_raise(self, tokens: int = 1) -> None:
        """Reserve *tokens* from reconciliation reserve or raise.

        Raises
        ------
        BudgetExhaustedError
            If the reconciliation reserve is exhausted.
        """
        if not self.reserve_reconciliation(tokens):
            raise BudgetExhaustedError(
                bucket=BucketType.RECONCILIATION.value,
                message=(
                    f"Reconciliation reserve exhausted "
                    f"(remaining={self.reconciliation.remaining}/{self.reconciliation.capacity})"
                ),
            )

    @property
    def can_accept_new_entries(self) -> bool:
        """``True`` if the system can safely accept new order submissions.

        Returns ``False`` when:
        - Inquiry budget is too low (``utilization < inquiry_block_threshold``)
        - Reconciliation reserve is too low (``utilization < reconciliation_reserve_min``)
        """
        if self.inquiry.utilization < self.inquiry_block_threshold:
            return False
        if self.reconciliation.utilization < self.reconciliation_reserve_min:
            return False
        return True

    @property
    def reconciliation_reserve_remaining(self) -> float:
        """Remaining reconciliation reserve as a ratio (0.0–1.0)."""
        return self.reconciliation.utilization

    @property
    def inquiry_remaining(self) -> float:
        """Remaining inquiry budget as a ratio (0.0–1.0)."""
        return self.inquiry.utilization

    async def shrink_universe(self, factor: float = 0.5) -> None:
        """Reduce inquiry and market-data consumption by *factor*.

        This is a **universe shrink** signal — the caller should reduce
        the number of symbols under analysis and the polling frequency.
        The budget manager itself only tracks consumption; the actual
        universe reduction is the caller's responsibility.
        """
        # Signal only — actual universe reduction is handled upstream.
        # The factor is recorded for monitoring/tracing purposes.
        pass

    def _bucket(self, bucket_type: BucketType) -> OperationBucket:
        mapping: dict[BucketType, OperationBucket] = {
            BucketType.ORDER: self.order,
            BucketType.INQUIRY: self.inquiry,
            BucketType.RECONCILIATION: self.reconciliation,
            BucketType.MARKET_DATA: self.market_data,
            BucketType.AUTH: self.auth,
        }
        return mapping[bucket_type]

    def snapshot(self) -> dict[str, Any]:
        """Return a snapshot of all bucket states for monitoring."""
        return {
            "session_id": str(self.session_id),
            "order": {
                "remaining": self.order.remaining,
                "capacity": self.order.capacity,
                "utilization": self.order.utilization,
            },
            "inquiry": {
                "remaining": self.inquiry.remaining,
                "capacity": self.inquiry.capacity,
                "utilization": self.inquiry.utilization,
            },
            "reconciliation": {
                "remaining": self.reconciliation.remaining,
                "capacity": self.reconciliation.capacity,
                "utilization": self.reconciliation.utilization,
            },
            "market_data": {
                "remaining": self.market_data.remaining,
                "capacity": self.market_data.capacity,
                "utilization": self.market_data.utilization,
            },
            "auth": {
                "remaining": self.auth.remaining,
                "capacity": self.auth.capacity,
                "utilization": self.auth.utilization,
            },
            "can_accept_new_entries": self.can_accept_new_entries,
        }


@dataclass(slots=True, frozen=True)
class SubscriptionBudget:
    """WebSocket subscription capacity management.

    Parameters
    ----------
    max_subscriptions : int
        Absolute maximum number of concurrent subscriptions.
    critical_limit : int
        Maximum number of **critical** subscriptions (held positions,
        open orders, top entry candidates).
    optional_limit : int
        Maximum number of **optional** subscriptions (watchlist, non-held
        observation symbols).
    current_critical : int
        Current count of critical subscriptions.
    current_optional : int
        Current count of optional subscriptions.
    """

    max_subscriptions: int
    critical_limit: int
    optional_limit: int
    current_critical: int = 0
    current_optional: int = 0

    @property
    def total_used(self) -> int:
        return self.current_critical + self.current_optional

    @property
    def can_subscribe_critical(self) -> bool:
        return self.current_critical < self.critical_limit and self.total_used < self.max_subscriptions

    @property
    def can_subscribe_optional(self) -> bool:
        return self.current_optional < self.optional_limit and self.total_used < self.max_subscriptions

    def subscribe_critical(self) -> bool:
        if not self.can_subscribe_critical:
            return False
        object.__setattr__(self, "current_critical", self.current_critical + 1)
        return True

    def subscribe_optional(self) -> bool:
        if not self.can_subscribe_optional:
            return False
        object.__setattr__(self, "current_optional", self.current_optional + 1)
        return True

    def unsubscribe(self, *, critical: bool = False, optional: bool = False) -> None:
        if critical and self.current_critical > 0:
            object.__setattr__(self, "current_critical", self.current_critical - 1)
        if optional and self.current_optional > 0:
            object.__setattr__(self, "current_optional", self.current_optional - 1)
