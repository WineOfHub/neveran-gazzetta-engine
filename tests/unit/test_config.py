from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from neveran_gazzetta.config import GenerationConfig, load_config
from neveran_gazzetta.domain.errors import ConfigurationError

ROOT = Path(__file__).resolve().parents[2]

_BASE_GENERATION_FIELDS = {
    "api_key_env": "CLOUDFLARE_API_TOKEN",
    "planner_model_env": "GAZZETTA_PLANNER_MODEL",
    "planner_model_default": "modello",
    "writer_model_env": "GAZZETTA_WRITER_MODEL",
    "writer_model_default": "modello",
    "verifier_model_env": "GAZZETTA_VERIFIER_MODEL",
    "verifier_model_default": "modello",
    "structured_planner_strict": True,
    "structured_writer_strict": True,
    "structured_verifier_strict": True,
    "max_normal_calls": 3,
    "max_repair_calls": 1,
    "max_total_tokens_per_edition": 35000,
    "max_storyline_context_tokens": 500,
    "max_edition_output_tokens": 6500,
    "max_repair_output_tokens": 5000,
    "max_rate_limit_wait_seconds": 180,
    "rate_limit_strategy": "response_headers",
    "retry_on_invalid_content": False,
}

_CODEX_FIELDS = {
    "codex_executable": "codex",
    "codex_sandbox": "read-only",
    "codex_timeout_seconds": 600,
    "codex_auth_recheck_seconds": 300,
    "codex_quota_cooldown_seconds": 1800,
    "codex_reasoning_effort": "medium",
}


def test_config_valida_senza_segreti_in_sviluppo() -> None:
    config = load_config(ROOT, environment={"ENVIRONMENT": "test"})

    assert config.runtime.scheduler.timezone == "Europe/Rome"
    assert config.editorial.policy_version == "gazzetta-editorial-v1"
    assert len(config.policy_hash) == 64
    assert config.secrets.cloudflare_api_token is None


def test_generation_config_codex_cli_richiede_i_campi_codex() -> None:
    with pytest.raises(ValidationError, match="richiede tutti i campi codex_"):
        GenerationConfig(provider="codex_cli", **_BASE_GENERATION_FIELDS)


def test_generation_config_cloudflare_rifiuta_i_campi_codex() -> None:
    with pytest.raises(ValidationError, match="si usano solo con provider codex_cli"):
        GenerationConfig(
            provider="cloudflare_workers_ai", **_BASE_GENERATION_FIELDS, **_CODEX_FIELDS
        )


def test_generation_config_codex_cli_valido_con_tutti_i_campi() -> None:
    config = GenerationConfig(
        provider="codex_cli", **_BASE_GENERATION_FIELDS, **_CODEX_FIELDS
    )
    assert config.codex_executable == "codex"
    assert config.codex_reasoning_effort == "medium"


def test_config_live_fallisce_se_mancano_segreti() -> None:
    with pytest.raises(ConfigurationError, match="Segreti runtime mancanti"):
        load_config(ROOT, environment={"ENVIRONMENT": "production"})


def test_config_rifiuta_campi_inattesi(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    default = (ROOT / "config" / "default.yaml").read_text(encoding="utf-8")
    policy = (ROOT / "config" / "editorial_policy.yaml").read_text(encoding="utf-8")
    (config_dir / "default.yaml").write_text(
        default + "\ncampo_imprevisto: true\n",
        encoding="utf-8",
    )
    (config_dir / "editorial_policy.yaml").write_text(policy, encoding="utf-8")

    with pytest.raises(ConfigurationError, match="Configurazione YAML non valida"):
        load_config(tmp_path, environment={"ENVIRONMENT": "test"})
