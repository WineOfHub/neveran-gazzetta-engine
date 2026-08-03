from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from neveran_gazzetta.config import load_config
from neveran_gazzetta.domain.models import GazzettaArticle, GazzettaEditionSnapshot
from neveran_gazzetta.generation.validators import validate_edition, word_count

ROOT = Path(__file__).resolve().parents[2]


def _words(count: int) -> str:
    return " ".join(f"parola{index}" for index in range(count))


def _article(importance: str, index: int) -> GazzettaArticle:
    paragraphs = {
        "lead": (_words(28), _words(28), _words(28)),
        "major": (_words(22), _words(22)),
        "minor": (_words(25),),
        "brief": (_words(25),),
    }[importance]
    return GazzettaArticle(
        id=f"{importance}-{index}",
        category="Cronaca",
        byline=f"Cronista CCIN {index % 4 + 1}",
        title=f"Titolo {index}",
        summary=_words(10),
        paragraphs=paragraphs,
        importance=importance,
        pull_quote=_words(8) if importance in {"lead", "major"} else None,
    )


def _edition() -> GazzettaEditionSnapshot:
    return GazzettaEditionSnapshot(
        id=uuid4(),
        slug="edizione-valida",
        issue_number=1,
        publication_date=datetime.now(UTC),
        masthead_subtitle="Cronache quotidiane da Neveran",
        location_label="CCIN",
        breaking_news=("Notizia uno", "Notizia due", "Notizia tre"),
        lead_article=_article("lead", 0),
        articles=(
            _article("major", 1),
            _article("major", 2),
            _article("minor", 3),
            _article("minor", 4),
            _article("brief", 5),
        ),
        editorial_quote=_words(10),
        closing_motto=_words(5),
    )


def test_validator_accetta_edizione_entro_budget() -> None:
    policy = load_config(ROOT, environment={"ENVIRONMENT": "test"}).editorial

    assert validate_edition(_edition(), policy).passed


def test_validator_segnala_budget_e_loop_ambiguo() -> None:
    policy = load_config(ROOT, environment={"ENVIRONMENT": "test"}).editorial
    edition = _edition().model_copy(
        update={
            "breaking_news": (
                "La città è entrata in un loop temporale che nessuno comprende",
                "Due",
                "Tre",
            ),
            "closing_motto": _words(12),
        }
    )

    report = validate_edition(edition, policy)
    codes = {issue.code for issue in report.issues}

    assert not report.passed
    assert "loop_ambiguous" in codes
    assert "motto_too_long" in codes


def test_validator_impedisce_una_sola_firma_su_tutta_la_prima_pagina() -> None:
    policy = load_config(ROOT, environment={"ENVIRONMENT": "test"}).editorial
    edition = _edition()
    repeated = tuple(
        article.model_copy(update={"byline": "Livia Cartis"})
        for article in edition.articles
    )
    edition = edition.model_copy(
        update={
            "lead_article": edition.lead_article.model_copy(
                update={"byline": "Livia Cartis"}
            ),
            "articles": repeated,
        }
    )

    report = validate_edition(edition, policy)

    assert "byline_rotation" in {issue.code for issue in report.issues}


def test_conteggio_parole_gestisce_apostrofi_italiani() -> None:
    assert word_count("L\u2019acqua dell'emporio è limpida") == 4
