"""Esporta JSON Schema deterministici dai modelli Pydantic autorevoli."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from neveran_gazzetta.domain.models import (  # noqa: E402
    GazzettaEditionSnapshot,
    GazzettaEvent,
    StorylineMemory,
)

TARGET = ROOT / "prompts" / "schemas"
MODELS = {
    "gazzetta-event.schema.json": GazzettaEvent,
    "gazzetta-edition-snapshot.schema.json": GazzettaEditionSnapshot,
    "storyline-memory.schema.json": StorylineMemory,
}


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for filename, model in MODELS.items():
        payload = model.model_json_schema(by_alias=True, mode="serialization")
        path = TARGET / filename
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
