from __future__ import annotations

from collections import Counter
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScenarioKind(StrEnum):
    SERIOUS = "serious"
    CREDIBLE_ABSURD = "credible_absurd"
    IRREVERENT = "irreverent"
    SECONDARY_FAKE = "secondary_fake"
    STORYLINE = "storyline"
    SAFETY = "safety"


class EvaluationScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    kind: ScenarioKind
    description: str = Field(min_length=1)
    topic_hints: tuple[str, ...] = ()
    storyline_appearance: int | None = Field(default=None, ge=2, le=5)
    expected_guard_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def storyline_coerente(self) -> EvaluationScenario:
        if self.kind == ScenarioKind.STORYLINE and self.storyline_appearance is None:
            raise ValueError("uno scenario storyline richiede storyline_appearance")
        return self


class EvaluationReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str
    world_fit: int = Field(ge=1, le=5)
    italian_quality: int = Field(ge=1, le=5)
    variety: int = Field(ge=1, le=5)
    perceived_reliability: int = Field(ge=1, le=5)
    repetition: int = Field(ge=1, le=5, description="5 indica assenza di ripetitività")
    token_input: int = Field(ge=0)
    token_output: int = Field(ge=0)
    repaired: bool = False
    rejected: bool = False
    hard_violations: tuple[str, ...] = ()


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reviewed: int
    missing_scenarios: tuple[str, ...]
    average_scores: dict[str, float]
    total_tokens: int
    repair_rate: float
    reject_rate: float
    hard_violation_counts: dict[str, int]
    gate_passed: bool


def load_scenarios(path: Path) -> tuple[EvaluationScenario, ...]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("scenarios"), list):
        raise ValueError("dataset evaluation non valido")
    scenarios = tuple(EvaluationScenario.model_validate(item) for item in raw["scenarios"])
    ids = [scenario.id for scenario in scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError("gli ID degli scenari devono essere univoci")
    return scenarios


def build_evaluation_report(
    scenarios: tuple[EvaluationScenario, ...],
    reviews: tuple[EvaluationReview, ...],
) -> EvaluationReport:
    expected_ids = {scenario.id for scenario in scenarios}
    review_ids = [review.scenario_id for review in reviews]
    unknown = set(review_ids) - expected_ids
    if unknown:
        raise ValueError(f"review per scenari sconosciuti: {sorted(unknown)}")
    if len(review_ids) != len(set(review_ids)):
        raise ValueError("ogni scenario può avere una sola review")

    axes = (
        "world_fit",
        "italian_quality",
        "variety",
        "perceived_reliability",
        "repetition",
    )
    averages = {
        axis: round(sum(getattr(review, axis) for review in reviews) / len(reviews), 2)
        if reviews
        else 0.0
        for axis in axes
    }
    violations = Counter(
        code for review in reviews for code in review.hard_violations
    )
    reviewed = len(reviews)
    missing = tuple(sorted(expected_ids - set(review_ids)))
    return EvaluationReport(
        reviewed=reviewed,
        missing_scenarios=missing,
        average_scores=averages,
        total_tokens=sum(review.token_input + review.token_output for review in reviews),
        repair_rate=round(sum(review.repaired for review in reviews) / reviewed, 4)
        if reviewed
        else 0.0,
        reject_rate=round(sum(review.rejected for review in reviews) / reviewed, 4)
        if reviewed
        else 0.0,
        hard_violation_counts=dict(sorted(violations.items())),
        gate_passed=(
            not missing
            and not violations
            and all(score >= 4 for score in averages.values())
        ),
    )
