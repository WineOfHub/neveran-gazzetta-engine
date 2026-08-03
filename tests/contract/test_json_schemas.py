from __future__ import annotations

import json
from pathlib import Path

from neveran_gazzetta.config import load_config
from neveran_gazzetta.domain.models import (
    GazzettaEditionSnapshot,
    GazzettaEvent,
    StorylineMemory,
)
from neveran_gazzetta.generation.validators import validate_edition

ROOT = Path(__file__).resolve().parents[2]


def test_schema_versionati_derivano_dai_modelli() -> None:
    models = {
        "gazzetta-event.schema.json": GazzettaEvent,
        "gazzetta-edition-snapshot.schema.json": GazzettaEditionSnapshot,
        "storyline-memory.schema.json": StorylineMemory,
    }
    for filename, model in models.items():
        actual = json.loads((ROOT / "prompts" / "schemas" / filename).read_text(encoding="utf-8"))
        expected = model.model_json_schema(by_alias=True, mode="serialization")
        assert actual == expected, filename


def test_fixture_player_condivisa_supera_schema_e_budget() -> None:
    fixture = (
        ROOT.parent
        / "neveran-main-app"
        / "frontend"
        / "src"
        / "features"
        / "gazzetta"
        / "content"
        / "editionContractFixture.json"
    )
    edition = GazzettaEditionSnapshot.model_validate(
        json.loads(fixture.read_text(encoding="utf-8"))
    )
    config = load_config(ROOT, environment={"ENVIRONMENT": "test"})
    assert validate_edition(edition, config.editorial).passed
