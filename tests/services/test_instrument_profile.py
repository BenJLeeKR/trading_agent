from agent_trading.services.instrument_profile import (
    derive_primary_index_membership,
    normalize_index_memberships,
)


def test_normalize_index_memberships_prefers_higher_priority_codes_first() -> None:
    memberships = normalize_index_memberships(
        ["KOSPI200", "KOSPI100", "KOSPI200", "KOSDAQ150"]
    )
    assert memberships == ("KOSPI100", "KOSPI200", "KOSDAQ150")


def test_derive_primary_index_membership_picks_more_specific_nested_code() -> None:
    primary = derive_primary_index_membership(["KOSPI200", "KOSPI100"])
    assert primary == "KOSPI100"


def test_derive_primary_index_membership_returns_none_for_empty_input() -> None:
    assert derive_primary_index_membership([]) is None
