"""Tests for DedupKeyGenerator."""

from __future__ import annotations

import hashlib

import pytest

from agent_trading.brokers.dedup import DedupKeyGenerator


class TestDedupKeyGenerator:
    """DedupKeyGenerator determinism and stability."""

    def test_generate_returns_sha256_hex(self) -> None:
        """Output is a SHA-256 hex digest (64 hex chars)."""
        key = DedupKeyGenerator.generate(
            source_name="opendart",
            source_event_id="20230101000001",
            event_type="A|사업보고서",
            symbol=None,
            issuer_code="00123456",
        )
        assert len(key) == 64
        # Verify it's valid hex
        int(key, 16)

    def test_same_input_same_key(self) -> None:
        """Same inputs produce the same key (deterministic)."""
        key1 = DedupKeyGenerator.generate(
            source_name="opendart",
            source_event_id="20230101000001",
            event_type="A|사업보고서",
            issuer_code="00123456",
        )
        key2 = DedupKeyGenerator.generate(
            source_name="opendart",
            source_event_id="20230101000001",
            event_type="A|사업보고서",
            issuer_code="00123456",
        )
        assert key1 == key2

    def test_different_source_event_id_different_key(self) -> None:
        """Different source_event_id produces different key."""
        key1 = DedupKeyGenerator.generate(
            source_name="opendart",
            source_event_id="evt-001",
            event_type="A|사업보고서",
            issuer_code="00123456",
        )
        key2 = DedupKeyGenerator.generate(
            source_name="opendart",
            source_event_id="evt-002",
            event_type="A|사업보고서",
            issuer_code="00123456",
        )
        assert key1 != key2

    def test_different_event_type_different_key(self) -> None:
        """Different event_type produces different key."""
        key1 = DedupKeyGenerator.generate(
            source_name="opendart",
            source_event_id="evt-001",
            event_type="A|사업보고서",
            issuer_code="00123456",
        )
        key2 = DedupKeyGenerator.generate(
            source_name="opendart",
            source_event_id="evt-001",
            event_type="B|반기보고서",
            issuer_code="00123456",
        )
        assert key1 != key2

    def test_symbol_vs_issuer_code(self) -> None:
        """Symbol and issuer_code produce different keys when both provided."""
        key_with_symbol = DedupKeyGenerator.generate(
            source_name="test",
            source_event_id="evt-001",
            event_type="news",
            symbol="005930",
        )
        key_with_issuer = DedupKeyGenerator.generate(
            source_name="test",
            source_event_id="evt-001",
            event_type="news",
            issuer_code="00123456",
        )
        assert key_with_symbol != key_with_issuer

    def test_payload_hash_not_used(self) -> None:
        """Payload content does NOT affect the dedup key.

        This is the core rule: source-specific stable fields only.
        """
        key1 = DedupKeyGenerator.generate(
            source_name="opendart",
            source_event_id="evt-001",
            event_type="A|사업보고서",
            issuer_code="00123456",
        )
        key2 = DedupKeyGenerator.generate(
            source_name="opendart",
            source_event_id="evt-001",
            event_type="A|사업보고서",
            issuer_code="00123456",
        )
        # Same inputs regardless of payload → same key
        assert key1 == key2

    def test_generate_from_raw_convenience(self) -> None:
        """generate_from_raw() matches generate() with same args."""
        direct = DedupKeyGenerator.generate(
            source_name="opendart",
            source_event_id="evt-001",
            event_type="A|사업보고서",
            symbol="005930",
            issuer_code="00123456",
        )
        via_raw = DedupKeyGenerator.generate_from_raw(
            source_name="opendart",
            source_event_id="evt-001",
            event_type="A|사업보고서",
            symbol="005930",
            issuer_code="00123456",
        )
        assert direct == via_raw

    def test_known_key_format(self) -> None:
        """Verify the exact key format for a known input."""
        key = DedupKeyGenerator.generate(
            source_name="opendart",
            source_event_id="20230101000001",
            event_type="A|사업보고서",
            issuer_code="00123456",
        )
        expected_input = "opendart|20230101000001|A|사업보고서|00123456"
        expected_key = hashlib.sha256(expected_input.encode("utf-8")).hexdigest()
        assert key == expected_key
