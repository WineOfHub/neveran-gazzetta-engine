from __future__ import annotations

import random
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from neveran_gazzetta.domain.models import StorylineMemory
from neveran_gazzetta.generation.editorial_planner import EditionPlan


class QueryPurpose(StrEnum):
    PLACE = "place"
    DAILY_LIFE = "daily_life"
    INSTITUTION = "institution"
    COMMERCE = "commerce"
    STORYLINE = "storyline"


class EditorialQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    purpose: QueryPurpose
    text: str = Field(min_length=3, max_length=240)


_BASE_QUERIES = {
    QueryPurpose.PLACE: (
        "luoghi pubblici città e regioni di Neveran",
        "quartieri strade porti e mercati di Neveran",
        "territori abitati e collegamenti di Neveran",
    ),
    QueryPurpose.DAILY_LIFE: (
        "vita quotidiana abitudini e problemi comuni",
        "famiglie lavoro cibo e relazioni sociali",
        "feste locali servizi e inconvenienti quotidiani",
    ),
    QueryPurpose.INSTITUTION: (
        "istituzioni pubbliche mestieri e autorità locali",
        "professioni associazioni e servizi civici",
        "CCIN funzionari testimoni e attività pubbliche",
    ),
    QueryPurpose.COMMERCE: (
        "commercio merci materiali e trasporti",
        "botteghe mercati prodotti locali e prezzi",
        "artigianato risorse scambi e materiali di Neveran",
    ),
}


def build_editorial_queries(
    plan: EditionPlan,
    *,
    storylines: list[StorylineMemory],
    topic_hints: list[str] | None = None,
) -> tuple[EditorialQuery, ...]:
    rng = random.Random(int(plan.seed, 16))
    hints = [item.strip() for item in topic_hints or [] if item.strip()]
    rng.shuffle(hints)
    queries: list[EditorialQuery] = []
    for purpose in (
        QueryPurpose.PLACE,
        QueryPurpose.DAILY_LIFE,
        QueryPurpose.INSTITUTION,
        QueryPurpose.COMMERCE,
    ):
        base = rng.choice(_BASE_QUERIES[purpose])
        hint = hints.pop() if hints else ""
        queries.append(EditorialQuery(purpose=purpose, text=f"{base} {hint}".strip()))

    selected_storyline_ids = {
        slot.storyline_id for slot in plan.slots if slot.storyline_id is not None
    }
    selected = next((item for item in storylines if item.id in selected_storyline_ids), None)
    if selected is not None:
        queries.append(
            EditorialQuery(
                purpose=QueryPurpose.STORYLINE,
                text=f"{selected.location} {selected.title} {selected.open_hook or selected.recap}",
            )
        )
    elif hints:
        queries.append(EditorialQuery(purpose=QueryPurpose.PLACE, text=hints.pop()))
    return tuple(queries[:5])
