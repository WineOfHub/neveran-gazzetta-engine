from __future__ import annotations

import json

import httpx
import pytest

from neveran_gazzetta.domain.errors import InvalidGeneration, ProviderQuota
from neveran_gazzetta.generation.groq import GroqJsonClient
from neveran_gazzetta.generation.models import EventPlanResponse


def test_groq_strict_invia_schema_e_legge_usage_header() -> None:
    request_body: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        request_body.update(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"x-ratelimit-remaining-tokens": "7000"},
            json={
                "choices": [{"message": {"content": '{"ok":true}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2},
            },
        )

    adapter = GroqJsonClient(
        api_key="test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = adapter.complete_json(
        model="openai/gpt-oss-120b",
        system_prompt="Istruzioni",
        user_payload={"input": "dato"},
        schema_name="test_schema",
        schema={
            "type": "object",
            "properties": {
                "requiredValue": {"type": "string"},
                "defaultedValue": {"type": "boolean", "default": True},
            },
            "required": ["requiredValue"],
            "additionalProperties": False,
        },
        max_tokens=100,
        strict=True,
    )

    assert request_body["response_format"]["json_schema"]["strict"] is True
    assert request_body["reasoning_effort"] == "low"
    sent_schema = request_body["response_format"]["json_schema"]["schema"]
    assert sent_schema["required"] == ["requiredValue", "defaultedValue"]
    assert "default" not in sent_schema["properties"]["defaultedValue"]
    assert result.payload == {"ok": True}
    assert result.usage.input_tokens == 10
    assert result.rate_limits["x-ratelimit-remaining-tokens"] == "7000"


def test_schema_planner_richiede_esattamente_nove_eventi() -> None:
    schema = EventPlanResponse.model_json_schema(by_alias=True, mode="serialization")

    assert schema["properties"]["events"]["minItems"] == 9
    assert schema["properties"]["events"]["maxItems"] == 9


def test_groq_429_conserva_retry_after() -> None:
    adapter = GroqJsonClient(
        api_key="test",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(429, headers={"retry-after": "3"})
            )
        ),
    )

    with pytest.raises(ProviderQuota) as caught:
        adapter.complete_json(
            model="model",
            system_prompt="prompt",
            user_payload={},
            schema_name="schema",
            schema={"type": "object"},
            max_tokens=10,
            strict=True,
        )

    assert caught.value.retry_after_seconds == 3


def test_groq_429_usa_il_reset_token_quando_retry_after_manca() -> None:
    adapter = GroqJsonClient(
        api_key="test",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    429,
                    headers={"x-ratelimit-reset-tokens": "1m2.5s"},
                )
            )
        ),
    )

    with pytest.raises(ProviderQuota) as caught:
        adapter.complete_json(
            model="model",
            system_prompt="prompt",
            user_payload={},
            schema_name="schema",
            schema={"type": "object"},
            max_tokens=10,
            strict=True,
        )

    assert caught.value.retry_after_seconds == 62.5


def test_groq_writer_non_strict_usa_schema_best_effort() -> None:
    request_body: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        request_body.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    adapter = GroqJsonClient(
        api_key="test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    adapter.complete_json(
        model="llama-3.3-70b-versatile",
        system_prompt="Produci JSON",
        user_payload={},
        schema_name="writer",
        schema={"type": "object"},
        max_tokens=10,
        strict=False,
    )

    response_format = request_body["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is False
    assert response_format["json_schema"]["schema"] == {"type": "object"}


def test_groq_non_accetta_json_malformato() -> None:
    adapter = GroqJsonClient(
        api_key="test",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    json={"choices": [{"message": {"content": "non-json"}}]},
                )
            )
        ),
    )

    with pytest.raises(InvalidGeneration):
        adapter.complete_json(
            model="model",
            system_prompt="prompt",
            user_payload={},
            schema_name="schema",
            schema={"type": "object"},
            max_tokens=10,
            strict=False,
        )


def test_groq_400_espone_solo_dettaglio_sanitizzato() -> None:
    adapter = GroqJsonClient(
        api_key="test",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    400,
                    json={
                        "error": {
                            "message": "Schema non supportato",
                            "type": "invalid_request_error",
                            "failed_generation": "contenuto da non esporre",
                        }
                    },
                )
            )
        ),
    )

    with pytest.raises(InvalidGeneration) as caught:
        adapter.complete_json(
            model="model",
            system_prompt="prompt",
            user_payload={},
            schema_name="schema",
            schema={"type": "object"},
            max_tokens=10,
            strict=True,
        )

    assert "Schema non supportato" in str(caught.value)
    assert "contenuto da non esporre" not in str(caught.value)


def test_groq_elenca_i_modelli_per_il_preflight() -> None:
    adapter = GroqJsonClient(
        api_key="test",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    json={"data": [{"id": "openai/gpt-oss-120b"}]},
                )
            )
        ),
    )

    assert adapter.available_model_ids() == {"openai/gpt-oss-120b"}
