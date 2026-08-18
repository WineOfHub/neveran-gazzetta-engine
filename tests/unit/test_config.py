from __future__ import annotations

from pathlib import Path

import pytest

from neveran_gazzetta.config import load_config
from neveran_gazzetta.domain.errors import ConfigurationError

ROOT = Path(__file__).resolve().parents[2]


def test_config_valida_senza_segreti_in_sviluppo() -> None:
    config = load_config(ROOT, environment={"ENVIRONMENT": "test"})

    assert config.runtime.scheduler.timezone == "Europe/Rome"
    assert config.editorial.policy_version == "gazzetta-editorial-v1"
    assert len(config.policy_hash) == 64
    assert config.secrets.cloudflare_api_token is None


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
