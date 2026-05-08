from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from agent_trading.brokers.koreainvestment.rest_client import KISRestClient
from agent_trading.domain.entities import (
    CashBalanceSnapshotEntity,
    PositionSnapshotEntity,
)
from agent_trading.repositories.contracts import (
    CashBalanceSnapshotRepository,
    InstrumentRepository,
    PositionSnapshotRepository,
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
_KIS_ORD_PSBL_AMT = "ord_psbl_amt"  # 주문가능금액 (fallback용)

_SOURCE_OF_TRUTH = "broker"
_DEFAULT_MARKET_CODE = "KRX"


@dataclass(slots=True, frozen=True)
class SyncResult:
    """Result of a single KIS account snapshot sync operation.

    Uses ``object.__setattr__`` internally because the dataclass is frozen
    (immutable by contract for callers), but the sync function needs to
    accumulate counters.
    """

    positions_synced: int = 0
    positions_skipped: int = 0
    cash_balance_synced: bool = False
    errors: list[str] = field(default_factory=list)

    def _incr(self, field_name: str, delta: int = 1) -> None:
        object.__setattr__(self, field_name, getattr(self, field_name) + delta)

    def _set(self, field_name: str, value: object) -> None:
        object.__setattr__(self, field_name, value)

    def _add_error(self, msg: str) -> None:
        self.errors.append(msg)


async def sync_kis_account_snapshots(
    rest_client: KISRestClient,
    instrument_repo: InstrumentRepository,
    position_snapshot_repo: PositionSnapshotRepository,
    cash_balance_snapshot_repo: CashBalanceSnapshotRepository,
    account_id: UUID,
) -> SyncResult:
    """Fetch KIS positions and cash balance, then store as snapshots.

    Parameters
    ----------
    rest_client:
        Authenticated KIS REST client.
    instrument_repo:
        Repository for resolving ``pdno`` (KIS product code) to
        ``instrument_id`` (UUID).
    position_snapshot_repo:
        Repository for persisting position snapshots.
    cash_balance_snapshot_repo:
        Repository for persisting cash-balance snapshots.
    account_id:
        The ``AccountEntity.account_id`` (UUID) to associate with the
        snapshots.

    Returns
    -------
    SyncResult
        Summary of what was synced, skipped, or errored.
    """
    result = SyncResult()
    snapshot_at = datetime.now(tz=timezone.utc)

    # ── 1. Sync positions ──────────────────────────────────────────────
    try:
        raw_positions: Sequence[dict[str, Any]] = await rest_client.get_positions()
    except Exception as exc:
        msg = f"Failed to fetch positions from KIS: {exc}"
        logger.error(msg)
        result._add_error(msg)
        raw_positions = []

    for raw in raw_positions:
        pdno = raw.get(_KIS_PDNO, "")
        if not pdno:
            result._incr("positions_skipped")
            result._add_error("Position row missing 'pdno' — skipped")
            continue

        # Resolve instrument_id via symbol lookup
        try:
            instrument = await instrument_repo.get_by_symbol(pdno, _DEFAULT_MARKET_CODE)
        except Exception as exc:
            logger.warning("Instrument lookup failed for pdno=%s: %s", pdno, exc)
            instrument = None

        if instrument is None:
            logger.warning(
                "Skipping position pdno=%s — instrument not found in DB", pdno
            )
            result._incr("positions_skipped")
            result._add_error(f"Instrument not found for pdno={pdno} — skipped")
            continue

        # Map KIS raw fields → PositionSnapshotEntity
        try:
            entity = PositionSnapshotEntity(
                position_snapshot_id=uuid4(),
                account_id=account_id,
                instrument_id=instrument.instrument_id,
                quantity=_safe_decimal(raw.get(_KIS_HLDG_QTY, "0")),
                average_price=_safe_decimal(raw.get(_KIS_PCHS_AVG_PRIC, "0")),
                market_price=_safe_optional_decimal(raw.get(_KIS_PRPR)),
                unrealized_pnl=_safe_optional_decimal(raw.get(_KIS_EVL_PFLS_AMT)),
                source_of_truth=_SOURCE_OF_TRUTH,
                snapshot_at=snapshot_at,
            )
        except Exception as exc:
            logger.warning("Failed to build PositionSnapshotEntity for pdno=%s: %s", pdno, exc)
            result._incr("positions_skipped")
            result._add_error(f"Mapping error for pdno={pdno}: {exc}")
            continue

        try:
            await position_snapshot_repo.add(entity)
            result._incr("positions_synced")
        except Exception as exc:
            logger.error("Failed to persist position snapshot pdno=%s: %s", pdno, exc)
            result._add_error(f"Persist error for pdno={pdno}: {exc}")

    # ── 2. Sync cash balance ───────────────────────────────────────────
    try:
        raw_cash: dict[str, Any] = await rest_client.get_cash_balance()
    except Exception as exc:
        msg = f"Failed to fetch cash balance from KIS: {exc}"
        logger.error(msg)
        result._add_error(msg)
        raw_cash = {}

    if raw_cash:
        try:
            available_cash = _safe_decimal(raw_cash.get(_KIS_DNCA_TOT_AMT, "0"))
            # settled_cash: prefer nxdy_excc_amt, fall back to dnca_tot_amt
            settled_raw = raw_cash.get(_KIS_NXDY_EXCC_AMT)
            if settled_raw is not None and str(settled_raw).strip():
                settled_cash = _safe_decimal(settled_raw)
            else:
                settled_cash = available_cash

            # unsettled_cash: difference if both are positive
            if available_cash > 0 and settled_cash > 0 and settled_cash < available_cash:
                unsettled_cash = available_cash - settled_cash
            else:
                unsettled_cash = None

            cash_entity = CashBalanceSnapshotEntity(
                cash_balance_snapshot_id=uuid4(),
                account_id=account_id,
                currency="KRW",
                available_cash=available_cash,
                settled_cash=settled_cash,
                unsettled_cash=unsettled_cash,
                source_of_truth=_SOURCE_OF_TRUTH,
                snapshot_at=snapshot_at,
            )
        except Exception as exc:
            msg = f"Failed to map cash balance: {exc}"
            logger.error(msg)
            result._add_error(msg)
            cash_entity = None

        if cash_entity is not None:
            try:
                await cash_balance_snapshot_repo.add(cash_entity)
                result._set("cash_balance_synced", True)
            except Exception as exc:
                msg = f"Failed to persist cash balance snapshot: {exc}"
                logger.error(msg)
                result._add_error(msg)

    return result


# ── Helpers ─────────────────────────────────────────────────────────────


def _safe_decimal(value: object) -> Decimal:
    """Convert a KIS string-or-number to ``Decimal``, defaulting to ``0``."""
    try:
        return Decimal(str(value))
    except (ValueError, TypeError, ArithmeticError):
        return Decimal("0")


def _safe_optional_decimal(value: object) -> Decimal | None:
    """Convert a KIS string-or-number to ``Decimal | None``."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return Decimal(s)
    except (ValueError, TypeError, ArithmeticError):
        return None
