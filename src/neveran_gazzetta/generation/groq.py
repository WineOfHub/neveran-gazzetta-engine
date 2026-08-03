from __future__ import annotations

import json
from typing import Any

import httpx

from neveran_gazzetta.domain.errors import InvalidGeneration, ProviderQuota, ProviderUnavailable
from neveran_gazzetta.generation.models import GroqJsonResult, TokenUsage
from neveran_gazzetta.generation.rate_limits import parse_rate_limit_reset

_RATE_HEADERS = (
    "x-ratelimit-limit-requests",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-requests",
    "x-ratelimit-reset-tokens",
    "retry-after",
)


def _safe_error_detail(response: httpx.Response) -> str:
    """Estrae soltanto metadati di errore, mai prompt o generazioni fallite."""

    try:
        body = response.json()
    except (json.JSONDecodeError, TypeError, ValueError):
        return f"HTTP {response.status_code}"
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return f"HTTP {response.status_code}"
    parts = [
        str(error[key]).strip()
        for key in ("message", "type", "code")
        if error.get(key) not in (None, "")
    ]
    detail = " | ".join(parts)
    return detail[:500] if detail else f"HTTP {response.status_code}"


def _strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Adatta lo schema Pydantic al sottoinsieme strict accettato da Groq."""

    normalized: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "default":
            continue
        if isinstance(value, dict):
            normalized[key] = _strict_schema(value)
        elif isinstance(value, list):
            normalized[key] = [
                _strict_schema(item) if isinstance(item, dict) else item for item in value
            ]
        else:
            normalized[key] = value

    properties = normalized.get("properties")
    if normalized.get("type") == "object" and isinstance(properties, dict):
        normalized["required"] = list(properties)
        normalized["additionalProperties"] = False
    return normalized


class GroqJsonClient:
    def __init__(
        self,
        *,
        api_key: str,
        client: httpx.Client | None = None,
        base_url: str = "https://api.groq.com/openai/v1",
    ) -> None:
        if not api_key:
            raise ValueError("GROQ_API_KEY obbligatoria")
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=90)
        self._base_url = base_url.rstrip("/")

    def available_model_ids(self) -> frozenset[str]:
        try:
            response = self._client.get(
                f"{self._base_url}/models",
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            response.raise_for_status()
            data = response.json()["data"]
            if not isinstance(data, list):
                raise TypeError("data non lista")
            return frozenset(str(item["id"]) for item in data)
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise ProviderUnavailable("Elenco modelli Groq non disponibile") from exc

    def complete_json(
        self,
        *,
        model: str,
        system_prompt: str,
        user_payload: dict[str, object],
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int,
        strict: bool,
    ) -> GroqJsonResult:
        response_format: dict[str, object]
        if strict:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": _strict_schema(schema),
                },
            }
        else:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": False,
                    "schema": schema,
                },
            }
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False, separators=(",", ":")),
                },
            ],
            "temperature": 0.7,
            "reasoning_effort": "low",
            "max_completion_tokens": max_tokens,
            "response_format": response_format,
        }
        try:
            response = self._client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailable("Groq non raggiungibile") from exc
        if response.status_code == 429:
            seconds = parse_rate_limit_reset(
                response.headers.get("retry-after")
                or response.headers.get("x-ratelimit-reset-tokens")
                or response.headers.get("x-ratelimit-reset-requests")
            )
            raise ProviderQuota("Rate limit Groq", retry_after_seconds=seconds)
        if response.status_code in {401, 403}:
            raise ProviderUnavailable("Groq non autorizzato o modello non abilitato")
        if response.status_code >= 500:
            raise ProviderUnavailable(f"Groq ha risposto {response.status_code}")
        if 400 <= response.status_code < 500:
            raise InvalidGeneration(f"Richiesta Groq rifiutata: {_safe_error_detail(response)}")
        try:
            response.raise_for_status()
            raw = response.json()
            content = raw["choices"][0]["message"]["content"]
            payload = json.loads(content) if isinstance(content, str) else content
            usage = raw.get("usage") or {}
            if not isinstance(payload, dict):
                raise TypeError("payload JSON non oggetto")
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise InvalidGeneration("Output JSON Groq invalido") from exc
        rate_limits: dict[str, str | int | float | None] = {
            name: response.headers.get(name) for name in _RATE_HEADERS if name in response.headers
        }
        return GroqJsonResult(
            payload=payload,
            usage=TokenUsage(
                input_tokens=int(usage.get("prompt_tokens", 0)),
                output_tokens=int(usage.get("completion_tokens", 0)),
            ),
            rate_limits=rate_limits,
        )
