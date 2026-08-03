from __future__ import annotations

import base64
import hashlib
import json
from uuid import UUID

import httpx
import pytest

from neveran_gazzetta.artwork.cloudflare import CloudflareArtworkClient
from neveran_gazzetta.artwork.models import ArtworkBrief, WorkerGeneratedImage
from neveran_gazzetta.artwork.service import SupabaseBackedArtworkService
from neveran_gazzetta.artwork.supabase import SupabaseArtworkStore
from neveran_gazzetta.domain.errors import ArtworkGenerationFailed

JOB_ID = UUID("7808e01e-61bc-4899-88bd-e26ad6d29e54")
TOKEN = "1234567890abcdef1234567890abcdef"
MODEL = "@cf/black-forest-labs/flux-2-klein-9b"
PNG = b"\x89PNG\r\n\x1a\n" + b"neveran-artwork-di-test"
PNG_SHA256 = hashlib.sha256(PNG).hexdigest()


def _brief() -> ArtworkBrief:
    prompt = (
        "Create a documentary editorial illustration set in Neveran with a guarded market, "
        "restrained cyan magitech lighting, a wide landscape composition and absolutely no text."
    )
    return ArtworkBrief(
        job_id=JOB_ID,
        issue_number=7,
        prompt=prompt,
        prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
        seed=42,
        alt="Illustrazione editoriale del mercato sorvegliato.",
        caption="Clovertia · Il mercato riapre sotto sorveglianza.",
        credit="Archivio ottico CCIN · sintesi illustrata",
        focal_point="50% 42%",
    )


def _worker_payload(*, content_sha256: str = PNG_SHA256) -> dict[str, object]:
    return {
        "imageBase64": base64.b64encode(PNG).decode("ascii"),
        "contentSha256": content_sha256,
        "mimeType": "image/png",
        "model": MODEL,
        "seed": 42,
        "width": 1536,
        "height": 896,
    }


def _cloudflare_client(handler: httpx.MockTransport) -> CloudflareArtworkClient:
    return CloudflareArtworkClient(
        base_url="https://neveran-gazzetta-image.workers.dev",
        token=TOKEN,
        expected_model=MODEL,
        expected_width=1536,
        expected_height=896,
        timeout_seconds=120,
        client=httpx.Client(transport=handler),
    )


def _store(handler: httpx.MockTransport, *, max_stored_images: int = 120) -> SupabaseArtworkStore:
    return SupabaseArtworkStore(
        url="https://neveran-test.supabase.co",
        anon_key="sb_publishable_test",
        token_provider=lambda refresh: f"worker-jwt-{'refresh' if refresh else 'cached'}",
        bucket="gazzetta-artwork",
        max_stored_images=max_stored_images,
        expected_model=MODEL,
        expected_width=1536,
        expected_height=896,
        client=httpx.Client(transport=handler),
    )


def test_adapter_invia_solo_il_contratto_privato() -> None:
    observed: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        observed.update(json.loads(request.content))
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        return httpx.Response(200, json=_worker_payload())

    artwork = _cloudflare_client(httpx.MockTransport(handle)).generate(_brief())

    assert set(observed) == {"jobId", "issueNumber", "prompt", "promptSha256", "seed"}
    assert artwork.decoded_bytes() == PNG


def test_adapter_riprova_una_volta_su_errore_temporaneo() -> None:
    attempts = 0

    def handle(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(502 if attempts == 1 else 200, json=_worker_payload())

    assert _cloudflare_client(httpx.MockTransport(handle)).generate(_brief()).width == 1536
    assert attempts == 2


def test_adapter_rifiuta_hash_binario_non_coerente() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json=_worker_payload(content_sha256="a" * 64))
    )

    with pytest.raises(ArtworkGenerationFailed, match="contratto"):
        _cloudflare_client(transport).generate(_brief())


def test_store_riusa_il_file_pubblico_prima_di_generare() -> None:
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if str(request.url).endswith(".png"):
            return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
        return httpx.Response(404)

    store = _store(httpx.MockTransport(handle))
    artwork = store.load_existing(_brief())

    assert artwork is not None
    assert artwork.cached is True
    assert artwork.content_sha256 == PNG_SHA256
    assert len(calls) == 1


def test_store_tratta_il_nosuchkey_400_di_supabase_come_cache_miss() -> None:
    calls = 0

    def handle(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            400,
            json={
                "statusCode": "404",
                "error": "not_found",
                "message": "Object not found",
                "code": "NoSuchKey",
            },
        )

    assert _store(httpx.MockTransport(handle)).load_existing(_brief()) is None
    assert calls == 3


def test_store_non_nasconde_un_generico_errore_400() -> None:
    store = _store(
        httpx.MockTransport(
            lambda _request: httpx.Response(400, json={"message": "bucket non valido"})
        )
    )

    with pytest.raises(ArtworkGenerationFailed) as caught:
        store.load_existing(_brief())

    assert caught.value.reason_code == "storage_read_400"


def test_store_potatura_preventiva_e_upload_immutabile() -> None:
    deleted: list[str] = []
    upload_headers: dict[str, str] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET":
            return httpx.Response(404)
        if path.endswith("/object/list/gazzetta-artwork"):
            rows = [
                {
                    "name": (
                        f"issue-{index:06d}-7808e01e-61bc-4899-88bd-e26ad6d29e54"
                        f"-lead-{'a' * 20}.png"
                    )
                }
                for index in range(1, 11)
            ]
            return httpx.Response(200, json=rows)
        if request.method == "DELETE":
            deleted.extend(json.loads(request.content)["prefixes"])
            return httpx.Response(200, json=[])
        if request.method == "POST" and "/storage/v1/object/gazzetta-artwork/" in path:
            upload_headers.update(request.headers)
            assert request.content == PNG
            return httpx.Response(200, json={"Key": "gazzetta-artwork/editions/file.png"})
        raise AssertionError(f"Richiesta inattesa: {request.method} {request.url}")

    store = _store(httpx.MockTransport(handle), max_stored_images=10)
    generated = WorkerGeneratedImage.model_validate(_worker_payload())
    artwork = store.persist(_brief(), generated)

    assert deleted == [
        "editions/issue-000001-7808e01e-61bc-4899-88bd-e26ad6d29e54"
        f"-lead-{'a' * 20}.png"
    ]
    assert upload_headers["x-upsert"] == "false"
    assert artwork.src.startswith(
        "https://neveran-test.supabase.co/storage/v1/object/public/gazzetta-artwork/"
    )
    assert artwork.cached is False


def test_servizio_non_chiama_workers_ai_quando_supabase_ha_la_cache() -> None:
    class GeneratorCheNonDevePartire:
        def generate(self, _brief: ArtworkBrief) -> WorkerGeneratedImage:
            raise AssertionError("Workers AI non deve essere chiamato")

    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=PNG)
        if str(request.url).endswith(".png")
        else httpx.Response(404)
    )
    service = SupabaseBackedArtworkService(
        generator=GeneratorCheNonDevePartire(),
        store=_store(transport),
    )

    assert service.generate(_brief()).cached is True
