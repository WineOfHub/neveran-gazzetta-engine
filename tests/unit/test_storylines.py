from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from neveran_gazzetta.domain.errors import InvalidGeneration
from neveran_gazzetta.domain.models import GazzettaEvent, StorylineMemory
from neveran_gazzetta.generation.editorial_planner import EditionPlan, PlannedSlot
from neveran_gazzetta.generation.pipeline import _event_payloads, _storyline_updates
from neveran_gazzetta.generation.storylines import (
    advance_storyline,
    compact_recap,
    storyline_fingerprint,
)


def _storyline(*, appearances: int, status: str = "active", last_issue: int = 1):
    return StorylineMemory(
        id=uuid4(),
        title="Una storia breve",
        status=status,
        recap="Recap.",
        involved_entities=(),
        location="Neveran",
        reporting_mode="reported_event",
        appearance_count=appearances,
        first_issue=1,
        last_issue=last_issue,
        fingerprint="b" * 64,
    )


def test_quarta_apparizione_chiude_il_filone() -> None:
    updated = advance_storyline(
        _storyline(appearances=3),
        recap="La vicenda trova una conclusione.",
        issue_number=4,
        next_eligible_at=None,
    )

    assert updated.appearance_count == 4
    assert updated.status == "closed"
    assert updated.final_summary


def test_un_solo_epilogo_terminale() -> None:
    closed = _storyline(appearances=4, status="closed", last_issue=4)

    epilogue = advance_storyline(
        closed,
        recap="Un ultimo dettaglio emerge.",
        issue_number=7,
        next_eligible_at=None,
        epilogue=True,
    )

    assert epilogue.status == "epilogue"
    assert epilogue.epilogue_used
    with pytest.raises(ValueError, match="epilogo"):
        advance_storyline(
            epilogue,
            recap="Ancora.",
            issue_number=8,
            next_eligible_at=None,
            epilogue=True,
        )


def test_stessa_issue_non_puo_ripetere_filone() -> None:
    with pytest.raises(ValueError, match="stessa edizione"):
        advance_storyline(
            _storyline(appearances=2, last_issue=3),
            recap="Duplicato.",
            issue_number=3,
            next_eligible_at=datetime.now(UTC),
        )


def test_recap_viene_compattato_a_180_parole() -> None:
    assert len(compact_recap("parola " * 250).split()) == 180


def test_un_evento_candidato_crea_memoria_e_collegamento_ledger() -> None:
    schedule = datetime(2026, 8, 1, 4, 0, tzinfo=UTC)
    plan = EditionPlan(
        seed="01" * 32,
        schedule_slot=schedule,
        corpus_release_id="release-a",
        policy_version="v1",
        slots=(
            PlannedSlot(
                slot="major-1",
                reporting_mode="reported_event",
                start_storyline=True,
            ),
        ),
    )
    event = GazzettaEvent(
        id=uuid4(),
        slot="major-1",
        headline_seed="Il ponte dei fornai resta aperto",
        event_summary="I fornai chiedono un controllo nei prossimi giorni.",
        location="Clovertia",
        occurred_at=schedule,
        canon_relation="compatible_ephemeral",
        reporting_mode="reported_event",
        storyline_candidate=True,
        diegetic_sources=(
            {"name": "Gilda dei fornai", "kind": "testimone", "reliability": 0.8},
        ),
        lore_chunk_ids=("chunk-1",),
    )

    updates = _storyline_updates(plan, (event,), (), issue_number=3)
    payload = _event_payloads((event,))[0]

    assert updates[0]["appearanceCount"] == 1
    assert updates[0]["status"] == "cooling"
    assert payload["storylineId"] == updates[0]["id"]
    assert payload["storylineAppearance"] == 1


def test_un_evento_candidato_non_duplica_un_filone_esistente() -> None:
    schedule = datetime(2026, 8, 1, 4, 0, tzinfo=UTC)
    title = "Il ponte dei fornai resta aperto"
    location = "Clovertia"
    existing = _storyline(appearances=1).model_copy(
        update={"fingerprint": storyline_fingerprint(title, location, [])}
    )
    plan = EditionPlan(
        seed="01" * 32,
        schedule_slot=schedule,
        corpus_release_id="release-a",
        policy_version="v1",
        slots=(PlannedSlot(
            slot="major-1", reporting_mode="reported_event", start_storyline=True,
        ),),
    )
    event = GazzettaEvent(
        id=uuid4(),
        slot="major-1",
        headline_seed=title,
        event_summary="Un controllo viene richiesto.",
        location=location,
        occurred_at=schedule,
        canon_relation="compatible_ephemeral",
        reporting_mode="reported_event",
        storyline_candidate=True,
        diegetic_sources=(
            {"name": "Gilda dei fornai", "kind": "testimone", "reliability": 0.8},
        ),
    )

    with pytest.raises(InvalidGeneration, match="duplica"):
        _storyline_updates(plan, (event,), (existing,), issue_number=3)


def test_due_candidati_nello_stesso_numero_non_creano_lo_stesso_filone() -> None:
    schedule = datetime(2026, 8, 1, 4, 0, tzinfo=UTC)
    plan = EditionPlan(
        seed="01" * 32,
        schedule_slot=schedule,
        corpus_release_id="release-a",
        policy_version="v1",
        slots=(
            PlannedSlot(
                slot="major-1", reporting_mode="reported_event", start_storyline=True,
            ),
            PlannedSlot(
                slot="minor-1", reporting_mode="reported_event", start_storyline=True,
            ),
        ),
    )
    common = {
        "headline_seed": "Il ponte dei fornai resta aperto",
        "event_summary": "Un controllo viene richiesto.",
        "location": "Clovertia",
        "occurred_at": schedule,
        "canon_relation": "compatible_ephemeral",
        "reporting_mode": "reported_event",
        "storyline_candidate": True,
        "diegetic_sources": (
            {"name": "Gilda dei fornai", "kind": "testimone", "reliability": 0.8},
        ),
    }
    events = (
        GazzettaEvent(id=uuid4(), slot="major-1", **common),
        GazzettaEvent(id=uuid4(), slot="minor-1", **common),
    )

    with pytest.raises(InvalidGeneration, match="duplica"):
        _storyline_updates(plan, events, (), issue_number=3)
