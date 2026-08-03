from pathlib import Path

from neveran_gazzetta.evaluation import (
    EvaluationReview,
    build_evaluation_report,
    load_scenarios,
)
from neveran_gazzetta.evaluation.models import ScenarioKind

ROOT = Path(__file__).resolve().parents[2]


def test_dataset_copre_toni_storyline_e_sicurezza() -> None:
    scenarios = load_scenarios(ROOT / "eval" / "scenarios.yaml")
    kinds = {scenario.kind for scenario in scenarios}
    assert kinds == set(ScenarioKind)
    assert {item.storyline_appearance for item in scenarios if item.kind == "storyline"} == {
        2,
        3,
        4,
        5,
    }
    guard_codes = {code for item in scenarios for code in item.expected_guard_codes}
    assert {"no_evidence", "forbidden_deep_invention", "loop_ambiguous"} <= guard_codes


def test_report_non_supera_il_gate_con_review_mancanti() -> None:
    scenarios = load_scenarios(ROOT / "eval" / "scenarios.yaml")
    review = EvaluationReview(
        scenario_id=scenarios[0].id,
        world_fit=5,
        italian_quality=5,
        variety=5,
        perceived_reliability=5,
        repetition=5,
        token_input=100,
        token_output=50,
    )
    report = build_evaluation_report(scenarios, (review,))
    assert not report.gate_passed
    assert report.total_tokens == 150
    assert len(report.missing_scenarios) == len(scenarios) - 1
