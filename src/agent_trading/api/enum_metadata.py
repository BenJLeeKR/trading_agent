"""Central registry for enum field metadata.

Every enum field that appears in API responses should have its metadata
registered here so that consumers (Admin UI, inspection scripts) can
resolve canonical values to human-readable labels without hardcoding.

Usage::

    from agent_trading.api.enum_metadata import ENUM_METADATA

    metadata = ENUM_METADATA["order_type"]
    label = metadata.value_map["limit"].label  # "지정가"

Design principles
-----------------
* ``values`` is the **sole source of truth** — ``value_map`` is a derived
  ``@property``, never stored separately.
* Canonical enum values (``enums.py``) are never modified.
* ``broker_code`` is a **display reference only** — the authoritative
  submit mapping lives in ``rest_client._map_order_type()``.
* ``supported`` indicates whether the value is actively supported by the
  current broker adapter implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class EnumValueMetadata:
    """Metadata for a single enum value."""

    value: str
    """Canonical enum value (matches ``enums.py``)."""

    label: str
    """Human-readable display label (e.g. ``"지정가"``)."""

    description: str | None = None
    """Optional explanation, especially for unsupported values."""

    broker_code: str | None = None
    """Broker-specific code for display reference only.

    .. note::

       This is **not** the authoritative submit mapping.  The actual
       ``ORD_DVSN`` code sent to KIS is determined by
       ``KISRestClient._map_order_type()`` in ``rest_client.py``.
    """

    supported: bool = True
    """``True`` when the value is actively supported by the broker adapter."""


@dataclass(frozen=True)
class EnumFieldMetadata:
    """Metadata for an entire enum field."""

    field: str
    """API field name (e.g. ``"order_type"``)."""

    type: str = "enum"
    """Metadata type discriminator (reserved for future use)."""

    values: tuple[EnumValueMetadata, ...] = ()
    """All possible values for this field — **source of truth**."""

    @property
    def value_map(self) -> dict[str, EnumValueMetadata]:
        """Derived O(1) lookup — not stored separately."""
        return {v.value: v for v in self.values}


# ═══════════════════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════════════════
#
# P0 — order_type:  registered + tested.
# P1 — side, order_status, decision_type, entry_style:  registered + tested.
#
# When adding a new field, append to ENUM_METADATA below.  No other
# changes are required — the API endpoint automatically picks it up.
#
# NOTE on ``side``: the canonical ``OrderSide`` enum only defines
# ``buy`` / ``sell``, but the ``TradeDecisionDetail.side`` API payload
# also uses ``hold`` as a drift value.  The metadata below includes
# ``hold`` for display coverage — this is **UI/API payload display
# metadata**, not a strict mirror of the domain enum.
# ═══════════════════════════════════════════════════════════════════════

ENUM_METADATA: dict[str, EnumFieldMetadata] = {
    "order_type": EnumFieldMetadata(
        field="order_type",
        values=(
            EnumValueMetadata(
                value="limit",
                label="지정가",
                broker_code="00",
                supported=True,
            ),
            EnumValueMetadata(
                value="market",
                label="시장가",
                broker_code="01",
                supported=True,
            ),
            EnumValueMetadata(
                value="stop",
                label="조건부지정가",
                broker_code="02",
                supported=False,
                description="KIS adapter currently unsupported",
            ),
            EnumValueMetadata(
                value="stop_limit",
                label="조건부지정가",
                broker_code="03",
                supported=False,
                description="KIS adapter currently unsupported",
            ),
        ),
    ),
    # ── P1: side ──────────────────────────────────────────────────
    # UI/API payload display metadata — includes ``hold`` drift value
    # that is not part of the canonical ``OrderSide`` enum.
    "side": EnumFieldMetadata(
        field="side",
        values=(
            EnumValueMetadata(value="buy", label="매수"),
            EnumValueMetadata(value="sell", label="매도"),
            EnumValueMetadata(value="hold", label="보류"),
        ),
    ),
    # ── P1: order_status ──────────────────────────────────────────
    # Mirrors ``OrderStatus`` enum in ``enums.py``.
    "order_status": EnumFieldMetadata(
        field="order_status",
        values=(
            EnumValueMetadata(value="draft", label="초안"),
            EnumValueMetadata(value="validated", label="검증됨"),
            EnumValueMetadata(value="pending_submit", label="제출 대기"),
            EnumValueMetadata(value="submitted", label="제출됨"),
            EnumValueMetadata(value="acknowledged", label="확인됨"),
            EnumValueMetadata(value="partially_filled", label="부분 체결"),
            EnumValueMetadata(value="filled", label="체결"),
            EnumValueMetadata(value="cancel_pending", label="취소 대기"),
            EnumValueMetadata(value="cancelled", label="취소됨"),
            EnumValueMetadata(value="rejected", label="거부됨"),
            EnumValueMetadata(value="expired", label="만료"),
            EnumValueMetadata(value="reconcile_required", label="조정 필요"),
        ),
    ),
    # ── P1: decision_type ─────────────────────────────────────────
    # Mirrors ``DecisionType`` enum in ``enums.py``.
    "decision_type": EnumFieldMetadata(
        field="decision_type",
        values=(
            EnumValueMetadata(value="approve", label="승인"),
            EnumValueMetadata(value="reject", label="거부"),
            EnumValueMetadata(value="hold", label="보류"),
            EnumValueMetadata(value="watch", label="관찰"),
            EnumValueMetadata(value="exit", label="청산"),
            EnumValueMetadata(value="reduce", label="축소"),
        ),
    ),
    # ── P1: entry_style ───────────────────────────────────────────
    # Mirrors ``EntryStyle`` enum in ``enums.py``.
    # NOTE: Not yet displayed in any UI component — metadata-only
    # registration for future use.
    "entry_style": EnumFieldMetadata(
        field="entry_style",
        values=(
            EnumValueMetadata(value="limit", label="지정가"),
            EnumValueMetadata(value="market", label="시장가"),
            EnumValueMetadata(value="vwap", label="VWAP"),
            EnumValueMetadata(value="twap", label="TWAP"),
            EnumValueMetadata(value="no_order", label="미주문"),
        ),
    ),
}


def get_enum_field(field: str) -> EnumFieldMetadata | None:
    """Look up a single field by name.  Returns ``None`` if not found."""
    return ENUM_METADATA.get(field)
