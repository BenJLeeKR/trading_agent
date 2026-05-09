"""Unit tests for ``korean_normalizer``.

Tests cover:
* ``contains_korean()`` — Hangul detection
* ``validate_or_normalize_korean()`` — single-string normalisation
* ``normalize_structured_output()`` — recursive dict traversal
"""

from __future__ import annotations

from agent_trading.services.ai_agents.korean_normalizer import (
    contains_korean,
    normalize_structured_output,
    validate_or_normalize_korean,
)


# ============================================================================
# contains_korean
# ============================================================================


class TestContainsKorean:
    def test_hangul_syllables(self) -> None:
        """Pure Hangul text is detected."""
        assert contains_korean("안녕하세요") is True

    def test_english_text(self) -> None:
        """Pure English text is NOT detected."""
        assert contains_korean("Hello, world!") is False

    def test_mixed_text(self) -> None:
        """Mixed Hangul + English is detected."""
        assert contains_korean("매수 신호 detected") is True

    def test_empty_string(self) -> None:
        """Empty string is NOT detected."""
        assert contains_korean("") is False

    def test_numbers_and_symbols(self) -> None:
        """Numeric/symbolic strings are NOT detected."""
        assert contains_korean("12345 !@#$%") is False

    def test_english_with_korean_particle(self) -> None:
        """Korean particles attached to English are detected."""
        assert contains_korean("AAPL은") is True


# ============================================================================
# validate_or_normalize_korean
# ============================================================================


class TestValidateOrNormalizeKorean:
    def test_korean_passes_through(self) -> None:
        """Korean text is returned unchanged."""
        result = validate_or_normalize_korean("시장 모멘텀 둔화로 진입 보류")
        assert result == "시장 모멘텀 둔화로 진입 보류"

    def test_english_wrapped(self) -> None:
        """English text is wrapped with [ko: ...] marker."""
        result = validate_or_normalize_korean("Market momentum slowing")
        assert result == "[ko: Market momentum slowing]"

    def test_mixed_passes_through(self) -> None:
        """Mixed Korean + English passes through unchanged."""
        result = validate_or_normalize_korean("매수 신호 strong buy signal detected")
        assert result == "매수 신호 strong buy signal detected"

    def test_none_returns_none(self) -> None:
        """None is returned as-is."""
        result = validate_or_normalize_korean(None)
        assert result is None

    def test_empty_string_returns_empty(self) -> None:
        """Empty string is returned as-is."""
        result = validate_or_normalize_korean("")
        assert result == ""

    def test_korean_with_english_parens(self) -> None:
        """Korean with English parenthetical passes through."""
        result = validate_or_normalize_korean("변동성 증가 (volatility surge)")
        assert result == "변동성 증가 (volatility surge)"

    def test_english_with_numbers_wrapped(self) -> None:
        """English with numbers is still wrapped."""
        result = validate_or_normalize_korean("Score 85 out of 100")
        assert result == "[ko: Score 85 out of 100]"


# ============================================================================
# normalize_structured_output
# ============================================================================


class TestNormalizeStructuredOutput:
    def test_summary_korean_passes(self) -> None:
        """Korean 'summary' value is unchanged."""
        output = {"summary": "리스크 평가 통과", "agent_name": "ai_risk"}
        result = normalize_structured_output(output)
        assert result["summary"] == "리스크 평가 통과"

    def test_summary_english_wrapped(self) -> None:
        """English 'summary' value is wrapped with [ko: ...]."""
        output = {"summary": "Risk assessment passed", "agent_name": "ai_risk"}
        result = normalize_structured_output(output)
        assert result["summary"] == "[ko: Risk assessment passed]"
        # Non-narrative field untouched
        assert result["agent_name"] == "ai_risk"

    def test_opposing_evidence_tuple_normalized(self) -> None:
        """Each string in 'opposing_evidence' tuple is normalised."""
        output = {
            "opposing_evidence": (
                "Liquidity concern",
                "Market volatility",
            ),
        }
        result = normalize_structured_output(output)
        assert result["opposing_evidence"] == (
            "[ko: Liquidity concern]",
            "[ko: Market volatility]",
        )

    def test_opposing_evidence_list_normalized(self) -> None:
        """Each string in 'opposing_evidence' list is normalised."""
        output = {
            "opposing_evidence": [
                "Low volume warning",
                "Gap risk",
            ],
        }
        result = normalize_structured_output(output)
        assert result["opposing_evidence"] == [
            "[ko: Low volume warning]",
            "[ko: Gap risk]",
        ]

    def test_opposing_evidence_korean_passes(self) -> None:
        """Korean strings in 'opposing_evidence' pass through."""
        output = {
            "opposing_evidence": ("유동성 부족", "변동성 위험"),
        }
        result = normalize_structured_output(output)
        assert result["opposing_evidence"] == ("유동성 부족", "변동성 위험")

    def test_risk_opinion_normalized(self) -> None:
        """'risk_opinion' value is normalised."""
        output = {"risk_opinion": "allow with caution"}
        result = normalize_structured_output(output)
        assert result["risk_opinion"] == "[ko: allow with caution]"

    def test_risk_opinion_korean_passes(self) -> None:
        """Korean 'risk_opinion' passes through."""
        output = {"risk_opinion": "조심스럽게 허용"}
        result = normalize_structured_output(output)
        assert result["risk_opinion"] == "조심스럽게 허용"

    def test_non_narrative_fields_untouched(self) -> None:
        """Machine-readable fields are not modified."""
        output = {
            "decision_type": "APPROVE",
            "side": "BUY",
            "reason_codes": ("MOMENTUM", "VOLUME"),
            "agent_name": "final_decision_composer",
            "schema_version": "v1",
            "confidence": 0.85,
            "entry_style": "LIMIT",
        }
        result = normalize_structured_output(output)
        assert result == output

    def test_nested_dict_summary_normalized(self) -> None:
        """Nested 'summary' inside a sub-dict is normalised."""
        output = {
            "events": (
                {"event_type": "Y", "summary": "Strong earnings"},
                {"event_type": "N", "summary": "규제 리스크"},
            ),
        }
        result = normalize_structured_output(output)
        events = result["events"]
        assert events[0]["summary"] == "[ko: Strong earnings]"
        assert events[1]["summary"] == "규제 리스크"

    def test_nested_opposing_evidence_normalized(self) -> None:
        """Nested 'opposing_evidence' inside aggregate_view is normalised."""
        output = {
            "aggregate_view": {
                "overall_bias": "positive",
                "opposing_evidence": ("Conflicting signals",),
            },
        }
        result = normalize_structured_output(output)
        assert result["aggregate_view"]["opposing_evidence"] == (
            "[ko: Conflicting signals]",
        )

    def test_empty_dict_unchanged(self) -> None:
        """Empty dict returns empty dict."""
        assert normalize_structured_output({}) == {}

    def test_none_values_unchanged(self) -> None:
        """None values are preserved."""
        output = {"summary": None, "agent_name": None}
        result = normalize_structured_output(output)
        assert result["summary"] is None
        assert result["agent_name"] is None

    def test_tuple_of_strings_preserved(self) -> None:
        """Tuple type is preserved after normalisation."""
        output = {"opposing_evidence": ("English text",)}
        result = normalize_structured_output(output)
        assert isinstance(result["opposing_evidence"], tuple)
        assert result["opposing_evidence"] == ("[ko: English text]",)
