from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from scripts.render_canary_preview import (
    render_preview,
    restyle_snapshot_with_current_name_policy,
)

from neveran_gazzetta.domain.models import GazzettaArticle, GazzettaEditionSnapshot


def _article(importance: str, index: int) -> GazzettaArticle:
    return GazzettaArticle(
        id=f"{importance}-{index}",
        category="Cronaca",
        byline="Livia Cartis",
        title=f"Titolo <{index}>",
        summary="Sommario valido.",
        paragraphs=("Paragrafo valido.",),
        importance=importance,
    )


def test_preview_mostra_solo_la_prima_pagina_ed_escapa_html() -> None:
    snapshot = GazzettaEditionSnapshot(
        id=uuid4(),
        slug="edizione-di-prova",
        issue_number=12,
        publication_date=datetime(2026, 8, 1, 6, tzinfo=UTC),
        masthead_subtitle="Cronache dal mondo",
        location_label="Neveran",
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

    html = render_preview(
        {
            "snapshot": snapshot.model_dump(mode="json", by_alias=True),
            "events": [{"secret": "non visibile"}],
        }
    )

    assert "Anteprima locale" in html
    assert "Edizione 12" in html
    assert "Titolo &lt;0&gt;" in html
    assert "non visibile" not in html


def test_restyle_applica_nomi_neveran_solo_a_identita_inventate() -> None:
    snapshot = GazzettaEditionSnapshot(
        id=uuid4(),
        slug="edizione-di-prova",
        issue_number=1,
        publication_date=datetime(2026, 8, 1, 6, tzinfo=UTC),
        masthead_subtitle="Cronache dal mondo",
        location_label="Neveran",
        breaking_news=("Pietro Lume ha parlato con Arin Vost", "Due", "Tre"),
        lead_article=_article("lead", 0).model_copy(
            update={"summary": "Pietro Lume incontra Arin Vost."}
        ),
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
    payload = {
        "snapshot": snapshot.model_dump(mode="json", by_alias=True),
        "events": [
            {
                "id": "evento-1",
                "entities": [
                    {"name": "Pietro Lume, mercante", "invented": True},
                    {"name": "Arin Vost", "invented": False},
                ],
            }
        ],
    }

    restyled = restyle_snapshot_with_current_name_policy(
        payload,
        newsroom_names=(
            "Vaeris Cartis",
            "Oryn Neral",
            "Maev Velis",
            "Tivar Revas",
            "Neris Vhal",
            "Kelra Morn",
        ),
        per_edition=3,
    )
    serialized = restyled.model_dump_json(by_alias=True)

    assert "Pietro Lume" not in serialized
    assert "Arin Vost" in serialized
    assert {restyled.lead_article.byline, *(a.byline for a in restyled.articles)} == {
        "Vaeris Cartis",
        "Oryn Neral",
        "Maev Velis",
    }
