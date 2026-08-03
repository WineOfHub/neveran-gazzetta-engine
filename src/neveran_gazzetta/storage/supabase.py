from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Any
from uuid import UUID

import httpx

from neveran_gazzetta.application.contracts import JobLease, PreparedRun, QueueStatus
from neveran_gazzetta.application.editorial_state import EditorialState
from neveran_gazzetta.domain.errors import (
    ConfigurationError,
    GenerationQueueEmpty,
    ProviderUnavailable,
    PublicationConflict,
)


class SupabaseRpcClient:
    """Control plane limitato alle RPC Gazzetta; non espone accesso alle tabelle."""

    def __init__(
        self,
        *,
        url: str,
        anon_key: str,
        email: str,
        password: str,
        client: httpx.Client | None = None,
    ) -> None:
        if not all((url, anon_key, email, password)):
            raise ConfigurationError("Credenziali Supabase worker incomplete")
        self._url = url.rstrip("/")
        self._anon_key = anon_key
        self._email = email
        self._password = password
        self._client = client or httpx.Client(timeout=30)
        self._access_token: str | None = None
        self._auth_lock = Lock()

    def _authenticate(self) -> str:
        with self._auth_lock:
            if self._access_token:
                return self._access_token
            try:
                response = self._client.post(
                    f"{self._url}/auth/v1/token?grant_type=password",
                    headers={"apikey": self._anon_key},
                    json={"email": self._email, "password": self._password},
                )
                response.raise_for_status()
                token = response.json()["access_token"]
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                raise ProviderUnavailable("Autenticazione Supabase non disponibile") from exc
            if not isinstance(token, str) or not token:
                raise ProviderUnavailable("Token Supabase assente")
            self._access_token = token
            return token

    def access_token(self, refresh: bool = False) -> str:
        """Condivide la sessione del worker con adapter Supabase a privilegi minimi."""

        if refresh:
            with self._auth_lock:
                self._access_token = None
        return self._authenticate()

    def _rpc(self, name: str, payload: dict[str, object]) -> Any:
        token = self._authenticate()
        try:
            response = self._client.post(
                f"{self._url}/rest/v1/rpc/{name}",
                headers={
                    "apikey": self._anon_key,
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if response.status_code == 401:
                self._access_token = None
                raise ProviderUnavailable("Sessione Supabase scaduta")
            if response.status_code in {400, 403, 409}:
                detail = str(response.json().get("message", "rpc_rejected"))[:200]
                raise PublicationConflict(detail)
            response.raise_for_status()
            return response.json() if response.content else None
        except (ProviderUnavailable, PublicationConflict):
            raise
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            raise ProviderUnavailable(f"RPC Supabase {name} non disponibile") from exc

    def heartbeat(
        self,
        *,
        worker_id: str,
        status: str,
        version: str,
        hostname: str,
        models: dict[str, str],
        diagnostics: dict[str, object],
    ) -> None:
        self._rpc(
            "gazzetta_worker_heartbeat",
            {
                "p_worker_id": worker_id,
                "p_status": status,
                "p_version": version,
                "p_hostname": hostname,
                "p_current_models": models,
                "p_diagnostics": diagnostics,
            },
        )

    def lease_next(self, worker_id: str) -> JobLease | None:
        rows = self._rpc("lease_next_gazzetta_job", {"p_worker_id": worker_id}) or []
        if not rows:
            return None
        if not isinstance(rows, list) or len(rows) != 1:
            raise ProviderUnavailable("Risposta lease Supabase invalida")
        row = rows[0]
        return JobLease(
            job_id=row["job_id"],
            schedule_slot=row["schedule_slot"],
            attempt_number=row["attempt_number"],
            policy_version=row["policy_version"],
        )

    def renew_lease(self, job_id: UUID, worker_id: str) -> None:
        self._rpc(
            "renew_gazzetta_job_lease",
            {"p_job_id": str(job_id), "p_worker_id": worker_id},
        )

    def submit_run(self, lease: JobLease, worker_id: str, run: PreparedRun) -> UUID:
        payload: dict[str, object] = {
            "p_job_id": str(lease.job_id),
            "p_worker_id": worker_id,
            "p_phase": run.phase,
            "p_validation_status": run.validation_status.value,
            "p_corpus_release_id": run.corpus_release_id,
            "p_policy_hash": run.policy_hash,
            "p_prompt_versions": run.prompt_versions,
            "p_prompt_hashes": run.prompt_hashes,
            "p_models": run.models,
            "p_token_input": run.token_input,
            "p_token_output": run.token_output,
            "p_groq_requests": run.groq_requests,
            "p_rate_limits": run.rate_limits,
            "p_validation_report": run.validation_report,
            "p_snapshot": run.snapshot,
            "p_events": list(run.events),
            "p_storyline_updates": list(run.storyline_updates),
            "p_entity_updates": list(run.entity_updates),
            "p_content_hash": run.content_hash,
            "p_duration_ms": run.duration_ms,
        }
        try:
            result = self._rpc("submit_gazzetta_run", payload)
        except ProviderUnavailable:
            result = self._rpc("submit_gazzetta_run", payload)
        if not isinstance(result, str):
            raise ProviderUnavailable("ID run Supabase non valido")
        return UUID(result)

    def materialize(self, job_id: UUID, worker_id: str, run_id: UUID) -> dict[str, object]:
        payload: dict[str, object] = {
            "p_job_id": str(job_id),
            "p_worker_id": worker_id,
            "p_run_id": str(run_id),
        }
        try:
            result = self._rpc("materialize_gazzetta_edition", payload)
        except ProviderUnavailable:
            result = self._rpc("materialize_gazzetta_edition", payload)
        if not isinstance(result, dict):
            raise ProviderUnavailable("Snapshot materializzato non valido")
        return result

    def publish_next(self, worker_id: str) -> dict[str, object] | None:
        try:
            result = self._rpc("publish_next_gazzetta_edition", {"p_worker_id": worker_id})
        except PublicationConflict as exc:
            # La RPC (in neveran-main-app/supabase/migrations/
            # 20260803150000_gazzetta_generation_queue.sql) segnala la coda vuota con
            # `raise exception 'queue_empty'`: PostgREST la trasforma in un 400 il cui
            # `message` è esattamente quel testo. Un cambio del messaggio SQL in quel
            # repo romperebbe silenziosamente questo confronto.
            if str(exc) == GenerationQueueEmpty.code:
                raise GenerationQueueEmpty(
                    "Slot di pubblicazione dovuto ma la coda è vuota"
                ) from exc
            raise
        if result is None:
            return None
        if not isinstance(result, dict):
            raise ProviderUnavailable("Snapshot pubblicato non valido")
        return result

    def queue_status(self) -> QueueStatus:
        result = self._rpc("gazzetta_get_queue_status", {})
        if not isinstance(result, dict):
            raise ProviderUnavailable("Stato coda Supabase non valido")
        return QueueStatus(depth=result["queueDepth"], depth_target=result["queueDepthTarget"])

    def fail_job(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        error_class: str,
        error_message: str,
        retryable: bool,
        available_at: datetime | None = None,
    ) -> None:
        self._rpc(
            "fail_gazzetta_job",
            {
                "p_job_id": str(job_id),
                "p_worker_id": worker_id,
                "p_error_class": error_class,
                "p_error_message": error_message[:1000],
                "p_retryable": retryable,
                "p_available_at": available_at.isoformat() if available_at else None,
            },
        )

    def get_editorial_state(self) -> EditorialState:
        result = self._rpc("gazzetta_get_editorial_context", {})
        if not isinstance(result, dict):
            raise ProviderUnavailable("Contesto editoriale Supabase non valido")
        return EditorialState.model_validate(result)

    def get_run(self, run_id: UUID) -> dict[str, object]:
        result = self._rpc("gazzetta_get_run", {"p_run_id": str(run_id)})
        if not isinstance(result, dict):
            raise ProviderUnavailable("Run Supabase non valido")
        return result

    def maintain_retention(
        self,
        detailed_days: int,
        storyline_compaction_days: int,
        recurring_inactive_issues: int,
        nonrecurring_keep_issues: int,
    ) -> int:
        result = self._rpc(
            "gazzetta_maintain_retention",
            {
                "p_detailed_days": detailed_days,
                "p_storyline_compaction_days": storyline_compaction_days,
                "p_recurring_inactive_issues": recurring_inactive_issues,
                "p_nonrecurring_keep_issues": nonrecurring_keep_issues,
            },
        )
        if not isinstance(result, int):
            raise ProviderUnavailable("Risultato retention Supabase non valido")
        return result
