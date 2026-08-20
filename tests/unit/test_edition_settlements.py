from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from neveran_gazzetta.config import load_config
from neveran_gazzetta.generation.editorial_planner import plan_edition
from neveran_gazzetta.retrieval.settlements import sample_edition_settlements

ROOT = Path(__file__).resolve().parents[2]

_DOCUMENT_TEMPLATE = """---
schema_version: 3
id: location.{slug}
title: {title}
slug: {slug}
aliases: []
language: it
document_type: location
settlement_tier: terziaria
knowledge_layer: canon
status: approved
canon_state: canon
authority: authoritative
knowledge_level: public_knowledge
visibility: public
allowed_audiences:
- player
spoiler_level: none
required_discoveries: []
allowed_roles: []
allowed_factions: []
allowed_locations: []
truth_status: confirmed
version: 1.0.0
canonical_owner: neveran-core
summary: Villaggio di test.
domains:
- citta
scopes:
- type: global
  value: neveran
locations: []
factions: []
professions: []
characters: []
time_periods: []
audiences:
- authoring
tags:
- test
dependencies: []
related_documents: []
supersedes: []
superseded_by: []
retrieval:
  enabled: true
  priority: normal
  evergreen: true
  allowed_for_generation: true
  allowed_for_factual_answers: true
  include_sections: []
  exclude_sections: []
  preferred_profiles: []
provenance:
  origin: authored
  source_id: null
  source_relative_path: null
  source_hash: null
  imported_at: null
review:
  reviewed_by:
  - test
  approved_at: '2026-08-20T00:00:00+02:00'
  notes: null
deprecated_aliases: []
---
# {title}

## Identità del luogo

Contenuto di test.
"""


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


def test_nessun_knowledge_root_restituisce_lista_vuota() -> None:
    settlements = sample_edition_settlements(_plan(), knowledge_root=None, count=3)

    assert settlements == ()


def test_estrae_insediamenti_reali_dal_knowledge_root(tmp_path: Path) -> None:
    for slug, title in (("uno", "Villaggio Uno"), ("due", "Villaggio Due")):
        (tmp_path / f"{slug}.md").write_text(
            _DOCUMENT_TEMPLATE.format(slug=slug, title=title), encoding="utf-8"
        )

    settlements = sample_edition_settlements(_plan(), knowledge_root=tmp_path, count=2)

    assert {item.title for item in settlements} == {"Villaggio Uno", "Villaggio Due"}
    assert all(item.settlement_tier == "terziaria" for item in settlements)


def test_estrazione_e_deterministica_a_parita_di_piano(tmp_path: Path) -> None:
    for slug, title in (("uno", "Villaggio Uno"), ("due", "Villaggio Due")):
        (tmp_path / f"{slug}.md").write_text(
            _DOCUMENT_TEMPLATE.format(slug=slug, title=title), encoding="utf-8"
        )
    plan = _plan()

    first = sample_edition_settlements(plan, knowledge_root=tmp_path, count=1)
    second = sample_edition_settlements(plan, knowledge_root=tmp_path, count=1)

    assert first == second
