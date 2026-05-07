"""``GET /broker-capacity`` — REST + WebSocket broker capacity inspection.

Read‑only snapshot of the active broker adapter's rate limit budgets
and WebSocket subscription state.  No enforcement logic is triggered.

Requires ``request.app.state.broker_adapter`` to be set by the caller
(e.g. ``create_app(broker_adapter=...)``).  When the adapter is missing
the endpoint returns a 503 status.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from agent_trading.api.schemas import (
    BrokerCapacityResponse,
    BucketSnapshot,
    WsSubscriptionSnapshot,
)

router = APIRouter(tags=["broker-capacity"])


@router.get(
    "/broker-capacity",
    response_model=BrokerCapacityResponse,
)
async def get_broker_capacity(request: Request) -> BrokerCapacityResponse:
    """Return a read‑only snapshot of broker REST + WS capacity.

    The response includes:

    * ``rest_budget`` — token‑bucket state for each operation type
      (order, inquiry, reconciliation, market_data, auth).
    * ``can_accept_new_entries`` — whether the overall budget is healthy.
    * ``websocket`` — WebSocket subscription budget counters.
    * ``market_data_subscriptions`` — active market data channel count.
    * ``order_event_accounts`` — accounts registered for order event push.
    """
    adapter: Any = getattr(request.app.state, "broker_adapter", None)
    if adapter is None:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=503,
            detail="Broker adapter not configured",
        )

    # ── REST budget snapshot ───────────────────────────────────────────────
    budget_manager = getattr(adapter, "_rest", None)
    if budget_manager is not None:
        budget_manager = getattr(budget_manager, "budget_manager", None)

    if budget_manager is not None:
        raw = budget_manager.snapshot()
        rest_budget: dict[str, BucketSnapshot] = {}
        for key, bucket in raw.items():
            if key == "session_id":
                continue
            if key == "can_accept_new_entries":
                continue
            if isinstance(bucket, dict):
                rest_budget[key] = BucketSnapshot(
                    remaining=bucket.get("remaining", 0.0),
                    capacity=bucket.get("capacity", 0.0),
                    refill_rate=bucket.get("refill_rate", 0.0),
                    utilization=bucket.get("utilization", 0.0),
                )
        can_accept = bool(raw.get("can_accept_new_entries", False))
    else:
        rest_budget = {}
        can_accept = False

    # ── WebSocket subscription snapshot ────────────────────────────────────
    sub_budget = getattr(adapter, "_subscription_budget", None)
    if sub_budget is not None:
        ws_raw = sub_budget.snapshot()
        ws_snapshot = WsSubscriptionSnapshot(
            max_subscriptions=ws_raw["max_subscriptions"],
            critical_limit=ws_raw["critical_limit"],
            optional_limit=ws_raw["optional_limit"],
            current_critical=ws_raw["current_critical"],
            current_optional=ws_raw["current_optional"],
            total_used=ws_raw["total_used"],
            remaining=ws_raw["remaining"],
        )
    else:
        ws_snapshot = WsSubscriptionSnapshot(
            max_subscriptions=0,
            critical_limit=0,
            optional_limit=0,
            current_critical=0,
            current_optional=0,
            total_used=0,
            remaining=0,
        )

    # ── Market data / order event counts ────────────────────────────────────
    md_subs: int = len(
        getattr(adapter, "_market_data_subscriptions", {})
        or {}
    )
    order_accounts: list[str] = list(
        getattr(adapter, "_order_event_accounts", set())
        or set()
    )

    return BrokerCapacityResponse(
        broker_name=getattr(adapter, "__class__", None).__name__
        if adapter
        else "unknown",
        environment=getattr(adapter, "_mode", "unknown"),
        rest_budget=rest_budget,
        can_accept_new_entries=can_accept,
        websocket=ws_snapshot,
        market_data_subscriptions=md_subs,
        order_event_accounts=order_accounts,
    )
