"""KIS (Korea Investment) implementation of ``SnapshotFetchProvider``.

Wraps ``KISRestClient`` and handles KIS-specific field mapping from raw
API response fields to domain entities.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.domain.entities import (
    CashBalanceSnapshotEntity,
    PositionSnapshotEntity,
)
from agent_trading.repositories.contracts import InstrumentRepository
from agent_trading.services.snapshot_sync import (
    FetchedSnapshot,
    SnapshotFetchProvider,
    safe_decimal,
    safe_optional_decimal,
)

logger = logging.getLogger(__name__)

# KIS inquire-balance output position field names
_KIS_PDNO = "pdno"  # 종목코드
_KIS_HLDG_QTY = "hldg_qty"  # 보유수량
_KIS_PCHS_AVG_PRIC = "pchs_avg_pric"  # 매입평균가
_KIS_PRPR = "prpr"  # 현재가
_KIS_EVL_PFLS_AMT = "evlu_pfls_amt"  # 평가손익

# KIS inquire-balance output2 (cash summary) field names
_KIS_DNCA_TOT_AMT = "dnca_tot_amt"  # 예수금총액
_KIS_NXDY_EXCC_AMT = "nxdy_excc_amt"  # 익일초과액
_KIS_TOT_EVL_AMT = "tot_evlu_amt"  # 총평가금액 (유가증권 평가금액 합계 + D+2 예수금)
_KIS_PRVS_RCDL_EXCC_AMT = "prvs_rcdl_excc_amt"  # 가수도정산금액 (D+2 예수금 기준)
_KIS_EVL_PFLS_SMTL_AMT = "evlu_pfls_smtl_amt"  # 평가손익합계금액 (계좌 총괄)

_SOURCE_OF_TRUTH = "broker"
_DEFAULT_MARKET_CODE = "KRX"


class KISSyncSnapshotProvider:
    """KIS implementation of ``SnapshotFetchProvider``.

    Wraps ``KISRestClient`` and handles KIS-specific field mapping from
    raw API response fields (``pdno``, ``hldg_qty``, ``dnca_tot_amt``, etc.)
    to ``PositionSnapshotEntity`` / ``CashBalanceSnapshotEntity``.
    """

    def __init__(self, rest_client: KISRestClient) -> None:
        self._rest = rest_client

    async def fetch_snapshot(
        self,
        account_id: UUID,
        instrument_repo: InstrumentRepository,
        *,
        after_hours: bool = False,
    ) -> FetchedSnapshot:
        """Fetch KIS positions and cash balance, return as domain entities.

        Parameters
        ----------
        account_id:
            The ``AccountEntity.account_id`` (UUID) to associate snapshots
            with.
        instrument_repo:
            Repository for resolving KIS ``pdno`` (product code) to
            ``InstrumentEntity.instrument_id``.
        after_hours:
            When ``True``, passes ``after_hours=True`` to
            ``get_cash_balance()`` so that ``AFHR_FLPR_YN=Y`` is used
            for after-hours cash inquiry (15:31∼16:31 KST).

        Returns
        -------
        FetchedSnapshot
            Position snapshots, optional cash balance snapshot, and any
            non-fatal errors (instrument lookup failures, field mapping
            issues).
        """
        snapshot_at = datetime.now(tz=timezone.utc)
        errors: list[str] = []
        positions: list[PositionSnapshotEntity] = []

        # ── 1. Fetch positions ────────────────────────────────────────────
        try:
            raw_positions: Sequence[Any] = await self._rest.get_positions()
        except Exception as exc:
            msg = f"Failed to fetch positions from KIS: {exc}"
            logger.error(msg)
            errors.append(msg)
            raw_positions = []

        for raw in raw_positions:
            pdno = raw.get(_KIS_PDNO, "")
            if not pdno:
                errors.append("Position row missing 'pdno' — skipped")
                continue

            # Resolve instrument_id via symbol lookup
            try:
                instrument = await instrument_repo.get_by_symbol(
                    pdno, _DEFAULT_MARKET_CODE
                )
            except Exception as exc:
                logger.warning("Instrument lookup failed for pdno=%s: %s", pdno, exc)
                instrument = None

            if instrument is None:
                logger.warning(
                    "Skipping position pdno=%s — instrument not found in DB", pdno
                )
                errors.append(f"Instrument not found for pdno={pdno} — skipped")
                continue

            # Map KIS raw fields → PositionSnapshotEntity
            try:
                entity = PositionSnapshotEntity(
                    position_snapshot_id=uuid4(),
                    account_id=account_id,
                    instrument_id=instrument.instrument_id,
                    quantity=safe_decimal(raw.get(_KIS_HLDG_QTY, "0")),
                    average_price=safe_decimal(raw.get(_KIS_PCHS_AVG_PRIC, "0")),
                    market_price=safe_optional_decimal(raw.get(_KIS_PRPR)),
                    unrealized_pnl=safe_optional_decimal(raw.get(_KIS_EVL_PFLS_AMT)),
                    source_of_truth=_SOURCE_OF_TRUTH,
                    snapshot_at=snapshot_at,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to build PositionSnapshotEntity for pdno=%s: %s",
                    pdno,
                    exc,
                )
                errors.append(f"Mapping error for pdno={pdno}: {exc}")
                continue

            positions.append(entity)

        # ── 2. Fetch cash balance ─────────────────────────────────────────
        cash_balance: CashBalanceSnapshotEntity | None = None
        try:
            raw_cash: dict[str, Any] = await self._rest.get_cash_balance(
                after_hours=after_hours,
            )
        except Exception as exc:
            msg = f"Failed to fetch cash balance from KIS: {exc}"
            logger.error(msg)
            errors.append(msg)
            raw_cash = {}

        if raw_cash:
            try:
                available_cash = safe_decimal(raw_cash.get(_KIS_DNCA_TOT_AMT, "0"))
                # settled_cash: prefer nxdy_excc_amt, fall back to dnca_tot_amt
                settled_raw = raw_cash.get(_KIS_NXDY_EXCC_AMT)
                if settled_raw is not None and str(settled_raw).strip():
                    settled_cash = safe_decimal(settled_raw)
                else:
                    settled_cash = available_cash

                # unsettled_cash: difference if both are positive
                if (
                    available_cash > 0
                    and settled_cash > 0
                    and settled_cash < available_cash
                ):
                    unsettled_cash = available_cash - settled_cash
                else:
                    unsettled_cash = None

                # KIS output2 account-level summary fields
                total_asset = safe_optional_decimal(raw_cash.get(_KIS_TOT_EVL_AMT))
                settlement_amount = safe_optional_decimal(raw_cash.get(_KIS_PRVS_RCDL_EXCC_AMT))
                total_unrealized_pnl = safe_optional_decimal(raw_cash.get(_KIS_EVL_PFLS_SMTL_AMT))

                cash_balance = CashBalanceSnapshotEntity(
                    cash_balance_snapshot_id=uuid4(),
                    account_id=account_id,
                    currency="KRW",
                    available_cash=available_cash,
                    settled_cash=settled_cash,
                    unsettled_cash=unsettled_cash,
                    total_asset=total_asset,
                    settlement_amount=settlement_amount,
                    total_unrealized_pnl=total_unrealized_pnl,
                    source_of_truth=_SOURCE_OF_TRUTH,
                    snapshot_at=snapshot_at,
                )
            except Exception as exc:
                msg = f"Failed to map cash balance: {exc}"
                logger.error(msg)
                errors.append(msg)

        return FetchedSnapshot(
            positions=positions,
            cash_balance=cash_balance,
            errors=errors,
        )
