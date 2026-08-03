from __future__ import annotations

import json

import httpx

from neveran_gazzetta.storage.supabase import SupabaseRpcClient


def test_adapter_supabase_usa_solo_auth_e_rpc() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/auth/v1/token":
            return httpx.Response(200, json={"access_token": "jwt-test"})
        if request.url.path.endswith("/lease_next_gazzetta_job"):
            return httpx.Response(200, json=[])
        raise AssertionError(request.url.path)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = SupabaseRpcClient(
        url="https://supabase.test",
        anon_key="anon-test",
        email="worker@test.invalid",
        password="password-test",
        client=client,
    )

    assert adapter.lease_next("worker-test") is None
    assert paths == ["/auth/v1/token", "/rest/v1/rpc/lease_next_gazzetta_job"]
    assert all("/rest/v1/" not in path or "/rpc/" in path for path in paths)


def test_adapter_non_invia_password_alle_rpc() -> None:
    rpc_body: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/v1/token":
            return httpx.Response(200, json={"access_token": "jwt-test"})
        rpc_body.update(json.loads(request.content))
        return httpx.Response(200, json=[])

    adapter = SupabaseRpcClient(
        url="https://supabase.test",
        anon_key="anon-test",
        email="worker@test.invalid",
        password="password-test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    adapter.lease_next("worker-test")

    assert "password" not in json.dumps(rpc_body).lower()


def test_adapter_accetta_contesto_editoriale_camel_case() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/v1/token":
            return httpx.Response(200, json={"access_token": "jwt-test"})
        if request.url.path.endswith("/gazzetta_get_editorial_context"):
            return httpx.Response(
                200,
                json={
                    "nextIssueNumber": 1,
                    "storylines": [],
                    "recurringEntities": [],
                    "topicHints": [],
                },
            )
        raise AssertionError(request.url.path)

    adapter = SupabaseRpcClient(
        url="https://supabase.test",
        anon_key="anon-test",
        email="worker@test.invalid",
        password="password-test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    state = adapter.get_editorial_state()

    assert state.next_issue_number == 1
    assert state.storylines == ()
    assert state.recurring_entities == ()
    assert state.topic_hints == ()
