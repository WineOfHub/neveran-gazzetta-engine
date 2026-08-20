from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from neveran_gazzetta.generation.editorial_planner import EditionPlan


class EditionSettlement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    title: str
    settlement_tier: str


def sample_edition_settlements(
    plan: EditionPlan,
    *,
    knowledge_root: Path | None,
    count: int,
) -> tuple[EditionSettlement, ...]:
    """Insediamenti reali estratti per questa edizione, mai inventati (ADR-016 knowledge-engine).

    Nessun `knowledge_root` configurato: nessun insediamento reale disponibile
    per questa esecuzione, non un errore — i chiamanti degradano ammorbidendo
    il vincolo invece di bloccare l'edizione (utile in ambienti di test o
    finché il primo insediamento non è ancora stato approvato).
    """
    if knowledge_root is None:
        return ()
    from neveran_knowledge.application.settlements import sample_settlements_seeded

    seed = hashlib.sha256(f"{plan.seed}:settlements".encode("utf-8")).hexdigest()
    sampled = sample_settlements_seeded(knowledge_root, count=count, seed=seed)
    return tuple(
        EditionSettlement(
            document_id=item.document_id,
            title=item.title,
            settlement_tier=item.settlement_tier.value,
        )
        for item in sampled
    )
