from __future__ import annotations

from dataclasses import replace

from agent_trading.services.deterministic_trigger_engine import (
    DeterministicTriggerAssessment,
)


def project_core_risk_off_topk_exceptions(
    assessments_by_symbol: dict[str, DeterministicTriggerAssessment],
) -> dict[str, DeterministicTriggerAssessment]:
    """Annotate core risk-off shadow top-k metadata for one cycle.

    This helper is shadow-only. It does not change authoritative
    eligibility or BUY candidate flags.
    """

    projected: dict[str, DeterministicTriggerAssessment] = {}
    candidates: list[tuple[str, DeterministicTriggerAssessment, dict[str, object]]] = []

    for symbol, assessment in assessments_by_symbol.items():
        metadata = dict(assessment.metadata or {})
        experiment = dict(metadata.get("core_risk_off_experiment") or {})
        if bool(experiment.get("active")) and bool(experiment.get("shadow_topk_candidate")):
            candidates.append((symbol, assessment, experiment))

    candidates.sort(
        key=lambda item: (
            -(float(item[2].get("shadow_rank_candidate_score") or -999.0)),
            -(float(item[1].entry_score or -999.0)),
            str(item[0]),
        )
    )
    selected_symbols = {
        symbol
        for idx, (symbol, _, experiment) in enumerate(candidates, start=1)
        if idx <= int(experiment.get("shadow_top_k_cap") or 0)
    }
    group_size = len(candidates)

    for symbol, assessment in assessments_by_symbol.items():
        metadata = dict(assessment.metadata or {})
        experiment = dict(metadata.get("core_risk_off_experiment") or {})
        if symbol in selected_symbols or bool(experiment.get("shadow_topk_candidate")):
            rank = next(
                (idx for idx, (candidate_symbol, _, _) in enumerate(candidates, start=1) if candidate_symbol == symbol),
                None,
            )
            experiment["shadow_group_size"] = group_size
            experiment["shadow_rank"] = rank
            experiment["shadow_topk_selected"] = symbol in selected_symbols
            experiment["shadow_would_pass"] = symbol in selected_symbols
            metadata["core_risk_off_experiment"] = experiment
            projected[symbol] = replace(assessment, metadata=metadata)
            continue
        projected[symbol] = assessment

    return projected
