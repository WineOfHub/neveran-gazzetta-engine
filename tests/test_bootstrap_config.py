from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(relative_path: str) -> dict[str, Any]:
    with (ROOT / relative_path).open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    assert isinstance(data, dict)
    return data


def test_configurazioni_base_sono_yaml_validi() -> None:
    default = _load_yaml("config/default.yaml")
    policy = _load_yaml("config/editorial_policy.yaml")
    logging = _load_yaml("config/logging.yaml")

    assert default["schema_version"] == 1
    assert policy["schema_version"] == 1
    assert logging["version"] == 1


def test_pesi_editoriali_sommano_a_uno() -> None:
    policy = _load_yaml("config/editorial_policy.yaml")

    for slot, weights in policy["reporting_mode_weights"].items():
        assert abs(sum(weights.values()) - 1.0) < 1e-9, slot


def test_fake_deliberata_resta_secondaria() -> None:
    policy = _load_yaml("config/editorial_policy.yaml")

    assert policy["truth_rules"]["fake_allowed_slots"] == ["minor", "brief"]
    assert policy["edition"]["max_intentional_fake_per_edition"] == 1


def test_storyline_quattro_piu_un_epilogo() -> None:
    policy = _load_yaml("config/editorial_policy.yaml")
    storylines = policy["storylines"]

    assert storylines["max_appearances_including_first"] == 4
    assert storylines["max_epilogues"] == 1
    assert storylines["max_appearances_per_edition"] == 1


def test_specifica_canonica_non_e_locale() -> None:
    spec = ROOT / "docs/software-design-specification.md"

    assert spec.is_file()
    assert not spec.name.endswith(".local.md")
