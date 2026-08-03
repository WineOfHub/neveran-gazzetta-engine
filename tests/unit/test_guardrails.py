from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from neveran_gazzetta.domain.models import DiegeticSource, GazzettaEvent
from neveran_gazzetta.generation.editorial_planner import SLOTS
from neveran_gazzetta.generation.guardrails import (
    normalize_loop_usage,
    validate_event_set,
    validate_loop_usage,
)
from neveran_gazzetta.generation.validators import truncate_to_word_limit, word_count


def _event(slot: str, *, summary: str = "Una notizia locale.", risk_flags=()):
    return GazzettaEvent(
        id=uuid4(),
        slot=slot,
        headline_seed="Titolo locale",
        event_summary=summary,
        location="Clovertia",
        occurred_at=datetime.now(UTC),
        canon_relation="compatible_ephemeral",
        reporting_mode="reported_event",
        diegetic_sources=(
            {"name": "Registro locale", "kind": "documento", "reliability": 0.8},
        ),
        lore_chunk_ids=("lore.test#1",),
        risk_flags=risk_flags,
    )


def test_loop_richiede_contesto_materiale() -> None:
    assert validate_loop_usage("Un frammento del raro materiale Loop è stato venduto.") is None
    assert validate_loop_usage("La città è bloccata in un loop temporale.").code == "loop_ambiguous"


def test_normalizzazione_loop_preserva_materiale_e_corregge_ricorrenza() -> None:
    assert normalize_loop_usage("Un Loop di consegne si ripete.") == (
        "Un Ciclo di consegne si ripete."
    )
    assert normalize_loop_usage("Un frammento di Loop prezioso è stato venduto.") == (
        "Un frammento di Loop prezioso è stato venduto."
    )


def test_troncamento_parole_usa_lo_stesso_contatore_del_validator() -> None:
    text = "L'oste racconta una storia molto lunga, precisa e sorprendente al mercato"

    truncated = truncate_to_word_limit(text, 6)

    assert word_count(truncated) == 6
    assert truncated.endswith(".")


def test_set_valido_non_produce_issue() -> None:
    assert validate_event_set([_event(slot) for slot in SLOTS]) == ()


def test_invenzione_profonda_e_assenza_grounding_sono_bloccanti() -> None:
    events = [_event(slot) for slot in SLOTS]
    events[0] = _event(
        "breaking-1",
        summary="Una nuova divinità è apparsa.",
        risk_flags=("invented_deity",),
    ).model_copy(update={"lore_chunk_ids": ()})

    codes = {issue.code for issue in validate_event_set(events)}

    assert "forbidden_deep_invention" in codes
    assert "ungrounded_event" in codes


def test_slot_principale_richiede_una_fonte_forte() -> None:
    events = [_event(slot) for slot in SLOTS]
    events[3] = events[3].model_copy(
        update={
            "diegetic_sources": (
                DiegeticSource(name="Voce lontana", kind="voce", reliability=0.4),
            )
        }
    )

    codes = {issue.code for issue in validate_event_set(events)}

    assert "weak_sources" in codes
    assert "weak_primary_sources" in codes
