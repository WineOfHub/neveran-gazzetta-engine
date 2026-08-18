from pathlib import Path

import pytest

from neveran_gazzetta.domain.errors import ConfigurationError
from neveran_gazzetta.generation.prompts import PromptRepository

ROOT = Path(__file__).resolve().parents[2]


def test_prompt_hanno_nome_versione_e_contenuto() -> None:
    repository = PromptRepository(ROOT / "prompts")

    expected_versions = {
        "event_planner.system.md": "gazzetta-event-planner-v6",
        "newspaper_writer.system.md": "gazzetta-newspaper-writer-v10",
        "repair.system.md": "gazzetta-repair-v5",
        "verifier.system.md": "gazzetta-verifier-v3",
    }
    for filename, expected_version in expected_versions.items():
        prompt = repository.load(filename)
        assert prompt.name.startswith("gazzetta-")
        assert prompt.version == expected_version
        assert prompt.content
        assert len(prompt.content_sha256) == 64


def test_prompt_repository_blocca_path_escape() -> None:
    with pytest.raises(ConfigurationError, match="non autorizzato"):
        PromptRepository(ROOT / "prompts").load("../README.md")


def test_prompt_live_rendono_espliciti_i_campi_json_obbligatori() -> None:
    repository = PromptRepository(ROOT / "prompts")
    planner = repository.load("event_planner.system.md").content
    writer = repository.load("newspaper_writer.system.md").content
    repair = repository.load("repair.system.md").content

    for field in (
        "slot",
        "headlineSeed",
        "eventSummary",
        "location",
        "entities",
        "diegeticSources",
        "loreChunkIds",
    ):
        assert f"`{field}`" in planner

    for field in (
        "mastheadSubtitle",
        "locationLabel",
        "breakingNews",
        "leadArticle",
        "majorArticles",
        "minorArticles",
        "briefArticle",
        "editorialQuote",
        "closingMotto",
    ):
        assert f"`{field}`" in writer
        assert f"`{field}`" in repair

    assert "esattamente due oggetti" in repair
    assert "esattamente tre stringhe" in repair
