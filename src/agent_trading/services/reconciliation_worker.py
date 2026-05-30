from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from agent_trading.config.settings import AppSettings
from agent_trading.domain.entities import (
    BrokerAccountEntity,
    ReconciliationOrderLinkEntity,
    ReconciliationRunEntity,
)
from agent_trading.domain.enums import OrderStatus
from agent_trading.repositories.container import RepositoryContainer
from agent_trading.services.reconciliation_service import ReconciliationService

logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    """Result of processing a single reconciliation run."""

    status: str
    """One of: ``resolved``, ``retained``, ``escalated``, ``skipped_no_links``, ``failed``."""

    orders_processed: int = 0
    """Number of order links processed."""

    orders_resolved: int = 0
    """Number of orders successfully resolved."""

    error: str | None = None
    """Error message if the run could not be processed."""

    run_id: UUID | None = None
    """The reconciliation run ID."""


@dataclass
class ReconciliationRunProcessor:
    """Processes a single reconciliation run.

    Flow
    ----
    1. Fetches order links attached to the run.
    2. Resolves the broker account (``Account → BrokerAccount``).
    3. Creates (or retrieves cached) broker adapter for the account.
    4. For each order link, inquires the broker via ``adapter.resolve_unknown_state()``.
    5. If broker truth is available, transitions the order to authoritative state.
    6. Marks the run as resolved, reflection_failed, or failed.

    Key Design Decisions
    --------------------
    - **Account-level adapter caching**: One ``KoreaInvestmentAdapter`` per
      ``account_id``, cached in ``_broker_cache``.  Authentication is
      performed once per account per worker cycle.
    - **Factory pattern**: ``_build_adapter_for_broker_account()`` creates
      the adapter using ``AppSettings`` for KIS env vars and the broker
      account's ``account_ref`` as the KIS account number.
    - **Graceful degradation**: If adapter creation or authentication fails,
      the run is ``retained`` (not ``failed``) — the worker continues to
      subsequent runs.
    """

    repos: RepositoryContainer
    reconciliation_service: ReconciliationService
    settings: AppSettings
    _broker_cache: dict[UUID, Any] = field(default_factory=dict)
    dry_run: bool = False
    order_manager: Any = None

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    async def process_run(self, run: ReconciliationRunEntity) -> ProcessingResult:
        """Process a single reconciliation run.

        Parameters
        ----------
        run : ReconciliationRunEntity
            The reconciliation run to process. Must have ``status == 'started'``.

        Returns
        -------
        ProcessingResult
            The result of processing.
        """
        run_id = run.reconciliation_run_id
        logger.info(
            "Processing reconciliation run: run_id=%s account_id=%s trigger_type=%s",
            run_id, run.account_id, run.trigger_type,
        )

        # ── 1. Order links ──────────────────────────────────────────────
        order_links = await self.repos.reconciliations.get_run_order_links(run_id)

        if not order_links:
            logger.warning(
                "started run without order links, skipping. run_id=%s account_id=%s",
                run_id, run.account_id,
            )
            return ProcessingResult(
                status="skipped_no_links",
                orders_processed=0,
                run_id=run_id,
            )

        # ── 2. Broker account resolution ────────────────────────────────
        try:
            broker_account = await self._get_broker_account(run.account_id)
        except Exception as exc:
            logger.warning(
                "Broker account resolution raised exception, retaining run. "
                "run_id=%s account_id=%s error=%s",
                run_id, run.account_id, exc,
            )
            return ProcessingResult(
                status="retained",
                error=f"broker_account_resolution_failed: {exc}",
                run_id=run_id,
            )

        if broker_account is None:
            logger.warning(
                "No koreainvestment broker account for run. run_id=%s account_id=%s",
                run_id, run.account_id,
            )
            return ProcessingResult(
                status="retained",
                error="broker_account_not_found",
                run_id=run_id,
            )

        # ── 3. Broker adapter (create or cached) ────────────────────────
        try:
            adapter = await self._get_or_create_broker(run.account_id, broker_account)
        except Exception as exc:
            logger.warning(
                "Broker adapter creation raised exception, retaining run. "
                "run_id=%s account_id=%s error=%s",
                run_id, run.account_id, exc,
            )
            return ProcessingResult(
                status="retained",
                error=f"broker_adapter_creation_failed: {exc}",
                run_id=run_id,
            )

        if adapter is None:
            logger.warning(
                "Broker adapter creation failed, retaining run. run_id=%s account_id=%s",
                run_id, run.account_id,
            )
            return ProcessingResult(
                status="retained",
                error="broker_adapter_creation_failed",
                run_id=run_id,
            )

        # ── 4. Process each order link ─────────────────────────────────
        all_succeeded = True
        orders_resolved = 0
        last_error: str | None = None

        for link in order_links:
            result = await self._process_order_link(
                run, link, adapter, broker_account.account_ref,
            )
            if result == "resolved":
                orders_resolved += 1
            elif result == "failed":
                all_succeeded = False
                last_error = f"order {link.order_request_id} failed"

        # ── 5. Run 마감 처리 ────────────────────────────────────────────
        if all_succeeded and orders_resolved == len(order_links):
            if not self.dry_run:
                await self._mark_run_resolved(run, order_links)
            logger.info(
                "Run resolved: run_id=%s orders=%d",
                run_id, orders_resolved,
            )
            return ProcessingResult(
                status="resolved",
                orders_processed=len(order_links),
                orders_resolved=orders_resolved,
                run_id=run_id,
            )
        elif not all_succeeded:
            if not self.dry_run:
                await self._mark_run_failed(run, last_error)
            logger.warning(
                "Run failed: run_id=%s orders=%d resolved=%d error=%s",
                run_id, len(order_links), orders_resolved, last_error,
            )
            return ProcessingResult(
                status="failed",
                orders_processed=len(order_links),
                orders_resolved=orders_resolved,
                error=last_error,
                run_id=run_id,
            )
        else:
            # All succeeded = False 이지만 일부는 성공 → reflection_failed
            if not self.dry_run:
                await self._mark_run_reflection_failed(run, order_links)
            logger.warning(
                "Run reflection_failed: run_id=%s orders=%d resolved=%d",
                run_id, len(order_links), orders_resolved,
            )
            return ProcessingResult(
                status="escalated",
                orders_processed=len(order_links),
                orders_resolved=orders_resolved,
                error="partial resolution",
                run_id=run_id,
            )

    # ──────────────────────────────────────────────────────────────────────
    # Broker adapter lifecycle
    # ──────────────────────────────────────────────────────────────────────

    async def _get_broker_account(
        self, account_id: UUID,
    ) -> BrokerAccountEntity | None:
        """Resolve the KIS broker account for the given ``account_id``.

        Flow: ``Account → broker_account_id → BrokerAccount.get()``.
        Returns ``None`` if the account is not found or the broker is not
        ``koreainvestment``.
        """
        account = await self.repos.accounts.get(account_id)
        if account is None:
            logger.warning("Account not found: account_id=%s", account_id)
            return None

        broker_account = await self.repos.broker_accounts.get(
            account.broker_account_id,
        )
        if broker_account is None:
            logger.warning(
                "Broker account not found: account_id=%s broker_account_id=%s",
                account_id, account.broker_account_id,
            )
            return None

        if broker_account.broker_name != "koreainvestment":
            logger.warning(
                "Unsupported broker for reconciliation inquiry: "
                "account_id=%s broker_name=%s",
                account_id, broker_account.broker_name,
            )
            return None

        return broker_account

    async def _get_or_create_broker(
        self,
        account_id: UUID,
        broker_account: BrokerAccountEntity,
    ) -> Any:
        """Return a cached or newly created broker adapter.

        Adapters are cached by ``account_id`` so that authentication is
        performed once per account per worker cycle.
        """
        if account_id in self._broker_cache:
            logger.debug(
                "Reusing cached broker adapter: account_id=%s", account_id,
            )
            return self._broker_cache[account_id]

        adapter = await self._build_adapter_for_broker_account(
            broker_account_id=broker_account.broker_account_id,
            broker_name=broker_account.broker_name,
        )
        if adapter is not None:
            self._broker_cache[account_id] = adapter
            logger.info(
                "Cached broker adapter: account_id=%s", account_id,
            )
        return adapter

    async def _build_adapter_for_broker_account(
        self,
        broker_account_id: UUID,
        broker_name: str,
    ) -> Any:
        """Create and authenticate a ``KoreaInvestmentAdapter``.

        Parameters
        ----------
        broker_account_id : UUID
            The broker account entity UUID to look up.
        broker_name : str
            Expected ``"koreainvestment"``.  Other brokers are rejected.

        Returns
        -------
        Any
            An authenticated ``KoreaInvestmentAdapter``, or ``None`` on
            failure.
        """
        if broker_name != "koreainvestment":
            logger.warning(
                "Unsupported broker_name=%s — only koreainvestment is supported",
                broker_name,
            )
            return None

        broker_account = await self.repos.broker_accounts.get(broker_account_id)
        if broker_account is None:
            logger.warning(
                "Broker account entity not found: broker_account_id=%s",
                broker_account_id,
            )
            return None

        try:
            from agent_trading.brokers.koreainvestment.adapter import (
                KoreaInvestmentAdapter,
            )
            from agent_trading.brokers.koreainvestment.rest_client import (
                KISRestClient,
            )

            # Build the REST client with env-config driven parameters
            rest_client = KISRestClient(
                api_key=self.settings.kis_api_key,
                api_secret=self.settings.kis_api_secret,
                account_number=broker_account.account_ref,
                account_product_code=self.settings.kis_account_product_code,
                env=self.settings.kis_env,
                base_url=self.settings.kis_base_url,
                dev_token_cache_enabled=self.settings.kis_dev_token_cache_enabled,
                dev_token_cache_path=self.settings.kis_dev_token_cache_path,
            )

            adapter = KoreaInvestmentAdapter(rest_client=rest_client)
            session = await adapter.authenticate()
            logger.info(
                "KIS adapter created and authenticated: "
                "broker_account_id=%s token_prefix=%s",
                broker_account_id,
                session.metadata.get("token_prefix", "N/A"),
            )
            return adapter

        except Exception as exc:
            logger.error(
                "Failed to create/authenticate KIS adapter: "
                "broker_account_id=%s error=%s",
                broker_account_id, exc,
                exc_info=True,
            )
            return None

    # ──────────────────────────────────────────────────────────────────────
    # Order processing
    # ──────────────────────────────────────────────────────────────────────

    async def _process_order_link(
        self,
        run: ReconciliationRunEntity,
        link: ReconciliationOrderLinkEntity,
        adapter: Any,
        account_ref: str,
    ) -> str:
        """Process a single order link by inquiring the broker adapter.

        Returns
        -------
        str
            ``"resolved"`` if broker truth was obtained (terminal status),
            ``"failed"`` otherwise.
        """
        broker_orders = await self.repos.broker_orders.list_by_order_request(
            link.order_request_id,
        )

        if not broker_orders:
            logger.warning(
                "No broker orders for order: run_id=%s order_id=%s",
                run.reconciliation_run_id, link.order_request_id,
            )
            return "failed"

        for bo in broker_orders:
            try:
                if self.dry_run:
                    logger.info(
                        "[DRY-RUN] Would inquire broker: run_id=%s order_id=%s "
                        "broker_native_order_id=%s",
                        run.reconciliation_run_id, link.order_request_id,
                        bo.broker_native_order_id,
                    )
                    return "resolved"

                logger.info(
                    "Inquiring broker for order: run_id=%s order_id=%s "
                    "broker_native_order_id=%s account_ref=%s",
                    run.reconciliation_run_id, link.order_request_id,
                    bo.broker_native_order_id, account_ref,
                )

                # --- Call adapter.resolve_unknown_state() for broker truth ---
                result = await adapter.resolve_unknown_state(
                    account_ref=account_ref,
                    client_order_id=None,
                    broker_order_id=bo.broker_native_order_id,
                )

                # Terminal states that resolve the order
                resolved_statuses = {
                    OrderStatus.FILLED,
                    OrderStatus.CANCELLED,
                    OrderStatus.REJECTED,
                    OrderStatus.EXPIRED,
                    OrderStatus.ACKNOWLEDGED,
                }

                if result.status in resolved_statuses:
                    logger.info(
                        "Order resolved via broker inquiry: run_id=%s order_id=%s "
                        "status=%s",
                        run.reconciliation_run_id, link.order_request_id,
                        result.status.value if result.status else "unknown",
                    )
                    return "resolved"
                elif result.status == OrderStatus.RECONCILE_REQUIRED:
                    # EXPIRED fallback: broker가 상태를 확정하지 못한 경우
                    if await self._try_expired_fallback(
                        link.order_request_id, bo, run.reconciliation_run_id,
                    ):
                        return "resolved"
                    return "failed"
                else:
                    logger.info(
                        "Broker truth unavailable for order: run_id=%s order_id=%s "
                        "status=%s",
                        run.reconciliation_run_id, link.order_request_id,
                        result.status.value if result.status else "unknown",
                    )
                    return "failed"

            except Exception as exc:
                logger.error(
                    "Broker inquiry failed for order: run_id=%s order_id=%s "
                    "broker_native_order_id=%s error=%s",
                    run.reconciliation_run_id, link.order_request_id,
                    bo.broker_native_order_id, exc,
                )
                return "failed"

        return "failed"

    async def _try_expired_fallback(
        self,
        order_request_id: UUID,
        broker_order: Any,
        run_id: UUID,
    ) -> bool:
        """Try to fall back to EXPIRED when broker returns reconcile_required.

        Conditions
        ----------
        1. Order must be in after-hours or past grace period (30 min since creation).
        2. Broker status must be ``reconcile_required``.

        Returns
        -------
        bool
            ``True`` if successfully transitioned to EXPIRED.
        """
        from agent_trading.domain.enums import OrderStatus

        # Grace period: 30 minutes from order creation
        now = datetime.now(timezone.utc)

        # Get order details
        order = await self.repos.orders.get(order_request_id)
        if order is None:
            logger.warning(
                "Order %s not found for expired fallback", order_request_id,
            )
            return False

        created_at = order.created_at
        if created_at is None:
            return False

        age_minutes = (now - created_at).total_seconds() / 60

        # Only allow fallback if:
        # 1. Order is at least 30 minutes old (grace period), OR
        # 2. Current time is in after-hours (KST 15:30~)
        kst_now = now.astimezone(timezone(timedelta(hours=9)))
        is_after_hours = kst_now.hour >= 15 and kst_now.hour < 18  # 15:30~18:00 KST

        if age_minutes < 30 and not is_after_hours:
            logger.info(
                "EXPIRED fallback skipped for %s: age=%.1fmin, after_hours=%s",
                order_request_id, age_minutes, is_after_hours,
            )
            return False

        try:
            if self.order_manager is not None:
                await self.order_manager.transition_to_authoritative(
                    order,
                    OrderStatus.EXPIRED,
                    reconciliation_run_id=run_id,
                    reason_message="reconciliation_expired_fallback",
                )
            else:
                # Fallback: 직접 repos를 통해 EXPIRED 전이
                logger.warning(
                    "order_manager is None, falling back to direct status update for %s",
                    order_request_id,
                )
                from agent_trading.domain.enums import OrderStatus as OS
                await self.repos.orders.update_status(
                    order_request_id=order_request_id,
                    status=OS.EXPIRED,
                    expected_version=order.version,
                    reason_code="reconciliation_expired_fallback",
                )
            logger.info(
                "EXPIRED fallback applied to %s (age=%.1fmin, after_hours=%s)",
                order_request_id, age_minutes, is_after_hours,
            )
            return True
        except Exception as e:
            logger.error(
                "EXPIRED fallback failed for %s: %s", order_request_id, e,
            )
            return False

    # ──────────────────────────────────────────────────────────────────────
    # Run status marking
    # ──────────────────────────────────────────────────────────────────────

    async def _mark_run_resolved(
        self,
        run: ReconciliationRunEntity,
        order_links: list[ReconciliationOrderLinkEntity],
    ) -> None:
        """Mark the run as resolved with a summary."""
        summary = {
            "resolved_via": "reconciliation_worker",
            "orders_processed": len(order_links),
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            await self.reconciliation_service.mark_resolved(
                reconciliation_run_id=run.reconciliation_run_id,
                summary_json=summary,
            )
            logger.info(
                "Run marked resolved: run_id=%s", run.reconciliation_run_id,
            )
        except Exception as exc:
            logger.error(
                "Failed to mark run resolved: run_id=%s error=%s",
                run.reconciliation_run_id, exc,
            )

    async def _mark_run_failed(
        self,
        run: ReconciliationRunEntity,
        error: str | None = None,
    ) -> None:
        """Mark the run as failed and release the blocking lock.

        Lock release is critical — without it, subsequent order attempts
        for the same account remain permanently BLOCKED until the lock
        TTL expires (30 minutes).
        """
        now = datetime.now(timezone.utc)
        summary = {
            "resolved_via": "reconciliation_worker",
            "status": "failed",
            "error": error or "unknown error",
            "failed_at": now.isoformat(),
        }
        try:
            await self.repos.reconciliations.update_run_status(
                reconciliation_run_id=run.reconciliation_run_id,
                status="failed",
                completed_at=now,
                summary_json=summary,
            )
            logger.info(
                "Run marked failed: run_id=%s", run.reconciliation_run_id,
            )
        except Exception as exc:
            logger.error(
                "Failed to mark run failed: run_id=%s error=%s",
                run.reconciliation_run_id, exc,
            )

        # Fix 1: reconciliation 실패 시 lock 해제 — 연쇄 차단 방지
        try:
            await self.reconciliation_service.release_blocking_lock(
                account_id=run.account_id,
                locked_by_run_id=run.reconciliation_run_id,
            )
            logger.info(
                "Blocking lock released for failed run: run_id=%s account_id=%s",
                run.reconciliation_run_id, run.account_id,
            )
        except Exception as exc:
            logger.error(
                "Failed to release blocking lock for failed run: run_id=%s error=%s",
                run.reconciliation_run_id, exc,
            )

    async def _mark_run_reflection_failed(
        self,
        run: ReconciliationRunEntity,
        order_links: list[ReconciliationOrderLinkEntity],
    ) -> None:
        """Mark the run as reflection_failed (partial resolution) and release lock."""
        now = datetime.now(timezone.utc)
        summary = {
            "resolved_via": "reconciliation_worker",
            "status": "reflection_failed",
            "orders_processed": len(order_links),
            "reflection_failed_at": now.isoformat(),
        }
        try:
            await self.repos.reconciliations.update_run_status(
                reconciliation_run_id=run.reconciliation_run_id,
                status="reflection_failed",
                completed_at=now,
                summary_json=summary,
            )
            logger.info(
                "Run marked reflection_failed: run_id=%s", run.reconciliation_run_id,
            )
        except Exception as exc:
            logger.error(
                "Failed to mark run reflection_failed: run_id=%s error=%s",
                run.reconciliation_run_id, exc,
            )

        # Fix 1: reconciliation 실패 시 lock 해제 — 연쇄 차단 방지
        try:
            await self.reconciliation_service.release_blocking_lock(
                account_id=run.account_id,
                locked_by_run_id=run.reconciliation_run_id,
            )
            logger.info(
                "Blocking lock released for reflection_failed run: run_id=%s account_id=%s",
                run.reconciliation_run_id, run.account_id,
            )
        except Exception as exc:
            logger.error(
                "Failed to release blocking lock for reflection_failed run: run_id=%s error=%s",
                run.reconciliation_run_id, exc,
            )
