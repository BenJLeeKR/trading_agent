from __future__ import annotations

from dataclasses import dataclass

from agent_trading.domain.enums import BrokerErrorType, BrokerName


@dataclass(slots=True)
class BrokerError(Exception):
    broker_name: BrokerName
    error_type: BrokerErrorType
    retryable: bool
    correlation_id: str | None = None
    raw_code: str | None = None
    raw_message: str | None = None
    retry_after_seconds: float | None = None
    requires_reconciliation: bool = False
    safe_to_retry: bool = True
    blocks_new_orders: bool = False

    def __str__(self) -> str:
        parts = [self.broker_name.value, self.error_type.value]
        if self.raw_code:
            parts.append(self.raw_code)
        if self.raw_message:
            parts.append(self.raw_message)
        return " | ".join(parts)


class AuthenticationError(BrokerError):
    pass


class AuthorizationError(BrokerError):
    pass


class RateLimitError(BrokerError):
    pass


class NetworkError(BrokerError):
    pass


class InvalidRequestError(BrokerError):
    pass


class UnsupportedCapabilityError(BrokerError):
    pass


class OrderRejectedError(BrokerError):
    pass


class TemporaryBrokerError(BrokerError):
    pass


class DataUnavailableError(BrokerError):
    pass


class AmbiguousOrderStateError(BrokerError):
    """Broker returned an order status that cannot be mapped to a known
    ``OrderStatus``.

    This is a **recoverable** error that triggers reconciliation.
    New orders for the same account/symbol/strategy/side must be blocked
    until reconciliation completes.

    By default ``requires_reconciliation=True`` and ``blocks_new_orders=True``
    for this error type.
    """
    pass

