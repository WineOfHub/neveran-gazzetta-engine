from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from neveran_gazzetta.config import load_config
from neveran_gazzetta.generation.editorial_planner import plan_edition
from neveran_gazzetta.retrieval.queries import QueryPurpose, build_editorial_queries

ROOT = Path(__file__).resolve().parents[2]


def _plan():
    config = load_config(ROOT, environment={"ENVIRONMENT": "test"})
    return plan_edition(
        schedule_slot=datetime(2026, 8, 1, 4, 0, tzinfo=UTC),
        issue_number=1,
        corpus_release_id="release-a",
        policy_hash=config.policy_hash,
        policy=config.editorial,
        storylines=[],
    )


def test_query_editoriali_restano_separate_per_scopo() -> None:
    queries = build_editorial_queries(
        _plan(),
        storylines=[],
        topic_hints=["Clovertia", "commercio fluviale", "artigiani"],
    )

    purposes = {query.purpose for query in queries}
    assert 4 <= len(queries) <= 5
    assert QueryPurpose.PLACE in purposes
    assert QueryPurpose.DAILY_LIFE in purposes
    assert QueryPurpose.INSTITUTION in purposes
    assert QueryPurpose.COMMERCE in purposes
    assert all(len(query.text) <= 240 for query in queries)


def test_query_place_include_gli_insediamenti_estratti_per_l_edizione() -> None:
    queries = build_editorial_queries(
        _plan(), storylines=[], settlement_names=("Romolia", "Lughat")
    )

    place_query = next(query for query in queries if query.purpose == QueryPurpose.PLACE)
    assert "Romolia" in place_query.text
    assert "Lughat" in place_query.text


def test_query_plan_e_riproducibile() -> None:
    first = build_editorial_queries(_plan(), storylines=[], topic_hints=["A", "B", "C"])
    second = build_editorial_queries(_plan(), storylines=[], topic_hints=["A", "B", "C"])

    assert first == second
