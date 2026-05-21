from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Sequence

from agent_trading.domain.models import (
    AmendOrderRequest,
    AmendOrderResult,
    BrokerCapability,
    BrokerHealth,
    BrokerSession,
    CancelOrderRequest,
    CancelOrderResult,
    CashBalance,
    FillEvent,
    MarketDataSubscription,
    OrderBook,
    OrderStatusResult,
    Position,
    Quote,
    SubmitOrderRequest,
    SubmitOrderResult,
)


@dataclass(slots=True, frozen=True)
class SubscriptionBudget:
    """WebSocket subscription capacity management with eviction policy.

    .. note::
       KIS official notice (2026-04-20) limits WebSocket registrations to
       **41 per account**.  The ``KoreaInvestmentAdapter`` creates its
       ``SubscriptionBudget`` with ``max_subscriptions=41``, making 41 the
       authoritative cap for the KIS WebSocket path.  The class-level
       default ``max_subscriptions=100`` is a **safety ceiling** for
       non-KIS use cases and future growth; other adapters or tests should
       set an explicit ``max_subscriptions`` matching their broker's limit.

    Manages two tiers of subscriptions:
    - **Critical**: held positions, open orders, fill notifications.
      Protected from eviction by optional subscriptions.
    - **Optional**: watchlist, non-held observation symbols.
      May be evicted when critical subscriptions need capacity.

    Eviction policy
    ---------------
    When an optional subscription cannot be added because the budget
    is full, the least-recently-used optional subscription is evicted
    (FIFO within the optional pool).  Critical subscriptions are never
    evicted automatically — they must be explicitly unsubscribed.

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

    max_subscriptions: int = 100
    critical_limit: int = 20
    optional_limit: int = 80
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
        """Subscribe a critical channel.

        If the critical limit is reached, returns ``False``.
        If the total limit is reached, attempts to evict an optional
        subscription to make room.
        """
        if self.current_critical >= self.critical_limit:
            return False

        if self.total_used >= self.max_subscriptions:
            # Evict one optional subscription to make room
            if self.current_optional > 0:
                object.__setattr__(self, "current_optional", self.current_optional - 1)
            else:
                return False

        object.__setattr__(self, "current_critical", self.current_critical + 1)
        return True

    def subscribe_optional(self) -> bool:
        """Subscribe an optional channel.

        If the optional limit is reached, returns ``False``.
        If the total limit is reached, returns ``False`` (optional
        subscriptions do not evict critical ones).
        """
        if self.current_optional >= self.optional_limit:
            return False

        if self.total_used >= self.max_subscriptions:
            return False

        object.__setattr__(self, "current_optional", self.current_optional + 1)
        return True

    def unsubscribe(self, *, critical: bool = False, optional: bool = False) -> None:
        """Unsubscribe and release budget capacity."""
        if critical and self.current_critical > 0:
            object.__setattr__(self, "current_critical", self.current_critical - 1)
        if optional and self.current_optional > 0:
            object.__setattr__(self, "current_optional", self.current_optional - 1)

    def snapshot(self) -> dict[str, object]:
        """Return a read-only snapshot of the current subscription budget state.

        Returns
        -------
        dict[str, object]
            Keys: ``max_subscriptions``, ``critical_limit``, ``optional_limit``,
            ``current_critical``, ``current_optional``, ``total_used``, ``remaining``.
        """
        return {
            "max_subscriptions": self.max_subscriptions,
            "critical_limit": self.critical_limit,
            "optional_limit": self.optional_limit,
            "current_critical": self.current_critical,
            "current_optional": self.current_optional,
            "total_used": self.total_used,
            "remaining": self.max_subscriptions - self.total_used,
        }

class BrokerAdapter(Protocol):
    """Common broker contract used by the trading core."""

    async def get_capabilities(self) -> BrokerCapability:
        """Return broker feature support and operational constraints."""

    async def health_check(self) -> BrokerHealth:
        """Return current adapter and upstream health information."""

    async def authenticate(self) -> BrokerSession:
        """Authenticate the adapter and return the active session metadata."""

    async def get_quote(self, symbol: str, market: str) -> Quote:
        """Fetch the latest normalized quote snapshot for a symbol."""

    async def get_orderbook(self, symbol: str, market: str) -> OrderBook:
        """Fetch the latest normalized orderbook snapshot for a symbol."""

    async def get_positions(self, account_ref: str) -> Sequence[Position]:
        """Return normalized positions for an account."""

    async def get_cash_balance(self, account_ref: str) -> CashBalance:
        """Return normalized cash balance information."""

    async def submit_order(self, request: SubmitOrderRequest) -> SubmitOrderResult:
        """Submit a new order to the broker."""

    async def cancel_order(self, request: CancelOrderRequest) -> CancelOrderResult:
        """Cancel a working order."""

    async def amend_order(self, request: AmendOrderRequest) -> AmendOrderResult:
        """Amend a working order if the broker supports it."""

    async def get_order_status(
        self,
        account_ref: str,
        client_order_id: str | None = None,
        broker_order_id: str | None = None,
    ) -> OrderStatusResult:
        """Fetch the latest normalized status for an order."""

    async def get_fills(
        self,
        account_ref: str,
        broker_order_id: str,
        from_ts: str | datetime | None = None,
    ) -> Sequence[FillEvent]:
        """Fetch normalized fill events for an order."""

    async def subscribe_market_data(
        self,
        subscriptions: Sequence[MarketDataSubscription],
    ) -> None:
        """Subscribe to real-time market data channels."""

    async def subscribe_order_events(self, account_ref: str) -> None:
        """Subscribe to real-time order and fill events."""

    async def resolve_unknown_state(
        self,
        account_ref: str,
        *,
        client_order_id: str | None = None,
        broker_order_id: str | None = None,
        symbol: str | None = None,
    ) -> OrderStatusResult:
        """Resolve an unknown order state by inquiring the broker.

        This is the **broker-specific recovery path** for reconciliation.
        Each broker adapter implements this using its own inquiry API.

        Parameters
        ----------
        account_ref : str
            The broker account reference to inquire against.
        client_order_id : str | None
            Optional client-side order identifier.
        broker_order_id : str | None
            Optional broker-side order identifier.

        Returns
        -------
        OrderStatusResult
            The current order status as reported by the broker.
        """

