from __future__ import annotations

import threading
from datetime import UTC, datetime
from uuid import UUID, uuid4

from neveran_gazzetta.application.contracts import JobLease, PreparedRun, QueueStatus
from neveran_gazzetta.domain.errors import GenerationQueueEmpty
from neveran_gazzetta.telemetry import TelemetrySink
from neveran_gazzetta.worker.runner import GazzettaWorker, TickStatus


class RecordingTelemetry(TelemetrySink):
    def __init__(self) -> None:
        self.events: list[str] = []

    def emit(self, event: str, **_kwargs: object) -> None:
        self.events.append(event)


class Control:
    def __init__(self, lease: JobLease | None) -> None:
        self.lease = lease
        self.heartbeats: list[str] = []
        self.failed: list[dict[str, object]] = []
        self.materialized = False
        self.fail_job_raises = False
        self.publish_next_responses: list[object] = [None]
        self.publish_next_calls = 0
        self.queue = QueueStatus(depth=4, depth_target=4)

    def queue_status(self) -> QueueStatus:
        return self.queue

    def heartbeat(self, **kwargs) -> None:
        self.heartbeats.append(kwargs["status"])

    def lease_next(self, _worker_id: str) -> JobLease | None:
        return self.lease

    def renew_lease(self, _job_id: UUID, _worker_id: str) -> None:
        return None

    def submit_run(self, _lease, _worker_id, _run) -> UUID:
        return uuid4()

    def materialize(self, _job_id, _worker_id, _run_id) -> dict[str, object]:
        self.materialized = True
        return {"schemaVersion": 1}

    def publish_next(self, _worker_id: str) -> dict[str, object] | None:
        index = min(self.publish_next_calls, len(self.publish_next_responses) - 1)
        response = self.publish_next_responses[index]
        self.publish_next_calls += 1
        if isinstance(response, Exception):
            raise response
        return response

    def fail_job(self, **kwargs) -> None:
        if self.fail_job_raises:
            raise RuntimeError("stato già concluso")
        self.failed.append(kwargs)

    def maintain_retention(self, *_limits: int) -> int:
        return 0


class Pipeline:
    def __init__(self, status: str = "passed") -> None:
        self.status = status

    def execute(self, _lease: JobLease) -> PreparedRun:
        return PreparedRun(
            phase="publishing",
            validation_status=self.status,
            corpus_release_id="release-a",
            policy_hash="a" * 64,
            prompt_versions={
                "planner": "v1", "writer": "v1", "verifier": "v1", "repair": "v1",
            },
            prompt_hashes={key: "a" * 64 for key in ("planner", "writer", "verifier", "repair")},
            models={"planner": "model", "writer": "model", "verifier": "model"},
            token_input=0,
            token_output=0,
            groq_requests=0,
            snapshot={"schemaVersion": 1},
            content_hash="a" * 64,
        )


class BlockingPipeline(Pipeline):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def execute(self, lease: JobLease) -> PreparedRun:
        self.started.set()
        assert self.release.wait(timeout=2)
        return super().execute(lease)


def _lease() -> JobLease:
    return JobLease(
        job_id=uuid4(),
        schedule_slot=datetime.now(UTC),
        attempt_number=1,
        policy_version="v1",
    )


def _worker(
    control: Control, pipeline: Pipeline, *, telemetry: TelemetrySink | None = None
) -> GazzettaWorker:
    return GazzettaWorker(
        worker_id="worker-test",
        control=control,
        pipeline=pipeline,
        lease_renew_seconds=60,
        models={},
        hostname="test",
        telemetry=telemetry,
    )


def test_tick_senza_pubblicazione_dovuta_rabbocca_la_coda() -> None:
    control = Control(_lease())

    result = _worker(control, Pipeline()).tick()

    assert result.status == TickStatus.MATERIALIZED
    assert control.materialized
    assert not control.failed


def test_tick_pubblica_dalla_coda_senza_generare() -> None:
    control = Control(_lease())
    control.publish_next_responses = [{"schemaVersion": 1}]

    result = _worker(control, Pipeline()).tick()

    assert result.status == TickStatus.PUBLISHED
    assert not control.materialized


def test_tick_senza_job_e_senza_pubblicazione_resta_idle() -> None:
    control = Control(None)

    result = _worker(control, Pipeline()).tick()

    assert result.status == TickStatus.IDLE
    assert control.heartbeats == ["online"]


def test_coda_vuota_alla_scadenza_attiva_il_fallback_di_emergenza() -> None:
    control = Control(_lease())
    control.publish_next_responses = [
        GenerationQueueEmpty("coda vuota"),
        {"schemaVersion": 1},
    ]

    result = _worker(control, Pipeline()).tick()

    assert result.status == TickStatus.PUBLISHED
    assert control.materialized
    assert control.publish_next_calls == 2


def test_fallback_di_emergenza_senza_job_disponibile_fallisce() -> None:
    control = Control(None)
    control.publish_next_responses = [GenerationQueueEmpty("coda vuota")]

    result = _worker(control, Pipeline()).tick()

    assert result.status == TickStatus.FAILED
    assert result.error_code == "queue_empty"


def test_generazione_rifiutata_non_materializza_e_programma_retry_limitato() -> None:
    control = Control(_lease())

    result = _worker(control, Pipeline("rejected")).tick()

    assert result.status == TickStatus.FAILED
    assert result.error_code == "invalid_generation"
    assert not control.materialized
    assert control.failed[0]["retryable"] is True


def test_errore_di_rete_dopo_materialize_non_nasconde_quello_originale() -> None:
    control = Control(_lease())
    control.fail_job_raises = True

    def lost_response(_job_id, _worker_id, _run_id):
        control.materialized = True
        raise RuntimeError("risposta persa")

    control.materialize = lost_response  # type: ignore[method-assign]
    result = _worker(control, Pipeline()).tick()

    assert result.status == TickStatus.FAILED
    assert result.error_code == "unexpected_error"
    assert control.materialized


def test_due_tick_nello_stesso_processo_non_corrono_in_parallelo() -> None:
    control = Control(_lease())
    pipeline = BlockingPipeline()
    worker = _worker(control, pipeline)
    first_results = []
    first = threading.Thread(target=lambda: first_results.append(worker.tick()))
    first.start()
    assert pipeline.started.wait(timeout=1)

    second = worker.tick()
    pipeline.release.set()
    first.join(timeout=2)

    assert second.status == TickStatus.IDLE
    assert second.error_code == "tick_in_progress"
    assert first_results[0].status == TickStatus.MATERIALIZED


def test_coda_sotto_soglia_emette_evento_di_telemetria() -> None:
    control = Control(_lease())
    control.queue = QueueStatus(depth=1, depth_target=4)
    telemetry = RecordingTelemetry()

    _worker(control, Pipeline(), telemetry=telemetry).tick()

    assert "queue_depth_low" in telemetry.events


def test_coda_sopra_soglia_non_emette_evento() -> None:
    control = Control(_lease())
    control.queue = QueueStatus(depth=3, depth_target=4)
    telemetry = RecordingTelemetry()

    _worker(control, Pipeline(), telemetry=telemetry).tick()

    assert "queue_depth_low" not in telemetry.events


def test_errore_nella_lettura_della_coda_non_blocca_il_tick() -> None:
    control = Control(_lease())

    def raising_queue_status() -> QueueStatus:
        raise RuntimeError("supabase giù")

    control.queue_status = raising_queue_status  # type: ignore[method-assign]
    result = _worker(control, Pipeline()).tick()

    assert result.status == TickStatus.MATERIALIZED
