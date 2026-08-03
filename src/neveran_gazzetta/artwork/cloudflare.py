from __future__ import annotations

from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from neveran_gazzetta.artwork.models import ArtworkBrief, WorkerGeneratedImage
from neveran_gazzetta.domain.errors import ArtworkGenerationFailed, ConfigurationError


class CloudflareArtworkClient:
    """Adapter stretto verso il Worker stateless che possiede soltanto il binding AI."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        expected_model: str,
        expected_width: int,
        expected_height: int,
        timeout_seconds: int,
        max_retries: int = 1,
        client: httpx.Client | None = None,
    ) -> None:
        endpoint = urlsplit(base_url)
        if endpoint.scheme != "https" or not endpoint.hostname:
            raise ConfigurationError("GAZZETTA_IMAGE_WORKER_URL deve essere HTTPS")
        if len(token) < 32:
            raise ConfigurationError("GAZZETTA_IMAGE_WORKER_TOKEN deve avere almeno 32 caratteri")
        if max_retries != 1:
            raise ConfigurationError("Il client artwork ammette esattamente un retry")
        self._endpoint = f"{base_url.rstrip('/')}/v1/generate"
        self._token = token
        self._expected_model = expected_model
        self._expected_width = expected_width
        self._expected_height = expected_height
        self._max_retries = max_retries
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def generate(self, brief: ArtworkBrief) -> WorkerGeneratedImage:
        response: httpx.Response | None = None
        last_error: httpx.RequestError | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.post(
                    self._endpoint,
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "jobId": str(brief.job_id),
                        "issueNumber": brief.issue_number,
                        "prompt": brief.prompt,
                        "promptSha256": brief.prompt_sha256,
                        "seed": brief.seed,
                    },
                )
            except httpx.RequestError as exc:
                last_error = exc
                if attempt < self._max_retries:
                    continue
                raise ArtworkGenerationFailed(
                    "Worker artwork non raggiungibile",
                    reason_code="worker_unavailable",
                    retriable=True,
                ) from exc
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < self._max_retries:
                    continue
                raise ArtworkGenerationFailed(
                    "Provider immagini temporaneamente non disponibile",
                    reason_code="provider_unavailable",
                    retriable=True,
                )
            if response.status_code != 200:
                raise ArtworkGenerationFailed(
                    "Worker artwork ha rifiutato la richiesta",
                    reason_code=f"worker_rejected_{response.status_code}",
                )
            break
        if response is None:
            raise ArtworkGenerationFailed(
                "Worker artwork senza risposta",
                reason_code="worker_unavailable",
                retriable=True,
            ) from last_error
        try:
            artwork = WorkerGeneratedImage.model_validate(response.json())
            artwork.decoded_bytes()
        except (ValueError, TypeError, ValidationError) as exc:
            raise ArtworkGenerationFailed(
                "Risposta artwork non conforme al contratto",
                reason_code="invalid_worker_response",
            ) from exc
        if (
            artwork.model != self._expected_model
            or artwork.width != self._expected_width
            or artwork.height != self._expected_height
            or artwork.seed != brief.seed
        ):
            raise ArtworkGenerationFailed(
                "Parametri dell'artwork diversi dal profilo installato",
                reason_code="artwork_profile_mismatch",
            )
        return artwork
