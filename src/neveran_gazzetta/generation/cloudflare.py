from __future__ import annotations

import json
from typing import Any

import httpx

from neveran_gazzetta.domain.errors import InvalidGeneration, ProviderQuota, ProviderUnavailable
from neveran_gazzetta.generation.models import GroqJsonResult, TokenUsage
from neveran_gazzetta.generation.rate_limits import parse_rate_limit_reset
from neveran_gazzetta.generation.schema_utils import strict_json_schema

_RATE_HEADERS = (
    "retry-after",
)


def _safe_error_detail(response: httpx.Response) -> str:
    """Estrae soltanto metadati di errore, mai prompt o generazioni fallite."""

    try:
        body = response.json()
    except (json.JSONDecodeError, TypeError, ValueError):
        return f"HTTP {response.status_code}"
    errors = body.get("errors") if isinstance(body, dict) else None
    if not isinstance(errors, list) or not errors:
        return f"HTTP {response.status_code}"
    parts = [
        str(item.get("message", "")).strip()
        for item in errors
        if isinstance(item, dict) and item.get("message")
    ]
    detail = " | ".join(parts)
    return detail[:500] if detail else f"HTTP {response.status_code}"


class CloudflareJsonClient:
    def __init__(
        self,
        *,
        account_id: str,
        api_token: str,
        client: httpx.Client | None = None,
        base_url: str = "https://api.cloudflare.com/client/v4",
    ) -> None:
        if not account_id:
            raise ValueError("CLOUDFLARE_ACCOUNT_ID obbligatorio")
        if not api_token:
            raise ValueError("CLOUDFLARE_API_TOKEN obbligatorio")
        self._api_token = api_token
        self._client = client or httpx.Client(timeout=120)
        self._base_url = f"{base_url.rstrip('/')}/accounts/{account_id}/ai"

    def available_model_ids(self) -> frozenset[str]:
        try:
            response = self._client.get(
                f"{self._base_url}/models/search",
                headers={"Authorization": f"Bearer {self._api_token}"},
                params={"per_page": 100},
            )
            response.raise_for_status()
            body = response.json()
            if not body.get("success"):
                raise ValueError("success=false")
            data = body["result"]
            if not isinstance(data, list):
                raise TypeError("result non lista")
            return frozenset(str(item["name"]) for item in data)
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise ProviderUnavailable("Elenco modelli Cloudflare non disponibile") from exc

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
        response_format: dict[str, object] = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": strict,
                "schema": strict_json_schema(schema) if strict else schema,
            },
        }
        body: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False, separators=(",", ":")),
                },
            ],
            "temperature": 0.7,
            "max_tokens": max_tokens,
            "response_format": response_format,
        }
        if "gpt-oss" in model:
            body["reasoning_effort"] = "low"
        try:
            response = self._client.post(
                f"{self._base_url}/run/{model}",
                headers={
                    "Authorization": f"Bearer {self._api_token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailable("Cloudflare Workers AI non raggiungibile") from exc
        if response.status_code == 429:
            seconds = parse_rate_limit_reset(response.headers.get("retry-after"))
            raise ProviderQuota(
                f"Rate limit Cloudflare schema={schema_name} model={model} "
                f"retry_after={seconds} {_safe_error_detail(response)}",
                retry_after_seconds=seconds,
            )
        if response.status_code in {401, 403}:
            raise ProviderUnavailable("Cloudflare non autorizzato o modello non abilitato")
        if response.status_code >= 500:
            raise ProviderUnavailable(f"Cloudflare ha risposto {response.status_code}")
        if 400 <= response.status_code < 500:
            raise InvalidGeneration(
                f"Richiesta Cloudflare rifiutata: {_safe_error_detail(response)}"
            )
        try:
            response.raise_for_status()
            raw = response.json()
            if not raw.get("success"):
                raise InvalidGeneration(
                    f"Cloudflare ha rifiutato la generazione: {_safe_error_detail(response)}"
                )
            result = raw["result"]
            content = result["choices"][0]["message"]["content"]
            payload = json.loads(content) if isinstance(content, str) else content
            usage = result.get("usage") or {}
            if not isinstance(payload, dict):
                raise TypeError("payload JSON non oggetto")
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            snippet = response.text[:300] if response is not None else "n/d"
            raise InvalidGeneration(
                f"Output JSON Cloudflare invalido ({type(exc).__name__}: {exc}) raw={snippet!r}"
            ) from exc
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
