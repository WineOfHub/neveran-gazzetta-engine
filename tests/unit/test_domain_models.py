from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from neveran_gazzetta.domain.models import (
    GazzettaArticle,
    GazzettaEditionSnapshot,
    GazzettaEvent,
)


def _article(importance: str, index: int) -> GazzettaArticle:
    return GazzettaArticle(
        id=f"{importance}-{index}",
        category="Cronaca",
        byline="Livia Cartis",
        title=f"Titolo {index}",
        summary="Sommario valido.",
        paragraphs=("Paragrafo valido.",),
        importance=importance,
    )


def test_snapshot_usa_alias_camel_case_e_slot_esatti() -> None:
    snapshot = GazzettaEditionSnapshot(
        id=uuid4(),
        slug="edizione-di-prova",
        issue_number=1,
        publication_date=datetime.now(UTC),
        masthead_subtitle="Cronache dal mondo",
        location_label="CCIN",
        breaking_news=("Uno", "Due", "Tre"),
        lead_article=_article("lead", 0),
        articles=(
            _article("major", 1),
            _article("major", 2),
            _article("minor", 3),
            _article("minor", 4),
            _article("brief", 5),
        ),
        editorial_quote="Citazione.",
        closing_motto="Motto.",
    )

    payload = snapshot.model_dump(mode="json", by_alias=True)
    assert payload["schemaVersion"] == 1
    assert payload["issueNumber"] == 1
    assert len(payload["breakingNews"]) == 3


def test_snapshot_rifiuta_un_numero_errato_di_major() -> None:
    with pytest.raises(ValidationError, match="2 major"):
        GazzettaEditionSnapshot(
            id=uuid4(),
            slug="edizione-errata",
            issue_number=1,
            publication_date=datetime.now(UTC),
            masthead_subtitle="Cronache",
            location_label="CCIN",
            breaking_news=("Uno", "Due", "Tre"),
            lead_article=_article("lead", 0),
            articles=(_article("major", 1),),
            editorial_quote="Citazione.",
            closing_motto="Motto.",
        )


def test_fake_deliberata_solo_secondaria_e_classificata() -> None:
    common = {
        "id": uuid4(),
        "headline_seed": "Titolo",
        "event_summary": "Evento",
        "location": "Mercato",
        "occurred_at": datetime.now(UTC),
        "reporting_mode": "intentional_fake",
        "canon_relation": "deliberately_false_claim",
        "diegetic_sources": (
            {"name": "Un testimone anonimo", "kind": "persona", "reliability": 0.2},
        ),
    }
    assert GazzettaEvent(slot="minor-1", **common).slot == "minor-1"

    with pytest.raises(ValidationError, match="minor o brief"):
        GazzettaEvent(slot="lead", **common)


def test_contratti_autorevoli_rifiutano_extra() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        GazzettaArticle(
            id="x",
            category="Cronaca",
            byline="Livia Cartis",
            title="Titolo",
            summary="Sommario",
            paragraphs=("Testo",),
            importance="brief",
            metadata_segreti=True,
        )
