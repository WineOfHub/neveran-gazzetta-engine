from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from neveran_gazzetta.artwork.models import (
    MAX_ARTWORK_BYTES,
    ArtworkBrief,
    GeneratedArtwork,
    WorkerGeneratedImage,
    detect_image_mime,
    extension_for_mime,
)
from neveran_gazzetta.domain.errors import ArtworkGenerationFailed, ConfigurationError

_STORED_NAME = re.compile(
    r"^issue-[0-9]{6,}-[0-9a-f-]+-lead-[a-f0-9]+\.(?:png|jpg|webp)$"
)


class SupabaseArtworkStore:
    """Storage pubblico limitato al bucket artwork e autenticato come worker dedicato."""

    def __init__(
        self,
        *,
        url: str,
        anon_key: str,
        token_provider: Callable[[bool], str],
        bucket: str,
        max_stored_images: int,
        expected_model: str,
        expected_width: int,
        expected_height: int,
        client: httpx.Client | None = None,
    ) -> None:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
        ):
            raise ConfigurationError("SUPABASE_URL deve essere una origine HTTPS")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,62}", bucket):
            raise ConfigurationError("Bucket artwork Supabase non valido")
        if not 10 <= max_stored_images <= 250:
            raise ConfigurationError("La retention artwork deve essere compresa tra 10 e 250")
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._anon_key = anon_key
        self._token_provider = token_provider
        self._bucket = bucket
        self._max_stored_images = max_stored_images
        self._expected_model = expected_model
        self._expected_width = expected_width
        self._expected_height = expected_height
        self._client = client or httpx.Client(timeout=45)

    def load_existing(self, brief: ArtworkBrief) -> GeneratedArtwork | None:
        for extension in ("png", "jpg", "webp"):
            key = self._object_key(brief, extension)
            response = self._public_get(key)
            if self._is_missing_object(response):
                continue
            if response.status_code != 200:
                raise ArtworkGenerationFailed(
                    "Supabase Storage non raggiungibile",
                    reason_code=f"storage_read_{response.status_code}",
                    retriable=response.status_code == 429 or response.status_code >= 500,
                )
            return self._from_stored_bytes(brief, key, response.content, cached=True)
        return None

    @staticmethod
    def _is_missing_object(response: httpx.Response) -> bool:
        if response.status_code == 404:
            return True
        if response.status_code != 400:
            return False
        try:
            payload = response.json()
        except ValueError:
            return False
        return (
            isinstance(payload, dict)
            and str(payload.get("statusCode")) == "404"
            and payload.get("code") == "NoSuchKey"
        )

    def persist(
        self,
        brief: ArtworkBrief,
        generated: WorkerGeneratedImage,
    ) -> GeneratedArtwork:
        image = generated.decoded_bytes()
        extension = extension_for_mime(generated.mime_type)
        key = self._object_key(brief, extension)
        self._prune_for_new_object()
        endpoint = (
            f"{self._origin}/storage/v1/object/"
            f"{quote(self._bucket, safe='')}/{quote(key, safe='/')}"
        )
        response = self._authenticated_request(
            "POST",
            endpoint,
            content=image,
            headers={
                "Content-Type": generated.mime_type,
                "Cache-Control": "max-age=31536000",
                "x-upsert": "false",
            },
        )
        if response.status_code in {400, 409}:
            existing = self.load_existing(brief)
            if existing is not None:
                return existing
        if response.status_code not in {200, 201}:
            raise ArtworkGenerationFailed(
                "Upload artwork su Supabase rifiutato",
                reason_code=f"storage_upload_{response.status_code}",
                retriable=response.status_code == 429 or response.status_code >= 500,
            )
        return GeneratedArtwork(
            src=self._public_url(key),
            object_key=key,
            content_sha256=generated.content_sha256,
            model=generated.model,
            seed=generated.seed,
            width=generated.width,
            height=generated.height,
            cached=False,
        )

    def _prune_for_new_object(self) -> None:
        endpoint = f"{self._origin}/storage/v1/object/list/{quote(self._bucket, safe='')}"
        response = self._authenticated_request(
            "POST",
            endpoint,
            json={
                "prefix": "editions",
                "limit": 1000,
                "offset": 0,
                "sortBy": {"column": "created_at", "order": "asc"},
            },
        )
        if response.status_code != 200:
            raise ArtworkGenerationFailed(
                "Retention artwork non verificabile",
                reason_code=f"storage_list_{response.status_code}",
                retriable=response.status_code == 429 or response.status_code >= 500,
            )
        try:
            rows = response.json()
        except ValueError as exc:
            raise ArtworkGenerationFailed(
                "Lista artwork Supabase non valida",
                reason_code="storage_list_invalid",
            ) from exc
        if not isinstance(rows, list):
            raise ArtworkGenerationFailed(
                "Lista artwork Supabase non valida",
                reason_code="storage_list_invalid",
            )
        paths: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = row.get("name")
            if isinstance(name, str) and _STORED_NAME.fullmatch(name):
                paths.append(f"editions/{name}")
        remove_count = len(paths) - self._max_stored_images + 1
        if remove_count <= 0:
            return
        delete_response = self._authenticated_request(
            "DELETE",
            f"{self._origin}/storage/v1/object/{quote(self._bucket, safe='')}",
            json={"prefixes": paths[:remove_count]},
        )
        if delete_response.status_code not in {200, 204}:
            raise ArtworkGenerationFailed(
                "Retention artwork Supabase fallita",
                reason_code=f"storage_delete_{delete_response.status_code}",
                retriable=(
                    delete_response.status_code == 429
                    or delete_response.status_code >= 500
                ),
            )

    def _authenticated_request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        for refresh in (False, True):
            token = self._token_provider(refresh)
            merged_headers = {
                "apikey": self._anon_key,
                "Authorization": f"Bearer {token}",
                **(headers or {}),
            }
            try:
                response = self._client.request(
                    method,
                    url,
                    headers=merged_headers,
                    **kwargs,
                )
            except httpx.RequestError as exc:
                raise ArtworkGenerationFailed(
                    "Supabase Storage non raggiungibile",
                    reason_code="storage_unavailable",
                    retriable=True,
                ) from exc
            if response.status_code != 401 or refresh:
                return response
        raise ArtworkGenerationFailed(
            "Sessione Supabase Storage non disponibile",
            reason_code="storage_unauthorized",
        )

    def _public_get(self, key: str) -> httpx.Response:
        try:
            response = self._client.get(self._public_url(key))
        except httpx.RequestError as exc:
            raise ArtworkGenerationFailed(
                "Supabase Storage non raggiungibile",
                reason_code="storage_unavailable",
                retriable=True,
            ) from exc
        length = response.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_ARTWORK_BYTES:
            raise ArtworkGenerationFailed(
                "Artwork memorizzato oltre il limite",
                reason_code="stored_image_too_large",
            )
        return response

    def _from_stored_bytes(
        self,
        brief: ArtworkBrief,
        key: str,
        image: bytes,
        *,
        cached: bool,
    ) -> GeneratedArtwork:
        if not image or len(image) > MAX_ARTWORK_BYTES:
            raise ArtworkGenerationFailed(
                "Artwork memorizzato non valido",
                reason_code="stored_image_invalid",
            )
        try:
            expected_extension = extension_for_mime(detect_image_mime(image))
        except (KeyError, ValueError) as exc:
            raise ArtworkGenerationFailed(
                "Formato artwork memorizzato non valido",
                reason_code="stored_image_invalid",
            ) from exc
        if not key.endswith(f".{expected_extension}"):
            raise ArtworkGenerationFailed(
                "Estensione artwork memorizzato non coerente",
                reason_code="stored_image_mime_mismatch",
            )
        return GeneratedArtwork(
            src=self._public_url(key),
            object_key=key,
            content_sha256=hashlib.sha256(image).hexdigest(),
            model=self._expected_model,
            seed=brief.seed,
            width=self._expected_width,
            height=self._expected_height,
            cached=cached,
        )

    def _object_key(self, brief: ArtworkBrief, extension: str) -> str:
        return (
            f"editions/issue-{brief.issue_number:06d}-{brief.job_id}"
            f"-lead-{brief.prompt_sha256[:20]}.{extension}"
        )

    def _public_url(self, key: str) -> str:
        return (
            f"{self._origin}/storage/v1/object/public/"
            f"{quote(self._bucket, safe='')}/{quote(key, safe='/')}"
        )
