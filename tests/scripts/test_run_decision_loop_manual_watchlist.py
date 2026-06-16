from scripts.run_decision_loop import _parse_manual_watchlist_symbols


def test_parse_manual_watchlist_symbols_deduplicates_and_defaults_market() -> None:
    parsed = _parse_manual_watchlist_symbols("005930,000660:KRX,005930,001740.KRX")

    assert parsed == (
        ("005930", "KRX"),
        ("000660", "KRX"),
        ("001740", "KRX"),
    )


def test_parse_manual_watchlist_symbols_empty_returns_empty_tuple() -> None:
    assert _parse_manual_watchlist_symbols(None) == ()
    assert _parse_manual_watchlist_symbols("   ") == ()
