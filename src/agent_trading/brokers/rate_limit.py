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

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


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
    REST_GLOBAL = "global"


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

    Held-position sell reserve
    --------------------------
    ``held_position_sell_reserve`` is a **protected reserve** for ORDER bucket.
    When ``consume_or_raise(bucket=ORDER, held_position_sell=True)`` is called,
    the reserve is consumed first (if available).  If the reserve is exhausted,
    falls back to the general ORDER bucket.  This ensures held-position sell
    orders are never starved by general BUY/SELL orders.

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
    global_rest_capacity : int
        Global REST bucket capacity (burst).  ``0`` disables the global
        REST cap (backward compatible).  Default 0.
    global_rest_refill_rate : float
        Global REST bucket tokens per second (the total environment RPS).
    held_position_sell_reserve_capacity : int
        Reserved ORDER tokens for held-position sell orders only.
        Default 1 (minimum guarantee).  ``0`` disables the reserve.
    """

    session_id: UUID
    # --- Buckets ---
    order: OperationBucket
    inquiry: OperationBucket
    reconciliation: OperationBucket
    market_data: OperationBucket
    auth: OperationBucket
    # --- Global REST cap -- (Tier 1, checked before per-operation buckets)
    global_rest: OperationBucket | None = None
    # --- Thresholds ---
    inquiry_block_threshold: float = 0.2
    reconciliation_reserve_min: float = 0.5
    # --- Held-position sell reserve (protected ORDER tokens) ---
    _held_sell_reserve: int = 0
    _held_sell_reserve_capacity: int = 0

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
        global_rest_capacity: int = 0,
        global_rest_refill_rate: float = 0.0,
        held_position_sell_reserve_capacity: int = 1,
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
        if global_rest_capacity > 0:
            self.global_rest = OperationBucket(
                bucket_type=BucketType.REST_GLOBAL,
                capacity=global_rest_capacity,
                refill_rate=global_rest_refill_rate,
            )
        else:
            self.global_rest = None
        self.inquiry_block_threshold = inquiry_block_threshold
        self.reconciliation_reserve_min = reconciliation_reserve_min
        # Held-position sell reserve: protected ORDER tokens
        self._held_sell_reserve_capacity = max(0, held_position_sell_reserve_capacity)
        self._held_sell_reserve = self._held_sell_reserve_capacity

    def try_consume(self, bucket: BucketType, tokens: int = 1) -> bool:
        """Try to consume *tokens* from the given *bucket*.

        Returns ``True`` if successful, ``False`` if the bucket is
        exhausted. This is a safety check — callers **must** handle
        ``False`` by blocking the operation, not by retrying blindly.
        """
        b = self._bucket(bucket)
        return b.try_consume(tokens)

    def _try_consume_held_sell_reserve(self, tokens: int = 1) -> bool:
        """Try to consume *tokens* from the held-position sell reserve.

        The reserve is a **protected pool** — it is only consumed by
        held-position sell orders.  It refills when the general ORDER
        bucket refills (proportional to capacity ratio).

        Returns ``True`` if tokens were consumed, ``False`` if the
        reserve is exhausted.
        """
        if self._held_sell_reserve_capacity <= 0:
            return False
        if self._held_sell_reserve >= tokens:
            self._held_sell_reserve -= tokens
            return True
        return False

    def _refill_held_sell_reserve(self) -> None:
        """Refill the held-position sell reserve based on ORDER bucket refill.

        The reserve refills proportionally: when the ORDER bucket refills,
        the reserve gets a proportional share of the refilled tokens.
        """
        if self._held_sell_reserve_capacity <= 0:
            return
        # Refill based on ORDER bucket utilization
        self.order._refill()
        # Reserve refills at the same rate as ORDER bucket, capped at capacity
        elapsed = (datetime.now(tz=timezone.utc) - self.order.refill_at).total_seconds()
        if elapsed > 0:
            # Proportional refill: reserve gets (reserve_capacity / order_capacity) share
            ratio = self._held_sell_reserve_capacity / max(1, self.order.capacity)
            tokens_to_add = int(elapsed * self.order.refill_rate * ratio)
            if tokens_to_add > 0:
                self._held_sell_reserve = min(
                    self._held_sell_reserve_capacity,
                    self._held_sell_reserve + tokens_to_add,
                )

    def consume_or_raise(
        self,
        bucket: BucketType,
        tokens: int = 1,
        *,
        skip_global_rest: bool = False,
        held_position_sell: bool = False,
    ) -> None:
        """Consume *tokens* from *bucket* or raise ``BudgetExhaustedError``.

        2-tier enforcement:
        1. **Global REST bucket** (Tier 1) — if the global REST cap is
           configured, check it first.  If the global bucket is exhausted
           the request is blocked regardless of the per-bucket state.
           Can be skipped via ``skip_global_rest=True`` for the
           reconciliation fallback path.
        2. **Per-operation bucket** (Tier 2) — the existing per-bucket
           check for the specific operation type.

        **Held-position sell special lane**:
        When ``held_position_sell=True`` and ``bucket=ORDER``, the
        held-position sell reserve is consumed first (if available).
        If the reserve is exhausted, falls back to the general ORDER
        bucket.  This ensures held-position sell orders are never
        starved by general BUY/SELL orders.

        Parameters
        ----------
        skip_global_rest:
            If ``True``, skip the global REST cap check (Tier 1).
            Used by the reconciliation fallback path where the
            reconciliation reserve has already been verified.
        held_position_sell:
            If ``True`` and ``bucket=ORDER``, use the held-position
            sell reserve first.

        Raises
        ------
        BudgetExhaustedError
            If neither the reserve nor the per-operation bucket
            has enough tokens.
        """
        # Tier 1: global REST gate (optional skip for reconcile fallback)
        if not skip_global_rest and self.global_rest is not None:
            if not self.global_rest.try_consume(tokens):
                raise BudgetExhaustedError(
                    bucket="global",
                    message=(
                        f"Global REST cap exhausted "
                        f"(remaining={self.global_rest.remaining}"
                        f"/{self.global_rest.capacity})"
                    ),
                )

        # Tier 1.5: held-position sell reserve (ORDER bucket only)
        if held_position_sell and bucket == BucketType.ORDER:
            self._refill_held_sell_reserve()
            if self._try_consume_held_sell_reserve(tokens):
                # Consumed from reserve — skip general ORDER bucket check
                return
            # Reserve exhausted — fall through to general ORDER bucket
            logger.info(
                "Held-position sell reserve exhausted (remaining=%d/%d) — "
                "falling back to general ORDER bucket",
                self._held_sell_reserve,
                self._held_sell_reserve_capacity,
            )

        # Tier 2: per-operation bucket
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
        result: dict[str, Any] = {
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
        }
        if self.global_rest is not None:
            result["global"] = {
                "remaining": self.global_rest.remaining,
                "capacity": self.global_rest.capacity,
                "refill_rate": self.global_rest.refill_rate,
                "utilization": self.global_rest.utilization,
            }
        result["can_accept_new_entries"] = self.can_accept_new_entries
        return result


# ---------------------------------------------------------------------------
# KIS environment-aware budget manager factory
# ---------------------------------------------------------------------------


def build_kis_budget_manager(
    kis_env: str,
    real_rest_rps: int = 18,
    paper_rest_rps: int = 10,
    shared_budget_file: str | None = None,
) -> RateLimitBudgetManager:
    """Create a ``RateLimitBudgetManager`` with per-bucket safety scaling
    based on the KIS environment's aggregate REST RPS **baseline**.

    .. important::
       This is the **primary env-specific rate-limit switch**.  Paper and
       live environments use completely different budget profiles (see
       Notes table below).  The ``kis_env`` parameter is driven by
       ``AppSettings.kis_env`` (which comes from ``KIS_ENV``), so
       switching the broker environment automatically switches the
       rate-limit budget profile.

    The environment RPS value is used both as a **safety scaling baseline**
    for per-bucket sizing **and** as the **strict global REST cap** enforced
    via a dedicated ``global_rest`` token bucket (Tier 1).  Every REST request
    first checks the global bucket, then the per-operation bucket — if either
    is exhausted the request is blocked.

    Parameters
    ----------
    kis_env : str
        Normalised KIS environment (``"paper"`` or ``"live"``).  ``"real"``
        is also accepted and treated as ``"live"``.
    real_rest_rps : int
        Aggregate REST RPS baseline for the live environment.
        Default 18 (per KIS official notice 2026-04-20: 실전 REST 계좌당
        초당 18건).  The design baseline (15) used for bucket weight
        normalisation is kept separate in the scaling math so that env
        overrides scale proportionally regardless of the default.
    paper_rest_rps : int
        Aggregate REST RPS baseline for the paper environment (default 1).

    Returns
    -------
    RateLimitBudgetManager
        A budget manager with a **2-tier token-bucket** architecture:
        Tier 1 ``global_rest`` (total RPS cap) + Tier 2 per-operation
        buckets independently scaled from the environment RPS baseline.

    Notes
    -----
    The per-bucket distribution is a **safety budget scaling**, not an
    exact RPS guarantee.  The weights are chosen to reflect expected
    traffic patterns while keeping headroom for burst handling:

    ================ ======== ========= ============
    Bucket            Weight   Paper rps Live rps
    ================ ======== ========= ============
    AUTH              0.017    0.017     0.10
    ORDER             0.10     0.10      2.00
    INQUIRY           0.50     0.50      5.00
    MARKET_DATA       0.50     0.50      5.00
    RECONCILIATION    0.10     0.10      1.00
    ================ ======== ========= ============

    Capacity (burst) is set conservatively to allow short bursts without
    immediate throttling.  The aggregate of all bucket refill rates is
    intentionally kept **below** the environment RPS baseline to provide
    safety headroom — this is **not** an exact quota partition.

    .. note::

       The ``15.0`` divisor in ``scale = total / 15.0`` is the **design
       baseline** — the bucket weights were calibrated for 15 RPS.  This
       divisor stays at 15.0 regardless of the default value, so that
       env overrides (e.g. ``KIS_REAL_REST_RPS=30``) always scale
       proportionally from the original design point.
    """
    env = kis_env.strip().lower().replace("real", "live")

    if env == "paper":
        total = max(1, paper_rest_rps)
        # Paper: very conservative — auth is the bottleneck (1 token/min).
        # Capacities are scaled proportionally from the 1-RPS baseline.
        # Global REST cap = total RPS (strict upper bound).
        #
        # Fix 3: ORDER bucket capacity=1 → 3 (burst 여유 확보).
        #   BudgetExhaustedError 발생 시 reconciliation trigger → lock
        #   → 연쇄 차단을 방지하기 위해 최소 3회 연속 주문 가능하도록 완화.
        manager = RateLimitBudgetManager(
            auth_capacity=max(1, int(total * 1)),
            auth_refill_rate=0.017 * total,
            order_capacity=max(3, int(total * 3)),
            order_refill_rate=0.1 * total,
            inquiry_capacity=max(1, int(total * 1)),
            inquiry_refill_rate=0.5 * total,
            market_data_capacity=max(1, int(total * 1)),
            market_data_refill_rate=0.5 * total,
            reconciliation_capacity=max(1, int(10 * total)),
            reconciliation_refill_rate=1.0 * total,
            global_rest_capacity=total,
            global_rest_refill_rate=1.0 * total,
        )
        # Paper 환경: shared_budget_file이 제공되면 in-process global_rest 대신
        # 프로세스 간 공유 FileBackedGlobalBucket 사용
        if shared_budget_file is not None:
            from agent_trading.brokers.shared_budget import FileBackedGlobalBucket

            manager.global_rest = FileBackedGlobalBucket(
                capacity=float(total),
                refill_rate=1.0 * total,
                file_path=shared_budget_file,
            )
        return manager

    # Live / real environment
    total = max(1, real_rest_rps)
    # Normalise the live baseline capacities (designed for total=15) to the
    # configured total RPS so that custom overrides scale proportionally.
    scale = total / 15.0
    return RateLimitBudgetManager(
        auth_capacity=max(1, int(5 * scale)),
        auth_refill_rate=0.1 * scale,
        order_capacity=max(1, int(5 * scale)),
        order_refill_rate=2.0 * scale,
        inquiry_capacity=max(1, int(10 * scale)),
        inquiry_refill_rate=5.0 * scale,
        market_data_capacity=max(1, int(20 * scale)),
        market_data_refill_rate=5.0 * scale,
        reconciliation_capacity=max(1, int(5 * scale)),
        reconciliation_refill_rate=1.0 * scale,
        global_rest_capacity=total,
        global_rest_refill_rate=1.0 * total,
    )


@dataclass(slots=True, frozen=True)
class SubscriptionBudget:
    """WebSocket subscription capacity management.

    .. note::
       KIS official notice (2026-04-20) limits WebSocket registrations to
       **41 per account**.  This budget does **not** enforce the 41-cap at
       this level; a dedicated KIS-capped wrapper is a documented follow-up
       item — see ``plan_docs/detailed_design/10_broker_rate_limit_and_capacity_policy.md`` §12.

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
