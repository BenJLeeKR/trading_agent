from __future__ import annotations

from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4

from agent_trading.brokers.base import BrokerAdapter
from agent_trading.domain.entities import ReconciliationRunEntity
from agent_trading.domain.enums import OrderStatus
from agent_trading.domain.models import OrderStatusResult
from agent_trading.repositories.container import RepositoryContainer


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
    ) -> OrderStatusResult:
        """Convenience: inquire broker and, if resolved, mark run as done.

        This method:
        1. Inquires the broker via ``resolve_unknown_state()``.
        2. If the returned status is a terminal or known-good state
           (FILLED, CANCELLED, REJECTED, EXPIRED, ACKNOWLEDGED),
           marks the reconciliation run as resolved.
        3. Returns the broker's response for the caller to act on.

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
