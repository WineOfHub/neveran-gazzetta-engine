from __future__ import annotations

import socket
import threading
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from neveran_gazzetta import __version__
from neveran_gazzetta.application.contracts import (
    ControlPlane,
    JobLease,
    Pipeline,
    ValidationStatus,
)
from neveran_gazzetta.domain.errors import (
    GazzettaError,
    GenerationQueueEmpty,
    InvalidGeneration,
    ProviderQuota,
)
from neveran_gazzetta.telemetry import NullTelemetry, TelemetrySink

# Sotto questa profondità la coda emette un evento di telemetria (Ticket 06):
# nessun allarme attivo, solo un gancio pronto per un futuro collegamento a
# neveran-monitor.
_LOW_QUEUE_DEPTH_THRESHOLD = 2


class TickStatus(StrEnum):
    IDLE = "idle"
    PUBLISHED = "published"
    MATERIALIZED = "materialized"
    FAILED = "failed"


@dataclass(frozen=True)
class TickResult:
    status: TickStatus
    job_id: UUID | None = None
    edition: dict[str, object] | None = None
    error_code: str | None = None


class LeaseRenewer:
    def __init__(
        self,
        control: ControlPlane,
        lease: JobLease,
        worker_id: str,
        interval_seconds: float,
    ) -> None:
        self._control = control
        self._lease = lease
        self._worker_id = worker_id
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._error: Exception | None = None
        self._thread = threading.Thread(target=self._run, daemon=True, name="gazzetta-lease")

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._control.renew_lease(self._lease.job_id, self._worker_id)
            except Exception as exc:  # eccezione trasferita al thread principale
                self._error = exc
                self._stop.set()

    def __enter__(self) -> LeaseRenewer:
        self._thread.start()
        return self

    def ensure_healthy(self) -> None:
        if self._error is not None:
            raise self._error

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        self._thread.join(timeout=max(self._interval, 1.0))


class GazzettaWorker:
    def __init__(
        self,
        *,
        worker_id: str,
        control: ControlPlane,
        pipeline: Pipeline,
        lease_renew_seconds: float,
        models: dict[str, str],
        hostname: str | None = None,
        telemetry: TelemetrySink | None = None,
        retention_days: int = 90,
        storyline_compaction_days: int = 180,
        recurring_inactive_issues: int = 50,
        nonrecurring_keep_issues: int = 20,
    ) -> None:
        self._worker_id = worker_id
        self._control = control
        self._pipeline = pipeline
        self._lease_renew_seconds = lease_renew_seconds
        self._models = models
        self._hostname = hostname or socket.gethostname()
        self._telemetry = telemetry or NullTelemetry()
        self._retention_days = retention_days
        self._storyline_compaction_days = storyline_compaction_days
        self._recurring_inactive_issues = recurring_inactive_issues
        self._nonrecurring_keep_issues = nonrecurring_keep_issues
        self._tick_lock = threading.Lock()

    def _heartbeat(self, status: str, diagnostics: dict[str, object] | None = None) -> None:
        self._control.heartbeat(
            worker_id=self._worker_id,
            status=status,
            version=__version__,
            hostname=self._hostname,
            models=self._models,
            diagnostics=diagnostics or {},
        )
        self._telemetry.emit(
            "heartbeat",
            status_code=200,
            metadata={"status": status, "worker_version": __version__},
        )

    def tick(self) -> TickResult:
        if not self._tick_lock.acquire(blocking=False):
            self._telemetry.emit(
                "scheduler_tick_skipped",
                status_code=409,
                metadata={"status": "tick_in_progress"},
            )
            return TickResult(status=TickStatus.IDLE, error_code="tick_in_progress")
        try:
            return self._tick_serialized()
        finally:
            self._tick_lock.release()

    def _tick_serialized(self) -> TickResult:
        self._telemetry.emit("scheduler_tick", status_code=200)
        self._heartbeat("online")
        self._check_queue_depth()

        try:
            published = self._control.publish_next(self._worker_id)
        except GenerationQueueEmpty:
            return self._emergency_fallback()
        except Exception as exc:
            return self._publish_failure(exc)

        if published is not None:
            self._telemetry.emit(
                "edition_published",
                status_code=200,
                metadata={"source": "queue"},
            )
            return TickResult(status=TickStatus.PUBLISHED, edition=published)

        # Nessuna pubblicazione dovuta in questo momento: prova a rabboccare la coda
        # di edizioni pronte (al massimo una generazione per tick — la cadenza dei
        # tick stessa fa da pacing fra chiamate Groq successive).
        lease = self._control.lease_next(self._worker_id)
        if lease is None:
            self._telemetry.emit("lease_idle", status_code=204)
            return TickResult(status=TickStatus.IDLE)
        return self._generate(lease)

    def _check_queue_depth(self) -> None:
        with suppress(Exception):
            status = self._control.queue_status()
            if status.depth < _LOW_QUEUE_DEPTH_THRESHOLD:
                self._telemetry.emit(
                    "queue_depth_low",
                    status_code=200,
                    metadata={
                        "queue_depth": status.depth,
                        "queue_depth_target": status.depth_target,
                    },
                )

    def _emergency_fallback(self) -> TickResult:
        """La pubblicazione è dovuta ma la coda è vuota: genera un'edizione subito
        (stesso percorso di codice della generazione ordinaria) e ripubblica."""
        self._telemetry.emit("queue_empty_at_due_slot", status_code=200)
        lease = self._control.lease_next(self._worker_id)
        if lease is None:
            self._telemetry.emit("queue_empty_no_job_available", status_code=503)
            return TickResult(status=TickStatus.FAILED, error_code=GenerationQueueEmpty.code)

        generated = self._generate(lease)
        if generated.status != TickStatus.MATERIALIZED:
            return generated

        try:
            published = self._control.publish_next(self._worker_id)
        except GenerationQueueEmpty:
            self._telemetry.emit("queue_still_empty_after_emergency", status_code=503)
            return TickResult(
                status=TickStatus.FAILED,
                job_id=generated.job_id,
                error_code=GenerationQueueEmpty.code,
            )
        except Exception as exc:
            return self._publish_failure(exc, job_id=generated.job_id)

        if published is None:
            # next_due_at era già dovuto quando siamo entrati: non dovrebbe succedere,
            # ma non blocchiamo il worker — la coda è comunque stata rabboccata.
            return generated

        self._telemetry.emit(
            "edition_published",
            status_code=200,
            metadata={"source": "emergency_fallback"},
        )
        return TickResult(
            status=TickStatus.PUBLISHED, job_id=generated.job_id, edition=published
        )

    def _publish_failure(self, exc: Exception, *, job_id: UUID | None = None) -> TickResult:
        code = exc.code if isinstance(exc, GazzettaError) else "unexpected_error"
        self._telemetry.emit(
            "publish_failed",
            status_code=503,
            error_message=str(exc),
            metadata={"error_code": code},
        )
        return TickResult(status=TickStatus.FAILED, job_id=job_id, error_code=code)

    def _generate(self, lease: JobLease) -> TickResult:
        trace_id = str(lease.job_id)
        self._telemetry.emit(
            "lease_acquired",
            status_code=200,
            trace_id=trace_id,
            metadata={
                "job_id": trace_id,
                "attempt": lease.attempt_number,
                "schedule_slot": lease.schedule_slot.isoformat(),
            },
        )
        self._heartbeat("busy", {"job_id": str(lease.job_id)})

        try:
            with LeaseRenewer(
                self._control,
                lease,
                self._worker_id,
                self._lease_renew_seconds,
            ) as renewer:
                run = self._pipeline.execute(lease)
                self._telemetry.emit(
                    "run_validated",
                    status_code=200,
                    duration_ms=run.duration_ms,
                    provider="groq",
                    trace_id=trace_id,
                    units={
                        "type": "tokens",
                        "input": run.token_input,
                        "output": run.token_output,
                    },
                    metadata={
                        "corpus_release_id": run.corpus_release_id,
                        "groq_requests": run.groq_requests,
                        "models": run.models,
                        "policy_hash": run.policy_hash,
                        "policy_version": lease.policy_version,
                        "prompt_hashes": run.prompt_hashes,
                        "prompt_versions": run.prompt_versions,
                        "rate_limits": run.rate_limits,
                        "token_input": run.token_input,
                        "token_output": run.token_output,
                    },
                )
                renewer.ensure_healthy()
                if run.validation_status != ValidationStatus.PASSED:
                    raise InvalidGeneration("Il run non ha superato la validazione")
                run_id = self._control.submit_run(lease, self._worker_id, run)
                renewer.ensure_healthy()
                edition = self._control.materialize(lease.job_id, self._worker_id, run_id)
                self._telemetry.emit(
                    "edition_materialized",
                    status_code=200,
                    trace_id=trace_id,
                    metadata={"job_id": trace_id},
                )
                with suppress(Exception):
                    archived = self._control.maintain_retention(
                        self._retention_days,
                        self._storyline_compaction_days,
                        self._recurring_inactive_issues,
                        self._nonrecurring_keep_issues,
                    )
                    self._telemetry.emit(
                        "retention_completed",
                        status_code=200,
                        trace_id=trace_id,
                        metadata={"status": f"archived:{archived}"},
                    )
            self._heartbeat("online", {"last_job_id": str(lease.job_id)})
            return TickResult(
                status=TickStatus.MATERIALIZED,
                job_id=lease.job_id,
                edition=edition,
            )
        except Exception as exc:
            code = exc.code if isinstance(exc, GazzettaError) else "unexpected_error"
            retryable = exc.retriable if isinstance(exc, GazzettaError) else False
            self._telemetry.emit(
                "job_failed",
                status_code=503 if retryable else 422,
                trace_id=str(lease.job_id),
                error_message=str(exc),
                metadata={
                    "attempt": lease.attempt_number,
                    "error_code": code,
                    "job_id": str(lease.job_id),
                },
            )
            available_at = None
            if isinstance(exc, ProviderQuota) and exc.retry_after_seconds is not None:
                available_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
            with suppress(Exception):
                self._control.fail_job(
                    job_id=lease.job_id,
                    worker_id=self._worker_id,
                    error_class=code,
                    error_message=str(exc)[:1000],
                    retryable=retryable,
                    available_at=available_at,
                )
                # La materializzazione potrebbe essere riuscita ma la risposta essersi
                # persa. Lo stato autorevole resta Supabase e il prossimo tick riconcilia
                # il job.
            with suppress(Exception):
                self._heartbeat("degraded", {"error_code": code})
            return TickResult(status=TickStatus.FAILED, job_id=lease.job_id, error_code=code)
