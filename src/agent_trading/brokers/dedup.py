"""Deterministic dedup key generation for external events.

Rules (Priority 2 / v1)
-----------------------
* Use source-specific stable fields **first** — never payload hash alone.
* Key formula: ``{source_name}|{source_event_id}|{event_type}|{symbol or issuer_code}``
* The same ``source_event_id`` + ``event_type`` → same event,
  even if payload content differs (e.g. amended disclosure).
* SHA-256 hash of the stable key string for storage efficiency.
"""

from __future__ import annotations

import hashlib


class DedupKeyGenerator:
    """Deterministic dedup key generation for external events.

    The generator uses **source-specific stable fields** as the primary
    dedup signal. Payload content is explicitly excluded from the key
    so that amendments/corrections with the same source_event_id are
    correctly identified as the same logical event.
    """

    @staticmethod
    def generate(
        source_name: str,
        source_event_id: str,
        event_type: str,
        *,
        symbol: str | None = None,
        issuer_code: str | None = None,
    ) -> str:
        """Generate a deterministic dedup key hash.

        Parameters
        ----------
        source_name : str
            Stable source identifier (e.g. ``"opendart"``).
        source_event_id : str
            The source's own unique event identifier.
        event_type : str
            Source-level event classification.
        symbol : str | None
            Trading symbol, if available.
        issuer_code : str | None
            Issuer/corporate code, if available.

        Returns
        -------
        str
            SHA-256 hex digest of the stable key string.

        Notes
        -----
        At least one of ``symbol`` or ``issuer_code`` should be provided.
        If both are ``None``, the key is still valid but less specific.
        """
        identifier = symbol or issuer_code or ""
        stable_key = f"{source_name}|{source_event_id}|{event_type}|{identifier}"
        return hashlib.sha256(stable_key.encode("utf-8")).hexdigest()

    @staticmethod
    def generate_from_raw(source_name: str, source_event_id: str, event_type: str,
                          symbol: str | None = None, issuer_code: str | None = None) -> str:
        """Convenience wrapper matching ``RawEvent`` field names.

        This is the primary entry point for ``SourceAdapter.generate_dedup_key()``
        implementations.
        """
        return DedupKeyGenerator.generate(
            source_name=source_name,
            source_event_id=source_event_id,
            event_type=event_type,
            symbol=symbol,
            issuer_code=issuer_code,
        )
