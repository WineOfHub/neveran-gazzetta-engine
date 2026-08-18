from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from neveran_gazzetta.application.contracts import JobLease, PreparedRun, ValidationStatus
from neveran_gazzetta.domain.errors import GenerationQueueEmpty
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


def test_adapter_legge_la_profondita_coda() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/v1/token":
            return httpx.Response(200, json={"access_token": "jwt-test"})
        if request.url.path.endswith("/gazzetta_get_queue_status"):
            return httpx.Response(200, json={"queueDepth": 1, "queueDepthTarget": 4})
        raise AssertionError(request.url.path)

    adapter = SupabaseRpcClient(
        url="https://supabase.test",
        anon_key="anon-test",
        email="worker@test.invalid",
        password="password-test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    status = adapter.queue_status()

    assert status.depth == 1
    assert status.depth_target == 4


def test_adapter_traduce_queue_empty_in_errore_tipizzato() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/v1/token":
            return httpx.Response(200, json={"access_token": "jwt-test"})
        if request.url.path.endswith("/publish_next_gazzetta_edition"):
            return httpx.Response(400, json={"message": "queue_empty"})
        raise AssertionError(request.url.path)

    adapter = SupabaseRpcClient(
        url="https://supabase.test",
        anon_key="anon-test",
        email="worker@test.invalid",
        password="password-test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(GenerationQueueEmpty):
        adapter.publish_next("worker-test")


def test_submit_run_usa_un_timeout_piu_lungo_del_default() -> None:
    """submit_gazzetta_run porta uno snapshot completo — molto più grande delle
    altre RPC — e in produzione ha superato più volte il timeout di default da
    30s ereditato da chiamate piccole come heartbeat/lease. Verifica che passi
    esplicitamente un timeout più ampio invece di quello di default del client."""
    captured_timeouts: list[object] = []
    original_post = httpx.Client.post

    def spying_post(self: httpx.Client, url: str, **kwargs: object) -> httpx.Response:
        if "/rpc/submit_gazzetta_run" in url:
            captured_timeouts.append(kwargs.get("timeout"))
        return original_post(self, url, **kwargs)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/v1/token":
            return httpx.Response(200, json={"access_token": "jwt-test"})
        if request.url.path.endswith("/submit_gazzetta_run"):
            return httpx.Response(200, json=str(uuid4()))
        raise AssertionError(request.url.path)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.post = spying_post.__get__(client, httpx.Client)  # type: ignore[method-assign]

    adapter = SupabaseRpcClient(
        url="https://supabase.test",
        anon_key="anon-test",
        email="worker@test.invalid",
        password="password-test",
        client=client,
    )

    prompt_stages = {"planner": "v1", "writer": "v1", "verifier": "v1", "repair": "v1"}
    run = PreparedRun(
        phase="publishing",
        validation_status=ValidationStatus.PASSED,
        corpus_release_id="release-a",
        policy_hash="a" * 64,
        prompt_versions=prompt_stages,
        prompt_hashes={key: "a" * 64 for key in prompt_stages},
        models={"planner": "model", "writer": "model", "verifier": "model"},
        token_input=0,
        token_output=0,
        groq_requests=0,
        snapshot={"schemaVersion": 1},
        content_hash="a" * 64,
    )
    lease = JobLease(
        job_id=uuid4(), schedule_slot=datetime.now(UTC), attempt_number=1, policy_version="v1",
    )

    adapter.submit_run(lease, "worker-test", run)

    assert captured_timeouts == [90]
