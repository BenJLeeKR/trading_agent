from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4

from agent_trading.brokers.base import BrokerAdapter
from agent_trading.domain.entities import (
    OrderRequestEntity,
    ReconciliationOrderLinkEntity,
    ReconciliationRunEntity,
)
from agent_trading.domain.enums import OrderStatus
from agent_trading.domain.models import OrderStatusResult
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.repositories.filters import OrderQuery

logger = logging.getLogger(__name__)


class ReconciliationService:
    """Application service for reconciliation lifecycle management.

    Scope (Milestone 6)
    -------------------
    * ``trigger()`` — create a reconciliation run and acquire a blocking lock.
    * ``acquire_blocking_lock()`` — INSERT into ``order_blocking_locks``.
    * ``release_blocking_lock()`` — DELETE from ``order_blocking_locks``.
    * ``is_blocked()`` — check whether a blocking lock exists and is not expired.
    * ``get_active_run()`` — retrieve the most recent active reconciliation run.
    * ``attach_mismatch()`` — record order or position mismatches.
    * ``mark_resolved()`` — finalise a run and release all its locks.

    Milestone 7 additions
    ---------------------
    * ``resolve_unknown_state()`` — broker-specific inquiry to resolve
      unknown order states, completing the submit/inquiry/reconciliation
      closed loop.
    * ``resolve_and_mark()`` — convenience method that inquires the broker
      and, if the state is resolved, marks the reconciliation run as done.
    """

    def __init__(self, repos: RepositoryContainer) -> None:
        self._repos = repos

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def trigger_and_link(
        self,
        account_id: UUID,
        trigger_type: str,
        *,
        strategy_id: UUID | None = None,
        symbol: str | None = None,
        side: str | None = None,
        order_request_id: UUID | None = None,
        instrument_id: UUID | None = None,
    ) -> ReconciliationRunEntity:
        """Create a reconciliation run AND link it to an order in one call.

        This is the canonical entry point for all reconciliation run
        production paths. It guarantees that every run has at least one
        order link, satisfying the membership contract.

        Parameters
        ----------
        account_id : UUID
            The account to reconcile.
        trigger_type : str
            Reason for triggering (e.g. ``"requires_reconciliation"``).
        strategy_id, symbol, side :
            Optional lock scope forwarded to ``trigger()``.
        order_request_id : UUID | None
            The order to link. If ``None``, no link is created.
        instrument_id : UUID | None
            Optional instrument ID for the link details.

        Returns
        -------
        ReconciliationRunEntity
            The newly created (or reused) run.
        """
        run = await self.trigger(
            account_id=account_id,
            trigger_type=trigger_type,
            strategy_id=strategy_id,
            symbol=symbol,
            side=side,
        )

        if order_request_id is not None:
            try:
                await self.attach_order_mismatch(
                    reconciliation_run_id=run.reconciliation_run_id,
                    order_request_id=order_request_id,
                    mismatch_type="pending_inquiry",
                    details={
                        "trigger_type": trigger_type,
                        "linked_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                logger.info(
                    "order link created: run_id=%s order_id=%s",
                    run.reconciliation_run_id, order_request_id,
                )
            except Exception as exc:
                logger.warning(
                    "order link creation failed (non-fatal): run_id=%s order_id=%s error=%s",
                    run.reconciliation_run_id, order_request_id, exc,
                )

        return run

    async def trigger(
        self,
        account_id: UUID,
        trigger_type: str,
        *,
        strategy_id: UUID | None = None,
        symbol: str | None = None,
        side: str | None = None,
    ) -> ReconciliationRunEntity:
        """Create a reconciliation run and acquire a blocking lock.

        Parameters
        ----------
        account_id : UUID
            The account to reconcile.
        trigger_type : str
            Reason for triggering (e.g. ``"uncertain_result"``,
            ``"requires_reconciliation"``, ``"scheduled"``).
        strategy_id, symbol, side :
            Optional lock scope. If provided, the blocking lock is scoped to
            ``(account_id, strategy_id, symbol, side)``. If omitted, a
            blanket lock for the entire account is created (strategy_id=NULL).

        Returns
        -------
        ReconciliationRunEntity
            The newly created run with ``status == "started"``.
        """
        # ── Idempotency: active run이 이미 존재하면 재사용 ──
        active_run = await self.get_active_run(account_id)
        if active_run is not None:
            logger.info(
                "reconcile_required auto-trigger: active reconciliation run already exists, reusing. "
                "run_id=%s account_id=%s trigger_type=%s",
                active_run.reconciliation_run_id, account_id, trigger_type,
            )
            return active_run

        logger.info(
            "reconcile_required auto-trigger: creating new reconciliation run. "
            "account_id=%s trigger_type=%s strategy_id=%s symbol=%s side=%s",
            account_id, trigger_type, strategy_id, symbol, side,
        )

        now = datetime.now(timezone.utc)

        run = ReconciliationRunEntity(
            reconciliation_run_id=uuid4(),
            account_id=account_id,
            trigger_type=trigger_type,
            status="started",
            started_at=now,
            mismatch_count=0,
            summary_json={},
            created_at=now,
        )

        created = await self._repos.reconciliations.add_run(run)

        # Acquire blocking lock for the account (or scoped subset).
        await self.acquire_blocking_lock(
            account_id=account_id,
            strategy_id=strategy_id,
            symbol=symbol,
            side=side,
            reason=f"reconciliation:{trigger_type}",
            locked_by_run_id=created.reconciliation_run_id,
        )

        return created

    async def acquire_blocking_lock(
        self,
        account_id: UUID,
        *,
        strategy_id: UUID | None = None,
        symbol: str | None = None,
        side: str | None = None,
        reason: str = "reconciliation",
        locked_by_run_id: UUID,
        ttl_minutes: int = 30,
    ) -> None:
        """Insert a blocking lock row.

        The lock prevents new orders from being submitted for the
        combination of ``(account_id, strategy_id, symbol, side)``.

        If a lock already exists (UNIQUE violation), the call is a no-op
        — the existing lock remains in place.
        """
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=ttl_minutes)

        try:
            await self._repos.reconciliations._tx.connection.execute(
                """
                INSERT INTO trading.order_blocking_locks
                    (lock_id, account_id, strategy_id, symbol, side,
                     reason, locked_by_run_id, locked_at, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (account_id, strategy_id, symbol, side)
                DO NOTHING
                """,
                uuid4(),
                account_id,
                strategy_id,
                symbol,
                side,
                reason,
                locked_by_run_id,
                now,
                expires_at,
            )
        except AttributeError:
            # In-memory fallback: delegate to InMemoryReconciliationRepository.
            self._repos.reconciliations.acquire_lock(
                account_id=account_id,
                strategy_id=strategy_id,
                symbol=symbol,
                side=side,
                reason=reason,
                locked_by_run_id=locked_by_run_id,
                expires_at=expires_at,
            )

    async def release_blocking_lock(
        self,
        account_id: UUID,
        *,
        strategy_id: UUID | None = None,
        symbol: str | None = None,
        side: str | None = None,
        locked_by_run_id: UUID | None = None,
    ) -> None:
        """Remove a blocking lock.

        Parameters
        ----------
        account_id : UUID
            The account whose locks to release.
        strategy_id, symbol, side :
            Optional scope to narrow which locks to release.
        locked_by_run_id : UUID | None
            If provided, only release locks created by this reconciliation
            run. This prevents releasing locks from other active runs on
            the same account.
        """
        conditions = ["account_id = $1"]
        params: list[object] = [account_id]
        idx = 2

        if strategy_id is not None:
            conditions.append(f"strategy_id = ${idx}")
            params.append(strategy_id)
            idx += 1
        if symbol is not None:
            conditions.append(f"symbol = ${idx}")
            params.append(symbol)
            idx += 1
        if side is not None:
            conditions.append(f"side = ${idx}")
            params.append(side)
            idx += 1
        if locked_by_run_id is not None:
            conditions.append(f"locked_by_run_id = ${idx}")
            params.append(locked_by_run_id)
            idx += 1

        sql = (
            "DELETE FROM trading.order_blocking_locks"
            f" WHERE {' AND '.join(conditions)}"
        )

        try:
            await self._repos.reconciliations._tx.connection.execute(sql, *params)
        except AttributeError:
            # In-memory fallback: delegate to InMemoryReconciliationRepository.
            self._repos.reconciliations.release_lock(
                account_id=account_id,
                strategy_id=strategy_id,
                symbol=symbol,
                side=side,
                locked_by_run_id=locked_by_run_id,
            )

    async def is_blocked(
        self,
        account_id: UUID,
        *,
        strategy_id: UUID | None = None,
        symbol: str | None = None,
        side: str | None = None,
    ) -> bool:
        """Check whether a non-expired blocking lock exists.

        Returns ``True`` if any lock matches the given scope and has not
        yet expired.
        """
        conditions = ["account_id = $1", "expires_at > NOW()"]
        params: list[object] = [account_id]
        idx = 2

        if strategy_id is not None:
            conditions.append(f"strategy_id = ${idx}")
            params.append(strategy_id)
            idx += 1
        if symbol is not None:
            conditions.append(f"symbol = ${idx}")
            params.append(symbol)
            idx += 1
        if side is not None:
            conditions.append(f"side = ${idx}")
            params.append(side)

        sql = (
            "SELECT 1 FROM trading.order_blocking_locks"
            f" WHERE {' AND '.join(conditions)}"
            " LIMIT 1"
        )

        try:
            row = await self._repos.reconciliations._tx.connection.fetchval(sql, *params)
            return row is not None
        except AttributeError:
            # In-memory fallback: delegate to InMemoryReconciliationRepository.
            return self._repos.reconciliations.is_locked(
                account_id=account_id,
                strategy_id=strategy_id,
                symbol=symbol,
                side=side,
            )

    async def get_active_run(self, account_id: UUID) -> ReconciliationRunEntity | None:
        """Return the most recent active reconciliation run for the account."""
        return await self._repos.reconciliations.get_active_run(account_id)

    async def list_pending_runs(
        self,
        limit: int = 10,
        *,
        account_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> list[ReconciliationRunEntity]:
        """Return reconciliation runs with ``status = 'started'``.

        Parameters
        ----------
        limit : int
            Maximum number of runs to return.
        account_id : UUID | None
            Optional filter by account.
        run_id : UUID | None
            Optional filter by specific run ID.

        Returns
        -------
        list[ReconciliationRunEntity]
            Runs ordered by ``started_at`` ASC (FIFO).
        """
        return list(await self._repos.reconciliations.list_pending_runs(
            limit=limit,
            account_id=account_id,
            run_id=run_id,
        ))

    async def list_legacy_runs(
        self,
        limit: int = 50,
        *,
        account_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> list[ReconciliationRunEntity]:
        """Return legacy runs: ``status = 'started'`` AND no order links.

        Parameters
        ----------
        limit : int
            Maximum number of runs to return (default ``50``).
        account_id : UUID | None
            Optional filter by account.
        run_id : UUID | None
            Optional filter by specific run ID.

        Returns
        -------
        list[ReconciliationRunEntity]
            Runs ordered by ``started_at`` ASC (oldest first).
        """
        return list(await self._repos.reconciliations.list_legacy_runs(
            limit=limit,
            account_id=account_id,
            run_id=run_id,
        ))

    async def get_run_order_links(
        self,
        reconciliation_run_id: UUID,
    ) -> list[ReconciliationOrderLinkEntity]:
        """Return order links attached to a reconciliation run.

        Parameters
        ----------
        reconciliation_run_id : UUID
            The reconciliation run to look up.

        Returns
        -------
        list[ReconciliationOrderLinkEntity]
            Links ordered by ``created_at`` ASC.
        """
        return list(await self._repos.reconciliations.get_run_order_links(
            reconciliation_run_id,
        ))

    async def attach_order_mismatch(
        self,
        reconciliation_run_id: UUID,
        order_request_id: UUID,
        mismatch_type: str,
        details: dict[str, object] | None = None,
    ) -> None:
        """Record an order-level mismatch for a reconciliation run."""
        await self._repos.reconciliations.attach_order_mismatch(
            reconciliation_run_id,
            order_request_id,
            mismatch_type,
            details or {},
        )

    async def attach_position_mismatch(
        self,
        reconciliation_run_id: UUID,
        position_snapshot_id: UUID,
        mismatch_type: str,
        details: dict[str, object] | None = None,
    ) -> None:
        """Record a position-level mismatch for a reconciliation run."""
        await self._repos.reconciliations.attach_position_mismatch(
            reconciliation_run_id,
            position_snapshot_id,
            mismatch_type,
            details or {},
        )

    async def mark_resolved(
        self,
        reconciliation_run_id: UUID,
        summary_json: dict[str, object] | None = None,
    ) -> None:
        """Mark a reconciliation run as resolved and release its locks.

        This is the **minimum recovery hook** — it finalises the run and
        removes only the blocking locks created by this specific run.
        Broker-specific recovery actions (e.g. resubmitting orders) are
        deferred to Milestone 7.
        """
        run = await self._repos.reconciliations.get_run(reconciliation_run_id)
        if run is None:
            raise ValueError(f"Reconciliation run not found: {reconciliation_run_id}")

        await self._repos.reconciliations.update_run_status(
            reconciliation_run_id,
            status="resolved",
            summary_json=summary_json,
        )

        # Release only the locks created by this reconciliation run.
        await self.release_blocking_lock(
            account_id=run.account_id,
            locked_by_run_id=reconciliation_run_id,
        )

    async def halt_run(
        self,
        reconciliation_run_id: UUID,
        summary_json: dict[str, object] | None = None,
    ) -> ReconciliationRunEntity:
        """Mark a reconciliation run as ``halted``.

        - Does **not** release the blocking lock (intentional — stale lock
          protection).
        - Records the reason in ``summary_json``.
        - Sets ``completed_at`` to the current time.

        Parameters
        ----------
        reconciliation_run_id : UUID
            The run to halt.
        summary_json : dict[str, object] | None
            Optional metadata to record (e.g. reason, superseded_by).

        Returns
        -------
        ReconciliationRunEntity
            The updated run entity.
        """
        run = await self._repos.reconciliations.get_run(reconciliation_run_id)
        if run is None:
            raise ValueError(
                f"Reconciliation run not found: {reconciliation_run_id}"
            )

        now = datetime.now(timezone.utc)
        updated_summary = dict(summary_json or {})
        updated_summary.setdefault("halted_at", now.isoformat())

        await self._repos.reconciliations.update_run_status(
            reconciliation_run_id=reconciliation_run_id,
            status="halted",
            completed_at=now,
            summary_json=updated_summary,
        )

        updated = await self._repos.reconciliations.get_run(reconciliation_run_id)
        assert updated is not None  # guaranteed by the get check above
        return updated

    # ------------------------------------------------------------------
    # Milestone 7: Broker-Specific Unknown State Recovery
    # ------------------------------------------------------------------

    async def resolve_unknown_state(
        self,
        account_ref: str,
        broker: BrokerAdapter,
        *,
        client_order_id: str | None = None,
        broker_order_id: str | None = None,
    ) -> OrderStatusResult:
        """Resolve an unknown order state by inquiring the broker.

        This is the **broker-specific inquiry path** that completes the
        submit/inquiry/reconciliation closed loop:

        1. Inquire the broker for the current order status.
        2. Return the result for the caller to act on.

        The caller (e.g. ``OrderManager``) is responsible for:
        * Triggering a reconciliation run if the result is still ambiguous.
        * Updating the order status based on the resolved state.

        Parameters
        ----------
        account_ref : str
            The broker account reference to inquire against.
        broker : BrokerAdapter
            The broker adapter to use for the inquiry.
        client_order_id : str | None
            Optional client-side order identifier.
        broker_order_id : str | None
            Optional broker-side order identifier.

        Returns
        -------
        OrderStatusResult
            The current order status as reported by the broker.
        """
        # Delegate to the broker adapter's resolve_unknown_state method.
        # For KIS, this uses the INQUIRY bucket with reconciliation reserve
        # fallback (see KISRestClient.resolve_unknown_state).
        return await broker.resolve_unknown_state(
            account_ref,
            client_order_id=client_order_id,
            broker_order_id=broker_order_id,
        )

    async def resolve_and_mark(
        self,
        reconciliation_run_id: UUID,
        account_ref: str,
        broker: BrokerAdapter,
        *,
        client_order_id: str | None = None,
        broker_order_id: str | None = None,
        order_manager: OrderManager | None = None,  # Plan 35: optional authoritative reflection
    ) -> OrderStatusResult:
        """Convenience: inquire broker and, if resolved, mark run as done.

        This method:
        1. Inquires the broker via ``resolve_unknown_state()``.
        2. If the returned status is a terminal or known-good state
           (FILLED, CANCELLED, REJECTED, EXPIRED, ACKNOWLEDGED),
           marks the reconciliation run as resolved.
        3. If ``order_manager`` is provided, also reflects the authoritative
           state onto the local order via ``transition_to_authoritative()``
           (Plan 35).  On reflection success, the run is marked resolved.
           On reflection failure, the run status is set to
           ``reflection_failed`` and the blocking lock remains held.
        4. Returns the broker's response for the caller to act on.

        Parameters
        ----------
        reconciliation_run_id : UUID
            The reconciliation run to resolve.
        account_ref : str
            The broker account reference.
        broker : BrokerAdapter
            The broker adapter for inquiry.
        client_order_id : str | None
            Optional client-side order identifier.
        broker_order_id : str | None
            Optional broker-side order identifier.
        order_manager : OrderManager | None
            If provided, the authoritative status from the broker inquiry
            is reflected onto the local order via
            ``transition_to_authoritative()``.  When ``None`` (default),
            the method behaves identically to the pre-Plan-35 behaviour.

        Returns
        -------
        OrderStatusResult
            The current order status as reported by the broker.
        """
        result = await self.resolve_unknown_state(
            account_ref,
            broker,
            client_order_id=client_order_id,
            broker_order_id=broker_order_id,
        )

        # If the broker returned a resolved state, mark the run as done.
        resolved_statuses = {
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
            OrderStatus.ACKNOWLEDGED,
        }
        if result.status in resolved_statuses:
            if order_manager is not None:
                # --- Authoritative state reflection (Plan 35) ---
                order = await self._resolve_order_for_reflection(
                    client_order_id=client_order_id or "",
                    broker_order_id=broker_order_id,
                )
                if order is not None and order.status == OrderStatus.RECONCILE_REQUIRED:
                    try:
                        await order_manager.transition_to_authoritative(
                            order,
                            result.status,
                            reconciliation_run_id=reconciliation_run_id,
                        )
                        # Step 1: authoritative transition → audit/state event
                        # Step 2: run resolved + lock released
                        await self.mark_resolved(
                            reconciliation_run_id,
                            summary_json={
                                "resolved_via": "broker_inquiry",
                                "resolved_status": result.status.value,
                                "broker_order_id": result.broker_order_id,
                                "client_order_id": result.client_order_id,
                            },
                        )
                    except Exception as exc:
                        # Inquiry succeeded but reflection failed.
                        # Run is NOT resolved; lock stays held.
                        logger.error(
                            "Authoritative reflection failed for run %s: %s",
                            reconciliation_run_id, exc,
                        )
                        await self._repos.reconciliations.update_run_status(
                            reconciliation_run_id,
                            status="reflection_failed",
                            summary_json={
                                "resolved_via": "broker_inquiry",
                                "resolved_status": result.status.value,
                                "reflection_error": str(exc),
                                "error_timestamp": datetime.now(timezone.utc).isoformat(),
                                "broker_order_id": result.broker_order_id,
                                "client_order_id": result.client_order_id,
                            },
                        )
                else:
                    # Order not found or not in RECONCILE_REQUIRED —
                    # still mark resolved (backward compatible).
                    await self.mark_resolved(
                        reconciliation_run_id,
                        summary_json={
                            "resolved_via": "broker_inquiry",
                            "resolved_status": result.status.value,
                            "broker_order_id": result.broker_order_id,
                            "client_order_id": result.client_order_id,
                        },
                    )
            else:
                # No order_manager provided — backward compatible behaviour.
                await self.mark_resolved(
                    reconciliation_run_id,
                    summary_json={
                        "resolved_via": "broker_inquiry",
                        "resolved_status": result.status.value,
                        "broker_order_id": result.broker_order_id,
                        "client_order_id": result.client_order_id,
                    },
                )

        return result

    async def _resolve_order_for_reflection(
        self,
        client_order_id: str,
        broker_order_id: str | None,
    ) -> OrderRequestEntity | None:
        """Find the order associated with this reconciliation run.

        Used by ``resolve_and_mark()`` to locate the local order that
        needs authoritative state reflection.
        """
        if broker_order_id:
            broker_order = await self._repos.broker_orders.get_by_native_order_id(
                broker_order_id
            )
            if broker_order is not None:
                return await self._repos.orders.get(broker_order.order_request_id)
        if client_order_id:
            orders = await self._repos.orders.list(OrderQuery(client_order_id=client_order_id))
            if orders:
                return orders[0]
        return None
