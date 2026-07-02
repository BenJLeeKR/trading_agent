from __future__ import annotations

from agent_trading.services.core_risk_off_topk_projection import (
    project_core_risk_off_topk_exceptions,
)
from agent_trading.services.deterministic_trigger_engine import (
    DeterministicTriggerAssessment,
)


def _make_assessment(
    *,
    symbol_score: float,
    entry_score: float,
    active: bool = True,
    candidate: bool = True,
    top_k_cap: int = 2,
) -> DeterministicTriggerAssessment:
    return DeterministicTriggerAssessment(
        trigger_version="deterministic_trigger_v1",
        primary_candidate="WATCH",
        candidate_set=("WATCH",),
        watch_candidate=True,
        buy_candidate=False,
        sell_candidate=False,
        reduce_candidate=False,
        candidate_confidence=entry_score,
        entry_score=entry_score,
        exit_score=0.0,
        watch_score=entry_score,
        eligibility_passed=False,
        ranking_score=symbol_score,
        metadata={
            "core_risk_off_experiment": {
                "active": active,
                "shadow_topk_candidate": candidate,
                "shadow_rank_candidate_score": symbol_score,
                "shadow_top_k_cap": top_k_cap,
                "shadow_group_size": None,
                "shadow_rank": None,
                "shadow_topk_selected": False,
                "shadow_would_pass": False,
            }
        },
    )


def test_projection_marks_only_top_two_candidates_selected() -> None:
    projected = project_core_risk_off_topk_exceptions(
        {
            "BBB": _make_assessment(symbol_score=0.31, entry_score=0.20),
            "AAA": _make_assessment(symbol_score=0.33, entry_score=0.19),
            "CCC": _make_assessment(symbol_score=0.29, entry_score=0.25),
        }
    )

    assert projected["AAA"].metadata["core_risk_off_experiment"]["shadow_topk_selected"] is True
    assert projected["BBB"].metadata["core_risk_off_experiment"]["shadow_topk_selected"] is True
    assert projected["CCC"].metadata["core_risk_off_experiment"]["shadow_topk_selected"] is False
    assert projected["AAA"].metadata["core_risk_off_experiment"]["shadow_rank"] == 1
    assert projected["BBB"].metadata["core_risk_off_experiment"]["shadow_rank"] == 2
    assert projected["CCC"].metadata["core_risk_off_experiment"]["shadow_rank"] == 3
    assert projected["AAA"].metadata["core_risk_off_experiment"]["shadow_group_size"] == 3


def test_projection_uses_entry_score_then_symbol_as_tie_breaker() -> None:
    projected = project_core_risk_off_topk_exceptions(
        {
            "BBB": _make_assessment(symbol_score=0.30, entry_score=0.15),
            "AAA": _make_assessment(symbol_score=0.30, entry_score=0.15),
            "CCC": _make_assessment(symbol_score=0.30, entry_score=0.20),
        }
    )

    assert projected["CCC"].metadata["core_risk_off_experiment"]["shadow_rank"] == 1
    assert projected["AAA"].metadata["core_risk_off_experiment"]["shadow_rank"] == 2
    assert projected["BBB"].metadata["core_risk_off_experiment"]["shadow_rank"] == 3


def test_projection_leaves_non_candidates_unchanged() -> None:
    assessment = _make_assessment(symbol_score=0.30, entry_score=0.20, candidate=False)
    projected = project_core_risk_off_topk_exceptions({"AAA": assessment})

    assert projected["AAA"] == assessment
