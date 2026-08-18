from __future__ import annotations

from typing import Any


def strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Adatta uno schema Pydantic al sottoinsieme strict richiesto dai modelli
    della famiglia GPT (Cloudflare Workers AI e Codex CLI condividono questa
    stessa esigenza: ogni proprietà elencata in `required`, niente
    `additionalProperties`)."""

    normalized: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "default":
            continue
        if isinstance(value, dict):
            normalized[key] = strict_json_schema(value)
        elif isinstance(value, list):
            normalized[key] = [
                strict_json_schema(item) if isinstance(item, dict) else item for item in value
            ]
        else:
            normalized[key] = value

    properties = normalized.get("properties")
    if normalized.get("type") == "object" and isinstance(properties, dict):
        normalized["required"] = list(properties)
        normalized["additionalProperties"] = False
    return normalized
