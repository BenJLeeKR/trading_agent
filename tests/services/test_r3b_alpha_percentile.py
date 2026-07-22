"""Tests for R3b candidate pool 내부 percentile 최하위 floor(SPPV-2.97/2.98).

핵심 검증:
1. floor 미만인 raw percentile은 CANDIDATE_PERCENTILE_FLOOR로 올라간다.
2. floor 이상인 raw percentile(최상위/중상위권)은 전혀 영향받지 않는다
   (max() 연산의 단조증가 성질 — 상위권 무손상).
3. candidate pool 밖 종목(신호 결측/quintile 밖)에는 영향이 없다.
"""

from __future__ import annotations

from agent_trading.services.r3b_alpha_percentile import (
    CANDIDATE_PERCENTILE_FLOOR,
    R3bAlphaInput,
    build_candidate_percentiles,
)


def _make_item(symbol: str, signal_rank: float) -> R3bAlphaInput:
    """range_bound 라벨에서 signal_rank를 그대로 return_3m_pct로 사용
    (volatility_20d_pct=1.0으로 고정해 regime_conditional_signal이
    signal_rank와 동일해지도록 단순화)."""
    return R3bAlphaInput(
        symbol=symbol,
        market_common_label="range_bound",
        return_1m_pct=0.0,
        return_3m_pct=signal_rank,
        volatility_20d_pct=1.0,
    )


class TestCandidatePercentileFloor:
    def test_floor_constant_is_0_60(self) -> None:
        assert CANDIDATE_PERCENTILE_FLOOR == 0.60

    def test_bottom_of_three_candidate_pool_floored(self) -> None:
        """n=3 pool에서 최하위(raw=0.0)가 floor로 올라가는지."""
        items = [_make_item(f"S{i}", float(i)) for i in range(10)]
        percentiles = build_candidate_percentiles(items)
        # top 20% of 10 = 2개 candidate (S9, S8) -> n=2, floor 미만이면 상향
        assert len(percentiles) == 2
        assert percentiles["S9"] == 1.0  # 최상위: 무손상
        assert percentiles["S8"] == CANDIDATE_PERCENTILE_FLOOR  # 최하위: floor 적용(원래 0.0)

    def test_top_of_pool_untouched_by_floor(self) -> None:
        """최상위 종목(raw percentile=1.0)은 floor와 무관하게 그대로 유지."""
        items = [_make_item(f"S{i}", float(i)) for i in range(20)]
        percentiles = build_candidate_percentiles(items)
        top_symbol = max(percentiles, key=lambda s: percentiles[s])
        assert percentiles[top_symbol] == 1.0

    def test_mid_rank_already_above_floor_untouched(self) -> None:
        """raw percentile이 이미 floor 이상이면 값이 바뀌지 않는다."""
        # n=5 pool: raw percentiles = 0.0, 0.25, 0.5, 0.75, 1.0
        items = [_make_item(f"S{i}", float(i)) for i in range(25)]
        percentiles = build_candidate_percentiles(items)
        assert len(percentiles) == 5
        ordered = sorted(percentiles.items(), key=lambda kv: kv[1])
        # raw(0.0, 0.25, 0.5)는 floor(0.60) 미만이라 전부 0.60으로 상향,
        # raw(0.75, 1.0)는 이미 floor 이상이라 원래 값 그대로 유지
        assert ordered[0][1] == CANDIDATE_PERCENTILE_FLOOR
        assert ordered[1][1] == CANDIDATE_PERCENTILE_FLOOR
        assert ordered[2][1] == CANDIDATE_PERCENTILE_FLOOR
        assert ordered[3][1] == 0.75
        assert ordered[4][1] == 1.0

    def test_pool_below_5_valid_signals_returns_empty(self) -> None:
        """기존 동작(신호 5개 미만이면 빈 dict) 유지 — floor 도입이 이 경로를 바꾸지 않는다."""
        items = [_make_item(f"S{i}", float(i)) for i in range(3)]
        assert build_candidate_percentiles(items) == {}

    def test_no_valid_signal_symbol_absent_from_result(self) -> None:
        """신호 결측 종목은 floor 적용 대상도 아니고 결과에 아예 없어야 한다."""
        items = [_make_item(f"S{i}", float(i)) for i in range(10)]
        items.append(
            R3bAlphaInput(
                symbol="MISSING",
                market_common_label="range_bound",
                return_1m_pct=None,
                return_3m_pct=None,
                volatility_20d_pct=None,
            )
        )
        percentiles = build_candidate_percentiles(items)
        assert "MISSING" not in percentiles
