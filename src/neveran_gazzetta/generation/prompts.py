from __future__ import annotations

import hashlib
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from neveran_gazzetta.domain.errors import ConfigurationError

_HEADER = re.compile(
    r"\A---\s*\nname:\s*(?P<name>[^\n]+)\nversion:\s*(?P<version>[^\n]+)\n---\s*\n",
    re.MULTILINE,
)


class PromptAsset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    content: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class PromptRepository:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def load(self, filename: str) -> PromptAsset:
        path = (self._root / filename).resolve()
        if self._root not in path.parents or path.suffix != ".md":
            raise ConfigurationError("Percorso prompt non autorizzato")
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigurationError(f"Prompt mancante: {filename}") from exc
        match = _HEADER.match(raw)
        if match is None:
            raise ConfigurationError(f"Header prompt non valido: {filename}")
        content = raw[match.end() :].strip()
        return PromptAsset(
            name=match.group("name").strip(),
            version=match.group("version").strip(),
            content=content,
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )
