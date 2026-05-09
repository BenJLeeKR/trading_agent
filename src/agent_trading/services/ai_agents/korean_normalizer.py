"""Korean text normalizer for AI Agent narrative fields.

This module provides a dual-purpose utility:

1. Detect whether a string contains Korean (Hangul) characters.
2. Normalize non-Korean narrative text to ensure it is marked as needing
   Korean translation before being persisted to PostgreSQL.

Usage
-----
    from agent_trading.services.ai_agents.korean_normalizer import (
        validate_or_normalize_korean,
        normalize_structured_output,
    )

    # Single string
    text = validate_or_normalize_korean("Market momentum slowing")
    # -> "[ko: Market momentum slowing]"

    # Recursive dict
    output = normalize_structured_output({
        "summary": "Market momentum slowing",
        "agent_name": "ai_risk",
        "opposing_evidence": ("Liquidity concern",),
    })
    # -> {
    #     "summary": "[ko: Market momentum slowing]",
    #     "agent_name": "ai_risk",       ← untouched (non-narrative key)
    #     "opposing_evidence": ("[ko: Liquidity concern]",),
    # }
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

# Unicode ranges for Korean (Hangul).
#   \uAC00-\uD7AF  Hangul Syllables (modern Korean)
#   \u1100-\u11FF  Hangul Jamo (consonant/vowel building blocks)
#   \u3130-\u318F  Hangul Compatibility Jamo
_KOREAN_RE = re.compile(r"[\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F]")

# Known narrative keys whose values MUST be Korean.
#
# These keys appear at various depths in the structured output dict.
# Machine-readable fields (reason_codes, decision_type, side, etc.) are
# intentionally excluded from this set — they remain in English.
_NARRATIVE_KEYS: frozenset[str] = frozenset({
    "summary",
    "risk_opinion",
    "opposing_evidence",
})

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def contains_korean(text: str) -> bool:
    """Return ``True`` if *text* contains at least one Korean (Hangul) character."""
    return bool(_KOREAN_RE.search(text))


def validate_or_normalize_korean(text: str | None) -> str | None:
    """Ensure *text* contains Korean; if not, wrap it with a ``[ko: ...]`` marker.

    Parameters
    ----------
    text
        The narrative text string to check.  ``None`` and empty strings are
        returned as-is.

    Returns
    -------
    str | None
        * If *text* is ``None`` or ``""`` -> unchanged.
        * If *text* already contains Korean -> unchanged.
        * If *text* has no Korean -> wrapped as ``"[ko: {text}]"``.
    """
    if not text:  # None or ""
        return text
    if contains_korean(text):
        return text
    return f"[ko: {text}]"


def normalize_structured_output(output: dict[str, Any]) -> dict[str, Any]:
    """Normalise narrative text fields in an agent's structured output dict.

    This function recursively walks the dict and applies
    ``validate_or_normalize_korean()`` to any string value whose key is in
    ``_NARRATIVE_KEYS`` (``"summary"``, ``"risk_opinion"``,
    ``"opposing_evidence"``).

    Non-narrative fields (``agent_name``, ``reason_codes``, ``decision_type``,
    ``side``, etc.) are left untouched.

    Parameters
    ----------
    output
        The ``structured_output_json`` dict from an agent run.
        Must be JSON-compatible (strings, numbers, bools, None, dicts, lists/tuples).

    Returns
    -------
    dict[str, Any]
        A new dict with narrative fields normalized.
    """
    return _normalize_node(output, depth=0)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_node(value: Any, depth: int) -> Any:
    """Recursively walk a JSON-compatible value and normalise narrative fields."""
    # Safety limit to prevent infinite recursion on cyclic references.
    if depth > 20:
        return value

    if isinstance(value, Mapping):
        # ── dict-like node: check each key ──
        return {
            k: _normalize_narrative_value(k, v, depth + 1)
            for k, v in value.items()
        }

    if isinstance(value, str):
        # Standalone string (not inside a dict) — normalise if it's narrative.
        # This path is reached for string values inside lists/tuples when
        # the parent key is narrative (e.g. opposing_evidence items).
        # Without key context we assume it IS narrative text.
        return validate_or_normalize_korean(value)

    if isinstance(value, (list, tuple)):
        # ── sequence node: recurse into each element ──
        # Preserve the original type (tuple vs list).
        converted = [_normalize_node(item, depth + 1) for item in value]
        return type(value)(converted)  # type: ignore[arg-type]

    # Scalar (int, float, bool, None) — unchanged.
    return value


def _normalize_narrative_value(key: str, value: Any, depth: int) -> Any:
    """Normalise a single value at *key*, recursing into nested structures.

    This is the key-aware variant that only normalises when the field name
    matches a known narrative key.
    """
    if depth > 20:
        return value

    # ── Dict child ──
    if isinstance(value, Mapping):
        return {k: _normalize_narrative_value(k, v, depth + 1) for k, v in value.items()}

    # ── List/tuple child ──
    if isinstance(value, (list, tuple)):
        # If the key is narrative (opposing_evidence), normalise each string element.
        if key in _NARRATIVE_KEYS:
            converted = [_normalize_node(item, depth + 1) for item in value]
            return type(value)(converted)  # type: ignore[arg-type]
        # Otherwise recurse into each element with _normalize_narrative_value
        # so that nested dicts inside arrays are still key-aware.
        converted = [_normalize_narrative_value(key, item, depth + 1) for item in value]
        return type(value)(converted)  # type: ignore[arg-type]

    # ── String child ──
    if isinstance(value, str):
        if key in _NARRATIVE_KEYS:
            return validate_or_normalize_korean(value)
        return value

    # Scalar — unchanged.
    return value
