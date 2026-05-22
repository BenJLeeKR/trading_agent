"""KIS (Korea Investment) implementation of ``SnapshotFetchProvider``.

Wraps ``KISRestClient`` and handles KIS-specific field mapping from raw
API response fields to domain entities.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4, uuid7

from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.brokers.rate_limit import BudgetExhaustedError
from agent_trading.domain.entities import (
    CashBalanceSnapshotEntity,
    PositionSnapshotEntity,
    RiskLimitSnapshotEntity,
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
_KIS_PCHS_AMT = "pchs_amt"  # 매입금액
_KIS_EVL_AMT = "evlu_amt"  # 평가금액

# KIS inquire-balance output2 (cash summary) field names
_KIS_DNCA_TOT_AMT = "dnca_tot_amt"  # 예수금총액
_KIS_NXDY_EXCC_AMT = "nxdy_excc_amt"  # 익일초과액
_KIS_TOT_EVL_AMT = "tot_evlu_amt"  # 총평가금액 (유가증권 평가금액 합계 + D+2 예수금)
_KIS_PRVS_RCDL_EXCC_AMT = "prvs_rcdl_excc_amt"  # 가수도정산금액 (D+2 예수금 기준)
_KIS_EVL_PFLS_SMTL_AMT = "evlu_pfls_smtl_amt"  # 평가손익합계금액 (계좌 총괄)
_KIS_ORD_PSBL_AMT = "ord_psbl_amt"  # 주문가능금액

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
        fetch_positions: bool = True,
    ) -> FetchedSnapshot:
        """Fetch KIS cash balance and positions, return as domain entities.

        Cash/orderable 조회를 positions보다 먼저 수행하여, 제한된 inquiry
        budget 환경에서도 cash snapshot이 우선적으로 성공하도록 보장한다.
        (BudgetExhaustedError 발생 시 positions는 실패해도 cash는 저장됨)

        ``fetch_positions=False``로 호출하면 positions 조회를 건너뛰어,
        budget이 부족한 상황에서도 cash+orderable을 안전하게 확보할 수 있다.
        positions는 별도 사이클(``fetch_positions=True``)에서 가져온다.

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
        fetch_positions:
            When ``False``, skip positions fetch entirely (cash+orderable only).
            Use this in Phase 1 of a split sync cycle; call again with
            ``fetch_positions=True`` in Phase 2.

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
        raw_positions: Sequence[Any] = []

        # ── 1. Fetch cash balance (우선) ─────────────────────────────────
        # cash/orderable은 submit에 가장 중요하므로 positions보다 먼저 확보
        cash_balance: CashBalanceSnapshotEntity | None = None

        try:
            raw_cash: dict[str, Any] = await self._rest.get_cash_balance(
                after_hours=after_hours,
            )
        except BudgetExhaustedError as exc:
            msg = f"Cash balance inquiry budget exhausted: {exc}"
            logger.error(msg)
            errors.append(msg)
            raw_cash = {}
        except Exception as exc:
            msg = f"Failed to fetch cash balance from KIS: {exc}"
            logger.error(msg, exc_info=True)
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

                # ── orderable_amount: VTTC8908R 시도, 실패 시 raw_cash fallback ──
                # get_cash_balance()는 VTTC8434R(inquire-balance) 사용 — paper에서
                # ord_psbl_cash를 반환하지 않음. get_orderable_cash()는 VTTC8908R
                # (inquire-psbl-order) 사용 — paper에서도 ord_psbl_cash 제공.
                # BudgetExhaustedError 발생 시 raw_cash(available_cash)로 fallback.
                orderable_amount: Decimal | None = None

                # Paper 1 RPS pacing: ensure at least 1s between consecutive KIS calls
                await asyncio.sleep(1.0)

                try:
                    orderable_cash = await self._rest.get_orderable_cash(
                        account_ref="",
                    )
                except BudgetExhaustedError:
                    # Budget 소진 → raw_cash로 fallback (CASH_SYNC_ZERO 방지)
                    logger.warning(
                        "VTTC8908R get_orderable_cash() budget exhausted; "
                        "falling back to raw_cash (available_cash=%s)",
                        available_cash,
                    )
                    orderable_cash = available_cash
                except Exception:
                    # 일반 Exception → available_cash로 fallback (VTTC8434R ord_psbl_amt는
                    # paper에서 unreliable하므로 available_cash가 더 안전)
                    logger.warning(
                        "VTTC8908R get_orderable_cash() failed; "
                        "falling back to available_cash=%s",
                        available_cash,
                        exc_info=True,
                    )
                    orderable_cash = available_cash

                if orderable_cash is not None:
                    orderable_amount = Decimal(str(orderable_cash))
                    logger.info(
                        "orderable_amount=%s (source: VTTC8908R)",
                        orderable_cash,
                    )
                else:
                    # Fallback: use ord_psbl_amt from VTTC8434R output2
                    orderable_amount = safe_optional_decimal(
                        raw_cash.get(_KIS_ORD_PSBL_AMT)
                    )
                    if orderable_amount is not None:
                        logger.info(
                            "orderable_amount=%s (source: VTTC8434R fallback)",
                            orderable_amount,
                        )
                    else:
                        logger.info(
                            "orderable_amount=None (VTTC8908R unavailable, "
                            "VTTC8434R ord_psbl_amt also missing)"
                        )

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
                    orderable_amount=orderable_amount,
                    source_of_truth=_SOURCE_OF_TRUTH,
                    snapshot_at=snapshot_at,
                )
            except Exception as exc:
                msg = f"Failed to map cash balance: {exc}"
                logger.error(msg)
                errors.append(msg)

        # ── 2. Fetch positions (cash 다음, skip in after-hours or fetch_positions=False) ──
        if after_hours:
            logger.info("After-hours mode — skipping positions fetch (cash-only sync)")
            raw_positions = []
        elif not fetch_positions:
            logger.info(
                "fetch_positions=False — skipping positions fetch "
                "(Phase 1: cash+orderable only; positions will be fetched in Phase 2)"
            )
            raw_positions = []
        else:
            try:
                raw_positions = await self._rest.get_positions()
            except BudgetExhaustedError as exc:
                msg = f"Positions inquiry budget exhausted: {exc}"
                logger.error(msg)
                errors.append(msg)
                raw_positions = []
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
                    purchase_amount=safe_optional_decimal(raw.get(_KIS_PCHS_AMT)),
                    evaluation_amount=safe_optional_decimal(raw.get(_KIS_EVL_AMT)),
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

        # ── 3. Build RiskLimitSnapshotEntity from available data ────────────
        risk_limit: RiskLimitSnapshotEntity | None = None
        if cash_balance is not None and cash_balance.total_asset is not None:
            risk_limit = RiskLimitSnapshotEntity(
                risk_limit_snapshot_id=uuid7(),
                account_id=account_id,
                nav=cash_balance.total_asset,
                snapshot_at=cash_balance.snapshot_at,
            )

        return FetchedSnapshot(
            positions=positions,
            cash_balance=cash_balance,
            risk_limit_snapshot=risk_limit,
            errors=errors,
        )
