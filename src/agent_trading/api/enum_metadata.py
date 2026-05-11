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
# P0 — order_type:  registered + tested in this iteration.
# P1 — order_status, side, decision_type, entry_style:
#      structure supports extension; registration deferred to a follow-up.
#
# When adding a new field, append to ENUM_METADATA below.  No other
# changes are required — the API endpoint automatically picks it up.
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
}


def get_enum_field(field: str) -> EnumFieldMetadata | None:
    """Look up a single field by name.  Returns ``None`` if not found."""
    return ENUM_METADATA.get(field)
